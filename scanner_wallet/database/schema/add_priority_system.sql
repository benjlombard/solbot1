-- Migration pour ajouter le système de priorité
-- À exécuter UNE SEULE FOIS

-- Ajouter les colonnes de priorité à la table tokens
ALTER TABLE tokens ADD COLUMN priority_level INTEGER DEFAULT 2;  -- WARM par défaut
ALTER TABLE tokens ADD COLUMN priority_score REAL DEFAULT 50.0;
ALTER TABLE tokens ADD COLUMN last_priority_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE tokens ADD COLUMN priority_recalc_needed INTEGER DEFAULT 1;

-- Créer un index pour optimiser les requêtes par priorité
CREATE INDEX IF NOT EXISTS idx_tokens_priority_level ON tokens(priority_level);
CREATE INDEX IF NOT EXISTS idx_tokens_priority_update ON tokens(last_priority_update);
CREATE INDEX IF NOT EXISTS idx_tokens_priority_score ON tokens(priority_score DESC);

-- Table pour stocker les métriques de performance du système de priorité
CREATE TABLE IF NOT EXISTS priority_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,
    hot_tokens_count INTEGER DEFAULT 0,
    warm_tokens_count INTEGER DEFAULT 0,
    cold_tokens_count INTEGER DEFAULT 0,
    dead_tokens_count INTEGER DEFAULT 0,
    critical_tokens_count INTEGER DEFAULT 0,
    api_calls_saved INTEGER DEFAULT 0,
    cycle_duration_ms INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);


-- Table pour l'historique des changements de priorité
CREATE TABLE IF NOT EXISTS priority_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_address TEXT NOT NULL,
    old_priority INTEGER,
    new_priority INTEGER NOT NULL,
    old_score REAL,
    new_score REAL NOT NULL,
    reason TEXT,
    timestamp INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index pour l'historique
CREATE INDEX IF NOT EXISTS idx_priority_history_token ON priority_history(token_address);
CREATE INDEX IF NOT EXISTS idx_priority_history_timestamp ON priority_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_priority_history_created ON priority_history(created_at);