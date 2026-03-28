"""position_repository.py — Data access for positions table.

Encapsulates all SELECT/INSERT/UPDATE/DELETE on ``positions``,
replacing direct SQL in ticker_watcher.py, pnl_engine.py, etc.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class PositionRecord:
    symbol: str
    quantity: int
    avg_price: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    state: str = "ACTIVE"
    high_water_mark: float = 0.0
    entry_trading_day: Optional[str] = None


class PositionRepository:
    """Encapsulates positions table access."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── Reads ───────────────────────────────────────────────────────────

    def get_all(self) -> List[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM positions"
        ).fetchall()

    def get_active(self) -> List[sqlite3.Row]:
        """Return positions with quantity > 0."""
        return self._conn.execute(
            "SELECT symbol, quantity, avg_price, high_water_mark "
            "FROM positions WHERE quantity > 0"
        ).fetchall()

    def get_by_symbol(self, symbol: str) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM positions WHERE symbol = ?", (symbol,)
        ).fetchone()

    def get_entry_trading_day(self, symbol: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT entry_trading_day FROM positions WHERE symbol = ?",
            (symbol,),
        ).fetchone()
        return row["entry_trading_day"] if row else None

    def get_suspended_symbols(self) -> set[str]:
        """Return set of symbols in SUSPENDED state from watcher_symbol_health."""
        try:
            rows = self._conn.execute(
                "SELECT symbol FROM watcher_symbol_health WHERE suspended = 1"
            ).fetchall()
            return {r[0].upper() for r in rows}
        except sqlite3.OperationalError:
            return set()

    # ── Writes ──────────────────────────────────────────────────────────

    def update_price(self, symbol: str, current_price: float, unrealized_pnl: float) -> None:
        self._conn.execute(
            "UPDATE positions SET current_price = ?, unrealized_pnl = ? WHERE symbol = ?",
            (current_price, unrealized_pnl, symbol),
        )

    def update_high_water_mark(self, symbol: str, hwm: float) -> None:
        self._conn.execute(
            "UPDATE positions SET high_water_mark = ? WHERE symbol = ?",
            (hwm, symbol),
        )

    def update_state(self, symbol: str, state: str) -> None:
        self._conn.execute(
            "UPDATE positions SET state = ? WHERE symbol = ?",
            (state, symbol),
        )

    def upsert(self, pos: PositionRecord) -> None:
        """Insert or replace a position record."""
        self._conn.execute(
            """INSERT OR REPLACE INTO positions
               (symbol, quantity, avg_price, entry_trading_day)
               VALUES (?, ?, ?, ?)""",
            (pos.symbol, pos.quantity, pos.avg_price, pos.entry_trading_day),
        )

    def delete_all(self) -> None:
        self._conn.execute("DELETE FROM positions")
