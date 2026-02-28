from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.db import fetch_rows, get_conn, get_conn_rw

router = APIRouter(prefix="/api/strategy", tags=["strategy"])


def _conn_dep():
    # FastAPI dependency wrapper around contextmanager (read-only)
    try:
        with get_conn() as conn:
            yield conn
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connection failed: {e}")


def _conn_rw_dep():
    # FastAPI dependency wrapper around contextmanager (read-write)
    try:
        with get_conn_rw() as conn:
            yield conn
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connection failed: {e}")


def _require_ops_token(x_ops_token: Optional[str] = Header(default=None)) -> None:
    """Require an operator token for state-changing operations.

    Set env var STRATEGY_OPS_TOKEN on the backend.
    Client must pass header: X-OPS-TOKEN: <token>

    If STRATEGY_OPS_TOKEN is missing, we *deny by default* for safety.
    """

    expected = os.environ.get("STRATEGY_OPS_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="STRATEGY_OPS_TOKEN not configured on backend")

    if not x_ops_token or x_ops_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


class DecideRequest(BaseModel):
    actor: str = "user"
    reason: str = ""


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Ensure required tables exist.

    production DB already has these, but keep it safe for fresh environments.
    """

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_proposals (
            proposal_id TEXT PRIMARY KEY,
            generated_by TEXT,
            target_rule TEXT,
            rule_category TEXT,
            current_value TEXT,
            proposed_value TEXT,
            supporting_evidence TEXT,
            confidence REAL,
            requires_human_approval INTEGER,
            status TEXT,
            expires_at INTEGER,
            proposal_json TEXT,
            created_at INTEGER,
            decided_at INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS version_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_id TEXT,
            action TEXT,
            performed_by TEXT,
            details TEXT,
            performed_at TEXT
        )
        """
    )


@router.get("/proposals")
def get_strategy_proposals(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    conn=Depends(_conn_dep),
):
    """Read-only: return rows from strategy_proposals.

    Note: strategy_proposals is a shared source for both:
    - Sentinel proposed changes / actions
    - Frontend operator approval workflow
    """

    try:
        # Fetch via helper; apply filter in-memory (simple & safe)
        data = fetch_rows(conn, table="strategy_proposals", limit=limit, offset=offset)
        if status:
            s = status.strip().lower()
            data = [r for r in data if str(r.get("status") or "").lower() == s]
        return {"status": "ok", "data": data, "limit": limit, "offset": offset}
    except sqlite3.OperationalError as e:
        # If table missing (fresh env), create it via RW and return empty.
        if "no such table" in str(e).lower():
            with get_conn_rw() as c2:
                _ensure_tables(c2)
            return {"status": "ok", "data": [], "limit": limit, "offset": offset}
        raise HTTPException(status_code=500, detail=f"Failed to read strategy_proposals: {e}")
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read strategy_proposals: {e}")


@router.get("/logs")
def get_strategy_logs(
    limit: int = 50,
    offset: int = 0,
    trace_id: Optional[str] = None,
    conn=Depends(_conn_dep),
):
    """Read-only: return rows from llm_traces.

    Optional: filter by trace_id.
    """

    try:
        if trace_id:
            rows = conn.execute(
                """
                SELECT * FROM llm_traces
                WHERE trace_id = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (trace_id, max(1, min(int(limit), 500)), max(0, int(offset))),
            ).fetchall()
            data = [dict(r) for r in rows]
        else:
            data = fetch_rows(conn, table="llm_traces", limit=limit, offset=offset)
        return {"status": "ok", "data": data, "limit": limit, "offset": offset}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read llm_traces: {e}")


def _update_proposal_status(
    conn: sqlite3.Connection,
    *,
    proposal_id: str,
    new_status: str,
    actor: str,
    reason: str,
) -> Dict[str, Any]:
    new_status = new_status.strip().lower()
    if new_status not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Invalid status")

    _ensure_tables(conn)

    row = conn.execute(
        "SELECT proposal_id, status, proposal_json FROM strategy_proposals WHERE proposal_id = ?",
        (proposal_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Proposal not found")

    current = str(row["status"] or "").lower()
    if current in {"executed"}:
        raise HTTPException(status_code=409, detail=f"Proposal already {current}")
    if current == new_status:
        # idempotent
        pass

    decided_at = int(time.time())
    conn.execute(
        "UPDATE strategy_proposals SET status = ?, decided_at = ? WHERE proposal_id = ?",
        (new_status, decided_at, proposal_id),
    )

    # Audit log
    details = {
        "proposal_id": proposal_id,
        "from": current,
        "to": new_status,
        "reason": reason,
    }

    try:
        proposal_payload = row["proposal_json"]
        if proposal_payload:
            details["proposal_json"] = json.loads(proposal_payload)
    except Exception:
        # best-effort
        pass

    conn.execute(
        """
        INSERT INTO version_audit_log(version_id, action, performed_by, details, performed_at)
        VALUES(?, ?, ?, ?, ?)
        """,
        (
            proposal_id,
            f"strategy_proposal_{new_status}",
            actor,
            json.dumps(details, ensure_ascii=False),
            _now_iso(),
        ),
    )

    updated = conn.execute("SELECT * FROM strategy_proposals WHERE proposal_id = ?", (proposal_id,)).fetchone()
    return dict(updated) if updated else {"proposal_id": proposal_id, "status": new_status, "decided_at": decided_at}


@router.post("/{proposal_id}/approve")
def approve_strategy_proposal(
    proposal_id: str,
    req: DecideRequest,
    conn=Depends(_conn_rw_dep),
    _=Depends(_require_ops_token),
):
    """Approve a strategy proposal (manual intervention)."""

    try:
        updated = _update_proposal_status(conn, proposal_id=proposal_id, new_status="approved", actor=req.actor, reason=req.reason)
        return {"status": "ok", "data": updated}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Approve failed: {e}")


@router.post("/{proposal_id}/reject")
def reject_strategy_proposal(
    proposal_id: str,
    req: DecideRequest,
    conn=Depends(_conn_rw_dep),
    _=Depends(_require_ops_token),
):
    """Reject a strategy proposal (manual intervention)."""

    try:
        updated = _update_proposal_status(conn, proposal_id=proposal_id, new_status="rejected", actor=req.actor, reason=req.reason)
        return {"status": "ok", "data": updated}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reject failed: {e}")
