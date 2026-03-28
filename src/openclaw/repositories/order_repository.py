"""order_repository.py — Data access for orders and fills tables.

Encapsulates all INSERT/UPDATE/SELECT on ``orders`` and ``fills``,
replacing direct SQL scattered across ticker_watcher.py and other modules.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass
class OrderRecord:
    order_id: str
    decision_id: str
    broker_order_id: str
    symbol: str
    side: str
    qty: int
    price: float
    status: str = "submitted"
    order_type: str = "limit"
    tif: str = "IOC"
    strategy_version: str = ""
    settlement_date: Optional[str] = None
    account_mode: str = "simulation"
    ts_submit: str = ""


@dataclass
class FillRecord:
    order_id: str
    qty: int
    price: float
    fee: float = 0.0
    tax: float = 0.0
    fill_id: str = ""
    ts_fill: str = ""


class OrderRepository:
    """Encapsulates orders + fills table access."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── Writes ──────────────────────────────────────────────────────────

    def insert_order(self, order: OrderRecord) -> None:
        ts = order.ts_submit or _utc_now_iso()
        self._conn.execute(
            """INSERT INTO orders
               (order_id, decision_id, broker_order_id, ts_submit,
                symbol, side, qty, price, order_type, tif, status,
                strategy_version, settlement_date, account_mode)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (order.order_id, order.decision_id, order.broker_order_id, ts,
             order.symbol, order.side, order.qty, order.price,
             order.order_type, order.tif, order.status,
             order.strategy_version, order.settlement_date, order.account_mode),
        )

    def insert_fill(self, fill: FillRecord) -> None:
        fill_id = fill.fill_id or str(uuid.uuid4())
        ts = fill.ts_fill or _utc_now_iso()
        self._conn.execute(
            """INSERT INTO fills (fill_id, order_id, ts_fill, qty, price, fee, tax)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (fill_id, fill.order_id, ts, fill.qty, fill.price, fill.fee, fill.tax),
        )

    def update_status(self, order_id: str, new_status: str) -> None:
        self._conn.execute(
            "UPDATE orders SET status = ? WHERE order_id = ?",
            (new_status, order_id),
        )

    def insert_order_event(
        self,
        *,
        order_id: str,
        event_type: str,
        from_status: Optional[str],
        to_status: Optional[str],
        source: str,
        reason_code: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> None:
        self._conn.execute(
            """INSERT INTO order_events
               (event_id, ts, order_id, event_type, from_status, to_status,
                source, reason_code, payload_json)
               VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), order_id, event_type, from_status, to_status,
             source, reason_code,
             json.dumps(payload or {}, ensure_ascii=True)),
        )

    # ── Reads ───────────────────────────────────────────────────────────

    def get_today_orders(self, side: Optional[str] = None) -> List[sqlite3.Row]:
        """Return today's orders, optionally filtered by side."""
        if side:
            return self._conn.execute(
                """SELECT DISTINCT o.symbol FROM orders o
                   JOIN fills f ON o.order_id = f.order_id
                   WHERE o.side = ? AND date(o.ts_submit) = date('now')""",
                (side,),
            ).fetchall()
        return self._conn.execute(
            "SELECT * FROM orders WHERE date(ts_submit) = date('now')"
        ).fetchall()

    def count_orders_last_minute(self) -> int:
        row = self._conn.execute(
            """SELECT COUNT(*) FROM orders
               WHERE ts_submit >= datetime('now', '-1 minute')"""
        ).fetchone()
        return int(row[0]) if row else 0

    def get_stale_pending_orders(self, cutoff_iso: str) -> List[sqlite3.Row]:
        return self._conn.execute(
            """SELECT order_id, broker_order_id, symbol FROM orders
               WHERE status = 'submitted' AND ts_submit < ?""",
            (cutoff_iso,),
        ).fetchall()

    def get_fill_costs(self, order_id: str) -> tuple[float, float]:
        """Return (total_fee, total_tax) for a given order."""
        row = self._conn.execute(
            """SELECT COALESCE(SUM(fee), 0.0), COALESCE(SUM(tax), 0.0)
               FROM fills WHERE order_id = ?""",
            (order_id,),
        ).fetchone()
        return (float(row[0]), float(row[1])) if row else (0.0, 0.0)
