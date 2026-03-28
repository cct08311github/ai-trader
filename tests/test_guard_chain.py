"""Tests for the Guard Chain pattern (Phase 4)."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from openclaw.guards.base import Guard, GuardChain, GuardContext, GuardResult


# ── Test helpers ────────────────────────────────────────────────────────────


class AlwaysPassGuard(Guard):
    def evaluate(self, ctx: GuardContext) -> GuardResult:
        return GuardResult(passed=True)


class AlwaysRejectGuard(Guard):
    def evaluate(self, ctx: GuardContext) -> GuardResult:
        return GuardResult(passed=False, reject_code="TEST_REJECT", reason="test")


class ContextUpdatingGuard(Guard):
    def evaluate(self, ctx: GuardContext) -> GuardResult:
        return GuardResult(
            passed=True,
            context_updates={"budget_status": "warn", "budget_used_pct": 0.75},
        )


class ContextReadingGuard(Guard):
    """Records the budget_status it sees for assertion."""
    seen_status: str = ""

    def evaluate(self, ctx: GuardContext) -> GuardResult:
        self.seen_status = ctx.budget_status
        return GuardResult(passed=True)


def _make_ctx(**overrides) -> GuardContext:
    defaults = dict(
        conn=None,
        system_state=None,
        order_candidate=None,
    )
    defaults.update(overrides)
    return GuardContext(**defaults)


# ── Tests ───────────────────────────────────────────────────────────────────


class TestGuardChain:
    def test_all_pass(self):
        chain = GuardChain([AlwaysPassGuard(), AlwaysPassGuard()])
        approved, code, ctx = chain.evaluate(_make_ctx())
        assert approved is True
        assert code == "DECISION_APPROVED"

    def test_first_reject_short_circuits(self):
        chain = GuardChain([AlwaysRejectGuard(), AlwaysPassGuard()])
        approved, code, ctx = chain.evaluate(_make_ctx())
        assert approved is False
        assert code == "TEST_REJECT"

    def test_second_reject(self):
        chain = GuardChain([AlwaysPassGuard(), AlwaysRejectGuard()])
        approved, code, ctx = chain.evaluate(_make_ctx())
        assert approved is False
        assert code == "TEST_REJECT"

    def test_empty_chain_approves(self):
        chain = GuardChain([])
        approved, code, ctx = chain.evaluate(_make_ctx())
        assert approved is True

    def test_context_updates_propagate(self):
        reader = ContextReadingGuard()
        chain = GuardChain([ContextUpdatingGuard(), reader])
        approved, code, ctx = chain.evaluate(_make_ctx())
        assert approved is True
        assert reader.seen_status == "warn"
        assert ctx.budget_used_pct == 0.75

    def test_guard_names(self):
        chain = GuardChain([AlwaysPassGuard(), AlwaysRejectGuard()])
        names = [g.name for g in chain.guards]
        assert names == ["AlwaysPassGuard", "AlwaysRejectGuard"]

    def test_guards_list_is_copy(self):
        chain = GuardChain([AlwaysPassGuard()])
        chain.guards.append(AlwaysRejectGuard())  # mutate the copy
        assert len(chain._guards) == 1  # original unchanged
