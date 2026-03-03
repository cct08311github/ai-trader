import json
import sqlite3
import time
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_with_analysis(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")
    db_path = str(tmp_path / "data" / "sqlite" / "trades.db")
    import os; os.makedirs(str(tmp_path / "data" / "sqlite"))
    monkeypatch.setenv("DB_PATH", db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE eod_analysis_reports (
            trade_date TEXT PRIMARY KEY,
            generated_at INTEGER NOT NULL,
            market_summary TEXT NOT NULL,
            technical TEXT NOT NULL,
            strategy TEXT NOT NULL,
            raw_prompt TEXT,
            model_used TEXT NOT NULL
        )
    """)
    conn.execute(
        "INSERT INTO eod_analysis_reports VALUES (?,?,?,?,?,?,?)",
        ("2026-03-03", int(time.time()*1000),
         '{"sentiment":"neutral"}', '{"2330":{}}',
         '{"summary":"test"}', None, "gemini-2.5-flash")
    )
    conn.commit()
    conn.close()

    import importlib
    import app.db as db_mod
    importlib.reload(db_mod)
    from app.main import app
    return TestClient(app)


def test_analysis_latest_unauthorized(client_with_analysis):
    r = client_with_analysis.get("/api/analysis/latest")
    assert r.status_code == 401


def test_analysis_latest_ok(client_with_analysis):
    r = client_with_analysis.get(
        "/api/analysis/latest",
        headers={"Authorization": "Bearer test-bearer-token"}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["trade_date"] == "2026-03-03"
    assert "market_summary" in data
    assert "technical" in data
    assert "strategy" in data


def test_analysis_by_date_not_found(client_with_analysis):
    r = client_with_analysis.get(
        "/api/analysis/2099-01-01",
        headers={"Authorization": "Bearer test-bearer-token"}
    )
    assert r.status_code == 404


def test_analysis_dates(client_with_analysis):
    r = client_with_analysis.get(
        "/api/analysis/dates",
        headers={"Authorization": "Bearer test-bearer-token"}
    )
    assert r.status_code == 200
    assert "2026-03-03" in r.json()
