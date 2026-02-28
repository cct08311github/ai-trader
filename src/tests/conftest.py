from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


def apply_v4_migrations(conn: sqlite3.Connection) -> None:
    """Apply the project's SQL migrations to an existing SQLite connection.

    Note: Some unit tests may define their own minimal schemas instead.
    """

    repo_root = Path(__file__).resolve().parents[2]
    sql_dir = repo_root / "src" / "sql"
    migration_files = [
        sql_dir / "migration_v1_1_0_core.sql",
        sql_dir / "migration_v1_1_1_order_events.sql",
        sql_dir / "migration_v1_2_0_observability_and_drawdown.sql",
        sql_dir / "migration_v1_2_1_eod_data.sql",
        sql_dir / "migration_v1_2_2_memory_reflection_proposals.sql",
        sql_dir / "risk_limits_seed_v1_1.sql",
    ]

    conn.execute("PRAGMA foreign_keys = ON")

    for path in migration_files:
        if not path.exists():
            raise FileNotFoundError(f"Migration SQL not found: {path}")
        conn.executescript(path.read_text(encoding="utf-8"))
    conn.commit()


@pytest.fixture()
def mem_db() -> sqlite3.Connection:
    """In-memory DB with v4 migrations applied."""

    conn = sqlite3.connect(":memory:")
    apply_v4_migrations(conn)
    try:
        yield conn
    finally:
        conn.close()
