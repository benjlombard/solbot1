# Documentation - Routes de Batching RPC Solana

## Vue d'ensemble
**Fichier**: `routes/batching.py`  
**Type**: Blueprint Flask pour la gestion du batching RPC  
**Objectif**: Contrôle, monitoring et optimisation du système de batching intelligent pour les requêtes RPC Solana

## Architecture générale

### Structure des imports
- **Core modules**: config, logger, exceptions
- **Batching modules**: BatchManager, RateLimiter
- **Utils**: helpers, formatters, constants
- **External**: Flask, datetime, threading, time, logging

### Variables globales
- `batching_bp`: Blueprint Flask avec préfixe `/api/batching`
- `_batching_stats`: Dictionnaire des statistiques globales thread-safe
- `_stats_lock`: Threading lock pour la synchronisation

## Modèle de données

### Structure `_batching_stats`
```python
{
    'start_time': float,                    # Timestamp de démarrage
    'total_batches': int,                   # Nombre total de batches
    'successful_batches': int,              # Batches réussis
    'failed_batches': int,                  # Batches échoués
    'total_items_processed': int,           # Items totaux traités
    'total_time_saved': float,              # Temps économisé estimé
    'performance_history': [                # Historique (max 100 entrées)
        {
            'timestamp': int,
            'success': bool,
            'items': int,
            'duration': float,
            'method': str
        }
    ]
}
```

### Structure de configuration validée
```python
{
    'batch_sizes': {method: int},           # Tailles par méthode RPC
    'min_delay_between_batches': float,     # Délai minimum (0-10s)
    'batch_timeout': int,                   # Timeout batch (5-120s)
    'adaptive_sizing': bool,                # Sizing adaptatif activé
    'enabled': bool                         # Système activé
}
```

## Fonctions utilitaires

### `update_batching_stats(batch_result: Dict) -> None`
- **Thread-safe** mise à jour des statistiques globales
- Met à jour les compteurs et l'historique de performance
- Limite l'historique à 100 entrées (FIFO)

### `get_batch_manager() -> Optional[BatchManager]`
- Récupère l'instance du BatchManager depuis la configuration
- Retourne None si batching désactivé
- Gère les erreurs de création d'instance

### `validate_batch_config(config_data: Dict) -> Tuple[bool, List[str]]`
- Valide une configuration de batching complète
- **Validations**:
  - batch_sizes: dict avec valeurs int entre 1-100
  - min_delay_between_batches: float entre 0-10
  - batch_timeout: int entre 5-120
- Retourne (is_valid, errors_list)

### `calculate_efficiency_metrics(performance_history: List) -> Dict`
- Calcule les métriques d'efficacité à partir de l'historique
- **Métriques calculées**:
  - avg_items_per_batch, avg_duration, success_rate
  - throughput_per_second, efficiency_trend
- **Trends**: 'improving', 'degrading', 'stable', 'insufficient_data'

### `calculate_percentile(data: List, percentile: int) -> float`
- Calcule un percentile donné d'une liste de valeurs
- Utilisé pour l'analyse des goulots d'étranglement

## Routes API

### Monitoring et Status

#### `GET /api/batching/status`
**Objectif**: Status général du système de batching  
**Réponse**:
```python
{
    'timestamp': int,
    'enabled': bool,
    'uptime_seconds': int,
    'status': 'active|unavailable|disabled',
    'configuration': {
        'adaptive_sizing': bool,
        'batch_sizes': dict,
        'min_delay_between_batches': float,
        'max_concurrent_batches': int,
        'batch_timeout': int
    },
    'statistics': {
        'total_batches': int,
        'success_rate': float,
        'total_items_processed': int,
        'estimated_time_saved': float,
        'avg_items_per_batch': float,
        'throughput_per_second': float
    },
    'performance': {
        'efficiency_trend': str,
        'current_status': 'optimal|suboptimal|poor',
        'recommendations': [str]
    }
}
```

#### `GET /api/batching/metrics?hours=1`
**Objectif**: Métriques détaillées sur une période  
**Paramètres**: `hours` (1-24, défaut: 1)  
**Fonctionnalités**:
- Filtrage par période temporelle
- Agrégation par méthode RPC
- Distribution horaire
- Calcul des percentiles de performance

**Réponse**:
```python
{
    'period': {'hours': int, 'start_time': int, 'end_time': int},
    'global_metrics': {
        'total_batches': int,
        'success_rate': float,
        'avg_items_per_batch': float,
        'overall_throughput': float,
        'estimated_time_saved': float
    },
    'methods_breakdown': {
        method_name: {
            'success_rate': float,
            'avg_duration': float,
            'throughput': float,
            'min_duration': float,
            'max_duration': float
        }
    },
    'hourly_distribution': [
        {
            'hour': str,
            'timestamp': int,
            'batches': int,
            'success_rate': float,
            'throughput': float
        }
    ]
}
```

#### `GET /api/batching/performance-analysis`
**Objectif**: Analyse avancée des performances  
**Conditions**: Minimum 10 entrées dans l'historique  
**Analyses effectuées**:
- Tendances de performance par méthode RPC
- Analyse des goulots d'étranglement (percentiles)
- Comparaison avec les baselines optimales
- Score de santé global (0-100)
- Recommandations d'optimisation automatiques

**Réponse**:
```python
{
    'performance_trends': {
        method: {
            'duration_trend': 'improving|degrading|stable',
            'success_trend': 'improving|degrading|stable',
            'recent_avg_duration': float,
            'recent_success_rate': float
        }
    },
    'bottleneck_analysis': {
        'duration_percentiles': {'p50': float, 'p90': float, 'p99': float},
        'timeout_risk': 'high|medium|low',
        'very_slow_batches_count': int
    },
    'optimization_recommendations': [
        {
            'priority': 'critical|high|medium|low',
            'category': str,
            'method': str,
            'issue': str,
            'recommendation': str
        }
    ],
    'health_score': {
        'overall': float,
        'factors': {'success_rate': float, 'performance': float, 'stability': float},
        'status': 'excellent|good|fair|poor'
    }
}
```

### Configuration

#### `GET /api/batching/config`
**Objectif**: Configuration actuelle du batching  
**Réponse**: Configuration complète avec valeurs par défaut et état actuel

#### `PUT /api/batching/config`
**Objectif**: Mise à jour de la configuration  
**Body**: Configuration partielle ou complète  
**Fonctionnalités**:
- Validation complète avant application
- Tracking des changements effectués
- Application en temps réel au BatchManager
- Logging des modifications

#### `GET /api/batching/config/presets`
**Objectif**: Presets de configuration prédéfinis  
**Presets disponibles**:
- **conservative**: RPC endpoints gratuits/limités
- **optimal**: RPC endpoints payants équilibrés  
- **aggressive**: RPC endpoints premium
- **disabled**: Désactivation complète

**Analyse incluse**:
- Détection du preset le plus proche de la config actuelle
- Score de similarité
- Recommandations contextuelles

#### `POST /api/batching/config/presets/<preset_name>?confirm=true`
**Objectif**: Application d'un preset  
**Sécurité**: Confirmation requise pour presets 'aggressive' et 'disabled'  
**Fonctionnalité**: Applique la configuration via `update_batching_config()`

### Contrôle système

#### `POST /api/batching/control/enable`
**Objectif**: Activation du système de batching  
**Actions**:
- Active la configuration
- Démarre le BatchManager
- Retourne le statut d'activation

#### `POST /api/batching/control/disable?confirm=true`
**Objectif**: Désactivation du système  
**Sécurité**: Confirmation obligatoire  
**Impact**: Performance significativement réduite

#### `POST /api/batching/control/reset-stats?confirm=true`
**Objectif**: Remise à zéro des statistiques  
**Actions**:
- Sauvegarde des anciennes stats
- Reset complet des compteurs
- Reset du BatchManager si disponible

#### `POST /api/batching/test?method=getMultipleAccounts&items=10`
**Objectif**: Test du système avec données simulées  
**Paramètres**:
- `method`: Méthode RPC à tester (défaut: getMultipleAccounts)
- `items`: Nombre d'items (1-50, défaut: 10)
**Fonctionnalité**: Simulation d'un batch avec métriques de performance

### Diagnostics

#### `GET /api/batching/diagnostics`
**Objectif**: Diagnostics complets du système  
**Analyses effectuées**:
1. **System Status**: Statut général et disponibilité
2. **Configuration Analysis**: Validation et problèmes détectés
3. **Performance Analysis**: Métriques récentes et historiques
4. **Health Checks**: Vérifications automatisées multiples
5. **Recommendations**: Actions recommandées par priorité

**Health Checks inclus**:
- Configuration cohérente
- Performance récente acceptable
- Système actif et fonctionnel

**Score de santé global**: 0-100 basé sur tous les checks

## Gestion d'erreurs

### Error Handlers spécialisés
- `BatchingError`: Erreurs spécifiques au batching
- `400`: Requêtes malformées
- `500`: Erreurs serveur internes

### Hooks Flask
- `before_request`: Vérification de la configuration
- `after_request`: Headers spécifiques à l'API batching

## Constantes et seuils

### Sources des constantes
- `OPTIMAL_BATCH_SIZES`: Tailles optimales par méthode RPC
- `CONSERVATIVE_BATCH_SIZES`: Tailles conservatrices
- `PERFORMANCE_THRESHOLDS`: Seuils de performance
- `BATCH_RPC_TIMEOUT`: Timeout par défaut

### Seuils de validation
- Batch sizes: 1-100 par méthode
- Délais: 0-10 secondes
- Timeouts: 5-120 secondes
- Historique: Maximum 100 entrées

## Sécurité et validation

### Confirmations requises
- Désactivation du système
- Application de presets risqués
- Reset des statistiques

### Validation des entrées
- Clamp des valeurs numériques
- Vérification des types de données
- Validation des plages acceptables

### Thread safety
- Utilisation de locks pour les statistiques partagées
- Opérations atomiques sur les structures de données

## Formats de réponse

### Structure standard
```python
{
    'success': bool,
    'message': str,
    'data': any,
    'timestamp': int
}
```

### Codes de statut HTTP
- `200`: Succès
- `400`: Paramètres invalides
- `500`: Erreur serveur

Cette documentation capture l'intégralité de la logique, des structures de données, des API endpoints et des fonctionnalités du script sans nécessiter l'accès au code source.