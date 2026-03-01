from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

import app.db as db
from app.services.strategy_service import StrategyService

router = APIRouter(prefix="/api/strategy", tags=["strategy"])

service = StrategyService()


def conn_dep():
    """Read-only DB connection dependency.

    Note: we import the db module (not get_conn directly) so that test suites that
    reload app.db after setting env vars still use the refreshed DB_PATH.
    """

    try:
        with db.get_conn() as conn:
            yield conn
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connection failed: {e}")


def require_ops_token(x_ops_token: Optional[str] = Header(default=None, alias="X-OPS-TOKEN")) -> None:
    """Require an operator token for state-changing operations.

    Note: use env lookup directly to avoid stale lru_cache state across tests.
    """

    import os

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
    conn: sqlite3.Connection = Depends(conn_dep),
):
    try:
        return service.list_proposals(conn, limit=limit, offset=offset, status=status)
    except sqlite3.OperationalError as e:
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
    decided_at = int(time.time())

    conn.execute(
        "UPDATE strategy_proposals SET status = ?, decided_at = ? WHERE proposal_id = ?",
        (new_status, decided_at, proposal_id),
    )

    details: Dict[str, Any] = {
        "proposal_id": proposal_id,
        "from": current,
        "to": new_status,
        "reason": reason,
    }
    try:
        payload = row["proposal_json"]
        if payload:
            details["proposal_json"] = json.loads(payload)
    except Exception:
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
    _: None = Depends(require_ops_token),
):
    try:
        with db.get_conn_rw() as conn:
            updated = _update_proposal_status(
                conn,
                proposal_id=proposal_id,
                new_status="approved",
                actor=req.actor,
                reason=req.reason,
            )
        return {"status": "ok", "data": updated}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to approve proposal: {e}")


@router.post("/{proposal_id}/reject")
def reject_strategy_proposal(
    proposal_id: str,
    req: DecideRequest,
    _: None = Depends(require_ops_token),
):
    try:
        with db.get_conn_rw() as conn:
            updated = _update_proposal_status(
                conn,
                proposal_id=proposal_id,
                new_status="rejected",
                actor=req.actor,
                reason=req.reason,
            )
        return {"status": "ok", "data": updated}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reject proposal: {e}")


@router.get("/market-rating")
def get_market_rating(conn: sqlite3.Connection = Depends(conn_dep)):
    """Return latest market rating from episodic_memory or working_memory."""
    try:
        # Try episodic_memory first (most recent market assessment)
        row = conn.execute(
            """
            SELECT content, created_at FROM episodic_memory
            WHERE content LIKE '%market%' OR content LIKE '%rating%' OR content LIKE '%市場%'
            ORDER BY created_at DESC LIMIT 1
            """
        ).fetchone()
        if row:
            return {
                "status": "ok",
                "data": {
                    "summary": str(row["content"])[:300],
                    "updated_at": row["created_at"],
                    "rating": "neutral",
                    "source": "episodic_memory",
                }
            }
        return {"status": "ok", "data": None}
    except sqlite3.OperationalError:
        return {"status": "ok", "data": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/semantic-memory")
def get_semantic_memory(
    sort: str = "confidence",
    order: str = "desc",
    limit: int = 50,
    conn: sqlite3.Connection = Depends(conn_dep),
):
    """Return semantic memory entries (learned trading rules/patterns)."""
    try:
        order_sql = "DESC" if order.lower() == "desc" else "ASC"
        # Sort by confidence if column exists, else by created_at
        try:
            rows = conn.execute(
                f"SELECT * FROM semantic_memory ORDER BY confidence {order_sql} LIMIT ?",
                (limit,)
            ).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(
                f"SELECT * FROM semantic_memory ORDER BY created_at {order_sql} LIMIT ?",
                (limit,)
            ).fetchall()
        data = [dict(r) for r in rows]
        return {"status": "ok", "data": data, "total": len(data)}
    except sqlite3.OperationalError:
        return {"status": "ok", "data": [], "total": 0}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pm-traces")
def get_pm_traces(
    limit: int = 10,
    conn: sqlite3.Connection = Depends(conn_dep),
):
    """Return recent PM review LLM traces with full prompt and raw Gemini response."""
    try:
        rows = conn.execute(
            """
            SELECT trace_id, model, prompt, response, latency_ms, created_at
            FROM llm_traces
            WHERE agent = 'pm_review'
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (min(limit, 50),),
        ).fetchall()
        data = [dict(r) for r in rows]
        return {"status": "ok", "data": data, "total": len(data)}
    except sqlite3.OperationalError:
        return {"status": "ok", "data": [], "total": 0}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/debates")
def get_debates(
    date: str = "today",
    conn: sqlite3.Connection = Depends(conn_dep),
):
    """Return AI debate records from episodic_memory (episode_type='pm_review')."""
    try:
        from datetime import date as _date, datetime, timezone
        if date == "today":
            date_str = _date.today().isoformat()
        else:
            date_str = date

        # created_at is Unix integer — compute day range
        day_start = int(datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc).timestamp())
        day_end = day_start + 86400

        rows = conn.execute(
            """
            SELECT episode_id, episode_type, summary, content_json, created_at
            FROM episodic_memory
            WHERE episode_type = 'pm_review'
              AND created_at >= ? AND created_at < ?
            ORDER BY created_at DESC LIMIT 50
            """,
            (day_start, day_end)
        ).fetchall()
        data = [dict(r) for r in rows]
        return {"status": "ok", "data": data, "date": date_str, "total": len(data)}
    except sqlite3.OperationalError:
        return {"status": "ok", "data": [], "date": date, "total": 0}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
