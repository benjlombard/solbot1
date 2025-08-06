# Documentation - Middleware d'Authentification Flask API

## Vue d'ensemble

Ce module implémente un système d'authentification multi-niveaux complet pour l'API Flask du Solana Wallet Monitor. Il combine authentification par clés API, tokens JWT, rate limiting avancé, gestion des permissions et monitoring statistique en temps réel.

## Architecture du Système

### Méthodes d'Authentification Supportées
1. **API Keys** : Clés permanentes avec permissions granulaires
2. **JWT Tokens** : Tokens temporaires pour sessions utilisateur
3. **Mode Public** : Routes sans authentification requise

### Niveaux d'Accès
- **Public** : Routes ouvertes sans authentification
- **User** : Accès authentifié standard
- **Admin** : Accès privilégié pour configuration système

## Modèles de Données

### ApiKeyInfo
Représente une clé API avec ses métadonnées et permissions.

#### Identification et Sécurité
- **key_id** (str): Identifiant unique de la clé
- **key_hash** (str): Hash SHA-256 de la clé pour stockage sécurisé
- **name** (str): Nom descriptif de la clé

#### Permissions et Restrictions
- **permissions** (List[str]): Liste des permissions accordées (défaut: [])
- **allowed_ips** (List[str], optionnel): IPs autorisées pour cette clé
- **is_active** (bool): État d'activation de la clé (défaut: True)
- **expires_at** (int, optionnel): Timestamp d'expiration

#### Rate Limiting et Usage
- **rate_limit_per_hour** (int): Limite de requêtes/heure (défaut: 1000)
- **usage_count** (int): Nombre total d'utilisations (défaut: 0)
- **last_used** (int, optionnel): Timestamp de dernière utilisation

#### Timestamps
- **created_at** (int): Timestamp de création (auto-généré)

#### Méthodes Principales

##### is_expired()
- **Description**: Vérifie si la clé a expiré
- **Logique**: Compare expires_at avec timestamp actuel
- **Retour**: bool

##### can_access(permission: str)
- **Description**: Vérifie l'autorisation pour une permission spécifique
- **Vérifications**: Activation, expiration, puis permissions
- **Logique permissions**: 
  - '*' = accès total
  - permission exacte dans la liste
- **Retour**: bool

##### is_ip_allowed(ip: str)
- **Description**: Vérifie si l'IP client est autorisée
- **Logique**: None = toutes IPs autorisées, sinon vérification liste
- **Retour**: bool

##### update_usage()
- **Description**: Met à jour les statistiques d'usage
- **Actions**: MAJ last_used et incrémente usage_count

### AuthConfig
Configuration centralisée du système d'authentification.

#### Configuration JWT
- **jwt_secret** (str): Clé secrète pour signature JWT (auto-générée si absente)
- **jwt_expiry_hours** (int): Durée de validité JWT en heures (défaut: 24)

#### État du Système
- **api_auth_enabled** (bool): Active/désactive l'authentification (défaut: False)

#### Routes et Permissions
- **admin_routes** (List[str]): Patterns de routes nécessitant accès admin
- **public_routes** (List[str]): Patterns de routes publiques sans auth

#### Rate Limiting
- **rate_limits** (Dict[str, int]): Limites par type de compte
  - 'default': 1000 req/h
  - 'admin': 5000 req/h
  - 'public': 100 req/h
  - 'premium': 10000 req/h

#### Clés par Défaut
- **default_api_keys** (Dict[str, ApiKeyInfo]): Clés préconfigurées pour développement

#### Méthodes de Configuration

##### Initialisation depuis core.config
- **Intégration**: Charge automatiquement depuis `core.config.get_config()`
- **Fallback**: Valeurs par défaut si module config indisponible
- **Sécurité**: Génération automatique du JWT secret

##### _generate_secret()
- **Description**: Génère un secret JWT cryptographiquement sécurisé
- **Méthode**: `secrets.token_urlsafe(64)` (URL-safe base64, 64 bytes)
- **Usage**: Automatique si secret non fourni

##### _init_default_keys()
- **Description**: Initialise les clés API pour développement
- **Clés créées**:
  - **Admin**: `swm_admin_*` avec permissions ['*']
  - **ReadOnly**: `swm_readonly_*` avec permissions ['read', 'dashboard']
- **Sécurité**: Logs des clés générées avec avertissement production

##### _hash_key(key: str)
- **Description**: Hash sécurisé des clés API
- **Méthode**: SHA-256 hexadecimal
- **Usage**: Stockage sans exposer la clé réelle

## Classe Principale AuthMiddleware

### Initialisation et Configuration
- **app** (Flask, optionnel): Application Flask à protéger
- **auth_config** (AuthConfig, optionnel): Configuration personnalisée
- **api_keys** (Dict): Dictionnaire des clés API actives
- **rate_limiter** (RateLimiter): Instance du rate limiter
- **auth_stats** (Dict): Statistiques en temps réel
- **_lock** (threading.Lock): Protection thread-safe des statistiques

### Méthodes d'Initialisation

#### init_app(app: Flask)
- **Description**: Intègre le middleware à l'application Flask
- **Mode désactivé**: Ajoute seulement le tracking statistique
- **Mode activé**: Configure handlers complets before/after_request
- **Logs**: Information sur l'état d'activation et configuration

### Handlers de Requêtes

#### _before_request_handler()
- **Description**: Traitement avant chaque requête
- **Flux d'exécution**:
  1. Incrémentation statistiques globales
  2. Vérification route publique (bypass si oui)
  3. Rate limiting par IP client
  4. Tentative d'authentification multi-méthodes
  5. Vérification permissions admin si nécessaire
  6. Stockage informations auth dans Flask g
- **Réponses d'erreur**: 429 (rate limit), 401 (auth), 403 (permissions)

#### _after_request_handler(response)
- **Description**: Traitement après chaque requête
- **Actions**:
  - Ajout headers informatifs (X-Auth-Method, X-Auth-Level)
  - Mise à jour statistiques d'usage des clés API
- **Retour**: Response Flask modifiée

### Méthodes d'Authentification

#### _authenticate_request()
- **Description**: Orchestrateur principal d'authentification
- **Stratégie**: Tentative séquentielle API Key puis JWT
- **Retour**: Dict avec success, error, method, level, user, etc.

#### _authenticate_api_key()
- **Description**: Authentification par clé API
- **Sources de clé**:
  - Header `X-API-Key`
  - Header `Authorization: Bearer swm_*`
- **Vérifications séquentielles**:
  1. Présence de la clé
  2. Existence dans le système (hash match)
  3. État actif
  4. Non-expirée
  5. IP autorisée
  6. Rate limiting respecté
- **Niveau d'accès**: 'admin' si '*' dans permissions, sinon 'user'

#### _authenticate_jwt()
- **Description**: Authentification par token JWT
- **Source**: Header `Authorization: Bearer <token>` (non swm_*)
- **Vérifications**:
  1. Format Bearer valide
  2. Décodage JWT avec secret
  3. Expiration du token
  4. Claims requis (sub)
- **Gestion erreurs**: Capture `jwt.InvalidTokenError`

### Gestion des Routes

#### _is_public_route(path: str), _is_admin_route(path: str)
- **Description**: Classification des routes selon patterns
- **Usage**: Détermine les exigences d'authentification

#### _match_route_pattern(path: str, pattern: str)
- **Description**: Matching de patterns de routes
- **Support**: Wildcards avec `*` en fin de pattern
- **Exemples**: `/api/admin/*` matche `/api/admin/test`

### Utilitaires Réseau

#### _get_client_ip()
- **Description**: Extraction IP client avec support proxy
- **Headers supportés**: X-Forwarded-For, X-Real-IP, X-Client-IP, CF-Connecting-IP
- **Fallback**: `request.remote_addr`
- **Traitement**: Première IP si liste séparée par virgules

### Gestion des Tokens et Clés

#### create_jwt_token(user: str, level: str = 'user', expires_hours: Optional[int] = None)
- **Description**: Génération de tokens JWT
- **Claims standards**: sub, level, iat, exp, iss
- **Signature**: HMAC-SHA256 avec jwt_secret
- **Personnalisation**: Expiration configurable

#### create_api_key(name: str, permissions: List[str], ...)
- **Description**: Création de nouvelles clés API
- **Format clé**: `swm_{key_id}_{token_32_bytes}`
- **Stockage**: Hash sécurisé dans self.api_keys
- **Options**: Expiration, rate limiting, restrictions IP

#### revoke_api_key(key_id: str)
- **Description**: Révocation d'une clé API
- **Méthode**: Désactivation (is_active = False)
- **Conservation**: Garde l'historique d'usage

### Monitoring et Statistiques

#### get_stats()
- **Description**: Compilation des statistiques complètes
- **Métriques incluses**:
  - Compteurs de requêtes par type
  - Taux d'authentification et de succès
  - Uptime et performance
  - État des clés API
  - Statistiques du rate limiter
- **Calculs**: Taux par heure, pourcentages de succès

## Classe RateLimiter

### Principe de Fonctionnement
- **Algorithme**: Sliding window par heure
- **Stockage**: Timestamps des requêtes par client
- **Thread-safety**: Protection par lock

### Structure de Données
- **requests** (defaultdict): `{client_id: [timestamps]}`
- **stats** (Dict): Compteurs de performance
- **_lock** (threading.Lock): Synchronisation

### Méthodes Principales

#### can_proceed(client_id: str, limit_per_hour: int = 1000)
- **Description**: Vérification et enregistrement de requête
- **Algorithme**:
  1. Nettoyage timestamps > 1h
  2. Vérification limite
  3. Ajout timestamp si autorisé
- **Thread-safety**: Opération atomique avec lock

#### cleanup_old_entries()
- **Description**: Maintenance périodique
- **Actions**: Suppression timestamps expirés et clients inactifs
- **Usage**: Appelé périodiquement pour optimiser mémoire

#### get_stats()
- **Description**: Métriques du rate limiter
- **Retour**: Clients actifs, vérifications totales, requêtes bloquées

## Décorateurs d'Authentification

### @auth_required(level: str = 'user')
- **Description**: Décorateur pour exiger authentification
- **Vérifications**: Présence auth dans Flask g, niveau suffisant
- **Usage**: `@auth_required('admin')` pour routes admin

### @permission_required(permission: str)
- **Description**: Décorateur pour permissions spécifiques
- **Prérequis**: Authentification par API Key
- **Vérification**: `api_key_info.can_access(permission)`

### @rate_limited(requests_per_hour: int = 100)
- **Description**: Rate limiting spécifique à un endpoint
- **Identification**: IP client + nom de route
- **Instance**: Rate limiter local (non partagé)

## Configuration des Routes

### Routes Publiques par Défaut
```
/api/health
/api/dashboard-data  
/api/recent-balance-changes
/api/cors/stats
```

### Routes Admin par Défaut
```
/api/admin/*
/api/batching/config*
/api/priority-update*
/api/maintenance/*
```

### Routes d'Authentification Ajoutées

#### GET /api/auth/stats
- **Auth**: Admin requis
- **Retour**: Statistiques complètes du système auth

#### POST /api/auth/login
- **Auth**: Publique
- **Fonction**: Authentification utilisateur basique
- **Retour**: JWT token si succès

#### POST /api/auth/create-key
- **Auth**: Admin requis
- **Fonction**: Création de nouvelles clés API
- **Paramètres**: name, permissions, expires_hours, rate_limit

## Intégration et Usage

### Initialisation Standard
```python
from auth_middleware import init_auth, AuthConfig

app = Flask(__name__)

# Configuration
auth_config = AuthConfig()
auth_config.api_auth_enabled = True

# Initialisation
auth_middleware = init_auth(app, auth_config)
```

### Protection d'Endpoints
```python
@app.route('/api/protected')
@auth_required('user')
def protected_endpoint():
    return jsonify({
        'user': g.auth_user,
        'level': g.auth_level
    })

@app.route('/api/admin/action')  
@auth_required('admin')
@permission_required('admin_action')
def admin_action():
    return jsonify({'status': 'executed'})
```

### Usage des Clés API
```python
# Headers acceptés:
# X-API-Key: swm_key_12345_abcdef...
# Authorization: Bearer swm_key_12345_abcdef...

# Création programmatique
api_key = auth_middleware.create_api_key(
    name="Service Account",
    permissions=["read", "write"],
    rate_limit=5000,
    expires_hours=24*30  # 30 jours
)
```

### Usage JWT
```python
# Login et récupération token
token = auth_middleware.create_jwt_token(
    user="admin",
    level="admin", 
    expires_hours=8
)

# Headers:
# Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...
```

## Sécurité et Bonnes Pratiques

### Stockage Sécurisé
- **Clés API**: Jamais stockées en clair, seulement hash SHA-256
- **JWT Secret**: Généré cryptographiquement, 64 bytes
- **Expiration**: Gestion automatique pour tokens et clés

### Rate Limiting
- **Par IP**: Protection DDoS
- **Par clé API**: Prévention abus
- **Par endpoint**: Protection fine-granularity
- **Sliding window**: Algorithme fair et précis

### Validation Robuste
- **IP whitelisting**: Restriction géographique
- **Expiration**: Limitation temporelle
- **Permissions**: Contrôle granulaire
- **Thread-safety**: Sécurité multi-thread

### Monitoring
- **Statistiques temps réel**: Détection anomalies
- **Logging sécurisé**: Traçabilité sans exposition secrets
- **Headers informatifs**: Debug et audit

## Configuration Production

### Variables d'Environnement Recommandées
- `JWT_SECRET`: Secret fort généré offline
- `API_AUTH_ENABLED`: True pour production
- `JWT_EXPIRY_HOURS`: 1-8h pour sécurité renforcée
- `RATE_LIMIT_DEFAULT`: Adapté au traffic attendu

### Clés API Production
- **Rotation**: Renouvellement périodique
- **Least privilege**: Permissions minimales nécessaires
- **Monitoring**: Surveillance usage inhabituel
- **Révocation**: Processus de révocation d'urgence

### Infrastructure
- **Proxy headers**: Configuration pour IP réelle
- **HTTPS**: Chiffrement transport obligatoire
- **Logging**: Audit trails complets
- **Backup**: Sauvegarde configuration auth

## Dépendances

### Bibliothèques Principales
- `flask`: Framework web
- `PyJWT`: Gestion tokens JWT
- `secrets`: Génération cryptographique sécurisée
- `hashlib`: Fonctions de hachage
- `hmac`: HMAC pour JWT

### Bibliothèques Standard
- `functools`: Décorateurs
- `threading`: Thread-safety
- `collections`: defaultdict pour rate limiting
- `logging`: Système de logs
- `datetime`: Gestion temporelle
- `time`: Timestamps Unix

### Intégration Optionnelle
- `core.config`: Configuration centralisée du projet
- Graceful degradation si module indisponible