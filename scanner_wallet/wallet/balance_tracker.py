
"""
Solana Wallet Monitor - Balance Tracking Module
Tracks real-time balance changes across monitored wallets
"""

import time
import threading
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime

# Core imports with fallbacks
try:
    from core.logger import get_logger
    from core.database import get_database_manager
    from core.config import get_config
    from models.transaction import Transaction, TransactionType, TransactionStatus
    from models.token import Token, TokenAccount
    from utils.helpers import safe_divide, get_current_timestamp
    from utils.validators import DataValidator
except ImportError as e:
    # Fallback implementations for development
    def get_logger(name=None):
        import logging
        return logging.getLogger(name or 'balance_tracker')
    
    def get_database_manager():
        return None
    
    def get_config():
        return None
    
    from dataclasses import dataclass
    class TransactionType:
        BUY = "buy"
        SELL = "sell"
        TRANSFER = "transfer"
    
    class TransactionStatus:
        SUCCESS = "success"
        FAILED = "failed"

# Logger instance
logger = get_logger(__name__)

@dataclass
class BalanceChange:
    """Represents a single balance change detected"""
    wallet_address: str
    token_mint: str
    ata_pubkey: str
    pre_balance: Decimal
    post_balance: Decimal
    balance_change: Decimal
    timestamp: int
    token_symbol: str = "UNKNOWN"
    token_name: str = "Unknown Token"
    decimals: int = 9
    transaction_signature: Optional[str] = None
    change_type: Optional[TransactionType] = None
    
    @property
    def display_change(self) -> Decimal:
        """Format balance change for display"""
        return safe_divide(self.balance_change, 10**self.decimals)
    
    @property
    def is_significant(self) -> bool:
        """Check if change is significant (> 0.000001)"""
        return abs(self.display_change) > Decimal('0.000001')

class BalanceTracker:
    """
    Real-time balance tracker for Solana wallets
    Monitors balance changes across all tracked wallets and tokens
    """
    
    def __init__(self):
        self.db_manager = get_database_manager()
        self.config = get_config()
        self.validator = DataValidator()
        
        # Thread-safe storage
        self._lock = threading.Lock()
        self._wallet_balances: Dict[str, Dict[str, Decimal]] = {}
        self._last_scan_time: Dict[str, int] = {}
        self._pending_changes: List[BalanceChange] = []
        
        # Tracking metrics
        self._metrics = {
            'total_changes_detected': 0,
            'total_wallets_tracked': 0,
            'last_update': 0
        }
        
        logger.info("🔍 Balance tracker initialized")
    
    def track_wallet(self, wallet_address: str) -> bool:
        """Add a wallet to tracking"""
        try:
            # Validate wallet address
            if not self.validator.solana.validate_address(wallet_address).is_valid:
                logger.warning(f"❌ Invalid wallet address: {wallet_address}")
                return False
            
            with self._lock:
                if wallet_address not in self._wallet_balances:
                    self._wallet_balances[wallet_address] = {}
                    self._last_scan_time[wallet_address] = 0
                    self._metrics['total_wallets_tracked'] += 1
                    logger.info(f"✅ Tracking wallet: {wallet_address}")
                
                # Load existing balances from DB
                self._load_existing_balances(wallet_address)
                return True
                
        except Exception as e:
            logger.error(f"❌ Error tracking wallet {wallet_address}: {e}")
            return False
    
    def untrack_wallet(self, wallet_address: str) -> bool:
        """Remove a wallet from tracking"""
        with self._lock:
            if wallet_address in self._wallet_balances:
                del self._wallet_balances[wallet_address]
                del self._last_scan_time[wallet_address]
                self._metrics['total_wallets_tracked'] -= 1
                logger.info(f"✅ Stopped tracking wallet: {wallet_address}")
                return True
        return False
    
    def _load_existing_balances(self, wallet_address: str):
        """Load existing token balances from database"""
        if not self.db_manager:
            return
            
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Query all token accounts for this wallet
                query = """
                    SELECT ta.token_mint, ta.balance, t.decimals, t.symbol, t.name
                    FROM token_accounts ta
                    JOIN tokens t ON ta.token_mint = t.address
                    WHERE ta.wallet_address = ? AND ta.is_active = 1
                """
                
                cursor.execute(query, (wallet_address,))
                results = cursor.fetchall()
                
                for token_mint, balance, decimals, symbol, name in results:
                    if balance and balance > 0:
                        self._wallet_balances[wallet_address][token_mint] = Decimal(str(balance))
                        
        except Exception as e:
            logger.error(f"❌ Error loading balances for {wallet_address}: {e}")
    
    def scan_balance_changes(self, wallet_address: str) -> List[BalanceChange]:
        """
        Scan for balance changes in a specific wallet
        Returns list of detected changes
        """
        changes = []
        
        try:
            # Validate wallet
            if wallet_address not in self._wallet_balances:
                logger.warning(f"⚠️ Wallet not tracked: {wallet_address}")
                return changes
            
            # Get current token accounts
            current_accounts = self._get_current_token_accounts(wallet_address)
            current_balances = self._get_current_balances(wallet_address, current_accounts)
            
            # Compare with stored balances
            stored_balances = self._wallet_balances.get(wallet_address, {})
            
            for mint, new_balance in current_balances.items():
                old_balance = stored_balances.get(mint, Decimal('0'))
                
                if old_balance != new_balance:
                    change = BalanceChange(
                        wallet_address=wallet_address,
                        token_mint=mint,
                        ata_pubkey=f"{wallet_address}:{mint}",  # Simplified
                        pre_balance=old_balance,
                        post_balance=new_balance,
                        balance_change=new_balance - old_balance,
                        timestamp=get_current_timestamp()
                    )
                    
                    # Get token metadata
                    token_info = self._get_token_info(mint)
                    change.token_symbol = token_info.get('symbol', 'UNKNOWN')
                    change.token_name = token_info.get('name', 'Unknown Token')
                    change.decimals = token_info.get('decimals', 9)
                    
                    if change.is_significant:
                        changes.append(change)
                        self._metrics['total_changes_detected'] += 1
            
            # Update stored balances
            with self._lock:
                self._wallet_balances[wallet_address] = current_balances
                self._last_scan_time[wallet_address] = get_current_timestamp()
            
            # Store changes in database
            if changes:
                self._store_balance_changes(changes)
            
            logger.info(f"🔍 Scanned {wallet_address}: {len(changes)} changes detected")
            
        except Exception as e:
            logger.error(f"❌ Error scanning balances for {wallet_address}: {e}")
        
        return changes
    
    def _get_current_token_accounts(self, wallet_address: str) -> List[str]:
        """Get all token accounts for a wallet (simplified implementation)"""
        # This would integrate with Solana RPC client
        # For now, return empty list for development
        return []
    
    def _get_current_balances(self, wallet_address: str, token_mints: List[str]) -> Dict[str, Decimal]:
        """Get current balances for token accounts"""
        # This would integrate with Solana RPC client
        # For now, return empty dict for development
        return {}
    
    def _get_token_info(self, token_mint: str) -> Dict[str, any]:
        """Get token metadata (simplified)"""
        if not self.db_manager:
            return {'symbol': 'UNKNOWN', 'name': 'Unknown Token', 'decimals': 9}
            
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT symbol, name, decimals FROM tokens WHERE address = ?",
                    (token_mint,)
                )
                result = cursor.fetchone()
                
                if result:
                    return {
                        'symbol': result[0],
                        'name': result[1],
                        'decimals': result[2]
                    }
                    
        except Exception as e:
            logger.error(f"❌ Error getting token info for {token_mint}: {e}")
            
        return {'symbol': 'UNKNOWN', 'name': 'Unknown Token', 'decimals': 9}
    
    def _store_balance_changes(self, changes: List[BalanceChange]) -> bool:
        """Store detected balance changes in database"""
        if not self.db_manager or not changes:
            return False
            
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Insert balance changes
                for change in changes:
                    cursor.execute("""
                        INSERT INTO wallet_balance_changes 
                        (wallet_address, token_mint, ata_pubkey, pre_balance, post_balance, 
                         balance_change, timestamp, token_symbol, token_name, decimals)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        change.wallet_address, change.token_mint, change.ata_pubkey,
                        str(change.pre_balance), str(change.post_balance),
                        str(change.balance_change), change.timestamp,
                        change.token_symbol, change.token_name, change.decimals
                    ))
                
                # Update token accounts
                for change in changes:
                    cursor.execute("""
                        INSERT OR REPLACE INTO token_accounts 
                        (wallet_address, token_mint, balance, last_updated)
                        VALUES (?, ?, ?, ?)
                    """, (
                        change.wallet_address, change.token_mint,
                        str(change.post_balance), change.timestamp
                    ))
                
                conn.commit()
                logger.info(f"💾 Stored {len(changes)} balance changes")
                return True
                
        except Exception as e:
            logger.error(f"❌ Error storing balance changes: {e}")
            return False
    
    def scan_all_wallets(self) -> Dict[str, List[BalanceChange]]:
        """Scan all tracked wallets for balance changes"""
        changes_by_wallet = {}
        
        with self._lock:
            wallets = list(self._wallet_balances.keys())
        
        for wallet in wallets:
            changes = self.scan_balance_changes(wallet)
            if changes:
                changes_by_wallet[wallet] = changes
        
        self._metrics['last_update'] = get_current_timestamp()
        
        logger.info(f"🔍 Scanned {len(wallets)} wallets, {sum(len(c) for c in changes_by_wallet.values())} total changes")
        
        return changes_by_wallet
    
    def get_wallet_summary(self, wallet_address: str) -> Dict[str, any]:
        """Get comprehensive wallet balance summary"""
        if wallet_address not in self._wallet_balances:
            return {}
        
        with self._lock:
            balances = self._wallet_balances[wallet_address]
            last_scan = self._last_scan_time.get(wallet_address, 0)
        
        # Calculate portfolio value
        total_value = Decimal('0')
        token_count = len(balances)
        active_tokens = sum(1 for b in balances.values() if b > 0)
        
        return {
            'wallet_address': wallet_address,
            'total_tokens': token_count,
            'active_tokens': active_tokens,
            'last_scan_time': last_scan,
            'hours_since_scan': safe_divide(get_current_timestamp() - last_scan, 3600),
            'balances': {mint: str(balance) for mint, balance in balances.items()},
            'total_value': str(total_value)  # Placeholder for USD value calculation
        }
    
    def get_system_metrics(self) -> Dict[str, any]:
        """Get system-wide tracking metrics"""
        with self._lock:
            metrics = self._metrics.copy()
            metrics['wallets_tracked'] = list(self._wallet_balances.keys())
            metrics['uptime_hours'] = safe_divide(get_current_timestamp() - metrics.get('start_time', 0), 3600)
        
        return metrics
    
    def get_recent_changes(self, wallet_address: str = None, limit: int = 50) -> List[BalanceChange]:
        """Get recent balance changes (from memory or database)"""
        if not self.db_manager:
            # Return from pending changes
            with self._lock:
                return self._pending_changes[-limit:] if limit else self._pending_changes
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                query = """
                    SELECT * FROM wallet_balance_changes
                    WHERE 1=1
                """
                params = []
                
                if wallet_address:
                    query += " AND wallet_address = ?"
                    params.append(wallet_address)
                
                query += " ORDER BY timestamp DESC LIMIT ?"
                params.append(limit)
                
                cursor.execute(query, params)
                results = cursor.fetchall()
                
                changes = []
                for row in results:
                    changes.append(BalanceChange(
                        wallet_address=row['wallet_address'],
                        token_mint=row['token_mint'],
                        ata_pubkey=row['ata_pubkey'],
                        pre_balance=Decimal(str(row['pre_balance'])),
                        post_balance=Decimal(str(row['post_balance'])),
                        balance_change=Decimal(str(row['balance_change'])),
                        timestamp=row['timestamp'],
                        token_symbol=row['token_symbol'],
                        token_name=row['token_name'],
                        decimals=row['decimals']
                    ))
                
                return changes
                
        except Exception as e:
            logger.error(f"❌ Error getting recent changes: {e}")
            return []

class BalanceTrackerManager:
    """
    Global manager for the balance tracker system
    Implements singleton pattern and thread-safe operations
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized') or not self._initialized:
            self.tracker = BalanceTracker()
            self._initialized = True
            logger.info("🎯 Balance tracker manager initialized")
    
    def start_tracking(self, wallet_addresses: List[str]) -> Dict[str, bool]:
        """Start tracking multiple wallets"""
        results = {}
        for address in wallet_addresses:
            results[address] = self.tracker.track_wallet(address)
        return results
    
    def stop_tracking(self, wallet_addresses: List[str]) -> Dict[str, bool]:
        """Stop tracking multiple wallets"""
        results = {}
        for address in wallet_addresses:
            results[address] = self.tracker.untrack_wallet(address)
        return results
    
    def scan_all(self) -> Dict[str, List[BalanceChange]]:
        """Scan all tracked wallets"""
        return self.tracker.scan_all_wallets()
    
    def get_summary(self) -> Dict[str, any]:
        """Get system summary"""
        return {
            'metrics': self.tracker.get_system_metrics(),
            'recent_changes': self.tracker.get_recent_changes(limit=10)
        }

# Global instance
_balance_tracker = None

def get_balance_tracker() -> BalanceTracker:
    """Get global balance tracker instance"""
    global _balance_tracker
    if _balance_tracker is None:
        _balance_tracker = BalanceTracker()
    return _balance_tracker

def get_balance_tracker_manager() -> BalanceTrackerManager:
    """Get global balance tracker manager"""
    return BalanceTrackerManager()

# Development testing
if __name__ == "__main__":
    logger.info("🧪 Testing Balance Tracker...")
    
    # Test basic functionality
    tracker = get_balance_tracker()
    
    # Test wallet tracking
    test_wallet = "4DdrfGHGdMjCqVbNtXsEEGL1SryTeMo8KMGWWtZyZVFh"
    tracker.track_wallet(test_wallet)
    
    # Test summary
    summary = tracker.get_wallet_summary(test_wallet)
    logger.info(f"📊 Wallet summary: {summary}")
    
    # Test system metrics
    metrics = tracker.get_system_metrics()
    logger.info(f"📈 System metrics: {metrics}")
    
    logger.info("✅ Balance tracker test completed")