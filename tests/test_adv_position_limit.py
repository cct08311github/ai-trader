"""Tests for ADV-based position limit (Issue #286).

Covers:
- fetch_avg_daily_volume_twd: correct averaging, missing table, insufficient data
- _apply_level_caps with ADV constraint: caps are applied as min(nav_cap, adv_cap)
- calculate_position_qty: ADV params flow through to final qty
- risk_engine default_limits: max_adv_pct present
"""
from __future__ import annotations

import sqlite3

import pytest

from openclaw.position_sizing import (
    _apply_level_caps,
    calculate_position_qty,
    fetch_avg_daily_volume_twd,
    PositionLevelLimits,
)
from openclaw.risk_engine import default_limits


# ──────────────────────────────────────────────
# DB helper
# ──────────────────────────────────────────────

def _eod_db(rows: list[tuple]) -> sqlite3.Connection:
    """In-memory DB with eod_prices (trade_date, symbol, close, volume)."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE eod_prices (
            trade_date TEXT,
            symbol     TEXT,
            close      REAL,
            volume     REAL
        )"""
    )
    conn.executemany(
        "INSERT INTO eod_prices (trade_date, symbol, close, volume) VALUES (?,?,?,?)",
        rows,
    )
    conn.commit()
    return conn


# ──────────────────────────────────────────────
# fetch_avg_daily_volume_twd
# ──────────────────────────────────────────────

class TestFetchAvgDailyVolumeTwd:
    def test_correct_average(self):
        rows = [
            ("2026-03-01", "2330", 1000.0, 10_000),  # TWD = 10_000_000
            ("2026-03-02", "2330", 1000.0, 20_000),  # TWD = 20_000_000
        ]
        conn = _eod_db(rows)
        result = fetch_avg_daily_volume_twd(conn, "2330", days=20)
        assert result == pytest.approx(15_000_000.0)

    def test_respects_days_limit(self):
        rows = [
            ("2026-01-01", "2330", 100.0, 1000),   # old row, outside window
            ("2026-03-01", "2330", 1000.0, 500),
            ("2026-03-02", "2330", 1000.0, 500),
        ]
        conn = _eod_db(rows)
        # days=2 → only 2 most recent rows
        result = fetch_avg_daily_volume_twd(conn, "2330", days=2)
        assert result == pytest.approx(500 * 1000.0)

    def test_returns_none_when_no_data(self):
        conn = _eod_db([])
        assert fetch_avg_daily_volume_twd(conn, "9999") is None

    def test_returns_none_when_table_missing(self):
        conn = sqlite3.connect(":memory:")
        assert fetch_avg_daily_volume_twd(conn, "2330") is None

    def test_symbol_filtered(self):
        rows = [
            ("2026-03-01", "2330", 1000.0, 10_000),
            ("2026-03-01", "2317", 500.0, 5_000),
        ]
        conn = _eod_db(rows)
        r2330 = fetch_avg_daily_volume_twd(conn, "2330")
        r2317 = fetch_avg_daily_volume_twd(conn, "2317")
        assert r2330 == pytest.approx(10_000_000.0)
        assert r2317 == pytest.approx(2_500_000.0)

    def test_excludes_zero_volume_rows(self):
        rows = [
            ("2026-03-01", "2330", 1000.0, 0),       # excluded
            ("2026-03-02", "2330", 1000.0, 10_000),
        ]
        conn = _eod_db(rows)
        result = fetch_avg_daily_volume_twd(conn, "2330")
        assert result == pytest.approx(10_000_000.0)


# ──────────────────────────────────────────────
# _apply_level_caps with ADV constraint
# ──────────────────────────────────────────────

class TestApplyLevelCapsAdv:
    def _level_limits(self, notional_pct=0.30) -> PositionLevelLimits:
        return PositionLevelLimits(
            max_risk_per_trade_pct_nav=0.005,
            max_position_notional_pct_nav=notional_pct,
        )

    def test_adv_cap_binds_when_tighter_than_nav_cap(self):
        # nav=10M, notional_pct=30% → nav_cap=3M notional
        # adv=5M, max_adv_pct=10% → adv_cap=500K notional
        # entry_price=100 → qty from nav_cap=30000; qty from adv_cap=5000
        qty = _apply_level_caps(
            qty=50_000,
            entry_price=100.0,
            nav=10_000_000.0,
            level_limits=self._level_limits(0.30),
            avg_daily_volume_twd=5_000_000.0,
            max_adv_pct=0.10,
        )
        assert qty == 5_000   # adv cap binds

    def test_nav_cap_binds_when_tighter(self):
        # nav=1M, notional_pct=5% → nav_cap=50K notional
        # adv=10M, max_adv_pct=10% → adv_cap=1M notional
        # entry_price=100 → qty from nav_cap=500; qty from adv_cap=10000
        qty = _apply_level_caps(
            qty=50_000,
            entry_price=100.0,
            nav=1_000_000.0,
            level_limits=self._level_limits(0.05),
            avg_daily_volume_twd=10_000_000.0,
            max_adv_pct=0.10,
        )
        assert qty == 500   # nav cap binds

    def test_no_adv_data_uses_nav_cap_only(self):
        qty = _apply_level_caps(
            qty=50_000,
            entry_price=100.0,
            nav=1_000_000.0,
            level_limits=self._level_limits(0.05),
            avg_daily_volume_twd=None,
        )
        assert qty == 500

    def test_no_level_limits_adv_still_applied(self):
        # Without level_limits, ADV cap should still limit qty
        qty = _apply_level_caps(
            qty=50_000,
            entry_price=100.0,
            nav=10_000_000.0,
            level_limits=None,
            avg_daily_volume_twd=500_000.0,
            max_adv_pct=0.10,
        )
        assert qty == 500   # 500K * 10% / 100 = 500

    def test_zero_adv_is_ignored(self):
        qty = _apply_level_caps(
            qty=100,
            entry_price=100.0,
            nav=1_000_000.0,
            level_limits=self._level_limits(0.10),
            avg_daily_volume_twd=0.0,
            max_adv_pct=0.10,
        )
        assert qty == 100   # adv=0 ignored, nav cap = 10000, qty unchanged


# ──────────────────────────────────────────────
# calculate_position_qty end-to-end
# ──────────────────────────────────────────────

class TestCalculatePositionQtyAdv:
    def test_adv_cap_flows_through_fixed_fractional(self):
        # Large nav but tiny ADV → position should be tiny
        qty = calculate_position_qty(
            nav=100_000_000.0,
            entry_price=100.0,
            base_risk_pct=0.01,
            stop_price=95.0,
            avg_daily_volume_twd=100_000.0,  # 100K TWD daily volume
            max_adv_pct=0.10,                # cap = 10K TWD = 100 shares
        )
        assert qty <= 100

    def test_no_adv_unchanged_behavior(self):
        # Without ADV, result should match original (no regression)
        qty_with_none = calculate_position_qty(
            nav=1_000_000.0,
            entry_price=100.0,
            base_risk_pct=0.005,
            stop_price=98.0,
            avg_daily_volume_twd=None,
        )
        qty_without_param = calculate_position_qty(
            nav=1_000_000.0,
            entry_price=100.0,
            base_risk_pct=0.005,
            stop_price=98.0,
        )
        assert qty_with_none == qty_without_param


# ──────────────────────────────────────────────
# default_limits
# ──────────────────────────────────────────────

class TestDefaultLimits:
    def test_max_adv_pct_present(self):
        limits = default_limits()
        assert "max_adv_pct" in limits
        assert limits["max_adv_pct"] == pytest.approx(0.10)

    def test_adv_lookback_days_present(self):
        limits = default_limits()
        assert "adv_lookback_days" in limits
        assert int(limits["adv_lookback_days"]) == 20
