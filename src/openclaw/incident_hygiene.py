from __future__ import annotations

import ast
import json
import sqlite3
from typing import Any


def _parse_detail_payload(raw: str | None) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            return None
    return data if isinstance(data, dict) else None


def _normalize_network_denied(detail: dict[str, Any]) -> dict[str, Any]:
    allowlist = sorted(str(item) for item in detail.get("allowlist", []) if str(item))
    return {
        "allowlist": allowlist,
        "current_ip": str(detail.get("current_ip") or ""),
    }


def _normalize_reconciliation_mismatch(detail: dict[str, Any]) -> dict[str, Any]:
    stable = detail.get("stable_detail")
    if isinstance(stable, dict):
        return {
            "mismatch_count": int(stable.get("mismatch_count") or 0),
            "missing_local_symbols": sorted(str(item) for item in stable.get("missing_local_symbols", []) if str(item)),
            "missing_broker_symbols": sorted(str(item) for item in stable.get("missing_broker_symbols", []) if str(item)),
            "quantity_mismatch_symbols": sorted(
                str(item) for item in stable.get("quantity_mismatch_symbols", []) if str(item)
            ),
            "missing_broker_order_ids": sorted(
                str(item) for item in stable.get("missing_broker_order_ids", []) if str(item)
            ),
        }

    mismatches = detail.get("mismatches")
    if not isinstance(mismatches, dict):
        return {
            "mismatch_count": int(detail.get("mismatch_count") or 0),
            "missing_local_symbols": [],
            "missing_broker_symbols": [],
            "quantity_mismatch_symbols": [],
            "missing_broker_order_ids": [],
        }
    return {
        "mismatch_count": int(detail.get("mismatch_count") or 0),
        "missing_local_symbols": sorted(
            str(item.get("symbol") or "") for item in mismatches.get("missing_local_position", []) if str(item.get("symbol") or "")
        ),
        "missing_broker_symbols": sorted(
            str(item.get("symbol") or "") for item in mismatches.get("missing_broker_position", []) if str(item.get("symbol") or "")
        ),
        "quantity_mismatch_symbols": sorted(
            str(item.get("symbol") or "") for item in mismatches.get("quantity_mismatch", []) if str(item.get("symbol") or "")
        ),
        "missing_broker_order_ids": sorted(
            str(item.get("order_id") or "") for item in mismatches.get("missing_broker_order", []) if str(item.get("order_id") or "")
        ),
    }


def incident_fingerprint(source: str, code: str, detail_json: str | None) -> str | None:
    detail = _parse_detail_payload(detail_json)
    if detail is None:
        return None
    normalized: dict[str, Any] | None = None
    if source == "network_security" and code == "SEC_NETWORK_IP_DENIED":
        normalized = _normalize_network_denied(detail)
    elif source == "broker_reconciliation" and code == "RECONCILIATION_MISMATCH":
        normalized = _normalize_reconciliation_mismatch(detail)
    if normalized is None:
        return None
    return f"{source}|{code}|{json.dumps(normalized, ensure_ascii=True, sort_keys=True)}"


def dedupe_open_incidents(
    conn: sqlite3.Connection,
    *,
    auto_commit: bool = True,
) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT incident_id, ts, source, code, detail_json
          FROM incidents
         WHERE resolved=0
      ORDER BY ts DESC, incident_id DESC
        """
    ).fetchall()
    seen: set[str] = set()
    duplicate_ids: list[str] = []
    buckets: dict[str, int] = {}
    for row in rows:
        fingerprint = incident_fingerprint(str(row[2]), str(row[3]), row[4])
        if fingerprint is None:
            continue
        buckets[fingerprint] = buckets.get(fingerprint, 0) + 1
        if fingerprint in seen:
            duplicate_ids.append(str(row[0]))
            continue
        seen.add(fingerprint)

    if duplicate_ids:
        conn.executemany("UPDATE incidents SET resolved=1 WHERE incident_id=?", [(item,) for item in duplicate_ids])
    if auto_commit:
        conn.commit()
    return {
        "open_incidents_scanned": len(rows),
        "duplicates_resolved": len(duplicate_ids),
        "unique_fingerprints": len(seen),
        "deduped_groups": sum(1 for count in buckets.values() if count > 1),
        "resolved_incident_ids": duplicate_ids,
    }
