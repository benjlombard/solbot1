# Solana Wallet Monitor - Système de Validation

## Vue d'ensemble

Le module `validators.py` fournit un système de validation complet pour les données blockchain Solana et métier du Solana Wallet Monitor. Il implémente une architecture modulaire avec différents niveaux de validation et des validateurs spécialisés.

## Architecture Générale

### Niveaux de Validation

```python
class ValidationLevel(Enum):
    STRICT = "strict"      # Validation stricte avec tous les checks
    STANDARD = "standard"  # Validation standard (défaut)  
    LENIENT = "lenient"    # Validation souple pour développement
```

### Gestion des Erreurs

**ValidationError** : Exception personnalisée avec propriétés :
- `message` : Message d'erreur
- `field` : Champ concerné (optionnel)
- `value` : Valeur qui a causé l'erreur (optionnel) 
- `code` : Code d'erreur (défaut: "VALIDATION_ERROR")
- `to_dict()` : Conversion en dictionnaire

**ValidationResult** : Résultat de validation avec :
- `is_valid` : Booléen de validité
- `errors` : Liste des erreurs (invalide le résultat)
- `warnings` : Liste des avertissements (n'invalident pas)
- `field_errors` : Dictionnaire des erreurs par champ
- `add_error(message, field)` : Ajoute une erreur
- `add_warning(message, field)` : Ajoute un avertissement  
- `merge(other_result)` : Fusionne deux résultats

## Constants et Configuration

### Constants Blockchain Solana
- `SOLANA_ADDRESS_PATTERN` : `r'^[1-9A-HJ-NP-Za-km-z]{44}$'` (Base58, 44 chars)
- `SOLANA_SIGNATURE_PATTERN` : `r'^[1-9A-HJ-NP-Za-km-z]{88}$'` (Base58, 88 chars)
- `LAMPORTS_PER_SOL` : 1,000,000,000
- `TOKEN_SYMBOL_PATTERN` : `r'^[A-Z][A-Z0-9_]{1,10}$'`

### Limites de Sécurité
- `max_wallets_per_instance` : 1000
- `max_tokens_per_wallet` : 50000  
- `max_transactions_per_scan` : 10000
- `max_rpc_requests_per_minute` : 300

### Patterns de Validation
- `cycle_id` : `r'^cycle_\d+_\d+$'`
- `scan_id` : `r'^scan_[a-zA-Z0-9]{6,8}_\d+$'`

## Validateurs Spécialisés

### 1. SolanaValidator - Données Blockchain Solana

#### validate_address(address, level)
**Objectif** : Valide une adresse Solana (wallet, token mint, ATA)
**Validations** :
- Type string requis
- Longueur exacte : 44 caractères
- Pattern Base58 valide
- En mode STRICT : décodage Base58 → 32 bytes
**Warnings spéciaux** :
- Adresse système : "11111111111111111111111111111111111111111112"
- Wrapped SOL : "So11111111111111111111111111111111111111112"
- Autres adresses système commençant par "1111111111111111111111111111111111111111111"

#### validate_signature(signature, level)  
**Objectif** : Valide une signature de transaction
**Validations** :
- Type string requis
- Longueur exacte : 88 caractères
- Pattern Base58 valide
- En mode STRICT : décodage Base58 → 64 bytes

#### validate_slot(slot, level)
**Objectif** : Valide un numéro de slot Solana
**Validations** :
- Conversion en entier réussie
- Valeur non négative
- En mode STRICT : vérification plausibilité (max ~2.5 slots/seconde depuis genesis 16 Mars 2020)

#### validate_lamports(lamports, allow_zero)
**Objectif** : Valide un montant en lamports
**Validations** :
- Conversion en entier réussie
- Valeur non négative (ou zéro si autorisé)
- Warning si > 1M SOL (montant très élevé)

#### validate_sol_amount(amount, allow_zero)
**Objectif** : Valide un montant en SOL  
**Validations** :
- Conversion en Decimal réussie
- Valeur non négative (ou zéro si autorisé)  
- Warning si > 1M SOL
- Warning si précision > 9 décimales (précision lamports)

### 2. TokenValidator - Données de Tokens

#### validate_symbol(symbol, level)
**Objectif** : Valide un symbole de token
**Validations** :
- Type string requis, nettoyage et conversion uppercase
- Longueur : 1-12 caractères
- Pattern selon niveau :
  - STRICT : doit matcher `TOKEN_SYMBOL_PATTERN`
  - STANDARD : warning si non-standard
  - LENIENT : pas de vérification pattern
**Détection patterns suspects** : SCAM, FAKE, TEST, UNKNOWN, $, ., espaces

#### validate_decimals(decimals, level)
**Objectif** : Valide le nombre de décimales d'un token
**Validations** :
- Conversion en entier réussie
- Range : 0-18
**Warnings** :
- 0 décimales : "Token sans décimales (NFT ou token entier)"  
- >12 décimales : "Décimales très élevé (inhabituel)"

#### validate_token_amount(amount, decimals, allow_zero)
**Objectif** : Valide un montant de token
**Validations** :
- Validation préalable des décimales
- Conversion en Decimal réussie  
- Valeur non négative (ou zéro si autorisé)
- Précision conforme aux décimales du token
- Warning si montant > 1e15 (potentiel overflow)

#### validate_price_usd(price, allow_zero)
**Objectif** : Valide un prix en USD
**Validations** :
- Conversion en Decimal réussie
- Valeur non négative (ou zéro si autorisé)
**Warnings** :
- Prix > $1M : "Prix très élevé"
- Prix < $0.000001 : "Prix très bas"

### 3. TransactionValidator - Données de Transactions

#### Types de transaction valides
`['buy', 'sell', 'transfer', 'transfer_in', 'transfer_out', 'swap', 'stake', 'unstake', 'liquidity_add', 'liquidity_remove', 'other']`

#### Statuts valides  
`['success', 'failed', 'pending', 'timeout', 'cancelled']`

#### validate_transaction_type(tx_type)
**Validations** : Vérification membership dans la liste des types valides

#### validate_transaction_status(status)  
**Validations** : Vérification membership dans la liste des statuts valides

#### validate_block_time(block_time, allow_none)
**Objectif** : Valide un timestamp Unix de bloc
**Validations** :
- Conversion en entier réussie (si non None)
- Valeur non négative
- Postérieur au genesis Solana (~16 Mars 2020, timestamp 1584355200)
- Warning si plus de 1h dans le futur

#### validate_transaction_consistency(tx_data)
**Objectif** : Valide la cohérence métier d'une transaction complète
**Vérifications de cohérence** :
- **BUY** : token_amount > 0, sol_amount < 0 (dépense)
- **SELL** : token_amount > 0, sol_amount > 0 (gain)
- **Cohérence prix** : Si price_per_token, token_amount et sol_amount présents → vérification calcul avec tolérance 10%

### 4. SystemValidator - Données Système

#### validate_cycle_id(cycle_id)
**Pattern attendu** : `cycle_\d+_\d+` (ex: "cycle_123_456")

#### validate_priority_score(score)
**Range valide** : 0.1 - 10.0
**Warnings** :
- < 0.5 : "Score très bas, risque d'être ignoré"
- > 8.0 : "Score très élevé, risque de sur-scanning"

#### validate_url(url, require_https)
**Validations** :
- Parse URL réussie
- Schéma présent (http/https)
- Domaine présent  
- HTTPS requis si spécifié

#### validate_json_structure(data, expected_keys)
**Validations** :
- Parse JSON réussie
- Présence des clés attendues si spécifiées

### 5. SecurityValidator - Aspects de Sécurité

#### Liste noire et patterns suspects
**Mints en liste noire** : `["HoneyBadgerz...", "ScamToken123...", "FakeSolana456..."]`
**Patterns suspects** : scam, fake, phish, honey.*pot, rug.*pull, ponzi, pyramid

#### validate_token_security(token_data)
**Vérifications** :
- Membership en liste noire → Erreur
- Patterns suspects dans symbol/name → Warning
- Métadonnées manquantes → Warning
- Prix suspicieux (> $1M ou < $0.000000001) → Warning  
- Market cap suspicieuse (> $1T ou < $1000 avec prix) → Warning

#### validate_transaction_security(tx_data)
**Vérifications** :
- Transaction SOL > 10,000 → Warning "Transaction très importante"
- Valeur totale > $100k → Warning "Valeur très élevée"
- Transaction < 60s → Warning "Transaction très récente"

#### validate_rate_limiting(request_count, time_window)
**Limites** : max_rpc_requests_per_minute (300 par défaut)
- Dépassement → Erreur
- > 80% du max → Warning

### 6. BatchValidator - Opérations Batch

#### validate_wallet_list(wallets, level)
**Validations** :
- Liste non vide
- Nombre ≤ max_wallets_per_instance
- Validation individuelle de chaque adresse
- Détection des doublons → Warning

#### validate_batch_size(size, method)
**Limites par méthode** :
- `getMultipleAccounts` : 100
- `getSignaturesForAddress` : 1000  
- `getTransaction` : 10
- `generic` : 50
**Validations** :
- Taille > 0
- Respect des limites par méthode
- Warning si > 80% de la limite

### 7. CompositeValidator - Validations Complètes

#### validate_wallet_data(wallet_data, level)
**Champs validés** :
- `wallet_address` : Validation adresse Solana
- `priority_score` : Validation score de priorité
- En mode STRICT : vérification `token_accounts_count` vs limites de sécurité

#### validate_token_data(token_data, level)  
**Champs validés** :
- `token_mint` ou `address` : Validation adresse mint
- `symbol` : Validation symbole
- `decimals` : Validation décimales
- `price_usd` : Validation prix

#### validate_transaction_data(tx_data, level)
**Champs validés** :
- `signature` : Validation signature (requis)
- `wallet_address` : Validation adresse wallet (requis)  
- `token_mint` : Validation si transaction token
- `transaction_type` : Validation type
- `status` : Validation statut
- `block_time` : Validation timestamp
- `slot` : Validation slot
- `amount` : Validation montant SOL
- `token_amount` : Validation montant token (si transaction token)
- `price_per_token` : Validation prix
- En mode STANDARD/STRICT : validation cohérence métier

## API Principale

### DataValidator - Classe Principale
**Initialisation** : `DataValidator(level=ValidationLevel.STANDARD)`
**Propriétés** : Accès à tous les validateurs spécialisés
**Méthodes principales** :
- `set_level(level)` : Change le niveau de validation
- `validate_wallet(wallet_data)` : Validation complète wallet + sécurité
- `validate_token(token_data)` : Validation complète token + sécurité  
- `validate_transaction(tx_data)` : Validation complète transaction + sécurité

### Fonctions Utilitaires

#### quick_validate_address(address) → bool
Validation rapide adresse (longueur + pattern Base58)

#### quick_validate_signature(signature) → bool  
Validation rapide signature (longueur + pattern Base58)

#### validate_and_sanitize_string(value, max_length, allow_empty) → (bool, str)
- Nettoyage : trim + suppression caractères de contrôle
- Validation longueur
- Retourne (validité, chaîne nettoyée)

#### create_validation_summary(results) → Dict
Agrège plusieurs ValidationResult en résumé :
- `is_valid` : Validité globale
- `total_validations`, `total_errors`, `total_warnings` : Compteurs
- `errors`, `warnings`, `field_errors` : Listes consolidées
- `summary` : Résumé textuel

## Utilisation et Points d'Entrée

### Instance Globale
```python
default_validator = DataValidator()
```

### Exemples d'Usage Typiques

**Validation adresse simple** :
```python
result = SolanaValidator.validate_address("4DdrfGHGdMjCqVbNtXsEEGL1SryTeMo8KMGWWtZyZVFh")
```

**Validation token complète** :
```python  
token_data = {
    'token_mint': 'So11111111111111111111111111111111111111112',
    'symbol': 'WSOL', 
    'decimals': 9,
    'price_usd': 150.0
}
result = default_validator.validate_token(token_data)
```

**Validation transaction complète** :
```python
tx_data = {
    'signature': 'A' * 88,
    'wallet_address': '4DdrfGHGdMjCqVbNtXsEEGL1SryTeMo8KMGWWtZyZVFh',
    'transaction_type': 'buy',
    'token_amount': 1000,
    'amount': -1.5,  # Dépense SOL pour achat
    'status': 'success'
}  
result = default_validator.validate_transaction(tx_data)
```

## Dépendances et Fallbacks

### Dépendances Externes
- `base58` : Décodage/validation Base58 (optionnel, fallback gracieux)
- `utils.constants` : Constants du projet (fallback sur constants par défaut)

### Imports Standards  
- `re`, `time`, `json`, `hashlib` : Traitement données
- `typing` : Annotations de types
- `decimal` : Calculs précis
- `urllib.parse` : Validation URLs  
- `dataclasses`, `enum` : Structures de données

## Tests et Validation

Le module inclut un section `if __name__ == "__main__"` avec tests basiques :
- Test validation adresse valide/invalide
- Test validation token avec données complètes  
- Test validation transaction avec cohérence métier
- Affichage résultats et warnings

## Points Clés d'Architecture

1. **Modularité** : Validateurs spécialisés par domaine (Solana, Token, Transaction, etc.)
2. **Niveaux de validation** : Adaptation stricte/standard/souple selon contexte  
3. **Gestion d'erreurs** : Distinction erreurs (invalidantes) vs warnings (informatifs)
4. **Sécurité** : Validations spécialisées anti-fraude et détection patterns suspects
5. **Performance** : Fonctions de validation rapide pour cas simples
6. **Robustesse** : Fallbacks gracieux sur dépendances manquantes
7. **Cohérence métier** : Validation des règles business au-delà de la syntaxe

Cette architecture permet une validation complète et graduée des données blockchain Solana, adaptée aux besoins spécifiques du wallet monitoring avec une attention particulière à la sécurité et la détection de fraudes.