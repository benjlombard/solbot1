#!/usr/bin/env python3
"""
📊 Performance Monitor COMPLET - Avec toutes les fonctions nécessaires
Version corrigée avec métrique fiables depuis la base de données
"""

import time
import threading
import sqlite3
import json
from datetime import datetime, timedelta
from collections import deque, defaultdict
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional
import logging

logger = logging.getLogger('performance_monitor')

@dataclass
class MetricSnapshot:
    """Snapshot des métriques à un moment donné"""
    timestamp: float
    tokens_updated_5min: int  # ✅ CORRIGÉ: Depuis la DB
    tokens_updated_1h: int    # ✅ AJOUTÉ: Pour plus de context
    tokens_per_second: float
    avg_update_time: float
    errors_count: int
    queue_size: int
    active_threads: int
    database_size: int
    enriched_tokens: int
    success_rate: float

class PerformanceMonitor:
    """Monitor de performance corrigé - données fiables depuis la DB"""
    
    def __init__(self, database_path: str = "tokens.db"):
        self.database_path = database_path
        self.start_time = time.time()
        
        # Métriques en mémoire (pour les tendances et temps)
        self.update_times = deque(maxlen=100)
        self.api_call_times = defaultdict(lambda: deque(maxlen=100))
        self.api_calls_count = defaultdict(int)
        self.error_count = 0
        self.total_updates = 0
        self.total_errors = 0
        self.enrichment_queue_size = 0
        self.active_enrichment_tasks = 0
        
        # Snapshots pour historique
        self.metric_history = deque(maxlen=50)
        
        # Thread pour monitoring continu
        self.monitoring = True
        self.monitor_thread = None
        
        # Lock pour thread safety
        self.lock = threading.Lock()
    
    def start_monitoring(self):
        """Démarrer le monitoring en arrière-plan"""
        if self.monitor_thread is None or not self.monitor_thread.is_alive():
            self.monitoring = True
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.monitor_thread.start()
            logger.info("📊 Performance monitoring started (DB-based)")
    
    def stop_monitoring(self):
        """Arrêter le monitoring"""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join()
        logger.info("📊 Performance monitoring stopped")
    
    def record_token_update(self, address: str, update_time: float, success: bool = True):
        """Enregistrer une mise à jour de token"""
        with self.lock:
            if success:
                self.update_times.append(update_time)
                self.total_updates += 1
            else:
                self.error_count += 1
                self.total_errors += 1
    
    def record_api_call(self, api_name: str, call_time: float):
        """Enregistrer un appel API"""
        with self.lock:
            self.api_call_times[api_name].append(call_time)
            self.api_calls_count[api_name] += 1
    
    def set_enrichment_queue_size(self, size: int):
        """Mettre à jour la taille de la queue d'enrichissement"""
        with self.lock:
            self.enrichment_queue_size = size
    
    def set_active_enrichment_tasks(self, count: int):
        """Mettre à jour le nombre de tâches d'enrichissement actives"""
        with self.lock:
            self.active_enrichment_tasks = count
    
    def get_database_metrics(self) -> Dict:
        """Récupérer les métriques RÉELLES depuis la base de données"""
        try:
            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            
            # ✅ TOKENS MIS À JOUR dans les 5 dernières minutes (RÉEL)
            cursor.execute("""
                SELECT COUNT(*) FROM tokens 
                WHERE updated_at > datetime('now', '-5 minutes', 'localtime')
                AND updated_at IS NOT NULL
                AND symbol IS NOT NULL 
                AND symbol != 'UNKNOWN' 
                AND symbol != ''
            """)
            tokens_updated_5min = cursor.fetchone()[0]
            
            # ✅ TOKENS MIS À JOUR dans la dernière heure
            cursor.execute("""
                SELECT COUNT(*) FROM tokens 
                WHERE updated_at > datetime('now', '-1 hour', 'localtime')
                AND updated_at IS NOT NULL
                AND symbol IS NOT NULL 
                AND symbol != 'UNKNOWN' 
                AND symbol != ''
            """)
            tokens_updated_1h = cursor.fetchone()[0]
            
            # Total de tokens
            cursor.execute("SELECT COUNT(*) FROM tokens")
            total_tokens = cursor.fetchone()[0]
            
            # Tokens enrichis
            cursor.execute("""
                SELECT COUNT(*) FROM tokens 
                WHERE symbol IS NOT NULL 
                AND symbol != 'UNKNOWN' 
                AND symbol != ''
            """)
            enriched_tokens = cursor.fetchone()[0]
            
            # Tokens avec score élevé
            cursor.execute("SELECT COUNT(*) FROM tokens WHERE invest_score >= 80")
            high_score_tokens = cursor.fetchone()[0]
            
            # Nouveaux tokens (24h)
            cursor.execute("""
                SELECT COUNT(*) FROM tokens 
                WHERE first_discovered_at > datetime('now', '-24 hours', 'localtime')
            """)
            new_tokens_24h = cursor.fetchone()[0]
            
            # Tokens actifs (avec volume)
            cursor.execute("""
                SELECT COUNT(*) FROM tokens 
                WHERE volume_24h > 50000 
                AND is_tradeable = 1
            """)
            active_tokens = cursor.fetchone()[0]
            
            conn.close()
            
            return {
                'tokens_updated_5min': tokens_updated_5min,  # ✅ MÉTRIQUE CLÉE
                'tokens_updated_1h': tokens_updated_1h,
                'total_tokens': total_tokens,
                'enriched_tokens': enriched_tokens,
                'enriched_percentage': (enriched_tokens / total_tokens * 100) if total_tokens > 0 else 0,
                'high_score_tokens': high_score_tokens,
                'new_tokens_24h': new_tokens_24h,
                'active_tokens': active_tokens
            }
        
        except Exception as e:
            logger.error(f"Error getting database metrics: {e}")
            return {
                'tokens_updated_5min': 0,
                'tokens_updated_1h': 0,
                'total_tokens': 0,
                'enriched_tokens': 0,
                'enriched_percentage': 0,
                'high_score_tokens': 0,
                'new_tokens_24h': 0,
                'active_tokens': 0
            }
    
    def get_api_stats(self) -> Dict:
        """Récupérer les statistiques des APIs"""
        with self.lock:
            stats = {}
            for api_name, times in self.api_call_times.items():
                if times:
                    stats[api_name] = {
                        'total_calls': self.api_calls_count[api_name],
                        'avg_time': sum(times) / len(times),
                        'min_time': min(times),
                        'max_time': max(times),
                        'recent_calls': len(times)
                    }
                else:
                    stats[api_name] = {
                        'total_calls': self.api_calls_count[api_name],
                        'avg_time': 0,
                        'min_time': 0,
                        'max_time': 0,
                        'recent_calls': 0
                    }
            return stats
    
    def calculate_current_metrics(self) -> MetricSnapshot:
        """Calculer les métriques actuelles basées sur la DB"""
        with self.lock:
            # ✅ RÉCUPÉRER LES VRAIES DONNÉES DEPUIS LA DB
            db_metrics = self.get_database_metrics()
            
            # Calculer le débit basé sur les vraies données
            tokens_per_second = db_metrics['tokens_updated_5min'] / 300.0  # 5min = 300sec
            
            # Temps moyen d'update (depuis mémoire si disponible)
            avg_update_time = sum(self.update_times) / len(self.update_times) if self.update_times else 0
            
            # Taux de succès (basé sur les compteurs)
            total_operations = self.total_updates + self.total_errors
            success_rate = (self.total_updates / total_operations * 100) if total_operations > 0 else 100.0
            
            return MetricSnapshot(
                timestamp=time.time(),
                tokens_updated_5min=db_metrics['tokens_updated_5min'],  # ✅ VRAI NOMBRE
                tokens_updated_1h=db_metrics['tokens_updated_1h'],
                tokens_per_second=tokens_per_second,
                avg_update_time=avg_update_time,
                errors_count=self.total_errors,
                queue_size=self.enrichment_queue_size,
                active_threads=self.active_enrichment_tasks,
                database_size=db_metrics['total_tokens'],
                enriched_tokens=db_metrics['enriched_tokens'],
                success_rate=success_rate
            )
    
    def _monitor_loop(self):
        """Boucle de monitoring continue"""
        while self.monitoring:
            try:
                # Prendre un snapshot des métriques
                snapshot = self.calculate_current_metrics()
                self.metric_history.append(snapshot)
                
                # Afficher les métriques
                self._display_metrics(snapshot)
                
                # Attendre avant le prochain snapshot
                time.sleep(30)  # Snapshot toutes les 30 secondes
                
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                time.sleep(10)
    
    def _display_metrics(self, snapshot: MetricSnapshot):
        """Afficher les métriques actuelles"""
        runtime = time.time() - self.start_time
        hours, remainder = divmod(runtime, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        api_stats = self.get_api_stats()
        
        print("\n" + "="*80)
        print(f"📊 SOLANA BOT PERFORMANCE - Uptime: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}")
        print("="*80)
        
        # ✅ MÉTRIQUES RÉELLES DEPUIS LA DB
        print(f"🚀 DÉBIT & PERFORMANCE (données réelles DB)")
        print(f"   Tokens mis à jour (5min): {snapshot.tokens_updated_5min:>6} tokens")
        print(f"   Tokens mis à jour (1h)  : {snapshot.tokens_updated_1h:>6} tokens")
        print(f"   Débit actuel            : {snapshot.tokens_per_second:>6.2f} tokens/sec")
        print(f"   Temps moy. update       : {snapshot.avg_update_time:>6.2f} secondes")
        print(f"   Taux de succès          : {snapshot.success_rate:>6.1f}%")
        print(f"   Total updates           : {self.total_updates:>6}")
        print(f"   Total erreurs           : {self.total_errors:>6}")
        
        # Queue et threads
        print(f"\n⚙️  SYSTÈME")
        print(f"   Queue enrichissement    : {snapshot.queue_size:>6}")
        print(f"   Tâches actives          : {snapshot.active_threads:>6}")
        
        # Base de données
        print(f"\n💾 BASE DE DONNÉES")
        print(f"   Total tokens            : {snapshot.database_size:>6}")
        print(f"   Tokens enrichis         : {snapshot.enriched_tokens:>6}")
        enriched_pct = (snapshot.enriched_tokens / snapshot.database_size * 100) if snapshot.database_size > 0 else 0
        print(f"   Taux d'enrichissement   : {enriched_pct:>6.1f}%")
        
        # APIs
        if api_stats:
            print(f"\n🌐 APIS")
            for api_name, stats in api_stats.items():
                print(f"   {api_name:<12}: {stats['total_calls']:>4} calls, "
                      f"moy: {stats['avg_time']:.2f}s, min: {stats['min_time']:.2f}s, max: {stats['max_time']:.2f}s")
        
        # Tendances
        if len(self.metric_history) >= 2:
            prev_snapshot = self.metric_history[-2]
            delta_5min = snapshot.tokens_updated_5min - prev_snapshot.tokens_updated_5min
            delta_1h = snapshot.tokens_updated_1h - prev_snapshot.tokens_updated_1h
            
            trend_symbol = "📈" if delta_5min > 0 else "📉" if delta_5min < 0 else "➡️"
            print(f"\n{trend_symbol} TENDANCE (vs snapshot précédent)")
            print(f"   Δ Updates (5min)        : {delta_5min:>+6}")
            print(f"   Δ Updates (1h)          : {delta_1h:>+6}")
        
        print("="*80)
    
    def get_performance_summary(self) -> Dict:
        """Obtenir un résumé des performances"""
        current = self.calculate_current_metrics()
        runtime = time.time() - self.start_time
        
        return {
            'runtime_hours': runtime / 3600,
            'tokens_updated_5min': current.tokens_updated_5min,  # ✅ MÉTRIQUE PRINCIPALE
            'tokens_updated_1h': current.tokens_updated_1h,
            'current_throughput': current.tokens_per_second,
            'database_total': current.database_size,
            'database_enriched': current.enriched_tokens,
            'enrichment_rate': (current.enriched_tokens / current.database_size * 100) if current.database_size > 0 else 0,
            'success_rate_overall': current.success_rate,
            'avg_update_time': current.avg_update_time,
            'queue_size': current.queue_size,
            'active_tasks': current.active_threads,
            'total_updates': self.total_updates,
            'total_errors': self.total_errors
        }
    
    def export_metrics_json(self, filename: str = None) -> str:
        """Exporter les métriques au format JSON"""
        if filename is None:
            filename = f"solana_bot_metrics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        export_data = {
            'export_time': datetime.now().isoformat(),
            'runtime_seconds': time.time() - self.start_time,
            'current_metrics': asdict(self.calculate_current_metrics()),
            'database_metrics': self.get_database_metrics(),
            'api_stats': self.get_api_stats(),
            'total_updates': self.total_updates,
            'total_errors': self.total_errors,
            'metric_history': [asdict(snapshot) for snapshot in list(self.metric_history)]
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"📊 Metrics exported to {filename}")
        return filename

# Instance globale du monitor
performance_monitor = PerformanceMonitor()

def start_performance_monitoring():
    """Démarrer le monitoring de performance"""
    performance_monitor.start_monitoring()

def stop_performance_monitoring():
    """Arrêter le monitoring de performance"""
    performance_monitor.stop_monitoring()

def record_token_update(address: str, update_time: float, success: bool = True):
    """Enregistrer une mise à jour de token"""
    performance_monitor.record_token_update(address, update_time, success)

def record_api_call(api_name: str, call_time: float):
    """Enregistrer un appel API"""
    performance_monitor.record_api_call(api_name, call_time)

def set_enrichment_queue_size(size: int):
    """Mettre à jour la taille de la queue"""
    performance_monitor.set_enrichment_queue_size(size)

def set_active_enrichment_tasks(count: int):
    """Mettre à jour le nombre de tâches actives"""
    performance_monitor.set_active_enrichment_tasks(count)

def export_performance_report():
    """Exporter un rapport de performance"""
    return performance_monitor.export_metrics_json()

def get_performance_summary():
    """Obtenir un résumé des performances"""
    return performance_monitor.get_performance_summary()

def debug_current_metrics():
    """Debug des métriques actuelles"""
    metrics = performance_monitor.calculate_current_metrics()
    db_metrics = performance_monitor.get_database_metrics()
    
    print("🔍 DEBUG MÉTRIQUES ACTUELLES:")
    print(f"   Tokens 5min (DB): {db_metrics['tokens_updated_5min']}")
    print(f"   Tokens 1h (DB):   {db_metrics['tokens_updated_1h']}")
    print(f"   Total tokens:     {db_metrics['total_tokens']}")
    print(f"   Enrichis:         {db_metrics['enriched_tokens']}")
    print(f"   Débit calculé:    {metrics.tokens_per_second:.2f} tokens/sec")
    print(f"   Updates totales:  {performance_monitor.total_updates}")
    print(f"   Erreurs totales:  {performance_monitor.total_errors}")
    
    return metrics

if __name__ == "__main__":
    # Test du monitor corrigé
    logging.basicConfig(level=logging.INFO)
    
    print("🧪 Test du monitoring corrigé...")
    start_performance_monitoring()
    
    time.sleep(5)
    debug_current_metrics()
    
    time.sleep(30)
    
    export_performance_report()
    stop_performance_monitoring()