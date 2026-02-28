from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Literal, Optional


PositionSide = Literal["long", "short"]


@dataclass
class TakeProfitPolicy:
    """Three-in-one take profit policy.

    Layers (evaluated in this order):
      1) Target price take profit (partial)
      2) Trailing stop (exit remaining)
      3) Time decay (exit remaining)

    Notes
    -----
    - Target price defaults to risk-reward (RR) multiple derived from
      (entry_price - initial_stop_price).
    - Trailing stop uses pct of peak/trough by default.
    """

    target_rr: float = 2.0
    target_exit_fraction: float = 0.50

    trailing_stop_pct: float = 0.01

    max_hold_ms: int = 90 * 60 * 1000  # 90 minutes
    time_decay_profit_floor_pct: float = 0.0  # allow time-exit at breakeven


@dataclass
class TakeProfitState:
    entry_ts_ms: int
    entry_price: float
    side: PositionSide
    qty: int
    initial_stop_price: float

    remaining_qty: int = field(init=False)
    target_taken: bool = field(default=False)

    peak_price: float = field(init=False)
    trough_price: float = field(init=False)

    def __post_init__(self) -> None:
        self.remaining_qty = int(self.qty)
        self.peak_price = float(self.entry_price)
        self.trough_price = float(self.entry_price)


@dataclass(frozen=True)
class TakeProfitDecision:
    action: Literal["hold", "exit"]
    qty_to_exit: int = 0
    reason: str = ""
    target_price: Optional[float] = None
    trailing_stop: Optional[float] = None
    metrics: Dict[str, float] = None  # type: ignore[assignment]


def _risk_per_share(state: TakeProfitState) -> float:
    return abs(float(state.entry_price) - float(state.initial_stop_price))


def compute_target_price(state: TakeProfitState, policy: TakeProfitPolicy) -> float:
    risk = _risk_per_share(state)
    if risk <= 0:
        # Fallback: 1% target if we don't have a stop distance.
        risk = abs(state.entry_price) * 0.01

    if state.side == "long":
        return float(state.entry_price + risk * float(policy.target_rr))
    return float(state.entry_price - risk * float(policy.target_rr))


def update_trailing_extremes(state: TakeProfitState, last_price: float) -> None:
    p = float(last_price)
    state.peak_price = max(float(state.peak_price), p)
    state.trough_price = min(float(state.trough_price), p)


def compute_trailing_stop(state: TakeProfitState, policy: TakeProfitPolicy) -> float:
    pct = max(0.0, float(policy.trailing_stop_pct))
    if state.side == "long":
        return float(state.peak_price * (1.0 - pct))
    return float(state.trough_price * (1.0 + pct))


def _profit_pct(state: TakeProfitState, last_price: float) -> float:
    lp = float(last_price)
    if state.entry_price == 0:
        return 0.0

    if state.side == "long":
        return (lp - float(state.entry_price)) / abs(float(state.entry_price))
    return (float(state.entry_price) - lp) / abs(float(state.entry_price))


def _crosses_target(state: TakeProfitState, last_price: float, target_price: float) -> bool:
    lp = float(last_price)
    if state.side == "long":
        return lp >= float(target_price)
    return lp <= float(target_price)


def _crosses_trailing_stop(state: TakeProfitState, last_price: float, trailing_stop: float) -> bool:
    lp = float(last_price)
    if state.side == "long":
        return lp <= float(trailing_stop)
    return lp >= float(trailing_stop)


def evaluate_take_profit(
    *,
    state: TakeProfitState,
    last_price: float,
    now_ms: int,
    policy: TakeProfitPolicy,
) -> TakeProfitDecision:
    """Evaluate take profit rules and (optionally) emit an exit instruction.

    The caller is responsible for turning the decision into actual orders.
    The state is mutated only for tracking extremes/target-taken bookkeeping.
    """

    if state.remaining_qty <= 0:
        return TakeProfitDecision(action="hold", qty_to_exit=0, reason="no_position")

    update_trailing_extremes(state, last_price)

    target_price = compute_target_price(state, policy)
    trailing_stop = compute_trailing_stop(state, policy)

    # 1) Target price: partial take profit once.
    if (not state.target_taken) and _crosses_target(state, last_price, target_price):
        exit_qty = max(1, int(round(state.qty * float(policy.target_exit_fraction))))
        exit_qty = min(exit_qty, state.remaining_qty)
        state.remaining_qty -= exit_qty
        state.target_taken = True
        return TakeProfitDecision(
            action="exit",
            qty_to_exit=int(exit_qty),
            reason="target_price",
            target_price=float(target_price),
            trailing_stop=float(trailing_stop),
            metrics={"profit_pct": float(_profit_pct(state, last_price))},
        )

    # 2) Trailing stop: exit all remaining.
    if _crosses_trailing_stop(state, last_price, trailing_stop):
        exit_qty = int(state.remaining_qty)
        state.remaining_qty = 0
        return TakeProfitDecision(
            action="exit",
            qty_to_exit=int(exit_qty),
            reason="trailing_stop",
            target_price=float(target_price),
            trailing_stop=float(trailing_stop),
            metrics={"profit_pct": float(_profit_pct(state, last_price))},
        )

    # 3) Time decay: exit if held too long.
    held_ms = int(now_ms) - int(state.entry_ts_ms)
    if held_ms >= int(policy.max_hold_ms):
        pp = float(_profit_pct(state, last_price))
        if pp >= float(policy.time_decay_profit_floor_pct):
            exit_qty = int(state.remaining_qty)
            state.remaining_qty = 0
            return TakeProfitDecision(
                action="exit",
                qty_to_exit=int(exit_qty),
                reason="time_decay",
                target_price=float(target_price),
                trailing_stop=float(trailing_stop),
                metrics={"profit_pct": pp, "held_ms": float(held_ms)},
            )

    return TakeProfitDecision(
        action="hold",
        qty_to_exit=0,
        reason="hold",
        target_price=float(target_price),
        trailing_stop=float(trailing_stop),
        metrics={"profit_pct": float(_profit_pct(state, last_price)), "held_ms": float(held_ms)},
    )
