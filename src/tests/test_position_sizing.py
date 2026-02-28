from openclaw.position_sizing import PositionSizingInput, fixed_fractional_qty


def test_fixed_fractional_qty_base():
    qty = fixed_fractional_qty(
        PositionSizingInput(
            nav=500_000,
            entry_price=1000,
            stop_price=970,
            base_risk_pct=0.01,
            confidence=0.9,
        )
    )
    assert qty == 166


def test_low_confidence_scales_down_qty():
    base = fixed_fractional_qty(
        PositionSizingInput(
            nav=500_000,
            entry_price=1000,
            stop_price=970,
            base_risk_pct=0.01,
            confidence=0.9,
        )
    )
    low_conf = fixed_fractional_qty(
        PositionSizingInput(
            nav=500_000,
            entry_price=1000,
            stop_price=970,
            base_risk_pct=0.01,
            confidence=0.4,
            confidence_threshold=0.6,
            low_confidence_scale=0.5,
        )
    )
    assert low_conf == int(base * 0.5)
