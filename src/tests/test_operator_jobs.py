from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
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


def make_system_state(path: Path, *, trading_enabled: bool = True, simulation_mode: bool = True) -> None:
    path.write_text(
        json.dumps(
            {
                "trading_enabled": trading_enabled,
                "simulation_mode": simulation_mode,
                "last_modified": "2026-03-06T00:00:00",
                "last_modified_by": "test",
            }
        ),
        encoding="utf-8",
    )


def test_run_ops_summary_job_writes_snapshot(tmp_path, monkeypatch):
    db_path = tmp_path / "trades.db"
    out_dir = tmp_path / "ops"
    system_state_path = tmp_path / "system_state.json"
    make_db(db_path)
    make_system_state(system_state_path, trading_enabled=False)
    state = json.loads(system_state_path.read_text(encoding="utf-8"))
    state["auto_lock_active"] = True
    state["auto_lock_source"] = "broker_reconciliation"
    state["auto_lock_reason_code"] = "MODE_OR_ACCOUNT_MISMATCH_SUSPECTED"
    state["auto_lock_reason"] = "verify account"
    system_state_path.write_text(json.dumps(state), encoding="utf-8")

    monkeypatch.setenv("SYSTEM_STATE_PATH", str(system_state_path))
    result = run_ops_summary_job(db_path=db_path, output_dir=out_dir)

    assert Path(result["output_path"]).exists()
    latest = json.loads((out_dir / "latest.json").read_text(encoding="utf-8"))
    assert latest["overall"] == "critical"
    assert latest["metrics"]["failed_executions"] == 1
    assert latest["metrics"]["auto_lock_active"] == 1
    assert latest["auto_lock"]["source"] == "broker_reconciliation"


def test_run_ops_summary_job_ignores_simulation_only_reconciliation_warning(tmp_path, monkeypatch):
    db_path = tmp_path / "trades.db"
    out_dir = tmp_path / "ops"
    system_state_path = tmp_path / "system_state.json"
    make_db(db_path)
    make_system_state(system_state_path, trading_enabled=True)

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS reconciliation_reports (report_id TEXT PRIMARY KEY, created_at INTEGER NOT NULL, mismatch_count INTEGER NOT NULL, summary_json TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO reconciliation_reports VALUES ('r-sim', ?, 9, ?)",
        (
            9_999_999_999_999,
            json.dumps(
                {
                    "diagnostics": {
                        "resolved_simulation": True,
                        "diagnosis_codes": ["MODE_OR_ACCOUNT_MISMATCH_SUSPECTED"],
                    }
                }
            ),
        ),
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("SYSTEM_STATE_PATH", str(system_state_path))
    result = run_ops_summary_job(db_path=db_path, output_dir=out_dir)

    latest = result["summary"]
    assert latest["metrics"]["reconciliation_mismatches_24h"] == 0
    assert latest["overall"] == "critical"  # failed execution + open incident from fixture still dominate


def test_run_reconciliation_job_writes_snapshot_and_report(tmp_path):
    db_path = tmp_path / "trades.db"
    out_dir = tmp_path / "recon"
    system_state_path = tmp_path / "system_state.json"
    make_db(db_path)
    make_system_state(system_state_path)

    result = run_reconciliation_job(
        db_path=db_path,
        output_dir=out_dir,
        broker_positions=[{"symbol": "2330", "quantity": 120, "current_price": 510}],
        broker_source="mock",
        simulation=True,
        resolved_simulation=True,
        broker_accounts=["SIMULATION"],
        system_state_path=system_state_path,
    )

    assert Path(result["output_path"]).exists()
    latest = json.loads((out_dir / "latest.json").read_text(encoding="utf-8"))
    assert latest["broker_source"] == "mock"
    assert latest["resolved_simulation"] is True
    assert latest["broker_accounts"] == ["SIMULATION"]
    assert latest["report"]["report_id"] == "bypassed-simulation"
    assert latest["report"]["mismatch_count"] == 0
    assert latest["auto_lock_applied"] is False


def test_run_reconciliation_job_simulation_skips_auto_lock(tmp_path):
    """Simulation mode: diagnostics still flag mismatch, but auto-lock is NOT applied."""
    db_path = tmp_path / "trades.db"
    out_dir = tmp_path / "recon"
    system_state_path = tmp_path / "system_state.json"
    make_db(db_path)
    make_system_state(system_state_path)

    result = run_reconciliation_job(
        db_path=db_path,
        output_dir=out_dir,
        broker_positions=[],
        broker_source="shioaji",
        simulation=None,
        resolved_simulation=True,
        broker_accounts=[],
        system_state_path=system_state_path,
    )

    diagnostics = result["report"]["diagnostics"]
    assert diagnostics["resolved_simulation"] is True
    latest = json.loads((out_dir / "latest.json").read_text(encoding="utf-8"))
    assert latest["report"]["report_id"] == "bypassed-simulation"
    assert latest["auto_lock_applied"] is False
    state = json.loads(system_state_path.read_text(encoding="utf-8"))
    assert state["trading_enabled"] is True

def test_run_reconciliation_job_simulation_forced(tmp_path, monkeypatch):
    """Setting RECON_FORCE_SIMULATION=1 enables real reconciliation in sim mode."""
    db_path = tmp_path / "trades.db"
    out_dir = tmp_path / "recon"
    system_state_path = tmp_path / "system_state.json"
    make_db(db_path)
    make_system_state(system_state_path)

    monkeypatch.setenv("RECON_FORCE_SIMULATION", "1")
    result = run_reconciliation_job(
        db_path=db_path,
        output_dir=out_dir,
        broker_positions=[],
        broker_source="shioaji",
        simulation=None,
        resolved_simulation=True,
        broker_accounts=[],
        system_state_path=system_state_path,
    )

    assert result["report"]["report_id"] != "bypassed-simulation"
    assert result["report"]["mismatch_count"] > 0
    assert result["report"]["diagnostics"]["suspected_mode_or_account_mismatch"] is True


def test_run_reconciliation_job_live_mode_applies_auto_lock(tmp_path):
    """Live mode: broker empty + local positions → auto-lock trading."""
    db_path = tmp_path / "trades.db"
    out_dir = tmp_path / "recon"
    system_state_path = tmp_path / "system_state.json"
    make_db(db_path)
    make_system_state(system_state_path)

    result = run_reconciliation_job(
        db_path=db_path,
        output_dir=out_dir,
        broker_positions=[],
        broker_source="shioaji",
        simulation=False,
        resolved_simulation=False,
        broker_accounts=["REAL-ACC"],
        system_state_path=system_state_path,
    )

    diagnostics = result["report"]["diagnostics"]
    assert diagnostics["suspected_mode_or_account_mismatch"] is True
    latest = json.loads((out_dir / "latest.json").read_text(encoding="utf-8"))
    assert latest["auto_lock_applied"] is True
    state = json.loads(system_state_path.read_text(encoding="utf-8"))
    assert state["trading_enabled"] is False
    assert state["auto_lock_active"] is True
    assert state["auto_lock_reason_code"] == "MODE_OR_ACCOUNT_MISMATCH_SUSPECTED"


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


def test_operator_cli_entrypoints_bootstrap_with_help():
    repo_root = Path(__file__).resolve().parents[2]
    scripts = [
        "tools/capture_ops_summary.py",
        "tools/run_reconciliation.py",
        "tools/run_incident_hygiene.py",
        "tools/run_reconciliation_quarantine.py",
        "tools/run_incident_resolution.py",
    ]

    for script in scripts:
        proc = subprocess.run(
            [sys.executable, str(repo_root / script), "--help"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"{script} failed: {proc.stderr}"
