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

    # === NOUVEAUX CHAMPS POUR LA QUEUE ===
    queue_tokens_added: int = 0
    queue_tokens_processing: int = 0
    queue_tokens_completed: int = 0
    queue_tokens_failed: int = 0
    queue_tokens_retrying: int = 0
    queue_processing_rate: float = 0.0  # tokens processed per hour
    queue_success_rate: float = 0.0     # percentage
    queue_avg_processing_time: float = 0.0  # seconds

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

    # === NOUVEAUX CHAMPS POUR LA QUEUE ===
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
                
                # 2. Nouvelles transactions
                cursor.execute("""
                    SELECT COUNT(*) FROM transactions 
                    WHERE created_at > datetime('now', '-' || ? || ' seconds')
                    OR datetime(created_at, 'unixepoch') > datetime('now', '-' || ? || ' seconds')
                """, (window_seconds, window_seconds))
                metrics.new_transactions = cursor.fetchone()[0]
                
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
                
                # 6. Mises à jour Rugcheck
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens 
                    WHERE last_rugcheck_update > ?
                """, (cutoff_time,))
                metrics.rugcheck_updates = cursor.fetchone()[0]
                
                # 7. Métriques de transactions détaillées
                cursor.execute("""
                    SELECT 
                        COUNT(DISTINCT wallet_address) as unique_wallets,
                        COUNT(CASE WHEN transaction_type = 'TransactionType.BUY' THEN 1 END) as buys,
                        COUNT(CASE WHEN transaction_type = 'TransactionType.SELL' THEN 1 END) as sells,
                        COALESCE(SUM(amount), 0) as total_volume,
                        COALESCE(AVG(detection_delay), 0) as avg_delay
                    FROM transactions 
                    WHERE created_at > datetime('now', '-' || ? || ' seconds')
                    OR datetime(created_at, 'unixepoch') > datetime('now', '-' || ? || ' seconds')
                """, (window_seconds, window_seconds))
                
                tx_data = cursor.fetchone()
                metrics.unique_wallets = tx_data[0] or 0
                metrics.buy_transactions = tx_data[1] or 0
                metrics.sell_transactions = tx_data[2] or 0
                metrics.total_volume_usd = tx_data[3] or 0.0
                metrics.avg_detection_delay = tx_data[4] or 0.0
                
                # 8. Estimation des appels API (basée sur les mises à jour)
                # Approximation : 1 token update = ~3 API calls (DexScreener + Rugcheck + éventuellement Pump.fun)
                metrics.api_calls_estimated = (metrics.token_updates * 3) + (metrics.new_tokens * 4)
                
                # === NOUVELLES MÉTRIQUES POUR LA QUEUE ===
            
                # 9. Tokens ajoutés à la queue
                cursor.execute("""
                    SELECT COUNT(*) FROM token_processing_queue 
                    WHERE created_at > datetime('now', '-' || ? || ' seconds')
                """, (window_seconds,))
                metrics.queue_tokens_added = cursor.fetchone()[0]
                
                # 10. Tokens traités (passés de processing à completed/failed)
                cursor.execute("""
                    SELECT COUNT(*) FROM token_processing_queue 
                    WHERE completed_at > datetime('now', '-' || ? || ' seconds')
                    AND status IN ('completed', 'failed')
                """, (window_seconds,))
                tokens_processed = cursor.fetchone()[0]
                
                # 11. Répartition par statut des tokens traités dans la fenêtre
                cursor.execute("""
                    SELECT 
                        COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed,
                        COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed,
                        COUNT(CASE WHEN status = 'retrying' THEN 1 END) as retrying
                    FROM token_processing_queue 
                    WHERE completed_at > datetime('now', '-' || ? || ' seconds')
                    OR (status = 'retrying' AND last_retry_at > datetime('now', '-' || ? || ' seconds'))
                """, (window_seconds, window_seconds))
                
                queue_status_data = cursor.fetchone()
                metrics.queue_tokens_completed = queue_status_data[0] or 0
                metrics.queue_tokens_failed = queue_status_data[1] or 0
                metrics.queue_tokens_retrying = queue_status_data[2] or 0
                
                # 12. Tokens actuellement en processing (démarrés dans la fenêtre)
                cursor.execute("""
                    SELECT COUNT(*) FROM token_processing_queue 
                    WHERE processing_started_at > datetime('now', '-' || ? || ' seconds')
                    AND status = 'processing'
                """, (window_seconds,))
                metrics.queue_tokens_processing = cursor.fetchone()[0]
                
                # 13. Calcul du taux de traitement (tokens/heure)
                if window_seconds > 0:
                    hours = window_seconds / 3600
                    metrics.queue_processing_rate = tokens_processed / hours if hours > 0 else 0
                
                # 14. Taux de succès dans la fenêtre
                if tokens_processed > 0:
                    metrics.queue_success_rate = (metrics.queue_tokens_completed / tokens_processed) * 100
                
                # 15. Temps de traitement moyen pour les tokens complétés dans la fenêtre
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
                    print(f"🏥 Santé système: {system_health.data_completeness_rate:.1f}% complétude | {system_health.freshness_rate:.1f}% fraîcheur")
                    print(f"🔄 Récemment mis à jour (5m): {system_health.tokens_recently_updated}")
                    print(f"⏰ Obsolètes (>5m): {system_health.tokens_outdated}")
                    
                    self.logger.info(f"Métriques complètes - itération {iteration}: {time_metrics.new_tokens} tokens, {time_metrics.new_transactions} tx")
                    
                    if save_history and history_file:
                        with open(Path(config.logging.base_dir) / history_file, 'a', encoding='utf-8') as f:
                            f.write(f"{datetime.now().isoformat()} - Tokens: {time_metrics.new_tokens}, TX: {time_metrics.new_transactions}, Updates: {time_metrics.token_updates}\n")
                
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

    def get_system_health(self) -> SystemHealth:
        """Obtenir la santé globale du système"""
        health = SystemHealth()
        self.logger.debug("🔍 Collecte des métriques de santé système")
        
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
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
                
                # === NOUVELLES MÉTRIQUES ===
                
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
                # Excluant no_data_available = 1 et symbol LIKE 'UNK%'
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

                # === NOUVELLES MÉTRIQUES POUR LA QUEUE ===
            
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

                # Calcul des taux
                if health.total_tokens > 0:
                    health.data_completeness_rate = (health.tokens_with_complete_data / health.total_tokens) * 100
                    
                    fresh_tokens = health.total_tokens - health.tokens_stale - health.tokens_never_updated - health.tokens_dead
                    health.freshness_rate = max(0, (fresh_tokens / health.total_tokens) * 100)
                
                self.logger.debug(f"✅ Santé système collectée: {health.total_tokens} tokens total, {health.data_completeness_rate:.1f}% complétude")
                
        except Exception as e:
            self.logger.error(f"❌ Erreur lors de la collecte de la santé système: {e}")
        
        return health
    
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
                        MAX(t.created_at) as last_activity
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
                    results.append({
                        'token_address': row[0],
                        'symbol': row[1] or 'Unknown',
                        'name': row[2] or 'Unknown Token',
                        'market_cap': row[3] or 0,
                        'price_usd': row[4] or 0,
                        'transaction_count': row[5],
                        'unique_wallets': row[6],
                        'buy_volume': row[7] or 0,
                        'sell_volume': row[8] or 0,
                        'last_activity': row[9],
                        'volume_ratio': (row[7] / row[8]) if row[8] and row[8] > 0 else float('inf')
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
                        MAX(detection_delay) as max_delay
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
                        COUNT(CASE WHEN no_data_available = 1 THEN 1 END) as failed_tokens
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
                        AVG(risk_score) as avg_risk
                    FROM tokens_history
                    WHERE snapshot_timestamp > ?
                """, (self.current_timestamp - 86400,))
                history_stats = cursor.fetchone()
                
                perf_data = {
                    'detection_delay': {
                        'avg_seconds': delay_stats[0] or 0,
                        'min_seconds': delay_stats[1] or 0,
                        'max_seconds': delay_stats[2] or 0
                    },
                    'api_success_rate': {
                        'total_tokens': api_stats[0] or 0,
                        'successful': api_stats[1] or 0,
                        'failed': api_stats[2] or 0,
                        'success_rate_pct': ((api_stats[1] or 0) / max(api_stats[0], 1)) * 100
                    },
                    'historization': {
                        'total_snapshots': history_stats[0] or 0,
                        'unique_tokens': history_stats[1] or 0,
                        'avg_viability_score': history_stats[2] or 0,
                        'avg_risk_score': history_stats[3] or 0
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
            
            return f"""
🔄 LIVE METRICS
├─ 🆕 Nouveaux tokens (5m): {metrics_5m.new_tokens}
├─ 📈 Transactions (5m): {metrics_5m.new_transactions}
├─ 🔄 Updates (5m): {metrics_5m.token_updates}
├─ 📊 Snapshots (5m): {metrics_5m.history_snapshots}
├─ 👥 Wallets actifs (5m): {metrics_5m.unique_wallets}
├─ 🏥 Santé: {health.data_completeness_rate:.1f}% | Fraîcheur: {health.freshness_rate:.1f}%
├─ ✅ Récemment mis à jour (<5m): {health.tokens_recently_updated}
├─ ⏰ Obsolètes (>5m): {health.tokens_outdated}
├─ ❓ Symboles inconnus (UNK%): {health.tokens_unknown_symbol}
├─ 🚫 Sans données disponibles: {health.tokens_no_data_available}
└─ 🚨 Tokens ruggés: {health.tokens_rugged}
├─ 📋 QUEUE (5m): +{metrics_5m.queue_tokens_added} ✅{metrics_5m.queue_tokens_completed} ❌{metrics_5m.queue_tokens_failed}
├─ 📋 Queue backlog: {health.queue_backlog_size} | Success: {health.queue_overall_success_rate:.1f}%
└─ ⏱️ Queue processing: {metrics_5m.queue_avg_processing_time:.1f}s avg | {metrics_5m.queue_processing_rate:.1f}/h
            """
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
        report.append("=" * 80)
        report.append("🎯 RAPPORT DE MÉTRIQUES DU SYSTÈME DE TOKENS")
        report.append("=" * 80)
        report.append(f"📅 Généré le: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"💾 Base de données: {self.db_path}")
        report.append("")
        
        # Métriques par fenêtre de temps MODIFIÉES
        report.append("📊 ACTIVITÉ PAR PÉRIODE")
        report.append("-" * 50)
        
        # HEADERS MODIFIÉS pour inclure la queue
        headers = ["Période", "Tokens", "TX", "Updates", "Snapshots", "+Queue", "✅Queue", "❌Queue"]
        row_format = "{:<8} {:<8} {:<8} {:<8} {:<10} {:<8} {:<8} {:<8}"
        report.append(row_format.format(*headers))
        report.append("-" * 70)
        
        for window_name, metrics in time_metrics.items():
            # LIGNE MODIFIÉE avec les métriques de queue
            report.append(row_format.format(
                window_name,
                metrics.new_tokens,
                metrics.new_transactions,
                metrics.token_updates,
                metrics.history_snapshots,
                metrics.queue_tokens_added,
                metrics.queue_tokens_completed,
                metrics.queue_tokens_failed
            ))
        
        report.append("")
        
        # Santé du système (INCHANGÉ)
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
        
        # === NOUVELLES MÉTRIQUES === (INCHANGÉ)
        report.append("")
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
        
        # === NOUVELLE SECTION: STATUT DE LA QUEUE ===
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
        
        # === NOUVELLE SECTION: PERFORMANCE DE LA QUEUE PAR PÉRIODE ===
        report.append("⚡ PERFORMANCE QUEUE PAR PÉRIODE")
        report.append("-" * 40)
        
        headers_perf = ["Période", "Rate/h", "Success%", "AvgTime", "Wallets"]
        row_format_perf = "{:<8} {:<8} {:<8} {:<8} {:<8}"
        report.append(row_format_perf.format(*headers_perf))
        report.append("-" * 42)
        
        for window_name, metrics in time_metrics.items():
            report.append(row_format_perf.format(
                window_name,
                f"{metrics.queue_processing_rate:.1f}",
                f"{metrics.queue_success_rate:.1f}%",
                f"{metrics.queue_avg_processing_time:.1f}s",
                f"{metrics.unique_wallets}"
            ))
        
        report.append("")
        
        # Performance (INCHANGÉ)
        if performance:
            report.append("⚡ PERFORMANCE GÉNÉRALE")
            report.append("-" * 25)
            report.append(f"🎯 Délai détection moyen: {performance.get('detection_delay', {}).get('avg_seconds', 0):.1f}s")
            report.append(f"📡 Taux succès API: {performance.get('api_success_rate', {}).get('success_rate_pct', 0):.1f}%")
            report.append(f"📊 Snapshots 24h: {performance.get('historization', {}).get('total_snapshots', 0):,}")
            report.append(f"🔒 Score viabilité moyen: {performance.get('historization', {}).get('avg_viability_score', 0):.1f}/100")
            report.append("")
        
        # Top tokens actifs (INCHANGÉ)
        if top_tokens:
            report.append("🔥 TOP 10 TOKENS ACTIFS (24H)")
            report.append("-" * 40)
            for i, token in enumerate(top_tokens[:10], 1):
                symbol = token['symbol'][:10] if len(token['symbol']) > 10 else token['symbol']
                mc_str = f"${token['market_cap']:,.0f}" if token['market_cap'] > 0 else "N/A"
                report.append(f"{i:2d}. {symbol:<12} | {token['transaction_count']:3d} tx | {token['unique_wallets']:3d} wallets | MC: {mc_str}")
        
        report.append("")
        report.append("=" * 80)
        
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
            'time_windows_config': self.time_windows
        }
        
        return json.dumps(report_data, indent=2, default=str)

def main():
    """Point d'entrée principal"""
    global config, logger
    
    # Configuration depuis le système central
    try:
        config = get_config()
        logger = setup_metrics_logger(config)
        
        logger.info("🚀 Démarrage du système de métriques")
        
    except Exception as e:
        print(f"❌ Erreur lors du chargement de la configuration: {e}")
        sys.exit(1)
    
    parser = argparse.ArgumentParser(
        description='Générateur de métriques pour le système de tokens',
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
        logger.info(f"✅ Collecteur initialisé avec DB: {db_path}")
        
        if args.watch:
            # Mode surveillance continue
            logger.info(f"🔄 Démarrage du monitoring continu (intervalle: {args.interval}s)")
            print(f"🔄 Démarrage du monitoring continu...")
            print(f"📊 Base de données: {db_path}")
            print(f"📝 Logs: {config.logging.get_full_path()}")
            print(f"⏱️  Intervalle: {args.interval}s")
            print(f"📋 Mode: {'Rapide' if args.quick else 'Complet'} | {'Défilement' if args.auto_scroll else 'Écran effacé'}")
            print(f"🚨 Alertes: {'Activées' if args.alert_threshold > 0 else 'Désactivées'}")
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
            print("🔄 Génération du rapport...")
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
                    for line in lines[:20]:
                        print(line)
                    if len(lines) > 20:
                        print(f"... ({len(lines) - 20} lignes supplémentaires dans le fichier)")
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