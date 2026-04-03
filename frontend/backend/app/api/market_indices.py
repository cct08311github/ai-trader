"""market_indices.py — FastAPI router for market index data from research.db.

Endpoints:
  GET /api/indices/latest           — all latest index values (cached 60 s)
  GET /api/indices/latest?symbols=  — filtered by comma-separated symbols
  GET /api/indices/history          — historical data for one index
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.cache import cached
from app.core.response import api_response
from app.db.research_db import RESEARCH_DB_PATH, connect_research, init_research_db

router = APIRouter(prefix="/api/indices", tags=["market-indices"])


# ---------------------------------------------------------------------------
# Dependency: read-only connection to research.db
# ---------------------------------------------------------------------------

def _research_conn_dep():
    """FastAPI dependency that yields a research.db connection."""
    try:
        init_research_db()           # no-op if schema already exists
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
# Cache helpers
# ---------------------------------------------------------------------------

@cached(ttl=60, maxsize=16)
def _latest_cached(symbols_key: str) -> list:
    """Fetch latest market_indices rows, cached for 60 seconds.

    Args:
        symbols_key: Comma-joined sorted symbol string, or '' for all.
    """
    conn = connect_research(RESEARCH_DB_PATH)
    try:
        if symbols_key:
            symbols = [s.strip() for s in symbols_key.split(",") if s.strip()]
            placeholders = ",".join("?" * len(symbols))
            sql = f"""
                SELECT m.*
                FROM market_indices m
                INNER JOIN (
                    SELECT symbol, MAX(trade_date) AS max_date
                    FROM market_indices
                    WHERE symbol IN ({placeholders})
                    GROUP BY symbol
                ) latest ON m.symbol = latest.symbol AND m.trade_date = latest.max_date
                ORDER BY m.symbol
            """
            rows = conn.execute(sql, symbols).fetchall()
        else:
            sql = """
                SELECT m.*
                FROM market_indices m
                INNER JOIN (
                    SELECT symbol, MAX(trade_date) AS max_date
                    FROM market_indices
                    GROUP BY symbol
                ) latest ON m.symbol = latest.symbol AND m.trade_date = latest.max_date
                ORDER BY m.symbol
            """
            rows = conn.execute(sql).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/latest")
def get_latest_indices(
    symbols: Optional[str] = Query(
        default=None,
        description="Comma-separated list of symbols, e.g. ^GSPC,^VIX. Omit for all.",
        examples=["^GSPC,^VIX"],
    ),
):
    """Return the most-recent snapshot for each index.

    Cached with a 60-second TTL to reduce SQLite load.
    """
    symbols_key = ",".join(sorted(s.strip() for s in symbols.split(",") if s.strip())) if symbols else ""
    rows = _latest_cached(symbols_key)
    return api_response(
        rows,
        total=len(rows),
        source="research.db/market_indices",
        cache_hit=True,
    )


@router.get("/history")
def get_index_history(
    index: str = Query(..., description="Ticker symbol, e.g. ^TWII"),
    days: int = Query(default=30, ge=1, le=365, description="Number of calendar days to look back"),
    conn: sqlite3.Connection = Depends(_research_conn_dep),
):
    """Return daily historical rows for a single index.

    Args:
        index: Ticker symbol (required).
        days:  Calendar days to look back (1–365, default 30).
    """
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """
        SELECT *
        FROM market_indices
        WHERE symbol = ? AND trade_date >= ?
        ORDER BY trade_date ASC
        """,
        (index, since),
    ).fetchall()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No data found for symbol '{index}' in the last {days} days.",
        )

    data = [dict(r) for r in rows]
    return api_response(
        data,
        total=len(data),
        source="research.db/market_indices",
        freshness=data[-1]["trade_date"] if data else None,
    )
