
# 📘 Solana Wallet Monitor – Documentation des Schémas API

## ✨ Introduction

Ce module définit les **schémas de validation, de requêtes et de réponses** pour une API de monitoring de wallets sur Solana.

Fonctionnalités incluses :

- Validation des formats d'adresse, signature et symboles
- Définition des structures de requêtes et réponses API
- Filtres avancés pour wallets et transactions
- Utilitaires pour la pagination, nettoyage et contrôle métier

---

## 🔐 Patterns de validation

```python
SOLANA_ADDRESS_PATTERN = r'^[1-9A-HJ-NP-Za-km-z]{44}$'
SOLANA_SIGNATURE_PATTERN = r'^[1-9A-HJ-NP-Za-km-z]{88}$'
TOKEN_SYMBOL_PATTERN = r'^[A-Z][A-Z0-9_]{0,10}$'
```

---

## ⚠️ ValidationError & ValidationResult

### ValidationError

Exception personnalisée pour erreurs de validation.

```python
ValidationError(message: str, field: Optional[str] = None)
```

### ValidationResult

Conteneur de validation :

- `is_valid: bool`
- `errors: List[str]`
- `warnings: List[str]`

Méthodes :

```python
add_error(message: str, field: Optional[str] = None)
add_warning(message: str, field: Optional[str] = None)
```

---

## 📤 Schémas de requêtes API

### WalletPriorityUpdateRequest

Met à jour le score de priorité d’un wallet.

| Champ            | Type           | Description                              |
|------------------|----------------|------------------------------------------|
| `wallet_address` | `str`          | Adresse Solana                           |
| `priority_score` | `float`        | Score entre 0.1 et 10.0                  |
| `reason`         | `Optional[str]`| Raison optionnelle (max 255 caractères)  |

### BatchingConfigRequest

Configuration du batching des requêtes.

| Champ                      | Type                 | Description                                |
|---------------------------|----------------------|--------------------------------------------|
| `enabled`                 | `Optional[bool]`     | Active/désactive le batching               |
| `batch_sizes`             | `Optional[Dict]`     | Méthodes valides : `getMultipleAccounts`, etc. |
| `min_delay_between_batches` | `Optional[float]` | 0 à 10 secondes                            |
| `max_concurrent_batches`  | `Optional[int]`      | 1 à 10                                     |
| `batch_timeout`           | `Optional[int]`      | 5 à 120 secondes                           |
| `adaptive_sizing`         | `Optional[bool]`     | Active l'adaptation automatique            |

### SelectionModeRequest

Change le mode de sélection des wallets.

| Champ                  | Type            | Description                                |
|------------------------|-----------------|--------------------------------------------|
| `mode`                 | `str`           | `priority` ou `random`                     |
| `weighted_by_priority` | `Optional[bool]`| Pondération par priorité                   |
| `min_interval`         | `Optional[int]` | Intervalle min. entre sélections (10–3600s)|

### DatabaseCleanupRequest

Nettoyage de tables de base de données.

| Champ     | Type             | Description                                  |
|-----------|------------------|----------------------------------------------|
| `days`    | `int`            | Nombre de jours de conservation (1–365)     |
| `tables`  | `Optional[List]` | Tables autorisées : `scan_history`, etc.     |
| `dry_run` | `bool`           | Simulation sans suppression réelle           |
| `confirm` | `bool`           | Requiert confirmation si `dry_run` est False |

### TokenMetadataRequest

Requête pour récupérer les métadonnées d’un token.

| Champ           | Type    | Description                                  |
|------------------|---------|----------------------------------------------|
| `mint_address`   | `str`   | Adresse mint (44 caractères, base58)         |
| `force_refresh`  | `bool`  | Forcer la mise à jour                        |
| `include_price`  | `bool`  | Inclure les données de prix dans la réponse  |

---

## 📥 Schémas de réponses API

### ApiResponse

Réponse standardisée.

```python
ApiResponse(
    success: bool,
    message: str,
    data: Optional[Any],
    timestamp: int,
    errors: Optional[List[str]],
    warnings: Optional[List[str]]
)
```

### PaginatedResponse

Réponse paginée.

| Champ         | Type       |
|---------------|------------|
| `items`       | `List[Any]`|
| `total_count` | `int`      |
| `page`        | `int`      |
| `page_size`   | `int`      |
| `has_next`    | `bool`     |
| `has_previous`| `bool`     |
| `total_pages` | `int` (calculé automatiquement) |

### HealthCheckResponse

Statut global de l’API (health check).

| Champ             | Type             | Description                              |
|-------------------|------------------|------------------------------------------|
| `status`          | `str`            | `healthy`, `degraded`, `critical`        |
| `timestamp`       | `int`            | Timestamp Unix                           |
| `version`         | `str`            | Version de l’API                         |
| `uptime_seconds`  | `int`            | Uptime depuis démarrage                  |
| `checks`          | `Dict`           | Détails par service                      |
| `system_stats`    | `Optional[Dict]` | Statistiques système optionnelles        |

---

## 🔍 Filtres et Recherche

### WalletFilterParams

| Champ                | Type            | Description                                  |
|----------------------|-----------------|----------------------------------------------|
| `priority_min/max`   | `Optional[float]` | Valeurs entre 0.1 et 10.0                  |
| `priority_category`  | `Optional[str]`  | `high`, `medium`, `low`                     |
| `has_recent_activity`| `Optional[bool]` | Activité récente                            |
| `min_balance`        | `Optional[float]`| Balance minimale                             |
| `scan_status`        | `Optional[str]`  | `ready`, `recent`, `overdue`                |

### TransactionFilterParams

| Champ              | Type             | Description                             |
|--------------------|------------------|-----------------------------------------|
| `wallet_address`   | `Optional[str]`  | Adresse du wallet                       |
| `token_mint`       | `Optional[str]`  | Adresse mint                            |
| `transaction_type` | `Optional[str]`  | `buy`, `sell`, `swap`, etc.             |
| `min_amount`       | `Optional[float]`| Montant minimum                         |
| `max_amount`       | `Optional[float]`| Montant maximum                         |
| `start_time`       | `Optional[int]`  | Timestamp début                         |
| `end_time`         | `Optional[int]`  | Timestamp fin                           |
| `is_large_amount`  | `Optional[bool]` | Montant élevé ?                         |
| `status`           | `Optional[str]`  | `success`, `failed`, `pending`, etc.    |

### PaginationParams

| Champ         | Type           | Description                        |
|---------------|----------------|------------------------------------|
| `page`        | `int`          | Page ≥ 1                           |
| `page_size`   | `int`          | Taille de page (1 à 1000)          |
| `sort_by`     | `Optional[str]`| Clé de tri                         |
| `sort_order`  | `str`          | `asc` ou `desc`                    |

---

## ✅ Validations Métiers

### WalletValidation

```python
validate_address(address: str) -> ValidationResult
validate_priority_score(score: float) -> ValidationResult
```

### TokenValidation

```python
validate_mint_address(mint: str) -> ValidationResult
validate_token_symbol(symbol: str) -> ValidationResult
validate_decimals(decimals: int) -> ValidationResult
```

### TransactionValidation

```python
validate_signature(signature: str) -> ValidationResult
validate_amount(amount: float, field_name: str = "amount") -> ValidationResult
```

---

## 🛠 Utilitaires de validation

### validate_time_range(start_time, end_time, max_range_hours=168)

Valide une plage temporelle cohérente.

### validate_pagination_with_total(pagination, total_count)

Valide les paramètres de pagination par rapport au nombre total d'éléments.

### sanitize_string_input(value, max_length=255, allow_empty=False)

Nettoie une chaîne (trim, contrôle de longueur, caractères non imprimables).

### create_error_response / create_success_response

Génèrent des objets `ApiResponse` standardisés.

---

## 🧩 Dépendances externes

- `base58` (facultatif) : pour décodage d’adresse Solana
- `re`, `time`, `dataclasses`, `typing` : intégrés

---

## 🧪 Exemple d'utilisation

```python
req = WalletPriorityUpdateRequest(wallet_address="...", priority_score=2.0)
result = req.validate()
if not result.is_valid:
    return create_error_response("Validation failed", result.errors)
```

---

## 📚 Résumé

Ce module fournit un socle robuste pour structurer, valider et répondre aux appels d'une API Solana Wallet Monitor. Il centralise toute la logique de validation et structure de données côté backend.
