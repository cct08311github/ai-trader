from openclaw.risk_engine import (
    Decision,
    MarketState,
    PortfolioState,
    Position,
    SystemState,
    default_limits,
    evaluate_and_build_order,
)


def _test_limits() -> dict:
    """default_limits() with pm_review_required=0 to bypass daily PM file check in unit tests."""
    lim = default_limits()
    lim["pm_review_required"] = 0
    return lim


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
        limits=_test_limits(),
        system_state=_base_system(),
    )
    assert result.approved is True
    assert result.order is not None
    assert result.order.qty > 0


def test_reject_trading_locked():
    sys = _base_system()
    sys.trading_locked = True
    result = evaluate_and_build_order(_base_decision(), _base_market(), _base_portfolio(), _test_limits(), sys)
    assert result.approved is False
    assert result.reject_code == "RISK_TRADING_LOCKED"


def test_reject_daily_loss_limit():
    pf = _base_portfolio()
    pf.unrealized_pnl = -60_000.0  # >5% NAV loss
    result = evaluate_and_build_order(_base_decision(), _base_market(), pf, _test_limits(), _base_system())
    assert result.approved is False
    assert result.reject_code == "RISK_DAILY_LOSS_LIMIT"


def test_reject_rate_limit():
    sys = _base_system()
    sys.orders_last_60s = 3
    result = evaluate_and_build_order(_base_decision(), _base_market(), _base_portfolio(), _test_limits(), sys)
    assert result.approved is False
    assert result.reject_code == "RISK_ORDER_RATE_LIMIT"


def test_reject_data_staleness():
    mkt = _base_market()
    mkt.feed_delay_ms = 2000
    result = evaluate_and_build_order(_base_decision(), mkt, _base_portfolio(), _test_limits(), _base_system())
    assert result.approved is False
    assert result.reject_code == "RISK_DATA_STALENESS"


def test_reject_reduce_only_new_position():
    sys = _base_system()
    sys.reduce_only_mode = True
    result = evaluate_and_build_order(_base_decision(), _base_market(), _base_portfolio(), _test_limits(), sys)
    assert result.approved is False
    assert result.reject_code == "RISK_CONSECUTIVE_LOSSES"


def test_auto_reduce_qty_when_liquidity_ratio_hit():
    limits = _test_limits()
    limits["max_qty_to_1m_volume_ratio"] = 0.01  # 100 shares max
    mkt = _base_market()
    mkt.volume_1m = 10_000
    result = evaluate_and_build_order(_base_decision(), mkt, _base_portfolio(), limits, _base_system())
    assert result.approved is True
    assert result.order is not None
    assert result.order.qty <= 100


def test_reject_when_auto_reduce_disabled_and_qty_too_large():
    limits = _test_limits()
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
    result = evaluate_and_build_order(d, _base_market(), pf, _test_limits(), sys)
    assert result.approved is True
    assert result.order is not None
    assert result.order.opens_new_position is False


# ---------------------------------------------------------------------------
# risk_store tests (lines 62-63: seed_sql)
# ---------------------------------------------------------------------------

import sqlite3 as _sqlite3
from openclaw.risk_store import load_limits, seed_sql, LimitQuery


def _risk_store_conn() -> _sqlite3.Connection:
    conn = _sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE risk_limits (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          rule_name TEXT NOT NULL,
          rule_value REAL NOT NULL,
          scope TEXT NOT NULL DEFAULT 'global',
          symbol TEXT,
          strategy_id TEXT,
          enabled INTEGER NOT NULL DEFAULT 1
        );
        """
    )
    return conn


def test_seed_sql_executes_script():
    """Lines 62-63: seed_sql runs executescript and commits."""
    conn = _risk_store_conn()
    seed_sql(
        conn,
        """
        INSERT INTO risk_limits(rule_name, rule_value, scope, enabled)
        VALUES ('max_position_pct', 0.05, 'global', 1);
        INSERT INTO risk_limits(rule_name, rule_value, scope, enabled)
        VALUES ('max_daily_loss_pct', 0.02, 'global', 1);
        """,
    )
    count = conn.execute("SELECT COUNT(*) FROM risk_limits").fetchone()[0]
    assert count == 2


def test_load_limits_global_only():
    """load_limits returns global-scoped limits."""
    conn = _risk_store_conn()
    seed_sql(
        conn,
        """
        INSERT INTO risk_limits(rule_name, rule_value, scope, enabled) VALUES ('max_pos', 0.10, 'global', 1);
        INSERT INTO risk_limits(rule_name, rule_value, scope, enabled) VALUES ('disabled_rule', 0.99, 'global', 0);
        """,
    )
    limits = load_limits(conn, LimitQuery())
    assert "max_pos" in limits
    assert abs(limits["max_pos"] - 0.10) < 1e-9
    assert "disabled_rule" not in limits


def test_load_limits_symbol_override():
    """load_limits applies symbol-level override on top of global."""
    conn = _risk_store_conn()
    seed_sql(
        conn,
        """
        INSERT INTO risk_limits(rule_name, rule_value, scope, enabled) VALUES ('max_pos', 0.10, 'global', 1);
        INSERT INTO risk_limits(rule_name, rule_value, scope, symbol, enabled) VALUES ('max_pos', 0.05, 'symbol', '2330', 1);
        """,
    )
    limits = load_limits(conn, LimitQuery(symbol="2330"))
    assert abs(limits["max_pos"] - 0.05) < 1e-9


def test_load_limits_strategy_override():
    """load_limits applies strategy-level override on top of global."""
    conn = _risk_store_conn()
    seed_sql(
        conn,
        """
        INSERT INTO risk_limits(rule_name, rule_value, scope, enabled) VALUES ('max_pos', 0.10, 'global', 1);
        INSERT INTO risk_limits(rule_name, rule_value, scope, strategy_id, enabled) VALUES ('max_pos', 0.03, 'strategy', 'breakout', 1);
        """,
    )
    limits = load_limits(conn, LimitQuery(strategy_id="breakout"))
    assert abs(limits["max_pos"] - 0.03) < 1e-9
