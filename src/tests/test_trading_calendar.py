from __future__ import annotations

import sqlite3

from openclaw.trading_calendar import (
    SeasonalEffectType,
    SeasonalEffect,
    get_effects_for_date,
    upsert_calendar_events,
)


def test_trading_calendar_rules_quarter_end_and_window_dressing():
    # End of March should trigger quarter-end + window dressing by rules.
    eff = get_effects_for_date("2026-03-30")
    types = {e.effect_type for e in eff}
    assert SeasonalEffectType.QUARTER_END in types
    assert SeasonalEffectType.WINDOW_DRESSING in types


def test_trading_calendar_db_festival_event_roundtrip():
    conn = sqlite3.connect(":memory:")

    upsert_calendar_events(
        conn,
        [
            SeasonalEffect(
                event_date="2026-02-10",
                name="春節效應(測試)",
                effect_type=SeasonalEffectType.FESTIVAL,
                impact=0.5,
                metadata={"festival": "cny"},
            )
        ],
        source="unit_test",
    )

    eff = get_effects_for_date("2026-02-10", conn=conn)
    assert any(e.effect_type == SeasonalEffectType.FESTIVAL and "春節" in e.name for e in eff)
