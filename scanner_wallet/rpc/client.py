
#!/usr/bin/env python3
"""
Client RPC pour Solana avec système de fallback intelligent et gestion avancée des erreurs
Gère la communication avec les endpoints RPC Solana avec résilience et optimisation
"""



import requests
import time
import logging
import random
from typing import Dict, List, Optional, Any, Union, Tuple, Callable, TYPE_CHECKING
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock, RLock
from collections import defaultdict, deque
from contextlib import contextmanager
import hashlib
import json
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry 

# Imports des modules internes
try:
    from core.config import get_config
    from core.exceptions import (
        RPCError, RPCTimeoutError, RPCRateLimitError, 
        RPCEndpointUnavailableError, RPCResponseError,
        create_rpc_error, handle_rpc_errors
    )
    from core.logger import get_logger
    from utils.helpers import exponential_backoff, CircularBuffer, get_current_timestamp,retry_with_backoff
    from utils.constants import (
        DEFAULT_RPC_ENDPOINTS, QUICKNODE_FREE_RPS_LIMIT,
        RPC_TIMEOUT_DEFAULT, RPC_TIMEOUT_BATCH, CRITICAL_RPC_TIMEOUT,
        MAX_RPC_RETRIES, RPC_RETRY_DELAY_BASE
    )
    # Dépendances RPC
    from .rate_limiter import RateLimiter
    from .endpoints import RPCEndpointManager

except ImportError as e:
    logging.warning(f"Import error in RPC client: {e}")
    # Fallbacks pour développement
    logger = logging.getLogger(__name__)
    
    # Constantes par défaut
    DEFAULT_RPC_ENDPOINTS = [
        "https://api.mainnet-beta.solana.com",
        "https://rpc.ankr.com/solana",
        "https://solana.public-rpc.com"
    ]
    RPC_TIMEOUT_DEFAULT = 15
    RPC_TIMEOUT_BATCH = 25
    CRITICAL_RPC_TIMEOUT = 30
    MAX_RPC_RETRIES = 3
    RPC_RETRY_DELAY_BASE = 2
    QUICKNODE_FREE_TIER_RPS = 100

    class RPCError(Exception):
        pass

    class RPCRateLimitError(RPCError):
        def __init__(self, endpoint, retry_after):
            self.endpoint = endpoint
            self.retry_after = retry_after
            super().__init__(f"Rate limit hit on {endpoint}, retry after {retry_after}s")
    
    class RPCTimeoutError(RPCError):
        def __init__(self, endpoint, timeout, method):
            self.endpoint = endpoint
            self.timeout = timeout
            self.method = method
            super().__init__(f"Timeout {timeout}s for {method} on {endpoint}")
    
    class RPCEndpointUnavailableError(RPCError):
        def __init__(self, endpoints, message):
            self.endpoints = endpoints
            super().__init__(message)
    
    class RPCResponseError(RPCError):
        def __init__(self, method, message, code):
            self.method = method
            self.code = code
            super().__init__(f"RPC error {code} for {method}: {message}")

    def exponential_backoff(attempt, max_delay=30.0):
        """Calcule un délai d'attente exponentiel avec jitter"""
        delay = min(max_delay, (2 ** attempt) + random.uniform(0, 1))
        return delay 
        
# Configuration du logger
logger = logging.getLogger(__name__)

# Variables globales pour le singleton
_default_rpc_client: Optional['RPCClient'] = None


@dataclass
class EndpointMetrics:
    """Métriques pour un endpoint RPC spécifique"""
    url: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_response_time: float = 0.0
    last_error_time: Optional[float] = None
    last_success_time: Optional[float] = None
    consecutive_errors: int = 0
    rate_limit_hits: int = 0
    average_latency: float = 0.0
    health_score: float = 100.0
    is_available: bool = True
    last_health_check: Optional[float] = None
    response_times: deque = field(default_factory=lambda: deque(maxlen=100))
    
    @property
    def success_rate(self) -> float:
        """Taux de succès de l'endpoint"""
        if self.total_requests == 0:
            return 0.0
        return (self.successful_requests / self.total_requests) * 100
    
    @property
    def avg_response_time(self) -> float:
        """Temps de réponse moyen"""
        if not self.response_times:
            return 0.0
        return sum(self.response_times) / len(self.response_times)
    
    def update_success(self, response_time: float):
        """Met à jour les métriques après un succès"""
        self.total_requests += 1
        self.successful_requests += 1
        self.consecutive_errors = 0
        self.response_times.append(response_time)
        self.last_success_time = time.time()
        self.is_available = True
        self._update_health_score()
    
    def update_failure(self, is_rate_limit: bool = False):
        """Met à jour les métriques après un échec"""
        self.total_requests += 1
        self.failed_requests += 1
        self.consecutive_errors += 1
        self.last_error_time = time.time()
        
        if is_rate_limit:
            self.rate_limit_hits += 1
        
        # Marquer comme indisponible après trop d'erreurs
        if self.consecutive_errors >= 5:
            self.is_available = False
        
        self._update_health_score()
    
    def _update_health_score(self):
        """Calcule le score de santé de l'endpoint"""
        score = 100.0
        
        # Pénalité pour taux d'échec
        if self.total_requests > 0:
            failure_rate = (self.failed_requests / self.total_requests) * 100
            score -= failure_rate * 0.5
        
        # Pénalité pour erreurs consécutives
        score -= self.consecutive_errors * 10
        
        # Pénalité pour latence élevée
        if self.avg_response_time > 5000:  # 5 secondes
            score -= 20
        elif self.avg_response_time > 2000:  # 2 secondes
            score -= 10
        
        # Pénalité pour rate limits
        score -= self.rate_limit_hits * 5
        
        # Bonus pour disponibilité récente
        if self.last_success_time:
            time_since_success = time.time() - self.last_success_time
            if time_since_success < 60:  # Succès dans la dernière minute
                score += 10
        
        self.health_score = max(0, min(100, score))


@dataclass
class RPCRequest:
    """Représente une requête RPC"""
    method: str
    params: List[Any]
    id: Optional[Union[str, int]] = None
    priority: int = 0  # 0 = normal, 1 = high, 2 = critical
    max_retries: Optional[int] = None
    timeout: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    
    def to_json(self) -> Dict:
        """Convertit en format JSON-RPC"""
        return {
            "jsonrpc": "2.0",
            "id": self.id or 1,
            "method": self.method,
            "params": self.params
        }
    
    @property
    def age(self) -> float:
        """Age de la requête en secondes"""
        return time.time() - self.created_at


class RPCClient:
    """Client RPC principal avec gestion intelligente des endpoints"""
    
    def __init__(self, config=None):
        """Initialise le client RPC avec configuration"""
        self.config = config or get_config()
        self.logger = logger
        self._setup_http_session()
        # Configuration des endpoints
        self._setup_endpoints()
        
        # Métriques et état
        self.endpoints_metrics: Dict[str, EndpointMetrics] = {}
        self.current_endpoint_index = 0
        self.total_requests = 0
        self.total_failures = 0
        
        # Thread safety
        self._lock = RLock()
        self._endpoint_locks: Dict[str, Lock] = defaultdict(Lock)
        
        # Cache de requêtes (optionnel)
        self.cache_enabled = getattr(self.config.rpc, 'enable_cache', False)
        self.request_cache: Dict[str, Tuple[Any, float]] = {}
        self.cache_ttl = getattr(self.config.rpc, 'cache_ttl', 60)
        
        # Rate limiting par endpoint
        self.rate_limiters: Dict[str, 'EndpointRateLimiter'] = {}
        
        # Statistiques de session
        self.session_stats = {
            'start_time': time.time(),
            'requests_by_method': defaultdict(int),
            'errors_by_type': defaultdict(int),
            'cache_hits': 0,
            'cache_misses': 0,
            'endpoint_switches': 0
        }
        
        # Initialiser les métriques pour chaque endpoint
        self._initialize_metrics()
        
        self.logger.info(f"🔌 Client RPC initialisé avec {len(self.endpoints)} endpoints")
    
    def _setup_http_session(self):
        """Configure la session HTTP avec pool de connexions réutilisables"""
        self.session = requests.Session()
        
        # Configuration du pool de connexions
        pool_config = {
            'pool_connections': getattr(self.config.rpc, 'pool_connections', 10),
            'pool_maxsize': getattr(self.config.rpc, 'pool_maxsize', 20),
            'max_retries': 0,  # Géré manuellement par notre logique
            'pool_block': False  # Non-bloquant si pool plein
        }
        
        # Créer l'adaptateur avec pool personnalisé
        adapter = HTTPAdapter(**pool_config)
        
        # Monter l'adaptateur pour HTTP et HTTPS
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        
        # Configuration des timeouts par défaut
        self.session_timeout = getattr(self.config.rpc, 'session_timeout', 30.0)
        
        # Headers par défaut pour toutes les requêtes
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'SolanaWalletMonitor/2.0',
            'Connection': 'keep-alive'  # Forcer keep-alive
        })
        
        self.logger.info(
            f"🔗 Session HTTP configurée: "
            f"{pool_config['pool_connections']} connexions, "
            f"pool max {pool_config['pool_maxsize']}"
        )
    
    def _setup_endpoints(self):
        """Configure les endpoints RPC depuis la configuration"""
        self.endpoints = []
        
        # Ajouter l'endpoint QuickNode s'il est configuré
        if hasattr(self.config.rpc, 'quicknode_endpoint') and self.config.rpc.quicknode_endpoint:
            self.endpoints.append({
                'url': self.config.rpc.quicknode_endpoint,
                'type': 'premium',
                'priority': 1,
                'rate_limit': QUICKNODE_FREE_RPS_LIMIT
            })
            self.logger.info(f"✅ Endpoint QuickNode configuré: {self.config.rpc.quicknode_endpoint}")

        
        # Ajouter les endpoints de fallback configurés
        if hasattr(self.config.rpc, 'fallback_endpoints') and self.config.rpc.fallback_endpoints:
            fallback_endpoints = self.config.rpc.fallback_endpoints
            self.logger.info(f"Configuring {len(fallback_endpoints)} fallback endpoints from config.")
            for endpoint in fallback_endpoints:
                self.endpoints.append({
                    'url': endpoint,
                    'type': 'public',
                    'priority': 2,
                    'rate_limit': 5
                })
        
        if not self.endpoints:
            self.logger.warning("⚠️ No RPC endpoints configured. Using default public endpoints.")
            for endpoint in DEFAULT_RPC_ENDPOINTS:
                self.endpoints.append({
                    'url': endpoint,
                    'type': 'public',
                    'priority': 3,
                    'rate_limit': 5
                })

    
    def _initialize_metrics(self):
        """Initialise les métriques pour chaque endpoint"""
        with self._lock:
            for endpoint_config in self.endpoints:
                url = endpoint_config['url']
                if url not in self.endpoints_metrics:
                    self.endpoints_metrics[url] = EndpointMetrics(url=url)
                    self.rate_limiters[url] = EndpointRateLimiter(
                        max_rps=endpoint_config['rate_limit']
                    )
    
    def get_current_endpoint(self) -> Dict:
        """Retourne l'endpoint actuel"""
        with self._lock:
            return self.endpoints[self.current_endpoint_index]
    
    def switch_endpoint(self, reason: str = "unknown"):
        """Bascule vers le prochain endpoint disponible"""
        with self._lock:
            old_endpoint = self.endpoints[self.current_endpoint_index]['url']
            
            # Trouver le prochain endpoint disponible
            attempts = 0
            while attempts < len(self.endpoints):
                self.current_endpoint_index = (self.current_endpoint_index + 1) % len(self.endpoints)
                new_endpoint = self.endpoints[self.current_endpoint_index]
                
                # Vérifier si l'endpoint est disponible
                metrics = self.endpoints_metrics[new_endpoint['url']]
                if metrics.is_available and metrics.health_score > 20:
                    self.session_stats['endpoint_switches'] += 1
                    self.logger.info(
                        f"🔄 Switch endpoint: {old_endpoint[:50]}. → {new_endpoint['url'][:50]}. "
                        f"(Raison: {reason})"
                    )
                    return new_endpoint
                
                attempts += 1
            
            # Si aucun endpoint sain n'est trouvé, réinitialiser et utiliser le meilleur
            self._reset_unhealthy_endpoints()
            best_endpoint = self._get_best_endpoint()
            self.current_endpoint_index = self.endpoints.index(best_endpoint)
            
            self.logger.warning(f"⚠️ Tous les endpoints sont dégradés, utilisation du meilleur disponible")
            return best_endpoint
    
    def _get_best_endpoint(self) -> Dict:
        """Retourne le meilleur endpoint selon les métriques"""
        with self._lock:
            best_score = -1
            best_endpoint = self.endpoints[0]
            
            for endpoint_config in self.endpoints:
                metrics = self.endpoints_metrics[endpoint_config['url']]
                
                # Score composite basé sur santé et priorité
                score = metrics.health_score - (endpoint_config['priority'] * 10)
                
                if score > best_score:
                    best_score = score
                    best_endpoint = endpoint_config
            
            return best_endpoint
    
    def _reset_unhealthy_endpoints(self):
        """Réinitialise les endpoints marqués comme indisponibles après un délai"""
        with self._lock:
            current_time = time.time()
            
            for url, metrics in self.endpoints_metrics.items():
                if not metrics.is_available and metrics.last_error_time:
                    # Réactiver après 5 minutes
                    if current_time - metrics.last_error_time > 300:
                        metrics.is_available = True
                        metrics.consecutive_errors = 0
                        metrics.health_score = 50.0  # Score de départ après reset
                        self.logger.info(f"♻️ Endpoint réactivé: {url[:50]}.")
    
    def _get_cache_key(self, method: str, params: List) -> str:
        """Génère une clé de cache pour une requête"""
        params_str = json.dumps(params, sort_keys=True)
        return hashlib.md5(f"{method}:{params_str}".encode()).hexdigest()
    
    def _check_cache(self, method: str, params: List) -> Optional[Any]:
        """Vérifie le cache pour une requête"""
        if not self.cache_enabled:
            return None
        
        cache_key = self._get_cache_key(method, params)
        
        if cache_key in self.request_cache:
            result, timestamp = self.request_cache[cache_key]
            
            # Vérifier si le cache est encore valide
            if time.time() - timestamp < self.cache_ttl:
                self.session_stats['cache_hits'] += 1
                self.logger.debug(f"✅ Cache hit pour {method}")
                return result
            else:
                # Cache expiré
                del self.request_cache[cache_key]
        
        self.session_stats['cache_misses'] += 1
        return None
    
    def _update_cache(self, method: str, params: List, result: Any):
        """Met à jour le cache avec un résultat"""
        if not self.cache_enabled:
            return
        
        cache_key = self._get_cache_key(method, params)
        self.request_cache[cache_key] = (result, time.time())
        
        # Nettoyer le cache si trop grand
        if len(self.request_cache) > 1000:
            self._cleanup_cache()
    
    def _cleanup_cache(self):
        """Nettoie les entrées expirées du cache"""
        with self._lock:
            current_time = time.time()
            expired_keys = [
                key for key, (_, timestamp) in self.request_cache.items()
                if current_time - timestamp > self.cache_ttl
            ]
            
            for key in expired_keys:
                del self.request_cache[key]
    
    def call(self, method: str, params: List = None, 
             priority: int = 0, use_cache: bool = True) -> Optional[Dict]:
        """
        Effectue un appel RPC avec gestion d'erreurs et fallback
        
        Args:
            method: Méthode RPC à appeler
            params: Paramètres de la méthode
            priority: Priorité de la requête (0=normal, 1=high, 2=critical)
            use_cache: Utiliser le cache si disponible
        
        Returns:
            Résultat de l'appel RPC ou None si échec
        """
        params = params or []
        
        # Vérifier le cache
        if use_cache:
            cached_result = self._check_cache(method, params)
            if cached_result is not None:
                return cached_result
        
        # Créer la requête
        request = RPCRequest(
            method=method,
            params=params,
            priority=priority,
            max_retries=getattr(self.config.rpc, 'max_retries', MAX_RPC_RETRIES),
            timeout=self._get_timeout_for_method(method)
        )
        
        # Exécuter avec retry et fallback
        result = self._execute_with_fallback(request)
        
        # Mettre à jour le cache si succès
        if result and use_cache:
            self._update_cache(method, params, result)
        
        # Mettre à jour les statistiques
        self.session_stats['requests_by_method'][method] += 1
        
        return result
    
    def _get_timeout_for_method(self, method: str) -> float:
        """Retourne le timeout approprié pour une méthode"""
        # Méthodes critiques avec timeout plus long
        critical_methods = [
            'getTransaction', 'getTransactions', 
            'getBlock', 'getBlocks'
        ]
        
        # Méthodes de batch avec timeout intermédiaire
        batch_methods = [
            'getMultipleAccounts', 'getSignaturesForAddress',
            'getTokenAccountsByOwner'
        ]
        
        if method in critical_methods:
            return getattr(self.config.rpc, 'timeout', CRITICAL_RPC_TIMEOUT)
        elif method in batch_methods:
            return getattr(self.config.rpc, 'timeout', RPC_TIMEOUT_BATCH)
        else:
            return getattr(self.config.rpc, 'timeout', RPC_TIMEOUT_DEFAULT)
    
    def _execute_with_fallback(self, request: RPCRequest) -> Optional[Dict]:
        """Exécute une requête avec retry et fallback entre endpoints"""
        max_retries = request.max_retries or MAX_RPC_RETRIES
        last_error = None
        endpoints_tried = set()
        
        for attempt in range(max_retries):
            endpoint_config = self.get_current_endpoint()
            endpoint_url = endpoint_config['url']
            
            # Marquer cet endpoint comme essayé
            endpoints_tried.add(endpoint_url)
            
            # Vérifier le rate limiting
            rate_limiter = self.rate_limiters[endpoint_url]
            if not rate_limiter.can_proceed():
                wait_time = rate_limiter.get_wait_time()
                self.logger.warning(
                    f"⏳ Rate limit atteint pour {endpoint_url[:50]}., "
                    f"attente {wait_time:.2f}s"
                )
                
                # Si c'est une requête prioritaire, essayer un autre endpoint
                if request.priority > 0 and len(endpoints_tried) < len(self.endpoints):
                    self.switch_endpoint("rate_limit")
                    continue
                else:
                    time.sleep(wait_time)
            
            try:
                # Exécuter la requête
                result = self._execute_single_request(request, endpoint_config)
                
                if result:
                    # Succès - mettre à jour les métriques
                    rate_limiter.record_request()
                    return result
                
            except RPCRateLimitError as e:
                last_error = e
                self.session_stats['errors_by_type']['rate_limit'] += 1
                
                # Marquer le rate limit hit
                metrics = self.endpoints_metrics[endpoint_url]
                metrics.update_failure(is_rate_limit=True)
                
                # Basculer vers un autre endpoint
                if len(endpoints_tried) < len(self.endpoints):
                    self.switch_endpoint("rate_limit")
                else:
                    # Attendre avant de réessayer
                    wait_time = exponential_backoff(attempt, max_delay=30.0)
                    self.logger.info(f"⏳ Attente {wait_time:.1f}s avant retry.")
                    time.sleep(wait_time)
                
            except RPCTimeoutError as e:
                last_error = e
                self.session_stats['errors_by_type']['timeout'] += 1
                
                # Timeout - essayer un autre endpoint
                if len(endpoints_tried) < len(self.endpoints):
                    self.switch_endpoint("timeout")
                
            except RPCEndpointUnavailableError as e:
                last_error = e
                self.session_stats['errors_by_type']['unavailable'] += 1
                
                # Endpoint indisponible - basculer
                metrics = self.endpoints_metrics[endpoint_url]
                metrics.update_failure()
                
                if len(endpoints_tried) < len(self.endpoints):
                    self.switch_endpoint("unavailable")
                
            except Exception as e:
                last_error = e
                self.session_stats['errors_by_type']['other'] += 1
                self.logger.error(f"❌ Erreur inattendue: {e}")
                
                # Erreur générique - essayer un autre endpoint après un délai
                if attempt < max_retries - 1:
                    time.sleep(exponential_backoff(attempt))
        
        # Échec après tous les retries
        self.total_failures += 1
        self.logger.error(
            f"❌ Échec définitif pour {request.method} après {max_retries} tentatives. "
            f"Dernière erreur: {last_error}"
        )
        
        return None
    
    def _execute_single_request(self, request: RPCRequest, 
                               endpoint_config: Dict) -> Optional[Dict]:
        """Exécute une seule requête RPC"""
        endpoint_url = endpoint_config['url']
        metrics = self.endpoints_metrics[endpoint_url]
        
        # Préparer la requête
        payload = request.to_json()
        headers = self._get_headers(endpoint_config)
        
        start_time = time.time()
        
        try:
            # Logging de debug
            self.logger.debug(f"🔌 RPC {request.method} vers {endpoint_url[:50]}.")
            
            # Faire la requête HTTP
            response = self.session.post(
                endpoint_url,
                json=payload,
                headers=self._get_headers(endpoint_config),  # Headers spécifiques
                timeout=request.timeout or RPC_TIMEOUT_DEFAULT
            )
            
            response_time = (time.time() - start_time) * 1000  # En millisecondes
            
            # Vérifier le statut HTTP
            if response.status_code == 429:
                # Rate limit
                retry_after = int(response.headers.get('Retry-After', 60))
                raise RPCRateLimitError(endpoint_url, retry_after)
            
            elif response.status_code >= 500:
                # Erreur serveur
                raise RPCEndpointUnavailableError(
                    [endpoint_url],
                    f"HTTP {response.status_code}: {response.text[:200]}"
                )
            
            elif response.status_code == 408:
                # Timeout
                raise RPCTimeoutError(endpoint_url, request.timeout, request.method)
            
            elif response.status_code != 200:
                # Autre erreur HTTP
                response.raise_for_status()
            
            # Parser la réponse JSON
            result = response.json()
            
            # Vérifier les erreurs RPC
            if 'error' in result:
                error = result['error']
                error_message = error.get('message', 'Unknown error')
                error_code = error.get('code', -1)
                
                # Log l'erreur RPC
                self.logger.warning(
                    f"⚠️ Erreur RPC {error_code}: {error_message} "
                    f"pour {request.method}"
                )
                
                raise RPCResponseError(request.method, error_message, error_code)
            
            # Succès - mettre à jour les métriques
            metrics.update_success(response_time)
            self.total_requests += 1
            
            self.logger.debug(
                f"✅ RPC {request.method} réussi en {response_time:.0f}ms"
            )
            
            return result
            
        except requests.exceptions.Timeout:
            metrics.update_failure()
            raise RPCTimeoutError(endpoint_url, request.timeout, request.method)
            
        except requests.exceptions.ConnectionError as e:
            metrics.update_failure()
            raise RPCEndpointUnavailableError([endpoint_url], str(e))
            
        except requests.exceptions.RequestException as e:
            metrics.update_failure()
            raise RPCError(f"Erreur requête: {e}")
    
    def _get_headers(self, endpoint_config: Dict) -> Dict[str, str]:
        """Retourne les headers pour une requête"""
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'SolanaWalletMonitor/2.0'
        }
        
        # Ajouter l'authentification pour QuickNode si disponible
        if endpoint_config['type'] == 'premium':
            api_key = getattr(self.config.rpc, 'quicknode_api_key', None)
            if api_key:
                headers['Authorization'] = f'Bearer {api_key}'
        
        return headers
    
    def batch_call(self, requests: List[Dict[str, Any]]) -> List[Optional[Dict]]:
        """
        Effectue plusieurs appels RPC en batch
        
        Args:
            requests: Liste de dicts avec 'method' et 'params'
        
        Returns:
            Liste des résultats (None pour les échecs)
        """
        batch_requests = []
        
        for i, req in enumerate(requests):
            batch_requests.append({
                "jsonrpc": "2.0",
                "id": i,
                "method": req['method'],
                "params": req.get('params', [])
            })
        
        endpoint_config = self.get_current_endpoint()
        endpoint_url = endpoint_config['url']
        
        try:
            
            response = self.session.post(
                endpoint_url,
                json=batch_requests,
                headers=self._get_headers(endpoint_config),
                timeout=RPC_TIMEOUT_BATCH
            )
            
            if response.status_code == 200:
                batch_results = response.json()
                
                # Organiser les résultats par ID
                results_by_id = {}
                for result in batch_results:
                    if 'id' in result:
                        results_by_id[result['id']] = result
                
                # Retourner dans l'ordre original
                results = []
                for i in range(len(requests)):
                    if i in results_by_id:
                        results.append(results_by_id[i])
                    else:
                        results.append(None)
                
                return results
            
        except Exception as e:
            self.logger.error(f"❌ Erreur batch RPC: {e}")
        
        # En cas d'échec, fallback vers appels individuels
        return [
            self.call(req['method'], req.get('params', []))
            for req in requests
        ]
    
    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques du client RPC"""
        with self._lock:
            uptime = time.time() - self.session_stats['start_time']
            
            # Statistiques par endpoint
            endpoints_stats = []
            for endpoint_config in self.endpoints:
                url = endpoint_config['url']
                metrics = self.endpoints_metrics[url]
                
                endpoints_stats.append({
                    'url': url[:50] + '.' if len(url) > 50 else url,
                    'type': endpoint_config['type'],
                    'health_score': round(metrics.health_score, 1),
                    'success_rate': round(metrics.success_rate, 1),
                    'avg_response_time': round(metrics.avg_response_time, 0),
                    'total_requests': metrics.total_requests,
                    'rate_limit_hits': metrics.rate_limit_hits,
                    'is_available': metrics.is_available,
                    'consecutive_errors': metrics.consecutive_errors
                })
            
            return {
                'uptime_seconds': int(uptime),
                'total_requests': self.total_requests,
                'total_failures': self.total_failures,
                'success_rate': round(
                    ((self.total_requests - self.total_failures) / max(self.total_requests, 1)) * 100,
                    1
                ),
                'current_endpoint': self.get_current_endpoint()['url'][:50] + '.',
                'endpoint_switches': self.session_stats['endpoint_switches'],
                'cache_enabled': self.cache_enabled,
                'cache_stats': {
                    'hits': self.session_stats['cache_hits'],
                    'misses': self.session_stats['cache_misses'],
                    'hit_rate': round(
                        (self.session_stats['cache_hits'] / 
                         max(self.session_stats['cache_hits'] + self.session_stats['cache_misses'], 1)) * 100,
                        1
                    )
                },
                'requests_by_method': dict(self.session_stats['requests_by_method']),
                'errors_by_type': dict(self.session_stats['errors_by_type']),
                'endpoints': endpoints_stats,
                'connection_pool': self.get_connection_stats()
            }
    
    def get_connection_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques du pool de connexions"""
        stats = {
            'session_active': self.session is not None,
            'adapters_mounted': len(self.session.adapters) if self.session else 0
        }
        
        # Statistiques détaillées si disponibles
        if self.session:
            for prefix, adapter in self.session.adapters.items():
                if hasattr(adapter, 'poolmanager'):
                    pool_stats = {
                        f'{prefix}_pools': len(adapter.poolmanager.pools),
                        f'{prefix}_pool_connections': getattr(adapter.config, 'pool_connections', 'N/A'),
                        f'{prefix}_pool_maxsize': getattr(adapter.config, 'pool_maxsize', 'N/A')
                    }
                    stats.update(pool_stats)
        
        return stats
    
    def health_check(self) -> Dict[str, Any]:
        """Effectue un health check de tous les endpoints"""
        health_results = {}
        
        for endpoint_config in self.endpoints:
            url = endpoint_config['url']
            
            try:
                start_time = time.time()
                
                # Test simple avec getHealth
                response = self.session.post(
                    url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getHealth",
                        "params": []
                    },
                    headers=self._get_headers(endpoint_config),
                    timeout=5.0
                )

                response_time = (time.time() - start_time) * 1000  # En millisecondes
                
                if response.status_code == 200:
                    result = response.json()
                    
                    # Mettre à jour les métriques
                    metrics = self.endpoints_metrics[url]
                    metrics.update_success(response_time)
                    
                    health_results[url] = {
                        'status': 'healthy',
                        'response_time_ms': round(response_time, 0),
                        'method': 'getHealth'
                    }
                    
                    logger.debug(f"✅ Health check OK pour {url[:50]}. ({response_time:.0f}ms)")
                else:
                    raise requests.RequestException(f"HTTP {response.status_code}")
                    
            except Exception as e:
                health_results[url] = {
                    'status': 'unhealthy',
                    'error': str(e),
                    'method': 'getHealth'
                }
                
                # Mettre à jour les métriques d'échec
                metrics = self.endpoints_metrics[url]
                metrics.update_failure()
                
                logger.warning(f"❌ Health check failed pour {url[:50]}.: {e}")
        
        # Analyser les résultats globaux
        healthy_count = sum(1 for result in health_results.values() if result['status'] == 'healthy')
        total_count = len(health_results)
        
        overall_status = 'healthy' if healthy_count == total_count else \
                        'degraded' if healthy_count > 0 else 'critical'
        
        return {
            'overall_status': overall_status,
            'healthy_endpoints': healthy_count,
            'total_endpoints': total_count,
            'endpoints': health_results,
            'timestamp': time.time()
        }
    
    def get_best_endpoints(self, count: int = 3) -> List[Dict]:
        """Retourne les meilleurs endpoints selon leurs métriques"""
        with self._lock:
            endpoint_scores = []
            
            for endpoint_config in self.endpoints:
                url = endpoint_config['url']
                metrics = self.endpoints_metrics[url]
                
                # Score composite
                score = metrics.health_score
                
                # Bonus pour endpoints premium
                if endpoint_config['type'] == 'premium':
                    score += 20
                
                endpoint_scores.append({
                    'endpoint': endpoint_config,
                    'metrics': metrics,
                    'score': score
                })
            
            # Trier par score décroissant
            endpoint_scores.sort(key=lambda x: x['score'], reverse=True)
            
            return [{
                'url': item['endpoint']['url'],
                'type': item['endpoint']['type'],
                'health_score': round(item['metrics'].health_score, 1),
                'success_rate': round(item['metrics'].success_rate, 1),
                'avg_response_time': round(item['metrics'].avg_response_time, 0)
            } for item in endpoint_scores[:count]]
    
    def reset_statistics(self):
        """Remet à zéro les statistiques de session"""
        with self._lock:
            self.total_requests = 0
            self.total_failures = 0
            
            # Reset des métriques par endpoint
            for metrics in self.endpoints_metrics.values():
                metrics.total_requests = 0
                metrics.successful_requests = 0
                metrics.failed_requests = 0
                metrics.consecutive_errors = 0
                metrics.rate_limit_hits = 0
                metrics.is_available = True
                metrics.response_times.clear()
            
            # Reset des stats de session
            self.session_stats = {
                'start_time': time.time(),
                'requests_by_method': defaultdict(int),
                'errors_by_type': defaultdict(int),
                'cache_hits': 0,
                'cache_misses': 0,
                'endpoint_switches': 0
            }
            
            # Reset du cache
            self.request_cache.clear()
            
            logger.info("📊 Statistiques RPC réinitialisées")
    
    def close(self):
        """Ferme le client RPC et nettoie les ressources"""
        try:
            
            if hasattr(self, 'session') and self.session:
                self.session.close()
                self.logger.debug("🔗 Session HTTP fermée")
                
            # Nettoyage final du cache
            self.request_cache.clear()
            
            # Log des statistiques finales
            uptime = time.time() - self.session_stats['start_time']
            success_rate = ((self.total_requests - self.total_failures) / max(self.total_requests, 1)) * 100
            
            logger.info(f"🔌 Fermeture client RPC:")
            logger.info(f"   ⏱️ Uptime: {uptime / 60:.1f} minutes")
            logger.info(f"   🔢 Requêtes totales: {self.total_requests}")
            logger.info(f"   ✅ Taux de succès: {success_rate:.1f}%")
            logger.info(f"   🔄 Changements d'endpoint: {self.session_stats['endpoint_switches']}")
            
        except Exception as e:
            logger.warning(f"⚠️ Erreur lors de la fermeture: {e}")


class EndpointRateLimiter:
    """Rate limiter spécifique pour un endpoint RPC"""
    
    def __init__(self, max_rps: float = 5.0):
        self.max_rps = max_rps
        self.requests = deque()  # Timestamps des requêtes
        self.lock = Lock()
        
    def can_proceed(self) -> bool:
        """Vérifie si on peut faire une requête maintenant"""
        with self.lock:
            now = time.time()
            
            # Nettoyer les anciennes requêtes (plus de 1 seconde)
            while self.requests and now - self.requests[0] > 1.0:
                self.requests.popleft()
            
            # Vérifier si on peut ajouter une nouvelle requête
            return len(self.requests) < self.max_rps
    
    def record_request(self):
        """Enregistre une requête"""
        with self.lock:
            self.requests.append(time.time())
    
    def get_wait_time(self) -> float:
        """Retourne le temps d'attente avant la prochaine requête"""
        with self.lock:
            if not self.requests:
                return 0.0
                
            oldest_request = self.requests[0]
            wait_time = 1.0 - (time.time() - oldest_request)
            return max(0.0, wait_time)
    
    def get_current_rps(self) -> float:
        """Retourne le RPS actuel"""
        with self.lock:
            now = time.time()
            
            # Compter les requêtes de la dernière seconde
            recent_requests = sum(1 for req_time in self.requests if now - req_time <= 1.0)
            return float(recent_requests)


# Factory functions et utilitaires globaux

def create_rpc_client(config=None) -> RPCClient:
    """
    Factory function pour créer un client RPC configuré
    
    Args:
        config: Configuration optionnelle (utilise get_config() par défaut)
    
    Returns:
        Instance RPCClient configurée
    """
    try:
        return RPCClient(config)
    except Exception as e:
        logger.error(f"❌ Erreur création client RPC: {e}")
        raise

def get_default_rpc_client() -> RPCClient:
    """
    Retourne l'instance par défaut du client RPC (singleton)
    
    Returns:
        Instance RPCClient globale
    """
    global _default_rpc_client
    
    if _default_rpc_client is None:
        _default_rpc_client = create_rpc_client()
        logger.info("🔌 Client RPC par défaut créé")
    
    return _default_rpc_client

def test_rpc_connectivity(endpoints: List[str] = None) -> Dict[str, Any]:
    """
    Teste la connectivité des endpoints RPC
    
    Args:
        endpoints: Liste d'endpoints à tester (utilise la config par défaut si None)
    
    Returns:
        Résultats des tests de connectivité
    """
    if endpoints is None:
        endpoints = DEFAULT_RPC_ENDPOINTS
    
    results = {}
    
    with requests.Session() as session:
        # Configuration de base pour les tests
        session.headers.update({'Content-Type': 'application/json'})
        
        for endpoint in endpoints:
            start_time = time.time()
            
            try:
                response = session.post(
                    endpoint,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getHealth",
                        "params": []
                    },
                    timeout=5.0,
                    headers={'Content-Type': 'application/json'}
                )
                
                response_time = (time.time() - start_time) * 1000
                
                if response.status_code == 200:
                    results[endpoint] = {
                        'status': 'success',
                        'response_time_ms': round(response_time, 0),
                        'available': True
                    }
                else:
                    results[endpoint] = {
                        'status': 'http_error',
                        'status_code': response.status_code,
                        'available': False
                    }
                    
            except requests.exceptions.Timeout:
                results[endpoint] = {
                    'status': 'timeout',
                    'available': False
                }
            except requests.exceptions.ConnectionError:
                results[endpoint] = {
                    'status': 'connection_error',
                    'available': False
                }
            except Exception as e:
                results[endpoint] = {
                    'status': 'error',
                    'error': str(e),
                    'available': False
            }
    
    # Statistiques globales
    total_endpoints = len(results)
    available_endpoints = sum(1 for r in results.values() if r.get('available', False))
    
    return {
        'endpoints': results,
        'summary': {
            'total': total_endpoints,
            'available': available_endpoints,
            'availability_percentage': round((available_endpoints / total_endpoints) * 100, 1) if total_endpoints > 0 else 0
        }
    }

# Context manager pour l'utilisation temporaire d'un client
@contextmanager
def rpc_client_context(config=None):
    """
    Context manager pour utiliser un client RPC temporaire
    
    Args:
        config: Configuration optionnelle
        
    Usage:
        with rpc_client_context() as client:
            result = client.call('getBalance', [wallet_address])
    """
    client = None
    try:
        client = create_rpc_client(config)
        yield client
    finally:
        if client:
            client.close()


# Fonction utilitaire pour les appels RPC simples
def quick_rpc_call(method: str, params: List = None, config=None, timeout: float = 15.0) -> Optional[Dict]:
    """
    Effectue un appel RPC rapide sans créer de client persistant
    
    Args:
        method: Méthode RPC à appeler
        params: Paramètres de la méthode
        config: Configuration optionnelle
        timeout: Timeout en secondes
        
    Returns:
        Résultat de l'appel RPC ou None si échec
    """
    try:
        with rpc_client_context(config) as client:
            # Ajuster le timeout si nécessaire
            if hasattr(client.config, 'rpc'):
                original_timeout = getattr(client.config.rpc, 'timeout', None)
                if original_timeout != timeout:
                    setattr(client.config.rpc, 'timeout', timeout)
            
            return client.call(method, params or [])
            
    except Exception as e:
        logger.error(f"❌ Quick RPC call failed for {method}: {e}")
        return None


if __name__ == "__main__":
    # Script de test pour le module RPC client
    import json
    
    print("🧪 Test du client RPC Solana")
    print("=" * 50)
    
    # Test 1: Connectivité des endpoints
    print("\n📡 Test de connectivité des endpoints.")
    connectivity_results = test_rpc_connectivity()
    
    print(f"Endpoints disponibles: {connectivity_results['summary']['available']}/{connectivity_results['summary']['total']}")
    print(f"Taux de disponibilité: {connectivity_results['summary']['availability_percentage']}%")
    
    for endpoint, result in connectivity_results['endpoints'].items():
        status_icon = "✅" if result.get('available', False) else "❌"
        endpoint_short = endpoint[:50] + "." if len(endpoint) > 50 else endpoint
        print(f"  {status_icon} {endpoint_short}: {result['status']}")
    
    # Test 2: Création du client RPC
    print("\n🔌 Test création client RPC.")
    try:
        client = create_rpc_client()
        print(f"✅ Client créé avec {len(client.endpoints)} endpoints")
        
        # Test 3: Health check
        print("\n🏥 Test health check.")
        health_results = client.health_check()
        print(f"Statut global: {health_results['overall_status']}")
        print(f"Endpoints sains: {health_results['healthy_endpoints']}/{health_results['total_endpoints']}")
        
        # Test 4: Appel RPC simple
        print("\n📞 Test appel RPC simple.")
        
        # Test avec getHealth (méthode simple)
        result = client.call("getHealth", [])
        if result:
            print("✅ Appel getHealth réussi")
        else:
            print("❌ Appel getHealth échoué")
        
        # Test 5: Statistiques
        print("\n📊 Statistiques du client.")
        stats = client.get_stats()
        print(f"Requêtes totales: {stats['total_requests']}")
        print(f"Taux de succès: {stats['success_rate']}%")
        print(f"Endpoint actuel: {stats['current_endpoint']}")
        
        # Test 6: Meilleurs endpoints
        print("\n🏆 Meilleurs endpoints.")
        best_endpoints = client.get_best_endpoints(3)
        for i, endpoint in enumerate(best_endpoints, 1):
            print(f"  {i}. {endpoint['url'][:40]}. (Score: {endpoint['health_score']})")
        
        client.close()
        print("\n✅ Tests terminés avec succès!")
        
    except Exception as e:
        print(f"\n❌ Erreur lors des tests: {e}")
        import traceback
        traceback.print_exc()
