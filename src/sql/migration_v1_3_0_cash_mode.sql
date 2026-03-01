-- Migration v1.3.0: Add cash mode state tracking (v4 #20)
-- Date: 2026-03-01

-- Cash mode state table (singleton)
CREATE TABLE IF NOT EXISTS cash_mode_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    is_active INTEGER NOT NULL DEFAULT 0,
    rating REAL NOT NULL DEFAULT 50.0,
    reason_code TEXT NOT NULL DEFAULT 'UNINITIALIZED',
    detail_json TEXT NOT NULL DEFAULT '{}',
    market_regime TEXT NOT NULL DEFAULT 'range',
    confidence REAL NOT NULL DEFAULT 0.0,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Cash mode history table
CREATE TABLE IF NOT EXISTS cash_mode_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_ms INTEGER NOT NULL,
    is_active INTEGER NOT NULL,
    rating REAL NOT NULL,
    reason_code TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    market_regime TEXT NOT NULL,
    confidence REAL NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index for querying history by time
CREATE INDEX IF NOT EXISTS idx_cash_mode_history_timestamp 
ON cash_mode_history(timestamp_ms DESC);

-- Insert initial cash mode state
INSERT OR REPLACE INTO cash_mode_state (
    id, is_active, rating, reason_code, detail_json,
    market_regime, confidence, updated_at
) VALUES (
    1, 0, 50.0, 'UNINITIALIZED', '{}',
    'range', 0.0, CURRENT_TIMESTAMP
);

-- Add cash mode status to decisions table if it exists
DO $$ 
BEGIN
    -- Check if decisions table exists
    IF EXISTS (SELECT 1 FROM sqlite_master WHERE type='table' AND name='decisions') THEN
        -- Add cash_mode_active column if it doesn't exist
        BEGIN
            ALTER TABLE decisions ADD COLUMN cash_mode_active INTEGER DEFAULT 0;
        EXCEPTION WHEN duplicate_column THEN
            -- Column already exists, do nothing
            NULL;
        END;
    END IF;
END $$;
