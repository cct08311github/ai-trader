-- migration_v1_2_2_memory_reflection_proposals.sql
-- v4 core: layered memory, structured reflection, proposal schema, authority boundary.

BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL
);

-- Working memory: intraday short-term context. Cleared after close.
CREATE TABLE IF NOT EXISTS working_memory (
  mem_key TEXT PRIMARY KEY,             -- e.g. position_state:2330 / market_regime
  mem_value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Episodic memory: day-level episodes with decay score.
CREATE TABLE IF NOT EXISTS episodic_memory (
  episode_id TEXT PRIMARY KEY,
  trade_date TEXT NOT NULL,
  symbol TEXT NOT NULL,
  strategy_id TEXT NOT NULL,
  market_regime TEXT NOT NULL,          -- trending/range/bear/volatile
  entry_reason TEXT NOT NULL,
  outcome_pnl REAL NOT NULL,
  pm_score REAL,                        -- 0~1 post-trade PM score
  root_cause_code TEXT,                 -- timing/chips/stop/news/exec
  decay_score REAL NOT NULL DEFAULT 1.0,
  archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0,1)),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_episodic_memory_date
ON episodic_memory(trade_date, symbol);

CREATE INDEX IF NOT EXISTS idx_episodic_memory_decay
ON episodic_memory(decay_score, archived);

-- Semantic memory: generalized rules learned from episodes.
CREATE TABLE IF NOT EXISTS semantic_memory (
  rule_id TEXT PRIMARY KEY,
  rule_text TEXT NOT NULL,
  confidence REAL NOT NULL,             -- 0~1
  source_episodes_json TEXT NOT NULL,   -- ["episode1","episode2",...]
  sample_count INTEGER NOT NULL DEFAULT 0,
  last_validated_date TEXT,             -- YYYY-MM-DD
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','review','deprecated')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_semantic_memory_status_conf
ON semantic_memory(status, confidence);

-- Structured reflection loop output: Diagnosis -> Abstraction -> Refinement.
CREATE TABLE IF NOT EXISTS reflection_runs (
  run_id TEXT PRIMARY KEY,
  trade_date TEXT NOT NULL,
  stage1_diagnosis_json TEXT NOT NULL,
  stage2_abstraction_json TEXT NOT NULL,
  stage3_refinement_json TEXT NOT NULL,
  candidate_semantic_rules INTEGER NOT NULL DEFAULT 0,
  semantic_memory_size INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Strategy proposals with schema fields and review state.
CREATE TABLE IF NOT EXISTS strategy_proposals (
  proposal_id TEXT PRIMARY KEY,
  generated_by TEXT NOT NULL,
  target_rule TEXT NOT NULL,
  rule_category TEXT NOT NULL,
  current_value TEXT NOT NULL,
  proposed_value TEXT NOT NULL,
  supporting_evidence TEXT NOT NULL,
  source_episodes_json TEXT NOT NULL,
  backtest_sharpe_before REAL,
  backtest_sharpe_after REAL,
  confidence REAL NOT NULL,
  semantic_memory_action TEXT NOT NULL CHECK (semantic_memory_action IN ('ADD','UPDATE','DELETE','NONE')),
  rollback_version TEXT NOT NULL,
  requires_human_approval INTEGER NOT NULL DEFAULT 1 CHECK (requires_human_approval IN (0,1)),
  auto_approve_eligible INTEGER NOT NULL DEFAULT 0 CHECK (auto_approve_eligible IN (0,1)),
  expires_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','expired','auto_approved')),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_strategy_proposals_status
ON strategy_proposals(status, created_at);

-- Authority policy and history.
CREATE TABLE IF NOT EXISTS authority_policy (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  level INTEGER NOT NULL DEFAULT 0 CHECK (level IN (0,1,2,3)),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  note TEXT
);

INSERT OR IGNORE INTO authority_policy(id, level, note)
VALUES (1, 0, 'default Level 0: full manual approval');

CREATE TABLE IF NOT EXISTS authority_actions (
  action_id TEXT PRIMARY KEY,
  ts TEXT NOT NULL DEFAULT (datetime('now')),
  proposal_id TEXT,
  requested_level INTEGER NOT NULL,
  decided_level INTEGER NOT NULL,
  allowed INTEGER NOT NULL CHECK (allowed IN (0,1)),
  reason_code TEXT NOT NULL
);

INSERT OR IGNORE INTO schema_migrations(version, applied_at)
VALUES ('v1.2.2', datetime('now'));

COMMIT;
