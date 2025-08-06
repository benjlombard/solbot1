# Solana Transaction Analyzer - Documentation Technique

## Vue d'ensemble

Le **Solana Transaction Analyzer** est un module d'analyse avancée de transactions avec détection de patterns, calcul P&L et détection de fraudes. Il fournit une analyse complète des transactions Solana avec scoring de risque, classification automatique et tracking de performance.

## Architecture générale

### Imports et dépendances

**Imports système :**
- `time`, `threading` - Fonctionnalités système et concurrence
- `typing` - Annotations de type (Dict, List, Optional, Tuple, Any, Set)
- `dataclasses` - Structures de données (dataclass, field)
- `datetime.{datetime, timedelta}` - Gestion des dates
- `decimal.Decimal` - Calculs décimaux précis
- `re` - Expressions régulières
- `collections.{defaultdict, deque}` - Collections avancées

**Imports métier avec fallbacks :**
- `core.logger.get_logger` → fallback: `logging.getLogger()`
- `core.database.get_database_manager` → fallback: `None`
- `core.config.get_config` → fallback: `None`
- `models.transaction.{Transaction, TransactionType, TransactionStatus}` → fallbacks: classes enum
- `models.token.{Token, TokenAccount}` → pas de fallback
- `models.wallet.WalletStats` → pas de fallback
- `utils.helpers.{get_current_timestamp, safe_divide, clamp}` → fallbacks simples
- `utils.formatters.format_sol_amount` → pas de fallback

**Fallbacks enum :**
```python
class TransactionType:
    BUY = "buy"
    SELL = "sell"
    TRANSFER = "transfer"
    SWAP = "swap"

class TransactionStatus:
    SUCCESS = "success"
    FAILED = "failed"
```

## Structures de données

### TransactionAnalysis

```python
@dataclass
class TransactionAnalysis:
    transaction: Transaction              # Transaction analysée
    analysis_type: str                   # Type d'analyse effectuée
    pnl_sol: float                      # P&L en SOL
    pnl_usd: Optional[float]            # P&L en USD (si prix disponible)
    classification: str                  # Classification de la transaction
    confidence: float                    # Score de confiance (0-1)
    risk_score: float                   # Score de risque (0-1)
    patterns_detected: List[str]        # Patterns détectés
    metadata: Dict[str, Any]            # Métadonnées additionnelles
    analyzed_at: int                    # Timestamp d'analyse
```

### PnLCalculation

```python
@dataclass
class PnLCalculation:
    token_mint: str                     # Adresse mint du token
    token_symbol: str                   # Symbole du token
    total_bought: float                 # Total acheté
    total_sold: float                   # Total vendu
    net_position: float                 # Position nette (bought - sold)
    avg_buy_price: float               # Prix d'achat moyen
    avg_sell_price: float              # Prix de vente moyen
    realized_pnl: float                # P&L réalisé
    unrealized_pnl: float              # P&L non réalisé
    total_pnl: float                   # P&L total
    last_updated: int                  # Timestamp mise à jour
```

### TradePattern

```python
@dataclass
class TradePattern:
    pattern_type: str                  # Type de pattern
    confidence: float                  # Confiance du pattern (0-1)
    transactions: List[Transaction]    # Transactions impliquées
    metadata: Dict[str, Any]          # Métadonnées pattern
```

## Classe principale : TransactionAnalyzer

### Initialisation

**Attributs de configuration :**
- `self.config` - Configuration via `get_config()`
- `self.db_manager` - Gestionnaire base de données

**Paramètres d'analyse :**
```python
self.MIN_TRANSACTION_AMOUNT = 0.001  # SOL minimum
self.PATTERN_WINDOW_HOURS = 24       # Fenêtre détection patterns
self.MAX_ANALYSIS_AGE = 7 * 24 * 3600  # 7 jours max
```

**Poids scoring risque :**
```python
self.RISK_WEIGHTS = {
    'transaction_size': 0.3,     # 30% - Taille transaction
    'frequency': 0.25,           # 25% - Fréquence
    'price_volatility': 0.2,     # 20% - Volatilité prix
    'token_age': 0.15,          # 15% - Âge token
    'blacklist_match': 0.1      # 10% - Match blacklist
}
```

**Stockage thread-safe :**
- `self._lock = threading.Lock()` - Verrou pour accès concurrent
- `self._analysis_cache: Dict[str, TransactionAnalysis]` - Cache analyses
- `self._pnl_cache: Dict[str, PnLCalculation]` - Cache P&L
- `self._recent_transactions: Dict[str, deque]` - Transactions récentes par wallet (maxlen=100)

**Log d'initialisation :** "💰 Transaction analyzer initialized"

### Méthodes principales

#### 1. `analyze_transaction(transaction: Transaction) -> TransactionAnalysis`

**Fonction :** Analyse complète d'une transaction unique

**Processus complet :**

1. **Gestion du cache :**
   - Clé cache : `f"{transaction.signature}:{transaction.wallet_address}"`
   - Vérification cache valide (5 min TTL)
   - Si trouvé → retour immédiat

2. **Analyse transaction :**
   - Appel `_perform_transaction_analysis(transaction)`
   - Stockage résultat dans cache avec verrou
   - Sauvegarde BDD via `_store_analysis()`

3. **Gestion erreurs :**
   - Try/catch global avec log "❌ Error analyzing transaction"
   - Retour `TransactionAnalysis` avec `analysis_type="error"`

#### 2. `_perform_transaction_analysis(tx: Transaction) -> TransactionAnalysis`

**Fonction :** Analyse détaillée interne

**Étapes d'analyse :**

1. **Calcul P&L :**
   - P&L SOL via `_calculate_pnl_for_transaction(tx)`
   - P&L USD via `_calculate_pnl_usd(tx, pnl_sol)`

2. **Classification :**
   - Classification via `_classify_transaction(tx)`

3. **Score de confiance :**
   - Calcul via `_calculate_confidence(tx)`

4. **Score de risque :**
   - Calcul via `_calculate_risk_score(tx)`

5. **Détection patterns :**
   - Patterns via `_detect_patterns(tx)`

6. **Extraction métadonnées :**
   - Métadonnées via `_extract_metadata(tx)`

#### 3. `_calculate_pnl_for_transaction(tx: Transaction) -> float`

**Fonction :** Calcule P&L pour transaction unique

**Logique par type :**
```python
if tx.transaction_type == TransactionType.BUY:
    return -abs(float(tx.amount)) - float(tx.fee)  # Négatif (sortie)

elif tx.transaction_type == TransactionType.SELL:
    return abs(float(tx.amount)) - float(tx.fee)   # Positif (entrée)

elif tx.transaction_type == TransactionType.SWAP:
    return float(tx.token_amount) if tx.token_amount else 0.0

else:  # TRANSFER, etc.
    return float(tx.amount) - float(tx.fee)
```

#### 4. `_calculate_pnl_usd(tx: Transaction, pnl_sol: float) -> Optional[float]`

**Fonction :** Convertit P&L SOL en USD

**Logique :** 
- Si `tx.price_per_token > 0` → `pnl_sol * tx.price_per_token`
- Sinon → `None`

#### 5. `_classify_transaction(tx: Transaction) -> str`

**Fonction :** Classifie transaction basé sur type et contexte

**Classifications :**
- **Base :** `str(tx.transaction_type)` (buy/sell/swap/transfer)
- **Modificateurs :**
  - `_large` si `amount > 100 SOL`
  - `_whale` si `token_amount > 10000`

**Exemples :** "buy_large", "sell_whale", "swap"

#### 6. `_calculate_confidence(tx: Transaction) -> float`

**Fonction :** Calcule score de confiance d'analyse

**Facteurs :**
```python
confidence = 0.8  # Base

# Bonifications
if tx.price_per_token and tx.price_per_token > 0:
    confidence += 0.1  # Prix disponible

if tx.token_amount and tx.token_amount > 0:
    confidence += 0.05  # Quantité token

# Pénalités
if tx.status == TransactionStatus.FAILED:
    confidence -= 0.2  # Transaction échouée

return clamp(confidence, 0.0, 1.0)
```

#### 7. `_calculate_risk_score(tx: Transaction) -> float`

**Fonction :** Calcule score de risque transaction

**Facteurs de risque :**

1. **Taille transaction :**
   ```python
   if amount > 1000: risk_score += 0.4      # Très grosse
   elif amount > 100: risk_score += 0.2     # Grosse
   elif amount > 10: risk_score += 0.1      # Moyenne
   ```

2. **Risque token :**
   - Si `tx.token_mint` → calcul `_assess_token_risk()` * 0.3

3. **Échec transaction :**
   - Si `FAILED` → +0.3

**Retour :** `clamp(risk_score, 0.0, 1.0)`

#### 8. `_assess_token_risk(token_mint: str) -> float`

**Fonction :** Évalue risque d'un token spécifique

**Patterns blacklist :**
```python
blacklist_patterns = [
    'scam', 'fake', 'rug', 'honeypot', 'pump', 'dump'
]
```

**Implémentation actuelle :** Simplifié, retourne `0.0`

### Détection de patterns

#### 9. `_detect_patterns(tx: Transaction) -> List[str]`

**Fonction :** Détecte patterns de trading

**Processus :**
1. Ajout transaction aux récentes (thread-safe)
2. Détection patterns via méthodes spécialisées :
   - `_detect_day_trading(tx)`
   - `_detect_whale_activity(tx)`
   - `_detect_arbitrage(tx)`

#### 10. `_detect_day_trading(tx: Transaction) -> List[str]`

**Fonction :** Détecte patterns day trading

**Logique :**
- Analyse 10 dernières transactions
- Si toutes dans 1h → pattern "high_frequency_trading"

#### 11. `_detect_whale_activity(tx: Transaction) -> List[str]`

**Fonction :** Détecte activité whale

**Seuils :**
- `amount > 10000` → "whale_transaction"
- `amount > 1000` → "large_transaction"

#### 12. `_detect_arbitrage(tx: Transaction) -> List[str]`

**Fonction :** Détecte arbitrage

**Implémentation actuelle :** Placeholder analysant séquences buy/sell rapides

#### 13. `_extract_metadata(tx: Transaction) -> Dict[str, Any]`

**Fonction :** Extrait métadonnées additionnelles

**Métadonnées calculées :**
```python
{
    'transaction_age_hours': (current_time - tx.block_time) / 3600,
    'amount_in_usd': tx.price_per_token * abs(tx.amount) if tx.price_per_token else None,
    'relative_size': abs(tx.amount) / 1000,  # Relativement à 1000 SOL
    'token_involved': bool(tx.token_mint)
}
```

### Calculs P&L avancés

#### 14. `calculate_wallet_pnl(wallet_address: str, token_mint: Optional[str] = None) -> Dict[str, PnLCalculation]`

**Fonction :** Calcule P&L pour portefeuille ou token spécifique

**Processus :**
1. **Validation :** Adresse wallet valide
2. **Récupération transactions :** Via `_get_wallet_transactions()`
3. **Groupement par token :** `defaultdict(list)`
4. **Calcul P&L par token :** Via `_calculate_token_pnl()` pour chaque groupe
5. **Cache résultats :** Stockage dans `_pnl_cache`

#### 15. `_get_wallet_transactions(wallet_address, token_mint=None) -> List[Transaction]`

**Fonction :** Récupère transactions portefeuille avec filtre optionnel

**Requête SQL avec filtre token :**
```sql
-- Avec token spécifique
SELECT * FROM transactions 
WHERE wallet_address = ? AND token_mint = ?
ORDER BY block_time DESC

-- Tous tokens
SELECT * FROM transactions 
WHERE wallet_address = ?
ORDER BY block_time DESC
```

**Construction objets :** Création complète objets `Transaction` depuis BDD

#### 16. `_calculate_token_pnl(wallet_address, token_mint, transactions) -> PnLCalculation`

**Fonction :** Calcule P&L détaillé pour token spécifique

**Processus chronologique :**
1. **Récupération infos token :** Symbole, decimales via `_get_token_info()`
2. **Initialisation compteurs :**
   ```python
   total_bought = 0.0
   total_sold = 0.0
   total_buy_value = 0.0  # Valeur totale achats
   total_sell_value = 0.0  # Valeur totale ventes
   realized_pnl = 0.0
   ```
3. **Traitement chronologique :**
   - Tri par `block_time`
   - Pour chaque transaction `SUCCESS` :
     - **BUY :** Accumul `total_bought`, `total_buy_value`
     - **SELL :** Accumul `total_sold`, `total_sell_value`, calcul `realized_pnl`

4. **Calculs finaux :**
   ```python
   avg_buy_price = total_buy_value / total_bought if total_bought > 0 else 0.0
   avg_sell_price = total_sell_value / total_sold if total_sold > 0 else 0.0
   net_position = total_bought - total_sold
   current_price = _get_current_price(token_mint)
   unrealized_pnl = net_position * current_price if current_price > 0 else 0.0
   total_pnl = realized_pnl + unrealized_pnl
   ```

#### 17. `_get_token_info(token_mint: str) -> Dict[str, Any]`

**Fonction :** Récupère informations token depuis BDD

**Requête SQL :**
```sql
SELECT symbol, decimals FROM tokens
WHERE address = ?
```

**Fallback :** `{'symbol': 'UNKNOWN', 'decimals': 9}`

#### 18. `_get_current_price(token_mint: str) -> float`

**Fonction :** Récupère prix actuel token

**Implémentation actuelle :** Placeholder retournant `0.0`

### Détection de fraudes

#### 19. `detect_fraudulent_transactions(transactions: List[Transaction]) -> List[Transaction]`

**Fonction :** Détecte transactions potentiellement frauduleuses

**Processus :** Filtre transactions via `_is_suspicious()` pour chacune

#### 20. `_is_suspicious(tx: Transaction) -> bool`

**Fonction :** Évalue si transaction suspecte

**Indicateurs suspects :**
1. **Gros montant sans prix :** `amount > 1000` et pas `price_per_token`
2. **Petit montant, gros fee :** `amount < 0.001` mais `fee > 0.01`
3. **Token blacklisté :** Symbole contient 'scam', 'fake', 'honeypot'

**Seuil :** Suspect si ≥ 2 indicateurs

### Analyses et rapports

#### 21. `get_trading_summary(wallet_address: str, days: int = 30) -> Dict[str, Any]`

**Fonction :** Rapport complet trading sur période

**Métriques calculées :**
```python
{
    'wallet_address': str,
    'period_days': int,
    'total_transactions': int,                   # Nombre transactions
    'total_volume': float,                       # Volume total SOL
    'unique_tokens': int,                        # Tokens uniques
    'pnl_by_token': Dict[str, PnLCalculation],  # P&L par token
    'patterns_detected': List[str],              # Patterns détectés
    'risk_score': float                         # Score risque global
}
```

#### 22. `_get_recent_transactions(wallet_address, cutoff_time) -> List[Transaction]`

**Fonction :** Récupère transactions récentes pour analyse

**Requête SQL :**
```sql
SELECT * FROM transactions
WHERE wallet_address = ? AND block_time > ?
ORDER BY block_time DESC
```

#### 23. `_analyze_patterns(transactions: List[Transaction]) -> List[str]`

**Fonction :** Analyse patterns dans ensemble transactions

**Patterns détectés :**
- **DCA :** Via `_detect_dca_pattern()` - Dollar Cost Averaging
- **Swing :** Via `_detect_swing_pattern()` - Swing trading
- **HODL :** Via `_detect_hodl_pattern()` - HODLing

#### 24. `_detect_dca_pattern(transactions) -> bool`

**Fonction :** Détecte pattern Dollar Cost Averaging

**Logique :**
1. Filtre transactions `BUY` (≥3 requises)
2. Calcul intervalles entre achats
3. Calcul variance des intervalles
4. DCA si variance < 20% de l'intervalle moyen (achats réguliers)

#### 25. `_detect_swing_pattern(transactions) -> bool`

**Fonction :** Détecte swing trading

**Logique :** Présence alternance buy/sell dans pattern transactions

#### 26. `_detect_hodl_pattern(transactions) -> bool`

**Fonction :** Détecte pattern HODLing

**Logique :** 
- `buys > 0` et `sells < buys * 0.2` (≤20% ventes vs achats)

#### 27. `_calculate_overall_risk(transactions) -> float`

**Fonction :** Calcule score risque global portefeuille

**Logique :** Moyenne scores risque individuels de toutes transactions

### Stockage et maintenance

#### 28. `_store_analysis(analysis: TransactionAnalysis) -> bool`

**Fonction :** Stocke résultat analyse en BDD

**Requête SQL :**
```sql
INSERT INTO transaction_analyses 
(signature, wallet_address, analysis_type, pnl_sol, pnl_usd,
 classification, confidence, risk_score, patterns_detected,
 metadata, analyzed_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
```

**Sérialisation JSON :** `patterns_detected` et `metadata`

#### 29. `cleanup_cache() -> int`

**Fonction :** Nettoyage cache analyses expirées

**Logique :**
- TTL cache analyses : 1 heure
- Suppression entrées expirées avec verrou
- Log "🧹 Cleaned X expired analysis cache entries"

## Instances et fonctions globales

### Instance globale singleton
```python
_analyzer = None

def get_transaction_analyzer() -> TransactionAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = TransactionAnalyzer()
    return _analyzer
```

### Fonctions de convenance

#### `analyze_transaction(transaction: Transaction) -> TransactionAnalysis`
**Wrapper :** `get_transaction_analyzer().analyze_transaction(transaction)`

#### `calculate_wallet_pnl(wallet_address: str, token_mint: Optional[str] = None) -> Dict[str, PnLCalculation]`
**Wrapper :** `get_transaction_analyzer().calculate_wallet_pnl(wallet_address, token_mint)`

#### `get_trading_summary(wallet_address: str, days: int = 30) -> Dict[str, Any]`
**Wrapper :** `get_transaction_analyzer().get_trading_summary(wallet_address, days)`

## Modèle Transaction (inféré)

```python
@dataclass
class Transaction:
    signature: str                    # Signature unique transaction
    wallet_address: str              # Adresse portefeuille
    slot: int                        # Slot Solana
    block_time: int                  # Timestamp block
    amount: float                    # Montant SOL
    fee: float                       # Frais transaction
    token_mint: Optional[str]        # Mint token impliqué
    token_symbol: Optional[str]      # Symbole token
    token_name: Optional[str]        # Nom token
    token_amount: Optional[float]    # Quantité token
    price_per_token: Optional[float] # Prix unitaire token
    transaction_type: TransactionType # Type transaction
    status: TransactionStatus        # Statut transaction
    source: str                      # Source données
```

## Schéma de base de données (inféré)

### Table `transactions`
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
    INDEX idx_wallet_time (wallet_address, block_time),
    INDEX idx_token_time (token_mint, block_time)
);
```

### Table `transaction_analyses`
```sql
CREATE TABLE transaction_analyses (
    signature TEXT NOT NULL,
    wallet_address TEXT NOT NULL,
    analysis_type TEXT NOT NULL,
    pnl_sol REAL NOT NULL,
    pnl_usd REAL,
    classification TEXT NOT NULL,
    confidence REAL NOT NULL,
    risk_score REAL NOT NULL,
    patterns_detected TEXT,  -- JSON
    metadata TEXT,           -- JSON
    analyzed_at INTEGER NOT NULL,
    PRIMARY KEY (signature, wallet_address),
    FOREIGN KEY (signature) REFERENCES transactions(signature)
);
```

### Table `tokens` (pour métadonnées)
```sql
CREATE TABLE tokens (
    address TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    decimals INTEGER DEFAULT 9
);
```

## Patterns et logiques métier

### Calculs P&L
- **Approche FIFO implicite** pour calculs realized P&L
- **Suivi positions nettes** (total_bought - total_sold)
- **P&L réalisé** calculé au moment ventes
- **P&L non réalisé** basé prix courant (si disponible)

### Scoring et classification
- **Score confiance** : qualité données disponibles
- **Score risque** : facteurs pondérés multiples
- **Classification dynamique** : type + modificateurs contextuels

### Détection patterns
- **Fenêtre glissante** : 100 dernières transactions par wallet
- **Patterns temporels** : DCA basé régularité intervalles
- **Patterns comportementaux** : HODL vs swing trading

### Cache et performance
- **Cache multi-niveaux** : analyses (5min), P&L (thread-safe)
- **Cleanup automatique** : TTL 1h pour analyses
- **Thread safety** : verrous pour accès concurrents

### Détection fraude
- **Scoring multi-facteurs** : taille, fees, metadata
- **Blacklists patterns** : détection tokens suspects
- **Seuils adaptatifs** : 2+ indicateurs = suspect

## Gestion d'erreurs et logging

### Préfixes de logs
- 💰 : Initialisation/P&L
- 📊 : Analyses/résultats
- 🧪 : Tests
- 🧹 : Maintenance/nettoyage
- ❌ : Erreurs

### Stratégies d'erreur
- **Graceful degradation** : analyses avec erreurs plutôt qu'exceptions
- **Fallbacks** : valeurs par défaut si calculs échouent
- **Cache protection** : verrous pour éviter race conditions

## Exemple de test (section __main__)

**Transaction de test :**
```python
Transaction(
    signature="test_signature_123456789",
    wallet_address="4DdrfGHGdMjCqVbNtXsEEGL1SryTeMo8KMGWWtZyZVFh",
    amount=1.5, fee=0.0005,
    token_mint="So11111111111111111111111111111111111111112",
    token_symbol="SOL", token_amount=1.5, price_per_token=150.0,
    transaction_type=TransactionType.BUY,
    status=TransactionStatus.SUCCESS
)
```

**Tests effectués :**
1. **Analyse transaction :** Classification, confiance, patterns
2. **Calcul P&L :** P&L portefeuille avec tokens multiples

## Points d'extension

1. **ML Pattern Detection :** Modèles apprentissage pour patterns complexes
2. **Real-time Price Integration :** Prix temps réel pour P&L précis
3. **Advanced Risk Models :** Scoring risque basé ML, market data
4. **Cross-chain Analysis :** Analyse transactions multi-blockchain
5. **Social Sentiment :** Integration signaux sociaux pour scoring
6. **Regulatory Compliance :** Détection patterns réglementaires
7. **Portfolio Optimization :** Recommandations basées analyse P&L
8. **API Webhooks :** Notifications temps réel patterns détectés