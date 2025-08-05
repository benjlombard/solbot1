
#!/usr/bin/env python3
"""
Exceptions personnalisées pour le Solana Wallet Monitor
Centralise toutes les exceptions métier avec des messages explicites
"""

from typing import Optional, Dict, Any
import time


class SolanaWalletMonitorError(Exception):
    """Classe de base pour toutes les exceptions du Solana Wallet Monitor"""
    
    def __init__(self, message: str, error_code: str = None, details: Dict[str, Any] = None):
        self.message = message
        self.error_code = error_code or self.__class__.__name__.upper()
        self.details = details or {}
        self.timestamp = int(time.time())
        super().__init__(self.message)
    
    def __str__(self):
        return f"[{self.error_code}] {self.message}"
    
    def to_dict(self):
        """Sérialise l'exception pour les logs ou API"""
        return {
            'error_code': self.error_code,
            'message': self.message,
            'details': self.details,
            'timestamp': self.timestamp,
            'exception_type': self.__class__.__name__
        }


# =============================================================================
# EXCEPTIONS RPC ET COMMUNICATION
# =============================================================================

class RPCError(SolanaWalletMonitorError):
    """Erreur générique lors des appels RPC Solana"""
    pass


class RPCTimeoutError(RPCError):
    """Timeout lors d'un appel RPC"""
    
    def __init__(self, endpoint: str, timeout_duration: float, method: str = None):
        message = f"RPC timeout après {timeout_duration}s sur {endpoint[:50]}..."
        details = {
            'endpoint': endpoint,
            'timeout_duration': timeout_duration,
            'method': method
        }
        super().__init__(message, "RPC_TIMEOUT", details)


class RPCRateLimitError(RPCError):
    """Rate limit atteint sur un endpoint RPC"""
    
    def __init__(self, endpoint: str, retry_after: int = None, current_rps: float = None):
        message = f"Rate limit atteint sur {endpoint[:50]}..."
        if retry_after:
            message += f" (retry dans {retry_after}s)"
        
        details = {
            'endpoint': endpoint,
            'retry_after': retry_after,
            'current_rps': current_rps
        }
        super().__init__(message, "RPC_RATE_LIMIT", details)


class RPCEndpointUnavailableError(RPCError):
    """Aucun endpoint RPC disponible"""
    
    def __init__(self, failed_endpoints: list, last_error: str = None):
        message = f"Tous les endpoints RPC ont échoué ({len(failed_endpoints)} tentés)"
        details = {
            'failed_endpoints': failed_endpoints,
            'last_error': last_error
        }
        super().__init__(message, "RPC_ALL_ENDPOINTS_FAILED", details)


class RPCResponseError(RPCError):
    """Réponse RPC invalide ou erreur"""
    
    def __init__(self, method: str, error_message: str, error_code: int = None):
        message = f"Erreur RPC {method}: {error_message}"
        details = {
            'method': method,
            'rpc_error_message': error_message,
            'rpc_error_code': error_code
        }
        super().__init__(message, "RPC_RESPONSE_ERROR", details)


# =============================================================================
# EXCEPTIONS BATCHING
# =============================================================================

class BatchingError(SolanaWalletMonitorError):
    """Erreur générique du système de batching"""
    pass


class BatchSizeError(BatchingError):
    """Taille de batch invalide"""
    
    def __init__(self, method: str, requested_size: int, max_allowed: int):
        message = f"Taille de batch invalide pour {method}: {requested_size} > {max_allowed}"
        details = {
            'method': method,
            'requested_size': requested_size,
            'max_allowed': max_allowed
        }
        super().__init__(message, "BATCH_SIZE_INVALID", details)


class BatchExecutionError(BatchingError):
    """Erreur lors de l'exécution d'un batch"""
    
    def __init__(self, method: str, batch_size: int, partial_results: int = 0, original_error: str = None):
        message = f"Échec d'exécution batch {method} (taille: {batch_size})"
        if partial_results > 0:
            message += f", {partial_results} résultats partiels"
        
        details = {
            'method': method,
            'batch_size': batch_size,
            'partial_results': partial_results,
            'original_error': original_error
        }
        super().__init__(message, "BATCH_EXECUTION_FAILED", details)


class BatchAdaptiveError(BatchingError):
    """Erreur dans le système adaptatif de batching"""
    
    def __init__(self, reason: str, current_stats: Dict[str, Any] = None):
        message = f"Erreur système adaptatif: {reason}"
        details = {'reason': reason, 'current_stats': current_stats or {}}
        super().__init__(message, "BATCH_ADAPTIVE_ERROR", details)


# =============================================================================
# EXCEPTIONS BASE DE DONNÉES
# =============================================================================

class DatabaseError(SolanaWalletMonitorError):
    """Erreur générique de base de données"""
    pass


class DatabaseConnectionError(DatabaseError):
    """Impossible de se connecter à la base de données"""
    
    def __init__(self, db_path: str, retry_count: int = 0, original_error: str = None):
        message = f"Connexion impossible à {db_path}"
        if retry_count > 0:
            message += f" (après {retry_count} tentatives)"
        
        details = {
            'db_path': db_path,
            'retry_count': retry_count,
            'original_error': original_error
        }
        super().__init__(message, "DB_CONNECTION_FAILED", details)


class DatabaseLockError(DatabaseError):
    """Base de données verrouillée"""
    
    def __init__(self, db_path: str, wait_time: float = 0):
        message = f"Base de données verrouillée: {db_path}"
        if wait_time > 0:
            message += f" (attente: {wait_time:.1f}s)"
        
        details = {'db_path': db_path, 'wait_time': wait_time}
        super().__init__(message, "DB_LOCKED", details)


class DatabaseSchemaError(DatabaseError):
    """Erreur de schéma de base de données"""
    
    def __init__(self, table_name: str, operation: str, error_details: str = None):
        message = f"Erreur schéma sur table '{table_name}' lors de '{operation}'"
        details = {
            'table_name': table_name,
            'operation': operation,
            'error_details': error_details
        }
        super().__init__(message, "DB_SCHEMA_ERROR", details)


class DatabaseIntegrityError(DatabaseError):
    """Erreur d'intégrité des données"""
    
    def __init__(self, constraint: str, table_name: str = None, data: Dict[str, Any] = None):
        message = f"Violation contrainte d'intégrité: {constraint}"
        if table_name:
            message += f" sur table '{table_name}'"
        
        details = {
            'constraint': constraint,
            'table_name': table_name,
            'data': data
        }
        super().__init__(message, "DB_INTEGRITY_ERROR", details)


# =============================================================================
# EXCEPTIONS WALLET ET PRIORITÉS
# =============================================================================

class WalletError(SolanaWalletMonitorError):
    """Erreur générique liée aux wallets"""
    pass


class WalletNotFoundError(WalletError):
    """Wallet non trouvé dans le système de priorités"""
    
    def __init__(self, wallet_address: str, context: str = None):
        message = f"Wallet non trouvé: {wallet_address[:8]}..."
        if context:
            message += f" (contexte: {context})"
        
        details = {
            'wallet_address': wallet_address,
            'context': context
        }
        super().__init__(message, "WALLET_NOT_FOUND", details)


class WalletValidationError(WalletError):
    """Adresse de wallet invalide"""
    
    def __init__(self, wallet_address: str, validation_issue: str):
        message = f"Wallet invalide {wallet_address[:8]}...: {validation_issue}"
        details = {
            'wallet_address': wallet_address,
            'validation_issue': validation_issue
        }
        super().__init__(message, "WALLET_INVALID", details)


class PrioritySystemError(WalletError):
    """Erreur dans le système de priorités dynamiques"""
    
    def __init__(self, operation: str, wallet_address: str = None, details_info: str = None):
        message = f"Erreur système priorités lors de '{operation}'"
        if wallet_address:
            message += f" pour {wallet_address[:8]}..."
        
        details = {
            'operation': operation,
            'wallet_address': wallet_address,
            'details_info': details_info
        }
        super().__init__(message, "PRIORITY_SYSTEM_ERROR", details)


# =============================================================================
# EXCEPTIONS TOKEN ET COMPTES
# =============================================================================

class TokenError(SolanaWalletMonitorError):
    """Erreur générique liée aux tokens"""
    pass


class TokenAccountError(TokenError):
    """Erreur liée à un compte de token (ATA)"""
    
    def __init__(self, ata_pubkey: str, token_mint: str = None, operation: str = None):
        message = f"Erreur compte token {ata_pubkey[:8]}..."
        if token_mint:
            message += f" (mint: {token_mint[:8]}...)"
        if operation:
            message += f" lors de '{operation}'"
        
        details = {
            'ata_pubkey': ata_pubkey,
            'token_mint': token_mint,
            'operation': operation
        }
        super().__init__(message, "TOKEN_ACCOUNT_ERROR", details)


class TokenMetadataError(TokenError):
    """Erreur lors de la récupération des métadonnées de token"""
    
    def __init__(self, mint_address: str, provider: str = None, retry_count: int = 0):
        message = f"Métadonnées token introuvables: {mint_address[:8]}..."
        if provider:
            message += f" via {provider}"
        if retry_count > 0:
            message += f" (après {retry_count} tentatives)"
        
        details = {
            'mint_address': mint_address,
            'provider': provider,
            'retry_count': retry_count
        }
        super().__init__(message, "TOKEN_METADATA_ERROR", details)


class TokenDiscoveryError(TokenError):
    """Erreur lors de la découverte de nouveaux tokens"""
    
    def __init__(self, wallet_address: str, scan_type: str, accounts_processed: int = 0):
        message = f"Échec découverte tokens pour {wallet_address[:8]}... (scan: {scan_type})"
        if accounts_processed > 0:
            message += f", {accounts_processed} comptes traités"
        
        details = {
            'wallet_address': wallet_address,
            'scan_type': scan_type,
            'accounts_processed': accounts_processed
        }
        super().__init__(message, "TOKEN_DISCOVERY_ERROR", details)


# =============================================================================
# EXCEPTIONS TRANSACTION ET ANALYSE
# =============================================================================

class TransactionError(SolanaWalletMonitorError):
    """Erreur générique liée aux transactions"""
    pass


class TransactionAnalysisError(TransactionError):
    """Erreur lors de l'analyse d'une transaction"""
    
    def __init__(self, signature: str, analysis_step: str, error_details: str = None):
        message = f"Échec analyse transaction {signature[:16]}... à l'étape '{analysis_step}'"
        details = {
            'signature': signature,
            'analysis_step': analysis_step,
            'error_details': error_details
        }
        super().__init__(message, "TRANSACTION_ANALYSIS_ERROR", details)


class BalanceChangeError(TransactionError):
    """Erreur lors du scan des balance changes"""
    
    def __init__(self, wallet_address: str, accounts_scanned: int, error_context: str = None):
        message = f"Erreur scan balance changes {wallet_address[:8]}..."
        if accounts_scanned > 0:
            message += f" ({accounts_scanned} comptes scannés)"
        
        details = {
            'wallet_address': wallet_address,
            'accounts_scanned': accounts_scanned,
            'error_context': error_context
        }
        super().__init__(message, "BALANCE_CHANGE_ERROR", details)


class TransactionValidationError(TransactionError):
    """Transaction invalide ou corrompue"""
    
    def __init__(self, signature: str, validation_issue: str, tx_data: Dict[str, Any] = None):
        message = f"Transaction invalide {signature[:16]}...: {validation_issue}"
        details = {
            'signature': signature,
            'validation_issue': validation_issue,
            'tx_data': tx_data
        }
        super().__init__(message, "TRANSACTION_INVALID", details)


# =============================================================================
# EXCEPTIONS CONFIGURATION ET SYSTÈME
# =============================================================================

class ConfigurationError(SolanaWalletMonitorError):
    """Erreur de configuration"""
    
    def __init__(self, config_key: str, issue: str, current_value: Any = None):
        message = f"Configuration invalide '{config_key}': {issue}"
        details = {
            'config_key': config_key,
            'issue': issue,
            'current_value': current_value
        }
        super().__init__(message, "CONFIG_ERROR", details)


class MonitoringError(SolanaWalletMonitorError):
    """Erreur dans la boucle principale de monitoring"""
    
    def __init__(self, cycle_id: str, step: str, error_details: str = None):
        message = f"Erreur monitoring cycle {cycle_id} à l'étape '{step}'"
        details = {
            'cycle_id': cycle_id,
            'step': step,
            'error_details': error_details
        }
        super().__init__(message, "MONITORING_ERROR", details)


class CriticalSystemError(SolanaWalletMonitorError):
    """Erreur système critique nécessitant un arrêt"""
    
    def __init__(self, reason: str, recovery_suggestion: str = None, system_state: Dict[str, Any] = None):
        message = f"ERREUR CRITIQUE: {reason}"
        if recovery_suggestion:
            message += f" | Suggestion: {recovery_suggestion}"
        
        details = {
            'reason': reason,
            'recovery_suggestion': recovery_suggestion,
            'system_state': system_state or {}
        }
        super().__init__(message, "CRITICAL_SYSTEM_ERROR", details)


# =============================================================================
# EXCEPTIONS API ET COMMUNICATION
# =============================================================================

class APIError(SolanaWalletMonitorError):
    """Erreur générique API"""
    pass


class APIValidationError(APIError):
    """Erreur de validation des paramètres API"""
    
    def __init__(self, endpoint: str, parameter: str, issue: str, received_value: Any = None):
        message = f"Paramètre invalide '{parameter}' sur {endpoint}: {issue}"
        details = {
            'endpoint': endpoint,
            'parameter': parameter,
            'issue': issue,
            'received_value': received_value
        }
        super().__init__(message, "API_VALIDATION_ERROR", details)


class APIRateLimitError(APIError):
    """Rate limit API atteint"""
    
    def __init__(self, endpoint: str, current_rate: float, limit: float):
        message = f"Rate limit API dépassé sur {endpoint}: {current_rate:.1f} > {limit:.1f}"
        details = {
            'endpoint': endpoint,
            'current_rate': current_rate,
            'limit': limit
        }
        super().__init__(message, "API_RATE_LIMIT", details)


# =============================================================================
# EXCEPTIONS CACHE ET PERFORMANCE
# =============================================================================

class CacheError(SolanaWalletMonitorError):
    """Erreur système de cache"""
    
    def __init__(self, cache_type: str, operation: str, key: str = None):
        message = f"Erreur cache {cache_type} lors de '{operation}'"
        if key:
            message += f" pour clé '{key}'"
        
        details = {
            'cache_type': cache_type,
            'operation': operation,
            'key': key
        }
        super().__init__(message, "CACHE_ERROR", details)


class PerformanceError(SolanaWalletMonitorError):
    """Erreur liée aux performances système"""
    
    def __init__(self, metric: str, current_value: float, threshold: float, context: str = None):
        message = f"Seuil performance dépassé {metric}: {current_value:.2f} > {threshold:.2f}"
        if context:
            message += f" (contexte: {context})"
        
        details = {
            'metric': metric,
            'current_value': current_value,
            'threshold': threshold,
            'context': context
        }
        super().__init__(message, "PERFORMANCE_ERROR", details)


# =============================================================================
# HELPERS ET UTILITAIRES
# =============================================================================

def create_rpc_error(endpoint: str, method: str, status_code: int, response_text: str = None) -> RPCError:
    """Factory pour créer les bonnes exceptions RPC selon le status code"""
    
    if status_code == 429:
        retry_after = None
        # Essayer d'extraire retry-after si présent dans response_text
        return RPCRateLimitError(endpoint, retry_after)
    
    elif status_code >= 500:
        return RPCEndpointUnavailableError([endpoint], f"HTTP {status_code}")
    
    elif status_code == 408:
        return RPCTimeoutError(endpoint, 15.0, method)  # Timeout par défaut
    
    else:
        error_msg = response_text or f"HTTP {status_code}"
        return RPCResponseError(method, error_msg, status_code)


def handle_database_error(original_error: Exception, context: str = None) -> DatabaseError:
    """Factory pour convertir les erreurs SQLite en exceptions custom"""
    
    error_msg = str(original_error).lower()
    
    if "database is locked" in error_msg:
        return DatabaseLockError("unknown", 0)
    
    elif "no such table" in error_msg or "no such column" in error_msg:
        return DatabaseSchemaError("unknown", context or "query", str(original_error))
    
    elif "unique constraint failed" in error_msg or "foreign key constraint failed" in error_msg:
        return DatabaseIntegrityError(str(original_error))
    
    else:
        return DatabaseError(f"Erreur base de données: {original_error}")


def is_recoverable_error(exception: Exception) -> bool:
    """Détermine si une erreur est récupérable ou critique"""
    
    # Erreurs récupérables
    recoverable_types = (
        RPCTimeoutError,
        RPCRateLimitError,
        DatabaseLockError,
        TokenMetadataError,
        CacheError
    )
    
    # Erreurs critiques
    critical_types = (
        CriticalSystemError,
        DatabaseConnectionError,
        RPCEndpointUnavailableError,
        ConfigurationError
    )
    
    if isinstance(exception, critical_types):
        return False
    
    if isinstance(exception, recoverable_types):
        return True
    
    # Par défaut, considérer comme récupérable sauf si explicitement critique
    return not isinstance(exception, SolanaWalletMonitorError) or \
           not exception.error_code.startswith("CRITICAL")


# =============================================================================
# CONTEXT MANAGERS POUR GESTION D'ERREURS
# =============================================================================

from contextlib import contextmanager
from typing import Generator, Type, Union


@contextmanager
def handle_rpc_errors(endpoint: str, method: str) -> Generator[None, None, None]:
    """Context manager pour gérer automatiquement les erreurs RPC"""
    try:
        yield
    except requests.exceptions.Timeout as e:
        raise RPCTimeoutError(endpoint, 15.0, method) from e
    except requests.exceptions.ConnectionError as e:
        raise RPCEndpointUnavailableError([endpoint], str(e)) from e
    except requests.exceptions.HTTPError as e:
        if e.response:
            raise create_rpc_error(endpoint, method, e.response.status_code, e.response.text) from e
        else:
            raise RPCError(f"Erreur HTTP {method} sur {endpoint}: {e}") from e
    except Exception as e:
        raise RPCError(f"Erreur inattendue {method} sur {endpoint}: {e}") from e


@contextmanager
def handle_database_errors(operation: str, table_name: str = None) -> Generator[None, None, None]:
    """Context manager pour gérer automatiquement les erreurs de base de données"""
    try:
        yield
    except Exception as e:
        raise handle_database_error(e, operation) from e
