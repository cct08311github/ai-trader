"""pnl_repository.py — Data access for P&L computation tables.

Encapsulates all SQL operations on ``daily_pnl_summary``, ``positions``
(sync/backfill), and the cost-basis query across ``orders+fills``.
"""
from __future__ import annotations

import datetime
import logging
import sqlite3
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


class PnLRepository:
    """Encapsulates daily_pnl_summary + cost-basis + positions sync."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── Cost basis ──────────────────────────────────────────────────────

    def get_avg_cost(self, symbol: str) -> Tuple[float, int]:
        """Return (avg_buy_price, net_qty) for a symbol from orders+fills."""
        row = self._conn.execute(
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
            (symbol,),
        ).fetchone()
        if row and row["net_qty"] and row["net_qty"] > 0:
            return float(row["avg_price"]), int(row["net_qty"])
        return 0.0, 0

    # ── Daily PnL summary ──────────────────────────────────────────────

    def upsert_daily_pnl(
        self,
        trade_date: str,
        delta_realized: float,
        delta_trades: int,
    ) -> None:
        """Add delta to daily_pnl_summary for trade_date (upsert)."""
        existing = self._conn.execute(
            "SELECT realized_pnl, total_trades FROM daily_pnl_summary WHERE trade_date=?",
            (trade_date,),
        ).fetchone()

        if existing:
            new_pnl = (existing["realized_pnl"] or 0.0) + delta_realized
            new_total = (existing["total_trades"] or 0) + delta_trades
            win_rate = self.compute_rolling_win_rate(trade_date, new_pnl)
            self._conn.execute(
                """UPDATE daily_pnl_summary
                   SET realized_pnl=?, total_pnl=?, total_trades=?,
                       rolling_win_rate=?
                   WHERE trade_date=?""",
                (round(new_pnl, 2), round(new_pnl, 2), new_total, win_rate, trade_date),
            )
        else:
            win_rate = 1.0 if delta_realized > 0 else 0.0
            self._conn.execute(
                """INSERT INTO daily_pnl_summary
                   (trade_date, realized_pnl, unrealized_pnl, total_pnl,
                    total_trades, rolling_drawdown, consecutive_losses,
                    losing_streak_days, rolling_win_rate)
                   VALUES (?,?,0.0,?,?,0.0,?,0,?)""",
                (
                    trade_date,
                    round(delta_realized, 2),
                    round(delta_realized, 2),
                    delta_trades,
                    1 if delta_realized < 0 else 0,
                    win_rate,
                ),
            )
        self._conn.commit()

    def compute_rolling_win_rate(
        self,
        up_to_date: str,
        today_pnl: float,
    ) -> float:
        """Rolling win rate: % of trading days with realized_pnl > 0 (last 20 days)."""
        rows = self._conn.execute(
            """SELECT realized_pnl FROM daily_pnl_summary
               WHERE trade_date < ?
               ORDER BY trade_date DESC LIMIT 19""",
            (up_to_date,),
        ).fetchall()
        all_pnls = [r["realized_pnl"] for r in rows] + [today_pnl]
        if not all_pnls:
            return 0.0
        wins = sum(1 for p in all_pnls if p > 0)
        return round(wins / len(all_pnls), 4)

    # ── Positions sync ─────────────────────────────────────────────────

    def sync_positions(self) -> None:
        """Recompute positions table from orders+fills (net qty, avg_cost)."""
        self._conn.execute("DELETE FROM positions")
        if _table_exists(self._conn, "position_quarantine"):
            self._conn.execute(
                """
                INSERT INTO positions (symbol, quantity, avg_price, entry_trading_day)
                SELECT
                  o.symbol,
                  SUM(CASE WHEN o.side='buy'  THEN f.qty ELSE 0 END)
                - SUM(CASE WHEN o.side='sell' THEN f.qty ELSE 0 END) AS net_qty,
                  ROUND(
                    SUM(CASE WHEN o.side='buy' THEN f.qty * f.price ELSE 0 END)
                    / MAX(SUM(CASE WHEN o.side='buy' THEN f.qty ELSE 0 END), 1),
                  4) AS avg_price,
                  MIN(CASE WHEN o.side='buy' THEN date(o.ts_submit) END) AS entry_trading_day
                FROM orders o
                JOIN fills f ON f.order_id = o.order_id
                LEFT JOIN position_quarantine q
                  ON UPPER(q.symbol) = UPPER(o.symbol)
                 AND q.active = 1
                WHERE o.status IN ('filled', 'partially_filled')
                  AND q.symbol IS NULL
                GROUP BY o.symbol
                HAVING net_qty > 0
                """
            )
        else:
            self._conn.execute(
                """
                INSERT INTO positions (symbol, quantity, avg_price, entry_trading_day)
                SELECT
                  o.symbol,
                  SUM(CASE WHEN o.side='buy'  THEN f.qty ELSE 0 END)
                - SUM(CASE WHEN o.side='sell' THEN f.qty ELSE 0 END) AS net_qty,
                  ROUND(
                    SUM(CASE WHEN o.side='buy' THEN f.qty * f.price ELSE 0 END)
                    / MAX(SUM(CASE WHEN o.side='buy' THEN f.qty ELSE 0 END), 1),
                  4) AS avg_price,
                  MIN(CASE WHEN o.side='buy' THEN date(o.ts_submit) END) AS entry_trading_day
                FROM orders o
                JOIN fills f ON f.order_id = o.order_id
                WHERE o.status IN ('filled', 'partially_filled')
                GROUP BY o.symbol
                HAVING net_qty > 0
                """
            )
        self._conn.commit()
        self.backfill_high_water_mark()

    def backfill_high_water_mark(self) -> None:
        """Set high_water_mark from eod_prices max(close) since entry."""
        try:
            self._conn.execute(
                """UPDATE positions SET high_water_mark = (
                     SELECT MAX(e.close) FROM eod_prices e
                     WHERE e.symbol = positions.symbol
                       AND e.trade_date >= COALESCE(positions.entry_trading_day, '2000-01-01')
                   )
                   WHERE high_water_mark IS NULL AND quantity > 0"""
            )
            self._conn.commit()
        except sqlite3.Error as e:
            log.warning("backfill_high_water_mark failed: %s", e)

    # ── API helpers ─────────────────────────────────────────────────────

    def get_today_pnl(self, trade_date: str) -> float:
        row = self._conn.execute(
            "SELECT realized_pnl FROM daily_pnl_summary WHERE trade_date=?",
            (trade_date,),
        ).fetchone()
        return float(row["realized_pnl"]) if row and row["realized_pnl"] is not None else 0.0

    def get_monthly_pnl(self, month_prefix: str) -> float:
        row = self._conn.execute(
            "SELECT SUM(realized_pnl) AS total FROM daily_pnl_summary WHERE trade_date LIKE ?",
            (f"{month_prefix}%",),
        ).fetchone()
        return float(row["total"]) if row and row["total"] is not None else 0.0

    def get_overall_win_rate(self) -> float:
        row = self._conn.execute(
            """SELECT
                 SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) AS wins,
                 COUNT(1) AS total
               FROM daily_pnl_summary
               WHERE total_trades > 0"""
        ).fetchone()
        if row and row["total"] and row["total"] > 0:
            return round(float(row["wins"] or 0) / float(row["total"]), 4)
        return 0.0

    def get_equity_curve(self, days: int, start_equity: float) -> List[dict]:
        cutoff = (
            datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)
        ).strftime("%Y-%m-%d")
        rows = self._conn.execute(
            """SELECT trade_date, realized_pnl
               FROM daily_pnl_summary
               WHERE trade_date >= ?
               ORDER BY trade_date ASC""",
            (cutoff,),
        ).fetchall()
        series = []
        equity = start_equity
        for r in rows:
            equity += float(r["realized_pnl"] or 0)
            series.append({"date": r["trade_date"], "equity": round(equity, 2)})
        return series
