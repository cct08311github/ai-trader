"""trace_repository.py — Data access for llm_traces and incidents tables.

Provides a simplified interface for trace insertion, complementing
the full multi-schema logic in llm_observability.py.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional


class TraceRepository:
    """Encapsulates llm_traces and incidents table access."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── LLM traces ──────────────────────────────────────────────────────

    def get_recent_traces(
        self,
        agent: Optional[str] = None,
        limit: int = 50,
    ) -> List[sqlite3.Row]:
        if agent:
            return self._conn.execute(
                """SELECT * FROM llm_traces
                   WHERE agent = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (agent, limit),
            ).fetchall()
        return self._conn.execute(
            "SELECT * FROM llm_traces ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

    # ── Incidents ───────────────────────────────────────────────────────

    def insert_incident(
        self,
        *,
        incident_id: str,
        source: str,
        code: str,
        severity: str,
        message: str,
        details_json: str = "{}",
        created_at: Optional[int] = None,
    ) -> None:
        import time
        ts = created_at or int(time.time() * 1000)
        self._conn.execute(
            """INSERT INTO incidents
               (incident_id, source, code, severity, message, details_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (incident_id, source, code, severity, message, details_json, ts),
        )

    def get_open_incidents(self, limit: int = 50) -> List[sqlite3.Row]:
        return self._conn.execute(
            """SELECT * FROM incidents
               WHERE resolved = 0
               ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
