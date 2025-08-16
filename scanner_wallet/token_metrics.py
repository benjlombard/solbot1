#!/usr/bin/env python3
"""
Système de métriques pour le monitoring des tokens
Fournit des statistiques détaillées sur l'activité du système
"""

import sqlite3
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass
import argparse

# Configuration
CONFIG = {
    'db_path': 'solana_wallet_monitor.db',
    'time_windows': {
        '5m': 300,      # 5 minutes
        '1h': 3600,     # 1 heure
        '6h': 21600,    # 6 heures
        '24h': 86400,   # 24 heures
        '7d': 604800,   # 7 jours
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
    # Nouvelles métriques
    tokens_recently_updated: int = 0  # updated_at > now-5min
    tokens_outdated: int = 0          # updated_at < now-5min (excluant no_data et UNK)
    tokens_unknown_symbol: int = 0    # symbol LIKE 'UNK%'
    tokens_no_data_available: int = 0 # no_data_available = 1
    data_completeness_rate: float = 0.0
    freshness_rate: float = 0.0

class TokenMetricsCollector:
    """Collecteur de métriques pour le système de tokens"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.current_timestamp = int(time.time())
    
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
                
                # 8. Estimation des appels API (basée sur les mises à jour)
                # Approximation : 1 token update = ~3 API calls (DexScreener + Rugcheck + éventuellement Pump.fun)
                metrics.api_calls_estimated = (metrics.token_updates * 3) + (metrics.new_tokens * 4)
                
        except Exception as e:
            print(f"Erreur lors de la collecte des métriques pour {window_name}: {e}")
        
        return metrics
    
    def run_continuous_with_history(self, refresh_interval: int = 30, quick_mode: bool = False, 
                               alert_threshold: int = 0, save_history: bool = False):
        """Monitoring continu avec historique (sans clear screen)"""
        print("🔄 Monitoring continu avec historique démarré")
        
        history_file = None
        if save_history:
            history_file = f"metrics_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            print(f"📝 Historique sauvegardé dans: {history_file}")
        
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
                    
                    # Sauvegarder l'historique si demandé
                    if save_history and history_file:
                        with open(history_file, 'a', encoding='utf-8') as f:
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
                    
                    if save_history and history_file:
                        with open(history_file, 'a', encoding='utf-8') as f:
                            f.write(f"{datetime.now().isoformat()} - Tokens: {time_metrics.new_tokens}, TX: {time_metrics.new_transactions}, Updates: {time_metrics.token_updates}\n")
                
                # Alertes si configurées
                if alert_threshold > 0:
                    metrics_5m = self.get_time_window_metrics(300, '5m')
                    if metrics_5m.new_tokens >= alert_threshold:
                        alert_msg = f"🚨 ALERTE: {metrics_5m.new_tokens} nouveaux tokens détectés!"
                        print(alert_msg)
                        if save_history and history_file:
                            with open(history_file, 'a', encoding='utf-8') as f:
                                f.write(f"{datetime.now().isoformat()} - {alert_msg}\n")
                
                time.sleep(refresh_interval)
                
        except KeyboardInterrupt:
            print("\n👋 Monitoring arrêté")
        except Exception as e:
            print(f"\n❌ Erreur pendant le monitoring: {e}")

    def run_continuous_monitoring(self, refresh_interval: int = 30, quick_mode: bool = False, alert_threshold: int = 0):
        """Monitoring en continu avec affichage mis à jour"""
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
                    
                    # Alertes si configurées
                    if alert_threshold > 0:
                        metrics_5m = self.get_time_window_metrics(300, '5m')
                        if metrics_5m.new_tokens >= alert_threshold:
                            print(f"\n🚨 ALERTE: {metrics_5m.new_tokens} nouveaux tokens détectés (seuil: {alert_threshold})")
                else:
                    report = self.generate_report('text')
                    print(report)
                    
                    # Alertes si configurées
                    if alert_threshold > 0:
                        metrics_5m = self.get_time_window_metrics(300, '5m')
                        if metrics_5m.new_tokens >= alert_threshold:
                            print(f"\n🚨 ALERTE: {metrics_5m.new_tokens} nouveaux tokens détectés!")
                
                print(f"\n⏭️  Prochaine mise à jour dans {refresh_interval}s...")
                
                # Attendre avant la prochaine itération
                time.sleep(refresh_interval)
                
        except KeyboardInterrupt:
            print("\n\n👋 Monitoring arrêté par l'utilisateur")
        except Exception as e:
            print(f"\n❌ Erreur pendant le monitoring: {e}")

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
                
                # === NOUVELLES MÉTRIQUES ===
                
                # Tokens récemment mis à jour (updated_at > now - 5 minutes)
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens 
                    WHERE updated_at > datetime('now', '-5 minutes')
                    AND no_data_available != 1 
                    AND (symbol NOT LIKE 'UNK%' OR symbol IS NULL)
                """)
                health.tokens_recently_updated = cursor.fetchone()[0]
                
                # Tokens obsolètes (updated_at < now - 5 minutes)
                # Excluant no_data_available = 1 et symbol LIKE 'UNK%'
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens 
                    WHERE updated_at < datetime('now', '-5 minutes')
                    AND no_data_available != 1 
                    AND (symbol NOT LIKE 'UNK%' OR symbol IS NULL)
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
                
                # Calcul des taux
                if health.total_tokens > 0:
                    health.data_completeness_rate = (health.tokens_with_complete_data / health.total_tokens) * 100
                    
                    fresh_tokens = health.total_tokens - health.tokens_stale - health.tokens_never_updated - health.tokens_dead
                    health.freshness_rate = max(0, (fresh_tokens / health.total_tokens) * 100)
                
        except Exception as e:
            print(f"Erreur lors de la collecte de la santé système: {e}")
        
        return health
    
    def get_top_active_tokens(self, limit: int = 10) -> List[Dict]:
        """Obtenir les tokens les plus actifs récemment"""
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
                
                return results
                
        except Exception as e:
            print(f"Erreur lors de la récupération des tokens actifs: {e}")
            return []
    
    def get_performance_metrics(self) -> Dict:
        """Obtenir les métriques de performance du système"""
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
                
                return {
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
                
        except Exception as e:
            print(f"Erreur lors de la collecte des métriques de performance: {e}")
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
└─ 🚫 Sans données disponibles: {health.tokens_no_data_available}
            """
        except Exception as e:
            return f"❌ Erreur métriques: {e}"

    def generate_report(self, format_type: str = 'text') -> str:
        """Générer un rapport complet"""
        print("🔄 Collecte des métriques en cours...")
        
        # Collecter toutes les métriques
        time_metrics = {}
        for window_name, window_seconds in CONFIG['time_windows'].items():
            time_metrics[window_name] = self.get_time_window_metrics(window_seconds, window_name)
        
        system_health = self.get_system_health()
        top_tokens = self.get_top_active_tokens(10)
        performance = self.get_performance_metrics()
        
        if format_type == 'json':
            return self._generate_json_report(time_metrics, system_health, top_tokens, performance)
        else:
            return self._generate_text_report(time_metrics, system_health, top_tokens, performance)
    
    def _generate_text_report(self, time_metrics: Dict, system_health: SystemHealth, 
                             top_tokens: List[Dict], performance: Dict) -> str:
        """Générer un rapport texte formaté"""
        report = []
        report.append("=" * 80)
        report.append("🎯 RAPPORT DE MÉTRIQUES DU SYSTÈME DE TOKENS")
        report.append("=" * 80)
        report.append(f"📅 Généré le: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")
        
        # Métriques par fenêtre de temps
        report.append("📊 ACTIVITÉ PAR PÉRIODE")
        report.append("-" * 50)
        
        headers = ["Période", "Tokens", "Transactions", "Updates", "Snapshots", "Wallets", "Volume"]
        row_format = "{:<8} {:<8} {:<12} {:<8} {:<10} {:<8} {:<12}"
        report.append(row_format.format(*headers))
        report.append("-" * 70)
        
        for window_name, metrics in time_metrics.items():
            volume_str = f"${metrics.total_volume_usd:,.0f}" if metrics.total_volume_usd > 0 else "$0"
            report.append(row_format.format(
                window_name,
                metrics.new_tokens,
                metrics.new_transactions,
                metrics.token_updates,
                metrics.history_snapshots,
                metrics.unique_wallets,
                volume_str
            ))
        
        report.append("")
        
        # Santé du système
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
        
        # === NOUVELLES MÉTRIQUES ===
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
        
        # Performance
        if performance:
            report.append("⚡ PERFORMANCE")
            report.append("-" * 20)
            report.append(f"🎯 Délai détection moyen: {performance.get('detection_delay', {}).get('avg_seconds', 0):.1f}s")
            report.append(f"📡 Taux succès API: {performance.get('api_success_rate', {}).get('success_rate_pct', 0):.1f}%")
            report.append(f"📊 Snapshots 24h: {performance.get('historization', {}).get('total_snapshots', 0):,}")
            report.append(f"🔒 Score viabilité moyen: {performance.get('historization', {}).get('avg_viability_score', 0):.1f}/100")
            report.append("")
        
        # Top tokens actifs
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
            'time_window_metrics': {k: v.__dict__ for k, v in time_metrics.items()},
            'system_health': system_health.__dict__,
            'top_active_tokens': top_tokens,
            'performance_metrics': performance
        }
        
        return json.dumps(report_data, indent=2, default=str)

def main():
    """Point d'entrée principal"""
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
    parser.add_argument('--db', type=str, default=CONFIG['db_path'], 
                       help='Chemin vers la base de données')
    
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
        print("⚠️  Attention: intervalle minimum recommandé de 5 secondes")
        args.interval = 5
    
    if args.quick and not args.watch:
        print("⚠️  L'option --quick n'est disponible qu'en mode --watch")
        args.quick = False
    
    # Mettre à jour la configuration
    CONFIG['db_path'] = args.db
    
    # Vérifier que la base de données existe
    import os
    if not os.path.exists(CONFIG['db_path']):
        print(f"❌ Erreur: Base de données introuvable à {CONFIG['db_path']}")
        print("💡 Vérifiez le chemin ou utilisez --db pour spécifier l'emplacement")
        return 1
    
    try:
        collector = TokenMetricsCollector(CONFIG['db_path'])
        
        if args.watch:
            # Mode surveillance continue
            print(f"🔄 Démarrage du monitoring continu...")
            print(f"📊 Base de données: {CONFIG['db_path']}")
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
            print("🔄 Génération du rapport...")
            report = collector.generate_report(args.format)
            
            if args.output:
                with open(args.output, 'w', encoding='utf-8') as f:
                    f.write(report)
                print(f"📝 Rapport sauvegardé dans: {args.output}")
                
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
        
        return 0
        
    except KeyboardInterrupt:
        print("\n👋 Arrêt demandé par l'utilisateur")
        return 0
    except FileNotFoundError as e:
        print(f"❌ Fichier introuvable: {e}")
        return 1
    except sqlite3.Error as e:
        print(f"❌ Erreur base de données: {e}")
        print("💡 Vérifiez que la base de données n'est pas corrompue")
        return 1
    except Exception as e:
        print(f"❌ Erreur inattendue: {e}")
        import traceback
        print("🔍 Détails de l'erreur:")
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit_code = main()
    exit(exit_code)