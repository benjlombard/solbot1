# Documentation - Modèles de Données Transactions Solana

## Vue d'ensemble

Ce module définit les modèles de données pour la gestion des transactions Solana dans le système de monitoring. Il inclut deux classes principales pour représenter les transactions complètes et les changements de balance détectés, ainsi qu'un ensemble de fonctions utilitaires pour la classification, l'analyse et le calcul de P&L.

## Énumérations

### TransactionType
Types de transactions supportés par le système.

#### Valeurs
- **BUY**: "buy" - Achat de token avec SOL
- **SELL**: "sell" - Vente de token pour SOL
- **TRANSFER**: "transfer" - Transfert générique
- **TRANSFER_IN**: "transfer_in" - Réception de tokens
- **TRANSFER_OUT**: "transfer_out" - Envoi de tokens
- **SWAP**: "swap" - Échange entre tokens
- **STAKE**: "stake" - Mise en stake
- **UNSTAKE**: "unstake" - Retrait de stake
- **LIQUIDITY_ADD**: "liquidity_add" - Ajout de liquidité
- **LIQUIDITY_REMOVE**: "liquidity_remove" - Retrait de liquidité
- **OTHER**: "other" - Autres types non classifiés

### TransactionStatus
Statuts d'exécution des transactions.

#### Valeurs
- **SUCCESS**: "success" - Transaction réussie
- **FAILED**: "failed" - Transaction échouée
- **PENDING**: "pending" - En cours d'exécution
- **TIMEOUT**: "timeout" - Timeout d'exécution
- **CANCELLED**: "cancelled" - Transaction annulée

## Modèles de Données Principaux

### Transaction
Modèle principal pour une transaction Solana complète.

#### Identifiants et Contexte
- **signature** (str): Signature de transaction (88 caractères, Base58)
- **wallet_address** (str): Adresse du wallet concerné (44 caractères)
- **slot** (int): Numéro de slot Solana
- **block_time** (int, optionnel): Timestamp Unix du bloc
- **source** (str): Source de détection (défaut: "unknown")
- **scan_cycle_id** (str, optionnel): ID du cycle de scan

#### Montants et Frais
- **amount** (float): Changement en SOL (défaut: 0.0)
- **fee** (float): Frais de transaction en SOL (défaut: 0.0)
- **status** (TransactionStatus): Statut d'exécution (défaut: SUCCESS)

#### Données Token
- **token_mint** (str, optionnel): Adresse de mint du token
- **token_symbol** (str, optionnel): Symbole du token
- **token_name** (str, optionnel): Nom du token
- **token_amount** (float): Montant de token impliqué (défaut: 0.0)
- **price_per_token** (float): Prix unitaire du token (défaut: 0.0)

#### Classification
- **transaction_type** (TransactionType): Type de transaction (défaut: OTHER)
- **is_token_transaction** (bool): Implique des tokens (défaut: False)
- **is_large_token_amount** (bool): Gros montant de token (défaut: False)

#### Métadonnées de Détection
- **detection_delay** (float): Délai de détection en secondes (défaut: 0.0)
- **wallet_priority_at_detection** (float): Priorité du wallet lors détection (défaut: 1.0)

#### Timestamps
- **created_at** (int): Timestamp de création (auto-généré)
- **updated_at** (int): Timestamp de dernière MAJ (auto-généré)

#### Validation Post-Initialisation
- **Signature**: Longueur exacte de 88 caractères
- **Wallet address**: Longueur exacte de 44 caractères
- **Conversion automatique**: Strings vers enums avec fallback

#### Propriétés Calculées

##### signature_short, wallet_short
- **Type**: str
- **Description**: Versions abrégées des identifiants
- **Format signature**: 8 premiers + 8 derniers caractères
- **Format wallet**: 6 premiers + 6 derniers caractères

##### mint_short
- **Type**: Optional[str]
- **Description**: Version abrégée du mint address si présent
- **Format**: 6 premiers + 6 derniers caractères

##### age_hours
- **Type**: float
- **Description**: Âge de la transaction en heures depuis block_time
- **Défaut**: 0 si pas de block_time

##### is_recent
- **Type**: bool
- **Description**: Transaction récente (< 24 heures)

##### is_buy_transaction, is_sell_transaction, is_transfer_transaction
- **Type**: bool
- **Description**: Tests rapides sur le type de transaction
- **Logique transfer**: Inclut TRANSFER, TRANSFER_IN, TRANSFER_OUT

##### net_sol_change
- **Type**: float
- **Description**: Changement net en SOL après déduction des frais
- **Calcul**: amount - fee

##### total_usd_value
- **Type**: Optional[float]
- **Description**: Valeur USD totale si prix disponible
- **Calcul**: token_amount × price_per_token
- **Retour**: None si données manquantes

##### profit_loss_sol
- **Type**: float
- **Description**: P&L en SOL pour cette transaction
- **Logique**:
  - BUY: -|amount| (dépense)
  - SELL: +|amount| (gain)
  - Autres: amount (tel quel)

#### Méthodes Principales

##### get_display_amount(decimals: Optional[int] = None)
- **Description**: Montant token formaté pour affichage
- **Paramètres**: decimals par défaut = 9
- **Logique**:
  - Si token_amount < 1000: retour direct
  - Sinon: division par 10^decimals
- **Usage**: Gestion des montants bruts vs formatés

##### calculate_detection_delay(scan_time: Optional[int] = None)
- **Description**: Calcule et met à jour le délai de détection
- **Paramètres**: scan_time par défaut = maintenant
- **Retour**: float (secondes de délai)
- **Side effect**: Met à jour self.detection_delay

##### get_transaction_icon(), get_status_icon()
- **Description**: Retourne icônes emoji pour UI
- **Transaction icons**: 🟢 BUY, 🔴 SELL, 🔵 TRANSFER, etc.
- **Status icons**: ✅ SUCCESS, ❌ FAILED, ⏳ PENDING, etc.

##### to_dict()
- **Description**: Sérialisation complète pour API/JSON
- **Inclut**: Tous les champs + propriétés calculées + icônes
- **Format**: Arrondis appropriés pour montants

### BalanceChange
Modèle pour représenter un changement de balance détecté lors du monitoring.

#### Identifiants
- **wallet_address** (str): Adresse du wallet
- **token_mint** (str): Mint du token concerné
- **ata_pubkey** (str): Clé publique du compte ATA
- **decimals** (int): Décimales du token (défaut: 9)

#### Changement de Balance
- **pre_balance** (float): Balance avant changement
- **post_balance** (float): Balance après changement
- **balance_change** (float): Différence calculée

#### Contexte Transactionnel
- **transaction_signature** (str, optionnel): Signature si connue
- **block_time** (int, optionnel): Timestamp du bloc
- **token_symbol** (str, optionnel): Symbole du token
- **token_name** (str, optionnel): Nom du token

#### Classification
- **change_type** (TransactionType, optionnel): Type classifié automatiquement
- **confidence** (float): Score de confiance (défaut: 1.0)
- **detected_at** (int): Timestamp de détection (auto-généré)

#### Propriétés Calculées

##### wallet_short, mint_short
- **Type**: str
- **Description**: Versions abrégées des adresses
- **Format**: 6 premiers + 6 derniers caractères

##### display_pre_balance, display_post_balance, display_change
- **Type**: float
- **Description**: Balances formatées selon les décimales
- **Logique**: Division par 10^decimals si valeur > 1

##### is_increase, is_decrease
- **Type**: bool
- **Description**: Direction du changement de balance

##### is_significant_change
- **Type**: bool
- **Description**: Changement significatif (> 0.000001 en format display)

#### Méthodes Principales

##### classify_change_type(sol_change: float = 0.0)
- **Description**: Classification automatique du type de changement
- **Paramètres**: sol_change pour contexte SOL
- **Logique**:
  - Augmentation + SOL diminué (> 0.001): BUY
  - Augmentation + SOL stable: TRANSFER_IN
  - Diminution + SOL augmenté (> 0.001): SELL
  - Diminution + SOL stable: TRANSFER_OUT
- **Retour**: TransactionType

##### to_transaction(sol_change: float = 0.0, fee: float = 0.0)
- **Description**: Convertit en objet Transaction complet
- **Paramètres**: Contexte SOL et frais
- **Actions**:
  - Classification automatique du type
  - Création Transaction avec métadonnées appropriées
  - Détection gros montant (> 1000)
  - Source = "balance_change"

##### to_dict()
- **Description**: Sérialisation complète pour API/JSON
- **Inclut**: Balances brutes et formatées, métadonnées de classification

## Fonctions Utilitaires

### Validation

#### validate_transaction_signature(signature: str)
- **Description**: Valide une signature de transaction Solana
- **Validations**:
  - Longueur exacte 88 caractères
  - Décodage Base58 (64 bytes) si bibliothèque disponible
  - Fallback: pattern regex Base58
- **Retour**: bool

### Classification

#### classify_transaction_from_amounts(token_change: float, sol_change: float, threshold: float = 0.001)
- **Description**: Classifie une transaction basée sur les changements de montants
- **Paramètres**:
  - token_change: Changement en tokens
  - sol_change: Changement en SOL
  - threshold: Seuil SOL significatif (défaut: 0.001)
- **Logique**: Identique à BalanceChange.classify_change_type()
- **Retour**: TransactionType

### Analyse et Scoring

#### calculate_transaction_importance(transaction: Transaction)
- **Description**: Calcule un score d'importance (0-10)
- **Facteurs de scoring**:
  - **Base**: 1.0
  - **Gros montant SOL**: +min(|amount|, 5.0)
  - **Gros montant token**: +3.0
  - **Trading (BUY/SELL)**: +2.0
  - **Prix disponible**: +1.0
  - **Valeur USD > $100**: +min(usd_value/100, 3.0)
  - **Détection rapide** (< 1min): +1.0, (< 5min): +0.5
  - **Transaction échouée**: ×0.5
- **Retour**: float (0.0-10.0)

### Regroupement et Analyse

#### group_transactions_by_type(transactions: List[Transaction])
- **Description**: Regroupe les transactions par type
- **Retour**: Dict[TransactionType, List[Transaction]]

#### calculate_portfolio_pnl(transactions: List[Transaction])
- **Description**: Calcule le P&L par token à partir des transactions
- **Logique**:
  - Filtre les transactions de tokens uniquement
  - Somme profit_loss_sol par token_mint
  - Ignore les transactions sans mint
- **Retour**: Dict[str, float] (mint_address -> pnl_sol)

## Patterns d'Usage

### Création d'une Transaction
```python
# 1. Création basique
tx = Transaction(
    signature="signature_88_chars",
    wallet_address="wallet_44_chars",
    slot=123456,
    amount=-1.5,  # Dépense SOL
    token_amount=1000,
    transaction_type=TransactionType.BUY
)

# 2. Avec validation automatique
# Lève ValueError si signature/wallet invalides

# 3. Classification automatique
tx_type = classify_transaction_from_amounts(
    token_change=1000,    # Reçu tokens
    sol_change=-1.5       # Dépensé SOL
)  # Retourne BUY
```

### Gestion des BalanceChange
```python
# 1. Création depuis monitoring
change = BalanceChange(
    wallet_address="wallet_addr",
    token_mint="mint_addr",
    ata_pubkey="ata_addr",
    pre_balance=1000000000,  # Montant brut
    post_balance=2000000000,  # Montant brut
    balance_change=1000000000
)

# 2. Classification automatique
change_type = change.classify_change_type(sol_change=-1.5)

# 3. Conversion en Transaction
tx = change.to_transaction(
    sol_change=-1.5,
    fee=0.0005
)
```

### Analyse de Portefeuille
```python
# 1. Calcul importance
importance = calculate_transaction_importance(transaction)

# 2. Regroupement par type
grouped = group_transactions_by_type(transactions)
buy_txs = grouped.get(TransactionType.BUY, [])

# 3. Calcul P&L
pnl = calculate_portfolio_pnl(transactions)
total_pnl = sum(pnl.values())
```

## Logiques de Classification

### Classification Buy/Sell
La distinction entre achat et vente se base sur les flux combinés de tokens et SOL :

#### Achat (BUY)
- **Token**: Augmentation (réception)
- **SOL**: Diminution significative (> threshold)
- **Interprétation**: Achat de tokens avec SOL

#### Vente (SELL)
- **Token**: Diminution (envoi)
- **SOL**: Augmentation significative (> threshold)
- **Interprétation**: Vente de tokens pour SOL

#### Transferts
- **TRANSFER_IN**: Réception tokens sans changement SOL significatif
- **TRANSFER_OUT**: Envoi tokens sans gain SOL significatif

### Seuils de Significativité

#### Changements SOL
- **Threshold par défaut**: 0.001 SOL
- **Justification**: Couvre frais de transaction typiques

#### Changements Tokens
- **Threshold display**: 0.000001 (après formatage)
- **Justification**: Précision suffisante pour la plupart des tokens

#### Gros Montants
- **Tokens**: > 1000 (après formatage)
- **SOL**: > 1.0
- **USD**: > $100

## États et Transitions

### Cycle de Vie d'une Transaction
1. **Détection**: Création depuis balance change ou API
2. **Classification**: Détermination du type automatique
3. **Enrichissement**: Ajout prix, métadonnées token
4. **Calcul importance**: Score pour priorisation
5. **Archivage**: Stockage avec métadonnées complètes

### Statuts de Transaction
- **PENDING** → **SUCCESS/FAILED**: Résolution normale
- **PENDING** → **TIMEOUT**: Dépassement délai
- **PENDING** → **CANCELLED**: Annulation utilisateur

## Métriques et KPIs

### Délai de Détection
- **Optimal**: < 60 secondes
- **Acceptable**: < 300 secondes
- **Dégradé**: > 300 secondes

### Score d'Importance
- **0-2**: Transactions mineures
- **3-5**: Transactions notables
- **6-8**: Transactions importantes
- **9-10**: Transactions critiques

### P&L Tracking
- **Par token**: Cumul des profit_loss_sol
- **Positif**: Gains nets en SOL
- **Négatif**: Pertes nettes en SOL

## Intégrations et Dépendances

### Bibliothèques Standard
- `dataclasses`: Structures de données
- `typing`: Annotations de type
- `datetime`: Gestion temporelle (importé mais peu utilisé)
- `time`: Timestamps Unix
- `enum`: Énumérations typées

### Bibliothèques Optionnelles
- `base58`: Validation avancée signatures (graceful degradation)

### Compatibilité
- Support tous types de transactions Solana
- Extensible pour nouveaux types (DEX, NFT, etc.)
- Format API standardisé (to_dict)
- Intégration prête pour UI (icônes, formatage)