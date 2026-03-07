"""proposal_executor.py — strategy_proposals 執行鏈

掃描 proposal queue，回傳待執行的 sell intents，並用 execution journal
確保重複執行可追蹤、可恢復、可去重。
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

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


def _load_journal(conn: sqlite3.Connection, execution_key: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM proposal_execution_journal WHERE execution_key=?",
        (execution_key,),
    ).fetchone()


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
    execution_key = _build_execution_key(proposal_id, symbol, qty, price)
    row = _load_journal(conn, execution_key)
    now = _now_ms()
    if row is None:
        conn.execute(
            """
            INSERT INTO proposal_execution_journal (
                execution_key, proposal_id, target_rule, symbol, qty, price,
                state, attempt_count, last_order_id, last_error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'prepared', 0, NULL, NULL, ?, ?)
            """,
            (execution_key, proposal_id, target_rule, symbol, qty, price, now, now),
        )
        conn.commit()
        return execution_key, 0

    state = str(_row_get(row, "state", 6))
    attempt_count = int(_row_get(row, "attempt_count", 7) or 0)
    updated_at = int(_row_get(row, "updated_at", 11) or 0)

    if state == "executing" and now - updated_at > (_INTENT_STALE_SEC * 1000):
        conn.execute(
            """
            UPDATE proposal_execution_journal
               SET state='prepared', last_error=?, updated_at=?
             WHERE execution_key=?
            """,
            ("stale executing attempt recovered", now, execution_key),
        )
        conn.execute(
            "UPDATE strategy_proposals SET status='queued', decided_at=NULL WHERE proposal_id=?",
            (proposal_id,),
        )
        conn.commit()
        return execution_key, attempt_count

    return execution_key, attempt_count


def execute_pending_proposals(conn: sqlite3.Connection) -> tuple[list[SellIntent], int]:
    """掃描 proposal queue，回傳待執行 intents。"""
    ensure_execution_journal_schema(conn)
    rows = conn.execute(
        """SELECT proposal_id, target_rule, proposal_json, status
           FROM strategy_proposals
           WHERE status IN ('approved', 'queued', 'executing')
             AND (expires_at IS NULL OR expires_at > ?)""",
        (int(time.time()),),
    ).fetchall()

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
                    conn.execute(
                        "UPDATE strategy_proposals SET status='skipped', decided_at=? WHERE proposal_id=?",
                        (_now_ms(), proposal_id),
                    )
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
                journal = _load_journal(conn, execution_key)
                journal_state = str(_row_get(journal, "state", 6)) if journal else "prepared"
                if journal_state in {"completed", "executing"}:
                    continue

                if status == "approved":
                    conn.execute(
                        "UPDATE strategy_proposals SET status='queued' WHERE proposal_id=?",
                        (proposal_id,),
                    )
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
                conn.execute(
                    "UPDATE strategy_proposals SET status='noted', decided_at=? WHERE proposal_id=?",
                    (_now_ms(), proposal_id),
                )
                conn.commit()
                n_noted += 1

        except Exception as e:
            log.error("Error processing proposal %s: %s", proposal_id, e, exc_info=True)

    return intents, n_noted


def mark_intent_executing(conn: sqlite3.Connection, proposal_id: str, execution_key: str) -> None:
    ensure_execution_journal_schema(conn)
    now = _now_ms()
    conn.execute(
        """
        UPDATE proposal_execution_journal
           SET state='executing',
               attempt_count=attempt_count + 1,
               updated_at=?
         WHERE execution_key=? AND proposal_id=?
        """,
        (now, execution_key, proposal_id),
    )
    conn.execute(
        "UPDATE strategy_proposals SET status='executing' WHERE proposal_id=?",
        (proposal_id,),
    )
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
    now = _now_ms()
    if execution_key:
        conn.execute(
            """
            UPDATE proposal_execution_journal
               SET state='completed', last_order_id=?, last_error=NULL, updated_at=?
             WHERE execution_key=? AND proposal_id=?
            """,
            (order_id or None, now, execution_key, proposal_id),
        )
    else:
        conn.execute(
            """
            UPDATE proposal_execution_journal
               SET state='completed', last_order_id=?, last_error=NULL, updated_at=?
             WHERE proposal_id=?
            """,
            (order_id or None, now, proposal_id),
        )
    conn.execute(
        "UPDATE strategy_proposals SET status='executed', decided_at=? WHERE proposal_id=?",
        (now, proposal_id),
    )
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
    now = _now_ms()
    if execution_key:
        conn.execute(
            """
            UPDATE proposal_execution_journal
               SET state='failed', last_error=?, last_order_id=?, updated_at=?
             WHERE execution_key=? AND proposal_id=?
            """,
            (reason, order_id or None, now, execution_key, proposal_id),
        )
    else:
        conn.execute(
            """
            UPDATE proposal_execution_journal
               SET state='failed', last_error=?, last_order_id=?, updated_at=?
             WHERE proposal_id=?
            """,
            (reason, order_id or None, now, proposal_id),
        )
    conn.execute(
        "UPDATE strategy_proposals SET status='failed', decided_at=?, "
        "supporting_evidence=COALESCE(supporting_evidence,'') || ? "
        "WHERE proposal_id=?",
        (now, f" | broker_reject: {reason}", proposal_id),
    )
    conn.commit()
