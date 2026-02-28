-- migration_v1_1_1_order_events.sql
-- Adds audit trail for order lifecycle transitions and external events.

BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS order_events (
  event_id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  order_id TEXT NOT NULL,
  event_type TEXT NOT NULL,       -- submitted/fill/status_transition/cancel_requested/cancelled/rejected
  from_status TEXT,
  to_status TEXT,
  source TEXT NOT NULL,           -- execution/broker/sentinel/manual
  reason_code TEXT,
  payload_json TEXT NOT NULL,
  FOREIGN KEY (order_id) REFERENCES orders(order_id)
);

CREATE INDEX IF NOT EXISTS idx_order_events_order_ts
ON order_events(order_id, ts);

CREATE INDEX IF NOT EXISTS idx_order_events_reason
ON order_events(reason_code, ts);

CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL
);

INSERT OR IGNORE INTO schema_migrations(version, applied_at)
VALUES ('v1.1.1', datetime('now'));

COMMIT;
