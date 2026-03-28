"""drawdown_guard.py — Drawdown and deep suspend guard adapters."""
from __future__ import annotations

from openclaw.drawdown_guard import (
    apply_drawdown_actions,
    evaluate_deep_suspend_guard,
    evaluate_drawdown_guard,
)
from openclaw.guards.base import Guard, GuardContext, GuardResult


class DrawdownGuard(Guard):
    """Evaluate drawdown risk mode and update context."""

    def evaluate(self, ctx: GuardContext) -> GuardResult:
        drawdown_decision = evaluate_drawdown_guard(ctx.conn, ctx.drawdown_policy)
        return GuardResult(
            passed=True,
            metadata={"check_type": "drawdown"},
            context_updates={"drawdown_decision": drawdown_decision},
        )


class DeepSuspendGuard(Guard):
    """Check for deep suspend (consecutive monthly losses)."""

    def evaluate(self, ctx: GuardContext) -> GuardResult:
        deep_decision = evaluate_deep_suspend_guard(ctx.conn, ctx.drawdown_policy)
        if deep_decision.risk_mode == "deep_suspend":
            apply_drawdown_actions(ctx.conn, deep_decision)
            return GuardResult(
                passed=False,
                reject_code=deep_decision.reason_code,
                reason="deep_suspend: consecutive monthly losses",
                metadata={"check_type": "deep_suspend_guard"},
            )
        return GuardResult(
            passed=True,
            metadata={"check_type": "deep_suspend_guard"},
        )
