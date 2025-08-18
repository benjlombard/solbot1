"""
Historization Processor
Handles creation and management of historical token data snapshots with analysis and trends.
"""
import time
import asyncio
import logging
import threading
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from collections import defaultdict

from ..models.token_data import TokenData, HistoricalSnapshot
from ..database.connection import DatabaseConnection, db_retry
from ..database.token_repository import TokenRepository
from ..database.history_repository import HistoryRepository
from ..analyzers.token_analyzer import TokenAnalyzer


@dataclass
class HistorizationResult:
    """Result of historization process"""
    token_address: str
    success: bool
    snapshot_id: Optional[int] = None
    error_message: Optional[str] = None
    processing_time: float = 0.0
    viability_score: float = 0.0
    risk_score: float = 0.0
    momentum_score: float = 0.0


@dataclass
class HistorizationBatch:
    """Batch of tokens to historize"""
    tokens: List[str]
    created_at: datetime
    priority: int = 0  # Higher = more priority
    batch_type: str = "regular"  # regular, priority, manual


@dataclass
class TrendAnalysis:
    """Analysis of token trends over time"""
    token_address: str
    timeframe_hours: int
    price_trend: str  # 'up', 'down', 'stable'
    volume_trend: str
    holder_trend: str
    volatility_score: float
    momentum_score: float
    prediction_confidence: float


class HistorizationProcessor:
    """
    Comprehensive historization processor with intelligent scheduling and analysis
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
        
        # Initialize repositories
        self.token_repo = TokenRepository(db_connection, logger)
        self.history_repo = HistoryRepository(db_connection, logger)
        
        # Initialize analyzer
        self.analyzer = TokenAnalyzer()
        
        # Processing configuration
        self.historization_config = {
            'default_interval_hours': getattr(config.monitoring, 'historization_interval_seconds', 3600) // 3600,
            'priority_interval_hours': 1,  # High-activity tokens
            'batch_size': getattr(config.batching.batch_sizes, 'historization', 100),
            'max_concurrent_batches': 3,
            'retention_days': getattr(config.monitoring, 'history_retention_days', 30),
            'analysis_enabled': True,
            'trend_analysis_enabled': True
        }
        
        # Processing state
        self.running = False
        self.processor_thread: Optional[threading.Thread] = None
        self.processing_queue: List[HistorizationBatch] = []
        self.queue_lock = threading.Lock()
        
        # Statistics
        self.stats = {
            'total_snapshots_created': 0,
            'successful_historizations': 0,
            'failed_historizations': 0,
            'avg_processing_time': 0.0,
            'tokens_analyzed': 0,
            'trends_identified': 0,
            'last_processing_time': None,
            'by_token_type': defaultdict(int),
            'processing_errors': []
        }
        
        # Token priority tracking
        self.token_priorities = {}  # token_address -> priority_score
        self.last_priority_update = 0
        
        self.logger.info("📈 Historization Processor initialized")
    
    def start_processor(self, processing_interval: float = 300.0):
        """
        Start the historization processor
        
        Args:
            processing_interval: How often to check for tokens to historize (seconds)
        """
        if self.running:
            self.logger.warning("Historization processor already running")
            return
        
        self.running = True
        self.processor_thread = threading.Thread(
            target=self._processing_loop,
            args=(processing_interval,),
            daemon=True
        )
        self.processor_thread.start()
        
        self.logger.info(f"🚀 Historization processor started (interval: {processing_interval}s)")
    
    def stop_processor(self):
        """Stop the historization processor"""
        self.running = False
        
        if self.processor_thread and self.processor_thread.is_alive():
            self.processor_thread.join(timeout=10.0)
        
        self.logger.info("🛑 Historization processor stopped")
    
    def _processing_loop(self, interval_seconds: float):
        """Main processing loop"""
        while self.running:
            try:
                # Update token priorities periodically
                if time.time() - self.last_priority_update > 3600:  # Every hour
                    self._update_token_priorities()
                
                # Identify tokens needing historization
                self._schedule_tokens_for_historization()
                
                # Process batches
                await self._process_historization_batches()
                
                # Cleanup old data periodically
                if self.stats['total_snapshots_created'] % 1000 == 0:
                    self._cleanup_old_snapshots()
                
                time.sleep(interval_seconds)
                
            except Exception as e:
                self.logger.error(f"Error in historization processing loop: {e}", exc_info=True)
                time.sleep(60)  # Wait before retrying on error
    
    def _update_token_priorities(self):
        """Update priority scores for tokens based on activity"""
        try:
            self.logger.debug("🎯 Updating token priorities...")
            
            # Get token activity metrics
            with self.db_connection.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # Calculate priority based on volume, price changes, and holder activity
                cursor.execute("""
                    SELECT address, volume_24h, price_change_24h, holder_count, market_cap,
                           last_price_update, created_at
                    FROM tokens 
                    WHERE is_dead = 0 AND (is_rugged = 0 OR is_rugged IS NULL)
                    AND (price_usd > 0 OR market_cap > 0)
                """)
                
                tokens = cursor.fetchall()
                
                for token in tokens:
                    priority_score = self._calculate_token_priority(dict(token))
                    self.token_priorities[token['address']] = priority_score
                
                self.last_priority_update = time.time()
                self.logger.debug(f"🎯 Updated priorities for {len(tokens)} tokens")
                
        except Exception as e:
            self.logger.error(f"Error updating token priorities: {e}")
    
    def _calculate_token_priority(self, token_data: Dict) -> float:
        """
        Calculate priority score for a token (0-100, higher = more priority)
        
        Args:
            token_data: Token data dictionary
            
        Returns:
            Priority score
        """
        try:
            score = 0.0
            
            # Volume activity (30 points)
            volume_24h = float(token_data.get('volume_24h', 0))
            if volume_24h > 1000000:  # > $1M
                score += 30
            elif volume_24h > 100000:  # > $100K
                score += 25
            elif volume_24h > 10000:   # > $10K
                score += 20
            elif volume_24h > 1000:    # > $1K
                score += 15
            elif volume_24h > 100:     # > $100
                score += 10
            
            # Price volatility (25 points)
            price_change = abs(float(token_data.get('price_change_24h', 0)))
            if price_change > 50:      # > 50% change
                score += 25
            elif price_change > 20:    # > 20% change
                score += 20
            elif price_change > 10:    # > 10% change
                score += 15
            elif price_change > 5:     # > 5% change
                score += 10
            
            # Market cap significance (20 points)
            market_cap = float(token_data.get('market_cap', 0))
            if market_cap > 10000000:  # > $10M
                score += 20
            elif market_cap > 1000000: # > $1M
                score += 15
            elif market_cap > 100000:  # > $100K
                score += 10
            elif market_cap > 10000:   # > $10K
                score += 5
            
            # Holder count (15 points)
            holder_count = int(token_data.get('holder_count', 0))
            if holder_count > 10000:
                score += 15
            elif holder_count > 1000:
                score += 12
            elif holder_count > 100:
                score += 10
            elif holder_count > 50:
                score += 8
            elif holder_count > 10:
                score += 5
            
            # Token age bonus (10 points) - newer tokens get higher priority
            created_at = token_data.get('created_at')
            if created_at:
                try:
                    creation_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    age_hours = (datetime.now() - creation_time).total_seconds() / 3600
                    
                    if age_hours < 24:       # < 1 day
                        score += 10
                    elif age_hours < 168:    # < 1 week
                        score += 8
                    elif age_hours < 720:    # < 1 month
                        score += 5
                except:
                    pass
            
            return min(100.0, max(0.0, score))
            
        except Exception as e:
            self.logger.debug(f"Error calculating priority: {e}")
            return 50.0  # Default medium priority
    
    def _schedule_tokens_for_historization(self):
        """Schedule tokens for historization based on priority and timing"""
        try:
            # Get tokens needing historization
            tokens_needing_historization = self._get_tokens_needing_historization()
            
            if not tokens_needing_historization:
                return
            
            # Group by priority
            high_priority = []
            medium_priority = []
            low_priority = []
            
            for token_addr in tokens_needing_historization:
                priority = self.token_priorities.get(token_addr, 50.0)
                
                if priority >= 75:
                    high_priority.append(token_addr)
                elif priority >= 40:
                    medium_priority.append(token_addr)
                else:
                    low_priority.append(token_addr)
            
            # Create batches
            with self.queue_lock:
                if high_priority:
                    batch = HistorizationBatch(
                        tokens=high_priority[:self.historization_config['batch_size']],
                        created_at=datetime.now(),
                        priority=3,
                        batch_type="priority"
                    )
                    self.processing_queue.append(batch)
                    self.logger.debug(f"📊 Scheduled {len(batch.tokens)} high-priority tokens")
                
                if medium_priority:
                    batch = HistorizationBatch(
                        tokens=medium_priority[:self.historization_config['batch_size']],
                        created_at=datetime.now(),
                        priority=2,
                        batch_type="regular"
                    )
                    self.processing_queue.append(batch)
                    self.logger.debug(f"📊 Scheduled {len(batch.tokens)} medium-priority tokens")
                
                if low_priority:
                    batch = HistorizationBatch(
                        tokens=low_priority[:self.historization_config['batch_size']],
                        created_at=datetime.now(),
                        priority=1,
                        batch_type="regular"
                    )
                    self.processing_queue.append(batch)
                    self.logger.debug(f"📊 Scheduled {len(batch.tokens)} low-priority tokens")
                
                # Sort queue by priority
                self.processing_queue.sort(key=lambda b: b.priority, reverse=True)
                
        except Exception as e:
            self.logger.error(f"Error scheduling tokens for historization: {e}")
    
    def _get_tokens_needing_historization(self) -> List[str]:
        """Get list of tokens that need historization"""
        try:
            # Use different intervals based on priority
            now = int(time.time())
            
            # Priority tokens (high activity) - every hour
            priority_cutoff = now - (self.historization_config['priority_interval_hours'] * 3600)
            
            # Regular tokens - based on configuration
            regular_cutoff = now - (self.historization_config['default_interval_hours'] * 3600)
            
            with self.db_connection.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # Get priority tokens
                cursor.execute("""
                    SELECT address FROM tokens 
                    WHERE is_dead = 0 AND (is_rugged = 0 OR is_rugged IS NULL)
                    AND (price_usd > 0 OR market_cap > 0)
                    AND (last_historized_at < ? OR last_historized_at IS NULL)
                    AND (volume_24h > 10000 OR ABS(price_change_24h) > 20 OR holder_count > 1000)
                    ORDER BY last_historized_at ASC NULLS FIRST
                    LIMIT ?
                """, (priority_cutoff, self.historization_config['batch_size']))
                
                priority_tokens = [row[0] for row in cursor.fetchall()]
                
                # Get regular tokens (excluding priority ones)
                if priority_tokens:
                    priority_placeholders = ','.join('?' for _ in priority_tokens)
                    cursor.execute(f"""
                        SELECT address FROM tokens 
                        WHERE is_dead = 0 AND (is_rugged = 0 OR is_rugged IS NULL)
                        AND (price_usd > 0 OR market_cap > 0)
                        AND (last_historized_at < ? OR last_historized_at IS NULL)
                        AND address NOT IN ({priority_placeholders})
                        ORDER BY last_historized_at ASC NULLS FIRST
                        LIMIT ?
                    """, [regular_cutoff] + priority_tokens + [self.historization_config['batch_size']])
                else:
                    cursor.execute("""
                        SELECT address FROM tokens 
                        WHERE is_dead = 0 AND (is_rugged = 0 OR is_rugged IS NULL)
                        AND (price_usd > 0 OR market_cap > 0)
                        AND (last_historized_at < ? OR last_historized_at IS NULL)
                        ORDER BY last_historized_at ASC NULLS FIRST
                        LIMIT ?
                    """, (regular_cutoff, self.historization_config['batch_size']))
                
                regular_tokens = [row[0] for row in cursor.fetchall()]
                
                return priority_tokens + regular_tokens
                
        except Exception as e:
            self.logger.error(f"Error getting tokens for historization: {e}")
            return []
    
    async def _process_historization_batches(self):
        """Process all pending historization batches"""
        if not self.processing_queue:
            return
        
        # Get batches to process
        with self.queue_lock:
            batches_to_process = self.processing_queue[:self.historization_config['max_concurrent_batches']]
            self.processing_queue = self.processing_queue[self.historization_config['max_concurrent_batches']:]
        
        if not batches_to_process:
            return
        
        self.logger.info(f"📈 Processing {len(batches_to_process)} historization batches")
        
        # Process batches concurrently
        batch_tasks = [self._process_batch(batch) for batch in batches_to_process]
        batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
        
        # Log results
        total_processed = 0
        total_successful = 0
        
        for i, result in enumerate(batch_results):
            if isinstance(result, Exception):
                self.logger.error(f"Batch {i+1} failed: {result}")
            else:
                processed, successful = result
                total_processed += processed
                total_successful += successful
        
        self.logger.info(f"✅ Historization completed: {total_successful}/{total_processed} successful")
    
    async def _process_batch(self, batch: HistorizationBatch) -> Tuple[int, int]:
        """Process a single historization batch"""
        self.logger.debug(f"📊 Processing {batch.batch_type} batch with {len(batch.tokens)} tokens")
        
        # Create historization tasks
        tasks = [asyncio.to_thread(self._historize_token, token_addr) for token_addr in batch.tokens]
        
        # Execute tasks
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Count results
        successful_count = 0
        for i, result in enumerate(results):
            token_addr = batch.tokens[i]
            
            if isinstance(result, Exception):
                self.logger.error(f"Historization failed for {token_addr[:8]}...: {result}")
                self.stats['failed_historizations'] += 1
                self.stats['processing_errors'].append({
                    'token': token_addr,
                    'error': str(result),
                    'timestamp': datetime.now().isoformat()
                })
            elif result and result.success:
                successful_count += 1
                self.stats['successful_historizations'] += 1
                self.stats['total_snapshots_created'] += 1
                
                # Update processing time average
                if self.stats['successful_historizations'] > 0:
                    total_time = (self.stats['avg_processing_time'] * 
                                (self.stats['successful_historizations'] - 1))
                    self.stats['avg_processing_time'] = (
                        (total_time + result.processing_time) / self.stats['successful_historizations']
                    )
                
                self.logger.debug(f"✅ Historized {token_addr[:8]}... (scores: V={result.viability_score:.1f}, R={result.risk_score:.1f})")
            else:
                self.stats['failed_historizations'] += 1
                self.logger.warning(f"❌ Historization failed for {token_addr[:8]}...")
        
        return len(batch.tokens), successful_count
    
    @db_retry(max_retries=3, delay=0.3)
    def _historize_token(self, token_address: str) -> HistorizationResult:
        """Historize a single token"""
        start_time = time.time()
        
        try:
            # Create snapshot using history repository
            success = self.history_repo.create_snapshot(token_address)
            
            if success:
                # Get the created snapshot for analysis
                recent_snapshots = self.history_repo._get_recent_history(token_address, limit=2)
                
                if recent_snapshots:
                    latest_snapshot = recent_snapshots[0]
                    
                    return HistorizationResult(
                        token_address=token_address,
                        success=True,
                        snapshot_id=latest_snapshot.get('id'),
                        processing_time=time.time() - start_time,
                        viability_score=latest_snapshot.get('viability_score', 0),
                        risk_score=latest_snapshot.get('risk_score', 0),
                        momentum_score=latest_snapshot.get('momentum_score', 0)
                    )
                else:
                    return HistorizationResult(
                        token_address=token_address,
                        success=True,
                        processing_time=time.time() - start_time
                    )
            else:
                return HistorizationResult(
                    token_address=token_address,
                    success=False,
                    error_message="Snapshot creation failed",
                    processing_time=time.time() - start_time
                )
                
        except Exception as e:
            return HistorizationResult(
                token_address=token_address,
                success=False,
                error_message=str(e),
                processing_time=time.time() - start_time
            )
    
    def manually_historize_tokens(self, token_addresses: List[str]) -> Dict:
        """
        Manually trigger historization for specific tokens
        
        Args:
            token_addresses: List of token addresses to historize
            
        Returns:
            Dictionary with results
        """
        self.logger.info(f"🔧 Manual historization requested for {len(token_addresses)} tokens")
        
        # Create high-priority batch
        batch = HistorizationBatch(
            tokens=token_addresses,
            created_at=datetime.now(),
            priority=5,  # Highest priority
            batch_type="manual"
        )
        
        # Add to front of queue
        with self.queue_lock:
            self.processing_queue.insert(0, batch)
        
        # Process immediately
        try:
            result = asyncio.run(self._process_batch(batch))
            processed, successful = result
            
            return {
                'success': True,
                'processed': processed,
                'successful': successful,
                'failed': processed - successful,
                'processing_time': time.time()
            }
            
        except Exception as e:
            self.logger.error(f"Manual historization failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'processed': 0,
                'successful': 0
            }
    
    def analyze_token_trends(self, token_address: str, timeframe_hours: int = 24) -> Optional[TrendAnalysis]:
        """
        Analyze trends for a specific token
        
        Args:
            token_address: Token address to analyze
            timeframe_hours: Analysis timeframe in hours
            
        Returns:
            TrendAnalysis object or None
        """
        try:
            # Get historical data
            start_time = int(time.time()) - (timeframe_hours * 3600)
            historical_data = self.history_repo.get_token_history(
                token_address=token_address,
                start_time=start_time,
                limit=100
            )
            
            if len(historical_data) < 2:
                return None
            
            # Analyze trends
            price_trend = self._analyze_price_trend(historical_data)
            volume_trend = self._analyze_volume_trend(historical_data)
            holder_trend = self._analyze_holder_trend(historical_data)
            volatility_score = self._calculate_volatility_score(historical_data)
            momentum_score = self._calculate_momentum_score(historical_data)
            
            # Calculate prediction confidence
            confidence = self._calculate_prediction_confidence(historical_data)
            
            return TrendAnalysis(
                token_address=token_address,
                timeframe_hours=timeframe_hours,
                price_trend=price_trend,
                volume_trend=volume_trend,
                holder_trend=holder_trend,
                volatility_score=volatility_score,
                momentum_score=momentum_score,
                prediction_confidence=confidence
            )
            
        except Exception as e:
            self.logger.error(f"Error analyzing trends for {token_address}: {e}")
            return None
    
    def _analyze_price_trend(self, historical_data: List[Dict]) -> str:
        """Analyze price trend from historical data"""
        if len(historical_data) < 2:
            return 'stable'
        
        prices = [float(h.get('price_usd', 0)) for h in historical_data]
        
        # Calculate trend
        first_half_avg = sum(prices[:len(prices)//2]) / (len(prices)//2) if len(prices) >= 4 else prices[0]
        second_half_avg = sum(prices[len(prices)//2:]) / (len(prices) - len(prices)//2) if len(prices) >= 4 else prices[-1]
        
        change_pct = ((second_half_avg - first_half_avg) / first_half_avg * 100) if first_half_avg > 0 else 0
        
        if change_pct > 10:
            return 'up'
        elif change_pct < -10:
            return 'down'
        else:
            return 'stable'
    
    def _analyze_volume_trend(self, historical_data: List[Dict]) -> str:
        """Analyze volume trend from historical data"""
        if len(historical_data) < 2:
            return 'stable'
        
        volumes = [float(h.get('volume_24h', 0)) for h in historical_data]
        
        first_half_avg = sum(volumes[:len(volumes)//2]) / (len(volumes)//2) if len(volumes) >= 4 else volumes[0]
        second_half_avg = sum(volumes[len(volumes)//2:]) / (len(volumes) - len(volumes)//2) if len(volumes) >= 4 else volumes[-1]
        
        change_pct = ((second_half_avg - first_half_avg) / first_half_avg * 100) if first_half_avg > 0 else 0
        
        if change_pct > 20:
            return 'up'
        elif change_pct < -20:
            return 'down'
        else:
            return 'stable'
    
    def _analyze_holder_trend(self, historical_data: List[Dict]) -> str:
        """Analyze holder count trend from historical data"""
        if len(historical_data) < 2:
            return 'stable'
        
        holders = [int(h.get('holder_count', 0)) for h in historical_data]
        
        first_half_avg = sum(holders[:len(holders)//2]) / (len(holders)//2) if len(holders) >= 4 else holders[0]
        second_half_avg = sum(holders[len(holders)//2:]) / (len(holders) - len(holders)//2) if len(holders) >= 4 else holders[-1]
        
        change_pct = ((second_half_avg - first_half_avg) / first_half_avg * 100) if first_half_avg > 0 else 0
        
        if change_pct > 5:
            return 'up'
        elif change_pct < -5:
            return 'down'
        else:
            return 'stable'
    
    def _calculate_volatility_score(self, historical_data: List[Dict]) -> float:
        """Calculate volatility score (0-100)"""
        try:
            prices = [float(h.get('price_usd', 0)) for h in historical_data if h.get('price_usd', 0) > 0]
            
            if len(prices) < 2:
                return 0.0
            
            # Calculate price changes
            changes = []
            for i in range(1, len(prices)):
                if prices[i-1] > 0:
                    change = abs((prices[i] - prices[i-1]) / prices[i-1] * 100)
                    changes.append(change)
            
            if not changes:
                return 0.0
            
            # Average absolute change as volatility score
            avg_volatility = sum(changes) / len(changes)
            
            # Normalize to 0-100 scale
            return min(100.0, avg_volatility)
            
        except Exception:
            return 0.0
    
    def _calculate_momentum_score(self, historical_data: List[Dict]) -> float:
        """Calculate momentum score (-100 to +100)"""
        try:
            if len(historical_data) < 3:
                return 0.0
            
            # Price momentum
            recent_prices = [float(h.get('price_usd', 0)) for h in historical_data[-3:]]
            if len(recent_prices) >= 2 and recent_prices[0] > 0:
                price_momentum = ((recent_prices[-1] - recent_prices[0]) / recent_prices[0] * 100)
            else:
                price_momentum = 0.0
            
            # Volume momentum
            recent_volumes = [float(h.get('volume_24h', 0)) for h in historical_data[-3:]]
            if len(recent_volumes) >= 2 and recent_volumes[0] > 0:
                volume_momentum = ((recent_volumes[-1] - recent_volumes[0]) / recent_volumes[0] * 100)
            else:
                volume_momentum = 0.0
            
            # Combined momentum (weighted)
            momentum = (price_momentum * 0.7) + (volume_momentum * 0.3)
            
            return max(-100.0, min(100.0, momentum))
            
        except Exception:
            return 0.0
    
    def _calculate_prediction_confidence(self, historical_data: List[Dict]) -> float:
        """Calculate confidence in trend predictions (0-100)"""
        try:
            # Base confidence on data consistency and quantity
            data_points = len(historical_data)
            
            # More data points = higher confidence
            quantity_score = min(100.0, (data_points / 20) * 100)
            
            # Consistency in trends = higher confidence
            prices = [float(h.get('price_usd', 0)) for h in historical_data if h.get('price_usd', 0) > 0]
            
            if len(prices) < 3:
                return max(20.0, quantity_score * 0.5)
            
            # Calculate trend consistency
            directional_changes = 0
            for i in range(2, len(prices)):
                prev_direction = 1 if prices[i-1] > prices[i-2] else -1
                curr_direction = 1 if prices[i] > prices[i-1] else -1
                
                if prev_direction != curr_direction:
                    directional_changes += 1
            
            consistency_ratio = 1 - (directional_changes / (len(prices) - 2))
            consistency_score = consistency_ratio * 100
            
            # Combined confidence
            confidence = (quantity_score * 0.4) + (consistency_score * 0.6)
            
            return max(10.0, min(100.0, confidence))
            
        except Exception:
            return 25.0  # Default low confidence
    
    def _cleanup_old_snapshots(self):
        """Clean up old historical snapshots"""
        try:
            self.logger.debug("🧹 Cleaning up old snapshots...")
            
            deleted_count = self.history_repo.cleanup_old_history(
                days_to_keep=self.historization_config['retention_days']
            )
            
            if deleted_count > 0:
                self.logger.info(f"🗑️ Cleaned up {deleted_count} old snapshots")
            
        except Exception as e:
            self.logger.error(f"Error cleaning up old snapshots: {e}")
    
    def get_processing_statistics(self) -> Dict:
        """Get current processing statistics"""
        stats = self.stats.copy()
        
        # Calculate success rate
        total_attempts = stats['successful_historizations'] + stats['failed_historizations']
        if total_attempts > 0:
            stats['success_rate'] = (stats['successful_historizations'] / total_attempts) * 100
        else:
            stats['success_rate'] = 0.0
        
        # Queue status
        with self.queue_lock:
            stats['queue_size'] = len(self.processing_queue)
            stats['queue_priorities'] = [b.priority for b in self.processing_queue]
        
        # Processing status
        stats['processor_running'] = self.running
        stats['last_priority_update'] = datetime.fromtimestamp(self.last_priority_update).isoformat() if self.last_priority_update else None
        stats['tracked_token_count'] = len(self.token_priorities)
        
        return stats
    
    def get_token_priority(self, token_address: str) -> float:
        """Get priority score for a specific token"""
        return self.token_priorities.get(token_address, 50.0)
    
    def force_historization_cycle(self) -> Dict:
        """Force a complete historization cycle"""
        self.logger.info("🔧 Forcing complete historization cycle...")
        
        try:
            # Update priorities
            self._update_token_priorities()
            
            # Schedule all eligible tokens
            self._schedule_tokens_for_historization()
            
            # Process all batches
            with self.queue_lock:
                batch_count = len(self.processing_queue)
            
            if batch_count > 0:
                asyncio.run(self._process_historization_batches())
                
                return {
                    'success': True,
                    'batches_processed': batch_count,
                    'message': f'Processed {batch_count} batches'
                }
            else:
                return {
                    'success': True,
                    'batches_processed': 0,
                    'message': 'No tokens needed historization'
                }
                
        except Exception as e:
            self.logger.error(f"Force historization cycle failed: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def reset_statistics(self):
        """Reset processing statistics"""
        self.stats = {
            'total_snapshots_created': 0,
            'successful_historizations': 0,
            'failed_historizations': 0,
            'avg_processing_time': 0.0,
            'tokens_analyzed': 0,
            'trends_identified': 0,
            'last_processing_time': None,
            'by_token_type': defaultdict(int),
            'processing_errors': []
        }
        
        self.logger.info("📊 Historization processor statistics reset")


def create_historization_processor(
    db_connection: DatabaseConnection,
    config,
    logger: Optional[logging.Logger] = None
) -> HistorizationProcessor:
    """
    Factory function to create a configured historization processor
    
    Args:
        db_connection: Database connection
        config: Configuration object
        logger: Optional logger instance
        
    Returns:
        Configured HistorizationProcessor instance
    """
    return HistorizationProcessor(
        db_connection=db_connection,
        config=config,
        logger=logger
    )