from __future__ import annotations

import sqlite3
from typing import Final


class OrderStateError(RuntimeError):
    pass


TERMINAL_STATUSES: Final[set[str]] = {"filled", "cancelled", "rejected", "expired"}

ALLOWED_TRANSITIONS: Final[dict[str, set[str]]] = {
    "new": {"submitted", "rejected", "expired"},
    "submitted": {"partially_filled", "filled", "cancelled", "rejected", "expired"},
    "partially_filled": {"partially_filled", "filled", "cancelled", "rejected"},
    "filled": set(),
    "cancelled": set(),
    "rejected": set(),
    "expired": set(),
}


def can_transition(current_status: str, next_status: str) -> bool:
    return next_status in ALLOWED_TRANSITIONS.get(current_status, set())


def get_order_status(conn: sqlite3.Connection, order_id: str) -> str:
    row = conn.execute("SELECT status FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if row is None:
        raise OrderStateError(f"order not found: {order_id}")
    return str(row[0])


def transition_order_status(conn: sqlite3.Connection, order_id: str, next_status: str) -> None:
    current = get_order_status(conn, order_id)
    if current == next_status:
        return
    if not can_transition(current, next_status):
        raise OrderStateError(f"invalid transition: {current} -> {next_status} (order_id={order_id})")
    conn.execute("UPDATE orders SET status = ? WHERE order_id = ?", (next_status, order_id))


def summarize_fill_status(conn: sqlite3.Connection, order_id: str) -> str:
    row = conn.execute("SELECT qty, status FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if row is None:
        raise OrderStateError(f"order not found: {order_id}")
    total_qty = int(row[0])
    current_status = str(row[1])
    if current_status in TERMINAL_STATUSES:
        return current_status

    fill_qty = conn.execute("SELECT COALESCE(SUM(qty), 0) FROM fills WHERE order_id = ?", (order_id,)).fetchone()[0]
    fill_qty = int(fill_qty or 0)
    if fill_qty <= 0:
        return current_status
    if fill_qty < total_qty:
        return "partially_filled"
    return "filled"
