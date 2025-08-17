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