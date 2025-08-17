CREATE TABLE IF NOT EXISTS token_processing_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_address TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', -- pending, processing, completed, failed
    retry_count INTEGER DEFAULT 0,
    
    -- Information sur la source de la tâche
    source_transaction_signature TEXT,
    source_wallet_address TEXT,

    -- Timestamps pour le suivi
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processing_started_at TIMESTAMP,
    completed_at TIMESTAMP,
    
    -- Pour le débogage
    last_error TEXT,
    
    UNIQUE(token_address)
);

-- Index pour une récupération rapide des tâches en attente
CREATE INDEX IF NOT EXISTS idx_queue_status_created ON token_processing_queue(status, created_at);
