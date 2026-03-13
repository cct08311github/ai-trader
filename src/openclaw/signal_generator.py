"""signal_generator.py — EOD 日線驅動信號生成模組（thin wrapper）

委託信號計算給 signal_logic.py（純函數），本模組負責 DB I/O。
公開 API 不變：compute_signal() 和 fetch_candles()。
"""
import os
import sqlite3
from typing import Optional

from openclaw.signal_logic import SignalParams, evaluate_entry, evaluate_exit

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


def _build_params(trailing_pct: float = _TRAILING_PCT_BASE) -> SignalParams:
    return SignalParams(
        take_profit_pct=_TAKE_PROFIT_PCT,
        stop_loss_pct=_STOP_LOSS_PCT,
        trailing_pct=trailing_pct,
        trailing_pct_tight=_TRAILING_PCT_TIGHT,
        trailing_profit_threshold=_TRAILING_PROFIT_THRESHOLD,
    )


def compute_signal(
    conn: sqlite3.Connection,
    symbol: str,
    position_avg_price: Optional[float],
    high_water_mark: Optional[float],
    trailing_pct: float = _TRAILING_PCT_BASE,
) -> str:
    """計算交易信號。公開 API 不變。

    Returns: "buy" | "sell" | "flat"
    """
    candles = _fetch_candles(conn, symbol)
    if len(candles) < 5:
        return "flat"

    closes = [c["close"] for c in candles]
    params = _build_params(trailing_pct)

    if position_avg_price is not None:
        return evaluate_exit(closes, position_avg_price, high_water_mark, params).signal

    return evaluate_entry(closes, params).signal


# Public alias — preferred import for external callers
fetch_candles = _fetch_candles
