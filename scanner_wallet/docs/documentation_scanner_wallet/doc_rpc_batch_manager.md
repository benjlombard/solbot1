# Gestionnaire de Batching RPC Intelligent pour Solana

## Vue d'ensemble

Le **Batch Manager RPC** est un système sophistiqué d'optimisation des requêtes RPC pour Solana qui groupe intelligemment les appels selon les performances et contraintes du réseau. Il implémente des stratégies adaptatives pour maximiser l'efficacité tout en respectant les limites de débit.

### Objectifs principaux
- **Optimisation des performances** : Réduction de la latence via le groupement de requêtes
- **Adaptation intelligente** : Ajustement automatique des tailles de batch selon les performances
- **Gestion des erreurs** : Retry automatique et gestion des timeouts
- **Monitoring** : Métriques détaillées et analytics d'adaptation

## Architecture du système

### Composants principaux

```
BatchManager (Orchestrateur principal)
├── BatchCollector (Collecteur de requêtes)
├── AdaptiveSizer (Gestionnaire d'adaptation)
├── BatchExecutor (Exécuteur HTTP)
└── RateLimiter (Limitation de débit)
```

## Enums et types de données

### BatchStrategy
Stratégies de batching disponibles :
- `FIXED_SIZE` : Taille fixe selon configuration
- `ADAPTIVE_SIZE` : Adaptation dynamique selon performances
- `PERFORMANCE_BASED` : Optimisation basée sur métriques
- `PRIORITY_WEIGHTED` : Priorisation des requêtes critiques

### BatchPriority
Niveaux de priorité des requêtes :
- `LOW` (1) : Requêtes non critiques
- `NORMAL` (2) : Priorité standard
- `HIGH` (3) : Requêtes importantes
- `CRITICAL` (4) : Requêtes urgentes

### BatchStatus
États d'exécution des batches :
- `PENDING` : En attente de traitement
- `PROCESSING` : En cours d'exécution
- `COMPLETED` : Terminé avec succès
- `FAILED` : Échec d'exécution
- `TIMEOUT` : Dépassement de délai
- `CANCELLED` : Annulé

## Classes de données principales

### BatchRequest
Représente une requête RPC individuelle dans un batch.

**Attributs :**
- `id` (str) : Identifiant unique de la requête
- `method` (str) : Méthode RPC (ex: "getMultipleAccounts")
- `params` (List[Any]) : Paramètres de la méthode
- `priority` (BatchPriority) : Niveau de priorité
- `timeout` (Optional[float]) : Timeout spécifique
- `retry_count` (int) : Nombre de tentatives effectuées
- `max_retries` (int) : Nombre maximum de tentatives (défaut: 3)
- `created_at` (float) : Timestamp de création
- `metadata` (Dict[str, Any]) : Données additionnelles

**Propriétés calculées :**
- `age` : Âge de la requête en secondes
- `to_json_rpc()` : Conversion au format JSON-RPC standard

### BatchConfig
Configuration globale du système de batching.

**Paramètres de taille :**
- `batch_sizes` (Dict[str, int]) : Tailles par méthode RPC
  - `getMultipleAccounts`: 100 (optimal), 50 (conservateur)
  - `getSignaturesForAddress`: 20 (optimal), 10 (conservateur)
  - `getTransaction`: 10 (optimal), 5 (conservateur)

**Paramètres temporels :**
- `min_delay_between_batches` (float) : Délai minimum entre batches (0.3s)
- `max_concurrent_batches` (int) : Batches simultanés maximum (3)
- `batch_timeout` (float) : Timeout par batch (25s)
- `collection_timeout` (float) : Temps max collecte requêtes (2s)

**Configuration d'adaptation :**
- `strategy` (BatchStrategy) : Stratégie utilisée
- `enable_adaptive_sizing` (bool) : Activation adaptation automatique
- `adaptation_sensitivity` (float) : Sensibilité ajustement (10%)

**Gestion des erreurs :**
- `max_response_time_threshold` (float) : Seuil critique (10s)
- `retry_failed_requests` (bool) : Retry automatique
- `max_retries_per_request` (int) : Tentatives max par requête

### BatchMetrics
Métriques de performance d'un batch exécuté.

**Données d'exécution :**
- `batch_id` (str) : Identifiant du batch
- `method` (str) : Méthode RPC exécutée
- `size` (int) : Nombre de requêtes
- `duration` (float) : Durée d'exécution
- `success_count` (int) : Requêtes réussies
- `failure_count` (int) : Requêtes échouées
- `timeout_count` (int) : Requêtes timeout
- `response_time_ms` (float) : Temps de réponse en millisecondes
- `endpoint` (str) : URL de l'endpoint utilisé

**Métriques calculées :**
- `success_rate` : Taux de succès (%)
- `throughput` : Débit (requêtes/seconde)

### BatchStats
Statistiques globales et historique du batch manager.

**Compteurs globaux :**
- `total_batches` : Total de batches exécutés
- `successful_batches` : Batches réussis
- `failed_batches` : Batches échoués
- `total_requests_processed` : Total requêtes traitées
- `total_time_saved_estimate` : Temps économisé estimé

**Moyennes mobiles :**
- `avg_batch_size` : Taille moyenne des batches
- `avg_response_time` : Temps de réponse moyen
- `success_rate` : Taux de succès global (%)

**État courant :**
- `current_batch_sizes` : Tailles actuelles par méthode
- `performance_history` : Historique des 100 dernières métriques

## Composants fonctionnels

### BatchCollector
Collecteur de requêtes pour la formation de batches.

**Fonctionnalités :**
- **Collection intelligente** : Accumule les requêtes par méthode
- **Gestion temporelle** : Timeout configurable pour éviter l'attente excessive
- **Thread safety** : Accès concurrent sécurisé
- **Conditions de déclenchement** : Batch prêt si plein OU timeout atteint

**Méthodes clés :**
- `add_request(request)` : Ajoute une requête (retourne bool succès)
- `is_ready()` : Vérifie si prêt à l'exécution
- `extract_batch()` : Extrait toutes les requêtes pour exécution
- `size()` : Nombre de requêtes accumulées
- `age()` : Âge du collecteur

### AdaptiveSizer
Gestionnaire d'adaptation automatique des tailles de batch.

**Algorithme d'adaptation :**

1. **Collecte de métriques** : Buffer circulaire des 50 dernières performances
2. **Analyse des tendances** : Évaluation sur les 10 derniers échantillons
3. **Critères de décision** :
   - Temps de réponse > 15s → Réduction drastique (50%)
   - Temps de réponse > 5s → Réduction modérée (80%)
   - Taux de succès < 80% → Réduction (70%)
   - Performance excellente → Augmentation prudente (120%)

**Seuils de performance :**
- `good_response_time` : 1000ms
- `warning_response_time` : 5000ms
- `critical_response_time` : 15000ms

**Méthodes principales :**
- `record_performance(metrics)` : Enregistre et déclenche adaptation si nécessaire
- `get_current_size(method)` : Taille actuelle pour une méthode
- `get_adaptation_history(method)` : Historique des 20 dernières adaptations
- `reset_adaptations()` : Remise à zéro

### BatchExecutor
Exécuteur HTTP des batches avec gestion des erreurs.

**Gestion des requêtes :**
- **Format JSON-RPC** : Conversion automatique des BatchRequest
- **Headers enrichis** : Informations de debug (batch-id, taille, méthode)
- **Timeouts configurable** : Par batch et global
- **Thread pool** : Exécution concurrente limitée

**Traitement des réponses :**
- **Analyse des codes d'erreur** : Distinction timeout (-32005) vs autres erreurs
- **Comptage précis** : Succès, échecs, timeouts
- **Gestion des réponses partielles** : Traitement des résultats incomplets

**Codes de retour HTTP :**
- `200` : Succès, analyse du contenu JSON
- `429` : Rate limiting, récupération du Retry-After
- Autres : Erreur avec message détaillé

## Classe principale : BatchManager

### Initialisation
```python
BatchManager(config: BatchConfig = None, rpc_client = None)
```

**Composants internes créés :**
- `AdaptiveSizer` : Gestionnaire d'adaptation
- `BatchExecutor` : Exécuteur de requêtes
- `Collections thread-safe` : Dictionnaires de collecteurs et requêtes
- `Thread de processing` : Boucle de traitement en arrière-plan
- `Rate limiter` : Si client RPC fourni

### Thread de processing
Boucle continue (100ms) qui :
1. Identifie les collecteurs prêts (plein ou timeout)
2. Extrait les batches
3. Lance l'exécution asynchrone
4. Gère les erreurs et retries

### Méthodes d'ajout de requêtes

#### `add_request(method, params, priority, timeout, metadata)`
Ajoute une requête individuelle au système.

**Processus :**
1. Création d'un BatchRequest avec ID unique
2. Ajout aux requêtes en attente
3. Recherche/création du collecteur approprié
4. Gestion du débordement (force processing si collecteur plein)

**Retour :** ID unique de la requête

### Méthodes de batching spécialisées

#### `batch_get_multiple_accounts(addresses, encoding="jsonParsed")`
Optimisation spécifique pour récupérer plusieurs comptes.

**Stratégie :**
- Division en chunks selon taille adaptative
- Préservation de l'ordre des résultats
- Délai inter-chunks configurable
- Métadonnées d'indexation pour reconstruction

#### `batch_get_signatures_for_addresses(addresses, limit_per_address=20)`
Récupération batch des signatures par adresse.

**Approche :**
- Une requête par adresse (pas de groupement possible)
- Traitement par chunks pour contrôler le débit
- Dictionnaire de résultats {adresse: [signatures]}

#### `batch_get_transactions(signatures, encoding="json")`
Récupération batch de transactions par signature.

**Optimisations :**
- Chunks selon taille adaptative pour transactions
- Préservation de l'ordre (index global)
- Support des transactions versionnées (maxSupportedTransactionVersion: 0)

### Système de retry et gestion d'erreurs

**Retry automatique :**
- Déclenchement : Échec du batch entier
- Stratégie : Retry individuel des requêtes avec priorité élevée
- Limite : `max_retries` par requête
- Abandon : Log d'avertissement après épuisement

**Types d'erreurs gérés :**
- `BatchExecutionError` : Erreur générale d'exécution
- `RPCTimeoutError` : Timeout spécifique
- `RPCRateLimitError` : Limitation de débit
- `BatchingError` : Erreur de configuration

### Rate limiting intégré

**Fonctionnalités :**
- Détection automatique de l'endpoint
- Priorités différenciées (batches > 10 requêtes = HIGH)
- Attente intelligente avec report si délai > 5s
- Enregistrement des performances pour adaptation

## Système de métriques et monitoring

### Méthodes de monitoring

#### `get_stats()`
Statistiques complètes du système.

**Sections retournées :**
- `performance_summary` : Métriques globales et moyennes
- `current_state` : État actuel des collecteurs
- `configuration` : Paramètres en cours
- `recent_performance` : 10 dernières métriques

#### `get_health_status()`
Évaluation de la santé du système.

**Critères d'évaluation :**
- **Healthy** ✅ : >90% succès + <1s réponse
- **Warning** ⚠️ : >70% succès + <5s réponse  
- **Critical** ❌ : Autres cas

**Recommandations automatiques :**
- Taux de succès faible → Vérifier connectivité
- Temps élevé → Réduire tailles de batch
- Trop de collecteurs → Possible fragmentation

#### `get_adaptation_analytics()`
Analytics détaillées sur l'adaptation des tailles.

**Données par méthode :**
- Taille actuelle vs optimale
- Efficacité (pourcentage de l'optimal)
- Tendance : amélioration/dégradation/stable
- Historique des 5 dernières adaptations

**Résumé global :**
- Méthodes analysées
- Répartition des tendances
- Efficacité moyenne

### Méthodes de contrôle

#### `force_process_all()`
Force le traitement de tous les collecteurs actifs, même non pleins/timeout.

#### `reset_stats()`
Remet à zéro toutes les statistiques et adaptations.

#### `update_config(new_config)`
Mise à jour à chaud de la configuration avec log des changements.

#### `close()`
Fermeture propre avec :
1. Arrêt du thread de processing
2. Traitement final des requêtes en attente  
3. Fermeture de l'executor
4. Log des statistiques finales

## Utilitaires et factories

### Fonctions de création

#### `create_batch_manager(config, rpc_client)`
Factory principal avec validation et initialisation.

#### `create_batch_config(strategy, enable_adaptive, min_delay, batch_timeout, **batch_sizes)`
Factory de configuration avec surcharges par méthode.

#### `create_conservative_batch_config()`
Configuration pour RPC gratuits/lents :
- Tailles réduites (50% de l'optimal)
- Stratégie fixe sans adaptation
- Délais augmentés (0.5s entre batches)
- Concurrence limitée (2 batches max)

#### `create_aggressive_batch_config()`
Configuration pour RPC premium :
- Tailles doublées (max 200)
- Adaptation performance très sensible (15%)
- Délais réduits (0.1s entre batches)
- Haute concurrence (5 batches simultanés)

### Context manager

#### `batch_context(config, rpc_client)`
Context manager pour utilisation temporaire :
```python
with batch_context() as batch_manager:
    batch_manager.add_request("getBalance", [address])
# Fermeture automatique à la sortie
```

### Décorateur de batching

#### `BatchingDecorator`
Décorateur pour batcher automatiquement les appels de fonction :
```python
@batch_method(batch_manager, "getBalance")
def get_balance(address):
    pass
# Les appels sont automatiquement mis en batch
```

## Constantes et configuration par défaut

### Tailles de batch optimales
```python
OPTIMAL_BATCH_SIZES = {
    'getMultipleAccounts': 100,      # Limite Solana : 100 comptes max
    'getSignaturesForAddress': 20,    # Balance performance/timeout
    'getTransaction': 10,             # Transactions lourdes
    'token_metadata': 15,             # Métadonnées token
    'signatures_batch': 25,           # Signatures en lot
    'transactions_batch': 8           # Transactions en lot (plus lourdes)
}
```

### Seuils de performance
```python
PERFORMANCE_THRESHOLDS = {
    'good_response_time': 1000,      # 1s = bonne performance
    'warning_response_time': 5000,   # 5s = performance dégradée
    'critical_response_time': 15000  # 15s = performance critique
}
```

### Timeouts
- `RPC_TIMEOUT_BATCH` : 25 secondes par batch
- Collection timeout : 2 secondes max pour accumuler requêtes
- Thread processing : Vérification toutes les 100ms

## Cas d'usage et exemples

### Utilisation basique
```python
# Création et configuration
config = create_batch_config(strategy="adaptive_size")
batch_manager = create_batch_manager(config, rpc_client)

# Ajout de requêtes
request_id = batch_manager.add_request(
    method="getMultipleAccounts",
    params=[addresses, {"encoding": "jsonParsed"}],
    priority=BatchPriority.HIGH
)

# Batching spécialisé
results = batch_manager.batch_get_multiple_accounts(addresses)
```

### Monitoring et optimisation
```python
# Vérification santé
health = batch_manager.get_health_status()
print(f"Santé: {health['summary']}")

# Analytics d'adaptation
analytics = batch_manager.get_adaptation_analytics()
for method, data in analytics['methods'].items():
    print(f"{method}: {data['current_size']} (efficacité: {data['size_efficiency']}%)")

# Statistiques détaillées
stats = batch_manager.get_stats()
print(f"Temps économisé estimé: {stats['performance_summary']['estimated_time_saved']}s")
```

### Configurations spécialisées
```python
# Pour RPC gratuits/lents
conservative_config = create_conservative_batch_config()

# Pour RPC premium/rapides  
aggressive_config = create_aggressive_batch_config()

# Configuration personnalisée
custom_config = create_batch_config(
    strategy="performance_based",
    getMultipleAccounts=50,
    getTransaction=5,
    min_delay=0.2
)
```

## Points d'attention et limitations

### Limitations techniques
- **Ordre des résultats** : Préservé uniquement pour méthodes spécialisées
- **Résultats asynchrones** : `get_request_result()` non implémenté (callbacks recommandés)
- **Taille maximale** : Limitée par contraintes Solana (ex: 100 comptes max pour getMultipleAccounts)

### Considérations de performance
- **Memory usage** : Buffer circulaire de 50 métriques par méthode
- **Thread overhead** : Un thread de processing permanent
- **Rate limiting** : Peut introduire des délais supplémentaires

### Gestion d'erreurs
- **Retry intelligent** : Uniquement sur échec complet du batch
- **Dégradation gracieuse** : Continue avec tailles réduites si performance dégradée
- **Fallbacks** : Configuration par défaut si imports échouent

## Évolutions possibles

### Améliorations suggérées
1. **Callbacks/Futures** : Système de notification des résultats
2. **Persistence** : Sauvegarde des adaptations entre redémarrages
3. **Load balancing** : Distribution sur plusieurs endpoints
4. **Circuit breaker** : Arrêt temporaire si trop d'échecs
5. **WebSocket support** : Pour requêtes temps réel

### Métriques additionnelles
- **Coût économique** : Calcul des frais RPC économisés
- **Latence P95/P99** : Percentiles de temps de réponse
- **Efficacité réseau** : Bytes économisés par batching