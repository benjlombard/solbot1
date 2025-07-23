"""
ToxiSol Trading System
File: trading.py

Advanced trading system integrating with ToxiSol via Telegram for automated
token trading with comprehensive notification support and risk management.
"""

import asyncio
import logging
import time
import json
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import sqlite3
import aiohttp
from decimal import Decimal, ROUND_DOWN

try:
    from telegram import Bot
    from telegram.error import TelegramError
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("⚠️  python-telegram-bot not installed. Trading notifications disabled.")

class TradeAction(Enum):
    BUY = "buy"
    SELL = "sell"
    CANCEL = "cancel"

class TradeStatus(Enum):
    PENDING = "pending"
    EXECUTED = "executed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL = "partial"

class RiskLevel(Enum):
    SAFE = "safe"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"

@dataclass
class TradeOrder:
    """Data class for trade orders"""
    id: str
    token_address: str
    token_symbol: str
    action: TradeAction
    amount_sol: float
    slippage: float
    priority_fee: float
    max_retries: int
    created_at: float
    status: TradeStatus
    executed_at: Optional[float] = None
    transaction_hash: Optional[str] = None
    actual_amount: Optional[float] = None
    price_per_token: Optional[float] = None
    gas_used: Optional[float] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    risk_level: RiskLevel = RiskLevel.MODERATE
    sol_received: Optional[float] = None  # ← Ajouter ceci
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()

@dataclass
class TradingPosition:
    """Data class for tracking trading positions"""
    token_address: str
    token_symbol: str
    total_invested_sol: float
    current_balance: float
    average_buy_price: float
    total_trades: int
    first_buy_at: float
    last_trade_at: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0

class ToxiSolTrader:
    """
    Advanced ToxiSol trading system with Telegram integration
    
    Features:
    - 🤖 Automated trading via ToxiSol Telegram bot
    - 📊 Real-time position tracking and PnL calculation
    - 🔔 Comprehensive notification system integration
    - ⚡ Smart retry logic with exponential backoff
    - 🛡️ Advanced risk management and safety checks
    - 📈 Performance analytics and trade history
    - 🎯 Dynamic slippage and priority fee optimization
    """
    
    def __init__(self, config, notification_manager=None):
        self.config = config['trading']
        self.toxisol_config = self.config['toxisol']
        self.notification_manager = notification_manager
        self.logger = logging.getLogger(__name__)
        self.advanced_logger = None
        
        # Trading state
        self.positions = {}  # token_address -> TradingPosition
        self.pending_orders = {}  # order_id -> TradeOrder
        self.trade_history = []
        self.is_trading_enabled = self.config.get('enabled', False)
        
        # Risk management
        self.daily_loss_limit = self.config.get('daily_loss_limit', 10.0)  # SOL
        self.max_position_size = self.config.get('max_position_size', 5.0)  # SOL
        self.daily_losses = 0.0
        self.last_reset_date = datetime.now().date()
        
        # ToxiSol integration
        self.toxisol_bot = None
        self.toxisol_chat_id = self.toxisol_config.get('chat_id')
        self.command_queue = asyncio.Queue()
        self.response_timeout = self.toxisol_config.get('response_timeout', 30)
        
        # Performance tracking
        self.total_trades_today = 0
        self.successful_trades_today = 0
        self.total_volume_today = 0.0
        
        # Initialize components
        self._setup_database()
        self._initialize_toxisol_bot()
        self._load_positions()
        self._start_command_processor()
        self.daily_reset_task = None
        self._start_daily_reset_task()
        self.logger.info("🚀 ToxiSol Trading System initialized")

    def _start_daily_reset_task(self):
        """Start the daily reset task"""
        self.daily_reset_task = asyncio.create_task(self._daily_reset_loop())
        if self.advanced_logger:
            self.advanced_logger.debug_step('trading', 'daily_reset_task_started', 'Daily reset task started')

    async def _daily_reset_loop(self):
        """Daily reset loop that runs continuously"""
        while True:
            try:
                # Check if we need to reset (every hour for precision)
                await self.reset_daily_limits()
        
                # Sleep for 1 hour before checking again
                await asyncio.sleep(3600)  # 1 hour = 3600 seconds
        
            except Exception as e:
                self.logger.error(f"Error in daily reset loop: {e}")
                if self.advanced_logger:
                    self.advanced_logger.debug_step('trading', 'daily_reset_error', f'Daily reset loop error: {e}')
                # Wait 5 minutes before retrying on error
                await asyncio.sleep(300)
        
        
    def set_advanced_logger(self, advanced_logger):
        """Set advanced logger instance"""
        self.advanced_logger = advanced_logger
    
    def _get_db_connection(self):
        """Get database connection"""
        return sqlite3.connect('trading.db')
    
    def _validate_inputs(self, token_address: str, amount_sol: float, slippage: float, priority_fee: float):
        """Validate trading inputs"""
        if not token_address or len(token_address) < 32:
            raise ValueError("Invalid token address format")
        if amount_sol <= 0:
            raise ValueError("Amount must be positive") 
        if not (0 <= slippage <= 100):
            raise ValueError("Slippage must be between 0 and 100")
        if priority_fee < 0:
            raise ValueError("Priority fee cannot be negative")
    
    def _setup_database(self):
        """Setup trading database tables"""
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            # Trade orders table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trade_orders (
                    id TEXT PRIMARY KEY,
                    token_address TEXT NOT NULL,
                    token_symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    amount_sol REAL NOT NULL,
                    slippage REAL NOT NULL,
                    priority_fee REAL NOT NULL,
                    max_retries INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    executed_at INTEGER,
                    transaction_hash TEXT,
                    actual_amount REAL,
                    price_per_token REAL,
                    gas_used REAL,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    risk_level TEXT DEFAULT 'moderate',
                    sol_received REAL
                )
            ''')
            
            # Positions table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS positions (
                    token_address TEXT PRIMARY KEY,
                    token_symbol TEXT NOT NULL,
                    total_invested_sol REAL NOT NULL,
                    current_balance REAL NOT NULL,
                    average_buy_price REAL NOT NULL,
                    total_trades INTEGER NOT NULL,
                    first_buy_at INTEGER NOT NULL,
                    last_trade_at INTEGER NOT NULL,
                    unrealized_pnl REAL DEFAULT 0,
                    realized_pnl REAL DEFAULT 0
                )
            ''')
            
            # Performance stats table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trading_stats (
                    date TEXT PRIMARY KEY,
                    total_trades INTEGER DEFAULT 0,
                    successful_trades INTEGER DEFAULT 0,
                    total_volume_sol REAL DEFAULT 0,
                    total_pnl REAL DEFAULT 0,
                    daily_losses REAL DEFAULT 0
                )
            ''')
            
            # Create indexes
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_orders_status ON trade_orders(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_orders_created ON trade_orders(created_at)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(token_symbol)')
            
            conn.commit()
            conn.close()
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'database_setup', 
                                               'Trading database initialized')
                
        except Exception as e:
            self.logger.error(f"Error setting up database: {e}")

    async def _remove_position_from_db(self, token_address: str):
        """Remove position from database"""
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute('DELETE FROM positions WHERE token_address = ?', (token_address,))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            self.logger.error(f"Error removing position from database: {e}")

    async def _update_daily_stats(self):
        """Update daily trading statistics"""
        try:
            today = datetime.now().date().isoformat()
            
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            # Calculate daily PnL
            total_pnl = sum(pos.realized_pnl + pos.unrealized_pnl for pos in self.positions.values())
            
            cursor.execute('''
                INSERT OR REPLACE INTO trading_stats 
                (date, total_trades, successful_trades, total_volume_sol, total_pnl, daily_losses)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                today, self.total_trades_today, self.successful_trades_today,
                self.total_volume_today, total_pnl, self.daily_losses
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            self.logger.error(f"Error updating daily stats: {e}")

    async def _send_trade_notification(self, order: TradeOrder, event_type: str):
        """Send trading notification"""
        if not self.notification_manager:
            return
            
        try:
            if event_type == "initiated":
                title = f"📋 TRADE INITIATED: {order.token_symbol}"
                message = f"Trade order created: {order.action.value.upper()} {order.amount_sol} SOL"
            elif event_type == "executed":
                title = f"✅ TRADE EXECUTED: {order.token_symbol}"
                message = f"Successfully {order.action.value}ed {order.actual_amount or 'N/A'} tokens"
                if order.transaction_hash:
                    message += f"\nTx: {order.transaction_hash[:16]}..."
            elif event_type == "failed":
                title = f"❌ TRADE FAILED: {order.token_symbol}"
                message = f"Trade failed: {order.error_message or 'Unknown error'}"
            else:
                return
            
            # Prepare notification data
            notification_data = {
                'token_address': order.token_address,
                'token_symbol': order.token_symbol,
                'action': order.action.value,
                'amount_sol': order.amount_sol,
                'status': order.status.value,
                'risk_level': order.risk_level.value,
                'slippage': order.slippage,
                'priority_fee': order.priority_fee
            }
            
            if order.executed_at:
                notification_data['executed_at'] = datetime.fromtimestamp(order.executed_at).isoformat()
            if order.transaction_hash:
                notification_data['transaction_hash'] = order.transaction_hash
            if order.actual_amount:
                notification_data['actual_amount'] = order.actual_amount
            if order.price_per_token:
                notification_data['price_per_token'] = order.price_per_token
                
            await self.notification_manager.send_trade_notification(
                order.action.value,
                order.token_symbol,
                order.amount_sol,
                notification_data
            )
            
        except Exception as e:
            self.logger.error(f"Error sending trade notification: {e}")

    def _generate_order_id(self, token_address: str, action: TradeAction, amount: float) -> str:
        """Generate unique order ID"""
        content = f"{token_address}:{action.value}:{amount}:{time.time()}"
        return hashlib.md5(content.encode()).hexdigest()[:12]

    async def buy_token(self, token_address: str, token_symbol: str, amount_sol: float, 
                       slippage: float = 10.0, priority_fee: float = 0.005) -> TradeOrder:
        """Buy token with specified SOL amount"""
        self._validate_inputs(token_address, amount_sol, slippage, priority_fee)
        return await self.execute_trade(
            token_address=token_address,
            token_symbol=token_symbol,
            action=TradeAction.BUY,
            amount_sol=amount_sol,
            slippage=slippage,
            priority_fee=priority_fee
        )

    async def sell_token(self, token_address: str, token_symbol: str, 
                        percentage: Optional[float] = None, amount_sol: Optional[float] = None,
                        slippage: float = 10.0, priority_fee: float = 0.005) -> TradeOrder:
        """Sell token by percentage or SOL amount"""
        position = self.positions.get(token_address)
        if not position:
            raise Exception(f"No position found for {token_symbol}")
        
        if percentage is not None:
            # Sell by percentage
            if not (0 < percentage <= 100):
                raise ValueError("Percentage must be between 0 and 100")
            
            sell_amount_tokens = position.current_balance * (percentage / 100)
            estimated_sol = sell_amount_tokens * position.average_buy_price
            
            # Validate inputs for percentage-based sale
            self._validate_inputs(token_address, estimated_sol, slippage, priority_fee)
            
            order = await self.execute_trade(
                token_address=token_address,
                token_symbol=token_symbol,
                action=TradeAction.SELL,
                amount_sol=estimated_sol,
                slippage=slippage,
                priority_fee=priority_fee
            )
            order.sell_percentage = percentage
            return order
            
        elif amount_sol is not None:
            # Sell by SOL amount
            self._validate_inputs(token_address, amount_sol, slippage, priority_fee)  # ← Ajouter ceci
            return await self.execute_trade(
                token_address=token_address,
                token_symbol=token_symbol,
                action=TradeAction.SELL,
                amount_sol=amount_sol,
                slippage=slippage,
                priority_fee=priority_fee
            )
        else:
            raise ValueError("Must specify either percentage or amount_sol")

    async def sell_all_token(self, token_address: str, token_symbol: str,
                            slippage: float = 10.0, priority_fee: float = 0.005) -> TradeOrder:
        """Sell all tokens (100%)"""
        return await self.sell_token(
            token_address=token_address,
            token_symbol=token_symbol,
            percentage=100.0,
            slippage=slippage,
            priority_fee=priority_fee
        )

    def get_position(self, token_address: str) -> Optional[TradingPosition]:
        """Get current position for token"""
        return self.positions.get(token_address)

    def get_all_positions(self) -> List[TradingPosition]:
        """Get all current positions"""
        return list(self.positions.values())

    async def update_position_pnl(self, token_address: str, current_price: float):
        """Update unrealized PnL for position"""
        position = self.positions.get(token_address)
        if not position:
            return
            
        try:
            # Calculate unrealized PnL
            current_value = position.current_balance * current_price
            position.unrealized_pnl = current_value - position.total_invested_sol
            
            # Save to database
            await self._save_position(position)
            
        except Exception as e:
            self.logger.error(f"Error updating position PnL: {e}")

    def get_portfolio_summary(self) -> Dict:
        """Get comprehensive portfolio summary"""
        try:
            total_invested = sum(pos.total_invested_sol for pos in self.positions.values())
            total_realized_pnl = sum(pos.realized_pnl for pos in self.positions.values())
            total_unrealized_pnl = sum(pos.unrealized_pnl for pos in self.positions.values())
            total_pnl = total_realized_pnl + total_unrealized_pnl
            
            summary = {
                'total_positions': len(self.positions),
                'total_invested_sol': total_invested,
                'total_realized_pnl': total_realized_pnl,
                'total_unrealized_pnl': total_unrealized_pnl,
                'total_pnl': total_pnl,
                'roi_percentage': (total_pnl / total_invested * 100) if total_invested > 0 else 0,
                'daily_trades': self.total_trades_today,
                'daily_success_rate': (self.successful_trades_today / max(self.total_trades_today, 1)) * 100,
                'daily_volume': self.total_volume_today,
                'daily_losses': self.daily_losses,
                'remaining_daily_limit': self.daily_loss_limit - self.daily_losses,
                'positions': [asdict(pos) for pos in self.positions.values()]
            }
            
            return summary
            
        except Exception as e:
            self.logger.error(f"Error generating portfolio summary: {e}")
            return {}

    async def get_trade_history(self, limit: int = 100, token_address: str = None) -> List[Dict]:
        """Get trade history"""
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            query = 'SELECT * FROM trade_orders'
            params = []
            
            if token_address:
                query += ' WHERE token_address = ?'
                params.append(token_address)
                
            query += ' ORDER BY created_at DESC LIMIT ?'
            params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            # Convert to dict format
            columns = [description[0] for description in cursor.description]
            history = []
            
            for row in rows:
                trade_dict = dict(zip(columns, row))
                # Convert timestamps to readable format
                if trade_dict['created_at']:
                    trade_dict['created_at_readable'] = datetime.fromtimestamp(trade_dict['created_at']).isoformat()
                if trade_dict['executed_at']:
                    trade_dict['executed_at_readable'] = datetime.fromtimestamp(trade_dict['executed_at']).isoformat()
                history.append(trade_dict)
            
            conn.close()
            return history
            
        except Exception as e:
            self.logger.error(f"Error getting trade history: {e}")
            return []

    async def cancel_pending_order(self, order_id: str) -> bool:
        """Cancel a pending order"""
        try:
            order = self.pending_orders.get(order_id)
            if not order:
                return False
                
            if order.status != TradeStatus.PENDING:
                return False
                
            # Update order status
            order.status = TradeStatus.CANCELLED
            order.error_message = "Cancelled by user"
            
            # Save to database
            await self._save_order(order)
            
            # Remove from pending
            self.pending_orders.pop(order_id, None)
            
            # Send notification
            if self.notification_manager:
                await self._send_trade_notification(order, "cancelled")
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'order_cancelled', 
                                               f'Order {order_id} cancelled')
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error cancelling order: {e}")
            return False

    async def set_trading_enabled(self, enabled: bool):
        """Enable or disable trading"""
        self.is_trading_enabled = enabled
        
        if self.advanced_logger:
            status = "enabled" if enabled else "disabled"
            self.advanced_logger.debug_step('trading', 'trading_status_changed', 
                                           f'Trading {status}')
        
        # Send notification
        if self.notification_manager:
            status_msg = "enabled" if enabled else "disabled"
            await self.notification_manager.send_system_notification(
                f"🔄 Trading {status_msg.title()}",
                f"Trading has been {status_msg} for ToxiSol integration"
            )

    def get_pending_orders(self) -> List[TradeOrder]:
        """Get all pending orders"""
        return list(self.pending_orders.values())

    async def reset_daily_limits(self):
        """Reset daily trading limits"""
        current_date = datetime.now().date()
        
        if current_date != self.last_reset_date:
            # Store previous values for logging
            prev_losses = self.daily_losses
            prev_trades = self.total_trades_today
            
            # Reset counters
            self.daily_losses = 0.0
            self.total_trades_today = 0
            self.successful_trades_today = 0
            self.total_volume_today = 0.0
            self.last_reset_date = current_date
            
            # Log the reset
            self.logger.info(f"📅 Daily limits reset - Previous: {prev_trades} trades, {prev_losses:.3f} SOL losses")
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'daily_limits_reset', 
                                               f'Daily trading limits reset - Date: {current_date}')
            
            # Send reset notification
            if self.notification_manager:
                await self.notification_manager.send_system_notification(
                    "📅 Daily Reset",
                    f"Trading limits reset for {current_date}",
                    {
                        'previous_trades': prev_trades,
                        'previous_losses': prev_losses,
                        'reset_date': current_date.isoformat()
                    }
                )

    async def emergency_stop(self):
        """Emergency stop all trading"""
        try:
            # Disable trading
            self.is_trading_enabled = False
            
            # Cancel all pending orders
            cancelled_count = 0
            for order_id in list(self.pending_orders.keys()):
                if await self.cancel_pending_order(order_id):
                    cancelled_count += 1
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'emergency_stop', 
                                               f'Emergency stop executed - {cancelled_count} orders cancelled')
            
            # Send critical notification
            if self.notification_manager:
                await self.notification_manager.send_error_notification(
                    "EMERGENCY_STOP",
                    f"Trading emergency stop executed - {cancelled_count} orders cancelled",
                    {'cancelled_orders': cancelled_count, 'timestamp': datetime.now().isoformat()}
                )
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error during emergency stop: {e}")
            return False

    async def get_trading_performance(self, days: int = 7) -> Dict:
        """Get trading performance metrics"""
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            # Get performance data for specified days
            start_date = (datetime.now() - timedelta(days=days)).date().isoformat()
            
            cursor.execute('''
                SELECT date, total_trades, successful_trades, total_volume_sol, total_pnl, daily_losses
                FROM trading_stats 
                WHERE date >= ?
                ORDER BY date DESC
            ''', (start_date,))
            
            rows = cursor.fetchall()
            
            # Calculate aggregated metrics
            total_trades = sum(row[1] for row in rows)
            total_successful = sum(row[2] for row in rows)
            total_volume = sum(row[3] for row in rows)
            total_pnl = sum(row[4] for row in rows)
            total_losses = sum(row[5] for row in rows)
            
            success_rate = (total_successful / max(total_trades, 1)) * 100
            avg_trade_size = total_volume / max(total_trades, 1)
            
            performance = {
                'period_days': days,
                'total_trades': total_trades,
                'successful_trades': total_successful,
                'success_rate': success_rate,
                'total_volume_sol': total_volume,
                'total_pnl': total_pnl,
                'total_losses': total_losses,
                'avg_trade_size': avg_trade_size,
                'daily_breakdown': [
                    {
                        'date': row[0],
                        'trades': row[1],
                        'successful': row[2],
                        'volume': row[3],
                        'pnl': row[4],
                        'losses': row[5]
                    }
                    for row in rows
                ]
            }
            
            conn.close()
            return performance
            
        except Exception as e:
            self.logger.error(f"Error getting trading performance: {e}")
            return {}

    async def optimize_trading_parameters(self, token_address: str) -> Dict:
        """Optimize trading parameters based on historical performance"""
        try:
            # Get historical trades for this token
            history = await self.get_trade_history(limit=50, token_address=token_address)
            
            if len(history) < 5:
                return {'message': 'Insufficient trade history for optimization'}
            
            # Analyze successful vs failed trades
            successful_trades = [t for t in history if t['status'] == 'executed']
            failed_trades = [t for t in history if t['status'] == 'failed']
            
            # Calculate optimal slippage
            if successful_trades:
                avg_successful_slippage = sum(t['slippage'] for t in successful_trades) / len(successful_trades)
                recommended_slippage = min(avg_successful_slippage * 1.1, 50.0)  # 10% buffer, max 50%
            else:
                recommended_slippage = 15.0  # Default
            
            # Calculate optimal priority fee
            if successful_trades:
                avg_successful_priority = sum(t['priority_fee'] for t in successful_trades) / len(successful_trades)
                recommended_priority = max(avg_successful_priority, 0.001)  # Minimum 0.001 SOL
            else:
                recommended_priority = 0.005  # Default
            
            optimization = {
                'recommended_slippage': round(recommended_slippage, 1),
                'recommended_priority_fee': round(recommended_priority, 6),
                'analysis': {
                    'total_trades': len(history),
                    'successful_trades': len(successful_trades),
                    'failed_trades': len(failed_trades),
                    'success_rate': (len(successful_trades) / len(history)) * 100,
                    'avg_successful_slippage': round(avg_successful_slippage, 1) if successful_trades else None,
                    'avg_successful_priority': round(avg_successful_priority, 6) if successful_trades else None
                }
            }
            
            return optimization
            
        except Exception as e:
            self.logger.error(f"Error optimizing trading parameters: {e}")
            return {'error': str(e)}


    def _initialize_toxisol_bot(self):
        """Initialize ToxiSol Telegram bot connection"""
        if not TELEGRAM_AVAILABLE:
            self.logger.warning("🤖 Telegram not available for ToxiSol integration")
            return
            
        bot_token = self.toxisol_config.get('bot_token')
        if not bot_token:
            self.logger.warning("🤖 ToxiSol bot token not configured")
            return
            
        try:
            self.toxisol_bot = Bot(token=bot_token)
            self.logger.info("🤖 ToxiSol bot initialized successfully")
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'toxisol_init_success', 
                                               'ToxiSol bot connection established')
        except Exception as e:
            self.logger.error(f"🤖 Failed to initialize ToxiSol bot: {e}")
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'toxisol_init_failed', 
                                               f'ToxiSol initialization failed: {e}')

    def _load_positions(self):
            """Load existing positions from database"""
            try:
                conn = self._get_db_connection()
                cursor = conn.cursor()
                
                cursor.execute('SELECT * FROM positions')
                rows = cursor.fetchall()
                
                for row in rows:
                    position = TradingPosition(
                        token_address=row[0],
                        token_symbol=row[1],
                        total_invested_sol=row[2],
                        current_balance=row[3],
                        average_buy_price=row[4],
                        total_trades=row[5],
                        first_buy_at=row[6],
                        last_trade_at=row[7],
                        unrealized_pnl=row[8] or 0.0,
                        realized_pnl=row[9] or 0.0
                    )
                    self.positions[row[0]] = position
                
                conn.close()
                
                if self.advanced_logger:
                    self.advanced_logger.debug_step('trading', 'positions_loaded', 
                                                f'Loaded {len(self.positions)} positions')
                    
            except Exception as e:
                self.logger.error(f"Error loading positions: {e}")


    def _start_command_processor(self):
        """Start the ToxiSol command processor"""
        if self.toxisol_bot:
            asyncio.create_task(self._process_toxisol_commands())
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'command_processor_started', 
                                               'ToxiSol command processor started')

    async def shutdown(self):
        """Gracefully shutdown trading system"""
        try:
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'shutdown_start', 
                                               'Starting trading system shutdown')
            
            # Cancel daily reset task
            if self.daily_reset_task and not self.daily_reset_task.done():
                self.daily_reset_task.cancel()
                try:
                    await self.daily_reset_task
                except asyncio.CancelledError:
                    pass
            # Disable new trades
            self.is_trading_enabled = False
            
            # Wait for pending commands to complete
            if not self.command_queue.empty():
                await self.command_queue.join()
            
            # Update final stats
            await self._update_daily_stats()
            
            # Send shutdown notification
            if self.notification_manager:
                await self.notification_manager.send_system_notification(
                    "🔴 Trading System Shutdown",
                    f"Trading system shutdown with {len(self.pending_orders)} pending orders",
                    {
                        'pending_orders': len(self.pending_orders),
                        'active_positions': len(self.positions),
                        'daily_trades': self.total_trades_today
                    }
                )
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'shutdown_complete', 
                                               'Trading system shutdown complete')
            
        except Exception as e:
            self.logger.error(f"Error during trading system shutdown: {e}")


# Utility functions for integration

def create_trader(config, notification_manager=None):
    """Factory function to create trader instance"""
    return ToxiSolTrader(config, notification_manager)

async def quick_buy(token_address: str, token_symbol: str, amount_sol: float, 
                   trader: ToxiSolTrader) -> TradeOrder:
    """Quick buy function for simple integrations"""
    return await trader.buy_token(token_address, token_symbol, amount_sol)

async def quick_sell(token_address: str, token_symbol: str, percentage: float,
                    trader: ToxiSolTrader) -> TradeOrder:
    """Quick sell function for simple integrations"""
    return await trader.sell_token(token_address, token_symbol, percentage=percentage)

def get_default_trading_config():
    """Get default trading configuration"""
    return {
        'trading': {
            'enabled': False,
            'daily_loss_limit': 10.0,  # SOL
            'max_position_size': 5.0,  # SOL
            'min_trade_amount': 0.01,  # SOL
            'max_trade_amount': 10.0,  # SOL
            'max_slippage': 50.0,  # %
            'default_slippage': 10.0,  # %
            'default_priority_fee': 0.005,  # SOL
            'toxisol': {
                'bot_token': '',  # ToxiSol bot token
                'chat_id': '',   # ToxiSol chat ID
                'response_timeout': 30,  # seconds
                'max_retries': 3
            }
        }
    } 

    

    

    

    async def _process_toxisol_commands(self):
        """Process ToxiSol trading commands from queue"""
        while True:
            try:
                # Wait for command with timeout
                try:
                    command_data = await asyncio.wait_for(
                        self.command_queue.get(), 
                        timeout=5.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                # Process the command
                await self._execute_toxisol_command(command_data)
                
                # Mark task as done
                self.command_queue.task_done()
                
            except Exception as e:
                self.logger.error(f"Error in ToxiSol command processor: {e}")
                if self.advanced_logger:
                    self.advanced_logger.debug_step('trading', 'command_processor_error', 
                                                   f'Command processor error: {e}')
                await asyncio.sleep(1)

    async def execute_trade(self, token_address: str, token_symbol: str, action: TradeAction, 
                          amount_sol: float, slippage: float = 10.0, priority_fee: float = 0.005,
                          max_retries: int = 3) -> TradeOrder:
        """
        Execute a trade order via ToxiSol
        
        Args:
            token_address: The token contract address
            token_symbol: Token symbol for display
            action: BUY or SELL
            amount_sol: Amount in SOL to trade
            slippage: Slippage tolerance (default 10%)
            priority_fee: Priority fee in SOL (default 0.005)
            max_retries: Maximum retry attempts
            
        Returns:
            TradeOrder object with execution details
        """
        
        # Ajouter cette ligne au tout début, après la docstring
        self._validate_inputs(token_address, amount_sol, slippage, priority_fee)
        
        if not self.is_trading_enabled:
            raise Exception("Trading is disabled")
            
        if not self.toxisol_bot:
            raise Exception("ToxiSol bot not initialized")
        
        # Generate unique order ID
        order_id = self._generate_order_id(token_address, action, amount_sol)
        
        # Create trade order
        order = TradeOrder(
            id=order_id,
            token_address=token_address,
            token_symbol=token_symbol,
            action=action,
            amount_sol=amount_sol,
            slippage=slippage,
            priority_fee=priority_fee,
            max_retries=max_retries,
            created_at=time.time(),
            status=TradeStatus.PENDING,
            risk_level=self._assess_trade_risk(action, amount_sol)
        )
        
        # Risk management checks
        if not await self._validate_trade_risk(order):
            order.status = TradeStatus.FAILED
            order.error_message = "Trade rejected by risk management"
            await self._save_order(order)
            return order
        
        # Add to pending orders
        self.pending_orders[order_id] = order
        
        # Save to database
        await self._save_order(order)
        
        # Send notification
        if self.notification_manager:
            await self._send_trade_notification(order, "initiated")
        
        if self.advanced_logger:
            self.advanced_logger.debug_step('trading', 'trade_initiated', 
                                           f'Trade {order_id} initiated: {action.value} {amount_sol} SOL of {token_symbol}')
        
        # Queue command for execution
        command_data = {
            'order': order,
            'attempt': 1
        }
        await self.command_queue.put(command_data)
        
        return order

    async def _execute_toxisol_command(self, command_data: Dict):
        """Execute ToxiSol command via Telegram"""
        order = command_data['order']
        attempt = command_data['attempt']
        
        try:
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'toxisol_command_start', 
                                               f'Executing ToxiSol command for order {order.id}, attempt {attempt}')
            
            # Build ToxiSol command
            toxisol_command = self._build_toxisol_command(order)
            
            # Send command to ToxiSol bot
            start_time = time.time()
            message = await self.toxisol_bot.send_message(
                chat_id=self.toxisol_chat_id,
                text=toxisol_command,
                parse_mode='Markdown'
            )
            
            # Wait for response and parse result
            result = await self._wait_for_toxisol_response(order, message.message_id)
            
            execution_time = time.time() - start_time
            
            if result['success']:
                order.status = TradeStatus.EXECUTED
                order.executed_at = time.time()
                order.transaction_hash = result.get('tx_hash')
                order.actual_amount = result.get('amount')
                order.price_per_token = result.get('price')
                order.gas_used = result.get('gas_fee', order.priority_fee)
                order.sol_received = result.get('sol_received', order.amount_sol)  # ← AJOUTER CECI
                
                # Update position
                await self._update_position(order)
                
                # Update stats
                self.successful_trades_today += 1
                self.total_volume_today += order.amount_sol
                
                if self.advanced_logger:
                    self.advanced_logger.debug_step('trading', 'trade_success', 
                                                   f'Trade {order.id} executed successfully in {execution_time:.2f}s')
                
                # Send success notification
                if self.notification_manager:
                    await self._send_trade_notification(order, "executed")
                    
            else:
                # Handle failure
                order.retry_count += 1
                order.error_message = result.get('error', 'Unknown error')
                
                if order.retry_count < order.max_retries:
                    # Retry with exponential backoff
                    retry_delay = min(60, 2 ** order.retry_count)
                    await asyncio.sleep(retry_delay)
                    
                    command_data['attempt'] = attempt + 1
                    await self.command_queue.put(command_data)
                    
                    if self.advanced_logger:
                        self.advanced_logger.debug_step('trading', 'trade_retry', 
                                                       f'Retrying trade {order.id}, attempt {order.retry_count + 1}')
                else:
                    # Max retries reached
                    order.status = TradeStatus.FAILED
                    
                    if self.advanced_logger:
                        self.advanced_logger.debug_step('trading', 'trade_failed', 
                                                       f'Trade {order.id} failed after {order.retry_count} attempts')
                    
                    # Send failure notification
                    if self.notification_manager:
                        await self._send_trade_notification(order, "failed")
            
            # Update order in database
            await self._save_order(order)
            
            # Remove from pending if completed
            if order.status in [TradeStatus.EXECUTED, TradeStatus.FAILED, TradeStatus.CANCELLED]:
                self.pending_orders.pop(order.id, None)
                
            # Update daily stats
            self.total_trades_today += 1
            await self._update_daily_stats()
                
        except Exception as e:
            order.status = TradeStatus.FAILED
            order.error_message = f"Execution error: {str(e)}"
            await self._save_order(order)
            
            self.logger.error(f"Error executing ToxiSol command: {e}")
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'toxisol_command_error', 
                                               f'Command execution failed: {e}')

    def _build_toxisol_command(self, order: TradeOrder) -> str:
        """Build ToxiSol command string"""
        if order.action == TradeAction.BUY:
            command = f"/buy {order.token_address} {order.amount_sol}"
        elif order.action == TradeAction.SELL:
            # For sell, we need to determine if it's percentage or amount
            if hasattr(order, 'sell_percentage'):
                command = f"/sell {order.token_address} {order.sell_percentage}%"
            else:
                command = f"/sell {order.token_address} {order.amount_sol}"
        else:
            raise ValueError(f"Unsupported trade action: {order.action}")
        
        # Add optional parameters
        if order.slippage != 10.0:  # Default slippage
            command += f" --slippage {order.slippage}"
            
        if order.priority_fee != 0.005:  # Default priority fee
            command += f" --priority {order.priority_fee}"
            
        return command

    async def _wait_for_toxisol_response(self, order: TradeOrder, command_message_id: int) -> Dict:
        """Wait for and parse ToxiSol response"""
        start_time = time.time()
        
        while time.time() - start_time < self.response_timeout:
            try:
                # Get recent messages from ToxiSol chat
                updates = await self.toxisol_bot.get_updates(
                    offset=-10,  # Get last 10 messages
                    timeout=5
                )
                
                for update in updates:
                    if not update.message:
                        continue
                        
                    message = update.message
                    
                    # Check if it's a response to our command
                    if (message.chat.id == self.toxisol_chat_id and 
                        message.date.timestamp() > start_time):
                        
                        # Parse ToxiSol response
                        result = self._parse_toxisol_response(message.text, order)
                        if result:
                            return result
                
                await asyncio.sleep(2)  # Check every 2 seconds
                
            except Exception as e:
                self.logger.error(f"Error waiting for ToxiSol response: {e}")
                await asyncio.sleep(1)
        
        # Timeout reached
        return {
            'success': False,
            'error': f'ToxiSol response timeout after {self.response_timeout}s'
        }

    def _parse_toxisol_response(self, response_text: str, order: TradeOrder) -> Optional[Dict]:
        """Parse ToxiSol bot response"""
        try:
            text = response_text.lower()
            
            # Success patterns
            if 'transaction successful' in text or 'swap completed' in text:
                result = {'success': True}
                
                # Extract transaction hash
                import re
                tx_pattern = r'(?:tx|hash|transaction)[\s:]*([a-f0-9]{64,88})'
                tx_match = re.search(tx_pattern, text, re.IGNORECASE)
                if tx_match:
                    result['tx_hash'] = tx_match.group(1)
                
                # Extract amount
                amount_pattern = r'(?:received|bought|sold)[\s:]*([0-9,]+\.?[0-9]*)'
                amount_match = re.search(amount_pattern, text)
                if amount_match:
                    result['amount'] = float(amount_match.group(1).replace(',', ''))
                
                # Extract SOL received (for sell orders)
                sol_received_pattern = r'(?:received|got|earned)[\s:]*([0-9]+\.?[0-9]*)\s*(?:sol|SOL)'
                sol_match = re.search(sol_received_pattern, text, re.IGNORECASE)
                if sol_match:
                    result['sol_received'] = float(sol_match.group(1))
                
                # Extract price
                price_pattern = r'(?:price|rate)[\s:]*([0-9]+\.?[0-9]*(?:e-?[0-9]+)?)'
                price_match = re.search(price_pattern, text)
                if price_match:
                    result['price'] = float(price_match.group(1))
                
                # Extract gas fee
                gas_pattern = r'(?:gas|fee)[\s:]*([0-9]+\.?[0-9]*)'
                gas_match = re.search(gas_pattern, text)
                if gas_match:
                    result['gas_fee'] = float(gas_match.group(1))
                
                return result
            
            # Error patterns
            elif any(keyword in text for keyword in ['error', 'failed', 'insufficient', 'invalid']):
                return {
                    'success': False,
                    'error': response_text.strip()
                }
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error parsing ToxiSol response: {e}")
            return None

    async def _validate_trade_risk(self, order: TradeOrder) -> bool:
        """Validate trade against risk management rules"""
        try:
            # Check if trading is enabled
            if not self.is_trading_enabled:
                return False
            
            # Check daily loss limit
            if self.daily_losses >= self.daily_loss_limit:
                if self.advanced_logger:
                    self.advanced_logger.debug_step('trading', 'risk_daily_limit', 
                                                   f'Daily loss limit reached: {self.daily_losses} SOL')
                return False
            
            # Check position size limit
            if order.action == TradeAction.BUY:
                current_position = self.positions.get(order.token_address)
                if current_position:
                    new_total = current_position.total_invested_sol + order.amount_sol
                    if new_total > self.max_position_size:
                        if self.advanced_logger:
                            self.advanced_logger.debug_step('trading', 'risk_position_limit', 
                                                           f'Position size limit exceeded: {new_total} SOL')
                        return False
                elif order.amount_sol > self.max_position_size:
                    return False
            
            # Check minimum trade amount
            min_trade = self.config.get('min_trade_amount', 0.01)
            if order.amount_sol < min_trade:
                return False
            
            # Check maximum trade amount
            max_trade = self.config.get('max_trade_amount', 10.0)
            if order.amount_sol > max_trade:
                return False
            
            # Check slippage limits
            max_slippage = self.config.get('max_slippage', 50.0)
            if order.slippage > max_slippage:
                return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error validating trade risk: {e}")
            return False

    def _assess_trade_risk(self, action: TradeAction, amount_sol: float) -> RiskLevel:
        """Assess risk level of a trade"""
        try:
            # Base risk on amount
            if amount_sol >= 5.0:
                risk = RiskLevel.HIGH
            elif amount_sol >= 2.0:
                risk = RiskLevel.MODERATE
            else:
                risk = RiskLevel.SAFE
            
            # Increase risk for sells in loss
            if action == TradeAction.SELL and self.daily_losses > 0:
                if risk == RiskLevel.SAFE:
                    risk = RiskLevel.MODERATE
                elif risk == RiskLevel.MODERATE:
                    risk = RiskLevel.HIGH
            
            # Critical risk if approaching limits
            if (amount_sol + self.daily_losses) >= self.daily_loss_limit * 0.8:
                risk = RiskLevel.CRITICAL
                
            return risk
            
        except Exception as e:
            self.logger.error(f"Error assessing trade risk: {e}")
            return RiskLevel.HIGH

    async def _update_position(self, order: TradeOrder):
        """Update position after trade execution"""
        try:
            token_address = order.token_address
            position = self.positions.get(token_address)
            
            if order.action == TradeAction.BUY:
                if position:
                    # Update existing position
                    old_total = position.total_invested_sol
                    old_balance = position.current_balance
                    
                    position.total_invested_sol += order.amount_sol
                    position.current_balance += order.actual_amount or 0
                    position.total_trades += 1
                    position.last_trade_at = order.executed_at
                    
                    # Recalculate average buy price
                    if position.current_balance > 0:
                        position.average_buy_price = position.total_invested_sol / position.current_balance
                else:
                    # Create new position
                    position = TradingPosition(
                        token_address=token_address,
                        token_symbol=order.token_symbol,
                        total_invested_sol=order.amount_sol,
                        current_balance=order.actual_amount or 0,
                        average_buy_price=order.price_per_token or 0,
                        total_trades=1,
                        first_buy_at=order.executed_at,
                        last_trade_at=order.executed_at
                    )
                    self.positions[token_address] = position
                    
            elif order.action == TradeAction.SELL:
                if position:
                    # Calculate realized PnL
                    sell_amount = order.actual_amount or 0
                    sell_value_sol = getattr(order, 'sol_received', order.amount_sol)
                    cost_basis = sell_amount * position.average_buy_price
                    realized_pnl = sell_value_sol - cost_basis
                    
                    # Update position
                    position.current_balance -= sell_amount
                    position.realized_pnl += realized_pnl
                    position.total_trades += 1
                    position.last_trade_at = order.executed_at
                    
                    # If position is closed, remove it
                    if position.current_balance <= 0:
                        self.positions.pop(token_address, None)
                        await self._remove_position_from_db(token_address)
                    else:
                        await self._save_position(position)
                else:
                    self.logger.warning(f"Sell order for unknown position: {token_address}")
                    return
            
            # Save position to database
            if position and token_address in self.positions:
                await self._save_position(position)
                
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'position_updated', 
                                               f'Updated position for {order.token_symbol}')
                
        except Exception as e:
            self.logger.error(f"Error updating position: {e}")

    async def _save_order(self, order: TradeOrder):
        """Save trade order to database"""
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO trade_orders 
                (id, token_address, token_symbol, action, amount_sol, slippage, priority_fee,
                 max_retries, created_at, status, executed_at, transaction_hash, actual_amount,
                 price_per_token, gas_used, error_message, retry_count, risk_level, sol_received)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                order.id, order.token_address, order.token_symbol, order.action.value,
                order.amount_sol, order.slippage, order.priority_fee, order.max_retries,
                order.created_at, order.status.value, order.executed_at, order.transaction_hash,
                order.actual_amount, order.price_per_token, order.gas_used, order.error_message,
                order.retry_count, order.risk_level.value, order.sol_received
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            self.logger.error(f"Error saving order to database: {e}")

    async def _save_position(self, position: TradingPosition):
        """Save position to database"""
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()
        
            cursor.execute('''
                INSERT OR REPLACE INTO positions 
                (token_address, token_symbol, total_invested_sol, current_balance,
                average_buy_price, total_trades, first_buy_at, last_trade_at,
                unrealized_pnl, realized_pnl)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (
                position.token_address, position.token_symbol, position.total_invested_sol,
                position.current_balance, position.average_buy_price, position.total_trades,
                position.first_buy_at, position.last_trade_at, position.unrealized_pnl,
                position.realized_pnl
            ))
        
            conn.commit()
            conn.close()
        
        except Exception as e:
            self.logger.error(f"Error saving/updating position for {position.token_symbol} ({position.token_address}): {e}")
