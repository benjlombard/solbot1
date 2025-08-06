
#!/usr/bin/env python3
"""
Rate Limiter adaptatif pour les requêtes RPC Solana
Gère les limites de taux avec algorithmes intelligents et adaptation automatique
"""

import time
import threading
import math
from typing import Dict, List, Optional, Any, Tuple, Callable
from dataclasses import dataclass, field
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timedelta
from enum import Enum
import logging

# Imports des modules internes
try:
    from core.config import get_config
    from core.exceptions import RPCRateLimitError, RPCError
    from core.logger import get_logger
    from utils.helpers import get_current_timestamp, CircularBuffer, exponential_backoff
    from utils.constants import (
        QUICKNODE_FREE_TIER_RPS, RPC_TIMEOUT_DEFAULT,
        OPTIMAL_BATCH_SIZES, PERFORMANCE_THRESHOLDS
    )
except ImportError as e:
    logging.warning(f"Import error in rate limiter: {e}")
    # Fallbacks pour développement
    logger = logging.getLogger(__name__)
    
    # Constantes par défaut
    QUICKNODE_FREE_TIER_RPS = 100
    RPC_TIMEOUT_DEFAULT = 15
    OPTIMAL_BATCH_SIZES = {
        'getMultipleAccounts': 100,
        'getSignaturesForAddress': 20,
        'getTransaction': 10
    }
    PERFORMANCE_THRESHOLDS = {
        'good_response_time': 1000,
        'warning_response_time': 5000,
        'critical_response_time': 15000
    }

# Configuration du logger
logger = logging.getLogger(__name__)


class RateLimitAlgorithm(Enum):
    """Algorithmes de rate limiting disponibles"""
    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"
    FIXED_WINDOW = "fixed_window"
    ADAPTIVE = "adaptive"


class RateLimitPriority(Enum):
    """Niveaux de priorité pour les requêtes"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class RateLimitConfig:
    """Configuration du rate limiter"""
    max_requests_per_second: float = 5.0
    max_requests_per_minute: float = 300.0
    max_requests_per_hour: float = 18000.0
    burst_capacity: int = 10
    algorithm: RateLimitAlgorithm = RateLimitAlgorithm.ADAPTIVE
    enable_adaptive_scaling: bool = True
    priority_multipliers: Dict[RateLimitPriority, float] = field(default_factory=lambda: {
        RateLimitPriority.LOW: 0.5,
        RateLimitPriority.NORMAL: 1.0,
        RateLimitPriority.HIGH: 1.5,
        RateLimitPriority.CRITICAL: 2.0
    })
    backoff_base: float = 2.0
    backoff_max: float = 60.0
    performance_window_size: int = 100
    adaptation_threshold: float = 0.8  # Seuil pour déclencher l'adaptation


@dataclass
class RequestMetrics:
    """Métriques d'une requête"""
    timestamp: float
    method: str
    priority: RateLimitPriority
    response_time: Optional[float] = None
    success: bool = True
    endpoint: Optional[str] = None
    retry_count: int = 0


@dataclass
class RateLimitStats:
    """Statistiques du rate limiter"""
    total_requests: int = 0
    blocked_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    avg_response_time: float = 0.0
    current_rps: float = 0.0
    burst_usage: int = 0
    adaptation_count: int = 0
    last_adaptation_time: Optional[float] = None


class TokenBucket:
    """Implémentation Token Bucket pour rate limiting"""
    
    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate  # Tokens per second
        self.tokens = float(capacity)
        self.last_refill = time.time()
        self.lock = threading.Lock()
    
    def consume(self, tokens: int = 1) -> bool:
        """Tente de consommer des tokens"""
        with self.lock:
            self._refill()
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
    
    def _refill(self):
        """Remplit le bucket avec de nouveaux tokens"""
        now = time.time()
        time_passed = now - self.last_refill
        tokens_to_add = time_passed * self.refill_rate
        
        self.tokens = min(self.capacity, self.tokens + tokens_to_add)
        self.last_refill = now
    
    def get_available_tokens(self) -> int:
        """Retourne le nombre de tokens disponibles"""
        with self.lock:
            self._refill()
            return int(self.tokens)
    
    def get_wait_time(self, tokens_needed: int = 1) -> float:
        """Calcule le temps d'attente pour obtenir les tokens nécessaires"""
        with self.lock:
            self._refill()
            
            if self.tokens >= tokens_needed:
                return 0.0
            
            tokens_deficit = tokens_needed - self.tokens
            return tokens_deficit / self.refill_rate


class SlidingWindowRateLimiter:
    """Rate limiter avec fenêtre glissante"""
    
    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = deque()
        self.lock = threading.Lock()
    
    def can_proceed(self) -> bool:
        """Vérifie si une requête peut être effectuée"""
        with self.lock:
            self._cleanup_old_requests()
            return len(self.requests) < self.max_requests
    
    def record_request(self, timestamp: Optional[float] = None):
        """Enregistre une nouvelle requête"""
        with self.lock:
            self.requests.append(timestamp or time.time())
    
    def _cleanup_old_requests(self):
        """Supprime les requêtes en dehors de la fenêtre"""
        now = time.time()
        cutoff = now - self.window_seconds
        
        while self.requests and self.requests[0] < cutoff:
            self.requests.popleft()
    
    def get_current_count(self) -> int:
        """Retourne le nombre de requêtes dans la fenêtre actuelle"""
        with self.lock:
            self._cleanup_old_requests()
            return len(self.requests)
    
    def get_wait_time(self) -> float:
        """Calcule le temps d'attente avant la prochaine requête"""
        with self.lock:
            self._cleanup_old_requests()
            
            if len(self.requests) < self.max_requests:
                return 0.0
            
            # Temps jusqu'à ce que la requête la plus ancienne sorte de la fenêtre
            oldest_request = self.requests[0]
            wait_time = (oldest_request + self.window_seconds) - time.time()
            return max(0.0, wait_time)


class AdaptiveRateLimiter:
    """Rate limiter adaptatif basé sur les performances"""
    
    def __init__(self, config: RateLimitConfig):
        self.config = config
        self.base_rps = config.max_requests_per_second
        self.current_rps = self.base_rps
        self.performance_buffer = CircularBuffer(config.performance_window_size)
        self.lock = threading.Lock()
        
        # Métriques d'adaptation
        self.adaptation_history = []
        self.last_performance_check = time.time()
        self.consecutive_good_performance = 0
        self.consecutive_bad_performance = 0
    
    def record_performance(self, response_time: float, success: bool):
        """Enregistre les performances d'une requête"""
        with self.lock:
            self.performance_buffer.append({
                'response_time': response_time,
                'success': success,
                'timestamp': time.time()
            })
            
            # Vérifier si adaptation nécessaire
            if len(self.performance_buffer) >= 10:  # Minimum d'échantillons
                self._check_adaptation_needed()
    
    def _check_adaptation_needed(self):
        """Vérifie si une adaptation du taux est nécessaire"""
        now = time.time()
        
        # Éviter les adaptations trop fréquentes
        if now - self.last_performance_check < 10:  # 10 secondes minimum
            return
        
        self.last_performance_check = now
        
        # Analyser les performances récentes
        recent_data = list(self.performance_buffer)[-20:]  # 20 dernières requêtes
        if not recent_data:
            return
        
        avg_response_time = sum(item['response_time'] for item in recent_data) / len(recent_data)
        success_rate = sum(1 for item in recent_data if item['success']) / len(recent_data)
        
        # Décider de l'adaptation
        performance_good = (
            avg_response_time < PERFORMANCE_THRESHOLDS['good_response_time'] and
            success_rate > 0.95
        )
        
        performance_bad = (
            avg_response_time > PERFORMANCE_THRESHOLDS['warning_response_time'] or
            success_rate < 0.8
        )
        
        if performance_good:
            self.consecutive_good_performance += 1
            self.consecutive_bad_performance = 0
            
            # Augmenter le taux après plusieurs bonnes performances
            if self.consecutive_good_performance >= 3:
                self._increase_rate()
                
        elif performance_bad:
            self.consecutive_bad_performance += 1
            self.consecutive_good_performance = 0
            
            # Diminuer le taux immédiatement si mauvaises performances
            self._decrease_rate()
    
    def _increase_rate(self):
        """Augmente le taux de requêtes"""
        old_rps = self.current_rps
        max_increase = self.base_rps * 2.0  # Maximum 2x le taux de base
        
        self.current_rps = min(max_increase, self.current_rps * 1.2)  # Augmentation de 20%
        
        if self.current_rps > old_rps:
            self._record_adaptation('increase', old_rps, self.current_rps)
            logger.info(f"📈 Rate limit adaptatif augmenté: {old_rps:.1f} → {self.current_rps:.1f} RPS")
    
    def _decrease_rate(self):
        """Diminue le taux de requêtes"""
        old_rps = self.current_rps
        min_rate = self.base_rps * 0.1  # Minimum 10% du taux de base
        
        self.current_rps = max(min_rate, self.current_rps * 0.7)  # Réduction de 30%
        
        if self.current_rps < old_rps:
            self._record_adaptation('decrease', old_rps, self.current_rps)
            logger.warning(f"📉 Rate limit adaptatif réduit: {old_rps:.1f} → {self.current_rps:.1f} RPS")
    
    def _record_adaptation(self, action: str, old_rate: float, new_rate: float):
        """Enregistre une adaptation du taux"""
        self.adaptation_history.append({
            'timestamp': time.time(),
            'action': action,
            'old_rate': old_rate,
            'new_rate': new_rate,
            'reason': 'performance_based'
        })
        
        # Garder seulement les 50 dernières adaptations
        if len(self.adaptation_history) > 50:
            self.adaptation_history = self.adaptation_history[-50:]
    
    def get_current_rate(self) -> float:
        """Retourne le taux actuel"""
        return self.current_rps
    
    def get_adaptation_history(self) -> List[Dict]:
        """Retourne l'historique des adaptations"""
        return self.adaptation_history.copy()


class RateLimiter:
    """Rate limiter principal avec support multi-algorithmes"""
    
    def __init__(self, config: RateLimitConfig = None, endpoint_name: str = "default"):
        self.config = config or RateLimitConfig()
        self.endpoint_name = endpoint_name
        self.stats = RateLimitStats()
        self.lock = threading.RLock()
        
        # Initialiser les différents algorithmes
        self._init_algorithms()
        
        # Buffer des requêtes récentes pour statistiques
        self.recent_requests = CircularBuffer(1000)
        
        # Historique des blocages pour analyse
        self.block_history = deque(maxlen=100)
        
        # Thread de nettoyage périodique
        self._cleanup_thread = None
        self._should_stop = threading.Event()
        self._start_cleanup_thread()
        
        logger.info(f"🛡️ Rate limiter initialisé pour {endpoint_name}")
        logger.info(f"   📊 Config: {self.config.max_requests_per_second} RPS, {self.config.algorithm.value}")
    
    def _init_algorithms(self):
        """Initialise les algorithmes de rate limiting"""
        # Token bucket pour burst capacity
        self.token_bucket = TokenBucket(
            capacity=self.config.burst_capacity,
            refill_rate=self.config.max_requests_per_second
        )
        
        # Sliding window pour les limites par minute/heure
        self.sliding_window_minute = SlidingWindowRateLimiter(
            max_requests=int(self.config.max_requests_per_minute),
            window_seconds=60
        )
        
        self.sliding_window_hour = SlidingWindowRateLimiter(
            max_requests=int(self.config.max_requests_per_hour),
            window_seconds=3600
        )
        
        # Rate limiter adaptatif
        if self.config.enable_adaptive_scaling:
            self.adaptive_limiter = AdaptiveRateLimiter(self.config)
        else:
            self.adaptive_limiter = None
    
    def can_proceed(self, priority: RateLimitPriority = RateLimitPriority.NORMAL,
                   method: str = "unknown") -> bool:
        """
        Vérifie si une requête peut être effectuée selon tous les algorithmes
        
        Args:
            priority: Priorité de la requête
            method: Nom de la méthode RPC
            
        Returns:
            True si la requête peut être effectuée
        """
        with self.lock:
            # Appliquer le multiplicateur de priorité
            priority_multiplier = self.config.priority_multipliers.get(priority, 1.0)
            effective_rps = self.config.max_requests_per_second * priority_multiplier
            
            # Vérifier selon l'algorithme principal
            can_proceed = True
            blocking_reason = None
            
            if self.config.algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
                can_proceed = self.token_bucket.consume(1)
                if not can_proceed:
                    blocking_reason = "token_bucket_exhausted"
                    
            elif self.config.algorithm == RateLimitAlgorithm.SLIDING_WINDOW:
                can_proceed = self.sliding_window_minute.can_proceed()
                if not can_proceed:
                    blocking_reason = "sliding_window_limit"
                    
            elif self.config.algorithm == RateLimitAlgorithm.ADAPTIVE:
                if self.adaptive_limiter:
                    current_rate = self.adaptive_limiter.get_current_rate() * priority_multiplier
                    # Utiliser token bucket avec le taux adaptatif
                    self.token_bucket.refill_rate = current_rate
                    can_proceed = self.token_bucket.consume(1)
                    if not can_proceed:
                        blocking_reason = "adaptive_rate_limit"
                else:
                    can_proceed = self.token_bucket.consume(1)
                    if not can_proceed:
                        blocking_reason = "token_bucket_fallback"
            
            # Vérifications additionnelles (limites par minute/heure)
            if can_proceed:
                if not self.sliding_window_minute.can_proceed():
                    can_proceed = False
                    blocking_reason = "minute_limit_exceeded"
                elif not self.sliding_window_hour.can_proceed():
                    can_proceed = False
                    blocking_reason = "hour_limit_exceeded"
            
            # Enregistrer le résultat
            if can_proceed:
                self._record_request_allowed(method, priority)
            else:
                self._record_request_blocked(method, priority, blocking_reason)
            
            return can_proceed
    
    def record_request(self, method: str = "unknown", 
                      priority: RateLimitPriority = RateLimitPriority.NORMAL,
                      response_time: Optional[float] = None,
                      success: bool = True):
        """
        Enregistre une requête effectuée (pour les statistiques et l'adaptation)
        
        Args:
            method: Nom de la méthode RPC
            priority: Priorité de la requête
            response_time: Temps de réponse en millisecondes
            success: Succès de la requête
        """
        with self.lock:
            now = time.time()
            
            # Créer les métriques de la requête
            metrics = RequestMetrics(
                timestamp=now,
                method=method,
                priority=priority,
                response_time=response_time,
                success=success,
                endpoint=self.endpoint_name
            )
            
            # Enregistrer dans le buffer
            self.recent_requests.append(metrics)
            
            # Enregistrer dans les sliding windows
            self.sliding_window_minute.record_request(now)
            self.sliding_window_hour.record_request(now)
            
            # Mettre à jour les statistiques
            self.stats.total_requests += 1
            if success:
                self.stats.successful_requests += 1
            else:
                self.stats.failed_requests += 1
            
            # Mettre à jour le temps de réponse moyen
            if response_time is not None:
                if self.stats.avg_response_time == 0:
                    self.stats.avg_response_time = response_time
                else:
                    # Moyenne mobile
                    alpha = 0.1  # Facteur de lissage
                    self.stats.avg_response_time = (
                        alpha * response_time + 
                        (1 - alpha) * self.stats.avg_response_time
                    )
            
            # Enregistrer pour l'adaptation
            if self.adaptive_limiter and response_time is not None:
                self.adaptive_limiter.record_performance(response_time, success)
            
            # Calculer le RPS actuel
            self._update_current_rps()
    
    def _record_request_allowed(self, method: str, priority: RateLimitPriority):
        """Enregistre une requête autorisée"""
        logger.debug(f"✅ Requête autorisée: {method} (priorité: {priority.name})")
    
    def _record_request_blocked(self, method: str, priority: RateLimitPriority, reason: str):
        """Enregistre une requête bloquée"""
        with self.lock:
            self.stats.blocked_requests += 1
            
            # Enregistrer dans l'historique des blocages
            self.block_history.append({
                'timestamp': time.time(),
                'method': method,
                'priority': priority.name,
                'reason': reason
            })
        
        logger.warning(f"🛑 Requête bloquée: {method} (priorité: {priority.name}, raison: {reason})")
    
    def _update_current_rps(self):
        """Met à jour le RPS actuel basé sur les requêtes récentes"""
        now = time.time()
        cutoff = now - 1.0  # Dernière seconde
        
        recent_count = sum(
            1 for req in self.recent_requests 
            if hasattr(req, 'timestamp') and req.timestamp >= cutoff
        )
        
        self.stats.current_rps = float(recent_count)
    
    def get_wait_time(self, priority: RateLimitPriority = RateLimitPriority.NORMAL) -> float:
        """
        Calcule le temps d'attente avant qu'une requête puisse être effectuée
        
        Args:
            priority: Priorité de la requête
            
        Returns:
            Temps d'attente en secondes
        """
        with self.lock:
            wait_times = []
            
            # Token bucket
            if self.config.algorithm == RateLimitAlgorithm.TOKEN_BUCKET:
                wait_times.append(self.token_bucket.get_wait_time(1))
            
            # Sliding windows
            wait_times.append(self.sliding_window_minute.get_wait_time())
            wait_times.append(self.sliding_window_hour.get_wait_time())
            
            # Prendre le maximum
            max_wait = max(wait_times) if wait_times else 0.0
            
            # Appliquer le multiplicateur de priorité (priorité élevée = moins d'attente)
            priority_factor = 1.0 / self.config.priority_multipliers.get(priority, 1.0)
            return max_wait * priority_factor
    
    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques complètes du rate limiter"""
        with self.lock:
            # Calculs dérivés
            block_rate = 0.0
            if self.stats.total_requests > 0:
                block_rate = (self.stats.blocked_requests / self.stats.total_requests) * 100
            
            success_rate = 0.0
            if self.stats.successful_requests + self.stats.failed_requests > 0:
                success_rate = (
                    self.stats.successful_requests / 
                    (self.stats.successful_requests + self.stats.failed_requests)
                ) * 100
            
            base_stats = {
                'endpoint_name': self.endpoint_name,
                'algorithm': self.config.algorithm.value,
                'limits': {
                    'rps': self.config.max_requests_per_second,
                    'rpm': self.config.max_requests_per_minute,
                    'rph': self.config.max_requests_per_hour,
                    'burst_capacity': self.config.burst_capacity
                },
                'current_state': {
                    'current_rps': round(self.stats.current_rps, 2),
                    'available_tokens': self.token_bucket.get_available_tokens(),
                    'minute_window_usage': self.sliding_window_minute.get_current_count(),
                    'hour_window_usage': self.sliding_window_hour.get_current_count()
                },
                'statistics': {
                    'total_requests': self.stats.total_requests,
                    'successful_requests': self.stats.successful_requests,
                    'failed_requests': self.stats.failed_requests,
                    'blocked_requests': self.stats.blocked_requests,
                    'success_rate': round(success_rate, 1),
                    'block_rate': round(block_rate, 1),
                    'avg_response_time': round(self.stats.avg_response_time, 1)
                },
                'recent_blocks': list(self.block_history)[-5:]  # 5 derniers blocages
            }
            
            # Ajouter les stats adaptatives si disponibles
            if self.adaptive_limiter:
                base_stats['adaptive'] = {
                    'current_rate': round(self.adaptive_limiter.get_current_rate(), 2),
                    'base_rate': self.config.max_requests_per_second,
                    'adaptation_count': len(self.adaptive_limiter.get_adaptation_history()),
                    'recent_adaptations': self.adaptive_limiter.get_adaptation_history()[-3:]
                }
            
            return base_stats
    
    def get_health_status(self) -> Dict[str, Any]:
        """Retourne l'état de santé du rate limiter"""
        with self.lock:
            stats = self.get_stats()
            
            # Déterminer l'état de santé
            block_rate = stats['statistics']['block_rate']
            success_rate = stats['statistics']['success_rate']
            
            if block_rate < 5 and success_rate > 95:
                health = "healthy"
            elif block_rate < 15 and success_rate > 80:
                health = "warning"
            else:
                health = "critical"
            
            return {
                'health': health,
                'block_rate': block_rate,
                'success_rate': success_rate,
                'current_load': round((stats['current_state']['current_rps'] / 
                                     stats['limits']['rps']) * 100, 1),
                'recommendations': self._get_health_recommendations(stats)
            }
    
    def _get_health_recommendations(self, stats: Dict) -> List[str]:
        """Génère des recommandations basées sur les statistiques"""
        recommendations = []
        
        block_rate = stats['statistics']['block_rate']
        success_rate = stats['statistics']['success_rate']
        current_load = (stats['current_state']['current_rps'] / stats['limits']['rps']) * 100
        
        if block_rate > 10:
            recommendations.append("Taux de blocage élevé - considérer augmenter les limites")
        
        if success_rate < 90:
            recommendations.append("Taux de succès faible - vérifier la stabilité du service")
        
        if current_load > 80:
            recommendations.append("Charge élevée - distribuer les requêtes ou augmenter la capacité")
        
        if not recommendations:
            recommendations.append("Performance optimale - aucune action requise")
        
        return recommendations
    
    def reset_stats(self):
        """Remet à zéro les statistiques"""
        with self.lock:
            self.stats = RateLimitStats()
            self.block_history.clear()
            self.recent_requests = CircularBuffer(1000)
            
            if self.adaptive_limiter:
                self.adaptive_limiter.adaptation_history.clear()
            
            logger.info(f"📊 Statistiques reset pour {self.endpoint_name}")
    
    def update_config(self, new_config: RateLimitConfig):
        """Met à jour la configuration du rate limiter"""
        with self.lock:
            old_rps = self.config.max_requests_per_second
            self.config = new_config
            
            # Réinitialiser les algorithmes avec la nouvelle config
            self._init_algorithms()
            
            logger.info(f"🔧 Configuration mise à jour pour {self.endpoint_name}")
            logger.info(f"   📊 RPS: {old_rps} → {new_config.max_requests_per_second}")
    
    def _start_cleanup_thread(self):
        """Démarre le thread de nettoyage périodique"""
        def cleanup_loop():
            while not self._should_stop.wait(30):  # Nettoyage toutes les 30 secondes
                try:
                    self._periodic_cleanup()
                except Exception as e:
                    logger.error(f"❌ Erreur lors du nettoyage périodique: {e}")
        
        self._cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
        self._cleanup_thread.start()
    
    def _periodic_cleanup(self):
        """Nettoyage périodique des anciennes données"""
        with self.lock:
            # Nettoyer l'historique des blocages (garder 1 heure)
            cutoff = time.time() - 3600
            self.block_history = deque([
                block for block in self.block_history 
                if block['timestamp'] > cutoff
            ], maxlen=100)
    
    def close(self):
        """Ferme le rate limiter proprement"""
        self._should_stop.set()
        
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=1)
        
        logger.info(f"🛡️ Rate limiter fermé pour {self.endpoint_name}")


class GlobalRateLimiterManager:
    """Gestionnaire global des rate limiters par endpoint"""
    
    def __init__(self):
        self.limiters: Dict[str, RateLimiter] = {}
        self.lock = threading.RLock()
        self.global_stats_start_time = time.time()
    
    def get_limiter(self, endpoint_name: str, config: RateLimitConfig = None) -> RateLimiter:
        """Récupère ou crée un rate limiter pour un endpoint"""
        with self.lock:
            if endpoint_name not in self.limiters:
                self.limiters[endpoint_name] = RateLimiter(config, endpoint_name)
                logger.info(f"🆕 Nouveau rate limiter créé pour {endpoint_name}")
            
            return self.limiters[endpoint_name]
    
    def remove_limiter(self, endpoint_name: str):
        """Supprime un rate limiter"""
        with self.lock:
            if endpoint_name in self.limiters:
                self.limiters[endpoint_name].close()
                del self.limiters[endpoint_name]
                logger.info(f"🗑️ Rate limiter supprimé pour {endpoint_name}")
    
    def get_global_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques globales de tous les limiters"""
        with self.lock:
            total_requests = 0
            total_blocked = 0
            total_successful = 0
            total_failed = 0
            avg_response_times = []
            
            endpoint_stats = {}
            
            for name, limiter in self.limiters.items():
                stats = limiter.get_stats()
                
                # Agrégation globale
                total_requests += stats['statistics']['total_requests']
                total_blocked += stats['statistics']['blocked_requests']
                total_successful += stats['statistics']['successful_requests']
                total_failed += stats['statistics']['failed_requests']
                
                if stats['statistics']['avg_response_time'] > 0:
                    avg_response_times.append(stats['statistics']['avg_response_time'])
                
                # Stats par endpoint
                endpoint_stats[name] = {
                    'current_rps': stats['current_state']['current_rps'],
                    'block_rate': stats['statistics']['block_rate'],
                    'health': limiter.get_health_status()['health']
                }
            
            # Calculs globaux
            global_block_rate = (total_blocked / max(total_requests, 1)) * 100
            global_success_rate = (total_successful / max(total_successful + total_failed, 1)) * 100
            global_avg_response_time = sum(avg_response_times) / len(avg_response_times) if avg_response_times else 0
            
            uptime_hours = (time.time() - self.global_stats_start_time) / 3600
            
            return {
                'uptime_hours': round(uptime_hours, 2),
                'total_endpoints': len(self.limiters),
                'global_metrics': {
                    'total_requests': total_requests,
                    'total_blocked': total_blocked,
                    'block_rate': round(global_block_rate, 2),
                    'success_rate': round(global_success_rate, 2),
                    'avg_response_time': round(global_avg_response_time, 1)
                },
                'endpoints': endpoint_stats,
                'summary': {
                    'healthy_endpoints': sum(1 for stats in endpoint_stats.values() if stats['health'] == 'healthy'),
                    'warning_endpoints': sum(1 for stats in endpoint_stats.values() if stats['health'] == 'warning'),
                    'critical_endpoints': sum(1 for stats in endpoint_stats.values() if stats['health'] == 'critical')
                }
            }
    
    def reset_all_stats(self):
        """Remet à zéro les statistiques de tous les limiters"""
        with self.lock:
            for limiter in self.limiters.values():
                limiter.reset_stats()
            
            self.global_stats_start_time = time.time()
            logger.info("📊 Toutes les statistiques de rate limiting ont été reset")
    
    def close_all(self):
        """Ferme tous les rate limiters"""
        with self.lock:
            for limiter in self.limiters.values():
                limiter.close()
            
            self.limiters.clear()
            logger.info("🛡️ Tous les rate limiters ont été fermés")


# Instance globale du manager
_global_manager = GlobalRateLimiterManager()


def get_rate_limiter(endpoint_name: str, config: RateLimitConfig = None) -> RateLimiter:
    """
    Factory function pour récupérer un rate limiter
    
    Args:
        endpoint_name: Nom de l'endpoint
        config: Configuration optionnelle
        
    Returns:
        Instance RateLimiter
    """
    return _global_manager.get_limiter(endpoint_name, config)


def create_rate_limit_config(
    rps: float = 5.0,
    rpm: float = 300.0,
    rph: float = 18000.0,
    algorithm: str = "adaptive",
    adaptive: bool = True
) -> RateLimitConfig:
    """
    Factory function pour créer une configuration de rate limiting
    
    Args:
        rps: Requêtes par seconde
        rpm: Requêtes par minute
        rph: Requêtes par heure
        algorithm: Algorithme à utiliser
        adaptive: Activer l'adaptation automatique
        
    Returns:
        Configuration RateLimitConfig
    """
    try:
        algo = RateLimitAlgorithm(algorithm)
    except ValueError:
        logger.warning(f"⚠️ Algorithme inconnu '{algorithm}', utilisation d'ADAPTIVE")
        algo = RateLimitAlgorithm.ADAPTIVE
    
    return RateLimitConfig(
        max_requests_per_second=rps,
        max_requests_per_minute=rpm,
        max_requests_per_hour=rph,
        algorithm=algo,
        enable_adaptive_scaling=adaptive
    )


@contextmanager
def rate_limited_context(endpoint_name: str, 
                        priority: RateLimitPriority = RateLimitPriority.NORMAL,
                        method: str = "unknown"):
    """
    Context manager pour requêtes avec rate limiting automatique
    
    Args:
        endpoint_name: Nom de l'endpoint
        priority: Priorité de la requête
        method: Nom de la méthode
        
    Usage:
        with rate_limited_context("quicknode", RateLimitPriority.HIGH, "getBalance") as limiter:
            if limiter.can_proceed():
                # Faire la requête
                result = make_request()
                limiter.record_request("getBalance", success=True, response_time=150.0)
    """
    limiter = get_rate_limiter(endpoint_name)
    start_time = time.time()
    
    try:
        yield limiter
    except Exception as e:
        # Enregistrer l'échec
        response_time = (time.time() - start_time) * 1000
        limiter.record_request(method, priority, response_time, success=False)
        raise
    finally:
        # Le record_request sera appelé manuellement dans le contexte si succès
        pass


def wait_for_rate_limit(endpoint_name: str, 
                       priority: RateLimitPriority = RateLimitPriority.NORMAL,
                       max_wait: float = 60.0) -> bool:
    """
    Attend que le rate limit permette une requête
    
    Args:
        endpoint_name: Nom de l'endpoint
        priority: Priorité de la requête
        max_wait: Temps d'attente maximum en secondes
        
    Returns:
        True si peut procéder, False si timeout
    """
    limiter = get_rate_limiter(endpoint_name)
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        if limiter.can_proceed(priority):
            return True
        
        wait_time = limiter.get_wait_time(priority)
        if wait_time > max_wait - (time.time() - start_time):
            break
        
        # Attendre avec backoff exponentiel
        sleep_time = min(wait_time, exponential_backoff(0, base_delay=0.1, max_delay=1.0))
        time.sleep(sleep_time)
    
    logger.warning(f"⏰ Timeout d'attente du rate limit pour {endpoint_name}")
    return False


def get_global_rate_limit_stats() -> Dict[str, Any]:
    """Retourne les statistiques globales de rate limiting"""
    return _global_manager.get_global_stats()


def reset_all_rate_limit_stats():
    """Remet à zéro toutes les statistiques de rate limiting"""
    _global_manager.reset_all_stats()


class RateLimitDecorator:
    """Décorateur pour appliquer automatiquement le rate limiting"""
    
    def __init__(self, endpoint_name: str, 
                 priority: RateLimitPriority = RateLimitPriority.NORMAL,
                 max_wait: float = 30.0):
        self.endpoint_name = endpoint_name
        self.priority = priority
        self.max_wait = max_wait
    
    def __call__(self, func: Callable):
        def wrapper(*args, **kwargs):
            method_name = func.__name__
            
            # Attendre que le rate limit permette la requête
            if not wait_for_rate_limit(self.endpoint_name, self.priority, self.max_wait):
                raise RPCRateLimitError(
                    self.endpoint_name,
                    retry_after=30,
                    current_rps=get_rate_limiter(self.endpoint_name).stats.current_rps
                )
            
            # Exécuter la fonction avec mesure du temps
            limiter = get_rate_limiter(self.endpoint_name)
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                
                # Enregistrer le succès
                response_time = (time.time() - start_time) * 1000
                limiter.record_request(method_name, self.priority, response_time, success=True)
                
                return result
                
            except Exception as e:
                # Enregistrer l'échec
                response_time = (time.time() - start_time) * 1000
                limiter.record_request(method_name, self.priority, response_time, success=False)
                raise
        
        return wrapper


def rate_limited(endpoint_name: str, 
                priority: RateLimitPriority = RateLimitPriority.NORMAL,
                max_wait: float = 30.0):
    """
    Décorateur pour appliquer le rate limiting à une fonction
    
    Args:
        endpoint_name: Nom de l'endpoint pour le rate limiting
        priority: Priorité de la requête
        max_wait: Temps d'attente maximum
        
    Usage:
        @rate_limited("quicknode", RateLimitPriority.HIGH)
        def get_account_info(address):
            # Faire l'appel RPC
            return rpc_call("getAccountInfo", [address])
    """
    return RateLimitDecorator(endpoint_name, priority, max_wait)


def create_endpoint_rate_limiter(endpoint_url: str, tier: str = "free") -> RateLimiter:
    """
    Crée un rate limiter configuré pour un endpoint spécifique
    
    Args:
        endpoint_url: URL de l'endpoint
        tier: Tier du service ("free", "premium", "enterprise")
        
    Returns:
        RateLimiter configuré
    """
    # Configurations prédéfinies par tier
    tier_configs = {
        "free": RateLimitConfig(
            max_requests_per_second=5.0,
            max_requests_per_minute=300.0,
            max_requests_per_hour=10000.0,
            burst_capacity=10,
            algorithm=RateLimitAlgorithm.SLIDING_WINDOW
        ),
        "premium": RateLimitConfig(
            max_requests_per_second=50.0,
            max_requests_per_minute=3000.0,
            max_requests_per_hour=100000.0,
            burst_capacity=100,
            algorithm=RateLimitAlgorithm.ADAPTIVE,
            enable_adaptive_scaling=True
        ),
        "enterprise": RateLimitConfig(
            max_requests_per_second=200.0,
            max_requests_per_minute=12000.0,
            max_requests_per_hour=500000.0,
            burst_capacity=500,
            algorithm=RateLimitAlgorithm.ADAPTIVE,
            enable_adaptive_scaling=True
        )
    }
    
    config = tier_configs.get(tier.lower(), tier_configs["free"])
    
    # Extraire un nom lisible de l'URL
    endpoint_name = endpoint_url.split("://")[-1].split("/")[0].split(".")[0]
    
    return RateLimiter(config, endpoint_name)


def analyze_rate_limit_patterns(endpoint_name: str, hours: int = 24) -> Dict[str, Any]:
    """
    Analyse les patterns de rate limiting pour un endpoint
    
    Args:
        endpoint_name: Nom de l'endpoint
        hours: Nombre d'heures à analyser
        
    Returns:
        Analyse des patterns
    """
    limiter = get_rate_limiter(endpoint_name)
    stats = limiter.get_stats()
    
    # Analyse des blocages récents
    recent_blocks = stats.get('recent_blocks', [])
    
    # Compter les blocages par raison
    block_reasons = defaultdict(int)
    for block in recent_blocks:
        block_reasons[block['reason']] += 1
    
    # Analyse des patterns temporels (si on a l'historique)
    patterns = {
        'endpoint_name': endpoint_name,
        'analysis_period_hours': hours,
        'current_health': limiter.get_health_status(),
        'block_analysis': {
            'total_blocks': len(recent_blocks),
            'block_reasons': dict(block_reasons),
            'most_common_reason': max(block_reasons.items(), key=lambda x: x[1])[0] if block_reasons else None
        },
        'recommendations': []
    }
    
    # Générer des recommandations
    if stats['statistics']['block_rate'] > 10:
        patterns['recommendations'].append("Considérer augmenter les limites de taux")
    
    if 'token_bucket_exhausted' in block_reasons:
        patterns['recommendations'].append("Augmenter la capacité de burst")
    
    if 'minute_limit_exceeded' in block_reasons:
        patterns['recommendations'].append("Revoir les limites par minute")
    
    # Analyse adaptative
    if 'adaptive' in stats and len(stats['adaptive']['recent_adaptations']) > 0:
        recent_adaptations = stats['adaptive']['recent_adaptations']
        increase_count = sum(1 for adapt in recent_adaptations if adapt['action'] == 'increase')
        decrease_count = sum(1 for adapt in recent_adaptations if adapt['action'] == 'decrease')
        
        patterns['adaptive_analysis'] = {
            'recent_increases': increase_count,
            'recent_decreases': decrease_count,
            'adaptation_trend': 'improving' if increase_count > decrease_count else 'degrading' if decrease_count > increase_count else 'stable'
        }
    
    return patterns


if __name__ == "__main__":
    # Script de test pour le rate limiter
    import random
    
    print("🧪 Test du Rate Limiter RPC")
    print("=" * 50)
    
    # Test 1: Création et configuration
    print("\n🛡️ Test création rate limiter...")
    config = create_rate_limit_config(rps=10.0, algorithm="adaptive")
    limiter = RateLimiter(config, "test_endpoint")
    
    print(f"✅ Rate limiter créé: {config.algorithm.value}, {config.max_requests_per_second} RPS")
    
    # Test 2: Test de base du rate limiting
    print("\n⚡ Test rate limiting basique...")
    allowed_requests = 0
    blocked_requests = 0
    
    for i in range(50):
        if limiter.can_proceed(RateLimitPriority.NORMAL, f"test_method_{i}"):
            allowed_requests += 1
            # Simuler une requête réussie
            response_time = random.uniform(50, 500)  # 50-500ms
            limiter.record_request(f"test_method_{i}", response_time=response_time, success=True)
        else:
            blocked_requests += 1
        
        time.sleep(0.05)  # 50ms entre les requêtes
    
    print(f"📊 Requêtes autorisées: {allowed_requests}")
    print(f"🛑 Requêtes bloquées: {blocked_requests}")
    print(f"📈 Taux de blocage: {(blocked_requests / 50) * 100:.1f}%")
    
    # Test 3: Statistiques
    print("\n📊 Test statistiques...")
    stats = limiter.get_stats()
    print(f"RPS actuel: {stats['current_state']['current_rps']}")
    print(f"Temps de réponse moyen: {stats['statistics']['avg_response_time']:.1f}ms")
    print(f"Taux de succès: {stats['statistics']['success_rate']:.1f}%")
    
    # Test 4: Health check
    print("\n🏥 Test health check...")
    health = limiter.get_health_status()
    print(f"Santé: {health['health']}")
    print(f"Charge actuelle: {health['current_load']:.1f}%")
    
    for rec in health['recommendations']:
        print(f"💡 {rec}")
    
    # Test 5: Test avec priorités
    print("\n🎯 Test priorités...")
    high_priority_allowed = 0
    low_priority_allowed = 0
    
    # Saturer le rate limiter
    for _ in range(20):
        limiter.can_proceed()
    
    # Tester les priorités
    for _ in range(10):
        if limiter.can_proceed(RateLimitPriority.HIGH):
            high_priority_allowed += 1
        if limiter.can_proceed(RateLimitPriority.LOW):
            low_priority_allowed += 1
    
    print(f"Haute priorité autorisée: {high_priority_allowed}/10")
    print(f"Basse priorité autorisée: {low_priority_allowed}/10")
    
    # Test 6: Context manager
    print("\n🔄 Test context manager...")
    try:
        with rate_limited_context("test_endpoint", RateLimitPriority.NORMAL, "test_context") as limiter_ctx:
            if limiter_ctx.can_proceed():
                print("✅ Requête autorisée dans le contexte")
                time.sleep(0.1)  # Simuler traitement
                limiter_ctx.record_request("test_context", response_time=100.0, success=True)
            else:
                print("🛑 Requête bloquée dans le contexte")
    except Exception as e:
        print(f"❌ Erreur context manager: {e}")
    
    # Test 7: Décorateur
    print("\n🎪 Test décorateur...")
    
    @rate_limited("test_endpoint", RateLimitPriority.NORMAL, max_wait=1.0)
    def test_function():
        time.sleep(0.1)  # Simuler traitement
        return "Success"
    
    try:
        result = test_function()
        print(f"✅ Fonction décorée: {result}")
    except RPCRateLimitError:
        print("🛑 Fonction bloquée par rate limiting")
    except Exception as e:
        print(f"❌ Erreur décorateur: {e}")
    
    # Test 8: Manager global
    print("\n🌍 Test manager global...")
    global_stats = get_global_rate_limit_stats()
    print(f"Endpoints gérés: {global_stats['total_endpoints']}")
    print(f"Requêtes globales: {global_stats['global_metrics']['total_requests']}")
    print(f"Taux de blocage global: {global_stats['global_metrics']['block_rate']:.1f}%")
    
    # Test 9: Analyse des patterns
    print("\n🔍 Test analyse patterns...")
    patterns = analyze_rate_limit_patterns("test_endpoint")
    print(f"Santé actuelle: {patterns['current_health']['health']}")
    print(f"Blocages totaux: {patterns['block_analysis']['total_blocks']}")
    
    for rec in patterns['recommendations']:
        print(f"💡 {rec}")
    
    # Nettoyage
    limiter.close()
    print("\n✅ Tests terminés avec succès!")
    print("🧹 Nettoyage effectué")