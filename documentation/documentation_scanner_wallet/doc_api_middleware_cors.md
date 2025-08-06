# Documentation - Middleware CORS Flask API

## Vue d'ensemble

Ce module implémente un middleware CORS (Cross-Origin Resource Sharing) avancé pour l'API Flask du Solana Wallet Monitor. Il fournit une gestion intelligente des requêtes cross-origin avec configuration flexible par route, gestion des requêtes preflight, validation robuste des origins et monitoring statistique en temps réel.

## Architecture du Système

### Fonctionnalités Principales
1. **Configuration flexible** : Par défaut et spécifique par route
2. **Gestion preflight** : Handler automatique des requêtes OPTIONS
3. **Validation robuste** : Origins, méthodes, headers avec patterns
4. **Monitoring** : Statistiques temps réel des requêtes CORS
5. **Sécurité** : Restrictions par environnement et validation stricte

### Niveaux de Configuration
- **Globale** : Configuration par défaut pour toutes les routes
- **Par route** : Override spécifique selon patterns de routes
- **Par environnement** : Presets développement vs production

## Modèles de Configuration

### CORSConfig
Configuration centralisée du système CORS avec validation et traitement intelligent.

#### Configuration Source
- **Intégration** : Charge depuis `core.config.get_config()` si disponible
- **Fallback** : Valeurs par défaut sécurisées si module indisponible
- **Attributs config** : 
  - `cors_enabled` (bool, défaut: True)
  - `cors_origins` (List[str], défaut: ['*'])

#### Configuration par Défaut
```python
default_config = {
    'origins': ['*'],  # Origins autorisés (traités et validés)
    'methods': ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
    'headers': [  # Headers autorisés dans les requêtes
        'Content-Type', 'Authorization', 'X-Requested-With',
        'Accept', 'Origin', 'X-API-Key', 'X-Client-Version', 'X-Request-ID'
    ],
    'credentials': True,  # Autorise cookies/credentials
    'max_age': 86400,  # Cache preflight 24h
    'expose_headers': [  # Headers exposés au client
        'X-Total-Count', 'X-Page-Count', 'X-Rate-Limit-Remaining',
        'X-Response-Time', 'X-Request-ID'
    ]
}
```

#### Configuration par Route
- **Route admin** (`/api/admin/*`): Origins restreints, credentials requis
- **Route dashboard** (`/api/dashboard/*`): Origins permissifs, pas de credentials
- **Route batching** (`/api/batching/*`): Origins admin, méthodes limitées

#### Méthodes de Traitement

##### _process_origins(origins: List[str])
- **Description** : Traite et valide la liste des origins
- **Fonctions** :
  - Validation format pour chaque origin
  - Suppression trailing slashes
  - Filtrage origins invalides avec logs warning
  - Fallback à ['*'] si liste vide après filtrage
- **Retour** : List[str] (origins validés)

##### _validate_origin(origin: str)
- **Description** : Valide un origin selon standards RFC
- **Pattern regex** : 
  - Protocole : `^https?://`
  - Domaine : Labels alphanumériques avec tirets
  - TLD : Domaine racine valide
  - Port : Optionnel `:1-65535`
- **Cas spéciaux** : Accepte '*' comme wildcard
- **Retour** : bool

##### _get_admin_origins()
- **Description** : Détermine origins pour routes administratives
- **Logique sécurité** :
  - Évite '*' en production avec warning
  - Fallback à 'https://localhost:3000' si pas d'origins spécifiques
  - Préserve origins explicites en développement
- **Détection environnement** : Via `config.environment.value`

## Classe Principale CORSMiddleware

### Initialisation et État
- **cors_config** (CORSConfig) : Configuration CORS utilisée
- **app** (Flask, optionnel) : Application Flask protégée
- **stats** (Dict) : Statistiques temps réel
  - `preflight_requests` : Compteur requêtes OPTIONS
  - `cors_requests` : Compteur requêtes avec Origin
  - `blocked_origins` : Compteur origins refusés
  - `start_time` : Timestamp démarrage

### Méthodes d'Initialisation

#### init_app(app: Flask)
- **Description** : Intègre le middleware à l'application Flask
- **Mode désactivé** : Log info et bypass si `cors_enabled = False`
- **Intégration active** :
  - Enregistrement handlers before/after_request
  - Route OPTIONS générique pour preflight
  - Logs configuration (origins, credentials)

### Handlers de Requêtes

#### _before_request_handler()
- **Description** : Traitement avant chaque requête
- **Actions** :
  1. Extraction Origin et méthode depuis headers
  2. Mise à jour statistiques (preflight vs CORS normal)
  3. Debug logging avec détails requête
  4. Stockage infos dans Flask g pour after_request
- **Variables g stockées** :
  - `cors_origin` : Origin de la requête
  - `cors_method` : Méthode HTTP
  - `cors_route_config` : Config spécifique à la route

#### _after_request_handler(response)
- **Description** : Traitement après chaque requête pour headers CORS
- **Flux de décision** :
  1. **Origin présent + autorisé** : Headers CORS complets
  2. **Pas d'origin** : Headers basiques (requête non-CORS)
  3. **Origin bloqué** : Statistique blocked_origins, warning log
- **Retour** : Response Flask avec headers CORS ajoutés

### Gestion des Requêtes Preflight

#### _handle_preflight(path)
- **Description** : Handler spécialisé pour requêtes OPTIONS (preflight)
- **Headers analysés** :
  - `Origin` : Source de la requête
  - `Access-Control-Request-Method` : Méthode cible
  - `Access-Control-Request-Headers` : Headers demandés
- **Validations séquentielles** :
  1. Origin présent et autorisé
  2. Méthode dans la liste autorisée pour la route
- **Réponses** :
  - **403** : Origin refusé
  - **405** : Méthode non autorisée  
  - **200** : Preflight autorisé avec headers appropriés

### Gestion des Routes

#### _get_route_config(path: str)
- **Description** : Récupère configuration CORS pour une route spécifique
- **Algorithme** :
  1. Itération patterns dans `route_configs`
  2. Match avec `_match_route_pattern`
  3. Merge avec configuration par défaut
  4. Fallback à config par défaut si pas de match
- **Retour** : Dict (configuration fusionnée)

#### _match_route_pattern(path: str, pattern: str)
- **Description** : Matching de patterns de routes
- **Patterns supportés** :
  - **Exact** : `/api/test` matche exactement
  - **Wildcard** : `/api/admin/*` matche tout sous `/api/admin/`
- **Retour** : bool

### Validation des Origins

#### _is_origin_allowed(origin: str, allowed_origins: List[str])
- **Description** : Vérification autorisation d'un origin
- **Logique de validation** :
  1. **Wildcard** : '*' dans allowed_origins → autorisation globale
  2. **Match exact** : origin dans la liste → autorisé
  3. **Sous-domaines** : Pattern `.example.com` pour autoriser sous-domaines
- **Cas spéciaux** : 
  - Origin vide → refusé
  - `.example.com` matche `sub.example.com` et `example.com`

### Gestion des Headers CORS

#### _add_cors_headers(response, origin: str, config: Dict)
- **Description** : Ajoute headers CORS complets pour requêtes authentifiées
- **Headers ajoutés** :
  - `Access-Control-Allow-Origin` : Origin spécifique (jamais '*' avec credentials)
  - `Access-Control-Allow-Credentials` : Si configuré
  - `Access-Control-Expose-Headers` : Headers exposés au client
  - `X-CORS-Enabled` : Marqueur custom pour debugging

#### _add_basic_cors_headers(response, config: Dict)
- **Description** : Headers basiques pour requêtes non-CORS
- **Usage** : Requêtes serveur-to-serveur sans Origin header

#### _add_preflight_headers(response, origin: str, config: Dict, method: str, headers: str)
- **Description** : Headers spécialisés pour réponses preflight
- **Headers ajoutés** :
  - `Access-Control-Allow-Origin` : Origin de la requête
  - `Access-Control-Allow-Methods` : Méthodes autorisées
  - `Access-Control-Allow-Headers` : Headers autorisés
  - `Access-Control-Max-Age` : Durée de cache preflight
  - `Access-Control-Allow-Credentials` : Si configuré

### Monitoring et Statistiques

#### get_stats()
- **Description** : Compilation statistiques CORS complètes
- **Métriques calculées** :
  - **Uptime** : Temps de fonctionnement en secondes
  - **Compteurs** : Preflights, CORS, origins bloqués
  - **Taux** : Preflights par heure
  - **Configuration** : Origins configurés, nombre de routes
- **Format retour** : Dict avec métriques normalisées

## Décorateurs Utilitaires

### @cors_required(origins=None, methods=None, credentials=True)
- **Description** : Décorateur pour exiger CORS sur route spécifique
- **Paramètres** :
  - `origins` : Liste origins autorisés (override config)
  - `methods` : Méthodes autorisées (override config)
  - `credentials` : Autorisation credentials
- **Validations** :
  - Origin présent et dans la liste autorisée
  - Méthode dans la liste si spécifiée
- **Erreurs** : 403 (origin), 405 (méthode)

### @no_cors
- **Description** : Décorateur pour désactiver CORS sur une route
- **Mécanisme** : Set `g.disable_cors = True`
- **Usage** : Routes internes ou APIs serveur-to-serveur

## Fonctions d'Initialisation et Configuration

### init_cors(app: Flask, config=None)
- **Description** : Initialisation complète CORS sur application Flask
- **Actions** :
  1. Création et initialisation CORSMiddleware
  2. Ajout route `/api/cors/stats` pour monitoring
- **Retour** : Instance CORSMiddleware configurée

### create_cors_config(origins=None, methods=None, credentials=True)
- **Description** : Factory pour configuration CORS personnalisée
- **Personnalisation** : Override des valeurs par défaut
- **Retour** : Instance CORSConfig configurée

## Configurations d'Environnement

### get_development_cors_config()
- **Description** : Configuration permissive pour développement
- **Caractéristiques** :
  - Origins : ['*'] (wildcard complet)
  - Credentials : True
  - Méthodes : Toutes incluant PATCH
  - Headers : Inclut 'X-Debug-Mode'
- **Usage** : Développement local, testing

### get_production_cors_config(allowed_domains: List[str])
- **Description** : Configuration restrictive pour production
- **Sécurité renforcée** :
  - Origins : Domaines explicites uniquement
  - Max-age : Réduit à 3600s (1h)
  - Méthodes : Pas de PATCH
  - Admin routes : Premier domaine seulement
- **Usage** : Déploiement production

## Validation et Tests

### validate_cors_config(config: CORSConfig)
- **Description** : Validation complète d'une configuration CORS
- **Vérifications** :
  - **Origins** : Format et validité selon RFC
  - **Méthodes** : Conformité HTTP standards
  - **Sécurité** : Détection configurations à risque
- **Classifications** :
  - **Errors** : Configurations invalides bloquantes
  - **Warnings** : Configurations à risque mais fonctionnelles
- **Exemples warnings** :
  - Wildcard + autres origins
  - Credentials + wildcard (risque sécurité)

### log_cors_request(origin: str, method: str, path: str, allowed: bool)
- **Description** : Logging détaillé des requêtes CORS
- **Format** : `CORS [✅ AUTORISÉ|🚫 REFUSÉ]: METHOD path depuis origin`
- **Usage** : Debugging, audit, monitoring

## Patterns d'Usage

### Initialisation Standard
```python
from cors_middleware import init_cors, create_cors_config

app = Flask(__name__)

# Configuration personnalisée
cors_config = create_cors_config(
    origins=['http://localhost:3000', 'https://app.example.com'],
    credentials=True
)

# Initialisation
cors_middleware = init_cors(app, cors_config)
```

### Protection de Routes Spécifiques
```python
@app.route('/api/sensitive')
@cors_required(origins=['https://trusted.example.com'])
def sensitive_endpoint():
    return jsonify({'data': 'sensitive'})

@app.route('/api/internal')
@no_cors
def internal_endpoint():
    return jsonify({'internal': 'data'})
```

### Configuration par Environnement
```python
if app.config['ENV'] == 'development':
    cors_config = get_development_cors_config()
else:
    cors_config = get_production_cors_config([
        'https://app.example.com',
        'https://admin.example.com'
    ])

cors_middleware = init_cors(app, cors_config)
```

## Sécurité et Bonnes Pratiques

### Configuration Sécurisée

#### Origins
- **Éviter wildcards** : Spécifier domaines explicites en production
- **Protocoles HTTPS** : Forcer HTTPS pour origins de production
- **Sous-domaines** : Utiliser patterns `.domain.com` avec prudence

#### Credentials
- **Jamais avec wildcard** : Combination credentials + '*' = vulnérabilité
- **HTTPS requis** : Credentials seulement sur connexions chiffrées
- **Validation stricte** : Vérifier origins avant autoriser credentials

#### Headers
- **Limitation** : N'exposer que headers nécessaires
- **Headers sensibles** : Éviter exposition Authorization, API-Keys
- **Custom headers** : Préfixer avec 'X-' pour identification

### Monitoring et Audit

#### Métriques Critiques
- **Blocked origins** : Surveillance tentatives malveillantes
- **Preflight rate** : Détection pics d'activité
- **Error patterns** : Analyse logs pour optimisation

#### Alertes Recommandées
- **Spike blocked origins** : Possible attaque
- **Preflight failures** : Configuration incorrecte
- **Origin validation failures** : Tentatives bypass

## Configuration par Route

### Patterns de Routes Supportés
- **Exact match** : `/api/endpoint` pour route spécifique
- **Prefix match** : `/api/section/*` pour toute une section
- **Priorité** : Premier pattern qui matche est utilisé

### Cas d'Usage Typiques
- **API publique** : Origins permissifs, pas de credentials
- **Dashboard admin** : Origins restreints, credentials requis
- **API interne** : Pas de CORS ou très restrictif
- **Endpoints de monitoring** : CORS basique pour outils

## Intégration et Déploiement

### Variables d'Environnement
- `CORS_ENABLED` : Activation/désactivation globale
- `CORS_ORIGINS` : Liste domains autorisés (JSON array)
- `CORS_CREDENTIALS` : Autorisation credentials globale
- `CORS_MAX_AGE` : Durée cache preflight

### Reverse Proxy (Nginx/Apache)
- **Headers forwarded** : Origin, X-Forwarded-* pour détection correcte
- **Preflight passthrough** : OPTIONS requests transmises à Flask
- **Cache consideration** : Coordination cache proxy + CORS max-age

### CDN et Caching
- **Vary headers** : Inclure Origin pour cache correct
- **Preflight caching** : Durée appropriée selon volatilité config
- **Edge cases** : Gestion origins dynamiques

## Dépendances et Compatibilité

### Bibliothèques Standard
- `flask` : Framework web principal
- `re` : Expressions régulières pour validation
- `logging` : Système de logs
- `datetime` : Gestion temporelle statistiques
- `functools` : Décorateurs wraps

### Intégration Optionnelle
- `core.config` : Configuration centralisée projet
- Graceful degradation si module indisponible

### Compatibilité Navigateurs
- **Standards** : CORS selon RFC 6454
- **Preflight** : Gestion OPTIONS selon CORS spec
- **Credentials** : Support cookies et authentication
- **Headers custom** : Validation stricte selon standards