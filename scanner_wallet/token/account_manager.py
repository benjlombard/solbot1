"""
Solana Wallet Monitor - Token Account Manager
Manages Associated Token Accounts (ATA) and token operations for Solana wallets
"""

import re
import time
import sqlite3
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass, field
from decimal import Decimal
from collections import defaultdict
import logging

# Core imports with fallbacks
try:
    from core.logger import get_logger
    from core.database import get_database_manager
    from core.config import get_config
    from models.token import Token, TokenAccount, TokenDiscovery
    from models.transaction import TransactionType
    from utils.helpers import get_current_timestamp, safe_divide
    from utils.validators import quick_validate_address as validate_token_mint
    from utils.validators import quick_validate_address as validate_wallet_address
    from constants import DEFAULT_RPC_ENDPOINTS, TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID
except ImportError as e:
    # Fallback implementations
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - fallback - %(message)s')
    def get_logger(name=None):
        logger = logging.getLogger(name or 'account_manager')
        logger.warning("Using fallback logger due to ImportError: %s", e)
        return logger
    
    def get_database_manager(): return None
    def get_config(): return None
    
   def validate_wallet_address(addr):
        logging.getLogger('account_manager').warning("Using fallback address validator for %s", addr)
        return bool(addr and len(addr) == 44)
    def validate_token_mint(mint):
        logging.getLogger('account_manager').warning("Using fallback mint validator for %s", mint)
        return bool(mint and len(mint) == 44)
    def get_current_timestamp(): return int(time.time())
    def safe_divide(a, b, default=0): return a/b if b else default
    
    TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
    ASSOCIATED_TOKEN_PROGRAM_ID = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"

logger = get_logger(__name__)

class TokenAccountManager:
    """
    Manages token accounts (ATA) for Solana wallets
    Handles discovery, balance tracking, and account lifecycle
    """
    
    def __init__(self):
        self.config = get_config()
        self.db_manager = get_database_manager()
        
        # Cache for performance
        self._mint_cache: Dict[str, Token] = {}
        self._account_cache: Dict[str, List[TokenAccount]] = {}
        self._cache_expiry = 300  # 5 minutes
        
        logger.info("✅ Token Account Manager initialized")
    
    def discover_token_accounts(self, wallet_address: str) -> List[TokenAccount]:
        """
        Discover all token accounts for a wallet
        Args:
            wallet_address: Solana wallet address
        Returns:
            List of TokenAccount objects
        """
        if not validate_wallet_address(wallet_address):
            raise ValueError(f"Invalid wallet address: {wallet_address}")
        
        logger.info(f"🔍 Discovering token accounts for wallet: {wallet_address[:8]}...")
        
        try:
            # Check cache first
            cache_key = wallet_address
            if cache_key in self._account_cache:
                cached_accounts = self._account_cache[cache_key]
                if get_current_timestamp() - cached_accounts[0].last_updated < self._cache_expiry:
                    logger.debug("📦 Using cached token accounts")
                    return cached_accounts
            
            # Query database for existing accounts
            accounts = self._query_existing_accounts(wallet_address)
            
            # Discover new accounts if database is empty or outdated
            if not accounts:
                accounts = self._discover_new_accounts(wallet_address)
            
            # Cache results
            self._account_cache[cache_key] = accounts
            
            logger.info(f"✅ Discovered {len(accounts)} token accounts")
            return accounts
            
        except Exception as e:
            logger.error(f"❌ Error discovering token accounts: {e}")
            return []
    
    def _query_existing_accounts(self, wallet_address: str) -> List[TokenAccount]:
        """Query existing token accounts from database"""
        if not self.db_manager:
            return []
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT 
                        wallet_address,
                        ata_pubkey,
                        token_mint,
                        balance,
                        decimals,
                        first_seen,
                        last_updated,
                        last_scanned,
                        is_active,
                        scan_priority,
                        activity_score,
                        last_activity_time,
                        total_transactions
                    FROM token_accounts
                    WHERE wallet_address = ? AND is_active = 1
                    ORDER BY scan_priority DESC, last_activity_time DESC
                """, (wallet_address,))
                
                accounts = []
                for row in cursor.fetchall():
                    account = TokenAccount(
                        wallet_address=row['wallet_address'],
                        ata_pubkey=row['ata_pubkey'],
                        token_mint=row['token_mint'],
                        balance=float(row['balance']),
                        decimals=int(row['decimals']),
                        first_seen=int(row['first_seen']),
                        last_updated=int(row['last_updated']),
                        last_scanned=int(row['last_scanned']) if row['last_scanned'] else None,
                        is_active=bool(row['is_active']),
                        scan_priority=int(row['scan_priority']),
                        activity_score=float(row['activity_score']),
                        last_activity_time=int(row['last_activity_time']) if row['last_activity_time'] else None,
                        total_transactions=int(row['total_transactions'])
                    )
                    accounts.append(account)
                
                return accounts
                
        except Exception as e:
            logger.error(f"❌ Error querying existing accounts: {e}")
            return []
    
    def _discover_new_accounts(self, wallet_address: str) -> List[TokenAccount]:
        """Discover new token accounts for wallet"""
        # This would typically query the blockchain
        # For now, simulate discovery or return empty
        logger.info("📊 Simulating token account discovery...")
        return []
    
    def create_or_update_token_account(self, wallet_address: str, token_mint: str, 
                                     ata_pubkey: str, balance: float = 0.0, 
                                     decimals: int = 9) -> TokenAccount:
        """
        Create or update a token account
        Args:
            wallet_address: Owner wallet address
            token_mint: Token mint address
            ata_pubkey: Associated token account public key
            balance: Current balance
            decimals: Token decimals
        Returns:
            TokenAccount object
        """
        if not validate_wallet_address(wallet_address):
            raise ValueError("Invalid wallet address")
        if not validate_token_mint(token_mint):
            raise ValueError("Invalid token mint")
        
        current_time = get_current_timestamp()
        
        # Check if account already exists
        existing_account = self._get_account(wallet_address, token_mint)
        
        if existing_account:
            # Update existing account
            return self._update_account_balance(existing_account, balance)
        else:
            # Create new account
            account = TokenAccount(
                wallet_address=wallet_address,
                ata_pubkey=ata_pubkey,
                token_mint=token_mint,
                balance=balance,
                decimals=decimals,
                first_seen=current_time,
                last_updated=current_time,
                scan_priority=5,  # New accounts get high priority
                is_active=True
            )
            
            self._save_account(account)
            return account
    
    def _get_account(self, wallet_address: str, token_mint: str) -> Optional[TokenAccount]:
        """Get specific token account from database"""
        if not self.db_manager:
            return None
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM token_accounts
                    WHERE wallet_address = ? AND token_mint = ?
                """, (wallet_address, token_mint))
                
                row = cursor.fetchone()
                if row:
                    return TokenAccount(
                        wallet_address=row['wallet_address'],
                        ata_pubkey=row['ata_pubkey'],
                        token_mint=row['token_mint'],
                        balance=float(row['balance']),
                        decimals=int(row['decimals']),
                        first_seen=int(row['first_seen']),
                        last_updated=int(row['last_updated']),
                        last_scanned=int(row['last_scanned']) if row['last_scanned'] else None,
                        is_active=bool(row['is_active']),
                        scan_priority=int(row['scan_priority']),
                        activity_score=float(row['activity_score']),
                        last_activity_time=int(row['last_activity_time']) if row['last_activity_time'] else None,
                        total_transactions=int(row['total_transactions'])
                    )
                
        except Exception as e:
            logger.error(f"❌ Error getting account: {e}")
        
        return None
    
    def _save_account(self, account: TokenAccount) -> bool:
        """Save token account to database"""
        if not self.db_manager:
            return False
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO token_accounts (
                        wallet_address, ata_pubkey, token_mint, balance, decimals,
                        first_seen, last_updated, last_scanned, is_active,
                        scan_priority, activity_score, last_activity_time, total_transactions
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    account.wallet_address, account.ata_pubkey, account.token_mint,
                    account.balance, account.decimals, account.first_seen,
                    account.last_updated, account.last_scanned,
                    int(account.is_active), account.scan_priority,
                    account.activity_score, account.last_activity_time,
                    account.total_transactions
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"❌ Error saving account: {e}")
            return False
    
    def update_account_balance(self, wallet_address: str, token_mint: str, 
                             new_balance: float) -> bool:
        """Update account balance"""
        account = self._get_account(wallet_address, token_mint)
        if not account:
            return False
        
        return self._update_account_balance(account, new_balance)
    
    def _update_account_balance(self, account: TokenAccount, new_balance: float) -> bool:
        """Internal balance update"""
        account.balance = new_balance
        account.last_updated = get_current_timestamp()
        
        # Update activity score if balance changed significantly
        if abs(new_balance - account.balance) > 0.001:
            account.activity_score = min(10, account.activity_score + 0.5)
            account.last_activity_time = get_current_timestamp()
        
        return self._save_account(account)
    
    def mark_account_scanned(self, wallet_address: str, token_mint: str) -> bool:
        """Mark account as scanned, reducing priority"""
        account = self._get_account(wallet_address, token_mint)
        if not account:
            return False
        
        account.last_scanned = get_current_timestamp()
        account.scan_priority = max(1, account.scan_priority - 1)
        
        return self._save_account(account)
    
    def boost_account_priority(self, wallet_address: str, token_mint: str, 
                             reason: str = "activity") -> bool:
        """Increase account scan priority"""
        account = self._get_account(wallet_address, token_mint)
        if not account:
            return False
        
        if reason == "new_account":
            account.scan_priority = 5
        elif reason == "activity":
            account.scan_priority = min(4, account.scan_priority + 1)
        elif reason == "large_balance":
            account.scan_priority = min(4, account.scan_priority + 2)
        
        return self._save_account(account)
    
    def deactivate_account(self, wallet_address: str, token_mint: str) -> bool:
        """Deactivate a token account"""
        account = self._get_account(wallet_address, token_mint)
        if not account:
            return False
        
        account.is_active = False
        account.scan_priority = 0
        
        return self._save_account(account)
    
    def get_token_balance(self, wallet_address: str, token_mint: str) -> float:
        """Get token balance for specific account"""
        account = self._get_account(wallet_address, token_mint)
        return account.balance if account else 0.0
    
    def get_wallet_tokens(self, wallet_address: str, 
                         include_zero: bool = False) -> List[TokenAccount]:
        """Get all tokens for wallet"""
        accounts = self.discover_token_accounts(wallet_address)
        
        if not include_zero:
            accounts = [acc for acc in accounts if acc.balance > 0]
        
        return accounts
    
    def get_top_holdings(self, wallet_address: str, limit: int = 10) -> List[TokenAccount]:
        """Get top token holdings by value"""
        accounts = self.get_wallet_tokens(wallet_address, include_zero=False)
        
        # Sort by balance (would be USD value if prices available)
        accounts.sort(key=lambda x: x.balance, reverse=True)
        
        return accounts[:limit]
    
    def calculate_portfolio_value(self, wallet_address: str) -> Dict[str, Any]:
        """Calculate total portfolio value"""
        accounts = self.get_wallet_tokens(wallet_address, include_zero=False)
        
        total_value = 0.0
        token_values = {}
        
        for account in accounts:
            # This would use USD prices when available
            value = account.balance
            token_values[account.token_symbol] = value
            total_value += value
        
        return {
            'wallet_address': wallet_address,
            'total_value': total_value,
            'token_count': len(accounts),
            'token_values': token_values,
            'timestamp': get_current_timestamp()
        }
    
    def scan_for_new_tokens(self, wallet_address: str) -> List[TokenDiscovery]:
        """Scan for newly discovered tokens"""
        if not validate_wallet_address(wallet_address):
            return []
        
        logger.info(f"🔍 Scanning for new tokens in wallet: {wallet_address[:8]}...")
        
        # This would normally query blockchain
        # For now, return empty list or simulate discovery
        
        return []
    
    def get_account_activity(self, wallet_address: str, token_mint: str, 
                           limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent activity for specific token account"""
        if not self.db_manager:
            return []
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT 
                        t.signature,
                        t.transaction_type,
                        t.token_amount,
                        t.amount,
                        t.block_time,
                        t.fee
                    FROM transactions t
                    WHERE t.wallet_address = ?
                        AND t.token_mint = ?
                    ORDER BY t.block_time DESC
                    LIMIT ?
                """, (wallet_address, token_mint, limit))
                
                activity = []
                for row in cursor.fetchall():
                    activity.append({
                        'signature': row['signature'],
                        'type': row['transaction_type'],
                        'token_amount': float(row['token_amount']),
                        'sol_amount': float(row['amount']),
                        'timestamp': int(row['block_time']),
                        'fee': float(row['fee'])
                    })
                
                return activity
                
        except Exception as e:
            logger.error(f"❌ Error getting account activity: {e}")
            return []
    
    def get_scan_priority_list(self, wallet_address: str, limit: int = 20) -> List[TokenAccount]:
        """Get accounts ordered by scan priority"""
        accounts = self.discover_token_accounts(wallet_address)
        
        # Filter active accounts
        active_accounts = [acc for acc in accounts if acc.is_active]
        
        # Sort by priority (high to low), then by last activity
        active_accounts.sort(
            key=lambda x: (x.scan_priority, x.last_activity_time or 0),
            reverse=True
        )
        
        return active_accounts[:limit]
    
    def cleanup_inactive_accounts(self, wallet_address: str, 
                                inactivity_days: int = 30) -> int:
        """Clean up inactive token accounts"""
        if not self.db_manager:
            return 0
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cutoff_time = get_current_timestamp() - (inactivity_days * 24 * 3600)
                
                cursor.execute("""
                    UPDATE token_accounts
                    SET is_active = 0, scan_priority = 0
                    WHERE wallet_address = ?
                        AND balance = 0
                        AND last_activity_time < ?
                """, (wallet_address, cutoff_time))
                
                affected_rows = cursor.rowcount
                conn.commit()
                
                logger.info(f"🧹 Cleaned up {affected_rows} inactive accounts")
                return affected_rows
                
        except Exception as e:
            logger.error(f"❌ Error cleaning inactive accounts: {e}")
            return 0
    
    def export_token_data(self, wallet_address: str, 
                        format_type: str = 'json') -> Dict[str, Any]:
        """Export token data for wallet"""
        accounts = self.get_wallet_tokens(wallet_address)
        
        data = {
            'wallet_address': wallet_address,
            'timestamp': get_current_timestamp(),
            'total_accounts': len(accounts),
            'accounts': [acc.to_dict() for acc in accounts],
            'summary': {
                'total_tokens': len(accounts),
                'active_tokens': len([acc for acc in accounts if acc.is_active]),
                'total_balance': sum(acc.balance for acc in accounts),
                'average_priority': safe_divide(
                    sum(acc.scan_priority for acc in accounts), 
                    len(accounts)
                ) if accounts else 0
            }
        }
        
        return data
    
    def get_account_statistics(self, wallet_address: str) -> Dict[str, Any]:
        """Get detailed account statistics"""
        accounts = self.discover_token_accounts(wallet_address)
        
        if not accounts:
            return {
                'wallet_address': wallet_address,
                'total_accounts': 0,
                'message': 'No token accounts found'
            }
        
        # Calculate statistics
        active_accounts = [acc for acc in accounts if acc.is_active]
        balances = [acc.balance for acc in accounts]
        
        stats = {
            'wallet_address': wallet_address,
            'total_accounts': len(accounts),
            'active_accounts': len(active_accounts),
            'zero_balance_accounts': len([acc for acc in accounts if acc.balance == 0]),
            'total_balance': sum(balances),
            'average_balance': safe_divide(sum(balances), len(balances)),
            'min_balance': min(balances) if balances else 0,
            'max_balance': max(balances) if balances else 0,
            'average_priority': safe_divide(
                sum(acc.scan_priority for acc in accounts), 
                len(accounts)
            ),
            'average_activity_score': safe_divide(
                sum(acc.activity_score for acc in accounts), 
                len(accounts)
            ),
            'tokens_by_priority': defaultdict(int),
            'last_scan_time': max(acc.last_scanned or 0 for acc in accounts)
        }
        
        # Count by priority
        for account in accounts:
            stats['tokens_by_priority'][account.scan_priority] += 1
        
        # Convert defaultdict to regular dict
        stats['tokens_by_priority'] = dict(stats['tokens_by_priority'])
        
        return stats

# Fonctions utilitaires globales

def create_ata_address(wallet_address: str, mint_address: str) -> str:
    """Generate ATA address for wallet and mint"""
    # This would normally use Solana SDK
    # For now, return placeholder
    return f"ATA_{wallet_address[:6]}_{mint_address[:6]}"

def get_token_program_for_mint(mint_address: str) -> str:
    """Get token program ID for mint"""
    # Future: Support Token-2022
    return TOKEN_PROGRAM_ID

# Statistiques et monitoring
def get_system_token_stats() -> Dict[str, Any]:
    """Get global token system statistics"""
    manager = TokenAccountManager()
    
    if not manager.db_manager:
        return {'status': 'error', 'message': 'Database unavailable'}
    
    try:
        with manager.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Total statistics
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_accounts,
                    COUNT(DISTINCT wallet_address) as unique_wallets,
                    COUNT(DISTINCT token_mint) as unique_tokens,
                    SUM(balance) as total_balance,
                    AVG(balance) as avg_balance
                FROM token_accounts
                WHERE is_active = 1
            """)
            
            stats = dict(cursor.fetchone())
            
            # Top tokens by account count
            cursor.execute("""
                SELECT token_mint, COUNT(*) as account_count
                FROM token_accounts
                WHERE is_active = 1
                GROUP BY token_mint
                ORDER BY account_count DESC
                LIMIT 10
            """)
            
            stats['top_tokens'] = [dict(row) for row in cursor.fetchall()]
            
            return stats
            
    except Exception as e:
        return {'status': 'error', 'message': str(e)}

if __name__ == "__main__":
    # Test initialization
    manager = TokenAccountManager()
    print("✅ Token Account Manager initialized")
    
    # Test statistics
    stats = get_system_token_stats()
    print("📊 System token stats:", stats)