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
from ..database.token_repository import TokenRepository
from ..database.queue_repository import QueueRepository
from ..database.history_repository import HistoryRepository
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
        self.history_repo = HistoryRepository(self.db_connection, self.config, self.logger)
        self.queue_repo = QueueRepository(self.db_connection, self.logger)
        self.token_repo = TokenRepository(self.db_connection, self.history_repo, self.logger)
        self.api_tracker = ApiTracker(
            db_connection=self.db_connection, 
            logger=self.logger
        )

        self.cycle_logger = CycleLogger(logger=self.logger)
        # Initialize API clients
        self.dex_client = DexScreenerClient(logger=self.logger, api_tracker=self.api_tracker)
        
        # Initialize processors
        self.batch_processor = BatchProcessor(
            dex_client=self.dex_client,
            token_repo=self.token_repo,
            queue_repo=self.queue_repo,
            config=config,
            logger=self.logger
        )
        
        # Initialize historization processor if available
        self.historization_processor = None
        try:
            from ..processors.historization_processor import HistorizationProcessor
            self.historization_processor = HistorizationProcessor(
                db_connection=self.db_connection,
                config=config,
                logger=self.logger
            )
            self.logger.debug("✅ Historization processor initialized")
        except ImportError:
            self.logger.warning("⚠️ Historization processor not available")
        
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
        self._cycle_started = False  # Flag pour éviter double logging
        
        pass
    
    def get_api_statistics(self) -> Dict[str, Any]:
        """Get detailed API statistics"""
        try:
            return {
                'api_tracker_stats': self.api_tracker.get_stats(),
                'global_stats': self.api_tracker.get_global_stats(),
                'health_report': self.api_tracker.get_api_health_report(),
                'top_apis_by_calls': self.api_tracker.get_top_apis(limit=10, sort_by='calls'),
                'top_apis_by_duration': self.api_tracker.get_top_apis(limit=5, sort_by='duration'),
                'top_apis_by_failures': self.api_tracker.get_top_apis(limit=5, sort_by='failures')
            }
        except Exception as e:
            self.logger.error(f"Error getting API statistics: {e}")
            return {'error': str(e)}

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
        
        try:
            # 1. Process new tokens from queue
            self.logger.debug("📥 Processing new tokens from queue...")
            new_tokens_processed = self._process_new_tokens()
            self.cycle_logger.record_operation('new_tokens', new_tokens_processed)
            
            if new_tokens_processed > 0:
                self.logger.info(f"➕ Processed {new_tokens_processed} new tokens")
            
            # 2. Update existing token prices
            self.logger.debug("🔄 Updating existing token prices...")
            prices_updated = self._update_existing_prices()
            self.cycle_logger.record_operation('updated_tokens', prices_updated)
            
            if prices_updated > 0:
                self.logger.info(f"🔄 Updated {prices_updated} token prices")
            
            # 3. Historization améliorée
            self.logger.debug("📈 Running historization...")
            historized_count = self._run_historization_improved()
            self.cycle_logger.record_operation('historized_tokens', historized_count)
            
            if historized_count > 0:
                self.logger.info(f"📈 Historized {historized_count} tokens")
            
            # 4. Periodic tasks (every N cycles)
            if self.cycle_count % 5 == 0:
                self.logger.debug("⚙️ Running periodic tasks...")
                self._run_periodic_tasks()
            
            # Update statistics
            total_processed = new_tokens_processed + prices_updated
            self.stats['processed_tokens'] += total_processed
            self.stats['successful_updates'] += total_processed  # Assuming all processed are successful for now
            
            # Log cycle completion
            if total_processed > 0 or historized_count > 0:
                self.logger.info(
                    f"✅ CYCLE {self.cycle_count} COMPLETED: "
                    f"{new_tokens_processed} new, {prices_updated} updated, {historized_count} historized"
                )
            else:
                self.logger.debug(f"✅ CYCLE {self.cycle_count} COMPLETED: No tokens to process")
            
            # Record API calls from this cycle
            if hasattr(self.api_tracker, 'get_stats'):
                api_stats = self.api_tracker.get_stats()
                for api_name, stats in api_stats.items():
                    if stats.get('calls_1m', 0) > 0:
                        self.cycle_logger.record_api_call(
                            api_name, 
                            stats.get('calls_1m', 0),
                            stats.get('avg_duration_1m', 0)
                        )
            
        except KeyboardInterrupt:
            self.logger.info("🛑 Keyboard interrupt received during cycle")
            raise
        except Exception as e:
            self.logger.error(f"❌ Error in sync cycle {cycle_id}: {e}", exc_info=True)
            self.cycle_logger.record_error(str(e))
            self.stats['failed_updates'] += 1
            
            # Don't re-raise to allow service to continue
            # but log the error for investigation
            
        finally:
            # Always end the cycle properly
            try:
                self._end_sync_cycle(cycle_id)
            except Exception as e:
                self.logger.error(f"Error ending sync cycle {cycle_id}: {e}")
    
    def _process_new_tokens(self) -> int:
        """Process new tokens from the queue"""
        self.logger.debug("📥 Processing new tokens from queue...")
        
        # Get pending tokens from queue
        pending_tokens = self.queue_repo.get_pending_tokens(
            self.config.processing.batch_size_new_tokens
        )
        
        if not pending_tokens:
            self.logger.debug("No new tokens in queue to process")
            return 0
        
        self.logger.info(f"📊 Processing {len(pending_tokens)} new tokens")

        successful_count = asyncio.run(self.batch_processor.process_new_tokens_from_queue(pending_tokens))

        # AJOUT TEMPORAIRE : Forcer l'historisation des nouveaux tokens
        if successful_count > 0:
            self.logger.info(f"🔍 DEBUG: Forcing historization for processed tokens...")
            try:
                # Obtenir les tokens récemment insérés
                recent_tokens = []
                with self.db_connection.get_connection_context() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT address FROM tokens 
                        WHERE created_at > datetime('now', '-5 minutes')
                        LIMIT 20
                    """)
                    recent_tokens = [row[0] for row in cursor.fetchall()]
                
                if recent_tokens:
                    self.logger.info(f"🔍 DEBUG: Found {len(recent_tokens)} recent tokens to historize")
                    historized = 0
                    for token_addr in recent_tokens:
                        if self.history_repo.create_snapshot(token_addr):
                            historized += 1
                            self.logger.debug(f"✅ Historized {token_addr[:8]}...")
                        else:
                            self.logger.debug(f"❌ Failed to historize {token_addr[:8]}...")
                    
                    self.logger.info(f"🔍 DEBUG: Manual historization result: {historized}/{len(recent_tokens)}")
                
            except Exception as e:
                self.logger.error(f"Error in manual historization: {e}")
        
        return successful_count
    
    def _update_existing_prices(self) -> int:
        """Update existing token prices"""
        self.logger.debug("🔄 Updating existing token prices...")
        
        # Use the centralized configuration from processing
        price_update_limit = self.config.processing.batch_size_price_updates
        price_update_interval = self.config.processing.price_update_interval_seconds
        max_failed_attempts = self.config.processing.max_failed_attempts
        
        # Get tokens needing updates
        tokens_to_update = self.token_repo.get_tokens_needing_price_update(
            interval_seconds=price_update_interval,
            max_failed_attempts=max_failed_attempts,
            limit=price_update_limit
        )
        
        if not tokens_to_update:
            self.logger.debug("No tokens need price updates")
            return 0
        
        self.logger.info(f"📊 Updating {len(tokens_to_update)} token prices")
        
        # Process updates in batch
        return asyncio.run(self.batch_processor.process_price_updates(tokens_to_update))
    
    def _run_historization_improved(self) -> int:
        """Run token historization with better logic"""
        try:
            # CORRECTION: Fix configuration attribute access for historization
            # Use processing.historization_interval_seconds which exists in the config
            historization_interval = getattr(
                self.config.processing, 
                'historization_interval_seconds', 
                3600  # Default 1 heure
            )
            
            # Obtenir les tokens qui ont besoin d'historisation
            tokens_to_historize = self.token_repo.get_tokens_needing_historization(
                interval_seconds=historization_interval,
                limit=min(50, self.config.processing.batch_size_historization)
            )
            
            if not tokens_to_historize:
                self.logger.debug("📈 No tokens need historization")
                return 0
            
            self.logger.info(f"📈 Starting historization for {len(tokens_to_historize)} tokens")
            
            # Utiliser le processeur d'historisation si disponible
            if self.historization_processor:
                try:
                    result = self.historization_processor.manually_historize_tokens(tokens_to_historize)
                    successful_count = result.get('successful', 0)
                    self.logger.info(f"📈 Historization completed: {successful_count}/{len(tokens_to_historize)} successful")
                    return successful_count
                except Exception as e:
                    self.logger.error(f"Error using historization processor: {e}")
                    # Fallback vers la méthode directe
            
            # Fallback vers l'historisation directe
            successful_count = 0
            for token_address in tokens_to_historize:
                try:
                    if self.history_repo.create_snapshot(token_address):
                        successful_count += 1
                except Exception as e:
                    self.logger.debug(f"Error historizing {token_address[:8]}...: {e}")
                    continue
            
            self.logger.info(f"📈 Historization completed: {successful_count}/{len(tokens_to_historize)} successful")
            return successful_count
                
        except Exception as e:
            self.logger.error(f"Error in historization: {e}")
            return 0
    
    def _run_periodic_tasks(self):
        """Run periodic maintenance tasks"""
        # Tâches périodiques moins fréquentes pour éviter la surcharge
        
        # Every 5 cycles - update creation timestamps
        if self.cycle_count % 5 == 0:
            self._update_creation_timestamps()
        
        # Every 10 cycles - database maintenance
        if self.cycle_count % 10 == 0:
            self._database_maintenance()
    
    def _update_creation_timestamps(self):
        """Update missing creation timestamps"""
        self.logger.debug("⏰ Updating creation timestamps...")
        
        try:
            tokens_missing_timestamps = self.token_repo.get_tokens_missing_creation_timestamp(
                limit=min(50, self.config.apis.dexscreener_batch_size)
            )
            
            if not tokens_missing_timestamps:
                self.logger.debug("No tokens need timestamp updates")
                return
            
            updated_count = 0
            for token_address in tokens_missing_timestamps:
                try:
                    timestamp = self.dex_client.get_token_creation_timestamp(token_address)
                    if timestamp:
                        if self.token_repo.update_creation_timestamp(token_address, timestamp):
                            updated_count += 1
                    
                    # CORRECTION: Fix rate limiting delay access
                    rate_limit_delay = getattr(self.config.processing, 'rate_limit_delay', 0.2)
                    time.sleep(rate_limit_delay)
                    
                except Exception as e:
                    self.logger.error(f"Error updating timestamp for {token_address}: {e}")
                    continue
            
            if updated_count > 0:
                self.logger.info(f"⏰ Updated {updated_count} creation timestamps")
                self.cycle_logger.record_operation('creation_timestamps', updated_count)
                
        except Exception as e:
            self.logger.error(f"Error in update_creation_timestamps: {e}")
    
    def _database_maintenance(self):
        """Perform database maintenance"""
        self.logger.debug("🧹 Running database maintenance...")
        
        try:
            # Check database health
            if not self.db_connection.check_health():
                self.logger.warning("Database health check failed during maintenance")
            
            # Get flagged tokens stats
            stats = self.token_repo.get_flagged_tokens_stats()
            if stats:
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
        
        # Éviter la duplication d'ID
        while cycle_id == self.current_sync_cycle_id:
            time.sleep(0.001)  # Attendre 1ms
            cycle_id = int(time.time() * 1000)
        
        self.current_sync_cycle_id = cycle_id
        
        self.api_tracker.set_current_cycle(cycle_id)
        self.cycle_logger.start_cycle(cycle_id)
        
        return cycle_id
    
    def _end_sync_cycle(self, cycle_id: int):
        """End the current sync cycle with detailed API stats"""
        cycle_summary = self.cycle_logger.get_cycle_api_summary()
        
        # Log detailed API breakdown
        self.logger.info("🌐 API CALLS BREAKDOWN:")
        self.logger.info(f"  📡 Total API calls: {sum(cycle_summary['calls_by_client'].values())}")
        
        # By client
        for client, calls in cycle_summary['calls_by_client'].items():
            self.logger.info(f"  🔸 {client}: {calls} calls total")
            
            # Batch vs individual breakdown
            if client in cycle_summary['batch_vs_individual']:
                batch_count = cycle_summary['batch_vs_individual'][client]['batch']
                individual_count = cycle_summary['batch_vs_individual'][client]['individual']
                self.logger.info(f"     └─ Batch calls: {batch_count}, Individual calls: {individual_count}")
        
        # Individual calls summary
        if cycle_summary['total_individual_calls'] > 0:
            self.logger.info(f"  ⚠️ Total individual calls: {cycle_summary['total_individual_calls']}")
            self.logger.info(f"  ⚠️ Individual addresses: {cycle_summary['individual_addresses_count']}")
        
        self.cycle_logger.end_cycle()
        self.api_tracker.end_cycle()
    
    def _wait_for_next_cycle(self):
        """Wait for the next sync cycle in a way that can be interrupted."""
        interval = self.config.processing.enrichment_interval_seconds
        self.logger.debug(f"⏳ Waiting {interval} seconds until next cycle...")

        # Print statistics periodically
        if self.cycle_count % 5 == 0:
            self._print_statistics()

        end_time = time.time() + interval
        while time.time() < end_time:
            if not self.running:
                break
            time.sleep(1)  # Sleep for 1 second at a time
    
    def _print_statistics(self):
        """Print current service statistics"""
        try:
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
            queue_stats = self.queue_repo.get_queue_status_summary()
            if queue_stats:
                self.logger.info("=== 📋 QUEUE STATISTICS ===")
                for key, value in queue_stats.items():
                    if key in ['pending', 'processing', 'completed', 'failed']:
                        self.logger.info(f"  {key}: {value}")
                    elif key == 'completion_rate_percent':
                        self.logger.info(f"  completion_rate: {value}%")
                    elif key == 'avg_processing_time_seconds':
                        self.logger.info(f"  avg_processing_time: {value:.1f}s")
        
        except Exception as e:
            self.logger.error(f"Error printing statistics: {e}")
    
    def _print_api_statistics(self):
        """Print API usage statistics"""
        try:
            self.logger.info("=== 🌐 API STATISTICS ===")
            
            # Stats globales
            global_stats = self.api_tracker.get_global_stats()
            if global_stats:
                self.logger.info(f"🌍 Global: {global_stats.get('total_api_calls', 0)} total calls")
                self.logger.info(f"📊 Success rate: {global_stats.get('global_success_rate', 0):.1f}%")
                self.logger.info(f"⚡ Current rate: {global_stats.get('current_rate_1m', 0)} calls/min")
            
            # Top APIs par nombre d'appels
            top_apis = self.api_tracker.get_top_apis(limit=5, sort_by='calls')
            if top_apis:
                self.logger.debug("🔝 Top APIs by calls:")
                for api_name, stats in top_apis:
                    self.logger.debug(
                        f"  🔗 {api_name}: {stats.get('total_calls', 0)} calls, "
                        f"avg {stats.get('avg_duration_seconds', 0):.3f}s, "
                        f"success {stats.get('success_rate', 0):.1f}%"
                    )
            
            # Health report
            health_report = self.api_tracker.get_api_health_report()
            if health_report.get('failing_apis'):
                self.logger.warning(f"⚠️ Failing APIs: {health_report['failing_apis']}")
            if health_report.get('degraded_apis'):
                self.logger.warning(f"🐌 Degraded APIs: {health_report['degraded_apis']}")
                
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
        
        try:
            return self.queue_repo.add_tokens_to_queue(token_addresses)
        except Exception as e:
            self.logger.error(f"Error adding tokens to queue: {e}")
            return 0
    
    def get_service_status(self) -> Dict[str, Any]:
        """Get current service status"""
        try:
            return {
                'running': self.running,
                'current_cycle_id': self.current_sync_cycle_id,
                'cycle_count': self.cycle_count,
                'stats': self.stats.copy(),
                'queue_stats': self.queue_repo.get_queue_status_summary(),
                'api_stats': self.api_tracker.get_stats() if hasattr(self.api_tracker, 'get_stats') else {},
                'database_healthy': self.db_connection.check_health(),
                'historization_processor_available': self.historization_processor is not None
            }
        except Exception as e:
            self.logger.error(f"Error getting service status: {e}")
            return {
                'running': self.running,
                'error': str(e)
            }
    
    def force_historization(self, token_addresses: Optional[list] = None) -> Dict[str, Any]:
        """
        Force historization for specific tokens or all eligible tokens
        
        Args:
            token_addresses: Optional list of specific token addresses
            
        Returns:
            Historization results
        """
        try:
            if token_addresses:
                # Force historization for specific tokens
                if self.historization_processor:
                    result = self.historization_processor.manually_historize_tokens(token_addresses)
                else:
                    successful_count = 0
                    for token_address in token_addresses:
                        try:
                            if self.history_repo.create_snapshot(token_address):
                                successful_count += 1
                        except Exception as e:
                            self.logger.error(f"Error historizing {token_address}: {e}")
                    
                    result = {
                        'success': True,
                        'processed': len(token_addresses),
                        'successful': successful_count,
                        'failed': len(token_addresses) - successful_count
                    }
            else:
                # Force historization for all eligible tokens
                result = {'successful': self._run_historization_improved()}
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error in force historization: {e}")
            return {'success': False, 'error': str(e)}
    
    def cleanup_old_data(self, days_to_keep: int = 30) -> Dict[str, Any]:
        """
        Clean up old historical data
        
        Args:
            days_to_keep: Number of days of data to keep
            
        Returns:
            Cleanup results
        """
        try:
            deleted_count = self.history_repo.cleanup_old_history(days_to_keep)
            
            return {
                'success': True,
                'records_deleted': deleted_count,
                'days_kept': days_to_keep
            }
            
        except Exception as e:
            self.logger.error(f"Error cleaning up old data: {e}")
            return {'success': False, 'error': str(e)}
    
    def stop(self):
        """Stop the synchronization service"""
        self.logger.info("🛑 Stopping Token Sync Service...")
        self.running = False
        
        try:
            # Stop historization processor if available
            if self.historization_processor and hasattr(self.historization_processor, 'stop_processor'):
                self.historization_processor.stop_processor()
            
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