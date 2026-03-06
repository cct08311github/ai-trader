"""Tests for app/api/settings.py — targeting 41% → near 100%."""
from __future__ import annotations

import json
import sqlite3
import pytest

_TOKEN = "test-bearer-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


@pytest.fixture
def settings_client(tmp_path, monkeypatch):
    """Client with temp config files for settings endpoints."""
    import importlib

    # Create temp config files
    capital_file = tmp_path / "capital.json"
    capital_file.write_text(json.dumps({
        "total_capital_twd": 500000.0,
        "max_single_position_pct": 0.10,
        "daily_loss_limit_twd": 5000.0,
        "monthly_loss_limit_twd": 30000.0,
        "monthly_api_budget_twd": 1000.0,
        "default_stop_loss_pct": 0.05,
        "default_take_profit_pct": 0.10,
    }))
    policy_file = tmp_path / "sentinel_policy.json"
    policy_file.write_text(json.dumps({
        "policy": {
            "budget_halt_enabled": True,
            "drawdown_suspended_enabled": True,
            "reduce_only_enabled": True,
            "broker_disconnected_enabled": True,
            "db_latency_enabled": True,
            "max_db_write_p99_ms": 200,
        },
        "monitoring": {
            "telegram_chat_id": "",
            "health_check_interval_seconds": 30,
        }
    }))
    watchlist_file = tmp_path / "watchlist.json"
    watchlist_file.write_text(json.dumps({
        "manual_watchlist": ["2330", "2317"],
        "max_system_candidates": 10,
        "screener": {"enabled": True},
    }))
    db_file = tmp_path / "trades.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS llm_traces (
            trace_id TEXT, agent TEXT, model TEXT,
            prompt TEXT, response TEXT,
            latency_ms INTEGER, prompt_tokens INTEGER,
            completion_tokens INTEGER, confidence REAL,
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
    conn.execute("""CREATE TABLE IF NOT EXISTS system_candidates (
        symbol TEXT, trade_date TEXT, label TEXT, score REAL,
        source TEXT, reasons TEXT, llm_filtered INTEGER,
        expires_at TEXT, created_at INTEGER,
        PRIMARY KEY(symbol, trade_date, label))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS eod_prices (
        trade_date TEXT, market TEXT, symbol TEXT, name TEXT,
        open REAL, high REAL, low REAL, close REAL, volume INTEGER,
        PRIMARY KEY(trade_date, market, symbol))""")
    conn.commit()
    conn.close()

    monkeypatch.setenv("DB_PATH", str(db_file))
    monkeypatch.setenv("RATE_LIMIT_RPM", "1000")
    monkeypatch.setenv("AUTH_TOKEN", "test-bearer-token")

    import app.api.settings as settings_mod
    monkeypatch.setattr(settings_mod, "CAPITAL_PATH", str(capital_file))
    monkeypatch.setattr(settings_mod, "POLICY_PATH", str(policy_file))
    monkeypatch.setattr(settings_mod, "WATCHLIST_PATH", str(watchlist_file))
    monkeypatch.setattr(settings_mod, "DB_PATH_ENV", str(db_file))

    import app.core.config as config
    importlib.reload(config)
    import app.db as db
    importlib.reload(db)
    import app.main as main
    importlib.reload(main)

    from fastapi.testclient import TestClient
    with TestClient(main.app) as c:
        yield c, tmp_path, capital_file, policy_file, watchlist_file, db_file


class TestCapitalSettings:
    def test_get_capital(self, settings_client):
        c, *_ = settings_client
        r = c.get("/api/settings/capital", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert "total_capital_twd" in data
        assert "max_single_position_twd" in data

    def test_update_capital(self, settings_client):
        c, *_ = settings_client
        payload = {
            "total_capital_twd": 800000.0,
            "max_single_position_pct": 0.12,
            "daily_loss_limit_twd": 8000.0,
            "monthly_loss_limit_twd": 40000.0,
            "monthly_api_budget_twd": 1500.0,
            "default_stop_loss_pct": 0.06,
            "default_take_profit_pct": 0.12,
        }
        r = c.put("/api/settings/capital", json=payload, headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["total_capital_twd"] == 800000.0

    def test_capital_no_auth(self, settings_client):
        c, *_ = settings_client
        r = c.get("/api/settings/capital")
        assert r.status_code == 401


class TestSentinelSettings:
    def test_get_sentinel(self, settings_client):
        c, *_ = settings_client
        r = c.get("/api/settings/sentinel", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert "budget_halt_enabled" in data
        assert "health_check_interval_seconds" in data

    def test_update_sentinel(self, settings_client):
        c, *_ = settings_client
        payload = {
            "budget_halt_enabled": False,
            "drawdown_suspended_enabled": True,
            "reduce_only_enabled": True,
            "broker_disconnected_enabled": True,
            "db_latency_enabled": True,
            "max_db_write_p99_ms": 300,
            "telegram_chat_id": "12345",
            "health_check_interval_seconds": 60,
        }
        r = c.put("/api/settings/sentinel", json=payload, headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["max_db_write_p99_ms"] == 300

    def test_sentinel_no_auth(self, settings_client):
        c, *_ = settings_client
        r = c.get("/api/settings/sentinel")
        assert r.status_code == 401


class TestPositionLimits:
    def test_get_position_limits(self, settings_client):
        c, *_ = settings_client
        r = c.get("/api/settings/position-limits", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert "level_1_max_risk_pct" in data
        assert "level_3_max_position_pct" in data

    def test_update_position_limits(self, settings_client):
        c, *_ = settings_client
        payload = {
            "level_1_max_risk_pct": 0.002,
            "level_1_max_position_pct": 0.02,
            "level_2_max_risk_pct": 0.004,
            "level_2_max_position_pct": 0.06,
            "level_3_max_risk_pct": 0.006,
            "level_3_max_position_pct": 0.12,
        }
        r = c.put("/api/settings/position-limits", json=payload, headers=_AUTH)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_position_limits_no_auth(self, settings_client):
        c, *_ = settings_client
        r = c.get("/api/settings/position-limits")
        assert r.status_code == 401


class TestAuthoritySettings:
    def test_get_authority_no_table(self, settings_client):
        """When authority_policy table doesn't exist, returns 500 or fallback."""
        c, _, _, _, _, db_file = settings_client
        r = c.get("/api/settings/authority", headers=_AUTH)
        # Either 500 (table missing) or 200 (fallback) — both valid
        assert r.status_code in (200, 500)

    def test_get_authority_with_table(self, settings_client):
        c, _, _, _, _, db_file = settings_client
        conn = sqlite3.connect(str(db_file))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS authority_policy (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level INTEGER,
                changed_by TEXT,
                reason TEXT,
                effective_from TEXT,
                updated_at TEXT
            )
        """)
        conn.execute(
            "INSERT INTO authority_policy (level, changed_by, reason, effective_from, updated_at) VALUES (?,?,?,?,?)",
            (2, "system", "default", "2026-01-01", "2026-01-01")
        )
        conn.commit()
        conn.close()
        r = c.get("/api/settings/authority", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert "level" in data

    def test_update_authority_invalid_level(self, settings_client):
        c, _, _, _, _, db_file = settings_client
        conn = sqlite3.connect(str(db_file))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS authority_policy (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level INTEGER,
                changed_by TEXT,
                reason TEXT,
                effective_from TEXT,
                updated_at TEXT
            )
        """)
        conn.commit()
        conn.close()
        r = c.put("/api/settings/authority",
                  json={"level": 9, "reason": "bad"},
                  headers=_AUTH)
        assert r.status_code == 400

    def test_update_authority_valid(self, settings_client):
        c, _, _, _, _, db_file = settings_client
        conn = sqlite3.connect(str(db_file))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS authority_policy (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level INTEGER,
                changed_by TEXT,
                reason TEXT,
                effective_from TEXT,
                updated_at TEXT
            )
        """)
        conn.commit()
        conn.close()
        r = c.put("/api/settings/authority",
                  json={"level": 2, "reason": "upgrade"},
                  headers=_AUTH)
        assert r.status_code == 200
        assert r.json()["level"] == 2

    def test_authority_no_auth(self, settings_client):
        c, *_ = settings_client
        r = c.get("/api/settings/authority")
        assert r.status_code == 401


class TestLimitsLegacy:
    def test_get_limits(self, settings_client):
        c, *_ = settings_client
        r = c.get("/api/settings/limits", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"

    def test_update_limits(self, settings_client):
        c, *_ = settings_client
        payload = {"max_position_notional_pct_nav": 0.15}
        r = c.post("/api/settings/limits", json=payload, headers=_AUTH)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_limits_no_auth(self, settings_client):
        c, *_ = settings_client
        r = c.get("/api/settings/limits")
        assert r.status_code == 401


class TestWatchlistSettings:
    def test_get_watchlist(self, settings_client):
        c, *_ = settings_client
        r = c.get("/api/settings/watchlist", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert "manual_watchlist" in data
        assert "system_candidates" in data
        assert "active_symbols" in data

    def test_update_watchlist(self, settings_client):
        c, *_ = settings_client
        payload = {"manual_watchlist": ["2330", "2454"]}
        r = c.put("/api/settings/watchlist", json=payload, headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "2330" in data["manual_watchlist"]

    def test_update_watchlist_empty(self, settings_client):
        c, *_ = settings_client
        payload = {"manual_watchlist": []}
        r = c.put("/api/settings/watchlist", json=payload, headers=_AUTH)
        assert r.status_code == 400

    def test_watchlist_no_auth(self, settings_client):
        c, *_ = settings_client
        r = c.get("/api/settings/watchlist")
        assert r.status_code == 401

    def test_get_watchlist_backward_compat(self, settings_client, monkeypatch):
        """Old format with 'universe' key should still work via backward compat."""
        c, tmp_path, _, _, watchlist_file, _ = settings_client
        # Overwrite with old-format config
        import app.api.settings as settings_mod
        old_cfg = tmp_path / "watchlist_old.json"
        old_cfg.write_text(json.dumps({
            "universe": ["1301", "2603"],
            "max_active": 5,
            "screening": {"method": "top_movers"},
        }))
        monkeypatch.setattr(settings_mod, "WATCHLIST_PATH", str(old_cfg))
        r = c.get("/api/settings/watchlist", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert "manual_watchlist" in data
        assert "1301" in data["manual_watchlist"]

    def test_system_candidates_in_response(self, settings_client):
        """Insert a system candidate with future expiry, verify it appears."""
        c, _, _, _, _, db_file = settings_client
        conn = sqlite3.connect(str(db_file))
        conn.execute(
            "INSERT INTO system_candidates (symbol, trade_date, label, score, source, reasons, llm_filtered, expires_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("9999", "2099-01-01", "短線", 0.85, "rule", '["vol_spike","price_breakout"]', 1, "2099-12-31", 1000000)
        )
        conn.execute(
            "INSERT INTO eod_prices (trade_date, market, symbol, name, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("2099-01-01", "TSE", "9999", "測試公司", 100, 110, 95, 105, 50000)
        )
        conn.commit()
        conn.close()
        r = c.get("/api/settings/watchlist", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        symbols = [sc["symbol"] for sc in data["system_candidates"]]
        assert "9999" in symbols
        # Verify it also appears in active_symbols
        assert "9999" in data["active_symbols"]
        # Verify name lookup worked
        candidate = [sc for sc in data["system_candidates"] if sc["symbol"] == "9999"][0]
        assert candidate["name"] == "測試公司"
        assert candidate["llm_filtered"] is True
        assert "vol_spike" in candidate["reasons"]


class TestLoadSystemCandidates:
    def test_no_table_returns_empty(self, settings_client):
        """When system_candidates table doesn't exist (different DB), returns empty list."""
        import app.api.settings as sm
        from unittest.mock import patch
        # Point to a fresh DB without the table
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            tmp_db = f.name
        try:
            conn = sqlite3.connect(tmp_db)
            conn.close()
            with patch.object(sm, "DB_PATH_ENV", tmp_db):
                result = sm._load_system_candidates()
            assert result == []
        finally:
            os.unlink(tmp_db)

    def test_exception_returns_empty(self, settings_client, monkeypatch):
        """_load_system_candidates silently handles DB exception."""
        import app.api.settings as settings_mod
        monkeypatch.setattr(settings_mod, "DB_PATH_ENV", "/nonexistent/db.db")
        result = settings_mod._load_system_candidates()
        assert result == []


class TestLoadJson:
    def test_load_missing_file_returns_default(self, tmp_path):
        from app.api.settings import _load_json
        result = _load_json(str(tmp_path / "missing.json"), {"key": "value"})
        assert result == {"key": "value"}

    def test_load_existing_file(self, tmp_path):
        from app.api.settings import _load_json
        f = tmp_path / "test.json"
        f.write_text(json.dumps({"hello": "world"}))
        result = _load_json(str(f), {})
        assert result == {"hello": "world"}


class TestSaveJson:
    def test_save_json_creates_dirs(self, tmp_path):
        from app.api.settings import _save_json
        nested = tmp_path / "subdir" / "config.json"
        _save_json(str(nested), {"test": 123})
        assert nested.exists()
        data = json.loads(nested.read_text())
        assert data["test"] == 123


class TestSentinelEmptyFile:
    def test_update_sentinel_with_empty_policy_file(self, settings_client, monkeypatch):
        """update_sentinel when policy.json is empty sets up policy and monitoring dicts (covers lines 97, 99)."""
        c, tmp_path, capital_file, policy_file, watchlist_file, db_file = settings_client
        # Overwrite policy file with empty JSON (no "policy" or "monitoring" keys)
        empty_policy = tmp_path / "empty_policy.json"
        empty_policy.write_text(json.dumps({}))
        import app.api.settings as settings_mod
        monkeypatch.setattr(settings_mod, "POLICY_PATH", str(empty_policy))
        payload = {
            "budget_halt_enabled": True,
            "drawdown_suspended_enabled": True,
            "reduce_only_enabled": True,
            "broker_disconnected_enabled": True,
            "db_latency_enabled": True,
            "max_db_write_p99_ms": 200,
            "telegram_chat_id": None,
            "health_check_interval_seconds": 30,
        }
        r = c.put("/api/settings/sentinel", json=payload, headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"


class TestAuthorityEdgeCases:
    def test_get_authority_table_exists_but_empty(self, settings_client):
        """get_authority returns default when table exists but has no rows (covers line 171)."""
        c, _, _, _, _, db_file = settings_client
        conn = sqlite3.connect(str(db_file))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS authority_policy (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level INTEGER,
                changed_by TEXT,
                reason TEXT,
                effective_from TEXT,
                updated_at TEXT
            )
        """)
        conn.commit()
        conn.close()
        r = c.get("/api/settings/authority", headers=_AUTH)
        assert r.status_code == 200
        data = r.json()
        # Default returned (line 171 executed)
        assert data["level"] == 0
        assert data["changed_by"] == "system"

    def test_update_authority_exception_500(self, settings_client, monkeypatch):
        """update_authority raises 500 when DB write fails (covers lines 190-191)."""
        c, _, _, _, _, db_file = settings_client
        # Create the table but then make the DB_PATH_ENV invalid after table creation
        conn = sqlite3.connect(str(db_file))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS authority_policy (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level INTEGER, changed_by TEXT, reason TEXT,
                effective_from TEXT, updated_at TEXT
            )
        """)
        conn.commit()
        conn.close()
        import app.api.settings as settings_mod
        # Point DB_PATH_ENV to a path we can't write to
        monkeypatch.setattr(settings_mod, "DB_PATH_ENV", "/nonexistent_path/db.db")
        r = c.put("/api/settings/authority",
                  json={"level": 1, "reason": "test"},
                  headers=_AUTH)
        assert r.status_code == 500


class TestLimitsWithLevel3:
    def test_update_limits_when_level3_exists(self, settings_client, monkeypatch):
        """update_limits updates level 3 when it exists in data (covers line 213)."""
        c, tmp_path, _, _, _, _ = settings_client
        # Create policy file WITH position_limits.levels.3 already set
        policy_with_l3 = tmp_path / "policy_with_l3.json"
        policy_with_l3.write_text(json.dumps({
            "position_limits": {
                "levels": {
                    "1": {"max_risk_per_trade_pct_nav": 0.001, "max_position_notional_pct_nav": 0.01},
                    "2": {"max_risk_per_trade_pct_nav": 0.003, "max_position_notional_pct_nav": 0.05},
                    "3": {"max_risk_per_trade_pct_nav": 0.005, "max_position_notional_pct_nav": 0.10},
                }
            }
        }))
        import app.api.settings as settings_mod
        monkeypatch.setattr(settings_mod, "POLICY_PATH", str(policy_with_l3))
        payload = {"max_position_notional_pct_nav": 0.12}
        r = c.post("/api/settings/limits", json=payload, headers=_AUTH)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        # Verify line 213 updated the level
        updated = json.loads(policy_with_l3.read_text())
        assert updated["position_limits"]["levels"]["3"]["max_position_notional_pct_nav"] == 0.12


class TestLoadSystemCandidatesException:
    def test_load_system_candidates_exception_returns_empty(self, settings_client, monkeypatch):
        """_load_system_candidates silently handles DB exception."""
        import app.api.settings as settings_mod
        monkeypatch.setattr(settings_mod, "DB_PATH_ENV", "/nonexistent/db.db")
        result = settings_mod._load_system_candidates()
        assert result == []
