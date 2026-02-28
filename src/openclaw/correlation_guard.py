"""Position Correlation Guard (v4 #22).

Purpose
-------
Monitor portfolio correlation risk and produce actionable suggestions.

This is a *risk* module:
- It does NOT try to predict returns.
- It focuses on concentration via correlated exposures.

Inputs are intentionally generic to keep the module dependency-light:
- returns_by_symbol: mapping symbol -> list of periodic returns
- weights_by_symbol: mapping symbol -> portfolio weights (0..1)

Output:
- CorrelationGuardDecision with risk metrics and suggested actions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple


def _safe_float(v: Any, default: float | None = None) -> float | None:
    try:
        fv = float(v)
    except Exception:
        return default
    if not math.isfinite(fv):
        return default
    return fv


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(var)


def pearson_corr(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Compute Pearson correlation between two sequences.

    Returns 0.0 when correlation is undefined (too few points or zero variance).
    """

    n = min(len(xs), len(ys))
    if n < 2:
        return 0.0
    x = list(xs[-n:])
    y = list(ys[-n:])

    mx = _mean(x)
    my = _mean(y)
    sx = _std(x)
    sy = _std(y)
    if sx <= 1e-12 or sy <= 1e-12:
        return 0.0

    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n)) / (n - 1)
    return float(max(-1.0, min(1.0, cov / (sx * sy))))


def compute_correlation_matrix(
    returns_by_symbol: Mapping[str, Sequence[float]],
    *,
    window: int = 60,
    min_points: int = 10,
) -> Dict[str, Dict[str, float]]:
    """Compute a correlation matrix for symbols with enough data."""

    clean: Dict[str, List[float]] = {}
    for sym, seq in returns_by_symbol.items():
        vals: List[float] = []
        for v in seq[-window:]:
            fv = _safe_float(v)
            if fv is None:
                continue
            vals.append(float(fv))
        if len(vals) >= min_points:
            clean[str(sym)] = vals

    syms = sorted(clean.keys())
    out: Dict[str, Dict[str, float]] = {s: {} for s in syms}
    for i, s1 in enumerate(syms):
        out[s1][s1] = 1.0
        for j in range(i + 1, len(syms)):
            s2 = syms[j]
            c = pearson_corr(clean[s1], clean[s2])
            out[s1][s2] = c
            out[s2][s1] = c
    return out


@dataclass(frozen=True)
class CorrelationGuardPolicy:
    window: int = 60
    min_points: int = 10

    # Hard/soft thresholds
    max_pair_abs_corr: float = 0.85
    max_weighted_avg_abs_corr: float = 0.55

    # When breached, apply suggested scaling to exposure limits.
    exposure_scale_on_breach: float = 0.80

    @staticmethod
    def default() -> "CorrelationGuardPolicy":
        return CorrelationGuardPolicy()


@dataclass(frozen=True)
class CorrelationGuardDecision:
    ok: bool
    reason_code: str
    n_symbols: int
    max_pair_abs_corr: float
    weighted_avg_abs_corr: float
    top_pairs: List[Tuple[str, str, float]]
    suggestions: List[str]
    matrix: Dict[str, Dict[str, float]]


def _normalize_weights(weights_by_symbol: Mapping[str, float]) -> Dict[str, float]:
    w: Dict[str, float] = {}
    for k, v in weights_by_symbol.items():
        fv = _safe_float(v)
        if fv is None:
            continue
        if fv <= 0:
            continue
        w[str(k)] = float(fv)
    s = sum(w.values())
    if s <= 0:
        return {}
    return {k: v / s for k, v in w.items()}


def _weighted_avg_abs_corr(matrix: Mapping[str, Mapping[str, float]], weights: Mapping[str, float]) -> float:
    syms = [s for s in matrix.keys() if s in weights]
    if len(syms) < 2:
        return 0.0

    num = 0.0
    den = 0.0
    for i in range(len(syms)):
        for j in range(i + 1, len(syms)):
            s1, s2 = syms[i], syms[j]
            c = float(matrix.get(s1, {}).get(s2, 0.0))
            w = float(weights[s1]) * float(weights[s2])
            num += abs(c) * w
            den += w

    if den <= 0:
        return 0.0
    return float(num / den)


def evaluate_correlation_risk(
    *,
    returns_by_symbol: Mapping[str, Sequence[float]],
    weights_by_symbol: Mapping[str, float],
    policy: CorrelationGuardPolicy | None = None,
) -> CorrelationGuardDecision:
    pol = policy or CorrelationGuardPolicy.default()

    matrix = compute_correlation_matrix(
        returns_by_symbol,
        window=pol.window,
        min_points=pol.min_points,
    )

    weights = _normalize_weights(weights_by_symbol)
    syms = [s for s in matrix.keys() if s in weights]

    max_abs = 0.0
    top: List[Tuple[str, str, float]] = []
    for i in range(len(syms)):
        for j in range(i + 1, len(syms)):
            s1, s2 = syms[i], syms[j]
            c = float(matrix[s1].get(s2, 0.0))
            a = abs(c)
            if a > max_abs:
                max_abs = a
            top.append((s1, s2, c))

    top.sort(key=lambda t: abs(t[2]), reverse=True)
    top_pairs = top[:5]

    wavg = _weighted_avg_abs_corr(matrix, weights)

    breached_pair = max_abs >= pol.max_pair_abs_corr
    breached_avg = wavg >= pol.max_weighted_avg_abs_corr
    ok = not (breached_pair or breached_avg)

    suggestions: List[str] = []
    reason = "CORR_OK"
    if breached_pair:
        reason = "CORR_MAX_PAIR_EXCEEDED"
        if top_pairs:
            s1, s2, c = top_pairs[0]
            # Reduce the larger-weight symbol first.
            w1 = weights.get(s1, 0.0)
            w2 = weights.get(s2, 0.0)
            reduce_sym = s1 if w1 >= w2 else s2
            suggestions.append(
                f"Reduce exposure on {reduce_sym} (top correlated pair {s1}/{s2} corr={c:.2f})."
            )

    if breached_avg:
        if reason == "CORR_OK":
            reason = "CORR_WEIGHTED_AVG_EXCEEDED"
        suggestions.append(
            "Increase diversification: lower gross exposure or add uncorrelated exposure / cash buffer."
        )

    if not suggestions and not ok:
        suggestions.append("Reduce correlated exposures.")

    return CorrelationGuardDecision(
        ok=ok,
        reason_code=reason,
        n_symbols=len(syms),
        max_pair_abs_corr=float(max_abs),
        weighted_avg_abs_corr=float(wavg),
        top_pairs=top_pairs,
        suggestions=suggestions,
        matrix={k: dict(v) for k, v in matrix.items()},
    )


def apply_correlation_guard_to_limits(
    limits: Mapping[str, Any],
    decision: CorrelationGuardDecision,
    *,
    policy: CorrelationGuardPolicy | None = None,
) -> Dict[str, Any]:
    """Apply correlation-guard adjustments to flattened limits dict.

    If breached, scales down max_gross_exposure and max_symbol_weight.
    """

    pol = policy or CorrelationGuardPolicy.default()
    out: Dict[str, Any] = {str(k): v for k, v in limits.items()}

    if decision.ok:
        out["correlation_guard_ok"] = True
        out["correlation_guard_reason"] = decision.reason_code
        return out

    scale = float(pol.exposure_scale_on_breach)

    for k in ("max_gross_exposure", "max_symbol_weight"):
        if k not in out:
            continue
        try:
            out[k] = float(out[k]) * scale
        except Exception:
            continue

    out["correlation_guard_ok"] = False
    out["correlation_guard_reason"] = decision.reason_code
    out["correlation_guard_scale"] = scale
    return out
