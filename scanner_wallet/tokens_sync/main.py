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
from pathlib import Path
from typing import Optional

# Add project root to path
project_root = Path(__file__).parent.absolute()
sys.path.insert(0, str(project_root))

# Import configuration and logging from the existing core modules
try:
    from core.config import get_config
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
        
        # Signal handling
        self.shutdown_requested = False
        self._setup_signal_handlers()
    
    def _setup_signal_handlers(self):
        """Setup graceful shutdown signal handlers"""
        def signal_handler(signum, frame):
            signal_name = signal.Signals(signum).name
            print(f"\n🛑 Received {signal_name} signal, initiating graceful shutdown...")
            self.shutdown_requested = True
            
            if self.sync_service:
                self.sync_service.stop()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Windows compatibility
        if hasattr(signal, 'SIGBREAK'):
            signal.signal(signal.SIGBREAK, signal_handler)
    
    def initialize(self) -> bool:
        """
        Initialize the application components
        
        Returns:
            True if initialization successful, False otherwise
        """
        try:
            # 1. Load configuration
            self.config = get_config()
            
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
        for key, value in self.config_override.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                if self.logger:
                    self.logger.info(f"🔧 Config override: {key} = {value}")
    
    def _setup_logging(self) -> logging.Logger:
        """Setup specialized logging for the sync service"""
        # Use environment variables for sync service specific logging
        sync_log_file = os.getenv('SYNC_SERVICE_LOG_FILE', 'token_sync_service.log')
        sync_log_level = os.getenv('SYNC_SERVICE_LOG_LEVEL', self.config.logging.level.value)
        sync_log_max_size = int(os.getenv('SYNC_SERVICE_LOG_MAX_SIZE_MB', '100'))
        sync_log_backup_count = int(os.getenv('SYNC_SERVICE_LOG_BACKUP_COUNT', '10'))
        
        # Create specialized logger
        sync_logger = SolanaWalletLogger(
            log_level=sync_log_level,
            log_file=str(Path(self.config.logging.base_dir) / sync_log_file),
            console_output=self.config.logging.console_output,
            json_output=self.config.logging.json_output,
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
        logger.info(f"📝 Log file: {Path(self.config.logging.base_dir) / sync_log_file}")
        logger.info(f"📋 Log level: {sync_log_level}")
        logger.info(f"📊 Database: {self.config.database.get_full_path()}")
        logger.info(f"🔄 Sync interval: {self.config.monitoring.enrichment_interval_seconds}s")
        logger.info(f"📈 Price update interval: {self.config.monitoring.price_update_interval_seconds}s")
        logger.info(f"🎯 Batch size: {self.config.batching.batch_sizes.get('dexscreener', 30)}")
        
        return logger
    
    def _test_database_connection(self) -> bool:
        """Test database connection and health"""
        try:
            self.logger.info("🔍 Testing database connection...")
            
            db_connection = DatabaseConnection(
                db_path=self.config.database.get_full_path(),
                timeout=self.config.database.timeout,
                logger=self.logger
            )
            
            if not db_connection.check_health():
                self.logger.error("❌ Database health check failed")
                return False
            
            self.logger.info("✅ Database connection test passed")
            return True
            
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
            
            # Get new tokens from transactions that aren't in the queue yet
            if hasattr(self.sync_service, 'token_repo'):
                new_tokens = self.sync_service.token_repo.get_new_tokens_from_transactions(
                    retry_failed_after_days=self.config.monitoring.retry_failed_after_days,
                    max_failed_attempts=self.config.monitoring.max_failed_attempts
                )
                
                if new_tokens:
                    added_count = self.sync_service.add_tokens_to_queue(list(new_tokens))
                    self.logger.info(f"➕ Added {added_count} new tokens to processing queue")
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