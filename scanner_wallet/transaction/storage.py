
"""
Solana Wallet Monitor - Transaction Storage Module
Advanced transaction storage with indexing, compression, and retention policies
"""

import time
import sqlite3
import threading
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
import json
import zlib
import hashlib

# Core imports with fallbacks
try:
    from core.logger import get_logger
    from core.database import get_database_manager
    from core.config import get_config
    from core.exceptions import DatabaseError
    
    from models.transaction import Transaction, TransactionType, TransactionStatus
    from models.token import Token
    
    from utils.helpers import get_current_timestamp, safe_divide
    from utils.validators import validate_wallet_address
    
except ImportError as e:
    # Fallback implementations for development
    import logging
    def get_logger(name=None):
        return logging.getLogger(name or 'transaction_storage')
    
    def get_database_manager(): return None
    def get_config(): return None
    
    def validate_wallet_address(addr): return len(addr) == 44

# Logger
logger = get_logger(__name__)

@dataclass
class StorageStats:
    """Storage statistics"""
    total_transactions: int = 0
    total_compressed: int = 0
    storage_size_mb: float = 0.0
    compression_ratio: float = 1.0
    last_cleanup: int = field(default_factory=lambda: int(time.time()))

@dataclass
class StorageConfig:
    """Storage configuration"""
    compression_enabled: bool = True
    compression_level: int = 6
    retention_days: int = 365
    max_batch_size: int = 1000
    enable_indexing: bool = True
    enable_archiving: bool = True

class TransactionStorage:
    """
    Advanced transaction storage system with compression, indexing, and retention
    Optimized for high-volume transaction data
    """
    
    def __init__(self):
        self.config = get_config()
        self.db_manager = get_database_manager()
        
        # Storage configuration
        self.storage_config = StorageConfig()
        self.stats = StorageStats()
        
        # Thread-safe operations
        self._lock = threading.Lock()
        self._batch_queue: List[Transaction] = []
        self._compression_cache: Dict[str, bytes] = {}
        self._index_cache: Dict[str, Set[str]] = defaultdict(set)
        
        # Initialize storage
        self._initialize_storage()
        
        logger.info("💾 Transaction storage initialized")
    
    def _initialize_storage(self):
        """Initialize storage tables and indexes"""
        if not self.db_manager:
            logger.warning("⚠️ No database manager available")
            return
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Create main transactions table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS transactions (
                        signature TEXT PRIMARY KEY,
                        wallet_address TEXT NOT NULL,
                        slot INTEGER NOT NULL,
                        block_time INTEGER NOT NULL,
                        amount REAL NOT NULL,
                        fee REAL NOT NULL,
                        token_mint TEXT,
                        token_symbol TEXT,
                        token_name TEXT,
                        token_amount REAL,
                        price_per_token REAL,
                        transaction_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        is_token_transaction INTEGER DEFAULT 0,
                        is_large_token_amount INTEGER DEFAULT 0,
                        detection_delay REAL,
                        wallet_priority_at_detection REAL,
                        scan_cycle_id TEXT,
                        source TEXT,
                        metadata_json TEXT,
                        compressed_data BLOB,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL,
                        tags TEXT
                    )
                """)
                
                # Create indexes for performance
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_transactions_wallet_time 
                    ON transactions(wallet_address, block_time DESC)
                """)
                
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_transactions_token 
                    ON transactions(token_mint, block_time DESC)
                """)
                
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_transactions_type 
                    ON transactions(transaction_type, status)
                """)
                
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_transactions_recent 
                    ON transactions(block_time DESC, wallet_address)
                """)
                
                # Create compressed transactions table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS transactions_compressed (
                        signature TEXT PRIMARY KEY,
                        wallet_address TEXT NOT NULL,
                        compressed_data BLOB NOT NULL,
                        original_size INTEGER NOT NULL,
                        compressed_size INTEGER NOT NULL,
                        compression_ratio REAL NOT NULL,
                        created_at INTEGER NOT NULL
                    )
                """)
                
                # Create transaction tags table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS transaction_tags (
                        signature TEXT NOT NULL,
                        tag_name TEXT NOT NULL,
                        tag_value TEXT,
                        confidence REAL,
                        created_at INTEGER NOT NULL,
                        PRIMARY KEY (signature, tag_name)
                    )
                """)
                
                # Create transaction analytics table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS transaction_analytics (
                        signature TEXT PRIMARY KEY,
                        pnl_sol REAL,
                        pnl_usd REAL,
                        classification TEXT,
                        confidence REAL,
                        risk_score REAL,
                        patterns_detected TEXT,
                        metadata_json TEXT,
                        analyzed_at INTEGER NOT NULL
                    )
                """)
                
                conn.commit()
                logger.info("✅ Storage tables and indexes created")
                
        except Exception as e:
            logger.error(f"❌ Error initializing storage: {e}")
            raise DatabaseError(f"Storage initialization failed: {e}")
    
    def store_transaction(self, transaction: Transaction, compress: bool = None) -> bool:
        """Store a single transaction with optional compression"""
        if compress is None:
            compress = self.storage_config.compression_enabled
        
        try:
            if not validate_wallet_address(transaction.wallet_address):
                logger.warning(f"❌ Invalid wallet address: {transaction.wallet_address}")
                return False
            
            # Prepare transaction data
            transaction_data = {
                'signature': transaction.signature,
                'wallet_address': transaction.wallet_address,
                'slot': transaction.slot,
                'block_time': transaction.block_time,
                'amount': float(transaction.amount),
                'fee': float(transaction.fee),
                'token_mint': transaction.token_mint,
                'token_symbol': transaction.token_symbol,
                'token_name': transaction.token_name,
                'token_amount': float(transaction.token_amount) if transaction.token_amount else None,
                'price_per_token': float(transaction.price_per_token) if transaction.price_per_token else None,
                'transaction_type': str(transaction.transaction_type),
                'status': str(transaction.status),
                'is_token_transaction': transaction.is_token_transaction,
                'is_large_token_amount': transaction.is_large_token_amount,
                'detection_delay': transaction.detection_delay,
                'wallet_priority_at_detection': transaction.wallet_priority_at_detection,
                'scan_cycle_id': transaction.scan_cycle_id,
                'source': transaction.source,
                'created_at': transaction.created_at,
                'updated_at': transaction.created_at
            }
            
            if compress and self.storage_config.compression_enabled:
                return self._store_compressed_transaction(transaction_data)
            else:
                return self._store_uncompressed_transaction(transaction_data)
                
        except Exception as e:
            logger.error(f"❌ Error storing transaction {transaction.signature}: {e}")
            return False
    
    def _store_uncompressed_transaction(self, data: Dict[str, Any]) -> bool:
        """Store transaction without compression"""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                logger.info(f"DEBUG_JULES: Saving transaction {data['signature']}. is_token_transaction = {data.get('is_token_transaction')}")
                cursor.execute("""
                    INSERT OR REPLACE INTO transactions (
                        signature, wallet_address, slot, block_time, amount, fee,
                        token_mint, token_symbol, token_name, token_amount,
                        price_per_token, transaction_type, status, 
                        is_token_transaction, is_large_token_amount,
                        detection_delay, wallet_priority_at_detection, scan_cycle_id,
                        source, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    data['signature'], data['wallet_address'], data['slot'],
                    data['block_time'], data['amount'], data['fee'],
                    data['token_mint'], data['token_symbol'], data['token_name'],
                    data['token_amount'], data['price_per_token'],
                    data['transaction_type'], data['status'],
                    data['is_token_transaction'], data['is_large_token_amount'],
                    data['detection_delay'], data['wallet_priority_at_detection'], data['scan_cycle_id'],
                    data['source'], data['created_at'], data['updated_at']
                ))
                
                conn.commit()
                
                with self._lock:
                    self.stats.total_transactions += 1
                
                return True
                
        except Exception as e:
            logger.error(f"❌ Error storing uncompressed transaction: {e}")
            return False
    
    def _store_compressed_transaction(self, data: Dict[str, Any]) -> bool:
        """Store transaction with compression"""
        try:
            # Compress transaction data
            json_data = json.dumps(data)
            compressed = zlib.compress(json_data.encode('utf-8'), self.storage_config.compression_level)
            
            original_size = len(json_data.encode('utf-8'))
            compressed_size = len(compressed)
            compression_ratio = compressed_size / original_size
            
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Store compressed transaction
                cursor.execute("""
                    INSERT OR REPLACE INTO transactions_compressed (
                        signature, wallet_address, compressed_data,
                        original_size, compressed_size, compression_ratio, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    data['signature'], data['wallet_address'], compressed,
                    original_size, compressed_size, compression_ratio, data['created_at']
                ))
                
                conn.commit()
                
                with self._lock:
                    self.stats.total_compressed += 1
                    self.stats.compression_ratio = compression_ratio
                
                return True
                
        except Exception as e:
            logger.error(f"❌ Error storing compressed transaction: {e}")
            return False
    
    def store_batch_transactions(self, transactions: List[Transaction]) -> int:
        """Store multiple transactions efficiently"""
        if not transactions:
            return 0
        
        stored = 0
        
        try:
            # Process in batches
            batch_size = min(self.storage_config.max_batch_size, len(transactions))
            
            for i in range(0, len(transactions), batch_size):
                batch = transactions[i:i+batch_size]
                
                with self.db_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Use transaction for batch insert
                    cursor.execute("BEGIN TRANSACTION")
                    
                    for transaction in batch:
                        if self.store_transaction(transaction):
                            stored += 1
                    
                    cursor.execute("COMMIT")
        
        except Exception as e:
            logger.error(f"❌ Error storing batch transactions: {e}")
        
        logger.info(f"💾 Stored {stored} transactions in batch")
        return stored
    
    def get_transaction(self, signature: str) -> Optional[Transaction]:
        """Retrieve a single transaction by signature"""
        try:
            if not self.db_manager:
                return None
            
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM transactions
                    WHERE signature = ?
                """, (signature,))
                
                row = cursor.fetchone()
                if row:
                    return Transaction(
                        signature=row['signature'],
                        wallet_address=row['wallet_address'],
                        slot=row['slot'],
                        block_time=row['block_time'],
                        amount=float(row['amount']),
                        fee=float(row['fee']),
                        token_mint=row['token_mint'],
                        token_symbol=row['token_symbol'],
                        token_name=row['token_name'],
                        token_amount=float(row['token_amount']) if row['token_amount'] else 0.0,
                        price_per_token=float(row['price_per_token']) if row['price_per_token'] else 0.0,
                        transaction_type=TransactionType(row['transaction_type']),
                        status=TransactionStatus(row['status']),
                        source=row['source']
                    )
        
        except Exception as e:
            logger.error(f"❌ Error retrieving transaction {signature}: {e}")
        
        return None
    
    def get_wallet_transactions(
        self,
        wallet_address: str,
        token_mint: Optional[str] = None,
        transaction_type: Optional[TransactionType] = None,
        status: Optional[TransactionStatus] = None,
        limit: int = 100,
        offset: int = 0,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None
    ) -> List[Transaction]:
        """Get transactions for wallet with filtering"""
        transactions = []
        
        try:
            if not validate_wallet_address(wallet_address):
                return []
            
            if not self.db_manager:
                return []
            
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Build query with filters
                query = """
                    SELECT * FROM transactions
                    WHERE wallet_address = ?
                """
                params = [wallet_address]
                
                if token_mint:
                    query += " AND token_mint = ?"
                    params.append(token_mint)
                
                if transaction_type:
                    query += " AND transaction_type = ?"
                    params.append(str(transaction_type))
                
                if status:
                    query += " AND status = ?"
                    params.append(str(status))
                
                if start_time:
                    query += " AND block_time >= ?"
                    params.append(start_time)
                
                if end_time:
                    query += " AND block_time <= ?"
                    params.append(end_time)
                
                query += " ORDER BY block_time DESC LIMIT ? OFFSET ?"
                params.extend([limit, offset])
                
                cursor.execute(query, params)
                
                for row in cursor.fetchall():
                    transaction = Transaction(
                        signature=row['signature'],
                        wallet_address=row['wallet_address'],
                        slot=row['slot'],
                        block_time=row['block_time'],
                        amount=float(row['amount']),
                        fee=float(row['fee']),
                        token_mint=row['token_mint'],
                        token_symbol=row['token_symbol'],
                        token_name=row['token_name'],
                        token_amount=float(row['token_amount']) if row['token_amount'] else 0.0,
                        price_per_token=float(row['price_per_token']) if row['price_per_token'] else 0.0,
                        transaction_type=TransactionType(row['transaction_type']),
                        status=TransactionStatus(row['status']),
                        source=row['source']
                    )
                    transactions.append(transaction)
        
        except Exception as e:
            logger.error(f"❌ Error retrieving wallet transactions: {e}")
        
        return transactions
    
    def get_transaction_analytics(self, signature: str) -> Optional[Dict[str, Any]]:
        """Get transaction analytics data"""
        try:
            if not self.db_manager:
                return None
            
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM transaction_analytics
                    WHERE signature = ?
                """, (signature,))
                
                row = cursor.fetchone()
                if row:
                    return {
                        'pnl_sol': float(row['pnl_sol']) if row['pnl_sol'] else 0.0,
                        'pnl_usd': float(row['pnl_usd']) if row['pnl_usd'] else 0.0,
                        'classification': row['classification'],
                        'confidence': float(row['confidence']) if row['confidence'] else 0.0,
                        'risk_score': float(row['risk_score']) if row['risk_score'] else 0.0,
                        'patterns_detected': json.loads(row['patterns_detected']) if row['patterns_detected'] else [],
                        'metadata': json.loads(row['metadata_json']) if row['metadata_json'] else {},
                        'analyzed_at': row['analyzed_at']
                    }
        
        except Exception as e:
            logger.error(f"❌ Error retrieving transaction analytics: {e}")
        
        return None
    
    def cleanup_old_data(self, days: int = None) -> int:
        """Clean up old transaction data based on retention policy"""
        if days is None:
            days = self.storage_config.retention_days
        
        if not self.db_manager:
            return 0
        
        try:
            cutoff_time = int(time.time()) - (days * 86400)
            
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Delete old transactions
                cursor.execute("""
                    DELETE FROM transactions
                    WHERE block_time < ?
                """, (cutoff_time,))
                
                deleted_transactions = cursor.rowcount
                
                # Delete old compressed transactions
                cursor.execute("""
                    DELETE FROM transactions_compressed
                    WHERE created_at < ?
                """, (cutoff_time,))
                
                deleted_compressed = cursor.rowcount
                
                # Delete old analytics
                cursor.execute("""
                    DELETE FROM transaction_analytics
                    WHERE analyzed_at < ?
                """, (cutoff_time,))
                
                deleted_analytics = cursor.rowcount
                
                conn.commit()
                
                total_deleted = deleted_transactions + deleted_compressed + deleted_analytics
                
                logger.info(f"🧹 Cleaned up old data: {total_deleted} records removed")
                
                with self._lock:
                    self.stats.last_cleanup = int(time.time())
                
                return total_deleted
                
        except Exception as e:
            logger.error(f"❌ Error cleaning old data: {e}")
            return 0
    
    def get_storage_stats(self) -> Dict[str, Any]:
        """Get comprehensive storage statistics"""
        stats = {
            'total_transactions': 0,
            'compressed_transactions': 0,
            'storage_size_mb': 0.0,
            'compression_ratio': 0.0,
            'retention_days': self.storage_config.retention_days,
            'last_cleanup': self.stats.last_cleanup
        }
        
        try:
            if self.db_manager:
                with self.db_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Count transactions
                    cursor.execute("SELECT COUNT(*) FROM transactions")
                    stats['total_transactions'] = cursor.fetchone()[0]
                    
                    cursor.execute("SELECT COUNT(*) FROM transactions_compressed")
                    stats['compressed_transactions'] = cursor.fetchone()[0]
                    
                    # Calculate storage size
                    cursor.execute("""
                        SELECT SUM(LENGTH(compressed_data)) FROM transactions_compressed
                    """)
                    compressed_size = cursor.fetchone()[0] or 0
                    
                    cursor.execute("""
                        SELECT SUM(original_size) FROM transactions_compressed
                    """)
                    original_size = cursor.fetchone()[0] or 0
                    
                    stats['storage_size_mb'] = compressed_size / (1024 * 1024)
                    stats['compression_ratio'] = safe_divide(compressed_size, original_size)
        
        except Exception as e:
            logger.error(f"❌ Error getting storage stats: {e}")
        
        return stats
    
    def search_transactions(
        self,
        query: str,
        wallet_address: Optional[str] = None,
        limit: int = 50
    ) -> List[Transaction]:
        """Search transactions with full-text search"""
        results = []
        
        try:
            if not self.db_manager:
                return []
            
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Build search query
                search_query = """
                    SELECT * FROM transactions
                    WHERE (signature LIKE ? OR token_symbol LIKE ? OR token_name LIKE ?)
                """
                params = [f'%{query}%', f'%{query}%', f'%{query}%']
                
                if wallet_address:
                    search_query += " AND wallet_address = ?"
                    params.append(wallet_address)
                
                search_query += " ORDER BY block_time DESC LIMIT ?"
                params.append(limit)
                
                cursor.execute(search_query, params)
                
                for row in cursor.fetchall():
                    transaction = Transaction(
                        signature=row['signature'],
                        wallet_address=row['wallet_address'],
                        slot=row['slot'],
                        block_time=row['block_time'],
                        amount=float(row['amount']),
                        fee=float(row['fee']),
                        token_mint=row['token_mint'],
                        token_symbol=row['token_symbol'],
                        token_name=row['token_name'],
                        token_amount=float(row['token_amount']) if row['token_amount'] else 0.0,
                        price_per_token=float(row['price_per_token']) if row['price_per_token'] else 0.0,
                        transaction_type=TransactionType(row['transaction_type']),
                        status=TransactionStatus(row['status']),
                        source=row['source']
                    )
                    results.append(transaction)
        
        except Exception as e:
            logger.error(f"❌ Error searching transactions: {e}")
        
        return results
    
    def export_transactions(
        self,
        wallet_address: str,
        format: str = "json",
        start_time: Optional[int] = None,
        end_time: Optional[int] = None
    ) -> str:
        """Export transactions in specified format"""
        transactions = self.get_wallet_transactions(
            wallet_address,
            start_time=start_time,
            end_time=end_time
        )
        
        if format == "json":
            return json.dumps([tx.to_dict() for tx in transactions], indent=2, default=str)
        
        elif format == "csv":
            # Generate CSV format
            import csv
            import io
            
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow([
                'signature', 'wallet_address', 'slot', 'block_time',
                'amount', 'fee', 'token_mint', 'token_symbol',
                'token_name', 'token_amount', 'price_per_token',
                'transaction_type', 'status', 'source'
            ])
            
            # Write data
            for tx in transactions:
                writer.writerow([
                    tx.signature, tx.wallet_address, tx.slot, tx.block_time,
                    tx.amount, tx.fee, tx.token_mint, tx.token_symbol,
                    tx.token_name, tx.token_amount, tx.price_per_token,
                    str(tx.transaction_type), str(tx.status), tx.source
                ])
            
            return output.getvalue()
        
        return ""

# Global instance
_storage = None

def get_transaction_storage() -> TransactionStorage:
    """Get global transaction storage instance"""
    global _storage
    
    if _storage is None:
        _storage = TransactionStorage()
    
    return _storage

# Convenience functions
def store_transaction(transaction: Transaction) -> bool:
    """Store transaction using global storage"""
    return get_transaction_storage().store_transaction(transaction)

def get_transaction(signature: str) -> Optional[Transaction]:
    """Get transaction using global storage"""
    return get_transaction_storage().get_transaction(signature)

def get_wallet_transactions(wallet_address: str, **kwargs) -> List[Transaction]:
    """Get wallet transactions using global storage"""
    return get_transaction_storage().get_wallet_transactions(wallet_address, **kwargs)

def cleanup_old_transactions(days: int = 365) -> int:
    """Clean old transactions using global storage"""
    return get_transaction_storage().cleanup_old_data(days)

# Development testing
if __name__ == "__main__":
    logger.info("🧪 Testing Transaction Storage...")
    
    # Create test instance
    storage = get_transaction_storage()
    
    # Test with sample transaction
    test_tx = Transaction(
        signature="test_storage_123456789",
        wallet_address="4DdrfGHGdMjCqVbNtXsEEGL1SryTeMo8KMGWWtZyZVFh",
        slot=123456789,
        block_time=int(time.time()) - 3600,
        amount=1.5,
        fee=0.0005,
        token_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        token_symbol="USDC",
        token_name="USD Coin",
        token_amount=150.0,
        price_per_token=1.0,
        transaction_type="buy",
        status="success",
        source="test"
    )
    
    # Test storage
    success = storage.store_transaction(test_tx)
    logger.info(f"💾 Storage test: {'✅ Success' if success else '❌ Failed'}")
    
    # Test retrieval
    retrieved = storage.get_transaction(test_tx.signature)
    logger.info(f"🔍 Retrieval test: {'✅ Success' if retrieved else '❌ Failed'}")
    
    # Test stats
    stats = storage.get_storage_stats()
    logger.info(f"📊 Storage stats: {stats}")
    
    logger.info("✅ Transaction storage test completed")