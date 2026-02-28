import importlib
import os
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


BACKEND_PATH = Path(__file__).resolve().parents[1] / "frontend" / "backend"


def _init_db(p: Path):
    conn = sqlite3.connect(p)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_traces (
            trace_id TEXT,
            agent TEXT,
            model TEXT,
            prompt TEXT,
            response TEXT,
            latency_ms INTEGER,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            tool_calls_json TEXT,
            confidence REAL,
            created_at INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_proposals (
            proposal_id TEXT PRIMARY KEY,
            generated_by TEXT,
            target_rule TEXT,
            rule_category TEXT,
            current_value TEXT,
            proposed_value TEXT,
            supporting_evidence TEXT,
            confidence REAL,
            requires_human_approval INTEGER,
            status TEXT,
            expires_at INTEGER,
            proposal_json TEXT,
            created_at INTEGER,
            decided_at INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS version_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_id TEXT,
            action TEXT,
            performed_by TEXT,
            details TEXT,
            performed_at TEXT
        )
        """
    )

    conn.execute(
        "INSERT INTO strategy_proposals(proposal_id, status, confidence, created_at) VALUES(?, ?, ?, ?)",
        ("p1", "pending", 0.77, 1700000000),
    )
    conn.execute(
        "INSERT INTO llm_traces(trace_id, agent, model, created_at) VALUES(?, ?, ?, ?)",
        ("t1", "sentinel", "test", 1700000001),
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = tmp_path / "trades.db"
    _init_db(db)

    monkeypatch.setenv("DB_PATH", str(db))
    monkeypatch.setenv("STRATEGY_OPS_TOKEN", "secret")

    # Ensure backend package is importable
    sys.path.insert(0, str(BACKEND_PATH))

    # Import after env set, to ensure app.db resolves DB_PATH correctly.
    import app.db as dbmod
    import app.main as mainmod

    importlib.reload(dbmod)
    importlib.reload(mainmod)

    return TestClient(mainmod.app)


def test_get_proposals(client):
    r = client.get("/api/strategy/proposals")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert len(body["data"]) == 1
    assert body["data"][0]["proposal_id"] == "p1"


def test_get_logs(client):
    r = client.get("/api/strategy/logs")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert len(body["data"]) == 1
    assert body["data"][0]["trace_id"] == "t1"


def test_approve_requires_token(client):
    r = client.post("/api/strategy/p1/approve", json={"actor": "tester", "reason": "ok"})
    assert r.status_code == 401


def test_approve_ok(client):
    r = client.post(
        "/api/strategy/p1/approve",
        json={"actor": "tester", "reason": "ok"},
        headers={"X-OPS-TOKEN": "secret"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["data"]["status"] == "approved"


def test_reject_ok(client):
    r = client.post(
        "/api/strategy/p1/reject",
        json={"actor": "tester", "reason": "no"},
        headers={"X-OPS-TOKEN": "secret"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "rejected"
