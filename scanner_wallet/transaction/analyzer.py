
"""
Solana Wallet Monitor - Transaction Analyzer Module
Advanced transaction analysis with pattern detection, P&L calculation, and fraud detection
"""

import time
import threading
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
import re
from collections import defaultdict, deque

# Core imports with fallbacks
try:
    from core.logger import get_logger
    from core.database import get_database_manager
    from core.config import get_config
    
    from models.transaction import Transaction, TransactionType, TransactionStatus
    from models.token import Token, TokenAccount
    from models.wallet import WalletStats
    
    from utils.helpers import get_current_timestamp, safe_divide, clamp
    from utils.formatters import format_sol_amount
    
except ImportError as e:
    # Fallback implementations for development
    import logging
    def get_logger(name=None):
        return logging.getLogger(name or 'transaction_analyzer')
    
    def get_database_manager(): return None
    def get_config(): return None
    
    class TransactionType:
        BUY = "buy"
        SELL = "sell"
        TRANSFER = "transfer"
        SWAP = "swap"
    
    class TransactionStatus:
        SUCCESS = "success"
        FAILED = "failed"

# Logger
logger = get_logger(__name__)

@dataclass
class TransactionAnalysis:
    """Comprehensive transaction analysis result"""
    transaction: Transaction
    analysis_type: str
    pnl_sol: float
    pnl_usd: Optional[float]
    classification: str
    confidence: float
    risk_score: float
    patterns_detected: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)
    analyzed_at: int = field(default_factory=get_current_timestamp)

@dataclass
class PnLCalculation:
    """P&L calculation for tokens"""
    token_mint: str
    token_symbol: str
    total_bought: float
    total_sold: float
    net_position: float
    avg_buy_price: float
    avg_sell_price: float
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    last_updated: int = field(default_factory=get_current_timestamp)

@dataclass
class TradePattern:
    """Detected trading pattern"""
    pattern_type: str
    confidence: float
    transactions: List[Transaction]
    metadata: Dict[str, Any] = field(default_factory=dict)

class TransactionAnalyzer:
    """
    Advanced transaction analysis engine for Solana
    Provides P&L tracking, pattern detection, and risk assessment
    """
    
    def __init__(self):
        self.config = get_config()
        self.db_manager = get_database_manager()
        
        # Analysis parameters
        self.MIN_TRANSACTION_AMOUNT = 0.001  # SOL
        self.PATTERN_WINDOW_HOURS = 24
        self.MAX_ANALYSIS_AGE = 7 * 24 * 3600  # 7 days
        
        # Risk scoring weights
        self.RISK_WEIGHTS = {
            'transaction_size': 0.3,
            'frequency': 0.25,
            'price_volatility': 0.2,
            'token_age': 0.15,
            'blacklist_match': 0.1
        }
        
        # Thread-safe storage
        self._lock = threading.Lock()
        self._analysis_cache: Dict[str, TransactionAnalysis] = {}
        self._pnl_cache: Dict[str, PnLCalculation] = {}
        
        # Pattern detection
        self._recent_transactions: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=100)
        )
        
        logger.info("💰 Transaction analyzer initialized")
    
    def analyze_transaction(self, transaction: Transaction) -> TransactionAnalysis:
        """
        Comprehensive analysis of a single transaction
        """
        try:
            cache_key = f"{transaction.signature}:{transaction.wallet_address}"
            
            # Check cache
            if cache_key in self._analysis_cache:
                cached = self._analysis_cache[cache_key]
                if get_current_timestamp() - cached.analyzed_at < 300:  # 5 min cache
                    return cached
            
            # Perform analysis
            analysis = self._perform_transaction_analysis(transaction)
            
            # Cache result
            with self._lock:
                self._analysis_cache[cache_key] = analysis
            
            # Store in database
            self._store_analysis(analysis)
            
            return analysis
            
        except Exception as e:
            logger.error(f"❌ Error analyzing transaction {transaction.signature}: {e}")
            return TransactionAnalysis(
                transaction=transaction,
                analysis_type="error",
                pnl_sol=0.0,
                pnl_usd=None,
                classification="unknown",
                confidence=0.0,
                risk_score=0.0,
                patterns_detected=[],
                metadata={'error': str(e)}
            )
    
    def _perform_transaction_analysis(self, tx: Transaction) -> TransactionAnalysis:
        """Perform detailed transaction analysis"""
        
        # Calculate P&L
        pnl_sol = self._calculate_pnl_for_transaction(tx)
        pnl_usd = self._calculate_pnl_usd(tx, pnl_sol)
        
        # Classify transaction
        classification = self._classify_transaction(tx)
        
        # Calculate confidence
        confidence = self._calculate_confidence(tx)
        
        # Calculate risk score
        risk_score = self._calculate_risk_score(tx)
        
        # Detect patterns
        patterns = self._detect_patterns(tx)
        
        return TransactionAnalysis(
            transaction=tx,
            analysis_type="comprehensive",
            pnl_sol=pnl_sol,
            pnl_usd=pnl_usd,
            classification=classification,
            confidence=confidence,
            risk_score=risk_score,
            patterns_detected=patterns,
            metadata=self._extract_metadata(tx)
        )
    
    def _calculate_pnl_for_transaction(self, tx: Transaction) -> float:
        """Calculate P&L for a single transaction"""
        if tx.transaction_type == TransactionType.BUY:
            return -abs(float(tx.amount)) - float(tx.fee)
        elif tx.transaction_type == TransactionType.SELL:
            return abs(float(tx.amount)) - float(tx.fee)
        elif tx.transaction_type == TransactionType.SWAP:
            # For swaps, use token amount difference
            return float(tx.token_amount) if tx.token_amount else 0.0
        else:
            return float(tx.amount) - float(tx.fee)
    
    def _calculate_pnl_usd(self, tx: Transaction, pnl_sol: float) -> Optional[float]:
        """Calculate P&L in USD"""
        if tx.price_per_token and tx.price_per_token > 0:
            return pnl_sol * float(tx.price_per_token)
        return None
    
    def _classify_transaction(self, tx: Transaction) -> str:
        """Classify transaction based on type and context"""
        base_classification = str(tx.transaction_type)
        
        # Add context
        if abs(float(tx.amount)) > 100:  # Large transaction
            base_classification += "_large"
        
        if tx.token_amount and float(tx.token_amount) > 10000:
            base_classification += "_whale"
        
        return base_classification
    
    def _calculate_confidence(self, tx: Transaction) -> float:
        """Calculate analysis confidence score"""
        confidence = 0.8  # Base confidence
        
        # Increase confidence with more data
        if tx.price_per_token and tx.price_per_token > 0:
            confidence += 0.1
        
        if tx.token_amount and tx.token_amount > 0:
            confidence += 0.05
        
        # Decrease confidence for failed transactions
        if tx.status == TransactionStatus.FAILED:
            confidence -= 0.2
        
        return clamp(confidence, 0.0, 1.0)
    
    def _calculate_risk_score(self, tx: Transaction) -> float:
        """Calculate transaction risk score"""
        risk_score = 0.0
        
        # Risk factors
        amount = abs(float(tx.amount))
        
        # Transaction size risk
        if amount > 1000:
            risk_score += 0.4
        elif amount > 100:
            risk_score += 0.2
        elif amount > 10:
            risk_score += 0.1
        
        # Token risk
        if tx.token_mint:
            token_risk = self._assess_token_risk(tx.token_mint)
            risk_score += token_risk * 0.3
        
        # Failed transaction risk
        if tx.status == TransactionStatus.FAILED:
            risk_score += 0.3
        
        return clamp(risk_score, 0.0, 1.0)
    
    def _assess_token_risk(self, token_mint: str) -> float:
        """Assess risk for a specific token"""
        # Check blacklist
        blacklist_patterns = [
            'scam', 'fake', 'rug', 'honeypot', 'pump', 'dump'
        ]
        
        # This would check token metadata and history
        # Simplified implementation
        return 0.0
    
    def _detect_patterns(self, tx: Transaction) -> List[str]:
        """Detect trading patterns"""
        patterns = []
        
        # Add to recent transactions
        with self._lock:
            self._recent_transactions[tx.wallet_address].append(tx)
        
        # Pattern detection
        patterns.extend(self._detect_day_trading(tx))
        patterns.extend(self._detect_whale_activity(tx))
        patterns.extend(self._detect_arbitrage(tx))
        
        return patterns
    
    def _detect_day_trading(self, tx: Transaction) -> List[str]:
        """Detect day trading patterns"""
        patterns = []
        
        recent_txs = list(self._recent_transactions.get(tx.wallet_address, []))
        
        # Check for high frequency trading
        if len(recent_txs) >= 10:
            recent_times = [t.block_time for t in recent_txs[-10:]]
            if recent_times[-1] - recent_times[0] < 3600:  # 1 hour
                patterns.append("high_frequency_trading")
        
        return patterns
    
    def _detect_whale_activity(self, tx: Transaction) -> List[str]:
        """Detect whale activity patterns"""
        patterns = []
        
        amount = abs(float(tx.amount))
        
        if amount > 10000:
            patterns.append("whale_transaction")
        elif amount > 1000:
            patterns.append("large_transaction")
        
        return patterns
    
    def _detect_arbitrage(self, tx: Transaction) -> List[str]:
        """Detect arbitrage patterns"""
        patterns = []
        
        # Check for rapid buy/sell sequences
        recent_txs = list(self._recent_transactions.get(tx.wallet_address, []))
        
        # Look for buy/sell pairs within short time window
        # Simplified implementation
        return patterns
    
    def _extract_metadata(self, tx: Transaction) -> Dict[str, Any]:
        """Extract additional metadata from transaction"""
        return {
            'transaction_age_hours': safe_divide(get_current_timestamp() - tx.block_time, 3600),
            'amount_in_usd': tx.price_per_token * abs(float(tx.amount)) if tx.price_per_token else None,
            'relative_size': abs(float(tx.amount)) / 1000 if abs(float(tx.amount)) > 0 else 0,
            'token_involved': bool(tx.token_mint)
        }
    
    def calculate_wallet_pnl(self, wallet_address: str, token_mint: Optional[str] = None) -> Dict[str, PnLCalculation]:
        """Calculate P&L for wallet or specific token"""
        try:
            if not validate_wallet_address(wallet_address):
                return {}
            
            # Get transactions
            transactions = self._get_wallet_transactions(wallet_address, token_mint)
            
            # Calculate P&L by token
            pnl_by_token = {}
            
            # Group by token
            token_transactions = defaultdict(list)
            for tx in transactions:
                key = tx.token_mint or "SOL"
                token_transactions[key].append(tx)
            
            for token_mint, txs in token_transactions.items():
                pnl_calc = self._calculate_token_pnl(wallet_address, token_mint, txs)
                pnl_by_token[token_mint] = pnl_calc
            
            # Cache results
            with self._lock:
                self._pnl_cache[wallet_address] = pnl_by_token
            
            return pnl_by_token
            
        except Exception as e:
            logger.error(f"❌ Error calculating P&L for {wallet_address}: {e}")
            return {}
    
    def _get_wallet_transactions(self, wallet_address: str, token_mint: Optional[str] = None) -> List[Transaction]:
        """Get transactions for wallet (with optional token filter)"""
        transactions = []
        
        try:
            if not self.db_manager:
                return []
            
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                if token_mint:
                    query = """
                        SELECT * FROM transactions 
                        WHERE wallet_address = ? AND token_mint = ?
                        ORDER BY block_time DESC
                    """
                    params = (wallet_address, token_mint)
                else:
                    query = """
                        SELECT * FROM transactions 
                        WHERE wallet_address = ?
                        ORDER BY block_time DESC
                    """
                    params = (wallet_address,)
                
                cursor.execute(query, params)
                
                for row in cursor.fetchall():
                    tx = Transaction(
                        signature=row['signature'],
                        wallet_address=row['wallet_address'],
                        slot=row['slot'],
                        block_time=row['block_time'],
                        amount=float(row['amount']),
                        fee=float(row['fee']),
                        token_mint=row['token_mint'],
                        token_symbol=row['token_symbol'],
                        token_name=row['token_name'],
                        token_amount=float(row['token_amount']) if row['token_amount'] else 0.0,
                        price_per_token=float(row['price_per_token']) if row['price_per_token'] else 0.0,
                        transaction_type=TransactionType(row['transaction_type']),
                        status=TransactionStatus(row['status']),
                        source=row['source']
                    )
                    transactions.append(tx)
        
        except Exception as e:
            logger.error(f"❌ Error getting transactions: {e}")
        
        return transactions
    
    def _calculate_token_pnl(self, wallet_address: str, token_mint: str, transactions: List[Transaction]) -> PnLCalculation:
        """Calculate P&L for a specific token"""
        try:
            # Get token info
            token_info = self._get_token_info(token_mint)
            symbol = token_info.get('symbol', 'UNKNOWN')
            decimals = token_info.get('decimals', 9)
            
            # Initialize tracking
            total_bought = 0.0
            total_sold = 0.0
            total_buy_value = 0.0
            total_sell_value = 0.0
            realized_pnl = 0.0
            
            # Process transactions chronologically
            sorted_txs = sorted(transactions, key=lambda x: x.block_time)
            
            for tx in sorted_txs:
                if tx.status != TransactionStatus.SUCCESS:
                    continue
                
                amount = float(tx.token_amount) if tx.token_amount else 0.0
                
                if tx.transaction_type == TransactionType.BUY:
                    total_bought += amount
                    if tx.price_per_token and tx.price_per_token > 0:
                        total_buy_value += amount * float(tx.price_per_token)
                
                elif tx.transaction_type == TransactionType.SELL:
                    total_sold += amount
                    if tx.price_per_token and tx.price_per_token > 0:
                        total_sell_value += amount * float(tx.price_per_token)
                        realized_pnl += amount * (float(tx.price_per_token) - (total_buy_value / total_bought if total_bought > 0 else 0))
            
            # Calculate averages
            avg_buy_price = safe_divide(total_buy_value, total_bought) if total_bought > 0 else 0.0
            avg_sell_price = safe_divide(total_sell_value, total_sold) if total_sold > 0 else 0.0
            
            # Current position
            net_position = total_bought - total_sold
            
            # Unrealized P&L (assuming current price)
            current_price = self._get_current_price(token_mint)
            unrealized_pnl = net_position * current_price if current_price > 0 else 0.0
            
            total_pnl = realized_pnl + unrealized_pnl
            
            return PnLCalculation(
                token_mint=token_mint,
                token_symbol=symbol,
                total_bought=total_bought,
                total_sold=total_sold,
                net_position=net_position,
                avg_buy_price=avg_buy_price,
                avg_sell_price=avg_sell_price,
                realized_pnl=realized_pnl,
                unrealized_pnl=unrealized_pnl,
                total_pnl=total_pnl
            )
            
        except Exception as e:
            logger.error(f"❌ Error calculating token P&L: {e}")
            return PnLCalculation(
                token_mint=token_mint,
                token_symbol="ERROR",
                total_bought=0.0,
                total_sold=0.0,
                net_position=0.0,
                avg_buy_price=0.0,
                avg_sell_price=0.0,
                realized_pnl=0.0,
                unrealized_pnl=0.0,
                total_pnl=0.0
            )
    
    def _get_token_info(self, token_mint: str) -> Dict[str, Any]:
        """Get token information"""
        try:
            if not self.db_manager:
                return {'symbol': 'UNKNOWN', 'decimals': 9}
            
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT symbol, decimals FROM tokens
                    WHERE address = ?
                """, (token_mint,))
                
                row = cursor.fetchone()
                if row:
                    return {'symbol': row['symbol'], 'decimals': row['decimals']}
        
        except Exception as e:
            logger.error(f"❌ Error getting token info: {e}")
        
        return {'symbol': 'UNKNOWN', 'decimals': 9}
    
    def _get_current_price(self, token_mint: str) -> float:
        """Get current token price"""
        # This would integrate with price feeds
        # Simplified implementation
        return 0.0
    
    def detect_fraudulent_transactions(self, transactions: List[Transaction]) -> List[Transaction]:
        """Detect potentially fraudulent transactions"""
        suspicious = []
        
        for tx in transactions:
            if self._is_suspicious(tx):
                suspicious.append(tx)
        
        return suspicious
    
    def _is_suspicious(self, tx: Transaction) -> bool:
        """Check if transaction is suspicious"""
        # Check for suspicious patterns
        suspicious_indicators = 0
        
        # Large amount with no price data
        if abs(float(tx.amount)) > 1000 and not tx.price_per_token:
            suspicious_indicators += 1
        
        # Very small amount but high fee
        if abs(float(tx.amount)) < 0.001 and float(tx.fee) > 0.01:
            suspicious_indicators += 1
        
        # Check blacklist patterns
        if tx.token_symbol:
            blacklist_patterns = ['scam', 'fake', 'honeypot']
            for pattern in blacklist_patterns:
                if pattern.lower() in tx.token_symbol.lower():
                    suspicious_indicators += 1
        
        return suspicious_indicators >= 2
    
    def get_trading_summary(self, wallet_address: str, days: int = 30) -> Dict[str, Any]:
        """Get comprehensive trading summary"""
        try:
            cutoff_time = get_current_timestamp() - (days * 86400)
            
            # Get recent transactions
            recent_txs = self._get_recent_transactions(wallet_address, cutoff_time)
            
            # Calculate metrics
            total_volume = sum(abs(float(tx.amount)) for tx in recent_txs)
            unique_tokens = len(set(tx.token_mint for tx in recent_txs if tx.token_mint))
            
            # P&L by token
            pnl_by_token = self.calculate_wallet_pnl(wallet_address)
            
            # Patterns detected
            patterns = self._analyze_patterns(recent_txs)
            
            return {
                'wallet_address': wallet_address,
                'period_days': days,
                'total_transactions': len(recent_txs),
                'total_volume': total_volume,
                'unique_tokens': unique_tokens,
                'pnl_by_token': {k: v.to_dict() for k, v in pnl_by_token.items()},
                'patterns_detected': patterns,
                'risk_score': self._calculate_overall_risk(recent_txs)
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting trading summary: {e}")
            return {'error': str(e)}
    
    def _get_recent_transactions(self, wallet_address: str, cutoff_time: int) -> List[Transaction]:
        """Get recent transactions for analysis"""
        transactions = []
        
        try:
            if not self.db_manager:
                return []
            
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM transactions
                    WHERE wallet_address = ? AND block_time > ?
                    ORDER BY block_time DESC
                """, (wallet_address, cutoff_time))
                
                for row in cursor.fetchall():
                    tx = Transaction(
                        signature=row['signature'],
                        wallet_address=row['wallet_address'],
                        slot=row['slot'],
                        block_time=row['block_time'],
                        amount=float(row['amount']),
                        fee=float(row['fee']),
                        token_mint=row['token_mint'],
                        token_symbol=row['token_symbol'],
                        token_name=row['token_name'],
                        token_amount=float(row['token_amount']) if row['token_amount'] else 0.0,
                        price_per_token=float(row['price_per_token']) if row['price_per_token'] else 0.0,
                        transaction_type=TransactionType(row['transaction_type']),
                        status=TransactionStatus(row['status']),
                        source=row['source']
                    )
                    transactions.append(tx)
        
        except Exception as e:
            logger.error(f"❌ Error getting recent transactions: {e}")
        
        return transactions
    
    def _analyze_patterns(self, transactions: List[Transaction]) -> List[str]:
        """Analyze trading patterns in transactions"""
        patterns = []
        
        if len(transactions) < 2:
            return patterns
        
        # DCA pattern
        if self._detect_dca_pattern(transactions):
            patterns.append("dollar_cost_averaging")
        
        # Swing trading
        if self._detect_swing_pattern(transactions):
            patterns.append("swing_trading")
        
        # HODLing
        if self._detect_hodl_pattern(transactions):
            patterns.append("hodling")
        
        return patterns
    
    def _detect_dca_pattern(self, transactions: List[Transaction]) -> bool:
        """Detect dollar-cost averaging pattern"""
        # Check for regular buy intervals
        buy_txs = [t for t in transactions if t.transaction_type == TransactionType.BUY]
        
        if len(buy_txs) < 3:
            return False
        
        # Check for consistent intervals
        intervals = [buy_txs[i+1].block_time - buy_txs[i].block_time 
                    for i in range(len(buy_txs)-1)]
        
        avg_interval = sum(intervals) / len(intervals)
        variance = sum(abs(i - avg_interval) for i in intervals) / len(intervals)
        
        # Consistent if variance < 20% of average
        return variance < avg_interval * 0.2
    
    def _detect_swing_pattern(self, transactions: List[Transaction]) -> bool:
        """Detect swing trading pattern"""
        # Check for buy/sell cycles
        pattern = []
        for tx in transactions:
            pattern.append(tx.transaction_type)
        
        # Look for buy-sell-buy-sell sequences
        pattern_str = ''.join([str(t) for t in pattern])
        return "buy" in pattern_str and "sell" in pattern_str
    
    def _detect_hodl_pattern(self, transactions: List[Transaction]) -> bool:
        """Detect HODLing pattern"""
        # Check for mostly buys with few sells
        buys = sum(1 for t in transactions if t.transaction_type == TransactionType.BUY)
        sells = sum(1 for t in transactions if t.transaction_type == TransactionType.SELL)
        
        return buys > 0 and sells < buys * 0.2
    
    def _calculate_overall_risk(self, transactions: List[Transaction]) -> float:
        """Calculate overall risk score for wallet"""
        if not transactions:
            return 0.0
        
        # Average risk score
        risk_scores = [self._calculate_risk_score(tx) for tx in transactions]
        return sum(risk_scores) / len(risk_scores)
    
    def _store_analysis(self, analysis: TransactionAnalysis) -> bool:
        """Store analysis result in database"""
        if not self.db_manager:
            return True
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO transaction_analyses 
                    (signature, wallet_address, analysis_type, pnl_sol, pnl_usd,
                     classification, confidence, risk_score, patterns_detected,
                     metadata, analyzed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    analysis.transaction.signature,
                    analysis.transaction.wallet_address,
                    analysis.analysis_type,
                    analysis.pnl_sol,
                    analysis.pnl_usd,
                    analysis.classification,
                    analysis.confidence,
                    analysis.risk_score,
                    json.dumps(analysis.patterns_detected),
                    json.dumps(analysis.metadata),
                    analysis.analyzed_at
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"❌ Error storing analysis: {e}")
            return False
    
    def cleanup_cache(self) -> int:
        """Clean analysis cache"""
        removed = 0
        current_time = get_current_timestamp()
        
        with self._lock:
            expired_keys = [
                key for key, value in self._analysis_cache.items()
                if current_time - value.analyzed_at > 3600  # 1 hour cache
            ]
            
            for key in expired_keys:
                del self._analysis_cache[key]
                removed += 1
        
        logger.info(f"🧹 Cleaned {removed} expired analysis cache entries")
        return removed

# Global instance
_analyzer = None

def get_transaction_analyzer() -> TransactionAnalyzer:
    """Get global transaction analyzer instance"""
    global _analyzer
    
    if _analyzer is None:
        _analyzer = TransactionAnalyzer()
    
    return _analyzer

# Convenience functions
def analyze_transaction(transaction: Transaction) -> TransactionAnalysis:
    """Analyze a transaction using global analyzer"""
    return get_transaction_analyzer().analyze_transaction(transaction)

def calculate_wallet_pnl(wallet_address: str, token_mint: Optional[str] = None) -> Dict[str, PnLCalculation]:
    """Calculate P&L for wallet using global analyzer"""
    return get_transaction_analyzer().calculate_wallet_pnl(wallet_address, token_mint)

def get_trading_summary(wallet_address: str, days: int = 30) -> Dict[str, Any]:
    """Get trading summary using global analyzer"""
    return get_transaction_analyzer().get_trading_summary(wallet_address, days)

# Development testing
if __name__ == "__main__":
    logger.info("🧪 Testing Transaction Analyzer...")
    
    # Create test instance
    analyzer = get_transaction_analyzer()
    
    # Test with sample transaction
    test_tx = Transaction(
        signature="test_signature_123456789",
        wallet_address="4DdrfGHGdMjCqVbNtXsEEGL1SryTeMo8KMGWWtZyZVFh",
        slot=123456789,
        block_time=get_current_timestamp() - 3600,
        amount=1.5,
        fee=0.0005,
        token_mint="So11111111111111111111111111111111111111112",
        token_symbol="SOL",
        token_name="Wrapped SOL",
        token_amount=1.5,
        price_per_token=150.0,
        transaction_type=TransactionType.BUY,
        status=TransactionStatus.SUCCESS,
        source="test"
    )
    
    # Analyze transaction
    analysis = analyzer.analyze_transaction(test_tx)
    logger.info(f"📊 Analysis result: {analysis.classification} with confidence {analysis.confidence}")
    
    # Test P&L calculation
    pnl = analyzer.calculate_wallet_pnl("4DdrfGHGdMjCqVbNtXsEEGL1SryTeMo8KMGWWtZyZVFh")
    logger.info(f"💰 P&L summary: {len(pnl)} tokens analyzed")
    
    logger.info("✅ Transaction analyzer test completed")