"""
Cleanup Service
Handles database maintenance, log rotation, and system cleanup tasks.
"""
import time
import os
import logging
import threading
import shutil
import glob
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from pathlib import Path
import gzip

from ..database.connection import DatabaseConnection, db_retry
from ..database.token_repository import TokenRepository
from ..database.history_repository import HistoryRepository


class CleanupService:
    """
    Service for automated database maintenance and system cleanup
    """
    
    def __init__(
        self,
        db_connection: DatabaseConnection,
        config,
        logger: Optional[logging.Logger] = None
    ):
        self.db_connection = db_connection
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        
        # Repositories for database operations
        self.token_repo = TokenRepository(db_connection, logger)
        self.history_repo = HistoryRepository(db_connection, logger)
        
        # Cleanup configuration
        self.cleanup_config = {
            # Database cleanup
            'history_retention_days': getattr(config.monitoring, 'history_retention_days', 30),
            'api_metrics_retention_days': getattr(config.monitoring, 'api_metrics_retention_days', 7),
            'performance_metrics_retention_days': getattr(config.monitoring, 'performance_metrics_retention_days', 14),
            'failed_tokens_cleanup_days': getattr(config.monitoring, 'failed_tokens_cleanup_days', 7),
            
            # Log cleanup
            'log_retention_days': getattr(config.logging, 'max_age_days', 30),
            'compress_logs_older_than_days': 7,
            
            # Database maintenance
            'vacuum_interval_hours': 24,
            'analyze_interval_hours': 6,
            'checkpoint_interval_hours': 2,
            
            # Queue cleanup
            'queue_completed_retention_hours': 48,
            'queue_failed_retention_hours': 168,  # 7 days
        }
        
        # State tracking
        self.running = False
        self.cleanup_thread: Optional[threading.Thread] = None
        self.last_vacuum = 0
        self.last_analyze = 0
        self.last_checkpoint = 0
        self.last_log_cleanup = 0
        
        # Statistics
        self.cleanup_stats = {
            'total_cleanups': 0,
            'records_deleted': 0,
            'space_freed_mb': 0.0,
            'logs_compressed': 0,
            'logs_deleted': 0,
            'last_cleanup': None,
            'last_vacuum': None,
            'last_analyze': None
        }
        
        self.logger.info("🧹 Cleanup Service initialized")
    
    def start_cleanup_service(self, interval_hours: float = 1.0):
        """
        Start automated cleanup service
        
        Args:
            interval_hours: How often to run cleanup checks
        """
        if self.running:
            self.logger.warning("Cleanup service already running")
            return
        
        self.running = True
        self.cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            args=(interval_hours * 3600,),
            daemon=True
        )
        self.cleanup_thread.start()
        
        self.logger.info(f"🚀 Cleanup service started (interval: {interval_hours}h)")
    
    def stop_cleanup_service(self):
        """Stop the cleanup service"""
        self.running = False
        
        if self.cleanup_thread and self.cleanup_thread.is_alive():
            self.cleanup_thread.join(timeout=10.0)
        
        self.logger.info("🛑 Cleanup service stopped")
    
    def _cleanup_loop(self, interval_seconds: float):
        """Main cleanup loop"""
        while self.running:
            try:
                self._run_cleanup_cycle()
                time.sleep(interval_seconds)
                
            except Exception as e:
                self.logger.error(f"Error in cleanup loop: {e}", exc_info=True)
                time.sleep(300)  # Wait 5 minutes on error
    
    def _run_cleanup_cycle(self):
        """Run a complete cleanup cycle"""
        self.logger.debug("🧹 Starting cleanup cycle...")
        current_time = time.time()
        
        try:
            # Database maintenance
            self._run_database_maintenance(current_time)
            
            # Data cleanup
            self._cleanup_old_data()
            
            # Log cleanup
            self._cleanup_logs(current_time)
            
            # Queue cleanup
            self._cleanup_processing_queue()
            
            # Update statistics
            self.cleanup_stats['total_cleanups'] += 1
            self.cleanup_stats['last_cleanup'] = datetime.now().isoformat()
            
            self.logger.debug("✅ Cleanup cycle completed")
            
        except Exception as e:
            self.logger.error(f"Error in cleanup cycle: {e}")
    
    def _run_database_maintenance(self, current_time: float):
        """Run database maintenance tasks"""
        try:
            # Checkpoint WAL file
            if current_time - self.last_checkpoint > (self.cleanup_config['checkpoint_interval_hours'] * 3600):
                self._checkpoint_database()
                self.last_checkpoint = current_time
            
            # Analyze tables for query optimization
            if current_time - self.last_analyze > (self.cleanup_config['analyze_interval_hours'] * 3600):
                self._analyze_database()
                self.last_analyze = current_time
            
            # Vacuum database
            if current_time - self.last_vacuum > (self.cleanup_config['vacuum_interval_hours'] * 3600):
                self._vacuum_database()
                self.last_vacuum = current_time
        
        except Exception as e:
            self.logger.error(f"Error in database maintenance: {e}")
    
    @db_retry(max_retries=3, delay=1.0)
    def _checkpoint_database(self):
        """Checkpoint the WAL file to main database"""
        try:
            with self.db_connection.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # Checkpoint WAL
                cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                result = cursor.fetchone()
                
                if result:
                    busy, log_size, checkpointed = result
                    self.logger.info(f"📊 WAL checkpoint: {checkpointed} pages checkpointed, {log_size} pages in log")
                
        except Exception as e:
            self.logger.error(f"Error checkpointing database: {e}")
    
    @db_retry(max_retries=2, delay=2.0)
    def _analyze_database(self):
        """Analyze database tables for query optimization"""
        try:
            with self.db_connection.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # Get all tables
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cursor.fetchall()]
                
                # Analyze each table
                for table in tables:
                    try:
                        cursor.execute(f"ANALYZE {table}")
                        self.logger.debug(f"📊 Analyzed table: {table}")
                    except Exception as e:
                        self.logger.warning(f"Failed to analyze table {table}: {e}")
                
                conn.commit()
                self.cleanup_stats['last_analyze'] = datetime.now().isoformat()
                self.logger.info(f"📊 Database analysis completed for {len(tables)} tables")
                
        except Exception as e:
            self.logger.error(f"Error analyzing database: {e}")
    
    @db_retry(max_retries=2, delay=5.0)
    def _vacuum_database(self):
        """Vacuum the database to reclaim space"""
        try:
            self.logger.info("🧹 Starting database vacuum...")
            
            # Get database size before vacuum
            db_size_before = self._get_database_size()
            
            with self.db_connection.get_connection_context() as conn:
                # Switch to DELETE mode for vacuum
                conn.execute("PRAGMA journal_mode=DELETE")
                conn.execute("VACUUM")
                # Switch back to WAL mode
                conn.execute("PRAGMA journal_mode=WAL")
                conn.commit()
            
            # Get database size after vacuum
            db_size_after = self._get_database_size()
            space_freed = db_size_before - db_size_after
            
            self.cleanup_stats['space_freed_mb'] += space_freed
            self.cleanup_stats['last_vacuum'] = datetime.now().isoformat()
            
            self.logger.info(f"✅ Database vacuum completed: {space_freed:.2f}MB freed")
            
        except Exception as e:
            self.logger.error(f"Error vacuuming database: {e}")
    
    def _get_database_size(self) -> float:
        """Get current database size in MB"""
        try:
            db_path = Path(self.db_connection.db_path)
            if db_path.exists():
                return db_path.stat().st_size / (1024 * 1024)
        except Exception:
            pass
        return 0.0
    
    def _cleanup_old_data(self):
        """Clean up old data from various tables"""
        try:
            deleted_count = 0
            
            # Clean old history snapshots
            history_deleted = self._cleanup_token_history()
            deleted_count += history_deleted
            
            # Clean old API metrics
            api_metrics_deleted = self._cleanup_api_metrics()
            deleted_count += api_metrics_deleted
            
            # Clean old performance metrics
            perf_metrics_deleted = self._cleanup_performance_metrics()
            deleted_count += perf_metrics_deleted
            
            # Clean old failed tokens
            failed_tokens_deleted = self._cleanup_failed_tokens()
            deleted_count += failed_tokens_deleted
            
            if deleted_count > 0:
                self.cleanup_stats['records_deleted'] += deleted_count
                self.logger.info(f"🗑️ Cleaned up {deleted_count} old records")
        
        except Exception as e:
            self.logger.error(f"Error cleaning up old data: {e}")
    
    @db_retry(max_retries=3, delay=1.0)
    def _cleanup_token_history(self) -> int:
        """Clean up old token history snapshots"""
        try:
            cutoff_timestamp = int(time.time()) - (self.cleanup_config['history_retention_days'] * 86400)
            
            with self.db_connection.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # Count records to delete
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens_history 
                    WHERE snapshot_timestamp < ?
                """, (cutoff_timestamp,))
                count_to_delete = cursor.fetchone()[0]
                
                if count_to_delete > 0:
                    # Delete old snapshots
                    cursor.execute("""
                        DELETE FROM tokens_history 
                        WHERE snapshot_timestamp < ?
                    """, (cutoff_timestamp,))
                    
                    conn.commit()
                    
                    self.logger.info(f"🗑️ Deleted {count_to_delete} old history snapshots")
                    return count_to_delete
            
            return 0
            
        except Exception as e:
            self.logger.error(f"Error cleaning token history: {e}")
            return 0
    
    @db_retry(max_retries=3, delay=1.0)
    def _cleanup_api_metrics(self) -> int:
        """Clean up old API metrics"""
        try:
            cutoff_timestamp = int(time.time()) - (self.cleanup_config['api_metrics_retention_days'] * 86400)
            
            with self.db_connection.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # Count records to delete
                cursor.execute("""
                    SELECT COUNT(*) FROM api_metrics 
                    WHERE call_timestamp < ?
                """, (cutoff_timestamp,))
                count_to_delete = cursor.fetchone()[0]
                
                if count_to_delete > 0:
                    # Delete old metrics
                    cursor.execute("""
                        DELETE FROM api_metrics 
                        WHERE call_timestamp < ?
                    """, (cutoff_timestamp,))
                    
                    conn.commit()
                    
                    self.logger.info(f"🗑️ Deleted {count_to_delete} old API metrics")
                    return count_to_delete
            
            return 0
            
        except Exception as e:
            self.logger.error(f"Error cleaning API metrics: {e}")
            return 0
    
    @db_retry(max_retries=3, delay=1.0)
    def _cleanup_performance_metrics(self) -> int:
        """Clean up old performance metrics"""
        try:
            cutoff_timestamp = int(time.time()) - (self.cleanup_config['performance_metrics_retention_days'] * 86400)
            
            with self.db_connection.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # Check if table exists
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='performance_metrics'
                """)
                
                if not cursor.fetchone():
                    return 0  # Table doesn't exist
                
                # Count records to delete
                cursor.execute("""
                    SELECT COUNT(*) FROM performance_metrics 
                    WHERE timestamp < ?
                """, (cutoff_timestamp,))
                count_to_delete = cursor.fetchone()[0]
                
                if count_to_delete > 0:
                    # Delete old metrics
                    cursor.execute("""
                        DELETE FROM performance_metrics 
                        WHERE timestamp < ?
                    """, (cutoff_timestamp,))
                    
                    conn.commit()
                    
                    self.logger.info(f"🗑️ Deleted {count_to_delete} old performance metrics")
                    return count_to_delete
            
            return 0
            
        except Exception as e:
            self.logger.error(f"Error cleaning performance metrics: {e}")
            return 0
    
    @db_retry(max_retries=3, delay=1.0)
    def _cleanup_failed_tokens(self) -> int:
        """Clean up old failed token records"""
        try:
            cutoff_time = datetime.now() - timedelta(days=self.cleanup_config['failed_tokens_cleanup_days'])
            
            with self.db_connection.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # Count tokens to clean
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens 
                    WHERE no_data_available = 1 
                    AND no_data_last_check < ?
                    AND failed_attempts >= 5
                """, (cutoff_time.isoformat(),))
                count_to_delete = cursor.fetchone()[0]
                
                if count_to_delete > 0:
                    # Delete old failed tokens
                    cursor.execute("""
                        DELETE FROM tokens 
                        WHERE no_data_available = 1 
                        AND no_data_last_check < ?
                        AND failed_attempts >= 5
                    """, (cutoff_time.isoformat(),))
                    
                    conn.commit()
                    
                    self.logger.info(f"🗑️ Deleted {count_to_delete} old failed token records")
                    return count_to_delete
            
            return 0
            
        except Exception as e:
            self.logger.error(f"Error cleaning failed tokens: {e}")
            return 0
    
    def _cleanup_processing_queue(self):
        """Clean up old processing queue entries"""
        try:
            current_time = datetime.now()
            
            # Clean completed entries
            completed_cutoff = current_time - timedelta(hours=self.cleanup_config['queue_completed_retention_hours'])
            
            # Clean failed entries
            failed_cutoff = current_time - timedelta(hours=self.cleanup_config['queue_failed_retention_hours'])
            
            with self.db_connection.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # Check if queue table exists
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='token_processing_queue'
                """)
                
                if not cursor.fetchone():
                    return  # Table doesn't exist
                
                # Clean completed entries
                cursor.execute("""
                    DELETE FROM token_processing_queue 
                    WHERE status = 'completed' 
                    AND completed_at < ?
                """, (completed_cutoff.isoformat(),))
                completed_deleted = cursor.rowcount
                
                # Clean old failed entries
                cursor.execute("""
                    DELETE FROM token_processing_queue 
                    WHERE status = 'failed' 
                    AND completed_at < ?
                """, (failed_cutoff.isoformat(),))
                failed_deleted = cursor.rowcount
                
                conn.commit()
                
                if completed_deleted > 0 or failed_deleted > 0:
                    self.logger.info(f"🗑️ Cleaned queue: {completed_deleted} completed, {failed_deleted} failed")
        
        except Exception as e:
            self.logger.error(f"Error cleaning processing queue: {e}")
    
    def _cleanup_logs(self, current_time: float):
        """Clean up and compress old log files"""
        if current_time - self.last_log_cleanup < 86400:  # Once per day
            return
        
        try:
            log_dir = Path(self.config.logging.base_dir)
            if not log_dir.exists():
                return
            
            compressed_count = 0
            deleted_count = 0
            
            # Get all log files
            log_files = list(log_dir.glob("*.log*"))
            
            for log_file in log_files:
                try:
                    # Skip if already compressed
                    if log_file.suffix == '.gz':
                        # Check if old compressed file should be deleted
                        if self._should_delete_log(log_file):
                            log_file.unlink()
                            deleted_count += 1
                            self.logger.debug(f"🗑️ Deleted old log: {log_file.name}")
                        continue
                    
                    # Check if log should be compressed
                    if self._should_compress_log(log_file):
                        compressed_file = self._compress_log_file(log_file)
                        if compressed_file:
                            compressed_count += 1
                            self.logger.debug(f"📦 Compressed log: {log_file.name}")
                    
                    # Check if uncompressed log should be deleted
                    elif self._should_delete_log(log_file):
                        log_file.unlink()
                        deleted_count += 1
                        self.logger.debug(f"🗑️ Deleted old log: {log_file.name}")
                
                except Exception as e:
                    self.logger.warning(f"Error processing log file {log_file}: {e}")
            
            if compressed_count > 0 or deleted_count > 0:
                self.cleanup_stats['logs_compressed'] += compressed_count
                self.cleanup_stats['logs_deleted'] += deleted_count
                self.logger.info(f"📦 Log cleanup: {compressed_count} compressed, {deleted_count} deleted")
            
            self.last_log_cleanup = current_time
            
        except Exception as e:
            self.logger.error(f"Error cleaning logs: {e}")
    
    def _should_compress_log(self, log_file: Path) -> bool:
        """Check if a log file should be compressed"""
        try:
            # Don't compress active log files
            if log_file.name.endswith('.log'):
                return False
            
            # Check age
            age_days = (time.time() - log_file.stat().st_mtime) / 86400
            return age_days > self.cleanup_config['compress_logs_older_than_days']
            
        except Exception:
            return False
    
    def _should_delete_log(self, log_file: Path) -> bool:
        """Check if a log file should be deleted"""
        try:
            age_days = (time.time() - log_file.stat().st_mtime) / 86400
            return age_days > self.cleanup_config['log_retention_days']
            
        except Exception:
            return False
    
    def _compress_log_file(self, log_file: Path) -> Optional[Path]:
        """Compress a log file"""
        try:
            compressed_file = log_file.with_suffix(log_file.suffix + '.gz')
            
            with open(log_file, 'rb') as f_in:
                with gzip.open(compressed_file, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            # Remove original file
            log_file.unlink()
            
            return compressed_file
            
        except Exception as e:
            self.logger.error(f"Error compressing log file {log_file}: {e}")
            return None
    
    def run_manual_cleanup(self, force_vacuum: bool = False) -> Dict[str, Any]:
        """
        Run manual cleanup and return statistics
        
        Args:
            force_vacuum: Force database vacuum regardless of schedule
            
        Returns:
            Dictionary with cleanup results
        """
        self.logger.info("🧹 Starting manual cleanup...")
        start_time = time.time()
        
        results = {
            'start_time': datetime.now().isoformat(),
            'database_maintenance': {},
            'data_cleanup': {},
            'log_cleanup': {},
            'queue_cleanup': {},
            'duration_seconds': 0,
            'success': False
        }
        
        try:
            # Database maintenance
            if force_vacuum:
                self._vacuum_database()
                results['database_maintenance']['vacuum'] = 'completed'
            
            self._analyze_database()
            results['database_maintenance']['analyze'] = 'completed'
            
            self._checkpoint_database()
            results['database_maintenance']['checkpoint'] = 'completed'
            
            # Data cleanup
            history_deleted = self._cleanup_token_history()
            api_deleted = self._cleanup_api_metrics()
            perf_deleted = self._cleanup_performance_metrics()
            failed_deleted = self._cleanup_failed_tokens()
            
            results['data_cleanup'] = {
                'history_records_deleted': history_deleted,
                'api_metrics_deleted': api_deleted,
                'performance_metrics_deleted': perf_deleted,
                'failed_tokens_deleted': failed_deleted,
                'total_deleted': history_deleted + api_deleted + perf_deleted + failed_deleted
            }
            
            # Queue cleanup
            self._cleanup_processing_queue()
            results['queue_cleanup']['completed'] = True
            
            # Log cleanup
            self._cleanup_logs(time.time())
            results['log_cleanup']['completed'] = True
            
            results['success'] = True
            results['duration_seconds'] = time.time() - start_time
            
            self.logger.info(f"✅ Manual cleanup completed in {results['duration_seconds']:.1f}s")
            
        except Exception as e:
            results['success'] = False
            results['error'] = str(e)
            self.logger.error(f"❌ Manual cleanup failed: {e}")
        
        return results
    
    def get_cleanup_statistics(self) -> Dict[str, Any]:
        """Get cleanup service statistics"""
        try:
            # Database size info
            db_size_mb = self._get_database_size()
            
            # Get record counts
            with self.db_connection.get_connection_context() as conn:
                cursor = conn.cursor()
                
                record_counts = {}
                
                # Count history records
                try:
                    cursor.execute("SELECT COUNT(*) FROM tokens_history")
                    record_counts['history_snapshots'] = cursor.fetchone()[0]
                except Exception:
                    record_counts['history_snapshots'] = 0
                
                # Count API metrics
                try:
                    cursor.execute("SELECT COUNT(*) FROM api_metrics")
                    record_counts['api_metrics'] = cursor.fetchone()[0]
                except Exception:
                    record_counts['api_metrics'] = 0
                
                # Count tokens
                try:
                    cursor.execute("SELECT COUNT(*) FROM tokens")
                    record_counts['tokens'] = cursor.fetchone()[0]
                    
                    cursor.execute("SELECT COUNT(*) FROM tokens WHERE no_data_available = 1")
                    record_counts['failed_tokens'] = cursor.fetchone()[0]
                except Exception:
                    record_counts['tokens'] = 0
                    record_counts['failed_tokens'] = 0
            
            # Service status
            status = {
                'service_running': self.running,
                'database_size_mb': db_size_mb,
                'record_counts': record_counts,
                'cleanup_config': self.cleanup_config,
                'statistics': self.cleanup_stats.copy()
            }
            
            return status
            
        except Exception as e:
            self.logger.error(f"Error getting cleanup statistics: {e}")
            return {'error': str(e)}
    
    def update_cleanup_config(self, new_config: Dict[str, Any]):
        """Update cleanup configuration"""
        self.cleanup_config.update(new_config)
        self.logger.info(f"🔧 Updated cleanup configuration: {new_config}")
    
    def get_maintenance_schedule(self) -> Dict[str, str]:
        """Get next scheduled maintenance times"""
        current_time = time.time()
        
        next_vacuum = self.last_vacuum + (self.cleanup_config['vacuum_interval_hours'] * 3600)
        next_analyze = self.last_analyze + (self.cleanup_config['analyze_interval_hours'] * 3600)
        next_checkpoint = self.last_checkpoint + (self.cleanup_config['checkpoint_interval_hours'] * 3600)
        
        return {
            'next_vacuum': datetime.fromtimestamp(next_vacuum).isoformat() if next_vacuum > current_time else 'overdue',
            'next_analyze': datetime.fromtimestamp(next_analyze).isoformat() if next_analyze > current_time else 'overdue',
            'next_checkpoint': datetime.fromtimestamp(next_checkpoint).isoformat() if next_checkpoint > current_time else 'overdue',
            'service_running': self.running
        }