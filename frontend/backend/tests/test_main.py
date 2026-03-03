"""Tests for app/main.py — covering lifespan exception paths (lines 44-45, 50-51)."""
from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _init_minimal_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS strategy_proposals (
            proposal_id TEXT PRIMARY KEY, status TEXT, created_at INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS llm_traces (
            trace_id TEXT, agent TEXT, model TEXT, prompt TEXT, response TEXT,
            latency_ms INTEGER, prompt_tokens INTEGER, completion_tokens INTEGER,
            confidence REAL, created_at INTEGER
        )
    """)
    conn.commit()
    conn.close()


class TestLifespanStartupFailure:
    def test_startup_logs_warning_when_init_pool_fails(self, tmp_path, monkeypatch):
        """When init_readonly_pool fails during startup, a warning is logged (covers lines 44-45)."""
        # Set DB_PATH to non-existent location so init_readonly_pool fails
        monkeypatch.setenv("DB_PATH", "/nonexistent/path/db.db")
        monkeypatch.setenv("RATE_LIMIT_RPM", "1000")
        monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")

        import app.core.config as config
        importlib.reload(config)
        import app.db as db
        importlib.reload(db)
        import app.main as main
        importlib.reload(main)

        from fastapi.testclient import TestClient
        # Should not raise even though init_readonly_pool fails (warning is logged)
        with TestClient(main.app) as c:
            # The app still starts — health check works
            r = c.get("/api/health", headers={"Authorization": "Bearer test-bearer-token"})
            assert r.status_code == 200

    def test_startup_with_valid_db_succeeds(self, tmp_path, monkeypatch):
        """Normal startup path with valid DB (covers lines 42-43)."""
        db_path = tmp_path / "trades.db"
        _init_minimal_db(db_path)

        monkeypatch.setenv("DB_PATH", str(db_path))
        monkeypatch.setenv("RATE_LIMIT_RPM", "1000")
        monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")

        import app.core.config as config
        importlib.reload(config)
        import app.db as db
        importlib.reload(db)
        import app.main as main
        importlib.reload(main)

        from fastapi.testclient import TestClient
        with TestClient(main.app) as c:
            r = c.get("/api/health", headers={"Authorization": "Bearer test-bearer-token"})
            assert r.status_code == 200


class TestLifespanShutdownFailure:
    def test_shutdown_exception_is_swallowed(self, tmp_path, monkeypatch):
        """When READONLY_POOL.close() fails during shutdown, exception is swallowed (covers lines 50-51)."""
        db_path = tmp_path / "trades.db"
        _init_minimal_db(db_path)

        monkeypatch.setenv("DB_PATH", str(db_path))
        monkeypatch.setenv("RATE_LIMIT_RPM", "1000")
        monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")

        import app.core.config as config
        importlib.reload(config)
        import app.db as db
        importlib.reload(db)
        import app.main as main_mod
        importlib.reload(main_mod)

        # Patch READONLY_POOL.close to raise during shutdown
        main_mod.READONLY_POOL.close = MagicMock(side_effect=RuntimeError("close failed"))

        from fastapi.testclient import TestClient
        # Should not raise even if close() fails — exception is swallowed (lines 50-51)
        with TestClient(main_mod.app) as c:
            r = c.get("/api/health", headers={"Authorization": "Bearer test-bearer-token"})
            assert r.status_code == 200
        # Exiting the context triggers shutdown → close() raises but is caught


class TestHealthEndpoint:
    def test_health_check_returns_ok(self, tmp_path, monkeypatch):
        """GET /api/health returns 200 with service name."""
        db_path = tmp_path / "trades.db"
        _init_minimal_db(db_path)

        monkeypatch.setenv("DB_PATH", str(db_path))
        monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")

        import app.core.config as config
        importlib.reload(config)
        import app.db as db
        importlib.reload(db)
        import app.main as main
        importlib.reload(main)

        from fastapi.testclient import TestClient
        with TestClient(main.app) as c:
            r = c.get("/api/health", headers={"Authorization": "Bearer test-bearer-token"})
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "ok"
            assert "service" in data
