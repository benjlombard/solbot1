"""
Token Sync Service
Main orchestrator service that coordinates all token synchronization activities.
"""
import time
import asyncio
import logging
import signal
import sys
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from ..database.connection import DatabaseConnection
from ..database.token_repository import TokenRepository, QueueRepository
from ..api_clients.dexscreener_client import DexScreenerClient
from ..processors.batch_processor import BatchProcessor
from ..monitoring.cycle_logger import CycleLogger
from ..monitoring.api_tracker import ApiTracker


class SyncService:
    """
    Main synchronization service that orchestrates all token data operations
    """
    
    def __init__(self, config, logger: Optional[logging.Logger] = None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.running = False
        
        # Initialize database connection
        self.db_connection = DatabaseConnection(
            db_path=config.database.get_full_path(),
            timeout=config.database.timeout,
            logger=self.logger
        )
        
        # Initialize repositories
        self.token_repo = TokenRepository(self.db_connection, self.logger)
        self.queue_repo = QueueRepository(self.db_connection, self.logger)
        
        # Initialize API clients
        self.dex_client = DexScreenerClient(logger=self.logger)
        
        # Initialize processors
        self.batch_processor = BatchProcessor(
            dex_client=self.dex_client,
            token_repo=self.token_repo,
            queue_repo=self.queue_repo,
            config=config,
            logger=self.logger
        )
        
        # Initialize monitoring
        self.api_tracker = ApiTracker(db_connection=self.db_connection, logger=self.logger)
        self.cycle_logger = CycleLogger(logger=self.logger)
        
        # Statistics
        self.stats = {
            'processed_tokens': 0,
            'successful_updates': 0,
            'failed_updates': 0,
            'cycles_completed': 0,
            'start_time': None
        }
        
        # Cycle management
        self.current_sync_cycle_id = None
        self.cycle_count = 0
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle termination signals"""
        self.logger.info("Received termination signal, stopping gracefully...")
        self.stop()
    
    def start(self):
        """Start the continuous synchronization service"""
        self.logger.info("🚀 Starting Token Sync Service...")
        
        # Check database health
        if not self.db_connection.check_health():
            self.logger.error("❌ Database health check failed. Stopping service.")
            return
        
        self.running = True
        self.stats['start_time'] = time.time()
        
        try:
            while self.running:
                try:
                    self._run_sync_cycle()
                    self.stats['cycles_completed'] += 1
                    
                    if self.running:
                        self._wait_for_next_cycle()
                        
                except KeyboardInterrupt:
                    self.logger.info("Received keyboard interrupt")
                    break
                except Exception as e:
                    self.logger.error(f"Unexpected error in sync cycle: {e}", exc_info=True)
                    # Wait a bit before retrying to avoid rapid failures
                    if self.running:
                        time.sleep(30)
                    
        except Exception as e:
            self.logger.error(f"Fatal error in main loop: {e}", exc_info=True)
        finally:
            self.stop()
    
    def _run_sync_cycle(self):
        """Run one complete synchronization cycle"""
        self.cycle_count += 1
        cycle_id = self._start_sync_cycle()
        
        self.logger.info(f"🔄 CYCLE {self.cycle_count} STARTED - ID: {cycle_id}")
        
        try:
            # 1. Process new tokens from queue
            new_tokens_processed = self._process_new_tokens()
            self.cycle_logger.record_operation('new_tokens', new_tokens_processed)
            
            # 2. Update existing token prices
            prices_updated = self._update_existing_prices()
            self.cycle_logger.record_operation('updated_tokens', prices_updated)
            
            # 3. Periodic tasks (every N cycles)
            self._run_periodic_tasks()
            
            # Update statistics
            self.stats['processed_tokens'] += new_tokens_processed + prices_updated
            
            self.logger.info(
                f"✅ CYCLE {self.cycle_count} COMPLETED: "
                f"{new_tokens_processed} new, {prices_updated} updated"
            )
            
        except Exception as e:
            self.logger.error(f"Error in sync cycle {cycle_id}: {e}", exc_info=True)
            self.cycle_logger.record_error(str(e))
        finally:
            self._end_sync_cycle(cycle_id)
    
    def _process_new_tokens(self) -> int:
        """Process new tokens from the queue"""
        self.logger.debug("📥 Processing new tokens from queue...")
        
        # Get pending tokens from queue
        pending_tokens = self.queue_repo.get_pending_tokens(
            self.config.batching.batch_sizes['dexscreener']
        )
        
        if not pending_tokens:
            self.logger.debug("No new tokens in queue to process")
            return 0
        
        self.logger.info(f"📊 Processing {len(pending_tokens)} new tokens")
        
        # Process tokens in batch
        return asyncio.run(self.batch_processor.process_tokens_batch(pending_tokens))
    
    def _update_existing_prices(self) -> int:
        """Update existing token prices"""
        self.logger.debug("🔄 Updating existing token prices...")
        
        # Get tokens needing updates
        tokens_to_update = self.token_repo.get_tokens_needing_price_update(
            interval_seconds=self.config.monitoring.price_update_interval_seconds,
            max_failed_attempts=self.config.monitoring.max_failed_attempts,
            limit=self.config.monitoring.price_update_limit
        )
        
        if not tokens_to_update:
            self.logger.debug("No tokens need price updates")
            return 0
        
        self.logger.info(f"📊 Updating {len(tokens_to_update)} token prices")
        
        # Process updates in batch
        return asyncio.run(self.batch_processor.process_tokens_batch(tokens_to_update))
    
    def _run_periodic_tasks(self):
        """Run periodic maintenance tasks"""
        # Every 3 cycles - run historization
        if self.cycle_count % 3 == 0:
            self._run_historization()
        
        # Every 5 cycles - update creation timestamps
        if self.cycle_count % 5 == 0:
            self._update_creation_timestamps()
        
        # Every 10 cycles - database maintenance
        if self.cycle_count % 10 == 0:
            self._database_maintenance()
    
    def _run_historization(self):
        """Run token historization"""
        self.logger.debug("📈 Running historization...")
        
        tokens_to_historize = self.token_repo.get_tokens_needing_historization(
            interval_seconds=self.config.monitoring.historization_interval_seconds,
            limit=self.config.batching.batch_sizes['dexscreener']
        )
        
        if tokens_to_historize:
            # This would be implemented in a separate historization processor
            self.logger.info(f"📈 Would historize {len(tokens_to_historize)} tokens")
            # TODO: Implement historization processor
            self.cycle_logger.record_operation('historized_tokens', len(tokens_to_historize))
    
    def _update_creation_timestamps(self):
        """Update missing creation timestamps"""
        self.logger.debug("⏰ Updating creation timestamps...")
        
        tokens_missing_timestamps = self.token_repo.get_tokens_missing_creation_timestamp(
            limit=self.config.batching.batch_sizes['dexscreener']
        )
        
        if tokens_missing_timestamps:
            updated_count = 0
            for token_address in tokens_missing_timestamps:
                try:
                    timestamp = self.dex_client.get_token_creation_timestamp(token_address)
                    if timestamp:
                        if self.token_repo.update_creation_timestamp(token_address, timestamp):
                            updated_count += 1
                    
                    # Rate limiting
                    time.sleep(self.config.monitoring.rate_limit_delay)
                    
                except Exception as e:
                    self.logger.error(f"Error updating timestamp for {token_address}: {e}")
                    continue
            
            self.logger.info(f"⏰ Updated {updated_count} creation timestamps")
            self.cycle_logger.record_operation('creation_timestamps', updated_count)
    
    def _database_maintenance(self):
        """Perform database maintenance"""
        self.logger.debug("🧹 Running database maintenance...")
        
        try:
            # Check database health
            if not self.db_connection.check_health():
                self.logger.warning("Database health check failed during maintenance")
            
            # Get flagged tokens stats
            stats = self.token_repo.get_flagged_tokens_stats()
            self.logger.info(f"📊 Flagged tokens: {stats}")
            
            # Periodic vacuum (every 100 cycles)
            if self.cycle_count % 100 == 0:
                self.logger.info("🧹 Running database vacuum...")
                self.db_connection.vacuum_database()
                
        except Exception as e:
            self.logger.error(f"Error in database maintenance: {e}")
    
    def _start_sync_cycle(self) -> int:
        """Start a new sync cycle"""
        cycle_id = int(time.time() * 1000)
        self.current_sync_cycle_id = cycle_id
        
        self.api_tracker.set_current_cycle(cycle_id)
        self.cycle_logger.start_cycle(cycle_id)
        
        return cycle_id
    
    def _end_sync_cycle(self, cycle_id: int):
        """End the current sync cycle"""
        self.cycle_logger.end_cycle()
        self.api_tracker.end_cycle()
        self.current_sync_cycle_id = None
    
    def _wait_for_next_cycle(self):
        """Wait for the next sync cycle"""
        interval = self.config.monitoring.enrichment_interval_seconds
        self.logger.debug(f"⏳ Waiting {interval} seconds until next cycle...")
        
        # Print statistics periodically
        if self.cycle_count % 5 == 0:
            self._print_statistics()
        
        time.sleep(interval)
    
    def _print_statistics(self):
        """Print current service statistics"""
        if self.stats['start_time']:
            runtime = time.time() - self.stats['start_time']
            runtime_str = str(timedelta(seconds=int(runtime)))
        else:
            runtime_str = "N/A"
        
        self.logger.info("=== 📊 SYNC SERVICE STATISTICS ===")
        self.logger.info(f"⏱️ Runtime: {runtime_str}")
        self.logger.info(f"🔄 Cycles completed: {self.stats['cycles_completed']}")
        self.logger.info(f"📊 Tokens processed: {self.stats['processed_tokens']}")
        self.logger.info(f"✅ Successful updates: {self.stats['successful_updates']}")
        self.logger.info(f"❌ Failed updates: {self.stats['failed_updates']}")
        
        if self.stats['processed_tokens'] > 0:
            success_rate = (self.stats['successful_updates'] / self.stats['processed_tokens']) * 100
            self.logger.info(f"📈 Success rate: {success_rate:.1f}%")
        
        # API statistics
        self._print_api_statistics()
        
        # Queue statistics
        queue_stats = self.queue_repo.get_queue_stats()
        if queue_stats:
            self.logger.info("=== 📋 QUEUE STATISTICS ===")
            for key, value in queue_stats.items():
                self.logger.info(f"  {key}: {value}")
    
    def _print_api_statistics(self):
        """Print API usage statistics"""
        try:
            api_stats = self.api_tracker.get_stats()
            
            if api_stats:
                self.logger.info("=== 🌐 API STATISTICS ===")
                for api_name, stats in api_stats.items():
                    if stats.get('total_calls', 0) > 0:
                        self.logger.info(
                            f"🔗 {api_name}: {stats.get('total_calls', 0)} calls, "
                            f"avg {stats.get('avg_duration_seconds', 0):.3f}s, "
                            f"rate {stats.get('rate_per_minute_5m', 0):.1f}/min"
                        )
        except Exception as e:
            self.logger.debug(f"Error printing API statistics: {e}")
    
    def add_tokens_to_queue(self, token_addresses: list) -> int:
        """
        Add tokens to the processing queue
        
        Args:
            token_addresses: List of token addresses to add
            
        Returns:
            Number of tokens added to queue
        """
        if not token_addresses:
            return 0
        
        return self.queue_repo.add_tokens_to_queue(token_addresses)
    
    def get_service_status(self) -> Dict[str, Any]:
        """Get current service status"""
        return {
            'running': self.running,
            'current_cycle_id': self.current_sync_cycle_id,
            'cycle_count': self.cycle_count,
            'stats': self.stats.copy(),
            'queue_stats': self.queue_repo.get_queue_stats(),
            'api_stats': self.api_tracker.get_stats() if hasattr(self.api_tracker, 'get_stats') else {},
            'database_healthy': self.db_connection.check_health()
        }
    
    def stop(self):
        """Stop the synchronization service"""
        self.logger.info("🛑 Stopping Token Sync Service...")
        self.running = False
        
        try:
            # Close API clients
            self.dex_client.close()
            
            # Print final statistics
            self._print_statistics()
            
            self.logger.info("✅ Token Sync Service stopped successfully")
            
        except Exception as e:
            self.logger.error(f"Error during service shutdown: {e}")


def create_sync_service(config, logger: Optional[logging.Logger] = None) -> SyncService:
    """
    Factory function to create a configured sync service
    
    Args:
        config: Configuration object
        logger: Optional logger instance
        
    Returns:
        Configured SyncService instance
    """
    return SyncService(config=config, logger=logger)