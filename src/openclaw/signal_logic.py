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
    trailing_pct: float = 0.05           # Tier 1: profit < 10%
    trailing_pct_mid: float = 0.04       # Tier 2: profit 10-30%
    trailing_pct_tight: float = 0.03     # Tier 3: profit > 30%
    trailing_profit_threshold_mid: float = 0.10   # 10% triggers mid tier
    trailing_profit_threshold_tight: float = 0.30  # 30% triggers tight tier
    trailing_profit_threshold: float = 0.30  # kept for backward compat
    hard_kill_dd_pct: float = 0.15       # #598: hard kill at -15% DD from HWM
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

    # 0. Hard Kill — unconditional exit if DD from HWM exceeds hard_kill_dd_pct (#598)
    # This fires regardless of profit tier — prevents catastrophic drawdown
    if high_water_mark and high_water_mark > 0:
        dd_from_hwm = (high_water_mark - latest) / high_water_mark
        if dd_from_hwm >= params.hard_kill_dd_pct:
            return SignalResult("sell", f"hard_kill:hwm={high_water_mark:.2f},dd={dd_from_hwm:.2%}")

    # 1. Trailing Stop (3-tier: 5% / 4% / 3%)
    if high_water_mark and avg_price > 0:
        profit_pct = (high_water_mark - avg_price) / avg_price
        if profit_pct >= params.trailing_profit_threshold_tight:
            effective = params.trailing_pct_tight      # ≥30% profit → 3%
        elif profit_pct >= params.trailing_profit_threshold_mid:
            effective = params.trailing_pct_mid         # 10-30% profit → 4%
        else:
            effective = params.trailing_pct             # <10% profit → 5%
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


# ---------------------------------------------------------------------------
# Multi-signal entry evaluation (#384) — MACD + Volume Breakout + RS
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MultiSignalResult:
    """多信號進場評估結果。score 為 0.0~1.0。"""
    score: float           # 綜合技術分數
    signals_fired: int     # 觸發的信號數量
    reasons: list          # 各信號觸發原因


def _macd_entry(closes: Sequence[float]) -> tuple[bool, str]:
    """MACD histogram 由負翻正（bullish crossover）。"""
    from openclaw.technical_indicators import calc_macd
    if len(closes) < 27:  # need at least slow(26) + 1
        return False, ""
    macd = calc_macd(closes)
    hist = macd["histogram"]
    if len(hist) >= 2 and hist[-1] is not None and hist[-2] is not None:
        if hist[-2] <= 0 and hist[-1] > 0:
            return True, f"macd_bullish_cross:hist={hist[-1]:.4f}"
    return False, ""


def _volume_breakout(
    closes: Sequence[float],
    volumes: Sequence[float],
    period: int = 20,
    volume_ratio: float = 2.0,
) -> tuple[bool, str]:
    """價格突破 N 日最高且成交量 > 均量 × ratio。"""
    if len(closes) < period + 1 or len(volumes) < period + 1:
        return False, ""
    high_n = max(closes[-(period + 1):-1])
    avg_vol = sum(volumes[-(period + 1):-1]) / period
    latest_close = closes[-1]
    latest_vol = volumes[-1]
    if latest_close > high_n and avg_vol > 0 and latest_vol >= avg_vol * volume_ratio:
        return True, (
            f"vol_breakout:close={latest_close:.2f}>high{period}={high_n:.2f},"
            f"vol_ratio={latest_vol / avg_vol:.1f}x"
        )
    return False, ""


def _relative_strength(
    closes: Sequence[float],
    benchmark_closes: Sequence[float],
    period: int = 20,
) -> tuple[bool, str]:
    """個股 N 日報酬率 > 大盤 N 日報酬率（相對強勢）。"""
    if len(closes) < period + 1 or len(benchmark_closes) < period + 1:
        return False, ""
    stock_ret = (closes[-1] - closes[-(period + 1)]) / closes[-(period + 1)]
    bench_ret = (benchmark_closes[-1] - benchmark_closes[-(period + 1)]) / benchmark_closes[-(period + 1)]
    rs = stock_ret - bench_ret
    if rs > 0:
        return True, f"relative_strength:stock={stock_ret:.2%},bench={bench_ret:.2%},rs={rs:.2%}"
    return False, ""


def evaluate_entry_multi(
    closes: Sequence[float],
    volumes: Sequence[float],
    benchmark_closes: Sequence[float],
    params: SignalParams = SignalParams(),
) -> MultiSignalResult:
    """多信號進場評估。

    四個獨立信號各貢獻 0.25 分，全部觸發 = 1.0：
    1. MA 黃金交叉 + RSI（原有）
    2. MACD histogram 翻正
    3. 成交量突破（20 日新高 + 2x 量）
    4. 相對強度（vs 大盤）

    Returns:
        MultiSignalResult with score 0.0~1.0
    """
    reasons: list[str] = []
    score = 0.0
    signals_fired = 0

    # Signal 1: MA golden cross + RSI (original)
    ma_result = evaluate_entry(closes, params)
    if ma_result.signal == "buy":
        score += 0.25
        signals_fired += 1
        reasons.append(ma_result.reason)

    # Signal 2: MACD histogram bullish crossover
    fired, reason = _macd_entry(closes)
    if fired:
        score += 0.25
        signals_fired += 1
        reasons.append(reason)

    # Signal 3: Volume breakout
    fired, reason = _volume_breakout(closes, volumes)
    if fired:
        score += 0.25
        signals_fired += 1
        reasons.append(reason)

    # Signal 4: Relative strength vs benchmark
    fired, reason = _relative_strength(closes, benchmark_closes)
    if fired:
        score += 0.25
        signals_fired += 1
        reasons.append(reason)

    return MultiSignalResult(
        score=round(score, 4),
        signals_fired=signals_fired,
        reasons=reasons,
    )


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
