#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
import traceback


if sys.platform.startswith('win'):
    # Forcer UTF-8 pour toute l'application
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    
    # Reconfigurer les streams si possible
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass



# Ajouter le répertoire parent au Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Créer le répertoire logs s'il n'existe pas
log_dir = Path('logs')
log_dir.mkdir(exist_ok=True)

from flask import Flask, jsonify, request, g

# === CONFIGURATION LOGGING SÉCURISÉ ===
class UnicodeFileHandler(logging.FileHandler):
    """Handler de fichier avec encodage UTF-8 forcé"""
    def __init__(self, filename, mode='a', encoding='utf-8', delay=False):
        super().__init__(filename, mode, encoding, delay)

class SafeConsoleHandler(logging.StreamHandler):
    """Handler console qui gère les erreurs Unicode"""
    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self.stream
            
            # Sur Windows, gérer l'encodage
            if sys.platform.startswith('win'):
                try:
                    stream.write(msg + self.terminator)
                except UnicodeEncodeError:
                    # Remplacer les caractères problématiques
                    safe_msg = msg.encode('ascii', errors='replace').decode('ascii')
                    stream.write(safe_msg + self.terminator)
            else:
                stream.write(msg + self.terminator)
            
            self.flush()
            
        except Exception:
            self.handleError(record)

# Configuration du logging de base
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        UnicodeFileHandler('logs/app.log')
    ]
)

logger = logging.getLogger(__name__)

try:
    from api.routes.trading import trading_bp, init_trading_routes
except ImportError as e:
    logging.warning(f"Trading routes non disponibles: {e}")
    trading_bp = None

# Imports de configuration avec fallbacks
try:
    from core.config import get_config, init_config
    from core.logger import get_logger, setup_logger
    from core.database import get_database_manager
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
    
    def get_database_manager():
        raise ImportError("DatabaseManager not available")

def load_blueprints():
    """Charge les blueprints avec gestion d'erreurs détaillée"""
    blueprints = []
    
    blueprint_configs = [
        ('dashboard', 'api.routes.dashboard', 'dashboard_bp', '/api/dashboard/*'),
        ('analytics', 'api.routes.analytics', 'analytics_bp', '/api/analytics/*'),
        ('admin', 'api.routes.admin', 'admin_bp', '/api/admin/*'),
        ('batching', 'api.routes.batching', 'batching_bp', '/api/batching/*'),
        ('trading', 'api.routes.trading', 'trading_bp', '/api/trading/*') 
    ]
    
    for name, module_path, bp_name, route_prefix in blueprint_configs:
        try:
            module = __import__(module_path, fromlist=[bp_name])
            blueprint = getattr(module, bp_name)
            blueprints.append((name, blueprint, route_prefix))
            logger.debug(f"✅ Blueprint {name} chargé depuis {module_path}")
        except ImportError as e:
            logger.warning(f"⚠️ Blueprint {name} non disponible: {e}")
            blueprints.append((name, None, route_prefix))
        except AttributeError as e:
            logger.error(f"❌ Blueprint {name}: {bp_name} non trouvé dans {module_path}")
            blueprints.append((name, None, route_prefix))
    
    return blueprints

blueprints_config = load_blueprints()


# Middleware
try:
    from api.middleware.auth import init_auth
except ImportError as e:
    logger.warning(f"Auth middleware non disponible: {e}")
    def init_auth(app, config=None):
        logger.warning("Auth middleware stub")
        return None

try:
    from api.middleware.cors import init_cors  # ✅ CORRECTION ICI
except ImportError as e:
    logger.warning(f"CORS middleware non disponible: {e}")
    def init_cors(app, config=None):
        logger.warning("CORS middleware stub")
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
    app = Flask(__name__, template_folder='templates', static_folder='static')
    
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
        
        # Détecter les blueprints enregistrés
        registered_bp = list(app.blueprints.keys())
        
        endpoints = {
            'health': '/health',
            'stats': '/stats',
            'dashboard': '/api/dashboard/' if 'dashboard' in registered_bp else None,
            'analytics': '/api/analytics/' if 'analytics' in registered_bp else None,
            'admin': '/api/admin/health' if 'admin' in registered_bp else None,
            'batching': '/api/batching/status' if 'batching' in registered_bp else None,
            'trading': '/api/trading/health' if 'trading' in registered_bp else None,
        }
        
        # Filtrer les endpoints None
        available_endpoints = {k: v for k, v in endpoints.items() if v is not None}

        return jsonify({
            'name': 'Solana Wallet Monitor API',
            'version': '2.0.0',
            'status': 'running',
            'uptime_seconds': round(uptime, 2),
            'environment': getattr(getattr(config, 'environment', None), 'value', 'unknown'),
            'blueprints_registered': len(registered_bp),
            'blueprints': registered_bp,
            'endpoints': available_endpoints,
            'documentation': {
                'dashboard': 'Interface principale de visualisation',
                'analytics': 'API d\'analyse des wallets Solana',
                'admin': 'Administration et monitoring système', 
                'batching': 'Contrôle du système de batching RPC',
                'trading': 'Interface de trading avec Phantom Wallet',
                'health': 'Statut de santé de l\'application',
                'stats': 'Statistiques d\'utilisation'
            },
            'unicode_support': '🚀✅📊🎯',  # Test des emojis dans la réponse
            'message': '🎉 API Solana Wallet Monitor opérationnelle!'
        })


    @app.route('/debug/routes-list')
    def debug_routes_list():
        """Debug: Liste toutes les routes enregistrées"""
        try:
            routes_info = []
            for rule in app.url_map.iter_rules():
                routes_info.append({
                    'endpoint': rule.endpoint,
                    'rule': str(rule.rule),
                    'methods': list(rule.methods)
                })
            
            # Grouper par règle pour détecter les duplicatas
            rules_count = {}
            for route in routes_info:
                rule = route['rule']
                if rule in rules_count:
                    rules_count[rule].append(route)
                else:
                    rules_count[rule] = [route]
            
            duplicates = {rule: routes for rule, routes in rules_count.items() if len(routes) > 1}
            
            return jsonify({
                'total_routes': len(routes_info),
                'all_routes': sorted(routes_info, key=lambda x: x['rule']),
                'duplicates': duplicates,
                'health_routes': [r for r in routes_info if 'health' in r['rule']],
                'dashboard_routes': [r for r in routes_info if 'dashboard' in r['rule']]
            })
            
        except Exception as e:
            return jsonify({
                'error': str(e),
                'message': 'Failed to list routes'
            }), 500

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

    @app.route('/trading')
    def trading_interface():
        """Interface de trading"""
        try:
            return render_template('trading.html')
        except Exception as e:
            logger.error(f"Erreur template trading: {e}")
            return jsonify({'error': 'Trading interface not available'}), 500

    # ============= ENREGISTREMENT DES BLUEPRINTS =============

    registered_blueprints = []

    # Enregistrement avec gestion d'erreurs
    for name, blueprint, path in blueprints_config:
        if blueprint is not None:
            try:
                app.register_blueprint(blueprint)
                registered_blueprints.append(name)
                logger.info(f"✅ {name.capitalize()} routes enregistrées: {path}")
            except Exception as bp_error:
                logger.error(f"❌ Erreur enregistrement blueprint {name}: {bp_error}")
        else:
            logger.warning(f"⚠️ Blueprint {name} non disponible")

    # Vérification analytics
    if 'analytics' not in registered_blueprints:
        logger.warning("⚠️ Blueprint Analytics manquant - certaines fonctionnalités seront indisponibles")

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

def test_application_startup():
    """Teste les composants critiques avant démarrage"""
    tests = []
    
    # Test emojis
    try:
        test_msg = "🚀 Test emoji"
        test_msg.encode('utf-8')
        tests.append(('Unicode/Emojis', True, 'OK'))
    except Exception as e:
        tests.append(('Unicode/Emojis', False, str(e)))
    
    # Test config
    try:
        config = get_config()
        tests.append(('Configuration', True, 'Chargée'))
    except Exception as e:
        tests.append(('Configuration', False, str(e)))
    
    # Test blueprints
    bp_count = len([bp for name, bp, path in blueprints_config if bp is not None])
    tests.append(('Blueprints', bp_count > 0, f'{bp_count} disponibles'))
    
    # Afficher les résultats
    logger.info("🧪 Tests de démarrage:")
    for test_name, success, details in tests:
        status = "✅" if success else "❌"
        logger.info(f"   {status} {test_name}: {details}")
    
    return all(test[1] for test in tests)

# Création de l'instance d'application
app = create_app()

if __name__ == "__main__":
    """Démarrage de l'application en mode development"""

    if not test_application_startup():
        logger.warning("⚠️ Certains tests ont échoué, démarrage quand même...")

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
        logger.info(f"   • Analytics: http://{host}:{port}/api/analytics/")  # ✅ Ajouter analytics
        logger.info(f"   • Admin: http://{host}:{port}/api/admin/health")
        logger.info(f"   • Health: http://{host}:{port}/health")
        logger.info(f"   • Stats: http://{host}:{port}/stats")
        logger.info(f"💱 Trading API: http://{host}:{port}/api/trading")  # NOUVEAU
        logger.info(f"🎯 Trading Interface: http://{host}:{port}/trading")  # NOUVEAU
        logger.info("=" * 60)
        
        # Test des emojis
        logger.info("🎯 Test emojis: ✅ 🚀 📊 🔧")

        # Démarrer le serveur
        app.run(
            host=host,
            port=port,
            debug=debug,
            threaded=True,
            use_reloader=debug
        )
        
    except KeyboardInterrupt:
        logger.info("🛑 Arrêt de l'application par l'utilisateur")
    except Exception as e:
        logger.error(f"💥 Erreur critique au démarrage: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        sys.exit(1)
