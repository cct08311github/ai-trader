from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.db import fetch_rows, get_conn

router = APIRouter(prefix="/api/strategy", tags=["strategy"])


def _conn_dep():
    # FastAPI dependency wrapper around contextmanager
    try:
        with get_conn() as conn:
            yield conn
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connection failed: {e}")


@router.get("/proposals")
def get_strategy_proposals(limit: int = 50, offset: int = 0, conn=Depends(_conn_dep)):
    """Read-only: return rows from strategy_proposals."""
    try:
        data = fetch_rows(conn, table="strategy_proposals", limit=limit, offset=offset)
        return {"status": "ok", "data": data, "limit": limit, "offset": offset}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read strategy_proposals: {e}")


@router.get("/logs")
def get_strategy_logs(limit: int = 50, offset: int = 0, conn=Depends(_conn_dep)):
    """Read-only: return rows from llm_traces."""
    try:
        data = fetch_rows(conn, table="llm_traces", limit=limit, offset=offset)
        return {"status": "ok", "data": data, "limit": limit, "offset": offset}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read llm_traces: {e}")
