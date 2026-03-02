from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Query

from app.db import get_conn
from app.services.shioaji_service import get_positions, _get_system_simulation_mode

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

_LOCKED_PATH = os.path.join(os.path.dirname(__file__), "../../../../config/locked_symbols.json")


def _read_locked() -> list:
    try:
        with open(_LOCKED_PATH, "r") as f:
            return json.load(f).get("locked", [])
    except Exception:
        return []


def _write_locked(symbols: list) -> None:
    with open(_LOCKED_PATH, "w") as f:
        json.dump({"locked": sorted(set(symbols))}, f, indent=2)


@router.get("/locks")
def list_locked_symbols():
    """Return the list of locked symbols (sell-forbidden)."""
    return {"status": "ok", "locked": _read_locked()}


@router.post("/lock/{symbol}")
def lock_symbol(symbol: str):
    """Lock a symbol — AI agent cannot sell it."""
    symbol = symbol.strip().upper()
    locked = _read_locked()
    if symbol not in locked:
        locked.append(symbol)
        _write_locked(locked)
    return {"status": "ok", "locked": sorted(locked)}


@router.delete("/lock/{symbol}")
def unlock_symbol(symbol: str):
    """Unlock a symbol — allow AI agent to sell again."""
    symbol = symbol.strip().upper()
    locked = [s for s in _read_locked() if s != symbol]
    _write_locked(locked)
    return {"status": "ok", "locked": locked}


@router.get("/positions")
def portfolio_positions(source: str = "shioaji", simulation: Optional[bool] = None):
    """Return portfolio positions.

    source: mock|shioaji
    simulation: None = read from system_state.json (mirrors System page toggle)
    """
    if simulation is None:
        simulation = _get_system_simulation_mode()

    source = source.lower().strip()
    if source not in {"mock", "shioaji"}:
        source = "mock"

    result = get_positions(source=source, simulation=simulation)

    # If broker returns no positions, compute from orders+fills in DB
    if not result.get("positions"):
        try:
            with get_conn() as conn:
                rows = conn.execute("""
                    SELECT
                      o.symbol,
                      SUM(CASE WHEN o.side='buy'  THEN f.qty ELSE 0 END)
                    - SUM(CASE WHEN o.side='sell' THEN f.qty ELSE 0 END) AS net_qty,
                      ROUND(
                        SUM(CASE WHEN o.side='buy' THEN f.qty * f.price ELSE 0 END)
                        / MAX(SUM(CASE WHEN o.side='buy' THEN f.qty ELSE 0 END), 1),
                      2) AS avg_price
                    FROM orders o
                    JOIN fills f ON f.order_id = o.order_id
                    WHERE o.status IN ('filled', 'partially_filled')
                    GROUP BY o.symbol
                    HAVING net_qty > 0
                """).fetchall()
            if rows:
                result = {
                    "source": "db_fills",
                    "simulation": simulation,
                    "positions": [
                        {
                            "account": "SIM",
                            "symbol": r["symbol"],
                            "name": r["symbol"],
                            "qty": int(r["net_qty"]),
                            "avg_price": float(r["avg_price"]),
                            "last_price": None,
                            "market_value": None,
                            "unrealized_pnl": None,
                            "currency": "TWD",
                        }
                        for r in rows
                    ],
                }
        except Exception:
            pass

    # Attach locked status to each position
    locked_set = set(_read_locked())
    for p in result.get("positions", []):
        p["locked"] = p.get("symbol", "").upper() in locked_set

    return {"status": "ok", **result}


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

    # Build WHERE from orders+fills (orders.status already filters to filled orders)
    base_where: List[str] = ["o.status IN ('filled', 'partially_filled')"]
    params: List[Any] = []

    if start:
        base_where.append("o.ts_submit >= ?")
        params.append(start)
    if end:
        base_where.append("o.ts_submit <= ?")
        params.append(end)
    if symbol_norm:
        base_where.append("UPPER(o.symbol) = ?")
        params.append(symbol_norm)
    if trade_type:
        base_where.append("LOWER(o.side) = ?")
        params.append(trade_type)

    where_sql = "WHERE " + " AND ".join(base_where)

    order_map = {
        "time": "o.ts_submit",
        "amount": "SUM(f.qty * f.price)",
        "pnl": "o.ts_submit",  # no realized pnl yet; fallback to time
    }
    order_expr = order_map[sort_by]
    direction = "ASC" if sort_dir == "asc" else "DESC"

    count_sql = f"""
        SELECT COUNT(DISTINCT o.order_id) AS cnt
        FROM orders o
        JOIN fills f ON f.order_id = o.order_id
        {where_sql}
    """

    select_sql = f"""
        SELECT
          o.order_id                                              AS id,
          o.ts_submit                                            AS timestamp,
          o.symbol,
          o.side                                                 AS action,
          CAST(SUM(f.qty) AS INTEGER)                           AS quantity,
          ROUND(CAST(SUM(f.qty * f.price) AS REAL)
                / MAX(CAST(SUM(f.qty) AS REAL), 1), 2)          AS price,
          SUM(f.fee)                                             AS fee,
          SUM(f.tax)                                             AS tax,
          NULL                                                   AS pnl,
          o.strategy_version                                     AS agent_id,
          o.decision_id,
          ROUND(SUM(f.qty * f.price), 2)                        AS amount
        FROM orders o
        JOIN fills f ON f.order_id = o.order_id
        {where_sql}
        GROUP BY o.order_id, o.ts_submit, o.symbol, o.side,
                 o.strategy_version, o.decision_id
        ORDER BY {order_expr} {direction}
        LIMIT ? OFFSET ?
    """.strip()

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
    P1-5: 持倉詳情 — 查詢真實 DB，設計書 §4.1。

    資料來源（按優先級）:
    - entry_reason: llm_traces 表中 PM agent 的 response
    - stop_loss / take_profit: position_params 表（若存在），否則基於 avg_price 推算
    - chip_trend: chip_trend 表（若存在），否則回傳空陣列
    - pm_authorization: llm_traces PM agent 原始 response
    """
    symbol = symbol.strip().upper()

    import os, json
    cap_path = os.path.join(os.path.dirname(__file__), "../../../../config/capital.json")
    def_sl, def_tp = 0.05, 0.10
    try:
        if os.path.exists(cap_path):
            with open(cap_path, 'r') as f:
                cap_data = json.load(f)
                def_sl = float(cap_data.get("default_stop_loss_pct", 0.05))
                def_tp = float(cap_data.get("default_take_profit_pct", 0.10))
    except Exception: pass

    with get_conn() as conn:
        # 1. 取最近的 PM 決策（從 trades 找到買入時間再找 llm_traces）
        entry_reason = "暫無進場資料（請確認 llm_traces 表是否有對應筆數）"
        pm_authorization = None
        avg_price = None

        trade_row = conn.execute(
            """SELECT o.ts_submit AS timestamp,
                      ROUND(SUM(f.qty*f.price)/MAX(SUM(f.qty),1),2) AS price
               FROM orders o JOIN fills f ON f.order_id=o.order_id
               WHERE UPPER(o.symbol)=? AND LOWER(o.side)='buy'
               GROUP BY o.order_id ORDER BY o.ts_submit DESC LIMIT 1""",
            (symbol,)
        ).fetchone()

        if trade_row:
            avg_price = trade_row["price"]
            trade_ts = trade_row["timestamp"]
            try:
                import datetime as _dt
                dt = _dt.datetime.fromisoformat(str(trade_ts).replace("Z", "+00:00"))
                ts_unix = int(dt.timestamp())
                pm_row = conn.execute(
                    """SELECT response FROM llm_traces
                       WHERE LOWER(agent) LIKE '%pm%'
                         AND created_at <= ? AND created_at >= ?
                       ORDER BY created_at DESC LIMIT 1""",
                    (ts_unix + 300, ts_unix - 300)
                ).fetchone()
                if pm_row and pm_row["response"]:
                    pm_authorization = pm_row["response"]
                    entry_reason = pm_row["response"][:500]
            except Exception:
                pass

        # 2. 止損/止盈 — 嘗試讀 position_params 表，否則基於 avg_price 推算
        stop_loss = None
        take_profit = None
        try:
            pp = conn.execute(
                "SELECT stop_loss, take_profit FROM position_params WHERE UPPER(symbol)=? LIMIT 1",
                (symbol,)
            ).fetchone()
            if pp:
                stop_loss = pp["stop_loss"]
                take_profit = pp["take_profit"]
        except Exception:
            pass  # 表可能不存在

        if avg_price and (stop_loss is None or take_profit is None):
            p = float(avg_price)
            if stop_loss is None:
                stop_loss = round(p * (1.0 - def_sl), 2)
            if take_profit is None:
                take_profit = round(p * (1.0 + def_tp), 2)

        # 3. 籌碼趨勢 — 嘗試讀 chip_trend 表
        chip_trend = []
        try:
            rows = conn.execute(
                """SELECT date, institution_buy, institution_sell, score
                   FROM chip_trend WHERE UPPER(symbol)=?
                   ORDER BY date DESC LIMIT 7""",
                (symbol,)
            ).fetchall()
            chip_trend = [
                {"date": r["date"], "institution_buy": r["institution_buy"],
                 "institution_sell": r["institution_sell"], "score": r["score"]}
                for r in rows
            ]
        except Exception:
            pass  # 表可能不存在

    return {
        "status": "ok",
        "data": {
            "symbol": symbol,
            "entry_reason": entry_reason,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "pm_authorization": pm_authorization or "暫無 PM 授權資料",
            "chip_trend": chip_trend
        }
    }


@router.get("/kpis")
def get_portfolio_kpis():
    """
    P1-5: KPI 卡片補齊缺失指標: 可用現金、今日成交筆數、整體勝率。
    """
    import datetime
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")

    import os, json
    cap_path = os.path.join(os.path.dirname(__file__), "../../../../config/capital.json")
    try:
        with open(cap_path, 'r') as f:
            cap_data = json.load(f)
            available_cash = float(cap_data.get("total_capital_twd", 500000.0))
            def_sl = float(cap_data.get("default_stop_loss_pct", 0.05))
            def_tp = float(cap_data.get("default_take_profit_pct", 0.10))
    except Exception:
        available_cash = 500000.0
        def_sl = 0.05
        def_tp = 0.10
    today_trades_count = 0
    overall_win_rate = 0.0

    try:
        with get_conn() as conn:
            # Today's filled orders count (orders+fills schema)
            today_count_row = conn.execute(
                """SELECT COUNT(DISTINCT o.order_id) AS cnt
                   FROM orders o JOIN fills f ON f.order_id=o.order_id
                   WHERE DATE(o.ts_submit)=?
                     AND o.status IN ('filled','partially_filled')""",
                (today,)
            ).fetchone()
            if today_count_row:
                today_trades_count = today_count_row["cnt"]

            # overall_win_rate: read from daily_pnl_summary (written by pnl_engine on sell fills)
            try:
                from openclaw.pnl_engine import get_overall_win_rate as _win_rate
                overall_win_rate = _win_rate(conn)
            except Exception:
                pass

            # Try to get latest cash from position snapshots if available
            try:
                snapshot_row = conn.execute(
                    "SELECT available_cash FROM position_snapshots ORDER BY timestamp DESC LIMIT 1"
                ).fetchone()
                if snapshot_row and snapshot_row["available_cash"] is not None:
                    available_cash = snapshot_row["available_cash"]
            except Exception:
                pass
    except Exception as e:
        pass # fallback to defaults

    return {
        "status": "ok",
        "data": {
            "available_cash": available_cash,
            "today_trades_count": today_trades_count,
            "overall_win_rate": overall_win_rate
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
        # 查询本月交易数据 (orders JOIN fills，trades 表目前為空)
        query = """
        SELECT
            SUM(f.qty * f.price)  AS total_amount,
            SUM(f.fee + f.tax)    AS total_fee_tax,
            COUNT(DISTINCT o.order_id) AS total_trades,
            0                     AS winning_trades,
            NULL                  AS max_profit,
            NULL                  AS max_loss
        FROM orders o
        JOIN fills f ON f.order_id = o.order_id
        WHERE o.ts_submit >= ? AND o.ts_submit < ?
        """

        result = conn.execute(query, (start_date, end_date)).fetchone()

        if result and result['total_trades'] > 0:
            total_amount = result['total_amount'] or 0.0
            total_fee_tax = result['total_fee_tax'] or 0.0
            total_trades = result['total_trades']
            winning_trades = result['winning_trades'] or 0
            max_profit = result['max_profit']
            max_loss = result['max_loss']

            win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

            # P1-7: 計算平均持倉天數 — 配對同一標的買/賣訂單
            avg_holding_days = 0.0
            try:
                import datetime as _dt
                buys = conn.execute(
                    "SELECT symbol, ts_submit AS timestamp FROM orders WHERE LOWER(side)='buy' AND ts_submit>=? AND ts_submit<?",
                    (start_date, end_date)
                ).fetchall()
                sells = conn.execute(
                    "SELECT symbol, ts_submit AS timestamp FROM orders WHERE LOWER(side)='sell' AND ts_submit>=? AND ts_submit<?",
                    (start_date, end_date)
                ).fetchall()
                buy_map: dict = {}
                for b in buys:
                    sym = b["symbol"]
                    buy_map.setdefault(sym, [])
                    buy_map[sym].append(b["timestamp"])
                holding_days_list = []
                for s in sells:
                    sym = s["symbol"]
                    if sym in buy_map and buy_map[sym]:
                        buy_ts = buy_map[sym].pop(0)
                        try:
                            buy_dt = _dt.datetime.fromisoformat(str(buy_ts).replace("Z", "+00:00"))
                            sell_dt = _dt.datetime.fromisoformat(str(s["timestamp"]).replace("Z", "+00:00"))
                            days = abs((sell_dt - buy_dt).total_seconds()) / 86400
                            holding_days_list.append(days)
                        except Exception:
                            pass
                if holding_days_list:
                    avg_holding_days = sum(holding_days_list) / len(holding_days_list)
            except Exception:
                avg_holding_days = 0.0

            return {
                "status": "ok",
                "data": {
                    "month": month,
                    "total_amount": float(total_amount),
                    "total_fee_tax": float(total_fee_tax),
                    "win_rate": float(win_rate),
                    "avg_holding_days": round(float(avg_holding_days), 1),
                    "max_profit": float(max_profit) if max_profit is not None else None,
                    "max_loss": float(max_loss) if max_loss is not None else None,
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


@router.get("/equity-curve")
def get_equity_curve(days: int = 60, start_equity: float = 100000.0):
    """
    P1-6: 損益曲線 — 從 daily_pnl_summary 計算每日累積已實現 PnL。

    回傳格式: [{ date: "YYYY-MM-DD", equity: float }]
    若 DB 無資料，回傳空陣列（前端可 fallback 到 mock）。
    """
    try:
        from openclaw.pnl_engine import get_equity_curve as _eq_curve
        with get_conn() as conn:
            series = _eq_curve(conn, days=days, start_equity=start_equity)
        if series:
            return {"status": "ok", "data": series, "source": "db"}
    except Exception:
        pass
    return {"status": "ok", "data": [], "source": "no_data"}


@router.get("/trade-causal/{trade_id}")
def get_trade_causal_chain(trade_id: str):
    """
    決策因果鏈展開：PM 決策 → Trader 執行 → 成交回報。
    """
    with get_conn() as conn:
        # Look up order + fills (orders+fills schema; trade_id == order_id)
        trade_result = conn.execute(
            """SELECT o.order_id AS id, o.ts_submit AS timestamp, o.symbol,
                      o.side AS action, o.status, o.decision_id, o.strategy_version AS agent_id,
                      ROUND(SUM(f.qty*f.price)/MAX(SUM(f.qty),1),2) AS price,
                      CAST(SUM(f.qty) AS INTEGER) AS quantity,
                      ROUND(SUM(f.qty*f.price),2) AS amount,
                      SUM(f.fee) AS fee, SUM(f.tax) AS tax
               FROM orders o JOIN fills f ON f.order_id=o.order_id
               WHERE o.order_id=?
               GROUP BY o.order_id""",
            (trade_id,)
        ).fetchone()

        if not trade_result:
            return {
                "status": "error",
                "message": f"Trade {trade_id} not found"
            }

        trade_dict = dict(trade_result)

        # 查询相关的 LLM traces
        llm_traces = []
        trade_timestamp = trade_dict.get('timestamp', '')
        if trade_timestamp:
            try:
                import datetime
                dt = datetime.datetime.fromisoformat(trade_timestamp.replace('Z', '+00:00'))
                unix_timestamp = int(dt.timestamp())
                llm_results = conn.execute(
                    """SELECT agent, prompt, response, created_at
                       FROM llm_traces
                       WHERE created_at <= ? AND created_at >= ?
                       ORDER BY created_at DESC LIMIT 3""",
                    (unix_timestamp + 300, unix_timestamp - 300)
                ).fetchall()
                llm_traces = [
                    {
                        "agent": row['agent'],
                        "prompt_text": (row['prompt'] or '')[:200],
                        "response_text": (row['response'] or '')[:200],
                        "created_at": row['created_at']
                    }
                    for row in llm_results
                ]
            except Exception:
                llm_traces = []

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
@router.get("/inventory")
def inventory_list(source: str = "shioaji", simulation: bool = True):
    """Return inventory list. Uses the same data as /positions but formatted for inventory.
    """
    res = get_positions(source=source, simulation=simulation)
    
    # Map portfolio positions to inventory fields
    inventory = []
    positions = res.get("positions", [])
    for p in positions:
        inventory.append({
            "id": p.get("symbol"),
            "code": p.get("symbol"),
            "name": p.get("name"),
            "quantity": p.get("qty"),
            "unitCost": p.get("avg_price"),
            "currentValue": p.get("market_value") or (p.get("qty", 0) * (p.get("last_price") or p.get("avg_price", 0))),
            "status": "正常"
        })
    return inventory
