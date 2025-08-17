CREATE TABLE tokens (
    -- === Identité ===
    address TEXT PRIMARY KEY,
    symbol TEXT,
    name TEXT,
    decimals INTEGER DEFAULT 9,
    logo_uri TEXT,
    coingecko_id TEXT,
    metadata_source TEXT,
    creator_address TEXT,

    -- === Statut et vérifications ===
    is_verified BOOLEAN DEFAULT 0,
    contract_verified BOOLEAN DEFAULT 0,
    has_social_presence BOOLEAN DEFAULT 0,
    is_dead BOOLEAN DEFAULT 0,
    death_reason TEXT,
    death_timestamp INTEGER DEFAULT 0,

    -- === Scores & risques ===
    viability_score REAL DEFAULT 50.0,
    risk_score REAL DEFAULT 50.0,
    momentum_score REAL DEFAULT 0.0,
    predictive_scam_score REAL DEFAULT 50.0, -- Score prédictif de scam/rug (0=safe, 100=danger)
    rug_risk_score INTEGER DEFAULT 50,       -- Score de risque rug
    rug_raw_score INTEGER DEFAULT 0,         -- Score brut rug
    is_rugged BOOLEAN DEFAULT 0,
    mint_authority_revoked BOOLEAN DEFAULT 0,
    freeze_authority_revoked BOOLEAN DEFAULT 0,
    has_low_liquidity BOOLEAN DEFAULT 0,
    risk_count INTEGER DEFAULT 0,            -- Nombre de risques détectés par rugcheck

    -- === Prix & marchés ===
    price_usd REAL DEFAULT 0.0,
    market_cap REAL DEFAULT 0.0,
    fdv REAL DEFAULT 0.0,
    liquidity_usd REAL DEFAULT 0.0,
    liquidity_sol REAL DEFAULT 0.0,
    liquidity_mc_ratio REAL DEFAULT 0.0,
    volume_mc_ratio REAL DEFAULT 0.0,
    price_volatility_24h REAL DEFAULT 0.0,

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
    price_delta_24h REAL DEFAULT 0.0,
    volume_delta_24h REAL DEFAULT 0.0,
    holder_delta_24h INTEGER DEFAULT 0,

    -- === Analyse des holders ===
    bonding_curve_progress REAL DEFAULT 0.0,
    holder_count INTEGER DEFAULT 0,
    top_holder_percentage REAL DEFAULT 0.0,
    top_10_holders_percentage REAL DEFAULT 0.0,
    insider_holders_count INTEGER DEFAULT 0,
    insider_networks_detected INTEGER DEFAULT 0,

    -- === Launchpad ===
    launchpad_name TEXT,
    is_pump_fun BOOLEAN DEFAULT 0,

    -- === Liquidité & providers ===
    lp_providers_count INTEGER DEFAULT 0,

    -- === Tracking & historisation ===
    last_price_update INTEGER DEFAULT 0,
    last_historized_at INTEGER DEFAULT 0,
    history_snapshots_count INTEGER DEFAULT 0,
    last_dev_activity INTEGER DEFAULT 0,
    last_rugcheck_update INTEGER DEFAULT 0,   -- Date de mise à jour rugcheck
    no_data_last_check TIMESTAMP,
    failed_attempts INTEGER DEFAULT 0,
    no_data_available INTEGER DEFAULT 0,

    -- === Dates ===
    timestamp_token_created INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
