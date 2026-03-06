from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from openclaw.operator_jobs import (
    fetch_broker_snapshot,
    fetch_broker_positions,
    run_incident_hygiene_job,
    run_ops_summary_job,
    run_reconciliation_job,
)


def make_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE strategy_proposals (
          proposal_id TEXT PRIMARY KEY,
          status TEXT,
          created_at INTEGER
        );
        CREATE TABLE proposal_execution_journal (
          execution_key TEXT PRIMARY KEY,
          proposal_id TEXT,
          target_rule TEXT,
          symbol TEXT,
          qty INTEGER,
          price REAL,
          state TEXT,
          attempt_count INTEGER,
          last_order_id TEXT,
          last_error TEXT,
          created_at INTEGER,
          updated_at INTEGER
        );
        CREATE TABLE incidents (
          incident_id TEXT PRIMARY KEY,
          ts TEXT NOT NULL,
          severity TEXT NOT NULL,
          source TEXT NOT NULL,
          code TEXT NOT NULL,
          detail_json TEXT NOT NULL,
          resolved INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE order_events (
          event_id TEXT PRIMARY KEY,
          ts TEXT NOT NULL,
          order_id TEXT NOT NULL,
          event_type TEXT NOT NULL,
          from_status TEXT,
          to_status TEXT,
          source TEXT NOT NULL,
          reason_code TEXT,
          payload_json TEXT NOT NULL
        );
        CREATE TABLE llm_traces (
          trace_id TEXT PRIMARY KEY,
          agent TEXT,
          model TEXT,
          prompt TEXT,
          response TEXT,
          latency_ms INTEGER,
          prompt_tokens INTEGER,
          completion_tokens INTEGER,
          confidence REAL,
          created_at INTEGER,
          shadow_mode INTEGER DEFAULT 0
        );
        CREATE TABLE positions (
          symbol TEXT PRIMARY KEY,
          quantity INTEGER,
          avg_price REAL,
          current_price REAL
        );
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
        );
        """
    )
    conn.execute("INSERT INTO strategy_proposals VALUES ('p1', 'queued', 1)")
    conn.execute(
        "INSERT INTO proposal_execution_journal VALUES ('ek1', 'p1', 'POSITION_REBALANCE', '2330', 100, 500.0, 'failed', 1, 'o1', 'err', 1, 1)"
    )
    conn.execute(
        "INSERT INTO incidents VALUES ('i1', '2026-03-06T00:00:00Z', 'warning', 'ops', 'X', '{}', 0)"
    )
    conn.execute(
        "INSERT INTO order_events VALUES ('e1', datetime('now'), 'o1', 'rejected', NULL, 'rejected', 'pre_trade_guard', 'RISK', '{}')"
    )
    conn.execute(
        "INSERT INTO llm_traces VALUES ('t1', 'pm', 'gemini', 'p', 'r', 1, 1, 1, 0.5, 9999999999999, 1)"
    )
    conn.execute("INSERT INTO positions VALUES ('2330', 100, 500, 510)")
    conn.commit()
    conn.close()


def test_run_ops_summary_job_writes_snapshot(tmp_path):
    db_path = tmp_path / "trades.db"
    out_dir = tmp_path / "ops"
    make_db(db_path)

    result = run_ops_summary_job(db_path=db_path, output_dir=out_dir)

    assert Path(result["output_path"]).exists()
    latest = json.loads((out_dir / "latest.json").read_text(encoding="utf-8"))
    assert latest["overall"] == "critical"
    assert latest["metrics"]["failed_executions"] == 1


def test_run_reconciliation_job_writes_snapshot_and_report(tmp_path):
    db_path = tmp_path / "trades.db"
    out_dir = tmp_path / "recon"
    make_db(db_path)

    result = run_reconciliation_job(
        db_path=db_path,
        output_dir=out_dir,
        broker_positions=[{"symbol": "2330", "quantity": 120, "current_price": 510}],
        broker_source="mock",
        simulation=True,
        resolved_simulation=True,
        broker_accounts=["SIMULATION"],
    )

    assert Path(result["output_path"]).exists()
    latest = json.loads((out_dir / "latest.json").read_text(encoding="utf-8"))
    assert latest["broker_source"] == "mock"
    assert latest["resolved_simulation"] is True
    assert latest["broker_accounts"] == ["SIMULATION"]
    assert latest["report"]["mismatch_count"] >= 1


def test_run_reconciliation_job_includes_diagnostics_when_broker_empty(tmp_path):
    db_path = tmp_path / "trades.db"
    out_dir = tmp_path / "recon"
    make_db(db_path)

    result = run_reconciliation_job(
        db_path=db_path,
        output_dir=out_dir,
        broker_positions=[],
        broker_source="shioaji",
        simulation=None,
        resolved_simulation=True,
        broker_accounts=[],
    )

    diagnostics = result["report"]["diagnostics"]
    assert diagnostics["suspected_mode_or_account_mismatch"] is True
    latest = json.loads((out_dir / "latest.json").read_text(encoding="utf-8"))
    assert latest["report"]["diagnostics"]["resolved_simulation"] is True


def test_fetch_broker_snapshot_maps_service_payload(monkeypatch):
    import app.services.shioaji_service as svc

    monkeypatch.setattr(
        svc,
        "get_positions",
        lambda source="shioaji", simulation=None: {
            "source": source,
            "simulation": True,
            "positions": [
                {"account": "SIM-ACC", "symbol": "2330", "qty": 100, "avg_price": 500.0, "last_price": 510.0}
            ],
        },
    )

    snapshot = fetch_broker_snapshot(source="mock", simulation=None)
    assert snapshot["source"] == "mock"
    assert snapshot["resolved_simulation"] is True
    assert snapshot["accounts"] == ["SIM-ACC"]
    assert snapshot["positions"] == [{"symbol": "2330", "quantity": 100, "current_price": 510.0}]


def test_fetch_broker_positions_maps_service_payload(monkeypatch):
    import app.services.shioaji_service as svc

    monkeypatch.setattr(
        svc,
        "get_positions",
        lambda source="shioaji", simulation=None: {
            "source": source,
            "simulation": True,
            "positions": [{"symbol": "2330", "qty": 100, "avg_price": 500.0, "last_price": 510.0}],
        },
    )

    positions = fetch_broker_positions(source="mock", simulation=True)
    assert positions == [{"symbol": "2330", "quantity": 100, "current_price": 510.0}]


def test_run_incident_hygiene_job_resolves_duplicates(tmp_path):
    db_path = tmp_path / "trades.db"
    out_dir = tmp_path / "incident-hygiene"
    make_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO incidents VALUES ('i-net-1', '2026-03-06T00:00:00Z', 'warning', 'network_security', 'SEC_NETWORK_IP_DENIED', '{\"allowlist\":[\"192.168.1.0/24\"],\"current_ip\":\"8.8.8.8\"}', 0)"
    )
    conn.execute(
        "INSERT INTO incidents VALUES ('i2', '2026-03-05T00:00:00Z', 'warning', 'network_security', 'SEC_NETWORK_IP_DENIED', '{\"allowlist\":[\"192.168.1.0/24\"],\"current_ip\":\"8.8.8.8\"}', 0)"
    )
    conn.commit()
    conn.close()

    result = run_incident_hygiene_job(db_path=db_path, output_dir=out_dir)

    assert result["summary"]["duplicates_resolved"] == 1
    latest = json.loads((out_dir / "latest.json").read_text(encoding="utf-8"))
    assert latest["summary"]["duplicates_resolved"] == 1
