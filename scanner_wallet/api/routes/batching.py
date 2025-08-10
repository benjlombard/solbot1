
#!/usr/bin/env python3
"""
Routes de gestion du batching RPC pour le Solana Wallet Monitor
Contrôle, monitoring et optimisation du système de batching intelligent
"""

from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
import logging
import time
import threading

# Imports depuis la nouvelle structure
from core.config import get_config
from core.logger import get_logger
from core.exceptions import (
    BatchingError, BatchSizeError, BatchExecutionError,
    RPCError, ConfigurationError
)
from rpc.batch_manager import BatchManager
from rpc.rate_limiter import RateLimiter
from utils.helpers import (
    get_current_timestamp, calculate_time_since, safe_divide,
    clamp, calculate_moving_average
)
from utils.formatters import (
    format_duration, format_api_response, format_percentage,
    format_compact_number, format_batch_info
)
from utils.constants import (
    OPTIMAL_BATCH_SIZES, CONSERVATIVE_BATCH_SIZES,
    PERFORMANCE_THRESHOLDS, ADAPTIVE_INTERVALS,
    RPC_TIMEOUT_BATCH
)

# Configuration du blueprint
batching_bp = Blueprint('batching', __name__, url_prefix='/api/batching')
logger = get_logger(__name__)

# Statistiques globales du batching
_batching_stats = {
    'start_time': time.time(),
    'total_batches': 0,
    'successful_batches': 0,
    'failed_batches': 0,
    'total_items_processed': 0,
    'total_time_saved': 0.0,
    'performance_history': []
}
_stats_lock = threading.Lock()


# =============================================================================
# HELPERS ET UTILITAIRES
# =============================================================================

def update_batching_stats(batch_result: Dict[str, Any]) -> None:
    """Met à jour les statistiques globales de batching"""
    with _stats_lock:
        _batching_stats['total_batches'] += 1
        
        if batch_result.get('success', False):
            _batching_stats['successful_batches'] += 1
        else:
            _batching_stats['failed_batches'] += 1
        
        _batching_stats['total_items_processed'] += batch_result.get('items_processed', 0)
        _batching_stats['total_time_saved'] += batch_result.get('time_saved', 0.0)
        
        # Garder un historique des performances (max 100 entrées)
        performance_entry = {
            'timestamp': get_current_timestamp(),
            'success': batch_result.get('success', False),
            'items': batch_result.get('items_processed', 0),
            'duration': batch_result.get('duration', 0.0),
            'method': batch_result.get('method', 'unknown')
        }
        
        _batching_stats['performance_history'].append(performance_entry)
        if len(_batching_stats['performance_history']) > 100:
            _batching_stats['performance_history'].pop(0)


def get_batch_manager() -> Optional[BatchManager]:
    """Récupère l'instance du BatchManager"""
    try:
        config = get_config()
        if not config.batching.enabled:
            return None
        
        # TODO: Récupérer l'instance depuis le système principal
        # Pour l'instant, créer une nouvelle instance
        return BatchManager()
    except Exception as e:
        logger.error(f"Failed to get BatchManager: {e}")
        return None


def validate_batch_config(config_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Valide une configuration de batching"""
    errors = []
    
    # Validation des tailles de batch
    if 'batch_sizes' in config_data:
        batch_sizes = config_data['batch_sizes']
        if not isinstance(batch_sizes, dict):
            errors.append("batch_sizes must be a dictionary")
        else:
            for method, size in batch_sizes.items():
                if not isinstance(size, int):
                    errors.append(f"Batch size for {method} must be an integer")
                elif size < 1 or size > 100:
                    errors.append(f"Batch size for {method} must be between 1 and 100 (got {size})")
    
    # Validation des délais
    if 'min_delay_between_batches' in config_data:
        delay = config_data['min_delay_between_batches']
        if not isinstance(delay, (int, float)):
            errors.append("min_delay_between_batches must be a number")
        elif delay < 0 or delay > 10:
            errors.append("min_delay_between_batches must be between 0 and 10 seconds")
    
    # Validation du timeout
    if 'batch_timeout' in config_data:
        timeout = config_data['batch_timeout']
        if not isinstance(timeout, int):
            errors.append("batch_timeout must be an integer")
        elif timeout < 5 or timeout > 120:
            errors.append("batch_timeout must be between 5 and 120 seconds")
    
    return len(errors) == 0, errors


def calculate_efficiency_metrics(performance_history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calcule les métriques d'efficacité du batching"""
    if not performance_history:
        return {
            'avg_items_per_batch': 0,
            'avg_duration': 0,
            'success_rate': 0,
            'throughput_per_second': 0,
            'efficiency_trend': 'unknown'
        }
    
    # Calculs de base
    total_items = sum(entry['items'] for entry in performance_history)
    total_duration = sum(entry['duration'] for entry in performance_history)
    successful_batches = sum(1 for entry in performance_history if entry['success'])
    
    avg_items = total_items / len(performance_history) if performance_history else 0
    avg_duration = total_duration / len(performance_history) if performance_history else 0
    success_rate = (successful_batches / len(performance_history)) * 100 if performance_history else 0
    throughput = total_items / total_duration if total_duration > 0 else 0
    
    # Tendance d'efficacité (comparaison première moitié vs seconde moitié)
    if len(performance_history) >= 10:
        mid_point = len(performance_history) // 2
        first_half = performance_history[:mid_point]
        second_half = performance_history[mid_point:]
        
        first_half_success = sum(1 for entry in first_half if entry['success']) / len(first_half) * 100
        second_half_success = sum(1 for entry in second_half if entry['success']) / len(second_half) * 100
        
        if second_half_success > first_half_success + 5:
            trend = 'improving'
        elif second_half_success < first_half_success - 5:
            trend = 'degrading'
        else:
            trend = 'stable'
    else:
        trend = 'insufficient_data'
    
    return {
        'avg_items_per_batch': round(avg_items, 1),
        'avg_duration': round(avg_duration, 3),
        'success_rate': round(success_rate, 1),
        'throughput_per_second': round(throughput, 1),
        'efficiency_trend': trend,
        'sample_size': len(performance_history)
    }


# =============================================================================
# ROUTES DE STATUS ET MONITORING
# =============================================================================

@batching_bp.route('/status', methods=['GET'])
def get_batching_status():
    """Status général du système de batching"""
    try:
        config = get_config()
        current_time = get_current_timestamp()
        
        status = {
            'timestamp': current_time,
            'enabled': config.batching.enabled,
            'uptime_seconds': current_time - int(_batching_stats['start_time'])
        }
        
        if not config.batching.enabled:
            status['message'] = "Batching is disabled in configuration"
            return jsonify(format_api_response(
                status,
                message="Batching system is disabled"
            ))
        
        # Récupérer le BatchManager
        batch_manager = get_batch_manager()
        if not batch_manager:
            status.update({
                'status': 'unavailable',
                'message': "BatchManager not available"
            })
            return jsonify(format_api_response(
                status,
                success=False,
                message="Batching system unavailable"
            ))
        
        # Statistiques actuelles
        with _stats_lock:
            batch_stats = _batching_stats.copy()
        
        # Métriques d'efficacité
        efficiency_metrics = calculate_efficiency_metrics(batch_stats['performance_history'])
        
        # Configuration actuelle
        current_config = {
            'adaptive_sizing': config.batching.adaptive_sizing,
            'batch_sizes': config.batching.batch_sizes.copy(),
            'min_delay_between_batches': config.batching.min_delay_between_batches,
            'max_concurrent_batches': config.batching.max_concurrent_batches,
            'batch_timeout': config.batching.batch_timeout
        }
        
        # Status détaillé
        status.update({
            'status': 'active',
            'configuration': current_config,
            'statistics': {
                'total_batches': batch_stats['total_batches'],
                'successful_batches': batch_stats['successful_batches'],
                'failed_batches': batch_stats['failed_batches'],
                'success_rate': safe_divide(batch_stats['successful_batches'], 
                                          batch_stats['total_batches'], 0) * 100,
                'total_items_processed': batch_stats['total_items_processed'],
                'estimated_time_saved': round(batch_stats['total_time_saved'], 2),
                'avg_items_per_batch': efficiency_metrics['avg_items_per_batch'],
                'avg_batch_duration': efficiency_metrics['avg_duration'],
                'throughput_per_second': efficiency_metrics['throughput_per_second']
            },
            'performance': {
                'efficiency_trend': efficiency_metrics['efficiency_trend'],
                'current_status': 'optimal' if efficiency_metrics['success_rate'] >= 90 else
                                'suboptimal' if efficiency_metrics['success_rate'] >= 70 else
                                'poor',
                'recommendations': []
            }
        })
        
        # Recommandations basées sur les performances
        if efficiency_metrics['success_rate'] < 80:
            status['performance']['recommendations'].append(
                "Consider reducing batch sizes due to low success rate"
            )
        
        if efficiency_metrics['avg_duration'] > 5.0:
            status['performance']['recommendations'].append(
                "Batch processing is slow - check RPC endpoints performance"
            )
        
        if efficiency_metrics['efficiency_trend'] == 'degrading':
            status['performance']['recommendations'].append(
                "Performance is degrading - review configuration"
            )
        
        return jsonify(format_api_response(
            status,
            message=f"Batching system is {status['status']} with {status['statistics']['success_rate']:.1f}% success rate"
        ))
        
    except Exception as e:
        logger.error(f"Failed to get batching status: {e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Failed to retrieve batching status: {e}"
        )), 500


@batching_bp.route('/metrics', methods=['GET'])
def get_batching_metrics():
    """Métriques détaillées du batching"""
    try:
        hours = request.args.get('hours', 1, type=int)
        hours = clamp(hours, 1, 24)  # Entre 1h et 24h
        
        current_time = get_current_timestamp()
        start_time = current_time - (hours * 3600)
        
        with _stats_lock:
            performance_history = _batching_stats['performance_history'].copy()
        
        # Filtrer l'historique par période
        recent_history = [
            entry for entry in performance_history 
            if entry['timestamp'] >= start_time
        ]
        
        if not recent_history:
            return jsonify(format_api_response(
                {
                    'period_hours': hours,
                    'message': 'No batching activity in the specified period'
                },
                message=f"No batching data for the last {hours} hours"
            ))
        
        # Métriques par méthode RPC
        methods_stats = {}
        for entry in recent_history:
            method = entry['method']
            if method not in methods_stats:
                methods_stats[method] = {
                    'total_batches': 0,
                    'successful_batches': 0,
                    'total_items': 0,
                    'total_duration': 0.0,
                    'min_duration': float('inf'),
                    'max_duration': 0.0
                }
            
            stats = methods_stats[method]
            stats['total_batches'] += 1
            if entry['success']:
                stats['successful_batches'] += 1
            stats['total_items'] += entry['items']
            stats['total_duration'] += entry['duration']
            stats['min_duration'] = min(stats['min_duration'], entry['duration'])
            stats['max_duration'] = max(stats['max_duration'], entry['duration'])
        
        # Calculer les métriques finales par méthode
        for method, stats in methods_stats.items():
            stats['success_rate'] = safe_divide(stats['successful_batches'], 
                                               stats['total_batches'], 0) * 100
            stats['avg_duration'] = safe_divide(stats['total_duration'], 
                                              stats['total_batches'], 0)
            stats['avg_items_per_batch'] = safe_divide(stats['total_items'], 
                                                     stats['total_batches'], 0)
            stats['throughput'] = safe_divide(stats['total_items'], 
                                            stats['total_duration'], 0)
            
            if stats['min_duration'] == float('inf'):
                stats['min_duration'] = 0.0
        
        # Métriques temporelles (par tranche horaire)
        hourly_metrics = {}
        for entry in recent_history:
            hour_bucket = (entry['timestamp'] // 3600) * 3600
            if hour_bucket not in hourly_metrics:
                hourly_metrics[hour_bucket] = {
                    'batches': 0,
                    'successful': 0,
                    'items': 0,
                    'duration': 0.0
                }
            
            metrics = hourly_metrics[hour_bucket]
            metrics['batches'] += 1
            if entry['success']:
                metrics['successful'] += 1
            metrics['items'] += entry['items']
            metrics['duration'] += entry['duration']
        
        # Convertir en liste triée
        hourly_list = []
        for timestamp, metrics in sorted(hourly_metrics.items()):
            hourly_list.append({
                'hour': datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:00'),
                'timestamp': timestamp,
                'batches': metrics['batches'],
                'success_rate': safe_divide(metrics['successful'], metrics['batches'], 0) * 100,
                'total_items': metrics['items'],
                'avg_duration': safe_divide(metrics['duration'], metrics['batches'], 0),
                'throughput': safe_divide(metrics['items'], metrics['duration'], 0)
            })
        
        # Métriques globales pour la période
        total_batches = len(recent_history)
        successful_batches = sum(1 for entry in recent_history if entry['success'])
        total_items = sum(entry['items'] for entry in recent_history)
        total_duration = sum(entry['duration'] for entry in recent_history)
        
        global_metrics = {
            'period_hours': hours,
            'total_batches': total_batches,
            'successful_batches': successful_batches,
            'failed_batches': total_batches - successful_batches,
            'success_rate': safe_divide(successful_batches, total_batches, 0) * 100,
            'total_items_processed': total_items,
            'avg_items_per_batch': safe_divide(total_items, total_batches, 0),
            'total_processing_time': round(total_duration, 2),
            'avg_batch_duration': safe_divide(total_duration, total_batches, 0),
            'overall_throughput': safe_divide(total_items, total_duration, 0)
        }
        
        # Calcul du temps économisé estimé
        # Estimation: chaque item en batch économise ~0.1s par rapport à l'individuel
        estimated_time_saved = total_items * 0.1  # Estimation conservative
        global_metrics['estimated_time_saved'] = round(estimated_time_saved, 2)
        
        metrics_data = {
            'period': {
                'hours': hours,
                'start_time': start_time,
                'end_time': current_time
            },
            'global_metrics': global_metrics,
            'methods_breakdown': methods_stats,
            'hourly_distribution': hourly_list,
            'efficiency_analysis': calculate_efficiency_metrics(recent_history)
        }
        
        return jsonify(format_api_response(
            metrics_data,
            message=f"Batching metrics for last {hours} hours"
        ))
        
    except Exception as e:
        logger.error(f"Failed to get batching metrics: {e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Failed to retrieve batching metrics: {e}"
        )), 500


@batching_bp.route('/performance-analysis', methods=['GET'])
def get_performance_analysis():
    """Analyse avancée des performances de batching"""
    try:
        config = get_config()
        
        if not config.batching.enabled:
            return jsonify(format_api_response(
                {'enabled': False},
                message="Batching is disabled"
            ))
        
        with _stats_lock:
            performance_history = _batching_stats['performance_history'].copy()
        
        if len(performance_history) < 10:
            return jsonify(format_api_response(
                {
                    'message': 'Insufficient data for performance analysis',
                    'sample_size': len(performance_history),
                    'minimum_required': 10
                },
                message="Need more batching activity for analysis"
            ))
        
        # Analyse des tendances de performance
        analysis = {
            'sample_size': len(performance_history),
            'analysis_period': {
                'start': performance_history[0]['timestamp'],
                'end': performance_history[-1]['timestamp'],
                'duration_hours': (performance_history[-1]['timestamp'] - 
                                 performance_history[0]['timestamp']) / 3600
            },
            'performance_trends': {},
            'optimization_recommendations': [],
            'bottleneck_analysis': {},
            'comparison_with_baseline': {}
        }
        
        # Analyse des tendances par méthode
        methods_analysis = {}
        for entry in performance_history:
            method = entry['method']
            if method not in methods_analysis:
                methods_analysis[method] = {
                    'durations': [],
                    'success_rates': [],
                    'item_counts': [],
                    'timestamps': []
                }
            
            methods_analysis[method]['durations'].append(entry['duration'])
            methods_analysis[method]['success_rates'].append(1 if entry['success'] else 0)
            methods_analysis[method]['item_counts'].append(entry['items'])
            methods_analysis[method]['timestamps'].append(entry['timestamp'])
        
        # Calculer les tendances pour chaque méthode
        for method, data in methods_analysis.items():
            if len(data['durations']) < 5:
                continue
            
            # Moyenne mobile sur les 5 derniers points
            recent_avg_duration = calculate_moving_average(data['durations'][-5:])
            overall_avg_duration = sum(data['durations']) / len(data['durations'])
            
            recent_success_rate = calculate_moving_average(data['success_rates'][-5:]) * 100
            overall_success_rate = sum(data['success_rates']) / len(data['success_rates']) * 100
            
            # Déterminer la tendance
            duration_trend = 'improving' if recent_avg_duration < overall_avg_duration * 0.9 else \
                           'degrading' if recent_avg_duration > overall_avg_duration * 1.1 else 'stable'
            
            success_trend = 'improving' if recent_success_rate > overall_success_rate + 5 else \
                          'degrading' if recent_success_rate < overall_success_rate - 5 else 'stable'
            
            analysis['performance_trends'][method] = {
                'duration_trend': duration_trend,
                'success_trend': success_trend,
                'recent_avg_duration': round(recent_avg_duration, 3),
                'overall_avg_duration': round(overall_avg_duration, 3),
                'recent_success_rate': round(recent_success_rate, 1),
                'overall_success_rate': round(overall_success_rate, 1),
                'sample_count': len(data['durations'])
            }
        
        # Analyse des goulots d'étranglement
        all_durations = [entry['duration'] for entry in performance_history]
        duration_percentiles = {
            'p50': calculate_percentile(all_durations, 50),
            'p75': calculate_percentile(all_durations, 75),
            'p90': calculate_percentile(all_durations, 90),
            'p95': calculate_percentile(all_durations, 95),
            'p99': calculate_percentile(all_durations, 99)
        }
        
        analysis['bottleneck_analysis'] = {
            'duration_percentiles': {k: round(v, 3) for k, v in duration_percentiles.items()},
            'slow_batches_threshold': round(duration_percentiles['p90'], 3),
            'very_slow_batches_count': sum(1 for d in all_durations if d > duration_percentiles['p95']),
            'timeout_risk': 'high' if duration_percentiles['p95'] > RPC_BATCH_TIMEOUT * 0.8 else
                          'medium' if duration_percentiles['p90'] > RPC_BATCH_TIMEOUT * 0.6 else 'low'
        }
        
        # Comparaison avec les seuils optimaux
        current_config_sizes = config.batching.batch_sizes
        optimal_sizes = OPTIMAL_BATCH_SIZES
        
        comparison = {}
        for method, current_size in current_config_sizes.items():
            if method in optimal_sizes:
                optimal_size = optimal_sizes[method]
                comparison[method] = {
                    'current_size': current_size,
                    'optimal_size': optimal_size,
                    'difference': current_size - optimal_size,
                    'recommendation': 'increase' if current_size < optimal_size * 0.8 else
                                   'decrease' if current_size > optimal_size * 1.2 else
                                   'maintain'
                }
        
        analysis['comparison_with_baseline'] = comparison
        
        # Recommandations d'optimisation
        recommendations = []
        
        # Recommandations basées sur les tendances
        for method, trends in analysis['performance_trends'].items():
            if trends['duration_trend'] == 'degrading':
                recommendations.append({
                    'priority': 'high',
                    'category': 'performance',
                    'method': method,
                    'issue': f"Duration trend degrading for {method}",
                    'recommendation': f"Consider reducing batch size for {method} or check RPC endpoint health"
                })
            
            if trends['success_trend'] == 'degrading':
                recommendations.append({
                    'priority': 'critical',
                    'category': 'reliability',
                    'method': method,
                    'issue': f"Success rate declining for {method}",
                    'recommendation': f"Reduce batch size for {method} and investigate error causes"
                })
        
        # Recommandations basées sur les goulots d'étranglement
        if analysis['bottleneck_analysis']['timeout_risk'] == 'high':
            recommendations.append({
                'priority': 'critical',
                'category': 'timeout_risk',
                'issue': "High risk of batch timeouts",
                'recommendation': "Reduce all batch sizes by 20-30% to prevent timeouts"
            })
        
        # Recommandations basées sur la comparaison avec l'optimal
        for method, comp in comparison.items():
            if comp['recommendation'] == 'decrease' and comp['difference'] > 10:
                recommendations.append({
                    'priority': 'medium',
                    'category': 'optimization',
                    'method': method,
                    'issue': f"Batch size for {method} significantly above optimal",
                    'recommendation': f"Reduce batch size for {method} from {comp['current_size']} to ~{comp['optimal_size']}"
                })
        
        analysis['optimization_recommendations'] = recommendations
        
        # Score de santé global (0-100)
        health_factors = []
        
        # Facteur de succès global
        overall_success_rate = sum(1 for entry in performance_history if entry['success']) / len(performance_history) * 100
        health_factors.append(min(100, overall_success_rate))
        
        # Facteur de performance (basé sur les durées)
        avg_duration = sum(entry['duration'] for entry in performance_history) / len(performance_history)
        performance_score = max(0, 100 - (avg_duration * 20))  # Pénalité pour durées élevées
        health_factors.append(performance_score)
        
        # Facteur de stabilité (moins de variations = mieux)
        duration_variance = sum((d - avg_duration) ** 2 for d in all_durations) / len(all_durations)
        stability_score = max(0, 100 - (duration_variance * 100))
        health_factors.append(stability_score)
        
        overall_health_score = sum(health_factors) / len(health_factors)
        
        analysis['health_score'] = {
            'overall': round(overall_health_score, 1),
            'factors': {
                'success_rate': round(health_factors[0], 1),
                'performance': round(health_factors[1], 1),
                'stability': round(health_factors[2], 1)
            },
            'status': 'excellent' if overall_health_score >= 90 else
                     'good' if overall_health_score >= 75 else
                     'fair' if overall_health_score >= 60 else
                     'poor'
        }
        
        return jsonify(format_api_response(
            analysis,
            message=f"Performance analysis completed - Health score: {overall_health_score:.1f}/100"
        ))
        
    except Exception as e:
        logger.error(f"Performance analysis failed: {e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Performance analysis failed: {e}"
        )), 500


# =============================================================================
# ROUTES DE CONFIGURATION
# =============================================================================

@batching_bp.route('/config', methods=['GET'])
def get_batching_config():
    """Récupération de la configuration actuelle du batching"""
    try:
        config = get_config()
        
        batching_config = {
            'enabled': config.batching.enabled,
            'adaptive_sizing': config.batching.adaptive_sizing,
            'batch_sizes': config.batching.batch_sizes.copy(),
            'timing': {
                'min_delay_between_batches': config.batching.min_delay_between_batches,
                'max_concurrent_batches': config.batching.max_concurrent_batches,
                'batch_timeout': config.batching.batch_timeout
            },
            'monitoring': {
                'track_response_times': config.batching.track_response_times,
                'max_acceptable_response_time': config.batching.max_acceptable_response_time,
                'reduce_batch_size_threshold': config.batching.reduce_batch_size_threshold,
                'emergency_fallback_threshold': config.batching.emergency_fallback_threshold
            },
            'defaults': {
                'optimal_batch_sizes': OPTIMAL_BATCH_SIZES.copy(),
                'conservative_batch_sizes': CONSERVATIVE_BATCH_SIZES.copy()
            }
        }
        
        # Ajouter l'état actuel si le batching est activé
        if config.batching.enabled:
            batch_manager = get_batch_manager()
            if batch_manager:
                # Récupérer les statistiques actuelles du batch manager
                current_stats = batch_manager.get_performance_stats()
                batching_config['current_performance'] = current_stats
        
        return jsonify(format_api_response(
            batching_config,
            message="Batching configuration retrieved successfully"
        ))
        
    except Exception as e:
        logger.error(f"Failed to get batching config: {e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Failed to retrieve batching configuration: {e}"
        )), 500


@batching_bp.route('/config', methods=['PUT'])
def update_batching_config():
    """Mise à jour de la configuration du batching"""
    try:
        config_data = request.get_json()
        
        if not config_data:
            return jsonify(format_api_response(
                None,
                success=False,
                message="No configuration data provided"
            )), 400
        
        # Validation de la configuration
        is_valid, validation_errors = validate_batch_config(config_data)
        
        if not is_valid:
            return jsonify(format_api_response(
                {'errors': validation_errors},
                success=False,
                message="Configuration validation failed"
            )), 400
        
        # Récupérer la configuration actuelle
        config = get_config()
        changes_made = []
        
        # Mise à jour du statut activé/désactivé
        if 'enabled' in config_data:
            old_enabled = config.batching.enabled
            new_enabled = bool(config_data['enabled'])
            
            if old_enabled != new_enabled:
                config.batching.enabled = new_enabled
                changes_made.append(f"Batching {'enabled' if new_enabled else 'disabled'}")
                logger.info(f"Batching {'enabled' if new_enabled else 'disabled'} via API")
        
        # Mise à jour des tailles de batch
        if 'batch_sizes' in config_data:
            batch_sizes = config_data['batch_sizes']
            old_sizes = config.batching.batch_sizes.copy()
            
            for method, new_size in batch_sizes.items():
                if method in old_sizes and old_sizes[method] != new_size:
                    config.batching.batch_sizes[method] = new_size
                    changes_made.append(f"Batch size for {method}: {old_sizes[method]} → {new_size}")
        
        # Mise à jour du sizing adaptatif
        if 'adaptive_sizing' in config_data:
            old_adaptive = config.batching.adaptive_sizing
            new_adaptive = bool(config_data['adaptive_sizing'])
            
            if old_adaptive != new_adaptive:
                config.batching.adaptive_sizing = new_adaptive
                changes_made.append(f"Adaptive sizing {'enabled' if new_adaptive else 'disabled'}")
        
        # Mise à jour des délais
        if 'min_delay_between_batches' in config_data:
            old_delay = config.batching.min_delay_between_batches
            new_delay = float(config_data['min_delay_between_batches'])
            
            if abs(old_delay - new_delay) > 0.01:  # Seuil de changement significatif
                config.batching.min_delay_between_batches = new_delay
                changes_made.append(f"Min delay between batches: {old_delay}s → {new_delay}s")
        
        # Mise à jour du timeout
        if 'batch_timeout' in config_data:
            old_timeout = config.batching.batch_timeout
            new_timeout = int(config_data['batch_timeout'])
            
            if old_timeout != new_timeout:
                config.batching.batch_timeout = new_timeout
                changes_made.append(f"Batch timeout: {old_timeout}s → {new_timeout}s")
        
        # Appliquer les changements au BatchManager si disponible
        if changes_made and config.batching.enabled:
            batch_manager = get_batch_manager()
            if batch_manager:
                try:
                    batch_manager.update_configuration(config.batching)
                    logger.info("BatchManager configuration updated successfully")
                except Exception as e:
                    logger.error(f"Failed to update BatchManager configuration: {e}")
                    changes_made.append("Warning: Failed to apply changes to active BatchManager")
        
        # Résultat de la mise à jour
        update_result = {
            'success': True,
            'changes_made': changes_made,
            'total_changes': len(changes_made),
            'updated_at': get_current_timestamp(),
            'new_configuration': {
                'enabled': config.batching.enabled,
                'adaptive_sizing': config.batching.adaptive_sizing,
                'batch_sizes': config.batching.batch_sizes.copy(),
                'min_delay_between_batches': config.batching.min_delay_between_batches,
                'batch_timeout': config.batching.batch_timeout
            }
        }
        
        if changes_made:
            message = f"Configuration updated successfully - {len(changes_made)} changes applied"
            logger.info(f"Batching configuration updated: {changes_made}")
        else:
            message = "No changes were needed - configuration is already up to date"
        
        return jsonify(format_api_response(
            update_result,
            message=message
        ))
        
    except Exception as e:
        logger.error(f"Failed to update batching config: {e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Failed to update batching configuration: {e}"
        )), 500


@batching_bp.route('/config/presets', methods=['GET'])
def get_config_presets():
    """Récupération des presets de configuration"""
    try:
        presets = {
            'conservative': {
                'name': 'Conservative',
                'description': 'Safe settings for rate-limited RPC endpoints',
                'enabled': True,
                'adaptive_sizing': True,
                'batch_sizes': CONSERVATIVE_BATCH_SIZES.copy(),
                'min_delay_between_batches': 0.5,
                'max_concurrent_batches': 1,
                'batch_timeout': 20,
                'use_case': 'Free RPC endpoints or strict rate limits'
            },
            'optimal': {
                'name': 'Optimal',
                'description': 'Balanced settings for good performance',
                'enabled': True,
                'adaptive_sizing': True,
                'batch_sizes': OPTIMAL_BATCH_SIZES.copy(),
                'min_delay_between_batches': 0.3,
                'max_concurrent_batches': 2,
                'batch_timeout': 25,
                'use_case': 'Paid RPC endpoints with moderate limits'
            },
            'aggressive': {
                'name': 'Aggressive',
                'description': 'Maximum performance settings',
                'enabled': True,
                'adaptive_sizing': True,
                'batch_sizes': {
                    method: min(size * 1.5, 100) for method, size in OPTIMAL_BATCH_SIZES.items()
                },
                'min_delay_between_batches': 0.1,
                'max_concurrent_batches': 3,
                'batch_timeout': 30,
                'use_case': 'Premium RPC endpoints with high limits'
            },
            'disabled': {
                'name': 'Disabled',
                'description': 'Disable batching completely',
                'enabled': False,
                'adaptive_sizing': False,
                'batch_sizes': {method: 1 for method in OPTIMAL_BATCH_SIZES.keys()},
                'min_delay_between_batches': 0.2,
                'max_concurrent_batches': 1,
                'batch_timeout': 15,
                'use_case': 'Debugging or troubleshooting'
            }
        }
        
        # Ajouter des recommandations basées sur la configuration actuelle
        config = get_config()
        current_config = {
            'enabled': config.batching.enabled,
            'batch_sizes': config.batching.batch_sizes,
            'min_delay_between_batches': config.batching.min_delay_between_batches
        }
        
        # Déterminer le preset le plus proche
        closest_preset = 'custom'
        min_difference = float('inf')
        
        for preset_name, preset_config in presets.items():
            if preset_config['enabled'] != current_config['enabled']:
                continue
            
            # Calculer la différence entre les tailles de batch
            batch_diff = 0
            for method in current_config['batch_sizes']:
                if method in preset_config['batch_sizes']:
                    batch_diff += abs(current_config['batch_sizes'][method] - 
                                    preset_config['batch_sizes'][method])
            
            # Différence de délai
            delay_diff = abs(current_config['min_delay_between_batches'] - 
                           preset_config['min_delay_between_batches']) * 10
            
            total_diff = batch_diff + delay_diff
            
            if total_diff < min_difference:
                min_difference = total_diff
                closest_preset = preset_name
        
        result = {
            'presets': presets,
            'current_closest_preset': closest_preset,
            'similarity_score': max(0, 100 - min_difference),
            'recommendations': []
        }
        
        # Ajouter des recommandations
        if closest_preset == 'custom':
            result['recommendations'].append(
                "Your configuration is custom - consider using a preset for easier management"
            )
        
        if not config.batching.enabled:
            result['recommendations'].append(
                "Batching is disabled - consider enabling it for better performance"
            )
        
        return jsonify(format_api_response(
            result,
            message=f"Configuration presets retrieved - closest match: {closest_preset}"
        ))
        
    except Exception as e:
        logger.error(f"Failed to get config presets: {e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Failed to retrieve configuration presets: {e}"
        )), 500


@batching_bp.route('/config/presets/<preset_name>', methods=['POST'])
def apply_config_preset(preset_name: str):
    """Application d'un preset de configuration"""
    try:
        # Récupérer les presets disponibles
        presets_response = get_config_presets()
        presets_data = presets_response.get_json()
        
        if not presets_data.get('success'):
            return jsonify(format_api_response(
                None,
                success=False,
                message="Failed to load available presets"
            )), 500
        
        presets = presets_data['data']['presets']
        
        if preset_name not in presets:
            available_presets = list(presets.keys())
            return jsonify(format_api_response(
                {'available_presets': available_presets},
                success=False,
                message=f"Unknown preset '{preset_name}'. Available presets: {available_presets}"
            )), 400
        
        preset_config = presets[preset_name]
        
        # Confirmation requise pour certains presets
        confirm = request.args.get('confirm', 'false').lower() == 'true'
        
        if preset_name in ['aggressive', 'disabled'] and not confirm:
            return jsonify(format_api_response(
                {
                    'preset': preset_config,
                    'warning': f"Applying '{preset_name}' preset requires confirmation",
                    'confirmation_required': True
                },
                success=False,
                message=f"Confirmation required for '{preset_name}' preset (confirm=true)"
            )), 400
        
        # Appliquer le preset
        config_to_apply = {
            'enabled': preset_config['enabled'],
            'adaptive_sizing': preset_config['adaptive_sizing'],
            'batch_sizes': preset_config['batch_sizes'],
            'min_delay_between_batches': preset_config['min_delay_between_batches'],
            'batch_timeout': preset_config['batch_timeout']
        }
        
        # Utiliser la fonction de mise à jour existante
        # Simuler une requête PUT avec les données du preset
        original_json = request.get_json
        request.get_json = lambda: config_to_apply
        
        try:
            update_response = update_batching_config()
            update_data = update_response.get_json()
            
            if update_data.get('success'):
                result = {
                    'preset_applied': preset_name,
                    'preset_description': preset_config['description'],
                    'changes_made': update_data['data']['changes_made'],
                    'applied_at': get_current_timestamp()
                }
                
                logger.info(f"Applied batching preset '{preset_name}': {preset_config['description']}")
                
                return jsonify(format_api_response(
                    result,
                    message=f"Successfully applied '{preset_name}' preset"
                ))
            else:
                return update_response
                
        finally:
            request.get_json = original_json
        
    except Exception as e:
        logger.error(f"Failed to apply preset '{preset_name}': {e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Failed to apply preset '{preset_name}': {e}"
        )), 500


# =============================================================================
# ROUTES DE CONTRÔLE ET ACTIONS
# =============================================================================

@batching_bp.route('/control/enable', methods=['POST'])
def enable_batching():
    """Activation du système de batching"""
    try:
        config = get_config()
        
        if config.batching.enabled:
            return jsonify(format_api_response(
                {'already_enabled': True},
                message="Batching is already enabled"
            ))
        
        # Activer le batching
        config.batching.enabled = True
        
        # Tenter de démarrer le BatchManager
        try:
            batch_manager = get_batch_manager()
            if batch_manager:
                # TODO: Méthode pour redémarrer/réinitialiser le BatchManager
                status = 'active'
            else:
                status = 'enabled_but_inactive'
        except Exception as e:
            logger.error(f"Failed to start BatchManager: {e}")
            status = 'enabled_with_errors'
        
        result = {
            'enabled': True,
            'status': status,
            'enabled_at': get_current_timestamp(),
            'configuration': {
                'adaptive_sizing': config.batching.adaptive_sizing,
                'batch_sizes': config.batching.batch_sizes.copy()
            }
        }
        
        logger.info("Batching enabled via API")
        
        return jsonify(format_api_response(
            result,
            message=f"Batching enabled successfully - Status: {status}"
        ))
        
    except Exception as e:
        logger.error(f"Failed to enable batching: {e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Failed to enable batching: {e}"
        )), 500


@batching_bp.route('/control/disable', methods=['POST'])
def disable_batching():
    """Désactivation du système de batching"""
    try:
        config = get_config()
        
        if not config.batching.enabled:
            return jsonify(format_api_response(
                {'already_disabled': True},
                message="Batching is already disabled"
            ))
        
        # Confirmation requise
        confirm = request.args.get('confirm', 'false').lower() == 'true'
        
        if not confirm:
            return jsonify(format_api_response(
                {
                    'confirmation_required': True,
                    'warning': "Disabling batching will reduce performance significantly"
                },
                success=False,
                message="Confirmation required to disable batching (confirm=true)"
            )), 400
        
        # Désactiver le batching
        config.batching.enabled = False
        
        # Arrêter le BatchManager si possible
        try:
            batch_manager = get_batch_manager()
            if batch_manager:
                # TODO: Méthode pour arrêter proprement le BatchManager
                pass
        except Exception as e:
            logger.warning(f"Error stopping BatchManager: {e}")
        
        result = {
            'enabled': False,
            'disabled_at': get_current_timestamp(),
            'fallback_mode': 'individual_requests',
            'performance_impact': 'Requests will be processed individually (slower)'
        }
        
        logger.warning("Batching disabled via API")
        
        return jsonify(format_api_response(
            result,
            message="Batching disabled - Performance will be reduced"
        ))
        
    except Exception as e:
        logger.error(f"Failed to disable batching: {e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Failed to disable batching: {e}"
        )), 500


@batching_bp.route('/control/reset-stats', methods=['POST'])
def reset_batching_stats():
    """Reset des statistiques de batching"""
    try:
        confirm = request.args.get('confirm', 'false').lower() == 'true'
        
        if not confirm:
            return jsonify(format_api_response(
                {'confirmation_required': True},
                success=False,
                message="Statistics reset requires confirmation (confirm=true)"
            )), 400
        
        # Sauvegarder les anciennes stats
        with _stats_lock:
            old_stats = _batching_stats.copy()
            
            # Reset des statistiques
            _batching_stats.update({
                'start_time': time.time(),
                'total_batches': 0,
                'successful_batches': 0,
                'failed_batches': 0,
                'total_items_processed': 0,
                'total_time_saved': 0.0,
                'performance_history': []
            })
        
        # Reset du BatchManager si disponible
        try:
            batch_manager = get_batch_manager()
            if batch_manager:
                batch_manager.reset_statistics()
        except Exception as e:
            logger.warning(f"Failed to reset BatchManager statistics: {e}")
        
        result = {
            'reset_at': get_current_timestamp(),
            'previous_stats': {
                'total_batches': old_stats['total_batches'],
                'successful_batches': old_stats['successful_batches'],
                'uptime_hours': (time.time() - old_stats['start_time']) / 3600
            },
            'new_baseline': {
                'start_time': _batching_stats['start_time'],
                'all_counters_reset': True
            }
        }
        
        logger.info("Batching statistics reset via API")
        
        return jsonify(format_api_response(
            result,
            message="Batching statistics reset successfully"
        ))
        
    except Exception as e:
        logger.error(f"Failed to reset batching stats: {e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Failed to reset statistics: {e}"
        )), 500


@batching_bp.route('/test', methods=['POST'])
def test_batching():
    """Test du système de batching avec données simulées"""
    try:
        config = get_config()
        
        if not config.batching.enabled:
            return jsonify(format_api_response(
                None,
                success=False,
                message="Cannot test batching - system is disabled"
            )), 400
        
        # Paramètres du test
        test_method = request.args.get('method', 'getMultipleAccounts')
        test_items = request.args.get('items', 10, type=int)
        test_items = clamp(test_items, 1, 50)  # Limiter pour éviter la surcharge
        
        if test_method not in OPTIMAL_BATCH_SIZES:
            available_methods = list(OPTIMAL_BATCH_SIZES.keys())
            return jsonify(format_api_response(
                {'available_methods': available_methods},
                success=False,
                message=f"Unknown test method '{test_method}'. Available: {available_methods}"
            )), 400
        
        test_start = time.time()
        
        try:
            batch_manager = get_batch_manager()
            if not batch_manager:
                return jsonify(format_api_response(
                    None,
                    success=False,
                    message="BatchManager not available for testing"
                )), 500
            
            # Simuler un test de batch
            # TODO: Implémenter la méthode de test dans BatchManager
            test_duration = 0.5  # Simulation
            
            # Enregistrer le résultat du test
            test_result = {
                'success': True,
                'method': test_method,
                'items_processed': test_items,
                'duration': test_duration,
                'time_saved': test_items * 0.1  # Estimation
            }
            
            update_batching_stats(test_result)
            
            result = {
                'test_completed': True,
                'method_tested': test_method,
                'items_processed': test_items,
                'duration_seconds': round(test_duration, 3),
                'estimated_time_saved': round(test_result['time_saved'], 3),
                'performance_rating': 'excellent' if test_duration < 1.0 else
                                   'good' if test_duration < 2.0 else
                                   'acceptable' if test_duration < 5.0 else 'poor',
                'batch_size_used': config.batching.batch_sizes.get(test_method, 1),
                'test_timestamp': get_current_timestamp()
            }
            
            logger.info(f"Batching test completed: {test_method} with {test_items} items in {test_duration:.3f}s")
            
            return jsonify(format_api_response(
                result,
                message=f"Batching test successful - {test_method} processed {test_items} items"
            ))
            
        except Exception as e:
            # Enregistrer l'échec du test
            test_result = {
                'success': False,
                'method': test_method,
                'items_processed': 0,
                'duration': time.time() - test_start
            }
            
            update_batching_stats(test_result)
            raise e
        
    except Exception as e:
        logger.error(f"Batching test failed: {e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Batching test failed: {e}"
        )), 500


# =============================================================================
# ROUTES DE DIAGNOSTICS ET TROUBLESHOOTING
# =============================================================================

@batching_bp.route('/diagnostics', methods=['GET'])
def get_batching_diagnostics():
    """Diagnostics complets du système de batching"""
    try:
        config = get_config()
        current_time = get_current_timestamp()
        
        diagnostics = {
            'timestamp': current_time,
            'system_status': {},
            'configuration_analysis': {},
            'performance_analysis': {},
            'health_checks': {},
            'recommendations': []
        }
        
        # 1. Status du système
        diagnostics['system_status'] = {
            'enabled': config.batching.enabled,
            'adaptive_sizing': config.batching.adaptive_sizing,
            'uptime_hours': (time.time() - _batching_stats['start_time']) / 3600
        }
        
        if config.batching.enabled:
            batch_manager = get_batch_manager()
            diagnostics['system_status']['batch_manager_available'] = batch_manager is not None
        
        # 2. Analyse de configuration
        config_issues = []
        
        # Vérifier les tailles de batch
        for method, size in config.batching.batch_sizes.items():
            optimal_size = OPTIMAL_BATCH_SIZES.get(method, 10)
            conservative_size = CONSERVATIVE_BATCH_SIZES.get(method, 5)
            
            if size > optimal_size * 1.5:
                config_issues.append(f"Batch size for {method} is very high ({size} vs optimal {optimal_size})")
            elif size < conservative_size * 0.5:
                config_issues.append(f"Batch size for {method} is very low ({size} vs conservative {conservative_size})")
        
        # Vérifier les délais
        if config.batching.min_delay_between_batches > 2.0:
            config_issues.append("Very high delay between batches - may reduce performance")
        elif config.batching.min_delay_between_batches < 0.05:
            config_issues.append("Very low delay between batches - risk of rate limiting")
        
        diagnostics['configuration_analysis'] = {
            'issues_found': len(config_issues),
            'issues': config_issues,
            'batch_sizes_analysis': {
                method: {
                    'current': size,
                    'optimal': OPTIMAL_BATCH_SIZES.get(method, 10),
                    'status': 'ok' if CONSERVATIVE_BATCH_SIZES.get(method, 5) <= size <= OPTIMAL_BATCH_SIZES.get(method, 10) else 'review'
                }
                for method, size in config.batching.batch_sizes.items()
            }
        }
        
        # 3. Analyse de performance
        with _stats_lock:
            performance_history = _batching_stats['performance_history'].copy()
            global_stats = _batching_stats.copy()
        
        if performance_history:
            recent_performance = performance_history[-10:] if len(performance_history) >= 10 else performance_history
            
            success_rate = sum(1 for entry in recent_performance if entry['success']) / len(recent_performance) * 100
            avg_duration = sum(entry['duration'] for entry in recent_performance) / len(recent_performance)
            avg_items = sum(entry['items'] for entry in recent_performance) / len(recent_performance)
            
            performance_status = 'excellent' if success_rate >= 95 and avg_duration < 2.0 else \
                               'good' if success_rate >= 85 and avg_duration < 5.0 else \
                               'fair' if success_rate >= 70 else 'poor'
            
            diagnostics['performance_analysis'] = {
                'recent_success_rate': round(success_rate, 1),
                'recent_avg_duration': round(avg_duration, 3),
                'recent_avg_items_per_batch': round(avg_items, 1),
                'performance_status': performance_status,
                'total_batches_processed': global_stats['total_batches'],
                'total_items_processed': global_stats['total_items_processed'],
                'estimated_time_saved_hours': round(global_stats['total_time_saved'] / 3600, 2)
            }
        else:
            diagnostics['performance_analysis'] = {
                'status': 'no_data',
                'message': 'No performance data available'
            }
        
        # 4. Health checks
        health_checks = []
        
        # Check 1: Configuration cohérente
        if not config_issues:
            health_checks.append({'name': 'Configuration', 'status': 'ok', 'message': 'Configuration is optimal'})
        else:
            health_checks.append({'name': 'Configuration', 'status': 'warning', 'message': f'{len(config_issues)} configuration issues found'})
        
        # Check 2: Performance récente
        if 'performance_analysis' in diagnostics and 'performance_status' in diagnostics['performance_analysis']:
            perf_status = diagnostics['performance_analysis']['performance_status']
            if perf_status in ['excellent', 'good']:
                health_checks.append({'name': 'Performance', 'status': 'ok', 'message': f'Performance is {perf_status}'})
            else:
                health_checks.append({'name': 'Performance', 'status': 'warning', 'message': f'Performance is {perf_status}'})
        else:
            health_checks.append({'name': 'Performance', 'status': 'unknown', 'message': 'No performance data available'})
        
        # Check 3: Système actif
        if config.batching.enabled:
            batch_manager = get_batch_manager()
            if batch_manager:
                health_checks.append({'name': 'System', 'status': 'ok', 'message': 'Batching system is active'})
            else:
                health_checks.append({'name': 'System', 'status': 'error', 'message': 'Batching enabled but BatchManager unavailable'})
        else:
            health_checks.append({'name': 'System', 'status': 'info', 'message': 'Batching is disabled'})
        
        diagnostics['health_checks'] = health_checks
        
        # 5. Recommandations
        recommendations = []
        
        # Recommandations basées sur la configuration
        for issue in config_issues:
            recommendations.append({
                'priority': 'medium',
                'category': 'configuration',
                'issue': issue,
                'action': 'Review and adjust batch configuration'
            })
        
        # Recommandations basées sur la performance
        if 'performance_status' in diagnostics.get('performance_analysis', {}):
            perf_status = diagnostics['performance_analysis']['performance_status']
            if perf_status == 'poor':
                recommendations.append({
                    'priority': 'high',
                    'category': 'performance',
                    'issue': 'Poor batching performance detected',
                    'action': 'Reduce batch sizes and increase delays between batches'
                })
            elif perf_status == 'fair':
                recommendations.append({
                    'priority': 'medium',
                    'category': 'performance',
                    'issue': 'Suboptimal batching performance',
                    'action': 'Fine-tune batch sizes based on RPC endpoint capabilities'
                })
        
        # Recommandation générale si pas de données
        if not performance_history:
            recommendations.append({
                'priority': 'low',
                'category': 'monitoring',
                'issue': 'No performance history available',
                'action': 'Run system for a while to collect performance data'
            })
        
        diagnostics['recommendations'] = recommendations
        
        # Score de santé global
        health_score = 0
        total_checks = len(health_checks)
        
        for check in health_checks:
            if check['status'] == 'ok':
                health_score += 100
            elif check['status'] == 'warning':
                health_score += 50
            elif check['status'] == 'info':
                health_score += 75
            # error = 0 points
        
        overall_health = health_score / total_checks if total_checks > 0 else 0
        
        diagnostics['overall_health'] = {
            'score': round(overall_health, 1),
            'status': 'healthy' if overall_health >= 80 else
                     'warning' if overall_health >= 60 else
                     'critical',
            'checks_passed': sum(1 for check in health_checks if check['status'] == 'ok'),
            'total_checks': total_checks
        }
        
        return jsonify(format_api_response(
            diagnostics,
            message=f"Diagnostics completed - Health score: {overall_health:.1f}/100"
        ))
        
    except Exception as e:
        logger.error(f"Batching diagnostics failed: {e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message=f"Failed to run batching diagnostics: {e}"
        )), 500


# =============================================================================
# GESTIONNAIRES D'ERREURS
# =============================================================================

@batching_bp.errorhandler(BatchingError)
def handle_batching_error(error):
    """Gestionnaire spécifique pour les erreurs de batching"""
    logger.error(f"Batching error: {error}")
    return jsonify(format_api_response(
        None,
        success=False,
        message=f"Batching error: {error}"
    )), 500


@batching_bp.errorhandler(400)
def bad_request(error):
    """Gestionnaire d'erreur pour les requêtes malformées"""
    return jsonify(format_api_response(
        None,
        success=False,
        message="Bad request - Invalid parameters"
    )), 400


@batching_bp.errorhandler(500)
def internal_error(error):
    """Gestionnaire d'erreur serveur interne"""
    logger.error(f"Internal error in batching routes: {error}")
    return jsonify(format_api_response(
        None,
        success=False,
        message="Internal server error"
    )), 500


# =============================================================================
# HOOKS ET MIDDLEWARES
# =============================================================================

@batching_bp.before_request
def before_batching_request():
    """Exécuté avant chaque requête batching"""
    # Vérifier que la configuration est chargée
    try:
        get_config()
    except Exception as e:
        logger.error(f"Configuration error in batching routes: {e}")


@batching_bp.after_request
def after_batching_request(response):
    """Exécuté après chaque requête batching"""
    # Ajouter des headers spécifiques au batching
    response.headers['X-Batching-API'] = 'v1'
    return response


# =============================================================================
# EXPORT
# =============================================================================

__all__ = ['batching_bp', 'update_batching_stats', 'get_batch_manager']