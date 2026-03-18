# src/openclaw/signal_aggregator.py
"""signal_aggregator.py — Regime-based 動態權重信號融合

整合技術面（signal_generator）、LLM 面（lm_signal_cache）、
市況（market_regime）三個信號，輸出加權融合後的 AggregatedSignal。

風控層（risk_engine）獨立運作，不參與此處加權。
"""
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from openclaw.market_regime import classify_market_regime
from openclaw.signal_generator import compute_signal, fetch_candles
from openclaw.lm_signal_cache import read_cache_with_fallback

REGIME_WEIGHTS: dict[str, dict[str, float]] = {
    "bull":  {"technical": 0.50, "llm": 0.20, "risk_adj": 0.30},
    "bear":  {"technical": 0.30, "llm": 0.20, "risk_adj": 0.50},
    "range": {"technical": 0.40, "llm": 0.20, "risk_adj": 0.40},
}

# 黑天鵝即時熔斷：市場指數（0050）單日跌幅超過此門檻時強制切入 bear regime
_BLACK_SWAN_DROP_THRESHOLD: float = float(
    __import__("os").environ.get("BLACK_SWAN_DROP_THRESHOLD", "-0.03")
)

SIGNAL_TO_SCORE: dict[str, float] = {"buy": 0.8, "flat": 0.5, "sell": 0.2}

_LIMIT_UP_THRESHOLD   = 0.095   # 漲幅 >= 9.5% 視為漲停
_BUY_SCORE_LIMIT_UP   = 0.30    # 漲停時壓低 buy score 上限
_LIMIT_DOWN_THRESHOLD = -0.095  # 跌幅 <= -9.5% 視為跌停
_SELL_SCORE_LIMIT_DOWN = 0.70   # 跌停時壓高 sell score 下限（不追殺）
_BUY_ACTION_THRESHOLD  = 0.65
_SELL_ACTION_THRESHOLD = 0.35


@dataclass(frozen=True)
class AggregatedSignal:
    action: str                          # 'buy' | 'sell' | 'flat'
    score: float                         # 0.0 ~ 1.0
    regime: str                          # 'bull' | 'bear' | 'range'
    weights_used: dict                   # {'technical': float, 'llm': float, 'risk_adj': float}
    reasons: list = field(default_factory=list)
    limit_filtered: bool = False


def _get_regime(conn: sqlite3.Connection, symbol: str) -> tuple[str, float]:
    """從 eod_prices 取收盤價序列，判斷 market regime。
    回傳 (regime_str, volatility_multiplier)。
    """
    candles = fetch_candles(conn, symbol, days=60)
    if len(candles) < 20:
        return "range", 1.0
    prices  = [c["close"]  for c in candles]
    volumes = [c["volume"] for c in candles]
    result = classify_market_regime(prices, volumes)
    return result.regime.value, result.volatility_multiplier


def aggregate(
    conn: sqlite3.Connection,
    symbol: str,
    snap: dict,
    position_avg_price: Optional[float],
    high_water_mark: Optional[float],
    market_snap: Optional[dict] = None,
) -> AggregatedSignal:
    """
    計算 Regime-based 加權信號。

    Args:
        snap: 即時快照 {"close": float, "reference": float, ...}
    Returns:
        AggregatedSignal
    """
    reasons: list[str] = []

    # 1. Market regime
    regime, vol_mult = _get_regime(conn, symbol)

    # 黑天鵝即時熔斷：市場指數單日跌幅超過門檻時強制切入 bear regime
    if market_snap is not None:
        _close = market_snap.get("close", 0.0)
        _ref   = market_snap.get("reference", _close) or _close
        if _ref > 0:
            _market_drop = (_close - _ref) / _ref
            if _market_drop <= _BLACK_SWAN_DROP_THRESHOLD:
                regime = "bear"
                reasons.append(
                    f"BLACK_SWAN_OVERRIDE:market_drop={_market_drop:.2%}"
                    f"<={_BLACK_SWAN_DROP_THRESHOLD:.2%}"
                )

    weights = REGIME_WEIGHTS.get(regime, REGIME_WEIGHTS["range"])
    reasons.append(f"regime={regime}")

    # 2. Technical signal（無資料時 compute_signal 回傳 flat，不拋例外）
    tech_str = compute_signal(conn, symbol, position_avg_price, high_water_mark)
    tech_score = SIGNAL_TO_SCORE.get(tech_str, 0.5)  # default to neutral on unknown
    reasons.append(f"technical={tech_str}({tech_score:.2f})")

    # 3. LLM cache（個股 fallback 全市場；miss → neutral 0.5）
    cache = read_cache_with_fallback(conn, symbol)
    if cache:
        llm_score = cache["score"]
        llm_label = cache["source"]
    else:
        llm_score = 0.5
        llm_label = "cache_miss"
    reasons.append(f"llm={llm_score:.2f}({llm_label})")

    # 4. Risk adjustment（由 volatility_multiplier 衍生：高波動 → 偏保守）
    risk_adj = max(0.1, min(0.9, 0.5 / vol_mult))
    reasons.append(f"risk_adj={risk_adj:.2f}(vol_mult={vol_mult:.2f})")

    # 5. 漲停板 / 跌停板過濾
    close = snap.get("close", 0.0)
    ref   = snap.get("reference", close) or close
    limit_filtered = False
    if ref > 0 and close >= ref * (1 + _LIMIT_UP_THRESHOLD):
        # 漲停：流動性風險，不追漲，buy score 壓低上限
        tech_score = min(tech_score, _BUY_SCORE_LIMIT_UP)
        limit_filtered = True
        reasons.append("limit_up:buy_score_capped_to_0.3")
    elif ref > 0 and close <= ref * (1 + _LIMIT_DOWN_THRESHOLD):
        # 跌停：流動性風險，不追殺，sell score 壓至 0.7（防止恐慌賣出）
        tech_score = max(tech_score, _SELL_SCORE_LIMIT_DOWN)
        limit_filtered = True
        reasons.append("limit_down:sell_score_floored_to_0.7")

    # 6. 加權融合
    final_score = (
        weights["technical"] * tech_score +
        weights["llm"]       * llm_score  +
        weights["risk_adj"]  * risk_adj
    )

    if final_score >= _BUY_ACTION_THRESHOLD:
        action = "buy"
    elif final_score <= _SELL_ACTION_THRESHOLD:
        action = "sell"
    else:
        action = "flat"

    return AggregatedSignal(
        action=action,
        score=round(final_score, 4),
        regime=regime,
        weights_used=weights,
        reasons=reasons,
        limit_filtered=limit_filtered,
    )
