
#!/usr/bin/env python3
"""
Validateurs pour le Solana Wallet Monitor
Validation complète des données blockchain Solana et métier
"""

import re
import time
import json
import hashlib
from typing import Any, Dict, List, Optional, Union, Tuple
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse
from dataclasses import dataclass
from enum import Enum

# Imports internes avec fallback gracieux
try:
    from utils.constants import (
        SOLANA_ADDRESS_PATTERN, SOLANA_SIGNATURE_PATTERN,
        TOKEN_SYMBOL_PATTERN, LAMPORTS_PER_SOL,
        SECURITY_LIMITS, VALIDATION_PATTERNS
    )
except ImportError:
    # Fallbacks si constantes non disponibles
    SOLANA_ADDRESS_PATTERN = r'^[1-9A-HJ-NP-Za-km-z]{44}$'
    SOLANA_SIGNATURE_PATTERN = r'^[1-9A-HJ-NP-Za-km-z]{88}$'
    TOKEN_SYMBOL_PATTERN = r'^[A-Z][A-Z0-9_]{1,10}$'
    LAMPORTS_PER_SOL = 1_000_000_000
    SECURITY_LIMITS = {
        'max_wallets_per_instance': 1000,
        'max_tokens_per_wallet': 50000,
        'max_transactions_per_scan': 10000,
        'max_rpc_requests_per_minute': 300
    }
    VALIDATION_PATTERNS = {
        'cycle_id': r'^cycle_\d+_\d+$',
        'scan_id': r'^scan_[a-zA-Z0-9]{6,8}_\d+$'
    }

try:
    import base58
    HAS_BASE58 = True
except ImportError:
    HAS_BASE58 = False

class ValidationLevel(Enum):
    """Niveaux de validation"""
    STRICT = "strict"      # Validation stricte avec tous les checks
    STANDARD = "standard"  # Validation standard (défaut)
    LENIENT = "lenient"    # Validation souple pour développement

class ValidationError(Exception):
    """Exception de validation personnalisée"""
    def __init__(self, message: str, field: str = None, value: Any = None, code: str = None):
        super().__init__(message)
        self.message = message
        self.field = field
        self.value = value
        self.code = code or "VALIDATION_ERROR"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'error': self.message,
            'field': self.field,
            'value': str(self.value) if self.value is not None else None,
            'code': self.code
        }

@dataclass
class ValidationResult:
    """Résultat d'une validation"""
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    field_errors: Dict[str, List[str]]
    
    def __init__(self):
        self.is_valid = True
        self.errors = []
        self.warnings = []
        self.field_errors = {}
    
    def add_error(self, message: str, field: str = None):
        """Ajoute une erreur et invalide le résultat"""
        self.is_valid = False
        self.errors.append(message)
        if field:
            if field not in self.field_errors:
                self.field_errors[field] = []
            self.field_errors[field].append(message)
    
    def add_warning(self, message: str, field: str = None):
        """Ajoute un avertissement sans invalider"""
        self.warnings.append(message)
        # Les warnings ne créent pas d'entrées field_errors
    
    def merge(self, other: 'ValidationResult'):
        """Fusionne avec un autre résultat de validation"""
        if not other.is_valid:
            self.is_valid = False
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        for field, errors in other.field_errors.items():
            if field not in self.field_errors:
                self.field_errors[field] = []
            self.field_errors[field].extend(errors)

# ========================
# VALIDATEURS BLOCKCHAIN SOLANA
# ========================

class SolanaValidator:
    """Validateur spécialisé pour les données blockchain Solana"""
    
    @staticmethod
    def validate_address(address: str, level: ValidationLevel = ValidationLevel.STANDARD) -> ValidationResult:
        """Valide une adresse Solana (wallet, token mint, ATA, etc.)"""
        result = ValidationResult()
        
        if not address:
            result.add_error("Adresse requise", "address")
            return result
        
        if not isinstance(address, str):
            result.add_error(f"Adresse doit être une chaîne, reçu: {type(address).__name__}", "address")
            return result
        
        # Nettoyage basique
        address = address.strip()
        
        # Validation longueur
        if len(address) != 44:
            result.add_error(f"Adresse Solana doit faire 44 caractères, reçu: {len(address)}", "address")
            return result
        
        # Validation pattern Base58
        if not re.match(SOLANA_ADDRESS_PATTERN, address):
            result.add_error("Format d'adresse Solana invalide (doit être en Base58)", "address")
            return result
        
        # Validation stricte avec décodage Base58 si possible
        if level == ValidationLevel.STRICT and HAS_BASE58:
            try:
                decoded = base58.b58decode(address)
                if len(decoded) != 32:
                    result.add_error(f"Adresse décodée doit faire 32 bytes, reçu: {len(decoded)}", "address")
                    return result
            except Exception as e:
                result.add_error(f"Décodage Base58 échoué: {str(e)}", "address")
                return result
        
        # Warnings pour adresses spéciales
        if address == "11111111111111111111111111111111111111111112":
            result.add_warning("Adresse système détectée (System Program)")
        elif address == "So11111111111111111111111111111111111111112":
            result.add_warning("Adresse Wrapped SOL détectée")
        elif address.startswith("1111111111111111111111111111111111111111111"):
            result.add_warning("Adresse système ou programme détectée")
        
        return result
    
    @staticmethod
    def validate_signature(signature: str, level: ValidationLevel = ValidationLevel.STANDARD) -> ValidationResult:
        """Valide une signature de transaction Solana"""
        result = ValidationResult()
        
        if not signature:
            result.add_error("Signature requise", "signature")
            return result
        
        if not isinstance(signature, str):
            result.add_error(f"Signature doit être une chaîne, reçu: {type(signature).__name__}", "signature")
            return result
        
        # Nettoyage
        signature = signature.strip()
        
        # Validation longueur
        if len(signature) != 88:
            result.add_error(f"Signature Solana doit faire 88 caractères, reçu: {len(signature)}", "signature")
            return result
        
        # Validation pattern Base58
        if not re.match(SOLANA_SIGNATURE_PATTERN, signature):
            result.add_error("Format de signature Solana invalide (doit être en Base58)", "signature")
            return result
        
        # Validation stricte avec décodage
        if level == ValidationLevel.STRICT and HAS_BASE58:
            try:
                decoded = base58.b58decode(signature)
                if len(decoded) != 64:
                    result.add_error(f"Signature décodée doit faire 64 bytes, reçu: {len(decoded)}", "signature")
                    return result
            except Exception as e:
                result.add_error(f"Décodage Base58 de signature échoué: {str(e)}", "signature")
                return result
        
        return result
    
    @staticmethod
    def validate_slot(slot: Union[int, str], level: ValidationLevel = ValidationLevel.STANDARD) -> ValidationResult:
        """Valide un numéro de slot Solana"""
        result = ValidationResult()
        
        try:
            slot_num = int(slot)
        except (ValueError, TypeError):
            result.add_error(f"Slot doit être un entier, reçu: {slot}", "slot")
            return result
        
        if slot_num < 0:
            result.add_error(f"Slot ne peut pas être négatif: {slot_num}", "slot")
            return result
        
        # Validation stricte - slot ne peut pas être trop futur
        if level == ValidationLevel.STRICT:
            # Estimation: ~2.3 slots par seconde en moyenne
            current_time = int(time.time())
            # Slot genesis approximatif (2020-03-16)
            genesis_time = 1584355200
            max_reasonable_slot = (current_time - genesis_time) * 2.5
            
            if slot_num > max_reasonable_slot:
                result.add_warning(f"Slot semble trop élevé: {slot_num} (max raisonnable: {int(max_reasonable_slot)})")
        
        return result
    
    @staticmethod
    def validate_lamports(lamports: Union[int, str, float], allow_zero: bool = True) -> ValidationResult:
        """Valide un montant en lamports"""
        result = ValidationResult()
        
        try:
            lamports_num = int(float(lamports))
        except (ValueError, TypeError):
            result.add_error(f"Lamports doit être un nombre, reçu: {lamports}", "lamports")
            return result
        
        if not allow_zero and lamports_num == 0:
            result.add_error("Montant en lamports ne peut pas être zéro", "lamports")
            return result
        
        if lamports_num < 0:
            result.add_error(f"Montant en lamports ne peut pas être négatif: {lamports_num}", "lamports")
            return result
        
        # Warning pour très gros montants (>1M SOL)
        if lamports_num > LAMPORTS_PER_SOL * 1_000_000:
            sol_equivalent = lamports_num / LAMPORTS_PER_SOL
            result.add_warning(f"Montant très élevé détecté: {sol_equivalent:,.0f} SOL")
        
        return result
    
    @staticmethod
    def validate_sol_amount(amount: Union[float, str, Decimal], allow_zero: bool = True) -> ValidationResult:
        """Valide un montant en SOL"""
        result = ValidationResult()
        
        try:
            if isinstance(amount, str):
                amount_decimal = Decimal(amount)
            else:
                amount_decimal = Decimal(str(amount))
        except (ValueError, InvalidOperation):
            result.add_error(f"Montant SOL invalide: {amount}", "sol_amount")
            return result
        
        if not allow_zero and amount_decimal == 0:
            result.add_error("Montant SOL ne peut pas être zéro", "sol_amount")
            return result
        
        if amount_decimal < 0:
            result.add_error(f"Montant SOL ne peut pas être négatif: {amount_decimal}", "sol_amount")
            return result
        
        # Warning pour montants très élevés
        if amount_decimal > 1_000_000:
            result.add_warning(f"Montant SOL très élevé: {amount_decimal:,.2f} SOL")
        
        # Warning pour précision excessive (>9 décimales)
        if amount_decimal != amount_decimal.quantize(Decimal('0.000000001')):
            result.add_warning("Précision supérieure aux lamports détectée (>9 décimales)")
        
        return result

# ========================
# VALIDATEURS TOKENS
# ========================

class TokenValidator:
    """Validateur spécialisé pour les données de tokens"""
    
    @staticmethod
    def validate_symbol(symbol: str, level: ValidationLevel = ValidationLevel.STANDARD) -> ValidationResult:
        """Valide un symbole de token"""
        result = ValidationResult()
        
        if not symbol:
            result.add_error("Symbole de token requis", "symbol")
            return result
        
        if not isinstance(symbol, str):
            result.add_error(f"Symbole doit être une chaîne, reçu: {type(symbol).__name__}", "symbol")
            return result
        
        # Nettoyage
        symbol = symbol.strip().upper()
        
        # Validation longueur
        if len(symbol) > 12:
            result.add_error(f"Symbole trop long: {len(symbol)} caractères (max: 12)", "symbol")
            return result
        
        if len(symbol) < 1:
            result.add_error("Symbole ne peut pas être vide", "symbol")
            return result
        
        # Validation pattern selon le niveau
        if level in [ValidationLevel.STRICT, ValidationLevel.STANDARD]:
            if not re.match(TOKEN_SYMBOL_PATTERN, symbol):
                if level == ValidationLevel.STRICT:
                    result.add_error(f"Symbole invalide: {symbol} (doit commencer par une lettre et contenir seulement lettres, chiffres, _)", "symbol")
                else:
                    result.add_warning(f"Symbole non-standard: {symbol}")
        
        # Détection symboles problématiques
        suspicious_patterns = [
            r'.*SCAM.*', r'.*FAKE.*', r'.*TEST.*', r'.*UNKNOWN.*',
            r'.*\$.*', r'.*\..*', r'.*\s.*'
        ]
        
        for pattern in suspicious_patterns:
            if re.match(pattern, symbol, re.IGNORECASE):
                result.add_warning(f"Symbole potentiellement problématique: {symbol}")
                break
        
        return result
    
    @staticmethod
    def validate_decimals(decimals: Union[int, str], level: ValidationLevel = ValidationLevel.STANDARD) -> ValidationResult:
        """Valide le nombre de décimales d'un token"""
        result = ValidationResult()
        
        try:
            decimals_num = int(decimals)
        except (ValueError, TypeError):
            result.add_error(f"Décimales doit être un entier, reçu: {decimals}", "decimals")
            return result
        
        if decimals_num < 0:
            result.add_error(f"Décimales ne peut pas être négatif: {decimals_num}", "decimals")
            return result
        
        if decimals_num > 18:
            result.add_error(f"Décimales trop élevé: {decimals_num} (max: 18)", "decimals")
            return result
        
        # Warnings pour valeurs inhabituelles
        if decimals_num == 0:
            result.add_warning("Token sans décimales (NFT ou token entier)")
        elif decimals_num > 12:
            result.add_warning(f"Décimales très élevé: {decimals_num} (inhabituel)")
        
        return result
    
    @staticmethod
    def validate_token_amount(amount: Union[float, str, int], decimals: int = 9, 
                            allow_zero: bool = True) -> ValidationResult:
        """Valide un montant de token"""
        result = ValidationResult()
        
        # Valider d'abord les décimales
        decimals_validation = TokenValidator.validate_decimals(decimals)
        if not decimals_validation.is_valid:
            result.merge(decimals_validation)
            return result
        
        try:
            if isinstance(amount, str):
                amount_decimal = Decimal(amount)
            else:
                amount_decimal = Decimal(str(amount))
        except (ValueError, InvalidOperation):
            result.add_error(f"Montant de token invalide: {amount}", "token_amount")
            return result
        
        if not allow_zero and amount_decimal == 0:
            result.add_error("Montant de token ne peut pas être zéro", "token_amount")
            return result
        
        if amount_decimal < 0:
            result.add_error(f"Montant de token ne peut pas être négatif: {amount_decimal}", "token_amount")
            return result
        
        # Validation de la précision selon les décimales
        try:
            max_precision = Decimal('0.1') ** decimals
            if amount_decimal != amount_decimal.quantize(max_precision):
                result.add_warning(f"Précision excessive pour {decimals} décimales")
        except:
            pass  # Ignorer les erreurs de quantification
        
        # Warning pour montants très élevés (potentiel overflow)
        if amount_decimal > Decimal('1e15'):
            result.add_warning(f"Montant de token très élevé: {amount_decimal}")
        
        return result
    
    @staticmethod
    def validate_price_usd(price: Union[float, str], allow_zero: bool = False) -> ValidationResult:
        """Valide un prix en USD"""
        result = ValidationResult()
        
        try:
            price_decimal = Decimal(str(price))
        except (ValueError, InvalidOperation):
            result.add_error(f"Prix USD invalide: {price}", "price_usd")
            return result
        
        if not allow_zero and price_decimal == 0:
            result.add_error("Prix ne peut pas être zéro", "price_usd")
            return result
        
        if price_decimal < 0:
            result.add_error(f"Prix ne peut pas être négatif: {price_decimal}", "price_usd")
            return result
        
        # Warnings pour prix suspects
        if price_decimal > 1_000_000:
            result.add_warning(f"Prix très élevé: ${price_decimal:,.2f}")
        elif price_decimal < 0.000001:
            result.add_warning(f"Prix très bas: ${price_decimal:.10f}")
        
        return result

# ========================
# VALIDATEURS TRANSACTIONS
# ========================

class TransactionValidator:
    """Validateur spécialisé pour les données de transactions"""
    
    VALID_TRANSACTION_TYPES = [
        'buy', 'sell', 'transfer', 'transfer_in', 'transfer_out',
        'swap', 'stake', 'unstake', 'liquidity_add', 'liquidity_remove', 'other'
    ]
    
    VALID_STATUSES = ['success', 'failed', 'pending', 'timeout', 'cancelled']
    
    @staticmethod
    def validate_transaction_type(tx_type: str) -> ValidationResult:
        """Valide un type de transaction"""
        result = ValidationResult()
        
        if not tx_type:
            result.add_error("Type de transaction requis", "transaction_type")
            return result
        
        if not isinstance(tx_type, str):
            result.add_error(f"Type de transaction doit être une chaîne, reçu: {type(tx_type).__name__}", "transaction_type")
            return result
        
        tx_type = tx_type.lower().strip()
        
        if tx_type not in TransactionValidator.VALID_TRANSACTION_TYPES:
            result.add_error(f"Type de transaction invalide: {tx_type}. "
                           f"Valides: {', '.join(TransactionValidator.VALID_TRANSACTION_TYPES)}", 
                           "transaction_type")
        
        return result
    
    @staticmethod
    def validate_transaction_status(status: str) -> ValidationResult:
        """Valide un statut de transaction"""
        result = ValidationResult()
        
        if not status:
            result.add_error("Statut de transaction requis", "status")
            return result
        
        status = status.lower().strip()
        
        if status not in TransactionValidator.VALID_STATUSES:
            result.add_error(f"Statut de transaction invalide: {status}. "
                           f"Valides: {', '.join(TransactionValidator.VALID_STATUSES)}", 
                           "status")
        
        return result
    
    @staticmethod
    def validate_block_time(block_time: Union[int, str, None], allow_none: bool = True) -> ValidationResult:
        """Valide un timestamp de bloc"""
        result = ValidationResult()
        
        if block_time is None:
            if not allow_none:
                result.add_error("Block time requis", "block_time")
            return result
        
        try:
            block_time_int = int(block_time)
        except (ValueError, TypeError):
            result.add_error(f"Block time doit être un timestamp Unix, reçu: {block_time}", "block_time")
            return result
        
        if block_time_int < 0:
            result.add_error(f"Block time ne peut pas être négatif: {block_time_int}", "block_time")
            return result
        
        # Validation de plausibilité
        current_time = int(time.time())
        solana_genesis = 1584355200  # ~16 Mars 2020
        
        if block_time_int < solana_genesis:
            result.add_error(f"Block time antérieur au genesis Solana: {block_time_int}", "block_time")
            return result
        
        if block_time_int > current_time + 3600:  # +1h de tolérance
            result.add_warning(f"Block time dans le futur: {block_time_int}")
        
        return result
    
    @staticmethod
    def validate_transaction_consistency(tx_data: Dict[str, Any]) -> ValidationResult:
        """Valide la cohérence d'une transaction complète"""
        result = ValidationResult()
        
        # Vérifications de cohérence métier
        tx_type = tx_data.get('transaction_type', '').lower()
        token_amount = tx_data.get('token_amount', 0)
        sol_amount = tx_data.get('amount', 0)
        
        # Cohérence buy/sell
        if tx_type == 'buy':
            if token_amount <= 0:
                result.add_warning("Transaction BUY sans montant de token positif")
            if sol_amount >= 0:
                result.add_warning("Transaction BUY sans dépense SOL (montant SOL devrait être négatif)")
        
        elif tx_type == 'sell':
            if token_amount <= 0:
                result.add_warning("Transaction SELL sans montant de token positif")
            if sol_amount <= 0:
                result.add_warning("Transaction SELL sans gain SOL (montant SOL devrait être positif)")
        
        # Cohérence prix
        price_per_token = tx_data.get('price_per_token', 0)
        if price_per_token > 0 and token_amount > 0 and abs(sol_amount) > 0:
            expected_value = price_per_token * token_amount
            actual_value = abs(sol_amount)
            
            if abs(expected_value - actual_value) / max(expected_value, actual_value) > 0.1:  # 10% tolerance
                result.add_warning(f"Incohérence prix: calculé={expected_value:.6f}, réel={actual_value:.6f}")
        
        return result

# ========================
# VALIDATEURS SYSTÈME
# ========================

class SystemValidator:
    """Validateur pour les données système et configuration"""
    
    @staticmethod
    def validate_cycle_id(cycle_id: str) -> ValidationResult:
        """Valide un identifiant de cycle"""
        result = ValidationResult()
        
        if not cycle_id:
            result.add_error("Cycle ID requis", "cycle_id")
            return result
        
        if not isinstance(cycle_id, str):
            result.add_error(f"Cycle ID doit être une chaîne, reçu: {type(cycle_id).__name__}", "cycle_id")
            return result
        
        if not re.match(VALIDATION_PATTERNS['cycle_id'], cycle_id):
            result.add_error(f"Format de cycle ID invalide: {cycle_id}", "cycle_id")
        
        return result
    
    @staticmethod
    def validate_priority_score(score: Union[float, int, str]) -> ValidationResult:
        """Valide un score de priorité"""
        result = ValidationResult()
        
        try:
            score_float = float(score)
        except (ValueError, TypeError):
            result.add_error(f"Score de priorité doit être un nombre, reçu: {score}", "priority_score")
            return result
        
        if not (0.1 <= score_float <= 10.0):
            result.add_error(f"Score de priorité doit être entre 0.1 et 10.0, reçu: {score_float}", "priority_score")
            return result
        
        # Warnings pour valeurs inhabituelles
        if score_float < 0.5:
            result.add_warning("Score de priorité très bas, risque d'être ignoré")
        elif score_float > 8.0:
            result.add_warning("Score de priorité très élevé, risque de sur-scanning")
        
        return result
    
    @staticmethod
    def validate_url(url: str, require_https: bool = False) -> ValidationResult:
        """Valide une URL"""
        result = ValidationResult()
        
        if not url:
            result.add_error("URL requise", "url")
            return result
        
        try:
            parsed = urlparse(url)
        except Exception as e:
            result.add_error(f"URL mal formée: {str(e)}", "url")
            return result
        
        if not parsed.scheme:
            result.add_error("Schéma URL manquant (http/https)", "url")
            return result
        
        if not parsed.netloc:
            result.add_error("Domaine URL manquant", "url")
            return result
        
        if require_https and parsed.scheme != 'https':
            result.add_error("HTTPS requis pour cette URL", "url")
            return result
        
        if parsed.scheme not in ['http', 'https']:
            result.add_error(f"Schéma URL non supporté: {parsed.scheme}", "url")
        
        return result
    
    @staticmethod
    def validate_json_structure(data: str, expected_keys: List[str] = None) -> ValidationResult:
        """Valide une structure JSON"""
        result = ValidationResult()
        
        if not data:
            result.add_error("Données JSON requises", "json_data")
            return result
        
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as e:
            result.add_error(f"JSON invalide: {str(e)}", "json_data")
            return result
        
        if expected_keys:
            for key in expected_keys:
                if key not in parsed:
                    result.add_error(f"Clé manquante dans JSON: {key}", "json_data")
        
        return result

# ========================
# VALIDATEURS COMPOSÉS
# ========================

class CompositeValidator:
    """Validateur composé pour validation complète d'objets"""
    
    @staticmethod
    def validate_wallet_data(wallet_data: Dict[str, Any], 
                           level: ValidationLevel = ValidationLevel.STANDARD) -> ValidationResult:
        """Validation complète des données d'un wallet"""
        result = ValidationResult()
        
        # Validation de l'adresse
        address = wallet_data.get('wallet_address')
        if address:
            addr_result = SolanaValidator.validate_address(address, level)
            result.merge(addr_result)
        else:
            result.add_error("Adresse wallet manquante", "wallet_address")
        
        # Validation du score de priorité
        priority = wallet_data.get('priority_score')
        if priority is not None:
            priority_result = SystemValidator.validate_priority_score(priority)
            result.merge(priority_result)
        
        # Validation des limites de sécurité
        if level == ValidationLevel.STRICT:
            token_count = wallet_data.get('token_accounts_count', 0)
            if token_count > SECURITY_LIMITS['max_tokens_per_wallet']:
                result.add_warning(f"Nombre élevé de tokens: {token_count}")
        
        return result
    
    @staticmethod
    def validate_token_data(token_data: Dict[str, Any],
                          level: ValidationLevel = ValidationLevel.STANDARD) -> ValidationResult:
        """Validation complète des données d'un token"""
        result = ValidationResult()
        
        # Validation du mint
        mint = token_data.get('token_mint') or token_data.get('address')
        if mint:
            mint_result = SolanaValidator.validate_address(mint, level)
            result.merge(mint_result)
        else:
            result.add_error("Adresse mint manquante", "token_mint")
        
        # Validation du symbole
        symbol = token_data.get('symbol')
        if symbol:
            symbol_result = TokenValidator.validate_symbol(symbol, level)
            result.merge(symbol_result)
        
        # Validation des décimales
        decimals = token_data.get('decimals')
        if decimals is not None:
            decimals_result = TokenValidator.validate_decimals(decimals, level)
            result.merge(decimals_result)
        
        # Validation du prix
        price = token_data.get('price_usd')
        if price is not None:
            price_result = TokenValidator.validate_price_usd(price, allow_zero=True)
            result.merge(price_result)
        
        return result
    
    @staticmethod
    def validate_transaction_data(tx_data: Dict[str, Any],
                                level: ValidationLevel = ValidationLevel.STANDARD) -> ValidationResult:
        """Validation complète des données d'une transaction"""
        result = ValidationResult()
        
        # Validation signature
        signature = tx_data.get('signature')
        if signature:
            sig_result = SolanaValidator.validate_signature(signature, level)
            result.merge(sig_result)
        else:
            result.add_error("Signature de transaction manquante", "signature")
        
        # Validation wallet
        wallet = tx_data.get('wallet_address')
        if wallet:
            wallet_result = SolanaValidator.validate_address(wallet, level)
            result.merge(wallet_result)
        else:
            result.add_error("Adresse wallet manquante", "wallet_address")
        
        # Validation token mint (si transaction token)
        token_mint = tx_data.get('token_mint')
        is_token_tx = tx_data.get('is_token_transaction', False)
        if is_token_tx and token_mint:
            mint_result = SolanaValidator.validate_address(token_mint, level)
            result.merge(mint_result)
        elif is_token_tx and not token_mint:
            result.add_error("Token mint manquant pour transaction token", "token_mint")
        
        # Validation type de transaction
        tx_type = tx_data.get('transaction_type')
        if tx_type:
            type_result = TransactionValidator.validate_transaction_type(tx_type)
            result.merge(type_result)
        
        # Validation statut
        status = tx_data.get('status')
        if status:
            status_result = TransactionValidator.validate_transaction_status(status)
            result.merge(status_result)
        
        # Validation block_time
        block_time = tx_data.get('block_time')
        if block_time is not None:
            time_result = TransactionValidator.validate_block_time(block_time)
            result.merge(time_result)
        
        # Validation slot
        slot = tx_data.get('slot')
        if slot is not None:
            slot_result = SolanaValidator.validate_slot(slot, level)
            result.merge(slot_result)
        
        # Validation montants
        sol_amount = tx_data.get('amount')
        if sol_amount is not None:
            sol_result = SolanaValidator.validate_sol_amount(sol_amount, allow_zero=True)
            result.merge(sol_result)
        
        token_amount = tx_data.get('token_amount')
        if token_amount is not None and is_token_tx:
            decimals = tx_data.get('decimals', 9)
            token_result = TokenValidator.validate_token_amount(token_amount, decimals, allow_zero=True)
            result.merge(token_result)
        
        # Validation prix
        price = tx_data.get('price_per_token')
        if price is not None:
            price_result = TokenValidator.validate_price_usd(price, allow_zero=True)
            result.merge(price_result)
        
        # Validation de cohérence métier
        if level in [ValidationLevel.STANDARD, ValidationLevel.STRICT]:
            consistency_result = TransactionValidator.validate_transaction_consistency(tx_data)
            result.merge(consistency_result)
        
        return result

# ========================
# VALIDATEURS DE SÉCURITÉ
# ========================

class SecurityValidator:
    """Validateur pour les aspects de sécurité"""
    
    # Liste noire de mints connus comme malveillants
    BLACKLISTED_MINTS = [
        "HoneyBadgerz...",  # Exemples de mints problématiques
        "ScamToken123...",
        "FakeSolana456..."
    ]
    
    # Patterns suspects dans les noms/symboles
    SUSPICIOUS_PATTERNS = [
        r'.*scam.*', r'.*fake.*', r'.*phish.*', r'.*honey.*pot.*',
        r'.*rug.*pull.*', r'.*ponzi.*', r'.*pyramid.*'
    ]
    
    @staticmethod
    def validate_token_security(token_data: Dict[str, Any]) -> ValidationResult:
        """Valide la sécurité d'un token"""
        result = ValidationResult()
        
        mint = token_data.get('token_mint') or token_data.get('address', '')
        symbol = token_data.get('symbol', '').lower()
        name = token_data.get('name', '').lower()
        
        # Vérification blacklist
        if mint in SecurityValidator.BLACKLISTED_MINTS:
            result.add_error(f"Token en liste noire détecté: {mint}", "security")
            return result
        
        # Vérification patterns suspects
        for pattern in SecurityValidator.SUSPICIOUS_PATTERNS:
            if re.search(pattern, symbol, re.IGNORECASE) or re.search(pattern, name, re.IGNORECASE):
                result.add_warning(f"Pattern suspect détecté dans le token: {symbol}")
                break
        
        # Vérification métadonnées manquantes (signe de token non-légitime)
        if not symbol or symbol == 'unknown':
            result.add_warning("Symbole de token manquant ou générique")
        
        if not name or name == 'unknown token':
            result.add_warning("Nom de token manquant ou générique")
        
        # Vérification prix suspicieux
        price = token_data.get('price_usd', 0)
        if price > 0:
            if price > 1_000_000:
                result.add_warning(f"Prix extrêmement élevé: ${price:,.2f}")
            elif price < 0.000000001:
                result.add_warning(f"Prix extrêmement bas: ${price:.12f}")
        
        # Vérification market cap suspicieuse
        market_cap = token_data.get('market_cap', 0)
        if market_cap > 0:
            if market_cap > 1e12:  # >1T$
                result.add_warning(f"Market cap suspicieusement élevée: ${market_cap:,.0f}")
            elif market_cap < 1000 and price > 0:
                result.add_warning("Market cap très faible pour un token avec prix")
        
        return result
    
    @staticmethod
    def validate_transaction_security(tx_data: Dict[str, Any]) -> ValidationResult:
        """Valide la sécurité d'une transaction"""
        result = ValidationResult()
        
        # Vérification montants suspects
        sol_amount = abs(tx_data.get('amount', 0))
        token_amount = tx_data.get('token_amount', 0)
        
        # Transaction SOL suspecte (>10000 SOL)
        if sol_amount > 10000:
            result.add_warning(f"Transaction SOL très importante: {sol_amount:,.2f} SOL")
        
        # Vérification ratio prix/montant (détection potentiels honeypots)
        price = tx_data.get('price_per_token', 0)
        if price > 0 and token_amount > 0:
            total_value = price * token_amount
            if total_value > 100000:  # >100k$
                result.add_warning(f"Transaction de valeur très élevée: ${total_value:,.2f}")
        
        # Détection patterns temporels suspects
        block_time = tx_data.get('block_time', 0)
        current_time = int(time.time())
        if block_time > 0:
            time_diff = current_time - block_time
            if time_diff < 60:  # Transaction très récente
                result.add_warning("Transaction très récente, vérifier authenticité")
        
        return result
    
    @staticmethod
    def validate_rate_limiting(request_count: int, time_window: int = 60) -> ValidationResult:
        """Valide le respect des limites de taux"""
        result = ValidationResult()
        
        max_requests = SECURITY_LIMITS.get('max_rpc_requests_per_minute', 300)
        
        if request_count > max_requests:
            result.add_error(f"Limite de taux dépassée: {request_count}/{max_requests} requêtes en {time_window}s", 
                           "rate_limit")
        elif request_count > max_requests * 0.8:
            result.add_warning(f"Proche de la limite de taux: {request_count}/{max_requests}")
        
        return result

# ========================
# VALIDATEURS BATCH
# ========================

class BatchValidator:
    """Validateur pour les opérations batch"""
    
    @staticmethod
    def validate_wallet_list(wallets: List[str], level: ValidationLevel = ValidationLevel.STANDARD) -> ValidationResult:
        """Valide une liste de wallets"""
        result = ValidationResult()
        
        if not wallets:
            result.add_error("Liste de wallets vide", "wallets")
            return result
        
        if len(wallets) > SECURITY_LIMITS['max_wallets_per_instance']:
            result.add_error(f"Trop de wallets: {len(wallets)} (max: {SECURITY_LIMITS['max_wallets_per_instance']})", 
                           "wallets")
        
        seen_addresses = set()
        for i, wallet in enumerate(wallets):
            # Validation individuelle
            wallet_result = SolanaValidator.validate_address(wallet, level)
            if not wallet_result.is_valid:
                for error in wallet_result.errors:
                    result.add_error(f"Wallet #{i+1}: {error}", f"wallets[{i}]")
            
            # Vérification doublons
            if wallet in seen_addresses:
                result.add_warning(f"Wallet dupliqué: {wallet}", f"wallets[{i}]")
            else:
                seen_addresses.add(wallet)
        
        return result
    
    @staticmethod
    def validate_batch_size(size: int, method: str = "generic") -> ValidationResult:
        """Valide la taille d'un batch"""
        result = ValidationResult()
        
        if size <= 0:
            result.add_error(f"Taille de batch invalide: {size}", "batch_size")
            return result
        
        # Limites par méthode
        method_limits = {
            'getMultipleAccounts': 100,
            'getSignaturesForAddress': 1000,
            'getTransaction': 10,
            'generic': 50
        }
        
        max_size = method_limits.get(method, method_limits['generic'])
        
        if size > max_size:
            result.add_error(f"Taille de batch trop importante pour {method}: {size} (max: {max_size})", 
                           "batch_size")
        elif size > max_size * 0.8:
            result.add_warning(f"Taille de batch élevée pour {method}: {size}")
        
        return result

# ========================
# UTILITAIRES ET API PUBLIQUE
# ========================

def quick_validate_address(address: str) -> bool:
    """Validation rapide d'adresse (bool seulement)"""
    if not address or len(address) != 44:
        return False
    return bool(re.match(SOLANA_ADDRESS_PATTERN, address))

def quick_validate_signature(signature: str) -> bool:
    """Validation rapide de signature (bool seulement)"""
    if not signature or len(signature) != 88:
        return False
    return bool(re.match(SOLANA_SIGNATURE_PATTERN, signature))

def validate_and_sanitize_string(value: str, max_length: int = 255, 
                                allow_empty: bool = False) -> Tuple[bool, str]:
    """Valide et nettoie une chaîne de caractères"""
    if not value:
        return allow_empty, ""
    
    if not isinstance(value, str):
        return False, ""
    
    # Nettoyage basique
    sanitized = value.strip()
    
    # Suppression caractères de contrôle
    sanitized = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', sanitized)
    
    # Vérification longueur
    if len(sanitized) > max_length:
        return False, sanitized[:max_length]
    
    return True, sanitized

def create_validation_summary(results: List[ValidationResult]) -> Dict[str, Any]:
    """Crée un résumé de plusieurs résultats de validation"""
    total_errors = sum(len(r.errors) for r in results)
    total_warnings = sum(len(r.warnings) for r in results)
    all_valid = all(r.is_valid for r in results)
    
    all_errors = []
    all_warnings = []
    all_field_errors = {}
    
    for result in results:
        all_errors.extend(result.errors)
        all_warnings.extend(result.warnings)
        for field, errors in result.field_errors.items():
            if field not in all_field_errors:
                all_field_errors[field] = []
            all_field_errors[field].extend(errors)
    
    return {
        'is_valid': all_valid,
        'total_validations': len(results),
        'total_errors': total_errors,
        'total_warnings': total_warnings,
        'errors': all_errors,
        'warnings': all_warnings,
        'field_errors': all_field_errors,
        'summary': f"{len(results)} validations: {total_errors} erreurs, {total_warnings} warnings"
    }

# Classe principale pour l'API
class DataValidator:
    """Classe principale pour toutes les validations"""
    
    def __init__(self, level: ValidationLevel = ValidationLevel.STANDARD):
        self.level = level
        self.solana = SolanaValidator()
        self.token = TokenValidator()
        self.transaction = TransactionValidator()
        self.system = SystemValidator()
        self.security = SecurityValidator()
        self.batch = BatchValidator()
        self.composite = CompositeValidator()
    
    def set_level(self, level: ValidationLevel):
        """Change le niveau de validation"""
        self.level = level
    
    def validate_wallet(self, wallet_data: Dict[str, Any]) -> ValidationResult:
        """Point d'entrée principal pour validation wallet"""
        return self.composite.validate_wallet_data(wallet_data, self.level)
    
    def validate_token(self, token_data: Dict[str, Any]) -> ValidationResult:
        """Point d'entrée principal pour validation token"""
        result = self.composite.validate_token_data(token_data, self.level)
        
        # Ajout validation sécurité
        security_result = self.security.validate_token_security(token_data)
        result.merge(security_result)
        
        return result
    
    def validate_transaction(self, tx_data: Dict[str, Any]) -> ValidationResult:
        """Point d'entrée principal pour validation transaction"""
        result = self.composite.validate_transaction_data(tx_data, self.level)
        
        # Ajout validation sécurité
        security_result = self.security.validate_transaction_security(tx_data)
        result.merge(security_result)
        
        return result

# Instance globale par défaut
default_validator = DataValidator()

# Exports principaux
__all__ = [
    'ValidationLevel', 'ValidationError', 'ValidationResult',
    'SolanaValidator', 'TokenValidator', 'TransactionValidator', 
    'SystemValidator', 'SecurityValidator', 'BatchValidator',
    'CompositeValidator', 'DataValidator',
    'quick_validate_address', 'quick_validate_signature',
    'validate_and_sanitize_string', 'create_validation_summary',
    'default_validator'
]

# Point d'entrée pour tests
if __name__ == "__main__":
    # Tests basiques
    print("🧪 Test du système de validation...")
    
    # Test validation adresse
    valid_addr = "4DdrfGHGdMjCqVbNtXsEEGL1SryTeMo8KMGWWtZyZVFh"
    invalid_addr = "invalid_address"
    
    addr_result = SolanaValidator.validate_address(valid_addr)
    print(f"✅ Adresse valide: {addr_result.is_valid}")
    
    addr_result2 = SolanaValidator.validate_address(invalid_addr)
    print(f"❌ Adresse invalide: {addr_result2.is_valid} - {addr_result2.errors}")
    
    # Test validation token
    token_data = {
        'token_mint': valid_addr,
        'symbol': 'TEST',
        'decimals': 9,
        'price_usd': 1.50
    }
    
    token_result = default_validator.validate_token(token_data)
    print(f"🪙 Token validation: {token_result.is_valid}")
    if token_result.warnings:
        print(f"⚠️ Warnings: {token_result.warnings}")
    
    # Test validation transaction
    tx_data = {
        'signature': 'A' * 88,  # Signature factice mais bon format
        'wallet_address': valid_addr,
        'transaction_type': 'buy',
        'token_amount': 1000,
        'amount': -1.5,  # Dépense SOL
        'status': 'success'
    }
    
    tx_result = default_validator.validate_transaction(tx_data)
    print(f"💰 Transaction validation: {tx_result.is_valid}")
    
    print("✅ Tests terminés")