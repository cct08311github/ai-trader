from __future__ import annotations

import sqlite3

from openclaw.incident_resolution import list_open_incident_clusters, resolve_open_incidents


def make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
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


def test_list_open_incident_clusters_groups_by_fingerprint():
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

    result = list_open_incident_clusters(conn)

    assert result["count"] == 1
    assert result["items"][0]["count"] == 2
    assert result["items"][0]["source"] == "network_security"


def test_resolve_open_incidents_marks_matching_cluster_resolved_and_logs():
    conn = make_db()
    conn.execute(
        "INSERT INTO incidents VALUES ('i1', '2026-03-06T10:00:00Z', 'critical', 'network_security', 'SEC_NETWORK_IP_DENIED', ?, 0)",
        ('{"allowlist":["192.168.1.0/24"],"current_ip":"8.8.8.8"}',),
    )
    conn.execute(
        "INSERT INTO incidents VALUES ('i2', '2026-03-06T09:00:00Z', 'critical', 'network_security', 'SEC_NETWORK_IP_DENIED', ?, 0)",
        ('{"allowlist":["203.0.113.0/28"],"current_ip":"203.0.113.10"}',),
    )
    conn.commit()

    fingerprint = list_open_incident_clusters(conn)["items"][0]["fingerprint"]
    result = resolve_open_incidents(
        conn,
        source="network_security",
        code="SEC_NETWORK_IP_DENIED",
        fingerprint=fingerprint,
        reason="allowlist fixed",
    )

    assert result["resolved_count"] == 1
    resolved = conn.execute("SELECT resolved FROM incidents WHERE incident_id='i1'").fetchone()[0]
    remaining = conn.execute("SELECT resolved FROM incidents WHERE incident_id='i2'").fetchone()[0]
    assert resolved == 1
    assert remaining == 0
    log_row = conn.execute(
        "SELECT action_type, status FROM operator_remediation_log ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    assert log_row["action_type"] == "incident_resolve"
    assert log_row["status"] == "resolved"


def test_list_open_incident_clusters_supports_filters():
    conn = make_db()
    conn.execute(
        "INSERT INTO incidents VALUES ('i1', '2026-03-06T10:00:00Z', 'critical', 'network_security', 'SEC_NETWORK_IP_DENIED', ?, 0)",
        ('{"allowlist":["192.168.1.0/24"],"current_ip":"8.8.8.8"}',),
    )
    conn.execute(
        "INSERT INTO incidents VALUES ('i2', '2026-03-06T09:00:00Z', 'warning', 'broker_reconciliation', 'RECONCILIATION_MISMATCH', ?, 0)",
        ('{"mismatch_count":1}',),
    )
    conn.commit()

    result = list_open_incident_clusters(conn, source="network_security", code="SEC_NETWORK_IP_DENIED", severity="critical")

    assert result["count"] == 1
    assert result["items"][0]["source"] == "network_security"
