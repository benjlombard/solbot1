
#!/usr/bin/env python3
"""
Routes API pour le dashboard principal du Solana Wallet Monitor
Interface principale pour la visualisation des données en temps réel
"""

from flask import Blueprint, request, jsonify, render_template
from typing import Dict, List, Optional, Any, Union
import time
import logging
from datetime import datetime, timedelta
from dataclasses import asdict

# Imports des modèles et utilitaires
try:
    from models.wallet import WalletPriority, WalletStats, WalletActivityMetrics
    from models.token import Token, TokenAccount, TokenDiscovery
    from models.transaction import Transaction, TransactionType, TransactionStatus
    from models.schemas import (
        PaginationParams, WalletFilterParams, TransactionFilterParams,
        ApiResponse, PaginatedResponse, create_success_response, create_error_response
    )
    from core.database import get_database_manager
    from core.config import get_config
    from utils.formatters import (
        format_sol_amount, format_token_amount, format_timestamp,
        format_percentage, format_duration
    )
    from utils.helpers import safe_get, calculate_moving_average, get_current_timestamp
except ImportError as e:
    logging.warning(f"Import error in dashboard routes: {e}")
    # Fallbacks pour développement
    def create_success_response(msg, data=None): 
        return {'success': True, 'message': msg, 'data': data}
    def create_error_response(msg, errors=None): 
        return {'success': False, 'message': msg, 'errors': errors or []}

# Configuration du logger
logger = logging.getLogger(__name__)

# Création du blueprint
dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/api/dashboard')

# Variables globales pour cache et configuration
_dashboard_cache = {}
_cache_expiry = {}
CACHE_DURATION = 30  # 30 secondes


def get_db_connection():
    """Récupère une connexion à la base de données"""
    try:
        db_manager = get_database_manager()
        return db_manager.get_connection()
    except Exception as e:
        logger.error(f"Erreur connexion DB: {e}")
        raise


def cache_result(key: str, data: Any, duration: int = CACHE_DURATION):
    """Met en cache un résultat"""
    _dashboard_cache[key] = data
    _cache_expiry[key] = time.time() + duration


def get_cached_result(key: str) -> Optional[Any]:
    """Récupère un résultat du cache s'il est valide"""
    if key in _dashboard_cache and time.time() < _cache_expiry.get(key, 0):
        return _dashboard_cache[key]
    return None


def clear_expired_cache():
    """Nettoie le cache expiré"""
    current_time = time.time()
    expired_keys = [k for k, exp_time in _cache_expiry.items() if current_time > exp_time]
    for key in expired_keys:
        _dashboard_cache.pop(key, None)
        _cache_expiry.pop(key, None)


# ============= ROUTES PRINCIPALES DU DASHBOARD =============

@dashboard_bp.route('/', methods=['GET'])
@dashboard_bp.route('/index', methods=['GET'])  # Route alternative
def dashboard_home():
    """Page principale du dashboard"""
    try:
        return render_template('dashboard.html')
    except Exception as e:
        logger.error(f"Erreur template dashboard: {e}")
        return jsonify({'error': 'Dashboard template not found'}), 500

@dashboard_bp.route('/debug', methods=['GET', 'POST'])
def debug_routes():
    """Debug des routes disponibles"""
    from flask import current_app
    routes = []
    for rule in current_app.url_map.iter_rules():
        if 'dashboard' in rule.endpoint:
            routes.append({
                'endpoint': rule.endpoint,
                'methods': list(rule.methods),
                'rule': str(rule.rule)
            })
    return jsonify({
        'dashboard_routes': routes,
        'request_method': request.method,
        'request_url': request.url
    })

@dashboard_bp.route('/config-debug')
def config_debug():
    """Debug de la configuration des wallets"""
    from core.config import get_config
    
    config = get_config()
    
    return jsonify({
        'wallets_configured': config.wallet.addresses,
        'total_wallets': len(config.wallet.addresses),
        'primary_wallet': config.wallet.primary_address,
        'selection_mode': config.wallet.selection_mode.value,
        'database_path': config.database.get_full_path()
    })



@dashboard_bp.route('/debug/wallet-overview')
def debug_wallet_overview():
    """Debug détaillé pour la route wallet-overview"""
    try:
        debug_info = {
            'timestamp': get_current_timestamp(),
            'request_info': {
                'method': request.method,
                'url': request.url,
                'endpoint': request.endpoint
            },
            'database_checks': {},
            'wallet_data': {},
            'errors': [],
            'suggestions': []
        }
        
        # Test de connexion à la base de données
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                debug_info['database_checks']['connection'] = 'OK'
                
                # 1. Vérifier la table wallet_priorities
                try:
                    cursor.execute("SELECT COUNT(*) FROM wallet_priorities")
                    total_wallets = cursor.fetchone()[0]
                    debug_info['database_checks']['wallet_priorities_count'] = total_wallets
                    
                    if total_wallets == 0:
                        debug_info['errors'].append("Table wallet_priorities est vide")
                        debug_info['suggestions'].append("Vérifiez que vos wallets ont été ajoutés dans wallet_priorities")
                    
                except Exception as e:
                    debug_info['database_checks']['wallet_priorities_error'] = str(e)
                    debug_info['errors'].append(f"Erreur accès wallet_priorities: {e}")
                
                # 2. Vérifier la structure de la table
                try:
                    cursor.execute("PRAGMA table_info(wallet_priorities)")
                    columns = cursor.fetchall()
                    debug_info['database_checks']['wallet_priorities_columns'] = [col[1] for col in columns]
                    
                    required_columns = ['wallet_address', 'priority_score', 'last_scan_time', 'total_scans', 'activity_score', 'consecutive_empty_scans']
                    missing_columns = [col for col in required_columns if col not in [c[1] for c in columns]]
                    
                    if missing_columns:
                        debug_info['errors'].append(f"Colonnes manquantes: {missing_columns}")
                        debug_info['suggestions'].append("Vérifiez le schéma de votre table wallet_priorities")
                    
                except Exception as e:
                    debug_info['database_checks']['schema_error'] = str(e)
                
                # 3. Échantillon de données wallet_priorities
                try:
                    cursor.execute("""
                        SELECT 
                            wallet_address, 
                            priority_score, 
                            last_scan_time, 
                            total_scans, 
                            activity_score, 
                            consecutive_empty_scans
                        FROM wallet_priorities 
                        ORDER BY priority_score DESC 
                        LIMIT 5
                    """)
                    sample_wallets = cursor.fetchall()
                    
                    debug_info['wallet_data']['sample_wallets'] = []
                    for row in sample_wallets:
                        debug_info['wallet_data']['sample_wallets'].append({
                            'wallet_address': row[0],
                            'wallet_short': f"{row[0][:8]}...{row[0][-8:]}" if row[0] else 'None',
                            'priority_score': row[1],
                            'last_scan_time': row[2],
                            'total_scans': row[3],
                            'activity_score': row[4],
                            'consecutive_empty_scans': row[5],
                            'minutes_since_scan': round((get_current_timestamp() - (row[2] or 0)) / 60, 1) if row[2] else 999
                        })
                        
                except Exception as e:
                    debug_info['wallet_data']['sample_error'] = str(e)
                
                # 4. Vérifier la table token_accounts
                try:
                    cursor.execute("SELECT COUNT(*) FROM token_accounts")
                    token_accounts_count = cursor.fetchone()[0]
                    debug_info['database_checks']['token_accounts_count'] = token_accounts_count
                    
                    # Compter par wallet
                    cursor.execute("""
                        SELECT 
                            wallet_address, 
                            COUNT(*) as account_count,
                            COUNT(CASE WHEN is_active = 1 THEN 1 END) as active_count
                        FROM token_accounts 
                        GROUP BY wallet_address 
                        ORDER BY account_count DESC 
                        LIMIT 3
                    """)
                    token_stats = cursor.fetchall()
                    debug_info['wallet_data']['token_accounts_by_wallet'] = [
                        {
                            'wallet': f"{row[0][:8]}...{row[0][-8:]}" if row[0] else 'None',
                            'total_accounts': row[1],
                            'active_accounts': row[2]
                        } for row in token_stats
                    ]
                    
                except Exception as e:
                    debug_info['database_checks']['token_accounts_error'] = str(e)
                
                # 5. Vérifier la table transactions
                try:
                    cursor.execute("SELECT COUNT(*) FROM transactions")
                    transactions_count = cursor.fetchone()[0]
                    debug_info['database_checks']['transactions_count'] = transactions_count
                    
                    # Transactions récentes par wallet
                    current_time = get_current_timestamp()
                    cursor.execute("""
                        SELECT 
                            wallet_address, 
                            COUNT(*) as tx_24h
                        FROM transactions 
                        WHERE block_time >= ?
                        GROUP BY wallet_address 
                        ORDER BY tx_24h DESC 
                        LIMIT 3
                    """, (current_time - 86400,))
                    tx_stats = cursor.fetchall()
                    debug_info['wallet_data']['transactions_24h_by_wallet'] = [
                        {
                            'wallet': f"{row[0][:8]}...{row[0][-8:]}" if row[0] else 'None',
                            'transactions_24h': row[1]
                        } for row in tx_stats
                    ]
                    
                except Exception as e:
                    debug_info['database_checks']['transactions_error'] = str(e)
                
                # 6. Test de la requête complète wallet-overview
                try:
                    current_time = get_current_timestamp()
                    cursor.execute("""
                        SELECT 
                            wp.wallet_address,
                            wp.priority_score,
                            wp.last_scan_time,
                            wp.total_scans,
                            wp.activity_score,
                            wp.consecutive_empty_scans,
                            (? - wp.last_scan_time) as seconds_since_scan,
                            
                            -- Stats des comptes de tokens
                            (SELECT COUNT(*) FROM token_accounts ta 
                             WHERE ta.wallet_address = wp.wallet_address AND ta.is_active = 1) as total_accounts,
                            (SELECT COUNT(*) FROM token_accounts ta 
                             WHERE ta.wallet_address = wp.wallet_address 
                             AND ta.scan_priority >= 3) as priority_accounts,
                            
                            -- Stats des transactions (24h)
                            (SELECT COUNT(*) FROM transactions t 
                             WHERE t.wallet_address = wp.wallet_address 
                             AND t.block_time >= ?) as transactions_24h
                             
                        FROM wallet_priorities wp
                        ORDER BY wp.priority_score DESC
                        LIMIT 3
                    """, (current_time, current_time - 86400))
                    
                    test_results = cursor.fetchall()
                    debug_info['wallet_data']['full_query_test'] = []
                    
                    for row in test_results:
                        wallet_addr = row[0]
                        priority_score = row[1]
                        last_scan = row[2]
                        since_scan = row[6]
                        total_accounts = row[7] or 0
                        priority_accounts = row[8] or 0
                        tx_24h = row[9] or 0
                        
                        # Calculer le statut
                        if since_scan <= 60:
                            scan_status = "recent"
                        elif since_scan <= 300:
                            scan_status = "normal"
                        else:
                            scan_status = "overdue"
                        
                        # Calculer la priorité
                        if priority_score >= 4.0:
                            priority_category = "high"
                        elif priority_score >= 2.0:
                            priority_category = "medium"
                        else:
                            priority_category = "low"
                        
                        debug_info['wallet_data']['full_query_test'].append({
                            'wallet_address': wallet_addr,
                            'wallet_short': f"{wallet_addr[:8]}...{wallet_addr[-8:]}",
                            'priority_score': round(priority_score, 2),
                            'priority_category': priority_category,
                            'scan_status': scan_status,
                            'seconds_since_scan': since_scan,
                            'total_token_accounts': total_accounts,
                            'priority_accounts': priority_accounts,
                            'transactions_24h': tx_24h
                        })
                    
                    debug_info['wallet_data']['full_query_success'] = True
                    debug_info['wallet_data']['processed_wallets'] = len(test_results)
                    
                except Exception as e:
                    debug_info['wallet_data']['full_query_error'] = str(e)
                    debug_info['errors'].append(f"Erreur requête complète: {e}")
        
        except Exception as e:
            debug_info['database_checks']['connection_error'] = str(e)
            debug_info['errors'].append(f"Erreur connexion base de données: {e}")
        
        # 7. Test de la configuration
        try:
            config = get_config()
            debug_info['config_check'] = {
                'wallet_addresses_configured': len(config.wallet.addresses),
                'sample_configured_addresses': [
                    f"{addr[:8]}...{addr[-8:]}" for addr in config.wallet.addresses[:3]
                ] if hasattr(config.wallet, 'addresses') else []
            }
            
            # Vérifier si les adresses configurées sont dans wallet_priorities
            if hasattr(config.wallet, 'addresses'):
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    
                    configured_in_db = []
                    missing_from_db = []
                    
                    for addr in config.wallet.addresses[:5]:  # Test sur les 5 premiers
                        cursor.execute("SELECT COUNT(*) FROM wallet_priorities WHERE wallet_address = ?", (addr,))
                        count = cursor.fetchone()[0]
                        
                        if count > 0:
                            configured_in_db.append(f"{addr[:8]}...{addr[-8:]}")
                        else:
                            missing_from_db.append(f"{addr[:8]}...{addr[-8:]}")
                    
                    debug_info['config_check']['configured_in_db'] = configured_in_db
                    debug_info['config_check']['missing_from_db'] = missing_from_db
                    
                    if missing_from_db:
                        debug_info['errors'].append(f"Wallets configurés mais absents de wallet_priorities: {len(missing_from_db)}")
                        debug_info['suggestions'].append("Lancez le système de monitoring pour initialiser wallet_priorities")
                        
        except Exception as e:
            debug_info['config_check'] = {'error': str(e)}
        
        # 8. Suggestions supplémentaires
        if not debug_info['errors']:
            debug_info['suggestions'].append("✅ Tout semble fonctionner correctement")
            debug_info['suggestions'].append("Si le problème persiste, vérifiez la console JavaScript pour les erreurs d'appel API")
        else:
            debug_info['suggestions'].append("🔧 Corrigez les erreurs listées ci-dessus")
            debug_info['suggestions'].append("📊 Vérifiez que le système de monitoring est démarré")
            debug_info['suggestions'].append("🔄 Essayez de redémarrer l'application après corrections")
        
        # 9. Informations de cache
        try:
            cache_key = "wallet_overview"
            cached_data = get_cached_result(cache_key)
            debug_info['cache_info'] = {
                'has_cached_data': cached_data is not None,
                'cache_size': len(str(cached_data)) if cached_data else 0,
                'cache_keys_count': len(_dashboard_cache)
            }
        except Exception as e:
            debug_info['cache_info'] = {'error': str(e)}
        
        # Status final
        debug_info['overall_status'] = 'OK' if not debug_info['errors'] else 'ERRORS_FOUND'
        debug_info['total_errors'] = len(debug_info['errors'])
        debug_info['total_suggestions'] = len(debug_info['suggestions'])
        
        return jsonify({
            'success': True,
            'message': f"Debug wallet-overview completed - Status: {debug_info['overall_status']}",
            'data': debug_info
        })
        
    except Exception as e:
        logger.error(f"Debug wallet-overview failed: {e}")
        import traceback
        return jsonify({
            'success': False,
            'message': f"Debug failed: {e}",
            'traceback': traceback.format_exc(),
            'data': None
        }), 500

@dashboard_bp.route('/dashboard-data', methods=['GET', 'POST'])
def debug_dashboard_data():
    """Debug de l'URL problématique"""
    from flask import request
    return jsonify({
        'message': 'URL dashboard-data appelée (avec tiret)',
        'method': request.method,
        'url': request.url,
        'redirect_to': '/api/dashboard/data',
        'note': 'Cette URL devrait être /dashboard/data avec un slash'
    })

@dashboard_bp.route('/data')
def get_dashboard_data():
    """Données principales pour le dashboard - VERSION MULTI-WALLETS AMÉLIORÉE"""
    try:
        # Vérifier le cache
        cache_key = "dashboard_main_data"
        cached_data = get_cached_result(cache_key)
        if cached_data:
            return jsonify(create_success_response("Dashboard data retrieved from cache", cached_data))

        with get_db_connection() as conn:
            cursor = conn.cursor()
            current_time = int(time.time())
            
            # === STATISTIQUES GÉNÉRALES MULTI-WALLETS ===
            
            # Comptes de tokens actifs
            cursor.execute("SELECT COUNT(*) FROM token_accounts WHERE is_active = 1")
            total_token_accounts = cursor.fetchone()[0] or 0
            
            # Tokens uniques découverts
            cursor.execute("""
                SELECT COUNT(DISTINCT token_mint) 
                FROM transactions 
                WHERE is_token_transaction = 1
            """)
            total_unique_tokens = cursor.fetchone()[0] or 0
            
            # Balance changes dernière heure
            cursor.execute("""
                SELECT COUNT(*) FROM transactions 
                WHERE is_token_transaction = 1 
                AND block_time >= ?
            """, (current_time - 3600,))
            balance_changes_1h = cursor.fetchone()[0] or 0
            
            # Grosses transactions 24h
            cursor.execute("""
                SELECT COUNT(*) FROM transactions 
                WHERE is_large_token_amount = 1 
                AND block_time >= ?
            """, (current_time - 86400,))
            large_transactions_24h = cursor.fetchone()[0] or 0
            
            # Dernier scan
            cursor.execute("SELECT MAX(completed_at) FROM scan_history")
            last_scan_result = cursor.fetchone()
            last_scan_time = last_scan_result[0] if last_scan_result[0] else 0
            
            # Total wallets monitorés
            cursor.execute("SELECT COUNT(DISTINCT wallet_address) FROM wallet_priorities")
            total_wallets = cursor.fetchone()[0] or 0
            
            # === TOKENS LES PLUS ACTIFS (24H) ===
            cursor.execute("""
                SELECT 
                    t.token_symbol, 
                    t.token_mint, 
                    t.wallet_address,
                    COUNT(*) as tx_count,
                    SUM(CASE WHEN t.transaction_type = 'buy' THEN t.token_amount ELSE 0 END) as total_bought,
                    SUM(CASE WHEN t.transaction_type = 'sell' THEN t.token_amount ELSE 0 END) as total_sold,
                    AVG(CASE WHEN t.price_per_token > 0 THEN t.price_per_token ELSE NULL END) as avg_price,
                    MAX(t.block_time) as last_activity,
                    SUM(ABS(t.amount)) as total_sol_volume
                FROM transactions t
                WHERE t.is_token_transaction = 1 
                AND t.block_time >= ?
                GROUP BY t.token_mint, t.token_symbol, t.wallet_address
                HAVING tx_count >= 1
                ORDER BY tx_count DESC, last_activity DESC
                LIMIT 20
            """, (current_time - 86400,))

            top_tokens_raw = cursor.fetchall()
            top_tokens = []
            
            for row in top_tokens_raw:
                symbol = row[0] or 'UNKNOWN'
                mint = row[1]
                wallet = row[2]
                tx_count = row[3]
                bought = row[4] or 0
                sold = row[5] or 0
                avg_price = row[6] or 0
                last_activity = row[7]
                sol_volume = row[8] or 0
                
                # Calculer un score d'activité
                activity_score = min(100, (tx_count * 10) + (sol_volume * 5))
                
                top_tokens.append({
                    'symbol': symbol,
                    'mint': mint,
                    'mint_short': f"{mint[:6]}...{mint[-6:]}" if mint else "Unknown",
                    'wallet_address': wallet,
                    'wallet_short': f"{wallet[:4]}...{wallet[-4:]}" if wallet else "Unknown",
                    'transaction_count': tx_count,
                    'total_bought': round(bought, 4),
                    'total_sold': round(sold, 4),
                    'net_position': round(bought - sold, 4),
                    'avg_price': round(avg_price, 6) if avg_price else None,
                    'sol_volume': round(sol_volume, 4),
                    'last_activity': last_activity,
                    'activity_score': round(activity_score, 1),
                    'hours_ago': round((current_time - last_activity) / 3600, 1) if last_activity else 999
                })

            # === NOUVEAUX TOKENS RÉCENTS (GEMS) ===
            new_gems = []
            recent_discoveries = [t for t in top_tokens if t['hours_ago'] < 2]  # Moins de 2h
            for token in recent_discoveries[:5]:
                if token['transaction_count'] >= 2:  # Au moins 2 transactions
                    new_gems.append({
                        **token,
                        'discovery_type': 'recent_activity',
                        'confidence': 'high' if token['transaction_count'] >= 5 else 'medium'
                    })

            # === ALERTES VOLUME ÉLEVÉ ===
            volume_alerts = []
            high_volume_tokens = [t for t in top_tokens if t['sol_volume'] > 1.0]  # Plus de 1 SOL
            for token in high_volume_tokens[:5]:
                volume_alerts.append({
                    **token,
                    'alert_type': 'high_volume',
                    'alert_level': 'critical' if token['sol_volume'] > 10 else 'warning'
                })

            # === STATISTIQUES DES WALLETS ===
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_wallets,
                    COUNT(CASE WHEN priority_score >= 4.0 THEN 1 END) as high_priority,
                    COUNT(CASE WHEN priority_score >= 2.0 AND priority_score < 4.0 THEN 1 END) as medium_priority,
                    COUNT(CASE WHEN priority_score < 2.0 THEN 1 END) as low_priority,
                    AVG(priority_score) as avg_priority,
                    COUNT(CASE WHEN (? - last_scan_time) <= 300 THEN 1 END) as recently_scanned
                FROM wallet_priorities
            """, (current_time,))

            wallet_stats = cursor.fetchone()
            wallet_metrics = {
                'total_wallets': wallet_stats[0] or 0,
                'high_priority': wallet_stats[1] or 0,
                'medium_priority': wallet_stats[2] or 0,
                'low_priority': wallet_stats[3] or 0,
                'avg_priority': round(wallet_stats[4], 2) if wallet_stats[4] else 0,
                'recently_scanned_5min': wallet_stats[5] or 0
            }

            # === MÉTRIQUES DE PERFORMANCE ===
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_scans,
                    AVG(scan_duration) as avg_duration,
                    SUM(new_accounts) as total_discoveries,
                    AVG(efficiency_score) as avg_efficiency
                FROM scan_history 
                WHERE completed_at >= ?
            """, (current_time - 86400,))  # Dernières 24h

            perf_stats = cursor.fetchone()
            performance_metrics = {
                'scans_24h': perf_stats[0] or 0,
                'avg_scan_duration': round(perf_stats[1], 2) if perf_stats[1] else 0,
                'discoveries_24h': perf_stats[2] or 0,
                'avg_efficiency': round(perf_stats[3], 1) if perf_stats[3] else 0,
                'scans_per_hour': round((perf_stats[0] or 0) / 24, 1)
            }

            # === RÉSUMÉ FINAL ===
            dashboard_data = {
                'timestamp': current_time,
                'stats': {
                    'total_token_accounts': total_token_accounts,
                    'total_unique_tokens': total_unique_tokens,
                    'balance_changes_1h': balance_changes_1h,
                    'large_transactions_24h': large_transactions_24h,
                    'last_scan_time': last_scan_time,
                    'minutes_since_scan': round((current_time - last_scan_time) / 60, 1) if last_scan_time else 999
                },
                'wallet_metrics': wallet_metrics,
                'performance_metrics': performance_metrics,
                'top_tokens': top_tokens[:8],  # Top 8 pour affichage principal
                'new_gems': new_gems,
                'volume_alerts': volume_alerts,
                'active_tokens_list': top_tokens  # Liste complète pour modal
            }

            # Mise en cache
            cache_result(cache_key, dashboard_data, 60)  # Cache 1 minute
            
            return jsonify(create_success_response("Dashboard data retrieved", dashboard_data))

    except Exception as e:
        logger.error(f"Erreur dashboard data: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify(create_error_response("Failed to load dashboard data", [str(e)])), 500


@dashboard_bp.route('/wallet-overview')
def get_wallet_overview():
    """Vue d'ensemble de tous les wallets monitorés"""
    try:
        cache_key = "wallet_overview"
        cached_data = get_cached_result(cache_key)
        if cached_data:
            return jsonify(create_success_response("Wallet overview from cache", cached_data))

        with get_db_connection() as conn:
            cursor = conn.cursor()
            current_time = int(time.time())

            # Récupérer les informations de tous les wallets
            cursor.execute("""
                SELECT 
                    wp.wallet_address,
                    wp.priority_score,
                    wp.last_scan_time,
                    wp.total_scans,
                    wp.activity_score,
                    wp.consecutive_empty_scans,
                    (? - wp.last_scan_time) as seconds_since_scan,
                    
                    -- Stats des comptes de tokens
                    (SELECT COUNT(*) FROM token_accounts ta 
                     WHERE ta.wallet_address = wp.wallet_address AND ta.is_active = 1) as total_accounts,
                    (SELECT COUNT(*) FROM token_accounts ta 
                     WHERE ta.wallet_address = wp.wallet_address 
                     AND ta.scan_priority >= 3) as priority_accounts,
                    
                    -- Stats des transactions (24h)
                    (SELECT COUNT(*) FROM transactions t 
                     WHERE t.wallet_address = wp.wallet_address 
                     AND t.block_time >= ?) as transactions_24h,
                    (SELECT COUNT(*) FROM transactions t 
                     WHERE t.wallet_address = wp.wallet_address 
                     AND t.is_token_transaction = 1 
                     AND t.block_time >= ?) as token_transactions_24h
                     
                FROM wallet_priorities wp
                ORDER BY wp.priority_score DESC, wp.last_scan_time ASC
            """, (current_time, current_time - 86400, current_time - 86400))

            wallets_data = cursor.fetchall()
            wallets_overview = []

            for row in wallets_data:
                wallet_addr = row[0]
                priority_score = row[1]
                last_scan = row[2]
                total_scans = row[3]
                activity_score = row[4]
                empty_scans = row[5]
                since_scan = row[6]
                total_accounts = row[7] or 0
                priority_accounts = row[8] or 0
                tx_24h = row[9] or 0
                token_tx_24h = row[10] or 0

                # Calculer le statut du wallet
                if since_scan <= 60:
                    scan_status = "recent"
                elif since_scan <= 300:
                    scan_status = "normal"
                else:
                    scan_status = "overdue"

                # Calculer la catégorie de priorité
                if priority_score >= 4.0:
                    priority_category = "high"
                elif priority_score >= 2.0:
                    priority_category = "medium"
                else:
                    priority_category = "low"

                # Calculer le niveau d'activité
                if tx_24h > 10:
                    activity_level = "high"
                elif tx_24h > 2:
                    activity_level = "medium"
                else:
                    activity_level = "low"

                wallets_overview.append({
                    'wallet_address': wallet_addr,
                    'wallet_short': f"{wallet_addr[:8]}...{wallet_addr[-8:]}",
                    'priority_score': round(priority_score, 2),
                    'priority_category': priority_category,
                    'last_scan_time': last_scan,
                    'seconds_since_scan': since_scan,
                    'scan_status': scan_status,
                    'total_scans': total_scans,
                    'activity_score': round(activity_score, 1),
                    'consecutive_empty_scans': empty_scans,
                    'total_token_accounts': total_accounts,
                    'priority_accounts': priority_accounts,
                    'transactions_24h': tx_24h,
                    'token_transactions_24h': token_tx_24h,
                    'activity_level': activity_level
                })

            # Statistiques globales
            total_wallets = len(wallets_overview)
            high_priority_count = len([w for w in wallets_overview if w['priority_category'] == 'high'])
            overdue_count = len([w for w in wallets_overview if w['scan_status'] == 'overdue'])
            active_count = len([w for w in wallets_overview if w['activity_level'] != 'low'])

            overview_data = {
                'wallets': wallets_overview,
                'summary': {
                    'total_wallets': total_wallets,
                    'high_priority_wallets': high_priority_count,
                    'overdue_scans': overdue_count,
                    'active_wallets': active_count,
                    'avg_priority': round(sum(w['priority_score'] for w in wallets_overview) / max(total_wallets, 1), 2)
                }
            }

            cache_result(cache_key, overview_data, 45)  # Cache 45 secondes
            
            return jsonify(create_success_response("Wallet overview retrieved", overview_data))

    except Exception as e:
        logger.error(f"Erreur wallet overview: {e}")
        return jsonify(create_error_response("Failed to load wallet overview", [str(e)])), 500


@dashboard_bp.route('/recent-activity')
def get_recent_activity():
    """Activité récente - transactions et découvertes"""
    try:
        hours = request.args.get('hours', 24, type=int)
        limit = min(request.args.get('limit', 50, type=int), 200)  # Max 200
        
        cache_key = f"recent_activity_{hours}h_{limit}"
        cached_data = get_cached_result(cache_key)
        if cached_data:
            return jsonify(create_success_response("Recent activity from cache", cached_data))

        with get_db_connection() as conn:
            cursor = conn.cursor()
            start_time = int(time.time()) - (hours * 3600)

            # === TRANSACTIONS RÉCENTES ===
            cursor.execute("""
                SELECT 
                    signature, wallet_address, token_mint, token_symbol, token_name,
                    transaction_type, token_amount, amount, block_time, 
                    is_large_token_amount, price_per_token, detection_delay
                FROM transactions 
                WHERE is_token_transaction = 1 
                AND block_time >= ?
                ORDER BY block_time DESC 
                LIMIT ?
            """, (start_time, limit))

            transactions_data = cursor.fetchall()
            recent_transactions = []

            for row in transactions_data:
                signature = row[0]
                wallet = row[1]
                mint = row[2]
                symbol = row[3] or 'UNKNOWN'
                name = row[4] or 'Unknown Token'
                tx_type = row[5]
                token_amount = row[6]
                sol_amount = row[7]
                block_time = row[8]
                is_large = bool(row[9])
                price = row[10] or 0
                detection_delay = row[11] or 0

                recent_transactions.append({
                    'type': 'transaction',
                    'signature': signature,
                    'signature_short': f"{signature[:16]}..." if signature else "Unknown",
                    'wallet_address': wallet,
                    'wallet_short': f"{wallet[:6]}...{wallet[-6:]}",
                    'token_symbol': symbol,
                    'token_name': name,
                    'token_mint': mint,
                    'mint_short': f"{mint[:6]}...{mint[-6:]}" if mint else "Unknown",
                    'transaction_type': tx_type,
                    'token_amount': round(token_amount, 6),
                    'sol_amount': round(sol_amount, 6),
                    'price_per_token': round(price, 8) if price else None,
                    'usd_value': round(token_amount * price, 2) if price and token_amount else None,
                    'is_large_amount': is_large,
                    'block_time': block_time,
                    'detection_delay': round(detection_delay, 1),
                    'hours_ago': round((int(time.time()) - block_time) / 3600, 1) if block_time else 999
                })

            # === DÉCOUVERTES RÉCENTES DE TOKENS ===
            cursor.execute("""
                SELECT 
                    ta.token_mint, ta.wallet_address, ta.first_seen, ta.balance,
                    t.token_symbol
                FROM token_accounts ta
                LEFT JOIN transactions t ON ta.token_mint = t.token_mint 
                    AND t.wallet_address = ta.wallet_address
                WHERE ta.first_seen >= ?
                GROUP BY ta.token_mint, ta.wallet_address, ta.first_seen, ta.balance
                ORDER BY ta.first_seen DESC
                LIMIT ?
            """, (start_time, limit // 2))  # Moins de découvertes que de transactions

            discoveries_data = cursor.fetchall()
            recent_discoveries = []

            for row in discoveries_data:
                mint = row[0]
                wallet = row[1]
                discovered_at = row[2]
                balance = row[3]
                symbol = row[4] or f"TOKEN_{mint[:6]}"

                recent_discoveries.append({
                    'type': 'discovery',
                    'token_mint': mint,
                    'mint_short': f"{mint[:6]}...{mint[-6:]}",
                    'wallet_address': wallet,
                    'wallet_short': f"{wallet[:6]}...{wallet[-6:]}",
                    'token_symbol': symbol,
                    'initial_balance': round(balance, 6),
                    'discovered_at': discovered_at,
                    'hours_ago': round((int(time.time()) - discovered_at) / 3600, 1)
                })

            # === COMBINER ET TRIER PAR TEMPS ===
            all_activity = recent_transactions + recent_discoveries
            
            # Trier par timestamp (block_time pour transactions, discovered_at pour découvertes)
            all_activity.sort(key=lambda x: x.get('block_time') or x.get('discovered_at', 0), reverse=True)
            
            # Limiter au nombre demandé
            all_activity = all_activity[:limit]

            activity_data = {
                'period_hours': hours,
                'total_items': len(all_activity),
                'transactions_count': len(recent_transactions),
                'discoveries_count': len(recent_discoveries),
                'activity': all_activity
            }

            cache_result(cache_key, activity_data, 30)  # Cache 30 secondes
            
            return jsonify(create_success_response("Recent activity retrieved", activity_data))

    except Exception as e:
        logger.error(f"Erreur recent activity: {e}")
        return jsonify(create_error_response("Failed to load recent activity", [str(e)])), 500


@dashboard_bp.route('/performance-metrics')
def get_performance_metrics():
    """Métriques de performance du système"""
    try:
        hours = request.args.get('hours', 24, type=int)
        
        cache_key = f"performance_metrics_{hours}h"
        cached_data = get_cached_result(cache_key)
        if cached_data:
            return jsonify(create_success_response("Performance metrics from cache", cached_data))

        with get_db_connection() as conn:
            cursor = conn.cursor()
            start_time = int(time.time()) - (hours * 3600)

            # === MÉTRIQUES DE SCAN ===
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_scans,
                    AVG(scan_duration) as avg_duration,
                    MIN(scan_duration) as min_duration,
                    MAX(scan_duration) as max_duration,
                    SUM(new_accounts) as total_discoveries,
                    SUM(total_accounts) as total_accounts_scanned,
                    AVG(efficiency_score) as avg_efficiency
                FROM scan_history 
                WHERE completed_at >= ?
            """, (start_time,))

            scan_metrics = cursor.fetchone()

            # === MÉTRIQUES PAR WALLET ===
            cursor.execute("""
                SELECT 
                    sh.wallet_address,
                    COUNT(*) as scan_count,
                    AVG(sh.scan_duration) as avg_duration,
                    SUM(sh.new_accounts) as discoveries,
                    AVG(sh.efficiency_score) as avg_efficiency
                FROM scan_history sh
                WHERE sh.completed_at >= ?
                GROUP BY sh.wallet_address
                ORDER BY avg_efficiency DESC
            """, (start_time,))

            wallet_metrics = []
            for row in cursor.fetchall():
                wallet_metrics.append({
                    'wallet_address': row[0],
                    'wallet_short': f"{row[0][:6]}...{row[0][-6:]}",
                    'scan_count': row[1],
                    'avg_duration': round(row[2], 2) if row[2] else 0,
                    'discoveries': row[3] or 0,
                    'avg_efficiency': round(row[4], 1) if row[4] else 0
                })

            # === ÉVOLUTION TEMPORELLE (par heure) ===
            cursor.execute("""
                SELECT 
                    strftime('%H', datetime(completed_at, 'unixepoch')) as hour,
                    COUNT(*) as scans,
                    AVG(scan_duration) as avg_duration,
                    SUM(new_accounts) as discoveries
                FROM scan_history
                WHERE completed_at >= ?
                GROUP BY hour
                ORDER BY hour
            """, (start_time,))

            hourly_metrics = []
            for row in cursor.fetchall():
                hourly_metrics.append({
                    'hour': int(row[0]),
                    'scans': row[1],
                    'avg_duration': round(row[2], 2) if row[2] else 0,
                    'discoveries': row[3] or 0,
                    'scans_per_hour': row[1] / max(hours / 24, 1)  # Normaliser par durée
                })

            # === MÉTRIQUES RPC (si disponibles) ===
            cursor.execute("""
                SELECT 
                    AVG(rpc_requests_count) as avg_rpc_requests,
                    SUM(rpc_requests_count) as total_rpc_requests
                FROM scan_history 
                WHERE completed_at >= ?
                AND rpc_requests_count IS NOT NULL
            """, (start_time,))

            rpc_data = cursor.fetchone()

            performance_data = {
                'period_hours': hours,
                'system_metrics': {
                    'total_scans': scan_metrics[0] or 0,
                    'avg_scan_duration': round(scan_metrics[1], 2) if scan_metrics[1] else 0,
                    'min_scan_duration': round(scan_metrics[2], 2) if scan_metrics[2] else 0,
                    'max_scan_duration': round(scan_metrics[3], 2) if scan_metrics[3] else 0,
                    'total_discoveries': scan_metrics[4] or 0,
                    'total_accounts_scanned': scan_metrics[5] or 0,
                    'avg_efficiency': round(scan_metrics[6], 1) if scan_metrics[6] else 0,
                    'scans_per_hour': round((scan_metrics[0] or 0) / hours, 1),
                    'discoveries_per_scan': round((scan_metrics[4] or 0) / max(scan_metrics[0] or 1, 1), 2)
                },
                'rpc_metrics': {
                    'avg_requests_per_scan': round(rpc_data[0], 1) if rpc_data[0] else 0,
                    'total_rpc_requests': rpc_data[1] or 0,
                    'rpc_efficiency': round((scan_metrics[4] or 0) / max(rpc_data[1] or 1, 1), 4)
                },
                'wallet_performance': wallet_metrics[:10],  # Top 10
                'hourly_trends': hourly_metrics
            }

            cache_result(cache_key, performance_data, 120)  # Cache 2 minutes
            
            return jsonify(create_success_response("Performance metrics retrieved", performance_data))

    except Exception as e:
        logger.error(f"Erreur performance metrics: {e}")
        return jsonify(create_error_response("Failed to load performance metrics", [str(e)])), 500


# ============= ROUTES DE RECHERCHE ET FILTRAGE =============

@dashboard_bp.route('/search')
def search_data():
    """Recherche globale dans les données"""
    try:
        query = request.args.get('q', '').strip()
        data_type = request.args.get('type', 'all')  # all, wallets, tokens, transactions
        limit = min(request.args.get('limit', 20, type=int), 100)
        
        if not query or len(query) < 3:
            return jsonify(create_error_response("Query must be at least 3 characters")), 400

        results = {'wallets': [], 'tokens': [], 'transactions': []}

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # === RECHERCHE WALLETS ===
            if data_type in ['all', 'wallets']:
                cursor.execute("""
                    SELECT DISTINCT wallet_address, priority_score, last_scan_time, total_scans
                    FROM wallet_priorities
                    WHERE wallet_address LIKE ?
                    ORDER BY priority_score DESC
                    LIMIT ?
                """, (f"%{query}%", limit))
                
                for row in cursor.fetchall():
                    results['wallets'].append({
                        'wallet_address': row[0],
                        'wallet_short': f"{row[0][:8]}...{row[0][-8:]}",
                        'priority_score': round(row[1], 2),
                        'total_scans': row[3],
                        'match_type': 'wallet_address'
                    })

            # === RECHERCHE TOKENS ===
            if data_type in ['all', 'tokens']:
                # Recherche par symbol ou mint
                cursor.execute("""
                    SELECT DISTINCT token_mint, token_symbol, token_name, wallet_address,
                           COUNT(*) as tx_count, MAX(block_time) as last_activity
                    FROM transactions
                    WHERE is_token_transaction = 1
                    AND (token_symbol LIKE ? OR token_name LIKE ? OR token_mint LIKE ?)
                    GROUP BY token_mint, wallet_address
                    ORDER BY tx_count DESC, last_activity DESC
                    LIMIT ?
                """, (f"%{query}%", f"%{query}%", f"%{query}%", limit))
                
                for row in cursor.fetchall():
                    mint = row[0]
                    symbol = row[1] or 'UNKNOWN'
                    name = row[2] or 'Unknown Token'
                    wallet = row[3]
                    tx_count = row[4]
                    last_activity = row[5]
                    
                    # Déterminer le type de match
                    match_type = 'symbol' if query.upper() in symbol.upper() else \
                               'name' if query.lower() in name.lower() else 'mint'
                    
                    results['tokens'].append({
                        'token_mint': mint,
                        'mint_short': f"{mint[:6]}...{mint[-6:]}",
                        'token_symbol': symbol,
                        'token_name': name,
                        'wallet_address': wallet,
                        'wallet_short': f"{wallet[:6]}...{wallet[-6:]}",
                        'transaction_count': tx_count,
                        'last_activity': last_activity,
                        'match_type': match_type
                    })

            # === RECHERCHE TRANSACTIONS ===
            if data_type in ['all', 'transactions']:
                cursor.execute("""
                    SELECT signature, wallet_address, token_symbol, token_mint,
                           transaction_type, token_amount, block_time, is_large_token_amount
                    FROM transactions
                    WHERE signature LIKE ? OR token_symbol LIKE ?
                    ORDER BY block_time DESC
                    LIMIT ?
                """, (f"%{query}%", f"%{query}%", limit))
                
                for row in cursor.fetchall():
                    signature = row[0]
                    wallet = row[1]
                    symbol = row[2] or 'UNKNOWN'
                    mint = row[3]
                    tx_type = row[4]
                    amount = row[5]
                    block_time = row[6]
                    is_large = bool(row[7])
                    
                    match_type = 'signature' if query in signature else 'token'
                    
                    results['transactions'].append({
                        'signature': signature,
                        'signature_short': f"{signature[:16]}...",
                        'wallet_address': wallet,
                        'wallet_short': f"{wallet[:6]}...{wallet[-6:]}",
                        'token_symbol': symbol,
                        'token_mint': mint,
                        'mint_short': f"{mint[:6]}...{mint[-6:]}",
                        'transaction_type': tx_type,
                        'token_amount': round(amount, 6),
                        'block_time': block_time,
                        'is_large_amount': is_large,
                        'match_type': match_type
                    })

        # Statistiques de recherche
        total_results = len(results['wallets']) + len(results['tokens']) + len(results['transactions'])
        
        search_data = {
            'query': query,
            'data_type': data_type,
            'total_results': total_results,
            'results': results
        }
        
        return jsonify(create_success_response("Search completed", search_data))

    except Exception as e:
        logger.error(f"Erreur search: {e}")
        return jsonify(create_error_response("Search failed", [str(e)])), 500


@dashboard_bp.route('/wallet/<wallet_address>')
def get_wallet_detail(wallet_address):
    """Détails complets d'un wallet spécifique"""
    try:
        # Validation de l'adresse
        if not wallet_address or len(wallet_address) != 44:
            return jsonify(create_error_response("Invalid wallet address format")), 400

        cache_key = f"wallet_detail_{wallet_address}"
        cached_data = get_cached_result(cache_key)
        if cached_data:
            return jsonify(create_success_response("Wallet details from cache", cached_data))

        with get_db_connection() as conn:
            cursor = conn.cursor()
            current_time = int(time.time())

            # === INFORMATIONS DE BASE ===
            cursor.execute("""
                SELECT priority_score, last_scan_time, total_scans, activity_score,
                       consecutive_empty_scans, avg_scan_duration, last_activity_detected
                FROM wallet_priorities
                WHERE wallet_address = ?
            """, (wallet_address,))

            wallet_info = cursor.fetchone()
            if not wallet_info:
                return jsonify(create_error_response("Wallet not found in monitoring system")), 404

            # === STATISTIQUES DES COMPTES DE TOKENS ===
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_accounts,
                    COUNT(CASE WHEN balance > 0 THEN 1 END) as active_accounts,
                    COUNT(CASE WHEN scan_priority >= 3 THEN 1 END) as priority_accounts,
                    AVG(scan_priority) as avg_priority
                FROM token_accounts
                WHERE wallet_address = ? AND is_active = 1
            """, (wallet_address,))

            account_stats = cursor.fetchone()

            # === STATISTIQUES DES TRANSACTIONS ===
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_transactions,
                    COUNT(CASE WHEN is_token_transaction = 1 THEN 1 END) as token_transactions,
                    COUNT(CASE WHEN is_large_token_amount = 1 THEN 1 END) as large_transactions,
                    COUNT(CASE WHEN transaction_type = 'buy' THEN 1 END) as buy_count,
                    COUNT(CASE WHEN transaction_type = 'sell' THEN 1 END) as sell_count,
                    COUNT(CASE WHEN block_time >= ? THEN 1 END) as transactions_24h,
                    MAX(block_time) as last_transaction_time,
                    SUM(ABS(amount)) as total_volume_sol
                FROM transactions
                WHERE wallet_address = ?
            """, (current_time - 86400, wallet_address))

            transaction_stats = cursor.fetchone()

            # === TOP TOKENS DU WALLET ===
            cursor.execute("""
                SELECT 
                    ta.token_mint, ta.balance, ta.decimals, ta.scan_priority,
                    ta.last_activity_time, ta.total_transactions,
                    t.token_symbol, t.token_name,
                    -- Stats des transactions pour ce token
                    (SELECT COUNT(*) FROM transactions tx 
                     WHERE tx.wallet_address = ta.wallet_address 
                     AND tx.token_mint = ta.token_mint) as tx_count,
                    (SELECT MAX(block_time) FROM transactions tx 
                     WHERE tx.wallet_address = ta.wallet_address 
                     AND tx.token_mint = ta.token_mint) as last_tx_time
                FROM token_accounts ta
                LEFT JOIN (
                    SELECT DISTINCT token_mint, 
                           FIRST_VALUE(token_symbol) OVER (PARTITION BY token_mint ORDER BY created_at DESC) as token_symbol,
                           FIRST_VALUE(token_name) OVER (PARTITION BY token_mint ORDER BY created_at DESC) as token_name
                    FROM transactions 
                    WHERE wallet_address = ? AND token_symbol IS NOT NULL
                ) t ON ta.token_mint = t.token_mint
                WHERE ta.wallet_address = ? AND ta.is_active = 1
                ORDER BY ta.balance DESC, ta.scan_priority DESC
                LIMIT 20
            """, (wallet_address, wallet_address))

            top_tokens = []
            for row in cursor.fetchall():
                mint = row[0]
                balance = row[1]
                decimals = row[2]
                priority = row[3]
                last_activity = row[4]
                total_tx = row[5]
                symbol = row[6] or f"TOKEN_{mint[:6]}"
                name = row[7] or f"Token {mint[:6]}"
                tx_count = row[8] or 0
                last_tx_time = row[9]

                display_balance = balance / (10 ** decimals) if balance > 1 else balance

                top_tokens.append({
                    'token_mint': mint,
                    'mint_short': f"{mint[:6]}...{mint[-6:]}",
                    'token_symbol': symbol,
                    'token_name': name,
                    'balance': balance,
                    'display_balance': round(display_balance, 6),
                    'decimals': decimals,
                    'scan_priority': priority,
                    'has_balance': balance > 0,
                    'transaction_count': tx_count,
                    'last_activity_time': last_activity,
                    'last_transaction_time': last_tx_time,
                    'days_since_activity': round((current_time - (last_activity or 0)) / 86400, 1) if last_activity else None
                })

            # === ACTIVITÉ RÉCENTE ===
            cursor.execute("""
                SELECT signature, token_symbol, token_mint, transaction_type,
                       token_amount, amount, block_time, is_large_token_amount
                FROM transactions
                WHERE wallet_address = ? AND is_token_transaction = 1
                ORDER BY block_time DESC
                LIMIT 10
            """, (wallet_address,))

            recent_activity = []
            for row in cursor.fetchall():
                recent_activity.append({
                    'signature': row[0],
                    'signature_short': f"{row[0][:16]}...",
                    'token_symbol': row[1] or 'UNKNOWN',
                    'token_mint': row[2],
                    'transaction_type': row[3],
                    'token_amount': round(row[4], 6),
                    'sol_amount': round(row[5], 6),
                    'block_time': row[6],
                    'is_large_amount': bool(row[7]),
                    'hours_ago': round((current_time - row[6]) / 3600, 1) if row[6] else 999
                })

            # === ASSEMBLAGE FINAL ===
            wallet_detail = {
                'wallet_address': wallet_address,
                'wallet_short': f"{wallet_address[:8]}...{wallet_address[-8:]}",
                'priority_info': {
                    'priority_score': round(wallet_info[0], 2),
                    'priority_category': 'high' if wallet_info[0] >= 4.0 else 'medium' if wallet_info[0] >= 2.0 else 'low',
                    'last_scan_time': wallet_info[1],
                    'minutes_since_scan': round((current_time - wallet_info[1]) / 60, 1) if wallet_info[1] else 999,
                    'total_scans': wallet_info[2],
                    'activity_score': round(wallet_info[3], 1),
                    'consecutive_empty_scans': wallet_info[4],
                    'avg_scan_duration': round(wallet_info[5], 1) if wallet_info[5] else 0
                },
                'account_stats': {
                    'total_accounts': account_stats[0] or 0,
                    'active_accounts': account_stats[1] or 0,
                    'priority_accounts': account_stats[2] or 0,
                    'avg_account_priority': round(account_stats[3], 1) if account_stats[3] else 0
                },
                'transaction_stats': {
                    'total_transactions': transaction_stats[0] or 0,
                    'token_transactions': transaction_stats[1] or 0,
                    'large_transactions': transaction_stats[2] or 0,
                    'buy_transactions': transaction_stats[3] or 0,
                    'sell_transactions': transaction_stats[4] or 0,
                    'transactions_24h': transaction_stats[5] or 0,
                    'last_transaction_time': transaction_stats[6],
                    'total_volume_sol': round(transaction_stats[7], 4) if transaction_stats[7] else 0,
                    'buy_sell_ratio': round(transaction_stats[3] / max(transaction_stats[4], 1), 2) if transaction_stats[4] else 0
                },
                'top_tokens': top_tokens,
                'recent_activity': recent_activity
            }

            cache_result(cache_key, wallet_detail, 60)  # Cache 1 minute
            
            return jsonify(create_success_response("Wallet details retrieved", wallet_detail))

    except Exception as e:
        logger.error(f"Erreur wallet detail: {e}")
        return jsonify(create_error_response("Failed to load wallet details", [str(e)])), 500


@dashboard_bp.route('/token/<token_mint>')
def get_token_detail(token_mint):
    """Détails complets d'un token spécifique"""
    try:
        # Validation du mint
        if not token_mint or len(token_mint) != 44:
            return jsonify(create_error_response("Invalid token mint format")), 400

        cache_key = f"token_detail_{token_mint}"
        cached_data = get_cached_result(cache_key)
        if cached_data:
            return jsonify(create_success_response("Token details from cache", cached_data))

        with get_db_connection() as conn:
            cursor = conn.cursor()
            current_time = int(time.time())

            # === INFORMATIONS DE BASE DU TOKEN ===
            cursor.execute("""
                SELECT DISTINCT token_symbol, token_name,
                       FIRST_VALUE(wallet_address) OVER (ORDER BY created_at DESC) as sample_wallet
                FROM transactions
                WHERE token_mint = ? AND token_symbol IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 1
            """, (token_mint,))

            token_info = cursor.fetchone()
            if not token_info:
                # Token pas encore dans les transactions
                token_symbol = f"TOKEN_{token_mint[:6]}"
                token_name = f"Token {token_mint[:6]}"
                sample_wallet = None
            else:
                token_symbol = token_info[0] or f"TOKEN_{token_mint[:6]}"
                token_name = token_info[1] or f"Token {token_mint[:6]}"
                sample_wallet = token_info[2]

            # === STATISTIQUES GLOBALES ===
            cursor.execute("""
                SELECT 
                    COUNT(DISTINCT wallet_address) as holder_count,
                    COUNT(*) as total_transactions,
                    SUM(CASE WHEN transaction_type = 'buy' THEN token_amount ELSE 0 END) as total_bought,
                    SUM(CASE WHEN transaction_type = 'sell' THEN token_amount ELSE 0 END) as total_sold,
                    AVG(CASE WHEN price_per_token > 0 THEN price_per_token ELSE NULL END) as avg_price,
                    MIN(block_time) as first_seen,
                    MAX(block_time) as last_activity,
                    COUNT(CASE WHEN block_time >= ? THEN 1 END) as transactions_24h
                FROM transactions
                WHERE token_mint = ?
            """, (current_time - 86400, token_mint))

            global_stats = cursor.fetchone()

            # === RÉPARTITION PAR WALLET ===
            cursor.execute("""
                SELECT 
                    wallet_address,
                    COUNT(*) as tx_count,
                    SUM(CASE WHEN transaction_type = 'buy' THEN token_amount ELSE 0 END) as bought,
                    SUM(CASE WHEN transaction_type = 'sell' THEN token_amount ELSE 0 END) as sold,
                    MAX(block_time) as last_tx_time,
                    -- Balance actuelle depuis token_accounts
                    (SELECT balance FROM token_accounts ta 
                     WHERE ta.wallet_address = t.wallet_address 
                     AND ta.token_mint = t.token_mint 
                     AND ta.is_active = 1) as current_balance
                FROM transactions t
                WHERE token_mint = ?
                GROUP BY wallet_address
                ORDER BY tx_count DESC, last_tx_time DESC
                LIMIT 15
            """, (token_mint,))

            wallet_distribution = []
            for row in cursor.fetchall():
                wallet = row[0]
                tx_count = row[1]
                bought = row[2] or 0
                sold = row[3] or 0
                last_tx = row[4]
                balance = row[5] or 0

                net_position = bought - sold

                wallet_distribution.append({
                    'wallet_address': wallet,
                    'wallet_short': f"{wallet[:6]}...{wallet[-6:]}",
                    'transaction_count': tx_count,
                    'total_bought': round(bought, 6),
                    'total_sold': round(sold, 6),
                    'net_position': round(net_position, 6),
                    'current_balance': round(balance, 6),
                    'last_transaction_time': last_tx,
                    'hours_since_tx': round((current_time - last_tx) / 3600, 1) if last_tx else 999
                })

            # === ACTIVITÉ RÉCENTE ===
            cursor.execute("""
                SELECT wallet_address, transaction_type, token_amount, amount,
                       block_time, signature, price_per_token
                FROM transactions
                WHERE token_mint = ?
                ORDER BY block_time DESC
                LIMIT 15
            """, (token_mint,))

            recent_transactions = []
            for row in cursor.fetchall():
                wallet = row[0]
                tx_type = row[1]
                token_amount = row[2]
                sol_amount = row[3]
                block_time = row[4]
                signature = row[5]
                price = row[6] or 0

                recent_transactions.append({
                    'wallet_address': wallet,
                    'wallet_short': f"{wallet[:6]}...{wallet[-6:]}",
                    'transaction_type': tx_type,
                    'token_amount': round(token_amount, 6),
                    'sol_amount': round(sol_amount, 6),
                    'price_per_token': round(price, 8) if price else None,
                    'block_time': block_time,
                    'signature': signature,
                    'signature_short': f"{signature[:16]}...",
                    'hours_ago': round((current_time - block_time) / 3600, 1) if block_time else 999
                })

            # === ASSEMBLAGE FINAL ===
            first_seen = global_stats[5]
            last_activity = global_stats[6]

            token_detail = {
                'token_mint': token_mint,
                'mint_short': f"{token_mint[:6]}...{token_mint[-6:]}",
                'token_symbol': token_symbol,
                'token_name': token_name,
                'global_stats': {
                    'holder_count': global_stats[0] or 0,
                    'total_transactions': global_stats[1] or 0,
                    'total_bought': round(global_stats[2] or 0, 6),
                    'total_sold': round(global_stats[3] or 0, 6),
                    'net_flow': round((global_stats[2] or 0) - (global_stats[3] or 0), 6),
                    'avg_price': round(global_stats[4], 8) if global_stats[4] else None,
                    'first_seen': first_seen,
                    'last_activity': last_activity,
                    'transactions_24h': global_stats[7] or 0,
                    'days_since_discovery': round((current_time - first_seen) / 86400, 1) if first_seen else None,
                    'hours_since_activity': round((current_time - last_activity) / 3600, 1) if last_activity else None
                },
                'wallet_distribution': wallet_distribution,
                'recent_transactions': recent_transactions
            }

            cache_result(cache_key, token_detail, 90)  # Cache 90 secondes
            
            return jsonify(create_success_response("Token details retrieved", token_detail))

    except Exception as e:
        logger.error(f"Erreur token detail: {e}")
        return jsonify(create_error_response("Failed to load token details", [str(e)])), 500


# ============= ROUTES UTILITAIRES =============

@dashboard_bp.route('/health')
def dashboard_health():
    """Health check du dashboard"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            db_status = "ok"
    except Exception as e:
        logger.error(f"Dashboard health check failed: {e}")
        db_status = "error"

    health_data = {
        'status': 'healthy' if db_status == 'ok' else 'degraded',
        'database': db_status,
        'cache_size': len(_dashboard_cache),
        'timestamp': int(time.time())
    }

    return jsonify(create_success_response("Dashboard health check", health_data))


@dashboard_bp.route('/cache/clear', methods=['POST'])
def clear_cache():
    """Vide le cache du dashboard"""
    try:
        cleared_items = len(_dashboard_cache)
        _dashboard_cache.clear()
        _cache_expiry.clear()
        
        return jsonify(create_success_response(f"Cache cleared: {cleared_items} items removed"))
    except Exception as e:
        logger.error(f"Erreur clear cache: {e}")
        return jsonify(create_error_response("Failed to clear cache", [str(e)])), 500


@dashboard_bp.route('/stats')
def dashboard_stats():
    """Statistiques d'usage du dashboard"""
    try:
        clear_expired_cache()  # Nettoyer avant de compter
        
        stats = {
            'cache_entries': len(_dashboard_cache),
            'cache_hit_ratio': 'N/A',  # À implémenter avec compteurs
            'active_connections': 'N/A',  # À implémenter
            'avg_response_time': 'N/A'  # À implémenter
        }
        
        return jsonify(create_success_response("Dashboard statistics", stats))
    except Exception as e:
        logger.error(f"Erreur dashboard stats: {e}")
        return jsonify(create_error_response("Failed to get dashboard stats", [str(e)])), 500


# ============= HANDLERS D'ERREURS =============

@dashboard_bp.errorhandler(404)
def dashboard_not_found(error):
    """Handler pour erreur 404"""
    return jsonify(create_error_response("Dashboard endpoint not found")), 404


@dashboard_bp.errorhandler(500)
def dashboard_server_error(error):
    """Handler pour erreur 500"""
    logger.error(f"Dashboard server error: {error}")
    return jsonify(create_error_response("Internal server error in dashboard")), 500


# ============= INITIALISATION =============

def init_dashboard_routes(app):
    """Initialise les routes dashboard sur l'application"""
    app.register_blueprint(dashboard_bp)
    logger.info("✅ Routes dashboard enregistrées")


# Nettoyage automatique du cache (appelé périodiquement)
def cleanup_dashboard_cache():
    """Fonction de nettoyage du cache (à appeler périodiquement)"""
    try:
        clear_expired_cache()
        logger.debug(f"Cache nettoyé: {len(_dashboard_cache)} entrées restantes")
    except Exception as e:
        logger.error(f"Erreur nettoyage cache dashboard: {e}")


# Export des fonctions principales
__all__ = [
    'dashboard_bp',
    'init_dashboard_routes',
    'cleanup_dashboard_cache'
]