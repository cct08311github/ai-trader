"""sector.py — 產業分析 API Router

Endpoints:
  GET /api/sector/overview       — 所有產業最新數據（cached 300 s）
  GET /api/sector/flow           — 法人資金流向 BarChart 數據
  GET /api/sector/{code}/detail  — 單一產業詳情 + 股票清單
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.core.cache import cached
from app.core.response import api_response
from app.db.research_db import RESEARCH_DB_PATH, connect_research, init_research_db

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sector", tags=["sector"])


# ---------------------------------------------------------------------------
# DB dependency
# ---------------------------------------------------------------------------

def _research_conn_dep():
    """FastAPI dependency：research.db read-write connection。"""
    try:
        init_research_db()
        conn = connect_research()
        try:
            yield conn
        finally:
            conn.close()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"research.db error: {exc}") from exc


# ---------------------------------------------------------------------------
# Cached helpers（避免每次請求重複查 DB）
# ---------------------------------------------------------------------------

@cached(ttl=300, maxsize=4)
def _load_sector_overview(db_path_str: str) -> List[Dict[str, Any]]:
    """讀取最新日期各產業數據。Cached 300 s。"""
    conn = connect_research(RESEARCH_DB_PATH)
    try:
        # 取最新 trade_date
        row = conn.execute(
            "SELECT MAX(trade_date) AS d FROM sector_data"
        ).fetchone()
        if not row or not row["d"]:
            return []
        latest = row["d"]

        rows = conn.execute(
            """
            SELECT
                trade_date, sector_code, sector_name,
                market_cap, turnover, change_pct,
                fund_flow_net, fund_flow_foreign, fund_flow_trust,
                pe_ratio, stock_count, source
            FROM sector_data
            WHERE trade_date = ?
            ORDER BY COALESCE(market_cap, 0) DESC
            """,
            (latest,),
        ).fetchall()

        return [dict(r) for r in rows]
    finally:
        conn.close()


@cached(ttl=300, maxsize=4)
def _load_fund_flow(db_path_str: str, days: int) -> List[Dict[str, Any]]:
    """讀取近 N 日各產業法人流向（外資 + 投信分開）。Cached 300 s。"""
    conn = connect_research(RESEARCH_DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT
                trade_date,
                sector_name,
                sector_code,
                fund_flow_foreign,
                fund_flow_trust,
                fund_flow_net
            FROM sector_data
            WHERE trade_date >= date('now', ? || ' days')
            ORDER BY trade_date ASC, COALESCE(ABS(fund_flow_net), 0) DESC
            """,
            (f"-{days}",),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/overview")
def get_sector_overview(
    conn: sqlite3.Connection = Depends(_research_conn_dep),
):
    """所有產業最新日期數據，依市值降序排列。

    回傳：trade_date, sector_code, sector_name, market_cap, turnover,
          change_pct, fund_flow_net, fund_flow_foreign, fund_flow_trust,
          pe_ratio, stock_count
    """
    db_path_str = str(RESEARCH_DB_PATH)
    try:
        data = _load_sector_overview(db_path_str)
    except Exception as e:
        log.error("[sector] overview error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Service temporarily unavailable")

    return api_response(
        data,
        total=len(data),
        source="research.db/sector_data",
        cache_hit=True,
    )


@router.get("/flow")
def get_sector_flow(
    days: int = Query(default=5, ge=1, le=30, description="回溯天數"),
    conn: sqlite3.Connection = Depends(_research_conn_dep),
):
    """法人資金流向，回傳適合 BarChart 的格式。

    每筆包含：trade_date, sector_name, fund_flow_foreign（外資，blue）,
    fund_flow_trust（投信，orange）, fund_flow_net
    """
    db_path_str = str(RESEARCH_DB_PATH)
    try:
        data = _load_fund_flow(db_path_str, days)
    except Exception as e:
        log.error("[sector] flow error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Service temporarily unavailable")

    return api_response(
        data,
        total=len(data),
        days=days,
        source="research.db/sector_data",
        cache_hit=True,
    )


@router.get("/{code}/detail")
def get_sector_detail(
    code: str = Path(description="產業代碼（sector_code）"),
    conn: sqlite3.Connection = Depends(_research_conn_dep),
):
    """單一產業詳情：最新數據 + 該產業的股票清單（從 sector_mapping）。

    stock_list 欄位：包含 symbol, sub_sector（如有）
    """
    try:
        # 最新日期數據
        date_row = conn.execute(
            "SELECT MAX(trade_date) AS d FROM sector_data WHERE sector_code = ?",
            (code,),
        ).fetchone()
        if not date_row or not date_row["d"]:
            raise HTTPException(status_code=404, detail=f"Sector '{code}' not found")

        latest = date_row["d"]

        sector_row = conn.execute(
            """
            SELECT *
            FROM sector_data
            WHERE trade_date = ? AND sector_code = ?
            """,
            (latest, code),
        ).fetchone()

        if not sector_row:
            raise HTTPException(status_code=404, detail=f"Sector '{code}' not found")

        sector_dict = dict(sector_row)

        # 股票清單
        stock_rows = conn.execute(
            """
            SELECT symbol, sub_sector
            FROM sector_mapping
            WHERE sector_code = ?
            ORDER BY symbol
            """,
            (code,),
        ).fetchall()

        sector_dict["stock_list"] = [dict(r) for r in stock_rows]

    except HTTPException:
        raise
    except Exception as e:
        log.error("[sector] detail error for %s: %s", code, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Service temporarily unavailable")

    return api_response(sector_dict, source="research.db/sector_data+sector_mapping")
