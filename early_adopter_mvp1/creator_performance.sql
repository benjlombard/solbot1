-- Migration SQL pour ajouter le système de performance des créateurs

-- 1. Créer la table creator_performance
CREATE TABLE IF NOT EXISTS creator_performance (
    creator_address TEXT PRIMARY KEY,
    total_tokens_created INTEGER DEFAULT 0,
    successful_tokens INTEGER DEFAULT 0,
    failed_tokens INTEGER DEFAULT 0,
    neutral_tokens INTEGER DEFAULT 0,
    avg_roi REAL DEFAULT 0.0,
    avg_peak_market_cap REAL DEFAULT 0.0,
    avg_survival_time_hours REAL DEFAULT 0.0,
    success_rate REAL DEFAULT 0.0,
    failure_rate REAL DEFAULT 0.0,
    risk_score REAL DEFAULT 50.0,
    reputation_score REAL DEFAULT 50.0,
    confidence_level TEXT DEFAULT 'UNKNOWN',
    is_blacklisted BOOLEAN DEFAULT FALSE,
    blacklist_reason TEXT,
    consecutive_failures INTEGER DEFAULT 0,
    best_token_roi REAL DEFAULT 0.0,
    worst_token_roi REAL DEFAULT 0.0,
    avg_time_between_launches_hours REAL DEFAULT 0.0,
    last_success_date TIMESTAMP,
    last_failure_date TIMESTAMP,
    first_token_date TIMESTAMP,
    last_token_date TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Créer les index pour optimiser les performances
CREATE INDEX IF NOT EXISTS idx_creator_reputation_score ON creator_performance(reputation_score DESC);
CREATE INDEX IF NOT EXISTS idx_creator_success_rate ON creator_performance(success_rate DESC);
CREATE INDEX IF NOT EXISTS idx_creator_risk_score ON creator_performance(risk_score ASC);
CREATE INDEX IF NOT EXISTS idx_creator_blacklisted ON creator_performance(is_blacklisted);
CREATE INDEX IF NOT EXISTS idx_creator_total_tokens ON creator_performance(total_tokens_created DESC);
CREATE INDEX IF NOT EXISTS idx_creator_last_updated ON creator_performance(last_updated DESC);

-- 3. Ajouter colonnes à pump_tokens pour lier aux performances créateur
ALTER TABLE pump_tokens ADD COLUMN creator_reputation_score REAL DEFAULT NULL;
ALTER TABLE pump_tokens ADD COLUMN creator_risk_score REAL DEFAULT NULL;
ALTER TABLE pump_tokens ADD COLUMN creator_is_blacklisted BOOLEAN DEFAULT FALSE;
ALTER TABLE pump_tokens ADD COLUMN creator_total_previous_tokens INTEGER DEFAULT 0;
ALTER TABLE pump_tokens ADD COLUMN creator_success_rate REAL DEFAULT NULL;

-- 4. Créer la table token_outcomes pour tracker les résultats (si pas déjà existante)
CREATE TABLE IF NOT EXISTS token_outcomes_extended (
    token_address TEXT PRIMARY KEY,
    outcome_type TEXT, -- 'SUCCESS', 'FAILURE', 'NEUTRAL', 'PENDING'
    roi_1h REAL,
    roi_6h REAL,
    roi_24h REAL,
    roi_7d REAL,
    peak_market_cap REAL,
    current_market_cap REAL,
    survival_time_hours REAL,
    is_rugged BOOLEAN DEFAULT FALSE,
    rug_detection_date TIMESTAMP,
    migration_date TIMESTAMP,
    death_date TIMESTAMP,
    final_status TEXT, -- 'MIGRATED', 'DEAD', 'RUGGED', 'ACTIVE'
    evaluation_date TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (token_address) REFERENCES pump_tokens(address)
);

-- 5. Index pour token_outcomes_extended
CREATE INDEX IF NOT EXISTS idx_token_outcomes_type ON token_outcomes_extended(outcome_type);
CREATE INDEX IF NOT EXISTS idx_token_outcomes_roi_24h ON token_outcomes_extended(roi_24h DESC);
CREATE INDEX IF NOT EXISTS idx_token_outcomes_survival ON token_outcomes_extended(survival_time_hours DESC);
CREATE INDEX IF NOT EXISTS idx_token_outcomes_status ON token_outcomes_extended(final_status);

-- 6. Créer la table creator_token_history pour historique détaillé
CREATE TABLE IF NOT EXISTS creator_token_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_address TEXT,
    token_address TEXT,
    token_name TEXT,
    token_symbol TEXT,
    launch_date TIMESTAMP,
    outcome_type TEXT,
    roi_24h REAL,
    peak_market_cap REAL,
    survival_time_hours REAL,
    is_success BOOLEAN,
    contributed_to_blacklist BOOLEAN DEFAULT FALSE,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (creator_address) REFERENCES creator_performance(creator_address),
    FOREIGN KEY (token_address) REFERENCES pump_tokens(address)
);

-- 7. Index pour creator_token_history
CREATE INDEX IF NOT EXISTS idx_creator_history_creator ON creator_token_history(creator_address);
CREATE INDEX IF NOT EXISTS idx_creator_history_token ON creator_token_history(token_address);
CREATE INDEX IF NOT EXISTS idx_creator_history_outcome ON creator_token_history(outcome_type);
CREATE INDEX IF NOT EXISTS idx_creator_history_launch_date ON creator_token_history(launch_date DESC);

-- 8. Vue pour faciliter les requêtes de performance créateur
CREATE VIEW IF NOT EXISTS creator_performance_summary AS
SELECT 
    cp.*,
    pt.name as latest_token_name,
    pt.symbol as latest_token_symbol,
    pt.created_at as latest_token_date,
    CASE 
        WHEN cp.reputation_score >= 80 THEN 'EXCELLENT'
        WHEN cp.reputation_score >= 60 THEN 'GOOD'
        WHEN cp.reputation_score >= 40 THEN 'AVERAGE'
        WHEN cp.reputation_score >= 20 THEN 'POOR'
        ELSE 'VERY_POOR'
    END as reputation_category,
    CASE 
        WHEN cp.risk_score <= 20 THEN 'LOW_RISK'
        WHEN cp.risk_score <= 40 THEN 'MEDIUM_RISK'
        WHEN cp.risk_score <= 60 THEN 'HIGH_RISK'
        ELSE 'VERY_HIGH_RISK'
    END as risk_category
FROM creator_performance cp
LEFT JOIN pump_tokens pt ON cp.creator_address = pt.creator 
    AND pt.created_at = cp.last_token_date;

-- 9. Trigger pour auto-update de last_updated
CREATE TRIGGER IF NOT EXISTS update_creator_performance_timestamp 
    AFTER UPDATE ON creator_performance
BEGIN
    UPDATE creator_performance 
    SET last_updated = CURRENT_TIMESTAMP 
    WHERE creator_address = NEW.creator_address;
END;