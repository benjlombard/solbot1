# Solana Cache Manager - Documentation Technique

## Vue d'ensemble

Le **Solana Cache Manager** est un système de mise en cache intelligent pour les métadonnées de tokens et les données de comptes. Il fournit une architecture de cache multi-niveaux avec gestion TTL, éviction LRU, tagging et statistiques détaillées.

## Architecture générale

### Imports et dépendances

**Imports système :**
- `time`, `json`, `pickle`, `hashlib`, `threading` - Fonctionnalités système
- `typing` - Annotations de type (Dict, List, Optional, Any, Tuple, Callable)
- `collections.OrderedDict` - Dictionnaire ordonné pour LRU
- `dataclasses.dataclass` - Décorateur pour structures de données
- `datetime.{datetime, timedelta}` - Gestion des dates
- `logging` - Système de logs

**Imports métier avec fallbacks :**
- `core.logger.get_logger` → fallback: `logging.getLogger()`
- `core.config.get_config` → fallback: objet Config simulé avec attributs cache
- `utils.helpers.get_current_timestamp` → fallback: `int(time.time())`
- `models.token.{Token, TokenAccount}` → pas de fallback
- `constants.CACHE_SETTINGS` → valeurs par défaut

**Configuration par défaut (CACHE_SETTINGS) :**
```python
CACHE_SETTINGS = {
    'default_ttl': 3600,         # 1 heure
    'max_size': 1000,            # 1000 entrées max
    'cleanup_interval': 300,      # 5 minutes
    'compression_threshold': 1000 # Seuil de compression
}
```

## Classe CacheEntry

```python
@dataclass
class CacheEntry:
    value: Any                   # Valeur cachée
    timestamp: int              # Timestamp de création
    ttl: int                    # Time To Live en secondes
    hits: int = 0               # Nombre d'accès
    misses: int = 0             # Nombre de ratés
    size: int = 0               # Taille en bytes
    tags: List[str] = None      # Tags pour regroupement
```

### Propriétés calculées

**`is_expired -> bool`**
- **Calcul :** `get_current_timestamp() > self.timestamp + self.ttl`
- **Fonction :** Vérifie si l'entrée a expiré

**`age -> int`**
- **Calcul :** `get_current_timestamp() - self.timestamp`
- **Fonction :** Retourne l'âge en secondes

### `__post_init__()`
- **Action :** Initialise `tags` à liste vide si `None`

## Classe TokenCacheManager (classe de base)

### Initialisation

**Paramètres :**
- `cache_name: str = "token_cache"` - Nom du cache

**Attributs d'instance :**
- `self.config` - Configuration via `get_config()`
- `self.cache_name` - Nom du cache
- `self.cache: OrderedDict[str, CacheEntry]` - Cache ordonné pour LRU
- `self.lock = threading.RLock()` - Verrou réentrant pour thread-safety
- `self.stats` - Dictionnaire de statistiques

**Structure self.stats :**
```python
{
    'hits': 0,              # Nombre de hits
    'misses': 0,            # Nombre de misses
    'evictions': 0,         # Nombre d'évictions
    'expirations': 0,       # Nombre d'expirations
    'total_size': 0,        # Taille totale en bytes
    'max_size': int,        # Taille maximale
    'ttl': int              # TTL par défaut
}
```

**Thread de nettoyage :**
- `self.cleanup_thread = None` - Thread de nettoyage en arrière-plan
- `self.cleanup_running = False` - Flag d'état du thread
- Démarrage automatique via `start_cleanup_thread()`

**Log d'initialisation :** "✅ Token Cache Manager initialized: {cache_name}"

### Méthodes principales

#### 1. `_calculate_size(value: Any) -> int`

**Fonction :** Calcule la taille approximative d'une valeur en bytes

**Logique par type :**
- `str, int, float` → `len(str(value))`
- `dict` → `len(json.dumps(value))`
- `Token, TokenAccount` → `len(json.dumps(value.to_dict()))`
- Autres → `len(pickle.dumps(value))`
- Exception → `100` (valeur par défaut)

#### 2. `get(key: str) -> Optional[Any]`

**Fonction :** Récupère une valeur du cache

**Processus avec verrou :**
1. Vérification existence de la clé
2. Si trouvée :
   - Test expiration via `entry.is_expired`
   - Si expirée → suppression via `_remove_expired()`, incrémente `expirations` et `misses`
   - Si valide → déplacement en fin (LRU) via `cache.move_to_end(key)`, incrémente `entry.hits` et `stats['hits']`
3. Si non trouvée → incrémente `stats['misses']`

**Logs :**
- Hit : "📦 Cache HIT: {key}" (debug)
- Miss : "📦 Cache MISS: {key}" (debug)

#### 3. `set(key: str, value: Any, ttl: Optional[int] = None, tags: List[str] = None) -> bool`

**Fonction :** Stocke une valeur dans le cache

**Processus avec verrou :**
1. Calcul TTL (paramètre ou défaut)
2. Calcul taille via `_calculate_size()`
3. Création `CacheEntry` avec timestamp actuel
4. Si clé existe → soustraction taille ancienne entrée
5. Vérification limite taille → évictions LRU si nécessaire
6. Ajout nouvelle entrée + déplacement en fin
7. Mise à jour `stats['total_size']`

**Gestion des évictions :**
```python
while (self.stats['total_size'] + size > self.stats['max_size'] and self.cache):
    self._evict_lru()
    self.stats['evictions'] += 1
```

**Log :** "📦 Cache SET: {key} (size: {size}, ttl: {ttl})" (debug)

#### 4. `delete(key: str) -> bool`

**Fonction :** Supprime une clé du cache

**Processus :**
1. Vérification existence
2. Suppression via `cache.pop(key)`
3. Soustraction taille de `stats['total_size']`

**Log :** "📦 Cache DELETE: {key}" (debug)

#### 5. `delete_by_tag(tag: str) -> int`

**Fonction :** Supprime toutes les entrées avec un tag spécifique

**Processus :**
1. Recherche clés avec tag dans `entry.tags`
2. Suppression via `delete()` pour chaque clé
3. Retour nombre d'entrées supprimées

**Log :** "📦 Cache DELETE BY TAG: {tag} ({count} entries)" (debug)

#### 6. `clear() -> bool`

**Fonction :** Vide complètement le cache

**Actions :**
- `cache.clear()`
- `stats['total_size'] = 0`

**Log :** "📦 Cache CLEARED" (info)

#### 7. Méthodes utilitaires

**`_evict_lru()`**
- Supprime l'entrée la moins récemment utilisée
- `cache.popitem(last=False)` (premier = plus ancien)
- Log : "📦 Cache EVICTED: {key}" (debug)

**`_remove_expired(key)`**
- Supprime une entrée expirée spécifique
- Met à jour `stats['total_size']`

#### 8. `cleanup_expired() -> int`

**Fonction :** Supprime toutes les entrées expirées

**Processus avec verrou :**
1. Identification clés expirées via `entry.is_expired`
2. Suppression via `_remove_expired()` pour chaque clé
3. Log si nettoyage effectué : "📦 Cache CLEANUP: {count} expired entries" (debug)
4. Retour nombre d'entrées nettoyées

### Gestion du thread de nettoyage

#### 9. `start_cleanup_thread()`

**Fonction :** Démarre le thread de nettoyage en arrière-plan

**Logique :**
- Vérification si thread existe et actif
- Définition fonction `cleanup_worker()` :
  - Boucle tant que `cleanup_running = True`
  - Appel `cleanup_expired()` 
  - Sleep `CACHE_SETTINGS['cleanup_interval']` (300s)
  - Gestion erreurs avec retry après 60s
- Création thread daemon nommé "CacheCleanup-{cache_name}"

#### 10. `stop_cleanup_thread()`

**Fonction :** Arrête le thread de nettoyage

**Actions :**
- `cleanup_running = False`
- `thread.join(timeout=5)` avec timeout de 5 secondes

### Statistiques et monitoring

#### 11. `get_stats() -> Dict[str, Any]`

**Fonction :** Retourne statistiques détaillées du cache

**Structure retour :**
```python
{
    'cache_name': str,
    'size': int,                    # Nombre d'entrées
    'total_size_bytes': int,        # Taille totale
    'max_size': int,                # Limite max
    'ttl': int,                     # TTL par défaut
    'hits': int,
    'misses': int,
    'hit_ratio': float,             # Ratio de hits
    'evictions': int,
    'expirations': int,
    'current_entries': [            # Top 10 entrées
        {
            'key': str,
            'age': int,
            'hits': int,
            'size': int,
            'tags': List[str]
        }, ...
    ]
}
```

**Calcul hit_ratio :** `safe_divide(hits, hits + misses)`

#### 12. `get_health_status() -> Dict[str, str]`

**Fonction :** Évalue l'état de santé du cache

**Critères d'évaluation :**
- `critical` : taille ≥ 90% de max_size
- `warning` : taille ≥ 70% de max_size  
- `degraded` : hit_ratio < 0.5
- `healthy` : sinon

**Structure retour :**
```python
{
    'status': str,              # healthy/warning/degraded/critical
    'size': str,                # "current/max"
    'hit_ratio': str,           # "XX.XX%"
    'message': str              # Description
}
```

## Classes spécialisées

### TokenMetadataCache(TokenCacheManager)

**Initialisation :**
- Appel `super().__init__("token_metadata")`
- `self.metadata_ttl = 3600 * 4` (4 heures)

**Méthodes spécialisées :**

#### `cache_token_metadata(token: Token) -> bool`
- **Clé :** `f"metadata:{token.address}"`
- **Tags :** `['metadata', token.symbol]`
- **TTL :** `self.metadata_ttl` (4h)

#### `get_token_metadata(token_address: str) -> Optional[Token]`
- **Clé :** `f"metadata:{token_address}"`

#### `invalidate_token(token_address: str) -> bool`
- **Action :** Suppression via `delete()`

#### `cache_bulk_metadata(tokens: List[Token]) -> int`
- **Fonction :** Cache plusieurs tokens en lot
- **Retour :** Nombre de tokens cachés avec succès

### TokenAccountCache(TokenCacheManager)

**Initialisation :**
- Appel `super().__init__("token_accounts")`
- `self.account_ttl = 300` (5 minutes)

**Méthodes spécialisées :**

#### `cache_account(wallet_address: str, accounts: List[TokenAccount]) -> bool`
- **Clé :** `f"accounts:{wallet_address}"`
- **Tags :** `['accounts', wallet_address]`
- **TTL :** `self.account_ttl` (5min)

#### `get_accounts(wallet_address: str) -> Optional[List[TokenAccount]]`
- **Clé :** `f"accounts:{wallet_address}"`

#### `invalidate_wallet(wallet_address: str) -> int`
- **Action :** Suppression par tag via `delete_by_tag(f"accounts:{wallet_address}")`

### PriceCache(TokenCacheManager)

**Initialisation :**
- Appel `super().__init__("token_prices")`
- `self.price_ttl = 300` (5 minutes)

**Méthodes spécialisées :**

#### `cache_price(token_address: str, price: float, source: str = "unknown") -> bool`
- **Clé :** `f"price:{token_address}"`
- **Valeur :** 
  ```python
  {
      'price': float,
      'source': str,
      'timestamp': int
  }
  ```
- **Tags :** `['price', token_address]`
- **TTL :** `self.price_ttl` (5min)

#### `get_price(token_address: str) -> Optional[Dict[str, Any]]`
- **Clé :** `f"price:{token_address}"`

#### `is_price_fresh(token_address: str, max_age: int = 300) -> bool`
- **Fonction :** Vérifie si le prix est récent
- **Logique :** `current_timestamp - price_data['timestamp'] < max_age`

## CacheManagerSingleton

### Pattern Singleton

**Implémentation thread-safe :**
- `_instance = None` - Instance unique
- `_lock = threading.Lock()` - Verrou pour création
- Double-check locking pattern dans `__new__()`
- Flag `_initialized` pour éviter double initialisation

### Attributs d'instance

**Caches gérés :**
- `self.metadata_cache = TokenMetadataCache()`
- `self.account_cache = TokenAccountCache()`  
- `self.price_cache = PriceCache()`

### Méthodes de gestion globale

#### `get_all_stats() -> Dict[str, Dict[str, Any]]`
**Structure retour :**
```python
{
    'metadata': metadata_cache.get_stats(),
    'accounts': account_cache.get_stats(), 
    'prices': price_cache.get_stats()
}
```

#### `clear_all() -> bool`
**Action :** Appel `clear()` sur tous les caches

#### `cleanup_all() -> int`
**Action :** Appel `cleanup_expired()` sur tous les caches
**Retour :** Nombre total d'entrées nettoyées

#### `shutdown()`
**Action :** Appel `stop_cleanup_thread()` sur tous les caches

## Fonctions utilitaires globales

### Instance globale
```python
cache_manager = CacheManagerSingleton()
```

### Fonctions d'accès
- `get_token_metadata_cache() -> TokenMetadataCache`
- `get_token_account_cache() -> TokenAccountCache`  
- `get_price_cache() -> PriceCache`

### CacheContext (Context Manager)

**Utilisation :**
```python
class CacheContext:
    def __init__(self, cache_name: str = "temp"):
        self.cache = TokenCacheManager(cache_name)
    
    def __enter__(self):
        return self.cache
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cache.clear()
        self.cache.stop_cleanup_thread()
```

**But :** Cache temporaire avec nettoyage automatique

## Patterns et logiques métier

### Stratégie LRU (Least Recently Used)
- Utilisation `OrderedDict` pour maintenir l'ordre d'accès
- `move_to_end(key)` après chaque accès
- `popitem(last=False)` pour éviction du plus ancien

### Gestion TTL (Time To Live)
- Vérification expiration à chaque accès via `is_expired`
- Nettoyage automatique en arrière-plan
- TTL configurables par type de cache

### Thread Safety
- Utilisation `threading.RLock()` (réentrant)
- Toutes les opérations critiques dans blocs `with self.lock:`
- Thread daemon pour nettoyage automatique

### Système de tags
- Tags multiples par entrée pour regroupement logique
- Suppression par tag pour invalidation en lot
- Exemples : `['metadata', 'WSOL']`, `['accounts', wallet_address]`

### Éviction intelligente
- Éviction automatique si limite de taille atteinte
- Stratégie FIFO pour les évictions (plus ancienne entrée)
- Gestion granulaire des tailles en bytes

### Statistiques complètes
- Compteurs hits/misses pour monitoring performance
- Métriques de santé (ratios, utilisation mémoire)
- Historique des accès par entrée

## Gestion d'erreurs et logging

### Préfixes de logs
- ✅ : Initialisation/succès
- 📦 : Opérations cache (SET/GET/DELETE/etc.)
- 📊 : Statistiques/monitoring  
- ❌ : Erreurs

### Niveaux de logs
- `debug` : Opérations détaillées (GET/SET/DELETE)
- `info` : Événements importants (CLEAR, nettoyage)
- `error` : Erreurs système

### Gestion d'erreurs
- Try/catch sur calculs de taille avec fallback
- Retry automatique en cas d'erreur thread nettoyage
- Timeouts sur arrêt de threads

## Exemple de test (section __main__)

**Test complet incluant :**
1. Initialisation cache métadonnées
2. Création objet Token de test (WSOL)
3. Cache et récupération métadonnées
4. Affichage statistiques locales et globales

**Objet Token de test :**
```python
Token(
    address="So11111111111111111111111111111111111111112",
    symbol="WSOL", 
    name="Wrapped SOL",
    decimals=9
)
```

## Configuration et personnalisation

### Variables configurables
- `default_ttl` : TTL par défaut (1h)
- `max_size` : Taille maximale cache (1000 entrées)  
- `cleanup_interval` : Intervalle nettoyage (5min)
- `compression_threshold` : Seuil compression (1000 bytes)

### TTL spécialisés
- **Métadonnées tokens :** 4 heures (peu volatiles)
- **Comptes tokens :** 5 minutes (moyennement volatils)
- **Prix tokens :** 5 minutes (très volatils)

### Extensibilité
- Classe de base `TokenCacheManager` réutilisable
- Pattern singleton pour gestion centralisée
- Support tags pour invalidation flexible
- Thread-safety pour utilisation multi-threadée