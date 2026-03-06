from __future__ import annotations

import json
import sqlite3
import time
from typing import Any


def ensure_position_quarantine_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS position_quarantine (
            symbol TEXT PRIMARY KEY,
            active INTEGER NOT NULL DEFAULT 1,
            source TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            reason TEXT,
            report_id TEXT,
            created_at INTEGER NOT NULL,
            cleared_at INTEGER,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_position_quarantine_active ON position_quarantine (active)"
    )
    conn.commit()


def _active_quarantine_symbols(conn: sqlite3.Connection) -> set[str]:
    if not _table_exists(conn, "position_quarantine"):
        return set()
    rows = conn.execute("SELECT symbol FROM position_quarantine WHERE active=1").fetchall()
    return {str(r[0]).upper() for r in rows}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def build_reconciliation_quarantine_plan(
    conn: sqlite3.Connection,
    *,
    report: dict[str, Any],
) -> dict[str, Any]:
    diagnostics = report.get("diagnostics") or {}
    missing = list((report.get("mismatches") or {}).get("missing_broker_position", []))
    active_quarantines = _active_quarantine_symbols(conn)
    actions: list[dict[str, Any]] = []
    for item in missing:
        symbol = str(item.get("symbol") or "").upper()
        if not symbol:
            continue
        position_row = conn.execute(
            "SELECT symbol, quantity, avg_price, current_price, state FROM positions WHERE UPPER(symbol)=UPPER(?) LIMIT 1",
            (symbol,),
        ).fetchone()
        open_orders = conn.execute(
            "SELECT order_id, status FROM orders WHERE UPPER(symbol)=UPPER(?) AND status IN ('submitted', 'partially_filled')",
            (symbol,),
        ).fetchall()
        actions.append(
            {
                "symbol": symbol,
                "position": dict(position_row) if position_row is not None else None,
                "open_orders": [{"order_id": str(r[0]), "status": str(r[1])} for r in open_orders],
                "already_quarantined": symbol in active_quarantines,
                "eligible": position_row is not None and len(open_orders) == 0 and symbol not in active_quarantines,
            }
        )
    eligible_symbols = [item["symbol"] for item in actions if item["eligible"]]
    return {
        "report_id": report.get("report_id"),
        "reason_code": "BROKER_POSITION_MISSING",
        "reason": "Local position absent from broker snapshot during reconciliation.",
        "diagnostics": diagnostics,
        "eligible_symbols": eligible_symbols,
        "actions": actions,
        "safe_to_apply": bool(diagnostics.get("suspected_mode_or_account_mismatch")) and len(eligible_symbols) > 0,
    }


def apply_quarantine_plan(
    conn: sqlite3.Connection,
    *,
    plan: dict[str, Any],
    source: str = "broker_reconciliation",
    auto_commit: bool = True,
) -> dict[str, Any]:
    ensure_position_quarantine_schema(conn)
    now_ms = int(time.time() * 1000)
    applied: list[str] = []
    for item in plan.get("actions", []):
        if not item.get("eligible"):
            continue
        symbol = str(item["symbol"]).upper()
        payload = {
            "report_id": plan.get("report_id"),
            "position": item.get("position"),
            "diagnostics": plan.get("diagnostics") or {},
        }
        conn.execute(
            """
            INSERT INTO position_quarantine(symbol, active, source, reason_code, reason, report_id, created_at, cleared_at, payload_json)
            VALUES (?, 1, ?, ?, ?, ?, ?, NULL, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                active=1,
                source=excluded.source,
                reason_code=excluded.reason_code,
                reason=excluded.reason,
                report_id=excluded.report_id,
                created_at=excluded.created_at,
                cleared_at=NULL,
                payload_json=excluded.payload_json
            """,
            (
                symbol,
                source,
                str(plan.get("reason_code") or "BROKER_POSITION_MISSING"),
                str(plan.get("reason") or ""),
                str(plan.get("report_id") or ""),
                now_ms,
                json.dumps(payload, ensure_ascii=True),
            ),
        )
        conn.execute(
            """
            UPDATE positions
               SET quantity=0,
                   unrealized_pnl=0,
                   state='QUARANTINED'
             WHERE UPPER(symbol)=UPPER(?)
            """,
            (symbol,),
        )
        applied.append(symbol)
    if auto_commit:
        conn.commit()
    result = dict(plan)
    result["applied_symbols"] = applied
    result["applied_count"] = len(applied)
    return result
