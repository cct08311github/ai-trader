-- migration_v1_3_1_signal_attribution.sql
-- 新增信號來源歸因欄位至 decisions 表，支援後續績效歸因報告
-- Issue #283

-- 為 decisions 表加入 signal_source 欄位（dominant signal contributor）
ALTER TABLE decisions ADD COLUMN signal_source TEXT;

-- 建立索引以加速歸因查詢
CREATE INDEX IF NOT EXISTS idx_decisions_signal_source
ON decisions(signal_source, ts);
