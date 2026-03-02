from __future__ import annotations

import sqlite3

from openclaw.trading_calendar import (
    SeasonalEffectType,
    SeasonalEffect,
    get_effects_for_date,
    upsert_calendar_events,
    list_events_for_date,
    ensure_schema,
    _rule_quarter_end,
    _rule_window_dressing,
    _default_festival_events_for_year,
)
from datetime import date


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


# ── Additional tests for uncovered lines ─────────────────────────────────────

def test_rule_quarter_end_non_quarter_month_returns_none():
    """Line 82 (old line 79): non-quarter month (e.g. January) returns None."""
    d = date(2026, 1, 30)
    result = _rule_quarter_end(d)
    assert result is None


def test_rule_quarter_end_day_before_25_returns_none():
    """Line 82: quarter month but day < 25 → returns None."""
    d = date(2026, 3, 20)
    result = _rule_quarter_end(d)
    assert result is None


def test_list_events_for_date_bad_metadata_json():
    """Lines 180-181: invalid metadata_json falls back to empty dict {}."""
    conn = sqlite3.connect(":memory:")
    ensure_schema(conn)
    # Insert a row with deliberately broken metadata_json
    conn.execute(
        """
        INSERT INTO calendar_events(event_date, name, effect_type, impact, metadata_json, source, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        ("2026-07-01", "測試壞JSON", "festival", 0.1, "NOT_VALID_JSON{{", "unit_test"),
    )
    conn.commit()
    events = list_events_for_date(conn, "2026-07-01")
    # Should still return the event with metadata={}
    assert len(events) == 1
    assert events[0].metadata == {}


def test_list_events_for_date_invalid_effect_type_skipped():
    """Lines 184-185: invalid effect_type value → row is skipped (continue)."""
    conn = sqlite3.connect(":memory:")
    ensure_schema(conn)
    # Insert row with an unrecognised effect_type value
    conn.execute(
        """
        INSERT INTO calendar_events(event_date, name, effect_type, impact, metadata_json, source, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        ("2026-08-01", "未知效應", "unknown_type_xyz", 0.1, "{}", "unit_test"),
    )
    conn.commit()
    events = list_events_for_date(conn, "2026-08-01")
    # Row with invalid effect_type should be skipped
    assert events == []


def test_get_effects_for_date_builtin_festival_match():
    """Line 221: built-in festival event_date matches the requested date."""
    # 2026 CNY is on 2026-02-17 per _default_festival_events_for_year
    eff = get_effects_for_date("2026-02-17")
    types = {e.effect_type for e in eff}
    assert SeasonalEffectType.FESTIVAL in types
    names = [e.name for e in eff if e.effect_type == SeasonalEffectType.FESTIVAL]
    assert any("春節" in n for n in names)
