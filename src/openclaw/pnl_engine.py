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


def backfill_high_water_mark(conn: sqlite3.Connection) -> None:
    """Set high_water_mark from eod_prices max(close) since entry for positions missing it."""
    PnLRepository(conn).backfill_high_water_mark()


# keep private alias for backward compat
_backfill_high_water_mark = backfill_high_water_mark


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


def backfill_daily_pnl_summary(conn: sqlite3.Connection) -> int:
    """從 orders+fills 回填 daily_pnl_summary（修復 #630）。

    用途：daily_pnl_summary 為空但 orders/fills 有歷史成交資料時，
    重建每日 PnL 摘要。已存在的日期不會重複累加（冪等）。

    Returns: 回填的賣出筆數。
    """
    repo = PnLRepository(conn)

    # 已有數據的日期 → 跳過（冪等）
    existing_dates = {
        r[0]
        for r in conn.execute("SELECT trade_date FROM daily_pnl_summary").fetchall()
    }

    # 取得所有 filled sell orders，含 fills，按日期排序
    sell_rows = conn.execute(
        """
        SELECT
            date(o.ts_submit) AS trade_date,
            o.symbol,
            f.qty AS fill_qty,
            f.price AS fill_price,
            f.fee,
            f.tax
        FROM orders o
        JOIN fills f ON f.order_id = o.order_id
        WHERE o.side = 'sell'
          AND o.status IN ('filled', 'partially_filled')
        ORDER BY o.ts_submit ASC
        """
    ).fetchall()

    if not sell_rows:
        log.info("[backfill_daily_pnl] No filled sell orders found, nothing to backfill")
        return 0

    count = 0
    for row in sell_rows:
        trade_date = row[0]
        symbol = row[1]
        fill_qty = int(row[2])
        fill_price = float(row[3])
        fee = float(row[4] or 0)
        tax = float(row[5] or 0)

        if trade_date in existing_dates:
            log.debug("[backfill_daily_pnl] %s already in daily_pnl_summary, skip", trade_date)
            continue

        avg_cost, _ = repo.get_avg_cost(symbol)
        if avg_cost <= 0:
            log.warning("[backfill_daily_pnl] %s: no avg_cost, skip sell on %s", symbol, trade_date)
            continue

        realized_pnl = (fill_price - avg_cost) * fill_qty - fee - tax
        repo.upsert_daily_pnl(trade_date, delta_realized=realized_pnl, delta_trades=1)
        existing_dates.add(trade_date)
        count += 1
        log.info(
            "[backfill_daily_pnl] %s %s: realized_pnl=%.2f (fill=%.2f avg=%.2f qty=%d)",
            trade_date, symbol, realized_pnl, fill_price, avg_cost, fill_qty,
        )

    log.info("[backfill_daily_pnl] Done — backfilled %d sell records", count)
    return count
