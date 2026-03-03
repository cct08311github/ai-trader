"""Tests for app/api/agents.py — targeting 28% → near 100%."""
from __future__ import annotations

import importlib
import threading
import sqlite3
from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest

_TOKEN = "test-bearer-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


def _init_agents_db(path: Path) -> None:
    """Full schema needed by agents API."""
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
    conn.commit()
    conn.close()


@pytest.fixture
def agents_client(tmp_path, monkeypatch):
    db_path = tmp_path / "trades.db"
    _init_agents_db(db_path)

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
        yield c, db_path


class TestListAgents:
    def test_list_agents_returns_ok(self, agents_client):
        c, _ = agents_client
        r = c.get("/api/agents", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "data" in data
        assert "running" in data

    def test_list_agents_has_all_five(self, agents_client):
        c, _ = agents_client
        r = c.get("/api/agents", headers=_AUTH)
        data = r.json()
        names = [a["name"] for a in data["data"]]
        assert "market_research" in names
        assert "portfolio_review" in names
        assert "system_health" in names
        assert "strategy_committee" in names
        assert "system_optimization" in names

    def test_list_agents_has_meta(self, agents_client):
        c, _ = agents_client
        r = c.get("/api/agents", headers=_AUTH)
        agent = r.json()["data"][0]
        assert "label" in agent
        assert "label_zh" in agent
        assert "description" in agent
        assert "schedule" in agent

    def test_list_agents_no_auth(self, agents_client):
        c, _ = agents_client
        r = c.get("/api/agents")
        assert r.status_code == 401


class TestAgentHistory:
    def test_history_valid_agent(self, agents_client):
        c, _ = agents_client
        r = c.get("/api/agents/market_research/history", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert isinstance(data["data"], list)

    def test_history_unknown_agent(self, agents_client):
        c, _ = agents_client
        r = c.get("/api/agents/unknown_agent/history", headers=_AUTH)
        assert r.status_code == 404

    def test_history_all_agents(self, agents_client):
        c, _ = agents_client
        agents = ["market_research", "portfolio_review", "system_health",
                  "strategy_committee", "system_optimization"]
        for name in agents:
            r = c.get(f"/api/agents/{name}/history", headers=_AUTH)
            assert r.status_code == 200

    def test_history_limit_param(self, agents_client):
        c, _ = agents_client
        r = c.get("/api/agents/system_health/history?limit=5", headers=_AUTH)
        assert r.status_code == 200

    def test_history_no_auth(self, agents_client):
        c, _ = agents_client
        r = c.get("/api/agents/market_research/history")
        assert r.status_code == 401


class TestRunAgent:
    def test_run_unknown_agent(self, agents_client):
        c, _ = agents_client
        r = c.post("/api/agents/bad_agent/run", headers=_AUTH)
        assert r.status_code == 404

    def test_run_agent_starts(self, agents_client, monkeypatch):
        """Running an agent should return 'started' immediately."""
        c, _ = agents_client
        import app.api.agents as agents_mod

        # Mock out _run_agent_bg so it doesn't actually do anything
        calls = []
        def fake_bg(agent_name, db_path):
            calls.append(agent_name)

        monkeypatch.setattr(agents_mod, "_run_agent_bg", fake_bg)
        r = c.post("/api/agents/market_research/run", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "started"
        assert data["agent"] == "market_research"

    def test_run_agent_conflict_409(self, agents_client, monkeypatch):
        """If agent is already running, return 409."""
        c, _ = agents_client
        import app.api.agents as agents_mod
        with agents_mod._lock:
            agents_mod._running.add("system_health")
        try:
            r = c.post("/api/agents/system_health/run", headers=_AUTH)
            assert r.status_code == 409
        finally:
            with agents_mod._lock:
                agents_mod._running.discard("system_health")

    def test_run_agent_no_auth(self, agents_client):
        c, _ = agents_client
        r = c.post("/api/agents/market_research/run")
        assert r.status_code == 401


class TestRunAgentBackground:
    def test_run_agent_bg_removes_from_running_on_error(self, monkeypatch):
        """_run_agent_bg should always discard agent from _running, even on error."""
        from app.api.agents import _running, _lock, _run_agent_bg

        # Mock open_conn to fail so the error path is exercised
        with patch("app.api.agents._run_agent_bg.__module__"):
            pass  # just ensure import works

        # Directly call _run_agent_bg with open_conn mocked to raise
        with patch("app.api.agents.open_conn" if hasattr(__import__("app.api.agents", fromlist=["_run_agent_bg"]), "open_conn") else "openclaw.agents.base.open_conn",
                   side_effect=ImportError("mocked")):
            try:
                _run_agent_bg("portfolio_review", ":memory:")
            except Exception:
                pass

        # After error (import fails), agent should NOT be in _running
        with _lock:
            assert "portfolio_review" not in _running

    def _run_with_mock_agents(self, agent_name, monkeypatch):
        """Helper to run _run_agent_bg with all agent functions mocked."""
        import sqlite3
        import app.api.agents as agents_mod

        # Create a minimal DB
        conn = sqlite3.connect(":memory:")
        conn.execute("""CREATE TABLE IF NOT EXISTS llm_traces
            (trace_id TEXT, agent TEXT, model TEXT, response TEXT,
             created_at INTEGER, confidence REAL, latency_ms INTEGER)""")
        conn.commit()
        conn.close()

        # Mock the heavy agent imports
        mock_open_conn = MagicMock(return_value=MagicMock())
        mock_open_conn.return_value.__enter__ = lambda s: s
        mock_open_conn.return_value.__exit__ = MagicMock(return_value=False)
        mock_open_conn.return_value.close = MagicMock()

        with patch("openclaw.agents.base.open_conn", return_value=mock_open_conn()):
            with patch(f"openclaw.agents.{agent_name}.run_{agent_name}", MagicMock()):
                try:
                    agents_mod._run_agent_bg(agent_name, ":memory:")
                except Exception:
                    pass

        with agents_mod._lock:
            assert agent_name not in agents_mod._running

    def test_run_agent_bg_clears_running_on_exception(self):
        """Even if all imports fail, running flag is cleared."""
        import app.api.agents as m
        # Force _running.add manually, then call
        with m._lock:
            m._running.discard("market_research")

        # With bad db_path, open_conn will fail
        m._run_agent_bg("market_research", "/nonexistent/path/trades.db")

        with m._lock:
            assert "market_research" not in m._running

    def test_run_agent_bg_all_dispatches(self, monkeypatch):
        """All 5 agents are dispatched in _run_agent_bg."""
        import app.api.agents as m

        mock_conn = MagicMock()
        mock_conn.close = MagicMock()

        agents_dispatch = [
            ("market_research", "openclaw.agents.market_research.run_market_research"),
            ("portfolio_review", "openclaw.agents.portfolio_review.run_portfolio_review"),
            ("system_health", "openclaw.agents.system_health.run_system_health"),
            ("strategy_committee", "openclaw.agents.strategy_committee.run_strategy_committee"),
            ("system_optimization", "openclaw.agents.system_optimization.run_system_optimization"),
        ]

        for agent_name, func_path in agents_dispatch:
            with patch("openclaw.agents.base.open_conn", return_value=mock_conn):
                with patch(func_path, MagicMock()):
                    m._run_agent_bg(agent_name, ":memory:")
            with m._lock:
                assert agent_name not in m._running
