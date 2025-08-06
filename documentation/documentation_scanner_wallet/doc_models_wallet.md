# 📄 Documentation — `models/wallet.py`

Ce module contient les modèles de données pour la surveillance de wallets Solana. Il est organisé autour de plusieurs classes principales avec des fonctions utilitaires associées.

---

## 🧩 Classes principales

### ### `WalletPriority`
Représente la priorité et l'activité d'un wallet pour déterminer sa fréquence de scan.

**Attributs :**
- `wallet_address`: adresse du wallet (44 caractères)
- `priority_score`: score de priorité (0.1 à 10.0)
- `last_scan_time`, `scan_count_1h`, `scan_count_24h`, `activity_score`, `volume_score_1h`
- `new_tokens_score_1h`, `total_scans`, `avg_scan_duration`
- `last_activity_detected`, `consecutive_empty_scans`
- `best_priority_ever`, `worst_priority_ever`
- `priority_history`: historique JSON
- `updated_at`, `created_at`

**Méthodes :**
- `wallet_short`: adresse abrégée
- `priority_category`: retourne `low`, `medium`, `high`
- `scan_interval_seconds`: temps recommandé entre deux scans
- `seconds_since_scan`, `is_ready_for_scan`, `next_scan_in`
- `update_priority()`: ajuste le score en fonction de l'activité détectée
- `to_dict()`: exporte les données

---

### `WalletStats`
Statistiques générales sur un wallet.

**Attributs :**
- `wallet_address`, `balance_sol`, `total_transactions`, `total_volume`
- `pnl`, `largest_transaction`, `token_accounts_count`, `active_tokens_count`
- `new_tokens_24h`, `large_transactions_24h`, `updated_at`

**Méthodes :**
- `wallet_short`: adresse abrégée
- `avg_transaction_size`: moyenne des transactions
- `to_dict()`: exporte les données

---

### `WalletActivityMetrics`
Stocke des métriques détaillées sur une période glissante (par défaut 15 minutes).

**Attributs :**
- `wallet_address`, `timestamp`, `period_minutes`
- `new_transactions_count`, `volume_sol`, `new_token_accounts`, `scan_duration`
- `discoveries_count`, `balance_changes_count`, `rpc_requests_made`, `errors_count`
- `efficiency_score`

**Méthodes :**
- `wallet_short`: adresse abrégée
- `rps`: requêtes RPC par seconde
- `discoveries_per_rpc`: découvertes par RPC
- `calculate_efficiency()`: calcule un score d’efficacité
- `to_dict()`: exporte les données

---

### `ScanHistory`
Historique détaillé d’un scan effectué.

**Attributs :**
- `id`, `wallet_address`, `scan_type`, `total_accounts`, `new_accounts`
- `scan_duration`, `completed_at`, `priority_score_before`, `priority_score_after`
- `rpc_requests_count`, `efficiency_score`, `activity_detected`, `notes`

**Méthodes :**
- `wallet_short`: adresse abrégée
- `priority_change`, `change_direction`, `discovery_rate`
- `to_dict()`: exporte les données

---

## 🛠️ Fonctions utilitaires

### `validate_wallet_address(address: str) -> bool`
Valide qu’une adresse est bien une adresse Solana valide (44 caractères Base58).

### `format_wallet_address(address: str, length: int = 8) -> str`
Formate une adresse pour affichage : exemple `5GhK...fJd8`

### `calculate_wallet_score(priority: WalletPriority, stats: WalletStats) -> float`
Retourne un score agrégé basé sur :
- activité récente
- volume total
- diversité de tokens
- temps depuis la dernière activité

---

## 🧠 Remarques

- Le score de priorité permet d’ajuster dynamiquement la fréquence de scan de chaque wallet.
- Le système est conçu pour être extensible avec d’autres modèles (PNL, analyse des jetons, risques, etc.).
