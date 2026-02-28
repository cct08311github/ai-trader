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
    if den <= 0:
        return 0.0
    return num / den


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

    return {
        "n": float(len(ps)),
        "ma_short": float(ma_short),
        "ma_long": float(ma_long),
        "trend_strength": float(trend_strength),
        "slope_pct": float(slope),
        "volatility": float(volatility),
        "vol_ratio": float(vol_ratio),
    }


def classify_market_regime(
    prices: Sequence[float],
    volumes: Sequence[float] | None = None,
    *,
    short_window: int = 20,
    long_window: int = 60,
    trend_threshold: float = 0.01,
    slope_threshold: float = 0.0005,
) -> MarketRegimeResult:
    """Classify bull/bear/range based on trend + volume + volatility."""

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
