from __future__ import annotations

import os
import time
from functools import lru_cache
from typing import Any, Dict, List, Literal, Optional


def _mock_positions() -> List[Dict[str, Any]]:
    # Keep schema stable for frontend.
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
            "chip_health_score": 8,  # 0-10 score for chip health
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


@lru_cache(maxsize=1)
def _get_api(simulation: bool = True):
    """Create (and cache) Shioaji API instance.

    NOTE: caching avoids repeated logins. The first login can still be slow.
    """
    import shioaji as sj  # type: ignore

    api = sj.Shioaji(simulation=simulation)
    api_key = os.environ.get("SHIOAJI_API_KEY")
    secret_key = os.environ.get("SHIOAJI_SECRET_KEY")

    if not api_key or not secret_key:
        raise RuntimeError("Missing SHIOAJI_API_KEY / SHIOAJI_SECRET_KEY env vars")

    api.login(api_key=api_key, secret_key=secret_key)
    return api


def get_positions(
    *,
    source: Literal["mock", "shioaji"] = "mock",
    simulation: bool = True,
    max_wait_seconds: float = 2.0,
) -> Dict[str, Any]:
    """Fetch positions.

    Default returns mock data for speed/reliability.
    """

    if source == "mock":
        return {"source": "mock", "simulation": simulation, "positions": _mock_positions()}

    # Best-effort real fetch; fall back to mock if anything goes wrong or too slow.
    t0 = time.time()
    try:
        api = _get_api(simulation=simulation)
        # Shioaji has a few ways to fetch positions depending on account type.
        # We'll try the most common 'list_positions' API.
        positions = api.list_positions(api.stock_account)
        out: List[Dict[str, Any]] = []
        for p in positions:
            out.append(
                {
                    "account": str(getattr(p, "account_id", "")) or "SHIOAJI",
                    "symbol": getattr(p, "code", None) or getattr(p, "stock_id", None) or "",
                    "name": getattr(p, "name", None) or "",
                    "qty": float(getattr(p, "quantity", 0) or 0),
                    "avg_price": float(getattr(p, "price", 0) or 0),
                    "last_price": None,
                    "market_value": None,
                    "unrealized_pnl": None,
                    "currency": "TWD",
                }
            )

        if (time.time() - t0) > max_wait_seconds:
            return {"source": "mock", "simulation": simulation, "positions": _mock_positions(), "note": "timeout_fallback"}

        return {"source": "shioaji", "simulation": simulation, "positions": out}
    except Exception as e:
        return {"source": "mock", "simulation": simulation, "positions": _mock_positions(), "note": f"fallback: {e}"}
