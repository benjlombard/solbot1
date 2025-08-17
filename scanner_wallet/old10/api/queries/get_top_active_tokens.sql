-- Queries for the main dashboard in Solana Wallet Monitor
-- File: get_top_active_tokens.sql
-- Description: Fetches the most active tokens in the last 24 hours,
--              ranked by transaction count and recent activity.

SELECT 
    t.token_symbol, 
    t.token_mint, 
    t.wallet_address,
    COUNT(*) as tx_count,
    SUM(CASE WHEN t.transaction_type = 'buy' THEN t.token_amount ELSE 0 END) as total_bought,
    SUM(CASE WHEN t.transaction_type = 'sell' THEN t.token_amount ELSE 0 END) as total_sold,
    AVG(CASE WHEN t.price_per_token > 0 THEN t.price_per_token ELSE NULL END) as avg_price,
    MAX(t.block_time) as last_activity,
    SUM(ABS(t.amount)) as total_sol_volume
FROM transactions t
WHERE t.is_token_transaction = 1 
AND t.block_time >= ?
GROUP BY t.token_mint, t.token_symbol, t.wallet_address
HAVING tx_count >= 1
ORDER BY tx_count DESC, last_activity DESC
LIMIT 20;
