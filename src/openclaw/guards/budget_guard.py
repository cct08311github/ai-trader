"""budget_guard.py — Token budget guard adapter."""
from __future__ import annotations

from openclaw.guards.base import Guard, GuardContext, GuardResult
from openclaw.token_budget import evaluate_budget, load_budget_policy, emit_budget_event


class BudgetGuard(Guard):
    """Evaluate token budget and update context with status."""

    def evaluate(self, ctx: GuardContext) -> GuardResult:
        budget_policy = load_budget_policy(ctx.budget_policy_path)
        budget_status, budget_used_pct, budget_tier = evaluate_budget(
            ctx.conn, budget_policy
        )

        # Emit budget event if at threshold
        if budget_tier and budget_tier.threshold_pct <= budget_used_pct:
            emit_budget_event(ctx.conn, tier=budget_tier, used_pct=budget_used_pct)

        return GuardResult(
            passed=True,
            metadata={"check_type": "budget"},
            context_updates={
                "budget_status": budget_status,
                "budget_used_pct": budget_used_pct,
                "budget_tier": budget_tier,
            },
        )
