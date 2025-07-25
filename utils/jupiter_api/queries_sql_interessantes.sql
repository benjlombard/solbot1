-- 🚨 TOP GEMS: Tokens avec score élevé découverts récemment
SELECT 
    symbol, 
    address,
    invest_score,
    price_usdc,
    market_cap,
    volume_24h,
    liquidity_usd,
    holders,
    rug_score,
    age_hours,
    bonding_curve_status,
    first_discovered_at
FROM tokens 
WHERE invest_score >= 60 
    AND first_discovered_at > datetime('now', '-24 hours')
    AND is_tradeable = 1
ORDER BY invest_score DESC, first_discovered_at DESC
LIMIT 20;

-- 🔥 EARLY STAGE GEMS: Tokens très récents (< 6h) avec bon potentiel
SELECT 
    symbol,
    address,
    invest_score,
    price_usdc,
    volume_24h,
    holders,
    rug_score,
    age_hours,
    bonding_curve_status,
    'https://dexscreener.com/solana/' || address AS dexscreener_link,
    'https://pump.fun/coin/' || address AS pumpfun_link
FROM tokens 
WHERE age_hours <= 6 
    AND invest_score >= 60
    AND is_tradeable = 1
    AND rug_score >= 50  -- Sécurité minimale
ORDER BY invest_score DESC, age_hours ASC
LIMIT 15;

-- 💎 MOMENTUM TOKENS: Tokens avec forte croissance de volume
SELECT 
    symbol,
    address,
    invest_score,
    price_usdc,
    volume_24h,
    price_change_24h,
    holders,
    liquidity_usd,
    bonding_curve_status,
    first_discovered_at
FROM tokens 
WHERE volume_24h > 50000  -- Volume significatif
    AND price_change_24h > 20  -- Hausse de +20%
    AND first_discovered_at > datetime('now', '-12 hours')
    AND is_tradeable = 1
ORDER BY volume_24h DESC, price_change_24h DESC
LIMIT 10;

-- 🚀 PUMP.FUN GRADUATION: Tokens ayant complété la bonding curve
SELECT 
    symbol,
    address,
    invest_score,
    price_usdc,
    market_cap,
    volume_24h,
    holders,
    rug_score,
    bonding_curve_status,
    raydium_pool_address,
    first_discovered_at
FROM tokens 
WHERE bonding_curve_status IN ('completed', 'migrated')
    AND first_discovered_at > datetime('now', '-48 hours')
    AND invest_score >= 50
ORDER BY invest_score DESC, market_cap DESC
LIMIT 15;

-- 🔍 UNDERVALUED GEMS: Faible market cap mais bon score
SELECT 
    symbol,
    address,
    invest_score,
    price_usdc,
    market_cap,
    volume_24h,
    holders,
    rug_score,
    liquidity_usd,
    first_discovered_at
FROM tokens 
WHERE market_cap > 0 
    AND market_cap < 1000000  -- Market cap < 1M USD
    AND invest_score >= 65
    AND volume_24h > 10000
    AND is_tradeable = 1
    AND first_discovered_at > datetime('now', '-24 hours')
ORDER BY invest_score DESC, volume_24h DESC
LIMIT 12;

-- 👥 GROWING COMMUNITY: Tokens avec croissance rapide de holders
SELECT 
    symbol,
    address,
    invest_score,
    price_usdc,
    holders,
    volume_24h,
    rug_score,
    age_hours,
    bonding_curve_status,
    first_discovered_at
FROM tokens 
WHERE holders >= 10  -- Au moins 100 holders
    AND age_hours <= 24  -- Récent
    AND invest_score >= 55
    AND is_tradeable = 1
ORDER BY holders DESC, invest_score DESC
LIMIT 10;

-- ⚡ FLASH OPPORTUNITIES: Tokens très récents avec activité
SELECT 
    symbol,
    address,
    invest_score,
    price_usdc,
    volume_24h,
    holders,
    age_hours,
    rug_score,
    bonding_curve_status,
    first_discovered_at
FROM tokens 
WHERE first_discovered_at > datetime('now', '-2 hours')  -- Découverts dans les 2 dernières heures
    AND (volume_24h > 5000 OR holders > 50)  -- Activité minimale
    AND rug_score >= 40  -- Sécurité de base
    AND is_tradeable = 1
ORDER BY first_discovered_at DESC, invest_score DESC
LIMIT 8;

-- 🏆 BEST RISK/REWARD: Score élevé avec sécurité
SELECT 
    symbol,
    address,
    invest_score,
    rug_score,
    price_usdc,
    market_cap,
    volume_24h,
    holders,
    liquidity_usd,
    age_hours,
    bonding_curve_status,
    ROUND((invest_score * rug_score) / 100, 2) as risk_adjusted_score,
    first_discovered_at
FROM tokens 
WHERE invest_score >= 60
    AND rug_score >= 60  -- Sécurité importante
    AND is_tradeable = 1
    AND first_discovered_at > datetime('now', '-24 hours')
ORDER BY risk_adjusted_score DESC, liquidity_usd DESC
LIMIT 15;

-- 📊 ANALYTICS: Vue d'ensemble des performances récentes
SELECT 
    COUNT(*) as total_tokens,
    COUNT(CASE WHEN invest_score >= 80 THEN 1 END) as high_score_count,
    COUNT(CASE WHEN bonding_curve_status = 'completed' THEN 1 END) as graduated_count,
    COUNT(CASE WHEN volume_24h > 50000 THEN 1 END) as high_volume_count,
    AVG(invest_score) as avg_score,
    AVG(rug_score) as avg_security,
    MAX(volume_24h) as max_volume,
    MAX(holders) as max_holders,
    MAX(age_hours) as max_age_hours,
    MIN(age_hours) as min_age_hours,
    AVG(age_hours) as avg_age_hours
FROM tokens 
WHERE first_discovered_at > datetime('now', '-24 hours')
    AND is_tradeable = 1;

-- 🎯 CUSTOM ALERTS: Tokens méritant attention immédiate
SELECT 
    symbol,
    address,
    invest_score,
    price_usdc,
    volume_24h,
    price_change_24h,
    holders,
    rug_score,
    age_hours,
    bonding_curve_status,
    CASE 
        WHEN invest_score >= 90 THEN '🔥 MUST WATCH'
        WHEN invest_score >= 80 THEN '⭐ HIGH POTENTIAL'
        WHEN volume_24h > 100000 THEN '📈 HIGH VOLUME'
        WHEN holders > 500 AND age_hours < 12 THEN '👥 VIRAL POTENTIAL'
        WHEN bonding_curve_status = 'completed' THEN '🚀 GRADUATED'
        ELSE '📊 MONITOR'
    END as alert_type,
    'https://dexscreener.com/solana/' || address AS dex_link
FROM tokens 
WHERE first_discovered_at > datetime('now', '-6 hours')
    AND is_tradeable = 1
    AND (
        invest_score >= 70 
        OR volume_24h > 75000 
        OR (holders > 300 AND age_hours < 12)
        OR bonding_curve_status IN ('completed', 'migrated')
    )
ORDER BY 
    CASE 
        WHEN invest_score >= 90 THEN 1
        WHEN invest_score >= 80 THEN 2
        WHEN volume_24h > 100000 THEN 3
        WHEN bonding_curve_status = 'completed' THEN 4
        ELSE 5
    END,
    invest_score DESC
LIMIT 20;