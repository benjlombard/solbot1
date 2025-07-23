"""
DexScreener API Integration Module - Version Professionnelle
File: dexscreener.py

Comprehensive DexScreener API integration with advanced features:
- Real-time token and pair data retrieval
- Market analysis and trending tokens identification
- Advanced caching and rate limiting
- Circuit breaker pattern for reliability
- Comprehensive analytics and monitoring
- Performance optimization and error handling
"""

import re
import time
import logging
import requests
import asyncio
import aiohttp
import json
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Union, Any
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque
import concurrent.futures
from urllib.parse import urlencode, quote

# Import shared components from other modules
from rugcheck import (
    EnhancedCircuitBreaker, HealthMetricsCollector, ImprovedCacheManager, 
    CacheStrategy, CircuitBreakerError
)


class ChainId(Enum):
    """Supported blockchain networks on DexScreener"""
    ETHEREUM = "ethereum"
    BSC = "bsc" 
    POLYGON = "polygon"
    AVALANCHE = "avalanche"
    FANTOM = "fantom"
    CRONOS = "cronos"
    ARBITRUM = "arbitrum"
    OPTIMISM = "optimism"
    SOLANA = "solana"
    BASE = "base"
    TRON = "tron"
    HARMONY = "harmony"
    MOONBEAM = "moonbeam"
    CELO = "celo"
    AURORA = "aurora"
    METIS = "metis"


class SortBy(Enum):
    """Sorting options for token/pair queries"""
    LIQUIDITY = "liquidity"
    VOLUME = "volume" 
    PRICE_CHANGE = "priceChange"
    MARKET_CAP = "marketCap"
    FDV = "fdv"
    CREATED_AT = "pairCreatedAt"
    TRENDING_SCORE = "trendingScore"
    TXNS = "txns"


class TimeFrame(Enum):
    """Time frames for data analysis"""
    M5 = "m5"
    H1 = "h1"
    H6 = "h6"
    H24 = "h24"


@dataclass
class TokenInfo:
    """Token information structure"""
    address: str
    name: str
    symbol: str
    decimals: Optional[int] = None
    total_supply: Optional[float] = None


@dataclass
class LiquidityInfo:
    """Liquidity information structure"""
    usd: Optional[float] = None
    base: Optional[float] = None
    quote: Optional[float] = None


@dataclass
class TransactionStats:
    """Transaction statistics structure"""
    buys: int = 0
    sells: int = 0


@dataclass
class VolumeInfo:
    """Volume information structure"""
    h24: Optional[float] = None
    h6: Optional[float] = None
    h1: Optional[float] = None
    m5: Optional[float] = None


@dataclass
class PriceChangeInfo:
    """Price change information structure"""
    h24: Optional[float] = None
    h6: Optional[float] = None  
    h1: Optional[float] = None
    m5: Optional[float] = None


@dataclass
class SocialInfo:
    """Social media information"""
    platform: str
    handle: str


@dataclass
class WebsiteInfo:
    """Website information"""
    url: str


@dataclass
class TokenMetadata:
    """Extended token metadata"""
    image_url: Optional[str] = None
    websites: List[WebsiteInfo] = field(default_factory=list)
    socials: List[SocialInfo] = field(default_factory=list)


@dataclass
class BoostInfo:
    """Token boost information"""
    active: int = 0


@dataclass
class TradingPair:
    """Complete trading pair information from DexScreener"""
    chain_id: str
    dex_id: str
    pair_address: str
    base_token: TokenInfo
    quote_token: TokenInfo
    price_native: Optional[str] = None
    price_usd: Optional[str] = None
    liquidity: Optional[LiquidityInfo] = None
    volume: Optional[VolumeInfo] = None
    price_change: Optional[PriceChangeInfo] = None
    txns: Optional[Dict[str, TransactionStats]] = None
    fdv: Optional[float] = None
    market_cap: Optional[float] = None
    pair_created_at: Optional[int] = None
    url: Optional[str] = None
    labels: List[str] = field(default_factory=list)
    info: Optional[TokenMetadata] = None
    boosts: Optional[BoostInfo] = None
    
    # Calculated fields
    age_hours: Optional[float] = None
    volume_to_liquidity_ratio: Optional[float] = None
    market_cap_to_fdv_ratio: Optional[float] = None
    
    def __post_init__(self):
        """Calculate derived fields after initialization"""
        if self.pair_created_at:
            current_time = int(time.time() * 1000)
            self.age_hours = (current_time - self.pair_created_at) / (1000 * 3600)
        
        if self.volume and self.volume.h24 and self.liquidity and self.liquidity.usd:
            if self.liquidity.usd > 0:
                self.volume_to_liquidity_ratio = self.volume.h24 / self.liquidity.usd
        
        if self.market_cap and self.fdv and self.fdv > 0:
            self.market_cap_to_fdv_ratio = self.market_cap / self.fdv


@dataclass
class MarketAnalysis:
    """Market analysis results"""
    total_pairs: int
    total_volume_24h: float
    total_liquidity: float
    average_price_change_24h: float
    trending_tokens: List[TradingPair]
    high_volume_pairs: List[TradingPair]
    new_pairs: List[TradingPair]
    risk_assessment: Dict[str, Any]
    analysis_timestamp: float = field(default_factory=time.time)


@dataclass
class DexScreenerResponse:
    """Standard response wrapper for DexScreener API"""
    schema_version: str
    pairs: List[TradingPair]
    request_timestamp: float = field(default_factory=time.time)
    cache_hit: bool = False


class DexScreenerAnalyzer:
    """
    Professional DexScreener API integration with advanced analytics
    
    Features:
    - Comprehensive token and pair data retrieval
    - Real-time market analysis
    - Advanced filtering and sorting
    - Circuit breaker pattern for reliability
    - Intelligent caching with multiple strategies
    - Performance monitoring and health checks
    - Rate limiting and retry logic
    - Async support for batch operations
    """
    
    def __init__(self, config: Dict):
        self.config = config.get('dexscreener', {})
        #self.base_url = self.config.get('api_base_url', 'https://api.dexscreener.com/latest')
        self.base_url = self.config.get('api_base_url', 'https://api.dexscreener.com/latest')
        self.api_base = 'https://api.dexscreener.com'
        self.logger = logging.getLogger(__name__)
        self.advanced_logger = None  # Will be set by parent
        
        # Request session with optimizations
        self._session = requests.Session()
        self._session.timeout = self.config.get('api_timeout', 20)
        
        # Circuit breaker for API reliability
        self.circuit_breaker = EnhancedCircuitBreaker(
            failure_threshold=self.config.get('failure_threshold', 5),
            recovery_timeout=self.config.get('recovery_timeout', 300),
            half_open_max_calls=self.config.get('half_open_max_calls', 3),
            timeout_threshold=self.config.get('api_timeout', 20),
            logger=self.logger
        )
        
        # Health metrics collector
        self.health_metrics = HealthMetricsCollector(
            self.config.get('health_metrics', {})
        )
        
        # Cache manager
        cache_strategy = CacheStrategy(self.config.get('cache_strategy', 'hybrid'))
        self.cache_manager = ImprovedCacheManager(cache_strategy, self.config)
        self.cache_manager._metrics_callback = self._cache_metrics_callback
        
        # Rate limiting
        self._rate_limiter = self._setup_rate_limiter()
        
        # Request semaphore for concurrency control
        self._request_semaphore = asyncio.Semaphore(
            self.config.get('max_concurrent_requests', 10)
        )
        
        # Performance tracking
        self._performance_metrics = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'average_response_time': 0.0,
            'cache_hit_rate': 0.0,
            'last_updated': time.time()
        }
        
        # Thread safety
        self._metrics_lock = threading.Lock()
        
        self.logger.info("DexScreener Analyzer initialized successfully")
    
    def _setup_rate_limiter(self):
        """Setup rate limiter based on configuration"""
        return {
            'requests_per_minute': self.config.get('requests_per_minute', 300),
            'request_timestamps': deque(maxlen=300),
            'lock': threading.Lock()
        }
    
    def _cache_metrics_callback(self, operation: str, success: bool, cache_type: str):
        """Callback for cache metrics"""
        self.health_metrics.record_cache_operation(operation, success, cache_type)
    
    def set_advanced_logger(self, advanced_logger):
        """Set advanced logger instance"""
        self.advanced_logger = advanced_logger
    
    def _check_rate_limit(self) -> bool:
        """Check if request is within rate limits"""
        with self._rate_limiter['lock']:
            current_time = time.time()
            # Remove timestamps older than 1 minute
            while (self._rate_limiter['request_timestamps'] and 
                   current_time - self._rate_limiter['request_timestamps'][0] > 60):
                self._rate_limiter['request_timestamps'].popleft()
            
            # Check if under limit
            if len(self._rate_limiter['request_timestamps']) >= self._rate_limiter['requests_per_minute']:
                return False
            
            # Add current timestamp
            self._rate_limiter['request_timestamps'].append(current_time)
            return True
    
    def _wait_for_rate_limit(self):
        """Wait if rate limit is exceeded"""
        if not self._check_rate_limit():
            with self._rate_limiter['lock']:
                if self._rate_limiter['request_timestamps']:
                    oldest_request = self._rate_limiter['request_timestamps'][0]
                    wait_time = 60 - (time.time() - oldest_request) + 1
                    if wait_time > 0:
                        self.logger.info(f"Rate limit reached, waiting {wait_time:.1f}s")
                        time.sleep(wait_time)
    
    def _get_cache_key(self, endpoint: str, params: Dict = None) -> str:
        """Generate cache key for request"""
        key_parts = [endpoint]
        if params:
            # Sort params for consistent key generation
            sorted_params = sorted(params.items())
            key_parts.append(urlencode(sorted_params))
        return f"dexscreener_{'_'.join(key_parts)}"
    
    def _make_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """Make API request with circuit breaker and rate limiting"""
        
        # Check rate limit
        self._wait_for_rate_limit()
        
        # Check cache first
        cache_key = self._get_cache_key(endpoint, params)
        if self.cache_manager.is_cache_valid(cache_key):
            cached_result = self.cache_manager.get_from_cache(cache_key)
            if cached_result:
                if self.advanced_logger:
                    self.advanced_logger.log_cache_operation(
                        'dexscreener', 'GET', cache_key[:20], hit=True
                    )
                return cached_result
        
        # Make API request through circuit breaker
        try:
            return self.circuit_breaker.call(self._execute_request, endpoint, params, cache_key)
        except CircuitBreakerError as e:
            self.logger.warning(f"Circuit breaker blocked request: {e}")
            return None
    
    def _execute_request(self, endpoint: str, params: Dict = None, cache_key: str = None) -> Optional[Dict]:
        """Execute the actual API request"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        start_time = time.time()
        
        try:
            headers = {
                'User-Agent': 'DexScreener-Bot/2.0',
                'Accept': 'application/json',
                'Accept-Encoding': 'gzip, deflate',
            }
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('api_calls', 'dexscreener_request_start',
                                              f'🌐 DEXSCREENER: Starting request to {endpoint}')
            
            response = self._session.get(
                url,
                params=params,
                headers=headers,
                timeout=self.config.get('api_timeout', 20)
            )
            
            duration = time.time() - start_time
            
            # Record metrics
            self.health_metrics.record_api_call(
                endpoint=endpoint,
                network='dexscreener',
                response_time=duration * 1000,
                status_code=response.status_code,
                success=(response.status_code == 200)
            )
            
            if self.advanced_logger:
                self.advanced_logger.log_api_call('api_calls', url, 'GET', response.status_code, duration)
            
            if response.status_code == 200:
                json_data = response.json()
                
                # Cache successful response
                if cache_key:
                    self.cache_manager.store_in_cache(cache_key, json_data)
                
                # Update performance metrics
                self._update_performance_metrics(duration, True)
                
                if self.advanced_logger:
                    self.advanced_logger.debug_step('api_calls', 'dexscreener_success',
                                                  f'✅ DEXSCREENER: Success for {endpoint} in {duration:.3f}s')
                
                return json_data
            
            elif response.status_code == 429:
                self.logger.warning(f"Rate limited by DexScreener API: {response.status_code}")
                time.sleep(self.config.get('rate_limit_delay', 5))
                raise Exception("Rate limited")
            
            else:
                self.logger.warning(f"API returned status {response.status_code}: {response.text[:200]}")
                raise Exception(f"API error: {response.status_code}")
        
        except requests.exceptions.Timeout:
            duration = time.time() - start_time
            self._update_performance_metrics(duration, False)
            self.logger.warning(f"Request timeout for {endpoint}")
            raise Exception("Request timeout")
        
        except requests.exceptions.RequestException as e:
            duration = time.time() - start_time
            self._update_performance_metrics(duration, False)
            self.logger.error(f"Request error for {endpoint}: {e}")
            raise Exception(f"Request error: {e}")
    
    def _update_performance_metrics(self, duration: float, success: bool):
        """Update performance metrics"""
        with self._metrics_lock:
            self._performance_metrics['total_requests'] += 1
            
            if success:
                self._performance_metrics['successful_requests'] += 1
            else:
                self._performance_metrics['failed_requests'] += 1
            
            # Update average response time
            total_requests = self._performance_metrics['total_requests']
            current_avg = self._performance_metrics['average_response_time']
            self._performance_metrics['average_response_time'] = (
                (current_avg * (total_requests - 1) + duration) / total_requests
            )
            
            self._performance_metrics['last_updated'] = time.time()
    
    def get_token_pairs(self, token_addresses: List[str]) -> Optional[DexScreenerResponse]:
        """
        Get trading pairs for given token addresses
        
        Args:
            token_addresses: List of token contract addresses (up to 30)
            
        Returns:
            DexScreenerResponse with pairs data
        """
        if not token_addresses or len(token_addresses) > 30:
            self.logger.error("Token addresses list must be between 1 and 30 items")
            return None
        
        # Join addresses with comma
        addresses_str = ','.join(token_addresses)
        endpoint = f"dex/tokens/{addresses_str}"
        
        try:
            response_data = self._make_request(endpoint)
            if response_data:
                return self._parse_pairs_response(response_data)
            
        except Exception as e:
            self.logger.error(f"Error getting token pairs: {e}")
            
        return None
    
    def get_pair_by_chain_and_address(self, chain_id: str, pair_address: str) -> Optional[DexScreenerResponse]:
        """
        Get specific pair by chain and pair address
        
        Args:
            chain_id: Blockchain identifier (e.g., 'ethereum', 'solana')
            pair_address: Trading pair contract address
            
        Returns:
            DexScreenerResponse with pair data
        """
        endpoint = f"dex/pairs/{chain_id}/{pair_address}"
        
        try:
            response_data = self._make_request(endpoint)
            if response_data:
                return self._parse_pairs_response(response_data)
                
        except Exception as e:
            self.logger.error(f"Error getting pair {pair_address} on {chain_id}: {e}")
            
        return None
    
    def search_pairs(self, query: str, limit: int = 1000) -> Optional[DexScreenerResponse]:
        """
        Search for trading pairs by token name/symbol
        
        Args:
            query: Search query (token name or symbol)
            limit: Maximum number of results (default 10)
            
        Returns:
            DexScreenerResponse with matching pairs
        """
        if not query or len(query.strip()) < 2:
            self.logger.error("Search query must be at least 2 characters")
            return None
        
        params = {
            'q': query.strip()
        }
        
        endpoint = "dex/search"
        
        try:
            response_data = self._make_request(endpoint, params)
            if response_data:
                # Limit results if specified
                if limit and 'pairs' in response_data:
                    response_data['pairs'] = response_data['pairs'][:limit]
                
                return self._parse_pairs_response(response_data)
                
        except Exception as e:
            self.logger.error(f"Error searching pairs for '{query}': {e}")
            
        return None
    
    def get_token_pairs_by_chain(self, chain_id: str, token_address: str) -> Optional[List[TradingPair]]:
        """
        Get all trading pairs for a token on a specific chain
        
        Args:
            chain_id: Blockchain identifier
            token_address: Token contract address
            
        Returns:
            List of TradingPair objects
        """
        endpoint = f"token-pairs/v1/{chain_id}/{token_address}"
        
        try:
            response_data = self._make_request(endpoint)
            if response_data and isinstance(response_data, list):
                pairs = []
                for pair_data in response_data:
                    pair = self._parse_single_pair(pair_data)
                    if pair:
                        pairs.append(pair)
                return pairs
                
        except Exception as e:
            self.logger.error(f"Error getting pairs for token {token_address} on {chain_id}: {e}")
            
        return None
    
    def get_trending_pairs_old(self, chain_ids: List[str] = None, limit: int = 1000) -> List[TradingPair]:
        """
        Get trending pairs across specified chains
        
        This method uses search with popular tokens and sorts by various metrics
        to identify trending pairs since DexScreener doesn't have a direct trending endpoint.
        
        Args:
            chain_ids: List of chain identifiers to focus on
            limit: Maximum number of trending pairs to return
            
        Returns:
            List of trending TradingPair objects
        """
        trending_pairs = []
        seen_addresses = set()  # Éviter les doublons
        import random
        # Popular search terms that often yield trending tokens
        trending_terms = [
            # Mots-clés crypto classiques
            'bitcoin', 'btc', 'ethereum', 'eth', 'solana', 'sol', 'usdc', 'usdt',
            
            # Mots-clés populaires actuels
            'ai', 'artificial', 'intelligence', 'bot', 'agent', 'gpt', 'chat',
            'meme', 'pepe', 'doge', 'shib', 'bonk', 'wojak', 'apu', 'brett',
            'dog', 'cat', 'frog', 'bear', 'bull', 'ape', 'monkey', 'lion',
            'moon', 'mars', 'rocket', 'space', 'galaxy', 'star', 'cosmic',
            'safe', 'secure', 'diamond', 'gem', 'gold', 'treasure', 'vault',
            'baby', 'mini', 'micro', 'nano', 'tiny', 'small', 'giant', 'mega',
            'elon', 'trump', 'biden', 'tesla', 'spacex', 'twitter', 'x',
            'floki', 'inu', 'shiba', 'akita', 'husky', 'retriever',
            'chad', 'wojak', 'based', 'cringe', 'sigma', 'alpha', 'beta',
            'pump', 'dump', 'lambo', 'ferrari', 'porsche', 'yacht', 'mansion',
            'hodl', 'rekt', 'wen', 'ser', 'gm', 'gn', 'wagmi', 'ngmi',
            'banana', 'coconut', 'pineapple', 'mango', 'pizza', 'burger',
            'gaming', 'play', 'earn', 'nft', 'metaverse', 'virtual', 'reality',
            'defi', 'dao', 'yield', 'farm', 'stake', 'liquidity', 'swap',
            'king', 'queen', 'prince', 'princess', 'royal', 'crown', 'throne',
            'fire', 'ice', 'water', 'earth', 'wind', 'lightning', 'thunder',
            'red', 'blue', 'green', 'yellow', 'purple', 'pink', 'black', 'white',
            'new', 'next', 'future', 'tomorrow', 'today', 'now', 'time',
            'world', 'global', 'universal', 'infinite', 'eternal', 'forever',
            
            # Termes techniques émergents
            'quantum', 'neural', 'machine', 'learning', 'blockchain', 'web3',
            'zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine',
            '2024', '2025', 'v2', 'v3', 'pro', 'max', 'ultra', 'super', 'hyper',
            
            # Caractères et symboles populaires  
            'x', 'xx', 'xxx', '420', '69', '100', '1000', '10k', '100k', '1m',
            'alpha', 'beta', 'gamma', 'delta', 'omega', 'sigma', 'theta',
        ]
        # 🎯 ROTATION : Sélectionner 3 termes aléatoires à chaque cycle
        selected_terms = random.sample(trending_terms, min(50, len(trending_terms)))
        
        for term in trending_terms[:50]:  # Limit API calls
            try:
                results = self.search_pairs(term, limit=50)
                if results and results.pairs:
                    for pair in results.pairs:
                        # Filter by chain if specified
                        if chain_ids and pair.chain_id not in chain_ids:
                            continue
                        
                        # Basic trending criteria
                        if self._is_potentially_trending(pair):
                            trending_pairs.append(pair)
                
                # Small delay between searches
                time.sleep(0.5)
                
            except Exception as e:
                self.logger.warning(f"Error searching trending term '{term}': {e}")
        
        # Sort by trending score (volume/age ratio with liquidity consideration)
        trending_pairs.sort(key=self._calculate_trending_score, reverse=True)
        
        return trending_pairs[:limit]
    
    def get_trending_pairs(self, chain_ids: List[str] = None, limit: int = 1000) -> List[TradingPair]:
        """
        NOUVELLE MÉTHODE OPTIMISÉE - Get trending pairs (1 seul API call)
        
        Args:
            chain_ids: List of chain identifiers to focus on
            limit: Maximum number of trending pairs to return
            
        Returns:
            List of trending TradingPair objects
        """
        trending_pairs = []
        seen_addresses = set()
        
        try:
            print("🔍 Getting trending tokens (optimized method)...")
            
            # UN SEUL appel API au lieu de 50
            response = requests.get(
                f"{self.base_url}/dex/search",
                params={
                    'q': '',  # Recherche vide = TOUS les tokens actifs
                    'chainIds': ','.join(chain_ids) if chain_ids else 'solana',
                    'orderBy': 'txns',    # Trier par activité
                    'order': 'desc',      # Plus actifs d'abord
                    'limit': min(limit * 3, 100)  # Récupérer plus pour filtrer
                },
                headers={
                    'User-Agent': 'DexScreener-Bot/2.0',
                    'Accept': 'application/json',
                },
                timeout=self.config.get('api_timeout', 15)
            )
            
            if response.status_code == 200:
                data = response.json()
                pairs_data = data.get('pairs', [])
                
                self.logger.info(f"📊 Retrieved {len(pairs_data)} pairs from single API call")
                
                # Convertir et filtrer
                for pair_data in pairs_data:
                    try:
                        # Parser le pair
                        pair = self._parse_single_pair(pair_data)
                        if not pair:
                            continue
                        
                        # Éviter doublons
                        if pair.base_token.address in seen_addresses:
                            continue
                        
                        # Filtrer par chaîne si spécifié
                        if chain_ids and pair.chain_id not in chain_ids:
                            continue
                        
                        # Critères de trending améliorés
                        if self._is_potentially_trending_optimized(pair):
                            trending_pairs.append(pair)
                            seen_addresses.add(pair.base_token.address)
                            
                            if len(trending_pairs) >= limit:
                                break
                                
                    except Exception as e:
                        self.logger.debug(f"Error processing pair: {e}")
                        continue
                
                # Trier par score de trending
                trending_pairs.sort(key=self._calculate_trending_score, reverse=True)
                
                self.logger.info(f"✅ Found {len(trending_pairs)} trending tokens")
                
            else:
                self.logger.warning(f"API returned status {response.status_code}")
                
        except Exception as e:
            self.logger.error(f"Error in optimized trending search: {e}")
        
        return trending_pairs[:limit]

    def _is_potentially_trending_optimized(self, pair: TradingPair) -> bool:
        """Version optimisée des critères de trending"""
        try:
            # Volume minimum requis
            if not pair.volume or not pair.volume.h24 or pair.volume.h24 < 5000:
                return False
            
            # Liquidité minimum
            if not pair.liquidity or not pair.liquidity.usd or pair.liquidity.usd < 2000:
                return False
            
            # Âge raisonnable (pas trop vieux, pas trop récent)
            if pair.age_hours:
                if pair.age_hours < 0.5:  # Moins de 30 minutes = trop récent
                    return False
                if pair.age_hours > 168:  # Plus de 7 jours = pas trending
                    return False
            
            # Au moins un des critères de trending :
            trending_indicators = 0
            
            # 1. Ratio volume/liquidité élevé
            if pair.volume_to_liquidity_ratio and pair.volume_to_liquidity_ratio > 1.5:
                trending_indicators += 1
            
            # 2. Changement de prix significatif
            if pair.price_change and pair.price_change.h24:
                if abs(pair.price_change.h24) > 15:  # +/- 15%
                    trending_indicators += 1
            
            # 3. Activité de trading élevée
            if pair.txns and 'h24' in pair.txns:
                total_txns = pair.txns['h24'].buys + pair.txns['h24'].sells
                if total_txns > 50:
                    trending_indicators += 1
            
            # 4. Token récent avec volume
            if pair.age_hours and pair.age_hours < 48 and pair.volume.h24 > 20000:
                trending_indicators += 1
            
            # Besoin d'au moins 2 indicateurs pour être considéré trending
            return trending_indicators >= 2
            
        except Exception as e:
            self.logger.debug(f"Error checking optimized trending: {e}")
            return False

    # MÉTHODE ALTERNATIVE : Scan par temps réel
    async def get_newest_tokens_realtime(self, hours_back: int = 2) -> List[Dict]:
        """
        Scanner les tokens créés dans les X dernières heures
        CORRECTION: Utiliser une approche plus simple et directe
        """
        newest_tokens = []
        
        try:
            from datetime import datetime, timedelta
            
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=hours_back)
            
            self.logger.info(f"🔍 Searching for tokens created in last {hours_back}h...")
            
            # CORRECTION 1: Utiliser différents termes de recherche pour plus de résultats
            search_terms = [
                '', 'new', 'token', 'coin', 'gem', 'moon', 'safe', 'baby', 'mini',
                'doge', 'pepe', 'shib', 'bonk', 'meme', 'ai', 'bot', 'defi'
            ]
            
            all_pairs = []
            seen_addresses = set()
            
            print(f"🔍 Searching across {len(search_terms)} different search terms...")
            
            for i, term in enumerate(search_terms, 1):  # Limiter à 8 termes pour éviter trop d'appels
                try:
                    print(f"   {i}/8 Searching '{term}'...")
                    
                    # CORRECTION 2: Utiliser l'API search officielle avec params corrects
                    if term:
                        params = {'q': term}
                    else:
                        params = {}  # Recherche générale
                    
                    response = requests.get(
                        f"{self.base_url}/dex/search",
                        params=params,
                        timeout=15,
                        headers={
                            'User-Agent': 'DexScreener-Bot/2.0',
                            'Accept': 'application/json',
                        }
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        pairs = data.get('pairs', [])
                        
                        if pairs:
                            print(f"      ✅ Found {len(pairs)} pairs")
                            
                            for pair in pairs:
                                token_address = pair.get('baseToken', {}).get('address')
                                if token_address and token_address not in seen_addresses:
                                    # CORRECTION 3: Filtrer par chaîne Solana dès le début
                                    if pair.get('chainId') == 'solana':
                                        all_pairs.append(pair)
                                        seen_addresses.add(token_address)
                        else:
                            print(f"      ⚠️ No pairs found for '{term}'")
                    
                    elif response.status_code == 429:
                        print(f"      ⏰ Rate limited, waiting...")
                        await asyncio.sleep(5)
                        continue
                    else:
                        print(f"      ❌ HTTP {response.status_code}")
                    
                    # Délai entre requêtes pour éviter rate limiting
                    if i < len(search_terms[:8]):  # Pas de délai après la dernière requête
                        await asyncio.sleep(1)
                    
                except Exception as e:
                    print(f"      ❌ Error in search term '{term}': {e}")
                    continue
            
            print(f"📊 Retrieved {len(all_pairs)} unique Solana pairs total")
            
            if not all_pairs:
                print("❌ No pairs found at all - API might be having issues")
                return []
            
            # CORRECTION 4: Filtrer et analyser par âge
            for pair in all_pairs:
                try:
                    # Vérifier l'âge du token
                    created_at = pair.get('pairCreatedAt')
                    if not created_at:
                        continue
                    
                    created_time = datetime.fromtimestamp(created_at / 1000)
                    age_hours = (end_time - created_time).total_seconds() / 3600
                    
                    # CORRECTION 5: Critères d'âge plus flexibles
                    if age_hours > hours_back * 2:  # Doubler la fenêtre pour plus de résultats
                        continue
                    
                    if age_hours < 0.05:  # Au moins 3 minutes d'existence
                        continue
                    
                    token_address = pair['baseToken']['address']
                    
                    # Filtres de qualité de base
                    liquidity_usd = pair.get('liquidity', {}).get('usd', 0)
                    volume_24h = pair.get('volume', {}).get('h24', 0)
                    
                    # CORRECTION 6: Critères moins stricts pour avoir plus de résultats
                    if liquidity_usd >= 100:  # Réduire de $1K à $500
                        
                        token_data = {
                            'token_address': token_address,
                            'symbol': pair['baseToken'].get('symbol', 'UNKNOWN'),
                            'name': pair['baseToken'].get('name', 'Unknown'),
                            'age_hours': age_hours,
                            'liquidity_usd': liquidity_usd,
                            'volume_24h': volume_24h,
                            'price_usd': float(pair.get('priceUsd', 0)) if pair.get('priceUsd') else 0,
                            'dex_id': pair.get('dexId'),
                            'pair_address': pair.get('pairAddress'),
                            'created_timestamp': created_at,
                            'chain_id': 'solana'
                        }
                        
                        newest_tokens.append(token_data)
                        
                except Exception as e:
                    self.logger.debug(f"Error processing pair for newest tokens: {e}")
                    continue
            
            # Trier par âge (plus récents d'abord)
            newest_tokens.sort(key=lambda x: x['age_hours'])
            
            self.logger.info(f"🆕 Found {len(newest_tokens)} quality newest Solana tokens in last {hours_back}h")
            
            # CORRECTION 7: Afficher des exemples même si peu de résultats
            if newest_tokens:
                print(f"📋 Sample newest tokens found:")
                for i, token in enumerate(newest_tokens[:10]):  # Afficher jusqu'à 10
                    print(f"   {i+1}. {token['symbol']} - {token['age_hours']:.1f}h - ${token['liquidity_usd']:,.0f}")
            else:
                print("ℹ️ No newest tokens found matching criteria")
                print("💡 Try increasing hours_back or check if there are new listings")
                
        except Exception as e:
            self.logger.error(f"Error getting newest tokens: {e}")
            import traceback
            traceback.print_exc()
        
        return newest_tokens


    async def get_newest_tokens_by_timestamp(self, hours_back: int = 2) -> List[Dict]:
        """Récupérer les tokens par timestamp avec diversification des sources"""
        newest_tokens = []
        
        try:
            from datetime import datetime, timedelta
            import time
            
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=hours_back)
            cutoff_timestamp = int(start_time.timestamp() * 1000)
            
            print(f"🔍 Getting diversified newest tokens (last {hours_back}h)...")
            
            # SYSTÈME DE ROTATION DES STRATÉGIES
            # Change de stratégie toutes les 5 minutes pour diversifier
            strategy_cycle = int(time.time() // 300) % 4  # 4 stratégies, rotation 5min
            
            strategy_names = ["Token Boosts", "Varied Search", "DEX Rotation", "Hybrid"]
            print(f"🔄 Using strategy #{strategy_cycle + 1}: {strategy_names[strategy_cycle]}")
            
            if strategy_cycle == 0:
                # STRATÉGIE 1: TOKEN BOOSTS + PROFILES
                newest_tokens = await self._get_from_token_boosts(hours_back, cutoff_timestamp)
                
            elif strategy_cycle == 1:
                # STRATÉGIE 2: RECHERCHE PAR TERMES VARIÉS
                newest_tokens = await self._get_from_varied_search(hours_back, cutoff_timestamp)
                
            elif strategy_cycle == 2:
                # STRATÉGIE 3: ROTATION PAR DEX
                newest_tokens = await self._get_from_different_dexes(hours_back, cutoff_timestamp)
                
            else:
                # STRATÉGIE 4: APPROCHE HYBRIDE
                newest_tokens = await self._get_hybrid_approach(hours_back, cutoff_timestamp)
            
            # Déduplication finale par adresse
            seen_addresses = set()
            unique_tokens = []
            
            for token in newest_tokens:
                token_address = token.get('token_address')
                if token_address and token_address not in seen_addresses:
                    seen_addresses.add(token_address)
                    unique_tokens.append(token)
            
            # Trier par âge (plus récents d'abord)
            unique_tokens.sort(key=lambda x: x.get('age_hours', 999))
            
            # Limiter les résultats
            final_tokens = unique_tokens[:30]  # Max 30 tokens par cycle
            
            self.logger.info(f"🆕 Found {len(final_tokens)} unique newest tokens using strategy {strategy_cycle + 1}")
            
            if final_tokens:
                print(f"📋 Sample from strategy '{strategy_names[strategy_cycle]}':")
                for i, token in enumerate(final_tokens[:8]):
                    print(f"   {i+1}. {token['symbol']} - {token['age_hours']:.1f}h - ${token['liquidity_usd']:,.0f}")
            
            return final_tokens
            
        except Exception as e:
            self.logger.error(f"Error in diversified newest tokens: {e}")
            import traceback
            traceback.print_exc()
            return []

    async def _get_from_token_boosts(self, hours_back: int, cutoff_timestamp: int) -> List[Dict]:
        """STRATÉGIE 1: Récupérer via token-boosts et profiles"""
        tokens = []
        
        try:
            print("   🚀 Strategy 1: Token Boosts + Profiles")
            
            # Endpoint 1: Token Boosts Latest
            try:
                response = requests.get(
                    f"{self.base_url.replace('/latest', '')}/token-boosts/latest/v1",
                    timeout=15,
                    headers={'User-Agent': 'DexScreener-Bot/2.0', 'Accept': 'application/json'}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    print(f"      ✅ Token boosts: {len(data) if isinstance(data, list) else 'object'}")
                    
                    if isinstance(data, list):
                        for item in data[:20]:  # Limiter à 20
                            token_address = item.get('tokenAddress') or item.get('address')
                            if token_address:
                                token_details = await self._get_token_details_from_pairs(token_address)
                                if (token_details and 
                                    token_details.get('created_timestamp', 0) >= cutoff_timestamp):
                                    tokens.append(token_details)
                            
                            await asyncio.sleep(0.1)
                else:
                    print(f"      ❌ Token boosts failed: {response.status_code}")
                    
            except Exception as e:
                print(f"      ⚠️ Token boosts error: {e}")
            
            # Endpoint 2: Token Profiles (si différent)
            try:
                response = requests.get(
                    f"{self.base_url.replace('/latest', '')}/token-profiles/latest/v1",
                    timeout=15,
                    headers={'User-Agent': 'DexScreener-Bot/2.0', 'Accept': 'application/json'}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    print(f"      ✅ Token profiles: {len(data) if isinstance(data, list) else 'object'}")
                    
                    # Traitement similaire...
                    if isinstance(data, list):
                        for item in data[:15]:
                            token_address = item.get('tokenAddress') or item.get('address')
                            if token_address:
                                token_details = await self._get_token_details_from_pairs(token_address)
                                if (token_details and 
                                    token_details.get('created_timestamp', 0) >= cutoff_timestamp):
                                    tokens.append(token_details)
                            
                            await asyncio.sleep(0.1)
                else:
                    print(f"      ❌ Token profiles failed: {response.status_code}")
                    
            except Exception as e:
                print(f"      ⚠️ Token profiles error: {e}")
            
            return tokens
            
        except Exception as e:
            print(f"   ❌ Strategy 1 failed: {e}")
            return []

    async def _get_from_varied_search(self, hours_back: int, cutoff_timestamp: int) -> List[Dict]:
        """STRATÉGIE 2: Recherche par termes variés et rotatifs"""
        tokens = []
        
        try:
            print("   🔍 Strategy 2: Varied Search Terms")
            
            # Termes de recherche rotatifs basés sur l'heure actuelle
            import time
            hour_of_day = int(time.time() // 3600) % 24
            
            # Différentes listes selon l'heure pour diversifier
            term_sets = [
                ['', 'pump', 'new', 'fresh'],           # Set 1: 0-5h
                ['token', 'coin', 'gem', 'moon'],       # Set 2: 6-11h  
                ['meme', 'dog', 'cat', 'pepe'],         # Set 3: 12-17h
                ['ai', 'bot', 'defi', 'nft']            # Set 4: 18-23h
            ]
            
            current_set = term_sets[hour_of_day // 6]  # Change toutes les 6h
            print(f"      📚 Using term set for hour {hour_of_day}: {current_set}")
            
            for term in current_set:
                try:
                    params = {'q': term} if term else {}
                    
                    response = requests.get(
                        f"{self.base_url}/dex/search",
                        params=params,
                        timeout=15,
                        headers={'User-Agent': 'DexScreener-Bot/2.0', 'Accept': 'application/json'}
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        pairs = data.get('pairs', [])
                        
                        print(f"      🔍 '{term}': {len(pairs)} pairs")
                        
                        for pair in pairs[:8]:  # Max 8 par terme
                            if pair.get('chainId') == 'solana':
                                created_at = pair.get('pairCreatedAt')
                                if created_at and created_at >= cutoff_timestamp:
                                    token_data = self._parse_pair_to_token_data(pair)
                                    if token_data:
                                        tokens.append(token_data)
                    
                    await asyncio.sleep(0.8)  # Délai entre termes
                    
                except Exception as e:
                    print(f"      ⚠️ Term '{term}' failed: {e}")
                    continue
            
            return tokens
            
        except Exception as e:
            print(f"   ❌ Strategy 2 failed: {e}")
            return []

    async def _get_from_different_dexes(self, hours_back: int, cutoff_timestamp: int) -> List[Dict]:
        """STRATÉGIE 3: Rotation par DEX différents"""
        tokens = []
        
        try:
            print("   🏪 Strategy 3: DEX Rotation")
            
            # Liste des DEX Solana populaires pour cibler différentes sources
            target_dexes = ['raydium', 'orca', 'jupiter', 'meteora', 'phoenix']
            
            # Rotation basée sur les minutes pour changer régulièrement
            import time
            minute_cycle = int(time.time() // 60) % len(target_dexes)
            primary_dex = target_dexes[minute_cycle]
            secondary_dex = target_dexes[(minute_cycle + 1) % len(target_dexes)]
            
            print(f"      🎯 Targeting DEXes: {primary_dex}, {secondary_dex}")
            
            # Recherche générale puis filtrage par DEX
            response = requests.get(
                f"{self.base_url}/dex/search",
                params={'q': 'solana'},
                timeout=15,
                headers={'User-Agent': 'DexScreener-Bot/2.0', 'Accept': 'application/json'}
            )
            
            if response.status_code == 200:
                data = response.json()
                pairs = data.get('pairs', [])
                
                primary_count = 0
                secondary_count = 0
                
                for pair in pairs:
                    try:
                        if pair.get('chainId') != 'solana':
                            continue
                        
                        dex_id = pair.get('dexId', '').lower()
                        created_at = pair.get('pairCreatedAt')
                        
                        if not created_at or created_at < cutoff_timestamp:
                            continue
                        
                        # Priorité au DEX principal, puis secondaire
                        if primary_dex in dex_id and primary_count < 15:
                            token_data = self._parse_pair_to_token_data(pair)
                            if token_data:
                                tokens.append(token_data)
                                primary_count += 1
                        
                        elif secondary_dex in dex_id and secondary_count < 10:
                            token_data = self._parse_pair_to_token_data(pair)
                            if token_data:
                                tokens.append(token_data)
                                secondary_count += 1
                        
                        if primary_count >= 15 and secondary_count >= 10:
                            break
                            
                    except Exception as e:
                        continue
                
                print(f"      📊 Found: {primary_count} from {primary_dex}, {secondary_count} from {secondary_dex}")
            
            return tokens
            
        except Exception as e:
            print(f"   ❌ Strategy 3 failed: {e}")
            return []

    async def _get_hybrid_approach(self, hours_back: int, cutoff_timestamp: int) -> List[Dict]:
        """STRATÉGIE 4: Approche hybride combinant plusieurs méthodes"""
        tokens = []
        
        try:
            print("   🔄 Strategy 4: Hybrid Approach")
            
            # Combiner 3 sources différentes avec des quotas
            sources = [
                ("Token Boosts", lambda: self._get_from_token_boosts(hours_back, cutoff_timestamp), 10),
                ("Popular Search", lambda: self._search_popular_terms(cutoff_timestamp), 10),
                ("Recent Pairs", lambda: self._get_recent_pairs_direct(cutoff_timestamp), 10)
            ]
            
            for source_name, source_func, quota in sources:
                try:
                    print(f"      📡 Hybrid source: {source_name}")
                    source_tokens = await source_func()
                    
                    # Prendre seulement le quota de chaque source
                    tokens.extend(source_tokens[:quota])
                    print(f"      ✅ {source_name}: Added {len(source_tokens[:quota])} tokens")
                    
                    await asyncio.sleep(0.5)  # Délai entre sources
                    
                except Exception as e:
                    print(f"      ⚠️ {source_name} failed: {e}")
                    continue
            
            return tokens
            
        except Exception as e:
            print(f"   ❌ Strategy 4 failed: {e}")
            return []

    async def _search_popular_terms(self, cutoff_timestamp: int) -> List[Dict]:
        """Recherche avec termes populaires actuels"""
        tokens = []
        popular_terms = ['pump', 'moon', 'gem']  # Termes courts et populaires
        
        for term in popular_terms:
            try:
                response = requests.get(
                    f"{self.base_url}/dex/search",
                    params={'q': term},
                    timeout=10,
                    headers={'User-Agent': 'DexScreener-Bot/2.0', 'Accept': 'application/json'}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    pairs = data.get('pairs', [])
                    
                    for pair in pairs[:5]:  # Max 5 par terme
                        if (pair.get('chainId') == 'solana' and 
                            pair.get('pairCreatedAt', 0) >= cutoff_timestamp):
                            token_data = self._parse_pair_to_token_data(pair)
                            if token_data:
                                tokens.append(token_data)
                
                await asyncio.sleep(0.3)
                
            except Exception as e:
                continue
        
        return tokens

    async def _get_recent_pairs_direct(self, cutoff_timestamp: int) -> List[Dict]:
        """Récupération directe des paires récentes"""
        tokens = []
        
        try:
            # Recherche très générale pour avoir un large éventail
            response = requests.get(
                f"{self.base_url}/dex/search",
                params={'q': ''},  # Recherche vide
                timeout=15,
                headers={'User-Agent': 'DexScreener-Bot/2.0', 'Accept': 'application/json'}
            )
            
            if response.status_code == 200:
                data = response.json()
                pairs = data.get('pairs', [])
                
                recent_pairs = []
                for pair in pairs:
                    if (pair.get('chainId') == 'solana' and 
                        pair.get('pairCreatedAt', 0) >= cutoff_timestamp):
                        recent_pairs.append(pair)
                
                # Trier par date de création (plus récents d'abord)
                recent_pairs.sort(key=lambda p: p.get('pairCreatedAt', 0), reverse=True)
                
                # Prendre les 15 plus récents
                for pair in recent_pairs[:15]:
                    token_data = self._parse_pair_to_token_data(pair)
                    if token_data:
                        tokens.append(token_data)
        
        except Exception as e:
            pass
        
        return tokens

    def _parse_pair_to_token_data(self, pair: Dict) -> Optional[Dict]:
        """Convertir une paire DexScreener in format token_data standard"""
        try:
            from datetime import datetime
            
            created_at = pair.get('pairCreatedAt')
            if not created_at:
                return None
            
            created_time = datetime.fromtimestamp(created_at / 1000)
            age_hours = (datetime.now() - created_time).total_seconds() / 3600
            
            liquidity_usd = pair.get('liquidity', {}).get('usd', 0)
            volume_24h = pair.get('volume', {}).get('h24', 0)
            
            # Filtres de qualité minimum
            if liquidity_usd < 100 or age_hours < 0.05:  # Au moins $100 et 3 minutes
                return None
            
            token_address = pair['baseToken']['address']
            
            return {
                'token_address': token_address,
                'symbol': pair['baseToken'].get('symbol', 'UNKNOWN'),
                'name': pair['baseToken'].get('name', 'Unknown'),
                'age_hours': age_hours,
                'liquidity_usd': liquidity_usd,
                'volume_24h': volume_24h,
                'price_usd': float(pair.get('priceUsd', 0)) if pair.get('priceUsd') else 0,
                'dex_id': pair.get('dexId'),
                'pair_address': pair.get('pairAddress'),
                'created_timestamp': created_at,
                'chain_id': 'solana'
            }
            
        except Exception as e:
            self.logger.debug(f"Error parsing pair to token data: {e}")
            return None

    async def get_newest_tokens_by_timestamp_old(self, hours_back: int = 2) -> List[Dict]:
        """Récupérer les tokens par timestamp de création - utilise la vraie API"""
        newest_tokens = []
        
        try:
            from datetime import datetime, timedelta
            
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=hours_back)
            cutoff_timestamp = int(start_time.timestamp() * 1000)
            
            print(f"🔍 Getting newest tokens via token-boosts API (last {hours_back}h)...")
            
            # MÉTHODE 1: Utiliser l'endpoint token-boosts/latest/v1 (selon la doc)
            try:
                response = requests.get(
                    f"{self.base_url.replace('/latest', '')}/token-boosts/latest/v1",
                    timeout=20,
                    headers={
                        'User-Agent': 'DexScreener-Bot/2.0',
                        'Accept': 'application/json',
                    }
                )
                
                if response.status_code == 200:
                    boosts_data = response.json()
                    print(f"📊 Got {len(boosts_data) if isinstance(boosts_data, list) else 'object'} from token-boosts")
                    
                    # Traiter les données des boosts
                    if isinstance(boosts_data, list):
                        for boost_item in boosts_data[:50]:  # Limiter à 50
                            try:
                                # Extraire l'adresse du token depuis les boosts
                                token_address = boost_item.get('tokenAddress') or boost_item.get('address')
                                if not token_address:
                                    continue
                                
                                # Récupérer les détails du token via token-pairs API
                                token_details = await self._get_token_details_from_pairs(token_address)
                                if token_details and token_details.get('age_hours', 0) <= hours_back:
                                    newest_tokens.append(token_details)
                                
                                await asyncio.sleep(0.1)  # Rate limiting
                                
                            except Exception as e:
                                self.logger.debug(f"Error processing boost item: {e}")
                                continue
                    
                    if newest_tokens:
                        print(f"✅ Found {len(newest_tokens)} tokens via token-boosts method")
                        return newest_tokens
                else:
                    print(f"⚠️ Token-boosts API returned {response.status_code}")
                    
            except Exception as e:
                print(f"⚠️ Token-boosts method failed: {e}")
            
            # MÉTHODE 2: Fallback - utiliser search avec requête vide (mais sans paramètres invalides)
            print("🔄 Trying fallback with basic search...")
            
            response = requests.get(
                f"{self.base_url}/dex/search",
                params={'q': 'solana'},  # Recherche simple
                timeout=20,
                headers={
                    'User-Agent': 'DexScreener-Bot/2.0',
                    'Accept': 'application/json',
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                all_pairs = data.get('pairs', [])
                
                print(f"📊 Got {len(all_pairs)} pairs from fallback search, filtering by timestamp...")
                
                for pair in all_pairs:
                    try:
                        if pair.get('chainId') != 'solana':
                            continue
                            
                        created_at = pair.get('pairCreatedAt')
                        if not created_at:
                            continue
                        
                        # Filtrer par timestamp
                        if created_at >= cutoff_timestamp:
                            created_time = datetime.fromtimestamp(created_at / 1000)
                            age_hours = (end_time - created_time).total_seconds() / 3600
                            
                            liquidity_usd = pair.get('liquidity', {}).get('usd', 0)
                            volume_24h = pair.get('volume', {}).get('h24', 0)
                            
                            if liquidity_usd >= 100 and age_hours >= 0.05:
                                token_address = pair['baseToken']['address']
                                
                                token_data = {
                                    'token_address': token_address,
                                    'symbol': pair['baseToken'].get('symbol', 'UNKNOWN'),
                                    'name': pair['baseToken'].get('name', 'Unknown'),
                                    'age_hours': age_hours,
                                    'liquidity_usd': liquidity_usd,
                                    'volume_24h': volume_24h,
                                    'price_usd': float(pair.get('priceUsd', 0)) if pair.get('priceUsd') else 0,
                                    'dex_id': pair.get('dexId'),
                                    'pair_address': pair.get('pairAddress'),
                                    'created_timestamp': created_at,
                                    'chain_id': 'solana'
                                }
                                
                                newest_tokens.append(token_data)
                                
                    except Exception as e:
                        continue
            
            # Trier et limiter
            newest_tokens.sort(key=lambda x: x['age_hours'])
            newest_tokens = newest_tokens[:100]  # Limiter à 50 résultats
            
            self.logger.info(f"🆕 Found {len(newest_tokens)} newest Solana tokens")
            
            if newest_tokens:
                print(f"📋 Sample newest tokens found:")
                for i, token in enumerate(newest_tokens[:10]):
                    print(f"   {i+1}. {token['symbol']} - {token['age_hours']:.1f}h - ${token['liquidity_usd']:,.0f}")
            else:
                print("ℹ️ No newest tokens found matching criteria")
                
        except Exception as e:
            self.logger.error(f"Error getting newest tokens by timestamp: {e}")
            import traceback
            traceback.print_exc()
        
        return newest_tokens

    async def _get_token_details_from_pairs(self, token_address: str) -> Optional[Dict]:
        """Récupérer les détails d'un token via l'API token-pairs"""
        try:
            # Utiliser l'endpoint token-pairs selon la documentation
            response = requests.get(
                f"{self.base_url.replace('/latest', '')}/token-pairs/v1/solana/{token_address}",
                timeout=15,
                headers={
                    'User-Agent': 'DexScreener-Bot/2.0',
                    'Accept': 'application/json',
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    pair = data[0]  # Prendre la première paire
                    
                    from datetime import datetime
                    created_at = pair.get('pairCreatedAt')
                    age_hours = 0
                    
                    if created_at:
                        created_time = datetime.fromtimestamp(created_at / 1000)
                        age_hours = (datetime.now() - created_time).total_seconds() / 3600
                    
                    return {
                        'token_address': token_address,
                        'symbol': pair['baseToken'].get('symbol', 'UNKNOWN'),
                        'name': pair['baseToken'].get('name', 'Unknown'),
                        'age_hours': age_hours,
                        'liquidity_usd': pair.get('liquidity', {}).get('usd', 0),
                        'volume_24h': pair.get('volume', {}).get('h24', 0),
                        'price_usd': float(pair.get('priceUsd', 0)) if pair.get('priceUsd') else 0,
                        'dex_id': pair.get('dexId'),
                        'pair_address': pair.get('pairAddress'),
                        'created_timestamp': created_at,
                        'chain_id': 'solana'
                    }
            
            return None
            
        except Exception as e:
            self.logger.debug(f"Error getting token details for {token_address}: {e}")
            return None

    async def get_newest_tokens_optimized(self, hours_back: int = 2) -> List[Dict]:
        """Méthode optimisée utilisant les vrais endpoints de l'API"""
        newest_tokens = []
        
        try:
            print(f"🚀 Using optimized method with real API endpoints...")
            
            # Stratégie 1: Utiliser token-boosts/latest/v1
            try:
                response = requests.get(
                    f"{self.base_url.replace('/latest', '')}/token-boosts/latest/v1",
                    timeout=15,
                    headers={
                        'User-Agent': 'DexScreener-Bot/2.0',
                        'Accept': 'application/json',
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    print(f"✅ Token-boosts endpoint successful")
                    
                    if isinstance(data, list):
                        for item in data[:30]:  # Limiter à 30 pour éviter trop d'appels
                            token_address = item.get('tokenAddress') or item.get('address')
                            if token_address:
                                token_details = await self._get_token_details_from_pairs(token_address)
                                if token_details and token_details.get('age_hours', 999) <= hours_back:
                                    newest_tokens.append(token_details)
                            
                            await asyncio.sleep(0.1)
                    
                    if newest_tokens:
                        print(f"✅ Found {len(newest_tokens)} tokens via token-boosts")
                        return newest_tokens
                
            except Exception as e:
                print(f"⚠️ Token-boosts method failed: {e}")
            
            # Stratégie 2: Utiliser search simple
            print("🔄 Trying basic search method...")
            
            search_terms = ['', 'new', 'token', 'gem']
            
            for term in search_terms[:3]:  # Limiter à 3 termes
                try:
                    params = {'q': term} if term else {}
                    
                    response = requests.get(
                        f"{self.base_url}/dex/search",
                        params=params,
                        timeout=15,
                        headers={
                            'User-Agent': 'DexScreener-Bot/2.0',
                            'Accept': 'application/json',
                        }
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        pairs = data.get('pairs', [])
                        
                        # Traiter les paires comme dans la méthode timestamp
                        # [Code de traitement similaire]
                        
                    await asyncio.sleep(1)  # Rate limiting
                    
                except Exception as e:
                    continue
            
            return newest_tokens
            
        except Exception as e:
            self.logger.error(f"Error in optimized method: {e}")
            return []

    

    async def get_newest_tokens_paginated(self, hours_back: int = 2) -> List[Dict]:
        """Parcourir les pages de résultats au lieu de chercher par termes"""
        newest_tokens = []
        page_size = 50
        max_pages = 20  # Limite pour éviter trop d'appels API
        
        for page in range(max_pages):
            try:
                # Utiliser l'offset pour paginer
                params = {
                    'limit': page_size,
                    'offset': page * page_size
                }
                
                response = requests.get(
                    f"{self.base_url}/dex/pairs",  # Endpoint différent
                    params=params,
                    timeout=15
                )
                
                if response.status_code == 200:
                    pairs = response.json()
                    if not pairs:
                        break  # Plus de résultats
                        
                    # Traiter les paires de cette page...
                    
                await asyncio.sleep(0.5)  # Rate limiting
                
            except Exception as e:
                continue

    async def get_newest_tokens_sorted(self, hours_back: int = 2) -> List[Dict]:
        """Utiliser le tri par date de création"""
        newest_tokens = []
        
        try:
            from datetime import datetime, timedelta
            
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=hours_back)
            cutoff_timestamp = int(start_time.timestamp() * 1000)
            
            print(f"🔍 Getting tokens sorted by creation date (last {hours_back}h)...")
            
            # Requête avec tri par date
            params = {
                'sort': 'pairCreatedAt',
                'order': 'desc',
                'limit': 100,
                'chainId': 'solana'
            }
            
            response = requests.get(
                f"{self.base_url}/dex/search",
                params=params,
                timeout=15,
                headers={
                    'User-Agent': 'DexScreener-Bot/2.0',
                    'Accept': 'application/json',
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                pairs = data.get('pairs', [])
                
                print(f"📊 Got {len(pairs)} pairs sorted by creation date")
                
                # Filtrer par âge et traiter les données
                for pair in pairs:
                    try:
                        created_at = pair.get('pairCreatedAt')
                        if not created_at:
                            continue
                        
                        # Vérifier si le token est dans la fenêtre temporelle
                        if created_at >= cutoff_timestamp:
                            created_time = datetime.fromtimestamp(created_at / 1000)
                            age_hours = (end_time - created_time).total_seconds() / 3600
                            
                            # Filtres de qualité
                            liquidity_usd = pair.get('liquidity', {}).get('usd', 0)
                            volume_24h = pair.get('volume', {}).get('h24', 0)
                            
                            if liquidity_usd >= 100 and age_hours >= 0.05:
                                token_address = pair['baseToken']['address']
                                
                                token_data = {
                                    'token_address': token_address,
                                    'symbol': pair['baseToken'].get('symbol', 'UNKNOWN'),
                                    'name': pair['baseToken'].get('name', 'Unknown'),
                                    'age_hours': age_hours,
                                    'liquidity_usd': liquidity_usd,
                                    'volume_24h': volume_24h,
                                    'price_usd': float(pair.get('priceUsd', 0)) if pair.get('priceUsd') else 0,
                                    'dex_id': pair.get('dexId'),
                                    'pair_address': pair.get('pairAddress'),
                                    'created_timestamp': created_at,
                                    'chain_id': 'solana'
                                }
                                
                                newest_tokens.append(token_data)
                        else:
                            # Comme c'est trié par date desc, on peut s'arrêter ici
                            break
                            
                    except Exception as e:
                        self.logger.debug(f"Error processing sorted pair: {e}")
                        continue
                
                self.logger.info(f"🆕 Found {len(newest_tokens)} tokens using sorted method")
                
            elif response.status_code == 429:
                print("⏰ Rate limited by API")
                self.logger.warning("Rate limited by DexScreener API in sorted method")
                
            else:
                print(f"❌ API returned status {response.status_code}")
                self.logger.warning(f"DexScreener API returned status {response.status_code} in sorted method")
                
            # Afficher des exemples
            if newest_tokens:
                print(f"📋 Sample tokens from sorted method:")
                for i, token in enumerate(newest_tokens[:5]):
                    print(f"   {i+1}. {token['symbol']} - {token['age_hours']:.1f}h - ${token['liquidity_usd']:,.0f}")
            else:
                print("ℹ️ No tokens found with sorted method")
                
        except Exception as e:
            self.logger.error(f"Error in sorted tokens method: {e}")
            print(f"❌ Sorted method failed: {e}")
            import traceback
            traceback.print_exc()
        
        return newest_tokens


    async def get_newest_tokens_optimized(self, hours_back: int = 2) -> List[Dict]:
        """Méthode optimisée sans dépendance aux termes de recherche"""
        newest_tokens = []
        
        try:
            # Stratégie 1: Essayer l'endpoint "latest" s'il existe
            endpoints_to_try = [
                '/dex/pairs/latest',
                '/dex/pairs/new', 
                '/dex/search?sort=newest',
                '/dex/search'  # Fallback
            ]
            
            for endpoint in endpoints_to_try:
                try:
                    url = f"{self.base_url.rstrip('/')}{endpoint}"
                    response = requests.get(url, timeout=10)
                    
                    if response.status_code == 200:
                        data = response.json()
                        pairs = data.get('pairs', data if isinstance(data, list) else [])
                        
                        if pairs:
                            print(f"✅ Success with endpoint: {endpoint}")
                            print(f"📊 Found {len(pairs)} pairs")
                            
                            # Filtrer par âge directement
                            filtered_pairs = self._filter_pairs_by_age(pairs, hours_back)
                            return filtered_pairs
                            
                except Exception as e:
                    continue
            
            print("⚠️ All optimized methods failed, using fallback...")
            return []
            
        except Exception as e:
            self.logger.error(f"Optimized method failed: {e}")
            return []

    def _filter_pairs_by_age(self, pairs: List, hours_back: int) -> List[Dict]:
        """Filtrer les paires par âge uniquement"""
        from datetime import datetime, timedelta
        
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        cutoff_timestamp = int(cutoff_time.timestamp() * 1000)
        
        filtered = []
        
        for pair in pairs:
            try:
                created_at = pair.get('pairCreatedAt')
                if created_at and created_at >= cutoff_timestamp:
                    if pair.get('chainId') == 'solana':
                        # Traitement du token...
                        filtered.append(self._process_pair_data(pair))
            except:
                continue
        
        return filtered

    async def get_newest_tokens_via_boosts(self, limit: int = 50) -> List[Dict]:
        """
        Récupérer les tokens récents via l'endpoint token-boosts
        """
        newest_tokens = []
        
        try:
            # Utiliser l'endpoint token-boosts/latest/v1
            response = requests.get(
                "https://api.dexscreener.com/token-boosts/latest/v1",
                timeout=15,
                headers={
                    'User-Agent': 'DexScreener-Bot/2.0',
                    'Accept': 'application/json',
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # La structure exacte dépend de la réponse de l'API
                # Il faut adapter selon ce qui est retourné
                self.logger.info(f"📊 Token boosts response: {len(data) if isinstance(data, list) else 'object'}")
                
                # Pour chaque token boosté, récupérer ses détails
                if isinstance(data, list):
                    for item in data[:limit]:
                        try:
                            # Extraire l'adresse du token (structure à adapter)
                            token_address = item.get('tokenAddress') or item.get('address')
                            if token_address:
                                # Récupérer les détails du token
                                token_details = await self._get_token_details(token_address)
                                if token_details:
                                    newest_tokens.append(token_details)
                                    
                            await asyncio.sleep(0.2)  # Rate limiting
                            
                        except Exception as e:
                            self.logger.debug(f"Error processing boost item: {e}")
                            continue
            
            else:
                self.logger.warning(f"Token boosts API returned status {response.status_code}")
                
        except Exception as e:
            self.logger.error(f"Error getting newest tokens via boosts: {e}")
        
        return newest_tokens

    async def _get_token_details(self, token_address: str) -> Optional[Dict]:
        """Récupérer les détails d'un token spécifique"""
        try:
            # Utiliser l'endpoint token-pairs pour obtenir les détails
            response = requests.get(
                f"https://api.dexscreener.com/token-pairs/v1/solana/{token_address}",
                timeout=15,
                headers={
                    'User-Agent': 'DexScreener-Bot/2.0',
                    'Accept': 'application/json',
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and data:
                    pair = data[0]  # Prendre la première paire
                    
                    from datetime import datetime
                    created_at = pair.get('pairCreatedAt')
                    age_hours = 0
                    
                    if created_at:
                        created_time = datetime.fromtimestamp(created_at / 1000)
                        age_hours = (datetime.now() - created_time).total_seconds() / 3600
                    
                    return {
                        'token_address': token_address,
                        'symbol': pair['baseToken'].get('symbol', 'UNKNOWN'),
                        'name': pair['baseToken'].get('name', 'Unknown'),
                        'age_hours': age_hours,
                        'liquidity_usd': pair.get('liquidity', {}).get('usd', 0),
                        'volume_24h': pair.get('volume', {}).get('h24', 0),
                        'price_usd': float(pair.get('priceUsd', 0)) if pair.get('priceUsd') else 0,
                        'dex_id': pair.get('dexId'),
                        'pair_address': pair.get('pairAddress'),
                        'created_timestamp': created_at,
                        'chain_id': 'solana'
                    }
            
            return None
            
        except Exception as e:
            self.logger.debug(f"Error getting token details for {token_address}: {e}")
            return None

    def _is_potentially_trending(self, pair: TradingPair) -> bool:
        """Check if a pair shows trending characteristics"""
        try:
            # Must have recent activity
            if not pair.volume or not pair.volume.h24:
                return False
            
            # Must have reasonable liquidity
            if not pair.liquidity or not pair.liquidity.usd or pair.liquidity.usd < 1000:
                return False
            
            # High volume relative to liquidity
            if pair.volume_to_liquidity_ratio and pair.volume_to_liquidity_ratio > 2.0:
                return True
            
            # Recent pair with significant volume
            if pair.age_hours and pair.age_hours < 168 and pair.volume.h24 > 50000:  # Less than 7 days old
                return True
            
            # High transaction count
            if pair.txns and 'h24' in pair.txns:
                total_txns = pair.txns['h24'].buys + pair.txns['h24'].sells
                if total_txns > 100:
                    return True
            
            return False
            
        except Exception as e:
            self.logger.debug(f"Error checking trending status: {e}")
            return False
    
    def _calculate_trending_score(self, pair: TradingPair) -> float:
        """Calculate trending score for sorting"""
        try:
            score = 0.0
            
            # Volume factor
            if pair.volume and pair.volume.h24:
                score += min(pair.volume.h24 / 100000, 10)  # Max 10 points for volume
            
            # Liquidity factor
            if pair.liquidity and pair.liquidity.usd:
                score += min(pair.liquidity.usd / 50000, 5)  # Max 5 points for liquidity
            
            # Age factor (newer is trendier)
            if pair.age_hours:
                if pair.age_hours < 24:
                    score += 5  # Very new
                elif pair.age_hours < 168:
                    score += 3  # Less than a week
                elif pair.age_hours < 720:
                    score += 1  # Less than a month
            
            # Transaction activity
            if pair.txns and 'h24' in pair.txns:
                total_txns = pair.txns['h24'].buys + pair.txns['h24'].sells
                score += min(total_txns / 100, 5)  # Max 5 points for transactions
            
            # Price change bonus
            if pair.price_change and pair.price_change.h24:
                if pair.price_change.h24 > 20:  # 20%+ gain
                    score += 3
                elif pair.price_change.h24 > 10:
                    score += 2
                elif pair.price_change.h24 > 0:
                    score += 1
            
            return score
            
        except Exception as e:
            self.logger.debug(f"Error calculating trending score: {e}")
            return 0.0
    
    def analyze_market_conditions(self, chain_ids: List[str] = None, limit: int = 1000) -> MarketAnalysis:
        """
        Analyze overall market conditions across specified chains
        
        Args:
            chain_ids: List of chain identifiers to analyze
            limit: Number of pairs to analyze per chain
            
        Returns:
            MarketAnalysis with comprehensive market data
        """
        if not chain_ids:
            chain_ids = [ChainId.SOLANA.value, ChainId.ETHEREUM.value, ChainId.BSC.value]
        
        all_pairs = []
        total_volume_24h = 0
        total_liquidity = 0
        price_changes = []
        
        # Collect data from different searches to get market overview
        search_terms = ['usd', 'eth', 'btc', 'sol']  # Major pairs
        
        for term in search_terms:
            try:
                results = self.search_pairs(term, limit=15)
                if results and results.pairs:
                    for pair in results.pairs:
                        if chain_ids and pair.chain_id not in chain_ids:
                            continue
                        
                        all_pairs.append(pair)
                        
                        # Aggregate metrics
                        if pair.volume and pair.volume.h24:
                            total_volume_24h += pair.volume.h24
                        
                        if pair.liquidity and pair.liquidity.usd:
                            total_liquidity += pair.liquidity.usd
                        
                        if pair.price_change and pair.price_change.h24 is not None:
                            price_changes.append(pair.price_change.h24)
                
                time.sleep(0.5)  # Rate limiting
                
            except Exception as e:
                self.logger.warning(f"Error in market analysis for term '{term}': {e}")
        
        # Calculate averages and identify categories
        avg_price_change = sum(price_changes) / len(price_changes) if price_changes else 0
        
        # Identify different categories of pairs
        trending_tokens = self._identify_trending_from_pairs(all_pairs, limit=10)
        high_volume_pairs = sorted(
            [p for p in all_pairs if p.volume and p.volume.h24 and p.volume.h24 > 100000],
            key=lambda p: p.volume.h24 if p.volume and p.volume.h24 else 0,
            reverse=True
        )[:10]
        
        new_pairs = sorted(
            [p for p in all_pairs if p.age_hours and p.age_hours < 24],
            key=lambda p: p.age_hours if p.age_hours else 0
        )[:10]
        
        # Risk assessment
        risk_assessment = self._assess_market_risk(all_pairs)
        
        return MarketAnalysis(
            total_pairs=len(all_pairs),
            total_volume_24h=total_volume_24h,
            total_liquidity=total_liquidity,
            average_price_change_24h=avg_price_change,
            trending_tokens=trending_tokens,
            high_volume_pairs=high_volume_pairs,
            new_pairs=new_pairs,
            risk_assessment=risk_assessment
        )
    
    def _identify_trending_from_pairs(self, pairs: List[TradingPair], limit: int) -> List[TradingPair]:
        """Identify trending pairs from a list"""
        trending = [p for p in pairs if self._is_potentially_trending(p)]
        trending.sort(key=self._calculate_trending_score, reverse=True)
        return trending[:limit]
    
    def _assess_market_risk(self, pairs: List[TradingPair]) -> Dict[str, Any]:
        """Assess overall market risk from pairs data"""
        risk_factors = {
            'high_volatility_pairs': 0,
            'low_liquidity_pairs': 0,
            'new_pairs_ratio': 0.0,
            'average_liquidity': 0.0,
            'risk_level': 'LOW'
        }
        
        if not pairs:
            return risk_factors
        
        total_liquidity = 0
        liquidity_count = 0
        high_volatility = 0
        low_liquidity = 0
        new_pairs = 0
        
        for pair in pairs:
            # Liquidity analysis
            if pair.liquidity and pair.liquidity.usd:
                total_liquidity += pair.liquidity.usd
                liquidity_count += 1
                
                if pair.liquidity.usd < 10000:  # Low liquidity threshold
                    low_liquidity += 1
            
            # Volatility analysis
            if pair.price_change and pair.price_change.h24:
                if abs(pair.price_change.h24) > 50:  # High volatility threshold
                    high_volatility += 1
            
            # Age analysis
            if pair.age_hours and pair.age_hours < 24:
                new_pairs += 1
        
        # Calculate metrics
        risk_factors['high_volatility_pairs'] = high_volatility
        risk_factors['low_liquidity_pairs'] = low_liquidity
        risk_factors['new_pairs_ratio'] = new_pairs / len(pairs) if pairs else 0
        risk_factors['average_liquidity'] = total_liquidity / liquidity_count if liquidity_count else 0
        
        # Determine overall risk level
        risk_score = 0
        if high_volatility / len(pairs) > 0.3:  # More than 30% high volatility
            risk_score += 3
        if low_liquidity / len(pairs) > 0.4:  # More than 40% low liquidity
            risk_score += 2
        if new_pairs / len(pairs) > 0.5:  # More than 50% new pairs
            risk_score += 2
        
        if risk_score >= 5:
            risk_factors['risk_level'] = 'HIGH'
        elif risk_score >= 3:
            risk_factors['risk_level'] = 'MEDIUM'
        else:
            risk_factors['risk_level'] = 'LOW'
        
        return risk_factors
    
    def get_high_volume_pairs(self, chain_ids: List[str] = None, min_volume: float = 100000, limit: int = 1000) -> List[TradingPair]:
        """
        Get pairs with high trading volume
        
        Args:
            chain_ids: List of chain identifiers to filter by
            min_volume: Minimum 24h volume in USD
            limit: Maximum number of pairs to return
            
        Returns:
            List of high volume TradingPair objects
        """
        high_volume_pairs = []
        
        # Search for major trading pairs that typically have high volume
        major_terms = ['usdt', 'usdc', 'eth', 'btc', 'bnb', 'sol']
        
        for term in major_terms:
            try:
                results = self.search_pairs(term, limit=10)
                if results and results.pairs:
                    for pair in results.pairs:
                        # Filter by chain if specified
                        if chain_ids and pair.chain_id not in chain_ids:
                            continue
                        
                        # Check volume criteria
                        if (pair.volume and pair.volume.h24 and 
                            pair.volume.h24 >= min_volume and
                            pair.liquidity and pair.liquidity.usd and 
                            pair.liquidity.usd >= min_volume / 10):  # Reasonable liquidity
                            
                            high_volume_pairs.append(pair)
                
                time.sleep(0.3)  # Rate limiting
                
            except Exception as e:
                self.logger.warning(f"Error searching high volume pairs for '{term}': {e}")
        
        # Remove duplicates and sort by volume
        seen_addresses = set()
        unique_pairs = []
        
        for pair in high_volume_pairs:
            if pair.pair_address not in seen_addresses:
                seen_addresses.add(pair.pair_address)
                unique_pairs.append(pair)
        
        # Sort by 24h volume descending
        unique_pairs.sort(
            key=lambda p: p.volume.h24 if p.volume and p.volume.h24 else 0,
            reverse=True
        )
        
        return unique_pairs[:limit]
    
    def get_new_pairs(self, chain_ids: List[str] = None, max_age_hours: float = 24, limit: int = 1000) -> List[TradingPair]:
        """
        Get recently created trading pairs
        
        Args:
            chain_ids: List of chain identifiers to filter by
            max_age_hours: Maximum age in hours
            limit: Maximum number of pairs to return
            
        Returns:
            List of new TradingPair objects
        """
        new_pairs = []
        
        # Search various terms to find recently listed tokens
        search_terms = ['new', 'launch', 'token', 'coin', 'meme']
        
        for term in search_terms:
            try:
                results = self.search_pairs(term, limit=15)
                if results and results.pairs:
                    for pair in results.pairs:
                        # Filter by chain if specified
                        if chain_ids and pair.chain_id not in chain_ids:
                            continue
                        
                        # Check age criteria
                        if (pair.age_hours and pair.age_hours <= max_age_hours and
                            pair.liquidity and pair.liquidity.usd and pair.liquidity.usd > 1000):
                            
                            new_pairs.append(pair)
                
                time.sleep(0.3)  # Rate limiting
                
            except Exception as e:
                self.logger.warning(f"Error searching new pairs for '{term}': {e}")
        
        # Remove duplicates and sort by age (newest first)
        seen_addresses = set()
        unique_pairs = []
        
        for pair in new_pairs:
            if pair.pair_address not in seen_addresses:
                seen_addresses.add(pair.pair_address)
                unique_pairs.append(pair)
        
        # Sort by age (newest first)
        unique_pairs.sort(key=lambda p: p.age_hours if p.age_hours else float('inf'))
        
        return unique_pairs[:limit]
    
    def filter_pairs_by_criteria(self, pairs: List[TradingPair], 
                                min_liquidity: float = None,
                                min_volume: float = None,
                                max_age_hours: float = None,
                                min_price_change: float = None,
                                max_price_change: float = None,
                                chain_ids: List[str] = None) -> List[TradingPair]:
        """
        Filter pairs by multiple criteria
        
        Args:
            pairs: List of TradingPair objects to filter
            min_liquidity: Minimum liquidity in USD
            min_volume: Minimum 24h volume in USD
            max_age_hours: Maximum age in hours
            min_price_change: Minimum 24h price change percentage
            max_price_change: Maximum 24h price change percentage
            chain_ids: List of allowed chain identifiers
            
        Returns:
            Filtered list of TradingPair objects
        """
        filtered_pairs = []
        
        for pair in pairs:
            # Chain filter
            if chain_ids and pair.chain_id not in chain_ids:
                continue
            
            # Liquidity filter
            if min_liquidity and (not pair.liquidity or not pair.liquidity.usd or 
                                 pair.liquidity.usd < min_liquidity):
                continue
            
            # Volume filter
            if min_volume and (not pair.volume or not pair.volume.h24 or 
                              pair.volume.h24 < min_volume):
                continue
            
            # Age filter
            if max_age_hours and (not pair.age_hours or pair.age_hours > max_age_hours):
                continue
            
            # Price change filters
            if pair.price_change and pair.price_change.h24 is not None:
                if min_price_change and pair.price_change.h24 < min_price_change:
                    continue
                if max_price_change and pair.price_change.h24 > max_price_change:
                    continue
            elif min_price_change or max_price_change:
                # Skip pairs without price change data if filters are specified
                continue
            
            filtered_pairs.append(pair)
        
        return filtered_pairs
    
    def _parse_pairs_response(self, response_data: Dict) -> DexScreenerResponse:
        """Parse API response into DexScreenerResponse"""
        try:
            pairs = []
            pairs_data = response_data.get('pairs', [])
            
            if isinstance(pairs_data, list):
                for pair_data in pairs_data:
                    pair = self._parse_single_pair(pair_data)
                    if pair:
                        pairs.append(pair)
            
            return DexScreenerResponse(
                schema_version=response_data.get('schemaVersion', '1.0.0'),
                pairs=pairs
            )
            
        except Exception as e:
            self.logger.error(f"Error parsing pairs response: {e}")
            return DexScreenerResponse(
                schema_version='1.0.0',
                pairs=[]
            )
    
    def _parse_single_pair(self, pair_data: Dict) -> Optional[TradingPair]:
        """Parse a single pair from API response"""
        try:
            # Parse base and quote tokens
            base_token_data = pair_data.get('baseToken', {})
            quote_token_data = pair_data.get('quoteToken', {})
            
            base_token = TokenInfo(
                address=base_token_data.get('address', ''),
                name=base_token_data.get('name', 'Unknown'),
                symbol=base_token_data.get('symbol', 'UNKNOWN')
            )
            
            quote_token = TokenInfo(
                address=quote_token_data.get('address', ''),
                name=quote_token_data.get('name', 'Unknown'),
                symbol=quote_token_data.get('symbol', 'UNKNOWN')
            )
            
            # Parse liquidity info
            liquidity_data = pair_data.get('liquidity', {})
            liquidity = None
            if liquidity_data:
                liquidity = LiquidityInfo(
                    usd=liquidity_data.get('usd'),
                    base=liquidity_data.get('base'),
                    quote=liquidity_data.get('quote')
                )
            
            # Parse volume info
            volume_data = pair_data.get('volume', {})
            volume = None
            if volume_data:
                volume = VolumeInfo(
                    h24=volume_data.get('h24'),
                    h6=volume_data.get('h6'),
                    h1=volume_data.get('h1'),
                    m5=volume_data.get('m5')
                )
            
            # Parse price change info
            price_change_data = pair_data.get('priceChange', {})
            price_change = None
            if price_change_data:
                price_change = PriceChangeInfo(
                    h24=price_change_data.get('h24'),
                    h6=price_change_data.get('h6'),
                    h1=price_change_data.get('h1'),
                    m5=price_change_data.get('m5')
                )
            
            # Parse transaction stats
            txns_data = pair_data.get('txns', {})
            txns = None
            if txns_data:
                txns = {}
                for timeframe, txn_data in txns_data.items():
                    if isinstance(txn_data, dict):
                        txns[timeframe] = TransactionStats(
                            buys=txn_data.get('buys', 0),
                            sells=txn_data.get('sells', 0)
                        )
            
            # Parse token metadata
            info_data = pair_data.get('info', {})
            token_info = None
            if info_data:
                websites = []
                if 'websites' in info_data:
                    for website in info_data['websites']:
                        if isinstance(website, dict):
                            websites.append(WebsiteInfo(url=website.get('url', '')))
                
                socials = []
                if 'socials' in info_data:
                    for social in info_data['socials']:
                        if isinstance(social, dict):
                            socials.append(SocialInfo(
                                platform=social.get('platform', ''),
                                handle=social.get('handle', '')
                            ))
                
                token_info = TokenMetadata(
                    image_url=info_data.get('imageUrl'),
                    websites=websites,
                    socials=socials
                )
            
            # Parse boost info
            boosts_data = pair_data.get('boosts', {})
            boosts = None
            if boosts_data:
                boosts = BoostInfo(active=boosts_data.get('active', 0))
            
            # Create TradingPair object
            pair = TradingPair(
                chain_id=pair_data.get('chainId', ''),
                dex_id=pair_data.get('dexId', ''),
                pair_address=pair_data.get('pairAddress', ''),
                base_token=base_token,
                quote_token=quote_token,
                price_native=pair_data.get('priceNative'),
                price_usd=pair_data.get('priceUsd'),
                liquidity=liquidity,
                volume=volume,
                price_change=price_change,
                txns=txns,
                fdv=pair_data.get('fdv'),
                market_cap=pair_data.get('marketCap'),
                pair_created_at=pair_data.get('pairCreatedAt'),
                url=pair_data.get('url'),
                labels=pair_data.get('labels', []),
                info=token_info,
                boosts=boosts
            )
            
            return pair
            
        except Exception as e:
            self.logger.error(f"Error parsing single pair: {e}")
            return None
    
    # === ASYNC METHODS ===
    
    async def get_token_pairs_async(self, token_addresses: List[str]) -> Optional[DexScreenerResponse]:
        """Async version of get_token_pairs"""
        return await self._run_in_executor(self.get_token_pairs, token_addresses)
    
    async def search_pairs_async(self, query: str, limit: int = 1000) -> Optional[DexScreenerResponse]:
        """Async version of search_pairs"""
        return await self._run_in_executor(self.search_pairs, query, limit)
    
    async def get_trending_pairs_async(self, chain_ids: List[str] = None, limit: int = 1000) -> List[TradingPair]:
        """Async version of get_trending_pairs"""
        return await self._run_in_executor(self.get_trending_pairs, chain_ids, limit)
    
    async def analyze_market_conditions_async(self, chain_ids: List[str] = None, limit: int = 1000) -> MarketAnalysis:
        """Async version of analyze_market_conditions"""
        return await self._run_in_executor(self.analyze_market_conditions, chain_ids, limit)
    
    async def _run_in_executor(self, func, *args):
        """Run synchronous function in thread executor"""
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            return await loop.run_in_executor(executor, func, *args)
    
    async def batch_analyze_tokens(self, token_addresses: List[str], batch_size: int = 10) -> Dict[str, DexScreenerResponse]:
        """
        Analyze multiple tokens in batches asynchronously
        
        Args:
            token_addresses: List of token addresses to analyze
            batch_size: Number of tokens per batch (max 30 for DexScreener)
            
        Returns:
            Dictionary mapping token addresses to their DexScreenerResponse
        """
        results = {}
        
        # Split addresses into batches
        batches = [token_addresses[i:i + min(batch_size, 30)] 
                  for i in range(0, len(token_addresses), min(batch_size, 30))]
        
        async def process_batch(batch):
            async with self._request_semaphore:
                response = await self.get_token_pairs_async(batch)
                return batch, response
        
        # Process batches concurrently
        tasks = [process_batch(batch) for batch in batches]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Compile results
        for batch_result in batch_results:
            if isinstance(batch_result, Exception):
                self.logger.error(f"Batch processing error: {batch_result}")
                continue
            
            batch_addresses, response = batch_result
            if response:
                for address in batch_addresses:
                    # Find pairs for this specific token
                    token_pairs = [p for p in response.pairs 
                                 if (p.base_token.address.lower() == address.lower() or 
                                     p.quote_token.address.lower() == address.lower())]
                    
                    if token_pairs:
                        results[address] = DexScreenerResponse(
                            schema_version=response.schema_version,
                            pairs=token_pairs
                        )
        
        return results
    
    # === UTILITY AND ANALYTICS METHODS ===
    
    def get_pair_analytics(self, pair: TradingPair) -> Dict[str, Any]:
        """
        Calculate advanced analytics for a trading pair
        
        Args:
            pair: TradingPair object to analyze
            
        Returns:
            Dictionary with analytical metrics
        """
        analytics = {
            'basic_metrics': {},
            'risk_indicators': {},
            'trading_signals': {},
            'market_position': {}
        }
        
        try:
            # Basic metrics
            analytics['basic_metrics'] = {
                'age_hours': pair.age_hours,
                'current_price_usd': float(pair.price_usd) if pair.price_usd else None,
                'market_cap': pair.market_cap,
                'fdv': pair.fdv,
                'liquidity_usd': pair.liquidity.usd if pair.liquidity else None,
                'volume_24h': pair.volume.h24 if pair.volume else None,
                'price_change_24h': pair.price_change.h24 if pair.price_change else None
            }
            
            # Risk indicators
            risk_score = 0
            risk_factors = []
            
            # Low liquidity risk
            if pair.liquidity and pair.liquidity.usd:
                if pair.liquidity.usd < 10000:
                    risk_score += 3
                    risk_factors.append("Very low liquidity")
                elif pair.liquidity.usd < 50000:
                    risk_score += 1
                    risk_factors.append("Low liquidity")
            
            # Age risk
            if pair.age_hours:
                if pair.age_hours < 1:
                    risk_score += 3
                    risk_factors.append("Very new pair")
                elif pair.age_hours < 24:
                    risk_score += 2
                    risk_factors.append("New pair")
            
            # Volume/liquidity ratio risk
            if pair.volume_to_liquidity_ratio:
                if pair.volume_to_liquidity_ratio > 10:
                    risk_score += 2
                    risk_factors.append("Extremely high volume/liquidity ratio")
                elif pair.volume_to_liquidity_ratio > 5:
                    risk_score += 1
                    risk_factors.append("High volume/liquidity ratio")
            
            # Price volatility risk
            if pair.price_change and pair.price_change.h24:
                if abs(pair.price_change.h24) > 100:
                    risk_score += 3
                    risk_factors.append("Extreme price volatility")
                elif abs(pair.price_change.h24) > 50:
                    risk_score += 2
                    risk_factors.append("High price volatility")
            
            analytics['risk_indicators'] = {
                'risk_score': risk_score,
                'risk_level': 'HIGH' if risk_score >= 6 else 'MEDIUM' if risk_score >= 3 else 'LOW',
                'risk_factors': risk_factors
            }
            
            # Trading signals
            signals = []
            signal_strength = 0
            
            # Volume spike signal
            if pair.volume and pair.volume.h24 and pair.liquidity and pair.liquidity.usd:
                vol_liq_ratio = pair.volume.h24 / pair.liquidity.usd
                if vol_liq_ratio > 3:
                    signals.append("High trading activity")
                    signal_strength += 2
            
            # Price momentum signal
            if pair.price_change:
                if pair.price_change.h24 and pair.price_change.h24 > 20:
                    signals.append("Strong upward momentum")
                    signal_strength += 2
                elif pair.price_change.h24 and pair.price_change.h24 < -20:
                    signals.append("Strong downward momentum")
                    signal_strength -= 2
            
            # Transaction activity signal
            if pair.txns and 'h24' in pair.txns:
                total_txns = pair.txns['h24'].buys + pair.txns['h24'].sells
                if total_txns > 500:
                    signals.append("High transaction activity")
                    signal_strength += 1
            
            analytics['trading_signals'] = {
                'signals': signals,
                'signal_strength': signal_strength,
                'recommendation': self._get_trading_recommendation(signal_strength, risk_score)
            }
            
            # Market position
            analytics['market_position'] = {
                'dex_id': pair.dex_id,
                'chain_id': pair.chain_id,
                'pair_url': pair.url,
                'has_boosts': bool(pair.boosts and pair.boosts.active > 0),
                'labels': pair.labels,
                'social_presence': len(pair.info.socials) if pair.info and pair.info.socials else 0,
                'website_count': len(pair.info.websites) if pair.info and pair.info.websites else 0
            }
            
        except Exception as e:
            self.logger.error(f"Error calculating pair analytics: {e}")
            
        return analytics
    
    def _get_trading_recommendation(self, signal_strength: int, risk_score: int) -> str:
        """Get trading recommendation based on signals and risk"""
        if risk_score >= 6:
            return "AVOID - High Risk"
        elif signal_strength >= 3 and risk_score <= 2:
            return "BUY - Strong Signals, Low Risk"
        elif signal_strength >= 1 and risk_score <= 3:
            return "CONSIDER - Moderate Signals"
        elif signal_strength <= -2:
            return "SELL - Negative Signals"
        else:
            return "HOLD - Neutral"
    
    def compare_pairs(self, pair1: TradingPair, pair2: TradingPair) -> Dict[str, Any]:
        """
        Compare two trading pairs across multiple metrics
        
        Args:
            pair1: First trading pair
            pair2: Second trading pair
            
        Returns:
            Comparison results dictionary
        """
        comparison = {
            'pair1': f"{pair1.base_token.symbol}/{pair1.quote_token.symbol}",
            'pair2': f"{pair2.base_token.symbol}/{pair2.quote_token.symbol}",
            'metrics': {},
            'winner': {}
        }
        
        metrics_to_compare = [
            ('liquidity', lambda p: p.liquidity.usd if p.liquidity else 0),
            ('volume_24h', lambda p: p.volume.h24 if p.volume else 0),
            ('price_change_24h', lambda p: p.price_change.h24 if p.price_change else 0),
            ('market_cap', lambda p: p.market_cap if p.market_cap else 0),
            ('age_hours', lambda p: p.age_hours if p.age_hours else 0),
            ('transaction_count', lambda p: (p.txns['h24'].buys + p.txns['h24'].sells) 
                                         if p.txns and 'h24' in p.txns else 0)
        ]
        
        winner_count = {'pair1': 0, 'pair2': 0}
        
        for metric_name, metric_getter in metrics_to_compare:
            try:
                value1 = metric_getter(pair1)
                value2 = metric_getter(pair2)
                
                comparison['metrics'][metric_name] = {
                    'pair1': value1,
                    'pair2': value2,
                    'difference': value1 - value2 if isinstance(value1, (int, float)) and isinstance(value2, (int, float)) else None
                }
                
                # Determine winner (higher is better, except for age where lower might be better for some use cases)
                if metric_name == 'age_hours':
                    # For age, we'll consider both as neutral for winner calculation
                    continue
                elif value1 > value2:
                    comparison['metrics'][metric_name]['winner'] = 'pair1'
                    winner_count['pair1'] += 1
                elif value2 > value1:
                    comparison['metrics'][metric_name]['winner'] = 'pair2'
                    winner_count['pair2'] += 1
                else:
                    comparison['metrics'][metric_name]['winner'] = 'tie'
                    
            except Exception as e:
                self.logger.error(f"Error comparing metric {metric_name}: {e}")
                comparison['metrics'][metric_name] = {'error': str(e)}
        
        # Overall winner
        if winner_count['pair1'] > winner_count['pair2']:
            comparison['winner']['overall'] = 'pair1'
        elif winner_count['pair2'] > winner_count['pair1']:
            comparison['winner']['overall'] = 'pair2'
        else:
            comparison['winner']['overall'] = 'tie'
        
        comparison['winner']['scores'] = winner_count
        
        return comparison
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics for the analyzer"""
        with self._metrics_lock:
            stats = self._performance_metrics.copy()
        
        # Add circuit breaker stats
        circuit_stats = self.circuit_breaker.get_stats()
        
        # Add health metrics
        health_summary = self.health_metrics.get_health_summary()
        
        # Add cache stats
        cache_info = {
            'strategy': self.cache_manager.strategy.value,
            'cache_size': len(getattr(self.cache_manager, 'cache', {}))
        }
        
        return {
            'performance_metrics': stats,
            'circuit_breaker': circuit_stats,
            'health_metrics': health_summary,
            'cache_info': cache_info,
            'rate_limiter': {
                'requests_in_last_minute': len(self._rate_limiter['request_timestamps']),
                'requests_per_minute_limit': self._rate_limiter['requests_per_minute']
            }
        }
    
    def clear_cache(self) -> bool:
        """Clear all cached data"""
        try:
            if hasattr(self.cache_manager, 'cache'):
                self.cache_manager.cache.clear()
            if hasattr(self.cache_manager, 'cache_expiry'):
                self.cache_manager.cache_expiry.clear()
            
            self.logger.info("DexScreener cache cleared")
            return True
        except Exception as e:
            self.logger.error(f"Error clearing cache: {e}")
            return False
    
    def get_supported_chains(self) -> List[Dict[str, str]]:
        """Get list of supported blockchain networks"""
        return [
            {'id': chain.value, 'name': chain.value.title()} 
            for chain in ChainId
        ]
    
    def validate_token_address(self, address: str, chain_id: str = None) -> bool:
        """
        Validate token address format for given chain
        
        Args:
            address: Token contract address
            chain_id: Blockchain identifier (optional)
            
        Returns:
            True if address format is valid
        """
        if not address or not isinstance(address, str):
            return False
        
        address = address.strip()
        
        # Ethereum-like chains (40 hex chars with 0x prefix)
        ethereum_like = [ChainId.ETHEREUM.value, ChainId.BSC.value, ChainId.POLYGON.value,
                        ChainId.AVALANCHE.value, ChainId.FANTOM.value, ChainId.ARBITRUM.value,
                        ChainId.OPTIMISM.value, ChainId.BASE.value]
        
        if not chain_id or chain_id in ethereum_like:
            if re.match(r'^0x[a-fA-F0-9]{40}', address):
                return True
        
        # Solana (base58, 32-44 chars)
        if not chain_id or chain_id == ChainId.SOLANA.value:
            if 32 <= len(address) <= 44 and not address.startswith('0x'):
                # Basic base58 character check
                base58_chars = set('123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz')
                if all(c in base58_chars for c in address):
                    return True
        
        # Tron (base58, 34 chars starting with T)
        if not chain_id or chain_id == ChainId.TRON.value:
            if len(address) == 34 and address.startswith('T'):
                base58_chars = set('123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz')
                if all(c in base58_chars for c in address):
                    return True
        
        return False


# === UTILITY FUNCTIONS ===

def create_dexscreener_analyzer(config: Dict) -> DexScreenerAnalyzer:
    """Factory function to create a DexScreener analyzer instance"""
    return DexScreenerAnalyzer(config)

def quick_token_lookup(token_address: str, config: Dict = None) -> Optional[DexScreenerResponse]:
    """Quick token lookup utility function"""
    if not config:
        config = {
            'dexscreener': {
                'api_base_url': 'https://api.dexscreener.com/latest',
                'api_timeout': 15,
                'cache_strategy': 'legacy',
                'requests_per_minute': 300
            }
        }
    
    analyzer = DexScreenerAnalyzer(config)
    return analyzer.get_token_pairs([token_address])

async def batch_token_analysis(token_addresses: List[str], config: Dict = None) -> Dict[str, DexScreenerResponse]:
    """Async batch token analysis utility"""
    if not config:
        config = {
            'dexscreener': {
                'api_base_url': 'https://api.dexscreener.com/latest',
                'api_timeout': 20,
                'cache_strategy': 'weak_ref',
                'max_concurrent_requests': 5,
                'requests_per_minute': 300
            }
        }
    
    analyzer = DexScreenerAnalyzer(config)
    return await analyzer.batch_analyze_tokens(token_addresses)

# === EXAMPLE USAGE ===

def example_basic_usage():
    """Example of basic DexScreener usage"""
    config = {
        'dexscreener': {
            'api_base_url': 'https://api.dexscreener.com/latest',
            'api_timeout': 20,
            'cache_strategy': 'hybrid',
            'requests_per_minute': 300,
            'max_concurrent_requests': 10
        }
    }
    
    analyzer = DexScreenerAnalyzer(config)
    
    # Example 1: Get pairs for specific tokens
    token_addresses = [
        'So11111111111111111111111111111111111111112',  # SOL
        'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'   # USDC
    ]
    
    response = analyzer.get_token_pairs(token_addresses)
    if response and response.pairs:
        print(f"Found {len(response.pairs)} trading pairs")
        for pair in response.pairs:
            print(f"  {pair.base_token.symbol}/{pair.quote_token.symbol} - ${pair.price_usd}")
    
    # Example 2: Search for tokens
    search_results = analyzer.search_pairs("PEPE", limit=5)
    if search_results and search_results.pairs:
        print(f"\nFound {len(search_results.pairs)} PEPE-related pairs")
    
    # Example 3: Get trending pairs
    trending = analyzer.get_trending_pairs(chain_ids=[ChainId.SOLANA.value], limit=1000)
    print(f"\nFound {len(trending)} trending pairs on Solana")
    
    # Example 4: Analyze specific pair
    if response and response.pairs:
        pair = response.pairs[0]
        analytics = analyzer.get_pair_analytics(pair)
        print(f"\nAnalytics for {pair.base_token.symbol}/{pair.quote_token.symbol}:")
        print(f"  Risk Level: {analytics['risk_indicators']['risk_level']}")
        print(f"  Recommendation: {analytics['trading_signals']['recommendation']}")

async def example_async_usage():
    """Example of async DexScreener usage"""
    config = {
        'dexscreener': {
            'api_base_url': 'https://api.dexscreener.com/latest',
            'api_timeout': 20,
            'cache_strategy': 'weak_ref',
            'max_concurrent_requests': 15
        }
    }
    
    analyzer = DexScreenerAnalyzer(config)
    
    # Batch analyze multiple tokens
    token_addresses = [
        'So11111111111111111111111111111111111111112',  # SOL
        'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
        'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',  # USDT
        'mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So'   # mSOL
    ]
    
    results = await analyzer.batch_analyze_tokens(token_addresses, batch_size=10)
    
    print(f"Analyzed {len(results)} tokens:")
    for address, response in results.items():
        if response and response.pairs:
            pair = response.pairs[0]  # Get first pair
            print(f"  {address[:8]}... - {pair.base_token.symbol}: ${pair.price_usd}")
    
    # Get market analysis
    market_analysis = await analyzer.analyze_market_conditions_async(
        chain_ids=[ChainId.SOLANA.value, ChainId.ETHEREUM.value]
    )
    
    print(f"\nMarket Analysis:")
    print(f"  Total Volume 24h: ${market_analysis.total_volume_24h:,.2f}")
    print(f"  Total Liquidity: ${market_analysis.total_liquidity:,.2f}")
    print(f"  Average Price Change: {market_analysis.average_price_change_24h:.2f}%")
    print(f"  Risk Level: {market_analysis.risk_assessment['risk_level']}")

def example_advanced_filtering():
    """Example of advanced pair filtering"""
    config = {
        'dexscreener': {
            'api_base_url': 'https://api.dexscreener.com/latest',
            'api_timeout': 20,
            'cache_strategy': 'hybrid'
        }
    }
    
    analyzer = DexScreenerAnalyzer(config)
    
    # Get trending pairs first
    trending_pairs = analyzer.get_trending_pairs(limit=1000)
    
    # Apply multiple filters
    filtered_pairs = analyzer.filter_pairs_by_criteria(
        pairs=trending_pairs,
        min_liquidity=50000,        # At least $50k liquidity
        min_volume=100000,          # At least $100k 24h volume
        max_age_hours=168,          # Less than 7 days old
        min_price_change=10,        # At least 10% positive change
        chain_ids=[ChainId.SOLANA.value, ChainId.ETHEREUM.value]
    )
    
    print(f"Filtered to {len(filtered_pairs)} high-quality pairs:")
    for pair in filtered_pairs[:5]:  # Show top 5
        analytics = analyzer.get_pair_analytics(pair)
        print(f"  {pair.base_token.symbol}/{pair.quote_token.symbol}")
        print(f"    Price: ${pair.price_usd}")
        print(f"    24h Change: {pair.price_change.h24 if pair.price_change else 0:.2f}%")
        print(f"    Liquidity: ${pair.liquidity.usd if pair.liquidity else 0:,.0f}")
        print(f"    Risk: {analytics['risk_indicators']['risk_level']}")
        print(f"    Recommendation: {analytics['trading_signals']['recommendation']}")
        print()

def example_pair_comparison():
    """Example of comparing two trading pairs"""
    config = {
        'dexscreener': {
            'api_base_url': 'https://api.dexscreener.com/latest',
            'api_timeout': 20
        }
    }
    
    analyzer = DexScreenerAnalyzer(config)
    
    # Get pairs for comparison
    sol_pairs = analyzer.search_pairs("SOL/USDC", limit=5)
    eth_pairs = analyzer.search_pairs("ETH/USDC", limit=5)
    
    if (sol_pairs and sol_pairs.pairs and 
        eth_pairs and eth_pairs.pairs):
        
        sol_pair = sol_pairs.pairs[0]
        eth_pair = eth_pairs.pairs[0]
        
        comparison = analyzer.compare_pairs(sol_pair, eth_pair)
        
        print("Pair Comparison:")
        print(f"  {comparison['pair1']} vs {comparison['pair2']}")
        print(f"  Overall Winner: {comparison['winner']['overall']}")
        print()
        
        for metric, data in comparison['metrics'].items():
            if 'winner' in data:
                print(f"  {metric.title()}:")
                print(f"    {comparison['pair1']}: {data['pair1']}")
                print(f"    {comparison['pair2']}: {data['pair2']}")
                print(f"    Winner: {data['winner']}")
                print()

def test_analyzer_performance():
    """Test analyzer performance and health metrics"""
    config = {
        'dexscreener': {
            'api_base_url': 'https://api.dexscreener.com/latest',
            'api_timeout': 20,
            'cache_strategy': 'hybrid',
            'max_concurrent_requests': 10,
            'health_metrics': {
                'enable_system_metrics': True,
                'metrics_retention_hours': 24
            }
        }
    }
    
    analyzer = DexScreenerAnalyzer(config)
    
    # Test basic functionality
    print("Testing DexScreener analyzer...")
    
    # Test address validation
    test_addresses = [
        ('So11111111111111111111111111111111111111112', 'solana'),  # Valid Solana
        ('0xA0b86a33E6441b45b91b5D8c80fB70D5f8Ff94b5', 'ethereum'),  # Valid Ethereum
        ('invalid_address', None),  # Invalid
        ('0x123', 'ethereum')  # Invalid Ethereum
    ]
    
    print("\nAddress Validation Tests:")
    for address, chain in test_addresses:
        is_valid = analyzer.validate_token_address(address, chain)
        print(f"  {address[:20]}... on {chain or 'any'}: {is_valid}")
    
    # Test API calls
    print("\nTesting API calls...")
    response = analyzer.search_pairs("USDC", limit=3)
    
    if response and response.pairs:
        print(f"  Found {len(response.pairs)} pairs for USDC")
        
        # Test analytics on first pair
        pair = response.pairs[0]
        analytics = analyzer.get_pair_analytics(pair)
        print(f"  Analytics for {pair.base_token.symbol}/{pair.quote_token.symbol}:")
        print(f"    Risk: {analytics['risk_indicators']['risk_level']}")
        print(f"    Signals: {len(analytics['trading_signals']['signals'])}")
    
    # Get performance stats
    stats = analyzer.get_performance_stats()
    print(f"\nPerformance Stats:")
    print(f"  Total Requests: {stats['performance_metrics']['total_requests']}")
    print(f"  Success Rate: {stats['performance_metrics']['successful_requests'] / max(stats['performance_metrics']['total_requests'], 1) * 100:.1f}%")
    print(f"  Average Response Time: {stats['performance_metrics']['average_response_time']:.3f}s")
    print(f"  Circuit Breaker State: {stats['circuit_breaker']['state']}")
    
    # Test supported chains
    chains = analyzer.get_supported_chains()
    print(f"\nSupported Chains: {len(chains)}")
    for chain in chains[:5]:  # Show first 5
        print(f"  {chain['id']}: {chain['name']}")
    
    print("\n✅ DexScreener analyzer test completed!")

# === INTEGRATION HELPERS ===

class DexScreenerIntegration:
    """Helper class for integrating DexScreener with trading bots"""
    
    def __init__(self, config: Dict, advanced_logger=None):
        self.analyzer = DexScreenerAnalyzer(config)
        if advanced_logger:
            self.analyzer.set_advanced_logger(advanced_logger)
        
        self.logger = logging.getLogger(__name__)
    
    def get_token_trading_data(self, token_address: str, chain_id: str = None) -> Dict[str, Any]:
        """Get comprehensive trading data for a token"""
        try:
            # Validate address
            if not self.analyzer.validate_token_address(token_address, chain_id):
                return {'error': 'Invalid token address format'}
            
            # Get pairs data
            response = self.analyzer.get_token_pairs([token_address])
            if not response or not response.pairs:
                return {'error': 'No trading pairs found'}
            
            # Find best pair (highest liquidity)
            best_pair = max(response.pairs, 
                          key=lambda p: p.liquidity.usd if p.liquidity and p.liquidity.usd else 0)
            
            # Get analytics
            analytics = self.analyzer.get_pair_analytics(best_pair)
            
            return {
                'token_address': token_address,
                'pair_info': {
                    'dex': best_pair.dex_id,
                    'chain': best_pair.chain_id,
                    'pair_address': best_pair.pair_address,
                    'base_token': best_pair.base_token.symbol,
                    'quote_token': best_pair.quote_token.symbol
                },
                'price_data': {
                    'current_price_usd': float(best_pair.price_usd) if best_pair.price_usd else None,
                    'price_change_24h': best_pair.price_change.h24 if best_pair.price_change else None,
                    'price_change_1h': best_pair.price_change.h1 if best_pair.price_change else None
                },
                'market_data': {
                    'market_cap': best_pair.market_cap,
                    'fdv': best_pair.fdv,
                    'liquidity_usd': best_pair.liquidity.usd if best_pair.liquidity else None,
                    'volume_24h': best_pair.volume.h24 if best_pair.volume else None,
                    'age_hours': best_pair.age_hours
                },
                'trading_metrics': {
                    'buys_24h': best_pair.txns['h24'].buys if best_pair.txns and 'h24' in best_pair.txns else 0,
                    'sells_24h': best_pair.txns['h24'].sells if best_pair.txns and 'h24' in best_pair.txns else 0,
                    'volume_to_liquidity_ratio': best_pair.volume_to_liquidity_ratio
                },
                'risk_assessment': analytics['risk_indicators'],
                'trading_signals': analytics['trading_signals'],
                'recommendation': analytics['trading_signals']['recommendation'],
                'last_updated': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"Error getting trading data for {token_address}: {e}")
            return {'error': f'Failed to get trading data: {str(e)}'}
    
    def is_token_suitable_for_trading(self, token_address: str, 
                                    min_liquidity: float = 50000,
                                    max_age_hours: float = 168,
                                    max_risk_score: int = 5) -> Dict[str, Any]:
        """Check if token meets trading criteria"""
        trading_data = self.get_token_trading_data(token_address)
        
        if 'error' in trading_data:
            return {'suitable': False, 'reason': trading_data['error']}
        
        reasons = []
        
        # Check liquidity
        liquidity = trading_data['market_data']['liquidity_usd']
        if not liquidity or liquidity < min_liquidity:
            reasons.append(f"Low liquidity: ${liquidity:,.0f} < ${min_liquidity:,.0f}")
        
        # Check age
        age_hours = trading_data['market_data']['age_hours']
        if age_hours and age_hours > max_age_hours:
            reasons.append(f"Token too old: {age_hours:.1f}h > {max_age_hours}h")
        
        # Check risk
        risk_score = trading_data['risk_assessment']['risk_score']
        if risk_score > max_risk_score:
            reasons.append(f"High risk score: {risk_score} > {max_risk_score}")
        
        # Check for critical risk factors
        if trading_data['risk_assessment']['risk_level'] == 'HIGH':
            reasons.append("High risk level detected")
        
        suitable = len(reasons) == 0
        
        return {
            'suitable': suitable,
            'reasons': reasons if not suitable else [],
            'trading_data': trading_data,
            'criteria_used': {
                'min_liquidity': min_liquidity,
                'max_age_hours': max_age_hours,
                'max_risk_score': max_risk_score
            }
        }
    
    async def monitor_token_price(self, token_address: str, 
                                price_change_threshold: float = 10.0,
                                check_interval: int = 60) -> Dict[str, Any]:
        """Monitor token price changes (basic implementation)"""
        initial_data = self.get_token_trading_data(token_address)
        
        if 'error' in initial_data:
            return initial_data
        
        initial_price = initial_data['price_data']['current_price_usd']
        
        if not initial_price:
            return {'error': 'No price data available'}
        
        await asyncio.sleep(check_interval)
        
        current_data = self.get_token_trading_data(token_address)
        
        if 'error' in current_data:
            return current_data
        
        current_price = current_data['price_data']['current_price_usd']
        
        if not current_price:
            return {'error': 'No current price data'}
        
        price_change_percent = ((current_price - initial_price) / initial_price) * 100
        
        return {
            'token_address': token_address,
            'initial_price': initial_price,
            'current_price': current_price,
            'price_change_percent': price_change_percent,
            'threshold_exceeded': abs(price_change_percent) >= price_change_threshold,
            'monitoring_period': check_interval,
            'timestamp': time.time()
        }

# === MAIN EXECUTION ===

if __name__ == "__main__":
    print("DexScreener API Integration Module")
    print("=" * 50)
    
    # Test basic functionality
    try:
        test_analyzer_performance()
        
        print("\nRunning examples...")
        example_basic_usage()
        
        print("\nRunning advanced filtering example...")
        example_advanced_filtering()
        
        print("\n✅ All tests completed successfully!")
        
    except Exception as e:
        print(f"❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()

    # Example of async usage
    try:
        print("\nTesting async functionality...")
        asyncio.run(example_async_usage())
        print("✅ Async tests completed!")
        
    except Exception as e:
        print(f"❌ Async test error: {e}")

    print("\n" + "=" * 50)
    print("DexScreener module ready for integration!")