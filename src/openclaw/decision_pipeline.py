from __future__ import annotations

import json
import sqlite3
from typing import Any, Callable, Dict

from openclaw.llm_observability import LLMTrace, insert_llm_trace
from openclaw.model_registry import resolve_pinned_model_id
from openclaw.news_guard import build_news_sentiment_prompt, sanitize_external_news_text
from openclaw.pm_debate import build_debate_prompt


LLMCaller = Callable[[str, str], Dict[str, Any]]


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


def run_news_sentiment_with_guard(
    conn: sqlite3.Connection,
    *,
    model: str,
    raw_news_text: str,
    llm_call: LLMCaller,
    decision_id: str | None = None,
) -> Dict[str, Any]:
    pinned_model = resolve_pinned_model_id(model)
    guard = sanitize_external_news_text(raw_news_text)
    if not guard.safe:
        # Observability MUST still record a trace (blocked call).
        insert_llm_trace(
            conn,
            LLMTrace(
                component="news_guard",
                model=model,
                prompt_text="",
                response_text=json.dumps({"blocked": True, "reason": guard.reason}, ensure_ascii=True),
                input_tokens=0,
                output_tokens=0,
                latency_ms=0,
                confidence=None,
                decision_id=decision_id,
                metadata={"stage": "news_sentiment", "blocked": True, "blocked_reason": guard.reason, "pinned_model": pinned_model},
            ),
        )
        return {"blocked": True, "reason": guard.reason}

    prompt = build_news_sentiment_prompt(guard.sanitized_text)
    result = llm_call(pinned_model, prompt)
    insert_llm_trace(
        conn,
        LLMTrace(
            component="news_guard",
            model=model,
            prompt_text=prompt,
            response_text=json.dumps(result, ensure_ascii=True),
            input_tokens=_safe_int(result.get("input_tokens"), 0),
            output_tokens=_safe_int(result.get("output_tokens"), 0),
            latency_ms=_safe_int(result.get("latency_ms"), 0),
            confidence=_safe_float(result.get("confidence"), 0.0),
            decision_id=decision_id,
            metadata={"stage": "news_sentiment", "pinned_model": pinned_model},
        ),
    )
    return result


def run_pm_debate(
    conn: sqlite3.Connection,
    *,
    model: str,
    context: Dict[str, Any],
    llm_call: LLMCaller,
    decision_id: str | None = None,
) -> Dict[str, Any]:
    pinned_model = resolve_pinned_model_id(model)
    prompt = build_debate_prompt(context)
    result = llm_call(pinned_model, prompt)
    insert_llm_trace(
        conn,
        LLMTrace(
            component="pm",
            model=model,
            prompt_text=prompt,
            response_text=json.dumps(result, ensure_ascii=True),
            input_tokens=_safe_int(result.get("input_tokens"), 0),
            output_tokens=_safe_int(result.get("output_tokens"), 0),
            latency_ms=_safe_int(result.get("latency_ms"), 0),
            confidence=_safe_float(result.get("confidence"), 0.0),
            decision_id=decision_id,
            metadata={"stage": "bull_bear_debate", "pinned_model": pinned_model},
        ),
    )
    return result



def make_decision(*args, **kwargs):
    """Backward-compatible placeholder for legacy tests.

    The v4 decision pipeline exposes higher-level entrypoints; some early unit
    tests only require this symbol to exist.
    """

    raise NotImplementedError("make_decision is not implemented in this project")
