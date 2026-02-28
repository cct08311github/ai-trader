-- risk_limits_seed_v1_1.sql
-- Seed defaults for OpenClaw v1.1 risk limits.
-- Requires table:
--   risk_limits(limit_id, scope, symbol, strategy_id, rule_name, rule_value, enabled, updated_at)

BEGIN TRANSACTION;

-- Global risk limits
INSERT OR REPLACE INTO risk_limits
  (limit_id, scope, symbol, strategy_id, rule_name, rule_value, enabled, updated_at)
VALUES
  ('global.max_daily_loss_pct', 'global', NULL, NULL, 'max_daily_loss_pct', 0.05, 1, datetime('now')),
  ('global.max_loss_per_trade_pct_nav', 'global', NULL, NULL, 'max_loss_per_trade_pct_nav', 0.005, 1, datetime('now')),
  ('global.low_confidence_threshold', 'global', NULL, NULL, 'low_confidence_threshold', 0.60, 1, datetime('now')),
  ('global.low_confidence_scale', 'global', NULL, NULL, 'low_confidence_scale', 0.50, 1, datetime('now')),
  ('global.max_orders_per_min', 'global', NULL, NULL, 'max_orders_per_min', 3, 1, datetime('now')),
  ('global.max_price_deviation_pct', 'global', NULL, NULL, 'max_price_deviation_pct', 0.02, 1, datetime('now')),
  ('global.max_slippage_bps', 'global', NULL, NULL, 'max_slippage_bps', 12, 1, datetime('now')),
  ('global.max_qty_to_1m_volume_ratio', 'global', NULL, NULL, 'max_qty_to_1m_volume_ratio', 0.15, 1, datetime('now')),
  ('global.max_feed_delay_ms', 'global', NULL, NULL, 'max_feed_delay_ms', 1000, 1, datetime('now')),
  ('global.max_db_write_p99_ms', 'global', NULL, NULL, 'max_db_write_p99_ms', 200, 1, datetime('now')),
  ('global.max_symbol_weight', 'global', NULL, NULL, 'max_symbol_weight', 0.20, 1, datetime('now')),
  ('global.max_top5_weight', 'global', NULL, NULL, 'max_top5_weight', 0.60, 1, datetime('now')),
  ('global.max_gross_exposure', 'global', NULL, NULL, 'max_gross_exposure', 1.20, 1, datetime('now')),
  ('global.max_consecutive_losses', 'global', NULL, NULL, 'max_consecutive_losses', 3, 1, datetime('now')),
  ('global.default_stop_pct', 'global', NULL, NULL, 'default_stop_pct', 0.015, 1, datetime('now')),
  ('global.allow_auto_reduce_qty', 'global', NULL, NULL, 'allow_auto_reduce_qty', 1, 1, datetime('now')),
  ('global.api_budget_warn_ratio', 'global', NULL, NULL, 'api_budget_warn_ratio', 0.20, 1, datetime('now')),
  ('global.api_budget_critical_ratio', 'global', NULL, NULL, 'api_budget_critical_ratio', 0.10, 1, datetime('now'));

-- Example symbol overrides (optional)
INSERT OR REPLACE INTO risk_limits
  (limit_id, scope, symbol, strategy_id, rule_name, rule_value, enabled, updated_at)
VALUES
  ('symbol.2330.max_symbol_weight', 'symbol', '2330', NULL, 'max_symbol_weight', 0.15, 1, datetime('now')),
  ('symbol.2330.max_qty_to_1m_volume_ratio', 'symbol', '2330', NULL, 'max_qty_to_1m_volume_ratio', 0.10, 1, datetime('now'));

-- Example strategy overrides (optional)
INSERT OR REPLACE INTO risk_limits
  (limit_id, scope, symbol, strategy_id, rule_name, rule_value, enabled, updated_at)
VALUES
  ('strategy.breakout.max_orders_per_min', 'strategy', NULL, 'breakout', 'max_orders_per_min', 2, 1, datetime('now')),
  ('strategy.breakout.max_slippage_bps', 'strategy', NULL, 'breakout', 'max_slippage_bps', 8, 1, datetime('now'));

COMMIT;
