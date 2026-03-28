from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

from openclaw.config_manager import get_config
from openclaw.drawdown_guard import DrawdownDecision
from openclaw.risk_engine import OrderCandidate, SystemState

logger = logging.getLogger(__name__)


def _locked_symbols() -> set:
    """Read locked symbols from config. Returns empty set on error."""
    return get_config().locked_symbols()


@dataclass(frozen=True)
class SentinelVerdict:
    allowed: bool
    hard_blocked: bool
    reason_code: str
    detail: Dict[str, Any]


_HARD_BLOCK_CODES: Sequence[str] = (
    "SENTINEL_TRADING_LOCKED",
    "SENTINEL_BROKER_DISCONNECTED",
    "SENTINEL_DB_LATENCY",
    "SENTINEL_DRAWDOWN_SUSPENDED",
    "SENTINEL_BUDGET_HALT",
    "SENTINEL_SYMBOL_LOCKED",  # Long-term hold protection
)


def sentinel_pre_trade_check(
    *,
    system_state: SystemState,
    drawdown: Optional[DrawdownDecision] = None,
    budget_status: str = "ok",  # ok/warn/throttle/halt
    budget_used_pct: float = 0.0,
    max_db_write_p99_ms: int = 200,
) -> SentinelVerdict:
    """Hard circuit-breakers. PM cannot override this layer.

    Responsibility split (P1):
    - Sentinel: safety invariants / circuit breakers
    - PM: discretionary veto (soft)
    """

    if system_state.trading_locked:
        return SentinelVerdict(False, True, "SENTINEL_TRADING_LOCKED", {})

    if not system_state.broker_connected:
        return SentinelVerdict(False, True, "SENTINEL_BROKER_DISCONNECTED", {})

    if system_state.db_write_p99_ms > max_db_write_p99_ms:
        return SentinelVerdict(
            False,
            True,
            "SENTINEL_DB_LATENCY",
            {"db_write_p99_ms": system_state.db_write_p99_ms, "limit": max_db_write_p99_ms},
        )

    if drawdown and drawdown.risk_mode == "suspended":
        return SentinelVerdict(
            False,
            True,
            "SENTINEL_DRAWDOWN_SUSPENDED",
            {"reason": drawdown.reason_code, "drawdown": drawdown.drawdown},
        )

    if budget_status == "halt":
        return SentinelVerdict(
            False,
            True,
            "SENTINEL_BUDGET_HALT",
            {"used_pct": budget_used_pct},
        )

    # warnings/throttling are soft signals
    if budget_status in {"warn", "throttle"}:
        return SentinelVerdict(
            True,
            False,
            "SENTINEL_BUDGET_SOFT",
            {"used_pct": budget_used_pct, "mode": budget_status},
        )

    return SentinelVerdict(True, False, "SENTINEL_OK", {})


def sentinel_post_risk_check(
    *,
    system_state: SystemState,
    candidate: Optional[OrderCandidate],
) -> SentinelVerdict:
    """Second-stage hard enforcement after a candidate order exists."""

    if candidate is None:
        return SentinelVerdict(False, False, "SENTINEL_NO_CANDIDATE", {})

    if system_state.reduce_only_mode and candidate.opens_new_position:
        return SentinelVerdict(False, True, "SENTINEL_REDUCE_ONLY", {"symbol": candidate.symbol})

    # Long-term hold protection: hard-block sell orders on locked symbols
    if candidate.side == "sell":
        locked = _locked_symbols()
        if candidate.symbol.upper() in locked:
            return SentinelVerdict(
                False, True, "SENTINEL_SYMBOL_LOCKED", {"symbol": candidate.symbol}
            )

    return SentinelVerdict(True, False, "SENTINEL_OK", {})


def pm_veto(*, pm_approved: bool, reason_code: str = "PM_REJECT") -> SentinelVerdict:
    """Soft veto layer: PM can veto, but cannot hard-override Sentinel."""

    if pm_approved:
        return SentinelVerdict(True, False, "PM_OK", {})
    return SentinelVerdict(False, False, reason_code, {})


def is_hard_block(verdict: SentinelVerdict) -> bool:
    return bool(verdict.hard_blocked or verdict.reason_code in _HARD_BLOCK_CODES)


def filter_locked_positions(portfolio: "PortfolioState") -> "PortfolioState":
    """Return a new PortfolioState with locked symbols removed.

    Call this BEFORE passing PortfolioState into the decision pipeline so that
    locked long-term holdings:
      - are invisible to strategy signal evaluation
      - do not inflate gross_exposure / NAV used for sizing
      - do not affect unrealized PnL that influences risk guards
      - cannot appear as sell candidates
    """
    locked = _locked_symbols()
    if not locked:
        return portfolio

    active = {sym: pos for sym, pos in portfolio.positions.items() if sym.upper() not in locked}
    removed = {sym: pos for sym, pos in portfolio.positions.items() if sym.upper() in locked}

    if not removed:
        return portfolio

    # Subtract locked positions' market value and unrealized PnL
    locked_mv = sum(abs(p.qty * p.last_price) for p in removed.values())
    locked_unrealized = sum((p.last_price - p.avg_price) * p.qty for p in removed.values())

    from openclaw.risk_engine import PortfolioState  # local import avoids circular dep
    return PortfolioState(
        nav=max(portfolio.nav - locked_mv, portfolio.cash),
        cash=portfolio.cash,
        realized_pnl_today=portfolio.realized_pnl_today,
        unrealized_pnl=portfolio.unrealized_pnl - locked_unrealized,
        positions=active,
        consecutive_losses=portfolio.consecutive_losses,
    )
