"""
API Statistics Models
Data structures for API performance monitoring and statistics tracking.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from collections import deque
from datetime import datetime, timedelta
from enum import Enum
import time
import json


class ApiStatus(Enum):
    """API health status enumeration"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILING = "failing"
    UNKNOWN = "unknown"


class TimeWindow(Enum):
    """Time window enumeration for metrics"""
    ONE_MINUTE = 60
    FIVE_MINUTES = 300
    THIRTY_MINUTES = 1800
    ONE_HOUR = 3600
    SIX_HOURS = 21600
    TWENTY_FOUR_HOURS = 86400


@dataclass
class ApiCallRecord:
    """Individual API call record with detailed information"""
    timestamp: float
    duration: float  # in seconds
    success: bool
    http_status: Optional[int] = None
    error_message: Optional[str] = None
    request_size: Optional[int] = None  # bytes
    response_size: Optional[int] = None  # bytes
    endpoint: Optional[str] = None
    retry_count: int = 0
    
    @property
    def duration_ms(self) -> int:
        """Duration in milliseconds"""
        return int(self.duration * 1000)
    
    @property
    def datetime(self) -> datetime:
        """Convert timestamp to datetime"""
        return datetime.fromtimestamp(self.timestamp)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization"""
        return {
            'timestamp': self.timestamp,
            'datetime': self.datetime.isoformat(),
            'duration_ms': self.duration_ms,
            'success': self.success,
            'http_status': self.http_status,
            'error_message': self.error_message,
            'request_size': self.request_size,
            'response_size': self.response_size,
            'endpoint': self.endpoint,
            'retry_count': self.retry_count
        }


@dataclass
class TimeWindowStats:
    """Statistics for a specific time window"""
    window_size: int  # seconds
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_duration: float = 0.0
    min_duration: float = float('inf')
    max_duration: float = 0.0
    total_retries: int = 0
    
    # Response sizes
    total_request_size: int = 0
    total_response_size: int = 0
    
    # HTTP status codes
    status_codes: Dict[int, int] = field(default_factory=dict)
    
    # Error tracking
    error_types: Dict[str, int] = field(default_factory=dict)
    
    @property
    def success_rate(self) -> float:
        """Success rate as percentage"""
        if self.total_calls == 0:
            return 0.0
        return (self.successful_calls / self.total_calls) * 100
    
    @property
    def failure_rate(self) -> float:
        """Failure rate as percentage"""
        return 100.0 - self.success_rate
    
    @property
    def avg_duration(self) -> float:
        """Average duration in seconds"""
        if self.total_calls == 0:
            return 0.0
        return self.total_duration / self.total_calls
    
    @property
    def avg_duration_ms(self) -> float:
        """Average duration in milliseconds"""
        return self.avg_duration * 1000
    
    @property
    def calls_per_minute(self) -> float:
        """Calls per minute rate"""
        if self.window_size == 0:
            return 0.0
        return (self.total_calls / self.window_size) * 60
    
    @property
    def avg_request_size(self) -> float:
        """Average request size in bytes"""
        if self.total_calls == 0:
            return 0.0
        return self.total_request_size / self.total_calls
    
    @property
    def avg_response_size(self) -> float:
        """Average response size in bytes"""
        if self.total_calls == 0:
            return 0.0
        return self.total_response_size / self.total_calls
    
    def add_call(self, record: ApiCallRecord):
        """Add a call record to the statistics"""
        self.total_calls += 1
        self.total_duration += record.duration
        self.total_retries += record.retry_count
        
        if record.success:
            self.successful_calls += 1
        else:
            self.failed_calls += 1
            
            # Track error types
            if record.error_message:
                error_type = record.error_message.split(':')[0]  # Get error type
                self.error_types[error_type] = self.error_types.get(error_type, 0) + 1
        
        # Update duration bounds
        self.min_duration = min(self.min_duration, record.duration)
        self.max_duration = max(self.max_duration, record.duration)
        
        # Track HTTP status codes
        if record.http_status:
            self.status_codes[record.http_status] = self.status_codes.get(record.http_status, 0) + 1
        
        # Track sizes
        if record.request_size:
            self.total_request_size += record.request_size
        if record.response_size:
            self.total_response_size += record.response_size
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization"""
        return {
            'window_size_seconds': self.window_size,
            'total_calls': self.total_calls,
            'successful_calls': self.successful_calls,
            'failed_calls': self.failed_calls,
            'success_rate': round(self.success_rate, 2),
            'failure_rate': round(self.failure_rate, 2),
            'avg_duration_ms': round(self.avg_duration_ms, 2),
            'min_duration_ms': round(self.min_duration * 1000, 2) if self.min_duration != float('inf') else 0,
            'max_duration_ms': round(self.max_duration * 1000, 2),
            'calls_per_minute': round(self.calls_per_minute, 2),
            'total_retries': self.total_retries,
            'avg_request_size_bytes': round(self.avg_request_size, 0),
            'avg_response_size_bytes': round(self.avg_response_size, 0),
            'status_codes': self.status_codes,
            'error_types': self.error_types
        }


@dataclass
class ApiEndpointStats:
    """Comprehensive statistics for a single API endpoint"""
    api_name: str
    endpoint: str
    first_call_time: Optional[float] = None
    last_call_time: Optional[float] = None
    
    # Raw call records (limited history)
    call_records: deque = field(default_factory=lambda: deque(maxlen=1000))
    
    # Time-windowed statistics
    stats_1m: TimeWindowStats = field(default_factory=lambda: TimeWindowStats(60))
    stats_5m: TimeWindowStats = field(default_factory=lambda: TimeWindowStats(300))
    stats_30m: TimeWindowStats = field(default_factory=lambda: TimeWindowStats(1800))
    stats_1h: TimeWindowStats = field(default_factory=lambda: TimeWindowStats(3600))
    stats_6h: TimeWindowStats = field(default_factory=lambda: TimeWindowStats(21600))
    stats_24h: TimeWindowStats = field(default_factory=lambda: TimeWindowStats(86400))
    
    # Overall lifetime statistics
    lifetime_stats: TimeWindowStats = field(default_factory=lambda: TimeWindowStats(0))
    
    # Health tracking
    consecutive_failures: int = 0
    last_failure_time: Optional[float] = None
    
    def add_call(self, record: ApiCallRecord):
        """Add a new API call record"""
        current_time = record.timestamp
        
        # Update timing
        if self.first_call_time is None:
            self.first_call_time = current_time
        self.last_call_time = current_time
        
        # Add to raw records
        self.call_records.append(record)
        
        # Update failure tracking
        if record.success:
            self.consecutive_failures = 0
        else:
            self.consecutive_failures += 1
            self.last_failure_time = current_time
        
        # Clean old records and update time-windowed stats
        self._clean_and_update_stats(current_time)
        
        # Update lifetime stats
        self.lifetime_stats.add_call(record)
    
    def _clean_and_update_stats(self, current_time: float):
        """Clean old records and update time-windowed statistics"""
        # Reset all time window stats
        self.stats_1m = TimeWindowStats(60)
        self.stats_5m = TimeWindowStats(300)
        self.stats_30m = TimeWindowStats(1800)
        self.stats_1h = TimeWindowStats(3600)
        self.stats_6h = TimeWindowStats(21600)
        self.stats_24h = TimeWindowStats(86400)
        
        # Recalculate stats from valid records
        for record in self.call_records:
            time_diff = current_time - record.timestamp
            
            if time_diff <= 60:
                self.stats_1m.add_call(record)
            if time_diff <= 300:
                self.stats_5m.add_call(record)
            if time_diff <= 1800:
                self.stats_30m.add_call(record)
            if time_diff <= 3600:
                self.stats_1h.add_call(record)
            if time_diff <= 21600:
                self.stats_6h.add_call(record)
            if time_diff <= 86400:
                self.stats_24h.add_call(record)
    
    def get_status(self) -> ApiStatus:
        """Determine current API health status"""
        if self.lifetime_stats.total_calls == 0:
            return ApiStatus.UNKNOWN
        
        # Check for consecutive failures
        if self.consecutive_failures >= 5:
            return ApiStatus.FAILING
        
        # Check recent performance (last 5 minutes)
        if self.stats_5m.total_calls > 0:
            success_rate = self.stats_5m.success_rate
            avg_duration = self.stats_5m.avg_duration
            
            if success_rate < 50 or avg_duration > 10.0:
                return ApiStatus.FAILING
            elif success_rate < 80 or avg_duration > 5.0:
                return ApiStatus.DEGRADED
        
        return ApiStatus.HEALTHY
    
    def get_recent_errors(self, limit: int = 10) -> List[ApiCallRecord]:
        """Get recent error records"""
        errors = [record for record in self.call_records if not record.success]
        return list(errors)[-limit:] if errors else []
    
    def get_slowest_calls(self, limit: int = 10) -> List[ApiCallRecord]:
        """Get slowest API calls"""
        sorted_calls = sorted(
            self.call_records, 
            key=lambda r: r.duration, 
            reverse=True
        )
        return sorted_calls[:limit]
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization"""
        return {
            'api_name': self.api_name,
            'endpoint': self.endpoint,
            'first_call_time': self.first_call_time,
            'last_call_time': self.last_call_time,
            'first_call_datetime': datetime.fromtimestamp(self.first_call_time).isoformat() if self.first_call_time else None,
            'last_call_datetime': datetime.fromtimestamp(self.last_call_time).isoformat() if self.last_call_time else None,
            'status': self.get_status().value,
            'consecutive_failures': self.consecutive_failures,
            'last_failure_time': self.last_failure_time,
            'stats': {
                '1m': self.stats_1m.to_dict(),
                '5m': self.stats_5m.to_dict(),
                '30m': self.stats_30m.to_dict(),
                '1h': self.stats_1h.to_dict(),
                '6h': self.stats_6h.to_dict(),
                '24h': self.stats_24h.to_dict(),
                'lifetime': self.lifetime_stats.to_dict()
            },
            'total_records': len(self.call_records)
        }


@dataclass
class ApiServiceStats:
    """Statistics for an entire API service (multiple endpoints)"""
    service_name: str
    endpoints: Dict[str, ApiEndpointStats] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    
    def add_call(self, endpoint: str, record: ApiCallRecord):
        """Add a call record to a specific endpoint"""
        if endpoint not in self.endpoints:
            self.endpoints[endpoint] = ApiEndpointStats(
                api_name=self.service_name,
                endpoint=endpoint
            )
        
        self.endpoints[endpoint].add_call(record)
    
    def get_service_status(self) -> ApiStatus:
        """Get overall service status"""
        if not self.endpoints:
            return ApiStatus.UNKNOWN
        
        statuses = [endpoint.get_status() for endpoint in self.endpoints.values()]
        
        # If any endpoint is failing, service is failing
        if ApiStatus.FAILING in statuses:
            return ApiStatus.FAILING
        
        # If any endpoint is degraded, service is degraded
        if ApiStatus.DEGRADED in statuses:
            return ApiStatus.DEGRADED
        
        # All endpoints healthy
        return ApiStatus.HEALTHY
    
    def get_aggregated_stats(self, time_window: str = '5m') -> TimeWindowStats:
        """Get aggregated statistics across all endpoints"""
        aggregated = TimeWindowStats(
            window_size=getattr(self.endpoints[list(self.endpoints.keys())[0]], f'stats_{time_window}').window_size
            if self.endpoints else 0
        )
        
        for endpoint in self.endpoints.values():
            endpoint_stats = getattr(endpoint, f'stats_{time_window}')
            
            aggregated.total_calls += endpoint_stats.total_calls
            aggregated.successful_calls += endpoint_stats.successful_calls
            aggregated.failed_calls += endpoint_stats.failed_calls
            aggregated.total_duration += endpoint_stats.total_duration
            aggregated.total_retries += endpoint_stats.total_retries
            aggregated.total_request_size += endpoint_stats.total_request_size
            aggregated.total_response_size += endpoint_stats.total_response_size
            
            # Update min/max durations
            if endpoint_stats.min_duration != float('inf'):
                aggregated.min_duration = min(aggregated.min_duration, endpoint_stats.min_duration)
            aggregated.max_duration = max(aggregated.max_duration, endpoint_stats.max_duration)
            
            # Merge status codes
            for status, count in endpoint_stats.status_codes.items():
                aggregated.status_codes[status] = aggregated.status_codes.get(status, 0) + count
            
            # Merge error types
            for error, count in endpoint_stats.error_types.items():
                aggregated.error_types[error] = aggregated.error_types.get(error, 0) + count
        
        return aggregated
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization"""
        return {
            'service_name': self.service_name,
            'created_at': self.created_at,
            'created_datetime': datetime.fromtimestamp(self.created_at).isoformat(),
            'status': self.get_service_status().value,
            'total_endpoints': len(self.endpoints),
            'endpoints': {name: endpoint.to_dict() for name, endpoint in self.endpoints.items()},
            'aggregated_stats': {
                '1m': self.get_aggregated_stats('1m').to_dict(),
                '5m': self.get_aggregated_stats('5m').to_dict(),
                '30m': self.get_aggregated_stats('30m').to_dict(),
                '1h': self.get_aggregated_stats('1h').to_dict(),
                '6h': self.get_aggregated_stats('6h').to_dict(),
                '24h': self.get_aggregated_stats('24h').to_dict(),
                'lifetime': self.get_aggregated_stats('lifetime').to_dict()
            }
        }


@dataclass
class ApiHealthReport:
    """Comprehensive API health report"""
    generated_at: float = field(default_factory=time.time)
    healthy_apis: List[str] = field(default_factory=list)
    degraded_apis: List[str] = field(default_factory=list)
    failing_apis: List[str] = field(default_factory=list)
    unknown_apis: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    total_apis: int = 0
    overall_health_score: float = 0.0
    
    def calculate_health_score(self):
        """Calculate overall health score (0-100)"""
        if self.total_apis == 0:
            self.overall_health_score = 0.0
            return
        
        healthy_weight = 1.0
        degraded_weight = 0.5
        failing_weight = 0.0
        unknown_weight = 0.25
        
        score = (
            len(self.healthy_apis) * healthy_weight +
            len(self.degraded_apis) * degraded_weight +
            len(self.failing_apis) * failing_weight +
            len(self.unknown_apis) * unknown_weight
        ) / self.total_apis * 100
        
        self.overall_health_score = round(score, 2)
    
    def add_recommendation(self, message: str):
        """Add a recommendation to the report"""
        if message not in self.recommendations:
            self.recommendations.append(message)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization"""
        return {
            'generated_at': self.generated_at,
            'generated_datetime': datetime.fromtimestamp(self.generated_at).isoformat(),
            'total_apis': self.total_apis,
            'overall_health_score': self.overall_health_score,
            'healthy_apis': self.healthy_apis,
            'degraded_apis': self.degraded_apis,
            'failing_apis': self.failing_apis,
            'unknown_apis': self.unknown_apis,
            'recommendations': self.recommendations,
            'summary': {
                'healthy_count': len(self.healthy_apis),
                'degraded_count': len(self.degraded_apis),
                'failing_count': len(self.failing_apis),
                'unknown_count': len(self.unknown_apis)
            }
        }