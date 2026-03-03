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


# ── 缺口分支覆蓋 ──────────────────────────────────────

@pytest.fixture
def empty_client(tmp_path, monkeypatch):
    """空資料表的 client：用於測試 get_latest 回傳 404。"""
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
    conn.commit()
    conn.close()

    import importlib
    import app.db as db_mod
    importlib.reload(db_mod)
    from app.main import app
    return TestClient(app)


def test_get_latest_returns_404_when_table_empty(empty_client):
    """eod_analysis_reports 表為空時，/latest 應回傳 404（line 43）。"""
    r = empty_client.get(
        "/api/analysis/latest",
        headers={"Authorization": "Bearer test-bearer-token"}
    )
    assert r.status_code == 404
    assert "No analysis report" in r.json()["detail"]


def test_get_by_date_returns_404_for_missing_date(client_with_analysis):
    """指定日期不存在時，/api/analysis/{date} 應回傳 404（line 61）。"""
    r = client_with_analysis.get(
        "/api/analysis/1900-01-01",
        headers={"Authorization": "Bearer test-bearer-token"}
    )
    assert r.status_code == 404
    assert "No report" in r.json()["detail"]


def test_get_by_date_returns_200_for_existing_date(client_with_analysis):
    """指定存在日期時，/api/analysis/{date} 應回傳 200 及完整資料（line 62 return）。"""
    r = client_with_analysis.get(
        "/api/analysis/2026-03-03",
        headers={"Authorization": "Bearer test-bearer-token"}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["trade_date"] == "2026-03-03"
    assert "market_summary" in data


def test_row_to_dict_handles_invalid_json_gracefully(client_with_analysis, tmp_path, monkeypatch):
    """market_summary/technical/strategy 含非 JSON 字串時，_row_to_dict 應靜默跳過（lines 32-33）。"""
    # 直接對 _row_to_dict 做 unit test，不需要 HTTP
    from app.api.analysis import _row_to_dict

    class FakeRow(dict):
        """模擬 sqlite3.Row，讓 dict(row) 可用。"""
        def keys(self):
            return super().keys()

    row_data = {
        "trade_date": "2026-03-03",
        "generated_at": 0,
        "market_summary": "NOT_VALID_JSON{{{",   # 無效 JSON
        "technical": '{"2330": {}}',              # 正常 JSON
        "strategy": None,                          # TypeError when json.loads(None)
        "raw_prompt": None,
        "model_used": "test",
    }

    result = _row_to_dict(row_data)
    # 無效 JSON → 保持原始字串（靜默 pass）
    assert result["market_summary"] == "NOT_VALID_JSON{{{"
    # 正常 JSON → 解析為 dict
    assert result["technical"] == {"2330": {}}
    # None → json.loads(None) 拋 TypeError → 靜默 pass
    assert result["strategy"] is None


def test_conn_dep_returns_503_on_file_not_found(tmp_path, monkeypatch):
    """DB 路徑不存在時，conn_dep 應回傳 503（line 20-21）。"""
    monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")
    # 指向不存在的路徑
    monkeypatch.setenv("DB_PATH", "/nonexistent/path/trades.db")

    import importlib
    import app.db as db_mod
    importlib.reload(db_mod)
    from app.main import app
    client = TestClient(app)

    r = client.get(
        "/api/analysis/latest",
        headers={"Authorization": "Bearer test-bearer-token"}
    )
    assert r.status_code == 503


def test_conn_dep_returns_500_on_unexpected_error(monkeypatch):
    """DB get_conn 拋出非 FileNotFoundError 的例外時，conn_dep 應回傳 500（lines 22-23）。"""
    monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")

    import importlib
    import app.db as db_mod
    importlib.reload(db_mod)

    from app.main import app
    from contextlib import contextmanager

    # patch db.get_conn 讓它在 context manager 進入時拋出 RuntimeError
    @contextmanager
    def broken_get_conn(*args, **kwargs):
        raise RuntimeError("unexpected DB failure")
        yield None  # noqa: unreachable

    monkeypatch.setattr(db_mod, "get_conn", broken_get_conn)

    # conn_dep 使用 db.get_conn，但 analysis.py import 的是模組參考
    import app.api.analysis as aa
    monkeypatch.setattr(aa, "db", db_mod)

    from fastapi.testclient import TestClient as TC
    client = TC(app)
    r = client.get(
        "/api/analysis/latest",
        headers={"Authorization": "Bearer test-bearer-token"},
    )
    assert r.status_code == 500
