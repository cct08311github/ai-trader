"""pm.py — 每日 PM 審核 API

Endpoints:
  GET  /api/pm/status          → 今日審核狀態
  POST /api/pm/approve         → 人工授權今日交易
  POST /api/pm/reject          → 人工封鎖今日交易
  POST /api/pm/review          → 觸發 LLM 審核（需 llm_call 已配置）
"""

from __future__ import annotations

import sys
import os

from fastapi import APIRouter
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


@router.get("/status")
def pm_status():
    """Return today's PM review state."""
    return {"status": "ok", "data": get_daily_pm_state()}


class OverrideRequest(BaseModel):
    reason: str = ""


@router.post("/approve")
def pm_approve(body: OverrideRequest = OverrideRequest()):
    """Human operator approves today's trading."""
    state = manual_override(approved=True, reason=body.reason or "人工授權")
    return {"status": "ok", "data": state}


@router.post("/reject")
def pm_reject(body: OverrideRequest = OverrideRequest()):
    """Human operator rejects today's trading."""
    state = manual_override(approved=False, reason=body.reason or "人工封鎖")
    return {"status": "ok", "data": state}


@router.post("/review")
def pm_review():
    """Trigger LLM-based daily review.

    In production, connect to real LLM by replacing llm_call.
    Currently runs without LLM (sets state to pending_manual).
    """
    try:
        from app.db import get_conn
        with get_conn() as conn:
            context = build_daily_context(conn)
    except Exception:
        context = build_daily_context(conn=None)

    # llm_call=None → marks as pending_manual (operator must override)
    state = run_daily_pm_review(context=context, llm_call=None)
    return {"status": "ok", "data": state}
