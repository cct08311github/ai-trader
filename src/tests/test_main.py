"""Tests for openclaw.main — persist_order, persist_fill, persist_decision,
execute_approved_order, _apply_broker_status, and the main() entry point."""
from __future__ import annotations

import argparse
import sqlite3
import time
from unittest.mock import MagicMock, patch

import pytest

from openclaw.broker import BrokerOrderStatus, BrokerSubmission, SimBrokerAdapter
from openclaw.main import (
    ExecutionResult,
    _apply_broker_status,
    execute_approved_order,
    main,
    persist_decision,
    persist_fill,
    persist_order,
    utc_now_iso,
)
from openclaw.risk_engine import Decision, OrderCandidate


# ---------------------------------------------------------------------------
# Minimal in-memory DB fixture with the tables used by main.py
# ---------------------------------------------------------------------------

def make_db() -> sqlite3.Connection:
    """Create a minimal in-memory SQLite DB with all tables required by main."""
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        PRAGMA foreign_keys = OFF;

        CREATE TABLE IF NOT EXISTS decisions (
          decision_id TEXT PRIMARY KEY,
          ts TEXT NOT NULL,
          symbol TEXT NOT NULL,
          strategy_id TEXT NOT NULL,
          strategy_version TEXT NOT NULL,
          signal_side TEXT NOT NULL,
          signal_score REAL NOT NULL,
          signal_ttl_ms INTEGER NOT NULL DEFAULT 30000,
          llm_ref TEXT,
          reason_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS risk_limits (
          limit_id TEXT PRIMARY KEY,
          scope TEXT NOT NULL,
          symbol TEXT,
          strategy_id TEXT,
          rule_name TEXT NOT NULL,
          rule_value REAL NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 1,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS risk_checks (
          check_id TEXT PRIMARY KEY,
          decision_id TEXT NOT NULL,
          ts TEXT NOT NULL,
          passed INTEGER NOT NULL,
          reject_code TEXT,
          metrics_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS orders (
          order_id TEXT PRIMARY KEY,
          decision_id TEXT NOT NULL,
          broker_order_id TEXT,
          ts_submit TEXT NOT NULL,
          symbol TEXT NOT NULL,
          side TEXT NOT NULL,
          qty INTEGER NOT NULL,
          price REAL,
          order_type TEXT NOT NULL,
          tif TEXT NOT NULL,
          status TEXT NOT NULL,
          strategy_version TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fills (
          fill_id TEXT PRIMARY KEY,
          order_id TEXT NOT NULL,
          ts_fill TEXT NOT NULL,
          qty INTEGER NOT NULL,
          price REAL NOT NULL,
          fee REAL NOT NULL DEFAULT 0,
          tax REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS order_events (
          event_id TEXT PRIMARY KEY,
          ts TEXT NOT NULL,
          order_id TEXT NOT NULL,
          event_type TEXT NOT NULL,
          from_status TEXT,
          to_status TEXT,
          source TEXT NOT NULL,
          reason_code TEXT,
          payload_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS incidents (
          incident_id TEXT PRIMARY KEY,
          ts TEXT NOT NULL,
          severity TEXT NOT NULL,
          source TEXT NOT NULL,
          code TEXT NOT NULL,
          detail_json TEXT NOT NULL,
          resolved INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS daily_pnl_summary (
          trade_date TEXT PRIMARY KEY,
          nav_start REAL NOT NULL,
          nav_end REAL NOT NULL,
          realized_pnl REAL NOT NULL,
          unrealized_pnl REAL NOT NULL,
          total_pnl REAL NOT NULL,
          daily_return REAL NOT NULL,
          rolling_peak_nav REAL NOT NULL,
          rolling_drawdown REAL NOT NULL,
          losing_streak_days INTEGER NOT NULL DEFAULT 0,
          risk_mode TEXT NOT NULL DEFAULT 'normal'
        );

        CREATE TABLE IF NOT EXISTS strategy_health (
          strategy_id TEXT PRIMARY KEY,
          as_of_ts TEXT NOT NULL,
          rolling_trades INTEGER NOT NULL DEFAULT 0,
          rolling_win_rate REAL NOT NULL DEFAULT 0.0,
          enabled INTEGER NOT NULL DEFAULT 1,
          note TEXT
        );

        CREATE TABLE IF NOT EXISTS position_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
          system_state_json TEXT NOT NULL,
          positions_json TEXT NOT NULL,
          available_cash REAL,
          reason TEXT
        );
        """
    )
    return conn


def _make_decision() -> Decision:
    import datetime as dt
    return Decision(
        decision_id="test-dec-001",
        ts_ms=int(dt.datetime.now(tz=dt.timezone.utc).timestamp() * 1000),
        symbol="2330",
        strategy_id="breakout",
        signal_side="buy",
        signal_score=0.80,
    )


def _make_candidate() -> OrderCandidate:
    return OrderCandidate(symbol="2330", side="buy", qty=100, price=500.0)


# ---------------------------------------------------------------------------
# utc_now_iso
# ---------------------------------------------------------------------------

def test_utc_now_iso_returns_string():
    ts = utc_now_iso()
    assert isinstance(ts, str)
    assert "T" in ts  # ISO format marker


# ---------------------------------------------------------------------------
# ExecutionResult dataclass
# ---------------------------------------------------------------------------

def test_execution_result_defaults():
    er = ExecutionResult(ok=True, order_id="o1")
    assert er.error_code == ""
    assert er.error_message == ""


def test_execution_result_with_error():
    er = ExecutionResult(ok=False, order_id="o2", error_code="E1", error_message="bad")
    assert not er.ok
    assert er.error_code == "E1"


# ---------------------------------------------------------------------------
# persist_order
# ---------------------------------------------------------------------------

def test_persist_order_inserts_row(monkeypatch):
    conn = make_db()
    # Insert a decision row first (FK disabled, but let's keep it clean)
    conn.execute(
        "INSERT INTO decisions VALUES (?, datetime('now'), '2330', 'breakout', 'v1', 'buy', 0.8, 30000, NULL, '{}')",
        ("test-dec-001",),
    )
    persist_order(
        conn,
        order_id="ORD-1",
        decision_id="test-dec-001",
        broker_order_id="BRK-1",
        symbol="2330",
        side="buy",
        qty=100,
        price=500.0,
        strategy_version="v1",
        status="submitted",
    )
    row = conn.execute("SELECT * FROM orders WHERE order_id='ORD-1'").fetchone()
    assert row is not None
    assert row["symbol"] == "2330"
    assert row["status"] == "submitted"
    assert row["order_type"] == "limit"
    assert row["tif"] == "IOC"


def test_persist_order_default_status(monkeypatch):
    conn = make_db()
    conn.execute(
        "INSERT INTO decisions VALUES (?, datetime('now'), '2330', 'breakout', 'v1', 'buy', 0.8, 30000, NULL, '{}')",
        ("dec-002",),
    )
    persist_order(
        conn,
        order_id="ORD-2",
        decision_id="dec-002",
        broker_order_id="BRK-2",
        symbol="2330",
        side="sell",
        qty=50,
        price=499.0,
        strategy_version="v1",
    )
    row = conn.execute("SELECT status FROM orders WHERE order_id='ORD-2'").fetchone()
    assert row["status"] == "submitted"


# ---------------------------------------------------------------------------
# persist_fill
# ---------------------------------------------------------------------------

def test_persist_fill_inserts_row():
    conn = make_db()
    # Insert a parent order
    conn.execute(
        "INSERT INTO orders VALUES ('ORD-F', 'dec-f', 'BRK-F', datetime('now'), '2330', 'buy', 100, 500.0, 'limit', 'IOC', 'submitted', 'v1')"
    )
    persist_fill(
        conn,
        fill_id="FILL-1",
        order_id="ORD-F",
        qty=100,
        price=500.0,
        fee=20.0,
        tax=30.0,
    )
    row = conn.execute("SELECT * FROM fills WHERE fill_id='FILL-1'").fetchone()
    assert row is not None
    assert row["qty"] == 100
    assert row["fee"] == 20.0
    assert row["tax"] == 30.0


# ---------------------------------------------------------------------------
# persist_decision
# ---------------------------------------------------------------------------

def test_persist_decision_inserts_row():
    conn = make_db()
    decision = _make_decision()
    persist_decision(conn, decision=decision, strategy_version="v1")
    row = conn.execute("SELECT * FROM decisions WHERE decision_id=?", (decision.decision_id,)).fetchone()
    assert row is not None
    assert row["symbol"] == "2330"
    assert row["strategy_id"] == "breakout"


def test_persist_decision_with_reason():
    conn = make_db()
    decision = _make_decision()
    persist_decision(conn, decision=decision, strategy_version="v1", reason={"source": "test"})
    row = conn.execute("SELECT reason_json FROM decisions WHERE decision_id=?", (decision.decision_id,)).fetchone()
    import json
    assert json.loads(row["reason_json"]) == {"source": "test"}


def test_persist_decision_or_ignore():
    """Second insert on same decision_id must not raise (INSERT OR IGNORE)."""
    conn = make_db()
    decision = _make_decision()
    persist_decision(conn, decision=decision, strategy_version="v1")
    persist_decision(conn, decision=decision, strategy_version="v2")  # should not raise
    count = conn.execute(
        "SELECT COUNT(*) FROM decisions WHERE decision_id=?", (decision.decision_id,)
    ).fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# _apply_broker_status
# ---------------------------------------------------------------------------

def _insert_order(conn: sqlite3.Connection, order_id: str, qty: int = 100, status: str = "submitted") -> None:
    conn.execute(
        "INSERT INTO orders VALUES (?, 'dec-x', 'BRK-X', datetime('now'), '2330', 'buy', ?, 500.0, 'limit', 'IOC', ?, 'v1')",
        (order_id, qty, status),
    )


def test_apply_broker_status_no_new_fill():
    """When broker filled_qty <= last_filled_qty, no new fill row is written."""
    conn = make_db()
    _insert_order(conn, "ORD-A", qty=100, status="submitted")
    broker_status = BrokerOrderStatus(
        broker_order_id="BRK-A",
        status="submitted",
        filled_qty=0,
        avg_fill_price=500.0,
        fee=0.0,
        tax=0.0,
    )
    new_qty = _apply_broker_status(conn, order_id="ORD-A", broker_status=broker_status, last_filled_qty=0)
    assert new_qty == 0
    fills = conn.execute("SELECT COUNT(*) FROM fills WHERE order_id='ORD-A'").fetchone()[0]
    assert fills == 0


def test_apply_broker_status_with_partial_fill():
    """When broker reports a partial fill, a fill row and event are inserted."""
    conn = make_db()
    _insert_order(conn, "ORD-B", qty=100, status="submitted")
    broker_status = BrokerOrderStatus(
        broker_order_id="BRK-B",
        status="partially_filled",
        filled_qty=50,
        avg_fill_price=501.0,
        fee=10.0,
        tax=5.0,
    )
    new_qty = _apply_broker_status(conn, order_id="ORD-B", broker_status=broker_status, last_filled_qty=0)
    assert new_qty == 50
    fill = conn.execute("SELECT * FROM fills WHERE order_id='ORD-B'").fetchone()
    assert fill is not None
    assert fill["qty"] == 50


def test_apply_broker_status_broker_terminal_status():
    """When broker status is a terminal state (cancelled), order status is updated."""
    conn = make_db()
    _insert_order(conn, "ORD-C", qty=100, status="submitted")
    broker_status = BrokerOrderStatus(
        broker_order_id="BRK-C",
        status="cancelled",
        filled_qty=0,
        avg_fill_price=0.0,
        fee=0.0,
        tax=0.0,
    )
    _apply_broker_status(conn, order_id="ORD-C", broker_status=broker_status, last_filled_qty=0)
    row = conn.execute("SELECT status FROM orders WHERE order_id='ORD-C'").fetchone()
    assert row["status"] == "cancelled"


def test_apply_broker_status_rejected():
    """Rejected terminal broker status flows through correctly."""
    conn = make_db()
    _insert_order(conn, "ORD-D", qty=100, status="submitted")
    broker_status = BrokerOrderStatus(
        broker_order_id="BRK-D",
        status="rejected",
        filled_qty=0,
        avg_fill_price=0.0,
        fee=0.0,
        tax=0.0,
        reason="price out of band",
        reason_code="RISK_PRICE",
    )
    _apply_broker_status(conn, order_id="ORD-D", broker_status=broker_status, last_filled_qty=0)
    row = conn.execute("SELECT status FROM orders WHERE order_id='ORD-D'").fetchone()
    assert row["status"] == "rejected"


def test_apply_broker_status_expired():
    conn = make_db()
    _insert_order(conn, "ORD-EXP", qty=100, status="submitted")
    broker_status = BrokerOrderStatus(
        broker_order_id="BRK-EXP",
        status="expired",
        filled_qty=0,
        avg_fill_price=0.0,
        fee=0.0,
        tax=0.0,
    )
    _apply_broker_status(conn, order_id="ORD-EXP", broker_status=broker_status, last_filled_qty=0)
    row = conn.execute("SELECT status FROM orders WHERE order_id='ORD-EXP'").fetchone()
    assert row["status"] == "expired"


def test_apply_broker_status_incremental_fills():
    """Delta is computed correctly when last_filled_qty is non-zero."""
    conn = make_db()
    _insert_order(conn, "ORD-E", qty=100, status="submitted")
    # First partial fill of 30
    broker_status1 = BrokerOrderStatus(
        broker_order_id="BRK-E", status="partially_filled",
        filled_qty=30, avg_fill_price=502.0, fee=5.0, tax=2.0,
    )
    qty_after_1 = _apply_broker_status(conn, order_id="ORD-E", broker_status=broker_status1, last_filled_qty=0)
    assert qty_after_1 == 30

    # Second partial fill of 70 (total 100)
    broker_status2 = BrokerOrderStatus(
        broker_order_id="BRK-E", status="filled",
        filled_qty=100, avg_fill_price=502.0, fee=20.0, tax=8.0,
    )
    qty_after_2 = _apply_broker_status(conn, order_id="ORD-E", broker_status=broker_status2, last_filled_qty=30)
    assert qty_after_2 == 100
    fill_count = conn.execute("SELECT COUNT(*) FROM fills WHERE order_id='ORD-E'").fetchone()[0]
    assert fill_count == 2  # two separate fill rows


# ---------------------------------------------------------------------------
# execute_approved_order
# ---------------------------------------------------------------------------

def test_execute_approved_order_success():
    """Happy-path: SimBrokerAdapter fills the order."""
    conn = make_db()
    decision = _make_decision()
    conn.execute(
        "INSERT INTO decisions VALUES (?, datetime('now'), '2330', 'breakout', 'v1', 'buy', 0.8, 30000, NULL, '{}')",
        (decision.decision_id,),
    )
    broker = SimBrokerAdapter()
    candidate = _make_candidate()

    with patch("openclaw.network_allowlist.enforce_network_security", return_value="1.2.3.4"):
        result = execute_approved_order(
            conn,
            broker=broker,
            decision=decision,
            strategy_version="v1",
            symbol="2330",
            side="buy",
            qty=100,
            price=500.0,
            candidate=candidate,
            poll_interval_sec=0.0,
            poll_timeout_sec=2.0,
        )

    assert result.ok is True
    orders_count = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    assert orders_count == 1


def test_execute_approved_order_broker_rejects_submission():
    """When broker.submit_order returns rejected, ExecutionResult.ok is False."""
    conn = make_db()
    decision = _make_decision()
    conn.execute(
        "INSERT INTO decisions VALUES (?, datetime('now'), '2330', 'breakout', 'v1', 'buy', 0.8, 30000, NULL, '{}')",
        (decision.decision_id,),
    )

    bad_broker = MagicMock()
    bad_broker.submit_order.return_value = BrokerSubmission(
        broker_order_id="",
        status="rejected",
        reason="insufficient margin",
        reason_code="EXEC_INSUFFICIENT_BALANCE",
    )
    candidate = _make_candidate()

    with patch("openclaw.network_allowlist.enforce_network_security", return_value="1.2.3.4"):
        result = execute_approved_order(
            conn,
            broker=bad_broker,
            decision=decision,
            strategy_version="v1",
            symbol="2330",
            side="buy",
            qty=100,
            price=500.0,
            candidate=candidate,
        )

    assert result.ok is False
    assert result.error_code == "EXEC_INSUFFICIENT_BALANCE"


def test_execute_approved_order_broker_rejects_no_reason_code():
    """Rejected submission with empty reason_code falls back to EXEC_BROKER_REJECTED."""
    conn = make_db()
    decision = _make_decision()
    conn.execute(
        "INSERT INTO decisions VALUES (?, datetime('now'), '2330', 'breakout', 'v1', 'buy', 0.8, 30000, NULL, '{}')",
        (decision.decision_id,),
    )

    bad_broker = MagicMock()
    bad_broker.submit_order.return_value = BrokerSubmission(
        broker_order_id="",
        status="rejected",
        reason="",
        reason_code="",
    )

    with patch("openclaw.network_allowlist.enforce_network_security", return_value="1.2.3.4"):
        result = execute_approved_order(
            conn,
            broker=bad_broker,
            decision=decision,
            strategy_version="v1",
            symbol="2330",
            side="buy",
            qty=100,
            price=500.0,
            candidate=_make_candidate(),
        )

    assert result.ok is False
    assert result.error_code == "EXEC_BROKER_REJECTED"


def test_execute_approved_order_timeout_then_cancel_success():
    """Order times out; cancel_order succeeds (status='submitted')."""
    conn = make_db()
    decision = _make_decision()
    conn.execute(
        "INSERT INTO decisions VALUES (?, datetime('now'), '2330', 'breakout', 'v1', 'buy', 0.8, 30000, NULL, '{}')",
        (decision.decision_id,),
    )

    mock_broker = MagicMock()
    mock_broker.submit_order.return_value = BrokerSubmission(
        broker_order_id="BRK-TIMEOUT", status="submitted"
    )
    # poll_order_status always returns None → triggers timeout
    mock_broker.poll_order_status.return_value = None
    mock_broker.cancel_order.return_value = BrokerSubmission(
        broker_order_id="BRK-TIMEOUT", status="submitted"
    )

    with patch("openclaw.network_allowlist.enforce_network_security", return_value="1.2.3.4"):
        with patch("openclaw.main.time.sleep"):  # don't actually sleep
            result = execute_approved_order(
                conn,
                broker=mock_broker,
                decision=decision,
                strategy_version="v1",
                symbol="2330",
                side="buy",
                qty=100,
                price=500.0,
                candidate=_make_candidate(),
                poll_interval_sec=0.0,
                poll_timeout_sec=0.0,  # immediate timeout
            )

    assert result.ok is True


def test_execute_approved_order_timeout_cancel_fails():
    """Order times out; cancel_order fails → ExecutionResult.ok is False."""
    conn = make_db()
    decision = _make_decision()
    conn.execute(
        "INSERT INTO decisions VALUES (?, datetime('now'), '2330', 'breakout', 'v1', 'buy', 0.8, 30000, NULL, '{}')",
        (decision.decision_id,),
    )

    mock_broker = MagicMock()
    mock_broker.submit_order.return_value = BrokerSubmission(
        broker_order_id="BRK-CF", status="submitted"
    )
    mock_broker.poll_order_status.return_value = None
    mock_broker.cancel_order.return_value = BrokerSubmission(
        broker_order_id="BRK-CF",
        status="rejected",
        reason="cancel not allowed",
        reason_code="EXEC_CANCEL_DENIED",
    )

    with patch("openclaw.network_allowlist.enforce_network_security", return_value="1.2.3.4"):
        with patch("openclaw.main.time.sleep"):
            result = execute_approved_order(
                conn,
                broker=mock_broker,
                decision=decision,
                strategy_version="v1",
                symbol="2330",
                side="buy",
                qty=100,
                price=500.0,
                candidate=_make_candidate(),
                poll_interval_sec=0.0,
                poll_timeout_sec=0.0,
            )

    assert result.ok is False
    assert result.error_code == "EXEC_CANCEL_DENIED"


def test_execute_approved_order_timeout_cancel_fails_no_reason_code():
    """Cancel fails with empty reason_code falls back to EXEC_CANCEL_FAILED."""
    conn = make_db()
    decision = _make_decision()
    conn.execute(
        "INSERT INTO decisions VALUES (?, datetime('now'), '2330', 'breakout', 'v1', 'buy', 0.8, 30000, NULL, '{}')",
        (decision.decision_id,),
    )

    mock_broker = MagicMock()
    mock_broker.submit_order.return_value = BrokerSubmission(
        broker_order_id="BRK-CF2", status="submitted"
    )
    mock_broker.poll_order_status.return_value = None
    mock_broker.cancel_order.return_value = BrokerSubmission(
        broker_order_id="BRK-CF2",
        status="rejected",
        reason="unknown",
        reason_code="",
    )

    with patch("openclaw.network_allowlist.enforce_network_security", return_value="1.2.3.4"):
        with patch("openclaw.main.time.sleep"):
            result = execute_approved_order(
                conn,
                broker=mock_broker,
                decision=decision,
                strategy_version="v1",
                symbol="2330",
                side="buy",
                qty=100,
                price=500.0,
                candidate=_make_candidate(),
                poll_interval_sec=0.0,
                poll_timeout_sec=0.0,
            )

    assert result.ok is False
    assert result.error_code == "EXEC_CANCEL_FAILED"


def test_execute_approved_order_poll_returns_terminal():
    """If poll returns filled immediately, returns True."""
    conn = make_db()
    decision = _make_decision()
    conn.execute(
        "INSERT INTO decisions VALUES (?, datetime('now'), '2330', 'breakout', 'v1', 'buy', 0.8, 30000, NULL, '{}')",
        (decision.decision_id,),
    )

    mock_broker = MagicMock()
    mock_broker.submit_order.return_value = BrokerSubmission(
        broker_order_id="BRK-FILLED", status="submitted"
    )
    mock_broker.poll_order_status.return_value = BrokerOrderStatus(
        broker_order_id="BRK-FILLED",
        status="filled",
        filled_qty=100,
        avg_fill_price=500.0,
        fee=20.0,
        tax=30.0,
    )

    with patch("openclaw.network_allowlist.enforce_network_security", return_value="1.2.3.4"):
        with patch("openclaw.main.time.sleep"):
            result = execute_approved_order(
                conn,
                broker=mock_broker,
                decision=decision,
                strategy_version="v1",
                symbol="2330",
                side="buy",
                qty=100,
                price=500.0,
                candidate=_make_candidate(),
                poll_interval_sec=0.0,
                poll_timeout_sec=5.0,
            )

    assert result.ok is True


def test_execute_approved_order_poll_none_then_filled():
    """poll_order_status returns None once, then filled — covers the sleep/continue branch."""
    conn = make_db()
    decision = _make_decision()
    conn.execute(
        "INSERT INTO decisions VALUES (?, datetime('now'), '2330', 'breakout', 'v1', 'buy', 0.8, 30000, NULL, '{}')",
        (decision.decision_id,),
    )

    # First call returns None (hits line 204-205), second call returns filled
    filled_status = BrokerOrderStatus(
        broker_order_id="BRK-N2F",
        status="filled",
        filled_qty=100,
        avg_fill_price=500.0,
        fee=20.0,
        tax=30.0,
    )
    mock_broker = MagicMock()
    mock_broker.submit_order.return_value = BrokerSubmission(
        broker_order_id="BRK-N2F", status="submitted"
    )
    mock_broker.poll_order_status.side_effect = [None, filled_status]

    with patch("openclaw.network_allowlist.enforce_network_security", return_value="1.2.3.4"):
        with patch("openclaw.main.time.sleep"):
            result = execute_approved_order(
                conn,
                broker=mock_broker,
                decision=decision,
                strategy_version="v1",
                symbol="2330",
                side="buy",
                qty=100,
                price=500.0,
                candidate=_make_candidate(),
                poll_interval_sec=0.0,
                poll_timeout_sec=30.0,  # long enough to loop at least twice
            )

    assert result.ok is True


# ---------------------------------------------------------------------------
# main() function tests
# ---------------------------------------------------------------------------

def _make_common_patches(monkeypatch, *, resume_arg=False):
    """Helper to set up common mocks for main()."""
    import datetime as dt

    # Patch argparse to control what args main() sees
    mock_args = argparse.Namespace(db="trades.db", resume=resume_arg)
    monkeypatch.setattr("argparse.ArgumentParser.parse_args", lambda *a, **kw: mock_args)

    # Patch init_execution_tables
    monkeypatch.setattr("openclaw.main.init_execution_tables", lambda: None)

    return mock_args


def test_main_resume_flow(monkeypatch):
    """main() with --resume calls run_resume_flow and returns."""
    _make_common_patches(monkeypatch, resume_arg=True)
    monkeypatch.setattr("openclaw.main.run_resume_flow", lambda: True)
    # Should not raise
    main()


def test_main_resume_flow_failed(monkeypatch):
    """main() with --resume where run_resume_flow returns False."""
    _make_common_patches(monkeypatch, resume_arg=True)
    monkeypatch.setattr("openclaw.main.run_resume_flow", lambda: False)
    main()  # should complete without error


def test_main_self_check_needs_resume(monkeypatch):
    """main() exits early when system_self_check returns needs_resume."""
    _make_common_patches(monkeypatch, resume_arg=False)
    monkeypatch.setattr(
        "openclaw.main.system_self_check", lambda: {"status": "needs_resume"}
    )
    main()  # should print warning and return without further processing


def test_main_approved_path(monkeypatch, capsys):
    """Happy path: risk approved, order submitted successfully."""
    _make_common_patches(monkeypatch, resume_arg=False)

    # system_self_check returns ok
    monkeypatch.setattr("openclaw.main.system_self_check", lambda: {"status": "ok"})

    # Use a real in-memory DB
    mem_conn = make_db()
    monkeypatch.setattr("openclaw.main.get_connection", lambda domain: mem_conn)

    # Patch filter_locked_positions to pass through
    from openclaw.risk_engine import PortfolioState
    monkeypatch.setattr("openclaw.main.filter_locked_positions", lambda p: p)

    # Patch load_limits to return empty dict
    monkeypatch.setattr("openclaw.main.load_limits", lambda conn, q: {})

    # Patch drawdown guard — normal mode
    from openclaw.drawdown_guard import DrawdownDecision
    monkeypatch.setattr(
        "openclaw.main.evaluate_drawdown_guard",
        lambda conn, policy: DrawdownDecision(risk_mode="normal", reason_code="OK", drawdown=0.0, losing_streak_days=0),
    )
    monkeypatch.setattr(
        "openclaw.main.evaluate_strategy_health_guard",
        lambda conn, policy, sid: DrawdownDecision(risk_mode="normal", reason_code="OK", drawdown=0.0, losing_streak_days=0),
    )

    # Patch CashModeManager to return a neutral decision
    from openclaw.cash_mode import CashModeDecision
    from openclaw.risk_engine import SystemState
    mock_cash_decision = CashModeDecision(
        rating=0.8,
        cash_mode=False,
        reason_code="NORMAL",
        detail={},
    )

    class MockCashModeManager:
        def __init__(self, db_path=":memory:"):
            pass
        def evaluate(self, regime_result, system_state):
            return mock_cash_decision, system_state

    monkeypatch.setattr("openclaw.main.CashModeManager", MockCashModeManager)

    # Patch evaluate_and_build_order to approve
    from openclaw.risk_engine import OrderCandidate
    mock_result = MagicMock()
    mock_result.approved = True
    mock_result.reject_code = None
    mock_result.metrics = {}
    mock_result.order = OrderCandidate(symbol="2330", side="buy", qty=100, price=500.0)
    monkeypatch.setattr("openclaw.main.evaluate_and_build_order", lambda *a, **kw: mock_result)

    # Patch execute_approved_order to return success
    monkeypatch.setattr(
        "openclaw.main.execute_approved_order",
        lambda *a, **kw: ExecutionResult(ok=True, order_id="ORDER-OK"),
    )

    # Patch ResumeProtocolTracker
    mock_tracker = MagicMock()
    monkeypatch.setattr("openclaw.main.ResumeProtocolTracker", lambda: mock_tracker)

    main()

    captured = capsys.readouterr()
    assert "APPROVED" in captured.out


def test_main_rejected_path(monkeypatch, capsys):
    """Risk check rejected: prints REJECTED and inserts incident."""
    _make_common_patches(monkeypatch, resume_arg=False)
    monkeypatch.setattr("openclaw.main.system_self_check", lambda: {"status": "ok"})

    mem_conn = make_db()
    monkeypatch.setattr("openclaw.main.get_connection", lambda domain: mem_conn)
    monkeypatch.setattr("openclaw.main.filter_locked_positions", lambda p: p)
    monkeypatch.setattr("openclaw.main.load_limits", lambda conn, q: {})

    from openclaw.drawdown_guard import DrawdownDecision
    monkeypatch.setattr(
        "openclaw.main.evaluate_drawdown_guard",
        lambda conn, policy: DrawdownDecision(risk_mode="normal", reason_code="OK", drawdown=0.0, losing_streak_days=0),
    )
    monkeypatch.setattr(
        "openclaw.main.evaluate_strategy_health_guard",
        lambda conn, policy, sid: DrawdownDecision(risk_mode="normal", reason_code="OK", drawdown=0.0, losing_streak_days=0),
    )

    from openclaw.cash_mode import CashModeDecision
    mock_cash_decision = CashModeDecision(rating=0.8, cash_mode=False, reason_code="NORMAL", detail={})

    class MockCashModeManager:
        def __init__(self, db_path=":memory:"):
            pass
        def evaluate(self, regime_result, system_state):
            return mock_cash_decision, regime_result  # pass system_state as-is

    monkeypatch.setattr("openclaw.main.CashModeManager", MockCashModeManager)

    # evaluate_and_build_order returns rejected
    mock_result = MagicMock()
    mock_result.approved = False
    mock_result.reject_code = "RISK_LIMIT_EXCEEDED"
    mock_result.metrics = {"foo": 1}
    monkeypatch.setattr("openclaw.main.evaluate_and_build_order", lambda *a, **kw: mock_result)

    main()

    captured = capsys.readouterr()
    assert "REJECTED" in captured.out


def test_main_execution_failed_path(monkeypatch, capsys):
    """Execution order fails: prints FAILED."""
    _make_common_patches(monkeypatch, resume_arg=False)
    monkeypatch.setattr("openclaw.main.system_self_check", lambda: {"status": "ok"})

    mem_conn = make_db()
    monkeypatch.setattr("openclaw.main.get_connection", lambda domain: mem_conn)
    monkeypatch.setattr("openclaw.main.filter_locked_positions", lambda p: p)
    monkeypatch.setattr("openclaw.main.load_limits", lambda conn, q: {})

    from openclaw.drawdown_guard import DrawdownDecision
    dd_ok = DrawdownDecision(risk_mode="normal", reason_code="OK", drawdown=0.0, losing_streak_days=0)
    monkeypatch.setattr("openclaw.main.evaluate_drawdown_guard", lambda conn, policy: dd_ok)
    monkeypatch.setattr("openclaw.main.evaluate_strategy_health_guard", lambda conn, policy, sid: dd_ok)

    from openclaw.cash_mode import CashModeDecision
    from openclaw.risk_engine import SystemState

    mock_cash_decision = CashModeDecision(rating=0.8, cash_mode=False, reason_code="NORMAL", detail={})

    class MockCashModeManager:
        def __init__(self, db_path=":memory:"):
            pass
        def evaluate(self, regime_result, system_state):
            return mock_cash_decision, system_state

    monkeypatch.setattr("openclaw.main.CashModeManager", MockCashModeManager)

    mock_result = MagicMock()
    mock_result.approved = True
    mock_result.reject_code = None
    mock_result.metrics = {}
    mock_result.order = OrderCandidate(symbol="2330", side="buy", qty=100, price=500.0)
    monkeypatch.setattr("openclaw.main.evaluate_and_build_order", lambda *a, **kw: mock_result)

    # execute_approved_order returns failure
    monkeypatch.setattr(
        "openclaw.main.execute_approved_order",
        lambda *a, **kw: ExecutionResult(ok=False, order_id="ORD-FAIL", error_code="EXEC_FAILED", error_message="broker down"),
    )

    mock_tracker = MagicMock()
    monkeypatch.setattr("openclaw.main.ResumeProtocolTracker", lambda: mock_tracker)

    main()

    captured = capsys.readouterr()
    assert "FAILED" in captured.out


def test_main_exception_path(monkeypatch, capsys):
    """An exception during the transaction block is caught and printed."""
    _make_common_patches(monkeypatch, resume_arg=False)
    monkeypatch.setattr("openclaw.main.system_self_check", lambda: {"status": "ok"})

    mem_conn = make_db()
    monkeypatch.setattr("openclaw.main.get_connection", lambda domain: mem_conn)
    monkeypatch.setattr("openclaw.main.filter_locked_positions", lambda p: p)
    monkeypatch.setattr("openclaw.main.load_limits", lambda conn, q: {})

    from openclaw.drawdown_guard import DrawdownDecision
    dd_ok = DrawdownDecision(risk_mode="normal", reason_code="OK", drawdown=0.0, losing_streak_days=0)
    monkeypatch.setattr("openclaw.main.evaluate_drawdown_guard", lambda conn, policy: dd_ok)
    monkeypatch.setattr("openclaw.main.evaluate_strategy_health_guard", lambda conn, policy, sid: dd_ok)

    from openclaw.cash_mode import CashModeDecision
    mock_cash_decision = CashModeDecision(rating=0.8, cash_mode=False, reason_code="NORMAL", detail={})

    class MockCashModeManager:
        def __init__(self, db_path=":memory:"):
            pass
        def evaluate(self, regime_result, system_state):
            return mock_cash_decision, system_state

    monkeypatch.setattr("openclaw.main.CashModeManager", MockCashModeManager)

    # persist_decision raises an error
    monkeypatch.setattr(
        "openclaw.main.persist_decision",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("DB_WRITE_ERROR: disk full")),
    )

    mock_result = MagicMock()
    mock_result.approved = True
    mock_result.reject_code = None
    mock_result.metrics = {}
    mock_result.order = OrderCandidate(symbol="2330", side="buy", qty=100, price=500.0)
    monkeypatch.setattr("openclaw.main.evaluate_and_build_order", lambda *a, **kw: mock_result)

    mock_tracker = MagicMock()
    monkeypatch.setattr("openclaw.main.ResumeProtocolTracker", lambda: mock_tracker)

    main()

    captured = capsys.readouterr()
    assert "FAILED" in captured.out


def test_main_exception_with_structured_code(monkeypatch, capsys):
    """Exception message that starts with UPPER_CODE: is parsed as incident_code."""
    _make_common_patches(monkeypatch, resume_arg=False)
    monkeypatch.setattr("openclaw.main.system_self_check", lambda: {"status": "ok"})

    mem_conn = make_db()
    monkeypatch.setattr("openclaw.main.get_connection", lambda domain: mem_conn)
    monkeypatch.setattr("openclaw.main.filter_locked_positions", lambda p: p)
    monkeypatch.setattr("openclaw.main.load_limits", lambda conn, q: {})

    from openclaw.drawdown_guard import DrawdownDecision
    dd_ok = DrawdownDecision(risk_mode="normal", reason_code="OK", drawdown=0.0, losing_streak_days=0)
    monkeypatch.setattr("openclaw.main.evaluate_drawdown_guard", lambda conn, policy: dd_ok)
    monkeypatch.setattr("openclaw.main.evaluate_strategy_health_guard", lambda conn, policy, sid: dd_ok)

    from openclaw.cash_mode import CashModeDecision
    mock_cash_decision = CashModeDecision(rating=0.8, cash_mode=False, reason_code="NORMAL", detail={})

    class MockCashModeManager:
        def __init__(self, db_path=":memory:"):
            pass
        def evaluate(self, regime_result, system_state):
            return mock_cash_decision, system_state

    monkeypatch.setattr("openclaw.main.CashModeManager", MockCashModeManager)

    # Exception message has a recognizable structured code
    def _raise(*a, **kw):
        raise RuntimeError("RISK_PRICE_DEVIATION_LIMIT: price too far from market")

    monkeypatch.setattr("openclaw.main.persist_decision", _raise)

    mock_result = MagicMock()
    mock_result.approved = True
    mock_result.reject_code = None
    mock_result.metrics = {}
    mock_result.order = OrderCandidate(symbol="2330", side="buy", qty=100, price=500.0)
    monkeypatch.setattr("openclaw.main.evaluate_and_build_order", lambda *a, **kw: mock_result)

    mock_tracker = MagicMock()
    monkeypatch.setattr("openclaw.main.ResumeProtocolTracker", lambda: mock_tracker)

    main()

    captured = capsys.readouterr()
    assert "FAILED" in captured.out


def test_main_snapshot_exception_is_swallowed(monkeypatch, capsys):
    """If ResumeProtocolTracker.snapshot raises, main() still finishes."""
    _make_common_patches(monkeypatch, resume_arg=False)
    monkeypatch.setattr("openclaw.main.system_self_check", lambda: {"status": "ok"})

    mem_conn = make_db()
    monkeypatch.setattr("openclaw.main.get_connection", lambda domain: mem_conn)
    monkeypatch.setattr("openclaw.main.filter_locked_positions", lambda p: p)
    monkeypatch.setattr("openclaw.main.load_limits", lambda conn, q: {})

    from openclaw.drawdown_guard import DrawdownDecision
    dd_ok = DrawdownDecision(risk_mode="normal", reason_code="OK", drawdown=0.0, losing_streak_days=0)
    monkeypatch.setattr("openclaw.main.evaluate_drawdown_guard", lambda conn, policy: dd_ok)
    monkeypatch.setattr("openclaw.main.evaluate_strategy_health_guard", lambda conn, policy, sid: dd_ok)

    from openclaw.cash_mode import CashModeDecision
    mock_cash_decision = CashModeDecision(rating=0.8, cash_mode=False, reason_code="NORMAL", detail={})

    class MockCashModeManager:
        def __init__(self, db_path=":memory:"):
            pass
        def evaluate(self, regime_result, system_state):
            return mock_cash_decision, system_state

    monkeypatch.setattr("openclaw.main.CashModeManager", MockCashModeManager)

    mock_result = MagicMock()
    mock_result.approved = True
    mock_result.reject_code = None
    mock_result.metrics = {}
    mock_result.order = OrderCandidate(symbol="2330", side="buy", qty=100, price=500.0)
    monkeypatch.setattr("openclaw.main.evaluate_and_build_order", lambda *a, **kw: mock_result)

    monkeypatch.setattr(
        "openclaw.main.execute_approved_order",
        lambda *a, **kw: ExecutionResult(ok=True, order_id="ORD-SNAP"),
    )

    mock_tracker = MagicMock()
    mock_tracker.snapshot.side_effect = RuntimeError("snapshot DB unavailable")
    monkeypatch.setattr("openclaw.main.ResumeProtocolTracker", lambda: mock_tracker)

    main()  # must not raise

    captured = capsys.readouterr()
    assert "APPROVED" in captured.out


def test_main_drawdown_suspended(monkeypatch, capsys):
    """When drawdown guard returns suspended, trading_locked is set."""
    _make_common_patches(monkeypatch, resume_arg=False)
    monkeypatch.setattr("openclaw.main.system_self_check", lambda: {"status": "ok"})

    mem_conn = make_db()
    monkeypatch.setattr("openclaw.main.get_connection", lambda domain: mem_conn)
    monkeypatch.setattr("openclaw.main.filter_locked_positions", lambda p: p)
    monkeypatch.setattr("openclaw.main.load_limits", lambda conn, q: {})

    from openclaw.drawdown_guard import DrawdownDecision
    monkeypatch.setattr(
        "openclaw.main.evaluate_drawdown_guard",
        lambda conn, policy: DrawdownDecision(risk_mode="suspended", reason_code="DD_EXCEED", drawdown=0.2, losing_streak_days=7),
    )
    monkeypatch.setattr(
        "openclaw.main.evaluate_strategy_health_guard",
        lambda conn, policy, sid: DrawdownDecision(risk_mode="normal", reason_code="OK", drawdown=0.0, losing_streak_days=0),
    )

    from openclaw.cash_mode import CashModeDecision
    mock_cash_decision = CashModeDecision(rating=0.8, cash_mode=False, reason_code="NORMAL", detail={})

    class MockCashModeManager:
        def __init__(self, db_path=":memory:"):
            pass
        def evaluate(self, regime_result, system_state):
            return mock_cash_decision, system_state

    monkeypatch.setattr("openclaw.main.CashModeManager", MockCashModeManager)

    mock_result = MagicMock()
    mock_result.approved = False
    mock_result.reject_code = "RISK_TRADING_LOCKED"
    mock_result.metrics = {}
    monkeypatch.setattr("openclaw.main.evaluate_and_build_order", lambda *a, **kw: mock_result)

    main()

    captured = capsys.readouterr()
    assert "REJECTED" in captured.out


def test_main_strategy_health_suspended(monkeypatch, capsys):
    """When strategy health guard returns suspended, trading_locked is set."""
    _make_common_patches(monkeypatch, resume_arg=False)
    monkeypatch.setattr("openclaw.main.system_self_check", lambda: {"status": "ok"})

    mem_conn = make_db()
    monkeypatch.setattr("openclaw.main.get_connection", lambda domain: mem_conn)
    monkeypatch.setattr("openclaw.main.filter_locked_positions", lambda p: p)
    monkeypatch.setattr("openclaw.main.load_limits", lambda conn, q: {})

    from openclaw.drawdown_guard import DrawdownDecision
    monkeypatch.setattr(
        "openclaw.main.evaluate_drawdown_guard",
        lambda conn, policy: DrawdownDecision(risk_mode="normal", reason_code="OK", drawdown=0.0, losing_streak_days=0),
    )
    monkeypatch.setattr(
        "openclaw.main.evaluate_strategy_health_guard",
        lambda conn, policy, sid: DrawdownDecision(risk_mode="suspended", reason_code="STRAT_FAIL", drawdown=0.0, losing_streak_days=10),
    )

    from openclaw.cash_mode import CashModeDecision
    mock_cash_decision = CashModeDecision(rating=0.8, cash_mode=False, reason_code="NORMAL", detail={})

    class MockCashModeManager:
        def __init__(self, db_path=":memory:"):
            pass
        def evaluate(self, regime_result, system_state):
            return mock_cash_decision, system_state

    monkeypatch.setattr("openclaw.main.CashModeManager", MockCashModeManager)

    mock_result = MagicMock()
    mock_result.approved = False
    mock_result.reject_code = "RISK_TRADING_LOCKED"
    mock_result.metrics = {}
    monkeypatch.setattr("openclaw.main.evaluate_and_build_order", lambda *a, **kw: mock_result)

    main()

    captured = capsys.readouterr()
    assert "REJECTED" in captured.out


def test_main_reduce_only_mode(monkeypatch, capsys):
    """When drawdown guard returns reduce_only, reduce_only_mode is set."""
    _make_common_patches(monkeypatch, resume_arg=False)
    monkeypatch.setattr("openclaw.main.system_self_check", lambda: {"status": "ok"})

    mem_conn = make_db()
    monkeypatch.setattr("openclaw.main.get_connection", lambda domain: mem_conn)
    monkeypatch.setattr("openclaw.main.filter_locked_positions", lambda p: p)
    monkeypatch.setattr("openclaw.main.load_limits", lambda conn, q: {})

    from openclaw.drawdown_guard import DrawdownDecision
    monkeypatch.setattr(
        "openclaw.main.evaluate_drawdown_guard",
        lambda conn, policy: DrawdownDecision(risk_mode="reduce_only", reason_code="STREAK", drawdown=0.05, losing_streak_days=6),
    )
    monkeypatch.setattr(
        "openclaw.main.evaluate_strategy_health_guard",
        lambda conn, policy, sid: DrawdownDecision(risk_mode="normal", reason_code="OK", drawdown=0.0, losing_streak_days=0),
    )

    from openclaw.cash_mode import CashModeDecision
    mock_cash_decision = CashModeDecision(rating=0.8, cash_mode=False, reason_code="NORMAL", detail={})

    class MockCashModeManager:
        def __init__(self, db_path=":memory:"):
            pass
        def evaluate(self, regime_result, system_state):
            return mock_cash_decision, system_state

    monkeypatch.setattr("openclaw.main.CashModeManager", MockCashModeManager)

    mock_result = MagicMock()
    mock_result.approved = False
    mock_result.reject_code = "RISK_REDUCE_ONLY"
    mock_result.metrics = {}
    monkeypatch.setattr("openclaw.main.evaluate_and_build_order", lambda *a, **kw: mock_result)

    main()

    captured = capsys.readouterr()
    assert "REJECTED" in captured.out
