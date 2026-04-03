from __future__ import annotations

"""research_db.py — Initialize and manage the research.db SQLite database.

Provides WAL-mode setup and schema creation for all AI Investment Research
Platform tables:

  - market_indices        — daily snapshots of major index levels
  - geopolitical_events   — curated macro / geopolitical risk events
  - research_reports      — generated investment research reports
  - data_source_health    — connectivity / staleness health for data providers
  - risk_snapshots        — periodic portfolio-level risk metric snapshots
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _resolve_research_db_path() -> Path:
    """Resolve research.db path from env or default relative to repo layout.

    Default: <repo_root>/data/sqlite/research.db
    Override: set RESEARCH_DB_PATH env variable.
    """
    env_path = os.environ.get("RESEARCH_DB_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()

    # backend/app/db/research_db.py -> backend root -> ../../data/sqlite/research.db
    backend_root = Path(__file__).resolve().parent.parent.parent
    return (backend_root / ".." / ".." / "data" / "sqlite" / "research.db").resolve()


RESEARCH_DB_PATH: Path = _resolve_research_db_path()


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL_STATEMENTS = [
    # ------------------------------------------------------------------
    # market_indices: daily closing levels for major indices.
    # ------------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS market_indices (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol          TEXT    NOT NULL,
        name            TEXT,
        close_price     REAL    NOT NULL,
        open_price      REAL,
        high_price      REAL,
        low_price       REAL,
        volume          INTEGER,
        change_pct      REAL,
        trade_date      TEXT    NOT NULL,           -- ISO-8601 YYYY-MM-DD
        source          TEXT    NOT NULL DEFAULT 'yfinance',
        fetched_at      TEXT    NOT NULL DEFAULT (datetime('now')),
        UNIQUE (symbol, trade_date)
    )
    """,

    # ------------------------------------------------------------------
    # geopolitical_events: macro / geopolitical risk items.
    # ------------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS geopolitical_events (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        event_date      TEXT    NOT NULL,           -- ISO-8601 YYYY-MM-DD
        title           TEXT    NOT NULL,
        summary         TEXT,
        region          TEXT,                       -- asia / europe / americas / middle_east / africa / global
        severity        TEXT    NOT NULL DEFAULT 'medium', -- low / medium / high / critical
        tags            TEXT,                       -- JSON array of keyword tags
        source_url      TEXT,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
        -- Extended fields added by GeopoliticalAgent (Issue #566)
        category        TEXT,                       -- trade_war / sanctions / conflict / policy / election
        impact_score    REAL    DEFAULT 0,          -- 0-10 LLM-evaluated severity
        market_impact   TEXT,                       -- JSON: {sectors, assets, direction, note}
        lat             REAL,                       -- approximate latitude for map markers
        lng             REAL,                       -- approximate longitude for map markers
        url_hash        TEXT                        -- SHA-256[:32] of source_url or title (dedup key)
    )
    """,

    # ------------------------------------------------------------------
    # research_reports: AI-generated investment research outputs.
    # ------------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS research_reports (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        report_date     TEXT    NOT NULL,           -- ISO-8601 YYYY-MM-DD
        report_type     TEXT    NOT NULL,           -- e.g. "daily_brief", "sector_deep_dive"
        title           TEXT    NOT NULL,
        summary         TEXT,
        body            TEXT,                       -- Full markdown / JSON content
        tickers         TEXT,                       -- JSON array of relevant tickers
        sentiment       TEXT,                       -- bullish / bearish / neutral
        confidence      REAL,                       -- 0.0 – 1.0
        model_id        TEXT,                       -- AI model that produced the report
        created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,

    # ------------------------------------------------------------------
    # data_source_health: track connectivity / staleness of data providers.
    # ------------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS data_source_health (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        source_name     TEXT    NOT NULL,           -- e.g. "yfinance", "fred", "twse"
        status          TEXT    NOT NULL DEFAULT 'unknown', -- ok / degraded / down / unknown
        last_success_at TEXT,
        last_failure_at TEXT,
        failure_count   INTEGER NOT NULL DEFAULT 0,
        latency_ms      REAL,
        error_message   TEXT,
        checked_at      TEXT    NOT NULL DEFAULT (datetime('now')),
        UNIQUE (source_name)
    )
    """,

    # ------------------------------------------------------------------
    # risk_snapshots: periodic portfolio-level risk metric captures.
    # ------------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS risk_snapshots (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_at     TEXT    NOT NULL DEFAULT (datetime('now')),
        portfolio_id    TEXT    NOT NULL DEFAULT 'default',
        var_1d          REAL,                       -- 1-day Value at Risk (95 %)
        var_5d          REAL,                       -- 5-day Value at Risk (95 %)
        beta            REAL,                       -- Portfolio beta vs. benchmark
        sharpe_ratio    REAL,
        max_drawdown    REAL,
        gross_exposure  REAL,
        net_exposure    REAL,
        concentration   REAL,                       -- Herfindahl index
        notes           TEXT
    )
    """,

    # ------------------------------------------------------------------
    # sector_mapping: TWSE symbol -> sector classification (Module 2B).
    # ------------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS sector_mapping (
        symbol      TEXT    PRIMARY KEY,
        sector_code TEXT    NOT NULL,
        sector_name TEXT    NOT NULL,
        sub_sector  TEXT,
        updated_at  INTEGER NOT NULL
    )
    """,

    # ------------------------------------------------------------------
    # sector_data: daily aggregated sector metrics (Module 2B).
    # ------------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS sector_data (
        trade_date        TEXT    NOT NULL,
        sector_code       TEXT    NOT NULL,
        sector_name       TEXT    NOT NULL,
        market_cap        REAL,
        turnover          REAL,
        change_pct        REAL,
        fund_flow_net     REAL,
        fund_flow_foreign REAL,
        fund_flow_trust   REAL,
        pe_ratio          REAL,
        stock_count       INTEGER,
        source            TEXT    NOT NULL DEFAULT 'twse',
        created_at        INTEGER NOT NULL,
        UNIQUE (trade_date, sector_code)
    )
    """,

    # ------------------------------------------------------------------
    # Indices for common query patterns.
    # ------------------------------------------------------------------
    "CREATE INDEX IF NOT EXISTS idx_sector_data_date      ON sector_data (trade_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_sector_mapping_code   ON sector_mapping (sector_code)",
    "CREATE INDEX IF NOT EXISTS idx_market_indices_date   ON market_indices (trade_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_market_indices_symbol ON market_indices (symbol)",
    "CREATE INDEX IF NOT EXISTS idx_geo_events_date       ON geopolitical_events (event_date DESC)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_geo_events_url_hash ON geopolitical_events (url_hash) WHERE url_hash IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_geo_events_category   ON geopolitical_events (category)",
    "CREATE INDEX IF NOT EXISTS idx_geo_events_region     ON geopolitical_events (region)",
    "CREATE INDEX IF NOT EXISTS idx_research_date         ON research_reports (report_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_risk_snapshot_at      ON risk_snapshots (snapshot_at DESC)",
]


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def connect_research(db_path: Path = RESEARCH_DB_PATH) -> sqlite3.Connection:
    """Open a read-write connection to research.db with WAL mode enabled."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path.as_posix(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Enable WAL for better concurrent read performance.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextmanager
def get_research_conn(db_path: Path = RESEARCH_DB_PATH) -> Iterator[sqlite3.Connection]:
    """Context-manager for a read-write research.db connection (auto-commits)."""
    conn = connect_research(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

def init_research_db(db_path: Path = RESEARCH_DB_PATH) -> None:
    """Create research.db and apply all DDL statements.

    Safe to call multiple times — all statements use IF NOT EXISTS / IF NOT EXISTS.
    """
    logger.info("Initialising research.db at %s", db_path)
    with get_research_conn(db_path) as conn:
        for stmt in _DDL_STATEMENTS:
            conn.execute(stmt)
    logger.info("research.db schema ready.")


# ---------------------------------------------------------------------------
# Convenience: run directly to bootstrap the database.
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else RESEARCH_DB_PATH
    init_research_db(path)
    print(f"research.db initialised at {path}")
