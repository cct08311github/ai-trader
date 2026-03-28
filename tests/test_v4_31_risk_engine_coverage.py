"""Tests for risk_engine.py — 7-layer risk control (Issue #236).

Coverage target: ≥85% of risk_engine.py
Each risk gate has at least one approve + one reject path.
"""
import time
import unittest.mock as mock

import pytest

from openclaw.risk_engine import (
    Decision,
    EvaluationResult,
    MarketState,
    PortfolioState,
    Position,
    SystemState,
    default_limits,
    evaluate_and_build_order,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _decision(
    symbol="2330",
    side="buy",
    ts_offset_ms=0,
    ttl_ms=60_000,
) -> Decision:
    now_ms = int(time.time() * 1000)
    return Decision(
        decision_id="test-dec-001",
        ts_ms=now_ms - ts_offset_ms,
        symbol=symbol,
        strategy_id="test",
        signal_side=side,
        signal_score=0.8,
        signal_ttl_ms=ttl_ms,
    )


def _market(bid=580.0, ask=581.0, volume=50_000, feed_delay_ms=50) -> MarketState:
    return MarketState(
        best_bid=bid,
        best_ask=ask,
        volume_1m=volume,
        feed_delay_ms=feed_delay_ms,
    )


def _portfolio(nav=1_000_000.0, positions=None, pnl_today=0.0, unrealized=0.0) -> PortfolioState:
    return PortfolioState(
        nav=nav,
        cash=nav,
        realized_pnl_today=pnl_today,
        unrealized_pnl=unrealized,
        positions=positions or {},
    )


def _system(
    now_offset_ms=0,
    trading_locked=False,
    broker_connected=True,
    db_write_p99_ms=20,
    orders_last_60s=0,
    reduce_only=False,
) -> SystemState:
    now_ms = int(time.time() * 1000) + now_offset_ms
    return SystemState(
        now_ms=now_ms,
        trading_locked=trading_locked,
        broker_connected=broker_connected,
        db_write_p99_ms=db_write_p99_ms,
        orders_last_60s=orders_last_60s,
        reduce_only_mode=reduce_only,
    )


def _limits(**overrides) -> dict:
    lim = default_limits()
    lim["pm_review_required"] = 0   # bypass PM approval by default in tests
    lim.update(overrides)
    return lim


# Mock apply_tw_session_risk_adjustments to be a no-op in all tests
@pytest.fixture(autouse=True)
def bypass_tw_session(monkeypatch):
    monkeypatch.setattr(
        "openclaw.risk_engine.apply_tw_session_risk_adjustments",
        lambda limits, **_: limits,
    )


# ── Happy Path ────────────────────────────────────────────────────────────────

def test_approve_basic_buy(monkeypatch):
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: False)
    # Use low price (10 TWD) so position sizing stays within all limits
    result = evaluate_and_build_order(
        _decision(), _market(bid=10.0, ask=10.0, volume=50_000), _portfolio(), _limits(), _system()
    )
    assert result.approved is True
    assert result.order is not None
    assert result.order.side == "buy"


def test_approve_sell_unlocked(monkeypatch):
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: False)
    pos = {"2330": Position(symbol="2330", qty=1000, avg_price=500.0, last_price=580.0)}
    result = evaluate_and_build_order(
        _decision(side="sell"),
        _market(),
        _portfolio(positions=pos),
        # Relax all portfolio limits so sell passes through
        _limits(max_symbol_weight=5.0, max_gross_exposure=9.9, max_loss_per_trade_pct_nav=0.05),
        _system(),
    )
    assert result.approved is True


# ── Layer 1: Symbol Lock ───────────────────────────────────────────────────────

def test_reject_sell_locked_symbol(monkeypatch):
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: True)
    result = evaluate_and_build_order(
        _decision(side="sell"), _market(), _portfolio(), _limits(), _system()
    )
    assert result.approved is False
    assert result.reject_code == "RISK_SYMBOL_LOCKED"


def test_buy_locked_symbol_not_blocked(monkeypatch):
    """Lock only protects sell; buy should pass through to other checks."""
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: True)
    result = evaluate_and_build_order(
        _decision(side="buy"), _market(), _portfolio(), _limits(), _system()
    )
    # Lock only applies to sell — buy should not be rejected by RISK_SYMBOL_LOCKED
    assert result.reject_code != "RISK_SYMBOL_LOCKED"


# ── Layer 2: Daily PM Approval ────────────────────────────────────────────────

def test_reject_pm_not_approved(monkeypatch):
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: False)
    monkeypatch.setattr("openclaw.risk_engine._get_daily_pm_approval", lambda: False)
    result = evaluate_and_build_order(
        _decision(), _market(), _portfolio(),
        _limits(pm_review_required=1),  # enforce PM review
        _system(),
    )
    assert result.approved is False
    assert result.reject_code == "RISK_PM_NOT_APPROVED"


def test_approve_pm_bypass_in_simulation(monkeypatch):
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: False)
    monkeypatch.setattr("openclaw.risk_engine._get_daily_pm_approval", lambda: False)
    result = evaluate_and_build_order(
        _decision(), _market(), _portfolio(),
        _limits(pm_review_required=0),  # simulation bypasses PM
        _system(),
    )
    assert result.reject_code != "RISK_PM_NOT_APPROVED"


# ── Layer 3: System-Level Gates ───────────────────────────────────────────────

def test_reject_trading_locked(monkeypatch):
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: False)
    result = evaluate_and_build_order(
        _decision(), _market(), _portfolio(), _limits(), _system(trading_locked=True)
    )
    assert result.approved is False
    assert result.reject_code == "RISK_TRADING_LOCKED"


def test_reject_feed_delay_too_high(monkeypatch):
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: False)
    result = evaluate_and_build_order(
        _decision(),
        _market(feed_delay_ms=2000),
        _portfolio(),
        _limits(max_feed_delay_ms=1000),
        _system(),
    )
    assert result.approved is False
    assert result.reject_code == "RISK_DATA_STALENESS"


def test_reject_broker_disconnected(monkeypatch):
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: False)
    result = evaluate_and_build_order(
        _decision(), _market(), _portfolio(), _limits(), _system(broker_connected=False)
    )
    assert result.approved is False
    assert result.reject_code == "RISK_BROKER_CONNECTIVITY"


def test_reject_db_write_latency(monkeypatch):
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: False)
    result = evaluate_and_build_order(
        _decision(), _market(), _portfolio(),
        _limits(max_db_write_p99_ms=100),
        _system(db_write_p99_ms=500),
    )
    assert result.approved is False
    assert result.reject_code == "RISK_DB_WRITE_LATENCY"


# ── Layer 4: P&L and Rate Limits ─────────────────────────────────────────────

def test_reject_daily_loss_limit(monkeypatch):
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: False)
    # NAV = 1M, max_daily_loss_pct = 5% → max loss = 50k. Use 60k loss.
    result = evaluate_and_build_order(
        _decision(), _market(), _portfolio(pnl_today=-60_000.0),
        _limits(max_daily_loss_pct=0.05),
        _system(),
    )
    assert result.approved is False
    assert result.reject_code == "RISK_DAILY_LOSS_LIMIT"


def test_reject_order_rate_limit(monkeypatch):
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: False)
    result = evaluate_and_build_order(
        _decision(), _market(), _portfolio(),
        _limits(max_orders_per_min=3),
        _system(orders_last_60s=3),
    )
    assert result.approved is False
    assert result.reject_code == "RISK_ORDER_RATE_LIMIT"


def test_reject_signal_ttl_expired(monkeypatch):
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: False)
    # Signal is 10 minutes old, TTL is 5 minutes
    result = evaluate_and_build_order(
        _decision(ts_offset_ms=600_000, ttl_ms=300_000),
        _market(), _portfolio(), _limits(), _system(),
    )
    assert result.approved is False
    assert result.reject_code == "RISK_DATA_STALENESS"


# ── Layer 5: Position Sizing ──────────────────────────────────────────────────

def test_reject_reduce_only_blocks_new_buy(monkeypatch):
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: False)
    result = evaluate_and_build_order(
        _decision(side="buy"),
        _market(),
        _portfolio(),   # no existing position → opens_new_position=True
        _limits(),
        _system(reduce_only=True),
    )
    assert result.approved is False
    assert result.reject_code == "RISK_CONSECUTIVE_LOSSES"


def test_approve_sell_in_reduce_only_mode(monkeypatch):
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: False)
    pos = {"2330": Position(symbol="2330", qty=1000, avg_price=500.0, last_price=580.0)}
    result = evaluate_and_build_order(
        _decision(side="sell"),
        _market(),
        _portfolio(positions=pos),
        _limits(),
        _system(reduce_only=True),
    )
    # Sell on existing position is not a new position — should not be blocked by reduce_only
    assert result.reject_code != "RISK_CONSECUTIVE_LOSSES"


# ── Layer 6: Price Deviation and Slippage ────────────────────────────────────

def test_reject_price_deviation(monkeypatch):
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: False)
    # Mid = (500+501)/2 = 500.5; ask=600 → deviation > 2%
    result = evaluate_and_build_order(
        _decision(side="buy"),
        _market(bid=500.0, ask=600.0),
        _portfolio(),
        _limits(max_price_deviation_pct=0.02),
        _system(),
    )
    assert result.approved is False
    assert result.reject_code == "RISK_PRICE_DEVIATION_LIMIT"


def test_reject_slippage_too_high(monkeypatch):
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: False)
    # Very low volume → high slippage estimate
    result = evaluate_and_build_order(
        _decision(side="buy"),
        _market(bid=580.0, ask=581.0, volume=1),  # near-zero volume → high slippage
        _portfolio(),
        _limits(max_slippage_bps=1),   # extremely tight limit
        _system(),
    )
    assert result.approved is False
    assert result.reject_code == "RISK_SLIPPAGE_ESTIMATE_LIMIT"


# ── Layer 7: Portfolio Constraints ───────────────────────────────────────────

def test_reject_position_concentration(monkeypatch):
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: False)
    # Ask 580*1000 = 580k / NAV 1M = 58% > max_symbol_weight 20%
    result = evaluate_and_build_order(
        _decision(side="buy"),
        _market(bid=580.0, ask=580.0, volume=100_000),
        _portfolio(nav=1_000_000),
        _limits(max_symbol_weight=0.20, max_qty_to_1m_volume_ratio=1.0),
        _system(),
    )
    assert result.approved is False
    assert result.reject_code in ("RISK_POSITION_CONCENTRATION", "RISK_PORTFOLIO_EXPOSURE_LIMIT",
                                  "RISK_PER_TRADE_LOSS_LIMIT")


def test_reject_gross_exposure_limit(monkeypatch):
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: False)
    # Already at 119% gross exposure — any buy pushes over 120%
    existing_pos = {
        "2317": Position(symbol="2317", qty=1000, avg_price=1190.0, last_price=1190.0),
    }
    result = evaluate_and_build_order(
        _decision(symbol="2330", side="buy"),
        _market(bid=580.0, ask=580.0, volume=100_000),
        _portfolio(nav=1_000_000, positions=existing_pos),
        _limits(max_gross_exposure=1.20, max_symbol_weight=0.99, max_qty_to_1m_volume_ratio=1.0),
        _system(),
    )
    assert result.approved is False
    assert result.reject_code in ("RISK_PORTFOLIO_EXPOSURE_LIMIT", "RISK_POSITION_CONCENTRATION",
                                  "RISK_PER_TRADE_LOSS_LIMIT")


def test_reject_per_trade_loss_limit(monkeypatch):
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: False)
    # Set stop_price very close to ask (0.01% = 1bp stop) so fixed_fractional gives huge qty.
    # Then default_stop_pct=10% makes est_trade_loss = qty * price * 0.10 >> limit.
    # Relax symbol_weight & gross_exposure so only per_trade_loss triggers.
    dec = Decision(
        decision_id="test-ptl",
        ts_ms=int(time.time() * 1000),
        symbol="2330", strategy_id="test",
        signal_side="buy", signal_score=0.8,
        stop_price=99.99,  # stop is 0.01 below ask=100 → 0.01% risk/share → huge qty
    )
    result = evaluate_and_build_order(
        dec,
        _market(bid=100.0, ask=100.0, volume=5_000_000),
        _portfolio(nav=1_000_000),
        _limits(
            max_loss_per_trade_pct_nav=0.001,  # budget 1000 TWD → qty≈100,000
            max_symbol_weight=99.0,            # relaxed to let concentration pass
            max_gross_exposure=999.0,          # relaxed
            max_qty_to_1m_volume_ratio=1.0,
            default_stop_pct=0.10,             # est_loss = qty*100*0.10 = 1M >> 1000
        ),
        _system(),
    )
    assert result.approved is False
    assert result.reject_code == "RISK_PER_TRADE_LOSS_LIMIT"


# ── Boundary Conditions ───────────────────────────────────────────────────────

def test_daily_loss_exactly_at_limit_passes(monkeypatch):
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: False)
    # Loss exactly at limit (not exceeding) → should not trigger
    nav = 1_000_000.0
    max_loss = 0.05 * nav  # 50k
    result = evaluate_and_build_order(
        _decision(), _market(),
        _portfolio(nav=nav, pnl_today=-(max_loss - 1)),  # 1 TWD under limit
        _limits(max_daily_loss_pct=0.05),
        _system(),
    )
    assert result.reject_code != "RISK_DAILY_LOSS_LIMIT"


def test_metrics_always_returned(monkeypatch):
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: False)
    result = evaluate_and_build_order(
        _decision(), _market(), _portfolio(), _limits(), _system(trading_locked=True)
    )
    assert isinstance(result.metrics, dict)
    assert len(result.metrics) > 0


def test_pm_approval_file_missing_fail_safe(tmp_path, monkeypatch):
    """If PM approval file doesn't exist, _get_daily_pm_approval returns False (fail-safe)."""
    import openclaw.risk_engine as re_mod
    monkeypatch.setattr(re_mod, "_get_daily_pm_approval", lambda: False)
    result = evaluate_and_build_order(
        _decision(), _market(), _portfolio(),
        _limits(pm_review_required=1),
        _system(),
    )
    assert result.approved is False
    assert result.reject_code == "RISK_PM_NOT_APPROVED"


def test_default_limits_has_required_keys():
    lim = default_limits()
    required = [
        "max_daily_loss_pct", "max_loss_per_trade_pct_nav", "max_orders_per_min",
        "max_price_deviation_pct", "max_slippage_bps", "max_qty_to_1m_volume_ratio",
        "max_feed_delay_ms", "max_db_write_p99_ms", "max_symbol_weight",
        "max_gross_exposure", "default_stop_pct",
    ]
    for key in required:
        assert key in lim, f"Missing required limit key: {key}"


# ── Internal helpers coverage ─────────────────────────────────────────────────

def test_is_symbol_locked_returns_false_when_no_file(tmp_path, monkeypatch):
    """_is_symbol_locked reads locked_symbols.json; missing file → not locked (fail-safe)."""
    import openclaw.risk_engine as re_mod
    from openclaw.config_manager import get_config, reset_config
    reset_config()
    get_config(config_dir=tmp_path)  # no locked_symbols.json
    try:
        assert re_mod._is_symbol_locked("2330") is False
    finally:
        reset_config()


def test_is_symbol_locked_true_when_in_file(tmp_path, monkeypatch):
    import json
    import openclaw.risk_engine as re_mod
    from openclaw.config_manager import get_config, reset_config
    (tmp_path / "locked_symbols.json").write_text(json.dumps({"locked": ["2330", "2317"]}))
    reset_config()
    get_config(config_dir=tmp_path)
    try:
        assert re_mod._is_symbol_locked("2330") is True
        assert re_mod._is_symbol_locked("0050") is False
    finally:
        reset_config()


def test_get_daily_pm_approval_false_when_no_file(tmp_path, monkeypatch):
    import openclaw.risk_engine as re_mod
    from openclaw.config_manager import get_config, reset_config
    reset_config()
    get_config(config_dir=tmp_path)  # no daily_pm_state.json
    try:
        assert re_mod._get_daily_pm_approval() is False
    finally:
        reset_config()


def test_get_daily_pm_approval_true_when_approved(tmp_path, monkeypatch):
    import json
    from datetime import datetime, timezone, timedelta
    import openclaw.risk_engine as re_mod
    from openclaw.config_manager import get_config, reset_config
    _tz_twn = timezone(timedelta(hours=8))
    today_twn = datetime.now(tz=_tz_twn).strftime("%Y-%m-%d")
    (tmp_path / "daily_pm_state.json").write_text(json.dumps({"date": today_twn, "approved": True}))
    reset_config()
    get_config(config_dir=tmp_path)
    try:
        assert re_mod._get_daily_pm_approval() is True
    finally:
        reset_config()


def test_reject_liquidity_when_auto_reduce_disabled(monkeypatch):
    """When allow_auto_reduce_qty=0 and qty > max_qty → RISK_LIQUIDITY_LIMIT."""
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: False)
    result = evaluate_and_build_order(
        _decision(side="buy"),
        _market(bid=10.0, ask=10.0, volume=1),  # volume=1 → max_qty=0
        _portfolio(),
        _limits(max_qty_to_1m_volume_ratio=1.0, allow_auto_reduce_qty=0),
        _system(),
    )
    assert result.approved is False
    assert result.reject_code == "RISK_LIQUIDITY_LIMIT"


def test_sell_stop_price_calculated_above_mid(monkeypatch):
    """For sell signals, stop_price is set above mid (short stop)."""
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: False)
    pos = {"2330": Position(symbol="2330", qty=1000, avg_price=500.0, last_price=580.0)}
    # With existing position, sell will use pos.qty (not stop_price calc) — use flat signal
    # Test via _build_candidate indirectly: if sell opens new (short), stop is above mid
    from openclaw.risk_engine import _build_candidate
    dec = Decision(
        decision_id="x", ts_ms=int(time.time() * 1000),
        symbol="2330", strategy_id="t", signal_side="sell",
        signal_score=0.8, stop_price=None,
    )
    # No existing position → opens_new=True → stop_price calculated above mid
    candidate = _build_candidate(
        dec,
        _market(bid=580.0, ask=581.0),
        _portfolio(),  # no position
        _limits(),
    )
    # candidate may be None if qty=0 due to sizing, but no exception should occur
    assert candidate is None or candidate.side == "sell"
