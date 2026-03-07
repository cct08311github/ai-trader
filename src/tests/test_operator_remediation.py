from __future__ import annotations

import sqlite3

from openclaw.operator_remediation import (
    ensure_operator_remediation_schema,
    list_operator_remediations,
    record_operator_remediation,
)


def make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_operator_remediation_schema(conn)
    return conn


def test_record_operator_remediation_inserts_row():
    conn = make_db()

    remediation_id = record_operator_remediation(
        conn,
        action_type="quarantine_apply",
        target_type="symbol",
        target_ref="2330",
        actor="broker_reconciliation",
        status="applied",
        payload={"report_id": "r1"},
    )

    row = conn.execute(
        "SELECT action_id, action_type, target_ref, actor, status FROM operator_remediation_log WHERE action_id=?",
        (remediation_id,),
    ).fetchone()
    assert row["action_type"] == "quarantine_apply"
    assert row["target_ref"] == "2330"
    assert row["actor"] == "broker_reconciliation"
    assert row["status"] == "applied"


def test_list_operator_remediations_returns_payloads():
    conn = make_db()
    record_operator_remediation(
        conn,
        action_type="quarantine_clear",
        target_type="symbol",
        target_ref="2330",
        actor="operator",
        status="cleared",
        payload={"requested_symbols": ["2330"]},
        created_at=2,
    )
    record_operator_remediation(
        conn,
        action_type="quarantine_apply",
        target_type="symbol",
        target_ref="2317",
        actor="broker_reconciliation",
        status="applied",
        payload={"report_id": "r2"},
        created_at=1,
    )

    result = list_operator_remediations(conn, limit=10)

    assert result["count"] == 2
    assert result["items"][0]["action_type"] == "quarantine_clear"
    assert result["items"][0]["payload"]["requested_symbols"] == ["2330"]


def test_list_operator_remediations_supports_filters():
    conn = make_db()
    record_operator_remediation(
        conn,
        action_type="incident_resolve",
        target_type="incident_cluster",
        target_ref="network_security|SEC_NETWORK_IP_DENIED|x",
        actor="operator",
        status="resolved",
        payload={"reason": "allowlist updated"},
        created_at=2,
    )
    record_operator_remediation(
        conn,
        action_type="quarantine_apply",
        target_type="symbol",
        target_ref="2330",
        actor="broker_reconciliation",
        status="applied",
        payload={"report_id": "r2"},
        created_at=1,
    )

    result = list_operator_remediations(conn, action_type="incident_resolve", target_ref="network_security")

    assert result["count"] == 1
    assert result["items"][0]["action_type"] == "incident_resolve"
