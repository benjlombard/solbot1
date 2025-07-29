#!/usr/bin/env python3
"""
🚀 Lanceur Optimisé - Scanner Solana Haute Performance
Débit cible: 5-10 tokens/seconde vs 0.02 actuel
"""

import asyncio
import logging
import argparse
import signal
import sys
from datetime import datetime
import threading
import time

# Importer vos modules optimisés
from system_optimization import (
    apply_system_optimizations, 
    global_cache, 
    global_profiler,
    SYSTEM_CONFIG,
    performance_monitoring_loop
)

# Configuration du logging optimisé
def setup_optimized_logging(log_level: str, whale_log_level: str = 'WARNING', disable_whale_logs: bool = False, whale_log_file: str = "whale_detector.log"):
    """Configuration logging optimisée pour haute performance"""
    
    # Format de log plus compact pour réduire l'overhead
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)s | %(name)s | %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # Handler console avec buffer
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, log_level))
    console_handler.setFormatter(formatter)
    
    # Handler fichier avec rotation pour éviter les gros fichiers
    from logging.handlers import RotatingFileHandler
    file_handler = RotatingFileHandler(
        'solana_scanner_optimized.log',
        maxBytes=50*1024*1024,
        backupCount=3,
        encoding='utf-8'  # Ajout de l'encodage UTF-8
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    
    # === NOUVEAU: Handler séparé pour les whales ===
    whale_file_handler = RotatingFileHandler(
        whale_log_file,
        maxBytes=20*1024*1024,  # Fichier plus petit car plus spécialisé
        backupCount=5,
        encoding='utf-8'
    )
    whale_file_handler.setLevel(getattr(logging, whale_log_level))
    whale_file_handler.setFormatter(logging.Formatter(
        '%(asctime)s | %(levelname)s | 🐋 %(message)s',
        datefmt='%H:%M:%S'
    ))

    # Configuration du logger racine
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    whale_logger_names = ['whale_detector', 'whale_detection', 'whale', 'whales']
    for logger_name in whale_logger_names:
        whale_logger = logging.getLogger(logger_name)
        
        if disable_whale_logs:
            # Complètement désactiver
            whale_logger.setLevel(logging.CRITICAL + 1)  # Au-dessus de CRITICAL
            whale_logger.propagate = False
            whale_logger.handlers.clear()
            logging.info(f"🚫 Whale logs completely disabled for {logger_name}")
        else:
            whale_logger.setLevel(getattr(logging, whale_log_level))
            whale_logger.propagate = False  # IMPORTANT: Empêcher la propagation
            
            # Nettoyer les handlers existants
            whale_logger.handlers.clear()
            
            # *** CHANGEMENT PRINCIPAL: AJOUTER UNIQUEMENT LE HANDLER FICHIER ***
            whale_logger.addHandler(whale_file_handler)
            
            # *** SUPPRIMER CETTE SECTION QUI AJOUTAIT LA CONSOLE ***
            # PAS DE CONSOLE HANDLER, MÊME POUR DEBUG/INFO
            
            logging.info(f"🐋 Whale logs for {logger_name}: {whale_log_level} level -> {whale_log_file} (FILE ONLY)")

    
    # Réduire les logs des libs externes

    console_handler.addFilter(WhaleLogFilter())
    logging.info("🚫 Anti-whale filter applied to console - ALL whale logs go to file ONLY")

    for lib in ['httpx', 'httpcore', 'aiohttp', 'websockets', 'urllib3']:
        logging.getLogger(lib).setLevel(logging.WARNING)
    
    logging.getLogger('solana_monitoring').addFilter(ParsingErrorFilter())

    if disable_whale_logs:
        logging.info("🚫 ALL whale detector logs disabled")
    else:
        logging.info(f"🐋 Whale detector configuration:")
        logging.info(f"   📄 Log level: {whale_log_level}")
        logging.info(f"   📄 Log file: {whale_log_file}")
        logging.info(f"   📺 Console: DISABLED (file only)")
        logging.info(f"   🔒 Mode: FILE ONLY regardless of level")
    
    logging.info("✅ Optimized logging configured")
    logging.info(f"📄 Main logs: solana_scanner_optimized.log")

def test_whale_logging_file_only():
    """Test pour vérifier que les whale logs vont uniquement dans le fichier"""
    import logging
    import os
    
    print("\n=== TEST WHALE LOGGING (FILE ONLY) ===")
    
    # Tester différents loggers whale
    whale_loggers = [
        logging.getLogger('whale_detector'),
        logging.getLogger('whale_detection'), 
        logging.getLogger('whale'),
        logging.getLogger('whales')
    ]
    
    print("📝 Sending test logs to file...")
    for logger in whale_loggers:
        logger.debug(f"🐋 Test DEBUG from {logger.name} - should go to FILE ONLY")
        logger.info(f"🐋 Test INFO from {logger.name} - should go to FILE ONLY")
        logger.warning(f"🐋 Test WARNING from {logger.name} - should go to FILE ONLY")
        logger.error(f"🐋 Test ERROR from {logger.name} - should go to FILE ONLY")
        print(f"✅ Sent logs for {logger.name}")
    
    print("📺 Console: No whale logs should appear above")
    print("📄 File: All whale logs should be in whale_detector.log")
    
    # Vérifier le fichier
    import time
    time.sleep(0.1)
    
    try:
        if os.path.exists('whale_detector.log'):
            with open('whale_detector.log', 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            recent_lines = [line for line in lines if '🐋 Test' in line]
            print(f"📊 Found {len(recent_lines)} test whale logs in file")
            
            if recent_lines:
                print("🔍 Recent whale logs from file:")
                for line in recent_lines[-4:]:
                    print(f"   {line.strip()}")
            else:
                print("⚠️  No test whale logs found in file")
        else:
            print("❌ whale_detector.log file not found!")
    
    except Exception as e:
        print(f"⚠️  Error reading whale file: {e}")
    
    print("=== END TEST ===\n")

class WhaleLogFilter(logging.Filter):
        def filter(self, record):
            # Bloquer TOUS les logs contenant des mots-clés whale dans la console
            message = record.getMessage().lower()
            logger_name = record.name.lower()
            
            # Mots-clés whale à bloquer
            whale_keywords = ['whale', '🐋', 'large transaction', 'big transfer', 'whale detector']
            
            # Si c'est un logger whale ou contient des mots-clés whale
            if any(keyword in logger_name for keyword in ['whale']) or \
               any(keyword in message for keyword in whale_keywords):
                return False  # Bloquer ce log pour la console
            
            return True  # Laisser passer les autres logs

class ParsingErrorFilter(logging.Filter):
    """Filtrer les erreurs de parsing fréquentes mais normales"""
    def filter(self, record):
        message = record.getMessage()
        # Filtrer les erreurs de parsing communes
        if any(phrase in message for phrase in [
            "Error parsing signature",
            "Error parsing transaction", 
            "Error parsing Raydium",
            "No valid transaction data",
            "No transaction data for signature"
        ]):
            return False  # Ne pas logger ces erreurs
        return True

class OptimizedSolanaScanner:
    """Scanner Solana optimisé pour débit maximal"""
    
    def __init__(self, args):
        self.args = args
        self.shutdown_event = asyncio.Event()
        self.tasks = []
        self.stats = {
            'start_time': time.time(),
            'tokens_processed': 0,
            'tokens_enriched': 0,
            'api_calls': 0,
            'errors': 0
        }
        
        # Configuration optimisée basée sur les args
        self.config = {
            'batch_size': args.batch_size,
            'max_concurrent': args.max_concurrent,
            'scan_interval': args.scan_interval,
            'enrichment_interval': args.enrichment_interval,
            'monitoring_interval': args.monitoring_interval
        }
        
    async def start(self):
        """Démarrer le scanner optimisé avec Flask intégré"""
        logging.info("🚀 Starting Optimized Solana Scanner with Dashboard...")
        logging.info(f"📊 Target performance: {self.config['batch_size']} tokens/batch, "
                    f"{self.config['max_concurrent']} concurrent operations")
        
        # 1. Appliquer les optimisations système
        from system_optimization import apply_system_optimizations
        apply_system_optimizations(self.args.database)
        
        # 2. Démarrer le serveur Flask dans un thread séparé
        self._start_flask_server()
        
        # 3. Démarrer l'enrichisseur optimisé
        from solana_monitor_c4 import token_enricher
        await token_enricher.start()
        
        # === NOUVEAU: Configurer le seuil whale ===
        from whale_detector_integration import whale_detector
        whale_detector.whale_threshold = self.args.whale_threshold

        # 4. Importer et configurer le monitoring Solana
        from solana_monitor_c4 import start_monitoring
        
        # 5. Créer toutes les tâches optimisées
        tasks_config = [
            ("solana_monitoring", start_monitoring(self.args.log_level)),
            ("performance_monitoring", self._performance_monitoring_loop()),
            ("stats_reporter", self._stats_reporting_loop()),
            ("enrichment_monitor", self._enrichment_monitoring_loop()),
            ("cache_maintenance", self._cache_maintenance_loop()),
        ]
        
        # Ajouter les tâches conditionnelles
        if self.args.enable_performance_profiling:
            tasks_config.append(("profiler", self._performance_profiling_loop()))
        
        if self.args.enable_auto_scaling:
            tasks_config.append(("auto_scaler", self._auto_scaling_loop()))
        
        # Démarrer toutes les tâches
        for name, coro in tasks_config:
            task = asyncio.create_task(coro, name=name)
            self.tasks.append(task)
            logging.info(f"✅ Started task: {name}")
        
        # Configuration des signaux pour arrêt propre
        self._setup_signal_handlers()
        
        # Afficher les URLs du dashboard
        self._display_dashboard_info()
        
        logging.info("🎯 All systems running - High performance mode enabled!")
        logging.info("📈 Expected throughput: 5-10 tokens/sec (vs 0.02 current)")
        
        # Attendre l'arrêt
        await self.shutdown_event.wait()
        
        # Arrêt propre
        await self.shutdown()

    def _start_flask_server(self):
        """Démarrer le serveur Flask dans un thread séparé"""
        def run_flask():
            try:
                # Importer l'app Flask
                from flask_api_backend import app
                
                # Configuration pour production
                app.config['ENV'] = 'production'
                app.config['DEBUG'] = False
                app.config['TESTING'] = False
                
                # Désactiver les logs Flask verbeux
                import logging as flask_logging
                flask_log = flask_logging.getLogger('werkzeug')
                flask_log.setLevel(flask_logging.WARNING)
                
                # Démarrer le serveur
                app.run(
                    host='0.0.0.0',  # Accessible depuis l'extérieur
                    port=5000,       # Port standard
                    debug=False,     # Pas de debug en production
                    use_reloader=False,  # Éviter les conflits avec threading
                    threaded=True    # Support multi-threading
                )
            except Exception as e:
                logging.error(f"Error starting Flask server: {e}")
        
        # Créer et démarrer le thread Flask
        self.flask_thread = threading.Thread(target=run_flask, daemon=True, name="FlaskServer")
        self.flask_thread.start()
        
        # Attendre que Flask démarre
        import time
        time.sleep(2)
        
        logging.info("🌐 Flask dashboard server started on http://0.0.0.0:5000")

    def _display_dashboard_info(self):
        """Afficher les informations du dashboard"""
        logging.info("=" * 60)
        logging.info("🌐 DASHBOARD ACCESS")
        logging.info("=" * 60)
        logging.info("📊 Main Dashboard:     http://localhost:5000/dashboard")
        logging.info("🎯 Performance:       http://localhost:5000/performance")
        logging.info("💎 Invest Ready:      http://localhost:5000/dashboard/invest-ready")
        logging.info("📈 API Stats:         http://localhost:5000/api/stats")
        logging.info("🔧 Health Check:      http://localhost:5000/api/health")
        logging.info("=" * 60)
        
        # Optionnel : ouvrir automatiquement le navigateur
        if not getattr(self.args, 'no_browser', False):
            try:
                import webbrowser
                webbrowser.open('http://localhost:5000/dashboard')
                logging.info("🌐 Dashboard opened in browser")
            except Exception as e:
                logging.debug(f"Could not open browser: {e}")

    async def _performance_monitoring_loop(self):
        """Boucle de monitoring de performance améliorée"""
        while not self.shutdown_event.is_set():
            try:
                await asyncio.sleep(60)  # Check chaque minute
                
                # Importer les métriques de performance
                try:
                    from performance_monitor import performance_monitor
                    current_metrics = performance_monitor.calculate_current_metrics()
                    
                    # Log les métriques importantes
                    throughput = current_metrics.tokens_updated_5min / 300.0
                    
                    logging.info(
                        f"⚡ Performance: {throughput:.3f} tokens/sec | "
                        f"Queue: {current_metrics.queue_size} | "
                        f"Success: {current_metrics.success_rate:.1f}%"
                    )
                    
                    # Alertes de performance
                    if throughput < 1.0:
                        logging.warning(f"⚠️  Low throughput: {throughput:.3f} tokens/sec")
                    
                    if current_metrics.queue_size > 50:
                        logging.warning(f"⚠️  High queue size: {current_metrics.queue_size}")
                        
                except ImportError:
                    # Fallback si performance_monitor n'est pas disponible
                    logging.debug("Performance monitor not available, using basic stats")
                    
            except Exception as e:
                logging.error(f"Error in performance monitoring: {e}")
    
    def _setup_signal_handlers(self):
        """Configurer les gestionnaires de signaux"""
        def signal_handler(signum, frame):
            logging.info(f"🛑 Received signal {signum}, initiating graceful shutdown...")
            asyncio.create_task(self._trigger_shutdown())
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def _trigger_shutdown(self):
        """Déclencher l'arrêt"""
        self.shutdown_event.set()
    
    async def shutdown(self):
        """Arrêt propre de tous les composants avec Flask"""
        logging.info("🔄 Starting graceful shutdown...")
        
        # Annuler toutes les tâches asyncio
        for task in self.tasks:
            if not task.done():
                task.cancel()
        
        # Attendre l'arrêt des tâches
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        
        # Arrêter l'enrichisseur
        try:
            from solana_monitor_c4 import token_enricher
            await token_enricher.stop()
        except Exception as e:
            logging.debug(f"Error stopping enricher: {e}")
        
        # Note: Le thread Flask se fermera automatiquement car il est en daemon mode
        logging.info("🌐 Flask server will stop automatically (daemon thread)")
        
        # Rapport final
        await self._final_report()
        
        logging.info("✅ Graceful shutdown completed")
        logging.info("📊 Dashboard was available at: http://localhost:5000/dashboard")
    
    async def _stats_reporting_loop(self):
        """Boucle de rapport des statistiques en temps réel"""
        while not self.shutdown_event.is_set():
            try:
                await asyncio.sleep(self.config['monitoring_interval'])
                await self._report_performance_stats()
            except Exception as e:
                logging.error(f"Error in stats reporting: {e}")
    
    async def _report_performance_stats(self):
        """Rapporter les statistiques de performance actuelles"""
        from performance_monitor import performance_monitor
        
        # Métriques depuis le monitor de performance
        current_metrics = performance_monitor.calculate_current_metrics()
        
        runtime = time.time() - self.stats['start_time']
        hours, remainder = divmod(runtime, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        # Calcul du débit actuel
        throughput = current_metrics.tokens_updated_5min / 300.0  # tokens/sec
        
        logging.info("=" * 60)
        logging.info(f"⚡ PERFORMANCE DASHBOARD - Runtime: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}")
        logging.info("=" * 60)
        logging.info(f"🚀 THROUGHPUT")
        logging.info(f"   Current: {throughput:.3f} tokens/sec")
        logging.info(f"   5min:    {current_metrics.tokens_updated_5min} tokens")
        logging.info(f"   1hour:   {current_metrics.tokens_updated_1h} tokens")
        logging.info(f"   Target:  5.000 tokens/sec (improvement: {throughput/0.02:.1f}x)")
        
        logging.info(f"💾 DATABASE")
        logging.info(f"   Total:     {current_metrics.database_size}")
        logging.info(f"   Enriched:  {current_metrics.enriched_tokens}")
        logging.info(f"   Rate:      {(current_metrics.enriched_tokens/current_metrics.database_size*100):.1f}%")
        
        logging.info(f"⚙️  SYSTEM")
        logging.info(f"   Queue:     {current_metrics.queue_size}")
        logging.info(f"   Active:    {current_metrics.active_threads}")
        logging.info(f"   Success:   {current_metrics.success_rate:.1f}%")
        
        # Cache stats
        cache_stats = global_cache.get_stats()
        logging.info(f"💾 CACHE")
        logging.info(f"   Entries:   {cache_stats['total_entries']}")
        logging.info(f"   Hit rate:  {cache_stats['cache_hit_potential']:.1f}%")
        
        logging.info("=" * 60)
        
        # Alertes de performance
        if throughput < 1.0:
            logging.warning(f"⚠️  LOW THROUGHPUT: {throughput:.3f} tokens/sec (target: 5+)")
        
        if current_metrics.success_rate < 85:
            logging.warning(f"⚠️  LOW SUCCESS RATE: {current_metrics.success_rate:.1f}% (target: 95%+)")
    
    async def _enrichment_monitoring_loop(self):
        """Surveiller l'état de l'enrichissement"""
        while not self.shutdown_event.is_set():
            try:
                await asyncio.sleep(60)  # Vérifier chaque minute
                
                # Statistiques de la queue d'enrichissement
                try:
                    from solana_monitor_c4 import token_enricher
                    queue_size = token_enricher.enrichment_queue.qsize()
                    
                    if queue_size > 50:
                        logging.warning(f"⚠️  High enrichment queue: {queue_size} tokens")
                    elif queue_size > 20:
                        logging.info(f"📊 Enrichment queue: {queue_size} tokens")
                    else:
                        logging.debug(f"📊 Enrichment queue: {queue_size} tokens")
                        
                except ImportError as e:
                    logging.debug(f"Token enricher not available for monitoring: {e}")
                except AttributeError as e:
                    logging.debug(f"Token enricher queue not accessible: {e}")
            except Exception as e:
                logging.error(f"Error in enrichment monitoring: {e}")
    
    async def _cache_maintenance_loop(self):
        """Maintenance du cache"""
        while not self.shutdown_event.is_set():
            try:
                await asyncio.sleep(1800)  # Toutes les 30 minutes
                
                # Nettoyer le cache expiré
                before_count = len(global_cache.cache)
                # Le cache se nettoie automatiquement lors des accès
                
                # Rapport de maintenance
                cache_stats = global_cache.get_stats()
                logging.info(f"🧹 Cache maintenance: {cache_stats['total_entries']} entries, "
                           f"{cache_stats['cache_hit_potential']:.1f}% hit potential")
                
            except Exception as e:
                logging.error(f"Error in cache maintenance: {e}")
    
    async def _performance_profiling_loop(self):
        """Profilage de performance détaillé"""
        while not self.shutdown_event.is_set():
            try:
                await asyncio.sleep(600)  # Toutes les 10 minutes
                global_profiler.log_performance_report()
            except Exception as e:
                logging.error(f"Error in performance profiling: {e}")
    
    async def _auto_scaling_loop(self):
        """Auto-scaling basé sur la charge"""
        while not self.shutdown_event.is_set():
            try:
                await asyncio.sleep(300)  # Vérifier toutes les 5 minutes
                
                try:
                    from solana_monitor_c4 import token_enricher
                    queue_size = token_enricher.enrichment_queue.qsize()
                    
                    # Auto-scaling simple basé sur la taille de la queue
                    if queue_size > 75:
                        # Queue très pleine - augmenter le batch size temporairement
                        token_enricher.batch_size = min(20, token_enricher.batch_size + 2)
                        logging.info(f"📈 Auto-scaling UP: batch_size -> {token_enricher.batch_size}")
                        
                    elif queue_size < 10 and token_enricher.batch_size > 10:
                        # Queue vide - réduire le batch size
                        token_enricher.batch_size = max(10, token_enricher.batch_size - 1)
                        logging.info(f"📉 Auto-scaling DOWN: batch_size -> {token_enricher.batch_size}")
                        
                except ImportError as e:
                    logging.debug(f"Token enricher not available for auto-scaling: {e}")
                except AttributeError as e:
                    logging.debug(f"Token enricher attributes not accessible: {e}")
                
            except Exception as e:
                logging.error(f"Error in auto-scaling: {e}")
    
    async def _final_report(self):
        """Rapport final de performance"""
        runtime = time.time() - self.stats['start_time']
        
        logging.info("=" * 80)
        logging.info("📊 FINAL PERFORMANCE REPORT")
        logging.info("=" * 80)
        
        # Métriques finales
        from performance_monitor import performance_monitor
        final_metrics = performance_monitor.get_performance_summary()
        
        logging.info(f"⏱️  RUNTIME: {runtime/3600:.2f} hours")
        logging.info(f"🚀 THROUGHPUT:")
        logging.info(f"   Average: {final_metrics.get('current_throughput', 0):.3f} tokens/sec")
        logging.info(f"   Total updates: {final_metrics.get('total_updates', 0)}")
        logging.info(f"   Success rate: {final_metrics.get('success_rate_overall', 0):.1f}%")
        
        logging.info(f"💾 DATABASE:")
        logging.info(f"   Total tokens: {final_metrics.get('database_total', 0)}")
        logging.info(f"   Enriched: {final_metrics.get('database_enriched', 0)}")
        logging.info(f"   Enrichment rate: {final_metrics.get('enrichment_rate', 0):.1f}%")
        
        # Performance comparison
        current_throughput = final_metrics.get('current_throughput', 0)
        improvement = current_throughput / 0.02 if current_throughput > 0 else 0
        
        logging.info(f"📈 IMPROVEMENT:")
        logging.info(f"   Before: 0.02 tokens/sec")
        logging.info(f"   After:  {current_throughput:.3f} tokens/sec")
        logging.info(f"   Gain:   {improvement:.1f}x faster")
        
        # Recommandations
        if current_throughput < 2.0:
            logging.warning("💡 RECOMMENDATIONS FOR FURTHER IMPROVEMENT:")
            logging.warning("   - Increase batch_size to 20-25")
            logging.warning("   - Add more concurrent connections")
            logging.warning("   - Consider using faster API endpoints")
            logging.warning("   - Implement more aggressive caching")
        
        logging.info("=" * 80)

def main():
    """Point d'entrée principal optimisé"""
    parser = argparse.ArgumentParser(description="Optimized Solana Token Scanner")
    
    # Arguments de base
    parser.add_argument("--database", default="tokens.db", help="Database path")
    parser.add_argument("--log-level", choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], 
                       default='INFO', help="Logging level")
    
    # Arguments de performance
    parser.add_argument("--batch-size", type=int, default=15, 
                       help="Tokens per batch (default: 15)")
    parser.add_argument("--max-concurrent", type=int, default=25,
                       help="Max concurrent operations (default: 25)")
    parser.add_argument("--scan-interval", type=float, default=10.0,
                       help="Scan interval in minutes (default: 10)")
    parser.add_argument("--enrichment-interval", type=float, default=5.0,
                       help="Enrichment check interval in minutes (default: 5)")
    parser.add_argument("--monitoring-interval", type=int, default=120,
                       help="Performance monitoring interval in seconds (default: 120)")
    parser.add_argument("--test-whale-file-only", action="store_true",
                    help="Test that whale logs go ONLY to file (no console)")
    parser.add_argument("--whale-log-level", 
                   choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                   default='ERROR',
                   help="Whale detector log level (default: WARNING)")
    parser.add_argument("--disable-whale-logs", action="store_true",
                    help="Disable whale detection verbose logging")
    parser.add_argument("--whale-threshold", type=int, default=10000,
                    help="Whale detection threshold in USD (default: 10000)")
    parser.add_argument("--whale-log-file", type=str, default="whale_detector.log",
                    help="Whale detector log file path (default: whale_detector.log)")
    # Options avancées
    parser.add_argument("--enable-performance-profiling", action="store_true",
                       help="Enable detailed performance profiling")
    parser.add_argument("--enable-auto-scaling", action="store_true",
                       help="Enable automatic batch size scaling")
    parser.add_argument("--enable-cache-preload", action="store_true",
                       help="Preload Jupiter tokens cache on startup")
    
    # Options de test
    parser.add_argument("--dry-run", action="store_true",
                       help="Run without making actual API calls (testing)")
    parser.add_argument("--benchmark-mode", action="store_true",
                       help="Run in benchmark mode for performance testing")
    
    args = parser.parse_args()
    
    # Configuration du logging optimisé
    setup_optimized_logging(args.log_level, args.whale_log_level, args.disable_whale_logs, args.whale_log_file)
    if args.test_whale_file_only:
        test_whale_logging_file_only()
        return
    # Information de démarrage
    logging.info("🚀 SOLANA TOKEN SCANNER - HIGH PERFORMANCE MODE")
    logging.info("=" * 60)
    logging.info(f"📊 Configuration:")
    logging.info(f"   Batch size: {args.batch_size}")
    logging.info(f"   Max concurrent: {args.max_concurrent}")
    logging.info(f"   Target: 5-10 tokens/sec (vs 0.02 current)")
    logging.info(f"   Expected improvement: 250-500x")
    logging.info("=" * 60)
    
    # Warnings pour configurations non optimales
    if args.batch_size < 10:
        logging.warning(f"⚠️  Small batch size ({args.batch_size}) may reduce performance")
    
    if args.max_concurrent < 20:
        logging.warning(f"⚠️  Low concurrency ({args.max_concurrent}) may limit throughput")
    
    # Créer et démarrer le scanner
    scanner = OptimizedSolanaScanner(args)
    
    try:
        # Utiliser uvloop si disponible pour de meilleures performances
        try:
            import uvloop
            uvloop.install()
            logging.info("✅ uvloop enabled for maximum async performance")
        except ImportError:
            logging.info("⚠️  uvloop not available, using default asyncio")
        
        # Mode benchmark
        if args.benchmark_mode:
            logging.info("🏁 BENCHMARK MODE - Running performance test...")
        
        # Démarrer le scanner
        asyncio.run(scanner.start())
        
    except KeyboardInterrupt:
        logging.info("🛑 Interrupted by user")
    except Exception as e:
        logging.error(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()