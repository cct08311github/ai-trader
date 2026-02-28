-- migration_v1_2_0_observability_and_drawdown.sql
-- v1.2.0 schema for LLM observability, drawdown guard, and strategy health.

BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_traces (
  trace_id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  component TEXT NOT NULL,             -- pm/flash/news_guard/backtest
  model TEXT NOT NULL,
  decision_id TEXT,
  prompt_text TEXT NOT NULL,
  response_text TEXT NOT NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  latency_ms INTEGER NOT NULL DEFAULT 0,
  tools_json TEXT NOT NULL DEFAULT '[]',
  confidence REAL,                     -- 0~1
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_llm_traces_ts
ON llm_traces(ts);

CREATE INDEX IF NOT EXISTS idx_llm_traces_component_ts
ON llm_traces(component, ts);

CREATE TABLE IF NOT EXISTS daily_pnl_summary (
  trade_date TEXT PRIMARY KEY,         -- YYYY-MM-DD
  nav_start REAL NOT NULL,
  nav_end REAL NOT NULL,
  realized_pnl REAL NOT NULL,
  unrealized_pnl REAL NOT NULL,
  total_pnl REAL NOT NULL,
  daily_return REAL NOT NULL,
  rolling_peak_nav REAL NOT NULL,
  rolling_drawdown REAL NOT NULL,      -- 0~1
  losing_streak_days INTEGER NOT NULL DEFAULT 0,
  risk_mode TEXT NOT NULL DEFAULT 'normal'  -- normal/reduce_only/suspended
);

CREATE TABLE IF NOT EXISTS strategy_health (
  strategy_id TEXT PRIMARY KEY,
  as_of_ts TEXT NOT NULL,
  rolling_trades INTEGER NOT NULL DEFAULT 0,
  rolling_win_rate REAL NOT NULL DEFAULT 0.0,
  enabled INTEGER NOT NULL DEFAULT 1,
  note TEXT
);

INSERT OR IGNORE INTO schema_migrations(version, applied_at)
VALUES ('v1.2.0', datetime('now'));

COMMIT;
