#!/usr/bin/env python3
"""
⚡ Optimisations Système pour Performance Maximale
Base de données, cache, et configuration réseau optimisés
"""

import sqlite3
import asyncio
import logging
from typing import Dict, List
import threading
import time
from collections import deque, defaultdict

logger = logging.getLogger('system_optimization')

class DatabaseOptimizer:
    """Optimisations SQLite pour débit maximal"""
    
    @staticmethod
    def optimize_database(db_path: str):
        """Appliquer toutes les optimisations SQLite"""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        try:
            logger.info("🔧 Applying SQLite optimizations...")
            
            # 1. Optimisations SQLite PRAGMA
            optimizations = [
                "PRAGMA journal_mode = WAL",           # Write-Ahead Logging pour concurrence
                "PRAGMA synchronous = NORMAL",         # Balance sécurité/performance
                "PRAGMA cache_size = -128000",         # 128MB de cache
                "PRAGMA temp_store = MEMORY",          # Tables temporaires en RAM
                "PRAGMA mmap_size = 268435456",        # 256MB memory mapping
                "PRAGMA optimize",                     # Optimisations automatiques
                "PRAGMA wal_autocheckpoint = 1000",    # Checkpoint moins fréquent
                "PRAGMA busy_timeout = 30000",         # Timeout 30s pour lock
            ]
            
            for pragma in optimizations:
                cursor.execute(pragma)
                logger.debug(f"Applied: {pragma}")
            
            # 2. Index optimisés pour les requêtes fréquentes
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_tokens_updated_at ON tokens(updated_at)",
                "CREATE INDEX IF NOT EXISTS idx_tokens_symbol_notnull ON tokens(symbol) WHERE symbol IS NOT NULL AND symbol != 'UNKNOWN'",
                "CREATE INDEX IF NOT EXISTS idx_tokens_first_discovered ON tokens(first_discovered_at)",
                "CREATE INDEX IF NOT EXISTS idx_tokens_invest_score ON tokens(invest_score DESC)",
                "CREATE INDEX IF NOT EXISTS idx_tokens_tradeable ON tokens(is_tradeable) WHERE is_tradeable = 1",
                "CREATE INDEX IF NOT EXISTS idx_tokens_enrichment_status ON tokens(symbol, updated_at) WHERE symbol IS NULL OR symbol = 'UNKNOWN'",
            ]
            
            for index_sql in indexes:
                cursor.execute(index_sql)
                logger.debug(f"Created index: {index_sql.split()[-1]}")
            
            # 3. Analyse des statistiques pour l'optimiseur
            cursor.execute("ANALYZE")
            
            conn.commit()
            logger.info("✅ Database optimized successfully")
            
        except sqlite3.Error as e:
            logger.error(f"Database optimization error: {e}")
        finally:
            conn.close()

class TokenCache:
    """Cache intelligent pour éviter les requêtes redondantes"""
    
    def __init__(self, max_size: int = 10000, ttl_seconds: int = 3600):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        
        # Cache avec TTL
        self.cache: Dict[str, Dict] = {}
        self.timestamps: Dict[str, float] = {}
        
        # Cache des métadonnées Jupiter (long TTL)
        self.jupiter_cache: Dict[str, Dict] = {}
        self.jupiter_cache_time = 0
        self.jupiter_ttl = 7200  # 2 heures
        
        # LRU tracking
        self.access_order = deque(maxlen=max_size)
        self.lock = threading.Lock()
    
    def get(self, key: str) -> Dict:
        """Récupérer depuis le cache si valide"""
        with self.lock:
            now = time.time()
            
            if key in self.cache:
                # Vérifier TTL
                if now - self.timestamps[key] < self.ttl_seconds:
                    # Mettre à jour l'ordre d'accès
                    if key in self.access_order:
                        self.access_order.remove(key)
                    self.access_order.append(key)
                    return self.cache[key]
                else:
                    # Expirer
                    self._remove_key(key)
            
            return None
    
    def set(self, key: str, value: Dict):
        """Stocker dans le cache"""
        with self.lock:
            now = time.time()
            
            # Vérifier la taille du cache
            if len(self.cache) >= self.max_size:
                # Supprimer l'élément le moins récemment utilisé
                if self.access_order:
                    oldest_key = self.access_order.popleft()
                    self._remove_key(oldest_key)
            
            self.cache[key] = value
            self.timestamps[key] = now
            self.access_order.append(key)
    
    def _remove_key(self, key: str):
        """Supprimer une clé du cache"""
        if key in self.cache:
            del self.cache[key]
        if key in self.timestamps:
            del self.timestamps[key]
    
    def get_jupiter_tokens(self) -> Dict[str, Dict]:
        """Cache spécial pour la liste Jupiter (mise à jour moins fréquente)"""
        now = time.time()
        if now - self.jupiter_cache_time > self.jupiter_ttl:
            return None
        return self.jupiter_cache
    
    def set_jupiter_tokens(self, tokens_dict: Dict[str, Dict]):
        """Mettre à jour le cache Jupiter"""
        with self.lock:
            self.jupiter_cache = tokens_dict
            self.jupiter_cache_time = time.time()
            logger.info(f"📦 Cached {len(tokens_dict)} Jupiter tokens")
    
    def get_stats(self) -> Dict:
        """Statistiques du cache"""
        with self.lock:
            total_size = len(self.cache)
            expired_count = sum(
                1 for key, ts in self.timestamps.items()
                if time.time() - ts >= self.ttl_seconds
            )
            
            return {
                "total_entries": total_size,
                "expired_entries": expired_count,
                "jupiter_cache_size": len(self.jupiter_cache),
                "cache_hit_potential": (total_size - expired_count) / max(1, total_size) * 100
            }

class ConnectionPoolManager:
    """Gestionnaire de pool de connexions optimisé"""
    
    def __init__(self, database_path: str, pool_size: int = 10):
        self.database_path = database_path
        self.pool_size = pool_size
        self.pool = asyncio.Queue(maxsize=pool_size)
        self.initialized = False
    
    async def initialize(self):
        """Initialiser le pool de connexions"""
        if self.initialized:
            return
        
        for _ in range(self.pool_size):
            conn = sqlite3.connect(
                self.database_path,
                check_same_thread=False,
                timeout=30.0
            )
            conn.row_factory = sqlite3.Row
            
            # Optimisations par connexion
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA synchronous = NORMAL")
            cursor.execute("PRAGMA cache_size = -32000")  # 32MB per connection
            
            await self.pool.put(conn)
        
        self.initialized = True
        logger.info(f"✅ Database connection pool initialized ({self.pool_size} connections)")
    
    async def get_connection(self):
        """Obtenir une connexion du pool"""
        if not self.initialized:
            await self.initialize()
        return await self.pool.get()
    
    async def return_connection(self, conn):
        """Rendre une connexion au pool"""
        await self.pool.put(conn)
    
    async def execute_batch(self, sql: str, data: List[tuple]) -> int:
        """Exécuter une requête batch optimisée"""
        conn = await self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.executemany(sql, data)
            conn.commit()
            return cursor.rowcount
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"Batch execution error: {e}")
            return 0
        finally:
            await self.return_connection(conn)

class PerformanceProfiler:
    """Profiler pour identifier les goulots d'étranglement"""
    
    def __init__(self):
        self.metrics = defaultdict(list)
        self.start_times = {}
        self.lock = threading.Lock()
    
    def start_timer(self, operation: str):
        """Démarrer un timer pour une opération"""
        self.start_times[operation] = time.time()
    
    def end_timer(self, operation: str):
        """Terminer un timer et enregistrer le temps"""
        if operation in self.start_times:
            elapsed = time.time() - self.start_times[operation]
            with self.lock:
                self.metrics[operation].append(elapsed)
                # Garder seulement les 100 dernières mesures
                if len(self.metrics[operation]) > 100:
                    self.metrics[operation] = self.metrics[operation][-100:]
            del self.start_times[operation]
            return elapsed
        return 0
    
    def get_stats(self) -> Dict:
        """Obtenir les statistiques de performance"""
        with self.lock:
            stats = {}
            for operation, times in self.metrics.items():
                if times:
                    stats[operation] = {
                        "count": len(times),
                        "avg_time": sum(times) / len(times),
                        "min_time": min(times),
                        "max_time": max(times),
                        "recent_avg": sum(times[-10:]) / min(10, len(times))
                    }
            return stats
    
    def log_performance_report(self):
        """Logger un rapport de performance"""
        stats = self.get_stats()
        if stats:
            logger.info("📊 PERFORMANCE REPORT:")
            for operation, metrics in stats.items():
                logger.info(
                    f"   {operation}: {metrics['avg_time']:.3f}s avg "
                    f"(min: {metrics['min_time']:.3f}s, max: {metrics['max_time']:.3f}s, "
                    f"count: {metrics['count']})"
                )

# Configuration globale optimisée
SYSTEM_CONFIG = {
    # Réseau
    "max_connections_per_host": 30,
    "total_connection_limit": 100,
    "connection_timeout": 10,
    "dns_cache_ttl": 300,
    
    # Processing
    "batch_size": 15,
    "max_concurrent_enrichments": 25,
    "enrichment_timeout": 12,
    "queue_max_size": 100,
    
    # Cache
    "cache_size": 10000,
    "cache_ttl_seconds": 3600,
    "jupiter_cache_ttl": 7200,
    
    # Base de données
    "db_pool_size": 10,
    "db_timeout": 30,
    "wal_checkpoint_interval": 1000,
    
    # Rate limiting optimisé
    "api_rates": {
        "jupiter": {"calls_per_second": 5, "burst": 15},
        "dexscreener": {"calls_per_second": 2, "burst": 8},
        "rugcheck": {"calls_per_second": 1.5, "burst": 6},
        "helius": {"calls_per_second": 3, "burst": 10},
        "solscan": {"calls_per_second": 2.5, "burst": 8},
    }
}

# Instances globales
global_cache = TokenCache(
    max_size=SYSTEM_CONFIG["cache_size"],
    ttl_seconds=SYSTEM_CONFIG["cache_ttl_seconds"]
)

global_profiler = PerformanceProfiler()

def apply_system_optimizations(database_path: str):
    """Appliquer toutes les optimisations système"""
    logger.info("🚀 Applying system optimizations...")
    
    # 1. Optimiser la base de données
    DatabaseOptimizer.optimize_database(database_path)
    
    # 2. Configurer asyncio pour de meilleures performances
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        logger.info("✅ Using uvloop for better async performance")
    except ImportError:
        logger.info("⚠️ uvloop not available, using default asyncio")
    
    # 3. Logger les configurations
    logger.info(f"📋 System configuration:")
    for category, settings in SYSTEM_CONFIG.items():
        if isinstance(settings, dict):
            logger.info(f"   {category}:")
            for key, value in settings.items():
                logger.info(f"     {key}: {value}")
        else:
            logger.info(f"   {category}: {settings}")
    
    logger.info("✅ System optimizations applied")

# Fonction de monitoring des performances
async def performance_monitoring_loop():
    """Boucle de monitoring des performances"""
    while True:
        await asyncio.sleep(300)  # Toutes les 5 minutes
        
        # Rapport de performance
        global_profiler.log_performance_report()
        
        # Stats du cache
        cache_stats = global_cache.get_stats()
        logger.info(f"💾 Cache stats: {cache_stats}")

if __name__ == "__main__":
    # Test des optimisations
    logging.basicConfig(level=logging.INFO)
    apply_system_optimizations("tokens.db")