# Documentation - Système de Configuration Solana v2.0

## Vue d'ensemble
**Fichier**: `core/config.py`  
**Type**: Système de configuration centralisé hiérarchique  
**Objectif**: Configuration multi-environnements avec validation, migration et extensibilité pour le Solana Wallet Monitor v2.0

## Architecture générale

### Système hiérarchique
- **Enums** pour types et constantes
- **Dataclasses** pour sections de configuration
- **Classe principale** SolanaWalletConfig orchestrant tout
- **Fonctions utilitaires** pour chargement/validation/migration
- **Instance globale** thread-safe avec singleton pattern

### Fallbacks et imports
- Imports avec fallbacks gracieux si modules indisponibles
- Fonctions de validation par défaut si utils non disponibles
- Endpoints RPC par défaut intégrés

## Enums et constantes

### `Environment(Enum)`
- `DEVELOPMENT`: Développement local
- `PRODUCTION`: Production optimisée
- `TESTING`: Tests automatisés
- `STAGING`: Pré-production

### `WalletSelectionMode(Enum)`
- `PRIORITY`: Sélection par score de priorité
- `RANDOM`: Sélection aléatoire
- `ROUND_ROBIN`: Rotation cyclique
- `WEIGHTED_RANDOM`: Aléatoire pondéré par priorité

### `LogLevel(Enum)`
- `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

## Dataclasses de configuration

### `WalletConfig`
**Objectif**: Configuration des wallets surveillés
```python
{
    'addresses': List[str],                    # Adresses wallets
    'primary_address': str,                    # Wallet principal
    'selection_mode': WalletSelectionMode,     # Mode de sélection
    'random_selection_weight_by_priority': bool,
    'min_interval_between_scans': int,         # Secondes minimum entre scans
    'random_selection_cooldown': int,          # Cooldown sélection aléatoire
    'max_wallets_per_instance': int            # Limite système
}
```

**Post-init validation**:
- Validation Solana de toutes les adresses
- Auto-définition primary_address si non spécifiée
- Vérification cohérence primary_address

### `RPCConfig`
**Objectif**: Configuration endpoints RPC
```python
{
    'quicknode_endpoint': str,                 # Endpoint premium
    'quicknode_api_key': str,                  # Clé API premium
    'fallback_endpoints': List[str],           # Endpoints de secours
    'timeout': int,                            # Timeout requêtes
    'connection_timeout': int,                 # Timeout connexion
    'max_retries': int,                        # Tentatives maximum
    'retry_delay': int,                        # Délai entre tentatives
    'requests_per_minute': int,                # Limite de taux
    'error_backoff_multiplier': float          # Multiplicateur backoff
}
```

**Méthodes**:
- `get_all_endpoints()`: Endpoints par ordre de priorité (premium first)
- `get_headers()`: Headers HTTP avec auth si disponible

### `BatchingConfig`
**Objectif**: Configuration système de batching RPC
```python
{
    'enabled': bool,                           # Système activé
    'adaptive_sizing': bool,                   # Adaptation automatique tailles
    'min_delay_between_batches': float,        # Délai minimum (secondes)
    'max_concurrent_batches': int,             # Batches simultanés max
    'batch_timeout': int,                      # Timeout par batch
    'batch_sizes': {                           # Tailles par méthode RPC
        'getMultipleAccounts': 8,
        'token_metadata': 5,
        'signatures_batch': 12,
        'transactions_batch': 6
    },
    'track_response_times': bool,              # Monitoring performances
    'max_acceptable_response_time': int,       # Seuil acceptable (ms)
    'reduce_batch_size_threshold': int,        # Seuil réduction taille (ms)
    'emergency_fallback_threshold': int        # Seuil fallback urgence (ms)
}
```

### `MonitoringConfig`
**Objectif**: Configuration scanning et monitoring
```python
{
    'update_interval': int,                    # Intervalle mise à jour (s)
    'full_scan_interval_hours': int,           # Scan complet périodique
    'rate_limit_delay': float,                 # Délai rate limiting
    'token_discovery_batch_size': int,         # Taille batch découverte
    'pause_between_tx_details': float,         # Délai entre détails TX
    'max_consecutive_errors': int,             # Erreurs max avant fallback
    'large_transaction_threshold': float,      # Seuil transaction importante
    'default_transaction_limit': int,          # Limite par défaut TX
    'max_transaction_limit': int               # Limite maximum TX
}
```

### `DatabaseConfig`
**Objectif**: Configuration base de données
```python
{
    'name': str,                               # Nom fichier DB
    'path': str,                               # Répertoire DB
    'timeout': float,                          # Timeout opérations
    'max_connections': int,                    # Connexions max pool
    'backup_enabled': bool,                    # Backups automatiques
    'backup_interval_hours': int,              # Fréquence backup
    'cleanup_old_data_days': int               # Rétention données
}
```

**Méthodes**:
- `get_full_path()`: Chemin complet fichier DB

### `LoggingConfig`
**Objectif**: Configuration système de logs
```python
{
    'level': LogLevel,                         # Niveau de log
    'file_path': str,                          # Fichier de log
    'console_output': bool,                    # Sortie console
    'json_output': bool,                       # Format JSON
    'max_file_size_mb': int,                   # Taille max fichier
    'backup_count': int,                       # Nombre de backups
    'max_age_days': int,                       # Âge max logs
    'rate_limit_enabled': bool,                # Rate limiting logs
    'rate_limit_max_per_minute': int           # Max logs/minute
}
```

### `FlaskConfig`
**Objectif**: Configuration serveur API Flask
```python
{
    'host': str,                               # Host d'écoute
    'port': int,                               # Port d'écoute
    'debug': bool,                             # Mode debug
    'cors_enabled': bool,                      # CORS activé
    'cors_origins': List[str],                 # Origins CORS autorisées
    'api_rate_limit_enabled': bool,            # Rate limiting API
    'api_rate_limit_per_minute': int,          # Requêtes/minute
    'api_rate_limit_per_hour': int             # Requêtes/heure
}
```

### `AlertingConfig`
**Objectif**: Configuration système d'alertes
```python
{
    'enabled': bool,                           # Système activé
    'slack_webhook_url': str,                  # Webhook Slack
    'email_enabled': bool,                     # Alertes email
    'email_smtp_server': str,                  # Serveur SMTP
    'email_smtp_port': int,                    # Port SMTP
    'email_username': str,                     # Username email
    'email_password': str,                     # Password email
    'email_recipients': List[str],             # Destinataires
    'alert_thresholds': {                      # Seuils d'alerte
        'large_transaction_sol': 10.0,
        'large_transaction_tokens': 100000,
        'high_activity_tx_per_hour': 50,
        'error_rate_critical': 25,
        'response_time_critical': 30000
    }
}
```

## Classe principale SolanaWalletConfig

### Initialisation
**Constructeur**: `__init__(environment: Union[Environment, str])`
- Détermine l'environnement cible
- Charge toutes les sous-configurations via variables d'environnement
- Applique les overrides spécifiques à l'environnement
- Effectue la validation finale

### Chargement des configurations

#### `_get_wallet_addresses() -> List[str]`
**Logique avancée**:
1. **Mode test**: Variable `TEST_MODE=true` + `TEST_WALLET`
2. **Parsing CSV**: `WALLET_ADDRESSES` séparées par virgules
3. **Validation**: Filtrage adresses invalides avec avertissements
4. **Fallback**: Wallet par défaut si aucune adresse valide
5. **Logging**: Affichage détaillé des wallets chargés

#### Autres méthodes de chargement
- `_load_rpc_config()`: Endpoints et authentification
- `_load_batching_config()`: Tailles personnalisées par variables d'env
- `_load_monitoring_config()`: Intervalles et seuils
- `_load_database_config()`: Chemin et paramètres DB
- `_load_logging_config()`: Niveaux et rotation
- `_load_flask_config()`: Parsing CORS origins
- `_load_alerting_config()`: Parsing recipients et seuils

### Overrides par environnement

#### `_apply_development_overrides()`
- Flask debug = true
- Log level = DEBUG, console = true
- Rate limit plus lent (0.3s)
- Scans plus fréquents (2h)
- Backup désactivé
- Batches réduits de moitié

#### `_apply_production_overrides()`
- Flask debug = false, host = 0.0.0.0
- Log level = INFO, console = false, JSON = true
- Intervalles optimisés (60s)
- Limites TX augmentées (25/200)
- Backup activé
- Alertes activées

#### `_apply_testing_overrides()`
- Debug = false
- Log level = WARNING, console = false
- DB et logs de test
- Intervalles courts (10s)
- Fail fast (1 erreur max)
- Batching désactivé

#### `_apply_staging_overrides()`
- Paramètres production-like
- DB et logs staging
- Alertes activées

### Validation globale

#### `_validate_configuration()`
**Vérifications critiques**:
- Wallets: Au moins une adresse
- RPC: Au moins un endpoint, timeout positif
- Monitoring: Intervalles cohérents, seuils valides
- Batching: Tailles positives si activé
- Flask: Port valide (1024-65535)
- DB: Répertoire créable
- Logging: Répertoire créable
- Alerting: Canaux configurés si activé

**Gestion des erreurs**:
- Erreurs critiques → `ConfigurationError`
- Warnings stockés dans `_warnings`

### Méthodes utilitaires

#### `_get_bool_env(key: str, default: bool) -> bool`
**Parsing booléen robuste**: `true`, `1`, `yes`, `on`, `enabled`

#### `to_dict() -> Dict[str, Any]`
**Export structure complète** pour API/JSON

#### `save_to_file(file_path: str)`
**Sauvegarde JSON** avec masquage informations sensibles

#### `get_summary() -> str`
**Résumé formaté** pour affichage console/logs

## Fonctions d'initialisation et utilitaires

### `load_config_from_file(file_path: str) -> Dict[str, Any]`
**Chargement JSON** avec gestion d'erreurs gracieuse

### `load_config_from_env_file(env_file_path: str = ".env")`
**Parser .env avancé**:
- Ignore commentaires et lignes vides
- Parse `KEY=VALUE` avec guillemets optionnels
- Ne surcharge pas variables d'environnement existantes
- Gestion d'erreurs par ligne

### `get_environment_from_args_or_env() -> Environment`
**Détection environnement intelligente**:
1. Arguments ligne de commande (`--env=dev`, `--prod`, etc.)
2. Variable d'environnement `ENVIRONMENT`
3. Fallback vers `DEVELOPMENT`

### `create_config(...) -> SolanaWalletConfig`
**Factory function complète**:
- Chargement .env optionnel
- Auto-détection environnement
- Application overrides depuis fichier JSON
- Instance configurée prête à l'emploi

### `apply_config_overrides(config, overrides: Dict)`
**Application overrides** par section avec gestion d'erreurs

## Validation avancée - ConfigValidator

### `ConfigValidator(config: SolanaWalletConfig)`
**Validateur complet** avec règles métier avancées

#### Méthodes de validation spécialisées

**`_validate_wallet_config()`**:
- Warning si >100 wallets
- Erreur si >1000 wallets
- Détection doublons
- Cohérence mode sélection

**`_validate_rpc_config()`**:
- Warning si un seul endpoint
- Validation URLs (http/https)
- Seuils timeout et rate limiting

**`_validate_batching_config()`**:
- Analyse tailles de batch par méthode
- Cohérence délais et timeouts
- Recommandations optimisation

**`_validate_monitoring_config()`**:
- Seuils intervalles (minimum 5s)
- Cohérence limites transactions
- Validation seuils d'alerte

**`_validate_database_config()`**:
- Vérification espace disque approximative
- Paramètres backup cohérents
- Politique rétention données

**`_validate_logging_config()`**:
- Test permissions écriture
- Paramètres rotation logs
- Tailles et backup counts

**`_validate_flask_config()`**:
- Sécurité production (debug off)
- Exposition réseau avec CORS
- Rate limiting activé

**`_validate_alerting_config()`**:
- Validation webhook Slack
- Configuration email complète
- Seuils critiques cohérents

**`_validate_cross_dependencies()`**:
- Cohérence batching/monitoring
- Impact nombre wallets/intervalles
- Logs debug en production

**`_generate_recommendations()`**:
- Recommandations par environnement
- Optimisations performance
- Conseils sécurité et maintenance

### Résultats de validation
```python
{
    'errors': List[str],           # Erreurs critiques bloquantes
    'warnings': List[str],         # Avertissements non-bloquants
    'recommendations': List[str]   # Conseils d'optimisation
}
```

## Migration et compatibilité

### `migrate_from_legacy_config(legacy_config_dict) -> SolanaWalletConfig`
**Migration automatique** ancienne version:
- Mapping variables d'environnement
- Traitement spécial `WALLET_ADDRESS` → `WALLET_ADDRESSES`
- Préservation settings existants

### `export_to_env_file(config, file_path=".env.generated")`
**Export .env structuré**:
- Headers et sections commentées
- Valeurs actuelles de configuration
- Masquage informations sensibles
- Format standard .env

## Instance globale et thread safety

### Singleton pattern thread-safe
```python
_global_config: Optional[SolanaWalletConfig] = None
_config_lock = threading.Lock()
```

### `get_config() -> SolanaWalletConfig`
**Lazy initialization** avec double-checked locking:
- Création instance unique à la première demande
- Thread-safe avec lock
- Réutilisation instances suivantes

### `set_global_config(config)` et `reload_config()`
**Gestion instance globale** pour tests et reconfigurations

## Compatibilité legacy - Classe Config

### `Config()`
**Wrapper compatibilité** avec ancienne interface:
- Properties mappées vers nouvelle structure
- Méthodes legacy préservées
- Transparence pour code existant

### Instances compatibilité
- `DefaultConfig`: Instance par défaut
- `DevelopmentConfig`: Alias pour compatibilité
- `ProductionConfig`: Alias pour compatibilité

## Initialisation automatique

### `init_config()`
**Bootstrap complet système**:
1. Chargement .env automatique
2. Création instance globale
3. Affichage résumé configuration
4. Validation avec rapport détaillé
5. Gestion erreurs avec conseils

### Import-time initialization
- Initialisation automatique à l'import (sauf `__main__`)
- Gestion d'erreurs non-bloquante
- Warning si échec initialisation

## Mode développement et test

### `if __name__ == "__main__"`
**Suite de tests intégrée**:
- Test création configuration
- Validation complète avec rapports
- Export JSON et .env
- Démonstration fonctionnalités

## Variables d'environnement supportées

### Wallets
- `TEST_MODE`: Mode test avec wallet unique
- `TEST_WALLET`: Wallet de test
- `WALLET_ADDRESSES`: Liste CSV des wallets
- `WALLET_SELECTION_MODE`: Mode de sélection
- `MIN_INTERVAL_BETWEEN_SCANS`: Intervalle minimum

### RPC
- `QUICKNODE_ENDPOINT`: Endpoint premium
- `QUICKNODE_API_KEY`: Clé API premium
- `RPC_TIMEOUT`: Timeout requêtes
- `MAX_RETRIES`: Tentatives maximum
- `RETRY_DELAY`: Délai entre tentatives
- `REQUESTS_PER_MINUTE`: Limite taux

### Batching
- `ENABLE_RPC_BATCHING`: Activation système
- `BATCH_ADAPTIVE_SIZING`: Sizing adaptatif
- `MIN_DELAY_BETWEEN_BATCHES`: Délai minimum
- `BATCH_SIZE_*`: Tailles par méthode (ex: `BATCH_SIZE_GETMULTIPLEACCOUNTS`)

### Monitoring
- `UPDATE_INTERVAL`: Intervalle principal
- `FULL_SCAN_INTERVAL_HOURS`: Scan complet
- `RATE_LIMIT_DELAY`: Délai rate limiting
- `TOKEN_DISCOVERY_BATCH_SIZE`: Taille batch découverte
- `MAX_CONSECUTIVE_ERRORS`: Erreurs max
- `ALERT_THRESHOLD`: Seuil transaction importante

### Database
- `DB_NAME`: Nom fichier DB
- `DB_PATH`: Répertoire DB
- `DB_TIMEOUT`: Timeout opérations

### Logging
- `LOG_LEVEL`: Niveau de log
- `LOG_FILE`: Fichier de log
- `LOG_CONSOLE_OUTPUT`: Sortie console
- `LOG_JSON_OUTPUT`: Format JSON

### Flask
- `FLASK_HOST`: Host écoute
- `FLASK_PORT`: Port écoute
- `FLASK_DEBUG`: Mode debug
- `FLASK_CORS_ENABLED`: CORS activé
- `FLASK_CORS_ORIGINS`: Origins autorisées

### Alerting
- `ALERTING_ENABLED`: Système activé
- `SLACK_WEBHOOK_URL`: Webhook Slack
- `ALERT_EMAIL_ENABLED`: Alertes email
- `ALERT_EMAIL_SMTP_SERVER`: Serveur SMTP
- `ALERT_EMAIL_RECIPIENTS`: Destinataires CSV
- `ALERT_*`: Seuils personnalisés

Cette documentation couvre l'intégralité du système de configuration modulaire, hiérarchique et extensible, avec toutes ses fonctionnalités de validation, migration, et compatibilité.