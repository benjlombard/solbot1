"""
RugCheck.xyz Integration Module - Version Améliorée
File: rugcheck.py

This module integrates with RugCheck.xyz API to verify contract safety
and detect bundle launches, providing comprehensive token security analysis.
"""


import re
import functools
import requests
import time
import logging
import hashlib
import json
import concurrent.futures
import threading
import asyncio
import aiohttp
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Optional, Dict, List, Tuple, Union, Callable, Any
from datetime import datetime, timedelta
from collections import defaultdict, deque, Counter  
import weakref
from cachetools import LRUCache
from threading import RLock

# Ajout conditionnel de base58 pour Solana
try:
    import base58
    HAS_BASE58 = True
except ImportError:
    HAS_BASE58 = False


class CircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=300):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = 'CLOSED'  # CLOSED, OPEN, HALF_OPEN


class RiskLevel(Enum):
    """Énumération pour les niveaux de risque"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class SafetyRating(Enum):
    """Énumération pour les évaluations de sécurité"""
    GOOD = "Good"
    WARNING = "Warning"
    CAUTION = "Caution"
    DANGEROUS = "Dangerous"
    UNKNOWN = "Unknown"


class CacheStrategy(Enum):
    """Stratégies de cache disponibles"""
    LEGACY = "legacy"           # Ancien système avec dict
    WEAK_REF = "weak_ref"      # Nouveau système avec WeakValueDictionary
    HYBRID = "hybrid"          # Les deux pour migration


class CircuitState(Enum):
    """États du circuit breaker"""
    CLOSED = "CLOSED"       # Fonctionnement normal
    OPEN = "OPEN"           # Circuit ouvert, requêtes bloquées
    HALF_OPEN = "HALF_OPEN" # Test de récupération

@dataclass
class HealthMetrics:
    """Métriques de santé détaillées"""
    # Métriques par endpoint
    endpoint_response_times: Dict[str, deque] = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=100)))
    endpoint_success_rates: Dict[str, float] = field(default_factory=dict)
    endpoint_error_codes: Dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    
    # Métriques par réseau
    network_performance: Dict[str, Dict] = field(default_factory=dict)
    
    # Métriques de cache
    cache_metrics: Dict[str, Any] = field(default_factory=dict)
    
    # Métriques de qualité
    bundle_detection_accuracy: deque = field(default_factory=lambda: deque(maxlen=1000))
    false_positive_rate: float = 0.0
    false_negative_rate: float = 0.0
    
    # Métriques système
    memory_usage: deque = field(default_factory=lambda: deque(maxlen=100))
    cpu_usage: deque = field(default_factory=lambda: deque(maxlen=100))
    
    # Timestamps
    last_updated: float = field(default_factory=time.time)
    start_time: float = field(default_factory=time.time)

class HealthMetricsCollector:
    """Collecteur de métriques de santé avancé"""
    
    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.metrics = HealthMetrics()
        self._lock = threading.RLock()
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Configuration
        self.enable_system_metrics = self.config.get('enable_system_metrics', True)
        self.metrics_retention_hours = self.config.get('metrics_retention_hours', 24)
        self.alert_thresholds = self.config.get('alert_thresholds', {
            'error_rate_threshold': 0.1,
            'response_time_threshold': 10.0,
            'cache_hit_rate_threshold': 0.7
        })
        
        # Callbacks pour alertes
        self.alert_callbacks = []
        
        # Thread pour collecte système
        if self.enable_system_metrics:
            self._start_system_monitoring()
    
    def record_api_call(self, endpoint: str, network: str, response_time: float, 
                       status_code: int, success: bool):
        """Enregistre une métrique d'appel API"""
        with self._lock:
            # Métriques par endpoint
            self.metrics.endpoint_response_times[endpoint].append(response_time)
            
            # Calcul du taux de succès
            if endpoint not in self.metrics.endpoint_success_rates:
                self.metrics.endpoint_success_rates[endpoint] = 1.0 if success else 0.0
            else:
                # Moyenne mobile
                current_rate = self.metrics.endpoint_success_rates[endpoint]
                self.metrics.endpoint_success_rates[endpoint] = (current_rate * 0.9) + (0.1 if success else 0.0)
            
            # Codes d'erreur
            if not success:
                self.metrics.endpoint_error_codes[endpoint][status_code] += 1
            
            # Métriques par réseau
            if network not in self.metrics.network_performance:
                self.metrics.network_performance[network] = {
                    'total_calls': 0,
                    'successful_calls': 0,
                    'avg_response_time': 0.0,
                    'response_times': deque(maxlen=100)
                }
            
            net_metrics = self.metrics.network_performance[network]
            net_metrics['total_calls'] += 1
            if success:
                net_metrics['successful_calls'] += 1
            net_metrics['response_times'].append(response_time)
            
            # Recalcul temps de réponse moyen
            if net_metrics['response_times']:
                net_metrics['avg_response_time'] = sum(net_metrics['response_times']) / len(net_metrics['response_times'])
            
            self.metrics.last_updated = time.time()
            
            # Vérification des seuils d'alerte
            self._check_alerts(endpoint, network, response_time, success)
    
    def record_cache_operation(self, operation: str, hit: bool, cache_type: str = 'default'):
        """Enregistre une opération de cache"""
        with self._lock:
            cache_key = f"{cache_type}_{operation}"
            
            if cache_key not in self.metrics.cache_metrics:
                self.metrics.cache_metrics[cache_key] = {
                    'total_operations': 0,
                    'hits': 0,
                    'hit_rate': 0.0,
                    'recent_operations': deque(maxlen=1000)
                }
            
            cache_metric = self.metrics.cache_metrics[cache_key]
            cache_metric['total_operations'] += 1
            if hit:
                cache_metric['hits'] += 1
            
            cache_metric['recent_operations'].append(hit)
            cache_metric['hit_rate'] = cache_metric['hits'] / cache_metric['total_operations']
    
    def record_bundle_detection(self, predicted: bool, actual: bool = None, confidence: float = 0.0):
        """Enregistre une prédiction de bundle pour calcul de précision"""
        if actual is not None:
            with self._lock:
                result = {
                    'predicted': predicted,
                    'actual': actual,
                    'confidence': confidence,
                    'timestamp': time.time()
                }
                self.metrics.bundle_detection_accuracy.append(result)
                
                # Recalcul des taux d'erreur
                self._recalculate_detection_rates()
    
    def _recalculate_detection_rates(self):
        """Recalcule les taux de faux positifs/négatifs"""
        if not self.metrics.bundle_detection_accuracy:
            return
        
        recent_predictions = list(self.metrics.bundle_detection_accuracy)[-100:]  # 100 dernières
        
        true_positives = sum(1 for r in recent_predictions if r['predicted'] and r['actual'])
        false_positives = sum(1 for r in recent_predictions if r['predicted'] and not r['actual'])
        false_negatives = sum(1 for r in recent_predictions if not r['predicted'] and r['actual'])
        
        total_positive_predictions = true_positives + false_positives
        total_actual_positives = true_positives + false_negatives
        
        if total_positive_predictions > 0:
            self.metrics.false_positive_rate = false_positives / total_positive_predictions
        
        if total_actual_positives > 0:
            self.metrics.false_negative_rate = false_negatives / total_actual_positives
    
    def _start_system_monitoring(self):
        """Démarre le monitoring système en arrière-plan"""
        def collect_system_metrics():
            try:
                import psutil
                process = psutil.Process()
                
                while True:
                    try:
                        # Métriques mémoire
                        memory_info = process.memory_info()
                        memory_mb = memory_info.rss / 1024 / 1024
                        self.metrics.memory_usage.append(memory_mb)
                        
                        # Métriques CPU
                        cpu_percent = process.cpu_percent()
                        self.metrics.cpu_usage.append(cpu_percent)
                        
                        time.sleep(60)  # Collecte toutes les minutes
                        
                    except Exception as e:
                        self.logger.warning(f"Error collecting system metrics: {e}")
                        time.sleep(60)
                        
            except ImportError:
                self.logger.info("psutil not available, system metrics disabled")
        
        thread = threading.Thread(target=collect_system_metrics, daemon=True)
        thread.start()
    
    def _check_alerts(self, endpoint: str, network: str, response_time: float, success: bool):
        """Vérifie les seuils d'alerte et déclenche si nécessaire"""
        alerts = []
        
        # Seuil de temps de réponse
        if response_time > self.alert_thresholds['response_time_threshold']:
            alerts.append({
                'type': 'high_response_time',
                'endpoint': endpoint,
                'network': network,
                'value': response_time,
                'threshold': self.alert_thresholds['response_time_threshold']
            })
        
        # Seuil de taux d'erreur
        error_rate = 1 - self.metrics.endpoint_success_rates.get(endpoint, 1.0)
        if error_rate > self.alert_thresholds['error_rate_threshold']:
            alerts.append({
                'type': 'high_error_rate',
                'endpoint': endpoint,
                'value': error_rate,
                'threshold': self.alert_thresholds['error_rate_threshold']
            })
        
        # Déclencher les alertes
        for alert in alerts:
            self._trigger_alert(alert)
    
    def _trigger_alert(self, alert: Dict):
        """Déclenche une alerte"""
        self.logger.warning(f"ALERT: {alert['type']} - {alert}")
        
        for callback in self.alert_callbacks:
            try:
                callback(alert)
            except Exception as e:
                self.logger.error(f"Error in alert callback: {e}")
    
    def add_alert_callback(self, callback: Callable):
        """Ajoute un callback d'alerte"""
        self.alert_callbacks.append(callback)
    
    def get_health_summary(self) -> Dict:
        """Retourne un résumé de santé"""
        with self._lock:
            uptime = time.time() - self.metrics.start_time
            
            # Calcul des moyennes
            avg_response_times = {}
            for endpoint, times in self.metrics.endpoint_response_times.items():
                if times:
                    avg_response_times[endpoint] = sum(times) / len(times)
            
            # Cache hit rates globaux
            global_cache_stats = {
                'total_operations': 0,
                'total_hits': 0,
                'global_hit_rate': 0.0
            }
            
            for cache_metric in self.metrics.cache_metrics.values():
                global_cache_stats['total_operations'] += cache_metric['total_operations']
                global_cache_stats['total_hits'] += cache_metric['hits']
            
            if global_cache_stats['total_operations'] > 0:
                global_cache_stats['global_hit_rate'] = global_cache_stats['total_hits'] / global_cache_stats['total_operations']
            
            return {
                'uptime_seconds': uptime,
                'uptime_human': self._format_duration(uptime),
                'endpoint_performance': {
                    'average_response_times': avg_response_times,
                    'success_rates': dict(self.metrics.endpoint_success_rates),
                    'error_distribution': {k: dict(v) for k, v in self.metrics.endpoint_error_codes.items()}
                },
                'network_performance': dict(self.metrics.network_performance),
                'cache_performance': {
                    'detailed_stats': dict(self.metrics.cache_metrics),
                    'global_stats': global_cache_stats
                },
                'bundle_detection_quality': {
                    'false_positive_rate': self.metrics.false_positive_rate,
                    'false_negative_rate': self.metrics.false_negative_rate,
                    'total_predictions': len(self.metrics.bundle_detection_accuracy)
                },
                'system_resources': {
                    'current_memory_mb': self.metrics.memory_usage[-1] if self.metrics.memory_usage else 0,
                    'avg_memory_mb': sum(self.metrics.memory_usage) / len(self.metrics.memory_usage) if self.metrics.memory_usage else 0,
                    'current_cpu_percent': self.metrics.cpu_usage[-1] if self.metrics.cpu_usage else 0,
                    'avg_cpu_percent': sum(self.metrics.cpu_usage) / len(self.metrics.cpu_usage) if self.metrics.cpu_usage else 0
                },
                'last_updated': self.metrics.last_updated
            }
    
    def _format_duration(self, seconds: float) -> str:
        """Formate une durée en format lisible"""
        if seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            return f"{seconds/60:.1f}m"
        elif seconds < 86400:
            return f"{seconds/3600:.1f}h"
        else:
            return f"{seconds/86400:.1f}d"
    
    def export_metrics_prometheus(self) -> str:
        """Exporte les métriques au format Prometheus"""
        lines = []
        timestamp = int(time.time() * 1000)
        
        # Métriques de temps de réponse
        for endpoint, times in self.metrics.endpoint_response_times.items():
            if times:
                avg_time = sum(times) / len(times)
                lines.append(f'rugcheck_response_time_seconds{{endpoint="{endpoint}"}} {avg_time/1000} {timestamp}')
        
        # Métriques de taux de succès
        for endpoint, rate in self.metrics.endpoint_success_rates.items():
            lines.append(f'rugcheck_success_rate{{endpoint="{endpoint}"}} {rate} {timestamp}')
        
        # Métriques de cache
        for cache_key, metrics in self.metrics.cache_metrics.items():
            lines.append(f'rugcheck_cache_hit_rate{{cache="{cache_key}"}} {metrics["hit_rate"]} {timestamp}')
        
        return '\n'.join(lines)

@dataclass
class CircuitBreakerMetrics:
    """Métriques du circuit breaker"""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    timeout_calls: int = 0
    circuit_opened_count: int = 0
    circuit_half_opened_count: int = 0
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    failure_rate: float = 0.0
    average_call_duration: float = 0.0
    recent_call_durations: deque = field(default_factory=lambda: deque(maxlen=100))


class CircuitBreakerError(Exception):
    """Exception levée quand le circuit est ouvert"""
    def __init__(self, message: str, state: CircuitState, metrics: CircuitBreakerMetrics):
        super().__init__(message)
        self.state = state
        self.metrics = metrics


class EnhancedCircuitBreaker:
    """
    Circuit Breaker avancé avec états CLOSED/OPEN/HALF_OPEN
    
    Features:
    - États standards du pattern Circuit Breaker
    - Métriques détaillées
    - Support des timeouts
    - Thread-safe
    - Configuration flexible
    - Logging intégré
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 300,
        half_open_max_calls: int = 3,
        timeout_threshold: int = 30,
        success_threshold: int = 2,
        enable_metrics: bool = True,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize Enhanced Circuit Breaker
        
        Args:
            failure_threshold: Nombre d'échecs consécutifs avant ouverture
            recovery_timeout: Temps d'attente avant passage en HALF_OPEN (secondes)
            half_open_max_calls: Nombre max d'appels en mode HALF_OPEN
            timeout_threshold: Seuil de timeout en secondes
            success_threshold: Nombre de succès requis en HALF_OPEN pour fermer
            enable_metrics: Activer la collecte de métriques
            logger: Logger personnalisé
        """
        # Configuration
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.timeout_threshold = timeout_threshold
        self.success_threshold = success_threshold
        self.enable_metrics = enable_metrics
        
        # État du circuit
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.half_open_calls = 0
        self.last_failure_time = None
        self.last_state_change = time.time()
        
        # Thread safety
        self._lock = threading.RLock()  # RLock pour éviter les deadlocks
        
        # Métriques
        self.metrics = CircuitBreakerMetrics() if enable_metrics else None
        
        # Logging
        self.logger = logger or logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        self.logger.info(
            f"Circuit Breaker initialized: failure_threshold={failure_threshold}, "
            f"recovery_timeout={recovery_timeout}s, half_open_max_calls={half_open_max_calls}"
        )
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Exécute une fonction à travers le circuit breaker
        
        Args:
            func: Fonction à exécuter
            *args: Arguments positionnels
            **kwargs: Arguments nommés
            
        Returns:
            Résultat de la fonction
            
        Raises:
            CircuitBreakerError: Si le circuit est ouvert
            Exception: Toute exception levée par la fonction
        """
        with self._lock:
            # Vérification de l'état avant l'appel
            self._check_state()
            
            # Vérification des limites en mode HALF_OPEN
            if self.state == CircuitState.HALF_OPEN:
                if self.half_open_calls >= self.half_open_max_calls:
                    self._transition_to_open("Too many calls in HALF_OPEN state")
            
            # Enregistrement de l'appel
            if self.enable_metrics:
                self.metrics.total_calls += 1
            
            # Exécution de la fonction avec mesure du temps
            start_time = time.time()
            
            try:
                self.logger.debug(f"Executing call through circuit breaker (state: {self.state.value})")
                
                # Appel de la fonction
                result = func(*args, **kwargs)
                
                # Succès
                call_duration = time.time() - start_time
                self._record_success(call_duration)
                
                return result
                
            except Exception as e:
                # Échec
                call_duration = time.time() - start_time
                self._record_failure(e, call_duration)
                raise  # Re-lancer l'exception originale
    
    def _check_state(self):
        """Vérifie et met à jour l'état du circuit si nécessaire"""
        current_time = time.time()
        
        if self.state == CircuitState.OPEN:
            # Vérifier si on peut passer en HALF_OPEN
            if (self.last_failure_time and 
                current_time - self.last_failure_time >= self.recovery_timeout):
                self._transition_to_half_open()
            else:
                # Circuit toujours ouvert
                time_remaining = self.recovery_timeout - (current_time - (self.last_failure_time or 0))
                raise CircuitBreakerError(
                    f"Circuit breaker is OPEN. Recovery in {time_remaining:.1f}s",
                    self.state,
                    self.metrics
                )
    
    def _record_success(self, call_duration: float):
        """Enregistre un appel réussi"""
        if self.enable_metrics:
            self.metrics.successful_calls += 1
            self.metrics.last_success_time = time.time()
            self.metrics.recent_call_durations.append(call_duration)
            self._update_average_duration()
        
        # Gestion des états
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            self.half_open_calls += 1
            
            if self.success_count >= self.success_threshold:
                self._transition_to_closed("Sufficient successes in HALF_OPEN")
        
        elif self.state == CircuitState.CLOSED:
            # Reset du compteur d'échecs en cas de succès
            if self.failure_count > 0:
                self.logger.debug(f"Resetting failure count from {self.failure_count} to 0")
                self.failure_count = 0
    
    def _record_failure(self, exception: Exception, call_duration: float):
        """Enregistre un appel échoué"""
        if self.enable_metrics:
            self.metrics.failed_calls += 1
            self.metrics.last_failure_time = time.time()
            self.metrics.recent_call_durations.append(call_duration)
            self._update_average_duration()
            
            # Classement du type d'erreur
            if call_duration >= self.timeout_threshold:
                self.metrics.timeout_calls += 1
        
        # Mise à jour des compteurs d'échecs
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        self.logger.warning(
            f"Call failed (failure #{self.failure_count}): {type(exception).__name__}: {exception}"
        )
        
        # Gestion des transitions d'état
        if self.state == CircuitState.CLOSED:
            if self.failure_count >= self.failure_threshold:
                self._transition_to_open(f"Failure threshold reached: {self.failure_count}")
        
        elif self.state == CircuitState.HALF_OPEN:
            # Un seul échec en HALF_OPEN suffit pour rouvrir
            self._transition_to_open("Failure in HALF_OPEN state")
    
    def _transition_to_open(self, reason: str):
        """Transition vers l'état OPEN"""
        self.state = CircuitState.OPEN
        self.last_state_change = time.time()
        self.success_count = 0
        self.half_open_calls = 0
        
        if self.enable_metrics:
            self.metrics.circuit_opened_count += 1
            self._update_failure_rate()
        
        self.logger.warning(f"Circuit breaker OPENED: {reason}")
    
    def _transition_to_half_open(self):
        """Transition vers l'état HALF_OPEN"""
        self.state = CircuitState.HALF_OPEN
        self.last_state_change = time.time()
        self.success_count = 0
        self.half_open_calls = 0
        
        if self.enable_metrics:
            self.metrics.circuit_half_opened_count += 1
        
        self.logger.info("Circuit breaker transitioned to HALF_OPEN (testing recovery)")
    
    def _transition_to_closed(self, reason: str):
        """Transition vers l'état CLOSED"""
        self.state = CircuitState.CLOSED
        self.last_state_change = time.time()
        self.failure_count = 0
        self.success_count = 0
        self.half_open_calls = 0
        
        self.logger.info(f"Circuit breaker CLOSED (recovered): {reason}")
    
    def _update_failure_rate(self):
        """Met à jour le taux d'échec"""
        if not self.enable_metrics or self.metrics.total_calls == 0:
            return
        
        self.metrics.failure_rate = self.metrics.failed_calls / self.metrics.total_calls
    
    def _update_average_duration(self):
        """Met à jour la durée moyenne des appels"""
        if not self.enable_metrics or not self.metrics.recent_call_durations:
            return
        
        total_duration = sum(self.metrics.recent_call_durations)
        self.metrics.average_call_duration = total_duration / len(self.metrics.recent_call_durations)
    
    # Méthodes d'inspection et contrôle
    
    def get_state(self) -> CircuitState:
        """Retourne l'état actuel du circuit"""
        return self.state
    
    def get_metrics(self) -> Optional[CircuitBreakerMetrics]:
        """Retourne les métriques du circuit breaker"""
        if self.enable_metrics:
            self._update_failure_rate()
            return self.metrics
        return None
    
    def get_stats(self) -> Dict[str, Any]:
        """Retourne un résumé des statistiques"""
        with self._lock:
            stats = {
                'state': self.state.value,
                'failure_count': self.failure_count,
                'success_count': self.success_count,
                'half_open_calls': self.half_open_calls,
                'time_in_current_state': time.time() - self.last_state_change,
                'last_failure_time': self.last_failure_time,
            }
            
            if self.enable_metrics and self.metrics:
                stats.update({
                    'total_calls': self.metrics.total_calls,
                    'successful_calls': self.metrics.successful_calls,
                    'failed_calls': self.metrics.failed_calls,
                    'timeout_calls': self.metrics.timeout_calls,
                    'failure_rate': round(self.metrics.failure_rate * 100, 2),
                    'average_call_duration': round(self.metrics.average_call_duration, 3),
                    'circuit_opened_count': self.metrics.circuit_opened_count,
                    'circuit_half_opened_count': self.metrics.circuit_half_opened_count,
                })
            
            return stats
    
    def reset(self):
        """Reset le circuit breaker à l'état initial"""
        with self._lock:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.success_count = 0
            self.half_open_calls = 0
            self.last_failure_time = None
            self.last_state_change = time.time()
            
            if self.enable_metrics:
                self.metrics = CircuitBreakerMetrics()
            
            self.logger.info("Circuit breaker has been reset")
    
    def force_open(self, reason: str = "Manually forced"):
        """Force l'ouverture du circuit"""
        with self._lock:
            self._transition_to_open(f"FORCED OPEN: {reason}")
    
    def force_close(self, reason: str = "Manually forced"):
        """Force la fermeture du circuit"""
        with self._lock:
            self._transition_to_closed(f"FORCED CLOSE: {reason}")
    
    def is_call_allowed(self) -> bool:
        """Vérifie si un appel serait autorisé sans l'exécuter"""
        with self._lock:
            try:
                self._check_state()
                if self.state == CircuitState.HALF_OPEN:
                    return self.half_open_calls < self.half_open_max_calls
                return True
            except CircuitBreakerError:
                return False
    
    def get_time_to_recovery(self) -> Optional[float]:
        """Retourne le temps restant avant tentative de récupération"""
        if self.state != CircuitState.OPEN or not self.last_failure_time:
            return None
        
        elapsed = time.time() - self.last_failure_time
        remaining = max(0, self.recovery_timeout - elapsed)
        return remaining
    
    def __str__(self) -> str:
        """Représentation string du circuit breaker"""
        return (
            f"CircuitBreaker(state={self.state.value}, "
            f"failures={self.failure_count}/{self.failure_threshold}, "
            f"successes={self.success_count}/{self.success_threshold})"
        )
    
    def __repr__(self) -> str:
        return self.__str__()


# Décorateur pour simplifier l'usage
def circuit_breaker(
    failure_threshold: int = 5,
    recovery_timeout: int = 300,
    half_open_max_calls: int = 3,
    **kwargs
):
    """
    Décorateur pour appliquer un circuit breaker à une fonction
    
    Example:
        @circuit_breaker(failure_threshold=3, recovery_timeout=60)
        def risky_api_call():
            # Your API call here
            pass
    """
    def decorator(func):
        breaker = EnhancedCircuitBreaker(
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
            half_open_max_calls=half_open_max_calls,
            **kwargs
        )
        
        def wrapper(*args, **kwargs):
            return breaker.call(func, *args, **kwargs)
        
        # Exposer le circuit breaker sur la fonction
        wrapper.circuit_breaker = breaker
        return wrapper
    
    return decorator


class TokenBucketRateLimiter:
    def __init__(self, capacity, refill_rate):
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_rate
        self.last_refill = time.time()


@dataclass
class PerformanceMetrics:
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    average_response_time: float = 0.0
    cache_hit_rate: float = 0.0
    bundle_detection_rate: float = 0.0


@dataclass
class AnalysisResult:
    """Structure de données pour les résultats d'analyse"""
    token_address: str
    token_symbol: str
    token_name: str
    safety_score: float
    safety_rating: SafetyRating
    is_safe: bool
    bundle_detected: bool
    bundle_confidence: float
    risk_indicators: Dict[str, List]
    analysis_timestamp: float
    passed_verification: bool
    error: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert AnalysisResult to dictionary"""
        return {
            'token_address': self.token_address,
            'token_symbol': self.token_symbol,
            'token_name': self.token_name,
            'safety_score': self.safety_score,
            'safety_rating': self.safety_rating.value if hasattr(self.safety_rating, 'value') else str(self.safety_rating),
            'is_safe': self.is_safe,
            'bundle_detected': self.bundle_detected,
            'bundle_confidence': self.bundle_confidence,
            'risk_indicators': self.risk_indicators,
            'analysis_timestamp': self.analysis_timestamp,
            'passed_verification': self.passed_verification,
            'error': self.error
        }


@dataclass
class RiskThresholds:
    """Configuration des seuils de risque avec validation"""
    critical_max: int = 0
    high_max: int = 2
    medium_max: int = 5
    low_max: int = 10
    
    def __post_init__(self):
        """Validation des seuils"""
        if self.critical_max < 0 or self.high_max < 0 or self.medium_max < 0 or self.low_max < 0:
            raise ValueError("Risk thresholds must be non-negative")
        
        if not (self.critical_max <= self.high_max <= self.medium_max <= self.low_max):
            logging.getLogger(__name__).warning(
                "Risk thresholds may not follow expected hierarchy: "
                f"critical({self.critical_max}) <= high({self.high_max}) <= "
                f"medium({self.medium_max}) <= low({self.low_max})"
            )


@dataclass
class BundlePatterns:
    """Configuration des patterns de détection de bundle"""
    naming_keywords: List[str] = field(default_factory=lambda: [
        'v2', 'v3', '2.0', '3.0', 'relaunch', 'new', 'fixed', 'updated', 
        'beta', 'test', 'final', 'official', 'real', 'legit', 'copy', 'fork'
    ])
    
    template_indicators: List[str] = field(default_factory=lambda: [
        'copy', 'paste', 'template', 'example', 'placeholder', 'lorem',
        'ipsum', 'todo', 'changeme', 'editme'
    ])
    
    creator_thresholds: Dict[str, Union[int, float]] = field(default_factory=lambda: {
        'prolific_creator': 10,
        'rapid_launch_window': 86400 * 7,  # 7 days
        'rapid_launch_count': 3,
        'suspicious_interval': 3600  # 1 hour
    })
    
    def add_naming_keyword(self, keyword: str):
        """Ajoute un mot-clé de naming"""
        if keyword not in self.naming_keywords:
            self.naming_keywords.append(keyword.lower())
    
    def add_template_indicator(self, indicator: str):
        """Ajoute un indicateur de template"""
        if indicator not in self.template_indicators:
            self.template_indicators.append(indicator.lower())

@dataclass
class AnalysisThresholds:
    """Configuration centralisée des seuils d'analyse"""
    # Bundle detection thresholds
    variance_threshold: float = 0.1  # Seuil de variance pour la régularité des lancements
    similarity_threshold: float = 0.8  # Seuil de similarité pour les montants de trading
    frequency_penalty_factor: float = 0.1  # Facteur de pénalité pour la fréquence des risques
    
    # Trading pattern thresholds
    rapid_trade_window: int = 10  # Fenêtre en secondes pour les trades rapides
    bot_interval_tolerance: float = 0.1  # Tolérance pour détecter les intervalles de bot
    coordinated_trade_threshold: float = 0.8  # Seuil pour détecter le trading coordonné
    
    # Market analysis thresholds
    low_liquidity_threshold: int = 500  # Seuil de liquidité faible en USD
    very_low_liquidity_threshold: int = 100  # Seuil de liquidité très faible
    high_volume_ratio_threshold: float = 10.0  # Ratio volume/liquidité élevé
    
    # Bundle confidence scoring
    prolific_creator_confidence: float = 0.4  # Bonus de confiance pour créateur prolifique
    regular_timing_confidence: float = 0.3  # Bonus pour timing régulier
    coordinated_trading_confidence: float = 0.3  # Bonus pour trading coordonné
    metadata_pattern_confidence: float = 0.2  # Bonus pour patterns de métadonnées
    template_indicator_confidence: float = 0.15  # Bonus pour indicateurs de template
    multiple_indicator_bonus_cap: float = 0.2  # Bonus maximum pour multiples indicateurs
    multiple_indicator_bonus_factor: float = 0.1  # Facteur de bonus par indicateur additionnel
    
    # Risk scoring
    max_frequency_penalty: float = 1.2  # Pénalité maximum pour fréquence
    safety_score_floor: float = 0.0  # Score de sécurité minimum
    safety_score_ceiling: float = 1.0  # Score de sécurité maximum
    
    # Market concentration
    high_concentration_threshold: float = 0.8  # Seuil de concentration élevée
    medium_concentration_threshold: float = 0.6  # Seuil de concentration moyenne
    
    # Performance thresholds
    max_performance_metrics: int = 100  # Nombre maximum de métriques à conserver
    cache_cleanup_batch_size: int = 10  # Pourcentage du cache à nettoyer (divisé par 10)



class CacheWrapper:
    """Wrapper pour permettre l'utilisation avec WeakValueDictionary"""
    def __init__(self, data):
        self.data = data
        # Copier les attributs du dict pour l'accès direct
        if isinstance(data, dict):
            for key, value in data.items():
                setattr(self, key, value)
    
    def get(self, key, default=None):
        """Interface dict-like"""
        return getattr(self, key, default) if hasattr(self, key) else self.data.get(key, default)
    
    def __getitem__(self, key):
        return self.data[key]
    
    def __contains__(self, key):
        return key in self.data
    
    def items(self):
        return self.data.items() if isinstance(self.data, dict) else []


class ImprovedCacheManager:
    """Gestionnaire de cache amélioré avec migration progressive"""
    
    def __init__(self, strategy: CacheStrategy = CacheStrategy.HYBRID, config: Dict = None):
        self.strategy = strategy
        self.config = config or {}
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Cache legacy (garde la compatibilité)
        if strategy in [CacheStrategy.LEGACY, CacheStrategy.HYBRID]:
            self.cache = {}
            self.cache_expiry = {}
        
        # Nouveau cache avec WeakValueDictionary
        if strategy in [CacheStrategy.WEAK_REF, CacheStrategy.HYBRID]:
            self._weak_cache = weakref.WeakValueDictionary()
            self._weak_cache_timestamps = {}
        
        self.max_cache_size = self.config.get('max_cache_size', 1000)
        self.cache_duration_hours = self.config.get('cache_results_hours', 6)
    
    def get_cache_key(self, token_address: str) -> str:
        """Génère une clé de cache standardisée"""
        return f"rugcheck_{token_address.lower()}"
    
    def is_cache_valid(self, cache_key: str) -> bool:
        """Vérifie si l'entrée du cache est valide"""
        if self.strategy == CacheStrategy.LEGACY:
            return self._is_legacy_cache_valid(cache_key)
        elif self.strategy == CacheStrategy.WEAK_REF:
            return self._is_weak_cache_valid(cache_key)
        else:  # HYBRID
            return (self._is_legacy_cache_valid(cache_key) or 
                   self._is_weak_cache_valid(cache_key))
    
    def _is_legacy_cache_valid(self, cache_key: str) -> bool:
        """Vérification du cache legacy"""
        return (hasattr(self, 'cache_expiry') and
                cache_key in self.cache_expiry and 
                datetime.now() < self.cache_expiry[cache_key])
    
    def _is_weak_cache_valid(self, cache_key: str) -> bool:
        """Vérification du cache WeakRef"""
        if cache_key not in self._weak_cache_timestamps:
            return False
        
        timestamp = self._weak_cache_timestamps[cache_key]
        expiry = datetime.fromtimestamp(timestamp) + timedelta(hours=self.cache_duration_hours)
        return datetime.now() < expiry
    
    def get_from_cache(self, cache_key: str) -> Optional[Union[Dict, AnalysisResult]]:
        """
        Récupère une valeur du cache avec gestion d'erreurs robuste et fallback
        
        Args:
            cache_key: Clé de cache à rechercher
            
        Returns:
            Données du cache ou None si non trouvé/expiré
        """
        cache_hit = False
        cache_type = self.strategy.value
        error_occurred = False

        try:
            if self.strategy == CacheStrategy.LEGACY:
                result = self._get_from_legacy_cache(cache_key)
                cache_hit = result is not None
            
            elif self.strategy == CacheStrategy.WEAK_REF:
                result = self._get_from_weak_cache(cache_key)
                cache_hit = result is not None
            
            else:  # HYBRID
                result = self._get_from_hybrid_cache(cache_key)
                cache_hit = result is not None
                
        except (KeyError, AttributeError, ReferenceError) as e:
            logger = logging.getLogger(__name__)
            logger.warning(f"Expected cache error for {cache_key}: {e}")
            result = None
            cache_hit = False
            error_occurred = True
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Unexpected cache error for {cache_key}: {e}")
            result = None
            cache_hit = False
            error_occurred = True
        
            # Pour les erreurs inattendues, nettoyer le cache corrompu
            self._cleanup_cache_on_error(cache_key)
            raise  # Re-lancer les erreurs inattendues

        if hasattr(self, '_metrics_callback') and self._metrics_callback:
            try:
                self._metrics_callback('GET', cache_hit and not error_occurred, cache_type)
            except Exception as callback_error:
                logger = logging.getLogger(__name__)
                logger.warning(f"Metrics callback error: {callback_error}")
    
        return result


    def _get_from_legacy_cache(self, cache_key: str) -> Optional[Union[Dict, AnalysisResult]]:
        """Récupération depuis le cache legacy avec validation"""
        if not hasattr(self, 'cache') or not hasattr(self, 'cache_expiry'):
            return None
        
        # Vérification de l'existence de la clé
        if cache_key not in self.cache:
            return None
        
        try:
            result = self.cache.get(cache_key)
            if result is None:
                return None
            
            # Vérification de l'expiration
            expiry = self.cache_expiry.get(cache_key)
            if expiry is None or datetime.now() >= expiry:
                # Nettoyage atomique
                self.cache.pop(cache_key, None)
                self.cache_expiry.pop(cache_key, None)
                return None

            return result if self._validate_cached_result(result) else None
                
        except Exception as e:
            self.logger.warning(f"Legacy cache access error for {cache_key}: {e}")
            return None

    def _get_from_weak_cache(self, cache_key: str) -> Optional[Union[Dict, AnalysisResult]]:
        """Récupération depuis le cache WeakRef avec gestion des références mortes"""
        if not hasattr(self, '_weak_cache') or not hasattr(self, '_weak_cache_timestamps'):
            return None
        
        # Vérification de l'expiration d'abord
        if not self._is_weak_cache_valid(cache_key):
            # Nettoyage automatique
            self._weak_cache_timestamps.pop(cache_key, None)
            # Le WeakValueDictionary se nettoie automatiquement
            return None
        
        try:
            # Récupération avec gestion des références mortes
            wrapper = self._weak_cache.get(cache_key)
            if wrapper is None:
                # La référence a été garbage collectée
                self._weak_cache_timestamps.pop(cache_key, None)
                return None
            
            # Validation du wrapper
            if not hasattr(wrapper, 'data'):
                self._weak_cache_timestamps.pop(cache_key, None)
                return None
            
            result = wrapper.data
            
            # Validation du contenu
            if self._validate_cached_result(result):
                return result
            else:
                # Supprimer l'entrée corrompue
                self._weak_cache_timestamps.pop(cache_key, None)
                return None
                
        except (ReferenceError, AttributeError) as e:
            # L'objet a été garbage collecté ou le wrapper est corrompu
            self._weak_cache_timestamps.pop(cache_key, None)
            return None
        except Exception as e:
            # Autres erreurs inattendues
            logger = logging.getLogger(__name__)
            logger.warning(f"Weak cache access error for {cache_key}: {e}")
            return None

    def _get_from_hybrid_cache(self, cache_key: str) -> Optional[Union[Dict, AnalysisResult]]:
        """Récupération hybride avec fallback intelligent"""
        # Essaie d'abord le cache legacy (plus rapide)
        try:
            result = self._get_from_legacy_cache(cache_key)
            if result is not None:
                return result
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.debug(f"Legacy cache access failed for {cache_key}: {e}")
        
        # Fallback vers le cache WeakRef
        try:
            result = self._get_from_weak_cache(cache_key)
            if result is not None:
                # Migration automatique vers le cache legacy pour la performance
                try:
                    if isinstance(result, AnalysisResult):
                        result_dict = {
                            'token_address': result.token_address,
                            'token_symbol': result.token_symbol,
                            'token_name': result.token_name,
                            'safety_score': result.safety_score,
                            'safety_rating': result.safety_rating.value if hasattr(result.safety_rating, 'value') else str(result.safety_rating),
                            'is_safe': result.is_safe,
                            'bundle_detected': result.bundle_detected,
                            'bundle_confidence': result.bundle_confidence,
                            'risk_indicators': result.risk_indicators,
                            'analysis_timestamp': result.analysis_timestamp,
                            'passed_verification': result.passed_verification,
                            'error': result.error
                        }
                        self._store_in_legacy_cache(cache_key, result_dict)
                    else:
                        self._store_in_legacy_cache(cache_key, result)
                except Exception as migration_error:
                    logger = logging.getLogger(__name__)
                    logger.debug(f"Cache migration failed for {cache_key}: {migration_error}")
                
                return result
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.debug(f"Weak cache access failed for {cache_key}: {e}")
        
        return None


    def _validate_cached_result(self, result) -> bool:
        """Valide la structure d'un résultat mis en cache"""
        if result is None:
            return False
        
        # Validation pour AnalysisResult
        if isinstance(result, AnalysisResult):
            return (hasattr(result, 'token_address') and 
                    hasattr(result, 'safety_score') and 
                    hasattr(result, 'analysis_timestamp'))
        
        # Validation pour dict
        elif isinstance(result, dict):
            required_fields = ['token_address', 'safety_score', 'analysis_timestamp']
            return all(field in result for field in required_fields)
        
        return False

    def _cleanup_cache_on_error(self, cache_key: str):
        """Nettoie les entrées de cache corrompues"""
        try:
            # Nettoyage du cache legacy
            if hasattr(self, 'cache'):
                self.cache.pop(cache_key, None)
            if hasattr(self, 'cache_expiry'):
                self.cache_expiry.pop(cache_key, None)
            
            # Nettoyage du cache WeakRef
            if hasattr(self, '_weak_cache_timestamps'):
                self._weak_cache_timestamps.pop(cache_key, None)
                
        except Exception as cleanup_error:
            logger = logging.getLogger(__name__)
            logger.warning(f"Cache cleanup error for {cache_key}: {cleanup_error}")


    def store_in_cache(self, cache_key: str, result):
        """Stocke une valeur dans le cache"""
        if self.strategy == CacheStrategy.LEGACY:
            self._store_in_legacy_cache(cache_key, result)
        elif self.strategy == CacheStrategy.WEAK_REF:
            self._store_in_weak_cache(cache_key, result)
        else:  # HYBRID
            self._store_in_legacy_cache(cache_key, result)
            self._store_in_weak_cache(cache_key, result)
    
    def _store_in_legacy_cache(self, cache_key: str, result):
        """Stockage dans le cache legacy"""
        if not hasattr(self, 'cache'):
            return
            
        # Nettoyage si nécessaire
        if len(self.cache) >= self.max_cache_size:
            self._cleanup_legacy_cache()
        
        self.cache[cache_key] = result
        self.cache_expiry[cache_key] = datetime.now() + timedelta(hours=self.cache_duration_hours)
    
    def _store_in_weak_cache(self, cache_key: str, result):
        """Stockage dans le cache WeakRef"""
        # Wrapper le résultat pour le WeakValueDictionary
        wrapper = CacheWrapper(result)
        self._weak_cache[cache_key] = wrapper
        self._weak_cache_timestamps[cache_key] = time.time()
    
    def _cleanup_legacy_cache(self):
        """Nettoyage du cache legacy"""
        if not hasattr(self, 'cache'):
            return
            
        current_time = datetime.now()
        expired_keys = [
            key for key, expiry in self.cache_expiry.items()
            if current_time >= expiry
        ]
        
        for key in expired_keys:
            self.cache.pop(key, None)
            self.cache_expiry.pop(key, None)
        
        # Si encore trop grand, supprimer les plus anciens
        if len(self.cache) >= self.max_cache_size:
            oldest_keys = sorted(
                self.cache_expiry.items(), 
                key=lambda x: x[1]
            )[:len(self.cache) // 10]
            
            for key, _ in oldest_keys:
                self.cache.pop(key, None)
                self.cache_expiry.pop(key, None)


class RugCheckAnalyzer:
    """
    RugCheck.xyz API integration for comprehensive token safety analysis
    
    Features:
    - Contract safety verification
    - Bundle launch detection  
    - Risk assessment and scoring
    - Automated retry logic with rate limiting
    - Comprehensive caching system with migration support
    """

    # Patterns compilés pour de meilleures performances
    _ETH_ADDRESS_PATTERN = re.compile(r'^0x[a-fA-F0-9]{40}$')
    _BASE58_CHARS = set('123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz')

    def __init__(self, config):
        self.config = config['rugcheck']
        self.base_url = self.config['api_base_url']
        self.logger = logging.getLogger(__name__)
        self.advanced_logger = None  # Will be set by parent
        self._session = requests.Session()
        self._session.timeout = self.config['api_timeout']
        self._address_cache = LRUCache(maxsize=5000)
        self._address_cache_lock = RLock()
        self.circuit_breaker = EnhancedCircuitBreaker(
            failure_threshold=self.config.get('circuit_breaker_failure_threshold', 5),
            recovery_timeout=self.config.get('circuit_breaker_recovery_timeout', 300),
            half_open_max_calls=self.config.get('circuit_breaker_half_open_calls', 3),
            timeout_threshold=self.config.get('api_timeout', 30),
            logger=self.logger
        )

        # Collecteur de métriques de santé
        metrics_config = self.config.get('health_metrics', {})
        self.health_metrics = HealthMetricsCollector(metrics_config)

        # Configuration des alertes par défaut
        self.health_metrics.add_alert_callback(self._default_alert_handler)

        # Gestionnaire de cache amélioré
        cache_strategy = CacheStrategy(self.config.get('cache_strategy', 'hybrid'))
        self.cache_manager = ImprovedCacheManager(cache_strategy, self.config)

        # Configurer le callback de métriques pour le cache manager
        self.cache_manager._metrics_callback = self._cache_metrics_callback

        # Configuration des seuils de risque (version améliorée)
        risk_config = self.config.get('risk_thresholds', {})
        self.risk_thresholds = RiskThresholds(
            critical_max=risk_config.get('critical_max', 0),
            high_max=risk_config.get('high_max', 2),
            medium_max=risk_config.get('medium_max', 5),
            low_max=risk_config.get('low_max', 10)
        )
        
        # Configuration des seuils d'analyse (NOUVEAU)
        thresholds_config = self.config.get('analysis_thresholds', {})
        self.analysis_thresholds = AnalysisThresholds(
            variance_threshold=thresholds_config.get('variance_threshold', 0.1),
            similarity_threshold=thresholds_config.get('similarity_threshold', 0.8),
            frequency_penalty_factor=thresholds_config.get('frequency_penalty_factor', 0.1),
            rapid_trade_window=thresholds_config.get('rapid_trade_window', 10),
            bot_interval_tolerance=thresholds_config.get('bot_interval_tolerance', 0.1),
            coordinated_trade_threshold=thresholds_config.get('coordinated_trade_threshold', 0.8),
            low_liquidity_threshold=thresholds_config.get('low_liquidity_threshold', 500),
            very_low_liquidity_threshold=thresholds_config.get('very_low_liquidity_threshold', 100),
            high_volume_ratio_threshold=thresholds_config.get('high_volume_ratio_threshold', 10.0),
            prolific_creator_confidence=thresholds_config.get('prolific_creator_confidence', 0.4),
            regular_timing_confidence=thresholds_config.get('regular_timing_confidence', 0.3),
            coordinated_trading_confidence=thresholds_config.get('coordinated_trading_confidence', 0.3),
            metadata_pattern_confidence=thresholds_config.get('metadata_pattern_confidence', 0.2),
            template_indicator_confidence=thresholds_config.get('template_indicator_confidence', 0.15),
            multiple_indicator_bonus_cap=thresholds_config.get('multiple_indicator_bonus_cap', 0.2),
            multiple_indicator_bonus_factor=thresholds_config.get('multiple_indicator_bonus_factor', 0.1),
            max_frequency_penalty=thresholds_config.get('max_frequency_penalty', 1.2),
            safety_score_floor=thresholds_config.get('safety_score_floor', 0.0),
            safety_score_ceiling=thresholds_config.get('safety_score_ceiling', 1.0),
            high_concentration_threshold=thresholds_config.get('high_concentration_threshold', 0.8),
            medium_concentration_threshold=thresholds_config.get('medium_concentration_threshold', 0.6),
            max_performance_metrics=thresholds_config.get('max_performance_metrics', 100),
            cache_cleanup_batch_size=thresholds_config.get('cache_cleanup_batch_size', 10)
        )

        try:
            # Validation basique des seuils
            if self.analysis_thresholds.variance_threshold < 0 or self.analysis_thresholds.variance_threshold > 1:
                self.logger.warning(f"variance_threshold should be between 0 and 1, got {self.analysis_thresholds.variance_threshold}")
    
            if (self.analysis_thresholds.similarity_threshold < 0 or self.analysis_thresholds.similarity_threshold > 1):
                self.logger.warning(f"similarity_threshold should be between 0 and 1, got {self.analysis_thresholds.similarity_threshold}")
        
        except Exception as e:
            self.logger.error(f"Error validating analysis thresholds: {e}")
    
        # Configuration des patterns de bundle (version améliorée)
        bundle_config = self.config.get('bundle_patterns', {})
        self.bundle_patterns = BundlePatterns(
            naming_keywords=bundle_config.get('naming_keywords', BundlePatterns().naming_keywords),
            template_indicators=bundle_config.get('template_indicators', BundlePatterns().template_indicators),
            creator_thresholds=bundle_config.get('creator_thresholds', BundlePatterns().creator_thresholds)
        )
        
        # Configuration améliorée des poids de risque
        self.risk_weights = self._initialize_risk_weights()
        
        # Semaphore pour limiter les requêtes concurrentes
        self._request_semaphore = asyncio.Semaphore(
            self.config.get('max_concurrent_requests', 5)
        )
        
        # Propriétés pour rétrocompatibilité
        self._setup_legacy_compatibility()
        
        self.logger.info(
            f"RugCheck Analyzer improved initialized - "
            f"Strategy: {cache_strategy.value}, "
            f"Variance threshold: {self.analysis_thresholds.variance_threshold}, "
            f"Similarity threshold: {self.analysis_thresholds.similarity_threshold}"
        )
    
    def _assess_api_health(self, health_summary: Dict) -> str:
        """Évalue la santé de l'API client"""
        success_rates = health_summary.get('endpoint_performance', {}).get('success_rates', {})
        if not success_rates:
            return 'unknown'
        
        avg_success_rate = sum(success_rates.values()) / len(success_rates)
        if avg_success_rate >= 0.9:
            return 'excellent'
        elif avg_success_rate >= 0.8:
            return 'good'
        elif avg_success_rate >= 0.6:
            return 'warning'
        else:
            return 'critical'

    def _assess_cache_health(self, health_summary: Dict) -> str:
        """Évalue la santé du système de cache"""
        cache_stats = health_summary.get('cache_performance', {}).get('global_stats', {})
        hit_rate = cache_stats.get('global_hit_rate', 0)
        
        if hit_rate >= 0.8:
            return 'excellent'
        elif hit_rate >= 0.6:
            return 'good'
        elif hit_rate >= 0.4:
            return 'warning'
        else:
            return 'critical'

    def _assess_circuit_health(self, circuit_stats: Dict) -> str:
        """Évalue la santé du circuit breaker"""
        state = circuit_stats.get('state', 'UNKNOWN')
        if state == 'CLOSED':
            return 'excellent'
        elif state == 'HALF_OPEN':
            return 'warning'
        else:
            return 'critical'

    def _assess_detection_health(self, health_summary: Dict) -> str:
        """Évalue la santé de la détection de bundle"""
        detection_quality = health_summary.get('bundle_detection_quality', {})
        false_positive_rate = detection_quality.get('false_positive_rate', 0)
        
        if false_positive_rate <= 0.05:
            return 'excellent'
        elif false_positive_rate <= 0.1:
            return 'good'
        elif false_positive_rate <= 0.2:
            return 'warning'
        else:
            return 'critical'

    def _generate_health_recommendations(self, health_summary: Dict, circuit_stats: Dict) -> List[str]:
        """Génère des recommandations de santé"""
        recommendations = []
        
        # Vérifier l'état du circuit breaker
        if circuit_stats.get('state') == 'OPEN':
            recommendations.append("Circuit breaker is open - service degraded")
        
        # Vérifier les taux de succès API
        success_rates = health_summary.get('endpoint_performance', {}).get('success_rates', {})
        if success_rates:
            avg_rate = sum(success_rates.values()) / len(success_rates)
            if avg_rate < 0.8:
                recommendations.append("API success rate is low - check network connectivity")
        
        # Vérifier le cache
        cache_stats = health_summary.get('cache_performance', {}).get('global_stats', {})
        if cache_stats.get('global_hit_rate', 0) < 0.5:
            recommendations.append("Cache hit rate is low - consider adjusting cache strategy")
        
        return recommendations

    def _cache_metrics_callback(self, operation: str, success: bool, cache_type: str):
        """Callback pour enregistrer les métriques de cache depuis le cache manager"""
        self.health_metrics.record_cache_operation(operation, success, cache_type)

    def _initialize_risk_weights(self) -> Dict[RiskLevel, float]:
        """Initialise les poids de risque avec une logique plus sophistiquée"""
        base_weights = {
            RiskLevel.CRITICAL: 1.0,
            RiskLevel.HIGH: 0.6,
            RiskLevel.MEDIUM: 0.3,
            RiskLevel.LOW: 0.1,
            RiskLevel.INFO: 0.02
        }
        
        # Ajustements basés sur la configuration
        multiplier = self.config.get('risk_sensitivity', 1.0)
        return {level: weight * multiplier for level, weight in base_weights.items()}
    
    def _default_alert_handler(self, alert: Dict):
        """Gestionnaire d'alerte par défaut"""
        self.logger.warning(f"Health Alert: {alert['type']} - Value: {alert['value']}, Threshold: {alert['threshold']}")
        
        if self.advanced_logger:
            self.advanced_logger.debug_step('health', f'alert_{alert["type"]}', 
                                        f'🚨 HEALTH ALERT: {alert["type"]} detected')

    def get_health_status(self) -> Dict:
        """Retourne le statut de santé détaillé"""
        health_summary = self.health_metrics.get_health_summary()
        circuit_stats = self.circuit_breaker.get_stats()
        
        return {
            'overall_health': self._calculate_overall_health(health_summary, circuit_stats),
            'component_health': {
                'api_client': self._assess_api_health(health_summary),
                'cache_system': self._assess_cache_health(health_summary),
                'circuit_breaker': self._assess_circuit_health(circuit_stats),
                'bundle_detection': self._assess_detection_health(health_summary)
            },
            'metrics': health_summary,
            'circuit_breaker': circuit_stats,
            'recommendations': self._generate_health_recommendations(health_summary, circuit_stats)
        }

    def add_health_alert_callback(self, callback: Callable):
        """Ajoute un callback d'alerte personnalisé"""
        self.health_metrics.add_alert_callback(callback)

    def export_metrics_prometheus(self) -> str:
        """Exporte les métriques pour Prometheus"""
        return self.health_metrics.export_metrics_prometheus()

    def _detect_network(self, token_address: str) -> str:
        """Détecte le réseau basé sur le format d'adresse"""
        if token_address.startswith('0x') and len(token_address) == 42:
            return 'ethereum'
        elif 32 <= len(token_address) <= 44 and not token_address.startswith('0x'):
            return 'solana'
        elif token_address.startswith('T') and len(token_address) == 34:
            return 'tron'
        else:
            return 'unknown'

    def _calculate_overall_health(self, health_summary: Dict, circuit_stats: Dict) -> str:
        """Calcule l'état de santé global"""
        scores = []
        
        # Score API (basé sur taux de succès)
        success_rates = health_summary.get('endpoint_performance', {}).get('success_rates', {})
        if success_rates:
            avg_success_rate = sum(success_rates.values()) / len(success_rates)
            scores.append(avg_success_rate)
        
        # Score cache
        cache_stats = health_summary.get('cache_performance', {}).get('global_stats', {})
        cache_hit_rate = cache_stats.get('global_hit_rate', 0)
        scores.append(cache_hit_rate)
        
        # Score circuit breaker
        if circuit_stats['state'] == 'CLOSED':
            scores.append(1.0)
        elif circuit_stats['state'] == 'HALF_OPEN':
            scores.append(0.5)
        else:
            scores.append(0.0)
        
        if not scores:
            return 'unknown'
        
        overall_score = sum(scores) / len(scores)
        
        if overall_score >= 0.9:
            return 'excellent'
        elif overall_score >= 0.8:
            return 'good'
        elif overall_score >= 0.6:
            return 'warning'
        elif overall_score >= 0.4:
            return 'critical'
        else:
            return 'failure'

    def _setup_legacy_compatibility(self):
        """Configure la compatibilité avec l'ancienne API"""
        # Expose les anciennes propriétés pour la compatibilité
        if hasattr(self.cache_manager, 'cache'):
            self.cache = self.cache_manager.cache
            self.cache_expiry = self.cache_manager.cache_expiry
        else:
            # Fallback pour compatibilité
            self.cache = {}
            self.cache_expiry = {}
        
    def set_advanced_logger(self, advanced_logger):
        """Set advanced logger instance"""
        self.advanced_logger = advanced_logger

    def get_cache_key(self, token_address):
        """Generate cache key for token analysis"""
        return self.cache_manager.get_cache_key(token_address)
        
    def is_cache_valid(self, cache_key):
        """Check if cached result is still valid"""
        return self.cache_manager.is_cache_valid(cache_key)

    def analyze_token_safety(self, token_address: str) -> AnalysisResult:
        """
        Comprehensive token safety analysis using RugCheck.xyz - Version corrigée
        
        🔧 CORRECTION : Cette fonction retourne TOUJOURS un AnalysisResult, jamais un dict
        
        Returns detailed analysis including:
        - Safety score and rating
        - Bundle detection with confidence
        - Risk indicators categorized by severity
        - Market analysis and trading patterns
        """
        start_time = time.time()
        
        if not self._validate_token_for_rugcheck(token_address):
            return self._create_error_result("Token not suitable for RugCheck analysis", token_address)

        # Validation d'entrée améliorée
        if not self._validate_address_format(token_address):
            error_msg = f"Invalid token address format: {token_address}"
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'rugcheck_invalid_address', 
                                               f'❌ RUGCHECK: {error_msg}')
            # ✅ CORRECTION : Retour cohérent en AnalysisResult
            return self._create_error_result(error_msg, token_address)
        
        # Normalisation de l'adresse
        normalized_address = token_address.strip()
        cache_key = self.get_cache_key(normalized_address.lower())
        
        if self.advanced_logger:
            self.advanced_logger.debug_step('analysis', 'rugcheck_start', 
                                           f'🔒 RUGCHECK: Starting safety analysis for {normalized_address[:8]}...')
        
        # Vérification du cache avec gestion d'erreurs
        try:
            cached_result = self.cache_manager.get_from_cache(cache_key)
            if cached_result:
                if self.advanced_logger:
                    self.advanced_logger.log_cache_operation('analysis', 'GET', 
                                                           f'rugcheck_{normalized_address[:8]}', hit=True)
                
                return self._normalize_cached_result(cached_result, normalized_address)
            else:
                if self.advanced_logger:
                    self.advanced_logger.log_cache_operation('analysis', 'GET', 
                                                           f'rugcheck_{normalized_address[:8]}', hit=False)
        except Exception as cache_error:

            # Enregistrer manuellement l'erreur si le callback n'a pas pu le faire
            self.health_metrics.record_cache_operation('GET', False, self.cache_manager.strategy.value)
            self.logger.warning(f"Cache retrieval error for {normalized_address}: {cache_error}")
            # Continue sans cache
        
        try:
            # Requête API avec retry et circuit breaker
            response_data = self._make_rugcheck_request_with_circuit_breaker(normalized_address)
            
            if not response_data:
                error_msg = "API request failed after all retries"
                return self._create_error_result(error_msg, normalized_address)
            
            # Validation de la réponse API
            if not self._validate_api_response(response_data):
                error_msg = "Invalid API response structure"
                return self._create_error_result(error_msg, normalized_address)
            
            # Parse de la réponse avec gestion d'erreurs robuste
            try:
                analysis_result = self._parse_rugcheck_response_to_analysis_result(response_data, normalized_address)
            except Exception as parse_error:
                error_msg = f"Response parsing error: {str(parse_error)}"
                self.logger.error(f"Parse error for {normalized_address}: {parse_error}")
                return self._create_error_result(error_msg, normalized_address)
            
            # ✅ VALIDATION : S'assurer qu'on a bien un AnalysisResult
            if not isinstance(analysis_result, AnalysisResult):
                self.logger.error(f"Parser returned invalid type: {type(analysis_result)}")
                return self._create_error_result("Internal parsing error", normalized_address)
            
            # Cache du résultat avec gestion d'erreurs
            try:
                cacheable_dict = self._analysis_result_to_cacheable_dict(analysis_result)
                self._cache_result(cache_key, cacheable_dict)
            except Exception as cache_error:
                self.logger.warning(f"Cache storage error for {normalized_address}: {cache_error}")
                # Continue sans mettre en cache
            
            # Logging de fin avec métriques
            duration = time.time() - start_time
            if self.advanced_logger:
                safety_rating = analysis_result.safety_rating.value if hasattr(analysis_result.safety_rating, 'value') else str(analysis_result.safety_rating)
                self.advanced_logger.debug_step('analysis', 'rugcheck_complete', 
                                               f'✅ RUGCHECK: Analysis complete for {normalized_address[:8]}... - '
                                               f'Rating: {safety_rating}, Bundle: {analysis_result.bundle_detected}, '
                                               f'Duration: {duration:.3f}s')
            
            # Enregistrement des métriques de performance
            self._record_performance_metrics(normalized_address, duration, True)
            
            return analysis_result
            
        except requests.exceptions.Timeout:
            error_msg = "API request timeout"
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'rugcheck_timeout', 
                                               f'⏰ RUGCHECK: Timeout for {normalized_address[:8]}...')
            return self._create_error_result(error_msg, normalized_address)
            
        except requests.exceptions.ConnectionError:
            error_msg = "API connection error"
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'rugcheck_connection_error', 
                                               f'🌐 RUGCHECK: Connection error for {normalized_address[:8]}...')
            return self._create_error_result(error_msg, normalized_address)
            
        except Exception as e:
            error_msg = f"Unexpected analysis error: {str(e)}"
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'rugcheck_error', 
                                               f'❌ RUGCHECK: Analysis error for {normalized_address[:8]}...: {e}')
            self.logger.error(f"Error analyzing token safety for {normalized_address}: {e}")
            
            # Enregistrement des métriques d'erreur
            duration = time.time() - start_time
            self._record_performance_metrics(normalized_address, duration, False)
            
            return self._create_error_result(error_msg, normalized_address)


    # ✅ MÉTHODE AUXILIAIRE : Normalisation robuste du cache
    def _normalize_cached_result(self, cached_result, token_address: str) -> AnalysisResult:
        """Normalise un résultat de cache en AnalysisResult de manière robuste"""
        try:
            if isinstance(cached_result, AnalysisResult):
                # Déjà au bon format
                return cached_result
                
            elif isinstance(cached_result, dict):
                # Conversion dict -> AnalysisResult avec validation
                return self._dict_to_analysis_result(cached_result, token_address)
                
            else:
                # Type inattendu
                self.logger.warning(f"Unexpected cached result type: {type(cached_result)}")
                return self._create_error_result("Invalid cached result type", token_address)
                
        except Exception as e:
            self.logger.error(f"Error normalizing cached result: {e}")
            return self._create_error_result("Cache normalization error", token_address)

    # ✅ MÉTHODE AUXILIAIRE : Conversion dict -> AnalysisResult robuste
    def _dict_to_analysis_result(self, result_dict: Dict, token_address: str) -> AnalysisResult:
        """Convertit un dict en AnalysisResult avec validation et valeurs par défaut"""
        try:
            # Validation des champs obligatoires
            required_fields = ['token_address', 'safety_score', 'analysis_timestamp']
            for field in required_fields:
                if field not in result_dict:
                    raise ValueError(f"Missing required field: {field}")
            
            # Conversion sécurisée du safety_rating
            safety_rating_raw = result_dict.get('safety_rating', 'Unknown')
            if isinstance(safety_rating_raw, str):
                try:
                    safety_rating = SafetyRating(safety_rating_raw.lower())
                except ValueError:
                    safety_rating = SafetyRating.UNKNOWN
            elif hasattr(safety_rating_raw, 'value'):
                safety_rating = safety_rating_raw
            else:
                safety_rating = SafetyRating.UNKNOWN
            
            # Construction avec valeurs par défaut sécurisées
            return AnalysisResult(
                token_address=result_dict.get('token_address', token_address),
                token_symbol=result_dict.get('token_symbol', 'UNKNOWN'),
                token_name=result_dict.get('token_name', 'Unknown'),
                safety_score=float(result_dict.get('safety_score', 0.0)),
                safety_rating=safety_rating,
                is_safe=bool(result_dict.get('is_safe', False)),
                bundle_detected=bool(result_dict.get('bundle_detected', False)),
                bundle_confidence=float(result_dict.get('bundle_confidence', 0.0)),
                risk_indicators=result_dict.get('risk_indicators', {}),
                analysis_timestamp=float(result_dict.get('analysis_timestamp', time.time())),
                passed_verification=bool(result_dict.get('passed_verification', False)),
                error=result_dict.get('error')
            )
            
        except (ValueError, TypeError, KeyError) as e:
            self.logger.error(f"Error converting dict to AnalysisResult: {e}")
            return self._create_error_result(f"Dict conversion error: {e}", token_address)

    # ✅ MÉTHODE AUXILIAIRE : Parse vers AnalysisResult directement
    def _parse_rugcheck_response_to_analysis_result(self, response_data: Dict, token_address: str) -> AnalysisResult:
        """Parse RugCheck API response directement vers AnalysisResult"""
        try:
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'rugcheck_parse_start', 
                                            f'📋 RUGCHECK: Parsing response for {token_address[:8]}...')
            
            # ✅ Structure selon la documentation RugCheck
            mint = response_data.get('mint', token_address)
            token_meta = response_data.get('tokenMeta', {}) or response_data.get('fileMeta', {})
            risks = response_data.get('risks', [])
            score = response_data.get('score', 0)
            score_normalised = response_data.get('score_normalised', score)
            
            # Calculate comprehensive safety score
            safety_score = min(1.0, max(0.0, score_normalised / 100.0)) if score_normalised else 0.0
            safety_rating = self._get_safety_rating_enum(safety_score)
            
            # ✅ Extraction des métadonnées de token
            token_symbol = token_meta.get('symbol', 'UNKNOWN')
            token_name = token_meta.get('name', 'Unknown Token')
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'rugcheck_safety_calculated', 
                                            f'🎯 RUGCHECK: Safety calculated - Score: {safety_score:.3f}, Rating: {safety_rating.value}')
            
            # Advanced bundle detection analysis
            bundle_analysis = self._analyze_rugcheck_bundle_indicators(response_data)
            bundle_detected, bundle_confidence, bundle_indicators = bundle_analysis
            
            if bundle_detected and self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'rugcheck_bundle_detected', 
                                            f'📦 RUGCHECK: BUNDLE DETECTED - Confidence: {bundle_confidence:.3f}')
            
            # Extract and categorize risk indicators
            risk_indicators = self._extract_rugcheck_risk_indicators(risks)
            
            # ✅ Déterminer si le token passe la vérification
            passed_verification = (
                safety_score >= 0.7 and
                not bundle_detected and
                len(risk_indicators.get('critical', [])) == 0 and
                len(risk_indicators.get('high', [])) <= 2
            )
            
            # ✅ Créer l'AnalysisResult
            analysis_result = AnalysisResult(
                token_address=mint,
                token_symbol=token_symbol,
                token_name=token_name,
                safety_score=safety_score,
                safety_rating=safety_rating,
                is_safe=(safety_score >= 0.7 and not bundle_detected),
                bundle_detected=bundle_detected,
                bundle_confidence=bundle_confidence,
                risk_indicators=risk_indicators,
                analysis_timestamp=time.time(),
                passed_verification=passed_verification,
                error=None
            )
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'rugcheck_parse_complete', 
                                            f'RugCheck: Parsing complete - {len(risks)} risks analyzed')
            
            return analysis_result
            
        except Exception as e:
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'rugcheck_parse_error', 
                                            f'RugCheck: Parse error: {e}')
            self.logger.error(f"Error parsing RugCheck response: {e}")
            return self._create_error_result(f"Parse error: {str(e)}", token_address)



    def _analyze_rugcheck_bundle_indicators(self, response_data: Dict) -> Tuple[bool, float, List[str]]:
        """Analyse les indicateurs de bundle basés sur les données RugCheck"""
        indicators = []
        confidence_scores = []
        
        try:

            if not response_data or not isinstance(response_data, dict):
                return False, 0.0, []

            # ✅ Analyser les créateurs de tokens (indicateur de bundle)
            creator_tokens = response_data.get('creatorTokens', [])
            if creator_tokens and len(creator_tokens) > 10:
                indicators.append(f"Creator has launched {len(creator_tokens)} tokens")
                confidence_scores.append(0.6)
            elif creator_tokens and len(creator_tokens) > 5:
                indicators.append(f"Creator has launched {len(creator_tokens)} tokens")
                confidence_scores.append(0.3)
            
            # ✅ Analyser les réseaux d'insiders
            insider_networks = response_data.get('insiderNetworks', [])
            if insider_networks:
                for network in insider_networks:
                    if network and network.get('size', 0) > 10:
                        indicators.append(f"Large insider network detected: {network.get('size')} accounts")
                        confidence_scores.append(0.4)
            
            # ✅ Analyser les top holders pour des patterns suspects
            top_holders = response_data.get('topHolders', [])
            if top_holders:  # Vérifier que ce n'est pas None
                insider_count = sum(1 for holder in top_holders if holder and holder.get('insider', False))
                if len(top_holders) > 0 and insider_count > len(top_holders) * 0.5:
                    indicators.append(f"High insider concentration: {insider_count}/{len(top_holders)} top holders")
                    confidence_scores.append(0.5)
            
            # ✅ Analyser les risques liés aux bundles
            risks = response_data.get('risks', [])
            if risks:  # Vérifier que ce n'est pas None
                bundle_related_risks = [
                    risk for risk in risks 
                    if (risk and 
                        any(keyword in risk.get('description', '').lower() 
                            for keyword in ['bundle', 'coordinated', 'insider', 'launch']))
                ]
                
                if bundle_related_risks:
                    indicators.append(f"Bundle-related risks detected: {len(bundle_related_risks)}")
                    confidence_scores.append(0.3)
            
            # ✅ Calcul de confiance composite
            if confidence_scores:
                # Moyenne pondérée avec bonus pour multiples indicateurs
                weighted_confidence = sum(confidence_scores) / len(confidence_scores)
                multiple_indicator_bonus = min(0.2, (len(confidence_scores) - 1) * 0.1)
                final_confidence = min(1.0, weighted_confidence + multiple_indicator_bonus)
            else:
                final_confidence = 0.0
            
            detected = final_confidence > 0.5
            
            return detected, final_confidence, indicators
            
        except Exception as e:
            self.logger.error(f"Error in RugCheck bundle analysis: {e}")
            return False, 0.0, []

    # 5. EXTRAIRE les risques selon la structure RugCheck :
    def _extract_rugcheck_risk_indicators(self, risks: List[Dict]) -> Dict[str, List]:
        """Extrait et catégorise les risques selon la structure RugCheck"""
        risk_indicators = {
            'critical': [],
            'high': [],
            'medium': [],
            'low': [],
            'info': []
        }
        
        # ✅ Mapping des niveaux de risque RugCheck
        level_mapping = {
            'critical': 'critical',
            'high': 'high', 
            'medium': 'medium',
            'low': 'low',
            'info': 'info',
            'warning': 'medium',  # Fallback
            'caution': 'medium'   # Fallback
        }
        
        for risk in risks:
            level = risk.get('level', 'low').lower()
            mapped_level = level_mapping.get(level, 'low')
            
            risk_info = {
                'name': risk.get('name', 'Unknown Risk'),
                'description': risk.get('description', 'No description'),
                'score': risk.get('score', 0),
                'value': risk.get('value', ''),
                'rugcheck_level': level
            }
            
            risk_indicators[mapped_level].append(risk_info)
        
        return risk_indicators


    # ✅ MÉTHODE AUXILIAIRE : Conversion safety_rating vers enum
    def _get_safety_rating_enum(self, safety_score: float) -> SafetyRating:
        """Convert numerical score to SafetyRating enum"""
        if safety_score >= 0.85:
            return SafetyRating.GOOD
        elif safety_score >= 0.65:
            return SafetyRating.WARNING
        elif safety_score >= 0.45:
            return SafetyRating.CAUTION
        else:
            return SafetyRating.DANGEROUS

    # ✅ MÉTHODE AUXILIAIRE : AnalysisResult vers dict cacheable
    def _analysis_result_to_cacheable_dict(self, analysis_result: AnalysisResult) -> Dict:
        """Convertit un AnalysisResult en dict cacheable pour compatibilité legacy"""
        try:
            return {
                'token_address': analysis_result.token_address,
                'token_symbol': analysis_result.token_symbol,
                'token_name': analysis_result.token_name,
                'safety_score': analysis_result.safety_score,
                'safety_rating': analysis_result.safety_rating.value if hasattr(analysis_result.safety_rating, 'value') else str(analysis_result.safety_rating),
                'is_safe': analysis_result.is_safe,
                'bundle_detected': analysis_result.bundle_detected,
                'bundle_confidence': analysis_result.bundle_confidence,
                'risk_indicators': analysis_result.risk_indicators,
                'analysis_timestamp': analysis_result.analysis_timestamp,
                'passed_verification': analysis_result.passed_verification,
                'error': analysis_result.error,
                # Champs calculés pour compatibilité legacy
                'total_risks': sum(len(risks) for risks in analysis_result.risk_indicators.values()) if analysis_result.risk_indicators else 0,
                'critical_risk_count': len(analysis_result.risk_indicators.get('critical', [])) if analysis_result.risk_indicators else 0,
                'high_risk_count': len(analysis_result.risk_indicators.get('high', [])) if analysis_result.risk_indicators else 0,
                'medium_risk_count': len(analysis_result.risk_indicators.get('medium', [])) if analysis_result.risk_indicators else 0,
                'low_risk_count': len(analysis_result.risk_indicators.get('low', [])) if analysis_result.risk_indicators else 0,
                'rugcheck_version': '2.0'
            }
        except Exception as e:
            self.logger.error(f"Error converting AnalysisResult to dict: {e}")
            # Retourner un dict minimal en cas d'erreur
            return {
                'token_address': getattr(analysis_result, 'token_address', ''),
                'safety_score': getattr(analysis_result, 'safety_score', 0.0),
                'analysis_timestamp': time.time(),
                'error': f"Conversion error: {e}"
            }

    def _make_rugcheck_request_with_circuit_breaker(self, token_address: str):
        """Requête avec circuit breaker avancé"""
        try:
            return self.circuit_breaker.call(self._make_rugcheck_request, token_address)
        except CircuitBreakerError as e:
            self.logger.warning(f"Circuit breaker blocked request for {token_address}: {e}")
            raise Exception(f"Service temporarily unavailable: {e}")

    def get_circuit_breaker_stats(self):
        """Retourne les statistiques du circuit breaker"""
        return self.circuit_breaker.get_stats()

    def _record_performance_metrics(self, token_address: str, duration: float, success: bool):
        """Enregistre les métriques de performance"""
        if not hasattr(self, '_performance_metrics'):
            self._performance_metrics = {
                'request_times': [],
                'success_count': 0,
                'error_count': 0,
                'last_updated': time.time()
            }
        
        self._performance_metrics['request_times'].append(duration)
        if success:
            self._performance_metrics['success_count'] += 1
        else:
            self._performance_metrics['error_count'] += 1
        
        # Garder seulement les 100 dernières mesures
        max_metrics = self.analysis_thresholds.max_performance_metrics
        if len(self._performance_metrics['request_times']) > max_metrics:
            self._performance_metrics['request_times'] = self._performance_metrics['request_times'][-max_metrics:]


    def _validate_api_response(self, response_data: Dict) -> bool:
        """Valide la structure de la réponse API"""
        if not isinstance(response_data, dict):
            return False
        
        # Vérification des champs obligatoires
        required_fields = ['token']
        for field in required_fields:
            if field not in response_data:
                return False
        
        # Vérification de la structure du token
        token_data = response_data.get('token', {})
        if not isinstance(token_data, dict):
            return False
        
        return True


    async def analyze_token_safety_async(self, token_address: str) -> AnalysisResult:
        """Version asynchrone de l'analyse de sécurité"""
        if not self._validate_address_format(token_address):
            return AnalysisResult(
                token_address=token_address,
                token_symbol="INVALID",
                token_name="Invalid Address",
                safety_score=0.0,
                safety_rating=SafetyRating.UNKNOWN,
                is_safe=False,
                bundle_detected=False,
                bundle_confidence=0.0,
                risk_indicators={},
                analysis_timestamp=time.time(),
                passed_verification=False,
                error="Invalid token address format"
            )
        
        # Vérification du cache
        cache_key = self.get_cache_key(token_address)
        cached_result = self.cache_manager.get_from_cache(cache_key)
        if cached_result:
            return AnalysisResult(**cached_result) if isinstance(cached_result, dict) else cached_result
        
        async with self._request_semaphore:
            try:
                response_data = await self._make_async_request(token_address)
                if response_data is None:
                    return self._create_error_result("API request failed", token_address)
                
                result = self._parse_rugcheck_response(response_data, token_address)
                self._cache_result(cache_key, result)
                return AnalysisResult(**result) if isinstance(result, dict) else result
                
            except Exception as e:
                self.logger.error(f"Error in async analysis for {token_address}: {e}")
                return self._create_error_result(str(e), token_address)

    async def _make_async_request(self, token_address: str) -> Optional[Dict]:
        """Requête asynchrone améliorée avec gestion d'erreurs robuste"""
        url = f"{self.base_url}/tokens/{token_address}/report"
        
        timeout = aiohttp.ClientTimeout(total=self.config['api_timeout'])
        connector = aiohttp.TCPConnector(limit=10, limit_per_host=5)
        
        async with aiohttp.ClientSession(
            timeout=timeout, 
            connector=connector
        ) as session:
            
            for attempt in range(self.config['retry_attempts']):
                try:
                    if attempt > 0:
                        await asyncio.sleep(self.config['retry_delay'] * attempt)
                    
                    async with session.get(
                        url,
                        headers=self._get_request_headers()
                    ) as response:
                        
                        if response.status == 200:
                            return await response.json()
                        elif response.status == 429:
                            # Rate limiting avec backoff exponentiel
                            await asyncio.sleep(2 ** attempt)
                            continue
                        elif response.status == 404:
                            self.logger.warning(f"Token not found: {token_address}")
                            return None
                        else:
                            self.logger.warning(f"Unexpected status {response.status}")
                            
                except asyncio.TimeoutError:
                    self.logger.warning(f"Timeout on attempt {attempt + 1}")
                except aiohttp.ClientError as e:
                    self.logger.warning(f"Request error on attempt {attempt + 1}: {e}")
        
        return None

    def _get_request_headers(self) -> Dict[str, str]:
        """Génère les headers pour les requêtes"""
        return {
            'User-Agent': 'DexScreener-Bot/2.0',
            'Accept': 'application/json',
            'X-Request-ID': f'dsbot_{int(time.time())}'
        }

    def _make_rugcheck_request(self, token_address):
        """Make request to RugCheck API with comprehensive retry logic"""
        session = requests.Session()
        session.timeout = self.config['api_timeout']
        url = f"{self.base_url}/tokens/{token_address}/report"

        # Déterminer le réseau pour les métriques
        network = self._detect_network(token_address)

        if self.advanced_logger:
            self.advanced_logger.debug_step('api_calls', 'rugcheck_request_start', 
                                           f'🌐 RUGCHECK API: Starting request for {token_address[:8]}...')
        
        self.logger.info(f"RugCheck API URL: {url}") #Debug

        for attempt in range(self.config['retry_attempts']):
            try:
                start_time = time.time()
                
                if attempt > 0:
                    delay = self.config['retry_delay'] * attempt
                    if self.advanced_logger:
                        self.advanced_logger.debug_step('api_calls', 'rugcheck_retry_delay', 
                                                       f'⏳ RUGCHECK: Waiting {delay}s before retry {attempt + 1}')
                    time.sleep(delay)

                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'application/json',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                    'Sec-Fetch-Dest': 'empty',
                    'Sec-Fetch-Mode': 'cors',
                    'Sec-Fetch-Site': 'cross-site'
                }

                response = self._session.get(
                    url, 
                    timeout=self.config['api_timeout'],
                    headers=headers,
                    verify=True
                )
                
                duration = time.time() - start_time
                
                self.logger.info(f"RugCheck API Response: {response.status_code} in {duration:.3f}s")

                # Log du contenu de réponse pour debug
                if response.status_code != 200:
                    self.logger.warning(f"RugCheck API Error Content: {response.text[:500]}")


                # Enregistrer les métriques de santé
                self.health_metrics.record_api_call(
                    endpoint=f"/tokens/*/report",  # Pattern générique pour grouper
                    network=network,
                    response_time=duration * 1000,  # Convertir en millisecondes
                    status_code=response.status_code,
                    success=(response.status_code == 200)
                )

                if self.advanced_logger:
                    self.advanced_logger.log_api_call('api_calls', url, 'GET', response.status_code, duration)
                
                if response.status_code == 200:
                    if self.advanced_logger:
                        self.advanced_logger.debug_step('api_calls', 'rugcheck_success', 
                                                       f'✅ RUGCHECK API: Success for {token_address[:8]}... in {duration:.3f}s')
                    # ✅ Validation du JSON de réponse
                    try:
                        json_response = response.json()
                        
                        # Vérifier que la réponse contient les champs attendus
                        if not isinstance(json_response, dict):
                            self.logger.warning(f"RugCheck API returned invalid JSON format")
                            return None
                        
                        # Log des champs principaux pour debug
                        self.logger.info(f"RugCheck response fields: {list(json_response.keys())[:10]}")
                        
                        return json_response
                        
                    except ValueError as e:
                        self.logger.error(f"RugCheck API returned invalid JSON: {e}")
                        return None
                
                elif response.status_code == 400:  # Bad Request
                    # ✅ Gestion améliorée de l'erreur 400
                    try:
                        error_json = response.json()
                        error_msg = error_json.get('error', 'Unknown error')
                        self.logger.warning(f"RugCheck API 400 - Error: {error_msg}")
                    except:
                        self.logger.warning(f"RugCheck API 400 - Raw response: {response.text[:200]}")
                    
                    if self.advanced_logger:
                        self.advanced_logger.debug_step('api_calls', 'rugcheck_bad_request', 
                                                    f'Bad Request (400) for {token_address[:8]}...')
                    
                    # Ne pas retry sur 400 - c'est généralement un problème d'adresse
                    self.logger.warning(f"RugCheck API returned 400 for {token_address} - skipping retries")
                    return None

                elif response.status_code == 429:  # Rate limited
                    # Rate limiting
                    if self.advanced_logger:
                        self.advanced_logger.debug_step('api_calls', 'rugcheck_rate_limited', 
                                                    f'Rate limited, attempt {attempt + 1}')
                    self.logger.warning(f"Rate limited by RugCheck, attempt {attempt + 1}")
                    
                    # Regarder les headers de rate limiting
                    retry_after = response.headers.get('Retry-After')
                    if retry_after:
                        try:
                            sleep_time = int(retry_after)
                            self.logger.info(f"RugCheck rate limit - waiting {sleep_time}s as per Retry-After header")
                            time.sleep(sleep_time)
                        except ValueError:
                            time.sleep(self.config['rate_limit_delay'] * (attempt + 1))
                    else:
                        time.sleep(self.config['rate_limit_delay'] * (attempt + 1))
                    continue
                    
                elif response.status_code == 404:
                    if self.advanced_logger:
                        self.advanced_logger.debug_step('api_calls', 'rugcheck_not_found', 
                                                       f'❌ RUGCHECK API: Token not found: {token_address[:8]}...')
                    self.logger.warning(f"Token not found on RugCheck: {token_address}")
                    return None
                    
                else:
                    self.logger.warning(f"RugCheck API returned unexpected status {response.status_code} for {token_address}")
                    
            except requests.exceptions.Timeout:

                duration = time.time() - start_time

                # Enregistrer timeout dans les métriques
                self.health_metrics.record_api_call(
                    endpoint=f"/tokens/*/report",
                    network=network,
                    response_time=duration * 1000,
                    status_code=408,  # Request Timeout
                    success=False
                )

                if self.advanced_logger:
                    self.advanced_logger.debug_step('api_calls', 'rugcheck_timeout', 
                                                   f'⏰ RUGCHECK API: Timeout, attempt {attempt + 1}')
                self.logger.warning(f"RugCheck API timeout, attempt {attempt + 1}")
            

            except requests.exceptions.ConnectionError as e:
                duration = time.time() - start_time
                self.health_metrics.record_api_call(
                    endpoint=f"/tokens/*/report",
                    network=network,
                    response_time=duration * 1000,
                    status_code=0,
                    success=False
                )

                self.logger.warning(f"RugCheck API connection error: {e}, attempt {attempt + 1}")

            except requests.exceptions.RequestException as e:

                duration = time.time() - start_time

                # Enregistrer erreur de connexion dans les métriques
                self.health_metrics.record_api_call(
                    endpoint=f"/tokens/*/report",
                    network=network,
                    response_time=duration * 1000,
                    status_code=0,  # Connection error
                    success=False
                )

                if self.advanced_logger:
                    self.advanced_logger.debug_step('api_calls', 'rugcheck_request_error', 
                                                   f'❌ RUGCHECK API: Request failed: {e}, attempt {attempt + 1}')
                self.logger.warning(f"RugCheck API request failed: {e}, attempt {attempt + 1}")

        # ✅ Après tous les échecs, essayer le fallback si activé
        self.logger.warning(f"RugCheck API failed for {token_address}, trying fallback...")

        # Appeler le fallback si disponible
        fallback_response = self._create_fallback_response(token_address)
        if fallback_response:
            self.logger.info(f"Using fallback data for {token_address[:8]}...")
            return fallback_response

        # Enregistrer l'échec final après tous les essais
        final_duration = time.time() - start_time if 'start_time' in locals() else 0
        self.health_metrics.record_api_call(
            endpoint=f"/tokens/*/report",
            network=network,
            response_time=final_duration * 1000,
            status_code=500,  # Internal error après tous les échecs
            success=False
        )

        if self.advanced_logger:
            self.advanced_logger.debug_step('api_calls', 'rugcheck_all_retries_failed', 
                                           f'💀 RUGCHECK API: All retries failed for {token_address[:8]}...')

        self.logger.error(f"RugCheck API: All retries failed for {token_address}")
        return None

    def _parse_rugcheck_response(self, response_data, token_address):
        """Parse RugCheck API response into standardized analysis format"""
        try:
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'rugcheck_parse_start', 
                                               f'📋 RUGCHECK: Parsing response for {token_address[:8]}...')
            
            # Extract main safety information
            token_info = response_data.get('token', {})
            risks = response_data.get('risks', [])
            markets = response_data.get('markets', [])
            
            # Calculate comprehensive safety score
            safety_score = self._calculate_safety_score_improved(risks)
            safety_rating = self._get_safety_rating(safety_score)
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'rugcheck_safety_calculated', 
                                               f'🎯 RUGCHECK: Safety calculated - Score: {safety_score:.3f}, Rating: {safety_rating}')
            
            # Advanced bundle detection analysis
            bundle_analysis = self._advanced_bundle_detection(response_data, token_address)
            
            if bundle_analysis[0] and self.advanced_logger:  # bundle_analysis returns (detected, confidence, indicators)
                self.advanced_logger.debug_step('analysis', 'rugcheck_bundle_detected', 
                                               f'📦 RUGCHECK: BUNDLE DETECTED - Confidence: {bundle_analysis[1]:.3f}')
            
            # Extract and categorize risk indicators
            risk_indicators = self._extract_risk_indicators(risks)
            
            # Analyze market data for additional insights
            market_analysis = self._analyze_market_data(markets)
            
            # Determine if token passes verification
            passed_verification = (
                safety_rating == self.config.get('required_safety_score', 'Good') and
                not bundle_analysis[0] and
                self._passes_risk_thresholds(risk_indicators)
            )
            
            analysis = {
                'token_address': token_info.get('address', token_address).lower(),
                'token_symbol': token_info.get('symbol', 'UNKNOWN'),
                'token_name': token_info.get('name', 'Unknown'),
                'safety_score': safety_score,
                'safety_rating': safety_rating,
                'is_safe': safety_rating == 'Good',
                'bundle_detected': bundle_analysis[0],
                'bundle_confidence': bundle_analysis[1],
                'bundle_indicators': bundle_analysis[2],
                'risk_indicators': risk_indicators,
                'market_analysis': market_analysis,
                'total_risks': len(risks),
                'high_risk_count': len([r for r in risks if r.get('level') == 'high']),
                'medium_risk_count': len([r for r in risks if r.get('level') == 'medium']),
                'low_risk_count': len([r for r in risks if r.get('level') == 'low']),
                'critical_risk_count': len([r for r in risks if r.get('level') == 'critical']),
                'rugcheck_data': response_data,  # Store full response for detailed analysis
                'analysis_timestamp': datetime.now().timestamp(),
                'passed_verification': passed_verification,
                'rugcheck_version': response_data.get('version', '1.0')
            }
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'rugcheck_parse_complete', 
                                               f'✅ RUGCHECK: Parsing complete - {len(risks)} risks, {len(markets)} markets')
            
            return analysis
            
        except Exception as e:
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'rugcheck_parse_error', 
                                               f'❌ RUGCHECK: Parse error: {e}')
            self.logger.error(f"Error parsing RugCheck response: {e}")
            return self._create_failed_result(f"Parse error: {str(e)}", token_address)

    def _calculate_safety_score_improved(self, risks: List[Dict]) -> float:
        """Calcul amélioré du score de sécurité avec pondération dynamique"""
        if not risks:
            return 1.0
        
        total_risk_impact = 0.0
        risk_count_by_level = {}
        
        for risk in risks:
            try:
                risk_level = RiskLevel(risk.get('level', 'low').lower())
            except ValueError:
                risk_level = RiskLevel.LOW
                
            risk_count_by_level[risk_level] = risk_count_by_level.get(risk_level, 0) + 1
            
            base_weight = self.risk_weights[risk_level]
            
            # Pondération dynamique basée sur la catégorie
            category_multiplier = self._get_category_multiplier(risk.get('category', ''))
            
            # Pondération basée sur le nombre de risques du même niveau
            frequency_penalty = min(self.analysis_thresholds.max_frequency_penalty, 1 + (risk_count_by_level[risk_level] - 1) * self.analysis_thresholds.frequency_penalty_factor)
            risk_impact = base_weight * category_multiplier * frequency_penalty
            total_risk_impact += risk_impact
        
        # Application d'une fonction sigmoïde pour une courbe plus naturelle
        safety_score = 1 / (1 + total_risk_impact)
        return max(self.analysis_thresholds.safety_score_floor, min(self.analysis_thresholds.safety_score_ceiling, safety_score))

    def _get_category_multiplier(self, category: str) -> float:
        """Multiplicateur basé sur la catégorie de risque"""
        category_multipliers = {
            'honeypot': 2.0,
            'rug': 1.8,
            'liquidity': 1.5,
            'ownership': 1.3,
            'trading': 1.2,
            'general': 1.0
        }
        
        category_lower = category.lower()
        for key, multiplier in category_multipliers.items():
            if key in category_lower:
                return multiplier
        return 1.0

    def _calculate_safety_score(self, risks):
        """Calculate comprehensive safety score from risk analysis (legacy method)"""
        if not risks:
            return 1.0
            
        # Advanced risk weighting based on RugCheck methodology
        risk_weights = {
            'critical': 0.8,    # Critical risks heavily penalize score
            'high': 0.4,        # High risks significantly impact score
            'medium': 0.2,      # Medium risks moderately impact score
            'low': 0.1,         # Low risks slightly impact score
            'info': 0.05        # Informational risks minimal impact
        }
        
        total_risk_score = 0
        for risk in risks:
            risk_level = risk.get('level', 'low').lower()
            weight = risk_weights.get(risk_level, 0.1)
            
            # Additional weighting based on risk category
            risk_category = risk.get('category', '').lower()
            if 'honeypot' in risk_category or 'rug' in risk_category:
                weight *= 1.5  # Amplify critical security risks
            elif 'liquidity' in risk_category:
                weight *= 1.3  # Liquidity risks are important
            elif 'ownership' in risk_category:
                weight *= 1.2  # Ownership risks matter
            
            total_risk_score += weight
            
        # Convert to 0-1 scale (higher = safer)
        safety_score = max(0, 1 - min(total_risk_score, 1))
        return safety_score

    def _get_safety_rating(self, safety_score):
        """Convert numerical score to human-readable rating"""
        if safety_score >= 0.85:
            return 'Good'
        elif safety_score >= 0.65:
            return 'Warning'
        elif safety_score >= 0.45:
            return 'Caution'
        else:
            return 'Dangerous'

    def _passes_risk_thresholds(self, risk_indicators):
        """Check if token passes configured risk thresholds"""
        critical_count = len(risk_indicators.get('critical', []))
        high_count = len(risk_indicators.get('high', []))
        medium_count = len(risk_indicators.get('medium', []))
        low_count = len(risk_indicators.get('low', []))
        
        return (
            critical_count <= self.risk_thresholds.critical_max and
            high_count <= self.risk_thresholds.high_max and
            medium_count <= self.risk_thresholds.medium_max and
            low_count <= self.risk_thresholds.low_max
        )

    def _advanced_bundle_detection(self, response_data: Dict, token_address: str) -> Tuple[bool, float, List[str]]:
        """
        Détection de bundle améliorée avec machine learning basique
        
        Analyzes multiple indicators to detect coordinated token launches:
        - Creator history and patterns
        - Launch timing analysis
        - Market behavior patterns
        - Metadata similarities
        """
        indicators = []
        confidence_scores = []
        
        try:
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'rugcheck_bundle_analysis_start', 
                                               f'🔍 RUGCHECK: Starting bundle analysis for {token_address[:8]}...')
            
            # Analyse des patterns de création
            creator_analysis = self._analyze_creator_patterns_improved(response_data)
            if creator_analysis['suspicious']:
                indicators.extend(creator_analysis['indicators'])
                confidence_scores.append(creator_analysis['confidence'])
            
            # Analyse des métadonnées
            metadata_analysis = self._analyze_metadata_patterns(response_data)
            if metadata_analysis['suspicious']:
                indicators.extend(metadata_analysis['indicators'])
                confidence_scores.append(metadata_analysis['confidence'])
            
            # Analyse des patterns de trading
            trading_analysis = self._analyze_trading_patterns_improved(response_data)
            if trading_analysis['suspicious']:
                indicators.extend(trading_analysis['indicators'])
                confidence_scores.append(trading_analysis['confidence'])
            
            # Calcul de confiance composite avec pondération
            if confidence_scores:
                # Moyenne pondérée avec bonus pour multiple indicators
                weighted_confidence = sum(confidence_scores) / len(confidence_scores)
                multiple_indicator_bonus = min(self.analysis_thresholds.multiple_indicator_bonus_cap, (len(confidence_scores) - 1) * self.analysis_thresholds.multiple_indicator_bonus_factor)
                final_confidence = min(1.0, weighted_confidence + multiple_indicator_bonus)
            else:
                final_confidence = 0.0
            
            detected = final_confidence > self.config.get('bundle_detection_threshold', 0.6)
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'rugcheck_bundle_analysis_complete', 
                                               f'📊 RUGCHECK: Bundle analysis complete - Detected: {detected}, Confidence: {final_confidence:.3f}')
            
            return detected, final_confidence, indicators
            
        except Exception as e:
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'rugcheck_bundle_analysis_error', 
                                               f'❌ RUGCHECK: Bundle analysis error: {e}')
            self.logger.error(f"Error in advanced bundle detection: {e}")
            return False, 0.0, []

    def _analyze_creator_patterns_improved(self, response_data: Dict) -> Dict:
        """Analyse améliorée des patterns de créateur avec protection contre division par zéro"""
        creator_info = response_data.get('token', {}).get('creator', {})
        other_tokens = creator_info.get('other_tokens', [])
        
        suspicious = False
        confidence = 0.0
        indicators = []
        
        if len(other_tokens) > 20:  # Créateur très prolifique
            suspicious = True
            confidence += self.analysis_thresholds.prolific_creator_confidence
            indicators.append(f"Créateur très prolifique: {len(other_tokens)} tokens")
        
        #  Analyse temporelle avancée avec protection complète contre les erreurs
        if len(other_tokens) >= 3:
            launch_times = [token.get('created_at', 0) for token in other_tokens[-10:]]
            # Filtrer les timestamps valides (> 0)
            launch_times = [t for t in launch_times if t > 0]
            
            if len(launch_times) >= 3:
                # Calculer les intervalles entre lancements
                intervals = []
                sorted_times = sorted(launch_times)
            
                for i in range(1, len(sorted_times)):
                    interval = sorted_times[i] - sorted_times[i-1]
                    # ✅ PROTECTION : Ignorer les intervalles négatifs ou nuls
                    if interval > 0:
                        intervals.append(interval)
                
                # ✅ PROTECTION : Vérifier qu'on a des intervalles valides
                if len(intervals) >= 2:  # Au moins 2 intervalles pour calculer variance
                
                    # ✅ PROTECTION : Calcul sécurisé de la moyenne
                    avg_interval = sum(intervals) / len(intervals)
                    
                    # 🐛 BUG ORIGINAL : Division par zéro potentielle
                    # if variance < avg_interval * self.analysis_thresholds.variance_threshold:
                
                    # ✅ CORRECTION : Protection contre avg_interval = 0
                    if avg_interval > 0:  # Protection principale
                        
                        # Calcul de la variance
                        variance = sum((x - avg_interval) ** 2 for x in intervals) / len(intervals)
                        
                        # Calcul du ratio variance/moyenne pour normaliser
                        variance_ratio = variance / avg_interval
                        
                        # Seuil basé sur le ratio plutôt que sur la valeur absolue
                        if variance_ratio < self.analysis_thresholds.variance_threshold:
                            suspicious = True
                            confidence += self.analysis_thresholds.regular_timing_confidence
                            indicators.append(f"Lancements à intervalles très réguliers (variance ratio: {variance_ratio:.4f})")
                            
                            # ✅ BONUS : Détecter les intervalles suspects
                            avg_hours = avg_interval / 3600  # Convertir en heures
                            if avg_hours < 1:  # Moins d'1h entre lancements
                                confidence += 0.1
                                indicators.append(f"Intervalles très rapides: {avg_hours:.2f}h en moyenne")
                            elif avg_hours < 24:  # Moins d'1 jour
                                confidence += 0.05
                                indicators.append(f"Intervalles rapides: {avg_hours:.2f}h en moyenne")
                
                    else:
                        # ✅ CAS EDGE : Intervalles simultanés (timestamp identiques)
                        if all(interval == 0 for interval in intervals if interval == 0):
                            suspicious = True
                            confidence += 0.3
                            indicators.append("Lancements simultanés détectés (timestamps identiques)")
            
                # ✅ ANALYSE COMPLÉMENTAIRE : Détecter les patterns temporels suspects
                if len(intervals) >= 1:
                    # Analyser la distribution des intervalles
                    unique_intervals = set(intervals)
                    
                    # Si tous les intervalles sont identiques = très suspect
                    if len(unique_intervals) == 1 and len(intervals) >= 3:
                        suspicious = True
                        confidence += 0.25
                        indicators.append("Intervalles parfaitement identiques (pattern de bot)")
                    
                    # Si très peu de variations = suspect
                    elif len(unique_intervals) <= max(2, len(intervals) // 3):
                        suspicious = True
                        confidence += 0.15
                        indicators.append("Très peu de variation dans les intervalles")
    
        # ✅ PROTECTION : Plafonner la confiance
        confidence = min(confidence, 1.0)
        
        return {
            'suspicious': suspicious,
            'confidence': confidence,
            'indicators': indicators
        }

    def _analyze_metadata_patterns(self, response_data: Dict) -> Dict:
        """Analyse des patterns de métadonnées"""
        token_info = response_data.get('token', {})
        token_name = token_info.get('name', '').lower()
        token_symbol = token_info.get('symbol', '').lower()
        description = token_info.get('description', '').lower()
        
        suspicious = False
        confidence = 0.0
        indicators = []
        
        # Check for bundle naming patterns
        for keyword in self.bundle_patterns.naming_keywords:
            if keyword in token_name or keyword in token_symbol:
                suspicious = True
                confidence += self.analysis_thresholds.metadata_pattern_confidence
                indicators.append(f"Suspicious naming pattern: '{keyword}'")
                break
        
        # Check for template-like descriptions
        if len(description) > 10:
            for indicator in self.bundle_patterns.template_indicators:
                if indicator in description:
                    suspicious = True
                    confidence += self.analysis_thresholds.template_indicator_confidence
                    indicators.append(f"Template-like description contains '{indicator}'")
                    break
        
        return {
            'suspicious': suspicious,
            'confidence': confidence,
            'indicators': indicators
        }

    def _analyze_trading_patterns_improved(self, response_data: Dict) -> Dict:
        """Analyse améliorée des patterns de trading"""
        markets = response_data.get('markets', [])
        suspicious = False
        confidence = 0.0
        indicators = []
        
        for market in markets:
            # Check for coordinated initial trading
            initial_traders = market.get('initial_traders', [])
            if len(initial_traders) > 1:
                # Look for wallet address patterns
                similar_addresses = 0
                for i, trader1 in enumerate(initial_traders):
                    for trader2 in initial_traders[i+1:]:
                        # Validation des adresses avant comparaison
                        if (isinstance(trader1, str) and isinstance(trader2, str) and len(trader1) >= 4 and len(trader2) >= 4):
                            # Simple similarity check (first/last 4 chars)
                            if (trader1[:4] == trader2[:4] or trader1[-4:] == trader2[-4:]):
                                similar_addresses += 1
                
                if similar_addresses > 0:
                    suspicious = True
                    confidence += self.analysis_thresholds.coordinated_trading_confidence
                    indicators.append(f"{similar_addresses} similar initial trader addresses")
        
        return {
            'suspicious': suspicious,
            'confidence': confidence,
            'indicators': indicators
        }

    def _analyze_bundle_indicators(self, response_data, token_address):
        """
        Advanced bundle/coordinated launch detection (legacy method for compatibility)
        
        Analyzes multiple indicators to detect coordinated token launches:
        - Creator history and patterns
        - Launch timing analysis
        - Market behavior patterns
        - Metadata similarities
        """
        bundle_indicators = []
        confidence = 0.0
        
        try:
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'rugcheck_bundle_analysis_start', 
                                               f'🔍 RUGCHECK: Starting bundle analysis for {token_address[:8]}...')
            
            # Analyze creator patterns
            creator_info = response_data.get('token', {}).get('creator', {})
            if creator_info:
                creator_address = creator_info.get('address', '')
                other_tokens = creator_info.get('other_tokens', [])
                
                if len(other_tokens) > self.bundle_patterns.creator_thresholds['prolific_creator']:
                    bundle_indicators.append(f"Creator launched {len(other_tokens)} tokens")
                    confidence += 0.4
                    if self.advanced_logger:
                        self.advanced_logger.debug_step('analysis', 'rugcheck_prolific_creator', 
                                                       f'📈 RUGCHECK: Prolific creator detected - {len(other_tokens)} tokens')
                
                # Analyze launch timing patterns
                if len(other_tokens) >= self.bundle_patterns.creator_thresholds['rapid_launch_count']:
                    recent_launches = []
                    current_time = datetime.now().timestamp()
                    
                    for token in other_tokens:
                        created_at = token.get('created_at')
                        if created_at and (current_time - created_at) < self.bundle_patterns.creator_thresholds['rapid_launch_window']:
                            recent_launches.append(created_at)
                    
                    if len(recent_launches) >= self.bundle_patterns.creator_thresholds['rapid_launch_count']:
                        bundle_indicators.append(f"{len(recent_launches)} tokens launched in 7 days")
                        confidence += 0.5
                        if self.advanced_logger:
                            self.advanced_logger.debug_step('analysis', 'rugcheck_rapid_launches', 
                                                           f'🚀 RUGCHECK: Rapid launches detected - {len(recent_launches)} in 7 days')
                        
                        # Check for very rapid launches (within hours)
                        if len(recent_launches) >= 2:
                            launch_intervals = []
                            sorted_launches = sorted(recent_launches)
                            for i in range(1, len(sorted_launches)):
                                interval = sorted_launches[i] - sorted_launches[i-1]
                                launch_intervals.append(interval)
                            
                            avg_interval = sum(launch_intervals) / len(launch_intervals)
                            if avg_interval < self.bundle_patterns.creator_thresholds['suspicious_interval']:
                                bundle_indicators.append(f"Tokens launched {avg_interval/60:.1f} minutes apart on average")
                                confidence += 0.3
                                if self.advanced_logger:
                                    self.advanced_logger.debug_step('analysis', 'rugcheck_rapid_succession', 
                                                                   f'⚡ RUGCHECK: Very rapid succession - {avg_interval/60:.1f} min avg')
            
            # Analyze market behavior patterns
            markets = response_data.get('markets', [])
            for market in markets:
                # Check for coordinated initial trading
                initial_traders = market.get('initial_traders', [])
                if len(initial_traders) > 1:
                    # Look for wallet address patterns
                    similar_addresses = 0
                    for i, trader1 in enumerate(initial_traders):
                        for trader2 in initial_traders[i+1:]:
                            # Simple similarity check (first/last 4 chars)
                            if (trader1[:4] == trader2[:4] or trader1[-4:] == trader2[-4:]):
                                similar_addresses += 1
                    
                    if similar_addresses > 0:
                        bundle_indicators.append(f"{similar_addresses} similar initial trader addresses")
                        confidence += 0.3
                        if self.advanced_logger:
                            self.advanced_logger.debug_step('analysis', 'rugcheck_coordinated_traders', 
                                                           f'👥 RUGCHECK: Coordinated traders detected - {similar_addresses} similarities')
            
            # Check token metadata patterns
            token_info = response_data.get('token', {})
            token_name = token_info.get('name', '').lower()
            token_symbol = token_info.get('symbol', '').lower()
            
            # Check for bundle naming patterns
            for keyword in self.bundle_patterns.naming_keywords:
                if keyword in token_name or keyword in token_symbol:
                    bundle_indicators.append(f"Suspicious naming pattern: '{keyword}'")
                    confidence += 0.2
                    if self.advanced_logger:
                        self.advanced_logger.debug_step('analysis', 'rugcheck_suspicious_naming', 
                                                       f'🏷️ RUGCHECK: Suspicious naming - contains "{keyword}"')
                    break
            
            # Check for identical or very similar descriptions
            description = token_info.get('description', '').lower()
            if len(description) > 10:
                # Check for template-like descriptions
                for indicator in self.bundle_patterns.template_indicators:
                    if indicator in description:
                        bundle_indicators.append(f"Template-like description contains '{indicator}'")
                        confidence += 0.15
                        break
            
        except Exception as e:
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'rugcheck_bundle_analysis_error', 
                                               f'❌ RUGCHECK: Bundle analysis error: {e}')
            self.logger.error(f"Error analyzing bundle indicators: {e}")
            
        detected = confidence > self.config.get('bundle_detection_threshold', 0.5)
        
        if self.advanced_logger:
            self.advanced_logger.debug_step('analysis', 'rugcheck_bundle_analysis_complete', 
                                           f'📊 RUGCHECK: Bundle analysis complete - Detected: {detected}, Confidence: {confidence:.3f}')
        
        return {
            'detected': detected,
            'confidence': min(confidence, 1.0),
            'indicators': bundle_indicators
        }

    def _extract_risk_indicators(self, risks):
        """Extract and categorize risk indicators by severity"""
        risk_indicators = {
            'critical': [],
            'high': [],
            'medium': [],
            'low': [],
            'info': []
        }
        
        for risk in risks:
            level = risk.get('level', 'low').lower()
            description = risk.get('description', 'Unknown risk')
            risk_type = risk.get('type', 'general')
            category = risk.get('category', 'unknown')
            
            risk_info = {
                'type': risk_type,
                'category': category,
                'description': description,
                'details': risk.get('details', {}),
                'severity_score': self._calculate_risk_severity(risk)
            }
            
            if level in risk_indicators:
                risk_indicators[level].append(risk_info)
            else:
                risk_indicators['low'].append(risk_info)
                
        return risk_indicators

    def _calculate_risk_severity(self, risk):
        """Calculate numerical severity score for a risk"""
        base_scores = {
            'critical': 1.0,
            'high': 0.8,
            'medium': 0.6,
            'low': 0.4,
            'info': 0.2
        }
        
        level = risk.get('level', 'low').lower()
        base_score = base_scores.get(level, 0.4)
        
        # Adjust based on category
        category = risk.get('category', '').lower()
        if 'honeypot' in category or 'rug' in category:
            base_score *= 1.5
        elif 'liquidity' in category:
            base_score *= 1.2
        elif 'ownership' in category:
            base_score *= 1.1
        
        return min(base_score, 1.0)

    def _analyze_market_data(self, markets):
        """Analyze market trading data for additional security insights"""
        analysis = {
            'total_markets': len(markets),
            'suspicious_patterns': [],
            'liquidity_analysis': {},
            'trading_analysis': {},
            'security_score': 1.0
        }
        
        try:
            total_liquidity = 0
            total_volume = 0
            suspicious_score = 0
            
            for market in markets:
                # Analyze liquidity patterns
                liquidity = market.get('liquidity', {})
                if liquidity:
                    liquidity_usd = liquidity.get('usd', 0)
                    total_liquidity += liquidity_usd
                    
                    if liquidity_usd < self.analysis_thresholds.low_liquidity_threshold:
                        analysis['suspicious_patterns'].append("Very low liquidity detected")
                        suspicious_score += 0.3
                
                # Analyze trading volume
                volume = market.get('volume', {})
                if volume:
                    volume_24h = volume.get('h24', 0)
                    total_volume += volume_24h
                
                # Analyze initial trading patterns
                initial_trades = market.get('initial_trades', [])
                if len(initial_trades) > 5:
                    # Check for bot-like trading patterns
                    trade_amounts = [t.get('amount', 0) for t in initial_trades[:10]]
                    if len(set(trade_amounts)) <= 2:  # Very similar trade amounts
                        analysis['suspicious_patterns'].append("Repetitive initial trade amounts")
                        suspicious_score += 0.2
                
                # Check for rapid successive trades
                trade_times = [t.get('timestamp', 0) for t in initial_trades[:5]]
                if len(trade_times) >= 3:
                    intervals = []
                    for i in range(1, len(trade_times)):
                        if trade_times[i] > trade_times[i-1]:
                            intervals.append(trade_times[i] - trade_times[i-1])
                    
                    if intervals and all(interval < self.analysis_thresholds.rapid_trade_window for interval in intervals):
                        analysis['suspicious_patterns'].append("Rapid successive initial trades")
                        suspicious_score += 0.25
            
            # Calculate overall security score
            analysis['security_score'] = max(0, 1 - suspicious_score)
            analysis['liquidity_analysis'] = {
                'total_liquidity': total_liquidity,
                'average_liquidity': total_liquidity / max(len(markets), 1),
                'liquidity_distribution': self._analyze_liquidity_distribution(markets)
            }
            analysis['trading_analysis'] = {
                'total_volume': total_volume,
                'volume_to_liquidity_ratio': total_volume / max(total_liquidity, 1),
                'trading_patterns': self._analyze_trading_patterns(markets)
            }
            
        except Exception as e:
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'rugcheck_market_analysis_error', 
                                               f'❌ RUGCHECK: Market analysis error: {e}')
            self.logger.error(f"Error analyzing market data: {e}")
            
        return analysis

    def _analyze_liquidity_distribution(self, markets):
        """Analyze how liquidity is distributed across markets"""
        if not markets:
            return {'distribution_score': 0, 'concentration_risk': 'unknown'}
        
        liquidities = [market.get('liquidity', {}).get('usd', 0) for market in markets]
        total_liquidity = sum(liquidities)
        
        if total_liquidity == 0:
            return {'distribution_score': 0, 'concentration_risk': 'no_liquidity'}
        
        # Calculate concentration (Gini coefficient-like measure)
        sorted_liquidities = sorted(liquidities, reverse=True)
        concentration = sorted_liquidities[0] / total_liquidity if len(sorted_liquidities) > 0 else 0
        
        if concentration > self.analysis_thresholds.high_concentration_threshold:
            risk_level = 'high'
        elif concentration > self.analysis_thresholds.medium_concentration_threshold:
            risk_level = 'medium'
        else:
            risk_level = 'low'
        
        return {
            'distribution_score': 1 - concentration,
            'concentration_risk': risk_level,
            'dominant_market_share': concentration,
            'market_count': len(markets)
        }

    def _analyze_trading_patterns(self, markets):
        """Analyze trading patterns for suspicious behavior"""
        patterns = {
            'bot_trading_detected': False,
            'coordinated_trading': False,
            'unusual_volumes': False,
            'pattern_confidence': 0.0
        }
        
        for market in markets:
            trades = market.get('initial_trades', [])
            if len(trades) < 3:
                continue
            
            # Check for bot-like regular intervals
            timestamps = [t.get('timestamp', 0) for t in trades[:10]]
            if len(timestamps) >= 3:
                intervals = []
                for i in range(1, len(timestamps)):
                    if timestamps[i] > timestamps[i-1]:
                        intervals.append(timestamps[i] - timestamps[i-1])
                
                if intervals:
                    avg_interval = sum(intervals) / len(intervals)
                    # Very regular intervals suggest bot trading
                    tolerance = avg_interval * self.analysis_thresholds.bot_interval_tolerance
                    if all(abs(interval - avg_interval) < tolerance for interval in intervals):
                        patterns['bot_trading_detected'] = True
                        patterns['pattern_confidence'] += 0.3
            
            # Check for coordinated large trades
            amounts = [t.get('amount', 0) for t in trades[:5]]
            if len(amounts) >= 3:
                # Similar amounts within 10% suggest coordination
                avg_amount = sum(amounts) / len(amounts)
                # Calcule correctement les montants similaires
                tolerance = avg_amount * (1 - self.analysis_thresholds.coordinated_trade_threshold)
                similar_amounts = sum(1 for amount in amounts if abs(amount - avg_amount) <= tolerance)
                if similar_amounts >= len(amounts) * self.analysis_thresholds.coordinated_trade_threshold:
                    patterns['coordinated_trading'] = True
                    patterns['pattern_confidence'] += 0.4
        
        return patterns

    def _create_failed_result(self, reason, token_address=""):
        """Create standardized failed analysis result"""
        return {
            'token_address': token_address.lower() if token_address else '',
            'token_symbol': 'UNKNOWN',
            'token_name': 'Unknown',
            'safety_score': 0.0,
            'safety_rating': 'Unknown',
            'is_safe': False,
            'bundle_detected': False,
            'bundle_confidence': 0.0,
            'bundle_indicators': [],
            'risk_indicators': {'critical': [], 'high': [], 'medium': [], 'low': [], 'info': []},
            'market_analysis': {
                'total_markets': 0,
                'suspicious_patterns': [],
                'liquidity_analysis': {},
                'trading_analysis': {},
                'security_score': 0.0
            },
            'total_risks': 0,
            'high_risk_count': 0,
            'medium_risk_count': 0,
            'low_risk_count': 0,
            'critical_risk_count': 0,
            'analysis_timestamp': datetime.now().timestamp(),
            'passed_verification': False,
            'error': reason,
            'rugcheck_version': 'unknown'
        }

    def _create_error_result(self, reason, token_address=""):
        """Create standardized error result for AnalysisResult"""
        return AnalysisResult(
            token_address=token_address.lower() if token_address else '',
            token_symbol='UNKNOWN',
            token_name='Unknown',
            safety_score=0.0,
            safety_rating=SafetyRating.UNKNOWN,
            is_safe=False,
            bundle_detected=False,
            bundle_confidence=0.0,
            risk_indicators={'critical': [], 'high': [], 'medium': [], 'low': [], 'info': []},
            analysis_timestamp=time.time(),
            passed_verification=False,
            error=reason
        )

    def _cache_result(self, cache_key, result):
        """Cache RugCheck analysis result with expiration - Version corrigée"""

        # ✅ CORRECTION : Initialiser cache_type avec une valeur par défaut sûre
        cache_type = 'unknown'
        operation_start_time = time.time()

        try:
            # ✅ SÉCURITÉ : Récupérer le type de cache de manière défensive
            try:
                cache_type = self.cache_manager.strategy.value
            except (AttributeError, TypeError) as e:
                # Fallback si cache_manager ou strategy n'est pas disponible
                self.logger.debug(f"Could not determine cache strategy, using fallback: {e}")
                cache_type = 'legacy'
            
            # ✅ VALIDATION : Vérifier que le cache_manager existe
            if not hasattr(self, 'cache_manager') or self.cache_manager is None:
                self.logger.warning("Cache manager not available, skipping cache operation")
                return
            
            # ✅ VALIDATION : Vérifier la validité du cache_key
            if not cache_key or not isinstance(cache_key, str):
                self.logger.warning(f"Invalid cache key: {cache_key}")
                return
            
            # ✅ VALIDATION : Vérifier que result n'est pas None
            if result is None:
                self.logger.warning("Attempted to cache None result, skipping")
                return
            
            # 🐛 BUG ORIGINAL : cache_type peut ne pas être défini en cas d'exception
            # try:
            #     self.cache_manager.store_in_cache(cache_key, result)
            #     cache_type = self.cache_manager.strategy.value  # ❌ Trop tard !
            #     self.health_metrics.record_cache_operation('SET', True, cache_type)
            # except Exception as e:
            #     cache_type = getattr(self.cache_manager, 'strategy', CacheStrategy.LEGACY).value  # ❌ Peut échouer
            
            # ✅ CORRECTION : Stocker dans le cache avec gestion robuste
            self.cache_manager.store_in_cache(cache_key, result)
            
            # ✅ SUCCÈS : Enregistrer les métriques de cache
            if hasattr(self, 'health_metrics') and self.health_metrics:
                self.health_metrics.record_cache_operation('SET', True, cache_type)
            
            # ✅ LOGGING : Enregistrer l'opération de cache réussie
            if hasattr(self, 'advanced_logger') and self.advanced_logger:
                cache_key_short = cache_key.split('_')[1][:8] if '_' in cache_key else cache_key[:8]
                self.advanced_logger.log_cache_operation(
                    'cache', 'SET', 
                    cache_key_short, 
                    hit=True
                )
            
            # ✅ MÉTRIQUES : Enregistrer le temps d'opération
            operation_duration = time.time() - operation_start_time
            if operation_duration > 0.1:  # Log si l'opération prend plus de 100ms
                self.logger.debug(f"Cache operation took {operation_duration:.3f}s for key {cache_key[:20]}...")
        
        except AttributeError as e:
            # ✅ SPÉCIFIQUE : Erreur d'attribut (cache_manager manquant, etc.)
            self.logger.warning(f"Cache manager attribute error for {cache_key[:20]}...: {e}")
            
            # Enregistrer l'échec avec fallback sûr
            cache_type = 'unavailable'
            if hasattr(self, 'health_metrics') and self.health_metrics:
                self.health_metrics.record_cache_operation('SET', False, cache_type)
        
        except TypeError as e:
            # ✅ SPÉCIFIQUE : Erreur de type (result non sérialisable, etc.)
            self.logger.warning(f"Cache type error for {cache_key[:20]}... (result type: {type(result).__name__}): {e}")
            
            # Tentative de conversion du résultat
            try:
                if hasattr(result, 'to_dict'):
                    serializable_result = result.to_dict()
                    self.cache_manager.store_in_cache(cache_key, serializable_result)
                    
                    if hasattr(self, 'health_metrics') and self.health_metrics:
                        self.health_metrics.record_cache_operation('SET', True, cache_type)
                    
                    self.logger.debug(f"Successfully cached result after conversion to dict")
                    return
                    
            except Exception as conversion_error:
                self.logger.warning(f"Failed to convert result to cacheable format: {conversion_error}")
            
            # Enregistrer l'échec final
            if hasattr(self, 'health_metrics') and self.health_metrics:
                self.health_metrics.record_cache_operation('SET', False, cache_type)
        
        except MemoryError as e:
            # ✅ SPÉCIFIQUE : Erreur de mémoire
            self.logger.error(f"Memory error caching result for {cache_key[:20]}...: {e}")
            
            # Essayer de nettoyer le cache pour libérer la mémoire
            try:
                self.clear_expired_cache()
                self.logger.info("Cache cleanup performed due to memory error")
            except Exception as cleanup_error:
                self.logger.error(f"Failed to cleanup cache after memory error: {cleanup_error}")
            
            cache_type = 'memory_error'
            if hasattr(self, 'health_metrics') and self.health_metrics:
                self.health_metrics.record_cache_operation('SET', False, cache_type)
        
        except Exception as e:
            # ✅ FALLBACK : Gestion robuste pour toute autre erreur
            error_type = type(e).__name__
            self.logger.warning(f"Unexpected cache error ({error_type}) for {cache_key[:20]}...: {e}")
            
            # ✅ CORRECTION : Fallback sûr pour obtenir cache_type
            try:
                if hasattr(self, 'cache_manager') and self.cache_manager:
                    if hasattr(self.cache_manager, 'strategy'):
                        cache_type = getattr(self.cache_manager.strategy, 'value', 'unknown')
                    else:
                        cache_type = 'no_strategy'
                else:
                    cache_type = 'no_manager'
            except Exception:
                # Dernier fallback absolument sûr
                cache_type = 'error_fallback'
            
            # Enregistrer l'échec avec type sûr
            if hasattr(self, 'health_metrics') and self.health_metrics:
                try:
                    self.health_metrics.record_cache_operation('SET', False, cache_type)
                except Exception as metrics_error:
                    # Si même les métriques échouent, log seulement
                    self.logger.error(f"Failed to record cache metrics: {metrics_error}")
            
            # Advanced logger avec protection
            if hasattr(self, 'advanced_logger') and self.advanced_logger:
                try:
                    cache_key_short = cache_key.split('_')[1][:8] if '_' in cache_key and len(cache_key) > 8 else cache_key[:8]
                    self.advanced_logger.log_cache_operation(
                        'cache', 'SET', 
                        cache_key_short, 
                        hit=False
                    )
                except Exception as logger_error:
                    # Si le logging avancé échoue, continuer silencieusement
                    pass

    # ✅ MÉTHODE AUXILIAIRE : Validation du cache avant stockage
    def _validate_cache_data(self, result) -> Tuple[bool, str]:
        """Valide les données avant mise en cache"""
        try:
            # Vérifier que result n'est pas None
            if result is None:
                return False, "Result is None"
            
            # Vérifier la taille approximative (éviter les objets trop gros)
            try:
                import sys
                size = sys.getsizeof(result)
                max_size = 10 * 1024 * 1024  # 10MB max
                if size > max_size:
                    return False, f"Result too large: {size} bytes"
            except Exception:
                pass  # Ignorer si on ne peut pas calculer la taille
            
            # Vérifier que le résultat est sérialisable (test rapide)
            if isinstance(result, (dict, list, str, int, float, bool, type(None))):
                return True, "Valid basic type"
            
            # Pour les objets personnalisés, vérifier to_dict
            if hasattr(result, 'to_dict') and callable(getattr(result, 'to_dict')):
                return True, "Has to_dict method"
            
            # Essayer une sérialisation rapide
            try:
                import json
                json.dumps(result, default=str)  # Test avec fallback string
                return True, "JSON serializable"
            except Exception as e:
                return False, f"Not serializable: {e}"
                
        except Exception as e:
            return False, f"Validation error: {e}"

    # ✅ MÉTHODE AUXILIAIRE : Cache avec retry
    def _cache_result_with_retry(self, cache_key, result, max_retries=2):
        """Version avec retry pour les cas où le cache est temporairement indisponible"""
        
        for attempt in range(max_retries + 1):
            try:
                # Valider avant de tenter la mise en cache
                is_valid, validation_msg = self._validate_cache_data(result)
                if not is_valid:
                    self.logger.debug(f"Cache validation failed: {validation_msg}")
                    return False
                
                # Tenter la mise en cache
                self._cache_result(cache_key, result)
                return True
                
            except Exception as e:
                if attempt < max_retries:
                    wait_time = 0.1 * (2 ** attempt)  # Backoff exponentiel
                    self.logger.debug(f"Cache attempt {attempt + 1} failed, retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)
                else:
                    self.logger.warning(f"All cache attempts failed for {cache_key[:20]}...: {e}")
                    return False
        
        return False

    def _validate_address_format(self, token_address: str) -> bool:
        with self._address_cache_lock:
            if token_address in self._address_cache:
                return self._address_cache[token_address]
            
            result = self._validate_address_format_cached(token_address)
            self._address_cache[token_address] = result
            return result


    @functools.lru_cache(maxsize=1000)
    def _validate_address_format_cached(self, token_address: str) -> bool:
        """
        Validation améliorée des formats d'adresse avec cache et meilleure performance
        
        Supports:
       - Ethereum/BSC/Polygon (EVM compatible): 0x + 40 hex chars
        - Solana: 32-44 base58 chars (exactly 32 bytes when decoded)
        - Tron: 34 base58 chars starting with 'T' (25 bytes when decoded)
        """
        if not token_address or not isinstance(token_address, str):
            return False
        
        token_address = token_address.strip()
        
        # Validation rapide de la longueur
        addr_len = len(token_address)
        if addr_len < 32:  # Trop court pour tout format supporté
            return False
        
        # Ethereum/BSC/Polygon (EVM compatible)
        if addr_len == 42 and token_address.startswith('0x'):
            return bool(self._ETH_ADDRESS_PATTERN.match(token_address))
        
        # Solana - validation optimisée
        elif 32 <= addr_len <= 44 and not token_address.startswith('0x'):
            
            
            # ✅ CORRECTION : Gestion d'erreurs spécifique et robuste
            if HAS_BASE58:
                try:
                    # Validation préalable des caractères base58
                    if not all(c in self._BASE58_CHARS for c in token_address):
                        return False
                    
                    # Tentative de décodage base58
                    decoded = base58.b58decode(token_address)
                    
                    # Solana public keys sont exactement 32 bytes
                    return len(decoded) == 32
                    
                except ValueError as e:
                    # ✅ SPÉCIFIQUE : Erreur de décodage base58 (caractères invalides, etc.)
                    if self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug(f"Invalid base58 format for Solana address {token_address[:8]}...: {e}")
                    return False
                    
                except TypeError as e:
                    # ✅ SPÉCIFIQUE : Erreur de type (None, etc.)
                    if self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug(f"Type error validating Solana address {token_address[:8]}...: {e}")
                    return False
                    
                except OverflowError as e:
                    # ✅ SPÉCIFIQUE : Adresse trop longue pour le décodage
                    if self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug(f"Overflow error for Solana address {token_address[:8]}...: {e}")
                    return False
                    
                except MemoryError as e:
                    # ✅ SPÉCIFIQUE : Adresse provoquant un problème mémoire
                    self.logger.warning(f"Memory error validating Solana address {token_address[:8]}...: {e}")
                    return False
                    
                except Exception as e:
                    # ✅ FALLBACK : Log pour déboguer les erreurs inattendues
                    self.logger.warning(f"Unexpected error validating Solana address {token_address[:8]}...: {type(e).__name__}: {e}")
                    return False
            else:
                # ✅ FALLBACK : Validation sans bibliothèque base58
                # Vérification plus stricte des caractères
                if not all(c in self._BASE58_CHARS for c in token_address):
                    return False
                
                # Vérifications additionnelles pour Solana
                # Les adresses Solana évitent certains patterns
                if token_address.startswith('1111') or token_address.endswith('1111'):
                    return False  # Pattern suspect
                
                # Vérification de longueur plus stricte sans décodage
                # Solana addresses sont généralement 43-44 caractères
                return 43 <= addr_len <= 44
        
        # Tron - validation avec gestion d'erreurs améliorée
        elif addr_len == 34 and token_address.startswith('T'):
            
            if HAS_BASE58:
                try:
                    # Validation préalable des caractères base58
                    if not all(c in self._BASE58_CHARS for c in token_address):
                        return False
                    
                    decoded = base58.b58decode(token_address)
                    # Tron addresses sont exactement 25 bytes (21 + 4 checksum)
                    is_valid_length = len(decoded) == 25
                    
                    # ✅ BONUS : Validation basique du checksum Tron
                    if is_valid_length and len(decoded) >= 4:
                        # Vérification que c'est bien une adresse Tron (commence par 0x41)
                        return decoded[0] == 0x41
                    
                    return is_valid_length
                    
                except (ValueError, TypeError) as e:
                    # ✅ SPÉCIFIQUE : Erreurs de décodage attendues
                    if self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug(f"Invalid Tron address format {token_address[:8]}...: {e}")
                    return False
                    
                except Exception as e:
                    # ✅ FALLBACK : Log pour les erreurs inattendues
                    self.logger.warning(f"Unexpected error validating Tron address {token_address[:8]}...: {type(e).__name__}: {e}")
                    return False
            else:
                # Fallback sans base58
                return all(c in self._BASE58_CHARS for c in token_address)
        
        # ✅ VALIDATION SUPPLÉMENTAIRE : Détecter les formats suspects
        # Adresses avec patterns répétitifs (potentiellement fakées)
        if len(set(token_address)) < 4:  # Moins de 4 caractères uniques
            return False
        
        # Adresses avec trop de répétitions consécutives
        max_consecutive = max(len(list(group)) for char, group in __import__('itertools').groupby(token_address))
        if max_consecutive > 10:  # Plus de 10 caractères identiques consécutifs
            return False

        return False


    # ✅ MÉTHODE AUXILIAIRE : Validation rapide sans cache pour tests
    def _validate_address_format_no_cache(self, token_address: str) -> bool:
        """Version sans cache pour les tests ou validations ponctuelles"""
        # Temporairement désactiver le cache
        original_func = self._validate_address_format_cached
        
        # Appeler la version non cachée
        return self._validate_address_format_cached.__wrapped__(self, token_address)

    # ✅ MÉTHODE AUXILIAIRE : Nettoyage du cache de validation
    def clear_address_validation_cache(self):
        """Nettoie le cache de validation d'adresses"""
        try:
            self._validate_address_format_cached.cache_clear()
            if hasattr(self, '_address_cache'):
                with self._address_cache_lock:
                    self._address_cache.clear()
            
            self.logger.debug("Address validation cache cleared")
            return True
        except Exception as e:
            self.logger.warning(f"Failed to clear address validation cache: {e}")
            return False

    # ✅ MÉTHODE AUXILIAIRE : Statistiques du cache
    def get_address_validation_stats(self):
        """Retourne les statistiques du cache de validation d'adresses"""
        try:
            cache_info = self._validate_address_format_cached.cache_info()
            return {
                'hits': cache_info.hits,
                'misses': cache_info.misses,
                'current_size': cache_info.currsize,
                'max_size': cache_info.maxsize,
                'hit_rate': cache_info.hits / (cache_info.hits + cache_info.misses) if (cache_info.hits + cache_info.misses) > 0 else 0
            }
        except Exception as e:
            self.logger.warning(f"Failed to get cache stats: {e}")
            return {}


    def is_token_safe(self, token_address):
        """Quick safety check for token"""
        analysis = self.analyze_token_safety(token_address)
        return (analysis.get('is_safe', False) and 
                not analysis.get('bundle_detected', False) and
                analysis.get('passed_verification', False))

    def get_bundle_tokens(self):
        """Get list of tokens identified as bundles"""
        bundle_tokens = []
        current_time = datetime.now()
        
        # Check both cache systems for compatibility
        if hasattr(self, 'cache') and hasattr(self, 'cache_expiry'):
            for cache_key, result in self.cache.items():
                if (cache_key in self.cache_expiry and 
                    current_time < self.cache_expiry[cache_key] and
                    result.get('bundle_detected', False)):
                    bundle_tokens.append(result)
        
        return bundle_tokens

    def get_dangerous_tokens(self):
        """Get list of tokens identified as dangerous"""
        dangerous_tokens = []
        current_time = datetime.now()
        
        # Check both cache systems for compatibility
        if hasattr(self, 'cache') and hasattr(self, 'cache_expiry'):
            for cache_key, result in self.cache.items():
                if (cache_key in self.cache_expiry and 
                    current_time < self.cache_expiry[cache_key] and
                    result.get('safety_rating', '') == 'Dangerous'):
                    dangerous_tokens.append(result)
        
        return dangerous_tokens

    def get_analysis_stats(self):
        """Get comprehensive RugCheck analysis statistics"""
        current_time = datetime.now()
        stats = {
            'total_analyses': 0,
            'verified_tokens': 0,
            'bundles_detected': 0,
            'dangerous_tokens': 0,
            'average_safety_score': 0,
            'cache_size': len(getattr(self, 'cache', {})),
            'safety_ratings': {'Good': 0, 'Warning': 0, 'Caution': 0, 'Dangerous': 0, 'Unknown': 0},
            'risk_distribution': {'critical': 0, 'high': 0, 'medium': 0, 'low': 0, 'info': 0},
            'bundle_confidence_avg': 0.0
        }
        
        total_score = 0
        total_bundle_confidence = 0
        valid_analyses = 0
        
        # Use legacy cache if available for compatibility
        cache_to_use = getattr(self, 'cache', {})
        cache_expiry_to_use = getattr(self, 'cache_expiry', {})
        
        for cache_key, result in cache_to_use.items():
            if cache_key in cache_expiry_to_use and current_time < cache_expiry_to_use[cache_key]:
                valid_analyses += 1
                
                # Count by verification status
                if result.get('passed_verification', False):
                    stats['verified_tokens'] += 1
                
                # Count bundles
                if result.get('bundle_detected', False):
                    stats['bundles_detected'] += 1
                    total_bundle_confidence += result.get('bundle_confidence', 0)
                
                # Count dangerous tokens
                if result.get('safety_rating') == 'Dangerous':
                    stats['dangerous_tokens'] += 1
                
                # Safety ratings distribution
                rating = result.get('safety_rating', 'Unknown')
                if rating in stats['safety_ratings']:
                    stats['safety_ratings'][rating] += 1
                
                # Risk distribution
                risk_indicators = result.get('risk_indicators', {})
                for level, risks in risk_indicators.items():
                    if level in stats['risk_distribution']:
                        stats['risk_distribution'][level] += len(risks)
                
                # Average safety score
                score = result.get('safety_score', 0)
                total_score += score
        
        stats['total_analyses'] = valid_analyses
        stats['average_safety_score'] = total_score / max(valid_analyses, 1)
        stats['bundle_confidence_avg'] = total_bundle_confidence / max(stats['bundles_detected'], 1)
        
        return stats

    def clear_expired_cache(self):
        """Clear expired cache entries to free memory"""
        cleared_count = 0
        
        # Clear legacy cache if available
        if hasattr(self, 'cache') and hasattr(self, 'cache_expiry'):
            current_time = datetime.now()
            expired_keys = [
                key for key, expiry_time in self.cache_expiry.items()
                if current_time >= expiry_time
            ]
            
            for key in expired_keys:
                self.cache.pop(key, None)
                self.cache_expiry.pop(key, None)
            
            cleared_count += len(expired_keys)
        
        # Clear weak cache if available
        if hasattr(self.cache_manager, '_weak_cache_timestamps'):
            current_time = time.time()
            cache_duration = self.cache_manager.cache_duration_hours * 3600
            
            expired_keys = [
                key for key, timestamp in self.cache_manager._weak_cache_timestamps.items()
                if current_time - timestamp > cache_duration
            ]
            
            for key in expired_keys:
                self.cache_manager._weak_cache_timestamps.pop(key, None)
                # WeakValueDictionary se nettoie automatiquement
            
            cleared_count += len(expired_keys)
        
        if self.advanced_logger and cleared_count > 0:
            self.advanced_logger.debug_step('cache', 'rugcheck_cache_cleanup', 
                                           f'Cleared {cleared_count} expired RugCheck cache entries')
        
        return cleared_count

    def export_analysis_results(self, include_full_data=False):
        """Export RugCheck analysis results for backup/analysis"""
        export_data = {
            'export_timestamp': datetime.now().isoformat(),
            'rugcheck_config': self.config,
            'total_analyses': len(getattr(self, 'cache', {})),
            'analyses': []
        }
        
        current_time = datetime.now()
        cache_to_use = getattr(self, 'cache', {})
        cache_expiry_to_use = getattr(self, 'cache_expiry', {})
        
        for cache_key, result in cache_to_use.items():
            if cache_key in cache_expiry_to_use and current_time < cache_expiry_to_use[cache_key]:
                export_item = {
                    'token_address': result.get('token_address'),
                    'token_symbol': result.get('token_symbol'),
                    'safety_rating': result.get('safety_rating'),
                    'safety_score': result.get('safety_score'),
                    'bundle_detected': result.get('bundle_detected'),
                    'bundle_confidence': result.get('bundle_confidence'),
                    'analysis_timestamp': result.get('analysis_timestamp')
                }
                
                if include_full_data:
                    export_item['full_analysis'] = result
                
                export_data['analyses'].append(export_item)
        
        filename = f"rugcheck_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(filename, 'w') as f:
            json.dump(export_data, f, indent=2, default=lambda x: str(x) if isinstance(x, (datetime, timedelta)) else None)
            
        self.logger.info(f"Exported RugCheck analysis results to {filename}")
        return filename

    async def batch_analyze_optimized(self, token_addresses: List[str]) -> Dict:
        """Analyse par lot optimisée avec traitement asynchrone"""
        semaphore = asyncio.Semaphore(self.config.get('batch_concurrent_limit', 10))
        
        async def analyze_with_semaphore(address):
            async with semaphore:
                return await self.analyze_token_safety_async(address)
        
        # Filtrer les adresses invalides avant traitement
        valid_addresses = [addr for addr in token_addresses if self._validate_address_format(addr)]
        
        if len(valid_addresses) != len(token_addresses):
            self.logger.warning(f"Filtered out {len(token_addresses) - len(valid_addresses)} invalid addresses")
        
        # Traitement concurrent
        tasks = [analyze_with_semaphore(addr) for addr in valid_addresses]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Compilation des résultats
        processed_results = {}
        for addr, result in zip(valid_addresses, results):
            if isinstance(result, Exception):
                processed_results[addr] = self._create_error_result(str(result), addr)
            else:
                processed_results[addr] = result
        
        return {
            'results': processed_results,
            'summary': self._generate_batch_summary_improved(processed_results),
            'metadata': {
                'total_requested': len(token_addresses),
                'valid_addresses': len(valid_addresses),
                'successful_analyses': len([r for r in processed_results.values() if not getattr(r, 'error', None)]),
                'timestamp': time.time()
            }
        }

    def _generate_batch_summary_improved(self, results: Dict) -> Dict:
        """Generate improved summary statistics for batch analysis"""
        summary = {
            'total_analyzed': len(results),
            'safety_distribution': defaultdict(int),
            'bundle_detection': {
                'total_bundles': 0,
                'high_confidence_bundles': 0,
                'bundle_rate': 0.0
            },
            'risk_summary': {
                'safe_tokens': 0,
                'dangerous_tokens': 0,
                'tokens_with_critical_risks': 0
            },
            'verification_summary': {
                'passed_verification': 0,
                'failed_verification': 0,
                'verification_rate': 0.0
            }
        }
        
        for token_addr, result in results.items():
            # Handle both dict and AnalysisResult objects
            if isinstance(result, AnalysisResult):
                result_dict = {
                    'safety_rating': result.safety_rating.value if hasattr(result.safety_rating, 'value') else str(result.safety_rating),
                    'bundle_detected': result.bundle_detected,
                    'bundle_confidence': result.bundle_confidence,
                    'is_safe': result.is_safe,
                    'passed_verification': result.passed_verification
                }
            else:
                result_dict = result
            
            # Safety distribution
            rating = result_dict.get('safety_rating', 'Unknown')
            summary['safety_distribution'][rating] += 1
            
            # Bundle detection
            if result_dict.get('bundle_detected', False):
                summary['bundle_detection']['total_bundles'] += 1
                if result_dict.get('bundle_confidence', 0) > 0.8:
                    summary['bundle_detection']['high_confidence_bundles'] += 1
            
            # Risk summary
            if result_dict.get('is_safe', False):
                summary['risk_summary']['safe_tokens'] += 1
            elif result_dict.get('safety_rating') == 'Dangerous':
                summary['risk_summary']['dangerous_tokens'] += 1
            
            # Verification summary
            if result_dict.get('passed_verification', False):
                summary['verification_summary']['passed_verification'] += 1
            else:
                summary['verification_summary']['failed_verification'] += 1
        
        # Calculate rates
        total = max(len(results), 1)
        summary['bundle_detection']['bundle_rate'] = summary['bundle_detection']['total_bundles'] / total
        summary['verification_summary']['verification_rate'] = summary['verification_summary']['passed_verification'] / total
        
        return summary

    def batch_analyze_tokens(self, token_addresses, max_concurrent=3):
        """
        Analyze multiple tokens concurrently with rate limiting (legacy method)
        """
        results = {}
        semaphore = threading.Semaphore(max_concurrent)
        
        def analyze_single_token(token_address):
            with semaphore:
                try:
                    result = self.analyze_token_safety(token_address)
                    return token_address, result
                except Exception as e:
                    self.logger.error(f"Batch analysis error for {token_address}: {e}")
                    return token_address, self._create_failed_result(f"Batch analysis error: {str(e)}", token_address)

        # Process tokens concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            future_to_token = {
                executor.submit(analyze_single_token, addr): addr 
                for addr in token_addresses
            }
            
            for future in concurrent.futures.as_completed(future_to_token):
                token_address, result = future.result()
                results[token_address] = result

        # Generate batch summary
        summary = self._generate_batch_summary(results)
        
        if self.advanced_logger:
            self.advanced_logger.debug_step('analysis', 'rugcheck_batch_complete', 
                                           f'🔍 RUGCHECK BATCH: Analyzed {len(results)} tokens', 
                                           summary)

        return {
            'individual_results': results,
            'batch_summary': summary,
            'analysis_metadata': {
                'total_tokens': len(token_addresses),
                'successful_analyses': len([r for r in results.values() if 'error' not in r]),
                'failed_analyses': len([r for r in results.values() if 'error' in r]),
                'timestamp': datetime.now().isoformat(),
                'rugcheck_version': '2.0'
            }
        }

    def _generate_batch_summary(self, results):
        """Generate summary statistics for batch analysis (legacy method)"""
        summary = {
            'total_analyzed': len(results),
            'safety_distribution': defaultdict(int),
            'bundle_detection': {
                'total_bundles': 0,
                'high_confidence_bundles': 0,
                'bundle_rate': 0.0
            },
            'risk_summary': {
                'safe_tokens': 0,
                'dangerous_tokens': 0,
                'tokens_with_critical_risks': 0
            },
            'verification_summary': {
                'passed_verification': 0,
                'failed_verification': 0,
                'verification_rate': 0.0
            }
        }
        
        for token_addr, result in results.items():
            # Safety distribution
            rating = result.get('safety_rating', 'Unknown')
            summary['safety_distribution'][rating] += 1
            
            # Bundle detection
            if result.get('bundle_detected', False):
                summary['bundle_detection']['total_bundles'] += 1
                if result.get('bundle_confidence', 0) > 0.8:
                    summary['bundle_detection']['high_confidence_bundles'] += 1
            
            # Risk summary
            if result.get('is_safe', False):
                summary['risk_summary']['safe_tokens'] += 1
            elif result.get('safety_rating') == 'Dangerous':
                summary['risk_summary']['dangerous_tokens'] += 1
            
            if result.get('critical_risk_count', 0) > 0:
                summary['risk_summary']['tokens_with_critical_risks'] += 1
            
            # Verification summary
            if result.get('passed_verification', False):
                summary['verification_summary']['passed_verification'] += 1
            else:
                summary['verification_summary']['failed_verification'] += 1
        
        # Calculate rates
        total = max(len(results), 1)
        summary['bundle_detection']['bundle_rate'] = summary['bundle_detection']['total_bundles'] / total
        summary['verification_summary']['verification_rate'] = summary['verification_summary']['passed_verification'] / total
        
        return summary

    def generate_security_report(self, token_address):
        """Generate comprehensive security report for a token"""
        analysis = self.analyze_token_safety(token_address)
        
        if 'error' in analysis:
            return {
                'report_type': 'error',
                'token_address': token_address,
                'error': analysis['error'],
                'timestamp': datetime.now().isoformat()
            }
        
        # Generate detailed security report
        report = {
            'report_type': 'security_analysis',
            'token_info': {
                'address': analysis.get('token_address'),
                'symbol': analysis.get('token_symbol'),
                'name': analysis.get('token_name')
            },
            'security_assessment': {
                'overall_rating': analysis.get('safety_rating'),
                'safety_score': analysis.get('safety_score'),
                'is_safe_to_trade': analysis.get('is_safe'),
                'passed_verification': analysis.get('passed_verification')
            },
            'bundle_analysis': {
                'is_bundle': analysis.get('bundle_detected'),
                'confidence': analysis.get('bundle_confidence'),
                'indicators': analysis.get('bundle_indicators', [])
            },
            'risk_analysis': {
                'total_risks': analysis.get('total_risks'),
                'risk_breakdown': {
                    'critical': analysis.get('critical_risk_count'),
                    'high': analysis.get('high_risk_count'),
                    'medium': analysis.get('medium_risk_count'),
                    'low': analysis.get('low_risk_count')
                },
                'risk_details': analysis.get('risk_indicators', {})
            },
            'market_analysis': analysis.get('market_analysis', {}),
            'recommendations': self._generate_recommendations(analysis),
            'report_metadata': {
                'generated_at': datetime.now().isoformat(),
                'rugcheck_version': analysis.get('rugcheck_version'),
                'analysis_timestamp': analysis.get('analysis_timestamp')
            }
        }
        
        return report

    def _generate_recommendations(self, analysis):
        """Generate trading recommendations based on analysis"""
        recommendations = []
        
        safety_rating = analysis.get('safety_rating')
        bundle_detected = analysis.get('bundle_detected', False)
        critical_risks = analysis.get('critical_risk_count', 0)
        high_risks = analysis.get('high_risk_count', 0)
        
        if safety_rating == 'Dangerous' or critical_risks > 0:
            recommendations.append({
                'type': 'AVOID',
                'priority': 'HIGH',
                'message': 'Do not trade this token - critical security risks detected'
            })
        elif bundle_detected and analysis.get('bundle_confidence', 0) > 0.8:
            recommendations.append({
                'type': 'AVOID',
                'priority': 'HIGH',
                'message': 'Likely bundle launch - high probability of coordinated manipulation'
            })
        elif safety_rating == 'Caution' or high_risks > 2:
            recommendations.append({
                'type': 'EXTREME_CAUTION',
                'priority': 'MEDIUM',
                'message': 'Exercise extreme caution - multiple high-risk factors present'
            })
        elif safety_rating == 'Warning':
            recommendations.append({
                'type': 'CAUTION',
                'priority': 'MEDIUM',
                'message': 'Trade with caution - some risk factors present'
            })
        elif safety_rating == 'Good' and not bundle_detected:
            recommendations.append({
                'type': 'PROCEED',
                'priority': 'LOW',
                'message': 'Token appears safe based on current analysis'
            })
        
        # Add specific recommendations based on risk types
        risk_indicators = analysis.get('risk_indicators', {})
        
        if risk_indicators.get('critical'):
            recommendations.append({
                'type': 'CRITICAL_RISKS',
                'priority': 'HIGH',
                'message': f"Critical risks found: {len(risk_indicators['critical'])} issues require immediate attention"
            })
        
        if bundle_detected:
            recommendations.append({
                'type': 'BUNDLE_WARNING',
                'priority': 'HIGH',
                'message': f"Bundle detection confidence: {analysis.get('bundle_confidence', 0):.1%}"
            })
        
        return recommendations

    def _validate_token_for_rugcheck(self, token_address: str) -> bool:
        """Valide si le token peut être analysé par RugCheck"""
        
        # Vérifier le format d'adresse
        if not self._validate_address_format(token_address):
            return False
        
        # Éviter certains tokens système qui causent des erreurs 400
        system_tokens = [
            'So11111111111111111111111111111111111111112',  # SOL (wrapped)
            '11111111111111111111111111111112',             # System Program
            'SysvarRent111111111111111111111111111111111',  # Sysvar Rent
            'SysvarC1ock11111111111111111111111111111111'   # Sysvar Clock
        ]
        
        if token_address in system_tokens:
            self.logger.debug(f"Skipping system token: {token_address}")
            return False
        
        return True

    def validate_token_address(self, token_address):
        """Validate if token address format is correct for supported networks"""
        return self._validate_address_format(token_address)

    def get_token_risk_profile(self, token_address):
        """Get simplified risk profile for quick decision making"""
        if not self.validate_token_address(token_address):
            return {'status': 'invalid_address', 'risk_level': 'unknown'}
        
        analysis = self.analyze_token_safety(token_address)
        
        # Gérer AnalysisResult correctement
        if hasattr(analysis, 'error') and analysis.error:
            return {'status': 'analysis_failed', 'risk_level': 'unknown', 'error': analysis.error}
        
        # Simplified risk assessment - Corriger l'accès aux attributs
        if isinstance(analysis, AnalysisResult):
            risk_indicators = analysis.risk_indicators or {}
        
            # Calculer les compteurs à partir des risk_indicators
            critical_risks = len(risk_indicators.get('critical', []))
            high_risks = len(risk_indicators.get('high', []))
            medium_risks = len(risk_indicators.get('medium', []))
            low_risks = len(risk_indicators.get('low', []))
            info_risks = len(risk_indicators.get('info', []))

            # Calculer le total des risques
            total_risks = critical_risks + high_risks + medium_risks + low_risks + info_risks

            # Accès direct aux attributs existants
            bundle_detected = analysis.bundle_detected
            bundle_confidence = analysis.bundle_confidence
            safety_score = analysis.safety_score
            safety_rating = analysis.safety_rating.value if hasattr(analysis.safety_rating, 'value') else str(analysis.safety_rating)
            passed_verification = analysis.passed_verification

        else:
            # Pour dict (legacy), utiliser get() avec fallback intelligent
            risk_indicators = analysis.get('risk_indicators', {})
            
            # Essayer d'abord les champs pré-calculés, sinon calculer
            critical_risks = analysis.get('critical_risk_count', len(risk_indicators.get('critical', [])))
            high_risks = analysis.get('high_risk_count', len(risk_indicators.get('high', [])))
            medium_risks = analysis.get('medium_risk_count', len(risk_indicators.get('medium', [])))
            low_risks = analysis.get('low_risk_count', len(risk_indicators.get('low', [])))
            
            # Calculer total_risks si pas disponible
            total_risks = analysis.get('total_risks', critical_risks + high_risks + medium_risks + low_risks)
            
            bundle_detected = analysis.get('bundle_detected', False)
            bundle_confidence = analysis.get('bundle_confidence', 0.0)
            safety_score = analysis.get('safety_score', 0.0)
            safety_rating = analysis.get('safety_rating', 'Unknown')
            passed_verification = analysis.get('passed_verification', False)
        
        if critical_risks > 0 or (bundle_detected and bundle_confidence > 0.8):
            risk_level = 'CRITICAL'
        elif high_risks > 2 or safety_score < 0.3:
            risk_level = 'HIGH'
        elif high_risks > 0 or safety_score < 0.6:
            risk_level = 'MEDIUM'
        elif safety_score < 0.8:
            risk_level = 'LOW'
        else:
            risk_level = 'MINIMAL'
        
        return {
            'status': 'analyzed',
            'risk_level': risk_level,
            'safety_score': safety_score,
            'bundle_detected': bundle_detected,
            'passed_verification': analysis.get('passed_verification', False),
            'risk_breakdown': {
                'critical': critical_risks,
                'high': high_risks,
                'medium': medium_risks,
                'low': low_risks,
                'total': total_risks
            },
            'quick_summary': f"{total_risks} risks, {safety_rating} rating"
        }

    # Configuration management methods
    def update_risk_thresholds(self, **kwargs):
        """Update risk thresholds dynamically"""
        for key, value in kwargs.items():
            if hasattr(self.risk_thresholds, key):
                setattr(self.risk_thresholds, key, value)
                self.logger.info(f"Updated risk threshold {key} to {value}")

    def update_analysis_thresholds(self, **kwargs):
        """Update analysis thresholds dynamically"""
        for key, value in kwargs.items():
            if hasattr(self.analysis_thresholds, key):
                setattr(self.analysis_thresholds, key, value)
                self.logger.info(f"Updated analysis threshold {key} to {value}")
            else:
                self.logger.warning(f"Unknown analysis threshold: {key}")

    def get_analysis_thresholds(self):
        """Get current analysis thresholds configuration"""
        return {
            field.name: getattr(self.analysis_thresholds, field.name)
            for field in fields(self.analysis_thresholds)
        }
    
    def add_bundle_keyword(self, keyword: str):
        """Add a new bundle detection keyword"""
        self.bundle_patterns.add_naming_keyword(keyword)
        self.logger.info(f"Added bundle detection keyword: {keyword}")

    def add_template_indicator(self, indicator: str):
        """Add a new template indicator"""
        self.bundle_patterns.add_template_indicator(indicator)
        self.logger.info(f"Added template indicator: {indicator}")

    def get_cache_info(self):
        """Get information about cache status"""
        cache_info = {
            'strategy': self.cache_manager.strategy.value,
            'legacy_cache_size': len(getattr(self, 'cache', {})),
            'weak_cache_size': len(getattr(self.cache_manager, '_weak_cache', {})),
            'max_cache_size': self.cache_manager.max_cache_size,
            'cache_duration_hours': self.cache_manager.cache_duration_hours
        }
        
        # Add expiry information if available
        if hasattr(self, 'cache_expiry'):
            current_time = datetime.now()
            valid_entries = sum(1 for expiry in self.cache_expiry.values() if current_time < expiry)
            cache_info['valid_legacy_entries'] = valid_entries
            
        return cache_info

    def migrate_cache_strategy(self, new_strategy: str):
        """Migrate to a new cache strategy"""
        try:
            new_strategy_enum = CacheStrategy(new_strategy)
            old_strategy = self.cache_manager.strategy
            
            # Create new cache manager
            new_cache_manager = ImprovedCacheManager(new_strategy_enum, self.config)
            
            # Migrate existing data if possible
            if hasattr(self, 'cache') and self.cache:
                for key, value in self.cache.items():
                    if self.is_cache_valid(key):
                        new_cache_manager.store_in_cache(key, value)
            
            # Replace cache manager
            self.cache_manager = new_cache_manager
            self._setup_legacy_compatibility()
            
            self.logger.info(f"Migrated cache strategy from {old_strategy.value} to {new_strategy_enum.value}")
            
        except ValueError as e:
            self.logger.error(f"Invalid cache strategy: {new_strategy}. Valid options: {[s.value for s in CacheStrategy]}")
            raise


# Utility functions for integration

def create_rugcheck_analyzer(config):
    """Factory function to create a RugCheck analyzer instance"""
    return RugCheckAnalyzer(config)

def quick_safety_check(token_address, config=None):
    """Quick safety check for simple integrations"""
    if config is None:
        config = {
            'rugcheck': {
                'api_base_url': 'https://api.rugcheck.xyz/v1',
                'api_timeout': 30,
                'retry_attempts': 3,
                'retry_delay': 2,
                'rate_limit_delay': 5,
                'bundle_detection_threshold': 0.5,
                'required_safety_score': 'Good',
                'cache_results_hours': 6,
                'cache_strategy': 'hybrid',
                'max_concurrent_requests': 5,
                'risk_sensitivity': 1.0,
                'risk_thresholds': {
                    'critical_max': 0,
                    'high_max': 2,
                    'medium_max': 5,
                    'low_max': 10
                }
            }
        }
    
    analyzer = RugCheckAnalyzer(config)
    return analyzer.get_token_risk_profile(token_address)

# Advanced utility functions

async def async_batch_analyze(token_addresses: List[str], config: Dict = None) -> Dict:
    """Asynchronous batch analysis utility"""
    if config is None:
        config = {
            'rugcheck': {
                'api_base_url': 'https://api.rugcheck.xyz/v1',
                'api_timeout': 30,
                'retry_attempts': 3,
                'retry_delay': 2,
                'rate_limit_delay': 5,
                'bundle_detection_threshold': 0.6,
                'required_safety_score': 'Good',
                'cache_results_hours': 6,
                'cache_strategy': 'weak_ref',
                'max_concurrent_requests': 10,
                'batch_concurrent_limit': 15,
                'risk_sensitivity': 1.0
            }
        }
    
    analyzer = RugCheckAnalyzer(config)
    return await analyzer.batch_analyze_optimized(token_addresses)

def create_custom_analyzer(
    api_base_url: str = 'https://api.rugcheck.xyz/v1',
    cache_strategy: str = 'hybrid',
    risk_sensitivity: float = 1.0,
    bundle_threshold: float = 0.6,
    **kwargs
) -> RugCheckAnalyzer:
    """Create a customized RugCheck analyzer with specific parameters"""
    
    config = {
        'rugcheck': {
            'api_base_url': api_base_url,
            'api_timeout': kwargs.get('api_timeout', 30),
            'retry_attempts': kwargs.get('retry_attempts', 3),
            'retry_delay': kwargs.get('retry_delay', 2),
            'rate_limit_delay': kwargs.get('rate_limit_delay', 5),
            'bundle_detection_threshold': bundle_threshold,
            'required_safety_score': kwargs.get('required_safety_score', 'Good'),
            'cache_results_hours': kwargs.get('cache_hours', 6),
            'cache_strategy': cache_strategy,
            'max_concurrent_requests': kwargs.get('max_concurrent', 5),
            'risk_sensitivity': risk_sensitivity,
            'risk_thresholds': kwargs.get('risk_thresholds', {
                'critical_max': 0,
                'high_max': 2,
                'medium_max': 5,
                'low_max': 10
            })
        }
    }
    
    return RugCheckAnalyzer(config)


# Example usage and testing utilities

def test_analyzer_functionality():
    """Test basic analyzer functionality"""
    config = {
        'rugcheck': {
            'api_base_url': 'https://api.rugcheck.xyz/v1',
            'api_timeout': 30,
            'retry_attempts': 2,
            'retry_delay': 1,
            'rate_limit_delay': 3,
            'bundle_detection_threshold': 0.5,
            'required_safety_score': 'Good',
            'cache_results_hours': 1,
            'cache_strategy': 'hybrid'
        }
    }
    
    analyzer = RugCheckAnalyzer(config)
    
    # Test cache info
    cache_info = analyzer.get_cache_info()
    print(f"Cache info: {cache_info}")
    
    # Test address validation
    test_addresses = [
        '0x1234567890123456789012345678901234567890',  # Valid Ethereum
        'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # Valid Solana
        'invalid_address',  # Invalid
        '0x123'  # Invalid Ethereum
    ]
    
    for addr in test_addresses:
        is_valid = analyzer.validate_token_address(addr)
        print(f"Address {addr[:20]}... is valid: {is_valid}")
    
    return analyzer

if __name__ == "__main__":
    # Example usage
    print("RugCheck Analyzer Improved - Testing...")
    
    try:
        analyzer = test_analyzer_functionality()
        print("✅ Analyzer created successfully")
        
        # Test configuration updates
        analyzer.update_risk_thresholds(high_max=3, medium_max=7)
        analyzer.add_bundle_keyword("scam")
        analyzer.add_template_indicator("fake")
        
        print("✅ Configuration updates completed")
        
    except Exception as e:
        print(f"❌ Error during testing: {e}")
        raise
