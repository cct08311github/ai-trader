from openclaw.technical_indicators import calc_ma, calc_rsi, calc_macd, find_support_resistance


def test_calc_ma_basic():
    prices = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert calc_ma(prices, 3) == [None, None, 20.0, 30.0, 40.0]


def test_calc_ma_insufficient_data():
    assert calc_ma([1.0, 2.0], 5) == [None, None]


def test_calc_rsi_overbought():
    # 14 期全漲→ RSI 應接近 100
    prices = [float(i) for i in range(1, 20)]
    rsi = calc_rsi(prices, period=14)
    assert rsi[-1] > 90.0


def test_calc_rsi_oversold():
    # 14 期全跌→ RSI 應接近 0
    prices = [float(20 - i) for i in range(20)]
    rsi = calc_rsi(prices, period=14)
    assert rsi[-1] < 10.0


def test_calc_macd_returns_keys():
    prices = [100.0 + i * 0.5 for i in range(35)]
    result = calc_macd(prices)
    assert "macd" in result and "signal" in result and "histogram" in result
    assert len(result["macd"]) == len(prices)


def test_find_support_resistance_returns_floats():
    highs = [110.0, 115.0, 112.0, 118.0, 113.0]
    lows  = [100.0,  98.0, 102.0,  97.0, 101.0]
    closes = [105.0, 107.0, 104.0, 110.0, 108.0]
    result = find_support_resistance(highs, lows, closes)
    assert "support" in result and "resistance" in result
    assert result["support"] < result["resistance"]
