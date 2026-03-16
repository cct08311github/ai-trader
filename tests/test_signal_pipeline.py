"""tests/test_signal_pipeline.py — Unit tests for SignalPipeline facade.

Tests verify:
1. PipelineSignalResult creation and field values
2. SignalPipeline delegates compute_signals to signal_generator correctly
3. SignalPipeline enriches results with lm_signal_cache when available
4. get_cached_or_compute returns LLM cache on hit and falls back to technical on miss
5. Cache errors are handled gracefully (non-fatal)
"""
from __future__ import annotations

import sqlite3
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from openclaw.signal_pipeline import PipelineSignalResult, SignalPipeline


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_conn() -> sqlite3.Connection:
    """In-memory DB with minimal schema for tests that need a real connection."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS lm_signal_cache (
        cache_id TEXT PRIMARY KEY, symbol TEXT, score REAL NOT NULL,
        source TEXT NOT NULL, direction TEXT, raw_json TEXT,
        created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS eod_prices (
        trade_date TEXT, symbol TEXT, open REAL, high REAL,
        low REAL, close REAL, volume INTEGER
    )""")
    conn.commit()
    return conn


def _mock_generator(signal: str = "flat"):
    """Return a mock object that simulates openclaw.signal_generator."""
    gen = MagicMock()
    gen.compute_signal.return_value = signal
    gen.fetch_candles.return_value = []
    return gen


def _mock_cache(result: Optional[Dict[str, Any]] = None):
    """Return a mock object that simulates openclaw.lm_signal_cache."""
    cache = MagicMock()
    cache.read_cache_with_fallback.return_value = result
    return cache


# ---------------------------------------------------------------------------
# 1. PipelineSignalResult
# ---------------------------------------------------------------------------

class TestPipelineSignalResult:
    def test_from_technical_buy_no_llm(self):
        result = PipelineSignalResult.from_technical("2330", "buy")
        assert result.symbol == "2330"
        assert result.direction == "buy"
        assert result.strength == 1.0
        assert result.signals["technical"] == "buy"
        assert result.source == "technical"

    def test_from_technical_sell_no_llm(self):
        result = PipelineSignalResult.from_technical("2317", "sell")
        assert result.direction == "sell"
        assert result.strength == 0.0
        assert result.source == "technical"

    def test_from_technical_flat_no_llm(self):
        result = PipelineSignalResult.from_technical("2330", "flat")
        assert result.direction == "flat"
        assert result.strength == 0.5
        assert result.source == "technical"

    def test_from_technical_with_llm_cache(self):
        llm = {"score": 0.8, "direction": "bull", "source": "strategy_committee"}
        result = PipelineSignalResult.from_technical("2330", "buy", llm_cache=llm)
        assert result.direction == "buy"
        assert result.signals["llm_score"] == 0.8
        assert result.signals["llm_direction"] == "bull"
        assert result.signals["llm_source"] == "strategy_committee"
        assert result.source == "combined"

    def test_direct_construction(self):
        r = PipelineSignalResult(
            symbol="1301",
            direction="flat",
            strength=0.5,
            signals={"technical": "flat"},
            source="technical",
        )
        assert r.symbol == "1301"
        assert r.strength == 0.5


# ---------------------------------------------------------------------------
# 2. SignalPipeline.compute_signals — delegates to generator
# ---------------------------------------------------------------------------

class TestSignalPipelineComputeSignals:
    def test_delegates_to_generator_buy(self):
        gen = _mock_generator("buy")
        cache = _mock_cache(None)
        pipeline = SignalPipeline(signal_generator=gen, cache=cache)
        conn = _make_conn()

        result = pipeline.compute_signals(conn, "2330", None, None)

        gen.compute_signal.assert_called_once_with(conn, "2330", None, None)
        assert result.direction == "buy"
        assert result.source == "technical"

    def test_delegates_to_generator_sell(self):
        gen = _mock_generator("sell")
        cache = _mock_cache(None)
        pipeline = SignalPipeline(signal_generator=gen, cache=cache)
        conn = _make_conn()

        result = pipeline.compute_signals(conn, "2454", 1200.0, 1250.0)

        gen.compute_signal.assert_called_once_with(conn, "2454", 1200.0, 1250.0)
        assert result.direction == "sell"

    def test_trailing_pct_forwarded(self):
        gen = _mock_generator("flat")
        cache = _mock_cache(None)
        pipeline = SignalPipeline(signal_generator=gen, cache=cache)
        conn = _make_conn()

        pipeline.compute_signals(conn, "2330", 900.0, 950.0, trailing_pct=0.03)

        gen.compute_signal.assert_called_once_with(conn, "2330", 900.0, 950.0, trailing_pct=0.03)

    def test_no_trailing_pct_not_forwarded(self):
        """When trailing_pct is None, it should NOT be passed as kwarg."""
        gen = _mock_generator("flat")
        cache = _mock_cache(None)
        pipeline = SignalPipeline(signal_generator=gen, cache=cache)
        conn = _make_conn()

        pipeline.compute_signals(conn, "2330", None, None)

        # trailing_pct should NOT appear in the call kwargs
        call_kwargs = gen.compute_signal.call_args[1]
        assert "trailing_pct" not in call_kwargs


# ---------------------------------------------------------------------------
# 3. SignalPipeline cache integration
# ---------------------------------------------------------------------------

class TestSignalPipelineCacheIntegration:
    def test_llm_cache_hit_enriches_result(self):
        gen = _mock_generator("buy")
        llm_data = {"score": 0.75, "direction": "bull", "source": "strategy_committee"}
        cache = _mock_cache(llm_data)
        pipeline = SignalPipeline(signal_generator=gen, cache=cache)
        conn = _make_conn()

        result = pipeline.compute_signals(conn, "2330", None, None)

        assert result.direction == "buy"
        assert result.source == "combined"
        assert result.signals["llm_score"] == 0.75
        assert result.signals["llm_direction"] == "bull"

    def test_llm_cache_miss_yields_technical_source(self):
        gen = _mock_generator("flat")
        cache = _mock_cache(None)
        pipeline = SignalPipeline(signal_generator=gen, cache=cache)
        conn = _make_conn()

        result = pipeline.compute_signals(conn, "2330", None, None)

        assert result.source == "technical"
        assert "llm_score" not in result.signals

    def test_cache_error_is_non_fatal(self):
        gen = _mock_generator("buy")
        cache = MagicMock()
        cache.read_cache_with_fallback.side_effect = Exception("DB error")
        pipeline = SignalPipeline(signal_generator=gen, cache=cache)
        conn = _make_conn()

        # Should not raise, should still return a result
        result = pipeline.compute_signals(conn, "2330", None, None)
        assert result.direction == "buy"
        assert result.source == "technical"


# ---------------------------------------------------------------------------
# 4. SignalPipeline.get_cached_or_compute
# ---------------------------------------------------------------------------

class TestGetCachedOrCompute:
    def test_returns_llm_direction_on_cache_hit_bull(self):
        gen = _mock_generator("flat")  # technical says flat
        llm_data = {"score": 0.9, "direction": "bull", "source": "strategy_committee"}
        cache = _mock_cache(llm_data)
        pipeline = SignalPipeline(signal_generator=gen, cache=cache)
        conn = _make_conn()

        result = pipeline.get_cached_or_compute(conn, "2330")

        assert result.direction == "buy"
        assert result.source == "llm"
        # Should NOT have called compute_signals (no generator call)
        gen.compute_signal.assert_not_called()

    def test_returns_llm_direction_on_cache_hit_bear(self):
        llm_data = {"score": 0.1, "direction": "bear", "source": "pm_review"}
        cache = _mock_cache(llm_data)
        gen = _mock_generator("flat")
        pipeline = SignalPipeline(signal_generator=gen, cache=cache)
        conn = _make_conn()

        result = pipeline.get_cached_or_compute(conn, "2317")

        assert result.direction == "sell"
        assert result.source == "llm"
        assert result.signals["llm_direction"] == "bear"

    def test_returns_llm_direction_on_cache_hit_neutral(self):
        llm_data = {"score": 0.5, "direction": "neutral", "source": "pm_review"}
        cache = _mock_cache(llm_data)
        gen = _mock_generator("buy")
        pipeline = SignalPipeline(signal_generator=gen, cache=cache)
        conn = _make_conn()

        result = pipeline.get_cached_or_compute(conn, "2330")

        assert result.direction == "flat"
        assert result.source == "llm"

    def test_falls_back_to_technical_on_cache_miss(self):
        gen = _mock_generator("buy")
        cache = _mock_cache(None)
        pipeline = SignalPipeline(signal_generator=gen, cache=cache)
        conn = _make_conn()

        result = pipeline.get_cached_or_compute(conn, "2330", position_avg_price=None,
                                                high_water_mark=None)

        assert result.direction == "buy"
        assert result.source == "technical"
        gen.compute_signal.assert_called_once()

    def test_cache_error_falls_back_to_technical(self):
        gen = _mock_generator("sell")
        cache = MagicMock()
        cache.read_cache_with_fallback.side_effect = RuntimeError("cache down")
        pipeline = SignalPipeline(signal_generator=gen, cache=cache)
        conn = _make_conn()

        result = pipeline.get_cached_or_compute(conn, "2330", position_avg_price=900.0,
                                                high_water_mark=950.0)

        assert result.direction == "sell"
        assert result.source == "technical"


# ---------------------------------------------------------------------------
# 5. Default dependency injection (real modules loaded)
# ---------------------------------------------------------------------------

class TestDefaultDependencyLoading:
    def test_default_init_loads_real_modules(self):
        """Ensure SignalPipeline can be instantiated without injected deps."""
        pipeline = SignalPipeline()
        # Should have loaded real modules
        import openclaw.signal_generator as sg
        import openclaw.lm_signal_cache as lc
        assert pipeline._generator is sg
        assert pipeline._cache is lc
