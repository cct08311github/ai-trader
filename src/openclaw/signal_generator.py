"""signal_generator.py — EOD 日線驅動信號生成模組（thin wrapper）

委託信號計算給 signal_logic.py（純函數），本模組負責 DB I/O。
公開 API 不變：compute_signal() 和 fetch_candles()。
"""
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional

from openclaw.signal_logic import SignalParams, evaluate_entry, evaluate_exit

_TZ_TWN = timezone(timedelta(hours=8))
# 盤後收盤基準：14:30 TWN（台股 13:30 收盤，ingest 約 14:00–14:30 完成）
_EOD_COMPLETE_HOUR = 14

_TAKE_PROFIT_PCT:          float = float(os.environ.get("TAKE_PROFIT_PCT",   "0.02"))
_STOP_LOSS_PCT:            float = float(os.environ.get("STOP_LOSS_PCT",     "0.03"))
_TRAILING_PCT_BASE:        float = float(os.environ.get("TRAILING_PCT",      "0.05"))
_TRAILING_PCT_TIGHT:       float = float(os.environ.get("TRAILING_PCT_TIGHT","0.03"))
_TRAILING_PROFIT_THRESHOLD: float = 0.50


def _fetch_candles(
    conn: sqlite3.Connection,
    symbol: str,
    days: int = 60,
    max_date: Optional[str] = None,
) -> list[dict]:
    """從 eod_prices 取最近 N 日 OHLCV（由舊到新）。

    Args:
        max_date: 只取 trade_date <= max_date 的資料。
                  None = 自動決定：盤後（TWN >= 14:30）取當日；盤中取前一日，
                  避免混入當日尚未完成的 EOD ingest 資料。
    """
    if max_date is None:
        twn = datetime.now(tz=_TZ_TWN)
        if twn.hour >= _EOD_COMPLETE_HOUR:
            max_date = twn.strftime("%Y-%m-%d")
        else:
            max_date = (twn - timedelta(days=1)).strftime("%Y-%m-%d")

    rows = conn.execute(
        "SELECT trade_date, open, high, low, close, volume "
        "FROM eod_prices WHERE symbol=? AND trade_date<=? ORDER BY trade_date DESC LIMIT ?",
        (symbol, max_date, days)
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
    max_date: Optional[str] = None,
) -> str:
    """計算交易信號。公開 API 不變。

    Args:
        max_date: 傳給 _fetch_candles；None = 依 TWN 時間自動決定（推薦）。
    Returns: "buy" | "sell" | "flat"
    """
    candles = _fetch_candles(conn, symbol, max_date=max_date)
    if len(candles) < 5:
        return "flat"

    closes = [c["close"] for c in candles]
    params = _build_params(trailing_pct)

    if position_avg_price is not None:
        return evaluate_exit(closes, position_avg_price, high_water_mark, params).signal

    return evaluate_entry(closes, params).signal


# Public alias — preferred import for external callers
fetch_candles = _fetch_candles
