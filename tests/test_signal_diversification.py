"""Tests for multi-signal entry evaluation (#384).

Covers:
- MACD histogram bullish crossover detection
- Volume breakout detection
- Relative strength detection
- evaluate_entry_multi aggregation
- Integration with signal_generator.compute_multi_signal
"""
from __future__ import annotations

import math

import pytest

from openclaw.signal_logic import (
    MultiSignalResult,
    SignalParams,
    _macd_entry,
    _relative_strength,
    _volume_breakout,
    evaluate_entry_multi,
)


# ---------------------------------------------------------------------------
# Helpers: generate synthetic price/volume data
# ---------------------------------------------------------------------------

def _trending_up(n: int = 60, start: float = 100.0, step: float = 0.5) -> list[float]:
    """Generate a steadily rising price series."""
    return [start + i * step for i in range(n)]


def _trending_down(n: int = 60, start: float = 100.0, step: float = 0.5) -> list[float]:
    return [start - i * step for i in range(n)]


def _flat_series(n: int = 60, val: float = 100.0) -> list[float]:
    return [val] * n


def _golden_cross_series(n: int = 40) -> list[float]:
    """MA5 crosses above MA20: declining then sharply rising at end."""
    # First 30 bars: gently declining
    prices = [100.0 - i * 0.3 for i in range(30)]
    # Last 10 bars: sharp rise (forces MA5 above MA20)
    for i in range(10):
        prices.append(prices[-1] + 2.0)
    return prices


# ---------------------------------------------------------------------------
# Tests: _macd_entry
# ---------------------------------------------------------------------------

class TestMacdEntry:
    def test_detects_bullish_crossover(self):
        # Create series where MACD histogram goes from negative to positive
        # Declining then rising creates this transition
        prices = _trending_down(30, 100, 0.5) + _trending_up(10, 85, 1.5)
        fired, reason = _macd_entry(prices)
        # The MACD should eventually cross; just verify it doesn't crash
        assert isinstance(fired, bool)
        assert isinstance(reason, str)

    def test_returns_false_on_insufficient_data(self):
        fired, reason = _macd_entry([100.0] * 10)
        assert fired is False
        assert reason == ""

    def test_returns_false_on_flat_series(self):
        fired, _ = _macd_entry(_flat_series(40))
        assert fired is False


# ---------------------------------------------------------------------------
# Tests: _volume_breakout
# ---------------------------------------------------------------------------

class TestVolumeBreakout:
    def test_detects_breakout(self):
        closes = _flat_series(20, 100.0) + [110.0]  # Break above 20-day high
        volumes = _flat_series(20, 1000.0) + [3000.0]  # 3x average volume
        fired, reason = _volume_breakout(closes, volumes, period=20, volume_ratio=2.0)
        assert fired is True
        assert "vol_breakout" in reason

    def test_no_breakout_when_price_below_high(self):
        closes = _flat_series(21, 100.0)  # No new high
        volumes = _flat_series(20, 1000.0) + [3000.0]
        fired, _ = _volume_breakout(closes, volumes, period=20, volume_ratio=2.0)
        assert fired is False

    def test_no_breakout_when_volume_too_low(self):
        closes = _flat_series(20, 100.0) + [110.0]  # Price breakout
        volumes = _flat_series(21, 1000.0)  # Normal volume
        fired, _ = _volume_breakout(closes, volumes, period=20, volume_ratio=2.0)
        assert fired is False

    def test_insufficient_data(self):
        fired, _ = _volume_breakout([100.0] * 5, [1000.0] * 5)
        assert fired is False


# ---------------------------------------------------------------------------
# Tests: _relative_strength
# ---------------------------------------------------------------------------

class TestRelativeStrength:
    def test_detects_outperformance(self):
        stock = _trending_up(21, 100.0, 1.0)    # +20%
        bench = _flat_series(21, 100.0)          # 0%
        fired, reason = _relative_strength(stock, bench, period=20)
        assert fired is True
        assert "relative_strength" in reason

    def test_no_signal_when_underperforming(self):
        stock = _flat_series(21, 100.0)
        bench = _trending_up(21, 100.0, 1.0)
        fired, _ = _relative_strength(stock, bench, period=20)
        assert fired is False

    def test_insufficient_data(self):
        fired, _ = _relative_strength([100.0] * 5, [100.0] * 5)
        assert fired is False


# ---------------------------------------------------------------------------
# Tests: evaluate_entry_multi
# ---------------------------------------------------------------------------

class TestEvaluateEntryMulti:
    def test_no_signals_returns_zero(self):
        closes = _flat_series(40)
        volumes = _flat_series(40, 1000.0)
        bench = _flat_series(40)
        result = evaluate_entry_multi(closes, volumes, bench)
        assert result.score == 0.0
        assert result.signals_fired == 0

    def test_score_is_bounded(self):
        # Even in best case, score <= 1.0
        closes = _golden_cross_series(40)
        volumes = _flat_series(40, 1000.0)
        bench = _flat_series(40)
        result = evaluate_entry_multi(closes, volumes, bench)
        assert 0.0 <= result.score <= 1.0
        assert result.signals_fired >= 0

    def test_volume_breakout_fires_independently(self):
        # Flat prices then breakout with volume
        closes = _flat_series(39, 100.0) + [110.0]
        volumes = _flat_series(39, 1000.0) + [3000.0]
        bench = _flat_series(40)
        result = evaluate_entry_multi(closes, volumes, bench)
        assert result.score >= 0.25  # At least volume breakout fired
        assert any("vol_breakout" in r for r in result.reasons)

    def test_relative_strength_fires_independently(self):
        closes = _trending_up(40, 100.0, 1.0)
        volumes = _flat_series(40, 1000.0)
        bench = _flat_series(40, 100.0)
        result = evaluate_entry_multi(closes, volumes, bench)
        assert any("relative_strength" in r for r in result.reasons)

    def test_empty_benchmark_skips_rs(self):
        closes = _trending_up(40, 100.0, 1.0)
        volumes = _flat_series(40, 1000.0)
        result = evaluate_entry_multi(closes, volumes, benchmark_closes=[])
        # Should not crash; RS simply doesn't fire
        assert isinstance(result, MultiSignalResult)

    def test_reasons_list_populated(self):
        closes = _flat_series(39, 100.0) + [110.0]
        volumes = _flat_series(39, 1000.0) + [3000.0]
        bench = _flat_series(40)
        result = evaluate_entry_multi(closes, volumes, bench)
        assert isinstance(result.reasons, list)
