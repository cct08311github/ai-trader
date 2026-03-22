"""Tests for performance_summary module (#387).

Covers:
- build_daily_summary returns valid DailyPerformanceSummary
- format_summary_text produces readable output
- check_nav_staleness detects stale data
- Handles missing tables gracefully
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

from openclaw.performance_summary import (
    DailyPerformanceSummary,
    build_daily_summary,
    check_nav_staleness,
    format_summary_text,
)


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE daily_nav (
            trade_date TEXT PRIMARY KEY,
            nav REAL, cash REAL, unrealized_pnl REAL,
            realized_pnl_cumulative REAL, recorded_at INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE daily_pnl_summary (
            trade_date TEXT PRIMARY KEY,
            realized_pnl REAL,
            rolling_win_rate REAL,
            consecutive_losses INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE decisions (
            decision_id TEXT PRIMARY KEY,
            symbol TEXT, signal TEXT, signal_score REAL,
            signal_source TEXT, created_at INTEGER
        )
    """)
    return conn


def _populate_nav(conn: sqlite3.Connection, days: int = 10) -> None:
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    for i in range(days):
        d = (now - timedelta(days=days - i - 1)).strftime("%Y-%m-%d")
        nav = 1_000_000 + i * 5000
        conn.execute(
            "INSERT INTO daily_nav VALUES (?,?,?,?,?,?)",
            (d, nav, 500000, i * 1000, i * 2000, int(time.time() * 1000)),
        )
    conn.commit()


class TestBuildDailySummary:
    def test_returns_summary_with_nav_data(self):
        conn = _make_db()
        _populate_nav(conn, 5)
        tz = timezone(timedelta(hours=8))
        today = datetime.now(tz).strftime("%Y-%m-%d")
        summary = build_daily_summary(conn, today)
        assert isinstance(summary, DailyPerformanceSummary)
        assert summary.trade_date == today
        assert summary.nav > 0

    def test_returns_zero_nav_when_no_data(self):
        conn = _make_db()
        summary = build_daily_summary(conn, "2099-01-01")
        assert summary.nav == 0.0
        assert summary.nav_change_pct == 0.0

    def test_calculates_nav_change_pct(self):
        conn = _make_db()
        conn.execute("INSERT INTO daily_nav VALUES ('2026-03-18', 1000000, 500000, 0, 0, 1)")
        conn.execute("INSERT INTO daily_nav VALUES ('2026-03-19', 1050000, 500000, 50000, 0, 1)")
        conn.commit()
        summary = build_daily_summary(conn, "2026-03-19")
        assert summary.nav_change_pct == 5.0  # +5%

    def test_28d_stats_with_pnl_data(self):
        conn = _make_db()
        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)
        for i in range(10):
            d = (now - timedelta(days=10 - i)).strftime("%Y-%m-%d")
            pnl = 1000 if i % 3 != 0 else -500  # ~67% win rate
            conn.execute("INSERT INTO daily_pnl_summary VALUES (?,?,?,?)", (d, pnl, 0.6, 0))
        conn.commit()
        summary = build_daily_summary(conn, now.strftime("%Y-%m-%d"))
        assert summary.win_rate_28d is not None
        assert summary.total_trades_28d == 10


class TestFormatSummaryText:
    def test_produces_readable_text(self):
        summary = DailyPerformanceSummary(
            trade_date="2026-03-19",
            nav=1_050_000,
            nav_change_pct=2.5,
            realized_pnl_today=5000,
            realized_pnl_cumulative=25000,
            unrealized_pnl=-3000,
            win_rate_28d=0.55,
            profit_factor_28d=1.3,
            total_trades_28d=20,
            signal_attribution={"technical": {"count": 15, "win_rate": 0.6}},
        )
        text = format_summary_text(summary)
        assert "2026-03-19" in text
        assert "1,050,000" in text
        assert "+2.50%" in text
        assert "55.0%" in text
        assert "technical" in text

    def test_handles_none_values(self):
        summary = DailyPerformanceSummary(
            trade_date="2026-03-19",
            nav=0,
            nav_change_pct=0,
            realized_pnl_today=0,
            realized_pnl_cumulative=0,
            unrealized_pnl=0,
            win_rate_28d=None,
            profit_factor_28d=None,
            total_trades_28d=0,
            signal_attribution={},
        )
        text = format_summary_text(summary)
        assert "2026-03-19" in text
        assert "28日勝率" not in text  # Should be skipped when None


class TestCheckNavStaleness:
    def test_returns_none_when_recent(self):
        conn = _make_db()
        _populate_nav(conn, 3)
        result = check_nav_staleness(conn)
        assert result is None  # Recent data → OK

    def test_returns_warning_when_stale(self):
        conn = _make_db()
        # Insert data from 10 days ago
        old_date = (datetime.now(timezone(timedelta(hours=8))) - timedelta(days=10)).strftime("%Y-%m-%d")
        conn.execute("INSERT INTO daily_nav VALUES (?,?,?,?,?,?)", (old_date, 1000000, 500000, 0, 0, 1))
        conn.commit()
        result = check_nav_staleness(conn)
        assert result is not None
        assert "stale" in result

    def test_returns_warning_when_empty(self):
        conn = _make_db()
        result = check_nav_staleness(conn)
        assert result is not None
        assert "empty" in result
