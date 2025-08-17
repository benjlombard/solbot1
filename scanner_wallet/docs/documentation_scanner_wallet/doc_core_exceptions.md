# Documentation - Système d'Exceptions Solana

## Vue d'ensemble
**Fichier**: `core/exceptions.py`  
**Type**: Système d'exceptions centralisé avec hiérarchie métier  
**Objectif**: Gestion d'erreurs spécialisée pour tous les domaines du Solana Wallet Monitor avec contexte riche et récupération intelligente

## Architecture générale

### Hiérarchie d'exceptions
- **Classe de base**: `SolanaWalletMonitorError` avec sérialisation complète
- **7 domaines métier**: RPC, Batching, Database, Wallet, Token, Transaction, System
- **Exceptions spécialisées**: 25+ types avec contexte spécifique
- **Context managers**: Gestion automatique d'erreurs par domaine
- **Factory functions**: Création intelligente selon conditions

### Enrichissement automatique
- **Timestamp** automatique à la création
- **Error codes** générés depuis classe si non spécifiés
- **Détails contextuels** structurés par domaine
- **Sérialisation JSON** pour logs et API

## Classe de base - SolanaWalletMonitorError

### Structure complète
```python
class SolanaWalletMonitorError(Exception):
    def __init__(self, message: str, error_code: str = None, details: Dict[str, Any] = None):
        self.message = message                              # Message human-readable
        self.error_code = error_code or CLASS_NAME.upper()  # Code unique
        self.details = details or {}                        # Contexte structuré
        self.timestamp = int(time.time())                   # Timestamp création
```

### Méthodes utilitaires
- `__str__()`: Format `[ERROR_CODE] Message`
- `to_dict()`: Sérialisation complète pour API/logs

**Structure sérialisée**:
```python
{
    'error_code': str,           # Code unique d'erreur
    'message': str,              # Message principal
    'details': dict,             # Contexte spécifique
    'timestamp': int,            # Unix timestamp
    'exception_type': str        # Nom de la classe
}
```

## Domaine RPC - Communication réseau

### `RPCError` (classe parent)
Exception générique pour toutes erreurs RPC Solana

### `RPCTimeoutError(RPCError)`
**Objectif**: Timeout lors d'appel RPC
```python
RPCTimeoutError(
    endpoint: str,           # URL endpoint RPC
    timeout_duration: float, # Durée timeout en secondes
    method: str = None       # Méthode RPC appelée
)
```

**Détails contextuels**: endpoint, timeout_duration, method

### `RPCRateLimitError(RPCError)`
**Objectif**: Rate limit atteint sur endpoint
```python
RPCRateLimitError(
    endpoint: str,            # URL endpoint
    retry_after: int = None,  # Délai avant retry (secondes)
    current_rps: float = None # RPS actuel
)
```

**Message dynamique**: Inclut suggestion retry si `retry_after` fourni

### `RPCEndpointUnavailableError(RPCError)`
**Objectif**: Tous endpoints RPC ont échoué
```python
RPCEndpointUnavailableError(
    failed_endpoints: list,  # Liste URLs qui ont échoué
    last_error: str = None   # Dernière erreur rencontrée
)
```

**Usage**: Échec total système RPC avec détail des tentatives

### `RPCResponseError(RPCError)`
**Objectif**: Réponse RPC invalide ou erreur serveur
```python
RPCResponseError(
    method: str,             # Méthode RPC
    error_message: str,      # Message d'erreur RPC
    error_code: int = None   # Code d'erreur RPC
)
```

**Contexte**: Préserve codes d'erreur RPC natifs

## Domaine Batching - Optimisation RPC

### `BatchingError` (classe parent)
Exception générique système de batching

### `BatchSizeError(BatchingError)`
**Objectif**: Taille de batch invalide
```python
BatchSizeError(
    method: str,           # Méthode RPC concernée
    requested_size: int,   # Taille demandée
    max_allowed: int       # Taille maximum autorisée
)
```

**Validation**: Contrôle des limites par méthode RPC

### `BatchExecutionError(BatchingError)`
**Objectif**: Échec exécution d'un batch
```python
BatchExecutionError(
    method: str,                # Méthode RPC
    batch_size: int,           # Taille du batch
    partial_results: int = 0,  # Résultats partiels obtenus
    original_error: str = None # Erreur sous-jacente
)
```

**Message adaptatif**: Inclut résultats partiels si disponibles

### `BatchAdaptiveError(BatchingError)`
**Objectif**: Erreur système adaptatif de batching
```python
BatchAdaptiveError(
    reason: str,                           # Raison de l'erreur
    current_stats: Dict[str, Any] = None   # Stats système actuelles
)
```

**Usage**: Problèmes d'adaptation automatique des tailles

## Domaine Database - Persistance

### `DatabaseError` (classe parent)
Exception générique base de données

### `DatabaseConnectionError(DatabaseError)`
**Objectif**: Connexion impossible à la DB
```python
DatabaseConnectionError(
    db_path: str,              # Chemin fichier DB
    retry_count: int = 0,      # Nombre tentatives
    original_error: str = None # Erreur sous-jacente
)
```

**Message adaptatif**: Inclut tentatives si retry_count > 0

### `DatabaseLockError(DatabaseError)`
**Objectif**: Base de données verrouillée
```python
DatabaseLockError(
    db_path: str,      # Chemin fichier DB
    wait_time: float = 0 # Temps d'attente
)
```

**Usage**: SQLite database locked

### `DatabaseSchemaError(DatabaseError)`
**Objectif**: Erreur de schéma de base de données
```python
DatabaseSchemaError(
    table_name: str,        # Table concernée
    operation: str,         # Opération tentée
    error_details: str = None # Détails erreur
)
```

**Cas typiques**: Table/colonne inexistante, DDL incorrect

### `DatabaseIntegrityError(DatabaseError)`
**Objectif**: Violation contrainte d'intégrité
```python
DatabaseIntegrityError(
    constraint: str,              # Contrainte violée
    table_name: str = None,       # Table concernée
    data: Dict[str, Any] = None   # Données qui ont causé l'erreur
)
```

**Usage**: UNIQUE, FOREIGN KEY, CHECK constraints

## Domaine Wallet - Gestion portefeuilles

### `WalletError` (classe parent)
Exception générique wallets

### `WalletNotFoundError(WalletError)`
**Objectif**: Wallet non trouvé dans système
```python
WalletNotFoundError(
    wallet_address: str,   # Adresse wallet (tronquée dans message)
    context: str = None    # Contexte de la recherche
)
```

**Formatage**: Adresse tronquée à 8 chars pour lisibilité

### `WalletValidationError(WalletError)`
**Objectif**: Adresse wallet invalide
```python
WalletValidationError(
    wallet_address: str,      # Adresse invalide
    validation_issue: str     # Problème spécifique
)
```

**Usage**: Format Solana incorrect, checksum invalide

### `PrioritySystemError(WalletError)`
**Objectif**: Erreur système de priorités dynamiques
```python
PrioritySystemError(
    operation: str,               # Opération tentée
    wallet_address: str = None,   # Wallet concerné
    details_info: str = None      # Détails supplémentaires
)
```

**Opérations typiques**: update_priority, calculate_score, select_wallet

## Domaine Token - Gestion des tokens

### `TokenError` (classe parent)
Exception générique tokens

### `TokenAccountError(TokenError)`
**Objectif**: Erreur compte de token (ATA)
```python
TokenAccountError(
    ata_pubkey: str,         # Adresse compte token
    token_mint: str = None,  # Adresse mint token
    operation: str = None    # Opération tentée
)
```

**Message enrichi**: Inclut mint et opération si fournis

### `TokenMetadataError(TokenError)`
**Objectif**: Métadonnées token introuvables
```python
TokenMetadataError(
    mint_address: str,       # Adresse mint
    provider: str = None,    # Fournisseur métadonnées
    retry_count: int = 0     # Nombre tentatives
)
```

**Providers typiques**: Jupiter, CoinGecko, on-chain

### `TokenDiscoveryError(TokenError)`
**Objectif**: Échec découverte nouveaux tokens
```python
TokenDiscoveryError(
    wallet_address: str,        # Wallet scanné
    scan_type: str,            # Type de scan
    accounts_processed: int = 0 # Comptes traités avant échec
)
```

**Scan types**: full_scan, balance_change, priority_scan

## Domaine Transaction - Analyse transactions

### `TransactionError` (classe parent)
Exception générique transactions

### `TransactionAnalysisError(TransactionError)`
**Objectif**: Échec analyse d'une transaction
```python
TransactionAnalysisError(
    signature: str,           # Signature transaction (tronquée)
    analysis_step: str,       # Étape qui a échoué
    error_details: str = None # Détails erreur
)
```

**Steps typiques**: parse_instructions, extract_tokens, calculate_balances

### `BalanceChangeError(TransactionError)`
**Objectif**: Erreur scan balance changes
```python
BalanceChangeError(
    wallet_address: str,        # Wallet scanné
    accounts_scanned: int,      # Comptes scannés avant erreur
    error_context: str = None   # Contexte erreur
)
```

**Usage**: Scan pré/post transaction pour détecter changements

### `TransactionValidationError(TransactionError)`
**Objectif**: Transaction invalide ou corrompue
```python
TransactionValidationError(
    signature: str,                # Signature transaction
    validation_issue: str,         # Problème de validation
    tx_data: Dict[str, Any] = None # Données transaction
)
```

**Issues typiques**: signature_invalid, incomplete_data, corrupted_instructions

## Domaine System - Configuration et monitoring

### `ConfigurationError(SolanaWalletMonitorError)`
**Objectif**: Erreur de configuration
```python
ConfigurationError(
    config_key: str,        # Clé configuration problématique
    issue: str,             # Description problème
    current_value: Any = None # Valeur actuelle
)
```

**Usage**: Validation configuration au démarrage

### `MonitoringError(SolanaWalletMonitorError)`
**Objectif**: Erreur boucle principale monitoring
```python
MonitoringError(
    cycle_id: str,             # ID cycle monitoring
    step: str,                 # Étape qui a échoué
    error_details: str = None  # Détails erreur
)
```

**Steps typiques**: wallet_selection, token_discovery, priority_update

### `CriticalSystemError(SolanaWalletMonitorError)`
**Objectif**: Erreur critique nécessitant arrêt
```python
CriticalSystemError(
    reason: str,                           # Raison critique
    recovery_suggestion: str = None,       # Suggestion récupération
    system_state: Dict[str, Any] = None    # État système
)
```

**Message enrichi**: Inclut suggestion de récupération si disponible

## Domaine API - Communication externe

### `APIError` (classe parent)
Exception générique API

### `APIValidationError(APIError)`
**Objectif**: Validation paramètres API
```python
APIValidationError(
    endpoint: str,             # Endpoint concerné
    parameter: str,            # Paramètre invalide
    issue: str,                # Problème spécifique
    received_value: Any = None # Valeur reçue
)
```

**Usage**: Validation Flask routes

### `APIRateLimitError(APIError)`
**Objectif**: Rate limit API atteint
```python
APIRateLimitError(
    endpoint: str,      # Endpoint concerné
    current_rate: float, # Taux actuel
    limit: float        # Limite autorisée
)
```

**Message**: Format numérique avec comparaison explicite

## Domaine Performance - Cache et métriques

### `CacheError(SolanaWalletMonitorError)`
**Objectif**: Erreur système de cache
```python
CacheError(
    cache_type: str,    # Type cache (redis, memory, file)
    operation: str,     # Opération (get, set, delete)
    key: str = None     # Clé concernée
)
```

### `PerformanceError(SolanaWalletMonitorError)`
**Objectif**: Seuil performance dépassé
```python
PerformanceError(
    metric: str,           # Métrique concernée
    current_value: float,  # Valeur actuelle
    threshold: float,      # Seuil configuré
    context: str = None    # Contexte mesure
)
```

**Métriques typiques**: response_time, rps, success_rate, memory_usage

## Factory functions - Création intelligente

### `create_rpc_error(endpoint, method, status_code, response_text) -> RPCError`
**Objectif**: Création exception RPC selon code HTTP

**Logique de mapping**:
- `429` → `RPCRateLimitError`
- `>= 500` → `RPCEndpointUnavailableError`
- `408` → `RPCTimeoutError`
- Autres → `RPCResponseError`

**Extraction automatique**: Retry-After header depuis response_text

### `handle_database_error(original_error, context) -> DatabaseError`
**Objectif**: Conversion erreurs SQLite en exceptions custom

**Logique de détection** (analyse message d'erreur):
- `"database is locked"` → `DatabaseLockError`
- `"no such table/column"` → `DatabaseSchemaError`
- `"constraint failed"` → `DatabaseIntegrityError`
- Autres → `DatabaseError` générique

## Utilitaires de récupération

### `is_recoverable_error(exception) -> bool`
**Objectif**: Détermine si erreur est récupérable ou critique

**Erreurs récupérables**:
- `RPCTimeoutError`, `RPCRateLimitError`
- `DatabaseLockError`, `TokenMetadataError`
- `CacheError`

**Erreurs critiques**:
- `CriticalSystemError`, `DatabaseConnectionError`
- `RPCEndpointUnavailableError`, `ConfigurationError`

**Logique par défaut**: Récupérable sauf code commençant par "CRITICAL"

## Context managers - Gestion automatique

### `@contextmanager handle_rpc_errors(endpoint, method)`
**Objectif**: Conversion automatique erreurs requests en exceptions RPC

**Mappings automatiques**:
```python
try:
    yield
except requests.exceptions.Timeout:
    raise RPCTimeoutError(endpoint, 15.0, method)
except requests.exceptions.ConnectionError:
    raise RPCEndpointUnavailableError([endpoint], str(e))
except requests.exceptions.HTTPError:
    raise create_rpc_error(endpoint, method, status_code, response_text)
```

**Usage**:
```python
with handle_rpc_errors(endpoint, "getMultipleAccounts"):
    response = requests.post(endpoint, json=payload)
```

### `@contextmanager handle_database_errors(operation, table_name)`
**Objectif**: Conversion automatique erreurs SQLite

**Usage**:
```python
with handle_database_errors("INSERT", "transactions"):
    cursor.execute("INSERT INTO transactions ...")
```

**Conversion**: Utilise `handle_database_error()` factory

## Patterns d'utilisation recommandés

### Création avec contexte riche
```python
# Exception avec détails complets
raise TokenMetadataError(
    mint_address=mint,
    provider="Jupiter",
    retry_count=3
)

# Factory pour cas complexes
rpc_error = create_rpc_error(endpoint, method, 429, response.text)
```

### Context managers pour domaines
```python
# RPC automatique
with handle_rpc_errors(endpoint, "getTokenAccounts"):
    data = make_rpc_call()

# Database automatique  
with handle_database_errors("UPDATE", "wallet_priorities"):
    update_priority(wallet, score)
```

### Récupération intelligente
```python
try:
    risky_operation()
except SolanaWalletMonitorError as e:
    if is_recoverable_error(e):
        logger.warning(f"Erreur récupérable: {e}")
        retry_with_backoff()
    else:
        logger.critical(f"Erreur critique: {e}")
        shutdown_system()
```

### Sérialisation pour logs/API
```python
try:
    operation()
except SolanaWalletMonitorError as e:
    error_dict = e.to_dict()
    logger.error("Exception détaillée", extra={'exception_data': error_dict})
    return jsonify({'error': error_dict}), 500
```

Cette documentation couvre l'intégralité du système d'exceptions avec ses 25+ types spécialisés, ses factory functions, context managers et patterns d'utilisation, permettant une gestion d'erreurs robuste et contextuelle dans tout le système Solana.