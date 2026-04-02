"""Tests for eod_exit_check — 盤後 exit signal fallback."""
from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

from openclaw.eod_exit_check import run_eod_exit_check
from openclaw.signal_logic import SignalParams


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.executescript("""
        CREATE TABLE positions (
            symbol TEXT PRIMARY KEY, quantity INTEGER, avg_price REAL,
            current_price REAL DEFAULT 0, unrealized_pnl REAL DEFAULT 0,
            state TEXT DEFAULT 'ACTIVE', high_water_mark REAL,
            entry_trading_day TEXT
        );
        CREATE TABLE eod_prices (
            trade_date TEXT, symbol TEXT, open REAL, high REAL,
            low REAL, close REAL, volume INTEGER
        );
        CREATE TABLE decisions (
            decision_id TEXT PRIMARY KEY, ts TEXT NOT NULL,
            symbol TEXT NOT NULL, strategy_id TEXT NOT NULL,
            strategy_version TEXT NOT NULL,
            signal_side TEXT NOT NULL CHECK (signal_side IN ('buy','sell','flat')),
            signal_score REAL NOT NULL,
            signal_ttl_ms INTEGER NOT NULL DEFAULT 30000,
            llm_ref TEXT, reason_json TEXT NOT NULL
        );
    """)
    return c


def _seed_eod_prices(conn, symbol, closes, start_date="2026-03-01"):
    """Insert eod_prices rows with ascending trade dates."""
    for i, close in enumerate(closes):
        d = int(start_date.split("-")[2]) + i
        date_str = f"2026-03-{d:02d}"
        conn.execute(
            "INSERT INTO eod_prices VALUES (?, ?, ?, ?, ?, ?, ?)",
            (date_str, symbol, close, close + 2, close - 2, close, 10000),
        )


class TestEodExitCheckTrailingStop:
    """trailing_stop should fire when price drops below HWM * (1 - trailing_pct)."""

    def test_trailing_stop_fires_with_hwm(self, conn):
        # Position: avg=100, HWM=120, current=110
        # profit_pct = (120-100)/100 = 20% → Tier 2 trailing (4%)
        # stop level = 120 * 0.96 = 115.2 → 110 < 115.2 → SELL
        conn.execute(
            "INSERT INTO positions VALUES ('2330', 1000, 100.0, 110.0, 10000.0, 'ACTIVE', 120.0, '2026-03-01')"
        )
        _seed_eod_prices(conn, "2330", [105, 110, 115, 120, 118, 115, 112, 110])

        with patch("openclaw.eod_exit_check._send_telegram_alert"):
            results = run_eod_exit_check(conn)

        assert len(results) == 1
        assert results[0]["symbol"] == "2330"
        assert results[0]["signal"] == "sell"
        assert "trailing_stop" in results[0]["reason"]

        # Verify decision persisted
        row = conn.execute(
            "SELECT * FROM decisions WHERE decision_id=?",
            (results[0]["decision_id"],),
        ).fetchone()
        assert row is not None
        assert row[3] == "eod_exit_fallback"  # strategy_id

    def test_no_signal_when_price_above_trailing(self, conn):
        # avg=115, HWM=120, profit_pct=(120-115)/115=4.3% → Tier 1 (5%)
        # stop level = 120 * 0.95 = 114 → current=116 > 114 → no trailing
        # take_profit = 115 * 1.02 = 117.3 → current=116 < 117.3 → no take_profit
        # stop_loss = 115 * 0.97 = 111.55 → current=116 > 111.55 → no stop_loss
        conn.execute(
            "INSERT INTO positions VALUES ('2330', 1000, 115.0, 116.0, 1000.0, 'ACTIVE', 120.0, '2026-03-01')"
        )
        _seed_eod_prices(conn, "2330", [112, 115, 118, 120, 119, 117, 116])

        with patch("openclaw.eod_exit_check._send_telegram_alert"):
            results = run_eod_exit_check(conn)

        assert len(results) == 0


class TestEodExitCheckStopLoss:
    """stop_loss should fire when price drops below avg * (1 - stop_loss_pct)."""

    def test_stop_loss_fires(self, conn):
        # avg=100, stop_loss=3% → level=97, current=95 → SELL
        # No HWM → trailing won't fire, but stop_loss will
        conn.execute(
            "INSERT INTO positions VALUES ('1303', 500, 100.0, 95.0, -2500.0, 'ACTIVE', NULL, '2026-03-01')"
        )
        _seed_eod_prices(conn, "1303", [100, 99, 98, 97, 96, 95])

        with patch("openclaw.eod_exit_check._send_telegram_alert"):
            results = run_eod_exit_check(conn)

        assert len(results) == 1
        assert results[0]["symbol"] == "1303"
        assert "stop_loss" in results[0]["reason"]


class TestEodExitCheckTakeProfit:
    """take_profit should fire when price exceeds avg * (1 + take_profit_pct)."""

    def test_take_profit_fires(self, conn):
        # avg=100, take_profit=2% → level=102, current=103 → SELL
        # No HWM so trailing won't fire first
        conn.execute(
            "INSERT INTO positions VALUES ('2886', 500, 100.0, 103.0, 1500.0, 'ACTIVE', NULL, '2026-03-01')"
        )
        _seed_eod_prices(conn, "2886", [100, 100.5, 101, 101.5, 102, 103])

        with patch("openclaw.eod_exit_check._send_telegram_alert"):
            results = run_eod_exit_check(conn)

        assert len(results) == 1
        assert "take_profit" in results[0]["reason"]


class TestEodExitCheckNoPosition:
    """No results when no positions exist."""

    def test_empty_positions(self, conn):
        results = run_eod_exit_check(conn)
        assert results == []


class TestEodExitCheckInsufficientData:
    """Skip positions with insufficient eod_prices data."""

    def test_skips_with_few_closes(self, conn):
        conn.execute(
            "INSERT INTO positions VALUES ('9999', 100, 50.0, 40.0, -1000.0, 'ACTIVE', NULL, '2026-03-01')"
        )
        # Only 3 data points, need at least 5
        _seed_eod_prices(conn, "9999", [50, 45, 40])

        results = run_eod_exit_check(conn)
        assert results == []


class TestBackfillHwmCalledByEodIngest:
    """Verify backfill_high_water_mark is now public in pnl_engine."""

    def test_public_export(self):
        from openclaw.pnl_engine import backfill_high_water_mark
        assert callable(backfill_high_water_mark)

    def test_private_alias_still_exists(self):
        from openclaw.pnl_engine import _backfill_high_water_mark
        assert callable(_backfill_high_water_mark)
