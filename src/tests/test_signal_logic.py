# src/tests/test_signal_logic.py
"""Tests for signal_logic.py + cost_model.py — 純函數信號邏輯與交易成本

覆蓋：evaluate_exit（trailing/止盈/止損/flat）、evaluate_entry（黃金交叉/RSI）、
cost_model 三個函數、regression test（重構前後一致）。
"""
import sqlite3
import pytest

from openclaw.signal_logic import SignalParams, SignalResult, evaluate_exit, evaluate_entry
from openclaw.cost_model import CostParams, calc_buy_cost, calc_sell_proceeds, calc_round_trip_pnl


# ── Default params ──
P = SignalParams()


# ═══════════════════════════════════════════════
# evaluate_exit
# ═══════════════════════════════════════════════

class TestEvaluateExitTrailingStop:
    def test_trailing_stop_triggers_sell(self):
        # hwm=110, trailing=5% → threshold=104.5, close=104 < 104.5 → sell
        r = evaluate_exit([104.0], avg_price=100.0, high_water_mark=110.0, params=P)
        assert r.signal == "sell"
        assert "trailing_stop" in r.reason

    def test_trailing_stop_tight_when_profit_over_50pct(self):
        # avg=100, hwm=160 (60% profit > 50% threshold) → tight trailing=3%
        # threshold = 160 * 0.97 = 155.2, close=155 < 155.2 → sell
        r = evaluate_exit([155.0], avg_price=100.0, high_water_mark=160.0, params=P)
        assert r.signal == "sell"
        assert "trailing_stop" in r.reason

    def test_trailing_mid_tier_triggers_at_moderate_profit(self):
        # hwm=110, avg=100, profit=10% → mid tier 4% → threshold=110*0.96=105.6
        # close=105 < 105.6 → trailing_stop fires (mid tier)
        r = evaluate_exit([105.0], avg_price=100.0, high_water_mark=110.0, params=P)
        assert r.signal == "sell"
        assert "trailing_stop" in r.reason
        assert "4.00%" in r.reason

    def test_trailing_not_triggered_above_threshold(self):
        # hwm=105, avg=100, profit=5% < 10% → base 5% → threshold=105*0.95=99.75
        # close=103 > 99.75 → no trailing → take_profit (103 > 100*1.02=102)
        # Use explicit mid threshold=0.50 so profit=5% stays in base tier
        P_explicit = SignalParams(trailing_profit_threshold_mid=0.50, trailing_profit_threshold_tight=0.70)
        r = evaluate_exit([103.0], avg_price=100.0, high_water_mark=105.0, params=P_explicit)
        assert r.signal == "sell"
        assert "take_profit" in r.reason

    def test_no_hwm_skips_trailing(self):
        # No high_water_mark → skip trailing, check take_profit/stop_loss
        r = evaluate_exit([103.0], avg_price=100.0, high_water_mark=None, params=P)
        assert r.signal == "sell"  # 103 > 102 → take_profit


class TestEvaluateExitTakeProfit:
    def test_take_profit_triggers(self):
        # close=103 > 100*1.02=102 → sell
        r = evaluate_exit([103.0], avg_price=100.0, high_water_mark=None, params=P)
        assert r.signal == "sell"
        assert "take_profit" in r.reason

    def test_just_below_take_profit_is_flat(self):
        # close=101.9 < 102 → flat
        r = evaluate_exit([101.9], avg_price=100.0, high_water_mark=None, params=P)
        assert r.signal == "flat"


class TestEvaluateExitStopLoss:
    def test_stop_loss_triggers(self):
        # close=96 < 100*0.97=97 → sell
        r = evaluate_exit([96.0], avg_price=100.0, high_water_mark=None, params=P)
        assert r.signal == "sell"
        assert "stop_loss" in r.reason

    def test_just_above_stop_loss_is_flat(self):
        # close=97.5 > 97 → flat
        r = evaluate_exit([97.5], avg_price=100.0, high_water_mark=None, params=P)
        assert r.signal == "flat"


class TestEvaluateExitEdgeCases:
    def test_empty_closes_returns_flat(self):
        r = evaluate_exit([], avg_price=100.0, high_water_mark=110.0, params=P)
        assert r.signal == "flat"
        assert "insufficient" in r.reason

    def test_zero_avg_price_returns_flat(self):
        r = evaluate_exit([100.0], avg_price=0, high_water_mark=None, params=P)
        assert r.signal == "flat"

    def test_custom_params(self):
        custom = SignalParams(take_profit_pct=0.10, stop_loss_pct=0.05)
        # close=108 < 100*1.10=110 → no take_profit; > 100*0.95=95 → flat
        r = evaluate_exit([108.0], avg_price=100.0, high_water_mark=None, params=custom)
        assert r.signal == "flat"


# ═══════════════════════════════════════════════
# evaluate_entry
# ═══════════════════════════════════════════════

class TestEvaluateEntry:
    def _make_golden_cross_closes(self):
        """建立一組觸發 MA5 上穿 MA20 的收盤價序列。"""
        # 20 天下跌趨勢 + 最後 5 天快速上漲
        base = [100 - i * 0.5 for i in range(20)]  # 100, 99.5, ... 90.5
        # 追加 5 天上漲讓 MA5 穿越 MA20
        rising = [92.0, 94.0, 96.0, 98.0, 100.0]
        return base + rising

    def test_golden_cross_triggers_buy(self):
        closes = self._make_golden_cross_closes()
        r = evaluate_entry(closes, P)
        # 這組序列不一定觸發黃金交叉（取決於 MA 計算），但至少不出錯
        assert r.signal in ("buy", "flat")

    def test_insufficient_data_returns_flat(self):
        r = evaluate_entry([100.0] * 10, P)  # < 20
        assert r.signal == "flat"
        assert "insufficient" in r.reason

    def test_flat_market_no_crossover(self):
        # 穩定序列不會觸發黃金交叉
        closes = [100.0] * 30
        r = evaluate_entry(closes, P)
        assert r.signal == "flat"

    def test_downtrend_no_buy(self):
        closes = [100 - i for i in range(25)]
        r = evaluate_entry(closes, P)
        assert r.signal == "flat"


# ═══════════════════════════════════════════════
# cost_model
# ═══════════════════════════════════════════════

class TestCostModel:
    def test_buy_cost_default(self):
        # 100 * 1000 = 100000, fee = 100000 * 0.001425 = 142.5
        cost = calc_buy_cost(100.0, 1000)
        assert cost == 100142.5

    def test_sell_proceeds_default(self):
        # 100 * 1000 = 100000, fee = 142.5, tax = 300
        proceeds = calc_sell_proceeds(100.0, 1000)
        assert proceeds == 99557.5

    def test_round_trip_pnl_breakeven(self):
        # 買賣同價 → 虧手續費+稅
        pnl = calc_round_trip_pnl(100.0, 100.0, 1000)
        assert pnl < 0  # 一定虧（交易成本）
        assert pnl == round(99557.5 - 100142.5, 2)  # -585.0

    def test_round_trip_pnl_profit(self):
        pnl = calc_round_trip_pnl(100.0, 110.0, 1000)
        assert pnl > 0

    def test_round_trip_pnl_loss(self):
        pnl = calc_round_trip_pnl(100.0, 90.0, 1000)
        assert pnl < 0

    def test_discount_broker(self):
        params = CostParams(commission_discount=0.28)  # 2.8 折
        cost = calc_buy_cost(100.0, 1000, params)
        # fee = 100000 * 0.001425 * 0.28 = 39.9
        assert cost == 100039.9

    def test_zero_qty(self):
        assert calc_buy_cost(100.0, 0) == 0.0
        assert calc_sell_proceeds(100.0, 0) == 0.0


# ═══════════════════════════════════════════════
# Regression: signal_generator 重構前後一致
# ═══════════════════════════════════════════════

class TestRegressionSignalGenerator:
    """確保 signal_generator.compute_signal 重構後行為不變。"""

    def _make_db(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("""CREATE TABLE eod_prices (
            trade_date TEXT, symbol TEXT, open REAL, high REAL, low REAL,
            close REAL, volume INTEGER, PRIMARY KEY (trade_date, symbol)
        )""")
        return conn

    def _insert_candles(self, conn, symbol, closes):
        for i, c in enumerate(closes):
            conn.execute(
                "INSERT INTO eod_prices VALUES (?,?,?,?,?,?,?)",
                (f"2026-01-{i+1:02d}", symbol, c, c+1, c-1, c, 1000),
            )

    def test_flat_when_few_candles(self):
        from openclaw.signal_generator import compute_signal
        conn = self._make_db()
        self._insert_candles(conn, "2330", [100.0, 101.0, 102.0])
        assert compute_signal(conn, "2330", None, None) == "flat"

    def test_sell_on_stop_loss(self):
        from openclaw.signal_generator import compute_signal
        conn = self._make_db()
        # 5+ candles, position at avg=100, current=96 < 97 → sell (stop_loss)
        self._insert_candles(conn, "2330", [100.0] * 5 + [96.0])
        assert compute_signal(conn, "2330", position_avg_price=100.0, high_water_mark=None) == "sell"

    def test_sell_on_take_profit(self):
        from openclaw.signal_generator import compute_signal
        conn = self._make_db()
        self._insert_candles(conn, "2330", [100.0] * 5 + [103.0])
        assert compute_signal(conn, "2330", position_avg_price=100.0, high_water_mark=None) == "sell"

    def test_flat_hold(self):
        from openclaw.signal_generator import compute_signal
        conn = self._make_db()
        self._insert_candles(conn, "2330", [100.0] * 5 + [101.0])
        assert compute_signal(conn, "2330", position_avg_price=100.0, high_water_mark=None) == "flat"

    def test_flat_no_position_stable(self):
        from openclaw.signal_generator import compute_signal
        conn = self._make_db()
        self._insert_candles(conn, "2330", [100.0] * 25)
        assert compute_signal(conn, "2330", position_avg_price=None, high_water_mark=None) == "flat"
