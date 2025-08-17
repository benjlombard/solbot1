# Solana Wallet Priority Manager - Documentation Technique

## Vue d'ensemble

Le **Solana Wallet Priority Manager** est un système de scoring dynamique de priorités pour le scanning intelligent de portefeuilles. Il utilise un algorithme sophistiqué basé sur l'activité, le volume, la récence et les découvertes pour optimiser l'ordre de scanning des wallets.

## Architecture générale

### Imports et dépendances

**Imports système :**
- `time`, `threading`, `json` - Temps, concurrence, sérialisation
- `typing` - Annotations de type (Dict, List, Optional, Tuple, Any)
- `dataclasses` - Structures de données (dataclass, field)
- `datetime.{datetime, timedelta}` - Gestion dates
- `decimal.Decimal` - Calculs décimaux précis
- `heapq` - File de priorité (heap)

**Imports métier avec fallbacks :**
- `core.logger.get_logger` → fallback: `logging.getLogger()`
- `core.database.get_database_manager` → fallback: `None`
- `core.config.get_config` → fallback: `None`
- `core.exceptions.PrioritySystemError` → pas de fallback
- `models.wallet.{WalletPriority, WalletStats}` → pas de fallback
- `utils.helpers.{get_current_timestamp, clamp, safe_divide}` → pas de fallback
- `utils.validators.validate_wallet_address` → fallback: `len(addr) == 44`

## Structure de données

### PriorityScore

```python
@dataclass
class PriorityScore:
    wallet_address: str              # Adresse portefeuille
    base_score: float = 5.0          # Score de base (défaut)
    activity_bonus: float = 0.0      # Bonus activité récente
    volume_bonus: float = 0.0        # Bonus volume transactions
    recency_bonus: float = 0.0       # Bonus temps depuis dernier scan
    discovery_bonus: float = 0.0     # Bonus découvertes tokens
    penalty: float = 0.0             # Pénalités (scans vides, inactivité)
    final_score: float = 5.0         # Score final calculé
    calculation_time: int            # Timestamp calcul
```

#### Propriété calculée

**`priority_category -> str`**
- **Fonction :** Catégorise le score de priorité

**Catégories par score :**
```python
if final_score >= 8.0: return "CRITICAL"    # Critique
elif final_score >= 6.0: return "HIGH"      # Haute  
elif final_score >= 3.0: return "MEDIUM"    # Moyenne
elif final_score >= 1.0: return "LOW"       # Basse
else: return "VERY_LOW"                      # Très basse
```

#### `to_dict() -> Dict[str, Any]`
**Fonction :** Conversion en dictionnaire pour stockage/sérialisation

## Classe principale : WalletPriorityManager

### Initialisation

**Attributs core :**
- `self.db_manager` - Gestionnaire base de données
- `self.config` - Configuration système

**Stockage thread-safe :**
- `self._lock = threading.Lock()` - Verrou pour opérations atomiques
- `self._wallet_priorities: Dict[str, WalletPriority]` - Priorités par wallet
- `self._priority_scores: Dict[str, PriorityScore]` - Scores calculés en cache
- `self._selection_queue: List[Tuple[float, str, int]]` - Queue de sélection
- `self._last_selection_time: Dict[str, int]` - Timestamp dernières sélections

**Constantes de configuration :**
```python
self.MAX_PRIORITY = 10.0      # Score maximum
self.MIN_PRIORITY = 0.1       # Score minimum  
self.DEFAULT_PRIORITY = 5.0   # Score par défaut
```

**Poids de scoring :**
```python
self.WEIGHTS = {
    'activity': 0.3,     # 30% - Activité récente
    'volume': 0.25,      # 25% - Volume transactions
    'recency': 0.2,      # 20% - Temps depuis dernier scan
    'discovery': 0.15,   # 15% - Découvertes récentes
    'penalty': 0.1       # 10% - Pénalités
}
```

**Initialisation :** Appel `_initialize_system()` puis chargement BDD

**Log d'initialisation :** "🎯 Wallet priority manager initialized"

### Initialisation et chargement

#### 1. `_initialize_system()`

**Fonction :** Initialise système de priorités depuis base de données

**Processus :**
- Si `db_manager` disponible → `_load_priorities_from_db()`
- Sinon → warning "⚠️ No database manager available, using memory storage"

#### 2. `_load_priorities_from_db()`

**Fonction :** Charge priorités existantes depuis BDD

**Requête SQL :**
```sql
SELECT * FROM wallet_priorities
```

**Construction objets :** Création complète `WalletPriority` depuis chaque ligne avec :
- Données numériques : scores, counts, durées
- Données temporelles : timestamps scan, activité
- Historique : `priority_history` désérialisé JSON
- Stockage thread-safe dans `_wallet_priorities`

**Log :** "✅ Loaded {count} wallet priorities"

### Gestion des wallets

#### 3. `add_wallet(wallet_address: str, initial_priority: float = 5.0) -> bool`

**Fonction :** Ajoute nouveau portefeuille à la gestion de priorité

**Processus :**
1. **Validation :** `validate_wallet_address(wallet_address)`
2. **Création objet :** Construction `WalletPriority` avec :
   ```python
   WalletPriority(
       wallet_address=wallet_address,
       priority_score=clamp(initial_priority, MIN_PRIORITY, MAX_PRIORITY),
       last_scan_time=0,
       scan_count_1h=0, scan_count_24h=0,
       activity_score=0.0,
       volume_score_1h=0.0, new_tokens_score_1h=0.0,
       total_scans=0, avg_scan_duration=0.0,
       last_activity_detected=0,
       consecutive_empty_scans=0,
       priority_history=[],
       updated_at=now, created_at=now
   )
   ```
3. **Stockage thread-safe :** Ajout dans `_wallet_priorities`
4. **Persistance :** Sauvegarde via `_save_priority()`

**Log :** "✅ Added wallet {address} with priority {priority}"

#### 4. `remove_wallet(wallet_address: str) -> bool`

**Fonction :** Supprime portefeuille de la gestion

**Actions thread-safe :**
- Suppression de `_wallet_priorities`
- Suppression de `_priority_scores` (cache)

### Calcul de scores de priorité

#### 5. `calculate_priority_score(wallet_address: str) -> PriorityScore`

**Fonction :** Calcule score de priorité complet pour un portefeuille

**Processus de calcul :**

1. **Score de base :** `base_score = DEFAULT_PRIORITY` (5.0)

2. **Bonus activité :** `activity_bonus = _calculate_activity_bonus(priority)`

3. **Bonus volume :** `volume_bonus = _calculate_volume_bonus(wallet_address)`

4. **Bonus récence :** `recency_bonus = _calculate_recency_bonus(priority)`

5. **Bonus découverte :** `discovery_bonus = _calculate_discovery_bonus(wallet_address)`

6. **Pénalités :** `penalty = _calculate_penalty(priority)`

7. **Score final :**
   ```python
   final_score = base_score + activity_bonus + volume_bonus + recency_bonus + discovery_bonus - penalty
   final_score = clamp(final_score, MIN_PRIORITY, MAX_PRIORITY)
   ```

8. **Cache résultat :** Stockage dans `_priority_scores`

#### 6. `_calculate_activity_bonus(priority: WalletPriority) -> float`

**Fonction :** Calcule bonus basé activité récente

**Logique par âge activité :**
```python
hours_since_activity = (now - priority.last_activity_detected) / 3600

if hours_since_activity < 1: return 3.0      # Très récent
elif hours_since_activity < 6: return 2.0    # Récent  
elif hours_since_activity < 24: return 1.0   # Modéré
elif hours_since_activity > 168: return -2.0 # Pénalité (>1 semaine)
else: return 0.0                             # Neutre
```

#### 7. `_calculate_volume_bonus(wallet_address: str) -> float`

**Fonction :** Calcule bonus basé volume transactions 24h

**Requête SQL :**
```sql
SELECT SUM(ABS(amount)) FROM transactions
WHERE wallet_address = ? AND block_time > ?
```

**Paramètres :** `block_time > current_timestamp - 86400` (24h)

**Bonus par volume :**
```python
if volume > 100: return 2.5    # >100 SOL
elif volume > 10: return 1.5   # >10 SOL
elif volume > 1: return 0.5    # >1 SOL
else: return 0.0               # Faible volume
```

#### 8. `_calculate_recency_bonus(priority: WalletPriority) -> float`

**Fonction :** Calcule bonus pour temps depuis dernier scan

**Logique :**
```python
hours_since_scan = (now - priority.last_scan_time) / 3600

if hours_since_scan > 6:
    return min(2.0, hours_since_scan / 12.0)  # Bonus progressif, max 2.0
else:
    return 0.0  # Pas de bonus si scanné récemment
```

#### 9. `_calculate_discovery_bonus(wallet_address: str) -> float`

**Fonction :** Calcule bonus pour découvertes récentes

**Requête SQL :**
```sql
SELECT COUNT(*) FROM token_discoveries
WHERE wallet_address = ? AND discovered_at > ?
```

**Paramètres :** `discovered_at > current_timestamp - 86400` (24h)

**Bonus :** `min(2.0, discoveries * 0.5)` - 0.5 par découverte, max 2.0

#### 10. `_calculate_penalty(priority: WalletPriority) -> float`

**Fonction :** Calcule pénalités pour inactivité

**Pénalités cumulatives :**

1. **Scans vides consécutifs :**
   ```python
   if priority.consecutive_empty_scans > 5:
       penalty += min(3.0, consecutive_empty_scans * 0.3)
   ```

2. **Inactivité prolongée :**
   ```python
   days_since_activity = (now - priority.last_activity_detected) / 86400
   if days_since_activity > 7:
       penalty += min(2.0, days_since_activity / 7.0)
   ```

### Sélection et mise à jour

#### 11. `select_next_wallet() -> Optional[str]`

**Fonction :** Sélectionne prochain portefeuille à scanner basé priorité

**Processus :**
1. **Calcul scores :** `calculate_priority_score()` pour tous wallets
2. **Construction liste :** `[(score.final_score, wallet_address), ...]`
3. **Tri :** Par score décroissant
4. **Sélection :** Wallet avec score le plus élevé

**Log debug :** "🎯 Selected wallet {address} with score {score}"

#### 12. `update_priority(wallet_address, new_score, reason="manual") -> bool`

**Fonction :** Met à jour score de priorité d'un portefeuille

**Processus thread-safe :**
1. **Validation :** Adresse + clamp score dans range valide
2. **Mise à jour :**
   - `priority.priority_score = new_score`
   - `priority.updated_at = get_current_timestamp()`
3. **Historique :**
   ```python
   priority.priority_history.append({
       'score': new_score,
       'reason': reason,
       'timestamp': get_current_timestamp()
   })
   ```
4. **Trim historique :** Garde seulement 50 dernières entrées
5. **Persistance :** `_save_priority(priority)`

**Log :** "🔄 Updated priority for {address}: {old} → {new} ({reason})"

#### 13. `increment_scan_count(wallet_address, duration, discoveries=0) -> bool`

**Fonction :** Incrémente compteur scans et met à jour métriques

**Métriques mises à jour :**
```python
priority.total_scans += 1
priority.scan_count_1h += 1  
priority.scan_count_24h += 1
priority.last_scan_time = now
```

**Durée moyenne :**
```python
if priority.total_scans == 1:
    priority.avg_scan_duration = duration
else:
    priority.avg_scan_duration = (
        (priority.avg_scan_duration * (total_scans - 1) + duration) / total_scans
    )
```

**Gestion découvertes :**
- Si `discoveries > 0` → `consecutive_empty_scans = 0`
- Sinon → `consecutive_empty_scans += 1`
- Bonus découverte : `new_tokens_score_1h = min(10.0, score + discoveries * 0.2)`

### Persistance

#### 14. `_save_priority(priority: WalletPriority) -> bool`

**Fonction :** Sauvegarde priorité en base de données

**Requête SQL :**
```sql
INSERT OR REPLACE INTO wallet_priorities 
(wallet_address, priority_score, last_scan_time, scan_count_1h, 
 scan_count_24h, activity_score, volume_score_1h, new_tokens_score_1h,
 total_scans, avg_scan_duration, last_activity_detected, 
 consecutive_empty_scans, priority_history, updated_at, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
```

**Sérialisation :** `priority_history` → JSON via `json.dumps()`

### APIs et requêtes

#### 15. `get_wallet_priorities() -> Dict[str, WalletPriority]`

**Fonction :** Récupère toutes les priorités wallets (copie thread-safe)

#### 16. `get_priority_scores() -> Dict[str, PriorityScore]`

**Fonction :** Calcule et retourne scores actuels pour tous wallets

**Processus :** Appel `calculate_priority_score()` pour chaque wallet

#### 17. `get_priority_ranking(limit: Optional[int] = None) -> List[Tuple[float, str]]`

**Fonction :** Classement wallets par priorité

**Format retour :** `[(score, wallet_address), ...]` trié par score décroissant

#### 18. `get_priority_statistics() -> Dict[str, Any]`

**Fonction :** Statistiques complètes du système de priorités

**Structure retour :**
```python
{
    'total_wallets': int,
    'priority_distribution': {
        'critical': int,    # Score >= 8.0
        'high': int,        # 6.0 <= score < 8.0
        'medium': int,      # 3.0 <= score < 6.0
        'low': int,         # 1.0 <= score < 3.0
        'very_low': int     # Score < 1.0
    },
    'statistics': {
        'min': float,       # Score minimum
        'max': float,       # Score maximum
        'avg': float,       # Score moyen
        'median': float     # Score médian
    },
    'last_update': int
}
```

### Utilitaires et maintenance

#### 19. `reset_priorities(reason="system_reset") -> bool`

**Fonction :** Remet tous les scores à la valeur par défaut

**Processus :** Pour chaque wallet :
- `priority_score = DEFAULT_PRIORITY`
- Ajout entrée historique avec raison
- Sauvegarde en BDD

#### 20. `reset_wallet_priority(wallet_address, reason="manual_reset") -> bool`

**Wrapper :** `update_priority(wallet_address, DEFAULT_PRIORITY, reason)`

#### 21. `cleanup_old_data(days: int = 30) -> int`

**Fonction :** Nettoyage données anciennes

**Requête SQL :**
```sql
DELETE FROM wallet_priorities 
WHERE last_scan_time < ? AND total_scans = 0
```

**Paramètres :** `last_scan_time < current_timestamp - (days * 86400)`

**Log :** "🧹 Cleaned up {count} old priority records"

## Fonctions globales

### Instance singleton

#### `get_priority_manager() -> WalletPriorityManager`

**Singleton global :** Instance unique thread-safe

### Fonctions de convenance

#### `calculate_priority(wallet_address: str) -> PriorityScore`
**Wrapper :** `get_priority_manager().calculate_priority_score(wallet_address)`

#### `get_next_priority_wallet() -> Optional[str]`
**Wrapper :** `get_priority_manager().select_next_wallet()`

#### `update_wallet_priority(wallet_address, new_priority, reason="manual") -> bool`
**Wrapper :** `get_priority_manager().update_priority(wallet_address, new_priority, reason)`

## Modèle WalletPriority (inféré)

```python
@dataclass
class WalletPriority:
    wallet_address: str               # Adresse portefeuille
    priority_score: float            # Score priorité actuel
    last_scan_time: int              # Timestamp dernier scan
    scan_count_1h: int               # Nombre scans dernière heure
    scan_count_24h: int              # Nombre scans dernières 24h
    activity_score: float            # Score activité
    volume_score_1h: float           # Score volume 1h
    new_tokens_score_1h: float       # Score nouvelles découvertes 1h
    total_scans: int                 # Total scans effectués
    avg_scan_duration: float         # Durée moyenne scan
    last_activity_detected: int      # Timestamp dernière activité
    consecutive_empty_scans: int     # Scans vides consécutifs
    priority_history: List[Dict]     # Historique changements priorité
    updated_at: int                  # Timestamp dernière mise à jour
    created_at: int                  # Timestamp création
```

## Schéma base de données

### Table `wallet_priorities`
```sql
CREATE TABLE wallet_priorities (
    wallet_address TEXT PRIMARY KEY,
    priority_score REAL NOT NULL DEFAULT 5.0,
    last_scan_time INTEGER DEFAULT 0,
    scan_count_1h INTEGER DEFAULT 0,
    scan_count_24h INTEGER DEFAULT 0,
    activity_score REAL DEFAULT 0.0,
    volume_score_1h REAL DEFAULT 0.0,
    new_tokens_score_1h REAL DEFAULT 0.0,
    total_scans INTEGER DEFAULT 0,
    avg_scan_duration REAL DEFAULT 0.0,
    last_activity_detected INTEGER DEFAULT 0,
    consecutive_empty_scans INTEGER DEFAULT 0,
    priority_history TEXT,           -- JSON array
    updated_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);
```

### Tables référencées pour calculs

#### Table `transactions` (pour bonus volume)
```sql
-- Utilisée pour calculer volume 24h
SELECT SUM(ABS(amount)) FROM transactions
WHERE wallet_address = ? AND block_time > ?
```

#### Table `token_discoveries` (pour bonus découverte)
```sql  
-- Utilisée pour compter découvertes récentes
SELECT COUNT(*) FROM token_discoveries
WHERE wallet_address = ? AND discovered_at > ?
```

## Patterns et logiques métier

### Algorithme de scoring sophistiqué
- **Multi-factoriel :** 5 composants (base, activité, volume, récence, découverte) - pénalités
- **Pondération équilibrée :** Activité 30%, volume 25%, récence 20%, etc.
- **Range normalisé :** Scores clampés entre 0.1-10.0
- **Decay temporel :** Bonus diminuent avec le temps

### Système de bonus/pénalités
- **Activité récente :** Bonus élevé (<1h: +3.0, <6h: +2.0)  
- **Volume transactions :** Bonus progressif (>100 SOL: +2.5)
- **Récence scan :** Bonus si pas scanné >6h
- **Découvertes tokens :** 0.5 par découverte récente
- **Pénalités :** Scans vides consécutifs, inactivité >7 jours

### Thread safety et performance
- **Verrou unique :** Protection toutes opérations critiques
- **Cache scores :** Évite recalculs fréquents
- **Batch operations :** Calculs groupés pour ranking
- **Persistence asynchrone :** Sauvegarde après modifications

### Historique et auditabilité
- **Change tracking :** Historique tous changements priorité
- **Raisons documentées :** Contexte chaque modification
- **Trim automatique :** Garde 50 dernières entrées max
- **Timestamps précis :** Traçabilité complète

### Maintenance automatique
- **Cleanup périodique :** Suppression wallets inactifs anciens
- **Reset fonctionnalités :** Global ou individuel
- **Statistiques détaillées :** Distribution, moyennes, extremums

## Gestion d'erreurs et logging

### Préfixes de logs
- 🎯 : Initialisation/sélection
- ✅ : Succès opérations (ajout, chargement)
- 🔄 : Mises à jour priorités
- 📊 : Statistiques/classements
- 🏆 : Rankings et sélections
- 🧹 : Nettoyage/maintenance
- 🧪 : Tests
- ⚠️ : Avertissements (DB indisponible)
- ❌ : Erreurs système

### Stratégies d'erreur
- **Graceful degradation :** Fonctionne sans BDD (mémoire)
- **Scores par défaut :** 5.0 si calcul échoue
- **Validation stricte :** Adresses, ranges scores
- **Logging détaillé :** Context complet erreurs

## Exemple de test (section __main__)

**Wallets de test :**
- "4DdrfGHGdMjCqVbNtXsEEGL1SryTeMo8KMGWWtZyZVFh"
- "5GhK...fJd8"  
- "6JkL...mN9"

**Tests effectués :**
1. **Ajout wallets :** `manager.add_wallet()` pour chaque
2. **Calcul scores :** `calculate_priority_score()` + log résultats
3. **Ranking :** `get_priority_ranking()` avec tri par score
4. **Statistiques :** `get_priority_statistics()` avec distribution

## Points d'extension

1. **Machine Learning :** Modèles prédictifs pour scoring avancé
2. **Real-time Updates :** WebSocket pour changements priorité temps réel
3. **Advanced Analytics :** Corrélations activité, patterns temporels
4. **Custom Weights :** Configuration poids par utilisateur/contexte
5. **Multi-criteria Optimization :** Algorithmes MCDM pour sélection
6. **Predictive Scheduling :** Planification scans basée prédictions
7. **Load Balancing :** Distribution charges entre workers multiples
8. **Anomaly Detection :** Détection patterns inhabituels pour ajustement priorités

## Architecture avancée recommandée

### ML-Enhanced Scoring
```python
class MLPriorityManager(WalletPriorityManager):
    def __init__(self):
        super().__init__()
        self.ml_model = load_trained_model()
        
    def _calculate_ml_score(self, features: Dict[str, float]) -> float:
        # Prédiction score via modèle ML
        return self.ml_model.predict([list(features.values())])[0]
```

### Dynamic Weight Adjustment
```python
class AdaptivePriorityManager(WalletPriorityManager):
    def adjust_weights_based_on_performance(self):
        # Ajustement automatique poids basé performance historique
        performance_metrics = self.analyze_scanning_effectiveness()
        self.WEIGHTS = self.optimize_weights(performance_metrics)
```

### Real-time Priority Updates
```python
class RealtimePriorityManager(WalletPriorityManager):
    def __init__(self):
        super().__init__()
        self.websocket_server = PriorityWebSocketServer()
        
    def update_priority(self, wallet_address: str, new_score: float, reason: str):
        result = super().update_priority(wallet_address, new_score, reason)
        if result:
            self.websocket_server.broadcast_priority_update(wallet_address, new_score)
        return result
```