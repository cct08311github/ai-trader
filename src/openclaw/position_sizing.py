from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional


@dataclass
class PositionSizingInput:
    """Legacy fixed-fractional sizing input.

    Kept for backward compatibility with early v4 tests and reference code.
    """

    nav: float
    entry_price: float
    stop_price: float
    base_risk_pct: float
    confidence: float = 1.0
    confidence_threshold: float = 0.60
    low_confidence_scale: float = 0.50
    volatility_multiplier: float = 1.0


def fixed_fractional_qty(inp: PositionSizingInput) -> int:
    """Fixed fractional sizing using explicit stop distance.

    qty = (NAV * risk_pct) / |entry - stop|

    Notes:
    - This function intentionally does NOT read external policy files.
    - Use `calculate_position_qty(...)` if you want Level 0-3 caps.
    """

    if inp.nav <= 0 or inp.entry_price <= 0 or inp.stop_price <= 0:
        return 0
    # 如果停損價高於入場價（負風險），返回 0
    if inp.stop_price > inp.entry_price:
        return 0
    stop_distance = abs(inp.entry_price - inp.stop_price)
    if stop_distance <= 0:
        return 0

    effective_risk_pct = max(0.0, inp.base_risk_pct * max(inp.volatility_multiplier, 0.0))
    max_loss_abs = inp.nav * effective_risk_pct
    qty = int(max_loss_abs / stop_distance)
    if qty <= 0:
        return 0

    if inp.confidence < inp.confidence_threshold:
        qty = int(qty * inp.low_confidence_scale)
    return max(0, qty)


@dataclass(frozen=True)
class PositionLevelLimits:
    """Level 0-3 position sizing caps loaded from Sentinel policy."""

    max_risk_per_trade_pct_nav: float
    max_position_notional_pct_nav: float


_DEFAULT_LEVEL_LIMITS: dict[int, PositionLevelLimits] = {
    # Level 0: observe-only, no positions.
    0: PositionLevelLimits(max_risk_per_trade_pct_nav=0.0, max_position_notional_pct_nav=0.0),
    # Level 1: log-only (very small), mostly to validate wiring.
    1: PositionLevelLimits(max_risk_per_trade_pct_nav=0.001, max_position_notional_pct_nav=0.01),
    # Level 2: propose/manual approval.
    2: PositionLevelLimits(max_risk_per_trade_pct_nav=0.003, max_position_notional_pct_nav=0.05),
    # Level 3: auto-approve (still bounded).
    3: PositionLevelLimits(max_risk_per_trade_pct_nav=0.005, max_position_notional_pct_nav=0.10),
}


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def load_sentinel_policy(policy_path: str) -> dict[str, Any]:
    """Load Sentinel policy JSON (best-effort).

    This module uses the policy as a *risk cap* input. If the file is missing
    or malformed, we fall back to safe defaults.
    """

    try:
        text = Path(policy_path).read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return {}


def get_position_limits_for_level(policy: Mapping[str, Any], level: int) -> PositionLevelLimits:
    """Extract Level 0-3 position limits from sentinel_policy_v1.json.

    Expected shape:
    {
      "position_limits": {
        "levels": {
          "0": {"max_risk_per_trade_pct_nav": 0.0, "max_position_notional_pct_nav": 0.0},
          "1": {...},
          "2": {...},
          "3": {...}
        }
      }
    }

    Falls back to `_DEFAULT_LEVEL_LIMITS` when fields are missing.
    """

    lvl = int(level)
    defaults = _DEFAULT_LEVEL_LIMITS.get(lvl, _DEFAULT_LEVEL_LIMITS[2])
    if not isinstance(policy, Mapping):
        return defaults
    
    position_limits = policy.get("position_limits")
    if not isinstance(position_limits, Mapping):
        return defaults
    
    levels = position_limits.get("levels")
    if not isinstance(levels, Mapping):
        return defaults

    raw = levels.get(str(lvl))
    if not isinstance(raw, Mapping):
        return defaults

    max_risk = _safe_float(raw.get("max_risk_per_trade_pct_nav"), defaults.max_risk_per_trade_pct_nav)
    max_notional = _safe_float(raw.get("max_position_notional_pct_nav"), defaults.max_position_notional_pct_nav)
    max_risk = max(0.0, min(max_risk, 1.0))
    max_notional = max(0.0, min(max_notional, 1.0))
    return PositionLevelLimits(max_risk_per_trade_pct_nav=max_risk, max_position_notional_pct_nav=max_notional)


@dataclass
class ATRPositionSizingInput:
    """ATR-based sizing input.

    qty = (NAV * risk_pct) / (ATR * atr_stop_multiple)

    Where ATR is in price units (same as entry price).
    """

    nav: float
    entry_price: float
    atr: float
    base_risk_pct: float
    atr_stop_multiple: float = 2.0
    confidence: float = 1.0
    confidence_threshold: float = 0.60
    low_confidence_scale: float = 0.50
    volatility_multiplier: float = 1.0


def _apply_level_caps(
    *,
    qty: int,
    entry_price: float,
    nav: float,
    level_limits: Optional[PositionLevelLimits],
    avg_daily_volume_twd: float | None = None,
    max_adv_pct: float = 0.10,
) -> int:
    if qty <= 0:
        return 0
    if entry_price <= 0 or nav <= 0:
        return 0
    if level_limits is None:
        # Still apply ADV cap even without level limits.
        if avg_daily_volume_twd and avg_daily_volume_twd > 0 and max_adv_pct > 0:
            adv_notional = avg_daily_volume_twd * max(0.0, max_adv_pct)
            adv_qty = int(adv_notional / entry_price)
            qty = max(0, min(qty, adv_qty))
        return qty

    # Notional cap from sentinel level limits.
    max_notional = nav * max(0.0, level_limits.max_position_notional_pct_nav)

    # ADV cap: position value ≤ max_adv_pct × average_daily_volume (in TWD).
    if avg_daily_volume_twd and avg_daily_volume_twd > 0 and max_adv_pct > 0:
        adv_notional = avg_daily_volume_twd * max(0.0, max_adv_pct)
        max_notional = min(max_notional, adv_notional)

    if max_notional <= 0:
        return 0

    capped_qty = int(max_notional / entry_price)
    return max(0, min(int(qty), capped_qty))


def atr_risk_qty(
    inp: ATRPositionSizingInput,
    *,
    level_limits: Optional[PositionLevelLimits] = None,
    avg_daily_volume_twd: float | None = None,
    max_adv_pct: float = 0.10,
) -> int:
    if inp.nav <= 0 or inp.entry_price <= 0 or inp.atr <= 0:
        return 0

    stop_distance = inp.atr * max(inp.atr_stop_multiple, 0.0)
    if stop_distance <= 0:
        return 0

    effective_risk_pct = max(0.0, inp.base_risk_pct * max(inp.volatility_multiplier, 0.0))
    if level_limits is not None:
        effective_risk_pct = min(effective_risk_pct, max(0.0, level_limits.max_risk_per_trade_pct_nav))

    if effective_risk_pct <= 0:
        return 0

    max_loss_abs = inp.nav * effective_risk_pct
    qty = int(max_loss_abs / stop_distance)
    if qty <= 0:
        return 0

    if inp.confidence < inp.confidence_threshold:
        qty = int(qty * inp.low_confidence_scale)

    qty = _apply_level_caps(
        qty=qty,
        entry_price=inp.entry_price,
        nav=inp.nav,
        level_limits=level_limits,
        avg_daily_volume_twd=avg_daily_volume_twd,
        max_adv_pct=max_adv_pct,
    )
    return max(0, int(qty))


def fetch_avg_daily_volume_twd(
    conn: "sqlite3.Connection",
    symbol: str,
    days: int = 20,
) -> float | None:
    """Compute average daily turnover (TWD) for *symbol* over the last *days* trading days.

    Returns ``None`` when there is insufficient data or the table does not exist.
    ADV_TWD = avg(volume * close) over the lookback window.
    """
    try:
        rows = conn.execute(
            """
            SELECT volume, close
            FROM eod_prices
            WHERE symbol = ?
              AND volume > 0
              AND close > 0
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            (symbol, days),
        ).fetchall()
    except Exception:
        return None

    if not rows:
        return None
    total = sum(float(r[0]) * float(r[1]) for r in rows)
    return total / len(rows)


def calculate_position_qty(
    *,
    nav: float,
    entry_price: float,
    base_risk_pct: float,
    stop_price: float | None = None,
    atr: float | None = None,
    atr_stop_multiple: float = 2.0,
    confidence: float = 1.0,
    confidence_threshold: float = 0.60,
    low_confidence_scale: float = 0.50,
    volatility_multiplier: float = 1.0,
    method: str = "fixed_fractional",
    authority_level: int | None = None,
    sentinel_policy_path: str = "config/sentinel_policy_v1.json",
    avg_daily_volume_twd: float | None = None,
    max_adv_pct: float = 0.10,
) -> int:
    """Unified sizing entrypoint.

    This provides:
    - ATR-based sizing (preferred when ATR is available)
    - Level 0-3 caps from Sentinel policy
    - Backward compatible fixed-fractional sizing

    `authority_level` is interpreted as Level 0-3.
    """

    level_limits: Optional[PositionLevelLimits] = None
    if authority_level is not None:
        policy = load_sentinel_policy(sentinel_policy_path)
        level_limits = get_position_limits_for_level(policy, int(authority_level))

    m = (method or "fixed_fractional").strip().lower()
    if m in {"atr", "atr_risk", "atr_based"} and atr is not None and atr > 0:
        return atr_risk_qty(
            ATRPositionSizingInput(
                nav=nav,
                entry_price=entry_price,
                atr=atr,
                base_risk_pct=base_risk_pct,
                atr_stop_multiple=atr_stop_multiple,
                confidence=confidence,
                confidence_threshold=confidence_threshold,
                low_confidence_scale=low_confidence_scale,
                volatility_multiplier=volatility_multiplier,
            ),
            level_limits=level_limits,
            avg_daily_volume_twd=avg_daily_volume_twd,
            max_adv_pct=max_adv_pct,
        )

    # Fallback: fixed-fractional using stop price.
    if stop_price is None:
        return 0
    qty = fixed_fractional_qty(
        PositionSizingInput(
            nav=nav,
            entry_price=entry_price,
            stop_price=stop_price,
            base_risk_pct=base_risk_pct,
            confidence=confidence,
            confidence_threshold=confidence_threshold,
            low_confidence_scale=low_confidence_scale,
            volatility_multiplier=volatility_multiplier,
        )
    )

    qty = _apply_level_caps(
        qty=qty,
        entry_price=entry_price,
        nav=nav,
        level_limits=level_limits,
        avg_daily_volume_twd=avg_daily_volume_twd,
        max_adv_pct=max_adv_pct,
    )
    return max(0, int(qty))
