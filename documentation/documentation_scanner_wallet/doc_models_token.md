# Documentation - Modèles de Données Tokens Solana

## Vue d'ensemble

Ce module définit les modèles de données pour la gestion des tokens Solana dans le système de monitoring de wallets. Il inclut trois classes principales pour représenter les métadonnées de tokens, les comptes de tokens associés (ATA), et les découvertes de nouveaux tokens, ainsi qu'un ensemble complet de fonctions utilitaires pour l'analyse et la gestion des tokens.

## Constantes et Configuration

### Adresses Spéciales
- **Wrapped SOL**: `"So11111111111111111111111111111111111111112"`
- **Token Program Standard**: `"TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"`

### Stablecoins Reconnus
- **Liste**: `['USDC', 'USDT', 'BUSD', 'DAI', 'FRAX', 'UST']`

## Modèles de Données Principaux

### Token
Représente les métadonnées complètes d'un token Solana.

#### Champs Principaux
- **address** (str): Adresse de mint du token (44 caractères, Base58)
- **symbol** (str): Symbole du token (défaut: 'UNKNOWN')
- **name** (str): Nom complet du token (défaut: 'Unknown Token')
- **decimals** (int): Nombre de décimales (0-18, défaut: 9)
- **price_usd** (float, optionnel): Prix actuel en USD
- **logo_uri** (str, optionnel): URL du logo du token
- **coingecko_id** (str, optionnel): Identifiant CoinGecko
- **is_verified** (bool): Token vérifié (défaut: False)

#### Données de Marché
- **market_cap** (float, optionnel): Capitalisation de marché
- **volume_24h** (float, optionnel): Volume de trading 24h
- **price_change_24h** (float, optionnel): Changement de prix 24h en %
- **last_price_update** (int, optionnel): Timestamp dernière MAJ prix

#### Métadonnées
- **metadata_source** (str): Source des métadonnées (défaut: 'unknown')
- **updated_at** (int): Timestamp de dernière mise à jour (auto-généré)

#### Validation Post-Initialisation
- **Adresse**: Présence et longueur exacte de 44 caractères
- **Décimales**: Plage valide 0-18

#### Propriétés Calculées

##### mint_short
- **Type**: str
- **Description**: Version abrégée du mint address (6 premiers + 6 derniers caractères)
- **Format**: `"ABC123...XYZ789"`

##### is_stablecoin
- **Type**: bool
- **Description**: Détecte si le token est un stablecoin basé sur le symbole
- **Logique**: Comparaison avec liste de stablecoins connus

##### is_wrapped_sol
- **Type**: bool
- **Description**: Détecte si c'est du SOL wrappé
- **Logique**: Comparaison avec adresse officielle wSOL

##### price_age_hours
- **Type**: float
- **Description**: Âge du prix en heures depuis last_price_update
- **Défaut**: 999999 si pas de timestamp

##### is_price_fresh
- **Type**: bool
- **Description**: Prix considéré comme récent (< 1 heure)

#### Méthodes Principales

##### format_amount(raw_amount: float, compact: bool = False)
- **Description**: Formate un montant de ce token pour affichage
- **Logique**:
  - Conversion selon décimales du token
  - Mode compact: suffixes K/M pour gros montants
  - Adaptation précision selon montant
  - Retours: "0", "1,234.5678", "1.23M", "0.00000123"

##### get_usd_value(token_amount: float)
- **Description**: Calcule valeur USD d'un montant de token
- **Conditions**: Prix disponible ET récent
- **Retour**: float ou None

##### update_price(new_price: float, source: str = 'unknown')
- **Description**: Met à jour le prix avec calcul du changement 24h
- **Actions**:
  - MAJ price_usd, last_price_update, metadata_source, updated_at
  - Calcul price_change_24h si ancien prix disponible
- **Retour**: bool (succès/échec)

##### to_dict()
- **Description**: Sérialisation complète pour API/JSON
- **Inclut**: Tous les champs + propriétés calculées

### TokenAccount
Représente un compte de token associé (ATA) lié à un wallet spécifique.

#### Identifiants
- **wallet_address** (str): Adresse du wallet propriétaire
- **ata_pubkey** (str): Clé publique du compte ATA
- **token_mint** (str): Adresse de mint du token
- **decimals** (int): Décimales du token (défaut: 9)

#### État et Balance
- **balance** (float): Balance brute du token (défaut: 0.0)
- **is_active** (bool): Compte actif (défaut: True)

#### Timestamps
- **first_seen** (int): Première découverte (auto-généré)
- **last_updated** (int): Dernière MAJ balance (auto-généré)
- **last_scanned** (int, optionnel): Dernier scan
- **last_activity_time** (int, optionnel): Dernière activité détectée

#### Priorité et Activité
- **scan_priority** (int): Priorité de scan (1-5, défaut: 1)
- **activity_score** (float): Score d'activité (0-10, défaut: 0.0)
- **total_transactions** (int): Nombre total de transactions (défaut: 0)

#### Validation Post-Initialisation
- **Toutes les adresses**: Longueur exacte de 44 caractères

#### Propriétés Calculées

##### wallet_short, ata_short, mint_short
- **Type**: str
- **Description**: Versions abrégées des adresses
- **Format**: 6 premiers + 6 derniers caractères

##### display_balance
- **Type**: float
- **Description**: Balance formatée selon les décimales
- **Logique**: Division par 10^decimals si balance > 1

##### has_balance
- **Type**: bool
- **Description**: Balance non-nulle

##### hours_since_scan
- **Type**: float
- **Description**: Heures depuis dernier scan
- **Défaut**: 999999 si jamais scanné

##### needs_scan
- **Type**: bool
- **Description**: Détermine nécessité de scan
- **Logique**:
  - Jamais scanné: True
  - Priorité ≥ 3: True
  - Plus de 30 minutes: True
  - Sinon: False

##### priority_label
- **Type**: str
- **Description**: Label textuel de priorité
- **Mapping**: 4+="CRITICAL", 3="HIGH", 2="MEDIUM", 1="LOW"

#### Méthodes Principales

##### update_balance(new_balance: float)
- **Description**: Met à jour la balance avec détection d'activité
- **Actions**:
  - MAJ balance et last_updated
  - Si changement significatif (> 0.000001):
    - MAJ last_activity_time
    - Incrémente activity_score (max 10)
    - Incrémente total_transactions
- **Retour**: float (changement de balance)

##### mark_scanned()
- **Description**: Marque comme scanné avec réduction progressive de priorité
- **Actions**:
  - MAJ last_scanned
  - Réduction priorité si > 1 (décrémente de 1)

##### boost_priority(reason: str = "activity")
- **Description**: Augmente la priorité selon la raison
- **Logique**:
  - "new_account": priorité = 5
  - "activity": +1 (max 4)
  - "large_balance": +2 (max 4)

##### deactivate()
- **Description**: Désactive le compte
- **Actions**: is_active = False, scan_priority = 0

##### to_dict()
- **Description**: Sérialisation complète avec propriétés calculées

### TokenDiscovery
Représente la découverte d'un nouveau token dans un wallet.

#### Données de Découverte
- **token_mint** (str): Adresse de mint du token découvert
- **wallet_address** (str): Adresse du wallet
- **discovered_at** (int): Timestamp de découverte
- **ata_pubkey** (str): Adresse du compte ATA
- **initial_balance** (float): Balance initiale à la découverte
- **decimals** (int): Décimales du token (défaut: 9)

#### Métadonnées
- **symbol** (str, optionnel): Symbole du token
- **name** (str, optionnel): Nom du token
- **discovery_method** (str): Méthode de découverte (défaut: "balance_scan")
- **confidence_score** (float): Score de confiance (défaut: 1.0)

#### Post-Initialisation
- **Génération automatique** de symbol/name si manquants
- **Format**: `"TOKEN_ABCDEF"` / `"Token ABCDEF"`

#### Propriétés Calculées

##### age_hours
- **Type**: float
- **Description**: Âge de la découverte en heures

##### is_recent
- **Type**: bool
- **Description**: Découverte récente (< 24 heures)

##### display_balance
- **Type**: float
- **Description**: Balance initiale formatée selon décimales

##### wallet_short, mint_short
- **Type**: str
- **Description**: Versions abrégées des adresses

## Fonctions Utilitaires

### Validation

#### validate_token_mint(mint_address: str)
- **Description**: Valide une adresse de mint token Solana
- **Validation**:
  - Longueur exacte 44 caractères
  - Décodage Base58 (32 bytes) si bibliothèque disponible
  - Fallback: pattern regex Base58
- **Retour**: bool

### Analyse de Montants

#### is_large_token_amount(amount: float, decimals: int)
- **Description**: Détermine si montant considéré comme important
- **Logique progressive**:
  - Montant brut ≥ 100000: True
  - ≤ 2 décimales ET ≥ 10: True
  - ≤ 6 décimales ET ≥ 1000: True
  - ≤ 9 décimales ET ≥ 10000: True
- **Retour**: bool

### Configuration

#### get_token_program_id(mint_address: str)
- **Description**: Retourne Program ID approprié
- **Actuel**: Token Program standard uniquement
- **Futur**: Support Token-2022

#### format_token_symbol(symbol: str)
- **Description**: Nettoie et formate un symbole
- **Traitements**:
  - Conversion majuscules
  - Suppression caractères non-alphanumériques
  - Limitation 10 caractères
  - Défaut "UNKNOWN"

#### create_fallback_token_metadata(mint_address: str)
- **Description**: Crée métadonnées par défaut
- **Génération**:
  - Symbol: `"TOKEN_ABCDEF"`
  - Name: `"Token ABCDEF"`
  - Decimals: 9
  - Source: "fallback"

### Scoring et Analyse

#### calculate_token_importance_score(token_account: TokenAccount, token_meta: Optional[Token])
- **Description**: Calcule score d'importance (0-10)
- **Facteurs**:
  - **Balance**: +3 si non-nulle, +1/+2 bonus selon montant
  - **Activité**: +0.5 par point d'activity_score (max +3)
  - **Transactions**: +0.1 par transaction (max +2)
  - **Vérification**: +1 si token vérifié
  - **Stablecoin**: +1.5 si stablecoin
  - **Inactivité**: -2 max selon ancienneté (1 semaine+)
- **Retour**: float (0.0-10.0)

#### get_token_risk_level(token: Token, token_account: TokenAccount)
- **Description**: Évalue niveau de risque
- **Facteurs de risque** (points):
  - Non vérifié: +2
  - Pas de prix: +1
  - Market cap < 100K: +2
  - Token récent (< 24h): +1
  - Métadonnées fallback: +2
- **Classification**:
  - ≥ 6 points: "HIGH"
  - ≥ 3 points: "MEDIUM"
  - < 3 points: "LOW"

### Détection de Fraudes

#### detect_potential_scam_tokens(tokens: List[Token])
- **Description**: Détecte tokens potentiellement frauduleux
- **Indicateurs de suspicion**:
  - **Mots suspects**: MOON, LAMBO, DOGE, ELON, SAFEMOON, BABY (+1)
  - **Non vérifié + fallback**: +2
  - **Pas de prix/market cap**: +1
  - **Market cap anormale**: < 1K (+2), > 1T (+3)
- **Seuil**: ≥ 3 points = suspect
- **Retour**: List[str] (adresses suspectes)

### Analyse de Portefeuille

#### calculate_token_portfolio_diversity(token_accounts: List[TokenAccount])
- **Description**: Calcule diversité du portefeuille
- **Métrique**: Score basé sur entropie de Shannon
- **Calcul**:
  - Distribution des balances actives
  - Calcul entropie normalisée (0-10)
  - Évaluation risque de concentration
- **Retour**: Dict avec:
  - `diversity_score`: Score 0-10
  - `total_tokens`: Nombre total
  - `active_tokens`: Tokens avec balance
  - `concentration_risk`: 'HIGH' si >50% dans un token
  - `balance_distribution`: Pourcentages

### Recommandations

#### recommend_token_actions(token_account: TokenAccount, token: Token)
- **Description**: Génère recommandations d'actions
- **Types de recommandations**:
  - **Scan prioritaire**: Si pas scanné depuis 24h
  - **Prix manquant**: Si balance significative sans prix
  - **Vérification**: Token non vérifié avec grosse holding
  - **Prise de bénéfices**: Score importance > 8
  - **Monitoring**: Activity score > 5
- **Retour**: List[str] (messages de recommandation)

## Patterns d'Usage

### Création d'un Token
```python
# 1. Création basique
token = Token(
    address="mint_address",
    symbol="SYMBOL",
    name="Token Name"
)

# 2. Avec validation automatique
# Lève ValueError si adresse invalide

# 3. Mise à jour prix
success = token.update_price(1.50, "coingecko")
```

### Gestion d'un TokenAccount
```python
# 1. Création
account = TokenAccount(
    wallet_address="wallet_addr",
    ata_pubkey="ata_addr", 
    token_mint="mint_addr"
)

# 2. Mise à jour balance
balance_change = account.update_balance(1000.0)

# 3. Gestion priorité
account.boost_priority("new_account")
account.mark_scanned()

# 4. Vérification scan
if account.needs_scan:
    # Scanner le compte
```

### Analyse Complète
```python
# 1. Score d'importance
importance = calculate_token_importance_score(account, token)

# 2. Niveau de risque
risk = get_token_risk_level(token, account)

# 3. Recommandations
actions = recommend_token_actions(account, token)

# 4. Détection fraudes
suspicious = detect_potential_scam_tokens([token])
```

## États et Transitions

### Priorités de Scan
- **0**: Désactivé
- **1**: LOW - Scan routinier
- **2**: MEDIUM - Scan régulier
- **3**: HIGH - Scan fréquent
- **4**: CRITICAL - Scan immédiat
- **5**: Nouveau compte (temporaire)

### Cycle de Vie d'un TokenAccount
1. **Découverte**: Priorité = 5, needs_scan = True
2. **Premier scan**: Priorité réduite, last_scanned mis à jour
3. **Activité détectée**: Boost priorité, MAJ scores
4. **Inactivité**: Réduction progressive priorité
5. **Balance nulle longue**: Désactivation possible

### États de Fraîcheur Prix
- **Frais**: < 1 heure
- **Acceptable**: 1-24 heures  
- **Périmé**: > 24 heures
- **Absent**: Pas de last_price_update

## Intégrations et Dépendances

### Bibliothèques Standard
- `dataclasses`: Structures de données
- `typing`: Annotations de type
- `datetime`: Gestion temporelle
- `time`: Timestamps Unix
- `math`: Calculs entropie
- `re`: Nettoyage symboles

### Bibliothèques Optionnelles
- `base58`: Validation avancée adresses (graceful degradation)

### Compatibilité
- Support Token Program standard
- Préparé pour Token-2022 (futur)
- Intégration CoinGecko ready
- Format API standardisé (to_dict)