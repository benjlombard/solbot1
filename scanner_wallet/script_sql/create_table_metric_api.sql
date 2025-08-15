CREATE TABLE IF NOT EXISTS api_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    api_name TEXT NOT NULL,
    call_timestamp INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    success INTEGER NOT NULL DEFAULT 1, -- BOOLEAN alias
    http_status_code INTEGER,
    error_message TEXT,
    sync_cycle_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Création des index séparément
CREATE INDEX IF NOT EXISTS idx_api_metrics_name_timestamp 
    ON api_metrics (api_name, call_timestamp);

CREATE INDEX IF NOT EXISTS idx_api_metrics_timestamp 
    ON api_metrics (call_timestamp);

CREATE INDEX IF NOT EXISTS idx_api_metrics_cycle 
    ON api_metrics (sync_cycle_id);


CREATE TABLE IF NOT EXISTS api_cycle_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_cycle_id INTEGER NOT NULL UNIQUE,
    cycle_start_time INTEGER NOT NULL,
    cycle_end_time INTEGER,
    total_api_calls INTEGER DEFAULT 0,
    total_duration_ms INTEGER DEFAULT 0,
    successful_calls INTEGER DEFAULT 0,
    failed_calls INTEGER DEFAULT 0,
    unique_apis_used INTEGER DEFAULT 0,
    tokens_processed INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index séparé
CREATE INDEX IF NOT EXISTS idx_cycle_stats_time
    ON api_cycle_stats (cycle_start_time);
