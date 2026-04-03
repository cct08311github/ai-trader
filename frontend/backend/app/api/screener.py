"""screener.py — Market Screener API Router

Endpoints:
  GET /api/screener/candidates   — paginated system_candidates from trades.db
  GET /api/screener/scatter      — scatter plot data per candidate (RSI14, volume_ratio,
                                   foreign_consecutive, change_5d, score, sector)
                                   Cached 300 s.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

log = logging.getLogger(__name__)

import app.db as db
from app.core.cache import cached
from app.core.response import api_response
from openclaw.stock_screener import load_system_candidates_full

router = APIRouter(prefix="/api/screener", tags=["screener"])


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


def _round2(v: Optional[float]) -> Optional[float]:
    return round(v, 2) if v is not None else None


def _compute_rsi14(closes: List[float]) -> Optional[float]:
    """Compute RSI-14 from a chronological list of close prices."""
    try:
        from openclaw.technical_indicators import calc_rsi
        rsi_vals = calc_rsi(closes, 14)
        for v in reversed(rsi_vals):
            if v is not None:
                return round(v, 2)
    except (ImportError, Exception):
        pass
    return None


def _compute_volume_ratio(volumes: List[int]) -> Optional[float]:
    """Compute today / 5-day-avg volume ratio. Expects volumes in chronological order."""
    if len(volumes) < 6:
        return None
    avg5 = sum(volumes[-6:-1]) / 5
    if avg5 <= 0:
        return None
    return round(volumes[-1] / avg5, 2)


def _compute_change_5d(closes: List[float]) -> Optional[float]:
    """5-day price change percent."""
    if len(closes) < 6:
        return None
    prev = closes[-6]
    curr = closes[-1]
    if prev == 0:
        return None
    return round((curr - prev) / prev * 100, 2)


def _compute_foreign_consecutive(conn: sqlite3.Connection, symbol: str, latest_date: str) -> int:
    """Count consecutive days foreign_net > 0 ending at latest_date."""
    rows = conn.execute(
        "SELECT foreign_net FROM eod_institution_flows "
        "WHERE symbol = ? AND trade_date <= ? "
        "ORDER BY trade_date DESC LIMIT 20",
        (symbol, latest_date),
    ).fetchall()
    count = 0
    for r in rows:
        val = r["foreign_net"] if isinstance(r, sqlite3.Row) else r[0]
        if (val or 0) > 0:
            count += 1
        else:
            break
    return count


def _get_latest_trade_date(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute("SELECT MAX(trade_date) AS d FROM eod_prices").fetchone()
    if row:
        return row["d"] if isinstance(row, sqlite3.Row) else row[0]
    return None


# ---------------------------------------------------------------------------
# Cached scatter builder
# ---------------------------------------------------------------------------


@cached(ttl=300, maxsize=8)
def _build_scatter_data(db_path_str: str) -> List[Dict[str, Any]]:
    """Compute scatter-plot metrics for all unexpired system_candidates.

    Cached for 300 s to avoid repeated SQLite reads per request.
    """
    import sqlite3 as _sqlite3
    conn = _sqlite3.connect(f"file:{db_path_str}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = _sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = ON;")
    except _sqlite3.DatabaseError:
        pass

    try:
        candidates = load_system_candidates_full(conn)
    except Exception:
        conn.close()
        return []

    if not candidates:
        conn.close()
        return []

    latest_date = _get_latest_trade_date(conn)
    if not latest_date:
        conn.close()
        return []

    result: List[Dict[str, Any]] = []

    for c in candidates:
        symbol = c["symbol"]
        try:
            # Closes for RSI + change_5d
            close_rows = conn.execute(
                "SELECT close FROM eod_prices "
                "WHERE symbol = ? AND trade_date <= ? "
                "ORDER BY trade_date DESC LIMIT 60",
                (symbol, latest_date),
            ).fetchall()
            closes = [float(r["close"]) for r in reversed(close_rows)]

            # Volumes for volume_ratio
            vol_rows = conn.execute(
                "SELECT volume FROM eod_prices "
                "WHERE symbol = ? AND trade_date <= ? "
                "ORDER BY trade_date DESC LIMIT 10",
                (symbol, latest_date),
            ).fetchall()
            volumes = [int(r["volume"]) for r in reversed(vol_rows)]

            # Name + sector from latest eod_prices row
            meta_row = conn.execute(
                "SELECT name FROM eod_prices "
                "WHERE symbol = ? AND trade_date <= ? "
                "ORDER BY trade_date DESC LIMIT 1",
                (symbol, latest_date),
            ).fetchone()
            name = meta_row["name"] if meta_row else symbol

            # Sector — from positions if available, fallback null
            sector_row = conn.execute(
                "SELECT sector FROM positions WHERE symbol = ? LIMIT 1",
                (symbol,),
            ).fetchone()
            sector: Optional[str] = None
            if sector_row:
                sector = sector_row["sector"] if isinstance(sector_row, sqlite3.Row) else sector_row[0]

            foreign_consecutive = _compute_foreign_consecutive(conn, symbol, latest_date)

            result.append({
                "symbol": symbol,
                "name": name or symbol,
                "rsi14": _compute_rsi14(closes),
                "volume_ratio": _compute_volume_ratio(volumes),
                "foreign_consecutive": foreign_consecutive,
                "change_5d": _compute_change_5d(closes),
                "score": c["score"],
                "label": c["label"],
                "sector": sector,
                "reasons": c.get("reasons", []),
            })
        except Exception as e:
            # Skip symbols with broken data rather than failing the whole endpoint
            log.warning("Skipping %s: %s", symbol, e)
            continue

    conn.close()
    return result


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/candidates")
def get_candidates(
    page: int = Query(default=1, ge=1, description="1-indexed page number"),
    per_page: int = Query(default=50, ge=1, le=200, description="Records per page"),
    label: Optional[str] = Query(default=None, description="Filter by label: short_term | long_term"),
    conn: sqlite3.Connection = Depends(_conn_dep),
):
    """Return paginated system_candidates (unexpired, sorted by score desc).

    Optionally filter by ``label=short_term`` or ``label=long_term``.
    """
    try:
        candidates = load_system_candidates_full(conn)
    except Exception as e:
        log.error("screener candidates error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Service temporarily unavailable")

    if label:
        candidates = [c for c in candidates if c.get("label") == label]

    total = len(candidates)
    offset = (page - 1) * per_page
    page_data = candidates[offset: offset + per_page]

    return api_response(
        page_data,
        total=total,
        page=page,
        per_page=per_page,
        source="sqlite/system_candidates",
        cache_hit=False,
    )


@router.get("/scatter")
def get_scatter(
    conn: sqlite3.Connection = Depends(_conn_dep),
):
    """Return scatter-plot data for all unexpired system_candidates.

    Each item contains: symbol, name, rsi14, volume_ratio, foreign_consecutive,
    change_5d, score, label, sector, reasons.

    Result is cached for 300 s (TTL).
    """
    db_path_str = str(db.DB_PATH)
    try:
        data = _build_scatter_data(db_path_str)
    except Exception as e:
        log.error("screener scatter error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Service temporarily unavailable")

    return api_response(
        data,
        total=len(data),
        source="sqlite/system_candidates+eod_prices",
        cache_hit=True,
    )
