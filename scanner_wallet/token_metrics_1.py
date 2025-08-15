#!/usr/bin/env python3
"""
Système de métriques pour le monitoring des tokens avec graphiques temps réel
Fournit des statistiques détaillées sur l'activité du système avec visualisation
"""

import sqlite3
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import argparse
from collections import deque
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
        'figure_size': (15, 10), # Taille de la fenêtre
        'subplot_rows': 2,      # Nombre de lignes de sous-graphiques
        'subplot_cols': 3,      # Nombre de colonnes de sous-graphiques
    }
}

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

class RealTimeGraphs:
    """Gestionnaire des graphiques temps réel"""
    
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
        self.fig.suptitle('📊 Token System Metrics - Real Time Dashboard', fontsize=16, color='white')
        
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
        
        # Graphique 4: Snapshots d'historique
        self.axes[3].set_title('📊 Snapshots créés (5m)', color='purple')
        self.axes[3].set_ylabel('Nombre')
        self.axes[3].grid(True, alpha=0.3)
        
        # Graphique 5: Santé du système
        self.axes[4].set_title('🏥 Santé Système (%)', color='yellow')
        self.axes[4].set_ylabel('Pourcentage')
        self.axes[4].set_ylim(0, 100)
        self.axes[4].grid(True, alpha=0.3)
        
        # Graphique 6: Volume et wallets
        self.axes[5].set_title('👥💰 Wallets & Volume', color='magenta')
        self.axes[5].set_ylabel('Nombre/USD')
        self.axes[5].grid(True, alpha=0.3)
        
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
        
        # Données pour chaque graphique
        new_tokens = [point.metrics_5m.new_tokens for point in self.data_history]
        transactions = [point.metrics_5m.new_transactions for point in self.data_history]
        updates = [point.metrics_5m.token_updates for point in self.data_history]
        snapshots = [point.metrics_5m.history_snapshots for point in self.data_history]
        completeness = [point.system_health.data_completeness_rate for point in self.data_history]
        freshness = [point.system_health.freshness_rate for point in self.data_history]
        wallets = [point.metrics_5m.unique_wallets for point in self.data_history]
        volume = [point.metrics_5m.total_volume_usd for point in self.data_history]
        
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
        
        # Graphique 4: Snapshots
        self.axes[3].plot(timestamps, snapshots, 'purple', linewidth=2, marker='d', markersize=3)
        self.axes[3].fill_between(timestamps, snapshots, alpha=0.3, color='purple')
        
        # Graphique 5: Santé du système (2 lignes)
        self.axes[4].plot(timestamps, completeness, 'yellow', linewidth=2, marker='o', markersize=3, label='Complétude')
        self.axes[4].plot(timestamps, freshness, 'lime', linewidth=2, marker='s', markersize=3, label='Fraîcheur')
        self.axes[4].legend(loc='upper right')
        self.axes[4].set_ylim(0, 100)
        
        # Graphique 6: Wallets et Volume (double axe Y)
        ax6_twin = self.axes[5].twinx()
        line1 = self.axes[5].plot(timestamps, wallets, 'magenta', linewidth=2, marker='o', markersize=3, label='Wallets')
        line2 = ax6_twin.plot(timestamps, volume, 'gold', linewidth=2, marker='s', markersize=3, label='Volume ($)')
        
        self.axes[5].set_ylabel('Wallets', color='magenta')
        ax6_twin.set_ylabel('Volume (USD)', color='gold')
        
        # Légende combinée
        lines = line1 + line2
        labels = [l.get_label() for l in lines]
        self.axes[5].legend(lines, labels, loc='upper left')
        
        # Ajuster les limites des axes X pour tous
        for ax in self.axes:
            if timestamps:
                ax.set_xlim(timestamps[0], timestamps[-1])
        
        # Mettre à jour le titre avec la dernière valeur
        if self.data_history:
            last_point = self.data_history[-1]
            title = f'📊 Token System Metrics - {last_point.timestamp.strftime("%H:%M:%S")} - '
            title += f'🆕 {last_point.metrics_5m.new_tokens} tokens | '
            title += f'📈 {last_point.metrics_5m.new_transactions} tx | '
            title += f'🏥 {last_point.system_health.data_completeness_rate:.1f}%'
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
    """Collecteur de métriques pour le système de tokens avec support graphiques"""
    
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
        
        return MetricsSnapshot(
            timestamp=datetime.now(),
            metrics_5m=metrics_5m,
            system_health=system_health
        )

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
                    
                    # Log console
                    print(f"\n🔄 Itération {iteration} - {snapshot.timestamp.strftime('%H:%M:%S')}")
                    print(f"🆕 Tokens: {snapshot.metrics_5m.new_tokens} | "
                          f"📈 TX: {snapshot.metrics_5m.new_transactions} | "
                          f"🔄 Updates: {snapshot.metrics_5m.token_updates} | "
                          f"📊 Snapshots: {snapshot.metrics_5m.history_snapshots}")
                    print(f"🏥 Santé: {snapshot.system_health.data_completeness_rate:.1f}% complétude | "
                          f"{snapshot.system_health.freshness_rate:.1f}% fraîcheur")
                    
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

    def generate_report(self, format_type: str = 'text') -> str:
        """Générer un rapport complet (méthodes existantes conservées)"""
        # Code existant conservé...
        pass

def main():
    """Point d'entrée principal avec support graphiques"""
    parser = argparse.ArgumentParser(
        description='Générateur de métriques pour le système de tokens avec graphiques',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples d'utilisation:
  python token_metrics.py                           # Rapport unique
  python token_metrics.py --format json             # Format JSON
  python token_metrics.py --watch                   # Surveillance continue
  python token_metrics.py --graph                   # Graphiques temps réel
  python token_metrics.py --graph --interval 60     # Graphiques toutes les 60s
  python token_metrics.py --graph --save-snapshots  # Avec sauvegarde d'images
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
        
        if args.graph:
            # Mode graphiques temps réel
            print(f"📊 Démarrage des graphiques temps réel...")
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
            # Mode console existant
            # Utiliser les méthodes existantes...
            pass
        else:
            # Génération unique
            print("🔄 Génération du rapport...")
            # Utiliser generate_report existant...
            pass
        
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