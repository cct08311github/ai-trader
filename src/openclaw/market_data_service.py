"""market_data_service.py — Market data snapshot fetching.

Extracted from ticker_watcher.py to isolate market data concerns.
Supports Shioaji live data with mock fallback.
"""
from __future__ import annotations

import logging
import random
from typing import Dict, Optional

log = logging.getLogger(__name__)


# Default base prices for mock snapshot generation
BASE_PRICE_DEFAULT: Dict[str, float] = {
    "2330": 900.0, "2317": 200.0, "2454": 1200.0, "2308": 50.0, "2382": 220.0,
    "2881": 28.0, "2882": 48.0, "2886": 38.0, "2412": 120.0, "3008": 380.0,
    "2002": 25.0, "1301": 90.0, "1303": 80.0, "2603": 60.0, "2609": 18.0,
}


class SnapshotUnavailableError(RuntimeError):
    """Raised when a live broker snapshot cannot be used safely."""


class MarketDataService:
    """Fetches market snapshots from Shioaji or generates mock data.

    Parameters
    ----------
    api : optional
        A Shioaji API instance.  If ``None``, always uses mock data.
    base_prices : dict, optional
        Override default base prices for mock generation.
    """

    def __init__(
        self,
        api=None,
        base_prices: Optional[Dict[str, float]] = None,
    ) -> None:
        self._api = api
        self._base_prices = base_prices or dict(BASE_PRICE_DEFAULT)

    @property
    def has_live_api(self) -> bool:
        return self._api is not None

    def get_snapshot(
        self,
        symbol: str,
        *,
        allow_mock_fallback: bool = True,
    ) -> dict:
        """Fetch bid/ask/close/reference/volume for *symbol*.

        Tries Shioaji first; falls back to mock if *allow_mock_fallback*.
        """
        if self._api is not None:
            try:
                contract = self._api.Contracts.Stocks[symbol]
                snaps = self._api.snapshots([contract])
                if not snaps:
                    raise SnapshotUnavailableError("empty snapshot payload")
                s = snaps[0]
                close = float(getattr(s, "close", 0) or 0)
                if close <= 0:
                    raise SnapshotUnavailableError("snapshot close <= 0")
                bid = float(getattr(s, "buy_price", 0) or close * 0.999)
                ask = float(getattr(s, "sell_price", 0) or close * 1.001)
                ref = float(getattr(s, "reference", close) or close)
                vol = int(getattr(s, "volume", 1000) or 1000)
                return {"close": close, "bid": bid, "ask": ask, "reference": ref, "volume": vol}
            except SnapshotUnavailableError:
                if not allow_mock_fallback:
                    raise
            except Exception as e:  # noqa: BLE001
                if not allow_mock_fallback:
                    raise SnapshotUnavailableError(str(e)) from e
                log.warning("Shioaji snapshot [%s]: %s — using mock", symbol, e)

        return self.mock_snapshot(symbol)

    def mock_snapshot(self, symbol: str) -> dict:
        """Generate a mock snapshot around the base price."""
        base = self._base_prices.get(symbol, 100.0)
        close = round(base * (1 + random.uniform(-0.003, 0.003)), 1)
        return {
            "close": close,
            "bid": round(close * 0.999, 1),
            "ask": round(close * 1.001, 1),
            "reference": base,
            "volume": random.randint(500, 5000),
            "source": "mock",
        }

    def update_base_price(self, symbol: str, price: float) -> None:
        """Update the base price for mock generation (e.g. after a fill)."""
        self._base_prices[symbol] = price
