"""Strategy Version Registry (v4 #28).

Implements strategy version control with rollback and monthly reporting.
"""

from __future__ import annotations

import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from enum import Enum


class VersionStatus(Enum):
    """Strategy version status."""
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ROLLED_BACK = "rolled_back"


class StrategyRegistry:
    """Manages strategy versions and rollbacks."""
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize with optional database path."""
        self.db_path = db_path or "data/sqlite/trades.db"
        
    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection."""
        return sqlite3.connect(self.db_path)
    
    def create_version(
        self,
        strategy_config: Dict[str, Any],
        created_by: str,
        source_proposal_id: Optional[str] = None,
        version_tag: Optional[str] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new strategy version."""
        conn = self._get_conn()
        try:
            # Ensure tables exist
            self._ensure_table_exists(conn)
            
            # Generate version ID
            import uuid
            version_id = f"v{datetime.utcnow().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
            
            # If no version tag provided, generate one
            if not version_tag:
                version_tag = f"Version {self._get_next_version_number(conn)}"
            
            # Prepare version data
            now = datetime.utcnow().isoformat()
            config_json = json.dumps(strategy_config, ensure_ascii=False)
            
            # Insert version
            conn.execute(
                """
                INSERT INTO strategy_versions (
                    version_id, version_tag, status, strategy_config_json,
                    created_by, source_proposal_id, notes, created_at, effective_from
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    version_tag,
                    VersionStatus.DRAFT.value,
                    config_json,
                    created_by,
                    source_proposal_id,
                    notes or "",
                    now,
                    now,  # effective_from defaults to creation time
                )
            )
            
            # Create audit log entry
            conn.execute(
                """
                INSERT INTO version_audit_log (
                    version_id, action, performed_by, details, performed_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    "created",
                    created_by,
                    json.dumps({"source_proposal_id": source_proposal_id, "notes": notes}),
                    now
                )
            )
            
            conn.commit()
            
            return {
                "version_id": version_id,
                "version_tag": version_tag,
                "status": VersionStatus.DRAFT.value,
                "created_at": now
            }
        finally:
            conn.close()
    
    def activate_version(self, version_id: str, activated_by: str, reason: str) -> bool:
        """Activate a version (makes it the current active version)."""
        conn = self._get_conn()
        try:
            # Deactivate current active version if exists
            current_active = self.get_active_version()
            if current_active:
                conn.execute(
                    "UPDATE strategy_versions SET status = ?, effective_to = ? WHERE version_id = ?",
                    (VersionStatus.DEPRECATED.value, datetime.utcnow().isoformat(), current_active["version_id"])
                )
                
                # Audit log for deactivation
                conn.execute(
                    """
                    INSERT INTO version_audit_log (version_id, action, performed_by, details, performed_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        current_active["version_id"],
                        "deactivated",
                        activated_by,
                        json.dumps({"reason": "Replaced by new version", "new_version": version_id}),
                        datetime.utcnow().isoformat()
                    )
                )
            
            # Activate new version
            now = datetime.utcnow().isoformat()
            conn.execute(
                """
                UPDATE strategy_versions 
                SET status = ?, effective_from = ?, effective_to = NULL
                WHERE version_id = ?
                """,
                (VersionStatus.ACTIVE.value, now, version_id)
            )
            
            # Audit log for activation
            conn.execute(
                """
                INSERT INTO version_audit_log (version_id, action, performed_by, details, performed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    "activated",
                    activated_by,
                    json.dumps({"reason": reason}),
                    now
                )
            )
            
            conn.commit()
            return True
        except Exception as e:
            print(f"Error activating version: {e}")
            return False
        finally:
            conn.close()
    
    def rollback_to_version(self, target_version_id: str, rolled_back_by: str, reason: str) -> bool:
        """Rollback to a previous version."""
        conn = self._get_conn()
        try:
            # Get target version
            target = self.get_version(target_version_id)
            if not target:
                return False
            
            # Deactivate current active version
            current_active = self.get_active_version()
            if current_active:
                conn.execute(
                    "UPDATE strategy_versions SET status = ?, effective_to = ? WHERE version_id = ?",
                    (VersionStatus.ROLLED_BACK.value, datetime.utcnow().isoformat(), current_active["version_id"])
                )
                
                # Audit log for rollback deactivation
                conn.execute(
                    """
                    INSERT INTO version_audit_log (version_id, action, performed_by, details, performed_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        current_active["version_id"],
                        "rolled_back",
                        rolled_back_by,
                        json.dumps({"reason": reason, "rolled_back_to": target_version_id}),
                        datetime.utcnow().isoformat()
                    )
                )
            
            # Create a copy of target version as new active version
            import uuid
            new_version_id = f"rb_{datetime.utcnow().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
            now = datetime.utcnow().isoformat()
            
            conn.execute(
                """
                INSERT INTO strategy_versions (
                    version_id, version_tag, status, strategy_config_json,
                    created_by, source_proposal_id, notes, created_at, effective_from,
                    rolled_back_from
                )
                SELECT ?, ?, ?, strategy_config_json,
                    ?, source_proposal_id, ?, ?, ?,
                    ?
                FROM strategy_versions WHERE version_id = ?
                """,
                (
                    new_version_id,
                    f"Rollback: {target.get('version_tag', 'Unknown')}",
                    VersionStatus.ACTIVE.value,
                    rolled_back_by,
                    f"Rollback to {target_version_id}: {reason}",
                    now,
                    now,
                    target_version_id,
                    target_version_id
                )
            )
            
            # Audit log for rollback creation
            conn.execute(
                """
                INSERT INTO version_audit_log (version_id, action, performed_by, details, performed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    new_version_id,
                    "rollback_created",
                    rolled_back_by,
                    json.dumps({"reason": reason, "rolled_back_from": target_version_id}),
                    now
                )
            )
            
            conn.commit()
            return True
        except Exception as e:
            print(f"Error rolling back: {e}")
            return False
        finally:
            conn.close()
    
    def get_active_version(self) -> Optional[Dict[str, Any]]:
        """Get currently active strategy version."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                """
                SELECT version_id, version_tag, status, strategy_config_json,
                       created_by, source_proposal_id, notes, created_at,
                       effective_from, effective_to
                FROM strategy_versions 
                WHERE status = ?
                ORDER BY effective_from DESC
                LIMIT 1
                """,
                (VersionStatus.ACTIVE.value,)
            ).fetchone()
            
            if row is None:
                return None
            
            return {
                "version_id": row[0],
                "version_tag": row[1],
                "status": row[2],
                "strategy_config": json.loads(row[3]) if row[3] else {},
                "created_by": row[4],
                "source_proposal_id": row[5],
                "notes": row[6],
                "created_at": row[7],
                "effective_from": row[8],
                "effective_to": row[9]
            }
        finally:
            conn.close()
    
    def get_version(self, version_id: str) -> Optional[Dict[str, Any]]:
        """Get specific version by ID."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                """
                SELECT version_id, version_tag, status, strategy_config_json,
                       created_by, source_proposal_id, notes, created_at,
                       effective_from, effective_to, rolled_back_from
                FROM strategy_versions 
                WHERE version_id = ?
                """,
                (version_id,)
            ).fetchone()
            
            if row is None:
                return None
            
            return {
                "version_id": row[0],
                "version_tag": row[1],
                "status": row[2],
                "strategy_config": json.loads(row[3]) if row[3] else {},
                "created_by": row[4],
                "source_proposal_id": row[5],
                "notes": row[6],
                "created_at": row[7],
                "effective_from": row[8],
                "effective_to": row[9],
                "rolled_back_from": row[10]
            }
        finally:
            conn.close()
    
    def get_version_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get version history."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT version_id, version_tag, status, created_by, created_at,
                       effective_from, effective_to
                FROM strategy_versions 
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,)
            ).fetchall()
            
            return [
                {
                    "version_id": row[0],
                    "version_tag": row[1],
                    "status": row[2],
                    "created_by": row[3],
                    "created_at": row[4],
                    "effective_from": row[5],
                    "effective_to": row[6]
                }
                for row in rows
            ]
        finally:
            conn.close()
    
    def generate_monthly_report(self, year: int, month: int) -> Dict[str, Any]:
        """Generate monthly version comparison report."""
        conn = self._get_conn()
        try:
            # Get versions effective in the month
            start_date = datetime(year, month, 1).isoformat()
            if month == 12:
                end_date = datetime(year + 1, 1, 1).isoformat()
            else:
                end_date = datetime(year, month + 1, 1).isoformat()
            
            rows = conn.execute(
                """
                SELECT version_id, version_tag, status, created_at, effective_from, effective_to
                FROM strategy_versions 
                WHERE (effective_from >= ? AND effective_from < ?)
                   OR (effective_to >= ? AND effective_to < ?)
                   OR (effective_from <= ? AND (effective_to IS NULL OR effective_to >= ?))
                ORDER BY effective_from
                """,
                (start_date, end_date, start_date, end_date, start_date, start_date)
            ).fetchall()
            
            # Calculate metrics
            total_versions = len(rows)
            active_days = self._calculate_active_days(rows, year, month)
            changes_count = sum(1 for row in rows if row[2] == VersionStatus.ACTIVE.value)
            
            return {
                "year": year,
                "month": month,
                "total_versions": total_versions,
                "active_days": active_days,
                "changes_count": changes_count,
                "versions": [
                    {
                        "version_id": row[0],
                        "version_tag": row[1],
                        "status": row[2],
                        "created_at": row[3],
                        "effective_from": row[4],
                        "effective_to": row[5]
                    }
                    for row in rows
                ]
            }
        finally:
            conn.close()
    
    def _calculate_active_days(self, rows: List[tuple], year: int, month: int) -> int:
        """Calculate number of days with active version changes."""
        # Simplified implementation
        return len(rows)
    
    def _get_next_version_number(self, conn: sqlite3.Connection) -> int:
        """Get next version number for auto-tagging."""
        row = conn.execute(
            "SELECT COUNT(*) FROM strategy_versions"
        ).fetchone()
        return row[0] + 1 if row else 1
    
    def _ensure_table_exists(self, conn: sqlite3.Connection) -> None:
        """Ensure strategy version tables exist."""
        # Create strategy_versions table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS strategy_versions (
                version_id TEXT PRIMARY KEY,
                version_tag TEXT NOT NULL,
                status TEXT NOT NULL,
                strategy_config_json TEXT NOT NULL,
                created_by TEXT NOT NULL,
                source_proposal_id TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                effective_from TEXT NOT NULL,
                effective_to TEXT,
                rolled_back_from TEXT,
                FOREIGN KEY (source_proposal_id) REFERENCES strategy_proposals(proposal_id)
            )
        """)
        
        # Create version_audit_log table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS version_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id TEXT NOT NULL,
                action TEXT NOT NULL,
                performed_by TEXT NOT NULL,
                details TEXT,
                performed_at TEXT NOT NULL,
                FOREIGN KEY (version_id) REFERENCES strategy_versions(version_id)
            )
        """)
        
        # Create indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_versions_status ON strategy_versions(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_versions_effective ON strategy_versions(effective_from, effective_to)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_version ON version_audit_log(version_id)")
        
        conn.commit()


if __name__ == "__main__":
    print("Strategy Version Registry (v4 #28)")
    print("Supports version control, rollback, and monthly reporting")
    
    # Test
    registry = StrategyRegistry(":memory:")
    print("Tables ensured")
    
    # Create a test version
    version = registry.create_version(
        strategy_config={"buy_threshold": 0.02, "sell_threshold": 0.015},
        created_by="test_user",
        version_tag="Test Version 1"
    )
    print(f"Created version: {version['version_id']}")
    
    # Activate it
    success = registry.activate_version(version["version_id"], "admin", "Initial activation")
    print(f"Activation success: {success}")
    
    # Get active version
    active = registry.get_active_version()
    print(f"Active version: {active['version_id'] if active else 'None'}")
