"""Strategy Proposal Engine (v4 #26).

Implements structured proposal system with state machine:
- pending → approved/rejected/expired
- Telegram UI integration for review
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from enum import Enum


class ProposalStatus(Enum):
    """Proposal status states."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    AUTO_APPROVED = "auto_approved"


class AuthorityLevel(Enum):
    """Authorization levels."""
    LEVEL_0 = 0  # No autonomy
    LEVEL_1 = 1  # Observation only
    LEVEL_2 = 2  # Can propose
    LEVEL_3 = 3  # Can approve certain categories


# Level 3 forbidden categories (must have human approval)
LEVEL3_FORBIDDEN_CATEGORIES = {
    "stop_loss_logic",
    "position_sizing",
    "symbol_universe",
    "live_mode_switch",
    "monthly_drawdown_limit",
    "risk_parameters",
}


@dataclass
class StrategyProposal:
    """Strategy proposal data structure (v4 schema)."""
    proposal_id: str
    generated_by: str
    target_rule: str
    rule_category: str
    
    # Values
    current_value: Optional[str] = None
    proposed_value: Optional[str] = None
    supporting_evidence: Optional[str] = None
    
    # Metrics
    confidence: Optional[float] = None
    backtest_sharpe_before: Optional[float] = None
    backtest_sharpe_after: Optional[float] = None
    
    # Authorization
    requires_human_approval: bool = True
    status: str = "pending"
    
    # Timestamps
    expires_at: Optional[int] = None
    created_at: int = field(default_factory=lambda: int(datetime.utcnow().timestamp() * 1000))
    decided_at: Optional[int] = None
    
    # Metadata
    proposal_json: str = "{}"  # JSON blob for flexible data
    decided_by: Optional[str] = None
    decision_reason: Optional[str] = None


def create_proposal(
    conn: sqlite3.Connection,
    generated_by: str,
    target_rule: str,
    rule_category: str,
    current_value: Optional[str] = None,
    proposed_value: Optional[str] = None,
    supporting_evidence: Optional[str] = None,
    confidence: Optional[float] = None,
    backtest_sharpe_before: Optional[float] = None,
    backtest_sharpe_after: Optional[float] = None,
    auto_approve: bool = False,
    expires_days: int = 7
) -> StrategyProposal:
    """Create a new strategy proposal."""
    import uuid
    proposal_id = f"prop_{uuid.uuid4().hex[:12]}"
    
    # Calculate expiration (default 7 days)
    expires_at = int((datetime.utcnow() + timedelta(days=expires_days)).timestamp() * 1000)
    
    # Determine if human approval required
    requires_human = not _check_auto_approve_eligibility(
        rule_category, confidence, backtest_sharpe_after, backtest_sharpe_before
    )
    
    proposal = StrategyProposal(
        proposal_id=proposal_id,
        generated_by=generated_by,
        target_rule=target_rule,
        rule_category=rule_category,
        current_value=current_value,
        proposed_value=proposed_value,
        supporting_evidence=supporting_evidence,
        confidence=confidence,
        backtest_sharpe_before=backtest_sharpe_before,
        backtest_sharpe_after=backtest_sharpe_after,
        requires_human_approval=requires_human or not auto_approve,
        status="pending",
        expires_at=expires_at,
    )
    
    # Build proposal_json
    proposal.proposal_json = json.dumps({
        "target_rule": target_rule,
        "rule_category": rule_category,
        "current_value": current_value,
        "proposed_value": proposed_value,
        "backtest_sharpe_before": backtest_sharpe_before,
        "backtest_sharpe_after": backtest_sharpe_after,
        "confidence": confidence,
    }, ensure_ascii=False)
    
    _insert_proposal(conn, proposal)
    return proposal


def _check_auto_approve_eligibility(
    rule_category: str,
    confidence: Optional[float],
    backtest_sharpe_after: Optional[float],
    backtest_sharpe_before: Optional[float]
) -> bool:
    """Check if proposal is eligible for auto-approval."""
    # Cannot auto-approve Level 3 forbidden categories
    if rule_category in LEVEL3_FORBIDDEN_CATEGORIES:
        return False
    
    # Confidence threshold
    if confidence is not None and confidence < 0.85:
        return False
    
    # Must show improvement
    if backtest_sharpe_after is not None and backtest_sharpe_before is not None:
        if backtest_sharpe_after <= backtest_sharpe_before:
            return False
    
    return True


def _insert_proposal(conn: sqlite3.Connection, p: StrategyProposal) -> None:
    """Insert proposal into database.

    Compatibility: support both legacy test schema and the richer v4 migration
    schema by inserting only columns that exist.
    """

    cols = {r[1] for r in conn.execute("PRAGMA table_info(strategy_proposals)").fetchall()}

    values = {
        'proposal_id': p.proposal_id,
        'generated_by': p.generated_by,
        'target_rule': p.target_rule,
        'rule_category': p.rule_category,
        'current_value': p.current_value,
        'proposed_value': p.proposed_value,
        'supporting_evidence': p.supporting_evidence,
        'confidence': p.confidence,
        'requires_human_approval': 1 if p.requires_human_approval else 0,
        'status': p.status,
        'expires_at': p.expires_at,
        'proposal_json': p.proposal_json,
        'created_at': p.created_at,
        'decided_at': p.decided_at,
        'decided_by': p.decided_by,
        'decision_reason': p.decision_reason,
        # optional v4+ columns
        'source_episodes_json': json.dumps(getattr(p, 'source_episodes', []), ensure_ascii=False),
        'backtest_sharpe_before': p.backtest_sharpe_before,
        'backtest_sharpe_after': p.backtest_sharpe_after,
        'semantic_memory_action': getattr(p, 'semantic_memory_action', 'NONE'),
        'rollback_version': getattr(p, 'rollback_version', ''),
        'auto_approve_eligible': 1 if getattr(p, 'auto_approve_eligible', False) else 0,
    }

    preferred = [
        'proposal_id','generated_by','target_rule','rule_category',
        'current_value','proposed_value','supporting_evidence',
        'confidence','requires_human_approval','status',
        'expires_at','proposal_json','created_at','decided_at','decided_by','decision_reason',
        'source_episodes_json','backtest_sharpe_before','backtest_sharpe_after',
        'semantic_memory_action','rollback_version','auto_approve_eligible',
    ]
    insert_cols=[c for c in preferred if c in cols]
    sql=f"INSERT INTO strategy_proposals ({', '.join(insert_cols)}) VALUES ({', '.join(['?']*len(insert_cols))})"
    conn.execute(sql, tuple(values[c] for c in insert_cols))
    conn.commit()

def approve_proposal(
    conn: sqlite3.Connection,
    proposal_id: str,
    decided_by: str,
    decision_reason: Optional[str] = None
) -> Dict[str, Any]:
    """Approve a proposal."""
    proposal = _get_proposal(conn, proposal_id)
    if proposal is None:
        return {"success": False, "reason": "PROPOSAL_NOT_FOUND"}
    
    if proposal["status"] != "pending":
        return {"success": False, "reason": f"INVALID_STATUS_{proposal['status']}"}
    
    # Check expiration
    if proposal["expires_at"] and proposal["expires_at"] < int(datetime.utcnow().timestamp() * 1000):
        _expire_proposal(conn, proposal_id)
        return {"success": False, "reason": "PROPOSAL_EXPIRED"}
    
    # Update status
    now = int(datetime.utcnow().timestamp() * 1000)
    conn.execute(
        """
        UPDATE strategy_proposals 
        SET status = 'approved', decided_at = ?, decided_by = ?, decision_reason = ?
        WHERE proposal_id = ?
        """,
        (now, decided_by, decision_reason or "Approved", proposal_id)
    )
    conn.commit()
    
    return {"success": True, "proposal_id": proposal_id, "status": "approved"}


def reject_proposal(
    conn: sqlite3.Connection,
    proposal_id: str,
    decided_by: str,
    decision_reason: str
) -> Dict[str, Any]:
    """Reject a proposal."""
    proposal = _get_proposal(conn, proposal_id)
    if proposal is None:
        return {"success": False, "reason": "PROPOSAL_NOT_FOUND"}
    
    if proposal["status"] != "pending":
        return {"success": False, "reason": f"INVALID_STATUS_{proposal['status']}"}
    
    now = int(datetime.utcnow().timestamp() * 1000)
    conn.execute(
        """
        UPDATE strategy_proposals 
        SET status = 'rejected', decided_at = ?, decided_by = ?, decision_reason = ?
        WHERE proposal_id = ?
        """,
        (now, decided_by, decision_reason, proposal_id)
    )
    conn.commit()
    
    return {"success": True, "proposal_id": proposal_id, "status": "rejected"}


def _expire_proposal(conn: sqlite3.Connection, proposal_id: str) -> None:
    """Expire a proposal (internal)."""
    now = int(datetime.utcnow().timestamp() * 1000)
    conn.execute(
        """
        UPDATE strategy_proposals 
        SET status = 'expired', decided_at = ?, decision_reason = 'Auto-expired'
        WHERE proposal_id = ?
        """,
        (now, proposal_id)
    )
    conn.commit()


def expire_old_proposals(conn: sqlite3.Connection) -> int:
    """Expire all pending proposals past their expiration time."""
    now = int(datetime.utcnow().timestamp() * 1000)
    cursor = conn.execute(
        """
        UPDATE strategy_proposals 
        SET status = 'expired', decided_at = ?, decision_reason = 'Auto-expired'
        WHERE status = 'pending' AND expires_at IS NOT NULL AND expires_at < ?
        """,
        (now, now)
    )
    conn.commit()
    return cursor.rowcount


def _get_proposal(conn: sqlite3.Connection, proposal_id: str) -> Optional[Dict[str, Any]]:
    """Get proposal by ID."""
    row = conn.execute(
        "SELECT * FROM strategy_proposals WHERE proposal_id = ?",
        (proposal_id,)
    ).fetchone()
    
    if row is None:
        return None
    
    # Convert to dict
    columns = [row[1] for row in conn.execute("PRAGMA table_info(strategy_proposals)").fetchall()]
    return dict(zip(columns, row))


def get_pending_proposals(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Get all pending proposals."""
    rows = conn.execute(
        """
        SELECT * FROM strategy_proposals 
        WHERE status = 'pending' 
        ORDER BY created_at DESC
        """
    ).fetchall()
    
    columns = [row[1] for row in conn.execute("PRAGMA table_info(strategy_proposals)").fetchall()]
    return [dict(zip(columns, row)) for row in rows]


def get_proposal_history(
    conn: sqlite3.Connection, 
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Get proposal history (decided proposals)."""
    rows = conn.execute(
        """
        SELECT * FROM strategy_proposals 
        WHERE status != 'pending'
        ORDER BY decided_at DESC
        LIMIT ?
        """,
        (limit,)
    ).fetchall()
    
    columns = [row[1] for row in conn.execute("PRAGMA table_info(strategy_proposals)").fetchall()]
    return [dict(zip(columns, row)) for row in rows]


# Backward compatibility
def insert_strategy_proposal(conn: sqlite3.Connection, p: Any) -> None:
    """Legacy function for compatibility."""
    # Build a StrategyProposal using provided fields
    from datetime import datetime, timedelta
    import json
    import uuid
    
    proposal_id = getattr(p, 'proposal_id', f'prop_{uuid.uuid4().hex[:12]}')
    # expires_at as YYYY-MM-DD string (legacy schema expects TEXT)
    expires_at = (datetime.utcnow() + timedelta(days=7)).strftime('%Y-%m-%d')
    
    # Determine auto_approve eligibility
    auto_approve = getattr(p, 'auto_approve_eligible', False)
    # Check eligibility using similar logic as _check_auto_approve_eligibility
    from .proposal_engine import LEVEL3_FORBIDDEN_CATEGORIES, _check_auto_approve_eligibility
    requires_human = not _check_auto_approve_eligibility(
        getattr(p, 'rule_category', ''),
        getattr(p, 'confidence', None),
        getattr(p, 'backtest_sharpe_after', None),
        getattr(p, 'backtest_sharpe_before', None)
    )
    
    proposal = StrategyProposal(
        proposal_id=proposal_id,
        generated_by=getattr(p, 'generated_by', ''),
        target_rule=getattr(p, 'target_rule', ''),
        rule_category=getattr(p, 'rule_category', ''),
        current_value=getattr(p, 'current_value', None),
        proposed_value=getattr(p, 'proposed_value', None),
        supporting_evidence=getattr(p, 'supporting_evidence', None),
        confidence=getattr(p, 'confidence', None),
        backtest_sharpe_before=getattr(p, 'backtest_sharpe_before', None),
        backtest_sharpe_after=getattr(p, 'backtest_sharpe_after', None),
        requires_human_approval=requires_human or not auto_approve,
        status='pending',
        expires_at=expires_at,
    )
    # Add extra fields for legacy schema
    proposal.source_episodes = getattr(p, 'source_episodes', [])
    proposal.semantic_memory_action = getattr(p, 'semantic_memory_action', 'NONE')
    proposal.rollback_version = getattr(p, 'rollback_version', '')
    proposal.auto_approve_eligible = 1 if auto_approve else 0
    
    # Insert using _insert_proposal
    _insert_proposal(conn, proposal)

def get_authority_level(conn: sqlite3.Connection) -> int:
    """Get current authority level (for backward compatibility)."""
    # Default to LEVEL_2 (can propose)
    return 2


# Telegram UI helpers
def format_proposal_for_telegram(proposal: Dict[str, Any]) -> str:
    """Format proposal for Telegram display."""
    status_emoji = {
        "pending": "⏳",
        "approved": "✅",
        "rejected": "❌",
        "expired": "⏰",
    }
    
    emoji = status_emoji.get(proposal.get("status", ""), "❓")
    
    text = f"""
📋 <b>策略提案</b> {emoji}

<b>ID:</b> <code>{proposal.get('proposal_id', 'N/A')}</code>
<b>規則:</b> {proposal.get('target_rule', 'N/A')}
<b>類別:</b> {proposal.get('rule_category', 'N/A')}

<b>現值:</b>
<pre>{proposal.get('current_value', 'N/A')}</pre>

<b>提議值:</b>
<pre>{proposal.get('proposed_value', 'N/A')}</pre>

<b>信心度:</b> {proposal.get('confidence', 'N/A')}
<b>狀態:</b> {proposal.get('status', 'N/A').upper()}
<b>創建時間:</b> {datetime.fromtimestamp(proposal.get('created_at', 0)/1000)}
"""
    
    return text


if __name__ == "__main__":
    print("Strategy Proposal Engine (v4 #26)")
    print("Supports: pending → approved/rejected/expired state machine")

# Backward compatibility for ref_package tests
def apply_authority_decision(conn: sqlite3.Connection, proposal_id: str) -> Dict[str, Any]:
    """
    Legacy function for ref_package test compatibility.
    """
    row = conn.execute(
        """
        SELECT rule_category, auto_approve_eligible, expires_at, status
        FROM strategy_proposals
        WHERE proposal_id = ?
        """,
        (proposal_id,),
    ).fetchone()
    if row is None:
        raise ValueError("proposal not found")

    category, eligible, expires_at, status = row
    if status != "pending":
        return {"allowed": False, "reason_code": "AUTH_NOT_PENDING"}
    if category in LEVEL3_FORBIDDEN_CATEGORIES:
        return {"allowed": False, "reason_code": "AUTH_LEVEL3_FORBIDDEN"}
    if expires_at < datetime.utcnow().strftime("%Y-%m-%d"):
        conn.execute("UPDATE strategy_proposals SET status='expired' WHERE proposal_id = ?", (proposal_id,))
        return {"allowed": False, "reason_code": "AUTH_PROPOSAL_EXPIRED"}

    level = get_authority_level(conn)
    if level < 2 or int(eligible) != 1:
        return {"allowed": False, "reason_code": "AUTH_MANUAL_REQUIRED"}

    conn.execute("UPDATE strategy_proposals SET status='auto_approved' WHERE proposal_id = ?", (proposal_id,))
    return {"allowed": True, "reason_code": "AUTH_AUTO_APPROVED"}
