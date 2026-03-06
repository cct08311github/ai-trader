from __future__ import annotations

import sqlite3

from openclaw.incident_hygiene import dedupe_open_incidents, incident_fingerprint


def make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE incidents (
          incident_id TEXT PRIMARY KEY,
          ts TEXT NOT NULL,
          severity TEXT NOT NULL,
          source TEXT NOT NULL,
          code TEXT NOT NULL,
          detail_json TEXT NOT NULL,
          resolved INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    return conn


def test_incident_fingerprint_normalizes_network_payload_formats():
    old_style = "{'current_ip': '8.8.8.8', 'allowlist': ['192.168.1.0/24']}"
    new_style = '{"allowlist":["192.168.1.0/24"],"current_ip":"8.8.8.8"}'
    assert (
        incident_fingerprint("network_security", "SEC_NETWORK_IP_DENIED", old_style)
        == incident_fingerprint("network_security", "SEC_NETWORK_IP_DENIED", new_style)
    )


def test_incident_fingerprint_normalizes_old_and_new_reconciliation_payloads():
    old_style = """
    {"report_id":"r1","mismatch_count":1,"mismatches":{"missing_local_position":[],"missing_broker_position":[{"symbol":"2330","local":{"quantity":100,"current_price":510.0}}],"quantity_mismatch":[],"missing_broker_order":[]}}
    """
    new_style = """
    {"report_id":"r2","stable_detail":{"mismatch_count":1,"missing_local_symbols":[],"missing_broker_symbols":["2330"],"quantity_mismatch_symbols":[],"missing_broker_order_ids":[],"diagnosis_codes":["MODE_OR_ACCOUNT_MISMATCH_SUSPECTED"],"resolved_simulation":true,"requested_simulation":null,"broker_source":"shioaji","broker_accounts":[]},"mismatches":{"missing_local_position":[],"missing_broker_position":[{"symbol":"2330","local":{"quantity":100,"current_price":510.0}}],"quantity_mismatch":[],"missing_broker_order":[]},"diagnostics":{"diagnosis_codes":["MODE_OR_ACCOUNT_MISMATCH_SUSPECTED"],"resolved_simulation":true,"requested_simulation":null,"broker_source":"shioaji","broker_accounts":[]}}
    """
    assert incident_fingerprint("broker_reconciliation", "RECONCILIATION_MISMATCH", old_style) is not None
    assert incident_fingerprint("broker_reconciliation", "RECONCILIATION_MISMATCH", new_style) is not None


def test_dedupe_open_incidents_resolves_network_duplicates():
    conn = make_db()
    conn.execute(
        "INSERT INTO incidents VALUES ('i1', '2026-03-06T10:00:00Z', 'critical', 'network_security', 'SEC_NETWORK_IP_DENIED', ?, 0)",
        ('{"allowlist":["192.168.1.0/24"],"current_ip":"8.8.8.8"}',),
    )
    conn.execute(
        "INSERT INTO incidents VALUES ('i2', '2026-03-06T09:00:00Z', 'critical', 'network_security', 'SEC_NETWORK_IP_DENIED', ?, 0)",
        ("{'current_ip': '8.8.8.8', 'allowlist': ['192.168.1.0/24']}",),
    )
    conn.commit()

    summary = dedupe_open_incidents(conn)

    assert summary["duplicates_resolved"] == 1
    resolved = conn.execute("SELECT resolved FROM incidents WHERE incident_id='i2'").fetchone()[0]
    assert resolved == 1


def test_dedupe_open_incidents_resolves_reconciliation_duplicates():
    conn = make_db()
    conn.execute(
        "INSERT INTO incidents VALUES ('i1', '2026-03-06T15:05:30Z', 'critical', 'broker_reconciliation', 'RECONCILIATION_MISMATCH', ?, 0)",
        (
            '{"report_id":"new","stable_detail":{"mismatch_count":1,"missing_local_symbols":[],"missing_broker_symbols":["2330"],"quantity_mismatch_symbols":[],"missing_broker_order_ids":[],"diagnosis_codes":["MODE_OR_ACCOUNT_MISMATCH_SUSPECTED"],"resolved_simulation":true,"requested_simulation":null,"broker_source":"shioaji","broker_accounts":[]}}',
        ),
    )
    conn.execute(
        "INSERT INTO incidents VALUES ('i2', '2026-03-06T14:53:45Z', 'warning', 'broker_reconciliation', 'RECONCILIATION_MISMATCH', ?, 0)",
        (
            '{"report_id":"old","mismatch_count":1,"mismatches":{"missing_local_position":[],"missing_broker_position":[{"symbol":"2330","local":{"quantity":100,"current_price":510.0}}],"quantity_mismatch":[],"missing_broker_order":[]}}',
        ),
    )
    conn.commit()

    summary = dedupe_open_incidents(conn)

    assert summary["duplicates_resolved"] == 1
    resolved = conn.execute("SELECT resolved FROM incidents WHERE incident_id='i2'").fetchone()[0]
    assert resolved == 1
