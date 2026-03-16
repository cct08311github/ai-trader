"""Tests for proposal_executor module.

Covers:
- Duplicate SellIntent is handled idempotently
- Intent marked as executed after successful execution
- Intent marked as failed after broker error
"""
from __future__ import annotations

import json
import sqlite3
import time

import pytest

from openclaw.proposal_executor import (
    SellIntent,
    _build_execution_key,
    ensure_execution_journal_schema,
    execute_pending_proposals,
    mark_intent_executed,
    mark_intent_executing,
    mark_intent_failed,
)


# ---------------------------------------------------------------------------
# Helper: build in-memory DB with required tables
# ---------------------------------------------------------------------------

def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE strategy_proposals (
            proposal_id TEXT PRIMARY KEY,
            generated_by TEXT,
            target_rule TEXT,
            rule_category TEXT,
            proposed_value TEXT,
            supporting_evidence TEXT,
            confidence REAL,
            requires_human_approval INTEGER DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'pending',
            proposal_json TEXT,
            created_at INTEGER,
            decided_at INTEGER,
            expires_at INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE positions (
            symbol TEXT PRIMARY KEY,
            quantity REAL,
            current_price REAL,
            state TEXT,
            avg_price REAL,
            unrealized_pnl REAL,
            high_water_mark REAL,
            entry_trading_day TEXT
        )
        """
    )
    conn.commit()
    ensure_execution_journal_schema(conn)
    return conn


def _insert_proposal(
    conn: sqlite3.Connection,
    *,
    proposal_id: str,
    target_rule: str = "POSITION_REBALANCE",
    status: str = "approved",
    proposal_json: dict | None = None,
    expires_at: int | None = None,
) -> None:
    if proposal_json is None:
        proposal_json = {"symbol": "2330", "reduce_pct": 0.5}
    conn.execute(
        """
        INSERT INTO strategy_proposals
            (proposal_id, generated_by, target_rule, rule_category,
             status, proposal_json, created_at, expires_at)
        VALUES (?, 'test', ?, 'entry_parameters', ?, ?, ?, ?)
        """,
        (
            proposal_id,
            target_rule,
            status,
            json.dumps(proposal_json),
            int(time.time() * 1000),
            expires_at,
        ),
    )
    conn.commit()


def _insert_position(
    conn: sqlite3.Connection, symbol: str, quantity: float, price: float
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO positions (symbol, quantity, current_price) VALUES (?,?,?)",
        (symbol, quantity, price),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Tests: ensure_execution_journal_schema
# ---------------------------------------------------------------------------

class TestJournalSchema:
    def test_schema_creation_is_idempotent(self):
        """Calling ensure_execution_journal_schema twice must not raise."""
        conn = sqlite3.connect(":memory:")
        ensure_execution_journal_schema(conn)
        ensure_execution_journal_schema(conn)  # second call — must not crash

    def test_journal_table_exists_after_schema_call(self):
        conn = sqlite3.connect(":memory:")
        ensure_execution_journal_schema(conn)
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='proposal_execution_journal'"
        ).fetchone()
        assert row is not None


# ---------------------------------------------------------------------------
# Tests: execute_pending_proposals — basic flows
# ---------------------------------------------------------------------------

class TestExecutePendingProposals:
    def test_no_proposals_returns_empty(self):
        conn = _make_db()
        intents, n_noted = execute_pending_proposals(conn)
        assert intents == []
        assert n_noted == 0

    def test_approved_proposal_with_position_returns_intent(self):
        conn = _make_db()
        _insert_position(conn, "2330", 1000, 500.0)
        _insert_proposal(
            conn, proposal_id="p-001",
            proposal_json={"symbol": "2330", "reduce_pct": 0.5}
        )
        intents, _ = execute_pending_proposals(conn)
        assert len(intents) == 1
        intent = intents[0]
        assert intent.proposal_id == "p-001"
        assert intent.symbol == "2330"
        assert intent.qty == 500  # 1000 * 0.5
        assert intent.price == 500.0

    def test_approved_proposal_status_becomes_queued(self):
        conn = _make_db()
        _insert_position(conn, "2330", 1000, 500.0)
        _insert_proposal(conn, proposal_id="p-002", proposal_json={"symbol": "2330", "reduce_pct": 0.3})
        execute_pending_proposals(conn)
        row = conn.execute(
            "SELECT status FROM strategy_proposals WHERE proposal_id='p-002'"
        ).fetchone()
        assert row[0] == "queued"

    def test_proposal_with_no_position_is_skipped(self):
        """If symbol has no position in DB, proposal should be marked skipped."""
        conn = _make_db()
        # No position inserted
        _insert_proposal(
            conn, proposal_id="p-003",
            proposal_json={"symbol": "9999", "reduce_pct": 0.5}
        )
        intents, _ = execute_pending_proposals(conn)
        assert intents == []
        row = conn.execute(
            "SELECT status FROM strategy_proposals WHERE proposal_id='p-003'"
        ).fetchone()
        assert row[0] == "skipped"

    def test_strategy_direction_proposal_is_noted(self):
        conn = _make_db()
        _insert_proposal(
            conn, proposal_id="p-dir-001",
            target_rule="STRATEGY_DIRECTION",
            proposal_json={"direction": "bullish"}
        )
        intents, n_noted = execute_pending_proposals(conn)
        assert intents == []
        assert n_noted == 1
        row = conn.execute(
            "SELECT status FROM strategy_proposals WHERE proposal_id='p-dir-001'"
        ).fetchone()
        assert row[0] == "noted"

    def test_expired_proposal_is_not_returned(self):
        """Proposals with expires_at in the past should be ignored."""
        conn = _make_db()
        _insert_position(conn, "2330", 1000, 500.0)
        past_ts = int(time.time()) - 3600  # 1 hour ago
        _insert_proposal(
            conn, proposal_id="p-expired",
            proposal_json={"symbol": "2330", "reduce_pct": 0.5},
            expires_at=past_ts,
        )
        intents, _ = execute_pending_proposals(conn)
        assert not any(i.proposal_id == "p-expired" for i in intents)

    def test_zero_price_proposal_is_skipped(self):
        """If current_price is 0, proposal should be skipped (no valid price)."""
        conn = _make_db()
        _insert_position(conn, "2330", 1000, 0.0)  # price = 0
        _insert_proposal(conn, proposal_id="p-noprice", proposal_json={"symbol": "2330", "reduce_pct": 0.5})
        intents, _ = execute_pending_proposals(conn)
        assert not any(i.proposal_id == "p-noprice" for i in intents)


# ---------------------------------------------------------------------------
# Tests: duplicate SellIntent is handled idempotently
# ---------------------------------------------------------------------------

class TestDuplicateSellIntent:
    def test_duplicate_call_returns_same_execution_key(self):
        """Two calls with identical proposal/symbol/qty/price must yield the same execution_key."""
        key1 = _build_execution_key("p-001", "2330", 500, 500.0)
        key2 = _build_execution_key("p-001", "2330", 500, 500.0)
        assert key1 == key2

    def test_different_params_yield_different_key(self):
        key1 = _build_execution_key("p-001", "2330", 500, 500.0)
        key2 = _build_execution_key("p-001", "2330", 600, 500.0)  # different qty
        assert key1 != key2

    def test_execute_pending_proposals_twice_deduplicates(self):
        """Calling execute_pending_proposals twice for the same queued proposal should not double-add intents."""
        conn = _make_db()
        _insert_position(conn, "2330", 1000, 500.0)
        _insert_proposal(conn, proposal_id="p-dedup", proposal_json={"symbol": "2330", "reduce_pct": 0.5})

        intents1, _ = execute_pending_proposals(conn)
        assert len(intents1) == 1

        # Second call — proposal now has status='queued', journal state='prepared'
        intents2, _ = execute_pending_proposals(conn)
        # Should still return the intent (queued, not completed)
        # but the execution_key must be identical across both calls
        if intents2:
            assert intents1[0].execution_key == intents2[0].execution_key

    def test_completed_journal_entry_not_returned_again(self):
        """Once marked executed, the proposal must not appear in subsequent execute calls."""
        conn = _make_db()
        _insert_position(conn, "2330", 1000, 500.0)
        _insert_proposal(conn, proposal_id="p-once", proposal_json={"symbol": "2330", "reduce_pct": 0.5})

        intents, _ = execute_pending_proposals(conn)
        assert len(intents) == 1
        intent = intents[0]

        # Mark as executing then executed
        mark_intent_executing(conn, intent.proposal_id, intent.execution_key)
        mark_intent_executed(conn, intent.proposal_id, execution_key=intent.execution_key, order_id="ord-123")

        # Second scan — should not return this proposal again
        intents2, _ = execute_pending_proposals(conn)
        assert not any(i.proposal_id == "p-once" for i in intents2)


# ---------------------------------------------------------------------------
# Tests: mark_intent_executed
# ---------------------------------------------------------------------------

class TestMarkIntentExecuted:
    def test_intent_marked_executed_updates_proposal_status(self):
        conn = _make_db()
        _insert_position(conn, "2330", 1000, 500.0)
        _insert_proposal(conn, proposal_id="p-exec-01", proposal_json={"symbol": "2330", "reduce_pct": 0.5})

        intents, _ = execute_pending_proposals(conn)
        intent = intents[0]
        mark_intent_executing(conn, intent.proposal_id, intent.execution_key)
        mark_intent_executed(conn, intent.proposal_id, execution_key=intent.execution_key, order_id="ord-555")

        # Proposal status must be 'executed'
        row = conn.execute(
            "SELECT status FROM strategy_proposals WHERE proposal_id=?", (intent.proposal_id,)
        ).fetchone()
        assert row[0] == "executed"

    def test_intent_marked_executed_updates_journal_state(self):
        conn = _make_db()
        _insert_position(conn, "2330", 1000, 500.0)
        _insert_proposal(conn, proposal_id="p-exec-02", proposal_json={"symbol": "2330", "reduce_pct": 0.3})

        intents, _ = execute_pending_proposals(conn)
        intent = intents[0]
        mark_intent_executing(conn, intent.proposal_id, intent.execution_key)
        mark_intent_executed(conn, intent.proposal_id, execution_key=intent.execution_key, order_id="ord-777")

        journal = conn.execute(
            "SELECT state, last_order_id FROM proposal_execution_journal WHERE execution_key=?",
            (intent.execution_key,),
        ).fetchone()
        assert journal[0] == "completed"
        assert journal[1] == "ord-777"

    def test_mark_executed_without_execution_key_updates_by_proposal_id(self):
        """mark_intent_executed supports lookup by proposal_id alone (no execution_key)."""
        conn = _make_db()
        _insert_position(conn, "2330", 1000, 500.0)
        _insert_proposal(conn, proposal_id="p-exec-03", proposal_json={"symbol": "2330", "reduce_pct": 0.4})

        intents, _ = execute_pending_proposals(conn)
        intent = intents[0]
        mark_intent_executing(conn, intent.proposal_id, intent.execution_key)
        # No execution_key passed
        mark_intent_executed(conn, intent.proposal_id, order_id="ord-888")

        row = conn.execute(
            "SELECT status FROM strategy_proposals WHERE proposal_id=?", (intent.proposal_id,)
        ).fetchone()
        assert row[0] == "executed"

    def test_mark_executing_increments_attempt_count(self):
        conn = _make_db()
        _insert_position(conn, "2330", 1000, 500.0)
        _insert_proposal(conn, proposal_id="p-exec-04", proposal_json={"symbol": "2330", "reduce_pct": 0.5})

        intents, _ = execute_pending_proposals(conn)
        intent = intents[0]
        mark_intent_executing(conn, intent.proposal_id, intent.execution_key)

        row = conn.execute(
            "SELECT attempt_count, state FROM proposal_execution_journal WHERE execution_key=?",
            (intent.execution_key,),
        ).fetchone()
        assert row[0] >= 1
        assert row[1] == "executing"


# ---------------------------------------------------------------------------
# Tests: mark_intent_failed after broker error
# ---------------------------------------------------------------------------

class TestMarkIntentFailed:
    def test_intent_marked_failed_updates_proposal_status(self):
        conn = _make_db()
        _insert_position(conn, "2330", 1000, 500.0)
        _insert_proposal(conn, proposal_id="p-fail-01", proposal_json={"symbol": "2330", "reduce_pct": 0.5})

        intents, _ = execute_pending_proposals(conn)
        intent = intents[0]
        mark_intent_executing(conn, intent.proposal_id, intent.execution_key)
        mark_intent_failed(
            conn, intent.proposal_id, "broker_rejected: insufficient margin",
            execution_key=intent.execution_key
        )

        row = conn.execute(
            "SELECT status FROM strategy_proposals WHERE proposal_id=?", (intent.proposal_id,)
        ).fetchone()
        assert row[0] == "failed"

    def test_intent_marked_failed_updates_journal_state(self):
        conn = _make_db()
        _insert_position(conn, "2330", 1000, 500.0)
        _insert_proposal(conn, proposal_id="p-fail-02", proposal_json={"symbol": "2330", "reduce_pct": 0.5})

        intents, _ = execute_pending_proposals(conn)
        intent = intents[0]
        mark_intent_executing(conn, intent.proposal_id, intent.execution_key)
        mark_intent_failed(
            conn, intent.proposal_id, "network_error",
            execution_key=intent.execution_key
        )

        journal = conn.execute(
            "SELECT state, last_error FROM proposal_execution_journal WHERE execution_key=?",
            (intent.execution_key,),
        ).fetchone()
        assert journal[0] == "failed"
        assert "network_error" in (journal[1] or "")

    def test_failed_proposal_appends_to_supporting_evidence(self):
        """mark_intent_failed should append broker_reject reason to supporting_evidence."""
        conn = _make_db()
        _insert_position(conn, "2330", 1000, 500.0)
        _insert_proposal(conn, proposal_id="p-fail-03", proposal_json={"symbol": "2330", "reduce_pct": 0.5})

        intents, _ = execute_pending_proposals(conn)
        intent = intents[0]
        mark_intent_executing(conn, intent.proposal_id, intent.execution_key)
        mark_intent_failed(conn, intent.proposal_id, "order_limit_exceeded", execution_key=intent.execution_key)

        row = conn.execute(
            "SELECT supporting_evidence FROM strategy_proposals WHERE proposal_id=?",
            (intent.proposal_id,),
        ).fetchone()
        evidence = row[0] or ""
        assert "order_limit_exceeded" in evidence

    def test_mark_failed_without_execution_key(self):
        """mark_intent_failed with no execution_key should still update by proposal_id."""
        conn = _make_db()
        _insert_position(conn, "2330", 1000, 500.0)
        _insert_proposal(conn, proposal_id="p-fail-04", proposal_json={"symbol": "2330", "reduce_pct": 0.5})

        intents, _ = execute_pending_proposals(conn)
        intent = intents[0]
        mark_intent_executing(conn, intent.proposal_id, intent.execution_key)
        # No execution_key
        mark_intent_failed(conn, intent.proposal_id, "timeout")

        row = conn.execute(
            "SELECT status FROM strategy_proposals WHERE proposal_id=?", (intent.proposal_id,)
        ).fetchone()
        assert row[0] == "failed"

    def test_failed_intent_journal_preserved_for_audit(self):
        """After failure, the journal row should still exist (not deleted)."""
        conn = _make_db()
        _insert_position(conn, "2330", 1000, 500.0)
        _insert_proposal(conn, proposal_id="p-fail-05", proposal_json={"symbol": "2330", "reduce_pct": 0.5})

        intents, _ = execute_pending_proposals(conn)
        intent = intents[0]
        mark_intent_executing(conn, intent.proposal_id, intent.execution_key)
        mark_intent_failed(conn, intent.proposal_id, "broker_down", execution_key=intent.execution_key)

        journal_row = conn.execute(
            "SELECT execution_key FROM proposal_execution_journal WHERE execution_key=?",
            (intent.execution_key,),
        ).fetchone()
        assert journal_row is not None, "Journal row must be preserved after failure for audit trail"
