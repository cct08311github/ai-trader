from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Dict, Optional


def insert_risk_check(
    conn: sqlite3.Connection,
    *,
    decision_id: str,
    ts: str,
    passed: bool,
    reject_code: Optional[str],
    metrics: Dict[str, Any],
    check_id: Optional[str] = None,
    auto_commit: bool = True,
) -> str:
    rid = check_id or str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO risk_checks (check_id, decision_id, ts, passed, reject_code, metrics_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (rid, decision_id, ts, int(passed), reject_code, json.dumps(metrics, ensure_ascii=True)),
    )
    if auto_commit:
        conn.commit()
    return rid


def insert_incident(
    conn: sqlite3.Connection,
    *,
    ts: str,
    severity: str,
    source: str,
    code: str,
    detail: Dict[str, Any],
    resolved: bool = False,
    incident_id: Optional[str] = None,
    auto_commit: bool = True,
) -> str:
    iid = incident_id or str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO incidents (incident_id, ts, severity, source, code, detail_json, resolved)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (iid, ts, severity, source, code, json.dumps(detail, ensure_ascii=True), int(resolved)),
    )
    if auto_commit:
        conn.commit()
    return iid
