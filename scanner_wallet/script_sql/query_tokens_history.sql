-- =====================================================================
-- REQUÊTES D'ANALYSE POUR IDENTIFICATION D'OPPORTUNITÉS D'INVESTISSEMENT
-- =====================================================================

-- 1. TOKENS À FORTE CROISSANCE (Momentum positif + faible risque)
-- ================================================================
SELECT 
    token_address,
    symbol,
    name,
    price_usd,
    market_cap,
    price_change_24h,
    volume_24h,
    momentum_score,
    risk_score,
    rug_risk_score,
    holder_count,
    liquidity_mc_ratio,
    snapshot_timestamp
FROM tokens_history 
WHERE snapshot_timestamp = (SELECT MAX(snapshot_timestamp) FROM tokens_history)
    AND momentum_score > 70
    AND risk_score < 30
    AND rug_risk_score < 20
    AND price_change_24h > 10
    AND volume_24h > 10000
    AND liquidity_mc_ratio > 0.1
ORDER BY momentum_score DESC, price_change_24h DESC
LIMIT 20;

-- 2. GEMS CACHÉS (Faible market cap + croissance récente + liquidité décente)
-- =========================================================================
SELECT 
    token_address,
    symbol,
    name,
    price_usd,
    market_cap,
    price_change_6h,
    price_change_24h,
    volume_24h,
    holder_count,
    holder_count_delta,
    liquidity_usd,
    viability_score
FROM tokens_history 
WHERE snapshot_timestamp = (SELECT MAX(snapshot_timestamp) FROM tokens_history)
    AND market_cap BETWEEN 10000 AND 500000  -- Micro cap
    AND price_change_6h > 5
    AND volume_24h > 5000
    AND holder_count > 50
    AND holder_count_delta > 0  -- Nouveaux holders
    AND liquidity_usd > market_cap * 0.05  -- Au moins 5% de liquidité
    --AND viability_score > 60
    AND is_rugged = 0
ORDER BY price_change_24h DESC, viability_score DESC
LIMIT 15;

-- 3. ANALYSE DE TENDANCE (Tokens avec croissance constante sur plusieurs snapshots)
-- ===============================================================================
WITH recent_snapshots AS (
    SELECT DISTINCT snapshot_timestamp 
    FROM tokens_history 
    ORDER BY snapshot_timestamp DESC 
    LIMIT 10
),
consistent_growth AS (
    SELECT 
        token_address,
        COUNT(*) as positive_snapshots,
        AVG(price_change_24h) as avg_price_change,
        AVG(volume_24h) as avg_volume,
        AVG(holder_count_delta) as avg_holder_growth,
        MIN(risk_score) as min_risk,
        MAX(momentum_score) as max_momentum
    FROM tokens_history th
    WHERE th.snapshot_timestamp IN (SELECT snapshot_timestamp FROM recent_snapshots)
        AND price_change_24h > 0
        AND volume_24h > 1000
    GROUP BY token_address
    HAVING COUNT(*) >= 7  -- Croissance dans au moins 7/10 snapshots
)
SELECT 
    cg.token_address,
    th.symbol,
    th.name,
    th.price_usd,
    th.market_cap,
    cg.avg_price_change,
    cg.avg_volume,
    cg.avg_holder_growth,
    cg.positive_snapshots,
    th.liquidity_mc_ratio,
    cg.min_risk,
    cg.max_momentum
FROM consistent_growth cg
JOIN tokens_history th ON cg.token_address = th.token_address
WHERE th.snapshot_timestamp = (SELECT MAX(snapshot_timestamp) FROM tokens_history)
    AND cg.min_risk < 40
    AND th.is_rugged = 0
ORDER BY cg.avg_price_change DESC, cg.positive_snapshots DESC
LIMIT 10;

-- 4. BREAKOUT DETECTION (Tokens qui sortent d'une phase de consolidation)
-- ======================================================================
WITH price_analysis AS (
    SELECT 
        token_address,
        price_usd,
        volume_24h,
        LAG(price_usd, 1) OVER (PARTITION BY token_address ORDER BY snapshot_timestamp) as prev_price,
        LAG(volume_24h, 1) OVER (PARTITION BY token_address ORDER BY snapshot_timestamp) as prev_volume,
        AVG(price_usd) OVER (
            PARTITION BY token_address 
            ORDER BY snapshot_timestamp 
            ROWS BETWEEN 9 PRECEDING AND 1 PRECEDING
        ) as price_avg_10,
        AVG(volume_24h) OVER (
            PARTITION BY token_address 
            ORDER BY snapshot_timestamp 
            ROWS BETWEEN 4 PRECEDING AND 1 PRECEDING
        ) as volume_avg_5,
        snapshot_timestamp
    FROM tokens_history
    WHERE snapshot_timestamp >= (
        SELECT MAX(snapshot_timestamp) - 86400 * 7  -- 7 derniers jours
        FROM tokens_history
    )
)
SELECT 
    pa.token_address,
    th.symbol,
    th.name,
    pa.price_usd,
    th.market_cap,
    ((pa.price_usd - pa.price_avg_10) / pa.price_avg_10 * 100) as breakout_percentage,
    ((pa.volume_24h - pa.volume_avg_5) / pa.volume_avg_5 * 100) as volume_surge,
    th.holder_count,
    th.liquidity_mc_ratio,
    th.risk_score,
    th.momentum_score
FROM price_analysis pa
JOIN tokens_history th ON pa.token_address = th.token_address 
    AND pa.snapshot_timestamp = th.snapshot_timestamp
WHERE pa.snapshot_timestamp = (SELECT MAX(snapshot_timestamp) FROM tokens_history)
    AND pa.price_usd > pa.price_avg_10 * 1.15  -- Prix 15% au-dessus de la moyenne
    AND pa.volume_24h > pa.volume_avg_5 * 2    -- Volume doublé
    AND th.risk_score < 50
    AND th.market_cap > 50000
    AND th.is_rugged = 0
ORDER BY breakout_percentage DESC, volume_surge DESC
LIMIT 15;

-- 5. ANALYSE DE LIQUIDITÉ & STABILITÉ (Tokens avec bonne liquidité et faible volatilité)
-- ====================================================================================
SELECT 
    token_address,
    symbol,
    name,
    price_usd,
    market_cap,
    liquidity_usd,
    liquidity_mc_ratio,
    price_volatility_1h,
    volume_mc_ratio,
    holder_count,
    top_10_holders_percentage,
    lp_providers_count,
    risk_score,
    viability_score
FROM tokens_history 
WHERE snapshot_timestamp = (SELECT MAX(snapshot_timestamp) FROM tokens_history)
    AND liquidity_mc_ratio > 0.2  -- Liquidité > 20% de la market cap
    AND price_volatility_1h < 0.05  -- Faible volatilité
    AND volume_mc_ratio > 0.1  -- Volume décent
    AND top_10_holders_percentage < 60  -- Distribution décente
    AND lp_providers_count > 5  -- Plusieurs fournisseurs de liquidité
    AND holder_count > 100
    AND market_cap > 100000
    AND risk_score < 40
    AND viability_score > 70
    AND is_rugged = 0
ORDER BY viability_score DESC, liquidity_mc_ratio DESC
LIMIT 20;

-- 6. ANALYSE DU MOMENTUM ET VOLUME (Détection de tokens en accumulation)
-- ====================================================================
SELECT 
    token_address,
    symbol,
    name,
    price_usd,
    market_cap,
    volume_24h,
    volume_24h_delta,
    price_change_24h,
    holder_count,
    holder_count_delta,
    momentum_score,
    bonding_curve_progress,
    insider_holders_count,
    risk_score
FROM tokens_history 
WHERE snapshot_timestamp = (SELECT MAX(snapshot_timestamp) FROM tokens_history)
    AND volume_24h_delta > 50  -- Volume en croissance
    AND holder_count_delta > 0  -- Nouveaux investisseurs
    AND price_change_24h BETWEEN -5 AND 15  -- Prix stable à légèrement haussier
    AND bonding_curve_progress < 90  -- Pas encore saturé
    AND insider_holders_count < 5  -- Peu d'insiders
    AND market_cap BETWEEN 50000 AND 2000000  -- Sweet spot market cap
    AND risk_score < 35
    AND momentum_score > 50
ORDER BY volume_24h_delta DESC, holder_count_delta DESC
LIMIT 15;

-- 7. TOKENS DE QUALITÉ (Critères stricts pour investissement sûr)
-- ==============================================================
SELECT 
    token_address,
    symbol,
    name,
    price_usd,
    market_cap,
    fdv,
    liquidity_usd,
    volume_24h,
    holder_count,
    top_holder_percentage,
    viability_score,
    risk_score,
    rug_risk_score,
    is_verified,
    lp_providers_count,
    price_change_24h,
    price_change_6h
FROM tokens_history 
WHERE snapshot_timestamp = (SELECT MAX(snapshot_timestamp) FROM tokens_history)
    AND viability_score > 80
    AND risk_score < 25
    AND rug_risk_score < 15
    AND holder_count > 200
    AND top_holder_percentage < 40  -- Pas de concentration excessive
    AND liquidity_usd > market_cap * 0.15  -- Liquidité > 15%
    AND lp_providers_count > 3
    AND market_cap > 200000
    AND volume_24h > market_cap * 0.05  -- Volume > 5% market cap
    AND is_rugged = 0
    AND (is_verified = 1 OR viability_score > 85)
ORDER BY viability_score DESC, market_cap ASC
LIMIT 10;

-- 8. ANALYSE COMPARATIVE (Performance relative au marché)
-- =====================================================
WITH market_stats AS (
    SELECT 
        AVG(price_change_24h) as market_avg_24h,
        AVG(volume_24h) as market_avg_volume,
        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY momentum_score) as momentum_75th
    FROM tokens_history 
    WHERE snapshot_timestamp = (SELECT MAX(snapshot_timestamp) FROM tokens_history)
        AND market_cap > 10000
        AND is_rugged = 0
)
SELECT 
    th.token_address,
    th.symbol,
    th.name,
    th.price_usd,
    th.market_cap,
    th.price_change_24h,
    th.volume_24h,
    th.momentum_score,
    (th.price_change_24h - ms.market_avg_24h) as outperformance_24h,
    (th.volume_24h / ms.market_avg_volume) as volume_ratio,
    th.holder_count,
    th.risk_score,
    th.viability_score
FROM tokens_history th
CROSS JOIN market_stats ms
WHERE th.snapshot_timestamp = (SELECT MAX(snapshot_timestamp) FROM tokens_history)
    AND th.price_change_24h > ms.market_avg_24h * 1.5  -- Surperforme le marché
    AND th.momentum_score > ms.momentum_75th  -- Top 25% momentum
    AND th.risk_score < 40
    AND th.market_cap BETWEEN 25000 AND 1000000
    AND th.is_rugged = 0
ORDER BY outperformance_24h DESC, th.momentum_score DESC
LIMIT 15;