"""research_reports.py — Research Reports CRUD API.

Endpoints:
  GET  /api/research-reports/list?type=geopolitical&page=1&per_page=20
      List reports from research_reports table, filterable by type.
      Type filter: geopolitical, market, investment (partial-match on report_type).

  GET  /api/research-reports/{report_id}
      Single report with full body content.

  POST /api/research-reports/generate
      Queue a report generation run (202 Accepted — async stub).
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from app.core.response import api_response
from app.db.research_db import get_research_conn

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/research-reports", tags=["research-reports"])

# ── Type filter mapping ────────────────────────────────────────────────────────

_TYPE_PATTERNS: Dict[str, str] = {
    "geopolitical": "%geopolitical%",
    "market":       "%market%",
    "investment":   "%investment%",
}


# ── Dependency: research.db connection ────────────────────────────────────────

def _research_conn_dep():
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_report(row: sqlite3.Row, *, include_body: bool = False) -> Dict[str, Any]:
    """Convert a research_reports row to API dict."""
    d = dict(row)
    body: Optional[str] = d.get("body")

    if not include_body:
        # Preview: first 100 chars of body, stripped of leading markdown fences
        preview = ""
        if body:
            stripped = body.strip()
            # Remove leading code-fence if present
            if stripped.startswith("```"):
                stripped = stripped[stripped.find("\n") + 1:]
            preview = stripped[:100].replace("\n", " ").strip()
        d["preview"] = preview
        d.pop("body", None)

    return d


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/list")
def list_reports(
    type: Optional[str] = Query(None, description="Filter by type: geopolitical / market / investment"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(20, ge=1, le=100, description="Records per page"),
    conn: sqlite3.Connection = Depends(_research_conn_dep),
):
    """List research reports with optional type filter and pagination.

    Returns paginated report cards (no full body — use /list/{id} for full content).
    """
    offset = (page - 1) * per_page

    # Build WHERE clause
    where_parts: List[str] = []
    params: List[Any] = []

    if type and type in _TYPE_PATTERNS:
        where_parts.append("report_type LIKE ?")
        params.append(_TYPE_PATTERNS[type])
    elif type and type not in _TYPE_PATTERNS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid type '{type}'. Valid values: geopolitical, market, investment",
        )

    where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    try:
        count_row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM research_reports {where_sql}", params
        ).fetchone()
        total = count_row["cnt"] if count_row else 0

        rows = conn.execute(
            f"""SELECT id, report_date, report_type, title, summary, body,
                       tickers, sentiment, confidence, model_id, created_at
                FROM research_reports
                {where_sql}
                ORDER BY report_date DESC, created_at DESC
                LIMIT ? OFFSET ?""",
            params + [per_page, offset],
        ).fetchall()

        data = [_row_to_report(r, include_body=False) for r in rows]

    except sqlite3.Error as e:
        log.error("list_reports DB error: %s", e)
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")

    return api_response(
        data,
        total=total,
        page=page,
        per_page=per_page,
        source="research.db",
    )


@router.get("/{report_id}")
def get_report(
    report_id: int,
    conn: sqlite3.Connection = Depends(_research_conn_dep),
):
    """Fetch a single research report with full Markdown body."""
    try:
        row = conn.execute(
            """SELECT id, report_date, report_type, title, summary, body,
                      tickers, sentiment, confidence, model_id, created_at
               FROM research_reports
               WHERE id = ?""",
            (report_id,),
        ).fetchone()
    except sqlite3.Error as e:
        log.error("get_report DB error: %s", e)
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")

    if not row:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found")

    return api_response(_row_to_report(row, include_body=True), source="research.db")


@router.post("/generate")
def generate_report(
    type: str = Query("geopolitical", description="Report type to generate: geopolitical / market / investment"),
):
    """Queue a report generation run.

    Returns 202 Accepted immediately — actual generation is handled asynchronously
    by the research agent pipeline. The caller should poll /list to check for new reports.
    """
    valid_types = list(_TYPE_PATTERNS.keys())
    if type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid type '{type}'. Valid values: {', '.join(valid_types)}",
        )

    log.info("Report generation requested: type=%s", type)

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "message": f"Report generation queued for type={type}",
            "type": type,
        },
    )
