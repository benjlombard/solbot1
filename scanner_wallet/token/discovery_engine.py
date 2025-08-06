"""
Solana Wallet Monitor - Token Discovery Engine
Advanced engine for discovering new tokens and monitoring token changes
"""

import time
import json
import hashlib
import threading
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

# Core imports with fallbacks
try:
    from core.logger import get_logger
    from core.database import get_database_manager
    from core.config import get_config
    from models.token import Token, TokenAccount, TokenDiscovery
    from models.transaction import Transaction
    from utils.helpers import get_current_timestamp, safe_divide
    from utils.validators import validate_wallet_address, validate_token_mint
    from token.cache_manager import get_token_metadata_cache, get_token_account_cache
    
except ImportError as e:
    # Fallback implementations
    import logging
    def get_logger(name=None):
        return logging.getLogger(name or 'discovery_engine')
    
    def get_database_manager(): return None
    def get_config(): return None
    
    def validate_wallet_address(addr): return bool(addr and len(addr) == 44)
    def validate_token_mint(mint): return bool(mint and len(mint) == 44)
    def get_current_timestamp(): return int(time.time())
    def safe_divide(a, b, default=0): return a/b if b else default
    
    class Token: pass
    class TokenAccount: pass
    class TokenDiscovery: pass
    class Transaction: pass

logger = get_logger(__name__)

@dataclass
class DiscoveryParams:
    """Parameters for token discovery"""
    min_balance: float = 0.000001
    max_age_hours: int = 168  # 1 week
    include_zero_balance: bool = False
    include_verified_only: bool = False
    scan_depth: int = 3
    priority_boost: float = 1.0

@dataclass
class DiscoveryResult:
    """Result of token discovery"""
    wallet_address: str
    new_tokens: List[TokenDiscovery]
    updated_tokens: List[TokenAccount]
    removed_tokens: List[str]
    scan_duration: float
    total_scanned: int
    confidence_score: float
    metadata: Dict[str, Any]

class TokenDiscoveryEngine:
    """
    Advanced token discovery engine
    Discovers new tokens, monitors changes, and provides insights
    """
    
    def __init__(self):
        self.config = get_config()
        self.db_manager = get_database_manager()
        
        # Discovery settings
        self.discovery_params = DiscoveryParams()
        self.scan_threads = {}
        self.scan_lock = threading.RLock()
        
        # Cache references
        self.metadata_cache = get_token_metadata_cache()
        self.account_cache = get_token_account_cache()
        
        logger.info("✅ Token Discovery Engine initialized")
    
    def discover_new_tokens(self, wallet_address: str, 
                          params: Optional[DiscoveryParams] = None) -> DiscoveryResult:
        """
        Discover new tokens for a wallet
        Args:
            wallet_address: Solana wallet address
            params: Discovery parameters
        Returns:
            DiscoveryResult with findings
        """
        start_time = time.time()
        
        if not validate_wallet_address(wallet_address):
            raise ValueError(f"Invalid wallet address: {wallet_address}")
        
        params = params or self.discovery_params
        
        logger.info(f"🔍 Starting token discovery for {wallet_address[:8]}...")
        
        try:
            # Get existing accounts
            existing_accounts = self._get_existing_accounts(wallet_address)
            existing_mints = {acc.token_mint for acc in existing_accounts}
            
            # Discover new accounts
            discovered_accounts = self._discover_accounts(wallet_address, params)
            
            # Identify changes
            new_tokens = []
            updated_tokens = []
            removed_tokens = []
            
            # Process discovered accounts
            for account in discovered_accounts:
                if account.token_mint not in existing_mints:
                    # New token discovered
                    discovery = self._create_discovery(account, wallet_address)
                    new_tokens.append(discovery)
                    
                    # Create TokenAccount
                    token_account = self._create_token_account(account, wallet_address)
                    updated_tokens.append(token_account)
                    
                    # Cache metadata
                    self._cache_token_metadata(account)
                
                elif account.balance > 0:  # Existing but updated
                    updated_account = self._update_existing_account(account)
                    if updated_account:
                        updated_tokens.append(updated_account)
            
            # Find removed tokens (zero balance)
            removed_tokens = self._find_removed_tokens(wallet_address, existing_accounts, discovered_accounts)
            
            # Calculate confidence score
            confidence_score = self._calculate_confidence_score(new_tokens, updated_tokens, params)
            
            # Build result
            result = DiscoveryResult(
                wallet_address=wallet_address,
                new_tokens=new_tokens,
                updated_tokens=updated_tokens,
                removed_tokens=removed_tokens,
                scan_duration=time.time() - start_time,
                total_scanned=len(discovered_accounts),
                confidence_score=confidence_score,
                metadata={
                    'discovery_method': 'balance_scan',
                    'scan_depth': params.scan_depth,
                    'parameters': params.__dict__
                }
            )
            
            # Log results
            logger.info(f"✅ Discovery complete: {len(new_tokens)} new, "
                       f"{len(updated_tokens)} updated, {len(removed_tokens)} removed")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Discovery error: {e}")
            return DiscoveryResult(
                wallet_address=wallet_address,
                new_tokens=[], updated_tokens=[], removed_tokens=[],
                scan_duration=time.time() - start_time,
                total_scanned=0,
                confidence_score=0.0,
                metadata={'error': str(e)}
            )
    
    def _get_existing_accounts(self, wallet_address: str) -> List[TokenAccount]:
        """Get existing token accounts from database"""
        if not self.db_manager:
            return []
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM token_accounts
                    WHERE wallet_address = ? AND is_active = 1
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
                        is_active=bool(row['is_active']),
                        scan_priority=int(row['scan_priority'])
                    )
                    accounts.append(account)
                
                return accounts
                
        except Exception as e:
            logger.error(f"❌ Error getting existing accounts: {e}")
            return []
    
    def _discover_accounts(self, wallet_address: str, params: DiscoveryParams) -> List[Dict[str, Any]]:
        """Discover token accounts from blockchain or database"""
        # This would normally query blockchain
        # For now, simulate discovery based on transactions
        
        if not self.db_manager:
            return []
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get recent transaction tokens
                cursor.execute("""
                    SELECT DISTINCT token_mint, token_symbol, token_name, decimals
                    FROM transactions
                    WHERE wallet_address = ?
                        AND token_mint IS NOT NULL
                        AND block_time > ?
                    ORDER BY block_time DESC
                    LIMIT 1000
                """, (wallet_address, 
                      get_current_timestamp() - (params.max_age_hours * 3600)))
                
                discovered = []
                for row in cursor.fetchall():
                    if row['token_mint']:
                        discovered.append({
                            'token_mint': row['token_mint'],
                            'token_symbol': row['token_symbol'],
                            'token_name': row['token_name'],
                            'decimals': int(row['decimals']),
                            'balance': 0.0,  # Would be fetched from blockchain
                            'ata_pubkey': f"ATA_{wallet_address[:6]}_{row['token_mint'][:6]}"
                        })
                
                return discovered
                
        except Exception as e:
            logger.error(f"❌ Error discovering accounts: {e}")
            return []
    
    def _create_discovery(self, account: Dict[str, Any], wallet_address: str) -> TokenDiscovery:
        """Create TokenDiscovery object"""
        return TokenDiscovery(
            token_mint=account['token_mint'],
            wallet_address=wallet_address,
            discovered_at=get_current_timestamp(),
            ata_pubkey=account['ata_pubkey'],
            initial_balance=account['balance'],
            decimals=account['decimals'],
            symbol=account['token_symbol'],
            name=account['token_name'],
            discovery_method="transaction_scan",
            confidence_score=0.8
        )
    
    def _create_token_account(self, account: Dict[str, Any], wallet_address: str) -> TokenAccount:
        """Create TokenAccount object"""
        return TokenAccount(
            wallet_address=wallet_address,
            ata_pubkey=account['ata_pubkey'],
            token_mint=account['token_mint'],
            balance=account['balance'],
            decimals=account['decimals'],
            first_seen=get_current_timestamp(),
            last_updated=get_current_timestamp(),
            is_active=True,
            scan_priority=5  # High priority for new discoveries
        )
    
    def _update_existing_account(self, account: Dict[str, Any]) -> Optional[TokenAccount]:
        """Update existing token account"""
        # This would fetch and update balance
        return None
    
    def _find_removed_tokens(self, wallet_address: str, 
                           existing: List[TokenAccount], 
                           discovered: List[Dict[str, Any]]) -> List[str]:
        """Find tokens that have been removed (zero balance)"""
        discovered_mints = {acc['token_mint'] for acc in discovered}
        removed = []
        
        for existing_account in existing:
            if existing_account.token_mint not in discovered_mints:
                removed.append(existing_account.token_mint)
        
        return removed
    
    def _calculate_confidence_score(self, new_tokens: List[TokenDiscovery], 
                                  updated_tokens: List[TokenAccount], 
                                  params: DiscoveryParams) -> float:
        """Calculate confidence score for discovery"""
        factors = []
        
        # Account for number of new tokens
        if new_tokens:
            factors.append(min(len(new_tokens) / 10, 1.0))
        
        # Account for scan completeness
        factors.append(0.9)  # Assume good scan
        
        # Account for parameters
        if params.include_verified_only:
            factors.append(0.95)
        
        return safe_divide(sum(factors), len(factors)) if factors else 0.0
    
    def _cache_token_metadata(self, account: Dict[str, Any]) -> None:
        """Cache token metadata"""
        token = Token(
            address=account['token_mint'],
            symbol=account['token_symbol'],
            name=account['token_name'],
            decimals=account['decimals']
        )
        
        self.metadata_cache.cache_token_metadata(token)
    
    def scan_for_gems(self, wallet_address: str, 
                    min_balance: float = 1000.0,
                    max_age_hours: int = 24) -> List[TokenDiscovery]:
        """Scan for potential gems (undervalued tokens)"""
        discoveries = []
        
        result = self.discover_new_tokens(wallet_address)
        
        for discovery in result.new_tokens:
            # Evaluate gem potential
            if self._is_potential_gem(discovery, min_balance, max_age_hours):
                discovery.metadata['gem_score'] = self._calculate_gem_score(discovery)
                discoveries.append(discovery)
        
        return discoveries
    
    def _is_potential_gem(self, discovery: TokenDiscovery, 
                         min_balance: float, max_age_hours: int) -> bool:
        """Check if token is a potential gem"""
        criteria = []
        
        # New discovery
        if discovery.age_hours < max_age_hours:
            criteria.append(True)
        
        # Has balance
        if discovery.initial_balance >= min_balance:
            criteria.append(True)
        
        # Low market cap indication (would need price data)
        criteria.append(True)  # Placeholder
        
        return len(criteria) >= 2
    
    def _calculate_gem_score(self, discovery: TokenDiscovery) -> float:
        """Calculate gem potential score"""
        score = 0.0
        
        # New discovery bonus
        if discovery.age_hours < 24:
            score += 0.3
        
        # Balance size
        if discovery.initial_balance > 10000:
            score += 0.4
        
        # Symbol analysis
        if discovery.symbol and len(discovery.symbol) <= 5:
            score += 0.1
        
        # Name analysis
        if discovery.name and "token" not in discovery.name.lower():
            score += 0.2
        
        return min(score, 1.0)
    
    def monitor_token_changes(self, wallet_address: str, 
                            since_timestamp: int) -> List[Dict[str, Any]]:
        """Monitor token balance changes"""
        if not self.db_manager:
            return []
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT 
                        ta.token_mint,
                        ta.token_symbol,
                        ta.balance as current_balance,
                        t.token_amount as transaction_amount,
                        t.transaction_type,
                        t.block_time
                    FROM token_accounts ta
                    JOIN transactions t ON ta.token_mint = t.token_mint
                    WHERE ta.wallet_address = ?
                        AND t.block_time > ?
                        AND ta.is_active = 1
                    ORDER BY t.block_time DESC
                """, (wallet_address, since_timestamp))
                
                changes = []
                for row in cursor.fetchall():
                    changes.append({
                        'token_mint': row['token_mint'],
                        'symbol': row['token_symbol'],
                        'current_balance': float(row['current_balance']),
                        'transaction_amount': float(row['transaction_amount']),
                        'transaction_type': row['transaction_type'],
                        'timestamp': int(row['block_time'])
                    })
                
                return changes
                
        except Exception as e:
            logger.error(f"❌ Error monitoring token changes: {e}")
            return []
    
    def get_discovery_statistics(self, wallet_address: str, 
                               days: int = 30) -> Dict[str, Any]:
        """Get discovery statistics for wallet"""
        if not self.db_manager:
            return {'error': 'Database unavailable'}
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cutoff_time = get_current_timestamp() - (days * 24 * 3600)
                
                # Discovery statistics
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_discoveries,
                        AVG(confidence_score) as avg_confidence,
                        COUNT(CASE WHEN confidence_score > 0.8 THEN 1 END) as high_confidence,
                        COUNT(DISTINCT token_mint) as unique_tokens
                    FROM token_accounts ta
                    WHERE ta.wallet_address = ?
                        AND ta.first_seen > ?
                """, (wallet_address, cutoff_time))
                
                stats = dict(cursor.fetchone())
                
                # Top discovered tokens
                cursor.execute("""
                    SELECT token_mint, symbol, COUNT(*) as discovery_count
                    FROM token_accounts ta
                    WHERE ta.wallet_address = ?
                        AND ta.first_seen > ?
                    GROUP BY token_mint, symbol
                    ORDER BY discovery_count DESC
                    LIMIT 10
                """, (wallet_address, cutoff_time))
                
                stats['top_discovered'] = [dict(row) for row in cursor.fetchall()]
                
                return stats
                
        except Exception as e:
            logger.error(f"❌ Error getting discovery stats: {e}")
            return {'error': str(e)}
    
    def generate_discovery_report(self, wallet_address: str) -> Dict[str, Any]:
        """Generate comprehensive discovery report"""
        report = {
            'wallet_address': wallet_address,
            'timestamp': get_current_timestamp(),
            'discoveries': [],
            'recommendations': [],
            'insights': {}
        }
        
        try:
            # Get current state
            current_tokens = self._get_existing_accounts(wallet_address)
            current_count = len(current_tokens)
            
            # Get discovery stats
            stats = self.get_discovery_statistics(wallet_address, days=7)
            report['insights'].update(stats)
            
            # Analyze patterns
            if current_count > 0:
                # Token diversity
                unique_tokens = len(set(acc.token_mint for acc in current_tokens))
                report['insights']['token_diversity'] = safe_divide(unique_tokens, current_count)
                
                # Average priority
                avg_priority = safe_divide(
                    sum(acc.scan_priority for acc in current_tokens), 
                    current_count
                )
                report['insights']['average_priority'] = avg_priority
            
            # Generate recommendations
            if stats.get('total_discoveries', 0) > 10:
                report['recommendations'].append("High discovery rate - consider automated monitoring")
            
            if stats.get('avg_confidence', 0) < 0.7:
                report['recommendations'].append("Low confidence scores - review discovery parameters")
            
            if current_count > 50:
                report['recommendations'].append("Large token portfolio - consider risk assessment")
        
        except Exception as e:
            report['error'] = str(e)
        
        return report
    
    def batch_discover_wallets(self, wallet_addresses: List[str], 
                             params: Optional[DiscoveryParams] = None) -> Dict[str, DiscoveryResult]:
        """Discover tokens for multiple wallets"""
        results = {}
        
        params = params or self.discovery_params
        
        for wallet_address in wallet_addresses:
            if validate_wallet_address(wallet_address):
                results[wallet_address] = self.discover_new_tokens(wallet_address, params)
            else:
                results[wallet_address] = DiscoveryResult(
                    wallet_address=wallet_address,
                    new_tokens=[], updated_tokens=[], removed_tokens=[],
                    scan_duration=0, total_scanned=0, confidence_score=0,
                    metadata={'error': 'Invalid wallet address'}
                )
        
        return results

# Global discovery engine instance
discovery_engine = TokenDiscoveryEngine()

# Convenience functions
def discover_tokens(wallet_address: str) -> DiscoveryResult:
    """Discover tokens for wallet"""
    return discovery_engine.discover_new_tokens(wallet_address)

def scan_for_gems(wallet_address: str) -> List[TokenDiscovery]:
    """Scan for potential gems"""
    return discovery_engine.scan_for_gems(wallet_address)

def get_discovery_report(wallet_address: str) -> Dict[str, Any]:
    """Get discovery report for wallet"""
    return discovery_engine.generate_discovery_report(wallet_address)

if __name__ == "__main__":
    # Test discovery engine
    print("✅ Testing Token Discovery Engine...")
    
    test_wallet = "4DdrfGHGdMjCqVbNtXsEEGL1SryTeMo8KMGWWtZyZVFh"
    
    # Test basic discovery
    result = discover_tokens(test_wallet)
    print(f"📊 Discovery result: {len(result.new_tokens)} new tokens")
    
    # Test gems scan
    gems = scan_for_gems(test_wallet)
    print(f"💎 Found {len(gems)} potential gems")
    
    # Test report
    report = get_discovery_report(test_wallet)
    print("📋 Discovery report generated")