# Solana Wallet Scanner - Documentation Technique

## Vue d'ensemble

Le **Solana Wallet Scanner** est un moteur de scanning avancé pour découvrir tokens et transactions dans les portefeuilles Solana. Il fournit plusieurs modes de scanning optimisés avec cache intelligent, batch processing RPC et stockage automatique des découvertes.

## Architecture générale

### Imports et dépendances

**Imports système :**
- `time`, `threading` - Temps et gestion concurrence
- `typing` - Annotations de type (Dict, List, Optional, Set, Tuple, Any)
- `dataclasses` - Structures de données (dataclass, field)
- `datetime.datetime` - Gestion dates
- `decimal.Decimal` - Calculs décimaux précis

**Imports métier avec fallbacks :**
- `core.logger.get_logger` → fallback: `logging.getLogger()`
- `core.database.get_database_manager` → fallback: `None`
- `core.config.get_config` → fallback: `None`
- `core.exceptions.MonitoringError` → pas de fallback
- `models.*` - Token, TokenAccount, TokenDiscovery, Transaction, etc.
- `utils.helpers.{get_current_timestamp, safe_divide}` → pas de fallback
- `utils.validators.validate_wallet_address` → fallback: `len(addr) == 44`
- `rpc.client.get_rpc_client` → fallback: `None`
- `rpc.batch_manager.create_batch_manager` → pas de fallback

## Structures de données

### ScanBatch

```python
@dataclass
class ScanBatch:
    wallet_address: str             # Adresse portefeuille à scanner
    accounts: List[str]            # Liste comptes à traiter
    scan_type: str                 # Type de scan à effectuer
    priority: int = 5              # Priorité du batch
    created_at: int                # Timestamp création
```

### ScanResult

```python
@dataclass
class ScanResult:
    wallet_address: str                    # Adresse portefeuille scanné
    scan_type: str                        # Type scan effectué
    total_accounts: int                   # Total comptes trouvés
    new_accounts: int                     # Nouveaux comptes découverts
    scan_duration: float                  # Durée scan en secondes
    tokens_discovered: List[TokenDiscovery]  # Tokens découverts
    transactions_found: List[Transaction]    # Transactions trouvées
    balances_updated: List[Dict[str, Any]]  # Balances mises à jour
    completed_at: int                     # Timestamp completion
    success: bool = True                  # Statut succès
    error_message: Optional[str] = None   # Message erreur si échec
```

### TokenAccountInfo

```python
@dataclass
class TokenAccountInfo:
    ata_pubkey: str                # Clé publique compte token associé
    token_mint: str               # Adresse mint token
    owner: str                    # Propriétaire compte
    balance: int                  # Balance en unités minimales
    decimals: int                 # Nombre décimales token
    token_symbol: str             # Symbole token
    token_name: str               # Nom token
    is_frozen: bool = False       # Compte gelé
    is_native: bool = False       # Token natif (SOL)
    rent_exempt_reserve: int = 0  # Réserve exemption loyer
```

## Classe principale : WalletScanner

### Initialisation

**Composants core :**
- `self.config` - Configuration système
- `self.db_manager` - Gestionnaire base de données
- `self.rpc_client` - Client RPC Solana

**Thread safety :**
- `self._lock = threading.Lock()` - Verrou pour opérations atomiques
- `self._active_scans: Dict[str, int]` - Scans en cours (wallet → timestamp)
- `self._scan_cache: Dict[str, Dict]` - Cache résultats scan
- `self._cache_timeout = 300` - Expiration cache (5 minutes)

**Configuration :**
```python
self.BATCH_SIZE = 100           # Taille batch RPC
self.MAX_RETRIES = 3            # Tentatives maximum
self.SCAN_TIMEOUT = 30          # Timeout scan (secondes)
self.RATE_LIMIT_DELAY = 0.1     # Délai rate limiting
```

**Batch manager :** `self.batch_manager` - Gestionnaire requêtes groupées RPC

**Log d'initialisation :** "🔍 Wallet scanner initialized"

### Initialisation batch manager

#### `_initialize_batch_manager()`

**Fonction :** Initialise gestionnaire batch pour requêtes RPC efficaces

**Processus :**
1. Vérification `self.rpc_client` disponible
2. Import `create_batch_config` et création configuration
3. Création `batch_manager` via `create_batch_manager()`
4. Log "✅ Batch manager initialized" ou warning si échec

### Méthode principale de scanning

#### `scan_wallet(wallet_address: str, scan_type: str = "full") -> Dict[str, Any]`

**Fonction :** Scanning complet portefeuille avec types configurables

**Types de scan supportés :**
- **"full"** : Scan complet (tokens + transactions + balances)
- **"quick"** : Scan rapide (balances seulement)
- **"balances"** : Focus balances
- **"tokens"** : Focus découverte tokens

**Processus de scanning :**

1. **Validation :** `validate_wallet_address(wallet_address)`

2. **Protection concurrence :**
   ```python
   with self._lock:
       if wallet_address in self._active_scans:
           return {"error": "Scan already in progress"}
       self._active_scans[wallet_address] = scan_start
   ```

3. **Vérification cache :**
   - `_should_use_cache(wallet_address, scan_type)`
   - Si cache valide → retour `_get_cached_result()`

4. **Dispatch par type :**
   - `"full"` → `_perform_full_scan(wallet_address)`
   - `"quick"` → `_perform_quick_scan(wallet_address)`
   - `"balances"` → `_perform_balance_scan(wallet_address)`
   - `"tokens"` → `_perform_token_scan(wallet_address)`

5. **Cache résultats :** `_cache_result(wallet_address, scan_type, result)`

6. **Cleanup :** Suppression de `_active_scans`

**Log succès :** "✅ Scan completed for {wallet}: {tokens} tokens, {transactions} transactions"

### Implémentations scan spécialisées

#### `_perform_full_scan(wallet_address: str) -> Dict[str, Any]`

**Fonction :** Scan complet avec toutes données

**Étapes séquentielles :**

1. **Token accounts :** `token_accounts = _get_token_accounts(wallet_address)`
2. **Transactions :** `transactions = _get_recent_transactions(wallet_address)`
3. **Process tokens :** `tokens_discovered = _process_token_accounts(wallet_address, token_accounts)`
4. **Process transactions :** `transactions_processed = _process_transactions(wallet_address, transactions)`
5. **Update balances :** `balances_updated = _update_balances(wallet_address, token_accounts)`

**Structure retour :**
```python
{
    "wallet_address": str,
    "scan_type": "full",
    "total_accounts": len(token_accounts),
    "new_accounts": len([t for t in tokens_discovered if t.discovery_method == "new_scan"]),
    "scan_duration": float,
    "tokens_discovered": List[TokenDiscovery],
    "transactions_found": List[Transaction],
    "balances_updated": List[Dict],
    "completed_at": int,
    "success": True
}
```

#### `_perform_quick_scan(wallet_address: str) -> Dict[str, Any]`

**Fonction :** Scan rapide (balances uniquement)

**Processus simplifié :**
1. Get token accounts via `_get_token_accounts()`
2. Update balances via `_update_balances()`
3. Pas de discovery tokens ni transactions

#### `_perform_token_scan(wallet_address: str) -> Dict[str, Any]`

**Fonction :** Scan focalisé découverte tokens

**Processus :**
1. Get token accounts
2. Process pour découvertes via `_process_token_accounts()`
3. Pas de transactions ni balances

### Récupération données blockchain

#### `_get_token_accounts(wallet_address: str) -> List[TokenAccountInfo]`

**Fonction :** Récupère tous comptes token d'un portefeuille

**Processus :**
- Si `batch_manager` disponible → `_get_token_accounts_batch()`
- Sinon → fallback `_get_token_accounts_direct()`

#### `_get_token_accounts_batch(wallet_address: str) -> List[TokenAccountInfo]`

**Fonction :** Récupération via batch manager (efficace)

**Appel RPC :**
```python
response = self.rpc_client.call(
    "getTokenAccountsByOwner",
    [
        wallet_address, 
        {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}, 
        {"encoding": "jsonParsed"}
    ]
)
```

**Parsing réponse :**
1. Navigation : `response['result']['value']`
2. Pour chaque `account_data` :
   - Extraction `pubkey` et `account_info`
   - Parse `account_info['data']['parsed']`
   - Vérification `parsed['type'] == 'account'`
   - Construction `TokenAccountInfo` avec :
     ```python
     TokenAccountInfo(
         ata_pubkey=pubkey,
         token_mint=info['mint'],
         owner=info['owner'],
         balance=int(info['tokenAmount']['amount']),
         decimals=int(info['tokenAmount']['decimals']),
         # autres champs...
     )
     ```

#### `_get_recent_transactions(wallet_address: str) -> List[Dict[str, Any]]`

**Fonction :** Récupère transactions récentes

**Processus en 2 étapes :**

1. **Get signatures :**
   ```python
   response = self.rpc_client.call(
       "getSignaturesForAddress",
       [wallet_address, {"limit": 50}]
   )
   ```

2. **Get transaction details :**
   ```python
   for signature in signatures[:20]:  # Limite à 20
       tx_response = self.rpc_client.call(
           "getTransaction",
           [signature, {"encoding": "json", "maxSupportedTransactionVersion": 0}]
       )
   ```

**Format retour :** `[{'signature': str, 'transaction': dict}, ...]`

### Traitement et persistance

#### `_process_token_accounts(wallet_address, accounts) -> List[TokenDiscovery]`

**Fonction :** Traite comptes token et découvre nouveaux tokens

**Processus :**
1. **Get existing :** `existing_mints = _get_existing_tokens(wallet_address)`
2. **Filtrage nouveaux :** Pour chaque account si `token_mint not in existing_mints`
3. **Création discovery :**
   ```python
   discovery = TokenDiscovery(
       token_mint=account.token_mint,
       wallet_address=wallet_address,
       discovered_at=get_current_timestamp(),
       ata_pubkey=account.ata_pubkey,
       initial_balance=safe_divide(account.balance, 10**account.decimals),
       decimals=account.decimals,
       symbol=account.token_symbol,
       name=account.token_name,
       discovery_method="balance_scan",
       confidence_score=1.0
   )
   ```
4. **Stockage :** `_store_discovery(discovery)`

#### `_process_transactions(wallet_address, transactions) -> List[Transaction]`

**Fonction :** Traite transactions et crée enregistrements

**Processus :**
1. Parse chaque transaction via `_parse_transaction()`
2. Store via `_store_transaction()`

#### `_parse_transaction(wallet_address, tx_data) -> Optional[Transaction]`

**Fonction :** Parse données transaction vers modèle Transaction

**Extraction données :**
```python
tx = tx_data['transaction']
signature = tx_data['signature']
slot = tx.get('slot', 0)
block_time = tx.get('blockTime', 0)
meta = tx.get('meta', {})

# Calcul montants
amount = 0.0  # À déterminer depuis transaction
fee = float(meta.get('fee', 0)) / 1_000_000_000  # Lamports → SOL

# Type transaction
tx_type = TransactionType.TRANSFER  # Logique classification

# Status
status = TransactionStatus.SUCCESS if not meta.get('err') else TransactionStatus.FAILED
```

#### `_update_balances(wallet_address, accounts) -> List[Dict[str, Any]]`

**Fonction :** Met à jour informations balance portefeuille

**Processus :**
1. Pour chaque account, création :
   ```python
   balance_info = {
       'wallet_address': wallet_address,
       'token_mint': account.token_mint,
       'balance': safe_divide(account.balance, 10**account.decimals),
       'decimals': account.decimals,
       'updated_at': get_current_timestamp()
   }
   ```
2. Stockage via `_store_balance_update(balance_info)`

### Méthodes de stockage BDD

#### `_store_discovery(discovery: TokenDiscovery) -> bool`

**Requête SQL :**
```sql
INSERT OR REPLACE INTO token_discoveries 
(token_mint, wallet_address, discovered_at, ata_pubkey, 
 initial_balance, decimals, symbol, name, discovery_method, confidence_score)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
```

#### `_store_transaction(transaction: Transaction) -> bool`

**Requête SQL :**
```sql
INSERT OR REPLACE INTO transactions 
(signature, wallet_address, slot, block_time, amount, fee, 
 token_mint, token_symbol, token_name, token_amount, 
 price_per_token, transaction_type, status, source, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
```

#### `_store_balance_update(balance_info: Dict[str, Any]) -> bool`

**Requête SQL :**
```sql
INSERT OR REPLACE INTO token_accounts 
(wallet_address, token_mint, balance, decimals, last_updated)
VALUES (?, ?, ?, ?, ?)
```

### Gestion cache

#### `_should_use_cache(wallet_address, scan_type) -> bool`

**Fonction :** Détermine si cache doit être utilisé

**Logique :**
```python
cache_key = f"{wallet_address}:{scan_type}"
if cache_key in self._scan_cache:
    cached_time = self._scan_cache[cache_key].get('cached_at', 0)
    if get_current_timestamp() - cached_time < self._cache_timeout:
        return True
```

#### `_cache_result(wallet_address, scan_type, result)`

**Fonction :** Met en cache résultats scan

**Cache structure :**
```python
cache_key = f"{wallet_address}:{scan_type}"
self._scan_cache[cache_key] = {
    **result,
    'cached_at': get_current_timestamp()
}
```

#### `cleanup_cache() -> int`

**Fonction :** Nettoie entrées cache expirées

**Processus thread-safe :**
1. Identification clés expirées
2. Suppression sous verrou
3. Log "🧹 Cleaned {count} expired cache entries"

### Utilitaires et requêtes

#### `_get_existing_tokens(wallet_address: str) -> Set[str]`

**Fonction :** Récupère mints tokens existants pour un wallet

**Requête SQL :**
```sql
SELECT token_mint FROM token_accounts
WHERE wallet_address = ?
```

#### `get_scan_status() -> Dict[str, Any]`

**Fonction :** Status actuel système scanning

**Retour :**
```python
{
    'active_scans': len(self._active_scans),
    'cache_size': len(self._scan_cache),
    'batch_manager_available': bool,
    'rpc_client_available': bool
}
```

#### `get_scanning_history(wallet_address, limit=50) -> List[Dict[str, Any]]`

**Fonction :** Historique scanning pour un wallet

**Requête SQL :**
```sql
SELECT * FROM scan_history
WHERE wallet_address = ?
ORDER BY completed_at DESC
LIMIT ?
```

## Fonctions globales

### Instance singleton

#### `get_wallet_scanner() -> WalletScanner`

**Singleton global :** Instance unique thread-safe

### Fonctions de convenance

#### `scan_wallet(wallet_address: str, scan_type: str = "full") -> Dict[str, Any]`
**Wrapper :** `get_wallet_scanner().scan_wallet(wallet_address, scan_type)`

#### `scan_multiple_wallets(wallet_addresses: List[str]) -> Dict[str, Dict[str, Any]]`
**Fonction :** Scanne multiple wallets

**Processus :** Itération avec `scanner.scan_wallet()` pour chaque wallet

## Modèles de données (inférés)

### TokenDiscovery

```python
@dataclass
class TokenDiscovery:
    token_mint: str              # Adresse mint token
    wallet_address: str          # Portefeuille où découvert
    discovered_at: int           # Timestamp découverte
    ata_pubkey: str             # Compte token associé
    initial_balance: float       # Balance initiale
    decimals: int               # Décimales token
    symbol: str                 # Symbole token
    name: str                   # Nom token
    discovery_method: str       # Méthode découverte
    confidence_score: float     # Score confiance découverte
```

### Transaction (modèle complet)

```python
@dataclass  
class Transaction:
    signature: str              # Signature unique
    wallet_address: str         # Adresse portefeuille
    slot: int                   # Slot blockchain
    block_time: int             # Timestamp block
    amount: float               # Montant SOL
    fee: float                  # Frais transaction
    token_mint: Optional[str]   # Mint token impliqué
    token_symbol: Optional[str] # Symbole token
    token_name: Optional[str]   # Nom token
    token_amount: Optional[float] # Quantité token
    price_per_token: Optional[float] # Prix unitaire
    transaction_type: TransactionType # Type transaction
    status: TransactionStatus   # Statut
    source: str                # Source données
    created_at: int            # Timestamp création
```

## Schémas base de données (inférés)

### Table `token_discoveries`
```sql
CREATE TABLE token_discoveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_mint TEXT NOT NULL,
    wallet_address TEXT NOT NULL,
    discovered_at INTEGER NOT NULL,
    ata_pubkey TEXT NOT NULL,
    initial_balance TEXT NOT NULL,    -- Decimal en string
    decimals INTEGER NOT NULL,
    symbol TEXT,
    name TEXT,
    discovery_method TEXT NOT NULL,
    confidence_score REAL DEFAULT 1.0,
    INDEX idx_wallet_discovered (wallet_address, discovered_at),
    INDEX idx_token_wallet (token_mint, wallet_address)
);
```

### Table `transactions`
```sql
CREATE TABLE transactions (
    signature TEXT PRIMARY KEY,
    wallet_address TEXT NOT NULL,
    slot INTEGER NOT NULL,
    block_time INTEGER NOT NULL,
    amount REAL NOT NULL,
    fee REAL NOT NULL,
    token_mint TEXT,
    token_symbol TEXT,
    token_name TEXT,
    token_amount REAL,
    price_per_token REAL,
    transaction_type TEXT NOT NULL,
    status TEXT NOT NULL,
    source TEXT,
    created_at INTEGER NOT NULL,
    INDEX idx_wallet_time (wallet_address, block_time DESC),
    INDEX idx_token_time (token_mint, block_time DESC)
);
```

### Table `token_accounts`
```sql
CREATE TABLE token_accounts (
    wallet_address TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    ata_pubkey TEXT,
    balance TEXT NOT NULL,           -- Decimal en string
    decimals INTEGER NOT NULL,
    last_updated INTEGER NOT NULL,
    is_active INTEGER DEFAULT 1,
    PRIMARY KEY (wallet_address, token_mint)
);
```

### Table `scan_history`
```sql
CREATE TABLE scan_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address TEXT NOT NULL,
    scan_type TEXT NOT NULL,
    total_accounts INTEGER DEFAULT 0,
    new_accounts INTEGER DEFAULT 0,
    scan_duration REAL DEFAULT 0.0,
    completed_at INTEGER NOT NULL,
    success INTEGER DEFAULT 1,
    error_message TEXT,
    INDEX idx_wallet_scan (wallet_address, completed_at DESC)
);
```

## Patterns et logiques métier

### Architecture scanning modulaire
- **Types spécialisés :** full, quick, balances, tokens avec logiques optimisées
- **Pipeline données :** Get accounts → Process tokens → Get transactions → Update balances
- **Batch processing :** Utilisation batch manager pour requêtes RPC efficaces

### Gestion concurrence et cache
- **Protection scans simultanés :** Verrou `_active_scans` par wallet
- **Cache intelligent :** 5 min TTL avec clé `wallet:scan_type`
- **Cleanup automatique :** Expiration cache avec comptage entrées supprimées

### Integration RPC Solana
- **Client flexible :** Support avec/sans batch manager
- **Requêtes optimisées :** `getTokenAccountsByOwner` + `getSignaturesForAddress` + `getTransaction`
- **Parsing robuste :** Navigation JSON structures Solana avec gestion erreurs

### Découverte et persistance
- **Discovery logic :** Comparaison mints existants vs scannés
- **Storage atomique :** INSERT OR REPLACE pour éviter doublons
- **Confidence scoring :** Score 1.0 pour découvertes balance scan

### Performance et résilience
- **Rate limiting :** Délai configurable entre requêtes
- **Timeouts :** Scan timeout 30s par défaut
- **Retry logic :** Max 3 tentatives sur échecs
- **Error isolation :** Échec scan n'affecte pas autres operations

## Gestion d'erreurs et logging

### Préfixes de logs
- 🔍 : Initialisation/scanning
- ✅ : Succès opérations (batch manager, scans)
- 📊 : Résultats/statistiques scanning
- 🎯 : Cache utilization
- 🧹 : Maintenance/cleanup cache
- 🧪 : Tests
- ⚠️ : Avertissements (RPC indisponible, scans en cours)
- ❌ : Erreurs système

### Stratégies d'erreur
- **Graceful degradation :** Fonctionne sans RPC/batch manager
- **Isolation erreurs :** Échec scan wallet n'affecte pas autres
- **Cache fallback :** Utilise cache si RPC échoue
- **Logging détaillé :** Context complet pour debugging

## Exemple de test (section __main__)

**Wallet de test :** "4DdrfGHGdMjCqVbNtXsEEGL1SryTeMo8KMGWWtZyZVFh"

**Tests effectués :**
1. **Types scan :** full, quick, tokens, balances
2. **Résultats :** Count tokens discovered et transactions found
3. **Cache cleanup :** Test nettoyage cache

## Points d'extension

1. **Advanced RPC Batching :** Optimisation requêtes parallèles multiples
2. **Real-time WebSocket :** Écoute changements temps réel
3. **Token Metadata Enhancement :** Enrichissement automatique métadonnées
4. **Transaction Classification :** Analyse avancée types transactions  
5. **Performance Monitoring :** Métriques durées scan, taux succès
6. **Distributed Scanning :** Scaling horizontal workers multiples
7. **Smart Cache Strategies :** Cache adaptatif basé patterns usage
8. **Historical Analysis :** Trends discovery, patterns activité

## Architecture production recommandée

### RPC Load Balancing
```python
class LoadBalancedScanner(WalletScanner):
    def __init__(self, rpc_endpoints: List[str]):
        super().__init__()
        self.rpc_pool = RPCConnectionPool(rpc_endpoints)
        
    def _get_token_accounts(self, wallet_address: str):
        # Utilise connection pool pour load balancing
        return self.rpc_pool.execute_request(
            "getTokenAccountsByOwner", [wallet_address, ...]
        )
```

### Real-time Monitoring
```python
class RealtimeScanner(WalletScanner):
    def __init__(self):
        super().__init__()
        self.websocket_client = SolanaWebSocketClient()
        
    def start_realtime_monitoring(self, wallet_address: str):
        # Subscribe à account changes pour wallet
        self.websocket_client.subscribe_account_changes(
            wallet_address, self._handle_account_change
        )
```

### Advanced Caching
```python
class SmartCacheScanner(WalletScanner):
    def __init__(self):
        super().__init__()
        self.redis_cache = RedisCache()
        self.cache_predictor = CachePredictionModel()
        
    def _should_use_cache(self, wallet_address: str, scan_type: str) -> bool:
        # ML-based cache prediction
        return self.cache_predictor.should_cache(wallet_address, scan_type)
```