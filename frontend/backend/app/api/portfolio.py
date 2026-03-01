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


@router.get("/position-detail/{symbol}")
def get_position_detail(symbol: str):
    """
    获取持倉詳情：進場理由、止損/止盈設定、PM 授權原文、籌碼趨勢歷史。
    """
    # 模拟数据
    return {
        "status": "ok",
        "data": {
            "symbol": symbol,
            "entry_reason": "基于技术分析和市场情绪入场",
            "stop_loss": 550.0,
            "take_profit": 620.0,
            "pm_authorization": "PM 授权原文：...",
            "chip_trend": [
                {"date": "2026-02-25", "institution_buy": 1200, "institution_sell": 800, "score": 7},
                {"date": "2026-02-26", "institution_buy": 1500, "institution_sell": 600, "score": 8},
                {"date": "2026-02-27", "institution_buy": 1800, "institution_sell": 900, "score": 6},
                {"date": "2026-02-28", "institution_buy": 2000, "institution_sell": 1200, "score": 5},
            ]
        }
    }


@router.get("/monthly-summary")
def get_monthly_summary(month: str = "2026-02"):
    """
    月度統計摘要：本月成交金額、手續費+稅金淨成本、勝率、平均持倉天數、最大單筆獲利/虧損。
    """
    # 模拟数据
    return {
        "status": "ok",
        "data": {
            "month": month,
            "total_amount": 1250000.0,
            "total_fee_tax": 1250.0,
            "win_rate": 0.65,
            "avg_holding_days": 5.2,
            "max_profit": 50000.0,
            "max_loss": -20000.0
        }
    }


@router.get("/trade-causal/{trade_id}")
def get_trade_causal_chain(trade_id: str):
    """
    決策因果鏈展開：PM 決策 → Trader 執行 → 成交回報。
    """
    # 模拟数据
    return {
        "status": "ok",
        "data": {
            "decision": {"decision_id": f"dec_{trade_id}", "signal_side": "buy", "reason_json": "{}"},
            "risk_check": {"passed": True, "reject_code": None},
            "llm_traces": [{"agent": "PM", "prompt_text": "...", "response_text": "..."}],
            "fills": [{"fill_id": f"fill_{trade_id}", "qty": 1000, "price": 580.0}]
        }
    }
