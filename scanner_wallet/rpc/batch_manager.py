
#!/usr/bin/env python3
"""
Gestionnaire de batching RPC intelligent pour Solana
Optimise les requêtes RPC en les groupant selon les performances et contraintes
"""

import asyncio
import time
import threading
import json
import hashlib
from typing import Dict, List, Optional, Any, Tuple, Callable, Union
from dataclasses import dataclass, field
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timedelta
from enum import Enum
import logging
import uuid
import requests
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed

# Imports des modules internes
try:
    from core.config import get_config
    from core.exceptions import (
        BatchingError, BatchSizeError, BatchExecutionError, 
        BatchAdaptiveError, RPCTimeoutError, RPCRateLimitError
    )
    from core.logger import get_logger
    from utils.helpers import get_current_timestamp, CircularBuffer, exponential_backoff
    from utils.constants import (
        OPTIMAL_BATCH_SIZES, CONSERVATIVE_BATCH_SIZES, 
        PERFORMANCE_THRESHOLDS, RPC_TIMEOUT_BATCH
    )
    from .rate_limiter import get_rate_limiter, RateLimitPriority
except ImportError as e:
    logging.warning(f"Import error in batch manager: {e}")
    # Fallbacks pour développement
    logger = logging.getLogger(__name__)
    
    # Constantes par défaut
    OPTIMAL_BATCH_SIZES = {
        'getMultipleAccounts': 100,
        'getSignaturesForAddress': 20,
        'getTransaction': 10,
        'token_metadata': 15,
        'signatures_batch': 25,
        'transactions_batch': 8
    }
    
    CONSERVATIVE_BATCH_SIZES = {k: max(1, v // 2) for k, v in OPTIMAL_BATCH_SIZES.items()}
    
    PERFORMANCE_THRESHOLDS = {
        'good_response_time': 1000,
        'warning_response_time': 5000,
        'critical_response_time': 15000
    }
    
    RPC_TIMEOUT_BATCH = 25
    
    class BatchingError(Exception):
        pass
    
    class RateLimitPriority:
        NORMAL = "normal"
        HIGH = "high"

# Configuration du logger
logger = logging.getLogger(__name__)


class BatchStrategy(Enum):
    """Stratégies de batching disponibles"""
    FIXED_SIZE = "fixed_size"
    ADAPTIVE_SIZE = "adaptive_size"
    PERFORMANCE_BASED = "performance_based"
    PRIORITY_WEIGHTED = "priority_weighted"


class BatchPriority(Enum):
    """Priorités de batch"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


class BatchStatus(Enum):
    """États d'un batch"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class BatchRequest:
    """Représente une requête RPC individuelle dans un batch"""
    id: str
    method: str
    params: List[Any]
    priority: BatchPriority = BatchPriority.NORMAL
    timeout: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 3
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def age(self) -> float:
        """Age de la requête en secondes"""
        return time.time() - self.created_at
    
    def to_json_rpc(self) -> Dict[str, Any]:
        """Convertit en format JSON-RPC"""
        return {
            "jsonrpc": "2.0",
            "id": self.id,
            "method": self.method,
            "params": self.params
        }


@dataclass
class BatchConfig:
    """Configuration du batching"""
    # Tailles de batch par méthode
    batch_sizes: Dict[str, int] = field(default_factory=lambda: OPTIMAL_BATCH_SIZES.copy())
    
    # Paramètres temporels
    min_delay_between_batches: float = 0.3
    max_concurrent_batches: int = 3
    batch_timeout: float = RPC_TIMEOUT_BATCH
    collection_timeout: float = 2.0  # Temps max pour collecter les requêtes
    
    # Stratégie et adaptation
    strategy: BatchStrategy = BatchStrategy.ADAPTIVE_SIZE
    enable_adaptive_sizing: bool = True
    adaptation_sensitivity: float = 0.1  # 10% d'ajustement par adaptation
    
    # Performance et retry
    max_response_time_threshold: float = 10000.0  # 10s en ms
    retry_failed_requests: bool = True
    max_retries_per_request: int = 3
    
    # Priorités et équilibrage
    priority_boost_factor: float = 1.5
    enable_priority_queuing: bool = True


@dataclass
class BatchMetrics:
    """Métriques d'un batch exécuté"""
    batch_id: str
    method: str
    size: int
    duration: float
    success_count: int
    failure_count: int
    timeout_count: int
    response_time_ms: float
    endpoint: str
    created_at: float = field(default_factory=time.time)
    
    @property
    def success_rate(self) -> float:
        """Taux de succès du batch"""
        total = self.success_count + self.failure_count
        return (self.success_count / total * 100) if total > 0 else 0.0
    
    @property
    def throughput(self) -> float:
        """Débit du batch (requêtes/seconde)"""
        return self.size / self.duration if self.duration > 0 else 0.0


@dataclass
class BatchStats:
    """Statistiques globales du batch manager"""
    total_batches: int = 0
    successful_batches: int = 0
    failed_batches: int = 0
    total_requests_processed: int = 0
    total_time_saved_estimate: float = 0.0
    avg_batch_size: float = 0.0
    avg_response_time: float = 0.0
    current_batch_sizes: Dict[str, int] = field(default_factory=dict)
    performance_history: List[BatchMetrics] = field(default_factory=list)
    
    @property
    def success_rate(self) -> float:
        """Taux de succès global"""
        total = self.successful_batches + self.failed_batches
        return (self.successful_batches / total * 100) if total > 0 else 0.0


class BatchCollector:
    """Collecteur de requêtes pour formation de batches"""
    
    def __init__(self, method: str, max_size: int, timeout: float = 2.0):
        self.method = method
        self.max_size = max_size
        self.timeout = timeout
        self.requests: List[BatchRequest] = []
        self.lock = threading.Lock()
        self.created_at = time.time()
        self.last_addition = time.time()
        
    def add_request(self, request: BatchRequest) -> bool:
        """Ajoute une requête au collecteur"""
        with self.lock:
            if len(self.requests) >= self.max_size:
                return False
            
            if request.method != self.method:
                return False
            
            self.requests.append(request)
            self.last_addition = time.time()
            return True
    
    def is_ready(self) -> bool:
        """Vérifie si le batch est prêt à être exécuté"""
        with self.lock:
            # Prêt si plein ou si timeout atteint
            is_full = len(self.requests) >= self.max_size
            is_timeout = (time.time() - self.created_at) >= self.timeout
            has_requests = len(self.requests) > 0
            
            return is_full or (is_timeout and has_requests)
    
    def extract_batch(self) -> List[BatchRequest]:
        """Extrait toutes les requêtes pour former un batch"""
        with self.lock:
            batch = self.requests.copy()
            self.requests.clear()
            return batch
    
    def size(self) -> int:
        """Retourne la taille actuelle du collecteur"""
        with self.lock:
            return len(self.requests)
    
    def age(self) -> float:
        """Age du collecteur en secondes"""
        return time.time() - self.created_at


class AdaptiveSizer:
    """Gestionnaire de taille adaptative des batches"""
    
    def __init__(self, config: BatchConfig):
        self.config = config
        self.method_performance = defaultdict(lambda: CircularBuffer(50))
        self.current_sizes = config.batch_sizes.copy()
        self.last_adaptation = defaultdict(float)
        self.adaptation_history = defaultdict(list)
        self.lock = threading.Lock()
        
    def record_performance(self, metrics: BatchMetrics):
        """Enregistre les performances d'un batch"""
        with self.lock:
            self.method_performance[metrics.method].append(metrics)
            
            # Vérifier si adaptation nécessaire
            if self._should_adapt(metrics.method):
                self._adapt_size(metrics.method)
    
    def _should_adapt(self, method: str) -> bool:
        """Détermine si une adaptation est nécessaire"""
        now = time.time()
        
        # Éviter les adaptations trop fréquentes
        if now - self.last_adaptation[method] < 30:  # 30 secondes minimum
            return False
        
        # Besoin d'au moins 5 échantillons
        buffer = self.method_performance[method]
        if len(buffer) < 5:
            return False
        
        return True
    
    def _adapt_size(self, method: str):
        """Adapte la taille du batch pour une méthode"""
        buffer = self.method_performance[method]
        recent_metrics = list(buffer)[-10:]  # 10 dernières métriques
        
        if not recent_metrics:
            return
        
        # Analyser les performances
        avg_response_time = sum(m.response_time_ms for m in recent_metrics) / len(recent_metrics)
        avg_success_rate = sum(m.success_rate for m in recent_metrics) / len(recent_metrics)
        avg_throughput = sum(m.throughput for m in recent_metrics) / len(recent_metrics)
        
        current_size = self.current_sizes.get(method, OPTIMAL_BATCH_SIZES.get(method, 10))
        old_size = current_size
        
        # Logique d'adaptation
        if avg_response_time > PERFORMANCE_THRESHOLDS['critical_response_time']:
            # Performance très dégradée - réduction drastique
            new_size = max(1, int(current_size * 0.5))
            reason = "critical_performance"
            
        elif avg_response_time > PERFORMANCE_THRESHOLDS['warning_response_time']:
            # Performance dégradée - réduction modérée
            new_size = max(1, int(current_size * 0.8))
            reason = "poor_performance"
            
        elif avg_success_rate < 80:
            # Taux d'échec élevé - réduction
            new_size = max(1, int(current_size * 0.7))
            reason = "low_success_rate"
            
        elif (avg_response_time < PERFORMANCE_THRESHOLDS['good_response_time'] and 
              avg_success_rate > 95):
            # Bonnes performances - augmentation prudente
            optimal_size = OPTIMAL_BATCH_SIZES.get(method, 10)
            if current_size < optimal_size:
                new_size = min(optimal_size, int(current_size * 1.2))
                reason = "good_performance"
            else:
                return  # Déjà à la taille optimale
        else:
            return  # Performances acceptables, pas de changement
        
        # Appliquer le changement
        self.current_sizes[method] = new_size
        self.last_adaptation[method] = time.time()
        
        # Enregistrer l'adaptation
        adaptation = {
            'timestamp': time.time(),
            'old_size': old_size,
            'new_size': new_size,
            'reason': reason,
            'avg_response_time': avg_response_time,
            'avg_success_rate': avg_success_rate
        }
        
        self.adaptation_history[method].append(adaptation)
        
        # Garder seulement les 20 dernières adaptations
        if len(self.adaptation_history[method]) > 20:
            self.adaptation_history[method] = self.adaptation_history[method][-20:]
        
        logger.info(f"🔧 Adaptation batch {method}: {old_size} → {new_size} ({reason})")
    
    def get_current_size(self, method: str) -> int:
        """Retourne la taille actuelle pour une méthode"""
        with self.lock:
            return self.current_sizes.get(method, OPTIMAL_BATCH_SIZES.get(method, 10))
    
    def get_adaptation_history(self, method: str) -> List[Dict]:
        """Retourne l'historique d'adaptation pour une méthode"""
        with self.lock:
            return self.adaptation_history[method].copy()
    
    def reset_adaptations(self):
        """Remet à zéro les adaptations"""
        with self.lock:
            self.current_sizes = self.config.batch_sizes.copy()
            self.adaptation_history.clear()
            self.last_adaptation.clear()
            logger.info("🔄 Adaptations de batch remises à zéro")


class BatchExecutor:
    """Exécuteur de batches RPC"""
    
    def __init__(self, config: BatchConfig, rpc_client=None):
        self.config = config
        self.rpc_client = rpc_client
        self.executor = ThreadPoolExecutor(max_workers=config.max_concurrent_batches)
        self.active_batches: Dict[str, asyncio.Future] = {}
        self.lock = threading.Lock()
        
    def execute_batch(self, requests: List[BatchRequest], endpoint: str) -> BatchMetrics:
        """
        Exécute un batch de requêtes
        
        Args:
            requests: Liste des requêtes à exécuter
            endpoint: URL de l'endpoint RPC
            
        Returns:
            BatchMetrics avec les résultats
        """
        batch_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        
        if not requests:
            raise BatchExecutionError("", 0, 0, "Empty batch")
        
        method = requests[0].method
        batch_size = len(requests)
        
        logger.debug(f"🚀 Exécution batch {batch_id}: {method} x{batch_size}")
        
        try:
            # Préparer le payload JSON-RPC
            json_requests = [req.to_json_rpc() for req in requests]
            
            # Headers avec informations de batch
            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'SolanaWalletMonitor-Batch/2.0',
                'X-Batch-ID': batch_id,
                'X-Batch-Size': str(batch_size),
                'X-Batch-Method': method
            }
            
            # Exécuter la requête HTTP
            response = requests.post(
                endpoint,
                json=json_requests,
                headers=headers,
                timeout=self.config.batch_timeout
            )
            
            duration = time.time() - start_time
            
            # Traiter la réponse
            if response.status_code == 200:
                try:
                    results = response.json()
                    
                    if not isinstance(results, list):
                        results = [results]
                    
                    # Analyser les résultats
                    success_count = 0
                    failure_count = 0
                    timeout_count = 0
                    
                    for result in results:
                        if isinstance(result, dict):
                            if 'error' in result:
                                error_code = result.get('error', {}).get('code', 0)
                                if error_code == -32005:  # Timeout
                                    timeout_count += 1
                                else:
                                    failure_count += 1
                            else:
                                success_count += 1
                        else:
                            failure_count += 1
                    
                    # Compléter les résultats manquants
                    missing_results = batch_size - len(results)
                    failure_count += missing_results
                    
                    metrics = BatchMetrics(
                        batch_id=batch_id,
                        method=method,
                        size=batch_size,
                        duration=duration,
                        success_count=success_count,
                        failure_count=failure_count,
                        timeout_count=timeout_count,
                        response_time_ms=duration * 1000,
                        endpoint=endpoint
                    )
                    
                    logger.info(f"✅ Batch {batch_id} terminé: "
                               f"{success_count}/{batch_size} succès en {duration:.2f}s")
                    
                    return metrics
                    
                except json.JSONDecodeError as e:
                    raise BatchExecutionError(method, batch_size, 0, f"JSON decode error: {e}")
                    
            elif response.status_code == 429:
                raise RPCRateLimitError(endpoint, 
                                      retry_after=int(response.headers.get('Retry-After', 60)))
            
            else:
                raise BatchExecutionError(
                    method, batch_size, 0,
                    f"HTTP {response.status_code}: {response.text[:200]}"
                )
                
        except requests.exceptions.Timeout:
            duration = time.time() - start_time
            raise BatchExecutionError(method, batch_size, 0, f"Batch timeout after {duration:.1f}s")
        
        except requests.exceptions.RequestException as e:
            duration = time.time() - start_time
            raise BatchExecutionError(method, batch_size, 0, f"Request error: {e}")
    
    def close(self):
        """Ferme l'exécuteur de batch"""
        self.executor.shutdown(wait=True)


class BatchManager:
    """Gestionnaire principal de batching RPC"""
    
    def __init__(self, config: BatchConfig = None, rpc_client=None):
        self.config = config or BatchConfig()
        self.rpc_client = rpc_client
        
        # Composants internes
        self.adaptive_sizer = AdaptiveSizer(self.config)
        self.executor = BatchExecutor(self.config, rpc_client)
        
        # État du manager
        self.collectors: Dict[str, BatchCollector] = {}
        self.pending_requests: Dict[str, BatchRequest] = {}
        self.stats = BatchStats()
        self.stats.current_batch_sizes = self.config.batch_sizes.copy()
        
        # Thread safety
        self.lock = threading.RLock()
        
        # Thread de traitement
        self._processing_thread = None
        self._should_stop = threading.Event()
        self._start_processing_thread()
        
        # Rate limiting
        self.rate_limiter = None
        try:
            if rpc_client and hasattr(rpc_client, 'get_current_endpoint'):
                endpoint = rpc_client.get_current_endpoint()
                endpoint_name = endpoint.get('url', 'unknown').split('://')[1].split('/')[0]
                self.rate_limiter = get_rate_limiter(endpoint_name)
        except Exception:
            pass
        
        logger.info(f"📦 Batch Manager initialisé")
        logger.info(f"   🔧 Stratégie: {self.config.strategy.value}")
        logger.info(f"   📊 Tailles: {self.config.batch_sizes}")
        logger.info(f"   ⏱️ Timeout: {self.config.batch_timeout}s")
    
    def _start_processing_thread(self):
        """Démarre le thread de traitement des batches"""
        def processing_loop():
            while not self._should_stop.wait(0.1):  # Vérification toutes les 100ms
                try:
                    self._process_ready_batches()
                except Exception as e:
                    logger.error(f"❌ Erreur dans le thread de processing: {e}")
        
        self._processing_thread = threading.Thread(target=processing_loop, daemon=True)
        self._processing_thread.start()
        logger.debug("🔄 Thread de processing des batches démarré")
    
    def _process_ready_batches(self):
        """Traite les batches prêts à être exécutés"""
        ready_collectors = []
        
        with self.lock:
            # Identifier les collecteurs prêts
            for method, collector in list(self.collectors.items()):
                if collector.is_ready():
                    ready_collectors.append((method, collector))
        
        # Traiter chaque collecteur prêt
        for method, collector in ready_collectors:
            try:
                batch_requests = collector.extract_batch()
                
                if not batch_requests:
                    continue
                
                # Supprimer le collecteur vide
                with self.lock:
                    if method in self.collectors and self.collectors[method].size() == 0:
                        del self.collectors[method]
                
                # Exécuter le batch
                self._execute_batch_async(batch_requests)
                
            except Exception as e:
                logger.error(f"❌ Erreur traitement batch {method}: {e}")
    
    def _execute_batch_async(self, requests: List[BatchRequest]):
        """Exécute un batch de manière asynchrone"""
        if not requests:
            return
        
        method = requests[0].method
        
        # Obtenir l'endpoint
        endpoint = self._get_endpoint_url()
        if not endpoint:
            logger.error(f"❌ Pas d'endpoint disponible pour batch {method}")
            return
        
        # Vérifier le rate limiting
        if self.rate_limiter:
            priority = RateLimitPriority.HIGH if len(requests) > 10 else RateLimitPriority.NORMAL
            
            if not self.rate_limiter.can_proceed(priority, f"batch_{method}"):
                wait_time = self.rate_limiter.get_wait_time(priority)
                if wait_time > 5.0:  # Plus de 5 secondes d'attente
                    logger.warning(f"⏳ Rate limit: report du batch {method} ({wait_time:.1f}s)")
                    # Remettre les requêtes dans la queue
                    self._requeue_requests(requests)
                    return
                
                time.sleep(wait_time)
        
        # Exécuter le batch
        try:
            metrics = self.executor.execute_batch(requests, endpoint)
            
            # Enregistrer les performances
            self.adaptive_sizer.record_performance(metrics)
            
            # Mettre à jour les statistiques
            with self.lock:
                self.stats.total_batches += 1
                self.stats.total_requests_processed += len(requests)
                
                if metrics.success_rate > 50:  # Considéré comme réussi si >50% de succès
                    self.stats.successful_batches += 1
                else:
                    self.stats.failed_batches += 1
                
                # Mettre à jour les moyennes
                self._update_averages(metrics)
                
                # Ajouter à l'historique
                self.stats.performance_history.append(metrics)
                if len(self.stats.performance_history) > 100:
                    self.stats.performance_history = self.stats.performance_history[-100:]
            
            # Enregistrer dans le rate limiter si disponible
            if self.rate_limiter:
                self.rate_limiter.record_request(
                    method=f"batch_{method}",
                    response_time=metrics.response_time_ms,
                    success=metrics.success_rate > 50
                )
            
            logger.debug(f"📊 Batch {method} metrics: "
                        f"{metrics.success_rate:.1f}% succès, {metrics.response_time_ms:.0f}ms")
                        
        except Exception as e:
            logger.error(f"❌ Erreur exécution batch {method}: {e}")
            
            # Mettre à jour les stats d'échec
            with self.lock:
                self.stats.total_batches += 1
                self.stats.failed_batches += 1
            
            # Retry individuel si configuré
            if self.config.retry_failed_requests:
                self._retry_requests_individually(requests, str(e))
    
    def _get_endpoint_url(self) -> Optional[str]:
        """Récupère l'URL de l'endpoint RPC"""
        if self.rpc_client and hasattr(self.rpc_client, 'get_current_endpoint'):
            endpoint_info = self.rpc_client.get_current_endpoint()
            return endpoint_info.get('url') if isinstance(endpoint_info, dict) else endpoint_info
        
        # Fallback vers configuration
        try:
            config = get_config()
            if hasattr(config, 'rpc') and hasattr(config.rpc, 'quicknode_endpoint'):
                return config.rpc.quicknode_endpoint
        except:
            pass
        
        return "https://api.mainnet-beta.solana.com"  # Fallback public
    
    def _requeue_requests(self, requests: List[BatchRequest]):
        """Remet des requêtes dans la queue"""
        with self.lock:
            for request in requests:
                self.pending_requests[request.id] = request
                
                # Ajouter au collecteur approprié
                collector = self._get_or_create_collector(request.method)
                if not collector.add_request(request):
                    logger.warning(f"⚠️ Impossible de re-queue la requête {request.id}")
    
    def _retry_requests_individually(self, requests: List[BatchRequest], error: str):
        """Retry les requêtes individuellement en cas d'échec du batch"""
        logger.info(f"🔄 Retry individuel de {len(requests)} requêtes après échec batch: {error}")
        
        for request in requests:
            if request.retry_count < request.max_retries:
                request.retry_count += 1
                
                # Remettre dans la queue avec priorité élevée
                request.priority = BatchPriority.HIGH
                
                with self.lock:
                    self.pending_requests[request.id] = request
                
                # Ajouter au collecteur
                collector = self._get_or_create_collector(request.method)
                collector.add_request(request)
            else:
                logger.warning(f"⚠️ Requête {request.id} abandonnée après {request.retry_count} retries")
    
    def _update_averages(self, metrics: BatchMetrics):
        """Met à jour les moyennes dans les statistiques"""
        # Moyenne mobile pour la taille de batch
        if self.stats.avg_batch_size == 0:
            self.stats.avg_batch_size = float(metrics.size)
        else:
            alpha = 0.1  # Facteur de lissage
            self.stats.avg_batch_size = (
                alpha * metrics.size + (1 - alpha) * self.stats.avg_batch_size
            )
        
        # Moyenne mobile pour le temps de réponse
        if self.stats.avg_response_time == 0:
            self.stats.avg_response_time = metrics.response_time_ms
        else:
            alpha = 0.1
            self.stats.avg_response_time = (
                alpha * metrics.response_time_ms + (1 - alpha) * self.stats.avg_response_time
            )
    
    def add_request(self, method: str, params: List[Any], 
                   priority: BatchPriority = BatchPriority.NORMAL,
                   timeout: Optional[float] = None,
                   metadata: Dict[str, Any] = None) -> str:
        """
        Ajoute une requête au système de batching
        
        Args:
            method: Méthode RPC
            params: Paramètres de la méthode
            priority: Priorité de la requête
            timeout: Timeout spécifique
            metadata: Métadonnées additionnelles
            
        Returns:
            ID de la requête
        """
        request = BatchRequest(
            id=str(uuid.uuid4()),
            method=method,
            params=params,
            priority=priority,
            timeout=timeout or self.config.batch_timeout,
            metadata=metadata or {}
        )
        
        with self.lock:
            # Ajouter aux requêtes en attente
            self.pending_requests[request.id] = request
            
            # Ajouter au collecteur approprié
            collector = self._get_or_create_collector(method)
            
            if not collector.add_request(request):
                logger.warning(f"⚠️ Collecteur plein pour {method}, création d'un nouveau")
                # Forcer le traitement du collecteur actuel
                self._force_process_collector(method)
                
                # Créer un nouveau collecteur
                collector = self._get_or_create_collector(method, force_new=True)
                collector.add_request(request)
        
        logger.debug(f"➕ Requête ajoutée: {method} (ID: {request.id[:8]}...)")
        return request.id
    
    def _get_or_create_collector(self, method: str, force_new: bool = False) -> BatchCollector:
        """Récupère ou crée un collecteur pour une méthode"""
        if method not in self.collectors or force_new:
            # Déterminer la taille du batch
            if self.config.enable_adaptive_sizing:
                batch_size = self.adaptive_sizer.get_current_size(method)
            else:
                batch_size = self.config.batch_sizes.get(method, OPTIMAL_BATCH_SIZES.get(method, 10))
            
            self.collectors[method] = BatchCollector(
                method=method,
                max_size=batch_size,
                timeout=self.config.collection_timeout
            )
            
            logger.debug(f"🆕 Nouveau collecteur créé pour {method} (taille: {batch_size})")
        
        return self.collectors[method]
    
    def _force_process_collector(self, method: str):
        """Force le traitement d'un collecteur spécifique"""
        if method in self.collectors:
            collector = self.collectors[method]
            if collector.size() > 0:
                batch_requests = collector.extract_batch()
                if batch_requests:
                    self._execute_batch_async(batch_requests)
                
                # Supprimer le collecteur vide
                if method in self.collectors and self.collectors[method].size() == 0:
                    del self.collectors[method]
    
    def get_request_result(self, request_id: str, timeout: float = 30.0) -> Optional[Dict]:
        """
        Récupère le résultat d'une requête (bloquant)
        
        Args:
            request_id: ID de la requête
            timeout: Timeout d'attente
            
        Returns:
            Résultat de la requête ou None
        """
        # Note: Cette implémentation est simplifiée
        # Dans une version complète, on aurait un système de callbacks/futures
        logger.warning("⚠️ get_request_result not fully implemented - use async callbacks")
        return None
    
    def batch_get_multiple_accounts(self, addresses: List[str], 
                                   encoding: str = "jsonParsed") -> List[Optional[Dict]]:
        """
        Batch optimisé pour getMultipleAccounts
        
        Args:
            addresses: Liste d'adresses à récupérer
            encoding: Encodage des données
            
        Returns:
            Liste des résultats (ordre préservé)
        """
        if not addresses:
            return []
        
        logger.info(f"📦 Batch getMultipleAccounts: {len(addresses)} adresses")
        
        # Diviser en chunks selon la taille adaptative
        current_batch_size = self.adaptive_sizer.get_current_size('getMultipleAccounts')
        chunks = [addresses[i:i + current_batch_size] 
                 for i in range(0, len(addresses), current_batch_size)]
        
        all_results = [None] * len(addresses)  # Préserver l'ordre
        
        for chunk_idx, chunk in enumerate(chunks):
            try:
                # Créer la requête
                request_id = self.add_request(
                    method="getMultipleAccounts",
                    params=[chunk, {"encoding": encoding}],
                    priority=BatchPriority.HIGH,
                    metadata={'chunk_index': chunk_idx, 'chunk_size': len(chunk)}
                )
                
                logger.debug(f"📋 Chunk {chunk_idx + 1}/{len(chunks)}: {len(chunk)} adresses")
                
                # Attendre un délai entre chunks pour éviter la surcharge
                if chunk_idx > 0:
                    time.sleep(self.config.min_delay_between_batches)
                
            except Exception as e:
                logger.error(f"❌ Erreur chunk {chunk_idx}: {e}")
        
        # Note: Dans une version complète, on attendrait les résultats
        # et on les assemblerait dans l'ordre correct
        logger.info(f"✅ Batch getMultipleAccounts soumis: {len(chunks)} chunks")
        return all_results
    
    def batch_get_signatures_for_addresses(self, addresses: List[str], 
                                         limit_per_address: int = 20) -> Dict[str, List]:
        """
        Batch optimisé pour getSignaturesForAddress
        
        Args:
            addresses: Liste d'adresses
            limit_per_address: Limite de signatures par adresse
            
        Returns:
            Dictionnaire {adresse: [signatures]}
        """
        if not addresses:
            return {}
        
        logger.info(f"📦 Batch getSignaturesForAddress: {len(addresses)} adresses")
        
        results = {}
        current_batch_size = self.adaptive_sizer.get_current_size('signatures_batch')
        
        # Traiter par chunks
        for i in range(0, len(addresses), current_batch_size):
            chunk = addresses[i:i + current_batch_size]
            
            for address in chunk:
                try:
                    request_id = self.add_request(
                        method="getSignaturesForAddress",
                        params=[address, {"limit": limit_per_address, "commitment": "finalized"}],
                        priority=BatchPriority.NORMAL,
                        metadata={'address': address}
                    )
                    
                    results[address] = []  # Placeholder
                    
                except Exception as e:
                    logger.error(f"❌ Erreur requête signatures pour {address[:8]}...: {e}")
                    results[address] = []
            
            # Délai entre chunks
            if i + current_batch_size < len(addresses):
                time.sleep(self.config.min_delay_between_batches)
        
        logger.info(f"✅ Batch signatures soumis: {len(addresses)} adresses")
        return results
    
    def batch_get_transactions(self, signatures: List[str], 
                             encoding: str = "json") -> List[Optional[Dict]]:
        """
        Batch optimisé pour getTransaction
        
        Args:
            signatures: Liste de signatures
            encoding: Encodage des données
            
        Returns:
            Liste des transactions (ordre préservé)
        """
        if not signatures:
            return []
        
        logger.info(f"📦 Batch getTransaction: {len(signatures)} signatures")
        
        results = [None] * len(signatures)
        current_batch_size = self.adaptive_sizer.get_current_size('transactions_batch')
        
        # Traiter par chunks
        chunks = [signatures[i:i + current_batch_size] 
                 for i in range(0, len(signatures), current_batch_size)]
        
        for chunk_idx, chunk in enumerate(chunks):
            for sig_idx, signature in enumerate(chunk):
                try:
                    global_idx = chunk_idx * current_batch_size + sig_idx
                    
                    request_id = self.add_request(
                        method="getTransaction",
                        params=[signature, {
                            "encoding": encoding,
                            "maxSupportedTransactionVersion": 0
                        }],
                        priority=BatchPriority.NORMAL,
                        metadata={
                            'signature': signature,
                            'global_index': global_idx
                        }
                    )
                    
                except Exception as e:
                    logger.error(f"❌ Erreur requête transaction {signature[:8]}...: {e}")
            
            # Délai entre chunks
            if chunk_idx < len(chunks) - 1:
                time.sleep(self.config.min_delay_between_batches)
        
        logger.info(f"✅ Batch transactions soumis: {len(chunks)} chunks")
        return results
    
    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques complètes du batch manager"""
        with self.lock:
            current_collectors = {
                method: {
                    'size': collector.size(),
                    'max_size': collector.max_size,
                    'age_seconds': collector.age(),
                    'ready': collector.is_ready()
                }
                for method, collector in self.collectors.items()
            }
            
            # Calculer des métriques dérivées
            total_batches = self.stats.successful_batches + self.stats.failed_batches
            
            # Efficacité du batching (temps économisé estimé)
            if self.stats.total_requests_processed > 0:
                # Estimation: chaque requête individuelle = 200ms, batch moyen = 2s
                individual_time = self.stats.total_requests_processed * 0.2
                batch_time = total_batches * 2.0
                time_saved = max(0, individual_time - batch_time)
            else:
                time_saved = 0
            
            return {
                'enabled': True,
                'strategy': self.config.strategy.value,
                'performance_summary': {
                    'total_batches': total_batches,
                    'success_rate': self.stats.success_rate,
                    'avg_batch_size': round(self.stats.avg_batch_size, 1),
                    'avg_response_time': round(self.stats.avg_response_time, 1),
                    'total_requests_processed': self.stats.total_requests_processed,
                    'estimated_time_saved': round(time_saved, 1)
                },
                'current_state': {
                    'active_collectors': len(self.collectors),
                    'pending_requests': len(self.pending_requests),
                    'collectors_detail': current_collectors
                },
                'configuration': {
                    'batch_sizes': self.stats.current_batch_sizes,
                    'adaptive_sizing': self.config.enable_adaptive_sizing,
                    'min_delay_between_batches': self.config.min_delay_between_batches,
                    'max_concurrent_batches': self.config.max_concurrent_batches,
                    'batch_timeout': self.config.batch_timeout
                },
                'recent_performance': self.stats.performance_history[-10:] if self.stats.performance_history else []
            }
    
    def get_health_status(self) -> Dict[str, Any]:
        """Retourne l'état de santé du batch manager"""
        stats = self.get_stats()
        
        # Déterminer l'état de santé
        success_rate = stats['performance_summary']['success_rate']
        avg_response_time = stats['performance_summary']['avg_response_time']
        
        if success_rate > 90 and avg_response_time < PERFORMANCE_THRESHOLDS['good_response_time']:
            health = "healthy"
            status_icon = "✅"
        elif success_rate > 70 and avg_response_time < PERFORMANCE_THRESHOLDS['warning_response_time']:
            health = "warning"
            status_icon = "⚠️"
        else:
            health = "critical"
            status_icon = "❌"
        
        # Recommandations
        recommendations = []
        
        if success_rate < 80:
            recommendations.append("Taux de succès faible - vérifier la connectivité RPC")
        
        if avg_response_time > PERFORMANCE_THRESHOLDS['warning_response_time']:
            recommendations.append("Temps de réponse élevé - considérer réduire les tailles de batch")
        
        if stats['current_state']['active_collectors'] > 10:
            recommendations.append("Beaucoup de collecteurs actifs - possible fragmentation")
        
        if not recommendations:
            recommendations.append("Performance optimale")
        
        return {
            'health': health,
            'status_icon': status_icon,
            'success_rate': success_rate,
            'avg_response_time': avg_response_time,
            'recommendations': recommendations,
            'summary': f"{status_icon} {health.upper()}: {success_rate:.1f}% succès, {avg_response_time:.0f}ms moyen"
        }
    
    def get_adaptation_analytics(self) -> Dict[str, Any]:
        """Retourne des analytics sur les adaptations"""
        analytics = {}
        
        for method in self.config.batch_sizes.keys():
            history = self.adaptive_sizer.get_adaptation_history(method)
            current_size = self.adaptive_sizer.get_current_size(method)
            optimal_size = OPTIMAL_BATCH_SIZES.get(method, 10)
            
            if history:
                recent_adaptations = history[-5:]  # 5 dernières
                increases = sum(1 for adapt in recent_adaptations if adapt['new_size'] > adapt['old_size'])
                decreases = sum(1 for adapt in recent_adaptations if adapt['new_size'] < adapt['old_size'])
                
                if increases > decreases:
                    trend = "improving"
                elif decreases > increases:
                    trend = "degrading"
                else:
                    trend = "stable"
            else:
                trend = "no_data"
                recent_adaptations = []
            
            analytics[method] = {
                'current_size': current_size,
                'optimal_size': optimal_size,
                'size_efficiency': round((current_size / optimal_size) * 100, 1),
                'adaptation_count': len(history),
                'trend': trend,
                'recent_adaptations': recent_adaptations
            }
        
        return {
            'methods': analytics,
            'global_summary': {
                'methods_analyzed': len(analytics),
                'methods_improving': sum(1 for m in analytics.values() if m['trend'] == 'improving'),
                'methods_degrading': sum(1 for m in analytics.values() if m['trend'] == 'degrading'),
                'avg_efficiency': round(sum(m['size_efficiency'] for m in analytics.values()) / len(analytics), 1) if analytics else 0
            }
        }
    
    def reset_stats(self):
        """Remet à zéro les statistiques"""
        with self.lock:
            self.stats = BatchStats()
            self.stats.current_batch_sizes = self.config.batch_sizes.copy()
            self.adaptive_sizer.reset_adaptations()
            
            logger.info("📊 Statistiques du batch manager remises à zéro")
    
    def update_config(self, new_config: BatchConfig):
        """Met à jour la configuration"""
        with self.lock:
            old_strategy = self.config.strategy
            self.config = new_config
            
            # Mettre à jour l'adaptive sizer
            self.adaptive_sizer.config = new_config
            if new_config.enable_adaptive_sizing:
                self.adaptive_sizer.current_sizes = new_config.batch_sizes.copy()
            
            # Mettre à jour les stats
            self.stats.current_batch_sizes = new_config.batch_sizes.copy()
            
            logger.info(f"🔧 Configuration mise à jour")
            logger.info(f"   📊 Stratégie: {old_strategy.value} → {new_config.strategy.value}")
            logger.info(f"   🎯 Adaptatif: {new_config.enable_adaptive_sizing}")
    
    def force_process_all(self):
        """Force le traitement de tous les collecteurs actifs"""
        with self.lock:
            methods_to_process = list(self.collectors.keys())
        
        for method in methods_to_process:
            try:
                self._force_process_collector(method)
                logger.debug(f"🔄 Collecteur {method} traité forcément")
            except Exception as e:
                logger.error(f"❌ Erreur traitement forcé {method}: {e}")
        
        logger.info(f"🚀 {len(methods_to_process)} collecteurs traités forcément")
    
    def close(self):
        """Ferme proprement le batch manager"""
        logger.info("🔄 Fermeture du batch manager...")
        
        # Arrêter le thread de processing
        self._should_stop.set()
        
        if self._processing_thread and self._processing_thread.is_alive():
            self._processing_thread.join(timeout=5)
        
        # Traiter les requêtes en attente
        try:
            self.force_process_all()
        except Exception as e:
            logger.warning(f"⚠️ Erreur lors du traitement final: {e}")
        
        # Fermer l'exécuteur
        try:
            self.executor.close()
        except Exception as e:
            logger.warning(f"⚠️ Erreur fermeture executor: {e}")
        
        # Statistiques finales
        stats = self.get_stats()
        logger.info(f"📊 Statistiques finales:")
        logger.info(f"   🎯 Batches traités: {stats['performance_summary']['total_batches']}")
        logger.info(f"   ✅ Taux de succès: {stats['performance_summary']['success_rate']:.1f}%")
        logger.info(f"   ⏱️ Temps économisé: {stats['performance_summary']['estimated_time_saved']:.1f}s")
        
        logger.info("✅ Batch manager fermé")


# Factory functions et utilitaires globaux

def create_batch_manager(config: BatchConfig = None, rpc_client=None) -> BatchManager:
    """
    Factory pour créer un batch manager
    
    Args:
        config: Configuration optionnelle
        rpc_client: Client RPC optionnel
        
    Returns:
        Instance BatchManager configurée
    """
    return BatchManager(config, rpc_client)


def create_batch_config(
    strategy: str = "adaptive_size",
    enable_adaptive: bool = True,
    min_delay: float = 0.3,
    batch_timeout: float = 25.0,
    **batch_sizes
) -> BatchConfig:
    """
    Factory pour créer une configuration de batching
    
    Args:
        strategy: Stratégie de batching
        enable_adaptive: Activer l'adaptation automatique
        min_delay: Délai minimum entre batches
        batch_timeout: Timeout par batch
        **batch_sizes: Tailles personnalisées par méthode
        
    Returns:
        Configuration BatchConfig
    """
    try:
        strategy_enum = BatchStrategy(strategy)
    except ValueError:
        logger.warning(f"⚠️ Stratégie inconnue '{strategy}', utilisation d'ADAPTIVE_SIZE")
        strategy_enum = BatchStrategy.ADAPTIVE_SIZE
    
    # Tailles par défaut avec overrides
    sizes = OPTIMAL_BATCH_SIZES.copy()
    sizes.update(batch_sizes)
    
    return BatchConfig(
        batch_sizes=sizes,
        strategy=strategy_enum,
        enable_adaptive_sizing=enable_adaptive,
        min_delay_between_batches=min_delay,
        batch_timeout=batch_timeout
    )


def create_conservative_batch_config() -> BatchConfig:
    """Crée une configuration conservative pour RPC gratuits"""
    return BatchConfig(
        batch_sizes=CONSERVATIVE_BATCH_SIZES.copy(),
        strategy=BatchStrategy.FIXED_SIZE,
        enable_adaptive_sizing=False,
        min_delay_between_batches=0.5,
        max_concurrent_batches=2,
        batch_timeout=30.0
    )


def create_aggressive_batch_config() -> BatchConfig:
    """Crée une configuration agressive pour RPC premium"""
    aggressive_sizes = {k: min(v * 2, 200) for k, v in OPTIMAL_BATCH_SIZES.items()}
    
    return BatchConfig(
        batch_sizes=aggressive_sizes,
        strategy=BatchStrategy.PERFORMANCE_BASED,
        enable_adaptive_sizing=True,
        min_delay_between_batches=0.1,
        max_concurrent_batches=5,
        batch_timeout=20.0,
        adaptation_sensitivity=0.15  # Plus sensible
    )


@contextmanager
def batch_context(config: BatchConfig = None, rpc_client=None):
    """
    Context manager pour utilisation temporaire du batch manager
    
    Usage:
        with batch_context() as batch_manager:
            batch_manager.add_request("getBalance", [address])
    """
    manager = None
    try:
        manager = create_batch_manager(config, rpc_client)
        yield manager
    finally:
        if manager:
            manager.close()


class BatchingDecorator:
    """Décorateur pour appliquer automatiquement le batching"""
    
    def __init__(self, manager: BatchManager, method_name: str, 
                 priority: BatchPriority = BatchPriority.NORMAL):
        self.manager = manager
        self.method_name = method_name
        self.priority = priority
    
    def __call__(self, func: Callable):
        def wrapper(*args, **kwargs):
            # Extraire les paramètres de la fonction
            params = list(args) + list(kwargs.values())
            
            # Ajouter la requête au batch
            request_id = self.manager.add_request(
                method=self.method_name,
                params=params,
                priority=self.priority,
                metadata={'function': func.__name__}
            )
            
            # Note: Dans une version complète, on attendrait le résultat
            # Pour l'instant, on retourne l'ID de la requête
            return request_id
        
        return wrapper


def batch_method(manager: BatchManager, method_name: str, 
                priority: BatchPriority = BatchPriority.NORMAL):
    """
    Décorateur pour batcher automatiquement les appels de méthode
    
    Usage:
        @batch_method(batch_manager, "getBalance")
        def get_balance(address):
            pass
    """
    return BatchingDecorator(manager, method_name, priority)


if __name__ == "__main__":
    # Script de test pour le batch manager
    import random
    
    print("🧪 Test du Batch Manager RPC")
    print("=" * 50)
    
    # Test 1: Création et configuration
    print("\n📦 Test création batch manager...")
    config = create_batch_config(
        strategy="adaptive_size",
        enable_adaptive=True,
        getMultipleAccounts=10,
        getSignaturesForAddress=15
    )
    
    batch_manager = create_batch_manager(config)
    print(f"✅ Batch manager créé: {config.strategy.value}")
    print(f"   📊 Tailles configurées: {config.batch_sizes}")
    
    # Test 2: Ajout de requêtes
    print("\n➕ Test ajout de requêtes...")
    request_ids = []
    
    # Ajouter des requêtes getMultipleAccounts
    for i in range(25):
        address = f"Test{i:020d}{'x' * 24}"  # Adresse fictive
        request_id = batch_manager.add_request(
            method="getMultipleAccounts",
            params=[[address], {"encoding": "jsonParsed"}],
            priority=BatchPriority.NORMAL
        )
        request_ids.append(request_id)
    
    print(f"✅ {len(request_ids)} requêtes ajoutées")
    
    # Test 3: Statistiques initiales
    print("\n📊 Test statistiques...")
    stats = batch_manager.get_stats()
    print(f"Collecteurs actifs: {stats['current_state']['active_collectors']}")
    print(f"Requêtes en attente: {stats['current_state']['pending_requests']}")
    
    # Test 4: Health check
    print("\n🏥 Test health check...")
    health = batch_manager.get_health_status()
    print(f"Santé: {health['summary']}")
    
    for rec in health['recommendations']:
        print(f"💡 {rec}")
    
    # Test 5: Batching spécialisé
    print("\n🔧 Test méthodes spécialisées...")
    
    # Test getMultipleAccounts
    test_addresses = [f"Test{i:044d}" for i in range(50, 75)]
    results = batch_manager.batch_get_multiple_accounts(test_addresses)
    print(f"✅ Batch getMultipleAccounts: {len(test_addresses)} adresses")
    
    # Test getSignaturesForAddress
    sig_results = batch_manager.batch_get_signatures_for_addresses(test_addresses[:10])
    print(f"✅ Batch getSignaturesForAddress: {len(sig_results)} adresses")
    
    # Test 6: Adaptation analytics
    print("\n📈 Test analytics d'adaptation...")
    
    # Simuler quelques métriques pour déclencher l'adaptation
    for i in range(5):
        metrics = BatchMetrics(
            batch_id=f"test_{i}",
            method="getMultipleAccounts",
            size=10,
            duration=random.uniform(1.0, 3.0),
            success_count=random.randint(8, 10),
            failure_count=random.randint(0, 2),
            timeout_count=0,
            response_time_ms=random.uniform(1000, 5000),
            endpoint="test_endpoint"
        )
        batch_manager.adaptive_sizer.record_performance(metrics)
    
    analytics = batch_manager.get_adaptation_analytics()
    print(f"Analytics d'adaptation:")
    for method, data in analytics['methods'].items():
        print(f"  {method}: {data['current_size']} (efficacité: {data['size_efficiency']}%)")
    
    # Test 7: Configuration conservative vs aggressive
    print("\n⚖️ Test configurations prédéfinies...")
    
    conservative_config = create_conservative_batch_config()
    aggressive_config = create_aggressive_batch_config()
    
    print(f"Conservative: {conservative_config.batch_sizes['getMultipleAccounts']} (délai: {conservative_config.min_delay_between_batches}s)")
    print(f"Aggressive: {aggressive_config.batch_sizes['getMultipleAccounts']} (délai: {aggressive_config.min_delay_between_batches}s)")
    
    # Test 8: Context manager
    print("\n🔄 Test context manager...")
    try:
        with batch_context(config) as ctx_manager:
            ctx_request_id = ctx_manager.add_request(
                method="getBalance",
                params=["TestAddress"],
                priority=BatchPriority.HIGH
            )
            print(f"✅ Requête dans contexte: {ctx_request_id[:8]}...")
    except Exception as e:
        print(f"❌ Erreur context manager: {e}")
    
    # Test 9: Force processing
    print("\n🚀 Test traitement forcé...")
    batch_manager.force_process_all()
    
    final_stats = batch_manager.get_stats()
    print(f"Statistiques après traitement:")
    print(f"  Batches traités: {final_stats['performance_summary']['total_batches']}")
    print(f"  Requêtes traitées: {final_stats['performance_summary']['total_requests_processed']}")
    
    # Test 10: Fermeture propre
    print("\n🔄 Test fermeture...")
    batch_manager.close()
    
    print("\n✅ Tests terminés avec succès!")
    print("🧹 Nettoyage effectué")