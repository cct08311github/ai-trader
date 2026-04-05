from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
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



class DecideRequest(BaseModel):
    actor: str = "user"
    reason: str = ""


class BatchDecideRequest(BaseModel):
    proposal_ids: list[str]
    actor: str = "user"
    reason: str = ""

_BATCH_MAX = 50


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


@router.post("/proposals/batch/{action}")
def batch_decide(action: str, req: BatchDecideRequest):
    """批量核准或拒絕多筆 pending 提案。

    action: "approve" | "reject"
    最多 50 筆/次。每筆獨立寫 version_audit_log。
    已非 pending 的提案放入 failed（不中斷流程）。
    """
    action = action.strip().lower()
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")
    if not req.proposal_ids:
        raise HTTPException(status_code=422, detail="proposal_ids must not be empty")
    if len(req.proposal_ids) > _BATCH_MAX:
        raise HTTPException(
            status_code=422,
            detail=f"Too many proposals: {len(req.proposal_ids)} (max {_BATCH_MAX})",
        )

    succeeded: list[dict] = []
    failed: list[dict] = []

    try:
        with db.get_conn_rw() as conn:
            _ensure_tables(conn)
            for pid in req.proposal_ids:
                row = conn.execute(
                    "SELECT proposal_id, status FROM strategy_proposals WHERE proposal_id = ?",
                    (pid,),
                ).fetchone()
                if not row:
                    failed.append({"proposal_id": pid, "reason": "not_found"})
                    continue
                if str(row["status"] or "").lower() != "pending":
                    failed.append({"proposal_id": pid, "reason": f"already_{row['status']}"})
                    continue
                try:
                    updated = _update_proposal_status(
                        conn,
                        proposal_id=pid,
                        new_status=action + ("d" if action == "approve" else "ed"),
                        actor=req.actor,
                        reason=req.reason or f"batch_{action}",
                    )
                    succeeded.append({"proposal_id": pid, "status": updated.get("status", action)})
                except Exception as exc:
                    failed.append({"proposal_id": pid, "reason": str(exc)})
            conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch {action} failed: {e}")

    return {
        "status": "ok",
        "action": action,
        "total": len(req.proposal_ids),
        "succeeded": succeeded,
        "failed": failed,
    }


@router.get("/proposals/batch-approve-all", response_class=HTMLResponse)
def batch_approve_all_url(token: str = Query(...)):
    """一鍵核准所有 pending 提案（Telegram URL button 用）。"""
    import os
    if token != os.environ.get("AUTH_TOKEN", ""):
        return HTMLResponse("<h2>❌ 無效 token</h2>", status_code=403)

    approved_ids: list[str] = []
    with db.get_conn_rw() as conn:
        _ensure_tables(conn)
        rows = conn.execute(
            "SELECT proposal_id, target_rule FROM strategy_proposals WHERE status = 'pending'"
        ).fetchall()
        now_ts = int(time.time())
        for row in rows:
            pid = row["proposal_id"]
            conn.execute(
                "UPDATE strategy_proposals SET status='approved', decided_at=? WHERE proposal_id=?",
                (now_ts, pid),
            )
            conn.execute(
                """INSERT INTO version_audit_log(version_id, action, performed_by, details, performed_at)
                   VALUES(?, ?, ?, ?, ?)""",
                (
                    pid,
                    "strategy_proposal_approved",
                    "telegram_batch",
                    json.dumps({"proposal_id": pid, "from": "pending", "to": "approved",
                                "reason": "batch_approve_all"}, ensure_ascii=False),
                    _now_iso(),
                ),
            )
            approved_ids.append(pid[:8])
        conn.commit()

    n = len(approved_ids)
    if n == 0:
        return HTMLResponse("<h2>⚠️ 目前無待審提案</h2><p>可關閉此頁面。</p>")

    try:
        from openclaw.tg_notify import send_message
        send_message(
            f"✅ <b>批量核准完成</b> — 共 {n} 筆提案已核准\n"
            f"IDs: {', '.join(approved_ids)}…",
            chat_id=os.environ.get("TELEGRAM_CHAT_ID", "-1003772422881"),
        )
    except Exception:
        pass

    ids_html = "".join(f"<li>{pid}…</li>" for pid in approved_ids)
    return HTMLResponse(
        f"<h2>✅ 批量核准完成 — {n} 筆</h2><ul>{ids_html}</ul><p>可關閉此頁面。</p>"
    )


@router.get("/market-rating")
def get_market_rating(conn: sqlite3.Connection = Depends(conn_dep)):
    """Return latest market rating from episodic_memory or working_memory."""
    try:
        # Try episodic_memory first (most recent market assessment)
        row = conn.execute(
            """
            SELECT content_json, summary, created_at FROM episodic_memory
            WHERE content_json LIKE '%market%' OR content_json LIKE '%rating%' OR content_json LIKE '%市場%'
               OR summary LIKE '%市場%' OR summary LIKE '%觀望%' OR summary LIKE '%多頭%'
            ORDER BY created_at DESC LIMIT 1
            """
        ).fetchone()
        if row:
            import json as _json
            cj = {}
            try:
                cj = _json.loads(row["content_json"] or "{}")
            except Exception:
                pass
            confidence = cj.get("confidence", 0)
            approved = cj.get("approved", False)
            action = cj.get("recommended_action", "")
            # Map to A/B/C: approved+high conf=A, approved=B, not approved=C
            if approved and confidence >= 0.7:
                rating = "A"
            elif approved:
                rating = "B"
            else:
                rating = "C"
            basis = cj.get("adjudication") or row["summary"] or action
            return {
                "status": "ok",
                "data": {
                    "summary": str(basis)[:300],
                    "updated_at": row["created_at"],
                    "rating": rating,
                    "source": "episodic_memory",
                    "basis": str(basis)[:300],
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

        # created_at is Unix integer — compute day range in TWN (UTC+8)
        from datetime import timedelta
        TWN = timezone(timedelta(hours=8))
        day_start = int(datetime.fromisoformat(date_str).replace(tzinfo=TWN).timestamp())
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


@router.get("/proposals/{proposal_id}/approve", response_class=HTMLResponse)
def approve_proposal_url(proposal_id: str, token: str = Query(...)):
    """URL 按鈕核准提案（Telegram URL button 用）。"""
    import os
    if token != os.environ.get("AUTH_TOKEN", ""):
        return HTMLResponse("<h2>❌ 無效 token</h2>", status_code=403)
    with db.get_conn_rw() as conn:
        row = conn.execute(
            "SELECT proposal_id, target_rule, status FROM strategy_proposals WHERE proposal_id=?",
            (proposal_id,)
        ).fetchone()
        if not row:
            return HTMLResponse("<h2>❌ 找不到提案</h2>", status_code=404)
        if row["status"] != "pending":
            return HTMLResponse(f"<h2>⚠️ 提案已處理（狀態：{row['status']}）</h2>")
        conn.execute(
            "UPDATE strategy_proposals SET status='approved', decided_at=? WHERE proposal_id=?",
            (int(time.time()), proposal_id)
        )
        conn.commit()
    try:
        from openclaw.tg_notify import send_message
        send_message(f"✅ 已核准 — {row['target_rule']}（{proposal_id[:8]}…）", chat_id=os.environ.get("TELEGRAM_CHAT_ID", "-1003772422881"))
    except Exception:
        pass
    return HTMLResponse("<h2>✅ 提案已核准</h2><p>可關閉此頁面。</p>")


@router.post("/proposals/triage-pending")
def triage_pending_proposals():
    """批量處理 pending proposals（修復 #631）。

    規則：
    - confidence >= 0.65 + STOP_LOSS/POSITION_REDUCTION/RISK_CONTROL 類 → approved
    - DATA_RECOVERY/DATA_REFRESH_REQUIRED → noted（人工追蹤）
    - confidence < 0.60 且非 DATA 類 → expired
    - 其餘 → 維持 pending（需人工決策）
    """
    _STOP_RULES = {
        "STOP_LOSS", "STOP_LOSS_THRESHOLD", "STOP_LOSS_ADJUSTMENT", "STOPLOSS_LEVEL",
        "POSITION_REDUCTION", "POSITION_MANAGEMENT", "RISK_CONTROL", "RISK_THRESHOLD",
        "停損紀律", "減碼時機與價位", "避免加碼攤平", "NO_AVERAGING_DOWN",
    }
    _DATA_RULES = {"DATA_RECOVERY", "DATA_REFRESH_REQUIRED", "資訊追蹤清單"}

    results = {"approved": [], "noted": [], "expired": [], "kept_pending": []}
    now_ts = int(time.time())

    with db.get_conn_rw() as conn:
        rows = conn.execute(
            "SELECT proposal_id, target_rule, rule_category, confidence "
            "FROM strategy_proposals WHERE status='pending'"
        ).fetchall()

        for row in rows:
            pid = row["proposal_id"]
            rule = row["target_rule"]
            conf = float(row["confidence"] or 0)

            if rule in _DATA_RULES:
                conn.execute(
                    "UPDATE strategy_proposals SET status='noted', decided_at=? WHERE proposal_id=?",
                    (now_ts, pid),
                )
                results["noted"].append({"proposal_id": pid, "rule": rule})
            elif rule in _STOP_RULES and conf >= 0.65:
                conn.execute(
                    "UPDATE strategy_proposals SET status='approved', decided_at=? WHERE proposal_id=?",
                    (now_ts, pid),
                )
                results["approved"].append({"proposal_id": pid, "rule": rule, "confidence": conf})
            elif conf < 0.60:
                conn.execute(
                    "UPDATE strategy_proposals SET status='expired', decided_at=? WHERE proposal_id=?",
                    (now_ts, pid),
                )
                results["expired"].append({"proposal_id": pid, "rule": rule, "confidence": conf})
            else:
                results["kept_pending"].append({"proposal_id": pid, "rule": rule, "confidence": conf})

        conn.commit()

    total = sum(len(v) for v in results.values())
    return {
        "status": "ok",
        "processed": total,
        "summary": {k: len(v) for k, v in results.items()},
        "details": results,
    }


@router.get("/proposals/{proposal_id}/reject", response_class=HTMLResponse)
def reject_proposal_url(proposal_id: str, token: str = Query(...)):
    """URL 按鈕拒絕提案（Telegram URL button 用）。"""
    import os
    if token != os.environ.get("AUTH_TOKEN", ""):
        return HTMLResponse("<h2>❌ 無效 token</h2>", status_code=403)
    with db.get_conn_rw() as conn:
        row = conn.execute(
            "SELECT proposal_id, target_rule, status FROM strategy_proposals WHERE proposal_id=?",
            (proposal_id,)
        ).fetchone()
        if not row:
            return HTMLResponse("<h2>❌ 找不到提案</h2>", status_code=404)
        if row["status"] != "pending":
            return HTMLResponse(f"<h2>⚠️ 提案已處理（狀態：{row['status']}）</h2>")
        conn.execute(
            "UPDATE strategy_proposals SET status='rejected', decided_at=? WHERE proposal_id=?",
            (int(time.time()), proposal_id)
        )
        conn.commit()
    try:
        from openclaw.tg_notify import send_message
        send_message(f"🚫 已拒絕 — {row['target_rule']}（{proposal_id[:8]}…）", chat_id=os.environ.get("TELEGRAM_CHAT_ID", "-1003772422881"))
    except Exception:
        pass
    return HTMLResponse("<h2>🚫 提案已拒絕</h2><p>可關閉此頁面。</p>")
