
"""
Solana Wallet Monitor - Transaction Classifier Module
Advanced transaction classification with ML-like pattern recognition and context analysis
"""

import re
import json
import time
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
import logging

# Core imports with fallbacks
try:
    from core.logger import get_logger
    from core.database import get_database_manager
    from core.config import get_config
    
    from models.transaction import Transaction, TransactionType, TransactionStatus
    from models.token import Token
    
    from utils.helpers import get_current_timestamp, safe_divide
    from utils.constants import SOLANA_PROGRAM_IDS
    
except ImportError as e:
    # Fallback implementations for development
    import logging
    def get_logger(name=None):
        return logging.getLogger(name or 'transaction_classifier')
    
    def get_database_manager(): return None
    def get_config(): return None
    
    class TransactionType:
        BUY = "buy"
        SELL = "sell"
        TRANSFER = "transfer"
        SWAP = "swap"
        STAKE = "stake"
        UNSTAKE = "unstake"

# Logger
logger = get_logger(__name__)

class ClassificationConfidence(Enum):
    """Confidence levels for transaction classification"""
    HIGH = 0.95
    MEDIUM = 0.75
    LOW = 0.50
    UNCERTAIN = 0.25

@dataclass
class ClassificationContext:
    """Context for transaction classification"""
    transaction: Any
    wallet_address: str
    network_state: Dict[str, Any] = field(default_factory=dict)
    token_metadata: Dict[str, Any] = field(default_factory=dict)
    market_conditions: Dict[str, Any] = field(default_factory=dict)
    historical_patterns: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ClassificationResult:
    """Transaction classification result"""
    transaction_type: TransactionType
    confidence: float
    reasoning: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    alternative_types: List[Tuple[TransactionType, float]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    classified_at: int = field(default_factory=lambda: int(time.time()))

class TransactionClassifier:
    """
    Advanced transaction classification system for Solana
    Uses multi-layer analysis with context awareness and confidence scoring
    """
    
    def __init__(self):
        self.config = get_config()
        self.db_manager = get_database_manager()
        
        # Classification rules and patterns
        self._load_classification_rules()
        
        # Known DEX programs
        self.DEX_PROGRAMS = {
            'JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5wNy3aZV',  # Jupiter
            '9W959DqEETiGZocYWCQPaJ6sBmUzgfxXfqGeTEdp3aQP',  # Raydium
            '675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8',  # Orca
            'CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTyW7P6d5yF3p6',  # Serum
            'Eo7WjKq67rjJQSZxS6z3YkapzY3eMj6Xy8X5EQVn5UaB',  # Meteora
        }
    
    def _load_classification_rules(self):
        """Load classification rules from database or defaults"""
        self.CLASSIFICATION_RULES = {
            # Amount-based rules
            'amount_thresholds': {
                'whale': 1000,
                'large': 100,
                'medium': 10,
                'small': 0.1
            },
            
            # Time-based patterns
            'time_patterns': {
                'recent': 3600,  # 1 hour
                'day': 86400,    # 1 day
                'week': 604800,  # 1 week
            },
            
            # Program-based classification
            'program_types': {
                'JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5wNy3aZV': 'DEX_SWAP',
                '9W959DqEETiGZocYWCQPaJ6sBmUzgfxXfqGeTEdp3aQP': 'DEX_SWAP',
                'Stake111111111111111111111111111111111111111': 'STAKE',
                'Stake222222222222222222222222222222222222222': 'UNSTAKE',
                '111111111111111111111111111111111111111111': 'SYSTEM_TRANSFER',
            }
        }
    
    def classify_transaction(self, transaction: Transaction, context: Optional[ClassificationContext] = None) -> ClassificationResult:
        """
        Classify a single transaction with confidence scoring
        """
        try:
            logger.info(f"🏷️ Classifying transaction {transaction.signature}")
            
            # Build context if not provided
            if not context:
                context = self._build_classification_context(transaction)
            
            # Multi-layer classification
            classification = self._multi_layer_classification(transaction, context)
            
            return classification
            
        except Exception as e:
            logger.error(f"❌ Error classifying transaction {transaction.signature}: {e}")
            return ClassificationResult(
                transaction_type=TransactionType.OTHER,
                confidence=ClassificationConfidence.UNCERTAIN.value,
                reasoning=f"Classification error: {str(e)}",
                evidence={'error': str(e)}
            )
    
    def _build_classification_context(self, transaction: Transaction) -> ClassificationContext:
        """Build comprehensive classification context"""
        context = ClassificationContext(
            transaction=transaction,
            wallet_address=transaction.wallet_address
        )
        
        # Load network state
        context.network_state = self._get_network_state(transaction)
        
        # Load token metadata
        if transaction.token_mint:
            context.token_metadata = self._get_token_metadata(transaction.token_mint)
        
        # Load market conditions
        context.market_conditions = self._get_market_conditions(transaction)
        
        # Load historical patterns
        context.historical_patterns = self._get_historical_patterns(transaction)
        
        return context
    
    def _multi_layer_classification(self, transaction: Transaction, context: ClassificationContext) -> ClassificationResult:
        """Multi-layer classification approach"""
        
        # Layer 1: Direct evidence
        layer1_result = self._layer1_direct_classification(transaction, context)
        
        # Layer 2: Context analysis
        layer2_result = self._layer2_context_analysis(transaction, context)
        
        # Layer 3: Pattern matching
        layer3_result = self._layer3_pattern_matching(transaction, context)
        
        # Combine results
        return self._combine_classification_results([layer1_result, layer2_result, layer3_result])
    
    def _layer1_direct_classification(self, transaction: Transaction, context: ClassificationContext) -> ClassificationResult:
        """Direct evidence-based classification"""
        evidence = {}
        confidence = ClassificationConfidence.HIGH.value
        
        # Check transaction metadata
        if transaction.transaction_type != TransactionType.OTHER:
            return ClassificationResult(
                transaction_type=transaction.transaction_type,
                confidence=confidence,
                reasoning="Direct type from transaction",
                evidence={'type': str(transaction.transaction_type)}
            )
        
        # Check amounts
        amount = abs(float(transaction.amount))
        if amount < 0.001:
            evidence['small_amount'] = True
            confidence *= 0.9
        
        # Check token involvement
        if transaction.token_mint:
            evidence['token_transaction'] = True
        
        return ClassificationResult(
            transaction_type=TransactionType.TRANSFER,
            confidence=confidence,
            reasoning="Default classification based on metadata",
            evidence=evidence
        )
    
    def _layer2_context_analysis(self, transaction: Transaction, context: ClassificationContext) -> ClassificationResult:
        """Context-based classification"""
        evidence = {}
        confidence = ClassificationConfidence.MEDIUM.value
        
        # Analyze program interactions
        program_type = self._identify_program_type(transaction)
        if program_type:
            evidence['program_type'] = program_type
            
            type_mapping = {
                'DEX_SWAP': TransactionType.SWAP,
                'STAKE': TransactionType.STAKE,
                'UNSTAKE': TransactionType.UNSTAKE,
                'SYSTEM_TRANSFER': TransactionType.TRANSFER,
            }
            
            if program_type in type_mapping:
                return ClassificationResult(
                    transaction_type=type_mapping[program_type],
                    confidence=confidence,
                    reasoning=f"Identified by program interaction: {program_type}",
                    evidence={'program_type': program_type}
                )
        
        # Analyze token patterns
        if transaction.token_mint:
            token_pattern = self._analyze_token_pattern(transaction, context)
            if token_pattern:
                evidence['token_pattern'] = token_pattern
        
        return ClassificationResult(
            transaction_type=TransactionType.OTHER,
            confidence=confidence * 0.8,
            reasoning="Context analysis inconclusive",
            evidence=evidence
        )
    
    def _layer3_pattern_matching(self, transaction: Transaction, context: ClassificationContext) -> ClassificationResult:
        """Pattern matching classification"""
        patterns = []
        confidence = ClassificationConfidence.LOW.value
        
        # Detect buy/sell patterns
        buy_sell_pattern = self._detect_buy_sell_pattern(transaction, context)
        if buy_sell_pattern:
            patterns.append(buy_sell_pattern)
        
        # Detect swap patterns
        swap_pattern = self._detect_swap_pattern(transaction, context)
        if swap_pattern:
            patterns.append(swap_pattern)
        
        # Detect arbitrage
        arbitrage_pattern = self._detect_arbitrage_pattern(transaction, context)
        if arbitrage_pattern:
            patterns.append(arbitrage_pattern)
        
        if patterns:
            primary_pattern = patterns[0]
            return ClassificationResult(
                transaction_type=primary_pattern['type'],
                confidence=confidence * 0.9,
                reasoning=f"Detected pattern: {primary_pattern['name']}",
                evidence={'patterns': patterns}
            )
        
        return ClassificationResult(
            transaction_type=TransactionType.OTHER,
            confidence=confidence * 0.5,
            reasoning="No patterns detected",
            evidence={'patterns': []}
        )
    
    def _identify_program_type(self, transaction: Transaction) -> Optional[str]:
        """Identify program type from transaction data"""
        # This would analyze the actual transaction instructions
        # Simplified implementation
        
        # Check against known program IDs
        program_id = transaction.metadata.get('program_id', '')
        
        for known_program, program_type in self.CLASSIFICATION_RULES['program_types'].items():
            if program_id == known_program:
                return program_type
        
        return None
    
    def _analyze_token_pattern(self, transaction: Transaction, context: ClassificationContext) -> Optional[Dict[str, Any]]:
        """Analyze token-related patterns"""
        if not transaction.token_mint:
            return None
        
        patterns = {}
        
        # Check if it's a known token
        if transaction.token_symbol in ['USDC', 'USDT', 'SOL', 'ETH', 'BTC']:
            patterns['known_token'] = True
        
        # Check token age
        if context.token_metadata:
            token_age = get_current_timestamp() - context.token_metadata.get('created_at', 0)
            patterns['token_age_days'] = token_age / 86400
        
        return patterns
    
    def _detect_buy_sell_pattern(self, transaction: Transaction, context: ClassificationContext) -> Optional[Dict[str, Any]]:
        """Detect buy/sell patterns from transaction flow"""
        # Analyze SOL and token flows
        sol_change = float(transaction.amount)
        token_change = float(transaction.token_amount) if transaction.token_amount else 0.0
        
        # Buy pattern: SOL out, tokens in
        if sol_change < -self.MIN_TRANSACTION_AMOUNT and token_change > 0:
            return {
                'type': TransactionType.BUY,
                'name': 'direct_buy',
                'confidence': 0.85,
                'evidence': {
                    'sol_spent': abs(sol_change),
                    'tokens_received': token_change
                }
            }
        
        # Sell pattern: tokens out, SOL in
        elif sol_change > self.MIN_TRANSACTION_AMOUNT and token_change < 0:
            return {
                'type': TransactionType.SELL,
                'name': 'direct_sell',
                'confidence': 0.85,
                'evidence': {
                    'sol_received': sol_change,
                    'tokens_sold': abs(token_change)
                }
            }
        
        return None
    
    def _detect_swap_pattern(self, transaction: Transaction, context: ClassificationContext) -> Optional[Dict[str, Any]]:
        """Detect DEX swap patterns"""
        # Check for swap indicators
        if 'swap' in str(transaction.metadata).lower():
            return {
                'type': TransactionType.SWAP,
                'name': 'dex_swap',
                'confidence': 0.9,
                'evidence': {'dex_indicators': True}
            }
        
        # Check for program interaction
        program_id = transaction.metadata.get('program_id', '')
        if program_id in self.DEX_PROGRAMS:
            return {
                'type': TransactionType.SWAP,
                'name': 'program_swap',
                'confidence': 0.95,
                'evidence': {'program': program_id}
            }
        
        return None
    
    def _detect_arbitrage_pattern(self, transaction: Transaction, context: ClassificationContext) -> Optional[Dict[str, Any]]:
        """Detect arbitrage patterns"""
        # This would require cross-DEX analysis
        # Simplified implementation
        return None
    
    def _combine_classification_results(self, results: List[ClassificationResult]) -> ClassificationResult:
        """Combine multiple classification results with weighted confidence"""
        if not results:
            return ClassificationResult(
                transaction_type=TransactionType.OTHER,
                confidence=ClassificationConfidence.UNCERTAIN.value,
                reasoning="No classification results"
            )
        
        # Weight results by confidence
        weighted_results = defaultdict(float)
        total_confidence = 0.0
        
        for result in results:
            weighted_results[result.transaction_type] += result.confidence
            total_confidence += result.confidence
        
        # Select highest weighted type
        if weighted_results:
            primary_type = max(weighted_results.items(), key=lambda x: x[1])[0]
            combined_confidence = min(weighted_results[primary_type] / len(results), 1.0)
            
            # Collect all evidence
            all_evidence = {}
            all_reasoning = []
            
            for result in results:
                all_evidence.update(result.evidence)
                if result.reasoning:
                    all_reasoning.append(result.reasoning)
            
            return ClassificationResult(
                transaction_type=primary_type,
                confidence=combined_confidence,
                reasoning=" | ".join(all_reasoning),
                evidence=all_evidence
            )
        
        return ClassificationResult(
            transaction_type=TransactionType.OTHER,
            confidence=ClassificationConfidence.UNCERTAIN.value,
            reasoning="Combined classification failed"
        )
    
    def _get_network_state(self, transaction: Transaction) -> Dict[str, Any]:
        """Get current network state"""
        return {
            'timestamp': transaction.block_time,
            'slot': transaction.slot,
            'gas_price': transaction.fee
        }
    
    def _get_token_metadata(self, token_mint: str) -> Dict[str, Any]:
        """Get token metadata"""
        if not self.db_manager:
            return {}
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM tokens WHERE address = ?
                """, (token_mint,))
                
                row = cursor.fetchone()
                if row:
                    return dict(row)
        
        except Exception as e:
            logger.error(f"❌ Error getting token metadata: {e}")
        
        return {}
    
    def _get_market_conditions(self, transaction: Transaction) -> Dict[str, Any]:
        """Get market conditions at transaction time"""
        return {
            'timestamp': transaction.block_time,
            'price': transaction.price_per_token
        }
    
    def _get_historical_patterns(self, transaction: Transaction) -> Dict[str, Any]:
        """Get historical patterns for wallet"""
        patterns = {}
        
        try:
            if self.db_manager:
                with self.db_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Get recent transaction patterns
                    cursor.execute("""
                        SELECT transaction_type, COUNT(*) as count
                        FROM transactions
                        WHERE wallet_address = ? AND block_time > ?
                        GROUP BY transaction_type
                    """, (transaction.wallet_address, transaction.block_time - 86400))
                    
                    for row in cursor.fetchall():
                        patterns[row['transaction_type']] = row['count']
        
        except Exception as e:
            logger.error(f"❌ Error getting historical patterns: {e}")
        
        return patterns
    
    def batch_classify_transactions(self, transactions: List[Transaction]) -> List[ClassificationResult]:
        """Classify multiple transactions efficiently"""
        results = []
        
        for transaction in transactions:
            result = self.classify_transaction(transaction)
            results.append(result)
        
        return results
    
    def validate_classification(self, result: ClassificationResult, ground_truth: TransactionType) -> bool:
        """Validate classification accuracy"""
        return result.transaction_type == ground_truth
    
    def get_classification_stats(self, wallet_address: str) -> Dict[str, Any]:
        """Get classification statistics for wallet"""
        stats = {
            'total_classified': 0,
            'by_type': defaultdict(int),
            'confidence_distribution': defaultdict(int),
            'accuracy': 0.0
        }
        
        try:
            if self.db_manager:
                with self.db_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    
                    cursor.execute("""
                        SELECT classification, confidence
                        FROM transaction_analyses
                        WHERE wallet_address = ?
                    """, (wallet_address,))
                    
                    for row in cursor.fetchall():
                        stats['total_classified'] += 1
                        stats['by_type'][row['classification']] += 1
                        
                        # Categorize confidence
                        if row['confidence'] >= 0.9:
                            stats['confidence_distribution']['high'] += 1
                        elif row['confidence'] >= 0.7:
                            stats['confidence_distribution']['medium'] += 1
                        elif row['confidence'] >= 0.5:
                            stats['confidence_distribution']['low'] += 1
                        else:
                            stats['confidence_distribution']['uncertain'] += 1
        
        except Exception as e:
            logger.error(f"❌ Error getting classification stats: {e}")
        
        return dict(stats)
    
    def reclassify_transactions(self, wallet_address: str, new_rules: Dict[str, Any]) -> int:
        """Reclassify transactions with new rules"""
        updated = 0
        
        try:
            if self.db_manager:
                with self.db_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    
                    cursor.execute("""
                        SELECT * FROM transactions
                        WHERE wallet_address = ?
                    """, (wallet_address,))
                    
                    for row in cursor.fetchall():
                        # Create transaction object
                        transaction = Transaction(
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
                        
                        # Reclassify
                        new_result = self.classify_transaction(transaction)
                        
                        # Update if different
                        if new_result.transaction_type != transaction.transaction_type:
                            cursor.execute("""
                                UPDATE transactions
                                SET transaction_type = ?
                                WHERE signature = ?
                            """, (str(new_result.transaction_type), transaction.signature))
                            
                            updated += 1
                    
                    conn.commit()
        
        except Exception as e:
            logger.error(f"❌ Error reclassifying transactions: {e}")
        
        logger.info(f"🔄 Reclassified {updated} transactions")
        return updated

# Global instance
_classifier = None

def get_transaction_classifier() -> TransactionClassifier:
    """Get global transaction classifier instance"""
    global _classifier
    
    if _classifier is None:
        _classifier = TransactionClassifier()
    
    return _classifier

# Convenience functions
def classify_transaction(transaction: Transaction, context: Optional[ClassificationContext] = None) -> ClassificationResult:
    """Classify a transaction using global classifier"""
    return get_transaction_classifier().classify_transaction(transaction, context)

def batch_classify_transactions(transactions: List[Transaction]) -> List[ClassificationResult]:
    """Classify multiple transactions using global classifier"""
    return get_transaction_classifier().batch_classify_transactions(transactions)

def get_classification_stats(wallet_address: str) -> Dict[str, Any]:
    """Get classification stats using global classifier"""
    return get_transaction_classifier().get_classification_stats(wallet_address)

# Development testing
if __name__ == "__main__":
    logger.info("🧪 Testing Transaction Classifier...")
    
    # Create test instance
    classifier = get_transaction_classifier()
    
    # Test with sample transactions
    test_transactions = [
        Transaction(
            signature="test_buy_123456789",
            wallet_address="4DdrfGHGdMjCqVbNtXsEEGL1SryTeMo8KMGWWtZyZVFh",
            slot=123456789,
            block_time=int(time.time()) - 3600,
            amount=-1.5,  # SOL spent
            fee=0.0005,
            token_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
            token_symbol="USDC",
            token_name="USD Coin",
            token_amount=150.0,
            price_per_token=1.0,
            transaction_type=TransactionType.OTHER,
            status=TransactionStatus.SUCCESS,
            source="test"
        ),
        Transaction(
            signature="test_sell_987654321",
            wallet_address="4DdrfGHGdMjCqVbNtXsEEGL1SryTeMo8KMGWWtZyZVFh",
            slot=123456789,
            block_time=int(time.time()) - 7200,
            amount=2.0,  # SOL received
            fee=0.0005,
            token_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
            token_symbol="USDC",
            token_name="USD Coin",
            token_amount=-200.0,
            price_per_token=1.0,
            transaction_type=TransactionType.OTHER,
            status=TransactionStatus.SUCCESS,
            source="test"
        )
    ]
    
    # Classify transactions
    for tx in test_transactions:
        result = classifier.classify_transaction(tx)
        logger.info(f"🏷️ Classified {tx.signature}: {result.transaction_type} ({result.confidence:.2f})")
    
    logger.info("✅ Transaction classifier test completed")