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


# ── 邊界分支覆蓋 ──────────────────────────────────────

def test_calc_rsi_returns_all_none_when_too_few_prices():
    """prices 數量 < period+1 時，全部回傳 None（line 32 early return）。"""
    result = calc_rsi([100.0, 101.0, 102.0], period=14)
    assert result == [None, None, None]
    assert all(v is None for v in result)


def test_find_support_resistance_empty_inputs_returns_zeros():
    """highs 或 lows 為空時，回傳 support=0.0 resistance=0.0（line 104 early return）。"""
    result = find_support_resistance([], [], [])
    assert result == {"support": 0.0, "resistance": 0.0}


def test_calc_rsi_all_none_prefix_length():
    """RSI 結果長度必須與輸入等長（含 None prefix）。"""
    prices = [float(i) for i in range(20)]
    rsi = calc_rsi(prices, period=14)
    assert len(rsi) == len(prices)
    # 前 14 個 None
    assert all(v is None for v in rsi[:14])
    # 第 14 個（index 14）起有值
    assert rsi[14] is not None


# ── ATR(14) — Task 4 ──────────────────────────────────────────────────────────

def test_atr_basic():
    """ATR(14) 基本計算：結果為正 float"""
    from openclaw.technical_indicators import atr
    candles = [{"high": 100 + i, "low": 99 + i, "close": 99.5 + i} for i in range(15)]
    result = atr(candles, period=14)
    assert isinstance(result, float)
    assert result > 0
    assert result < 5  # 合理範圍（振幅約 1）


def test_atr_insufficient_data_returns_none():
    """資料不足 period+1 根時回傳 None"""
    from openclaw.technical_indicators import atr
    candles = [{"high": 100, "low": 99, "close": 99.5}] * 10
    result = atr(candles, period=14)
    assert result is None


def test_atr_volatile_market():
    """高波動市場 ATR 較大"""
    from openclaw.technical_indicators import atr
    candles = [{"high": 110, "low": 90, "close": 100}] * 20
    result = atr(candles, period=14)
    assert result is not None
    assert result > 8  # 振幅 20，ATR 接近 20


def test_atr_exact_period_boundary():
    """剛好 period+1 筆資料能計算（最小有效輸入）"""
    from openclaw.technical_indicators import atr
    candles = [{"high": 100, "low": 99, "close": 99.5}] * 15  # 14+1
    result = atr(candles, period=14)
    assert result is not None
