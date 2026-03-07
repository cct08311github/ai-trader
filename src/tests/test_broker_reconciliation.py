from __future__ import annotations

import json
import sqlite3

from openclaw.broker_reconciliation import reconcile_broker_state


def make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE positions (
          symbol TEXT PRIMARY KEY,
          quantity INTEGER,
          avg_price REAL,
          current_price REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE orders (
          order_id TEXT PRIMARY KEY,
          decision_id TEXT,
          broker_order_id TEXT,
          ts_submit TEXT,
          symbol TEXT,
          side TEXT,
          qty INTEGER,
          price REAL,
          order_type TEXT,
          tif TEXT,
          status TEXT,
          strategy_version TEXT
        )
        """
    )
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


def test_reconcile_broker_state_reports_clean_match():
    conn = make_db()
    conn.execute("INSERT INTO positions VALUES ('2330', 100, 500, 510)")
    report = reconcile_broker_state(
        conn,
        broker_positions=[{"symbol": "2330", "quantity": 100, "current_price": 510}],
        broker_open_orders=[],
    )
    assert report["ok"] is True
    assert report["mismatch_count"] == 0
    stored = conn.execute("SELECT COUNT(*) FROM reconciliation_reports").fetchone()[0]
    assert stored == 1


def test_reconcile_broker_state_writes_incident_on_mismatch():
    conn = make_db()
    conn.execute("INSERT INTO positions VALUES ('2330', 100, 500, 510)")
    conn.execute(
        "INSERT INTO orders VALUES ('o1', 'd1', 'BRK-1', '2026-03-06T00:00:00+00:00', '2330', 'buy', 100, 500, 'limit', 'IOC', 'submitted', 'v1')"
    )
    report = reconcile_broker_state(
        conn,
        broker_positions=[{"symbol": "2330", "quantity": 120, "current_price": 510}],
        broker_open_orders=[],
    )
    assert report["ok"] is False
    assert report["mismatch_count"] == 2
    incidents = conn.execute("SELECT code, severity, detail_json FROM incidents").fetchall()
    assert incidents[0][0] == "RECONCILIATION_MISMATCH"
    assert incidents[0][1] == "warning"
    detail = json.loads(incidents[0][2])
    assert detail["stable_detail"]["quantity_mismatch_symbols"] == ["2330"]


def test_reconcile_broker_state_marks_mode_mismatch_diagnostic_live():
    """Live mode: mismatch creates a critical incident."""
    conn = make_db()
    conn.execute("INSERT INTO positions VALUES ('2330', 100, 500, 510)")

    report = reconcile_broker_state(
        conn,
        broker_positions=[],
        broker_context={"broker_source": "shioaji", "requested_simulation": None, "resolved_simulation": False},
    )

    diagnostics = report["diagnostics"]
    assert diagnostics["suspected_mode_or_account_mismatch"] is True
    assert "MODE_OR_ACCOUNT_MISMATCH_SUSPECTED" in diagnostics["diagnosis_codes"]
    incident = conn.execute("SELECT severity, detail_json FROM incidents").fetchone()
    assert incident[0] == "critical"
    detail = json.loads(incident[1])
    assert detail["stable_detail"]["resolved_simulation"] is False


def test_reconcile_broker_state_simulation_skips_incident():
    """Simulation mode + MODE_OR_ACCOUNT_MISMATCH: no incident created (expected mismatch)."""
    conn = make_db()
    conn.execute("INSERT INTO positions VALUES ('2330', 100, 500, 510)")

    report = reconcile_broker_state(
        conn,
        broker_positions=[],
        broker_context={"broker_source": "shioaji", "requested_simulation": None, "resolved_simulation": True},
    )

    diagnostics = report["diagnostics"]
    assert diagnostics["suspected_mode_or_account_mismatch"] is True
    assert "MODE_OR_ACCOUNT_MISMATCH_SUSPECTED" in diagnostics["diagnosis_codes"]
    # Report is still written
    stored = conn.execute("SELECT COUNT(*) FROM reconciliation_reports").fetchone()[0]
    assert stored == 1
    # But no incident — this mismatch is structurally expected in simulation
    incident_count = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    assert incident_count == 0


def test_reconcile_broker_state_dedupes_identical_open_incident():
    conn = make_db()
    conn.execute("INSERT INTO positions VALUES ('2330', 100, 500, 510)")

    reconcile_broker_state(conn, broker_positions=[])
    reconcile_broker_state(conn, broker_positions=[])

    count = conn.execute(
        "SELECT COUNT(*) FROM incidents WHERE source='broker_reconciliation' AND code='RECONCILIATION_MISMATCH' AND resolved=0"
    ).fetchone()[0]
    assert count == 1
