
#!/usr/bin/env python3
"""
Schémas de validation pour l'API du Solana Wallet Monitor
"""

from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field
from enum import Enum
import re
import time


# Patterns de validation
SOLANA_ADDRESS_PATTERN = r'^[1-9A-HJ-NP-Za-km-z]{44}$'
SOLANA_SIGNATURE_PATTERN = r'^[1-9A-HJ-NP-Za-km-z]{88}$'
TOKEN_SYMBOL_PATTERN = r'^[A-Z][A-Z0-9_]{0,10}$'


class ValidationError(Exception):
    """Exception pour erreurs de validation"""
    def __init__(self, message: str, field: str = None):
        self.message = message
        self.field = field
        super().__init__(message)


@dataclass
class ValidationResult:
    """Résultat d'une validation"""
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def add_error(self, message: str, field: str = None):
        """Ajoute une erreur"""
        if field:
            message = f"{field}: {message}"
        self.errors.append(message)
        self.is_valid = False
    
    def add_warning(self, message: str, field: str = None):
        """Ajoute un avertissement"""
        if field:
            message = f"{field}: {message}"
        self.warnings.append(message)


# ============= SCHÉMAS DE REQUÊTES API =============

@dataclass
class WalletPriorityUpdateRequest:
    """Schéma pour mise à jour de priorité wallet"""
    wallet_address: str
    priority_score: float
    reason: Optional[str] = None
    
    def validate(self) -> ValidationResult:
        result = ValidationResult(is_valid=True)
        
        # Validation adresse wallet
        if not re.match(SOLANA_ADDRESS_PATTERN, self.wallet_address):
            result.add_error("Invalid Solana wallet address format", "wallet_address")
        
        # Validation score
        if not 0.1 <= self.priority_score <= 10.0:
            result.add_error("Priority score must be between 0.1 and 10.0", "priority_score")
        
        # Validation raison
        if self.reason and len(self.reason) > 255:
            result.add_error("Reason too long (max 255 characters)", "reason")
        
        return result


@dataclass
class BatchingConfigRequest:
    """Schéma pour configuration du batching"""
    enabled: Optional[bool] = None
    batch_sizes: Optional[Dict[str, int]] = None
    min_delay_between_batches: Optional[float] = None
    max_concurrent_batches: Optional[int] = None
    batch_timeout: Optional[int] = None
    adaptive_sizing: Optional[bool] = None
    
    def validate(self) -> ValidationResult:
        result = ValidationResult(is_valid=True)
        
        # Validation batch_sizes
        if self.batch_sizes:
            valid_methods = [
                'getMultipleAccounts', 'token_metadata', 'signatures_batch', 'transactions_batch'
            ]
            for method, size in self.batch_sizes.items():
                if method not in valid_methods:
                    result.add_warning(f"Unknown batch method: {method}", "batch_sizes")
                
                if not 1 <= size <= 100:
                    result.add_error(f"Batch size for {method} must be between 1 and 100", "batch_sizes")
        
        # Validation délai
        if self.min_delay_between_batches is not None:
            if not 0.0 <= self.min_delay_between_batches <= 10.0:
                result.add_error("Min delay must be between 0 and 10 seconds", "min_delay_between_batches")
        
        # Validation concurrence
        if self.max_concurrent_batches is not None:
            if not 1 <= self.max_concurrent_batches <= 10:
                result.add_error("Max concurrent batches must be between 1 and 10", "max_concurrent_batches")
        
        # Validation timeout
        if self.batch_timeout is not None:
            if not 5 <= self.batch_timeout <= 120:
                result.add_error("Batch timeout must be between 5 and 120 seconds", "batch_timeout")
        
        return result


@dataclass
class SelectionModeRequest:
    """Schéma pour changement de mode de sélection"""
    mode: str
    weighted_by_priority: Optional[bool] = None
    min_interval: Optional[int] = None
    
    def validate(self) -> ValidationResult:
        result = ValidationResult(is_valid=True)
        
        # Validation mode
        valid_modes = ['priority', 'random']
        if self.mode not in valid_modes:
            result.add_error(f"Mode must be one of: {', '.join(valid_modes)}", "mode")
        
        # Validation intervalle
        if self.min_interval is not None:
            if not 10 <= self.min_interval <= 3600:
                result.add_error("Min interval must be between 10 and 3600 seconds", "min_interval")
        
        return result


@dataclass
class DatabaseCleanupRequest:
    """Schéma pour nettoyage de base de données"""
    days: int = 30
    tables: Optional[List[str]] = None
    dry_run: bool = False
    confirm: bool = False
    
    def validate(self) -> ValidationResult:
        result = ValidationResult(is_valid=True)
        
        # Validation jours
        if not 1 <= self.days <= 365:
            result.add_error("Days must be between 1 and 365", "days")
        
        # Validation tables
        if self.tables:
            allowed_tables = ['scan_history', 'wallet_activity_metrics', 'system_logs']
            for table in self.tables:
                if table not in allowed_tables:
                    result.add_error(f"Table '{table}' not allowed for cleanup", "tables")
        
        # Validation confirmation pour opérations destructives
        if not self.dry_run and not self.confirm:
            result.add_error("Confirmation required for actual cleanup", "confirm")
        
        return result


@dataclass
class TokenMetadataRequest:
    """Schéma pour requête de métadonnées de token"""
    mint_address: str
    force_refresh: bool = False
    include_price: bool = True
    
    def validate(self) -> ValidationResult:
        result = ValidationResult(is_valid=True)
        
        # Validation mint address
        if not re.match(SOLANA_ADDRESS_PATTERN, self.mint_address):
            result.add_error("Invalid Solana mint address format", "mint_address")
        
        return result


# ============= SCHÉMAS DE RÉPONSES API =============

@dataclass
class ApiResponse:
    """Schéma standard de réponse API"""
    success: bool
    message: str
    data: Optional[Any] = None
    timestamp: int = field(default_factory=lambda: int(time.time()))
    errors: Optional[List[str]] = None
    warnings: Optional[List[str]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour JSON"""
        response = {
            'success': self.success,
            'message': self.message,
            'timestamp': self.timestamp
        }
        
        if self.data is not None:
            response['data'] = self.data
        
        if self.errors:
            response['errors'] = self.errors
        
        if self.warnings:
            response['warnings'] = self.warnings
        
        return response


@dataclass
class PaginatedResponse:
    """Schéma pour réponses paginées"""
    items: List[Any]
    total_count: int
    page: int = 1
    page_size: int = 20
    has_next: bool = False
    has_previous: bool = False
    
    @property
    def total_pages(self) -> int:
        """Nombre total de pages"""
        return (self.total_count + self.page_size - 1) // self.page_size
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour JSON"""
        return {
            'items': self.items,
            'pagination': {
                'total_count': self.total_count,
                'page': self.page,
                'page_size': self.page_size,
                'total_pages': self.total_pages,
                'has_next': self.has_next,
                'has_previous': self.has_previous
            }
        }


@dataclass
class HealthCheckResponse:
    """Schéma pour réponse de health check"""
    status: str  # healthy, degraded, critical
    timestamp: int
    version: str
    uptime_seconds: int
    checks: Dict[str, Any]
    system_stats: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour JSON"""
        response = {
            'status': self.status,
            'timestamp': self.timestamp,
            'version': self.version,
            'uptime_seconds': self.uptime_seconds,
            'checks': self.checks
        }
        
        if self.system_stats:
            response['system_stats'] = self.system_stats
        
        return response


# ============= SCHÉMAS DE FILTRAGE ET RECHERCHE =============

@dataclass
class WalletFilterParams:
    """Paramètres de filtrage pour les wallets"""
    priority_min: Optional[float] = None
    priority_max: Optional[float] = None
    priority_category: Optional[str] = None  # high, medium, low
    has_recent_activity: Optional[bool] = None
    min_balance: Optional[float] = None
    scan_status: Optional[str] = None  # ready, recent, overdue
    
    def validate(self) -> ValidationResult:
        result = ValidationResult(is_valid=True)
        
        # Validation priorité
        if self.priority_min is not None and not 0.1 <= self.priority_min <= 10.0:
            result.add_error("Priority min must be between 0.1 and 10.0", "priority_min")
        
        if self.priority_max is not None and not 0.1 <= self.priority_max <= 10.0:
            result.add_error("Priority max must be between 0.1 and 10.0", "priority_max")
        
        if (self.priority_min is not None and self.priority_max is not None 
            and self.priority_min > self.priority_max):
            result.add_error("Priority min cannot be greater than priority max", "priority_min")
        
        # Validation catégorie
        if self.priority_category and self.priority_category not in ['high', 'medium', 'low']:
            result.add_error("Priority category must be high, medium, or low", "priority_category")
        
        # Validation balance
        if self.min_balance is not None and self.min_balance < 0:
            result.add_error("Min balance cannot be negative", "min_balance")
        
        # Validation statut
        if self.scan_status and self.scan_status not in ['ready', 'recent', 'overdue']:
            result.add_error("Scan status must be ready, recent, or overdue", "scan_status")
        
        return result


@dataclass
class TransactionFilterParams:
    """Paramètres de filtrage pour les transactions"""
    wallet_address: Optional[str] = None
    token_mint: Optional[str] = None
    transaction_type: Optional[str] = None
    min_amount: Optional[float] = None
    max_amount: Optional[float] = None
    start_time: Optional[int] = None
    end_time: Optional[int] = None
    is_large_amount: Optional[bool] = None
    status: Optional[str] = None
    
    def validate(self) -> ValidationResult:
        result = ValidationResult(is_valid=True)
        
        # Validation adresses
        if self.wallet_address and not re.match(SOLANA_ADDRESS_PATTERN, self.wallet_address):
            result.add_error("Invalid wallet address format", "wallet_address")
        
        if self.token_mint and not re.match(SOLANA_ADDRESS_PATTERN, self.token_mint):
            result.add_error("Invalid token mint format", "token_mint")
        
        # Validation type de transaction
        valid_types = ['buy', 'sell', 'transfer', 'transfer_in', 'transfer_out', 'swap', 'stake', 'unstake', 'other']
        if self.transaction_type and self.transaction_type not in valid_types:
            result.add_error(f"Transaction type must be one of: {', '.join(valid_types)}", "transaction_type")
        
        # Validation montants
        if self.min_amount is not None and self.min_amount < 0:
            result.add_error("Min amount cannot be negative", "min_amount")
        
        if (self.min_amount is not None and self.max_amount is not None 
            and self.min_amount > self.max_amount):
            result.add_error("Min amount cannot be greater than max amount", "min_amount")
        
        # Validation timestamps
        if self.start_time is not None and self.start_time < 0:
            result.add_error("Start time cannot be negative", "start_time")
        
        if (self.start_time is not None and self.end_time is not None 
            and self.start_time > self.end_time):
            result.add_error("Start time cannot be after end time", "start_time")
        
        # Validation statut
        valid_statuses = ['success', 'failed', 'pending', 'timeout', 'cancelled']
        if self.status and self.status not in valid_statuses:
            result.add_error(f"Status must be one of: {', '.join(valid_statuses)}", "status")
        
        return result


@dataclass
class PaginationParams:
    """Paramètres de pagination"""
    page: int = 1
    page_size: int = 20
    sort_by: Optional[str] = None
    sort_order: str = 'desc'  # asc, desc
    
    def validate(self) -> ValidationResult:
        result = ValidationResult(is_valid=True)
        
        # Validation page
        if self.page < 1:
            result.add_error("Page must be >= 1", "page")
        
        # Validation taille de page
        if not 1 <= self.page_size <= 1000:
            result.add_error("Page size must be between 1 and 1000", "page_size")
        
        # Validation ordre de tri
        if self.sort_order not in ['asc', 'desc']:
            result.add_error("Sort order must be 'asc' or 'desc'", "sort_order")
        
        return result
    
    @property
    def offset(self) -> int:
        """Calcule l'offset pour la base de données"""
        return (self.page - 1) * self.page_size


# ============= SCHÉMAS DE VALIDATION MÉTIER =============

@dataclass
class WalletValidation:
    """Validation spécialisée pour les wallets"""
    
    @staticmethod
    def validate_address(address: str) -> ValidationResult:
        """Valide une adresse de wallet Solana"""
        result = ValidationResult(is_valid=True)
        
        if not address:
            result.add_error("Wallet address is required")
            return result
        
        if len(address) != 44:
            result.add_error("Wallet address must be 44 characters long")
            return result
        
        if not re.match(SOLANA_ADDRESS_PATTERN, address):
            result.add_error("Invalid wallet address format (Base58)")
            return result
        
        # Validation Base58 avancée si disponible
        try:
            import base58
            decoded = base58.b58decode(address)
            if len(decoded) != 32:
                result.add_error("Invalid wallet address (decoded length)")
        except ImportError:
            # Pas de base58 disponible, on garde la validation regex
            pass
        except Exception:
            result.add_error("Invalid wallet address (Base58 decode failed)")
        
        return result
    
    @staticmethod
    def validate_priority_score(score: float) -> ValidationResult:
        """Valide un score de priorité"""
        result = ValidationResult(is_valid=True)
        
        if not 0.1 <= score <= 10.0:
            result.add_error("Priority score must be between 0.1 and 10.0")
        
        # Avertissements pour valeurs extrêmes
        if score < 0.5:
            result.add_warning("Very low priority score, wallet may be ignored")
        elif score > 8.0:
            result.add_warning("Very high priority score, may cause over-scanning")
        
        return result


@dataclass
class TokenValidation:
    """Validation spécialisée pour les tokens"""
    
    @staticmethod
    def validate_mint_address(mint: str) -> ValidationResult:
        """Valide une adresse de mint token"""
        result = ValidationResult(is_valid=True)
        
        if not mint:
            result.add_error("Token mint address is required")
            return result
        
        if len(mint) != 44:
            result.add_error("Token mint address must be 44 characters long")
            return result
        
        if not re.match(SOLANA_ADDRESS_PATTERN, mint):
            result.add_error("Invalid token mint address format (Base58)")
            return result
        
        return result
    
    @staticmethod
    def validate_token_symbol(symbol: str) -> ValidationResult:
        """Valide un symbole de token"""
        result = ValidationResult(is_valid=True)
        
        if not symbol:
            result.add_error("Token symbol is required")
            return result
        
        if len(symbol) > 10:
            result.add_error("Token symbol too long (max 10 characters)")
        
        if not re.match(TOKEN_SYMBOL_PATTERN, symbol):
            result.add_error("Invalid token symbol format (A-Z, 0-9, _ only)")
        
        return result
    
    @staticmethod
    def validate_decimals(decimals: int) -> ValidationResult:
        """Valide le nombre de décimales d'un token"""
        result = ValidationResult(is_valid=True)
        
        if not 0 <= decimals <= 18:
            result.add_error("Token decimals must be between 0 and 18")
        
        # Avertissement pour valeurs inhabituelles
        if decimals > 12:
            result.add_warning("Unusually high decimal count")
        
        return result


@dataclass
class TransactionValidation:
    """Validation spécialisée pour les transactions"""
    
    @staticmethod
    def validate_signature(signature: str) -> ValidationResult:
        """Valide une signature de transaction"""
        result = ValidationResult(is_valid=True)
        
        if not signature:
            result.add_error("Transaction signature is required")
            return result
        
        if len(signature) != 88:
            result.add_error("Transaction signature must be 88 characters long")
            return result
        
        if not re.match(SOLANA_SIGNATURE_PATTERN, signature):
            result.add_error("Invalid transaction signature format (Base58)")
            return result
        
        return result
    
    @staticmethod
    def validate_amount(amount: float, field_name: str = "amount") -> ValidationResult:
        """Valide un montant de transaction"""
        result = ValidationResult(is_valid=True)
        
        if amount < 0:
            result.add_error(f"{field_name} cannot be negative")
        
        # Avertissement pour montants très élevés
        if amount > 1000000:  # 1M SOL ou tokens
            result.add_warning(f"Very large {field_name}, please verify")
        
        return result


# ============= UTILITAIRES DE VALIDATION =============

def validate_time_range(start_time: Optional[int], end_time: Optional[int], 
                       max_range_hours: int = 168) -> ValidationResult:
    """Valide une plage de temps"""
    result = ValidationResult(is_valid=True)
    
    if start_time is not None and start_time < 0:
        result.add_error("Start time cannot be negative")
    
    if end_time is not None and end_time < 0:
        result.add_error("End time cannot be negative")
    
    if (start_time is not None and end_time is not None):
        if start_time > end_time:
            result.add_error("Start time cannot be after end time")
        
        # Vérifier la plage maximum
        range_hours = (end_time - start_time) / 3600
        if range_hours > max_range_hours:
            result.add_error(f"Time range too large (max {max_range_hours} hours)")
    
    return result


def validate_pagination_with_total(pagination: PaginationParams, 
                                  total_count: int) -> ValidationResult:
    """Valide la pagination avec le nombre total d'éléments"""
    result = pagination.validate()
    
    if result.is_valid and total_count > 0:
        max_page = (total_count + pagination.page_size - 1) // pagination.page_size
        if pagination.page > max_page:
            result.add_error(f"Page {pagination.page} does not exist (max: {max_page})")
    
    return result


def sanitize_string_input(value: str, max_length: int = 255, 
                         allow_empty: bool = False) -> str:
    """Nettoie et valide une entrée string"""
    if not value:
        if allow_empty:
            return ""
        raise ValidationError("Value cannot be empty")
    
    # Nettoyer
    cleaned = value.strip()
    
    # Vérifier la longueur
    if len(cleaned) > max_length:
        raise ValidationError(f"Value too long (max {max_length} characters)")
    
    # Supprimer les caractères de contrôle
    import re
    cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', cleaned)
    
    return cleaned


def create_error_response(message: str, errors: List[str] = None) -> ApiResponse:
    """Crée une réponse d'erreur standardisée"""
    return ApiResponse(
        success=False,
        message=message,
        errors=errors or []
    )


def create_success_response(message: str, data: Any = None, 
                          warnings: List[str] = None) -> ApiResponse:
    """Crée une réponse de succès standardisée"""
    return ApiResponse(
        success=True,
        message=message,
        data=data,
        warnings=warnings
    )