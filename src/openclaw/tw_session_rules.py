from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from pathlib import Path
from typing import Dict, Mapping, Optional

from zoneinfo import ZoneInfo


class TWTradingPhase(str, Enum):
    """Taiwan equity market session phase (UTC+8).

    Canonical phases for OpenClaw v4 Batch-D:
      - preopen_auction: 09:00-09:10
      - regular:         09:10-13:25
      - afterhours:      13:30-13:40
      - closed:          otherwise

    We keep the schedule hard-coded to avoid accidental misconfiguration.
    JSON (sentinel_policy_v1.json) is used only for *risk multipliers*.
    """

    PREOPEN_AUCTION = "preopen_auction"
    REGULAR = "regular"
    AFTERHOURS_AUCTION = "afterhours_auction"
    CLOSED = "closed"


@dataclass(frozen=True)
class TWSessionConfig:
    tz: str

    # Multipliers applied to flattened risk `limits`.
    preopen_multipliers: Mapping[str, float]
    regular_multipliers: Mapping[str, float]
    afterhours_multipliers: Mapping[str, float]

    @staticmethod
    def default() -> "TWSessionConfig":
        # Conservative defaults: auction sessions are thinner & more discontinuous.
        return TWSessionConfig(
            tz="Asia/Taipei",
            preopen_multipliers={
                "max_orders_per_min": 0.50,
                "max_slippage_bps": 0.80,
                "max_price_deviation_pct": 0.80,
                "max_qty_to_1m_volume_ratio": 0.70,
                "max_loss_per_trade_pct_nav": 0.70,
            },
            regular_multipliers={
                "max_orders_per_min": 1.00,
                "max_slippage_bps": 1.00,
                "max_price_deviation_pct": 1.00,
                "max_qty_to_1m_volume_ratio": 1.00,
                "max_loss_per_trade_pct_nav": 1.00,
            },
            afterhours_multipliers={
                "max_orders_per_min": 0.60,
                "max_slippage_bps": 0.70,
                "max_price_deviation_pct": 0.80,
                "max_qty_to_1m_volume_ratio": 0.50,
                "max_loss_per_trade_pct_nav": 0.70,
            },
        )


_PREOPEN_START = time(9, 0)
_PREOPEN_END = time(9, 10)
_REGULAR_START = time(9, 10)
_REGULAR_END = time(13, 25)
_AFTER_START = time(13, 30)
_AFTER_END = time(13, 40)


def _to_local_time_of_day(now_ms: int, tz: ZoneInfo) -> time:
    dt = datetime.fromtimestamp(now_ms / 1000, tz=tz)
    return dt.timetz().replace(tzinfo=None)


def get_tw_trading_phase(now_ms: int, tz: str = "Asia/Taipei") -> TWTradingPhase:
    """Return current TW market phase for a given epoch-ms."""

    z = ZoneInfo(tz)
    tod = _to_local_time_of_day(now_ms, z)

    if _PREOPEN_START <= tod < _PREOPEN_END:
        return TWTradingPhase.PREOPEN_AUCTION
    if _REGULAR_START <= tod < _REGULAR_END:
        return TWTradingPhase.REGULAR
    if _AFTER_START <= tod < _AFTER_END:
        return TWTradingPhase.AFTERHOURS_AUCTION
    return TWTradingPhase.CLOSED


def _load_sentinel_tw_session_config(sentinel_policy_path: str) -> Optional[TWSessionConfig]:
    """Load TW session multipliers from sentinel_policy_v1.json.

    This function is *optional* and must never throw: if the policy file is
    missing / malformed / has no session config, we fall back to defaults.
    """

    try:
        p = Path(sentinel_policy_path)
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None

    cfg = raw.get("tw_session_rules")
    if not isinstance(cfg, dict):
        return None

    def _mp(key: str) -> Optional[Mapping[str, float]]:
        v = cfg.get(key)
        if not isinstance(v, dict):
            return None
        out: Dict[str, float] = {}
        for k, vv in v.items():
            try:
                out[str(k)] = float(vv)
            except Exception:
                continue
        return out

    preopen = _mp("preopen_auction")
    regular = _mp("regular")
    after = _mp("afterhours_auction")

    if preopen is None and regular is None and after is None:
        return None

    base = TWSessionConfig.default()
    return TWSessionConfig(
        tz=str(cfg.get("timezone", base.tz)),
        preopen_multipliers=preopen or base.preopen_multipliers,
        regular_multipliers=regular or base.regular_multipliers,
        afterhours_multipliers=after or base.afterhours_multipliers,
    )


def apply_tw_session_risk_adjustments(
    limits: Mapping[str, object],
    *,
    now_ms: int,
    sentinel_policy_path: str = "config/sentinel_policy_v1.json",
) -> Dict[str, object]:
    """Apply Taiwan-session-aware risk multipliers to a flattened limits dict.

    - Only keys present in both `limits` and multipliers are modified.
    - CLOSED phase returns the original limits (no implicit lock).
      Session-level lock is the responsibility of the orchestrator.
    """

    base_limits: Dict[str, object] = {str(k): v for k, v in limits.items()}
    cfg = _load_sentinel_tw_session_config(sentinel_policy_path) or TWSessionConfig.default()

    phase = get_tw_trading_phase(now_ms, tz=cfg.tz)
    if phase == TWTradingPhase.CLOSED:
        return dict(base_limits)

    if phase == TWTradingPhase.PREOPEN_AUCTION:
        multipliers = cfg.preopen_multipliers
    elif phase == TWTradingPhase.REGULAR:
        multipliers = cfg.regular_multipliers
    else:
        multipliers = cfg.afterhours_multipliers

    adjusted = dict(base_limits)
    for k, m in multipliers.items():
        if k not in adjusted:
            continue
        try:
            adjusted[k] = float(adjusted[k]) * float(m)
        except Exception:
            # Don't allow session config to break risk evaluation.
            continue

    # Useful debug metadata for audit logs / metrics.
    adjusted["tw_trading_phase"] = phase.value  # type: ignore[assignment]
    return adjusted


def tw_session_allows_trading(now_ms: int, tz: str = "Asia/Taipei") -> bool:
    """True if the timestamp is inside one of the TW trading phases."""

    return get_tw_trading_phase(now_ms, tz=tz) != TWTradingPhase.CLOSED
