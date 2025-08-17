# Solana Balance Tracker - Documentation Technique

## Vue d'ensemble

Le **Solana Balance Tracker** est un module de suivi des changements de balances en temps réel à travers les portefeuilles surveillés. Il fournit un système de monitoring complet des balances de tokens avec détection de changements, métriques et historique.

## Architecture générale

### Imports et dépendances

**Imports système :**
- `time`, `threading` - Temps et gestion concurrence
- `typing` - Annotations de type (Dict, List, Optional, Tuple, Set)
- `dataclasses` - Structures de données (dataclass, field)
- `decimal.Decimal` - Calculs décimaux précis
- `datetime.datetime` - Gestion dates

**Imports métier avec fallbacks :**
- `core.logger.get_logger` → fallback: `logging.getLogger()`
- `core.database.get_database_manager` → fallback: `None`
- `core.config.get_config` → fallback: `None`
- `models.transaction.{Transaction, TransactionType, TransactionStatus}` → fallback: classes enum
- `models.token.{Token, TokenAccount}` → pas de fallback
- `utils.helpers.{safe_divide, get_current_timestamp}` → pas de fallback
- `utils.validators.DataValidator` → pas de fallback

**Fallbacks classes :**
```python
class TransactionType:
    BUY = "buy"
    SELL = "sell"
    TRANSFER = "transfer"

class TransactionStatus:
    SUCCESS = "success"
    FAILED = "failed"
```

## Structure de données

### BalanceChange

```python
@dataclass
class BalanceChange:
    wallet_address: str                    # Adresse portefeuille
    token_mint: str                       # Adresse mint token
    ata_pubkey: str                       # Clé publique compte token associé
    pre_balance: Decimal                  # Balance avant changement
    post_balance: Decimal                 # Balance après changement
    balance_change: Decimal               # Delta de changement
    timestamp: int                        # Timestamp du changement
    token_symbol: str = "UNKNOWN"        # Symbole token
    token_name: str = "Unknown Token"    # Nom token
    decimals: int = 9                     # Décimales token
    transaction_signature: Optional[str] = None  # Signature transaction (optionnel)
    change_type: Optional[TransactionType] = None # Type changement (optionnel)
```

#### Propriétés calculées

**`display_change -> Decimal`**
- **Fonction :** Formate changement balance pour affichage
- **Calcul :** `safe_divide(self.balance_change, 10**self.decimals)`

**`is_significant -> bool`**
- **Fonction :** Vérifie si changement est significatif
- **Critère :** `abs(self.display_change) > Decimal('0.000001')`

## Classe principale : BalanceTracker

### Initialisation

**Attributs d'instance :**
- `self.db_manager` - Gestionnaire base de données
- `self.config` - Configuration système
- `self.validator = DataValidator()` - Validateur données

**Stockage thread-safe :**
- `self._lock = threading.Lock()` - Verrou pour opérations atomiques
- `self._wallet_balances: Dict[str, Dict[str, Decimal]]` - Balances par wallet puis par token
- `self._last_scan_time: Dict[str, int]` - Timestamp dernier scan par wallet
- `self._pending_changes: List[BalanceChange]` - Changements en attente

**Métriques de suivi :**
```python
self._metrics = {
    'total_changes_detected': 0,   # Nombre total changements détectés
    'total_wallets_tracked': 0,    # Nombre wallets suivis
    'last_update': 0               # Timestamp dernière mise à jour
}
```

**Log d'initialisation :** "🔍 Balance tracker initialized"

### Gestion des wallets surveillés

#### 1. `track_wallet(wallet_address: str) -> bool`

**Fonction :** Ajoute un portefeuille au suivi

**Processus :**
1. **Validation :** Vérification adresse via `self.validator.validate_address()`
2. **Ajout tracking :**
   - Initialisation `_wallet_balances[wallet_address] = {}`
   - Initialisation `_last_scan_time[wallet_address] = 0`
   - Incrémentation `metrics['total_wallets_tracked']`
3. **Chargement balances existantes :** Appel `_load_existing_balances(wallet_address)`

**Thread-safety :** Opération sous verrou `with self._lock:`

**Log :** "✅ Tracking wallet: {wallet_address}"

#### 2. `untrack_wallet(wallet_address: str) -> bool`

**Fonction :** Retire un portefeuille du suivi

**Actions sous verrou :**
- Suppression de `_wallet_balances`
- Suppression de `_last_scan_time`
- Décrémentation `metrics['total_wallets_tracked']`

**Log :** "✅ Stopped tracking wallet: {wallet_address}"

#### 3. `_load_existing_balances(wallet_address: str)`

**Fonction :** Charge balances existantes depuis la base de données

**Requête SQL :**
```sql
SELECT ta.token_mint, ta.balance, t.decimals, t.symbol, t.name
FROM token_accounts ta
JOIN tokens t ON ta.token_mint = t.address
WHERE ta.wallet_address = ? AND ta.is_active = 1
```

**Stockage :** Balances > 0 stockées dans `_wallet_balances[wallet_address][token_mint]`

### Scan et détection de changements

#### 4. `scan_balance_changes(wallet_address: str) -> List[BalanceChange]`

**Fonction :** Scanne changements de balance pour un portefeuille spécifique

**Processus complet :**

1. **Validation :** Vérification wallet dans `_wallet_balances`

2. **Récupération balances actuelles :**
   - `_get_current_token_accounts(wallet_address)` → Liste mints
   - `_get_current_balances(wallet_address, current_accounts)` → Dict[mint, balance]

3. **Comparaison avec balances stockées :**
   ```python
   stored_balances = self._wallet_balances.get(wallet_address, {})
   for mint, new_balance in current_balances.items():
       old_balance = stored_balances.get(mint, Decimal('0'))
       if old_balance != new_balance:
           # Création BalanceChange
   ```

4. **Construction BalanceChange :**
   - Calcul delta : `new_balance - old_balance`
   - Enrichissement métadonnées via `_get_token_info(mint)`
   - Filtrage changements significatifs via `is_significant`

5. **Mise à jour état :**
   - Balances stockées : `_wallet_balances[wallet_address] = current_balances`
   - Timestamp : `_last_scan_time[wallet_address] = get_current_timestamp()`
   - Métriques : `_metrics['total_changes_detected'] += len(changes)`

6. **Persistance :** `_store_balance_changes(changes)` si changements détectés

**Log :** "🔍 Scanned {wallet_address}: {len(changes)} changes detected"

#### 5. `_get_current_token_accounts(wallet_address: str) -> List[str]`

**Fonction :** Récupère comptes token actuels (implémentation simplifiée)

**Note :** Devrait intégrer client RPC Solana, retourne liste vide en développement

#### 6. `_get_current_balances(wallet_address, token_mints) -> Dict[str, Decimal]`

**Fonction :** Récupère balances actuelles pour comptes token

**Note :** Devrait intégrer client RPC Solana, retourne dict vide en développement

#### 7. `_get_token_info(token_mint: str) -> Dict[str, Any]`

**Fonction :** Récupère métadonnées token depuis BDD

**Requête SQL :**
```sql
SELECT symbol, name, decimals FROM tokens WHERE address = ?
```

**Retour par défaut :**
```python
{'symbol': 'UNKNOWN', 'name': 'Unknown Token', 'decimals': 9}
```

### Persistance des données

#### 8. `_store_balance_changes(changes: List[BalanceChange]) -> bool`

**Fonction :** Stocke changements détectés en base de données

**Opérations BDD :**

1. **Insertion changements :**
   ```sql
   INSERT INTO wallet_balance_changes 
   (wallet_address, token_mint, ata_pubkey, pre_balance, post_balance, 
    balance_change, timestamp, token_symbol, token_name, decimals)
   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
   ```

2. **Mise à jour comptes token :**
   ```sql
   INSERT OR REPLACE INTO token_accounts 
   (wallet_address, token_mint, balance, last_updated)
   VALUES (?, ?, ?, ?)
   ```

**Log :** "💾 Stored {len(changes)} balance changes"

### Scan globaux et métriques

#### 9. `scan_all_wallets() -> Dict[str, List[BalanceChange]]`

**Fonction :** Scanne tous les wallets suivis

**Processus :**
1. Copie thread-safe liste wallets : `list(self._wallet_balances.keys())`
2. Appel `scan_balance_changes()` pour chaque wallet
3. Agrégation résultats par wallet
4. Mise à jour `metrics['last_update']`

**Log :** "🔍 Scanned {len(wallets)} wallets, {total_changes} total changes"

#### 10. `get_wallet_summary(wallet_address: str) -> Dict[str, Any]`

**Fonction :** Résumé complet balance portefeuille

**Métriques calculées :**
```python
{
    'wallet_address': str,
    'total_tokens': int,              # Nombre tokens total
    'active_tokens': int,             # Nombre tokens avec balance > 0
    'last_scan_time': int,            # Timestamp dernier scan
    'hours_since_scan': float,        # Heures depuis dernier scan
    'balances': Dict[str, str],       # Balances par mint (format string)
    'total_value': str                # Valeur totale USD (placeholder)
}
```

#### 11. `get_system_metrics() -> Dict[str, Any]`

**Fonction :** Métriques système globales

**Métriques retournées :**
```python
{
    'total_changes_detected': int,
    'total_wallets_tracked': int,
    'last_update': int,
    'wallets_tracked': List[str],     # Liste adresses wallets
    'uptime_hours': float            # Durée fonctionnement
}
```

### Historique et requêtes

#### 12. `get_recent_changes(wallet_address: str = None, limit: int = 50) -> List[BalanceChange]`

**Fonction :** Récupère changements récents depuis BDD ou mémoire

**Requête SQL (si BDD disponible) :**
```sql
SELECT * FROM wallet_balance_changes
WHERE 1=1
[AND wallet_address = ?]  -- Si wallet spécifié
ORDER BY timestamp DESC 
LIMIT ?
```

**Reconstruction objets :** Création `BalanceChange` depuis lignes BDD avec conversion `Decimal`

**Fallback :** Si pas de BDD, retour depuis `_pending_changes`

## Classe BalanceTrackerManager (Singleton)

### Pattern Singleton thread-safe

```python
class BalanceTrackerManager:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
```

### Méthodes de gestion

#### `__init__()`
**Initialisation :** `self.tracker = BalanceTracker()` si pas déjà initialisé

#### `start_tracking(wallet_addresses: List[str]) -> Dict[str, bool]`
**Fonction :** Démarre suivi multiple wallets
**Retour :** `{wallet_address: success_bool}` pour chaque wallet

#### `stop_tracking(wallet_addresses: List[str]) -> Dict[str, bool]`
**Fonction :** Arrête suivi multiple wallets
**Retour :** `{wallet_address: success_bool}` pour chaque wallet

#### `scan_all() -> Dict[str, List[BalanceChange]]`
**Wrapper :** `self.tracker.scan_all_wallets()`

#### `get_summary() -> Dict[str, Any]`
**Fonction :** Résumé système complet
```python
{
    'metrics': dict,              # Métriques système
    'recent_changes': List[BalanceChange]  # 10 changements récents
}
```

## Fonctions globales

### Instances globales

#### `get_balance_tracker() -> BalanceTracker`
**Singleton simple :** Instance globale `BalanceTracker`

#### `get_balance_tracker_manager() -> BalanceTrackerManager`
**Singleton thread-safe :** Instance `BalanceTrackerManager`

## Schémas base de données (inférés)

### Table `wallet_balance_changes` (historique changements)
```sql
CREATE TABLE wallet_balance_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    ata_pubkey TEXT NOT NULL,
    pre_balance TEXT NOT NULL,        -- Decimal stocké en string
    post_balance TEXT NOT NULL,       -- Decimal stocké en string
    balance_change TEXT NOT NULL,     -- Decimal stocké en string
    timestamp INTEGER NOT NULL,
    token_symbol TEXT DEFAULT 'UNKNOWN',
    token_name TEXT DEFAULT 'Unknown Token',
    decimals INTEGER DEFAULT 9,
    transaction_signature TEXT,
    change_type TEXT,
    INDEX idx_wallet_time (wallet_address, timestamp),
    INDEX idx_timestamp (timestamp DESC)
);
```

### Table `token_accounts` (états actuels)
```sql
CREATE TABLE token_accounts (
    wallet_address TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    ata_pubkey TEXT,
    balance TEXT NOT NULL,           -- Decimal stocké en string
    decimals INTEGER DEFAULT 9,
    is_active INTEGER DEFAULT 1,
    last_updated INTEGER NOT NULL,
    PRIMARY KEY (wallet_address, token_mint)
);
```

### Table `tokens` (métadonnées)
```sql
CREATE TABLE tokens (
    address TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    decimals INTEGER DEFAULT 9,
    -- autres métadonnées...
);
```

## Patterns et logiques métier

### Gestion thread-safety
- **Verrou unique :** `threading.Lock()` pour toutes opérations critiques
- **Copies locales :** Éviter accès concurrent aux structures partagées
- **Opérations atomiques :** Modifications état sous verrou

### Détection changements
- **Comparaison exacte :** `old_balance != new_balance` avec `Decimal`
- **Filtrage significativité :** Changements > 0.000001 seulement
- **Enrichissement automatique :** Métadonnées token depuis BDD

### Stockage et précision
- **Decimal partout :** Précision exacte pour calculs financiers
- **Serialization string :** Stockage BDD en format string pour préserver précision
- **Reconstitution :** `Decimal(str(value))` lors récupération BDD

### Architecture modulaire
- **Séparation responsabilités :** Tracker vs Manager vs instances globales
- **Extensibilité :** Méthodes `_get_current_*` pour intégration RPC future
- **Fallbacks :** Fonctionnement dégradé si BDD indisponible

### Monitoring et métriques
- **Compteurs globaux :** Changements détectés, wallets suivis
- **Timestamps :** Dernier scan par wallet, dernière mise à jour système
- **Historique :** Changements persistés avec métadonnées complètes

## Gestion d'erreurs et logging

### Préfixes de logs
- 🔍 : Initialisation/scanning
- ✅ : Succès opérations
- 📊 : Résumés/statistiques
- 📈 : Métriques système
- 💾 : Persistance données
- 🧪 : Tests
- ⚠️ : Avertissements
- ❌ : Erreurs

### Stratégies d'erreur
- **Graceful degradation :** Fonctionnement même si BDD indisponible
- **Logging détaillé :** Context complet pour debugging
- **Isolation erreurs :** Échec sur un wallet n'affecte pas autres
- **Valeurs par défaut :** Métadonnées token par défaut si non trouvées

## Exemple de test (section __main__)

**Test wallet :** "4DdrfGHGdMjCqVbNtXsEEGL1SryTeMo8KMGWWtZyZVFh"

**Tests effectués :**
1. **Initialisation :** `get_balance_tracker()`
2. **Ajout suivi :** `tracker.track_wallet(test_wallet)`
3. **Résumé wallet :** `tracker.get_wallet_summary(test_wallet)`
4. **Métriques système :** `tracker.get_system_metrics()`

## Points d'extension

1. **RPC Integration :** Intégration client Solana RPC pour balances temps réel
2. **WebSocket Monitoring :** Écoute changements en temps réel via WebSockets
3. **Price Integration :** Calcul valeurs USD avec données prix
4. **Alert System :** Notifications sur changements significatifs
5. **Historical Analysis :** Analyses tendances et patterns changements
6. **Performance Optimization :** Batch processing, cache intelligent
7. **Multi-chain Support :** Extension autres blockchains
8. **Advanced Metrics :** Volatilité, corrélations, prédictions

## Architecture future recommandée

### Integration RPC Solana
```python
def _get_current_balances(self, wallet_address: str, token_mints: List[str]) -> Dict[str, Decimal]:
    # Integration avec solana-py ou solders
    from solana.rpc.api import Client
    client = Client("https://api.mainnet-beta.solana.com")
    
    balances = {}
    for mint in token_mints:
        # Récupération balance via RPC
        balance = client.get_token_account_balance(ata_address)
        balances[mint] = Decimal(balance.value.amount) / (10 ** balance.value.decimals)
    
    return balances
```

### Monitoring temps réel
```python
def start_realtime_monitoring(self):
    # WebSocket connection pour events blockchain
    # Détection changements instantanée vs polling
    pass
```

### Alertes intelligentes
```python
def setup_alerts(self, wallet_address: str, thresholds: Dict[str, Decimal]):
    # Configuration alertes par token/montant
    # Notifications push, email, webhooks
    pass
```