-- Migration v1.2.0: observability + drawdown guard (minimal, idempotent)
-- NOTE: This repo uses multiple historical schemas; unit tests expect this file
-- to exist and to create at least the legacy `llm_traces` table.

PRAGMA foreign_keys = ON;

-- LLM observability (legacy schema)
CREATE TABLE IF NOT EXISTS llm_traces (
  trace_id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  component TEXT NOT NULL,
  model TEXT NOT NULL,
  decision_id TEXT,
  prompt_text TEXT,
  response_text TEXT,
  input_tokens INTEGER,
  output_tokens INTEGER,
  latency_ms INTEGER,
  tools_json TEXT,
  confidence REAL,
  metadata_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_llm_traces_ts ON llm_traces(ts);
CREATE INDEX IF NOT EXISTS idx_llm_traces_component ON llm_traces(component);

-- Drawdown guard summary table (used by drawdown_guard.evaluate_drawdown_guard)
CREATE TABLE IF NOT EXISTS daily_pnl_summary (
  trade_date TEXT PRIMARY KEY,
  nav_end REAL,
  rolling_peak_nav REAL,
  rolling_drawdown REAL,
  losing_streak_days INTEGER
);

-- Strategy health gate (used by drawdown_guard.evaluate_strategy_health_guard)
CREATE TABLE IF NOT EXISTS strategy_health (
  strategy_id TEXT PRIMARY KEY,
  rolling_trades INTEGER,
  rolling_win_rate REAL,
  enabled INTEGER
);

-- Optional: persistent lock flags (best-effort writes by drawdown_guard.apply_drawdown_actions)
CREATE TABLE IF NOT EXISTS trading_locks (
  lock_id TEXT PRIMARY KEY,
  locked INTEGER NOT NULL,
  reason_code TEXT,
  locked_at TEXT,
  unlock_after TEXT,
  note TEXT
);

-- Optional: incidents audit trail
CREATE TABLE IF NOT EXISTS incidents (
  incident_id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  severity TEXT,
  source TEXT,
  code TEXT,
  detail_json TEXT,
  resolved INTEGER DEFAULT 0
);
