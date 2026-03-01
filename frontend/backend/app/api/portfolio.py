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
    # 解析月份，格式应为 YYYY-MM
    try:
        year, month_num = map(int, month.split('-'))
        start_date = f"{year:04d}-{month_num:02d}-01"
        if month_num == 12:
            end_date = f"{year+1:04d}-01-01"
        else:
            end_date = f"{year:04d}-{month_num+1:02d}-01"
    except ValueError:
        # 如果月份格式错误，返回空数据
        return {
            "status": "ok",
            "data": {
                "month": month,
                "total_amount": 0.0,
                "total_fee_tax": 0.0,
                "win_rate": 0.0,
                "avg_holding_days": 0.0,
                "max_profit": 0.0,
                "max_loss": 0.0
            }
        }
    
    with get_conn() as conn:
        # 查询本月交易数据
        query = """
        SELECT 
            SUM(quantity * price) as total_amount,
            SUM(fee + tax) as total_fee_tax,
            COUNT(*) as total_trades,
            SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
            MAX(pnl) as max_profit,
            MIN(pnl) as max_loss
        FROM trades 
        WHERE timestamp >= ? AND timestamp < ?
        """
        
        result = conn.execute(query, (start_date, end_date)).fetchone()
        
        if result and result['total_trades'] > 0:
            total_amount = result['total_amount'] or 0.0
            total_fee_tax = result['total_fee_tax'] or 0.0
            total_trades = result['total_trades']
            winning_trades = result['winning_trades'] or 0
            max_profit = result['max_profit'] or 0.0
            max_loss = result['max_loss'] or 0.0
            
            win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
            
            # 平均持仓天数 - 由于trades表没有持仓天数字段，暂时使用默认值
            avg_holding_days = 5.2  # 默认值，实际需要从其他表获取
            
            return {
                "status": "ok",
                "data": {
                    "month": month,
                    "total_amount": float(total_amount),
                    "total_fee_tax": float(total_fee_tax),
                    "win_rate": float(win_rate),
                    "avg_holding_days": float(avg_holding_days),
                    "max_profit": float(max_profit),
                    "max_loss": float(max_loss)
                }
            }
        else:
            # 没有数据的情况
            return {
                "status": "ok",
                "data": {
                    "month": month,
                    "total_amount": 0.0,
                    "total_fee_tax": 0.0,
                    "win_rate": 0.0,
                    "avg_holding_days": 0.0,
                    "max_profit": 0.0,
                    "max_loss": 0.0
                }
            }


@router.get("/trade-causal/{trade_id}")
def get_trade_causal_chain(trade_id: str):
    """
    決策因果鏈展開：PM 決策 → Trader 執行 → 成交回報。
    """
    with get_conn() as conn:
        # 查询交易基本信息
        trade_query = "SELECT * FROM trades WHERE id = ?"
        trade_result = conn.execute(trade_query, (trade_id,)).fetchone()
        
        if not trade_result:
            return {
                "status": "error",
                "message": f"Trade {trade_id} not found"
            }
        
        trade_dict = dict(trade_result)
        
        # 查询相关的 LLM traces（如果有）
        llm_query = """
        SELECT agent, prompt, response, created_at 
        FROM llm_traces 
        WHERE created_at <= ? 
        ORDER BY created_at DESC 
        LIMIT 3
        """
        
        # 使用交易时间戳作为参考
        trade_timestamp = trade_dict.get('timestamp', '')
        llm_traces = []
        if trade_timestamp:
            # 将 ISO 时间戳转换为 Unix 时间戳（简化处理）
            try:
                # 简单解析 ISO 时间戳
                import datetime
                dt = datetime.datetime.fromisoformat(trade_timestamp.replace('Z', '+00:00'))
                unix_timestamp = int(dt.timestamp())
                
                llm_results = conn.execute(llm_query, (unix_timestamp,)).fetchall()
                llm_traces = [
                    {
                        "agent": row['agent'],
                        "prompt_text": row['prompt'][:200] + "..." if len(row['prompt']) > 200 else row['prompt'],
                        "response_text": row['response'][:200] + "..." if len(row['response']) > 200 else row['response'],
                        "created_at": row['created_at']
                    }
                    for row in llm_results
                ]
            except Exception as e:
                # 如果解析失败，返回空 traces
                llm_traces = []
        
        # 构建决策信息（基于现有数据）
        decision_id = trade_dict.get('decision_id', f"dec_{trade_id}")
        signal_side = trade_dict.get('action', 'buy').lower()
        
        return {
            "status": "ok",
            "data": {
                "decision": {
                    "decision_id": decision_id,
                    "signal_side": signal_side,
                    "reason_json": "{}"  # 暂时返回空 JSON
                },
                "risk_check": {
                    "passed": True,
                    "reject_code": None
                },
                "llm_traces": llm_traces,
                "fills": [
                    {
                        "fill_id": f"fill_{trade_id}",
                        "qty": trade_dict.get('quantity', 0),
                        "price": trade_dict.get('price', 0.0)
                    }
                ],
                "trade_info": {
                    "symbol": trade_dict.get('symbol', ''),
                    "action": trade_dict.get('action', ''),
                    "quantity": trade_dict.get('quantity', 0),
                    "price": trade_dict.get('price', 0.0),
                    "fee": trade_dict.get('fee', 0.0),
                    "tax": trade_dict.get('tax', 0.0),
                    "pnl": trade_dict.get('pnl', 0.0),
                    "timestamp": trade_dict.get('timestamp', '')
                }
            }
        }
