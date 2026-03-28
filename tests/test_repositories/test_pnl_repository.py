"""Tests for PnLRepository."""
from __future__ import annotations

import sqlite3

import pytest

from openclaw.repositories.pnl_repository import PnLRepository


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE orders (
            order_id TEXT PRIMARY KEY, symbol TEXT, side TEXT,
            status TEXT, ts_submit TEXT
        );
        CREATE TABLE fills (
            fill_id TEXT, order_id TEXT, qty INTEGER, price REAL,
            fee REAL DEFAULT 0, tax REAL DEFAULT 0
        );
        CREATE TABLE positions (
            symbol TEXT PRIMARY KEY, quantity INTEGER, avg_price REAL,
            current_price REAL DEFAULT 0, unrealized_pnl REAL DEFAULT 0,
            state TEXT DEFAULT 'ACTIVE', high_water_mark REAL,
            entry_trading_day TEXT
        );
        CREATE TABLE daily_pnl_summary (
            trade_date TEXT PRIMARY KEY, realized_pnl REAL,
            unrealized_pnl REAL DEFAULT 0, total_pnl REAL DEFAULT 0,
            total_trades INTEGER DEFAULT 0, rolling_drawdown REAL DEFAULT 0,
            consecutive_losses INTEGER DEFAULT 0,
            losing_streak_days INTEGER DEFAULT 0,
            rolling_win_rate REAL DEFAULT 0
        );
        CREATE TABLE eod_prices (
            trade_date TEXT, symbol TEXT, open REAL, high REAL,
            low REAL, close REAL, volume INTEGER
        );
    """)
    return c


@pytest.fixture()
def repo(conn):
    return PnLRepository(conn)


class TestGetAvgCost:
    def test_returns_zero_when_no_orders(self, repo):
        avg, qty = repo.get_avg_cost("2330")
        assert avg == 0.0
        assert qty == 0

    def test_computes_avg_cost(self, conn, repo):
        conn.execute("INSERT INTO orders VALUES ('o1','2330','buy','filled','2026-03-28')")
        conn.execute("INSERT INTO fills VALUES ('f1','o1',1000,500.0,0,0)")
        avg, qty = repo.get_avg_cost("2330")
        assert qty == 1000
        assert avg == 500.0


class TestUpsertDailyPnl:
    def test_inserts_new_record(self, conn, repo):
        repo.upsert_daily_pnl("2026-03-28", 1000.0, 1)
        row = conn.execute("SELECT * FROM daily_pnl_summary WHERE trade_date='2026-03-28'").fetchone()
        assert row["realized_pnl"] == 1000.0
        assert row["total_trades"] == 1

    def test_updates_existing_record(self, conn, repo):
        repo.upsert_daily_pnl("2026-03-28", 1000.0, 1)
        repo.upsert_daily_pnl("2026-03-28", 500.0, 1)
        row = conn.execute("SELECT * FROM daily_pnl_summary WHERE trade_date='2026-03-28'").fetchone()
        assert row["realized_pnl"] == 1500.0
        assert row["total_trades"] == 2


class TestSyncPositions:
    def test_syncs_from_orders_fills(self, conn, repo):
        conn.execute("INSERT INTO orders VALUES ('o1','2330','buy','filled','2026-03-28')")
        conn.execute("INSERT INTO fills VALUES ('f1','o1',1000,500.0,0,0)")
        repo.sync_positions()
        row = conn.execute("SELECT * FROM positions WHERE symbol='2330'").fetchone()
        assert row["quantity"] == 1000
        assert row["avg_price"] == 500.0

    def test_excludes_sold_positions(self, conn, repo):
        conn.execute("INSERT INTO orders VALUES ('o1','2330','buy','filled','2026-03-28')")
        conn.execute("INSERT INTO fills VALUES ('f1','o1',1000,500.0,0,0)")
        conn.execute("INSERT INTO orders VALUES ('o2','2330','sell','filled','2026-03-28')")
        conn.execute("INSERT INTO fills VALUES ('f2','o2',1000,510.0,0,0)")
        repo.sync_positions()
        row = conn.execute("SELECT * FROM positions WHERE symbol='2330'").fetchone()
        assert row is None  # net_qty = 0, excluded


class TestGetTodayPnl:
    def test_returns_zero_when_no_data(self, repo):
        assert repo.get_today_pnl("2026-03-28") == 0.0

    def test_returns_pnl(self, conn, repo):
        conn.execute(
            "INSERT INTO daily_pnl_summary (trade_date, realized_pnl, total_trades) VALUES (?, ?, ?)",
            ("2026-03-28", 1500.0, 3),
        )
        assert repo.get_today_pnl("2026-03-28") == 1500.0


class TestGetMonthlyPnl:
    def test_returns_sum(self, conn, repo):
        conn.execute(
            "INSERT INTO daily_pnl_summary (trade_date, realized_pnl, total_trades) VALUES (?, ?, ?)",
            ("2026-03-27", 1000.0, 1),
        )
        conn.execute(
            "INSERT INTO daily_pnl_summary (trade_date, realized_pnl, total_trades) VALUES (?, ?, ?)",
            ("2026-03-28", 500.0, 1),
        )
        assert repo.get_monthly_pnl("2026-03") == 1500.0


class TestGetOverallWinRate:
    def test_returns_zero_when_no_data(self, repo):
        assert repo.get_overall_win_rate() == 0.0

    def test_computes_win_rate(self, conn, repo):
        for i, pnl in enumerate([100, -50, 200]):
            conn.execute(
                "INSERT INTO daily_pnl_summary (trade_date, realized_pnl, total_trades) VALUES (?, ?, 1)",
                (f"2026-03-{26+i}", pnl),
            )
        assert repo.get_overall_win_rate() == round(2 / 3, 4)


class TestBackfillHighWaterMark:
    def test_backfills_from_eod(self, conn, repo):
        conn.execute(
            "INSERT INTO positions (symbol, quantity, avg_price, entry_trading_day) VALUES (?, ?, ?, ?)",
            ("2330", 1000, 500.0, "2026-03-01"),
        )
        conn.execute(
            "INSERT INTO eod_prices VALUES ('2026-03-15', '2330', 500, 550, 490, 540, 10000)"
        )
        conn.execute(
            "INSERT INTO eod_prices VALUES ('2026-03-20', '2330', 540, 560, 530, 555, 12000)"
        )
        repo.backfill_high_water_mark()
        row = conn.execute("SELECT high_water_mark FROM positions WHERE symbol='2330'").fetchone()
        assert row["high_water_mark"] == 555.0  # max(close) from eod_prices
