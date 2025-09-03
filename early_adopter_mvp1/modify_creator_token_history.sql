ALTER TABLE creator_token_history ADD COLUMN last_updated_from_api TIMESTAMP;
ALTER TABLE creator_token_history ADD COLUMN current_market_cap REAL DEFAULT 0.0;
CREATE INDEX idx_creator_token_history_last_updated ON creator_token_history(last_updated_from_api);

ALTER TABLE creator_token_history
ADD COLUMN is_complete INTEGER NOT NULL DEFAULT 0;

ALTER TABLE creator_token_history
ADD COLUMN bonding_curve_completed_timestamp INTEGER NOT NULL DEFAULT 0;