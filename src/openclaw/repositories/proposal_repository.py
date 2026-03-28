"""proposal_repository.py — Data access for strategy_proposals and execution journal.

Encapsulates SQL operations on ``strategy_proposals`` and
``proposal_execution_journal`` tables, used by proposal_executor.py,
proposal_engine.py, and concentration_guard.py.
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional


def _now_ms() -> int:
    return int(time.time() * 1000)


class ProposalRepository:
    """Encapsulates strategy_proposals + proposal_execution_journal access."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── strategy_proposals reads ────────────────────────────────────────

    def get_actionable_proposals(
        self,
        statuses: tuple[str, ...] = ("approved", "queued", "executing"),
    ) -> List[sqlite3.Row]:
        """Return proposals with given statuses that haven't expired."""
        placeholders = ",".join("?" * len(statuses))
        return self._conn.execute(
            f"""SELECT proposal_id, target_rule, proposal_json, status
               FROM strategy_proposals
               WHERE status IN ({placeholders})
                 AND (expires_at IS NULL OR expires_at > ?)""",
            (*statuses, int(time.time())),
        ).fetchall()

    def get_pending_by_rule(
        self,
        target_rule: str,
        statuses: tuple[str, ...] = ("pending",),
    ) -> List[sqlite3.Row]:
        placeholders = ",".join("?" * len(statuses))
        return self._conn.execute(
            f"""SELECT * FROM strategy_proposals
               WHERE target_rule = ? AND status IN ({placeholders})
               ORDER BY created_at DESC""",
            (target_rule, *statuses),
        ).fetchall()

    def get_recent_by_rule(
        self,
        target_rule: str,
        since_ms: int,
    ) -> List[sqlite3.Row]:
        return self._conn.execute(
            """SELECT * FROM strategy_proposals
               WHERE target_rule = ? AND created_at > ?
               ORDER BY created_at DESC""",
            (target_rule, since_ms),
        ).fetchall()

    # ── strategy_proposals writes ───────────────────────────────────────

    def update_status(
        self,
        proposal_id: str,
        status: str,
        decided_at: Optional[int] = None,
    ) -> None:
        ts = decided_at or _now_ms()
        self._conn.execute(
            "UPDATE strategy_proposals SET status=?, decided_at=? WHERE proposal_id=?",
            (status, ts, proposal_id),
        )

    def insert_proposal(
        self,
        *,
        proposal_id: str,
        generated_by: str,
        target_rule: str,
        rule_category: str = "",
        proposed_value: str = "",
        supporting_evidence: str = "",
        confidence: float = 0.0,
        requires_human_approval: bool = False,
        status: str = "pending",
        proposal_json: Optional[str] = None,
        expires_at: Optional[int] = None,
    ) -> None:
        now = _now_ms()
        self._conn.execute(
            """INSERT INTO strategy_proposals
               (proposal_id, generated_by, target_rule, rule_category,
                proposed_value, supporting_evidence, confidence,
                requires_human_approval, status, proposal_json,
                created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                proposal_id,
                generated_by,
                target_rule,
                rule_category,
                proposed_value,
                supporting_evidence,
                confidence,
                int(requires_human_approval),
                status,
                proposal_json or "{}",
                now,
                expires_at,
            ),
        )

    def expire_stale_noted(self, max_age_ms: int = 48 * 60 * 60 * 1000) -> int:
        """Expire 'noted' proposals older than max_age_ms. Returns count."""
        cutoff = _now_ms() - max_age_ms
        cursor = self._conn.execute(
            """UPDATE strategy_proposals
               SET status = 'expired', decided_at = ?
               WHERE status = 'noted' AND created_at < ?""",
            (_now_ms(), cutoff),
        )
        n = cursor.rowcount
        if n > 0:
            self._conn.commit()
        return n

    def has_active_sell_order(self, symbol: str) -> bool:
        """Check if there's an active submitted sell order for symbol."""
        row = self._conn.execute(
            """SELECT 1 FROM orders
               WHERE symbol = ? AND side = 'sell' AND status = 'submitted'
               LIMIT 1""",
            (symbol,),
        ).fetchone()
        return row is not None

    def count_daily_sell_proposals(self, symbol: str, trade_date: str) -> int:
        """Count concentration sell proposals for symbol today."""
        row = self._conn.execute(
            """SELECT COUNT(*) FROM strategy_proposals
               WHERE target_rule = 'POSITION_REBALANCE'
                 AND proposal_json LIKE ?
                 AND created_at >= ?""",
            (f'%"{symbol}"%', int(time.mktime(time.strptime(trade_date, "%Y-%m-%d")) * 1000)),
        ).fetchone()
        return int(row[0]) if row else 0

    # ── execution journal reads ─────────────────────────────────────────

    def load_journal(self, execution_key: str) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM proposal_execution_journal WHERE execution_key=?",
            (execution_key,),
        ).fetchone()

    # ── execution journal writes ────────────────────────────────────────

    def upsert_journal(
        self,
        *,
        execution_key: str,
        proposal_id: str,
        target_rule: str,
        symbol: str,
        qty: int,
        price: float,
        state: str = "prepared",
    ) -> None:
        now = _now_ms()
        existing = self.load_journal(execution_key)
        if existing is None:
            self._conn.execute(
                """INSERT INTO proposal_execution_journal
                   (execution_key, proposal_id, target_rule, symbol, qty, price,
                    state, attempt_count, last_order_id, last_error, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, ?, ?)""",
                (execution_key, proposal_id, target_rule, symbol, qty, price, state, now, now),
            )
            self._conn.commit()

    def update_journal_state(
        self,
        execution_key: str,
        state: str,
        *,
        increment_attempt: bool = False,
        last_order_id: Optional[str] = None,
        last_error: Optional[str] = None,
    ) -> None:
        now = _now_ms()
        if increment_attempt:
            self._conn.execute(
                """UPDATE proposal_execution_journal
                   SET state=?, attempt_count=attempt_count+1, updated_at=?
                   WHERE execution_key=?""",
                (state, now, execution_key),
            )
        else:
            parts = ["state=?", "updated_at=?"]
            params: list = [state, now]
            if last_order_id is not None:
                parts.append("last_order_id=?")
                params.append(last_order_id)
            if last_error is not None:
                parts.append("last_error=?")
                params.append(last_error)
            params.append(execution_key)
            self._conn.execute(
                f"UPDATE proposal_execution_journal SET {', '.join(parts)} WHERE execution_key=?",
                params,
            )
