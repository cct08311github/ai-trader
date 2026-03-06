"""chips.py — 法人籌碼 API Router

Endpoints:
  GET /api/chips/{trade_date}/institution-flows   三大法人買賣超
  GET /api/chips/{trade_date}/margin              融資借券餘額
  GET /api/chips/{trade_date}/summary             兩者摘要（依 symbol 合併）
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

import app.db as db

router = APIRouter(prefix="/api/chips", tags=["chips"])


# ── DB connection dependency ─────────────────────────────────────────────────

def conn_dep():
    try:
        with db.get_conn() as conn:
            yield conn
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rows_to_list(rows) -> List[Dict[str, Any]]:
    return [dict(r) for r in rows]


def _check_date(trade_date: str) -> None:
    """Reject obviously malformed dates to prevent SQL injection."""
    if len(trade_date) != 10 or trade_date[4] != "-" or trade_date[7] != "-":
        raise HTTPException(status_code=422, detail="trade_date 格式必須為 YYYY-MM-DD")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/{trade_date}/institution-flows")
def get_institution_flows(
    trade_date: str,
    conn: sqlite3.Connection = Depends(conn_dep),
):
    """三大法人買賣超（外資/投信/自營），依 total_net 排序。"""
    _check_date(trade_date)
    try:
        rows = conn.execute(
            """
            SELECT symbol, name, foreign_net, trust_net, dealer_net, total_net
            FROM eod_institution_flows
            WHERE trade_date = ?
            ORDER BY ABS(total_net) DESC
            """,
            (trade_date,),
        ).fetchall()
    except sqlite3.OperationalError:
        raise HTTPException(status_code=503, detail="eod_institution_flows 表尚未建立")

    if not rows:
        raise HTTPException(status_code=404, detail=f"{trade_date} 無法人流向資料")

    return {"trade_date": trade_date, "data": _rows_to_list(rows)}


@router.get("/{trade_date}/margin")
def get_margin_data(
    trade_date: str,
    conn: sqlite3.Connection = Depends(conn_dep),
):
    """融資借券餘額，依 margin_balance 降序排列。"""
    _check_date(trade_date)
    try:
        rows = conn.execute(
            """
            SELECT symbol, name, margin_balance, short_balance
            FROM eod_margin_data
            WHERE trade_date = ?
            ORDER BY margin_balance DESC NULLS LAST
            """,
            (trade_date,),
        ).fetchall()
    except sqlite3.OperationalError:
        raise HTTPException(status_code=503, detail="eod_margin_data 表尚未建立")

    if not rows:
        raise HTTPException(status_code=404, detail=f"{trade_date} 無融資借券資料")

    return {"trade_date": trade_date, "data": _rows_to_list(rows)}


@router.get("/{trade_date}/summary")
def get_chips_summary(
    trade_date: str,
    symbol: Optional[str] = Query(None, description="單一股票代號（如 2330）"),
    conn: sqlite3.Connection = Depends(conn_dep),
):
    """
    依 symbol 合併法人流向 + 融資借券。
    傳入 ?symbol=XXXX 則只回傳該股票一筆資料。
    左連接：以 institution_flows 為基礎，補上 margin 資料（可能為 null）。
    """
    _check_date(trade_date)
    sym_filter = "AND f.symbol = ?" if symbol else ""
    params: list = [trade_date] + ([symbol.upper()] if symbol else [])
    try:
        rows = conn.execute(
            f"""
            SELECT
                f.symbol, f.name,
                f.foreign_net, f.trust_net, f.dealer_net, f.total_net,
                m.margin_balance, m.short_balance
            FROM eod_institution_flows f
            LEFT JOIN eod_margin_data m
                ON f.trade_date = m.trade_date AND f.symbol = m.symbol
            WHERE f.trade_date = ? {sym_filter}
            ORDER BY ABS(f.total_net) DESC
            """,
            params,
        ).fetchall()
    except sqlite3.OperationalError:
        raise HTTPException(status_code=503, detail="籌碼資料表尚未建立")

    if not rows:
        raise HTTPException(status_code=404, detail=f"{trade_date} 無籌碼摘要資料")

    return {"trade_date": trade_date, "data": _rows_to_list(rows)}


@router.get("/dates")
def get_available_dates(conn: sqlite3.Connection = Depends(conn_dep)):
    """回傳有法人資料的交易日列表（最近 30 天）。"""
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT trade_date
            FROM eod_institution_flows
            ORDER BY trade_date DESC
            LIMIT 30
            """,
        ).fetchall()
    except sqlite3.OperationalError:
        return {"dates": []}

    return {"dates": [r["trade_date"] for r in rows]}
