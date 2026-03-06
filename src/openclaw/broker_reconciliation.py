from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any

from openclaw.audit_store import insert_incident


def ensure_reconciliation_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reconciliation_reports (
            report_id TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL,
            mismatch_count INTEGER NOT NULL,
            summary_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_reconciliation_reports_created ON reconciliation_reports (created_at)"
    )
    conn.commit()


def reconcile_broker_state(
    conn: sqlite3.Connection,
    *,
    broker_positions: list[dict[str, Any]],
    broker_open_orders: list[dict[str, Any]] | None = None,
    broker_context: dict[str, Any] | None = None,
    auto_commit: bool = True,
) -> dict[str, Any]:
    ensure_reconciliation_schema(conn)
    broker_open_orders = broker_open_orders or []
    broker_context = broker_context or {}

    local_positions_rows = conn.execute(
        "SELECT symbol, quantity, current_price FROM positions WHERE quantity > 0"
    ).fetchall()
    local_positions = {
        str(r[0]): {"quantity": int(r[1] or 0), "current_price": float(r[2] or 0.0)}
        for r in local_positions_rows
    }
    broker_positions_map = {
        str(p["symbol"]): {"quantity": int(p.get("quantity") or 0), "current_price": float(p.get("current_price") or 0.0)}
        for p in broker_positions
        if int(p.get("quantity") or 0) > 0
    }

    mismatches: dict[str, list[dict[str, Any]]] = {
        "missing_local_position": [],
        "missing_broker_position": [],
        "quantity_mismatch": [],
        "missing_broker_order": [],
    }

    for symbol, bpos in broker_positions_map.items():
        lpos = local_positions.get(symbol)
        if lpos is None:
            mismatches["missing_local_position"].append({"symbol": symbol, "broker": bpos})
        elif int(lpos["quantity"]) != int(bpos["quantity"]):
            mismatches["quantity_mismatch"].append({"symbol": symbol, "local": lpos, "broker": bpos})

    for symbol, lpos in local_positions.items():
        if symbol not in broker_positions_map:
            mismatches["missing_broker_position"].append({"symbol": symbol, "local": lpos})

    local_open_orders = conn.execute(
        "SELECT order_id, broker_order_id, symbol, status FROM orders WHERE status IN ('submitted', 'partially_filled')"
    ).fetchall()
    broker_order_ids = {str(o.get("broker_order_id") or "") for o in broker_open_orders}
    for row in local_open_orders:
        broker_order_id = str(row[1] or "")
        if broker_order_id and broker_order_id not in broker_order_ids:
            mismatches["missing_broker_order"].append(
                {
                    "order_id": str(row[0]),
                    "broker_order_id": broker_order_id,
                    "symbol": str(row[2]),
                    "status": str(row[3]),
                }
            )

    mismatch_count = sum(len(v) for v in mismatches.values())
    diagnostics = _build_reconciliation_diagnostics(
        local_positions=local_positions,
        broker_positions_map=broker_positions_map,
        local_open_orders=local_open_orders,
        broker_open_orders=broker_open_orders,
        mismatches=mismatches,
        broker_context=broker_context,
    )
    report = {
        "report_id": str(uuid.uuid4()),
        "created_at": int(time.time() * 1000),
        "mismatch_count": mismatch_count,
        "ok": mismatch_count == 0,
        "mismatches": mismatches,
        "diagnostics": diagnostics,
    }

    conn.execute(
        "INSERT INTO reconciliation_reports(report_id, created_at, mismatch_count, summary_json) VALUES (?, ?, ?, ?)",
        (report["report_id"], report["created_at"], mismatch_count, json.dumps(report, ensure_ascii=True)),
    )
    if mismatch_count:
        try:
            _insert_reconciliation_incident_best_effort(
                conn=conn,
                report=report,
                mismatches=mismatches,
                diagnostics=diagnostics,
            )
        except sqlite3.Error:
            pass
    if auto_commit:
        conn.commit()
    return report


def _build_reconciliation_diagnostics(
    *,
    local_positions: dict[str, dict[str, Any]],
    broker_positions_map: dict[str, dict[str, Any]],
    local_open_orders: list[tuple[Any, ...]],
    broker_open_orders: list[dict[str, Any]],
    mismatches: dict[str, list[dict[str, Any]]],
    broker_context: dict[str, Any],
) -> dict[str, Any]:
    diagnosis_codes: list[str] = []
    notes: list[str] = []
    missing_broker_count = len(mismatches.get("missing_broker_position", []))

    if local_positions and not broker_positions_map:
        diagnosis_codes.append("MODE_OR_ACCOUNT_MISMATCH_SUSPECTED")
        notes.append("Local positions exist while broker snapshot is empty; verify account and simulation mode.")
    elif local_positions and missing_broker_count == len(local_positions):
        diagnosis_codes.append("BROKER_POSITION_DIVERGENCE")
        notes.append("Every local position is absent from broker snapshot; verify account mapping and sync source.")

    return {
        "resolved_simulation": broker_context.get("resolved_simulation"),
        "requested_simulation": broker_context.get("requested_simulation"),
        "broker_source": broker_context.get("broker_source"),
        "broker_accounts": sorted({str(a) for a in broker_context.get("broker_accounts", []) if str(a)}),
        "local_position_count": len(local_positions),
        "broker_position_count": len(broker_positions_map),
        "local_open_order_count": len(local_open_orders),
        "broker_open_order_count": len(broker_open_orders),
        "diagnosis_codes": diagnosis_codes,
        "suspected_mode_or_account_mismatch": "MODE_OR_ACCOUNT_MISMATCH_SUSPECTED" in diagnosis_codes,
        "notes": notes,
    }


def _stable_incident_detail(
    mismatches: dict[str, list[dict[str, Any]]],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    return {
        "mismatch_count": sum(len(v) for v in mismatches.values()),
        "missing_local_symbols": sorted(item["symbol"] for item in mismatches.get("missing_local_position", [])),
        "missing_broker_symbols": sorted(item["symbol"] for item in mismatches.get("missing_broker_position", [])),
        "quantity_mismatch_symbols": sorted(item["symbol"] for item in mismatches.get("quantity_mismatch", [])),
        "missing_broker_order_ids": sorted(item["order_id"] for item in mismatches.get("missing_broker_order", [])),
        "diagnosis_codes": diagnostics.get("diagnosis_codes", []),
        "resolved_simulation": diagnostics.get("resolved_simulation"),
        "requested_simulation": diagnostics.get("requested_simulation"),
        "broker_source": diagnostics.get("broker_source"),
        "broker_accounts": diagnostics.get("broker_accounts", []),
    }


def _insert_reconciliation_incident_best_effort(
    *,
    conn: sqlite3.Connection,
    report: dict[str, Any],
    mismatches: dict[str, list[dict[str, Any]]],
    diagnostics: dict[str, Any],
) -> None:
    stable_detail = _stable_incident_detail(mismatches, diagnostics)
    rows = conn.execute(
        """
        SELECT detail_json
          FROM incidents
         WHERE resolved=0
           AND source='broker_reconciliation'
           AND code='RECONCILIATION_MISMATCH'
        """,
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row[0] or "{}")
        except Exception:
            continue
        if payload.get("stable_detail") == stable_detail:
            return
    severity = "critical" if diagnostics.get("suspected_mode_or_account_mismatch") else "warning"
    insert_incident(
        conn,
        ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        severity=severity,
        source="broker_reconciliation",
        code="RECONCILIATION_MISMATCH",
        detail={
            "report_id": report["report_id"],
            "stable_detail": stable_detail,
            "mismatches": mismatches,
            "diagnostics": diagnostics,
        },
        auto_commit=False,
    )
