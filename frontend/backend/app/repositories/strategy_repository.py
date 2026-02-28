from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from app.db import fetch_rows


class StrategyRepository:
    """DB access layer for strategy-related read operations."""

    def get_proposals(
        self,
        conn: sqlite3.Connection,
        *,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        data = fetch_rows(conn, table="strategy_proposals", limit=limit, offset=offset)
        if status:
            s = status.strip().lower()
            data = [r for r in data if str(r.get("status") or "").lower() == s]
        return data

    def get_logs(
        self,
        conn: sqlite3.Connection,
        *,
        limit: int = 50,
        offset: int = 0,
        trace_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))

        if trace_id:
            rows = conn.execute(
                """
                SELECT * FROM llm_traces
                WHERE trace_id = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (trace_id, limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

        return fetch_rows(conn, table="llm_traces", limit=limit, offset=offset)
