"""market_index_fetcher.py — Fetch global market indices via yfinance and store to research.db.

Supported indices:
  TAIEX (^TWII), S&P500 (^GSPC), NASDAQ (^IXIC), SOX (^SOX), VIX (^VIX),
  DXY (DX-Y.NYB), Nikkei (^N225), HSI (^HSI), Gold (GC=F), Oil (CL=F),
  10Y Treasury (^TNX), USD/TWD (USDTWD=X), Bitcoin (BTC-USD), KOSPI (^KS11)
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import yfinance as yf

from openclaw.path_utils import get_repo_root

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Index registry
# ---------------------------------------------------------------------------

INDICES: List[Dict[str, str]] = [
    {"symbol": "^TWII",     "name": "TAIEX"},
    {"symbol": "^GSPC",     "name": "S&P 500"},
    {"symbol": "^IXIC",     "name": "NASDAQ"},
    {"symbol": "^SOX",      "name": "Philadelphia SOX"},
    {"symbol": "^VIX",      "name": "VIX"},
    {"symbol": "DX-Y.NYB",  "name": "DXY"},
    {"symbol": "^N225",     "name": "Nikkei 225"},
    {"symbol": "^HSI",      "name": "Hang Seng"},
    {"symbol": "GC=F",      "name": "Gold"},
    {"symbol": "CL=F",      "name": "Crude Oil (WTI)"},
    {"symbol": "^TNX",      "name": "10Y Treasury"},
    {"symbol": "USDTWD=X",  "name": "USD/TWD"},
    {"symbol": "BTC-USD",   "name": "Bitcoin"},
    {"symbol": "^KS11",     "name": "KOSPI"},
]

_RESEARCH_DB: str = str(get_repo_root() / "data" / "sqlite" / "research.db")


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def _fetch_ticker(symbol: str, name: str) -> Optional[Dict[str, Any]]:
    """Fetch latest quote for a single symbol. Returns None on failure."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="2d", auto_adjust=True)

        if hist.empty:
            logger.warning("No data for %s", symbol)
            return None

        latest = hist.iloc[-1]
        trade_date = str(hist.index[-1].date()) if hasattr(hist.index[-1], "date") else str(date.today())

        close_price = float(latest["Close"])
        open_price  = float(latest["Open"])  if "Open"   in latest else None
        high_price  = float(latest["High"])  if "High"   in latest else None
        low_price   = float(latest["Low"])   if "Low"    in latest else None
        volume      = int(latest["Volume"])  if "Volume" in latest and latest["Volume"] is not None else None

        # Change % — compare to previous day if available, else None
        change_pct: Optional[float] = None
        if len(hist) >= 2:
            prev_close = float(hist.iloc[-2]["Close"])
            if prev_close and prev_close != 0:
                change_pct = round((close_price - prev_close) / prev_close * 100, 4)

        return {
            "symbol":      symbol,
            "name":        name,
            "close_price": close_price,
            "open_price":  open_price,
            "high_price":  high_price,
            "low_price":   low_price,
            "volume":      volume,
            "change_pct":  change_pct,
            "trade_date":  trade_date,
            "source":      "yfinance",
        }

    except Exception as exc:
        logger.error("Failed to fetch %s (%s): %s", symbol, name, exc)
        return None


def fetch_all_indices() -> List[Dict[str, Any]]:
    """Fetch latest quotes for all configured indices.

    Returns:
        List of dicts — one per successfully fetched symbol.
    """
    results: List[Dict[str, Any]] = []
    for entry in INDICES:
        row = _fetch_ticker(entry["symbol"], entry["name"])
        if row:
            results.append(row)
            logger.info("Fetched %s: %.4f (%s%%)",
                        entry["symbol"], row["close_price"],
                        row["change_pct"] if row["change_pct"] is not None else "n/a")
        else:
            logger.warning("Skipped %s — no data returned.", entry["symbol"])
    return results


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def store_indices(conn: sqlite3.Connection, indices: List[Dict[str, Any]]) -> int:
    """UPSERT index rows into market_indices table in research.db.

    Args:
        conn:    Open writable sqlite3.Connection to research.db.
        indices: List of dicts as returned by fetch_all_indices().

    Returns:
        Number of rows inserted/replaced.
    """
    if not indices:
        logger.warning("store_indices called with empty list — nothing to write.")
        return 0

    sql = """
        INSERT INTO market_indices
            (symbol, name, close_price, open_price, high_price, low_price,
             volume, change_pct, trade_date, source, fetched_at)
        VALUES
            (:symbol, :name, :close_price, :open_price, :high_price, :low_price,
             :volume, :change_pct, :trade_date, :source, :fetched_at)
        ON CONFLICT(symbol, trade_date) DO UPDATE SET
            name        = excluded.name,
            close_price = excluded.close_price,
            open_price  = excluded.open_price,
            high_price  = excluded.high_price,
            low_price   = excluded.low_price,
            volume      = excluded.volume,
            change_pct  = excluded.change_pct,
            source      = excluded.source,
            fetched_at  = excluded.fetched_at
    """

    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = [{**r, "fetched_at": now} for r in indices]

    conn.executemany(sql, rows)
    conn.commit()
    logger.info("Stored %d index rows to research.db.", len(rows))
    return len(rows)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_market_index_fetcher(db_path: Optional[str] = None) -> None:
    """Fetch all indices and store them to research.db.

    Args:
        db_path: Optional override for research.db path.
                 Falls back to RESEARCH_DB_PATH from research_db module.
    """
    from frontend.backend.app.db.research_db import (  # noqa: PLC0415
        RESEARCH_DB_PATH,
        connect_research,
        init_research_db,
    )
    from pathlib import Path

    target = Path(db_path) if db_path else RESEARCH_DB_PATH

    # Ensure schema exists
    init_research_db(target)

    indices = fetch_all_indices()
    if not indices:
        logger.error("No indices fetched — nothing stored.")
        return

    conn = connect_research(target)
    try:
        stored = store_indices(conn, indices)
        logger.info("run_market_index_fetcher complete: %d indices stored to %s", stored, target)
    finally:
        conn.close()


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    )
    db_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run_market_index_fetcher(db_arg)
