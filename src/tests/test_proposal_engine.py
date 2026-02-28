import sqlite3

from openclaw.proposal_engine import ProposalInput, apply_authority_decision, insert_strategy_proposal


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE strategy_proposals(
          proposal_id TEXT PRIMARY KEY,
          generated_by TEXT NOT NULL,
          target_rule TEXT NOT NULL,
          rule_category TEXT NOT NULL,
          current_value TEXT NOT NULL,
          proposed_value TEXT NOT NULL,
          supporting_evidence TEXT NOT NULL,
          source_episodes_json TEXT NOT NULL,
          backtest_sharpe_before REAL,
          backtest_sharpe_after REAL,
          confidence REAL NOT NULL,
          semantic_memory_action TEXT NOT NULL,
          rollback_version TEXT NOT NULL,
          requires_human_approval INTEGER NOT NULL DEFAULT 1,
          auto_approve_eligible INTEGER NOT NULL DEFAULT 0,
          expires_at TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          created_at TEXT NOT NULL
        );
        CREATE TABLE authority_policy(
          id INTEGER PRIMARY KEY CHECK (id = 1),
          level INTEGER NOT NULL DEFAULT 0,
          updated_at TEXT NOT NULL,
          note TEXT
        );
        INSERT INTO authority_policy(id, level, updated_at, note) VALUES (1, 2, datetime('now'), 'test');
        """
    )
    return conn


def test_auto_approve_level2():
    conn = _conn()
    p = ProposalInput(
        proposal_id="p1",
        generated_by="pm",
        target_rule="entry",
        rule_category="entry_threshold",
        current_value="2%",
        proposed_value="2.5%",
        supporting_evidence="x",
        source_episodes=["e"] * 20,
        backtest_sharpe_before=0.8,
        backtest_sharpe_after=1.0,
        confidence=0.9,
        semantic_memory_action="UPDATE",
        rollback_version="v1",
    )
    insert_strategy_proposal(conn, p)
    res = apply_authority_decision(conn, "p1")
    assert res["allowed"] is True
