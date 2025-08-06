# Client RPC Solana avec Système de Fallback Intelligent

## Vue d'ensemble

Le **Client RPC Solana** est un système sophistiqué de communication avec les endpoints RPC Solana qui implémente une gestion avancée des erreurs, un système de fallback automatique entre endpoints, et une optimisation intelligente des performances. Il assure la résilience et la continuité de service même en cas de défaillance d'endpoints individuels.

### Objectifs principaux
- **Résilience** : Basculement automatique entre endpoints en cas de problème
- **Optimisation** : Sélection intelligente du meilleur endpoint selon les performances
- **Cache intelligent** : Mise en cache des réponses pour réduire la latence
- **Rate limiting** : Respect des limitations de débit par endpoint
- **Monitoring** : Métriques détaillées et health checks automatiques

## Architecture du système

### Composants principaux

```
RPCClient (Client principal)
├── EndpointMetrics (Métriques par endpoint)
├── EndpointRateLimiter (Rate limiting)
├── Request Cache (Cache des réponses)
└── Fallback Manager (Gestion des basculements)
```

## Classes de données principales

### EndpointMetrics
Métriques complètes pour un endpoint RPC spécifique.

**Attributs de base :**
- `url` (str) : URL de l'endpoint
- `total_requests` (int) : Nombre total de requêtes
- `successful_requests` (int) : Requêtes réussies
- `failed_requests` (int) : Requêtes échouées
- `total_response_time` (float) : Temps cumulé des réponses
- `last_error_time` (Optional[float]) : Timestamp dernière erreur
- `last_success_time` (Optional[float]) : Timestamp dernier succès
- `consecutive_errors` (int) : Erreurs consécutives actuelles
- `rate_limit_hits` (int) : Nombre de rate limits rencontrés
- `average_latency` (float) : Latence moyenne
- `health_score` (float) : Score de santé (0-100)
- `is_available` (bool) : Disponibilité de l'endpoint
- `last_health_check` (Optional[float]) : Dernière vérification santé
- `response_times` (deque) : Buffer circulaire des 100 derniers temps de réponse

**Propriétés calculées :**
- `success_rate` : Taux de succès (%) = (successful_requests / total_requests) * 100
- `avg_response_time` : Moyenne des temps de réponse du buffer circulaire

**Méthodes de mise à jour :**

#### `update_success(response_time: float)`
Met à jour les métriques après un succès :
- Incrémente les compteurs totaux et de succès
- Remet à zéro les erreurs consécutives
- Ajoute le temps de réponse au buffer
- Marque l'endpoint comme disponible
- Recalcule le score de santé

#### `update_failure(is_rate_limit: bool = False)`
Met à jour les métriques après un échec :
- Incrémente les compteurs totaux et d'échec
- Incrémente les erreurs consécutives
- Marque comme indisponible si 5+ erreurs consécutives
- Incrémente le compteur de rate limit si applicable
- Recalcule le score de santé

#### `_update_health_score()`
Calcule le score de santé composite (0-100) :

**Pénalités :**
- Taux d'échec : -0.5 point par % d'échec
- Erreurs consécutives : -10 points par erreur
- Latence élevée : -20 points si >5s, -10 points si >2s
- Rate limits : -5 points par occurrence

**Bonus :**
- Succès récent : +10 points si succès dans la dernière minute

### RPCRequest
Représente une requête RPC avec métadonnées.

**Attributs :**
- `method` (str) : Méthode RPC à appeler
- `params` (List[Any]) : Paramètres de la méthode
- `id` (Optional[Union[str, int]]) : Identifiant de la requête
- `priority` (int) : Niveau de priorité (0=normal, 1=high, 2=critical)
- `max_retries` (Optional[int]) : Nombre maximum de tentatives
- `timeout` (Optional[float]) : Timeout spécifique
- `created_at` (float) : Timestamp de création

**Propriétés calculées :**
- `age` : Âge de la requête en secondes
- `to_json()` : Conversion au format JSON-RPC standard

## Classe principale : RPCClient

### Initialisation
```python
RPCClient(config=None)
```

**Composants initialisés :**
- **Configuration des endpoints** : Setup depuis config ou fallback
- **Métriques par endpoint** : EndpointMetrics pour chaque URL
- **Rate limiters** : Un EndpointRateLimiter par endpoint
- **Cache optionnel** : Système de cache des réponses si activé
- **Thread safety** : RLock principal + locks par endpoint
- **Statistiques de session** : Compteurs et métriques globales

### Configuration des endpoints

#### `_setup_endpoints()`
Configure les endpoints selon la hiérarchie :

**Priorité 1 - Premium :**
- Endpoint QuickNode si configuré dans `config.rpc.quicknode_endpoint`
- Rate limit : `QUICKNODE_FREE_TIER_RPS` (100 RPS par défaut)
- Type : 'premium'

**Priorité 2 - Fallback configurés :**
- Endpoints de `config.rpc.fallback_endpoints`
- Rate limit conservateur : 5 RPS
- Type : 'public'

**Priorité 3 - Défaut :**
- Endpoints de `DEFAULT_RPC_ENDPOINTS` si aucun configuré
- Endpoints publics standard Solana

### Système de métriques

#### `_initialize_metrics()`
Initialise les structures de données pour chaque endpoint :
- Création d'un `EndpointMetrics` par URL
- Création d'un `EndpointRateLimiter` avec la limite RPS configurée
- Association des locks thread-safe

### Gestion des endpoints

#### `get_current_endpoint() -> Dict`
Retourne l'endpoint actuellement sélectionné avec ses métadonnées.

#### `switch_endpoint(reason: str) -> Dict`
Bascule vers le prochain endpoint disponible :

**Algorithme de sélection :**
1. Parcourt les endpoints suivants dans l'ordre
2. Vérifie disponibilité (`is_available = True`)
3. Vérifie santé minimale (`health_score > 20`)
4. Si aucun endpoint sain : réinitialise tous et prend le meilleur

**Réactivation automatique :**
- Endpoints indisponibles réactivés après 5 minutes (`_reset_unhealthy_endpoints`)
- Score de santé réinitialisé à 50 lors de la réactivation

#### `_get_best_endpoint() -> Dict`
Sélectionne le meilleur endpoint selon un score composite :
- Score = `health_score - (priority * 10)`
- Les endpoints premium (priority=1) sont favorisés

### Système de cache

#### Configuration
- Activé via `config.rpc.enable_cache`
- TTL configurable via `config.rpc.cache_ttl` (défaut: 60s)
- Limite de 1000 entrées avec nettoyage automatique

#### `_get_cache_key(method: str, params: List) -> str`
Génère une clé MD5 basée sur méthode + paramètres sérialisés.

#### `_check_cache(method: str, params: List) -> Optional[Any]`
Vérifie le cache et retourne le résultat si valide :
- Incrémente `cache_hits` ou `cache_misses`
- Supprime automatiquement les entrées expirées

#### `_update_cache(method: str, params: List, result: Any)`
Met à jour le cache avec un nouveau résultat :
- Déclenche `_cleanup_cache()` si >1000 entrées

### Timeouts adaptatifs

#### `_get_timeout_for_method(method: str) -> float`
Retourne le timeout approprié selon la méthode :

**Méthodes critiques (30s) :**
- `getTransaction`, `getTransactions`
- `getBlock`, `getBlocks`

**Méthodes batch (25s) :**
- `getMultipleAccounts`
- `getSignaturesForAddress`
- `getTokenAccountsByOwner`

**Méthodes standard (15s) :**
- Toutes les autres méthodes

### Exécution des requêtes

#### `call(method: str, params: List, priority: int, use_cache: bool) -> Optional[Dict]`
Point d'entrée principal pour les appels RPC.

**Flux d'exécution :**
1. **Vérification cache** (si `use_cache=True`)
2. **Création RPCRequest** avec timeout adaptatif
3. **Exécution avec fallback** via `_execute_with_fallback`
4. **Mise à jour cache** si succès
5. **Mise à jour statistiques** de session

#### `_execute_with_fallback(request: RPCRequest) -> Optional[Dict]`
Cœur de la logique de retry et fallback.

**Stratégie de retry :**
- Maximum `MAX_RPC_RETRIES` tentatives (défaut: 3)
- Track des endpoints essayés pour éviter les boucles
- Basculement d'endpoint selon le type d'erreur

**Gestion par type d'erreur :**

**Rate Limit (`RPCRateLimitError`) :**
- Basculement immédiat si requête prioritaire
- Sinon attente du délai indiqué
- Mise à jour métrique `rate_limit_hits`

**Timeout (`RPCTimeoutError`) :**
- Basculement immédiat vers autre endpoint
- Pas d'attente additionnelle

**Endpoint indisponible (`RPCEndpointUnavailableError`) :**
- Marque l'endpoint comme indisponible
- Basculement immédiat

**Erreurs génériques :**
- Attente avec backoff exponentiel
- Retry sur le même endpoint

#### `_execute_single_request(request: RPCRequest, endpoint_config: Dict) -> Optional[Dict]`
Exécute une requête unique sur un endpoint spécifique.

**Traitement HTTP :**

**Codes de statut gérés :**
- `200` : Succès, parsing JSON et vérification erreurs RPC
- `429` : Rate limit, extraction du `Retry-After` header
- `408` : Timeout, levée `RPCTimeoutError`
- `5xx` : Erreur serveur, levée `RPCEndpointUnavailableError`

**Traitement des erreurs RPC :**
- Détection du champ `error` dans la réponse JSON
- Extraction `message` et `code` d'erreur
- Levée `RPCResponseError` avec détails

**Métriques automatiques :**
- Temps de réponse calculé et enregistré
- Mise à jour des métriques de succès/échec
- Logging détaillé des performances

### Headers et authentification

#### `_get_headers(endpoint_config: Dict) -> Dict[str, str]`
Génère les headers HTTP appropriés :

**Headers standards :**
- `Content-Type`: `application/json`
- `Accept`: `application/json`  
- `User-Agent`: `SolanaWalletMonitor/2.0`

**Authentification premium :**
- Header `Authorization: Bearer {api_key}` pour endpoints QuickNode
- API key depuis `config.rpc.quicknode_api_key`

### Appels batch

#### `batch_call(requests: List[Dict[str, Any]]) -> List[Optional[Dict]]`
Exécute plusieurs requêtes en une seule requête HTTP batch.

**Format des requêtes :**
- Input: Liste de `{'method': str, 'params': List}`
- Conversion: Format JSON-RPC batch avec IDs séquentiels

**Gestion des réponses :**
- Réorganisation des résultats par ID pour préserver l'ordre
- Remplissage des résultats manquants avec `None`
- Fallback vers appels individuels si échec du batch

**Timeout :**
- Utilise `RPC_TIMEOUT_BATCH` (25s par défaut)

### Monitoring et statistiques

#### `get_stats() -> Dict[str, Any]`
Retourne les statistiques complètes du client.

**Métriques globales :**
- `uptime_seconds` : Durée de vie du client
- `total_requests` : Requêtes totales toutes méthodes
- `total_failures` : Échecs totaux
- `success_rate` : Taux de succès global (%)
- `current_endpoint` : Endpoint actuellement utilisé
- `endpoint_switches` : Nombre de basculements d'endpoint

**Statistiques de cache :**
- `cache_enabled` : État du cache
- `hits` / `misses` : Compteurs de cache
- `hit_rate` : Taux de hits du cache (%)

**Répartition détaillée :**
- `requests_by_method` : Dict {méthode: count}
- `errors_by_type` : Dict {type_erreur: count}
- `endpoints` : Array avec métriques par endpoint

#### `health_check() -> Dict[str, Any]`
Effectue un test de santé actif de tous les endpoints.

**Méthode de test :**
- Appel `getHealth` avec timeout 5s sur chaque endpoint
- Mesure du temps de réponse
- Mise à jour automatique des métriques

**Résultats par endpoint :**
- `status` : 'healthy' ou 'unhealthy'
- `response_time_ms` : Temps de réponse mesuré
- `error` : Message d'erreur si échec

**Évaluation globale :**
- `overall_status` : 'healthy', 'degraded', ou 'critical'
- Basé sur le nombre d'endpoints sains vs total

#### `get_best_endpoints(count: int = 3) -> List[Dict]`
Retourne les meilleurs endpoints classés par score.

**Calcul du score :**
- Score de base = `health_score` de l'endpoint
- Bonus +20 pour endpoints premium
- Tri par score décroissant

**Informations retournées :**
- URL, type, health_score, success_rate, avg_response_time

### Méthodes de contrôle

#### `reset_statistics()`
Remet à zéro toutes les statistiques :
- Compteurs globaux du client
- Métriques de tous les endpoints  
- Statistiques de session
- Cache des requêtes
- Réactivation de tous les endpoints

#### `close()`
Fermeture propre du client avec :
- Nettoyage du cache
- Log des statistiques finales (uptime, requêtes, taux de succès)
- Pas de ressources réseau à fermer (requests sans session persistante)

## Classe EndpointRateLimiter

Rate limiter individuel par endpoint utilisant une fenêtre glissante.

### Attributs
- `max_rps` (float) : Limite maximale en requêtes/seconde
- `requests` (deque) : Buffer des timestamps des requêtes
- `lock` (Lock) : Thread safety

### Méthodes

#### `can_proceed() -> bool`
Vérifie si une nouvelle requête peut être faite :
- Nettoie les requêtes > 1 seconde
- Compare le count avec `max_rps`

#### `record_request()`
Enregistre une requête en ajoutant le timestamp actuel.

#### `get_wait_time() -> float`
Calcule le temps d'attente avant la prochaine requête possible :
- Basé sur la requête la plus ancienne dans la fenêtre
- Retourne 0.0 si aucune attente nécessaire

#### `get_current_rps() -> float`
Retourne le taux actuel de requêtes/seconde calculé sur la dernière seconde.

## Utilitaires et factories

### Fonctions de création

#### `create_rpc_client(config=None) -> RPCClient`
Factory principal avec gestion d'erreurs :
- Utilise `get_config()` si pas de config fournie
- Log des erreurs de création
- Propagation des exceptions

#### `get_default_rpc_client() -> RPCClient`
Singleton global du client RPC :
- Variable globale `_default_rpc_client`
- Création lazy lors du premier appel
- Réutilisation pour les appels suivants

### Fonctions utilitaires

#### `test_rpc_connectivity(endpoints: List[str] = None) -> Dict[str, Any]`
Teste la connectivité d'une liste d'endpoints.

**Test par endpoint :**
- Appel `getHealth` avec timeout 5s
- Mesure du temps de réponse
- Classification du résultat

**Types de résultats :**
- `success` : Réponse HTTP 200 en temps
- `http_error` : Code HTTP non-200
- `timeout` : Dépassement délai
- `connection_error` : Erreur de connexion
- `error` : Autre erreur

**Statistiques globales :**
- Total d'endpoints testés
- Nombre d'endpoints disponibles
- Pourcentage de disponibilité

#### `quick_rpc_call(method: str, params: List, config=None, timeout: float) -> Optional[Dict]`
Appel RPC rapide sans client persistant :
- Création temporaire d'un client via context manager
- Override du timeout si spécifié
- Gestion d'erreurs avec log
- Nettoyage automatique

### Context manager

#### `rpc_client_context(config=None)`
Context manager pour utilisation temporaire :
```python
with rpc_client_context() as client:
    result = client.call('getBalance', [wallet_address])
# Nettoyage automatique
```

**Avantages :**
- Création et destruction automatique
- Gestion d'erreurs intégrée
- Pas de pollution de l'espace global

## Configuration et constantes

### Constantes de timeout
```python
RPC_TIMEOUT_DEFAULT = 15    # Requêtes standard
RPC_TIMEOUT_BATCH = 25      # Requêtes batch
RPC_TIMEOUT_CRITICAL = 30   # Requêtes critiques
```

### Paramètres de retry
```python
MAX_RPC_RETRIES = 3           # Tentatives max
RPC_RETRY_DELAY_BASE = 2      # Base backoff exponentiel
```

### Endpoints par défaut
```python
DEFAULT_RPC_ENDPOINTS = [
    "https://api.mainnet-beta.solana.com",      # Endpoint officiel
    "https://rpc.ankr.com/solana",              # Ankr public
    "https://solana.public-rpc.com"             # Public RPC
]
```

### Rate limiting
```python
QUICKNODE_FREE_TIER_RPS = 100  # QuickNode gratuit
# Endpoints publics: 5 RPS (conservateur)
```

## Gestion d'erreurs

### Hiérarchie des exceptions

**`RPCError`** : Exception de base
- **`RPCTimeoutError`** : Timeout de requête
- **`RPCRateLimitError`** : Rate limit atteint  
- **`RPCEndpointUnavailableError`** : Endpoint indisponible
- **`RPCResponseError`** : Erreur dans la réponse RPC

### Stratégies de gestion

**Erreurs temporaires (retry) :**
- Rate limits : Attendre délai ou changer endpoint
- Timeouts : Changer endpoint immédiatement
- Erreurs réseau : Backoff exponentiel

**Erreurs permanentes (fail-fast) :**
- Erreurs de paramètres RPC
- Erreurs d'authentification
- Réponses malformées

### Logging des erreurs

**Niveaux de log :**
- **DEBUG** : Requêtes individuelles et temps de réponse
- **INFO** : Changements d'endpoint, statistiques
- **WARNING** : Erreurs RPC récupérables, rate limits
- **ERROR** : Échecs définitifs, erreurs système

## Optimisations de performance

### Réutilisation de connections
- Utilise la session globale `requests` (keep-alive automatique)
- Pas de pool de connections personnalisé (délégué à `requests`)

### Métriques en mémoire
- Buffers circulaires pour limiter l'usage mémoire
- Nettoyage automatique du cache
- Métriques agrégées (pas de stockage individuel)

### Thread safety
- `RLock` principal pour modifications d'état
- Locks individuels par endpoint pour métriques
- Collections thread-safe (deque avec lock)

### Algorithmes optimisés
- Score de santé composite (O(1))
- Cache avec clés hashées (O(1) lookup)
- Rate limiting avec fenêtre glissante efficace

## Cas d'usage et patterns

### Utilisation basique
```python
# Création et appel simple
client = create_rpc_client()
result = client.call("getBalance", [wallet_address])

# Avec priorité et cache
result = client.call(
    method="getMultipleAccounts",
    params=[addresses, {"encoding": "jsonParsed"}],
    priority=1,  # Priorité haute
    use_cache=False  # Pas de cache
)
```

### Appels batch
```python
requests = [
    {"method": "getBalance", "params": [addr1]},
    {"method": "getBalance", "params": [addr2]},
    {"method": "getAccountInfo", "params": [addr3]}
]

results = client.batch_call(requests)
# results[0] = balance addr1, results[1] = balance addr2, etc.
```

### Monitoring continu
```python
# Health check périodique
health = client.health_check()
if health['overall_status'] != 'healthy':
    print(f"⚠️ Problème RPC: {health['healthy_endpoints']}/{health['total_endpoints']} endpoints OK")

# Statistiques détaillées
stats = client.get_stats()
print(f"Taux succès: {stats['success_rate']}% ({stats['total_requests']} requêtes)")
print(f"Cache: {stats['cache_stats']['hit_rate']}% hits")

# Meilleurs endpoints
for endpoint in client.get_best_endpoints():
    print(f"🏆 {endpoint['url']}: {endpoint['health_score']} points")
```

### Usage avec context manager
```python
# Client temporaire
with rpc_client_context() as client:
    balances = []
    for address in wallet_addresses:
        balance = client.call("getBalance", [address])
        balances.append(balance)
# Client automatiquement fermé

# Appel unique rapide
result = quick_rpc_call("getHealth", timeout=5.0)
```

### Configuration avancée
```python
# Config personnalisée
config = get_config()
config.rpc.enable_cache = True
config.rpc.cache_ttl = 30
config.rpc.max_retries = 5
config.rpc.timeout = 20

client = create_rpc_client(config)

# Reset et reconfiguration
client.reset_statistics()
```

## Points d'attention et limitations

### Limitations techniques
- **Pas de pool de connections** : Délégué à `requests` (suffisant pour la plupart des cas)
- **Cache en mémoire uniquement** : Pas de persistence entre redémarrages
- **Singleton global** : Un seul client par défaut (mais multiples instances possibles)

### Considérations de performance
- **Memory footprint** : Buffers circulaires de 100 entrées par endpoint
- **Thread contention** : Locks multiples peuvent créer des goulots
- **GIL impact** : Thread safety en Python peut limiter la vraie concurrence

### Gestion d'erreurs
- **Fallback peut masquer des problèmes** : Endpoints défaillants continuent d'être utilisés
- **Rate limiting conservateur** : Peut sous-utiliser la capacité réelle
- **Pas de circuit breaker** : Continue d'essayer même si tout échoue

### Configuration recommandée

**Pour production :**
- Configurer des endpoints premium (QuickNode, Alchemy)
- Activer le cache avec TTL adapté au use case
- Monitorer les métriques de health_check
- Logger les changements d'endpoint

**Pour développement :**
- Utiliser `quick_rpc_call` pour tests ponctuels  
- Context manager pour isolation
- Reset des stats entre tests
- Endpoints publics suffisants

## Évolutions possibles

### Améliorations suggérées
1. **Pool de connections persistantes** avec `requests.Session`
2. **Circuit breaker** pour arrêter temporairement les endpoints défaillants
3. **Load balancing** intelligent avec distribution des requêtes
4. **Métriques Prometheus** pour monitoring externe
5. **Configuration hot-reload** sans redémarrage
6. **Cache distribué** avec Redis/Memcached
7. **Compression des réponses** pour économiser la bande passante
8. **Retry jitter** pour éviter les thundering herds

### Intégrations possibles
- **Service discovery** pour endpoints dynamiques  
- **Health check externe** via Kubernetes probes
- **Alerting** sur dégradation des endpoints
- **Rate limiting distribué** entre instances