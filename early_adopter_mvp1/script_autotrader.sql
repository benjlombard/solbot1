-- ====================================================================
-- AUTOTRADER DATABASE SCHEMA
-- SQLite Database pour le tracking des transactions et du portfolio
-- ====================================================================

-- Table principale des transactions
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    transaction_signature VARCHAR(88) UNIQUE NOT NULL,
    network VARCHAR(10) NOT NULL CHECK (network IN ('mainnet', 'devnet')),
    operation_type VARCHAR(10) NOT NULL CHECK (operation_type IN ('BUY', 'SELL', 'TRANSFER', 'AIRDROP')),
    
    -- Informations sur le token
    token_address VARCHAR(44) NOT NULL,
    token_symbol VARCHAR(20),
    token_decimals INTEGER DEFAULT 6,
    
    -- Montants de la transaction
    sol_amount_spent DECIMAL(18, 9) DEFAULT 0,     -- SOL dépensé (pour achats)
    sol_amount_received DECIMAL(18, 9) DEFAULT 0,  -- SOL reçu (pour ventes)
    token_amount DECIMAL(24, 6) NOT NULL,          -- Nombre de tokens
    price_per_token_sol DECIMAL(18, 12) NOT NULL,  -- Prix unitaire en SOL
    
    -- Données Jupiter et métadonnées
    jupiter_quote_data TEXT,                        -- JSON du quote Jupiter
    jupiter_route_label VARCHAR(50),                -- Label de la route utilisée
    price_impact_percent DECIMAL(8, 4),             -- Impact sur le prix
    
    -- Frais détaillés
    transaction_fees_sol DECIMAL(18, 9) DEFAULT 0,
    priority_fees_sol DECIMAL(18, 9) DEFAULT 0,
    account_creation_fees_sol DECIMAL(18, 9) DEFAULT 0,
    total_fees_sol DECIMAL(18, 9) DEFAULT 0,
    
    -- Execution details
    slippage_tolerance_bps INTEGER,                 -- Slippage configuré
    slippage_actual_percent DECIMAL(8, 4),          -- Slippage réel
    confirmation_time_seconds DECIMAL(8, 2),
    block_slot BIGINT,
    
    -- Status et validation
    status VARCHAR(10) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'CONFIRMED', 'FAILED', 'CANCELLED')),
    error_message TEXT,
    
    -- Audit
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index pour les requêtes fréquentes
CREATE INDEX idx_transactions_signature ON transactions(transaction_signature);
CREATE INDEX idx_transactions_token ON transactions(token_address);
CREATE INDEX idx_transactions_timestamp ON transactions(timestamp);
CREATE INDEX idx_transactions_network ON transactions(network);
CREATE INDEX idx_transactions_status ON transactions(status);

-- Table des positions actuelles
CREATE TABLE current_positions (
    token_address VARCHAR(44) PRIMARY KEY,
    token_symbol VARCHAR(20) NOT NULL,
    network VARCHAR(10) NOT NULL CHECK (network IN ('mainnet', 'devnet')),
    
    -- Holdings
    total_tokens_held DECIMAL(24, 6) NOT NULL DEFAULT 0,
    average_entry_price_sol DECIMAL(18, 12) NOT NULL,
    total_sol_invested DECIMAL(18, 9) NOT NULL,
    
    -- Timestamps
    first_purchase_timestamp DATETIME NOT NULL,
    last_transaction_timestamp DATETIME NOT NULL,
    last_price_update DATETIME,
    
    -- PnL (mis à jour par le portfolio tracker)
    current_price_sol DECIMAL(18, 12),
    current_value_sol DECIMAL(18, 9),
    unrealized_pnl_sol DECIMAL(18, 9),
    unrealized_pnl_percent DECIMAL(8, 4),
    
    -- Statistiques
    total_transactions INTEGER DEFAULT 1,
    total_fees_paid_sol DECIMAL(18, 9) DEFAULT 0,
    
    -- Audit
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index pour current_positions
CREATE INDEX idx_positions_network ON current_positions(network);
CREATE INDEX idx_positions_symbol ON current_positions(token_symbol);

-- Table de l'historique des prix
CREATE TABLE price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_address VARCHAR(44) NOT NULL,
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    -- Prix et données de marché
    price_sol DECIMAL(18, 12) NOT NULL,
    price_usd DECIMAL(18, 8),
    market_cap_usd DECIMAL(18, 2),
    volume_24h_usd DECIMAL(18, 2),
    
    -- Source des données
    source VARCHAR(20) DEFAULT 'jupiter' CHECK (source IN ('jupiter', 'coingecko', 'dexscreener', 'birdeye')),
    network VARCHAR(10) NOT NULL CHECK (network IN ('mainnet', 'devnet')),
    
    -- Métadonnées supplémentaires
    holders_count INTEGER,
    liquidity_usd DECIMAL(18, 2),
    
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index pour price_history
CREATE INDEX idx_price_history_token_time ON price_history(token_address, timestamp);
CREATE INDEX idx_price_history_timestamp ON price_history(timestamp);
CREATE INDEX idx_price_history_source ON price_history(source);

-- Table des statistiques quotidiennes
CREATE TABLE daily_stats (
    date DATE PRIMARY KEY,
    network VARCHAR(10) NOT NULL CHECK (network IN ('mainnet', 'devnet')),
    
    -- Trading stats
    total_trades INTEGER DEFAULT 0,
    buy_trades INTEGER DEFAULT 0,
    sell_trades INTEGER DEFAULT 0,
    
    -- Montants
    total_sol_spent DECIMAL(18, 9) DEFAULT 0,
    total_sol_received DECIMAL(18, 9) DEFAULT 0,
    total_fees_paid DECIMAL(18, 9) DEFAULT 0,
    net_sol_flow DECIMAL(18, 9) DEFAULT 0,  -- spent - received
    
    -- PnL
    realized_pnl_sol DECIMAL(18, 9) DEFAULT 0,
    unrealized_pnl_sol DECIMAL(18, 9) DEFAULT 0,
    total_pnl_sol DECIMAL(18, 9) DEFAULT 0,
    
    -- Portfolio value
    portfolio_value_start_sol DECIMAL(18, 9),
    portfolio_value_end_sol DECIMAL(18, 9),
    portfolio_change_percent DECIMAL(8, 4),
    
    -- Best/Worst performers
    best_performing_token VARCHAR(44),
    best_performance_percent DECIMAL(8, 4),
    worst_performing_token VARCHAR(44),
    worst_performance_percent DECIMAL(8, 4),
    
    -- Execution stats
    avg_confirmation_time_seconds DECIMAL(8, 2),
    failed_transactions INTEGER DEFAULT 0,
    success_rate_percent DECIMAL(5, 2),
    
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index pour daily_stats
CREATE INDEX idx_daily_stats_network ON daily_stats(network);
CREATE INDEX idx_daily_stats_date ON daily_stats(date);

-- Table des alertes et notifications
CREATE TABLE alerts_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    alert_type VARCHAR(20) NOT NULL CHECK (alert_type IN ('PNL_THRESHOLD', 'DAILY_LOSS', 'LOW_BALANCE', 'TRADE_EXECUTED', 'ERROR', 'SYSTEM')),
    severity VARCHAR(10) NOT NULL CHECK (severity IN ('INFO', 'WARNING', 'ERROR', 'CRITICAL')),
    
    -- Context
    token_address VARCHAR(44),
    network VARCHAR(10) CHECK (network IN ('mainnet', 'devnet')),
    
    -- Message
    title VARCHAR(100) NOT NULL,
    message TEXT NOT NULL,
    
    -- Notification status
    discord_sent BOOLEAN DEFAULT FALSE,
    telegram_sent BOOLEAN DEFAULT FALSE,
    
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Index pour alerts_log
CREATE INDEX idx_alerts_timestamp ON alerts_log(timestamp);
CREATE INDEX idx_alerts_type ON alerts_log(alert_type);
CREATE INDEX idx_alerts_severity ON alerts_log(severity);

-- ====================================================================
-- TRIGGERS pour maintenir la cohérence des données
-- ====================================================================

-- Trigger pour mettre à jour updated_at automatiquement
CREATE TRIGGER update_transactions_timestamp 
    AFTER UPDATE ON transactions
    FOR EACH ROW
BEGIN
    UPDATE transactions SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER update_positions_timestamp 
    AFTER UPDATE ON current_positions
    FOR EACH ROW
BEGIN
    UPDATE current_positions SET updated_at = CURRENT_TIMESTAMP WHERE token_address = NEW.token_address;
END;

CREATE TRIGGER update_daily_stats_timestamp 
    AFTER UPDATE ON daily_stats
    FOR EACH ROW
BEGIN
    UPDATE daily_stats SET updated_at = CURRENT_TIMESTAMP WHERE date = NEW.date;
END;

-- ====================================================================
-- VIEWS utiles pour les requêtes fréquentes
-- ====================================================================

-- Vue pour le portfolio actuel avec PnL
CREATE VIEW portfolio_summary AS
SELECT 
    p.token_address,
    p.token_symbol,
    p.network,
    p.total_tokens_held,
    p.average_entry_price_sol,
    p.total_sol_invested,
    p.current_price_sol,
    p.current_value_sol,
    p.unrealized_pnl_sol,
    p.unrealized_pnl_percent,
    p.total_transactions,
    p.total_fees_paid_sol,
    p.first_purchase_timestamp,
    p.last_transaction_timestamp,
    -- Calculer l'âge de la position
    CAST((julianday('now') - julianday(p.first_purchase_timestamp)) * 24 * 60 AS INTEGER) as age_minutes,
    -- ROI total incluant les frais
    ROUND(((p.current_value_sol - p.total_sol_invested - p.total_fees_paid_sol) / (p.total_sol_invested + p.total_fees_paid_sol)) * 100, 2) as roi_percent
FROM current_positions p
WHERE p.total_tokens_held > 0
ORDER BY p.unrealized_pnl_percent DESC;

-- Vue pour les transactions récentes avec détails
CREATE VIEW recent_transactions AS
SELECT 
    t.timestamp,
    t.transaction_signature,
    t.network,
    t.operation_type,
    t.token_symbol,
    t.token_amount,
    t.price_per_token_sol,
    CASE 
        WHEN t.operation_type = 'BUY' THEN t.sol_amount_spent
        WHEN t.operation_type = 'SELL' THEN t.sol_amount_received
        ELSE 0
    END as sol_amount,
    t.total_fees_sol,
    t.slippage_actual_percent,
    t.confirmation_time_seconds,
    t.status
FROM transactions t
WHERE t.status = 'CONFIRMED'
ORDER BY t.timestamp DESC
LIMIT 50;

-- Vue pour les statistiques globales
CREATE VIEW global_stats AS
SELECT 
    network,
    COUNT(*) as total_transactions,
    SUM(CASE WHEN operation_type = 'BUY' THEN 1 ELSE 0 END) as total_buys,
    SUM(CASE WHEN operation_type = 'SELL' THEN 1 ELSE 0 END) as total_sells,
    SUM(sol_amount_spent) as total_sol_spent,
    SUM(sol_amount_received) as total_sol_received,
    SUM(total_fees_sol) as total_fees_paid,
    AVG(confirmation_time_seconds) as avg_confirmation_time,
    COUNT(DISTINCT token_address) as unique_tokens_traded
FROM transactions 
WHERE status = 'CONFIRMED'
GROUP BY network;

-- ====================================================================
-- DONNÉES D'EXEMPLE (optionnel, pour les tests)
-- ====================================================================

-- Insérer quelques données de test (commenté par défaut)
/*
INSERT INTO transactions (
    transaction_signature, network, operation_type, token_address, token_symbol,
    sol_amount_spent, token_amount, price_per_token_sol, status
) VALUES 
    ('test_sig_1', 'devnet', 'BUY', 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v', 'USDC', 0.001, 1000, 0.000001, 'CONFIRMED'),
    ('test_sig_2', 'devnet', 'BUY', 'So11111111111111111111111111111111111111112', 'WSOL', 0.005, 5000, 0.000001, 'CONFIRMED');
*/