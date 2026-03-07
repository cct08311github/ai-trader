from __future__ import annotations

import datetime as dt
import math
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from openclaw.risk_engine import OrderCandidate


@dataclass
class PreTradeGuardResult:
    approved: bool
    reject_code: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)


def default_hard_limits() -> dict[str, float]:
    return {
        "max_order_qty": float(os.environ.get("PRE_TRADE_MAX_ORDER_QTY", "2000")),
        "max_order_notional": float(os.environ.get("PRE_TRADE_MAX_ORDER_NOTIONAL", "500000")),
        "max_symbol_position_notional": float(
            os.environ.get("PRE_TRADE_MAX_SYMBOL_POSITION_NOTIONAL", "1200000")
        ),
        "max_orders_per_symbol_window": float(
            os.environ.get("PRE_TRADE_MAX_ORDERS_PER_SYMBOL_WINDOW", "2")
        ),
        "recent_order_window_sec": float(os.environ.get("PRE_TRADE_RECENT_ORDER_WINDOW_SEC", "600")),
        "duplicate_order_window_sec": float(os.environ.get("PRE_TRADE_DUPLICATE_ORDER_WINDOW_SEC", "30")),
    }


def _now_utc() -> dt.datetime:
    return dt.datetime.now(tz=dt.timezone.utc)


def _to_iso_cutoff(now: dt.datetime, seconds: float) -> str:
    return (now - dt.timedelta(seconds=max(seconds, 0))).isoformat()


def _load_position(conn: sqlite3.Connection, symbol: str) -> tuple[int | None, float | None]:
    try:
        row = conn.execute(
            "SELECT quantity, current_price FROM positions WHERE UPPER(symbol)=UPPER(?) LIMIT 1",
            (symbol,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None, None
    if not row:
        return None, None
    quantity = row["quantity"] if isinstance(row, sqlite3.Row) else row[0]
    current_price = row["current_price"] if isinstance(row, sqlite3.Row) else row[1]
    return int(quantity or 0), float(current_price or 0.0)


def evaluate_pre_trade_guard(
    conn: sqlite3.Connection,
    candidate: OrderCandidate,
    *,
    limits: dict[str, float] | None = None,
    now: dt.datetime | None = None,
) -> PreTradeGuardResult:
    hard_limits = dict(default_hard_limits())
    if limits:
        hard_limits.update(limits)

    current_now = now or _now_utc()
    notional = float(candidate.qty) * float(candidate.price)
    metrics: dict[str, Any] = {
        "symbol": candidate.symbol,
        "side": candidate.side,
        "qty": candidate.qty,
        "price": candidate.price,
        "notional": notional,
    }

    if candidate.side not in {"buy", "sell"}:
        return PreTradeGuardResult(False, "RISK_HARD_GUARD_INVALID_SIDE", metrics)

    if int(candidate.qty) <= 0:
        return PreTradeGuardResult(False, "RISK_HARD_GUARD_INVALID_QTY", metrics)

    if not math.isfinite(candidate.price) or float(candidate.price) <= 0:
        return PreTradeGuardResult(False, "RISK_HARD_GUARD_INVALID_PRICE", metrics)

    if candidate.qty > int(hard_limits["max_order_qty"]):
        metrics["max_order_qty"] = int(hard_limits["max_order_qty"])
        return PreTradeGuardResult(False, "RISK_HARD_GUARD_MAX_ORDER_QTY", metrics)

    if notional > float(hard_limits["max_order_notional"]):
        metrics["max_order_notional"] = float(hard_limits["max_order_notional"])
        return PreTradeGuardResult(False, "RISK_HARD_GUARD_MAX_ORDER_NOTIONAL", metrics)

    recent_cutoff = _to_iso_cutoff(current_now, float(hard_limits["recent_order_window_sec"]))
    recent_rows = conn.execute(
        """
        SELECT side, qty, price
        FROM orders
        WHERE UPPER(symbol)=UPPER(?)
          AND ts_submit >= ?
          AND status IN ('submitted', 'partially_filled', 'filled')
        """,
        (candidate.symbol, recent_cutoff),
    ).fetchall()
    metrics["recent_symbol_orders"] = len(recent_rows)
    if len(recent_rows) >= int(hard_limits["max_orders_per_symbol_window"]):
        metrics["max_orders_per_symbol_window"] = int(hard_limits["max_orders_per_symbol_window"])
        return PreTradeGuardResult(False, "RISK_HARD_GUARD_SYMBOL_RATE_LIMIT", metrics)

    duplicate_cutoff = _to_iso_cutoff(current_now, float(hard_limits["duplicate_order_window_sec"]))
    duplicate_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM orders
        WHERE UPPER(symbol)=UPPER(?)
          AND side=?
          AND qty=?
          AND ABS(COALESCE(price, 0) - ?) < 0.000001
          AND ts_submit >= ?
          AND status IN ('submitted', 'partially_filled', 'filled')
        """,
        (candidate.symbol, candidate.side, candidate.qty, candidate.price, duplicate_cutoff),
    ).fetchone()[0]
    metrics["duplicate_orders"] = int(duplicate_count or 0)
    if duplicate_count:
        return PreTradeGuardResult(False, "RISK_HARD_GUARD_DUPLICATE_ORDER", metrics)

    position_qty, current_price = _load_position(conn, candidate.symbol)
    if position_qty is not None:
        metrics["position_qty"] = position_qty
        metrics["position_price"] = current_price

    if candidate.side == "sell" and position_qty is not None and candidate.qty > max(position_qty, 0):
        return PreTradeGuardResult(False, "RISK_HARD_GUARD_SELL_QTY_EXCEEDS_POSITION", metrics)

    if candidate.side == "buy":
        projected_qty = max(position_qty or 0, 0) + candidate.qty
        projected_notional = projected_qty * (current_price or candidate.price or 0.0)
        metrics["projected_symbol_notional"] = projected_notional
        metrics["max_symbol_position_notional"] = float(hard_limits["max_symbol_position_notional"])
        if projected_notional > float(hard_limits["max_symbol_position_notional"]):
            return PreTradeGuardResult(False, "RISK_HARD_GUARD_SYMBOL_NOTIONAL_LIMIT", metrics)

    return PreTradeGuardResult(True, metrics=metrics)
