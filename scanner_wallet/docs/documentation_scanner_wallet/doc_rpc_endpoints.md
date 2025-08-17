# Gestionnaire d'Endpoints RPC Solana

## Vue d'ensemble

Le module `rpc_endpoint_manager.py` fournit un système intelligent de gestion des endpoints RPC Solana avec fallbacks automatiques, validation de santé, optimisation des performances et rotation intelligente. Il implémente un pattern singleton thread-safe pour garantir une gestion centralisée des connexions RPC.

## Architecture des Classes

### 1. Énumérations de Classification

#### EndpointTier - Tiers de qualité
```python
class EndpointTier(Enum):
    PREMIUM = "premium"      # Endpoints payants haute performance
    PUBLIC = "public"        # Endpoints publics gratuits  
    FALLBACK = "fallback"    # Endpoints de secours
    CUSTOM = "custom"        # Endpoints personnalisés
```

#### EndpointStatus - États opérationnels
```python
class EndpointStatus(Enum):
    ACTIVE = "active"        # Endpoint fonctionnel
    DEGRADED = "degraded"    # Performance dégradée
    OFFLINE = "offline"      # Endpoint indisponible
    TESTING = "testing"      # En cours de test
```

### 2. EndpointConfig - Configuration d'endpoint

#### Propriétés de configuration
- **url** : URL de l'endpoint RPC (nettoyage automatique trailing slash)
- **tier** : Niveau de qualité (défaut: PUBLIC)
- **api_key** : Clé API optionnelle pour authentification
- **rate_limit_rps** : Limite de requêtes par seconde (défaut: 5.0)
- **timeout** : Timeout en secondes (défaut: RPC_TIMEOUT_DEFAULT)
- **priority** : Priorité numérique (plus bas = plus prioritaire, défaut: 1)
- **description** : Description textuelle
- **headers** : Headers HTTP personnalisés

#### Métadonnées de santé (auto-gérées)
- **status** : État actuel (EndpointStatus)
- **last_test** : Timestamp du dernier test
- **consecutive_errors** : Nombre d'erreurs consécutives
- **average_response_time** : Temps de réponse moyen (moyenne mobile)
- **success_rate** : Taux de succès en pourcentage

#### Méthodes principales

**`__post_init__()`** - Validation et configuration automatique :
- Validation URL avec `validate_url()`
- Nettoyage URL (suppression trailing slash)
- Configuration headers par défaut :
  ```python
  {
      'Content-Type': 'application/json',
      'Accept': 'application/json', 
      'User-Agent': 'SolanaWalletMonitor/2.0'
  }
  ```
- Gestion authentification selon provider :
  - QuickNode : Auth via URL directement
  - Autres : Header `Authorization: Bearer {api_key}`

**`@property is_healthy`** - Critères de santé :
- Status = ACTIVE
- Erreurs consécutives < 3
- Taux de succès ≥ 70%
- Temps de réponse moyen < 10s

**`@property display_name`** - Noms d'affichage selon domaine :
- `quicknode` → "QuickNode"
- `ankr.com` → "Ankr"
- `api.mainnet-beta.solana.com` → "Solana Labs"
- `rpcpool.com` → "RPCPool"
- `helius-rpc.com` → "Helius"
- `public-rpc.com` → "Public RPC"
- Autres → nom de domaine

**`update_metrics(response_time, success)`** - Mise à jour performances :
- **Temps de réponse** : Moyenne mobile avec facteur lissage α=0.1
- **Erreurs consécutives** : Reset sur succès, +1 sur échec
- **Taux de succès** : +1 sur succès (max 100), -5 sur échec (min 0)
- **Statut automatique** :
  - ≥5 erreurs → OFFLINE
  - ≥3 erreurs ou temps >15s → DEGRADED
  - Sinon → ACTIVE

### 3. RPCEndpointManager - Gestionnaire principal

#### Initialisation et configuration

**`__init__(config)`** :
- Configuration depuis objet config ou None
- Liste endpoints vide initialisée
- Index endpoint actuel = 0
- Thread lock (RLock) pour thread-safety
- Statistiques globales initialisées
- Appel `_initialize_endpoints()` puis `_initial_health_check()`

**Statistiques globales** :
```python
self.stats = {
    'total_requests': 0,
    'total_failures': 0, 
    'endpoint_rotations': 0,
    'start_time': time.time()
}
```

#### Gestion des endpoints

**`_initialize_endpoints()`** - Initialisation séquentielle :

1. **Endpoints premium depuis config** :
   - Récupération `config.rpc.quicknode_endpoint` et `quicknode_api_key`
   - Configuration QuickNode premium si disponible :
     - Tier : PREMIUM
     - Rate limit : 100 RPS
     - Timeout : 25s
     - Priority : 1

2. **Fallbacks depuis config** :
   - Liste `config.rpc.fallback_endpoints`
   - Configuration automatique :
     - Tier : PUBLIC
     - Rate limit : 10 RPS
     - Priority : 10 + index

3. **Endpoints par défaut** (si aucune config) :
   ```python
   DEFAULT_RPC_ENDPOINTS = [
       "https://api.mainnet-beta.solana.com",  # Solana Labs
       "https://rpc.ankr.com/solana",          # Ankr  
       "https://solana.public-rpc.com"         # Public RPC
   ]
   ```

4. **Tri final** : `(priority, tier.value)`

**`_initial_health_check()`** - Test santé initial :
- Test de tous les endpoints via `_test_endpoint_health()`
- Classification ACTIVE/DEGRADED selon résultats
- Logging détaillé des performances
- Alerte si aucun endpoint fonctionnel

**`_test_endpoint_health(endpoint)`** - Test individuel :
- Requête POST avec payload : `{"jsonrpc": "2.0", "id": 1, "method": "getHealth"}`
- Headers avec authentification via `get_auth_headers()`
- Timeout configuré par endpoint
- Critères succès : Status 200 + temps < 15s
- Mise à jour automatique métriques via `update_metrics()`

#### Sélection et rotation des endpoints

**`get_current_endpoint()`** - Endpoint actuel thread-safe :
- Protection par lock
- Validation index dans bornes
- Reset à 0 si index invalide
- Exception si aucun endpoint disponible

**`get_next_healthy_endpoint()`** - Rotation intelligente :
- Recherche circulaire depuis index+1
- Sélection premier endpoint `is_healthy`
- Si aucun sain : sélection du "moins mauvais" selon critères :
  ```python
  min(endpoints, key=lambda x: (x.consecutive_errors, -x.success_rate))
  ```
- Mise à jour index et compteur rotations
- Logging des changements

**`report_endpoint_result(success, response_time, error_type)`** - Feedback :
- Mise à jour métriques endpoint actuel
- Incrémentation statistiques globales
- Logging adaptatif (debug succès, warning échecs)
- **Rotation automatique** si ≥3 erreurs consécutives

**`force_rotate_endpoint(reason)`** - Rotation manuelle :
- Appel `get_next_healthy_endpoint()` forcé
- Logging avec raison fournie
- Retour boolean (succès/échec rotation)

#### Gestion dynamique des endpoints

**`add_custom_endpoint(url, tier, api_key, **kwargs)`** - Ajout runtime :
- Création `EndpointConfig` avec paramètres
- Test santé préalable via `_test_endpoint_health()`
- Ajout seulement si test réussi
- Re-tri automatique par priorité
- Thread-safe avec lock

**`remove_endpoint(url)`** - Suppression sécurisée :
- Protection : ne pas supprimer le dernier endpoint
- Ajustement `current_endpoint_index` si nécessaire
- Rotation automatique si endpoint actuel supprimé
- Thread-safe

#### Optimisation et statistiques

**`optimize_endpoint_order()`** - Réorganisation par performance :
- **Score composite** par endpoint :
  ```python
  health_score = 100 if is_healthy else 0
  performance_score = max(0, 100 - response_time/100)  
  reliability_score = success_rate
  tier_bonus = {PREMIUM: 50, PUBLIC: 0, FALLBACK: -20, CUSTOM: 10}
  
  total_score = health_score + performance_score + reliability_score + tier_bonus
  ```
- Tri par score décroissant puis priorité manuelle
- Réajustement index actuel après réorganisation
- Logging du top 3 avec scores

**`get_all_endpoints()`** - Export métriques complètes :
- Données par endpoint : URL, statut, métriques, santé
- Flag `is_current` pour identifier l'actuel
- Thread-safe avec snapshot

**`get_stats()`** - Statistiques globales :
- Compteurs endpoints et santé
- Statistiques requêtes et taux succès  
- Temps de fonctionnement (uptime)
- Nombre rotations et dernière rotation

**`health_check_all()`** - Audit complet :
- Test santé tous endpoints en parallèle
- Classification statut global :
  - `healthy` : tous endpoints sains
  - `degraded` : ≥50% endpoints sains
  - `critical` : <50% endpoints sains
- Durée de test et métriques détaillées

**`reset_statistics()`** - Remise à zéro :
- Reset compteurs globaux
- Reset métriques par endpoint à valeurs neutres
- Nouveau timestamp de démarrage

## Pattern Singleton Thread-Safe

### Variables globales
```python
_endpoint_manager: Optional[RPCEndpointManager] = None
_manager_lock = threading.Lock()
```

### Fonctions d'accès
**`get_endpoint_manager(config=None)`** - Singleton thread-safe :
- Création instance unique si inexistante
- Protection par lock global
- Configuration optionnelle lors de première création

**`reset_endpoint_manager()`** - Reset pour tests :
- Remise à None de l'instance globale
- Thread-safe

## API Utilitaires Simplifiées

### Fonctions de convenance
**`get_current_endpoint_url()`** - URL endpoint actuel  
**`get_current_endpoint_headers()`** - Headers avec auth  
**`report_rpc_result(success, response_time, error_type)`** - Feedback simplifié  
**`force_endpoint_rotation(reason)`** - Rotation externe

## Configuration par Défaut et Fallbacks

### Constants de fallback
```python
DEFAULT_RPC_ENDPOINTS = [
    "https://api.mainnet-beta.solana.com",
    "https://rpc.ankr.com/solana", 
    "https://solana.public-rpc.com"
]
RPC_TIMEOUT_DEFAULT = 15
```

### Fallbacks gracieux
- **Import config** : Fonction `get_config()` ou None
- **Import utils** : Functions simplifiées si modules absents
- **Validation URL** : Check `http://` ou `https://` si fonction absente
- **Test connectivité** : Return `True` si fonction absente

## Logging et Monitoring

### Niveaux de logging
- **INFO** : Initialisations, rotations, optimisations
- **DEBUG** : Métriques de performance, tests endpoints
- **WARNING** : Endpoints dégradés, rotations automatiques
- **ERROR** : Échecs critiques, aucun endpoint disponible

### Messages formatés
- **✅** : Succès et validations
- **⚠️** : Avertissements et dégradations
- **❌** : Erreurs et échecs
- **🔄** : Rotations et changements
- **📊** : Statistiques et métriques
- **🔧** : Configurations et optimisations

## Utilisation et Points d'Entrée

### Initialisation typique
```python
# Via singleton
manager = get_endpoint_manager(config)

# Utilisation directe
url = get_current_endpoint_url()
headers = get_current_endpoint_headers()
```

### Cycle de vie d'une requête
```python
# 1. Récupération endpoint
url = get_current_endpoint_url()
headers = get_current_endpoint_headers()

# 2. Requête RPC (externe)
success, response_time, error = make_rpc_call(url, headers, payload)

# 3. Feedback pour optimisation
report_rpc_result(success, response_time, error)
```

### Monitoring et maintenance
```python
# Health check complet
health = manager.health_check_all()

# Statistiques
stats = manager.get_stats()

# Optimisation
manager.optimize_endpoint_order()

# Gestion endpoints
manager.add_custom_endpoint("https://custom.rpc.com", tier=EndpointTier.CUSTOM)
manager.remove_endpoint("https://old.rpc.com")
```

## Tests et Validation

### Tests intégrés
Le module inclut une section `__main__` avec :
- Création gestionnaire de test
- Affichage endpoints initialisés
- Test de santé complet
- Affichage statistiques

### Points de test
- **Validation URL** : Format et accessibilité
- **Thread safety** : Opérations concurrentes
- **Rotation automatique** : Comportement sur échecs
- **Métriques** : Exactitude des calculs
- **Persistance config** : Chargement depuis configuration

## Architecture et Avantages

### Thread Safety
- Tous les accès protégés par `threading.RLock()`
- Pattern singleton avec lock global
- Operations atomiques sur état partagé

### Résilience
- Fallbacks automatiques sur échecs
- Rotation intelligente basée métriques
- Test de santé proactif
- Récupération automatique d'endpoints

### Performance
- Cache métriques avec moyenne mobile
- Optimisation ordre basée scores
- Rate limiting par endpoint
- Timeouts configurables

### Monitoring
- Métriques détaillées par endpoint
- Statistiques globales système
- Logging adaptatif multilingue
- Health checks à la demande

Cette architecture fournit un système robuste et intelligent pour la gestion des endpoints RPC Solana, avec une haute disponibilité, des performances optimisées et une surveillance complète des métriques de santé.