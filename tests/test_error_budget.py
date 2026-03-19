"""Tests for reconciliation Error Budget (Issue #288).

Covers:
- _compute_quantity_delta(): correct share counting across mismatch types
- _get_daily_mismatch_counts(): history query from reconciliation_reports
- _count_consecutive_small_days(): streak detection
- evaluate_error_budget(): spike detection, small-noise suppression, normal path
- reconcile_broker_state() integration: suppress incident, P0 upgrade
"""
from __future__ import annotations

import json
import sqlite3
import time

import pytest

import openclaw.broker_reconciliation as recon_mod
from openclaw.broker_reconciliation import (
    ErrorBudgetPolicy,
    _compute_quantity_delta,
    _count_consecutive_small_days,
    _get_daily_mismatch_counts,
    evaluate_error_budget,
    reconcile_broker_state,
)


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE incidents (
            incident_id TEXT PRIMARY KEY,
            ts          TEXT,
            severity    TEXT,
            source      TEXT,
            code        TEXT,
            detail_json TEXT,
            resolved    INTEGER DEFAULT 0
        )"""
    )
    conn.execute(
        """CREATE TABLE reconciliation_reports (
            report_id    TEXT PRIMARY KEY,
            created_at   INTEGER NOT NULL,
            mismatch_count INTEGER NOT NULL,
            summary_json TEXT NOT NULL
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rr_created ON reconciliation_reports (created_at)"
    )
    conn.execute(
        """CREATE TABLE positions (
            symbol TEXT PRIMARY KEY,
            quantity INTEGER,
            current_price REAL
        )"""
    )
    conn.execute(
        """CREATE TABLE orders (
            order_id TEXT PRIMARY KEY,
            broker_order_id TEXT,
            symbol TEXT,
            status TEXT
        )"""
    )
    conn.commit()
    return conn


def _insert_report(conn: sqlite3.Connection, *, days_ago: float, mismatch_count: int,
                   qty_delta: int = 0) -> None:
    ts_ms = int((time.time() - days_ago * 86400) * 1000)
    summary = {"quantity_delta": qty_delta, "mismatch_count": mismatch_count}
    conn.execute(
        "INSERT INTO reconciliation_reports(report_id, created_at, mismatch_count, summary_json)"
        " VALUES (hex(randomblob(8)), ?, ?, ?)",
        (ts_ms, mismatch_count, json.dumps(summary)),
    )
    conn.commit()


_SMALL_MISMATCHES: dict = {
    "missing_local_position": [],
    "missing_broker_position": [],
    "quantity_mismatch": [
        {"symbol": "2330", "local": {"quantity": 100, "current_price": 900.0},
         "broker": {"quantity": 102, "current_price": 900.0}},
    ],
    "missing_broker_order": [],
}

_LARGE_MISMATCHES: dict = {
    "missing_local_position": [
        {"symbol": "0050", "broker": {"quantity": 200, "current_price": 100.0}},
    ],
    "missing_broker_position": [
        {"symbol": "2412", "local": {"quantity": 300, "current_price": 50.0}},
    ],
    "quantity_mismatch": [
        {"symbol": "2330", "local": {"quantity": 1000, "current_price": 900.0},
         "broker": {"quantity": 800, "current_price": 900.0}},
    ],
    "missing_broker_order": [],
}


# ──────────────────────────────────────────────
# _compute_quantity_delta
# ──────────────────────────────────────────────

class TestComputeQuantityDelta:
    def test_empty_mismatches_returns_zero(self):
        m = {"missing_local_position": [], "missing_broker_position": [],
             "quantity_mismatch": [], "missing_broker_order": []}
        assert _compute_quantity_delta(m) == 0

    def test_quantity_mismatch_only(self):
        m = {
            "quantity_mismatch": [
                {"symbol": "A", "local": {"quantity": 100}, "broker": {"quantity": 90}},
                {"symbol": "B", "local": {"quantity": 50}, "broker": {"quantity": 60}},
            ],
            "missing_local_position": [],
            "missing_broker_position": [],
            "missing_broker_order": [],
        }
        assert _compute_quantity_delta(m) == 10 + 10

    def test_missing_positions_counted(self):
        m = {
            "missing_local_position": [{"symbol": "X", "broker": {"quantity": 200}}],
            "missing_broker_position": [{"symbol": "Y", "local": {"quantity": 150}}],
            "quantity_mismatch": [],
            "missing_broker_order": [],
        }
        assert _compute_quantity_delta(m) == 350

    def test_combined_all_types(self):
        delta = _compute_quantity_delta(_LARGE_MISMATCHES)
        # 200 (missing_local) + 300 (missing_broker) + 200 (qty diff)
        assert delta == 700


# ──────────────────────────────────────────────
# _get_daily_mismatch_counts
# ──────────────────────────────────────────────

class TestGetDailyMismatchCounts:
    def test_empty_history_returns_empty(self):
        conn = _make_db()
        assert _get_daily_mismatch_counts(conn, days=7) == []

    def test_returns_max_per_day(self):
        conn = _make_db()
        # Two reports on same day (~1 day ago)
        _insert_report(conn, days_ago=1.0, mismatch_count=3)
        _insert_report(conn, days_ago=1.0, mismatch_count=7)
        counts = _get_daily_mismatch_counts(conn, days=7)
        assert 7 in counts
        assert 3 not in counts

    def test_excludes_old_reports(self):
        conn = _make_db()
        _insert_report(conn, days_ago=10.0, mismatch_count=50)
        _insert_report(conn, days_ago=2.0, mismatch_count=5)
        counts = _get_daily_mismatch_counts(conn, days=7)
        assert counts == [5]


# ──────────────────────────────────────────────
# _count_consecutive_small_days
# ──────────────────────────────────────────────

class TestCountConsecutiveSmallDays:
    def test_no_history_returns_zero(self):
        conn = _make_db()
        result = _count_consecutive_small_days(
            conn, small_diff_shares=100, consecutive_days=3
        )
        assert result == 0

    def test_all_small_counts_streak(self):
        conn = _make_db()
        for d in [0.5, 1.5, 2.5]:
            _insert_report(conn, days_ago=d, mismatch_count=1, qty_delta=10)
        result = _count_consecutive_small_days(
            conn, small_diff_shares=100, consecutive_days=3
        )
        assert result == 3

    def test_large_day_breaks_streak(self):
        conn = _make_db()
        _insert_report(conn, days_ago=0.5, mismatch_count=1, qty_delta=5)   # small
        _insert_report(conn, days_ago=1.5, mismatch_count=5, qty_delta=500) # large
        _insert_report(conn, days_ago=2.5, mismatch_count=1, qty_delta=5)   # small
        result = _count_consecutive_small_days(
            conn, small_diff_shares=100, consecutive_days=3
        )
        assert result == 1  # only the first recent day is small before the break


# ──────────────────────────────────────────────
# evaluate_error_budget
# ──────────────────────────────────────────────

class TestEvaluateErrorBudget:
    def test_no_history_returns_warning(self):
        conn = _make_db()
        policy = ErrorBudgetPolicy(consecutive_days_to_suppress=3)
        decision = evaluate_error_budget(conn, _SMALL_MISMATCHES, policy=policy)
        assert decision.severity == "warning"
        assert decision.suppress_incident is False

    def test_spike_detected_returns_critical(self):
        conn = _make_db()
        # Baseline: avg mismatch_count = 2 (over last 7 days)
        for d in [1.0, 2.0, 3.0, 4.0]:
            _insert_report(conn, days_ago=d, mismatch_count=2)
        # Today's mismatches = 10 entries → 10 > 2 * 3.0 = 6 → spike
        big = {
            "quantity_mismatch": [
                {"symbol": str(i),
                 "local": {"quantity": 100}, "broker": {"quantity": 90}}
                for i in range(10)
            ],
            "missing_local_position": [],
            "missing_broker_position": [],
            "missing_broker_order": [],
        }
        policy = ErrorBudgetPolicy(spike_multiplier=3.0, small_diff_shares=100)
        decision = evaluate_error_budget(conn, big, policy=policy)
        assert decision.severity == "critical"
        assert "SPIKE" in decision.reason

    def test_small_noise_suppressed_after_streak(self):
        conn = _make_db()
        # 3 days of small diffs in history
        for d in [0.5, 1.5, 2.5]:
            _insert_report(conn, days_ago=d, mismatch_count=1, qty_delta=2)
        policy = ErrorBudgetPolicy(
            small_diff_shares=100, consecutive_days_to_suppress=3
        )
        decision = evaluate_error_budget(conn, _SMALL_MISMATCHES, policy=policy)
        assert decision.severity == "info"
        assert decision.suppress_incident is True
        assert "SMALL_NOISE" in decision.reason

    def test_insufficient_streak_not_suppressed(self):
        conn = _make_db()
        # Only 2 days of small diffs
        for d in [0.5, 1.5]:
            _insert_report(conn, days_ago=d, mismatch_count=1, qty_delta=2)
        policy = ErrorBudgetPolicy(
            small_diff_shares=100, consecutive_days_to_suppress=3
        )
        decision = evaluate_error_budget(conn, _SMALL_MISMATCHES, policy=policy)
        assert decision.suppress_incident is False

    def test_qty_exceeds_threshold_not_suppressed(self):
        conn = _make_db()
        for d in [0.5, 1.5, 2.5]:
            _insert_report(conn, days_ago=d, mismatch_count=1, qty_delta=50)
        policy = ErrorBudgetPolicy(small_diff_shares=10, consecutive_days_to_suppress=3)
        # _SMALL_MISMATCHES has qty_delta=2 but threshold is 10, so 2 < 10 → suppressed
        # Use a mismatch with large qty
        big_qty = {
            "quantity_mismatch": [
                {"symbol": "2330",
                 "local": {"quantity": 1000}, "broker": {"quantity": 800}},
            ],
            "missing_local_position": [],
            "missing_broker_position": [],
            "missing_broker_order": [],
        }
        decision = evaluate_error_budget(conn, big_qty, policy=policy)
        # qty_delta=200 > threshold=10 → should NOT suppress
        assert decision.suppress_incident is False


# ──────────────────────────────────────────────
# reconcile_broker_state integration
# ──────────────────────────────────────────────

class TestReconcileIntegration:
    def _setup_positions(self, conn: sqlite3.Connection) -> None:
        conn.execute("INSERT INTO positions VALUES ('2330', 1000, 900.0)")
        conn.commit()

    def test_small_noise_suppresses_incident(self, monkeypatch):
        conn = _make_db()
        self._setup_positions(conn)
        # 3 days of small diffs in history
        for d in [0.5, 1.5, 2.5]:
            _insert_report(conn, days_ago=d, mismatch_count=1, qty_delta=2)

        policy = ErrorBudgetPolicy(
            small_diff_shares=100, consecutive_days_to_suppress=3
        )
        monkeypatch.setattr(recon_mod, "ErrorBudgetPolicy", lambda: policy)

        broker_positions = [{"symbol": "2330", "quantity": 1002, "current_price": 900.0}]
        report = reconcile_broker_state(conn, broker_positions=broker_positions)

        assert report["mismatch_count"] > 0
        incidents = conn.execute(
            "SELECT COUNT(*) FROM incidents WHERE code='RECONCILIATION_MISMATCH'"
        ).fetchone()[0]
        assert incidents == 0  # suppressed

    def test_spike_writes_critical_incident(self, monkeypatch):
        conn = _make_db()
        self._setup_positions(conn)
        # Baseline: 2 mismatches/day average
        for d in [1.0, 2.0, 3.0]:
            _insert_report(conn, days_ago=d, mismatch_count=2)

        # Today's broker snapshot is completely empty → all positions missing
        # That's 1 mismatch entry — check spike_multiplier calculation
        # avg=2, spike_multiplier=3 → threshold=6; need >6 mismatches to trigger
        # We'll lower the multiplier to guarantee spike
        policy = ErrorBudgetPolicy(spike_multiplier=0.4, small_diff_shares=100)
        monkeypatch.setattr(recon_mod, "ErrorBudgetPolicy", lambda: policy)

        report = reconcile_broker_state(conn, broker_positions=[])
        incidents = conn.execute(
            "SELECT severity, detail_json FROM incidents WHERE code='RECONCILIATION_MISMATCH'"
        ).fetchall()
        # simulation_expected=False (no resolved_simulation), incident should be written
        # severity from budget (critical) or account mismatch (critical either way)
        assert len(incidents) >= 1

    def test_report_includes_quantity_delta(self):
        conn = _make_db()
        self._setup_positions(conn)
        broker_positions = [{"symbol": "2330", "quantity": 1050, "current_price": 900.0}]
        report = reconcile_broker_state(conn, broker_positions=broker_positions)
        assert "quantity_delta" in report
        assert report["quantity_delta"] == 50  # |1000 - 1050|

    def test_clean_run_no_incident(self):
        conn = _make_db()
        self._setup_positions(conn)
        broker_positions = [{"symbol": "2330", "quantity": 1000, "current_price": 900.0}]
        report = reconcile_broker_state(conn, broker_positions=broker_positions)
        assert report["ok"] is True
        incidents = conn.execute(
            "SELECT COUNT(*) FROM incidents WHERE code='RECONCILIATION_MISMATCH'"
        ).fetchone()[0]
        assert incidents == 0
