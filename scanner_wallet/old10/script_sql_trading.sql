-- =============================================================================
-- SCHÉMA BASE DE DONNÉES POUR LE TRADING AVEC PHANTOM WALLET
-- Extension du schéma existant pour supporter les fonctionnalités de trading
-- =============================================================================

-- Table des paramètres de trading par wallet
CREATE TABLE IF NOT EXISTS trading_settings (
    wallet_address TEXT PRIMARY KEY,
    default_slippage REAL DEFAULT 0.5,
    max_trade_amount_sol REAL DEFAULT 10.0,
    max_daily_volume_sol REAL DEFAULT 100.0,
    auto_approve_under_sol REAL DEFAULT 1.0,
    preferred_dex TEXT DEFAULT 'jupiter',
    enable_mev_protection BOOLEAN DEFAULT 1,
    priority_fee_lamports INTEGER DEFAULT 5000,
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    updated_at INTEGER DEFAULT (strftime('%s', 'now'))
);

-- Table des ordres de trade
CREATE TABLE IF NOT EXISTS trade_orders (
    order_id TEXT PRIMARY KEY,
    wallet_address TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    token_symbol TEXT,
    trade_type TEXT NOT NULL, -- 'buy', 'sell', 'swap'
    amount_sol REAL NOT NULL,
    amount_tokens REAL NOT NULL,
    slippage REAL NOT NULL,
    quote_id TEXT,
    dex TEXT DEFAULT 'jupiter',
    status TEXT DEFAULT 'pending', -- 'pending', 'confirmed', 'failed', 'cancelled', 'timeout'
    
    -- Données d'exécution
    transaction_signature TEXT,
    actual_amount_received REAL,
    actual_price REAL,
    gas_used REAL,
    
    -- Timestamps
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    submitted_at INTEGER,
    confirmed_at INTEGER,
    
    -- Métadonnées
    priority_fee INTEGER DEFAULT 5000,
    notes TEXT,
    
    FOREIGN KEY (wallet_address) REFERENCES wallet_priorities(wallet_address)
);

-- Table des portfolios de trading
CREATE TABLE IF NOT EXISTS trading_portfolios (
    wallet_address TEXT PRIMARY KEY,
    total_trades INTEGER DEFAULT 0,
    successful_trades INTEGER DEFAULT 0,
    failed_trades INTEGER DEFAULT 0,
    total_volume_sol REAL DEFAULT 0.0,
    total_fees_paid REAL DEFAULT 0.0,
    total_pnl_sol REAL DEFAULT 0.0,
    avg_trade_size_sol REAL DEFAULT 0.0,
    largest_trade_sol REAL DEFAULT 0.0,
    best_trade_pnl REAL DEFAULT 0.0,
    worst_trade_pnl REAL DEFAULT 0.0,
    favorite_tokens TEXT DEFAULT '[]', -- JSON array des tokens favoris
    preferred_dex TEXT DEFAULT 'jupiter',
    risk_score REAL DEFAULT 1.0,
    updated_at INTEGER DEFAULT (strftime('%s', 'now')),
    
    FOREIGN KEY (wallet_address) REFERENCES wallet_priorities(wallet_address)
);

-- Table des données de marché (cache)
CREATE TABLE IF NOT EXISTS market_data (
    token_mint TEXT PRIMARY KEY,
    price_usd REAL DEFAULT 0.0,
    price_sol REAL DEFAULT 0.0,
    volume_24h_usd REAL DEFAULT 0.0,
    market_cap_usd REAL,
    liquidity_usd REAL,
    price_change_24h REAL DEFAULT 0.0,
    price_change_1h REAL DEFAULT 0.0,
    fdv REAL, -- Fully Diluted Valuation
    source TEXT DEFAULT 'jupiter',
    updated_at INTEGER DEFAULT (strftime('%s', 'now'))
);

-- Table des quotes de trading (cache temporaire)
CREATE TABLE IF NOT EXISTS trade_quotes (
    quote_id TEXT PRIMARY KEY,
    token_mint TEXT NOT NULL,
    token_symbol TEXT,
    trade_type TEXT NOT NULL,
    amount_in REAL NOT NULL,
    amount_out REAL NOT NULL,
    amount_in_decimals INTEGER DEFAULT 9,
    amount_out_decimals INTEGER DEFAULT 9,
    price_impact REAL DEFAULT 0.0,
    slippage REAL NOT NULL,
    minimum_received REAL,
    dex TEXT DEFAULT 'jupiter',
    route TEXT DEFAULT '[]', -- JSON array de la route
    fee_bps INTEGER DEFAULT 25,
    estimated_fee_sol REAL,
    expires_at INTEGER NOT NULL,
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    used BOOLEAN DEFAULT 0
);

-- Table des limites de trading quotidiennes
CREATE TABLE IF NOT EXISTS daily_trading_limits (
    wallet_address TEXT NOT NULL,
    trading_date TEXT NOT NULL, -- Format YYYY-MM-DD
    volume_traded_sol REAL DEFAULT 0.0,
    trades_count INTEGER DEFAULT 0,
    last_trade_time INTEGER,
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    
    PRIMARY KEY (wallet_address, trading_date),
    FOREIGN KEY (wallet_address) REFERENCES wallet_priorities(wallet_address)
);

-- Table des alertes de trading
CREATE TABLE IF NOT EXISTS trading_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address TEXT NOT NULL,
    alert_type TEXT NOT NULL, -- 'large_trade', 'profit_target', 'stop_loss', 'volume_limit'
    token_mint TEXT,
    threshold_value REAL,
    current_value REAL,
    triggered_at INTEGER,
    resolved_at INTEGER,
    status TEXT DEFAULT 'active', -- 'active', 'triggered', 'resolved', 'disabled'
    message TEXT,
    created_at INTEGER DEFAULT (strftime('%s', 'now')),
    
    FOREIGN KEY (wallet_address) REFERENCES wallet_priorities(wallet_address)
);

-- Table des performances de trading par token
CREATE TABLE IF NOT EXISTS token_trading_performance (
    wallet_address TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    total_trades INTEGER DEFAULT 0,
    total_bought REAL DEFAULT 0.0,
    total_sold REAL DEFAULT 0.0,
    avg_buy_price REAL DEFAULT 0.0,
    avg_sell_price REAL DEFAULT 0.0,
    realized_pnl_sol REAL DEFAULT 0.0,
    unrealized_pnl_sol REAL DEFAULT 0.0,
    first_trade_at INTEGER,
    last_trade_at INTEGER,
    best_trade_pnl REAL DEFAULT 0.0,
    worst_trade_pnl REAL DEFAULT 0.0,
    win_rate REAL DEFAULT 0.0,
    updated_at INTEGER DEFAULT (strftime('%s', 'now')),
    
    PRIMARY KEY (wallet_address, token_mint),
    FOREIGN KEY (wallet_address) REFERENCES wallet_priorities(wallet_address)
);

-- =============================================================================
-- INDEX POUR OPTIMISER LES PERFORMANCES
-- =============================================================================

-- Index sur les ordres de trade
CREATE INDEX IF NOT EXISTS idx_trade_orders_wallet_time ON trade_orders(wallet_address, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trade_orders_status ON trade_orders(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trade_orders_token ON trade_orders(token_mint, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trade_orders_signature ON trade_orders(transaction_signature);

-- Index sur les portfolios
CREATE INDEX IF NOT EXISTS idx_trading_portfolios_volume ON trading_portfolios(total_volume_sol DESC);
CREATE INDEX IF NOT EXISTS idx_trading_portfolios_risk ON trading_portfolios(risk_score DESC);
CREATE INDEX IF NOT EXISTS idx_trading_portfolios_pnl ON trading_portfolios(total_pnl_sol DESC);

-- Index sur les données de marché
CREATE INDEX IF NOT EXISTS idx_market_data_updated ON market_data(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_market_data_price ON market_data(price_usd DESC) WHERE price_usd > 0;
CREATE INDEX IF NOT EXISTS idx_market_data_volume ON market_data(volume_24h_usd DESC);

-- Index sur les quotes
CREATE INDEX IF NOT EXISTS idx_trade_quotes_expires ON trade_quotes(expires_at ASC);
CREATE INDEX IF NOT EXISTS idx_trade_quotes_token ON trade_quotes(token_mint, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trade_quotes_unused ON trade_quotes(used, expires_at) WHERE used = 0;

-- Index sur les limites quotidiennes
CREATE INDEX IF NOT EXISTS idx_daily_limits_date ON daily_trading_limits(trading_date DESC);
CREATE INDEX IF NOT EXISTS idx_daily_limits_volume ON daily_trading_limits(volume_traded_sol DESC);

-- Index sur les alertes
CREATE INDEX IF NOT EXISTS idx_trading_alerts_wallet ON trading_alerts(wallet_address, status);
CREATE INDEX IF NOT EXISTS idx_trading_alerts_triggered ON trading_alerts(triggered_at DESC) WHERE triggered_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_trading_alerts_type ON trading_alerts(alert_type, status);

-- Index sur les performances par token
CREATE INDEX IF NOT EXISTS idx_token_performance_pnl ON token_trading_performance(realized_pnl_sol DESC);
CREATE INDEX IF NOT EXISTS idx_token_performance_trades ON token_trading_performance(total_trades DESC);
CREATE INDEX IF NOT EXISTS idx_token_performance_win_rate ON token_trading_performance(win_rate DESC);

-- =============================================================================
-- TRIGGERS POUR MAINTENIR LA COHÉRENCE DES DONNÉES
-- =============================================================================

-- Trigger pour mettre à jour le timestamp des paramètres de trading
CREATE TRIGGER IF NOT EXISTS update_trading_settings_timestamp
    AFTER UPDATE ON trading_settings
    FOR EACH ROW
BEGIN
    UPDATE trading_settings 
    SET updated_at = strftime('%s', 'now') 
    WHERE wallet_address = NEW.wallet_address;
END;

-- Trigger pour mettre à jour les portfolios lors d'un nouvel ordre confirmé
CREATE TRIGGER IF NOT EXISTS update_portfolio_on_trade
    AFTER UPDATE OF status ON trade_orders
    FOR EACH ROW
    WHEN NEW.status = 'confirmed' AND OLD.status != 'confirmed'
BEGIN
    -- Mettre à jour le portfolio
    INSERT OR REPLACE INTO trading_portfolios (
        wallet_address, total_trades, successful_trades, total_volume_sol, updated_at
    )
    SELECT 
        NEW.wallet_address,
        COALESCE((SELECT total_trades FROM trading_portfolios WHERE wallet_address = NEW.wallet_address), 0) + 1,
        COALESCE((SELECT successful_trades FROM trading_portfolios WHERE wallet_address = NEW.wallet_address), 0) + 1,
        COALESCE((SELECT total_volume_sol FROM trading_portfolios WHERE wallet_address = NEW.wallet_address), 0) + NEW.amount_sol,
        strftime('%s', 'now');
    
    -- Mettre à jour les limites quotidiennes
    INSERT OR REPLACE INTO daily_trading_limits (
        wallet_address, trading_date, volume_traded_sol, trades_count, last_trade_time
    )
    SELECT 
        NEW.wallet_address,
        date('now'),
        COALESCE((SELECT volume_traded_sol FROM daily_trading_limits 
                 WHERE wallet_address = NEW.wallet_address AND trading_date = date('now')), 0) + NEW.amount_sol,
        COALESCE((SELECT trades_count FROM daily_trading_limits 
                 WHERE wallet_address = NEW.wallet_address AND trading_date = date('now')), 0) + 1,
        strftime('%s', 'now');
    
    -- Mettre à jour les performances par token
    INSERT OR REPLACE INTO token_trading_performance (
        wallet_address, token_mint, total_trades, 
        total_bought, total_sold, first_trade_at, last_trade_at, updated_at
    )
    SELECT 
        NEW.wallet_address,
        NEW.token_mint,
        COALESCE((SELECT total_trades FROM token_trading_performance 
                 WHERE wallet_address = NEW.wallet_address AND token_mint = NEW.token_mint), 0) + 1,
        CASE 
            WHEN NEW.trade_type = 'buy' THEN 
                COALESCE((SELECT total_bought FROM token_trading_performance 
                         WHERE wallet_address = NEW.wallet_address AND token_mint = NEW.token_mint), 0) + NEW.amount_tokens
            ELSE 
                COALESCE((SELECT total_bought FROM token_trading_performance 
                         WHERE wallet_address = NEW.wallet_address AND token_mint = NEW.token_mint), 0)
        END,
        CASE 
            WHEN NEW.trade_type = 'sell' THEN 
                COALESCE((SELECT total_sold FROM token_trading_performance 
                         WHERE wallet_address = NEW.wallet_address AND token_mint = NEW.token_mint), 0) + NEW.amount_tokens
            ELSE 
                COALESCE((SELECT total_sold FROM token_trading_performance 
                         WHERE wallet_address = NEW.wallet_address AND token_mint = NEW.token_mint), 0)
        END,
        COALESCE((SELECT first_trade_at FROM token_trading_performance 
                 WHERE wallet_address = NEW.wallet_address AND token_mint = NEW.token_mint), NEW.confirmed_at),
        NEW.confirmed_at,
        strftime('%s', 'now');
END;

-- Trigger pour nettoyer les quotes expirées
CREATE TRIGGER IF NOT EXISTS cleanup_expired_quotes
    AFTER INSERT ON trade_quotes
    FOR EACH ROW
BEGIN
    DELETE FROM trade_quotes 
    WHERE expires_at < strftime('%s', 'now') - 3600; -- Supprimer les quotes expirées depuis plus d'1h
END;

-- Trigger pour marquer les quotes comme utilisées
CREATE TRIGGER IF NOT EXISTS mark_quote_used
    AFTER INSERT ON trade_orders
    FOR EACH ROW
    WHEN NEW.quote_id IS NOT NULL
BEGIN
    UPDATE trade_quotes 
    SET used = 1 
    WHERE quote_id = NEW.quote_id;
END;

-- =============================================================================
-- VUES POUR FACILITER LES REQUÊTES
-- =============================================================================

-- Vue des trades récents avec métadonnées
CREATE VIEW IF NOT EXISTS recent_trades AS
SELECT 
    to.*,
    tp.wallet_address as portfolio_wallet,
    tp.total_trades as wallet_total_trades,
    tp.total_pnl_sol as wallet_total_pnl,
    md.price_usd as current_token_price,
    md.price_change_24h as token_price_change_24h,
    ts.preferred_dex as wallet_preferred_dex,
    ts.default_slippage as wallet_default_slippage
FROM trade_orders to
LEFT JOIN trading_portfolios tp ON to.wallet_address = tp.wallet_address
LEFT JOIN market_data md ON to.token_mint = md.token_mint
LEFT JOIN trading_settings ts ON to.wallet_address = ts.wallet_address
WHERE to.created_at > strftime('%s', 'now') - 86400 -- Dernières 24h
ORDER BY to.created_at DESC;

-- Vue des performances agrégées par wallet
CREATE VIEW IF NOT EXISTS wallet_trading_summary AS
SELECT 
    tp.wallet_address,
    tp.total_trades,
    tp.successful_trades,
    tp.failed_trades,
    ROUND(tp.successful_trades * 100.0 / NULLIF(tp.total_trades, 0), 2) as success_rate_pct,
    tp.total_volume_sol,
    tp.total_pnl_sol,
    tp.avg_trade_size_sol,
    tp.risk_score,
    COUNT(DISTINCT ttp.token_mint) as tokens_traded,
    ts.preferred_dex,
    ts.default_slippage,
    dtl.volume_traded_sol as today_volume,
    dtl.trades_count as today_trades
FROM trading_portfolios tp
LEFT JOIN trading_settings ts ON tp.wallet_address = ts.wallet_address
LEFT JOIN token_trading_performance ttp ON tp.wallet_address = ttp.wallet_address
LEFT JOIN daily_trading_limits dtl ON tp.wallet_address = dtl.wallet_address 
    AND dtl.trading_date = date('now')
GROUP BY tp.wallet_address;

-- Vue des top tokens par performance
CREATE VIEW IF NOT EXISTS top_trading_tokens AS
SELECT 
    ttp.token_mint,
    COUNT(DISTINCT ttp.wallet_address) as unique_traders,
    SUM(ttp.total_trades) as total_trades,
    SUM(ttp.realized_pnl_sol) as total_pnl_sol,
    AVG(ttp.win_rate) as avg_win_rate,
    md.price_usd as current_price,
    md.volume_24h_usd as volume_24h,
    md.price_change_24h
FROM token_trading_performance ttp
LEFT JOIN market_data md ON ttp.token_mint = md.token_mint
WHERE ttp.total_trades > 0
GROUP BY ttp.token_mint
ORDER BY total_trades DESC, total_pnl_sol DESC;

-- Vue des alertes actives
CREATE VIEW IF NOT EXISTS active_trading_alerts AS
SELECT 
    ta.*,
    tp.total_pnl_sol as wallet_pnl,
    tp.total_volume_sol as wallet_volume,
    md.price_usd as current_token_price
FROM trading_alerts ta
LEFT JOIN trading_portfolios tp ON ta.wallet_address = tp.wallet_address
LEFT JOIN market_data md ON ta.token_mint = md.token_mint
WHERE ta.status = 'active'
ORDER BY ta.created_at DESC;

-- =============================================================================
-- FONCTIONS ET PROCÉDURES STOCKÉES (SQLite equivalents)
-- =============================================================================

-- Vue pour calculer les statistiques de trading en temps réel
CREATE VIEW IF NOT EXISTS trading_stats_realtime AS
SELECT 
    COUNT(*) as total_orders,
    COUNT(CASE WHEN status = 'confirmed' THEN 1 END) as successful_orders,
    COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed_orders,
    COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending_orders,
    ROUND(COUNT(CASE WHEN status = 'confirmed' THEN 1 END) * 100.0 / COUNT(*), 2) as success_rate,
    SUM(CASE WHEN status = 'confirmed' THEN amount_sol ELSE 0 END) as total_volume_sol,
    AVG(CASE WHEN status = 'confirmed' THEN amount_sol ELSE NULL END) as avg_trade_size_sol,
    COUNT(DISTINCT wallet_address) as unique_traders,
    COUNT(DISTINCT token_mint) as unique_tokens_traded,
    MIN(created_at) as first_trade_time,
    MAX(created_at) as last_trade_time
FROM trade_orders
WHERE created_at > strftime('%s', 'now') - 86400; -- Dernières 24h

-- =============================================================================
-- DONNÉES DE RÉFÉRENCE
-- =============================================================================

-- Insertion des DEX supportés
INSERT OR IGNORE INTO system_config (key, value, description) VALUES 
('supported_dex', '["jupiter", "raydium", "orca", "serum"]', 'Liste des DEX supportés pour le trading'),
('default_slippage', '0.5', 'Slippage par défaut en pourcentage'),
('max_trade_amount_sol', '100.0', 'Montant maximum par trade en SOL'),
('trading_enabled', 'true', 'Trading activé globalement'),
('maintenance_mode', 'false', 'Mode maintenance pour le trading');

-- Insertion des types d'alertes supportés
INSERT OR IGNORE INTO system_config (key, value, description) VALUES 
('alert_types', '["large_trade", "profit_target", "stop_loss", "volume_limit", "price_change"]', 'Types d''alertes de trading supportés'),
('default_alert_thresholds', '{"large_trade": 10.0, "profit_target": 50.0, "stop_loss": -20.0, "volume_limit": 100.0}', 'Seuils d''alerte par défaut');

-- =============================================================================
-- REQUÊTES D'EXEMPLE POUR LES RAPPORTS
-- =============================================================================

/*
-- Rapport de performance quotidien
SELECT 
    date(created_at, 'unixepoch') as trade_date,
    COUNT(*) as total_trades,
    COUNT(CASE WHEN status = 'confirmed' THEN 1 END) as successful_trades,
    SUM(CASE WHEN status = 'confirmed' THEN amount_sol ELSE 0 END) as volume_sol,
    COUNT(DISTINCT wallet_address) as active_traders
FROM trade_orders 
WHERE created_at > strftime('%s', 'now') - 7*86400 
GROUP BY date(created_at, 'unixepoch')
ORDER BY trade_date DESC;

-- Top traders par volume
SELECT 
    wallet_address,
    total_volume_sol,
    total_trades,
    ROUND(total_pnl_sol, 4) as pnl_sol,
    ROUND(total_pnl_sol / NULLIF(total_volume_sol, 0) * 100, 2) as roi_pct,
    risk_score
FROM trading_portfolios 
WHERE total_trades > 5
ORDER BY total_volume_sol DESC 
LIMIT 20;

-- Tokens les plus tradés aujourd'hui
SELECT 
    to.token_mint,
    to.token_symbol,
    COUNT(*) as trades_today,
    COUNT(DISTINCT to.wallet_address) as unique_traders,
    SUM(to.amount_sol) as volume_sol_today,
    md.price_usd,
    md.price_change_24h
FROM trade_orders to
LEFT JOIN market_data md ON to.token_mint = md.token_mint
WHERE to.created_at > strftime('%s', 'now') - 86400
  AND to.status = 'confirmed'
GROUP BY to.token_mint, to.token_symbol
ORDER BY trades_today DESC, volume_sol_today DESC
LIMIT 15;
*/