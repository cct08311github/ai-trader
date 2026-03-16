"""Tests for src/openclaw/db_utils.py — unified DB connection utilities."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from openclaw.db_utils import (
    _get_db_path,
    get_readonly_conn,
    get_readwrite_conn,
    open_watcher_conn,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path: Path) -> str:
    """Create a minimal SQLite DB with a 'items' table and return its path."""
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO items (value) VALUES ('hello')")
    conn.commit()
    conn.close()
    return db_path


# ── _get_db_path ──────────────────────────────────────────────────────────────

def test_get_db_path_resolves_to_trades_db():
    """_get_db_path returns a path ending with data/sqlite/trades.db."""
    path = _get_db_path()
    assert path.endswith("data/sqlite/trades.db")
    # Must be absolute
    assert Path(path).is_absolute()


# ── get_readonly_conn ─────────────────────────────────────────────────────────

def test_readonly_conn_can_read(tmp_db: str):
    """get_readonly_conn allows SELECT queries."""
    with get_readonly_conn(tmp_db) as conn:
        rows = conn.execute("SELECT value FROM items").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "hello"


def test_readonly_conn_refuses_writes(tmp_db: str):
    """get_readonly_conn raises an error on INSERT/UPDATE/DELETE."""
    with pytest.raises(Exception):
        with get_readonly_conn(tmp_db) as conn:
            conn.execute("INSERT INTO items (value) VALUES ('new')")


def test_readonly_conn_closed_after_exit(tmp_db: str):
    """Connection is closed after the context manager exits."""
    with get_readonly_conn(tmp_db) as conn:
        pass  # just enter and exit
    # Attempting to use the connection after close raises ProgrammingError
    with pytest.raises(Exception):
        conn.execute("SELECT 1")


def test_readonly_conn_row_factory(tmp_db: str):
    """Rows are returned as sqlite3.Row (accessible by name)."""
    with get_readonly_conn(tmp_db) as conn:
        row = conn.execute("SELECT value FROM items").fetchone()
    assert row["value"] == "hello"


# ── get_readwrite_conn ────────────────────────────────────────────────────────

def test_readwrite_conn_allows_writes(tmp_db: str):
    """get_readwrite_conn allows INSERT and auto-commits on clean exit."""
    with get_readwrite_conn(tmp_db) as conn:
        conn.execute("INSERT INTO items (value) VALUES ('world')")

    # Verify the row persisted after the context closed
    verify = sqlite3.connect(tmp_db)
    rows = verify.execute("SELECT value FROM items ORDER BY id").fetchall()
    verify.close()
    assert len(rows) == 2
    assert rows[1][0] == "world"


def test_readwrite_conn_rollback_on_error(tmp_db: str):
    """get_readwrite_conn rolls back when an exception is raised inside."""
    with pytest.raises(RuntimeError):
        with get_readwrite_conn(tmp_db) as conn:
            conn.execute("INSERT INTO items (value) VALUES ('rollback_me')")
            raise RuntimeError("forced error")

    # The inserted row must NOT be present
    verify = sqlite3.connect(tmp_db)
    rows = verify.execute("SELECT value FROM items WHERE value='rollback_me'").fetchall()
    verify.close()
    assert rows == []


def test_readwrite_conn_reraises_exception(tmp_db: str):
    """The original exception propagates out of get_readwrite_conn."""
    class _Sentinel(Exception):
        pass

    with pytest.raises(_Sentinel):
        with get_readwrite_conn(tmp_db) as conn:
            raise _Sentinel("sentinel")


def test_readwrite_conn_closed_after_exit(tmp_db: str):
    """Connection is closed after the context manager exits (success path)."""
    with get_readwrite_conn(tmp_db) as conn:
        pass
    with pytest.raises(Exception):
        conn.execute("SELECT 1")


def test_readwrite_conn_row_factory(tmp_db: str):
    """Rows returned by get_readwrite_conn are sqlite3.Row instances."""
    with get_readwrite_conn(tmp_db) as conn:
        row = conn.execute("SELECT value FROM items").fetchone()
    assert row["value"] == "hello"


# ── open_watcher_conn ─────────────────────────────────────────────────────────

def test_watcher_conn_allows_writes(tmp_db: str):
    """open_watcher_conn returns a writable connection."""
    conn = open_watcher_conn(tmp_db)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO items (value) VALUES ('watcher')")
        conn.commit()
    finally:
        conn.close()

    verify = sqlite3.connect(tmp_db)
    rows = verify.execute("SELECT value FROM items WHERE value='watcher'").fetchall()
    verify.close()
    assert len(rows) == 1


def test_watcher_conn_explicit_rollback(tmp_db: str):
    """open_watcher_conn supports explicit ROLLBACK (isolation_level=None)."""
    conn = open_watcher_conn(tmp_db)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO items (value) VALUES ('should_rollback')")
        conn.execute("ROLLBACK")
    finally:
        conn.close()

    verify = sqlite3.connect(tmp_db)
    rows = verify.execute(
        "SELECT value FROM items WHERE value='should_rollback'"
    ).fetchall()
    verify.close()
    assert rows == []


def test_watcher_conn_wal_mode(tmp_db: str):
    """open_watcher_conn sets WAL journal mode."""
    conn = open_watcher_conn(tmp_db)
    try:
        row = conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"
    finally:
        conn.close()


def test_watcher_conn_row_factory(tmp_db: str):
    """open_watcher_conn rows are accessible by column name."""
    conn = open_watcher_conn(tmp_db)
    try:
        row = conn.execute("SELECT value FROM items").fetchone()
        assert row["value"] == "hello"
    finally:
        conn.close()
