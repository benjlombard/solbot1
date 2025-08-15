-- =====================================================================
-- SCRIPT SQL - SYSTÈME D'HISTORISATION DES TOKENS
-- Solana Wallet Monitor - Historisation et Filtrage Intelligent
-- =====================================================================

-- 1. CRÉATION DE LA TABLE tokens_history
-- =====================================================================
CREATE TABLE IF NOT EXISTS tokens_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_address TEXT NOT NULL,
    
    -- Données de prix et marché
    price_usd REAL DEFAULT 0.0,
    market_cap REAL DEFAULT 0.0,
    volume_5m REAL DEFAULT 0.0,
    volume_1h REAL DEFAULT 0.0,
    volume_6h REAL DEFAULT 0.0,
    volume_24h REAL DEFAULT 0.0,
    
    -- Changements de prix
    price_change_5m REAL DEFAULT 0.0,
    price_change_1h REAL DEFAULT 0.0,
    price_change_6h REAL DEFAULT 0.0,
    price_change_24h REAL DEFAULT 0.0,
    
    -- Métriques sociales et communauté
    holder_count INTEGER DEFAULT 0,
    creator_address TEXT,
    bonding_curve_progress REAL DEFAULT 0.0,
    
    -- Liquidité et trading
    liquidity_usd REAL DEFAULT 0.0,
    liquidity_sol REAL DEFAULT 0.0,
    fdv REAL DEFAULT 0.0,
    
    -- Métriques calculées
    liquidity_mc_ratio REAL DEFAULT 0.0,  -- liquidity/market_cap
    volume_mc_ratio REAL DEFAULT 0.0,     -- volume_24h/market_cap
    price_volatility_1h REAL DEFAULT 0.0, -- Volatilité calculée
    
    -- Métadonnées
    symbol TEXT,
    name TEXT,
    decimals INTEGER DEFAULT 9,
    logo_uri TEXT,
    is_verified BOOLEAN DEFAULT 0,
    metadata_source TEXT,
    
    -- Tracking temporel
    snapshot_timestamp INTEGER NOT NULL,  -- Timestamp de cette snapshot
    previous_snapshot_id INTEGER,         -- ID de la snapshot précédente pour ce token
    
    -- Changements depuis la snapshot précédente (deltas)
    price_delta_usd REAL DEFAULT 0.0,
    market_cap_delta REAL DEFAULT 0.0,
    volume_24h_delta REAL DEFAULT 0.0,
    holder_count_delta INTEGER DEFAULT 0,
    
    -- Flags et scores
    viability_score REAL DEFAULT 50.0,    -- Score de viabilité 0-100
    risk_score REAL DEFAULT 50.0,         -- Score de risque 0-100
    momentum_score REAL DEFAULT 0.0,      -- Score de momentum
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Contraintes
    FOREIGN KEY (token_address) REFERENCES tokens(address),
    FOREIGN KEY (previous_snapshot_id) REFERENCES tokens_history(id)
);
-- 3. CRÉATION DES INDEX POUR OPTIMISER LES PERFORMANCES
-- =====================================================================

-- Index principaux pour tokens_history
CREATE INDEX IF NOT EXISTS idx_tokens_history_address ON tokens_history(token_address);
CREATE INDEX IF NOT EXISTS idx_tokens_history_timestamp ON tokens_history(snapshot_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_tokens_history_address_timestamp ON tokens_history(token_address, snapshot_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_tokens_history_previous_snapshot ON tokens_history(previous_snapshot_id);

-- Index pour les scores et filtrage
CREATE INDEX IF NOT EXISTS idx_tokens_history_viability_score ON tokens_history(viability_score DESC);
CREATE INDEX IF NOT EXISTS idx_tokens_history_risk_score ON tokens_history(risk_score DESC);
CREATE INDEX IF NOT EXISTS idx_tokens_history_momentum_score ON tokens_history(momentum_score DESC);

-- Index pour les métriques de performance
CREATE INDEX IF NOT EXISTS idx_tokens_history_price_delta ON tokens_history(price_delta_usd DESC);
CREATE INDEX IF NOT EXISTS idx_tokens_history_volume_delta ON tokens_history(volume_24h_delta DESC);

-- Index composites pour les requêtes complexes
CREATE INDEX IF NOT EXISTS idx_tokens_history_score_timestamp ON tokens_history(viability_score DESC, snapshot_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_tokens_history_address_score ON tokens_history(token_address, viability_score DESC);

-- Index pour la table tokens mise à jour
CREATE INDEX IF NOT EXISTS idx_tokens_is_dead ON tokens(is_dead);
CREATE INDEX IF NOT EXISTS idx_tokens_viability_score ON tokens(viability_score DESC);
CREATE INDEX IF NOT EXISTS idx_tokens_risk_score ON tokens(risk_score DESC);
CREATE INDEX IF NOT EXISTS idx_tokens_momentum_score ON tokens(momentum_score DESC);
CREATE INDEX IF NOT EXISTS idx_tokens_last_historized ON tokens(last_historized_at DESC);

-- Index composites pour filtrage avancé
CREATE INDEX IF NOT EXISTS idx_tokens_alive_viability ON tokens(is_dead, viability_score DESC) WHERE is_dead = 0;
CREATE INDEX IF NOT EXISTS idx_tokens_active_updated ON tokens(is_dead, updated_at DESC) WHERE is_dead = 0;

CREATE TABLE tokens (
    -- Identité
    address TEXT PRIMARY KEY,
    symbol TEXT,
    name TEXT,
    decimals INTEGER DEFAULT 9,
    logo_uri TEXT,
    coingecko_id TEXT,
    metadata_source TEXT,
    creator_address TEXT,

    -- Statut et vérifications
    is_verified BOOLEAN DEFAULT 0,
    contract_verified BOOLEAN DEFAULT 0,
    has_social_presence BOOLEAN DEFAULT 0,
    is_dead BOOLEAN DEFAULT 0,
    death_reason TEXT,
    death_timestamp INTEGER DEFAULT 0,

    -- Prix & marchés
    price_usd REAL DEFAULT 0.0,
    market_cap REAL DEFAULT 0.0,
    fdv REAL DEFAULT 0.0,
    liquidity_usd REAL DEFAULT 0.0,
    liquidity_sol REAL DEFAULT 0.0,
    liquidity_mc_ratio REAL DEFAULT 0.0,
    volume_mc_ratio REAL DEFAULT 0.0,
    price_volatility_24h REAL DEFAULT 0.0,

    -- Volumes
    volume_5m REAL DEFAULT 0.0,
    volume_1h REAL DEFAULT 0.0,
    volume_6h REAL DEFAULT 0.0,
    volume_24h REAL DEFAULT 0.0,

    -- Variations de prix
    price_change_5m REAL DEFAULT 0.0,
    price_change_1h REAL DEFAULT 0.0,
    price_change_6h REAL DEFAULT 0.0,
    price_change_24h REAL DEFAULT 0.0,
    price_delta_24h REAL DEFAULT 0.0,
    volume_delta_24h REAL DEFAULT 0.0,
    holder_delta_24h INTEGER DEFAULT 0,

    -- Scores
    viability_score REAL DEFAULT 50.0,
    risk_score REAL DEFAULT 50.0,
    momentum_score REAL DEFAULT 0.0,

    -- Autres métriques
    bonding_curve_progress REAL DEFAULT 0.0,
    holder_count INTEGER DEFAULT 0,

    -- Tracking & historisation
    last_price_update INTEGER DEFAULT 0,
    last_historized_at INTEGER DEFAULT 0,
    history_snapshots_count INTEGER DEFAULT 0,
    last_dev_activity INTEGER DEFAULT 0,
    no_data_last_check TIMESTAMP,
    failed_attempts INTEGER DEFAULT 0,
    no_data_available INTEGER DEFAULT 0,

    -- Dates
    timestamp_token_created INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE transactions (
    id INTEGER PRIMARY KEY,
    signature TEXT NOT NULL,
    wallet_address TEXT NOT NULL,
    slot INTEGER,
    block_time INTEGER,
    amount REAL DEFAULT 0.0,
    token_mint TEXT,
    token_symbol TEXT,
    token_name TEXT,
    transaction_type TEXT,
    token_amount REAL DEFAULT 0.0,
    price_per_token REAL DEFAULT 0.0,
    fee REAL DEFAULT 0.0,
    status TEXT DEFAULT 'success',
    is_token_transaction BOOLEAN DEFAULT 0,
    is_large_token_amount BOOLEAN DEFAULT 0,
    detection_delay REAL DEFAULT 0.0,
    wallet_priority_at_detection REAL DEFAULT 1.0,
    scan_cycle_id TEXT,
    source TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. CRÉATION DE TRIGGERS POUR L'AUTOMATISATION
-- =====================================================================

-- Trigger pour mettre à jour automatiquement updated_at dans tokens
CREATE TRIGGER IF NOT EXISTS tokens_updated_at_trigger
    AFTER UPDATE ON tokens
    FOR EACH ROW
BEGIN
    UPDATE tokens SET updated_at = CURRENT_TIMESTAMP WHERE address = NEW.address;
END;

-- Trigger pour incrémenter le compteur de snapshots
CREATE TRIGGER IF NOT EXISTS tokens_history_count_trigger
    AFTER INSERT ON tokens_history
    FOR EACH ROW
BEGIN
    UPDATE tokens 
    SET history_snapshots_count = history_snapshots_count + 1
    WHERE address = NEW.token_address;
END;


-- 4. CRÉATION DE VUES UTILES POUR LES REQUÊTES FRÉQUENTES
-- =====================================================================

-- Vue pour les tokens vivants avec leurs dernières métriques
CREATE VIEW IF NOT EXISTS tokens_alive AS
SELECT 
    t.*,
    th.price_delta_usd,
    th.volume_24h_delta,
    th.holder_count_delta,
    th.momentum_score as latest_momentum
FROM tokens t
LEFT JOIN tokens_history th ON t.address = th.token_address 
    AND th.id = (
        SELECT id FROM tokens_history th2 
        WHERE th2.token_address = t.address 
        ORDER BY th2.snapshot_timestamp DESC 
        LIMIT 1
    )
WHERE t.is_dead = 0;

-- Vue pour les tokens avec tendances (dernières 24h)
CREATE VIEW IF NOT EXISTS tokens_trending AS
SELECT 
    t.address,
    t.symbol,
    t.name,
    t.price_usd,
    t.market_cap,
    t.volume_24h,
    t.viability_score,
    t.momentum_score,
    
    -- Calculs de tendance basés sur l'historique
    AVG(th.price_delta_usd) as avg_price_trend_24h,
    AVG(th.volume_24h_delta) as avg_volume_trend_24h,
    COUNT(th.id) as snapshots_count,
    
    -- Classification automatique
    CASE 
        WHEN t.momentum_score > 80 THEN 'HOT'
        WHEN t.momentum_score > 60 THEN 'TRENDING'
        WHEN t.momentum_score > 40 THEN 'STABLE'
        WHEN t.momentum_score > 20 THEN 'DECLINING'
        ELSE 'DEAD'
    END as trend_category
    
FROM tokens t
LEFT JOIN tokens_history th ON t.address = th.token_address 
    AND th.snapshot_timestamp > (strftime('%s', 'now') - 86400) -- Dernières 24h
WHERE t.is_dead = 0
GROUP BY t.address, t.symbol, t.name, t.price_usd, t.market_cap, t.volume_24h, t.viability_score, t.momentum_score
HAVING snapshots_count > 0
ORDER BY t.momentum_score DESC;

-- Vue pour les tokens à risque
CREATE VIEW IF NOT EXISTS tokens_at_risk AS
SELECT 
    t.address,
    t.symbol,
    t.name,
    t.risk_score,
    t.viability_score,
    t.death_reason,
    
    -- Signaux de danger
    CASE WHEN t.price_delta_24h < -0.8 THEN 1 ELSE 0 END as price_crash_signal,
    CASE WHEN t.volume_delta_24h < -0.9 THEN 1 ELSE 0 END as volume_death_signal,
    CASE WHEN t.liquidity_mc_ratio < 0.05 THEN 1 ELSE 0 END as liquidity_risk_signal,
    CASE WHEN t.holder_delta_24h < -0.5 THEN 1 ELSE 0 END as holder_exodus_signal,
    
    -- Score de danger composite
    (CASE WHEN t.price_delta_24h < -0.8 THEN 25 ELSE 0 END +
     CASE WHEN t.volume_delta_24h < -0.9 THEN 25 ELSE 0 END +
     CASE WHEN t.liquidity_mc_ratio < 0.05 THEN 25 ELSE 0 END +
     CASE WHEN t.holder_delta_24h < -0.5 THEN 25 ELSE 0 END) as danger_score
     
FROM tokens t
WHERE t.is_dead = 0 
AND t.risk_score > 60
ORDER BY danger_score DESC, t.risk_score DESC;