"""Tests for regime detection enhancement (#390).

Covers:
- _benchmark_ma_direction detects up/down/flat
- _foreign_investor_streak counts consecutive days
- classify_market_regime benchmark override
- classify_market_regime foreign investor confirmation
"""
from __future__ import annotations

import pytest

from openclaw.market_regime import (
    MarketRegime,
    _benchmark_ma_direction,
    _foreign_investor_streak,
    classify_market_regime,
)


def _trending_up(n: int = 60, start: float = 100.0, step: float = 0.5) -> list[float]:
    return [start + i * step for i in range(n)]


def _trending_down(n: int = 60, start: float = 130.0, step: float = 0.5) -> list[float]:
    return [start - i * step for i in range(n)]


def _flat(n: int = 60, val: float = 100.0) -> list[float]:
    return [val] * n


class TestBenchmarkMaDirection:
    def test_up(self):
        prices = _trending_up(25, 100, 1.0)
        assert _benchmark_ma_direction(prices) == "up"

    def test_down(self):
        prices = _trending_down(25, 130, 1.0)
        assert _benchmark_ma_direction(prices) == "down"

    def test_flat(self):
        prices = _flat(25, 100.0)
        assert _benchmark_ma_direction(prices) == "flat"

    def test_insufficient_data(self):
        assert _benchmark_ma_direction([100.0] * 5) == "flat"


class TestForeignInvestorStreak:
    def test_consecutive_buy(self):
        assert _foreign_investor_streak([100, 200, 50, 300, 150]) == 5

    def test_consecutive_sell(self):
        assert _foreign_investor_streak([-100, -200, -50]) == -3

    def test_mixed_ending_buy(self):
        assert _foreign_investor_streak([-100, -200, 50, 100]) == 2

    def test_mixed_ending_sell(self):
        assert _foreign_investor_streak([100, 200, -50, -100]) == -2

    def test_empty(self):
        assert _foreign_investor_streak([]) == 0

    def test_single_day(self):
        assert _foreign_investor_streak([100]) == 1
        assert _foreign_investor_streak([-100]) == -1


class TestRegimeBenchmarkOverride:
    def test_bull_downgraded_when_benchmark_falling(self):
        """Stock trending up but benchmark (0050) falling → RANGE."""
        stock_prices = _trending_up(60, 100, 1.0)
        volumes = _flat(60, 10000)
        benchmark = _trending_down(60, 130, 0.5)

        result = classify_market_regime(
            stock_prices, volumes, benchmark_prices=benchmark
        )
        # Should be downgraded from BULL to RANGE
        assert result.regime in (MarketRegime.RANGE, MarketRegime.BEAR)

    def test_bear_upgraded_when_benchmark_rising(self):
        """Stock trending down but benchmark rising → RANGE."""
        stock_prices = _trending_down(60, 130, 1.0)
        volumes = _flat(60, 10000)
        benchmark = _trending_up(60, 100, 0.5)

        result = classify_market_regime(
            stock_prices, volumes, benchmark_prices=benchmark
        )
        assert result.regime in (MarketRegime.RANGE, MarketRegime.BULL)

    def test_no_override_when_aligned(self):
        """Stock and benchmark both trending up → stays BULL."""
        stock_prices = _trending_up(60, 100, 1.0)
        volumes = _flat(60, 10000)
        benchmark = _trending_up(60, 100, 0.3)

        result = classify_market_regime(
            stock_prices, volumes, benchmark_prices=benchmark
        )
        assert result.regime == MarketRegime.BULL

    def test_no_override_without_benchmark(self):
        """Without benchmark, original logic applies."""
        stock_prices = _trending_up(60, 100, 1.0)
        volumes = _flat(60, 10000)

        result = classify_market_regime(stock_prices, volumes)
        assert result.regime == MarketRegime.BULL


class TestRegimeForeignInvestor:
    def test_bear_upgraded_with_strong_buying(self):
        """Bear regime + 5 consecutive foreign buy days → RANGE."""
        stock_prices = _trending_down(60, 130, 1.0)
        volumes = _flat(60, 10000)
        fi_days = [100, 200, 300, 400, 500]  # 5 consecutive buy days

        result = classify_market_regime(
            stock_prices, volumes, foreign_net_buy_days=fi_days
        )
        assert result.regime == MarketRegime.RANGE
        assert result.features.get("regime_fi_upgrade") == 1.0

    def test_bull_downgraded_with_strong_selling(self):
        """Bull regime + 5 consecutive foreign sell days → RANGE."""
        stock_prices = _trending_up(60, 100, 1.0)
        volumes = _flat(60, 10000)
        fi_days = [-100, -200, -300, -400, -500]

        result = classify_market_regime(
            stock_prices, volumes, foreign_net_buy_days=fi_days
        )
        assert result.regime == MarketRegime.RANGE
        assert result.features.get("regime_fi_downgrade") == 1.0

    def test_no_change_with_weak_streak(self):
        """3 consecutive sell days (< 5) → no override."""
        stock_prices = _trending_up(60, 100, 1.0)
        volumes = _flat(60, 10000)
        fi_days = [100, -100, -200, -300]  # only 3 sell days

        result = classify_market_regime(
            stock_prices, volumes, foreign_net_buy_days=fi_days
        )
        assert result.regime == MarketRegime.BULL  # Not downgraded
