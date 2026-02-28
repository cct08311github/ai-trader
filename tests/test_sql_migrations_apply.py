import sqlite3
from pathlib import Path


def _apply_sql(conn: sqlite3.Connection, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()


def test_sql_migrations_apply_in_order(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    sql_dir = repo_root / "src" / "sql"

    migration_files = [
        "migration_v1_1_0_core.sql",
        "migration_v1_1_1_order_events.sql",
        "migration_v1_2_0_observability_and_drawdown.sql",
        "migration_v1_2_1_eod_data.sql",
        "migration_v1_2_2_memory_reflection_proposals.sql",
        "risk_limits_seed_v1_1.sql",
    ]

    for name in migration_files:
        assert (sql_dir / name).exists(), f"Missing migration file: {name}"

    conn = sqlite3.connect(str(tmp_path / "test.db"))

    # Mirror init_db.py PRAGMA expectations
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")

    for name in migration_files:
        _apply_sql(conn, sql_dir / name)

    required_tables = {
        "schema_migrations",
        "strategy_versions",
        "risk_limits",
        "decisions",
        "risk_checks",
        "orders",
        "fills",
        "order_events",
        "portfolio_snapshots",
        "incidents",
        "trading_locks",
        "llm_traces",
        "daily_pnl_summary",
        "strategy_health",
        "eod_prices",
        "eod_ingest_runs",
        "working_memory",
        "episodic_memory",
        "semantic_memory",
        "reflection_runs",
        "strategy_proposals",
        "authority_policy",
        "authority_actions",
    }

    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    }

    missing = sorted(required_tables - tables)
    assert not missing, f"Missing tables after migrations: {missing}"

    conn.close()
