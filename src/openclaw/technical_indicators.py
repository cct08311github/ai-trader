"""技術指標計算 — 純函數，不依賴外部套件。"""
from __future__ import annotations
from typing import List, Optional, Dict


def calc_ma(prices: List[float], window: int) -> List[Optional[float]]:
    """移動平均。前 window-1 個位置回傳 None。"""
    result: List[Optional[float]] = []
    for i in range(len(prices)):
        if i + 1 < window:
            result.append(None)
        else:
            result.append(sum(prices[i - window + 1 : i + 1]) / window)
    return result


def _ema(prices: List[float], period: int) -> List[float]:
    """指數移動平均（EMA），用於 MACD / RSI 平滑。"""
    k = 2.0 / (period + 1)
    ema: List[float] = []
    for i, p in enumerate(prices):
        if i == 0:
            ema.append(p)
        else:
            ema.append(p * k + ema[-1] * (1 - k))
    return ema


def calc_rsi(prices: List[float], period: int = 14) -> List[Optional[float]]:
    """RSI（Wilder 平滑法）。前 period 個位置回傳 None。"""
    if len(prices) < period + 1:
        return [None] * len(prices)

    gains: List[float] = []
    losses: List[float] = []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    result: List[Optional[float]] = [None] * period

    # 第一個 RSI：用簡單平均做種子
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def _rsi_from_avg(ag: float, al: float) -> float:
        if al == 0.0:
            return 100.0
        rs = ag / al
        return 100.0 - 100.0 / (1.0 + rs)

    result.append(_rsi_from_avg(avg_gain, avg_loss))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        result.append(_rsi_from_avg(avg_gain, avg_loss))

    return result


def calc_macd(
    prices: List[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Dict[str, List[Optional[float]]]:
    """MACD(fast, slow, signal)。回傳 {macd, signal, histogram}，各長度與 prices 相同。"""
    ema_fast = _ema(prices, fast)
    ema_slow = _ema(prices, slow)

    macd_line: List[Optional[float]] = []
    for i in range(len(prices)):
        if i < slow - 1:
            macd_line.append(None)
        else:
            macd_line.append(ema_fast[i] - ema_slow[i])

    # Signal line：只對非 None 的 macd_line 做 EMA
    valid_macd = [v for v in macd_line if v is not None]
    ema_signal = _ema(valid_macd, signal)

    signal_line: List[Optional[float]] = [None] * (len(prices) - len(valid_macd))
    signal_line.extend(ema_signal)

    histogram: List[Optional[float]] = []
    for m, s in zip(macd_line, signal_line):
        if m is None or s is None:
            histogram.append(None)
        else:
            histogram.append(m - s)

    return {"macd": macd_line, "signal": signal_line, "histogram": histogram}


def find_support_resistance(
    highs: List[float],
    lows: List[float],
    closes: List[float],
) -> Dict[str, float]:
    """以近期 high/low 的簡單統計估算支撐壓力位。"""
    if not highs or not lows:
        return {"support": 0.0, "resistance": 0.0}
    # 近 20 根（或全部）
    n = min(20, len(highs))
    recent_highs = sorted(highs[-n:])
    recent_lows  = sorted(lows[-n:])
    # 壓力：前 25% 高點的均值；支撐：後 25% 低點的均值
    q = max(1, n // 4)
    resistance = sum(recent_highs[-q:]) / q
    support    = sum(recent_lows[:q]) / q
    return {"support": round(support, 2), "resistance": round(resistance, 2)}
