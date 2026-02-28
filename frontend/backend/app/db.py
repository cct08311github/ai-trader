from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional


def _resolve_db_path() -> Path:
    """Resolve DB path from env/relative defaults.

    Default matches the repository layout:
    backend/app/db.py -> backend root -> ../../data/sqlite/trades.db
    """
    env_path = os.environ.get("DB_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()

    backend_root = Path(__file__).resolve().parent.parent
    return (backend_root / ".." / ".." / "data" / "sqlite" / "trades.db").resolve()


DB_PATH: Path = _resolve_db_path()


def connect_readonly(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Open sqlite connection in read-only mode.

    Uses sqlite URI mode=ro to guarantee no writes.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite DB not found: {db_path}")

    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # Extra safety: force query-only.
    try:
        conn.execute("PRAGMA query_only = ON;")
    except sqlite3.DatabaseError:
        # Some sqlite builds may not support it; mode=ro still enforces read-only.
        pass

    return conn


@contextmanager
def get_conn(db_path: Path = DB_PATH) -> Iterator[sqlite3.Connection]:
    conn = connect_readonly(db_path)
    try:
        yield conn
    finally:
        conn.close()


def _table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]  # name


def choose_order_by(conn: sqlite3.Connection, table: str, candidates: Iterable[str]) -> Optional[str]:
    cols = set(_table_columns(conn, table))
    for c in candidates:
        if c in cols:
            return c
    return None


def fetch_rows(
    conn: sqlite3.Connection,
    *,
    table: str,
    limit: int = 50,
    offset: int = 0,
    order_by_candidates: Iterable[str] = ("created_at", "timestamp", "time", "id"),
    desc: bool = True,
) -> List[Dict[str, Any]]:
    """Fetch rows from a fixed table name.

    IMPORTANT: table name is interpolated (cannot be parameterized). Only call this
    for trusted, hard-coded table names.
    """

    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))

    order_col = choose_order_by(conn, table, order_by_candidates)
    if order_col:
        direction = "DESC" if desc else "ASC"
        sql = f"SELECT * FROM {table} ORDER BY {order_col} {direction} LIMIT ? OFFSET ?"
        params = (limit, offset)
    else:
        sql = f"SELECT * FROM {table} LIMIT ? OFFSET ?"
        params = (limit, offset)

    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
