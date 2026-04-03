"""macro.py — FastAPI router for macro-economic indicator data from research.db.

Endpoints:
  GET /api/macro/dashboard                        — latest KPI values for all indicators (cached 3600s)
  GET /api/macro/indicator/{indicator_id}/history — historical data points for one indicator
  GET /api/macro/calendar                         — upcoming economic calendar events
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date, timedelta
from typing import List, Optional

log = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException, Path, Query

from app.core.cache import cached
from app.core.response import api_response
from app.db.research_db import RESEARCH_DB_PATH, connect_research, init_research_db

router = APIRouter(prefix="/api/macro", tags=["macro"])

# ---------------------------------------------------------------------------
# Indicator metadata registry (human-readable labels, units, countries)
# ---------------------------------------------------------------------------

_INDICATOR_META = {
    "A191RL1Q225SBEA": {"name": "Real GDP Growth",          "unit": "percent",           "country": "US"},
    "CPIAUCSL":        {"name": "CPI (All Urban)",           "unit": "index_1982_84_100", "country": "US"},
    "PCEPILFE":        {"name": "Core PCE Price Index",      "unit": "index_2017_100",    "country": "US"},
    "FEDFUNDS":        {"name": "Fed Funds Rate",            "unit": "percent",           "country": "US"},
    "UNRATE":          {"name": "Unemployment Rate",         "unit": "percent",           "country": "US"},
    "MANBUSINDX":      {"name": "ISM Manufacturing PMI",     "unit": "index",             "country": "US"},
    "DGS10":           {"name": "10Y Treasury Yield",        "unit": "percent",           "country": "US"},
    "DGS2":            {"name": "2Y Treasury Yield",         "unit": "percent",           "country": "US"},
    "DTWEXBGS":        {"name": "US Dollar Index (DXY)",     "unit": "index_jan2006_100", "country": "US"},
    "SPREAD_10Y_2Y":   {"name": "10Y-2Y Treasury Spread",   "unit": "percent",           "country": "US"},
    # Taiwan placeholders (manual / future data sources)
    "TW_GDP":          {"name": "Taiwan GDP Growth",         "unit": "percent",           "country": "TW"},
    "TW_CPI":          {"name": "Taiwan CPI",                "unit": "percent",           "country": "TW"},
    "TW_UNRATE":       {"name": "Taiwan Unemployment Rate",  "unit": "percent",           "country": "TW"},
    "TW_EXPORT_YOY":   {"name": "Taiwan Export Orders YoY", "unit": "percent",           "country": "TW"},
    "TW_M1B":          {"name": "Taiwan M1B Money Supply",   "unit": "percent_yoy",       "country": "TW"},
    "TW_M2":           {"name": "Taiwan M2 Money Supply",    "unit": "percent_yoy",       "country": "TW"},
}

# ---------------------------------------------------------------------------
# Hardcoded economic calendar events
# ---------------------------------------------------------------------------

FIXED_EVENTS = [
    {
        "date":        "2026-04-08",
        "event":       "FOMC Meeting Minutes",
        "country":     "US",
        "importance":  "high",
        "indicator":   "FEDFUNDS",
    },
    {
        "date":        "2026-04-10",
        "event":       "CPI Release (Mar)",
        "country":     "US",
        "importance":  "high",
        "indicator":   "CPIAUCSL",
    },
    {
        "date":        "2026-04-16",
        "event":       "Core Retail Sales (Mar)",
        "country":     "US",
        "importance":  "medium",
        "indicator":   None,
    },
    {
        "date":        "2026-04-17",
        "event":       "Initial Jobless Claims",
        "country":     "US",
        "importance":  "medium",
        "indicator":   "UNRATE",
    },
    {
        "date":        "2026-04-24",
        "event":       "Core PCE Release (Mar)",
        "country":     "US",
        "importance":  "high",
        "indicator":   "PCEPILFE",
    },
    {
        "date":        "2026-04-30",
        "event":       "FOMC Rate Decision",
        "country":     "US",
        "importance":  "critical",
        "indicator":   "FEDFUNDS",
    },
    {
        "date":        "2026-05-02",
        "event":       "Non-Farm Payrolls (Apr)",
        "country":     "US",
        "importance":  "high",
        "indicator":   "UNRATE",
    },
    {
        "date":        "2026-05-12",
        "event":       "CPI Release (Apr)",
        "country":     "US",
        "importance":  "high",
        "indicator":   "CPIAUCSL",
    },
    {
        "date":        "2026-04-15",
        "event":       "Taiwan GDP Preliminary (Q1)",
        "country":     "TW",
        "importance":  "high",
        "indicator":   "TW_GDP",
    },
    {
        "date":        "2026-04-25",
        "event":       "Taiwan Export Orders (Mar)",
        "country":     "TW",
        "importance":  "medium",
        "indicator":   "TW_EXPORT_YOY",
    },
    {
        "date":        "2026-06-18",
        "event":       "CBC Interest Rate Decision",
        "country":     "TW",
        "importance":  "critical",
        "indicator":   None,
    },
    # ISM Manufacturing PMI (monthly, 1st business day)
    {"date": "2026-04-01", "event": "ISM Manufacturing PMI", "country": "US", "importance": "high", "recurrence": "monthly_1st_biz_day"},
    {"date": "2026-05-01", "event": "ISM Manufacturing PMI", "country": "US", "importance": "high", "recurrence": "monthly_1st_biz_day"},
    {"date": "2026-06-01", "event": "ISM Manufacturing PMI", "country": "US", "importance": "high", "recurrence": "monthly_1st_biz_day"},
    # Taiwan Monthly Revenue Deadline (every month 10th)
    {"date": "2026-04-10", "event": "上市櫃月營收公告截止", "country": "TW", "importance": "high", "recurrence": "monthly_10th"},
    {"date": "2026-05-10", "event": "上市櫃月營收公告截止", "country": "TW", "importance": "high", "recurrence": "monthly_10th"},
    {"date": "2026-06-10", "event": "上市櫃月營收公告截止", "country": "TW", "importance": "high", "recurrence": "monthly_10th"},
    # China Manufacturing PMI (monthly, last day or 1st)
    {"date": "2026-03-31", "event": "中國製造業PMI", "country": "CN", "importance": "high", "recurrence": "monthly_last_day"},
    {"date": "2026-04-30", "event": "中國製造業PMI", "country": "CN", "importance": "high", "recurrence": "monthly_last_day"},
    {"date": "2026-05-31", "event": "中國製造業PMI", "country": "CN", "importance": "high", "recurrence": "monthly_last_day"},
    # Taiwan Ex-dividend Season (June-September marker)
    {"date": "2026-06-01", "event": "台股除權息旺季開始", "country": "TW", "importance": "medium", "recurrence": "annual"},
    {"date": "2026-09-30", "event": "台股除權息旺季結束", "country": "TW", "importance": "medium", "recurrence": "annual"},
]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _research_conn() -> sqlite3.Connection:
    """Open a read-only-safe connection to research.db."""
    init_research_db()
    return connect_research(RESEARCH_DB_PATH)


# ---------------------------------------------------------------------------
# Cached dashboard fetch
# ---------------------------------------------------------------------------

@cached(ttl=3600, maxsize=4)
def _dashboard_cached() -> dict:
    """Fetch latest value for every indicator and yield curve data, cached 1 hour."""
    conn = _research_conn()
    try:
        # Latest value per indicator
        rows = conn.execute("""
            SELECT m.indicator_id, m.date, m.value, m.unit, m.source, m.country
            FROM macro_indicators m
            INNER JOIN (
                SELECT indicator_id, MAX(date) AS max_date
                FROM macro_indicators
                GROUP BY indicator_id
            ) latest ON m.indicator_id = latest.indicator_id AND m.date = latest.max_date
            ORDER BY m.country, m.indicator_id
        """).fetchall()

        # Fetch previous value per indicator in one query using window function
        prev_rows = conn.execute("""
            SELECT indicator_id, value
            FROM (
                SELECT indicator_id, value,
                       ROW_NUMBER() OVER (PARTITION BY indicator_id ORDER BY date DESC) AS rn
                FROM macro_indicators
            ) ranked
            WHERE rn = 2
        """).fetchall()
        prev_value_map = {r["indicator_id"]: r["value"] for r in prev_rows}

        # Build kpi list with previous value for trend
        kpis = []
        freshness: Optional[str] = None

        for row in rows:
            ind_id = row["indicator_id"]
            meta   = _INDICATOR_META.get(ind_id, {})

            current_val  = row["value"]
            previous_val = prev_value_map.get(ind_id)
            change       = round(current_val - previous_val, 4) if previous_val is not None else None
            trend        = (
                "up"   if change is not None and change > 0 else
                "down" if change is not None and change < 0 else
                "flat"
            )

            kpis.append({
                "indicator_id":   ind_id,
                "indicator_name": meta.get("name", ind_id),
                "latest_value":   current_val,
                "previous_value": previous_val,
                "change":         change,
                "unit":           row["unit"] or meta.get("unit"),
                "date":           row["date"],
                "country":        row["country"],
                "source":         row["source"],
                "trend":          trend,
            })

            if freshness is None or (row["date"] and row["date"] > freshness):
                freshness = row["date"]

        # Yield curve section
        dgs10_row = next((k for k in kpis if k["indicator_id"] == "DGS10"), None)
        dgs2_row  = next((k for k in kpis if k["indicator_id"] == "DGS2"),  None)
        spread_row = next((k for k in kpis if k["indicator_id"] == "SPREAD_10Y_2Y"), None)

        spread_val = spread_row["latest_value"] if spread_row else (
            round(dgs10_row["latest_value"] - dgs2_row["latest_value"], 4)
            if dgs10_row and dgs2_row else None
        )

        yield_curve = {
            "spread_10y_2y": spread_val,
            "inverted":      spread_val is not None and spread_val < 0,
            "data": [
                {"maturity": "2Y",  "yield": dgs2_row["latest_value"]  if dgs2_row  else None},
                {"maturity": "10Y", "yield": dgs10_row["latest_value"] if dgs10_row else None},
            ],
        }

        return {
            "kpis":        kpis,
            "yield_curve": yield_curve,
            "freshness":   freshness,
            "total":       len(kpis),
        }

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/dashboard")
def get_macro_dashboard(
    country: Optional[str] = Query(
        default=None,
        description="Filter by country: 'US', 'TW', or omit for all",
    ),
):
    """Return latest KPI values for all macro indicators plus yield curve snapshot.

    Cached for 3600 seconds (1 hour).
    """
    try:
        data = _dashboard_cached()
    except Exception as exc:
        log.error("macro dashboard error: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable") from exc

    kpis = data["kpis"]
    if country:
        country_upper = country.upper()
        kpis = [k for k in kpis if k["country"] == country_upper]

    return api_response(
        {
            "kpis":        kpis,
            "yield_curve": data["yield_curve"],
        },
        total=len(kpis),
        source="research.db/macro_indicators",
        freshness=data.get("freshness"),
    )


@router.get("/indicator/{indicator_id}/history")
def get_indicator_history(
    indicator_id: str = Path(..., description="FRED series ID or custom indicator ID"),
    months: int = Query(
        default=12,
        ge=1,
        le=120,
        description="Number of months to look back (default 12, max 120)",
    ),
    days: Optional[int] = Query(
        default=None,
        ge=1,
        le=3650,
        description="Alias: number of days to look back (overrides months when provided)",
    ),
):
    """Return historical data points for a single macro indicator.

    Args:
        indicator_id: FRED series ID (e.g. 'FEDFUNDS') or custom ID.
        months:       Calendar months to look back (1–120, default 12).
        days:         Alias for specifying look-back in days (overrides months when provided).
    """
    if days is not None:
        since = (date.today() - timedelta(days=days)).isoformat()
    else:
        since = (date.today() - timedelta(days=months * 31)).isoformat()

    try:
        conn = _research_conn()
        rows = conn.execute("""
            SELECT date, value, unit, source, country
            FROM macro_indicators
            WHERE indicator_id = ? AND date >= ?
            ORDER BY date ASC
        """, (indicator_id, since)).fetchall()
        conn.close()
    except Exception as exc:
        log.error("macro indicator history error [%s]: %s", indicator_id, exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable") from exc

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No data found for indicator '{indicator_id}' in the last {months} months.",
        )

    meta_entry = _INDICATOR_META.get(indicator_id, {})
    data = [{"date": r["date"], "value": r["value"]} for r in rows]
    latest_row = rows[-1]

    return api_response(
        data,
        total=len(data),
        source=f"research.db/macro_indicators/{indicator_id}",
        freshness=data[-1]["date"] if data else None,
    ) | {
        "meta": {
            "indicator_id":   indicator_id,
            "indicator_name": meta_entry.get("name", indicator_id),
            "unit":           latest_row["unit"] or meta_entry.get("unit"),
            "country":        latest_row["country"],
            "source":         latest_row["source"],
            "total":          len(data),
        }
    }


@router.get("/calendar")
def get_economic_calendar(
    country: Optional[str] = Query(
        default=None,
        description="Filter by country: 'US', 'TW', or omit for all",
    ),
):
    """Return upcoming economic calendar events sorted by date.

    Events are hardcoded (Phase 2 initial implementation).
    Dynamic scraping planned for Phase 3.
    """
    today = date.today().isoformat()
    events = sorted(
        [e for e in FIXED_EVENTS if e["date"] >= today],
        key=lambda x: x["date"],
    )

    if country:
        country_upper = country.upper()
        events = [e for e in events if e["country"] == country_upper]

    return api_response(
        events,
        total=len(events),
        source="hardcoded/economic_calendar",
    )
