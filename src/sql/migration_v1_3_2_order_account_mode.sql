-- migration_v1_3_2_order_account_mode.sql
-- 為 orders 表加入 account_mode 欄位，記錄訂單是模擬還是實盤
-- 支援 paper-vs-live execution quality 比對
-- Issue #284

ALTER TABLE orders ADD COLUMN account_mode TEXT NOT NULL DEFAULT 'simulation';

CREATE INDEX IF NOT EXISTS idx_orders_account_mode_symbol
ON orders(account_mode, symbol, ts_submit);
