from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.core.config import get_settings
from app.db import get_conn
from app.services.strategy_service import StrategyService

router = APIRouter(prefix="/api/strategy", tags=["strategy"])

service = StrategyService()


def conn_dep():
    try:
        with get_conn() as conn:
            yield conn
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connection failed: {e}")


def require_ops_token(x_ops_token: Optional[str] = Header(default=None)) -> None:
    settings = get_settings()
    if not settings.strategy_ops_token:
        raise HTTPException(status_code=503, detail="STRATEGY_OPS_TOKEN not configured on backend")
    if not x_ops_token or x_ops_token != settings.strategy_ops_token:
        raise HTTPException(status_code=401, detail="Unauthorized")


class DecideRequest(BaseModel):
    actor: str = "user"
    reason: str = ""


@router.get("/proposals")
def get_strategy_proposals(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    conn: sqlite3.Connection = Depends(conn_dep),
):
    try:
        return service.list_proposals(conn, limit=limit, offset=offset, status=status)
    except sqlite3.OperationalError as e:
        # If the table doesn't exist in a fresh db, return empty (read-only service).
        if "no such table" in str(e).lower():
            return {"status": "ok", "data": [], "limit": limit, "offset": offset}
        raise HTTPException(status_code=500, detail=f"Failed to read strategy_proposals: {e}")


@router.get("/logs")
def get_strategy_logs(
    limit: int = 50,
    offset: int = 0,
    trace_id: Optional[str] = None,
    conn: sqlite3.Connection = Depends(conn_dep),
):
    try:
        return service.list_logs(conn, limit=limit, offset=offset, trace_id=trace_id)
    except sqlite3.OperationalError as e:
        if "no such table" in str(e).lower():
            return {"status": "ok", "data": [], "limit": limit, "offset": offset}
        raise HTTPException(status_code=500, detail=f"Failed to read llm_traces: {e}")


@router.post("/{proposal_id}/approve")
def approve_strategy_proposal(
    proposal_id: str,
    req: DecideRequest,
    _=Depends(require_ops_token),
):
    settings = get_settings()
    service.ensure_rw_allowed(settings)
    raise HTTPException(status_code=501, detail="RW workflow is not enabled in read-only backend build")


@router.post("/{proposal_id}/reject")
def reject_strategy_proposal(
    proposal_id: str,
    req: DecideRequest,
    _=Depends(require_ops_token),
):
    settings = get_settings()
    service.ensure_rw_allowed(settings)
    raise HTTPException(status_code=501, detail="RW workflow is not enabled in read-only backend build")
