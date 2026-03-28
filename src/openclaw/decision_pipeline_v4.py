from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple

from openclaw.drawdown_guard import (
    DrawdownDecision,
    DrawdownPolicy,
    apply_drawdown_actions,
    evaluate_deep_suspend_guard,
    evaluate_drawdown_guard,
)
from openclaw.llm_observability import LLMTrace, insert_llm_trace
from openclaw.model_registry import resolve_pinned_model_id
from openclaw.news_guard import build_news_sentiment_prompt, sanitize_external_news_text
from openclaw.pm_debate import build_debate_prompt, parse_debate_response
from openclaw.risk_engine import OrderCandidate, SystemState
from openclaw.system_switch import check_system_switch

from openclaw.sentinel import SentinelVerdict, sentinel_pre_trade_check, sentinel_post_risk_check, pm_veto, is_hard_block
from openclaw.token_budget import BudgetPolicy, evaluate_budget, load_budget_policy, emit_budget_event


LLMCaller = Callable[[str, str], Dict[str, Any]]

logger = logging.getLogger(__name__)



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


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _insert_decision_record(
    conn: sqlite3.Connection,
    decision_id: str,
    symbol: str,
    direction: str,
    quantity: int,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    sentinel_verdict: SentinelVerdict,
    budget_status: str,
    budget_used_pct: float,
    drawdown_decision: DrawdownDecision,
    pm_approved: bool,
) -> None:
    """Insert decision record into decisions table (v4 schema)."""
    
    if not _table_exists(conn, "decisions"):
        return
    
    conn.execute(
        """
        INSERT INTO decisions(
            decision_id, created_at, symbol, direction, quantity, entry_price,
            stop_loss, take_profit, reason_json, sentinel_blocked, pm_veto,
            budget_status, sentinel_reason_code, drawdown_risk_mode,
            drawdown_reason_code
        ) VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            decision_id, symbol, direction, quantity, entry_price,
            stop_loss, take_profit, json.dumps({}), sentinel_verdict.hard_blocked,
            not pm_approved, budget_status, sentinel_verdict.reason_code,
            drawdown_decision.risk_mode, drawdown_decision.reason_code
        )
    )


def _insert_risk_check(
    conn: sqlite3.Connection,
    decision_id: str,
    check_type: str,
    check_passed: bool,
    details: str,
) -> None:
    """Insert risk check record (v4 schema)."""
    
    if not _table_exists(conn, "risk_checks"):
        return
    
    conn.execute(
        """
        INSERT INTO risk_checks(
            risk_check_id, decision_id, check_type, check_passed, details, created_at
        ) VALUES (?, ?, ?, ?, ?, datetime('now'))
        """,
        (str(uuid.uuid4()), decision_id, check_type, 1 if check_passed else 0, details)
    )


def _default_guard_chain():
    """Build the default guard chain matching the original v4 pipeline order."""
    from openclaw.guards.base import GuardChain
    from openclaw.guards.system_switch_guard import SystemSwitchGuard
    from openclaw.guards.budget_guard import BudgetGuard
    from openclaw.guards.drawdown_guard import DrawdownGuard, DeepSuspendGuard
    from openclaw.guards.sentinel_guard import (
        SentinelPreTradeGuard,
        PMVetoGuard,
        SentinelPostRiskGuard,
    )
    return GuardChain([
        SystemSwitchGuard(),       # Step 0: master switch
        BudgetGuard(),             # Step 1: budget evaluation
        DrawdownGuard(),           # Step 2: drawdown risk mode
        DeepSuspendGuard(),        # Step 2b: deep suspend
        SentinelPreTradeGuard(),   # Step 3-4: hard circuit-breakers
        PMVetoGuard(),             # Step 5: PM veto (soft)
        SentinelPostRiskGuard(),   # Step 6: post-risk check
    ])


def run_decision_with_sentinel(
    conn: sqlite3.Connection,
    *,
    system_state: SystemState,
    order_candidate: Optional[OrderCandidate],
    budget_policy_path: str,
    drawdown_policy: DrawdownPolicy,
    pm_context: Dict[str, Any],
    pm_approved: bool = False,
    llm_call: LLMCaller,
    decision_id: Optional[str] = None,
    guard_chain=None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Complete decision pipeline with Sentinel integration (v4 #1).

    Uses a pluggable GuardChain (Chain of Responsibility pattern).
    Each guard evaluates independently; the first rejection short-circuits.

    Returns: (allowed, reason_code, decision_record)
    """
    from openclaw.guards.base import GuardContext

    if decision_id is None:
        decision_id = f"dec_{uuid.uuid4().hex[:16]}"

    chain = guard_chain or _default_guard_chain()

    ctx = GuardContext(
        conn=conn,
        system_state=system_state,
        order_candidate=order_candidate,
        budget_policy_path=budget_policy_path,
        drawdown_policy=drawdown_policy,
        pm_context=pm_context,
        pm_approved=pm_approved,
        llm_call=llm_call,
        decision_id=decision_id,
    )

    approved, reject_code, ctx = chain.evaluate(ctx)

    # ── Audit trail: write risk_check records from collected results ─
    for guard, result in getattr(chain, "last_results", []):
        check_type = result.metadata.get("check_type", guard.name)
        _insert_risk_check(conn, decision_id, check_type, result.passed,
                           json.dumps(result.metadata))

    # ── Decision record (audit trail) ──────────────────────────────
    sentinel_verdict = getattr(ctx, "sentinel_verdict", None) or SentinelVerdict(
        allowed=approved, hard_blocked=False, reason_code=reject_code, detail={},
    )
    drawdown_decision = getattr(ctx, "drawdown_decision", None) or DrawdownDecision(
        risk_mode="normal", reason_code="NORMAL", drawdown=0.0, losing_streak_days=0,
    )
    budget_status = getattr(ctx, "budget_status", "ok")
    budget_used_pct = getattr(ctx, "budget_used_pct", 0.0)

    if order_candidate:
        _insert_decision_record(
            conn, decision_id, order_candidate.symbol, order_candidate.side,
            order_candidate.qty, order_candidate.price,
            getattr(order_candidate, "stop_loss", 0.0),
            getattr(order_candidate, "take_profit", 0.0),
            sentinel_verdict, budget_status, budget_used_pct,
            drawdown_decision, pm_approved,
        )

    if not approved:
        return False, reject_code, None

    decision_record = {
        "decision_id": decision_id,
        "allowed": True,
        "sentinel_verdict": sentinel_verdict,
        "budget_status": budget_status,
        "budget_used_pct": budget_used_pct,
        "drawdown_decision": drawdown_decision,
        "pm_approved": pm_approved,
        "order_candidate": order_candidate.__dict__ if order_candidate else None,
    }

    return True, "DECISION_APPROVED", decision_record


# Keep original functions for backward compatibility
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
                metadata={
                    "stage": "news_sentiment",
                    "blocked": True,
                    "blocked_reason": guard.reason,
                    "pinned_model": pinned_model,
                    "prompt_version": "decision_pipeline_v4/news_sentiment/v1",
                    "model_version": pinned_model,
                    "input_snapshot": {"news_len": len(raw_news_text)},
                },
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
            metadata={
                "stage": "news_sentiment",
                "pinned_model": pinned_model,
                "prompt_version": "decision_pipeline_v4/news_sentiment/v1",
                "model_version": pinned_model,
                "input_snapshot": {"news_len": len(raw_news_text)},
            },
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
            metadata={
                "stage": "bull_bear_debate",
                "pinned_model": pinned_model,
                "prompt_version": "decision_pipeline_v4/pm_debate/v1",
                "model_version": pinned_model,
                "input_snapshot": context,
            },
        ),
    )
    # Validate response shape (v4 #9)
    try:
        parsed = parse_debate_response(result)
        # Ensure adjudication is present (optional)
        if parsed.adjudication is not None:
            result["adjudication"] = parsed.adjudication
    except Exception as e:
        logger.warning("PM debate response validation failed: %s", e)
    return result
