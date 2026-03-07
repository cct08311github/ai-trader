from __future__ import annotations

import json
import sqlite3
import time
import subprocess
import sys
from typing import Any

from openclaw.system_state_store import system_state_path_from_env
from openclaw.position_quarantine import get_quarantine_status


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return False
    return any(str(r[1]) == column for r in rows)


def _sum_actionable_reconciliation_mismatches(conn: sqlite3.Connection, since_ms: int) -> int:
    if _has_table(conn, "incidents"):
        rows = conn.execute(
            """
            SELECT detail_json
              FROM incidents
             WHERE resolved=0
               AND source='broker_reconciliation'
               AND code='RECONCILIATION_MISMATCH'
               AND ts >= datetime('now', '-1 day')
            """
        ).fetchall()
        if rows:
            actionable = 0
            for (detail_json,) in rows:
                try:
                    payload = json.loads(detail_json or "{}")
                except Exception:
                    payload = {}
                stable_detail = payload.get("stable_detail") if isinstance(payload, dict) else {}
                actionable += int((stable_detail or {}).get("mismatch_count") or 0)
            return actionable
        return 0

    rows = conn.execute(
        """
        SELECT mismatch_count, summary_json
          FROM reconciliation_reports
         WHERE created_at >= ?
        """,
        (since_ms,),
    ).fetchall()
    actionable = 0
    for mismatch_count, summary_json in rows:
        try:
            payload = json.loads(summary_json or "{}")
        except Exception:
            payload = {}
        diagnostics = payload.get("diagnostics") if isinstance(payload, dict) else {}
        resolved_simulation = bool((diagnostics or {}).get("resolved_simulation", False))
        if resolved_simulation:
            continue
        actionable += int(mismatch_count or 0)
    return actionable


def collect_ops_health_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    last_24h_ms = now_ms - 86_400_000

    summary = {
        "ts": now_ms,
        "metrics": {
            "pending_proposals": 0,
            "queued_executions": 0,
            "failed_executions": 0,
            "open_incidents": 0,
            "pre_trade_rejects_24h": 0,
            "llm_calls_24h": 0,
            "llm_shadow_calls_24h": 0,
            "llm_shadow_calls_24h": 0,
            "reconciliation_mismatches_24h": 0,
            "auto_lock_active": 0,
            "active_quarantines": 0,
        },
        "auto_lock": {
            "active": False,
            "source": None,
            "reason_code": None,
            "reason": None,
            "report_id": None,
        },
        "environment": {
            "python": sys.version.split()[0],
            "node": "unknown",
            "git_commit": "unknown",
        },
        "overall": "ok",
    }

    try:
        summary["environment"]["git_commit"] = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        pass

    try:
        summary["environment"]["node"] = subprocess.check_output(
            ["node", "-v"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        pass

    try:
        with open(system_state_path_from_env(), "r", encoding="utf-8") as f:
            system_state = json.load(f)
        auto_lock_active = bool(system_state.get("auto_lock_active", False))
        summary["metrics"]["auto_lock_active"] = int(auto_lock_active)
        summary["auto_lock"] = {
            "active": auto_lock_active,
            "source": system_state.get("auto_lock_source"),
            "reason_code": system_state.get("auto_lock_reason_code"),
            "reason": system_state.get("auto_lock_reason"),
            "report_id": system_state.get("auto_lock_report_id"),
        }
    except Exception:
        pass

    if _has_table(conn, "strategy_proposals"):
        row = conn.execute(
            "SELECT COUNT(*) FROM strategy_proposals WHERE status IN ('pending', 'approved', 'queued', 'executing')"
        ).fetchone()
        summary["metrics"]["pending_proposals"] = int(row[0] or 0)

    if _has_table(conn, "proposal_execution_journal"):
        row = conn.execute(
            "SELECT state, COUNT(*) FROM proposal_execution_journal GROUP BY state"
        ).fetchall()
        counts = {str(r[0]): int(r[1] or 0) for r in row}
        summary["metrics"]["queued_executions"] = counts.get("prepared", 0) + counts.get("executing", 0)
        summary["metrics"]["failed_executions"] = counts.get("failed", 0)

    if _has_table(conn, "incidents"):
        row = conn.execute("SELECT COUNT(*) FROM incidents WHERE resolved=0").fetchone()
        summary["metrics"]["open_incidents"] = int(row[0] or 0)

    if _has_table(conn, "order_events"):
        row = conn.execute(
            """
            SELECT COUNT(*) FROM order_events
             WHERE source='pre_trade_guard'
               AND event_type='rejected'
               AND ts >= datetime('now', '-1 day')
            """
        ).fetchone()
        summary["metrics"]["pre_trade_rejects_24h"] = int(row[0] or 0)

    if _has_table(conn, "llm_traces"):
        created_col = "created_at" if _has_column(conn, "llm_traces", "created_at") else None
        if created_col:
            row = conn.execute(
                f"SELECT COUNT(*) FROM llm_traces WHERE {created_col} >= ?",
                (last_24h_ms,),
            ).fetchone()
            summary["metrics"]["llm_calls_24h"] = int(row[0] or 0)
            if _has_column(conn, "llm_traces", "shadow_mode"):
                row = conn.execute(
                    f"SELECT COUNT(*) FROM llm_traces WHERE {created_col} >= ? AND shadow_mode=1",
                    (last_24h_ms,),
                ).fetchone()
                summary["metrics"]["llm_shadow_calls_24h"] = int(row[0] or 0)

    if _has_table(conn, "reconciliation_reports"):
        summary["metrics"]["reconciliation_mismatches_24h"] = _sum_actionable_reconciliation_mismatches(
            conn,
            last_24h_ms,
        )

    try:
        q_status = get_quarantine_status(conn)
        summary["metrics"]["active_quarantines"] = q_status.get("active_count", 0)
    except Exception:
        pass

    if (
        summary["metrics"]["open_incidents"] > 0
        or summary["metrics"]["failed_executions"] > 0
        or summary["metrics"]["auto_lock_active"] > 0
    ):
        summary["overall"] = "critical"
    elif summary["metrics"]["pre_trade_rejects_24h"] > 10 or summary["metrics"]["reconciliation_mismatches_24h"] > 0:
        summary["overall"] = "warning"

    return summary
