-- 1. AJOUT DE LA COLONNE STATUS À LA TABLE TOKENS
-- ================================================================================================
ALTER TABLE tokens ADD COLUMN status TEXT DEFAULT 'active';

-- Créer un index sur la colonne status pour optimiser les requêtes
CREATE INDEX IF NOT EXISTS idx_tokens_status ON tokens(status);

-- Mettre à jour tous les tokens existants avec le statut 'active' par défaut
UPDATE tokens SET status = 'active' WHERE status IS NULL;


CREATE TABLE IF NOT EXISTS tokens_hist (
    -- Clé primaire composite (address + snapshot_timestamp)
    address                              TEXT       NOT NULL,
    snapshot_timestamp                   TIMESTAMP  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    -- Copie exacte de toutes les colonnes de la table tokens (état au moment du snapshot)
    symbol                               TEXT,
    name                                 TEXT,
    decimals                             INTEGER,
    logo_uri                             TEXT,
    price_usdc                           REAL,
    market_cap                           REAL,
    liquidity_usd                        REAL,
    volume_24h                           REAL,
    price_change_24h                     REAL,
    age_hours                            REAL,
    quality_score                        REAL,
    rug_score                            REAL,
    holders                              INTEGER,
    holder_distribution                  TEXT,
    is_tradeable                         BOOLEAN    DEFAULT 0,
    invest_score                         REAL,
    early_bonus                          INTEGER    DEFAULT 0,
    social_bonus                         INTEGER    DEFAULT 0,
    holders_bonus                        INTEGER    DEFAULT 0,
    first_discovered_at                  TIMESTAMP,
    launch_timestamp                     TIMESTAMP,
    bonding_curve_status                 TEXT,
    raydium_pool_address                 TEXT,
    updated_at                           TIMESTAMP,
    bonding_curve_progress               REAL       DEFAULT 0,
    
    -- Colonnes DexScreener
    dexscreener_pair_created_at          TIMESTAMP,
    dexscreener_price_usd                REAL       DEFAULT 0,
    dexscreener_market_cap               REAL       DEFAULT 0,
    dexscreener_liquidity_base           REAL       DEFAULT 0,
    dexscreener_liquidity_quote          REAL       DEFAULT 0,
    dexscreener_volume_1h                REAL       DEFAULT 0,
    dexscreener_volume_6h                REAL       DEFAULT 0,
    dexscreener_volume_24h               REAL       DEFAULT 0,
    dexscreener_price_change_1h          REAL       DEFAULT 0,
    dexscreener_price_change_6h          REAL       DEFAULT 0,
    dexscreener_price_change_h24         REAL       DEFAULT 0,
    dexscreener_txns_1h                  INTEGER    DEFAULT 0,
    dexscreener_txns_6h                  INTEGER    DEFAULT 0,
    dexscreener_txns_24h                 INTEGER    DEFAULT 0,
    dexscreener_buys_1h                  INTEGER    DEFAULT 0,
    dexscreener_sells_1h                 INTEGER    DEFAULT 0,
    dexscreener_buys_24h                 INTEGER    DEFAULT 0,
    dexscreener_sells_24h                INTEGER    DEFAULT 0,
    dexscreener_dexscreener_url          TEXT,
    dexscreener_last_dexscreener_update  TIMESTAMP,
    
    -- Statut au moment du snapshot
    status                               TEXT       DEFAULT 'active',
    
    -- Métadonnées du snapshot
    snapshot_reason                      TEXT,      -- Pourquoi ce snapshot a été créé
    
    -- Clé primaire composite
    PRIMARY KEY (address, snapshot_timestamp)
);


-- Index principal pour les requêtes par token
CREATE INDEX IF NOT EXISTS idx_tokens_hist_address ON tokens_hist(address);

-- Index pour les requêtes temporelles
CREATE INDEX IF NOT EXISTS idx_tokens_hist_timestamp ON tokens_hist(snapshot_timestamp);

-- Index composite pour les requêtes token + période
CREATE INDEX IF NOT EXISTS idx_tokens_hist_address_timestamp ON tokens_hist(address, snapshot_timestamp);

-- Index pour les requêtes de statut historique
CREATE INDEX IF NOT EXISTS idx_tokens_hist_status ON tokens_hist(status);

-- Index pour les analyses de volume (détection d'inactivité)
CREATE INDEX IF NOT EXISTS idx_tokens_hist_volume_analysis ON tokens_hist(address, snapshot_timestamp, dexscreener_volume_24h);

-- Index pour les analyses de liquidité
CREATE INDEX IF NOT EXISTS idx_tokens_hist_liquidity_analysis ON tokens_hist(address, snapshot_timestamp, dexscreener_liquidity_quote);
