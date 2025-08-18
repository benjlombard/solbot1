"""
Token Type Detector
Intelligent detection of token types (DEX listed, Pump.fun, etc.) with caching and optimization.
"""
import asyncio
import aiohttp
import time
import logging
from typing import Dict, Optional, Tuple, List, Set
from dataclasses import dataclass
from enum import Enum
import json

from ..models.token_data import TokenType, TokenTypeResult
from ..api_clients.dexscreener_client import DexScreenerClient
from ..api_clients.pumpfun_client import PumpFunClient


@dataclass
class DetectionCache:
    """Cache entry for token type detection"""
    token_type: TokenType
    confidence: float
    timestamp: float
    source_data: Dict
    ttl_seconds: int = 3600  # 1 hour default TTL
    
    def is_expired(self) -> bool:
        """Check if cache entry is expired"""
        return time.time() - self.timestamp > self.ttl_seconds


@dataclass
class DetectionStrategy:
    """Strategy for detecting token types"""
    name: str
    apis_to_check: List[str]
    timeout_seconds: float
    confidence_threshold: float
    fallback_enabled: bool = True


class TokenTypeDetector:
    """
    Intelligent token type detection with caching and optimization
    """
    
    def __init__(
        self,
        dex_client: DexScreenerClient,
        pump_client: PumpFunClient,
        logger: Optional[logging.Logger] = None
    ):
        self.dex_client = dex_client
        self.pump_client = pump_client
        self.logger = logger or logging.getLogger(__name__)
        
        # Detection cache
        self.cache: Dict[str, DetectionCache] = {}
        self.cache_hits = 0
        self.cache_misses = 0
        
        # Detection strategies
        self.strategies = {
            'fast': DetectionStrategy(
                name='fast',
                apis_to_check=['dexscreener', 'pumpfun'],
                timeout_seconds=10.0,
                confidence_threshold=0.7
            ),
            'comprehensive': DetectionStrategy(
                name='comprehensive',
                apis_to_check=['dexscreener', 'pumpfun'],
                timeout_seconds=30.0,
                confidence_threshold=0.8
            ),
            'pump_priority': DetectionStrategy(
                name='pump_priority',
                apis_to_check=['pumpfun', 'dexscreener'],
                timeout_seconds=15.0,
                confidence_threshold=0.8
            )
        }
        
        # Performance tracking
        self.detection_stats = {
            'total_detections': 0,
            'successful_detections': 0,
            'failed_detections': 0,
            'avg_detection_time': 0.0,
            'by_token_type': {
                TokenType.DEX_LISTED: 0,
                TokenType.PUMP_PREBOND: 0,
                TokenType.PUMP_GRADUATED: 0,
                TokenType.UNKNOWN: 0
            },
            'api_usage': {
                'dexscreener': 0,
                'pumpfun': 0
            }
        }
        
        # Known token patterns for optimization
        self.known_patterns = {
            'pump_indicators': [
                'pump', 'pumpfun', 'prebond', 'bonding'
            ],
            'dex_indicators': [
                'raydium', 'orca', 'jupiter'
            ]
        }
        
        self.logger.info("🔍 Token Type Detector initialized")
    
    def detect_token_type(
        self, 
        token_address: str, 
        strategy: str = 'fast',
        use_cache: bool = True
    ) -> TokenTypeResult:
        """
        Detect token type synchronously
        
        Args:
            token_address: Token address to analyze
            strategy: Detection strategy to use
            use_cache: Whether to use cached results
            
        Returns:
            TokenTypeResult with detected type and confidence
        """
        return asyncio.run(self.detect_token_type_async(token_address, strategy, use_cache))
    
    async def detect_token_type_async(
        self, 
        token_address: str, 
        strategy: str = 'fast',
        use_cache: bool = True
    ) -> TokenTypeResult:
        """
        Detect token type asynchronously
        
        Args:
            token_address: Token address to analyze
            strategy: Detection strategy to use
            use_cache: Whether to use cached results
            
        Returns:
            TokenTypeResult with detected type and confidence
        """
        start_time = time.time()
        self.logger.debug(f"🔍 Detecting token type for {token_address[:8]}... using {strategy} strategy")
        
        try:
            # Check cache first
            if use_cache:
                cached_result = self._get_from_cache(token_address)
                if cached_result:
                    self.cache_hits += 1
                    self.logger.debug(f"✅ Cache hit for {token_address[:8]}... -> {cached_result.token_type.value}")
                    return cached_result
            
            self.cache_misses += 1
            
            # Get detection strategy
            detection_strategy = self.strategies.get(strategy, self.strategies['fast'])
            
            # Run detection
            result = await self._run_detection(token_address, detection_strategy)
            
            # Cache result
            if use_cache:
                self._store_in_cache(token_address, result)
            
            # Update statistics
            detection_time = time.time() - start_time
            self._update_detection_stats(result, detection_time)
            
            self.logger.debug(
                f"✅ Detection completed for {token_address[:8]}... -> "
                f"{result.token_type.value} (confidence: {result.confidence:.2f}) in {detection_time:.2f}s"
            )
            
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Error detecting token type for {token_address[:8]}...: {e}")
            
            # Return unknown with low confidence
            error_result = TokenTypeResult(
                token_type=TokenType.UNKNOWN,
                confidence=0.1,
                source_data={'error': str(e)}
            )
            
            self._update_detection_stats(error_result, time.time() - start_time, success=False)
            return error_result
    
    async def detect_tokens_batch(
        self, 
        token_addresses: List[str], 
        strategy: str = 'fast',
        use_cache: bool = True
    ) -> Dict[str, TokenTypeResult]:
        """
        Detect token types for multiple tokens in batch
        
        Args:
            token_addresses: List of token addresses
            strategy: Detection strategy to use
            use_cache: Whether to use cached results
            
        Returns:
            Dictionary mapping token_address -> TokenTypeResult
        """
        if not token_addresses:
            return {}
        
        self.logger.info(f"🔍 Batch detecting token types for {len(token_addresses)} tokens")
        
        # Check cache for all tokens first
        results = {}
        uncached_tokens = []
        
        if use_cache:
            for token_addr in token_addresses:
                cached_result = self._get_from_cache(token_addr)
                if cached_result:
                    results[token_addr] = cached_result
                    self.cache_hits += 1
                else:
                    uncached_tokens.append(token_addr)
                    self.cache_misses += 1
        else:
            uncached_tokens = token_addresses.copy()
            self.cache_misses += len(token_addresses)
        
        if uncached_tokens:
            self.logger.debug(f"🔍 Need to detect {len(uncached_tokens)} tokens (cache hits: {len(results)})")
            
            # Detect uncached tokens
            detection_strategy = self.strategies.get(strategy, self.strategies['fast'])
            batch_results = await self._run_batch_detection(uncached_tokens, detection_strategy)
            
            # Store in cache and update results
            for token_addr, result in batch_results.items():
                if use_cache:
                    self._store_in_cache(token_addr, result)
                results[token_addr] = result
        
        self.logger.info(f"✅ Batch detection completed: {len(results)} results")
        return results
    
    def _get_from_cache(self, token_address: str) -> Optional[TokenTypeResult]:
        """Get token type from cache if available and not expired"""
        cache_entry = self.cache.get(token_address)
        
        if cache_entry and not cache_entry.is_expired():
            return TokenTypeResult(
                token_type=cache_entry.token_type,
                confidence=cache_entry.confidence,
                source_data=cache_entry.source_data.copy()
            )
        
        # Remove expired entry
        if cache_entry:
            del self.cache[token_address]
        
        return None
    
    def _store_in_cache(self, token_address: str, result: TokenTypeResult):
        """Store detection result in cache"""
        # Determine TTL based on confidence and token type
        if result.confidence >= 0.9:
            ttl = 7200  # 2 hours for high confidence
        elif result.confidence >= 0.7:
            ttl = 3600  # 1 hour for medium confidence
        else:
            ttl = 1800  # 30 minutes for low confidence
        
        self.cache[token_address] = DetectionCache(
            token_type=result.token_type,
            confidence=result.confidence,
            timestamp=time.time(),
            source_data=result.source_data.copy(),
            ttl_seconds=ttl
        )
        
        # Limit cache size
        if len(self.cache) > 10000:
            self._cleanup_cache()
    
    def _cleanup_cache(self):
        """Clean up expired cache entries"""
        expired_keys = []
        for token_addr, cache_entry in self.cache.items():
            if cache_entry.is_expired():
                expired_keys.append(token_addr)
        
        for key in expired_keys:
            del self.cache[key]
        
        self.logger.debug(f"🧹 Cleaned up {len(expired_keys)} expired cache entries")
    
    async def _run_detection(self, token_address: str, strategy: DetectionStrategy) -> TokenTypeResult:
        """Run detection using the specified strategy"""
        
        # Quick heuristic check first
        heuristic_result = self._heuristic_detection(token_address)
        if heuristic_result and heuristic_result.confidence >= strategy.confidence_threshold:
            return heuristic_result
        
        # API-based detection
        detection_tasks = []
        
        for api_name in strategy.apis_to_check:
            if api_name == 'dexscreener':
                task = self._detect_from_dexscreener(token_address)
            elif api_name == 'pumpfun':
                task = self._detect_from_pumpfun(token_address)
            else:
                continue
            
            detection_tasks.append((api_name, task))
        
        if not detection_tasks:
            return TokenTypeResult(
                token_type=TokenType.UNKNOWN,
                confidence=0.1,
                source_data={'error': 'No APIs available'}
            )
        
        # Run detection tasks with timeout
        try:
            # Execute tasks concurrently with timeout
            timeout = aiohttp.ClientTimeout(total=strategy.timeout_seconds)
            
            results = []
            for api_name, task in detection_tasks:
                try:
                    result = await asyncio.wait_for(task, timeout=strategy.timeout_seconds)
                    if result:
                        results.append((api_name, result))
                        self.detection_stats['api_usage'][api_name] += 1
                except asyncio.TimeoutError:
                    self.logger.debug(f"⏰ {api_name} detection timeout for {token_address[:8]}...")
                except Exception as e:
                    self.logger.debug(f"❌ {api_name} detection error for {token_address[:8]}...: {e}")
            
            # Analyze results and determine best match
            if results:
                return self._analyze_detection_results(results)
            else:
                return TokenTypeResult(
                    token_type=TokenType.UNKNOWN,
                    confidence=0.2,
                    source_data={'reason': 'no_api_results'}
                )
                
        except Exception as e:
            self.logger.error(f"Detection failed for {token_address[:8]}...: {e}")
            return TokenTypeResult(
                token_type=TokenType.UNKNOWN,
                confidence=0.1,
                source_data={'error': str(e)}
            )
    
    async def _run_batch_detection(
        self, 
        token_addresses: List[str], 
        strategy: DetectionStrategy
    ) -> Dict[str, TokenTypeResult]:
        """Run batch detection for multiple tokens"""
        
        # For now, run individual detections concurrently
        # This could be optimized with actual batch APIs in the future
        
        detection_tasks = [
            self._run_detection(token_addr, strategy) 
            for token_addr in token_addresses
        ]
        
        results = await asyncio.gather(*detection_tasks, return_exceptions=True)
        
        batch_results = {}
        for i, result in enumerate(results):
            token_addr = token_addresses[i]
            
            if isinstance(result, Exception):
                self.logger.error(f"Batch detection failed for {token_addr[:8]}...: {result}")
                batch_results[token_addr] = TokenTypeResult(
                    token_type=TokenType.UNKNOWN,
                    confidence=0.1,
                    source_data={'error': str(result)}
                )
            else:
                batch_results[token_addr] = result
        
        return batch_results
    
    def _heuristic_detection(self, token_address: str) -> Optional[TokenTypeResult]:
        """Quick heuristic-based detection using patterns"""
        
        # This is a placeholder for pattern-based detection
        # Could include:
        # - Known token address patterns
        # - Symbol/name patterns
        # - Metadata patterns
        
        # For now, return None to always use API detection
        return None
    
    async def _detect_from_dexscreener(self, token_address: str) -> Optional[TokenTypeResult]:
        """Detect token type from DexScreener API"""
        try:
            async with aiohttp.ClientSession() as session:
                token_data = await self.dex_client.get_token_data_async(session, token_address)
            
            if token_data and token_data.market_cap > 1000:
                # Determine if it's graduated pump token or native DEX token
                if (hasattr(token_data, 'is_pump_fun') and token_data.is_pump_fun) or \
                   (hasattr(token_data, 'launchpad_name') and 'pump' in str(token_data.launchpad_name).lower()):
                    token_type = TokenType.PUMP_GRADUATED
                else:
                    token_type = TokenType.DEX_LISTED
                
                return TokenTypeResult(
                    token_type=token_type,
                    confidence=0.85,
                    source_data={
                        'market_cap': token_data.market_cap,
                        'price_usd': token_data.price_usd,
                        'volume_24h': token_data.volume_24h,
                        'source': 'dexscreener'
                    }
                )
            
            return None
            
        except Exception as e:
            self.logger.debug(f"DexScreener detection error: {e}")
            return None
    
    async def _detect_from_pumpfun(self, token_address: str) -> Optional[TokenTypeResult]:
        """Detect token type from Pump.fun API"""
        try:
            async with aiohttp.ClientSession() as session:
                token_data = await self.pump_client.get_token_data_async(session, token_address)
            
            if token_data:
                # Determine prebond vs graduated based on bonding curve progress
                if token_data.bonding_curve_progress < 100:
                    token_type = TokenType.PUMP_PREBOND
                    confidence = 0.95
                else:
                    token_type = TokenType.PUMP_GRADUATED
                    confidence = 0.90
                
                return TokenTypeResult(
                    token_type=token_type,
                    confidence=confidence,
                    source_data={
                        'bonding_curve_progress': token_data.bonding_curve_progress,
                        'market_cap': token_data.market_cap,
                        'holder_count': token_data.holder_count,
                        'creator_address': token_data.creator_address,
                        'source': 'pumpfun'
                    },
                    needs_pump_enrichment=True,
                    needs_dex_enrichment=(token_type == TokenType.PUMP_GRADUATED)
                )
            
            return None
            
        except Exception as e:
            self.logger.debug(f"Pump.fun detection error: {e}")
            return None
    
    def _analyze_detection_results(self, results: List[Tuple[str, TokenTypeResult]]) -> TokenTypeResult:
        """Analyze multiple detection results and return the best match"""
        
        if not results:
            return TokenTypeResult(
                token_type=TokenType.UNKNOWN,
                confidence=0.1,
                source_data={'reason': 'no_results'}
            )
        
        # If only one result, return it
        if len(results) == 1:
            api_name, result = results[0]
            result.source_data['detected_by'] = api_name
            return result
        
        # Multiple results - analyze for best match
        pump_result = None
        dex_result = None
        
        for api_name, result in results:
            if api_name == 'pumpfun':
                pump_result = result
            elif api_name == 'dexscreener':
                dex_result = result
        
        # Decision logic
        if pump_result and pump_result.token_type in [TokenType.PUMP_PREBOND, TokenType.PUMP_GRADUATED]:
            # Pump.fun found the token, trust this result
            pump_result.source_data['detected_by'] = 'pumpfun'
            pump_result.source_data['confirmed_by'] = [api for api, _ in results]
            return pump_result
        
        elif dex_result and dex_result.token_type == TokenType.DEX_LISTED:
            # DexScreener found it as DEX token
            dex_result.source_data['detected_by'] = 'dexscreener'
            dex_result.source_data['confirmed_by'] = [api for api, _ in results]
            return dex_result
        
        else:
            # Conflicting or unclear results
            # Return the result with highest confidence
            best_result = max(results, key=lambda x: x[1].confidence)[1]
            best_result.source_data['detected_by'] = 'multiple'
            best_result.source_data['all_results'] = [
                {'api': api, 'type': result.token_type.value, 'confidence': result.confidence}
                for api, result in results
            ]
            
            # Lower confidence due to ambiguity
            best_result.confidence *= 0.8
            
            return best_result
    
    def _update_detection_stats(
        self, 
        result: TokenTypeResult, 
        detection_time: float, 
        success: bool = True
    ):
        """Update detection statistics"""
        self.detection_stats['total_detections'] += 1
        
        if success:
            self.detection_stats['successful_detections'] += 1
            self.detection_stats['by_token_type'][result.token_type] += 1
        else:
            self.detection_stats['failed_detections'] += 1
        
        # Update average detection time
        total_time = (self.detection_stats['avg_detection_time'] * 
                     (self.detection_stats['total_detections'] - 1))
        self.detection_stats['avg_detection_time'] = (
            (total_time + detection_time) / self.detection_stats['total_detections']
        )
    
    def get_detection_statistics(self) -> Dict:
        """Get current detection statistics"""
        stats = self.detection_stats.copy()
        
        # Add cache statistics
        stats['cache'] = {
            'size': len(self.cache),
            'hits': self.cache_hits,
            'misses': self.cache_misses,
            'hit_rate': (self.cache_hits / (self.cache_hits + self.cache_misses) * 100) 
                       if (self.cache_hits + self.cache_misses) > 0 else 0.0
        }
        
        # Add success rate
        if stats['total_detections'] > 0:
            stats['success_rate'] = (stats['successful_detections'] / stats['total_detections']) * 100
        else:
            stats['success_rate'] = 0.0
        
        # Convert token type enum keys to strings for JSON serialization
        stats['by_token_type'] = {
            token_type.value: count 
            for token_type, count in stats['by_token_type'].items()
        }
        
        return stats
    
    def clear_cache(self):
        """Clear the detection cache"""
        cleared_count = len(self.cache)
        self.cache.clear()
        self.logger.info(f"🧹 Cleared {cleared_count} cache entries")
    
    def get_cache_info(self) -> Dict:
        """Get detailed cache information"""
        now = time.time()
        
        cache_info = {
            'total_entries': len(self.cache),
            'by_token_type': {},
            'by_age': {'fresh': 0, 'aging': 0, 'stale': 0},
            'by_confidence': {'high': 0, 'medium': 0, 'low': 0},
            'memory_usage_estimate': len(self.cache) * 200  # Rough estimate in bytes
        }
        
        for token_addr, cache_entry in self.cache.items():
            # Count by token type
            type_str = cache_entry.token_type.value
            cache_info['by_token_type'][type_str] = cache_info['by_token_type'].get(type_str, 0) + 1
            
            # Count by age
            age = now - cache_entry.timestamp
            if age < 300:  # < 5 minutes
                cache_info['by_age']['fresh'] += 1
            elif age < 1800:  # < 30 minutes
                cache_info['by_age']['aging'] += 1
            else:
                cache_info['by_age']['stale'] += 1
            
            # Count by confidence
            if cache_entry.confidence >= 0.8:
                cache_info['by_confidence']['high'] += 1
            elif cache_entry.confidence >= 0.5:
                cache_info['by_confidence']['medium'] += 1
            else:
                cache_info['by_confidence']['low'] += 1
        
        return cache_info
    
    def reset_statistics(self):
        """Reset all detection statistics"""
        self.detection_stats = {
            'total_detections': 0,
            'successful_detections': 0,
            'failed_detections': 0,
            'avg_detection_time': 0.0,
            'by_token_type': {
                TokenType.DEX_LISTED: 0,
                TokenType.PUMP_PREBOND: 0,
                TokenType.PUMP_GRADUATED: 0,
                TokenType.UNKNOWN: 0
            },
            'api_usage': {
                'dexscreener': 0,
                'pumpfun': 0
            }
        }
        
        self.cache_hits = 0
        self.cache_misses = 0
        
        self.logger.info("📊 Token type detector statistics reset")
    
    def update_strategy(self, strategy_name: str, strategy: DetectionStrategy):
        """Update or add a detection strategy"""
        self.strategies[strategy_name] = strategy
        self.logger.info(f"🔧 Updated detection strategy: {strategy_name}")
    
    def get_health_status(self) -> Dict:
        """Get health status of the detector and its dependencies"""
        return {
            'detector_healthy': True,
            'cache_size': len(self.cache),
            'cache_hit_rate': (self.cache_hits / (self.cache_hits + self.cache_misses) * 100) 
                             if (self.cache_hits + self.cache_misses) > 0 else 0.0,
            'total_detections': self.detection_stats['total_detections'],
            'success_rate': (self.detection_stats['successful_detections'] / 
                           self.detection_stats['total_detections'] * 100) 
                          if self.detection_stats['total_detections'] > 0 else 0.0,
            'avg_detection_time': self.detection_stats['avg_detection_time'],
            'strategies_available': list(self.strategies.keys())
        }