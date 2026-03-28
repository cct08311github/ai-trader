"""proposal_executor.py — strategy_proposals 執行鏈

掃描 proposal queue，回傳待執行的 sell intents，並用 execution journal
確保重複執行可追蹤、可恢復、可去重。

All SQL is delegated to ProposalRepository and PositionRepository.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from openclaw.repositories.position_repository import PositionRepository
from openclaw.repositories.proposal_repository import ProposalRepository

log = logging.getLogger(__name__)

_INTENT_STALE_SEC = 300


@dataclass
class SellIntent:
    proposal_id: str
    symbol: str
    qty: int
    price: float
    execution_key: str
    attempt_count: int = 0


def _now_ms() -> int:
    return int(time.time() * 1000)


def ensure_execution_journal_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS proposal_execution_journal (
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
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_exec_journal_proposal ON proposal_execution_journal (proposal_id, updated_at)"
    )
    conn.commit()


def _row_get(row: Any, key: str, idx: int) -> Any:
    if isinstance(row, sqlite3.Row):
        return row[key]
    return row[idx]


def _build_execution_key(proposal_id: str, symbol: str, qty: int, price: float) -> str:
    raw = f"{proposal_id}:{symbol}:{qty}:{price:.4f}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _upsert_journal_prepared(
    conn: sqlite3.Connection,
    *,
    proposal_id: str,
    target_rule: str,
    symbol: str,
    qty: int,
    price: float,
) -> tuple[str, int]:
    ensure_execution_journal_schema(conn)
    repo = ProposalRepository(conn)
    execution_key = _build_execution_key(proposal_id, symbol, qty, price)
    row = repo.load_journal(execution_key)
    now = _now_ms()
    if row is None:
        repo.upsert_journal(
            execution_key=execution_key, proposal_id=proposal_id,
            target_rule=target_rule, symbol=symbol, qty=qty, price=price,
        )
        return execution_key, 0

    state = str(_row_get(row, "state", 6))
    attempt_count = int(_row_get(row, "attempt_count", 7) or 0)
    updated_at = int(_row_get(row, "updated_at", 11) or 0)

    if state == "executing" and now - updated_at > (_INTENT_STALE_SEC * 1000):
        repo.update_journal_state(
            execution_key, "prepared",
            last_error="stale executing attempt recovered",
        )
        repo.update_status(proposal_id, "queued")
        conn.commit()
        return execution_key, attempt_count

    return execution_key, attempt_count


def execute_pending_proposals(conn: sqlite3.Connection) -> tuple[list[SellIntent], int]:
    """掃描 proposal queue，回傳待執行 intents。"""
    ensure_execution_journal_schema(conn)
    repo = ProposalRepository(conn)
    pos_repo = PositionRepository(conn)
    rows = repo.get_actionable_proposals()

    intents: list[SellIntent] = []
    n_noted = 0

    for row in rows:
        proposal_id = _row_get(row, "proposal_id", 0)
        target_rule = _row_get(row, "target_rule", 1)
        proposal_json_str = _row_get(row, "proposal_json", 2)
        status = _row_get(row, "status", 3)
        try:
            proposal = json.loads(proposal_json_str or "{}")

            if target_rule == "POSITION_REBALANCE":
                symbol = proposal.get("symbol")
                reduce_pct = float(proposal.get("reduce_pct", 0))
                if not symbol or reduce_pct <= 0:
                    log.warning("Invalid POSITION_REBALANCE proposal %s", proposal_id)
                    continue

                pos = conn.execute(
                    "SELECT quantity, current_price FROM positions WHERE symbol=?",
                    (symbol,),
                ).fetchone()
                if not pos or (pos[0] or 0) <= 0:
                    log.info("Proposal %s: no position in %s", proposal_id, symbol)
                    repo.update_status(proposal_id, "skipped")
                    conn.commit()
                    continue

                qty_to_sell = max(1, int(float(pos[0]) * reduce_pct))
                price = float(pos[1] or 0.0)
                if price <= 0:
                    log.warning("Proposal %s: %s has no valid price (%.2f), skipping", proposal_id, symbol, price)
                    continue

                execution_key, attempt_count = _upsert_journal_prepared(
                    conn,
                    proposal_id=proposal_id,
                    target_rule=target_rule,
                    symbol=symbol,
                    qty=qty_to_sell,
                    price=price,
                )
                journal = repo.load_journal(execution_key)
                journal_state = str(_row_get(journal, "state", 6)) if journal else "prepared"
                if journal_state in {"completed", "executing"}:
                    continue

                if status == "approved":
                    repo.update_status(proposal_id, "queued")
                    conn.commit()

                intents.append(
                    SellIntent(
                        proposal_id=proposal_id,
                        symbol=symbol,
                        qty=qty_to_sell,
                        price=price,
                        execution_key=execution_key,
                        attempt_count=attempt_count,
                    )
                )
                log.info(
                    "Proposal %s: %s sell %d @ %.2f -> intent queued (attempt=%d)",
                    proposal_id,
                    symbol,
                    qty_to_sell,
                    price,
                    attempt_count,
                )

            elif target_rule == "STRATEGY_DIRECTION":
                repo.update_status(proposal_id, "noted")
                conn.commit()
                n_noted += 1

        except (json.JSONDecodeError, sqlite3.Error, ValueError, TypeError) as e:
            log.error("Error processing proposal %s: %s", proposal_id, e, exc_info=True)

    return intents, n_noted


# 48 hours in milliseconds — noted proposals older than this are expired (#383)
_NOTED_EXPIRY_MS = 48 * 60 * 60 * 1000


def expire_stale_noted_proposals(conn: sqlite3.Connection) -> int:
    """Expire 'noted' proposals older than 48 hours. Returns count of expired rows."""
    try:
        n = ProposalRepository(conn).expire_stale_noted(_NOTED_EXPIRY_MS)
        if n > 0:
            log.info("Expired %d stale noted proposals (older than 48h)", n)
        return n
    except sqlite3.Error as e:
        log.warning("expire_stale_noted_proposals failed: %s", e)
        return 0


def mark_intent_executing(conn: sqlite3.Connection, proposal_id: str, execution_key: str) -> None:
    ensure_execution_journal_schema(conn)
    repo = ProposalRepository(conn)
    repo.update_journal_state(execution_key, "executing", increment_attempt=True)
    repo.update_status(proposal_id, "executing")
    conn.commit()


def mark_intent_executed(
    conn: sqlite3.Connection,
    proposal_id: str,
    *,
    execution_key: str | None = None,
    order_id: str = "",
) -> None:
    """Broker 成交後，標記 proposal 與 execution journal 完成。"""
    ensure_execution_journal_schema(conn)
    repo = ProposalRepository(conn)
    if execution_key:
        repo.update_journal_state(
            execution_key, "completed", last_order_id=order_id or None,
        )
    else:
        # Fallback: update by proposal_id
        conn.execute(
            """UPDATE proposal_execution_journal
               SET state='completed', last_order_id=?, last_error=NULL, updated_at=?
               WHERE proposal_id=?""",
            (order_id or None, _now_ms(), proposal_id),
        )
    repo.update_status(proposal_id, "executed")
    conn.commit()


def mark_intent_failed(
    conn: sqlite3.Connection,
    proposal_id: str,
    reason: str = "",
    *,
    execution_key: str | None = None,
    order_id: str = "",
) -> None:
    """Broker 拒絕或執行異常時標記 failed，保留 journal 供後續排查。"""
    ensure_execution_journal_schema(conn)
    repo = ProposalRepository(conn)
    if execution_key:
        repo.update_journal_state(
            execution_key, "failed",
            last_order_id=order_id or None, last_error=reason,
        )
    else:
        conn.execute(
            """UPDATE proposal_execution_journal
               SET state='failed', last_error=?, last_order_id=?, updated_at=?
               WHERE proposal_id=?""",
            (reason, order_id or None, _now_ms(), proposal_id),
        )
    repo.update_status_with_evidence(
        proposal_id, "failed",
        evidence_append=f" | broker_reject: {reason}",
    )
    conn.commit()
