"""reports.py — Report Context API for OpenClaw investment report skills.

Provides structured trading data context that OpenClaw agents consume
when generating morning/evening/weekly investment reports.

Data sources:
  - positions table (simulated holdings from ticker_watcher)
  - portfolio.json (real holdings, read from workspace-finance)
  - eod_prices (OHLCV history)
  - eod_institution_flows / eod_margin_data (institutional chips)
  - eod_analysis_reports (latest EOD analysis)
  - orders + fills (recent trades)
  - technical_indicators module (MA/RSI/MACD)
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

import app.db as db

router = APIRouter(prefix="/api/reports", tags=["reports"])

_TZ_TWN = timezone(timedelta(hours=8))
_PORTFOLIO_JSON = os.environ.get("PORTFOLIO_JSON_PATH", "")


def conn_dep():
    try:
        with db.get_conn() as conn:
            yield conn
    except HTTPException:
        raise
    except (sqlite3.Error, OSError) as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")


def _read_portfolio_json() -> List[Dict[str, Any]]:
    """Read real holdings from workspace-finance/portfolio.json."""
    try:
        with open(_PORTFOLIO_JSON, "r") as f:
            data = json.load(f)
        return data.get("holdings", [])
    except (OSError, ValueError):
        return []


def _get_sim_positions(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Simulated positions from ai-trader DB."""
    try:
        rows = conn.execute(
            "SELECT p.symbol, p.quantity, p.avg_price, p.current_price, "
            "p.unrealized_pnl, p.state, p.high_water_mark, p.entry_trading_day, "
            "ep.name AS stock_name, ep.close AS eod_close "
            "FROM positions p "
            "LEFT JOIN eod_prices ep ON ep.symbol = p.symbol "
            "  AND ep.trade_date = ("
            "    SELECT MAX(trade_date) FROM eod_prices WHERE symbol = p.symbol"
            "  ) "
            "WHERE p.quantity > 0 ORDER BY p.symbol"
        ).fetchall()
        return [
            {
                "symbol": r["symbol"],
                "name": r["stock_name"] or r["symbol"],
                "quantity": int(r["quantity"]),
                "avg_price": float(r["avg_price"] or 0),
                "current_price": (
                    float(r["current_price"])
                    if r["current_price"] is not None
                    else (float(r["eod_close"]) if r["eod_close"] is not None else None)
                ),
                "unrealized_pnl": (
                    float(r["unrealized_pnl"])
                    if r["unrealized_pnl"] is not None
                    else (
                        round(
                            ((float(r["current_price"]) if r["current_price"] is not None else float(r["eod_close"])) - float(r["avg_price"] or 0))
                            * int(r["quantity"]),
                            2,
                        )
                        if (r["current_price"] is not None or r["eod_close"] is not None)
                        else None
                    )
                ),
                "price_source": (
                    "realtime" if r["current_price"] is not None
                    else ("eod" if r["eod_close"] is not None else None)
                ),
                "state": r["state"],
                "high_water_mark": float(r["high_water_mark"]) if r["high_water_mark"] else None,
                "entry_trading_day": r["entry_trading_day"],
            }
            for r in rows
        ]
    except sqlite3.Error:
        return []


def _get_recent_trades(conn: sqlite3.Connection, days: int = 7) -> List[Dict[str, Any]]:
    """Recent filled orders from the last N days."""
    cutoff = (datetime.now(_TZ_TWN) - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        rows = conn.execute(
            """SELECT o.order_id, o.ts_submit, o.symbol, o.side,
                      CAST(SUM(f.qty) AS INTEGER) AS qty,
                      ROUND(SUM(f.qty * f.price) / MAX(SUM(f.qty), 1), 2) AS avg_price,
                      SUM(f.fee) AS fee, SUM(f.tax) AS tax
               FROM orders o JOIN fills f ON f.order_id = o.order_id
               WHERE o.status IN ('filled','partially_filled')
                 AND o.ts_submit >= ?
               GROUP BY o.order_id
               ORDER BY o.ts_submit DESC""",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []


def _get_technical_indicators(
    conn: sqlite3.Connection, symbols: List[str], days: int = 60,
) -> Dict[str, Any]:
    """Compute MA/RSI/MACD for each symbol using technical_indicators module."""
    result = {}
    try:
        from openclaw.technical_indicators import calc_ma, calc_rsi, calc_macd
    except ImportError:
        return result

    for sym in symbols:
        try:
            rows = conn.execute(
                "SELECT close FROM eod_prices WHERE symbol = ? "
                "ORDER BY trade_date DESC LIMIT ?",
                (sym, days),
            ).fetchall()
            if not rows or len(rows) < 5:
                continue
            closes = [float(r["close"]) for r in reversed(rows)]
            ma5 = calc_ma(closes, 5)
            ma20 = calc_ma(closes, 20)
            rsi = calc_rsi(closes, 14)
            macd_data = calc_macd(closes)
            macd_line = macd_data.get("macd", [])
            signal_line = macd_data.get("signal", [])
            histogram = macd_data.get("histogram", [])

            def _round_optional(value):
                return round(value, 2) if value is not None else None

            def _last_valid(arr):
                for v in reversed(arr):
                    if v is not None:
                        return round(v, 2)
                return None

            result[sym] = {
                "latest_close": closes[-1],
                "ma5": _round_optional(ma5[-1]) if ma5 else None,
                "ma20": _round_optional(ma20[-1]) if ma20 else None,
                "rsi14": _round_optional(rsi[-1]) if rsi else None,
                "macd": _last_valid(macd_line),
                "macd_signal": _last_valid(signal_line),
                "macd_histogram": _last_valid(histogram),
            }
        except (sqlite3.Error, ValueError, IndexError, TypeError):
            continue
    return result


def _get_institution_summary(
    conn: sqlite3.Connection, symbols: List[str],
) -> Dict[str, Any]:
    """Latest institution flows + margin for given symbols."""
    result = {}
    try:
        # Find latest trade_date with data
        date_row = conn.execute(
            "SELECT MAX(trade_date) AS d FROM eod_institution_flows"
        ).fetchone()
        if not date_row or not date_row["d"]:
            return result
        latest_date = date_row["d"]

        placeholders = ",".join("?" for _ in symbols)
        rows = conn.execute(
            f"""SELECT f.symbol, f.name, f.foreign_net, f.trust_net,
                       f.dealer_net, f.total_net,
                       m.margin_balance, m.short_balance
                FROM eod_institution_flows f
                LEFT JOIN eod_margin_data m
                    ON f.trade_date = m.trade_date AND f.symbol = m.symbol
                WHERE f.trade_date = ? AND f.symbol IN ({placeholders})""",
            [latest_date] + [s.upper() for s in symbols],
        ).fetchall()
        for r in rows:
            result[r["symbol"]] = {
                "foreign_net": r["foreign_net"],
                "trust_net": r["trust_net"],
                "dealer_net": r["dealer_net"],
                "total_net": r["total_net"],
                "margin_balance": r["margin_balance"],
                "short_balance": r["short_balance"],
            }
        result["_trade_date"] = latest_date
    except sqlite3.Error:
        pass
    return result


def _get_committee_outlook(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    """Latest strategy_committee proposal within the last 24 hours.

    Extracts bull_thesis / bear_thesis / arbiter_stance from committee_context
    stored in proposal_json. Returns None gracefully if no data or any error.
    """
    try:
        cutoff_ms = int(
            (datetime.now(timezone.utc) - timedelta(hours=24)).timestamp() * 1000
        )
        row = conn.execute(
            """SELECT proposal_id, proposal_json, confidence, created_at
               FROM strategy_proposals
               WHERE generated_by = 'strategy_committee'
                 AND created_at >= ?
               ORDER BY created_at DESC
               LIMIT 1""",
            (cutoff_ms,),
        ).fetchone()
        if not row:
            return None

        proposal_json_raw = row["proposal_json"]
        if not proposal_json_raw:
            return None

        try:
            pj = json.loads(proposal_json_raw) if isinstance(proposal_json_raw, str) else proposal_json_raw
        except (json.JSONDecodeError, TypeError):
            return None

        ctx = pj.get("committee_context", {}) if isinstance(pj, dict) else {}
        bull = ctx.get("bull", {}) if isinstance(ctx, dict) else {}
        bear = ctx.get("bear", {}) if isinstance(ctx, dict) else {}
        arbiter = ctx.get("arbiter", {}) if isinstance(ctx, dict) else {}

        return {
            "proposal_id": row["proposal_id"],
            "created_at": row["created_at"],
            "bull_thesis": bull.get("thesis") if isinstance(bull, dict) else None,
            "bear_thesis": bear.get("thesis") if isinstance(bear, dict) else None,
            "arbiter_stance": arbiter.get("stance") if isinstance(arbiter, dict) else None,
            "arbiter_summary": arbiter.get("summary") if isinstance(arbiter, dict) else None,
            "confidence": float(row["confidence"]) if row["confidence"] is not None else None,
        }
    except sqlite3.Error:
        return None


def _get_latest_eod_analysis(conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    """Latest EOD analysis report."""
    try:
        row = conn.execute(
            "SELECT trade_date, market_summary, technical, strategy "
            "FROM eod_analysis_reports ORDER BY trade_date DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        for key in ("market_summary", "technical", "strategy"):
            if isinstance(d.get(key), str):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d
    except sqlite3.Error:
        return None


@router.get("/context")
def get_report_context(
    type: Literal["morning", "evening", "weekly"] = Query("morning"),
    conn: sqlite3.Connection = Depends(conn_dep),
):
    """Structured trading data context for investment report generation.

    Consumed by OpenClaw finance/researcher agents to enrich reports
    with real trading data from ai-trader.
    """
    now_twn = datetime.now(_TZ_TWN)

    # 1. Real holdings (portfolio.json)
    real_holdings = _read_portfolio_json()
    real_symbols = [h["symbol"] for h in real_holdings]

    # 2. Simulated positions (ai-trader DB)
    sim_positions = _get_sim_positions(conn)
    sim_symbols = [p["symbol"] for p in sim_positions]

    # 3. All symbols for technical/chips lookup
    all_symbols = list(set(real_symbols + sim_symbols))

    # 4. Technical indicators for all symbols
    technicals = _get_technical_indicators(conn, all_symbols)

    # 5. Institution chips for all symbols
    chips = _get_institution_summary(conn, all_symbols)

    # 6. Recent trades (last 7 days for morning/evening, 14 for weekly)
    trade_days = 14 if type == "weekly" else 7
    recent_trades = _get_recent_trades(conn, days=trade_days)

    # 7. Latest EOD analysis
    eod_analysis = _get_latest_eod_analysis(conn)

    # 8. Committee outlook (last 24h, morning/evening only)
    committee_outlook = _get_committee_outlook(conn) if type in ("morning", "evening") else None

    # 10. System state
    system_state = None
    try:
        state_path = os.path.join(
            os.path.dirname(__file__), "../../../../config/system_state.json"
        )
        with open(state_path) as f:
            system_state = json.load(f)
    except (OSError, ValueError):
        pass

    return {
        "status": "ok",
        "generated_at": now_twn.isoformat(),
        "report_type": type,
        "real_holdings": {
            "source": "portfolio.json",
            "note": "actual brokerage positions",
            "holdings": real_holdings,
        },
        "simulated_positions": {
            "source": "ai-trader DB (simulation mode)",
            "note": "paper trading positions from ticker_watcher",
            "positions": sim_positions,
        },
        "technical_indicators": technicals,
        "institution_chips": chips,
        "recent_trades": recent_trades,
        "eod_analysis": eod_analysis,
        "committee_outlook": committee_outlook,
        "system_state": {
            "simulation_mode": system_state.get("simulation_mode", True) if system_state else True,
            "trading_enabled": system_state.get("trading_enabled", False) if system_state else False,
        },
    }
