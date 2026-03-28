"""base.py — Guard protocol, context, and chain runner.

Defines the abstract interface that all guards must implement,
the immutable context object passed through the chain, and the
``GuardChain`` orchestrator.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


@dataclass
class GuardContext:
    """Immutable context passed through the guard chain.

    Contains all the data that guards might need to make their decision.
    Individual guards read only what they need and ignore the rest.
    """
    conn: Any  # sqlite3.Connection
    system_state: Any  # risk_engine.SystemState
    order_candidate: Any  # Optional[risk_engine.OrderCandidate]
    budget_policy_path: str = ""
    drawdown_policy: Any = None  # DrawdownPolicy
    pm_context: Dict[str, Any] = field(default_factory=dict)
    pm_approved: bool = False
    llm_call: Optional[Callable] = None
    decision_id: str = ""
    # Accumulated state from previous guards
    budget_status: str = "ok"
    budget_used_pct: float = 0.0
    budget_tier: Any = None
    drawdown_decision: Any = None
    sentinel_verdict: Any = None


@dataclass
class GuardResult:
    """Result of a single guard evaluation."""
    passed: bool
    reject_code: str = ""
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Guards can update the context for downstream guards
    context_updates: Dict[str, Any] = field(default_factory=dict)


class Guard(ABC):
    """Abstract base class for pipeline guards."""

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    def evaluate(self, ctx: GuardContext) -> GuardResult:
        """Evaluate this guard.  Return GuardResult with passed=False to reject."""
        ...


class GuardChain:
    """Evaluates a sequence of guards, short-circuiting on first rejection.

    Parameters
    ----------
    guards : sequence of Guard
        Guards to evaluate in order.
    """

    def __init__(self, guards: Sequence[Guard]) -> None:
        self._guards = list(guards)

    @property
    def guards(self) -> List[Guard]:
        return list(self._guards)

    def evaluate(self, ctx: GuardContext) -> Tuple[bool, str, GuardContext]:
        """Run all guards in sequence.

        Returns (approved, reject_code_or_APPROVED, final_context).
        Context is updated with each guard's context_updates.
        """
        for guard in self._guards:
            result = guard.evaluate(ctx)

            # Apply context updates from this guard
            for key, value in result.context_updates.items():
                if hasattr(ctx, key):
                    object.__setattr__(ctx, key, value)

            logger.debug(
                "Guard %s: passed=%s code=%s",
                guard.name, result.passed, result.reject_code,
            )

            if not result.passed:
                return False, result.reject_code, ctx

        return True, "DECISION_APPROVED", ctx
