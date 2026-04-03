"""macro_data_fetcher.py — Fetch macro-economic indicators from FRED API and store to research.db.

FRED Series fetched:
  GDP Growth   (A191RL1Q225SBEA) — quarterly
  CPI          (CPIAUCSL)        — monthly
  Core PCE     (PCEPILFE)        — monthly
  Fed Funds    (FEDFUNDS)        — monthly
  Unemployment (UNRATE)          — monthly
  ISM PMI      (MANBUSINDX)      — monthly
  10Y Treasury (DGS10)           — daily
  2Y Treasury  (DGS2)            — daily
  DXY          (DTWEXBGS)        — daily

Derived:
  10Y-2Y Spread (SPREAD_10Y_2Y) — computed locally, not fetched from FRED

Requires FRED_API_KEY environment variable (free at https://fred.stlouisfed.org/docs/api/).
Missing key → warning logged, fetcher skips gracefully.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

FRED_SERIES: List[Dict[str, str]] = [
    {
        "indicator_id":   "A191RL1Q225SBEA",
        "indicator_name": "Real GDP Growth (QoQ, annualised)",
        "unit":           "percent",
        "frequency":      "quarterly",
        "country":        "US",
    },
    {
        "indicator_id":   "CPIAUCSL",
        "indicator_name": "CPI (All Urban Consumers)",
        "unit":           "index_1982_84_100",
        "frequency":      "monthly",
        "country":        "US",
    },
    {
        "indicator_id":   "PCEPILFE",
        "indicator_name": "Core PCE Price Index",
        "unit":           "index_2017_100",
        "frequency":      "monthly",
        "country":        "US",
    },
    {
        "indicator_id":   "FEDFUNDS",
        "indicator_name": "Fed Funds Rate",
        "unit":           "percent",
        "frequency":      "monthly",
        "country":        "US",
    },
    {
        "indicator_id":   "UNRATE",
        "indicator_name": "Unemployment Rate",
        "unit":           "percent",
        "frequency":      "monthly",
        "country":        "US",
    },
    {
        "indicator_id":   "MANBUSINDX",
        "indicator_name": "ISM Manufacturing PMI",
        "unit":           "index",
        "frequency":      "monthly",
        "country":        "US",
    },
    {
        "indicator_id":   "DGS10",
        "indicator_name": "10-Year Treasury Yield",
        "unit":           "percent",
        "frequency":      "daily",
        "country":        "US",
    },
    {
        "indicator_id":   "DGS2",
        "indicator_name": "2-Year Treasury Yield",
        "unit":           "percent",
        "frequency":      "daily",
        "country":        "US",
    },
    {
        "indicator_id":   "DTWEXBGS",
        "indicator_name": "US Dollar Index (DXY)",
        "unit":           "index_jan2006_100",
        "frequency":      "daily",
        "country":        "US",
    },
]

_RATE_LIMIT_SECONDS = 0.5  # 0.5 s between FRED API calls


# ---------------------------------------------------------------------------
# FRED fetch helpers
# ---------------------------------------------------------------------------

def _get_fred_api_key() -> Optional[str]:
    key = os.environ.get("FRED_API_KEY", "").strip()
    return key if key else None


def _fetch_series(fred, series_id: str, limit: int = 200) -> List[Tuple[str, float]]:
    """Fetch the most-recent `limit` observations for a FRED series.

    Returns list of (date_str, value) tuples, sorted oldest→newest.
    NaN values are dropped.
    """
    try:
        obs = fred.get_series(series_id)
        if obs is None or obs.empty:
            logger.warning("FRED: No data for %s", series_id)
            return []

        # Drop NaN, take the most-recent `limit` points
        obs = obs.dropna().tail(limit)
        result = []
        for idx, val in obs.items():
            date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
            result.append((date_str, float(val)))
        return result

    except Exception as exc:
        logger.error("FRED fetch failed for %s: %s", series_id, exc)
        return []


# ---------------------------------------------------------------------------
# Derived indicators
# ---------------------------------------------------------------------------

def _compute_yield_spread(
    rows_10y: List[Tuple[str, float]],
    rows_2y: List[Tuple[str, float]],
) -> List[Dict[str, Any]]:
    """Compute 10Y-2Y spread.  Returns list of rows for macro_indicators."""
    map_2y = {date: val for date, val in rows_2y}
    map_10y = {date: val for date, val in rows_10y}

    common_dates = sorted(set(map_10y) & set(map_2y))
    derived = []
    for date in common_dates:
        spread = round(map_10y[date] - map_2y[date], 4)
        derived.append({
            "indicator_id":   "SPREAD_10Y_2Y",
            "indicator_name": "10Y-2Y Treasury Spread",
            "date":           date,
            "value":          spread,
            "unit":           "percent",
            "frequency":      "daily",
            "source":         "derived",
            "country":        "US",
        })
    return derived


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _store_rows(conn: sqlite3.Connection, rows: List[Dict[str, Any]]) -> int:
    """UPSERT macro_indicators rows.  Returns number of rows inserted/updated."""
    if not rows:
        return 0

    now_ts = int(datetime.now(tz=timezone.utc).timestamp())

    sql = """
        INSERT INTO macro_indicators
            (indicator_id, date, value, unit, source, country, created_at)
        VALUES
            (:indicator_id, :date, :value, :unit, :source, :country, :created_at)
        ON CONFLICT(indicator_id, date) DO UPDATE SET
            value      = excluded.value,
            unit       = excluded.unit,
            source     = excluded.source,
            country    = excluded.country,
            created_at = excluded.created_at
    """

    prepared = [
        {
            "indicator_id": r["indicator_id"],
            "date":         r["date"],
            "value":        r["value"],
            "unit":         r.get("unit"),
            "source":       r.get("source", "fred"),
            "country":      r.get("country", "US"),
            "created_at":   now_ts,
        }
        for r in rows
    ]

    conn.executemany(sql, prepared)
    conn.commit()
    logger.info("Stored %d macro_indicator rows.", len(prepared))
    return len(prepared)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_macro_fetcher(db_path: Optional[str] = None) -> None:
    """Fetch all FRED indicators and store them to research.db.

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

    api_key = _get_fred_api_key()
    if not api_key:
        logger.warning(
            "FRED_API_KEY not set — macro indicator fetch skipped. "
            "Register for a free key at https://fred.stlouisfed.org/docs/api/"
        )
        return

    try:
        from fredapi import Fred  # noqa: PLC0415
    except ImportError:
        logger.error("fredapi not installed — run: pip install fredapi")
        return

    fred = Fred(api_key=api_key)

    target = Path(db_path) if db_path else RESEARCH_DB_PATH
    init_research_db(target)
    conn = connect_research(target)

    try:
        all_rows: List[Dict[str, Any]] = []

        # Track 10Y and 2Y raw observations for spread computation
        raw_10y: List[Tuple[str, float]] = []
        raw_2y: List[Tuple[str, float]] = []

        for series_meta in FRED_SERIES:
            sid = series_meta["indicator_id"]
            logger.info("Fetching FRED series: %s (%s)", sid, series_meta["indicator_name"])
            observations = _fetch_series(fred, sid)

            if observations:
                for date_str, value in observations:
                    all_rows.append({
                        "indicator_id":   sid,
                        "indicator_name": series_meta["indicator_name"],
                        "date":           date_str,
                        "value":          value,
                        "unit":           series_meta.get("unit"),
                        "frequency":      series_meta.get("frequency", "monthly"),
                        "source":         "fred",
                        "country":        series_meta.get("country", "US"),
                    })

                if sid == "DGS10":
                    raw_10y = observations
                elif sid == "DGS2":
                    raw_2y = observations

            else:
                logger.warning("No observations returned for %s — skipping.", sid)

            time.sleep(_RATE_LIMIT_SECONDS)

        # Compute and append derived spread
        if raw_10y and raw_2y:
            spread_rows = _compute_yield_spread(raw_10y, raw_2y)
            all_rows.extend(spread_rows)
            logger.info("Computed %d yield-spread rows.", len(spread_rows))

        stored = _store_rows(conn, all_rows)
        logger.info(
            "run_macro_fetcher complete: %d total rows stored to %s", stored, target
        )

    finally:
        conn.close()


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    )
    db_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run_macro_fetcher(db_arg)
