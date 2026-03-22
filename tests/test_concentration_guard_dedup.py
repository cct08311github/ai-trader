"""Tests for concentration_guard dedup fix and threshold changes (#385).

Covers:
- New thresholds: 40% auto-approve, 25% warn
- Dedup: pending sell orders skip only if sufficient to reach target
- Stale orders (>6 min) are ignored in dedup
- Insufficient pending sell generates additional proposal
"""
import sqlite3
import time

import pytest

from openclaw.concentration_guard import (
    _AUTO_REDUCE_THRESHOLD,
    _STALE_ORDER_SEC,
    _TARGET_WEIGHT,
    _WARN_THRESHOLD,
    check_concentration,
)


def _make_db(positions: list[tuple], orders: list[tuple] | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE positions (
            symbol TEXT PRIMARY KEY,
            quantity REAL,
            current_price REAL,
            state TEXT,
            avg_price REAL,
            unrealized_pnl REAL,
            high_water_mark REAL,
            entry_trading_day TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE orders (
            order_id TEXT PRIMARY KEY,
            symbol TEXT,
            side TEXT,
            qty INTEGER,
            status TEXT,
            ts_submit TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE strategy_proposals (
            proposal_id TEXT PRIMARY KEY,
            generated_by TEXT,
            target_rule TEXT,
            rule_category TEXT,
            proposed_value TEXT,
            supporting_evidence TEXT,
            confidence REAL,
            requires_human_approval INTEGER,
            status TEXT,
            proposal_json TEXT,
            created_at INTEGER
        )"""
    )
    conn.executemany(
        "INSERT INTO positions (symbol, quantity, current_price) VALUES (?,?,?)",
        positions,
    )
    if orders:
        conn.executemany(
            "INSERT INTO orders (order_id, symbol, side, qty, status, ts_submit) VALUES (?,?,?,?,?,?)",
            orders,
        )
    conn.commit()
    return conn


class TestThresholdValues:
    """Verify threshold constants match #385 spec."""

    def test_auto_reduce_threshold(self):
        assert _AUTO_REDUCE_THRESHOLD == 0.40

    def test_warn_threshold(self):
        assert _WARN_THRESHOLD == 0.25

    def test_target_weight(self):
        assert _TARGET_WEIGHT == 0.20


class TestConcentrationDetection:
    def test_above_40pct_auto_approved(self):
        # SYM_A: 500 * 100 = 50,000 (50%)
        # SYM_B: 500 * 100 = 50,000 (50%)
        conn = _make_db([("SYM_A", 500, 100), ("SYM_B", 500, 100)])
        proposals = check_concentration(conn)
        # Both at 50% > 40% → both auto-approved
        assert len(proposals) == 2
        assert all(p["auto_approve"] for p in proposals)

    def test_between_25_and_40_pending(self):
        # SYM_A: 300 * 100 = 30,000 (30%)
        # SYM_B: 700 * 100 = 70,000 (70%)
        conn = _make_db([("SYM_A", 300, 100), ("SYM_B", 700, 100)])
        proposals = check_concentration(conn)
        sym_a = [p for p in proposals if p["symbol"] == "SYM_A"]
        sym_b = [p for p in proposals if p["symbol"] == "SYM_B"]
        # SYM_A: 30% > 25%, < 40% → pending
        assert len(sym_a) == 1
        assert sym_a[0]["auto_approve"] is False
        # SYM_B: 70% > 40% → auto-approved
        assert len(sym_b) == 1
        assert sym_b[0]["auto_approve"] is True

    def test_below_threshold_no_proposal(self):
        # SYM_A: 200 * 100 = 20,000 (20%)
        # SYM_B: 800 * 100 = 80,000 (80%)
        conn = _make_db([("SYM_A", 200, 100), ("SYM_B", 800, 100)])
        proposals = check_concentration(conn)
        # SYM_A: 20% < 25% → no proposal
        assert len(proposals) == 1
        assert proposals[0]["symbol"] == "SYM_B"


class TestDedupSufficientSell:
    def test_skips_when_pending_sell_covers_target(self):
        # SYM_A: 800 * 100 = 80,000 (80%)
        # SYM_B: 200 * 100 = 20,000 (20%)
        # Pending sell 600 for SYM_A → remaining = 200 (20%) <= target 20%
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        conn = _make_db(
            [("SYM_A", 800, 100), ("SYM_B", 200, 100)],
            [("ORD1", "SYM_A", "sell", 600, "submitted", now_iso)],
        )
        proposals = check_concentration(conn)
        # SYM_A should be skipped — pending sell is sufficient
        sym_a = [p for p in proposals if p["symbol"] == "SYM_A"]
        assert len(sym_a) == 0

    def test_generates_proposal_when_pending_sell_insufficient(self):
        # SYM_A: 800 * 100 = 80,000 (80%)
        # SYM_B: 200 * 100 = 20,000 (20%)
        # Pending sell 100 for SYM_A → remaining = 700 (70%) > target 20%
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        conn = _make_db(
            [("SYM_A", 800, 100), ("SYM_B", 200, 100)],
            [("ORD1", "SYM_A", "sell", 100, "submitted", now_iso)],
        )
        proposals = check_concentration(conn)
        sym_a = [p for p in proposals if p["symbol"] == "SYM_A"]
        assert len(sym_a) == 1

    def test_ignores_stale_orders(self):
        # SYM_A: 800 * 100 = 80,000 (80%)
        # SYM_B: 200 * 100 = 20,000 (20%)
        # Old sell order (7 min ago) → stale, should be ignored
        stale_iso = time.strftime(
            "%Y-%m-%dT%H:%M:%S",
            time.gmtime(time.time() - _STALE_ORDER_SEC - 60),
        )
        conn = _make_db(
            [("SYM_A", 800, 100), ("SYM_B", 200, 100)],
            [("ORD1", "SYM_A", "sell", 600, "submitted", stale_iso)],
        )
        proposals = check_concentration(conn)
        # Stale sell order ignored → SYM_A gets a new proposal
        sym_a = [p for p in proposals if p["symbol"] == "SYM_A"]
        assert len(sym_a) == 1

    def test_no_pending_sells_generates_proposal(self):
        # SYM_A: 800 * 100 = 80,000 (80%)
        # SYM_B: 200 * 100 = 20,000 (20%)
        conn = _make_db([("SYM_A", 800, 100), ("SYM_B", 200, 100)])
        proposals = check_concentration(conn)
        sym_a = [p for p in proposals if p["symbol"] == "SYM_A"]
        assert len(sym_a) == 1
        assert sym_a[0]["auto_approve"] is True
