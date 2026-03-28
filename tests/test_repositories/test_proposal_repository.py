"""Tests for ProposalRepository."""
from __future__ import annotations

import json
import sqlite3
import time

import pytest

from openclaw.repositories.proposal_repository import ProposalRepository


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE strategy_proposals (
            proposal_id TEXT PRIMARY KEY,
            generated_by TEXT,
            target_rule TEXT,
            rule_category TEXT,
            proposed_value TEXT,
            supporting_evidence TEXT,
            confidence REAL,
            requires_human_approval INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            proposal_json TEXT,
            created_at INTEGER,
            decided_at INTEGER,
            expires_at INTEGER
        );
        CREATE TABLE proposal_execution_journal (
            execution_key TEXT PRIMARY KEY,
            proposal_id TEXT NOT NULL,
            target_rule TEXT NOT NULL,
            symbol TEXT,
            qty INTEGER,
            price REAL,
            state TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_order_id TEXT,
            last_error TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE orders (
            order_id TEXT PRIMARY KEY, symbol TEXT, side TEXT,
            status TEXT, ts_submit TEXT
        );
    """)
    return c


@pytest.fixture()
def repo(conn):
    return ProposalRepository(conn)


class TestInsertProposal:
    def test_inserts_proposal(self, conn, repo):
        repo.insert_proposal(
            proposal_id="p1",
            generated_by="concentration_guard",
            target_rule="POSITION_REBALANCE",
            confidence=0.8,
        )
        row = conn.execute("SELECT * FROM strategy_proposals WHERE proposal_id='p1'").fetchone()
        assert row["target_rule"] == "POSITION_REBALANCE"
        assert row["confidence"] == 0.8


class TestUpdateStatus:
    def test_updates_status(self, conn, repo):
        repo.insert_proposal(
            proposal_id="p1", generated_by="test", target_rule="X",
        )
        repo.update_status("p1", "approved")
        row = conn.execute("SELECT status FROM strategy_proposals WHERE proposal_id='p1'").fetchone()
        assert row["status"] == "approved"


class TestGetActionableProposals:
    def test_returns_matching_proposals(self, conn, repo):
        repo.insert_proposal(
            proposal_id="p1", generated_by="test", target_rule="X", status="approved",
        )
        repo.insert_proposal(
            proposal_id="p2", generated_by="test", target_rule="Y", status="pending",
        )
        rows = repo.get_actionable_proposals()
        assert len(rows) == 1
        assert rows[0]["proposal_id"] == "p1"


class TestExpireStaleNoted:
    def test_expires_old_noted(self, conn, repo):
        # Insert a noted proposal with old created_at
        old_ts = int(time.time() * 1000) - 72 * 60 * 60 * 1000  # 72h ago
        conn.execute(
            """INSERT INTO strategy_proposals
               (proposal_id, generated_by, target_rule, status, created_at, proposal_json)
               VALUES (?, ?, ?, 'noted', ?, '{}')""",
            ("p1", "test", "X", old_ts),
        )
        conn.commit()
        n = repo.expire_stale_noted()
        assert n == 1
        row = conn.execute("SELECT status FROM strategy_proposals WHERE proposal_id='p1'").fetchone()
        assert row["status"] == "expired"


class TestHasActiveSellOrder:
    def test_false_when_no_orders(self, repo):
        assert repo.has_active_sell_order("2330") is False

    def test_true_when_submitted_sell(self, conn, repo):
        conn.execute(
            "INSERT INTO orders VALUES ('o1', '2330', 'sell', 'submitted', '2026-03-28')"
        )
        assert repo.has_active_sell_order("2330") is True


class TestJournal:
    def test_upsert_and_load(self, conn, repo):
        repo.upsert_journal(
            execution_key="ek1", proposal_id="p1",
            target_rule="POSITION_REBALANCE",
            symbol="2330", qty=100, price=500.0,
        )
        row = repo.load_journal("ek1")
        assert row is not None
        assert row["proposal_id"] == "p1"
        assert row["state"] == "prepared"

    def test_update_journal_state(self, conn, repo):
        repo.upsert_journal(
            execution_key="ek1", proposal_id="p1",
            target_rule="X", symbol="2330", qty=100, price=500.0,
        )
        repo.update_journal_state("ek1", "executing", increment_attempt=True)
        row = repo.load_journal("ek1")
        assert row["state"] == "executing"
        assert row["attempt_count"] == 1

    def test_load_nonexistent_returns_none(self, repo):
        assert repo.load_journal("nonexistent") is None
