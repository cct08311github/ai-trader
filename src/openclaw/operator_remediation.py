from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def ensure_operator_remediation_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS operator_remediation_log (
            action_id TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_ref TEXT,
            actor TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_operator_remediation_created_at
            ON operator_remediation_log (created_at DESC)
        """
    )
    conn.commit()


def record_operator_remediation(
    conn: sqlite3.Connection,
    *,
    action_type: str,
    target_type: str,
    actor: str,
    status: str,
    payload: dict[str, Any],
    target_ref: str | None = None,
    action_id: str | None = None,
    created_at: int | None = None,
    auto_commit: bool = True,
) -> str:
    ensure_operator_remediation_schema(conn)
    remediation_id = action_id or str(uuid.uuid4())
    ts_ms = int(created_at or time.time() * 1000)
    conn.execute(
        """
        INSERT INTO operator_remediation_log (
            action_id,
            created_at,
            action_type,
            target_type,
            target_ref,
            actor,
            status,
            payload_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            remediation_id,
            ts_ms,
            action_type,
            target_type,
            target_ref,
            actor,
            status,
            json.dumps(payload, ensure_ascii=True),
        ),
    )
    if auto_commit:
        conn.commit()
    return remediation_id


def list_operator_remediations(
    conn: sqlite3.Connection,
    *,
    limit: int = 20,
    action_type: str | None = None,
    target_ref: str | None = None,
) -> dict[str, Any]:
    if not _table_exists(conn, "operator_remediation_log"):
        return {"count": 0, "items": []}
    where = []
    params: list[Any] = []
    if action_type:
        where.append("action_type=?")
        params.append(str(action_type))
    if target_ref:
        where.append("target_ref LIKE ?")
        params.append(f"%{str(target_ref)}%")
    sql = """
        SELECT action_id, created_at, action_type, target_type, target_ref, actor, status, payload_json
          FROM operator_remediation_log
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC, action_id DESC LIMIT ?"
    params.append(max(int(limit), 1))
    rows = conn.execute(sql, tuple(params)).fetchall()
    items = []
    for row in rows:
        try:
            payload = json.loads(row[7] or "{}")
        except Exception:
            payload = {}
        items.append(
            {
                "action_id": str(row[0]),
                "created_at": int(row[1]),
                "action_type": str(row[2]),
                "target_type": str(row[3]),
                "target_ref": row[4],
                "actor": str(row[5]),
                "status": str(row[6]),
                "payload": payload,
            }
        )
    return {"count": len(items), "items": items}
