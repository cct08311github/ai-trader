from __future__ import annotations

import importlib
import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _init_test_db(path: Path) -> None:
    conn = sqlite3.connect(path.as_posix())
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS strategy_proposals (
                proposal_id TEXT PRIMARY KEY,
                status TEXT,
                created_at INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_traces (
                trace_id TEXT,
                content TEXT,
                created_at INTEGER
            )
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO strategy_proposals(proposal_id, status, created_at) VALUES(?, ?, ?) ",
            ("p1", "pending", 123),
        )
        conn.execute(
            "INSERT INTO llm_traces(trace_id, content, created_at) VALUES(?, ?, ?)",
            ("t1", "hello", 456),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "trades.db"
    _init_test_db(db_path)

    monkeypatch.setenv("DB_PATH", db_path.as_posix())
    monkeypatch.setenv("RATE_LIMIT_RPM", "1000")

    # Reload modules that read env at import-time
    import app.core.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)
    import app.main as main
    importlib.reload(main)

    with TestClient(main.app) as c:
        yield c
