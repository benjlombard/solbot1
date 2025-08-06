
"""
Solana Wallet Monitor - Wallet Scanner Module
Advanced scanning engine for discovering tokens and transactions in Solana wallets
"""

import time
import threading
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

# Core imports with fallbacks
try:
    from core.logger import get_logger
    from core.database import get_database_manager
    from core.config import get_config
    from core.exceptions import MonitoringError
    
    from models.token import Token, TokenAccount, TokenDiscovery
    from models.transaction import Transaction, TransactionType, TransactionStatus
    from models.wallet import WalletStats
    
    from utils.helpers import get_current_timestamp, safe_divide
    from utils.validators import validate_wallet_address
    
    # RPC imports
    from rpc.client import get_rpc_client
    from rpc.batch_manager import create_batch_manager
    
except ImportError as e:
    # Fallback implementations for development
    import logging
    def get_logger(name=None):
        return logging.getLogger(name or 'wallet_scanner')
    
    def get_database_manager(): return None
    def get_config(): return None
    def get_rpc_client(): return None
    
    def validate_wallet_address(addr): return len(addr) == 44

# Logger
logger = get_logger(__name__)

@dataclass
class ScanBatch:
    """Batch of accounts to scan efficiently"""
    wallet_address: str
    accounts: List[str]
    scan_type: str
    priority: int = 5
    created_at: int = field(default_factory=get_current_timestamp)

@dataclass
class ScanResult:
    """Complete scan results for a wallet"""
    wallet_address: str
    scan_type: str
    total_accounts: int
    new_accounts: int
    scan_duration: float
    tokens_discovered: List[TokenDiscovery]
    transactions_found: List[Transaction]
    balances_updated: List[Dict[str, Any]]
    completed_at: int = field(default_factory=get_current_timestamp)
    success: bool = True
    error_message: Optional[str] = None

@dataclass
class TokenAccountInfo:
    """Detailed token account information"""
    ata_pubkey: str
    token_mint: str
    owner: str
    balance: int
    decimals: int
    token_symbol: str
    token_name: str
    is_frozen: bool = False
    is_native: bool = False
    rent_exempt_reserve: int = 0

class WalletScanner:
    """
    Advanced wallet scanner for Solana
    Discovers tokens, transactions, and balance changes across wallets
    """
    
    def __init__(self):
        self.config = get_config()
        self.db_manager = get_database_manager()
        self.rpc_client = get_rpc_client()
        
        # Thread-safe operations
        self._lock = threading.Lock()
        self._active_scans: Dict[str, int] = {}
        self._scan_cache: Dict[str, Dict] = {}
        self._cache_timeout = 300  # 5 minutes
        
        # Configuration
        self.BATCH_SIZE = 100
        self.MAX_RETRIES = 3
        self.SCAN_TIMEOUT = 30
        self.RATE_LIMIT_DELAY = 0.1
        
        # Initialize batch manager
        self.batch_manager = None
        self._initialize_batch_manager()
        
        logger.info("🔍 Wallet scanner initialized")
    
    def _initialize_batch_manager(self):
        """Initialize batch manager for efficient RPC calls"""
        try:
            if self.rpc_client:
                from rpc.batch_manager import create_batch_config
                batch_config = create_batch_config()
                self.batch_manager = create_batch_manager(batch_config, self.rpc_client)
                logger.info("✅ Batch manager initialized")
            else:
                logger.warning("⚠️ RPC client not available, batch manager disabled")
                
        except Exception as e:
            logger.warning(f"⚠️ Could not initialize batch manager: {e}")
    
    def scan_wallet(self, wallet_address: str, scan_type: str = "full") -> Dict[str, Any]:
        """
        Comprehensive wallet scan
        Args:
            wallet_address: Solana wallet address
            scan_type: "full", "quick", "balances", "tokens"
        Returns:
            Dictionary with scan results
        """
        try:
            if not validate_wallet_address(wallet_address):
                raise ValueError(f"Invalid wallet address: {wallet_address}")
            
            scan_start = get_current_timestamp()
            
            with self._lock:
                if wallet_address in self._active_scans:
                    logger.warning(f"⚠️ Scan already in progress for {wallet_address}")
                    return {"error": "Scan already in progress"}
                
                self._active_scans[wallet_address] = scan_start
            
            logger.info(f"🔍 Starting {scan_type} scan for {wallet_address}")
            
            # Check cache
            if self._should_use_cache(wallet_address, scan_type):
                cached_result = self._get_cached_result(wallet_address, scan_type)
                if cached_result:
                    logger.info(f"🎯 Using cached results for {wallet_address}")
                    return cached_result
            
            # Perform scan based on type
            if scan_type == "full":
                result = self._perform_full_scan(wallet_address)
            elif scan_type == "quick":
                result = self._perform_quick_scan(wallet_address)
            elif scan_type == "balances":
                result = self._perform_balance_scan(wallet_address)
            elif scan_type == "tokens":
                result = self._perform_token_scan(wallet_address)
            else:
                result = self._perform_full_scan(wallet_address)
            
            # Cache results
            self._cache_result(wallet_address, scan_type, result)
            
            # Clean up
            with self._lock:
                self._active_scans.pop(wallet_address, None)
            
            logger.info(f"✅ Scan completed for {wallet_address}: {len(result.get('tokens_discovered', []))} tokens, {len(result.get('transactions_found', []))} transactions")
            
            return result
            
        except Exception as e:
            with self._lock:
                self._active_scans.pop(wallet_address, None)
            
            logger.error(f"❌ Scan failed for {wallet_address}: {e}")
            return {
                "wallet_address": wallet_address,
                "success": False,
                "error_message": str(e),
                "scan_duration": 0
            }
    
    def _perform_full_scan(self, wallet_address: str) -> Dict[str, Any]:
        """Perform comprehensive wallet scan"""
        scan_start = time.time()
        
        try:
            # Step 1: Get token accounts
            token_accounts = self._get_token_accounts(wallet_address)
            
            # Step 2: Get transactions
            transactions = self._get_recent_transactions(wallet_address)
            
            # Step 3: Process token information
            tokens_discovered = self._process_token_accounts(wallet_address, token_accounts)
            
            # Step 4: Process transactions
            transactions_processed = self._process_transactions(wallet_address, transactions)
            
            # Step 5: Update balances
            balances_updated = self._update_balances(wallet_address, token_accounts)
            
            scan_duration = time.time() - scan_start
            
            return {
                "wallet_address": wallet_address,
                "scan_type": "full",
                "total_accounts": len(token_accounts),
                "new_accounts": len([t for t in tokens_discovered if t.discovery_method == "new_scan"]),
                "scan_duration": scan_duration,
                "tokens_discovered": tokens_discovered,
                "transactions_found": transactions_processed,
                "balances_updated": balances_updated,
                "completed_at": get_current_timestamp(),
                "success": True
            }
            
        except Exception as e:
            scan_duration = time.time() - scan_start
            return {
                "wallet_address": wallet_address,
                "scan_type": "full",
                "scan_duration": scan_duration,
                "success": False,
                "error_message": str(e)
            }
    
    def _get_token_accounts(self, wallet_address: str) -> List[TokenAccountInfo]:
        """Get all token accounts for a wallet"""
        token_accounts = []
        
        try:
            if self.batch_manager:
                # Use batch manager for efficiency
                result = self._get_token_accounts_batch(wallet_address)
            else:
                # Fallback to direct RPC calls
                result = self._get_token_accounts_direct(wallet_address)
            
            # Process accounts
            for account_info in result:
                token_accounts.append(account_info)
                
        except Exception as e:
            logger.error(f"❌ Error getting token accounts for {wallet_address}: {e}")
        
        return token_accounts
    
    def _get_token_accounts_batch(self, wallet_address: str) -> List[TokenAccountInfo]:
        """Get token accounts using batch manager"""
        try:
            # Get token accounts via RPC
            if not self.rpc_client:
                return []
            
            # Get token accounts by owner
            response = self.rpc_client.call(
                "getTokenAccountsByOwner",
                [wallet_address, {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}, {"encoding": "jsonParsed"}]
            )
            
            accounts = []
            if response and 'result' in response and 'value' in response['result']:
                for account_data in response['result']['value']:
                    account_info = account_data['account']
                    pubkey = account_data['pubkey']
                    
                    if account_info and 'data' in account_info and 'parsed' in account_info['data']:
                        parsed = account_info['data']['parsed']
                        
                        if parsed['type'] == 'account':
                            info = parsed['info']
                            
                            accounts.append(TokenAccountInfo(
                                ata_pubkey=pubkey,
                                token_mint=info['mint'],
                                owner=info['owner'],
                                balance=int(info['tokenAmount']['amount']),
                                decimals=int(info['tokenAmount']['decimals']),
                                token_symbol=info.get('tokenAmount', {}).get('uiAmountString', '0'),
                                token_name="Unknown Token",
                                is_frozen=info.get('state') == 'frozen',
                                is_native=info.get('isNative', False),
                                rent_exempt_reserve=int(info.get('rentExemptReserve', 0))
                            ))
            
            return accounts
            
        except Exception as e:
            logger.error(f"❌ Error in batch token accounts: {e}")
            return []
    
    def _get_token_accounts_direct(self, wallet_address: str) -> List[TokenAccountInfo]:
        """Get token accounts via direct RPC calls"""
        # Simplified implementation for development
        return []
    
    def _get_recent_transactions(self, wallet_address: str) -> List[Dict[str, Any]]:
        """Get recent transactions for a wallet"""
        transactions = []
        
        try:
            # Get recent signatures
            response = self.rpc_client.call(
                "getSignaturesForAddress",
                [wallet_address, {"limit": 50}]
            )
            
            if response and 'result' in response:
                signatures = [sig['signature'] for sig in response['result'][:20]]  # Limit to 20
                
                # Get transaction details
                for signature in signatures:
                    tx_response = self.rpc_client.call(
                        "getTransaction",
                        [signature, {"encoding": "json", "maxSupportedTransactionVersion": 0}]
                    )
                    
                    if tx_response and 'result' in tx_response and tx_response['result']:
                        transactions.append({
                            'signature': signature,
                            'transaction': tx_response['result']
                        })
            
        except Exception as e:
            logger.error(f"❌ Error getting transactions for {wallet_address}: {e}")
        
        return transactions
    
    def _process_token_accounts(self, wallet_address: str, accounts: List[TokenAccountInfo]) -> List[TokenDiscovery]:
        """Process token accounts and discover new tokens"""
        discoveries = []
        
        try:
            # Get existing tokens from database
            existing_mints = self._get_existing_tokens(wallet_address)
            
            for account in accounts:
                if account.token_mint not in existing_mints:
                    # Create discovery record
                    discovery = TokenDiscovery(
                        token_mint=account.token_mint,
                        wallet_address=wallet_address,
                        discovered_at=get_current_timestamp(),
                        ata_pubkey=account.ata_pubkey,
                        initial_balance=safe_divide(account.balance, 10**account.decimals),
                        decimals=account.decimals,
                        symbol=account.token_symbol,
                        name=account.token_name,
                        discovery_method="balance_scan",
                        confidence_score=1.0
                    )
                    
                    discoveries.append(discovery)
                    
                    # Store discovery
                    self._store_discovery(discovery)
        
        except Exception as e:
            logger.error(f"❌ Error processing token accounts: {e}")
        
        return discoveries
    
    def _process_transactions(self, wallet_address: str, transactions: List[Dict[str, Any]]) -> List[Transaction]:
        """Process transactions and create transaction records"""
        processed_transactions = []
        
        try:
            for tx_data in transactions:
                transaction = self._parse_transaction(wallet_address, tx_data)
                if transaction:
                    processed_transactions.append(transaction)
                    self._store_transaction(transaction)
        
        except Exception as e:
            logger.error(f"❌ Error processing transactions: {e}")
        
        return processed_transactions
    
    def _parse_transaction(self, wallet_address: str, tx_data: Dict[str, Any]) -> Optional[Transaction]:
        """Parse transaction data into Transaction model"""
        try:
            if not tx_data['transaction']:
                return None
            
            tx = tx_data['transaction']
            signature = tx_data['signature']
            
            # Extract basic info
            slot = tx.get('slot', 0)
            block_time = tx.get('blockTime', 0)
            
            # Parse transaction details
            meta = tx.get('meta', {})
            transaction = tx.get('transaction', {})
            
            # Calculate amounts and fees
            amount = 0.0
            fee = float(meta.get('fee', 0)) / 1_000_000_000  # Convert lamports to SOL
            
            # Determine transaction type
            tx_type = TransactionType.TRANSFER
            
            # Create transaction record
            transaction_obj = Transaction(
                signature=signature,
                wallet_address=wallet_address,
                slot=slot,
                block_time=block_time,
                amount=amount,
                fee=fee,
                transaction_type=tx_type,
                status=TransactionStatus.SUCCESS if not meta.get('err') else TransactionStatus.FAILED,
                source="wallet_scanner"
            )
            
            return transaction_obj
            
        except Exception as e:
            logger.error(f"❌ Error parsing transaction {signature}: {e}")
            return None
    
    def _update_balances(self, wallet_address: str, accounts: List[TokenAccountInfo]) -> List[Dict[str, Any]]:
        """Update wallet balance information"""
        updated_balances = []
        
        try:
            for account in accounts:
                balance_info = {
                    'wallet_address': wallet_address,
                    'token_mint': account.token_mint,
                    'balance': safe_divide(account.balance, 10**account.decimals),
                    'decimals': account.decimals,
                    'updated_at': get_current_timestamp()
                }
                
                updated_balances.append(balance_info)
                
                # Store balance update
                self._store_balance_update(balance_info)
        
        except Exception as e:
            logger.error(f"❌ Error updating balances: {e}")
        
        return updated_balances
    
    def _perform_quick_scan(self, wallet_address: str) -> Dict[str, Any]:
        """Perform quick wallet scan (balances only)"""
        scan_start = time.time()
        
        try:
            # Get balances only
            token_accounts = self._get_token_accounts(wallet_address)
            
            scan_duration = time.time() - scan_start
            
            return {
                "wallet_address": wallet_address,
                "scan_type": "quick",
                "total_accounts": len(token_accounts),
                "new_accounts": 0,
                "scan_duration": scan_duration,
                "tokens_discovered": [],
                "transactions_found": [],
                "balances_updated": self._update_balances(wallet_address, token_accounts),
                "completed_at": get_current_timestamp(),
                "success": True
            }
            
        except Exception as e:
            scan_duration = time.time() - scan_start
            return {
                "wallet_address": wallet_address,
                "scan_type": "quick",
                "scan_duration": scan_duration,
                "success": False,
                "error_message": str(e)
            }
    
    def _perform_balance_scan(self, wallet_address: str) -> Dict[str, Any]:
        """Perform balance-focused scan"""
        return self._perform_quick_scan(wallet_address)
    
    def _perform_token_scan(self, wallet_address: str) -> Dict[str, Any]:
        """Perform token-focused scan"""
        scan_start = time.time()
        
        try:
            # Get token accounts
            token_accounts = self._get_token_accounts(wallet_address)
            
            # Process for discoveries
            discoveries = self._process_token_accounts(wallet_address, token_accounts)
            
            scan_duration = time.time() - scan_start
            
            return {
                "wallet_address": wallet_address,
                "scan_type": "tokens",
                "total_accounts": len(token_accounts),
                "new_accounts": len(discoveries),
                "scan_duration": scan_duration,
                "tokens_discovered": discoveries,
                "transactions_found": [],
                "balances_updated": [],
                "completed_at": get_current_timestamp(),
                "success": True
            }
            
        except Exception as e:
            scan_duration = time.time() - scan_start
            return {
                "wallet_address": wallet_address,
                "scan_type": "tokens",
                "scan_duration": scan_duration,
                "success": False,
                "error_message": str(e)
            }
    
    def _get_existing_tokens(self, wallet_address: str) -> Set[str]:
        """Get existing token mints for a wallet"""
        existing_mints = set()
        
        try:
            if not self.db_manager:
                return existing_mints
            
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT token_mint FROM token_accounts
                    WHERE wallet_address = ?
                """, (wallet_address,))
                
                for row in cursor.fetchall():
                    existing_mints.add(row['token_mint'])
        
        except Exception as e:
            logger.error(f"❌ Error getting existing tokens: {e}")
        
        return existing_mints
    
    def _store_discovery(self, discovery: TokenDiscovery) -> bool:
        """Store token discovery in database"""
        if not self.db_manager:
            return True
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO token_discoveries 
                    (token_mint, wallet_address, discovered_at, ata_pubkey, 
                     initial_balance, decimals, symbol, name, discovery_method, confidence_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    discovery.token_mint,
                    discovery.wallet_address,
                    discovery.discovered_at,
                    discovery.ata_pubkey,
                    str(discovery.initial_balance),
                    discovery.decimals,
                    discovery.symbol,
                    discovery.name,
                    discovery.discovery_method,
                    discovery.confidence_score
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"❌ Error storing discovery: {e}")
            return False
    
    def _store_transaction(self, transaction: Transaction) -> bool:
        """Store transaction in database"""
        if not self.db_manager:
            return True
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO transactions 
                    (signature, wallet_address, slot, block_time, amount, fee, 
                     token_mint, token_symbol, token_name, token_amount, 
                     price_per_token, transaction_type, status, source, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    transaction.signature,
                    transaction.wallet_address,
                    transaction.slot,
                    transaction.block_time,
                    transaction.amount,
                    transaction.fee,
                    transaction.token_mint,
                    transaction.token_symbol,
                    transaction.token_name,
                    transaction.token_amount,
                    transaction.price_per_token,
                    str(transaction.transaction_type),
                    str(transaction.status),
                    transaction.source,
                    transaction.created_at
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"❌ Error storing transaction: {e}")
            return False
    
    def _store_balance_update(self, balance_info: Dict[str, Any]) -> bool:
        """Store balance update in database"""
        if not self.db_manager:
            return True
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO token_accounts 
                    (wallet_address, token_mint, balance, decimals, last_updated)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    balance_info['wallet_address'],
                    balance_info['token_mint'],
                    str(balance_info['balance']),
                    balance_info['decimals'],
                    balance_info['updated_at']
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"❌ Error storing balance update: {e}")
            return False
    
    def _should_use_cache(self, wallet_address: str, scan_type: str) -> bool:
        """Check if cached results should be used"""
        cache_key = f"{wallet_address}:{scan_type}"
        
        with self._lock:
            if cache_key in self._scan_cache:
                cached_time = self._scan_cache[cache_key].get('cached_at', 0)
                if get_current_timestamp() - cached_time < self._cache_timeout:
                    return True
        
        return False
    
    def _get_cached_result(self, wallet_address: str, scan_type: str) -> Optional[Dict[str, Any]]:
        """Get cached scan results"""
        cache_key = f"{wallet_address}:{scan_type}"
        
        with self._lock:
            if cache_key in self._scan_cache:
                return self._scan_cache[cache_key]
        
        return None
    
    def _cache_result(self, wallet_address: str, scan_type: str, result: Dict[str, Any]):
        """Cache scan results"""
        cache_key = f"{wallet_address}:{scan_type}"
        
        with self._lock:
            self._scan_cache[cache_key] = {
                **result,
                'cached_at': get_current_timestamp()
            }
    
    def get_scan_status(self) -> Dict[str, Any]:
        """Get current scanning status"""
        with self._lock:
            return {
                'active_scans': len(self._active_scans),
                'cache_size': len(self._scan_cache),
                'batch_manager_available': self.batch_manager is not None,
                'rpc_client_available': self.rpc_client is not None
            }
    
    def get_scanning_history(self, wallet_address: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get scanning history for a wallet"""
        if not self.db_manager:
            return []
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM scan_history
                    WHERE wallet_address = ?
                    ORDER BY completed_at DESC
                    LIMIT ?
                """, (wallet_address, limit))
                
                return [dict(row) for row in cursor.fetchall()]
                
        except Exception as e:
            logger.error(f"❌ Error getting scanning history: {e}")
            return []
    
    def cleanup_cache(self) -> int:
        """Clean expired cache entries"""
        removed = 0
        current_time = get_current_timestamp()
        
        with self._lock:
            expired_keys = [
                key for key, value in self._scan_cache.items()
                if current_time - value.get('cached_at', 0) > self._cache_timeout
            ]
            
            for key in expired_keys:
                del self._scan_cache[key]
                removed += 1
        
        logger.info(f"🧹 Cleaned {removed} expired cache entries")
        return removed

# Global instance
_scanner = None

def get_wallet_scanner() -> WalletScanner:
    """Get global wallet scanner instance"""
    global _scanner
    
    if _scanner is None:
        _scanner = WalletScanner()
    
    return _scanner

# Convenience functions
def scan_wallet(wallet_address: str, scan_type: str = "full") -> Dict[str, Any]:
    """Scan a wallet using global scanner"""
    return get_wallet_scanner().scan_wallet(wallet_address, scan_type)

def scan_multiple_wallets(wallet_addresses: List[str]) -> Dict[str, Dict[str, Any]]:
    """Scan multiple wallets"""
    scanner = get_wallet_scanner()
    results = {}
    
    for wallet in wallet_addresses:
        results[wallet] = scanner.scan_wallet(wallet)
    
    return results

# Development testing
if __name__ == "__main__":
    logger.info("🧪 Testing Wallet Scanner...")
    
    # Create test instance
    scanner = get_wallet_scanner()
    
    # Test with sample wallet
    test_wallet = "4DdrfGHGdMjCqVbNtXsEEGL1SryTeMo8KMGWWtZyZVFh"
    
    # Test different scan types
    scan_types = ["full", "quick", "tokens", "balances"]
    
    for scan_type in scan_types:
        logger.info(f"🔍 Testing {scan_type} scan...")
        result = scanner.scan_wallet(test_wallet, scan_type)
        logger.info(f"📊 {scan_type} scan result: {len(result.get('tokens_discovered', []))} tokens, {len(result.get('transactions_found', []))} transactions")
    
    # Test cache
    scanner.cleanup_cache()
    
    logger.info("✅ Scanner test completed")