"""Tests for src/openclaw/db_router.py"""

import os
import sqlite3
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_db_dir(tmp_path, monkeypatch):
    """Redirect DB_DIR to a temp directory for every test so we never touch
    the real ~/.openclaw/db directory."""
    monkeypatch.setenv("OPENCLAW_HOME", str(tmp_path))
    # Re-import the module so module-level DB_DIR picks up the new env var.
    import importlib
    import openclaw.db_router as dbr
    importlib.reload(dbr)
    yield dbr


# ---------------------------------------------------------------------------
# get_db_path
# ---------------------------------------------------------------------------

class TestGetDbPath:
    def test_ticks_domain(self, patch_db_dir):
        dbr = patch_db_dir
        p = dbr.get_db_path("ticks")
        assert p.name == "ticks.db"

    def test_market_data_alias(self, patch_db_dir):
        dbr = patch_db_dir
        p = dbr.get_db_path("market_data")
        assert p.name == "ticks.db"

    def test_trades_domain(self, patch_db_dir):
        dbr = patch_db_dir
        p = dbr.get_db_path("trades")
        assert p.name == "trades.db"

    def test_execution_alias(self, patch_db_dir):
        dbr = patch_db_dir
        p = dbr.get_db_path("execution")
        assert p.name == "trades.db"

    def test_memory_domain(self, patch_db_dir):
        dbr = patch_db_dir
        p = dbr.get_db_path("memory")
        assert p.name == "memory.db"

    def test_main_domain(self, patch_db_dir):
        dbr = patch_db_dir
        p = dbr.get_db_path("main")
        assert p.name == "main.db"

    def test_unknown_domain_falls_back_to_main(self, patch_db_dir):
        dbr = patch_db_dir
        p = dbr.get_db_path("unknown_xyz")
        assert p.name == "main.db"

    def test_empty_string_falls_back_to_main(self, patch_db_dir):
        dbr = patch_db_dir
        p = dbr.get_db_path("")
        assert p.name == "main.db"

    def test_returned_path_is_inside_db_dir(self, patch_db_dir):
        dbr = patch_db_dir
        for domain in ("ticks", "market_data", "trades", "execution", "memory", "main"):
            p = dbr.get_db_path(domain)
            assert p.parent == dbr.DB_DIR


# ---------------------------------------------------------------------------
# get_connection
# ---------------------------------------------------------------------------

class TestGetConnection:
    def test_returns_sqlite_connection(self, patch_db_dir):
        dbr = patch_db_dir
        conn = dbr.get_connection("main")
        assert isinstance(conn, sqlite3.Connection)
        conn.close()

    def test_row_factory_is_set(self, patch_db_dir):
        dbr = patch_db_dir
        conn = dbr.get_connection("main")
        assert conn.row_factory is sqlite3.Row
        conn.close()

    def test_wal_mode_enabled(self, patch_db_dir):
        dbr = patch_db_dir
        conn = dbr.get_connection("main")
        row = conn.execute("PRAGMA journal_mode;").fetchone()
        assert row[0] == "wal"
        conn.close()

    def test_foreign_keys_on(self, patch_db_dir):
        dbr = patch_db_dir
        conn = dbr.get_connection("main")
        row = conn.execute("PRAGMA foreign_keys;").fetchone()
        assert row[0] == 1
        conn.close()

    def test_connection_for_each_domain(self, patch_db_dir):
        dbr = patch_db_dir
        for domain in ("main", "trades", "ticks", "memory"):
            conn = dbr.get_connection(domain)
            assert isinstance(conn, sqlite3.Connection)
            conn.close()

    def test_custom_timeout_accepted(self, patch_db_dir):
        dbr = patch_db_dir
        # Just make sure the call doesn't raise with a non-default timeout.
        conn = dbr.get_connection("main", timeout=5.0)
        assert conn is not None
        conn.close()

    def test_default_timeout_constant(self, patch_db_dir):
        dbr = patch_db_dir
        assert dbr.DEFAULT_TIMEOUT == 30.0

    def test_connection_is_usable(self, patch_db_dir):
        """Ensure we can actually execute statements on the returned connection."""
        dbr = patch_db_dir
        conn = dbr.get_connection("main")
        conn.execute("CREATE TABLE IF NOT EXISTS _test (id INTEGER PRIMARY KEY);")
        conn.execute("INSERT INTO _test VALUES (1);")
        row = conn.execute("SELECT id FROM _test;").fetchone()
        assert row[0] == 1
        conn.close()


# ---------------------------------------------------------------------------
# init_execution_tables
# ---------------------------------------------------------------------------

class TestInitExecutionTables:
    def test_creates_position_snapshots_table(self, patch_db_dir):
        dbr = patch_db_dir
        dbr.init_execution_tables()
        conn = dbr.get_connection("trades")
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='position_snapshots';"
        ).fetchone()
        assert row is not None
        conn.close()

    def test_creates_executions_table(self, patch_db_dir):
        dbr = patch_db_dir
        dbr.init_execution_tables()
        conn = dbr.get_connection("trades")
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='executions';"
        ).fetchone()
        assert row is not None
        conn.close()

    def test_idempotent_when_called_twice(self, patch_db_dir):
        dbr = patch_db_dir
        # Should not raise on second call (CREATE TABLE IF NOT EXISTS)
        dbr.init_execution_tables()
        dbr.init_execution_tables()

    def test_can_insert_into_executions(self, patch_db_dir):
        dbr = patch_db_dir
        dbr.init_execution_tables()
        conn = dbr.get_connection("trades")
        conn.execute(
            "INSERT INTO executions (id, symbol, action, quantity, price) VALUES (?, ?, ?, ?, ?);",
            ("exec-1", "2330", "BUY", 1000, 555.0),
        )
        row = conn.execute("SELECT symbol FROM executions WHERE id='exec-1';").fetchone()
        assert row["symbol"] == "2330"
        conn.close()

    def test_can_insert_into_position_snapshots(self, patch_db_dir):
        dbr = patch_db_dir
        dbr.init_execution_tables()
        conn = dbr.get_connection("trades")
        conn.execute(
            "INSERT INTO position_snapshots (system_state_json, positions_json, available_cash, reason) "
            "VALUES (?, ?, ?, ?);",
            ('{"mode":"ok"}', '[]', 100000.0, "test"),
        )
        row = conn.execute("SELECT reason FROM position_snapshots LIMIT 1;").fetchone()
        assert row["reason"] == "test"
        conn.close()
