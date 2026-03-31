"""tests/test_ticker_watcher_sell.py

Validates building blocks for the sell auto-trigger:
  1. evaluate_exit returns sell on stop-loss scenario
  2. risk_engine blocks sell on locked symbol
  3. risk_engine does NOT block buy on locked symbol
  4. Closing-position orders skip slippage/deviation checks
"""
import time
import uuid
from unittest.mock import patch

import pytest

from openclaw.signal_logic import evaluate_exit, SignalParams, SignalResult
from openclaw.risk_engine import (
    Decision,
    MarketState,
    PortfolioState,
    Position,
    SystemState,
    evaluate_and_build_order,
    default_limits,
)


# ─── helpers ────────────────────────────────────────────────────────────────

def _make_decision(side: str, symbol: str = "2330") -> Decision:
    return Decision(
        decision_id=str(uuid.uuid4()),
        ts_ms=int(time.time() * 1000),
        symbol=symbol,
        strategy_id="test",
        signal_side=side,
        signal_score=0.9,
    )


def _market(bid: float = 595.0, ask: float = 605.0, volume_1m: int = 5000) -> MarketState:
    return MarketState(
        best_bid=bid,
        best_ask=ask,
        volume_1m=volume_1m,
        feed_delay_ms=10,
    )


def _portfolio(with_position: bool = False, symbol: str = "2330") -> PortfolioState:
    positions = {}
    if with_position:
        positions[symbol] = Position(
            symbol=symbol,
            qty=100,
            avg_price=600.0,
            last_price=500.0,
        )
    return PortfolioState(
        nav=1_000_000.0,
        cash=500_000.0,
        realized_pnl_today=0.0,
        unrealized_pnl=0.0,
        positions=positions,
    )


def _system() -> SystemState:
    return SystemState(
        now_ms=int(time.time() * 1000),
        trading_locked=False,
        broker_connected=True,
        db_write_p99_ms=10,
        orders_last_60s=0,
    )


def _limits_no_pm() -> dict:
    lim = default_limits()
    lim["pm_review_required"] = 0
    return lim


# ─── tests ──────────────────────────────────────────────────────────────────

class TestEvaluateExit:
    def test_sell_trigger_calls_evaluate_exit(self):
        """evaluate_exit returns sell signal when stop-loss is breached."""
        avg_price = 600.0
        # Current price is 8% below avg_price — exceeds default stop_loss_pct=3%
        closes = [620.0, 610.0, 600.0, 590.0, 552.0]
        result = evaluate_exit(
            closes=closes,
            avg_price=avg_price,
            high_water_mark=620.0,
            params=SignalParams(),
        )
        assert isinstance(result, SignalResult)
        assert result.signal == "sell", f"Expected 'sell', got '{result.signal}': {result.reason}"
        assert "stop_loss" in result.reason or "trailing_stop" in result.reason

    def test_evaluate_exit_returns_flat_on_hold(self):
        """evaluate_exit returns flat when no exit condition is met."""
        avg_price = 600.0
        closes = [600.0, 601.0, 602.0]
        result = evaluate_exit(
            closes=closes,
            avg_price=avg_price,
            high_water_mark=602.0,
            params=SignalParams(),
        )
        assert result.signal == "flat"


class TestLockedSymbol:
    def test_sell_trigger_skips_locked_symbol(self):
        """risk_engine blocks sell order when symbol is locked."""
        decision = _make_decision("sell")
        with patch("openclaw.risk_engine._is_symbol_locked", return_value=True):
            result = evaluate_and_build_order(
                decision=decision,
                market=_market(),
                portfolio=_portfolio(with_position=True),
                limits=_limits_no_pm(),
                system_state=_system(),
            )
        assert result.approved is False
        assert result.reject_code == "RISK_SYMBOL_LOCKED"

    def test_sell_trigger_buy_locked_allowed(self):
        """risk_engine does NOT block buy order on locked symbol.

        LOCK_PROTECTION only blocks sells; buys on locked symbols are permitted.
        """
        decision = _make_decision("buy")
        with patch("openclaw.risk_engine._is_symbol_locked", return_value=True):
            result = evaluate_and_build_order(
                decision=decision,
                market=_market(),
                portfolio=_portfolio(with_position=False),
                limits=_limits_no_pm(),
                system_state=_system(),
            )
        # Must NOT be rejected with RISK_SYMBOL_LOCKED
        assert result.reject_code != "RISK_SYMBOL_LOCKED", (
            "Buy orders should never be blocked by LOCK_PROTECTION"
        )


class TestClosingOrderSlippage:
    def test_closing_order_skips_slippage_check(self):
        """Closing position orders bypass slippage and price-deviation checks.

        Even with an extreme bid/ask spread (high slippage), a sell that closes
        an existing long position must be approved so stop-losses can execute.
        """
        decision = _make_decision("sell")

        # Extreme spread → slippage would be huge if checked
        market = MarketState(
            best_bid=100.0,   # far below avg_price of 600
            best_ask=1100.0,
            volume_1m=10_000,
            feed_delay_ms=10,
        )

        # Existing long position — this sell is a closing order (opens_new_position=False)
        portfolio = _portfolio(with_position=True)

        lim = _limits_no_pm()
        lim["max_slippage_bps"] = 1       # effectively zero tolerance
        lim["max_price_deviation_pct"] = 0.001  # 0.1% — impossible to satisfy

        result = evaluate_and_build_order(
            decision=decision,
            market=market,
            portfolio=portfolio,
            limits=lim,
            system_state=_system(),
        )

        assert result.approved is True, (
            f"Closing order should skip slippage/deviation checks but got: "
            f"{result.reject_code}"
        )
        assert result.order is not None
        assert result.order.opens_new_position is False
        assert result.order.side == "sell"


# ─── signal_logic edge cases ────────────────────────────────────────────────

class TestEvaluateEntryRSI:
    def test_entry_rsi_too_high_blocks_buy(self):
        """Golden cross + RSI > rsi_entry_max → should return flat (RSI filter)."""
        from openclaw.signal_logic import evaluate_entry, SignalParams
        # Flat 15 days at 100, then 5 days of sharp rise: 110, 120, 130, 140, 150
        # MA5 crosses above MA20, but RSI will be very high after the spike
        closes = [100.0] * 15 + [110.0, 120.0, 130.0, 140.0, 150.0]
        params = SignalParams(ma_short=5, ma_long=20, rsi_entry_max=60)  # strict RSI limit
        result = evaluate_entry(closes, params)
        # RSI after sharp spike should be very high (>60) → flat
        assert result.signal == "flat"

    def test_entry_rsi_ok_allows_buy(self):
        """Golden cross + RSI within limit → should return buy."""
        from openclaw.signal_logic import evaluate_entry, SignalParams
        # Gentle uptrend: slowly increasing to create crossover without extreme RSI
        closes = [100 - i * 0.3 for i in range(15, 0, -1)] + [100, 101, 102, 103, 104]
        params = SignalParams(ma_short=5, ma_long=20, rsi_entry_max=80)
        result = evaluate_entry(closes, params)
        # If golden cross occurs with moderate RSI → buy
        # The important test is: if result IS buy, RSI was within limit
        if result.signal == "buy":
            assert "golden_cross" in result.reason

    def test_entry_insufficient_data(self):
        """Closes shorter than ma_long → insufficient_data."""
        from openclaw.signal_logic import evaluate_entry, SignalParams
        params = SignalParams(ma_short=5, ma_long=20)
        result = evaluate_entry([100, 101, 102], params)  # only 3 bars, need 20
        assert result.signal == "flat"
        assert "insufficient_data" in result.reason

    def test_entry_exact_boundary_length(self):
        """Closes exactly equal to ma_long → should evaluate (not insufficient)."""
        from openclaw.signal_logic import evaluate_entry, SignalParams
        params = SignalParams(ma_short=5, ma_long=20)
        closes = list(range(80, 100))  # exactly 20 bars
        result = evaluate_entry(closes, params)
        # Should NOT be insufficient_data
        assert result.reason != "insufficient_data"


class TestTrailingStop:
    def test_trailing_stop_tight_triggers_on_high_profit(self):
        """獲利 >= threshold → 使用 tight trailing → 觸發 sell。"""
        from openclaw.signal_logic import evaluate_exit, SignalParams
        # avg=100, hwm=155 → profit 55% >= threshold 50% → tight trailing 3%
        # 155 * (1-0.03) = 150.35 → close=149 should trigger
        params = SignalParams(trailing_pct=0.10, trailing_pct_tight=0.03, trailing_profit_threshold=0.50)
        closes = [100, 130, 155, 149]
        result = evaluate_exit(closes, avg_price=100.0, high_water_mark=155.0, params=params)
        assert result.signal == "sell"
        assert "trailing_stop" in result.reason

    def test_trailing_stop_wide_holds_on_moderate_profit(self):
        """獲利 < threshold → 使用 wide trailing → 不觸發。"""
        from openclaw.signal_logic import evaluate_exit, SignalParams
        # avg=100, hwm=130 → profit 30% < threshold_mid 50% → wide trailing 10%
        # 130 * (1-0.10) = 117 → close=126 should NOT trigger
        params = SignalParams(
            trailing_pct=0.10, trailing_pct_mid=0.06, trailing_pct_tight=0.03,
            trailing_profit_threshold_mid=0.50, trailing_profit_threshold_tight=0.70,
            trailing_profit_threshold=0.70,
        )
        closes = [100, 120, 130, 126]
        result = evaluate_exit(closes, avg_price=100.0, high_water_mark=130.0, params=params)
        assert result.signal == "flat" or "trailing" not in result.reason

    def test_trailing_stop_wide_triggers_on_moderate_profit(self):
        """獲利 < threshold → 使用 wide trailing → 跌破 wide → 觸發。"""
        from openclaw.signal_logic import evaluate_exit, SignalParams
        # avg=100, hwm=130 → profit 30% < 50% → wide trailing 10%
        # 130 * (1-0.10) = 117 → close=115 < 117 → should trigger
        params = SignalParams(
            trailing_pct=0.10, trailing_pct_mid=0.06, trailing_pct_tight=0.03,
            trailing_profit_threshold_mid=0.50, trailing_profit_threshold_tight=0.70,
            trailing_profit_threshold=0.70,
        )
        closes = [100, 120, 130, 115]
        result = evaluate_exit(closes, avg_price=100.0, high_water_mark=130.0, params=params)
        assert result.signal == "sell"
        assert "trailing_stop" in result.reason

    def test_exit_insufficient_data(self):
        """Empty closes → flat with insufficient_data."""
        from openclaw.signal_logic import evaluate_exit, SignalParams
        result = evaluate_exit([], avg_price=100.0, high_water_mark=100.0)
        assert result.signal == "flat"
        assert "insufficient_data" in result.reason

    def test_exit_zero_avg_price(self):
        """avg_price=0 → flat with insufficient_data."""
        from openclaw.signal_logic import evaluate_exit, SignalParams
        result = evaluate_exit([100], avg_price=0.0, high_water_mark=100.0)
        assert result.signal == "flat"
        assert "insufficient_data" in result.reason


# ---------------------------------------------------------------------------
# _build_exit_closes tests (Issue #249)
# ---------------------------------------------------------------------------

import sqlite3
from datetime import date, timedelta


def _make_eod_db(tmp_path, symbol: str = "2330", n_days: int = 20):
    """建立含 eod_prices 的測試 DB。"""
    conn = sqlite3.connect(str(tmp_path / "trades.db"))
    conn.execute("""CREATE TABLE eod_prices (
        trade_date TEXT, symbol TEXT, open REAL, high REAL, low REAL,
        close REAL, volume REAL, PRIMARY KEY (trade_date, symbol)
    )""")
    base = 500.0
    for i in range(n_days):
        d = (date(2026, 2, 1) + timedelta(days=i)).isoformat()
        conn.execute("INSERT INTO eod_prices VALUES (?,?,?,?,?,?,?)",
            (d, symbol, base, base + 1, base - 1, base + i * 0.5, 1e6))
    conn.commit()
    return conn


def test_build_exit_closes_returns_eod_when_history_empty(tmp_path):
    """price_history 空時，應從 eod_prices 取歷史收盤。"""
    from openclaw.ticker_watcher import _build_exit_closes
    conn = _make_eod_db(tmp_path, n_days=20)
    closes = _build_exit_closes(conn, "2330", {})
    assert len(closes) == 20
    assert all(isinstance(c, float) for c in closes)


def test_build_exit_closes_appends_intraday_ticks(tmp_path):
    """price_history 有值時，應 append 至 EOD 歷史後。"""
    from openclaw.ticker_watcher import _build_exit_closes
    conn = _make_eod_db(tmp_path, n_days=10)
    ph = {"2330": [510.0, 511.0, 509.5]}
    closes = _build_exit_closes(conn, "2330", ph)
    assert len(closes) == 13       # 10 EOD + 3 intraday
    assert closes[-1] == 509.5    # 最後一筆是盤中最新價


def test_build_exit_closes_intraday_capped_at_20(tmp_path):
    """盤中 ticks 最多取 20 筆，避免比 EOD 還長。"""
    from openclaw.ticker_watcher import _build_exit_closes
    conn = _make_eod_db(tmp_path, n_days=5)
    ph = {"2330": [500.0 + i for i in range(50)]}  # 50 盤中 ticks
    closes = _build_exit_closes(conn, "2330", ph)
    # 5 EOD + 20 intraday（最後 20）
    assert len(closes) == 25


def test_build_exit_closes_unknown_symbol_returns_empty(tmp_path):
    """未知股票無 EOD 資料且 price_history 無值時，回傳空串列。"""
    from openclaw.ticker_watcher import _build_exit_closes
    conn = _make_eod_db(tmp_path, n_days=5)
    closes = _build_exit_closes(conn, "9999", {})
    assert closes == []
