# Documentation - Schémas de Validation API Solana Wallet Monitor

## Vue d'ensemble

Ce module fournit un système complet de validation de données pour l'API du Solana Wallet Monitor. Il définit des schémas de validation pour toutes les requêtes et réponses API, avec des contrôles métier spécialisés pour les adresses Solana, tokens, et transactions.

## Patterns de Validation

### Expressions Régulières
- **SOLANA_ADDRESS_PATTERN**: `^[1-9A-HJ-NP-Za-km-z]{44}$` - Validation des adresses Solana (Base58, 44 caractères)
- **SOLANA_SIGNATURE_PATTERN**: `^[1-9A-HJ-NP-Za-km-z]{88}$` - Validation des signatures de transaction (Base58, 88 caractères)
- **TOKEN_SYMBOL_PATTERN**: `^[A-Z][A-Z0-9_]{0,10}$` - Validation des symboles de token (majuscules, max 10 chars)

## Classes de Base

### ValidationError
Exception personnalisée pour les erreurs de validation.
- **Attributs**: `message` (str), `field` (str, optionnel)

### ValidationResult
Conteneur pour les résultats de validation.
- **Attributs**:
  - `is_valid` (bool): État de validation
  - `errors` (List[str]): Liste des erreurs
  - `warnings` (List[str]): Liste des avertissements
- **Méthodes**:
  - `add_error(message, field=None)`: Ajoute une erreur et invalide le résultat
  - `add_warning(message, field=None)`: Ajoute un avertissement

## Schémas de Requêtes API

### WalletPriorityUpdateRequest
Mise à jour de la priorité d'un wallet.
- **Champs**:
  - `wallet_address` (str): Adresse du wallet (format Solana requis)
  - `priority_score` (float): Score de priorité (0.1 à 10.0)
  - `reason` (str, optionnel): Raison de la mise à jour (max 255 caractères)
- **Validations**:
  - Adresse Solana valide
  - Score dans la plage autorisée
  - Longueur de la raison respectée

### BatchingConfigRequest
Configuration du système de batching.
- **Champs**:
  - `enabled` (bool, optionnel): Activation du batching
  - `batch_sizes` (Dict[str, int], optionnel): Tailles par méthode
  - `min_delay_between_batches` (float, optionnel): Délai minimum (0-10s)
  - `max_concurrent_batches` (int, optionnel): Concurrence max (1-10)
  - `batch_timeout` (int, optionnel): Timeout (5-120s)
  - `adaptive_sizing` (bool, optionnel): Taille adaptative
- **Méthodes de batch supportées**: `getMultipleAccounts`, `token_metadata`, `signatures_batch`, `transactions_batch`
- **Validations**: Tailles (1-100), délais, concurrence, timeouts dans les plages autorisées

### SelectionModeRequest
Configuration du mode de sélection des wallets.
- **Champs**:
  - `mode` (str): Mode de sélection ('priority' ou 'random')
  - `weighted_by_priority` (bool, optionnel): Pondération par priorité
  - `min_interval` (int, optionnel): Intervalle minimum (10-3600s)
- **Validations**: Mode valide, intervalle dans la plage

### DatabaseCleanupRequest
Configuration du nettoyage de base de données.
- **Champs**:
  - `days` (int): Nombre de jours à conserver (1-365, défaut: 30)
  - `tables` (List[str], optionnel): Tables à nettoyer
  - `dry_run` (bool): Mode simulation (défaut: False)
  - `confirm` (bool): Confirmation requise (défaut: False)
- **Tables autorisées**: `scan_history`, `wallet_activity_metrics`, `system_logs`
- **Sécurité**: Confirmation obligatoire pour opérations réelles

### TokenMetadataRequest
Requête de métadonnées de token.
- **Champs**:
  - `mint_address` (str): Adresse de mint du token
  - `force_refresh` (bool): Forcer le rafraîchissement (défaut: False)
  - `include_price` (bool): Inclure le prix (défaut: True)
- **Validations**: Format d'adresse Solana valide

## Schémas de Réponses API

### ApiResponse
Réponse API standardisée.
- **Champs**:
  - `success` (bool): Statut de succès
  - `message` (str): Message descriptif
  - `data` (Any, optionnel): Données de réponse
  - `timestamp` (int): Timestamp Unix (auto-généré)
  - `errors` (List[str], optionnel): Liste des erreurs
  - `warnings` (List[str], optionnel): Liste des avertissements
- **Méthode**: `to_dict()` pour sérialisation JSON

### PaginatedResponse
Réponse paginée avec métadonnées.
- **Champs**:
  - `items` (List[Any]): Éléments de la page
  - `total_count` (int): Nombre total d'éléments
  - `page` (int): Page courante (défaut: 1)
  - `page_size` (int): Taille de page (défaut: 20)
  - `has_next` (bool): Existence page suivante
  - `has_previous` (bool): Existence page précédente
- **Propriété calculée**: `total_pages` - Nombre total de pages
- **Méthode**: `to_dict()` avec métadonnées de pagination

### HealthCheckResponse
Réponse de vérification de santé du système.
- **Champs**:
  - `status` (str): État général ('healthy', 'degraded', 'critical')
  - `timestamp` (int): Timestamp de vérification
  - `version` (str): Version du système
  - `uptime_seconds` (int): Temps de fonctionnement
  - `checks` (Dict[str, Any]): Résultats des vérifications
  - `system_stats` (Dict[str, Any], optionnel): Statistiques système
- **Méthode**: `to_dict()` pour sérialisation

## Schémas de Filtrage

### WalletFilterParams
Paramètres de filtrage pour les wallets.
- **Champs**:
  - `priority_min/max` (float, optionnel): Plage de priorité (0.1-10.0)
  - `priority_category` (str, optionnel): Catégorie ('high', 'medium', 'low')
  - `has_recent_activity` (bool, optionnel): Activité récente
  - `min_balance` (float, optionnel): Balance minimum (≥0)
  - `scan_status` (str, optionnel): Statut ('ready', 'recent', 'overdue')
- **Validations**: Cohérence des plages, valeurs positives, énumérations valides

### TransactionFilterParams
Paramètres de filtrage pour les transactions.
- **Champs**:
  - `wallet_address` (str, optionnel): Adresse du wallet
  - `token_mint` (str, optionnel): Mint du token
  - `transaction_type` (str, optionnel): Type de transaction
  - `min/max_amount` (float, optionnel): Plage de montant
  - `start/end_time` (int, optionnel): Plage temporelle
  - `is_large_amount` (bool, optionnel): Gros montant
  - `status` (str, optionnel): Statut de transaction
- **Types supportés**: 'buy', 'sell', 'transfer', 'transfer_in', 'transfer_out', 'swap', 'stake', 'unstake', 'other'
- **Statuts supportés**: 'success', 'failed', 'pending', 'timeout', 'cancelled'

### PaginationParams
Paramètres de pagination standardisés.
- **Champs**:
  - `page` (int): Numéro de page (≥1, défaut: 1)
  - `page_size` (int): Taille de page (1-1000, défaut: 20)
  - `sort_by` (str, optionnel): Champ de tri
  - `sort_order` (str): Ordre de tri ('asc', 'desc', défaut: 'desc')
- **Propriété calculée**: `offset` - Offset pour base de données
- **Validations**: Page positive, taille dans la plage, ordre valide

## Validations Métier Spécialisées

### WalletValidation
Validation spécialisée pour les wallets Solana.

#### validate_address(address: str)
- **Validations**:
  - Présence de l'adresse
  - Longueur exacte de 44 caractères
  - Format Base58 valide
  - Décodage Base58 (si bibliothèque disponible)
  - Longueur décodée de 32 bytes

#### validate_priority_score(score: float)
- **Validations**: Score dans la plage 0.1-10.0
- **Avertissements**:
  - Score < 0.5: risque d'être ignoré
  - Score > 8.0: risque de sur-scan

### TokenValidation
Validation spécialisée pour les tokens.

#### validate_mint_address(mint: str)
- **Validations**: Identiques aux adresses de wallet
- **Usage**: Validation des adresses de mint de tokens

#### validate_token_symbol(symbol: str)
- **Validations**:
  - Présence du symbole
  - Longueur ≤ 10 caractères
  - Format: lettres majuscules, chiffres, underscore seulement
  - Doit commencer par une lettre

#### validate_decimals(decimals: int)
- **Validations**: Plage 0-18 décimales
- **Avertissement**: Plus de 12 décimales considéré comme inhabituel

### TransactionValidation
Validation spécialisée pour les transactions.

#### validate_signature(signature: str)
- **Validations**:
  - Présence de la signature
  - Longueur exacte de 88 caractères
  - Format Base58 valide

#### validate_amount(amount: float, field_name: str)
- **Validations**: Montant non-négatif
- **Avertissement**: Montant > 1M considéré comme très élevé

## Utilitaires de Validation

### validate_time_range(start_time, end_time, max_range_hours=168)
Validation des plages temporelles.
- **Validations**:
  - Timestamps non-négatifs
  - Cohérence start ≤ end
  - Plage ≤ maximum autorisé (défaut: 168h/1 semaine)

### validate_pagination_with_total(pagination, total_count)
Validation de pagination avec vérification d'existence.
- **Validations**: Page demandée ≤ nombre total de pages calculé

### sanitize_string_input(value, max_length=255, allow_empty=False)
Nettoyage et validation des chaînes.
- **Traitements**:
  - Suppression espaces début/fin
  - Vérification longueur maximale
  - Suppression caractères de contrôle
- **Paramètres**: Longueur max, autorisation valeurs vides

### Fonctions de Réponse Standardisées

#### create_error_response(message, errors=None)
Création de réponse d'erreur standardisée.
- **Retour**: ApiResponse avec success=False

#### create_success_response(message, data=None, warnings=None)
Création de réponse de succès standardisée.
- **Retour**: ApiResponse avec success=True et données optionnelles

## Patterns d'Usage

### Validation Typique
```python
# 1. Créer l'objet de requête
request = WalletPriorityUpdateRequest(...)

# 2. Valider
result = request.validate()

# 3. Vérifier le résultat
if not result.is_valid:
    return create_error_response("Validation failed", result.errors)

# 4. Traiter la requête valide
```

### Gestion des Erreurs
- **ValidationError**: Exception levée pour erreurs critiques
- **ValidationResult**: Conteneur pour erreurs/avertissements multiples
- **ApiResponse**: Format standardisé pour retour API

### Niveaux de Validation
1. **Format**: Patterns regex, types de données
2. **Métier**: Règles spécifiques au domaine
3. **Cohérence**: Relations entre champs
4. **Sécurité**: Prévention d'opérations dangereuses

## Dépendances

### Bibliothèques Standard
- `typing`: Annotations de type
- `dataclasses`: Structures de données
- `enum`: Énumérations
- `re`: Expressions régulières
- `time`: Timestamps

### Bibliothèques Optionnelles
- `base58`: Validation avancée Base58 (graceful degradation si absente)

## Extensibilité

Le système est conçu pour être facilement extensible :
- Nouveaux schémas par dataclass
- Nouvelles validations par méthodes statiques
- Patterns de validation centralisés
- Réponses API standardisées
- Gestion d'erreurs uniforme