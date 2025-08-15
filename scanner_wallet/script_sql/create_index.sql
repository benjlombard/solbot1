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
