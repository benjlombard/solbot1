"""
Cycle Logger
Specialized logging and monitoring for synchronization cycles with detailed metrics and reporting.
"""
import time
import logging
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import defaultdict

from ..models.token_data import CycleStats


@dataclass
class CycleMetrics:
    """Detailed metrics for a single cycle"""
    cycle_id: int
    cycle_number: int
    start_time: float
    end_time: Optional[float] = None
    
    # Operation counters
    new_tokens: int = 0
    updated_tokens: int = 0
    historized_tokens: int = 0
    creation_timestamps: int = 0
    dead_tokens_marked: int = 0
    pumpfun_updated: int = 0
    
    # API call tracking
    api_calls: Dict[str, int] = field(default_factory=dict)
    api_durations: Dict[str, List[float]] = field(default_factory=lambda: defaultdict(list))
    
    # Error tracking
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    # Performance metrics
    tokens_per_second: float = 0.0
    api_calls_per_minute: float = 0.0
    
    @property
    def duration(self) -> float:
        """Calculate cycle duration in seconds"""
        if self.end_time is None:
            return time.time() - self.start_time
        return self.end_time - self.start_time
    
    @property
    def total_operations(self) -> int:
        """Total number of operations performed"""
        return (
            self.new_tokens + self.updated_tokens + self.historized_tokens +
            self.creation_timestamps + self.dead_tokens_marked + self.pumpfun_updated
        )
    
    @property
    def total_api_calls(self) -> int:
        """Total number of API calls made"""
        return sum(self.api_calls.values())
    
    def calculate_performance_metrics(self):
        """Calculate performance metrics"""
        if self.duration > 0:
            self.tokens_per_second = (self.new_tokens + self.updated_tokens) / self.duration
            self.api_calls_per_minute = (self.total_api_calls / self.duration) * 60
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization"""
        return {
            'cycle_id': self.cycle_id,
            'cycle_number': self.cycle_number,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'duration': self.duration,
            'start_datetime': datetime.fromtimestamp(self.start_time).isoformat(),
            'end_datetime': datetime.fromtimestamp(self.end_time).isoformat() if self.end_time else None,
            'operations': {
                'new_tokens': self.new_tokens,
                'updated_tokens': self.updated_tokens,
                'historized_tokens': self.historized_tokens,
                'creation_timestamps': self.creation_timestamps,
                'dead_tokens_marked': self.dead_tokens_marked,
                'pumpfun_updated': self.pumpfun_updated,
                'total_operations': self.total_operations
            },
            'api_metrics': {
                'total_calls': self.total_api_calls,
                'calls_by_api': self.api_calls,
                'calls_per_minute': self.api_calls_per_minute
            },
            'performance': {
                'tokens_per_second': self.tokens_per_second,
                'duration_seconds': self.duration
            },
            'issues': {
                'error_count': len(self.errors),
                'warning_count': len(self.warnings),
                'errors': self.errors,
                'warnings': self.warnings
            }
        }


class CycleLogger:
    """
    Specialized logger for synchronization cycles with comprehensive metrics tracking
    """
    
    def __init__(self, logger: logging.Logger, max_history: int = 100):
        self.logger = logger
        self.max_history = max_history
        
        # Current cycle
        self.current_cycle: Optional[CycleMetrics] = None
        self.cycle_count = 0
        
        # Cycle history
        self.cycle_history: List[CycleMetrics] = []
        
        # Cumulative statistics
        self.cumulative_stats = {
            'total_cycles': 0,
            'total_duration': 0.0,
            'total_new_tokens': 0,
            'total_updated_tokens': 0,
            'total_historized_tokens': 0,
            'total_api_calls': {},
            'start_time': None,
            'total_errors': 0,
            'total_warnings': 0
        }
        
        # Performance tracking
        self.performance_trends = {
            'avg_cycle_duration': [],
            'avg_tokens_per_second': [],
            'avg_api_calls_per_minute': []
        }
        
    def start_cycle(self, cycle_id: int):
        """Start a new synchronization cycle"""
        self.cycle_count += 1
        
        self.current_cycle = CycleMetrics(
            cycle_id=cycle_id,
            cycle_number=self.cycle_count,
            start_time=time.time()
        )
        
        if self.cumulative_stats['start_time'] is None:
            self.cumulative_stats['start_time'] = self.current_cycle.start_time
        
        # Log cycle start
        self.logger.info(f"🔄 CYCLE {self.cycle_count} STARTED - ID: {cycle_id}")
        self.logger.debug(f"   Start time: {datetime.fromtimestamp(self.current_cycle.start_time).strftime('%H:%M:%S')}")
    
    def end_cycle(self):
        """End the current synchronization cycle and generate reports"""
        if not self.current_cycle:
            self.logger.warning("No active cycle to end")
            return
        
        # Finalize cycle
        self.current_cycle.end_time = time.time()
        self.current_cycle.calculate_performance_metrics()
        
        # Update cumulative statistics
        self._update_cumulative_stats()
        
        # Add to history
        self.cycle_history.append(self.current_cycle)
        
        # Trim history if needed
        if len(self.cycle_history) > self.max_history:
            self.cycle_history = self.cycle_history[-self.max_history:]
        
        # Update performance trends
        self._update_performance_trends()
        
        # Generate and log reports
        self._log_cycle_summary()
        self._log_cumulative_summary()
        
        # Reset current cycle
        self.current_cycle = None
    
    def record_operation(self, operation: str, count: int = 1):
        """Record an operation in the current cycle"""
        if not self.current_cycle:
            self.logger.warning(f"No active cycle to record operation: {operation}")
            return
        
        if operation == 'new_tokens':
            self.current_cycle.new_tokens += count
        elif operation == 'updated_tokens':
            self.current_cycle.updated_tokens += count
        elif operation == 'historized_tokens':
            self.current_cycle.historized_tokens += count
        elif operation == 'creation_timestamps':
            self.current_cycle.creation_timestamps += count
        elif operation == 'dead_tokens_marked':
            self.current_cycle.dead_tokens_marked += count
        elif operation == 'pumpfun_updated':
            self.current_cycle.pumpfun_updated += count
        else:
            self.logger.debug(f"Unknown operation type: {operation}")
    
    def record_api_call(self, api_name: str, count: int = 1, duration: Optional[float] = None):
        """Record API calls in the current cycle"""
        if not self.current_cycle:
            return
        
        if api_name not in self.current_cycle.api_calls:
            self.current_cycle.api_calls[api_name] = 0
        
        self.current_cycle.api_calls[api_name] += count
        
        if duration is not None:
            self.current_cycle.api_durations[api_name].append(duration)
    
    def record_error(self, error_msg: str):
        """Record an error in the current cycle"""
        if not self.current_cycle:
            return
        
        self.current_cycle.errors.append(error_msg)
        self.cumulative_stats['total_errors'] += 1
    
    def record_warning(self, warning_msg: str):
        """Record a warning in the current cycle"""
        if not self.current_cycle:
            return
        
        self.current_cycle.warnings.append(warning_msg)
        self.cumulative_stats['total_warnings'] += 1
    
    def _update_cumulative_stats(self):
        """Update cumulative statistics"""
        cycle = self.current_cycle
        cumul = self.cumulative_stats
        
        cumul['total_cycles'] += 1
        cumul['total_duration'] += cycle.duration
        cumul['total_new_tokens'] += cycle.new_tokens
        cumul['total_updated_tokens'] += cycle.updated_tokens
        cumul['total_historized_tokens'] += cycle.historized_tokens
        
        # Update API call counts
        for api_name, count in cycle.api_calls.items():
            if api_name not in cumul['total_api_calls']:
                cumul['total_api_calls'][api_name] = 0
            cumul['total_api_calls'][api_name] += count
    
    def _update_performance_trends(self):
        """Update performance trend tracking"""
        cycle = self.current_cycle
        
        # Keep last 20 cycles for trend analysis
        max_trend_history = 20
        
        self.performance_trends['avg_cycle_duration'].append(cycle.duration)
        self.performance_trends['avg_tokens_per_second'].append(cycle.tokens_per_second)
        self.performance_trends['avg_api_calls_per_minute'].append(cycle.api_calls_per_minute)
        
        # Trim trend history
        for key in self.performance_trends:
            if len(self.performance_trends[key]) > max_trend_history:
                self.performance_trends[key] = self.performance_trends[key][-max_trend_history:]
    
    def _log_cycle_summary(self):
        """Log detailed cycle summary"""
        cycle = self.current_cycle
        
        self.logger.info("=" * 80)
        self.logger.info(f"📊 CYCLE {cycle.cycle_number} SUMMARY - ID: {cycle.cycle_id}")
        self.logger.info(f"⏰ Start: {datetime.fromtimestamp(cycle.start_time).strftime('%H:%M:%S')}")
        self.logger.info(f"⏰ End: {datetime.fromtimestamp(cycle.end_time).strftime('%H:%M:%S')}")
        self.logger.info(f"⏱️ Duration: {cycle.duration:.1f}s")
        self.logger.info("-" * 40)
        
        # Operations summary
        self.logger.info("🔢 OPERATIONS:")
        self.logger.info(f"  ➕ New tokens: {cycle.new_tokens}")
        self.logger.info(f"  🔄 Updated tokens: {cycle.updated_tokens}")
        self.logger.info(f"  📈 Historized: {cycle.historized_tokens}")
        
        if cycle.creation_timestamps > 0:
            self.logger.info(f"  ⏰ Creation timestamps: {cycle.creation_timestamps}")
        if cycle.dead_tokens_marked > 0:
            self.logger.info(f"  💀 Dead tokens marked: {cycle.dead_tokens_marked}")
        if cycle.pumpfun_updated > 0:
            self.logger.info(f"  🚀 Pump.fun updated: {cycle.pumpfun_updated}")
        
        self.logger.info(f"  📊 Total operations: {cycle.total_operations}")
        
        # API calls summary
        if cycle.api_calls:
            self.logger.info("🌐 API CALLS:")
            self.logger.info(f"  📡 Total calls: {cycle.total_api_calls}")
            self.logger.info(f"  📈 Rate: {cycle.api_calls_per_minute:.1f} calls/min")
            
            # Group API calls by service
            api_groups = self._group_api_calls(cycle.api_calls)
            for service, calls in api_groups.items():
                self.logger.info(f"  🔸 {service}: {calls} calls")
        
        # Performance metrics
        self.logger.info("⚡ PERFORMANCE:")
        self.logger.info(f"  🏃 Tokens/second: {cycle.tokens_per_second:.2f}")
        if cycle.duration > 0:
            efficiency = (cycle.total_operations / cycle.duration) * 100
            self.logger.info(f"  📊 Efficiency: {efficiency:.1f} ops/min")
        
        # Issues
        if cycle.errors or cycle.warnings:
            self.logger.info("⚠️ ISSUES:")
            if cycle.errors:
                self.logger.warning(f"  ❌ Errors: {len(cycle.errors)}")
                for error in cycle.errors[:3]:  # Show max 3 errors
                    self.logger.warning(f"    • {error}")
                if len(cycle.errors) > 3:
                    self.logger.warning(f"    ... and {len(cycle.errors) - 3} more errors")
            
            if cycle.warnings:
                self.logger.info(f"  ⚠️ Warnings: {len(cycle.warnings)}")
    
    def _log_cumulative_summary(self):
        """Log cumulative statistics summary"""
        cumul = self.cumulative_stats
        
        if cumul['total_cycles'] == 0:
            return
        
        # Calculate averages and rates
        avg_duration = cumul['total_duration'] / cumul['total_cycles']
        runtime = time.time() - cumul['start_time']
        
        self.logger.info("-" * 40)
        self.logger.info("📈 CUMULATIVE TOTALS:")
        self.logger.info(f"  🔄 Total cycles: {cumul['total_cycles']}")
        self.logger.info(f"  ⏱️ Average cycle time: {avg_duration:.1f}s")
        self.logger.info(f"  🕐 Total runtime: {runtime/3600:.1f}h")
        self.logger.info(f"  ➕ Total new tokens: {cumul['total_new_tokens']}")
        self.logger.info(f"  🔄 Total updated: {cumul['total_updated_tokens']}")
        self.logger.info(f"  📈 Total historized: {cumul['total_historized_tokens']}")
        
        # API statistics
        if cumul['total_api_calls']:
            total_api = sum(cumul['total_api_calls'].values())
            avg_api_per_cycle = total_api / cumul['total_cycles']
            self.logger.info(f"  📡 Total API calls: {total_api} (avg {avg_api_per_cycle:.1f}/cycle)")
            
            # Top 3 APIs
            top_apis = sorted(cumul['total_api_calls'].items(), key=lambda x: x[1], reverse=True)[:3]
            for api_name, count in top_apis:
                self.logger.info(f"    🔸 {api_name}: {count} calls")
        
        # Error summary
        if cumul['total_errors'] > 0 or cumul['total_warnings'] > 0:
            self.logger.info(f"  ⚠️ Total errors: {cumul['total_errors']}")
            self.logger.info(f"  ⚠️ Total warnings: {cumul['total_warnings']}")
        
        self.logger.info("=" * 80)
    
    def _group_api_calls(self, api_calls: Dict[str, int]) -> Dict[str, int]:
        """Group API calls by service"""
        groups = defaultdict(int)
        
        for api_name, count in api_calls.items():
            # Extract service name from API name
            if 'dexscreener' in api_name.lower():
                groups['DexScreener'] += count
            elif 'pumpfun' in api_name.lower():
                groups['Pump.fun'] += count
            elif 'rugcheck' in api_name.lower():
                groups['RugCheck'] += count
            elif 'solanatracker' in api_name.lower():
                groups['SolanaTracker'] += count
            else:
                groups['Other'] += count
        
        return dict(groups)
    
    def get_cycle_stats_for_db(self) -> Optional[Dict]:
        """Get current cycle statistics for database storage"""
        if not self.current_cycle or self.current_cycle.end_time is None:
            return None
        
        return self.current_cycle.to_dict()
    
    def get_performance_summary(self, cycles: int = 10) -> Dict:
        """Get performance summary for the last N cycles"""
        if not self.cycle_history:
            return {}
        
        recent_cycles = self.cycle_history[-cycles:] if len(self.cycle_history) >= cycles else self.cycle_history
        
        if not recent_cycles:
            return {}
        
        # Calculate averages
        avg_duration = sum(c.duration for c in recent_cycles) / len(recent_cycles)
        avg_tokens_per_sec = sum(c.tokens_per_second for c in recent_cycles) / len(recent_cycles)
        avg_api_calls = sum(c.total_api_calls for c in recent_cycles) / len(recent_cycles)
        
        # Calculate trends
        durations = [c.duration for c in recent_cycles]
        duration_trend = "improving" if len(durations) >= 2 and durations[-1] < durations[0] else "stable"
        
        return {
            'cycles_analyzed': len(recent_cycles),
            'avg_duration_seconds': round(avg_duration, 2),
            'avg_tokens_per_second': round(avg_tokens_per_sec, 2),
            'avg_api_calls_per_cycle': round(avg_api_calls, 1),
            'duration_trend': duration_trend,
            'last_cycle_duration': recent_cycles[-1].duration,
            'best_cycle_duration': min(c.duration for c in recent_cycles),
            'worst_cycle_duration': max(c.duration for c in recent_cycles)
        }
    
    def get_error_analysis(self, cycles: int = 20) -> Dict:
        """Analyze errors from recent cycles"""
        if not self.cycle_history:
            return {}
        
        recent_cycles = self.cycle_history[-cycles:] if len(self.cycle_history) >= cycles else self.cycle_history
        
        # Collect all errors
        all_errors = []
        all_warnings = []
        
        for cycle in recent_cycles:
            all_errors.extend(cycle.errors)
            all_warnings.extend(cycle.warnings)
        
        # Count error types
        error_types = defaultdict(int)
        for error in all_errors:
            # Extract error type (first part before colon or first few words)
            error_type = error.split(':')[0] if ':' in error else ' '.join(error.split()[:3])
            error_types[error_type] += 1
        
        return {
            'cycles_analyzed': len(recent_cycles),
            'total_errors': len(all_errors),
            'total_warnings': len(all_warnings),
            'error_rate': len(all_errors) / len(recent_cycles) if recent_cycles else 0,
            'warning_rate': len(all_warnings) / len(recent_cycles) if recent_cycles else 0,
            'common_error_types': dict(sorted(error_types.items(), key=lambda x: x[1], reverse=True)[:5]),
            'cycles_with_errors': len([c for c in recent_cycles if c.errors]),
            'cycles_with_warnings': len([c for c in recent_cycles if c.warnings])
        }
    
    def export_cycle_history(self, filename: Optional[str] = None) -> str:
        """Export cycle history to JSON file"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"cycle_history_{timestamp}.json"
        
        export_data = {
            'export_timestamp': datetime.now().isoformat(),
            'total_cycles': len(self.cycle_history),
            'cumulative_stats': self.cumulative_stats,
            'cycle_history': [cycle.to_dict() for cycle in self.cycle_history],
            'performance_summary': self.get_performance_summary(),
            'error_analysis': self.get_error_analysis()
        }
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"📄 Cycle history exported to {filename}")
            return filename
            
        except Exception as e:
            self.logger.error(f"❌ Failed to export cycle history: {e}")
            return ""
    
    def reset_statistics(self):
        """Reset all statistics and history"""
        self.current_cycle = None
        self.cycle_count = 0
        self.cycle_history.clear()
        
        self.cumulative_stats = {
            'total_cycles': 0,
            'total_duration': 0.0,
            'total_new_tokens': 0,
            'total_updated_tokens': 0,
            'total_historized_tokens': 0,
            'total_api_calls': {},
            'start_time': None,
            'total_errors': 0,
            'total_warnings': 0
        }
        
        self.performance_trends = {
            'avg_cycle_duration': [],
            'avg_tokens_per_second': [],
            'avg_api_calls_per_minute': []
        }
        
        self.logger.info("🔄 Cycle logger statistics reset")