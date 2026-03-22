"""Tests for hard wash sale prevention (#386).

Covers:
- RISK_WASH_SALE_SELL_TODAY blocks buy after same-day sell
- Cannot be bypassed by wash_sale_prevention_enabled=0
- Does not block buy when no same-day sell exists
- Does not block sell orders
"""
from __future__ import annotations

import pytest

from openclaw.risk_engine import (
    Decision,
    EvaluationResult,
    MarketState,
    PortfolioState,
    SystemState,
    evaluate_and_build_order,
    default_limits,
)


def _make_decision(symbol: str = "2330", side: str = "buy") -> Decision:
    return Decision(
        decision_id="test-001",
        ts_ms=1000,
        symbol=symbol,
        strategy_id="test",
        signal_side=side,
        signal_score=0.8,
    )


def _make_market() -> MarketState:
    return MarketState(
        best_bid=100.0,
        best_ask=100.2,
        volume_1m=100000,
        feed_delay_ms=10,
    )


def _make_portfolio(
    same_day_sell_symbols: set | None = None,
    same_day_fill_symbols: set | None = None,
) -> PortfolioState:
    return PortfolioState(
        nav=1_000_000,
        cash=500_000,
        realized_pnl_today=0.0,
        unrealized_pnl=0.0,
        same_day_fill_symbols=same_day_fill_symbols or set(),
        same_day_sell_symbols=same_day_sell_symbols or set(),
    )


def _make_system() -> SystemState:
    return SystemState(
        now_ms=1000,
        trading_locked=False,
        broker_connected=True,
        db_write_p99_ms=10,
        orders_last_60s=0,
    )


class TestHardWashSale:
    def test_buy_blocked_after_same_day_sell(self):
        decision = _make_decision("2330", "buy")
        portfolio = _make_portfolio(same_day_sell_symbols={"2330"})
        limits = default_limits()
        limits["pm_review_required"] = 0

        result = evaluate_and_build_order(
            decision, _make_market(), portfolio, limits, _make_system()
        )
        assert not result.approved
        assert result.reject_code == "RISK_WASH_SALE_SELL_TODAY"

    def test_cannot_bypass_with_config(self):
        """Even with wash_sale_prevention_enabled=0, sell-today check still blocks."""
        decision = _make_decision("2330", "buy")
        portfolio = _make_portfolio(same_day_sell_symbols={"2330"})
        limits = default_limits()
        limits["pm_review_required"] = 0
        limits["wash_sale_prevention_enabled"] = 0  # disable old check

        result = evaluate_and_build_order(
            decision, _make_market(), portfolio, limits, _make_system()
        )
        assert not result.approved
        assert result.reject_code == "RISK_WASH_SALE_SELL_TODAY"

    def test_buy_allowed_when_no_same_day_sell(self):
        decision = _make_decision("2330", "buy")
        portfolio = _make_portfolio(same_day_sell_symbols=set())
        limits = default_limits()
        limits["pm_review_required"] = 0

        result = evaluate_and_build_order(
            decision, _make_market(), portfolio, limits, _make_system()
        )
        # May still be rejected by other checks, but NOT by wash sale
        assert result.reject_code != "RISK_WASH_SALE_SELL_TODAY"

    def test_sell_not_blocked_by_same_day_sell(self):
        """Sell orders should not be blocked by wash sale (allow closing positions)."""
        decision = _make_decision("2330", "sell")
        portfolio = _make_portfolio(same_day_sell_symbols={"2330"})
        limits = default_limits()
        limits["pm_review_required"] = 0

        result = evaluate_and_build_order(
            decision, _make_market(), portfolio, limits, _make_system()
        )
        assert result.reject_code != "RISK_WASH_SALE_SELL_TODAY"

    def test_different_symbol_not_blocked(self):
        decision = _make_decision("2317", "buy")
        portfolio = _make_portfolio(same_day_sell_symbols={"2330"})
        limits = default_limits()
        limits["pm_review_required"] = 0

        result = evaluate_and_build_order(
            decision, _make_market(), portfolio, limits, _make_system()
        )
        assert result.reject_code != "RISK_WASH_SALE_SELL_TODAY"
