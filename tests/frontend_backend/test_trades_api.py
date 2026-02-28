from __future__ import annotations

import importlib
import os
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "trades.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE trades (
            id TEXT PRIMARY KEY,
            symbol TEXT,
            action TEXT,
            quantity INTEGER,
            price REAL,
            fee REAL,
            tax REAL,
            pnl REAL,
            timestamp TEXT,
            agent_id TEXT,
            decision_id TEXT
        );
        """
    )
    rows = [
        (
            "t1",
            "2330",
            "buy",
            1,
            100.0,
            1.0,
            0.2,
            0.0,
            "2026-02-27T09:00:00Z",
            "agentA",
            "d1",
        ),
        (
            "t2",
            "2330",
            "sell",
            1,
            110.0,
            1.0,
            0.2,
            9.0,
            "2026-02-28T09:00:00Z",
            "agentA",
            "d2",
        ),
        (
            "t3",
            "0050",
            "buy",
            2,
            50.0,
            0.5,
            0.1,
            -1.0,
            "2026-02-26T09:00:00Z",
            "agentB",
            "d3",
        ),
    ]
    conn.executemany(
        """
        INSERT INTO trades (id, symbol, action, quantity, price, fee, tax, pnl, timestamp, agent_id, decision_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture()
def client(tmp_path: Path):
    db_path = _make_db(tmp_path)

    # Make frontend backend importable
    backend_root = Path(__file__).resolve().parents[2] / "frontend" / "backend"
    sys.path.insert(0, str(backend_root))

    os.environ["DB_PATH"] = str(db_path)

    # Import after setting env
    import app.db as db  # noqa: E402
    import app.main as main  # noqa: E402

    importlib.reload(db)
    importlib.reload(main)

    with TestClient(main.app) as c:
        yield c

    sys.path = [p for p in sys.path if p != str(backend_root)]


def test_list_trades_default_sort_time_desc(client: TestClient):
    res = client.get("/api/portfolio/trades")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["total"] == 3
    assert [it["id"] for it in data["items"]] == ["t2", "t1", "t3"]
    assert all(it["status"] == "filled" for it in data["items"])


def test_list_trades_filter_symbol_and_type(client: TestClient):
    res = client.get("/api/portfolio/trades", params={"symbol": "2330", "type": "buy"})
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == "t1"


def test_list_trades_time_range_and_pagination(client: TestClient):
    res = client.get(
        "/api/portfolio/trades",
        params={"start": "2026-02-27T00:00:00Z", "end": "2026-02-28T23:59:59Z", "limit": 1, "offset": 0},
    )
    data = res.json()
    assert data["total"] == 2
    assert len(data["items"]) == 1
    assert data["items"][0]["id"] == "t2"


def test_list_trades_sort_by_amount_asc(client: TestClient):
    res = client.get("/api/portfolio/trades", params={"sort_by": "amount", "sort_dir": "asc"})
    data = res.json()
    ids = [it["id"] for it in data["items"]]
    # amounts: t1=100, t2=110, t3=100
    assert ids[0] in {"t1", "t3"}
    assert ids[-1] == "t2"
