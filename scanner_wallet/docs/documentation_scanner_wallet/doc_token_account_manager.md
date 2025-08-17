# Solana Token Account Manager - Documentation Technique

## Vue d'ensemble

Le **Solana Token Account Manager** est un système de gestion des comptes de tokens associés (ATA) pour les portefeuilles Solana. Il permet la découverte, le suivi des balances et la gestion du cycle de vie des comptes de tokens.

## Architecture générale

### Imports et dépendances

**Imports système :**
- `re`, `time`, `sqlite3` - Fonctionnalités système de base
- `typing` - Annotations de type (Dict, List, Optional, Tuple, Any, Union)
- `dataclasses` - Décorateurs pour structures de données
- `decimal.Decimal` - Calculs décimaux précis
- `collections.defaultdict` - Dictionnaires avec valeurs par défaut
- `logging` - Système de logs

**Imports métier avec fallbacks :**
- `core.logger.get_logger` → fallback: `logging.getLogger()`
- `core.database.get_database_manager` → fallback: `None`
- `core.config.get_config` → fallback: `None`
- `models.token.{Token, TokenAccount, TokenDiscovery}` → pas de fallback
- `models.transaction.TransactionType` → pas de fallback
- `utils.helpers.{get_current_timestamp, safe_divide}` → fallbacks simples
- `utils.validators.{validate_wallet_address, validate_token_mint}` → fallbacks basiques
- `constants.{DEFAULT_RPC_ENDPOINTS, TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID}` → valeurs par défaut

**Constantes définies en fallback :**
```python
TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
ASSOCIATED_TOKEN_PROGRAM_ID = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
```

## Classe principale : TokenAccountManager

### Initialisation

**Attributs d'instance :**
- `self.config` - Configuration via `get_config()`
- `self.db_manager` - Gestionnaire de base de données
- `self._mint_cache: Dict[str, Token]` - Cache des informations de tokens
- `self._account_cache: Dict[str, List[TokenAccount]]` - Cache des comptes par wallet
- `self._cache_expiry = 300` - Expiration du cache (5 minutes)

**Log d'initialisation :** "✅ Token Account Manager initialized"

### Méthodes principales

#### 1. `discover_token_accounts(wallet_address: str) -> List[TokenAccount]`

**Fonction :** Découvre tous les comptes de tokens d'un portefeuille

**Processus :**
1. Validation de l'adresse wallet
2. Log : "🔍 Discovering token accounts for wallet: {wallet_address[:8]}..."
3. Vérification du cache (clé = wallet_address)
4. Si cache valide → retour des données cachées avec log "📦 Using cached token accounts"
5. Sinon → interrogation BDD via `_query_existing_accounts()`
6. Si pas de comptes → découverte via `_discover_new_accounts()`
7. Mise en cache des résultats
8. Log final : "✅ Discovered {len(accounts)} token accounts"

**Gestion d'erreur :** Retourne liste vide en cas d'exception

#### 2. `_query_existing_accounts(wallet_address: str) -> List[TokenAccount]`

**Fonction :** Récupère les comptes existants depuis la base de données

**Requête SQL :**
```sql
SELECT wallet_address, ata_pubkey, token_mint, balance, decimals,
       first_seen, last_updated, last_scanned, is_active,
       scan_priority, activity_score, last_activity_time, total_transactions
FROM token_accounts
WHERE wallet_address = ? AND is_active = 1
ORDER BY scan_priority DESC, last_activity_time DESC
```

**Construction objet :** Crée des objets `TokenAccount` avec tous les attributs de la BDD

#### 3. `_discover_new_accounts(wallet_address: str) -> List[TokenAccount]`

**Fonction :** Découvre de nouveaux comptes (simulation pour l'instant)

**Implémentation actuelle :** 
- Log "📊 Simulating token account discovery..."
- Retourne liste vide

#### 4. `create_or_update_token_account()` 

**Signature :** `(wallet_address: str, token_mint: str, ata_pubkey: str, balance: float = 0.0, decimals: int = 9) -> TokenAccount`

**Logique :**
1. Validation des adresses wallet et token mint
2. Récupération timestamp actuel
3. Recherche compte existant via `_get_account()`
4. Si existe → mise à jour balance via `_update_account_balance()`
5. Si nouveau → création objet `TokenAccount` avec :
   - `scan_priority = 5` (priorité haute pour nouveaux comptes)
   - `is_active = True`
   - timestamps first_seen et last_updated
6. Sauvegarde via `_save_account()`

#### 5. `_get_account(wallet_address: str, token_mint: str) -> Optional[TokenAccount]`

**Fonction :** Récupère un compte spécifique depuis la BDD

**Requête SQL :**
```sql
SELECT * FROM token_accounts
WHERE wallet_address = ? AND token_mint = ?
```

#### 6. `_save_account(account: TokenAccount) -> bool`

**Fonction :** Sauvegarde un compte en base

**Requête SQL :**
```sql
INSERT OR REPLACE INTO token_accounts (
    wallet_address, ata_pubkey, token_mint, balance, decimals,
    first_seen, last_updated, last_scanned, is_active,
    scan_priority, activity_score, last_activity_time, total_transactions
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
```

#### 7. Méthodes de gestion des balances

**`update_account_balance(wallet_address, token_mint, new_balance) -> bool`**
- Interface publique pour mise à jour balance

**`_update_account_balance(account, new_balance) -> bool`**
- Mise à jour interne
- Met à jour `last_updated`
- Si changement significatif (> 0.001) :
  - Augmente `activity_score` (max 10, +0.5)
  - Met à jour `last_activity_time`

#### 8. Gestion des priorités de scan

**`mark_account_scanned(wallet_address, token_mint) -> bool`**
- Met à jour `last_scanned`
- Réduit `scan_priority` (minimum 1)

**`boost_account_priority(wallet_address, token_mint, reason) -> bool`**
- Reasons et effets :
  - "new_account" → `scan_priority = 5`
  - "activity" → `scan_priority = min(4, priority + 1)`
  - "large_balance" → `scan_priority = min(4, priority + 2)`

#### 9. Méthodes d'analyse

**`get_wallet_tokens(wallet_address, include_zero=False) -> List[TokenAccount]`**
- Récupère tous les tokens d'un wallet
- Filtre les balances nulles si `include_zero=False`

**`get_top_holdings(wallet_address, limit=10) -> List[TokenAccount]`**
- Tri par balance décroissante
- Limité aux N premiers

**`calculate_portfolio_value(wallet_address) -> Dict[str, Any]`**
- Retourne :
  ```python
  {
      'wallet_address': wallet_address,
      'total_value': float,  # Somme des balances
      'token_count': int,
      'token_values': dict,  # Par token symbol
      'timestamp': int
  }
  ```

#### 10. Activité et historique

**`get_account_activity(wallet_address, token_mint, limit=50) -> List[Dict]`**

**Requête SQL :**
```sql
SELECT t.signature, t.transaction_type, t.token_amount, t.amount, t.block_time, t.fee
FROM transactions t
WHERE t.wallet_address = ? AND t.token_mint = ?
ORDER BY t.block_time DESC LIMIT ?
```

**Format retour :**
```python
[{
    'signature': str,
    'type': str,
    'token_amount': float,
    'sol_amount': float,
    'timestamp': int,
    'fee': float
}, ...]
```

#### 11. Utilitaires de maintenance

**`cleanup_inactive_accounts(wallet_address, inactivity_days=30) -> int`**
- Désactive les comptes :
  - Balance = 0
  - Inactifs depuis N jours
- Met `is_active = 0` et `scan_priority = 0`
- Retourne nombre de comptes affectés

**`get_scan_priority_list(wallet_address, limit=20) -> List[TokenAccount]`**
- Filtre comptes actifs
- Tri par priorité décroissante puis dernière activité
- Limité à N comptes

#### 12. Export et statistiques

**`export_token_data(wallet_address, format_type='json') -> Dict`**
- Structure complète :
  ```python
  {
      'wallet_address': str,
      'timestamp': int,
      'total_accounts': int,
      'accounts': [account.to_dict(), ...],
      'summary': {
          'total_tokens': int,
          'active_tokens': int,
          'total_balance': float,
          'average_priority': float
      }
  }
  ```

**`get_account_statistics(wallet_address) -> Dict`**
- Statistiques détaillées :
  ```python
  {
      'wallet_address': str,
      'total_accounts': int,
      'active_accounts': int,
      'zero_balance_accounts': int,
      'total_balance': float,
      'average_balance': float,
      'min_balance': float,
      'max_balance': float,
      'average_priority': float,
      'average_activity_score': float,
      'tokens_by_priority': dict,  # {priority: count}
      'last_scan_time': int
  }
  ```

## Fonctions utilitaires globales

### `create_ata_address(wallet_address: str, mint_address: str) -> str`
- **Fonction :** Génère l'adresse ATA pour un wallet et mint
- **Implémentation actuelle :** Retourne `f"ATA_{wallet_address[:6]}_{mint_address[:6]}"`
- **Note :** Devrait utiliser le SDK Solana en production

### `get_token_program_for_mint(mint_address: str) -> str`
- **Fonction :** Retourne l'ID du programme token pour un mint
- **Implémentation :** Retourne `TOKEN_PROGRAM_ID` (support Token-2022 futur)

### `get_system_token_stats() -> Dict[str, Any]`
- **Fonction :** Statistiques globales du système

**Requêtes SQL :**

1. Statistiques générales :
```sql
SELECT COUNT(*) as total_accounts,
       COUNT(DISTINCT wallet_address) as unique_wallets,
       COUNT(DISTINCT token_mint) as unique_tokens,
       SUM(balance) as total_balance,
       AVG(balance) as avg_balance
FROM token_accounts WHERE is_active = 1
```

2. Top tokens :
```sql
SELECT token_mint, COUNT(*) as account_count
FROM token_accounts WHERE is_active = 1
GROUP BY token_mint ORDER BY account_count DESC LIMIT 10
```

**Format retour :**
```python
{
    'total_accounts': int,
    'unique_wallets': int,
    'unique_tokens': int,
    'total_balance': float,
    'avg_balance': float,
    'top_tokens': [{'token_mint': str, 'account_count': int}, ...]
}
```

## Structure de données TokenAccount (inférée)

```python
@dataclass
class TokenAccount:
    wallet_address: str          # Adresse du portefeuille propriétaire
    ata_pubkey: str             # Clé publique du compte token associé
    token_mint: str             # Adresse du mint du token
    balance: float              # Balance actuelle
    decimals: int               # Nombre de décimales du token
    first_seen: int             # Timestamp de première découverte
    last_updated: int           # Timestamp de dernière mise à jour
    last_scanned: Optional[int] # Timestamp de dernier scan
    is_active: bool             # Compte actif ou non
    scan_priority: int          # Priorité de scan (1-5)
    activity_score: float       # Score d'activité (0-10)
    last_activity_time: Optional[int]  # Timestamp de dernière activité
    total_transactions: int     # Nombre total de transactions
```

## Schéma de base de données (inféré)

### Table `token_accounts`
```sql
CREATE TABLE token_accounts (
    wallet_address TEXT NOT NULL,
    ata_pubkey TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    balance REAL DEFAULT 0.0,
    decimals INTEGER DEFAULT 9,
    first_seen INTEGER NOT NULL,
    last_updated INTEGER NOT NULL,
    last_scanned INTEGER,
    is_active INTEGER DEFAULT 1,
    scan_priority INTEGER DEFAULT 1,
    activity_score REAL DEFAULT 0.0,
    last_activity_time INTEGER,
    total_transactions INTEGER DEFAULT 0,
    PRIMARY KEY (wallet_address, token_mint)
);
```

### Table `transactions` (utilisée par get_account_activity)
```sql
CREATE TABLE transactions (
    signature TEXT PRIMARY KEY,
    wallet_address TEXT NOT NULL,
    token_mint TEXT,
    transaction_type TEXT,
    token_amount REAL,
    amount REAL,
    block_time INTEGER,
    fee REAL
);
```

## Patterns et logiques métier

### Système de cache
- Cache en mémoire avec expiration (5 minutes)
- Clés : adresses wallet
- Invalide automatiquement après timeout

### Système de priorités
- Nouveaux comptes : priorité 5
- Comptes actifs : priorité 1-4 selon activité
- Comptes scannés : priorité réduite
- Comptes inactifs : priorité 0

### Score d'activité
- Échelle 0-10
- Augmente de 0.5 par changement significatif de balance
- Utilisé pour le tri et les statistiques

### Gestion d'erreurs
- Try/catch sur toutes les opérations BDD
- Logs d'erreur avec préfixe "❌"
- Valeurs par défaut en cas d'échec (listes vides, False, etc.)

### Logging
- Préfixes emoji pour catégoriser :
  - ✅ : Succès/initialisation
  - 🔍 : Découverte/recherche
  - 📦 : Cache
  - 📊 : Statistiques/simulation
  - 🧹 : Nettoyage
  - ❌ : Erreurs

## Points d'extension

1. **Blockchain Integration :** `_discover_new_accounts()` doit être implémentée
2. **Price Integration :** Calculs de valeur USD dans `calculate_portfolio_value()`
3. **Token-2022 Support :** Extension de `get_token_program_for_mint()`
4. **Real ATA Generation :** `create_ata_address()` avec SDK Solana
5. **Advanced Caching :** Système de cache plus sophistiqué avec Redis
6. **Webhooks :** Notifications sur nouveaux tokens ou activité