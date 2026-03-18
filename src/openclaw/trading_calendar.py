from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence

# ── 台灣股票交易所國定假日（2025–2026）────────────────────────────────────────
TAIWAN_HOLIDAYS_2024_2026: set[date] = {
    # 2025 Taiwan public holidays (TSE calendar)
    date(2025, 1, 1),   # New Year's Day 元旦
    date(2025, 1, 27),  # Lunar New Year eve 農曆除夕
    date(2025, 1, 28),  # Lunar New Year Day 1 春節
    date(2025, 1, 29),  # Lunar New Year Day 2 春節
    date(2025, 1, 30),  # Lunar New Year Day 3 春節
    date(2025, 1, 31),  # Lunar New Year Day 4 春節
    date(2025, 2, 28),  # Peace Memorial Day 和平紀念日
    date(2025, 4, 3),   # Children's Day 兒童節
    date(2025, 4, 4),   # Tomb Sweeping Day 清明節
    date(2025, 5, 1),   # Labor Day 勞動節
    date(2025, 5, 30),  # Dragon Boat Festival eve 端午節補假
    date(2025, 5, 31),  # Dragon Boat Festival 端午節
    date(2025, 10, 6),  # Mid-Autumn Festival 中秋節
    date(2025, 10, 10), # National Day 國慶日
    # 2026 Taiwan public holidays (TSE calendar)
    date(2026, 1, 1),   # New Year's Day 元旦
    date(2026, 2, 16),  # Lunar New Year Day 1 春節
    date(2026, 2, 17),  # Lunar New Year Day 2 春節
    date(2026, 2, 18),  # Lunar New Year Day 3 春節
    date(2026, 2, 19),  # Lunar New Year Day 4 春節
    date(2026, 2, 20),  # Lunar New Year Day 5 春節
    date(2026, 3, 28),  # Tomb Sweeping Day makeup 清明節補假
    date(2026, 4, 3),   # Children's Day 兒童節
    date(2026, 4, 4),   # Tomb Sweeping Day 清明節
    date(2026, 6, 19),  # Dragon Boat Festival 端午節
    date(2026, 9, 25),  # Mid-Autumn Festival 中秋節
    date(2026, 10, 9),  # National Day makeup 國慶日補假
    date(2026, 10, 10), # National Day 國慶日
}


def is_trading_day(d: date) -> bool:
    """判斷指定日期是否為台股交易日。

    非交易日條件：週六、週日、或在 TAIWAN_HOLIDAYS_2024_2026 中的國定假日。

    Args:
        d: 要判斷的日期。

    Returns:
        True 表示為交易日；False 表示非交易日。
    """
    if d.weekday() >= 5:  # 5=Saturday, 6=Sunday
        return False
    if d in TAIWAN_HOLIDAYS_2024_2026:
        return False
    return True


def next_trading_day(d: date) -> date:
    """回傳指定日期之後（不含當天）的下一個交易日。

    Args:
        d: 起始日期（不含）。

    Returns:
        下一個交易日。
    """
    candidate = d + _dt.timedelta(days=1)
    while not is_trading_day(candidate):
        candidate += _dt.timedelta(days=1)
    return candidate


def add_trading_days(d: date, n: int) -> date:
    """從指定日期向後推進 n 個交易日。

    Args:
        d: 起始日期（不含在計數內）。
        n: 要推進的交易日數量，必須為正整數。

    Returns:
        推進 n 個交易日後的日期。
    """
    result = d
    for _ in range(n):
        result = next_trading_day(result)
    return result


def get_settlement_date(trade_date: date) -> date:
    """計算台股 T+2 交割日，正確排除週末與國定假日。

    Args:
        trade_date: 交易日期。

    Returns:
        T+2 交割日（date 物件）。
    """
    return add_trading_days(trade_date, 2)


class SeasonalEffectType(str, Enum):
    FESTIVAL = "festival"
    QUARTER_END = "quarter_end"
    WINDOW_DRESSING = "window_dressing"


@dataclass(frozen=True)
class SeasonalEffect:
    event_date: str  # YYYY-MM-DD
    name: str
    effect_type: SeasonalEffectType
    impact: float = 0.0
    metadata: Dict[str, Any] | None = None


def _parse_date(d: str) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date()


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Ensure calendar_events exists (ticks.db recommended)."""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS calendar_events (
          event_date    TEXT NOT NULL,
          name          TEXT NOT NULL,
          effect_type   TEXT NOT NULL,
          impact        REAL NOT NULL,
          metadata_json TEXT NOT NULL,
          source        TEXT NOT NULL,
          updated_at    TEXT NOT NULL,
          PRIMARY KEY (event_date, name, effect_type)
        )
        """
    )


def upsert_calendar_events(conn: sqlite3.Connection, events: Sequence[SeasonalEffect], *, source: str = "manual") -> int:
    ensure_schema(conn)
    conn.executemany(
        """
        INSERT INTO calendar_events(
          event_date, name, effect_type, impact, metadata_json, source, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(event_date, name, effect_type) DO UPDATE SET
          impact = excluded.impact,
          metadata_json = excluded.metadata_json,
          source = excluded.source,
          updated_at = excluded.updated_at
        """,
        [
            (
                e.event_date,
                e.name,
                e.effect_type.value,
                float(e.impact),
                json.dumps(e.metadata or {}, ensure_ascii=True),
                source,
            )
            for e in events
        ],
    )
    return len(events)


def _rule_quarter_end(d: date) -> Optional[SeasonalEffect]:
    if d.month not in (3, 6, 9, 12):
        return None
    # Approximate: last calendar week of the quarter month.
    if d.day < 25:
        return None
    return SeasonalEffect(
        event_date=d.isoformat(),
        name="季底效應",
        effect_type=SeasonalEffectType.QUARTER_END,
        impact=0.25,
        metadata={"window": "last_week"},
    )


def _rule_window_dressing(d: date) -> Optional[SeasonalEffect]:
    # Approximate: month-end window dressing (法人作帳) in the last few days.
    if d.day < 26:
        return None
    return SeasonalEffect(
        event_date=d.isoformat(),
        name="法人作帳效應",
        effect_type=SeasonalEffectType.WINDOW_DRESSING,
        impact=0.20,
        metadata={"window": "month_end"},
    )


def _default_festival_events_for_year(year: int) -> List[SeasonalEffect]:
    """Built-in festival events (minimal).

    Lunar-based festivals vary by year; production should load from external
    sources. We provide a *tiny* baked-in set for deterministic behavior.

    The unit tests should not depend on this mapping.
    """

    out: List[SeasonalEffect] = []

    # Keep a small, conservative mapping for the next few years.
    # Sources: public calendars (not embedded here). Adjust via DB upsert.
    known: Dict[int, Dict[str, str]] = {
        2026: {
            "cny": "2026-02-17",
            "dragon_boat": "2026-06-19",
            "mid_autumn": "2026-09-25",
        }
    }
    m = known.get(year) or {}

    if "cny" in m:
        out.append(
            SeasonalEffect(
                event_date=m["cny"],
                name="春節效應",
                effect_type=SeasonalEffectType.FESTIVAL,
                impact=0.30,
                metadata={"festival": "cny"},
            )
        )
    if "dragon_boat" in m:
        out.append(
            SeasonalEffect(
                event_date=m["dragon_boat"],
                name="端午效應",
                effect_type=SeasonalEffectType.FESTIVAL,
                impact=0.15,
                metadata={"festival": "dragon_boat"},
            )
        )
    if "mid_autumn" in m:
        out.append(
            SeasonalEffect(
                event_date=m["mid_autumn"],
                name="中秋效應",
                effect_type=SeasonalEffectType.FESTIVAL,
                impact=0.15,
                metadata={"festival": "mid_autumn"},
            )
        )

    return out


def list_events_for_date(conn: sqlite3.Connection, d: str) -> List[SeasonalEffect]:
    """List DB-stored calendar events for a given date."""

    ensure_schema(conn)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT event_date, name, effect_type, impact, metadata_json
        FROM calendar_events
        WHERE event_date = ?
        ORDER BY effect_type, name
        """,
        (d,),
    ).fetchall()

    out: List[SeasonalEffect] = []
    for r in rows:
        try:
            meta = json.loads(r["metadata_json"]) if r["metadata_json"] else {}
        except Exception:
            meta = {}
        try:
            et = SeasonalEffectType(str(r["effect_type"]))
        except Exception:
            continue
        out.append(
            SeasonalEffect(
                event_date=str(r["event_date"]),
                name=str(r["name"]),
                effect_type=et,
                impact=float(r["impact"]),
                metadata=meta,
            )
        )
    return out


def get_effects_for_date(d: str, *, conn: sqlite3.Connection | None = None) -> List[SeasonalEffect]:
    """Return seasonal effects for a given date.

    Includes:
    - rule-based effects (quarter end, window dressing)
    - optional DB-backed events (festivals, overrides)
    - a minimal built-in festival mapping (best-effort)
    """

    dd = _parse_date(d)
    effects: List[SeasonalEffect] = []

    qe = _rule_quarter_end(dd)
    if qe:
        effects.append(qe)

    wd = _rule_window_dressing(dd)
    if wd:
        effects.append(wd)

    # Built-in festivals (minimal, can be overridden by DB data).
    for e in _default_festival_events_for_year(dd.year):
        if e.event_date == d:
            effects.append(e)

    if conn is not None:
        effects.extend(list_events_for_date(conn, d))

    # De-duplicate by (date, type, name)
    uniq: Dict[str, SeasonalEffect] = {}
    for e in effects:
        k = f"{e.event_date}|{e.effect_type.value}|{e.name}"
        uniq[k] = e

    return list(uniq.values())
