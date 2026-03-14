"""tests/test_ticker_watcher_sell.py

Validates building blocks for the sell auto-trigger:
  1. evaluate_exit returns sell on stop-loss scenario
  2. risk_engine blocks sell on locked symbol
  3. risk_engine does NOT block buy on locked symbol
  4. Closing-position orders skip slippage/deviation checks
"""
import time
import uuid
from unittest.mock import patch

import pytest

from openclaw.signal_logic import evaluate_exit, SignalParams, SignalResult
from openclaw.risk_engine import (
    Decision,
    MarketState,
    PortfolioState,
    Position,
    SystemState,
    evaluate_and_build_order,
    default_limits,
)


# ─── helpers ────────────────────────────────────────────────────────────────

def _make_decision(side: str, symbol: str = "2330") -> Decision:
    return Decision(
        decision_id=str(uuid.uuid4()),
        ts_ms=int(time.time() * 1000),
        symbol=symbol,
        strategy_id="test",
        signal_side=side,
        signal_score=0.9,
    )


def _market(bid: float = 595.0, ask: float = 605.0, volume_1m: int = 5000) -> MarketState:
    return MarketState(
        best_bid=bid,
        best_ask=ask,
        volume_1m=volume_1m,
        feed_delay_ms=10,
    )


def _portfolio(with_position: bool = False, symbol: str = "2330") -> PortfolioState:
    positions = {}
    if with_position:
        positions[symbol] = Position(
            symbol=symbol,
            qty=100,
            avg_price=600.0,
            last_price=500.0,
        )
    return PortfolioState(
        nav=1_000_000.0,
        cash=500_000.0,
        realized_pnl_today=0.0,
        unrealized_pnl=0.0,
        positions=positions,
    )


def _system() -> SystemState:
    return SystemState(
        now_ms=int(time.time() * 1000),
        trading_locked=False,
        broker_connected=True,
        db_write_p99_ms=10,
        orders_last_60s=0,
    )


def _limits_no_pm() -> dict:
    lim = default_limits()
    lim["pm_review_required"] = 0
    return lim


# ─── tests ──────────────────────────────────────────────────────────────────

class TestEvaluateExit:
    def test_sell_trigger_calls_evaluate_exit(self):
        """evaluate_exit returns sell signal when stop-loss is breached."""
        avg_price = 600.0
        # Current price is 8% below avg_price — exceeds default stop_loss_pct=3%
        closes = [620.0, 610.0, 600.0, 590.0, 552.0]
        result = evaluate_exit(
            closes=closes,
            avg_price=avg_price,
            high_water_mark=620.0,
            params=SignalParams(),
        )
        assert isinstance(result, SignalResult)
        assert result.signal == "sell", f"Expected 'sell', got '{result.signal}': {result.reason}"
        assert "stop_loss" in result.reason or "trailing_stop" in result.reason

    def test_evaluate_exit_returns_flat_on_hold(self):
        """evaluate_exit returns flat when no exit condition is met."""
        avg_price = 600.0
        closes = [600.0, 601.0, 602.0]
        result = evaluate_exit(
            closes=closes,
            avg_price=avg_price,
            high_water_mark=602.0,
            params=SignalParams(),
        )
        assert result.signal == "flat"


class TestLockedSymbol:
    def test_sell_trigger_skips_locked_symbol(self):
        """risk_engine blocks sell order when symbol is locked."""
        decision = _make_decision("sell")
        with patch("openclaw.risk_engine._is_symbol_locked", return_value=True):
            result = evaluate_and_build_order(
                decision=decision,
                market=_market(),
                portfolio=_portfolio(with_position=True),
                limits=_limits_no_pm(),
                system_state=_system(),
            )
        assert result.approved is False
        assert result.reject_code == "RISK_SYMBOL_LOCKED"

    def test_sell_trigger_buy_locked_allowed(self):
        """risk_engine does NOT block buy order on locked symbol.

        LOCK_PROTECTION only blocks sells; buys on locked symbols are permitted.
        """
        decision = _make_decision("buy")
        with patch("openclaw.risk_engine._is_symbol_locked", return_value=True):
            result = evaluate_and_build_order(
                decision=decision,
                market=_market(),
                portfolio=_portfolio(with_position=False),
                limits=_limits_no_pm(),
                system_state=_system(),
            )
        # Must NOT be rejected with RISK_SYMBOL_LOCKED
        assert result.reject_code != "RISK_SYMBOL_LOCKED", (
            "Buy orders should never be blocked by LOCK_PROTECTION"
        )


class TestClosingOrderSlippage:
    def test_closing_order_skips_slippage_check(self):
        """Closing position orders bypass slippage and price-deviation checks.

        Even with an extreme bid/ask spread (high slippage), a sell that closes
        an existing long position must be approved so stop-losses can execute.
        """
        decision = _make_decision("sell")

        # Extreme spread → slippage would be huge if checked
        market = MarketState(
            best_bid=100.0,   # far below avg_price of 600
            best_ask=1100.0,
            volume_1m=10_000,
            feed_delay_ms=10,
        )

        # Existing long position — this sell is a closing order (opens_new_position=False)
        portfolio = _portfolio(with_position=True)

        lim = _limits_no_pm()
        lim["max_slippage_bps"] = 1       # effectively zero tolerance
        lim["max_price_deviation_pct"] = 0.001  # 0.1% — impossible to satisfy

        result = evaluate_and_build_order(
            decision=decision,
            market=market,
            portfolio=portfolio,
            limits=lim,
            system_state=_system(),
        )

        assert result.approved is True, (
            f"Closing order should skip slippage/deviation checks but got: "
            f"{result.reject_code}"
        )
        assert result.order is not None
        assert result.order.opens_new_position is False
        assert result.order.side == "sell"
