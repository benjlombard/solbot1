CREATE TABLE scan_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address TEXT NOT NULL,
    cycle_id TEXT,
    scan_type TEXT NOT NULL,
    total_accounts INTEGER DEFAULT 0,
    new_accounts INTEGER DEFAULT 0,
    scan_duration REAL DEFAULT 0.0,
    completed_at INTEGER NOT NULL,
    priority_score_before REAL DEFAULT 1.0,
    priority_score_after REAL DEFAULT 1.0,
    rpc_requests_count INTEGER DEFAULT 0,
    efficiency_score REAL DEFAULT 0.0,
    activity_detected INTEGER DEFAULT 0,
    errors_count INTEGER DEFAULT 0,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
