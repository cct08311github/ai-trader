from __future__ import annotations

import os
import queue
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
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


@dataclass
class SQLiteReadonlyPool:
    size: int = 5
    _q: queue.Queue[sqlite3.Connection] | None = None
    _db_path: Path | None = None

    def init(self, db_path: Path) -> None:
        self._db_path = db_path
        self._q = queue.Queue(maxsize=self.size)
        for _ in range(self.size):
            self._q.put(connect_readonly(db_path))

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        if not self._q or not self._db_path:
            # fallback
            c = connect_readonly(DB_PATH)
            try:
                yield c
            finally:
                c.close()
            return

        c = self._q.get()
        try:
            yield c
        finally:
            # Return to pool
            self._q.put(c)

    def close(self) -> None:
        if not self._q:
            return
        while True:
            try:
                c = self._q.get_nowait()
            except queue.Empty:
                break
            try:
                c.close()
            except Exception:
                pass


READONLY_POOL = SQLiteReadonlyPool(size=int(os.environ.get("DB_POOL_SIZE", "5")))


def init_readonly_pool(db_path: Path = DB_PATH) -> None:
    """Initialize a small read-only connection pool.

    SQLite doesn't have server-side pooling; this is a pragmatic optimization to
    avoid reconnect overhead under concurrent API calls.
    """

    READONLY_POOL.init(db_path)


@contextmanager
def get_conn(db_path: Path = DB_PATH) -> Iterator[sqlite3.Connection]:
    # If pool initialized, use it.
    if READONLY_POOL._q is not None:
        with READONLY_POOL.conn() as conn:
            yield conn
    else:
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


def connect_rw(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Open sqlite connection in read-write mode.

    NOTE:
    - Use this ONLY for explicit operator actions (approve/reject).
    - Keep the scope tight and always commit.
    """

    if not db_path.exists():
        raise FileNotFoundError(f"SQLite DB not found: {db_path}")

    conn = sqlite3.connect(db_path.as_posix(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL mode gives better concurrent read performance and crash safety.
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def get_conn_rw(db_path: Path = DB_PATH) -> Iterator[sqlite3.Connection]:
    conn = connect_rw(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
