# src/openclaw/signal_logic.py
"""signal_logic.py — 純函數信號邏輯（無 DB、無副作用）

Phase 1a extraction: 從 signal_generator.py 抽取計算邏輯，
讓 backtest engine 可以直接餵入歷史 close 序列重播。

行為與 signal_generator.compute_signal 完全一致（方案 A 順序）。
"""
from dataclasses import dataclass
from typing import Optional, Sequence

from openclaw.technical_indicators import calc_ma, calc_rsi


@dataclass(frozen=True)
class SignalParams:
    """可調參數 — backtest scanner 會 grid search 這些值。"""
    take_profit_pct: float = 0.02
    stop_loss_pct: float = 0.03
    trailing_pct: float = 0.05
    trailing_pct_tight: float = 0.03
    trailing_profit_threshold: float = 0.50
    ma_short: int = 5
    ma_long: int = 20
    rsi_period: int = 14
    rsi_entry_max: float = 70.0


@dataclass(frozen=True)
class SignalResult:
    """信號輸出。"""
    signal: str            # "buy" | "sell" | "flat"
    reason: str = ""       # 人類可讀的觸發原因


def evaluate_exit(
    closes: Sequence[float],
    avg_price: float,
    high_water_mark: Optional[float],
    params: SignalParams = SignalParams(),
) -> SignalResult:
    """持倉時的出場信號（順序：Trailing → 止盈 → 止損 → flat）。

    Args:
        closes: 由舊到新的收盤價序列（至少 1 筆）
        avg_price: 持倉均價
        high_water_mark: 持倉期間最高價
        params: 可調參數
    """
    if len(closes) < 1 or avg_price <= 0:
        return SignalResult("flat", "insufficient_data")

    latest = closes[-1]

    # 1. Trailing Stop
    if high_water_mark and avg_price > 0:
        profit_pct = (high_water_mark - avg_price) / avg_price
        effective = params.trailing_pct_tight if profit_pct >= params.trailing_profit_threshold else params.trailing_pct
        if latest < high_water_mark * (1 - effective):
            return SignalResult("sell", f"trailing_stop:hwm={high_water_mark:.2f},eff={effective:.2%}")

    # 2. 止盈
    if latest > avg_price * (1 + params.take_profit_pct):
        return SignalResult("sell", f"take_profit:{latest:.2f}>{avg_price:.2f}*{1+params.take_profit_pct:.2%}")

    # 3. 止損
    if latest < avg_price * (1 - params.stop_loss_pct):
        return SignalResult("sell", f"stop_loss:{latest:.2f}<{avg_price:.2f}*{1-params.stop_loss_pct:.2%}")

    return SignalResult("flat", "hold")


def evaluate_entry(
    closes: Sequence[float],
    params: SignalParams = SignalParams(),
) -> SignalResult:
    """無持倉時的進場信號（MA 黃金交叉 + RSI 過濾）。

    Args:
        closes: 由舊到新的收盤價序列（至少 ma_long 筆）
        params: 可調參數
    """
    if len(closes) < params.ma_long:
        return SignalResult("flat", "insufficient_data")

    ma_short = calc_ma(closes, params.ma_short)
    ma_long = calc_ma(closes, params.ma_long)

    cur_s, prev_s = ma_short[-1], ma_short[-2]
    cur_l, prev_l = ma_long[-1], ma_long[-2]

    if (cur_s and cur_l and prev_s and prev_l
            and prev_s <= prev_l and cur_s > cur_l):
        rsi_series = calc_rsi(closes, params.rsi_period)
        rsi_val = rsi_series[-1]
        if rsi_val is None or rsi_val < params.rsi_entry_max:
            return SignalResult("buy", f"golden_cross:ma{params.ma_short}>{params.ma_long},rsi={rsi_val}")

    return SignalResult("flat", "no_entry_signal")


def load_params_from_file(path: str) -> SignalParams:
    """從 JSON 檔案讀取信號參數，不存在則 fallback 到預設值。"""
    try:
        import json
        with open(path, "r") as f:
            data = json.load(f)
        p = data.get("params", {})
        return SignalParams(**{
            k: v for k, v in p.items()
            if k in SignalParams.__dataclass_fields__
        })
    except Exception:
        return SignalParams()
