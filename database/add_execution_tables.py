#!/usr/bin/env python3
"""Add execution tables to existing database (v4 #7: Execution tables 方案A).

This script adds execution tracking tables to the existing database schema:
- execution_orders: Order execution tracking
- execution_fills: Individual fill records
- execution_settlements: Daily settlement records

Usage:
    python3 database/add_execution_tables.py [--dry-run]
"""

import sqlite3
import sys
import argparse
from pathlib import Path


def get_db_path(db_name: str) -> Path:
    """Get database path."""
    base_dir = Path(__file__).parent.parent
    return base_dir / "data" / "sqlite" / f"{db_name}.db"


def add_execution_tables(conn: sqlite3.Connection, db_name: str) -> None:
    """Add execution tables to the database."""
    print(f"Adding execution tables to {db_name}...")
    
    # execution_orders: Track order execution status
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
            
            -- Execution status
            status            TEXT NOT NULL DEFAULT 'pending',
            filled_quantity   REAL DEFAULT 0.0,
            avg_fill_price    REAL,
            
            -- Timestamps
            created_at        INTEGER NOT NULL,
            updated_at        INTEGER NOT NULL,
            expires_at        INTEGER,
            
            -- Metadata
            strategy_id       TEXT,
            broker_order_id   TEXT,
            error_message     TEXT,
            
            FOREIGN KEY (order_id) REFERENCES orders(order_id)
        )
    """)
    
    # Create indexes for execution_orders
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_exec_orders_order_id ON execution_orders(order_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_exec_orders_symbol ON execution_orders(symbol)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_exec_orders_status ON execution_orders(status)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_exec_orders_created_at ON execution_orders(created_at)
    """)
    
    # execution_fills: Individual fill records
    conn.execute("""
        CREATE TABLE IF NOT EXISTS execution_fills (
            fill_id           TEXT PRIMARY KEY,
            exec_id           TEXT NOT NULL,
            order_id          TEXT NOT NULL,
            symbol            TEXT NOT NULL,
            side              TEXT NOT NULL,
            quantity          REAL NOT NULL,
            price             REAL NOT NULL,
            
            -- Fill details
            trade_time        INTEGER NOT NULL,
            broker_trade_id   TEXT,
            
            -- Fees
            commission        REAL DEFAULT 0.0,
            tax               REAL DEFAULT 0.0,
            
            created_at        INTEGER NOT NULL,
            
            FOREIGN KEY (exec_id) REFERENCES execution_orders(exec_id),
            FOREIGN KEY (order_id) REFERENCES orders(order_id)
        )
    """)
    
    # Create indexes for execution_fills
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_exec_fills_exec_id ON execution_fills(exec_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_exec_fills_order_id ON execution_fills(order_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_exec_fills_symbol ON execution_fills(symbol)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_exec_fills_trade_time ON execution_fills(trade_time)
    """)
    
    # execution_settlements: Daily settlement records
    conn.execute("""
        CREATE TABLE IF NOT EXISTS execution_settlements (
            settlement_id     TEXT PRIMARY KEY,
            trade_date       TEXT NOT NULL,
            
            -- Summary
            total_trades     INTEGER DEFAULT 0,
            total_volume     REAL DEFAULT 0.0,
            total_value      REAL DEFAULT 0.0,
            
            -- Fees
            total_commission REAL DEFAULT 0.0,
            total_tax        REAL DEFAULT 0.0,
            net_value        REAL DEFAULT 0.0,
            
            -- Status
            status           TEXT NOT NULL DEFAULT 'pending',
            confirmed_at     INTEGER,
            
            created_at       INTEGER NOT NULL,
            updated_at       INTEGER NOT NULL
        )
    """)
    
    # Create indexes for execution_settlements
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_exec_settlements_date ON execution_settlements(trade_date)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_exec_settlements_status ON execution_settlements(status)
    """)
    
    conn.commit()
    print(f"✓ Added execution tables to {db_name}")


def verify_tables(conn: sqlite3.Connection) -> None:
    """Verify tables were created."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'execution_%'"
    )
    tables = [row[0] for row in cursor.fetchall()]
    print(f"\nExecution tables in database: {tables}")
    assert len(tables) == 3, f"Expected 3 execution tables, found {len(tables)}"
    print("✓ All execution tables verified")


def main():
    parser = argparse.ArgumentParser(description="Add execution tables to database")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    args = parser.parse_args()
    
    dbs = [
        ("ticks.db", "ticks"),
        ("trades.db", "trades")
    ]
    
    for db_file, db_name in dbs:
        db_path = get_db_path(db_name)
        
        if not db_path.exists():
            print(f"⚠ Database {db_name} not found at {db_path}, skipping...")
            continue
            
        print(f"\nProcessing {db_name}...")
        
        if args.dry_run:
            print(f"[DRY RUN] Would add execution tables to {db_name}")
            continue
            
        conn = sqlite3.connect(str(db_path))
        
        try:
            add_execution_tables(conn, db_name)
            verify_tables(conn)
        finally:
            conn.close()
    
    print("\n✅ Execution tables migration complete!")


if __name__ == "__main__":
    main()
