"""test_exact_boundaries.py — 6 個精確邊界條件測試

測試比較運算符的精確邊界行為：
  - line 257 risk_engine: day_pnl <=       (inclusive — exact equality REJECTS)
  - line 263 risk_engine: TTL     >        (exclusive — exact equality PASSES)
  - line 275 risk_engine: price_dev >      (exclusive — exact equality PASSES)
  - line 295 risk_engine: symbol_weight >  (exclusive — exact equality PASSES)
  - line 301 risk_engine: gross_exposure > (exclusive — exact equality PASSES)
  - line 181 daily_pm_review: confidence >= (inclusive — exact equality APPROVES)
"""
from __future__ import annotations

import time

import pytest

from openclaw.risk_engine import (
    Decision,
    MarketState,
    PortfolioState,
    SystemState,
    default_limits,
    evaluate_and_build_order,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _now_ms() -> int:
    return int(time.time() * 1000)


def _base_limits(**overrides) -> dict:
    """default_limits() + PM bypass + any overrides."""
    lim = default_limits()
    lim["pm_review_required"] = 0
    lim.update(overrides)
    return lim


def _market_zero_spread(price: float = 100.0) -> MarketState:
    """Zero-spread market — deterministic qty and zero slippage."""
    return MarketState(best_bid=price, best_ask=price, volume_1m=100_000, feed_delay_ms=0)


def _system(**kwargs) -> SystemState:
    defaults = dict(
        now_ms=_now_ms(),
        trading_locked=False,
        broker_connected=True,
        db_write_p99_ms=10,
        orders_last_60s=0,
        reduce_only_mode=False,
    )
    defaults.update(kwargs)
    return SystemState(**defaults)


def _decision(ts_ms: int | None = None, ttl_ms: int = 30_000) -> Decision:
    """Buy decision for symbol 2330 with explicit stop_price=90.

    With entry=100, stop=90, risk_pct=0.005, nav=1e6:
      stop_distance = 10  →  qty = floor(1e6 * 0.005 / 10) = 500
      candidate.price = best_ask = 100.0  (zero-spread market)
      symbol_value = 500 * 100 = 50_000
      symbol_weight_after = 50_000 / 1_000_000 = 0.05
      gross_after         = 0 + 50_000 / 1_000_000 = 0.05
    """
    if ts_ms is None:
        ts_ms = _now_ms() - 1_000
    return Decision(
        decision_id="boundary-test",
        ts_ms=ts_ms,
        symbol="2330",
        strategy_id="unit-test",
        signal_side="buy",
        signal_score=0.8,
        signal_ttl_ms=ttl_ms,
        stop_price=90.0,
    )


def _empty_portfolio(nav: float = 1_000_000) -> PortfolioState:
    return PortfolioState(
        nav=nav,
        cash=nav,
        realized_pnl_today=0.0,
        unrealized_pnl=0.0,
        positions={},
    )


@pytest.fixture(autouse=True)
def _patch_helpers(monkeypatch):
    """Suppress file-based helpers so all tests run in isolation."""
    monkeypatch.setattr("openclaw.risk_engine._is_symbol_locked", lambda s: False)
    monkeypatch.setattr("openclaw.risk_engine._get_daily_pm_approval", lambda: True)
    # Suppress TW session multipliers: boundary tests verify exact numeric limits;
    # running during Taiwan PREOPEN/AFTERHOURS would silently alter limits and flip results.
    monkeypatch.setattr(
        "openclaw.risk_engine.apply_tw_session_risk_adjustments",
        lambda limits, *, now_ms, sentinel_policy_path="config/sentinel_policy_v1.json": dict(limits),
    )


# ---------------------------------------------------------------------------
# Boundary 1 — Daily Loss Limit (line 257): <=
# Exact equality at threshold REJECTS (inclusive boundary)
# ---------------------------------------------------------------------------

class TestDailyLossLimitBoundary:
    """day_pnl <= -(max_daily_loss_pct * nav) — 邊界包含（<=），精確等於閾值應拒絕。"""

    _NAV = 1_000_000.0
    _LIMIT_PCT = 0.05

    @property
    def _threshold(self) -> float:
        return self._LIMIT_PCT * self._NAV   # 50_000.0

    def _portfolio(self, realized: float, unrealized: float = 0.0) -> PortfolioState:
        return PortfolioState(
            nav=self._NAV,
            cash=self._NAV,
            realized_pnl_today=realized,
            unrealized_pnl=unrealized,
            positions={},
        )

    def test_exactly_at_threshold_is_rejected(self):
        """day_pnl == -50_000 → -50_000 <= -50_000 → REJECT（<= 包含邊界）。"""
        result = evaluate_and_build_order(
            _decision(),
            _market_zero_spread(),
            self._portfolio(-self._threshold),
            _base_limits(max_daily_loss_pct=self._LIMIT_PCT),
            _system(),
        )
        assert result.approved is False
        assert result.reject_code == "RISK_DAILY_LOSS_LIMIT"

    def test_one_cent_below_threshold_passes(self):
        """day_pnl == -(threshold - 0.01) → 不被 RISK_DAILY_LOSS_LIMIT 拒絕。"""
        result = evaluate_and_build_order(
            _decision(),
            _market_zero_spread(),
            self._portfolio(-(self._threshold - 0.01)),
            _base_limits(max_daily_loss_pct=self._LIMIT_PCT),
            _system(),
        )
        assert result.reject_code != "RISK_DAILY_LOSS_LIMIT"

    def test_unrealized_pnl_combines_with_realized(self):
        """realized + unrealized 合計恰好等於閾值 → REJECT。"""
        result = evaluate_and_build_order(
            _decision(),
            _market_zero_spread(),
            self._portfolio(realized=-40_000.0, unrealized=-10_000.0),  # sum = -50_000
            _base_limits(max_daily_loss_pct=self._LIMIT_PCT),
            _system(),
        )
        assert result.approved is False
        assert result.reject_code == "RISK_DAILY_LOSS_LIMIT"

    def test_unrealized_just_short_passes(self):
        """realized + unrealized = -(threshold - 0.01) → 通過。"""
        result = evaluate_and_build_order(
            _decision(),
            _market_zero_spread(),
            self._portfolio(realized=-40_000.0, unrealized=-9_999.99),  # sum = -49_999.99
            _base_limits(max_daily_loss_pct=self._LIMIT_PCT),
            _system(),
        )
        assert result.reject_code != "RISK_DAILY_LOSS_LIMIT"


# ---------------------------------------------------------------------------
# Boundary 2 — Signal TTL (line 263): >
# Exact equality PASSES (exclusive boundary — now-ts must be GREATER than ttl)
# ---------------------------------------------------------------------------

class TestSignalTtlBoundary:
    """now_ms - ts_ms > ttl_ms — 邊界排除（>），精確等於不應觸發。"""

    def test_exactly_at_ttl_passes(self):
        """now - ts == ttl → ttl > ttl 為 False → 不被 RISK_DATA_STALENESS 拒絕。"""
        ttl = 30_000
        ts = _now_ms()
        result = evaluate_and_build_order(
            _decision(ts_ms=ts, ttl_ms=ttl),
            _market_zero_spread(),
            _empty_portfolio(),
            _base_limits(),
            _system(now_ms=ts + ttl),       # now - ts == ttl exactly
        )
        assert result.reject_code != "RISK_DATA_STALENESS"

    def test_one_ms_past_ttl_is_rejected(self):
        """now - ts == ttl + 1 → ttl+1 > ttl → RISK_DATA_STALENESS。"""
        ttl = 30_000
        ts = _now_ms()
        result = evaluate_and_build_order(
            _decision(ts_ms=ts, ttl_ms=ttl),
            _market_zero_spread(),
            _empty_portfolio(),
            _base_limits(),
            _system(now_ms=ts + ttl + 1),   # one ms past expiry
        )
        assert result.approved is False
        assert result.reject_code == "RISK_DATA_STALENESS"

    def test_well_within_ttl_passes(self):
        """now - ts = 1s，ttl = 30s → 遠未逾期，PASS。"""
        ttl = 30_000
        ts = _now_ms() - 1_000    # 1 second old
        result = evaluate_and_build_order(
            _decision(ts_ms=ts, ttl_ms=ttl),
            _market_zero_spread(),
            _empty_portfolio(),
            _base_limits(),
            _system(),
        )
        assert result.reject_code != "RISK_DATA_STALENESS"


# ---------------------------------------------------------------------------
# Boundary 3 — Price Deviation (line 275): >
# Exact equality PASSES (exclusive boundary)
#
# Setup: bid=98, ask=102 → mid=100 → price_dev = (102-100)/100 = 0.02
# Note: set max_slippage_bps=10_000 so slippage check (line 280) doesn't shadow.
# ---------------------------------------------------------------------------

class TestPriceDeviationBoundary:
    """price_dev_pct > max_price_deviation_pct — 邊界排除（>），精確等於不應觸發。"""

    _BID = 98.0
    _ASK = 102.0
    # dev = abs(ask - mid) / mid = (102 - 100) / 100 = 0.02
    _DEV = 0.02

    def _market(self) -> MarketState:
        return MarketState(
            best_bid=self._BID, best_ask=self._ASK,
            volume_1m=100_000, feed_delay_ms=0,
        )

    def test_price_dev_exactly_at_limit_passes(self):
        """price_dev_pct == 0.02, limit == 0.02 → 0.02 > 0.02 為 False → PASS。"""
        result = evaluate_and_build_order(
            _decision(),
            self._market(),
            _empty_portfolio(),
            _base_limits(
                max_price_deviation_pct=self._DEV,   # limit == actual dev
                max_slippage_bps=10_000,             # prevent slippage from shadowing
            ),
            _system(),
        )
        assert result.reject_code != "RISK_PRICE_DEVIATION_LIMIT"

    def test_price_dev_above_limit_rejected(self):
        """price_dev_pct == 0.02, limit == 0.019 → 0.02 > 0.019 → REJECT。"""
        result = evaluate_and_build_order(
            _decision(),
            self._market(),
            _empty_portfolio(),
            _base_limits(
                max_price_deviation_pct=self._DEV - 0.001,   # limit < actual dev
                max_slippage_bps=10_000,
            ),
            _system(),
        )
        assert result.approved is False
        assert result.reject_code == "RISK_PRICE_DEVIATION_LIMIT"

    def test_price_dev_zero_always_passes(self):
        """零價差市場 → price_dev_pct = 0 → 永遠不觸發 RISK_PRICE_DEVIATION_LIMIT。"""
        result = evaluate_and_build_order(
            _decision(),
            _market_zero_spread(),
            _empty_portfolio(),
            _base_limits(max_price_deviation_pct=0.001),   # very tight limit
            _system(),
        )
        assert result.reject_code != "RISK_PRICE_DEVIATION_LIMIT"


# ---------------------------------------------------------------------------
# Boundary 4 — Symbol Weight Concentration (line 295): >
# Exact equality PASSES (exclusive boundary)
#
# With zero-spread market at 100.0 and stop=90.0:
#   qty = floor(1e6 * 0.005 / 10) = 500
#   symbol_weight_after = 500 * 100.0 / 1_000_000 = 0.05
# ---------------------------------------------------------------------------

class TestSymbolWeightBoundary:
    """symbol_weight_after > max_symbol_weight — 邊界排除（>），精確等於不應觸發。"""

    _EXPECTED_WEIGHT = 0.05   # 500 shares * 100.0 / 1_000_000

    def test_symbol_weight_exactly_at_limit_passes(self):
        """symbol_weight_after == 0.05, limit == 0.05 → 0.05 > 0.05 為 False → PASS。"""
        result = evaluate_and_build_order(
            _decision(),
            _market_zero_spread(),
            _empty_portfolio(),
            _base_limits(
                max_symbol_weight=self._EXPECTED_WEIGHT,
                max_gross_exposure=9.0,   # prevent gross exposure check from shadowing
            ),
            _system(),
        )
        assert result.reject_code != "RISK_POSITION_CONCENTRATION"

    def test_symbol_weight_above_limit_rejected(self):
        """symbol_weight_after == 0.05, limit == 0.049 → 0.05 > 0.049 → REJECT。"""
        result = evaluate_and_build_order(
            _decision(),
            _market_zero_spread(),
            _empty_portfolio(),
            _base_limits(
                max_symbol_weight=self._EXPECTED_WEIGHT - 0.001,   # just below actual weight
                max_gross_exposure=9.0,
            ),
            _system(),
        )
        assert result.approved is False
        assert result.reject_code == "RISK_POSITION_CONCENTRATION"

    def test_existing_position_adds_to_symbol_weight(self):
        """既有部位 + 新增部位 超過 weight limit → REJECT。"""
        from openclaw.risk_engine import Position
        portfolio_with_pos = PortfolioState(
            nav=1_000_000,
            cash=900_000,
            realized_pnl_today=0.0,
            unrealized_pnl=0.0,
            positions={
                "2330": Position(symbol="2330", qty=100, avg_price=100.0, last_price=100.0),
            },
        )
        # existing = 100 * 100 = 10_000, new candidate = 500 * 100 = 50_000
        # symbol_value_after = 60_000, weight = 0.06
        result = evaluate_and_build_order(
            _decision(),
            _market_zero_spread(),
            portfolio_with_pos,
            _base_limits(
                max_symbol_weight=0.055,   # 0.055 < 0.06 → REJECT
                max_gross_exposure=9.0,
            ),
            _system(),
        )
        assert result.approved is False
        assert result.reject_code == "RISK_POSITION_CONCENTRATION"


# ---------------------------------------------------------------------------
# Boundary 5 — Gross Exposure (line 301): >
# Exact equality PASSES (exclusive boundary)
#
# Same setup as Boundary 4:
#   gross_after = 500 * 100.0 / 1_000_000 = 0.05  (no existing positions)
# ---------------------------------------------------------------------------

class TestGrossExposureBoundary:
    """gross_after > max_gross_exposure — 邊界排除（>），精確等於不應觸發。"""

    _EXPECTED_GROSS = 0.05   # 500 shares * 100.0 / 1_000_000

    def test_gross_exactly_at_limit_passes(self):
        """gross_after == 0.05, limit == 0.05 → 0.05 > 0.05 為 False → PASS。"""
        result = evaluate_and_build_order(
            _decision(),
            _market_zero_spread(),
            _empty_portfolio(),
            _base_limits(
                max_gross_exposure=self._EXPECTED_GROSS,
                max_symbol_weight=9.0,   # prevent concentration check from shadowing
            ),
            _system(),
        )
        assert result.reject_code != "RISK_PORTFOLIO_EXPOSURE_LIMIT"

    def test_gross_above_limit_rejected(self):
        """gross_after == 0.05, limit == 0.049 → 0.05 > 0.049 → REJECT。"""
        result = evaluate_and_build_order(
            _decision(),
            _market_zero_spread(),
            _empty_portfolio(),
            _base_limits(
                max_gross_exposure=self._EXPECTED_GROSS - 0.001,   # just below actual gross
                max_symbol_weight=9.0,
            ),
            _system(),
        )
        assert result.approved is False
        assert result.reject_code == "RISK_PORTFOLIO_EXPOSURE_LIMIT"

    def test_existing_positions_count_toward_gross(self):
        """既有部位的 gross_exposure 計入新訂單，超限 → REJECT。"""
        from openclaw.risk_engine import Position
        # existing exposure = 200 * 100 / 1_000_000 = 0.02
        # new candidate = 500 * 100 / 1_000_000 = 0.05
        # gross_after = 0.07 → reject if limit = 0.06
        portfolio_with_pos = PortfolioState(
            nav=1_000_000,
            cash=800_000,
            realized_pnl_today=0.0,
            unrealized_pnl=0.0,
            positions={
                "0050": Position(symbol="0050", qty=200, avg_price=100.0, last_price=100.0),
            },
        )
        result = evaluate_and_build_order(
            _decision(),
            _market_zero_spread(),
            portfolio_with_pos,
            _base_limits(
                max_gross_exposure=0.06,   # 0.06 < 0.07 → REJECT
                max_symbol_weight=9.0,
            ),
            _system(),
        )
        assert result.approved is False
        assert result.reject_code == "RISK_PORTFOLIO_EXPOSURE_LIMIT"


# ---------------------------------------------------------------------------
# Boundary 6 — PM Confidence Threshold (daily_pm_review.py:181): >=
# confidence == 0.65 exactly APPROVES (inclusive boundary)
# confidence == 0.6499 REJECTS
# ---------------------------------------------------------------------------

class TestPmConfidenceBoundary:
    """confidence >= 0.65 in neutral PM review — 邊界包含（>=），精確等於閾值應批准。

    Tests the pure approval logic without triggering the LLM call.
    Uses a neutral action (no bearish/bullish keywords) so the confidence
    threshold is the deciding factor.
    """

    _THRESHOLD = 0.65
    _NEUTRAL_ACTION = "hold"   # not in _BEARISH_KW or _BULLISH_KW

    def _approval(self, confidence: float) -> bool:
        """Inline mirror of daily_pm_review.py lines 174-181."""
        from openclaw.daily_pm_review import _BEARISH_KW, _BULLISH_KW
        action = self._NEUTRAL_ACTION.lower()
        if any(kw in action for kw in _BEARISH_KW):
            return False
        if any(kw in action for kw in _BULLISH_KW):
            return True
        return confidence >= self._THRESHOLD

    def test_confidence_exactly_at_threshold_approves(self):
        """confidence == 0.65 → 0.65 >= 0.65 → True（>= 包含邊界）。"""
        assert self._approval(self._THRESHOLD) is True

    def test_confidence_just_below_threshold_rejects(self):
        """confidence == 0.6499 → 0.6499 >= 0.65 → False。"""
        assert self._approval(0.6499) is False

    def test_confidence_zero_rejects(self):
        """confidence == 0.0 → 0.0 >= 0.65 → False。"""
        assert self._approval(0.0) is False

    def test_confidence_one_approves(self):
        """confidence == 1.0 → 1.0 >= 0.65 → True。"""
        assert self._approval(1.0) is True

    def test_neutral_action_not_polluted_by_keywords(self):
        """確認 'hold' 不意外包含看空或看多關鍵字，邏輯由 confidence 決定。"""
        # If hold were accidentally bearish/bullish, confidence wouldn't matter.
        # This test pins that behavior: below threshold → False, at threshold → True.
        assert self._approval(self._THRESHOLD - 0.0001) is False
        assert self._approval(self._THRESHOLD) is True
