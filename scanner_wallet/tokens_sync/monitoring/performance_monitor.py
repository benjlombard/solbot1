"""
Performance Monitor
Comprehensive system performance monitoring for the token synchronization service.
"""
import time
import psutil
import threading
import logging
import json
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import deque, defaultdict
import gc
import sys
import tracemalloc

from ..database.connection import DatabaseConnection, db_retry


@dataclass
class SystemMetrics:
    """System performance metrics snapshot"""
    timestamp: float
    cpu_percent: float
    memory_percent: float
    memory_available_mb: float
    memory_used_mb: float
    disk_usage_percent: float
    disk_free_gb: float
    network_bytes_sent: int = 0
    network_bytes_recv: int = 0
    process_count: int = 0
    thread_count: int = 0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'timestamp': self.timestamp,
            'datetime': datetime.fromtimestamp(self.timestamp).isoformat(),
            'cpu_percent': self.cpu_percent,
            'memory_percent': self.memory_percent,
            'memory_available_mb': self.memory_available_mb,
            'memory_used_mb': self.memory_used_mb,
            'disk_usage_percent': self.disk_usage_percent,
            'disk_free_gb': self.disk_free_gb,
            'network_bytes_sent': self.network_bytes_sent,
            'network_bytes_recv': self.network_bytes_recv,
            'process_count': self.process_count,
            'thread_count': self.thread_count
        }


@dataclass
class ApplicationMetrics:
    """Application-specific performance metrics"""
    timestamp: float
    process_cpu_percent: float
    process_memory_mb: float
    process_memory_percent: float
    open_files: int
    threads: int
    gc_collections: Dict[int, int] = field(default_factory=dict)
    memory_allocations: int = 0
    memory_peak_mb: float = 0.0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'timestamp': self.timestamp,
            'datetime': datetime.fromtimestamp(self.timestamp).isoformat(),
            'process_cpu_percent': self.process_cpu_percent,
            'process_memory_mb': self.process_memory_mb,
            'process_memory_percent': self.process_memory_percent,
            'open_files': self.open_files,
            'threads': self.threads,
            'gc_collections': self.gc_collections,
            'memory_allocations': self.memory_allocations,
            'memory_peak_mb': self.memory_peak_mb
        }


@dataclass
class DatabaseMetrics:
    """Database performance metrics"""
    timestamp: float
    connection_count: int = 0
    query_duration_avg: float = 0.0
    query_duration_max: float = 0.0
    transactions_per_minute: float = 0.0
    database_size_mb: float = 0.0
    wal_size_mb: float = 0.0
    cache_hit_ratio: float = 0.0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'timestamp': self.timestamp,
            'datetime': datetime.fromtimestamp(self.timestamp).isoformat(),
            'connection_count': self.connection_count,
            'query_duration_avg': self.query_duration_avg,
            'query_duration_max': self.query_duration_max,
            'transactions_per_minute': self.transactions_per_minute,
            'database_size_mb': self.database_size_mb,
            'wal_size_mb': self.wal_size_mb,
            'cache_hit_ratio': self.cache_hit_ratio
        }


@dataclass
class PerformanceAlert:
    """Performance alert/warning"""
    timestamp: float
    level: str  # 'warning', 'critical'
    category: str  # 'cpu', 'memory', 'disk', 'database', 'application'
    message: str
    value: float
    threshold: float
    resolved: bool = False
    resolved_at: Optional[float] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'timestamp': self.timestamp,
            'datetime': datetime.fromtimestamp(self.timestamp).isoformat(),
            'level': self.level,
            'category': self.category,
            'message': self.message,
            'value': self.value,
            'threshold': self.threshold,
            'resolved': self.resolved,
            'resolved_at': self.resolved_at,
            'resolved_datetime': datetime.fromtimestamp(self.resolved_at).isoformat() if self.resolved_at else None
        }


class PerformanceMonitor:
    """
    Comprehensive performance monitoring system
    """
    
    def __init__(
        self,
        db_connection: Optional[DatabaseConnection] = None,
        logger: Optional[logging.Logger] = None,
        monitoring_interval: float = 30.0,
        history_size: int = 1000
    ):
        self.db_connection = db_connection
        self.logger = logger or logging.getLogger(__name__)
        self.monitoring_interval = monitoring_interval
        self.history_size = history_size
        
        # Monitoring state
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None
        
        # Metrics history
        self.system_metrics_history: deque = deque(maxlen=history_size)
        self.app_metrics_history: deque = deque(maxlen=history_size)
        self.db_metrics_history: deque = deque(maxlen=history_size)
        
        # Alert management
        self.active_alerts: List[PerformanceAlert] = []
        self.alert_history: deque = deque(maxlen=200)
        self.alert_callbacks: List[Callable] = []
        
        # Performance thresholds
        self.thresholds = {
            'cpu_warning': 70.0,
            'cpu_critical': 90.0,
            'memory_warning': 80.0,
            'memory_critical': 95.0,
            'disk_warning': 85.0,
            'disk_critical': 95.0,
            'process_memory_warning': 500.0,  # MB
            'process_memory_critical': 1000.0,  # MB
            'query_duration_warning': 5.0,  # seconds
            'query_duration_critical': 10.0,  # seconds
        }
        
        # Initialize process monitoring
        self.process = psutil.Process()
        self.initial_network_stats = psutil.net_io_counters()
        
        # Memory tracking
        self.memory_tracking_enabled = False
        self._enable_memory_tracking()
        
        self.logger.info("🎯 Performance Monitor initialized")
    
    def _enable_memory_tracking(self):
        """Enable detailed memory tracking"""
        try:
            tracemalloc.start()
            self.memory_tracking_enabled = True
            self.logger.debug("✅ Memory tracking enabled")
        except Exception as e:
            self.logger.warning(f"Could not enable memory tracking: {e}")
    
    def start_monitoring(self):
        """Start continuous performance monitoring"""
        if self.running:
            self.logger.warning("Performance monitoring already running")
            return
        
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self.monitor_thread.start()
        
        self.logger.info(f"🚀 Performance monitoring started (interval: {self.monitoring_interval}s)")
    
    def stop_monitoring(self):
        """Stop performance monitoring"""
        self.running = False
        
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=5.0)
        
        self.logger.info("🛑 Performance monitoring stopped")
    
    def _monitoring_loop(self):
        """Main monitoring loop"""
        while self.running:
            try:
                # Collect metrics
                system_metrics = self._collect_system_metrics()
                app_metrics = self._collect_application_metrics()
                db_metrics = self._collect_database_metrics()
                
                # Store metrics
                self.system_metrics_history.append(system_metrics)
                self.app_metrics_history.append(app_metrics)
                self.db_metrics_history.append(db_metrics)
                
                # Check for alerts
                self._check_alerts(system_metrics, app_metrics, db_metrics)
                
                # Store to database periodically
                if len(self.system_metrics_history) % 10 == 0:  # Every 10 collections
                    self._store_metrics_to_db()
                
                # Sleep until next collection
                time.sleep(self.monitoring_interval)
                
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                time.sleep(self.monitoring_interval)
    
    def _collect_system_metrics(self) -> SystemMetrics:
        """Collect system-wide performance metrics"""
        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # Memory usage
            memory = psutil.virtual_memory()
            
            # Disk usage
            disk_usage = psutil.disk_usage('/')
            
            # Network statistics
            net_io = psutil.net_io_counters()
            
            return SystemMetrics(
                timestamp=time.time(),
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                memory_available_mb=memory.available / (1024 * 1024),
                memory_used_mb=memory.used / (1024 * 1024),
                disk_usage_percent=disk_usage.percent,
                disk_free_gb=disk_usage.free / (1024 * 1024 * 1024),
                network_bytes_sent=net_io.bytes_sent - self.initial_network_stats.bytes_sent,
                network_bytes_recv=net_io.bytes_recv - self.initial_network_stats.bytes_recv,
                process_count=len(psutil.pids()),
                thread_count=threading.active_count()
            )
            
        except Exception as e:
            self.logger.error(f"Error collecting system metrics: {e}")
            return SystemMetrics(timestamp=time.time(), cpu_percent=0, memory_percent=0, 
                               memory_available_mb=0, memory_used_mb=0, disk_usage_percent=0, disk_free_gb=0)
    
    def _collect_application_metrics(self) -> ApplicationMetrics:
        """Collect application-specific metrics"""
        try:
            # Process CPU and memory
            process_cpu = self.process.cpu_percent()
            process_memory = self.process.memory_info()
            process_memory_percent = self.process.memory_percent()
            
            # Open files and threads
            try:
                open_files = len(self.process.open_files())
            except (psutil.AccessDenied, OSError):
                open_files = 0
            
            threads = self.process.num_threads()
            
            # Garbage collection stats
            gc_stats = {}
            for i in range(3):  # Python has 3 GC generations
                gc_stats[i] = gc.get_count()[i]
            
            # Memory tracking
            memory_allocations = 0
            memory_peak_mb = 0.0
            
            if self.memory_tracking_enabled:
                try:
                    current, peak = tracemalloc.get_traced_memory()
                    memory_allocations = current
                    memory_peak_mb = peak / (1024 * 1024)
                except Exception:
                    pass
            
            return ApplicationMetrics(
                timestamp=time.time(),
                process_cpu_percent=process_cpu,
                process_memory_mb=process_memory.rss / (1024 * 1024),
                process_memory_percent=process_memory_percent,
                open_files=open_files,
                threads=threads,
                gc_collections=gc_stats,
                memory_allocations=memory_allocations,
                memory_peak_mb=memory_peak_mb
            )
            
        except Exception as e:
            self.logger.error(f"Error collecting application metrics: {e}")
            return ApplicationMetrics(timestamp=time.time(), process_cpu_percent=0, 
                                   process_memory_mb=0, process_memory_percent=0, 
                                   open_files=0, threads=0)
    
    def _collect_database_metrics(self) -> DatabaseMetrics:
        """Collect database performance metrics"""
        if not self.db_connection:
            return DatabaseMetrics(timestamp=time.time())
        
        try:
            with self.db_connection.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # Database size
                cursor.execute("SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()")
                db_size = cursor.fetchone()[0] / (1024 * 1024)  # Convert to MB
                
                # WAL size
                try:
                    cursor.execute("PRAGMA wal_checkpoint(PASSIVE)")
                    cursor.execute("SELECT SUM(size) FROM pragma_wal_checkpoint()")
                    wal_result = cursor.fetchone()
                    wal_size = (wal_result[0] if wal_result and wal_result[0] else 0) / (1024 * 1024)
                except Exception:
                    wal_size = 0.0
                
                # Cache statistics
                cursor.execute("PRAGMA cache_size")
                cache_size = cursor.fetchone()[0]
                
                return DatabaseMetrics(
                    timestamp=time.time(),
                    database_size_mb=db_size,
                    wal_size_mb=wal_size,
                    cache_hit_ratio=95.0,  # Placeholder - would need query stats for real value
                )
                
        except Exception as e:
            self.logger.error(f"Error collecting database metrics: {e}")
            return DatabaseMetrics(timestamp=time.time())
    
    def _check_alerts(self, system: SystemMetrics, app: ApplicationMetrics, db: DatabaseMetrics):
        """Check for performance alerts"""
        current_time = time.time()
        
        # Check system alerts
        self._check_threshold_alert('cpu', 'CPU Usage', system.cpu_percent, 
                                  self.thresholds['cpu_warning'], self.thresholds['cpu_critical'], '%')
        
        self._check_threshold_alert('memory', 'Memory Usage', system.memory_percent,
                                  self.thresholds['memory_warning'], self.thresholds['memory_critical'], '%')
        
        self._check_threshold_alert('disk', 'Disk Usage', system.disk_usage_percent,
                                  self.thresholds['disk_warning'], self.thresholds['disk_critical'], '%')
        
        # Check application alerts
        self._check_threshold_alert('application', 'Process Memory', app.process_memory_mb,
                                  self.thresholds['process_memory_warning'], 
                                  self.thresholds['process_memory_critical'], 'MB')
        
        # Check for resolved alerts
        self._check_resolved_alerts(current_time)
    
    def _check_threshold_alert(self, category: str, name: str, value: float, 
                             warning_threshold: float, critical_threshold: float, unit: str):
        """Check if a metric exceeds thresholds"""
        current_time = time.time()
        
        # Check for existing alert
        existing_alert = None
        for alert in self.active_alerts:
            if alert.category == category and not alert.resolved:
                existing_alert = alert
                break
        
        if value >= critical_threshold:
            level = 'critical'
            threshold = critical_threshold
        elif value >= warning_threshold:
            level = 'warning'
            threshold = warning_threshold
        else:
            # Value is below thresholds
            if existing_alert:
                self._resolve_alert(existing_alert, current_time)
            return
        
        # Create new alert if none exists or severity changed
        if not existing_alert or existing_alert.level != level:
            if existing_alert:
                self._resolve_alert(existing_alert, current_time)
            
            alert = PerformanceAlert(
                timestamp=current_time,
                level=level,
                category=category,
                message=f"{name} is {level}: {value:.1f}{unit} (threshold: {threshold:.1f}{unit})",
                value=value,
                threshold=threshold
            )
            
            self.active_alerts.append(alert)
            self.alert_history.append(alert)
            
            # Log alert
            if level == 'critical':
                self.logger.critical(f"🚨 CRITICAL ALERT: {alert.message}")
            else:
                self.logger.warning(f"⚠️ WARNING: {alert.message}")
            
            # Trigger callbacks
            for callback in self.alert_callbacks:
                try:
                    callback(alert)
                except Exception as e:
                    self.logger.error(f"Error in alert callback: {e}")
    
    def _resolve_alert(self, alert: PerformanceAlert, current_time: float):
        """Resolve an active alert"""
        alert.resolved = True
        alert.resolved_at = current_time
        
        if alert in self.active_alerts:
            self.active_alerts.remove(alert)
        
        self.logger.info(f"✅ RESOLVED: {alert.message}")
    
    def _check_resolved_alerts(self, current_time: float):
        """Check if any alerts should be auto-resolved"""
        # Auto-resolve alerts older than 5 minutes if conditions improved
        cutoff_time = current_time - 300  # 5 minutes
        
        alerts_to_resolve = []
        for alert in self.active_alerts:
            if alert.timestamp < cutoff_time:
                # Check if current value is below threshold
                current_value = self._get_current_metric_value(alert.category)
                if current_value is not None and current_value < alert.threshold:
                    alerts_to_resolve.append(alert)
        
        for alert in alerts_to_resolve:
            self._resolve_alert(alert, current_time)
    
    def _get_current_metric_value(self, category: str) -> Optional[float]:
        """Get current value for a metric category"""
        if not self.system_metrics_history or not self.app_metrics_history:
            return None
        
        latest_system = self.system_metrics_history[-1]
        latest_app = self.app_metrics_history[-1]
        
        if category == 'cpu':
            return latest_system.cpu_percent
        elif category == 'memory':
            return latest_system.memory_percent
        elif category == 'disk':
            return latest_system.disk_usage_percent
        elif category == 'application':
            return latest_app.process_memory_mb
        
        return None
    
    @db_retry(max_retries=2, delay=0.5)
    def _store_metrics_to_db(self):
        """Store metrics to database"""
        if not self.db_connection or not self.system_metrics_history:
            return
        
        try:
            with self.db_connection.get_connection_context() as conn:
                cursor = conn.cursor()
                
                # Store latest metrics
                latest_system = self.system_metrics_history[-1]
                latest_app = self.app_metrics_history[-1]
                latest_db = self.db_metrics_history[-1] if self.db_metrics_history else None
                
                cursor.execute("""
                    INSERT INTO performance_metrics (
                        timestamp, 
                        cpu_percent, memory_percent, memory_used_mb,
                        disk_usage_percent, disk_free_gb,
                        process_cpu_percent, process_memory_mb,
                        threads, database_size_mb
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    int(latest_system.timestamp),
                    latest_system.cpu_percent,
                    latest_system.memory_percent,
                    latest_system.memory_used_mb,
                    latest_system.disk_usage_percent,
                    latest_system.disk_free_gb,
                    latest_app.process_cpu_percent,
                    latest_app.process_memory_mb,
                    latest_app.threads,
                    latest_db.database_size_mb if latest_db else 0
                ))
                
                conn.commit()
                
        except Exception as e:
            self.logger.debug(f"Failed to store metrics to database: {e}")
    
    def add_alert_callback(self, callback: Callable[[PerformanceAlert], None]):
        """Add callback function for alerts"""
        self.alert_callbacks.append(callback)
    
    def get_current_metrics(self) -> Dict:
        """Get current performance metrics"""
        if not self.system_metrics_history:
            return {}
        
        latest_system = self.system_metrics_history[-1]
        latest_app = self.app_metrics_history[-1] if self.app_metrics_history else None
        latest_db = self.db_metrics_history[-1] if self.db_metrics_history else None
        
        return {
            'system': latest_system.to_dict(),
            'application': latest_app.to_dict() if latest_app else {},
            'database': latest_db.to_dict() if latest_db else {},
            'alerts': {
                'active_count': len(self.active_alerts),
                'active_alerts': [alert.to_dict() for alert in self.active_alerts],
                'total_alerts_today': len([a for a in self.alert_history 
                                         if a.timestamp > time.time() - 86400])
            }
        }
    
    def get_performance_summary(self, hours: int = 24) -> Dict:
        """Get performance summary for the last N hours"""
        cutoff_time = time.time() - (hours * 3600)
        
        # Filter metrics
        recent_system = [m for m in self.system_metrics_history if m.timestamp > cutoff_time]
        recent_app = [m for m in self.app_metrics_history if m.timestamp > cutoff_time]
        
        if not recent_system:
            return {}
        
        # Calculate averages and peaks
        avg_cpu = sum(m.cpu_percent for m in recent_system) / len(recent_system)
        max_cpu = max(m.cpu_percent for m in recent_system)
        
        avg_memory = sum(m.memory_percent for m in recent_system) / len(recent_system)
        max_memory = max(m.memory_percent for m in recent_system)
        
        avg_process_memory = sum(m.process_memory_mb for m in recent_app) / len(recent_app) if recent_app else 0
        max_process_memory = max(m.process_memory_mb for m in recent_app) if recent_app else 0
        
        # Count alerts
        recent_alerts = [a for a in self.alert_history if a.timestamp > cutoff_time]
        critical_alerts = len([a for a in recent_alerts if a.level == 'critical'])
        warning_alerts = len([a for a in recent_alerts if a.level == 'warning'])
        
        return {
            'period_hours': hours,
            'data_points': len(recent_system),
            'cpu': {
                'average_percent': round(avg_cpu, 2),
                'peak_percent': round(max_cpu, 2)
            },
            'memory': {
                'average_percent': round(avg_memory, 2),
                'peak_percent': round(max_memory, 2)
            },
            'process_memory': {
                'average_mb': round(avg_process_memory, 2),
                'peak_mb': round(max_process_memory, 2)
            },
            'alerts': {
                'total': len(recent_alerts),
                'critical': critical_alerts,
                'warning': warning_alerts,
                'currently_active': len(self.active_alerts)
            }
        }
    
    def export_metrics(self, filename: Optional[str] = None, hours: int = 24) -> str:
        """Export metrics to JSON file"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"performance_metrics_{timestamp}.json"
        
        cutoff_time = time.time() - (hours * 3600)
        
        export_data = {
            'export_timestamp': datetime.now().isoformat(),
            'period_hours': hours,
            'system_metrics': [
                m.to_dict() for m in self.system_metrics_history 
                if m.timestamp > cutoff_time
            ],
            'application_metrics': [
                m.to_dict() for m in self.app_metrics_history 
                if m.timestamp > cutoff_time
            ],
            'database_metrics': [
                m.to_dict() for m in self.db_metrics_history 
                if m.timestamp > cutoff_time
            ],
            'alerts': [
                a.to_dict() for a in self.alert_history 
                if a.timestamp > cutoff_time
            ],
            'summary': self.get_performance_summary(hours),
            'thresholds': self.thresholds
        }
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"📄 Performance metrics exported to {filename}")
            return filename
            
        except Exception as e:
            self.logger.error(f"❌ Failed to export metrics: {e}")
            return ""
    
    def update_thresholds(self, new_thresholds: Dict[str, float]):
        """Update performance thresholds"""
        self.thresholds.update(new_thresholds)
        self.logger.info(f"🎯 Updated performance thresholds: {new_thresholds}")
    
    def force_garbage_collection(self):
        """Force garbage collection and log memory stats"""
        if self.memory_tracking_enabled:
            before_current, before_peak = tracemalloc.get_traced_memory()
        
        # Force GC
        collected = gc.collect()
        
        if self.memory_tracking_enabled:
            after_current, after_peak = tracemalloc.get_traced_memory()
            freed_mb = (before_current - after_current) / (1024 * 1024)
            
            self.logger.info(
                f"🧹 Garbage collection: {collected} objects collected, "
                f"{freed_mb:.2f}MB freed"
            )
    
    def get_health_status(self) -> Dict:
        """Get overall system health status"""
        if not self.system_metrics_history:
            return {'status': 'unknown', 'message': 'No metrics available'}
        
        latest = self.system_metrics_history[-1]
        critical_alerts = len([a for a in self.active_alerts if a.level == 'critical'])
        warning_alerts = len([a for a in self.active_alerts if a.level == 'warning'])
        
        # Determine overall status
        if critical_alerts > 0:
            status = 'critical'
            message = f"{critical_alerts} critical alert(s) active"
        elif warning_alerts > 0:
            status = 'warning'
            message = f"{warning_alerts} warning(s) active"
        elif (latest.cpu_percent > 50 or latest.memory_percent > 70 or 
              latest.disk_usage_percent > 80):
            status = 'degraded'
            message = "System resources under moderate load"
        else:
            status = 'healthy'
            message = "All systems operating normally"
        
        return {
            'status': status,
            'message': message,
            'active_alerts': len(self.active_alerts),
            'monitoring_active': self.running,
            'last_update': datetime.fromtimestamp(latest.timestamp).isoformat()
        }