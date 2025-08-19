"""
Token Repository
Handles all database operations related to tokens.
"""
import time
import logging
from typing import List, Dict, Optional, Set, Tuple
from datetime import datetime, timedelta
import sqlite3

from .connection import DatabaseConnection, db_retry
from ..models.token_data import TokenData, QueueItem
from .history_repository import HistoryRepository


class TokenRepository:
    """Repository for token-related database operations"""
    
    def __init__(self, db_connection: DatabaseConnection, history_repo: HistoryRepository, logger: Optional[logging.Logger] = None):
        self.db = db_connection
        self.history_repo = history_repo
        self.logger = logger or logging.getLogger(__name__)
    
    @db_retry(max_retries=3, delay=0.3)
    def get_token_by_address(self, address: str) -> Optional[Dict]:
        """Get token by address"""
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tokens WHERE address = ?", (address,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    @db_retry(max_retries=3, delay=0.3)
    def token_exists(self, address: str) -> bool:
        """Check if token exists in database"""
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM tokens WHERE address = ? LIMIT 1", (address,))
            return cursor.fetchone() is not None

    @db_retry(max_retries=3, delay=0.3)
    def get_most_recent_token_timestamp(self) -> Optional[str]:
        """Get the created_at timestamp of the most recently created token."""
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(created_at) FROM tokens")
            result = cursor.fetchone()
            return result[0] if result and result[0] else None
    
    @db_retry(max_retries=3, delay=0.3)
    def get_new_tokens_from_transactions(
        self, 
        retry_failed_after_days: int = 7, 
        max_failed_attempts: int = 5,
        since_timestamp: Optional[str] = None,
        limit: Optional[int] = None
    ) -> Set[str]:
        """Get new token addresses from transactions table (excluding flagged tokens)"""
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            params = [retry_failed_after_days, max_failed_attempts]
            
            query = """
            SELECT DISTINCT t.token_mint
            FROM transactions t
            LEFT JOIN tokens tk ON t.token_mint = tk.address
            WHERE t.token_mint IS NOT NULL 
            AND t.token_mint != ''
            AND tk.address IS NULL
            AND t.token_mint NOT IN (
                SELECT address FROM tokens 
                WHERE no_data_available = 1 
                AND (no_data_last_check > datetime('now', '-' || ? || ' days') OR failed_attempts >= ?)
            )
            """

            if since_timestamp:
                query += " AND t.created_at > ?"
                params.append(since_timestamp)
            
            query += " ORDER BY t.created_at DESC"

            if limit:
                query += " LIMIT ?"
                params.append(limit)
            
            cursor.execute(query, tuple(params))
            results = cursor.fetchall()
            
            return {row[0] for row in results}
    
    @db_retry(max_retries=3, delay=0.3)
    def get_tokens_needing_price_update(
        self, 
        interval_seconds: int, 
        max_failed_attempts: int, 
        limit: int
    ) -> List[str]:
        """Get tokens that need price updates"""
        cutoff_time = int(time.time()) - interval_seconds
        
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            query = """
            SELECT address 
            FROM tokens 
            WHERE (last_price_update < ? OR last_price_update IS NULL)
            AND is_dead = 0
            AND (no_data_available = 0 OR no_data_available IS NULL)
            AND (failed_attempts < ? OR failed_attempts IS NULL)
            ORDER BY 
                CASE WHEN last_price_update IS NULL THEN 0 ELSE last_price_update END ASC,
                market_cap DESC NULLS LAST
            LIMIT ?
            """
            
            cursor.execute(query, (cutoff_time, max_failed_attempts, limit))
            results = cursor.fetchall()
            
            return [row[0] for row in results]
    
    @db_retry(max_retries=3, delay=0.3)
    def get_tokens_missing_creation_timestamp(self, limit: int = 100) -> List[str]:
        """Get tokens that need creation timestamp updates"""
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            query = """
            SELECT address 
            FROM tokens 
            WHERE (timestamp_token_created IS NULL OR timestamp_token_created = 0)
            AND is_dead = 0
            ORDER BY created_at DESC
            LIMIT ?
            """
            
            cursor.execute(query, (limit,))
            results = cursor.fetchall()
            
            return [row[0] for row in results]
    
    @db_retry(max_retries=3, delay=0.3)
    def get_tokens_needing_historization(self, interval_seconds: int, limit: int = 100) -> List[str]:
        """Get tokens that need historization"""
        cutoff_time = int(time.time()) - interval_seconds
        
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            query = """
            SELECT address 
            FROM tokens 
            WHERE is_dead = 0
            AND (is_rugged = 0 OR is_rugged IS NULL)
            AND (last_historized_at < ? OR last_historized_at IS NULL)
            AND (price_usd > 0 OR market_cap > 0)
            ORDER BY last_historized_at ASC NULLS FIRST
            LIMIT ?
            """
            
            cursor.execute(query, (cutoff_time, limit))
            results = cursor.fetchall()
            
            return [row[0] for row in results]
    
    @db_retry(max_retries=3, delay=0.3)
    def upsert_token(self, token_data: TokenData) -> bool:
        """Insert or update token in database"""
        try:
            # Clean data first
            token_data = token_data.clean_symbol_name()
            current_timestamp = int(time.time())
            
            with self.db.get_connection_context() as conn:
                cursor = conn.cursor()
                
                check_start = time.time()
                token_exists = self.token_exists(token_data.address)
                check_duration = time.time() - check_start
            
                self.logger.debug(f"💾 Token exists check: {token_data.address[:8]}... exists={token_exists} ({check_duration:.3f}s)")
                
                # Calculate advanced metrics
                liquidity_mc_ratio = 0.0
                volume_mc_ratio = 0.0
                if token_data.market_cap > 0:
                    liquidity_mc_ratio = token_data.liquidity_usd / token_data.market_cap
                    volume_mc_ratio = token_data.volume_24h / token_data.market_cap
                
                if token_exists:
                    # Historize before update
                    self.history_repo.create_snapshot(token_data.address)
                    update_start = time.time()
                    # Update existing token
                    query = """
                    UPDATE tokens SET
                        symbol = COALESCE(?, symbol),
                        name = COALESCE(?, name),
                        decimals = COALESCE(?, decimals),
                        price_usd = ?,
                        logo_uri = COALESCE(?, logo_uri),
                        coingecko_id = COALESCE(?, coingecko_id),
                        is_verified = COALESCE(?, is_verified),
                        timestamp_token_created = CASE 
                            WHEN ? > 0 AND (timestamp_token_created IS NULL OR timestamp_token_created = 0) 
                            THEN ? 
                            ELSE timestamp_token_created 
                        END,
                        creator_address = COALESCE(?, creator_address),
                        bonding_curve_progress = MAX(COALESCE(bonding_curve_progress, 0), COALESCE(?, 0)),
                        holder_count = MAX(COALESCE(holder_count, 0), COALESCE(?, 0)),
                        market_cap = ?,
                        fdv = ?,
                        liquidity_usd = ?,
                        liquidity_sol = ?,
                        liquidity_mc_ratio = ?,
                        volume_mc_ratio = ?,
                        price_volatility_24h = ?,
                        volume_5m = ?,
                        volume_1h = ?,
                        volume_6h = ?,
                        volume_24h = ?,
                        price_change_5m = ?,
                        price_change_1h = ?,
                        price_change_6h = ?,
                        price_change_24h = ?,
                        last_price_update = ?,
                        metadata_source = COALESCE(?, metadata_source),
                        updated_at = CURRENT_TIMESTAMP,
                        failed_attempts = 0,
                        no_data_available = 0
                    WHERE address = ?
                    """
                    
                    cursor.execute(query, (
                        token_data.symbol,
                        token_data.name,
                        token_data.decimals,
                        token_data.price_usd,
                        token_data.logo_uri,
                        token_data.coingecko_id,
                        token_data.is_verified,
                        token_data.timestamp_token_created,
                        token_data.timestamp_token_created,
                        token_data.creator_address,
                        token_data.bonding_curve_progress,
                        token_data.holder_count,
                        token_data.market_cap,
                        token_data.fdv,
                        token_data.liquidity_usd,
                        token_data.liquidity_sol,
                        liquidity_mc_ratio,
                        volume_mc_ratio,
                        getattr(token_data, 'price_volatility_24h', 0.0),
                        token_data.volume_5m,
                        token_data.volume_1h,
                        token_data.volume_6h,
                        token_data.volume_24h,
                        token_data.price_change_5m,
                        token_data.price_change_1h,
                        token_data.price_change_6h,
                        token_data.price_change_24h,
                        current_timestamp,
                        token_data.metadata_source,
                        token_data.address
                    ))

                    update_duration = time.time() - update_start
                    rows_affected = cursor.rowcount
                
                    self.logger.debug(f"💾 Update query for {token_data.address[:8]}... completed in {update_duration:.3f}s, rows affected: {rows_affected}")

                else:
                    # Insert new token
                    insert_start = time.time()
                    query = """
                    INSERT INTO tokens (
                        address, symbol, name, decimals, price_usd, logo_uri,
                        coingecko_id, is_verified, timestamp_token_created, creator_address,
                        bonding_curve_progress, holder_count, market_cap, fdv,
                        liquidity_usd, liquidity_sol, liquidity_mc_ratio, volume_mc_ratio,
                        price_volatility_24h,
                        volume_5m, volume_1h, volume_6h, volume_24h, 
                        price_change_5m, price_change_1h, price_change_6h, price_change_24h,
                        last_price_update, metadata_source, last_historized_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """

                    cursor.execute(query, (
                        token_data.address,
                        token_data.symbol,
                        token_data.name,
                        token_data.decimals,
                        token_data.price_usd,
                        token_data.logo_uri,
                        token_data.coingecko_id,
                        token_data.is_verified,
                        token_data.timestamp_token_created,
                        token_data.creator_address,
                        token_data.bonding_curve_progress,
                        token_data.holder_count,
                        token_data.market_cap,
                        token_data.fdv,
                        token_data.liquidity_usd,
                        token_data.liquidity_sol,
                        liquidity_mc_ratio,
                        volume_mc_ratio,
                        getattr(token_data, 'price_volatility_24h', 0.0),
                        token_data.volume_5m,
                        token_data.volume_1h,
                        token_data.volume_6h,
                        token_data.volume_24h,
                        token_data.price_change_5m,
                        token_data.price_change_1h,
                        token_data.price_change_6h,
                        token_data.price_change_24h,
                        current_timestamp,
                        token_data.metadata_source,
                        current_timestamp
                    ))
                    insert_duration = time.time() - insert_start
                    rows_affected = cursor.rowcount
                    self.logger.debug(f"💾 Insert query for {token_data.address[:8]}... completed in {insert_duration:.3f}s, rows affected: {rows_affected}")
                    
                    # Historize after insert
                    self.history_repo.create_snapshot(token_data.address)

                conn.commit()
                commit_duration = time.time() - (update_start if token_exists else insert_start)
                self.logger.debug(f"✅ Upsert completed for {token_data.address[:8]}... total time: {commit_duration:.3f}s")
                return True
                
        except Exception as e:
            self.logger.error(f"Error upserting token {token_data.address}: {e}")
            return False
    
    @db_retry(max_retries=3, delay=0.3)
    def mark_token_no_data(self, token_address: str, max_attempts: int, increment_attempts: bool = True) -> bool:
        """Mark a token as having no data available"""
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            if increment_attempts:
                # Increment failed attempts counter
                cursor.execute("""
                    UPDATE tokens 
                    SET failed_attempts = COALESCE(failed_attempts, 0) + 1,
                        no_data_last_check = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE address = ?
                """, (token_address,))
                
                if cursor.rowcount == 0:
                    # If the update failed (e.g., token not found), we consider it a failure.
                    conn.commit()
                    return False

                # Check if we should mark as no_data_available after enough attempts
                cursor.execute("SELECT failed_attempts FROM tokens WHERE address = ?", (token_address,))
                result = cursor.fetchone()
                
                if result and result[0] >= max_attempts:
                    cursor.execute("""
                        UPDATE tokens SET no_data_available = 1 WHERE address = ?
                    """, (token_address,))
                    self.logger.warning(f"Token {token_address[:8]}... marked as no_data_available after {result[0]} failed attempts")

                conn.commit()
                # Return True because the primary operation (incrementing attempts) was successful.
                return True
            else:
                # Mark directly as no_data
                cursor.execute("""
                    UPDATE tokens 
                    SET no_data_available = 1,
                        no_data_last_check = CURRENT_TIMESTAMP,
                        failed_attempts = COALESCE(failed_attempts, 0) + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE address = ?
                """, (token_address,))
                self.logger.warning(f"Token {token_address[:8]}... marked as no_data_available")
                update_successful = cursor.rowcount > 0
                conn.commit()
                return update_successful
    
    @db_retry(max_retries=3, delay=0.3)
    def create_token_stub(self, token_address: str, max_attempts: int) -> bool:
        """Create a minimal token entry when no data is found"""
        try:
            # CORRECTION: Validation de l'adresse du token
            if not token_address or len(token_address.strip()) < 32:
                self.logger.warning(f"Invalid token address: {token_address}")
                return False
            
            token_address = token_address.strip()
            
            # Check if token already exists
            if self.token_exists(token_address):
                return self.mark_token_no_data(token_address, max_attempts=max_attempts)
            
            with self.db.get_connection_context() as conn:
                cursor = conn.cursor()
                
                try:
                    query = """
                    INSERT INTO tokens (
                        address, symbol, name, decimals, price_usd, 
                        failed_attempts, no_data_available,
                        last_price_update, metadata_source, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """
                    
                    cursor.execute(query, (
                        token_address,
                        f"UNK_{token_address[:6]}",
                        f"Unknown Token {token_address[:8]}",
                        9,
                        0.0,
                        1,
                        0,  # Pas immédiatement marqué comme no_data
                        int(time.time()),
                        "stub"
                    ))
                    
                    conn.commit()
                    self.logger.debug(f"✅ Created stub entry for {token_address[:8]}...")
                    return True
                    
                except sqlite3.IntegrityError as e:
                    # Token existe déjà, marquer comme no_data au lieu d'échouer
                    self.logger.debug(f"Token {token_address[:8]}... already exists, marking as no_data")
                    return self.mark_token_no_data(token_address)
                    
        except Exception as e:
            self.logger.error(f"Error creating token stub {token_address}: {e}")
            return False
    
    @db_retry(max_retries=3, delay=0.3)
    def update_creation_timestamp(self, token_address: str, timestamp: int) -> bool:
        """Update only the creation timestamp for a specific token"""
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE tokens 
                SET timestamp_token_created = ?, updated_at = CURRENT_TIMESTAMP
                WHERE address = ?
            """, (timestamp, token_address))
            
            conn.commit()
            return cursor.rowcount > 0
    
    @db_retry(max_retries=3, delay=0.3)
    def get_tokens_for_dead_check(self) -> List[Dict]:
        """Get tokens that should be checked for dead status"""
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT address, symbol, price_usd, market_cap, volume_24h, 
                       holder_count, liquidity_usd, price_change_24h, 
                       viability_score, risk_score
                FROM tokens 
                WHERE is_dead = 0 
                AND updated_at > datetime('now', '-7 days')
            """)
            
            return [dict(row) for row in cursor.fetchall()]
    
    @db_retry(max_retries=3, delay=0.3)
    def mark_token_dead(self, token_address: str, death_reason: str) -> bool:
        """Mark a token as dead"""
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE tokens 
                SET is_dead = 1, 
                    death_reason = ?, 
                    death_timestamp = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE address = ?
            """, (death_reason, int(time.time()), token_address))
            
            conn.commit()
            return cursor.rowcount > 0
    
    @db_retry(max_retries=3, delay=0.3)
    def get_flagged_tokens_stats(self) -> Dict:
        """Get statistics about flagged tokens"""
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            stats = {}
            
            # Tokens marked as no_data
            cursor.execute("SELECT COUNT(*) FROM tokens WHERE no_data_available = 1")
            stats['no_data_flagged'] = cursor.fetchone()[0]
            
            # Tokens with failed attempts but not yet flagged
            cursor.execute("SELECT COUNT(*) FROM tokens WHERE failed_attempts > 0 AND no_data_available = 0")
            stats['partial_failures'] = cursor.fetchone()[0]
            
            # Tokens eligible for retry (7 days default)
            cursor.execute("""
                SELECT COUNT(*) FROM tokens 
                WHERE no_data_available = 1 
                AND no_data_last_check < datetime('now', '-7 days')
            """)
            stats['retry_eligible'] = cursor.fetchone()[0]
            
            # Dead tokens
            cursor.execute("SELECT COUNT(*) FROM tokens WHERE is_dead = 1")
            stats['dead_tokens'] = cursor.fetchone()[0]
            
            return stats
    
    @db_retry(max_retries=3, delay=0.3)
    def get_dashboard_priority_tokens(self, limit: int = 100) -> List[str]:
        """Get tokens that appear in dashboard overview (high priority)"""
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            # Similar query to dashboard but simplified
            query = """
            WITH token_stats AS (
                SELECT 
                    t.token_mint,
                    COUNT(*) as total_transactions,
                    COUNT(CASE WHEN t.transaction_type = 'TransactionType.BUY' THEN 1 END) as total_buys,
                    COUNT(CASE WHEN t.transaction_type = 'TransactionType.SELL' THEN 1 END) as total_sells,
                    COUNT(DISTINCT CASE WHEN t.transaction_type = 'TransactionType.BUY' THEN t.wallet_address END) as unique_buyers,
                    SUM(CASE WHEN t.transaction_type = 'TransactionType.BUY' THEN t.amount ELSE 0 END) as buy_volume,
                    SUM(CASE WHEN t.transaction_type = 'TransactionType.SELL' THEN t.amount ELSE 0 END) as sell_volume,
                    AVG(CASE WHEN t.transaction_type = 'TransactionType.BUY' THEN t.wallet_priority_at_detection END) as avg_buyer_priority,
                    COUNT(CASE 
                        WHEN t.transaction_type = 'TransactionType.BUY' 
                        AND t.block_time >= (strftime('%s', 'now') - 86400) 
                        THEN 1 
                    END) as recent_buys_24h
                FROM transactions t
                WHERE t.token_mint IS NOT NULL AND t.token_mint != ''
                GROUP BY t.token_mint
                HAVING total_buys >= 1
            )
            SELECT token_mint
            FROM token_stats
            ORDER BY 
                (CASE WHEN sell_volume > 0 THEN buy_volume / sell_volume ELSE 999 END * 20) +
                (unique_buyers * 2) +
                (CASE WHEN total_buys > 0 THEN (recent_buys_24h * 100.0 / total_buys) ELSE 0 END) +
                (COALESCE(avg_buyer_priority, 0) * 50)
                DESC
            LIMIT ?
            """
            
            cursor.execute(query, (limit,))
            results = cursor.fetchall()
            
            return [row[0] for row in results if row[0]]

