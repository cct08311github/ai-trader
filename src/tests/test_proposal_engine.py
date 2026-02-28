import sqlite3

from openclaw.proposal_engine import (
    approve_proposal,
    create_proposal,
    expire_old_proposals,
    reject_proposal,
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    # Minimal schema matching current proposal_engine.py expectations.
    conn.executescript(
        """
        CREATE TABLE strategy_proposals(
          proposal_id TEXT PRIMARY KEY,
          generated_by TEXT NOT NULL,
          target_rule TEXT NOT NULL,
          rule_category TEXT NOT NULL,
          current_value TEXT,
          proposed_value TEXT,
          supporting_evidence TEXT,
          confidence REAL,
          requires_human_approval INTEGER NOT NULL DEFAULT 1,
          status TEXT NOT NULL DEFAULT 'pending',
          expires_at INTEGER,
          proposal_json TEXT NOT NULL,
          created_at INTEGER NOT NULL,
          decided_at INTEGER,
          decided_by TEXT,
          decision_reason TEXT
        );
        """
    )
    return conn


def test_create_proposal_inserts_pending_row():
    conn = _conn()
    p = create_proposal(
        conn,
        generated_by="pm",
        target_rule="entry_threshold",
        rule_category="entry_threshold",
        current_value="2%",
        proposed_value="2.5%",
        supporting_evidence="test",
        confidence=0.9,
        backtest_sharpe_before=0.8,
        backtest_sharpe_after=1.0,
    )
    row = conn.execute(
        "SELECT status, generated_by, target_rule, rule_category FROM strategy_proposals WHERE proposal_id=?",
        (p.proposal_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == "pending"
    assert row[1] == "pm"


def test_approve_and_reject_transitions():
    conn = _conn()
    p = create_proposal(
        conn,
        generated_by="pm",
        target_rule="entry",
        rule_category="entry_threshold",
        current_value="2%",
        proposed_value="2.5%",
        supporting_evidence="x",
        confidence=0.9,
    )

    ok = approve_proposal(conn, p.proposal_id, decided_by="human", decision_reason="ok")
    assert ok["success"] is True
    assert ok["status"] == "approved"

    # cannot reject once approved
    bad = reject_proposal(conn, p.proposal_id, decided_by="human", decision_reason="no")
    assert bad["success"] is False


def test_expire_old_proposals_marks_expired():
    conn = _conn()
    p = create_proposal(
        conn,
        generated_by="pm",
        target_rule="entry",
        rule_category="entry_threshold",
        current_value="2%",
        proposed_value="2.5%",
        supporting_evidence="x",
        confidence=0.9,
        expires_days=-1,  # already expired
    )

    n = expire_old_proposals(conn)
    assert n >= 1
    row = conn.execute("SELECT status FROM strategy_proposals WHERE proposal_id=?", (p.proposal_id,)).fetchone()
    assert row[0] == "expired"
