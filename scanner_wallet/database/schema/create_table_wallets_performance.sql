CREATE TABLE IF NOT EXISTS wallets_performance (
    wallet_address TEXT PRIMARY KEY,
    
    -- Métriques d'investissement et de valeur
    total_investment_usd REAL DEFAULT 0.0,
    total_divestment_usd REAL DEFAULT 0.0,
    current_portfolio_value_usd REAL DEFAULT 0.0,
    
    -- P&L (Profit and Loss)
    realized_pnl_usd REAL DEFAULT 0.0,      -- Profits/pertes sur les ventes
    unrealized_pnl_usd REAL DEFAULT 0.0,    -- Profits/pertes latents sur les avoirs actuels
    total_pnl_usd REAL DEFAULT 0.0,         -- P&L total (réalisé + non réalisé)
    pnl_percentage REAL DEFAULT 0.0,        -- Pourcentage de P&L total par rapport à l'investissement

    -- Métriques de trading
    total_trades INTEGER DEFAULT 0,         -- Nombre total de trades (achats + ventes)
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    win_rate REAL DEFAULT 0.0,              -- Pourcentage de trades gagnants

    -- Avoirs
    current_token_holdings_count INTEGER DEFAULT 0,
    most_profitable_token TEXT,
    biggest_win_usd REAL DEFAULT 0.0,
    least_profitable_token TEXT,
    biggest_loss_usd REAL DEFAULT 0.0,

    -- Tracking
    last_calculated_at INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index pour des requêtes rapides
CREATE INDEX IF NOT EXISTS idx_wallets_perf_pnl ON wallets_performance(total_pnl_usd DESC);
CREATE INDEX IF NOT EXISTS idx_wallets_perf_win_rate ON wallets_performance(win_rate DESC);
CREATE INDEX IF NOT EXISTS idx_wallets_perf_updated ON wallets_performance(last_calculated_at DESC);
