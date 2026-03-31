"""Realized PnL engine — average-cost method.

Responsibilities:
  - Compute avg cost basis from buy fills (per symbol)
  - On sell fill: calculate realized PnL, upsert to daily_pnl_summary
  - Sync positions table from orders+fills
  - Helper: read today/monthly PnL for API responses

Schema dependencies:
  orders  (order_id, symbol, side, status)
  fills   (order_id, qty, price, fee, tax)
  daily_pnl_summary  (trade_date PK, realized_pnl, total_trades, ...)
  positions          (symbol PK, quantity, avg_price, ...)

All SQL is delegated to PnLRepository.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Tuple

from openclaw.repositories.pnl_repository import PnLRepository

log = logging.getLogger(__name__)

# ── Cost basis ──────────────────────────────────────────────────────────────


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None

def get_avg_cost(conn: sqlite3.Connection, symbol: str) -> Tuple[float, int]:
    """Return (avg_buy_price, net_qty) for a symbol from orders+fills.

    Uses all historical buy fills minus sold qty to reflect current holding.
    Returns (0.0, 0) if no position.
    """
    return PnLRepository(conn).get_avg_cost(symbol)


# ── Sell fill handler ────────────────────────────────────────────────────────

def on_sell_filled(
    conn: sqlite3.Connection,
    *,
    symbol: str,
    sell_qty: int,
    sell_price: float,
    sell_fee: float,
    sell_tax: float,
    trade_date: str,           # "YYYY-MM-DD" in TWN time
) -> float:
    """Compute realized PnL for a sell fill and upsert into daily_pnl_summary.

    PnL formula (avg-cost, fee-exclusive on buy side):
      realized_pnl = (sell_price - avg_cost) * sell_qty - sell_fee - sell_tax

    Returns the realized_pnl value.
    """
    repo = PnLRepository(conn)
    avg_cost, _ = repo.get_avg_cost(symbol)
    realized_pnl = (sell_price - avg_cost) * sell_qty - sell_fee - sell_tax
    repo.upsert_daily_pnl(trade_date, delta_realized=realized_pnl, delta_trades=1)
    return realized_pnl


def _upsert_daily_pnl(
    conn: sqlite3.Connection,
    trade_date: str,
    delta_realized: float,
    delta_trades: int,
) -> None:
    """Add delta to daily_pnl_summary for trade_date (upsert)."""
    PnLRepository(conn).upsert_daily_pnl(trade_date, delta_realized, delta_trades)


def _compute_rolling_win_rate(
    conn: sqlite3.Connection,
    up_to_date: str,
    today_pnl: float,
) -> float:
    """Rolling win rate: % of trading days with realized_pnl > 0 (last 20 days)."""
    return PnLRepository(conn).compute_rolling_win_rate(up_to_date, today_pnl)


# ── Positions table sync ─────────────────────────────────────────────────────

def sync_positions_table(conn: sqlite3.Connection) -> None:
    """Recompute positions table from orders+fills (net qty, avg_cost).

    Removes closed positions (net_qty <= 0).
    Does NOT update current_price or unrealized_pnl (requires live feed).
    """
    PnLRepository(conn).sync_positions()


def refresh_current_prices(conn: sqlite3.Connection) -> int:
    """Update positions.current_price and unrealized_pnl from latest eod_prices."""
    return PnLRepository(conn).refresh_current_prices()


def _backfill_high_water_mark(conn: sqlite3.Connection) -> None:
    """Set high_water_mark from eod_prices max(close) since entry for positions missing it."""
    PnLRepository(conn).backfill_high_water_mark()


# ── API helpers ──────────────────────────────────────────────────────────────

def get_today_pnl(conn: sqlite3.Connection, trade_date: str) -> float:
    """Return today's realized_pnl from daily_pnl_summary."""
    return PnLRepository(conn).get_today_pnl(trade_date)


def get_monthly_pnl(conn: sqlite3.Connection, month_prefix: str) -> float:
    """Return sum of realized_pnl for month_prefix e.g. '2026-03'."""
    return PnLRepository(conn).get_monthly_pnl(month_prefix)


def get_overall_win_rate(conn: sqlite3.Connection) -> float:
    """Win rate = days with realized_pnl > 0 / total days with trades."""
    return PnLRepository(conn).get_overall_win_rate()


def get_equity_curve(conn: sqlite3.Connection, days: int, start_equity: float) -> list:
    """Build equity curve from daily_pnl_summary (realized_pnl cumsum)."""
    return PnLRepository(conn).get_equity_curve(days, start_equity)
