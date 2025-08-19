#!/usr/bin/env python3
"""
Système de métriques pour le monitoring des tokens
Fournit des statistiques détaillées sur l'activité du système
Version intégrée avec le système de configuration et logging du projet
"""

import sqlite3
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass
import argparse
import sys
import os
from pathlib import Path

# Ajouter la racine du projet au path
project_root = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(project_root))

# Import du système de configuration et logging du projet
from core.config import get_config
from core.logger import get_logger, SolanaWalletLogger

# Variables globales
config = None
logger = None

@dataclass
class TimeWindowMetrics:
    """Métriques pour une fenêtre de temps donnée"""
    window: str
    new_tokens: int = 0
    new_transactions: int = 0
    token_updates: int = 0
    history_snapshots: int = 0
    dead_tokens_marked: int = 0
    rugcheck_updates: int = 0
    api_calls_estimated: int = 0
    unique_wallets: int = 0
    buy_transactions: int = 0
    sell_transactions: int = 0
    total_volume_usd: float = 0.0
    avg_detection_delay: float = 0.0

    # === CHAMPS POUR LA QUEUE (ÉTENDUS) ===
    queue_tokens_added: int = 0
    queue_tokens_pending: int = 0
    queue_tokens_processing: int = 0
    queue_tokens_completed: int = 0
    queue_tokens_failed: int = 0
    queue_tokens_retrying: int = 0
    queue_processing_rate: float = 0.0  # tokens processed per hour
    queue_success_rate: float = 0.0     # percentage
    queue_avg_processing_time: float = 0.0  # seconds
    
    # === NOUVEAUX COMPTEURS ===
    tokens_stale: int = 0  # tokens devenus obsolètes dans la période
    api_errors: int = 0  # erreurs API estimées
    buy_sell_ratio: float = 0.0  # ratio achats/ventes
    volume_buy_usd: float = 0.0  # volume d'achats
    volume_sell_usd: float = 0.0  # volume de ventes
    avg_market_cap: float = 0.0  # market cap moyen des nouveaux tokens
    tokens_with_high_activity: int = 0  # tokens avec >X transactions
    unique_active_tokens: int = 0  # tokens ayant eu au moins 1 transaction
    
    # Métriques de performance
    queue_throughput: float = 0.0  # items traités / temps
    queue_efficiency: float = 0.0  # (completed / (completed + failed)) * 100

@dataclass
class SystemHealth:
    """Santé globale du système"""
    total_tokens: int = 0
    tokens_with_complete_data: int = 0
    tokens_missing_price: int = 0
    tokens_missing_metadata: int = 0
    tokens_never_updated: int = 0
    tokens_stale: int = 0
    tokens_dead: int = 0
    tokens_flagged_no_data: int = 0
    tokens_rugged: int = 0
    
    # Nouvelles métriques
    tokens_recently_updated: int = 0  # updated_at > now-5min
    tokens_outdated: int = 0          # updated_at < now-5min (excluant no_data et UNK)
    tokens_unknown_symbol: int = 0    # symbol LIKE 'UNK%'
    tokens_no_data_available: int = 0 # no_data_available = 1
    data_completeness_rate: float = 0.0
    freshness_rate: float = 0.0

    # === MÉTRIQUES POUR LA QUEUE ===
    queue_total_items: int = 0
    queue_pending: int = 0
    queue_processing: int = 0
    queue_completed: int = 0
    queue_failed: int = 0
    queue_retrying: int = 0
    queue_abandoned: int = 0
    queue_overall_success_rate: float = 0.0
    queue_avg_processing_time_all: float = 0.0
    queue_oldest_pending_hours: float = 0.0
    queue_backlog_size: int = 0  # pending + retrying
    
    # === NOUVEAUX COMPTEURS SYSTÈME ===
    tokens_high_activity: int = 0  # tokens avec >10 transactions/24h
    tokens_zero_activity: int = 0  # tokens sans transactions
    avg_token_age_hours: float = 0.0  # âge moyen des tokens
    total_volume_24h: float = 0.0  # volume total 24h
    api_error_rate: float = 0.0  # taux d'erreur API estimé
    
    # Alertes système
    alerts: List[str] = None
    
    def __post_init__(self):
        if self.alerts is None:
            self.alerts = []

@dataclass
class AlertThresholds:
    """Seuils d'alerte configurables"""
    queue_backlog_critical: int = 1000
    queue_backlog_warning: int = 500
    success_rate_critical: float = 50.0
    success_rate_warning: float = 80.0
    processing_time_critical: float = 300.0  # 5 minutes
    processing_time_warning: float = 120.0   # 2 minutes
    api_error_rate_critical: float = 50.0
    api_error_rate_warning: float = 20.0
    stale_tokens_critical: int = 1000
    stale_tokens_warning: int = 500

def setup_metrics_logger(config):
    """Configure un logger spécialisé pour les métriques"""
    global logger
    
    # Configuration spécialisée pour ce script
    metrics_log_file = os.getenv('METRICS_LOG_FILE', 'token_metrics.log')
    metrics_log_level = os.getenv('METRICS_LOG_LEVEL', config.logging.level.value)
    metrics_log_max_size = int(os.getenv('METRICS_LOG_MAX_SIZE_MB', '30'))
    metrics_log_backup_count = int(os.getenv('METRICS_LOG_BACKUP_COUNT', '5'))
    
    # Créer le logger spécialisé avec fichier dédié
    metrics_logger = SolanaWalletLogger(
        log_level=metrics_log_level,
        log_file=str(Path(config.logging.base_dir) / metrics_log_file),
        console_output=config.logging.console_output,
        json_output=config.logging.json_output,
        max_file_size=metrics_log_max_size * 1024 * 1024,
        backup_count=metrics_log_backup_count,
        max_age_days=config.logging.max_age_days,
        force_reconfigure=True
    )
    
    logger = metrics_logger.get_logger('token_metrics')
    
    logger.info("🚀 Token Metrics System démarré")
    logger.info(f"📊 Base de données: {config.database.get_full_path()}")
    logger.info(f"📝 Log fichier: {Path(config.logging.base_dir) / metrics_log_file}")
    logger.info(f"📋 Niveau de log: {metrics_log_level}")
    
    return logger

class TokenMetricsCollector:
    """Collecteur de métriques pour le système de tokens"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.current_timestamp = int(time.time())
        self.logger = get_logger('token_metrics.collector')
        
        # Configuration des fenêtres de temps depuis les variables d'env ou par défaut
        self.time_windows = {
            '5m': int(os.getenv('METRICS_WINDOW_5M', '300')),      # 5 minutes
            '1h': int(os.getenv('METRICS_WINDOW_1H', '3600')),     # 1 heure
            '6h': int(os.getenv('METRICS_WINDOW_6H', '21600')),    # 6 heures
            '24h': int(os.getenv('METRICS_WINDOW_24H', '86400')),  # 24 heures
            '7d': int(os.getenv('METRICS_WINDOW_7D', '604800')),   # 7 jours
        }
        
        # Seuils d'alerte configurables
        self.alert_thresholds = AlertThresholds()
        
        self.logger.debug(f"🔧 Fenêtres de temps configurées: {self.time_windows}")
    
    def get_db_connection(self) -> sqlite3.Connection:
        """Obtenir une connexion à la base de données"""
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.row_factory = sqlite3.Row
            self.logger.debug(f"🔌 Connexion établie avec {self.db_path}")
            return conn
        except Exception as e:
            self.logger.error(f"❌ Erreur connexion DB: {e}")
            raise
    
    def get_time_window_metrics(self, window_seconds: int, window_name: str) -> TimeWindowMetrics:
        """Obtenir les métriques pour une fenêtre de temps"""
        cutoff_time = self.current_timestamp - window_seconds
        cutoff_datetime = datetime.fromtimestamp(cutoff_time).strftime('%Y-%m-%d %H:%M:%S')
        
        metrics = TimeWindowMetrics(window=window_name)
        self.logger.debug(f"🔍 Collecte des métriques pour la fenêtre {window_name} (depuis {cutoff_datetime})")
        
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 1. Nouveaux tokens créés
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens 
                    WHERE created_at > datetime('now', '-' || ? || ' seconds')
                """, (window_seconds,))
                metrics.new_tokens = cursor.fetchone()[0]
                
                # 2. Nouvelles transactions avec volumes détaillés
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_tx,
                        COUNT(CASE WHEN transaction_type = 'TransactionType.BUY' THEN 1 END) as buys,
                        COUNT(CASE WHEN transaction_type = 'TransactionType.SELL' THEN 1 END) as sells,
                        COALESCE(SUM(CASE WHEN transaction_type = 'TransactionType.BUY' THEN amount ELSE 0 END), 0) as buy_volume,
                        COALESCE(SUM(CASE WHEN transaction_type = 'TransactionType.SELL' THEN amount ELSE 0 END), 0) as sell_volume,
                        COUNT(DISTINCT token_mint) as unique_tokens,
                        COUNT(DISTINCT wallet_address) as unique_wallets,
                        COALESCE(AVG(detection_delay), 0) as avg_delay
                    FROM transactions 
                    WHERE created_at > datetime('now', '-' || ? || ' seconds')
                    OR datetime(created_at, 'unixepoch') > datetime('now', '-' || ? || ' seconds')
                """, (window_seconds, window_seconds))
                
                tx_data = cursor.fetchone()
                metrics.new_transactions = tx_data[0] or 0
                metrics.buy_transactions = tx_data[1] or 0
                metrics.sell_transactions = tx_data[2] or 0
                metrics.volume_buy_usd = tx_data[3] or 0.0
                metrics.volume_sell_usd = tx_data[4] or 0.0
                metrics.unique_active_tokens = tx_data[5] or 0
                metrics.unique_wallets = tx_data[6] or 0
                metrics.avg_detection_delay = tx_data[7] or 0.0
                
                # Calcul du ratio buy/sell
                if metrics.sell_transactions > 0:
                    metrics.buy_sell_ratio = metrics.buy_transactions / metrics.sell_transactions
                else:
                    metrics.buy_sell_ratio = float('inf') if metrics.buy_transactions > 0 else 0
                
                metrics.total_volume_usd = metrics.volume_buy_usd + metrics.volume_sell_usd
                
                # 3. Mises à jour de tokens
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens 
                    WHERE updated_at > datetime('now', '-' || ? || ' seconds')
                    AND (created_at != updated_at OR created_at <= datetime('now', '-' || ? || ' seconds'))
                """, (window_seconds, window_seconds))
                metrics.token_updates = cursor.fetchone()[0]
                
                # 4. Snapshots d'historique créés
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens_history 
                    WHERE created_at > datetime('now', '-' || ? || ' seconds')
                """, (window_seconds,))
                metrics.history_snapshots = cursor.fetchone()[0]
                
                # 5. Tokens marqués comme morts
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens 
                    WHERE death_timestamp > ? AND is_dead = 1
                """, (cutoff_time,))
                metrics.dead_tokens_marked = cursor.fetchone()[0]
                
                # 6. Tokens devenus obsolètes (stale) dans la période
                stale_cutoff = cutoff_time - 86400  # tokens qui étaient à jour et sont maintenant stale
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens 
                    WHERE last_price_update BETWEEN ? AND ?
                    AND last_price_update < datetime('now', '-24 hours', 'unixepoch')
                    AND is_dead = 0 AND is_rugged = 0
                """, (stale_cutoff, cutoff_time))
                metrics.tokens_stale = cursor.fetchone()[0]
                
                # 7. Mises à jour Rugcheck
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens 
                    WHERE last_rugcheck_update > ?
                """, (cutoff_time,))
                metrics.rugcheck_updates = cursor.fetchone()[0]
                
                # 8. Market cap moyen des nouveaux tokens
                cursor.execute("""
                    SELECT AVG(market_cap) FROM tokens 
                    WHERE created_at > datetime('now', '-' || ? || ' seconds')
                    AND market_cap > 0
                """, (window_seconds,))
                avg_mc_result = cursor.fetchone()
                metrics.avg_market_cap = avg_mc_result[0] if avg_mc_result[0] else 0.0
                
                # 9. Tokens avec haute activité (>5 transactions dans la période)
                cursor.execute("""
                    SELECT COUNT(DISTINCT t.token_mint) 
                    FROM transactions t
                    WHERE (t.created_at > datetime('now', '-' || ? || ' seconds')
                        OR datetime(t.created_at, 'unixepoch') > datetime('now', '-' || ? || ' seconds'))
                    GROUP BY t.token_mint
                    HAVING COUNT(*) > 5
                """, (window_seconds, window_seconds))
                metrics.tokens_with_high_activity = len(cursor.fetchall())
                
                # 10. Estimation des erreurs API (basée sur les échecs)
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_attempts,
                        COUNT(CASE WHEN failed_attempts > 0 THEN 1 END) as failed_tokens
                    FROM tokens
                    WHERE updated_at > datetime('now', '-' || ? || ' seconds')
                """, (window_seconds,))
                api_data = cursor.fetchone()
                total_attempts = api_data[0] or 0
                failed_tokens = api_data[1] or 0
                metrics.api_errors = failed_tokens
                
                # Estimation des appels API totaux
                metrics.api_calls_estimated = (metrics.token_updates * 3) + (metrics.new_tokens * 4)
                
                # === MÉTRIQUES DE LA QUEUE (ÉTENDUES) ===
                
                # Tokens ajoutés à la queue
                cursor.execute("""
                    SELECT COUNT(*) FROM token_processing_queue 
                    WHERE created_at > datetime('now', '-' || ? || ' seconds')
                """, (window_seconds,))
                metrics.queue_tokens_added = cursor.fetchone()[0]
                
                # Tokens en pending (nouveaux dans la période)
                cursor.execute("""
                    SELECT COUNT(*) FROM token_processing_queue 
                    WHERE status = 'pending' 
                    AND created_at > datetime('now', '-' || ? || ' seconds')
                """, (window_seconds,))
                metrics.queue_tokens_pending = cursor.fetchone()[0]
                
                # Tokens traités dans la période
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_processed,
                        COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed,
                        COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed,
                        COUNT(CASE WHEN status = 'retrying' THEN 1 END) as retrying
                    FROM token_processing_queue 
                    WHERE completed_at > datetime('now', '-' || ? || ' seconds')
                    OR (status = 'retrying' AND last_retry_at > datetime('now', '-' || ? || ' seconds'))
                """, (window_seconds, window_seconds))
                
                queue_data = cursor.fetchone()
                total_processed = queue_data[0] or 0
                metrics.queue_tokens_completed = queue_data[1] or 0
                metrics.queue_tokens_failed = queue_data[2] or 0
                metrics.queue_tokens_retrying = queue_data[3] or 0
                
                # Tokens en processing (démarrés dans la période)
                cursor.execute("""
                    SELECT COUNT(*) FROM token_processing_queue 
                    WHERE processing_started_at > datetime('now', '-' || ? || ' seconds')
                    AND status = 'processing'
                """, (window_seconds,))
                metrics.queue_tokens_processing = cursor.fetchone()[0]
                
                # Calculs de performance de la queue
                if window_seconds > 0:
                    hours = window_seconds / 3600
                    metrics.queue_processing_rate = total_processed / hours if hours > 0 else 0
                    metrics.queue_throughput = total_processed / (window_seconds / 60)  # par minute
                
                if total_processed > 0:
                    metrics.queue_success_rate = (metrics.queue_tokens_completed / total_processed) * 100
                    metrics.queue_efficiency = metrics.queue_success_rate
                
                # Temps de traitement moyen
                cursor.execute("""
                    SELECT AVG(
                        CASE 
                            WHEN processing_started_at IS NOT NULL AND completed_at IS NOT NULL
                            THEN (julianday(completed_at) - julianday(processing_started_at)) * 86400
                            ELSE NULL 
                        END
                    ) as avg_processing_time
                    FROM token_processing_queue
                    WHERE completed_at > datetime('now', '-' || ? || ' seconds')
                    AND status = 'completed'
                """, (window_seconds,))

                avg_time_result = cursor.fetchone()
                metrics.queue_avg_processing_time = avg_time_result[0] if avg_time_result[0] else 0.0
                
                self.logger.debug(f"✅ Métriques collectées pour {window_name}: {metrics.new_tokens} nouveaux tokens, {metrics.new_transactions} transactions")
                
        except Exception as e:
            self.logger.error(f"❌ Erreur lors de la collecte des métriques pour {window_name}: {e}")
        
        return metrics
    
    def get_system_health(self) -> SystemHealth:
        """Obtenir la santé globale du système avec alertes"""
        health = SystemHealth()
        self.logger.debug("🔍 Collecte des métriques de santé système")
        
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # === MÉTRIQUES EXISTANTES ===
                # Total des tokens
                cursor.execute("SELECT COUNT(*) FROM tokens")
                health.total_tokens = cursor.fetchone()[0]
                
                # Tokens avec données complètes
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens 
                    WHERE symbol IS NOT NULL 
                    AND name IS NOT NULL 
                    AND price_usd > 0 
                    AND market_cap > 0
                    AND is_dead = 0
                """)
                health.tokens_with_complete_data = cursor.fetchone()[0]
                
                # Tokens sans prix
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens 
                    WHERE (price_usd IS NULL OR price_usd = 0) 
                    AND is_dead = 0
                """)
                health.tokens_missing_price = cursor.fetchone()[0]
                
                # Tokens sans métadonnées
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens 
                    WHERE (symbol IS NULL OR name IS NULL) 
                    AND is_dead = 0
                """)
                health.tokens_missing_metadata = cursor.fetchone()[0]
                
                # Tokens jamais mis à jour
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens 
                    WHERE last_price_update IS NULL 
                    AND is_dead = 0
                """)
                health.tokens_never_updated = cursor.fetchone()[0]
                
                # Tokens avec données obsolètes (>24h)
                stale_cutoff = self.current_timestamp - 86400
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens 
                    WHERE last_price_update < ? 
                    AND (is_dead = 0)
                    AND (is_rugged = 0)
                """, (stale_cutoff,))
                health.tokens_stale = cursor.fetchone()[0]
                
                # Tokens morts
                cursor.execute("SELECT COUNT(*) FROM tokens WHERE is_dead = 1")
                health.tokens_dead = cursor.fetchone()[0]
                
                # Tokens flaggés sans données
                cursor.execute("SELECT COUNT(*) FROM tokens WHERE no_data_available = 1")
                health.tokens_flagged_no_data = cursor.fetchone()[0]
                
                # Tokens récemment mis à jour (updated_at > now - 5 minutes)
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens 
                    WHERE updated_at > datetime('now', '-5 minutes')
                    AND no_data_available != 1 
                    AND (symbol NOT LIKE 'UNK%' OR symbol IS NULL)
                    AND (is_rugged = 0)
                """)
                health.tokens_recently_updated = cursor.fetchone()[0]
                
                # Tokens obsolètes (updated_at < now - 5 minutes)
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens 
                    WHERE updated_at < datetime('now', '-5 minutes')
                    AND no_data_available != 1 
                    AND (symbol NOT LIKE 'UNK%' OR symbol IS NULL)
                    AND (is_rugged = 0)
                """)
                health.tokens_outdated = cursor.fetchone()[0]
                
                # Tokens avec symbole inconnu (UNK%)
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens 
                    WHERE symbol LIKE 'UNK%'
                """)
                health.tokens_unknown_symbol = cursor.fetchone()[0]
                
                # Tokens sans données disponibles
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens 
                    WHERE no_data_available = 1
                """)
                health.tokens_no_data_available = cursor.fetchone()[0]
                
                # Tokens ruggés
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens 
                    WHERE is_rugged = 1
                """)
                health.tokens_rugged = cursor.fetchone()[0]

                # === NOUVELLES MÉTRIQUES SYSTÈME ===
                
                # Tokens avec haute activité (>10 transactions/24h)
                cursor.execute("""
                    SELECT COUNT(DISTINCT t.token_mint)
                    FROM transactions t
                    WHERE (t.created_at > datetime('now', '-24 hours')
                        OR datetime(t.created_at, 'unixepoch') > datetime('now', '-24 hours'))
                    GROUP BY t.token_mint
                    HAVING COUNT(*) > 10
                """)
                health.tokens_high_activity = len(cursor.fetchall())
                
                # Tokens sans activité (aucune transaction)
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens t
                    WHERE NOT EXISTS (
                        SELECT 1 FROM transactions tx 
                        WHERE tx.token_mint = t.address
                    )
                    AND t.is_dead = 0
                """)
                health.tokens_zero_activity = cursor.fetchone()[0]
                
                # Âge moyen des tokens en heures
                cursor.execute("""
                    SELECT AVG(
                        (julianday('now') - julianday(created_at)) * 24
                    ) as avg_age_hours
                    FROM tokens
                    WHERE is_dead = 0
                """)
                age_result = cursor.fetchone()
                health.avg_token_age_hours = age_result[0] if age_result[0] else 0.0
                
                # Volume total 24h
                cursor.execute("""
                    SELECT COALESCE(SUM(amount), 0) as total_volume
                    FROM transactions
                    WHERE created_at > datetime('now', '-24 hours')
                    OR datetime(created_at, 'unixepoch') > datetime('now', '-24 hours')
                """)
                volume_result = cursor.fetchone()
                health.total_volume_24h = volume_result[0] if volume_result[0] else 0.0
                
                # Taux d'erreur API estimé
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_tokens,
                        COUNT(CASE WHEN failed_attempts > 0 THEN 1 END) as failed_tokens
                    FROM tokens
                    WHERE updated_at > datetime('now', '-24 hours')
                """)
                api_stats = cursor.fetchone()
                if api_stats[0] and api_stats[0] > 0:
                    health.api_error_rate = (api_stats[1] / api_stats[0]) * 100
                
                # === MÉTRIQUES DE LA QUEUE ===
                
                # Statistiques globales de la queue
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total,
                        COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending,
                        COUNT(CASE WHEN status = 'processing' THEN 1 END) as processing,
                        COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed,
                        COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed,
                        COUNT(CASE WHEN status = 'retrying' THEN 1 END) as retrying,
                        COUNT(CASE WHEN status = 'abandoned' THEN 1 END) as abandoned
                    FROM token_processing_queue
                """)
                
                queue_data = cursor.fetchone()
                health.queue_total_items = queue_data[0] or 0
                health.queue_pending = queue_data[1] or 0
                health.queue_processing = queue_data[2] or 0
                health.queue_completed = queue_data[3] or 0
                health.queue_failed = queue_data[4] or 0
                health.queue_retrying = queue_data[5] or 0
                health.queue_abandoned = queue_data[6] or 0
                
                # Taux de succès global
                total_processed = health.queue_completed + health.queue_failed
                if total_processed > 0:
                    health.queue_overall_success_rate = (health.queue_completed / total_processed) * 100
                
                # Temps de traitement moyen global
                cursor.execute("""
                    SELECT AVG(
                        CASE 
                            WHEN processing_started_at IS NOT NULL AND completed_at IS NOT NULL
                            THEN (julianday(completed_at) - julianday(processing_started_at)) * 86400
                            ELSE NULL 
                        END
                    ) as avg_processing_time
                    FROM token_processing_queue
                    WHERE status = 'completed'
                """)
                
                avg_time_result = cursor.fetchone()
                health.queue_avg_processing_time_all = avg_time_result[0] if avg_time_result[0] else 0.0
                
                # Âge du plus ancien token en attente
                cursor.execute("""
                    SELECT MIN(created_at) FROM token_processing_queue
                    WHERE status = 'pending'
                """)
                
                oldest_pending = cursor.fetchone()[0]
                if oldest_pending:
                    try:
                        oldest_time = datetime.fromisoformat(oldest_pending.replace('Z', '+00:00'))
                        age = datetime.now() - oldest_time
                        health.queue_oldest_pending_hours = age.total_seconds() / 3600
                    except Exception:
                        health.queue_oldest_pending_hours = 0.0
                
                # Taille du backlog
                health.queue_backlog_size = health.queue_pending + health.queue_retrying

                # === CALCUL DES TAUX ===
                if health.total_tokens > 0:
                    health.data_completeness_rate = (health.tokens_with_complete_data / health.total_tokens) * 100
                    
                    fresh_tokens = health.total_tokens - health.tokens_stale - health.tokens_never_updated - health.tokens_dead
                    health.freshness_rate = max(0, (fresh_tokens / health.total_tokens) * 100)
                
                # === GÉNÉRATION D'ALERTES ===
                health.alerts = self._generate_alerts(health)
                
                self.logger.debug(f"✅ Santé système collectée: {health.total_tokens} tokens total, {health.data_completeness_rate:.1f}% complétude")
                
        except Exception as e:
            self.logger.error(f"❌ Erreur lors de la collecte de la santé système: {e}")
        
        return health
    
    def _generate_alerts(self, health: SystemHealth) -> List[str]:
        """Générer des alertes basées sur les seuils"""
        alerts = []
        
        # Alertes sur le backlog de la queue
        if health.queue_backlog_size >= self.alert_thresholds.queue_backlog_critical:
            alerts.append(f"🚨 CRITIQUE: Backlog queue très élevé ({health.queue_backlog_size} items)")
        elif health.queue_backlog_size >= self.alert_thresholds.queue_backlog_warning:
            alerts.append(f"⚠️ ATTENTION: Backlog queue élevé ({health.queue_backlog_size} items)")
        
        # Alertes sur le taux de succès
        if health.queue_overall_success_rate <= self.alert_thresholds.success_rate_critical:
            alerts.append(f"🚨 CRITIQUE: Taux de succès très bas ({health.queue_overall_success_rate:.1f}%)")
        elif health.queue_overall_success_rate <= self.alert_thresholds.success_rate_warning:
            alerts.append(f"⚠️ ATTENTION: Taux de succès bas ({health.queue_overall_success_rate:.1f}%)")
        
        # Alertes sur le temps de traitement
        if health.queue_avg_processing_time_all >= self.alert_thresholds.processing_time_critical:
            alerts.append(f"🚨 CRITIQUE: Temps de traitement très élevé ({health.queue_avg_processing_time_all:.1f}s)")
        elif health.queue_avg_processing_time_all >= self.alert_thresholds.processing_time_warning:
            alerts.append(f"⚠️ ATTENTION: Temps de traitement élevé ({health.queue_avg_processing_time_all:.1f}s)")
        
        # Alertes sur les erreurs API
        if health.api_error_rate >= self.alert_thresholds.api_error_rate_critical:
            alerts.append(f"🚨 CRITIQUE: Taux d'erreur API très élevé ({health.api_error_rate:.1f}%)")
        elif health.api_error_rate >= self.alert_thresholds.api_error_rate_warning:
            alerts.append(f"⚠️ ATTENTION: Taux d'erreur API élevé ({health.api_error_rate:.1f}%)")
        
        # Alertes sur les tokens obsolètes
        if health.tokens_stale >= self.alert_thresholds.stale_tokens_critical:
            alerts.append(f"🚨 CRITIQUE: Trop de tokens obsolètes ({health.tokens_stale})")
        elif health.tokens_stale >= self.alert_thresholds.stale_tokens_warning:
            alerts.append(f"⚠️ ATTENTION: Beaucoup de tokens obsolètes ({health.tokens_stale})")
        
        # Alerte si plus ancien pending > 24h
        if health.queue_oldest_pending_hours > 24:
            alerts.append(f"🚨 CRITIQUE: Token en attente depuis {health.queue_oldest_pending_hours:.1f}h")
        elif health.queue_oldest_pending_hours > 12:
            alerts.append(f"⚠️ ATTENTION: Token en attente depuis {health.queue_oldest_pending_hours:.1f}h")
        
        return alerts

    def run_continuous_with_history(self, refresh_interval: int = 30, quick_mode: bool = False, 
                               alert_threshold: int = 0, save_history: bool = False):
        """Monitoring continu avec historique (sans clear screen)"""
        self.logger.info(f"🔄 Monitoring continu avec historique démarré (intervalle: {refresh_interval}s)")
        
        history_file = None
        if save_history:
            history_file = f"metrics_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            history_path = Path(config.logging.base_dir) / history_file
            self.logger.info(f"📝 Historique sauvegardé dans: {history_path}")
            print(f"📝 Historique sauvegardé dans: {history_path}")
        
        try:
            iteration = 0
            while True:
                iteration += 1
                current_time = datetime.now().strftime('%H:%M:%S')
                
                print(f"\n{'='*20} ITÉRATION {iteration} - {current_time} {'='*20}")
                
                if quick_mode:
                    # Afficher seulement les métriques clés
                    metrics_output = self.get_quick_metrics()
                    print(metrics_output)
                    self.logger.info(f"Métriques rapides - itération {iteration}")
                    
                    # Sauvegarder l'historique si demandé
                    if save_history and history_file:
                        with open(Path(config.logging.base_dir) / history_file, 'a', encoding='utf-8') as f:
                            f.write(f"{datetime.now().isoformat()} - {metrics_output}\n")
                else:
                    # Afficher métriques complètes mais condensées
                    time_metrics = self.get_time_window_metrics(300, '5m')  # 5 minutes
                    system_health = self.get_system_health()
                    
                    print(f"🆕 Nouveaux tokens (5m): {time_metrics.new_tokens}")
                    print(f"📈 Nouvelles transactions (5m): {time_metrics.new_transactions}")
                    print(f"🔄 Updates tokens (5m): {time_metrics.token_updates}")
                    print(f"📊 Snapshots créés (5m): {time_metrics.history_snapshots}")
                    print(f"👥 Wallets actifs (5m): {time_metrics.unique_wallets}")
                    print(f"💰 Volume (5m): ${time_metrics.total_volume_usd:,.0f} (B/S: {time_metrics.buy_sell_ratio:.2f})")
                    print(f"🏥 Santé système: {system_health.data_completeness_rate:.1f}% complétude | {system_health.freshness_rate:.1f}% fraîcheur")
                    print(f"🔄 Récemment mis à jour (5m): {system_health.tokens_recently_updated}")
                    print(f"⏰ Obsolètes (>5m): {system_health.tokens_outdated}")
                    print(f"📋 Queue: ✅{time_metrics.queue_tokens_completed} ❌{time_metrics.queue_tokens_failed} ⏳{system_health.queue_backlog_size}")
                    
                    # Afficher les alertes
                    if system_health.alerts:
                        print("🚨 ALERTES:")
                        for alert in system_health.alerts:
                            print(f"   {alert}")
                    
                    self.logger.info(f"Métriques complètes - itération {iteration}: {time_metrics.new_tokens} tokens, {time_metrics.new_transactions} tx")
                    
                    if save_history and history_file:
                        with open(Path(config.logging.base_dir) / history_file, 'a', encoding='utf-8') as f:
                            f.write(f"{datetime.now().isoformat()} - Tokens: {time_metrics.new_tokens}, TX: {time_metrics.new_transactions}, Updates: {time_metrics.token_updates}, Alerts: {len(system_health.alerts)}\n")
                
                # Alertes si configurées
                if alert_threshold > 0:
                    metrics_5m = self.get_time_window_metrics(300, '5m')
                    if metrics_5m.new_tokens >= alert_threshold:
                        alert_msg = f"🚨 ALERTE: {metrics_5m.new_tokens} nouveaux tokens détectés!"
                        print(alert_msg)
                        self.logger.warning(alert_msg)
                        if save_history and history_file:
                            with open(Path(config.logging.base_dir) / history_file, 'a', encoding='utf-8') as f:
                                f.write(f"{datetime.now().isoformat()} - {alert_msg}\n")
                
                time.sleep(refresh_interval)
                
        except KeyboardInterrupt:
            self.logger.info("⌨️ Monitoring arrêté par l'utilisateur")
            print("\n👋 Monitoring arrêté")
        except Exception as e:
            self.logger.error(f"❌ Erreur pendant le monitoring: {e}")
            print(f"\n❌ Erreur pendant le monitoring: {e}")

    def run_continuous_monitoring(self, refresh_interval: int = 30, quick_mode: bool = False, alert_threshold: int = 0):
        """Monitoring en continu avec affichage mis à jour"""
        self.logger.info(f"🔄 Monitoring continu démarré (intervalle: {refresh_interval}s, mode: {'rapide' if quick_mode else 'complet'})")
        print("🔄 Monitoring continu démarré (Ctrl+C pour arrêter)")
        print(f"⏱️  Intervalle de rafraîchissement: {refresh_interval}s")
        
        try:
            while True:
                # Clear screen (compatible Windows/Linux/Mac)
                import os
                os.system('cls' if os.name == 'nt' else 'clear')
                
                # Afficher timestamp actuel
                current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                print(f"🕐 Dernière mise à jour: {current_time}")
                print()
                
                # Générer et afficher le rapport (mode rapide ou complet)
                if quick_mode:
                    report = self.get_quick_metrics()
                    print(report)
                    self.logger.debug("Affichage métriques rapides")
                    
                    # Alertes si configurées
                    if alert_threshold > 0:
                        metrics_5m = self.get_time_window_metrics(300, '5m')
                        if metrics_5m.new_tokens >= alert_threshold:
                            alert_msg = f"\n🚨 ALERTE: {metrics_5m.new_tokens} nouveaux tokens détectés (seuil: {alert_threshold})"
                            print(alert_msg)
                            self.logger.warning(f"ALERTE: {metrics_5m.new_tokens} nouveaux tokens détectés")
                else:
                    report = self.generate_report('text')
                    print(report)
                    self.logger.debug("Affichage rapport complet")
                    
                    # Alertes si configurées
                    if alert_threshold > 0:
                        metrics_5m = self.get_time_window_metrics(300, '5m')
                        if metrics_5m.new_tokens >= alert_threshold:
                            alert_msg = f"\n🚨 ALERTE: {metrics_5m.new_tokens} nouveaux tokens détectés!"
                            print(alert_msg)
                            self.logger.warning(f"ALERTE: {metrics_5m.new_tokens} nouveaux tokens détectés")
                
                print(f"\n⏭️  Prochaine mise à jour dans {refresh_interval}s...")
                
                # Attendre avant la prochaine itération
                time.sleep(refresh_interval)
                
        except KeyboardInterrupt:
            self.logger.info("⌨️ Monitoring arrêté par l'utilisateur")
            print("\n\n👋 Monitoring arrêté par l'utilisateur")
        except Exception as e:
            self.logger.error(f"❌ Erreur pendant le monitoring: {e}")
            print(f"\n❌ Erreur pendant le monitoring: {e}")

    def get_top_active_tokens(self, limit: int = 10) -> List[Dict]:
        """Obtenir les tokens les plus actifs récemment"""
        self.logger.debug(f"🔍 Recherche des {limit} tokens les plus actifs")
        
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                cutoff_time = self.current_timestamp - 86400  # 24h
                
                cursor.execute("""
                    SELECT 
                        t.token_mint,
                        tk.symbol,
                        tk.name,
                        tk.market_cap,
                        tk.price_usd,
                        COUNT(*) as transaction_count,
                        COUNT(DISTINCT t.wallet_address) as unique_wallets,
                        SUM(CASE WHEN t.transaction_type = 'TransactionType.BUY' THEN t.amount ELSE 0 END) as buy_volume,
                        SUM(CASE WHEN t.transaction_type = 'TransactionType.SELL' THEN t.amount ELSE 0 END) as sell_volume,
                        MAX(t.created_at) as last_activity,
                        COUNT(CASE WHEN t.transaction_type = 'TransactionType.BUY' THEN 1 END) as buy_count,
                        COUNT(CASE WHEN t.transaction_type = 'TransactionType.SELL' THEN 1 END) as sell_count
                    FROM transactions t
                    LEFT JOIN tokens tk ON t.token_mint = tk.address
                    WHERE (t.created_at > datetime(?, 'unixepoch')
                        OR datetime(t.created_at, 'unixepoch') > datetime(?, 'unixepoch'))
                    AND t.token_mint IS NOT NULL
                    GROUP BY t.token_mint
                    ORDER BY transaction_count DESC, unique_wallets DESC
                    LIMIT ?
                """, (cutoff_time, cutoff_time, limit))
                
                results = []
                for row in cursor.fetchall():
                    buy_volume = row[7] or 0
                    sell_volume = row[8] or 0
                    buy_count = row[10] or 0
                    sell_count = row[11] or 0
                    
                    results.append({
                        'token_address': row[0],
                        'symbol': row[1] or 'Unknown',
                        'name': row[2] or 'Unknown Token',
                        'market_cap': row[3] or 0,
                        'price_usd': row[4] or 0,
                        'transaction_count': row[5],
                        'unique_wallets': row[6],
                        'buy_volume': buy_volume,
                        'sell_volume': sell_volume,
                        'total_volume': buy_volume + sell_volume,
                        'last_activity': row[9],
                        'buy_count': buy_count,
                        'sell_count': sell_count,
                        'buy_sell_ratio': buy_count / sell_count if sell_count > 0 else float('inf'),
                        'volume_ratio': buy_volume / sell_volume if sell_volume > 0 else float('inf')
                    })
                
                self.logger.debug(f"✅ {len(results)} tokens actifs trouvés")
                return results
                
        except Exception as e:
            self.logger.error(f"❌ Erreur lors de la récupération des tokens actifs: {e}")
            return []
    
    def get_performance_metrics(self) -> Dict:
        """Obtenir les métriques de performance du système"""
        self.logger.debug("🔍 Collecte des métriques de performance")
        
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Délai moyen de détection
                cursor.execute("""
                    SELECT AVG(detection_delay) as avg_delay,
                        MIN(detection_delay) as min_delay,
                        MAX(detection_delay) as max_delay,
                        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY detection_delay) as median_delay,
                        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY detection_delay) as p95_delay
                    FROM transactions 
                    WHERE created_at > datetime('now', '-24 hours')
                    OR datetime(created_at, 'unixepoch') > datetime('now', '-24 hours')
                    AND detection_delay IS NOT NULL
                """)
                delay_stats = cursor.fetchone()
                
                # Taux de succès des API calls (approximatif)
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_tokens,
                        COUNT(CASE WHEN failed_attempts = 0 THEN 1 END) as successful_tokens,
                        COUNT(CASE WHEN no_data_available = 1 THEN 1 END) as failed_tokens,
                        AVG(failed_attempts) as avg_failures_per_token
                    FROM tokens
                    WHERE created_at > datetime('now', '-24 hours')
                """)
                api_stats = cursor.fetchone()
                
                # Historisation stats
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_snapshots,
                        COUNT(DISTINCT token_address) as unique_tokens_historized,
                        AVG(viability_score) as avg_viability,
                        AVG(risk_score) as avg_risk,
                        MIN(viability_score) as min_viability,
                        MAX(viability_score) as max_viability
                    FROM tokens_history
                    WHERE snapshot_timestamp > ?
                """, (self.current_timestamp - 86400,))
                history_stats = cursor.fetchone()
                
                # Statistiques de volume et prix
                cursor.execute("""
                    SELECT 
                        AVG(price_usd) as avg_price,
                        MIN(price_usd) as min_price,
                        MAX(price_usd) as max_price,
                        AVG(market_cap) as avg_market_cap,
                        COUNT(CASE WHEN market_cap > 1000000 THEN 1 END) as tokens_over_1m_mc
                    FROM tokens
                    WHERE price_usd > 0 AND created_at > datetime('now', '-24 hours')
                """)
                price_stats = cursor.fetchone()
                
                perf_data = {
                    'detection_delay': {
                        'avg_seconds': delay_stats[0] or 0,
                        'min_seconds': delay_stats[1] or 0,
                        'max_seconds': delay_stats[2] or 0,
                        'median_seconds': delay_stats[3] or 0,
                        'p95_seconds': delay_stats[4] or 0
                    },
                    'api_success_rate': {
                        'total_tokens': api_stats[0] or 0,
                        'successful': api_stats[1] or 0,
                        'failed': api_stats[2] or 0,
                        'success_rate_pct': ((api_stats[1] or 0) / max(api_stats[0], 1)) * 100,
                        'avg_failures_per_token': api_stats[3] or 0
                    },
                    'historization': {
                        'total_snapshots': history_stats[0] or 0,
                        'unique_tokens': history_stats[1] or 0,
                        'avg_viability_score': history_stats[2] or 0,
                        'avg_risk_score': history_stats[3] or 0,
                        'min_viability': history_stats[4] or 0,
                        'max_viability': history_stats[5] or 0
                    },
                    'market_data': {
                        'avg_price_usd': price_stats[0] or 0,
                        'min_price_usd': price_stats[1] or 0,
                        'max_price_usd': price_stats[2] or 0,
                        'avg_market_cap': price_stats[3] or 0,
                        'tokens_over_1m_mc': price_stats[4] or 0
                    }
                }
                
                self.logger.debug("✅ Métriques de performance collectées")
                return perf_data
                
        except Exception as e:
            self.logger.error(f"❌ Erreur lors de la collecte des métriques de performance: {e}")
            return {}
    
    def get_quick_metrics(self) -> str:
        """Métriques rapides pour affichage continu"""
        try:
            metrics_5m = self.get_time_window_metrics(300, '5m')
            health = self.get_system_health()
            
            # Formater le ratio buy/sell
            bs_ratio = "∞" if metrics_5m.buy_sell_ratio == float('inf') else f"{metrics_5m.buy_sell_ratio:.2f}"
            
            result = f"""
🔄 LIVE METRICS
├─ 🆕 Nouveaux tokens (5m): {metrics_5m.new_tokens}
├─ 📈 Transactions (5m): {metrics_5m.new_transactions} (👥 {metrics_5m.unique_wallets} wallets)
├─ 💰 Volume (5m): ${metrics_5m.total_volume_usd:,.0f} | B/S ratio: {bs_ratio}
├─ 🔄 Updates (5m): {metrics_5m.token_updates}
├─ 📊 Snapshots (5m): {metrics_5m.history_snapshots}
├─ 🏥 Santé: {health.data_completeness_rate:.1f}% complétude | {health.freshness_rate:.1f}% fraîcheur
├─ ✅ Récemment mis à jour (<5m): {health.tokens_recently_updated}
├─ ⏰ Obsolètes (>5m): {health.tokens_outdated}
├─ ❓ Symboles inconnus (UNK%): {health.tokens_unknown_symbol}
├─ 🚫 Sans données disponibles: {health.tokens_no_data_available}
├─ 🚨 Tokens ruggés: {health.tokens_rugged}
├─ 🔥 Haute activité (24h): {health.tokens_high_activity}
├─ 💤 Sans activité: {health.tokens_zero_activity}
├─ 📋 QUEUE (5m): +{metrics_5m.queue_tokens_added} ⏳{metrics_5m.queue_tokens_pending} ✅{metrics_5m.queue_tokens_completed} ❌{metrics_5m.queue_tokens_failed} 🔄{metrics_5m.queue_tokens_retrying}
├─ 📋 Queue backlog: {health.queue_backlog_size} | Success: {health.queue_overall_success_rate:.1f}%
├─ ⏱️ Queue processing: {metrics_5m.queue_avg_processing_time:.1f}s avg | {metrics_5m.queue_processing_rate:.1f}/h
├─ 🎯 API errors (5m): {metrics_5m.api_errors} | Error rate: {health.api_error_rate:.1f}%
└─ ⚡ Throughput: {metrics_5m.queue_throughput:.1f}/min | Efficiency: {metrics_5m.queue_efficiency:.1f}%"""
            
            # Ajouter les alertes si présentes
            if health.alerts:
                result += "\n\n🚨 ALERTES ACTIVES:"
                for alert in health.alerts:
                    result += f"\n├─ {alert}"
            
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Erreur métriques rapides: {e}")
            return f"❌ Erreur métriques: {e}"

    def generate_report(self, format_type: str = 'text') -> str:
        """Générer un rapport complet"""
        self.logger.info(f"📊 Génération du rapport (format: {format_type})")
        
        # Collecter toutes les métriques
        time_metrics = {}
        for window_name, window_seconds in self.time_windows.items():
            time_metrics[window_name] = self.get_time_window_metrics(window_seconds, window_name)
        
        system_health = self.get_system_health()
        top_tokens = self.get_top_active_tokens(10)
        performance = self.get_performance_metrics()
        
        if format_type == 'json':
            report = self._generate_json_report(time_metrics, system_health, top_tokens, performance)
        else:
            report = self._generate_text_report(time_metrics, system_health, top_tokens, performance)
        
        self.logger.info("✅ Rapport généré avec succès")
        return report
    
    def _generate_text_report(self, time_metrics: Dict, system_health: SystemHealth, 
                         top_tokens: List[Dict], performance: Dict) -> str:
        """Générer un rapport texte formaté"""
        report = []
        report.append("=" * 100)
        report.append("🎯 RAPPORT DE MÉTRIQUES DU SYSTÈME DE TOKENS")
        report.append("=" * 100)
        report.append(f"📅 Généré le: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"💾 Base de données: {self.db_path}")
        report.append("")
        
        # === ALERTES EN HAUT DU RAPPORT ===
        if system_health.alerts:
            report.append("🚨 ALERTES SYSTÈME")
            report.append("-" * 30)
            for alert in system_health.alerts:
                report.append(f"   {alert}")
            report.append("")
        
        # === TABLEAU PRINCIPAL ÉTENDU ===
        report.append("📊 ACTIVITÉ PAR PÉRIODE (TABLEAU ÉTENDU)")
        report.append("-" * 100)
        
        # Headers étendus
        headers = ["Période", "Tokens", "TX", "Updates", "Snapshots", "+Queue", "⏳Pend", "🔄Proc", "✅Comp", "❌Fail", "🔄Retry", "Success%", "AvgTime", "Volume$"]
        row_format = "{:<8} {:<7} {:<7} {:<8} {:<10} {:<7} {:<7} {:<7} {:<7} {:<7} {:<7} {:<8} {:<8} {:<10}"
        report.append(row_format.format(*headers))
        report.append("-" * 120)
        
        for window_name, metrics in time_metrics.items():
            success_rate = f"{metrics.queue_success_rate:.1f}%" if metrics.queue_success_rate > 0 else "N/A"
            avg_time = f"{metrics.queue_avg_processing_time:.1f}s" if metrics.queue_avg_processing_time > 0 else "N/A"
            volume = f"${metrics.total_volume_usd:,.0f}" if metrics.total_volume_usd > 0 else "$0"
            
            report.append(row_format.format(
                window_name,
                metrics.new_tokens,
                metrics.new_transactions,
                metrics.token_updates,
                metrics.history_snapshots,
                metrics.queue_tokens_added,
                metrics.queue_tokens_pending,
                metrics.queue_tokens_processing,
                metrics.queue_tokens_completed,
                metrics.queue_tokens_failed,
                metrics.queue_tokens_retrying,
                success_rate,
                avg_time,
                volume
            ))
        
        report.append("")
        
        # === MÉTRIQUES DE TRADING ===
        report.append("💰 MÉTRIQUES DE TRADING")
        report.append("-" * 30)
        
        headers_trading = ["Période", "Buys", "Sells", "B/S Ratio", "Buy Vol$", "Sell Vol$", "Wallets", "Active Tokens"]
        row_format_trading = "{:<8} {:<6} {:<6} {:<9} {:<10} {:<11} {:<8} {:<13}"
        report.append(row_format_trading.format(*headers_trading))
        report.append("-" * 80)
        
        for window_name, metrics in time_metrics.items():
            bs_ratio = "∞" if metrics.buy_sell_ratio == float('inf') else f"{metrics.buy_sell_ratio:.2f}"
            buy_vol = f"${metrics.volume_buy_usd:,.0f}" if metrics.volume_buy_usd > 0 else "$0"
            sell_vol = f"${metrics.volume_sell_usd:,.0f}" if metrics.volume_sell_usd > 0 else "$0"
            
            report.append(row_format_trading.format(
                window_name,
                metrics.buy_transactions,
                metrics.sell_transactions,
                bs_ratio,
                buy_vol,
                sell_vol,
                metrics.unique_wallets,
                metrics.unique_active_tokens
            ))
        
        report.append("")
        
        # === SANTÉ DU SYSTÈME ÉTENDUE ===
        report.append("🏥 SANTÉ DU SYSTÈME")
        report.append("-" * 30)
        report.append(f"📈 Total tokens: {system_health.total_tokens:,}")
        report.append(f"✅ Données complètes: {system_health.tokens_with_complete_data:,} ({system_health.data_completeness_rate:.1f}%)")
        report.append(f"🔄 Fraîcheur des données: {system_health.freshness_rate:.1f}%")
        report.append(f"💰 Sans prix: {system_health.tokens_missing_price:,}")
        report.append(f"📝 Sans métadonnées: {system_health.tokens_missing_metadata:,}")
        report.append(f"⏱️  Jamais mis à jour: {system_health.tokens_never_updated:,}")
        report.append(f"🕐 Données obsolètes (>24h): {system_health.tokens_stale:,}")
        report.append(f"💀 Tokens morts: {system_health.tokens_dead:,}")
        report.append(f"🚫 Flaggés sans données: {system_health.tokens_flagged_no_data:,}")
        report.append(f"🚨 Tokens ruggés: {system_health.tokens_rugged:,}")
        report.append(f"🔥 Haute activité (>10 tx/24h): {system_health.tokens_high_activity:,}")
        report.append(f"💤 Sans activité: {system_health.tokens_zero_activity:,}")
        report.append(f"⌚ Âge moyen des tokens: {system_health.avg_token_age_hours:.1f}h")
        report.append(f"💰 Volume total 24h: ${system_health.total_volume_24h:,.0f}")
        report.append(f"📡 Taux d'erreur API: {system_health.api_error_rate:.1f}%")
        
        report.append("")
        
        # === STATUT DE MISE À JOUR (5 MINUTES) ===
        report.append("🔄 STATUT DE MISE À JOUR (5 MINUTES)")
        report.append("-" * 40)
        report.append(f"✅ Récemment mis à jour (<5m): {system_health.tokens_recently_updated:,}")
        report.append(f"⏰ Obsolètes (>5m): {system_health.tokens_outdated:,}")
        report.append(f"❓ Symboles inconnus (UNK%): {system_health.tokens_unknown_symbol:,}")
        report.append(f"🚫 Sans données disponibles: {system_health.tokens_no_data_available:,}")
        
        # Calcul du pourcentage de tokens à jour
        total_valid_tokens = system_health.tokens_recently_updated + system_health.tokens_outdated
        if total_valid_tokens > 0:
            freshness_5m_rate = (system_health.tokens_recently_updated / total_valid_tokens) * 100
            report.append(f"📊 Taux de fraîcheur (5m): {freshness_5m_rate:.1f}%")
        
        report.append("")
        
        # === STATUT DE LA QUEUE ÉTENDU ===
        report.append("📋 STATUT DE LA QUEUE")
        report.append("-" * 30)
        report.append(f"📊 Total items: {system_health.queue_total_items:,}")
        report.append(f"⏳ En attente: {system_health.queue_pending:,}")
        report.append(f"🔄 En traitement: {system_health.queue_processing:,}")
        report.append(f"✅ Terminés: {system_health.queue_completed:,}")
        report.append(f"❌ Échoués: {system_health.queue_failed:,}")
        report.append(f"🔄 En retry: {system_health.queue_retrying:,}")
        report.append(f"🗑️ Abandonnés: {system_health.queue_abandoned:,}")
        report.append(f"📊 Taux de succès global: {system_health.queue_overall_success_rate:.1f}%")
        report.append(f"⏱️ Temps traitement moyen: {system_health.queue_avg_processing_time_all:.1f}s")
        report.append(f"📋 Backlog actuel: {system_health.queue_backlog_size:,}")
        if system_health.queue_oldest_pending_hours > 0:
            report.append(f"⏰ Plus ancien en attente: {system_health.queue_oldest_pending_hours:.1f}h")
        
        report.append("")
        
        # === PERFORMANCE DE LA QUEUE PAR PÉRIODE ===
        report.append("⚡ PERFORMANCE QUEUE PAR PÉRIODE")
        report.append("-" * 50)
        
        headers_perf = ["Période", "Rate/h", "Success%", "AvgTime", "Throughput/min", "Efficiency%", "API Errors"]
        row_format_perf = "{:<8} {:<8} {:<8} {:<8} {:<14} {:<12} {:<11}"
        report.append(row_format_perf.format(*headers_perf))
        report.append("-" * 75)
        
        for window_name, metrics in time_metrics.items():
            rate = f"{metrics.queue_processing_rate:.1f}" if metrics.queue_processing_rate > 0 else "0"
            success = f"{metrics.queue_success_rate:.1f}%" if metrics.queue_success_rate > 0 else "N/A"
            avg_time = f"{metrics.queue_avg_processing_time:.1f}s" if metrics.queue_avg_processing_time > 0 else "N/A"
            throughput = f"{metrics.queue_throughput:.1f}" if metrics.queue_throughput > 0 else "0"
            efficiency = f"{metrics.queue_efficiency:.1f}%" if metrics.queue_efficiency > 0 else "N/A"
            
            report.append(row_format_perf.format(
                window_name,
                rate,
                success,
                avg_time,
                throughput,
                efficiency,
                metrics.api_errors
            ))
        
        report.append("")
        
        # === PERFORMANCE GÉNÉRALE ÉTENDUE ===
        if performance:
            report.append("⚡ PERFORMANCE GÉNÉRALE")
            report.append("-" * 25)
            
            # Délais de détection
            detection = performance.get('detection_delay', {})
            report.append(f"🎯 Délai détection moyen: {detection.get('avg_seconds', 0):.1f}s")
            report.append(f"   ├─ Médian: {detection.get('median_seconds', 0):.1f}s")
            report.append(f"   ├─ P95: {detection.get('p95_seconds', 0):.1f}s")
            report.append(f"   └─ Min/Max: {detection.get('min_seconds', 0):.1f}s / {detection.get('max_seconds', 0):.1f}s")
            
            # API Success
            api_perf = performance.get('api_success_rate', {})
            report.append(f"📡 Taux succès API: {api_perf.get('success_rate_pct', 0):.1f}%")
            report.append(f"   ├─ Tokens traités: {api_perf.get('total_tokens', 0):,}")
            report.append(f"   ├─ Succès: {api_perf.get('successful', 0):,}")
            report.append(f"   ├─ Échecs: {api_perf.get('failed', 0):,}")
            report.append(f"   └─ Moy. échecs/token: {api_perf.get('avg_failures_per_token', 0):.1f}")
            
            # Historisation
            hist = performance.get('historization', {})
            report.append(f"📊 Snapshots 24h: {hist.get('total_snapshots', 0):,}")
            report.append(f"   ├─ Tokens uniques: {hist.get('unique_tokens', 0):,}")
            report.append(f"   ├─ Score viabilité: {hist.get('avg_viability_score', 0):.1f}/100")
            report.append(f"   └─ Score risque: {hist.get('avg_risk_score', 0):.1f}/100")
            
            # Données de marché
            market = performance.get('market_data', {})
            if market:
                report.append(f"💰 Prix moyen: ${market.get('avg_price_usd', 0):.6f}")
                report.append(f"   ├─ Prix min/max: ${market.get('min_price_usd', 0):.6f} / ${market.get('max_price_usd', 0):.2f}")
                report.append(f"   ├─ Market cap moyen: ${market.get('avg_market_cap', 0):,.0f}")
                report.append(f"   └─ Tokens >$1M MC: {market.get('tokens_over_1m_mc', 0):,}")
            
            report.append("")
        
        # === TOP TOKENS ACTIFS ÉTENDU ===
        if top_tokens:
            report.append("🔥 TOP 10 TOKENS ACTIFS (24H)")
            report.append("-" * 80)
            
            headers_tokens = ["#", "Symbol", "TX", "Wallets", "B/S Ratio", "Volume", "MC", "Last Activity"]
            row_format_tokens = "{:<3} {:<12} {:<5} {:<8} {:<9} {:<12} {:<12} {:<15}"
            report.append(row_format_tokens.format(*headers_tokens))
            report.append("-" * 85)
            
            for i, token in enumerate(top_tokens[:10], 1):
                symbol = token['symbol'][:10] if len(token['symbol']) > 10 else token['symbol']
                bs_ratio = "∞" if token['buy_sell_ratio'] == float('inf') else f"{token['buy_sell_ratio']:.2f}"
                volume = f"${token['total_volume']:,.0f}" if token['total_volume'] > 0 else "$0"
                mc_str = f"${token['market_cap']:,.0f}" if token['market_cap'] > 0 else "N/A"
                
                # Formater la dernière activité
                try:
                    if token['last_activity']:
                        last_act = datetime.fromisoformat(token['last_activity'].replace('Z', '+00:00'))
                        time_diff = datetime.now() - last_act
                        if time_diff.total_seconds() < 3600:
                            last_act_str = f"{int(time_diff.total_seconds()/60)}m ago"
                        else:
                            last_act_str = f"{int(time_diff.total_seconds()/3600)}h ago"
                    else:
                        last_act_str = "N/A"
                except:
                    last_act_str = "N/A"
                
                report.append(row_format_tokens.format(
                    f"{i:2d}.",
                    symbol,
                    token['transaction_count'],
                    token['unique_wallets'],
                    bs_ratio,
                    volume,
                    mc_str,
                    last_act_str
                ))
        
        report.append("")
        
        # === SEUILS D'ALERTE ===
        report.append("⚙️ CONFIGURATION DES SEUILS D'ALERTE")
        report.append("-" * 40)
        report.append(f"📋 Queue backlog: ⚠️{self.alert_thresholds.queue_backlog_warning} / 🚨{self.alert_thresholds.queue_backlog_critical}")
        report.append(f"✅ Taux de succès: ⚠️{self.alert_thresholds.success_rate_warning:.1f}% / 🚨{self.alert_thresholds.success_rate_critical:.1f}%")
        report.append(f"⏱️ Temps traitement: ⚠️{self.alert_thresholds.processing_time_warning:.0f}s / 🚨{self.alert_thresholds.processing_time_critical:.0f}s")
        report.append(f"📡 Erreurs API: ⚠️{self.alert_thresholds.api_error_rate_warning:.1f}% / 🚨{self.alert_thresholds.api_error_rate_critical:.1f}%")
        report.append(f"🕐 Tokens obsolètes: ⚠️{self.alert_thresholds.stale_tokens_warning} / 🚨{self.alert_thresholds.stale_tokens_critical}")
        
        report.append("")
        report.append("=" * 100)
        
        return "\n".join(report)
    
    def _generate_json_report(self, time_metrics: Dict, system_health: SystemHealth, 
                             top_tokens: List[Dict], performance: Dict) -> str:
        """Générer un rapport JSON"""
        report_data = {
            'timestamp': self.current_timestamp,
            'generated_at': datetime.now().isoformat(),
            'database_path': self.db_path,
            'time_window_metrics': {k: v.__dict__ for k, v in time_metrics.items()},
            'system_health': system_health.__dict__,
            'top_active_tokens': top_tokens,
            'performance_metrics': performance,
            'time_windows_config': self.time_windows,
            'alert_thresholds': self.alert_thresholds.__dict__,
            'alerts_active': system_health.alerts,
            'summary': {
                'total_alerts': len(system_health.alerts),
                'critical_alerts': len([a for a in system_health.alerts if '🚨' in a]),
                'warning_alerts': len([a for a in system_health.alerts if '⚠️' in a]),
                'overall_system_status': 'CRITICAL' if any('🚨' in a for a in system_health.alerts) 
                                       else 'WARNING' if any('⚠️' in a for a in system_health.alerts) 
                                       else 'HEALTHY'
            }
        }
        
        return json.dumps(report_data, indent=2, default=str)

def main():
    """Point d'entrée principal"""
    global config, logger
    
    # Configuration depuis le système central
    try:
        config = get_config()
        logger = setup_metrics_logger(config)
        
        logger.info("🚀 Démarrage du système de métriques avancé")
        
    except Exception as e:
        print(f"❌ Erreur lors du chargement de la configuration: {e}")
        sys.exit(1)
    
    parser = argparse.ArgumentParser(
        description='Générateur de métriques avancées pour le système de tokens',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples d'utilisation:
  python token_metrics.py                           # Rapport unique
  python token_metrics.py --format json             # Format JSON
  python token_metrics.py --watch                   # Surveillance continue
  python token_metrics.py --watch --interval 60     # Surveillance toutes les 60s
  python token_metrics.py --watch --auto-scroll     # Avec historique
  python token_metrics.py --watch --quick           # Mode métriques rapides
  python token_metrics.py --output report.txt       # Sauvegarder
  python token_metrics.py --configure-alerts        # Configurer les seuils d'alerte
        """
    )
    
    # Arguments de base
    parser.add_argument('--format', choices=['text', 'json'], default='text', 
                       help='Format de sortie (text ou json)')
    parser.add_argument('--output', type=str, help='Fichier de sortie (optionnel)')
    
    # Arguments pour monitoring continu
    parser.add_argument('--watch', action='store_true', 
                       help='Mode surveillance continue (met à jour l\'écran)')
    parser.add_argument('--interval', type=int, default=30, 
                       help='Intervalle de rafraîchissement en secondes (défaut: 30)')
    parser.add_argument('--auto-scroll', action='store_true',
                       help='Mode défilement automatique (garde l\'historique visible)')
    parser.add_argument('--quick', action='store_true',
                       help='Mode métriques rapides (affichage compact)')
    
    # Arguments avancés
    parser.add_argument('--save-history', action='store_true',
                       help='Sauvegarder l\'historique des métriques dans un fichier')
    parser.add_argument('--alert-threshold', type=int, default=0,
                       help='Seuil d\'alerte pour nouveaux tokens (0 = désactivé)')
    parser.add_argument('--configure-alerts', action='store_true',
                       help='Mode configuration interactive des seuils d\'alerte')
    
    # Seuils d'alerte configurables via arguments
    parser.add_argument('--queue-backlog-warning', type=int, default=500,
                       help='Seuil d\'attention pour le backlog de la queue')
    parser.add_argument('--queue-backlog-critical', type=int, default=1000,
                       help='Seuil critique pour le backlog de la queue')
    parser.add_argument('--success-rate-warning', type=float, default=80.0,
                       help='Seuil d\'attention pour le taux de succès (%)')
    parser.add_argument('--success-rate-critical', type=float, default=50.0,
                       help='Seuil critique pour le taux de succès (%)')
    
    args = parser.parse_args()
    
    # Validation des arguments
    if args.interval < 5:
        logger.warning("Intervalle minimum recommandé de 5 secondes")
        print("⚠️  Attention: intervalle minimum recommandé de 5 secondes")
        args.interval = 5
    
    if args.quick and not args.watch:
        logger.warning("L'option --quick n'est disponible qu'en mode --watch")
        print("⚠️  L'option --quick n'est disponible qu'en mode --watch")
        args.quick = False
    
    # Utiliser la base de données depuis la configuration
    db_path = config.database.get_full_path()
    
    # Vérifier que la base de données existe
    if not os.path.exists(db_path):
        logger.error(f"Base de données introuvable à {db_path}")
        print(f"❌ Erreur: Base de données introuvable à {db_path}")
        print("💡 Vérifiez la configuration dans config.py")
        return 1
    
    try:
        collector = TokenMetricsCollector(db_path)
        
        # Configuration des seuils d'alerte depuis les arguments
        collector.alert_thresholds.queue_backlog_warning = args.queue_backlog_warning
        collector.alert_thresholds.queue_backlog_critical = args.queue_backlog_critical
        collector.alert_thresholds.success_rate_warning = args.success_rate_warning
        collector.alert_thresholds.success_rate_critical = args.success_rate_critical
        
        logger.info(f"✅ Collecteur initialisé avec DB: {db_path}")
        logger.info(f"⚙️ Seuils d'alerte: Backlog {args.queue_backlog_warning}/{args.queue_backlog_critical}, Success {args.success_rate_warning}/{args.success_rate_critical}%")
        
        if args.configure_alerts:
            # Mode configuration interactive des seuils d'alerte
            print("⚙️ CONFIGURATION DES SEUILS D'ALERTE")
            print("=" * 40)
            print("Configuration actuelle:")
            print(f"├─ Queue backlog: ⚠️{collector.alert_thresholds.queue_backlog_warning} / 🚨{collector.alert_thresholds.queue_backlog_critical}")
            print(f"├─ Taux de succès: ⚠️{collector.alert_thresholds.success_rate_warning:.1f}% / 🚨{collector.alert_thresholds.success_rate_critical:.1f}%")
            print(f"├─ Temps traitement: ⚠️{collector.alert_thresholds.processing_time_warning:.0f}s / 🚨{collector.alert_thresholds.processing_time_critical:.0f}s")
            print(f"└─ Erreurs API: ⚠️{collector.alert_thresholds.api_error_rate_warning:.1f}% / 🚨{collector.alert_thresholds.api_error_rate_critical:.1f}%")
            print("\n💡 Utilisez les arguments --queue-backlog-warning, --queue-backlog-critical, etc. pour modifier les seuils")
            return 0
        
        if args.watch:
            # Mode surveillance continue
            logger.info(f"🔄 Démarrage du monitoring continu (intervalle: {args.interval}s)")
            print(f"🔄 Démarrage du monitoring continu...")
            print(f"📊 Base de données: {db_path}")
            print(f"📝 Logs: {config.logging.get_full_path()}")
            print(f"⏱️  Intervalle: {args.interval}s")
            print(f"📋 Mode: {'Rapide' if args.quick else 'Complet'} | {'Défilement' if args.auto_scroll else 'Écran effacé'}")
            print(f"🚨 Alertes: {'Activées' if args.alert_threshold > 0 else 'Système activé'}")
            print(f"⚙️ Seuils: Backlog {args.queue_backlog_warning}/{args.queue_backlog_critical}")
            print("\n" + "─" * 60)
            
            if args.auto_scroll:
                collector.run_continuous_with_history(
                    refresh_interval=args.interval,
                    quick_mode=args.quick,
                    alert_threshold=args.alert_threshold,
                    save_history=args.save_history
                )
            else:
                collector.run_continuous_monitoring(
                    refresh_interval=args.interval,
                    quick_mode=args.quick,
                    alert_threshold=args.alert_threshold
                )
        else:
            # Génération unique
            logger.info("📊 Génération d'un rapport unique")
            print("🔄 Génération du rapport avancé...")
            report = collector.generate_report(args.format)
            
            if args.output:
                output_path = Path(config.logging.base_dir) / args.output
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(report)
                logger.info(f"Rapport sauvegardé dans: {output_path}")
                print(f"📝 Rapport sauvegardé dans: {output_path}")
                
                # Afficher aussi à l'écran si format texte
                if args.format == 'text':
                    print("\n" + "─" * 40)
                    print("📊 APERÇU DU RAPPORT:")
                    print("─" * 40)
                    # Afficher les premières lignes
                    lines = report.split('\n')
                    for line in lines[:25]:
                        print(line)
                    if len(lines) > 25:
                        print(f"... ({len(lines) - 25} lignes supplémentaires dans le fichier)")
            else:
                print(report)
        
        logger.info("✅ Système de métriques terminé avec succès")
        return 0
        
    except KeyboardInterrupt:
        logger.info("⌨️ Arrêt demandé par l'utilisateur")
        print("\n👋 Arrêt demandé par l'utilisateur")
        return 0
    except FileNotFoundError as e:
        logger.error(f"Fichier introuvable: {e}")
        print(f"❌ Fichier introuvable: {e}")
        return 1
    except sqlite3.Error as e:
        logger.error(f"Erreur base de données: {e}")
        print(f"❌ Erreur base de données: {e}")
        print("💡 Vérifiez que la base de données n'est pas corrompue")
        return 1
    except Exception as e:
        logger.error(f"Erreur inattendue: {e}")
        print(f"❌ Erreur inattendue: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        print("🔍 Détails de l'erreur:")
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)