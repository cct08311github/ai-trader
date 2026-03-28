"""Tests for OrderRepository."""
from __future__ import annotations

import sqlite3
import uuid

import pytest

from openclaw.repositories.order_repository import FillRecord, OrderRecord, OrderRepository


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE orders (
            order_id TEXT PRIMARY KEY,
            decision_id TEXT,
            broker_order_id TEXT,
            ts_submit TEXT,
            symbol TEXT,
            side TEXT,
            qty INTEGER,
            price REAL,
            order_type TEXT,
            tif TEXT,
            status TEXT,
            strategy_version TEXT,
            settlement_date TEXT,
            account_mode TEXT
        );
        CREATE TABLE fills (
            fill_id TEXT PRIMARY KEY,
            order_id TEXT,
            ts_fill TEXT,
            qty INTEGER,
            price REAL,
            fee REAL,
            tax REAL
        );
        CREATE TABLE order_events (
            event_id TEXT PRIMARY KEY,
            ts TEXT,
            order_id TEXT,
            event_type TEXT,
            from_status TEXT,
            to_status TEXT,
            source TEXT,
            reason_code TEXT,
            payload_json TEXT
        );
    """)
    return c


@pytest.fixture()
def repo(conn):
    return OrderRepository(conn)


class TestInsertOrder:
    def test_inserts_and_retrieves(self, conn, repo):
        order = OrderRecord(
            order_id="o1", decision_id="d1", broker_order_id="b1",
            symbol="2330", side="buy", qty=1000, price=100.0,
            strategy_version="v1",
        )
        repo.insert_order(order)
        row = conn.execute("SELECT * FROM orders WHERE order_id='o1'").fetchone()
        assert row["symbol"] == "2330"
        assert row["side"] == "buy"
        assert row["status"] == "submitted"


class TestInsertFill:
    def test_inserts_fill(self, conn, repo):
        repo.insert_fill(FillRecord(order_id="o1", qty=500, price=100.5, fee=14.3, tax=0.0))
        row = conn.execute("SELECT * FROM fills WHERE order_id='o1'").fetchone()
        assert row["qty"] == 500
        assert row["fee"] == 14.3


class TestUpdateStatus:
    def test_updates_order_status(self, conn, repo):
        order = OrderRecord(
            order_id="o1", decision_id="d1", broker_order_id="b1",
            symbol="2330", side="buy", qty=1000, price=100.0,
        )
        repo.insert_order(order)
        repo.update_status("o1", "filled")
        row = conn.execute("SELECT status FROM orders WHERE order_id='o1'").fetchone()
        assert row["status"] == "filled"


class TestInsertOrderEvent:
    def test_inserts_event(self, conn, repo):
        repo.insert_order_event(
            order_id="o1", event_type="status_change",
            from_status="submitted", to_status="filled",
            source="broker", reason_code=None, payload={"detail": "ok"},
        )
        row = conn.execute("SELECT * FROM order_events").fetchone()
        assert row["order_id"] == "o1"
        assert row["event_type"] == "status_change"


class TestGetFillCosts:
    def test_returns_aggregated_costs(self, conn, repo):
        repo.insert_fill(FillRecord(order_id="o1", qty=500, price=100.0, fee=10.0, tax=5.0))
        repo.insert_fill(FillRecord(order_id="o1", qty=500, price=100.0, fee=10.0, tax=5.0))
        fee, tax = repo.get_fill_costs("o1")
        assert fee == 20.0
        assert tax == 10.0

    def test_returns_zero_when_no_fills(self, repo):
        fee, tax = repo.get_fill_costs("nonexistent")
        assert fee == 0.0
        assert tax == 0.0
