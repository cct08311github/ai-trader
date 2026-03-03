from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.db import get_conn, get_conn_rw
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
def portfolio_positions(simulation: Optional[bool] = None):
    """Return portfolio positions from positions table (ticker_watcher source of truth).

    In simulation mode the positions table is always up-to-date.
    Shioaji live API is only used when simulation=False AND broker is reachable.
    """
    if simulation is None:
        simulation = _get_system_simulation_mode()

    # ── Primary source: positions table (maintained by ticker_watcher) ──────
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT symbol, quantity, avg_price, current_price, "
                "unrealized_pnl, chip_health_score, sector "
                "FROM positions WHERE quantity > 0 ORDER BY symbol"
            ).fetchall()
        if rows:
            locked_set = set(_read_locked())
            positions = [
                {
                    "symbol": r["symbol"],
                    "name": r["symbol"],
                    "qty": int(r["quantity"]),
                    "avg_price": float(r["avg_price"] or 0),
                    "last_price": float(r["current_price"]) if r["current_price"] else None,
                    "unrealized_pnl": float(r["unrealized_pnl"]) if r["unrealized_pnl"] else None,
                    "chip_health_score": r["chip_health_score"],
                    "sector": r["sector"],
                    "locked": r["symbol"].upper() in locked_set,
                }
                for r in rows
            ]
            return {"status": "ok", "source": "db_positions", "simulation": simulation, "positions": positions}
    except Exception:
        pass

    # ── Fallback: compute net positions from orders+fills ────────────────────
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
            locked_set = set(_read_locked())
            positions = [
                {
                    "symbol": r["symbol"],
                    "name": r["symbol"],
                    "qty": int(r["net_qty"]),
                    "avg_price": float(r["avg_price"]),
                    "last_price": None,
                    "locked": r["symbol"].upper() in locked_set,
                }
                for r in rows
            ]
            return {"status": "ok", "source": "db_fills", "simulation": simulation, "positions": positions}
    except Exception:
        pass

    return {"status": "ok", "source": "no_data", "simulation": simulation, "positions": []}


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
    持倉詳情 — 完整決策鏈：decisions → risk_checks → orders → fills + 止損止盈 + 籌碼趨勢。
    """
    import os, json as _json, datetime as _dt

    symbol = symbol.strip().upper()

    cap_path = os.path.join(os.path.dirname(__file__), "../../../../config/capital.json")
    def_sl, def_tp = 0.05, 0.10
    try:
        with open(cap_path, "r") as f:
            cap = _json.load(f)
            def_sl = float(cap.get("default_stop_loss_pct", 0.05))
            def_tp = float(cap.get("default_take_profit_pct", 0.10))
    except Exception:  # pragma: no cover
        pass  # pragma: no cover

    with get_conn() as conn:
        # ── 1. 最近一筆 BUY 的 order + decision + risk_check ─────────────
        order_row = conn.execute(
            """SELECT o.order_id, o.decision_id, o.ts_submit, o.qty, o.price, o.status,
                      o.strategy_version
               FROM orders o
               WHERE UPPER(o.symbol) = ? AND LOWER(o.side) = 'buy'
                 AND o.status IN ('filled', 'partially_filled')
               ORDER BY o.ts_submit DESC LIMIT 1""",
            (symbol,),
        ).fetchone()

        decision_info = None
        risk_info = None
        fills_info = []
        avg_price = None

        if order_row:
            order_id = order_row["order_id"]
            decision_id = order_row["decision_id"]
            avg_price = float(order_row["price"] or 0) or None

            # Decision record
            if decision_id:
                dec = conn.execute(
                    """SELECT ts, strategy_id, strategy_version, signal_side,
                              signal_score, reason_json
                       FROM decisions WHERE decision_id = ? LIMIT 1""",
                    (decision_id,),
                ).fetchone()
                if dec:
                    try:
                        reason = _json.loads(dec["reason_json"] or "{}")
                    except Exception:
                        reason = {}
                    decision_info = {
                        "decision_id": decision_id,
                        "ts": dec["ts"],
                        "strategy_id": dec["strategy_id"],
                        "strategy_version": dec["strategy_version"],
                        "signal_side": dec["signal_side"],
                        "signal_score": dec["signal_score"],
                        "reason": reason,
                    }

                # Risk check for this decision
                rc = conn.execute(
                    """SELECT passed, reject_code, metrics_json
                       FROM risk_checks WHERE decision_id = ? LIMIT 1""",
                    (decision_id,),
                ).fetchone()
                if rc:
                    try:
                        metrics = _json.loads(rc["metrics_json"] or "{}")
                    except Exception:
                        metrics = {}
                    risk_info = {
                        "passed": bool(rc["passed"]),
                        "reject_code": rc["reject_code"],
                        "metrics": metrics,
                    }

            # Fills for this order
            fill_rows = conn.execute(
                """SELECT fill_id, ts_fill, qty, price, fee, tax
                   FROM fills WHERE order_id = ? ORDER BY ts_fill""",
                (order_id,),
            ).fetchall()
            fills_info = [
                {
                    "fill_id": r["fill_id"],
                    "ts": r["ts_fill"],
                    "qty": r["qty"],
                    "price": r["price"],
                    "fee": r["fee"],
                    "tax": r["tax"],
                }
                for r in fill_rows
            ]

        # ── 2. 止損/止盈 ─────────────────────────────────────────────────
        stop_loss = None
        take_profit = None
        try:
            pp = conn.execute(
                "SELECT stop_loss, take_profit FROM position_params WHERE UPPER(symbol)=? LIMIT 1",
                (symbol,),
            ).fetchone()
            if pp:
                stop_loss = pp["stop_loss"]
                take_profit = pp["take_profit"]
        except Exception:
            pass

        if avg_price:
            p = float(avg_price)
            if stop_loss is None:
                stop_loss = round(p * (1.0 - def_sl), 2)
            if take_profit is None:
                take_profit = round(p * (1.0 + def_tp), 2)

        # ── 3. 籌碼趨勢 ──────────────────────────────────────────────────
        chip_trend = []
        try:
            rows = conn.execute(
                """SELECT date, institution_buy, institution_sell, score
                   FROM chip_trend WHERE UPPER(symbol) = ?
                   ORDER BY date DESC LIMIT 7""",
                (symbol,),
            ).fetchall()
            chip_trend = [
                {
                    "date": r["date"],
                    "institution_buy": r["institution_buy"],
                    "institution_sell": r["institution_sell"],
                    "score": r["score"],
                }
                for r in rows
            ]
        except Exception:
            pass

    return {
        "status": "ok",
        "data": {
            "symbol": symbol,
            "decision": decision_info,
            "risk_check": risk_info,
            "fills": fills_info,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "chip_trend": chip_trend,
            # legacy fields kept for backwards compat
            "entry_reason": (
                f"策略 {decision_info['strategy_id']} 信心 {decision_info['signal_score']}"
                if decision_info else "暫無進場資料"
            ),
            "pm_authorization": "暫無 PM 授權資料（ticker_watcher 不走 PM LLM）",
        },
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
    except Exception:  # pragma: no cover
        available_cash = 500000.0  # pragma: no cover
        def_sl = 0.05  # pragma: no cover
        def_tp = 0.10  # pragma: no cover
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
    except Exception as e:  # pragma: no cover
        pass  # pragma: no cover  # fallback to defaults

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
            except Exception:  # pragma: no cover
                avg_holding_days = 0.0  # pragma: no cover

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
@router.post("/close-position/{symbol}")
def close_position(symbol: str):
    """
    手動平倉：對 symbol 下反向賣單，透過 SimBrokerAdapter 立即成交並寫入 DB。
    鎖定部位回傳 403。
    """
    import datetime as _dt

    symbol = symbol.strip().upper()

    # ── 1. 鎖定檢查 ──────────────────────────────────────────────────────
    if symbol in {s.upper() for s in _read_locked()}:
        raise HTTPException(status_code=403, detail=f"{symbol} 已鎖定，無法平倉")

    with get_conn() as conn:
        # ── 2. 計算淨持倉 qty ─────────────────────────────────────────────
        net_row = conn.execute(
            """SELECT
                 SUM(CASE WHEN o.side='buy'  THEN f.qty ELSE 0 END)
               - SUM(CASE WHEN o.side='sell' THEN f.qty ELSE 0 END) AS net_qty,
                 ROUND(SUM(CASE WHEN o.side='buy' THEN f.qty*f.price ELSE 0 END)
                       / MAX(SUM(CASE WHEN o.side='buy' THEN f.qty ELSE 0 END), 1), 2) AS avg_price
               FROM orders o JOIN fills f ON f.order_id=o.order_id
               WHERE UPPER(o.symbol)=? AND o.status IN ('filled','partially_filled')""",
            (symbol,),
        ).fetchone()

        net_qty = int(net_row["net_qty"] or 0) if net_row else 0
        avg_price = float(net_row["avg_price"] or 0) if net_row else 0.0

        if net_qty <= 0:
            raise HTTPException(status_code=400, detail=f"{symbol} 無持倉可平")

        # ── 3. 取賣出價格（當前價 or 均價 fallback）───────────────────────
        sell_price = avg_price
        try:
            price_row = conn.execute(
                "SELECT current_price FROM positions WHERE UPPER(symbol)=? LIMIT 1",
                (symbol,),
            ).fetchone()
            if price_row and price_row["current_price"]:
                sell_price = float(price_row["current_price"])
        except Exception:
            pass

        if sell_price <= 0:
            raise HTTPException(status_code=400, detail=f"{symbol} 無法取得有效賣出價格")

    # ── 4. 建立 decision record ───────────────────────────────────────────
    decision_id = str(uuid.uuid4())
    now_iso = _dt.datetime.utcnow().isoformat(timespec="microseconds") + "+00:00"

    # ── 5. SimBrokerAdapter 提交賣單 ──────────────────────────────────────
    try:
        from openclaw.broker import SimBrokerAdapter
        from openclaw.risk_engine import OrderCandidate
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"無法載入 broker 模組: {e}")

    candidate = OrderCandidate(
        symbol=symbol,
        side="sell",
        qty=net_qty,
        price=sell_price,
        order_type="limit",
    )
    broker = SimBrokerAdapter()
    order_id = str(uuid.uuid4())
    submission = broker.submit_order(order_id, candidate)

    if submission.status != "submitted":
        raise HTTPException(status_code=500, detail=f"broker 拒絕下單: {submission.reason}")

    # ── 6. Poll 成交 ──────────────────────────────────────────────────────
    fills_collected: list[dict] = []
    final_status = "submitted"
    last_filled_qty = 0
    for _ in range(12):
        s = broker.poll_order_status(submission.broker_order_id)
        if s is None:
            time.sleep(0.3)
            continue
        new_qty = max(last_filled_qty, int(s.filled_qty))
        delta = new_qty - last_filled_qty
        if delta > 0:
            fills_collected.append({
                "fill_id": str(uuid.uuid4()),
                "qty": delta,
                "price": s.avg_fill_price,
                "fee": s.fee,
                "tax": s.tax,
            })
            last_filled_qty = new_qty
        if s.status in {"filled", "cancelled", "rejected", "expired"}:
            final_status = s.status
            break
        time.sleep(0.3)

    # ── 7. 寫入 DB ────────────────────────────────────────────────────────
    with get_conn_rw() as conn:
        # decisions
        conn.execute(
            """INSERT OR IGNORE INTO decisions
               (decision_id,ts,symbol,strategy_id,strategy_version,
                signal_side,signal_score,signal_ttl_ms,llm_ref,reason_json)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (decision_id, now_iso, symbol, "manual_close", "ui_v1",
             "sell", 1.0, 0, None,
             json.dumps({"source": "manual_close", "trigger": "ui"})),
        )

        # risk_checks (manual close always passes)
        conn.execute(
            """INSERT OR IGNORE INTO risk_checks
               (check_id,decision_id,ts,passed,reject_code,metrics_json)
               VALUES(?,?,?,?,?,?)""",
            (str(uuid.uuid4()), decision_id, now_iso, 1, None,
             json.dumps({"manual": True})),
        )

        # orders
        conn.execute(
            """INSERT OR IGNORE INTO orders
               (order_id,decision_id,broker_order_id,ts_submit,
                symbol,side,qty,price,order_type,tif,status,strategy_version)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (order_id, decision_id, submission.broker_order_id, now_iso,
             symbol, "sell", net_qty, sell_price,
             "limit", "IOC", final_status, "ui_v1"),
        )

        # fills
        for f in fills_collected:
            conn.execute(
                """INSERT OR IGNORE INTO fills
                   (fill_id,order_id,ts_fill,qty,price,fee,tax)
                   VALUES(?,?,?,?,?,?,?)""",
                (f["fill_id"], order_id, now_iso,
                 f["qty"], f["price"], f["fee"], f["tax"]),
            )

        # pnl_engine hook — update positions table
        try:
            from openclaw.pnl_engine import on_sell_filled, sync_positions_table
            for f in fills_collected:
                on_sell_filled(conn, symbol=symbol, qty=f["qty"],
                               sell_price=f["price"], fee=f["fee"], tax=f["tax"])
            sync_positions_table(conn)
        except Exception:
            pass  # non-critical

    return {
        "status": "ok",
        "symbol": symbol,
        "qty_closed": last_filled_qty,
        "sell_price": sell_price,
        "order_status": final_status,
        "order_id": order_id,
        "fills": fills_collected,
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


# ── 即時報價 ──────────────────────────────────────────────────────────────────

@router.get("/quote/{symbol}")
def get_quote_snapshot(symbol: str):
    """一次性 snapshot：收盤價、漲跌幅、成交量、金額、買1/賣1。"""
    symbol = symbol.strip().upper()
    try:
        from app.services.shioaji_service import _get_api
        api = _get_api(simulation=True)
        contract = api.Contracts.Stocks[symbol]
        snaps = api.snapshots([contract])
        if snaps:
            s = snaps[0]
            close     = float(getattr(s, "close",        0) or 0)
            reference = float(getattr(s, "reference",    0) or 0)
            volume    = int(getattr(s, "total_volume",   0) or 0)
            total_amt = int(
                getattr(s, "total_amount", None) or getattr(s, "amount", 0) or 0
            )
            bid1 = float(getattr(s, "bid_price",  0) or 0)
            ask1 = float(
                getattr(s, "sell_price", None) or getattr(s, "ask_price", 0) or 0
            )
            chg_price = round(close - reference, 2) if reference else 0.0
            chg_rate  = round((close - reference) / reference * 100, 2) if reference else 0.0
            return {
                "status": "ok", "symbol": symbol, "source": "shioaji",
                "data": {
                    "close": close, "reference": reference,
                    "change_price": chg_price, "change_rate": chg_rate,
                    "volume": volume, "total_amount": total_amt,
                    "bid_price": bid1, "ask_price": ask1,
                },
            }
    except Exception:
        pass
    return {"status": "ok", "symbol": symbol, "source": "closed", "data": None}


@router.get("/quote-stream/{symbol}")
async def get_quote_stream(symbol: str, request: Request):
    """SSE：Shioaji BidAsk 即時訂閱，推送五檔行情到前端。"""
    import asyncio as _asyncio
    import json as _json

    symbol = symbol.strip().upper()

    async def generator():
        from app.services.shioaji_service import _get_api, quote_service

        queue: _asyncio.Queue = _asyncio.Queue(maxsize=30)
        loop = _asyncio.get_event_loop()
        api = None
        try:
            api = _get_api(simulation=True)
            quote_service.subscribe(symbol, queue, loop, api)
        except Exception:
            pass  # Market closed or Shioaji unavailable

        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await _asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {_json.dumps(data)}\n\n"
                except _asyncio.TimeoutError:
                    yield 'data: {"type":"ping"}\n\n'
        finally:
            if api:
                quote_service.unsubscribe(symbol, queue, api)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
