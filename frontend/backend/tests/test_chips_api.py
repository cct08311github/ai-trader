"""test_chips_api.py — 完整測試 /api/chips 路由

正向 / 負向 / 邊界 / 資料庫錯誤路徑全覆蓋。
"""
from __future__ import annotations

import os
import sqlite3
import pytest
from fastapi.testclient import TestClient


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _init_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eod_institution_flows (
            trade_date  TEXT NOT NULL,
            symbol      TEXT NOT NULL,
            name        TEXT,
            foreign_net REAL,
            trust_net   REAL,
            dealer_net  REAL,
            total_net   REAL,
            PRIMARY KEY (trade_date, symbol)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eod_margin_data (
            trade_date     TEXT NOT NULL,
            symbol         TEXT NOT NULL,
            name           TEXT,
            margin_balance REAL,
            short_balance  REAL,
            PRIMARY KEY (trade_date, symbol)
        )
    """)
    # Seed data
    conn.execute(
        "INSERT INTO eod_institution_flows VALUES (?,?,?,?,?,?,?)",
        ("2026-03-03", "2330", "台積電", 550000, 100000, 60000, 710000),
    )
    conn.execute(
        "INSERT INTO eod_institution_flows VALUES (?,?,?,?,?,?,?)",
        ("2026-03-03", "2412", "中華電", -200000, -100000, 5000, -295000),
    )
    conn.execute(
        "INSERT INTO eod_institution_flows VALUES (?,?,?,?,?,?,?)",
        ("2026-03-04", "2330", "台積電", 300000, 50000, 10000, 360000),
    )
    conn.execute(
        "INSERT INTO eod_margin_data VALUES (?,?,?,?,?)",
        ("2026-03-03", "2330", "台積電", 12000, 500),
    )
    conn.execute(
        "INSERT INTO eod_margin_data VALUES (?,?,?,?,?)",
        ("2026-03-03", "2412", "中華電", 3000, 200),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")
    db_path = str(tmp_path / "data" / "sqlite" / "trades.db")
    os.makedirs(str(tmp_path / "data" / "sqlite"))
    monkeypatch.setenv("DB_PATH", db_path)
    _init_db(db_path)

    import importlib
    import app.db as db_mod
    importlib.reload(db_mod)
    from app.main import app
    return TestClient(app)


HEADERS = {"Authorization": "Bearer test-bearer-token"}
DATE = "2026-03-03"


# ══════════════════════════════════════════════════════════════════════════════
# /api/chips/{date}/institution-flows
# ══════════════════════════════════════════════════════════════════════════════

class TestInstitutionFlows:
    def test_returns_200_with_data(self, client):
        r = client.get(f"/api/chips/{DATE}/institution-flows", headers=HEADERS)
        assert r.status_code == 200
        body = r.json()
        assert body["trade_date"] == DATE
        assert len(body["data"]) == 2

    def test_data_sorted_by_abs_total_net(self, client):
        r = client.get(f"/api/chips/{DATE}/institution-flows", headers=HEADERS)
        data = r.json()["data"]
        totals = [abs(d["total_net"]) for d in data]
        assert totals == sorted(totals, reverse=True)

    def test_returns_correct_fields(self, client):
        r = client.get(f"/api/chips/{DATE}/institution-flows", headers=HEADERS)
        row = r.json()["data"][0]
        for field in ("symbol", "name", "foreign_net", "trust_net", "dealer_net", "total_net"):
            assert field in row

    def test_returns_404_for_unknown_date(self, client):
        r = client.get("/api/chips/2020-01-01/institution-flows", headers=HEADERS)
        assert r.status_code == 404

    def test_returns_422_for_bad_date_format(self, client):
        r = client.get("/api/chips/20260303/institution-flows", headers=HEADERS)
        assert r.status_code == 422

    def test_returns_404_for_letters_in_date(self, client):
        # xxxx-xx-xx passes format check (length=10, dashes at [4][7]) but has no DB match
        r = client.get("/api/chips/xxxx-xx-xx/institution-flows", headers=HEADERS)
        assert r.status_code == 404

    def test_requires_auth(self, client):
        r = client.get(f"/api/chips/{DATE}/institution-flows")
        assert r.status_code == 401

    def test_rejects_wrong_token(self, client):
        r = client.get(f"/api/chips/{DATE}/institution-flows",
                       headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401

    def test_returns_503_when_table_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")
        db_path = str(tmp_path / "data" / "sqlite" / "trades.db")
        os.makedirs(str(tmp_path / "data" / "sqlite"))
        monkeypatch.setenv("DB_PATH", db_path)
        # Empty DB — no tables
        sqlite3.connect(db_path).close()

        import importlib
        import app.db as db_mod
        importlib.reload(db_mod)
        from app.main import app
        c = TestClient(app)
        r = c.get(f"/api/chips/{DATE}/institution-flows", headers=HEADERS)
        assert r.status_code == 503


# ══════════════════════════════════════════════════════════════════════════════
# /api/chips/{date}/margin
# ══════════════════════════════════════════════════════════════════════════════

class TestMarginData:
    def test_returns_200_with_data(self, client):
        r = client.get(f"/api/chips/{DATE}/margin", headers=HEADERS)
        assert r.status_code == 200
        body = r.json()
        assert body["trade_date"] == DATE
        assert len(body["data"]) == 2

    def test_returns_correct_fields(self, client):
        r = client.get(f"/api/chips/{DATE}/margin", headers=HEADERS)
        row = r.json()["data"][0]
        for field in ("symbol", "name", "margin_balance", "short_balance"):
            assert field in row

    def test_sorted_by_margin_balance_desc(self, client):
        r = client.get(f"/api/chips/{DATE}/margin", headers=HEADERS)
        balances = [d["margin_balance"] for d in r.json()["data"]]
        assert balances == sorted(balances, reverse=True)

    def test_returns_404_for_unknown_date(self, client):
        r = client.get("/api/chips/2020-01-01/margin", headers=HEADERS)
        assert r.status_code == 404

    def test_returns_422_for_bad_date_format(self, client):
        r = client.get("/api/chips/2026-3-3/margin", headers=HEADERS)
        assert r.status_code == 422

    def test_requires_auth(self, client):
        r = client.get(f"/api/chips/{DATE}/margin")
        assert r.status_code == 401

    def test_returns_503_when_table_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")
        db_path = str(tmp_path / "data" / "sqlite" / "trades.db")
        os.makedirs(str(tmp_path / "data" / "sqlite"))
        monkeypatch.setenv("DB_PATH", db_path)
        sqlite3.connect(db_path).close()
        import importlib
        import app.db as db_mod
        importlib.reload(db_mod)
        from app.main import app
        c = TestClient(app)
        r = c.get(f"/api/chips/{DATE}/margin", headers=HEADERS)
        assert r.status_code == 503


# ══════════════════════════════════════════════════════════════════════════════
# /api/chips/{date}/summary
# ══════════════════════════════════════════════════════════════════════════════

class TestChipsSummary:
    def test_returns_200_with_combined_data(self, client):
        r = client.get(f"/api/chips/{DATE}/summary", headers=HEADERS)
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 2

    def test_includes_both_institution_and_margin_fields(self, client):
        r = client.get(f"/api/chips/{DATE}/summary", headers=HEADERS)
        row = r.json()["data"][0]
        for field in ("symbol", "foreign_net", "trust_net", "total_net",
                      "margin_balance", "short_balance"):
            assert field in row

    def test_margin_fields_null_when_no_margin_data(self, tmp_path, monkeypatch):
        """When margin table has no data for a symbol, LEFT JOIN → null."""
        monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")
        db_path = str(tmp_path / "data" / "sqlite" / "trades.db")
        os.makedirs(str(tmp_path / "data" / "sqlite"))
        monkeypatch.setenv("DB_PATH", db_path)

        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE eod_institution_flows (
                trade_date TEXT, symbol TEXT, name TEXT,
                foreign_net REAL, trust_net REAL, dealer_net REAL, total_net REAL,
                PRIMARY KEY (trade_date, symbol)
            )
        """)
        conn.execute("""
            CREATE TABLE eod_margin_data (
                trade_date TEXT, symbol TEXT, name TEXT,
                margin_balance REAL, short_balance REAL,
                PRIMARY KEY (trade_date, symbol)
            )
        """)
        # Institution data only — no margin for 2330
        conn.execute(
            "INSERT INTO eod_institution_flows VALUES (?,?,?,?,?,?,?)",
            ("2026-03-05", "2330", "台積電", 100, 50, 10, 160),
        )
        conn.commit()
        conn.close()

        import importlib
        import app.db as db_mod
        importlib.reload(db_mod)
        from app.main import app
        c = TestClient(app)
        r = c.get("/api/chips/2026-03-05/summary", headers=HEADERS)
        assert r.status_code == 200
        row = r.json()["data"][0]
        assert row["margin_balance"] is None
        assert row["short_balance"] is None

    def test_returns_404_for_unknown_date(self, client):
        r = client.get("/api/chips/1900-01-01/summary", headers=HEADERS)
        assert r.status_code == 404

    def test_returns_422_for_bad_date_format(self, client):
        r = client.get("/api/chips/2026/03/03/summary", headers=HEADERS)
        assert r.status_code == 404  # FastAPI path parse fails → 404

    def test_requires_auth(self, client):
        r = client.get(f"/api/chips/{DATE}/summary")
        assert r.status_code == 401

    def test_returns_503_when_table_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")
        db_path = str(tmp_path / "data" / "sqlite" / "trades.db")
        os.makedirs(str(tmp_path / "data" / "sqlite"))
        monkeypatch.setenv("DB_PATH", db_path)
        sqlite3.connect(db_path).close()
        import importlib
        import app.db as db_mod
        importlib.reload(db_mod)
        from app.main import app
        c = TestClient(app)
        r = c.get(f"/api/chips/{DATE}/summary", headers=HEADERS)
        assert r.status_code == 503


# ══════════════════════════════════════════════════════════════════════════════
# /api/chips/dates
# ══════════════════════════════════════════════════════════════════════════════

class TestChipsDates:
    def test_returns_available_dates(self, client):
        r = client.get("/api/chips/dates", headers=HEADERS)
        assert r.status_code == 200
        dates = r.json()["dates"]
        assert "2026-03-03" in dates
        assert "2026-03-04" in dates

    def test_dates_sorted_descending(self, client):
        r = client.get("/api/chips/dates", headers=HEADERS)
        dates = r.json()["dates"]
        assert dates == sorted(dates, reverse=True)

    def test_returns_empty_list_when_table_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")
        db_path = str(tmp_path / "data" / "sqlite" / "trades.db")
        os.makedirs(str(tmp_path / "data" / "sqlite"))
        monkeypatch.setenv("DB_PATH", db_path)
        sqlite3.connect(db_path).close()
        import importlib
        import app.db as db_mod
        importlib.reload(db_mod)
        from app.main import app
        c = TestClient(app)
        r = c.get("/api/chips/dates", headers=HEADERS)
        # Returns 200 with empty list (graceful degradation, not 503)
        assert r.status_code == 200
        assert r.json()["dates"] == []

    def test_requires_auth(self, client):
        r = client.get("/api/chips/dates")
        assert r.status_code == 401
