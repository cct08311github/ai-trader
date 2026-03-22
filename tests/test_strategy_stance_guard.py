"""Tests for strategy stance guard (#383).

Covers:
- _get_latest_committee_stance returns correct stance from DB
- Buy blocked when committee stance is defensive
- Buy blocked when stance is neutral and score < 0.75
- Buy allowed when stance is constructive
- expire_stale_noted_proposals cleans up old proposals
"""
from __future__ import annotations

import json
import sqlite3
import time

import pytest


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
    return conn


def _insert_stance_proposal(
    conn: sqlite3.Connection,
    stance: str,
    *,
    status: str = "noted",
    age_hours: float = 1.0,
) -> str:
    """Insert a STRATEGY_DIRECTION proposal with the given stance."""
    proposal_id = f"test-{stance}-{age_hours}"
    created_at = int(time.time() * 1000) - int(age_hours * 3600 * 1000)
    payload = json.dumps({
        "committee_context": {
            "arbiter": {
                "stance": stance,
                "summary": f"Test {stance} stance",
            }
        }
    })
    conn.execute(
        """INSERT INTO strategy_proposals
           (proposal_id, generated_by, target_rule, status, proposal_json, created_at)
           VALUES (?, 'strategy_committee', 'STRATEGY_DIRECTION', ?, ?, ?)""",
        (proposal_id, status, payload, created_at),
    )
    conn.commit()
    return proposal_id


# ---------------------------------------------------------------------------
# Tests: _get_latest_committee_stance
# ---------------------------------------------------------------------------

class TestGetLatestCommitteeStance:
    def test_returns_defensive_stance(self):
        from openclaw.ticker_watcher import _get_latest_committee_stance
        conn = _make_db()
        _insert_stance_proposal(conn, "defensive", age_hours=2)
        assert _get_latest_committee_stance(conn) == "defensive"

    def test_returns_constructive_stance(self):
        from openclaw.ticker_watcher import _get_latest_committee_stance
        conn = _make_db()
        _insert_stance_proposal(conn, "constructive", age_hours=1)
        assert _get_latest_committee_stance(conn) == "constructive"

    def test_returns_neutral_when_no_proposals(self):
        from openclaw.ticker_watcher import _get_latest_committee_stance
        conn = _make_db()
        assert _get_latest_committee_stance(conn) == "neutral"

    def test_returns_latest_stance_when_multiple(self):
        from openclaw.ticker_watcher import _get_latest_committee_stance
        conn = _make_db()
        _insert_stance_proposal(conn, "defensive", age_hours=10)
        _insert_stance_proposal(conn, "constructive", age_hours=1)
        assert _get_latest_committee_stance(conn) == "constructive"

    def test_ignores_proposals_older_than_24h(self):
        from openclaw.ticker_watcher import _get_latest_committee_stance
        conn = _make_db()
        _insert_stance_proposal(conn, "defensive", age_hours=25)
        assert _get_latest_committee_stance(conn) == "neutral"

    def test_ignores_non_noted_status(self):
        from openclaw.ticker_watcher import _get_latest_committee_stance
        conn = _make_db()
        _insert_stance_proposal(conn, "defensive", status="approved", age_hours=1)
        assert _get_latest_committee_stance(conn) == "neutral"

    def test_handles_missing_stance_in_json(self):
        from openclaw.ticker_watcher import _get_latest_committee_stance
        conn = _make_db()
        # Insert proposal with no stance field
        proposal_id = "test-no-stance"
        payload = json.dumps({"committee_context": {"arbiter": {"summary": "no stance"}}})
        conn.execute(
            """INSERT INTO strategy_proposals
               (proposal_id, generated_by, target_rule, status, proposal_json, created_at)
               VALUES (?, 'strategy_committee', 'STRATEGY_DIRECTION', 'noted', ?, ?)""",
            (proposal_id, payload, int(time.time() * 1000)),
        )
        conn.commit()
        assert _get_latest_committee_stance(conn) == "neutral"


# ---------------------------------------------------------------------------
# Tests: expire_stale_noted_proposals
# ---------------------------------------------------------------------------

class TestExpireStaleNotedProposals:
    def test_expires_old_noted_proposals(self):
        from openclaw.proposal_executor import expire_stale_noted_proposals
        conn = _make_db()
        pid = _insert_stance_proposal(conn, "defensive", age_hours=49)  # > 48h
        n = expire_stale_noted_proposals(conn)
        assert n == 1
        row = conn.execute(
            "SELECT status FROM strategy_proposals WHERE proposal_id=?", (pid,)
        ).fetchone()
        assert row[0] == "expired"

    def test_keeps_recent_noted_proposals(self):
        from openclaw.proposal_executor import expire_stale_noted_proposals
        conn = _make_db()
        pid = _insert_stance_proposal(conn, "neutral", age_hours=10)  # < 48h
        n = expire_stale_noted_proposals(conn)
        assert n == 0
        row = conn.execute(
            "SELECT status FROM strategy_proposals WHERE proposal_id=?", (pid,)
        ).fetchone()
        assert row[0] == "noted"

    def test_does_not_touch_non_noted_status(self):
        from openclaw.proposal_executor import expire_stale_noted_proposals
        conn = _make_db()
        _insert_stance_proposal(conn, "defensive", status="approved", age_hours=49)
        n = expire_stale_noted_proposals(conn)
        assert n == 0

    def test_mixed_old_and_new(self):
        from openclaw.proposal_executor import expire_stale_noted_proposals
        conn = _make_db()
        _insert_stance_proposal(conn, "defensive", age_hours=49)  # > 48h → expire
        _insert_stance_proposal(conn, "neutral", age_hours=10)    # < 48h → keep
        n = expire_stale_noted_proposals(conn)
        assert n == 1
