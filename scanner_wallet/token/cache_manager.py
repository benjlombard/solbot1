"""
Solana Wallet Monitor - Cache Manager
Intelligent caching system for token metadata and account data
"""

import time
import json
import pickle
import hashlib
import threading
from typing import Dict, List, Optional, Any, Tuple, Callable
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

# Core imports with fallbacks
try:
    from core.logger import get_logger
    from core.config import get_config
    from utils.helpers import get_current_timestamp
    from models.token import Token, TokenAccount
    from constants import CACHE_SETTINGS
    
except ImportError as e:
    # Fallback implementations
    import logging
    def get_logger(name=None):
        return logging.getLogger(name or 'cache_manager')
    
    def get_config():
        return type('Config', (), {'cache': type('CacheConfig', (), {
            'enabled': True,
            'ttl': 3600,
            'max_size': 1000,
            'cleanup_interval': 300
        })})()
    
    def get_current_timestamp(): return int(time.time())
    
    CACHE_SETTINGS = {
        'default_ttl': 3600,
        'max_size': 1000,
        'cleanup_interval': 300,
        'compression_threshold': 1000
    }

logger = get_logger(__name__)

@dataclass
class CacheEntry:
    """Represents a cached item with metadata"""
    value: Any
    timestamp: int
    ttl: int
    hits: int = 0
    misses: int = 0
    size: int = 0
    tags: List[str] = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []
    
    @property
    def is_expired(self) -> bool:
        """Check if entry has expired"""
        return get_current_timestamp() > self.timestamp + self.ttl
    
    @property
    def age(self) -> int:
        """Get age in seconds"""
        return get_current_timestamp() - self.timestamp

class TokenCacheManager:
    """
    Intelligent caching system for token metadata and accounts
    Features: LRU eviction, TTL expiration, tagging, statistics
    """
    
    def __init__(self, cache_name: str = "token_cache"):
        self.config = get_config()
        self.cache_name = cache_name
        self.cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self.lock = threading.RLock()
        self.stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0,
            'expirations': 0,
            'total_size': 0,
            'max_size': self.config.cache.max_size if hasattr(self.config, 'cache') else CACHE_SETTINGS['max_size'],
            'ttl': self.config.cache.ttl if hasattr(self.config, 'cache') else CACHE_SETTINGS['default_ttl']
        }
        
        # Background cleanup thread
        self.cleanup_thread = None
        self.cleanup_running = False
        self.start_cleanup_thread()
        
        logger.info(f"✅ Token Cache Manager initialized: {cache_name}")
    
    def _calculate_size(self, value: Any) -> int:
        """Calculate approximate size of cached value in bytes"""
        try:
            if isinstance(value, (str, int, float)):
                return len(str(value))
            elif isinstance(value, dict):
                return len(json.dumps(value))
            elif isinstance(value, (Token, TokenAccount)):
                return len(json.dumps(value.to_dict()))
            else:
                return len(pickle.dumps(value))
        except Exception:
            return 100  # Default fallback
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        with self.lock:
            if key in self.cache:
                entry = self.cache[key]
                
                if entry.is_expired:
                    self._remove_expired(key)
                    self.stats['expirations'] += 1
                    self.stats['misses'] += 1
                    return None
                
                # Move to end (LRU)
                self.cache.move_to_end(key)
                entry.hits += 1
                self.stats['hits'] += 1
                
                logger.debug(f"📦 Cache HIT: {key}")
                return entry.value
            
            self.stats['misses'] += 1
            logger.debug(f"📦 Cache MISS: {key}")
            return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None, tags: List[str] = None) -> bool:
        """Set value in cache"""
        with self.lock:
            try:
                ttl = ttl or self.stats['ttl']
                size = self._calculate_size(value)
                
                # Create cache entry
                entry = CacheEntry(
                    value=value,
                    timestamp=get_current_timestamp(),
                    ttl=ttl,
                    size=size,
                    tags=tags or []
                )
                
                # Handle key already exists
                if key in self.cache:
                    old_entry = self.cache[key]
                    self.stats['total_size'] -= old_entry.size
                
                # Check size limit
                while (self.stats['total_size'] + size > self.stats['max_size'] and 
                       self.cache):
                    self._evict_lru()
                    self.stats['evictions'] += 1
                
                # Add new entry
                self.cache[key] = entry
                self.cache.move_to_end(key)
                self.stats['total_size'] += size
                
                logger.debug(f"📦 Cache SET: {key} (size: {size}, ttl: {ttl})")
                return True
                
            except Exception as e:
                logger.error(f"❌ Error setting cache: {e}")
                return False
    
    def delete(self, key: str) -> bool:
        """Delete key from cache"""
        with self.lock:
            if key in self.cache:
                entry = self.cache.pop(key)
                self.stats['total_size'] -= entry.size
                logger.debug(f"📦 Cache DELETE: {key}")
                return True
            return False
    
    def delete_by_tag(self, tag: str) -> int:
        """Delete all entries with specific tag"""
        with self.lock:
            keys_to_delete = [
                key for key, entry in self.cache.items()
                if tag in entry.tags
            ]
            
            for key in keys_to_delete:
                self.delete(key)
            
            deleted_count = len(keys_to_delete)
            logger.debug(f"📦 Cache DELETE BY TAG: {tag} ({deleted_count} entries)")
            return deleted_count
    
    def clear(self) -> bool:
        """Clear entire cache"""
        with self.lock:
            self.cache.clear()
            self.stats['total_size'] = 0
            logger.info("📦 Cache CLEARED")
            return True
    
    def _evict_lru(self):
        """Evict least recently used entry"""
        if self.cache:
            oldest_key, oldest_entry = self.cache.popitem(last=False)
            self.stats['total_size'] -= oldest_entry.size
            logger.debug(f"📦 Cache EVICTED: {oldest_key}")
    
    def _remove_expired(self, key: str):
        """Remove expired entry"""
        if key in self.cache:
            entry = self.cache.pop(key)
            self.stats['total_size'] -= entry.size
    
    def cleanup_expired(self) -> int:
        """Remove all expired entries"""
        with self.lock:
            expired_keys = [
                key for key, entry in self.cache.items()
                if entry.is_expired
            ]
            
            for key in expired_keys:
                self._remove_expired(key)
            
            cleaned_count = len(expired_keys)
            if cleaned_count > 0:
                logger.debug(f"📦 Cache CLEANUP: {cleaned_count} expired entries")
            return cleaned_count
    
    def start_cleanup_thread(self):
        """Start background cleanup thread"""
        if self.cleanup_thread and self.cleanup_thread.is_alive():
            return
        
        self.cleanup_running = True
        
        def cleanup_worker():
            while self.cleanup_running:
                try:
                    cleaned = self.cleanup_expired()
                    if cleaned > 0:
                        logger.info(f"📦 Background cleanup: {cleaned} entries")
                    
                    time.sleep(CACHE_SETTINGS['cleanup_interval'])
                    
                except Exception as e:
                    logger.error(f"❌ Cleanup thread error: {e}")
                    time.sleep(60)  # Retry after 1 minute
        
        self.cleanup_thread = threading.Thread(
            target=cleanup_worker,
            name=f"CacheCleanup-{self.cache_name}",
            daemon=True
        )
        self.cleanup_thread.start()
    
    def stop_cleanup_thread(self):
        """Stop background cleanup thread"""
        self.cleanup_running = False
        if self.cleanup_thread and self.cleanup_thread.is_alive():
            self.cleanup_thread.join(timeout=5)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self.lock:
            now = get_current_timestamp()
            
            stats = {
                'cache_name': self.cache_name,
                'size': len(self.cache),
                'total_size_bytes': self.stats['total_size'],
                'max_size': self.stats['max_size'],
                'ttl': self.stats['ttl'],
                'hits': self.stats['hits'],
                'misses': self.stats['misses'],
                'hit_ratio': safe_divide(self.stats['hits'], 
                                       self.stats['hits'] + self.stats['misses']),
                'evictions': self.stats['evictions'],
                'expirations': self.stats['expirations'],
                'current_entries': [
                    {
                        'key': key,
                        'age': entry.age,
                        'hits': entry.hits,
                        'size': entry.size,
                        'tags': entry.tags
                    }
                    for key, entry in list(self.cache.items())[:10]  # Top 10
                ]
            }
            
            return stats
    
    def get_health_status(self) -> Dict[str, str]:
        """Get cache health status"""
        stats = self.get_stats()
        
        if stats['size'] >= self.stats['max_size'] * 0.9:
            status = 'critical'
        elif stats['size'] >= self.stats['max_size'] * 0.7:
            status = 'warning'
        elif stats['hit_ratio'] < 0.5:
            status = 'degraded'
        else:
            status = 'healthy'
        
        return {
            'status': status,
            'size': f"{stats['size']}/{stats['max_size']}",
            'hit_ratio': f"{stats['hit_ratio']:.2%}",
            'message': f"Cache {status} - {stats['size']} entries"
        }

class TokenMetadataCache(TokenCacheManager):
    """Specialized cache for token metadata"""
    
    def __init__(self):
        super().__init__("token_metadata")
        self.metadata_ttl = 3600 * 4  # 4 hours
    
    def cache_token_metadata(self, token: Token) -> bool:
        """Cache token metadata"""
        key = f"metadata:{token.address}"
        return self.set(key, token, ttl=self.metadata_ttl, tags=['metadata', token.symbol])
    
    def get_token_metadata(self, token_address: str) -> Optional[Token]:
        """Get cached token metadata"""
        return self.get(f"metadata:{token_address}")
    
    def invalidate_token(self, token_address: str) -> bool:
        """Invalidate token metadata"""
        return self.delete(f"metadata:{token_address}")
    
    def cache_bulk_metadata(self, tokens: List[Token]) -> int:
        """Cache multiple token metadata"""
        cached_count = 0
        for token in tokens:
            if self.cache_token_metadata(token):
                cached_count += 1
        return cached_count

class TokenAccountCache(TokenCacheManager):
    """Specialized cache for token accounts"""
    
    def __init__(self):
        super().__init__("token_accounts")
        self.account_ttl = 300  # 5 minutes
    
    def cache_account(self, wallet_address: str, accounts: List[TokenAccount]) -> bool:
        """Cache token accounts for wallet"""
        key = f"accounts:{wallet_address}"
        return self.set(key, accounts, ttl=self.account_ttl, tags=['accounts', wallet_address])
    
    def get_accounts(self, wallet_address: str) -> Optional[List[TokenAccount]]:
        """Get cached token accounts"""
        return self.get(f"accounts:{wallet_address}")
    
    def invalidate_wallet(self, wallet_address: str) -> int:
        """Invalidate all accounts for wallet"""
        return self.delete_by_tag(f"accounts:{wallet_address}")

class PriceCache(TokenCacheManager):
    """Specialized cache for token prices"""
    
    def __init__(self):
        super().__init__("token_prices")
        self.price_ttl = 300  # 5 minutes
    
    def cache_price(self, token_address: str, price: float, source: str = "unknown") -> bool:
        """Cache token price"""
        key = f"price:{token_address}"
        value = {
            'price': price,
            'source': source,
            'timestamp': get_current_timestamp()
        }
        return self.set(key, value, ttl=self.price_ttl, tags=['price', token_address])
    
    def get_price(self, token_address: str) -> Optional[Dict[str, Any]]:
        """Get cached token price"""
        return self.get(f"price:{token_address}")
    
    def is_price_fresh(self, token_address: str, max_age: int = 300) -> bool:
        """Check if price is fresh"""
        price_data = self.get_price(token_address)
        if not price_data:
            return False
        
        return get_current_timestamp() - price_data['timestamp'] < max_age

class CacheManagerSingleton:
    """Singleton manager for all cache instances"""
    
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
        if self._initialized:
            return
        
        self.metadata_cache = TokenMetadataCache()
        self.account_cache = TokenAccountCache()
        self.price_cache = PriceCache()
        self._initialized = True
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get stats for all caches"""
        return {
            'metadata': self.metadata_cache.get_stats(),
            'accounts': self.account_cache.get_stats(),
            'prices': self.price_cache.get_stats()
        }
    
    def clear_all(self) -> bool:
        """Clear all caches"""
        self.metadata_cache.clear()
        self.account_cache.clear()
        self.price_cache.clear()
        return True
    
    def cleanup_all(self) -> int:
        """Cleanup expired entries in all caches"""
        total_cleaned = 0
        total_cleaned += self.metadata_cache.cleanup_expired()
        total_cleaned += self.account_cache.cleanup_expired()
        total_cleaned += self.price_cache.cleanup_expired()
        return total_cleaned
    
    def shutdown(self):
        """Shutdown all cache managers"""
        self.metadata_cache.stop_cleanup_thread()
        self.account_cache.stop_cleanup_thread()
        self.price_cache.stop_cleanup_thread()

# Global instance
cache_manager = CacheManagerSingleton()

# Convenience functions
def get_token_metadata_cache() -> TokenMetadataCache:
    return cache_manager.metadata_cache

def get_token_account_cache() -> TokenAccountCache:
    return cache_manager.account_cache

def get_price_cache() -> PriceCache:
    return cache_manager.price_cache

# Context manager for temporary cache
class CacheContext:
    """Context manager for cache operations"""
    
    def __init__(self, cache_name: str = "temp"):
        self.cache = TokenCacheManager(cache_name)
    
    def __enter__(self):
        return self.cache
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cache.clear()
        self.cache.stop_cleanup_thread()

if __name__ == "__main__":
    # Test cache functionality
    print("✅ Testing Token Cache Manager...")
    
    # Test metadata cache
    metadata_cache = get_token_metadata_cache()
    
    # Test basic operations
    test_token = Token(
        address="So11111111111111111111111111111111111111112",
        symbol="WSOL",
        name="Wrapped SOL",
        decimals=9
    )
    
    success = metadata_cache.cache_token_metadata(test_token)
    print(f"📦 Token metadata cached: {success}")
    
    cached = metadata_cache.get_token_metadata(test_token.address)
    print(f"📦 Retrieved from cache: {cached.symbol if cached else None}")
    
    # Test statistics
    stats = metadata_cache.get_stats()
    print("📊 Cache stats:", stats)
    
    # Test global stats
    global_stats = cache_manager.get_all_stats()
    print("🌍 Global cache stats:", global_stats)