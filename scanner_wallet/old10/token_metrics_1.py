#!/usr/bin/env python3
"""
Système de métriques pour le monitoring des tokens avec graphiques temps réel
Fournit des statistiques détaillées sur l'activité du système avec visualisation
NOUVEAU: Monitoring temps réel des API calls
"""

import sqlite3
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import argparse
from collections import deque, defaultdict
import threading

# Imports pour les graphiques
try:
    import matplotlib.pyplot as plt
    import matplotlib.animation as animation
    from matplotlib.dates import DateFormatter
    import numpy as np
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("⚠️  matplotlib non disponible. Installez avec: pip install matplotlib")

# Configuration
CONFIG = {
    'db_path': 'solana_wallet_monitor.db',
    'time_windows': {
        '5m': 300,      # 5 minutes
        '1h': 3600,     # 1 heure
        '6h': 21600,    # 6 heures
        '24h': 86400,   # 24 heures
        '7d': 604800,   # 7 jours
    },
    'graph_config': {
        'max_points': 50,      # Nombre max de points sur le graphique
        'update_interval': 30,  # Intervalle de mise à jour en secondes
        'figure_size': (20, 12), # Taille de la fenêtre (augmentée pour plus de graphiques)
        'subplot_rows': 3,      # Nombre de lignes de sous-graphiques (augmenté)
        'subplot_cols': 3,      # Nombre de colonnes de sous-graphiques
    }
}

@dataclass
class ApiMetrics:
    """Métriques spécifiques aux API calls"""
    window: str
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    avg_response_time: float = 0.0
    success_rate: float = 0.0
    calls_per_minute: float = 0.0
    api_breakdown: Dict[str, int] = None  # Calls par API
    slowest_apis: List[Tuple[str, float]] = None  # APIs les plus lentes

    def __post_init__(self):
        if self.api_breakdown is None:
            self.api_breakdown = {}
        if self.slowest_apis is None:
            self.slowest_apis = []

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
    data_completeness_rate: float = 0.0
    freshness_rate: float = 0.0

@dataclass
class MetricsSnapshot:
    """Snapshot des métriques à un moment donné"""
    timestamp: datetime
    metrics_5m: TimeWindowMetrics
    system_health: SystemHealth
    api_metrics_5m: ApiMetrics  # NOUVEAU: Métriques API

class RealTimeGraphs:
    """Gestionnaire des graphiques temps réel avec support API"""
    
    def __init__(self, max_points: int = 50):
        if not MATPLOTLIB_AVAILABLE:
            raise ImportError("matplotlib requis pour les graphiques")
        
        self.max_points = max_points
        self.data_history = deque(maxlen=max_points)
        self.running = False
        
        # Configuration matplotlib
        plt.style.use('dark_background')
        self.fig, self.axes = plt.subplots(
            CONFIG['graph_config']['subplot_rows'], 
            CONFIG['graph_config']['subplot_cols'],
            figsize=CONFIG['graph_config']['figure_size']
        )
        self.fig.suptitle('📊 Token System + API Metrics - Real Time Dashboard', fontsize=16, color='white')
        
        # Aplatir les axes pour faciliter l'accès
        self.axes = self.axes.flatten()
        
        # Initialiser les graphiques
        self._setup_subplots()
        
        # Ajuster l'espacement
        plt.tight_layout()
        plt.subplots_adjust(top=0.93, hspace=0.4, wspace=0.3)
    
    def _setup_subplots(self):
        """Configurer tous les sous-graphiques"""
        
        # Graphique 1: Nouveaux tokens
        self.axes[0].set_title('🆕 Nouveaux Tokens (5m)', color='cyan')
        self.axes[0].set_ylabel('Nombre')
        self.axes[0].grid(True, alpha=0.3)
        
        # Graphique 2: Transactions
        self.axes[1].set_title('📈 Transactions (5m)', color='green')
        self.axes[1].set_ylabel('Nombre')
        self.axes[1].grid(True, alpha=0.3)
        
        # Graphique 3: Updates de tokens
        self.axes[2].set_title('🔄 Token Updates (5m)', color='orange')
        self.axes[2].set_ylabel('Nombre')
        self.axes[2].grid(True, alpha=0.3)
        
        # Graphique 4: API Calls Volume
        self.axes[3].set_title('🌐 API Calls Volume (5m)', color='lightblue')
        self.axes[3].set_ylabel('Calls/min')
        self.axes[3].grid(True, alpha=0.3)
        
        # Graphique 5: API Success Rate
        self.axes[4].set_title('✅ API Success Rate (%)', color='lightgreen')
        self.axes[4].set_ylabel('Success Rate (%)')
        self.axes[4].set_ylim(0, 100)
        self.axes[4].grid(True, alpha=0.3)
        
        # Graphique 6: API Response Times
        self.axes[5].set_title('⏱️ API Response Times (ms)', color='yellow')
        self.axes[5].set_ylabel('Avg Response Time (ms)')
        self.axes[5].grid(True, alpha=0.3)
        
        # Graphique 7: Snapshots d'historique
        self.axes[6].set_title('📊 Snapshots créés (5m)', color='purple')
        self.axes[6].set_ylabel('Nombre')
        self.axes[6].grid(True, alpha=0.3)
        
        # Graphique 8: Santé du système
        self.axes[7].set_title('🏥 Santé Système (%)', color='magenta')
        self.axes[7].set_ylabel('Pourcentage')
        self.axes[7].set_ylim(0, 100)
        self.axes[7].grid(True, alpha=0.3)
        
        # Graphique 9: Volume et wallets
        self.axes[8].set_title('👥💰 Wallets & Volume', color='gold')
        self.axes[8].set_ylabel('Nombre/USD')
        self.axes[8].grid(True, alpha=0.3)
        
        # Configuration des axes X pour tous
        for ax in self.axes:
            ax.tick_params(axis='x', rotation=45)
            ax.xaxis.set_major_formatter(DateFormatter('%H:%M:%S'))
    
    def add_data_point(self, snapshot: MetricsSnapshot):
        """Ajouter un nouveau point de données"""
        self.data_history.append(snapshot)
    
    def update_graphs(self, frame=None):
        """Mettre à jour tous les graphiques"""
        if len(self.data_history) < 2:
            return
        
        # Extraire les données pour les graphiques
        timestamps = [point.timestamp for point in self.data_history]
        
        # Données système existantes
        new_tokens = [point.metrics_5m.new_tokens for point in self.data_history]
        transactions = [point.metrics_5m.new_transactions for point in self.data_history]
        updates = [point.metrics_5m.token_updates for point in self.data_history]
        snapshots = [point.metrics_5m.history_snapshots for point in self.data_history]
        completeness = [point.system_health.data_completeness_rate for point in self.data_history]
        freshness = [point.system_health.freshness_rate for point in self.data_history]
        wallets = [point.metrics_5m.unique_wallets for point in self.data_history]
        volume = [point.metrics_5m.total_volume_usd for point in self.data_history]
        
        # NOUVEAU: Données API
        api_calls_per_min = [point.api_metrics_5m.calls_per_minute for point in self.data_history]
        api_success_rate = [point.api_metrics_5m.success_rate for point in self.data_history]
        api_response_time = [point.api_metrics_5m.avg_response_time for point in self.data_history]
        
        # Nettoyer et redessiner chaque graphique
        for ax in self.axes:
            ax.clear()
        
        # Reconfigurer les sous-graphiques
        self._setup_subplots()
        
        # Graphique 1: Nouveaux tokens
        self.axes[0].plot(timestamps, new_tokens, 'cyan', linewidth=2, marker='o', markersize=3)
        self.axes[0].fill_between(timestamps, new_tokens, alpha=0.3, color='cyan')
        
        # Graphique 2: Transactions
        self.axes[1].plot(timestamps, transactions, 'green', linewidth=2, marker='s', markersize=3)
        self.axes[1].fill_between(timestamps, transactions, alpha=0.3, color='green')
        
        # Graphique 3: Updates
        self.axes[2].plot(timestamps, updates, 'orange', linewidth=2, marker='^', markersize=3)
        self.axes[2].fill_between(timestamps, updates, alpha=0.3, color='orange')
        
        # Graphique 4: API Calls per minute
        self.axes[3].plot(timestamps, api_calls_per_min, 'lightblue', linewidth=2, marker='o', markersize=3)
        self.axes[3].fill_between(timestamps, api_calls_per_min, alpha=0.3, color='lightblue')
        
        # Graphique 5: API Success Rate
        self.axes[4].plot(timestamps, api_success_rate, 'lightgreen', linewidth=2, marker='s', markersize=3)
        self.axes[4].fill_between(timestamps, api_success_rate, alpha=0.3, color='lightgreen')
        self.axes[4].set_ylim(0, 100)
        
        # Graphique 6: API Response Times
        self.axes[5].plot(timestamps, api_response_time, 'yellow', linewidth=2, marker='^', markersize=3)
        self.axes[5].fill_between(timestamps, api_response_time, alpha=0.3, color='yellow')
        
        # Graphique 7: Snapshots
        self.axes[6].plot(timestamps, snapshots, 'purple', linewidth=2, marker='d', markersize=3)
        self.axes[6].fill_between(timestamps, snapshots, alpha=0.3, color='purple')
        
        # Graphique 8: Santé du système (2 lignes)
        self.axes[7].plot(timestamps, completeness, 'magenta', linewidth=2, marker='o', markersize=3, label='Complétude')
        self.axes[7].plot(timestamps, freshness, 'lime', linewidth=2, marker='s', markersize=3, label='Fraîcheur')
        self.axes[7].legend(loc='upper right')
        self.axes[7].set_ylim(0, 100)
        
        # Graphique 9: Wallets et Volume (double axe Y)
        ax9_twin = self.axes[8].twinx()
        line1 = self.axes[8].plot(timestamps, wallets, 'gold', linewidth=2, marker='o', markersize=3, label='Wallets')
        line2 = ax9_twin.plot(timestamps, volume, 'orange', linewidth=2, marker='s', markersize=3, label='Volume ($)')
        
        self.axes[8].set_ylabel('Wallets', color='gold')
        ax9_twin.set_ylabel('Volume (USD)', color='orange')
        
        # Légende combinée
        lines = line1 + line2
        labels = [l.get_label() for l in lines]
        self.axes[8].legend(lines, labels, loc='upper left')
        
        # Ajuster les limites des axes X pour tous
        for ax in self.axes:
            if timestamps:
                ax.set_xlim(timestamps[0], timestamps[-1])
        
        # Mettre à jour le titre avec les dernières valeurs
        if self.data_history:
            last_point = self.data_history[-1]
            title = f'📊 System + API Metrics - {last_point.timestamp.strftime("%H:%M:%S")} - '
            title += f'🆕 {last_point.metrics_5m.new_tokens} tokens | '
            title += f'📈 {last_point.metrics_5m.new_transactions} tx | '
            title += f'🌐 {last_point.api_metrics_5m.calls_per_minute:.1f} API/min | '
            title += f'✅ {last_point.api_metrics_5m.success_rate:.1f}% success'
            self.fig.suptitle(title, fontsize=14, color='white')
        
        plt.draw()
    
    def start_animation(self, interval: int = 30000):  # interval en millisecondes
        """Démarrer l'animation automatique"""
        self.running = True
        self.anim = animation.FuncAnimation(
            self.fig, 
            self.update_graphs, 
            interval=interval,
            blit=False,
            cache_frame_data=False
        )
        return self.anim
    
    def stop_animation(self):
        """Arrêter l'animation"""
        self.running = False
        if hasattr(self, 'anim'):
            self.anim.event_source.stop()
    
    def show(self):
        """Afficher la fenêtre des graphiques"""
        plt.show()
    
    def save_snapshot(self, filename: str):
        """Sauvegarder le graphique actuel"""
        self.fig.savefig(filename, dpi=300, bbox_inches='tight', facecolor='black')
        print(f"📸 Graphique sauvegardé: {filename}")

class TokenMetricsCollector:
    """Collecteur de métriques pour le système de tokens avec support graphiques et API"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.current_timestamp = int(time.time())
        self.graphs = None
        self.graph_thread = None
    
    def get_db_connection(self) -> sqlite3.Connection:
        """Obtenir une connexion à la base de données"""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn
    
    def get_api_metrics(self, window_seconds: int, window_name: str) -> ApiMetrics:
        """NOUVEAU: Obtenir les métriques des API calls"""
        cutoff_time = self.current_timestamp - window_seconds
        
        metrics = ApiMetrics(window=window_name)
        
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 1. Stats globales des API calls
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_calls,
                        SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful_calls,
                        SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed_calls,
                        AVG(duration_ms) as avg_duration
                    FROM api_metrics 
                    WHERE call_timestamp > ?
                """, (cutoff_time,))
                
                result = cursor.fetchone()
                if result:
                    metrics.total_calls = result[0] or 0
                    metrics.successful_calls = result[1] or 0
                    metrics.failed_calls = result[2] or 0
                    metrics.avg_response_time = result[3] or 0.0
                    
                    # Calculer le taux de succès
                    if metrics.total_calls > 0:
                        metrics.success_rate = (metrics.successful_calls / metrics.total_calls) * 100
                    
                    # Calculer calls per minute
                    metrics.calls_per_minute = (metrics.total_calls / window_seconds) * 60
                
                # 2. Breakdown par API
                cursor.execute("""
                    SELECT api_name, COUNT(*) as call_count
                    FROM api_metrics 
                    WHERE call_timestamp > ?
                    GROUP BY api_name
                    ORDER BY call_count DESC
                """, (cutoff_time,))
                
                metrics.api_breakdown = dict(cursor.fetchall())
                
                # 3. APIs les plus lentes
                cursor.execute("""
                    SELECT api_name, AVG(duration_ms) as avg_duration
                    FROM api_metrics 
                    WHERE call_timestamp > ? AND success = 1
                    GROUP BY api_name
                    HAVING COUNT(*) >= 3  -- Au moins 3 appels
                    ORDER BY avg_duration DESC
                    LIMIT 5
                """, (cutoff_time,))
                
                metrics.slowest_apis = [(row[0], row[1]) for row in cursor.fetchall()]
                
        except Exception as e:
            print(f"Erreur lors de la collecte des métriques API pour {window_name}: {e}")
        
        return metrics
    
    def get_time_window_metrics(self, window_seconds: int, window_name: str) -> TimeWindowMetrics:
        """Obtenir les métriques pour une fenêtre de temps"""
        cutoff_time = self.current_timestamp - window_seconds
        cutoff_datetime = datetime.fromtimestamp(cutoff_time).strftime('%Y-%m-%d %H:%M:%S')
        
        metrics = TimeWindowMetrics(window=window_name)
        
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
                
                # 8. Estimation des appels API
                metrics.api_calls_estimated = (metrics.token_updates * 3) + (metrics.new_tokens * 4)
                
        except Exception as e:
            print(f"Erreur lors de la collecte des métriques pour {window_name}: {e}")
        
        return metrics

    def get_system_health(self) -> SystemHealth:
        """Obtenir la santé globale du système"""
        health = SystemHealth()
        
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
                    AND is_dead = 0
                """, (stale_cutoff,))
                health.tokens_stale = cursor.fetchone()[0]
                
                # Tokens morts
                cursor.execute("SELECT COUNT(*) FROM tokens WHERE is_dead = 1")
                health.tokens_dead = cursor.fetchone()[0]
                
                # Tokens flaggés sans données
                cursor.execute("SELECT COUNT(*) FROM tokens WHERE no_data_available = 1")
                health.tokens_flagged_no_data = cursor.fetchone()[0]
                
                # Calcul des taux
                if health.total_tokens > 0:
                    health.data_completeness_rate = (health.tokens_with_complete_data / health.total_tokens) * 100
                    
                    fresh_tokens = health.total_tokens - health.tokens_stale - health.tokens_never_updated - health.tokens_dead
                    health.freshness_rate = max(0, (fresh_tokens / health.total_tokens) * 100)
                
        except Exception as e:
            print(f"Erreur lors de la collecte de la santé système: {e}")
        
        return health

    def get_current_snapshot(self) -> MetricsSnapshot:
        """Obtenir un snapshot complet des métriques actuelles"""
        self.current_timestamp = int(time.time())  # Mise à jour du timestamp
        
        metrics_5m = self.get_time_window_metrics(300, '5m')
        system_health = self.get_system_health()
        api_metrics_5m = self.get_api_metrics(300, '5m')  # NOUVEAU
        
        return MetricsSnapshot(
            timestamp=datetime.now(),
            metrics_5m=metrics_5m,
            system_health=system_health,
            api_metrics_5m=api_metrics_5m  # NOUVEAU
        )

    def print_api_metrics_summary(self, api_metrics: ApiMetrics):
        """NOUVEAU: Afficher un résumé des métriques API"""
        print(f"\n🌐 === API METRICS ({api_metrics.window}) ===")
        print(f"📞 Total calls: {api_metrics.total_calls}")
        print(f"✅ Success rate: {api_metrics.success_rate:.1f}% ({api_metrics.successful_calls}/{api_metrics.total_calls})")
        print(f"⏱️  Avg response: {api_metrics.avg_response_time:.0f}ms")
        print(f"📈 Rate: {api_metrics.calls_per_minute:.1f} calls/min")
        
        if api_metrics.api_breakdown:
            print(f"\n📊 Top APIs:")
            for api_name, count in list(api_metrics.api_breakdown.items())[:5]:
                print(f"   {api_name}: {count} calls")
        
        if api_metrics.slowest_apis:
            print(f"\n🐌 Slowest APIs:")
            for api_name, avg_time in api_metrics.slowest_apis[:3]:
                print(f"   {api_name}: {avg_time:.0f}ms avg")

    def run_continuous_with_graphs(self, refresh_interval: int = 30, save_snapshots: bool = False):
        """Monitoring continu avec graphiques temps réel"""
        if not MATPLOTLIB_AVAILABLE:
            print("❌ matplotlib non disponible. Utilisez --watch au lieu de --graph")
            return
        
        print("🔄 Monitoring continu avec graphiques démarré")
        print(f"⏱️  Intervalle de rafraîchissement: {refresh_interval}s")
        print("📊 Fenêtre graphique en cours d'ouverture...")
        
        # Initialiser les graphiques
        self.graphs = RealTimeGraphs(max_points=CONFIG['graph_config']['max_points'])
        
        # Fonction de mise à jour des données
        def update_data():
            iteration = 0
            try:
                while True:
                    iteration += 1
                    
                    # Obtenir les nouvelles métriques
                    snapshot = self.get_current_snapshot()
                    
                    # Ajouter aux graphiques
                    self.graphs.add_data_point(snapshot)
                    
                    # Log console enrichi avec métriques API
                    print(f"\n🔄 Itération {iteration} - {snapshot.timestamp.strftime('%H:%M:%S')}")
                    print(f"🆕 Tokens: {snapshot.metrics_5m.new_tokens} | "
                          f"📈 TX: {snapshot.metrics_5m.new_transactions} | "
                          f"🔄 Updates: {snapshot.metrics_5m.token_updates} | "
                          f"📊 Snapshots: {snapshot.metrics_5m.history_snapshots}")
                    print(f"🏥 Santé: {snapshot.system_health.data_completeness_rate:.1f}% complétude | "
                          f"{snapshot.system_health.freshness_rate:.1f}% fraîcheur")
                    print(f"🌐 API: {snapshot.api_metrics_5m.total_calls} calls | "
                          f"✅ {snapshot.api_metrics_5m.success_rate:.1f}% success | "
                          f"⏱️  {snapshot.api_metrics_5m.avg_response_time:.0f}ms avg | "
                          f"📈 {snapshot.api_metrics_5m.calls_per_minute:.1f}/min")
                    
                    # Afficher détails API si demandé en mode verbose
                    if iteration % 5 == 0:  # Tous les 5 cycles
                        self.print_api_metrics_summary(snapshot.api_metrics_5m)
                    
                    # Sauvegarder snapshot si demandé
                    if save_snapshots and iteration % 10 == 0:  # Tous les 10 cycles
                        filename = f"metrics_snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                        self.graphs.save_snapshot(filename)
                    
                    time.sleep(refresh_interval)
                    
            except KeyboardInterrupt:
                print("\n👋 Monitoring arrêté")
            except Exception as e:
                print(f"\n❌ Erreur pendant le monitoring: {e}")
            finally:
                if self.graphs:
                    self.graphs.stop_animation()
        
        # Démarrer le thread de mise à jour des données
        self.graph_thread = threading.Thread(target=update_data, daemon=True)
        self.graph_thread.start()
        
        # Démarrer l'animation automatique
        anim = self.graphs.start_animation(interval=refresh_interval * 1000)
        
        # Afficher les graphiques (bloquant)
        try:
            self.graphs.show()
        except KeyboardInterrupt:
            print("\n👋 Fenêtre graphique fermée")
        finally:
            if self.graphs:
                self.graphs.stop_animation()

    def run_continuous_console(self, refresh_interval: int = 30):
        """Mode surveillance console avec métriques API"""
        print("🔄 Mode surveillance console démarré")
        print(f"⏱️  Intervalle de rafraîchissement: {refresh_interval}s")
        print("Press Ctrl+C to stop\n")
        
        iteration = 0
        try:
            while True:
                iteration += 1
                
                # Obtenir snapshot
                snapshot = self.get_current_snapshot()
                
                # Affichage console
                print(f"\n{'='*80}")
                print(f"🔄 ITERATION {iteration} - {snapshot.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"{'='*80}")
                
                # Métriques système
                print(f"\n📊 SYSTÈME (5min):")
                print(f"   🆕 Nouveaux tokens: {snapshot.metrics_5m.new_tokens}")
                print(f"   📈 Nouvelles transactions: {snapshot.metrics_5m.new_transactions}")
                print(f"   🔄 Token updates: {snapshot.metrics_5m.token_updates}")
                print(f"   📊 Snapshots créés: {snapshot.metrics_5m.history_snapshots}")
                print(f"   👥 Wallets uniques: {snapshot.metrics_5m.unique_wallets}")
                print(f"   💰 Volume total: ${snapshot.metrics_5m.total_volume_usd:,.2f}")
                
                # Santé du système
                print(f"\n🏥 SANTÉ SYSTÈME:")
                print(f"   📋 Total tokens: {snapshot.system_health.total_tokens}")
                print(f"   ✅ Données complètes: {snapshot.system_health.tokens_with_complete_data} "
                      f"({snapshot.system_health.data_completeness_rate:.1f}%)")
                print(f"   🔄 Fraîcheur: {snapshot.system_health.freshness_rate:.1f}%")
                print(f"   💀 Tokens morts: {snapshot.system_health.tokens_dead}")
                print(f"   🚫 Flaggés no-data: {snapshot.system_health.tokens_flagged_no_data}")
                
                # Métriques API
                self.print_api_metrics_summary(snapshot.api_metrics_5m)
                
                print(f"\n⏳ Attente {refresh_interval}s...")
                time.sleep(refresh_interval)
                
        except KeyboardInterrupt:
            print("\n👋 Monitoring console arrêté")

    def generate_api_report(self, window: str = '1h') -> Dict:
        """NOUVEAU: Générer un rapport détaillé des API"""
        window_seconds = CONFIG['time_windows'].get(window, 3600)
        api_metrics = self.get_api_metrics(window_seconds, window)
        
        # Obtenir des statistiques détaillées
        cutoff_time = self.current_timestamp - window_seconds
        
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Statistiques par heure
                cursor.execute("""
                    SELECT 
                        strftime('%H', datetime(call_timestamp, 'unixepoch')) as hour,
                        COUNT(*) as calls,
                        AVG(duration_ms) as avg_duration,
                        SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as success_rate
                    FROM api_metrics 
                    WHERE call_timestamp > ?
                    GROUP BY hour
                    ORDER BY hour
                """, (cutoff_time,))
                
                hourly_stats = [dict(row) for row in cursor.fetchall()]
                
                # Top erreurs
                cursor.execute("""
                    SELECT 
                        api_name, 
                        error_message, 
                        COUNT(*) as error_count
                    FROM api_metrics 
                    WHERE call_timestamp > ? AND success = 0 AND error_message IS NOT NULL
                    GROUP BY api_name, error_message
                    ORDER BY error_count DESC
                    LIMIT 10
                """, (cutoff_time,))
                
                top_errors = [dict(row) for row in cursor.fetchall()]
                
                # Distribution des temps de réponse
                cursor.execute("""
                    SELECT 
                        api_name,
                        MIN(duration_ms) as min_duration,
                        AVG(duration_ms) as avg_duration,
                        MAX(duration_ms) as max_duration,
                        COUNT(*) as call_count
                    FROM api_metrics 
                    WHERE call_timestamp > ? AND success = 1
                    GROUP BY api_name
                    ORDER BY avg_duration DESC
                """, (cutoff_time,))
                
                response_times = [dict(row) for row in cursor.fetchall()]
                
        except Exception as e:
            print(f"Erreur lors de la génération du rapport API: {e}")
            hourly_stats = []
            top_errors = []
            response_times = []
        
        return {
            'window': window,
            'summary': {
                'total_calls': api_metrics.total_calls,
                'success_rate': api_metrics.success_rate,
                'avg_response_time': api_metrics.avg_response_time,
                'calls_per_minute': api_metrics.calls_per_minute
            },
            'api_breakdown': api_metrics.api_breakdown,
            'slowest_apis': api_metrics.slowest_apis,
            'hourly_stats': hourly_stats,
            'top_errors': top_errors,
            'response_times': response_times
        }

    def generate_report(self, format_type: str = 'text') -> str:
        """Générer un rapport complet incluant les métriques API"""
        snapshot = self.get_current_snapshot()
        
        if format_type == 'json':
            # Rapport JSON enrichi avec API
            report_data = {
                'timestamp': snapshot.timestamp.isoformat(),
                'system_metrics': {
                    'new_tokens_5m': snapshot.metrics_5m.new_tokens,
                    'new_transactions_5m': snapshot.metrics_5m.new_transactions,
                    'token_updates_5m': snapshot.metrics_5m.token_updates,
                    'history_snapshots_5m': snapshot.metrics_5m.history_snapshots,
                    'unique_wallets_5m': snapshot.metrics_5m.unique_wallets,
                    'total_volume_5m': snapshot.metrics_5m.total_volume_usd
                },
                'system_health': {
                    'total_tokens': snapshot.system_health.total_tokens,
                    'data_completeness_rate': snapshot.system_health.data_completeness_rate,
                    'freshness_rate': snapshot.system_health.freshness_rate,
                    'tokens_dead': snapshot.system_health.tokens_dead,
                    'tokens_flagged_no_data': snapshot.system_health.tokens_flagged_no_data
                },
                'api_metrics': {
                    'total_calls_5m': snapshot.api_metrics_5m.total_calls,
                    'success_rate': snapshot.api_metrics_5m.success_rate,
                    'avg_response_time': snapshot.api_metrics_5m.avg_response_time,
                    'calls_per_minute': snapshot.api_metrics_5m.calls_per_minute,
                    'api_breakdown': snapshot.api_metrics_5m.api_breakdown,
                    'slowest_apis': snapshot.api_metrics_5m.slowest_apis
                },
                'detailed_api_report': self.generate_api_report('1h')
            }
            return json.dumps(report_data, indent=2, ensure_ascii=False)
        
        else:
            # Rapport texte enrichi
            report = []
            report.append("📊 TOKEN SYSTEM METRICS REPORT")
            report.append("=" * 50)
            report.append(f"📅 Generated: {snapshot.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
            report.append("")
            
            # Métriques système
            report.append("🔥 SYSTEM ACTIVITY (Last 5 minutes)")
            report.append("-" * 40)
            report.append(f"🆕 New tokens: {snapshot.metrics_5m.new_tokens}")
            report.append(f"📈 New transactions: {snapshot.metrics_5m.new_transactions}")
            report.append(f"🔄 Token updates: {snapshot.metrics_5m.token_updates}")
            report.append(f"📊 History snapshots: {snapshot.metrics_5m.history_snapshots}")
            report.append(f"👥 Unique wallets: {snapshot.metrics_5m.unique_wallets}")
            report.append(f"💰 Total volume: ${snapshot.metrics_5m.total_volume_usd:,.2f}")
            report.append("")
            
            # Santé système
            report.append("🏥 SYSTEM HEALTH")
            report.append("-" * 40)
            report.append(f"📋 Total tokens: {snapshot.system_health.total_tokens:,}")
            report.append(f"✅ Complete data: {snapshot.system_health.tokens_with_complete_data:,} "
                         f"({snapshot.system_health.data_completeness_rate:.1f}%)")
            report.append(f"🔄 Freshness: {snapshot.system_health.freshness_rate:.1f}%")
            report.append(f"💀 Dead tokens: {snapshot.system_health.tokens_dead:,}")
            report.append(f"🚫 No-data flagged: {snapshot.system_health.tokens_flagged_no_data:,}")
            report.append("")
            
            # Métriques API
            report.append("🌐 API PERFORMANCE (Last 5 minutes)")
            report.append("-" * 40)
            report.append(f"📞 Total calls: {snapshot.api_metrics_5m.total_calls}")
            report.append(f"✅ Success rate: {snapshot.api_metrics_5m.success_rate:.1f}%")
            report.append(f"⏱️  Avg response: {snapshot.api_metrics_5m.avg_response_time:.0f}ms")
            report.append(f"📈 Rate: {snapshot.api_metrics_5m.calls_per_minute:.1f} calls/min")
            report.append("")
            
            if snapshot.api_metrics_5m.api_breakdown:
                report.append("📊 Top APIs:")
                for api_name, count in list(snapshot.api_metrics_5m.api_breakdown.items())[:5]:
                    report.append(f"   • {api_name}: {count} calls")
                report.append("")
            
            if snapshot.api_metrics_5m.slowest_apis:
                report.append("🐌 Slowest APIs:")
                for api_name, avg_time in snapshot.api_metrics_5m.slowest_apis[:3]:
                    report.append(f"   • {api_name}: {avg_time:.0f}ms avg")
                report.append("")
            
            return "\n".join(report)

def main():
    """Point d'entrée principal avec support graphiques et API"""
    parser = argparse.ArgumentParser(
        description='Générateur de métriques pour le système de tokens avec graphiques et monitoring API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples d'utilisation:
  python token_metrics.py                           # Rapport unique
  python token_metrics.py --format json             # Format JSON
  python token_metrics.py --watch                   # Surveillance continue console
  python token_metrics.py --graph                   # Graphiques temps réel
  python token_metrics.py --graph --interval 60     # Graphiques toutes les 60s
  python token_metrics.py --graph --save-snapshots  # Avec sauvegarde d'images
  python token_metrics.py --api-report              # Rapport détaillé API
        """
    )
    
    # Arguments de base
    parser.add_argument('--format', choices=['text', 'json'], default='text', 
                       help='Format de sortie (text ou json)')
    parser.add_argument('--output', type=str, help='Fichier de sortie (optionnel)')
    parser.add_argument('--db', type=str, default=CONFIG['db_path'], 
                       help='Chemin vers la base de données')
    
    # Arguments pour monitoring
    parser.add_argument('--watch', action='store_true', 
                       help='Mode surveillance continue (console)')
    parser.add_argument('--graph', action='store_true',
                       help='Mode graphiques temps réel (nécessite matplotlib)')
    parser.add_argument('--interval', type=int, default=30, 
                       help='Intervalle de rafraîchissement en secondes (défaut: 30)')
    
    # Arguments pour graphiques
    parser.add_argument('--save-snapshots', action='store_true',
                       help='Sauvegarder des images des graphiques périodiquement')
    parser.add_argument('--max-points', type=int, default=50,
                       help='Nombre maximum de points sur les graphiques (défaut: 50)')
    
    # NOUVEAU: Arguments pour API
    parser.add_argument('--api-report', action='store_true',
                       help='Générer un rapport détaillé des API calls')
    parser.add_argument('--api-window', choices=['5m', '1h', '6h', '24h'], default='1h',
                       help='Fenêtre de temps pour le rapport API (défaut: 1h)')
    
    args = parser.parse_args()
    
    # Validation des arguments
    if args.interval < 5:
        print("⚠️  Attention: intervalle minimum recommandé de 5 secondes")
        args.interval = 5
    
    if args.graph and not MATPLOTLIB_AVAILABLE:
        print("❌ matplotlib requis pour les graphiques. Installez avec: pip install matplotlib")
        print("💡 Utilisez --watch pour le mode console")
        return 1
    
    if args.graph and args.watch:
        print("⚠️  Options --graph et --watch mutuellement exclusives. Utilisation de --graph")
        args.watch = False
    
    # Mettre à jour la configuration
    CONFIG['db_path'] = args.db
    CONFIG['graph_config']['max_points'] = args.max_points
    CONFIG['graph_config']['update_interval'] = args.interval
    
    # Vérifier que la base de données existe
    import os
    if not os.path.exists(CONFIG['db_path']):
        print(f"❌ Erreur: Base de données introuvable à {CONFIG['db_path']}")
        print("💡 Vérifiez le chemin ou utilisez --db pour spécifier l'emplacement")
        return 1
    
    try:
        collector = TokenMetricsCollector(CONFIG['db_path'])
        
        if args.api_report:
            # Rapport API détaillé
            print(f"📊 Génération du rapport API ({args.api_window})...")
            api_report = collector.generate_api_report(args.api_window)
            
            if args.format == 'json':
                output = json.dumps(api_report, indent=2, ensure_ascii=False)
            else:
                # Format texte pour rapport API
                lines = []
                lines.append("🌐 API PERFORMANCE DETAILED REPORT")
                lines.append("=" * 50)
                lines.append(f"📅 Window: {api_report['window']}")
                lines.append(f"📞 Total calls: {api_report['summary']['total_calls']}")
                lines.append(f"✅ Success rate: {api_report['summary']['success_rate']:.1f}%")
                lines.append(f"⏱️  Avg response: {api_report['summary']['avg_response_time']:.0f}ms")
                lines.append(f"📈 Rate: {api_report['summary']['calls_per_minute']:.1f} calls/min")
                lines.append("")
                
                if api_report['api_breakdown']:
                    lines.append("📊 API BREAKDOWN:")
                    for api_name, count in api_report['api_breakdown'].items():
                        lines.append(f"   • {api_name}: {count} calls")
                    lines.append("")
                
                if api_report['response_times']:
                    lines.append("⏱️  RESPONSE TIMES:")
                    for api_data in api_report['response_times']:
                        lines.append(f"   • {api_data['api_name']}: "
                                   f"{api_data['avg_duration']:.0f}ms avg "
                                   f"({api_data['min_duration']}-{api_data['max_duration']}ms) "
                                   f"[{api_data['call_count']} calls]")
                    lines.append("")
                
                if api_report['top_errors']:
                    lines.append("❌ TOP ERRORS:")
                    for error_data in api_report['top_errors']:
                        lines.append(f"   • {error_data['api_name']}: "
                                   f"{error_data['error_message']} "
                                   f"({error_data['error_count']} times)")
                
                output = "\n".join(lines)
            
            if args.output:
                with open(args.output, 'w', encoding='utf-8') as f:
                    f.write(output)
                print(f"📄 Rapport sauvegardé dans {args.output}")
            else:
                print(output)
        
        elif args.graph:
            # Mode graphiques temps réel
            print(f"📊 Démarrage des graphiques temps réel avec monitoring API...")
            print(f"📈 Base de données: {CONFIG['db_path']}")
            print(f"⏱️  Intervalle: {args.interval}s")
            print(f"📊 Points max: {args.max_points}")
            print(f"📸 Snapshots: {'Activées' if args.save_snapshots else 'Désactivées'}")
            print("\n" + "─" * 60)
            
            collector.run_continuous_with_graphs(
                refresh_interval=args.interval,
                save_snapshots=args.save_snapshots
            )
        elif args.watch:
            # Mode console
            collector.run_continuous_console(refresh_interval=args.interval)
        else:
            # Génération unique
            print("🔄 Génération du rapport...")
            report = collector.generate_report(args.format)
            
            if args.output:
                with open(args.output, 'w', encoding='utf-8') as f:
                    f.write(report)
                print(f"📄 Rapport sauvegardé dans {args.output}")
            else:
                print(report)
        
        return 0
        
    except KeyboardInterrupt:
        print("\n👋 Arrêt demandé par l'utilisateur")
        return 0
    except Exception as e:
        print(f"❌ Erreur inattendue: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)