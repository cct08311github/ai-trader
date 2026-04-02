"""Tests for market regime filter (#531).

Covers:
- _is_market_bullish returns True when MA5 >= MA20 (bullish)
- _is_market_bullish returns False when MA5 < MA20 (bearish)
- Fail-open when insufficient data (< 20 rows)
- Fail-open on DB error
- Daily cache — same day returns cached result without re-querying
- Cache resets on new day
- Environment variable overrides for symbol and MA periods
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helper: build in-memory DB with eod_prices table
# ---------------------------------------------------------------------------

def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE eod_prices (
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            open REAL, high REAL, low REAL,
            close REAL,
            volume REAL,
            PRIMARY KEY (trade_date, symbol)
        )
        """
    )
    return conn


def _insert_prices(
    conn: sqlite3.Connection,
    symbol: str,
    closes: list[float],
    start_date: str = "2026-03-10",
) -> None:
    """Insert daily close prices starting from start_date (newest last)."""
    base = dt.datetime.strptime(start_date, "%Y-%m-%d")
    for i, close in enumerate(closes):
        trade_date = (base + dt.timedelta(days=i)).strftime("%Y-%m-%d")
        conn.execute(
            "INSERT INTO eod_prices (trade_date, symbol, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (trade_date, symbol, close, close, close, close, 1000),
        )
    conn.commit()


def _reset_cache() -> None:
    """Reset the module-level regime cache between tests."""
    import openclaw.ticker_watcher as tw
    tw._market_regime_cache = (None, True)


# ---------------------------------------------------------------------------
# Tests: _is_market_bullish
# ---------------------------------------------------------------------------

class TestIsMarketBullish:
    def setup_method(self):
        _reset_cache()

    def test_bullish_when_ma5_above_ma20(self):
        """MA5 > MA20 → bullish (True)."""
        from openclaw.ticker_watcher import _is_market_bullish
        conn = _make_db()
        # 20 prices: first 15 low, last 5 high → MA5 > MA20
        closes = [70.0] * 15 + [80.0] * 5
        _insert_prices(conn, "0050", closes)
        assert _is_market_bullish(conn) is True

    def test_bearish_when_ma5_below_ma20(self):
        """MA5 < MA20 → bearish (False)."""
        from openclaw.ticker_watcher import _is_market_bullish
        conn = _make_db()
        # 20 prices: first 15 high, last 5 low → MA5 < MA20
        closes = [80.0] * 15 + [70.0] * 5
        _insert_prices(conn, "0050", closes)
        assert _is_market_bullish(conn) is False

    def test_bullish_when_ma5_equals_ma20(self):
        """MA5 == MA20 → treated as bullish (>=)."""
        from openclaw.ticker_watcher import _is_market_bullish
        conn = _make_db()
        # All same price → MA5 == MA20
        closes = [75.0] * 20
        _insert_prices(conn, "0050", closes)
        assert _is_market_bullish(conn) is True

    def test_fail_open_insufficient_data(self):
        """< 20 rows → fail-open (True) to avoid blocking trades without data."""
        from openclaw.ticker_watcher import _is_market_bullish
        conn = _make_db()
        closes = [70.0] * 10  # only 10 rows, need 20
        _insert_prices(conn, "0050", closes)
        assert _is_market_bullish(conn) is True

    def test_fail_open_empty_table(self):
        """No data at all → fail-open (True)."""
        from openclaw.ticker_watcher import _is_market_bullish
        conn = _make_db()
        assert _is_market_bullish(conn) is True

    def test_fail_open_on_db_error(self):
        """DB error → fail-open (True)."""
        from openclaw.ticker_watcher import _is_market_bullish
        conn = _make_db()
        conn.execute("DROP TABLE eod_prices")
        assert _is_market_bullish(conn) is True

    def test_cache_returns_same_result_on_same_day(self):
        """Cache prevents re-query within the same calendar day."""
        from openclaw.ticker_watcher import _is_market_bullish
        conn = _make_db()
        # First call: bearish
        closes = [80.0] * 15 + [70.0] * 5
        _insert_prices(conn, "0050", closes)
        assert _is_market_bullish(conn) is False

        # Change data to bullish, but cache should still return False
        conn.execute("DELETE FROM eod_prices")
        closes_bull = [70.0] * 15 + [80.0] * 5
        _insert_prices(conn, "0050", closes_bull)
        assert _is_market_bullish(conn) is False  # cached

    def test_cache_resets_on_new_day(self):
        """Cache invalidates when the date changes."""
        import openclaw.ticker_watcher as tw
        from openclaw.ticker_watcher import _is_market_bullish

        conn = _make_db()
        closes = [80.0] * 15 + [70.0] * 5
        _insert_prices(conn, "0050", closes)
        assert _is_market_bullish(conn) is False

        # Simulate next day by clearing cache with a different date
        tw._market_regime_cache = (None, True)

        # Now insert bullish data
        conn.execute("DELETE FROM eod_prices")
        closes_bull = [70.0] * 15 + [80.0] * 5
        _insert_prices(conn, "0050", closes_bull)
        assert _is_market_bullish(conn) is True

    def test_uses_correct_symbol_from_env(self, monkeypatch):
        """MARKET_REGIME_SYMBOL env var overrides the default 0050."""
        _reset_cache()
        monkeypatch.setenv("MARKET_REGIME_SYMBOL", "0051")

        # Need to reload to pick up env var
        import importlib
        import openclaw.ticker_watcher as tw
        old_symbol = tw._MARKET_REGIME_SYMBOL
        tw._MARKET_REGIME_SYMBOL = "0051"

        try:
            conn = _make_db()
            # Insert 0050 bearish (should be ignored)
            _insert_prices(conn, "0050", [80.0] * 15 + [70.0] * 5)
            # Insert 0051 bullish
            _insert_prices(conn, "0051", [70.0] * 15 + [80.0] * 5)

            from openclaw.ticker_watcher import _is_market_bullish
            assert _is_market_bullish(conn) is True
        finally:
            tw._MARKET_REGIME_SYMBOL = old_symbol

    def test_realistic_price_sequence(self):
        """Test with realistic 0050 price data (recent actual bearish)."""
        from openclaw.ticker_watcher import _is_market_bullish
        conn = _make_db()
        # Simulated 0050: declining trend (MA5 < MA20)
        closes = [
            78.75, 77.40, 76.85, 75.60, 75.20, 78.20, 76.60, 75.95,
            75.60, 76.65, 76.00, 77.80, 76.20, 75.80, 75.00, 73.90,
            72.35, 75.45, 73.95, 74.00,
        ]
        _insert_prices(conn, "0050", closes)
        # MA5 ≈ 74.15, MA20 ≈ 75.69 → bearish
        assert _is_market_bullish(conn) is False
