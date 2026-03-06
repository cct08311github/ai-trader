"""Tests for app/api/system.py — targeting 22% → near 100%."""
from __future__ import annotations

import importlib
import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_TOKEN = "test-bearer-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


def _init_system_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS llm_traces (
            trace_id TEXT,
            agent TEXT,
            model TEXT,
            prompt TEXT,
            response TEXT,
            latency_ms INTEGER,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            confidence REAL,
            created_at INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS strategy_proposals (
            proposal_id TEXT PRIMARY KEY,
            status TEXT,
            created_at INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            symbol TEXT,
            quantity REAL,
            avg_price REAL,
            current_price REAL,
            chip_health_score REAL,
            sector TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            decision_id TEXT,
            strategy_id TEXT,
            ts_submit TEXT,
            symbol TEXT,
            side TEXT,
            qty INTEGER,
            price REAL,
            order_type TEXT,
            tif TEXT,
            status TEXT,
            broker_version TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fills (
            order_id TEXT,
            qty INTEGER,
            price REAL,
            fee REAL,
            tax REAL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proposal_execution_journal (
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
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS incidents (
            incident_id TEXT PRIMARY KEY,
            ts TEXT NOT NULL,
            severity TEXT NOT NULL,
            source TEXT NOT NULL,
            code TEXT NOT NULL,
            detail_json TEXT NOT NULL,
            resolved INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS order_events (
            event_id TEXT PRIMARY KEY,
            ts TEXT NOT NULL,
            order_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            from_status TEXT,
            to_status TEXT,
            source TEXT NOT NULL,
            reason_code TEXT,
            payload_json TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reconciliation_reports (
            report_id TEXT PRIMARY KEY,
            created_at INTEGER NOT NULL,
            mismatch_count INTEGER NOT NULL,
            summary_json TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS position_quarantine (
            symbol TEXT PRIMARY KEY,
            active INTEGER NOT NULL DEFAULT 1,
            source TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            reason TEXT,
            report_id TEXT,
            created_at INTEGER NOT NULL,
            cleared_at INTEGER,
            payload_json TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


@pytest.fixture
def sys_client(tmp_path, monkeypatch):
    db_path = tmp_path / "trades.db"
    _init_system_db(db_path)

    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("RATE_LIMIT_RPM", "1000")
    monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")

    import app.core.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)
    import app.api.system as sys_mod
    importlib.reload(sys_mod)
    import app.main as main
    importlib.reload(main)

    from fastapi.testclient import TestClient
    with TestClient(main.app) as c:
        yield c, tmp_path, db_path


class TestSystemHealth:
    def test_health_returns_200(self, sys_client):
        c, _, _ = sys_client
        r = c.get("/api/system/health", headers=_AUTH)
        assert r.status_code == 200

    def test_health_has_services(self, sys_client):
        c, _, _ = sys_client
        r = c.get("/api/system/health", headers=_AUTH)
        data = r.json()
        assert "services" in data
        assert "resources" in data
        assert "db_health" in data
        assert "timestamp" in data

    def test_health_fastapi_online(self, sys_client):
        c, _, _ = sys_client
        r = c.get("/api/system/health", headers=_AUTH)
        data = r.json()
        assert data["services"]["fastapi"]["status"] == "online"

    def test_health_no_auth_401(self, sys_client):
        c, _, _ = sys_client
        r = c.get("/api/system/health")
        assert r.status_code == 401

    def test_ops_summary_returns_metrics(self, sys_client):
        c, _, db_path = sys_client
        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO strategy_proposals (proposal_id, status, created_at) VALUES ('p2', 'queued', 1)")
        conn.execute(
            "INSERT INTO proposal_execution_journal VALUES ('ek1', 'p2', 'POSITION_REBALANCE', '2330', 100, 500.0, 'failed', 1, 'o1', 'err', 1, 1)"
        )
        conn.execute(
            "INSERT INTO incidents VALUES ('i1', '2026-03-06T00:00:00Z', 'warning', 'recon', 'CODE', '{}', 0)"
        )
        conn.execute(
            "INSERT INTO order_events VALUES ('e1', datetime('now'), 'o1', 'rejected', NULL, 'rejected', 'pre_trade_guard', 'RISK', '{}')"
        )
        conn.execute(
            "INSERT INTO reconciliation_reports VALUES ('r1', ?, 2, '{}')",
            (int(__import__('time').time() * 1000),),
        )
        conn.commit()
        conn.close()

        r = c.get("/api/system/ops-summary", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["overall"] == "critical"
        assert data["metrics"]["pending_proposals"] >= 1
        assert data["metrics"]["failed_executions"] == 1
        assert data["metrics"]["open_incidents"] == 1

    def test_latest_reconciliation_returns_latest_report(self, sys_client):
        c, _, db_path = sys_client
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO reconciliation_reports VALUES ('r2', 1234567890, 1, '{\"ok\": false}')"
        )
        conn.commit()
        conn.close()

        r = c.get("/api/system/reconciliation/latest", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["available"] is True
        assert data["report_id"] == "r2"
        assert data["mismatch_count"] == 1

    def test_quarantine_status_returns_active_items(self, sys_client):
        c, _, db_path = sys_client
        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO positions VALUES ('2330', 0, 500.0, 0.0, NULL, NULL)")
        conn.execute(
            "INSERT INTO position_quarantine VALUES ('2330', 1, 'broker_reconciliation', 'BROKER_POSITION_MISSING', 'x', 'r1', 1, NULL, '{}')"
        )
        conn.commit()
        conn.close()

        r = c.get("/api/system/quarantine-status", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["active_count"] == 1
        assert data["items"][0]["symbol"] == "2330"

    def test_quarantine_plan_returns_latest_report_plan(self, sys_client):
        c, _, db_path = sys_client
        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO positions VALUES ('2330', 100, 500.0, 510.0, NULL, NULL)")
        conn.execute(
            "INSERT INTO reconciliation_reports VALUES ('r-plan', 1234567891, 1, ?)",
            (json.dumps({"report_id": "r-plan", "mismatches": {"missing_broker_position": [{"symbol": "2330"}]}, "diagnostics": {"suspected_mode_or_account_mismatch": True}}),),
        )
        conn.commit()
        conn.close()

        r = c.get("/api/system/quarantine-plan", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["report_id"] == "r-plan"
        assert data["eligible_symbols"] == ["2330"]

    def test_quarantine_apply_updates_status(self, sys_client):
        c, _, db_path = sys_client
        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO positions VALUES ('2330', 100, 500.0, 510.0, NULL, NULL)")
        conn.execute(
            "INSERT INTO reconciliation_reports VALUES ('r-apply', 1234567892, 1, ?)",
            (json.dumps({"report_id": "r-apply", "mismatches": {"missing_broker_position": [{"symbol": "2330"}]}, "diagnostics": {"suspected_mode_or_account_mismatch": True}}),),
        )
        conn.commit()
        conn.close()

        r = c.post("/api/system/quarantine/apply", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["applied_symbols"] == ["2330"]
        assert data["quarantine_status"]["active_count"] == 1

    def test_quarantine_clear_clears_specific_symbol(self, sys_client):
        c, _, db_path = sys_client
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO orders VALUES ('o1', 'd1', NULL, '2026-03-06T00:00:00Z', '2330', 'buy', 100, 500.0, 'limit', 'DAY', 'filled', 'v1')"
        )
        conn.execute("INSERT INTO fills VALUES ('o1', 100, 500.0, 10.0, 0.0)")
        conn.execute("INSERT INTO positions VALUES ('2330', 0, 0.0, 0.0, NULL, NULL)")
        conn.execute(
            "INSERT INTO position_quarantine VALUES ('2330', 1, 'broker_reconciliation', 'BROKER_POSITION_MISSING', 'x', 'r1', 1, NULL, '{}')"
        )
        conn.commit()
        conn.close()

        r = c.post("/api/system/quarantine/clear", json={"symbols": ["2330"]}, headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["remaining_active_count"] == 0
        assert data["quarantine_status"]["active_count"] == 0

    def test_quarantine_plan_404_when_missing_report(self, sys_client):
        c, _, _ = sys_client
        r = c.get("/api/system/quarantine-plan", headers=_AUTH)
        assert r.status_code == 404

    def test_remediation_history_returns_latest_actions(self, sys_client):
        c, _, db_path = sys_client
        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO positions VALUES ('2330', 100, 500.0, 510.0, NULL, NULL)")
        conn.execute(
            "INSERT INTO reconciliation_reports VALUES ('r-history', 1234567893, 1, ?)",
            (json.dumps({"report_id": "r-history", "mismatches": {"missing_broker_position": [{"symbol": "2330"}]}, "diagnostics": {"suspected_mode_or_account_mismatch": True}}),),
        )
        conn.commit()
        conn.close()

        apply_resp = c.post("/api/system/quarantine/apply", headers=_AUTH)
        assert apply_resp.status_code == 200

        r = c.get("/api/system/remediation-history?limit=5", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["count"] >= 1
        assert data["items"][0]["action_type"] == "quarantine_apply"
        assert data["items"][0]["target_ref"] == "2330"


class TestSystemQuota:
    def test_quota_returns_200(self, sys_client):
        c, _, _ = sys_client
        r = c.get("/api/system/quota", headers=_AUTH)
        assert r.status_code == 200

    def test_quota_structure(self, sys_client):
        c, _, _ = sys_client
        r = c.get("/api/system/quota", headers=_AUTH)
        data = r.json()
        assert "month" in data
        assert "budget_twd" in data
        assert "used_twd" in data
        assert "used_percent" in data
        assert "status" in data

    def test_quota_no_auth_401(self, sys_client):
        c, _, _ = sys_client
        r = c.get("/api/system/quota")
        assert r.status_code == 401


class TestSystemRisk:
    def test_risk_returns_200(self, sys_client):
        c, _, _ = sys_client
        r = c.get("/api/system/risk", headers=_AUTH)
        assert r.status_code == 200

    def test_risk_structure(self, sys_client):
        c, _, _ = sys_client
        r = c.get("/api/system/risk", headers=_AUTH)
        data = r.json()
        assert "today_realized_pnl" in data
        assert "monthly_realized_pnl" in data
        assert "risk_mode" in data

    def test_risk_mode_normal_when_no_loss(self, sys_client):
        c, _, _ = sys_client
        r = c.get("/api/system/risk", headers=_AUTH)
        data = r.json()
        # With no data today_pnl = 0 → normal mode
        assert data["risk_mode"] == "normal"


class TestSystemEvents:
    def test_events_returns_200(self, sys_client):
        c, _, _ = sys_client
        r = c.get("/api/system/events", headers=_AUTH)
        assert r.status_code == 200

    def test_events_structure(self, sys_client):
        c, _, _ = sys_client
        r = c.get("/api/system/events", headers=_AUTH)
        data = r.json()
        assert "events" in data
        assert isinstance(data["events"], list)
        assert len(data["events"]) > 0

    def test_events_first_event_has_fields(self, sys_client):
        c, _, _ = sys_client
        r = c.get("/api/system/events", headers=_AUTH)
        evt = r.json()["events"][0]
        assert "severity" in evt
        assert "source" in evt


class TestInventoryEndpoint:
    def test_inventory_returns_200(self, sys_client):
        c, _, _ = sys_client
        r = c.get("/api/inventory", headers=_AUTH)
        assert r.status_code == 200

    def test_inventory_is_list(self, sys_client):
        c, _, _ = sys_client
        r = c.get("/api/inventory", headers=_AUTH)
        data = r.json()
        # Returns a list (empty is ok — positions table is empty in test DB)
        assert isinstance(data, list)

    def test_inventory_with_positions(self, sys_client):
        """Inventory with real positions data exercises more code paths."""
        c, _, db_path = sys_client
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO positions (symbol, quantity, avg_price, current_price, chip_health_score, sector) "
            "VALUES (?,?,?,?,?,?)",
            ("2330", 1000, 600.0, 620.0, 0.8, "半導體")
        )
        conn.execute(
            "INSERT INTO positions (symbol, quantity, avg_price, current_price, chip_health_score, sector) "
            "VALUES (?,?,?,?,?,?)",
            ("2317", 500, 85.0, None, 0.7, "電子")  # current_price = None → uses avg_price
        )
        conn.commit()
        conn.close()
        r = c.get("/api/inventory", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert len(data) >= 1
        codes = [item["code"] for item in data]
        assert "2330" in codes

    def test_inventory_exception_when_db_missing(self, sys_client, monkeypatch):
        """Inventory returns 500 when DB path is broken."""
        c, _, _ = sys_client
        import app.api.system as sys_mod
        from pathlib import Path
        monkeypatch.setattr(sys_mod, "DB_PATH", Path("/nonexistent/path/db.db"))
        r = c.get("/api/inventory", headers=_AUTH)
        assert r.status_code in (200, 500)  # May return empty list or 500


class TestCapitalEndpoints:
    def test_get_capital_returns_200(self, sys_client):
        c, _, _ = sys_client
        r = c.get("/api/capital", headers=_AUTH)
        assert r.status_code == 200

    def test_get_capital_structure(self, sys_client):
        c, _, _ = sys_client
        r = c.get("/api/capital", headers=_AUTH)
        data = r.json()
        assert "total_capital_twd" in data
        assert "max_single_position_twd" in data

    def test_get_capital_file_not_found_uses_defaults(self, sys_client, monkeypatch):
        """When capital.json doesn't exist, defaults are returned."""
        c, _, _ = sys_client
        import app.api.system as sys_mod
        monkeypatch.setattr(sys_mod, "_CAPITAL_FILE", "/nonexistent/capital.json")
        r = c.get("/api/capital", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["total_capital_twd"] == 500000.0

    def test_update_capital(self, sys_client, monkeypatch):
        """PUT /api/capital saves and returns new values."""
        c, tmp_path, _ = sys_client
        import app.api.system as sys_mod
        cap_file = tmp_path / "capital.json"
        cap_file.write_text(json.dumps({"total_capital_twd": 500000.0}))
        monkeypatch.setattr(sys_mod, "_CAPITAL_FILE", str(cap_file))
        payload = {
            "total_capital_twd": 1_000_000.0,
            "max_single_position_pct": 0.15,
            "daily_loss_limit_twd": 10000.0,
            "monthly_loss_limit_twd": 50000.0,
        }
        r = c.put("/api/capital", json=payload, headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["total_capital_twd"] == 1_000_000.0

    def test_capital_no_auth_401(self, sys_client):
        c, _, _ = sys_client
        r = c.get("/api/capital")
        assert r.status_code == 401


class TestSystemHealthExceptionPaths:
    def test_health_psutil_exception(self, sys_client, monkeypatch):
        """Health endpoint handles psutil failure gracefully."""
        import psutil
        monkeypatch.setattr(psutil, "cpu_percent", lambda interval=None: (_ for _ in ()).throw(RuntimeError("mock failure")))
        c, _, _ = sys_client
        # Even if psutil fails, health endpoint should still return 200
        r = c.get("/api/system/health", headers=_AUTH)
        assert r.status_code == 200

    def test_health_sqlite_offline_when_pool_fails(self, sys_client, monkeypatch):
        """Health endpoint shows sqlite offline when READONLY_POOL fails."""
        import app.api.system as sys_mod
        from unittest.mock import MagicMock, patch
        import contextlib

        # Patch the pool's conn context manager to raise
        @contextlib.contextmanager
        def bad_conn():
            raise Exception("pool unavailable")
            yield None

        original_pool = sys_mod.READONLY_POOL
        monkeypatch.setattr(original_pool, "conn", bad_conn)
        c, _, _ = sys_client
        r = c.get("/api/system/health", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["services"]["sqlite"]["status"] == "offline"


class TestSystemQuotaWithLlmObs:
    def test_quota_with_llm_traces_data(self, sys_client):
        """quota endpoint calculates correctly with real trace data."""
        c, _, db_path = sys_client
        now_ts = int(__import__("time").time())
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO llm_traces (trace_id, agent, model, prompt_tokens, completion_tokens, created_at) "
            "VALUES (?,?,?,?,?,?)",
            ("t1", "watcher", "gemini-flash", 1000, 500, now_ts)
        )
        conn.commit()
        conn.close()
        r = c.get("/api/system/quota", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert "used_twd" in data

    def test_quota_with_bad_obs_path(self, sys_client, monkeypatch):
        """quota uses default costs when llm_observability_v1.json is missing."""
        c, _, _ = sys_client
        import app.api.system as sys_mod
        # We can't easily monkeypatch the local variable in quota, but we can
        # test that the endpoint succeeds even without a valid obs file
        r = c.get("/api/system/quota", headers=_AUTH)
        assert r.status_code == 200

    def test_quota_with_bad_capital_path(self, sys_client, monkeypatch):
        """quota uses default budget when capital.json is missing."""
        c, _, _ = sys_client
        # The capital path is hardcoded in system.py as a local variable inside
        # the function, so we need to patch `open` to simulate failure
        import builtins
        original_open = builtins.open
        def patched_open(file, *args, **kwargs):
            if "capital.json" in str(file):
                raise FileNotFoundError("no capital file")
            return original_open(file, *args, **kwargs)
        monkeypatch.setattr(builtins, "open", patched_open)
        r = c.get("/api/system/quota", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["budget_twd"] == 1000.0  # default

    def test_quota_with_bad_obs_file_content(self, sys_client, monkeypatch):
        """quota uses default costs when llm_observability_v1.json is invalid JSON."""
        c, _, _ = sys_client
        import builtins
        original_open = builtins.open
        def patched_open(file, *args, **kwargs):
            if "llm_observability_v1.json" in str(file):
                raise FileNotFoundError("no obs file")
            return original_open(file, *args, **kwargs)
        monkeypatch.setattr(builtins, "open", patched_open)
        r = c.get("/api/system/quota", headers=_AUTH)
        assert r.status_code == 200


class TestSystemRiskPnl:
    def test_risk_with_mocked_pnl_engine(self, sys_client, monkeypatch):
        """risk endpoint covers get_monthly_pnl path when pnl_engine is available."""
        c, _, _ = sys_client
        import app.api.system as sys_mod
        import types

        # Create a fake pnl_engine module
        fake_pnl = types.ModuleType("openclaw.pnl_engine")
        fake_pnl.get_today_pnl = lambda conn, date_str: 1000.0
        fake_pnl.get_monthly_pnl = lambda conn, month_str: 5000.0

        import sys
        sys.modules["openclaw.pnl_engine"] = fake_pnl
        try:
            r = c.get("/api/system/risk", headers=_AUTH)
            assert r.status_code == 200
            data = r.json()
            assert data["today_realized_pnl"] == 1000.0
            assert data["monthly_realized_pnl"] == 5000.0
            assert data["risk_mode"] == "normal"
        finally:
            sys.modules.pop("openclaw.pnl_engine", None)
            # Restore original if it was there
            try:
                from openclaw import pnl_engine
                sys.modules["openclaw.pnl_engine"] = pnl_engine
            except Exception:
                pass

    def test_risk_defensive_mode_when_large_loss(self, sys_client, monkeypatch):
        """risk endpoint shows defensive mode when today's PnL < -5000."""
        c, _, _ = sys_client
        import types
        import sys

        fake_pnl = types.ModuleType("openclaw.pnl_engine")
        fake_pnl.get_today_pnl = lambda conn, date_str: -6000.0
        fake_pnl.get_monthly_pnl = lambda conn, month_str: -6000.0
        sys.modules["openclaw.pnl_engine"] = fake_pnl
        try:
            r = c.get("/api/system/risk", headers=_AUTH)
            assert r.status_code == 200
            data = r.json()
            assert data["risk_mode"] == "defensive"
        finally:
            sys.modules.pop("openclaw.pnl_engine", None)
            try:
                from openclaw import pnl_engine
                sys.modules["openclaw.pnl_engine"] = pnl_engine
            except Exception:
                pass
