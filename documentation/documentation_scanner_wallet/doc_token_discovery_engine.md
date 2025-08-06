# Solana Token Discovery Engine - Documentation Technique

## Vue d'ensemble

Le **Solana Token Discovery Engine** est un moteur avancé de découverte de nouveaux tokens et de monitoring des changements de tokens. Il fournit des capacités de découverte automatisée, d'analyse de gems potentielles et de génération de rapports d'insights.

## Architecture générale

### Imports et dépendances

**Imports système :**
- `time`, `json`, `hashlib`, `threading` - Fonctionnalités système
- `typing` - Annotations de type (Dict, List, Optional, Tuple, Any, Set)
- `dataclasses.dataclass` - Décorateur pour structures de données
- `datetime.{datetime, timedelta}` - Gestion des dates
- `logging` - Système de logs

**Imports métier avec fallbacks :**
- `core.logger.get_logger` → fallback: `logging.getLogger()`
- `core.database.get_database_manager` → fallback: `None`
- `core.config.get_config` → fallback: `None`
- `models.token.{Token, TokenAccount, TokenDiscovery}` → fallbacks: classes vides
- `models.transaction.Transaction` → fallback: classe vide
- `utils.helpers.{get_current_timestamp, safe_divide}` → fallbacks simples
- `utils.validators.{validate_wallet_address, validate_token_mint}` → fallbacks basiques
- `token.cache_manager.{get_token_metadata_cache, get_token_account_cache}` → pas de fallback

## Structures de données

### DiscoveryParams

```python
@dataclass
class DiscoveryParams:
    min_balance: float = 0.000001      # Balance minimale pour considérer un token
    max_age_hours: int = 168           # Âge maximum (1 semaine)
    include_zero_balance: bool = False # Inclure tokens avec balance nulle
    include_verified_only: bool = False # Tokens vérifiés uniquement
    scan_depth: int = 3                # Profondeur de scan
    priority_boost: float = 1.0        # Multiplicateur de priorité
```

### DiscoveryResult

```python
@dataclass
class DiscoveryResult:
    wallet_address: str              # Adresse du portefeuille scanné
    new_tokens: List[TokenDiscovery] # Nouveaux tokens découverts
    updated_tokens: List[TokenAccount] # Tokens existants mis à jour
    removed_tokens: List[str]        # Tokens supprimés (mints)
    scan_duration: float             # Durée du scan en secondes
    total_scanned: int               # Nombre total de tokens scannés
    confidence_score: float          # Score de confiance (0-1)
    metadata: Dict[str, Any]         # Métadonnées additionnelles
```

## Classe principale : TokenDiscoveryEngine

### Initialisation

**Attributs d'instance :**
- `self.config` - Configuration via `get_config()`
- `self.db_manager` - Gestionnaire de base de données
- `self.discovery_params = DiscoveryParams()` - Paramètres par défaut
- `self.scan_threads = {}` - Dictionnaire des threads de scan
- `self.scan_lock = threading.RLock()` - Verrou pour thread-safety
- `self.metadata_cache` - Cache métadonnées via `get_token_metadata_cache()`
- `self.account_cache` - Cache comptes via `get_token_account_cache()`

**Log d'initialisation :** "✅ Token Discovery Engine initialized"

### Méthodes principales

#### 1. `discover_new_tokens(wallet_address: str, params: Optional[DiscoveryParams] = None) -> DiscoveryResult`

**Fonction :** Découvre de nouveaux tokens pour un portefeuille

**Processus complet :**
1. **Validation et initialisation :**
   - Validation adresse wallet
   - Utilisation paramètres par défaut si non fournis
   - Mesure temps de début
   - Log : "🔍 Starting token discovery for {wallet_address[:8]}..."

2. **Récupération état existant :**
   - Appel `_get_existing_accounts(wallet_address)`
   - Création set `existing_mints` des mints existants

3. **Découverte nouveaux comptes :**
   - Appel `_discover_accounts(wallet_address, params)`
   - Retourne liste de dictionnaires avec données de comptes

4. **Analyse des changements :**
   - **Nouveaux tokens :** Si `token_mint` pas dans `existing_mints`
     - Création `TokenDiscovery` via `_create_discovery()`
     - Création `TokenAccount` via `_create_token_account()`
     - Mise en cache métadonnées via `_cache_token_metadata()`
   - **Tokens mis à jour :** Si existe et balance > 0
     - Appel `_update_existing_account()`
   - **Tokens supprimés :** Via `_find_removed_tokens()`

5. **Calcul de confiance :**
   - Appel `_calculate_confidence_score(new_tokens, updated_tokens, params)`

6. **Construction résultat :**
   - Création objet `DiscoveryResult` avec toutes les données
   - Métadonnées incluent : 'discovery_method', 'scan_depth', 'parameters'

7. **Log final :**
   - "✅ Discovery complete: {len(new_tokens)} new, {len(updated_tokens)} updated, {len(removed_tokens)} removed"

**Gestion d'erreur :** Retourne `DiscoveryResult` avec listes vides et métadonnées d'erreur

#### 2. `_get_existing_accounts(wallet_address: str) -> List[TokenAccount]`

**Fonction :** Récupère les comptes de tokens existants depuis la base de données

**Requête SQL :**
```sql
SELECT * FROM token_accounts
WHERE wallet_address = ? AND is_active = 1
```

**Construction objet :** Crée objets `TokenAccount` avec :
- `wallet_address`, `ata_pubkey`, `token_mint`
- `balance` (float), `decimals` (int)
- `first_seen`, `last_updated` (int)
- `is_active` (bool), `scan_priority` (int)

#### 3. `_discover_accounts(wallet_address: str, params: DiscoveryParams) -> List[Dict[str, Any]]`

**Fonction :** Découvre comptes de tokens depuis blockchain ou base de données

**Implémentation actuelle :** Simulation basée sur transactions récentes

**Requête SQL :**
```sql
SELECT DISTINCT token_mint, token_symbol, token_name, decimals
FROM transactions
WHERE wallet_address = ?
    AND token_mint IS NOT NULL
    AND block_time > ?
ORDER BY block_time DESC
LIMIT 1000
```

**Paramètres :**
- `block_time > current_timestamp - (params.max_age_hours * 3600)`

**Format retour :** Liste de dictionnaires :
```python
[{
    'token_mint': str,
    'token_symbol': str,
    'token_name': str,
    'decimals': int,
    'balance': float,  # 0.0 par défaut, serait récupéré de la blockchain
    'ata_pubkey': str  # Format : "ATA_{wallet[:6]}_{mint[:6]}"
}, ...]
```

#### 4. Méthodes de création d'objets

**`_create_discovery(account: Dict[str, Any], wallet_address: str) -> TokenDiscovery`**

Crée objet `TokenDiscovery` avec :
```python
TokenDiscovery(
    token_mint=account['token_mint'],
    wallet_address=wallet_address,
    discovered_at=get_current_timestamp(),
    ata_pubkey=account['ata_pubkey'],
    initial_balance=account['balance'],
    decimals=account['decimals'],
    symbol=account['token_symbol'],
    name=account['token_name'],
    discovery_method="transaction_scan",
    confidence_score=0.8
)
```

**`_create_token_account(account: Dict[str, Any], wallet_address: str) -> TokenAccount`**

Crée objet `TokenAccount` avec :
```python
TokenAccount(
    wallet_address=wallet_address,
    ata_pubkey=account['ata_pubkey'],
    token_mint=account['token_mint'],
    balance=account['balance'],
    decimals=account['decimals'],
    first_seen=get_current_timestamp(),
    last_updated=get_current_timestamp(),
    is_active=True,
    scan_priority=5  # Priorité haute pour nouvelles découvertes
)
```

#### 5. `_find_removed_tokens(wallet_address, existing, discovered) -> List[str]`

**Fonction :** Identifie tokens supprimés (balance nulle)

**Logique :**
1. Création set `discovered_mints` des mints découverts
2. Parcours comptes existants
3. Si `token_mint` pas dans `discovered_mints` → ajout à `removed`
4. Retour liste des mints supprimés

#### 6. `_calculate_confidence_score(new_tokens, updated_tokens, params) -> float`

**Fonction :** Calcule score de confiance pour la découverte

**Facteurs considérés :**
- **Nombre nouveaux tokens :** `min(len(new_tokens) / 10, 1.0)`
- **Complétude du scan :** `0.9` (assumption)
- **Tokens vérifiés uniquement :** `0.95` si `params.include_verified_only`

**Calcul final :** Moyenne des facteurs via `safe_divide(sum(factors), len(factors))`

#### 7. `_cache_token_metadata(account: Dict[str, Any]) -> None`

**Fonction :** Met en cache les métadonnées de token

**Actions :**
1. Création objet `Token` avec données du compte
2. Appel `self.metadata_cache.cache_token_metadata(token)`

### Fonctionnalités avancées

#### 8. `scan_for_gems(wallet_address: str, min_balance: float = 1000.0, max_age_hours: int = 24) -> List[TokenDiscovery]`

**Fonction :** Scanne pour des gems potentielles (tokens sous-évalués)

**Processus :**
1. Appel `discover_new_tokens(wallet_address)`
2. Pour chaque découverte :
   - Test `_is_potential_gem(discovery, min_balance, max_age_hours)`
   - Si gem potentielle → calcul `gem_score` via `_calculate_gem_score()`
   - Ajout score dans `discovery.metadata['gem_score']`
3. Retour liste des gems

#### 9. `_is_potential_gem(discovery, min_balance, max_age_hours) -> bool`

**Fonction :** Détermine si token est gem potentielle

**Critères évalués :**
- **Nouveauté :** `discovery.age_hours < max_age_hours`
- **Balance :** `discovery.initial_balance >= min_balance`
- **Market cap faible :** `True` (placeholder, nécessiterait données de prix)

**Décision :** Retourne `True` si au moins 2 critères satisfaits

#### 10. `_calculate_gem_score(discovery: TokenDiscovery) -> float`

**Fonction :** Calcule score potentiel de gem (0-1)

**Facteurs de score :**
- **Nouveauté :** +0.3 si âge < 24h
- **Balance importante :** +0.4 si balance > 10000
- **Symbole court :** +0.1 si symbole ≤ 5 caractères
- **Nom analyse :** +0.2 si nom ne contient pas "token"

**Plafond :** `min(score, 1.0)`

### Monitoring et analyse

#### 11. `monitor_token_changes(wallet_address: str, since_timestamp: int) -> List[Dict[str, Any]]`

**Fonction :** Monitore changements de balance des tokens

**Requête SQL complexe :**
```sql
SELECT 
    ta.token_mint,
    ta.token_symbol,
    ta.balance as current_balance,
    t.token_amount as transaction_amount,
    t.transaction_type,
    t.block_time
FROM token_accounts ta
JOIN transactions t ON ta.token_mint = t.token_mint
WHERE ta.wallet_address = ?
    AND t.block_time > ?
    AND ta.is_active = 1
ORDER BY t.block_time DESC
```

**Format retour :**
```python
[{
    'token_mint': str,
    'symbol': str,
    'current_balance': float,
    'transaction_amount': float,
    'transaction_type': str,
    'timestamp': int
}, ...]
```

#### 12. `get_discovery_statistics(wallet_address: str, days: int = 30) -> Dict[str, Any]`

**Fonction :** Récupère statistiques de découverte

**Requête principale :**
```sql
SELECT 
    COUNT(*) as total_discoveries,
    AVG(confidence_score) as avg_confidence,
    COUNT(CASE WHEN confidence_score > 0.8 THEN 1 END) as high_confidence,
    COUNT(DISTINCT token_mint) as unique_tokens
FROM token_accounts ta
WHERE ta.wallet_address = ?
    AND ta.first_seen > ?
```

**Requête top tokens :**
```sql
SELECT token_mint, symbol, COUNT(*) as discovery_count
FROM token_accounts ta
WHERE ta.wallet_address = ?
    AND ta.first_seen > ?
GROUP BY token_mint, symbol
ORDER BY discovery_count DESC
LIMIT 10
```

**Structure retour :**
```python
{
    'total_discoveries': int,
    'avg_confidence': float,
    'high_confidence': int,
    'unique_tokens': int,
    'top_discovered': [
        {
            'token_mint': str,
            'symbol': str,
            'discovery_count': int
        }, ...
    ]
}
```

#### 13. `generate_discovery_report(wallet_address: str) -> Dict[str, Any]`

**Fonction :** Génère rapport complet de découverte

**Structure rapport :**
```python
{
    'wallet_address': str,
    'timestamp': int,
    'discoveries': List[Any],     # Vide dans implémentation actuelle
    'recommendations': List[str], # Recommandations générées
    'insights': Dict[str, Any]    # Métriques et analyses
}
```

**Insights calculés :**
- **Stats découverte :** Via `get_discovery_statistics(wallet_address, days=7)`
- **Diversité tokens :** `unique_mints / total_mints` si tokens présents
- **Priorité moyenne :** Moyenne `scan_priority` de tous comptes

**Recommandations automatiques :**
- Si `total_discoveries > 10` : "High discovery rate - consider automated monitoring"
- Si `avg_confidence < 0.7` : "Low confidence scores - review discovery parameters"
- Si `current_count > 50` : "Large token portfolio - consider risk assessment"

#### 14. `batch_discover_wallets(wallet_addresses: List[str], params: Optional[DiscoveryParams] = None) -> Dict[str, DiscoveryResult]`

**Fonction :** Découverte en lot pour plusieurs portefeuilles

**Processus :**
1. Itération sur chaque adresse
2. Validation adresse via `validate_wallet_address()`
3. Si valide → appel `discover_new_tokens()`
4. Si invalide → création `DiscoveryResult` avec erreur
5. Retour dictionnaire `{wallet_address: DiscoveryResult}`

## Instances et fonctions globales

### Instance globale
```python
discovery_engine = TokenDiscoveryEngine()
```

### Fonctions de convenance

#### `discover_tokens(wallet_address: str) -> DiscoveryResult`
**Wrapper :** `discovery_engine.discover_new_tokens(wallet_address)`

#### `scan_for_gems(wallet_address: str) -> List[TokenDiscovery]`
**Wrapper :** `discovery_engine.scan_for_gems(wallet_address)`

#### `get_discovery_report(wallet_address: str) -> Dict[str, Any]`
**Wrapper :** `discovery_engine.generate_discovery_report(wallet_address)`

## Structures de données inférées

### TokenDiscovery (inférée)
```python
@dataclass
class TokenDiscovery:
    token_mint: str              # Adresse du mint
    wallet_address: str          # Portefeuille propriétaire
    discovered_at: int           # Timestamp découverte
    ata_pubkey: str             # Adresse compte token associé
    initial_balance: float       # Balance initiale à la découverte
    decimals: int               # Décimales du token
    symbol: str                 # Symbole du token
    name: str                   # Nom du token
    discovery_method: str       # Méthode de découverte
    confidence_score: float     # Score de confiance
    metadata: Dict[str, Any]    # Métadonnées additionnelles
    
    @property
    def age_hours(self) -> int:
        return (get_current_timestamp() - self.discovered_at) // 3600
```

## Schéma de base de données (inféré)

### Table `token_accounts` (utilisée pour état existant)
```sql
CREATE TABLE token_accounts (
    wallet_address TEXT NOT NULL,
    ata_pubkey TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    balance REAL DEFAULT 0.0,
    decimals INTEGER DEFAULT 9,
    first_seen INTEGER NOT NULL,
    last_updated INTEGER NOT NULL,
    is_active INTEGER DEFAULT 1,
    scan_priority INTEGER DEFAULT 1,
    PRIMARY KEY (wallet_address, token_mint)
);
```

### Table `transactions` (utilisée pour découverte)
```sql
CREATE TABLE transactions (
    wallet_address TEXT NOT NULL,
    token_mint TEXT,
    token_symbol TEXT,
    token_name TEXT,
    decimals INTEGER,
    token_amount REAL,
    transaction_type TEXT,
    block_time INTEGER,
    INDEX idx_discovery (wallet_address, block_time, token_mint)
);
```

## Patterns et logiques métier

### Méthode de découverte
- **Source primaire :** Analyse des transactions récentes
- **Période :** Configurable via `max_age_hours` (défaut 1 semaine)
- **Simulation blockchain :** Implémentation actuelle basée BDD, extension blockchain future

### Scoring et confiance
- **Score découverte :** Basé sur nombre tokens, qualité scan, paramètres
- **Score gem :** Facteurs nouveauté, balance, analyse symbole/nom
- **Seuils configurables :** Balance minimale, âge maximum

### Gestion d'état
- **États tokens :** nouveau, mis à jour, supprimé
- **Cache integration :** Métadonnées automatiquement cachées
- **Priorité découvertes :** Nouveaux tokens = priorité 5

### Thread safety
- **Verrou réentrant :** `threading.RLock()` pour opérations concurrentes
- **Dictionnaire threads :** Suivi des scans en cours
- **Protection cache :** Via caches thread-safe

### Analyse de gems
- **Critères multiples :** Âge, balance, market cap
- **Scoring composite :** Facteurs pondérés (nouveauté 30%, balance 40%, etc.)
- **Seuils ajustables :** Balance minimum, âge maximum

### Reporting et insights
- **Métriques automatiques :** Diversité, moyenne priorité, découvertes
- **Recommandations intelligentes :** Basées sur patterns détectés
- **Historique :** Analyse sur périodes configurables

## Gestion d'erreurs et logging

### Préfixes de logs
- ✅ : Succès/initialisation
- 🔍 : Découverte/recherche
- 📊 : Statistiques/résultats
- 💎 : Gems/analyses spéciales
- 📋 : Rapports
- ❌ : Erreurs

### Stratégie d'erreur
- **Graceful degradation :** Retour structures vides plutôt qu'exceptions
- **Métadonnées d'erreur :** Inclusion erreurs dans résultats
- **Logs détaillés :** Contexte complet pour debugging

## Exemple de test (section __main__)

**Wallet de test :** "4DdrfGHGdMjCqVbNtXsEEGL1SryTeMo8KMGWWtZyZVFh"

**Tests effectués :**
1. **Découverte basique :** `discover_tokens(test_wallet)`
2. **Scan gems :** `scan_for_gems(test_wallet)`
3. **Rapport :** `get_discovery_report(test_wallet)`

**Outputs attendus :**
- "📊 Discovery result: X new tokens"
- "💎 Found X potential gems" 
- "📋 Discovery report generated"

## Points d'extension

1. **Blockchain Integration :** Remplacement simulation par vraies requêtes RPC Solana
2. **Price Integration :** Données prix temps réel pour calculs gem score
3. **ML Scoring :** Modèles apprentissage automatique pour prédiction gems
4. **Real-time Monitoring :** WebSockets pour notifications changements
5. **Advanced Analytics :** Corrélations, patterns temporels, clustering
6. **Risk Assessment :** Évaluation risques basée historique, liquidité
7. **Portfolio Optimization :** Recommandations diversification automatique
8. **Social Sentiment :** Intégration signaux sociaux pour scoring