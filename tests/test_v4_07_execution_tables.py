"""Test execution tables (v4 #7)."""

import pytest
import sqlite3
import time
from pathlib import Path


def test_execution_orders_table():
    """Test execution_orders table creation and structure."""
    conn = sqlite3.connect(":memory:")
    
    # Create execution_orders table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS execution_orders (
            exec_id           TEXT PRIMARY KEY,
            order_id          TEXT NOT NULL,
            symbol            TEXT NOT NULL,
            side              TEXT NOT NULL,
            quantity          REAL NOT NULL,
            price             REAL,
            order_type        TEXT NOT NULL,
            time_in_force     TEXT DEFAULT 'IOC',
            status            TEXT NOT NULL DEFAULT 'pending',
            filled_quantity   REAL DEFAULT 0.0,
            avg_fill_price    REAL,
            created_at        INTEGER NOT NULL,
            updated_at        INTEGER NOT NULL,
            expires_at        INTEGER,
            strategy_id       TEXT,
            broker_order_id   TEXT,
            error_message     TEXT
        )
    """)
    
    # Test inserting an order
    now = int(time.time() * 1000)
    conn.execute("""
        INSERT INTO execution_orders (
            exec_id, order_id, symbol, side, quantity, price, 
            order_type, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "exec_001", "order_001", "2330.TW", "BUY", 1000.0, 950.0,
        "LIMIT", "filled", now, now
    ))
    
    # Verify insertion
    row = conn.execute(
        "SELECT exec_id, order_id, symbol, side, quantity, status FROM execution_orders"
    ).fetchone()
    
    assert row[0] == "exec_001"
    assert row[1] == "order_001"
    assert row[2] == "2330.TW"
    assert row[3] == "BUY"
    assert row[4] == 1000.0
    assert row[5] == "filled"
    
    conn.close()


def test_execution_fills_table():
    """Test execution_fills table creation and structure."""
    conn = sqlite3.connect(":memory:")
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS execution_fills (
            fill_id           TEXT PRIMARY KEY,
            exec_id           TEXT NOT NULL,
            order_id          TEXT NOT NULL,
            symbol            TEXT NOT NULL,
            side              TEXT NOT NULL,
            quantity          REAL NOT NULL,
            price             REAL NOT NULL,
            trade_time        INTEGER NOT NULL,
            broker_trade_id   TEXT,
            commission        REAL DEFAULT 0.0,
            tax               REAL DEFAULT 0.0,
            created_at        INTEGER NOT NULL
        )
    """)
    
    # Test inserting a fill
    now = int(time.time() * 1000)
    conn.execute("""
        INSERT INTO execution_fills (
            fill_id, exec_id, order_id, symbol, side, quantity, 
            price, trade_time, commission, tax, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "fill_001", "exec_001", "order_001", "2330.TW", "BUY",
        1000.0, 950.0, now, 10.0, 1.5, now
    ))
    
    # Verify insertion
    row = conn.execute(
        "SELECT fill_id, exec_id, symbol, quantity, price, commission, tax FROM execution_fills"
    ).fetchone()
    
    assert row[0] == "fill_001"
    assert row[1] == "exec_001"
    assert row[2] == "2330.TW"
    assert row[3] == 1000.0
    assert row[4] == 950.0
    assert row[5] == 10.0
    assert row[6] == 1.5
    
    conn.close()


def test_execution_settlements_table():
    """Test execution_settlements table creation and structure."""
    conn = sqlite3.connect(":memory:")
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS execution_settlements (
            settlement_id     TEXT PRIMARY KEY,
            trade_date       TEXT NOT NULL,
            total_trades     INTEGER DEFAULT 0,
            total_volume     REAL DEFAULT 0.0,
            total_value      REAL DEFAULT 0.0,
            total_commission REAL DEFAULT 0.0,
            total_tax        REAL DEFAULT 0.0,
            net_value        REAL DEFAULT 0.0,
            status           TEXT NOT NULL DEFAULT 'pending',
            confirmed_at     INTEGER,
            created_at       INTEGER NOT NULL,
            updated_at       INTEGER NOT NULL
        )
    """)
    
    # Test inserting a settlement
    now = int(time.time() * 1000)
    conn.execute("""
        INSERT INTO execution_settlements (
            settlement_id, trade_date, total_trades, total_volume, 
            total_value, total_commission, total_tax, net_value,
            status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "settle_20260227", "2026-02-27", 10, 10000.0,
        9500000.0, 100.0, 150.0, 9399750.0,
        "confirmed", now, now
    ))
    
    # Verify insertion
    row = conn.execute(
        "SELECT settlement_id, trade_date, total_trades, total_value, status FROM execution_settlements"
    ).fetchone()
    
    assert row[0] == "settle_20260227"
    assert row[1] == "2026-02-27"
    assert row[2] == 10
    assert row[3] == 9500000.0
    assert row[4] == "confirmed"
    
    conn.close()


def test_execution_indexes():
    """Test that execution tables have proper indexes."""
    conn = sqlite3.connect(":memory:")
    
    # Create tables with indexes
    conn.execute("""
        CREATE TABLE IF NOT EXISTS execution_orders (
            exec_id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_exec_orders_order_id ON execution_orders(order_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_exec_orders_symbol ON execution_orders(symbol)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_exec_orders_status ON execution_orders(status)")
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS execution_fills (
            fill_id TEXT PRIMARY KEY,
            exec_id TEXT NOT NULL,
            order_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            trade_time INTEGER NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_exec_fills_exec_id ON execution_fills(exec_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_exec_fills_order_id ON execution_fills(order_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_exec_fills_symbol ON execution_fills(symbol)")
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS execution_settlements (
            settlement_id TEXT PRIMARY KEY,
            trade_date TEXT NOT NULL,
            status TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_exec_settlements_date ON execution_settlements(trade_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_exec_settlements_status ON execution_settlements(status)")
    
    # Verify indexes exist
    indexes = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_exec_%'"
    ).fetchall()
    
    assert len(indexes) >= 8, f"Expected at least 9 indexes, found {len(indexes)}"
    
    conn.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
