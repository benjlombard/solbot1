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


-- Index SQLite pour optimisation des performances
-- À exécuter dans votre base de données SQLite

-- 1. Index critiques pour les requêtes tokens
CREATE INDEX IF NOT EXISTS idx_tokens_updated_price ON tokens(updated_at, price_usd);
CREATE INDEX IF NOT EXISTS idx_tokens_active_updated ON tokens(is_dead, updated_at) WHERE is_dead = 0;
CREATE INDEX IF NOT EXISTS idx_tokens_price_update ON tokens(last_price_update DESC) WHERE is_dead = 0;

-- 2. Index pour les transactions (streamlit dashboard)
CREATE INDEX IF NOT EXISTS idx_transactions_wallet_created ON transactions(wallet_address, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_token_created ON transactions(token_mint, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_type_time ON transactions(transaction_type, block_time DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_created_desc ON transactions(created_at DESC);

-- 3. Index pour les métriques API
CREATE INDEX IF NOT EXISTS idx_api_metrics_timestamp_desc ON api_metrics(call_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_api_metrics_name_time ON api_metrics(api_name, call_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_api_metrics_cycle ON api_metrics(sync_cycle_id, call_timestamp);

-- 4. Index pour wallet_priorities (scanner performance)
CREATE INDEX IF NOT EXISTS idx_wallet_priorities_score_scan ON wallet_priorities(priority_score DESC, last_scan_time ASC);
CREATE INDEX IF NOT EXISTS idx_wallet_priorities_active ON wallet_priorities(is_active, priority_score DESC) WHERE is_active = 1;

-- 5. Index pour scan_history
CREATE INDEX IF NOT EXISTS idx_scan_history_wallet_time ON scan_history(wallet_address, completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_scan_history_completed ON scan_history(completed_at DESC);

-- 6. Index pour token_accounts (balance tracking)
CREATE INDEX IF NOT EXISTS idx_token_accounts_wallet_updated ON token_accounts(wallet_address, last_updated DESC);
CREATE INDEX IF NOT EXISTS idx_token_accounts_active ON token_accounts(is_active, last_scanned) WHERE is_active = 1;

-- 7. Index pour les requêtes dashboard complexes
CREATE INDEX IF NOT EXISTS idx_tokens_market_data ON tokens(market_cap DESC, price_usd) WHERE market_cap > 0;
CREATE INDEX IF NOT EXISTS idx_transactions_recent_activity ON transactions(block_time) WHERE block_time > strftime('%s', 'now', '-24 hours');

-- 8. Index composites pour les jointures fréquentes
CREATE INDEX IF NOT EXISTS idx_transactions_wallet_token ON transactions(wallet_address, token_mint, block_time DESC);

-- 9. Index pour les statistiques temps réel
CREATE INDEX IF NOT EXISTS idx_tokens_metadata_source ON tokens(metadata_source, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_detection_delay ON transactions(detection_delay, created_at DESC);

-- Vérifier que les index ont été créés
.indexes tokens
.indexes transactions
.indexes api_metrics

-- Analyser la base pour optimiser le query planner
ANALYZE;