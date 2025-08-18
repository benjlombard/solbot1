"""
Solana Wallet Monitor - Token Metadata Fetcher
Advanced metadata retrieval system with caching, fallback providers, and validation
"""

import time
import json
import requests
import threading
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

# Core imports with fallbacks
try:
    from core.logger import get_logger
    from core.config import get_config
    from models.token import Token
    from token.cache_manager import get_token_metadata_cache, get_price_cache
    
    from utils.helpers import get_current_timestamp, safe_divide
    from utils.validators import validate_token_mint
    
except ImportError as e:
    # Fallback implementations
    import logging
    def get_logger(name=None):
        return logging.getLogger(name or 'metadata_fetcher')
    
    def get_config():
        return type('Config', (), {'metadata': type('MetadataConfig', (), {
            'providers': ['jupiter', 'coingecko', 'solscan'],
            'timeout': 10,
            'retries': 3
        })})()
    
    def validate_token_mint(mint): return bool(mint and len(mint) == 44)
    def get_current_timestamp(): return int(time.time())
    def safe_divide(a, b, default=0): return a/b if b else default
    
    class Token:
        def __init__(self, address, symbol=None, name=None, decimals=9, **kwargs):
            self.address = address
            self.symbol = symbol or "UNKNOWN"
            self.name = name or "Unknown Token"
            self.decimals = decimals

logger = get_logger(__name__)

@dataclass
class MetadataFetchResult:
    """Result of metadata fetch operation"""
    success: bool
    token: Optional[Token] = None
    source: str = "unknown"
    fetch_time: float = 0.0
    error: Optional[str] = None
    metadata: Dict[str, Any] = None

class TokenMetadataFetcher:
    """
    Advanced token metadata fetching system
    Supports multiple providers with fallback and caching
    """
    
    def __init__(self):
        self.config = get_config()
        self.metadata_cache = get_token_metadata_cache()
        self.price_cache = get_price_cache()
        
        # Provider configurations
        self.providers = {
            'jupiter': {
                'base_url': 'https://token.jup.ag',
                'endpoints': {
                    'metadata': '/all',
                    'price': '/price/v2'
                },
                'rate_limit': 100  # requests per minute
            },
            'coingecko': {
                'base_url': 'https://api.coingecko.com/api/v3',
                'endpoints': {
                    'metadata': '/coins/markets',
                    'price': '/simple/price'
                },
                'rate_limit': 50
            },
            'solscan': {
                'base_url': 'https://public-api.solscan.io',
                'endpoints': {
                    'metadata': '/token/meta',
                    'price': '/market/token'
                },
                'rate_limit': 30
            },
            'fallback': {
                'base_url': 'https://raw.githubusercontent.com/solana-labs/token-list/main/src/tokens',
                'endpoints': {
                    'metadata': '/solana.tokenlist.json'
                },
                'rate_limit': 1000
            }
        }
        
        # Rate limiting
        self.request_counts = defaultdict(int)
        self.last_reset = get_current_timestamp()
        
        # Thread safety
        self.fetch_lock = threading.RLock()
        
        logger.info("✅ Token Metadata Fetcher initialized")
    
    def fetch_metadata(self, token_mint: str, force_refresh: bool = False) -> MetadataFetchResult:
        """
        Fetch metadata for token with caching and fallbacks
        Args:
            token_mint: Token mint address
            force_refresh: Force refresh from providers
        Returns:
            MetadataFetchResult
        """
        start_time = time.time()
        
        if not validate_token_mint(token_mint):
            return MetadataFetchResult(
                success=False,
                error="Invalid token mint address"
            )
        
        # Check cache first
        if not force_refresh:
            cached = self.metadata_cache.get_token_metadata(token_mint)
            if cached:
                logger.debug(f"📦 Using cached metadata for {token_mint}")
                return MetadataFetchResult(
                    success=True,
                    token=cached,
                    source="cache",
                    fetch_time=time.time() - start_time
                )
        
        # Try providers in order
        for provider in self._get_provider_order():
            try:
                result = self._fetch_from_provider(token_mint, provider)
                if result.success and result.token:
                    # Cache successful result
                    self.metadata_cache.cache_token_metadata(result.token)
                    
                    logger.debug(f"✅ Fetched metadata from {provider} for {token_mint}")
                    return MetadataFetchResult(
                        success=True,
                        token=result.token,
                        source=provider,
                        fetch_time=time.time() - start_time,
                        metadata=result.metadata
                    )
                    
            except Exception as e:
                logger.warning(f"⚠️ {provider} failed for {token_mint}: {e}")
                continue
        
        # Generate fallback metadata
        fallback_token = self._generate_fallback_metadata(token_mint)
        self.metadata_cache.cache_token_metadata(fallback_token)
        
        return MetadataFetchResult(
            success=True,
            token=fallback_token,
            source="fallback",
            fetch_time=time.time() - start_time,
            metadata={'fallback': True}
        )
    
    def _get_provider_order(self) -> List[str]:
        """Get provider order based on configuration and reliability"""
        return ['jupiter', 'coingecko', 'solscan', 'fallback']
    
    def _fetch_from_provider(self, token_mint: str, provider: str) -> MetadataFetchResult:
        """Fetch metadata from specific provider"""
        if provider == 'jupiter':
            return self._fetch_from_jupiter(token_mint)
        elif provider == 'coingecko':
            return self._fetch_from_coingecko(token_mint)
        elif provider == 'solscan':
            return self._fetch_from_solscan(token_mint)
        elif provider == 'fallback':
            return self._fetch_from_fallback(token_mint)
        else:
            return MetadataFetchResult(success=False, error=f"Unknown provider: {provider}")
    
    def _fetch_from_jupiter(self, token_mint: str) -> MetadataFetchResult:
        """Fetch from Jupiter API"""
        try:
            # Jupiter all tokens endpoint
            url = f"https://token.jup.ag/all"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                tokens = response.json()
                
                for token_data in tokens:
                    if token_data.get('mint') == token_mint:
                        token = Token(
                            address=token_mint,
                            symbol=token_data.get('symbol', 'UNKNOWN'),
                            name=token_data.get('name', 'Unknown'),
                            decimals=token_data.get('decimals', 9),
                            logo_uri=token_data.get('logoURI'),
                            metadata_source='jupiter'
                        )
                        
                        return MetadataFetchResult(
                            success=True,
                            token=token,
                            source='jupiter',
                            metadata=token_data
                        )
            
            return MetadataFetchResult(success=False, error="Token not found in Jupiter")
            
        except Exception as e:
            return MetadataFetchResult(success=False, error=f"Jupiter API error: {e}")
    
    def _fetch_from_coingecko(self, token_mint: str) -> MetadataFetchResult:
        """Fetch from CoinGecko API"""
        try:
            # Map Solana mint to CoinGecko ID
            coingecko_id = self._get_coingecko_id(token_mint)
            if not coingecko_id:
                return MetadataFetchResult(success=False, error="No CoinGecko mapping")
            
            url = f"https://api.coingecko.com/api/v3/coins/{coingecko_id}"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                token = Token(
                    address=token_mint,
                    symbol=data.get('symbol', '').upper(),
                    name=data.get('name', 'Unknown'),
                    decimals=9,  # Default for Solana
                    logo_uri=data.get('image', {}).get('small'),
                    coingecko_id=coingecko_id,
                    market_cap=data.get('market_data', {}).get('market_cap', {}).get('usd'),
                    volume_24h=data.get('market_data', {}).get('total_volume', {}).get('usd'),
                    price_change_24h=data.get('market_data', {}).get('price_change_percentage_24h'),
                    metadata_source='coingecko'
                )
                
                return MetadataFetchResult(
                    success=True,
                    token=token,
                    source='coingecko',
                    metadata=data
                )
                
        except Exception as e:
            return MetadataFetchResult(success=False, error=f"CoinGecko API error: {e}")
    
    def _fetch_from_solscan(self, token_mint: str) -> MetadataFetchResult:
        """Fetch from Solscan API"""
        try:
            url = f"https://public-api.solscan.io/token/meta"
            params = {'tokenAddress': token_mint}
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                token = Token(
                    address=token_mint,
                    symbol=data.get('symbol', 'UNKNOWN'),
                    name=data.get('name', 'Unknown'),
                    decimals=data.get('decimals', 9),
                    logo_uri=data.get('icon'),
                    metadata_source='solscan'
                )
                
                return MetadataFetchResult(
                    success=True,
                    token=token,
                    source='solscan',
                    metadata=data
                )
                
        except Exception as e:
            return MetadataFetchResult(success=False, error=f"Solscan API error: {e}")
    
    def _fetch_from_fallback(self, token_mint: str) -> MetadataFetchResult:
        """Fetch from Solana token list"""
        try:
            # Solana Labs token list
            url = "https://raw.githubusercontent.com/solana-labs/token-list/main/src/tokens/solana.tokenlist.json"
            response = requests.get(url, timeout=15)
            
            if response.status_code == 200:
                token_list = response.json()
                
                for token_data in token_list.get('tokens', []):
                    if token_data.get('address') == token_mint:
                        token = Token(
                            address=token_mint,
                            symbol=token_data.get('symbol', 'UNKNOWN'),
                            name=token_data.get('name', 'Unknown'),
                            decimals=token_data.get('decimals', 9),
                            logo_uri=token_data.get('logoURI'),
                            metadata_source='token_list'
                        )
                        
                        return MetadataFetchResult(
                            success=True,
                            token=token,
                            source='token_list',
                            metadata=token_data
                        )
            
            return MetadataFetchResult(success=False, error="Token not found in list")
            
        except Exception as e:
            return MetadataFetchResult(success=False, error=f"Token list error: {e}")
    
    def _generate_fallback_metadata(self, token_mint: str) -> Token:
        """Generate fallback metadata"""
        # Create symbol from mint
        symbol = f"TOKEN_{token_mint[:6]}"
        name = f"Token {token_mint[:8]}"
        
        return Token(
            address=token_mint,
            symbol=symbol,
            name=name,
            decimals=9,
            metadata_source='generated'
        )
    
    def _get_coingecko_id(self, token_mint: str) -> Optional[str]:
        """Map Solana mint to CoinGecko ID"""
        # Solana mint to CoinGecko ID mapping
        mapping = {
            "So11111111111111111111111111111111111111112": "solana",
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "usd-coin",
            "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "tether",
            "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": "bonk",
            "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmM2yM": "pepe",
            "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": "bonk"
        }
        
        return mapping.get(token_mint)
    
    def fetch_bulk_metadata(self, token_mints: List[str], 
                          batch_size: int = 50) -> List[MetadataFetchResult]:
        """Fetch metadata for multiple tokens"""
        results = []
        
        for i in range(0, len(token_mints), batch_size):
            batch = token_mints[i:i+batch_size]
            batch_results = []
            
            for mint in batch:
                result = self.fetch_metadata(mint)
                batch_results.append(result)
            
            results.extend(batch_results)
            
            # Rate limiting
            time.sleep(0.1)
        
        return results
    
    def update_price_data(self, token_mint: str, price_usd: float, 
                        source: str = "unknown") -> bool:
        """Update price data in cache"""
        try:
            # Get current token
            current = self.metadata_cache.get_token_metadata(token_mint)
            if not current:
                return False
            
            # Update price
            current.update_price(price_usd, source)
            self.metadata_cache.cache_token_metadata(current)
            
            # Also cache in price cache
            self.price_cache.set(
                f"price:{token_mint}",
                {'price': price_usd, 'source': source, 'timestamp': get_current_timestamp()},
                ttl=300  # 5 minutes
            )
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error updating price: {e}")
            return False
    
    def enrich_token_data(self, token: Token) -> Token:
        """Enrich token with additional data"""
        try:
            # Add market data if available
            if token.coingecko_id:
                market_data = self._fetch_market_data(token.coingecko_id)
                if market_data:
                    token.market_cap = market_data.get('market_cap')
                    token.volume_24h = market_data.get('volume_24h')
                    token.price_change_24h = market_data.get('price_change_24h')
            
            # Add social links
            social_data = self._fetch_social_data(token.address)
            if social_data:
                token.metadata_source = 'enriched'
            
            return token
            
        except Exception as e:
            logger.error(f"❌ Error enriching token: {e}")
            return token
    
    def _fetch_market_data(self, coingecko_id: str) -> Optional[Dict[str, Any]]:
        """Fetch market data from CoinGecko"""
        try:
            url = f"https://api.coingecko.com/api/v3/coins/{coingecko_id}"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                market_data = data.get('market_data', {})
                
                return {
                    'market_cap': market_data.get('market_cap', {}).get('usd'),
                    'volume_24h': market_data.get('total_volume', {}).get('usd'),
                    'price_change_24h': market_data.get('price_change_percentage_24h')
                }
                
        except Exception as e:
            logger.error(f"❌ Error fetching market data: {e}")
        
        return None
    
    def _fetch_social_data(self, token_mint: str) -> Optional[Dict[str, Any]]:
        """Fetch social media data"""
        # Placeholder for social data fetching
        return None
    
    def validate_token_metadata(self, token: Token) -> Dict[str, Any]:
        """Validate token metadata"""
        issues = []
        warnings = []
        
        # Symbol validation
        if not token.symbol or len(token.symbol) > 10:
            issues.append("Invalid symbol")
        
        # Name validation
        if not token.name or len(token.name) > 100:
            issues.append("Invalid name")
        
        # Decimals validation
        if not 0 <= token.decimals <= 18:
            issues.append("Invalid decimals")
        
        # Logo validation
        if token.logo_uri and not token.logo_uri.startswith(('http://', 'https://')):
            warnings.append("Invalid logo URL")
        
        # Price validation
        if token.price_usd and (token.price_usd < 0 or token.price_usd > 1000000):
            warnings.append("Suspicious price value")
        
        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'warnings': warnings
        }
    
    def get_metadata_stats(self) -> Dict[str, Any]:
        """Get metadata fetch statistics"""
        return {
            'cache_stats': self.metadata_cache.get_stats(),
            'price_cache_stats': self.price_cache.get_stats(),
            'providers': list(self.providers.keys()),
            'fallback_enabled': True
        }
    
    def cleanup_metadata_cache(self) -> int:
        """Clean up expired metadata"""
        return self.metadata_cache.cleanup_expired()

# Global instance
metadata_fetcher = TokenMetadataFetcher()

# Convenience functions
def fetch_token_metadata(token_mint: str, force_refresh: bool = False) -> MetadataFetchResult:
    """Fetch metadata for single token"""
    return metadata_fetcher.fetch_metadata(token_mint, force_refresh)

def fetch_bulk_metadata(token_mints: List[str]) -> List[MetadataFetchResult]:
    """Fetch metadata for multiple tokens"""
    return metadata_fetcher.fetch_bulk_metadata(token_mints)

def update_token_price(token_mint: str, price_usd: float) -> bool:
    """Update token price"""
    return metadata_fetcher.update_price_data(token_mint, price_usd)

if __name__ == "__main__":
    # Test metadata fetcher
    print("✅ Testing Token Metadata Fetcher...")
    
    # Test single fetch
    test_mint = "So11111111111111111111111111111111111111112"
    result = fetch_token_metadata(test_mint)
    print(f"📊 Metadata fetch result: {result.success} from {result.source}")
    
    # Test stats
    stats = metadata_fetcher.get_metadata_stats()
    print("📈 Metadata stats:", stats)