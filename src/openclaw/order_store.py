from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Dict, Optional

from openclaw.orders import transition_order_status


def insert_order_event(
    conn: sqlite3.Connection,
    *,
    order_id: str,
    event_type: str,
    from_status: Optional[str],
    to_status: Optional[str],
    source: str,
    reason_code: Optional[str],
    payload: Dict[str, Any],
    event_id: Optional[str] = None,
) -> str:
    oid = event_id or str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO order_events (
          event_id, ts, order_id, event_type, from_status, to_status, source, reason_code, payload_json
        )
        VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            oid,
            order_id,
            event_type,
            from_status,
            to_status,
            source,
            reason_code,
            json.dumps(payload, ensure_ascii=True),
        ),
    )
    return oid


def transition_with_event(
    conn: sqlite3.Connection,
    *,
    order_id: str,
    next_status: str,
    source: str,
    reason_code: Optional[str],
    payload: Dict[str, Any],
) -> None:
    row = conn.execute("SELECT status FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if row is None:
        raise RuntimeError(f"order not found: {order_id}")
    prev = str(row[0])
    if prev == next_status:
        return
    transition_order_status(conn, order_id, next_status)
    insert_order_event(
        conn,
        order_id=order_id,
        event_type="status_transition",
        from_status=prev,
        to_status=next_status,
        source=source,
        reason_code=reason_code,
        payload=payload,
    )
