#!/usr/bin/env python3
"""
Token Data Synchronization Backend with Historical Tracking
Continuously monitors new tokens from transactions table and enriches them with DexScreener data
Now includes historical tracking and intelligent filtering
"""

#script à finir 
import sqlite3
import requests
import time
import logging
import json
import math
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Set, Tuple
import threading
from dataclasses import dataclass
import sys
import signal
import functools
from collections import deque, defaultdict
import threading
import asyncio
import aiohttp


# Configuration
CONFIG = {
    'db_path': 'solana_wallet_monitor.db',
    'api_rate_limit': 1.5,  # seconds between API calls
    'batch_size':30,       # tokens to process per batch
    'update_interval': 80,  # seconds between sync cycles
    'price_update_interval': 80,  # 1 minute for price updates
    'dashboard_update_interval': 120, # 2.5 minutes pour dashboard tokens
    'max_retries': 5,
    'pumpfun_rate_limit': 1.2,  # Rate limit spécifique Pump.fun
    'pumpfun_batch_size': 25,   # Batch plus petit pour Pump.fun
    'request_timeout': 10,
    'retry_failed_after_days': 7,  # Réessayer les tokens flaggés après X jours
    'max_failed_attempts': 1,      # Nombre max de tentatives avant flagging définitif
    'historization_interval': 7200,  # 30 minutes entre historisations
    'dead_token_check_interval': 3600,  # 1 heure pour vérifier tokens morts
    'db_timeout': 60.0,
    'db_retry_delay': 0.2,  # Nouveau paramètre
    'db_max_retries': 5,    # Nouveau paramètre
    'max_concurrent_batches': 3,      # Nombre max de lots traités en parallèle
    'batch_pause_seconds': 2.0,       # Pause entre lots pour éviter surcharge
    'batch_retry_failed': True,       # Réessayer les tokens échoués dans un batch
    'batch_log_detailed': False,      # Log détaillé pour debug

    'known_quote_tokens': {
        'So11111111111111111111111111111111111111112',  # SOL
        'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
        'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',  # USDT
        '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R',  # RAY
        'mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So'   # mSOL
    }
}



@dataclass
class ApiCallStats:
    """Statistics for a specific API endpoint"""
    total_calls: int = 0
    total_duration: float = 0.0
    calls_5m: deque = None
    calls_30m: deque = None
    calls_1h: deque = None
    
    def __post_init__(self):
        if self.calls_5m is None:
            self.calls_5m = deque()
        if self.calls_30m is None:
            self.calls_30m = deque()
        if self.calls_1h is None:
            self.calls_1h = deque()

class ApiStatsTracker:
    """Track detailed API statistics per endpoint"""
    
    def __init__(self, db_service=None):
        self.stats = defaultdict(lambda: ApiCallStats())
        self.lock = threading.Lock()
        self.db_service = db_service  # Référence au service pour accès DB
        self.current_cycle_id = None
    
    def set_current_cycle(self, cycle_id: int):
        """Set the current sync cycle ID for tracking"""
        self.current_cycle_id = cycle_id

    def record_call(self, api_name: str, duration: float, success: bool = True, 
                   http_status: int = None, error_msg: str = None):
        """Record an API call with duration and store in database"""
        current_time = time.time()
        duration_ms = int(duration * 1000)  # Convert to milliseconds
        
        with self.lock:
            # Update in-memory stats (existing logic)
            api_stats = self.stats[api_name]
            api_stats.total_calls += 1
            api_stats.total_duration += duration
            
            call_record = (current_time, duration)
            api_stats.calls_5m.append(call_record)
            api_stats.calls_30m.append(call_record)
            api_stats.calls_1h.append(call_record)
            
            self._clean_old_records(api_stats, current_time)
        
        # Store in database (non-blocking)
        if self.db_service:
            try:
                self._store_api_call_to_db(
                    api_name, int(current_time), duration_ms, 
                    success, http_status, error_msg
                )
            except Exception as e:
                # Don't fail the API call if DB storage fails
                print(f"Warning: Failed to store API metric to DB: {e}")
    
    def _store_api_call_to_db(self, api_name: str, timestamp: int, duration_ms: int,
                         success: bool, http_status: int, error_msg: str):
        """Store API call metrics to database - DEBUG VERSION"""
        try:
            print(f"🔍 DEBUG DB: Storing {api_name} - cycle: {self.current_cycle_id}, duration: {duration_ms}ms")
            
            with self.db_service.get_db_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO api_metrics (
                        api_name, call_timestamp, duration_ms, success,
                        http_status_code, error_message, sync_cycle_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (api_name, timestamp, duration_ms, success, 
                    http_status, error_msg, self.current_cycle_id))
                
                conn.commit()
                
                # DEBUG: Verify insertion
                cursor.execute("SELECT last_insert_rowid()")
                row_id = cursor.fetchone()[0]
                print(f"🔍 DEBUG DB: Inserted API metric with ID {row_id}")
                
                return True
                
        except Exception as e:
            print(f"❌ DEBUG DB: Failed to store API metric: {e}")
            # Log but don't raise - DB storage is not critical for API functionality
            if hasattr(self.db_service, 'logger'):
                self.db_service.logger.debug(f"Failed to store API metric: {e}")
            return False

    def _clean_old_records(self, api_stats: ApiCallStats, current_time: float):
        """Remove old records from time windows"""
        # 5 minutes
        while api_stats.calls_5m and current_time - api_stats.calls_5m[0][0] > 300:
            api_stats.calls_5m.popleft()
        
        # 30 minutes
        while api_stats.calls_30m and current_time - api_stats.calls_30m[0][0] > 1800:
            api_stats.calls_30m.popleft()
        
        # 1 hour
        while api_stats.calls_1h and current_time - api_stats.calls_1h[0][0] > 3600:
            api_stats.calls_1h.popleft()
    
    def get_stats(self, api_name: str = None) -> Dict:
        """Get statistics for specific API or all APIs"""
        current_time = time.time()
        
        with self.lock:
            if api_name:
                if api_name not in self.stats:
                    return {}
                return self._format_api_stats(api_name, self.stats[api_name], current_time)
            else:
                # Return all APIs
                result = {}
                for name, stats in self.stats.items():
                    result[name] = self._format_api_stats(name, stats, current_time)
                return result
    
    def _format_api_stats(self, name: str, stats: ApiCallStats, current_time: float) -> Dict:
        """Format stats for a single API"""
        # Clean old records first
        self._clean_old_records(stats, current_time)
        
        # Calculate averages
        avg_duration = stats.total_duration / stats.total_calls if stats.total_calls > 0 else 0
        
        # Count calls in time windows
        calls_5m = len(stats.calls_5m)
        calls_30m = len(stats.calls_30m)
        calls_1h = len(stats.calls_1h)
        
        # Calculate average durations for time windows
        avg_5m = sum(d for _, d in stats.calls_5m) / calls_5m if calls_5m > 0 else 0
        avg_30m = sum(d for _, d in stats.calls_30m) / calls_30m if calls_30m > 0 else 0
        avg_1h = sum(d for _, d in stats.calls_1h) / calls_1h if calls_1h > 0 else 0
        
        return {
            'total_calls': stats.total_calls,
            'total_duration_seconds': round(stats.total_duration, 2),
            'avg_duration_seconds': round(avg_duration, 3),
            'calls_5m': calls_5m,
            'calls_30m': calls_30m,
            'calls_1h': calls_1h,
            'avg_duration_5m': round(avg_5m, 3),
            'avg_duration_30m': round(avg_30m, 3),
            'avg_duration_1h': round(avg_1h, 3),
            'rate_per_minute_5m': round(calls_5m / 5, 2),
            'rate_per_minute_30m': round(calls_30m / 30, 2),
            'rate_per_minute_1h': round(calls_1h / 60, 2)
        }


@dataclass
class TokenData:
    """Data structure for token information"""
    address: str
    symbol: str = None
    name: str = None
    decimals: int = 9
    price_usd: float = 0.0
    logo_uri: str = None
    coingecko_id: str = None
    is_verified: bool = False
    timestamp_token_created: int = 0
    creator_address: str = None  
    bonding_curve_progress: float = 0.0    
    holder_count: int = 0  
    market_cap: float = 0.0
    volume_5m: float = 0.0
    volume_1h: float = 0.0
    volume_6h: float = 0.0
    volume_24h: float = 0.0
    price_change_5m: float = 0.0
    price_change_1h: float = 0.0
    price_change_6h: float = 0.0
    price_change_24h: float = 0.0
    liquidity_usd: float = 0.0
    liquidity_sol: float = 0.0
    fdv: float = 0.0
    metadata_source: str = None
    original_address: str = None  # For tracking pair -> token conversion

@dataclass
class HistoricalSnapshot:
    """Structure for historical token data snapshot"""
    token_address: str
    snapshot_timestamp: int
    previous_snapshot_id: Optional[int] = None
    # Metrics
    price_usd: float = 0.0
    market_cap: float = 0.0
    volume_24h: float = 0.0
    holder_count: int = 0
    liquidity_usd: float = 0.0
    # Calculated deltas
    price_delta_usd: float = 0.0
    market_cap_delta: float = 0.0
    volume_24h_delta: float = 0.0
    holder_count_delta: int = 0
    # Scores
    viability_score: float = 50.0
    risk_score: float = 50.0
    momentum_score: float = 0.0

def db_retry(max_retries=3, delay=0.2):
    """Decorator to automatically retry database operations"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(self, *args, **kwargs)
                except sqlite3.OperationalError as e:
                    if "database is locked" in str(e) and attempt < max_retries - 1:
                        wait_time = delay * (2 ** attempt)
                        self.logger.warning(f"Database locked in {func.__name__}, retry {attempt + 1}/{max_retries} in {wait_time:.2f}s")
                        time.sleep(wait_time)
                        continue
                    else:
                        self.logger.error(f"Database error in {func.__name__} after {max_retries} attempts: {e}")
                        raise
                except Exception as e:
                    self.logger.error(f"Unexpected error in {func.__name__}: {e}")
                    raise
            return None
        return wrapper
    return decorator


class TokenAnalyzer:
    """Advanced token analysis and scoring system"""
    
    def __init__(self):
        self.logger = logging.getLogger('TokenAnalyzer')
    
    def calculate_viability_score(self, current_data: TokenData, historical_data: List[Dict] = None) -> float:
        """Calculate token viability score (0-100)"""
        score = 0.0
        
        try:
            # 1. Market Cap Stability (25 points)
            if current_data.market_cap > 1000000:  # >1M
                score += 25
            elif current_data.market_cap > 100000:  # >100K
                score += 20
            elif current_data.market_cap > 10000:   # >10K
                score += 15
            elif current_data.market_cap > 1000:    # >1K
                score += 10
            
            # 2. Liquidity Health (25 points)
            if current_data.market_cap > 0:
                liquidity_ratio = current_data.liquidity_usd / current_data.market_cap
                if liquidity_ratio > 0.15:
                    score += 25
                elif liquidity_ratio > 0.10:
                    score += 20
                elif liquidity_ratio > 0.05:
                    score += 15
                elif liquidity_ratio > 0.02:
                    score += 10
            
            # 3. Volume Activity (20 points)
            if current_data.market_cap > 0:
                volume_ratio = current_data.volume_24h / current_data.market_cap
                if volume_ratio > 0.5:
                    score += 20
                elif volume_ratio > 0.2:
                    score += 15
                elif volume_ratio > 0.1:
                    score += 10
                elif volume_ratio > 0.05:
                    score += 5
            
            # 4. Holder Count (15 points)
            if current_data.holder_count > 1000:
                score += 15
            elif current_data.holder_count > 500:
                score += 12
            elif current_data.holder_count > 100:
                score += 10
            elif current_data.holder_count > 50:
                score += 8
            elif current_data.holder_count > 10:
                score += 5
            
            # 5. Price Stability (15 points)
            if abs(current_data.price_change_24h) < 10:  # <10% change
                score += 15
            elif abs(current_data.price_change_24h) < 25:  # <25% change
                score += 10
            elif abs(current_data.price_change_24h) < 50:  # <50% change
                score += 5
            
            # Bonus/Penalty adjustments
            if current_data.is_verified:
                score += 5
            
            if historical_data and len(historical_data) >= 2:
                # Penalize if consistently declining
                recent_prices = [h.get('price_usd', 0) for h in historical_data[-3:]]
                if len(recent_prices) >= 2 and all(recent_prices[i] <= recent_prices[i-1] for i in range(1, len(recent_prices))):
                    score -= 10
        
        except Exception as e:
            self.logger.error(f"Error calculating viability score: {e}")
            return 50.0
        
        return max(0.0, min(100.0, score))
    
    def calculate_risk_score(self, current_data: TokenData, historical_data: List[Dict] = None) -> float:
        """Calculate token risk score (0-100, higher = more risky)"""
        risk = 0.0
        
        try:
            # 1. Liquidity Risk (30 points)
            if current_data.market_cap > 0:
                liquidity_ratio = current_data.liquidity_usd / current_data.market_cap
                if liquidity_ratio < 0.02:
                    risk += 30
                elif liquidity_ratio < 0.05:
                    risk += 20
                elif liquidity_ratio < 0.10:
                    risk += 10
            
            # 2. Volume Risk (25 points)
            if current_data.volume_24h < 1000:  # Very low volume
                risk += 25
            elif current_data.volume_24h < 10000:
                risk += 15
            elif current_data.volume_24h < 50000:
                risk += 10
            
            # 3. Price Volatility Risk (25 points)
            if abs(current_data.price_change_24h) > 80:
                risk += 25
            elif abs(current_data.price_change_24h) > 50:
                risk += 15
            elif abs(current_data.price_change_24h) > 30:
                risk += 10
            
            # 4. Market Cap Risk (20 points)
            if current_data.market_cap < 1000:
                risk += 20
            elif current_data.market_cap < 10000:
                risk += 15
            elif current_data.market_cap < 100000:
                risk += 10
            
            # Historical trend analysis
            if historical_data and len(historical_data) >= 3:
                # Check for consistent decline
                recent_volumes = [h.get('volume_24h', 0) for h in historical_data[-3:]]
                if len(recent_volumes) >= 2:
                    volume_declining = all(recent_volumes[i] <= recent_volumes[i-1] * 0.8 for i in range(1, len(recent_volumes)))
                    if volume_declining:
                        risk += 10
        
        except Exception as e:
            self.logger.error(f"Error calculating risk score: {e}")
            return 50.0
        
        return max(0.0, min(100.0, risk))
    
    def calculate_momentum_score(self, current_data: TokenData, historical_data: List[Dict] = None) -> float:
        """Calculate momentum score (-100 to +100)"""
        momentum = 0.0
        
        try:
            # 1. Price momentum (40%)
            price_momentum = current_data.price_change_24h
            momentum += price_momentum * 0.4
            
            # 2. Volume momentum (30%)
            if historical_data and len(historical_data) >= 2:
                current_volume = current_data.volume_24h
                previous_volume = historical_data[-1].get('volume_24h', 0)
                if previous_volume > 0:
                    volume_change = ((current_volume - previous_volume) / previous_volume) * 100
                    momentum += volume_change * 0.3
            
            # 3. Holder momentum (20%)
            if historical_data and len(historical_data) >= 2:
                current_holders = current_data.holder_count
                previous_holders = historical_data[-1].get('holder_count', 0)
                if previous_holders > 0:
                    holder_change = ((current_holders - previous_holders) / previous_holders) * 100
                    momentum += holder_change * 0.2
            
            # 4. Liquidity momentum (10%)
            if historical_data and len(historical_data) >= 2:
                current_liquidity = current_data.liquidity_usd
                previous_liquidity = historical_data[-1].get('liquidity_usd', 0)
                if previous_liquidity > 0:
                    liquidity_change = ((current_liquidity - previous_liquidity) / previous_liquidity) * 100
                    momentum += liquidity_change * 0.1
        
        except Exception as e:
            self.logger.error(f"Error calculating momentum score: {e}")
            return 0.0
        
        return max(-100.0, min(100.0, momentum))
    
    def detect_dead_token(self, current_data: TokenData, historical_data: List[Dict] = None) -> Tuple[bool, str]:
        """Detect if a token should be marked as dead"""
        reasons = []
        
        try:
            # 1. Price crash (>90% drop in 24h)
            if current_data.price_change_24h < -90:
                reasons.append("price_crash_90pct")
            
            # 2. Volume death (volume < $100 for 24h)
            if current_data.volume_24h < 100:
                reasons.append("volume_death")
            
            # 3. Liquidity drain (liquidity < 1% of market cap)
            if current_data.market_cap > 0:
                liquidity_ratio = current_data.liquidity_usd / current_data.market_cap
                if liquidity_ratio < 0.01:
                    reasons.append("liquidity_drain")
            
            # 4. Market cap too low
            if current_data.market_cap < 500:  # Less than $500
                reasons.append("market_cap_too_low")
            
            # 5. Historical decline pattern
            if historical_data and len(historical_data) >= 5:
                # Check if consistently declining for 5 snapshots
                recent_prices = [h.get('price_usd', 0) for h in historical_data[-5:]]
                if len(recent_prices) == 5:
                    declining_trend = all(recent_prices[i] <= recent_prices[i-1] * 0.9 for i in range(1, 5))
                    if declining_trend:
                        reasons.append("consistent_decline")
            
            # 6. Zero holders (if data available)
            if current_data.holder_count == 0:
                reasons.append("zero_holders")
            
            # Decision logic
            critical_reasons = ["price_crash_90pct", "liquidity_drain", "market_cap_too_low"]
            has_critical = any(reason in critical_reasons for reason in reasons)
            
            # Mark as dead if:
            # - Has critical reason, OR
            # - Has 3+ reasons, OR
            # - Has volume death + another reason
            is_dead = (has_critical or 
                      len(reasons) >= 3 or 
                      ("volume_death" in reasons and len(reasons) >= 2))
            
            death_reason = ", ".join(reasons) if is_dead else None
            
            return is_dead, death_reason
        
        except Exception as e:
            self.logger.error(f"Error detecting dead token: {e}")
            return False, None

class TokenSyncService:
    """Main service for token synchronization with historical tracking"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.running = False
        self.logger = self._setup_logger()
        self.analyzer = TokenAnalyzer()
        try:
            self.api_tracker = ApiStatsTracker(db_service=self)  # ← Modification
            self.logger.info("✅ API tracker initialized successfully")
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize API tracker: {e}")
            raise
        
        self.current_sync_cycle_id = None
        # Request session for connection pooling
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://pump.fun/'
        })
        
        # Statistics
        self.stats = {
            'processed_tokens': 0,
            'successful_updates': 0,
            'failed_updates': 0,
            'api_calls': 0,
            'tokens_historized': 0,
            'tokens_marked_dead': 0,
            'start_time': None
        }

        
    
        self.logger.info(f"🔧 API tracker verification: {type(self.api_tracker)}")

    def test_api_tracking(self):
        """Test method to verify API tracking is working"""
        self.logger.info("🧪 Testing API tracking...")
        
        # Record a test call
        self.api_tracker.record_call('test_api', 1.5)
        
        # Get stats
        stats = self.api_tracker.get_stats()
        self.logger.info(f"Test stats: {stats}")
        
        if 'test_api' in stats:
            self.logger.info("✅ API tracking is working correctly")
        else:
            self.logger.error("❌ API tracking is not working")
        
        return 'test_api' in stats

    def _setup_logger(self) -> logging.Logger:
        """Setup logging configuration"""
        logger = logging.getLogger('TokenSync')
        logger.setLevel(logging.DEBUG)
        
        # Console handler with UTF-8 encoding
        handler = logging.StreamHandler()
        handler.stream = open(handler.stream.fileno(), mode='w', encoding='utf-8', buffering=1)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
        # File handler with UTF-8 encoding
        file_handler = logging.FileHandler('token_sync.log', encoding='utf-8')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        return logger
    
    def get_db_connection(self, retries: int = 5, delay: float = 0.1) -> sqlite3.Connection:
        """Get database connection with enhanced error handling and retry logic"""
        for attempt in range(retries):
            try:
                conn = sqlite3.connect(
                    self.db_path, 
                    timeout=60.0,  # Augmenter le timeout
                    check_same_thread=False  # Permettre l'utilisation dans plusieurs threads
                )
                conn.row_factory = sqlite3.Row
                
                # Configuration optimisée pour éviter les locks
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL") 
                conn.execute("PRAGMA cache_size=-65536")
                conn.execute("PRAGMA temp_store=memory")
                conn.execute("PRAGMA busy_timeout=60000")  # 60 secondes
                conn.execute("PRAGMA wal_autocheckpoint=1000")  # Checkpoint automatique
                
                # Test de la connexion
                conn.execute("SELECT 1").fetchone()
                
                return conn
                
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < retries - 1:
                    wait_time = delay * (2 ** attempt)  # Backoff exponentiel
                    self.logger.warning(f"Database locked, retry {attempt + 1}/{retries} in {wait_time:.2f}s")
                    time.sleep(wait_time)
                    continue
                else:
                    self.logger.error(f"Database connection error after {retries} attempts: {e}")
                    raise
            except Exception as e:
                self.logger.error(f"Unexpected database connection error: {e}")
                raise
    
    def check_database_health(self) -> bool:
        """Check database health and fix common issues"""
        try:
            conn = self.get_db_connection()
            try:
                cursor = conn.cursor()
                
                # Test basic connectivity
                cursor.execute("SELECT 1").fetchone()
                
                # Check for WAL mode
                cursor.execute("PRAGMA journal_mode")
                journal_mode = cursor.fetchone()[0]
                if journal_mode != 'wal':
                    self.logger.warning(f"Database not in WAL mode: {journal_mode}")
                    cursor.execute("PRAGMA journal_mode=WAL")
                    
                # Check and fix any database integrity issues
                cursor.execute("PRAGMA integrity_check")
                integrity = cursor.fetchone()[0]
                if integrity != 'ok':
                    self.logger.error(f"Database integrity issue: {integrity}")
                    return False
                    
                # Optimize database
                cursor.execute("PRAGMA optimize")
                
                self.logger.info("✅ Database health check passed")
                return True
                
            finally:
                conn.close()
                
        except Exception as e:
            self.logger.error(f"❌ Database health check failed: {e}")
            return False

    def historize_token_data(self, token_address: str, current_data: TokenData = None) -> bool:
        """
        Historize current token data before updating
        """
        max_retries = 5
        retry_delay = 0.2
        for attempt in range(max_retries):
            conn = None
            try:
                conn = self.get_db_connection()
                with conn:  # Utilise un context manager pour auto-commit/rollback
                    cursor = conn.cursor()
                    cursor.execute("BEGIN IMMEDIATE")  # Lock immédiat mais court
                    # Get the last snapshot ID for this token
                    cursor.execute("""
                        SELECT id FROM tokens_history 
                        WHERE token_address = ? 
                        ORDER BY snapshot_timestamp DESC 
                        LIMIT 1
                    """, (token_address,))
                    last_snapshot = cursor.fetchone()
                    previous_snapshot_id = last_snapshot[0] if last_snapshot else None
                
                    # Get historical data for score calculations
                    cursor.execute("""
                        SELECT * FROM tokens_history 
                        WHERE token_address = ? 
                        ORDER BY snapshot_timestamp DESC 
                        LIMIT 10
                    """, (token_address,))
                    historical_data = [dict(row) for row in cursor.fetchall()]
                
                    current_timestamp = int(time.time())
                
                    if current_data is None:
                        # Mode UPDATE : utiliser les données actuelles de la DB (avant mise à jour)
                        cursor.execute("""
                            SELECT * FROM tokens WHERE address = ?
                        """, (token_address,))
                        token_row = cursor.fetchone()
                        if not token_row:
                            self.logger.warning(f"No current data found for token {token_address}")
                            conn.close()
                            return False


                        def safe_get(row, column, default=0.0):
                            """Safely get value from sqlite3.Row with None handling"""
                            try:
                                value = row[column] if column in row.keys() else default
                                return value if value is not None else default
                            except (KeyError, TypeError):
                                return default

                        snapshot_data = {
                            'price_usd': safe_get(token_row, 'price_usd', 0.0),
                            'market_cap': safe_get(token_row, 'market_cap', 0.0),
                            'fdv': safe_get(token_row, 'fdv', 0.0),
                            'liquidity_usd': safe_get(token_row, 'liquidity_usd', 0.0),
                            'liquidity_sol': safe_get(token_row, 'liquidity_sol', 0.0),
                            'liquidity_mc_ratio': safe_get(token_row, 'liquidity_mc_ratio', 0.0),
                            'volume_mc_ratio': safe_get(token_row, 'volume_mc_ratio', 0.0),
                            'price_volatility_1h': safe_get(token_row, 'price_volatility_1h', 0.0),
                            'volume_5m': safe_get(token_row, 'volume_5m', 0.0),
                            'volume_1h': safe_get(token_row, 'volume_1h', 0.0),
                            'volume_6h': safe_get(token_row, 'volume_6h', 0.0),
                            'volume_24h': safe_get(token_row, 'volume_24h', 0.0),
                            'price_change_5m': safe_get(token_row, 'price_change_5m', 0.0),
                            'price_change_1h': safe_get(token_row, 'price_change_1h', 0.0),
                            'price_change_6h': safe_get(token_row, 'price_change_6h', 0.0),
                            'price_change_24h': safe_get(token_row, 'price_change_24h', 0.0),
                            'holder_count': safe_get(token_row, 'holder_count', 0),
                            'bonding_curve_progress': safe_get(token_row, 'bonding_curve_progress', 0.0),
                            # ✅ FIX: Ces champs étaient mal récupérés
                            'top_holder_percentage': safe_get(token_row, 'top_holder_percentage', 0.0),
                            'top_10_holders_percentage': safe_get(token_row, 'top_10_holders_percentage', 0.0),
                            'insider_holders_count': safe_get(token_row, 'insider_holders_count', 0),
                            'insider_networks_detected': safe_get(token_row, 'insider_networks_detected', 0),
                            'lp_providers_count': safe_get(token_row, 'lp_providers_count', 0),
                            'has_low_liquidity': safe_get(token_row, 'has_low_liquidity', False),
                            'rug_risk_score': safe_get(token_row, 'rug_risk_score', 50),
                            'rug_raw_score': safe_get(token_row, 'rug_raw_score', 0),
                            'is_rugged': safe_get(token_row, 'is_rugged', False),
                            'risk_count': safe_get(token_row, 'risk_count', 0),
                            'symbol': safe_get(token_row, 'symbol', ''),
                            'name': safe_get(token_row, 'name', ''),
                            'decimals': safe_get(token_row, 'decimals', 9),
                            'creator_address': safe_get(token_row, 'creator_address', None),
                            'logo_uri': safe_get(token_row, 'logo_uri', None),
                            'is_verified': safe_get(token_row, 'is_verified', False),
                            'metadata_source': safe_get(token_row, 'metadata_source', None)
                        }

                        if snapshot_data['market_cap'] > 0:
                            snapshot_data['liquidity_mc_ratio'] = snapshot_data['liquidity_usd'] / snapshot_data['market_cap']
                            snapshot_data['volume_mc_ratio'] = snapshot_data['volume_24h'] / snapshot_data['market_cap']
                        else:
                            snapshot_data['liquidity_mc_ratio'] = 0.0
                            snapshot_data['volume_mc_ratio'] = 0.0

                        score_data = TokenData(
                            address=token_address,
                            symbol=snapshot_data['symbol'],
                            price_usd=snapshot_data['price_usd'],
                            market_cap=snapshot_data['market_cap'],
                            fdv=snapshot_data['fdv'],
                            volume_5m=snapshot_data['volume_5m'],
                            volume_1h=snapshot_data['volume_1h'],
                            volume_6h=snapshot_data['volume_6h'],
                            volume_24h=snapshot_data['volume_24h'],
                            price_change_5m=snapshot_data['price_change_5m'],
                            price_change_1h=snapshot_data['price_change_1h'],
                            price_change_6h=snapshot_data['price_change_6h'],
                            price_change_24h=snapshot_data['price_change_24h'],
                            holder_count=snapshot_data['holder_count'],
                            liquidity_usd=snapshot_data['liquidity_usd'],
                            liquidity_sol=snapshot_data['liquidity_sol'],
                            bonding_curve_progress=snapshot_data['bonding_curve_progress']
                        )
                        self.logger.debug(f"📊 Historizing from DB for {token_address[:8]}... - TH: {snapshot_data['top_holder_percentage']:.2f}%, T10H: {snapshot_data['top_10_holders_percentage']:.2f}%")

                    else:
                        snapshot_data = {
                            'price_usd': current_data.price_usd,
                            'market_cap': current_data.market_cap,
                            'fdv': current_data.fdv,
                            'liquidity_usd': current_data.liquidity_usd,
                            'liquidity_sol': current_data.liquidity_sol,
                            'liquidity_mc_ratio': (current_data.liquidity_usd / current_data.market_cap) if current_data.market_cap > 0 else 0.0,
                            'volume_mc_ratio': (current_data.volume_24h / current_data.market_cap) if current_data.market_cap > 0 else 0.0,
                            'price_volatility_1h': getattr(current_data, 'price_volatility_1h', 0.0),
                            'volume_5m': current_data.volume_5m,
                            'volume_1h': current_data.volume_1h,
                            'volume_6h': current_data.volume_6h,
                            'volume_24h': current_data.volume_24h,
                            'price_change_5m': current_data.price_change_5m,
                            'price_change_1h': current_data.price_change_1h,
                            'price_change_6h': current_data.price_change_6h,
                            'price_change_24h': current_data.price_change_24h,
                            'holder_count': current_data.holder_count,
                            'bonding_curve_progress': current_data.bonding_curve_progress,
                            'top_holder_percentage': getattr(current_data, 'top_holder_percentage', 0.0),
                            'top_10_holders_percentage': getattr(current_data, 'top_10_holders_percentage', 0.0),
                            'insider_holders_count': getattr(current_data, 'insider_holders_count', 0),
                            'insider_networks_detected': getattr(current_data, 'insider_networks_detected', 0),
                            'lp_providers_count': getattr(current_data, 'lp_providers_count', 0),
                            'has_low_liquidity': getattr(current_data, 'has_low_liquidity', False),
                            'rug_risk_score': getattr(current_data, 'rug_risk_score', 50),
                            'rug_raw_score': getattr(current_data, 'rug_raw_score', 0),
                            'is_rugged': getattr(current_data, 'is_rugged', False),
                            'risk_count': getattr(current_data, 'risk_count', 0),
                            'symbol': current_data.symbol,
                            'name': current_data.name,
                            'decimals': current_data.decimals,
                            'creator_address': getattr(current_data, 'creator_address', None),
                            'logo_uri': getattr(current_data, 'logo_uri', None),
                            'is_verified': getattr(current_data, 'is_verified', False),
                            'metadata_source': getattr(current_data, 'metadata_source', None)
                        }
                        score_data = current_data
                    
                    deltas = {
                        'price_delta_usd': 0.0, 
                        'market_cap_delta': 0.0, 
                        'volume_24h_delta': 0.0, 
                        'holder_count_delta': 0,
                        'rug_risk_score_delta': 0.0,
                        'top_holder_percentage_delta': 0.0,
                        'insider_holders_delta': 0
                    }
                    
                    if historical_data:
                        last_snapshot_data = historical_data[0]
                        deltas['price_delta_usd'] = snapshot_data['price_usd'] - (last_snapshot_data.get('price_usd', 0) or 0)
                        deltas['market_cap_delta'] = snapshot_data['market_cap'] - (last_snapshot_data.get('market_cap', 0) or 0)
                        deltas['volume_24h_delta'] = snapshot_data['volume_24h'] - (last_snapshot_data.get('volume_24h', 0) or 0)
                        deltas['holder_count_delta'] = snapshot_data['holder_count'] - (last_snapshot_data.get('holder_count', 0) or 0)
                        deltas['rug_risk_score_delta'] = snapshot_data['rug_risk_score'] - (last_snapshot_data.get('rug_risk_score', 50) or 50)
                        deltas['top_holder_percentage_delta'] = snapshot_data['top_holder_percentage'] - (last_snapshot_data.get('top_holder_percentage', 0) or 0)
                        deltas['insider_holders_delta'] = snapshot_data['insider_holders_count'] - (last_snapshot_data.get('insider_holders_count', 0) or 0)
                    
                    viability_score = self.analyzer.calculate_viability_score(score_data, historical_data)
                    risk_score = self.analyzer.calculate_risk_score(score_data, historical_data)
                    momentum_score = self.analyzer.calculate_momentum_score(score_data, historical_data)
                    
                    # INSERT aligné au schéma tokens_history
                    cursor.execute("""
                        INSERT INTO tokens_history (
                            token_address,
                            price_usd, market_cap, fdv, liquidity_usd, liquidity_sol, liquidity_mc_ratio, volume_mc_ratio,
                            price_volatility_1h,
                            volume_5m, volume_1h, volume_6h, volume_24h,
                            price_change_5m, price_change_1h, price_change_6h, price_change_24h,
                            holder_count, bonding_curve_progress,
                            top_holder_percentage, top_10_holders_percentage, insider_holders_count, insider_networks_detected,
                            lp_providers_count, has_low_liquidity,
                            viability_score, risk_score, momentum_score,
                            rug_risk_score, rug_raw_score, is_rugged, risk_count,
                            creator_address, symbol, name, decimals, logo_uri, is_verified, metadata_source,
                            snapshot_timestamp, previous_snapshot_id,
                            price_delta_usd, market_cap_delta, volume_24h_delta, holder_count_delta,
                            rug_risk_score_delta, top_holder_percentage_delta, insider_holders_delta
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        token_address,
                        snapshot_data['price_usd'], snapshot_data['market_cap'], snapshot_data['fdv'],
                        snapshot_data['liquidity_usd'], snapshot_data['liquidity_sol'],
                        snapshot_data.get('liquidity_mc_ratio', 0.0), snapshot_data.get('volume_mc_ratio', 0.0),
                        snapshot_data.get('price_volatility_1h', 0.0),
                        snapshot_data['volume_5m'], snapshot_data['volume_1h'], snapshot_data['volume_6h'], snapshot_data['volume_24h'],
                        snapshot_data['price_change_5m'], snapshot_data['price_change_1h'], snapshot_data['price_change_6h'], snapshot_data['price_change_24h'],
                        snapshot_data['holder_count'], snapshot_data['bonding_curve_progress'],
                        snapshot_data['top_holder_percentage'], snapshot_data['top_10_holders_percentage'],
                        snapshot_data['insider_holders_count'], snapshot_data['insider_networks_detected'],
                        snapshot_data['lp_providers_count'], snapshot_data['has_low_liquidity'],
                        viability_score, risk_score, momentum_score,
                        snapshot_data['rug_risk_score'], snapshot_data['rug_raw_score'],
                        snapshot_data['is_rugged'], snapshot_data['risk_count'],
                        snapshot_data.get('creator_address'), snapshot_data['symbol'], snapshot_data['name'],
                        snapshot_data['decimals'], snapshot_data.get('logo_uri'),
                        snapshot_data.get('is_verified', False), snapshot_data.get('metadata_source'),
                        current_timestamp, previous_snapshot_id,
                        deltas['price_delta_usd'], deltas['market_cap_delta'], deltas['volume_24h_delta'], deltas['holder_count_delta'],
                        deltas.get('rug_risk_score_delta', 0.0),
                        deltas.get('top_holder_percentage_delta', 0.0),
                        deltas.get('insider_holders_delta', 0)
                    ))
                    
                    cursor.execute("""
                        UPDATE tokens 
                        SET last_historized_at = ?, history_snapshots_count = COALESCE(history_snapshots_count, 0) + 1
                        WHERE address = ?
                    """, (current_timestamp, token_address))
                    

                self.stats['tokens_historized'] += 1
                
                data_source = "new_data" if current_data else "db_data"
                self.logger.debug(f"✅ Historized token {token_address[:8]}... ({data_source}): V={viability_score:.1f}, R={risk_score:.1f}, M={momentum_score:.1f}, TH={snapshot_data['top_holder_percentage']:.1f}%")
                return True
                
            except sqlite3.OperationalError as e:
                if conn:
                    try:
                        conn.close()
                    except:
                        pass
                        
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    wait_time = base_delay * (2 ** attempt)  # Backoff exponentiel
                    self.logger.warning(f"Database locked during historization, retry {attempt + 1}/{max_retries} in {wait_time:.2f}s")
                    time.sleep(wait_time)
                    continue
                else:
                    self.logger.error(f"❌ Error historizing token {token_address} after {max_retries} attempts: {e}")
                    return False
                    
            except Exception as e:
                if conn:
                    try:
                        conn.close()
                    except:
                        pass
                self.logger.error(f"❌ Unexpected error historizing token {token_address}: {e}")
                return False

        return False

    
    def check_and_mark_dead_tokens(self) -> int:
        """Check for dead tokens and mark them"""
        marked_count = 0
        
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Get tokens that are not marked as dead and have recent data
                cursor.execute("""
                    SELECT address, symbol, price_usd, market_cap, volume_24h, 
                           holder_count, liquidity_usd, price_change_24h, 
                           viability_score, risk_score
                    FROM tokens 
                    WHERE is_dead = 0 
                    AND updated_at > datetime('now', '-7 days')
                """)
                
                tokens_to_check = cursor.fetchall()
                
                for token_row in tokens_to_check:
                    token_address = token_row['address']
                    
                    # Create TokenData object for analysis
                    token_data = TokenData(
                        address=token_address,
                        symbol=token_row['symbol'],
                        price_usd=token_row['price_usd'] or 0.0,
                        market_cap=token_row['market_cap'] or 0.0,
                        volume_24h=token_row['volume_24h'] or 0.0,
                        holder_count=token_row['holder_count'] or 0,
                        liquidity_usd=getattr(token_row, 'liquidity_usd', 0.0) or 0.0,
                        price_change_24h=token_row['price_change_24h'] or 0.0
                    )
                    
                    # Get historical data
                    cursor.execute("""
                        SELECT * FROM tokens_history 
                        WHERE token_address = ? 
                        ORDER BY snapshot_timestamp DESC 
                        LIMIT 10
                    """, (token_address,))
                    historical_data = [dict(row) for row in cursor.fetchall()]
                    
                    # Check if token should be marked as dead
                    is_dead, death_reason = self.analyzer.detect_dead_token(token_data, historical_data)
                    
                    if is_dead:
                        # Mark token as dead
                        cursor.execute("""
                            UPDATE tokens 
                            SET is_dead = 1, 
                                death_reason = ?, 
                                death_timestamp = ?
                            WHERE address = ?
                        """, (death_reason, int(time.time()), token_address))
                        
                        marked_count += 1
                        self.stats['tokens_marked_dead'] += 1
                        
                        self.logger.info(f"💀 Marked token {token_address} ({token_data.symbol}) as dead: {death_reason}")
                
                conn.commit()
                
        except Exception as e:
            self.logger.error(f"❌ Error checking dead tokens: {e}")
        
        return marked_count
    
    def get_pumpfun_data(self, token_address: str) -> Optional[TokenData]:
        """Get token data from Pump.fun API (unchanged from original)"""
        # URLs Pump.fun (comme dans le script qui fonctionne)
        pump_fun_urls = [
            f"https://frontend-api.pump.fun/coins/{token_address}",
            f"https://frontend-api-v2.pump.fun/coins/{token_address}",
            f"https://frontend-api-v3.pump.fun/coins/{token_address}",
        ]
        
        for i, url in enumerate(pump_fun_urls):
            try:
                start_time = time.time()
                response = self.session.get(url, timeout=CONFIG['request_timeout'])
                api_duration = time.time() - start_time
                self.api_tracker.record_call(f'pumpfun_v{i+1}', api_duration)
                self.stats['api_calls'] += 1
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Vérifier que les données sont valides
                    if not data or not isinstance(data, dict):
                        continue
                    
                    # Vérification flexible du mint
                    mint = data.get('mint') or data.get('address') or data.get('tokenAddress')
                    if not mint:
                        # Parfois les données sont dans un format différent
                        if 'id' in data:
                            mint = data.get('id')
                        elif 'contract' in data:
                            mint = data.get('contract')
                    
                    # Si mint correspond ou si on a des données valides sans mint
                    if (mint and mint.lower() == token_address.lower()) or (not mint and (data.get('symbol') or data.get('creator'))):
                        
                        # Parser les données Pump.fun
                        token_data = TokenData(
                            address=token_address,
                            symbol=data.get('symbol'),
                            name=data.get('name'),
                            decimals=data.get('decimals', 6),
                            price_usd=float(data.get('usd_market_cap', 0)) / float(data.get('total_supply', 1)) if data.get('total_supply') else 0.0,
                            timestamp_token_created=int(data['created_timestamp'] / 1000) if data.get('created_timestamp') and data['created_timestamp'] > 1e12 else int(data.get('created_timestamp', 0)),
                            creator_address=data.get('creator'), 
                            bonding_curve_progress=float(data.get('bonding_curve_progress', 0)), 
                            holder_count=int(data.get('holder_count', 0) or data.get('holders', 0)),  
                            market_cap=float(data.get('usd_market_cap', 0)),
                            volume_24h=float(data.get('volume_24h', 0)),
                            logo_uri=data.get('image_uri'),
                            is_verified=data.get('complete', False),
                            metadata_source="pumpfun"
                        )
                        
                        # Calculer le prix si pas directement disponible
                        if token_data.price_usd == 0.0 and data.get('virtual_sol_reserves') and data.get('virtual_token_reserves'):
                            sol_reserves = float(data.get('virtual_sol_reserves', 0))
                            token_reserves = float(data.get('virtual_token_reserves', 1))
                            if token_reserves > 0:
                                price_sol = sol_reserves / token_reserves
                                token_data.price_usd = price_sol * 150  # Approximation SOL/USD
                        
                        # Timestamp de création
                        if 'created_timestamp' in data:
                            token_data.timestamp_token_created = int(data['created_timestamp'] / 1000) if data['created_timestamp'] > 1e12 else int(data['created_timestamp'])
                        
                        self.logger.info(f"✅ Found Pump.fun data for {token_address[:8]}... (MC: ${token_data.market_cap:,.0f}) via URL {i+1}")
                        return token_data
                    else:
                        self.logger.debug(f"Mint mismatch in URL {i+1}: {mint} != {token_address}")
                        
                elif response.status_code == 404:
                    self.logger.debug(f"404 from Pump.fun URL {i+1}")
                    continue
                elif response.status_code == 530:
                    self.logger.warning(f"530 Server error from Pump.fun URL {i+1}, trying next...")
                    continue
                elif response.status_code == 429:
                    self.logger.warning(f"Rate limited by Pump.fun, waiting...")
                    time.sleep(5)  # Attendre plus longtemps
                    continue
                else:
                    self.logger.debug(f"HTTP {response.status_code} from Pump.fun URL {i+1}")
                    continue
                    
            except Exception as e:
                self.logger.debug(f"Error with Pump.fun URL {i+1}: {e}")
                continue
        
        # Aucune URL n'a fonctionné
        self.logger.debug(f"Token not found on any Pump.fun URL: {token_address[:8]}...")
        return None

    def get_rugcheck_data(self, token_address: str) -> Optional[dict]:
        """Get comprehensive analysis from rugcheck.xyz"""
        try:
            url = f"https://api.rugcheck.xyz/v1/tokens/{token_address}/report"
            start_time = time.time()
            response = self.session.get(url, timeout=CONFIG['request_timeout'])
            api_duration = time.time() - start_time
            self.api_tracker.record_call('rugcheck', api_duration)
            self.stats['api_calls'] += 1
            
            if response.status_code == 200:
                data = response.json()
                self.logger.debug(f"✅ Got rugcheck data for {token_address[:8]}...")
                return data
            
            return None
        except Exception as e:
            self.logger.debug(f"Rugcheck error for {token_address[:8]}...: {e}")
            return None

    def extract_rugcheck_data(self, rugcheck_response: dict) -> dict:
        """Extract useful data from rugcheck response"""
        try:
            # Add proper None check and type validation
            if not rugcheck_response or not isinstance(rugcheck_response, dict):
                self.logger.debug("Invalid or empty rugcheck response")
                return {}
            
            # Additional check for empty dict or missing critical data
            if not rugcheck_response:
                self.logger.debug("Empty rugcheck response dict")
                return {}
                
            security_data = {}
            
            # Scores de sécurité (with safe defaults)
            security_data['rug_risk_score'] = rugcheck_response.get('score_normalised', 50)
            security_data['rug_raw_score'] = rugcheck_response.get('score', 0)
            security_data['is_rugged'] = rugcheck_response.get('rugged', False)
            
            # Autorités (safe access with defaults)
            token_info = rugcheck_response.get('token', {})
            if isinstance(token_info, dict):
                security_data['mint_authority_revoked'] = token_info.get('mintAuthority') is None
                security_data['freeze_authority_revoked'] = token_info.get('freezeAuthority') is None
            else:
                security_data['mint_authority_revoked'] = False
                security_data['freeze_authority_revoked'] = False
            
            # Holders analysis (safe access)
            top_holders = rugcheck_response.get('topHolders', [])
            if isinstance(top_holders, list) and top_holders:
                try:
                    # Get top holder percentage safely
                    first_holder = top_holders[0] if len(top_holders) > 0 else {}
                    security_data['top_holder_percentage'] = float(first_holder.get('pct', 0))
                    
                    # Calculate top 10 holders percentage safely
                    top_10_pct = 0.0
                    for i, holder in enumerate(top_holders[:10]):
                        if isinstance(holder, dict) and 'pct' in holder:
                            try:
                                top_10_pct += float(holder.get('pct', 0))
                            except (ValueError, TypeError):
                                continue
                    security_data['top_10_holders_percentage'] = top_10_pct
                    
                    # Count insider holders safely
                    insider_count = 0
                    for holder in top_holders:
                        if isinstance(holder, dict) and holder.get('insider', False):
                            insider_count += 1
                    security_data['insider_holders_count'] = insider_count
                    
                except Exception as e:
                    self.logger.debug(f"Error processing top holders data: {e}")
                    security_data['top_holder_percentage'] = 0.0
                    security_data['top_10_holders_percentage'] = 0.0
                    security_data['insider_holders_count'] = 0
            else:
                security_data['top_holder_percentage'] = 0.0
                security_data['top_10_holders_percentage'] = 0.0
                security_data['insider_holders_count'] = 0
            
            # Autres données (safe access with type checking)
            security_data['holder_count'] = rugcheck_response.get('totalHolders', 0)
            if not isinstance(security_data['holder_count'], (int, float)):
                security_data['holder_count'] = 0
            else:
                security_data['holder_count'] = int(security_data['holder_count'])
                
            security_data['insider_networks_detected'] = rugcheck_response.get('graphInsidersDetected', 0)
            if not isinstance(security_data['insider_networks_detected'], (int, float)):
                security_data['insider_networks_detected'] = 0
            else:
                security_data['insider_networks_detected'] = int(security_data['insider_networks_detected'])
                
            security_data['lp_providers_count'] = rugcheck_response.get('totalLPProviders', 0)
            if not isinstance(security_data['lp_providers_count'], (int, float)):
                security_data['lp_providers_count'] = 0
            else:
                security_data['lp_providers_count'] = int(security_data['lp_providers_count'])
                
            # Liquidity with safe conversion
            liquidity_raw = rugcheck_response.get('totalMarketLiquidity', 0.0)
            try:
                security_data['liquidity_usd'] = float(liquidity_raw) if liquidity_raw is not None else 0.0
            except (ValueError, TypeError):
                security_data['liquidity_usd'] = 0.0
            
            # Launchpad info (safe access)
            launchpad = rugcheck_response.get('launchpad', {})
            if isinstance(launchpad, dict):
                security_data['launchpad_name'] = launchpad.get('name')
                security_data['is_pump_fun'] = launchpad.get('platform') == 'pump_fun'
            else:
                security_data['launchpad_name'] = None
                security_data['is_pump_fun'] = False
            
            # Risques (safe access)
            risks = rugcheck_response.get('risks', [])
            if isinstance(risks, list):
                security_data['risk_count'] = len(risks)
                security_data['has_low_liquidity'] = any(
                    isinstance(risk, dict) and risk.get('name') == 'Low Liquidity' 
                    for risk in risks
                )
            else:
                security_data['risk_count'] = 0
                security_data['has_low_liquidity'] = False
            
            self.logger.debug(f"Successfully extracted rugcheck data: score={security_data.get('rug_risk_score')}, holders={security_data.get('holder_count')}")
            return security_data
            
        except Exception as e:
            self.logger.error(f"Error extracting rugcheck data: {e}")
            return {
                'rug_risk_score': 50,
                'rug_raw_score': 0,
                'is_rugged': False,
                'mint_authority_revoked': False,
                'freeze_authority_revoked': False,
                'top_holder_percentage': 0.0,
                'top_10_holders_percentage': 0.0,
                'insider_holders_count': 0,
                'holder_count': 0,
                'insider_networks_detected': 0,
                'lp_providers_count': 0,
                'liquidity_usd': 0.0,
                'launchpad_name': None,
                'is_pump_fun': False,
                'risk_count': 0,
                'has_low_liquidity': False
            }

    def clean_token_data(self, token_data: TokenData) -> TokenData:
        """Clean token data to avoid SQL injection and special characters"""
        # Nettoyer le symbole
        if token_data.symbol:
            token_data.symbol = token_data.symbol.replace('#', '').replace("'", "").replace('"', '').strip()
            if not token_data.symbol:
                token_data.symbol = f"UNK_{token_data.address[:6]}"
        
        # Nettoyer le nom
        if token_data.name:
            token_data.name = token_data.name.replace('#', '').replace("'", "").replace('"', '').strip()
            if not token_data.name:
                token_data.name = f"Unknown Token {token_data.address[:8]}"
        
        # Limiter la longueur des chaînes
        if token_data.symbol and len(token_data.symbol) > 20:
            token_data.symbol = token_data.symbol[:20]
        
        if token_data.name and len(token_data.name) > 100:
            token_data.name = token_data.name[:100]
        
        return token_data

    def identify_address_type(self, address: str) -> str:
        """Identify if address is a token or pair"""
        try:
            # Test pairs endpoint first
            url_pair = f"https://api.dexscreener.com/latest/dex/pairs/solana/{address}"
            response = self.session.get(url_pair, timeout=CONFIG['request_timeout'])
            self.stats['api_calls'] += 1
            
            if response.status_code == 200:
                data = response.json()
                if 'pair' in data and data['pair']:
                    return 'pair'
            
            # Test tokens endpoint
            url_token = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
            response = self.session.get(url_token, timeout=CONFIG['request_timeout'])
            self.stats['api_calls'] += 1
            
            if response.status_code == 200:
                data = response.json()
                if 'pairs' in data and data['pairs']:
                    return 'token'
            
            return 'unknown'
            
        except Exception as e:
            self.logger.warning(f"Error identifying address type for {address}: {e}")
            return 'unknown'
    
    def extract_token_from_pair(self, pair_address: str) -> Optional[str]:
        """Extract token address from pair address"""
        try:
            url = f"https://api.dexscreener.com/latest/dex/pairs/solana/{pair_address}"
            response = self.session.get(url, timeout=CONFIG['request_timeout'])
            self.stats['api_calls'] += 1
            
            if response.status_code == 200:
                data = response.json()
                
                if 'pair' in data and data['pair']:
                    pair = data['pair']
                    base_token = pair.get('baseToken', {}).get('address')
                    quote_token = pair.get('quoteToken', {}).get('address')
                    
                    # Prefer base token if quote is known stable/SOL
                    if quote_token in CONFIG['known_quote_tokens']:
                        return base_token
                    else:
                        return base_token
                        
        except Exception as e:
            self.logger.warning(f"Error extracting token from pair {pair_address}: {e}")
            
        return None
        
    def get_token_creation_from_dexscreener(self, token_address: str) -> Optional[int]:
        """
        Get token creation timestamp from DexScreener
        
        Args:
            token_address: Token address
            
        Returns:
            Unix timestamp of creation or None if not found
        """
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            response = self.session.get(url, timeout=CONFIG['request_timeout'])
            self.stats['api_calls'] += 1
            
            if response.status_code == 200:
                data = response.json()
                
                if 'pairs' in data and data['pairs']:
                    # Take the oldest pair (first creation)
                    oldest_pair = min(data['pairs'], key=lambda p: p.get('pairCreatedAt', float('inf')))
                    
                    if 'pairCreatedAt' in oldest_pair:
                        # pairCreatedAt is usually in milliseconds
                        creation_time = oldest_pair['pairCreatedAt']
                        if creation_time > 1e12:  # If in milliseconds
                            creation_time = creation_time // 1000
                        return int(creation_time)
                
                self.logger.debug(f"No creation data found for {token_address[:8]}...")
                return None
                
        except Exception as e:
            self.logger.warning(f"Error getting creation timestamp from DexScreener for {token_address[:8]}...: {e}")
            return None
    
    def get_token_creation_from_solanatracker(self, token_address: str) -> Optional[int]:
        """
        Get token creation timestamp from Solana Tracker
        
        Args:
            token_address: Token address
            
        Returns:
            Unix timestamp of creation or None if not found
        """
        try:
            url = f"https://api.solanatracker.io/tokens/{token_address}"
            response = self.session.get(url, timeout=CONFIG['request_timeout'])
            self.stats['api_calls'] += 1
            
            if response.status_code == 200:
                data = response.json()
                
                if 'token' in data and 'creation' in data['token']:
                    creation_info = data['token']['creation']
                    if 'created_time' in creation_info:
                        return int(creation_info['created_time'])
                
                self.logger.debug(f"No creation data found on SolanaTracker for {token_address[:8]}...")
                return None
                
        except Exception as e:
            self.logger.warning(f"Error getting creation timestamp from SolanaTracker for {token_address[:8]}...: {e}")
            return None
    
    def get_token_creation_timestamp(self, token_address: str) -> Optional[int]:
        """
        Get token creation timestamp trying multiple sources
        
        Args:
            token_address: Token address
            
        Returns:
            Unix timestamp of creation or None if not found
        """
        self.logger.debug(f"🔍 Searching creation timestamp for {token_address[:8]}...")
        
        # Try DexScreener first (more reliable)
        timestamp = self.get_token_creation_from_dexscreener(token_address)
        if timestamp:
            self.logger.info(f"✅ Found creation timestamp on DexScreener: {datetime.fromtimestamp(timestamp)}")
            return timestamp
        
        # Pause to avoid rate limiting
        time.sleep(0.5)
        
        # Try Solana Tracker
        timestamp = self.get_token_creation_from_solanatracker(token_address)
        if timestamp:
            self.logger.info(f"✅ Found creation timestamp on SolanaTracker: {datetime.fromtimestamp(timestamp)}")
            return timestamp
        
        self.logger.debug(f"❌ Creation timestamp not found for {token_address[:8]}...")
        return None
    
    
    
    def print_api_database_stats(self):
        """Print API statistics from database"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Stats du cycle actuel
                if self.current_sync_cycle_id:
                    cursor.execute("""
                        SELECT api_name, COUNT(*) as calls, 
                            AVG(duration_ms) as avg_duration,
                            SUM(CASE WHEN success THEN 1 ELSE 0 END) as success_count,
                            SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as error_count
                        FROM api_metrics 
                        WHERE sync_cycle_id = ?
                        GROUP BY api_name
                        ORDER BY calls DESC
                    """, (self.current_sync_cycle_id,))
                    
                    current_cycle_stats = cursor.fetchall()
                    
                    if current_cycle_stats:
                        self.logger.info("=== 📊 API DATABASE STATS (Current Cycle) ===")
                        for row in current_cycle_stats:
                            self.logger.info(f"🔗 {row['api_name'].upper()}: {row['calls']} calls, "
                                        f"avg {row['avg_duration']:.0f}ms, "
                                        f"✅{row['success_count']} ❌{row['error_count']}")
                
                # Stats des dernières 24h
                yesterday = int(time.time()) - 86400
                cursor.execute("""
                    SELECT api_name, COUNT(*) as total_calls,
                        AVG(duration_ms) as avg_duration,
                        MIN(duration_ms) as min_duration,
                        MAX(duration_ms) as max_duration,
                        SUM(CASE WHEN success THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as success_rate
                    FROM api_metrics 
                    WHERE call_timestamp > ?
                    GROUP BY api_name
                    HAVING total_calls > 10
                    ORDER BY total_calls DESC
                """, (yesterday,))
                
                stats_24h = cursor.fetchall()
                
                if stats_24h:
                    self.logger.info("=== 📈 API PERFORMANCE (Last 24h) ===")
                    for row in stats_24h:
                        self.logger.info(f"📊 {row['api_name']}: {row['total_calls']} calls, "
                                    f"avg {row['avg_duration']:.0f}ms "
                                    f"({row['min_duration']}-{row['max_duration']}ms), "
                                    f"success {row['success_rate']:.1f}%")
        
        except Exception as e:
            self.logger.debug(f"Error getting API database stats: {e}")

    def get_api_performance_report(self, days: int = 7) -> Dict:
        """Get detailed API performance report from database"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                since_timestamp = int(time.time()) - (days * 86400)
                
                cursor.execute("""
                    SELECT 
                        api_name,
                        COUNT(*) as total_calls,
                        AVG(duration_ms) as avg_duration_ms,
                        MIN(duration_ms) as min_duration_ms,
                        MAX(duration_ms) as max_duration_ms,
                        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_ms) as median_duration_ms,
                        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) as p95_duration_ms,
                        SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful_calls,
                        SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as failed_calls,
                        COUNT(DISTINCT DATE(call_timestamp, 'unixepoch')) as days_active
                    FROM api_metrics 
                    WHERE call_timestamp > ?
                    GROUP BY api_name
                    ORDER BY total_calls DESC
                """, (since_timestamp,))
                
                return {
                    'period_days': days,
                    'apis': [dict(row) for row in cursor.fetchall()]
                }
                
        except Exception as e:
            self.logger.error(f"Error generating API performance report: {e}")
            return {}

    def start_sync_cycle(self) -> int:
        """Start a new sync cycle and return cycle ID - DEBUG FIXED VERSION"""
        cycle_id = int(time.time() * 1000)  # Timestamp en millisecondes comme ID
        
        # DEBUG: Log the exact values
        print(f"🔍 DEBUG CYCLE: Generated cycle_id = {cycle_id} (type: {type(cycle_id)})")
        
        self.current_sync_cycle_id = cycle_id
        self.api_tracker.set_current_cycle(cycle_id)
        
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # DEBUG: Log the exact query and parameters
                start_time = int(time.time())
                print(f"🔍 DEBUG CYCLE: Inserting with sync_cycle_id={cycle_id}, cycle_start_time={start_time}")
                
                cursor.execute("""
                    INSERT INTO api_cycle_stats (sync_cycle_id, cycle_start_time)
                    VALUES (?, ?)
                """, (cycle_id, start_time))
                
                # DEBUG: Verify the insertion immediately
                cursor.execute("SELECT last_insert_rowid()")
                row_id = cursor.fetchone()[0]
                print(f"🔍 DEBUG CYCLE: Inserted row ID: {row_id}")
                
                # DEBUG: Verify what was actually inserted
                cursor.execute("SELECT sync_cycle_id, cycle_start_time FROM api_cycle_stats WHERE id = ?", (row_id,))
                inserted_record = cursor.fetchone()
                print(f"🔍 DEBUG CYCLE: Inserted record: sync_cycle_id={inserted_record[0]}, cycle_start_time={inserted_record[1]}")
                
                conn.commit()
                
                self.logger.info(f"🚀 Started sync cycle {cycle_id}")
                
                # Vérifier que l'insertion a fonctionné avec le bon ID
                cursor.execute("SELECT sync_cycle_id FROM api_cycle_stats WHERE sync_cycle_id = ?", (cycle_id,))
                verification = cursor.fetchone()
                if verification:
                    self.logger.debug(f"✅ Cycle {cycle_id} successfully created in database")
                    print(f"🔍 DEBUG CYCLE: Verification successful - found cycle {verification[0]}")
                else:
                    self.logger.error(f"❌ Failed to create cycle {cycle_id} in database")
                    print(f"🔍 DEBUG CYCLE: Verification FAILED - cycle {cycle_id} not found")
                    
                    # DEBUG: Show what's actually in the table
                    cursor.execute("SELECT id, sync_cycle_id, cycle_start_time FROM api_cycle_stats ORDER BY id DESC LIMIT 3")
                    recent_cycles = cursor.fetchall()
                    print(f"🔍 DEBUG CYCLE: Recent cycles in DB: {[dict(zip(['id', 'sync_cycle_id', 'cycle_start_time'], row)) for row in recent_cycles]}")
                    
        except Exception as e:
            self.logger.error(f"❌ Failed to record cycle start: {e}")
            print(f"🔍 DEBUG CYCLE: Exception during insertion: {e}")
            import traceback
            print(f"🔍 DEBUG CYCLE: Full traceback: {traceback.format_exc()}")
        
        return cycle_id

    def end_sync_cycle(self, tokens_processed: int):
        """End current sync cycle and update stats - DEBUG FIXED VERSION"""
        if not self.current_sync_cycle_id:
            self.logger.warning("No current sync cycle ID to end")
            return
        
        self.logger.info(f"🔍 DEBUG: Starting end_sync_cycle for cycle {self.current_sync_cycle_id}")
        self.logger.info(f"🔍 DEBUG: Tokens processed parameter: {tokens_processed}")
        
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 1. Vérifier d'abord l'état actuel de la table api_cycle_stats
                cursor.execute("""
                    SELECT id, sync_cycle_id, cycle_start_time 
                    FROM api_cycle_stats 
                    ORDER BY id DESC LIMIT 3
                """)
                recent_cycles = cursor.fetchall()
                self.logger.info(f"🔍 DEBUG: Recent cycles: {[dict(zip(['id', 'sync_cycle_id', 'cycle_start_time'], row)) for row in recent_cycles]}")
                
                # 2. Chercher notre cycle - d'abord par sync_cycle_id exact
                cursor.execute("""
                    SELECT id, sync_cycle_id FROM api_cycle_stats WHERE sync_cycle_id = ?
                """, (self.current_sync_cycle_id,))
                exact_match = cursor.fetchone()
                
                if exact_match:
                    self.logger.info(f"🔍 DEBUG: Found exact match for cycle {self.current_sync_cycle_id}: id={exact_match[0]}")
                    target_cycle_db_id = exact_match[0]
                    update_condition = "id = ?"
                    update_param = target_cycle_db_id
                else:
                    # 3. Si pas de match exact, chercher le plus récent avec sync_cycle_id NULL
                    self.logger.warning(f"🔍 DEBUG: No exact match found for cycle {self.current_sync_cycle_id}")
                    cursor.execute("""
                        SELECT id, sync_cycle_id, cycle_start_time 
                        FROM api_cycle_stats 
                        WHERE sync_cycle_id IS NULL OR sync_cycle_id = ''
                        ORDER BY id DESC LIMIT 1
                    """)
                    null_cycle = cursor.fetchone()
                    
                    if null_cycle:
                        self.logger.info(f"🔍 DEBUG: Found NULL cycle to update: id={null_cycle[0]}, start_time={null_cycle[2]}")
                        target_cycle_db_id = null_cycle[0]
                        update_condition = "id = ?"
                        update_param = target_cycle_db_id
                        
                        # Mettre à jour le sync_cycle_id d'abord
                        cursor.execute("""
                            UPDATE api_cycle_stats SET sync_cycle_id = ? WHERE id = ?
                        """, (self.current_sync_cycle_id, target_cycle_db_id))
                        self.logger.info(f"🔍 DEBUG: Updated sync_cycle_id for record {target_cycle_db_id}")
                    else:
                        self.logger.error(f"🔍 DEBUG: No suitable cycle record found to update!")
                        return
                
                # 4. Maintenant, obtenir les statistiques API
                cursor.execute("""
                    SELECT COUNT(*) as count FROM api_metrics WHERE sync_cycle_id = ?
                """, (self.current_sync_cycle_id,))
                count_result = cursor.fetchone()
                record_count = count_result['count'] if count_result else 0
                self.logger.info(f"🔍 DEBUG: Found {record_count} api_metrics records for cycle {self.current_sync_cycle_id}")
                
                if record_count == 0:
                    self.logger.warning(f"🔍 DEBUG: No API metrics found for cycle {self.current_sync_cycle_id}")
                    # Essayer avec une recherche temporelle approximative
                    cycle_timestamp = self.current_sync_cycle_id // 1000  # Convertir en secondes
                    cursor.execute("""
                        SELECT COUNT(*) FROM api_metrics 
                        WHERE call_timestamp BETWEEN ? AND ?
                    """, (cycle_timestamp - 300, cycle_timestamp + 3600))  # ±5min avant, +1h après
                    approx_count = cursor.fetchone()[0]
                    self.logger.info(f"🔍 DEBUG: Found {approx_count} API metrics in time range")
                
                # 5. Calculer les statistiques
                cursor.execute("""
                    SELECT 
                        COALESCE(COUNT(*), 0) as total_calls,
                        COALESCE(SUM(duration_ms), 0) as total_duration,
                        COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END), 0) as successful_calls,
                        COALESCE(SUM(CASE WHEN NOT success THEN 1 ELSE 0 END), 0) as failed_calls,
                        COALESCE(COUNT(DISTINCT api_name), 0) as unique_apis
                    FROM api_metrics 
                    WHERE sync_cycle_id = ?
                """, (self.current_sync_cycle_id,))
                
                stats = cursor.fetchone()
                self.logger.info(f"🔍 DEBUG: Calculated stats: {dict(stats) if stats else 'None'}")
                
                if stats:
                    total_calls = stats['total_calls'] or 0
                    total_duration = stats['total_duration'] or 0
                    successful_calls = stats['successful_calls'] or 0
                    failed_calls = stats['failed_calls'] or 0
                    unique_apis = stats['unique_apis'] or 0
                    
                    self.logger.info(f"🔍 DEBUG: Final values - calls:{total_calls}, duration:{total_duration}, success:{successful_calls}")
                    
                    # 6. Mettre à jour les statistiques du cycle
                    cursor.execute(f"""
                        UPDATE api_cycle_stats SET
                            cycle_end_time = ?,
                            total_api_calls = ?,
                            total_duration_ms = ?,
                            successful_calls = ?,
                            failed_calls = ?,
                            unique_apis_used = ?,
                            tokens_processed = ?
                        WHERE {update_condition}
                    """, (
                        int(time.time()),
                        total_calls,
                        total_duration,
                        successful_calls,
                        failed_calls,
                        unique_apis,
                        tokens_processed,
                        update_param
                    ))
                    
                    update_count = cursor.rowcount
                    self.logger.info(f"🔍 DEBUG: UPDATE affected {update_count} rows")
                    
                    conn.commit()
                    
                    # 7. Vérifier le résultat
                    cursor.execute("""
                        SELECT * FROM api_cycle_stats WHERE id = ?
                    """, (target_cycle_db_id,))
                    final_record = cursor.fetchone()
                    self.logger.info(f"🔍 DEBUG: Final record: {dict(final_record) if final_record else 'NOT FOUND'}")
                    
                    if update_count > 0:
                        self.logger.info(f"✅ Successfully updated cycle stats for {self.current_sync_cycle_id}")
                    else:
                        self.logger.error(f"❌ Failed to update cycle stats")
                else:
                    self.logger.warning(f"⚠️ No stats calculated")
                    
        except Exception as e:
            self.logger.error(f"❌ Failed to end cycle stats: {e}")
            import traceback
            self.logger.error(f"❌ Full traceback: {traceback.format_exc()}")
        
        # Reset current cycle
        self.current_sync_cycle_id = None

    @db_retry(max_retries=3, delay=0.3)
    def get_new_tokens_from_transactions(self) -> Set[str]:
        """Get new token addresses from transactions table (excluding flagged tokens)"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Get all token_mint addresses from transactions that aren't in tokens table
                # AND exclude tokens that are flagged as no_data unless retry period has passed
                query = """
                SELECT DISTINCT t.token_mint
                FROM transactions t
                LEFT JOIN tokens tk ON t.token_mint = tk.address
                WHERE t.token_mint IS NOT NULL 
                AND t.token_mint != ''
                AND tk.address IS NULL
                AND t.token_mint NOT IN (
                    SELECT address FROM tokens 
                    WHERE no_data_available = 1 
                    AND (no_data_last_check > datetime('now', '-' || ? || ' days') OR failed_attempts >= ?)
                )
                ORDER BY t.created_at DESC
                """
                
                cursor.execute(query, (CONFIG['retry_failed_after_days'], CONFIG['max_failed_attempts']))
                results = cursor.fetchall()
                
                token_addresses = {row[0] for row in results}
                self.logger.info(f"Found {len(token_addresses)} new tokens to process (excluding flagged tokens)")
                
                return token_addresses
                
        except Exception as e:
            self.logger.error(f"Error getting new tokens: {e}")
            return set()
    
    @db_retry(max_retries=3, delay=0.3)
    def get_tokens_needing_price_update(self) -> List[str]:
        """Get tokens that need price updates (excluding flagged tokens)"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Get tokens that haven't been updated recently and aren't flagged
                cutoff_time = int(time.time()) - CONFIG['price_update_interval']
                self.logger.debug(f"DEBUG: Using cutoff time {datetime.fromtimestamp(cutoff_time)} for general price updates.")

                query = """
                SELECT address 
                FROM tokens 
                WHERE (last_price_update < ? OR last_price_update IS NULL)
                AND (no_data_available = 0 OR no_data_available IS NULL)
                AND (failed_attempts < ? OR failed_attempts IS NULL)
                AND is_dead = 0
                ORDER BY last_price_update ASC NULLS FIRST
                LIMIT ?
                """
                
                cursor.execute(query, (cutoff_time, CONFIG['max_failed_attempts'], CONFIG['batch_size']))
                results = cursor.fetchall()
                
                self.logger.info(f"Found {len(results)} general tokens needing price updates.")
                return [row[0] for row in results]
                
        except Exception as e:
            self.logger.error(f"Error getting tokens for price update: {e}")
            return []
    
    def get_tokens_needing_historization(self) -> List[str]:
        """Get tokens that need historization"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                cutoff_time = int(time.time()) - CONFIG['historization_interval']
                
                query = """
                SELECT address 
                FROM tokens 
                WHERE is_dead = 0
                AND (last_historized_at < ? OR last_historized_at IS NULL)
                AND (price_usd > 0 OR market_cap > 0)
                ORDER BY last_historized_at ASC NULLS FIRST
                LIMIT ?
                """
                
                cursor.execute(query, (cutoff_time, CONFIG['batch_size']))
                results = cursor.fetchall()
                
                return [row[0] for row in results]
                
        except Exception as e:
            self.logger.error(f"Error getting tokens for historization: {e}")
            return []
    
    @db_retry(max_retries=3, delay=0.3)
    def mark_token_no_data(self, token_address: str, increment_attempts: bool = True) -> bool:
        """Mark a token as having no data available"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                if increment_attempts:
                    # Incrémenter le compteur de tentatives échouées
                    cursor.execute("""
                        UPDATE tokens 
                        SET failed_attempts = COALESCE(failed_attempts, 0) + 1,
                            no_data_last_check = CURRENT_TIMESTAMP,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE address = ?
                    """, (token_address,))
                    
                    # Vérifier si on doit marquer comme no_data_available
                    cursor.execute("SELECT failed_attempts FROM tokens WHERE address = ?", (token_address,))
                    result = cursor.fetchone()
                    
                    if result and result[0] >= CONFIG['max_failed_attempts']:
                        cursor.execute("""
                            UPDATE tokens 
                            SET no_data_available = 1
                            WHERE address = ?
                        """, (token_address,))
                        self.logger.warning(f"🚫 Token {token_address[:8]}... marked as no_data_available after {result[0]} failed attempts")
                else:
                    # Marquer directement comme no_data
                    cursor.execute("""
                        UPDATE tokens 
                        SET no_data_available = 1,
                            no_data_last_check = CURRENT_TIMESTAMP,
                            failed_attempts = COALESCE(failed_attempts, 0) + 1,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE address = ?
                    """, (token_address,))
                    self.logger.warning(f"🚫 Token {token_address[:8]}... marked as no_data_available")
                
                conn.commit()
                return cursor.rowcount > 0
                
        except Exception as e:
            self.logger.error(f"Error marking token as no data {token_address}: {e}")
            return False

    def create_token_stub(self, token_address: str) -> bool:
        """Create a minimal token entry when no data is found"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Vérifier si le token existe déjà
                cursor.execute("SELECT address FROM tokens WHERE address = ?", (token_address,))
                if cursor.fetchone():
                    # Token existe déjà, juste marquer comme no_data
                    return self.mark_token_no_data(token_address)
                
                # Créer un stub avec données minimales
                current_timestamp = int(time.time())
                
                query = """
                INSERT INTO tokens (
                    address, symbol, name, decimals, price_usd, 
                    no_data_last_check, failed_attempts, no_data_available,
                    last_price_update, metadata_source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """
                
                cursor.execute(query, (
                    token_address,
                    f"UNK_{token_address[:6]}",  # Symbol générique
                    f"Unknown Token {token_address[:8]}",  # Nom générique
                    9,  # Decimals par défaut
                    0.0,  # Prix inconnu
                    None,  # no_data_last_check (pas encore de check)
                    1,  # failed_attempts (première tentative échouée)
                    0,  # no_data_available (pas encore marqué comme no_data)
                    current_timestamp,
                    "stub",  # Source
                ))
                
                conn.commit()
                self.logger.info(f"📝 Created stub entry for {token_address[:8]}...")
                return True
                
        except Exception as e:
            self.logger.error(f"Error creating token stub {token_address}: {e}")
            return False

    def upsert_token(self, token_data: TokenData) -> bool:
        """Insert or update token in database with historization - enhanced version with retry logic"""
        max_retries = 3
        base_delay = 0.2
        
        for attempt in range(max_retries):
            try:
                # Clean data before insertion
                original_symbol = token_data.symbol
                original_name = token_data.name
                token_data = self.clean_token_data(token_data)
                rugcheck_data = {}
                current_timestamp = int(time.time())

                if original_symbol != token_data.symbol:
                    self.logger.info(f"Symbol cleaned for {token_data.address[:8]}... - '{original_symbol}' -> '{token_data.symbol}'")
                if original_name != token_data.name:
                    self.logger.info(f"Name cleaned for {token_data.address[:8]}... - '{original_name}' -> '{token_data.name}'")
                
                # 1. Check if token exists avec retry
                token_exists = False
                conn = self.get_db_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT address FROM tokens WHERE address = ?", (token_data.address,))
                    token_exists = cursor.fetchone() is not None
                finally:
                    conn.close()
                
                # 2. Si token existe, historiser AVANT la mise à jour
                if token_exists:
                    conn = self.get_db_connection()
                    try:
                        cursor = conn.cursor()
                        cursor.execute("SELECT price_usd, market_cap FROM tokens WHERE address = ?", (token_data.address,))
                        existing_row = cursor.fetchone()
                        
                        # Historiser seulement si le token a déjà des données réelles
                        if existing_row and (existing_row['price_usd'] > 0 or existing_row['market_cap'] > 0):
                            # Appeler historize_token_data qui a maintenant sa propre logique de retry
                            self.historize_token_data(token_data.address, token_data)
                        else:
                            self.logger.debug(f"Skipping historization for {token_data.address[:8]}... - no significant data yet")
                    finally:
                        conn.close()
                
                # 3. Faire l'update/insert avec nouvelle connexion
                conn = self.get_db_connection()
                try:
                    cursor = conn.cursor()
                    
                    # Vérifier les données rugcheck récentes
                    if token_exists:
                        cursor.execute("""
                            SELECT last_rugcheck_update, rug_risk_score 
                            FROM tokens 
                            WHERE address = ? AND last_rugcheck_update > ?
                        """, (token_data.address, current_timestamp - 86400))
                        recent_rugcheck = cursor.fetchone()
                    else:
                        recent_rugcheck = None

                    if not recent_rugcheck:
                        # Récupérer nouvelles données rugcheck (sans connexion DB)
                        rugcheck_response = self.get_rugcheck_data(token_data.address)
                        if rugcheck_response:
                            rugcheck_data = self.extract_rugcheck_data(rugcheck_response)
                            # Enrichir token_data avec holder_count de rugcheck si meilleur
                            if rugcheck_data.get('holder_count', 0) > token_data.holder_count:
                                old_count = token_data.holder_count
                                token_data.holder_count = rugcheck_data['holder_count']
                                self.logger.info(f"📊 Updated holder_count for {token_data.address[:8]}... from {old_count} to {token_data.holder_count}")

                                # Ajouter les attributs manquants à token_data pour l'historisation
                                token_data.top_holder_percentage = rugcheck_data.get('top_holder_percentage', 0.0)
                                token_data.top_10_holders_percentage = rugcheck_data.get('top_10_holders_percentage', 0.0)
                                token_data.insider_holders_count = rugcheck_data.get('insider_holders_count', 0)
                                token_data.insider_networks_detected = rugcheck_data.get('insider_networks_detected', 0)
                                token_data.lp_providers_count = rugcheck_data.get('lp_providers_count', 0)
                                token_data.has_low_liquidity = rugcheck_data.get('has_low_liquidity', False)
                                token_data.rug_risk_score = rugcheck_data.get('rug_risk_score', 50)
                                token_data.rug_raw_score = rugcheck_data.get('rug_raw_score', 0)
                                token_data.is_rugged = rugcheck_data.get('is_rugged', False)
                                token_data.risk_count = rugcheck_data.get('risk_count', 0)
                                token_data.mint_authority_revoked = rugcheck_data.get('mint_authority_revoked', False)
                                token_data.freeze_authority_revoked = rugcheck_data.get('freeze_authority_revoked', False)
                                token_data.launchpad_name = rugcheck_data.get('launchpad_name')
                                token_data.is_pump_fun = rugcheck_data.get('is_pump_fun', False)
                                
                                self.logger.debug(f"🔒 Enriched token_data with rugcheck: TH={token_data.top_holder_percentage:.2f}%, T10H={token_data.top_10_holders_percentage:.2f}%")
                                
                                self.logger.info(f"🔒 Got rugcheck data for {token_data.address[:8]}... (score: {rugcheck_data.get('rug_risk_score', 50)})")

                    # Calculate advanced metrics
                    liquidity_mc_ratio = 0.0
                    volume_mc_ratio = 0.0
                    if token_data.market_cap > 0:
                        liquidity_mc_ratio = token_data.liquidity_usd / token_data.market_cap
                        volume_mc_ratio = token_data.volume_24h / token_data.market_cap
                    
                    # Calculate scores
                    viability_score = self.analyzer.calculate_viability_score(token_data, [])
                    risk_score = self.analyzer.calculate_risk_score(token_data, [])
                    momentum_score = self.analyzer.calculate_momentum_score(token_data, [])
                    
                    # Utiliser une transaction pour l'upsert
                    with conn:  # Context manager pour auto-commit/rollback
                        if token_exists:
                            # Update existing token
                            query = """
                            UPDATE tokens SET
                                symbol = COALESCE(?, symbol),
                                name = COALESCE(?, name),
                                decimals = COALESCE(?, decimals),
                                price_usd = ?,
                                logo_uri = COALESCE(?, logo_uri),
                                coingecko_id = COALESCE(?, coingecko_id),
                                is_verified = COALESCE(?, is_verified),
                                timestamp_token_created = CASE 
                                    WHEN ? > 0 AND (timestamp_token_created IS NULL OR timestamp_token_created = 0) 
                                    THEN ? 
                                    ELSE timestamp_token_created 
                                END,
                                creator_address = COALESCE(?, creator_address),
                                bonding_curve_progress = MAX(COALESCE(bonding_curve_progress, 0), COALESCE(?, 0)),
                                holder_count = MAX(COALESCE(holder_count, 0), COALESCE(?, 0)),
                                market_cap = ?,
                                fdv = ?,
                                liquidity_usd = ?,
                                liquidity_sol = ?,
                                liquidity_mc_ratio = ?,
                                volume_mc_ratio = ?,
                                volume_5m = ?,
                                volume_1h = ?,
                                volume_6h = ?,
                                volume_24h = ?,
                                price_change_5m = ?,
                                price_change_1h = ?,
                                price_change_6h = ?,
                                price_change_24h = ?,
                                viability_score = ?,
                                risk_score = ?,
                                momentum_score = ?,
                                rug_risk_score = COALESCE(?, rug_risk_score),
                                rug_raw_score = COALESCE(?, rug_raw_score),
                                is_rugged = COALESCE(?, is_rugged),
                                mint_authority_revoked = COALESCE(?, mint_authority_revoked),
                                freeze_authority_revoked = COALESCE(?, freeze_authority_revoked),
                                top_holder_percentage = COALESCE(?, top_holder_percentage),
                                top_10_holders_percentage = COALESCE(?, top_10_holders_percentage),
                                insider_holders_count = COALESCE(?, insider_holders_count),
                                insider_networks_detected = COALESCE(?, insider_networks_detected),
                                launchpad_name = COALESCE(?, launchpad_name),
                                is_pump_fun = COALESCE(?, is_pump_fun),
                                lp_providers_count = COALESCE(?, lp_providers_count),
                                has_low_liquidity = COALESCE(?, has_low_liquidity),
                                risk_count = COALESCE(?, risk_count),
                                last_rugcheck_update = CASE WHEN ? IS NOT NULL THEN ? ELSE last_rugcheck_update END,
                                last_price_update = ?,
                                metadata_source = COALESCE(?, metadata_source),
                                updated_at = CURRENT_TIMESTAMP,
                                failed_attempts = 0,
                                no_data_available = 0
                            WHERE address = ?
                            """
                            
                            cursor.execute(query, (
                                token_data.symbol,
                                token_data.name,
                                token_data.decimals,
                                token_data.price_usd,
                                token_data.logo_uri,
                                token_data.coingecko_id,
                                token_data.is_verified,
                                token_data.timestamp_token_created,
                                token_data.timestamp_token_created,
                                token_data.creator_address,  
                                token_data.bonding_curve_progress,  
                                token_data.holder_count,  
                                token_data.market_cap,
                                token_data.fdv,
                                token_data.liquidity_usd,
                                token_data.liquidity_sol,
                                liquidity_mc_ratio,
                                volume_mc_ratio,
                                token_data.volume_5m,
                                token_data.volume_1h,
                                token_data.volume_6h,
                                token_data.volume_24h,
                                token_data.price_change_5m,
                                token_data.price_change_1h,
                                token_data.price_change_6h,
                                token_data.price_change_24h,
                                viability_score,
                                risk_score,
                                momentum_score,
                                rugcheck_data.get('rug_risk_score'),
                                rugcheck_data.get('rug_raw_score'),
                                rugcheck_data.get('is_rugged'),
                                rugcheck_data.get('mint_authority_revoked'),
                                rugcheck_data.get('freeze_authority_revoked'),
                                rugcheck_data.get('top_holder_percentage'),
                                rugcheck_data.get('top_10_holders_percentage'),
                                rugcheck_data.get('insider_holders_count'),
                                rugcheck_data.get('insider_networks_detected'),
                                rugcheck_data.get('launchpad_name'),
                                rugcheck_data.get('is_pump_fun'),
                                rugcheck_data.get('lp_providers_count'),
                                rugcheck_data.get('has_low_liquidity'),
                                rugcheck_data.get('risk_count'),
                                current_timestamp if rugcheck_data else None,
                                current_timestamp if rugcheck_data else None,
                                current_timestamp,
                                token_data.metadata_source,
                                token_data.address
                            ))
                        else:
                            # Insert new token
                            query = """
                            INSERT INTO tokens (
                                address, symbol, name, decimals, price_usd, logo_uri,
                                coingecko_id, is_verified, timestamp_token_created, creator_address,
                                bonding_curve_progress, holder_count, market_cap, fdv,
                                liquidity_usd, liquidity_sol, liquidity_mc_ratio, volume_mc_ratio,
                                volume_5m, volume_1h, volume_6h, volume_24h, 
                                price_change_5m, price_change_1h, price_change_6h, price_change_24h,
                                viability_score, risk_score, momentum_score,
                                rug_risk_score, rug_raw_score, is_rugged,
                                mint_authority_revoked, freeze_authority_revoked,
                                top_holder_percentage, top_10_holders_percentage,
                                insider_holders_count, insider_networks_detected,
                                launchpad_name, is_pump_fun, lp_providers_count,
                                has_low_liquidity, risk_count, last_rugcheck_update,
                                last_price_update, metadata_source, last_historized_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """

                            cursor.execute(query, (
                                token_data.address,
                                token_data.symbol,
                                token_data.name,
                                token_data.decimals,
                                token_data.price_usd,
                                token_data.logo_uri,
                                token_data.coingecko_id,
                                token_data.is_verified,
                                token_data.timestamp_token_created,
                                token_data.creator_address, 
                                token_data.bonding_curve_progress,  
                                token_data.holder_count,  
                                token_data.market_cap,
                                token_data.fdv,
                                token_data.liquidity_usd,
                                token_data.liquidity_sol,
                                liquidity_mc_ratio,
                                volume_mc_ratio,
                                token_data.volume_5m,
                                token_data.volume_1h,
                                token_data.volume_6h,
                                token_data.volume_24h,
                                token_data.price_change_5m,
                                token_data.price_change_1h,
                                token_data.price_change_6h,
                                token_data.price_change_24h,
                                viability_score,
                                risk_score,
                                momentum_score,
                                # Données rugcheck
                                rugcheck_data.get('rug_risk_score', 50),
                                rugcheck_data.get('rug_raw_score', 0),
                                rugcheck_data.get('is_rugged', False),
                                rugcheck_data.get('mint_authority_revoked', False),
                                rugcheck_data.get('freeze_authority_revoked', False),
                                rugcheck_data.get('top_holder_percentage', 0.0),
                                rugcheck_data.get('top_10_holders_percentage', 0.0),
                                rugcheck_data.get('insider_holders_count', 0),
                                rugcheck_data.get('insider_networks_detected', 0),
                                rugcheck_data.get('launchpad_name'),
                                rugcheck_data.get('is_pump_fun', False),
                                rugcheck_data.get('lp_providers_count', 0),
                                rugcheck_data.get('has_low_liquidity', False),
                                rugcheck_data.get('risk_count', 0),
                                current_timestamp if rugcheck_data else None,
                                current_timestamp,
                                token_data.metadata_source,
                                current_timestamp
                            ))
                finally:
                    conn.close()
                    
                # 4. Historiser le nouveau token après insertion (si nouveau)
                if not token_exists and (token_data.price_usd > 0 or token_data.market_cap > 0):
                    self.historize_token_data(token_data.address, token_data)
                elif not token_exists:
                    self.logger.debug(f"Skipping initial historization for {token_data.address[:8]}... - no significant data")
                
                return True
                    
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    wait_time = base_delay * (2 ** attempt)
                    self.logger.warning(f"Database locked during upsert, retry {attempt + 1}/{max_retries} in {wait_time:.2f}s")
                    time.sleep(wait_time)
                    continue
                else:
                    self.logger.error(f"Error upserting token {token_data.address} after {max_retries} attempts: {e}")
                    return False
                    
            except Exception as e:
                self.logger.error(f"Unexpected error upserting token {token_data.address}: {e}")
                return False

        return False


    def get_dashboard_priority_tokens(self) -> List[str]:
        """Get tokens that appear in the dashboard overview (high priority for updates)"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Requête identique à get_tokens_overview du dashboard
                query = """
                WITH token_stats AS (
                    SELECT 
                        t.token_mint,
                        COUNT(*) as total_transactions,
                        COUNT(CASE WHEN t.transaction_type = 'TransactionType.BUY' THEN 1 END) as total_buys,
                        COUNT(CASE WHEN t.transaction_type = 'TransactionType.SELL' THEN 1 END) as total_sells,
                        COUNT(DISTINCT CASE WHEN t.transaction_type = 'TransactionType.BUY' THEN t.wallet_address END) as unique_buyers,
                        COUNT(DISTINCT CASE WHEN t.transaction_type = 'TransactionType.SELL' THEN t.wallet_address END) as unique_sellers,
                        SUM(CASE WHEN t.transaction_type = 'TransactionType.BUY' THEN t.amount ELSE 0 END) as buy_volume,
                        SUM(CASE WHEN t.transaction_type = 'TransactionType.SELL' THEN t.amount ELSE 0 END) as sell_volume,
                        AVG(CASE WHEN t.transaction_type = 'TransactionType.BUY' THEN t.wallet_priority_at_detection END) as avg_buyer_priority,
                        MIN(t.block_time) as first_tx_timestamp,
                        MAX(t.block_time) as last_tx_timestamp,
                        MIN(CASE WHEN t.transaction_type = 'TransactionType.BUY' THEN t.created_at END) as first_discovery,
                        COUNT(CASE 
                            WHEN t.transaction_type = 'TransactionType.BUY' 
                            AND t.block_time >= (strftime('%s', 'now') - 86400) 
                            THEN 1 
                        END) as recent_buys_24h,
                        AVG(t.detection_delay) as avg_detection_delay
                    FROM transactions t
                    WHERE t.token_mint IS NOT NULL AND t.token_mint != ''
                    GROUP BY t.token_mint
                    HAVING total_buys > 0
                ),
                enriched_stats AS (
                    SELECT 
                        ts.*,
                        tk.symbol,
                        tk.name,
                        tk.price_usd,
                        tk.market_cap,
                        tk.last_price_update,
                        tk.metadata_source,
                        tk.timestamp_token_created,
                        CASE 
                            WHEN ts.sell_volume > 0 THEN ROUND(ts.buy_volume / ts.sell_volume, 2)
                            ELSE 999.99
                        END as volume_ratio,
                        ROUND(ts.avg_buyer_priority, 3) as avg_buyer_priority_rounded,
                        ROUND(
                            CASE 
                                WHEN ts.total_buys > 0 THEN (ts.recent_buys_24h * 100.0 / ts.total_buys)
                                ELSE 0 
                            END, 1
                        ) as recent_activity_pct,
                        ROUND((strftime('%s', 'now') - COALESCE(tk.timestamp_token_created, ts.first_tx_timestamp)) / 3600.0, 1) as token_age_hours,
                        ROUND((ts.first_discovery - COALESCE(tk.timestamp_token_created, ts.first_tx_timestamp)) / 3600.0, 1) as discovery_delay_hours
                    FROM token_stats ts
                    LEFT JOIN tokens tk ON ts.token_mint = tk.address
                )
                SELECT 
                    token_mint
                FROM enriched_stats
                ORDER BY 
                    (CASE WHEN volume_ratio > 10 THEN 10 ELSE volume_ratio END * 20) +
                    (unique_buyers * 2) +
                    (recent_activity_pct) +
                    (avg_buyer_priority_rounded * 50) +
                    (CASE WHEN discovery_delay_hours <= 2 THEN 30 WHEN discovery_delay_hours <= 6 THEN 20 ELSE 0 END)
                    DESC
                LIMIT ?
                """
                
                cursor.execute(query, (CONFIG['batch_size'] * 2,))  # Plus de tokens prioritaires
                results = cursor.fetchall()
                
                token_addresses = [row[0] for row in results if row[0]]
                self.logger.info(f"Found {len(token_addresses)} dashboard priority tokens")
                
                return token_addresses
                
        except Exception as e:
            self.logger.error(f"Error getting dashboard priority tokens: {e}")
            return []

    def get_dashboard_tokens_needing_update(self) -> List[str]:
        """Get dashboard tokens that need data updates (prioritized)"""
        try:
            dashboard_tokens = self.get_dashboard_priority_tokens()
            
            if not dashboard_tokens:
                return []
            self.logger.debug(f"DEBUG: Found {len(dashboard_tokens)} dashboard priority tokens to check for updates.")

            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Construire la requête avec placeholders
                placeholders = ','.join(['?' for _ in dashboard_tokens])
                cutoff_time = int(time.time()) - (CONFIG['price_update_interval'] // 2)
                self.logger.debug(f"DEBUG: Using cutoff time {datetime.fromtimestamp(cutoff_time)} for dashboard token updates.")

                query = f"""
                SELECT t.address 
                FROM tokens t
                WHERE t.address IN ({placeholders})
                AND t.is_dead = 0
                AND (t.no_data_available = 0 OR t.no_data_available IS NULL)
                AND (t.failed_attempts < ? OR t.failed_attempts IS NULL)
                AND (
                    t.last_price_update < ? 
                    OR t.last_price_update IS NULL
                    OR t.price_usd IS NULL 
                    OR t.price_usd = 0
                    OR t.market_cap IS NULL 
                    OR t.market_cap = 0
                    OR t.symbol IS NULL
                    OR t.name IS NULL
                )
                ORDER BY 
                    CASE WHEN t.last_price_update IS NULL THEN 0 ELSE t.last_price_update END ASC
                """
                
                params = dashboard_tokens + [CONFIG['max_failed_attempts'], cutoff_time]
                cursor.execute(query, params)
                results = cursor.fetchall()
                
                priority_tokens = [row[0] for row in results]
                self.logger.info(f"Found {len(priority_tokens)} dashboard tokens needing updates (from a pool of {len(dashboard_tokens)}).")

                
                return priority_tokens
                
        except Exception as e:
            self.logger.error(f"Error getting dashboard tokens needing update: {e}")
            return []

    def get_tokens_missing_creation_timestamp(self) -> List[str]:
        """Get tokens that need creation timestamp updates"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                query = """
                SELECT address 
                FROM tokens 
                WHERE (timestamp_token_created IS NULL OR timestamp_token_created = 0)
                AND is_dead = 0
                ORDER BY created_at DESC
                LIMIT ?
                """
                
                cursor.execute(query, (CONFIG['batch_size'],))
                results = cursor.fetchall()
                
                return [row[0] for row in results]
                
        except Exception as e:
            self.logger.error(f"Error getting tokens missing creation timestamp: {e}")
            return []
    
    def update_token_creation_timestamp(self, token_address: str) -> bool:
        """Update only the creation timestamp for a specific token"""
        try:
            # Get creation timestamp
            creation_timestamp = self.get_token_creation_timestamp(token_address)
            
            if creation_timestamp:
                with self.get_db_connection() as conn:
                    cursor = conn.cursor()
                    
                    cursor.execute("""
                        UPDATE tokens 
                        SET timestamp_token_created = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE address = ?
                    """, (creation_timestamp, token_address))
                    
                    conn.commit()
                    
                    if cursor.rowcount > 0:
                        self.logger.info(f"✅ Updated creation timestamp for {token_address[:8]}...")
                        return True
                    else:
                        self.logger.warning(f"⚠️ Token not found in database: {token_address[:8]}...")
                        return False
            else:
                self.logger.warning(f"❌ Could not find creation timestamp for {token_address[:8]}...")
                return False
                
        except Exception as e:
            self.logger.error(f"Error updating creation timestamp for {token_address}: {e}")
            return False
    
    def update_missing_creation_timestamps(self) -> int:
        """Update creation timestamps for tokens that are missing them"""
        self.logger.info("Starting creation timestamp updates for existing tokens...")
        
        tokens_to_update = self.get_tokens_missing_creation_timestamp()
        
        if not tokens_to_update:
            self.logger.info("No tokens need creation timestamp updates")
            return 0
        
        successful_updates = 0
        
        for token_address in tokens_to_update:
            try:
                if self.update_token_creation_timestamp(token_address):
                    successful_updates += 1
                
                # Rate limiting between creation timestamp requests
                time.sleep(CONFIG['api_rate_limit'])
                
            except Exception as e:
                self.logger.error(f"Error updating creation timestamp for {token_address}: {e}")
                continue
        
        self.logger.info(f"Creation timestamp update completed: {successful_updates}/{len(tokens_to_update)} successful")
        
        return successful_updates

    def get_tokens_needing_pumpfun_update(self) -> List[str]:
        """Get tokens with missing market data (likely Pump.fun tokens)"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                query = """
                SELECT address 
                FROM tokens 
                WHERE (market_cap IS NULL OR market_cap = 0 OR market_cap < 1000)
                AND (metadata_source IS NULL OR metadata_source NOT LIKE '%pumpfun%')
                AND (created_at >= datetime('now', '-7 days'))
                AND is_dead = 0
                ORDER BY created_at DESC
                LIMIT ?
                """
                
                cursor.execute(query, (CONFIG['batch_size'] // 2,))  # Batch plus petit
                results = cursor.fetchall()
                
                return [row[0] for row in results]
                
        except Exception as e:
            self.logger.error(f"Error getting tokens needing Pump.fun update: {e}")
            return []

    def update_pumpfun_tokens(self) -> int:
        """Update Pump.fun tokens with missing data"""
        self.logger.info("Starting Pump.fun data updates for tokens with missing market data...")
        
        tokens_to_update = self.get_tokens_needing_pumpfun_update()
        
        if not tokens_to_update:
            self.logger.info("No tokens need Pump.fun updates")
            return 0
        
        successful_updates = 0
        
        for token_address in tokens_to_update:
            try:
                self.logger.info(f"Fetching Pump.fun data for: {token_address[:8]}...")
                
                # Get data from Pump.fun
                pumpfun_data = self.get_pumpfun_data(token_address)
                
                if pumpfun_data:
                    # Update only the missing fields in database
                    if self.update_token_with_pumpfun_data(token_address, pumpfun_data):
                        successful_updates += 1
                        self.logger.info(f"✅ Updated Pump.fun data for: {token_address[:8]}...")
                    else:
                        self.logger.warning(f"❌ Failed to save Pump.fun data for: {token_address[:8]}...")
                else:
                    self.logger.debug(f"No Pump.fun data found for: {token_address[:8]}...")
                
                # Rate limiting spécifique pour Pump.fun
                time.sleep(CONFIG.get('pumpfun_rate_limit', 1.0))
                
            except Exception as e:
                self.logger.error(f"Error updating Pump.fun data for {token_address}: {e}")
                
                # Gestion spécifique des erreurs 530
                if "530" in str(e):
                    self.logger.warning("530 Server error detected, waiting longer...")
                    time.sleep(5)
                
                continue
        
        self.logger.info(f"Pump.fun update completed: {successful_updates}/{len(tokens_to_update)} successful")
        
        return successful_updates

    def update_token_with_pumpfun_data(self, token_address: str, pumpfun_data: TokenData) -> bool:
        """Update existing token with Pump.fun data (only missing fields)"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Update seulement les champs manquants
                query = """
                UPDATE tokens SET
                    symbol = COALESCE(symbol, ?),
                    name = COALESCE(name, ?),
                    price_usd = CASE WHEN price_usd = 0 OR price_usd IS NULL THEN ? ELSE price_usd END,
                    market_cap = CASE WHEN market_cap = 0 OR market_cap IS NULL THEN ? ELSE market_cap END,
                    volume_24h = CASE WHEN volume_24h = 0 OR volume_24h IS NULL THEN ? ELSE volume_24h END,
                    logo_uri = COALESCE(logo_uri, ?),
                    timestamp_token_created = CASE WHEN (timestamp_token_created = 0 OR timestamp_token_created IS NULL) AND ? > 0 THEN ? ELSE timestamp_token_created END,
                    creator_address = COALESCE(creator_address, ?), 
                    bonding_curve_progress = CASE WHEN bonding_curve_progress = 0 OR bonding_curve_progress IS NULL THEN ? ELSE bonding_curve_progress END, 
                    holder_count = CASE WHEN holder_count = 0 OR holder_count IS NULL THEN ? ELSE holder_count END,  
                    metadata_source = CASE 
                        WHEN metadata_source IS NULL THEN ?
                        WHEN metadata_source NOT LIKE '%pumpfun%' THEN metadata_source || '+pumpfun'
                        ELSE metadata_source
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE address = ?
                """
                
                cursor.execute(query, (
                    pumpfun_data.symbol,
                    pumpfun_data.name,
                    pumpfun_data.price_usd,
                    pumpfun_data.market_cap,
                    pumpfun_data.volume_24h,
                    pumpfun_data.logo_uri,
                    pumpfun_data.timestamp_token_created,
                    pumpfun_data.timestamp_token_created,
                    pumpfun_data.creator_address,  
                    pumpfun_data.bonding_curve_progress,  
                    pumpfun_data.holder_count,  
                    pumpfun_data.metadata_source,
                    token_address
                ))
                
                conn.commit()
                
                return cursor.rowcount > 0
                
        except Exception as e:
            self.logger.error(f"Error updating token with Pump.fun data {token_address}: {e}")
            return False

    def run_historization_cycle(self) -> int:
        """Run historization for tokens that need it"""
        self.logger.info("Starting historization cycle...")
        
        tokens_to_historize = self.get_tokens_needing_historization()
        
        if not tokens_to_historize:
            self.logger.info("No tokens need historization")
            return 0
        
        historized_count = 0
        
        for token_address in tokens_to_historize:
            try:
                if self.historize_token_data(token_address):
                    historized_count += 1
                
            except Exception as e:
                self.logger.error(f"Error historizing token {token_address}: {e}")
                continue
        
        self.logger.info(f"Historization cycle completed: {historized_count}/{len(tokens_to_historize)} successful")
        
        return historized_count

    def run_dead_token_check(self) -> int:
        """Run dead token detection cycle"""
        self.logger.info("Starting dead token check cycle...")
        
        marked_count = self.check_and_mark_dead_tokens()
        
        self.logger.info(f"Dead token check completed: {marked_count} tokens marked as dead")
        
        return marked_count

    async def _fetch_one_token_data_async(self, session: aiohttp.ClientSession, token_address: str, semaphore: asyncio.Semaphore) -> Optional[TokenData]:
        """Coroutine to fetch and parse data for a single token address."""
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        # self.logger.debug(f"Fetching URL: {url}") # Uncomment for deep debug
        async with semaphore:
            try:
                start_time = time.time()
                async with session.get(url, timeout=CONFIG['request_timeout']) as response:
                    api_duration = time.time() - start_time
                    
                    self.api_tracker.record_call(
                        'dexscreener_tokens_async', 
                        api_duration, 
                        success=(response.status == 200),
                        http_status=response.status
                    )
                    self.stats['api_calls'] += 1

                    if response.status == 200:
                        data = await response.json()
                        if data and 'pairs' in data and data['pairs']:
                            valid_pairs = [p for p in data['pairs'] if p.get('fdv') and float(p.get('fdv', 0)) > 0]
                            if not valid_pairs:
                                return None
                            
                            best_pair = max(valid_pairs, key=lambda x: float(x.get('liquidity', {}).get('usd', 0) or 0))
                            
                            creation_timestamp = 0
                            if 'pairCreatedAt' in best_pair:
                                creation_time = best_pair['pairCreatedAt']
                                if creation_time and creation_time > 1e12:
                                    creation_timestamp = int(creation_time // 1000)
                                elif creation_time:
                                    creation_timestamp = int(creation_time)

                            token_data = TokenData(
                                address=token_address,
                                symbol=best_pair.get('baseToken', {}).get('symbol'),
                                name=best_pair.get('baseToken', {}).get('name'),
                                price_usd=float(best_pair.get('priceUsd', 0) or 0),
                                timestamp_token_created=creation_timestamp,
                                market_cap=float(best_pair.get('fdv', 0) or 0),
                                volume_5m=float(best_pair.get('volume', {}).get('m5', 0) or 0),
                                volume_1h=float(best_pair.get('volume', {}).get('h1', 0) or 0),
                                volume_6h=float(best_pair.get('volume', {}).get('h6', 0) or 0),
                                volume_24h=float(best_pair.get('volume', {}).get('h24', 0) or 0),
                                price_change_5m=float(best_pair.get('priceChange', {}).get('m5', 0) or 0),
                                price_change_1h=float(best_pair.get('priceChange', {}).get('h1', 0) or 0),
                                price_change_6h=float(best_pair.get('priceChange', {}).get('h6', 0) or 0),
                                price_change_24h=float(best_pair.get('priceChange', {}).get('h24', 0) or 0),
                                liquidity_usd=float(best_pair.get('liquidity', {}).get('usd', 0) or 0),
                                liquidity_sol=float(best_pair.get('liquidity', {}).get('base', 0) or 0),
                                fdv=float(best_pair.get('fdv', 0) or 0),
                                metadata_source="dexscreener_async",
                                original_address=token_address
                            )
                            return token_data
                    return None
            except asyncio.TimeoutError:
                self.logger.warning(f"Async fetch timed out for {token_address[:8]}...")
                return None
            except Exception as e:
                self.logger.error(f"Async fetch failed for {token_address[:8]}...: {e}")
                return None

    async def process_tokens_in_batches_async(self, tokens: List[str]) -> int:
        """Processes a list of tokens asynchronously."""
        if not tokens:
            return 0
        
        start_time = time.time()
        successful_upserts = 0
        failed_tokens = []
        
        # Limit concurrency to avoid getting rate-limited
        semaphore = asyncio.Semaphore(5) 
        
        async with aiohttp.ClientSession() as session:
            tasks = [self._fetch_one_token_data_async(session, token, semaphore) for token in tokens]
            results = await asyncio.gather(*tasks)

        # Process results
        for i, token_data in enumerate(results):
            token_address = tokens[i]
            if token_data:
                # This is a blocking call. We will make it non-blocking in the next step.
                if self.upsert_token(token_data):
                   successful_upserts += 1
                else:
                    failed_tokens.append(token_address)
            else:
                # If fetch failed, create a stub to avoid re-processing immediately
                self.create_token_stub(token_address)
                failed_tokens.append(token_address)
        
        self.stats['successful_updates'] += successful_upserts
        self.stats['failed_updates'] += len(failed_tokens)
        self.stats['processed_tokens'] += len(tokens)

        total_duration = time.time() - start_time
        self.logger.info(f"🏁 Async batch completed: {successful_upserts}/{len(tokens)} successful in {total_duration:.2f}s")
        
        return successful_upserts
    
    async def _fetch_one_token_data_async(self, session: aiohttp.ClientSession, token_address: str, semaphore: asyncio.Semaphore) -> Optional[TokenData]:
        """Coroutine to fetch and parse data for a single token address."""
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        # self.logger.debug(f"Fetching URL: {url}") # Uncomment for deep debug
        async with semaphore:
            try:
                start_time = time.time()
                async with session.get(url, timeout=CONFIG['request_timeout']) as response:
                    api_duration = time.time() - start_time
                    
                    self.api_tracker.record_call(
                        'dexscreener_tokens_async', 
                        api_duration, 
                        success=(response.status == 200),
                        http_status=response.status
                    )
                    self.stats['api_calls'] += 1

                    if response.status == 200:
                        data = await response.json()
                        if data and 'pairs' in data and data['pairs']:
                            valid_pairs = [p for p in data['pairs'] if p.get('fdv') and float(p.get('fdv', 0)) > 0]
                            if not valid_pairs:
                                return None
                            
                            best_pair = max(valid_pairs, key=lambda x: float(x.get('liquidity', {}).get('usd', 0) or 0))
                            
                            creation_timestamp = 0
                            if 'pairCreatedAt' in best_pair:
                                creation_time = best_pair['pairCreatedAt']
                                if creation_time and creation_time > 1e12:
                                    creation_timestamp = int(creation_time // 1000)
                                elif creation_time:
                                    creation_timestamp = int(creation_time)

                            token_data = TokenData(
                                address=token_address,
                                symbol=best_pair.get('baseToken', {}).get('symbol'),
                                name=best_pair.get('baseToken', {}).get('name'),
                                price_usd=float(best_pair.get('priceUsd', 0) or 0),
                                timestamp_token_created=creation_timestamp,
                                market_cap=float(best_pair.get('fdv', 0) or 0),
                                volume_5m=float(best_pair.get('volume', {}).get('m5', 0) or 0),
                                volume_1h=float(best_pair.get('volume', {}).get('h1', 0) or 0),
                                volume_6h=float(best_pair.get('volume', {}).get('h6', 0) or 0),
                                volume_24h=float(best_pair.get('volume', {}).get('h24', 0) or 0),
                                price_change_5m=float(best_pair.get('priceChange', {}).get('m5', 0) or 0),
                                price_change_1h=float(best_pair.get('priceChange', {}).get('h1', 0) or 0),
                                price_change_6h=float(best_pair.get('priceChange', {}).get('h6', 0) or 0),
                                price_change_24h=float(best_pair.get('priceChange', {}).get('h24', 0) or 0),
                                liquidity_usd=float(best_pair.get('liquidity', {}).get('usd', 0) or 0),
                                liquidity_sol=float(best_pair.get('liquidity', {}).get('base', 0) or 0),
                                fdv=float(best_pair.get('fdv', 0) or 0),
                                metadata_source="dexscreener_async",
                                original_address=token_address
                            )
                            return token_data
                    return None
            except asyncio.TimeoutError:
                self.logger.warning(f"Async fetch timed out for {token_address[:8]}...")
                return None
            except Exception as e:
                self.logger.error(f"Async fetch failed for {token_address[:8]}...: {e}")
                return None

    async def process_tokens_in_batches_async(self, tokens: List[str]) -> int:
        """Processes a list of tokens asynchronously."""
        if not tokens:
            return 0
        
        start_time = time.time()
        successful_upserts = 0
        failed_tokens = []
        
        # Limit concurrency to avoid getting rate-limited
        semaphore = asyncio.Semaphore(5) 
        
        async with aiohttp.ClientSession() as session:
            tasks = [self._fetch_one_token_data_async(session, token, semaphore) for token in tokens]
            results = await asyncio.gather(*tasks)

        # Process results by running DB operations in a thread pool to avoid blocking
        db_tasks = []
        for i, token_data in enumerate(results):
            token_address = tokens[i]
            if token_data:
                db_tasks.append(asyncio.to_thread(self.upsert_token, token_data))
            else:
                # If fetch failed, create a stub to avoid re-processing immediately
                db_tasks.append(asyncio.to_thread(self.create_token_stub, token_address))

        # Run all database operations concurrently
        db_results = await asyncio.gather(*db_tasks, return_exceptions=True)

        successful_upserts = 0
        failed_count = 0
        for i, result in enumerate(db_results):
            if isinstance(result, Exception):
                self.logger.error(f"DB operation failed for token {tokens[i]}: {result}")
                failed_count += 1
            elif result: # If the operation returned True
                # We only count an upsert as successful if it came from a successful fetch
                if results[i] is not None:
                    successful_upserts += 1
            else:
                failed_count += 1

        self.stats['successful_updates'] += successful_upserts
        self.stats['failed_updates'] += failed_count
        self.stats['processed_tokens'] += len(tokens)

        total_duration = time.time() - start_time
        self.logger.info(f"🏁 Async batch completed: {successful_upserts}/{len(tokens)} successful in {total_duration:.2f}s")
        
        return successful_upserts

    
    def sync_new_tokens(self) -> int:
        """Optimized version with async batch processing."""
        self.logger.info("🚀 Starting ASYNC token synchronization...")
        
        all_new_tokens = list(self.get_new_tokens_from_transactions())
        
        if not all_new_tokens:
            self.logger.info("No new tokens to process")
            return 0
        
        # We can process them all in one async run, priority doesn't matter for fetching
        # as much when it's all concurrent.
        self.logger.info(f"📊 Processing {len(all_new_tokens)} new tokens asynchronously")
        
        return asyncio.run(self.process_tokens_in_batches_async(all_new_tokens))

    def update_existing_prices(self) -> int:
        """Optimized version to update existing token prices asynchronously."""
        self.logger.info("🔄 Starting ASYNC price updates...")
        
        # 1. Get dashboard tokens needing updates first
        dashboard_tokens = self.get_dashboard_tokens_needing_update()
        
        # 2. Get other tokens needing updates
        other_tokens = self.get_tokens_needing_price_update()
        
        # Combine and deduplicate, keeping dashboard tokens at the front for priority
        tokens_to_update = list(dict.fromkeys(dashboard_tokens + other_tokens))
        
        if not tokens_to_update:
            self.logger.info("No tokens need price updates.")
            return 0
        
        self.logger.info(f"Found {len(tokens_to_update)} total tokens for price update (Dashboard: {len(dashboard_tokens)})")
        
        # Process all tokens in one async batch
        return asyncio.run(self.process_tokens_in_batches_async(tokens_to_update))

    
   

    def get_flagged_tokens_stats(self) -> Dict:
        """Get statistics about flagged tokens"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Tokens marqués comme no_data
                cursor.execute("SELECT COUNT(*) FROM tokens WHERE no_data_available = 1")
                no_data_count = cursor.fetchone()[0]
                
                # Tokens avec des tentatives échouées mais pas encore flaggés
                cursor.execute("SELECT COUNT(*) FROM tokens WHERE failed_attempts > 0 AND no_data_available = 0")
                partial_failures = cursor.fetchone()[0]
                
                # Tokens éligibles pour retry
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens 
                    WHERE no_data_available = 1 
                    AND no_data_last_check < datetime('now', '-' || ? || ' days')
                """, (CONFIG['retry_failed_after_days'],))
                retry_eligible = cursor.fetchone()[0]
                
                # Tokens morts
                cursor.execute("SELECT COUNT(*) FROM tokens WHERE is_dead = 1")
                dead_count = cursor.fetchone()[0]
                
                return {
                    'no_data_flagged': no_data_count,
                    'partial_failures': partial_failures,
                    'retry_eligible': retry_eligible,
                    'dead_tokens': dead_count
                }
                
        except Exception as e:
            self.logger.error(f"Error getting flagged tokens stats: {e}")
            return {}

    def print_statistics(self):
        """Print current statistics"""
        if self.stats['start_time']:
            runtime = time.time() - self.stats['start_time']
            runtime_str = str(timedelta(seconds=int(runtime)))
        else:
            runtime_str = "N/A"
        
        # Stats de flagging
        flagged_stats = self.get_flagged_tokens_stats()
        
        
        self.logger.info("=== TOKEN SYNC STATISTICS ===")
        self.logger.info(f"Runtime: {runtime_str}")
        self.logger.info(f"Processed tokens: {self.stats['processed_tokens']}")
        self.logger.info(f"Successful updates: {self.stats['successful_updates']}")
        self.logger.info(f"Failed updates: {self.stats['failed_updates']}")
        self.logger.info(f"API calls made: {self.stats['api_calls']}")
        self.logger.info(f"Tokens historized: {self.stats['tokens_historized']}")
        self.logger.info(f"Tokens marked dead: {self.stats['tokens_marked_dead']}")
        
        # Stats de flagging
        if flagged_stats:
            self.logger.info("=== FLAGGED TOKENS STATS ===")
            self.logger.info(f"Tokens marked as no-data: {flagged_stats.get('no_data_flagged', 0)}")
            self.logger.info(f"Tokens with partial failures: {flagged_stats.get('partial_failures', 0)}")
            self.logger.info(f"Tokens eligible for retry: {flagged_stats.get('retry_eligible', 0)}")
            self.logger.info(f"Dead tokens: {flagged_stats.get('dead_tokens', 0)}")

        if self.stats['processed_tokens'] > 0:
            success_rate = (self.stats['successful_updates'] / self.stats['processed_tokens']) * 100
            self.logger.info(f"Success rate: {success_rate:.1f}%")

        self.print_api_statistics()
    

    def print_api_statistics(self):
        """Print detailed API statistics"""
        try:
            api_stats = self.api_tracker.get_stats()
            
            if not api_stats:
                self.logger.info("=== 📡 API STATISTICS ===")
                self.logger.info("No API statistics available")
                return
            
            self.logger.info("=== 📡 API STATISTICS ===")
            
            # Sort by total calls for better readability
            sorted_apis = sorted(api_stats.items(), key=lambda x: x[1].get('total_calls', 0), reverse=True)
            
            for api_name, stats in sorted_apis:
                if stats.get('total_calls', 0) > 0:  # Only show APIs that have been called
                    self.logger.info(f"🔗 {api_name.upper()}")
                    self.logger.info(f"   Total: {stats.get('total_calls', 0)} calls | {stats.get('total_duration_seconds', 0)}s | avg {stats.get('avg_duration_seconds', 0)}s")
                    self.logger.info(f"   Recent: 5m={stats.get('calls_5m', 0)} | 30m={stats.get('calls_30m', 0)} | 1h={stats.get('calls_1h', 0)}")
                    self.logger.info(f"   Rate/min: 5m={stats.get('rate_per_minute_5m', 0)} | 30m={stats.get('rate_per_minute_30m', 0)} | 1h={stats.get('rate_per_minute_1h', 0)}")
                    
                    # Alert if rate is too high
                    if stats.get('rate_per_minute_5m', 0) > 10:  # Plus de 10 appels/min sur 5min
                        self.logger.warning(f"   ⚠️ HIGH RATE: {stats.get('rate_per_minute_5m', 0)} calls/min")
            
            # Summary
            total_calls = sum(stats.get('total_calls', 0) for stats in api_stats.values())
            total_duration = sum(stats.get('total_duration_seconds', 0) for stats in api_stats.values())
            total_5m = sum(stats.get('calls_5m', 0) for stats in api_stats.values())
            
            self.logger.info(f"📊 SUMMARY: {total_calls} total calls | {total_duration:.1f}s total | {total_5m} calls last 5min")
            
        except Exception as e:
            self.logger.error(f"Error printing API statistics: {e}")
            # Debug info
            self.logger.debug(f"API tracker exists: {hasattr(self, 'api_tracker')}")
            if hasattr(self, 'api_tracker'):
                self.logger.debug(f"API tracker type: {type(self.api_tracker)}")
                self.logger.debug(f"API tracker stats keys: {list(self.api_tracker.stats.keys()) if hasattr(self.api_tracker, 'stats') else 'No stats'}")

    
    def record_call(self, api_name: str, duration: float, success: bool = True, 
                http_status: int = None, error_msg: str = None):
        """Record an API call with duration and store in database - DEBUG VERSION"""
        current_time = time.time()
        duration_ms = int(duration * 1000)  # Convert to milliseconds
        
        # DEBUG: Log every call
        print(f"🔍 DEBUG API: Recording {api_name} call - duration: {duration:.3f}s, success: {success}, cycle: {self.current_cycle_id}")
        
        with self.lock:
            # Update in-memory stats (existing logic)
            api_stats = self.stats[api_name]
            api_stats.total_calls += 1
            api_stats.total_duration += duration
            
            call_record = (current_time, duration)
            api_stats.calls_5m.append(call_record)
            api_stats.calls_30m.append(call_record)
            api_stats.calls_1h.append(call_record)
            
            self._clean_old_records(api_stats, current_time)
        
        # Store in database (non-blocking)
        if self.db_service:
            try:
                result = self._store_api_call_to_db(
                    api_name, int(current_time), duration_ms, 
                    success, http_status, error_msg
                )
                print(f"🔍 DEBUG API: DB storage result for {api_name}: {result}")
            except Exception as e:
                # Don't fail the API call if DB storage fails
                print(f"❌ DEBUG API: Failed to store API metric to DB: {e}")
                if hasattr(self.db_service, 'logger'):
                    self.db_service.logger.error(f"Failed to store API metric: {e}")

    def get_api_summary(self) -> str:
        """Get a quick API summary for live monitoring"""
        api_stats = self.api_tracker.get_stats()
        
        if not api_stats:
            return "No API data"
        
        total_5m = sum(stats['calls_5m'] for stats in api_stats.values())
        total_30m = sum(stats['calls_30m'] for stats in api_stats.values())
        
        # Top 3 APIs by recent activity
        top_apis = sorted(api_stats.items(), key=lambda x: x[1]['calls_5m'], reverse=True)[:3]
        top_summary = " | ".join([f"{name}:{stats['calls_5m']}" for name, stats in top_apis if stats['calls_5m'] > 0])
        
        return f"APIs 5m: {total_5m} total ({top_summary}) | 30m: {total_30m}"

    def run_sync_cycle(self):
        """Run one complete synchronization cycle"""
        self.logger.info("Starting synchronization cycle...")
        self.logger.info(f"🔍 API tracker status: {hasattr(self, 'api_tracker')}")
        cycle_id = self.start_sync_cycle()
        total_tokens_processed = 0
        
        try:
            # 1. Sync new tokens from transactions
            new_tokens_updated = self.sync_new_tokens()
            self.logger.info("=== STATS API APRÈS NOUVEAUX TOKENS ===")
            self.print_api_statistics()
            
            # 2. Update existing token prices
            prices_updated = self.update_existing_prices()
            self.logger.info("=== STATS API APRÈS PRIX ===")
            self.print_api_statistics()
            self.print_api_database_stats()
            
            total_tokens_processed = new_tokens_updated + prices_updated
            self.logger.info(f"Sync cycle completed: {new_tokens_updated} new, {prices_updated} price updates...")
            
            # 3. Run historization cycle (every few cycles)
            if not hasattr(self, 'cycle_count'):
                self.cycle_count = 0
            
            self.cycle_count += 1
            creation_timestamps_updated = 0
            historized_count = 0
            dead_tokens_marked = 0
            
            # Every 3 cycles - run historization
            if self.cycle_count % 3 == 0:
                historized_count = self.run_historization_cycle()
                self.logger.info("=== STATS API APRÈS HISTORISATION ===")
                self.print_api_statistics()

            # Every 5 cycles - update missing creation timestamps
            if self.cycle_count % 5 == 0:
                creation_timestamps_updated = self.update_missing_creation_timestamps()
                self.logger.info("=== STATS API APRÈS TIMESTAMPS ===")
                self.print_api_statistics()
            
            # Every 6 cycles - check for dead tokens
            if self.cycle_count % 6 == 0:
                dead_tokens_marked = self.run_dead_token_check()
                self.logger.info("=== STATS API APRÈS DEAD TOKENS ===")
                self.print_api_statistics()

            # Every 10 cycles - update Pump.fun tokens
            if self.cycle_count % 10 == 0:
                pumpfun_updated = self.update_pumpfun_tokens()
                self.logger.info(f"Pump.fun tokens updated: {pumpfun_updated}")
                self.logger.info("=== STATS API APRÈS PUMPFUN ===")
                self.print_api_statistics()

            # 4. Print statistics
            self.print_statistics()
            
            self.logger.info(f"Sync cycle completed: {new_tokens_updated} new, {prices_updated} price updates, {creation_timestamps_updated} creation timestamps, {historized_count} historized, {dead_tokens_marked} marked dead")
            
        except Exception as e:
            self.logger.error(f"Error in sync cycle: {e}")
        finally:
            # ✅ CORRECTION - Terminer le cycle dans le finally
            self.end_sync_cycle(total_tokens_processed)

    def start(self):
        """Start the continuous synchronization service"""
        self.logger.info("Starting Token Sync Service...")

        if not self.check_database_health():
            self.logger.error("❌ Database health check failed. Stopping service.")
            return
        
        self.running = True
        self.stats['start_time'] = time.time()

        try:
            while self.running:
                # Vérifier la santé de la DB périodiquement
                if not hasattr(self, 'last_health_check'):
                    self.last_health_check = time.time()
                
                # Check database health every 30 minutes
                if time.time() - self.last_health_check > 1800:
                    if not self.check_database_health():
                        self.logger.warning("⚠️ Database health check failed during operation")
                    self.last_health_check = time.time()

                self.run_sync_cycle()
                
                if self.running:  # Check if still running before sleeping
                    self.logger.info(f"Waiting {CONFIG['update_interval']} seconds until next cycle...")
                    time.sleep(CONFIG['update_interval'])
                    
        except KeyboardInterrupt:
            self.logger.info("Received interrupt signal")
        except Exception as e:
            self.logger.error(f"Unexpected error in main loop: {e}")
        finally:
            self.stop()
    
    def stop(self):
        """Stop the synchronization service"""
        self.logger.info("Stopping Token Sync Service...")
        self.running = False
        self.session.close()
        self.print_statistics()
        self.logger.info("Token Sync Service stopped")

def signal_handler(signum, frame):
    """Handle termination signals"""
    global service
    if service:
        service.stop()
    sys.exit(0)

def main():
    """Main entry point"""
    global service
    
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("Token Data Synchronization Backend with Historical Tracking")
    print("=" * 60)
    print(f"Database: {CONFIG['db_path']}")
    print(f"Update interval: {CONFIG['update_interval']} seconds")
    print(f"Price update interval: {CONFIG['price_update_interval']} seconds")
    print(f"Historization interval: {CONFIG['historization_interval']} seconds")
    print(f"Dead token check interval: {CONFIG['dead_token_check_interval']} seconds")
    print(f"API rate limit: {CONFIG['api_rate_limit']} seconds")
    print("=" * 60)
    
    # Initialize service
    service = TokenSyncService(CONFIG['db_path'])
    
    # Start service
    service.start()

if __name__ == "__main__":
    service = None
    main()