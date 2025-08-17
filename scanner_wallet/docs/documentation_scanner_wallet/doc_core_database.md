# Documentation - Gestionnaire de Base de Données SQLite Thread-Safe

## Vue d'ensemble
**Fichier**: `core/database.py`  
**Type**: Gestionnaire de base de données centralisé avec pool de connexions  
**Objectif**: Gestion thread-safe, optimisée et résiliente de la base de données SQLite pour le Solana Wallet Monitor

## Architecture générale

### Système à 3 couches
- **Configuration**: `DatabaseConfig` centralise tous les paramètres SQLite
- **Pool de connexions**: `ConnectionPool` gère les connexions thread-safe avec retry automatique
- **Gestionnaire principal**: `DatabaseManager` singleton orchestrant toutes les opérations

### Composants avancés
- **Maintenance automatique**: Thread dédié pour backups, nettoyage et optimisations
- **Migration de schéma**: `DatabaseMigration` pour évolutions de structure
- **Métriques détaillées**: `DatabaseMetrics` pour monitoring de performance
- **Transactions sécurisées**: Context managers pour atomicité

## Classe DatabaseConfig

### Objectif
Configuration centralisée pour tous les paramètres de base de données

### Initialisation
```python
def __init__(self, config=None):
    if config is None:
        config = get_config()
```

### Attributs principaux
- `db_path`: Chemin complet fichier SQLite (via `config.database.get_full_path()`)
- `timeout`: Timeout opérations SQLite
- `max_connections`: Taille maximum du pool de connexions (défaut: 10)
- `backup_enabled`: Activation backups automatiques
- `backup_interval_hours`: Fréquence des backups
- `cleanup_old_data_days`: Rétention des données anciennes
- `sqlite_settings`: Paramètres SQLite optimisés depuis constantes
- `query_limits`: Limites de requêtes depuis constantes
- `db_dir`: Répertoire parent créé automatiquement si inexistant

## Classe ConnectionPool

### Objectif
Pool de connexions SQLite thread-safe avec gestion intelligente des ressources

### Architecture interne
- **Queue thread-safe**: `queue.Queue` pour stockage connexions
- **Statistiques**: Compteurs thread-safe pour monitoring
- **Lock réentrant**: `threading.RLock` pour synchronisation
- **Pré-création**: 3 connexions créées au démarrage
- **Validation**: Test de validité des connexions avant utilisation

### Paramètres de construction
```python
def __init__(self, db_path: str, max_connections: int = 10, timeout: float = 30.0)
```

### Statistiques trackées
```python
_connection_stats = {
    'total_created': 0,        # Connexions créées depuis démarrage
    'active_connections': 0,    # Connexions actives actuellement
    'total_queries': 0,        # Requêtes totales exécutées
    'failed_connections': 0    # Échecs de création connexion
}
```

### Méthode `_create_connection()`
**Fonctionnalités**:
- Connexion SQLite avec `check_same_thread=False` et `isolation_level=None` (autocommit)
- Application automatique optimisations SQLite via `_optimize_connection()`
- Mise à jour thread-safe des statistiques
- Conversion erreurs SQLite en exceptions custom `DatabaseConnectionError`

### Optimisations SQLite appliquées
```python
optimizations = [
    f"PRAGMA journal_mode={SQLITE_SETTINGS['journal_mode']}",      # WAL mode
    f"PRAGMA synchronous={SQLITE_SETTINGS['synchronous']}",        # NORMAL sync
    f"PRAGMA busy_timeout={SQLITE_SETTINGS['busy_timeout']}",      # 30s timeout
    f"PRAGMA cache_size={SQLITE_SETTINGS['cache_size']}",          # Cache optimisé
    f"PRAGMA page_size={SQLITE_SETTINGS['page_size']}",            # Taille page
    "PRAGMA temp_store=MEMORY",                                     # Temp en mémoire
    "PRAGMA mmap_size=268435456",                                   # 256MB mmap
    "PRAGMA optimize"                                               # Optimisations auto
]
```

### Context Manager `get_connection()`
**Logique de récupération avec retry**:
1. Essai récupération connexion du pool (timeout 5s)
2. Si pool vide: création nouvelle connexion si sous limite
3. Si limite atteinte: exception `DatabaseConnectionError`
4. Validation connexion via `SELECT 1`
5. Si invalide: fermeture et création nouvelle connexion
6. Retry avec backoff exponentiel (3 tentatives max)

**Gestion d'exceptions spécialisée**:
- `sqlite3.OperationalError` "database is locked" → `DatabaseLockError`
- `sqlite3.IntegrityError` → `DatabaseIntegrityError`
- Autres erreurs SQLite → `DatabaseError` générique

**Nettoyage automatique**: Rollback et remise en pool (ou fermeture si pool plein)

## Classe DatabaseManager

### Pattern Singleton Thread-Safe
```python
_instance = None
_lock = threading.Lock()

def __new__(cls, config=None):
    # Double-checked locking pattern
```

### Initialisation complète
**Séquence de démarrage**:
1. Évitement réinitialisation multiple via `_initialized`
2. Création `DatabaseConfig` et logger
3. Initialisation `ConnectionPool`
4. Setup statistiques monitoring
5. Initialisation schéma base de données
6. Démarrage thread maintenance automatique

### Statistiques système
```python
self.stats = {
    'start_time': time.time(),      # Timestamp démarrage
    'total_operations': 0,          # Opérations DB totales
    'failed_operations': 0,         # Opérations échouées
    'last_backup': 0,              # Timestamp dernier backup
    'last_cleanup': 0,             # Timestamp dernier nettoyage
    'schema_version': 1            # Version schéma actuelle
}
```

### Thread de maintenance
- **Thread daemon**: Ne bloque pas arrêt application
- **Nom**: "DatabaseMaintenance" pour debugging
- **Fréquence**: Vérifications toutes les heures
- **Arrêt propre**: Via `maintenance_stop_event`

### Initialisation schéma `_initialize_database()`
**Séquence complète**:
1. Création toutes tables via `_create_tables()`
2. Création index optimisés via `_create_indexes()`
3. Vérification/mise à jour version schéma via `_check_schema_version()`
4. Logging succès ou propagation erreur `DatabaseError`

### Tables créées

#### Table `transactions` (table principale)
**Colonnes métier**:
- `signature`: Signature unique transaction Solana
- `wallet_address`: Wallet concerné
- `slot`, `block_time`: Informations blockchain
- `amount`, `token_amount`: Montants SOL et token
- `token_mint`, `token_symbol`, `token_name`: Métadonnées token
- `transaction_type`: Type (buy/sell/transfer/etc.)
- `price_per_token`, `fee`: Prix et frais
- `status`: Statut transaction (success/failed)
- `is_token_transaction`, `is_large_token_amount`: Flags classification
- `detection_delay`: Temps détection depuis blockchain
- `wallet_priority_at_detection`: Priorité wallet au moment détection
- `scan_cycle_id`: ID cycle de scan ayant détecté
- `created_at`, `updated_at`: Timestamps gestion

#### Table `tokens` (métadonnées tokens)
**Colonnes métadonnées**:
- `address`: Mint address (clé primaire)
- `symbol`, `name`: Symbole et nom
- `decimals`: Nombre décimales (défaut: 9)
- `price_usd`: Prix USD
- `logo_uri`: URL logo
- `coingecko_id`: ID CoinGecko si disponible
- `is_verified`: Token vérifié
- `market_cap`, `volume_24h`, `price_change_24h`: Métriques marché
- `last_price_update`: Timestamp dernière MAJ prix
- `metadata_source`: Source métadonnées

#### Table `token_accounts` (comptes ATA)
**Clé primaire composite**: `(wallet_address, ata_pubkey)`
**Colonnes gestion**:
- `token_mint`: Mint du token
- `balance`: Balance actuelle
- `decimals`: Décimales token
- `first_seen`, `last_updated`, `last_scanned`: Timestamps lifecycle
- `is_active`: Compte actif
- `scan_priority`: Priorité scan (1-5)
- `activity_score`: Score activité calculé
- `last_activity_time`: Dernière activité détectée
- `total_transactions`: Nombre transactions du compte

#### Table `wallet_priorities` (système priorités dynamiques)
**Colonnes scoring**:
- `wallet_address`: Clé primaire
- `priority_score`: Score priorité (0.1-10.0)
- `last_scan_time`: Timestamp dernier scan
- `scan_count_1h`, `scan_count_24h`: Compteurs périodiques
- `activity_score`: Score activité récente
- `volume_score_1h`: Score volume dernière heure
- `new_tokens_score_1h`: Nouveaux tokens détectés
- `total_scans`: Scans total effectués
- `avg_scan_duration`: Durée moyenne scans
- `last_activity_detected`: Dernière activité blockchain
- `consecutive_empty_scans`: Scans vides consécutifs
- `best_priority_ever`, `worst_priority_ever`: Extremums historiques
- `priority_history`: JSON historique scores (pour trending)

#### Autres tables
- `wallet_stats`: Statistiques globales par wallet
- `scan_history`: Historique détaillé des scans
- `wallet_activity_metrics`: Métriques activité par périodes
- `scan_queue`: Queue des scans planifiés
- `system_config`: Configuration système key-value
- `system_logs`: Logs système (optionnel)

### Index de performance
**Index critiques**:
- `idx_transactions_wallet_time`: Requêtes transactions par wallet
- `idx_wallet_priorities_score`: Sélection wallet par priorité
- `idx_token_accounts_priority`: Scan comptes par priorité
- `idx_scan_history_wallet`: Historique par wallet
- **35+ index total** couvrant tous les patterns d'accès

### Boucle de maintenance `_maintenance_loop()`
**Tâches automatiques** (toutes les heures):
1. **Backup automatique**: Si activé et intervalle dépassé
2. **Nettoyage données**: Selon intervalles configurés
3. **VACUUM hebdomadaire**: Optimisation espace disque

**Robustesse**: Continue même si une tâche échoue

### Méthodes principales de gestion

#### `get_connection()` - Context Manager
```python
@contextmanager
def get_connection(self, retry_count: int = 3) -> Generator[sqlite3.Connection, None, None]:
```
- Délègue au pool de connexions
- Incrémente statistiques opérations
- Gestion d'erreurs avec décompte échecs

#### `execute_query()` - Exécution sécurisée
```python
def execute_query(self, query: str, params: tuple = (), 
                 fetch_one: bool = False, fetch_all: bool = False)
```
- Exécution avec paramètres (protection injection SQL)
- Options fetch automatiques
- Conversion erreurs SQLite en exceptions custom
- Logging erreurs avec troncature requête (100 chars)

#### `execute_many()` - Batch sécurisé
```python
def execute_many(self, query: str, params_list: List[tuple]) -> int:
```
- Insertion/update en lot pour performance
- Commit automatique
- Retour nombre lignes affectées

#### `transaction()` - Context Manager transactionnel
```python
def transaction(self) -> 'DatabaseTransaction':
```
- Retourne instance `DatabaseTransaction`
- Gestion automatique BEGIN/COMMIT/ROLLBACK

### Méthodes de monitoring

#### `get_stats()` - Statistiques complètes
**Sections retournées**:
- **Statistiques base**: Issues de `self.stats`
- **Pool connexions**: Via `connection_pool.get_stats()`
- **Métriques dérivées**: Uptime, opérations/heure, taux erreur
- **Fichier base**: Chemin, taille, dates modification
- **Tables**: Nombre lignes par table principale

#### `get_health_status()` - Health Check complet
**Vérifications effectuées**:
1. **Connectivité**: Test `SELECT 1` avec gestion erreurs
2. **Performance**: Mesure temps requête simple avec seuils
3. **Espace disque**: Vérification espace libre avec alertes (>1GB ok, >100MB warning, <100MB critical)
4. **Intégrité**: `PRAGMA integrity_check(10)` avec analyse résultats
5. **Pool connexions**: Taux utilisation avec seuils (80% ok, 95% warning, 100% critical)

**Statuts globaux**: `healthy`, `warning` (dégradé mais fonctionnel), `critical` (problème majeur), `error` (health check échoué)

### Méthodes de sauvegarde/restauration

#### `backup_database()` - Sauvegarde manuelle
```python
def backup_database(self, backup_path: Optional[str] = None) -> str:
```
- Path auto-généré si non fourni: `manual_backup_{timestamp}.db`
- Création répertoire automatique
- Utilise `sqlite3.Connection.backup()` pour cohérence
- Retour path sauvegarde créée

#### `restore_database()` - Restauration avec sécurité
```python
def restore_database(self, backup_path: str, confirm: bool = False):
```
- **Sécurité**: Confirmation explicite requise
- **Séquence sécurisée**:
  1. Arrêt thread maintenance
  2. Fermeture toutes connexions
  3. Sauvegarde base actuelle (`.pre_restore_{timestamp}`)
  4. Copie fichier sauvegarde
  5. Recréation pool connexions
  6. Redémarrage maintenance

#### `optimize_database()` - Optimisation complète
**Opérations effectuées**:
1. **VACUUM**: Récupération espace disque
2. **ANALYZE**: Mise à jour statistiques requêtes
3. **Integrity check**: Vérification cohérence
4. **Timing**: Mesure durée chaque opération

**Retour**: Dictionnaire avec durées et statuts

### Méthodes de nettoyage

#### `_perform_cleanup()` - Nettoyage automatique
**Tables nettoyées**:
- `scan_history`: Selon `CLEANUP_INTERVALS['old_scan_history']`
- `wallet_activity_metrics`: Selon `CLEANUP_INTERVALS['old_metrics']`
- `system_logs`: Selon `CLEANUP_INTERVALS['old_logs']`

**Logique**: Suppression basée sur colonnes timestamp avec cutoff calculé
**Robustesse**: Continue même si une table échoue
**Logging**: Détaillé par table + résumé global

#### `_perform_backup()` - Backup automatique
- Nom fichier: `backup_{timestamp}_{db_name}.db`
- Répertoire: `{db_dir}/backups/`
- Nettoyage automatique: Conservation 10 backups plus récents
- Mise à jour statistiques

## Classes utilitaires

### DatabaseTransaction - Context Manager transactionnel
```python
class DatabaseTransaction:
    def __init__(self, db_manager: DatabaseManager)
    def __enter__(self):  # BEGIN transaction
    def __exit__(self, exc_type, exc_val, exc_tb):  # COMMIT ou ROLLBACK
```

**Usage**:
```python
with db_manager.transaction() as cursor:
    cursor.execute("INSERT INTO ...")
    cursor.execute("UPDATE ...")
    # Auto-commit si pas d'exception, auto-rollback sinon
```

### DatabaseMigration - Migrations de schéma
**Fonctionnalités**:
- `get_current_version()`: Lecture version depuis `system_config`
- `migrate_to_version(target)`: Application migrations séquentielles
- Méthodes `_migrate_to_v{N}()`: Migrations spécifiques par version
- Logging détaillé étapes migration

### DatabaseMetrics - Collecte métriques avancées
**Métriques collectées**:
- **Features SQLite**: Via `PRAGMA compile_options`
- **Statistiques tables**: Nombre lignes, colonnes, taille estimée
- **Performance requêtes**: Test requêtes types avec mesure durée
- Classification performance: `fast` (<100ms), `normal` (<1s), `slow` (>1s)

## Fonctions utilitaires globales

### `get_database_manager(config=None) -> DatabaseManager`
Factory function pour récupération instance singleton

### `create_database_backup(db_path: str, backup_path: str) -> bool`
Fonction utilitaire backup simple sans gestionnaire complet

### `test_database_connection(db_path: str, timeout: float = 5.0) -> bool`
Test basique connectivité SQLite

## Gestion des erreurs

### Exceptions custom utilisées
- `DatabaseError`: Erreur générique base de données
- `DatabaseConnectionError`: Échec connexion/pool exhausté
- `DatabaseLockError`: Base verrouillée avec temps attente
- `DatabaseSchemaError`: Problème structure/migration
- `DatabaseIntegrityError`: Violation contraintes

### Conversion automatique
Les erreurs SQLite natives sont converties en exceptions custom appropriées avec contexte enrichi

## Thread Safety

### Éléments thread-safe
- **Pool connexions**: RLock + Queue thread-safe
- **Statistiques**: Mise à jour atomique avec locks
- **Singleton**: Double-checked locking pattern
- **Context managers**: Isolation par thread

### Bonnes pratiques
- Toujours utiliser context managers pour connexions
- Paramètres requêtes pour éviter injection SQL
- Transactions explicites pour opérations multi-étapes
- Gestion d'erreurs granulaire avec retry

## Configuration et constantes

### Depuis `utils/constants.py`
- `SQLITE_SETTINGS`: Paramètres optimisation SQLite
- `DB_QUERY_LIMITS`: Limites requêtes par table
- `CLEANUP_INTERVALS`: Intervalles nettoyage automatique

### Configuration runtime
Tous paramètres modifiables via `core/config.py` système configuration centralisé

## Performance et optimisations

### Optimisations SQLite
- **WAL mode**: Améliore concurrence lecture/écriture
- **Cache optimisé**: 64MB cache, pages 4KB
- **Memory mapping**: 256MB pour gros fichiers
- **Temp en mémoire**: Tables temporaires en RAM
- **Auto-optimize**: Optimisations automatiques SQLite

### Optimisations architecture
- **Pool connexions**: Réutilisation évite overhead création
- **Batch queries**: `execute_many()` pour lots
- **Index exhaustifs**: 35+ index couvrant tous patterns
- **Nettoyage automatique**: Évite croissance excessive
- **VACUUM périodique**: Récupération espace

Cette documentation couvre l'intégralité du système de base de données avec toutes ses fonctionnalités avancées, permettant une compréhension complète sans accès au code source.