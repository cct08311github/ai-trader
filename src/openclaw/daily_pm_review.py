"""daily_pm_review.py — 每日盤前 PM 審核機制

設計原則：
- 每日交易前執行一次（盤前 08:30 前）
- LLM 做多空辯論，輸出 approved / rejected
- 結果存入 config/daily_pm_state.json，有效期至當日 23:59
- 支援人工覆蓋（manual override）
- 未審核 / 昨日過期 → 預設封鎖（fail-safe）
- simulation 模式可跳過（由 limits 控制）
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, Optional

_log = logging.getLogger("daily_pm_review")

_STATE_PATH = os.path.join(os.path.dirname(__file__), "../../config/daily_pm_state.json")

# Keywords that indicate the LLM recommends trading today
_BULLISH_KW = {"買", "加碼", "buy", "long", "積極", "正向", "樂觀", "看多"}
# Keywords that indicate the LLM recommends avoiding trading today
_BEARISH_KW = {"觀望", "減碼", "賣", "sell", "short", "保守", "停止", "暫停", "等待", "避險"}


def _today() -> str:
    return date.today().isoformat()


def get_daily_pm_approval() -> bool:
    """Return today's PM approval status. Safe default: False (blocked)."""
    try:
        with open(_STATE_PATH, "r") as f:
            state = json.load(f)
        return state.get("date") == _today() and bool(state.get("approved", False))
    except Exception:
        return False


def get_daily_pm_state() -> Dict[str, Any]:
    """Return full state dict for API/UI consumption."""
    try:
        with open(_STATE_PATH, "r") as f:
            state = json.load(f)
        state["is_today"] = state.get("date") == _today()
        return state
    except Exception:
        return {
            "date": None,
            "approved": False,
            "is_today": False,
            "confidence": 0.0,
            "reason": "尚未執行今日 PM 審核",
            "recommended_action": None,
            "source": "none",
            "reviewed_at": None,
        }


def _save_state(state: Dict[str, Any]) -> None:
    with open(_STATE_PATH, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def build_daily_context(conn=None) -> Dict[str, Any]:
    """Build market/portfolio context for PM review.

    Tries to pull real data from DB. Falls back to empty context gracefully.
    """
    context: Dict[str, Any] = {
        "date": _today(),
        "recent_trades": [],
        "recent_pnl": [],
        "note": "",
    }

    if conn is None:
        return context

    try:
        rows = conn.execute(
            """SELECT symbol, action, quantity, price, pnl, timestamp
               FROM trades ORDER BY timestamp DESC LIMIT 20"""
        ).fetchall()
        context["recent_trades"] = [dict(r) for r in rows]
    except Exception:
        pass

    try:
        rows = conn.execute(
            """SELECT DATE(timestamp) as trade_date, SUM(pnl) as daily_pnl
               FROM trades WHERE pnl IS NOT NULL
               GROUP BY trade_date ORDER BY trade_date DESC LIMIT 7"""
        ).fetchall()
        context["recent_pnl"] = [dict(r) for r in rows]
    except Exception:
        pass

    return context


def run_daily_pm_review(
    *,
    context: Optional[Dict[str, Any]] = None,
    llm_call: Optional[Callable[[str, str], Dict[str, Any]]] = None,
    model: str = "gpt-4",
) -> Dict[str, Any]:
    """Run LLM-based daily PM review.

    Args:
        context: Market/portfolio context dict (from build_daily_context).
        llm_call: Callable(model, prompt) -> dict. If None, review is skipped
                  and state is set to pending (awaiting manual override).
        model: LLM model ID to use.

    Returns:
        State dict written to disk.
    """
    today = _today()

    if llm_call is None or context is None:
        state = {
            "date": today,
            "approved": False,
            "confidence": 0.0,
            "reason": "LLM 未配置，請使用人工覆蓋",
            "recommended_action": "pending_manual",
            "bull_case": "",
            "bear_case": "",
            "neutral_case": "",
            "consensus_points": [],
            "divergence_points": [],
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "source": "pending",
        }
        _save_state(state)
        return state

    from openclaw.pm_debate import build_debate_prompt, parse_debate_response

    prompt = build_debate_prompt(context)
    _retry_waits = [5, 15, 30]
    last_exc: Exception | None = None
    result = None
    for attempt, wait in enumerate([0] + _retry_waits, start=1):
        if wait:
            _log.warning("PM review LLM 重試 %d/%d，等待 %ds…", attempt, len(_retry_waits) + 1, wait)
            time.sleep(wait)
        try:
            result = llm_call(model, prompt)
            break
        except Exception as exc:
            _log.error("PM review LLM 呼叫失敗（第 %d 次）: %s", attempt, exc)
            last_exc = exc
    if result is None:
        raise last_exc  # type: ignore[misc]

    # Capture transparency metadata BEFORE parse_debate_response processes the dict,
    # since it only reads known fields and _prompt/_raw_response would be discarded.
    _trace = {
        "_prompt": result.get("_prompt"),
        "_raw_response": result.get("_raw_response"),
        "_latency_ms": result.get("_latency_ms"),
        "_model": result.get("_model"),
    }

    parsed = parse_debate_response(result)

    action_lower = parsed.recommended_action.lower()
    if any(kw in action_lower for kw in _BEARISH_KW):
        approved = False
    elif any(kw in action_lower for kw in _BULLISH_KW):
        approved = True
    else:
        # Neutral: approve only above confidence threshold
        approved = parsed.confidence >= 0.65

    state = {
        "date": today,
        "approved": approved,
        "confidence": parsed.confidence,
        "reason": parsed.adjudication or parsed.recommended_action,
        "recommended_action": parsed.recommended_action,
        "bull_case": parsed.bull_case,
        "bear_case": parsed.bear_case,
        "neutral_case": parsed.neutral_case,
        "consensus_points": parsed.consensus_points,
        "divergence_points": parsed.divergence_points,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "source": "llm",
    }
    _save_state(state)  # save clean state without trace data
    state.update(_trace)  # append trace fields for caller to log (not persisted to file)
    return state


def manual_override(*, approved: bool, reason: str = "") -> Dict[str, Any]:
    """Human operator manually approves or rejects today's trading.

    This overrides any LLM result. Intended for:
    - Black swan events (force-reject)
    - LLM unavailable (force-approve if operator deems safe)
    - Pre-market review by human trader
    """
    state = {
        "date": _today(),
        "approved": approved,
        "confidence": 1.0,
        "reason": reason or ("人工授權交易" if approved else "人工封鎖交易"),
        "recommended_action": "manual_override",
        "bull_case": "",
        "bear_case": "",
        "neutral_case": "",
        "consensus_points": [],
        "divergence_points": [],
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "source": "manual",
    }
    _save_state(state)
    return state
