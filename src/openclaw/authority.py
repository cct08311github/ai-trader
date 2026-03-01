"""Authority Boundary Engine (v4 #29).

Implements Level 0-3 authorization boundary with Level 3 forbidden categories.
"""

from __future__ import annotations

import sqlite3
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from enum import IntEnum


class AuthorityLevel(IntEnum):
    """Authorization levels (0-3)."""
    LEVEL_0 = 0  # Observe only, no actions
    LEVEL_1 = 1  # Log only, no real actions
    LEVEL_2 = 2  # Can propose, requires human approval
    LEVEL_3 = 3  # Can auto-approve non-sensitive categories


# Level 3 forbidden categories (must have human approval)
# Aligns with proposal_engine.LEVEL3_FORBIDDEN_CATEGORIES
LEVEL3_FORBIDDEN_CATEGORIES = {
    "stop_loss_logic",
    "position_sizing",
    "symbol_universe",
    "live_mode_switch",
    "monthly_drawdown_limit",
    "risk_parameters",
}


class AuthorityEngine:
    """Manages authorization boundaries."""
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize with optional database path."""
        self.db_path = db_path or "data/sqlite/trades.db"
        
    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection."""
        return sqlite3.connect(self.db_path)
    
    def get_current_level(self) -> AuthorityLevel:
        """Get current authority level from database."""
        conn = self._get_conn()
        try:
            # Check if authority_policy table exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='authority_policy'"
            )
            if cursor.fetchone() is None:
                # Table doesn't exist, default to LEVEL_2
                return AuthorityLevel.LEVEL_2
            
            # Get current level
            row = conn.execute(
                "SELECT level, effective_from FROM authority_policy WHERE id = 1"
            ).fetchone()
            
            if row is None:
                # No policy set, default to LEVEL_2
                return AuthorityLevel.LEVEL_2
            
            level, effective_from = row
            try:
                return AuthorityLevel(int(level))
            except (ValueError, TypeError):
                return AuthorityLevel.LEVEL_2
        finally:
            conn.close()

    def set_level(self, level: AuthorityLevel, changed_by: str, reason: str) -> bool:

        """Set authority level (requires audit log)."""
        # Check compliance restriction: cannot raise to LEVEL_3 if compliance not complete
        if level == AuthorityLevel.LEVEL_3 and not self.check_compliance_complete():
            print(f"ERROR: Cannot raise authority to LEVEL_3 because compliance is not complete.")
            # Log this attempt
            import logging
            logging.warning(f"Attempt to raise authority to LEVEL_3 blocked due to incomplete compliance. Changed by: {changed_by}, reason: {reason}")
            return False
        
        conn = self._get_conn()
        try:
            # Ensure table exists
            self._ensure_table_exists(conn)
            
            # Update level
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                INSERT OR REPLACE INTO authority_policy (id, level, changed_by, reason, effective_from, updated_at)
                VALUES (1, ?, ?, ?, ?, ?)
                """,
                (level.value, changed_by, reason, now, now)
            )
            
            # Create audit log
            conn.execute(
                """
                INSERT INTO authority_audit_log (old_level, new_level, changed_by, reason, changed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (self.get_current_level().value, level.value, changed_by, reason, now)
            )
            
            conn.commit()
            return True
        except Exception as e:
            print(f"Error setting authority level: {e}")
            return False
        finally:
            conn.close()
    
    def can_propose(self) -> bool:
        """Check if system can propose changes."""
        level = self.get_current_level()
        return level >= AuthorityLevel.LEVEL_2
    
    def can_auto_approve(self, rule_category: str) -> bool:
        """
        Check if system can auto-approve a proposal.
        
        Requirements:
        1. Level must be LEVEL_3
        2. Rule category must NOT be in LEVEL3_FORBIDDEN_CATEGORIES
        """
        level = self.get_current_level()
        
        if level != AuthorityLevel.LEVEL_3:
            return False
        
        if rule_category in LEVEL3_FORBIDDEN_CATEGORIES:
            return False
        
        return True
    
    def check_proposal_authorization(self, proposal_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check authorization for a proposal.
        
        Returns:
            {
                "allowed": bool,
                "level": int,
                "requires_human_approval": bool,
                "reason_code": str,
                "reason": str
            }
        """
        current_level = self.get_current_level()
        
        # Level 0 or 1 cannot propose
        if current_level <= AuthorityLevel.LEVEL_1:
            return {
                "allowed": False,
                "level": current_level.value,
                "requires_human_approval": True,
                "reason_code": "AUTH_LEVEL_TOO_LOW",
                "reason": f"Current level {current_level.value} cannot propose changes"
            }
        
        # Extract rule category
        rule_category = proposal_data.get("rule_category", "")
        
        # Check if auto-approval is possible
        if self.can_auto_approve(rule_category):
            return {
                "allowed": True,
                "level": current_level.value,
                "requires_human_approval": False,
                "reason_code": "AUTH_AUTO_APPROVE_ALLOWED",
                "reason": f"Level {current_level.value} can auto-approve non-sensitive category"
            }
        
        # Level 2 or Level 3 with forbidden category requires human approval
        return {
            "allowed": True,
            "level": current_level.value,
            "requires_human_approval": True,
            "reason_code": "AUTH_MANUAL_REQUIRED",
            "reason": f"Category '{rule_category}' requires human approval"
        }
    
    def get_audit_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get authority change audit log."""
        conn = self._get_conn()
        try:
            # Check if audit table exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='authority_audit_log'"
            )
            if cursor.fetchone() is None:
                return []
            
            rows = conn.execute(
                """
                SELECT old_level, new_level, changed_by, reason, changed_at
                FROM authority_audit_log
                ORDER BY changed_at DESC
                LIMIT ?
                """,
                (limit,)
            ).fetchall()
            
            return [
                {
                    "old_level": row[0],
                    "new_level": row[1],
                    "changed_by": row[2],
                    "reason": row[3],
                    "changed_at": row[4]
                }
                for row in rows
            ]
        finally:
            conn.close()

    def check_compliance_complete(self) -> bool:
        """
        Check if all required compliance items are completed.
        
        Returns:
            True if all required compliance items are completed, False otherwise.
            If no compliance items are defined, returns True (no compliance requirements).
        """
        conn = self._get_conn()
        try:
            # Check if compliance_status table exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='compliance_status'"
            )
            if cursor.fetchone() is None:
                # Table doesn't exist, assume compliance not complete
                return False
            
            # Check if all required compliance items are completed
            # Required items are those with requirement_id starting with 'REQ_'
            rows = conn.execute(
                """
                SELECT COUNT(*) as total, 
                       SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed
                FROM compliance_status
                WHERE requirement_id LIKE 'REQ_%'
                """
            ).fetchone()
            
            total, completed = rows
            if total == 0:
                # No required compliance items defined, assume compliance requirements are satisfied
                return True
            
            return completed == total
        except Exception as e:
            # Log error and assume compliance not complete
            import logging
            logging.error(f"Error checking compliance: {e}")
            return False
        finally:
            conn.close()
    
    def _ensure_table_exists(self, conn: sqlite3.Connection) -> None:
        """Ensure authority tables exist."""
        # Create authority_policy table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS authority_policy (
                id INTEGER PRIMARY KEY,
                level INTEGER NOT NULL,
                changed_by TEXT NOT NULL,
                reason TEXT NOT NULL,
                effective_from TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        # Create authority_audit_log table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS authority_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                old_level INTEGER NOT NULL,
                new_level INTEGER NOT NULL,
                changed_by TEXT NOT NULL,
                reason TEXT NOT NULL,
                changed_at TEXT NOT NULL
            )
        """)
        
        # Create compliance_status table for regulatory compliance tracking
        conn.execute("""
            CREATE TABLE IF NOT EXISTS compliance_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requirement_id TEXT UNIQUE NOT NULL,
                description TEXT,
                status TEXT CHECK(status IN ('not_started', 'in_progress', 'completed')),
                completed_date TEXT,
                evidence_path TEXT,
                responsible_person TEXT,
                last_updated TEXT
            )
        """)
        
        # Create compliance_audit_log table for tracking compliance changes
        conn.execute("""
            CREATE TABLE IF NOT EXISTS compliance_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requirement_id TEXT NOT NULL,
                old_status TEXT,
                new_status TEXT,
                changed_by TEXT NOT NULL,
                reason TEXT,
                changed_at TEXT NOT NULL
            )
        """)
        
        conn.commit()


# Backward compatibility function for proposal_engine.py
def get_authority_level(conn: sqlite3.Connection) -> int:
    """Backward compatibility function for existing code."""
    engine = AuthorityEngine()
    return engine.get_current_level().value


if __name__ == "__main__":
    print("Authority Boundary Engine (v4 #29)")
    print("Supports Level 0-3 authorization with Level 3 guardrails")
    
    # Test
    engine = AuthorityEngine()
    level = engine.get_current_level()
    print(f"Current level: {level} ({level.value})")
    print(f"Can propose: {engine.can_propose()}")
    print(f"Can auto-approve 'entry_parameters': {engine.can_auto_approve('entry_parameters')}")
    print(f"Can auto-approve 'stop_loss_logic': {engine.can_auto_approve('stop_loss_logic')}")
