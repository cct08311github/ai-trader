from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from openclaw.operator_remediation import record_operator_remediation
from openclaw.pnl_engine import sync_positions_table


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


def _position_columns(conn: sqlite3.Connection) -> set[str]:
    if not _table_exists(conn, "positions"):
        return set()
    rows = conn.execute("PRAGMA table_info(positions)").fetchall()
    return {str(r[1]) for r in rows}


def build_reconciliation_quarantine_plan(
    conn: sqlite3.Connection,
    *,
    report: dict[str, Any],
) -> dict[str, Any]:
    diagnostics = report.get("diagnostics") or {}
    missing = list((report.get("mismatches") or {}).get("missing_broker_position", []))
    active_quarantines = _active_quarantine_symbols(conn)
    position_columns = _position_columns(conn)
    position_select = [
        "symbol",
        "quantity" if "quantity" in position_columns else "NULL AS quantity",
        "avg_price" if "avg_price" in position_columns else "NULL AS avg_price",
        "current_price" if "current_price" in position_columns else "NULL AS current_price",
        "state" if "state" in position_columns else "NULL AS state",
    ]
    actions: list[dict[str, Any]] = []
    for item in missing:
        symbol = str(item.get("symbol") or "").upper()
        if not symbol:
            continue
        position_row = None
        if "symbol" in position_columns:
            position_row = conn.execute(
                f"SELECT {', '.join(position_select)} FROM positions WHERE UPPER(symbol)=UPPER(?) LIMIT 1",
                (symbol,),
            ).fetchone()
        if _table_exists(conn, "orders"):
            open_orders = conn.execute(
                "SELECT order_id, status FROM orders WHERE UPPER(symbol)=UPPER(?) AND status IN ('submitted', 'partially_filled')",
                (symbol,),
            ).fetchall()
        else:
            open_orders = []
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
    position_columns = _position_columns(conn)
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
        updates = []
        if "quantity" in position_columns:
            updates.append("quantity=0")
        if "unrealized_pnl" in position_columns:
            updates.append("unrealized_pnl=0")
        if "state" in position_columns:
            updates.append("state='QUARANTINED'")
        if updates:
            conn.execute(
                f"UPDATE positions SET {', '.join(updates)} WHERE UPPER(symbol)=UPPER(?)",
                (symbol,),
            )
        record_operator_remediation(
            conn,
            action_type="quarantine_apply",
            target_type="symbol",
            target_ref=symbol,
            actor=source,
            status="applied",
            payload={
                "report_id": plan.get("report_id"),
                "reason_code": plan.get("reason_code"),
                "diagnostics": plan.get("diagnostics") or {},
            },
            auto_commit=False,
        )
        applied.append(symbol)
    if auto_commit:
        conn.commit()
    result = dict(plan)
    result["applied_symbols"] = applied
    result["applied_count"] = len(applied)
    return result


def get_quarantine_status(conn: sqlite3.Connection) -> dict[str, Any]:
    if not _table_exists(conn, "position_quarantine"):
        return {"active_count": 0, "items": []}
    position_columns = _position_columns(conn)
    select_parts = [
        "q.symbol",
        "q.source",
        "q.reason_code",
        "q.reason",
        "q.report_id",
        "q.created_at",
        "q.payload_json",
        "p.quantity" if "quantity" in position_columns else "NULL AS quantity",
        "p.avg_price" if "avg_price" in position_columns else "NULL AS avg_price",
        "p.current_price" if "current_price" in position_columns else "NULL AS current_price",
        "p.state" if "state" in position_columns else "NULL AS state",
    ]
    rows = conn.execute(
        f"""
        SELECT {", ".join(select_parts)}
          FROM position_quarantine q
          LEFT JOIN positions p ON UPPER(p.symbol)=UPPER(q.symbol)
         WHERE q.active=1
      ORDER BY q.created_at DESC, q.symbol
        """
    ).fetchall()
    items = []
    for row in rows:
        try:
            payload = json.loads(row[6] or "{}")
        except Exception:
            payload = {}
        items.append(
            {
                "symbol": str(row[0]),
                "source": str(row[1]),
                "reason_code": str(row[2]),
                "reason": row[3],
                "report_id": row[4],
                "created_at": int(row[5] or 0),
                "payload": payload,
                "position": {
                    "quantity": int(row[7] or 0) if row[7] is not None else 0,
                    "avg_price": float(row[8] or 0.0) if row[8] is not None else 0.0,
                    "current_price": float(row[9] or 0.0) if row[9] is not None else 0.0,
                    "state": row[10],
                },
            }
        )
    return {"active_count": len(items), "items": items}


def clear_quarantine_symbols(
    conn: sqlite3.Connection,
    *,
    symbols: list[str] | None = None,
    auto_commit: bool = True,
) -> dict[str, Any]:
    ensure_position_quarantine_schema(conn)
    targets = [symbol.upper() for symbol in (symbols or []) if str(symbol).strip()]
    now_ms = int(time.time() * 1000)
    if targets:
        active_before = {
            str(row[0]).upper()
            for row in conn.execute(
                "SELECT symbol FROM position_quarantine WHERE active=1 AND UPPER(symbol) IN ({})".format(
                    ",".join("?" for _ in targets)
                ),
                tuple(targets),
            ).fetchall()
        }
    else:
        active_before = {
            str(row[0]).upper()
            for row in conn.execute("SELECT symbol FROM position_quarantine WHERE active=1").fetchall()
        }
    if targets:
        conn.executemany(
            "UPDATE position_quarantine SET active=0, cleared_at=? WHERE UPPER(symbol)=UPPER(?) AND active=1",
            [(now_ms, symbol) for symbol in targets],
        )
    else:
        conn.execute(
            "UPDATE position_quarantine SET active=0, cleared_at=? WHERE active=1",
            (now_ms,),
        )
    if _table_exists(conn, "orders") and _table_exists(conn, "fills"):
        sync_positions_table(conn)
    cleared_symbols = sorted(active_before)
    for symbol in cleared_symbols:
        record_operator_remediation(
            conn,
            action_type="quarantine_clear",
            target_type="symbol",
            target_ref=symbol,
            actor="operator",
            status="cleared",
            payload={
                "requested_symbols": targets,
                "cleared_at": now_ms,
            },
            auto_commit=False,
        )
    if auto_commit:
        conn.commit()
    status = get_quarantine_status(conn)
    return {
        "cleared_symbols": cleared_symbols,
        "cleared_count": len(cleared_symbols),
        "remaining_active_count": status["active_count"],
    }
