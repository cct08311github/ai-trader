from openclaw.risk_engine import (
    Decision,
    MarketState,
    PortfolioState,
    Position,
    SystemState,
    default_limits,
    evaluate_and_build_order,
)


def _base_decision() -> Decision:
    return Decision(
        decision_id="d1",
        ts_ms=1_000_000,
        symbol="2330",
        strategy_id="breakout",
        signal_side="buy",
        signal_score=0.9,
        signal_ttl_ms=30_000,
    )


def _base_market() -> MarketState:
    return MarketState(best_bid=100.0, best_ask=100.1, volume_1m=10_000, feed_delay_ms=50)


def _base_portfolio() -> PortfolioState:
    return PortfolioState(
        nav=1_000_000.0,
        cash=800_000.0,
        realized_pnl_today=0.0,
        unrealized_pnl=0.0,
        positions={},
        consecutive_losses=0,
    )


def _base_system() -> SystemState:
    return SystemState(
        now_ms=1_000_100,
        trading_locked=False,
        broker_connected=True,
        db_write_p99_ms=50,
        orders_last_60s=0,
        reduce_only_mode=False,
    )


def test_approve_happy_path():
    result = evaluate_and_build_order(
        decision=_base_decision(),
        market=_base_market(),
        portfolio=_base_portfolio(),
        limits=default_limits(),
        system_state=_base_system(),
    )
    assert result.approved is True
    assert result.order is not None
    assert result.order.qty > 0


def test_reject_trading_locked():
    sys = _base_system()
    sys.trading_locked = True
    result = evaluate_and_build_order(_base_decision(), _base_market(), _base_portfolio(), default_limits(), sys)
    assert result.approved is False
    assert result.reject_code == "RISK_TRADING_LOCKED"


def test_reject_daily_loss_limit():
    pf = _base_portfolio()
    pf.unrealized_pnl = -60_000.0  # >5% NAV loss
    result = evaluate_and_build_order(_base_decision(), _base_market(), pf, default_limits(), _base_system())
    assert result.approved is False
    assert result.reject_code == "RISK_DAILY_LOSS_LIMIT"


def test_reject_rate_limit():
    sys = _base_system()
    sys.orders_last_60s = 3
    result = evaluate_and_build_order(_base_decision(), _base_market(), _base_portfolio(), default_limits(), sys)
    assert result.approved is False
    assert result.reject_code == "RISK_ORDER_RATE_LIMIT"


def test_reject_data_staleness():
    mkt = _base_market()
    mkt.feed_delay_ms = 2000
    result = evaluate_and_build_order(_base_decision(), mkt, _base_portfolio(), default_limits(), _base_system())
    assert result.approved is False
    assert result.reject_code == "RISK_DATA_STALENESS"


def test_reject_reduce_only_new_position():
    sys = _base_system()
    sys.reduce_only_mode = True
    result = evaluate_and_build_order(_base_decision(), _base_market(), _base_portfolio(), default_limits(), sys)
    assert result.approved is False
    assert result.reject_code == "RISK_CONSECUTIVE_LOSSES"


def test_auto_reduce_qty_when_liquidity_ratio_hit():
    limits = default_limits()
    limits["max_qty_to_1m_volume_ratio"] = 0.01  # 100 shares max
    mkt = _base_market()
    mkt.volume_1m = 10_000
    result = evaluate_and_build_order(_base_decision(), mkt, _base_portfolio(), limits, _base_system())
    assert result.approved is True
    assert result.order is not None
    assert result.order.qty <= 100


def test_reject_when_auto_reduce_disabled_and_qty_too_large():
    limits = default_limits()
    limits["max_qty_to_1m_volume_ratio"] = 0.001
    limits["allow_auto_reduce_qty"] = 0
    mkt = _base_market()
    mkt.volume_1m = 1000
    result = evaluate_and_build_order(_base_decision(), mkt, _base_portfolio(), limits, _base_system())
    assert result.approved is False
    assert result.reject_code == "RISK_LIQUIDITY_LIMIT"


def test_reduce_only_allows_position_reduction():
    pf = _base_portfolio()
    pf.positions["2330"] = Position(symbol="2330", qty=100, avg_price=100.0, last_price=100.0)
    sys = _base_system()
    sys.reduce_only_mode = True
    d = _base_decision()
    d.signal_side = "sell"  # reduces long position
    result = evaluate_and_build_order(d, _base_market(), pf, default_limits(), sys)
    assert result.approved is True
    assert result.order is not None
    assert result.order.opens_new_position is False
