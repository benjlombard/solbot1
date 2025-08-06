# Documentation Solana Wallet Monitor v2.0 Optimized

## Vue d'ensemble

Le **Solana Wallet Monitor** est un système de surveillance intelligent pour portefeuilles Solana qui détecte automatiquement les nouveaux tokens, balance changes et transactions avec un système de priorités dynamiques et du batching RPC optimisé.

## Architecture Système

### Composants Principaux

1. **SolanaWalletMonitor** - Classe principale de monitoring
2. **BatchRPCManager** - Gestionnaire de requêtes RPC par batch
3. **ThreadSafeSQLiteManager** - Gestionnaire de base de données thread-safe
4. **Flask API** - Interface web et API REST
5. **Système de Priorités Dynamiques** - Algorithme intelligent de sélection des wallets

### Flux de Données

```
Configuration → Initialisation DB → Système Priorités → Boucle Monitoring → API Dashboard
```

## Configuration (Config Class)

### Paramètres Core
- `WALLET_ADDRESSES`: Liste des adresses à surveiller
- `QUICKNODE_ENDPOINT`: Endpoint RPC principal Solana
- `UPDATE_INTERVAL`: Intervalle entre scans (45s défaut)
- `DB_NAME`: Nom fichier SQLite ("solana_wallet.db")
- `RATE_LIMIT_DELAY`: Délai entre requêtes RPC (0.2s)

### Configuration Batching RPC
- `ENABLE_RPC_BATCHING`: Active/désactive le batching (bool)
- `BATCH_SIZES`: Tailles optimales par type de requête
  - `getMultipleAccounts`: 8
  - `token_metadata`: 5 
  - `signatures_batch`: 12
  - `transactions_batch`: 6

### Configuration Timing Batch
- `min_delay_between_batches`: 0.3s minimum entre batches
- `max_concurrent_batches`: 1 (séquentiel)
- `batch_timeout`: 25s timeout par batch
- `adaptive_sizing`: Ajustement automatique des tailles

### Configuration Sélection Wallets
- `WALLET_SELECTION_MODE`: "priority" ou "random"
- `RANDOM_SELECTION_WEIGHT_BY_PRIORITY`: Pondération par priorité
- `MIN_INTERVAL_BETWEEN_SCANS`: Intervalle minimum (30s)

## Base de Données SQLite

### Tables Principales

#### transactions
```sql
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY,
    signature TEXT UNIQUE,
    wallet_address TEXT,
    slot INTEGER,
    block_time INTEGER,
    amount REAL,
    token_mint TEXT,
    token_symbol TEXT,
    token_name TEXT,
    transaction_type TEXT, -- 'buy', 'sell', 'transfer'
    token_amount REAL,
    price_per_token REAL,
    fee REAL,
    status TEXT,
    is_token_transaction BOOLEAN,
    is_large_token_amount BOOLEAN,
    detection_delay REAL,
    wallet_priority_at_detection REAL,
    scan_cycle_id TEXT
)
```

#### token_accounts
```sql
CREATE TABLE token_accounts (
    wallet_address TEXT,
    ata_pubkey TEXT, -- Associated Token Account
    token_mint TEXT,
    balance REAL,
    decimals INTEGER,
    first_seen INTEGER,
    last_updated INTEGER,
    last_scanned INTEGER,
    is_active BOOLEAN,
    scan_priority INTEGER, -- 1=normal, 3=nouveau compte
    activity_score REAL,
    last_activity_time INTEGER,
    PRIMARY KEY (wallet_address, ata_pubkey)
)
```

#### wallet_priorities
```sql
CREATE TABLE wallet_priorities (
    wallet_address TEXT PRIMARY KEY,
    priority_score REAL, -- 0.1-10.0
    last_scan_time INTEGER,
    total_scans INTEGER,
    avg_scan_duration REAL,
    activity_score REAL,
    consecutive_empty_scans INTEGER,
    last_activity_detected INTEGER,
    updated_at INTEGER
)
```

#### wallet_activity_metrics
```sql
CREATE TABLE wallet_activity_metrics (
    wallet_address TEXT,
    timestamp INTEGER,
    period_minutes INTEGER,
    scan_duration REAL,
    discoveries_count INTEGER,
    balance_changes_count INTEGER,
    rpc_requests_made INTEGER,
    efficiency_score REAL,
    volume_sol REAL,
    errors_count INTEGER
)
```

#### scan_history
```sql
CREATE TABLE scan_history (
    wallet_address TEXT,
    scan_type TEXT, -- 'full', 'incremental', 'balance_change'
    total_accounts INTEGER,
    new_accounts INTEGER,
    scan_duration REAL,
    completed_at INTEGER,
    priority_score_before REAL,
    priority_score_after REAL,
    rpc_requests_count INTEGER,
    efficiency_score REAL,
    notes TEXT
)
```

## Classes Principales

### SolanaWalletMonitor

#### Méthodes Core
- `__init__(wallet_addresses, db_name)`: Initialisation avec BatchManager
- `monitor_loop()`: Boucle principale de monitoring intelligente
- `discover_token_accounts(wallet, force_full_scan)`: Découverte comptes tokens
- `scan_balance_changes_for_accounts(wallet, accounts)`: Scan balance changes
- `get_next_wallet_to_scan()`: Sélection wallet selon priorité/aléatoire

#### Méthodes RPC
- `rate_limited_rpc_call(method, params)`: Appel RPC avec rate limiting
- `get_solana_rpc_data(method, params)`: Appel RPC avec fallbacks
- `get_token_metadata(mint_address)`: Récupération métadonnées Jupiter

#### Méthodes Priorités
- `initialize_wallet_priorities()`: Calcul priorités initiales
- `get_priority_wallet_to_scan()`: Sélection par priorité
- `get_random_wallet_to_scan()`: Sélection aléatoire
- `update_wallet_priority(wallet, duration, discoveries, transactions)`: MAJ priorité

### BatchRPCManager

#### Méthodes Principales
- `batch_get_multiple_accounts(addresses)`: Batch getMultipleAccounts
- `batch_get_signatures_for_addresses(addresses)`: Batch signatures
- `adaptive_batch_size(method)`: Calcul taille optimale
- `get_batch_stats()`: Statistiques performance

#### Métriques Tracking
- `total_batches`, `successful_batches`, `failed_batches`
- `avg_response_time`, `rate_limit_hits`, `fallback_count`
- `current_batch_sizes`: Tailles adaptatives par méthode

### ThreadSafeSQLiteManager

#### Configuration SQLite
- Mode WAL pour concurrence
- `busy_timeout=30000`
- `synchronous=NORMAL`
- Context manager avec retry automatique

## Algorithme de Priorités Dynamiques

### Calcul du Score de Priorité

#### Score Initial (0.1-10.0)
```
base_score = 1.0
+ activité récente (max +3.0)
+ volume transactions (max +2.0) 
+ nouveaux comptes découverts (max +1.5)
+ portefeuille actif >20 comptes (max +1.0)
```

#### Mise à Jour après Scan
```
SI activité_détectée:
    nouveau_score = ancien_score + bonus_activité + bonus_découvertes - malus_lenteur
    scans_vides_consécutifs = 0
SINON:
    nouveau_score = max(0.5, ancien_score * 0.95 - malus_scans_vides)
    scans_vides_consécutifs += 1
```

### Intervalles de Scan par Priorité
- **Score ≥ 4.0**: 30 secondes (Haute priorité 🔥)
- **Score ≥ 2.0**: 90 secondes (Moyenne priorité 🟡)
- **Score < 2.0**: 180 secondes (Basse priorité 🔵)

## Boucle de Monitoring Intelligente

### Étapes d'un Cycle

#### 1. Sélection du Wallet
```python
if WALLET_SELECTION_MODE == "random":
    wallet = get_random_wallet_to_scan()  # Avec/sans pondération priorité
else:
    wallet = get_priority_wallet_to_scan()  # Par score priorité
```

#### 2. Découverte des Comptes de Tokens
- **Scan Complet**: Tous les 6h ou si force_full_scan
- **Scan Incrémental**: Vérification comptes existants + nouveaux
- Utilise `getTokenAccountsByOwner` avec batching si activé

#### 3. Identification Comptes Prioritaires
```python
priority_accounts = get_priority_accounts_for_scanning(wallet, limit=100)
# Critères: jamais_scannés OU >15min OU priority≥3
```

#### 4. Scan Balance Changes
- Récupération signatures récentes par batch
- Analyse `preTokenBalances` vs `postTokenBalances`
- Détection types: 'buy', 'sell', 'transfer'

#### 5. Sauvegarde et Métriques
- Évitement doublons par signature
- Calcul délai détection
- Mise à jour priorité wallet
- Enregistrement métriques performance

### Pause Adaptative
```python
if new_transactions > 0:
    pause = 10  # Activité détectée = haute fréquence
elif new_accounts > 0:
    pause = 20  # Nouvelles découvertes = moyenne fréquence
else:
    pause = 25  # Scan propre = fréquence normale
```

## API Flask Dashboard

### Endpoints Principaux

#### Stats et Dashboard
- `GET /api/dashboard-data`: Données principales dashboard
- `GET /api/wallet-summary`: Résumé par wallet
- `GET /api/recent-balance-changes`: Balance changes récents

#### Système de Priorités
- `GET /api/wallet-priorities`: État priorités actuelles
- `GET /api/next-scans`: Planification prochains scans
- `GET /api/priority-analytics`: Analytics avancées priorités
- `POST /api/manual-priority-update`: Modification manuelle priorité

#### Performance et Batching
- `GET /api/batching-performance`: Métriques batching RPC
- `GET /api/scan-efficiency`: Efficacité des scans
- `POST /api/batching-config`: Configuration batching

#### Sélection Wallets
- `GET /api/selection-mode`: Mode sélection actuel
- `POST /api/selection-mode`: Changement de mode
- `GET /api/selection-stats`: Statistiques sélection

## Optimisations Performance

### Batching RPC
- **Signatures**: Jusqu'à 12 adresses par batch
- **Comptes**: Jusqu'à 8 comptes par batch  
- **Délai adaptatif**: 0.3s minimum entre batches
- **Fallback automatique**: En cas d'échec batch

### Gestion Rate Limits
- Monitoring temps réponse
- Réduction taille batch si >5s réponse
- Changement endpoint si rate limit (429)
- Pause progressive si erreurs consécutives

### Base de Données
- Index optimisés sur colonnes fréquemment requêtées
- Mode WAL pour concurrence
- Nettoyage automatique anciennes métriques
- Connection pooling thread-safe

## Métriques et Monitoring

### Performance Batching
- `success_rate`: % succès batches
- `avg_response_time`: Temps réponse moyen
- `time_saved_estimate`: Temps économisé estimé
- `rate_limit_status`: Statut rate limits

### Efficacité Scans
- `efficiency_score`: (découvertes + transactions) / requêtes_RPC
- `discoveries_per_scan`: Nouvelles découvertes moyennes
- `detection_delay`: Délai détection transactions

### Analytics Priorités
- Distribution par tiers priorité (high/medium/low)
- Évolution priorités par heure
- Top performers par découvertes
- Métriques système globales

## Gestion des Erreurs

### Stratégies de Récupération
- **Erreurs RPC**: Rotation automatique endpoints
- **Rate Limits**: Pause progressive + réduction batch
- **DB Lock**: Retry avec backoff exponentiel
- **Erreurs consécutives**: Mode récupération (pause 2min)

### Logging Structuré
```python
# Niveaux: DEBUG, INFO, WARNING, ERROR, CRITICAL
# Format: timestamp - level - [function:line] - message
# Outputs: fichier 'wallet_monitor.log' + console
```

## Configuration Avancée

### Modes de Sélection
1. **Priority Mode**: Sélection par score priorité décroissant
2. **Random Mode**: Sélection aléatoire équiprobable
3. **Weighted Random**: Aléatoire pondéré par priorités

### Paramètres Tuning
- `TOKEN_DISCOVERY_BATCH_SIZE`: Taille lots traitement (50)
- `FULL_SCAN_INTERVAL_HOURS`: Scan complet périodique (6h)
- `MAX_CONSECUTIVE_ERRORS`: Seuil mode récupération (3)
- `PAUSE_BETWEEN_TX_DETAILS`: Délai détails transactions (0.1s)

## Points d'Extension

### Ajout Nouveaux Wallets
```python
# Modifier WALLET_ADDRESSES dans config.py
# Redémarrer pour initialisation priorités
```

### Nouvelles Métriques
```python
# Ajouter colonnes dans wallet_activity_metrics
# Implémenter calcul dans record_scan_metrics()
```

### API Personnalisée
```python
# Ajouter routes Flask dans section API
# Accéder DB via db_manager.get_connection()
```

Cette documentation capture l'architecture complète, les algorithmes, et la logique métier du système de monitoring Solana avec tous ses composants optimisés.