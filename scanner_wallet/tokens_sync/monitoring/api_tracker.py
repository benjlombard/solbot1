"""
API Tracker
Comprehensive monitoring and tracking of API calls with database storage and real-time metrics.
"""
import time
import threading
import logging
from typing import Dict, Optional, List, Tuple
from collections import deque, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..database.connection import DatabaseConnection, db_retry


@dataclass
class ApiCallStats:
    """Statistics for a specific API endpoint"""
    total_calls: int = 0
    total_duration: float = 0.0
    successful_calls: int = 0
    failed_calls: int = 0
    
    # Time-windowed tracking
    calls_1m: deque = field(default_factory=deque)
    calls_5m: deque = field(default_factory=deque)
    calls_30m: deque = field(default_factory=deque)
    calls_1h: deque = field(default_factory=deque)
    
    # Performance metrics
    min_duration: float = float('inf')
    max_duration: float = 0.0
    
    # Error tracking
    last_error: Optional[str] = None
    last_error_time: Optional[float] = None
    consecutive_failures: int = 0


@dataclass
class ApiCallRecord:
    """Individual API call record"""
    api_name: str
    timestamp: float
    duration_ms: int
    success: bool
    http_status: Optional[int] = None
    error_message: Optional[str] = None
    cycle_id: Optional[int] = None


class ApiTracker:
    """
    Comprehensive API tracking with real-time metrics and database storage
    """
    
    def __init__(
        self, 
        db_connection: Optional[DatabaseConnection] = None, 
        logger: Optional[logging.Logger] = None
    ):
        self.db_connection = db_connection
        self.logger = logger or logging.getLogger(__name__)
        
        # Thread-safe statistics storage
        self.stats = defaultdict(lambda: ApiCallStats())
        self.lock = threading.Lock()
        
        # Current cycle tracking
        self.current_cycle_id = None
        
        # Global metrics
        self.start_time = time.time()
        self.total_api_calls = 0
        
        # Performance thresholds
        self.slow_call_threshold = 5.0  # seconds
        self.rate_limit_threshold = 50  # calls per minute
        
        self.logger.debug("✅ API Tracker initialized")
    
    def set_current_cycle(self, cycle_id: int):
        """Set the current sync cycle ID for tracking"""
        with self.lock:
            self.current_cycle_id = cycle_id
        self.logger.debug(f"🔄 API Tracker set to cycle {cycle_id}")
    
    def record_call(
        self, 
        api_name: str, 
        duration: float, 
        success: bool = True,
        http_status: Optional[int] = None, 
        error_msg: Optional[str] = None
    ):
        """
        Record an API call with comprehensive metrics
        
        Args:
            api_name: Name of the API endpoint
            duration: Call duration in seconds
            success: Whether the call was successful
            http_status: HTTP status code
            error_msg: Error message if failed
        """
        current_time = time.time()
        duration_ms = int(duration * 1000)
        
        with self.lock:
            # Update in-memory stats
            api_stats = self.stats[api_name]
            self._update_api_stats(api_stats, current_time, duration, success, error_msg)
            
            # Clean old records from time windows
            self._clean_old_records(api_stats, current_time)
            
            # Update global metrics
            self.total_api_calls += 1
        
        # Store in database (non-blocking)
        if self.db_connection:
            try:
                self._store_api_call_to_db(
                    api_name, int(current_time), duration_ms, 
                    success, http_status, error_msg
                )
            except Exception as e:
                # Don't fail the API call if DB storage fails
                self.logger.debug(f"Failed to store API metric to DB: {e}")
        
        # Log performance warnings
        self._check_performance_warnings(api_name, duration, success)
    
    def _update_api_stats(
        self, 
        api_stats: ApiCallStats, 
        current_time: float, 
        duration: float, 
        success: bool, 
        error_msg: Optional[str]
    ):
        """Update API statistics in memory"""
        # Basic counters
        api_stats.total_calls += 1
        api_stats.total_duration += duration
        
        if success:
            api_stats.successful_calls += 1
            api_stats.consecutive_failures = 0
        else:
            api_stats.failed_calls += 1
            api_stats.consecutive_failures += 1
            api_stats.last_error = error_msg
            api_stats.last_error_time = current_time
        
        # Performance metrics
        api_stats.min_duration = min(api_stats.min_duration, duration)
        api_stats.max_duration = max(api_stats.max_duration, duration)
        
        # Add to time windows
        call_record = (current_time, duration, success)
        api_stats.calls_1m.append(call_record)
        api_stats.calls_5m.append(call_record)
        api_stats.calls_30m.append(call_record)
        api_stats.calls_1h.append(call_record)
    
    def _clean_old_records(self, api_stats: ApiCallStats, current_time: float):
        """Remove old records from time windows"""
        # 1 minute window
        while api_stats.calls_1m and current_time - api_stats.calls_1m[0][0] > 60:
            api_stats.calls_1m.popleft()
        
        # 5 minute window
        while api_stats.calls_5m and current_time - api_stats.calls_5m[0][0] > 300:
            api_stats.calls_5m.popleft()
        
        # 30 minute window
        while api_stats.calls_30m and current_time - api_stats.calls_30m[0][0] > 1800:
            api_stats.calls_30m.popleft()
        
        # 1 hour window
        while api_stats.calls_1h and current_time - api_stats.calls_1h[0][0] > 3600:
            api_stats.calls_1h.popleft()
    
    @db_retry(max_retries=2, delay=0.1)
    def _store_api_call_to_db(
        self, 
        api_name: str, 
        timestamp: int, 
        duration_ms: int,
        success: bool, 
        http_status: Optional[int], 
        error_msg: Optional[str]
    ) -> bool:
        """Store API call metrics to database"""
        if not self.db_connection:
            return False
        
        try:
            with self.db_connection.get_connection_context() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO api_metrics (
                        api_name, call_timestamp, duration_ms, success,
                        http_status_code, error_message, sync_cycle_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    api_name, timestamp, duration_ms, success, 
                    http_status, error_msg, self.current_cycle_id
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            self.logger.debug(f"Failed to store API metric: {e}")
            return False
    
    def _check_performance_warnings(self, api_name: str, duration: float, success: bool):
        """Check for performance issues and log warnings"""
        # Slow call warning
        if duration > self.slow_call_threshold:
            self.logger.warning(
                f"🐌 Slow API call: {api_name} took {duration:.2f}s "
                f"(threshold: {self.slow_call_threshold}s)"
            )
        
        # Rate limiting warning
        with self.lock:
            api_stats = self.stats[api_name]
            calls_1m = len(api_stats.calls_1m)
            
            if calls_1m > self.rate_limit_threshold:
                self.logger.warning(
                    f"⚡ High API rate: {api_name} made {calls_1m} calls in last minute "
                    f"(threshold: {self.rate_limit_threshold})"
                )
        
        # Consecutive failures warning
        if not success:
            with self.lock:
                api_stats = self.stats[api_name]
                if api_stats.consecutive_failures >= 3:
                    self.logger.warning(
                        f"🚨 API failures: {api_name} has {api_stats.consecutive_failures} "
                        f"consecutive failures"
                    )
    
    def get_stats(self, api_name: Optional[str] = None) -> Dict:
        """
        Get statistics for specific API or all APIs
        
        Args:
            api_name: Specific API name, or None for all APIs
            
        Returns:
            Dictionary with API statistics
        """
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
        success_rate = (stats.successful_calls / stats.total_calls * 100) if stats.total_calls > 0 else 0
        
        # Count calls in time windows
        calls_1m = len(stats.calls_1m)
        calls_5m = len(stats.calls_5m)
        calls_30m = len(stats.calls_30m)
        calls_1h = len(stats.calls_1h)
        
        # Calculate success rates for time windows
        success_1m = sum(1 for _, _, success in stats.calls_1m if success)
        success_5m = sum(1 for _, _, success in stats.calls_5m if success)
        
        # Calculate average durations for time windows
        avg_1m = sum(d for _, d, _ in stats.calls_1m) / calls_1m if calls_1m > 0 else 0
        avg_5m = sum(d for _, d, _ in stats.calls_5m) / calls_5m if calls_5m > 0 else 0
        avg_30m = sum(d for _, d, _ in stats.calls_30m) / calls_30m if calls_30m > 0 else 0
        avg_1h = sum(d for _, d, _ in stats.calls_1h) / calls_1h if calls_1h > 0 else 0
        
        return {
            # Overall metrics
            'total_calls': stats.total_calls,
            'successful_calls': stats.successful_calls,
            'failed_calls': stats.failed_calls,
            'success_rate': round(success_rate, 2),
            'total_duration_seconds': round(stats.total_duration, 2),
            'avg_duration_seconds': round(avg_duration, 3),
            'min_duration_seconds': round(stats.min_duration, 3) if stats.min_duration != float('inf') else 0,
            'max_duration_seconds': round(stats.max_duration, 3),
            
            # Time-windowed metrics
            'calls_1m': calls_1m,
            'calls_5m': calls_5m,
            'calls_30m': calls_30m,
            'calls_1h': calls_1h,
            
            # Success rates by time window
            'success_rate_1m': round(success_1m / calls_1m * 100, 1) if calls_1m > 0 else 0,
            'success_rate_5m': round(success_5m / calls_5m * 100, 1) if calls_5m > 0 else 0,
            
            # Average durations by time window
            'avg_duration_1m': round(avg_1m, 3),
            'avg_duration_5m': round(avg_5m, 3),
            'avg_duration_30m': round(avg_30m, 3),
            'avg_duration_1h': round(avg_1h, 3),
            
            # Rate calculations
            'rate_per_minute_1m': round(calls_1m, 2),
            'rate_per_minute_5m': round(calls_5m / 5, 2),
            'rate_per_minute_30m': round(calls_30m / 30, 2),
            'rate_per_minute_1h': round(calls_1h / 60, 2),
            
            # Error information
            'consecutive_failures': stats.consecutive_failures,
            'last_error': stats.last_error,
            'last_error_time': datetime.fromtimestamp(stats.last_error_time).isoformat() if stats.last_error_time else None
        }
    
    def get_global_stats(self) -> Dict:
        """Get global API tracking statistics"""
        current_time = time.time()
        runtime = current_time - self.start_time
        
        with self.lock:
            total_apis = len(self.stats)
            total_success = sum(stats.successful_calls for stats in self.stats.values())
            total_failures = sum(stats.failed_calls for stats in self.stats.values())
            
            # Calculate global rates
            calls_1m = sum(len(stats.calls_1m) for stats in self.stats.values())
            calls_5m = sum(len(stats.calls_5m) for stats in self.stats.values())
        
        return {
            'runtime_seconds': round(runtime, 1),
            'runtime_hours': round(runtime / 3600, 2),
            'total_api_calls': self.total_api_calls,
            'total_apis_used': total_apis,
            'total_successful_calls': total_success,
            'total_failed_calls': total_failures,
            'global_success_rate': round(total_success / self.total_api_calls * 100, 2) if self.total_api_calls > 0 else 0,
            'calls_per_second': round(self.total_api_calls / runtime, 2) if runtime > 0 else 0,
            'current_rate_1m': calls_1m,
            'current_rate_5m': round(calls_5m / 5, 2),
            'current_cycle_id': self.current_cycle_id
        }
    
    def get_api_health_report(self) -> Dict:
        """Generate a health report for all APIs"""
        current_time = time.time()
        report = {
            'healthy_apis': [],
            'degraded_apis': [],
            'failing_apis': [],
            'recommendations': []
        }
        
        with self.lock:
            for api_name, stats in self.stats.items():
                if stats.total_calls == 0:
                    continue
                
                # Calculate health metrics
                success_rate = (stats.successful_calls / stats.total_calls) * 100
                avg_duration = stats.total_duration / stats.total_calls
                calls_1m = len(stats.calls_1m)
                
                api_info = {
                    'name': api_name,
                    'success_rate': round(success_rate, 2),
                    'avg_duration': round(avg_duration, 3),
                    'calls_1m': calls_1m,
                    'consecutive_failures': stats.consecutive_failures
                }
                
                # Categorize API health
                if stats.consecutive_failures >= 5:
                    report['failing_apis'].append(api_info)
                elif success_rate < 80 or avg_duration > self.slow_call_threshold:
                    report['degraded_apis'].append(api_info)
                else:
                    report['healthy_apis'].append(api_info)
        
        # Generate recommendations
        if report['failing_apis']:
            report['recommendations'].append(
                f"⚠️ {len(report['failing_apis'])} APIs are failing - check connectivity and rate limits"
            )
        
        if report['degraded_apis']:
            report['recommendations'].append(
                f"🐌 {len(report['degraded_apis'])} APIs are degraded - monitor performance"
            )
        
        return report
    
    def reset_stats(self, api_name: Optional[str] = None):
        """
        Reset statistics for specific API or all APIs
        
        Args:
            api_name: Specific API name, or None to reset all
        """
        with self.lock:
            if api_name:
                if api_name in self.stats:
                    del self.stats[api_name]
                    self.logger.info(f"🔄 Reset stats for API: {api_name}")
            else:
                self.stats.clear()
                self.total_api_calls = 0
                self.start_time = time.time()
                self.logger.info("🔄 Reset all API statistics")
    
    def end_cycle(self):
        """End the current tracking cycle"""
        with self.lock:
            old_cycle_id = self.current_cycle_id
            self.current_cycle_id = None
        
        if old_cycle_id:
            self.logger.debug(f"🏁 Ended API tracking for cycle {old_cycle_id}")
    
    def get_top_apis(self, limit: int = 5, sort_by: str = 'calls') -> List[Tuple[str, Dict]]:
        """
        Get top APIs by specified metric
        
        Args:
            limit: Number of top APIs to return
            sort_by: Metric to sort by ('calls', 'duration', 'failures')
            
        Returns:
            List of (api_name, stats) tuples
        """
        current_time = time.time()
        
        with self.lock:
            api_list = []
            for api_name, stats in self.stats.items():
                formatted_stats = self._format_api_stats(api_name, stats, current_time)
                api_list.append((api_name, formatted_stats))
        
        # Sort by specified metric
        if sort_by == 'calls':
            api_list.sort(key=lambda x: x[1]['total_calls'], reverse=True)
        elif sort_by == 'duration':
            api_list.sort(key=lambda x: x[1]['total_duration_seconds'], reverse=True)
        elif sort_by == 'failures':
            api_list.sort(key=lambda x: x[1]['failed_calls'], reverse=True)
        
        return api_list[:limit]