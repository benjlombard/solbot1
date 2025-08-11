#!/usr/bin/env python3
"""
Routes API pour le trading avec Phantom Wallet
Interface REST pour les opérations de trading
"""

from flask import Blueprint, request, jsonify
from typing import Dict, List, Optional, Any
import time
import logging

# Imports des modèles et utilitaires
try:
    from models.trading import (
        TradeType, TradeStatus, SlippageLevel,
        TradingSettings, TradeQuote, TradeOrder, TradingPortfolio, MarketData,
        validate_trade_amount, calculate_slippage_tolerance
    )
    from models.schemas import (
        ApiResponse, create_success_response, create_error_response,
        ValidationError, ValidationResult
    )
    from trading.manager import trading_manager
    from core.database import get_database_manager
    from utils.validators import validate_wallet_address, validate_token_mint
    from utils.helpers import get_current_timestamp, safe_get
except ImportError as e:
    logging.warning(f"Import error in trading routes: {e}")
    # Fallbacks pour développement
    def create_success_response(msg, data=None): 
        return {'success': True, 'message': msg, 'data': data}
    def create_error_response(msg, errors=None): 
        return {'success': False, 'message': msg, 'errors': errors or []}
    def validate_wallet_address(addr): return bool(addr and len(addr) == 44)
    def validate_token_mint(mint): return bool(mint and len(mint) == 44)
    def get_current_timestamp(): return int(time.time())
    def safe_get(data, key, default=None): return data.get(key, default)

# Configuration du logger
logger = logging.getLogger(__name__)

# Création du blueprint
trading_bp = Blueprint('trading', __name__, url_prefix='/api/trading')


# =============================================================================
# ROUTES DE CONFIGURATION
# =============================================================================
@trading_bp.route('/quick-quote', methods=['GET','POST'])
def get_quick_quote():
    """Obtient un devis rapide pour un token depuis le dashboard"""
    try:
        # Pour GET, retourner un message d'aide
        if request.method == 'GET':
            return jsonify(create_success_response(
                "Quick quote endpoint",
                {
                    'usage': 'POST avec token_mint, amount_sol, trade_type, wallet_address',
                    'example': {
                        'token_mint': 'So11111111111111111111111111111111111111112',
                        'amount_sol': 1.0,
                        'trade_type': 'buy',
                        'wallet_address': 'your_wallet_address'
                    }
                }
            ))

        data = request.get_json()
        if not data:
            return jsonify(create_error_response("No data provided")), 400
        
        # Validation des paramètres requis
        token_mint = data.get('token_mint')
        amount_sol = data.get('amount_sol')
        trade_type_str = data.get('trade_type', 'buy')  # 'buy' ou 'sell'
        wallet_address = data.get('wallet_address')
        
        if not token_mint:
            return jsonify(create_error_response("token_mint is required")), 400
        
        if not amount_sol:
            return jsonify(create_error_response("amount_sol is required")), 400
        
        try:
            amount_sol = float(amount_sol)
        except ValueError:
            return jsonify(create_error_response("amount_sol must be a number")), 400
        
        # Validation du type de trade
        try:
            trade_type = TradeType(trade_type_str.lower())
        except ValueError:
            return jsonify(create_error_response("Invalid trade_type. Must be 'buy' or 'sell'")), 400
        
        # Si pas de wallet fourni, utiliser un wallet par défaut pour le devis
        if not wallet_address:
            wallet_address = "11111111111111111111111111111111"  # Wallet temporaire pour devis
        
        # Obtenir le devis
        quote = trading_manager.get_trade_quote(
            wallet_address, token_mint, amount_sol, trade_type
        )
        
        return jsonify(create_success_response(
            "Quick quote generated",
            {
                'quote': quote.to_dict(),
                'dex_url': _generate_dex_url(token_mint, amount_sol, trade_type),
                'jupiter_url': _generate_jupiter_url(token_mint, amount_sol, trade_type)
            }
        ))
        
    except Exception as e:
        logger.error(f"Error getting quick quote: {e}")
        return jsonify(create_error_response("Failed to get quote", [str(e)])), 500


@trading_bp.route('/dex-urls', methods=['POST'])
def get_dex_urls():
    """Génère les URLs pour différents DEX"""
    try:
        data = request.get_json()
        token_mint = data.get('token_mint')
        amount_sol = data.get('amount_sol', 1.0)
        trade_type = data.get('trade_type', 'buy')
        
        if not token_mint:
            return jsonify(create_error_response("token_mint is required")), 400
        
        urls = {
            'jupiter': _generate_jupiter_url(token_mint, amount_sol, trade_type),
            'raydium': _generate_raydium_url(token_mint, amount_sol, trade_type),
            'orca': _generate_orca_url(token_mint, amount_sol, trade_type),
            'dexscreener': f"https://dexscreener.com/solana/{token_mint}",
            'birdeye': f"https://birdeye.so/token/{token_mint}",
            'solscan': f"https://solscan.io/token/{token_mint}"
        }
        
        return jsonify(create_success_response(
            "DEX URLs generated",
            urls
        ))
        
    except Exception as e:
        logger.error(f"Error generating DEX URLs: {e}")
        return jsonify(create_error_response("Failed to generate URLs", [str(e)])), 500


@trading_bp.route('/phantom-transaction', methods=['POST'])
def create_phantom_transaction():
    """Crée une transaction pour Phantom Wallet"""
    try:
        data = request.get_json()
        wallet_address = data.get('wallet_address')
        token_mint = data.get('token_mint')
        amount_sol = data.get('amount_sol')
        trade_type = data.get('trade_type', 'buy')
        
        if not all([wallet_address, token_mint, amount_sol]):
            return jsonify(create_error_response("Missing required parameters")), 400
        
        # Validation
        if not validate_wallet_address(wallet_address):
            return jsonify(create_error_response("Invalid wallet address")), 400
        
        if not validate_token_mint(token_mint):
            return jsonify(create_error_response("Invalid token mint")), 400
        
        # Obtenir un devis
        quote = trading_manager.get_trade_quote(
            wallet_address, token_mint, float(amount_sol), TradeType(trade_type)
        )
        
        # Créer l'ordre
        order = trading_manager.create_trade_order(wallet_address, quote.quote_id)
        
        # Générer la transaction Phantom
        transaction_data = _create_phantom_transaction_data(quote, order)
        
        return jsonify(create_success_response(
            "Phantom transaction created",
            {
                'order_id': order.order_id,
                'quote': quote.to_dict(),
                'transaction_data': transaction_data,
                'phantom_params': _create_phantom_params(quote, order)
            }
        ))
        
    except Exception as e:
        logger.error(f"Error creating Phantom transaction: {e}")
        return jsonify(create_error_response("Failed to create transaction", [str(e)])), 500


def _generate_jupiter_url(token_mint: str, amount_sol: float, trade_type: str) -> str:
    """Génère une URL Jupiter pour le trade"""
    sol_mint = "So11111111111111111111111111111111111111112"
    
    if trade_type.lower() == 'buy':
        return f"https://jup.ag/swap/{sol_mint}-{token_mint}?inAmount={amount_sol}"
    else:
        return f"https://jup.ag/swap/{token_mint}-{sol_mint}?inAmount={amount_sol}"


def _generate_raydium_url(token_mint: str, amount_sol: float, trade_type: str) -> str:
    """Génère une URL Raydium pour le trade"""
    if trade_type.lower() == 'buy':
        return f"https://raydium.io/swap/?inputCurrency=sol&outputCurrency={token_mint}&inputAmount={amount_sol}"
    else:
        return f"https://raydium.io/swap/?inputCurrency={token_mint}&outputCurrency=sol&inputAmount={amount_sol}"


def _generate_orca_url(token_mint: str, amount_sol: float, trade_type: str) -> str:
    """Génère une URL Orca pour le trade"""
    if trade_type.lower() == 'buy':
        return f"https://www.orca.so/swap?from=sol&to={token_mint}&amount={amount_sol}"
    else:
        return f"https://www.orca.so/swap?from={token_mint}&to=sol&amount={amount_sol}"


def _create_phantom_transaction_data(quote: TradeQuote, order: TradeOrder) -> Dict[str, Any]:
    """Crée les données de transaction pour Phantom"""
    return {
        'type': 'swap',
        'input_mint': quote.token_mint if quote.trade_type == TradeType.SELL else "So11111111111111111111111111111111111111112",
        'output_mint': "So11111111111111111111111111111111111111112" if quote.trade_type == TradeType.SELL else quote.token_mint,
        'amount_in': int(quote.amount_in),
        'amount_out': int(quote.amount_out),
        'slippage_bps': int(quote.slippage * 100),
        'priority_fee': order.priority_fee,
        'quote_id': quote.quote_id,
        'order_id': order.order_id
    }


def _create_phantom_params(quote: TradeQuote, order: TradeOrder) -> Dict[str, Any]:
    """Crée les paramètres pour l'appel Phantom"""
    return {
        'method': 'swap',
        'params': {
            'inputMint': quote.token_mint if quote.trade_type == TradeType.SELL else "So11111111111111111111111111111111111111112",
            'outputMint': "So11111111111111111111111111111111111111112" if quote.trade_type == TradeType.SELL else quote.token_mint,
            'amount': str(int(quote.amount_in)),
            'slippageBps': int(quote.slippage * 100),
            'userPublicKey': order.wallet_address,
            'wrapUnwrapSOL': True,
            'asLegacyTransaction': False,
            'allowOptimizedWrappedSolTokenAccount': True,
            'onlyDirectRoutes': False,
            'prioritizationFeeLamports': order.priority_fee
        }
    }
    
@trading_bp.route('/settings/<wallet_address>', methods=['GET'])
def get_trading_settings(wallet_address):
    """Récupère les paramètres de trading d'un wallet"""
    try:
        if not validate_wallet_address(wallet_address):
            return jsonify(create_error_response("Invalid wallet address")), 400
        
        settings = trading_manager.get_trading_settings(wallet_address)
        
        return jsonify(create_success_response(
            "Trading settings retrieved",
            settings.to_dict()
        ))
        
    except Exception as e:
        logger.error(f"Error getting trading settings: {e}")
        return jsonify(create_error_response("Failed to get trading settings", [str(e)])), 500


@trading_bp.route('/settings/<wallet_address>', methods=['POST', 'PUT'])
def update_trading_settings(wallet_address):
    """Met à jour les paramètres de trading"""
    try:
        if not validate_wallet_address(wallet_address):
            return jsonify(create_error_response("Invalid wallet address")), 400
        
        data = request.get_json()
        if not data:
            return jsonify(create_error_response("No data provided")), 400
        
        # Récupérer paramètres actuels
        settings = trading_manager.get_trading_settings(wallet_address)
        
        # Mettre à jour les champs fournis
        if 'default_slippage' in data:
            slippage = float(data['default_slippage'])
            if not 0.1 <= slippage <= 10.0:
                return jsonify(create_error_response("Slippage must be between 0.1% and 10%")), 400
            settings.default_slippage = slippage
        
        if 'max_trade_amount_sol' in data:
            max_amount = float(data['max_trade_amount_sol'])
            if not 0.001 <= max_amount <= 1000.0:
                return jsonify(create_error_response("Max trade amount must be between 0.001 and 1000 SOL")), 400
            settings.max_trade_amount_sol = max_amount
        
        if 'max_daily_volume_sol' in data:
            max_volume = float(data['max_daily_volume_sol'])
            if not 0.01 <= max_volume <= 10000.0:
                return jsonify(create_error_response("Max daily volume must be between 0.01 and 10000 SOL")), 400
            settings.max_daily_volume_sol = max_volume
        
        if 'auto_approve_under_sol' in data:
            auto_approve = float(data['auto_approve_under_sol'])
            if not 0.001 <= auto_approve <= 10.0:
                return jsonify(create_error_response("Auto approve limit must be between 0.001 and 10 SOL")), 400
            settings.auto_approve_under_sol = auto_approve
        
        if 'preferred_dex' in data:
            dex = data['preferred_dex']
            if dex not in ['jupiter', 'raydium', 'orca']:
                return jsonify(create_error_response("Invalid DEX. Must be jupiter, raydium, or orca")), 400
            settings.preferred_dex = dex
        
        if 'enable_mev_protection' in data:
            settings.enable_mev_protection = bool(data['enable_mev_protection'])
        
        if 'priority_fee_lamports' in data:
            fee = int(data['priority_fee_lamports'])
            if not 0 <= fee <= 50000:
                return jsonify(create_error_response("Priority fee must be between 0 and 50000 lamports")), 400
            settings.priority_fee_lamports = fee
        
        # Sauvegarder
        success = trading_manager.update_trading_settings(settings)
        
        if success:
            return jsonify(create_success_response(
                "Trading settings updated",
                settings.to_dict()
            ))
        else:
            return jsonify(create_error_response("Failed to update settings")), 500
        
    except ValueError as e:
        return jsonify(create_error_response(f"Invalid value: {e}")), 400
    except Exception as e:
        logger.error(f"Error updating trading settings: {e}")
        return jsonify(create_error_response("Failed to update trading settings", [str(e)])), 500


# =============================================================================
# ROUTES DE QUOTES ET PRICING
# =============================================================================

@trading_bp.route('/quote', methods=['POST'])
def get_trade_quote():
    """Obtient un devis pour un trade"""
    try:
        data = request.get_json()
        if not data:
            return jsonify(create_error_response("No data provided")), 400
        
        # Validation des paramètres requis
        wallet_address = data.get('wallet_address')
        token_mint = data.get('token_mint')
        amount_sol = data.get('amount_sol')
        trade_type_str = data.get('trade_type', 'buy')
        
        if not wallet_address:
            return jsonify(create_error_response("wallet_address is required")), 400
        
        if not validate_wallet_address(wallet_address):
            return jsonify(create_error_response("Invalid wallet address")), 400
        
        if not token_mint:
            return jsonify(create_error_response("token_mint is required")), 400
        
        if not validate_token_mint(token_mint):
            return jsonify(create_error_response("Invalid token mint")), 400
        
        if not amount_sol:
            return jsonify(create_error_response("amount_sol is required")), 400
        
        try:
            amount_sol = float(amount_sol)
        except ValueError:
            return jsonify(create_error_response("amount_sol must be a number")), 400
        
        if not validate_trade_amount(amount_sol):
            return jsonify(create_error_response("Invalid trade amount")), 400
        
        # Validation du type de trade
        try:
            trade_type = TradeType(trade_type_str.lower())
        except ValueError:
            return jsonify(create_error_response("Invalid trade_type. Must be 'buy' or 'sell'")), 400
        
        # Paramètres optionnels
        slippage = data.get('slippage')
        if slippage is not None:
            try:
                slippage = float(slippage)
                if not 0.1 <= slippage <= 10.0:
                    return jsonify(create_error_response("Slippage must be between 0.1% and 10%")), 400
            except ValueError:
                return jsonify(create_error_response("Slippage must be a number")), 400
        
        # Obtenir le devis
        quote = trading_manager.get_trade_quote(
            wallet_address, token_mint, amount_sol, trade_type, slippage
        )
        
        return jsonify(create_success_response(
            "Quote generated successfully",
            quote.to_dict()
        ))
        
    except Exception as e:
        logger.error(f"Error getting trade quote: {e}")
        return jsonify(create_error_response("Failed to get quote", [str(e)])), 500


@trading_bp.route('/market-data/<token_mint>', methods=['GET'])
def get_market_data(token_mint):
    """Récupère les données de marché pour un token"""
    try:
        if not validate_token_mint(token_mint):
            return jsonify(create_error_response("Invalid token mint")), 400
        
        force_refresh = request.args.get('refresh', 'false').lower() == 'true'
        
        market_data = trading_manager.get_market_data(token_mint, force_refresh)
        
        return jsonify(create_success_response(
            "Market data retrieved",
            market_data.to_dict()
        ))
        
    except Exception as e:
        logger.error(f"Error getting market data: {e}")
        return jsonify(create_error_response("Failed to get market data", [str(e)])), 500


@trading_bp.route('/prices/batch', methods=['POST'])
def get_batch_prices():
    """Récupère les prix pour plusieurs tokens"""
    try:
        data = request.get_json()
        if not data:
            return jsonify(create_error_response("No data provided")), 400
        
        token_mints = data.get('token_mints', [])
        if not token_mints:
            return jsonify(create_error_response("token_mints array is required")), 400
        
        if len(token_mints) > 50:
            return jsonify(create_error_response("Maximum 50 tokens per request")), 400
        
        # Valider tous les mints
        invalid_mints = [mint for mint in token_mints if not validate_token_mint(mint)]
        if invalid_mints:
            return jsonify(create_error_response(f"Invalid token mints: {invalid_mints}")), 400
        
        # Récupérer données pour chaque token
        results = {}
        for token_mint in token_mints:
            try:
                market_data = trading_manager.get_market_data(token_mint)
                results[token_mint] = {
                    'price_usd': market_data.price_usd,
                    'price_sol': market_data.price_sol,
                    'price_change_24h': market_data.price_change_24h,
                    'volume_24h_usd': market_data.volume_24h_usd,
                    'updated_at': market_data.updated_at
                }
            except Exception as e:
                logger.warning(f"Failed to get data for {token_mint}: {e}")
                results[token_mint] = {
                    'error': str(e),
                    'price_usd': 0.0,
                    'price_sol': 0.0
                }
        
        return jsonify(create_success_response(
            f"Batch prices retrieved for {len(results)} tokens",
            results
        ))
        
    except Exception as e:
        logger.error(f"Error getting batch prices: {e}")
        return jsonify(create_error_response("Failed to get batch prices", [str(e)])), 500


# =============================================================================
# ROUTES DE TRADING
# =============================================================================

@trading_bp.route('/order', methods=['POST'])
def create_trade_order():
    """Crée un ordre de trade basé sur un devis"""
    try:
        data = request.get_json()
        if not data:
            return jsonify(create_error_response("No data provided")), 400
        
        wallet_address = data.get('wallet_address')
        quote_id = data.get('quote_id')
        notes = data.get('notes')
        
        if not wallet_address:
            return jsonify(create_error_response("wallet_address is required")), 400
        
        if not validate_wallet_address(wallet_address):
            return jsonify(create_error_response("Invalid wallet address")), 400
        
        if not quote_id:
            return jsonify(create_error_response("quote_id is required")), 400
        
        # Créer l'ordre
        order = trading_manager.create_trade_order(wallet_address, quote_id, notes)
        
        return jsonify(create_success_response(
            "Trade order created",
            order.to_dict()
        )), 201
        
    except Exception as e:
        logger.error(f"Error creating trade order: {e}")
        error_msg = str(e)
        
        if "Quote not found" in error_msg:
            return jsonify(create_error_response("Quote not found or expired")), 404
        elif "expired" in error_msg.lower():
            return jsonify(create_error_response("Quote has expired")), 410
        else:
            return jsonify(create_error_response("Failed to create trade order", [error_msg])), 500


@trading_bp.route('/order/<order_id>/execute', methods=['POST'])
def execute_trade_order(order_id):
    """Exécute un ordre de trade avec signature Phantom"""
    try:
        data = request.get_json()
        if not data:
            return jsonify(create_error_response("No data provided")), 400
        
        phantom_signature = data.get('signature')
        if not phantom_signature:
            return jsonify(create_error_response("Phantom signature is required")), 400
        
        # Validation basique de la signature
        if len(phantom_signature) < 80:
            return jsonify(create_error_response("Invalid signature format")), 400
        
        # Exécuter l'ordre
        success = trading_manager.execute_trade_order(order_id, phantom_signature)
        
        if success:
            # Récupérer l'ordre mis à jour
            order = trading_manager.pending_orders.get(order_id)
            if order:
                return jsonify(create_success_response(
                    "Trade executed successfully",
                    order.to_dict()
                ))
            else:
                return jsonify(create_success_response("Trade executed successfully"))
        else:
            return jsonify(create_error_response("Trade execution failed")), 500
        
    except Exception as e:
        logger.error(f"Error executing trade order: {e}")
        error_msg = str(e)
        
        if "Order not found" in error_msg:
            return jsonify(create_error_response("Order not found")), 404
        else:
            return jsonify(create_error_response("Failed to execute trade", [error_msg])), 500


@trading_bp.route('/order/<order_id>', methods=['GET'])
def get_trade_order(order_id):
    """Récupère les détails d'un ordre de trade"""
    try:
        # Chercher dans les ordres en attente
        if order_id in trading_manager.pending_orders:
            order = trading_manager.pending_orders[order_id]
            return jsonify(create_success_response(
                "Trade order retrieved",
                order.to_dict()
            ))
        
        # Chercher en base de données pour les ordres historiques
        db_manager = get_database_manager()
        if db_manager:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM trade_orders WHERE order_id = ?
                """, (order_id,))
                
                row = cursor.fetchone()
                if row:
                    order_data = {
                        'order_id': row['order_id'],
                        'wallet_address': row['wallet_address'],
                        'token_mint': row['token_mint'],
                        'token_symbol': row['token_symbol'],
                        'trade_type': row['trade_type'],
                        'amount_sol': float(row['amount_sol']),
                        'amount_tokens': float(row['amount_tokens']),
                        'slippage': float(row['slippage']),
                        'quote_id': row['quote_id'],
                        'dex': row['dex'],
                        'status': row['status'],
                        'transaction_signature': row['transaction_signature'],
                        'actual_amount_received': float(row['actual_amount_received']) if row['actual_amount_received'] else None,
                        'actual_price': float(row['actual_price']) if row['actual_price'] else None,
                        'gas_used': float(row['gas_used']) if row['gas_used'] else None,
                        'created_at': int(row['created_at']),
                        'submitted_at': int(row['submitted_at']) if row['submitted_at'] else None,
                        'confirmed_at': int(row['confirmed_at']) if row['confirmed_at'] else None,
                        'priority_fee': int(row['priority_fee']),
                        'notes': row['notes']
                    }
                    
                    return jsonify(create_success_response(
                        "Trade order retrieved from history",
                        order_data
                    ))
        
        return jsonify(create_error_response("Order not found")), 404
        
    except Exception as e:
        logger.error(f"Error getting trade order: {e}")
        return jsonify(create_error_response("Failed to get trade order", [str(e)])), 500


@trading_bp.route('/orders/<wallet_address>', methods=['GET'])
def get_wallet_orders(wallet_address):
    """Récupère l'historique des ordres d'un wallet"""
    try:
        if not validate_wallet_address(wallet_address):
            return jsonify(create_error_response("Invalid wallet address")), 400
        
        # Paramètres de pagination
        page = request.args.get('page', 1, type=int)
        page_size = min(request.args.get('page_size', 20, type=int), 100)
        status_filter = request.args.get('status')
        
        db_manager = get_database_manager()
        if not db_manager:
            return jsonify(create_error_response("Database not available")), 503
        
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Construire la requête avec filtres
            where_clause = "WHERE wallet_address = ?"
            params = [wallet_address]
            
            if status_filter:
                where_clause += " AND status = ?"
                params.append(status_filter)
            
            # Compter le total
            cursor.execute(f"""
                SELECT COUNT(*) FROM trade_orders {where_clause}
            """, params)
            total_count = cursor.fetchone()[0]
            
            # Récupérer les ordres paginés
            offset = (page - 1) * page_size
            cursor.execute(f"""
                SELECT * FROM trade_orders {where_clause}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, params + [page_size, offset])
            
            orders = []
            for row in cursor.fetchall():
                orders.append({
                    'order_id': row['order_id'],
                    'token_mint': row['token_mint'],
                    'token_symbol': row['token_symbol'],
                    'trade_type': row['trade_type'],
                    'amount_sol': float(row['amount_sol']),
                    'amount_tokens': float(row['amount_tokens']),
                    'status': row['status'],
                    'dex': row['dex'],
                    'transaction_signature': row['transaction_signature'],
                    'created_at': int(row['created_at']),
                    'confirmed_at': int(row['confirmed_at']) if row['confirmed_at'] else None
                })
            
            return jsonify(create_success_response(
                f"Retrieved {len(orders)} orders",
                {
                    'orders': orders,
                    'pagination': {
                        'page': page,
                        'page_size': page_size,
                        'total_count': total_count,
                        'total_pages': (total_count + page_size - 1) // page_size
                    }
                }
            ))
        
    except Exception as e:
        logger.error(f"Error getting wallet orders: {e}")
        return jsonify(create_error_response("Failed to get orders", [str(e)])), 500


# =============================================================================
# ROUTES DE PORTFOLIO
# =============================================================================

@trading_bp.route('/portfolio/<wallet_address>', methods=['GET'])
def get_trading_portfolio(wallet_address):
    """Récupère le portfolio de trading d'un wallet"""
    try:
        if not validate_wallet_address(wallet_address):
            return jsonify(create_error_response("Invalid wallet address")), 400
        
        portfolio = trading_manager.get_trading_portfolio(wallet_address)
        
        return jsonify(create_success_response(
            "Trading portfolio retrieved",
            portfolio.to_dict()
        ))
        
    except Exception as e:
        logger.error(f"Error getting trading portfolio: {e}")
        return jsonify(create_error_response("Failed to get portfolio", [str(e)])), 500


@trading_bp.route('/recommendations/<wallet_address>', methods=['GET'])
def get_trading_recommendations(wallet_address):
    """Récupère les recommandations de trading pour un wallet"""
    try:
        if not validate_wallet_address(wallet_address):
            return jsonify(create_error_response("Invalid wallet address")), 400
        
        limit = min(request.args.get('limit', 10, type=int), 50)
        
        recommendations = trading_manager.get_recommended_tokens(wallet_address, limit)
        
        return jsonify(create_success_response(
            f"Retrieved {len(recommendations)} recommendations",
            {
                'recommendations': recommendations,
                'generated_at': get_current_timestamp()
            }
        ))
        
    except Exception as e:
        logger.error(f"Error getting recommendations: {e}")
        return jsonify(create_error_response("Failed to get recommendations", [str(e)])), 500


# =============================================================================
# ROUTES D'ADMINISTRATION
# =============================================================================

@trading_bp.route('/stats', methods=['GET'])
def get_trading_stats():
    """Récupère les statistiques de trading"""
    try:
        stats = trading_manager.get_trading_stats()
        
        return jsonify(create_success_response(
            "Trading statistics retrieved",
            stats
        ))
        
    except Exception as e:
        logger.error(f"Error getting trading stats: {e}")
        return jsonify(create_error_response("Failed to get statistics", [str(e)])), 500


@trading_bp.route('/cleanup', methods=['POST'])
def cleanup_expired_data():
    """Nettoie les données expirées (quotes, etc.)"""
    try:
        cleaned_quotes = trading_manager.cleanup_expired_quotes()
        
        return jsonify(create_success_response(
            f"Cleanup completed: {cleaned_quotes} expired quotes removed",
            {
                'cleaned_quotes': cleaned_quotes,
                'timestamp': get_current_timestamp()
            }
        ))
        
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        return jsonify(create_error_response("Cleanup failed", [str(e)])), 500


@trading_bp.route('/health', methods=['GET'])
def trading_health():
    """Health check pour le système de trading"""
    try:
        health_data = {
            'status': 'healthy',
            'timestamp': get_current_timestamp(),
            'trading_manager': 'operational',
            'active_quotes': len(trading_manager.active_quotes),
            'pending_orders': len(trading_manager.pending_orders),
            'market_data_cache': len(trading_manager.market_data_cache)
        }
        
        return jsonify(create_success_response("Trading system healthy", health_data))
        
    except Exception as e:
        logger.error(f"Trading health check failed: {e}")
        return jsonify(create_error_response("Health check failed", [str(e)])), 500


# =============================================================================
# HANDLERS D'ERREURS
# =============================================================================

@trading_bp.errorhandler(404)
def trading_not_found(error):
    """Handler pour erreur 404"""
    return jsonify(create_error_response("Trading endpoint not found")), 404


@trading_bp.errorhandler(500)
def trading_server_error(error):
    """Handler pour erreur 500"""
    logger.error(f"Trading server error: {error}")
    return jsonify(create_error_response("Internal server error in trading")), 500


# =============================================================================
# INITIALISATION
# =============================================================================

def init_trading_routes(app):
    """Initialise les routes trading sur l'application"""
    app.register_blueprint(trading_bp)
    logger.info("✅ Routes trading enregistrées")


# Export
__all__ = [
    'trading_bp',
    'init_trading_routes'
]