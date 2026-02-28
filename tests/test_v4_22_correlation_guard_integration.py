"""Integration test: risk_engine applies correlation guard scaling (v4 #22)."""


def test_risk_engine_applies_correlation_guard_scaling_to_limits():
    from openclaw.correlation_guard import CorrelationGuardDecision
    from openclaw.risk_engine import (
        Decision,
        MarketState,
        PortfolioState,
        Position,
        SystemState,
        default_limits,
        evaluate_and_build_order,
    )

    decision = Decision(
        decision_id="d-corr",
        ts_ms=1_000_000,
        symbol="2330",
        strategy_id="breakout",
        signal_side="buy",
        signal_score=0.9,
    )

    market = MarketState(best_bid=100.0, best_ask=100.1, volume_1m=100_000, feed_delay_ms=10)

    # Existing position weight ~0.14, new order (authority_level=2 cap 0.05) -> total ~0.19
    portfolio = PortfolioState(
        nav=1_000_000.0,
        cash=800_000.0,
        realized_pnl_today=0.0,
        unrealized_pnl=0.0,
        positions={
            "2330": Position(symbol="2330", qty=1400, avg_price=100.0, last_price=100.0),
        },
        consecutive_losses=0,
    )

    system = SystemState(
        now_ms=1_000_010,
        trading_locked=False,
        broker_connected=True,
        db_write_p99_ms=10,
        orders_last_60s=0,
        reduce_only_mode=False,
    )

    limits = default_limits()
    limits["authority_level"] = 2  # Sentinel cap => max_position_notional_pct_nav=0.05
    limits["max_symbol_weight"] = 0.20

    ok = evaluate_and_build_order(decision, market, portfolio, limits, system)
    assert ok.approved is True

    breach = CorrelationGuardDecision(
        ok=False,
        reason_code="CORR_MAX_PAIR_EXCEEDED",
        n_symbols=3,
        max_pair_abs_corr=0.95,
        weighted_avg_abs_corr=0.70,
        top_pairs=[("A", "B", 0.95)],
        suggestions=["Reduce exposure"],
        matrix={"A": {"A": 1.0, "B": 0.95}, "B": {"A": 0.95, "B": 1.0}},
    )

    res = evaluate_and_build_order(decision, market, portfolio, limits, system, correlation_decision=breach)
    assert res.approved is False
    assert res.reject_code == "RISK_POSITION_CONCENTRATION"
    assert res.metrics.get("correlation_guard_ok") is False
