-- migration_v1_2_1_eod_data.sql
-- EOD (after-market) data storage for TWSE + TPEx integration.

BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eod_prices (
  trade_date TEXT NOT NULL,      -- YYYY-MM-DD
  market TEXT NOT NULL,          -- TWSE / TPEx
  symbol TEXT NOT NULL,
  name TEXT,
  close REAL,
  change REAL,
  open REAL,
  high REAL,
  low REAL,
  volume REAL,
  turnover REAL,
  trades REAL,
  source_url TEXT NOT NULL,
  ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (trade_date, market, symbol)
);

CREATE INDEX IF NOT EXISTS idx_eod_prices_symbol_date
ON eod_prices(symbol, trade_date);

CREATE TABLE IF NOT EXISTS eod_ingest_runs (
  run_id TEXT PRIMARY KEY,
  ts TEXT NOT NULL DEFAULT (datetime('now')),
  trade_date TEXT NOT NULL,
  status TEXT NOT NULL,         -- success / failed / partial
  twse_rows INTEGER NOT NULL DEFAULT 0,
  tpex_rows INTEGER NOT NULL DEFAULT 0,
  error_text TEXT
);

INSERT OR IGNORE INTO schema_migrations(version, applied_at)
VALUES ('v1.2.1', datetime('now'));

COMMIT;
