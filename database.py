"""
Database Manager for Solana Trading Bot - Version Professionnelle
File: database.py

Gestionnaire de base de données SQLite avec fonctionnalités avancées :
- Gestion des tokens, transactions, et analytiques
- Connection pooling et thread safety
- Migrations automatiques
- Backup et recovery
- Monitoring des performances
- Cache intelligent
"""

import sqlite3
import threading
import logging
import json
import time
import os
import shutil
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any, Union
from dataclasses import dataclass, asdict
from contextlib import contextmanager
from pathlib import Path
import hashlib
from enum import Enum
import asyncio
import aiosqlite
from concurrent.futures import ThreadPoolExecutor
import queue
import weakref


class TransactionStatus(Enum):
    """États des transactions"""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TokenStatus(Enum):
    """États des tokens"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    BLACKLISTED = "blacklisted"
    VERIFIED = "verified"


@dataclass
class TokenRecord:
    """Enregistrement de token"""
    address: str
    symbol: str
    name: str
    decimals: int
    status: TokenStatus
    safety_score: float
    bundle_detected: bool
    bundle_confidence: float
    risk_indicators: Dict
    market_cap: Optional[float] = None
    volume_24h: Optional[float] = None
    price_usd: Optional[float] = None
    liquidity: Optional[float] = None
    holders_count: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    rugcheck_data: Optional[Dict] = None
    dexscreener_data: Optional[Dict] = None


@dataclass
class TransactionRecord:
    """Enregistrement de transaction"""
    tx_hash: str
    token_address: str
    action: str  # 'buy', 'sell', 'swap'
    amount_in: float
    amount_out: float
    token_in: str
    token_out: str
    price: float
    slippage: float
    status: TransactionStatus
    gas_fee: Optional[float] = None
    created_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    block_number: Optional[int] = None
    error_message: Optional[str] = None
    metadata: Optional[Dict] = None


@dataclass
class AnalyticsRecord:
    """Enregistrement d'analytiques"""
    metric_name: str
    metric_value: Union[float, int, str]
    metric_type: str  # 'performance', 'trading', 'system', 'error'
    timestamp: datetime
    metadata: Optional[Dict] = None


class DatabaseError(Exception):
    """Exception pour les erreurs de base de données"""
    pass


class ConnectionPool:
    """Pool de connexions SQLite thread-safe"""
    
    def __init__(self, database_path: str, max_connections: int = 10):
        self.database_path = database_path
        self.max_connections = max_connections
        self._pool = queue.Queue(maxsize=max_connections)
        self._lock = threading.Lock()
        self._created_connections = 0
        
        # Pré-créer quelques connexions
        for _ in range(min(3, max_connections)):
            self._create_connection()
    
    def _create_connection(self) -> sqlite3.Connection:
        """Crée une nouvelle connexion avec configuration optimisée"""
        conn = sqlite3.connect(
            self.database_path,
            check_same_thread=False,
            timeout=30.0
        )
        
        # Configuration pour les performances
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=10000")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA mmap_size=268435456")  # 256MB
        
        # Row factory pour dict-like access
        conn.row_factory = sqlite3.Row
        
        self._created_connections += 1
        return conn
    
    @contextmanager
    def get_connection(self):
        """Context manager pour obtenir une connexion du pool"""
        conn = None
        try:
            # Essayer d'obtenir une connexion existante
            try:
                conn = self._pool.get_nowait()
            except queue.Empty:
                # Créer une nouvelle si le pool n'est pas plein
                with self._lock:
                    if self._created_connections < self.max_connections:
                        conn = self._create_connection()
                    else:
                        # Attendre qu'une connexion soit disponible
                        conn = self._pool.get(timeout=10.0)
            
            yield conn
            
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except:
                    pass
            raise
        finally:
            if conn:
                try:
                    # Remettre la connexion dans le pool
                    self._pool.put_nowait(conn)
                except queue.Full:
                    # Pool plein, fermer la connexion
                    conn.close()
                    with self._lock:
                        self._created_connections -= 1
    
    def close_all(self):
        """Ferme toutes les connexions du pool"""
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except queue.Empty:
                break
        self._created_connections = 0


class DatabaseManager:
    """
    Gestionnaire principal de la base de données
    
    Features:
    - Connection pooling pour les performances
    - Thread safety complet
    - Migrations automatiques
    - Backup automatique
    - Monitoring et métriques
    - Cache intelligent
    - Requêtes asynchrones
    """
    
    # Version du schéma pour les migrations
    SCHEMA_VERSION = 3
    
    def __init__(self, config: Dict):
        self.config = config
        self.db_config = config.get('database', {})
        self.db_path = self.db_config.get('path', 'data/trading_bot.db')
        self.backup_enabled = self.db_config.get('backup_enabled', True)
        self.backup_interval = self.db_config.get('backup_interval_hours', 24)
        self.max_connections = self.db_config.get('max_connections', 10)
        
        # Logging
        self.logger = logging.getLogger(__name__)
        
        # Créer le répertoire de données
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        # Pool de connexions
        self.pool = ConnectionPool(self.db_path, self.max_connections)
        
        # Thread safety
        self._write_lock = threading.RLock()
        
        # Cache pour les requêtes fréquentes
        self._cache = {}
        self._cache_lock = threading.RLock()
        self._cache_ttl = {}
        self.cache_duration = 300  # 5 minutes
        
        # Métriques de performance
        self._metrics = {
            'queries_count': 0,
            'avg_query_time': 0.0,
            'cache_hits': 0,
            'cache_misses': 0,
            'errors_count': 0
        }
        self._metrics_lock = threading.Lock()
        
        # Thread pool pour les opérations asynchrones
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="db_worker")
        
        # Backup automatique
        self._last_backup = None
        
        # Initialisation
        self._initialize_database()
        self._start_background_tasks()
        
        self.logger.info(f"Database manager initialized: {self.db_path}")
    
    def _initialize_database(self):
        """Initialise la base de données avec le schéma"""
        try:
            with self.pool.get_connection() as conn:
                # Créer les tables si elles n'existent pas
                self._create_tables(conn)
                
                # Vérifier et effectuer les migrations
                current_version = self._get_schema_version(conn)
                if current_version < self.SCHEMA_VERSION:
                    self._migrate_schema(conn, current_version)
                
                # Créer les index pour les performances
                self._create_indexes(conn)
                
                conn.commit()
                
        except Exception as e:
            self.logger.error(f"Failed to initialize database: {e}")
            raise DatabaseError(f"Database initialization failed: {e}")
    
    def _create_tables(self, conn: sqlite3.Connection):
        """Crée les tables de la base de données"""
        
        # Table des tokens
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tokens (
                address TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                decimals INTEGER NOT NULL DEFAULT 9,
                status TEXT NOT NULL DEFAULT 'active',
                safety_score REAL NOT NULL DEFAULT 0.0,
                bundle_detected BOOLEAN NOT NULL DEFAULT 0,
                bundle_confidence REAL NOT NULL DEFAULT 0.0,
                risk_indicators TEXT,  -- JSON
                market_cap REAL,
                volume_24h REAL,
                price_usd REAL,
                liquidity REAL,
                holders_count INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                rugcheck_data TEXT,  -- JSON
                dexscreener_data TEXT  -- JSON
            )
        """)
        
        # Table des transactions
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tx_hash TEXT UNIQUE NOT NULL,
                token_address TEXT NOT NULL,
                action TEXT NOT NULL,  -- buy, sell, swap
                amount_in REAL NOT NULL,
                amount_out REAL NOT NULL,
                token_in TEXT NOT NULL,
                token_out TEXT NOT NULL,
                price REAL NOT NULL,
                slippage REAL NOT NULL DEFAULT 0.0,
                status TEXT NOT NULL DEFAULT 'pending',
                gas_fee REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                confirmed_at TIMESTAMP,
                block_number INTEGER,
                error_message TEXT,
                metadata TEXT,  -- JSON
                FOREIGN KEY (token_address) REFERENCES tokens (address)
            )
        """)
        
        # Table des analytiques
        conn.execute("""
            CREATE TABLE IF NOT EXISTS analytics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                metric_name TEXT NOT NULL,
                metric_value TEXT NOT NULL,  -- Stocké comme TEXT pour flexibilité
                metric_type TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT  -- JSON
            )
        """)
        
        # Table de configuration système
        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Table des logs d'erreurs
        conn.execute("""
            CREATE TABLE IF NOT EXISTS error_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                error_type TEXT NOT NULL,
                error_message TEXT NOT NULL,
                error_details TEXT,  -- JSON
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Table de performance/monitoring
        conn.execute("""
            CREATE TABLE IF NOT EXISTS performance_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation_type TEXT NOT NULL,
                duration_ms REAL NOT NULL,
                success BOOLEAN NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                details TEXT  -- JSON
            )
        """)
    
    def _create_indexes(self, conn: sqlite3.Connection):
        """Crée les index pour optimiser les performances"""
        indexes = [
            # Tokens
            "CREATE INDEX IF NOT EXISTS idx_tokens_status ON tokens(status)",
            "CREATE INDEX IF NOT EXISTS idx_tokens_safety_score ON tokens(safety_score)",
            "CREATE INDEX IF NOT EXISTS idx_tokens_updated_at ON tokens(updated_at)",
            "CREATE INDEX IF NOT EXISTS idx_tokens_bundle ON tokens(bundle_detected)",
            
            # Transactions
            "CREATE INDEX IF NOT EXISTS idx_transactions_token ON transactions(token_address)",
            "CREATE INDEX IF NOT EXISTS idx_transactions_status ON transactions(status)",
            "CREATE INDEX IF NOT EXISTS idx_transactions_action ON transactions(action)",
            "CREATE INDEX IF NOT EXISTS idx_transactions_created_at ON transactions(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_transactions_hash ON transactions(tx_hash)",
            
            # Analytics
            "CREATE INDEX IF NOT EXISTS idx_analytics_metric_name ON analytics(metric_name)",
            "CREATE INDEX IF NOT EXISTS idx_analytics_type ON analytics(metric_type)",
            "CREATE INDEX IF NOT EXISTS idx_analytics_timestamp ON analytics(timestamp)",
            
            # Performance
            "CREATE INDEX IF NOT EXISTS idx_performance_operation ON performance_metrics(operation_type)",
            "CREATE INDEX IF NOT EXISTS idx_performance_timestamp ON performance_metrics(timestamp)",
            
            # Error logs
            "CREATE INDEX IF NOT EXISTS idx_error_logs_type ON error_logs(error_type)",
            "CREATE INDEX IF NOT EXISTS idx_error_logs_timestamp ON error_logs(timestamp)"
        ]
        
        for index_sql in indexes:
            conn.execute(index_sql)
    
    def _get_schema_version(self, conn: sqlite3.Connection) -> int:
        """Récupère la version actuelle du schéma"""
        try:
            cursor = conn.execute("SELECT value FROM system_config WHERE key = 'schema_version'")
            result = cursor.fetchone()
            return int(result[0]) if result else 0
        except:
            return 0
    
    def _migrate_schema(self, conn: sqlite3.Connection, from_version: int):
        """Effectue les migrations du schéma"""
        self.logger.info(f"Migrating database schema from v{from_version} to v{self.SCHEMA_VERSION}")
        
        migrations = {
            1: self._migrate_to_v1,
            2: self._migrate_to_v2,
            3: self._migrate_to_v3
        }
        
        for version in range(from_version + 1, self.SCHEMA_VERSION + 1):
            if version in migrations:
                self.logger.info(f"Applying migration to v{version}")
                migrations[version](conn)
        
        # Mettre à jour la version
        conn.execute(
            "INSERT OR REPLACE INTO system_config (key, value) VALUES ('schema_version', ?)",
            (str(self.SCHEMA_VERSION),)
        )
    
    def _migrate_to_v1(self, conn: sqlite3.Connection):
        """Migration vers la version 1"""
        # Ajouter des colonnes manquantes si nécessaire
        try:
            conn.execute("ALTER TABLE tokens ADD COLUMN rugcheck_data TEXT")
        except sqlite3.OperationalError:
            pass  # Colonne existe déjà
    
    def _migrate_to_v2(self, conn: sqlite3.Connection):
        """Migration vers la version 2"""
        try:
            conn.execute("ALTER TABLE tokens ADD COLUMN dexscreener_data TEXT")
            conn.execute("ALTER TABLE transactions ADD COLUMN metadata TEXT")
        except sqlite3.OperationalError:
            pass
    
    def _migrate_to_v3(self, conn: sqlite3.Connection):
        """Migration vers la version 3"""
        # Ajouter la table de métriques de performance
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS performance_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation_type TEXT NOT NULL,
                    duration_ms REAL NOT NULL,
                    success BOOLEAN NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    details TEXT
                )
            """)
        except sqlite3.OperationalError:
            pass
    
    def _start_background_tasks(self):
        """Démarre les tâches en arrière-plan"""
        if self.backup_enabled:
            self._executor.submit(self._background_backup_worker)
        
        # Nettoyage périodique du cache
        self._executor.submit(self._background_cache_cleaner)
    
    def _background_backup_worker(self):
        """Worker pour les sauvegardes automatiques"""
        while True:
            try:
                time.sleep(3600)  # Vérifier toutes les heures
                
                now = datetime.now()
                if (self._last_backup is None or 
                    (now - self._last_backup).total_seconds() > self.backup_interval * 3600):
                    
                    self.create_backup()
                    self._last_backup = now
                    
            except Exception as e:
                self.logger.error(f"Backup worker error: {e}")
                time.sleep(300)  # Attendre 5 minutes avant de réessayer
    
    def _background_cache_cleaner(self):
        """Nettoie le cache périodiquement"""
        while True:
            try:
                time.sleep(300)  # Nettoyer toutes les 5 minutes
                self._clean_expired_cache()
            except Exception as e:
                self.logger.error(f"Cache cleaner error: {e}")
                time.sleep(60)
    
    def _clean_expired_cache(self):
        """Nettoie les entrées expirées du cache"""
        with self._cache_lock:
            current_time = time.time()
            expired_keys = [
                key for key, ttl in self._cache_ttl.items()
                if current_time > ttl
            ]
            
            for key in expired_keys:
                self._cache.pop(key, None)
                self._cache_ttl.pop(key, None)
    
    def _get_cache_key(self, query: str, params: Tuple = ()) -> str:
        """Génère une clé de cache pour une requête"""
        content = f"{query}:{params}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def _cache_get(self, cache_key: str) -> Optional[Any]:
        """Récupère une valeur du cache"""
        with self._cache_lock:
            if cache_key in self._cache:
                if time.time() <= self._cache_ttl.get(cache_key, 0):
                    with self._metrics_lock:
                        self._metrics['cache_hits'] += 1
                    return self._cache[cache_key]
                else:
                    # Expiré
                    self._cache.pop(cache_key, None)
                    self._cache_ttl.pop(cache_key, None)
            
            with self._metrics_lock:
                self._metrics['cache_misses'] += 1
            return None
    
    def _cache_set(self, cache_key: str, value: Any):
        """Met en cache une valeur"""
        with self._cache_lock:
            self._cache[cache_key] = value
            self._cache_ttl[cache_key] = time.time() + self.cache_duration
    
    @contextmanager
    def _measure_query_time(self, operation: str):
        """Context manager pour mesurer le temps des requêtes"""
        start_time = time.time()
        success = True
        
        try:
            yield
        except Exception as e:
            success = False
            with self._metrics_lock:
                self._metrics['errors_count'] += 1
            raise
        finally:
            duration = (time.time() - start_time) * 1000  # en millisecondes
            
            with self._metrics_lock:
                self._metrics['queries_count'] += 1
                self._metrics['avg_query_time'] = (
                    (self._metrics['avg_query_time'] * (self._metrics['queries_count'] - 1) + duration) /
                    self._metrics['queries_count']
                )
            
            # Enregistrer dans la table de performance si l'opération prend du temps
            if duration > 100:  # Plus de 100ms
                self._executor.submit(
                    self._record_performance_metric,
                    operation, duration, success
                )
    
    def _record_performance_metric(self, operation: str, duration: float, success: bool):
        """Enregistre une métrique de performance"""
        try:
            with self.pool.get_connection() as conn:
                conn.execute(
                    """INSERT INTO performance_metrics 
                       (operation_type, duration_ms, success) 
                       VALUES (?, ?, ?)""",
                    (operation, duration, success)
                )
                conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to record performance metric: {e}")
    
    # === MÉTHODES PUBLIQUES - TOKENS ===
    
    def add_token(self, token: TokenRecord) -> bool:
        """Ajoute un nouveau token à la base de données"""
        try:
            with self._write_lock:
                with self.pool.get_connection() as conn:
                    with self._measure_query_time("add_token"):
                        conn.execute("""
                            INSERT OR REPLACE INTO tokens 
                            (address, symbol, name, decimals, status, safety_score, 
                             bundle_detected, bundle_confidence, risk_indicators,
                             market_cap, volume_24h, price_usd, liquidity, holders_count,
                             rugcheck_data, dexscreener_data, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        """, (
                            token.address, token.symbol, token.name, token.decimals,
                            token.status.value, token.safety_score,
                            token.bundle_detected, token.bundle_confidence,
                            json.dumps(token.risk_indicators) if token.risk_indicators else None,
                            token.market_cap, token.volume_24h, token.price_usd,
                            token.liquidity, token.holders_count,
                            json.dumps(token.rugcheck_data) if token.rugcheck_data else None,
                            json.dumps(token.dexscreener_data) if token.dexscreener_data else None
                        ))
                        conn.commit()
                        
                        # Invalider le cache
                        self._invalidate_token_cache(token.address)
                        
                        return True
                        
        except Exception as e:
            self.logger.error(f"Failed to add token {token.address}: {e}")
            return False
    
    def get_token(self, address: str) -> Optional[TokenRecord]:
        """Récupère un token par son adresse"""
        cache_key = self._get_cache_key("get_token", (address,))
        cached_result = self._cache_get(cache_key)
        
        if cached_result is not None:
            return cached_result
        
        try:
            with self.pool.get_connection() as conn:
                with self._measure_query_time("get_token"):
                    cursor = conn.execute(
                        "SELECT * FROM tokens WHERE address = ?", (address,)
                    )
                    row = cursor.fetchone()
                    
                    if row:
                        token = self._row_to_token_record(row)
                        self._cache_set(cache_key, token)
                        return token
                    
                    return None
                    
        except Exception as e:
            self.logger.error(f"Failed to get token {address}: {e}")
            return None
    
    def update_token_price(self, address: str, price_usd: float, 
                          market_cap: Optional[float] = None,
                          volume_24h: Optional[float] = None,
                          liquidity: Optional[float] = None) -> bool:
        """Met à jour le prix et les données de marché d'un token"""
        try:
            with self._write_lock:
                with self.pool.get_connection() as conn:
                    with self._measure_query_time("update_token_price"):
                        values = [price_usd]
                        set_clauses = ["price_usd = ?"]
                        
                        if market_cap is not None:
                            set_clauses.append("market_cap = ?")
                            values.append(market_cap)
                        
                        if volume_24h is not None:
                            set_clauses.append("volume_24h = ?")
                            values.append(volume_24h)
                        
                        if liquidity is not None:
                            set_clauses.append("liquidity = ?")
                            values.append(liquidity)
                        
                        set_clauses.append("updated_at = CURRENT_TIMESTAMP")
                        values.append(address)
                        
                        query = f"UPDATE tokens SET {', '.join(set_clauses)} WHERE address = ?"
                        
                        cursor = conn.execute(query, values)
                        conn.commit()
                        
                        # Invalider le cache
                        self._invalidate_token_cache(address)
                        
                        return cursor.rowcount > 0
                        
        except Exception as e:
            self.logger.error(f"Failed to update token price {address}: {e}")
            return False
    
    def get_tokens_by_status(self, status: TokenStatus, limit: int = 100) -> List[TokenRecord]:
        """Récupère les tokens par statut"""
        cache_key = self._get_cache_key("get_tokens_by_status", (status.value, limit))
        cached_result = self._cache_get(cache_key)
        
        if cached_result is not None:
            return cached_result
        
        try:
            with self.pool.get_connection() as conn:
                with self._measure_query_time("get_tokens_by_status"):
                    cursor = conn.execute(
                        """SELECT * FROM tokens 
                           WHERE status = ? 
                           ORDER BY updated_at DESC 
                           LIMIT ?""",
                        (status.value, limit)
                    )
                    
                    tokens = [self._row_to_token_record(row) for row in cursor.fetchall()]
                    self._cache_set(cache_key, tokens)
                    return tokens
                    
        except Exception as e:
            self.logger.error(f"Failed to get tokens by status {status}: {e}")
            return []
    
    def get_safe_tokens(self, min_safety_score: float = 0.7, limit: int = 50) -> List[TokenRecord]:
        """Récupère les tokens sûrs pour le trading"""
        try:
            with self.pool.get_connection() as conn:
                with self._measure_query_time("get_safe_tokens"):
                    cursor = conn.execute(
                        """SELECT * FROM tokens 
                           WHERE safety_score >= ? 
                           AND bundle_detected = 0 
                           AND status = 'active'
                           ORDER BY safety_score DESC, volume_24h DESC
                           LIMIT ?""",
                        (min_safety_score, limit)
                    )
                    
                    return [self._row_to_token_record(row) for row in cursor.fetchall()]
                    
        except Exception as e:
            self.logger.error(f"Failed to get safe tokens: {e}")
            return []
    
    def search_tokens(self, query: str, limit: int = 20) -> List[TokenRecord]:
        """Recherche des tokens par nom ou symbole"""
        try:
            search_term = f"%{query}%"
            with self.pool.get_connection() as conn:
                with self._measure_query_time("search_tokens"):
                    cursor = conn.execute(
                        """SELECT * FROM tokens 
                           WHERE (symbol LIKE ? OR name LIKE ?) 
                           AND status = 'active'
                           ORDER BY safety_score DESC
                           LIMIT ?""",
                        (search_term, search_term, limit)
                    )
                    
                    return [self._row_to_token_record(row) for row in cursor.fetchall()]
                    
        except Exception as e:
            self.logger.error(f"Failed to search tokens: {e}")
            return []
    
    # === MÉTHODES PUBLIQUES - TRANSACTIONS ===
    
    def add_transaction(self, transaction: TransactionRecord) -> bool:
        """Ajoute une nouvelle transaction"""
        try:
            with self._write_lock:
                with self.pool.get_connection() as conn:
                    with self._measure_query_time("add_transaction"):
                        conn.execute("""
                            INSERT OR REPLACE INTO transactions 
                            (tx_hash, token_address, action, amount_in, amount_out,
                             token_in, token_out, price, slippage, status, gas_fee,
                             confirmed_at, block_number, error_message, metadata)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            transaction.tx_hash, transaction.token_address, transaction.action,
                            transaction.amount_in, transaction.amount_out,
                            transaction.token_in, transaction.token_out,
                            transaction.price, transaction.slippage, transaction.status.value,
                            transaction.gas_fee, transaction.confirmed_at,
                            transaction.block_number, transaction.error_message,
                            json.dumps(transaction.metadata) if transaction.metadata else None
                        ))
                        conn.commit()
                        return True
                        
        except Exception as e:
            self.logger.error(f"Failed to add transaction {transaction.tx_hash}: {e}")
            return False
    
    def update_transaction_status(self, tx_hash: str, status: TransactionStatus,
                                 confirmed_at: Optional[datetime] = None,
                                 block_number: Optional[int] = None,
                                 error_message: Optional[str] = None) -> bool:
        """Met à jour le statut d'une transaction"""
        try:
            with self._write_lock:
                with self.pool.get_connection() as conn:
                    with self._measure_query_time("update_transaction_status"):
                        conn.execute("""
                            UPDATE transactions 
                            SET status = ?, confirmed_at = ?, block_number = ?, error_message = ?
                            WHERE tx_hash = ?
                        """, (status.value, confirmed_at, block_number, error_message, tx_hash))
                        
                        conn.commit()
                        return conn.total_changes > 0
                        
        except Exception as e:
            self.logger.error(f"Failed to update transaction status {tx_hash}: {e}")
            return False
    
    def get_transactions(self, token_address: Optional[str] = None,
                        status: Optional[TransactionStatus] = None,
                        limit: int = 100,
                        offset: int = 0) -> List[TransactionRecord]:
        """Récupère les transactions avec filtres optionnels"""
        try:
            with self.pool.get_connection() as conn:
                with self._measure_query_time("get_transactions"):
                    query = "SELECT * FROM transactions WHERE 1=1"
                    params = []
                    
                    if token_address:
                        query += " AND token_address = ?"
                        params.append(token_address)
                    
                    if status:
                        query += " AND status = ?"
                        params.append(status.value)
                    
                    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
                    params.extend([limit, offset])
                    
                    cursor = conn.execute(query, params)
                    return [self._row_to_transaction_record(row) for row in cursor.fetchall()]
                    
        except Exception as e:
            self.logger.error(f"Failed to get transactions: {e}")
            return []
    
    def get_transaction_by_hash(self, tx_hash: str) -> Optional[TransactionRecord]:
        """Récupère une transaction par son hash"""
        try:
            with self.pool.get_connection() as conn:
                with self._measure_query_time("get_transaction_by_hash"):
                    cursor = conn.execute(
                        "SELECT * FROM transactions WHERE tx_hash = ?", (tx_hash,)
                    )
                    row = cursor.fetchone()
                    
                    if row:
                        return self._row_to_transaction_record(row)
                    return None
                    
        except Exception as e:
            self.logger.error(f"Failed to get transaction {tx_hash}: {e}")
            return None
    
    def get_pending_transactions(self, older_than_minutes: int = 30) -> List[TransactionRecord]:
        """Récupère les transactions en attente depuis plus de X minutes"""
        try:
            cutoff_time = datetime.now() - timedelta(minutes=older_than_minutes)
            
            with self.pool.get_connection() as conn:
                with self._measure_query_time("get_pending_transactions"):
                    cursor = conn.execute(
                        """SELECT * FROM transactions 
                           WHERE status = 'pending' 
                           AND created_at < ?
                           ORDER BY created_at ASC""",
                        (cutoff_time,)
                    )
                    
                    return [self._row_to_transaction_record(row) for row in cursor.fetchall()]
                    
        except Exception as e:
            self.logger.error(f"Failed to get pending transactions: {e}")
            return []
    
    # === MÉTHODES PUBLIQUES - ANALYTICS ===
    
    def add_analytics_record(self, record: AnalyticsRecord) -> bool:
        """Ajoute un enregistrement d'analytiques"""
        try:
            with self._write_lock:
                with self.pool.get_connection() as conn:
                    with self._measure_query_time("add_analytics"):
                        conn.execute("""
                            INSERT INTO analytics 
                            (metric_name, metric_value, metric_type, timestamp, metadata)
                            VALUES (?, ?, ?, ?, ?)
                        """, (
                            record.metric_name,
                            str(record.metric_value),
                            record.metric_type,
                            record.timestamp,
                            json.dumps(record.metadata) if record.metadata else None
                        ))
                        conn.commit()
                        return True
                        
        except Exception as e:
            self.logger.error(f"Failed to add analytics record: {e}")
            return False
    
    def get_analytics(self, metric_name: Optional[str] = None,
                     metric_type: Optional[str] = None,
                     start_time: Optional[datetime] = None,
                     end_time: Optional[datetime] = None,
                     limit: int = 1000) -> List[AnalyticsRecord]:
        """Récupère les enregistrements d'analytiques"""
        try:
            with self.pool.get_connection() as conn:
                with self._measure_query_time("get_analytics"):
                    query = "SELECT * FROM analytics WHERE 1=1"
                    params = []
                    
                    if metric_name:
                        query += " AND metric_name = ?"
                        params.append(metric_name)
                    
                    if metric_type:
                        query += " AND metric_type = ?"
                        params.append(metric_type)
                    
                    if start_time:
                        query += " AND timestamp >= ?"
                        params.append(start_time)
                    
                    if end_time:
                        query += " AND timestamp <= ?"
                        params.append(end_time)
                    
                    query += " ORDER BY timestamp DESC LIMIT ?"
                    params.append(limit)
                    
                    cursor = conn.execute(query, params)
                    return [self._row_to_analytics_record(row) for row in cursor.fetchall()]
                    
        except Exception as e:
            self.logger.error(f"Failed to get analytics: {e}")
            return []
    
    def get_performance_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Récupère un résumé des performances"""
        try:
            start_time = datetime.now() - timedelta(hours=hours)
            
            with self.pool.get_connection() as conn:
                with self._measure_query_time("get_performance_summary"):
                    # Statistiques des transactions
                    cursor = conn.execute("""
                        SELECT 
                            COUNT(*) as total_transactions,
                            SUM(CASE WHEN status = 'confirmed' THEN 1 ELSE 0 END) as confirmed_transactions,
                            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_transactions,
                            AVG(CASE WHEN status = 'confirmed' THEN price ELSE NULL END) as avg_price,
                            SUM(CASE WHEN status = 'confirmed' THEN amount_out ELSE 0 END) as total_volume
                        FROM transactions 
                        WHERE created_at >= ?
                    """, (start_time,))
                    
                    tx_stats = dict(cursor.fetchone())
                    
                    # Statistiques des tokens
                    cursor = conn.execute("""
                        SELECT 
                            COUNT(*) as total_tokens,
                            AVG(safety_score) as avg_safety_score,
                            SUM(CASE WHEN bundle_detected = 1 THEN 1 ELSE 0 END) as bundle_count
                        FROM tokens 
                        WHERE updated_at >= ?
                    """, (start_time,))
                    
                    token_stats = dict(cursor.fetchone())
                    
                    # Métriques de performance de la base
                    cursor = conn.execute("""
                        SELECT 
                            operation_type,
                            AVG(duration_ms) as avg_duration,
                            COUNT(*) as operation_count,
                            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count
                        FROM performance_metrics 
                        WHERE timestamp >= ?
                        GROUP BY operation_type
                    """, (start_time,))
                    
                    perf_stats = {row[0]: {
                        'avg_duration': row[1],
                        'total_ops': row[2],
                        'success_rate': row[3] / row[2] if row[2] > 0 else 0
                    } for row in cursor.fetchall()}
                    
                    return {
                        'transaction_stats': tx_stats,
                        'token_stats': token_stats,
                        'performance_stats': perf_stats,
                        'database_metrics': self._metrics.copy(),
                        'period_hours': hours,
                        'generated_at': datetime.now()
                    }
                    
        except Exception as e:
            self.logger.error(f"Failed to get performance summary: {e}")
            return {}
    
    # === MÉTHODES PUBLIQUES - UTILITAIRES ===
    
    def log_error(self, error_type: str, error_message: str, error_details: Optional[Dict] = None):
        """Enregistre une erreur dans la base"""
        try:
            with self._write_lock:
                with self.pool.get_connection() as conn:
                    conn.execute("""
                        INSERT INTO error_logs 
                        (error_type, error_message, error_details)
                        VALUES (?, ?, ?)
                    """, (
                        error_type,
                        error_message,
                        json.dumps(error_details) if error_details else None
                    ))
                    conn.commit()
                    
        except Exception as e:
            self.logger.error(f"Failed to log error: {e}")
    
    def cleanup_old_data(self, days_to_keep: int = 30) -> Dict[str, int]:
        """Nettoie les anciennes données"""
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        cleanup_stats = {}
        
        try:
            with self._write_lock:
                with self.pool.get_connection() as conn:
                    with self._measure_query_time("cleanup_old_data"):
                        # Nettoyer les anciennes métriques de performance
                        cursor = conn.execute(
                            "DELETE FROM performance_metrics WHERE timestamp < ?",
                            (cutoff_date,)
                        )
                        cleanup_stats['performance_metrics'] = cursor.rowcount
                        
                        # Nettoyer les anciens logs d'erreurs
                        cursor = conn.execute(
                            "DELETE FROM error_logs WHERE timestamp < ?",
                            (cutoff_date,)
                        )
                        cleanup_stats['error_logs'] = cursor.rowcount
                        
                        # Nettoyer les anciennes analytiques (garder plus longtemps)
                        analytics_cutoff = datetime.now() - timedelta(days=days_to_keep * 2)
                        cursor = conn.execute(
                            "DELETE FROM analytics WHERE timestamp < ?",
                            (analytics_cutoff,)
                        )
                        cleanup_stats['analytics'] = cursor.rowcount
                        
                        # Nettoyer les transactions très anciennes et échouées
                        cursor = conn.execute(
                            """DELETE FROM transactions 
                               WHERE created_at < ? AND status IN ('failed', 'cancelled')""",
                            (cutoff_date,)
                        )
                        cleanup_stats['old_transactions'] = cursor.rowcount
                        
                        conn.commit()
                        
                        # VACUUM pour récupérer l'espace
                        conn.execute("VACUUM")
                        
                        self.logger.info(f"Cleanup completed: {cleanup_stats}")
                        return cleanup_stats
                        
        except Exception as e:
            self.logger.error(f"Failed to cleanup old data: {e}")
            return {}
    
    def get_database_stats(self) -> Dict[str, Any]:
        """Récupère les statistiques de la base de données"""
        try:
            with self.pool.get_connection() as conn:
                with self._measure_query_time("get_database_stats"):
                    stats = {}
                    
                    # Tailles des tables
                    tables = ['tokens', 'transactions', 'analytics', 'performance_metrics', 'error_logs']
                    for table in tables:
                        cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
                        stats[f"{table}_count"] = cursor.fetchone()[0]
                    
                    # Informations sur la base
                    cursor = conn.execute("PRAGMA database_list")
                    db_info = cursor.fetchone()
                    
                    # Taille du fichier
                    db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
                    
                    # Informations sur les index
                    cursor = conn.execute("PRAGMA index_list(tokens)")
                    token_indexes = len(cursor.fetchall())
                    
                    stats.update({
                        'database_path': self.db_path,
                        'database_size_mb': db_size / (1024 * 1024),
                        'schema_version': self._get_schema_version(conn),
                        'token_indexes': token_indexes,
                        'connection_pool_size': self.pool._created_connections,
                        'cache_size': len(self._cache),
                        'metrics': self._metrics.copy()
                    })
                    
                    return stats
                    
        except Exception as e:
            self.logger.error(f"Failed to get database stats: {e}")
            return {}
    
    def create_backup(self, backup_path: Optional[str] = None) -> str:
        """Crée une sauvegarde de la base de données"""
        if backup_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = os.path.join(os.path.dirname(self.db_path), "backups")
            os.makedirs(backup_dir, exist_ok=True)
            backup_path = os.path.join(backup_dir, f"backup_{timestamp}.db")
        
        try:
            with self.pool.get_connection() as conn:
                with self._measure_query_time("create_backup"):
                    # Utiliser la commande VACUUM INTO pour créer une copie compacte
                    conn.execute(f"VACUUM INTO '{backup_path}'")
                    
                    self.logger.info(f"Database backup created: {backup_path}")
                    return backup_path
                    
        except Exception as e:
            self.logger.error(f"Failed to create backup: {e}")
            # Fallback: copie simple du fichier
            try:
                shutil.copy2(self.db_path, backup_path)
                self.logger.info(f"Fallback backup created: {backup_path}")
                return backup_path
            except Exception as e2:
                self.logger.error(f"Fallback backup also failed: {e2}")
                raise DatabaseError(f"Backup failed: {e}")
    
    def restore_from_backup(self, backup_path: str) -> bool:
        """Restaure la base depuis une sauvegarde"""
        if not os.path.exists(backup_path):
            raise FileNotFoundError(f"Backup file not found: {backup_path}")
        
        try:
            # Fermer toutes les connexions
            self.close()
            
            # Sauvegarder la base actuelle
            current_backup = f"{self.db_path}.pre_restore_{int(time.time())}"
            shutil.move(self.db_path, current_backup)
            
            # Restaurer depuis la sauvegarde
            shutil.copy2(backup_path, self.db_path)
            
            # Réinitialiser le pool de connexions
            self.pool = ConnectionPool(self.db_path, self.max_connections)
            
            # Vérifier l'intégrité
            with self.pool.get_connection() as conn:
                cursor = conn.execute("PRAGMA integrity_check")
                result = cursor.fetchone()[0]
                
                if result != "ok":
                    # Restaurer l'ancienne base
                    shutil.move(current_backup, self.db_path)
                    self.pool = ConnectionPool(self.db_path, self.max_connections)
                    raise DatabaseError(f"Restored database failed integrity check: {result}")
                
                # Supprimer l'ancienne sauvegarde si tout va bien
                os.remove(current_backup)
                
                self.logger.info(f"Database restored from: {backup_path}")
                return True
                
        except Exception as e:
            self.logger.error(f"Failed to restore from backup: {e}")
            return False
    
    def execute_custom_query(self, query: str, params: Tuple = (), 
                           fetch_results: bool = True) -> Union[List[sqlite3.Row], bool]:
        """Exécute une requête personnalisée (avec précaution)"""
        try:
            with self.pool.get_connection() as conn:
                with self._measure_query_time("custom_query"):
                    cursor = conn.execute(query, params)
                    
                    if fetch_results:
                        return cursor.fetchall()
                    else:
                        conn.commit()
                        return cursor.rowcount > 0
                        
        except Exception as e:
            self.logger.error(f"Custom query failed: {e}")
            if fetch_results:
                return []
            return False
    
    # === MÉTHODES ASYNCHRONES ===
    
    async def async_get_token(self, address: str) -> Optional[TokenRecord]:
        """Version asynchrone de get_token"""
        return await asyncio.get_event_loop().run_in_executor(
            self._executor, self.get_token, address
        )
    
    async def async_add_transaction(self, transaction: TransactionRecord) -> bool:
        """Version asynchrone de add_transaction"""
        return await asyncio.get_event_loop().run_in_executor(
            self._executor, self.add_transaction, transaction
        )
    
    async def async_get_safe_tokens(self, min_safety_score: float = 0.7, 
                                   limit: int = 50) -> List[TokenRecord]:
        """Version asynchrone de get_safe_tokens"""
        return await asyncio.get_event_loop().run_in_executor(
            self._executor, self.get_safe_tokens, min_safety_score, limit
        )
    
    # === MÉTHODES PRIVÉES - CONVERSIONS ===
    
    def _row_to_token_record(self, row: sqlite3.Row) -> TokenRecord:
        """Convertit une ligne de base en TokenRecord"""
        return TokenRecord(
            address=row['address'],
            symbol=row['symbol'],
            name=row['name'],
            decimals=row['decimals'],
            status=TokenStatus(row['status']),
            safety_score=row['safety_score'],
            bundle_detected=bool(row['bundle_detected']),
            bundle_confidence=row['bundle_confidence'],
            risk_indicators=json.loads(row['risk_indicators']) if row['risk_indicators'] else {},
            market_cap=row['market_cap'],
            volume_24h=row['volume_24h'],
            price_usd=row['price_usd'],
            liquidity=row['liquidity'],
            holders_count=row['holders_count'],
            created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
            updated_at=datetime.fromisoformat(row['updated_at']) if row['updated_at'] else None,
            rugcheck_data=json.loads(row['rugcheck_data']) if row['rugcheck_data'] else None,
            dexscreener_data=json.loads(row['dexscreener_data']) if row['dexscreener_data'] else None
        )
    
    def _row_to_transaction_record(self, row: sqlite3.Row) -> TransactionRecord:
        """Convertit une ligne de base en TransactionRecord"""
        return TransactionRecord(
            tx_hash=row['tx_hash'],
            token_address=row['token_address'],
            action=row['action'],
            amount_in=row['amount_in'],
            amount_out=row['amount_out'],
            token_in=row['token_in'],
            token_out=row['token_out'],
            price=row['price'],
            slippage=row['slippage'],
            status=TransactionStatus(row['status']),
            gas_fee=row['gas_fee'],
            created_at=datetime.fromisoformat(row['created_at']) if row['created_at'] else None,
            confirmed_at=datetime.fromisoformat(row['confirmed_at']) if row['confirmed_at'] else None,
            block_number=row['block_number'],
            error_message=row['error_message'],
            metadata=json.loads(row['metadata']) if row['metadata'] else None
        )
    
    def _row_to_analytics_record(self, row: sqlite3.Row) -> AnalyticsRecord:
        """Convertit une ligne de base en AnalyticsRecord"""
        # Tenter de convertir la valeur en type approprié
        metric_value = row['metric_value']
        try:
            # Essayer int d'abord
            metric_value = int(metric_value)
        except ValueError:
            try:
                # Essayer float
                metric_value = float(metric_value)
            except ValueError:
                # Garder comme string
                pass
        
        return AnalyticsRecord(
            metric_name=row['metric_name'],
            metric_value=metric_value,
            metric_type=row['metric_type'],
            timestamp=datetime.fromisoformat(row['timestamp']) if row['timestamp'] else datetime.now(),
            metadata=json.loads(row['metadata']) if row['metadata'] else None
        )
    
    def _invalidate_token_cache(self, address: str):
        """Invalide le cache pour un token spécifique"""
        with self._cache_lock:
            keys_to_remove = [
                key for key in self._cache.keys()
                if address in key or 'tokens' in key
            ]
            for key in keys_to_remove:
                self._cache.pop(key, None)
                self._cache_ttl.pop(key, None)
    
    # === MÉTHODES DE GESTION DU CYCLE DE VIE ===
    
    def close(self):
        """Ferme proprement la base de données"""
        try:
            # Arrêter les workers
            self._executor.shutdown(wait=True)
            
            # Fermer toutes les connexions
            self.pool.close_all()
            
            self.logger.info("Database manager closed successfully")
            
        except Exception as e:
            self.logger.error(f"Error closing database manager: {e}")
    
    def __enter__(self):
        """Support du context manager"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Support du context manager"""
        self.close()
    
    def __del__(self):
        """Destructeur pour s'assurer que les ressources sont libérées"""
        try:
            self.close()
        except:
            pass


# === FONCTIONS UTILITAIRES ===

def create_database_manager(config: Dict) -> DatabaseManager:
    """Factory function pour créer un gestionnaire de base"""
    return DatabaseManager(config)


def migrate_database(db_path: str, backup_first: bool = True) -> bool:
    """Utilitaire pour migrer une base de données existante"""
    try:
        if backup_first and os.path.exists(db_path):
            backup_path = f"{db_path}.backup_{int(time.time())}"
            shutil.copy2(db_path, backup_path)
            print(f"Backup created: {backup_path}")
        
        # Configuration temporaire pour la migration
        config = {
            'database': {
                'path': db_path,
                'backup_enabled': False
            }
        }
        
        with DatabaseManager(config) as db_manager:
            print(f"Migration completed successfully")
            return True
            
    except Exception as e:
        print(f"Migration failed: {e}")
        return False


# === EXEMPLE D'UTILISATION ===

if __name__ == "__main__":
    # Configuration d'exemple
    config = {
        'database': {
            'path': 'data/trading_bot.db',
            'backup_enabled': True,
            'backup_interval_hours': 6,
            'max_connections': 5
        }
    }
    
    # Utilisation avec context manager
    with create_database_manager(config) as db:
        # Ajouter un token d'exemple
        token = TokenRecord(
            address="So11111111111111111111111111111111111111112",
            symbol="SOL",
            name="Solana",
            decimals=9,
            status=TokenStatus.VERIFIED,
            safety_score=0.95,
            bundle_detected=False,
            bundle_confidence=0.0,
            risk_indicators={},
            price_usd=100.50,
            market_cap=45000000000
        )
        
        success = db.add_token(token)
        print(f"Token added: {success}")
        
        # Récupérer des tokens sûrs
        safe_tokens = db.get_safe_tokens(min_safety_score=0.8)
        print(f"Found {len(safe_tokens)} safe tokens")
        
        # Statistiques
        stats = db.get_database_stats()
        print(f"Database stats: {stats}")
    
    print("Database manager example completed")