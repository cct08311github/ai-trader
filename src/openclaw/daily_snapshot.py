# src/openclaw/daily_snapshot.py
"""daily_snapshot.py — 每日 NAV 快照寫入 daily_nav 表 [Issue #282]

在 EOD 收盤後（eod_prices 已入庫）計算：
  cash              = initial_capital + cumulative_realized_pnl - open_position_book_value
  unrealized_pnl    = Σ( (eod_close - avg_price) * qty ) for all open positions
  nav               = cash + Σ( eod_close * qty )
  realized_pnl_cumulative = Σ realized_pnl from fills (all time)

呼叫方式：
  from openclaw.daily_snapshot import write_nav_snapshot
  write_nav_snapshot(conn, trade_date="2024-01-02", initial_capital=1_000_000.0)
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def _ensure_daily_nav_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_nav (
            trade_date              TEXT PRIMARY KEY,
            nav                     REAL NOT NULL,
            cash                    REAL NOT NULL,
            unrealized_pnl          REAL NOT NULL,
            realized_pnl_cumulative REAL NOT NULL,
            recorded_at             INTEGER NOT NULL  -- epoch ms
        )
    """)


def _calc_cash_and_realized(
    conn: sqlite3.Connection, initial_capital: float
) -> tuple[float, float]:
    """
    Returns (cash, realized_pnl_cumulative).

    Cash accounting:
        cash = initial_capital + sell_proceeds - buy_costs

    Realized PnL:
        realized = sell_proceeds - cost_basis_of_sold_shares
        cost_basis_of_sold = buy_costs - open_position_book_value

    This correctly handles open positions: unrealized gain is NOT counted
    as realized profit until shares are actually sold.
    """
    sell_proceeds = float(conn.execute(
        """SELECT COALESCE(SUM(f.price * f.qty - f.fee - f.tax), 0.0)
           FROM fills f JOIN orders o ON f.order_id = o.order_id
           WHERE o.side = 'sell'"""
    ).fetchone()[0] or 0.0)

    buy_costs = float(conn.execute(
        """SELECT COALESCE(SUM(f.price * f.qty + f.fee), 0.0)
           FROM fills f JOIN orders o ON f.order_id = o.order_id
           WHERE o.side = 'buy'"""
    ).fetchone()[0] or 0.0)

    open_book = float(conn.execute(
        "SELECT COALESCE(SUM(avg_price * quantity), 0.0) FROM positions WHERE quantity > 0"
    ).fetchone()[0] or 0.0)

    cash = initial_capital + sell_proceeds - buy_costs
    # cost_basis_of_what_was_sold = total_buy_costs - what_is_still_held
    cost_basis_of_sold = buy_costs - open_book
    realized = sell_proceeds - cost_basis_of_sold

    return cash, realized


def _calc_positions_nav(
    conn: sqlite3.Connection, trade_date: str
) -> tuple[float, float]:
    """
    Returns (position_market_value, unrealized_pnl) using eod_prices close.
    Falls back to avg_price if eod_prices not available for a symbol.
    """
    rows = conn.execute(
        "SELECT symbol, quantity, avg_price FROM positions WHERE quantity > 0"
    ).fetchall()

    market_value = 0.0
    unrealized = 0.0
    for sym, qty, avg_price in rows:
        close_row = conn.execute(
            "SELECT close FROM eod_prices WHERE symbol=? AND trade_date=?",
            (sym, trade_date),
        ).fetchone()
        close = float(close_row[0]) if close_row and close_row[0] else float(avg_price)
        market_value += close * qty
        unrealized += (close - avg_price) * qty

    return market_value, unrealized


def write_nav_snapshot(
    conn: sqlite3.Connection,
    trade_date: str,
    initial_capital: float,
    *,
    overwrite: bool = False,
) -> dict:
    """計算並寫入 daily_nav 快照，回傳 dict（nav, cash, unrealized_pnl, realized_pnl_cumulative）。

    Args:
        conn:             SQLite 連線（需 rw）
        trade_date:       "YYYY-MM-DD"
        initial_capital:  初始資金（通常從 config/capital.json 讀取）
        overwrite:        True = 已存在時覆蓋；False = 跳過（冪等）

    Returns:
        dict with keys: trade_date, nav, cash, unrealized_pnl, realized_pnl_cumulative
    """
    _ensure_daily_nav_table(conn)

    if not overwrite:
        existing = conn.execute(
            "SELECT 1 FROM daily_nav WHERE trade_date=?", (trade_date,)
        ).fetchone()
        if existing:
            log.debug("daily_nav: %s 已存在，跳過（overwrite=False）", trade_date)
            row = conn.execute(
                "SELECT nav, cash, unrealized_pnl, realized_pnl_cumulative FROM daily_nav WHERE trade_date=?",
                (trade_date,),
            ).fetchone()
            return {
                "trade_date": trade_date,
                "nav": row[0], "cash": row[1],
                "unrealized_pnl": row[2], "realized_pnl_cumulative": row[3],
            }

    cash, realized_cumulative = _calc_cash_and_realized(conn, initial_capital)
    position_market_value, unrealized_pnl = _calc_positions_nav(conn, trade_date)
    nav = cash + position_market_value

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    conn.execute(
        """
        INSERT OR REPLACE INTO daily_nav
            (trade_date, nav, cash, unrealized_pnl, realized_pnl_cumulative, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (trade_date, round(nav, 2), round(cash, 2),
         round(unrealized_pnl, 2), round(realized_cumulative, 2), now_ms),
    )
    conn.commit()

    log.info(
        "daily_nav: %s  NAV=%.0f  cash=%.0f  unrealized=%.0f  realized_cum=%.0f",
        trade_date, nav, cash, unrealized_pnl, realized_cumulative,
    )
    return {
        "trade_date": trade_date,
        "nav": round(nav, 2),
        "cash": round(cash, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "realized_pnl_cumulative": round(realized_cumulative, 2),
    }


def get_nav_history(
    conn: sqlite3.Connection, days: int = 60
) -> list[dict]:
    """回傳最近 days 天的 daily_nav 記錄（由舊至新）。表不存在時回傳空清單。"""
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_nav'"
    ).fetchone()
    if not table_exists:
        return []
    rows = conn.execute(
        """
        SELECT trade_date, nav, cash, unrealized_pnl, realized_pnl_cumulative
        FROM daily_nav
        ORDER BY trade_date DESC
        LIMIT ?
        """,
        (days,),
    ).fetchall()
    return [
        {
            "trade_date": r[0], "nav": r[1], "cash": r[2],
            "unrealized_pnl": r[3], "realized_pnl_cumulative": r[4],
        }
        for r in reversed(rows)
    ]
