# Documentation - Routes d'Administration Solana

## Vue d'ensemble
**Fichier**: `routes/admin.py`  
**Type**: Blueprint Flask pour l'administration système  
**Objectif**: Gestion des paramètres système, configuration, maintenance et monitoring avancé du Solana Wallet Monitor

## Architecture générale

### Structure des imports
- **Core modules**: config, logger, database, exceptions
- **System modules**: BatchManager, PriorityManager
- **Utils**: helpers, formatters, constants
- **External**: Flask, datetime, threading, time, logging

### Variables globales
- `admin_bp`: Blueprint Flask avec préfixe `/api/admin`
- `_system_stats`: Statistiques système thread-safe
- `_stats_lock`: Threading lock pour synchronisation

## Modèle de données

### Structure `_system_stats`
```python
{
    'start_time': float,           # Timestamp de démarrage système
    'requests_count': int,         # Nombre total de requêtes admin
    'errors_count': int,           # Nombre d'erreurs rencontrées
    'last_health_check': int       # Timestamp du dernier health check
}
```

### Structure de validation de configuration
```python
{
    'valid': bool,                    # Configuration valide globalement
    'errors': [str],                  # Liste des erreurs critiques
    'warnings': [str],                # Liste des avertissements
    'checks': {
        'wallets': {
            'count': int,
            'valid_addresses': int
        },
        'monitoring': {
            'update_interval': float|str
        },
        'batching': {
            'enabled': bool,
            'batch_sizes': dict
        }
    },
    'summary': {
        'total_errors': int,
        'total_warnings': int,
        'recommendation': 'approved|approved_with_warnings|rejected'
    }
}
```

## Middleware et sécurité

### Décorateur `admin_required`
- **Objectif**: Protection des routes administratives
- **Implémentation actuelle**: Placeholder (routes ouvertes)
- **TODO**: Implémentation d'authentification admin réelle

### Fonctions de tracking
- `update_request_stats()`: Incrémente le compteur de requêtes (thread-safe)
- `update_error_stats()`: Incrémente le compteur d'erreurs (thread-safe)

## Routes API - Monitoring système

### `GET /api/admin/health`
**Objectif**: Check de santé complet du système  
**Vérifications effectuées**:
1. **Configuration**: Wallets configurés, environnement, batching
2. **Base de données**: Connexion, requête de test
3. **RPC Endpoints**: Endpoints configurés et disponibilité
4. **Système de priorités**: PriorityManager initialisé

**Réponse**:
```python
{
    'status': 'healthy|degraded|critical',
    'timestamp': int,
    'version': str,
    'uptime_seconds': int,
    'checks': {
        'configuration': {
            'status': 'ok|error',
            'wallets_configured': int,
            'environment': str,
            'batching_enabled': bool
        },
        'database': {
            'status': 'ok|error',
            'connection': 'active',
            'test_query': 'success'
        },
        'rpc': {
            'status': 'ok|warning|error',
            'endpoints_configured': int,
            'primary_endpoint': str
        },
        'priorities': {
            'status': 'ok|warning',
            'wallets_managed': int,
            'system_initialized': bool
        }
    },
    'system_stats': {
        'requests_handled': int,
        'errors_count': int,
        'error_rate': float
    }
}
```

**Logique des statuts**:
- `healthy`: Tous les checks OK
- `degraded`: Warnings mais système opérationnel
- `critical`: Erreurs critiques (base de données, etc.)

### `GET /api/admin/system-info`
**Objectif**: Informations détaillées du système  
**Sécurité**: Décorateur `@admin_required`  
**Sections d'information**:
- **Application**: Version, uptime, environnement
- **Configuration**: Statistiques des paramètres actifs
- **Performance**: Requêtes/heure, taux d'erreur, dernier health check
- **Database**: Statistiques des tables principales

### `GET /api/admin/metrics?hours=24`
**Objectif**: Métriques détaillées sur une période  
**Paramètres**: `hours` (1-168, défaut: 24)  
**Requêtes de base de données**:
1. **Scan metrics**: Scans totaux, durée moyenne, découvertes, activité
2. **Transaction metrics**: Transactions, tokens, gros montants, wallets actifs
3. **Performance par wallet**: Scans, durée, découvertes, efficacité
4. **Distribution horaire**: Métriques par tranche horaire

**Réponse structurée**:
```python
{
    'period': {'hours': int, 'start_time': int, 'end_time': int},
    'scan_metrics': {
        'total_scans': int,
        'avg_duration_seconds': float,
        'total_discoveries': int,
        'activity_rate': float
    },
    'transaction_metrics': {
        'total_transactions': int,
        'token_transactions': int,
        'large_transactions': int,
        'active_wallets': int,
        'token_ratio': float
    },
    'wallet_performance': [
        {
            'wallet_address': str,
            'wallet_short': str,
            'scan_count': int,
            'avg_duration': float,
            'discoveries': int,
            'avg_efficiency': float
        }
    ],
    'hourly_distribution': [
        {
            'hour': int,
            'scans': int,
            'avg_duration': float,
            'discoveries': int
        }
    ]
}
```

## Routes API - Configuration

### `GET /api/admin/config`
**Objectif**: Configuration actuelle (sécurisée)  
**Sécurité**: Masquage des informations sensibles  
**Sections retournées**:
- **Wallet**: Nombre, mode de sélection, adresses formatées
- **Monitoring**: Intervalles, limites, seuils
- **Batching**: État, tailles, délais
- **RPC**: Timeout, retry, rate limits
- **Database**: Nom, timeout, backup
- **Logging**: Niveau, sortie console/JSON
- **Flask**: Host, port, debug, CORS

### `POST /api/admin/config/validate`
**Objectif**: Validation de configuration avant application  
**Body**: Configuration partielle ou complète  
**Validations effectuées**:

#### Validation Wallets
- Type: Liste non-vide
- Format: Validation d'adresse Solana
- Limite: Respect du `SECURITY_LIMITS['max_wallets_per_instance']`
- Warning: Performance avec nombre élevé de wallets

#### Validation Monitoring
- `update_interval`: Minimum 5 secondes
- Warning: Interval < 30s risque de rate limiting

#### Validation Batching
- `batch_sizes`: Dictionnaire avec valeurs 1-100
- Types: Validation stricte des types de données

**Recommandations automatiques**:
- `approved`: Aucune erreur ni warning
- `approved_with_warnings`: Valide avec avertissements
- `rejected`: Erreurs critiques détectées

## Routes API - Maintenance

### `POST /api/admin/maintenance/database-cleanup?days=30&tables=scan_history,wallet_activity_metrics&dry_run=false`
**Objectif**: Nettoyage de la base de données  
**Paramètres**:
- `days`: Données à conserver (1-365)
- `tables`: Tables à nettoyer (CSV)
- `dry_run`: Simulation sans suppression

**Tables autorisées**: `scan_history`, `wallet_activity_metrics`  
**Logique**: Suppression basée sur timestamps avec colonnes spécifiques  
**Sécurité**: Validation des tables autorisées

### `POST /api/admin/maintenance/reset-priorities?confirm=true&wallet=optional`
**Objectif**: Reset des priorités des wallets  
**Paramètres**:
- `confirm`: Confirmation obligatoire
- `wallet`: Reset ciblé (optionnel)

**Actions**:
- Reset global via `PriorityManager.reset_all_priorities()`
- Reset individuel via `PriorityManager.reset_wallet_priority()`
- Logging des actions pour audit

## Routes API - Debug et diagnostics

### `GET /api/admin/debug/logs?lines=100&level=INFO`
**Objectif**: Récupération des logs récents  
**Paramètres**:
- `lines`: Nombre de lignes (10-1000)
- `level`: Filtrage par niveau (`INFO`, `ERROR`, etc.)

**Gestion d'erreurs**:
- `FileNotFoundError`: 404 avec path du fichier
- `PermissionError`: 403 avec message explicite
- Lecture sécurisée avec encoding UTF-8

### `GET /api/admin/debug/performance`
**Objectif**: Informations de debug des performances  
**Fonctionnalités**:
- **Mémoire**: RSS, VMS, pourcentage (via psutil si disponible)
- **CPU**: Utilisation, nombre de threads
- **Threads**: Compte actif, thread courant
- **Performance**: Requêtes/seconde, taux d'erreur

**Fallback**: Dégradation gracieuse si psutil indisponible

### `GET /api/admin/debug/database-stats`
**Objectif**: Statistiques détaillées de la base de données  
**Tables analysées**: `transactions`, `token_accounts`, `wallet_priorities`, `scan_history`, `wallet_activity_metrics`, `tokens`

**Analyses par table**:
- Nombre de lignes
- Statistiques spécifiques (selon la table):
  - **transactions**: Token TX, large TX, wallets uniques, TX plus ancienne/récente
  - **wallet_priorities**: Priorité moyenne/min/max, wallets scannés

**Vérifications d'index**: Index critiques pour performance  
**Test de performance**: Requête chronométrée pour évaluer la vitesse

## Routes API - Administration des wallets

### `GET /api/admin/wallets`
**Objectif**: Liste des wallets gérés  
**Informations par wallet**:
- Adresse complète et raccourcie
- Score de priorité et métadonnées
- Temps depuis dernier scan
- Nombre de transactions et comptes token
- Statut (active/inactive/error)

**Fallback**: Liste basique si PriorityManager indisponible

### `PUT /api/admin/wallets/<wallet_address>/priority`
**Objectif**: Mise à jour manuelle de priorité  
**Body**: `{'priority_score': float, 'reason': str}`  
**Validations**:
- Format d'adresse Solana
- Score entre 0.1 et 10.0
- Raison optionnelle

**Actions**:
- Récupération ancienne priorité
- Mise à jour via PriorityManager
- Logging pour audit

### `DELETE /api/admin/wallets/<wallet_address>?confirm=true`
**Objectif**: Suppression de wallet (soft delete)  
**Sécurité**: Confirmation obligatoire  
**Implémentation actuelle**: Désactivation (priorité = 0) au lieu de suppression

## Routes API - Statistiques avancées

### `GET /api/admin/stats/summary?hours=24`
**Objectif**: Résumé exécutif pour administrateurs  
**Sections d'analyse**:

#### System
- Version, environnement, uptime
- Wallets configurés, état du batching

#### Performance
- Requêtes totales, taux d'erreur
- Requêtes moyennes par heure

#### Activity (requêtes DB)
- Scans: Total, durée moyenne, découvertes, taux d'activité
- Transactions: Total, tokens, gros montants

#### Wallets (requêtes DB)
- Total géré, priorité moyenne
- Wallets haute priorité, wallets actifs

#### Alertes automatiques
- **Taux d'erreur élevé**: >10% warning, >25% critical
- **Aucune activité**: 0 scans en X heures
- **Aucune découverte**: Scans sans résultats

**Health Status global**: `critical` > `warning` > `healthy`

## Gestion d'erreurs

### Error Handlers spécialisés
- `400`: Requêtes malformées avec stats d'erreur
- `403`: Accès non autorisé (privilèges admin)
- `500`: Erreurs serveur avec logging détaillé

### Tracking automatique
- Toutes les erreurs incrémentent `_system_stats['errors_count']`
- Logging spécifique pour chaque type d'erreur

## Hooks et middlewares

### `before_request`
- Logging de toutes les requêtes admin pour audit
- Format: `"Admin request: {method} {path} from {remote_addr}"`

### `after_request`
- Headers de sécurité:
  - `X-Admin-Response: true`
  - `X-Frame-Options: DENY`
  - `X-Content-Type-Options: nosniff`

## Constantes et seuils

### Sources des constantes
- `SYSTEM_INFO`: Version, codename système
- `SECURITY_LIMITS`: Limites de sécurité (max wallets, etc.)
- `VALIDATION_PATTERNS`: Patterns de validation (adresses, etc.)
- `API_LIMITS`: Limites d'API (requests, timeouts, etc.)

### Seuils de validation
- Update interval: Minimum 5 secondes
- Database cleanup: 1-365 jours
- Log lines: 10-1000 lignes
- Metrics period: 1-168 heures (7 jours max)
- Priority scores: 0.1-10.0
- Error rate alerts: 10% warning, 25% critical

## Sécurité et audit

### Logging d'audit
- Toutes les requêtes admin loggées
- Actions de maintenance tracées
- Modifications de priorité enregistrées
- Erreurs avec détails complets

### Protection des données sensibles
- Configuration exposée sans secrets
- Adresses wallets formatées (raccourcies)
- Logs avec limitation de lignes
- Validation stricte des paramètres

### Thread safety
- Locks pour statistiques partagées
- Opérations atomiques sur compteurs
- Protection des accès concurrents aux stats

## Formats de réponse standardisés

### Structure API standard
```python
{
    'success': bool,
    'message': str,
    'data': any,
    'timestamp': int
}
```

### Codes de statut
- `200`: Succès opérationnel
- `400`: Paramètres invalides
- `403`: Privilèges insuffisants
- `404`: Ressource non trouvée (logs)
- `500`: Erreur serveur

Cette documentation couvre l'intégralité des fonctionnalités d'administration, du monitoring système, de la maintenance, et des diagnostics avancés sans nécessiter l'accès au code source.