
"""
Solana Wallet Monitor - Wallet Scanner Module
Advanced scanning engine for discovering tokens and transactions in Solana wallets
"""

import time
import threading
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation, Context

# Core imports with fallbacks
try:
    from core.logger import get_logger
    from core.database import get_database_manager
    from core.config import get_config
    from core.exceptions import MonitoringError
    
    from models.token import Token, TokenAccount, TokenDiscovery
    from models.transaction import Transaction, TransactionType, TransactionStatus, classify_transaction_from_amounts
    from models.wallet import WalletStats
    
    from utils.helpers import get_current_timestamp, safe_divide
    from utils.validators import quick_validate_address as validate_wallet_address
    from utils.constants import SOLANA_TOKEN_PROGRAM_ID

    
    # RPC imports
    from rpc.client import get_default_rpc_client as get_rpc_client
    from rpc.batch_manager import create_batch_manager
    
except ImportError as e:
    # Fallback implementations for development
    import logging
    logging.warning(f"A core module import failed in scanner.py: {e}. Using fallback implementations.")

    def get_logger(name=None):
        logger = logging.getLogger(name or 'scanner')
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger
    
    def get_database_manager(): return None
    def get_config(): 
        class MockConfig:
            class rpc:
                quicknode_endpoint = None
        return MockConfig()
    def get_rpc_client(): return None
    def get_current_timestamp():
        import time
        return int(time.time())
    def safe_divide(a, b): return a/b if b != 0 else 0
    def validate_wallet_address(addr): return isinstance(addr, str) and len(addr) >= 32

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
        logger.debug(f"RPC endpoint from config: {self.config.rpc.quicknode_endpoint}")

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
        self.RECENT_TRANSACTIONS_LIMIT = 20
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
    
    def scan_wallet(self, wallet_address: str, scan_type: str = "full", is_initial_scan: bool = False) -> Dict[str, Any]:
        """
        Comprehensive wallet scan
        Args:
            wallet_address: Solana wallet address
            scan_type: "full", "quick", "balances", "tokens"
            is_initial_scan: If True, suppresses creation of discovery events to establish a baseline.
        Returns:
            Dictionary with scan results
        """
        try:
            if not validate_wallet_address(wallet_address):
                raise ValueError(f"Invalid wallet address: {wallet_address}")
            
            if self.rpc_client:
                logger.info(f"🌐 [RPC] RPC client available, endpoint: {getattr(self.config.rpc, 'quicknode_endpoint', 'Default')}")
            else:
                logger.warning(f"⚠️ [RPC] No RPC client available - using fallback mode")

            scan_start = get_current_timestamp()
            
            initial_qn_requests = self._get_quicknode_requests()

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
                result = self._perform_full_scan(wallet_address, is_initial_scan)
            elif scan_type == "quick":
                result = self._perform_quick_scan(wallet_address)
            elif scan_type == "balances":
                result = self._perform_balance_scan(wallet_address)
            elif scan_type == "tokens":
                result = self._perform_token_scan(wallet_address, is_initial_scan)
            else:
                result = self._perform_full_scan(wallet_address, is_initial_scan)
            
            # Cache results
            self._cache_result(wallet_address, scan_type, result)
            
            logger.info(f"✅ Scan completed for {wallet_address}: {len(result.get('tokens_discovered', []))} tokens, {len(result.get('transactions_found', []))} transactions")
            
            return result
            
        except Exception as e:
            
            logger.error(f"❌ Scan failed for {wallet_address}: {e}")
            return {
                "wallet_address": wallet_address,
                "success": False,
                "error_message": str(e),
                "scan_duration": 0
            }
        finally:
            # Log QuickNode API query count for the scan
            final_qn_requests = self._get_quicknode_requests()
            queries_for_scan = final_qn_requests - initial_qn_requests
            
            if queries_for_scan >= 0:
                with self._lock:
                    active_scans_count = len(self._active_scans)

                per_scan_msg = f"📊 QuickNode API queries for scan of {wallet_address}: {queries_for_scan}"
                total_msg = f"📊 Total QuickNode API queries since start: {final_qn_requests}"

                if active_scans_count > 1:
                    per_scan_msg += f" (Warning: {active_scans_count} scans were active, count may be shared)"
                    logger.warning(per_scan_msg)
                else:
                    logger.info(per_scan_msg)
                logger.info(total_msg)

            # This will always run, ensuring the lock is released.
            with self._lock:
                self._active_scans.pop(wallet_address, None)
                logger.debug(f"Scan lock released for {wallet_address}")
    
    def _perform_full_scan(self, wallet_address: str, is_initial_scan: bool = False) -> Dict[str, Any]:
        """Perform comprehensive wallet scan"""
        scan_start = time.time()
        
        try:
            # Step 1: Get token accounts
            token_accounts = self._get_token_accounts(wallet_address)
            
            # Step 2: Get transactions
            transactions = self._get_recent_transactions(wallet_address)
            
            # Step 3: Process token information
            tokens_discovered = self._process_token_accounts(wallet_address, token_accounts, is_initial_scan)
            
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
        logger.info(f"🔗 [RPC] Making getTokenAccountsByOwner call for {wallet_address}")
        try:
            # Get token accounts via RPC
            if not self.rpc_client:
                logger.error("❌ [RPC] No RPC client available!")
                return []
            
            # Get token accounts by owner
            response = self.rpc_client.call(
                "getTokenAccountsByOwner",
                [wallet_address, {"programId": SOLANA_TOKEN_PROGRAM_ID}, {"encoding": "jsonParsed"}]
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
                            
                            try:
                                token_amount_obj = info.get('tokenAmount')
                                if not isinstance(token_amount_obj, dict):
                                    logger.warning(f"Unexpected tokenAmount format for mint {info.get('mint')}: {token_amount_obj}")
                                    continue

                                balance_raw = token_amount_obj.get('amount')
                                decimals_raw = token_amount_obj.get('decimals')

                                # Validate types before casting
                                if not isinstance(balance_raw, (str, int, float)) or not isinstance(decimals_raw, (int, float)):
                                    logger.warning(f"Unexpected balance or decimals format for mint {info.get('mint')}. Balance: {balance_raw}, Decimals: {decimals_raw}")
                                    continue

                                accounts.append(TokenAccountInfo(
                                    ata_pubkey=pubkey,
                                    token_mint=info.get('mint'),
                                    owner=info.get('owner'),
                                    balance=int(balance_raw),
                                    decimals=int(decimals_raw),
                                    token_symbol=token_amount_obj.get('uiAmountString', '0'),
                                    token_name="Unknown Token",
                                    is_frozen=info.get('state') == 'frozen',
                                    is_native=info.get('isNative', False),
                                    rent_exempt_reserve=int(info.get('rentExemptReserve', 0))
                                ))
                            except (ValueError, TypeError, KeyError) as e:
                                logger.error(f"Could not parse token account info for mint {info.get('mint')}: {e}. Data: {info}", exc_info=True)
                                continue
            
            return accounts
            
        except Exception as e:
            logger.error(f"❌ Error in batch token accounts: {e}")
            return []
    
    def _get_token_accounts_direct(self, wallet_address: str) -> List[TokenAccountInfo]:
        """Get token accounts via direct RPC calls"""
        # Simplified implementation for development
        return []
    
    def _get_recent_transactions(self, wallet_address: str) -> List[Dict[str, Any]]:
        """Get recent transactions for a wallet using batch processing."""
        transactions = []
        
        try:
            # Step 1: Get recent signatures
            response = self.rpc_client.call(
                "getSignaturesForAddress",
                [wallet_address, {"limit": self.RECENT_TRANSACTIONS_LIMIT}]
            )
            
            if not (response and 'result' in response and response['result']):
                return []

            signatures = [sig['signature'] for sig in response['result']]
            
            # Step 2: Prepare batch request for getTransaction
            batch_requests = [
                {
                    "method": "getTransaction",
                    "params": [sig, {"encoding": "json", "maxSupportedTransactionVersion": 0}]
                }
                for sig in signatures
            ]
            
            # Step 3: Execute batch call
            logger.info(f"🔗 [RPC] Making batch getTransaction call for {len(signatures)} signatures.")
            batch_responses = self.rpc_client.batch_call(batch_requests)
            
            # Step 4: Process responses
            for i, tx_response in enumerate(batch_responses):
                if tx_response and 'result' in tx_response and tx_response['result']:
                    transactions.append({
                        'signature': signatures[i],
                        'transaction': tx_response['result']
                    })
                else:
                    logger.warning(f"Failed to fetch transaction details for signature: {signatures[i]}")

        except Exception as e:
            logger.error(f"❌ Error getting transactions for {wallet_address}: {e}", exc_info=True)
        
        return transactions
    
    def _process_token_accounts(self, wallet_address: str, accounts: List[TokenAccountInfo], is_initial_scan: bool = False) -> List[TokenDiscovery]:
        """Process token accounts and discover new tokens"""
        discoveries = []
        
        try:
            # Get existing tokens from database
            existing_mints = self._get_existing_tokens(wallet_address)
            
            for account in accounts:
                if account.token_mint not in existing_mints:
                    # For initial scans, we establish a baseline but don't create a "discovery" event.
                    if not is_initial_scan:
                        # Create discovery record only if it's not the first scan
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
        signature = tx_data.get('signature', 'N/A')
        try:
            logger.debug(f"Parsing transaction with signature: {signature}")
            tx = tx_data.get('transaction')
            if not tx:
                logger.warning(f"Transaction data missing for signature {signature}")
                return None

            meta = tx.get('meta', {})
            if not meta:
                logger.warning(f"Transaction meta data missing for signature {signature}")
                return None
            
            # Basic info
            slot = tx.get('slot', 0)
            block_time = tx.get('blockTime', 0)
            fee = meta.get('fee', 0) / 1_000_000_000  # Lamports to SOL
            status = TransactionStatus.SUCCESS if not meta.get('err') else TransactionStatus.FAILED

            # --- Balance Change Calculation ---
            account_keys = tx['transaction']['message']['accountKeys']

            
            # Find wallet's SOL balance change
            sol_change = 0.0
            try:
                wallet_index = account_keys.index(wallet_address)
                sol_pre = meta['preBalances'][wallet_index]
                sol_post = meta['postBalances'][wallet_index]
                sol_change = (sol_post - sol_pre) / 1_000_000_000
            except (ValueError, IndexError, KeyError) as e:
                logger.debug(f"Could not calculate SOL balance change for {signature}: {e}")

            # Find primary token balance change for the wallet
            token_change_details = self._find_primary_token_change(wallet_address, meta)

            if not token_change_details:
                logger.debug(f"No direct token balance change for wallet {wallet_address} in tx {signature}. Skipping as non-token-related for this wallet.")
                return None

            # Extract details from the identified token balance change
            token_mint = token_change_details['mint']
            token_change = token_change_details['uiTokenAmount']['uiAmount']
            decimals = token_change_details['uiTokenAmount']['decimals']
            
            # Use the helper from the model to classify the transaction
            tx_type = classify_transaction_from_amounts(token_change, sol_change)
            
            logger.info(f"Parsed transaction {signature}: Type={tx_type.value}, SOL Change={sol_change:.4f}, Token Change={token_change:.4f} ({token_mint})")

            
            # Create transaction record
            transaction_obj = Transaction(
                signature=signature,
                wallet_address=wallet_address,
                slot=slot,
                block_time=block_time,
                amount=sol_change,
                fee=fee,
                status=status,
                token_mint=token_mint,
                token_amount=abs(token_change),
                transaction_type=tx_type,
                is_token_transaction=True,
                source="wallet_scanner"
            )
            
            return transaction_obj
            
        except Exception as e:
            logger.error(f"❌ Error parsing transaction {signature}: {e}", exc_info=True)
            return None
    
    def _find_primary_token_change(self, wallet_address: str, meta: Dict[str, Any]) -> Optional[Dict]:
        """Find the most relevant token balance change for the specified wallet."""
        pre_token_balances = meta.get('preTokenBalances', [])
        post_token_balances = meta.get('postTokenBalances', [])

        all_changes = {}

        # Process pre-balances
        for balance in pre_token_balances:
            if balance.get('owner') == wallet_address:
                mint = balance.get('mint')
                if not mint: continue
                all_changes[mint] = {'pre': balance['uiTokenAmount']}

        # Process post-balances and calculate change
        for balance in post_token_balances:
            if balance.get('owner') == wallet_address:
                mint = balance.get('mint')
                if not mint: continue
                if mint not in all_changes:
                    all_changes[mint] = {}
                all_changes[mint]['post'] = balance['uiTokenAmount']
        
        # Find the change with the largest magnitude using Decimal for precision
        primary_change = None
        max_abs_change = Decimal('0.0')

        for mint, changes in all_changes.items():
            pre_balance_data = changes.get('pre')
            post_balance_data = changes.get('post')
            try:
                # Prefer uiAmountString for precision, fallback to uiAmount
                pre_amount_val = pre_balance_data.get('uiAmountString', pre_balance_data.get('uiAmount')) if pre_balance_data else '0'
                post_amount_val = post_balance_data.get('uiAmountString', post_balance_data.get('uiAmount')) if post_balance_data else '0'

                pre_amount = Decimal(str(pre_amount_val or '0'))
                post_amount = Decimal(str(post_amount_val or '0'))

                change = post_amount - pre_amount

            except (InvalidOperation, TypeError, KeyError) as e:
                logger.warning(f"Could not parse token amount as Decimal for mint {mint}: {e}")
                continue

            if abs(change) > max_abs_change:
                max_abs_change = abs(change)
                primary_change = {
                    'mint': mint,
                    'uiTokenAmount': {
                        # Convert back to float for compatibility with the rest of the system
                        'uiAmount': float(change),
                        'decimals': changes.get('post', changes.get('pre', {})).get('decimals', 9)
                    }
                }
        
        return primary_change

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
    
    def _perform_token_scan(self, wallet_address: str, is_initial_scan: bool = False) -> Dict[str, Any]:
        """Perform token-focused scan"""
        scan_start = time.time()
        
        try:
            # Get token accounts
            token_accounts = self._get_token_accounts(wallet_address)
            
            # Process for discoveries
            discoveries = self._process_token_accounts(wallet_address, token_accounts, is_initial_scan)
            
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
                    existing_mints.add(row[0])
        
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
                logger.debug(f"🐛 DEBUG: Storing balance for {balance_info}")
                ata_pubkey = balance_info.get('ata_pubkey', f"{balance_info['wallet_address']}:{balance_info['token_mint']}")

                cursor.execute("""
                    INSERT OR REPLACE INTO token_accounts 
                    (wallet_address, token_mint, ata_pubkey, balance, decimals, last_updated, first_seen)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    balance_info['wallet_address'],
                    balance_info['token_mint'],
                    ata_pubkey,  # ← This was missing!
                    str(balance_info['balance']),
                    balance_info['decimals'],
                    balance_info['updated_at'],
                    balance_info.get('first_seen', balance_info['updated_at'])
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
    
    def _get_quicknode_requests(self) -> int:
        """Helper to get current request count for QuickNode endpoint."""
        if not (self.rpc_client and hasattr(self.config, 'rpc') and self.config.rpc.quicknode_endpoint):
            return 0
            
        try:
            stats = self.rpc_client.get_stats()
            qn_endpoint = self.config.rpc.quicknode_endpoint
            
            if qn_endpoint and 'endpoints' in stats:
                for endpoint_stat in stats.get('endpoints', []):
                    # Direct comparison now that the full URL is available in stats
                    if qn_endpoint == endpoint_stat.get('url'):
                        return endpoint_stat.get('total_requests', 0)
        except Exception as e:
            logger.warning(f"Could not retrieve RPC stats for QuickNode request count: {e}")
            
        return 0
    
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
    logger.info("🧪 Testing Wallet Scanner.")
    
    # Create test instance
    scanner = get_wallet_scanner()
    
    # Test with sample wallet
    test_wallet = "4DdrfGHGdMjCqVbNtXsEEGL1SryTeMo8KMGWWtZyZVFh"
    
    # Test different scan types
    scan_types = ["full", "quick", "tokens", "balances"]
    
    for scan_type in scan_types:
        logger.info(f"🔍 Testing {scan_type} scan.")
        result = scanner.scan_wallet(test_wallet, scan_type)
        logger.info(f"📊 {scan_type} scan result: {len(result.get('tokens_discovered', []))} tokens, {len(result.get('transactions_found', []))} transactions")
    
    # Test cache
    scanner.cleanup_cache()
    
    logger.info("✅ Scanner test completed")