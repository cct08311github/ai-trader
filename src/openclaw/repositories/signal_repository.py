"""signal_repository.py — Data access for signal cache and EOD prices.

Encapsulates SQL for ``lm_signal_cache`` and ``eod_prices`` tables.
"""
from __future__ import annotations

import sqlite3
from typing import Dict, List, Optional


class SignalRepository:
    """Encapsulates lm_signal_cache + eod_prices table access."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── Signal cache ────────────────────────────────────────────────────

    def write_cache(
        self,
        *,
        cache_id: str,
        symbol: str,
        score: float,
        source: str,
        direction: str,
        raw_json: str,
        created_at: int,
        expires_at: int,
    ) -> None:
        self._conn.execute(
            """INSERT INTO lm_signal_cache
               (cache_id, symbol, score, source, direction, raw_json, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (cache_id, symbol, score, source, direction, raw_json, created_at, expires_at),
        )

    def read_cache(self, symbol: str, now_ms: int) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            """SELECT score, direction, source FROM lm_signal_cache
               WHERE symbol = ? AND expires_at > ?
               ORDER BY created_at DESC LIMIT 1""",
            (symbol, now_ms),
        ).fetchone()

    def purge_expired(self, now_ms: int) -> int:
        cur = self._conn.execute(
            "DELETE FROM lm_signal_cache WHERE expires_at <= ?", (now_ms,)
        )
        return cur.rowcount

    # ── EOD prices ──────────────────────────────────────────────────────

    def get_candles(self, symbol: str, days: int = 60) -> List[sqlite3.Row]:
        return self._conn.execute(
            """SELECT trade_date, open, high, low, close, volume
               FROM eod_prices
               WHERE symbol = ?
               ORDER BY trade_date DESC
               LIMIT ?""",
            (symbol, days),
        ).fetchall()

    def get_latest_close(self, symbol: str) -> Optional[float]:
        row = self._conn.execute(
            """SELECT close FROM eod_prices
               WHERE symbol = ?
               ORDER BY trade_date DESC LIMIT 1""",
            (symbol,),
        ).fetchone()
        return float(row[0]) if row else None
