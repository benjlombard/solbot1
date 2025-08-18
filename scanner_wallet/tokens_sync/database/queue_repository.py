"""
Queue Repository
Handles all database operations related to token processing queue management.
"""
import time
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from .connection import DatabaseConnection, db_retry
from ..models.token_data import QueueItem


class QueueStatus(Enum):
    """Queue item status enumeration"""
    PENDING = "pending"
    PROCESSING = "processing" 
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    ABANDONED = "abandoned"


class QueuePriority(Enum):
    """Queue priority levels"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4
    CRITICAL = 5


@dataclass
class QueueStatistics:
    """Queue statistics structure"""
    total_items: int = 0
    pending: int = 0
    processing: int = 0
    completed: int = 0
    failed: int = 0
    retrying: int = 0
    abandoned: int = 0
    avg_processing_time: float = 0.0
    oldest_pending_age_hours: float = 0.0
    newest_item_age_minutes: float = 0.0


class QueueRepository:
    """Repository for token processing queue operations"""
    
    def __init__(self, db_connection: DatabaseConnection, logger: Optional[logging.Logger] = None):
        self.db = db_connection
        self.logger = logger or logging.getLogger(__name__)
        
        # Configuration
        self.config = {
            'max_retries': 3,
            'retry_delay_base': 300,  # 5 minutes base delay
            'retry_delay_multiplier': 2,  # Exponential backoff
            'processing_timeout_minutes': 30,
            'abandonment_threshold_hours': 24,
            'batch_size_limit': 1000,
            'cleanup_interval_hours': 6
        }
        
        # Initialize the queue table if needed
        self._ensure_queue_table_exists()
        
        self.logger.debug("📋 Queue Repository initialized")
    
    @db_retry(max_retries=3, delay=0.5)
    def _ensure_queue_table_exists(self):
        """Ensure the queue table exists with proper schema"""
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            # Create the queue table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS token_processing_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_address TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    priority INTEGER DEFAULT 2,
                    
                    -- Timestamps
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    processing_started_at DATETIME NULL,
                    completed_at DATETIME NULL,
                    last_retry_at DATETIME NULL,
                    
                    -- Processing info
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    processing_node TEXT NULL,
                    
                    -- Error tracking
                    last_error TEXT NULL,
                    error_count INTEGER DEFAULT 0,
                    
                    -- Metadata
                    source TEXT NULL,
                    metadata TEXT NULL,
                    
                    UNIQUE(token_address, status) ON CONFLICT IGNORE
                )
            """)
            
            # Create indexes for performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_queue_status_priority 
                ON token_processing_queue(status, priority DESC, created_at ASC)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_queue_token_address 
                ON token_processing_queue(token_address)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_queue_processing_timeout 
                ON token_processing_queue(status, processing_started_at)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_queue_cleanup 
                ON token_processing_queue(status, completed_at)
            """)
            
            conn.commit()
            self.logger.debug("✅ Queue table and indexes ensured")
    
    @db_retry(max_retries=3, delay=0.3)
    def add_tokens_to_queue(
        self, 
        token_addresses: List[str], 
        priority: QueuePriority = QueuePriority.NORMAL,
        source: str = "sync_service",
        metadata: Optional[Dict] = None
    ) -> int:
        """
        Add multiple tokens to processing queue
        
        Args:
            token_addresses: List of token addresses to add
            priority: Queue priority level
            source: Source that added these tokens
            metadata: Optional metadata dictionary
            
        Returns:
            Number of tokens actually added (excludes duplicates)
        """
        if not token_addresses:
            return 0
        
        # Remove duplicates and validate addresses
        unique_addresses = list(set(addr.strip() for addr in token_addresses if addr and addr.strip()))
        
        if not unique_addresses:
            return 0
        
        metadata_json = None
        if metadata:
            import json
            try:
                metadata_json = json.dumps(metadata)
            except Exception as e:
                self.logger.warning(f"Failed to serialize metadata: {e}")
        
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            added_count = 0
            current_time = datetime.now().isoformat()
            
            for token_address in unique_addresses:
                try:
                    # Check if token is already in queue with pending/processing status
                    cursor.execute("""
                        SELECT COUNT(*) FROM token_processing_queue 
                        WHERE token_address = ? 
                        AND status IN ('pending', 'processing', 'retrying')
                    """, (token_address,))
                    
                    if cursor.fetchone()[0] > 0:
                        self.logger.debug(f"Token {token_address[:8]}... already in queue")
                        continue
                    
                    # Insert new queue item
                    cursor.execute("""
                        INSERT OR REPLACE INTO token_processing_queue (
                            token_address, status, priority, created_at,
                            max_retries, source, metadata
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        token_address, 
                        QueueStatus.PENDING.value, 
                        priority.value,
                        current_time,
                        self.config['max_retries'],
                        source,
                        metadata_json
                    ))
                    
                    added_count += 1
                    
                except Exception as e:
                    self.logger.error(f"Error adding token {token_address} to queue: {e}")
                    continue
            
            conn.commit()
            
            if added_count > 0:
                self.logger.info(f"📋 Added {added_count} tokens to processing queue")
            
            return added_count
    
    @db_retry(max_retries=3, delay=0.3)
    def get_pending_tokens(
        self, 
        batch_size: int,
        priority_filter: Optional[QueuePriority] = None,
        processing_node: str = "default"
    ) -> List[str]:
        """
        Get a batch of pending tokens and mark them as processing
        
        Args:
            batch_size: Maximum number of tokens to return
            priority_filter: Optional priority filter
            processing_node: Identifier for the processing node
            
        Returns:
            List of token addresses ready for processing
        """
        batch_size = min(batch_size, self.config['batch_size_limit'])
        
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            # Start transaction for atomicity
            cursor.execute("BEGIN IMMEDIATE")
            
            try:
                # First, reset any stuck processing items
                self._reset_stuck_processing_items(cursor)
                
                # Build query based on priority filter
                if priority_filter:
                    query = """
                        SELECT token_address FROM token_processing_queue
                        WHERE status = 'pending' AND priority = ?
                        ORDER BY priority DESC, created_at ASC
                        LIMIT ?
                    """
                    params = (priority_filter.value, batch_size)
                else:
                    query = """
                        SELECT token_address FROM token_processing_queue
                        WHERE status = 'pending'
                        ORDER BY priority DESC, created_at ASC
                        LIMIT ?
                    """
                    params = (batch_size,)
                
                cursor.execute(query, params)
                pending_tokens = [row[0] for row in cursor.fetchall()]
                
                if pending_tokens:
                    # Mark selected tokens as processing
                    current_time = datetime.now().isoformat()
                    placeholders = ','.join('?' for _ in pending_tokens)
                    
                    cursor.execute(f"""
                        UPDATE token_processing_queue
                        SET status = 'processing',
                            processing_started_at = ?,
                            processing_node = ?
                        WHERE token_address IN ({placeholders})
                        AND status = 'pending'
                    """, [current_time, processing_node] + pending_tokens)
                    
                    updated_count = cursor.rowcount
                    
                    # Return only the tokens that were successfully marked as processing
                    if updated_count != len(pending_tokens):
                        self.logger.warning(f"Expected to mark {len(pending_tokens)} tokens as processing, but only marked {updated_count}")
                        
                        # Get the actual tokens that were marked
                        cursor.execute(f"""
                            SELECT token_address FROM token_processing_queue
                            WHERE token_address IN ({placeholders})
                            AND status = 'processing'
                            AND processing_node = ?
                        """, pending_tokens + [processing_node])
                        
                        pending_tokens = [row[0] for row in cursor.fetchall()]
                
                conn.commit()
                
                if pending_tokens:
                    self.logger.debug(f"📤 Retrieved {len(pending_tokens)} tokens for processing")
                
                return pending_tokens
                
            except Exception as e:
                conn.rollback()
                self.logger.error(f"Error getting pending tokens: {e}")
                raise e
    
    @db_retry(max_retries=3, delay=0.3)
    def update_token_status(
        self, 
        token_address: str, 
        success: bool, 
        error_message: Optional[str] = None,
        processing_node: str = "default"
    ) -> bool:
        """
        Update the status of a token in the processing queue
        
        Args:
            token_address: Token address
            success: Whether processing was successful
            error_message: Error message if processing failed
            processing_node: Processing node identifier
            
        Returns:
            True if update was successful
        """
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()

            # LOG: Vérification de l'état initial
            cursor.execute("""
                SELECT status, processing_node, created_at, processing_started_at
                FROM token_processing_queue
                WHERE token_address = ?
            """, (token_address,))
            
            current_record = cursor.fetchone()
            
            if not current_record:
                self.logger.warning(f"🚨 Queue state error: {token_address[:8]}... not found in queue at all")
                return False
            
            current_status, current_node, created_at, started_at = current_record
            
            # LOG: État actuel détaillé
            self.logger.debug(f"📋 Queue state check: {token_address[:8]}... status={current_status}, node={current_node}, expected_node={processing_node}")
            
            if current_status != 'processing':
                self.logger.warning(f"🚨 Queue state error: {token_address[:8]}... in state '{current_status}', expected 'processing'")
                return False
            
            if current_node != processing_node:
                self.logger.warning(f"🚨 Queue node mismatch: {token_address[:8]}... node='{current_node}', expected='{processing_node}'")
                return False
            
            # LOG: Durée de processing
            if started_at:
                try:
                    start_time = datetime.fromisoformat(started_at)
                    processing_duration = (datetime.now() - start_time).total_seconds()
                    self.logger.debug(f"⏱️ Processing duration: {token_address[:8]}... took {processing_duration:.1f}s")
                except:
                    pass

            current_time = datetime.now().isoformat()
            
            if success:
                # Mark as completed
                cursor.execute("""
                    UPDATE token_processing_queue
                    SET status = 'completed',
                        completed_at = ?,
                        last_error = NULL
                    WHERE token_address = ? 
                    AND status = 'processing'
                    AND processing_node = ?
                """, (current_time, token_address, processing_node))
                
                if cursor.rowcount > 0:
                    self.logger.debug(f"✅ Queue updated: {token_address[:8]}... marked as completed")
                else:
                    self.logger.error(f"❌ Queue update failed: {token_address[:8]}... no rows affected")
                
            else:
                # Get current retry info
                cursor.execute("""
                    SELECT retry_count, max_retries FROM token_processing_queue
                    WHERE token_address = ? 
                    AND status = 'processing'
                    AND processing_node = ?
                """, (token_address, processing_node))
                
                result = cursor.fetchone()
                if not result:
                    self.logger.warning(f"Token {token_address[:8]}... not found in processing state")
                    return False
                
                retry_count, max_retries = result
                retry_count += 1
                
                if retry_count <= max_retries:
                    # Schedule for retry
                    retry_delay = self._calculate_retry_delay(retry_count)
                    retry_time = datetime.now() + timedelta(seconds=retry_delay)
                    
                    cursor.execute("""
                        UPDATE token_processing_queue
                        SET status = 'retrying',
                            retry_count = ?,
                            last_retry_at = ?,
                            last_error = ?,
                            error_count = error_count + 1,
                            processing_started_at = ?
                        WHERE token_address = ? 
                        AND status = 'processing'
                        AND processing_node = ?
                    """, (
                        retry_count, current_time, error_message, 
                        retry_time.isoformat(), token_address, processing_node
                    ))
                    
                    self.logger.warning(f"🔄 Scheduled {token_address[:8]}... for retry {retry_count}/{max_retries}")
                    
                else:
                    # Mark as failed (exhausted retries)
                    cursor.execute("""
                        UPDATE token_processing_queue
                        SET status = 'failed',
                            completed_at = ?,
                            last_error = ?,
                            error_count = error_count + 1
                        WHERE token_address = ? 
                        AND status = 'processing'
                        AND processing_node = ?
                    """, (current_time, error_message, token_address, processing_node))
                    
                    self.logger.error(f"❌ Marked {token_address[:8]}... as failed (max retries exceeded)")
            
            conn.commit()
            return cursor.rowcount > 0
    
    @db_retry(max_retries=3, delay=0.3)
    def get_retry_ready_tokens(self, batch_size: int) -> List[str]:
        """
        Get tokens that are ready for retry and mark them as pending
        
        Args:
            batch_size: Maximum number of tokens to return
            
        Returns:
            List of token addresses ready for retry
        """
        current_time = datetime.now().isoformat()
        
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            # Get tokens ready for retry
            cursor.execute("""
                SELECT token_address FROM token_processing_queue
                WHERE status = 'retrying'
                AND processing_started_at <= ?
                ORDER BY priority DESC, last_retry_at ASC
                LIMIT ?
            """, (current_time, batch_size))
            
            retry_tokens = [row[0] for row in cursor.fetchall()]
            
            if retry_tokens:
                # Mark them as pending for reprocessing
                placeholders = ','.join('?' for _ in retry_tokens)
                cursor.execute(f"""
                    UPDATE token_processing_queue
                    SET status = 'pending',
                        processing_started_at = NULL,
                        processing_node = NULL
                    WHERE token_address IN ({placeholders})
                    AND status = 'retrying'
                """, retry_tokens)
                
                conn.commit()
                
                self.logger.info(f"🔄 Made {len(retry_tokens)} retry tokens available for processing")
            
            return retry_tokens
    
    def _reset_stuck_processing_items(self, cursor):
        """Reset items that have been processing too long"""
        timeout_minutes = self.config['processing_timeout_minutes']
        timeout_time = datetime.now() - timedelta(minutes=timeout_minutes)
        
        cursor.execute("""
            UPDATE token_processing_queue
            SET status = 'pending',
                processing_started_at = NULL,
                processing_node = NULL,
                error_count = error_count + 1,
                last_error = 'Processing timeout - reset to pending'
            WHERE status = 'processing'
            AND processing_started_at < ?
        """, (timeout_time.isoformat(),))
        
        reset_count = cursor.rowcount
        if reset_count > 0:
            self.logger.warning(f"⚠️ Reset {reset_count} stuck processing items")
    
    def _calculate_retry_delay(self, retry_count: int) -> int:
        """Calculate retry delay with exponential backoff"""
        base_delay = self.config['retry_delay_base']
        multiplier = self.config['retry_delay_multiplier']
        
        delay = base_delay * (multiplier ** (retry_count - 1))
        
        # Cap at 1 hour
        return min(delay, 3600)
    
    @db_retry(max_retries=3, delay=0.5)
    def get_queue_statistics(self) -> QueueStatistics:
        """Get comprehensive queue statistics"""
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            stats = QueueStatistics()
            
            # Count by status
            cursor.execute("""
                SELECT status, COUNT(*) 
                FROM token_processing_queue 
                GROUP BY status
            """)
            
            status_counts = dict(cursor.fetchall())
            stats.total_items = sum(status_counts.values())
            stats.pending = status_counts.get('pending', 0)
            stats.processing = status_counts.get('processing', 0)
            stats.completed = status_counts.get('completed', 0)
            stats.failed = status_counts.get('failed', 0)
            stats.retrying = status_counts.get('retrying', 0)
            stats.abandoned = status_counts.get('abandoned', 0)
            
            # Average processing time for completed items
            cursor.execute("""
                SELECT AVG(
                    CASE 
                        WHEN processing_started_at IS NOT NULL AND completed_at IS NOT NULL
                        THEN (julianday(completed_at) - julianday(processing_started_at)) * 86400
                        ELSE NULL 
                    END
                ) as avg_processing_time
                FROM token_processing_queue
                WHERE status = 'completed'
                AND processing_started_at IS NOT NULL
                AND completed_at IS NOT NULL
            """)
            
            result = cursor.fetchone()
            stats.avg_processing_time = result[0] if result[0] else 0.0
            
            # Oldest pending item age
            cursor.execute("""
                SELECT MIN(created_at) FROM token_processing_queue
                WHERE status = 'pending'
            """)
            
            oldest_pending = cursor.fetchone()[0]
            if oldest_pending:
                try:
                    oldest_time = datetime.fromisoformat(oldest_pending.replace('Z', '+00:00'))
                    age = datetime.now() - oldest_time
                    stats.oldest_pending_age_hours = age.total_seconds() / 3600
                except Exception:
                    stats.oldest_pending_age_hours = 0.0
            
            # Newest item age
            cursor.execute("""
                SELECT MAX(created_at) FROM token_processing_queue
            """)
            
            newest_item = cursor.fetchone()[0]
            if newest_item:
                try:
                    newest_time = datetime.fromisoformat(newest_item.replace('Z', '+00:00'))
                    age = datetime.now() - newest_time
                    stats.newest_item_age_minutes = age.total_seconds() / 60
                except Exception:
                    stats.newest_item_age_minutes = 0.0
            
            return stats
    
    @db_retry(max_retries=3, delay=0.5)
    def get_queue_status_summary(self) -> Dict[str, any]:
        """Get a summary of queue status"""
        stats = self.get_queue_statistics()
        
        # Calculate additional metrics
        total_non_completed = stats.total_items - stats.completed
        completion_rate = (stats.completed / stats.total_items * 100) if stats.total_items > 0 else 0
        failure_rate = (stats.failed / stats.total_items * 100) if stats.total_items > 0 else 0
        
        return {
            'total_items': stats.total_items,
            'pending': stats.pending,
            'processing': stats.processing,
            'completed': stats.completed,
            'failed': stats.failed,
            'retrying': stats.retrying,
            'abandoned': stats.abandoned,
            'completion_rate_percent': round(completion_rate, 2),
            'failure_rate_percent': round(failure_rate, 2),
            'avg_processing_time_seconds': round(stats.avg_processing_time, 2),
            'oldest_pending_age_hours': round(stats.oldest_pending_age_hours, 2),
            'newest_item_age_minutes': round(stats.newest_item_age_minutes, 2),
            'queue_health': self._assess_queue_health(stats)
        }
    
    def _assess_queue_health(self, stats: QueueStatistics) -> str:
        """Assess overall queue health"""
        if stats.total_items == 0:
            return "empty"
        
        # Check for concerning conditions
        if stats.oldest_pending_age_hours > 24:
            return "backlogged"
        
        if stats.processing > stats.pending * 3:  # Too many processing relative to pending
            return "processing_overload"
        
        failure_rate = (stats.failed / stats.total_items) if stats.total_items > 0 else 0
        if failure_rate > 0.2:  # > 20% failure rate
            return "high_failure_rate"
        
        if stats.retrying > stats.pending:
            return "high_retry_rate"
        
        return "healthy"
    
    @db_retry(max_retries=3, delay=0.5)
    def get_failed_tokens_analysis(self, limit: int = 100) -> List[Dict]:
        """Get analysis of failed tokens"""
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    token_address,
                    retry_count,
                    error_count,
                    last_error,
                    created_at,
                    completed_at,
                    source
                FROM token_processing_queue
                WHERE status = 'failed'
                ORDER BY completed_at DESC
                LIMIT ?
            """, (limit,))
            
            failed_tokens = []
            for row in cursor.fetchall():
                failed_tokens.append({
                    'token_address': row[0],
                    'retry_count': row[1],
                    'error_count': row[2],
                    'last_error': row[3],
                    'created_at': row[4],
                    'completed_at': row[5],
                    'source': row[6]
                })
            
            return failed_tokens
    
    @db_retry(max_retries=3, delay=0.5)
    def cleanup_old_completed_items(self, retention_hours: int = 48) -> int:
        """
        Clean up old completed items from the queue
        
        Args:
            retention_hours: Hours to retain completed items
            
        Returns:
            Number of items cleaned up
        """
        cutoff_time = datetime.now() - timedelta(hours=retention_hours)
        
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            # Count items to be deleted
            cursor.execute("""
                SELECT COUNT(*) FROM token_processing_queue
                WHERE status = 'completed'
                AND completed_at < ?
            """, (cutoff_time.isoformat(),))
            
            count_to_delete = cursor.fetchone()[0]
            
            if count_to_delete > 0:
                # Delete old completed items
                cursor.execute("""
                    DELETE FROM token_processing_queue
                    WHERE status = 'completed'
                    AND completed_at < ?
                """, (cutoff_time.isoformat(),))
                
                conn.commit()
                
                self.logger.info(f"🧹 Cleaned up {count_to_delete} old completed queue items")
            
            return count_to_delete
    
    @db_retry(max_retries=3, delay=0.5)
    def abandon_old_failed_items(self, abandonment_hours: int = 168) -> int:
        """
        Mark very old failed items as abandoned
        
        Args:
            abandonment_hours: Hours after which to abandon failed items
            
        Returns:
            Number of items abandoned
        """
        cutoff_time = datetime.now() - timedelta(hours=abandonment_hours)
        
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE token_processing_queue
                SET status = 'abandoned'
                WHERE status = 'failed'
                AND completed_at < ?
            """, (cutoff_time.isoformat(),))
            
            abandoned_count = cursor.rowcount
            conn.commit()
            
            if abandoned_count > 0:
                self.logger.info(f"📦 Abandoned {abandoned_count} old failed queue items")
            
            return abandoned_count
    
    @db_retry(max_retries=3, delay=0.3)
    def get_token_queue_history(self, token_address: str) -> List[Dict]:
        """Get queue history for a specific token"""
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT * FROM token_processing_queue
                WHERE token_address = ?
                ORDER BY created_at DESC
            """, (token_address,))
            
            history = []
            for row in cursor.fetchall():
                history.append(dict(row))
            
            return history
    
    @db_retry(max_retries=3, delay=0.3)
    def requeue_failed_tokens(self, token_addresses: Optional[List[str]] = None, max_count: int = 100) -> int:
        """
        Requeue failed tokens for another processing attempt
        
        Args:
            token_addresses: Specific tokens to requeue, or None for automatic selection
            max_count: Maximum number of tokens to requeue
            
        Returns:
            Number of tokens requeued
        """
        with self.db.get_connection_context() as conn:
            cursor = conn.cursor()
            
            if token_addresses:
                # Requeue specific tokens
                placeholders = ','.join('?' for _ in token_addresses)
                cursor.execute(f"""
                    UPDATE token_processing_queue
                    SET status = 'pending',
                        retry_count = 0,
                        processing_started_at = NULL,
                        processing_node = NULL,
                        last_error = 'Manually requeued'
                    WHERE token_address IN ({placeholders})
                    AND status = 'failed'
                """, token_addresses)
                
            else:
                # Automatically select failed tokens to requeue (oldest first)
                cursor.execute("""
                    UPDATE token_processing_queue
                    SET status = 'pending',
                        retry_count = 0,
                        processing_started_at = NULL,
                        processing_node = NULL,
                        last_error = 'Automatically requeued'
                    WHERE id IN (
                        SELECT id FROM token_processing_queue
                        WHERE status = 'failed'
                        ORDER BY completed_at ASC
                        LIMIT ?
                    )
                """, (max_count,))
            
            requeued_count = cursor.rowcount
            conn.commit()
            
            if requeued_count > 0:
                self.logger.info(f"🔄 Requeued {requeued_count} failed tokens")
            
            return requeued_count
    
    def get_config(self) -> Dict:
        """Get current queue configuration"""
        return self.config.copy()
    
    def update_config(self, new_config: Dict):
        """Update queue configuration"""
        self.config.update(new_config)
        self.logger.info(f"🔧 Updated queue configuration: {new_config}")