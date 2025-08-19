#!/usr/bin/env python3
"""
Token Synchronization Service - Main Entry Point
Main entry point for the modular token synchronization service.
"""
import sys
import os
import signal
import threading
import logging
import argparse
import asyncio
import time
from pathlib import Path
from typing import Optional

# Add project root to path
project_root = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(project_root))

# Import configuration and logging from the existing core modules
try:
    from core.tokens_sync_config import get_tokens_sync_config
    from core.logger import get_logger, SolanaWalletLogger
except ImportError as e:
    print(f"❌ Error importing core modules: {e}")
    print("Make sure you're running from the project root directory")
    sys.exit(1)

# Import our modular components
from tokens_sync.services.sync_service import create_sync_service
from tokens_sync.database.connection import DatabaseConnection


class TokenSyncApplication:
    """
    Main application class that orchestrates the token synchronization service
    """
    
    def __init__(self, config_override: Optional[dict] = None):
        self.config = None
        self.logger = None
        self.sync_service = None
        self.config_override = config_override or {}
        self.running = False
        self.stats_thread = None
        self.stats_thread_running = False
        self.shutdown_requested = False
    
    def initialize(self) -> bool:
        """
        Initialize the application components
        
        Returns:
            True if initialization successful, False otherwise
        """
        try:
            # 1. Load configuration
            self.config = get_tokens_sync_config()
            
            # Apply any config overrides
            if self.config_override:
                self._apply_config_overrides()
            
            # 2. Setup logging
            self.logger = self._setup_logging()
            
            self.logger.info("🚀 Initializing Token Sync Service...")
            self.logger.info(f"📊 Database: {self.config.database.get_full_path()}")
            self.logger.info(f"🔧 Config loaded successfully")
            
            # 3. Test database connection
            if not self._test_database_connection():
                return False
            
            # 4. Create sync service
            self.sync_service = create_sync_service(
                config=self.config,
                logger=self.logger
            )
            
            self.logger.info("✅ Application initialization completed successfully")
            return True
            
        except Exception as e:
            error_msg = f"❌ Failed to initialize application: {e}"
            if self.logger:
                self.logger.error(error_msg, exc_info=True)
            else:
                print(error_msg)
            return False
    
    def _apply_config_overrides(self):
        """Apply configuration overrides"""
        if 'sync_interval' in self.config_override:
            self.config.processing.enrichment_interval_seconds = self.config_override['sync_interval']
            if self.logger:
                self.logger.info(f"🔧 Config override: processing.enrichment_interval_seconds = {self.config_override['sync_interval']}")

        if 'batch_size' in self.config_override:
            self.config.apis.dexscreener_batch_size = self.config_override['batch_size']
            if self.logger:
                self.logger.info(f"🔧 Config override: apis.dexscreener_batch_size = {self.config_override['batch_size']}")
    
    def _setup_logging(self) -> logging.Logger:
        """Setup specialized logging for the sync service"""
        # Use environment variables for sync service specific logging
        sync_log_file = os.getenv('SYNC_SERVICE_LOG_FILE', self.config.logging.log_file)
        
        # CORRECTION: Prioriser TOKENS_SYNC_LOG_LEVEL puis SYNC_SERVICE_LOG_LEVEL
        sync_log_level = (
            os.getenv('TOKENS_SYNC_LOG_LEVEL') or 
            os.getenv('SYNC_SERVICE_LOG_LEVEL') or 
            self.config.logging.level
        )
        
        sync_log_max_size = int(os.getenv('SYNC_SERVICE_LOG_MAX_SIZE_MB', self.config.logging.max_file_size_mb))
        sync_log_backup_count = int(os.getenv('SYNC_SERVICE_LOG_BACKUP_COUNT', self.config.logging.backup_count))
        
        # Create specialized logger
        sync_logger = SolanaWalletLogger(
            log_level=sync_log_level,
            log_file=str(Path(self.config.logging.log_dir) / sync_log_file),
            console_output=self.config.logging.console_output,
            json_output=self.config.logging.json_format,
            max_file_size=sync_log_max_size * 1024 * 1024,
            backup_count=sync_log_backup_count,
            max_age_days=self.config.logging.max_age_days,
            force_reconfigure=True
        )
        
        logger = sync_logger.get_logger('token_sync_main')
        
        # Log startup information
        logger.info("=" * 80)
        logger.info("🚀 TOKEN SYNCHRONIZATION SERVICE STARTING")
        logger.info("=" * 80)
        logger.info(f"📝 Log file: {Path(self.config.logging.log_dir) / sync_log_file}")
        logger.info(f"📋 Log level: {sync_log_level}")  # Affichera DEBUG maintenant
        logger.info(f"📊 Database: {self.config.database.get_full_path()}")
        logger.info(f"🔄 Sync interval: {self.config.processing.enrichment_interval_seconds}s")
        logger.info(f"📈 Price update interval: {self.config.processing.price_update_interval_seconds}s")
        logger.info(f"🎯 Batch size: {self.config.apis.dexscreener_batch_size}")
        
        return logger
    
    def _test_database_connection(self) -> bool:
        """Test database connection and health"""
        try:
            self.logger.info("🔍 Testing database connection...")
            
            db_connection = DatabaseConnection(
                db_path=self.config.database.get_full_path(),
                timeout=10.0,  # Réduit de 30s à 10s
                logger=self.logger
            )
            
            # CORRECTION: Test simple et rapide
            start_time = time.time()
            
            with db_connection.get_connection_context() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                
            test_duration = time.time() - start_time
            
            if result[0] == 1:
                self.logger.info(f"✅ Database connection test passed ({test_duration:.2f}s)")
                return True
            else:
                self.logger.error("❌ Database test query failed")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Database connection test failed: {e}")
            return False
    
    def run(self) -> int:
        """
        Run the main application
        
        Returns:
            Exit code (0 for success, non-zero for error)
        """
        if not self.initialize():
            return 1

        self.running = True
        self.shutdown_requested = False
        
        try:
            self.logger.info("🎯 Starting token synchronization service...")
            
            # Add some tokens to queue for initial processing if needed
            self._populate_initial_queue()
            
            self._setup_signal_handlers()

            if self.config_override.get('show_api_stats'):
                self._setup_periodic_stats_display()

            # Start the main sync service
            self.sync_service.start()
            
            # If we reach here, service stopped gracefully
            self.logger.info("✅ Token synchronization service stopped successfully")
            return 0
            
        except KeyboardInterrupt:
            self.logger.info("🛑 Keyboard interrupt received")
            self._print_final_api_statistics()
            return 0
            
        except Exception as e:
            self.logger.error(f"❌ Unexpected error in main loop: {e}", exc_info=True)
            return 1
        
        finally:
            self._cleanup()
    
    def _setup_periodic_stats_display(self):
        """Setup affichage périodique des stats API"""
        interval = self.config_override.get('api_stats_interval', 60)
        
        def periodic_stats_thread():
            while self.running and not self.shutdown_requested:
                try:
                    time.sleep(interval)
                    if self.running and not self.shutdown_requested:
                        self.logger.info("📊 === PERIODIC API STATISTICS ===")
                        self._print_detailed_api_statistics()
                except Exception as e:
                    self.logger.error(f"Error in periodic stats: {e}")
                    break
        
        self.stats_thread = threading.Thread(target=periodic_stats_thread, daemon=True)
        self.stats_thread.start()
        self.logger.info(f"📊 Periodic API stats enabled (every {interval}s)")

    def _populate_initial_queue(self):
        """Populate the processing queue with initial tokens if needed"""
        try:
            self.logger.info("🔍 Checking for tokens to add to processing queue...")
            max_initial_tokens = 500
            # Get new tokens from transactions that aren't in the queue yet
            if hasattr(self.sync_service, 'token_repo'):
                new_tokens = self.sync_service.token_repo.get_new_tokens_from_transactions(
                    retry_failed_after_days=self.config.processing.retry_failed_after_hours / 24,
                    max_failed_attempts=self.config.processing.max_failed_attempts
                )
                
                # CORRECTION: Limiter et prioriser
                if new_tokens:
                    limited_tokens = list(new_tokens)[:max_initial_tokens]
                    added_count = self.sync_service.add_tokens_to_queue(limited_tokens)
                    self.logger.info(f"➕ Added {added_count}/{len(new_tokens)} tokens to queue (limited to {max_initial_tokens})")
                    
                    if len(new_tokens) > max_initial_tokens:
                        self.logger.info(f"📋 {len(new_tokens) - max_initial_tokens} tokens queued for next cycles")
                else:
                    self.logger.info("📋 No new tokens found to add to queue")
            
        except Exception as e:
            self.logger.warning(f"⚠️ Error populating initial queue: {e}")
    
    def _cleanup(self):
        """Cleanup resources before shutdown"""
        try:
            # Arrêter le thread de stats si il existe
            if self.stats_thread_running:
                self.stats_thread_running = False
                if self.stats_thread and self.stats_thread.is_alive():
                    self.stats_thread.join(timeout=2.0)
            
            if self.sync_service:
                self.logger.info("🧹 Cleaning up sync service...")
                # Additional cleanup if needed
            
            self.logger.info("✅ Cleanup completed")
            
        except Exception as e:
            self.logger.error(f"❌ Error during cleanup: {e}")
    
    def _setup_signal_handlers(self):
        """Setup signal handlers pour afficher les stats"""
        import signal
        
        def signal_handler(signum, frame):
            if signum == signal.SIGINT:
                self.logger.info("🛑 Interrupt signal received")
                self._print_final_api_statistics()
                self.shutdown_requested = True
                if self.sync_service:
                    self.sync_service.stop()
                sys.exit(0)
        
        try:
            # SIGINT fonctionne sur tous les OS
            signal.signal(signal.SIGINT, signal_handler)
            self.logger.debug("📡 Signal handlers configured (Ctrl+C for graceful shutdown)")
            
            # Pour Unix/Linux, ajouter SIGUSR1 si disponible
            if hasattr(signal, 'SIGUSR1'):
                def stats_signal_handler(signum, frame):
                    self._print_detailed_api_statistics()
                
                signal.signal(signal.SIGUSR1, stats_signal_handler)
                self.logger.debug("📊 SIGUSR1 handler configured (kill -USR1 <pid> for API stats)")
            else:
                # Sur Windows, créer un thread de monitoring alternatif
                self._setup_windows_stats_monitoring()
                
        except Exception as e:
            self.logger.debug(f"Could not setup signal handlers: {e}")

    def _setup_windows_stats_monitoring(self):
        """Setup alternative stats monitoring pour Windows"""
        def stats_monitoring_thread():
            """Thread qui vérifie périodiquement un fichier de commande"""
            stats_file = "show_api_stats.trigger"
            
            while self.stats_thread_running:
                try:
                    # Vérifier si le fichier trigger existe
                    if os.path.exists(stats_file):
                        self.logger.info("📊 Stats trigger file detected!")
                        self._print_detailed_api_statistics()
                        
                        # Supprimer le fichier trigger
                        try:
                            os.remove(stats_file)
                        except Exception:
                            pass
                    
                    time.sleep(5)  # Vérifier toutes les 5 secondes
                    
                except Exception as e:
                    self.logger.debug(f"Error in stats monitoring thread: {e}")
                    time.sleep(10)
        
        # Démarrer le thread de monitoring
        self.stats_thread_running = True
        self.stats_thread = threading.Thread(target=stats_monitoring_thread, daemon=True)
        self.stats_thread.start()
        
        self.logger.info("💡 Windows detected: Create 'show_api_stats.trigger' file to display API stats")

    def _print_detailed_api_statistics(self):
        """Afficher des statistiques API détaillées"""
        try:
            if hasattr(self.sync_service, 'get_api_statistics'):
                self.logger.info("=" * 80)
                self.logger.info("📊 DETAILED API STATISTICS ON DEMAND")
                self.logger.info("=" * 80)
                
                api_stats = self.sync_service.get_api_statistics()
                
                # Stats globales
                global_stats = api_stats.get('global_stats', {})
                if global_stats:
                    self.logger.info(f"🌍 Total API calls: {global_stats.get('total_api_calls', 0)}")
                    self.logger.info(f"📊 Global success rate: {global_stats.get('global_success_rate', 0):.1f}%")
                    self.logger.info(f"⏱️ Runtime: {global_stats.get('runtime_hours', 0):.1f} hours")
                    self.logger.info(f"⚡ Current rate: {global_stats.get('current_rate_1m', 0)} calls/min")
                
                # Top APIs
                top_apis = api_stats.get('top_apis_by_calls', [])
                if top_apis:
                    self.logger.info("\n🔝 TOP APIs BY CALLS:")
                    for i, (api_name, stats) in enumerate(top_apis[:10], 1):
                        self.logger.info(
                            f"  {i:2d}. {api_name}: {stats.get('total_calls', 0)} calls "
                            f"(avg: {stats.get('avg_duration_seconds', 0):.3f}s, "
                            f"success: {stats.get('success_rate', 0):.1f}%)"
                        )
                
                # Health report
                health_report = api_stats.get('health_report', {})
                if health_report.get('failing_apis'):
                    self.logger.warning(f"\n⚠️  FAILING APIS: {len(health_report['failing_apis'])}")
                    for api_info in health_report['failing_apis']:
                        self.logger.warning(f"  ❌ {api_info['name']}: {api_info['consecutive_failures']} failures")
                
                if health_report.get('degraded_apis'):
                    self.logger.warning(f"\n🐌 DEGRADED APIS: {len(health_report['degraded_apis'])}")
                    for api_info in health_report['degraded_apis']:
                        self.logger.warning(f"  ⚠️  {api_info['name']}: {api_info['success_rate']:.1f}% success")
                
                self.logger.info("=" * 80)
                
        except Exception as e:
            self.logger.error(f"Error printing detailed API statistics: {e}")
    
    def _print_final_api_statistics(self):
        """Afficher les statistiques API finales au shutdown"""
        try:
            self.logger.info("=" * 80)
            self.logger.info("📊 FINAL API STATISTICS SUMMARY")
            self.logger.info("=" * 80)
            
            if hasattr(self.sync_service, 'api_tracker'):
                # Stats globales finales
                global_stats = self.sync_service.api_tracker.get_global_stats()
                if global_stats:
                    self.logger.info(f"🌍 SESSION TOTAL: {global_stats.get('total_api_calls', 0)} API calls")
                    self.logger.info(f"📊 SUCCESS RATE: {global_stats.get('global_success_rate', 0):.1f}%")
                    self.logger.info(f"⏱️  RUNTIME: {global_stats.get('runtime_hours', 0):.1f} hours")
                    self.logger.info(f"⚡ AVG RATE: {global_stats.get('calls_per_second', 0):.2f} calls/second")
                
                # Top 5 endpoints
                top_apis = self.sync_service.api_tracker.get_top_apis(limit=5, sort_by='calls')
                if top_apis:
                    self.logger.info("\n🏆 TOP 5 MOST USED ENDPOINTS:")
                    for i, (api_name, stats) in enumerate(top_apis, 1):
                        calls = stats.get('total_calls', 0)
                        avg_duration = stats.get('avg_duration_seconds', 0)
                        success_rate = stats.get('success_rate', 0)
                        self.logger.info(f"  {i}. {api_name}: {calls} calls ({avg_duration:.3f}s avg, {success_rate:.1f}% success)")
                
                # Recommendations finales
                health_report = self.sync_service.api_tracker.get_api_health_report()
                if health_report.get('recommendations'):
                    self.logger.info("\n💡 RECOMMENDATIONS:")
                    for rec in health_report['recommendations']:
                        self.logger.info(f"  • {rec}")
            
            self.logger.info("=" * 80)
            
        except Exception as e:
            self.logger.error(f"Error printing final API statistics: {e}")

    def get_status(self) -> dict:
        """Get current application status"""
        base_status = {
            'status': 'running' if not self.shutdown_requested else 'shutting_down',
            'config_loaded': self.config is not None,
            'logger_initialized': self.logger is not None
        }
        
        if self.sync_service:
            service_status = self.sync_service.get_service_status()
            base_status['service_status'] = service_status
            
            # ========== AJOUTER: API statistics dans le status ==========
            if hasattr(self.sync_service, 'get_api_statistics'):
                try:
                    api_stats = self.sync_service.get_api_statistics()
                    base_status['api_statistics'] = {
                        'total_calls': api_stats.get('global_stats', {}).get('total_api_calls', 0),
                        'success_rate': api_stats.get('global_stats', {}).get('global_success_rate', 0),
                        'active_endpoints': len(api_stats.get('api_tracker_stats', {})),
                        'health_status': 'healthy' if not api_stats.get('health_report', {}).get('failing_apis') else 'degraded'
                    }
                except Exception as e:
                    base_status['api_statistics'] = {'error': str(e)}
        else:
            base_status['service_status'] = {'status': 'not_initialized'}
        
        return base_status


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Token Synchronization Service',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                          # Run with default configuration
  %(prog)s --log-level DEBUG        # Run with debug logging
  %(prog)s --sync-interval 30       # Run with 30 second sync interval
  %(prog)s --batch-size 50          # Run with batch size of 50
  %(prog)s --dry-run                # Test configuration without starting service
  %(prog)s --show-api-stats         # Show API stats every 60 seconds
  %(prog)s --api-stats-interval 30  # Show API stats every 30 seconds
        """
    )
    
    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        help='Override log level'
    )
    
    parser.add_argument(
        '--sync-interval',
        type=int,
        help='Override sync interval in seconds'
    )
    
    parser.add_argument(
        '--batch-size',
        type=int,
        help='Override batch size for processing'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Test configuration and initialization without starting the service'
    )
    
    parser.add_argument(
        '--version',
        action='version',
        version='Token Sync Service 1.0.0'
    )

    parser.add_argument(
        '--show-api-stats',
        action='store_true',
        help='Enable periodic API statistics display'
    )
    
    parser.add_argument(
        '--api-stats-interval',
        type=int,
        default=60,
        help='Interval in seconds for API stats display (default: 60)'
    )
    
    parser.add_argument(
        '--api-stats-now',
        action='store_true',
        help='Show current API statistics and exit'
    )
    
    return parser.parse_args()


def main():
    """Main entry point"""
    print("🚀 Token Synchronization Service")
    print("=" * 50)
    
    # Parse command line arguments
    args = parse_arguments()
    
    if args.api_stats_now:
        print("📊 Displaying current API statistics...")
        try:
            # Lire les stats depuis un fichier de status ou la DB
            app = TokenSyncApplication()
            if app.initialize():
                app._print_detailed_api_statistics()
            return 0
        except Exception as e:
            print(f"❌ Error getting API stats: {e}")
            return 1

    # Prepare configuration overrides
    config_override = {}
    
    if args.log_level:
        print(f"🔧 Log level override: {args.log_level}")
        os.environ['SYNC_SERVICE_LOG_LEVEL'] = args.log_level
    
    if args.sync_interval:
        print(f"🔧 Sync interval override: {args.sync_interval}s")
        config_override['sync_interval'] = args.sync_interval
    
    if args.batch_size:
        print(f"🔧 Batch size override: {args.batch_size}")
        config_override['batch_size'] = args.batch_size
    
    if args.show_api_stats:
        print(f"📊 API stats will be shown every {args.api_stats_interval} seconds")
        config_override['show_api_stats'] = True
        config_override['api_stats_interval'] = args.api_stats_interval

    # Create and run application
    app = TokenSyncApplication(config_override=config_override)
    
    if args.dry_run:
        print("🧪 Dry run mode - testing configuration...")
        if app.initialize():
            print("✅ Configuration test passed")
            print("📊 Service status:", app.get_status())
            return 0
        else:
            print("❌ Configuration test failed")
            return 1
    
    # Run the application
    exit_code = app.run()
    
    print("👋 Token Synchronization Service shutdown complete")
    return exit_code


if __name__ == "__main__":
    # Ensure we're running with Python 3.8+
    if sys.version_info < (3, 8):
        print("❌ Python 3.8 or higher is required")
        sys.exit(1)
    
    # Set event loop policy for Windows compatibility
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    try:
        exit_code = main()
        sys.exit(exit_code)
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)