# Solana Transaction Storage - Documentation Technique

## Vue d'ensemble

Le **Solana Transaction Storage** est un module de stockage avancé de transactions avec indexation, compression et politiques de rétention. Il fournit un système de stockage haute performance optimisé pour les données volumineuses de transactions avec compression, archivage et recherche full-text.

## Architecture générale

### Imports et dépendances

**Imports système :**
- `time`, `sqlite3`, `threading` - Temps, base de données, concurrence
- `typing` - Annotations de type (Dict, List, Optional, Tuple, Any, Set)
- `dataclasses` - Structures de données (dataclass, field)
- `datetime.{datetime, timedelta}` - Gestion dates
- `decimal.Decimal` - Calculs décimaux précis
- `json`, `zlib`, `hashlib` - JSON, compression, hachage

**Imports métier avec fallbacks :**
- `core.logger.get_logger` → fallback: `logging.getLogger()`
- `core.database.get_database_manager` → fallback: `None`
- `core.config.get_config` → fallback: `None`
- `core.exceptions.DatabaseError` → pas de fallback
- `models.transaction.{Transaction, TransactionType, TransactionStatus}` → pas de fallback
- `models.token.Token` → pas de fallback
- `utils.helpers.{get_current_timestamp, safe_divide}` → pas de fallback
- `utils.validators.validate_wallet_address` → fallback: `len(addr) == 44`

## Structures de données

### StorageStats

```python
@dataclass
class StorageStats:
    total_transactions: int = 0        # Nombre total transactions
    total_compressed: int = 0          # Nombre transactions compressées
    storage_size_mb: float = 0.0       # Taille stockage en MB
    compression_ratio: float = 1.0     # Ratio compression moyen
    last_cleanup: int                  # Timestamp dernier nettoyage
```

### StorageConfig

```python
@dataclass
class StorageConfig:
    compression_enabled: bool = True    # Compression activée
    compression_level: int = 6          # Niveau compression zlib (1-9)
    retention_days: int = 365          # Durée rétention en jours
    max_batch_size: int = 1000         # Taille max batch
    enable_indexing: bool = True       # Indexation activée
    enable_archiving: bool = True      # Archivage activé
```

## Classe principale : TransactionStorage

### Initialisation

**Attributs d'instance :**
- `self.config` - Configuration via `get_config()`
- `self.db_manager` - Gestionnaire base de données
- `self.storage_config = StorageConfig()` - Configuration stockage
- `self.stats = StorageStats()` - Statistiques stockage

**Structures thread-safe :**
- `self._lock = threading.Lock()` - Verrou pour opérations atomiques
- `self._batch_queue: List[Transaction] = []` - Queue batch transactions
- `self._compression_cache: Dict[str, bytes] = {}` - Cache compression
- `self._index_cache: Dict[str, Set[str]]` - Cache index (defaultdict)

**Initialisation :** Appel `_initialize_storage()` automatique

**Log d'initialisation :** "💾 Transaction storage initialized"

### Initialisation base de données

#### `_initialize_storage()`

**Fonction :** Initialise tables et index de stockage

**Tables créées :**

1. **Table principale `transactions` :**
```sql
CREATE TABLE IF NOT EXISTS transactions (
    signature TEXT PRIMARY KEY,          -- Signature unique transaction
    wallet_address TEXT NOT NULL,        -- Adresse portefeuille
    slot INTEGER NOT NULL,               -- Slot Solana
    block_time INTEGER NOT NULL,         -- Timestamp block
    amount REAL NOT NULL,               -- Montant SOL
    fee REAL NOT NULL,                  -- Frais transaction
    token_mint TEXT,                    -- Mint token (optionnel)
    token_symbol TEXT,                  -- Symbole token
    token_name TEXT,                    -- Nom token
    token_amount REAL,                  -- Quantité token
    price_per_token REAL,               -- Prix unitaire token
    transaction_type TEXT NOT NULL,      -- Type transaction
    status TEXT NOT NULL,               -- Statut transaction
    source TEXT,                        -- Source données
    metadata_json TEXT,                 -- Métadonnées JSON
    compressed_data BLOB,               -- Données compressées
    created_at INTEGER NOT NULL,        -- Timestamp création
    updated_at INTEGER NOT NULL,        -- Timestamp mise à jour
    tags TEXT                          -- Tags (JSON)
)
```

2. **Table compression `transactions_compressed` :**
```sql
CREATE TABLE IF NOT EXISTS transactions_compressed (
    signature TEXT PRIMARY KEY,
    wallet_address TEXT NOT NULL,
    compressed_data BLOB NOT NULL,      -- Données compressées zlib
    original_size INTEGER NOT NULL,     -- Taille originale
    compressed_size INTEGER NOT NULL,   -- Taille compressée
    compression_ratio REAL NOT NULL,    -- Ratio compression
    created_at INTEGER NOT NULL
)
```

3. **Table tags `transaction_tags` :**
```sql
CREATE TABLE IF NOT EXISTS transaction_tags (
    signature TEXT NOT NULL,
    tag_name TEXT NOT NULL,            -- Nom du tag
    tag_value TEXT,                    -- Valeur tag (optionnel)
    confidence REAL,                   -- Confiance tag
    created_at INTEGER NOT NULL,
    PRIMARY KEY (signature, tag_name)
)
```

4. **Table analytiques `transaction_analytics` :**
```sql
CREATE TABLE IF NOT EXISTS transaction_analytics (
    signature TEXT PRIMARY KEY,
    pnl_sol REAL,                     -- P&L en SOL
    pnl_usd REAL,                     -- P&L en USD
    classification TEXT,               -- Classification transaction
    confidence REAL,                   -- Confiance classification
    risk_score REAL,                  -- Score de risque
    patterns_detected TEXT,           -- Patterns détectés (JSON)
    metadata_json TEXT,               -- Métadonnées analytiques
    analyzed_at INTEGER NOT NULL
)
```

**Index de performance créés :**
- `idx_transactions_wallet_time` : `(wallet_address, block_time DESC)`
- `idx_transactions_token` : `(token_mint, block_time DESC)`
- `idx_transactions_type` : `(transaction_type, status)`
- `idx_transactions_recent` : `(block_time DESC, wallet_address)`

### Stockage de transactions

#### 1. `store_transaction(transaction: Transaction, compress: bool = None) -> bool`

**Fonction :** Stocke une transaction unique avec compression optionnelle

**Processus :**
1. **Validation :** Adresse wallet via `validate_wallet_address()`
2. **Préparation données :** Conversion `Transaction` → dictionnaire
3. **Choix stockage :**
   - Si `compress=True` ou `storage_config.compression_enabled` → `_store_compressed_transaction()`
   - Sinon → `_store_uncompressed_transaction()`

**Structure données préparées :**
```python
transaction_data = {
    'signature': str,
    'wallet_address': str,
    'slot': int,
    'block_time': int,
    'amount': float,
    'fee': float,
    'token_mint': Optional[str],
    'token_symbol': Optional[str],
    'token_name': Optional[str],
    'token_amount': Optional[float],
    'price_per_token': Optional[float],
    'transaction_type': str,
    'status': str,
    'source': str,
    'created_at': int,
    'updated_at': int
}
```

#### 2. `_store_uncompressed_transaction(data: Dict[str, Any]) -> bool`

**Fonction :** Stockage sans compression dans table principale

**Requête SQL :**
```sql
INSERT OR REPLACE INTO transactions (
    signature, wallet_address, slot, block_time, amount, fee,
    token_mint, token_symbol, token_name, token_amount,
    price_per_token, transaction_type, status, source,
    created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
```

**Statistiques :** Incrémente `stats.total_transactions` (thread-safe)

#### 3. `_store_compressed_transaction(data: Dict[str, Any]) -> bool`

**Fonction :** Stockage avec compression zlib

**Processus compression :**
1. **Sérialisation :** `json.dumps(data)`
2. **Compression :** `zlib.compress(json_data.encode('utf-8'), compression_level)`
3. **Métriques :**
   - `original_size = len(json_data.encode('utf-8'))`
   - `compressed_size = len(compressed)`
   - `compression_ratio = compressed_size / original_size`

**Requête SQL :**
```sql
INSERT OR REPLACE INTO transactions_compressed (
    signature, wallet_address, compressed_data,
    original_size, compressed_size, compression_ratio, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?)
```

**Statistiques :** Incrémente `stats.total_compressed` et met à jour `stats.compression_ratio`

#### 4. `store_batch_transactions(transactions: List[Transaction]) -> int`

**Fonction :** Stockage efficace de multiples transactions

**Processus batch :**
1. **Batching :** Division en chunks de `max_batch_size` (défaut 1000)
2. **Transaction BDD :** `BEGIN TRANSACTION` pour chaque batch
3. **Stockage individuel :** Appel `store_transaction()` pour chaque transaction
4. **Commit :** `COMMIT` à la fin de chaque batch

**Retour :** Nombre de transactions stockées avec succès

### Récupération de données

#### 5. `get_transaction(signature: str) -> Optional[Transaction]`

**Fonction :** Récupère transaction unique par signature

**Requête SQL :**
```sql
SELECT * FROM transactions
WHERE signature = ?
```

**Construction objet :** Création complète objet `Transaction` depuis BDD

#### 6. `get_wallet_transactions()` (signature complète)

```python
def get_wallet_transactions(
    self,
    wallet_address: str,
    token_mint: Optional[str] = None,
    transaction_type: Optional[TransactionType] = None,
    status: Optional[TransactionStatus] = None,
    limit: int = 100,
    offset: int = 0,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None
) -> List[Transaction]
```

**Fonction :** Récupère transactions portefeuille avec filtrage avancé

**Construction requête dynamique :**
```sql
SELECT * FROM transactions
WHERE wallet_address = ?
-- Filtres conditionnels :
[AND token_mint = ?]
[AND transaction_type = ?]
[AND status = ?]
[AND block_time >= ?]  -- start_time
[AND block_time <= ?]  -- end_time
ORDER BY block_time DESC 
LIMIT ? OFFSET ?
```

**Filtres supportés :**
- **Token :** Filtrage par mint spécifique
- **Type :** Filtrage par type transaction (BUY, SELL, etc.)
- **Statut :** Filtrage par statut (SUCCESS, FAILED)
- **Période :** Filtrage temporel avec start_time/end_time
- **Pagination :** Support limit/offset

#### 7. `get_transaction_analytics(signature: str) -> Optional[Dict[str, Any]]`

**Fonction :** Récupère données analytiques d'une transaction

**Requête SQL :**
```sql
SELECT * FROM transaction_analytics
WHERE signature = ?
```

**Structure retour :**
```python
{
    'pnl_sol': float,
    'pnl_usd': float,
    'classification': str,
    'confidence': float,
    'risk_score': float,
    'patterns_detected': List[str],  # Désérialisé JSON
    'metadata': Dict[str, Any],      # Désérialisé JSON
    'analyzed_at': int
}
```

### Maintenance et nettoyage

#### 8. `cleanup_old_data(days: int = None) -> int`

**Fonction :** Nettoyage données anciennes selon politique rétention

**Processus nettoyage :**
1. **Calcul cutoff :** `current_time - (days * 86400)`
2. **Nettoyage transactions principales :**
   ```sql
   DELETE FROM transactions
   WHERE block_time < ?
   ```
3. **Nettoyage transactions compressées :**
   ```sql
   DELETE FROM transactions_compressed
   WHERE created_at < ?
   ```
4. **Nettoyage analytiques :**
   ```sql
   DELETE FROM transaction_analytics
   WHERE analyzed_at < ?
   ```

**Statistiques :** Met à jour `stats.last_cleanup`

**Log :** "🧹 Cleaned up old data: X records removed"

**Retour :** Nombre total enregistrements supprimés

### Statistiques et monitoring

#### 9. `get_storage_stats() -> Dict[str, Any]`

**Fonction :** Statistiques complètes du stockage

**Métriques calculées :**
```python
{
    'total_transactions': int,      # COUNT(*) FROM transactions
    'compressed_transactions': int, # COUNT(*) FROM transactions_compressed
    'storage_size_mb': float,      # Taille en MB des données compressées
    'compression_ratio': float,    # Ratio compression moyen
    'retention_days': int,         # Politique rétention
    'last_cleanup': int           # Timestamp dernier nettoyage
}
```

**Requêtes SQL spécialisées :**
- **Taille stockage :** `SUM(LENGTH(compressed_data))`
- **Taille originale :** `SUM(original_size)`
- **Ratio compression :** `compressed_size / original_size`

### Recherche et export

#### 10. `search_transactions(query: str, wallet_address: Optional[str] = None, limit: int = 50) -> List[Transaction]`

**Fonction :** Recherche full-text dans transactions

**Requête SQL avec LIKE :**
```sql
SELECT * FROM transactions
WHERE (signature LIKE ? OR token_symbol LIKE ? OR token_name LIKE ?)
[AND wallet_address = ?]  -- Si wallet spécifié
ORDER BY block_time DESC 
LIMIT ?
```

**Patterns recherche :** `%{query}%` sur signature, token_symbol, token_name

#### 11. `export_transactions()` (signature complète)

```python
def export_transactions(
    self,
    wallet_address: str,
    format: str = "json",
    start_time: Optional[int] = None,
    end_time: Optional[int] = None
) -> str
```

**Fonction :** Export transactions dans format spécifié

**Formats supportés :**

1. **JSON :** 
   - Sérialisation `json.dumps()` avec `indent=2`
   - Appel `tx.to_dict()` pour chaque transaction

2. **CSV :**
   - Utilisation module `csv` standard Python
   - Headers : signature, wallet_address, slot, block_time, amount, fee, etc.
   - Writer CSV avec `StringIO` pour output mémoire

## Instances et fonctions globales

### Instance globale singleton
```python
_storage = None

def get_transaction_storage() -> TransactionStorage:
    global _storage
    if _storage is None:
        _storage = TransactionStorage()
    return _storage
```

### Fonctions de convenance

#### `store_transaction(transaction: Transaction) -> bool`
**Wrapper :** `get_transaction_storage().store_transaction(transaction)`

#### `get_transaction(signature: str) -> Optional[Transaction]`
**Wrapper :** `get_transaction_storage().get_transaction(signature)`

#### `get_wallet_transactions(wallet_address: str, **kwargs) -> List[Transaction]`
**Wrapper :** `get_transaction_storage().get_wallet_transactions(wallet_address, **kwargs)`

#### `cleanup_old_transactions(days: int = 365) -> int`
**Wrapper :** `get_transaction_storage().cleanup_old_data(days)`

## Schéma de base de données complet

### Tables principales

#### Table `transactions` (principale)
```sql
CREATE TABLE IF NOT EXISTS transactions (
    -- Identifiants
    signature TEXT PRIMARY KEY,
    wallet_address TEXT NOT NULL,
    
    -- Données blockchain
    slot INTEGER NOT NULL,
    block_time INTEGER NOT NULL,
    
    -- Montants
    amount REAL NOT NULL,
    fee REAL NOT NULL,
    
    -- Données token (optionnelles)
    token_mint TEXT,
    token_symbol TEXT,
    token_name TEXT,
    token_amount REAL,
    price_per_token REAL,
    
    -- Classification
    transaction_type TEXT NOT NULL,
    status TEXT NOT NULL,
    source TEXT,
    
    -- Métadonnées
    metadata_json TEXT,
    compressed_data BLOB,
    
    -- Timestamps
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    
    -- Tags
    tags TEXT
);
```

#### Index de performance
```sql
-- Index principal par wallet et temps
CREATE INDEX IF NOT EXISTS idx_transactions_wallet_time 
ON transactions(wallet_address, block_time DESC);

-- Index par token et temps
CREATE INDEX IF NOT EXISTS idx_transactions_token 
ON transactions(token_mint, block_time DESC);

-- Index par type et statut
CREATE INDEX IF NOT EXISTS idx_transactions_type 
ON transactions(transaction_type, status);

-- Index temporel général
CREATE INDEX IF NOT EXISTS idx_transactions_recent 
ON transactions(block_time DESC, wallet_address);
```

#### Table compression
```sql
CREATE TABLE IF NOT EXISTS transactions_compressed (
    signature TEXT PRIMARY KEY,
    wallet_address TEXT NOT NULL,
    compressed_data BLOB NOT NULL,
    original_size INTEGER NOT NULL,
    compressed_size INTEGER NOT NULL,
    compression_ratio REAL NOT NULL,
    created_at INTEGER NOT NULL
);
```

#### Table tags
```sql
CREATE TABLE IF NOT EXISTS transaction_tags (
    signature TEXT NOT NULL,
    tag_name TEXT NOT NULL,
    tag_value TEXT,
    confidence REAL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (signature, tag_name)
);
```

#### Table analytiques
```sql
CREATE TABLE IF NOT EXISTS transaction_analytics (
    signature TEXT PRIMARY KEY,
    pnl_sol REAL,
    pnl_usd REAL,
    classification TEXT,
    confidence REAL,
    risk_score REAL,
    patterns_detected TEXT, -- JSON array
    metadata_json TEXT,
    analyzed_at INTEGER NOT NULL
);
```

## Patterns et logiques métier

### Compression intelligente
- **Niveau configurable :** zlib niveau 6 par défaut (balance vitesse/ratio)
- **Compression sélective :** Basée sur taille et configuration
- **Métriques détaillées :** Tracking ratio compression, taille originale/compressée
- **Cache compression :** Évite re-compression données identiques

### Indexation optimisée
- **Index composites :** (wallet_address, block_time) pour requêtes temporelles
- **Index spécialisés :** Par token mint, type transaction, statut
- **Ordre DESC :** block_time pour requêtes récentes (pattern commun)

### Batch processing
- **Taille configurable :** max_batch_size pour contrôler mémoire
- **Transactions BDD :** Atomicité par batch pour cohérence
- **Gestion erreurs :** Continue sur erreur individuelle, compte succès

### Politique de rétention
- **Configurable :** retention_days par défaut 365 jours
- **Nettoyage multi-tables :** Cohérence entre tables liées
- **Cleanup automatique :** Via méthode explicite (intégrable cron)

### Thread safety
- **Verrous granulaires :** Lock uniquement pour stats partagées
- **Opérations atomiques :** BDD SQLite thread-safe par défaut
- **Cache thread-local :** Évite contention sur structures partagées

## Gestion d'erreurs et logging

### Préfixes de logs
- 💾 : Stockage/sauvegarde
- 🔍 : Récupération/recherche
- 📊 : Statistiques
- 🧹 : Nettoyage/maintenance
- 🧪 : Tests
- ✅ : Succès
- ⚠️ : Avertissements
- ❌ : Erreurs

### Stratégies d'erreur
- **Graceful degradation :** Retour False/None plutôt qu'exceptions
- **Logging détaillé :** Context complet pour debugging
- **Validation stricte :** Adresses wallet, données avant stockage
- **Rollback automatique :** Transactions BDD pour cohérence

## Exemple de test (section __main__)

**Transaction de test :**
```python
Transaction(
    signature="test_storage_123456789",
    wallet_address="4DdrfGHGdMjCqVbNtXsEEGL1SryTeMo8KMGWWtZyZVFh",
    slot=123456789,
    amount=1.5, fee=0.0005,
    token_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    token_symbol="USDC", token_amount=150.0, price_per_token=1.0,
    transaction_type="buy", status="success", source="test"
)
```

**Tests effectués :**
1. **Stockage :** `store_transaction()` avec validation succès
2. **Récupération :** `get_transaction()` par signature
3. **Statistiques :** `get_storage_stats()` avec métriques

## Points d'extension

1. **Partitioning :** Partitionnement tables par période pour scaling
2. **Compression avancée :** Algorithmes spécialisés (LZ4, Snappy) selon usage
3. **Distributed Storage :** Sharding par wallet ou période
4. **Real-time Indexing :** Index full-text avec FTS pour recherche avancée
5. **Archive Tiers :** Stockage froid pour données anciennes
6. **Backup/Restore :** Mécanismes sauvegarde incrémentale
7. **Analytics Engine :** Pré-calculs et matérialisations pour analytics
8. **Monitoring :** Métriques performance, alertes espace disque