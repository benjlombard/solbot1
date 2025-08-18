#!/usr/bin/env python3
"""
Token Synchronization Service - Main Entry Point
Main entry point for the modular token synchronization service.
"""
import sys
import os
import signal
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
        
        try:
            self.logger.info("🎯 Starting token synchronization service...")
            
            # Add some tokens to queue for initial processing if needed
            self._populate_initial_queue()
            
            # Start the main sync service
            self.sync_service.start()
            
            # If we reach here, service stopped gracefully
            self.logger.info("✅ Token synchronization service stopped successfully")
            return 0
            
        except KeyboardInterrupt:
            self.logger.info("🛑 Keyboard interrupt received")
            return 0
            
        except Exception as e:
            self.logger.error(f"❌ Unexpected error in main loop: {e}", exc_info=True)
            return 1
        
        finally:
            self._cleanup()
    
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
            if self.sync_service:
                self.logger.info("🧹 Cleaning up sync service...")
                # Additional cleanup if needed
            
            self.logger.info("✅ Cleanup completed")
            
        except Exception as e:
            self.logger.error(f"❌ Error during cleanup: {e}")
    
    def get_status(self) -> dict:
        """Get current application status"""
        if not self.sync_service:
            return {'status': 'not_initialized'}
        
        return {
            'status': 'running' if not self.shutdown_requested else 'shutting_down',
            'service_status': self.sync_service.get_service_status(),
            'config_loaded': self.config is not None,
            'logger_initialized': self.logger is not None
        }


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
    
    return parser.parse_args()


def main():
    """Main entry point"""
    print("🚀 Token Synchronization Service")
    print("=" * 50)
    
    # Parse command line arguments
    args = parse_arguments()
    
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