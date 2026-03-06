from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path
from typing import Any

from openclaw.broker_reconciliation import reconcile_broker_state
from openclaw.incident_hygiene import dedupe_open_incidents
from openclaw.ops_health import collect_ops_health_summary


def _ts_label(now: dt.datetime | None = None) -> str:
    current = now or dt.datetime.now(tz=dt.timezone.utc)
    return current.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_snapshot(output_dir: str | Path, *, name: str, payload: dict[str, Any]) -> Path:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    stamp = _ts_label()
    history_path = target_dir / f"{stamp}.json"
    latest_path = target_dir / "latest.json"
    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    history_path.write_text(body + "\n", encoding="utf-8")
    latest_path.write_text(body + "\n", encoding="utf-8")
    return history_path


def run_ops_summary_job(
    *,
    db_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path))
    try:
        summary = collect_ops_health_summary(conn)
    finally:
        conn.close()

    history_path = write_snapshot(output_dir, name="ops-summary", payload=summary)
    return {"summary": summary, "output_path": str(history_path)}


def run_incident_hygiene_job(
    *,
    db_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path))
    try:
        summary = dedupe_open_incidents(conn)
    finally:
        conn.close()

    payload = {
        "ts": int(dt.datetime.now(tz=dt.timezone.utc).timestamp() * 1000),
        "summary": summary,
    }
    history_path = write_snapshot(output_dir, name="incident-hygiene", payload=payload)
    return {"summary": summary, "output_path": str(history_path)}


def run_reconciliation_job(
    *,
    db_path: str | Path,
    output_dir: str | Path,
    broker_positions: list[dict[str, Any]],
    broker_open_orders: list[dict[str, Any]] | None = None,
    broker_source: str = "shioaji",
    simulation: bool | None = None,
    resolved_simulation: bool | None = None,
    broker_accounts: list[str] | None = None,
) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path))
    try:
        report = reconcile_broker_state(
            conn,
            broker_positions=broker_positions,
            broker_open_orders=broker_open_orders or [],
            broker_context={
                "broker_source": broker_source,
                "requested_simulation": simulation,
                "resolved_simulation": resolved_simulation if resolved_simulation is not None else simulation,
                "broker_accounts": broker_accounts or [],
            },
        )
    finally:
        conn.close()

    payload = {
        "broker_source": broker_source,
        "simulation": simulation,
        "resolved_simulation": resolved_simulation if resolved_simulation is not None else simulation,
        "broker_accounts": sorted({str(a) for a in (broker_accounts or []) if str(a)}),
        "report": report,
    }
    history_path = write_snapshot(output_dir, name="reconciliation", payload=payload)
    return {"report": report, "output_path": str(history_path)}


def fetch_broker_snapshot(
    *,
    source: str = "shioaji",
    simulation: bool | None = None,
) -> dict[str, Any]:
    from app.services.shioaji_service import get_positions

    result = get_positions(source=source, simulation=simulation)
    if result.get("status") == "error":
        raise RuntimeError(str(result.get("message") or "broker snapshot failed"))

    raw_positions = result.get("positions", [])
    positions = []
    accounts = set()
    for item in raw_positions:
        account = str(item.get("account") or "").strip()
        if account:
            accounts.add(account)
        positions.append(
            {
                "symbol": str(item.get("symbol") or ""),
                "quantity": int(float(item.get("qty") or 0)),
                "current_price": float(item.get("last_price") or item.get("avg_price") or 0.0),
            }
        )
    return {
        "source": str(result.get("source") or source),
        "requested_simulation": simulation,
        "resolved_simulation": result.get("simulation", simulation),
        "accounts": sorted(accounts),
        "positions": positions,
    }


def fetch_broker_positions(
    *,
    source: str = "shioaji",
    simulation: bool | None = None,
) -> list[dict[str, Any]]:
    snapshot = fetch_broker_snapshot(source=source, simulation=simulation)
    return list(snapshot["positions"])
