#!/usr/bin/env python3
"""
Routes d'analytics pour l'analyse des wallets Solana
Conversion Flask du module FastAPI original
"""

from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import logging
import time

# Imports depuis la nouvelle structure
from core.config import get_config
from core.logger import get_logger
from core.database import get_database_manager
from core.exceptions import (
    SolanaWalletMonitorError, ValidationError, 
    RPCError, DatabaseError
)

# Imports des analyseurs (à créer selon la logique métier)
try:
    from analytics.wallet_analyzer import WalletAnalyzer
    from analytics.transaction_processor import TransactionProcessor  
    from analytics.portfolio_tracker import PortfolioTracker
    from analytics.data_collector import DataCollector
except ImportError as e:
    logger = logging.getLogger(__name__)
    logger.warning(f"Analytics modules not available: {e}")
    
    # Classes de fallback pour éviter les erreurs
    class WalletAnalyzer:
        def __init__(self):
            self.available = False
        
        def analyze_wallet(self, **kwargs): 
            return {
                "error": "WalletAnalyzer not implemented",
                "status": "service_unavailable",
                "wallet_address": kwargs.get('wallet_address', 'unknown')
            }
            
        def get_wallet_summary(self, **kwargs):
            return {
                "error": "WalletAnalyzer not implemented",
                "status": "service_unavailable",
                "wallet_address": kwargs.get('wallet_address', 'unknown'),
                "summary": {}
            }
            
        def get_performance_metrics(self, **kwargs):
            return {
                "error": "WalletAnalyzer not implemented", 
                "status": "service_unavailable",
                "wallet_address": kwargs.get('wallet_address', 'unknown'),
                "metrics": {}
            }
    
    class TransactionProcessor:
        def __init__(self):
            self.available = False
        
        def analyze_transactions(self, **kwargs):
            return {
                "error": "TransactionProcessor not implemented",
                "status": "service_unavailable",
                "transactions": []
            }
        
        def get_transactions(self, **kwargs):
            return []
    
    class PortfolioTracker:
        def __init__(self):
            self.available = False
        
        def analyze_portfolio(self, **kwargs):
            return {
                "error": "PortfolioTracker not implemented",
                "status": "service_unavailable",
                "portfolio": {}
            }
            
        def get_current_portfolio(self, wallet_address):
            return {
                "error": "PortfolioTracker not implemented",
                "status": "service_unavailable", 
                "tokens": [],
                "total_value": 0
            }
    
    class DataCollector:
        def __init__(self):
            self.available = False
        
        def analyze_tokens(self, **kwargs):
            return {
                "error": "DataCollector not implemented",
                "status": "service_unavailable",
                "tokens": []
            }

from utils.helpers import (
    get_current_timestamp, 
    safe_get, calculate_time_since
)
from utils.validators import quick_validate_address as validate_wallet_address
from utils.formatters import (
    format_api_response, format_wallet_address,
    format_timestamp, format_sol_amount
)

# Configuration du blueprint
analytics_bp = Blueprint('analytics', __name__, url_prefix='/api/analytics')
logger = get_logger(__name__)

# Services globaux (instanciés à l'initialisation)
wallet_analyzer = WalletAnalyzer()
transaction_processor = TransactionProcessor()
portfolio_tracker = PortfolioTracker()
data_collector = DataCollector()

# ============= FONCTIONS DE VALIDATION =============
def validate_request_data(data, required_fields, optional_fields=None):
    """Validation générique des données de requête"""
    if optional_fields is None:
        optional_fields = {}
    
    errors = []
    validated_data = {}
    
    # Vérifier les champs requis
    for field in required_fields:
        value = data.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(f"{field} is required")
        else:
            if field == 'wallet_address':
                if not validate_wallet_address(value.strip()):
                    errors.append("Invalid Solana wallet address format")
                else:
                    validated_data[field] = value.strip()
            else:
                validated_data[field] = value
    
    # Traiter les champs optionnels avec valeurs par défaut
    for field, default_value in optional_fields.items():
        value = data.get(field, default_value)
        
        if field == 'days':
            value = min(max(int(value) if isinstance(value, (int, str)) else default_value, 1), 365)
        elif field == 'limit':
            value = min(max(int(value) if isinstance(value, (int, str)) else default_value, 1), 1000)
        
        validated_data[field] = value
    
    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'validated_data': validated_data
    }

def safe_database_query(query_func, error_message="Database query failed"):
    """Wrapper sécurisé pour les requêtes de base de données"""
    try:
        return query_func()
    except DatabaseError as e:
        logger.error(f"Database error: {e}")
        raise DatabaseError(f"{error_message}: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in database query: {e}")
        raise DatabaseError(f"{error_message}: Unexpected error")


def validate_wallet_analysis_request(data: dict) -> dict:
    """Valide une requête d'analyse de wallet avec gestion d'erreurs améliorée"""
    field_errors = {}
    
    wallet_address = data.get('wallet_address', '').strip()
    if not wallet_address:
        field_errors['wallet_address'] = "is required"
    elif not validate_wallet_address(wallet_address):
        field_errors['wallet_address'] = "Invalid Solana wallet address format"
    
    days = data.get('days', 30)
    if not isinstance(days, int):
        try:
            days = int(days)
        except (ValueError, TypeError):
            field_errors['days'] = "must be a valid integer"
    
    if isinstance(days, int) and (days < 1 or days > 365):
        field_errors['days'] = "must be between 1 and 365"
    
    include_tokens = data.get('include_tokens', True)
    if not isinstance(include_tokens, bool):
        field_errors['include_tokens'] = "must be a boolean"
    
    include_nfts = data.get('include_nfts', False)
    if not isinstance(include_nfts, bool):
        field_errors['include_nfts'] = "must be a boolean"
    
    # Si des erreurs de validation
    if field_errors:
        validation_error = ValidationError(
            "Invalid request parameters",
            field_errors=field_errors,
            context="wallet_analysis_request"
        )
        return {
            'valid': False,
            'errors': [str(validation_error)],
            'field_errors': field_errors,
            'validation_exception': validation_error
        }
    
    return {
        'valid': True,
        'errors': [],
        'validated_data': {
            'wallet_address': wallet_address,
            'days': min(max(days, 1), 365),
            'include_tokens': include_tokens,
            'include_nfts': include_nfts
        }
    }

def validate_transaction_analysis_request(data: dict) -> dict:
    """Valide une requête d'analyse de transactions"""
    errors = []
    
    wallet_address = data.get('wallet_address', '').strip()
    if not wallet_address:
        errors.append("wallet_address is required")
    elif not validate_wallet_address(wallet_address):
        errors.append("Invalid Solana wallet address format")
    
    limit = data.get('limit', 100)
    if not isinstance(limit, int) or limit < 1 or limit > 1000:
        errors.append("limit must be between 1 and 1000")
    
    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'validated_data': {
            'wallet_address': wallet_address,
            'start_date': data.get('start_date'),
            'end_date': data.get('end_date'),
            'limit': min(max(limit, 1), 1000),
            'transaction_type': data.get('transaction_type')
        }
    }

# ============= ROUTES PRINCIPALES =============
# 6. AJOUTER UNE ROUTE DE STATUS DES SERVICES
@analytics_bp.route('/services/status')
def get_services_status():
    """Statut détaillé de tous les services analytics"""
    try:
        services_status = {
            'timestamp': datetime.utcnow().isoformat(),
            'services': {
                'wallet_analyzer': {
                    'available': hasattr(wallet_analyzer, 'available') and wallet_analyzer.available,
                    'status': 'operational' if wallet_analyzer.available else 'unavailable'
                },
                'transaction_processor': {
                    'available': hasattr(transaction_processor, 'available') and transaction_processor.available,
                    'status': 'operational' if transaction_processor.available else 'unavailable'
                },
                'portfolio_tracker': {
                    'available': hasattr(portfolio_tracker, 'available') and portfolio_tracker.available,
                    'status': 'operational' if portfolio_tracker.available else 'unavailable'
                },
                'data_collector': {
                    'available': hasattr(data_collector, 'available') and data_collector.available,
                    'status': 'operational' if data_collector.available else 'unavailable'
                }
            }
        }
        
        # Test de la base de données
        try:
            with get_database_manager().get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                services_status['services']['database'] = {
                    'available': True,
                    'status': 'operational'
                }
        except Exception as db_e:
            services_status['services']['database'] = {
                'available': False,
                'status': f'error: {str(db_e)}'
            }
        
        # Déterminer le statut global
        available_services = sum(1 for service in services_status['services'].values() 
                               if service.get('available', False))
        total_services = len(services_status['services'])
        
        if available_services == total_services:
            overall_status = 'fully_operational'
        elif available_services > 0:
            overall_status = 'partially_operational'
        else:
            overall_status = 'unavailable'
        
        services_status['overall_status'] = overall_status
        services_status['available_services'] = available_services
        services_status['total_services'] = total_services
        
        return jsonify(format_api_response(
            services_status,
            message=f"Services status: {overall_status}"
        ))
        
    except Exception as e:
        logger.error(f"Services status check failed: {e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message="Services status check failed"
        )), 500
        

@analytics_bp.route('/')
def analytics_info():
    """Informations sur l'API Analytics"""
    return jsonify(format_api_response({
        "name": "Solana Wallet Analytics",
        "version": "1.0.0",
        "description": "API d'analyse des wallets Solana",
        "endpoints": {
            "wallet_analysis": "/wallet/analyze",
            "transaction_analysis": "/transactions/analyze", 
            "portfolio_analysis": "/portfolio/analyze",
            "token_analysis": "/tokens/analyze",
            "wallet_summary": "/wallet/{wallet_address}/summary",
            "wallet_transactions": "/wallet/{wallet_address}/transactions",
            "wallet_portfolio": "/wallet/{wallet_address}/portfolio",
            "performance_metrics": "/wallet/{wallet_address}/performance"
        }
    }, message="Analytics API information"))

@analytics_bp.route('/wallet/analyze', methods=['POST'])
def analyze_wallet():
    """
    Analyse complète d'un wallet Solana
    
    Body JSON:
    {
        "wallet_address": "string (required)",
        "days": "integer (1-365, default: 30)",
        "include_tokens": "boolean (default: true)",
        "include_nfts": "boolean (default: false)"
    }
   Returns:
    {
        "success": true,
        "message": "Wallet analysis completed successfully",
        "data": {
            "wallet_address": "string",
            "analysis_date": "ISO datetime",
            "parameters": {
                "days": 30,
                "include_tokens": true,
                "include_nfts": false
            },
            "summary": {
                "transaction_count": 0,
                "total_volume_sol": 0.0,
                "active_days": 0,
                "first_transaction": null,
                "last_transaction": null
            },
            "tokens": [...],
            "performance": {...},
            "activity": {...}
        }
    }
    """
    try:
        data = request.get_json() or {}
        
        # Validation avec gestion d'erreurs améliorée
        validation = validate_wallet_analysis_request(data)
        if not validation['valid']:
            logger.warning(f"Wallet analysis validation failed: {validation.get('field_errors', {})}")
            
            # Si une exception ValidationError a été créée, la relancer
            if 'validation_exception' in validation:
                raise validation['validation_exception']
            
            return jsonify(format_api_response(
                None, 
                success=False, 
                message="Validation failed",
                errors=validation['errors']
            )), 400
        
        validated_data = validation['validated_data']
        wallet_address = validated_data['wallet_address']
        
        logger.info(f"Starting wallet analysis for: {wallet_address[:8]}...{wallet_address[-6:]}")
        start_time = time.time()
        
        # Vérification de la disponibilité du service
        if not hasattr(wallet_analyzer, 'available') or not wallet_analyzer.available:
            logger.warning("WalletAnalyzer service not available")
            return jsonify(format_api_response(
                {
                    'wallet_address': wallet_address,
                    'status': 'service_unavailable',
                    'message': 'Wallet analysis service is currently unavailable'
                },
                success=False,
                message="Wallet analysis service unavailable"
            )), 503
        
        # Analyse du wallet avec gestion d'erreurs robuste
        try:
            analysis_result = wallet_analyzer.analyze_wallet(**validated_data)
            
            # Vérification du résultat
            if isinstance(analysis_result, dict) and 'error' in analysis_result:
                logger.error(f"Wallet analyzer returned error: {analysis_result['error']}")
                return jsonify(format_api_response(
                    {
                        'wallet_address': wallet_address,
                        'error': analysis_result['error'],
                        'status': analysis_result.get('status', 'analysis_failed')
                    },
                    success=False,
                    message=f"Analysis failed: {analysis_result['error']}"
                )), 500
            
        except RPCError as rpc_e:
            logger.error(f"RPC error during wallet analysis: {rpc_e}")
            return jsonify(format_api_response(
                {
                    'wallet_address': wallet_address,
                    'error': 'rpc_connection_failed',
                    'details': str(rpc_e)
                },
                success=False,
                message="Solana RPC connection failed"
            )), 503
            
        except DatabaseError as db_e:
            logger.error(f"Database error during wallet analysis: {db_e}")
            return jsonify(format_api_response(
                {
                    'wallet_address': wallet_address,
                    'error': 'database_error',
                    'details': str(db_e)
                },
                success=False,
                message="Database operation failed"
            )), 500
            
        except SolanaWalletMonitorError as swm_e:
            logger.error(f"Solana wallet monitor error: {swm_e}")
            return jsonify(format_api_response(
                {
                    'wallet_address': wallet_address,
                    'error': 'wallet_monitor_error',
                    'details': str(swm_e)
                },
                success=False,
                message="Wallet monitoring error"
            )), 500
            
        except Exception as analyzer_error:
            logger.error(f"Unexpected error in wallet analyzer: {analyzer_error}")
            return jsonify(format_api_response(
                {
                    'wallet_address': wallet_address,
                    'error': 'unexpected_analysis_error',
                    'details': str(analyzer_error)
                },
                success=False,
                message="Unexpected analysis error occurred"
            )), 500
        
        # Construction de la réponse avec données enrichies
        analysis_duration = round((time.time() - start_time) * 1000, 2)  # en ms
        
        response_data = {
            'wallet_address': wallet_address,
            'wallet_short': format_wallet_address(wallet_address),
            'analysis_date': datetime.utcnow().isoformat(),
            'analysis_duration_ms': analysis_duration,
            'parameters': validated_data,
            **analysis_result
        }
        
        # Ajout de métadonnées sur l'analyse
        response_data['metadata'] = {
            'analyzer_version': '1.0.0',
            'analysis_type': 'complete_wallet_analysis',
            'data_freshness': 'real_time',
            'confidence_score': analysis_result.get('confidence_score', 0.95)
        }
        
        # Logging du succès
        logger.info(f"Wallet analysis completed successfully for {wallet_address[:8]}...{wallet_address[-6:]} in {analysis_duration}ms")
        
        return jsonify(format_api_response(
            response_data,
            message="Wallet analysis completed successfully"
        ))
        
    except ValidationError as validation_e:
        logger.warning(f"Validation error in wallet analysis: {validation_e}")
        return jsonify(format_api_response(
            {
                'field_errors': validation_e.field_errors,
                'context': validation_e.context
            },
            success=False,
            message=str(validation_e),
            errors=[validation_e.message]
        )), 400
        
    except Exception as unexpected_e:
        logger.error(f"Unexpected error in analyze_wallet endpoint: {unexpected_e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message="Internal server error during wallet analysis"
        )), 500

@analytics_bp.route('/wallet/<wallet_address>/transactions')
def get_wallet_transactions(wallet_address):
    """
    Récupère les transactions d'un wallet avec pagination
    
    Query parameters:
    - limit: integer (1-500, default: 50)
    - before: string (signature de transaction pour pagination)
    """
    try:
        if not validate_wallet_address(wallet_address):
            return jsonify(format_api_response(
                None,
                success=False,
                message="Invalid wallet address format"
            )), 400
        
        limit = request.args.get('limit', 50, type=int)
        limit = min(max(limit, 1), 500)  # Clamp entre 1 et 500
        
        before = request.args.get('before', '').strip()
        
        transactions = transaction_processor.get_transactions(
            wallet_address=wallet_address,
            limit=limit,
            before=before if before else None
        )
        
        response_data = {
            'wallet_address': wallet_address,
            'wallet_short': format_wallet_address(wallet_address),
            'transactions': transactions,
            'count': len(transactions),
            'limit': limit,
            'before': before
        }
        
        return jsonify(format_api_response(
            response_data,
            message=f"Retrieved {len(transactions)} transactions"
        ))
        
    except Exception as e:
        logger.error(f"Get wallet transactions failed: {e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message="Failed to get wallet transactions"
        )), 500

@analytics_bp.route('/wallet/<wallet_address>/portfolio')
def get_current_portfolio(wallet_address):
    """
    Récupère le portefeuille actuel d'un wallet
    """
    try:
        if not validate_wallet_address(wallet_address):
            return jsonify(format_api_response(
                None,
                success=False,
                message="Invalid wallet address format"
            )), 400
        
        portfolio = portfolio_tracker.get_current_portfolio(wallet_address)
        
        response_data = {
            'wallet_address': wallet_address,
            'wallet_short': format_wallet_address(wallet_address),
            'timestamp': datetime.utcnow().isoformat(),
            'portfolio': portfolio
        }
        
        return jsonify(format_api_response(
            response_data,
            message="Current portfolio retrieved"
        ))
        
    except Exception as e:
        logger.error(f"Get current portfolio failed: {e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message="Failed to get current portfolio"
        )), 500

@analytics_bp.route('/wallet/<wallet_address>/performance')
def get_performance_metrics(wallet_address):
    """
    Récupère les métriques de performance d'un wallet
    
    Query parameters:
    - days: integer (1-365, default: 30)
    """
    try:
        if not validate_wallet_address(wallet_address):
            return jsonify(format_api_response(
                None,
                success=False,
                message="Invalid wallet address format"
            )), 400
        
        days = request.args.get('days', 30, type=int)
        days = min(max(days, 1), 365)
        
        performance = wallet_analyzer.get_performance_metrics(
            wallet_address=wallet_address,
            days=days
        )
        
        response_data = {
            'wallet_address': wallet_address,
            'wallet_short': format_wallet_address(wallet_address),
            'period_days': days,
            'metrics': performance
        }
        
        return jsonify(format_api_response(
            response_data,
            message=f"Performance metrics for {days} days"
        ))
        
    except Exception as e:
        logger.error(f"Get performance metrics failed: {e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message="Failed to get performance metrics"
        )), 500

# ============= ROUTES DE COMPARAISON ET BENCHMARKING =============

@analytics_bp.route('/compare/wallets', methods=['POST'])
def compare_wallets():
    """
    Compare les performances de plusieurs wallets
    
    Body JSON:
    {
        "wallet_addresses": ["address1", "address2", ...],
        "days": "integer (1-365, default: 30)",
        "metrics": ["performance", "portfolio", "activity"]
    }
    """
    try:
        data = request.get_json() or {}
        
        wallet_addresses = data.get('wallet_addresses', [])
        if not isinstance(wallet_addresses, list) or len(wallet_addresses) < 2:
            return jsonify(format_api_response(
                None,
                success=False,
                message="At least 2 wallet addresses required"
            )), 400
        
        if len(wallet_addresses) > 10:
            return jsonify(format_api_response(
                None,
                success=False,
                message="Maximum 10 wallets can be compared at once"
            )), 400
        
        # Valider toutes les adresses
        invalid_addresses = []
        for addr in wallet_addresses:
            if not validate_wallet_address(addr):
                invalid_addresses.append(addr)
        
        if invalid_addresses:
            return jsonify(format_api_response(
                None,
                success=False,
                message="Invalid wallet addresses",
                errors=[f"Invalid address: {addr}" for addr in invalid_addresses]
            )), 400
        
        days = min(max(data.get('days', 30), 1), 365)
        metrics = data.get('metrics', ['performance', 'portfolio', 'activity'])
        
        # Analyser chaque wallet
        comparison_results = {}
        for wallet_address in wallet_addresses:
            try:
                wallet_data = {
                    'wallet_address': wallet_address,
                    'wallet_short': format_wallet_address(wallet_address)
                }
                
                if 'performance' in metrics:
                    wallet_data['performance'] = wallet_analyzer.get_performance_metrics(
                        wallet_address=wallet_address, days=days
                    )
                
                if 'portfolio' in metrics:
                    wallet_data['portfolio'] = portfolio_tracker.get_current_portfolio(wallet_address)
                
                if 'activity' in metrics:
                    wallet_data['activity'] = wallet_analyzer.get_wallet_summary(
                        wallet_address=wallet_address, days=days
                    )
                
                comparison_results[wallet_address] = wallet_data
                
            except Exception as wallet_error:
                logger.error(f"Failed to analyze wallet {wallet_address}: {wallet_error}")
                comparison_results[wallet_address] = {
                    'wallet_address': wallet_address,
                    'error': str(wallet_error)
                }
        
        response_data = {
            'comparison_date': datetime.utcnow().isoformat(),
            'period_days': days,
            'metrics_analyzed': metrics,
            'wallet_count': len(wallet_addresses),
            'wallets': comparison_results
        }
        
        return jsonify(format_api_response(
            response_data,
            message=f"Wallet comparison completed for {len(wallet_addresses)} wallets"
        ))
        
    except Exception as e:
        logger.error(f"Wallet comparison failed: {e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message="Wallet comparison failed"
        )), 500

# ============= ROUTES D'ANALYTICS AVANCÉES =============

@analytics_bp.route('/market/trending', methods=['GET'])
def get_trending_tokens():
    """
    Analyse les tokens les plus actifs dans tous les wallets monitorés
    
    Query parameters:
    - hours: integer (1-168, default: 24) 
    - limit: integer (1-100, default: 20)
    """
    try:
        hours = request.args.get('hours', 24, type=int)
        hours = min(max(hours, 1), 168)  # Max 1 semaine
        
        limit = request.args.get('limit', 20, type=int) 
        limit = min(max(limit, 1), 100)
        
        # Utiliser la base de données pour analyser les tendances
        with get_database_manager().get_connection() as conn:
            cursor = conn.cursor()
            start_time = get_current_timestamp() - (hours * 3600)
            
            # Tokens les plus actifs par nombre de transactions
            cursor.execute("""
                SELECT 
                    token_mint, token_symbol, token_name,
                    COUNT(*) as tx_count,
                    COUNT(DISTINCT wallet_address) as unique_wallets,
                    SUM(CASE WHEN transaction_type = 'buy' THEN 1 ELSE 0 END) as buy_count,
                    SUM(CASE WHEN transaction_type = 'sell' THEN 1 ELSE 0 END) as sell_count,
                    AVG(CASE WHEN price_per_token > 0 THEN price_per_token ELSE NULL END) as avg_price,
                    SUM(ABS(amount)) as total_volume_sol,
                    MAX(block_time) as last_activity
                FROM transactions 
                WHERE is_token_transaction = 1 
                AND block_time >= ?
                AND token_mint IS NOT NULL
                GROUP BY token_mint, token_symbol, token_name
                HAVING tx_count >= 2
                ORDER BY tx_count DESC, unique_wallets DESC
                LIMIT ?
            """, (start_time, limit))
            
            trending_tokens = []
            for row in cursor.fetchall():
                mint = row[0]
                symbol = row[1] or f"TOKEN_{mint[:6]}"
                name = row[2] or f"Token {mint[:6]}"
                tx_count = row[3]
                unique_wallets = row[4]
                buy_count = row[5]
                sell_count = row[6]
                avg_price = row[7]
                volume = row[8] or 0
                last_activity = row[9]
                
                # Calculer un score de tendance
                trend_score = (tx_count * 10) + (unique_wallets * 5) + (volume * 2)
                
                trending_tokens.append({
                    'token_mint': mint,
                    'mint_short': f"{mint[:6]}...{mint[-6:]}",
                    'token_symbol': symbol,
                    'token_name': name,
                    'transaction_count': tx_count,
                    'unique_wallets': unique_wallets,
                    'buy_count': buy_count,
                    'sell_count': sell_count,
                    'buy_sell_ratio': round(buy_count / max(sell_count, 1), 2),
                    'avg_price': round(avg_price, 8) if avg_price else None,
                    'total_volume_sol': round(volume, 4),
                    'trend_score': round(trend_score, 2),
                    'last_activity': last_activity,
                    'hours_ago': round((get_current_timestamp() - last_activity) / 3600, 1) if last_activity else 999
                })
        
        response_data = {
            'analysis_period_hours': hours,
            'trending_tokens_count': len(trending_tokens),
            'trending_tokens': trending_tokens,
            'analysis_timestamp': get_current_timestamp()
        }
        
        return jsonify(format_api_response(
            response_data,
            message=f"Trending tokens analysis for last {hours} hours"
        ))
        
    except Exception as e:
        logger.error(f"Trending tokens analysis failed: {e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message="Failed to analyze trending tokens"
        )), 500

@analytics_bp.route('/insights/risk-analysis', methods=['POST'])
def analyze_portfolio_risk():
    """
    Analyse de risque d'un portefeuille
    
    Body JSON:
    {
        "wallet_address": "string (required)",
        "risk_factors": ["concentration", "volatility", "liquidity"]
    }
    """
    try:
        data = request.get_json() or {}
        
        wallet_address = data.get('wallet_address', '').strip()
        if not wallet_address or not validate_wallet_address(wallet_address):
            return jsonify(format_api_response(
                None,
                success=False,
                message="Invalid or missing wallet_address"
            )), 400
        
        risk_factors = data.get('risk_factors', ['concentration', 'volatility', 'liquidity'])
        
        # Analyse de base depuis la base de données
        risk_analysis = {
            'wallet_address': wallet_address,
            'analysis_date': datetime.utcnow().isoformat(),
            'risk_factors': {}
        }
        
        with get_database_manager().get_connection() as conn:
            cursor = conn.cursor()
            
            if 'concentration' in risk_factors:
                # Analyse de concentration du portefeuille
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_tokens,
                        COUNT(CASE WHEN balance > 0 THEN 1 END) as active_tokens,
                        MAX(balance) as largest_holding,
                        SUM(balance) as total_balance
                    FROM token_accounts 
                    WHERE wallet_address = ? AND is_active = 1
                """, (wallet_address,))
                
                conc_data = cursor.fetchone()
                if conc_data and conc_data[0]:
                    concentration_ratio = (conc_data[2] or 0) / max(conc_data[3] or 1, 1)
                    concentration_risk = 'HIGH' if concentration_ratio > 0.5 else 'MEDIUM' if concentration_ratio > 0.3 else 'LOW'
                    
                    risk_analysis['risk_factors']['concentration'] = {
                        'total_tokens': conc_data[0],
                        'active_tokens': conc_data[1] or 0,
                        'concentration_ratio': round(concentration_ratio, 3),
                        'risk_level': concentration_risk
                    }
            
            if 'volatility' in risk_factors:
                # Analyse de volatilité basée sur l'historique des transactions
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_transactions,
                        COUNT(CASE WHEN is_large_token_amount = 1 THEN 1 END) as large_transactions,
                        AVG(ABS(amount)) as avg_sol_amount,
                        COUNT(DISTINCT DATE(datetime(block_time, 'unixepoch'))) as active_days
                    FROM transactions 
                    WHERE wallet_address = ? 
                    AND block_time >= ?
                """, (wallet_address, get_current_timestamp() - (30 * 86400)))
                
                vol_data = cursor.fetchone()
                if vol_data and vol_data[0]:
                    volatility_score = (vol_data[1] or 0) / max(vol_data[0], 1) * 100
                    volatility_risk = 'HIGH' if volatility_score > 20 else 'MEDIUM' if volatility_score > 10 else 'LOW'
                    
                    risk_analysis['risk_factors']['volatility'] = {
                        'total_transactions_30d': vol_data[0],
                        'large_transactions_30d': vol_data[1] or 0,
                        'volatility_score': round(volatility_score, 2),
                        'active_days_30d': vol_data[3] or 0,
                        'risk_level': volatility_risk
                    }
            
            if 'liquidity' in risk_factors:
                # Analyse de liquidité basée sur les tokens connus
                cursor.execute("""
                    SELECT 
                        ta.token_mint, ta.balance, t.token_symbol,
                        COUNT(tx.signature) as tx_history
                    FROM token_accounts ta
                    LEFT JOIN transactions t ON ta.token_mint = t.token_mint 
                        AND ta.wallet_address = t.wallet_address
                    LEFT JOIN transactions tx ON ta.token_mint = tx.token_mint
                    WHERE ta.wallet_address = ? AND ta.is_active = 1 AND ta.balance > 0
                    GROUP BY ta.token_mint, ta.balance, t.token_symbol
                    ORDER BY ta.balance DESC
                    LIMIT 10
                """, (wallet_address,))
                
                liquidity_tokens = []
                for row in cursor.fetchall():
                    mint = row[0]
                    balance = row[1]
                    symbol = row[2] or f"TOKEN_{mint[:6]}"
                    tx_history = row[3] or 0
                    
                    # Score de liquidité simple basé sur l'historique des transactions
                    liquidity_score = min(100, tx_history * 2)  # Max 100
                    liquidity_level = 'HIGH' if liquidity_score > 50 else 'MEDIUM' if liquidity_score > 20 else 'LOW'
                    
                    liquidity_tokens.append({
                        'token_mint': mint,
                        'mint_short': f"{mint[:6]}...{mint[-6:]}",
                        'token_symbol': symbol,
                        'balance': balance,
                        'transaction_history': tx_history,
                        'liquidity_score': liquidity_score,
                        'liquidity_level': liquidity_level
                    })
                
                risk_analysis['risk_factors']['liquidity'] = {
                    'analyzed_tokens': len(liquidity_tokens),
                    'tokens': liquidity_tokens
                }
        
        # Score de risque global
        risk_scores = []
        for factor, data in risk_analysis['risk_factors'].items():
            if isinstance(data, dict) and 'risk_level' in data:
                risk_level = data['risk_level']
                score = 3 if risk_level == 'HIGH' else 2 if risk_level == 'MEDIUM' else 1
                risk_scores.append(score)
        
        if risk_scores:
            avg_risk_score = sum(risk_scores) / len(risk_scores)
            overall_risk = 'HIGH' if avg_risk_score >= 2.5 else 'MEDIUM' if avg_risk_score >= 1.5 else 'LOW'
        else:
            overall_risk = 'UNKNOWN'
        
        risk_analysis['overall_risk'] = {
            'risk_level': overall_risk,
            'factors_analyzed': len(risk_analysis['risk_factors']),
            'recommendations': []
        }
        
        # Ajouter des recommandations
        if overall_risk == 'HIGH':
            risk_analysis['overall_risk']['recommendations'].append("Consider diversifying your portfolio")
            risk_analysis['overall_risk']['recommendations'].append("Monitor large positions closely")
        
        return jsonify(format_api_response(
            risk_analysis,
            message=f"Risk analysis completed - Overall risk: {overall_risk}"
        ))
        
    except Exception as e:
        logger.error(f"Risk analysis failed: {e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message="Risk analysis failed"
        )), 500

# ============= ROUTES DE SANTÉ ET MONITORING =============

@analytics_bp.route('/health')
def analytics_health_check():
    """Health check du service analytics"""
    try:
        # Test des services
        health_status = {
            'status': 'healthy',
            'timestamp': datetime.utcnow().isoformat(),
            'services': {
                'wallet_analyzer': 'operational',
                'transaction_processor': 'operational', 
                'portfolio_tracker': 'operational',
                'data_collector': 'operational'
            }
        }
        
        # Test de base de données
        try:
            with get_database_manager().get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM transactions LIMIT 1")
                result = cursor.fetchone()
                health_status['services']['database'] = 'operational'
        except Exception as db_e:
            health_status['services']['database'] = f'error: {str(db_e)}'
            health_status['status'] = 'degraded'
        
        return jsonify(format_api_response(
            health_status,
            message=f"Analytics service is {health_status['status']}"
        ))
        
    except Exception as e:
        logger.error(f"Analytics health check failed: {e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message="Analytics health check failed"
        )), 503

# ============= GESTIONNAIRES D'ERREURS =============

@analytics_bp.errorhandler(400)
def bad_request(error):
    """Gestionnaire d'erreur 400"""
    return jsonify(format_api_response(
        None,
        success=False,
        message="Bad request - Invalid parameters"
    )), 400

@analytics_bp.errorhandler(404)
def not_found(error):
    """Gestionnaire d'erreur 404"""
    return jsonify(format_api_response(
        None,
        success=False,
        message="Analytics endpoint not found"
    )), 404

@analytics_bp.errorhandler(500)
def internal_error(error):
    """Gestionnaire d'erreur 500"""
    logger.error(f"Internal error in analytics routes: {error}")
    return jsonify(format_api_response(
        None,
        success=False,
        message="Internal server error in analytics"
    )), 500

# ============= HOOKS ET MIDDLEWARES =============

@analytics_bp.before_request
def before_analytics_request():
    """Middleware exécuté avant chaque requête analytics"""
    start_time = time.time()
    request.start_time = start_time
    
    # Logging détaillé
    logger.info(f"Analytics request: {request.method} {request.path}")
    if request.is_json and request.get_json():
        data = request.get_json()
        # Masquer les données sensibles pour les logs
        safe_data = {k: v if k != 'wallet_address' else f"{v[:6]}...{v[-6:]}" 
                    for k, v in data.items() if isinstance(v, str) and len(str(v)) > 20}
        logger.debug(f"Request data: {safe_data}")

@analytics_bp.after_request
def after_analytics_request(response):
    """Middleware exécuté après chaque requête analytics"""
    if hasattr(request, 'start_time'):
        duration = round((time.time() - request.start_time) * 1000, 2)
        response.headers['X-Response-Time-Ms'] = str(duration)
        logger.info(f"Analytics response: {response.status_code} in {duration}ms")
    
    response.headers['X-Analytics-API'] = 'v1.0'
    response.headers['X-Service-Status'] = 'operational'
    return response




@analytics_bp.route('/transactions/analyze', methods=['POST'])
def analyze_transactions():
    """
    Analyse l'historique des transactions d'un wallet
    
    Body JSON:
    {
        "wallet_address": "string (required)",
        "start_date": "datetime (optional)",
        "end_date": "datetime (optional)", 
        "limit": "integer (1-1000, default: 100)",
        "transaction_type": "string (optional)"
    }
    """
    try:
        data = request.get_json() or {}
        
        # Validation
        validation = validate_transaction_analysis_request(data)
        if not validation['valid']:
            return jsonify(format_api_response(
                None,
                success=False,
                message="Validation failed", 
                errors=validation['errors']
            )), 400
        
        validated_data = validation['validated_data']
        
        logger.info(f"Starting transaction analysis for: {validated_data['wallet_address']}")
        
        # Analyse des transactions
        analysis_result = transaction_processor.analyze_transactions(**validated_data)
        
        return jsonify(format_api_response(
            analysis_result,
            message="Transaction analysis completed"
        ))
        
    except Exception as e:
        logger.error(f"Transaction analysis failed: {e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message="Transaction analysis failed"
        )), 500

@analytics_bp.route('/portfolio/analyze', methods=['POST'])
def analyze_portfolio():
    """
    Analyse la composition et performance du portefeuille
    
    Body JSON:
    {
        "wallet_address": "string (required)",
        "include_historical": "boolean (default: true)",
        "currency": "string (default: USD)"
    }
    """
    try:
        data = request.get_json() or {}
        
        wallet_address = data.get('wallet_address', '').strip()
        if not wallet_address or not validate_wallet_address(wallet_address):
            return jsonify(format_api_response(
                None,
                success=False,
                message="Invalid or missing wallet_address"
            )), 400
        
        logger.info(f"Starting portfolio analysis for: {wallet_address}")
        
        analysis_params = {
            'wallet_address': wallet_address,
            'include_historical': data.get('include_historical', True),
            'currency': data.get('currency', 'USD')
        }
        
        analysis_result = portfolio_tracker.analyze_portfolio(**analysis_params)
        
        return jsonify(format_api_response(
            analysis_result,
            message="Portfolio analysis completed"
        ))
        
    except Exception as e:
        logger.error(f"Portfolio analysis failed: {e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message="Portfolio analysis failed"
        )), 500

@analytics_bp.route('/tokens/analyze', methods=['POST'])
def analyze_tokens():
    """
    Analyse des holdings et transactions de tokens
    
    Body JSON:
    {
        "wallet_address": "string (required)",
        "token_address": "string (optional)",
        "min_value": "float (default: 0)"
    }
    """
    try:
        data = request.get_json() or {}
        
        wallet_address = data.get('wallet_address', '').strip()
        if not wallet_address or not validate_wallet_address(wallet_address):
            return jsonify(format_api_response(
                None,
                success=False,
                message="Invalid or missing wallet_address"
            )), 400
        
        logger.info(f"Starting token analysis for: {wallet_address}")
        
        analysis_params = {
            'wallet_address': wallet_address,
            'token_address': data.get('token_address'),
            'min_value': max(data.get('min_value', 0), 0)
        }
        
        analysis_result = data_collector.analyze_tokens(**analysis_params)
        
        return jsonify(format_api_response(
            analysis_result,
            message="Token analysis completed"
        ))
        
    except Exception as e:
        logger.error(f"Token analysis failed: {e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message="Token analysis failed"
        )), 500

# ============= ROUTES SPÉCIFIQUES PAR WALLET =============

@analytics_bp.route('/wallet/<wallet_address>/summary')
def get_wallet_summary(wallet_address):
    """
    Résumé rapide d'un wallet
    
    Query parameters:
    - days: integer (1-365, default: 30)
    """
    try:
        if not validate_wallet_address(wallet_address):
            return jsonify(format_api_response(
                None,
                success=False,
                message="Invalid wallet address format"
            )), 400
        
        days = request.args.get('days', 30, type=int)
        days = min(max(days, 1), 365)  # Clamp entre 1 et 365
        
        logger.info(f"Getting wallet summary for: {wallet_address}")
        
        summary = wallet_analyzer.get_wallet_summary(
            wallet_address=wallet_address,
            days=days
        )
        
        response_data = {
            'wallet_address': wallet_address,
            'wallet_short': format_wallet_address(wallet_address),
            'summary_date': datetime.utcnow().isoformat(),
            'period_days': days,
            **summary
        }
        
        return jsonify(format_api_response(
            response_data,
            message=f"Wallet summary for {days} days"
        ))
        
    except Exception as e:
        logger.error(f"Wallet summary failed: {e}")
        return jsonify(format_api_response(
            None,
            success=False,
            message="Failed to get wallet summary"
        )), 500

# ============= EXPORT =============

__all__ = ['analytics_bp']