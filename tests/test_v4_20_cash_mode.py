"""Test Cash Mode (v4 #20)."""


def test_cash_mode_enters_on_bear_regime():
    from openclaw.cash_mode import evaluate_cash_mode
    from openclaw.market_regime import MarketRegimeResult, MarketRegime

    res = MarketRegimeResult(
        regime=MarketRegime.BEAR,
        confidence=0.9,
        features={"trend_strength": -0.05, "volatility": 0.02},
        volatility_multiplier=0.7,
        risk_multipliers={"max_gross_exposure": 0.8},
    )

    dec = evaluate_cash_mode(res, current_cash_mode=False)
    assert dec.cash_mode is True
    assert dec.reason_code in {"CASHMODE_BEAR_REGIME", "CASHMODE_ENTER_LOW_RATING"}


def test_cash_mode_hysteresis_exit():
    from openclaw.cash_mode import evaluate_cash_mode, CashModePolicy
    from openclaw.market_regime import MarketRegimeResult, MarketRegime

    pol = CashModePolicy(enter_below_rating=40.0, exit_above_rating=60.0)

    # Start in cash mode with recovery rating.
    res = MarketRegimeResult(
        regime=MarketRegime.BULL,
        confidence=0.8,
        features={"trend_strength": 0.05, "volatility": 0.01},
        volatility_multiplier=1.0,
        risk_multipliers=None,
    )

    dec = evaluate_cash_mode(res, current_cash_mode=True, policy=pol)
    assert dec.cash_mode is False
    assert dec.reason_code == "CASHMODE_EXIT_RATING_RECOVERY"
