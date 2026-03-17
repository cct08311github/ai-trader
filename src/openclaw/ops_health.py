from __future__ import annotations

import json
import logging
import sqlite3
import time
import subprocess
import sys
from pathlib import Path
from typing import Any

from openclaw.system_state_store import system_state_path_from_env
from openclaw.position_quarantine import get_quarantine_status
from openclaw.path_utils import get_repo_root

_log = logging.getLogger("ops_health")

# Critical services that must be online for trading to function
_CRITICAL_SERVICES = {"ai-trader-api", "ai-trader-watcher"}

# Default alert thresholds — override via config/alert_policy.json
_DEFAULT_THRESHOLDS = {
    "cpu_percent_warn": 80,
    "cpu_percent_critical": 95,
    "memory_percent_warn": 80,
    "memory_percent_critical": 95,
    "disk_percent_warn": 85,
    "disk_percent_critical": 95,
}


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


def load_alert_thresholds() -> dict[str, Any]:
    """Load alert thresholds from config/alert_policy.json, falling back to defaults."""
    config_path = get_repo_root() / "config" / "alert_policy.json"
    thresholds = dict(_DEFAULT_THRESHOLDS)
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            overrides = json.load(f)
        thresholds.update(overrides)
    except FileNotFoundError:
        pass  # Use defaults
    except Exception:
        _log.warning("Failed to load alert_policy.json, using defaults", exc_info=True)
    return thresholds


def get_pm2_processes() -> dict[str, Any]:
    """Query PM2 for process status. Returns structured process info.

    Returns dict with:
      - processes: dict mapping name -> {status, pid, memory_mb, restart_count, uptime_s}
      - health: {total, online, stopped, errored}
      - critical_down: list of critical service names that are NOT online
    """
    result: dict[str, Any] = {
        "processes": {},
        "health": {"total": 0, "online": 0, "stopped": 0, "errored": 0},
        "critical_down": [],
    }
    try:
        raw = subprocess.check_output(
            ["pm2", "jlist"], text=True, stderr=subprocess.DEVNULL, timeout=10
        )
        processes = json.loads(raw)
    except Exception:
        return result

    for proc in processes:
        name = proc.get("name", "unknown")
        pm2_env = proc.get("pm2_env", {})
        monit = proc.get("monit", {})
        status = pm2_env.get("status", "unknown")

        result["processes"][name] = {
            "status": status,
            "pid": proc.get("pid", 0),
            "memory_mb": round((monit.get("memory", 0) or 0) / (1024 * 1024), 1),
            "restart_count": pm2_env.get("restart_time", 0),
            "uptime_s": int((time.time() * 1000 - (pm2_env.get("pm_uptime", 0) or 0)) / 1000)
            if pm2_env.get("pm_uptime")
            else 0,
        }

        result["health"]["total"] += 1
        if status == "online":
            result["health"]["online"] += 1
        elif status == "errored":
            result["health"]["errored"] += 1
        else:
            result["health"]["stopped"] += 1

    for svc in _CRITICAL_SERVICES:
        proc_info = result["processes"].get(svc)
        if proc_info is None or proc_info["status"] != "online":
            result["critical_down"].append(svc)

    return result


def check_resource_alerts(
    summary: dict[str, Any], thresholds: dict[str, Any]
) -> list[dict[str, str]]:
    """Check resource metrics against thresholds. Returns list of alerts."""
    alerts: list[dict[str, str]] = []

    pm2 = summary.get("pm2", {})
    for svc in pm2.get("critical_down", []):
        alerts.append({
            "severity": "critical",
            "source": "pm2",
            "message": f"Critical service '{svc}' is not online",
        })

    for name, proc in pm2.get("processes", {}).items():
        if proc.get("status") == "errored":
            alerts.append({
                "severity": "critical",
                "source": "pm2",
                "message": f"Process '{name}' is in errored state (restarts: {proc.get('restart_count', 0)})",
            })

    return alerts


def send_ops_alerts(alerts: list[dict[str, str]]) -> None:
    """Send critical/warning alerts via Telegram. Non-blocking, never raises."""
    if not alerts:
        return
    try:
        from openclaw.tg_notify import send_message
        critical = [a for a in alerts if a["severity"] == "critical"]
        if not critical:
            return

        lines = ["⚠️ <b>[Ops Alert]</b> 系統健康警報\n"]
        for a in critical:
            lines.append(f"🔴 [{a['source']}] {a['message']}")
        send_message("\n".join(lines))
    except Exception:
        _log.warning("Failed to send ops alerts via Telegram", exc_info=True)


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

    # PM2 process liveness
    pm2_data = get_pm2_processes()
    summary["pm2"] = pm2_data
    summary["metrics"]["pm2_errored"] = pm2_data["health"]["errored"]
    summary["metrics"]["pm2_critical_down"] = len(pm2_data["critical_down"])

    # Overall status determination
    if (
        summary["metrics"]["open_incidents"] > 0
        or summary["metrics"]["failed_executions"] > 0
        or summary["metrics"]["auto_lock_active"] > 0
        or summary["metrics"]["pm2_critical_down"] > 0
        or summary["metrics"]["pm2_errored"] > 0
    ):
        summary["overall"] = "critical"
    elif summary["metrics"]["pre_trade_rejects_24h"] > 10 or summary["metrics"]["reconciliation_mismatches_24h"] > 0:
        summary["overall"] = "warning"

    # Check and send alerts
    thresholds = load_alert_thresholds()
    alerts = check_resource_alerts(summary, thresholds)
    summary["alerts"] = alerts
    send_ops_alerts(alerts)

    return summary
