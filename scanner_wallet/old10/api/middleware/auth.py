
#!/usr/bin/env python3
"""
Middleware d'authentification pour l'API Flask du Solana Wallet Monitor
Système d'authentification multi-niveaux avec API keys, JWT et rate limiting
"""

from flask import Flask, request, jsonify, g, current_app
from functools import wraps
from typing import Dict, List, Optional, Union, Callable, Any
import jwt
import hashlib
import hmac
import time
import secrets
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import threading
from collections import defaultdict

# Configuration du logger
logger = logging.getLogger(__name__)


@dataclass
class ApiKeyInfo:
    """Informations sur une clé API"""
    key_id: str
    key_hash: str  # Hash de la clé pour stockage sécurisé
    name: str
    permissions: List[str] = field(default_factory=list)
    rate_limit_per_hour: int = 1000
    created_at: int = field(default_factory=lambda: int(time.time()))
    last_used: Optional[int] = None
    is_active: bool = True
    expires_at: Optional[int] = None
    usage_count: int = 0
    allowed_ips: Optional[List[str]] = None
    
    def is_expired(self) -> bool:
        """Vérifie si la clé a expiré"""
        return self.expires_at is not None and int(time.time()) > self.expires_at
    
    def can_access(self, permission: str) -> bool:
        """Vérifie si la clé a une permission spécifique"""
        if not self.is_active or self.is_expired():
            return False
        return '*' in self.permissions or permission in self.permissions
    
    def is_ip_allowed(self, ip: str) -> bool:
        """Vérifie si l'IP est autorisée"""
        if not self.allowed_ips:
            return True
        return ip in self.allowed_ips
    
    def update_usage(self):
        """Met à jour les statistiques d'usage"""
        self.last_used = int(time.time())
        self.usage_count += 1


@dataclass
class AuthConfig:
    """Configuration du système d'authentification"""
    
    def __init__(self, config=None):
        """Initialise la configuration d'auth depuis la config globale"""
        try:
            from core.config import get_config
            self.config = config or get_config()
            
            # Configuration depuis config.py
            self.jwt_secret = getattr(self.config, 'jwt_secret', self._generate_secret())
            self.jwt_expiry_hours = getattr(self.config, 'jwt_expiry_hours', 24)
            self.api_auth_enabled = getattr(self.config, 'api_auth_enabled', False)
            
        except ImportError:
            # Fallback si core.config n'est pas disponible
            logger.warning("⚠️ Core config non disponible, utilisation des valeurs par défaut auth")
            self.jwt_secret = self._generate_secret()
            self.jwt_expiry_hours = 24
            self.api_auth_enabled = False
        
        # Configuration par défaut
        self.admin_routes = [
            '/api/admin/*',
            '/api/batching/config*',
            '/api/priority-update*',
            '/api/maintenance/*'
        ]
        
        self.public_routes = [
            '/api/health',
            '/api/dashboard-data',
            '/api/recent-balance-changes',
            '/api/cors/stats'
        ]
        
        self.rate_limits = {
            'default': 1000,      # Requêtes/heure par défaut
            'admin': 5000,        # Requêtes/heure admin
            'public': 100,        # Requêtes/heure sans auth
            'premium': 10000      # Requêtes/heure premium
        }
        
        # Clés API par défaut (à changer en production)
        self.default_api_keys = self._init_default_keys()
    
    def _generate_secret(self) -> str:
        """Génère un secret JWT sécurisé"""
        return secrets.token_urlsafe(64)
    
    def _init_default_keys(self) -> Dict[str, ApiKeyInfo]:
        """Initialise les clés API par défaut"""
        keys = {}
        
        # Clé admin pour développement
        admin_key = "swm_admin_" + secrets.token_urlsafe(32)
        keys["admin"] = ApiKeyInfo(
            key_id="admin",
            key_hash=self._hash_key(admin_key),
            name="Admin Key (Development)",
            permissions=["*"],
            rate_limit_per_hour=5000,
            is_active=True
        )
        
        # Clé lecture seule
        readonly_key = "swm_readonly_" + secrets.token_urlsafe(32)
        keys["readonly"] = ApiKeyInfo(
            key_id="readonly",
            key_hash=self._hash_key(readonly_key),
            name="Read-Only Key",
            permissions=["read", "dashboard"],
            rate_limit_per_hour=1000,
            is_active=True
        )
        
        # Log des clés générées (uniquement en dev)
        logger.info("🔑 Clés API générées pour développement:")
        logger.info(f"   Admin: {admin_key}")
        logger.info(f"   ReadOnly: {readonly_key}")
        logger.warning("⚠️ CHANGEZ CES CLÉS EN PRODUCTION!")
        
        return keys
    
    def _hash_key(self, key: str) -> str:
        """Hash une clé API de manière sécurisée"""
        return hashlib.sha256(key.encode()).hexdigest()


class AuthMiddleware:
    """Middleware d'authentification principal"""
    
    def __init__(self, app: Optional[Flask] = None, config: Optional[AuthConfig] = None):
        self.auth_config = config or AuthConfig()
        self.app = app
        self.api_keys = self.auth_config.default_api_keys.copy()
        self.rate_limiter = RateLimiter()
        self.auth_stats = {
            'total_requests': 0,
            'authenticated_requests': 0,
            'failed_auths': 0,
            'api_key_auths': 0,
            'jwt_auths': 0,
            'blocked_requests': 0,
            'start_time': datetime.now()
        }
        self._lock = threading.Lock()
        
        if app:
            self.init_app(app)
    
    def init_app(self, app: Flask):
        """Initialise le middleware d'auth sur l'application Flask"""
        self.app = app
        
        if not self.auth_config.api_auth_enabled:
            logger.info("🔓 Authentification désactivée - mode développement")
            # En mode désactivé, on ajoute quand même les handlers pour les stats
            app.before_request(self._before_request_stats)
            return
        
        # Enregistrer les handlers d'auth
        app.before_request(self._before_request_handler)
        app.after_request(self._after_request_handler)
        
        logger.info("🔐 Middleware d'authentification initialisé")
        logger.info(f"   🔑 {len(self.api_keys)} clés API configurées")
        logger.info(f"   ⏰ JWT expiry: {self.auth_config.jwt_expiry_hours}h")
    
    def _before_request_stats(self):
        """Handler basique pour les stats même sans auth"""
        with self._lock:
            self.auth_stats['total_requests'] += 1
    
    def _before_request_handler(self):
        """Handler avant chaque requête pour l'authentification"""
        with self._lock:
            self.auth_stats['total_requests'] += 1
        
        # Vérifier si la route nécessite une authentification
        if self._is_public_route(request.path):
            g.auth_level = 'public'
            g.auth_method = 'none'
            return
        
        # Vérifier le rate limiting d'abord
        client_ip = self._get_client_ip()
        if not self.rate_limiter.can_proceed(client_ip, 'public'):
            with self._lock:
                self.auth_stats['blocked_requests'] += 1
            logger.warning(f"🚫 Rate limit dépassé pour {client_ip}")
            return jsonify({'error': 'Rate limit exceeded'}), 429
        
        # Tentative d'authentification
        auth_result = self._authenticate_request()
        
        if not auth_result['success']:
            with self._lock:
                self.auth_stats['failed_auths'] += 1
            logger.warning(f"🔐 Auth failed: {auth_result['error']} pour {client_ip}")
            return jsonify({'error': auth_result['error']}), 401
        
        # Authentification réussie
        with self._lock:
            self.auth_stats['authenticated_requests'] += 1
            if auth_result['method'] == 'api_key':
                self.auth_stats['api_key_auths'] += 1
            elif auth_result['method'] == 'jwt':
                self.auth_stats['jwt_auths'] += 1
        
        # Stocker les infos d'auth dans g
        g.auth_level = auth_result['level']
        g.auth_method = auth_result['method']
        g.auth_user = auth_result.get('user')
        g.api_key_info = auth_result.get('api_key')
        
        # Vérifier les permissions pour les routes admin
        if self._is_admin_route(request.path) and g.auth_level != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
    
    def _after_request_handler(self, response):
        """Handler après chaque requête"""
        # Ajouter des headers d'information
        if hasattr(g, 'auth_method'):
            response.headers['X-Auth-Method'] = g.auth_method
            response.headers['X-Auth-Level'] = g.auth_level
        
        # Mettre à jour l'usage des clés API
        if hasattr(g, 'api_key_info') and g.api_key_info:
            g.api_key_info.update_usage()
        
        return response
    
    def _authenticate_request(self) -> Dict[str, Any]:
        """Authentifie une requête avec différentes méthodes"""
        # 1. Essayer l'authentification par API Key
        api_key_result = self._authenticate_api_key()
        if api_key_result['success']:
            return api_key_result
        
        # 2. Essayer l'authentification JWT
        jwt_result = self._authenticate_jwt()
        if jwt_result['success']:
            return jwt_result
        
        # Aucune méthode n'a fonctionné
        return {
            'success': False,
            'error': 'Authentication required',
            'details': 'Provide valid API key or JWT token'
        }
    
    def _authenticate_api_key(self) -> Dict[str, Any]:
        """Authentification par clé API"""
        # Chercher la clé dans les headers
        api_key = None
        key_header = request.headers.get('X-API-Key')
        auth_header = request.headers.get('Authorization')
        
        if key_header:
            api_key = key_header
        elif auth_header and auth_header.startswith('Bearer '):
            potential_key = auth_header[7:]  # Enlever "Bearer "
            if potential_key.startswith('swm_'):
                api_key = potential_key
        
        if not api_key:
            return {'success': False, 'error': 'API key not provided'}
        
        # Vérifier la clé
        key_hash = self.auth_config._hash_key(api_key)
        api_key_info = None
        
        for key_info in self.api_keys.values():
            if key_info.key_hash == key_hash:
                api_key_info = key_info
                break
        
        if not api_key_info:
            return {'success': False, 'error': 'Invalid API key'}
        
        if not api_key_info.is_active:
            return {'success': False, 'error': 'API key disabled'}
        
        if api_key_info.is_expired():
            return {'success': False, 'error': 'API key expired'}
        
        # Vérifier l'IP si restriction
        client_ip = self._get_client_ip()
        if not api_key_info.is_ip_allowed(client_ip):
            return {'success': False, 'error': 'IP not allowed for this API key'}
        
        # Vérifier le rate limiting pour cette clé
        if not self.rate_limiter.can_proceed(api_key_info.key_id, api_key_info.rate_limit_per_hour):
            return {'success': False, 'error': 'API key rate limit exceeded'}
        
        # Déterminer le niveau d'accès
        auth_level = 'admin' if '*' in api_key_info.permissions else 'user'
        
        return {
            'success': True,
            'method': 'api_key',
            'level': auth_level,
            'user': api_key_info.name,
            'api_key': api_key_info
        }
    
    def _authenticate_jwt(self) -> Dict[str, Any]:
        """Authentification par JWT token"""
        auth_header = request.headers.get('Authorization')
        
        if not auth_header or not auth_header.startswith('Bearer '):
            return {'success': False, 'error': 'JWT token not provided'}
        
        token = auth_header[7:]  # Enlever "Bearer "
        
        # Si ça ressemble à une API key, ne pas traiter comme JWT
        if token.startswith('swm_'):
            return {'success': False, 'error': 'Invalid JWT format'}
        
        try:
            payload = jwt.decode(
                token,
                self.auth_config.jwt_secret,
                algorithms=['HS256']
            )
            
            # Vérifier l'expiration
            if payload.get('exp', 0) < int(time.time()):
                return {'success': False, 'error': 'JWT token expired'}
            
            # Vérifier les claims requis
            if not payload.get('sub'):
                return {'success': False, 'error': 'Invalid JWT claims'}
            
            auth_level = payload.get('level', 'user')
            
            return {
                'success': True,
                'method': 'jwt',
                'level': auth_level,
                'user': payload.get('sub'),
                'jwt_payload': payload
            }
            
        except jwt.InvalidTokenError as e:
            return {'success': False, 'error': f'Invalid JWT token: {str(e)}'}
    
    def _is_public_route(self, path: str) -> bool:
        """Vérifie si une route est publique"""
        for pattern in self.auth_config.public_routes:
            if self._match_route_pattern(path, pattern):
                return True
        return False
    
    def _is_admin_route(self, path: str) -> bool:
        """Vérifie si une route nécessite un accès admin"""
        for pattern in self.auth_config.admin_routes:
            if self._match_route_pattern(path, pattern):
                return True
        return False
    
    def _match_route_pattern(self, path: str, pattern: str) -> bool:
        """Vérifie si un chemin correspond à un pattern"""
        if pattern.endswith('*'):
            prefix = pattern[:-1]
            return path.startswith(prefix)
        else:
            return path == pattern
    
    def _get_client_ip(self) -> str:
        """Récupère l'IP du client en tenant compte des proxies"""
        # Headers possibles pour l'IP réelle
        ip_headers = [
            'X-Forwarded-For',
            'X-Real-IP',
            'X-Client-IP',
            'CF-Connecting-IP'
        ]
        
        for header in ip_headers:
            ip = request.headers.get(header)
            if ip:
                # Prendre la première IP si liste séparée par virgules
                return ip.split(',')[0].strip()
        
        return request.remote_addr or '0.0.0.0'
    
    def create_jwt_token(self, user: str, level: str = 'user', 
                        expires_hours: Optional[int] = None) -> str:
        """Crée un token JWT"""
        expires_hours = expires_hours or self.auth_config.jwt_expiry_hours
        
        payload = {
            'sub': user,
            'level': level,
            'iat': int(time.time()),
            'exp': int(time.time()) + (expires_hours * 3600),
            'iss': 'solana-wallet-monitor'
        }
        
        return jwt.encode(payload, self.auth_config.jwt_secret, algorithm='HS256')
    
    def create_api_key(self, name: str, permissions: List[str], 
                      expires_hours: Optional[int] = None,
                      rate_limit: int = 1000,
                      allowed_ips: Optional[List[str]] = None) -> str:
        """Crée une nouvelle clé API"""
        key_id = f"key_{int(time.time())}_{secrets.token_hex(4)}"
        api_key = f"swm_{key_id}_{secrets.token_urlsafe(32)}"
        
        expires_at = None
        if expires_hours:
            expires_at = int(time.time()) + (expires_hours * 3600)
        
        key_info = ApiKeyInfo(
            key_id=key_id,
            key_hash=self.auth_config._hash_key(api_key),
            name=name,
            permissions=permissions,
            rate_limit_per_hour=rate_limit,
            expires_at=expires_at,
            allowed_ips=allowed_ips
        )
        
        self.api_keys[key_id] = key_info
        
        logger.info(f"🔑 Nouvelle clé API créée: {name} ({key_id})")
        
        return api_key
    
    def revoke_api_key(self, key_id: str) -> bool:
        """Révoque une clé API"""
        if key_id in self.api_keys:
            self.api_keys[key_id].is_active = False
            logger.info(f"🔑 Clé API révoquée: {key_id}")
            return True
        return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques d'authentification"""
        uptime = (datetime.now() - self.auth_stats['start_time']).total_seconds()
        
        stats = self.auth_stats.copy()
        stats.update({
            'uptime_seconds': int(uptime),
            'auth_enabled': self.auth_config.api_auth_enabled,
            'auth_rate': round(stats['authenticated_requests'] / max(uptime / 3600, 0.1), 2),
            'success_rate': round(
                (stats['authenticated_requests'] / max(stats['total_requests'], 1)) * 100, 1
            ) if self.auth_config.api_auth_enabled else 100,
            'active_api_keys': len([k for k in self.api_keys.values() if k.is_active]),
            'total_api_keys': len(self.api_keys),
            'rate_limiter_stats': self.rate_limiter.get_stats()
        })
        
        return stats


class RateLimiter:
    """Rate limiter par client/clé API"""
    
    def __init__(self):
        self.requests = defaultdict(list)  # {client_id: [timestamps]}
        self._lock = threading.Lock()
        self.stats = {
            'total_checks': 0,
            'blocked_requests': 0,
            'cleanup_runs': 0
        }
    
    def can_proceed(self, client_id: str, limit_per_hour: int = 1000) -> bool:
        """Vérifie si le client peut faire une requête"""
        with self._lock:
            self.stats['total_checks'] += 1
            
            current_time = int(time.time())
            hour_ago = current_time - 3600
            
            # Nettoyer les anciennes requêtes
            self.requests[client_id] = [
                ts for ts in self.requests[client_id] if ts > hour_ago
            ]
            
            # Vérifier la limite
            if len(self.requests[client_id]) >= limit_per_hour:
                self.stats['blocked_requests'] += 1
                return False
            
            # Ajouter la requête actuelle
            self.requests[client_id].append(current_time)
            return True
    
    def cleanup_old_entries(self):
        """Nettoie les anciennes entrées (appelé périodiquement)"""
        with self._lock:
            current_time = int(time.time())
            hour_ago = current_time - 3600
            
            for client_id in list(self.requests.keys()):
                self.requests[client_id] = [
                    ts for ts in self.requests[client_id] if ts > hour_ago
                ]
                
                # Supprimer les clients sans requêtes récentes
                if not self.requests[client_id]:
                    del self.requests[client_id]
            
            self.stats['cleanup_runs'] += 1
    
    def get_stats(self) -> Dict[str, int]:
        """Retourne les statistiques du rate limiter"""
        with self._lock:
            return {
                'active_clients': len(self.requests),
                'total_checks': self.stats['total_checks'],
                'blocked_requests': self.stats['blocked_requests'],
                'cleanup_runs': self.stats['cleanup_runs']
            }


# Décorateurs d'authentification

def auth_required(level: str = 'user'):
    """Décorateur pour exiger une authentification"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not hasattr(g, 'auth_level'):
                return jsonify({'error': 'Authentication required'}), 401
            
            if level == 'admin' and g.auth_level != 'admin':
                return jsonify({'error': 'Admin access required'}), 403
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator


def permission_required(permission: str):
    """Décorateur pour exiger une permission spécifique"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not hasattr(g, 'api_key_info') or not g.api_key_info:
                return jsonify({'error': 'API key required for this operation'}), 401
            
            if not g.api_key_info.can_access(permission):
                return jsonify({'error': f'Permission {permission} required'}), 403
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator


def rate_limited(requests_per_hour: int = 100):
    """Décorateur pour rate limiting spécifique"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Utiliser l'IP client comme identifiant
            client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
            rate_limiter = RateLimiter()
            
            if not rate_limiter.can_proceed(f"route_{client_ip}", requests_per_hour):
                return jsonify({'error': 'Rate limit exceeded for this endpoint'}), 429
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator


# Fonctions d'initialisation

def init_auth(app: Flask, config: Optional[AuthConfig] = None) -> AuthMiddleware:
    """Initialise l'authentification sur une application Flask"""
    auth_middleware = AuthMiddleware(app, config)
    
    # Routes d'authentification
    @app.route('/api/auth/stats')
    @auth_required('admin')
    def auth_stats():
        return jsonify(auth_middleware.get_stats())
    
    @app.route('/api/auth/login', methods=['POST'])
    def login():
        # Placeholder pour future implémentation login
        data = request.get_json() or {}
        username = data.get('username')
        password = data.get('password')
        
        # Authentification basique (à améliorer)
        if username == 'admin' and password == 'admin123':
            token = auth_middleware.create_jwt_token(username, 'admin')
            return jsonify({
                'success': True,
                'token': token,
                'expires_in': auth_middleware.auth_config.jwt_expiry_hours * 3600
            })
        
        return jsonify({'error': 'Invalid credentials'}), 401
    
    @app.route('/api/auth/create-key', methods=['POST'])
    @auth_required('admin')
    def create_api_key():
        data = request.get_json() or {}
        name = data.get('name', 'Unnamed Key')
        permissions = data.get('permissions', ['read'])
        expires_hours = data.get('expires_hours')
        rate_limit = data.get('rate_limit', 1000)
        
        api_key = auth_middleware.create_api_key(
            name=name,
            permissions=permissions,
            expires_hours=expires_hours,
            rate_limit=rate_limit
        )
        
        return jsonify({
            'success': True,
            'api_key': api_key,
            'message': 'Store this key securely - it will not be shown again'
        })
    
    return auth_middleware


# Exemple d'usage
if __name__ == "__main__":
    from flask import Flask
    
    app = Flask(__name__)
    
    # Configuration auth
    auth_config = AuthConfig()
    auth_config.api_auth_enabled = True
    
    # Initialisation
    auth_middleware = init_auth(app, auth_config)
    
    @app.route('/api/test')
    @auth_required('user')
    def test_endpoint():
        return jsonify({
            'message': 'Authenticated access OK',
            'user': g.auth_user,
            'level': g.auth_level
        })
    
    @app.route('/api/admin/test')
    @auth_required('admin')
    def admin_endpoint():
        return jsonify({'message': 'Admin access OK'})
    
    @app.route('/api/public')
    def public_endpoint():
        return jsonify({'message': 'Public endpoint'})
    
    if __name__ == '__main__':
        app.run(debug=True, host='0.0.0.0', port=5000)