from __future__ import annotations

import os
import json
import time
from typing import Any, Dict, List, Literal, Optional

SYSTEM_STATE_PATH = os.path.join(os.path.dirname(__file__), "../../../../config/system_state.json")

def _get_system_simulation_mode() -> bool:
    """Read simulation_mode from system_state.json (single source of truth)."""
    try:
        with open(SYSTEM_STATE_PATH, "r") as f:
            state = json.load(f)
        return bool(state.get("simulation_mode", True))
    except Exception:
        return True  # Default to simulation if file unreadable

# Runtime cache: keyed by simulation flag, cleared on mode switch
_api_cache: Dict[bool, Any] = {}

def _clear_api_cache():
    """Clear Shioaji API cache (call after simulation mode switch)."""
    global _api_cache
    _api_cache.clear()

def _get_api(simulation: bool):
    """Create (and cache) Shioaji API instance keyed by simulation mode.

    Cache is separate for True/False so switching between modes works correctly.
    """
    if simulation in _api_cache:
        return _api_cache[simulation]

    try:
        import shioaji as sj  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "shioaji 未安裝。若要使用真實/模擬券商模式，請執行：\n"
            "  pip install shioaji>=1.0\n"
            "或繼續使用 Mock 模式（預設）。"
        ) from exc

    api = sj.Shioaji(simulation=simulation)
    api_key    = os.environ.get("SHIOAJI_API_KEY")
    secret_key = os.environ.get("SHIOAJI_SECRET_KEY")

    if not api_key or not secret_key:
        raise RuntimeError("Missing SHIOAJI_API_KEY / SHIOAJI_SECRET_KEY env vars")

    api.login(api_key=api_key, secret_key=secret_key)
    _api_cache[simulation] = api
    return api


def _mock_positions() -> List[Dict[str, Any]]:
    """Stable mock schema for frontend dev / fallback."""
    return [
        {
            "account": "SIMULATION",
            "symbol": "2330",
            "name": "TSMC",
            "qty": 100,
            "avg_price": 600.0,
            "last_price": 620.0,
            "market_value": 62000.0,
            "unrealized_pnl": 2000.0,
            "currency": "TWD",
            "chip_health_score": 8,
        },
        {
            "account": "SIMULATION",
            "symbol": "0050",
            "name": "TW50 ETF",
            "qty": 10,
            "avg_price": 140.0,
            "last_price": 142.0,
            "market_value": 1420.0,
            "unrealized_pnl": 20.0,
            "currency": "TWD",
            "chip_health_score": 5,
        },
    ]


def get_positions(
    *,
    source: Literal["mock", "shioaji"] = "shioaji",
    simulation: Optional[bool] = None,  # None = read from system_state.json
    max_wait_seconds: float = 5.0,
) -> Dict[str, Any]:
    """Fetch positions.

    Args:
        source: 'mock' returns hard-coded mock data. 'shioaji' fetches from broker.
        simulation: Override simulation flag. If None, reads from system_state.json.
        max_wait_seconds: Fallback timeout.
    """
    # Resolve simulation mode from system_state if not explicitly provided
    if simulation is None:
        simulation = _get_system_simulation_mode()

    if source == "mock":
        return {"source": "mock", "simulation": simulation, "positions": _mock_positions()}

    t0 = time.time()
    try:
        api = _get_api(simulation=simulation)
        positions = api.list_positions(api.stock_account)
        out: List[Dict[str, Any]] = []
        for p in positions:
            out.append(
                {
                    "account": str(getattr(p, "account_id", "")) or "SHIOAJI",
                    "symbol":  getattr(p, "code", None) or getattr(p, "stock_id", None) or "",
                    "name":    getattr(p, "name", None) or "",
                    "qty":     float(getattr(p, "quantity", 0) or 0),
                    "avg_price":  float(getattr(p, "price", 0) or 0),
                    "last_price": None,
                    "market_value": None,
                    "unrealized_pnl": None,
                    "currency": "TWD",
                }
            )

        if (time.time() - t0) > max_wait_seconds:
            return {
                "source": "mock", "simulation": simulation,
                "positions": _mock_positions(), "note": "timeout_fallback"
            }

        return {"source": "shioaji", "simulation": simulation, "positions": out}

    except Exception as e:
        return {
            "source": "mock", "simulation": simulation,
            "positions": _mock_positions(), "note": f"fallback: {e}"
        }
