"""signal_generator.py — EOD 日線驅動信號生成模組

Strangler Fig Pattern — 第一步：新模組與 ticker_watcher._generate_signal 並行存在，
逐步取代舊的 3 分鐘記憶體 close 作為技術指標來源。

輸入：SQLite 連線（讀 eod_prices）、持倉資訊
輸出：signal = "buy" | "sell" | "flat"
"""
import os
import sqlite3
from typing import Optional

from openclaw.technical_indicators import calc_ma, calc_rsi

_TAKE_PROFIT_PCT:          float = float(os.environ.get("TAKE_PROFIT_PCT",   "0.02"))
_STOP_LOSS_PCT:            float = float(os.environ.get("STOP_LOSS_PCT",     "0.03"))
_TRAILING_PCT_BASE:        float = float(os.environ.get("TRAILING_PCT",      "0.05"))
_TRAILING_PCT_TIGHT:       float = float(os.environ.get("TRAILING_PCT_TIGHT","0.03"))
_TRAILING_PROFIT_THRESHOLD: float = 0.50


def _fetch_candles(conn: sqlite3.Connection, symbol: str, days: int = 60) -> list[dict]:
    """從 eod_prices 取最近 N 日 OHLCV（由舊到新）"""
    rows = conn.execute(
        "SELECT trade_date, open, high, low, close, volume "
        "FROM eod_prices WHERE symbol=? ORDER BY trade_date DESC LIMIT ?",
        (symbol, days)
    ).fetchall()
    return [
        {"date": r[0], "open": r[1], "high": r[2], "low": r[3],
         "close": r[4], "volume": r[5]}
        for r in reversed(rows)
    ]


def compute_signal(
    conn: sqlite3.Connection,
    symbol: str,
    position_avg_price: Optional[float],
    high_water_mark: Optional[float],
    trailing_pct: float = _TRAILING_PCT_BASE,
) -> str:
    """計算交易信號。

    有持倉時（按優先順序）：
      1. Trailing Stop：close < high_water_mark * (1 - effective_trailing) → sell
         獲利超過 50% 時收緊至 3%
      2. 止盈：close > avg_price * (1 + TAKE_PROFIT_PCT) → sell
      3. 止損：close < avg_price * (1 - STOP_LOSS_PCT) → sell
      4. 其他：flat

    無持倉時：
      MA5 上穿 MA20（黃金交叉）+ RSI < 70 → buy
      其他：flat

    Returns: "buy" | "sell" | "flat"
    """
    candles = _fetch_candles(conn, symbol)
    if len(candles) < 5:
        return "flat"

    closes = [c["close"] for c in candles]
    latest_close = closes[-1]

    if position_avg_price is not None:
        # Trailing Stop
        if high_water_mark and position_avg_price > 0:
            profit_pct = (high_water_mark - position_avg_price) / position_avg_price
            effective_trailing = _TRAILING_PCT_TIGHT if profit_pct >= _TRAILING_PROFIT_THRESHOLD else trailing_pct
            if latest_close < high_water_mark * (1 - effective_trailing):
                return "sell"

        # 止盈 / 止損
        if latest_close > position_avg_price * (1 + _TAKE_PROFIT_PCT):
            return "sell"
        if latest_close < position_avg_price * (1 - _STOP_LOSS_PCT):
            return "sell"
        return "flat"

    # 無持倉：MA 黃金交叉進場
    if len(closes) >= 20:
        ma5_series  = calc_ma(closes, 5)
        ma20_series = calc_ma(closes, 20)
        # 最新值與前一日值
        cur_ma5,  prev_ma5  = ma5_series[-1],  ma5_series[-2]
        cur_ma20, prev_ma20 = ma20_series[-1], ma20_series[-2]
        if (cur_ma5 and cur_ma20 and prev_ma5 and prev_ma20
                and prev_ma5 <= prev_ma20 and cur_ma5 > cur_ma20):
            rsi_series = calc_rsi(closes, 14)
            rsi_val = rsi_series[-1]
            if rsi_val is None or rsi_val < 70:
                return "buy"

    return "flat"
