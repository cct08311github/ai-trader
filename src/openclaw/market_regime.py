from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from statistics import mean, pstdev
from typing import Dict, Mapping, Optional, Sequence, List


class MarketRegime(str, Enum):
    """Simple market regime classification.

    v4#14 scope: bull / bear / range.

    This module is intentionally deterministic and dependency-light.
    """

    BULL = "bull"
    BEAR = "bear"
    RANGE = "range"


@dataclass(frozen=True)
class MarketRegimeResult:
    regime: MarketRegime
    confidence: float
    features: Dict[str, float]

    # Integration points:
    # - `volatility_multiplier` can be applied to risk_engine.Decision.volatility_multiplier.
    # - `risk_multipliers` can be applied to a flattened limits dict.
    volatility_multiplier: float = 1.0
    risk_multipliers: Mapping[str, float] | None = None


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _to_floats(seq: Sequence[float]) -> List[float]:
    out: List[float] = []
    for v in seq:
        try:
            fv = float(v)
        except Exception:
            continue
        if math.isfinite(fv):
            out.append(fv)
    return out


def _returns(prices: Sequence[float]) -> List[float]:
    ps = _to_floats(prices)
    if len(ps) < 2:
        return []
    rets: List[float] = []
    for i in range(1, len(ps)):
        prev = ps[i - 1]
        cur = ps[i]
        if prev <= 0 or cur <= 0:
            continue
        rets.append(math.log(cur / prev))
    return rets


def _lin_slope(values: Sequence[float]) -> float:
    """Least-squares slope of values over index."""

    ys = _to_floats(values)
    n = len(ys)
    if n < 2:
        return 0.0

    x_mean = (n - 1) / 2.0
    y_mean = mean(ys)

    num = 0.0
    den = 0.0
    for i, y in enumerate(ys):
        dx = i - x_mean
        num += dx * (y - y_mean)
        den += dx * dx
    if den <= 0:  # pragma: no cover
        return 0.0
    return num / den



def _rsi(prices: Sequence[float], period: int = 14) -> float:
    """Compute Relative Strength Index (RSI) for given prices."""
    ps = _to_floats(prices)
    if len(ps) < period + 1:
        return 50.0  # Neutral
    
    gains = []
    losses = []
    for i in range(1, len(ps)):
        change = ps[i] - ps[i-1]
        if change > 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(change))
    
    # Use Wilder's smoothing (RSI typical)
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def _momentum(prices: Sequence[float], lookback: int = 10) -> float:
    """Price momentum over lookback periods."""
    ps = _to_floats(prices)
    if len(ps) < lookback + 1:
        return 0.0
    return (ps[-1] / ps[-lookback] - 1) * 100  # percentage


def _price_channel(prices: Sequence[float], window: int = 20) -> tuple[float, float, float]:
    """Compute high, low, and width of price channel."""
    ps = _to_floats(prices)
    if len(ps) < window:
        window = len(ps)
    if window == 0:
        return 0.0, 0.0, 0.0
    segment = ps[-window:]
    high = max(segment)
    low = min(segment)
    width = (high - low) / low if low > 0 else 0.0
    return high, low, width


def _atr(prices: Sequence[float], period: int = 14) -> float:
    """Average True Range (simplified using price ranges)."""
    ps = _to_floats(prices)
    if len(ps) < period + 1:
        return 0.0
    
    trs = []
    for i in range(1, len(ps)):
        high_low = abs(ps[i] - ps[i-1])
        # Simplified: we don't have high/low/close, so just use price differences
        trs.append(high_low)
    
    if len(trs) < period:  # pragma: no cover
        return 0.0
    return mean(trs[-period:]) / ps[-1] if ps[-1] > 0 else 0.0
def compute_regime_features(
    prices: Sequence[float],
    volumes: Sequence[float] | None = None,
    *,
    short_window: int = 20,
    long_window: int = 60,
) -> Dict[str, float]:
    """Compute deterministic features used by the classifier."""

    ps = _to_floats(prices)
    if len(ps) < 2:
        return {
            "n": float(len(ps)),
            "ma_short": 0.0,
            "ma_long": 0.0,
            "trend_strength": 0.0,
            "slope_pct": 0.0,
            "volatility": 0.0,
            "vol_ratio": 1.0,
            "rsi": 50.0,
            "momentum_pct": 0.0,
            "channel_width": 0.0,
            "atr": 0.0,
        }

    short_n = min(short_window, len(ps))
    long_n = min(long_window, len(ps))

    ma_short = mean(ps[-short_n:])
    ma_long = mean(ps[-long_n:])
    trend_strength = 0.0 if ma_long <= 0 else (ma_short - ma_long) / ma_long

    # Use log-price slope on long window.
    log_ps = [math.log(p) for p in ps[-long_n:] if p > 0]
    slope = _lin_slope(log_ps)

    rets = _returns(ps[-(short_n + 1) :])
    volatility = pstdev(rets) if len(rets) >= 2 else 0.0

    vol_ratio = 1.0
    if volumes is not None:
        vs = _to_floats(volumes)
        if len(vs) >= 2:
            s_n = min(short_n, len(vs))
            l_n = min(long_n, len(vs))
            v_short = mean(vs[-s_n:]) if s_n > 0 else 0.0
            v_long = mean(vs[-l_n:]) if l_n > 0 else 0.0
            if v_long > 0:
                vol_ratio = v_short / v_long

    # Additional technical indicators
    rsi = _rsi(ps, period=14)
    momentum = _momentum(ps, lookback=10)
    _, _, channel_width = _price_channel(ps, window=20)
    atr = _atr(ps, period=14)

    return {
        "n": float(len(ps)),
        "ma_short": float(ma_short),
        "ma_long": float(ma_long),
        "trend_strength": float(trend_strength),
        "slope_pct": float(slope),
        "volatility": float(volatility),
        "vol_ratio": float(vol_ratio),
        "rsi": float(rsi),
        "momentum_pct": float(momentum),
        "channel_width": float(channel_width),
        "atr": float(atr),
    }

def _benchmark_ma_direction(benchmark_prices: Sequence[float], window: int = 20) -> str:
    """Determine benchmark (0050) MA direction as a hard regime indicator (#390).

    Returns 'up', 'down', or 'flat' based on 20-day MA slope.
    """
    ps = _to_floats(benchmark_prices)
    if len(ps) < window + 1:
        return "flat"
    ma_now = mean(ps[-window:])
    ma_prev = mean(ps[-(window + 1):-1])
    if ma_prev <= 0:
        return "flat"
    change_pct = (ma_now - ma_prev) / ma_prev
    if change_pct > 0.001:   # MA rising > 0.1%
        return "up"
    elif change_pct < -0.001:
        return "down"
    return "flat"


def _foreign_investor_streak(net_buy_days: Sequence[float]) -> int:
    """Count consecutive net-buy (positive) or net-sell (negative) days (#390).

    Args:
        net_buy_days: sequence of daily net buy amounts (positive = net buy),
                      ordered oldest to newest.
    Returns:
        Positive int for consecutive buy days, negative for sell days, 0 if mixed/empty.
    """
    vals = _to_floats(net_buy_days)
    if not vals:
        return 0
    streak = 0
    direction = 1 if vals[-1] > 0 else -1 if vals[-1] < 0 else 0
    for v in reversed(vals):
        if (direction > 0 and v > 0) or (direction < 0 and v < 0):
            streak += 1
        else:
            break
    return streak * direction


def classify_market_regime(
    prices: Sequence[float],
    volumes: Sequence[float] | None = None,
    *,
    short_window: int = 20,
    long_window: int = 60,
    trend_threshold: float = 0.01,
    slope_threshold: float = 0.0005,
    benchmark_prices: Sequence[float] | None = None,
    foreign_net_buy_days: Sequence[float] | None = None,
) -> MarketRegimeResult:
    """Classify bull/bear/range based on trend + volume + volatility.

    #390 enhancements:
    - benchmark_prices: 0050 price series for MA direction override
    - foreign_net_buy_days: institutional net buy amounts for confirmation
    """

    feats = compute_regime_features(prices, volumes, short_window=short_window, long_window=long_window)
    trend = feats["trend_strength"]
    slope = feats["slope_pct"]
    vol_ratio = feats["vol_ratio"]
    vol = feats["volatility"]

    vol_confirm = vol_ratio >= 0.90

    if trend > trend_threshold and slope > slope_threshold and vol_confirm:
        regime = MarketRegime.BULL
    elif trend < -trend_threshold and slope < -slope_threshold and vol_confirm:
        regime = MarketRegime.BEAR
    else:
        regime = MarketRegime.RANGE

    # ── Benchmark MA override (#390) ──────────────────────────────
    # 0050 MA direction is a hard indicator: if benchmark disagrees
    # with individual stock regime, downgrade to RANGE.
    if benchmark_prices is not None:
        bench_dir = _benchmark_ma_direction(benchmark_prices)
        feats["benchmark_ma_direction"] = {"up": 1.0, "down": -1.0, "flat": 0.0}[bench_dir]
        if regime == MarketRegime.BULL and bench_dir == "down":
            regime = MarketRegime.RANGE
            feats["regime_override"] = 1.0  # flag the override
        elif regime == MarketRegime.BEAR and bench_dir == "up":
            regime = MarketRegime.RANGE
            feats["regime_override"] = 1.0

    # ── Foreign investor streak (#390) ────────────────────────────
    # Strong institutional flow confirms or weakens the regime.
    if foreign_net_buy_days is not None:
        fi_streak = _foreign_investor_streak(foreign_net_buy_days)
        feats["foreign_investor_streak"] = float(fi_streak)
        # 5+ consecutive buy days in bear → upgrade to range
        if regime == MarketRegime.BEAR and fi_streak >= 5:
            regime = MarketRegime.RANGE
            feats["regime_fi_upgrade"] = 1.0
        # 5+ consecutive sell days in bull → downgrade to range
        elif regime == MarketRegime.BULL and fi_streak <= -5:
            regime = MarketRegime.RANGE
            feats["regime_fi_downgrade"] = 1.0

    # Confidence: mostly trend strength + slope, penalize extreme volatility.
    trend_score = min(1.0, abs(trend) / max(trend_threshold * 3.0, 1e-9))
    slope_score = min(1.0, abs(slope) / max(slope_threshold * 3.0, 1e-9))
    vol_score = 1.0 - min(1.0, vol / 0.04)
    confidence = _clamp(0.15 + 0.45 * trend_score + 0.25 * slope_score + 0.15 * vol_score)

    # Default posture: bear/range reduce risk, bull keeps baseline.
    if regime == MarketRegime.BULL:
        vol_mult = 1.0
        rm = {
            "max_loss_per_trade_pct_nav": 1.00,
            "max_gross_exposure": 1.00,
            "max_symbol_weight": 1.00,
        }
    elif regime == MarketRegime.BEAR:
        vol_mult = 0.70
        rm = {
            "max_loss_per_trade_pct_nav": 0.70,
            "max_gross_exposure": 0.80,
            "max_symbol_weight": 0.90,
        }
    else:
        vol_mult = 0.85
        rm = {
            "max_loss_per_trade_pct_nav": 0.85,
            "max_gross_exposure": 0.90,
            "max_symbol_weight": 0.95,
        }

    return MarketRegimeResult(
        regime=regime,
        confidence=float(confidence),
        features=feats,
        volatility_multiplier=float(vol_mult),
        risk_multipliers=rm,
    )


def apply_market_regime_risk_adjustments(
    limits: Mapping[str, object],
    result: MarketRegimeResult,
    *,
    include_metadata: bool = True,
) -> Dict[str, object]:
    """Apply regime-derived multipliers to a flattened limits dict."""

    adjusted: Dict[str, object] = {str(k): v for k, v in limits.items()}
    for k, m in (result.risk_multipliers or {}).items():
        if k not in adjusted:
            continue
        try:
            adjusted[k] = float(adjusted[k]) * float(m)
        except Exception:
            continue

    if include_metadata:
        adjusted["market_regime"] = result.regime.value
        adjusted["market_regime_confidence"] = float(result.confidence)
        adjusted["market_regime_volatility_multiplier"] = float(result.volatility_multiplier)
    return adjusted


@dataclass(frozen=True)
class MarketRegimePolicy:
    """Optional JSON-config policy for regime multipliers."""

    multipliers: Mapping[str, Mapping[str, float]]
    volatility_multiplier: Mapping[str, float]

    @staticmethod
    def default() -> "MarketRegimePolicy":
        return MarketRegimePolicy(
            multipliers={
                "bull": {"max_loss_per_trade_pct_nav": 1.00, "max_gross_exposure": 1.00, "max_symbol_weight": 1.00},
                "bear": {"max_loss_per_trade_pct_nav": 0.70, "max_gross_exposure": 0.80, "max_symbol_weight": 0.90},
                "range": {"max_loss_per_trade_pct_nav": 0.85, "max_gross_exposure": 0.90, "max_symbol_weight": 0.95},
            },
            volatility_multiplier={"bull": 1.0, "bear": 0.70, "range": 0.85},
        )


def load_market_regime_policy(path: str = "config/market_regime_v1.json") -> MarketRegimePolicy | None:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None

    mult = raw.get("multipliers")
    volm = raw.get("volatility_multiplier")
    if not isinstance(mult, dict) or not isinstance(volm, dict):
        return None

    out_mult: Dict[str, Dict[str, float]] = {}
    for rk, rv in mult.items():
        if not isinstance(rv, dict):
            continue
        d: Dict[str, float] = {}
        for k, v in rv.items():
            try:
                d[str(k)] = float(v)
            except Exception:
                continue
        if d:
            out_mult[str(rk)] = d

    out_vol: Dict[str, float] = {}
    for rk, v in volm.items():
        try:
            out_vol[str(rk)] = float(v)
        except Exception:
            continue

    if not out_mult or not out_vol:
        return None

    return MarketRegimePolicy(multipliers=out_mult, volatility_multiplier=out_vol)


def apply_policy_to_result(result: MarketRegimeResult, policy: MarketRegimePolicy) -> MarketRegimeResult:
    rk = result.regime.value
    rm = policy.multipliers.get(rk) or (result.risk_multipliers or {})
    vm = float(policy.volatility_multiplier.get(rk, result.volatility_multiplier))
    return MarketRegimeResult(
        regime=result.regime,
        confidence=result.confidence,
        features=dict(result.features),
        volatility_multiplier=vm,
        risk_multipliers=dict(rm),
    )
