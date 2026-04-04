"""pm.py — 每日 PM 審核 API

Endpoints:
  GET  /api/pm/status          → 今日審核狀態
  GET  /api/pm/history         → 歷史審核紀錄（分頁）
  POST /api/pm/approve         → 人工授權今日交易
  POST /api/pm/reject          → 人工封鎖今日交易
  POST /api/pm/review          → 觸發 LLM 審核（需 llm_call 已配置）
"""

from __future__ import annotations

import sys
import os

import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Ensure src/ is importable
_SRC = os.path.join(os.path.dirname(__file__), "../../../../src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from openclaw.daily_pm_review import (
    get_daily_pm_state,
    manual_override,
    run_daily_pm_review,
    build_daily_context,
)

router = APIRouter(prefix="/api/pm", tags=["pm"])
logger = logging.getLogger("pm_api")

_PM_REVIEWS_DDL = """
CREATE TABLE IF NOT EXISTS pm_reviews (
    review_id TEXT PRIMARY KEY,
    review_date TEXT NOT NULL,
    approved INTEGER NOT NULL,
    confidence REAL NOT NULL,
    source TEXT NOT NULL,
    reason TEXT,
    recommended_action TEXT,
    bull_case TEXT,
    bear_case TEXT,
    neutral_case TEXT,
    consensus_points TEXT,
    divergence_points TEXT,
    reviewed_at INTEGER NOT NULL,
    llm_trace_id TEXT
);
"""
_PM_REVIEWS_IDX = "CREATE INDEX IF NOT EXISTS idx_pm_reviews_date ON pm_reviews(review_date DESC);"


def _ensure_pm_reviews_table(conn) -> None:
    """Create pm_reviews table if it doesn't exist."""
    conn.execute(_PM_REVIEWS_DDL)
    conn.execute(_PM_REVIEWS_IDX)


@router.get("/status")
def pm_status():
    """Return today's PM review state."""
    return {"status": "ok", "data": get_daily_pm_state()}


@router.get("/history")
def pm_history(
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Return paginated PM review history, newest first."""
    try:
        from app.db import get_conn
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM pm_reviews ORDER BY review_date DESC, reviewed_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM pm_reviews").fetchone()[0]
            return {
                "status": "ok",
                "data": [dict(r) for r in rows],
                "pagination": {"total": total, "limit": limit, "offset": offset},
            }
    except Exception as e:
        if "no such table" in str(e).lower():
            return {"status": "ok", "data": [], "pagination": {"total": 0, "limit": limit, "offset": offset}}
        raise


class OverrideRequest(BaseModel):
    reason: str = ""


@router.post("/approve")
def pm_approve(body: OverrideRequest = OverrideRequest()):
    """Human operator approves today's trading."""
    state = manual_override(approved=True, reason=body.reason or "人工授權")
    _write_pm_review_to_db(state)
    return {"status": "ok", "data": state}


@router.post("/reject")
def pm_reject(body: OverrideRequest = OverrideRequest()):
    """Human operator rejects today's trading."""
    state = manual_override(approved=False, reason=body.reason or "人工封鎖")
    _write_pm_review_to_db(state)
    return {"status": "ok", "data": state}


def _get_llm_call():
    """Return minimax_call."""
    from openclaw.llm_minimax import minimax_call
    return minimax_call


def _write_pm_review_to_db(state: dict, llm_trace_id: str | None = None) -> None:
    """Persist PM review to pm_reviews table for durable history."""
    import json, time, uuid
    if state.get("source") not in ("llm", "manual"):
        return
    try:
        from app.db import get_conn_rw
        with get_conn_rw() as conn:
            _ensure_pm_reviews_table(conn)
            review_date = state.get("date", "")
            review_id = f"pm_{review_date}_{uuid.uuid4().hex[:8]}"
            now_ms = int(time.time() * 1000)
            conn.execute(
                """INSERT INTO pm_reviews
                   (review_id, review_date, approved, confidence, source,
                    reason, recommended_action, bull_case, bear_case, neutral_case,
                    consensus_points, divergence_points, reviewed_at, llm_trace_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    review_id,
                    review_date,
                    1 if state.get("approved") else 0,
                    state.get("confidence", 0.0),
                    state.get("source", ""),
                    state.get("reason", ""),
                    state.get("recommended_action", ""),
                    state.get("bull_case", ""),
                    state.get("bear_case", ""),
                    state.get("neutral_case", ""),
                    json.dumps(state.get("consensus_points", []), ensure_ascii=False),
                    json.dumps(state.get("divergence_points", []), ensure_ascii=False),
                    now_ms,
                    llm_trace_id,
                ),
            )
    except Exception:
        logger.exception("Failed to persist PM review to pm_reviews")


def _write_debate_to_db(state: dict) -> None:
    """Write PM review result to episodic_memory so Strategy page can display it."""
    import json, time, uuid
    if state.get("source") not in ("llm", "manual"):
        return
    try:
        from app.db import get_conn_rw
        with get_conn_rw() as conn:
            episode_id = f"pm_review_{state.get('date', 'unknown')}_{uuid.uuid4().hex[:6]}"
            now = int(time.time())
            content = {
                "bull_case":   state.get("bull_case", ""),
                "bear_case":   state.get("bear_case", ""),
                "neutral_case": state.get("neutral_case", ""),
                "consensus_points":  state.get("consensus_points", []),
                "divergence_points": state.get("divergence_points", []),
                "recommended_action": state.get("recommended_action", ""),
                "confidence":  state.get("confidence", 0),
                "approved":    state.get("approved", False),
                "source":      state.get("source", ""),
            }
            conn.execute(
                """INSERT OR REPLACE INTO episodic_memory
                   (episode_id, episode_type, summary, content_json, decay_score,
                    is_archived, created_at, updated_at)
                   VALUES (?, 'pm_review', ?, ?, 1.0, 0, ?, ?)""",
                (
                    episode_id,
                    state.get("reason", "")[:500],
                    json.dumps(content, ensure_ascii=False),
                    now, now,
                )
            )
    except Exception:
        pass  # Never fail the API response over logging


@router.post("/review")
def pm_review():
    """Trigger LLM-based daily review via Gemini.

    Requires MINIMAX_API_KEY in environment or .env.
    If not set, marks state as pending_manual (manual override required).
    """
    try:
        from app.db import get_conn
        with get_conn() as conn:
            context = build_daily_context(conn)
    except Exception:
        context = build_daily_context(conn=None)

    # Read model at request time (not module load) so env vars from run.sh are visible
    from openclaw.llm_minimax import _DEFAULT_MODEL
    model = os.environ.get("PM_LLM_MODEL", _DEFAULT_MODEL)
    llm_call = _get_llm_call()
    try:
        state = run_daily_pm_review(context=context, llm_call=llm_call, model=model)
    except Exception as e:
        logger.error("PM review LLM 呼叫失敗: %s", e, exc_info=True)
        return JSONResponse(
            status_code=503,
            content={"error": "LLM 暫時不可用，請稍後重試", "detail": str(e)},
        )

    # Persist to episodic_memory so Strategy page debate section shows history
    _write_debate_to_db(state)

    # Write prompt + raw response to llm_traces for full transparency
    _write_llm_trace(state, model)

    # Persist to pm_reviews for durable history / API queries
    _write_pm_review_to_db(state)

    # Telegram 通知 PM review 結果（不阻塞 API 回應）
    _notify_pm_review(state)

    return {"status": "ok", "data": state}


def _notify_pm_review(state: dict) -> None:
    """PM review 結果送 Telegram（不拋例外）。"""
    try:
        from openclaw.tg_notify import send_message
        approved = state.get("approved", False)
        conf = state.get("confidence", 0)
        reason = state.get("reason", "")
        bull = state.get("bull_case", "")
        bear = state.get("bear_case", "")
        icon = "✅" if approved else "🚫"
        msg = (
            f"{icon} <b>[每日 PM 審核]</b> {state.get('date', '')}\n"
            f"決定：<b>{'授權交易' if approved else '封鎖交易'}</b>（信心 {conf:.0%}）\n"
            f"理由：{reason}\n"
        )
        if bull:
            msg += f"\n📈 多方：{bull}"
        if bear:
            msg += f"\n📉 空方：{bear}"
        send_message(msg)
    except Exception:
        pass


def _write_llm_trace(state: dict, model: str) -> None:
    """Write prompt and raw Gemini response to llm_traces for audit."""
    import json, time, uuid
    prompt = state.pop("_prompt", None)
    raw = state.pop("_raw_response", None)
    latency = state.pop("_latency_ms", None)
    state.pop("_model", None)
    if not prompt or not raw:
        return
    try:
        from app.db import get_conn_rw
        with get_conn_rw() as conn:
            conn.execute(
                """INSERT INTO llm_traces
                   (trace_id, agent, model, prompt, response, latency_ms, created_at)
                   VALUES (?, 'pm_review', ?, ?, ?, ?, ?)""",
                (
                    f"pm_{uuid.uuid4().hex[:12]}",
                    model,
                    prompt,
                    raw,
                    latency,
                    int(time.time()),
                )
            )
    except Exception:
        pass
