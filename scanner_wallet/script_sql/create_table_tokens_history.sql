-- =====================================================================
-- SCRIPT SQL - SYSTÈME D'HISTORISATION DES TOKENS
-- Solana Wallet Monitor - Historisation et Filtrage Intelligent
-- =====================================================================

CREATE TABLE IF NOT EXISTS tokens_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_address TEXT NOT NULL,

    -- === Prix & marché ===
    price_usd REAL DEFAULT 0.0,
    market_cap REAL DEFAULT 0.0,
    fdv REAL DEFAULT 0.0,
    liquidity_usd REAL DEFAULT 0.0,
    liquidity_sol REAL DEFAULT 0.0,
    liquidity_mc_ratio REAL DEFAULT 0.0,  -- liquidity/market_cap
    volume_mc_ratio REAL DEFAULT 0.0,     -- volume_24h/market_cap
    price_volatility_1h REAL DEFAULT 0.0, -- Volatilité calculée

    -- === Volumes ===
    volume_5m REAL DEFAULT 0.0,
    volume_1h REAL DEFAULT 0.0,
    volume_6h REAL DEFAULT 0.0,
    volume_24h REAL DEFAULT 0.0,

    -- === Variations de prix ===
    price_change_5m REAL DEFAULT 0.0,
    price_change_1h REAL DEFAULT 0.0,
    price_change_6h REAL DEFAULT 0.0,
    price_change_24h REAL DEFAULT 0.0,

    -- === Analyse des holders ===
    holder_count INTEGER DEFAULT 0,
    bonding_curve_progress REAL DEFAULT 0.0,
    top_holder_percentage REAL DEFAULT 0.0,
    top_10_holders_percentage REAL DEFAULT 0.0,
    insider_holders_count INTEGER DEFAULT 0,
    insider_networks_detected INTEGER DEFAULT 0,

    -- === Liquidité & providers ===
    lp_providers_count INTEGER DEFAULT 0,
    has_low_liquidity BOOLEAN DEFAULT 0,

    -- === Scores & risques ===
    viability_score REAL DEFAULT 50.0,
    risk_score REAL DEFAULT 50.0,
    momentum_score REAL DEFAULT 0.0,
    rug_risk_score INTEGER DEFAULT 50,
    rug_raw_score INTEGER DEFAULT 0,
    is_rugged BOOLEAN DEFAULT 0,
    risk_count INTEGER DEFAULT 0,

    -- === Métadonnées du token ===
    creator_address TEXT,
    symbol TEXT,
    name TEXT,
    decimals INTEGER DEFAULT 9,
    logo_uri TEXT,
    is_verified BOOLEAN DEFAULT 0,
    metadata_source TEXT,

    -- === Tracking temporel ===
    snapshot_timestamp INTEGER NOT NULL,  -- Timestamp de cette snapshot
    previous_snapshot_id INTEGER,         -- ID snapshot précédente

    -- === Deltas depuis la snapshot précédente ===
    price_delta_usd REAL DEFAULT 0.0,
    market_cap_delta REAL DEFAULT 0.0,
    volume_24h_delta REAL DEFAULT 0.0,
    holder_count_delta INTEGER DEFAULT 0,
    rug_risk_score_delta REAL DEFAULT 0.0,
    top_holder_percentage_delta REAL DEFAULT 0.0,
    insider_holders_delta INTEGER DEFAULT 0,

    -- === Dates ===
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- === Contraintes ===
    FOREIGN KEY (token_address) REFERENCES tokens(address),
    FOREIGN KEY (previous_snapshot_id) REFERENCES tokens_history(id)
);
