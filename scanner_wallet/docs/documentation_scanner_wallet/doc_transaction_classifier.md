# Solana Transaction Classifier - Documentation Technique

## Vue d'ensemble

Le **Solana Transaction Classifier** est un module de classification avancée de transactions avec reconnaissance de patterns de type ML et analyse contextuelle. Il utilise une approche multi-couches pour classifier les transactions Solana avec scoring de confiance et analyse de preuves.

## Architecture générale

### Imports et dépendances

**Imports système :**
- `re`, `json`, `time` - Expressions régulières, JSON, temps
- `typing` - Annotations de type (Dict, List, Optional, Tuple, Any, Set)
- `dataclasses` - Structures de données (dataclass, field)
- `datetime.datetime` - Gestion dates
- `decimal.Decimal` - Calculs décimaux précis
- `enum.Enum` - Énumérations
- `logging` - Système de logs

**Imports métier avec fallbacks :**
- `core.logger.get_logger` → fallback: `logging.getLogger()`
- `core.database.get_database_manager` → fallback: `None`
- `core.config.get_config` → fallback: `None`
- `models.transaction.{Transaction, TransactionType, TransactionStatus}` → fallback: classe enum TransactionType
- `models.token.Token` → pas de fallback
- `utils.helpers.{get_current_timestamp, safe_divide}` → pas de fallback
- `utils.constants.SOLANA_PROGRAM_IDS` → pas de fallback

**Fallback TransactionType :**
```python
class TransactionType:
    BUY = "buy"
    SELL = "sell"
    TRANSFER = "transfer"
    SWAP = "swap"
    STAKE = "stake"
    UNSTAKE = "unstake"
```

## Énumérations et structures de données

### ClassificationConfidence

```python
class ClassificationConfidence(Enum):
    HIGH = 0.95      # Confiance élevée
    MEDIUM = 0.75    # Confiance moyenne
    LOW = 0.50       # Confiance faible
    UNCERTAIN = 0.25 # Incertain
```

### ClassificationContext

```python
@dataclass
class ClassificationContext:
    transaction: Any                           # Transaction à analyser
    wallet_address: str                       # Adresse portefeuille
    network_state: Dict[str, Any]             # État réseau (slot, gas, etc.)
    token_metadata: Dict[str, Any]            # Métadonnées token impliqué
    market_conditions: Dict[str, Any]         # Conditions marché
    historical_patterns: Dict[str, Any]       # Patterns historiques wallet
```

### ClassificationResult

```python
@dataclass
class ClassificationResult:
    transaction_type: TransactionType         # Type classifié
    confidence: float                        # Score confiance (0-1)
    reasoning: str                           # Explication classification
    evidence: Dict[str, Any]                 # Preuves/indices utilisés
    alternative_types: List[Tuple[TransactionType, float]]  # Types alternatifs avec scores
    metadata: Dict[str, Any]                 # Métadonnées additionnelles
    classified_at: int                       # Timestamp classification
```

## Classe principale : TransactionClassifier

### Initialisation

**Attributs d'instance :**
- `self.config` - Configuration via `get_config()`
- `self.db_manager` - Gestionnaire base de données
- `self.DEX_PROGRAMS` - Set des programmes DEX connus
- `self.CLASSIFICATION_RULES` - Règles de classification chargées

**Programmes DEX connus :**
```python
self.DEX_PROGRAMS = {
    'JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5wNy3aZV',  # Jupiter
    '9W959DqEETiGZocYWCQPaJ6sBmUzgfxXfqGeTEdp3aQP',  # Raydium
    '675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8',  # Orca
    'CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTyW7P6d5yF3p6',  # Serum
    'Eo7WjKq67rjJQSZxS6z3YkapzY3eMj6Xy8X5EQVn5UaB',  # Meteora
}
```

### Règles de classification

#### `_load_classification_rules()`

**Fonction :** Charge les règles de classification depuis BDD ou valeurs par défaut

**Structure self.CLASSIFICATION_RULES :**
```python
{
    # Seuils basés sur montants
    'amount_thresholds': {
        'whale': 1000,    # > 1000 SOL = whale
        'large': 100,     # > 100 SOL = large
        'medium': 10,     # > 10 SOL = medium
        'small': 0.1      # > 0.1 SOL = small
    },
    
    # Patterns temporels
    'time_patterns': {
        'recent': 3600,   # 1 heure
        'day': 86400,     # 1 jour
        'week': 604800,   # 1 semaine
    },
    
    # Classification par programme
    'program_types': {
        'JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5wNy3aZV': 'DEX_SWAP',
        '9W959DqEETiGZocYWCQPaJ6sBmUzgfxXfqGeTEdp3aQP': 'DEX_SWAP',
        'Stake111111111111111111111111111111111111111': 'STAKE',
        'Stake222222222222222222222222222222222222222': 'UNSTAKE',
        '111111111111111111111111111111111111111111': 'SYSTEM_TRANSFER',
    }
}
```

### Méthodes principales

#### 1. `classify_transaction(transaction: Transaction, context: Optional[ClassificationContext] = None) -> ClassificationResult`

**Fonction :** Classifie une transaction unique avec scoring de confiance

**Processus complet :**

1. **Log début :** "🏷️ Classifying transaction {signature}"

2. **Construction contexte :**
   - Si pas de contexte fourni → appel `_build_classification_context(transaction)`

3. **Classification multi-couches :**
   - Appel `_multi_layer_classification(transaction, context)`

4. **Gestion erreurs :**
   - Try/catch global avec log "❌ Error classifying transaction"
   - Retour `ClassificationResult` avec type `OTHER`, confiance `UNCERTAIN`

#### 2. `_build_classification_context(transaction: Transaction) -> ClassificationContext`

**Fonction :** Construit contexte complet pour classification

**Données contextuelles collectées :**

1. **État réseau :** `_get_network_state(transaction)`
   ```python
   {
       'timestamp': transaction.block_time,
       'slot': transaction.slot,
       'gas_price': transaction.fee
   }
   ```

2. **Métadonnées token :** `_get_token_metadata(transaction.token_mint)` si token impliqué

3. **Conditions marché :** `_get_market_conditions(transaction)`
   ```python
   {
       'timestamp': transaction.block_time,
       'price': transaction.price_per_token
   }
   ```

4. **Patterns historiques :** `_get_historical_patterns(transaction)`

### Système de classification multi-couches

#### 3. `_multi_layer_classification(transaction, context) -> ClassificationResult`

**Fonction :** Approche classification multi-couches

**Architecture 3 couches :**

1. **Couche 1 - Preuves directes :** `_layer1_direct_classification()`
2. **Couche 2 - Analyse contextuelle :** `_layer2_context_analysis()`
3. **Couche 3 - Matching patterns :** `_layer3_pattern_matching()`
4. **Combinaison résultats :** `_combine_classification_results()`

#### 4. `_layer1_direct_classification(transaction, context) -> ClassificationResult`

**Fonction :** Classification basée preuves directes

**Logique de classification :**

1. **Type explicite :** Si `transaction.transaction_type != OTHER`
   - Retour direct avec confiance `HIGH`
   - Reasoning : "Direct type from transaction"

2. **Analyse montants :**
   - Si `amount < 0.001` → evidence `small_amount = True`, confiance × 0.9

3. **Implication token :**
   - Si `token_mint` présent → evidence `token_transaction = True`

**Fallback :** Type `TRANSFER` avec confiance `HIGH`, reasoning "Default classification based on metadata"

#### 5. `_layer2_context_analysis(transaction, context) -> ClassificationResult`

**Fonction :** Classification basée contexte

**Analyses contextuelles :**

1. **Identification programme :**
   - Appel `_identify_program_type(transaction)`
   - Mapping programme → type :
     ```python
     type_mapping = {
         'DEX_SWAP': TransactionType.SWAP,
         'STAKE': TransactionType.STAKE,
         'UNSTAKE': TransactionType.UNSTAKE,
         'SYSTEM_TRANSFER': TransactionType.TRANSFER,
     }
     ```

2. **Analyse patterns token :**
   - Si `token_mint` → appel `_analyze_token_pattern(transaction, context)`

**Confiance :** `MEDIUM` (0.75)

#### 6. `_layer3_pattern_matching(transaction, context) -> ClassificationResult`

**Fonction :** Classification par matching de patterns

**Patterns détectés :**

1. **Buy/Sell :** `_detect_buy_sell_pattern()`
2. **Swap :** `_detect_swap_pattern()`
3. **Arbitrage :** `_detect_arbitrage_pattern()`

**Logique :**
- Si patterns détectés → utilise pattern primaire
- Confiance : `LOW` (0.5) × 0.9 si patterns, × 0.5 sinon

#### 7. `_identify_program_type(transaction: Transaction) -> Optional[str]`

**Fonction :** Identifie type programme depuis données transaction

**Processus :**
1. Extraction `program_id` depuis `transaction.metadata`
2. Lookup dans `self.CLASSIFICATION_RULES['program_types']`
3. Retour type programme ou `None`

#### 8. `_analyze_token_pattern(transaction, context) -> Optional[Dict[str, Any]]`

**Fonction :** Analyse patterns liés aux tokens

**Patterns identifiés :**

1. **Token connu :**
   - Si symbole dans `['USDC', 'USDT', 'SOL', 'ETH', 'BTC']` → `known_token = True`

2. **Âge token :**
   - Calcul âge depuis `token_metadata.created_at`
   - Stockage en `token_age_days`

### Détection de patterns de trading

#### 9. `_detect_buy_sell_pattern(transaction, context) -> Optional[Dict[str, Any]]`

**Fonction :** Détecte patterns buy/sell depuis flux transaction

**Logique d'analyse des flux :**

**Pattern BUY :** SOL sortant, tokens entrant
```python
if sol_change < -MIN_TRANSACTION_AMOUNT and token_change > 0:
    return {
        'type': TransactionType.BUY,
        'name': 'direct_buy',
        'confidence': 0.85,
        'evidence': {
            'sol_spent': abs(sol_change),
            'tokens_received': token_change
        }
    }
```

**Pattern SELL :** Tokens sortant, SOL entrant
```python
elif sol_change > MIN_TRANSACTION_AMOUNT and token_change < 0:
    return {
        'type': TransactionType.SELL,
        'name': 'direct_sell',
        'confidence': 0.85,
        'evidence': {
            'sol_received': sol_change,
            'tokens_sold': abs(token_change)
        }
    }
```

#### 10. `_detect_swap_pattern(transaction, context) -> Optional[Dict[str, Any]]`

**Fonction :** Détecte patterns swap DEX

**Méthodes de détection :**

1. **Metadata swap :**
   - Si 'swap' dans `transaction.metadata` → confiance 0.9

2. **Interaction programme :**
   - Si `program_id` dans `self.DEX_PROGRAMS` → confiance 0.95

#### 11. `_detect_arbitrage_pattern(transaction, context) -> Optional[Dict[str, Any]]`

**Fonction :** Détecte patterns arbitrage

**Implémentation actuelle :** Placeholder retournant `None` (nécessiterait analyse cross-DEX)

### Combinaison des résultats

#### 12. `_combine_classification_results(results: List[ClassificationResult]) -> ClassificationResult`

**Fonction :** Combine multiples résultats classification avec confiance pondérée

**Algorithme de combinaison :**

1. **Pondération par confiance :**
   ```python
   weighted_results = defaultdict(float)
   for result in results:
       weighted_results[result.transaction_type] += result.confidence
   ```

2. **Sélection type dominant :**
   - Type avec poids le plus élevé
   - Confiance combinée : `min(weighted_results[primary_type] / len(results), 1.0)`

3. **Agrégation preuves :**
   - Fusion de toutes `evidence` des résultats
   - Concaténation `reasoning` avec séparateur " | "

**Fallback :** Si pas de résultats → type `OTHER`, confiance `UNCERTAIN`

### Méthodes de contexte

#### 13. `_get_token_metadata(token_mint: str) -> Dict[str, Any]`

**Fonction :** Récupère métadonnées token depuis BDD

**Requête SQL :**
```sql
SELECT * FROM tokens WHERE address = ?
```

**Retour :** Dictionnaire complet ligne BDD ou `{}` si erreur

#### 14. `_get_historical_patterns(transaction: Transaction) -> Dict[str, Any]`

**Fonction :** Récupère patterns historiques pour portefeuille

**Requête SQL :**
```sql
SELECT transaction_type, COUNT(*) as count
FROM transactions
WHERE wallet_address = ? AND block_time > ?
GROUP BY transaction_type
```

**Paramètres :** Analyse 24h précédentes (`block_time - 86400`)

**Structure retour :**
```python
{
    'buy': 5,      # 5 achats dans les 24h
    'sell': 3,     # 3 ventes
    'transfer': 10 # 10 transferts
}
```

### Fonctionnalités avancées

#### 15. `batch_classify_transactions(transactions: List[Transaction]) -> List[ClassificationResult]`

**Fonction :** Classifie plusieurs transactions efficacement

**Processus :** Itération simple avec appel `classify_transaction()` pour chaque transaction

#### 16. `validate_classification(result: ClassificationResult, ground_truth: TransactionType) -> bool`

**Fonction :** Valide précision classification

**Logique :** Comparaison simple `result.transaction_type == ground_truth`

#### 17. `get_classification_stats(wallet_address: str) -> Dict[str, Any]`

**Fonction :** Statistiques classification pour portefeuille

**Métriques calculées :**
```python
{
    'total_classified': int,           # Total transactions classifiées
    'by_type': Dict[str, int],        # Répartition par type
    'confidence_distribution': {      # Distribution confiance
        'high': int,      # ≥ 0.9
        'medium': int,    # ≥ 0.7
        'low': int,       # ≥ 0.5
        'uncertain': int  # < 0.5
    },
    'accuracy': float                 # Précision (placeholder)
}
```

**Requête SQL :**
```sql
SELECT classification, confidence
FROM transaction_analyses
WHERE wallet_address = ?
```

#### 18. `reclassify_transactions(wallet_address: str, new_rules: Dict[str, Any]) -> int`

**Fonction :** Re-classifie transactions avec nouvelles règles

**Processus :**

1. **Récupération transactions :**
   ```sql
   SELECT * FROM transactions WHERE wallet_address = ?
   ```

2. **Re-classification :**
   - Reconstruction objets `Transaction`
   - Appel `classify_transaction()` avec nouvelles règles

3. **Mise à jour si changement :**
   ```sql
   UPDATE transactions
   SET transaction_type = ?
   WHERE signature = ?
   ```

**Retour :** Nombre transactions mises à jour

## Instances et fonctions globales

### Instance globale singleton
```python
_classifier = None

def get_transaction_classifier() -> TransactionClassifier:
    global _classifier
    if _classifier is None:
        _classifier = TransactionClassifier()
    return _classifier
```

### Fonctions de convenance

#### `classify_transaction(transaction, context=None) -> ClassificationResult`
**Wrapper :** `get_transaction_classifier().classify_transaction(transaction, context)`

#### `batch_classify_transactions(transactions) -> List[ClassificationResult]`
**Wrapper :** `get_transaction_classifier().batch_classify_transactions(transactions)`

#### `get_classification_stats(wallet_address) -> Dict[str, Any]`
**Wrapper :** `get_transaction_classifier().get_classification_stats(wallet_address)`

## Schéma de base de données (inféré)

### Table `tokens` (métadonnées)
```sql
CREATE TABLE tokens (
    address TEXT PRIMARY KEY,
    symbol TEXT,
    name TEXT,
    decimals INTEGER,
    created_at INTEGER,
    -- autres métadonnées...
);
```

### Table `transactions` (données source)
```sql
CREATE TABLE transactions (
    signature TEXT PRIMARY KEY,
    wallet_address TEXT NOT NULL,
    slot INTEGER NOT NULL,
    block_time INTEGER NOT NULL,
    amount REAL NOT NULL,
    fee REAL DEFAULT 0.0,
    token_mint TEXT,
    token_symbol TEXT,
    token_name TEXT,
    token_amount REAL,
    price_per_token REAL,
    transaction_type TEXT NOT NULL,
    status TEXT NOT NULL,
    source TEXT,
    metadata TEXT, -- JSON pour program_id, etc.
    INDEX idx_wallet_time (wallet_address, block_time)
);
```

### Table `transaction_analyses` (résultats)
```sql
CREATE TABLE transaction_analyses (
    signature TEXT NOT NULL,
    wallet_address TEXT NOT NULL,
    classification TEXT NOT NULL,
    confidence REAL NOT NULL,
    reasoning TEXT,
    evidence TEXT, -- JSON
    classified_at INTEGER NOT NULL,
    PRIMARY KEY (signature, wallet_address)
);
```

## Patterns et logiques métier

### Architecture multi-couches
- **Couche 1 :** Preuves directes (type explicite, métadonnées)
- **Couche 2 :** Analyse contextuelle (programmes, tokens)
- **Couche 3 :** Pattern matching (flux SOL/tokens, signatures DEX)

### Classification par flux
- **BUY :** SOL-- + Token++ (sortie SOL, entrée tokens)
- **SELL :** SOL++ + Token-- (entrée SOL, sortie tokens)
- **SWAP :** Échange via programmes DEX identifiés

### Scoring de confiance
- **HIGH (0.95) :** Type explicite, programme connu
- **MEDIUM (0.75) :** Analyse contextuelle concluante
- **LOW (0.50) :** Pattern matching réussi
- **UNCERTAIN (0.25) :** Aucune classification fiable

### Combinaison intelligente
- **Pondération :** Poids par confiance de chaque couche
- **Consensus :** Type avec score pondéré maximal
- **Traçabilité :** Agrégation preuves et raisonnements

### Programmes DEX
- **Jupiter, Raydium, Orca, Serum, Meteora** identifiés par program_id
- **Confiance élevée** pour interactions programmes connus
- **Extensibilité** pour nouveaux DEX

## Gestion d'erreurs et logging

### Préfixes de logs
- 🏷️ : Classification en cours
- 🧪 : Tests et validation
- 🔄 : Re-classification
- ❌ : Erreurs système

### Stratégies d'erreur
- **Graceful degradation :** Type `OTHER` + confiance `UNCERTAIN` si échec
- **Logging détaillé :** Erreurs avec contexte complet
- **Validation :** Méthodes de test précision

## Exemple de test (section __main__)

**Transactions de test :**

1. **BUY pattern :**
   - `amount = -1.5` (SOL dépensé)
   - `token_amount = 150.0` (USDC reçu)
   - Token : USDC

2. **SELL pattern :**
   - `amount = 2.0` (SOL reçu)
   - `token_amount = -200.0` (USDC vendu)
   - Token : USDC

**Tests effectués :**
- Classification de chaque transaction
- Affichage type détecté + confiance

## Points d'extension

1. **ML Integration :** Modèles apprentissage automatique pour patterns complexes
2. **Program Analysis :** Décompilation instructions Solana pour classification précise
3. **Cross-DEX Arbitrage :** Détection arbitrage inter-DEX temps réel
4. **Advanced Context :** Sentiment marché, événements on-chain
5. **Real-time Classification :** WebSockets pour classification temps réel
6. **Ensemble Methods :** Combinaison multiples algorithmes classification
7. **Regulatory Patterns :** Détection patterns conformité réglementaire
8. **Social Integration :** Patterns basés activité sociale/communautaire