"""整合測試 — 完整交易循環模擬。"""
import time
import uuid
import pytest
from unittest.mock import patch

from openclaw.signal_logic import evaluate_entry, evaluate_exit, SignalParams
from openclaw.risk_engine import (
    Decision, MarketState, PortfolioState, Position, SystemState,
    evaluate_and_build_order, default_limits,
)


def test_full_cycle_buy_then_sell():
    """模擬完整週期：entry signal → exit signal → risk_engine approve sell (closing order)。"""
    params = SignalParams(stop_loss_pct=0.05)

    # Exit signal on held position
    closes_exit = [100, 98, 96, 94, 92]  # 持續下跌 → 觸發止損
    exit_sig = evaluate_exit(closes_exit, avg_price=100.0, high_water_mark=100.0, params=params)
    assert exit_sig.signal == "sell"
    # trailing_stop 比 stop_loss 優先觸發（92 < 100 * 0.95），兩者都屬有效出場
    assert any(kw in exit_sig.reason for kw in ("stop_loss", "trailing_stop"))

    # Risk engine approves sell (closing position)
    decision = Decision(
        decision_id=str(uuid.uuid4()), ts_ms=int(time.time() * 1000),
        symbol="2330", strategy_id="test", signal_side="sell", signal_score=0.9,
    )
    pos = Position(symbol="2330", qty=100, avg_price=100, last_price=92)
    market = MarketState(best_bid=91.5, best_ask=92.5, volume_1m=5000, feed_delay_ms=10)
    portfolio = PortfolioState(
        nav=1_000_000, cash=500_000, realized_pnl_today=0, unrealized_pnl=-800,
        positions={"2330": pos},
    )
    system = SystemState(
        now_ms=decision.ts_ms, trading_locked=False, broker_connected=True,
        db_write_p99_ms=10, orders_last_60s=0,
    )
    limits = default_limits()
    limits["pm_review_required"] = 0

    with patch("openclaw.risk_engine._is_symbol_locked", return_value=False):
        result = evaluate_and_build_order(decision, market, portfolio, limits, system)

    assert result.approved
    assert result.order is not None
    assert result.order.side == "sell"
    assert result.order.opens_new_position is False


def test_locked_symbol_consistent_across_layers():
    """Locked symbol 在各層行為一致：signal_logic 觸發 sell → risk_engine 擋 sell → buy 放行。"""
    params = SignalParams(stop_loss_pct=0.001)

    # signal_logic doesn't know about locked — triggers sell
    closes = [100, 90]
    exit_sig = evaluate_exit(closes, avg_price=100.0, high_water_mark=100.0, params=params)
    assert exit_sig.signal == "sell"

    # risk_engine blocks sell on locked
    decision = Decision(
        decision_id=str(uuid.uuid4()), ts_ms=int(time.time() * 1000),
        symbol="LOCKED", strategy_id="test", signal_side="sell", signal_score=0.9,
    )
    market = MarketState(best_bid=89, best_ask=91, volume_1m=5000, feed_delay_ms=10)
    pos = Position(symbol="LOCKED", qty=100, avg_price=100, last_price=90)
    portfolio = PortfolioState(
        nav=1_000_000, cash=500_000, realized_pnl_today=0, unrealized_pnl=-1000,
        positions={"LOCKED": pos},
    )
    system = SystemState(
        now_ms=decision.ts_ms, trading_locked=False, broker_connected=True,
        db_write_p99_ms=10, orders_last_60s=0,
    )
    limits = default_limits()
    limits["pm_review_required"] = 0

    with patch("openclaw.risk_engine._is_symbol_locked", return_value=True):
        result = evaluate_and_build_order(decision, market, portfolio, limits, system)
    assert not result.approved
    assert result.reject_code == "RISK_SYMBOL_LOCKED"

    # Buy on locked — should pass lock check
    buy_decision = Decision(
        decision_id=str(uuid.uuid4()), ts_ms=int(time.time() * 1000),
        symbol="LOCKED", strategy_id="test", signal_side="buy", signal_score=0.9,
    )
    with patch("openclaw.risk_engine._is_symbol_locked", return_value=True):
        buy_result = evaluate_and_build_order(buy_decision, market, portfolio, limits, system)
    assert buy_result.reject_code != "RISK_SYMBOL_LOCKED"
