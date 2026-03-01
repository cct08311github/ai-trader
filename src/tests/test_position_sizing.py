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


def test_fixed_fractional_zero_risk():
    """邊界測試：零風險百分比，應返回0。"""
    qty = fixed_fractional_qty(
        PositionSizingInput(
            nav=500_000,
            entry_price=1000,
            stop_price=970,
            base_risk_pct=0.0,
            confidence=0.9,
        )
    )
    assert qty == 0


def test_fixed_fractional_negative_stop():
    """反向測試：止損價高於入場價（多頭頭寸無效）。"""
    qty = fixed_fractional_qty(
        PositionSizingInput(
            nav=500_000,
            entry_price=1000,
            stop_price=1010,  # 高於入場價
            base_risk_pct=0.01,
            confidence=0.9,
        )
    )
    # 風險為負，應返回 0 或負數。我們接受 <= 0。
    assert qty <= 0


def test_fixed_fractional_high_confidence():
    """正向測試：信心高於閾值，應使用完整規模。"""
    qty = fixed_fractional_qty(
        PositionSizingInput(
            nav=500_000,
            entry_price=1000,
            stop_price=970,
            base_risk_pct=0.01,
            confidence=0.8,
            confidence_threshold=0.7,
        )
    )
    # 計算預期數量：nav * base_risk_pct / (entry_price - stop_price)
    expected = int(500_000 * 0.01 / (1000 - 970))
    assert qty == expected
