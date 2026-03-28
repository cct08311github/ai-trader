"""sentinel_guard.py — Sentinel pre/post trade check guard adapters."""
from __future__ import annotations

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

        if is_hard_block(verdict) or not verdict.allowed:
            return GuardResult(
                passed=False,
                reject_code=verdict.reason_code,
                reason="sentinel pre-trade hard block",
                context_updates={"sentinel_verdict": verdict},
            )
        return GuardResult(
            passed=True,
            context_updates={"sentinel_verdict": verdict},
        )


class PMVetoGuard(Guard):
    """PM discretionary veto check (soft layer)."""

    def evaluate(self, ctx: GuardContext) -> GuardResult:
        verdict = pm_veto(pm_approved=ctx.pm_approved)
        if not verdict.allowed:
            return GuardResult(
                passed=False,
                reject_code=verdict.reason_code,
                reason="PM veto",
            )
        return GuardResult(passed=True)


class SentinelPostRiskGuard(Guard):
    """Post-risk sentinel check (after candidate exists)."""

    def evaluate(self, ctx: GuardContext) -> GuardResult:
        if ctx.order_candidate is None:
            return GuardResult(passed=True)

        post_verdict = sentinel_post_risk_check(
            system_state=ctx.system_state,
            candidate=ctx.order_candidate,
        )

        if is_hard_block(post_verdict) or not post_verdict.allowed:
            return GuardResult(
                passed=False,
                reject_code=post_verdict.reason_code,
                reason="sentinel post-risk hard block",
            )
        return GuardResult(passed=True)
