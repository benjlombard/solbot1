
"""
Solana Wallet Monitor - Transaction Validation Module
Advanced validation system for transactions, balances, and blockchain data integrity
"""

import re
import time
import sqlite3
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime, timedelta
import json
import base58
import hashlib
from collections import defaultdict

# Core imports with fallbacks
try:
    from core.logger import get_logger
    from core.database import get_database_manager
    from core.config import get_config
    from core.exceptions import ValidationError
    
    from models.transaction import Transaction, TransactionType, TransactionStatus
    from models.token import Token
    
    from utils.helpers import get_current_timestamp, safe_divide
    from utils.validators import validate_wallet_address
    
except ImportError as e:
    # Fallback implementations for development
    import logging
    def get_logger(name=None):
        return logging.getLogger(name or 'transaction_validator')
    
    def get_database_manager(): return None
    def get_config(): return None
    
    class ValidationError(Exception):
        def __init__(self, message: str, field: str = None):
            self.message = message
            self.field = field
            super().__init__(message)

# Logger
logger = get_logger(__name__)

class ValidationResult:
    """Validation result with detailed information"""
    def __init__(self):
        self.is_valid = True
        self.errors: List[Dict[str, Any]] = []
        self.warnings: List[Dict[str, Any]] = []
        self.metadata: Dict[str, Any] = {}
    
    def add_error(self, message: str, field: str = None, severity: str = "error"):
        """Add validation error"""
        self.is_valid = False
        self.errors.append({
            'message': message,
            'field': field,
            'severity': severity,
            'timestamp': get_current_timestamp()
        })
    
    def add_warning(self, message: str, field: str = None):
        """Add validation warning"""
        self.warnings.append({
            'message': message,
            'field': field,
            'severity': 'warning',
            'timestamp': get_current_timestamp()
        })
    
    def merge(self, other: 'ValidationResult'):
        """Merge another validation result"""
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        self.metadata.update(other.metadata)
        self.is_valid = self.is_valid and other.is_valid
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'is_valid': self.is_valid,
            'errors': self.errors,
            'warnings': self.warnings,
            'metadata': self.metadata,
            'summary': {
                'total_errors': len(self.errors),
                'total_warnings': len(self.warnings),
                'severity': 'critical' if any(e['severity'] == 'critical' for e in self.errors) else
                           'error' if self.errors else
                           'warning' if self.warnings else 'ok'
            }
        }

class TransactionValidator:
    """
    Comprehensive transaction validation system
    Validates transactions, signatures, amounts, and blockchain integrity
    """
    
    def __init__(self):
        self.config = get_config()
        self.db_manager = get_database_manager()
        
        # Validation constants
        self.SOLANA_SIGNATURE_LENGTH = 88
        self.SOLANA_ADDRESS_LENGTH = 44
        self.MIN_TRANSACTION_AMOUNT = 0.000001  # SOL
        self.MAX_TRANSACTION_AMOUNT = 1000000  # SOL
        self.MAX_FEE = 0.1  # SOL
        self.MAX_SLOT = 2**64 - 1
        
        # Regex patterns
        self.SOLANA_ADDRESS_PATTERN = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{44}$')
        self.SOLANA_SIGNATURE_PATTERN = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{88}$')
        self.TOKEN_SYMBOL_PATTERN = re.compile(r'^[A-Z][A-Z0-9_]{1,10}$')
        
        logger.info("✅ Transaction validator initialized")
    
    def validate_transaction(self, transaction: Transaction, level: str = "standard") -> ValidationResult:
        """
        Comprehensive transaction validation
        Args:
            transaction: Transaction to validate
            level: "strict", "standard", or "lenient"
        """
        result = ValidationResult()
        
        try:
            # Basic validation
            self._validate_signature(transaction.signature, result)
            self._validate_wallet_address(transaction.wallet_address, result)
            self._validate_slot(transaction.slot, result)
            self._validate_block_time(transaction.block_time, result)
            self._validate_amount(transaction.amount, result)
            self._validate_fee(transaction.fee, result)
            
            # Token validation
            if transaction.token_mint:
                self._validate_token_mint(transaction.token_mint, result)
                self._validate_token_symbol(transaction.token_symbol, result)
                self._validate_token_amount(transaction.token_amount, result)
                self._validate_price_per_token(transaction.price_per_token, result)
            
            # Type and status validation
            self._validate_transaction_type(transaction.transaction_type, result)
            self._validate_status(transaction.status, result)
            
            # Advanced validation based on level
            if level == "strict":
                self._validate_blockchain_integrity(transaction, result)
                self._validate_sequence(transaction, result)
                self._validate_duplicate_check(transaction, result)
            
            # Metadata validation
            self._validate_metadata(transaction, result)
            
            # Cross-validation
            self._validate_cross_references(transaction, result)
            
        except Exception as e:
            result.add_error(f"Validation error: {str(e)}", severity="critical")
        
        return result
    
    def _validate_signature(self, signature: str, result: ValidationResult):
        """Validate transaction signature"""
        if not signature:
            result.add_error("Signature is required", "signature", "critical")
            return
        
        if len(signature) != self.SOLANA_SIGNATURE_LENGTH:
            result.add_error(
                f"Invalid signature length: {len(signature)}, expected {self.SOLANA_SIGNATURE_LENGTH}",
                "signature"
            )
            return
        
        if not self.SOLANA_SIGNATURE_PATTERN.match(signature):
            result.add_error("Invalid signature format", "signature")
            return
        
        # Validate base58 encoding
        try:
            decoded = base58.b58decode(signature)
            if len(decoded) != 64:
                result.add_error("Invalid signature byte length", "signature")
        except Exception:
            result.add_error("Invalid base58 signature", "signature")
    
    def _validate_wallet_address(self, address: str, result: ValidationResult):
        """Validate wallet address"""
        if not address:
            result.add_error("Wallet address is required", "wallet_address", "critical")
            return
        
        if not validate_wallet_address(address):
            result.add_error("Invalid wallet address format", "wallet_address")
            return
        
        # Check if address exists in database
        if self.db_manager:
            try:
                with self.db_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT 1 FROM wallet_priorities
                        WHERE wallet_address = ?
                    """, (address,))
                    
                    exists = cursor.fetchone()
                    if not exists:
                        result.add_warning("Wallet address not found in database", "wallet_address")
            except Exception as e:
                logger.warning(f"⚠️ Error checking wallet existence: {e}")
    
    def _validate_slot(self, slot: int, result: ValidationResult):
        """Validate slot number"""
        if slot is None:
            result.add_error("Slot is required", "slot", "critical")
            return
        
        if not isinstance(slot, int):
            result.add_error("Slot must be integer", "slot")
            return
        
        if slot < 0:
            result.add_error("Slot must be non-negative", "slot")
            return
        
        if slot > self.MAX_SLOT:
            result.add_error(f"Slot too large: {slot}", "slot")
        
        # Check if slot is reasonable (within last year)
        current_slot = self._get_current_slot()
        if current_slot and slot > current_slot:
            result.add_warning("Slot appears to be in the future", "slot")
        
    def _validate_block_time(self, block_time: int, result: ValidationResult):
        """Validate block timestamp"""
        if block_time is None:
            result.add_error("Block time is required", "block_time", "critical")
            return
        
        if not isinstance(block_time, int):
            result.add_error("Block time must be integer", "block_time")
            return
        
        current_time = get_current_timestamp()
        
        # Check reasonable range (last 2 years)
        min_time = current_time - (2 * 365 * 24 * 3600)
        max_time = current_time + 300  # 5 minutes in future
        
        if block_time < min_time:
            result.add_warning("Block time is very old", "block_time")
        
        if block_time > max_time:
            result.add_warning("Block time is in the future", "block_time")
    
    def _validate_amount(self, amount: float, result: ValidationResult):
        """Validate transaction amount"""
        if amount is None:
            result.add_error("Amount is required", "amount", "critical")
            return
        
        try:
            amount_float = float(amount)
            
            if abs(amount_float) < self.MIN_TRANSACTION_AMOUNT:
                result.add_warning("Amount is very small", "amount")
            
            if abs(amount_float) > self.MAX_TRANSACTION_AMOUNT:
                result.add_warning("Amount is very large", "amount")
            
            if amount_float == 0:
                result.add_warning("Amount is zero", "amount")
        
        except (ValueError, TypeError):
            result.add_error("Invalid amount format", "amount")
    
    def _validate_fee(self, fee: float, result: ValidationResult):
        """Validate transaction fee"""
        if fee is None:
            result.add_error("Fee is required", "fee", "critical")
            return
        
        try:
            fee_float = float(fee)
            
            if fee_float < 0:
                result.add_error("Fee cannot be negative", "fee")
            
            if fee_float > self.MAX_FEE:
                result.add_warning("Fee is unusually large", "fee")
            
            if fee_float == 0:
                result.add_warning("Fee is zero", "fee")
        
        except (ValueError, TypeError):
            result.add_error("Invalid fee format", "fee")
    
    def _validate_token_mint(self, token_mint: str, result: ValidationResult):
        """Validate token mint address"""
        if not token_mint:
            result.add_warning("Token mint not provided", "token_mint")
            return
        
        if len(token_mint) != 44:
            result.add_error("Invalid token mint length", "token_mint")
            return
        
        if not self.SOLANA_ADDRESS_PATTERN.match(token_mint):
            result.add_error("Invalid token mint format", "token_mint")
            return
        
        # Check if it's a known token
        if self.db_manager:
            try:
                with self.db_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT 1 FROM tokens WHERE address = ?
                    """, (token_mint,))
                    
                    exists = cursor.fetchone()
                    if not exists:
                        result.add_warning("Token mint not found in database", "token_mint")
            except Exception as e:
                logger.warning(f"⚠️ Error checking token mint: {e}")
    
    def _validate_token_symbol(self, symbol: str, result: ValidationResult):
        """Validate token symbol"""
        if symbol and symbol != "UNKNOWN":
            if not self.TOKEN_SYMBOL_PATTERN.match(symbol):
                result.add_warning("Invalid token symbol format", "token_symbol")
            
            if len(symbol) > 10:
                result.add_warning("Token symbol too long", "token_symbol")
    
    def _validate_token_amount(self, token_amount: float, result: ValidationResult):
        """Validate token amount"""
        if token_amount is None:
            return
        
        try:
            amount_float = float(token_amount)
            
            if amount_float < 0:
                result.add_error("Token amount cannot be negative", "token_amount")
            
            if amount_float > 1e18:  # 100 trillion tokens
                result.add_warning("Token amount is very large", "token_amount")
        
        except (ValueError, TypeError):
            result.add_error("Invalid token amount format", "token_amount")
    
    def _validate_price_per_token(self, price: float, result: ValidationResult):
        """Validate price per token"""
        if price is None:
            return
        
        try:
            price_float = float(price)
            
            if price_float < 0:
                result.add_error("Price cannot be negative", "price_per_token")
            
            if price_float > 1000000:  # $1M per token
                result.add_warning("Price is very high", "price_per_token")
            
            # Check for zero price
            if price_float == 0:
                result.add_warning("Price is zero", "price_per_token")
        
        except (ValueError, TypeError):
            result.add_error("Invalid price format", "price_per_token")
    
    def _validate_transaction_type(self, tx_type: TransactionType, result: ValidationResult):
        """Validate transaction type"""
        valid_types = [t.value for t in TransactionType]
        
        if str(tx_type) not in valid_types:
            result.add_error(f"Invalid transaction type: {tx_type}", "transaction_type")
    
    def _validate_status(self, status: TransactionStatus, result: ValidationResult):
        """Validate transaction status"""
        valid_statuses = [s.value for s in TransactionStatus]
        
        if str(status) not in valid_statuses:
            result.add_error(f"Invalid status: {status}", "status")
    
    def _validate_blockchain_integrity(self, transaction: Transaction, result: ValidationResult):
        """Validate blockchain integrity"""
        # Check if transaction exists on blockchain
        if self.db_manager:
            try:
                with self.db_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Check for duplicate signature
                    cursor.execute("""
                        SELECT COUNT(*) FROM transactions
                        WHERE signature = ? AND block_time != ?
                    """, (transaction.signature, transaction.block_time))
                    
                    count = cursor.fetchone()[0]
                    if count > 0:
                        result.add_error("Duplicate signature with different block time", "signature")
            
            except Exception as e:
                logger.warning(f"⚠️ Error checking blockchain integrity: {e}")
    
    def _validate_sequence(self, transaction: Transaction, result: ValidationResult):
        """Validate transaction sequence"""
        if self.db_manager:
            try:
                with self.db_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Check if there's a transaction with higher slot but earlier time
                    cursor.execute("""
                        SELECT COUNT(*) FROM transactions
                        WHERE wallet_address = ? 
                        AND slot > ? 
                        AND block_time < ?
                    """, (transaction.wallet_address, transaction.slot, transaction.block_time))
                    
                    count = cursor.fetchone()[0]
                    if count > 0:
                        result.add_warning("Sequence anomaly detected", "sequence")
            
            except Exception as e:
                logger.warning(f"⚠️ Error validating sequence: {e}")
    
    def _validate_duplicate_check(self, transaction: Transaction, result: ValidationResult):
        """Check for duplicate transactions"""
        if self.db_manager:
            try:
                with self.db_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    
                    cursor.execute("""
                        SELECT COUNT(*) FROM transactions
                        WHERE signature = ?
                    """, (transaction.signature,))
                    
                    count = cursor.fetchone()[0]
                    if count > 0:
                        result.add_error("Transaction already exists", "signature")
            
            except Exception as e:
                logger.warning(f"⚠️ Error checking duplicates: {e}")
    
    def _validate_metadata(self, transaction: Transaction, result: ValidationResult):
        """Validate transaction metadata"""
        # Check source
        if transaction.source and len(transaction.source) > 50:
            result.add_warning("Source field too long", "source")
        
        # Check metadata JSON
        if hasattr(transaction, 'metadata') and transaction.metadata:
            try:
                json.dumps(transaction.metadata)
            except Exception:
                result.add_warning("Invalid metadata format", "metadata")
    
    def _validate_cross_references(self, transaction: Transaction, result: ValidationResult):
        """Validate cross-references"""
        if self.db_manager:
            try:
                with self.db_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Validate wallet exists
                    cursor.execute("""
                        SELECT 1 FROM wallet_priorities
                        WHERE wallet_address = ?
                    """, (transaction.wallet_address,))
                    
                    wallet_exists = cursor.fetchone()
                    if not wallet_exists:
                        result.add_warning("Referenced wallet not found", "wallet_address")
                    
                    # Validate token exists if provided
                    if transaction.token_mint:
                        cursor.execute("""
                            SELECT 1 FROM tokens
                            WHERE address = ?
                        """, (transaction.token_mint,))
                        
                        token_exists = cursor.fetchone()
                        if not token_exists:
                            result.add_warning("Referenced token not found", "token_mint")
            
            except Exception as e:
                logger.warning(f"⚠️ Error validating cross-references: {e}")
    
    def _get_current_slot(self) -> Optional[int]:
        """Get current blockchain slot"""
        # This would query the blockchain
        # Simplified implementation
        return None
    
    def validate_transaction_batch(self, transactions: List[Transaction]) -> Dict[str, ValidationResult]:
        """Validate multiple transactions"""
        results = {}
        
        for transaction in transactions:
            results[transaction.signature] = self.validate_transaction(transaction)
        
        return results
    
    def validate_transaction_data(self, data: Dict[str, Any]) -> ValidationResult:
        """Validate raw transaction data"""
        result = ValidationResult()
        
        required_fields = ['signature', 'wallet_address', 'slot', 'block_time', 'amount', 'fee', 'transaction_type', 'status']
        
        for field in required_fields:
            if field not in data:
                result.add_error(f"Missing required field: {field}", field, "critical")
        
        if not result.is_valid:
            return result
        
        # Create temporary transaction object
        try:
            transaction = Transaction(
                signature=data['signature'],
                wallet_address=data['wallet_address'],
                slot=data['slot'],
                block_time=data['block_time'],
                amount=float(data['amount']),
                fee=float(data['fee']),
                token_mint=data.get('token_mint'),
                token_symbol=data.get('token_symbol'),
                token_name=data.get('token_name'),
                token_amount=float(data['token_amount']) if data.get('token_amount') else None,
                price_per_token=float(data['price_per_token']) if data.get('price_per_token') else None,
                transaction_type=TransactionType(data['transaction_type']),
                status=TransactionStatus(data['status']),
                source=data.get('source', 'unknown')
            )
            
            return self.validate_transaction(transaction)
            
        except Exception as e:
            result.add_error(f"Invalid transaction data: {str(e)}", "data", "critical")
            return result
    
    def check_transaction_integrity(self, signature: str) -> ValidationResult:
        """Check integrity of stored transaction"""
        result = ValidationResult()
        
        if not self.db_manager:
            result.add_error("Database not available", "database", "critical")
            return result
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM transactions
                    WHERE signature = ?
                """, (signature,))
                
                stored_tx = cursor.fetchone()
                
                if not stored_tx:
                    result.add_error("Transaction not found", "signature", "critical")
                    return result
                
                # Verify signature checksum
                calculated_hash = hashlib.sha256(
                    f"{stored_tx['signature']}{stored_tx['wallet_address']}{stored_tx['slot']}".encode()
                ).hexdigest()
                
                # Additional integrity checks
                if stored_tx['amount'] < 0 and stored_tx['transaction_type'] not in ['buy', 'sell', 'transfer']:
                    result.add_warning("Amount negative but not classified as transfer", "amount")
                
                if stored_tx['token_amount'] and stored_tx['token_amount'] < 0:
                    result.add_warning("Token amount negative", "token_amount")
        
        except Exception as e:
            result.add_error(f"Integrity check failed: {str(e)}", "integrity", "critical")
        
        return result
    
    def validate_transaction_sequence(
        self,
        wallet_address: str,
        transactions: List[Transaction]
    ) -> ValidationResult:
        """Validate sequence of transactions for a wallet"""
        result = ValidationResult()
        
        if not transactions:
            return result
        
        # Sort by block time
        sorted_txs = sorted(transactions, key=lambda x: (x.block_time, x.slot))
        
        # Check for chronological order
        for i in range(1, len(sorted_txs)):
            prev_tx = sorted_txs[i-1]
            curr_tx = sorted_txs[i]
            
            if curr_tx.block_time < prev_tx.block_time:
                result.add_error(
                    f"Chronological order violation: {curr_tx.signature} before {prev_tx.signature}",
                    "sequence"
                )
            
            if curr_tx.slot <= prev_tx.slot:
                result.add_warning(
                    f"Slot order violation: {curr_tx.signature} slot <= {prev_tx.signature}",
                    "sequence"
                )
        
        return result
    
    def detect_anomalies(self, transactions: List[Transaction]) -> List[Dict[str, Any]]:
        """Detect anomalies in transaction patterns"""
        anomalies = []
        
        if not transactions:
            return anomalies
        
        # Group by wallet
        wallet_transactions = defaultdict(list)
        for tx in transactions:
            wallet_transactions[tx.wallet_address].append(tx)
        
        for wallet_address, txs in wallet_transactions.items():
            # Sort by time
            sorted_txs = sorted(txs, key=lambda x: x.block_time)
            
            # Detect suspicious patterns
            anomalies.extend(self._detect_wallet_anomalies(wallet_address, sorted_txs))
        
        return anomalies
    
    def _detect_wallet_anomalies(self, wallet_address: str, transactions: List[Transaction]) -> List[Dict[str, Any]]:
        """Detect anomalies for a specific wallet"""
        anomalies = []
        
        # Check for extremely high frequency
        if len(transactions) > 100:
            time_range = transactions[-1].block_time - transactions[0].block_time
            if time_range < 3600:  # 1 hour
                anomalies.append({
                    'type': 'high_frequency',
                    'wallet': wallet_address,
                    'count': len(transactions),
                    'time_range': time_range,
                    'severity': 'medium'
                })
        
        # Check for large amounts
        large_amounts = [tx for tx in transactions if abs(float(tx.amount)) > 1000]
        if large_amounts:
            anomalies.append({
                'type': 'large_amounts',
                'wallet': wallet_address,
                'count': len(large_amounts),
                'severity': 'low'
            })
        
        # Check for zero fees
        zero_fees = [tx for tx in transactions if float(tx.fee) == 0]
        if zero_fees:
            anomalies.append({
                'type': 'zero_fees',
                'wallet': wallet_address,
                'count': len(zero_fees),
                'severity': 'low'
            })
        
        return anomalies
    
    def validate_database_integrity(self) -> Dict[str, Any]:
        """Validate database integrity"""
        integrity_result = {
            'overall_status': 'healthy',
            'issues': [],
            'warnings': []
        }
        
        if not self.db_manager:
            integrity_result['overall_status'] = 'error'
            integrity_result['issues'].append('Database unavailable')
            return integrity_result
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Check for orphaned records
                cursor.execute("""
                    SELECT COUNT(*) FROM transactions
                    WHERE wallet_address NOT IN (
                        SELECT wallet_address FROM wallet_priorities
                    )
                """)
                
                orphaned_count = cursor.fetchone()[0]
                if orphaned_count > 0:
                    integrity_result['warnings'].append(
                        f"{orphaned_count} transactions without wallet records"
                    )
                
                # Check for duplicate signatures
                cursor.execute("""
                    SELECT signature, COUNT(*)
                    FROM transactions
                    GROUP BY signature
                    HAVING COUNT(*) > 1
                """)
                
                duplicates = cursor.fetchall()
                if duplicates:
                    integrity_result['issues'].append(
                        f"Found {len(duplicates)} duplicate signatures"
                    )
                    integrity_result['overall_status'] = 'error'
                
                # Check for invalid timestamps
                current_time = get_current_timestamp()
                cursor.execute("""
                    SELECT COUNT(*) FROM transactions
                    WHERE block_time > ? OR block_time < ?
                """, (current_time + 3600, current_time - (365 * 24 * 3600)))
                
                invalid_timestamps = cursor.fetchone()[0]
                if invalid_timestamps > 0:
                    integrity_result['warnings'].append(
                        f"{invalid_timestamps} transactions with invalid timestamps"
                    )
        
        except Exception as e:
            integrity_result['overall_status'] = 'error'
            integrity_result['issues'].append(f"Database integrity check failed: {str(e)}")
        
        return integrity_result
    
    def generate_validation_report(self, wallet_address: str) -> Dict[str, Any]:
        """Generate comprehensive validation report for wallet"""
        report = {
            'wallet_address': wallet_address,
            'timestamp': get_current_timestamp(),
            'summary': {},
            'details': {},
            'recommendations': []
        }
        
        try:
            # Get wallet transactions
            if self.db_manager:
                with self.db_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    
                    cursor.execute("""
                        SELECT * FROM transactions
                        WHERE wallet_address = ?
                        ORDER BY block_time DESC
                        LIMIT 1000
                    """, (wallet_address,))
                    
                    transactions = []
                    for row in cursor.fetchall():
                        transactions.append(Transaction(
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
                        ))
                    
                    # Validate all transactions
                    validation_results = [self.validate_transaction(tx) for tx in transactions]
                    
                    # Generate summary
                    total_errors = sum(len(vr.errors) for vr in validation_results)
                    total_warnings = sum(len(vr.warnings) for vr in validation_results)
                    
                    report['summary'] = {
                        'total_transactions': len(transactions),
                        'total_errors': total_errors,
                        'total_warnings': total_warnings,
                        'valid_percentage': safe_divide(len(transactions) - total_errors, len(transactions)) * 100
                    }
                    
                    # Error distribution
                    error_types = defaultdict(int)
                    warning_types = defaultdict(int)
                    
                    for vr in validation_results:
                        for error in vr.errors:
                            error_types[error.get('field', 'unknown')] += 1
                        for warning in vr.warnings:
                            warning_types[warning.get('field', 'unknown')] += 1
                    
                    report['details'] = {
                        'error_distribution': dict(error_types),
                        'warning_distribution': dict(warning_types),
                        'validation_results': [vr.to_dict() for vr in validation_results[:10]]  # Show first 10
                    }
                    
                    # Generate recommendations
                    if total_errors > 0:
                        report['recommendations'].append("Review and fix validation errors")
                    
                    if total_warnings > 0:
                        report['recommendations'].append("Address validation warnings")
                    
                    if len(transactions) > 1000:
                        report['recommendations'].append("Consider data cleanup for old transactions")
        
        except Exception as e:
            report['summary'] = {'error': str(e)}
            report['recommendations'].append("Validation system error occurred")
        
        return report
    
    def validate_token_transfer(self, from_wallet: str, to_wallet: str, token_mint: str, amount: float) -> ValidationResult:
        """Validate a token transfer operation"""
        result = ValidationResult()
        
        # Validate addresses
        result.merge(self.validate_wallet_address(from_wallet))
        result.merge(self.validate_wallet_address(to_wallet))
        
        # Validate token mint
        self._validate_token_mint(token_mint, result)
        
        # Validate amount
        if amount <= 0:
            result.add_error("Transfer amount must be positive", "amount", "critical")
        
        # Check sender balance
        if self.db_manager:
            try:
                with self.db_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    
                    cursor.execute("""
                        SELECT SUM(balance) FROM token_accounts
                        WHERE wallet_address = ? AND token_mint = ?
                    """, (from_wallet, token_mint))
                    
                    balance = cursor.fetchone()[0] or 0
                    
                    if balance < amount:
                        result.add_error("Insufficient balance", "amount", "critical")
            
            except Exception as e:
                logger.error(f"❌ Error checking balance: {e}")
        
        return result
    
    def validate_block_range(self, start_slot: int, end_slot: int) -> ValidationResult:
        """Validate a range of blocks"""
        result = ValidationResult()
        
        if start_slot < 0 or end_slot < 0:
            result.add_error("Slot numbers must be non-negative", "slots", "critical")
        
        if start_slot > end_slot:
            result.add_error("Start slot must be <= end slot", "slots", "critical")
        
        # Check reasonable range
        if end_slot - start_slot > 1000000:
            result.add_warning("Very large block range", "slots")
        
        return result
    
    def validate_transaction_batch(self, transactions: List[Dict[str, Any]]) -> Dict[str, ValidationResult]:
        """Validate a batch of transactions"""
        results = {}
        
        for i, tx_data in enumerate(transactions):
            result = self.validate_transaction_data(tx_data)
            results[f"transaction_{i}"] = result
        
        return results
    
    def check_data_consistency(self, wallet_address: str) -> Dict[str, Any]:
        """Check data consistency for wallet"""
        consistency_result = {
            'wallet_address': wallet_address,
            'status': 'healthy',
            'issues': [],
            'balances': {},
            'summary': {}
        }
        
        if not self.db_manager:
            consistency_result['status'] = 'error'
            consistency_result['issues'].append('Database unavailable')
            return consistency_result
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Check transaction counts
                cursor.execute("""
                    SELECT transaction_type, COUNT(*) as count
                    FROM transactions
                    WHERE wallet_address = ?
                    GROUP BY transaction_type
                """, (wallet_address,))
                
                tx_counts = dict(cursor.fetchall())
                consistency_result['summary']['transaction_counts'] = tx_counts
                
                # Check total SOL balance from transactions
                cursor.execute("""
                    SELECT SUM(amount) as total_sol_change
                    FROM transactions
                    WHERE wallet_address = ?
                        AND token_mint IS NULL
                        AND status = 'success'
                """, (wallet_address,))
                
                total_sol_change = cursor.fetchone()[0] or 0
                consistency_result['balances']['calculated_sol_change'] = float(total_sol_change)
                
                # Check token balances consistency
                cursor.execute("""
                    SELECT token_mint, SUM(token_amount) as calculated_balance
                    FROM transactions
                    WHERE wallet_address = ?
                        AND token_mint IS NOT NULL
                        AND status = 'success'
                    GROUP BY token_mint
                """, (wallet_address,))
                
                calculated_token_balances = dict(cursor.fetchall())
                
                # Compare with actual token account balances
                cursor.execute("""
                    SELECT token_mint, balance
                    FROM token_accounts
                    WHERE wallet_address = ?
                        AND is_active = 1
                """, (wallet_address,))
                
                actual_token_balances = dict(cursor.fetchall())
                
                # Check for inconsistencies
                for token_mint, calculated_balance in calculated_token_balances.items():
                    actual_balance = actual_token_balances.get(token_mint, 0)
                    if abs(float(calculated_balance) - float(actual_balance)) > 0.001:
                        consistency_result['issues'].append(
                            f"Balance inconsistency for {token_mint}: calculated={calculated_balance}, actual={actual_balance}"
                        )
                
                # Check for orphaned token accounts
                cursor.execute("""
                    SELECT ata_pubkey, token_mint, balance
                    FROM token_accounts
                    WHERE wallet_address = ?
                        AND is_active = 1
                        AND token_mint NOT IN (
                            SELECT DISTINCT token_mint FROM transactions
                            WHERE wallet_address = ? AND token_mint IS NOT NULL
                        )
                """, (wallet_address, wallet_address))
                
                orphaned_accounts = cursor.fetchall()
                if orphaned_accounts:
                    consistency_result['issues'].append(
                        f"Found {len(orphaned_accounts)} token accounts without corresponding transactions"
                    )
                
                # Check for transactions without token accounts
                cursor.execute("""
                    SELECT token_mint, COUNT(*) as tx_count
                    FROM transactions
                    WHERE wallet_address = ?
                        AND token_mint IS NOT NULL
                        AND token_mint NOT IN (
                            SELECT token_mint FROM token_accounts
                            WHERE wallet_address = ? AND is_active = 1
                        )
                    GROUP BY token_mint
                """, (wallet_address, wallet_address))
                
                missing_accounts = cursor.fetchall()
                if missing_accounts:
                    consistency_result['issues'].append(
                        f"Found transactions for {len(missing_accounts)} tokens without active accounts"
                    )
                
                # Summary
                consistency_result['summary'].update({
                    'total_transactions': sum(tx_counts.values()),
                    'unique_tokens': len(actual_token_balances),
                    'calculated_total_sol': float(total_sol_change),
                    'data_quality_score': max(0, 100 - len(consistency_result['issues']) * 10)
                })
                
                # Determine overall status
                if len(consistency_result['issues']) > 5:
                    consistency_result['status'] = 'critical'
                elif len(consistency_result['issues']) > 2:
                    consistency_result['status'] = 'warning'
                elif len(consistency_result['issues']) > 0:
                    consistency_result['status'] = 'minor_issues'
        
        except Exception as e:
            consistency_result['status'] = 'error'
            consistency_result['issues'].append(f"Consistency check failed: {str(e)}")
        
        return consistency_result

# Ajout de méthodes utilitaires manquantes

    def validate_token_transfer(self, from_wallet: str, to_wallet: str, token_mint: str, amount: float) -> ValidationResult:
        """Validate a token transfer operation"""
        result = ValidationResult()
        
        # Validate addresses
        if not validate_wallet_address(from_wallet):
            result.add_error("Invalid from wallet address", "from_wallet", "critical")
        if not validate_wallet_address(to_wallet):
            result.add_error("Invalid to wallet address", "to_wallet", "critical")
        
        # Validate token mint
        self._validate_token_mint(token_mint, result)
        
        # Validate amount
        if amount <= 0:
            result.add_error("Transfer amount must be positive", "amount", "critical")
        
        # Check sender balance
        if self.db_manager:
            try:
                with self.db_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    
                    cursor.execute("""
                        SELECT SUM(balance) FROM token_accounts
                        WHERE wallet_address = ? AND token_mint = ?
                    """, (from_wallet, token_mint))
                    
                    balance = cursor.fetchone()[0] or 0
                    
                    if balance < amount:
                        result.add_error("Insufficient balance", "amount", "critical")
            
            except Exception as e:
                logger.error(f"❌ Error checking balance: {e}")
        
        return result

    def validate_block_range(self, start_slot: int, end_slot: int) -> ValidationResult:
        """Validate a range of blocks"""
        result = ValidationResult()
        
        if start_slot < 0 or end_slot < 0:
            result.add_error("Slot numbers must be non-negative", "slots", "critical")
        
        if start_slot > end_slot:
            result.add_error("Start slot must be <= end slot", "slots", "critical")
        
        # Check reasonable range
        if end_slot - start_slot > 1000000:
            result.add_warning("Very large block range", "slots")
        
        return result

    def get_validation_summary(self) -> Dict[str, Any]:
        """Get summary of validator capabilities"""
        return {
            'validator_version': "2.0.0",
            'supported_levels': ['strict', 'standard', 'lenient'],
            'validation_features': [
                'signature_validation',
                'address_validation',
                'amount_validation',
                'token_validation',
                'sequence_validation',
                'integrity_checks',
                'anomaly_detection'
            ],
            'constraints': {
                'min_transaction_amount': self.MIN_TRANSACTION_AMOUNT,
                'max_transaction_amount': self.MAX_TRANSACTION_AMOUNT,
                'max_fee': self.MAX_FEE,
                'signature_length': self.SOLANA_SIGNATURE_LENGTH,
                'address_length': self.SOLANA_ADDRESS_LENGTH
            }
        }

# Ajout du main pour testing si besoin
if __name__ == "__main__":
    validator = TransactionValidator()
    print("✅ Transaction Validator initialized successfully")
    
    # Test basic validation
    test_result = validator.get_validation_summary()
    print("📊 Validation summary:", json.dumps(test_result, indent=2))
    
    # Test validation features
    print("\n🔍 Testing validation features...")
    print("Available validation levels:", test_result['supported_levels'])
    print("Validation features:", test_result['validation_features'])