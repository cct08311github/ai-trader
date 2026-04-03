"""geopolitical.py — Geopolitical Events API Router.

Endpoints:
  GET /api/geopolitical/events?days=7&category=conflict&region=asia
      List geopolitical events with optional filters and pagination.

  GET /api/geopolitical/latest
      Latest 20 events (cached TTL 900 s).

  GET /api/geopolitical/triggers
      Latest thesis validator trigger results from CompetitorMonitorAgent.

Data sources:
  - geopolitical_events table (research.db)
  - llm_traces table (trades.db, for competitor_monitor trigger snapshots)
"""
from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

import app.db as db
from app.core.cache import cached
from app.db.research_db import get_research_conn

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/geopolitical", tags=["geopolitical"])


# ── Dependency: research.db connection ───────────────────────────────────────

def research_conn_dep():
    """FastAPI dependency: yield a read-write research.db connection."""
    try:
        with get_research_conn() as conn:
            yield conn
    except HTTPException:
        raise
    except sqlite3.Error as e:
        raise HTTPException(status_code=503, detail=f"research.db error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")


# ── Dependency: trades.db connection (for trigger data) ──────────────────────

def trades_conn_dep():
    """FastAPI dependency: yield a read-only trades.db connection."""
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

def _row_to_event(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert a geopolitical_events row to API dict."""
    d = dict(row)
    # Deserialize JSON fields
    for field in ("tags", "market_impact"):
        raw = d.get(field)
        if isinstance(raw, str):
            try:
                d[field] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                d[field] = raw
    return d


def _validate_category(value: Optional[str]) -> Optional[str]:
    """Return value if valid category, else raise 422."""
    valid = {"trade_war", "sanctions", "conflict", "policy", "election"}
    if value and value not in valid:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid category '{value}'. Valid: {sorted(valid)}",
        )
    return value


def _validate_region(value: Optional[str]) -> Optional[str]:
    """Return value if valid region, else raise 422."""
    valid = {"asia", "europe", "americas", "middle_east", "africa", "global"}
    if value and value not in valid:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid region '{value}'. Valid: {sorted(valid)}",
        )
    return value


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/events")
def list_events(
    days: int = Query(default=7, ge=1, le=365, description="Look-back window in days"),
    category: Optional[str] = Query(default=None, description="Filter by category"),
    region: Optional[str] = Query(default=None, description="Filter by region"),
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=50, ge=1, le=200, description="Results per page"),
    conn: sqlite3.Connection = Depends(research_conn_dep),
) -> Dict[str, Any]:
    """List geopolitical events with optional filters and pagination.

    Returns unified response envelope:
    {
        "ok": true,
        "total": <int>,
        "page": <int>,
        "page_size": <int>,
        "data": [<event>, ...]
    }
    """
    _validate_category(category)
    _validate_region(region)

    # Build WHERE clause with parameterised conditions
    conditions = ["event_date >= date('now', ?)"]
    params: List[Any] = [f"-{days} days"]

    if category:
        conditions.append("category = ?")
        params.append(category)
    if region:
        conditions.append("region = ?")
        params.append(region)

    where = " AND ".join(conditions)

    # Total count
    count_sql = f"SELECT COUNT(*) FROM geopolitical_events WHERE {where}"
    try:
        total = conn.execute(count_sql, params).fetchone()[0]
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"Query error: {e}")

    # Paginated results
    offset = (page - 1) * page_size
    data_sql = (
        f"SELECT * FROM geopolitical_events WHERE {where} "
        f"ORDER BY event_date DESC, id DESC "
        f"LIMIT ? OFFSET ?"
    )
    rows = conn.execute(data_sql, params + [page_size, offset]).fetchall()

    return {
        "ok": True,
        "total": total,
        "page": page,
        "page_size": page_size,
        "data": [_row_to_event(r) for r in rows],
    }


@cached(ttl=900, maxsize=4)
def _latest_events_cached() -> Dict[str, Any]:
    """Fetch latest 20 geopolitical events — cacheable helper (TTL 900 s).

    Uses its own short-lived connection so it can be safely cached without
    holding a DB connection across the TTL window.  Thread-safe via the
    Lock inside @cached.
    """
    try:
        with get_research_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM geopolitical_events ORDER BY event_date DESC, id DESC LIMIT 20"
            ).fetchall()
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"Query error: {e}")

    return {
        "ok": True,
        "data": [_row_to_event(r) for r in rows],
    }


@router.get("/latest")
def get_latest() -> Dict[str, Any]:
    """Return the latest 20 geopolitical events (cached for 900 s).

    Response envelope: {"ok": true, "data": [<event>, ...]}
    """
    return _latest_events_cached()


@router.get("/triggers")
def get_triggers(
    limit: int = Query(default=10, ge=1, le=100, description="Max trigger snapshots to return"),
    conn: sqlite3.Connection = Depends(trades_conn_dep),
) -> Dict[str, Any]:
    """Return the latest thesis validator trigger results from CompetitorMonitorAgent.

    Reads from llm_traces (trades.db), parses the stored response JSON which
    contains trigger result snapshots written by competitor_monitor.py.

    Response envelope:
    {
        "ok": true,
        "data": [
            {
                "run_at": <ISO timestamp>,
                "triggers": [
                    {"name": ..., "triggered": ..., "confidence": ...},
                    ...
                ]
            },
            ...
        ]
    }
    """
    try:
        rows = conn.execute(
            """SELECT response, created_at
               FROM llm_traces
               WHERE agent = 'CompetitorMonitorAgent'
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    except sqlite3.OperationalError as e:
        raise HTTPException(status_code=503, detail=f"Query error: {e}")

    results: List[Dict[str, Any]] = []
    for row in rows:
        raw_response = row[0] if isinstance(row, (tuple, list)) else row["response"]
        created_at_ts = row[1] if isinstance(row, (tuple, list)) else row["created_at"]

        # Parse stored JSON response
        try:
            payload = json.loads(raw_response) if raw_response else {}
        except (json.JSONDecodeError, TypeError):
            payload = {}

        # The competitor_monitor stores trigger info in the 'summary' field
        # and also writes individual trigger dicts under 'triggers' key if present.
        triggers_raw = payload.get("triggers", [])
        if not isinstance(triggers_raw, list):
            triggers_raw = []

        # Normalise triggers
        triggers = [
            {
                "name": t.get("trigger_name", t.get("name", "unknown")),
                "triggered": bool(t.get("triggered", False)),
                "confidence": int(t.get("confidence", 0)),
            }
            for t in triggers_raw
            if isinstance(t, dict)
        ]

        # Convert epoch seconds → ISO-8601
        try:
            from datetime import datetime, timezone
            run_at = datetime.fromtimestamp(int(created_at_ts), tz=timezone.utc).isoformat()
        except (ValueError, TypeError, OSError):
            run_at = str(created_at_ts)

        results.append({
            "run_at": run_at,
            "summary": payload.get("summary", ""),
            "triggers": triggers,
        })

    return {
        "ok": True,
        "data": results,
    }
