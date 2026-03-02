from __future__ import annotations

from openclaw.market_regime import (
    MarketRegime,
    apply_market_regime_risk_adjustments,
    classify_market_regime,
)
from openclaw.risk_engine import (
    Decision,
    MarketState,
    PortfolioState,
    SystemState,
    default_limits,
    evaluate_and_build_order,
)


def test_market_regime_classify_bull_bear_range():
    # Bull: trending up + volume confirmation
    prices_bull = [100 + i * 0.8 for i in range(80)]
    vols_bull = [1000 + i * 2 for i in range(80)]
    r1 = classify_market_regime(prices_bull, vols_bull)
    assert r1.regime == MarketRegime.BULL
    assert 0.0 <= r1.confidence <= 1.0

    # Bear: trending down
    prices_bear = [150 - i * 0.9 for i in range(80)]
    vols_bear = [1000 + i * 2 for i in range(80)]
    r2 = classify_market_regime(prices_bear, vols_bear)
    assert r2.regime == MarketRegime.BEAR

    # Range: oscillating
    prices_range = [100 + (1 if (i % 2 == 0) else -1) * 0.4 for i in range(80)]
    vols_range = [1000 for _ in range(80)]
    r3 = classify_market_regime(prices_range, vols_range)
    assert r3.regime == MarketRegime.RANGE


def test_apply_market_regime_risk_adjustments_adds_metadata_and_scales():
    prices_bear = [150 - i * 0.9 for i in range(80)]
    vols = [1000 + i * 2 for i in range(80)]
    r = classify_market_regime(prices_bear, vols)

    limits = default_limits()
    adjusted = apply_market_regime_risk_adjustments(limits, r)

    assert adjusted["market_regime"] == r.regime.value
    assert "market_regime_confidence" in adjusted
    assert "market_regime_volatility_multiplier" in adjusted

    # Bear regime reduces per-trade loss cap.
    assert adjusted["max_loss_per_trade_pct_nav"] < limits["max_loss_per_trade_pct_nav"]


def test_risk_engine_qty_reduces_when_volatility_multiplier_decreases():
    # Same decision except vol multiplier.
    base = Decision(
        decision_id="d1",
        ts_ms=1_000_000,
        symbol="2330",
        strategy_id="breakout",
        signal_side="buy",
        signal_score=0.9,
        signal_ttl_ms=30_000,
        confidence=1.0,
    )

    market = MarketState(best_bid=100.0, best_ask=100.0, volume_1m=1_000_000, feed_delay_ms=50)
    portfolio = PortfolioState(nav=10_000_000.0, cash=8_000_000.0, realized_pnl_today=0.0, unrealized_pnl=0.0)
    system = SystemState(now_ms=1_000_100, trading_locked=False, broker_connected=True, db_write_p99_ms=50, orders_last_60s=0)

    limits = default_limits()
    limits["pm_review_required"] = 0  # bypass PM check in unit tests
    limits["max_symbol_weight"] = 1.0
    limits["max_gross_exposure"] = 10.0
    limits["max_loss_per_trade_pct_nav"] = 0.006

    res1 = evaluate_and_build_order(base, market, portfolio, limits, system)
    assert res1.approved is True
    qty1 = res1.order.qty

    d2 = Decision(**{**base.__dict__, "decision_id": "d2", "volatility_multiplier": 0.70})
    res2 = evaluate_and_build_order(d2, market, portfolio, limits, system)
    assert res2.approved is True
    qty2 = res2.order.qty

    assert qty2 < qty1
