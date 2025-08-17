
#!/usr/bin/env python3
"""
Middleware CORS pour l'API Flask du Solana Wallet Monitor
Gestion avancée des Cross-Origin Resource Sharing avec configuration flexible
"""

from flask import Flask, request, jsonify, g
from functools import wraps
from typing import List, Dict, Optional, Union, Callable
import re
import logging
from datetime import datetime

# Configuration du logger
logger = logging.getLogger(__name__)


class CORSConfig:
    """Configuration CORS centralisée"""
    
    def __init__(self, config=None):
        """Initialise la configuration CORS depuis la config globale"""
        try:
            from core.config import get_config
            self.config = config or get_config()
            
            # Configuration CORS depuis config.py
            self.enabled = getattr(self.config.flask, 'cors_enabled', True)
            self.origins = getattr(self.config.flask, 'cors_origins', ['*'])
            
        except ImportError:
            # Fallback si core.config n'est pas disponible
            logger.warning("⚠️ Core config non disponible, utilisation des valeurs par défaut CORS")
            self.enabled = True
            self.origins = ['*']
        
        # Configuration par défaut et sécurisée
        self.default_config = {
            'origins': self._process_origins(self.origins),
            'methods': ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
            'headers': [
                'Content-Type',
                'Authorization', 
                'X-Requested-With',
                'Accept',
                'Origin',
                'X-API-Key',
                'X-Client-Version',
                'X-Request-ID'
            ],
            'credentials': True,
            'max_age': 86400,  # 24 heures
            'expose_headers': [
                'X-Total-Count',
                'X-Page-Count', 
                'X-Rate-Limit-Remaining',
                'X-Response-Time',
                'X-Request-ID'
            ]
        }
        
        # Configuration spécifique par route
        self.route_configs = {
            '/api/admin/*': {
                'origins': self._get_admin_origins(),
                'methods': ['GET', 'POST', 'PUT', 'DELETE'],
                'credentials': True
            },
            '/api/dashboard/*': {
                'origins': ['*'],  # Plus permissif pour le dashboard public
                'methods': ['GET'],
                'credentials': False
            },
            '/api/batching/*': {
                'origins': self._get_admin_origins(),
                'methods': ['GET', 'POST'],
                'credentials': True
            }
        }

    def _process_origins(self, origins: List[str]) -> List[str]:
        """Traite et valide la liste des origins"""
        if not origins:
            return ['*']
        
        processed = []
        for origin in origins:
            if origin == '*':
                processed.append('*')
            elif self._validate_origin(origin):
                processed.append(origin.rstrip('/'))
            else:
                logger.warning(f"⚠️ Origin invalide ignoré: {origin}")
        
        return processed or ['*']

    def _validate_origin(self, origin: str) -> bool:
        """Valide un origin selon les standards"""
        if origin == '*':
            return True
        
        # Pattern pour valider les URLs
        url_pattern = re.compile(
            r'^https?://'                       # http:// ou https://
            r'(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)*'  # domaine
            r'[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?'         # TLD
            r'(?::[0-9]{1,5})?'                              # port optionnel
            r'$', re.IGNORECASE
        )
        
        return bool(url_pattern.match(origin))

    def _get_admin_origins(self) -> List[str]:
        """Retourne les origins autorisés pour les routes admin"""
        admin_origins = []
        
        for origin in self.default_config['origins']:
            if origin == '*':
                # En production, éviter * pour les routes admin
                if hasattr(self.config, 'environment') and self.config.environment.value == 'PRODUCTION':
                    logger.warning("⚠️ Origin '*' déconseillé pour admin en production")
                    admin_origins.append('https://localhost:3000')  # Frontend par défaut
                else:
                    admin_origins.append('*')
            else:
                admin_origins.append(origin)
        
        return admin_origins


class CORSMiddleware:
    """Middleware CORS avancé avec gestion intelligente des preflight et routing"""
    
    def __init__(self, app: Optional[Flask] = None, config: Optional[CORSConfig] = None):
        self.cors_config = config or CORSConfig()
        self.app = app
        self.stats = {
            'preflight_requests': 0,
            'cors_requests': 0,
            'blocked_origins': 0,
            'start_time': datetime.now()
        }
        
        if app:
            self.init_app(app)

    def init_app(self, app: Flask):
        """Initialise le middleware CORS sur l'application Flask"""
        self.app = app
        
        if not self.cors_config.enabled:
            logger.info("🔒 CORS désactivé")
            return
        
        # Enregistrer les handlers CORS
        app.before_request(self._before_request_handler)
        app.after_request(self._after_request_handler)
        
        # Handler spécial pour OPTIONS (preflight)
        app.route('/<path:path>', methods=['OPTIONS'])(self._handle_preflight)
        
        logger.info("✅ Middleware CORS initialisé")
        logger.info(f"   📍 Origins autorisés: {self.cors_config.default_config['origins']}")
        logger.info(f"   🔧 Credentials: {self.cors_config.default_config['credentials']}")

    def _before_request_handler(self):
        """Handler avant chaque requête"""
        if not self.cors_config.enabled:
            return
        
        origin = request.headers.get('Origin')
        method = request.method
        
        # Statistiques
        if method == 'OPTIONS':
            self.stats['preflight_requests'] += 1
        if origin:
            self.stats['cors_requests'] += 1
        
        # Log détaillé pour debugging
        if origin:
            logger.debug(f"🌐 Requête CORS: {method} {request.path} depuis {origin}")
        
        # Stocker les infos CORS pour after_request
        g.cors_origin = origin
        g.cors_method = method
        g.cors_route_config = self._get_route_config(request.path)

    def _after_request_handler(self, response):
        """Handler après chaque requête pour ajouter les headers CORS"""
        if not self.cors_config.enabled:
            return response
        
        origin = getattr(g, 'cors_origin', None)
        route_config = getattr(g, 'cors_route_config', self.cors_config.default_config)
        
        # Ajouter les headers CORS
        if origin and self._is_origin_allowed(origin, route_config['origins']):
            self._add_cors_headers(response, origin, route_config)
        elif not origin:
            # Requête non-CORS, ajouter headers basiques
            self._add_basic_cors_headers(response, route_config)
        else:
            # Origin bloqué
            self.stats['blocked_origins'] += 1
            logger.warning(f"🚫 Origin bloqué: {origin} pour {request.path}")
        
        return response

    def _handle_preflight(self, path):
        """Gère les requêtes OPTIONS (preflight)"""
        origin = request.headers.get('Origin')
        method = request.headers.get('Access-Control-Request-Method')
        headers = request.headers.get('Access-Control-Request-Headers', '')
        
        logger.debug(f"✈️ Preflight: {method} {path} depuis {origin}")
        
        # Récupérer la config pour cette route
        route_config = self._get_route_config(f"/{path}")
        
        # Vérifier si l'origin et la méthode sont autorisés
        if not origin or not self._is_origin_allowed(origin, route_config['origins']):
            logger.warning(f"🚫 Preflight refusé - Origin: {origin}")
            return '', 403
        
        if method and method not in route_config['methods']:
            logger.warning(f"🚫 Preflight refusé - Méthode: {method}")
            return '', 405
        
        # Créer la réponse preflight
        response = jsonify({'preflight': 'ok'})
        self._add_preflight_headers(response, origin, route_config, method, headers)
        
        return response

    def _get_route_config(self, path: str) -> Dict:
        """Récupère la configuration CORS pour une route spécifique"""
        for pattern, config in self.cors_config.route_configs.items():
            if self._match_route_pattern(path, pattern):
                # Merger avec la config par défaut
                merged_config = self.cors_config.default_config.copy()
                merged_config.update(config)
                return merged_config
        
        return self.cors_config.default_config

    def _match_route_pattern(self, path: str, pattern: str) -> bool:
        """Vérifie si un chemin correspond à un pattern de route"""
        if pattern.endswith('/*'):
            prefix = pattern[:-2]
            return path.startswith(prefix)
        else:
            return path == pattern

    def _is_origin_allowed(self, origin: str, allowed_origins: List[str]) -> bool:
        """Vérifie si un origin est autorisé"""
        if not origin:
            return False
        
        if '*' in allowed_origins:
            return True
        
        # Vérification exacte
        if origin in allowed_origins:
            return True
        
        # Vérification avec sous-domaines
        for allowed in allowed_origins:
            if allowed.startswith('.'):  # Pattern .example.com
                if origin.endswith(allowed) or origin == allowed[1:]:
                    return True
        
        return False

    def _add_cors_headers(self, response, origin: str, config: Dict):
        """Ajoute les headers CORS complets"""
        response.headers['Access-Control-Allow-Origin'] = origin
        
        if config.get('credentials'):
            response.headers['Access-Control-Allow-Credentials'] = 'true'
        
        if config.get('expose_headers'):
            response.headers['Access-Control-Expose-Headers'] = ', '.join(config['expose_headers'])
        
        # Header personnalisé pour identifier les réponses CORS
        response.headers['X-CORS-Enabled'] = 'true'

    def _add_basic_cors_headers(self, response, config: Dict):
        """Ajoute les headers CORS basiques pour les requêtes non-CORS"""
        if config.get('expose_headers'):
            response.headers['Access-Control-Expose-Headers'] = ', '.join(config['expose_headers'])

    def _add_preflight_headers(self, response, origin: str, config: Dict, method: str, headers: str):
        """Ajoute les headers pour les requêtes preflight"""
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = ', '.join(config['methods'])
        response.headers['Access-Control-Allow-Headers'] = ', '.join(config['headers'])
        response.headers['Access-Control-Max-Age'] = str(config['max_age'])
        
        if config.get('credentials'):
            response.headers['Access-Control-Allow-Credentials'] = 'true'

    def get_stats(self) -> Dict:
        """Retourne les statistiques CORS"""
        uptime = (datetime.now() - self.stats['start_time']).total_seconds()
        
        return {
            'enabled': self.cors_config.enabled,
            'uptime_seconds': int(uptime),
            'preflight_requests': self.stats['preflight_requests'],
            'cors_requests': self.stats['cors_requests'],
            'blocked_origins': self.stats['blocked_origins'],
            'preflight_rate': round(self.stats['preflight_requests'] / max(uptime / 3600, 0.1), 2),
            'configured_origins': self.cors_config.default_config['origins'],
            'route_configs': len(self.cors_config.route_configs)
        }


# Décorateurs utilitaires

def cors_required(origins: Optional[List[str]] = None, 
                 methods: Optional[List[str]] = None,
                 credentials: bool = True):
    """Décorateur pour exiger CORS sur une route spécifique"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            origin = request.headers.get('Origin')
            
            # Vérifier l'origin si spécifié
            if origins and origin not in origins and '*' not in origins:
                logger.warning(f"🚫 CORS requis - Origin refusé: {origin}")
                return jsonify({'error': 'CORS origin not allowed'}), 403
            
            # Vérifier la méthode si spécifiée
            if methods and request.method not in methods:
                logger.warning(f"🚫 CORS requis - Méthode refusée: {request.method}")
                return jsonify({'error': 'CORS method not allowed'}), 405
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator


def no_cors(f):
    """Décorateur pour désactiver CORS sur une route spécifique"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        g.disable_cors = True
        return f(*args, **kwargs)
    
    return decorated_function


# Fonctions d'initialisation

def init_cors(app: Flask, config=None) -> CORSMiddleware:
    """Initialise CORS sur une application Flask"""
    cors_middleware = CORSMiddleware(app, config)
    
    # Ajouter une route pour les stats CORS
    @app.route('/api/cors/stats')
    def cors_stats():
        return jsonify(cors_middleware.get_stats())
    
    return cors_middleware


def create_cors_config(origins: List[str] = None, 
                      methods: List[str] = None,
                      credentials: bool = True) -> CORSConfig:
    """Crée une configuration CORS personnalisée"""
    config = CORSConfig()
    
    if origins:
        config.default_config['origins'] = config._process_origins(origins)
    
    if methods:
        config.default_config['methods'] = methods
    
    config.default_config['credentials'] = credentials
    
    return config


# Configuration pour différents environnements

def get_development_cors_config() -> CORSConfig:
    """Configuration CORS pour développement (permissive)"""
    config = CORSConfig()
    config.default_config.update({
        'origins': ['*'],
        'credentials': True,
        'methods': ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'],
        'headers': config.default_config['headers'] + ['X-Debug-Mode']
    })
    return config


def get_production_cors_config(allowed_domains: List[str]) -> CORSConfig:
    """Configuration CORS pour production (restrictive)"""
    config = CORSConfig()
    config.default_config.update({
        'origins': allowed_domains,
        'credentials': True,
        'methods': ['GET', 'POST', 'PUT', 'DELETE'],  # Pas de PATCH
        'max_age': 3600,  # Cache réduit
    })
    
    # Routes admin plus restrictives
    config.route_configs['/api/admin/*']['origins'] = allowed_domains[:1]  # Premier domaine seulement
    
    return config


# Tests et validation

def validate_cors_config(config: CORSConfig) -> Dict[str, List[str]]:
    """Valide une configuration CORS"""
    errors = []
    warnings = []
    
    # Validation des origins
    if '*' in config.default_config['origins'] and len(config.default_config['origins']) > 1:
        warnings.append("Wildcard '*' avec d'autres origins - '*' prend le dessus")
    
    for origin in config.default_config['origins']:
        if origin != '*' and not config._validate_origin(origin):
            errors.append(f"Origin invalide: {origin}")
    
    # Validation des méthodes
    valid_methods = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS', 'HEAD']
    for method in config.default_config['methods']:
        if method not in valid_methods:
            errors.append(f"Méthode HTTP invalide: {method}")
    
    # Validation sécurité
    if config.default_config['credentials'] and '*' in config.default_config['origins']:
        warnings.append("Credentials avec wildcard origin - risque de sécurité")
    
    return {'errors': errors, 'warnings': warnings}


# Logging des requêtes CORS

def log_cors_request(origin: str, method: str, path: str, allowed: bool):
    """Log une requête CORS avec détails"""
    status = "✅ AUTORISÉ" if allowed else "🚫 REFUSÉ"
    logger.info(f"CORS {status}: {method} {path} depuis {origin}")


# Exemple d'usage
if __name__ == "__main__":
    from flask import Flask
    
    app = Flask(__name__)
    
    # Configuration CORS
    cors_config = create_cors_config(
        origins=['http://localhost:3000', 'https://dashboard.example.com'],
        credentials=True
    )
    
    # Initialisation
    cors_middleware = init_cors(app, cors_config)
    
    @app.route('/api/test')
    @cors_required(origins=['http://localhost:3000'])
    def test_endpoint():
        return jsonify({'message': 'CORS OK'})
    
    @app.route('/api/public')
    def public_endpoint():
        return jsonify({'message': 'Public endpoint'})
    
    if __name__ == '__main__':
        app.run(debug=True, host='0.0.0.0', port=5000)