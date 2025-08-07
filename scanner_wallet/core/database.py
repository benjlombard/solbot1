#!/usr/bin/env python3
"""
Gestionnaire de base de données SQLite thread-safe pour le Solana Wallet Monitor
Centralise toutes les opérations de base de données avec optimisations et sécurité
"""

import sqlite3
import threading
import time
import os
import shutil
from pathlib import Path
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Union, Tuple, Generator
from datetime import datetime, timedelta
import logging
import queue
import json

# Imports depuis la nouvelle structure
from core.config import get_config
from core.exceptions import (
    DatabaseError, DatabaseConnectionError, DatabaseLockError, 
    DatabaseSchemaError, DatabaseIntegrityError
)
from utils.helpers import (
    get_current_timestamp, calculate_time_since, safe_divide,
    generate_short_hash, sanitize_filename
)
from utils.formatters import format_memory_usage, format_duration
from utils.constants import SQLITE_SETTINGS, DB_QUERY_LIMITS, CLEANUP_INTERVALS


# =============================================================================
# CONFIGURATION DE LA BASE DE DONNÉES
# =============================================================================

class DatabaseConfig:
    """Configuration centralisée pour la base de données"""
    
    def __init__(self, config=None):
        if config is None:
            config = get_config()
        
        self.db_path = config.database.get_full_path()
        self.timeout = config.database.timeout
        self.max_connections = getattr(config.database, 'max_connections', 10)
        self.backup_enabled = config.database.backup_enabled
        self.backup_interval_hours = config.database.backup_interval_hours
        self.cleanup_old_data_days = config.database.cleanup_old_data_days
        
        # Paramètres SQLite optimisés
        self.sqlite_settings = SQLITE_SETTINGS.copy()
        self.query_limits = DB_QUERY_LIMITS.copy()
        
        # Créer le répertoire de base de données si nécessaire
        self.db_dir = Path(self.db_path).parent
        self.db_dir.mkdir(parents=True, exist_ok=True)


# =============================================================================
# POOL DE CONNEXIONS THREAD-SAFE
# =============================================================================

class ConnectionPool:
    """Pool de connexions SQLite thread-safe avec gestion des ressources"""
    
    def __init__(self, db_path: str, max_connections: int = 10, timeout: float = 30.0):
        self.db_path = db_path
        self.max_connections = max_connections
        self.timeout = timeout
        
        self._pool = queue.Queue(maxsize=max_connections)
        self._created_connections = 0
        self._lock = threading.RLock()
        self._connection_stats = {
            'total_created': 0,
            'active_connections': 0,
            'total_queries': 0,
            'failed_connections': 0
        }
        
        # Pré-créer quelques connexions
        self._initialize_pool()
    
    def _initialize_pool(self):
        """Initialise le pool avec quelques connexions"""
        initial_connections = min(3, self.max_connections)
        
        for _ in range(initial_connections):
            try:
                conn = self._create_connection()
                self._pool.put(conn, block=False)
            except Exception as e:
                logging.warning(f"Failed to pre-create database connection: {e}")
                break
    
    def _create_connection(self) -> sqlite3.Connection:
        """Crée une nouvelle connexion SQLite optimisée"""
        try:
            conn = sqlite3.connect(
                self.db_path,
                timeout=self.timeout,
                check_same_thread=False,
                isolation_level=None  # Autocommit mode
            )
            
            # Appliquer les optimisations SQLite
            self._optimize_connection(conn)
            
            with self._lock:
                self._created_connections += 1
                self._connection_stats['total_created'] += 1
                self._connection_stats['active_connections'] += 1
            
            return conn
            
        except sqlite3.Error as e:
            with self._lock:
                self._connection_stats['failed_connections'] += 1
            raise DatabaseConnectionError(self.db_path, 0, str(e))
    
    def _optimize_connection(self, conn: sqlite3.Connection):
        """Applique les optimisations SQLite à une connexion"""
        optimizations = [
            f"PRAGMA journal_mode={SQLITE_SETTINGS['journal_mode']}",
            f"PRAGMA synchronous={SQLITE_SETTINGS['synchronous']}",
            f"PRAGMA busy_timeout={SQLITE_SETTINGS['busy_timeout']}",
            f"PRAGMA cache_size={SQLITE_SETTINGS['cache_size']}",
            f"PRAGMA page_size={SQLITE_SETTINGS['page_size']}",
            "PRAGMA temp_store=MEMORY",
            "PRAGMA mmap_size=268435456",  # 256MB
            "PRAGMA optimize"
        ]
        
        cursor = conn.cursor()
        for pragma in optimizations:
            try:
                cursor.execute(pragma)
            except sqlite3.Error as e:
                logging.warning(f"Failed to apply pragma '{pragma}': {e}")
        cursor.close()
    
    def _create_tables(self, cursor: sqlite3.Cursor):
        """Crée toutes les tables nécessaires"""
        
        # Table des transactions (schema principal)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signature TEXT UNIQUE NOT NULL,
                wallet_address TEXT NOT NULL,
                slot INTEGER,
                block_time INTEGER,
                amount REAL DEFAULT 0.0,
                token_mint TEXT,
                token_symbol TEXT,
                token_name TEXT,
                transaction_type TEXT,
                token_amount REAL DEFAULT 0.0,
                price_per_token REAL DEFAULT 0.0,
                fee REAL DEFAULT 0.0,
                status TEXT DEFAULT 'success',
                is_token_transaction BOOLEAN DEFAULT 0,
                is_large_token_amount BOOLEAN DEFAULT 0,
                detection_delay REAL DEFAULT 0.0,
                wallet_priority_at_detection REAL DEFAULT 1.0,
                scan_cycle_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Table des tokens (métadonnées)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tokens (
                address TEXT PRIMARY KEY,
                symbol TEXT,
                name TEXT,
                decimals INTEGER DEFAULT 9,
                price_usd REAL DEFAULT 0.0,
                logo_uri TEXT,
                coingecko_id TEXT,
                is_verified BOOLEAN DEFAULT 0,
                market_cap REAL DEFAULT 0.0,
                volume_24h REAL DEFAULT 0.0,
                price_change_24h REAL DEFAULT 0.0,
                last_price_update INTEGER DEFAULT 0,
                metadata_source TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Table des comptes de tokens (ATA)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS token_accounts (
                wallet_address TEXT NOT NULL,
                ata_pubkey TEXT NOT NULL,
                token_mint TEXT NOT NULL,
                balance REAL DEFAULT 0.0,
                decimals INTEGER DEFAULT 9,
                first_seen INTEGER NOT NULL,
                last_updated INTEGER NOT NULL,
                last_scanned INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT 1,
                scan_priority INTEGER DEFAULT 1,
                activity_score REAL DEFAULT 0.0,
                last_activity_time INTEGER DEFAULT 0,
                total_transactions INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (wallet_address, ata_pubkey)
            )
        ''')
        
        # Table des priorités des wallets
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS wallet_priorities (
                wallet_address TEXT PRIMARY KEY,
                priority_score REAL DEFAULT 1.0,
                last_scan_time INTEGER DEFAULT 0,
                scan_count_1h INTEGER DEFAULT 0,
                scan_count_24h INTEGER DEFAULT 0,
                activity_score REAL DEFAULT 0.0,
                volume_score_1h REAL DEFAULT 0.0,
                new_tokens_score_1h INTEGER DEFAULT 0,
                total_scans INTEGER DEFAULT 0,
                avg_scan_duration REAL DEFAULT 0.0,
                last_activity_detected INTEGER DEFAULT 0,
                consecutive_empty_scans INTEGER DEFAULT 0,
                best_priority_ever REAL DEFAULT 1.0,
                worst_priority_ever REAL DEFAULT 1.0,
                priority_history TEXT DEFAULT '[]',
                updated_at INTEGER DEFAULT 0,
                created_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        ''')
        
        # Table des statistiques des wallets
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS wallet_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL,
                balance_sol REAL DEFAULT 0.0,
                total_transactions INTEGER DEFAULT 0,
                total_volume REAL DEFAULT 0.0,
                pnl REAL DEFAULT 0.0,
                largest_transaction REAL DEFAULT 0.0,
                token_count INTEGER DEFAULT 0,
                active_token_count INTEGER DEFAULT 0,
                first_transaction_time INTEGER DEFAULT 0,
                last_transaction_time INTEGER DEFAULT 0,
                avg_transaction_size REAL DEFAULT 0.0,
                success_rate REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Table de l'historique des scans
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scan_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL,
                scan_type TEXT NOT NULL,
                total_accounts INTEGER DEFAULT 0,
                new_accounts INTEGER DEFAULT 0,
                scan_duration REAL DEFAULT 0.0,
                completed_at INTEGER NOT NULL,
                priority_score_before REAL DEFAULT 1.0,
                priority_score_after REAL DEFAULT 1.0,
                rpc_requests_count INTEGER DEFAULT 0,
                efficiency_score REAL DEFAULT 0.0,
                activity_detected INTEGER DEFAULT 0,
                errors_count INTEGER DEFAULT 0,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Table des métriques d'activité des wallets
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS wallet_activity_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                period_minutes INTEGER DEFAULT 15,
                new_transactions_count INTEGER DEFAULT 0,
                volume_sol REAL DEFAULT 0.0,
                new_token_accounts INTEGER DEFAULT 0,
                scan_duration REAL DEFAULT 0.0,
                discoveries_count INTEGER DEFAULT 0,
                balance_changes_count INTEGER DEFAULT 0,
                rpc_requests_made INTEGER DEFAULT 0,
                errors_count INTEGER DEFAULT 0,
                efficiency_score REAL DEFAULT 0.0,
                throughput_score REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Table de la queue de scan
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scan_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL,
                priority_score REAL NOT NULL,
                scheduled_time INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                scan_type TEXT DEFAULT 'balance_change',
                estimated_duration REAL DEFAULT 30.0,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                started_at INTEGER,
                completed_at INTEGER,
                error_message TEXT
            )
        ''')
        
        # Table des configurations système
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                value_type TEXT DEFAULT 'string',
                description TEXT,
                is_encrypted BOOLEAN DEFAULT 0,
                updated_at INTEGER DEFAULT (strftime('%s', 'now')),
                created_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        ''')
        
        # Table des logs système (optionnelle)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER NOT NULL,
                level TEXT NOT NULL,
                logger_name TEXT,
                message TEXT NOT NULL,
                wallet_address TEXT,
                cycle_id TEXT,
                scan_id TEXT,
                signature TEXT,
                token_mint TEXT,
                exception_info TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    

    def _check_schema_version(self, cursor: sqlite3.Cursor):
        """Vérifie et met à jour la version du schéma si nécessaire"""
        try:
            # Vérifier la version actuelle
            cursor.execute("SELECT value FROM system_config WHERE key = 'schema_version'")
            result = cursor.fetchone()
            
            current_version = int(result[0]) if result else 0
            target_version = self.stats['schema_version']
            
            if current_version < target_version:
                self.logger.info(f"Upgrading database schema from version {current_version} to {target_version}")
                self._upgrade_schema(cursor, current_version, target_version)
                
                # Mettre à jour la version
                cursor.execute('''
                    INSERT OR REPLACE INTO system_config (key, value, description)
                    VALUES ('schema_version', ?, 'Database schema version')
                ''', (str(target_version),))
            
        except sqlite3.Error as e:
            self.logger.warning(f"Schema version check failed: {e}")
    
    def _upgrade_schema(self, cursor: sqlite3.Cursor, from_version: int, to_version: int):
        """Met à jour le schéma de base de données"""
        # Pour l'instant, pas de migrations spécifiques
        # À implémenter selon les besoins futurs
        pass
    
    def _start_maintenance_thread(self):
        """Démarre le thread de maintenance automatique"""
        if self.maintenance_thread and self.maintenance_thread.is_alive():
            return
        
        self.maintenance_thread = threading.Thread(
            target=self._maintenance_loop,
            name="DatabaseMaintenance",
            daemon=True
        )
        self.maintenance_thread.start()
        self.logger.info("Database maintenance thread started")
    
    def _maintenance_loop(self):
        """Boucle de maintenance automatique"""
        while not self.maintenance_stop_event.wait(3600):  # Vérifier toutes les heures
            try:
                current_time = get_current_timestamp()
                
                # Backup automatique
                if (self.config.backup_enabled and 
                    current_time - self.stats['last_backup'] > self.config.backup_interval_hours * 3600):
                    self._perform_backup()
                
                # Nettoyage automatique (toutes les 6 heures par défaut)
                cleanup_interval = 6 * 3600  # 6 heures
                try:
                    cleanup_interval = CLEANUP_INTERVALS.get('cache_cleanup', 6 * 3600)
                except (NameError, AttributeError):
                    pass
                    
                if current_time - self.stats['last_cleanup'] > cleanup_interval:
                    self._perform_cleanup()
                
                # Optimisation VACUUM (hebdomadaire)
                if current_time % (7 * 24 * 3600) < 3600:  # Une fois par semaine
                    self._vacuum_database()
                
                # Nettoyage des connexions inactives du pool
                self._cleanup_connection_pool()
                
            except Exception as e:
                self.logger.error(f"Maintenance loop error: {e}")
    
    def _cleanup_connection_pool(self):
        """Nettoie les connexions inactives du pool"""
        try:
            # Cette méthode peut être appelée périodiquement pour optimiser le pool
            # Pour l'instant, on laisse le pool se gérer automatiquement
            pass
        except Exception as e:
            self.logger.warning(f"Connection pool cleanup error: {e}")
    
    def _create_indexes(self, cursor: sqlite3.Cursor):
        """Crée tous les index nécessaires pour optimiser les performances"""
        
        indexes = [
            # Index sur les transactions
            "CREATE INDEX IF NOT EXISTS idx_transactions_wallet_time ON transactions(wallet_address, block_time DESC)",
            "CREATE INDEX IF NOT EXISTS idx_transactions_signature ON transactions(signature)",
            "CREATE INDEX IF NOT EXISTS idx_transactions_token_type ON transactions(is_token_transaction, block_time DESC)",
            "CREATE INDEX IF NOT EXISTS idx_transactions_large_amount ON transactions(is_large_token_amount, block_time DESC)",
            "CREATE INDEX IF NOT EXISTS idx_transactions_token_mint ON transactions(token_mint, block_time DESC)",
            "CREATE INDEX IF NOT EXISTS idx_transactions_cycle ON transactions(scan_cycle_id)",
            
            # Index sur les comptes de tokens
            "CREATE INDEX IF NOT EXISTS idx_token_accounts_wallet ON token_accounts(wallet_address)",
            "CREATE INDEX IF NOT EXISTS idx_token_accounts_mint ON token_accounts(token_mint)",
            "CREATE INDEX IF NOT EXISTS idx_token_accounts_priority ON token_accounts(scan_priority DESC, last_scanned ASC)",
            "CREATE INDEX IF NOT EXISTS idx_token_accounts_active ON token_accounts(is_active, last_updated DESC)",
            "CREATE INDEX IF NOT EXISTS idx_token_accounts_activity ON token_accounts(activity_score DESC, last_activity_time DESC)",
            "CREATE INDEX IF NOT EXISTS idx_token_accounts_balance ON token_accounts(balance DESC) WHERE balance > 0",
            
            # Index sur les priorités des wallets
            "CREATE INDEX IF NOT EXISTS idx_wallet_priorities_score ON wallet_priorities(priority_score DESC, last_scan_time ASC)",
            "CREATE INDEX IF NOT EXISTS idx_wallet_priorities_activity ON wallet_priorities(last_activity_detected DESC)",
            "CREATE INDEX IF NOT EXISTS idx_wallet_priorities_scans ON wallet_priorities(total_scans DESC)",
            
            # Index sur l'historique des scans
            "CREATE INDEX IF NOT EXISTS idx_scan_history_wallet ON scan_history(wallet_address, completed_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_scan_history_time ON scan_history(completed_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_scan_history_activity ON scan_history(activity_detected, completed_at DESC)",
            
            # Index sur les métriques d'activité
            "CREATE INDEX IF NOT EXISTS idx_activity_metrics_wallet_time ON wallet_activity_metrics(wallet_address, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_activity_metrics_timestamp ON wallet_activity_metrics(timestamp DESC)",
            
            # Index sur les tokens
            "CREATE INDEX IF NOT EXISTS idx_tokens_symbol ON tokens(symbol)",
            "CREATE INDEX IF NOT EXISTS idx_tokens_verified ON tokens(is_verified, symbol)",
            "CREATE INDEX IF NOT EXISTS idx_tokens_price_update ON tokens(last_price_update DESC)",
            
            # Index sur les statistiques des wallets
            "CREATE INDEX IF NOT EXISTS idx_wallet_stats_address ON wallet_stats(wallet_address, updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_wallet_stats_volume ON wallet_stats(total_volume DESC)",
            
            # Index sur la queue de scan
            "CREATE INDEX IF NOT EXISTS idx_scan_queue_priority ON scan_queue(status, priority_score DESC, scheduled_time ASC)",
            "CREATE INDEX IF NOT EXISTS idx_scan_queue_status ON scan_queue(status, created_at DESC)",
            
            # Index sur les logs système
            "CREATE INDEX IF NOT EXISTS idx_system_logs_timestamp ON system_logs(timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_system_logs_level ON system_logs(level, timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_system_logs_wallet ON system_logs(wallet_address, timestamp DESC)"
        ]
        
        for index_sql in indexes:
            try:
                cursor.execute(index_sql)
            except sqlite3.Error as e:
                self.logger.warning(f"Failed to create index: {index_sql[:50]}... Error: {e}")

    @contextmanager
    def get_connection(self, retry_count: int = 3) -> Generator[sqlite3.Connection, None, None]:
        """Context manager pour obtenir une connexion de base de données"""
        with self.connection_pool.get_connection(retry_count) as conn:
            try:
                self.stats['total_operations'] += 1
                yield conn
            except Exception as e:
                self.stats['failed_operations'] += 1
                raise
    
    def execute_query(self, query: str, params: tuple = (), fetch_one: bool = False, 
                     fetch_all: bool = False) -> Union[sqlite3.Cursor, Any, List[Any]]:
        """Exécute une requête SQL avec gestion d'erreurs"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                
                if fetch_one:
                    return cursor.fetchone()
                elif fetch_all:
                    return cursor.fetchall()
                else:
                    return cursor
                    
        except sqlite3.Error as e:
            self.logger.error(f"Query execution failed: {query[:100]}... Error: {e}")
            raise DatabaseError(f"Query execution failed: {e}")
    
    def execute_many(self, query: str, params_list: List[tuple]) -> int:
        """Exécute une requête en batch pour plusieurs paramètres"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.executemany(query, params_list)
                conn.commit()
                return cursor.rowcount
                
        except sqlite3.Error as e:
            self.logger.error(f"Batch execution failed: {query[:100]}... Error: {e}")
            raise DatabaseError(f"Batch execution failed: {e}")
    
    def transaction(self) -> 'DatabaseTransaction':
        """Retourne un context manager pour les transactions"""
        return DatabaseTransaction(self)
    
    def _perform_backup(self):
        """Effectue une sauvegarde de la base de données"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"backup_{timestamp}_{sanitize_filename(Path(self.config.db_path).stem)}.db"
            backup_path = self.config.db_dir / "backups" / backup_filename
            
            # Créer le répertoire de backup
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Effectuer la sauvegarde
            with self.get_connection() as conn:
                backup = sqlite3.connect(str(backup_path))
                conn.backup(backup)
                backup.close()
            
            # Nettoyer les anciens backups (garder 10 plus récents)
            self._cleanup_old_backups(backup_path.parent, keep_count=10)
            
            self.stats['last_backup'] = get_current_timestamp()
            self.logger.info(f"Database backup created: {backup_path}")
            
        except Exception as e:
            self.logger.error(f"Backup failed: {e}")
    
    def _cleanup_old_backups(self, backup_dir: Path, keep_count: int = 10):
        """Nettoie les anciens fichiers de backup"""
        try:
            backup_files = list(backup_dir.glob("backup_*.db"))
            backup_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            
            # Supprimer les anciens backups
            for old_backup in backup_files[keep_count:]:
                try:
                    old_backup.unlink()
                    self.logger.debug(f"Deleted old backup: {old_backup}")
                except Exception as e:
                    self.logger.warning(f"Failed to delete backup {old_backup}: {e}")
                    
        except Exception as e:
            self.logger.error(f"Backup cleanup failed: {e}")
    
    def _perform_cleanup(self):
        """Effectue le nettoyage automatique des anciennes données"""
        try:
            # Tâches de nettoyage par défaut si CLEANUP_INTERVALS n'est pas disponible
            try:
                cleanup_tasks = [
                    ("scan_history", "completed_at", CLEANUP_INTERVALS.get('old_scan_history', 30)),
                    ("wallet_activity_metrics", "timestamp", CLEANUP_INTERVALS.get('old_metrics', 7)),
                    ("system_logs", "timestamp", CLEANUP_INTERVALS.get('old_logs', 14)),
                    ("token_accounts", "last_updated", CLEANUP_INTERVALS.get('inactive_accounts', 90)),
                    ("transactions", "block_time", CLEANUP_INTERVALS.get('old_transactions', 365))
                ]
            except (NameError, AttributeError):
                # Fallback si CLEANUP_INTERVALS n'est pas disponible
                cleanup_tasks = [
                    ("scan_history", "completed_at", 30),  # Garder 30 jours
                    ("wallet_activity_metrics", "timestamp", 7),  # Garder 7 jours
                    ("system_logs", "timestamp", 14),  # Garder 14 jours
                    ("token_accounts", "last_updated", 90),  # Garder 90 jours pour les comptes inactifs
                    ("transactions", "block_time", 365)  # Garder 1 an de transactions
                ]
            
            current_time = get_current_timestamp()
            total_deleted = 0
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                for table, timestamp_column, days_to_keep in cleanup_tasks:
                    try:
                        cutoff_timestamp = current_time - (days_to_keep * 24 * 3600)
                        
                        cursor.execute(f'''
                            DELETE FROM {table} 
                            WHERE {timestamp_column} < ?
                        ''', (cutoff_timestamp,))
                        
                        deleted_count = cursor.rowcount
                        total_deleted += deleted_count
                        
                        if deleted_count > 0:
                            self.logger.info(f"Cleaned up {deleted_count} old records from {table}")
                            
                    except sqlite3.Error as e:
                        self.logger.error(f"Cleanup failed for table {table}: {e}")
                
                conn.commit()
            
            self.stats['last_cleanup'] = current_time
            if total_deleted > 0:
                self.logger.info(f"Database cleanup completed: {total_deleted} total records deleted")
                
        except Exception as e:
            self.logger.error(f"Database cleanup failed: {e}")
            
    @contextmanager
    def get_connection(self, retry_count: int = 3) -> Generator[sqlite3.Connection, None, None]:
        """Context manager pour obtenir une connexion du pool"""
        conn = None
        start_time = time.time()
        
        for attempt in range(retry_count):
            try:
                # Essayer de récupérer une connexion du pool
                try:
                    conn = self._pool.get(block=True, timeout=5.0)
                except queue.Empty:
                    # Créer une nouvelle connexion si le pool est vide
                    if self._created_connections < self.max_connections:
                        conn = self._create_connection()
                    else:
                        raise DatabaseConnectionError(
                            self.db_path, 
                            attempt + 1, 
                            "Connection pool exhausted"
                        )
                
                # Vérifier que la connexion est valide
                try:
                    conn.execute("SELECT 1").fetchone()
                    break
                except sqlite3.Error:
                    # Connexion invalide, en créer une nouvelle
                    self._close_connection(conn)
                    conn = self._create_connection()
                    break
                    
            except Exception as e:
                if attempt < retry_count - 1:
                    wait_time = (attempt + 1) * 0.1
                    time.sleep(wait_time)
                    continue
                else:
                    raise DatabaseConnectionError(self.db_path, attempt + 1, str(e))
        
        try:
            with self._lock:
                self._connection_stats['total_queries'] += 1
            
            yield conn
            
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e).lower():
                wait_time = time.time() - start_time
                raise DatabaseLockError(self.db_path, wait_time)
            else:
                raise DatabaseError(f"Database operation failed: {e}")
                
        except sqlite3.IntegrityError as e:
            raise DatabaseIntegrityError(str(e))
            
        except sqlite3.Error as e:
            raise DatabaseError(f"Database error: {e}")
            
        finally:
            # Remettre la connexion dans le pool
            if conn:
                try:
                    # Nettoyer les transactions en cours
                    conn.rollback()
                    
                    # Remettre dans le pool si possible
                    try:
                        self._pool.put(conn, block=False)
                    except queue.Full:
                        # Pool plein, fermer la connexion
                        self._close_connection(conn)
                        
                except Exception as e:
                    logging.warning(f"Error returning connection to pool: {e}")
                    self._close_connection(conn)
    
    def _close_connection(self, conn: sqlite3.Connection):
        """Ferme une connexion proprement"""
        try:
            conn.close()
            with self._lock:
                self._created_connections -= 1
                self._connection_stats['active_connections'] -= 1
        except Exception as e:
            logging.warning(f"Error closing database connection: {e}")
    
    def close_all(self):
        """Ferme toutes les connexions du pool"""
        with self._lock:
            while not self._pool.empty():
                try:
                    conn = self._pool.get(block=False)
                    self._close_connection(conn)
                except queue.Empty:
                    break
                except Exception as e:
                    logging.warning(f"Error closing pooled connection: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques du pool"""
        with self._lock:
            return {
                'max_connections': self.max_connections,
                'active_connections': self._connection_stats['active_connections'],
                'pool_size': self._pool.qsize(),
                'total_created': self._connection_stats['total_created'],
                'total_queries': self._connection_stats['total_queries'],
                'failed_connections': self._connection_stats['failed_connections']
            }


# =============================================================================
# GESTIONNAIRE PRINCIPAL DE BASE DE DONNÉES
# =============================================================================

class DatabaseManager:
    """Gestionnaire principal de base de données avec fonctionnalités avancées"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, config=None):
        """Singleton pattern thread-safe"""
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, config=None):
        # Éviter la réinitialisation multiple
        if hasattr(self, '_initialized'):
            return
        
        self.config = DatabaseConfig(config)
        self.logger = logging.getLogger(__name__)
        
        # Initialiser le pool de connexions
        self.connection_pool = ConnectionPool(
            self.config.db_path,
            self.config.max_connections,
            self.config.timeout
        )
        
        # Statistiques et monitoring
        self.stats = {
            'start_time': time.time(),
            'total_operations': 0,
            'failed_operations': 0,
            'last_backup': 0,
            'last_cleanup': 0,
            'schema_version': 1
        }
        
        # Thread pour les tâches de maintenance
        self.maintenance_thread = None
        self.maintenance_stop_event = threading.Event()
        
        # Initialiser la base de données
        self._initialize_database()
        
        # Démarrer la maintenance automatique
        self._start_maintenance_thread()
        
        self._initialized = True
        self.logger.info(f"DatabaseManager initialized with path: {self.config.db_path}")
    
    def _initialize_database(self):
        """Initialise la base de données avec le schéma complet"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Créer toutes les tables
                self._create_tables(cursor)
                
                # Créer les index optimisés
                self._create_indexes(cursor)
                
                # Vérifier et mettre à jour le schéma si nécessaire
                self._check_schema_version(cursor)
                
                conn.commit()
                
            self.logger.info("Database schema initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize database: {e}")
            raise DatabaseError(f"Database initialization failed: {e}")
    
    def _vacuum_database(self):
        """Optimise la base de données avec VACUUM"""
        try:
            start_time = time.time()
            
            with self.get_connection() as conn:
                # VACUUM ne peut pas être dans une transaction
                conn.isolation_level = None
                cursor = conn.cursor()
                cursor.execute("VACUUM")
                cursor.execute("ANALYZE")
                conn.isolation_level = ""
            
            duration = time.time() - start_time
            self.logger.info(f"Database VACUUM completed in {duration:.2f}s")
            
        except Exception as e:
            self.logger.error(f"Database VACUUM failed: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques de la base de données"""
        try:
            stats = self.stats.copy()
            
            # Ajouter les stats du pool de connexions
            stats['connection_pool'] = self.connection_pool.get_stats()
            
            # Calculer des métriques dérivées
            uptime = time.time() - stats['start_time']
            stats['uptime_hours'] = uptime / 3600
            stats['operations_per_hour'] = safe_divide(stats['total_operations'], uptime / 3600, 0)
            stats['error_rate'] = safe_divide(stats['failed_operations'], stats['total_operations'], 0) * 100
            
            # Ajouter les informations sur le fichier de base de données
            try:
                db_path = Path(self.config.db_path)
                if db_path.exists():
                    stat = db_path.stat()
                    stats['database_file'] = {
                        'path': str(db_path),
                        'size_bytes': stat.st_size,
                        'size_mb': stat.st_size / (1024 * 1024),
                        'modified': stat.st_mtime,
                        'created': stat.st_ctime
                    }
            except Exception as e:
                stats['database_file'] = {'error': str(e)}
            
            # Statistiques des tables
            try:
                with self.get_connection() as conn:
                    cursor = conn.cursor()
                    
                    tables_stats = {}
                    tables = ['transactions', 'token_accounts', 'wallet_priorities', 
                            'scan_history', 'wallet_activity_metrics', 'tokens']
                    
                    for table in tables:
                        try:
                            cursor.execute(f"SELECT COUNT(*) FROM {table}")
                            count = cursor.fetchone()[0]
                            tables_stats[table] = {'row_count': count}
                        except sqlite3.Error:
                            tables_stats[table] = {'row_count': 'error'}
                    
                    stats['tables'] = tables_stats
                    
            except Exception as e:
                stats['tables'] = {'error': str(e)}
            
            return stats
            
        except Exception as e:
            self.logger.error(f"Failed to get database stats: {e}")
            return {'error': str(e)}

    def get_health_status(self) -> Dict[str, Any]:
        """Retourne le status de santé de la base de données"""
        health = {
            'status': 'healthy',
            'checks': {},
            'timestamp': get_current_timestamp()
        }
        
        try:
            # Test de connectivité
            try:
                with self.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT 1")
                    result = cursor.fetchone()
                    
                health['checks']['connectivity'] = {
                    'status': 'ok' if result and result[0] == 1 else 'error',
                    'message': 'Database connection test successful' if result else 'Connection test failed'
                }
            except Exception as e:
                health['checks']['connectivity'] = {
                    'status': 'error',
                    'message': f'Connection failed: {e}'
                }
                health['status'] = 'critical'
            
            # Test de performance
            try:
                start_time = time.time()
                with self.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM transactions LIMIT 1")
                    cursor.fetchone()
                
                query_time = time.time() - start_time
                
                if query_time < 0.1:
                    perf_status = 'excellent'
                elif query_time < 0.5:
                    perf_status = 'good'
                elif query_time < 2.0:
                    perf_status = 'fair'
                else:
                    perf_status = 'poor'
                    if health['status'] == 'healthy':
                        health['status'] = 'warning'
                
                health['checks']['performance'] = {
                    'status': perf_status,
                    'query_time_ms': round(query_time * 1000, 2),
                    'message': f'Query performance is {perf_status}'
                }
                
            except Exception as e:
                health['checks']['performance'] = {
                    'status': 'error',
                    'message': f'Performance test failed: {e}'
                }
            
            # Vérification de l'espace disque
            try:
                db_path = Path(self.config.db_path)
                if db_path.exists():
                    free_space = shutil.disk_usage(db_path.parent).free
                    free_space_mb = free_space / (1024 * 1024)
                    
                    if free_space_mb > 1000:  # >1GB
                        space_status = 'ok'
                        message = f'Sufficient disk space: {free_space_mb:.0f}MB free'
                    elif free_space_mb > 100:  # >100MB
                        space_status = 'warning'
                        message = f'Low disk space: {free_space_mb:.0f}MB free'
                        if health['status'] == 'healthy':
                            health['status'] = 'warning'
                    else:
                        space_status = 'critical'
                        message = f'Critical disk space: {free_space_mb:.0f}MB free'
                        health['status'] = 'critical'
                    
                    health['checks']['disk_space'] = {
                        'status': space_status,
                        'free_space_mb': round(free_space_mb, 1),
                        'message': message
                    }
                        
            except Exception as e:
                health['checks']['disk_space'] = {
                    'status': 'unknown',
                    'message': f'Disk space check failed: {e}'
                }
            
            # Vérification de l'intégrité (échantillon)
            try:
                with self.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("PRAGMA integrity_check(10)")
                    integrity_results = cursor.fetchall()
                    
                    if len(integrity_results) == 1 and integrity_results[0][0] == 'ok':
                        health['checks']['integrity'] = {
                            'status': 'ok',
                            'message': 'Database integrity is good'
                        }
                    else:
                        health['checks']['integrity'] = {
                            'status': 'warning',
                            'message': f'Integrity issues found: {len(integrity_results)} problems',
                            'details': [result[0] for result in integrity_results[:5]]
                        }
                        if health['status'] == 'healthy':
                            health['status'] = 'warning'
                            
            except Exception as e:
                health['checks']['integrity'] = {
                    'status': 'error',
                    'message': f'Integrity check failed: {e}'
                }
            
            # Stats du pool de connexions
            pool_stats = self.connection_pool.get_stats()
            active_ratio = safe_divide(pool_stats['active_connections'], pool_stats['max_connections'], 0)
            
            if active_ratio < 0.8:
                pool_status = 'ok'
            elif active_ratio < 0.95:
                pool_status = 'warning'
            else:
                pool_status = 'critical'
                health['status'] = 'critical'
            
            health['checks']['connection_pool'] = {
                'status': pool_status,
                'active_connections': pool_stats['active_connections'],
                'max_connections': pool_stats['max_connections'],
                'utilization_percent': round(active_ratio * 100, 1),
                'message': f'Connection pool utilization: {active_ratio*100:.1f}%'
            }
            
        except Exception as e:
            health['status'] = 'error'
            health['error'] = str(e)
            self.logger.error(f"Health check failed: {e}")
        
        return health

    def backup_database(self, backup_path: Optional[str] = None) -> str:
        """Crée une sauvegarde manuelle de la base de données"""
        try:
            if backup_path is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_filename = f"manual_backup_{timestamp}.db"
                backup_path = str(self.config.db_dir / "backups" / backup_filename)
            
            # Créer le répertoire si nécessaire
            Path(backup_path).parent.mkdir(parents=True, exist_ok=True)
            
            # Effectuer la sauvegarde
            with self.get_connection() as conn:
                backup = sqlite3.connect(backup_path)
                conn.backup(backup)
                backup.close()
            
            self.logger.info(f"Manual backup created: {backup_path}")
            return backup_path
            
        except Exception as e:
            self.logger.error(f"Manual backup failed: {e}")
            raise DatabaseError(f"Backup failed: {e}")

    def restore_database(self, backup_path: str, confirm: bool = False):
        """Restaure la base de données depuis une sauvegarde"""
        if not confirm:
            raise DatabaseError("Database restore requires explicit confirmation")
        
        backup_file = Path(backup_path)
        if not backup_file.exists():
            raise DatabaseError(f"Backup file not found: {backup_path}")
        
        try:
            # Arrêter le thread de maintenance
            self.maintenance_stop_event.set()
            if self.maintenance_thread:
                self.maintenance_thread.join(timeout=5)
            
            # Fermer toutes les connexions
            self.connection_pool.close_all()
            
            # Sauvegarder la base actuelle
            current_backup = f"{self.config.db_path}.pre_restore_{int(time.time())}"
            shutil.copy2(self.config.db_path, current_backup)
            
            # Restaurer depuis la sauvegarde
            shutil.copy2(backup_path, self.config.db_path)
            
            # Recréer le pool de connexions
            self.connection_pool = ConnectionPool(
                self.config.db_path,
                self.config.max_connections,
                self.config.timeout
            )
            
            # Redémarrer la maintenance
            self.maintenance_stop_event.clear()
            self._start_maintenance_thread()
            
            self.logger.info(f"Database restored from: {backup_path}")
            self.logger.info(f"Previous database saved as: {current_backup}")
            
        except Exception as e:
            self.logger.error(f"Database restore failed: {e}")
            raise DatabaseError(f"Restore failed: {e}")

    def optimize_database(self) -> Dict[str, Any]:
        """Optimise la base de données (VACUUM, ANALYZE, etc.)"""
        try:
            start_time = time.time()
            results = {}
            
            with self.get_connection() as conn:
                conn.isolation_level = None  # Autocommit pour VACUUM
                cursor = conn.cursor()
                
                # VACUUM pour récupérer l'espace
                vacuum_start = time.time()
                cursor.execute("VACUUM")
                results['vacuum_duration'] = time.time() - vacuum_start
                
                # ANALYZE pour optimiser les requêtes
                analyze_start = time.time()
                cursor.execute("ANALYZE")
                results['analyze_duration'] = time.time() - analyze_start
                
                # Vérifier l'intégrité
                integrity_start = time.time()
                cursor.execute("PRAGMA integrity_check")
                integrity_results = cursor.fetchall()
                results['integrity_check'] = {
                    'duration': time.time() - integrity_start,
                    'status': 'ok' if len(integrity_results) == 1 and integrity_results[0][0] == 'ok' else 'issues_found',
                    'issues_count': len(integrity_results) if integrity_results[0][0] != 'ok' else 0
                }
                
                conn.isolation_level = ""  # Remettre en mode transaction
            
            results['total_duration'] = time.time() - start_time
            results['timestamp'] = get_current_timestamp()
            
            self.logger.info(f"Database optimization completed in {results['total_duration']:.2f}s")
            return results
            
        except Exception as e:
            self.logger.error(f"Database optimization failed: {e}")
            raise DatabaseError(f"Optimization failed: {e}")

    def execute_script(self, script_path: str) -> bool:
        """Exécute un script SQL depuis un fichier"""
        try:
            script_file = Path(script_path)
            if not script_file.exists():
                raise DatabaseError(f"Script file not found: {script_path}")
            
            with open(script_file, 'r', encoding='utf-8') as f:
                script_content = f.read()
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # Exécuter le script par blocs (séparés par ;)
                for statement in script_content.split(';'):
                    statement = statement.strip()
                    if statement:
                        cursor.execute(statement)
                conn.commit()
            
            self.logger.info(f"Script executed successfully: {script_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Script execution failed: {script_path}, Error: {e}")
            return False
    
    def get_table_info(self, table_name: str) -> Dict[str, Any]:
        """Récupère les informations détaillées d'une table"""
        try:
            info = {}
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Structure de la table
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = cursor.fetchall()
                info['columns'] = [
                    {
                        'name': col[1],
                        'type': col[2],
                        'not_null': bool(col[3]),
                        'default_value': col[4],
                        'primary_key': bool(col[5])
                    }
                    for col in columns
                ]
                
                # Nombre de lignes
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                info['row_count'] = cursor.fetchone()[0]
                
                # Index sur cette table
                cursor.execute(f"PRAGMA index_list({table_name})")
                indexes = cursor.fetchall()
                info['indexes'] = [
                    {
                        'name': idx[1],
                        'unique': bool(idx[2]),
                        'origin': idx[3]
                    }
                    for idx in indexes
                ]
                
                # Taille approximative (en pages)
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM pragma_table_info('{table_name}')")
                    column_count = cursor.fetchone()[0]
                    info['estimated_size_kb'] = (info['row_count'] * column_count * 8) / 1024
                except Exception:
                    info['estimated_size_kb'] = 0
            
            return info
            
        except Exception as e:
            self.logger.error(f"Failed to get table info for {table_name}: {e}")
            return {'error': str(e)}
    
    def export_table_to_csv(self, table_name: str, output_path: str, limit: Optional[int] = None) -> bool:
        """Exporte une table vers un fichier CSV"""
        try:
            import csv
            
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            query = f"SELECT * FROM {table_name}"
            if limit:
                query += f" LIMIT {limit}"
            
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                
                # Récupérer les noms des colonnes
                column_names = [description[0] for description in cursor.description]
                
                # Écrire vers le CSV
                with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                    writer = csv.writer(csvfile)
                    writer.writerow(column_names)  # En-têtes
                    
                    # Écrire les données par chunks pour économiser la mémoire
                    while True:
                        rows = cursor.fetchmany(1000)  # 1000 lignes à la fois
                        if not rows:
                            break
                        writer.writerows(rows)
            
            self.logger.info(f"Table {table_name} exported to {output_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to export table {table_name}: {e}")
            return False
    
    def import_csv_to_table(self, table_name: str, csv_path: str, 
                           mapping: Optional[Dict[str, str]] = None) -> bool:
        """Importe un CSV dans une table"""
        try:
            import csv
            
            csv_file = Path(csv_path)
            if not csv_file.exists():
                raise DatabaseError(f"CSV file not found: {csv_path}")
            
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                # Préparer la requête d'insertion
                if mapping:
                    # Utiliser le mapping fourni
                    db_columns = list(mapping.values())
                    csv_columns = list(mapping.keys())
                else:
                    # Utiliser les colonnes telles quelles
                    csv_columns = reader.fieldnames
                    db_columns = csv_columns
                
                placeholders = ', '.join(['?' for _ in db_columns])
                column_names = ', '.join(db_columns)
                insert_query = f"INSERT INTO {table_name} ({column_names}) VALUES ({placeholders})"
                
                # Insérer les données par batch
                batch_size = 1000
                batch_data = []
                
                with self.transaction() as cursor:
                    for row in reader:
                        if mapping:
                            values = [row.get(csv_col, '') for csv_col in csv_columns]
                        else:
                            values = [row.get(col, '') for col in csv_columns]
                        
                        batch_data.append(tuple(values))
                        
                        if len(batch_data) >= batch_size:
                            cursor.executemany(insert_query, batch_data)
                            batch_data = []
                    
                    # Insérer le dernier batch
                    if batch_data:
                        cursor.executemany(insert_query, batch_data)
            
            self.logger.info(f"CSV {csv_path} imported to table {table_name}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to import CSV to {table_name}: {e}")
            return False
        """Ferme proprement le gestionnaire de base de données"""
        try:
            # Arrêter le thread de maintenance
            self.maintenance_stop_event.set()
            if self.maintenance_thread and self.maintenance_thread.is_alive():
                self.maintenance_thread.join(timeout=10)
            
            # Fermer toutes les connexions
            self.connection_pool.close_all()
            
            self.logger.info("DatabaseManager closed successfully")
            
        except Exception as e:
            self.logger.error(f"Error closing DatabaseManager: {e}")

    def close(self):
        """Ferme proprement le gestionnaire de base de données"""
        try:
            # Arrêter le thread de maintenance
            self.maintenance_stop_event.set()
            if self.maintenance_thread and self.maintenance_thread.is_alive():
                self.maintenance_thread.join(timeout=10)
            
            # Fermer toutes les connexions
            self.connection_pool.close_all()
            
            self.logger.info("DatabaseManager closed successfully")
            
        except Exception as e:
            self.logger.error(f"Error closing DatabaseManager: {e}")

    def __enter__(self):
        """Support du context manager"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Support du context manager"""
        self.close()


# =============================================================================
# CONTEXT MANAGER POUR LES TRANSACTIONS
# =============================================================================

class DatabaseTransaction:
    """Context manager pour les transactions de base de données"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.connection = None
        self.cursor = None
    
    def __enter__(self):
        self.connection = self.db_manager.connection_pool._create_connection()
        self.cursor = self.connection.cursor()
        self.connection.execute("BEGIN")
        return self.cursor
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                self.connection.execute("COMMIT")
            else:
                self.connection.execute("ROLLBACK")
        finally:
            if self.cursor:
                self.cursor.close()
            if self.connection:
                self.db_manager.connection_pool._close_connection(self.connection)


# =============================================================================
# UTILITAIRES ET HELPERS
# =============================================================================

class DatabaseMigration:
    """Gestionnaire de migrations de base de données"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.logger = logging.getLogger(__name__ + ".Migration")
    
    def get_current_version(self) -> int:
        """Récupère la version actuelle du schéma"""
        try:
            result = self.db_manager.execute_query(
                "SELECT value FROM system_config WHERE key = 'schema_version'",
                fetch_one=True
            )
            return int(result[0]) if result else 0
        except Exception:
            return 0
    
    def migrate_to_version(self, target_version: int):
        """Migre vers une version spécifique"""
        current_version = self.get_current_version()
        
        if current_version >= target_version:
            self.logger.info(f"Schema already at version {current_version}, no migration needed")
            return
        
        self.logger.info(f"Migrating schema from version {current_version} to {target_version}")
        
        with self.db_manager.transaction() as cursor:
            # Appliquer les migrations une par une
            for version in range(current_version + 1, target_version + 1):
                migration_method = getattr(self, f'_migrate_to_v{version}', None)
                if migration_method:
                    self.logger.info(f"Applying migration to version {version}")
                    migration_method(cursor)
                else:
                    self.logger.warning(f"No migration method found for version {version}")
            
            # Mettre à jour la version
            cursor.execute('''
                INSERT OR REPLACE INTO system_config (key, value, description)
                VALUES ('schema_version', ?, 'Database schema version')
            ''', (str(target_version),))
        
        self.logger.info(f"Migration completed to version {target_version}")
    
    def _migrate_to_v1(self, cursor: sqlite3.Cursor):
        """Migration vers la version 1 (exemple)"""
        # Ajouter des colonnes si nécessaire
        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN detection_delay REAL DEFAULT 0.0")
        except sqlite3.Error:
            pass  # La colonne existe déjà


class DatabaseMetrics:
    """Collecteur de métriques avancées pour la base de données"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.logger = logging.getLogger(__name__ + ".Metrics")
    
    def collect_performance_metrics(self) -> Dict[str, Any]:
        """Collecte les métriques de performance détaillées"""
        try:
            metrics = {
                'timestamp': get_current_timestamp(),
                'query_performance': {},
                'table_statistics': {},
                'index_usage': {},
                'cache_statistics': {}
            }
            
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Statistiques des requêtes (SQLite compile_options)
                try:
                    cursor.execute("PRAGMA compile_options")
                    compile_options = [row[0] for row in cursor.fetchall()]
                    metrics['sqlite_features'] = compile_options
                except Exception:
                    pass
                
                # Statistiques des tables
                tables = ['transactions', 'token_accounts', 'wallet_priorities']
                for table in tables:
                    try:
                        # Nombre de lignes
                        cursor.execute(f"SELECT COUNT(*) FROM {table}")
                        row_count = cursor.fetchone()[0]
                        
                        # Taille approximative
                        cursor.execute(f"PRAGMA table_info({table})")
                        columns = cursor.fetchall()
                        
                        metrics['table_statistics'][table] = {
                            'row_count': row_count,
                            'column_count': len(columns),
                            'estimated_size_mb': row_count * len(columns) * 8 / (1024 * 1024)  # Approximation
                        }
                        
                    except Exception as e:
                        metrics['table_statistics'][table] = {'error': str(e)}
                
                # Test de performance de requêtes communes
                test_queries = [
                    ("simple_select", "SELECT COUNT(*) FROM transactions"),
                    ("indexed_lookup", "SELECT * FROM transactions WHERE wallet_address = ? LIMIT 1", 
                     ('test_wallet',)),
                    ("join_query", """
                        SELECT COUNT(*) 
                        FROM transactions t 
                        JOIN token_accounts ta ON t.wallet_address = ta.wallet_address 
                        LIMIT 100
                    """)
                ]
                
                for test_name, query, *params in test_queries:
                    try:
                        start_time = time.time()
                        cursor.execute(query, params[0] if params else ())
                        cursor.fetchall()
                        duration = time.time() - start_time
                        
                        metrics['query_performance'][test_name] = {
                            'duration_ms': round(duration * 1000, 2),
                            'status': 'fast' if duration < 0.1 else 'slow' if duration > 1.0 else 'normal'
                        }
                        
                    except Exception as e:
                        metrics['query_performance'][test_name] = {'error': str(e)}
            
            return metrics
            
        except Exception as e:
            self.logger.error(f"Failed to collect performance metrics: {e}")
            return {'error': str(e)}


# =============================================================================
# FONCTIONS UTILITAIRES GLOBALES
# =============================================================================

def get_database_manager(config=None) -> DatabaseManager:
    """Fonction helper pour obtenir l'instance du DatabaseManager"""
    return DatabaseManager(config)


def create_database_backup(db_path: str, backup_path: str) -> bool:
    """Crée une sauvegarde d'une base de données SQLite"""
    try:
        source_conn = sqlite3.connect(db_path)
        backup_conn = sqlite3.connect(backup_path)
        source_conn.backup(backup_conn)
        backup_conn.close()
        source_conn.close()
        return True
    except Exception as e:
        logging.error(f"Backup creation failed: {e}")
        return False


def test_database_connection(db_path: str, timeout: float = 5.0) -> bool:
    """Test simple de connexion à une base de données"""
    try:
        conn = sqlite3.connect(db_path, timeout=timeout)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        conn.close()
        return result and result[0] == 1
    except Exception:
        return False


# =============================================================================
# EXPORT
# =============================================================================

__all__ = [
    'DatabaseManager',
    'DatabaseConfig', 
    'ConnectionPool',
    'DatabaseTransaction',
    'DatabaseMigration',
    'DatabaseMetrics',
    'get_database_manager',
    'create_database_backup',
    'test_database_connection'
]
    

    