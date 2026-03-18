"""tests/test_trading_calendar.py

測試 trading_calendar 新增的交易日判斷與 T+2 交割日計算功能。
"""

from __future__ import annotations

from datetime import date

import pytest

from openclaw.trading_calendar import (
    TAIWAN_HOLIDAYS_2024_2026,
    add_trading_days,
    get_settlement_date,
    is_trading_day,
    next_trading_day,
)


# ── is_trading_day ────────────────────────────────────────────────────────────

class TestIsTradingDay:
    def test_saturday_is_not_trading_day(self):
        # 2025-03-01 is Saturday
        assert is_trading_day(date(2025, 3, 1)) is False

    def test_sunday_is_not_trading_day(self):
        # 2025-03-02 is Sunday
        assert is_trading_day(date(2025, 3, 2)) is False

    def test_regular_weekday_is_trading_day(self):
        # 2025-03-03 is Monday (no holiday)
        assert is_trading_day(date(2025, 3, 3)) is True

    def test_another_regular_weekday(self):
        # 2025-03-05 is Wednesday
        assert is_trading_day(date(2025, 3, 5)) is True

    def test_new_year_2025_is_not_trading_day(self):
        assert is_trading_day(date(2025, 1, 1)) is False

    def test_lunar_new_year_2025_days_are_not_trading_days(self):
        for d in [27, 28, 29, 30, 31]:
            assert is_trading_day(date(2025, 1, d)) is False, f"2025-01-{d} should be holiday"

    def test_peace_memorial_day_2025(self):
        assert is_trading_day(date(2025, 2, 28)) is False

    def test_tomb_sweeping_2025(self):
        assert is_trading_day(date(2025, 4, 3)) is False
        assert is_trading_day(date(2025, 4, 4)) is False

    def test_labor_day_2025(self):
        assert is_trading_day(date(2025, 5, 1)) is False

    def test_dragon_boat_2025(self):
        assert is_trading_day(date(2025, 5, 30)) is False
        assert is_trading_day(date(2025, 5, 31)) is False

    def test_mid_autumn_2025(self):
        assert is_trading_day(date(2025, 10, 6)) is False

    def test_national_day_2025(self):
        assert is_trading_day(date(2025, 10, 10)) is False

    def test_new_year_2026_is_not_trading_day(self):
        assert is_trading_day(date(2026, 1, 1)) is False

    def test_lunar_new_year_2026_days_are_not_trading_days(self):
        for d in [16, 17, 18, 19, 20]:
            assert is_trading_day(date(2026, 2, d)) is False, f"2026-02-{d} should be holiday"

    def test_dragon_boat_2026(self):
        assert is_trading_day(date(2026, 6, 19)) is False

    def test_mid_autumn_2026(self):
        assert is_trading_day(date(2026, 9, 25)) is False

    def test_national_day_2026(self):
        assert is_trading_day(date(2026, 10, 9)) is False
        assert is_trading_day(date(2026, 10, 10)) is False

    def test_regular_day_around_holiday_is_trading(self):
        # 2025-04-02 (Wednesday) is NOT a holiday
        assert is_trading_day(date(2025, 4, 2)) is True
        # 2025-04-07 (Monday) is NOT a holiday
        assert is_trading_day(date(2025, 4, 7)) is True


# ── get_settlement_date ───────────────────────────────────────────────────────

class TestGetSettlementDate:
    def test_t2_normal_weekday(self):
        # Monday 2025-03-03 → T+2 = Wednesday 2025-03-05
        result = get_settlement_date(date(2025, 3, 3))
        assert result == date(2025, 3, 5)

    def test_t2_skips_weekend(self):
        # Thursday 2025-03-06 → skip Sat/Sun → T+1 = Fri 07, T+2 = Mon 10
        result = get_settlement_date(date(2025, 3, 6))
        assert result == date(2025, 3, 10)

    def test_t2_skips_holiday_tomb_sweeping_2025(self):
        # 2025-04-02 (Wed) → T+1 = Thu 04-03 (holiday Children's Day), skip →
        # T+1 lands on 04-07 (Mon), T+2 lands on 04-08 (Tue)
        # Actually: from 04-02, next trading day skipping 04-03 & 04-04 = 04-07 (Mon) = +1
        # then +2 = 04-08 (Tue)
        result = get_settlement_date(date(2025, 4, 2))
        assert result == date(2025, 4, 8)

    def test_t2_skips_holiday_national_day_2026(self):
        # 2026-10-08 (Thu) → T+1: skip 10-09 (holiday) = 10-12 (Mon)?
        # 10-09 Fri holiday, 10-10 Sat (weekend+holiday), so next = 10-12 Mon
        # T+2 from 10-12 Mon = 10-13 Tue
        result = get_settlement_date(date(2026, 10, 8))
        assert result == date(2026, 10, 13)

    def test_t2_mid_autumn_2025(self):
        # 2025-10-03 (Fri) → next trading: skip 10-04 Sat, 10-05 Sun, 10-06 Mon (holiday)
        # → 10-07 Tue = T+1, 10-08 Wed = T+2
        result = get_settlement_date(date(2025, 10, 3))
        assert result == date(2025, 10, 8)

    def test_t2_result_is_date_object(self):
        result = get_settlement_date(date(2025, 3, 10))
        assert isinstance(result, date)


# ── add_trading_days ──────────────────────────────────────────────────────────

class TestAddTradingDays:
    def test_add_zero(self):
        d = date(2025, 3, 3)
        # add_trading_days with n=0 should return same date (loop doesn't run)
        result = add_trading_days(d, 0)
        assert result == d

    def test_add_one(self):
        # Mon 2025-03-03, +1 = Tue 2025-03-04
        assert add_trading_days(date(2025, 3, 3), 1) == date(2025, 3, 4)

    def test_add_five_skips_weekend(self):
        # Mon 2025-03-03 +5 trading days → Mon 2025-03-10
        assert add_trading_days(date(2025, 3, 3), 5) == date(2025, 3, 10)


# ── next_trading_day ──────────────────────────────────────────────────────────

class TestNextTradingDay:
    def test_next_from_friday(self):
        # Fri 2025-03-07 → Mon 2025-03-10
        assert next_trading_day(date(2025, 3, 7)) == date(2025, 3, 10)

    def test_next_from_holiday(self):
        # 2025-04-03 (holiday) → next = 2025-04-07 (Mon, skipping 04-04 also holiday)
        assert next_trading_day(date(2025, 4, 3)) == date(2025, 4, 7)

    def test_next_from_regular_day(self):
        # Tue 2025-03-04 → Wed 2025-03-05
        assert next_trading_day(date(2025, 3, 4)) == date(2025, 3, 5)


# ── TAIWAN_HOLIDAYS_2024_2026 set ─────────────────────────────────────────────

class TestHolidaySet:
    def test_holiday_set_not_empty(self):
        assert len(TAIWAN_HOLIDAYS_2024_2026) > 0

    def test_all_entries_are_date_objects(self):
        for d in TAIWAN_HOLIDAYS_2024_2026:
            assert isinstance(d, date)

    def test_contains_key_2025_holidays(self):
        assert date(2025, 1, 1) in TAIWAN_HOLIDAYS_2024_2026
        assert date(2025, 2, 28) in TAIWAN_HOLIDAYS_2024_2026
        assert date(2025, 10, 10) in TAIWAN_HOLIDAYS_2024_2026

    def test_contains_key_2026_holidays(self):
        assert date(2026, 1, 1) in TAIWAN_HOLIDAYS_2024_2026
        assert date(2026, 6, 19) in TAIWAN_HOLIDAYS_2024_2026
        assert date(2026, 10, 10) in TAIWAN_HOLIDAYS_2024_2026
