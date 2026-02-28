import pytest

from openclaw.position_sizing import calculate_position_qty


def test_atr_position_sizing_with_level_caps():
    # NAV=100k, risk=1% => $1000 risk
    # ATR=2, stop_multiple=2 => stop_distance=4 => raw qty=250
    # Level 3 caps from sentinel_policy_v1.json:
    #   max_risk_per_trade_pct_nav=0.005 => $500 => qty=125
    #   max_position_notional_pct_nav=0.1 => $10,000 notional => qty<=100
    qty = calculate_position_qty(
        nav=100_000,
        entry_price=100,
        stop_price=95,  # fallback only
        atr=2,
        atr_stop_multiple=2,
        base_risk_pct=0.01,
        method="atr_risk",
        authority_level=3,
        sentinel_policy_path="config/sentinel_policy_v1.json",
        confidence=0.9,
    )
    assert qty == 100


def test_level0_blocks_position_sizing():
    qty = calculate_position_qty(
        nav=100_000,
        entry_price=100,
        stop_price=95,
        atr=2,
        base_risk_pct=0.01,
        method="atr_risk",
        authority_level=0,
        sentinel_policy_path="config/sentinel_policy_v1.json",
    )
    assert qty == 0
