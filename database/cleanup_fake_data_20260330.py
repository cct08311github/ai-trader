#!/usr/bin/env python3
"""Cleanup fake/dead NAV data and stale stress-test fills from the database.

This migration addresses Issue #511:
- Removes fabricated daily_nav entries (2026-03-19 ~ 2026-03-24)
  that were manually inserted to trigger DEEP SUSPEND
- Removes fabricated daily_pnl_summary entries (2026-03-06, 09, 16)
- Removes 2382 stress-test fill/order residuals (100 rows of filled sells
  from 2026-03-25, unrelated to real 1303 holding)
- Corrects positions.current_price for symbol 1303 using latest eod_prices

Usage:
    python3 database/cleanup_fake_data_20260330.py [--dry-run] [--db-path <path>]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def get_default_db_path() -> Path:
    base = Path(__file__).parent.parent
    return base / "data" / "sqlite" / "trades.db"


def cleanup(conn: sqlite3.Connection, dry_run: bool = True) -> dict:
    """Execute all cleanup steps. Returns a summary dict."""
    # ── Step 1: Remove fake daily_nav entries ────────────────────────────────
    fake_nav_dates = ("2026-03-19", "2026-03-20", "2026-03-23", "2026-03-24")
    cur = conn.execute(
        "SELECT COUNT(*) FROM daily_nav WHERE trade_date IN ("
        + ",".join("?" * len(fake_nav_dates))
        + ")",
        fake_nav_dates,
    )
    nav_count = cur.fetchone()[0]
    if nav_count and not dry_run:
        conn.execute(
            "DELETE FROM daily_nav WHERE trade_date IN ("
            + ",".join("?" * len(fake_nav_dates))
            + ")",
            fake_nav_dates,
        )

    # ── Step 2: Remove fake daily_pnl_summary entries ────────────────────────
    fake_pnl_dates = ("2026-03-06", "2026-03-09", "2026-03-16")
    cur = conn.execute(
        "SELECT COUNT(*) FROM daily_pnl_summary WHERE trade_date IN ("
        + ",".join("?" * len(fake_pnl_dates))
        + ")",
        fake_pnl_dates,
    )
    pnl_count = cur.fetchone()[0]
    if pnl_count and not dry_run:
        conn.execute(
            "DELETE FROM daily_pnl_summary WHERE trade_date IN ("
            + ",".join("?" * len(fake_pnl_dates))
            + ")",
            fake_pnl_dates,
        )

    # ── Step 3: Remove 2382 stress-test fills & orders ─────────────────────
    cur = conn.execute(
        "SELECT COUNT(*) FROM fills f JOIN orders o ON f.order_id = o.order_id WHERE o.symbol='2382'"
    )
    fill_count = cur.fetchone()[0]
    if fill_count and not dry_run:
        conn.execute(
            "DELETE FROM fills WHERE order_id IN (SELECT order_id FROM orders WHERE symbol='2382')"
        )
        conn.execute("DELETE FROM orders WHERE symbol='2382'")

    # ── Step 4: Fix positions.current_price for symbol 1303 ─────────────────
    cur = conn.execute(
        "SELECT close FROM eod_prices WHERE symbol='1303' ORDER BY trade_date DESC LIMIT 1"
    )
    row = cur.fetchone()
    close = float(row[0]) if row and row[0] else None
    if close:
        cur = conn.execute("SELECT avg_price, quantity FROM positions WHERE symbol='1303'")
        pos_row = cur.fetchone()
        if pos_row:
            avg_price, qty = float(pos_row[0]), int(pos_row[1])
            unreal = round((close - avg_price) * qty, 2)
            if not dry_run:
                conn.execute(
                    "UPDATE positions SET current_price=?, unrealized_pnl=? WHERE symbol='1303'",
                    (close, unreal),
                )

    # ── Step 5: Re-write daily_nav for latest eod date with corrected data ───
    from openclaw.daily_snapshot import write_nav_snapshot
    from openclaw.config_manager import get_config

    _initial = get_config().capital().total_capital_twd
    cur = conn.execute("SELECT MAX(trade_date) FROM eod_prices")
    latest_eod = cur.fetchone()[0]
    if latest_eod and not dry_run:
        write_nav_snapshot(conn, trade_date=latest_eod, initial_capital=_initial, overwrite=True)

    return {
        "daily_nav_removed": nav_count,
        "daily_pnl_summary_removed": pnl_count,
        "2382_fills_removed": fill_count,
        "1303_close_price": close,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Cleanup fake/dead data from trades.db")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")
    parser.add_argument("--db-path", default=None, help="Path to trades.db (default: project default)")
    args = parser.parse_args()

    db_path = Path(args.db_path) if args.db_path else get_default_db_path()
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    print(f"Connecting to: {db_path}")
    print(f"Dry-run: {args.dry_run}")
    print("-" * 50)

    # Add src to path for imports
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

    result = cleanup(conn, dry_run=args.dry_run)

    if not args.dry_run:
        conn.commit()

    conn.close()

    print("Cleanup summary:")
    print(f"  daily_nav rows removed:       {result['daily_nav_removed']}")
    print(f"  daily_pnl_summary rows removed: {result['daily_pnl_summary_removed']}")
    print(f"  2382 fills/orders removed:  {result['2382_fills_removed']}")
    print(f"  1303 current_price set to:  {result['1303_close_price']}")
    print()
    print("NOTE: daily_nav snapshot re-written for latest eod date.")
    print("DEEP SUSPEND guard will now return RISK_DEEP_SUSPEND_INSUFFICIENT_DATA (normal).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
