"""config_manager.py — Centralized configuration loading for the AI Trader core engine.

Replaces the scattered JSON-loading patterns found across 10+ modules.
Each config file is loaded once, cached, and served via typed accessors.
Thread-safe reads; call ``invalidate()`` to force a reload.

Usage::

    from openclaw.config_manager import get_config

    cfg = get_config()              # module-level singleton
    symbols = cfg.locked_symbols()  # cached, fail-safe
    watchlist = cfg.watchlist()     # cached, fail-safe
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from openclaw.path_utils import get_repo_root

logger = logging.getLogger(__name__)

_TZ_TWN = timezone(timedelta(hours=8))


# ── Typed config dataclasses ────────────────────────────────────────────────


@dataclass(frozen=True)
class CapitalConfig:
    total_capital_twd: float = 1_000_000.0
    max_single_position_pct: float = 0.20
    daily_loss_limit_twd: float = 10_000.0
    monthly_loss_limit_twd: float = 50_000.0
    monthly_api_budget_twd: float = 2_000.0
    default_stop_loss_pct: float = 0.05
    default_take_profit_pct: float = 0.10


@dataclass(frozen=True)
class WatchlistConfig:
    manual_watchlist: List[str] = field(default_factory=list)
    max_system_candidates: int = 10


@dataclass(frozen=True)
class DailyPMState:
    date: str = ""
    approved: bool = False
    confidence: float = 0.0
    reason: str = ""
    reviewed_at: str = ""
    source: str = ""


# ── ConfigManager ───────────────────────────────────────────────────────────


class ConfigManager:
    """Centralized, cached, thread-safe config loader.

    Parameters
    ----------
    config_dir : Path, optional
        Override the default ``<repo_root>/config`` directory.  Useful for
        testing with a temporary directory.
    """

    def __init__(self, config_dir: Optional[Path] = None) -> None:
        self._config_dir = config_dir or (get_repo_root() / "config")
        self._cache: Dict[str, Any] = {}
        self._lock = threading.Lock()

    # ── Public accessors ────────────────────────────────────────────────

    def locked_symbols(self) -> Set[str]:
        """Return the set of locked (sell-forbidden) symbols, upper-cased."""
        data = self._load_json("locked_symbols.json", default={"locked": []})
        return {s.upper() for s in data.get("locked", [])}

    def watchlist(self) -> WatchlistConfig:
        """Return the manual watchlist configuration.

        Backward-compatible: falls back to ``universe`` key if
        ``manual_watchlist`` is absent.
        """
        data = self._load_json("watchlist.json", default={})
        wl = data.get("manual_watchlist") or data.get("universe") or []
        return WatchlistConfig(
            manual_watchlist=list(wl),
            max_system_candidates=int(data.get("max_system_candidates", 10)),
        )

    def capital(self) -> CapitalConfig:
        """Return capital / risk-limit configuration."""
        data = self._load_json("capital.json", default={})
        return CapitalConfig(
            total_capital_twd=float(data.get("total_capital_twd", 1_000_000.0)),
            max_single_position_pct=float(data.get("max_single_position_pct", 0.20)),
            daily_loss_limit_twd=float(data.get("daily_loss_limit_twd", 10_000.0)),
            monthly_loss_limit_twd=float(data.get("monthly_loss_limit_twd", 50_000.0)),
            monthly_api_budget_twd=float(data.get("monthly_api_budget_twd", 2_000.0)),
            default_stop_loss_pct=float(data.get("default_stop_loss_pct", 0.05)),
            default_take_profit_pct=float(data.get("default_take_profit_pct", 0.10)),
        )

    def daily_pm_state(self) -> DailyPMState:
        """Return today's PM review state.  Always reloads (not cached)."""
        data = self._load_json("daily_pm_state.json", default={}, use_cache=False)
        return DailyPMState(
            date=str(data.get("date", "")),
            approved=bool(data.get("approved", False)),
            confidence=float(data.get("confidence", 0.0)),
            reason=str(data.get("reason", "")),
            reviewed_at=str(data.get("reviewed_at", "")),
            source=str(data.get("source", "")),
        )

    def is_pm_approved_today(self) -> bool:
        """Check if today's PM review is approved. Fail-safe: False."""
        state = self.daily_pm_state()
        today = datetime.now(tz=_TZ_TWN).strftime("%Y-%m-%d")
        return state.date == today and state.approved

    def system_state(self) -> Dict[str, Any]:
        """Return the raw system_state.json dict.  Always reloads (not cached)."""
        return self._load_json("system_state.json", default={}, use_cache=False)

    def drawdown_policy(self) -> Dict[str, Any]:
        """Return raw drawdown_policy_v1.json dict."""
        return self._load_json("drawdown_policy_v1.json", default={})

    def sentinel_policy(self) -> Dict[str, Any]:
        """Return raw sentinel_policy_v1.json dict."""
        return self._load_json("sentinel_policy_v1.json", default={})

    def alert_policy(self) -> Dict[str, Any]:
        """Return raw alert_policy.json dict."""
        return self._load_json("alert_policy.json", default={})

    def raw(self, filename: str, *, use_cache: bool = True) -> Dict[str, Any]:
        """Load an arbitrary config JSON by filename."""
        return self._load_json(filename, default={}, use_cache=use_cache)

    # ── Cache management ────────────────────────────────────────────────

    def invalidate(self, filename: Optional[str] = None) -> None:
        """Clear cached config.  If *filename* is None, clear everything."""
        with self._lock:
            if filename:
                self._cache.pop(filename, None)
            else:
                self._cache.clear()

    # ── Internal helpers ────────────────────────────────────────────────

    def _load_json(
        self,
        filename: str,
        *,
        default: Any = None,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """Load a JSON file from the config directory with caching and fail-safe."""
        if use_cache:
            with self._lock:
                if filename in self._cache:
                    return self._cache[filename]

        path = self._config_dir / filename
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            logger.debug("Config file not found: %s, using defaults", path)
            return default if default is not None else {}
        except json.JSONDecodeError as e:
            logger.warning("Corrupted config file: %s — %s", path, e)
            return default if default is not None else {}
        except OSError as e:
            logger.error("OS error reading %s: %s", path, e)
            return default if default is not None else {}

        if use_cache:
            with self._lock:
                self._cache[filename] = data

        return data


# ── Module-level singleton ──────────────────────────────────────────────────

_instance: Optional[ConfigManager] = None
_instance_lock = threading.Lock()


def get_config(config_dir: Optional[Path] = None) -> ConfigManager:
    """Return the module-level ConfigManager singleton.

    On first call (or after ``reset_config()``), a new instance is created.
    Pass *config_dir* only if you need a non-default directory (e.g. tests).
    """
    global _instance
    if _instance is not None and config_dir is None:
        return _instance
    with _instance_lock:
        if _instance is None or config_dir is not None:
            _instance = ConfigManager(config_dir=config_dir)
        return _instance


def reset_config() -> None:
    """Reset the singleton.  Mainly for testing."""
    global _instance
    with _instance_lock:
        _instance = None
