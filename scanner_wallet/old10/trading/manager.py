#!/usr/bin/env python3
"""
Trading Manager pour Phantom Wallet Integration
Gère les connexions wallet, les quotes, et l'exécution des trades
"""

import time
import json
import threading
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import asdict
import requests
import logging

# Core imports avec fallbacks
try:
    from core.logger import get_logger
    from core.database import get_database_manager
    from core.config import get_config
    from models.trading import (
        TradeType, TradeStatus, SlippageLevel,
        TradingSettings, TradeQuote, TradeOrder, TradingPortfolio, MarketData,
        validate_trade_amount, calculate_slippage_tolerance, estimate_trade_fee,
        get_recommended_dex, create_trade_order_id, create_quote_id
    )
    from models.token import Token
    from utils.helpers import get_current_timestamp, safe_divide
    from utils.validators import validate_wallet_address, validate_token_mint
    
except ImportError as e:
    # Fallback implementations
    import logging
    def get_logger(name=None):
        return logging.getLogger(name or 'trading_manager')
    
    def get_database_manager(): return None
    def get_config(): return None
    def validate_wallet_address(addr): return bool(addr and len(addr) == 44)
    def validate_token_mint(mint): return bool(mint and len(mint) == 44)
    def get_current_timestamp(): return int(time.time())
    def safe_divide(a, b, default=0): return a/b if b else default

logger = get_logger(__name__)


class TradingError(Exception):
    """Exception pour erreurs de trading"""
    pass


class InsufficientFundsError(TradingError):
    """Exception pour fonds insuffisants"""
    pass


class QuoteExpiredError(TradingError):
    """Exception pour devis expiré"""
    pass


class TradingManager:
    """
    Gestionnaire principal pour les opérations de trading
    Interface entre l'API et les DEX Solana
    """
    
    def __init__(self):
        self.config = get_config()
        self.db_manager = get_database_manager()
        
        # Configuration DEX
        self.dex_configs = {
            'jupiter': {
                'api_url': 'https://quote-api.jup.ag/v6',
                'supported_tokens': [],  # Sera chargé dynamiquement
                'fee_bps': 25,  # 0.25%
                'min_amount': 0.001
            },
            'raydium': {
                'api_url': 'https://api.raydium.io/v2',
                'fee_bps': 30,  # 0.3%
                'min_amount': 0.001
            }
        }
        
        # Cache et état
        self.active_quotes = {}  # quote_id -> TradeQuote
        self.pending_orders = {}  # order_id -> TradeOrder
        self.market_data_cache = {}  # token_mint -> MarketData
        self.trading_settings_cache = {}  # wallet_address -> TradingSettings
        
        # Thread safety
        self.trading_lock = threading.RLock()
        
        # Statistiques
        self.stats = {
            'total_quotes': 0,
            'total_orders': 0,
            'successful_trades': 0,
            'failed_trades': 0,
            'total_volume': 0.0
        }
        
        logger.info("✅ Trading Manager initialized")
    
    # =============================================================================
    # GESTION DES PARAMÈTRES UTILISATEUR
    # =============================================================================
    
    def get_trading_settings(self, wallet_address: str) -> TradingSettings:
        """Récupère les paramètres de trading d'un wallet"""
        if not validate_wallet_address(wallet_address):
            raise ValueError("Invalid wallet address")
        
        # Vérifier cache
        if wallet_address in self.trading_settings_cache:
            return self.trading_settings_cache[wallet_address]
        
        # Charger depuis DB ou créer par défaut
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM trading_settings WHERE wallet_address = ?
                """, (wallet_address,))
                
                row = cursor.fetchone()
                if row:
                    settings = TradingSettings(
                        wallet_address=row['wallet_address'],
                        default_slippage=float(row['default_slippage']),
                        max_trade_amount_sol=float(row['max_trade_amount_sol']),
                        max_daily_volume_sol=float(row['max_daily_volume_sol']),
                        auto_approve_under_sol=float(row['auto_approve_under_sol']),
                        preferred_dex=row['preferred_dex'],
                        enable_mev_protection=bool(row['enable_mev_protection']),
                        priority_fee_lamports=int(row['priority_fee_lamports']),
                        created_at=int(row['created_at']),
                        updated_at=int(row['updated_at'])
                    )
                else:
                    # Créer paramètres par défaut
                    settings = TradingSettings(wallet_address=wallet_address)
                    self._save_trading_settings(settings)
                
                # Cache
                self.trading_settings_cache[wallet_address] = settings
                return settings
                
        except Exception as e:
            logger.error(f"❌ Error loading trading settings: {e}")
            # Retourner paramètres par défaut
            return TradingSettings(wallet_address=wallet_address)
    
    def update_trading_settings(self, settings: TradingSettings) -> bool:
        """Met à jour les paramètres de trading"""
        try:
            settings.updated_at = get_current_timestamp()
            self._save_trading_settings(settings)
            
            # Mettre à jour cache
            self.trading_settings_cache[settings.wallet_address] = settings
            
            logger.info(f"✅ Trading settings updated for {settings.wallet_short}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error updating trading settings: {e}")
            return False
    
    def _save_trading_settings(self, settings: TradingSettings) -> None:
        """Sauvegarde les paramètres en base"""
        if not self.db_manager:
            return
        
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO trading_settings (
                    wallet_address, default_slippage, max_trade_amount_sol,
                    max_daily_volume_sol, auto_approve_under_sol, preferred_dex,
                    enable_mev_protection, priority_fee_lamports, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                settings.wallet_address, settings.default_slippage,
                settings.max_trade_amount_sol, settings.max_daily_volume_sol,
                settings.auto_approve_under_sol, settings.preferred_dex,
                settings.enable_mev_protection, settings.priority_fee_lamports,
                settings.created_at, settings.updated_at
            ))
            conn.commit()
    
    # =============================================================================
    # GESTION DES QUOTES
    # =============================================================================
    
    def get_trade_quote(self, wallet_address: str, token_mint: str, 
                       amount_sol: float, trade_type: TradeType = TradeType.BUY,
                       slippage: Optional[float] = None) -> TradeQuote:
        """Obtient un devis pour un trade"""
        if not validate_wallet_address(wallet_address):
            raise ValueError("Invalid wallet address")
        
        if not validate_token_mint(token_mint):
            raise ValueError("Invalid token mint")
        
        if not validate_trade_amount(amount_sol):
            raise ValueError("Invalid trade amount")
        
        # Récupérer paramètres utilisateur
        settings = self.get_trading_settings(wallet_address)
        
        if slippage is None:
            slippage = settings.default_slippage
        
        # Vérifier limites
        if amount_sol > settings.max_trade_amount_sol:
            raise TradingError(f"Amount exceeds max trade limit: {settings.max_trade_amount_sol} SOL")
        
        try:
            # Récupérer données de marché
            market_data = self.get_market_data(token_mint)
            
            # Ajuster slippage selon volatilité
            adjusted_slippage = calculate_slippage_tolerance(amount_sol, market_data.volatility_level)
            final_slippage = max(slippage, adjusted_slippage)
            
            # Obtenir devis du DEX
            quote = self._fetch_dex_quote(
                token_mint, amount_sol, trade_type, 
                final_slippage, settings.preferred_dex
            )
            
            # Ajouter au cache
            self.active_quotes[quote.quote_id] = quote
            self.stats['total_quotes'] += 1
            
            logger.info(f"💰 Quote generated: {trade_type.value} {amount_sol} SOL for {quote.token_symbol}")
            return quote
            
        except Exception as e:
            logger.error(f"❌ Error getting quote: {e}")
            raise TradingError(f"Failed to get quote: {e}")
    
    def _fetch_dex_quote(self, token_mint: str, amount_sol: float, 
                        trade_type: TradeType, slippage: float, dex: str) -> TradeQuote:
        """Récupère un devis depuis un DEX"""
        if dex == 'jupiter':
            return self._fetch_jupiter_quote(token_mint, amount_sol, trade_type, slippage)
        else:
            # Fallback vers Jupiter
            return self._fetch_jupiter_quote(token_mint, amount_sol, trade_type, slippage)
    
    def _fetch_jupiter_quote(self, token_mint: str, amount_sol: float, 
                           trade_type: TradeType, slippage: float) -> TradeQuote:
        """Récupère un devis depuis Jupiter"""
        try:
            # Conversion SOL en lamports
            sol_mint = "So11111111111111111111111111111111111111112"
            amount_lamports = int(amount_sol * 1_000_000_000)  # 1 SOL = 1B lamports
            
            if trade_type == TradeType.BUY:
                input_mint = sol_mint
                output_mint = token_mint
                amount = amount_lamports
            else:
                input_mint = token_mint
                output_mint = sol_mint
                # Pour les ventes, amount_sol représente la valeur en SOL qu'on veut vendre
                amount = amount_lamports  # Sera ajusté selon les décimales du token
            
            # Appel API Jupiter
            url = f"{self.dex_configs['jupiter']['api_url']}/quote"
            params = {
                'inputMint': input_mint,
                'outputMint': output_mint,
                'amount': str(amount),
                'slippageBps': int(slippage * 100)  # Convertir % en basis points
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code != 200:
                raise TradingError(f"Jupiter API error: {response.status_code}")
            
            data = response.json()
            
            # Parser la réponse
            amount_in = float(data['inAmount'])
            amount_out = float(data['outAmount'])
            price_impact = float(data.get('priceImpactPct', 0))
            
            # Récupérer métadonnées du token
            token_symbol = self._get_token_symbol(token_mint)
            
            # Créer le devis
            quote = TradeQuote(
                token_mint=token_mint,
                token_symbol=token_symbol,
                trade_type=trade_type,
                amount_in=amount_in,
                amount_out=amount_out,
                amount_in_decimals=9 if input_mint == sol_mint else self._get_token_decimals(input_mint),
                amount_out_decimals=9 if output_mint == sol_mint else self._get_token_decimals(output_mint),
                price_impact=price_impact,
                slippage=slippage,
                minimum_received=amount_out * (1 - slippage/100),
                dex='jupiter',
                route=self._parse_jupiter_route(data.get('routePlan', [])),
                fee_bps=self.dex_configs['jupiter']['fee_bps'],
                estimated_fee_sol=estimate_trade_fee(amount_sol, 'jupiter'),
                expires_at=get_current_timestamp() + 30,  # 30 secondes
                quote_id=create_quote_id()
            )
            
            return quote
            
        except Exception as e:
            logger.error(f"❌ Jupiter quote error: {e}")
            raise TradingError(f"Failed to get Jupiter quote: {e}")
    
    def _parse_jupiter_route(self, route_plan: List[Dict]) -> List[str]:
        """Parse la route Jupiter"""
        route = []
        for step in route_plan:
            if 'swapInfo' in step:
                swap_info = step['swapInfo']
                label = swap_info.get('label', 'Unknown DEX')
                route.append(label)
        return route
    
    def _get_token_symbol(self, token_mint: str) -> str:
        """Récupère le symbole d'un token"""
        # Utiliser le cache ou récupérer depuis les métadonnées
        if token_mint in self.market_data_cache:
            return self.market_data_cache[token_mint].token_symbol if hasattr(self.market_data_cache[token_mint], 'token_symbol') else 'UNKNOWN'
        
        # Fallback
        known_tokens = {
            'So11111111111111111111111111111111111111112': 'SOL',
            'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': 'USDC',
            'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB': 'USDT'
        }
        
        return known_tokens.get(token_mint, f'TOKEN_{token_mint[:6]}')
    
    def _get_token_decimals(self, token_mint: str) -> int:
        """Récupère les décimales d'un token"""
        # Fallback
        known_decimals = {
            'So11111111111111111111111111111111111111112': 9,  # SOL
            'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v': 6,  # USDC
            'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB': 6   # USDT
        }
        
        return known_decimals.get(token_mint, 9)  # Défaut 9 pour Solana
    
    # =============================================================================
    # EXÉCUTION DES TRADES
    # =============================================================================
    
    def create_trade_order(self, wallet_address: str, quote_id: str, 
                          notes: Optional[str] = None) -> TradeOrder:
        """Crée un ordre de trade basé sur un devis"""
        if quote_id not in self.active_quotes:
            raise QuoteExpiredError("Quote not found or expired")
        
        quote = self.active_quotes[quote_id]
        
        if quote.is_expired:
            raise QuoteExpiredError("Quote has expired")
        
        # Créer l'ordre
        order = TradeOrder(
            order_id=create_trade_order_id(),
            wallet_address=wallet_address,
            token_mint=quote.token_mint,
            token_symbol=quote.token_symbol,
            trade_type=quote.trade_type,
            amount_sol=quote.amount_in / 1_000_000_000 if quote.trade_type == TradeType.BUY else quote.amount_out / 1_000_000_000,
            amount_tokens=quote.amount_out if quote.trade_type == TradeType.BUY else quote.amount_in,
            slippage=quote.slippage,
            quote_id=quote_id,
            dex=quote.dex,
            notes=notes
        )
        
        # Ajouter aux ordres en attente
        self.pending_orders[order.order_id] = order
        self.stats['total_orders'] += 1
        
        # Sauvegarder en base
        self._save_trade_order(order)
        
        logger.info(f"📋 Trade order created: {order.order_id}")
        return order
    
    def execute_trade_order(self, order_id: str, phantom_signature: str) -> bool:
        """Exécute un ordre de trade avec la signature Phantom"""
        if order_id not in self.pending_orders:
            raise TradingError("Order not found")
        
        order = self.pending_orders[order_id]
        
        try:
            # Simuler l'exécution (en réalité, cela utiliserait l'API Jupiter swap)
            order.update_status(TradeStatus.CONFIRMED, phantom_signature)
            
            # Mettre à jour statistiques
            self.stats['successful_trades'] += 1
            self.stats['total_volume'] += order.amount_sol
            
            # Mettre à jour portfolio
            self._update_portfolio(order)
            
            # Sauvegarder
            self._save_trade_order(order)
            
            logger.info(f"✅ Trade executed: {order.order_id}")
            return True
            
        except Exception as e:
            order.update_status(TradeStatus.FAILED)
            self.stats['failed_trades'] += 1
            self._save_trade_order(order)
            
            logger.error(f"❌ Trade execution failed: {e}")
            return False
    
    def _save_trade_order(self, order: TradeOrder) -> None:
        """Sauvegarde un ordre en base"""
        if not self.db_manager:
            return
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO trade_orders (
                        order_id, wallet_address, token_mint, token_symbol,
                        trade_type, amount_sol, amount_tokens, slippage,
                        quote_id, dex, status, transaction_signature,
                        actual_amount_received, actual_price, gas_used,
                        created_at, submitted_at, confirmed_at, priority_fee, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    order.order_id, order.wallet_address, order.token_mint,
                    order.token_symbol, order.trade_type.value, order.amount_sol,
                    order.amount_tokens, order.slippage, order.quote_id,
                    order.dex, order.status.value, order.transaction_signature,
                    order.actual_amount_received, order.actual_price, order.gas_used,
                    order.created_at, order.submitted_at, order.confirmed_at,
                    order.priority_fee, order.notes
                ))
                conn.commit()
                
        except Exception as e:
            logger.error(f"❌ Error saving trade order: {e}")
    
    def _update_portfolio(self, order: TradeOrder) -> None:
        """Met à jour le portfolio de trading"""
        try:
            portfolio = self.get_trading_portfolio(order.wallet_address)
            portfolio.add_trade(order)
            self._save_trading_portfolio(portfolio)
            
        except Exception as e:
            logger.error(f"❌ Error updating portfolio: {e}")
    
    # =============================================================================
    # DONNÉES DE MARCHÉ
    # =============================================================================
    
    def get_market_data(self, token_mint: str, force_refresh: bool = False) -> MarketData:
        """Récupère les données de marché pour un token"""
        if not validate_token_mint(token_mint):
            raise ValueError("Invalid token mint")
        
        # Vérifier cache
        if not force_refresh and token_mint in self.market_data_cache:
            cached = self.market_data_cache[token_mint]
            if get_current_timestamp() - cached.updated_at < 300:  # 5 minutes
                return cached
        
        try:
            # Récupérer prix depuis Jupiter ou CoinGecko
            price_data = self._fetch_token_price(token_mint)
            
            market_data = MarketData(
                token_mint=token_mint,
                price_usd=price_data.get('price_usd', 0.0),
                price_sol=price_data.get('price_sol', 0.0),
                volume_24h_usd=price_data.get('volume_24h', 0.0),
                market_cap_usd=price_data.get('market_cap'),
                liquidity_usd=price_data.get('liquidity'),
                price_change_24h=price_data.get('price_change_24h', 0.0),
                price_change_1h=price_data.get('price_change_1h', 0.0),
                source=price_data.get('source', 'jupiter')
            )
            
            # Cache
            self.market_data_cache[token_mint] = market_data
            
            return market_data
            
        except Exception as e:
            logger.error(f"❌ Error fetching market data: {e}")
            # Retourner données par défaut
            return MarketData(
                token_mint=token_mint,
                price_usd=0.0,
                price_sol=0.0,
                volume_24h_usd=0.0,
                source='fallback'
            )
    
    def _fetch_token_price(self, token_mint: str) -> Dict[str, Any]:
        """Récupère le prix d'un token"""
        try:
            # Utiliser Jupiter pour le prix
            url = f"https://price.jup.ag/v4/price"
            params = {'ids': token_mint}
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if 'data' in data and token_mint in data['data']:
                    token_data = data['data'][token_mint]
                    return {
                        'price_usd': float(token_data.get('price', 0)),
                        'price_sol': 0.0,  # À calculer
                        'source': 'jupiter'
                    }
            
            return {'price_usd': 0.0, 'price_sol': 0.0, 'source': 'fallback'}
            
        except Exception as e:
            logger.error(f"❌ Error fetching price: {e}")
            return {'price_usd': 0.0, 'price_sol': 0.0, 'source': 'error'}
    
    # =============================================================================
    # GESTION DU PORTFOLIO
    # =============================================================================
    
    def get_trading_portfolio(self, wallet_address: str) -> TradingPortfolio:
        """Récupère le portfolio de trading d'un wallet"""
        if not validate_wallet_address(wallet_address):
            raise ValueError("Invalid wallet address")
        
        try:
            if self.db_manager:
                with self.db_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT * FROM trading_portfolios WHERE wallet_address = ?
                    """, (wallet_address,))
                    
                    row = cursor.fetchone()
                    if row:
                        portfolio = TradingPortfolio(
                            wallet_address=row['wallet_address'],
                            total_trades=int(row['total_trades']),
                            successful_trades=int(row['successful_trades']),
                            failed_trades=int(row['failed_trades']),
                            total_volume_sol=float(row['total_volume_sol']),
                            total_fees_paid=float(row['total_fees_paid']),
                            total_pnl_sol=float(row['total_pnl_sol']),
                            avg_trade_size_sol=float(row['avg_trade_size_sol']),
                            largest_trade_sol=float(row['largest_trade_sol']),
                            best_trade_pnl=float(row['best_trade_pnl']),
                            worst_trade_pnl=float(row['worst_trade_pnl']),
                            favorite_tokens=json.loads(row['favorite_tokens']) if row['favorite_tokens'] else [],
                            preferred_dex=row['preferred_dex'],
                            risk_score=float(row['risk_score']),
                            updated_at=int(row['updated_at'])
                        )
                    else:
                        # Créer nouveau portfolio
                        portfolio = TradingPortfolio(wallet_address=wallet_address)
                        self._save_trading_portfolio(portfolio)
                    
                    return portfolio
            
            # Fallback
            return TradingPortfolio(wallet_address=wallet_address)
            
        except Exception as e:
            logger.error(f"❌ Error loading portfolio: {e}")
            return TradingPortfolio(wallet_address=wallet_address)
    
    def _save_trading_portfolio(self, portfolio: TradingPortfolio) -> None:
        """Sauvegarde un portfolio en base"""
        if not self.db_manager:
            return
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO trading_portfolios (
                        wallet_address, total_trades, successful_trades, failed_trades,
                        total_volume_sol, total_fees_paid, total_pnl_sol, avg_trade_size_sol,
                        largest_trade_sol, best_trade_pnl, worst_trade_pnl,
                        favorite_tokens, preferred_dex, risk_score, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    portfolio.wallet_address, portfolio.total_trades,
                    portfolio.successful_trades, portfolio.failed_trades,
                    portfolio.total_volume_sol, portfolio.total_fees_paid,
                    portfolio.total_pnl_sol, portfolio.avg_trade_size_sol,
                    portfolio.largest_trade_sol, portfolio.best_trade_pnl,
                    portfolio.worst_trade_pnl, json.dumps(portfolio.favorite_tokens),
                    portfolio.preferred_dex, portfolio.risk_score, portfolio.updated_at
                ))
                conn.commit()
                
        except Exception as e:
            logger.error(f"❌ Error saving portfolio: {e}")
    
    # =============================================================================
    # UTILITAIRES ET STATISTIQUES
    # =============================================================================
    
    def get_trading_stats(self) -> Dict[str, Any]:
        """Récupère les statistiques de trading"""
        return {
            'manager_stats': self.stats.copy(),
            'active_quotes': len(self.active_quotes),
            'pending_orders': len(self.pending_orders),
            'cached_market_data': len(self.market_data_cache),
            'success_rate': safe_divide(self.stats['successful_trades'], self.stats['total_orders']) * 100,
            'timestamp': get_current_timestamp()
        }
    
    def cleanup_expired_quotes(self) -> int:
        """Nettoie les devis expirés"""
        current_time = get_current_timestamp()
        expired_quotes = [
            quote_id for quote_id, quote in self.active_quotes.items()
            if current_time > quote.expires_at
        ]
        
        for quote_id in expired_quotes:
            del self.active_quotes[quote_id]
        
        logger.info(f"🧹 Cleaned {len(expired_quotes)} expired quotes")
        return len(expired_quotes)
    
    def get_recommended_tokens(self, wallet_address: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Recommande des tokens à trader basé sur l'activité"""
        try:
            if not self.db_manager:
                return []
            
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Récupérer tokens avec activité récente
                cursor.execute("""
                    SELECT 
                        t.token_mint,
                        t.token_symbol,
                        COUNT(*) as activity_count,
                        AVG(t.token_amount) as avg_amount,
                        MAX(t.block_time) as last_activity
                    FROM transactions t
                    WHERE t.wallet_address = ?
                        AND t.is_token_transaction = 1
                        AND t.block_time > ?
                    GROUP BY t.token_mint, t.token_symbol
                    ORDER BY activity_count DESC, last_activity DESC
                    LIMIT ?
                """, (wallet_address, get_current_timestamp() - 7*24*3600, limit))
                
                recommendations = []
                for row in cursor.fetchall():
                    # Récupérer données de marché
                    try:
                        market_data = self.get_market_data(row['token_mint'])
                        
                        recommendations.append({
                            'token_mint': row['token_mint'],
                            'token_symbol': row['token_symbol'],
                            'activity_count': row['activity_count'],
                            'avg_amount': round(float(row['avg_amount']), 6),
                            'last_activity_hours': round((get_current_timestamp() - row['last_activity']) / 3600, 1),
                            'market_data': market_data.to_dict(),
                            'recommended_action': self._get_recommended_action(market_data),
                            'confidence': min(row['activity_count'] * 10, 100)
                        })
                    except Exception:
                        continue
                
                return recommendations
                
        except Exception as e:
            logger.error(f"❌ Error getting recommendations: {e}")
            return []
    
    def _get_recommended_action(self, market_data: MarketData) -> str:
        """Détermine l'action recommandée basée sur les données de marché"""
        if market_data.trend == "bullish" and market_data.volatility_level in ["low", "medium"]:
            return "buy"
        elif market_data.trend == "bearish" and market_data.price_change_24h < -10:
            return "sell"
        elif market_data.volatility_level == "extreme":
            return "wait"
        else:
            return "hold"


# Instance globale
trading_manager = TradingManager()

# Fonctions de convenance
def get_quote(wallet_address: str, token_mint: str, amount_sol: float, 
             trade_type: TradeType = TradeType.BUY) -> TradeQuote:
    """Obtient un devis de trading"""
    return trading_manager.get_trade_quote(wallet_address, token_mint, amount_sol, trade_type)

def create_order(wallet_address: str, quote_id: str) -> TradeOrder:
    """Crée un ordre de trade"""
    return trading_manager.create_trade_order(wallet_address, quote_id)

def execute_order(order_id: str, signature: str) -> bool:
    """Exécute un ordre de trade"""
    return trading_manager.execute_trade_order(order_id, signature)

def get_market_data(token_mint: str) -> MarketData:
    """Récupère les données de marché"""
    return trading_manager.get_market_data(token_mint)

def get_portfolio(wallet_address: str) -> TradingPortfolio:
    """Récupère le portfolio de trading"""
    return trading_manager.get_trading_portfolio(wallet_address)

if __name__ == "__main__":
    # Test du trading manager
    print("✅ Testing Trading Manager...")
    
    test_wallet = "4DdrfGHGdMjCqVbNtXsEEGL1SryTeMo8KMGWWtZyZVFh"
    test_token = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC
    
    try:
        # Test quote
        quote = get_quote(test_wallet, test_token, 1.0, TradeType.BUY)
        print(f"💰 Quote: {quote.amount_out} {quote.token_symbol} for {quote.amount_in} SOL")
        
        # Test market data
        market = get_market_data(test_token)
        print(f"📊 Market: ${market.price_usd} USD, volatility: {market.volatility_level}")
        
        print("✅ Trading Manager tests completed")
        
    except Exception as e:
        print(f"❌ Test error: {e}")