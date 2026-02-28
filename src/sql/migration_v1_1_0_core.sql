-- migration_v1_1_0_core.sql
-- Core schema for OpenClaw v1.1 execution, risk, and portfolio pipeline.

PRAGMA foreign_keys = ON;

BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS strategy_versions (
  version_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  config_json TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('shadow','canary','active','rolled_back')),
  parent_version_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_strategy_versions_status
ON strategy_versions(status);

CREATE TABLE IF NOT EXISTS risk_limits (
  limit_id TEXT PRIMARY KEY,
  scope TEXT NOT NULL CHECK (scope IN ('global','symbol','strategy')),
  symbol TEXT,
  strategy_id TEXT,
  rule_name TEXT NOT NULL,
  rule_value REAL NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_risk_limits_lookup
ON risk_limits(scope, symbol, strategy_id, rule_name, enabled);

CREATE TABLE IF NOT EXISTS decisions (
  decision_id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  symbol TEXT NOT NULL,
  strategy_id TEXT NOT NULL,
  strategy_version TEXT NOT NULL,
  signal_side TEXT NOT NULL CHECK (signal_side IN ('buy','sell','flat')),
  signal_score REAL NOT NULL,
  signal_ttl_ms INTEGER NOT NULL DEFAULT 30000,
  llm_ref TEXT,
  reason_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_decisions_ts
ON decisions(ts);

CREATE INDEX IF NOT EXISTS idx_decisions_symbol_ts
ON decisions(symbol, ts);

CREATE TABLE IF NOT EXISTS risk_checks (
  check_id TEXT PRIMARY KEY,
  decision_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  passed INTEGER NOT NULL CHECK (passed IN (0,1)),
  reject_code TEXT,
  metrics_json TEXT NOT NULL,
  FOREIGN KEY (decision_id) REFERENCES decisions(decision_id)
);

CREATE INDEX IF NOT EXISTS idx_risk_checks_decision
ON risk_checks(decision_id, ts);

CREATE INDEX IF NOT EXISTS idx_risk_checks_reject
ON risk_checks(reject_code, ts);

CREATE TABLE IF NOT EXISTS orders (
  order_id TEXT PRIMARY KEY,
  decision_id TEXT NOT NULL,
  broker_order_id TEXT,
  ts_submit TEXT NOT NULL,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL CHECK (side IN ('buy','sell')),
  qty INTEGER NOT NULL CHECK (qty > 0),
  price REAL,
  order_type TEXT NOT NULL CHECK (order_type IN ('market','limit')),
  tif TEXT NOT NULL CHECK (tif IN ('ROD','IOC','FOK')),
  status TEXT NOT NULL CHECK (status IN ('new','submitted','partially_filled','filled','cancelled','rejected','expired')),
  strategy_version TEXT NOT NULL,
  FOREIGN KEY (decision_id) REFERENCES decisions(decision_id)
);

CREATE INDEX IF NOT EXISTS idx_orders_ts
ON orders(ts_submit);

CREATE INDEX IF NOT EXISTS idx_orders_symbol_ts
ON orders(symbol, ts_submit);

CREATE INDEX IF NOT EXISTS idx_orders_broker_order_id
ON orders(broker_order_id);

CREATE TABLE IF NOT EXISTS fills (
  fill_id TEXT PRIMARY KEY,
  order_id TEXT NOT NULL,
  ts_fill TEXT NOT NULL,
  qty INTEGER NOT NULL CHECK (qty > 0),
  price REAL NOT NULL CHECK (price > 0),
  fee REAL NOT NULL DEFAULT 0,
  tax REAL NOT NULL DEFAULT 0,
  FOREIGN KEY (order_id) REFERENCES orders(order_id)
);

CREATE INDEX IF NOT EXISTS idx_fills_order
ON fills(order_id, ts_fill);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  nav REAL NOT NULL,
  cash REAL NOT NULL,
  gross_exposure REAL NOT NULL,
  net_exposure REAL NOT NULL,
  unrealized_pnl REAL NOT NULL,
  realized_pnl REAL NOT NULL,
  drawdown REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_ts
ON portfolio_snapshots(ts);

CREATE TABLE IF NOT EXISTS incidents (
  incident_id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  severity TEXT NOT NULL CHECK (severity IN ('info','warn','critical')),
  source TEXT NOT NULL,
  code TEXT NOT NULL,
  detail_json TEXT NOT NULL,
  resolved INTEGER NOT NULL DEFAULT 0 CHECK (resolved IN (0,1))
);

CREATE INDEX IF NOT EXISTS idx_incidents_ts
ON incidents(ts);

CREATE INDEX IF NOT EXISTS idx_incidents_code
ON incidents(code, resolved);

CREATE TABLE IF NOT EXISTS trading_locks (
  lock_id TEXT PRIMARY KEY,
  locked INTEGER NOT NULL CHECK (locked IN (0,1)),
  reason_code TEXT,
  locked_at TEXT,
  unlock_after TEXT,
  note TEXT
);

CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL
);

INSERT OR IGNORE INTO schema_migrations(version, applied_at)
VALUES ('v1.1.0', datetime('now'));

COMMIT;
