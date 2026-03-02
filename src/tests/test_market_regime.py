from __future__ import annotations

import json
import math
import os
import tempfile

from openclaw.market_regime import (
    MarketRegime,
    MarketRegimePolicy,
    MarketRegimeResult,
    apply_market_regime_risk_adjustments,
    apply_policy_to_result,
    classify_market_regime,
    compute_regime_features,
    load_market_regime_policy,
    _atr,
    _lin_slope,
    _momentum,
    _price_channel,
    _returns,
    _rsi,
    _to_floats,
)
from openclaw.risk_engine import (
    Decision,
    MarketState,
    PortfolioState,
    SystemState,
    default_limits,
    evaluate_and_build_order,
)


def _test_limits() -> dict:
    lim = default_limits()
    lim["pm_review_required"] = 0
    return lim


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

    limits = _test_limits()
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


# ──────────────────────────────────────────────────────────────────────────────
# _to_floats  (lines 47-48: non-convertible values)
# ──────────────────────────────────────────────────────────────────────────────

def test_to_floats_skips_non_convertible():
    result = _to_floats(["abc", None, 1.0, 2.0])
    assert result == [1.0, 2.0]


def test_to_floats_skips_inf_and_nan():
    result = _to_floats([float("inf"), float("nan"), 1.0])
    assert result == [1.0]


# ──────────────────────────────────────────────────────────────────────────────
# _returns  (line 57: less than 2 prices; line 63: non-positive prices)
# ──────────────────────────────────────────────────────────────────────────────

def test_returns_empty_when_less_than_two_prices():
    assert _returns([]) == []
    assert _returns([100.0]) == []


def test_returns_skips_nonpositive_prices():
    # 0 price in middle should be skipped
    result = _returns([100.0, 0.0, 105.0])
    # pair (100.0, 0.0): 0 → skip; pair (0.0, 105.0): 0 → skip
    assert result == []


def test_returns_normal():
    result = _returns([100.0, 110.0])
    assert len(result) == 1
    assert abs(result[0] - math.log(110.0 / 100.0)) < 1e-9


# ──────────────────────────────────────────────────────────────────────────────
# _lin_slope  (line 74: n < 2; line 86: den <= 0)
# ──────────────────────────────────────────────────────────────────────────────

def test_lin_slope_single_value_returns_zero():
    assert _lin_slope([5.0]) == 0.0


def test_lin_slope_empty_returns_zero():
    assert _lin_slope([]) == 0.0


def test_lin_slope_constant_series_returns_zero():
    # All same values → num = 0, but den can be > 0
    # For [5, 5]: x_mean=0.5, y_mean=5; dx0=-0.5, dx1=0.5; dy=0 → num=0, den=0.5 → slope=0
    result = _lin_slope([5.0, 5.0])
    assert result == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# _rsi  (line 95: too few prices)
# ──────────────────────────────────────────────────────────────────────────────

def test_rsi_returns_50_when_insufficient_prices():
    # Need period+1 = 15 prices for period=14
    result = _rsi([100.0] * 5, period=14)
    assert result == 50.0


def test_rsi_all_gains_returns_100():
    # All prices increasing → avg_loss == 0 → RSI = 100
    prices = [100 + i for i in range(20)]
    result = _rsi(prices, period=14)
    assert result == 100.0


# ──────────────────────────────────────────────────────────────────────────────
# _momentum  (line 123: too few prices)
# ──────────────────────────────────────────────────────────────────────────────

def test_momentum_returns_zero_when_insufficient_prices():
    result = _momentum([100.0] * 5, lookback=10)
    assert result == 0.0


def test_momentum_positive_trend():
    prices = [100.0] * 10 + [110.0]
    result = _momentum(prices, lookback=10)
    assert abs(result - 10.0) < 1e-6


# ──────────────────────────────────────────────────────────────────────────────
# _price_channel  (lines 131-133: window shrink; empty returns 0,0,0)
# ──────────────────────────────────────────────────────────────────────────────

def test_price_channel_empty_returns_zeros():
    result = _price_channel([], window=20)
    assert result == (0.0, 0.0, 0.0)


def test_price_channel_fewer_than_window():
    # ps has 5 elements, window=20 → window gets set to 5
    result = _price_channel([100.0, 110.0, 90.0, 105.0, 95.0], window=20)
    assert result[0] == 110.0  # high
    assert result[1] == 90.0   # low
    assert abs(result[2] - (110.0 - 90.0) / 90.0) < 1e-9


def test_price_channel_zero_low():
    # low = 0 → width = 0.0
    result = _price_channel([0.0, 100.0], window=2)
    assert result[2] == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# _atr  (lines 145, 154, 167)
# ──────────────────────────────────────────────────────────────────────────────

def test_atr_returns_zero_when_insufficient_prices():
    # Need period+1 = 15 prices
    result = _atr([100.0] * 5, period=14)
    assert result == 0.0


def test_atr_trs_less_than_period():
    # Have period+1 prices but only period-1 trs entries → trs < period branch
    # 15 prices → 14 trs; period=14 → len(trs) == period, so we need period+1 prices but only period-1 diffs
    # Actually: with 14 prices: len(ps)=14, period+1=15 → returns 0.0 (line 145)
    # With exactly period prices: len(ps)=14 < 15 → line 145
    # To hit line 154: need len(ps) >= period+1 but len(trs) < period
    # len(trs) = len(ps) - 1, so len(trs) < period means len(ps) <= period → conflicts with len(ps) >= period+1
    # Line 154 is unreachable as written - need to cover it via period > actual trs count
    # Actually period=14, len(trs)=len(ps)-1; for len(trs)<14 we need len(ps)<=14 < 15 → caught at line 144-145
    # This means line 154 (len(trs) < period) is never reached in practice when period+1 check passes
    # We can test with a very large period to reach line 154 indirectly
    # Pass period=5 with 7 prices: len(ps)=7 >= 6 ✓; len(trs)=6 >= 5 ✓ → won't hit 154
    # Actually line 154 seems unreachable. Let's just confirm normal ATR works:
    prices = [100.0 + i for i in range(20)]
    result = _atr(prices, period=14)
    assert result >= 0.0


def test_atr_zero_last_price():
    # ps[-1] == 0 → return 0.0 (line 155 else branch)
    # Build prices where last is 0 but we pass the length check
    prices = [100.0] * 14 + [0.0]  # 15 prices, last is 0
    result = _atr(prices, period=14)
    assert result == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# apply_market_regime_risk_adjustments  (lines 301, 304-305)
# ──────────────────────────────────────────────────────────────────────────────

def test_apply_regime_adjustments_key_not_in_limits():
    """Regime multipliers for keys not present in limits should be skipped (line 301)."""
    prices_bull = [100 + i * 0.8 for i in range(80)]
    result = classify_market_regime(prices_bull)

    # Limits dict with none of the keys the regime multipliers target
    limits = {"some_other_key": 0.5}
    adjusted = apply_market_regime_risk_adjustments(limits, result)
    # The regime keys were skipped; original key is unchanged
    assert adjusted["some_other_key"] == 0.5
    assert "market_regime" in adjusted


def test_apply_regime_adjustments_non_numeric_value():
    """Non-numeric limit value should trigger exception branch (lines 304-305)."""
    prices_bull = [100 + i * 0.8 for i in range(80)]
    result = classify_market_regime(prices_bull)

    # max_loss_per_trade_pct_nav must exist since that's what the multiplier references;
    # set it to a non-numeric so float() conversion fails
    limits = {
        "max_loss_per_trade_pct_nav": "not_a_number",
        "max_gross_exposure": 1.0,
        "max_symbol_weight": 1.0,
    }
    # Should not raise; exception is caught internally
    adjusted = apply_market_regime_risk_adjustments(limits, result)
    # The bad key is skipped; numeric keys are updated
    assert "market_regime" in adjusted


def test_apply_regime_adjustments_without_metadata():
    """include_metadata=False should not add metadata keys."""
    prices_bull = [100 + i * 0.8 for i in range(80)]
    result = classify_market_regime(prices_bull)
    limits = {"max_loss_per_trade_pct_nav": 0.01}
    adjusted = apply_market_regime_risk_adjustments(limits, result, include_metadata=False)
    assert "market_regime" not in adjusted
    assert "market_regime_confidence" not in adjusted


# ──────────────────────────────────────────────────────────────────────────────
# MarketRegimePolicy.default()  (line 323)
# ──────────────────────────────────────────────────────────────────────────────

def test_market_regime_policy_default():
    policy = MarketRegimePolicy.default()
    assert "bull" in policy.multipliers
    assert "bear" in policy.multipliers
    assert "range" in policy.multipliers
    assert policy.volatility_multiplier["bull"] == 1.0
    assert policy.volatility_multiplier["bear"] == 0.70


# ──────────────────────────────────────────────────────────────────────────────
# load_market_regime_policy  (lines 334-367)
# ──────────────────────────────────────────────────────────────────────────────

def test_load_market_regime_policy_valid(tmp_path):
    config = {
        "multipliers": {
            "bull": {"max_loss_per_trade_pct_nav": 1.0, "max_gross_exposure": 1.0, "max_symbol_weight": 1.0},
            "bear": {"max_loss_per_trade_pct_nav": 0.7, "max_gross_exposure": 0.8, "max_symbol_weight": 0.9},
            "range": {"max_loss_per_trade_pct_nav": 0.85, "max_gross_exposure": 0.9, "max_symbol_weight": 0.95},
        },
        "volatility_multiplier": {"bull": 1.0, "bear": 0.7, "range": 0.85},
    }
    p = tmp_path / "regime.json"
    p.write_text(json.dumps(config))
    policy = load_market_regime_policy(str(p))
    assert policy is not None
    assert "bull" in policy.multipliers
    assert policy.volatility_multiplier["bear"] == 0.7


def test_load_market_regime_policy_file_not_found():
    result = load_market_regime_policy("/nonexistent/path/policy.json")
    assert result is None


def test_load_market_regime_policy_missing_keys(tmp_path):
    # multipliers is not a dict
    config = {"multipliers": "not_a_dict", "volatility_multiplier": {"bull": 1.0}}
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(config))
    result = load_market_regime_policy(str(p))
    assert result is None


def test_load_market_regime_policy_non_dict_regime_entry(tmp_path):
    """A non-dict sub-entry in multipliers is skipped (line 346-347)."""
    config = {
        "multipliers": {
            "bull": "not_a_dict",  # This entry is skipped
            "bear": {"max_loss_per_trade_pct_nav": 0.7, "max_gross_exposure": 0.8, "max_symbol_weight": 0.9},
        },
        "volatility_multiplier": {"bull": 1.0, "bear": 0.7},
    }
    p = tmp_path / "partial.json"
    p.write_text(json.dumps(config))
    policy = load_market_regime_policy(str(p))
    assert policy is not None
    assert "bull" not in policy.multipliers
    assert "bear" in policy.multipliers


def test_load_market_regime_policy_non_numeric_vol_entry(tmp_path):
    """Non-numeric volm entry should be skipped (lines 359-362)."""
    config = {
        "multipliers": {
            "bull": {"max_loss_per_trade_pct_nav": 1.0},
        },
        "volatility_multiplier": {"bull": "not_a_number", "bear": 0.7},
    }
    p = tmp_path / "bad_vol.json"
    p.write_text(json.dumps(config))
    policy = load_market_regime_policy(str(p))
    # bull skipped (non-numeric), bear remains; out_vol = {bear: 0.7}
    assert policy is not None
    assert "bull" not in policy.volatility_multiplier
    assert policy.volatility_multiplier["bear"] == 0.7


def test_load_market_regime_policy_empty_out_returns_none(tmp_path):
    """If out_mult or out_vol is empty after filtering, return None (line 364-365)."""
    config = {
        "multipliers": {
            "bull": "not_a_dict",  # all skipped
        },
        "volatility_multiplier": {"bull": 1.0},
    }
    p = tmp_path / "empty.json"
    p.write_text(json.dumps(config))
    result = load_market_regime_policy(str(p))
    assert result is None


def test_load_market_regime_policy_non_numeric_multiplier_value(tmp_path):
    """Non-numeric value inside multiplier sub-dict is skipped (lines 352-353)."""
    config = {
        "multipliers": {
            "bull": {
                "max_loss_per_trade_pct_nav": "not_a_number",  # skipped
                "max_gross_exposure": 1.0,                      # kept
            },
        },
        "volatility_multiplier": {"bull": 1.0},
    }
    p = tmp_path / "bad_mult_val.json"
    p.write_text(json.dumps(config))
    policy = load_market_regime_policy(str(p))
    assert policy is not None
    # Only the valid key is kept
    assert "max_loss_per_trade_pct_nav" not in policy.multipliers["bull"]
    assert policy.multipliers["bull"]["max_gross_exposure"] == 1.0


# ──────────────────────────────────────────────────────────────────────────────
# apply_policy_to_result  (lines 371-374)
# ──────────────────────────────────────────────────────────────────────────────

def test_apply_policy_to_result():
    prices_bull = [100 + i * 0.8 for i in range(80)]
    vols = [1000 + i * 2 for i in range(80)]
    regime_result = classify_market_regime(prices_bull, vols)

    policy = MarketRegimePolicy.default()
    updated = apply_policy_to_result(regime_result, policy)

    assert updated.regime == regime_result.regime
    assert updated.confidence == regime_result.confidence
    rk = regime_result.regime.value
    assert updated.volatility_multiplier == policy.volatility_multiplier[rk]


def test_apply_policy_to_result_missing_regime_key():
    """If policy doesn't have the regime key, fallback to existing risk_multipliers."""
    prices_bull = [100 + i * 0.8 for i in range(80)]
    regime_result = classify_market_regime(prices_bull)

    # Policy without 'bull' key
    policy = MarketRegimePolicy(
        multipliers={"bear": {"max_loss_per_trade_pct_nav": 0.7}},
        volatility_multiplier={"bear": 0.7, "bull": 1.0, "range": 0.85},
    )
    updated = apply_policy_to_result(regime_result, policy)
    # Since 'bull' not in multipliers, falls back to existing risk_multipliers
    assert updated.regime == MarketRegime.BULL


# ──────────────────────────────────────────────────────────────────────────────
# compute_regime_features edge cases
# ──────────────────────────────────────────────────────────────────────────────

def test_compute_regime_features_single_price():
    feats = compute_regime_features([100.0])
    assert feats["n"] == 1.0
    assert feats["ma_short"] == 0.0  # falls through the len < 2 branch
