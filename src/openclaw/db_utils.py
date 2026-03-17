"""Unified database connection utilities for the AI Trader core engine.

Provides two context-manager helpers for SQLite access:
- ``get_readonly_conn`` — read-only mode (URI mode=ro); suitable for queries.
- ``get_readwrite_conn`` — read-write mode with automatic commit/rollback.

For long-lived connections that need explicit transaction control (e.g.
``ticker_watcher``'s inner scan loop), use ``open_watcher_conn`` which
returns a plain ``sqlite3.Connection`` with WAL mode and autocommit enabled.

Do NOT import or modify ``frontend/backend/app/db.py`` — that module owns
its own connection-pool pattern for the FastAPI process.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional
from openclaw.path_utils import get_repo_root

logger = logging.getLogger(__name__)


def _get_db_path() -> str:
    """Resolve path to trades.db relative to this file's repo root.

    Layout: src/openclaw/db_utils.py → parents[2] = repo root
    """
    root = get_repo_root()
    return str(root / "data" / "sqlite" / "trades.db")


@contextmanager
def get_readonly_conn(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    """Yield a read-only SQLite connection.

    Uses ``file:...?mode=ro`` URI to guarantee no writes are possible.
    The connection is closed automatically when the context exits.

    Example::

        with get_readonly_conn() as conn:
            rows = conn.execute("SELECT * FROM orders").fetchall()
    """
    path = db_path or _get_db_path()
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_readwrite_conn(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    """Yield a read-write SQLite connection with automatic commit/rollback.

    Commits on clean exit; rolls back and re-raises on any exception.
    The connection is closed automatically when the context exits.

    Example::

        with get_readwrite_conn() as conn:
            conn.execute("INSERT INTO orders ...", (...,))
    """
    path = db_path or _get_db_path()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def open_watcher_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Open a long-lived read-write connection optimised for the watcher loop.

    Sets WAL journal mode, NORMAL synchronous, a 30-second busy timeout, and
    foreign-key enforcement.  ``isolation_level=None`` enables autocommit so
    the caller can issue explicit ``BEGIN IMMEDIATE`` / ``COMMIT`` / ``ROLLBACK``
    statements — matching the existing ticker_watcher transaction pattern.

    The caller is responsible for calling ``conn.close()`` when done.

    Example::

        conn = open_watcher_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            ...
            conn.commit()
        finally:
            conn.close()
    """
    path = db_path or _get_db_path()
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    logger.debug("Opened watcher connection to %s", path)
    return conn
