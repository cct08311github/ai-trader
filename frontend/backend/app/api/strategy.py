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
    """
    获取今日市场评级（A/B/C）。
    从 llm_traces 表中读取今日 component='pm' 的最新一条记录，
    尝试从 response_text 解析 rating 和 basis。
    """
    try:
        today = datetime.now().date().isoformat()
        row = conn.execute(
            """
            SELECT trace_id, ts, prompt_text, response_text, metadata_json
            FROM llm_traces
            WHERE component = 'pm' AND ts >= ? AND response_text IS NOT NULL
            ORDER BY ts DESC
            LIMIT 1
            """,
            (today,)
        ).fetchone()
        if not row:
            return {"status": "ok", "data": {"rating": None, "basis": None}}

        # 尝试解析 response_text，可能是 JSON 或纯文本
        response_text = row["response_text"]
        rating = None
        basis = None

        # 尝试解析 JSON
        try:
            data = json.loads(response_text)
            if isinstance(data, dict):
                rating = data.get("market_rating") or data.get("rating")
                basis = data.get("basis") or data.get("reason") or data.get("summary")
            elif isinstance(data, str):
                # 可能是字符串形式的评级，如 "A"
                rating = data.strip().upper()
                basis = None
        except json.JSONDecodeError:
            # 不是 JSON，尝试提取评级模式
            import re
            match = re.search(r'\b([ABC])\b', response_text.upper())
            if match:
                rating = match.group(1)
            basis = response_text.strip() if len(response_text) < 500 else response_text[:500] + "..."

        return {"status": "ok", "data": {"rating": rating, "basis": basis}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch market rating: {e}")


@router.get("/semantic-memory")
def get_semantic_memory(
    sort: str = "confidence",
    order: str = "desc",
    limit: int = 50,
    conn: sqlite3.Connection = Depends(conn_dep)
):
    """
    获取语义记忆库条目。
    sort: confidence, updated_at, sample_count
    order: asc, desc
    """
    try:
        valid_sorts = {"confidence", "updated_at", "sample_count", "rule_id"}
        if sort not in valid_sorts:
            sort = "confidence"
        valid_orders = {"asc", "desc"}
        if order not in valid_orders:
            order = "desc"

        query = f"""
            SELECT rule_id, rule_text, confidence, sample_count,
                   last_validated_date, status, source_episodes_json
            FROM semantic_memory
            ORDER BY {sort} {order}
            LIMIT ?
        """
        rows = conn.execute(query, (limit,)).fetchall()
        data = []
        for row in rows:
            data.append({
                "rule_id": row["rule_id"],
                "rule_text": row["rule_text"],
                "confidence": row["confidence"],
                "sample_count": row["sample_count"],
                "last_validated_date": row["last_validated_date"],
                "status": row["status"],
                "source_episodes_json": row["source_episodes_json"]
            })
        return {"status": "ok", "data": data}
    except sqlite3.OperationalError as e:
        if "no such table" in str(e).lower():
            return {"status": "ok", "data": []}
        raise HTTPException(status_code=500, detail=f"Failed to read semantic_memory: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch semantic memory: {e}")


@router.get("/debates")
def get_debates(
    date: str = "today",
    conn: sqlite3.Connection = Depends(conn_dep)
):
    """
    获取多空辩论记录。
    date: "today" 或 YYYY-MM-DD
    """
    try:
        if date == "today":
            target_date = datetime.now().date().isoformat()
        else:
            target_date = date  # 假设格式正确
        # 查找 component='pm' 且 prompt_text 包含 bull_case 或 bear_case 的记录
        rows = conn.execute(
            """
            SELECT trace_id, ts, prompt_text, response_text, metadata_json
            FROM llm_traces
            WHERE component = 'pm' AND ts >= ? AND (
                prompt_text LIKE '%bull_case%' OR 
                prompt_text LIKE '%bear_case%' OR
                prompt_text LIKE '%辩论%' OR
                prompt_text LIKE '%debate%'
            )
            ORDER BY ts ASC
            """,
            (target_date,)
        ).fetchall()
        debates = []
        for row in rows:
            # 尝试解析 response_text 为 JSON
            response_text = row["response_text"]
            try:
                data = json.loads(response_text)
                bull_case = data.get("bull_case") or data.get("bull")
                bear_case = data.get("bear_case") or data.get("bear")
                pm_judgment = data.get("pm_judgment") or data.get("judgment") or data.get("conclusion")
            except json.JSONDecodeError:
                bull_case = None
                bear_case = None
                pm_judgment = None
            debates.append({
                "trace_id": row["trace_id"],
                "ts": row["ts"],
                "bull_case": bull_case,
                "bear_case": bear_case,
                "pm_judgment": pm_judgment,
                "prompt_text": row["prompt_text"],
                "response_text": response_text
            })
        return {"status": "ok", "data": debates}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch debates: {e}")
