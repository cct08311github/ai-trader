"""decision_repository.py — Data access for decisions and risk_checks tables.

Encapsulates INSERT operations for trading decisions and their
associated risk check records.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


class DecisionRepository:
    """Encapsulates decisions + risk_checks table access."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert_decision(
        self,
        *,
        decision_id: str,
        symbol: str,
        signal_side: str,
        now_iso: Optional[str] = None,
        strategy_id: str = "momentum_watcher",
        strategy_version: str = "watcher_v1",
        signal_score: float = 0.7,
        signal_ttl_ms: int = 30_000,
        signal_source: str = "technical",
        reason_json: Optional[str] = None,
    ) -> None:
        """Insert a watcher-style decision record."""
        ts = now_iso or _utc_now_iso()
        self._conn.execute(
            """INSERT OR IGNORE INTO decisions
               (decision_id, ts, symbol, strategy_id, strategy_version,
                signal_side, signal_score, signal_ttl_ms, llm_ref, reason_json,
                signal_source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (decision_id, ts, symbol, strategy_id, strategy_version,
             signal_side, signal_score, signal_ttl_ms, None,
             reason_json or json.dumps({"source": "ticker_watcher"}),
             signal_source),
        )

    def insert_pipeline_decision(
        self,
        *,
        decision_id: str,
        symbol: str,
        direction: str,
        quantity: int,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        reason_json: str,
        sentinel_blocked: bool,
        pm_veto: bool,
        budget_status: str,
        sentinel_reason_code: str,
        drawdown_risk_mode: str,
        drawdown_reason_code: str,
    ) -> None:
        """Insert a pipeline (v4) decision record."""
        if not _table_exists(self._conn, "decisions"):
            return
        self._conn.execute(
            """INSERT INTO decisions(
                decision_id, created_at, symbol, direction, quantity, entry_price,
                stop_loss, take_profit, reason_json, sentinel_blocked, pm_veto,
                budget_status, sentinel_reason_code, drawdown_risk_mode, drawdown_reason_code)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (decision_id, int(datetime.now(tz=timezone.utc).timestamp() * 1000),
             symbol, direction, quantity, entry_price,
             stop_loss, take_profit, reason_json,
             int(sentinel_blocked), int(pm_veto),
             budget_status, sentinel_reason_code,
             drawdown_risk_mode, drawdown_reason_code),
        )

    def insert_risk_check(
        self,
        *,
        decision_id: str,
        passed: bool,
        reject_code: Optional[str] = None,
        metrics: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Insert a risk check record."""
        self._conn.execute(
            """INSERT INTO risk_checks
               (check_id, decision_id, ts, passed, reject_code, metrics_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), decision_id, _utc_now_iso(),
             int(passed), reject_code,
             json.dumps(metrics or {}, ensure_ascii=True)),
        )
