"""test_ticker_watcher.py — Phase 1 基礎測試

涵蓋：
- _is_market_open()：週末 / 非交易時段 / 正常時段 / 節假日
- _generate_signal()：buy / sell / flat
- _update_price_history()：累積與上限截斷
- _evaluate_cash_mode()：資料不足保持現狀 / bull market 正常 / bear market cash mode
"""

from __future__ import annotations

import datetime as dt

import pytest

from openclaw.ticker_watcher import (
    _CASH_MODE_MIN_PRICES,
    _PRICE_HISTORY_MAX,
    _evaluate_cash_mode,
    _generate_signal,
    _is_market_open,
    _update_price_history,
)

_TZ_TWN = dt.timezone(dt.timedelta(hours=8))


# ── _is_market_open() ────────────────────────────────────────────────────────

class TestIsMarketOpen:
    def _twn(self, year: int, month: int, day: int, hour: int, minute: int = 0) -> dt.datetime:
        return dt.datetime(year, month, day, hour, minute, tzinfo=_TZ_TWN)

    def test_saturday_closed(self):
        """週六 → 市場關閉"""
        # 2026-03-07 是週六
        sat = self._twn(2026, 3, 7, 10, 0)
        assert sat.weekday() == 5
        assert _is_market_open(sat) is False

    def test_sunday_closed(self):
        """週日 → 市場關閉"""
        # 2026-03-08 是週日
        sun = self._twn(2026, 3, 8, 10, 0)
        assert sun.weekday() == 6
        assert _is_market_open(sun) is False

    def test_weekday_before_market_closed(self):
        """平日 08:30（盤前開始前）→ 市場關閉"""
        # 2026-03-02 是週一
        before = self._twn(2026, 3, 2, 8, 30)
        assert _is_market_open(before) is False

    def test_weekday_after_market_closed(self):
        """平日 14:00（盤後競價結束後）→ 市場關閉"""
        after = self._twn(2026, 3, 2, 14, 0)
        assert _is_market_open(after) is False

    def test_regular_session_open(self):
        """平日 10:00（正常交易時段）→ 市場開放"""
        regular = self._twn(2026, 3, 2, 10, 0)
        assert _is_market_open(regular) is True

    def test_preopen_auction_open(self):
        """平日 09:05（盤前競價）→ 市場開放（tw_session_allows_trading = True）"""
        preopen = self._twn(2026, 3, 2, 9, 5)
        assert _is_market_open(preopen) is True

    def test_afterhours_auction_open(self):
        """平日 13:35（盤後競價）→ 市場開放"""
        after = self._twn(2026, 3, 2, 13, 35)
        assert _is_market_open(after) is True

    def test_festival_holiday_closed(self):
        """春節（2026-02-17）→ 市場關閉（trading_calendar FESTIVAL 效應）"""
        # 2026-02-17 是週二（平日），但 trading_calendar 內建春節
        cny = self._twn(2026, 2, 17, 10, 0)
        assert cny.weekday() < 5  # 確認是平日
        assert _is_market_open(cny) is False


# ── _generate_signal() ───────────────────────────────────────────────────────

class TestGenerateSignal:
    def _snap(self, close: float, reference: float) -> dict:
        return {
            "close": close,
            "reference": reference,
            "bid": close * 0.999,
            "ask": close * 1.001,
            "volume": 1000,
        }

    def test_buy_signal_no_position(self):
        """close < ref * 0.998 且無持倉 → buy"""
        snap = self._snap(close=897.0, reference=900.0)  # 897 < 900*0.998=898.2
        assert _generate_signal(snap, position_avg_price=None) == "buy"

    def test_flat_signal_no_position_price_not_low(self):
        """close >= ref * 0.998 且無持倉 → flat"""
        snap = self._snap(close=899.0, reference=900.0)  # 899 > 898.2
        assert _generate_signal(snap, position_avg_price=None) == "flat"

    def test_sell_signal_with_position_profit(self):
        """有持倉 + close > avg * 1.02 → sell（止盈 +2%）"""
        snap = self._snap(close=920.0, reference=900.0)
        # 920 > 900 * 1.02 = 918
        assert _generate_signal(snap, position_avg_price=900.0) == "sell"

    def test_flat_signal_with_position_no_profit(self):
        """有持倉 + close < avg * 1.02 且 > avg * 0.97 → flat（在停損/止盈帶內）"""
        snap = self._snap(close=910.0, reference=900.0)
        # 910 < 900 * 1.02 = 918，且 910 > 900 * 0.97 = 873
        assert _generate_signal(snap, position_avg_price=900.0) == "flat"

    def test_sell_signal_with_position_at_stop_loss(self):
        """有持倉 + close < avg * 0.97 → sell（止損 -3%）"""
        snap = self._snap(close=850.0, reference=900.0)
        # 850 < 900 * 0.97 = 873 → 觸發止損
        assert _generate_signal(snap, position_avg_price=900.0) == "sell"

    def test_flat_signal_with_position_small_loss(self):
        """有持倉小幅虧損（-1%）→ flat（未達止損線 -3%）"""
        snap = self._snap(close=891.0, reference=900.0)
        # 891 > 900 * 0.97 = 873，且 891 < 918 → flat
        assert _generate_signal(snap, position_avg_price=900.0) == "flat"


# ── _update_price_history() ──────────────────────────────────────────────────

class TestUpdatePriceHistory:
    def test_accumulates_prices(self):
        """連續加入價格應正確累積"""
        hist: dict = {}
        _update_price_history(hist, "2330", 900.0)
        _update_price_history(hist, "2330", 905.0)
        assert hist["2330"] == [900.0, 905.0]

    def test_caps_at_max(self):
        """超過上限時，舊資料被移除"""
        hist: dict = {}
        for i in range(_PRICE_HISTORY_MAX + 5):
            _update_price_history(hist, "2330", float(900 + i))
        assert len(hist["2330"]) == _PRICE_HISTORY_MAX
        # 最後一筆應為最新加入
        assert hist["2330"][-1] == float(900 + _PRICE_HISTORY_MAX + 4)

    def test_multiple_symbols_independent(self):
        """不同 symbol 的歷史互不干擾"""
        hist: dict = {}
        _update_price_history(hist, "2330", 900.0)
        _update_price_history(hist, "2317", 200.0)
        assert hist["2330"] == [900.0]
        assert hist["2317"] == [200.0]


# ── _evaluate_cash_mode() ────────────────────────────────────────────────────

class TestEvaluateCashMode:
    def _hist_with(self, prices: list[float]) -> dict:
        return {"2330": prices}

    def test_insufficient_data_keeps_current(self):
        """資料不足（< _CASH_MODE_MIN_PRICES）→ 維持現狀，不切換"""
        hist = self._hist_with([900.0] * (_CASH_MODE_MIN_PRICES - 1))
        cash_mode, reason = _evaluate_cash_mode(hist, current_cash_mode=False)
        assert cash_mode is False
        assert reason == "CASHMODE_INSUFFICIENT_DATA"

    def test_insufficient_data_keeps_current_true(self):
        """資料不足時，若原本 cash_mode=True，仍維持 True"""
        hist = self._hist_with([900.0] * 5)
        cash_mode, reason = _evaluate_cash_mode(hist, current_cash_mode=True)
        assert cash_mode is True
        assert reason == "CASHMODE_INSUFFICIENT_DATA"

    def test_stable_bull_prices_normal_mode(self):
        """穩定上漲行情 → cash_mode=False（CASHMODE_NORMAL 或 CASHMODE_EXIT_*）"""
        # 60 筆持續上漲的價格 → BULL regime
        prices = [float(800 + i * 5) for i in range(60)]
        hist = self._hist_with(prices)
        cash_mode, reason = _evaluate_cash_mode(hist, current_cash_mode=False)
        assert cash_mode is False

    def test_strong_bear_prices_cash_mode(self):
        """強烈下跌行情（高波動）→ cash_mode=True"""
        # 60 筆持續大跌的價格
        prices = [float(1000 - i * 10) for i in range(60)]
        hist = self._hist_with(prices)
        cash_mode, reason = _evaluate_cash_mode(hist, current_cash_mode=False)
        # Bear regime with sufficient confidence → cash mode
        assert cash_mode is True

    def test_uses_2330_as_bellwether(self):
        """即使有其他 symbol，優先使用 2330 作為基準"""
        prices_2330 = [float(900 + i) for i in range(_CASH_MODE_MIN_PRICES)]
        prices_other = [float(50 - i) for i in range(_CASH_MODE_MIN_PRICES)]
        hist = {"2317": prices_other, "2330": prices_2330}
        # 結果應根據 2330 評估（上漲 → normal，不進入 cash mode）
        cash_mode, _ = _evaluate_cash_mode(hist, current_cash_mode=False)
        assert cash_mode is False

    def test_fallback_to_other_symbol_if_no_2330(self):
        """無 2330 資料時，fallback 到其他有足夠資料的 symbol"""
        prices = [float(200 + i * 2) for i in range(_CASH_MODE_MIN_PRICES)]
        hist = {"2317": prices}
        cash_mode, reason = _evaluate_cash_mode(hist, current_cash_mode=False)
        assert reason != "CASHMODE_INSUFFICIENT_DATA"  # 有資料，應能評估
