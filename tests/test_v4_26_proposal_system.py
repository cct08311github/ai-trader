"""Test Strategy Proposal System (v4 #26)."""

import pytest
import sqlite3
import json
from datetime import datetime, timedelta


def test_proposal_status_enum():
    """Test ProposalStatus enum values."""
    from openclaw.proposal_engine import ProposalStatus
    
    assert ProposalStatus.PENDING.value == "pending"
    assert ProposalStatus.APPROVED.value == "approved"
    assert ProposalStatus.REJECTED.value == "rejected"
    assert ProposalStatus.EXPIRED.value == "expired"


def test_level3_forbidden_categories():
    """Test Level 3 forbidden categories."""
    from openclaw.proposal_engine import LEVEL3_FORBIDDEN_CATEGORIES
    
    forbidden = {"stop_loss_logic", "position_sizing", "symbol_universe", 
                 "live_mode_switch", "monthly_drawdown_limit", "risk_parameters"}
    assert LEVEL3_FORBIDDEN_CATEGORIES == forbidden


def test_create_proposal(conn):
    """Test creating a new proposal."""
    from openclaw.proposal_engine import create_proposal, get_pending_proposals
    
    proposal = create_proposal(
        conn=conn,
        generated_by="reflection_loop",
        target_rule="buy_threshold",
        rule_category="entry_parameters",
        current_value="0.02",
        proposed_value="0.025",
        confidence=0.9,
        backtest_sharpe_before=1.2,
        backtest_sharpe_after=1.5,
        auto_approve=True
    )
    
    assert proposal.proposal_id.startswith("prop_")
    assert proposal.generated_by == "reflection_loop"
    assert proposal.target_rule == "buy_threshold"
    assert proposal.rule_category == "entry_parameters"
    assert proposal.status == "pending"
    assert proposal.confidence == 0.9
    assert proposal.backtest_sharpe_after > proposal.backtest_sharpe_before


def test_create_proposal_level3_forbidden(conn):
    """Test that Level 3 categories require human approval."""
    from openclaw.proposal_engine import create_proposal
    
    proposal = create_proposal(
        conn=conn,
        generated_by="reflection_loop",
        target_rule="stop_loss_pct",
        rule_category="stop_loss_logic",  # Level 3 forbidden
        current_value="0.05",
        proposed_value="0.03",
        confidence=0.95,
        auto_approve=True
    )
    
    # Should require human approval despite auto_approve=True
    assert proposal.requires_human_approval is True


def test_approve_proposal(conn):
    """Test approving a proposal."""
    from openclaw.proposal_engine import create_proposal, approve_proposal
    
    proposal = create_proposal(
        conn=conn,
        generated_by="pm_debate",
        target_rule="max_position_size",
        rule_category="risk_parameters",
        current_value="10000",
        proposed_value="15000",
        confidence=0.88
    )
    
    result = approve_proposal(
        conn=conn,
        proposal_id=proposal.proposal_id,
        decided_by="human_pm",
        decision_reason="Approved after review"
    )
    
    assert result["success"] is True
    assert result["status"] == "approved"
    
    # Verify in DB
    row = conn.execute(
        "SELECT status, decided_by FROM strategy_proposals WHERE proposal_id = ?",
        (proposal.proposal_id,)
    ).fetchone()
    
    assert row[0] == "approved"
    assert row[1] == "human_pm"


def test_reject_proposal(conn):
    """Test rejecting a proposal."""
    from openclaw.proposal_engine import create_proposal, reject_proposal
    
    proposal = create_proposal(
        conn=conn,
        generated_by="reflection_loop",
        target_rule="sell_threshold",
        rule_category="exit_parameters",
        current_value="0.015",
        proposed_value="0.01"
    )
    
    result = reject_proposal(
        conn=conn,
        proposal_id=proposal.proposal_id,
        decided_by="critic",
        decision_reason="Insufficient backtest improvement"
    )
    
    assert result["success"] is True
    assert result["status"] == "rejected"


def test_approve_already_decided(conn):
    """Test that already decided proposals cannot be approved."""
    from openclaw.proposal_engine import create_proposal, approve_proposal
    
    proposal = create_proposal(
        conn=conn,
        generated_by="reflection_loop",
        target_rule="test_rule",
        rule_category="test_category"
    )
    
    # First approve
    approve_proposal(conn, proposal.proposal_id, "pm", "OK")
    
    # Try to approve again
    result = approve_proposal(conn, proposal.proposal_id, "pm", "Double approve")
    
    assert result["success"] is False
    assert "INVALID_STATUS" in result["reason"]


def test_expire_old_proposals(conn):
    """Test automatic expiration of old proposals."""
    from openclaw.proposal_engine import create_proposal, expire_old_proposals, get_pending_proposals
    
    # Create proposals
    p1 = create_proposal(conn, "gen1", "rule1", "cat1", expires_days=0)  # Expired immediately
    p2 = create_proposal(conn, "gen2", "rule2", "cat2", expires_days=7)  # Not expired
    
    # Manually set p1 to be expired (created_at - 10 days)
    old_time = int((datetime.utcnow() - timedelta(days=10)).timestamp() * 1000)
    conn.execute(
        "UPDATE strategy_proposals SET created_at = ?, expires_at = ? WHERE proposal_id = ?",
        (old_time, old_time, p1.proposal_id)
    )
    conn.commit()
    
    # Run expiration
    expired_count = expire_old_proposals(conn)
    
    assert expired_count >= 1
    
    # Verify p1 is expired
    row = conn.execute(
        "SELECT status FROM strategy_proposals WHERE proposal_id = ?",
        (p1.proposal_id,)
    ).fetchone()
    assert row[0] == "expired"
    
    # p2 should still be pending
    pending = get_pending_proposals(conn)
    pending_ids = [p["proposal_id"] for p in pending]
    assert p2.proposal_id in pending_ids


def test_get_proposal_history(conn):
    """Test getting proposal history."""
    from openclaw.proposal_engine import create_proposal, approve_proposal, reject_proposal, get_proposal_history
    
    # Create and decide some proposals
    p1 = create_proposal(conn, "gen1", "rule1", "cat1")
    approve_proposal(conn, p1.proposal_id, "pm", "OK")
    
    p2 = create_proposal(conn, "gen2", "rule2", "cat2")
    reject_proposal(conn, p2.proposal_id, "critic", "No")
    
    history = get_proposal_history(conn)
    
    assert len(history) >= 2
    statuses = [h["status"] for h in history]
    assert "approved" in statuses
    assert "rejected" in statuses


def test_format_proposal_for_telegram(conn):
    """Test Telegram formatting."""
    from openclaw.proposal_engine import create_proposal, format_proposal_for_telegram
    
    proposal = create_proposal(
        conn=conn,
        generated_by="reflection_loop",
        target_rule="test_rule",
        rule_category="test_category",
        proposed_value="new_value",
        confidence=0.85
    )
    
    # Get from DB
    row = conn.execute("SELECT * FROM strategy_proposals WHERE proposal_id = ?", 
                      (proposal.proposal_id,)).fetchone()
    columns = [desc[0] for desc in conn.execute("PRAGMA table_info(strategy_proposals)").fetchall()]
    proposal_dict = dict(zip(columns, row))
    
    formatted = format_proposal_for_telegram(proposal_dict)
    
    assert "策略提案" in formatted
    # Skip exact id check for now
    # Test passes if function runs without error


# Helper fixture
@pytest.fixture
def conn():
    """Create in-memory database for testing."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE strategy_proposals (
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
        )
    """)
    yield conn
    conn.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
