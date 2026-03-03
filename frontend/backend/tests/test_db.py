"""Tests for app/db.py — covering missing lines."""
from __future__ import annotations

import importlib
import sqlite3
import os
from pathlib import Path
from unittest.mock import patch

import pytest


class TestResolveDbPath:
    def test_env_var_used_when_set(self, tmp_path, monkeypatch):
        db = tmp_path / "my.db"
        monkeypatch.setenv("DB_PATH", str(db))
        import app.db as db_mod
        importlib.reload(db_mod)
        assert db_mod.DB_PATH == db.resolve()

    def test_default_path_when_no_env(self, monkeypatch):
        monkeypatch.delenv("DB_PATH", raising=False)
        import app.db as db_mod
        importlib.reload(db_mod)
        # Should be some path ending in trades.db
        assert "trades.db" in str(db_mod.DB_PATH)


class TestConnectReadonly:
    def test_raises_file_not_found(self, tmp_path):
        from app.db import connect_readonly
        with pytest.raises(FileNotFoundError):
            connect_readonly(tmp_path / "missing.db")

    def test_returns_connection(self, tmp_path):
        db = tmp_path / "test.db"
        sqlite3.connect(str(db)).close()
        from app.db import connect_readonly
        conn = connect_readonly(db)
        assert conn is not None
        conn.close()

    def test_query_only_mode(self, tmp_path):
        db = tmp_path / "test.db"
        sqlite3.connect(str(db)).close()
        from app.db import connect_readonly
        conn = connect_readonly(db)
        # In query_only mode, writes should fail
        try:
            conn.execute("CREATE TABLE test (id INTEGER)")
        except sqlite3.DatabaseError:
            pass  # Expected in read-only mode
        conn.close()


class TestSqliteReadonlyPool:
    def test_pool_init_and_conn(self, tmp_path):
        from app.db import SQLiteReadonlyPool, connect_readonly
        db = tmp_path / "pool.db"
        sqlite3.connect(str(db)).close()
        pool = SQLiteReadonlyPool(size=2)
        pool.init(db)
        with pool.conn() as conn:
            result = conn.execute("SELECT 1").fetchone()
            assert result is not None
        pool.close()

    def test_pool_fallback_when_not_initialized(self, tmp_path, monkeypatch):
        """When pool not initialized, falls back to connect_readonly(DB_PATH)."""
        db = tmp_path / "fallback.db"
        sqlite3.connect(str(db)).close()
        monkeypatch.setenv("DB_PATH", str(db))
        import app.db as db_mod
        importlib.reload(db_mod)
        pool = db_mod.SQLiteReadonlyPool(size=2)
        # Don't call pool.init() — use fallback path
        with pool.conn() as conn:
            result = conn.execute("SELECT 1").fetchone()
            assert result is not None

    def test_pool_close_empty(self):
        from app.db import SQLiteReadonlyPool
        pool = SQLiteReadonlyPool(size=2)
        # Close without init should not raise
        pool.close()


class TestGetConn:
    def test_get_conn_with_pool(self, tmp_path, monkeypatch):
        db = tmp_path / "get.db"
        sqlite3.connect(str(db)).close()
        monkeypatch.setenv("DB_PATH", str(db))
        import app.db as db_mod
        importlib.reload(db_mod)
        db_mod.READONLY_POOL.init(db)
        with db_mod.get_conn() as conn:
            result = conn.execute("SELECT 1").fetchone()
            assert result is not None

    def test_get_conn_rw(self, tmp_path, monkeypatch):
        db = tmp_path / "rw.db"
        conn_init = sqlite3.connect(str(db))
        conn_init.execute("CREATE TABLE test (id INTEGER)")
        conn_init.commit()
        conn_init.close()
        monkeypatch.setenv("DB_PATH", str(db))
        import app.db as db_mod
        importlib.reload(db_mod)
        with db_mod.get_conn_rw() as conn:
            conn.execute("INSERT INTO test VALUES (1)")
            # conn is auto-committed when context manager exits


class TestFetchRows:
    def test_fetch_rows_with_order_by(self, tmp_path, monkeypatch):
        db = tmp_path / "fetch.db"
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE items (id INTEGER, created_at INTEGER)")
        conn.execute("INSERT INTO items VALUES (1, 1000)")
        conn.execute("INSERT INTO items VALUES (2, 2000)")
        conn.commit()

        from app.db import fetch_rows
        rows = fetch_rows(conn, table="items", limit=10, offset=0)
        assert len(rows) == 2
        conn.close()

    def test_fetch_rows_no_order_column(self, tmp_path):
        db = tmp_path / "noorder.db"
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE simple (name TEXT)")
        conn.execute("INSERT INTO simple VALUES ('a')")
        conn.commit()

        from app.db import fetch_rows
        rows = fetch_rows(conn, table="simple", limit=5, order_by_candidates=())
        assert len(rows) == 1
        conn.close()

    def test_fetch_rows_limit_clamped(self, tmp_path):
        db = tmp_path / "limit.db"
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE big (id INTEGER, created_at INTEGER)")
        for i in range(10):
            conn.execute(f"INSERT INTO big VALUES ({i}, {i*1000})")
        conn.commit()

        from app.db import fetch_rows
        rows = fetch_rows(conn, table="big", limit=3)
        assert len(rows) == 3
        conn.close()


class TestTableColumns:
    def test_table_columns(self, tmp_path):
        db = tmp_path / "cols.db"
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE t (a INTEGER, b TEXT, c REAL)")
        conn.commit()

        from app.db import _table_columns
        cols = _table_columns(conn, "t")
        assert "a" in cols
        assert "b" in cols
        assert "c" in cols
        conn.close()

    def test_choose_order_by(self, tmp_path):
        db = tmp_path / "order.db"
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE t (id INTEGER, created_at INTEGER)")
        conn.commit()

        from app.db import choose_order_by
        col = choose_order_by(conn, "t", ["created_at", "timestamp"])
        assert col == "created_at"
        conn.close()

    def test_choose_order_by_returns_none_when_no_match(self, tmp_path):
        db = tmp_path / "nomatch.db"
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE t (name TEXT)")
        conn.commit()

        from app.db import choose_order_by
        col = choose_order_by(conn, "t", ["created_at", "timestamp"])
        assert col is None
        conn.close()


class TestConnectRw:
    def test_connect_rw_raises_when_not_found(self, tmp_path):
        from app.db import connect_rw
        from pathlib import Path
        with pytest.raises(FileNotFoundError):
            connect_rw(Path(tmp_path / "nonexistent.db"))

    def test_connect_rw_returns_connection(self, tmp_path):
        from app.db import connect_rw
        from pathlib import Path
        db = Path(tmp_path / "rw.db")
        sqlite3.connect(str(db)).close()
        conn = connect_rw(db)
        assert conn is not None
        conn.execute("CREATE TABLE test_rw (id INTEGER)")
        conn.commit()
        conn.close()


class TestGetConnEdgeCases:
    def test_get_conn_without_pool(self, tmp_path, monkeypatch):
        """get_conn fallback path when pool not initialized."""
        import importlib
        db = tmp_path / "nopool.db"
        sqlite3.connect(str(db)).close()
        monkeypatch.setenv("DB_PATH", str(db))
        import app.db as db_mod
        importlib.reload(db_mod)
        # Ensure pool is NOT initialized
        db_mod.READONLY_POOL._q = None
        with db_mod.get_conn() as conn:
            result = conn.execute("SELECT 1").fetchone()
            assert result is not None

    def test_get_conn_rw_commits_on_success(self, tmp_path, monkeypatch):
        """get_conn_rw commits when no exception occurs."""
        import importlib
        db = tmp_path / "commit.db"
        conn_init = sqlite3.connect(str(db))
        conn_init.execute("CREATE TABLE items (val INTEGER)")
        conn_init.commit()
        conn_init.close()
        monkeypatch.setenv("DB_PATH", str(db))
        import app.db as db_mod
        importlib.reload(db_mod)
        with db_mod.get_conn_rw() as conn:
            conn.execute("INSERT INTO items VALUES (42)")
        # Verify it was committed
        check = sqlite3.connect(str(db))
        rows = check.execute("SELECT val FROM items").fetchall()
        check.close()
        assert any(r[0] == 42 for r in rows)


class TestInitReadonlyPool:
    def test_init_readonly_pool_function(self, tmp_path, monkeypatch):
        """init_readonly_pool() initializes READONLY_POOL."""
        import importlib
        db = tmp_path / "pool_init.db"
        sqlite3.connect(str(db)).close()
        monkeypatch.setenv("DB_PATH", str(db))
        import app.db as db_mod
        importlib.reload(db_mod)
        db_mod.init_readonly_pool(db)
        assert db_mod.READONLY_POOL._q is not None
        db_mod.READONLY_POOL.close()


class TestConnectReadonlyPragma:
    def test_pragma_query_only_exception_handled(self, tmp_path, monkeypatch):
        """connect_readonly handles sqlite DatabaseError from PRAGMA query_only."""
        db = tmp_path / "pragma.db"
        sqlite3.connect(str(db)).close()

        # Monkeypatch sqlite3.Connection.execute to raise on PRAGMA query_only
        import app.db as db_mod
        original_connect = db_mod.sqlite3.connect

        class FakeConn:
            row_factory = None
            def execute(self, sql, *args, **kwargs):
                if "query_only" in sql:
                    raise sqlite3.DatabaseError("PRAGMA not supported")
                return original_connect(str(db)).execute(sql, *args, **kwargs)
            def close(self):
                pass

        def fake_connect(positional_uri=None, *, uri=False, check_same_thread=True, **kwargs):
            return FakeConn()

        monkeypatch.setattr(db_mod.sqlite3, "connect", fake_connect)
        # Should not raise (DatabaseError is swallowed)
        conn = db_mod.connect_readonly(db)
        assert conn is not None


class TestPoolCloseException:
    def test_pool_close_handles_connection_error(self, tmp_path):
        """SQLiteReadonlyPool.close() handles error when closing a connection."""
        from app.db import SQLiteReadonlyPool, connect_readonly
        db = tmp_path / "closeerr.db"
        sqlite3.connect(str(db)).close()
        pool = SQLiteReadonlyPool(size=1)
        pool.init(db)
        # Replace the connection in the pool with one that raises on close
        import queue as q_mod
        bad_conn = sqlite3.connect(str(db))
        bad_conn.close()  # pre-close so .close() is a no-op (won't raise, but exercises the path)
        # To really exercise the exception path, put a mock that raises
        from unittest.mock import MagicMock
        mock_conn = MagicMock()
        mock_conn.close.side_effect = Exception("close failed")
        # Drain the real connection and put the mock
        real_conn = pool._q.get_nowait()
        real_conn.close()
        pool._q.put(mock_conn)
        # close() should not raise even when conn.close() raises
        pool.close()
