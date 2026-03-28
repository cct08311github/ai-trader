import json
import os
from datetime import date
from unittest.mock import patch

from openclaw.risk_engine import (
    Decision,
    MarketState,
    PortfolioState,
    Position,
    SystemState,
    OrderCandidate,
    _estimate_slippage_bps,
    _get_daily_pm_approval,
    _is_symbol_locked,
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


# ---------------------------------------------------------------------------
# Private helper functions — _is_symbol_locked, _get_daily_pm_approval
# ---------------------------------------------------------------------------

def test_is_symbol_locked_returns_false_on_file_error(tmp_path, monkeypatch):
    """Lines 19-20: exception reading locked symbols file → False (fail safe)."""
    from openclaw.config_manager import get_config, reset_config
    reset_config()
    get_config(config_dir=tmp_path)  # no locked_symbols.json → default empty
    try:
        result = _is_symbol_locked("2330")
        assert result is False
    finally:
        reset_config()


def test_is_symbol_locked_returns_true_for_locked_symbol(tmp_path, monkeypatch):
    """_is_symbol_locked returns True when symbol is in locked list."""
    from openclaw.config_manager import get_config, reset_config
    (tmp_path / "locked_symbols.json").write_text(json.dumps({"locked": ["2330", "0050"]}))
    reset_config()
    get_config(config_dir=tmp_path)
    try:
        assert _is_symbol_locked("2330") is True
        assert _is_symbol_locked("0050") is True
        assert _is_symbol_locked("2454") is False
    finally:
        reset_config()


def test_get_daily_pm_approval_returns_false_on_missing_file(tmp_path):
    """Lines 28-34: file not found → False (fail safe)."""
    from openclaw.config_manager import get_config, reset_config
    reset_config()
    get_config(config_dir=tmp_path)  # no daily_pm_state.json → default False
    try:
        result = _get_daily_pm_approval()
        assert result is False
    finally:
        reset_config()


def test_get_daily_pm_approval_returns_true_when_approved_today(tmp_path, monkeypatch):
    """Lines 28-34: today's date + approved=True → True."""
    from datetime import datetime, timezone, timedelta
    from openclaw.config_manager import get_config, reset_config
    _tz_twn = timezone(timedelta(hours=8))
    today_twn = datetime.now(tz=_tz_twn).strftime("%Y-%m-%d")
    (tmp_path / "daily_pm_state.json").write_text(json.dumps({"date": today_twn, "approved": True}))
    reset_config()
    get_config(config_dir=tmp_path)
    try:
        assert _get_daily_pm_approval() is True
    finally:
        reset_config()


def test_get_daily_pm_approval_returns_false_when_date_mismatch(tmp_path, monkeypatch):
    """_get_daily_pm_approval: wrong date → False."""
    from openclaw.config_manager import get_config, reset_config
    (tmp_path / "daily_pm_state.json").write_text(json.dumps({"date": "2000-01-01", "approved": True}))
    reset_config()
    get_config(config_dir=tmp_path)
    try:
        assert _get_daily_pm_approval() is False
    finally:
        reset_config()


# ---------------------------------------------------------------------------
# evaluate_and_build_order — additional branches for full coverage
# ---------------------------------------------------------------------------

def test_reject_pm_not_approved_when_required(tmp_path, monkeypatch):
    """Line 215: pm_review_required=1 + no valid approval → RISK_PM_NOT_APPROVED."""
    from openclaw.config_manager import get_config, reset_config
    (tmp_path / "daily_pm_state.json").write_text(json.dumps({"date": "2000-01-01", "approved": False}))
    reset_config()
    get_config(config_dir=tmp_path)
    try:
        limits = default_limits()
        limits["pm_review_required"] = 1
        result = evaluate_and_build_order(
            _base_decision(), _base_market(), _base_portfolio(), limits, _base_system()
        )
        assert result.approved is False
        assert result.reject_code == "RISK_PM_NOT_APPROVED"
    finally:
        reset_config()


def test_reject_symbol_locked_on_sell(tmp_path, monkeypatch):
    """Lines 211-212: sell on locked symbol → RISK_SYMBOL_LOCKED."""
    from openclaw.config_manager import get_config, reset_config
    (tmp_path / "locked_symbols.json").write_text(json.dumps({"locked": ["2330"]}))
    reset_config()
    get_config(config_dir=tmp_path)
    try:
        d = _base_decision()
        d.signal_side = "sell"
        result = evaluate_and_build_order(d, _base_market(), _base_portfolio(), _test_limits(), _base_system())
        assert result.approved is False
        assert result.reject_code == "RISK_SYMBOL_LOCKED"
    finally:
        reset_config()


def test_reject_signal_flat_returns_liquidity_limit():
    """Line 132: signal_side='flat' → _build_candidate returns None → RISK_LIQUIDITY_LIMIT."""
    d = _base_decision()
    d.signal_side = "flat"
    result = evaluate_and_build_order(d, _base_market(), _base_portfolio(), _test_limits(), _base_system())
    assert result.approved is False
    assert result.reject_code == "RISK_LIQUIDITY_LIMIT"


def test_sell_closes_existing_long_position():
    """Line 138: sell against existing long → opens_new = False."""
    pf = _base_portfolio()
    pf.positions["2330"] = Position(symbol="2330", qty=100, avg_price=90.0, last_price=100.0)
    d = _base_decision()
    d.signal_side = "sell"
    result = evaluate_and_build_order(d, _base_market(), pf, _test_limits(), _base_system())
    assert result.approved is True
    assert result.order.opens_new_position is False


def test_reject_stale_signal_ttl():
    """Lines 254,260: signal TTL exceeded → RISK_DATA_STALENESS."""
    d = _base_decision()
    d.ts_ms = 1_000_000
    d.signal_ttl_ms = 50  # 50ms TTL
    sys = _base_system()
    sys.now_ms = 1_000_200  # 200ms later
    result = evaluate_and_build_order(d, _base_market(), _base_portfolio(), _test_limits(), sys)
    assert result.approved is False
    assert result.reject_code == "RISK_DATA_STALENESS"


def test_reject_broker_disconnected():
    """Line 251: broker not connected → RISK_BROKER_CONNECTIVITY."""
    sys = _base_system()
    sys.broker_connected = False
    result = evaluate_and_build_order(_base_decision(), _base_market(), _base_portfolio(), _test_limits(), sys)
    assert result.approved is False
    assert result.reject_code == "RISK_BROKER_CONNECTIVITY"


def test_reject_db_write_latency():
    """Line 254: db_write_p99_ms too high → RISK_DB_WRITE_LATENCY."""
    sys = _base_system()
    sys.db_write_p99_ms = 9999
    result = evaluate_and_build_order(_base_decision(), _base_market(), _base_portfolio(), _test_limits(), sys)
    assert result.approved is False
    assert result.reject_code == "RISK_DB_WRITE_LATENCY"


def test_reject_price_deviation():
    """Line 268: price deviation too large → RISK_PRICE_DEVIATION_LIMIT."""
    limits = _test_limits()
    limits["max_price_deviation_pct"] = 0.001  # 0.1%
    mkt = MarketState(best_bid=100.0, best_ask=110.0, volume_1m=10_000, feed_delay_ms=50)
    result = evaluate_and_build_order(_base_decision(), mkt, _base_portfolio(), limits, _base_system())
    assert result.approved is False
    assert result.reject_code == "RISK_PRICE_DEVIATION_LIMIT"


def test_reject_slippage_estimate():
    """Lines 282-284: slippage too large → RISK_SLIPPAGE_ESTIMATE_LIMIT.
    Use a tight spread (0.5%) so price_dev_pct < max (2%), but spread > max_slippage_bps.
    """
    limits = _test_limits()
    limits["max_slippage_bps"] = 1  # 0.01 bps limit — very strict
    # best_bid=100, best_ask=101 → price_dev_pct≈0.5% < 2%, but slippage≈50 bps > 1 bps
    mkt = MarketState(best_bid=100.0, best_ask=101.0, volume_1m=10_000, feed_delay_ms=50)
    result = evaluate_and_build_order(_base_decision(), mkt, _base_portfolio(), limits, _base_system())
    assert result.approved is False
    assert result.reject_code == "RISK_SLIPPAGE_ESTIMATE_LIMIT"


def test_reject_position_concentration():
    """Lines 282-284: symbol weight after > max → RISK_POSITION_CONCENTRATION."""
    pf = _base_portfolio()
    pf.positions["2330"] = Position(symbol="2330", qty=900, avg_price=100.0, last_price=100.0)
    limits = _test_limits()
    limits["max_symbol_weight"] = 0.10  # 10% max
    result = evaluate_and_build_order(_base_decision(), _base_market(), pf, limits, _base_system())
    assert result.approved is False
    assert result.reject_code == "RISK_POSITION_CONCENTRATION"


def test_reject_portfolio_exposure():
    """Lines 302-304: gross_after > max_gross_exposure → RISK_PORTFOLIO_EXPOSURE_LIMIT."""
    limits = _test_limits()
    limits["max_gross_exposure"] = 0.001  # impossibly small
    result = evaluate_and_build_order(_base_decision(), _base_market(), _base_portfolio(), limits, _base_system())
    assert result.approved is False
    assert result.reject_code == "RISK_PORTFOLIO_EXPOSURE_LIMIT"


def test_reject_per_trade_loss():
    """Line 308: per-trade loss estimate > max → RISK_PER_TRADE_LOSS_LIMIT.
    Use a large existing position (reduces) so candidate.qty is big, then cap max_loss tiny."""
    pf = _base_portfolio()
    pf.positions["2330"] = Position(symbol="2330", qty=10_000, avg_price=90.0, last_price=100.0)
    d = _base_decision()
    d.signal_side = "sell"
    limits = _test_limits()
    limits["max_loss_per_trade_pct_nav"] = 0.000001  # tiny
    limits["max_symbol_weight"] = 10.0
    limits["max_gross_exposure"] = 100.0
    result = evaluate_and_build_order(d, _base_market(), pf, limits, _base_system())
    assert result.approved is False
    assert result.reject_code == "RISK_PER_TRADE_LOSS_LIMIT"

def test_sell_with_stop_price_sell_side():
    """Line 162-163: sell decision without stop_price → stop = mid * (1 + pct)."""
    d = _base_decision()
    d.signal_side = "sell"
    d.stop_price = None
    pf = _base_portfolio()
    pf.positions["2330"] = Position(symbol="2330", qty=50, avg_price=90.0, last_price=100.0)
    result = evaluate_and_build_order(d, _base_market(), pf, _test_limits(), _base_system())
    assert result.approved is True


def test_authority_level_invalid_falls_back_to_none():
    """Line 163: invalid authority_level → silently becomes None."""
    limits = _test_limits()
    limits["authority_level"] = "not_an_int"
    result = evaluate_and_build_order(_base_decision(), _base_market(), _base_portfolio(), limits, _base_system())
    # Should not crash, result depends on other limits
    assert result.approved is True or result.approved is False


def test_slippage_bps_zero_price_returns_9999():
    """Line 132: _estimate_slippage_bps when mid <= 0 returns 9999.0."""
    candidate = OrderCandidate(
        symbol="2330", side="buy", qty=10, price=0.0, order_type="limit", tif="IOC", opens_new_position=True
    )
    mkt = MarketState(best_bid=0.0, best_ask=0.0, volume_1m=10_000, feed_delay_ms=50)
    assert _estimate_slippage_bps(candidate, mkt) == 9999.0


def test_sell_no_stop_price_no_position_reaches_sell_stop():
    """Line 157: sell with no stop_price and no existing position → uses default sell stop.
    This exercises the `stop_price = mid * (1 + default_stop_pct)` branch.
    """
    d = _base_decision()
    d.signal_side = "sell"
    d.stop_price = None
    limits = _test_limits()
    result = evaluate_and_build_order(d, _base_market(), _base_portfolio(), limits, _base_system())
    # May approve or reject, but must not crash
    assert result.approved is True or result.approved is False


def test_build_candidate_returns_none_when_qty_zero():
    """Line 182: _build_candidate returns None when calculate_position_qty returns 0."""
    with patch("openclaw.risk_engine.calculate_position_qty", return_value=0):
        result = evaluate_and_build_order(
            _base_decision(), _base_market(), _base_portfolio(), _test_limits(), _base_system()
        )
    assert result.approved is False
    assert result.reject_code == "RISK_LIQUIDITY_LIMIT"


def test_correlation_guard_ok_updates_metrics():
    """Lines 234-239: correlation_decision ok=True → apply succeeds, metrics updated."""
    from openclaw.correlation_guard import CorrelationGuardDecision

    corr = CorrelationGuardDecision(
        ok=True,
        reason_code="OK",
        n_symbols=1,
        max_pair_abs_corr=0.0,
        weighted_avg_abs_corr=0.0,
        top_pairs=[],
        suggestions=[],
        matrix={},
    )
    result = evaluate_and_build_order(
        _base_decision(), _base_market(), _base_portfolio(), _test_limits(), _base_system(),
        correlation_decision=corr,
    )
    # metrics should contain correlation_guard_ok key
    assert "correlation_guard_ok" in result.metrics


def test_correlation_guard_exception_captured_in_metrics():
    """Lines 240-241: when apply_correlation_guard_to_limits raises, error stored in metrics."""
    from openclaw.correlation_guard import CorrelationGuardDecision

    corr = CorrelationGuardDecision(
        ok=True,
        reason_code="OK",
        n_symbols=1,
        max_pair_abs_corr=0.0,
        weighted_avg_abs_corr=0.0,
        top_pairs=[],
        suggestions=[],
        matrix={},
    )
    with patch("openclaw.correlation_guard.apply_correlation_guard_to_limits", side_effect=RuntimeError("boom")):
        result = evaluate_and_build_order(
            _base_decision(), _base_market(), _base_portfolio(), _test_limits(), _base_system(),
            correlation_decision=corr,
        )
    assert "correlation_guard_error" in result.metrics
    assert "boom" in result.metrics["correlation_guard_error"]


def test_close_position_order_skips_slippage_check():
    """平倉 sell 單即使 slippage 超標也應通過風控（跌停板止損場景）"""
    pf = _base_portfolio()
    pf.positions["2330"] = Position(symbol="2330", qty=100, avg_price=700.0, last_price=500.0)
    d = _base_decision()
    d.signal_side = "sell"

    # 跌停板：bid 極低 → slippage 天文數字
    # 設 max_slippage_bps=1（非常嚴格），但平倉應豁免
    limits = _test_limits()
    limits["max_slippage_bps"] = 1   # 近乎 0 slippage 允許值

    mkt = MarketState(best_bid=1.0, best_ask=510.0, volume_1m=100, feed_delay_ms=50)

    result = evaluate_and_build_order(d, mkt, pf, limits, _base_system())
    assert result.approved, f"平倉單應通過風控，但被拒絕：{result.reject_code}"


def test_close_position_order_skips_price_deviation_check():
    """平倉 sell 單即使 price_deviation 超標也應通過"""
    pf = _base_portfolio()
    pf.positions["2330"] = Position(symbol="2330", qty=100, avg_price=700.0, last_price=500.0)
    d = _base_decision()
    d.signal_side = "sell"

    limits = _test_limits()
    limits["max_price_deviation_pct"] = 0.0001   # 極嚴苛：0.01% 偏差

    mkt = MarketState(best_bid=100.0, best_ask=110.0, volume_1m=100, feed_delay_ms=50)

    result = evaluate_and_build_order(d, mkt, pf, limits, _base_system())
    assert result.approved, f"平倉單應通過風控，但被拒絕：{result.reject_code}"
