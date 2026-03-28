"""Tests for PositionRepository."""
from __future__ import annotations

import sqlite3

import pytest

from openclaw.repositories.position_repository import PositionRecord, PositionRepository


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE positions (
            symbol TEXT PRIMARY KEY,
            quantity INTEGER,
            avg_price REAL,
            current_price REAL DEFAULT 0,
            unrealized_pnl REAL DEFAULT 0,
            state TEXT DEFAULT 'ACTIVE',
            high_water_mark REAL DEFAULT 0,
            entry_trading_day TEXT
        );
        CREATE TABLE watcher_symbol_health (
            symbol TEXT PRIMARY KEY,
            consecutive_snapshot_failures INTEGER DEFAULT 0,
            suspended INTEGER DEFAULT 0,
            last_error TEXT,
            last_failure_at TEXT,
            updated_at TEXT
        );
    """)
    return c


@pytest.fixture()
def repo(conn):
    return PositionRepository(conn)


class TestGetActive:
    def test_returns_active_positions(self, conn, repo):
        conn.execute(
            "INSERT INTO positions (symbol, quantity, avg_price) VALUES (?, ?, ?)",
            ("2330", 1000, 500.0),
        )
        conn.execute(
            "INSERT INTO positions (symbol, quantity, avg_price) VALUES (?, ?, ?)",
            ("2317", 0, 200.0),
        )
        rows = repo.get_active()
        assert len(rows) == 1
        assert rows[0]["symbol"] == "2330"


class TestUpdatePrice:
    def test_updates_price_and_pnl(self, conn, repo):
        conn.execute(
            "INSERT INTO positions (symbol, quantity, avg_price) VALUES (?, ?, ?)",
            ("2330", 1000, 500.0),
        )
        repo.update_price("2330", 550.0, 50000.0)
        row = conn.execute("SELECT * FROM positions WHERE symbol='2330'").fetchone()
        assert row["current_price"] == 550.0
        assert row["unrealized_pnl"] == 50000.0


class TestUpsert:
    def test_inserts_new_position(self, conn, repo):
        repo.upsert(PositionRecord(symbol="2330", quantity=1000, avg_price=500.0))
        row = conn.execute("SELECT * FROM positions WHERE symbol='2330'").fetchone()
        assert row["quantity"] == 1000

    def test_replaces_existing_position(self, conn, repo):
        repo.upsert(PositionRecord(symbol="2330", quantity=1000, avg_price=500.0))
        repo.upsert(PositionRecord(symbol="2330", quantity=2000, avg_price=510.0))
        row = conn.execute("SELECT * FROM positions WHERE symbol='2330'").fetchone()
        assert row["quantity"] == 2000


class TestGetSuspendedSymbols:
    def test_returns_suspended(self, conn, repo):
        conn.execute(
            "INSERT INTO watcher_symbol_health (symbol, suspended) VALUES (?, ?)",
            ("2330", 1),
        )
        assert repo.get_suspended_symbols() == {"2330"}

    def test_returns_empty_when_no_table(self, repo):
        # Drop the table to simulate missing
        repo._conn.execute("DROP TABLE watcher_symbol_health")
        assert repo.get_suspended_symbols() == set()
