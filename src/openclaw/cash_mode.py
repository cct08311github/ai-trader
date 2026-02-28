"""Active Cash Mode (v4 #20).

Goal
----
Provide a deterministic mechanism to switch the system into *reduce-only* (cash) mode
based on market environment (v4 #14 market_regime).

Integration point
-----------------
`openclaw.risk_engine.SystemState` already supports `reduce_only_mode`.
Risk engine will reject orders that open new positions when reduce-only is enabled.

This module:
- Evaluates a market rating (0..100)
- Applies a hysteresis policy to avoid flapping
- Outputs a CashModeDecision that can be applied to SystemState

See also: docs/compliance_checklist.md (operational controls).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Mapping

from openclaw.market_regime import MarketRegime, MarketRegimeResult
from openclaw.risk_engine import SystemState


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def compute_market_rating(result: MarketRegimeResult) -> float:
    """Compute a simple 0..100 market rating from MarketRegimeResult.

    Heuristic (deterministic):
    - Start at 50
    - Trend contribution (trend_strength) scaled by confidence
    - Volatility penalty

    Note: This score is for *risk posture* only (not alpha forecasting).
    """

    feats: Mapping[str, float] = result.features or {}
    trend = float(feats.get("trend_strength", 0.0))
    vol = float(feats.get("volatility", 0.0))

    # Trend: normalize by ~3% to get strong moves near 1.0.
    trend_norm = _clamp(abs(trend) / 0.03, 0.0, 1.0)
    trend_sign = 1.0 if trend >= 0 else -1.0

    # Volatility: penalty (0..1) around 6% log-return std.
    vol_pen = _clamp(vol / 0.06, 0.0, 1.0)

    base = 50.0
    score = base + 35.0 * trend_sign * trend_norm * float(result.confidence) - 25.0 * vol_pen

    # Regime bias (small):
    if result.regime == MarketRegime.BULL:
        score += 5.0
    elif result.regime == MarketRegime.BEAR:
        score -= 5.0

    if not math.isfinite(score):
        score = 50.0

    return float(max(0.0, min(100.0, score)))


@dataclass(frozen=True)
class CashModePolicy:
    """Policy for entering/exiting cash mode (reduce-only)."""

    enter_below_rating: float = 35.0
    exit_above_rating: float = 55.0

    # Enter cash mode when market regime is bear and confidence is adequate.
    enter_on_bear_regime: bool = True
    bear_min_confidence: float = 0.45

    # Emergency enter cash mode when volatility too high.
    emergency_volatility_threshold: float = 0.07

    @staticmethod
    def default() -> "CashModePolicy":
        return CashModePolicy()


@dataclass(frozen=True)
class CashModeDecision:
    cash_mode: bool
    rating: float
    reason_code: str
    detail: Dict[str, Any]


def evaluate_cash_mode(
    result: MarketRegimeResult,
    *,
    current_cash_mode: bool,
    policy: CashModePolicy | None = None,
) -> CashModeDecision:
    """Evaluate whether the system should be in reduce-only cash mode."""

    pol = policy or CashModePolicy.default()
    rating = compute_market_rating(result)
    feats: Mapping[str, float] = result.features or {}
    vol = float(feats.get("volatility", 0.0))

    # Emergency switch first.
    if vol >= pol.emergency_volatility_threshold:
        return CashModeDecision(
            cash_mode=True,
            rating=rating,
            reason_code="CASHMODE_EMERGENCY_VOLATILITY",
            detail={"volatility": vol, "threshold": pol.emergency_volatility_threshold, "regime": result.regime.value},
        )

    if pol.enter_on_bear_regime and result.regime == MarketRegime.BEAR and float(result.confidence) >= pol.bear_min_confidence:
        return CashModeDecision(
            cash_mode=True,
            rating=rating,
            reason_code="CASHMODE_BEAR_REGIME",
            detail={"confidence": float(result.confidence), "min_confidence": pol.bear_min_confidence, "regime": result.regime.value},
        )

    # Hysteresis for rating-based switch.
    if current_cash_mode:
        if rating >= pol.exit_above_rating:
            return CashModeDecision(
                cash_mode=False,
                rating=rating,
                reason_code="CASHMODE_EXIT_RATING_RECOVERY",
                detail={"rating": rating, "exit_above": pol.exit_above_rating, "regime": result.regime.value},
            )
        return CashModeDecision(
            cash_mode=True,
            rating=rating,
            reason_code="CASHMODE_HOLD",
            detail={"rating": rating, "enter_below": pol.enter_below_rating, "exit_above": pol.exit_above_rating, "regime": result.regime.value},
        )

    # Not currently in cash mode.
    if rating <= pol.enter_below_rating:
        return CashModeDecision(
            cash_mode=True,
            rating=rating,
            reason_code="CASHMODE_ENTER_LOW_RATING",
            detail={"rating": rating, "enter_below": pol.enter_below_rating, "regime": result.regime.value},
        )

    return CashModeDecision(
        cash_mode=False,
        rating=rating,
        reason_code="CASHMODE_NORMAL",
        detail={"rating": rating, "enter_below": pol.enter_below_rating, "exit_above": pol.exit_above_rating, "regime": result.regime.value},
    )


def apply_cash_mode_to_system_state(system_state: SystemState, decision: CashModeDecision) -> SystemState:
    """Return a new SystemState with reduce_only_mode adjusted according to cash-mode decision."""

    # SystemState is a mutable dataclass, but keep it pure for safer integration.
    return SystemState(
        now_ms=system_state.now_ms,
        trading_locked=system_state.trading_locked,
        broker_connected=system_state.broker_connected,
        db_write_p99_ms=system_state.db_write_p99_ms,
        orders_last_60s=system_state.orders_last_60s,
        reduce_only_mode=bool(decision.cash_mode),
    )
