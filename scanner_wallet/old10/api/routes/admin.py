
#!/usr/bin/env python3
"""
Routes d'administration pour le Solana Wallet Monitor
Gestion des paramètres système, configuration et maintenance
"""

from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import logging
import time
import threading

# Imports depuis la nouvelle structure
from core.config import get_config
from core.logger import get_logger
from core.database import DatabaseManager
from core.exceptions import (
    ConfigurationError, DatabaseError, MonitoringError,
    SolanaWalletMonitorError
)
from rpc.batch_manager import BatchManager  
from wallet.priority_manager import WalletPriorityManager
from utils.helpers import (
    get_current_timestamp, calculate_time_since, safe_divide,
    generate_short_hash
)
from utils.validators import quick_validate_address as validate_wallet_address
from utils.formatters import (
    format_wallet_address, format_duration, format_timestamp,
    format_api_response, format_memory_usage
)
from utils.constants import (
    VALIDATION_PATTERNS, SECURITY_LIMITS, API_LIMITS,
    SYSTEM_INFO
)

# Configuration du blueprint
admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')
logger = get_logger(__name__)

# Variables globales pour le monitoring système
_system_stats = {
    'start_time': time.time(),
    'requests_count': 0,
    'errors_count': 0,
    'last_health_check': 0
}
_stats_lock = threading.Lock()


# =============================================================================
# MIDDLEWARE ET DÉCORATEURS
# =============================================================================

def admin_required(f):
    """Décorateur pour les routes nécessitant des privilèges admin"""
    def decorated_function(*args, **kwargs):
        # TODO: Implémenter la vérification d'authentification admin
        # Pour l'instant, toutes les routes admin sont ouvertes
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function


def update_request_stats():
    """Met à jour les statistiques de requêtes"""
    with _stats_lock:
        _system_stats['requests_count'] += 1


def update_error_stats():
    """Met à jour les statistiques d'erreurs"""
    with _stats_lock:
        _system_stats['errors_count'] += 1


# =============================================================================
# ROUTES DE MONITORING SYSTÈME
# =============================================================================

@admin_bp.route('/health', methods=['GET'])
def health_check():
    """Check de santé complet du système"""
    try:
        update_request_stats()
        current_time = get_current_timestamp()
        
        # Récupération de la configuration
        config = get_config()
        
        health_status = {
            'status': 'healthy',
            'timestamp': current_time,
            'version': SYSTEM_INFO['version'],
            'uptime_seconds': current_time - int(_system_stats['start_time']),
            'checks': {}
        }
        
        # Check 1: Configuration
        try:
            health_status['checks']['configuration'] = {
                'status': 'ok',
                'wallets_configured': len(config.wallet.addresses),
                'environment': config.environment.value,
                'batching_enabled': config.batching.enabled
            }
        except Exception as e:
            health_status['checks']['configuration'] = {
                'status': 'error',
                'error': str(e)
            }
            health_status['status'] = 'degraded'
        
        # Check 2: Base de données
        try:
            db_manager = DatabaseManager()
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM transactions LIMIT 1")
                result = cursor.fetchone()
                
            health_status['checks']['database'] = {
                'status': 'ok',
                'connection': 'active',
                'test_query': 'success'
            }
        except DatabaseError as e:
            health_status['checks']['database'] = {
                'status': 'error',
                'error': str(e)
            }
            health_status['status'] = 'critical'
        except Exception as e:
            health_status['checks']['database'] = {
                'status': 'error',
                'error': f"Database connection failed: {e}"
            }
            health_status['status'] = 'critical'
        
        # Check 3: RPC Endpoints
        try:
            rpc_endpoints = config.rpc.get_all_endpoints()
            health_status['checks']['rpc'] = {
                'status': 'ok',
                'endpoints_configured': len(rpc_endpoints),
                'primary_endpoint': rpc_endpoints[0] if rpc_endpoints else None
            }
        except Exception as e:
            health_status['checks']['rpc'] = {
                'status': 'warning',
                'error': str(e)
            }
            if health_status['status'] == 'healthy':
                health_status['status'] = 'degraded'
        
        # Check 4: Système de priorités
        try:
            priority_manager = PriorityManager()
            wallet_count = len(config.wallet.addresses)
            
            health_status['checks']['priorities'] = {
                'status': 'ok',
                'wallets_managed': wallet_count,
                'system_initialized': True
            }
        except Exception as e:
            health_status['checks']['priorities'] = {
                'status': 'warning',
                'error': str(e)
            }
        
        # Statistiques système
        with _stats_lock:
            health_status['system_stats'] = {
                'requests_handled': _system_stats['requests_count'],
                'errors_count': _system_stats['errors_count'],
                'error_rate': safe_divide(_system_stats['errors_count'], 
                                        _system_stats['requests_count'], 0) * 100
            }
        
        # Mise à jour du timestamp du dernier check
        with _stats_lock:
            _system_stats['last_health_check'] = current_time
        
        logger.info(f"Health check completed: {health_status['status']}")
        
        return jsonify(format_api_response(
            health_status,
            success=health_status['status'] in ['healthy', 'degraded'],
            message=f"System status: {health_status['status']}"
        ))
        
    except Exception as e:
        update_error_stats()
        logger.error(f"Health check failed: {e}")
        
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Health check failed: {e}"
        )), 500


@admin_bp.route('/system-info', methods=['GET'])
@admin_required
def get_system_info():
    """Informations détaillées du système"""
    try:
        update_request_stats()
        config = get_config()
        current_time = get_current_timestamp()
        
        system_info = {
            'application': {
                'name': "Solana Wallet Monitor",
                'version': SYSTEM_INFO['version'],
                'codename': SYSTEM_INFO['codename'],
                'uptime': format_duration(current_time - int(_system_stats['start_time'])),
                'environment': config.environment.value
            },
            'configuration': {
                'wallets_count': len(config.wallet.addresses),
                'selection_mode': config.wallet.selection_mode.value,
                'batching_enabled': config.batching.enabled,
                'update_interval': config.monitoring.update_interval,
                'log_level': config.logging.level.value
            },
            'performance': {
                'requests_per_hour': _system_stats['requests_count'] / max(
                    (current_time - _system_stats['start_time']) / 3600, 1
                ),
                'error_rate_percent': safe_divide(
                    _system_stats['errors_count'], 
                    _system_stats['requests_count'], 0
                ) * 100,
                'last_health_check': format_timestamp(
                    _system_stats['last_health_check'], 'relative'
                ) if _system_stats['last_health_check'] else 'Never'
            }
        }
        
        # Ajouter les informations de base de données
        try:
            db_manager = DatabaseManager()
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Statistiques des tables principales
                tables_stats = {}
                for table in ['transactions', 'token_accounts', 'wallet_priorities', 'scan_history']:
                    try:
                        cursor.execute(f"SELECT COUNT(*) FROM {table}")
                        count = cursor.fetchone()[0]
                        tables_stats[table] = count
                    except Exception:
                        tables_stats[table] = 'error'
                
                system_info['database'] = {
                    'status': 'connected',
                    'tables': tables_stats
                }
        except Exception as e:
            system_info['database'] = {
                'status': 'error',
                'error': str(e)
            }
        
        return jsonify(format_api_response(
            system_info,
            message="System information retrieved successfully"
        ))
        
    except Exception as e:
        update_error_stats()
        logger.error(f"Failed to get system info: {e}")
        
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Failed to retrieve system information: {e}"
        )), 500


@admin_bp.route('/metrics', methods=['GET'])
@admin_required
def get_system_metrics():
    """Métriques détaillées du système"""
    try:
        update_request_stats()
        hours = request.args.get('hours', 24, type=int)
        hours = min(max(hours, 1), 168)  # Entre 1h et 7 jours
        
        db_manager = DatabaseManager()
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Période de calcul
            start_time = get_current_timestamp() - (hours * 3600)
            
            # Métriques des scans
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_scans,
                    AVG(scan_duration) as avg_duration,
                    SUM(new_accounts) as total_discoveries,
                    SUM(CASE WHEN activity_detected = 1 THEN 1 ELSE 0 END) as active_scans
                FROM scan_history 
                WHERE completed_at >= ?
            ''', (start_time,))
            
            scan_metrics = cursor.fetchone()
            
            # Métriques des transactions
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_transactions,
                    COUNT(CASE WHEN is_token_transaction = 1 THEN 1 END) as token_transactions,
                    COUNT(CASE WHEN is_large_token_amount = 1 THEN 1 END) as large_transactions,
                    COUNT(DISTINCT wallet_address) as active_wallets
                FROM transactions 
                WHERE block_time >= ?
            ''', (start_time,))
            
            tx_metrics = cursor.fetchone()
            
            # Métriques de performance par wallet
            cursor.execute('''
                SELECT 
                    wallet_address,
                    COUNT(*) as scan_count,
                    AVG(scan_duration) as avg_duration,
                    SUM(new_accounts) as discoveries,
                    AVG(efficiency_score) as avg_efficiency
                FROM scan_history 
                WHERE completed_at >= ?
                GROUP BY wallet_address
                ORDER BY discoveries DESC, scan_count DESC
            ''', (start_time,))
            
            wallet_performance = []
            for row in cursor.fetchall():
                wallet_performance.append({
                    'wallet_address': row[0],
                    'wallet_short': format_wallet_address(row[0]),
                    'scan_count': row[1],
                    'avg_duration': round(row[2] or 0, 2),
                    'discoveries': row[3] or 0,
                    'avg_efficiency': round(row[4] or 0, 2)
                })
            
            # Métriques temporelles (par heure)
            cursor.execute('''
                SELECT 
                    strftime('%H', datetime(completed_at, 'unixepoch')) as hour,
                    COUNT(*) as scans,
                    AVG(scan_duration) as avg_duration,
                    SUM(new_accounts) as discoveries
                FROM scan_history 
                WHERE completed_at >= ?
                GROUP BY hour
                ORDER BY hour
            ''', (start_time,))
            
            hourly_metrics = []
            for row in cursor.fetchall():
                hourly_metrics.append({
                    'hour': int(row[0]),
                    'scans': row[1],
                    'avg_duration': round(row[2] or 0, 2),
                    'discoveries': row[3] or 0
                })
        
        metrics = {
            'period': {
                'hours': hours,
                'start_time': start_time,
                'end_time': get_current_timestamp()
            },
            'scan_metrics': {
                'total_scans': scan_metrics[0] or 0,
                'avg_duration_seconds': round(scan_metrics[1] or 0, 2),
                'total_discoveries': scan_metrics[2] or 0,
                'active_scans': scan_metrics[3] or 0,
                'activity_rate': safe_divide(scan_metrics[3], scan_metrics[0], 0) * 100
            },
            'transaction_metrics': {
                'total_transactions': tx_metrics[0] or 0,
                'token_transactions': tx_metrics[1] or 0,
                'large_transactions': tx_metrics[2] or 0,
                'active_wallets': tx_metrics[3] or 0,
                'token_ratio': safe_divide(tx_metrics[1], tx_metrics[0], 0) * 100
            },
            'wallet_performance': wallet_performance,
            'hourly_distribution': hourly_metrics
        }
        
        return jsonify(format_api_response(
            metrics,
            message=f"System metrics for last {hours} hours"
        ))
        
    except Exception as e:
        update_error_stats()
        logger.error(f"Failed to get system metrics: {e}")
        
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Failed to retrieve metrics: {e}"
        )), 500


# =============================================================================
# ROUTES DE CONFIGURATION
# =============================================================================

@admin_bp.route('/config', methods=['GET'])
@admin_required
def get_configuration():
    """Récupération de la configuration actuelle"""
    try:
        update_request_stats()
        config = get_config()
        
        # Configuration sécurisée (sans les informations sensibles)
        safe_config = {
            'environment': config.environment.value,
            'wallet': {
                'count': len(config.wallet.addresses),
                'selection_mode': config.wallet.selection_mode.value,
                'min_interval': config.wallet.min_interval_between_scans,
                'addresses': [format_wallet_address(addr) for addr in config.wallet.addresses]
            },
            'monitoring': {
                'update_interval': config.monitoring.update_interval,
                'full_scan_interval_hours': config.monitoring.full_scan_interval_hours,
                'rate_limit_delay': config.monitoring.rate_limit_delay,
                'max_consecutive_errors': config.monitoring.max_consecutive_errors
            },
            'batching': {
                'enabled': config.batching.enabled,
                'adaptive_sizing': config.batching.adaptive_sizing,
                'batch_sizes': config.batching.batch_sizes.copy(),
                'min_delay_between_batches': config.batching.min_delay_between_batches
            },
            'rpc': {
                'timeout': config.rpc.timeout,
                'max_retries': config.rpc.max_retries,
                'requests_per_minute': config.rpc.requests_per_minute,
                'endpoints_count': len(config.rpc.get_all_endpoints())
            },
            'database': {
                'name': config.database.name,
                'timeout': config.database.timeout,
                'backup_enabled': config.database.backup_enabled
            },
            'logging': {
                'level': config.logging.level.value,
                'console_output': config.logging.console_output,
                'json_output': config.logging.json_output
            },
            'flask': {
                'host': config.flask.host,
                'port': config.flask.port,
                'debug': config.flask.debug,
                'cors_enabled': config.flask.cors_enabled
            }
        }
        
        return jsonify(format_api_response(
            safe_config,
            message="Configuration retrieved successfully"
        ))
        
    except Exception as e:
        update_error_stats()
        logger.error(f"Failed to get configuration: {e}")
        
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Failed to retrieve configuration: {e}"
        )), 500


@admin_bp.route('/config/validate', methods=['POST'])
@admin_required
def validate_configuration():
    """Validation d'une configuration avant application"""
    try:
        update_request_stats()
        config_data = request.get_json()
        
        if not config_data:
            return jsonify(format_api_response(
                None,
                success=False,
                message="No configuration data provided"
            )), 400
        
        validation_results = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'checks': {}
        }
        
        # Validation des wallets
        if 'wallet' in config_data:
            wallet_config = config_data['wallet']
            
            if 'addresses' in wallet_config:
                addresses = wallet_config['addresses']
                if not isinstance(addresses, list) or not addresses:
                    validation_results['errors'].append("Wallet addresses must be a non-empty list")
                    validation_results['valid'] = False
                else:
                    invalid_addresses = []
                    for addr in addresses:
                        if not validate_wallet_address(addr):
                            invalid_addresses.append(addr)
                    
                    if invalid_addresses:
                        validation_results['errors'].append(
                            f"Invalid wallet addresses: {invalid_addresses}"
                        )
                        validation_results['valid'] = False
                    
                    if len(addresses) > SECURITY_LIMITS['max_wallets_per_instance']:
                        validation_results['warnings'].append(
                            f"Large number of wallets ({len(addresses)}) may impact performance"
                        )
                
                validation_results['checks']['wallets'] = {
                    'count': len(addresses) if isinstance(addresses, list) else 0,
                    'valid_addresses': len(addresses) - len(invalid_addresses) if isinstance(addresses, list) else 0
                }
        
        # Validation du monitoring
        if 'monitoring' in config_data:
            monitoring_config = config_data['monitoring']
            
            if 'update_interval' in monitoring_config:
                interval = monitoring_config['update_interval']
                if not isinstance(interval, (int, float)) or interval < 5:
                    validation_results['errors'].append("Update interval must be at least 5 seconds")
                    validation_results['valid'] = False
                elif interval < 30:
                    validation_results['warnings'].append(
                        "Short update interval may cause rate limiting"
                    )
            
            validation_results['checks']['monitoring'] = {
                'update_interval': monitoring_config.get('update_interval', 'not_set')
            }
        
        # Validation du batching
        if 'batching' in config_data:
            batching_config = config_data['batching']
            
            if 'batch_sizes' in batching_config:
                batch_sizes = batching_config['batch_sizes']
                if isinstance(batch_sizes, dict):
                    for method, size in batch_sizes.items():
                        if not isinstance(size, int) or size < 1 or size > 100:
                            validation_results['errors'].append(
                                f"Invalid batch size for {method}: {size} (must be 1-100)"
                            )
                            validation_results['valid'] = False
            
            validation_results['checks']['batching'] = {
                'enabled': batching_config.get('enabled', False),
                'batch_sizes': batching_config.get('batch_sizes', {})
            }
        
        # Résumé de validation
        validation_results['summary'] = {
            'total_errors': len(validation_results['errors']),
            'total_warnings': len(validation_results['warnings']),
            'recommendation': 'approved' if validation_results['valid'] and len(validation_results['warnings']) == 0 else
                           'approved_with_warnings' if validation_results['valid'] else 'rejected'
        }
        
        return jsonify(format_api_response(
            validation_results,
            success=True,
            message=f"Configuration validation completed: {validation_results['summary']['recommendation']}"
        ))
        
    except Exception as e:
        update_error_stats()
        logger.error(f"Configuration validation failed: {e}")
        
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Configuration validation failed: {e}"
        )), 500


# =============================================================================
# ROUTES DE MAINTENANCE
# =============================================================================

@admin_bp.route('/maintenance/database-cleanup', methods=['POST'])
@admin_required
def database_cleanup():
    """Nettoyage de la base de données"""
    try:
        update_request_stats()
        
        # Paramètres de nettoyage
        days_to_keep = request.args.get('days', 30, type=int)
        tables_to_clean = request.args.get('tables', 'scan_history,wallet_activity_metrics')
        dry_run = request.args.get('dry_run', 'false').lower() == 'true'
        
        if days_to_keep < 1 or days_to_keep > 365:
            return jsonify(format_api_response(
                None,
                success=False,
                message="Days to keep must be between 1 and 365"
            )), 400
        
        cutoff_timestamp = get_current_timestamp() - (days_to_keep * 24 * 3600)
        tables_list = [t.strip() for t in tables_to_clean.split(',')]
        
        cleanup_results = {
            'dry_run': dry_run,
            'cutoff_date': format_timestamp(cutoff_timestamp),
            'tables_processed': {},
            'total_rows_deleted': 0
        }
        
        db_manager = DatabaseManager()
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            for table in tables_list:
                if table in ['scan_history', 'wallet_activity_metrics']:
                    try:
                        # Compter les lignes à supprimer
                        timestamp_column = 'completed_at' if table == 'scan_history' else 'timestamp'
                        cursor.execute(f'''
                            SELECT COUNT(*) FROM {table} 
                            WHERE {timestamp_column} < ?
                        ''', (cutoff_timestamp,))
                        
                        rows_to_delete = cursor.fetchone()[0]
                        
                        if not dry_run and rows_to_delete > 0:
                            # Effectuer le nettoyage
                            cursor.execute(f'''
                                DELETE FROM {table} 
                                WHERE {timestamp_column} < ?
                            ''', (cutoff_timestamp,))
                            
                            actual_deleted = cursor.rowcount
                            conn.commit()
                        else:
                            actual_deleted = rows_to_delete
                        
                        cleanup_results['tables_processed'][table] = {
                            'rows_found': rows_to_delete,
                            'rows_deleted': actual_deleted if not dry_run else 0,
                            'status': 'success'
                        }
                        
                        cleanup_results['total_rows_deleted'] += actual_deleted if not dry_run else 0
                        
                    except Exception as e:
                        cleanup_results['tables_processed'][table] = {
                            'status': 'error',
                            'error': str(e)
                        }
                else:
                    cleanup_results['tables_processed'][table] = {
                        'status': 'skipped',
                        'reason': 'table not allowed for cleanup'
                    }
        
        action = "would delete" if dry_run else "deleted"
        message = f"Database cleanup completed: {action} {cleanup_results['total_rows_deleted']} rows"
        
        logger.info(f"Database cleanup: {message}")
        
        return jsonify(format_api_response(
            cleanup_results,
            message=message
        ))
        
    except Exception as e:
        update_error_stats()
        logger.error(f"Database cleanup failed: {e}")
        
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Database cleanup failed: {e}"
        )), 500


@admin_bp.route('/maintenance/reset-priorities', methods=['POST'])
@admin_required
def reset_wallet_priorities():
    """Reset des priorités des wallets"""
    try:
        update_request_stats()
        
        # Paramètres
        confirm = request.args.get('confirm', 'false').lower() == 'true'
        wallet_address = request.args.get('wallet')  # Optionnel: reset un seul wallet
        
        if not confirm:
            return jsonify(format_api_response(
                None,
                success=False,
                message="Priority reset requires confirmation (confirm=true)"
            )), 400
        
        reset_results = {
            'wallets_reset': 0,
            'errors': [],
            'timestamp': get_current_timestamp()
        }
        
        try:
            priority_manager = PriorityManager()
            
            if wallet_address:
                # Reset d'un seul wallet
                if not validate_wallet_address(wallet_address):
                    return jsonify(format_api_response(
                        None,
                        success=False,
                        message="Invalid wallet address"
                    )), 400
                
                success = priority_manager.reset_wallet_priority(wallet_address)
                if success:
                    reset_results['wallets_reset'] = 1
                    message = f"Priority reset for wallet {format_wallet_address(wallet_address)}"
                else:
                    reset_results['errors'].append(f"Failed to reset priority for {wallet_address}")
                    message = "Priority reset failed"
            else:
                # Reset de tous les wallets
                reset_count = priority_manager.reset_all_priorities()
                reset_results['wallets_reset'] = reset_count
                message = f"Priority reset completed for {reset_count} wallets"
            
            logger.info(f"Priority reset: {message}")
            
            return jsonify(format_api_response(
                reset_results,
                message=message
            ))
            
        except Exception as e:
            reset_results['errors'].append(str(e))
            raise e
        
    except Exception as e:
        update_error_stats()
        logger.error(f"Priority reset failed: {e}")
        
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Priority reset failed: {e}"
        )), 500


# =============================================================================
# ROUTES DE DEBUGGING ET DIAGNOSTICS
# =============================================================================

@admin_bp.route('/debug/logs', methods=['GET'])
@admin_required
def get_recent_logs():
    """Récupération des logs récents pour debugging"""
    try:
        update_request_stats()
        
        lines = request.args.get('lines', 100, type=int)
        level = request.args.get('level', 'INFO')
        
        lines = min(max(lines, 10), 1000)  # Entre 10 et 1000 lignes
        
        config = get_config()
        log_file_path = config.logging.file_path
        
        try:
            with open(log_file_path, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
            
            # Filtrer par niveau si spécifié
            if level and level != 'ALL':
                filtered_lines = [
                    line for line in all_lines 
                    if f' - {level} - ' in line
                ]
            else:
                filtered_lines = all_lines
            
            # Prendre les dernières lignes
            recent_logs = filtered_lines[-lines:] if filtered_lines else []
            
            log_data = {
                'lines_requested': lines,
                'lines_returned': len(recent_logs),
                'level_filter': level,
                'log_file': log_file_path,
                'logs': [line.strip() for line in recent_logs]
            }
            
            return jsonify(format_api_response(
                log_data,
                message=f"Retrieved {len(recent_logs)} log lines"
            ))
            
        except FileNotFoundError:
            return jsonify(format_api_response(
                {'error': 'log_file_not_found', 'path': log_file_path},
                success=False,
                message="Log file not found"
            )), 404
            
        except PermissionError:
            return jsonify(format_api_response(
                {'error': 'permission_denied', 'path': log_file_path},
                success=False,
                message="Permission denied to read log file"
            )), 403
        
    except Exception as e:
        update_error_stats()
        logger.error(f"Failed to retrieve logs: {e}")
        
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Failed to retrieve logs: {e}"
        )), 500


@admin_bp.route('/debug/performance', methods=['GET'])
@admin_required
def get_performance_debug():
    """Informations de debugging des performances"""
    try:
        update_request_stats()
        
        debug_info = {
            'timestamp': get_current_timestamp(),
            'uptime_seconds': time.time() - _system_stats['start_time'],
            'memory': {},
            'threads': {},
            'performance': {}
        }
        
        # Informations mémoire (si psutil est disponible)
        try:
            import psutil
            import os
            
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            
            debug_info['memory'] = {
                'rss': format_memory_usage(memory_info.rss),
                'vms': format_memory_usage(memory_info.vms),
                'percent': round(process.memory_percent(), 2)
            }
            
            debug_info['cpu'] = {
                'percent': round(process.cpu_percent(), 2),
                'num_threads': process.num_threads()
            }
            
        except ImportError:
            debug_info['memory'] = {'status': 'psutil_not_available'}
        except Exception as e:
            debug_info['memory'] = {'error': str(e)}
        
        # Informations sur les threads
        debug_info['threads'] = {
            'active_count': threading.active_count(),
            'current_thread': threading.current_thread().name
        }
        
        # Statistiques de performance système
        with _stats_lock:
            debug_info['performance'] = {
                'total_requests': _system_stats['requests_count'],
                'total_errors': _system_stats['errors_count'],
                'error_rate': safe_divide(_system_stats['errors_count'], 
                                        _system_stats['requests_count'], 0) * 100,
                'requests_per_second': safe_divide(
                    _system_stats['requests_count'],
                    time.time() - _system_stats['start_time'], 0
                )
            }
        
        return jsonify(format_api_response(
            debug_info,
            message="Performance debug information retrieved"
        ))
        
    except Exception as e:
        update_error_stats()
        logger.error(f"Performance debug failed: {e}")
        
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Performance debug failed: {e}"
        )), 500


@admin_bp.route('/debug/database-stats', methods=['GET'])
@admin_required
def get_database_stats():
    """Statistiques détaillées de la base de données"""
    try:
        update_request_stats()
        
        db_manager = DatabaseManager()
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            db_stats = {
                'timestamp': get_current_timestamp(),
                'tables': {},
                'indexes': {},
                'performance': {}
            }
            
            # Statistiques par table
            tables = ['transactions', 'token_accounts', 'wallet_priorities', 
                     'scan_history', 'wallet_activity_metrics', 'tokens']
            
            for table in tables:
                try:
                    # Nombre de lignes
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    row_count = cursor.fetchone()[0]
                    
                    # Taille approximative (SQLite)
                    cursor.execute(f"""
                        SELECT 
                            COUNT(*) as rows,
                            COUNT(*) * AVG(LENGTH(COALESCE(*, ''))) as approx_size
                        FROM {table}
                    """)
                    
                    db_stats['tables'][table] = {
                        'row_count': row_count,
                        'status': 'ok'
                    }
                    
                    # Statistiques spécifiques selon la table
                    if table == 'transactions':
                        cursor.execute("""
                            SELECT 
                                COUNT(CASE WHEN is_token_transaction = 1 THEN 1 END) as token_tx,
                                COUNT(CASE WHEN is_large_token_amount = 1 THEN 1 END) as large_tx,
                                COUNT(DISTINCT wallet_address) as unique_wallets,
                                MIN(block_time) as oldest_tx,
                                MAX(block_time) as newest_tx
                            FROM transactions
                        """)
                        
                        tx_stats = cursor.fetchone()
                        db_stats['tables'][table].update({
                            'token_transactions': tx_stats[0] or 0,
                            'large_transactions': tx_stats[1] or 0,
                            'unique_wallets': tx_stats[2] or 0,
                            'oldest_transaction': format_timestamp(tx_stats[3], 'relative') if tx_stats[3] else 'N/A',
                            'newest_transaction': format_timestamp(tx_stats[4], 'relative') if tx_stats[4] else 'N/A'
                        })
                    
                    elif table == 'wallet_priorities':
                        cursor.execute("""
                            SELECT 
                                AVG(priority_score) as avg_priority,
                                MIN(priority_score) as min_priority,
                                MAX(priority_score) as max_priority,
                                COUNT(CASE WHEN last_scan_time > 0 THEN 1 END) as wallets_scanned
                            FROM wallet_priorities
                        """)
                        
                        priority_stats = cursor.fetchone()
                        db_stats['tables'][table].update({
                            'avg_priority': round(priority_stats[0] or 0, 2),
                            'min_priority': round(priority_stats[1] or 0, 2),
                            'max_priority': round(priority_stats[2] or 0, 2),
                            'wallets_scanned': priority_stats[3] or 0
                        })
                
                except Exception as e:
                    db_stats['tables'][table] = {
                        'status': 'error',
                        'error': str(e)
                    }
            
            # Vérification des index critiques
            critical_indexes = [
                'idx_transactions_wallet_time',
                'idx_token_accounts_wallet',
                'idx_wallet_priorities_score'
            ]
            
            for index_name in critical_indexes:
                try:
                    cursor.execute("""
                        SELECT name FROM sqlite_master 
                        WHERE type='index' AND name=?
                    """, (index_name,))
                    
                    exists = cursor.fetchone() is not None
                    db_stats['indexes'][index_name] = {
                        'exists': exists,
                        'status': 'ok' if exists else 'missing'
                    }
                    
                except Exception as e:
                    db_stats['indexes'][index_name] = {
                        'status': 'error',
                        'error': str(e)
                    }
            
            # Performance de base de données
            try:
                # Test de performance simple
                start_time = time.time()
                cursor.execute("SELECT COUNT(*) FROM transactions WHERE wallet_address IS NOT NULL")
                query_time = time.time() - start_time
                
                db_stats['performance'] = {
                    'simple_query_time_ms': round(query_time * 1000, 2),
                    'status': 'fast' if query_time < 0.1 else 'slow' if query_time > 1.0 else 'normal'
                }
                
            except Exception as e:
                db_stats['performance'] = {
                    'status': 'error',
                    'error': str(e)
                }
        
        return jsonify(format_api_response(
            db_stats,
            message="Database statistics retrieved successfully"
        ))
        
    except Exception as e:
        update_error_stats()
        logger.error(f"Database stats failed: {e}")
        
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Database statistics failed: {e}"
        )), 500


# =============================================================================
# ROUTES D'ADMINISTRATION DES WALLETS
# =============================================================================

@admin_bp.route('/wallets', methods=['GET'])
@admin_required
def list_managed_wallets():
    """Liste des wallets gérés par le système"""
    try:
        update_request_stats()
        config = get_config()
        
        wallets_info = []
        
        try:
            priority_manager = PriorityManager()
            
            for wallet_address in config.wallet.addresses:
                try:
                    # Récupérer les informations de priorité
                    priority_info = priority_manager.get_wallet_priority(wallet_address)
                    
                    wallet_info = {
                        'address': wallet_address,
                        'address_short': format_wallet_address(wallet_address),
                        'priority_score': priority_info.get('priority_score', 1.0),
                        'last_scan_time': priority_info.get('last_scan_time', 0),
                        'total_scans': priority_info.get('total_scans', 0),
                        'consecutive_empty_scans': priority_info.get('consecutive_empty_scans', 0),
                        'time_since_scan': calculate_time_since(priority_info.get('last_scan_time', 0)),
                        'status': 'active' if priority_info.get('priority_score', 0) > 0.5 else 'inactive'
                    }
                    
                    # Ajouter des informations de base de données si disponibles
                    db_manager = DatabaseManager()
                    with db_manager.get_connection() as conn:
                        cursor = conn.cursor()
                        
                        # Compter les transactions
                        cursor.execute("""
                            SELECT COUNT(*) FROM transactions 
                            WHERE wallet_address = ?
                        """, (wallet_address,))
                        tx_count = cursor.fetchone()[0]
                        
                        # Compter les comptes de tokens
                        cursor.execute("""
                            SELECT COUNT(*) FROM token_accounts 
                            WHERE wallet_address = ? AND is_active = 1
                        """, (wallet_address,))
                        token_accounts = cursor.fetchone()[0]
                        
                        wallet_info.update({
                            'transaction_count': tx_count,
                            'token_accounts': token_accounts
                        })
                    
                    wallets_info.append(wallet_info)
                    
                except Exception as e:
                    # Ajouter le wallet même en cas d'erreur
                    wallets_info.append({
                        'address': wallet_address,
                        'address_short': format_wallet_address(wallet_address),
                        'status': 'error',
                        'error': str(e)
                    })
        
        except Exception as e:
            logger.error(f"Error retrieving wallet priorities: {e}")
            # Fallback: liste basique des wallets
            for wallet_address in config.wallet.addresses:
                wallets_info.append({
                    'address': wallet_address,
                    'address_short': format_wallet_address(wallet_address),
                    'status': 'unknown',
                    'error': 'Priority system unavailable'
                })
        
        # Statistiques globales
        total_wallets = len(wallets_info)
        active_wallets = len([w for w in wallets_info if w.get('status') == 'active'])
        
        summary = {
            'total_wallets': total_wallets,
            'active_wallets': active_wallets,
            'inactive_wallets': total_wallets - active_wallets,
            'selection_mode': config.wallet.selection_mode.value,
            'wallets': wallets_info
        }
        
        return jsonify(format_api_response(
            summary,
            message=f"Retrieved information for {total_wallets} wallets"
        ))
        
    except Exception as e:
        update_error_stats()
        logger.error(f"Failed to list wallets: {e}")
        
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Failed to retrieve wallet list: {e}"
        )), 500


@admin_bp.route('/wallets/<wallet_address>/priority', methods=['PUT'])
@admin_required
def update_wallet_priority(wallet_address: str):
    """Mise à jour manuelle de la priorité d'un wallet"""
    try:
        update_request_stats()
        
        if not validate_wallet_address(wallet_address):
            return jsonify(format_api_response(
                None,
                success=False,
                message="Invalid wallet address format"
            )), 400
        
        data = request.get_json()
        if not data or 'priority_score' not in data:
            return jsonify(format_api_response(
                None,
                success=False,
                message="Priority score is required"
            )), 400
        
        new_priority = data['priority_score']
        reason = data.get('reason', 'Manual admin update')
        
        # Validation de la priorité
        if not isinstance(new_priority, (int, float)) or not (0.1 <= new_priority <= 10.0):
            return jsonify(format_api_response(
                None,
                success=False,
                message="Priority score must be between 0.1 and 10.0"
            )), 400
        
        try:
            priority_manager = PriorityManager()
            
            # Récupérer l'ancienne priorité
            old_priority_info = priority_manager.get_wallet_priority(wallet_address)
            old_priority = old_priority_info.get('priority_score', 1.0)
            
            # Mettre à jour la priorité
            success = priority_manager.set_wallet_priority(
                wallet_address, 
                new_priority, 
                reason=reason
            )
            
            if success:
                result = {
                    'wallet_address': wallet_address,
                    'wallet_short': format_wallet_address(wallet_address),
                    'old_priority': round(old_priority, 2),
                    'new_priority': round(new_priority, 2),
                    'change': round(new_priority - old_priority, 2),
                    'reason': reason,
                    'updated_at': get_current_timestamp()
                }
                
                logger.info(f"Manual priority update: {wallet_address[:8]}... "
                           f"{old_priority:.2f} → {new_priority:.2f} ({reason})")
                
                return jsonify(format_api_response(
                    result,
                    message=f"Priority updated successfully for {format_wallet_address(wallet_address)}"
                ))
            else:
                return jsonify(format_api_response(
                    None,
                    success=False,
                    message="Failed to update wallet priority"
                )), 500
                
        except Exception as e:
            logger.error(f"Priority update failed for {wallet_address}: {e}")
            return jsonify(format_api_response(
                None,
                success=False,
                message=f"Priority update failed: {e}"
            )), 500
        
    except Exception as e:
        update_error_stats()
        logger.error(f"Wallet priority update failed: {e}")
        
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Failed to update wallet priority: {e}"
        )), 500


@admin_bp.route('/wallets/<wallet_address>', methods=['DELETE'])
@admin_required
def remove_wallet(wallet_address: str):
    """Suppression d'un wallet du système (soft delete)"""
    try:
        update_request_requests()
        
        if not validate_wallet_address(wallet_address):
            return jsonify(format_api_response(
                None,
                success=False,
                message="Invalid wallet address format"
            )), 400
        
        # Vérification de confirmation
        confirm = request.args.get('confirm', 'false').lower() == 'true'
        if not confirm:
            return jsonify(format_api_response(
                None,
                success=False,
                message="Wallet removal requires confirmation (confirm=true)"
            )), 400
        
        # TODO: Implémenter la suppression soft du wallet
        # Pour l'instant, on se contente de désactiver sa priorité
        
        try:
            priority_manager = PriorityManager()
            success = priority_manager.set_wallet_priority(
                wallet_address, 
                0.0, 
                reason="Admin removal"
            )
            
            if success:
                result = {
                    'wallet_address': wallet_address,
                    'wallet_short': format_wallet_address(wallet_address),
                    'action': 'deactivated',
                    'timestamp': get_current_timestamp(),
                    'note': 'Wallet priority set to 0 (soft removal)'
                }
                
                logger.warning(f"Wallet deactivated by admin: {wallet_address}")
                
                return jsonify(format_api_response(
                    result,
                    message=f"Wallet {format_wallet_address(wallet_address)} has been deactivated"
                ))
            else:
                return jsonify(format_api_response(
                    None,
                    success=False,
                    message="Failed to deactivate wallet"
                )), 500
                
        except Exception as e:
            logger.error(f"Wallet deactivation failed for {wallet_address}: {e}")
            return jsonify(format_api_response(
                None,
                success=False,
                message=f"Wallet deactivation failed: {e}"
            )), 500
        
    except Exception as e:
        update_error_stats()
        logger.error(f"Wallet removal failed: {e}")
        
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Failed to remove wallet: {e}"
        )), 500


# =============================================================================
# ROUTES DE STATISTIQUES AVANCÉES
# =============================================================================

@admin_bp.route('/stats/summary', methods=['GET'])
@admin_required
def get_admin_summary():
    """Résumé exécutif pour les administrateurs"""
    try:
        update_request_stats()
        
        # Période d'analyse
        hours = request.args.get('hours', 24, type=int)
        start_time = get_current_timestamp() - (hours * 3600)
        
        summary = {
            'timestamp': get_current_timestamp(),
            'period_hours': hours,
            'system': {},
            'performance': {},
            'wallets': {},
            'activity': {},
            'alerts': []
        }
        
        # Informations système
        config = get_config()
        summary['system'] = {
            'version': SYSTEM_INFO['version'],
            'environment': config.environment.value,
            'uptime': format_duration(time.time() - _system_stats['start_time']),
            'wallets_configured': len(config.wallet.addresses),
            'batching_enabled': config.batching.enabled
        }
        
        # Performance système
        with _stats_lock:
            summary['performance'] = {
                'total_requests': _system_stats['requests_count'],
                'error_rate': safe_divide(_system_stats['errors_count'], 
                                        _system_stats['requests_count'], 0) * 100,
                'avg_requests_per_hour': safe_divide(
                    _system_stats['requests_count'],
                    (time.time() - _system_stats['start_time']) / 3600, 0
                )
            }
        
        # Statistiques des wallets et activité
        try:
            db_manager = DatabaseManager()
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Activité des scans
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_scans,
                        AVG(scan_duration) as avg_duration,
                        SUM(new_accounts) as discoveries,
                        COUNT(CASE WHEN activity_detected = 1 THEN 1 END) as active_scans
                    FROM scan_history 
                    WHERE completed_at >= ?
                """, (start_time,))
                
                scan_stats = cursor.fetchone()
                summary['activity'] = {
                    'total_scans': scan_stats[0] or 0,
                    'avg_scan_duration': round(scan_stats[1] or 0, 2),
                    'total_discoveries': scan_stats[2] or 0,
                    'activity_rate': safe_divide(scan_stats[3], scan_stats[0], 0) * 100 if scan_stats[0] else 0
                }
                
                # Transactions récentes
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_tx,
                        COUNT(CASE WHEN is_token_transaction = 1 THEN 1 END) as token_tx,
                        COUNT(CASE WHEN is_large_token_amount = 1 THEN 1 END) as large_tx
                    FROM transactions 
                    WHERE block_time >= ?
                """, (start_time,))
                
                tx_stats = cursor.fetchone()
                summary['activity'].update({
                    'transactions_detected': tx_stats[0] or 0,
                    'token_transactions': tx_stats[1] or 0,
                    'large_transactions': tx_stats[2] or 0
                })
                
                # État des wallets
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_wallets,
                        AVG(priority_score) as avg_priority,
                        COUNT(CASE WHEN priority_score >= 4.0 THEN 1 END) as high_priority,
                        COUNT(CASE WHEN last_scan_time > 0 THEN 1 END) as scanned_wallets
                    FROM wallet_priorities
                """)
                
                wallet_stats = cursor.fetchone()
                summary['wallets'] = {
                    'total_managed': wallet_stats[0] or 0,
                    'avg_priority': round(wallet_stats[1] or 0, 2),
                    'high_priority_count': wallet_stats[2] or 0,
                    'active_wallets': wallet_stats[3] or 0
                }
        
        except Exception as e:
            logger.error(f"Database query error in admin summary: {e}")
            summary['activity'] = {'error': 'Database unavailable'}
            summary['wallets'] = {'error': 'Database unavailable'}
        
        # Alertes et recommandations
        alerts = []
        
        # Vérifier le taux d'erreur
        error_rate = summary['performance']['error_rate']
        if error_rate > 10:
            alerts.append({
                'level': 'critical' if error_rate > 25 else 'warning',
                'type': 'high_error_rate',
                'message': f"High error rate: {error_rate:.1f}%",
                'recommendation': "Check logs and system health"
            })
        
        # Vérifier l'activité
        if 'total_scans' in summary['activity'] and summary['activity']['total_scans'] == 0:
            alerts.append({
                'level': 'critical',
                'type': 'no_activity',
                'message': f"No scans completed in the last {hours} hours",
                'recommendation': "Check monitoring system status"
            })
        
        # Vérifier les découvertes
        if ('total_discoveries' in summary['activity'] and 
            summary['activity']['total_discoveries'] == 0 and 
            summary['activity'].get('total_scans', 0) > 10):
            alerts.append({
                'level': 'warning',
                'type': 'no_discoveries',
                'message': "No new token discoveries despite active scanning",
                'recommendation': "Review wallet selection and scanning parameters"
            })
        
        summary['alerts'] = alerts
        summary['health_status'] = 'critical' if any(a['level'] == 'critical' for a in alerts) else \
                                  'warning' if any(a['level'] == 'warning' for a in alerts) else 'healthy'
        
        return jsonify(format_api_response(
            summary,
            message=f"Admin summary for last {hours} hours (Status: {summary['health_status']})"
        ))
        
    except Exception as e:
        update_error_stats()
        logger.error(f"Admin summary failed: {e}")
        
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Failed to generate admin summary: {e}"
        )), 500


# =============================================================================
# GESTIONNAIRES D'ERREURS POUR LE BLUEPRINT
# =============================================================================

@admin_bp.errorhandler(400)
def bad_request(error):
    """Gestionnaire d'erreur pour les requêtes malformées"""
    update_error_stats()
    return jsonify(format_api_response(
        None,
        success=False,
        message="Bad request - Invalid parameters"
    )), 400


@admin_bp.errorhandler(403)
def forbidden(error):
    """Gestionnaire d'erreur pour les accès non autorisés"""
    update_error_stats()
    return jsonify(format_api_response(
        None,
        success=False,
        message="Access forbidden - Admin privileges required"
    )), 403


@admin_bp.errorhandler(500)
def internal_error(error):
    """Gestionnaire d'erreur serveur interne"""
    update_error_stats()
    logger.error(f"Internal server error in admin routes: {error}")
    
    return jsonify(format_api_response(
        None,
        success=False,
        message="Internal server error"
    )), 500


# =============================================================================
# HOOKS ET MIDDLEWARES
# =============================================================================

@admin_bp.before_request
def before_admin_request():
    """Exécuté avant chaque requête admin"""
    # Log des requêtes admin pour audit
    logger.info(f"Admin request: {request.method} {request.path} from {request.remote_addr}")


@admin_bp.after_request
def after_admin_request(response):
    """Exécuté après chaque requête admin"""
    # Ajouter des headers de sécurité
    response.headers['X-Admin-Response'] = 'true'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    
    return response


# =============================================================================
# EXPORT
# =============================================================================

__all__ = ['admin_bp']