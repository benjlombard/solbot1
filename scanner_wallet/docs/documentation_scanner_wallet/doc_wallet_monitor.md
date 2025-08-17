# Solana Wallet Monitor - Orchestrateur Principal - Documentation Technique

## Vue d'ensemble

Le **Solana Wallet Monitor - Orchestrateur Principal** est le module central qui coordonne toutes les activités de monitoring à travers les portefeuilles, tokens et transactions. Il orchestre le scanning, la gestion des priorités, le suivi des balances et l'analyse des transactions dans un système unifié et thread-safe.

## Architecture générale

### Imports et dépendances

**Imports système :**
- `time`, `threading` - Temps et gestion concurrence
- `typing` - Annotations de type (Dict, List, Optional, Set, Tuple)
- `dataclasses` - Structures de données (dataclass, field)
- `datetime.{datetime, timedelta}` - Gestion dates
- `decimal.Decimal` - Calculs décimaux précis
- `queue`, `signal`, `sys` - Queues, signaux système, contrôle programme

**Imports métier avec fallbacks :**
- `core.logger.{get_logger, get_default_logger}` → fallback: `logging.getLogger()`
- `core.database.get_database_manager` → fallback: `None`
- `core.config.get_config` → fallback: `None`
- `core.exceptions.{MonitoringError, CriticalSystemError}` → pas de fallback
- `wallet.priority_manager.WalletPriorityManager` → fallback: classe stub
- `wallet.scanner.WalletScanner` → fallback: classe stub
- `wallet.balance_tracker.BalanceTracker` → fallback: classe stub
- `models.*` - Pas de fallback (WalletPriority, WalletStats, Token, etc.)
- `utils.helpers.{get_current_timestamp, safe_divide}` → pas de fallback
- `utils.validators.validate_wallet_address` → pas de fallback

**Fallbacks classes principales :**
```python
class WalletPriorityManager:
    def __init__(self): pass
    def select_next_wallet(self): return None
    def update_priority(self, wallet, score): pass

class WalletScanner:
    def __init__(self): pass
    def scan_wallet(self, wallet): return None

class BalanceTracker:
    def __init__(self): pass
    def track_wallet(self, wallet): return True
```

## Structures de données

### ScanResult

```python
@dataclass
class ScanResult:
    wallet_address: str              # Adresse portefeuille scanné
    cycle_id: str                   # Identifiant du cycle de scan
    scan_duration: float            # Durée du scan en secondes
    new_accounts_found: int = 0     # Nouveaux comptes découverts
    total_accounts: int = 0         # Total comptes trouvés
    transactions_detected: int = 0   # Transactions détectées
    success: bool = True            # Statut succès du scan
    error_message: Optional[str] = None  # Message d'erreur si échec
    timestamp: int                  # Timestamp du scan
```

### MonitorStats

```python
@dataclass
class MonitorStats:
    total_cycles: int = 0           # Total cycles de monitoring
    total_scans: int = 0            # Total scans effectués
    successful_scans: int = 0       # Scans réussis
    failed_scans: int = 0           # Scans échoués
    total_wallets: int = 0          # Total wallets configurés
    active_wallets: int = 0         # Wallets actifs
    total_discoveries: int = 0      # Total découvertes
    total_transactions: int = 0     # Total transactions détectées
    avg_cycle_duration: float = 0.0 # Durée moyenne cycle
    last_cycle_time: int = 0        # Timestamp dernier cycle
    uptime_seconds: int = 0         # Temps de fonctionnement
    start_time: int                 # Timestamp démarrage
```

## Classe principale : SolanaWalletMonitor

### Initialisation

**Signature :** `__init__(wallet_addresses: Optional[List[str]] = None)`

**Composants core :**
- `self.config` - Configuration via `get_config()`
- `self.db_manager` - Gestionnaire base de données
- `self.logger` - Logger par défaut

**Sous-systèmes :**
- `self.priority_manager = WalletPriorityManager()` - Gestionnaire priorités
- `self.scanner = WalletScanner()` - Scanner de portefeuilles
- `self.balance_tracker = BalanceTracker()` - Tracker de balances

**Threading et synchronisation :**
- `self._lock = threading.Lock()` - Verrou principal
- `self._running = False` - Flag état monitoring
- `self._shutdown_event = threading.Event()` - Event arrêt
- `self._monitor_thread = None` - Thread principal monitoring
- `self._stats_thread = None` - Thread mise à jour statistiques

**Structures de données :**
- `self.wallets: Set[str]` - Set des adresses wallets monitored
- `self.stats = MonitorStats()` - Statistiques temps réel
- `self.scan_queue: queue.Queue` - Queue scans à effectuer
- `self.results_queue: queue.Queue` - Queue résultats scans

**Gestion signaux :**
- `signal.SIGINT` → `_signal_handler` (Ctrl+C)
- `signal.SIGTERM` → `_signal_handler` (Arrêt système)

**Initialisation wallets :** Si `wallet_addresses` fourni → `self.add_wallets(wallet_addresses)`

**Log d'initialisation :** "🧠 Solana Wallet Monitor initialized"

### Gestion des wallets

#### 1. `add_wallets(wallet_addresses: List[str]) -> Dict[str, bool]`

**Fonction :** Ajoute portefeuilles au monitoring

**Processus par wallet :**
1. **Validation :** `validate_wallet_address(address)`
2. **Ajout thread-safe :**
   ```python
   with self._lock:
       if address not in self.wallets:
           self.wallets.add(address)
           self.balance_tracker.track_wallet(address)
   ```
3. **Mise à jour stats :**
   - `stats.total_wallets = len(self.wallets)`
   - `stats.active_wallets = len(self.wallets)`

**Retour :** `{wallet_address: success_bool}` pour chaque wallet

**Logs :** "✅ Added wallet: {address}" ou "❌ Invalid wallet address: {address}"

#### 2. `remove_wallets(wallet_addresses: List[str]) -> Dict[str, bool]`

**Fonction :** Retire portefeuilles du monitoring

**Processus thread-safe :**
```python
with self._lock:
    if address in self.wallets:
        self.wallets.discard(address)
```

**Mise à jour stats :** Total et active wallets recalculés

### Contrôle du monitoring

#### 3. `start_monitoring() -> bool`

**Fonction :** Démarre le système de monitoring

**Vérifications préalables :**
1. **État :** Si déjà en cours → warning "⚠️ Monitoring already running"
2. **Wallets :** Si aucun wallet → warning "⚠️ No wallets to monitor"

**Démarrage sous verrou :**
```python
with self._lock:
    self._running = True
    self._shutdown_event.clear()
    self.stats.start_time = get_current_timestamp()
```

**Threads démarrés :**

1. **Thread monitoring principal :**
   ```python
   self._monitor_thread = threading.Thread(
       target=self._monitoring_loop,
       name="WalletMonitor",
       daemon=True
   )
   ```

2. **Thread statistiques :**
   ```python
   self._stats_thread = threading.Thread(
       target=self._stats_loop,
       name="StatsUpdater",
       daemon=True
   )
   ```

**Logs :**
- "🚀 Wallet monitoring started"
- "📊 Monitoring {len(wallets)} wallets"

#### 4. `stop_monitoring() -> bool`

**Fonction :** Arrête le système de monitoring

**Processus d'arrêt :**
1. **Flags d'arrêt :**
   ```python
   with self._lock:
       self._running = False
       self._shutdown_event.set()
   ```

2. **Attente threads :** `join(timeout=5.0)` pour monitoring, `join(timeout=2.0)` pour stats

**Log :** "🛑 Wallet monitoring stopped"

### Boucle principale de monitoring

#### 5. `_monitoring_loop()`

**Fonction :** Boucle principale exécutée dans thread dédié

**Processus de cycle :**

1. **Initialisation cycle :**
   ```python
   cycle_start = get_current_timestamp()
   cycle_id = f"cycle_{cycle_start}"
   self.logger.log_cycle_start(cycle_id, wallets=list(self.wallets))
   ```

2. **Sélection wallet :**
   - `selected_wallet = self.priority_manager.select_next_wallet()`
   - Vérification présence dans `self.wallets`

3. **Scan wallet :**
   - `scan_result = self._scan_wallet(selected_wallet, cycle_id)`

4. **Mise à jour priorité :**
   - `self._update_wallet_priority(selected_wallet, scan_result)`

5. **Suivi balances :**
   - `self._track_balance_changes(selected_wallet, scan_result)`

6. **Mise à jour stats :**
   - `self._update_cycle_stats(cycle_start, scan_result)`

7. **Logging cycle :**
   ```python
   self.logger.log_cycle_end(
       cycle_id, 
       duration=get_current_timestamp() - cycle_start,
       discoveries=scan_result.new_accounts_found,
       transactions=scan_result.transactions_detected
   )
   ```

8. **Pause :** `time.sleep(self.config.monitoring.update_interval)`

**Gestion d'erreurs :** Try/catch global avec pause 5s sur erreur

#### 6. `_scan_wallet(wallet_address: str, cycle_id: str) -> ScanResult`

**Fonction :** Effectue scan complet d'un portefeuille

**Processus de scan :**

1. **Mesure performance :** `scan_start = time.time()`

2. **Scan effectif :**
   ```python
   scan_data = self.scanner.scan_wallet(wallet_address)
   ```

3. **Traitement résultats :**
   - Extraction `new_accounts` et `transactions` depuis `scan_data`
   - Comptage nouveaux éléments découverts

4. **Persistance :**
   ```python
   if self.db_manager:
       self._store_scan_results(wallet_address, cycle_id, scan_data)
   ```

5. **Construction résultat :**
   ```python
   ScanResult(
       wallet_address=wallet_address,
       cycle_id=cycle_id,
       scan_duration=time.time() - scan_start,
       new_accounts_found=len(new_accounts),
       total_accounts=len(scan_data.get('all_accounts', [])),
       transactions_detected=len(transactions),
       success=True
   )
   ```

**Gestion erreurs :** Création `ScanResult` avec `success=False` et `error_message`

**Log succès :** "✅ Scan completed for {wallet}: {count} new accounts"

#### 7. `_update_wallet_priority(wallet_address: str, scan_result: ScanResult)`

**Fonction :** Met à jour priorité wallet basée sur résultats scan

**Calcul score activité :**
```python
activity_score = scan_result.transactions_detected * 2 + scan_result.new_accounts_found * 5
new_priority = min(10.0, max(0.1, activity_score / 10.0))
```

**Mise à jour :** `self.priority_manager.update_priority(wallet_address, new_priority)`

#### 8. `_track_balance_changes(wallet_address: str, scan_result: ScanResult)`

**Fonction :** Suit changements de balance pour un wallet

**Processus :**
1. **Scan balances :** `changes = self.balance_tracker.scan_balance_changes(wallet_address)`
2. **Log changements :** "💰 {count} balance changes detected"
3. **Filtrage significatifs :** `significant_changes = [c for c in changes if c.is_significant]`
4. **Traitement :** `self._process_significant_changes(significant_changes)`

#### 9. `_process_significant_changes(changes: List[BalanceChange])`

**Fonction :** Traite changements de balance significatifs

**Pour chaque changement :**

1. **Création transaction synthétique :**
   ```python
   transaction = Transaction(
       signature=f"balance_change_{change.timestamp}",
       wallet_address=change.wallet_address,
       amount=float(change.display_change),
       token_amount=float(change.display_change),
       token_mint=change.token_mint,
       token_symbol=change.token_symbol,
       transaction_type=TransactionType.TRANSFER,
       status=TransactionStatus.SUCCESS,
       source="balance_tracker"
   )
   ```

2. **Log grosses transactions :**
   ```python
   if abs(change.display_change) > 1000:
       self.logger.log_large_transaction(
           change.wallet_address,
           "balance_change",
           float(change.display_change),
           change.token_symbol
       )
   ```

### Persistance et stockage

#### 10. `_store_scan_results(wallet_address: str, cycle_id: str, scan_data: Dict)`

**Fonction :** Stocke résultats scan en base de données

**Stockage historique scan :**
```sql
INSERT INTO scan_history 
(wallet_address, cycle_id, scan_type, total_accounts, 
 new_accounts, scan_duration, completed_at)
VALUES (?, ?, ?, ?, ?, ?, ?)
```

**Stockage découvertes tokens :**
```sql
INSERT INTO token_discoveries 
(token_mint, wallet_address, discovered_at, initial_balance, decimals)
VALUES (?, ?, ?, ?, ?)
```

**Données stockées :** Métadonnées scan + nouveaux comptes découverts

### Mise à jour statistiques

#### 11. `_update_cycle_stats(cycle_start: int, scan_result: Optional[ScanResult])`

**Fonction :** Met à jour statistiques monitoring (thread-safe)

**Statistiques mises à jour :**
```python
with self._lock:
    self.stats.total_cycles += 1
    
    if scan_result:
        self.stats.total_scans += 1
        if scan_result.success:
            self.stats.successful_scans += 1
            self.stats.total_discoveries += scan_result.new_accounts_found
            self.stats.total_transactions += scan_result.transactions_detected
        else:
            self.stats.failed_scans += 1
```

**Moyennes calculées :**
- `avg_cycle_duration` = durée moyenne cycles
- `uptime_seconds` = temps depuis démarrage

#### 12. `_stats_loop()`

**Fonction :** Boucle background mise à jour statistiques

**Exécution périodique (60s) :**
1. `_update_wallet_statistics()` - Stats niveau wallet
2. `_log_periodic_summary()` - Log résumé système

#### 13. `_update_wallet_statistics()`

**Fonction :** Met à jour statistiques niveau wallet

**Requête SQL :**
```sql
INSERT OR REPLACE INTO wallet_stats 
(wallet_address, total_transactions, updated_at)
SELECT wallet_address, COUNT(*), ? 
FROM transactions 
WHERE wallet_address = ?
```

**Exécution :** Pour chaque wallet dans `self.wallets`

#### 14. `_log_periodic_summary()`

**Fonction :** Log résumé périodique activité monitoring

**Résumé formaté :**
```
📊 Monitoring Summary:
- Uptime: X.Xh
- Wallets: X total, X active
- Cycles: X total, X successful
- Discoveries: X new accounts
- Transactions: X detected
- Success Rate: XX.X%
```

### APIs et monitoring système

#### 15. `get_system_status() -> Dict[str, Any]`

**Fonction :** Statut complet système

**Structure retour :**
```python
{
    'monitoring_active': bool,
    'wallets_count': int,
    'statistics': MonitorStats.__dict__,
    'components': {
        'priority_manager': 'active',
        'scanner': 'active', 
        'balance_tracker': 'active'
    }
}
```

#### 16. `get_detailed_stats() -> Dict[str, Any]`

**Fonction :** Statistiques détaillées avec métriques performance

**Structure retour :**
```python
{
    'system_stats': MonitorStats.__dict__,
    'wallets': List[str],
    'performance': {
        'scans_per_hour': float,
        'discoveries_per_scan': float,
        'success_rate': float,
        'avg_cycle_duration': float
    }
}
```

#### 17. `health_check() -> Dict[str, Any]`

**Fonction :** Vérification santé complète système

**Checks effectués :**
```python
{
    'monitoring_active': self._running,
    'wallets_configured': len(self.wallets) > 0,
    'components_initialized': bool,  # Tous sous-systèmes != None
    'threads_alive': {
        'monitor': bool,  # Thread monitoring vivant
        'stats': bool     # Thread stats vivant
    },
    'uptime_hours': float,
    'overall_health': bool  # AND de tous checks
}
```

### Gestion signaux système

#### 18. `_signal_handler(signum, frame)`

**Fonction :** Gestionnaire arrêt gracieux

**Actions :**
1. Log "🛑 Received signal {signum}, shutting down..."
2. Appel `self.stop_monitoring()`
3. `sys.exit(0)`

**Signaux gérés :** `SIGINT` (Ctrl+C), `SIGTERM` (arrêt système)

## Fonctions factory et utilitaires

### Factory functions

#### `create_monitor(wallet_addresses: Optional[List[str]] = None) -> SolanaWalletMonitor`
**Fonction :** Crée nouvelle instance moniteur

#### `get_default_monitor() -> SolanaWalletMonitor`
**Fonction :** Singleton instance par défaut

**Implémentation :**
```python
global _default_monitor
if '_default_monitor' not in globals():
    _default_monitor = SolanaWalletMonitor()
return _default_monitor
```

### Fonctions de convenance

#### `start_monitoring(wallets: List[str] = None) -> bool`
**Wrapper :** Démarre monitoring avec instance par défaut + wallets optionnels

#### `stop_monitoring() -> bool`
**Wrapper :** Arrête monitoring instance par défaut

#### `get_status() -> Dict[str, Any]`
**Wrapper :** Statut instance par défaut

## Schémas base de données (inférés)

### Table `scan_history` (historique scans)
```sql
CREATE TABLE scan_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address TEXT NOT NULL,
    cycle_id TEXT NOT NULL,
    scan_type TEXT NOT NULL,        -- 'full_scan', 'balance_scan', etc.
    total_accounts INTEGER DEFAULT 0,
    new_accounts INTEGER DEFAULT 0,
    scan_duration REAL DEFAULT 0.0,
    completed_at INTEGER NOT NULL,
    INDEX idx_wallet_scan (wallet_address, completed_at),
    INDEX idx_cycle (cycle_id)
);
```

### Table `token_discoveries` (découvertes)
```sql
CREATE TABLE token_discoveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_mint TEXT NOT NULL,
    wallet_address TEXT NOT NULL,
    discovered_at INTEGER NOT NULL,
    initial_balance REAL DEFAULT 0.0,
    decimals INTEGER DEFAULT 9,
    INDEX idx_wallet_discovered (wallet_address, discovered_at),
    INDEX idx_token_discovered (token_mint, discovered_at)
);
```

### Table `wallet_stats` (statistiques wallets)
```sql
CREATE TABLE wallet_stats (
    wallet_address TEXT PRIMARY KEY,
    total_transactions INTEGER DEFAULT 0,
    total_discoveries INTEGER DEFAULT 0,
    last_scan_time INTEGER,
    updated_at INTEGER NOT NULL
);
```

## Patterns et logiques métier

### Architecture orchestrateur
- **Coordination centralisée :** Un point de contrôle pour tous sous-systèmes
- **Threading asynchrone :** Boucles dédiées monitoring et stats
- **Queue-based processing :** Queues pour scans et résultats (structure prête)

### Gestion priorités intelligente
- **Score dynamique :** Basé sur activité (transactions × 2 + nouveaux comptes × 5)
- **Plage normalisée :** Score final entre 0.1 et 10.0
- **Feedback loop :** Priorité mise à jour après chaque scan

### Thread safety complet
- **Verrou unique :** `threading.Lock()` pour toutes opérations critiques
- **Event coordination :** `threading.Event()` pour arrêt propre
- **Daemon threads :** Arrêt automatique avec processus principal

### Monitoring résilient
- **Gestion erreurs :** Isolation erreurs par wallet, continue sur échec
- **Stats détaillées :** Succès/échecs trackés séparément
- **Health checks :** Vérification état composants et threads

### Signal handling
- **Arrêt gracieux :** Gestionnaire SIGINT/SIGTERM
- **Cleanup automatique :** Join threads avec timeout
- **État cohérent :** Pas d'interruption au milieu d'opérations

## Gestion d'erreurs et logging

### Préfixes de logs
- 🧠 : Initialisation orchestrateur
- ✅ : Succès opérations (ajout wallet, scan, arrêt)
- 📊 : Statistiques et résumés
- 🚀 : Démarrage système
- 🛑 : Arrêt système et signaux
- 💰 : Changements balances
- 🔄 : Cycles et boucles
- ⚠️ : Avertissements (déjà en cours, pas de wallets)
- ❌ : Erreurs système
- 🧪 : Tests et développement

### Stratégies d'erreur
- **Isolation errors :** Échec scan wallet n'affecte pas autres
- **Graceful degradation :** Monitoring continue même si composants échouent
- **Retry logic :** Pause et retry sur erreurs boucle principale
- **Detailed logging :** Context complet pour debugging

### Métriques de santé
- **Success rates :** Pourcentage scans réussis vs échoués
- **Performance metrics :** Durée cycles, scans/heure, découvertes/scan
- **Component health :** État chaque sous-système
- **Thread monitoring :** Vérification threads vivants

## Exemple de test (section __main__)

**Wallets de test :**
- "4DdrfGHGdMjCqVbNtXsEEGL1SryTeMo8KMGWWtZyZVFh"
- "5GhK...fJd8"

**Séquence de test :**
1. **Création :** `monitor = create_monitor()`
2. **Ajout wallets :** `monitor.add_wallets(test_wallets)`
3. **Démarrage :** `monitor.start_monitoring()`
4. **Test court :** `time.sleep(2)`
5. **Status :** `monitor.get_system_status()`
6. **Arrêt :** `monitor.stop_monitoring()`

## Points d'extension

1. **Load Balancing :** Distribution scans sur workers multiples
2. **Priority Algorithms :** Algorithmes priorité plus sophistiqués (ML-based)
3. **Real-time Notifications :** WebSocket/SSE pour updates temps réel
4. **Distributed Architecture :** Scaling horizontal avec coordination
5. **Advanced Analytics :** Métriques prédictives, détection anomalies
6. **Configuration Dynamique :** Modification paramètres sans redémarrage
7. **Plugin System :** Architecture extensible pour nouveaux analyseurs
8. **Monitoring Dashboard :** Interface web temps réel pour visualisation

## Architecture de production recommandée

### Scaling horizontal
```python
class DistributedMonitor:
    def __init__(self, node_id: str, coordinator_url: str):
        self.node_id = node_id
        self.coordinator = CoordinatorClient(coordinator_url)
        # Distribution wallets entre nodes
        
    def register_with_coordinator(self):
        # Enregistrement auprès coordinateur central
        pass
        
    def get_assigned_wallets(self) -> List[str]:
        # Récupération wallets assignés à ce node
        return self.coordinator.get_wallet_assignments(self.node_id)
```

### Configuration dynamique
```python
class ConfigurableMonitor(SolanaWalletMonitor):
    def update_config(self, new_config: Dict[str, Any]):
        # Mise à jour configuration à chaud
        with self._lock:
            self.config.update(new_config)
            # Ajustement intervalles, timeouts, etc.
```

### Monitoring avancé
```python
class EnhancedMonitor(SolanaWalletMonitor):
    def __init__(self):
        super().__init__()
        self.metrics_exporter = PrometheusExporter()
        self.alert_manager = AlertManager()
        
    def export_metrics(self):
        # Export métriques Prometheus/Grafana
        pass
        
    def check_alert_conditions(self):
        # Vérification conditions alertes
        pass
```