
#!/usr/bin/env python3
"""
Gestionnaire d'Endpoints RPC Solana
Gestion intelligente des endpoints avec fallbacks, validation et optimisation
"""

import re
import time
import logging
import threading
from typing import Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse
from dataclasses import dataclass, field
from enum import Enum

# Imports internes avec fallback gracieux
try:
    from core.config import get_config
except ImportError:
    get_config = None

try:
    from utils.helpers import validate_url, test_connectivity
    from utils.constants import DEFAULT_RPC_ENDPOINTS, RPC_TIMEOUT_DEFAULT
except ImportError:
    # Fallbacks si modules utils non disponibles
    def validate_url(url): return url.startswith(('http://', 'https://'))
    def test_connectivity(url): return True
    DEFAULT_RPC_ENDPOINTS = [
        "https://api.mainnet-beta.solana.com",
        "https://rpc.ankr.com/solana", 
        "https://solana.public-rpc.com"
    ]
    RPC_TIMEOUT_DEFAULT = 15

logger = logging.getLogger(__name__)

class EndpointTier(Enum):
    """Tiers de qualité des endpoints RPC"""
    PREMIUM = "premium"      # Endpoints payants haute performance
    PUBLIC = "public"        # Endpoints publics gratuits
    FALLBACK = "fallback"    # Endpoints de secours
    CUSTOM = "custom"        # Endpoints personnalisés

class EndpointStatus(Enum):
    """Statuts des endpoints"""
    ACTIVE = "active"        # Endpoint fonctionnel
    DEGRADED = "degraded"    # Performance dégradée
    OFFLINE = "offline"      # Endpoint indisponible
    TESTING = "testing"      # En cours de test

@dataclass
class EndpointConfig:
    """Configuration d'un endpoint RPC"""
    url: str
    tier: EndpointTier = EndpointTier.PUBLIC
    api_key: Optional[str] = None
    rate_limit_rps: float = 5.0
    timeout: float = RPC_TIMEOUT_DEFAULT
    priority: int = 1  # Plus bas = plus prioritaire
    description: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    
    # Métadonnées de santé
    status: EndpointStatus = EndpointStatus.TESTING
    last_test: Optional[float] = None
    consecutive_errors: int = 0
    average_response_time: float = 0.0
    success_rate: float = 0.0
    
    def __post_init__(self):
        """Validation post-initialisation"""
        if not validate_url(self.url):
            raise ValueError(f"URL invalide: {self.url}")
        
        # Nettoyer l'URL (supprimer trailing slash)
        self.url = self.url.rstrip('/')
        
        # Headers par défaut
        if not self.headers:
            self.headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'User-Agent': 'SolanaWalletMonitor/2.0'
            }
        
        # Ajouter l'authentification si API key fournie
        if self.api_key:
            if 'quicknode' in self.url.lower():
                # QuickNode utilise un header Authorization Bearer
                pass  # L'auth QuickNode se fait via l'URL
            else:
                # Autres providers - header Authorization standard
                self.headers['Authorization'] = f'Bearer {self.api_key}'
    
    @property
    def is_healthy(self) -> bool:
        """Vérifie si l'endpoint est en bonne santé"""
        return (
            self.status == EndpointStatus.ACTIVE and
            self.consecutive_errors < 3 and
            self.success_rate >= 70.0 and
            self.average_response_time < 10.0
        )
    
    @property
    def display_name(self) -> str:
        """Nom d'affichage de l'endpoint"""
        parsed = urlparse(self.url)
        domain = parsed.netloc
        
        # Noms connus
        if 'quicknode' in domain:
            return "QuickNode"
        elif 'ankr.com' in domain:
            return "Ankr"
        elif 'api.mainnet-beta.solana.com' in domain:
            return "Solana Labs"
        elif 'rpcpool.com' in domain:
            return "RPCPool"
        elif 'helius-rpc.com' in domain:
            return "Helius"
        elif 'public-rpc.com' in domain:
            return "Public RPC"
        else:
            return domain
    
    def get_auth_headers(self) -> Dict[str, str]:
        """Retourne les headers avec authentification"""
        headers = self.headers.copy()
        return headers
    
    def update_metrics(self, response_time: float, success: bool):
        """Met à jour les métriques de performance"""
        # Moyenne mobile pour le temps de réponse
        if self.average_response_time == 0:
            self.average_response_time = response_time
        else:
            # Facteur de lissage alpha = 0.1
            self.average_response_time = (0.9 * self.average_response_time + 
                                        0.1 * response_time)
        
        # Mise à jour du taux de succès
        if success:
            self.consecutive_errors = 0
            # Améliorer progressivement le success rate
            if self.success_rate < 100:
                self.success_rate = min(100, self.success_rate + 1)
        else:
            self.consecutive_errors += 1
            # Dégrader le success rate
            self.success_rate = max(0, self.success_rate - 5)
        
        self.last_test = time.time()
        
        # Mettre à jour le statut
        if self.consecutive_errors >= 5:
            self.status = EndpointStatus.OFFLINE
        elif self.consecutive_errors >= 3 or self.average_response_time > 15:
            self.status = EndpointStatus.DEGRADED
        else:
            self.status = EndpointStatus.ACTIVE

class RPCEndpointManager:
    """Gestionnaire intelligent des endpoints RPC Solana"""
    
    def __init__(self, config=None):
        self.config = config or (get_config() if get_config else None)
        self.endpoints: List[EndpointConfig] = []
        self.current_endpoint_index = 0
        self.lock = threading.RLock()
        self.last_rotation_time = 0
        
        # Statistiques globales
        self.stats = {
            'total_requests': 0,
            'total_failures': 0,
            'endpoint_rotations': 0,
            'start_time': time.time()
        }
        
        # Initialiser les endpoints
        self._initialize_endpoints()
        
        # Tester la connectivité initiale
        self._initial_health_check()
    
    def _initialize_endpoints(self):
        """Initialise la liste des endpoints"""
        logger.info("🔧 Initialisation des endpoints RPC...")
        
        # 1. Endpoint premium depuis la config
        if self.config and hasattr(self.config, 'rpc'):
            quicknode_endpoint = getattr(self.config.rpc, 'quicknode_endpoint', None)
            quicknode_api_key = getattr(self.config.rpc, 'quicknode_api_key', None)
            
            if quicknode_endpoint and quicknode_endpoint.strip():
                try:
                    premium_endpoint = EndpointConfig(
                        url=quicknode_endpoint,
                        tier=EndpointTier.PREMIUM,
                        api_key=quicknode_api_key,
                        rate_limit_rps=100.0,  # QuickNode free tier
                        timeout=25.0,
                        priority=1,
                        description="QuickNode Premium RPC"
                    )
                    self.endpoints.append(premium_endpoint)
                    logger.info(f"✅ Endpoint premium ajouté: {premium_endpoint.display_name}")
                except ValueError as e:
                    logger.warning(f"⚠️ Endpoint premium invalide: {e}")
            
            # Endpoints de fallback depuis la config
            fallback_endpoints = getattr(self.config.rpc, 'fallback_endpoints', [])
            for i, url in enumerate(fallback_endpoints):
                if url and url.strip():
                    try:
                        fallback_endpoint = EndpointConfig(
                            url=url,
                            tier=EndpointTier.PUBLIC,
                            rate_limit_rps=10.0,
                            priority=10 + i,
                            description=f"Fallback RPC #{i+1}"
                        )
                        self.endpoints.append(fallback_endpoint)
                        logger.debug(f"✅ Fallback ajouté: {fallback_endpoint.display_name}")
                    except ValueError as e:
                        logger.warning(f"⚠️ Endpoint fallback invalide {url}: {e}")
        
        # 2. Endpoints par défaut si aucun configuré
        if not self.endpoints:
            logger.info("📡 Utilisation des endpoints par défaut...")
            self._add_default_endpoints()
        
        # 3. Trier par priorité
        self.endpoints.sort(key=lambda x: (x.priority, x.tier.value))
        
        logger.info(f"🎯 {len(self.endpoints)} endpoints initialisés:")
        for i, endpoint in enumerate(self.endpoints):
            logger.info(f"   {i+1}. {endpoint.display_name} ({endpoint.tier.value}) - "
                       f"Priority: {endpoint.priority}")
    
    def _add_default_endpoints(self):
        """Ajoute les endpoints par défaut"""
        default_configs = [
            # Endpoint officiel Solana
            {
                'url': 'https://api.mainnet-beta.solana.com',
                'tier': EndpointTier.PUBLIC,
                'rate_limit_rps': 5.0,
                'priority': 10,
                'description': 'Solana Labs Official RPC'
            },
            # Ankr
            {
                'url': 'https://rpc.ankr.com/solana',
                'tier': EndpointTier.PUBLIC,
                'rate_limit_rps': 10.0,
                'priority': 20,
                'description': 'Ankr Public RPC'
            },
            # Public RPC
            {
                'url': 'https://solana.public-rpc.com',
                'tier': EndpointTier.FALLBACK,
                'rate_limit_rps': 5.0,
                'priority': 30,
                'description': 'Public RPC Fallback'
            }
        ]
        
        for config_dict in default_configs:
            try:
                endpoint = EndpointConfig(**config_dict)
                self.endpoints.append(endpoint)
                logger.debug(f"✅ Endpoint par défaut ajouté: {endpoint.display_name}")
            except Exception as e:
                logger.warning(f"⚠️ Erreur ajout endpoint par défaut: {e}")
    
    def _initial_health_check(self):
        """Test de santé initial de tous les endpoints"""
        logger.info("🔍 Test de santé initial des endpoints...")
        
        healthy_count = 0
        for endpoint in self.endpoints:
            is_healthy = self._test_endpoint_health(endpoint)
            if is_healthy:
                healthy_count += 1
                endpoint.status = EndpointStatus.ACTIVE
                logger.info(f"✅ {endpoint.display_name}: OK "
                           f"({endpoint.average_response_time:.0f}ms)")
            else:
                endpoint.status = EndpointStatus.DEGRADED
                logger.warning(f"⚠️ {endpoint.display_name}: DÉGRADÉ")
        
        logger.info(f"📊 Santé initiale: {healthy_count}/{len(self.endpoints)} "
                   f"endpoints fonctionnels")
        
        if healthy_count == 0:
            logger.error("❌ Aucun endpoint fonctionnel détecté!")
        elif healthy_count < len(self.endpoints):
            logger.warning(f"⚠️ {len(self.endpoints) - healthy_count} endpoints "
                          "en état dégradé")
    
    def _test_endpoint_health(self, endpoint: EndpointConfig) -> bool:
        """Test la santé d'un endpoint"""
        try:
            import requests
            
            # Payload de test simple
            test_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getHealth"
            }
            
            start_time = time.time()
            response = requests.post(
                endpoint.url,
                json=test_payload,
                headers=endpoint.get_auth_headers(),
                timeout=endpoint.timeout
            )
            response_time = (time.time() - start_time) * 1000  # en ms
            
            # Considérer comme sain si statut 200 et temps < 15s
            success = (response.status_code == 200 and response_time < 15000)
            
            endpoint.update_metrics(response_time, success)
            return success
            
        except Exception as e:
            logger.debug(f"Test endpoint {endpoint.display_name} échoué: {e}")
            endpoint.update_metrics(30000, False)  # 30s timeout fictif
            return False
    
    def get_current_endpoint(self) -> EndpointConfig:
        """Retourne l'endpoint actuellement sélectionné"""
        with self.lock:
            if not self.endpoints:
                raise RuntimeError("Aucun endpoint disponible")
            
            # Assurer que l'index est valide
            if self.current_endpoint_index >= len(self.endpoints):
                self.current_endpoint_index = 0
            
            return self.endpoints[self.current_endpoint_index]
    
    def get_next_healthy_endpoint(self) -> Optional[EndpointConfig]:
        """Trouve le prochain endpoint en bonne santé"""
        with self.lock:
            if not self.endpoints:
                return None
            
            # Chercher un endpoint sain en partant du suivant
            start_index = self.current_endpoint_index
            
            for i in range(len(self.endpoints)):
                index = (start_index + i + 1) % len(self.endpoints)
                endpoint = self.endpoints[index]
                
                if endpoint.is_healthy:
                    logger.info(f"🔄 Basculement vers: {endpoint.display_name}")
                    self.current_endpoint_index = index
                    self.stats['endpoint_rotations'] += 1
                    self.last_rotation_time = time.time()
                    return endpoint
            
            # Si aucun endpoint sain, prendre le moins mauvais
            logger.warning("⚠️ Aucun endpoint sain, sélection du moins mauvais...")
            best_endpoint = min(self.endpoints, 
                              key=lambda x: (x.consecutive_errors, -x.success_rate))
            
            self.current_endpoint_index = self.endpoints.index(best_endpoint)
            return best_endpoint
    
    def report_endpoint_result(self, success: bool, response_time: float, 
                              error_type: Optional[str] = None):
        """Signale le résultat d'une requête sur l'endpoint actuel"""
        with self.lock:
            current = self.get_current_endpoint()
            current.update_metrics(response_time, success)
            
            self.stats['total_requests'] += 1
            if not success:
                self.stats['total_failures'] += 1
            
            # Log des performances
            if success:
                logger.debug(f"✅ {current.display_name}: {response_time:.0f}ms")
            else:
                logger.warning(f"❌ {current.display_name}: {error_type or 'Erreur'} "
                              f"({response_time:.0f}ms)")
            
            # Rotation automatique si trop d'erreurs consécutives
            if current.consecutive_errors >= 3:
                logger.warning(f"🔄 Rotation automatique depuis {current.display_name} "
                              f"({current.consecutive_errors} erreurs consécutives)")
                self.get_next_healthy_endpoint()
    
    def force_rotate_endpoint(self, reason: str = "Manual rotation"):
        """Force la rotation vers le prochain endpoint"""
        with self.lock:
            old_endpoint = self.get_current_endpoint()
            new_endpoint = self.get_next_healthy_endpoint()
            
            if new_endpoint and new_endpoint != old_endpoint:
                logger.info(f"🔄 Rotation forcée: {old_endpoint.display_name} → "
                           f"{new_endpoint.display_name} (Raison: {reason})")
                return True
            else:
                logger.warning("⚠️ Rotation impossible: aucun autre endpoint disponible")
                return False
    
    def add_custom_endpoint(self, url: str, tier: EndpointTier = EndpointTier.CUSTOM,
                           api_key: Optional[str] = None, **kwargs) -> bool:
        """Ajoute un endpoint personnalisé"""
        try:
            endpoint = EndpointConfig(
                url=url,
                tier=tier,
                api_key=api_key,
                priority=kwargs.get('priority', 50),
                rate_limit_rps=kwargs.get('rate_limit_rps', 10.0),
                description=kwargs.get('description', f'Custom endpoint {url}')
            )
            
            # Tester la santé avant d'ajouter
            if self._test_endpoint_health(endpoint):
                with self.lock:
                    self.endpoints.append(endpoint)
                    self.endpoints.sort(key=lambda x: (x.priority, x.tier.value))
                
                logger.info(f"✅ Endpoint personnalisé ajouté: {endpoint.display_name}")
                return True
            else:
                logger.warning(f"⚠️ Endpoint personnalisé non ajouté (échec test): {url}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Erreur ajout endpoint personnalisé {url}: {e}")
            return False
    
    def remove_endpoint(self, url: str) -> bool:
        """Supprime un endpoint de la liste"""
        with self.lock:
            for i, endpoint in enumerate(self.endpoints):
                if endpoint.url == url:
                    # Ne pas supprimer le dernier endpoint
                    if len(self.endpoints) <= 1:
                        logger.warning("⚠️ Impossible de supprimer le dernier endpoint")
                        return False
                    
                    # Ajuster l'index actuel si nécessaire
                    if i == self.current_endpoint_index:
                        self.get_next_healthy_endpoint()
                    elif i < self.current_endpoint_index:
                        self.current_endpoint_index -= 1
                    
                    self.endpoints.pop(i)
                    logger.info(f"🗑️ Endpoint supprimé: {endpoint.display_name}")
                    return True
            
            logger.warning(f"⚠️ Endpoint non trouvé pour suppression: {url}")
            return False
    
    def get_all_endpoints(self) -> List[Dict]:
        """Retourne tous les endpoints avec leurs métriques"""
        with self.lock:
            endpoints_data = []
            
            for i, endpoint in enumerate(self.endpoints):
                endpoints_data.append({
                    'url': endpoint.url,
                    'display_name': endpoint.display_name,
                    'tier': endpoint.tier.value,
                    'status': endpoint.status.value,
                    'is_current': i == self.current_endpoint_index,
                    'priority': endpoint.priority,
                    'rate_limit_rps': endpoint.rate_limit_rps,
                    'average_response_time': round(endpoint.average_response_time, 1),
                    'success_rate': round(endpoint.success_rate, 1),
                    'consecutive_errors': endpoint.consecutive_errors,
                    'is_healthy': endpoint.is_healthy,
                    'last_test': endpoint.last_test,
                    'description': endpoint.description
                })
            
            return endpoints_data
    
    def get_stats(self) -> Dict:
        """Retourne les statistiques globales"""
        with self.lock:
            uptime = time.time() - self.stats['start_time']
            
            return {
                'total_endpoints': len(self.endpoints),
                'current_endpoint': self.get_current_endpoint().display_name,
                'healthy_endpoints': sum(1 for ep in self.endpoints if ep.is_healthy),
                'total_requests': self.stats['total_requests'],
                'total_failures': self.stats['total_failures'],
                'success_rate': (
                    round((1 - self.stats['total_failures'] / max(self.stats['total_requests'], 1)) * 100, 1)
                ),
                'endpoint_rotations': self.stats['endpoint_rotations'],
                'uptime_seconds': round(uptime, 1),
                'uptime_hours': round(uptime / 3600, 2),
                'last_rotation_time': self.last_rotation_time
            }
    
    def health_check_all(self) -> Dict:
        """Effectue un test de santé complet de tous les endpoints"""
        logger.info("🔍 Test de santé complet de tous les endpoints...")
        
        results = []
        healthy_count = 0
        
        for endpoint in self.endpoints:
            start_time = time.time()
            is_healthy = self._test_endpoint_health(endpoint)
            test_duration = time.time() - start_time
            
            if is_healthy:
                healthy_count += 1
            
            results.append({
                'url': endpoint.url,
                'display_name': endpoint.display_name,
                'tier': endpoint.tier.value,
                'is_healthy': is_healthy,
                'status': endpoint.status.value,
                'response_time': round(endpoint.average_response_time, 1),
                'test_duration': round(test_duration * 1000, 1),
                'success_rate': round(endpoint.success_rate, 1),
                'consecutive_errors': endpoint.consecutive_errors
            })
        
        overall_status = (
            'healthy' if healthy_count == len(self.endpoints) else
            'degraded' if healthy_count >= len(self.endpoints) // 2 else
            'critical'
        )
        
        logger.info(f"📊 Résultat global: {overall_status} "
                   f"({healthy_count}/{len(self.endpoints)} sains)")
        
        return {
            'overall_status': overall_status,
            'healthy_count': healthy_count,
            'total_endpoints': len(self.endpoints),
            'endpoints': results,
            'timestamp': time.time()
        }
    
    def optimize_endpoint_order(self):
        """Optimise l'ordre des endpoints selon leurs performances"""
        with self.lock:
            # Calculer un score composite pour chaque endpoint
            def calculate_score(endpoint):
                # Score basé sur: santé + performance + fiabilité
                health_score = 100 if endpoint.is_healthy else 0
                performance_score = max(0, 100 - endpoint.average_response_time / 100)
                reliability_score = endpoint.success_rate
                
                # Bonus pour les tiers premium
                tier_bonus = {
                    EndpointTier.PREMIUM: 50,
                    EndpointTier.PUBLIC: 0,
                    EndpointTier.FALLBACK: -20,
                    EndpointTier.CUSTOM: 10
                }.get(endpoint.tier, 0)
                
                return (health_score + performance_score + reliability_score + tier_bonus)
            
            # Trier par score décroissant mais préserver les priorités manuelles
            old_order = [ep.display_name for ep in self.endpoints]
            
            self.endpoints.sort(key=lambda ep: (-calculate_score(ep), ep.priority))
            
            new_order = [ep.display_name for ep in self.endpoints]
            
            if old_order != new_order:
                logger.info("🔧 Ordre des endpoints optimisé:")
                for i, endpoint in enumerate(self.endpoints[:3]):  # Top 3
                    score = calculate_score(endpoint)
                    logger.info(f"   {i+1}. {endpoint.display_name} (score: {score:.1f})")
                
                # Réajuster l'index actuel
                current_url = self.get_current_endpoint().url
                for i, endpoint in enumerate(self.endpoints):
                    if endpoint.url == current_url:
                        self.current_endpoint_index = i
                        break
    
    def reset_statistics(self):
        """Remet à zéro toutes les statistiques"""
        with self.lock:
            self.stats = {
                'total_requests': 0,
                'total_failures': 0,
                'endpoint_rotations': 0,
                'start_time': time.time()
            }
            
            for endpoint in self.endpoints:
                endpoint.consecutive_errors = 0
                endpoint.success_rate = 50.0  # Valeur neutre
                endpoint.average_response_time = 0.0
                endpoint.status = EndpointStatus.TESTING
            
            logger.info("🔄 Statistiques des endpoints remises à zéro")


# Instance globale singleton
_endpoint_manager: Optional[RPCEndpointManager] = None
_manager_lock = threading.Lock()

def get_endpoint_manager(config=None) -> RPCEndpointManager:
    """Retourne l'instance singleton du gestionnaire d'endpoints"""
    global _endpoint_manager
    
    with _manager_lock:
        if _endpoint_manager is None:
            _endpoint_manager = RPCEndpointManager(config)
        
        return _endpoint_manager

def reset_endpoint_manager():
    """Remet à zéro l'instance singleton (pour les tests)"""
    global _endpoint_manager
    
    with _manager_lock:
        _endpoint_manager = None

# Fonctions utilitaires pour l'API
def get_current_endpoint_url() -> str:
    """Retourne l'URL de l'endpoint actuel"""
    manager = get_endpoint_manager()
    return manager.get_current_endpoint().url

def get_current_endpoint_headers() -> Dict[str, str]:
    """Retourne les headers de l'endpoint actuel"""
    manager = get_endpoint_manager()
    return manager.get_current_endpoint().get_auth_headers()

def report_rpc_result(success: bool, response_time: float, error_type: str = None):
    """Signale le résultat d'un appel RPC"""
    manager = get_endpoint_manager()
    manager.report_endpoint_result(success, response_time, error_type)

def force_endpoint_rotation(reason: str = "Manual rotation") -> bool:
    """Force la rotation d'endpoint"""
    manager = get_endpoint_manager()
    return manager.force_rotate_endpoint(reason)


# Point d'entrée pour tests
if __name__ == "__main__":
    # Tests basiques
    print("🧪 Test du gestionnaire d'endpoints RPC...")
    
    # Créer un gestionnaire de test
    manager = RPCEndpointManager()
    
    print(f"📊 Endpoints initialisés: {len(manager.endpoints)}")
    
    # Afficher tous les endpoints
    for endpoint in manager.get_all_endpoints():
        print(f"   • {endpoint['display_name']} ({endpoint['tier']}) - "
              f"Status: {endpoint['status']}")
    
    # Test de santé
    health_results = manager.health_check_all()
    print(f"🏥 Santé globale: {health_results['overall_status']}")
    
    # Statistiques
    stats = manager.get_stats()
    print(f"📈 Statistiques: {stats['healthy_endpoints']}/{stats['total_endpoints']} sains")
    
    print("✅ Tests terminés")