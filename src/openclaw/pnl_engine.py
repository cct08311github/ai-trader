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
"""
from __future__ import annotations

import datetime
import sqlite3
from typing import Tuple

# ── Cost basis ──────────────────────────────────────────────────────────────

def get_avg_cost(conn: sqlite3.Connection, symbol: str) -> Tuple[float, int]:
    """Return (avg_buy_price, net_qty) for a symbol from orders+fills.

    Uses all historical buy fills minus sold qty to reflect current holding.
    Returns (0.0, 0) if no position.
    """
    row = conn.execute(
        """
        SELECT
          SUM(CASE WHEN o.side='buy'  THEN f.qty ELSE 0 END)
        - SUM(CASE WHEN o.side='sell' THEN f.qty ELSE 0 END) AS net_qty,
          ROUND(
            SUM(CASE WHEN o.side='buy' THEN f.qty * f.price ELSE 0 END)
            / MAX(SUM(CASE WHEN o.side='buy' THEN f.qty ELSE 0 END), 1),
          4) AS avg_price
        FROM orders o
        JOIN fills f ON f.order_id = o.order_id
        WHERE UPPER(o.symbol) = UPPER(?)
          AND o.status IN ('filled', 'partially_filled')
        """,
        (symbol,)
    ).fetchone()
    if row and row["net_qty"] and row["net_qty"] > 0:
        return float(row["avg_price"]), int(row["net_qty"])
    return 0.0, 0


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
    avg_cost, _ = get_avg_cost(conn, symbol)
    realized_pnl = (sell_price - avg_cost) * sell_qty - sell_fee - sell_tax
    _upsert_daily_pnl(conn, trade_date, delta_realized=realized_pnl, delta_trades=1)
    return realized_pnl


def _upsert_daily_pnl(
    conn: sqlite3.Connection,
    trade_date: str,
    delta_realized: float,
    delta_trades: int,
) -> None:
    """Add delta to daily_pnl_summary for trade_date (upsert)."""
    existing = conn.execute(
        "SELECT realized_pnl, total_trades FROM daily_pnl_summary WHERE trade_date=?",
        (trade_date,)
    ).fetchone()

    if existing:
        new_pnl   = (existing["realized_pnl"] or 0.0) + delta_realized
        new_total = (existing["total_trades"] or 0) + delta_trades
        win_rate  = _compute_rolling_win_rate(conn, trade_date, new_pnl)
        conn.execute(
            """UPDATE daily_pnl_summary
               SET realized_pnl=?, total_pnl=?, total_trades=?,
                   rolling_win_rate=?
               WHERE trade_date=?""",
            (round(new_pnl, 2), round(new_pnl, 2), new_total, win_rate, trade_date)
        )
    else:
        win_rate = 1.0 if delta_realized > 0 else 0.0
        conn.execute(
            """INSERT INTO daily_pnl_summary
               (trade_date, realized_pnl, unrealized_pnl, total_pnl,
                total_trades, rolling_drawdown, consecutive_losses,
                losing_streak_days, rolling_win_rate)
               VALUES (?,?,0.0,?,?,0.0,?,0,?)""",
            (trade_date, round(delta_realized, 2), round(delta_realized, 2),
             delta_trades,
             1 if delta_realized < 0 else 0,
             win_rate)
        )
    conn.commit()


def _compute_rolling_win_rate(
    conn: sqlite3.Connection,
    up_to_date: str,
    today_pnl: float,
) -> float:
    """Rolling win rate: % of trading days with realized_pnl > 0 (last 20 days)."""
    rows = conn.execute(
        """SELECT realized_pnl FROM daily_pnl_summary
           WHERE trade_date < ?
           ORDER BY trade_date DESC LIMIT 19""",
        (up_to_date,)
    ).fetchall()
    all_pnls = [r["realized_pnl"] for r in rows] + [today_pnl]
    if not all_pnls:
        return 0.0
    wins = sum(1 for p in all_pnls if p > 0)
    return round(wins / len(all_pnls), 4)


# ── Positions table sync ─────────────────────────────────────────────────────

def sync_positions_table(conn: sqlite3.Connection) -> None:
    """Recompute positions table from orders+fills (net qty, avg_cost).

    Removes closed positions (net_qty <= 0).
    Does NOT update current_price or unrealized_pnl (requires live feed).
    """
    conn.execute("DELETE FROM positions")
    conn.execute(
        """
        INSERT INTO positions (symbol, quantity, avg_price)
        SELECT
          symbol,
          net_qty AS quantity,
          ROUND(
            SUM(CASE WHEN side='buy' THEN fill_amount ELSE 0 END)
            / MAX(SUM(CASE WHEN side='buy' THEN fill_qty ELSE 0 END), 1),
          4) AS avg_price
        FROM (
          SELECT o.symbol, o.side,
                 SUM(f.qty)         AS fill_qty,
                 SUM(f.qty*f.price) AS fill_amount,
                 SUM(CASE WHEN o.side='buy'  THEN f.qty ELSE 0 END)
               - SUM(CASE WHEN o.side='sell' THEN f.qty ELSE 0 END) AS net_qty
          FROM orders o
          JOIN fills f ON f.order_id=o.order_id
          WHERE o.status IN ('filled','partially_filled')
          GROUP BY o.symbol, o.side
        )
        GROUP BY symbol
        HAVING net_qty > 0
        """
    )
    conn.commit()


# ── API helpers ──────────────────────────────────────────────────────────────

def get_today_pnl(conn: sqlite3.Connection, trade_date: str) -> float:
    """Return today's realized_pnl from daily_pnl_summary."""
    row = conn.execute(
        "SELECT realized_pnl FROM daily_pnl_summary WHERE trade_date=?",
        (trade_date,)
    ).fetchone()
    return float(row["realized_pnl"]) if row and row["realized_pnl"] is not None else 0.0


def get_monthly_pnl(conn: sqlite3.Connection, month_prefix: str) -> float:
    """Return sum of realized_pnl for month_prefix e.g. '2026-03'."""
    row = conn.execute(
        "SELECT SUM(realized_pnl) AS total FROM daily_pnl_summary WHERE trade_date LIKE ?",
        (f"{month_prefix}%",)
    ).fetchone()
    return float(row["total"]) if row and row["total"] is not None else 0.0


def get_overall_win_rate(conn: sqlite3.Connection) -> float:
    """Win rate = days with realized_pnl > 0 / total days with trades."""
    row = conn.execute(
        """SELECT
             SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) AS wins,
             COUNT(1) AS total
           FROM daily_pnl_summary
           WHERE total_trades > 0"""
    ).fetchone()
    if row and row["total"] and row["total"] > 0:
        return round(float(row["wins"] or 0) / float(row["total"]), 4)
    return 0.0


def get_equity_curve(conn: sqlite3.Connection, days: int, start_equity: float) -> list:
    """Build equity curve from daily_pnl_summary (realized_pnl cumsum)."""
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute(
        """SELECT trade_date, realized_pnl
           FROM daily_pnl_summary
           WHERE trade_date >= ?
           ORDER BY trade_date ASC""",
        (cutoff,)
    ).fetchall()
    series = []
    equity = start_equity
    for r in rows:
        equity += float(r["realized_pnl"] or 0)
        series.append({"date": r["trade_date"], "equity": round(equity, 2)})
    return series
