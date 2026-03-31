"""Tests for DEEP_SUSPEND feature in drawdown_guard.py (Issue #285).

Covers:
- _compute_monthly_returns: groups daily_pnl_summary by month correctly
- evaluate_deep_suspend_guard: triggers on N consecutive losing months
- apply_drawdown_actions: locks trading and writes incident on deep_suspend
- _notify_deep_suspend: sends Telegram with checklist (mocked)
- get_restart_checklist: returns checklist string
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from openclaw.drawdown_guard import (
    DrawdownPolicy,
    DrawdownDecision,
    _compute_monthly_returns,
    evaluate_deep_suspend_guard,
    apply_drawdown_actions,
    get_restart_checklist,
)


# ──────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────

def _make_db(nav_rows: list[tuple] | None = None) -> sqlite3.Connection:
    """Build in-memory DB with daily_nav + supporting tables (#398)."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE daily_nav (
            trade_date              TEXT PRIMARY KEY,
            nav                     REAL NOT NULL,
            cash                    REAL NOT NULL DEFAULT 0,
            unrealized_pnl          REAL NOT NULL DEFAULT 0,
            realized_pnl_cumulative REAL NOT NULL DEFAULT 0,
            recorded_at             INTEGER NOT NULL DEFAULT 0
        )"""
    )
    conn.execute(
        """CREATE TABLE trading_locks (
            lock_id    TEXT PRIMARY KEY,
            locked     INTEGER DEFAULT 0,
            reason_code TEXT,
            locked_at  TEXT,
            unlock_after TEXT,
            note       TEXT
        )"""
    )
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
    conn.commit()

    if nav_rows:
        conn.executemany(
            "INSERT INTO daily_nav (trade_date, nav) VALUES (?,?)",
            nav_rows,
        )
        conn.commit()

    return conn


def _nav_sequence(
    months: list[tuple[str, float, float]]
) -> list[tuple[str, float]]:
    """Helper: build daily_nav rows from (YYYY-MM, nav_start, nav_end) specs.

    Inserts 6 rows per month (days 01,05,10,15,20,28) with linear
    interpolation from nav_start to nav_end.  This satisfies the
    _MIN_TRADING_DAYS_PER_MONTH=5 threshold in _compute_monthly_returns.
    """
    days = [1, 5, 10, 15, 20, 28]
    rows = []
    for month, start, end in months:
        n = len(days) - 1
        for i, d in enumerate(days):
            nav = start + (end - start) * i / n
            rows.append((f"{month}-{d:02d}", round(nav, 2)))
    return rows


# ──────────────────────────────────────────────
# _compute_monthly_returns
# ──────────────────────────────────────────────

class TestComputeMonthlyReturns:
    def test_empty_table_returns_empty(self):
        conn = _make_db()
        assert _compute_monthly_returns(conn) == []

    def test_single_month_positive(self):
        rows = _nav_sequence([("2026-01", 1_000_000, 1_050_000)])
        conn = _make_db(rows)
        results = _compute_monthly_returns(conn)
        assert len(results) == 1
        month, ret = results[0]
        assert month == "2026-01"
        assert abs(ret - 0.05) < 0.001   # +5%

    def test_single_month_negative(self):
        rows = _nav_sequence([("2026-02", 1_000_000, 870_000)])
        conn = _make_db(rows)
        results = _compute_monthly_returns(conn)
        assert len(results) == 1
        _, ret = results[0]
        assert ret < 0   # negative return

    def test_ordered_oldest_first(self):
        rows = _nav_sequence([
            ("2026-01", 1_000_000, 900_000),
            ("2026-02", 900_000, 1_100_000),
        ])
        conn = _make_db(rows)
        results = _compute_monthly_returns(conn)
        assert results[0][0] < results[1][0]   # 2026-01 < 2026-02

    def test_sparse_month_excluded(self):
        """Month with < MIN_TRADING_DAYS rows is excluded (防止假數據觸發)."""
        rows = [("2026-01-01", 1_000_000), ("2026-01-28", 850_000)]  # only 2 rows
        conn = _make_db(rows)
        results = _compute_monthly_returns(conn)
        assert len(results) == 0  # excluded by HAVING COUNT(*) >= 5

    def test_missing_table_returns_empty(self):
        conn = sqlite3.connect(":memory:")  # no table created
        assert _compute_monthly_returns(conn) == []


# ──────────────────────────────────────────────
# evaluate_deep_suspend_guard
# ──────────────────────────────────────────────

class TestEvaluateDeepSuspendGuard:
    def _policy(self, n=3, pct=0.10) -> DrawdownPolicy:
        return DrawdownPolicy(
            deep_suspend_consecutive_loss_months=n,
            deep_suspend_monthly_loss_pct=pct,
        )

    def test_no_data_returns_normal(self):
        conn = _make_db()
        decision = evaluate_deep_suspend_guard(conn, self._policy())
        assert decision.risk_mode == "normal"

    def test_insufficient_months_returns_normal(self):
        # Only 2 months of data, but policy requires 3
        rows = _nav_sequence([
            ("2026-01", 1_000_000, 880_000),  # -12%
            ("2026-02", 880_000,   760_000),  # -13.6%
        ])
        conn = _make_db(rows)
        decision = evaluate_deep_suspend_guard(conn, self._policy(n=3))
        assert decision.risk_mode == "normal"
        assert decision.reason_code == "RISK_DEEP_SUSPEND_INSUFFICIENT_DATA"

    def test_triggers_on_three_consecutive_loss_months(self):
        rows = _nav_sequence([
            ("2026-01", 1_000_000, 880_000),   # -12%
            ("2026-02", 880_000,   770_000),   # -12.5%
            ("2026-03", 770_000,   680_000),   # -11.7%
        ])
        conn = _make_db(rows)
        decision = evaluate_deep_suspend_guard(conn, self._policy(n=3, pct=0.10))
        assert decision.risk_mode == "deep_suspend"
        assert decision.reason_code == "RISK_DEEP_SUSPEND_CONSECUTIVE_LOSS"
        assert decision.consecutive_loss_months == 3
        assert len(decision.monthly_losses) == 3

    def test_does_not_trigger_if_one_month_recovery(self):
        rows = _nav_sequence([
            ("2026-01", 1_000_000, 880_000),   # -12%
            ("2026-02", 880_000,   960_000),   # +9.1% recovery
            ("2026-03", 960_000,   840_000),   # -12.5%
        ])
        conn = _make_db(rows)
        decision = evaluate_deep_suspend_guard(conn, self._policy(n=3, pct=0.10))
        assert decision.risk_mode == "normal"

    def test_does_not_trigger_if_loss_below_threshold(self):
        # Loses only 5% each month, threshold is 10%
        rows = _nav_sequence([
            ("2026-01", 1_000_000, 950_000),   # -5%
            ("2026-02", 950_000,   902_500),   # -5%
            ("2026-03", 902_500,   857_375),   # -5%
        ])
        conn = _make_db(rows)
        decision = evaluate_deep_suspend_guard(conn, self._policy(n=3, pct=0.10))
        assert decision.risk_mode == "normal"

    def test_n_equals_one(self):
        """Edge case: n=1 should trigger on any single month exceeding threshold."""
        rows = _nav_sequence([("2026-01", 1_000_000, 850_000)])  # -15%
        conn = _make_db(rows)
        decision = evaluate_deep_suspend_guard(conn, self._policy(n=1, pct=0.10))
        assert decision.risk_mode == "deep_suspend"


# ──────────────────────────────────────────────
# apply_drawdown_actions with deep_suspend
# ──────────────────────────────────────────────

class TestApplyDrawdownActionsDeepSuspend:
    def _deep_suspend_decision(self) -> DrawdownDecision:
        return DrawdownDecision(
            risk_mode="deep_suspend",
            reason_code="RISK_DEEP_SUSPEND_CONSECUTIVE_LOSS",
            drawdown=0.12,
            losing_streak_days=0,
            consecutive_loss_months=3,
            monthly_losses=[
                {"month": "2026-01", "return": -0.12},
                {"month": "2026-02", "return": -0.125},
                {"month": "2026-03", "return": -0.117},
            ],
        )

    def test_sets_trading_lock(self):
        conn = _make_db()
        decision = self._deep_suspend_decision()
        apply_drawdown_actions(conn, decision)
        row = conn.execute(
            "SELECT locked, reason_code FROM trading_locks WHERE lock_id='drawdown_guard'"
        ).fetchone()
        assert row is not None
        assert row[0] == 1   # locked=True
        assert row[1] == "RISK_DEEP_SUSPEND_CONSECUTIVE_LOSS"

    def test_writes_critical_incident(self):
        conn = _make_db()
        decision = self._deep_suspend_decision()
        apply_drawdown_actions(conn, decision)
        row = conn.execute(
            "SELECT severity, code, detail_json FROM incidents WHERE code='RISK_DEEP_SUSPEND_CONSECUTIVE_LOSS'"
        ).fetchone()
        assert row is not None
        assert row[0] == "critical"
        detail = json.loads(row[2])
        assert detail["risk_mode"] == "deep_suspend"
        assert detail["consecutive_loss_months"] == 3
        assert len(detail["monthly_losses"]) == 3

    def test_sends_telegram_notification(self, monkeypatch):
        # Reset module-level cooldown state so this test always passes in isolation
        import openclaw.drawdown_guard as dg
        monkeypatch.setattr(dg, "_LAST_DEEP_SUSPEND_NOTIFY", None)
        conn = _make_db()
        decision = self._deep_suspend_decision()
        sent = []
        monkeypatch.setattr("openclaw.tg_notify.send_message", lambda msg: sent.append(msg))
        apply_drawdown_actions(conn, decision)
        assert len(sent) == 1
        assert "DEEP SUSPEND" in sent[0]
        assert "Checklist" in sent[0]

    def test_notification_writes_audit_incident(self, monkeypatch):
        """_notify_deep_suspend writes an audit incident before sending Telegram."""
        import openclaw.drawdown_guard as dg
        monkeypatch.setattr(dg, "_LAST_DEEP_SUSPEND_NOTIFY", None)
        monkeypatch.setattr("openclaw.tg_notify.send_message", lambda msg: True)
        conn = _make_db()
        decision = self._deep_suspend_decision()
        apply_drawdown_actions(conn, decision)
        row = conn.execute(
            "SELECT code, detail_json FROM incidents WHERE code='DEEP_SUSPEND_TELEGRAM_SENT'"
        ).fetchone()
        assert row is not None
        detail = json.loads(row[1])
        assert detail["consecutive_loss_months"] == 3

    def test_normal_decision_no_lock(self):
        conn = _make_db()
        normal = DrawdownDecision("normal", "RISK_DRAWDOWN_OK", 0.0, 0)
        apply_drawdown_actions(conn, normal)
        row = conn.execute("SELECT * FROM trading_locks").fetchone()
        assert row is None


# ──────────────────────────────────────────────
# get_restart_checklist
# ──────────────────────────────────────────────

class TestGetRestartChecklist:
    def test_returns_non_empty_string(self):
        checklist = get_restart_checklist()
        assert isinstance(checklist, str)
        assert len(checklist) > 50

    def test_contains_key_checklist_items(self):
        checklist = get_restart_checklist()
        assert "DEEP SUSPEND" in checklist
        assert "Checklist" in checklist
