"""research.py — Stock Research API Router

Endpoints:
  GET /api/research/stocks               — latest report per symbol (paginated)
  GET /api/research/stocks/{symbol}      — full report for a symbol
  GET /api/research/stocks/{symbol}/history — historical reports (paginated)
  GET /api/research/debate/{symbol}      — latest debate record for a symbol
  GET /api/research/watchlist            — watchlist from config/watchlist.json
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

import app.db as db
from app.core.cache import cached
from app.core.response import api_response

router = APIRouter(prefix="/api/research", tags=["research"])

# ---------------------------------------------------------------------------
# Config path — resolved relative to the backend root
# ---------------------------------------------------------------------------

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
_WATCHLIST_PATH = (_BACKEND_ROOT / ".." / ".." / "config" / "watchlist.json").resolve()

# ---------------------------------------------------------------------------
# JSON fields that should be parsed from TEXT → dict/list
# ---------------------------------------------------------------------------

_RESEARCH_JSON_FIELDS = (
    "technical_json",
    "institutional_json",
    "llm_synthesis_json",
)

_DEBATE_JSON_FIELDS = (
    "bull_thesis_json",
    "bear_thesis_json",
    "arbiter_decision_json",
)

# ---------------------------------------------------------------------------
# DB dependency
# ---------------------------------------------------------------------------


def _conn_dep():
    try:
        with db.get_conn() as conn:
            yield conn
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_json_fields(row: Dict[str, Any], fields: tuple) -> Dict[str, Any]:
    """Deserialise known JSON TEXT columns in-place."""
    for field in fields:
        val = row.get(field)
        if isinstance(val, str):
            try:
                row[field] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
    return row


def _validate_symbol(symbol: str) -> str:
    """Basic symbol validation — alphanumeric + dot/dash only."""
    cleaned = symbol.upper().strip()
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_")
    if not cleaned or not all(c in allowed for c in cleaned):
        raise HTTPException(status_code=422, detail=f"Invalid symbol: {symbol!r}")
    return cleaned


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/stocks")
@cached(ttl=300, maxsize=64)
def list_stocks(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(50, ge=1, le=200, description="Records per page"),
    conn: sqlite3.Connection = Depends(_conn_dep),
):
    """Latest research report for each symbol, ordered by trade_date DESC."""
    offset = (page - 1) * per_page
    try:
        total_row = conn.execute(
            """
            SELECT COUNT(DISTINCT symbol) AS cnt
            FROM stock_research_reports
            """
        ).fetchone()
        total: int = total_row["cnt"] if total_row else 0

        rows = conn.execute(
            """
            SELECT symbol, rating, confidence, entry_price, stop_loss,
                   target_price, trade_date
            FROM stock_research_reports
            WHERE (symbol, trade_date) IN (
                SELECT symbol, MAX(trade_date)
                FROM stock_research_reports
                GROUP BY symbol
            )
            ORDER BY trade_date DESC, symbol
            LIMIT ? OFFSET ?
            """,
            (per_page, offset),
        ).fetchall()
    except sqlite3.OperationalError:
        raise HTTPException(status_code=503, detail="stock_research_reports 表尚未建立")

    data: List[Dict[str, Any]] = [dict(r) for r in rows]
    return api_response(
        data,
        total=total,
        page=page,
        per_page=per_page,
        source="sqlite",
    )


@router.get("/stocks/{symbol}")
def get_stock_report(
    symbol: str,
    conn: sqlite3.Connection = Depends(_conn_dep),
):
    """Full research report for a symbol (most recent).

    Includes technical_json, institutional_json, llm_synthesis_json,
    report_markdown, and fundamental data from eod_prices if available.
    """
    sym = _validate_symbol(symbol)
    try:
        row = conn.execute(
            """
            SELECT *
            FROM stock_research_reports
            WHERE symbol = ?
            ORDER BY trade_date DESC
            LIMIT 1
            """,
            (sym,),
        ).fetchone()
    except sqlite3.OperationalError:
        raise HTTPException(status_code=503, detail="stock_research_reports 表尚未建立")

    if row is None:
        raise HTTPException(status_code=404, detail=f"No research report for {sym}")

    data = _parse_json_fields(dict(row), _RESEARCH_JSON_FIELDS)

    # Augment with latest fundamental data from eod_prices if available
    try:
        price_row = conn.execute(
            """
            SELECT close, trade_date AS price_date
            FROM eod_prices
            WHERE symbol = ?
            ORDER BY trade_date DESC
            LIMIT 1
            """,
            (sym,),
        ).fetchone()
        if price_row:
            data["latest_close"] = price_row["close"]
            data["price_date"] = price_row["price_date"]
            # Compute a simple P/E if eps is available on the report row
            eps = data.get("eps")
            if eps and eps != 0 and price_row["close"]:
                data["pe_ratio"] = round(price_row["close"] / eps, 2)
            # Dividend yield: annual_dividend / close
            annual_dividend = data.get("annual_dividend")
            if annual_dividend and price_row["close"]:
                data["dividend_yield"] = round(annual_dividend / price_row["close"], 4)
    except sqlite3.OperationalError:
        pass  # eod_prices missing — skip fundamentals silently

    return api_response(data, source="sqlite")


@router.get("/stocks/{symbol}/history")
def get_stock_history(
    symbol: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    conn: sqlite3.Connection = Depends(_conn_dep),
):
    """Historical research reports for a symbol, newest first."""
    sym = _validate_symbol(symbol)
    offset = (page - 1) * per_page
    try:
        total_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM stock_research_reports WHERE symbol = ?",
            (sym,),
        ).fetchone()
        total = total_row["cnt"] if total_row else 0

        rows = conn.execute(
            """
            SELECT symbol, rating, confidence, entry_price, stop_loss,
                   target_price, trade_date, report_markdown
            FROM stock_research_reports
            WHERE symbol = ?
            ORDER BY trade_date DESC
            LIMIT ? OFFSET ?
            """,
            (sym, per_page, offset),
        ).fetchall()
    except sqlite3.OperationalError:
        raise HTTPException(status_code=503, detail="stock_research_reports 表尚未建立")

    if total == 0:
        raise HTTPException(status_code=404, detail=f"No history found for {sym}")

    data = [dict(r) for r in rows]
    return api_response(
        data,
        total=total,
        page=page,
        per_page=per_page,
        source="sqlite",
    )


@router.get("/debate/{symbol}")
def get_debate(
    symbol: str,
    conn: sqlite3.Connection = Depends(_conn_dep),
):
    """Latest debate record for a symbol."""
    sym = _validate_symbol(symbol)
    try:
        row = conn.execute(
            """
            SELECT bull_thesis_json, bear_thesis_json, arbiter_decision_json,
                   recommendation, confidence, trade_date, symbol
            FROM debate_records
            WHERE symbol = ?
            ORDER BY trade_date DESC
            LIMIT 1
            """,
            (sym,),
        ).fetchone()
    except sqlite3.OperationalError:
        raise HTTPException(status_code=503, detail="debate_records 表尚未建立")

    if row is None:
        raise HTTPException(status_code=404, detail=f"No debate record for {sym}")

    data = _parse_json_fields(dict(row), _DEBATE_JSON_FIELDS)
    return api_response(data, source="sqlite")


@router.get("/watchlist")
@cached(ttl=300, maxsize=4)
def get_watchlist():
    """Return the manual watchlist from config/watchlist.json."""
    if not _WATCHLIST_PATH.exists():
        raise HTTPException(status_code=503, detail=f"watchlist.json not found at {_WATCHLIST_PATH}")
    try:
        payload = json.loads(_WATCHLIST_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read watchlist: {exc}")

    return api_response(payload, source="config")
