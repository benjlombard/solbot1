#!/usr/bin/env python3
"""
Application Flask principale pour le Solana Wallet Monitor
Point d'entrée avec tous les blueprints et middleware configurés
"""
# Dépendances directes


import logging
import sys
import os
from pathlib import Path
import time
from datetime import datetime

# Ajouter le répertoire parent au Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Créer le répertoire logs s'il n'existe pas
log_dir = Path('logs')
log_dir.mkdir(exist_ok=True)

from flask import Flask, jsonify, request, g
import traceback

# Imports de configuration
try:
    from core.config import get_config, init_config
    from core.logger import get_logger, setup_logger
    from core.database import get_database_manager
    from core.config import Config
    from core.logger import setup_logger
    from core.database import DatabaseManager
    from api.routes.dashboard import dashboard_bp
    from api.routes.analytics import analytics_bp
    from api.routes.batching import batching_bp
    from api.routes.admin import admin_bp
    from api.middleware.cors import setup_cors
    from wallet.monitor import WalletMonitor
except ImportError as e:
    logging.warning(f"Config/core imports not available: {e}")
    # Fallbacks pour développement
    def get_config():
        class Config:
            class Flask:
                host = "0.0.0.0"
                port = 5000
                debug = True
                cors_enabled = True
                cors_origins = ['*']
            flask = Flask()
            class Environment:
                value = "DEVELOPMENT"
            environment = Environment()
        return Config()
    
    def get_logger(name):
        return logging.getLogger(name)

# Configuration du logging de base
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('logs/app.log')
    ]
)

logger = logging.getLogger(__name__)

# Imports des blueprints
try:
    from api.routes.dashboard import dashboard_bp
    from api.routes.admin import admin_bp  
    from api.routes.batching import batching_bp
    from api.middleware.auth import init_auth
    from api.middleware.cors import init_cors
except ImportError as e:
    logger.error(f"Erreur imports blueprints: {e}")
    logger.error(f"Traceback: {traceback.format_exc()}")
    # Créer des blueprints factices pour éviter les erreurs
    from flask import Blueprint
    dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/api/dashboard')
    admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin') 
    batching_bp = Blueprint('batching', __name__, url_prefix='/api/batching')
    
    @dashboard_bp.route('/health')
    def dashboard_health():
        return jsonify({"status": "fallback", "message": "Dashboard routes not loaded"})
    
    @admin_bp.route('/health')
    def admin_health():
        return jsonify({"status": "fallback", "message": "Admin routes not loaded"})
    
    @batching_bp.route('/health')
    def batching_health():
        return jsonify({"status": "fallback", "message": "Batching routes not loaded"})
    
    def init_auth(app, config=None):
        logger.warning("Auth middleware not available")
        return None
    
    def init_cors(app, config=None):
        logger.warning("CORS middleware not available") 
        return None

def create_app():
    """Factory pour créer l'application Flask"""
    
    # Initialisation de la configuration
    try:
        config = get_config()
        logger.info(f"🚀 Démarrage Solana Wallet Monitor - Environnement: {config.environment.value}")
    except Exception as e:
        logger.error(f"Erreur chargement config: {e}")
        config = get_config()  # Fallback

    # Création de l'application Flask
    app = Flask(__name__)
    
    # Configuration Flask
    app.config.update({
        'SECRET_KEY': 'dev-secret-key-change-in-production',
        'JSON_SORT_KEYS': False,
        'JSONIFY_PRETTYPRINT_REGULAR': config.flask.debug if hasattr(config, 'flask') else True
    })

    # Variables globales pour statistiques
    app.stats = {
        'start_time': time.time(),
        'total_requests': 0,
        'errors': 0
    }

    # ============= MIDDLEWARE ET HANDLERS =============
    
    @app.before_request
    def before_request():
        """Middleware avant chaque requête"""
        g.request_start_time = time.time()
        app.stats['total_requests'] += 1
        
        # Log des requêtes importantes
        if request.path.startswith('/api/'):
            logger.debug(f"🌐 {request.method} {request.path} - IP: {request.remote_addr}")

    @app.after_request 
    def after_request(response):
        """Middleware après chaque requête"""
        
        # Ajouter headers de sécurité
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        
        # Headers informatifs
        if hasattr(g, 'request_start_time'):
            duration = round((time.time() - g.request_start_time) * 1000, 2)
            response.headers['X-Response-Time'] = f"{duration}ms"
        
        response.headers['X-API-Version'] = '1.0.0'
        
        return response

    @app.errorhandler(404)
    def not_found(error):
        """Handler 404 personnalisé"""
        return jsonify({
            'error': 'Not Found',
            'message': 'The requested endpoint does not exist',
            'timestamp': int(time.time())
        }), 404

    @app.errorhandler(500)
    def internal_error(error):
        """Handler 500 personnalisé"""
        app.stats['errors'] += 1
        logger.error(f"Erreur 500: {error}")
        
        return jsonify({
            'error': 'Internal Server Error',
            'message': 'An unexpected error occurred',
            'timestamp': int(time.time())
        }), 500

    @app.errorhandler(Exception)
    def handle_exception(e):
        """Handler général des exceptions"""
        app.stats['errors'] += 1
        logger.error(f"Exception non gérée: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        return jsonify({
            'error': 'Unexpected Error',
            'message': str(e),
            'timestamp': int(time.time())
        }), 500

    # ============= ROUTES PRINCIPALES =============

    @app.route('/')
    def root():
        """Page d'accueil de l'API"""
        uptime = time.time() - app.stats['start_time']
        
        return jsonify({
            'name': 'Solana Wallet Monitor API',
            'version': '2.0.0',
            'status': 'running',
            'uptime_seconds': round(uptime, 2),
            'environment': getattr(getattr(config, 'environment', None), 'value', 'unknown'),
            'endpoints': {
                'dashboard': '/api/dashboard/',
                'admin': '/api/admin/health',
                'batching': '/api/batching/status',
                'health': '/health',
                'stats': '/stats'
            },
            'documentation': {
                'dashboard': 'Interface principale de visualisation',
                'admin': 'Administration et monitoring système', 
                'batching': 'Contrôle du système de batching RPC'
            }
        })

    @app.route('/health')
    def health_check():
        """Health check global de l'application"""
        try:
            checks = {
                'api': {'status': 'ok', 'message': 'API running'},
                'config': {'status': 'ok', 'message': 'Configuration loaded'},
                'database': {'status': 'unknown', 'message': 'Not checked'},
                'routes': {'status': 'ok', 'message': f'{len(app.blueprints)} blueprints registered'}
            }
            
            # Test base de données si disponible
            try:
                db_manager = get_database_manager()
                with db_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT 1")
                    result = cursor.fetchone()
                    if result:
                        checks['database'] = {'status': 'ok', 'message': 'Database connected'}
            except Exception as db_e:
                checks['database'] = {'status': 'error', 'message': f'Database error: {str(db_e)}'}

            # Déterminer le statut global
            all_ok = all(check['status'] == 'ok' for check in checks.values())
            has_errors = any(check['status'] == 'error' for check in checks.values())
            
            overall_status = 'healthy' if all_ok else 'critical' if has_errors else 'degraded'
            
            return jsonify({
                'status': overall_status,
                'timestamp': int(time.time()),
                'uptime_seconds': round(time.time() - app.stats['start_time'], 2),
                'version': '2.0.0',
                'checks': checks,
                'statistics': {
                    'total_requests': app.stats['total_requests'],
                    'total_errors': app.stats['errors'],
                    'error_rate': round((app.stats['errors'] / max(app.stats['total_requests'], 1)) * 100, 2)
                }
            })
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return jsonify({
                'status': 'critical',
                'timestamp': int(time.time()),
                'error': str(e)
            }), 500

    @app.route('/stats')
    def app_stats():
        """Statistiques de l'application"""
        uptime = time.time() - app.stats['start_time']
        
        return jsonify({
            'application': {
                'name': 'Solana Wallet Monitor',
                'version': '2.0.0',
                'uptime_seconds': round(uptime, 2),
                'uptime_human': f"{int(uptime // 3600)}h {int((uptime % 3600) // 60)}m"
            },
            'requests': {
                'total': app.stats['total_requests'],
                'errors': app.stats['errors'],
                'success_rate': round(((app.stats['total_requests'] - app.stats['errors']) / max(app.stats['total_requests'], 1)) * 100, 2),
                'requests_per_minute': round(app.stats['total_requests'] / (uptime / 60), 2) if uptime > 0 else 0
            },
            'routes': {
                'registered_blueprints': len(app.blueprints),
                'blueprint_names': list(app.blueprints.keys())
            },
            'environment': getattr(getattr(config, 'environment', None), 'value', 'unknown'),
            'timestamp': int(time.time())
        })

    # ============= ENREGISTREMENT DES BLUEPRINTS =============

    # Blueprint Dashboard (interface principale)
    app.register_blueprint(dashboard_bp)
    logger.info("✅ Dashboard routes enregistrées: /api/dashboard/*")

    # Blueprint Admin (gestion système)
    app.register_blueprint(admin_bp)
    logger.info("✅ Admin routes enregistrées: /api/admin/*")

    # Blueprint Batching (contrôle RPC)
    app.register_blueprint(batching_bp) 
    logger.info("✅ Batching routes enregistrées: /api/batching/*")

    # ============= INITIALISATION MIDDLEWARE =============

    # Middleware d'authentification (si configuré)
    try:
        if hasattr(config, 'auth') and getattr(config.auth, 'enabled', False):
            auth_middleware = init_auth(app)
            if auth_middleware:
                logger.info("🔐 Middleware d'authentification activé")
        else:
            logger.info("🔓 Authentification désactivée")
    except Exception as e:
        logger.warning(f"Authentification non configurée: {e}")

    # Middleware CORS (si configuré) 
    try:
        if hasattr(config, 'flask') and getattr(config.flask, 'cors_enabled', True):
            cors_middleware = init_cors(app)
            if cors_middleware:
                logger.info("🌐 Middleware CORS activé")
        else:
            logger.info("🚫 CORS désactivé")
    except Exception as e:
        logger.warning(f"CORS non configuré: {e}")

    # ============= ROUTES DE DEBUG (développement) =============
    
    if hasattr(config, 'flask') and getattr(config.flask, 'debug', False):
        
        @app.route('/debug/routes')
        def debug_routes():
            """Liste toutes les routes (debug uniquement)"""
            routes = []
            for rule in app.url_map.iter_rules():
                routes.append({
                    'endpoint': rule.endpoint,
                    'methods': list(rule.methods),
                    'path': str(rule.rule)
                })
            
            return jsonify({
                'total_routes': len(routes),
                'routes': sorted(routes, key=lambda x: x['path'])
            })

        @app.route('/debug/config')  
        def debug_config():
            """Configuration (masquée, debug uniquement)"""
            try:
                return jsonify({
                    'environment': config.environment.value,
                    'flask': {
                        'host': config.flask.host,
                        'port': config.flask.port,
                        'debug': config.flask.debug,
                        'cors_enabled': config.flask.cors_enabled
                    },
                    'blueprints_loaded': list(app.blueprints.keys()),
                    'note': 'Configuration sensible masquée'
                })
            except Exception as e:
                return jsonify({'error': str(e)})

        logger.info("🐛 Routes de debug activées (/debug/*)")

    # ============= FINALISATION =============
    
    logger.info(f"🎯 Application Flask créée avec {len(app.blueprints)} blueprints")
    logger.info(f"📊 Total des routes: {len(list(app.url_map.iter_rules()))}")
    
    return app

# ============= POINT D'ENTRÉE PRINCIPAL =============

# Création de l'instance d'application
app = create_app()

if __name__ == "__main__":
    """Démarrage de l'application en mode development"""
    
    try:
        # Récupération de la configuration
        config = get_config()
        
        # Configuration du serveur
        host = getattr(getattr(config, 'flask', None), 'host', '127.0.0.1')
        port = getattr(getattr(config, 'flask', None), 'port', 5000)
        debug = getattr(getattr(config, 'flask', None), 'debug', True)
        
        logger.info("=" * 60)
        logger.info("🚀 DÉMARRAGE SOLANA WALLET MONITOR")
        logger.info("=" * 60)
        logger.info(f"🌐 Serveur: http://{host}:{port}")
        logger.info(f"🔧 Mode debug: {'Activé' if debug else 'Désactivé'}")
        logger.info(f"📍 Endpoints principaux:")
        logger.info(f"   • Dashboard: http://{host}:{port}/api/dashboard/")
        logger.info(f"   • Admin: http://{host}:{port}/api/admin/health")
        logger.info(f"   • Health: http://{host}:{port}/health")
        logger.info("=" * 60)
        
        # Démarrer le serveur
        app.run(
            host=host,
            port=port,
            debug=debug,
            threaded=True,
            use_reloader=debug,
            reload=False
        )
        
    except KeyboardInterrupt:
        logger.info("🛑 Arrêt de l'application par l'utilisateur")
    except Exception as e:
        logger.error(f"💥 Erreur critique au démarrage: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        sys.exit(1)
