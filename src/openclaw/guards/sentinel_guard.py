"""sentinel_guard.py — Sentinel pre/post trade check guard adapters."""
from __future__ import annotations

import json

from openclaw.guards.base import Guard, GuardContext, GuardResult
from openclaw.sentinel import (
    is_hard_block,
    pm_veto,
    sentinel_post_risk_check,
    sentinel_pre_trade_check,
)


class SentinelPreTradeGuard(Guard):
    """Hard circuit-breakers — pre-trade sentinel check."""

    def evaluate(self, ctx: GuardContext) -> GuardResult:
        verdict = sentinel_pre_trade_check(
            system_state=ctx.system_state,
            drawdown=(
                ctx.drawdown_decision
                if ctx.drawdown_decision and ctx.drawdown_decision.risk_mode == "suspended"
                else None
            ),
            budget_status=ctx.budget_status,
            budget_used_pct=ctx.budget_used_pct,
            max_db_write_p99_ms=200,
        )

        metadata = {
            "check_type": "sentinel_pre_trade",
            "reason_code": verdict.reason_code,
            "hard_blocked": verdict.hard_blocked,
            "detail": verdict.detail,
        }

        if is_hard_block(verdict) or not verdict.allowed:
            return GuardResult(
                passed=False,
                reject_code=verdict.reason_code,
                reason="sentinel pre-trade block",
                metadata=metadata,
                context_updates={"sentinel_verdict": verdict},
            )
        return GuardResult(
            passed=True,
            metadata=metadata,
            context_updates={"sentinel_verdict": verdict},
        )


class PMVetoGuard(Guard):
    """PM discretionary veto check (soft layer)."""

    def evaluate(self, ctx: GuardContext) -> GuardResult:
        verdict = pm_veto(pm_approved=ctx.pm_approved)
        metadata = {
            "check_type": "pm_veto",
            "reason_code": verdict.reason_code,
        }
        if not verdict.allowed:
            return GuardResult(
                passed=False,
                reject_code=verdict.reason_code,
                reason="PM veto",
                metadata=metadata,
            )
        return GuardResult(passed=True, metadata=metadata)


class SentinelPostRiskGuard(Guard):
    """Post-risk sentinel check (after candidate exists)."""

    def evaluate(self, ctx: GuardContext) -> GuardResult:
        if ctx.order_candidate is None:
            return GuardResult(passed=True, metadata={"check_type": "sentinel_post_risk"})

        post_verdict = sentinel_post_risk_check(
            system_state=ctx.system_state,
            candidate=ctx.order_candidate,
        )

        metadata = {
            "check_type": "sentinel_post_risk",
            "reason_code": post_verdict.reason_code,
            "hard_blocked": post_verdict.hard_blocked,
            "detail": post_verdict.detail,
        }

        if is_hard_block(post_verdict) or not post_verdict.allowed:
            return GuardResult(
                passed=False,
                reject_code=post_verdict.reason_code,
                reason="sentinel post-risk block",
                metadata=metadata,
            )
        return GuardResult(passed=True, metadata=metadata)
