from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Query

from app.db import get_conn
from app.services.shioaji_service import get_positions

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/positions")
def portfolio_positions(source: str = "mock", simulation: bool = True):
    """Return portfolio positions.

    source: mock|shioaji (default mock for speed)
    """

    source = source.lower().strip()
    if source not in {"mock", "shioaji"}:
        source = "mock"

    return {"status": "ok", **get_positions(source=source, simulation=simulation)}


SortBy = Literal["time", "amount", "pnl"]
SortDir = Literal["asc", "desc"]


@router.get("/trades")
def list_trades(
    start: Optional[str] = Query(default=None, description="Start timestamp (inclusive). ISO8601 string."),
    end: Optional[str] = Query(default=None, description="End timestamp (inclusive). ISO8601 string."),
    symbol: Optional[str] = Query(default=None, description="Stock symbol/code (exact match)."),
    trade_type: Optional[Literal["buy", "sell"]] = Query(default=None, alias="type"),
    status: Optional[str] = Query(default=None, description="Trade status (reserved)."),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    sort_by: SortBy = Query(default="time"),
    sort_dir: SortDir = Query(default="desc"),
) -> Dict[str, Any]:
    """Return historical trades with filters, pagination, sorting.

    Data source: SQLite trades table (read-only).

    Notes:
    - `status` is currently not a physical column in trades table; for now we treat all
      rows as "filled" and allow filtering status="filled".
    - Sorting is allow-listed to prevent SQL injection.
    """

    symbol_norm = symbol.strip().upper() if symbol else None
    status_norm = status.strip().lower() if status else None

    if status_norm and status_norm not in {"filled", "all"}:
        return {"status": "ok", "items": [], "total": 0, "limit": limit, "offset": offset}

    order_map = {
        "time": "timestamp",
        "amount": "(quantity * price)",
        "pnl": "pnl",
    }
    order_expr = order_map[sort_by]
    direction = "ASC" if sort_dir == "asc" else "DESC"

    where: List[str] = []
    params: List[Any] = []

    if start:
        where.append("timestamp >= ?")
        params.append(start)
    if end:
        where.append("timestamp <= ?")
        params.append(end)

    if symbol_norm:
        where.append("UPPER(symbol) = ?")
        params.append(symbol_norm)

    if trade_type:
        where.append("LOWER(action) = ?")
        params.append(trade_type)

    if status_norm == "filled":
        where.append("1 = 1")

    where_sql = " WHERE " + " AND ".join(where) if where else ""

    select_sql = f"""
        SELECT
          id,
          timestamp,
          symbol,
          action,
          quantity,
          price,
          fee,
          tax,
          pnl,
          agent_id,
          decision_id,
          (quantity * price) AS amount
        FROM trades
        {where_sql}
        ORDER BY {order_expr} {direction}
        LIMIT ? OFFSET ?
    """.strip()

    count_sql = f"SELECT COUNT(1) AS cnt FROM trades{where_sql}"

    with get_conn() as conn:
        total_row = conn.execute(count_sql, params).fetchone()
        total = int(total_row["cnt"]) if total_row else 0
        rows = conn.execute(select_sql, [*params, limit, offset]).fetchall()

    items: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        d["status"] = "filled"
        items.append(d)

    return {"status": "ok", "items": items, "total": total, "limit": limit, "offset": offset}
