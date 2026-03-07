from __future__ import annotations

import json
import sqlite3
from typing import Any

from openclaw.incident_hygiene import incident_fingerprint
from openclaw.operator_remediation import record_operator_remediation


def list_open_incident_clusters(
    conn: sqlite3.Connection,
    *,
    source: str | None = None,
    code: str | None = None,
    severity: str | None = None,
) -> dict[str, Any]:
    where = ["resolved=0"]
    params: list[str] = []
    if source:
        where.append("source=?")
        params.append(str(source))
    if code:
        where.append("code=?")
        params.append(str(code))
    if severity:
        where.append("severity=?")
        params.append(str(severity))
    rows = conn.execute(
        f"""
        SELECT incident_id, ts, severity, source, code, detail_json
          FROM incidents
         WHERE {' AND '.join(where)}
      ORDER BY ts DESC, incident_id DESC
        """,
        tuple(params),
    ).fetchall()
    clusters: dict[str, dict[str, Any]] = {}
    for row in rows:
        source = str(row[3])
        code = str(row[4])
        fingerprint = incident_fingerprint(source, code, row[5]) or f"{source}|{code}|unfingerprinted"
        bucket = clusters.get(fingerprint)
        if bucket is None:
            try:
                detail = json.loads(row[5] or "{}")
            except Exception:
                detail = row[5]
            bucket = {
                "source": source,
                "code": code,
                "fingerprint": fingerprint,
                "severity": str(row[2]),
                "count": 0,
                "latest_ts": str(row[1]),
                "incident_ids": [],
                "sample_detail": detail,
            }
            clusters[fingerprint] = bucket
        bucket["count"] += 1
        bucket["incident_ids"].append(str(row[0]))
    items = list(clusters.values())
    items.sort(key=lambda item: str(item["fingerprint"]))
    items.sort(key=lambda item: str(item["latest_ts"]), reverse=True)
    items.sort(key=lambda item: int(item["count"]), reverse=True)
    return {"count": len(items), "items": items}


def resolve_open_incidents(
    conn: sqlite3.Connection,
    *,
    source: str,
    code: str,
    fingerprint: str | None = None,
    actor: str = "operator",
    reason: str = "",
    auto_commit: bool = True,
) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT incident_id, detail_json
          FROM incidents
         WHERE resolved=0
           AND source=?
           AND code=?
        """,
        (source, code),
    ).fetchall()
    resolved_ids: list[str] = []
    for row in rows:
        current_fingerprint = incident_fingerprint(source, code, row[1]) or f"{source}|{code}|unfingerprinted"
        if fingerprint and current_fingerprint != fingerprint:
            continue
        resolved_ids.append(str(row[0]))
    if resolved_ids:
        conn.executemany("UPDATE incidents SET resolved=1 WHERE incident_id=?", [(item,) for item in resolved_ids])
    record_operator_remediation(
        conn,
        action_type="incident_resolve",
        target_type="incident_cluster",
        target_ref=fingerprint or f"{source}|{code}",
        actor=actor,
        status="resolved" if resolved_ids else "no_op",
        payload={
            "source": source,
            "code": code,
            "fingerprint": fingerprint,
            "reason": reason,
            "resolved_incident_ids": resolved_ids,
        },
        auto_commit=False,
    )
    if auto_commit:
        conn.commit()
    return {
        "source": source,
        "code": code,
        "fingerprint": fingerprint,
        "resolved_count": len(resolved_ids),
        "resolved_incident_ids": resolved_ids,
    }
