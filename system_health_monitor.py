#!/usr/bin/env python3
"""
🩺 System Health Monitor - Tableau de bord de contrôle
Vérifie que tous les composants du système Solana fonctionnent correctement
"""

import sqlite3
import json
import time
import argparse
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import os
import asyncio
import aiohttp
import sys

# Configuration du logging minimal pour ce script
logging.basicConfig(level=logging.WARNING)

@dataclass
class HealthMetrics:
    """Métriques de santé du système"""
    timestamp: str
    
    # Base de données
    total_tokens: int
    tokens_with_symbol: int
    tokens_last_hour: int
    tokens_last_24h: int
    enriched_tokens: int
    
    # Historique
    hist_records_total: int
    hist_records_last_hour: int
    hist_records_last_24h: int
    
    # DexScreener
    dexscreener_tokens: int
    dexscreener_updated_last_hour: int
    
    # Whales
    whale_transactions_total: int
    whale_transactions_last_hour: int
    whale_transactions_last_24h: int
    
    # Scores et qualité
    high_score_tokens: int  # score >= 80
    active_tokens: int      # tradeable
    recent_updates: int     # updated_at dernière heure
    
    # Performance
    avg_enrichment_time: float
    success_rate: float
    
    # Status des services
    flask_api_status: str
    database_status: str
    enricher_queue_size: int

class SystemHealthMonitor:
    """Moniteur de santé du système"""
    
    def __init__(self, database_path: str = "tokens.db", api_url: str = "http://localhost:5000"):
        self.database_path = database_path
        self.api_url = api_url
        self.previous_metrics: Optional[HealthMetrics] = None
        
    def get_database_metrics(self) -> Dict:
        """Récupérer les métriques de la base de données"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            metrics = {}
            
            # === TOKENS PRINCIPAL ===
            cursor.execute("SELECT COUNT(*) FROM tokens")
            metrics['total_tokens'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tokens WHERE symbol IS NOT NULL AND symbol != 'UNKNOWN' AND symbol != ''")
            metrics['tokens_with_symbol'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tokens WHERE first_discovered_at > datetime('now', '-1 hour', 'localtime')")
            metrics['tokens_last_hour'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tokens WHERE first_discovered_at > datetime('now', '-24 hours', 'localtime')")
            metrics['tokens_last_24h'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tokens WHERE updated_at > datetime('now', '-1 hour', 'localtime')")
            metrics['recent_updates'] = cursor.fetchone()[0]
            
            # === TOKENS ENRICHIS ===
            cursor.execute("""
                SELECT COUNT(*) FROM tokens 
                WHERE symbol IS NOT NULL AND symbol != 'UNKNOWN' AND symbol != '' 
                AND invest_score IS NOT NULL AND invest_score > 0
            """)
            metrics['enriched_tokens'] = cursor.fetchone()[0]
            
            # === DEXSCREENER ===
            cursor.execute("SELECT COUNT(*) FROM tokens WHERE dexscreener_price_usd > 0")
            metrics['dexscreener_tokens'] = cursor.fetchone()[0]
            
            cursor.execute("""
                SELECT COUNT(*) FROM tokens 
                WHERE dexscreener_last_dexscreener_update > datetime('now', '-1 hour', 'localtime')
            """)
            metrics['dexscreener_updated_last_hour'] = cursor.fetchone()[0]
            
            # === HISTORIQUE ===
            try:
                cursor.execute("SELECT COUNT(*) FROM tokens_hist")
                metrics['hist_records_total'] = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM tokens_hist WHERE snapshot_timestamp > datetime('now', '-1 hour', 'localtime')")
                metrics['hist_records_last_hour'] = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM tokens_hist WHERE snapshot_timestamp > datetime('now', '-24 hours', 'localtime')")
                metrics['hist_records_last_24h'] = cursor.fetchone()[0]
            except sqlite3.OperationalError:
                # Table tokens_hist n'existe peut-être pas
                metrics['hist_records_total'] = 0
                metrics['hist_records_last_hour'] = 0
                metrics['hist_records_last_24h'] = 0
            
            # === WHALES ===
            try:
                cursor.execute("SELECT COUNT(*) FROM whale_transactions_live")
                metrics['whale_transactions_total'] = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM whale_transactions_live WHERE timestamp > datetime('now', '-1 hour', 'localtime')")
                metrics['whale_transactions_last_hour'] = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM whale_transactions_live WHERE timestamp > datetime('now', '-24 hours', 'localtime')")
                metrics['whale_transactions_last_24h'] = cursor.fetchone()[0]
            except sqlite3.OperationalError:
                # Table whale pas encore créée
                metrics['whale_transactions_total'] = 0
                metrics['whale_transactions_last_hour'] = 0
                metrics['whale_transactions_last_24h'] = 0
            
            # === QUALITÉ ===
            cursor.execute("SELECT COUNT(*) FROM tokens WHERE invest_score >= 80")
            metrics['high_score_tokens'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tokens WHERE is_tradeable = 1")
            metrics['active_tokens'] = cursor.fetchone()[0]
            
            # === PERFORMANCE ===
            cursor.execute("""
                SELECT AVG(
                    CASE 
                        WHEN updated_at IS NOT NULL AND first_discovered_at IS NOT NULL 
                        THEN (julianday(updated_at) - julianday(first_discovered_at)) * 24 * 3600
                        ELSE NULL 
                    END
                ) FROM tokens 
                WHERE updated_at > datetime('now', '-24 hours', 'localtime')
                AND first_discovered_at IS NOT NULL
            """)
            result = cursor.fetchone()[0]
            metrics['avg_enrichment_time'] = result if result else 0.0
            
            # Taux de succès approximatif
            total_recent = metrics['tokens_last_24h']
            enriched_recent = cursor.execute("""
                SELECT COUNT(*) FROM tokens 
                WHERE first_discovered_at > datetime('now', '-24 hours', 'localtime')
                AND symbol IS NOT NULL AND symbol != 'UNKNOWN' AND symbol != ''
            """).fetchone()[0]
            
            metrics['success_rate'] = (enriched_recent / max(1, total_recent)) * 100
            
            return metrics
            
        except Exception as e:
            print(f"❌ Erreur lors de la récupération des métriques DB: {e}")
            return {}
        finally:
            conn.close()
    
    def check_flask_api(self) -> Tuple[str, Dict]:
        """Vérifier l'état de l'API Flask"""
        try:
            response = requests.get(f"{self.api_url}/api/health", timeout=5)
            if response.status_code == 200:
                return "✅ ONLINE", response.json()
            else:
                return f"⚠️ ERROR {response.status_code}", {}
        except requests.exceptions.ConnectionError:
            return "❌ OFFLINE", {}
        except requests.exceptions.Timeout:
            return "⏱️ TIMEOUT", {}
        except Exception as e:
            return f"❌ ERROR: {str(e)}", {}
    
    def check_database_health(self) -> str:
        """Vérifier la santé de la base de données"""
        try:
            conn = sqlite3.connect(self.database_path, timeout=5)
            cursor = conn.cursor()
            
            # Test simple
            cursor.execute("SELECT COUNT(*) FROM tokens LIMIT 1")
            cursor.fetchone()
            
            # Vérifier l'intégrité
            cursor.execute("PRAGMA integrity_check")
            integrity = cursor.fetchone()[0]
            
            conn.close()
            
            if integrity == "ok":
                return "✅ HEALTHY"
            else:
                return f"⚠️ INTEGRITY: {integrity}"
                
        except sqlite3.OperationalError as e:
            return f"❌ OPERATIONAL: {str(e)}"
        except Exception as e:
            return f"❌ ERROR: {str(e)}"
    
    def get_enricher_queue_size(self) -> int:
        """Estimer la taille de la queue d'enrichissement"""
        try:
            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            
            # Tokens récents non enrichis = proxy pour queue size
            cursor.execute("""
                SELECT COUNT(*) FROM tokens 
                WHERE (symbol IS NULL OR symbol = 'UNKNOWN' OR symbol = '')
                AND first_discovered_at > datetime('now', '-2 hours', 'localtime')
            """)
            
            queue_estimate = cursor.fetchone()[0]
            conn.close()
            
            return queue_estimate
            
        except Exception:
            return -1
    
    def collect_metrics(self) -> HealthMetrics:
        """Collecter toutes les métriques"""
        db_metrics = self.get_database_metrics()
        flask_status, flask_data = self.check_flask_api()
        db_status = self.check_database_health()
        queue_size = self.get_enricher_queue_size()
        
        return HealthMetrics(
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            
            # Database
            total_tokens=db_metrics.get('total_tokens', 0),
            tokens_with_symbol=db_metrics.get('tokens_with_symbol', 0),
            tokens_last_hour=db_metrics.get('tokens_last_hour', 0),
            tokens_last_24h=db_metrics.get('tokens_last_24h', 0),
            enriched_tokens=db_metrics.get('enriched_tokens', 0),
            
            # History
            hist_records_total=db_metrics.get('hist_records_total', 0),
            hist_records_last_hour=db_metrics.get('hist_records_last_hour', 0),
            hist_records_last_24h=db_metrics.get('hist_records_last_24h', 0),
            
            # DexScreener
            dexscreener_tokens=db_metrics.get('dexscreener_tokens', 0),
            dexscreener_updated_last_hour=db_metrics.get('dexscreener_updated_last_hour', 0),
            
            # Whales
            whale_transactions_total=db_metrics.get('whale_transactions_total', 0),
            whale_transactions_last_hour=db_metrics.get('whale_transactions_last_hour', 0),
            whale_transactions_last_24h=db_metrics.get('whale_transactions_last_24h', 0),
            
            # Quality
            high_score_tokens=db_metrics.get('high_score_tokens', 0),
            active_tokens=db_metrics.get('active_tokens', 0),
            recent_updates=db_metrics.get('recent_updates', 0),
            
            # Performance
            avg_enrichment_time=db_metrics.get('avg_enrichment_time', 0.0),
            success_rate=db_metrics.get('success_rate', 0.0),
            
            # Services
            flask_api_status=flask_status,
            database_status=db_status,
            enricher_queue_size=queue_size
        )
    
    def display_dashboard(self, metrics: HealthMetrics, show_changes: bool = True):
        """Afficher le tableau de bord"""
        
        def format_change(current: int, previous: int) -> str:
            """Formater le changement avec couleur"""
            if not show_changes or not self.previous_metrics:
                return ""
            
            diff = current - previous
            if diff > 0:
                return f" 📈 (+{diff})"
            elif diff < 0:
                return f" 📉 ({diff})"
            else:
                return f" ➡️ (=)"
        
        def get_status_icon(value: int, threshold_good: int, threshold_warn: int = None) -> str:
            """Icône de statut basée sur les seuils"""
            if threshold_warn and value < threshold_warn:
                return "❌"
            elif value >= threshold_good:
                return "✅"
            else:
                return "⚠️"
        
        # Header
        print("=" * 100)
        print("🩺 SYSTEM HEALTH DASHBOARD")
        print("=" * 100)
        print(f"📅 Timestamp: {metrics.timestamp}")
        print(f"💾 Database: {metrics.database_status}")
        print(f"🌐 Flask API: {metrics.flask_api_status}")
        print()
        
        # === TOKENS PRINCIPAL ===
        print("🎯 TOKENS DATABASE")
        print("-" * 50)
        
        prev = self.previous_metrics
        
        enrichment_rate = (metrics.enriched_tokens / max(1, metrics.total_tokens)) * 100
        
        print(f"📊 Total tokens:        {metrics.total_tokens:,}{format_change(metrics.total_tokens, prev.total_tokens if prev else 0)}")
        print(f"💎 Enriched tokens:     {metrics.enriched_tokens:,} ({enrichment_rate:.1f}%){format_change(metrics.enriched_tokens, prev.enriched_tokens if prev else 0)}")
        print(f"🔤 With symbols:        {metrics.tokens_with_symbol:,}{format_change(metrics.tokens_with_symbol, prev.tokens_with_symbol if prev else 0)}")
        print(f"⭐ High score (≥80):    {metrics.high_score_tokens:,}{format_change(metrics.high_score_tokens, prev.high_score_tokens if prev else 0)}")
        print(f"💰 Active/Tradeable:    {metrics.active_tokens:,}{format_change(metrics.active_tokens, prev.active_tokens if prev else 0)}")
        print()
        
        # === ACTIVITÉ RÉCENTE ===
        print("📈 RECENT ACTIVITY")
        print("-" * 50)
        
        # Indicateurs de santé pour l'activité
        tokens_1h_status = get_status_icon(metrics.tokens_last_hour, 5, 1)
        updates_1h_status = get_status_icon(metrics.recent_updates, 10, 2)
        
        print(f"{tokens_1h_status} New tokens (1h):      {metrics.tokens_last_hour:,}{format_change(metrics.tokens_last_hour, prev.tokens_last_hour if prev else 0)}")
        print(f"📦 New tokens (24h):     {metrics.tokens_last_24h:,}{format_change(metrics.tokens_last_24h, prev.tokens_last_24h if prev else 0)}")
        print(f"{updates_1h_status} Updated tokens (1h):   {metrics.recent_updates:,}{format_change(metrics.recent_updates, prev.recent_updates if prev else 0)}")
        print(f"📊 Success rate:        {metrics.success_rate:.1f}%")
        print(f"⏱️ Avg enrichment:      {metrics.avg_enrichment_time:.1f}s")
        print()
        
        # === DEXSCREENER ===
        print("🔍 DEXSCREENER INTEGRATION")
        print("-" * 50)
        
        dex_coverage = (metrics.dexscreener_tokens / max(1, metrics.total_tokens)) * 100
        dex_status = get_status_icon(metrics.dexscreener_updated_last_hour, 5, 1)
        
        print(f"💹 DexScreener tokens:  {metrics.dexscreener_tokens:,} ({dex_coverage:.1f}% coverage){format_change(metrics.dexscreener_tokens, prev.dexscreener_tokens if prev else 0)}")
        print(f"{dex_status} Updated (1h):         {metrics.dexscreener_updated_last_hour:,}{format_change(metrics.dexscreener_updated_last_hour, prev.dexscreener_updated_last_hour if prev else 0)}")
        print()
        
        # === HISTORIQUE ===
        print("📚 HISTORICAL DATA")
        print("-" * 50)
        
        hist_1h_status = get_status_icon(metrics.hist_records_last_hour, 20, 5)
        
        print(f"📖 Total hist records:  {metrics.hist_records_total:,}{format_change(metrics.hist_records_total, prev.hist_records_total if prev else 0)}")
        print(f"{hist_1h_status} New records (1h):     {metrics.hist_records_last_hour:,}{format_change(metrics.hist_records_last_hour, prev.hist_records_last_hour if prev else 0)}")  
        print(f"📈 New records (24h):    {metrics.hist_records_last_24h:,}{format_change(metrics.hist_records_last_24h, prev.hist_records_last_24h if prev else 0)}")
        print()
        
        # === WHALE DETECTION ===
        print("🐋 WHALE DETECTION")  
        print("-" * 50)
        
        whale_1h_status = get_status_icon(metrics.whale_transactions_last_hour, 2, 0)
        
        print(f"🌊 Total whale txs:     {metrics.whale_transactions_total:,}{format_change(metrics.whale_transactions_total, prev.whale_transactions_total if prev else 0)}")
        print(f"{whale_1h_status} Whale txs (1h):       {metrics.whale_transactions_last_hour:,}{format_change(metrics.whale_transactions_last_hour, prev.whale_transactions_last_hour if prev else 0)}")
        print(f"📊 Whale txs (24h):     {metrics.whale_transactions_last_24h:,}{format_change(metrics.whale_transactions_last_24h, prev.whale_transactions_last_24h if prev else 0)}")
        print()
        
        # === SYSTEM PERFORMANCE ===
        print("⚡ SYSTEM PERFORMANCE")
        print("-" * 50)
        
        queue_status = "✅" if metrics.enricher_queue_size < 20 else ("⚠️" if metrics.enricher_queue_size < 50 else "❌")
        
        print(f"{queue_status} Enricher queue:       {metrics.enricher_queue_size}")
        print(f"📊 Enrichment rate:     {enrichment_rate:.1f}%")
        print(f"⏱️ Avg process time:    {metrics.avg_enrichment_time:.1f}s")
        print()
        
        # === ALERTES ===
        alerts = []
        
        if metrics.tokens_last_hour == 0:
            alerts.append("🚨 CRITIQUE: Aucun nouveau token dans la dernière heure")
        
        if metrics.recent_updates < 5:
            alerts.append("⚠️ WARNING: Peu de mises à jour récentes")
        
        if metrics.enricher_queue_size > 50:
            alerts.append("⚠️ WARNING: Queue d'enrichissement élevée")
        
        if metrics.success_rate < 70:
            alerts.append("⚠️ WARNING: Taux de succès faible")
        
        if metrics.hist_records_last_hour == 0:
            alerts.append("⚠️ WARNING: Pas de nouveaux enregistrements historiques")
        
        if "OFFLINE" in metrics.flask_api_status:
            alerts.append("🚨 CRITIQUE: API Flask hors ligne")
        
        if "ERROR" in metrics.database_status:
            alerts.append("🚨 CRITIQUE: Problème de base de données")
        
        if alerts:
            print("🚨 ALERTS")
            print("-" * 50)
            for alert in alerts:
                print(alert)
            print()
        else:
            print("✅ NO ALERTS - System operating normally")
            print()
        
        # === RECOMMENDATIONS ===
        recommendations = []
        
        if enrichment_rate < 50:
            recommendations.append("💡 Considérer augmenter la fréquence d'enrichissement")
        
        if dex_coverage < 30:
            recommendations.append("💡 Améliorer l'intégration DexScreener")
        
        if metrics.enricher_queue_size > 30:
            recommendations.append("💡 Augmenter la vitesse de traitement des tokens")
        
        if metrics.whale_transactions_last_24h == 0:
            recommendations.append("💡 Vérifier le système de détection whale")
        
        if recommendations:
            print("💡 RECOMMENDATIONS")
            print("-" * 50)
            for rec in recommendations:
                print(rec)
            print()
        
        print("=" * 100)
    
    def get_top_tokens_sample(self, limit: int = 5) -> List[Dict]:
        """Récupérer un échantillon des meilleurs tokens"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute(f"""
                SELECT address, symbol, invest_score, price_usdc, volume_24h, 
                       holders, first_discovered_at, updated_at
                FROM tokens 
                WHERE invest_score IS NOT NULL AND invest_score > 0
                ORDER BY invest_score DESC 
                LIMIT {limit}
            """)
            
            tokens = []
            for row in cursor.fetchall():
                tokens.append({
                    'address': row[0],
                    'symbol': row[1] or 'UNKNOWN',
                    'score': row[2] or 0,
                    'price': row[3] or 0,
                    'volume': row[4] or 0,
                    'holders': row[5] or 0,
                    'discovered': row[6] or 'N/A',
                    'updated': row[7] or 'N/A'
                })
            
            return tokens
            
        except Exception as e:
            print(f"Erreur récupération top tokens: {e}")
            return []
        finally:
            conn.close()
    
    def display_top_tokens(self):
        """Afficher les meilleurs tokens"""
        tokens = self.get_top_tokens_sample(10)
        
        if not tokens:
            return
        
        print("🏆 TOP TOKENS SAMPLE")
        print("-" * 100)
        print(f"{'#':<3} {'Symbol':<12} {'Score':<8} {'Price':<15} {'Volume':<12} {'Holders':<8} {'Address':<10}")
        print("-" * 100)
        
        for i, token in enumerate(tokens, 1):
            print(f"{i:<3} {token['symbol']:<12} {token['score']:<8.1f} ${token['price']:<14.8f} ${token['volume']:<11,.0f} {token['holders']:<8} {token['address'][:8]}...")
        
        print()

def main():
    """Fonction principale"""
    parser = argparse.ArgumentParser(description="🩺 System Health Monitor")
    
    parser.add_argument("--database", default="tokens.db", help="Path to database")
    parser.add_argument("--api-url", default="http://localhost:5000", help="Flask API URL")
    parser.add_argument("--continuous", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=60, help="Update interval in seconds")
    parser.add_argument("--show-tokens", action="store_true", help="Show top tokens sample")
    parser.add_argument("--export-json", type=str, help="Export metrics to JSON file")
    parser.add_argument("--alerts-only", action="store_true", help="Show only alerts and warnings")
    
    args = parser.parse_args()
    
    # Vérifier que la base existe
    if not os.path.exists(args.database):
        print(f"❌ Database not found: {args.database}")
        sys.exit(1)
    
    monitor = SystemHealthMonitor(args.database, args.api_url)
    
    try:
        if args.continuous:
            print(f"🔄 Starting continuous monitoring (interval: {args.interval}s)")
            print("Press Ctrl+C to stop\n")
            
            while True:
                # Clear screen
                os.system('cls' if os.name == 'nt' else 'clear')
                
                metrics = monitor.collect_metrics()
                
                if args.alerts_only:
                    # Mode alertes uniquement
                    if any(["CRITIQUE" in metrics.flask_api_status,
                           "ERROR" in metrics.database_status,
                           metrics.tokens_last_hour == 0,
                           metrics.recent_updates < 5]):
                        monitor.display_dashboard(metrics)
                    else:
                        print(f"✅ System OK - {metrics.timestamp}")
                else:
                    monitor.display_dashboard(metrics)
                
                if args.show_tokens:
                    monitor.display_top_tokens()
                
                if args.export_json:
                    with open(args.export_json, 'w') as f:
                        json.dump(metrics.__dict__, f, indent=2)
                
                monitor.previous_metrics = metrics
                time.sleep(args.interval)
        else:
            # Single run
            metrics = monitor.collect_metrics()
            monitor.display_dashboard(metrics, show_changes=False)
            
            if args.show_tokens:
                monitor.display_top_tokens()
            
            if args.export_json:
                with open(args.export_json, 'w') as f:
                    json.dump(metrics.__dict__, f, indent=2)
                print(f"📁 Metrics exported to: {args.export_json}")
    
    except KeyboardInterrupt:
        print("\n✅ Monitoring stopped by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()