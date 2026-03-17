from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openclaw.path_utils import get_repo_root

# Ensure `import app.*` works no matter where pytest rootdir is.
BACKEND_ROOT = get_repo_root()
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


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
            """
            CREATE TABLE IF NOT EXISTS pm_reviews (
                review_id TEXT PRIMARY KEY,
                review_date TEXT NOT NULL,
                approved INTEGER NOT NULL,
                confidence REAL NOT NULL,
                source TEXT NOT NULL,
                reason TEXT,
                recommended_action TEXT,
                bull_case TEXT,
                bear_case TEXT,
                neutral_case TEXT,
                consensus_points TEXT,
                divergence_points TEXT,
                reviewed_at INTEGER NOT NULL,
                llm_trace_id TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pm_reviews_date ON pm_reviews(review_date DESC)"
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
    monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")

    # Reload modules that read env at import-time
    import app.core.config as config

    importlib.reload(config)
    import app.db as db

    importlib.reload(db)
    import app.main as main

    importlib.reload(main)

    with TestClient(main.app) as c:
        yield c
