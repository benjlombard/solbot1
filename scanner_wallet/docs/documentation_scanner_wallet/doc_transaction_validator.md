# Solana Transaction Validator - Documentation Technique

## Vue d'ensemble

Le **Solana Transaction Validator** est un système de validation avancé pour transactions, balances et intégrité des données blockchain. Il fournit une validation complète multi-niveaux avec détection d'anomalies, vérification d'intégrité et rapports détaillés.

## Architecture générale

### Imports et dépendances

**Imports système :**
- `re`, `time`, `sqlite3` - Expressions régulières, temps, base de données
- `typing` - Annotations de type (Dict, List, Optional, Tuple, Any, Union)
- `dataclasses` - Structures de données (dataclass, field)
- `decimal.Decimal` - Calculs décimaux précis
- `datetime.{datetime, timedelta}` - Gestion dates
- `json`, `base58`, `hashlib` - JSON, encodage base58, hachage
- `collections.defaultdict` - Dictionnaires avec valeurs par défaut

**Imports métier avec fallbacks :**
- `core.logger.get_logger` → fallback: `logging.getLogger()`
- `core.database.get_database_manager` → fallback: `None`
- `core.config.get_config` → fallback: `None`
- `core.exceptions.ValidationError` → fallback: classe exception personnalisée
- `models.transaction.{Transaction, TransactionType, TransactionStatus}` → pas de fallback
- `models.token.Token` → pas de fallback
- `utils.helpers.{get_current_timestamp, safe_divide}` → pas de fallback
- `utils.validators.validate_wallet_address` → pas de fallback

**Fallback ValidationError :**
```python
class ValidationError(Exception):
    def __init__(self, message: str, field: str = None):
        self.message = message
        self.field = field
        super().__init__(message)
```

## Classe ValidationResult

### Structure et méthodes

**Attributs :**
```python
class ValidationResult:
    def __init__(self):
        self.is_valid = True                    # Statut validation global
        self.errors: List[Dict[str, Any]] = []  # Liste erreurs critiques
        self.warnings: List[Dict[str, Any]] = [] # Liste avertissements
        self.metadata: Dict[str, Any] = {}      # Métadonnées validation
```

**Méthodes principales :**

#### `add_error(message: str, field: str = None, severity: str = "error")`
**Fonction :** Ajoute erreur validation et invalide le résultat

**Structure erreur :**
```python
{
    'message': str,           # Message d'erreur
    'field': str,            # Champ concerné (optionnel)
    'severity': str,         # "error", "critical"
    'timestamp': int         # Timestamp ajout
}
```

**Effet :** `self.is_valid = False`

#### `add_warning(message: str, field: str = None)`
**Fonction :** Ajoute avertissement sans invalider

**Structure warning :**
```python
{
    'message': str,
    'field': str,
    'severity': 'warning',
    'timestamp': int
}
```

#### `merge(other: ValidationResult)`
**Fonction :** Fusionne deux résultats validation
- Étend listes `errors` et `warnings`
- Met à jour `metadata`
- Combine `is_valid` avec AND logique

#### `to_dict() -> Dict[str, Any]`
**Fonction :** Conversion en dictionnaire avec résumé

**Structure retour :**
```python
{
    'is_valid': bool,
    'errors': List[Dict],
    'warnings': List[Dict],
    'metadata': Dict,
    'summary': {
        'total_errors': int,
        'total_warnings': int,
        'severity': str  # 'critical', 'error', 'warning', 'ok'
    }
}
```

## Classe principale : TransactionValidator

### Initialisation

**Attributs de configuration :**
- `self.config` - Configuration via `get_config()`
- `self.db_manager` - Gestionnaire base de données

**Constantes de validation :**
```python
self.SOLANA_SIGNATURE_LENGTH = 88      # Longueur signature Solana
self.SOLANA_ADDRESS_LENGTH = 44        # Longueur adresse Solana
self.MIN_TRANSACTION_AMOUNT = 0.000001 # Montant minimum SOL
self.MAX_TRANSACTION_AMOUNT = 1000000  # Montant maximum SOL
self.MAX_FEE = 0.1                     # Frais maximum SOL
self.MAX_SLOT = 2**64 - 1              # Slot maximum
```

**Patterns regex :**
```python
self.SOLANA_ADDRESS_PATTERN = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{44}$')
self.SOLANA_SIGNATURE_PATTERN = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{88}$')
self.TOKEN_SYMBOL_PATTERN = re.compile(r'^[A-Z][A-Z0-9_]{1,10}$')
```

**Log d'initialisation :** "✅ Transaction validator initialized"

### Méthode principale de validation

#### `validate_transaction(transaction: Transaction, level: str = "standard") -> ValidationResult`

**Fonction :** Validation complète transaction avec niveaux configurables

**Niveaux de validation :**
- **"strict"** : Validation complète + intégrité blockchain + séquence + doublons
- **"standard"** : Validation standard (défaut)
- **"lenient"** : Validation basique

**Processus de validation :**

1. **Validation de base :**
   - `_validate_signature()`
   - `_validate_wallet_address()`
   - `_validate_slot()`
   - `_validate_block_time()`
   - `_validate_amount()`
   - `_validate_fee()`

2. **Validation token (si présent) :**
   - `_validate_token_mint()`
   - `_validate_token_symbol()`
   - `_validate_token_amount()`
   - `_validate_price_per_token()`

3. **Validation type/statut :**
   - `_validate_transaction_type()`
   - `_validate_status()`

4. **Validation avancée (level="strict") :**
   - `_validate_blockchain_integrity()`
   - `_validate_sequence()`
   - `_validate_duplicate_check()`

5. **Validation métadonnées :**
   - `_validate_metadata()`
   - `_validate_cross_references()`

### Méthodes de validation spécialisées

#### `_validate_signature(signature: str, result: ValidationResult)`

**Fonction :** Valide signature transaction Solana

**Validations effectuées :**
1. **Présence :** Signature non vide
2. **Longueur :** Exactement 88 caractères
3. **Format :** Respect pattern base58 Solana
4. **Décodage base58 :** Validation encoding + longueur 64 bytes

**Erreurs possibles :**
- "Signature is required" (critical)
- "Invalid signature length"
- "Invalid signature format"
- "Invalid base58 signature"

#### `_validate_wallet_address(address: str, result: ValidationResult)`

**Fonction :** Valide adresse portefeuille

**Validations :**
1. **Présence :** Adresse non vide (critical si manquante)
2. **Format :** Utilise `validate_wallet_address()` utilitaire
3. **Existence BDD :** Vérification dans table `wallet_priorities`

**Requête SQL existence :**
```sql
SELECT 1 FROM wallet_priorities
WHERE wallet_address = ?
```

**Warning si non trouvée :** "Wallet address not found in database"

#### `_validate_slot(slot: int, result: ValidationResult)`

**Fonction :** Valide numéro de slot blockchain

**Validations :**
1. **Présence :** Slot requis (critical)
2. **Type :** Doit être integer
3. **Range :** Non négatif et ≤ MAX_SLOT
4. **Réalisme :** Comparaison avec slot actuel via `_get_current_slot()`

#### `_validate_block_time(block_time: int, result: ValidationResult)`

**Fonction :** Valide timestamp de block

**Validations :**
1. **Présence :** Block time requis (critical)
2. **Type :** Doit être integer
3. **Range réaliste :**
   - Minimum : 2 ans dans le passé
   - Maximum : 5 minutes dans le futur

**Warnings :** "Block time is very old" ou "Block time is in the future"

#### `_validate_amount(amount: float, result: ValidationResult)`

**Fonction :** Valide montant transaction

**Validations :**
1. **Présence :** Montant requis (critical)
2. **Format :** Convertible en float
3. **Range :** Entre MIN et MAX_TRANSACTION_AMOUNT
4. **Warnings spéciaux :**
   - "Amount is very small" si < MIN_TRANSACTION_AMOUNT
   - "Amount is very large" si > MAX_TRANSACTION_AMOUNT
   - "Amount is zero" si = 0

#### `_validate_fee(fee: float, result: ValidationResult)`

**Fonction :** Valide frais transaction

**Validations :**
1. **Présence :** Fee requis (critical)
2. **Positivité :** Frais ≥ 0
3. **Limite :** Fee ≤ MAX_FEE (0.1 SOL)
4. **Warnings :** "Fee is unusually large" ou "Fee is zero"

#### `_validate_token_mint(token_mint: str, result: ValidationResult)`

**Fonction :** Valide adresse mint token

**Validations :**
1. **Longueur :** Exactement 44 caractères
2. **Format :** Pattern adresse Solana
3. **Existence BDD :** Vérification dans table `tokens`

**Requête SQL :**
```sql
SELECT 1 FROM tokens WHERE address = ?
```

#### `_validate_token_symbol(symbol: str, result: ValidationResult)`

**Fonction :** Valide symbole token

**Validations :**
- Skip si vide ou "UNKNOWN"
- Pattern : `^[A-Z][A-Z0-9_]{1,10}$`
- Longueur ≤ 10 caractères

#### `_validate_token_amount(token_amount: float, result: ValidationResult)`

**Fonction :** Valide quantité token

**Validations :**
1. **Positivité :** ≥ 0 (erreur si négatif)
2. **Limite :** ≤ 1e18 (100 trillion tokens)

#### `_validate_price_per_token(price: float, result: ValidationResult)`

**Fonction :** Valide prix unitaire token

**Validations :**
1. **Positivité :** ≥ 0
2. **Limite :** ≤ 1,000,000 USD
3. **Warning :** "Price is zero" si = 0

### Validation avancée (strict mode)

#### `_validate_blockchain_integrity(transaction, result)`

**Fonction :** Vérifie intégrité blockchain

**Vérifications :**
- **Signature unique :** Pas de signature dupliquée avec block_time différent

**Requête SQL :**
```sql
SELECT COUNT(*) FROM transactions
WHERE signature = ? AND block_time != ?
```

#### `_validate_sequence(transaction, result)`

**Fonction :** Valide séquence chronologique

**Vérification :** Pas de transaction avec slot > actuel mais block_time < actuel

**Requête SQL :**
```sql
SELECT COUNT(*) FROM transactions
WHERE wallet_address = ? 
AND slot > ? 
AND block_time < ?
```

#### `_validate_duplicate_check(transaction, result)`

**Fonction :** Détection doublons

**Requête SQL :**
```sql
SELECT COUNT(*) FROM transactions
WHERE signature = ?
```

**Erreur si count > 0 :** "Transaction already exists"

#### `_validate_cross_references(transaction, result)`

**Fonction :** Validation références croisées

**Vérifications :**
1. **Wallet existe :** Dans table `wallet_priorities`
2. **Token existe :** Dans table `tokens` si mint présent

### Validation de données brutes

#### `validate_transaction_data(data: Dict[str, Any]) -> ValidationResult`

**Fonction :** Valide données transaction brutes avant création objet

**Champs requis :**
```python
required_fields = [
    'signature', 'wallet_address', 'slot', 'block_time', 
    'amount', 'fee', 'transaction_type', 'status'
]
```

**Processus :**
1. Vérification champs requis (critical si manquant)
2. Construction objet `Transaction` temporaire
3. Appel `validate_transaction()` standard

### Validation batch et intégrité

#### `validate_transaction_batch(transactions: List[Transaction]) -> Dict[str, ValidationResult]`

**Fonction :** Validation multiple transactions

**Retour :** Dictionnaire `{signature: ValidationResult}`

#### `check_transaction_integrity(signature: str) -> ValidationResult`

**Fonction :** Vérification intégrité transaction stockée

**Vérifications :**
1. **Existence :** Transaction trouvée en BDD
2. **Checksum :** Hash calculé pour vérification
3. **Cohérence logique :**
   - Montant négatif mais type pas transfer/buy/sell
   - Token amount négatif

#### `validate_transaction_sequence(wallet_address, transactions) -> ValidationResult`

**Fonction :** Valide séquence temporelle transactions

**Validations :**
1. **Tri chronologique :** Par (block_time, slot)
2. **Ordre temporel :** block_time croissant
3. **Ordre slots :** slot croissant (warning si violation)

### Détection d'anomalies

#### `detect_anomalies(transactions: List[Transaction]) -> List[Dict[str, Any]]`

**Fonction :** Détecte patterns anormaux

**Anomalies par wallet via `_detect_wallet_anomalies()` :**

1. **Haute fréquence :**
   - 100+ transactions en 1 heure
   - Type : 'high_frequency', severity : 'medium'

2. **Gros montants :**
   - Transactions > 1000 SOL
   - Type : 'large_amounts', severity : 'low'

3. **Frais zéro :**
   - Transactions avec fee = 0
   - Type : 'zero_fees', severity : 'low'

### Validation intégrité base de données

#### `validate_database_integrity() -> Dict[str, Any]`

**Fonction :** Validation complète intégrité BDD

**Structure retour :**
```python
{
    'overall_status': str,    # 'healthy', 'error'
    'issues': List[str],      # Problèmes critiques
    'warnings': List[str]     # Avertissements
}
```

**Vérifications :**

1. **Enregistrements orphelins :**
   ```sql
   SELECT COUNT(*) FROM transactions
   WHERE wallet_address NOT IN (
       SELECT wallet_address FROM wallet_priorities
   )
   ```

2. **Signatures dupliquées :**
   ```sql
   SELECT signature, COUNT(*)
   FROM transactions
   GROUP BY signature
   HAVING COUNT(*) > 1
   ```

3. **Timestamps invalides :**
   ```sql
   SELECT COUNT(*) FROM transactions
   WHERE block_time > ? OR block_time < ?
   ```

### Rapports et analyses

#### `generate_validation_report(wallet_address: str) -> Dict[str, Any]`

**Fonction :** Rapport complet validation portefeuille

**Structure rapport :**
```python
{
    'wallet_address': str,
    'timestamp': int,
    'summary': {
        'total_transactions': int,
        'total_errors': int,
        'total_warnings': int,
        'valid_percentage': float
    },
    'details': {
        'error_distribution': Dict[str, int],      # Par champ
        'warning_distribution': Dict[str, int],    # Par champ
        'validation_results': List[Dict]           # 10 premiers résultats
    },
    'recommendations': List[str]
}
```

**Processus :**
1. Récupération 1000 dernières transactions
2. Validation de chaque transaction
3. Agrégation statistiques erreurs/warnings
4. Génération recommandations automatiques

#### `check_data_consistency(wallet_address: str) -> Dict[str, Any]`

**Fonction :** Vérification cohérence données wallet

**Vérifications cohérence :**

1. **Balance SOL calculée :**
   ```sql
   SELECT SUM(amount) as total_sol_change
   FROM transactions
   WHERE wallet_address = ? AND token_mint IS NULL AND status = 'success'
   ```

2. **Balances tokens calculées vs réelles :**
   - Calcul depuis transactions
   - Comparaison avec `token_accounts`
   - Détection écarts > 0.001

3. **Comptes orphelins :**
   - Token accounts sans transactions correspondantes
   - Transactions sans token accounts

4. **Score qualité données :**
   - Calcul : `max(0, 100 - issues_count * 10)`

**Structure retour :**
```python
{
    'wallet_address': str,
    'status': str,                    # 'healthy', 'warning', 'critical', 'error'
    'issues': List[str],              # Problèmes détectés
    'balances': {
        'calculated_sol_change': float,
        # autres balances calculées
    },
    'summary': {
        'total_transactions': int,
        'unique_tokens': int,
        'data_quality_score': int
    }
}
```

### Validation opérations spécifiques

#### `validate_token_transfer(from_wallet, to_wallet, token_mint, amount) -> ValidationResult`

**Fonction :** Validation transfert token

**Validations :**
1. **Adresses :** from_wallet et to_wallet valides
2. **Token mint :** Format correct
3. **Montant :** Positif
4. **Balance suffisante :** Vérification en BDD

**Requête balance :**
```sql
SELECT SUM(balance) FROM token_accounts
WHERE wallet_address = ? AND token_mint = ?
```

#### `validate_block_range(start_slot: int, end_slot: int) -> ValidationResult`

**Fonction :** Validation range de blocks

**Validations :**
1. **Positivité :** Slots ≥ 0
2. **Ordre :** start_slot ≤ end_slot
3. **Taille :** Warning si range > 1,000,000

### Méthodes utilitaires

#### `get_validation_summary() -> Dict[str, Any]`

**Fonction :** Résumé capacités validation

**Structure retour :**
```python
{
    'validator_version': "2.0.0",
    'supported_levels': ['strict', 'standard', 'lenient'],
    'validation_features': [
        'signature_validation', 'address_validation', 
        'amount_validation', 'token_validation',
        'sequence_validation', 'integrity_checks', 
        'anomaly_detection'
    ],
    'constraints': {
        'min_transaction_amount': float,
        'max_transaction_amount': float,
        'max_fee': float,
        'signature_length': int,
        'address_length': int
    }
}
```

## Schémas base de données (inférés)

### Tables utilisées pour validation

#### Table `transactions` (principale)
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
    source TEXT
);
```

#### Table `wallet_priorities` (référentiel wallets)
```sql
CREATE TABLE wallet_priorities (
    wallet_address TEXT PRIMARY KEY,
    -- autres colonnes...
);
```

#### Table `tokens` (métadonnées tokens)
```sql
CREATE TABLE tokens (
    address TEXT PRIMARY KEY,
    symbol TEXT,
    name TEXT,
    decimals INTEGER
);
```

#### Table `token_accounts` (comptes tokens)
```sql
CREATE TABLE token_accounts (
    wallet_address TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    balance REAL NOT NULL,
    is_active INTEGER DEFAULT 1,
    PRIMARY KEY (wallet_address, token_mint)
);
```

## Patterns et logiques métier

### Niveaux de validation
- **Lenient :** Validation de base, tolère anomalies mineures
- **Standard :** Validation complète standard (défaut)
- **Strict :** Toutes validations + intégrité blockchain + séquence

### Gestion des erreurs vs warnings
- **Erreurs :** Invalidation complète (`is_valid = False`)
- **Warnings :** Information sans invalidation
- **Severity levels :** "critical", "error", "warning"

### Validation progressive
1. **Validation syntaxique :** Format, longueur, encoding
2. **Validation sémantique :** Range, cohérence logique
3. **Validation référentielle :** Existence en BDD
4. **Validation intégrité :** Blockchain, séquence, doublons

### Anomaly detection
- **Statistical patterns :** Fréquence, montants, distributions
- **Behavioral patterns :** Séquences inhabituelles
- **Data quality :** Cohérence interne données

### Caching et performance
- **Pas de cache :** Validation temps réel pour intégrité
- **BDD queries optimisées :** Index sur champs validation
- **Batch processing :** Validation multiple transactions

## Gestion d'erreurs et logging

### Préfixes de logs
- ✅ : Initialisation/succès
- 🔍 : Validation/vérification
- 📊 : Statistiques/rapports
- ⚠️ : Avertissements
- ❌ : Erreurs critiques

### Stratégies d'erreur
- **Non-blocking :** Validation continue malgré erreurs individuelles
- **Graceful degradation :** Fallback si BDD indisponible
- **Detailed reporting :** Context complet pour chaque erreur

## Exemple d'utilisation

**Script principal de test :**
```python
validator = TransactionValidator()
summary = validator.get_validation_summary()
print("📊 Validation summary:", json.dumps(summary, indent=2))
```

**Validation transaction :**
```python
result = validator.validate_transaction(transaction, level="strict")
if not result.is_valid:
    print("❌ Validation failed:", result.errors)
else:
    print("✅ Transaction valid")
```

## Points d'extension

1. **ML Anomaly Detection :** Modèles apprentissage pour patterns complexes
2. **Real-time Blockchain Verification :** Vérification directe RPC Solana
3. **Advanced Integrity :** Merkle proofs, cryptographic verification
4. **Custom Rules Engine :** Règles métier configurables par utilisateur
5. **Performance Optimization :** Cache intelligent, validation parallèle
6. **Regulatory Compliance :** Règles AML/KYC intégrées
7. **Cross-chain Validation :** Support autres blockchains
8. **Automated Remediation :** Correction automatique erreurs mineures