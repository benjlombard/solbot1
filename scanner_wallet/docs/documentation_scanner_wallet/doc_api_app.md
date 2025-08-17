# FastAPI Main Application - Documentation Technique

## Vue d'ensemble

**Fichier**: `app.py`  
**Type**: Application FastAPI principale  
**Fonction**: Configuration et démarrage de l'API Solana Wallet Analytics

### Description
Module principal qui configure l'application FastAPI avec tous les routes, middleware, gestion d'erreurs, et configuration système. Point d'entrée de l'application.

## Architecture et Dépendances

### Imports principaux
- **FastAPI Core**: `FastAPI`, `Request`, `HTTPException`
- **Middleware**: `CORSMiddleware`
- **Responses**: `JSONResponse`
- **Exception Handling**: `http_exception_handler`
- **Routes**: `analytics` router
- **Core**: `settings`, exceptions personnalisées
- **Standard Library**: `logging`, `sys`, `traceback`, `time`, `datetime`, `contextlib`

### Exceptions personnalisées gérées
- **SolanaRPCError**: Erreurs RPC blockchain
- **DataProcessingError**: Erreurs traitement données
- **ValidationError**: Erreurs de validation
- **RateLimitError**: Erreurs de limite de taux

## Configuration de l'application

### Instance FastAPI
```python
app = FastAPI(
    title="Solana Wallet Analytics API",
    description="API for analyzing Solana wallet transactions and providing analytics insights",
    version="1.0.0",
    docs_url="/docs" (si DEBUG),
    redoc_url="/redoc" (si DEBUG),
    openapi_url="/openapi.json" (si DEBUG),
    lifespan=lifespan
)
```

### Configuration des docs
- **Docs activées**: Seulement en mode DEBUG
- **URLs conditionnelles**: `/docs`, `/redoc`, `/openapi.json`
- **Sécurité**: Docs désactivées en production

## Logging

### Configuration système
```python
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        StreamHandler(sys.stdout),  # Console
        FileHandler('logs/app.log')  # Fichier (si LOG_TO_FILE=True)
    ]
)
```

### Niveaux de log
- **Niveau**: Configuré via `settings.LOG_LEVEL`
- **Format**: Timestamp + nom + niveau + message
- **Sortie**: Console + fichier optionnel
- **Logger**: Instance `logger = logging.getLogger(__name__)`

## Lifecycle Management

### Gestionnaire de cycle de vie
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    - Log informations démarrage
    - Log configuration (environnement, debug, log level)
    - Initialisation services (placeholder)
    
    yield
    
    # Shutdown
    - Log arrêt application
```

### Informations loggées au démarrage
- Message de démarrage
- Environnement d'exécution
- Mode debug
- Niveau de log

## Middleware

### CORS Middleware
```python
CORSMiddleware(
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"]
)
```

### Request Logging Middleware
```python
@app.middleware("http")
async def log_requests(request, call_next):
    # Pré-traitement
    - Log de la requête (méthode + URL)
    - Log du body pour POST/PUT/PATCH (500 premiers caractères)
    - Mesure du temps de démarrage
    
    # Post-traitement
    - Log de la réponse (code statut + temps + chemin)
    - Calcul du temps de traitement
```

## Gestion d'erreurs personnalisées

### 1. SolanaRPCError Handler
- **Code HTTP**: 503 Service Unavailable
- **Type**: "solana_rpc_error"
- **Contenu**: Message d'erreur + détails optionnels
- **Log**: ERROR level

### 2. DataProcessingError Handler
- **Code HTTP**: 422 Unprocessable Entity
- **Type**: "data_processing_error"
- **Contenu**: Message d'erreur + détails optionnels
- **Log**: ERROR level

### 3. ValidationError Handler
- **Code HTTP**: 400 Bad Request
- **Type**: "validation_error"
- **Contenu**: Message d'erreur + détails optionnels
- **Log**: ERROR level

### 4. RateLimitError Handler
- **Code HTTP**: 429 Too Many Requests
- **Type**: "rate_limit_error"
- **Contenu**: Message + retry_after optionnel
- **Log**: WARNING level

### 5. Exception Handler (général)
- **Code HTTP**: 500 Internal Server Error
- **Type**: "internal_error"
- **Debug mode**: Inclut traceback complet
- **Production mode**: Message générique seulement
- **Log**: ERROR level + traceback

## Format des réponses d'erreur

### Structure standard
```json
{
  "error": "Type d'erreur lisible",
  "message": "Message d'erreur détaillé",
  "type": "code_type_erreur",
  "details": "Détails optionnels",
  "retry_after": "Pour rate limit seulement",
  "traceback": "En mode debug seulement"
}
```

## Endpoints système

### 1. **GET /health** - Health Check
```python
Retour:
{
  "status": "healthy",
  "timestamp": "ISO datetime",
  "version": "1.0.0",
  "environment": "settings.ENVIRONMENT"
}
```

### 2. **GET /** - Root Information
```python
Retour:
{
  "name": "Solana Wallet Analytics API",
  "version": "1.0.0", 
  "description": "API description",
  "docs_url": "/docs" (si DEBUG),
  "health_check": "/health"
}
```

## Routeurs inclus

### Analytics Router
- **Préfixe**: `/api/v1/analytics`
- **Tags**: ["analytics"]
- **Source**: `analytics.router`
- **Fonction**: Tous les endpoints d'analyse de wallets

## Configuration serveur

### Variables de configuration (via settings)
- **API_HOST**: Adresse d'écoute
- **API_PORT**: Port d'écoute
- **DEBUG**: Mode debug
- **LOG_LEVEL**: Niveau de logging
- **LOG_TO_FILE**: Log vers fichier
- **ENVIRONMENT**: Environnement d'exécution
- **ALLOWED_ORIGINS**: Origines CORS autorisées

### Démarrage avec Uvicorn
```python
uvicorn.run(
    "api.app:app",
    host=settings.API_HOST,
    port=settings.API_PORT,
    reload=settings.DEBUG,
    log_level=settings.LOG_LEVEL.lower(),
    access_log=True
)
```

## Sécurité et Production

### Mode Production
- **Docs désactivées**: Pas de `/docs`, `/redoc`, `/openapi.json`
- **Erreurs masquées**: Traceback non exposé
- **Logging contrôlé**: Niveau de log configuré

### Mode Debug  
- **Docs activées**: Documentation interactive disponible
- **Erreurs détaillées**: Traceback complet dans les réponses
- **Reload automatique**: Uvicorn avec reload=True

## Monitoring et Observabilité

### Métriques loggées
- **Requêtes entrantes**: Méthode + URL
- **Corps de requête**: Premiers 500 caractères (POST/PUT/PATCH)
- **Réponses**: Code statut + temps de traitement + chemin
- **Erreurs**: Tous types d'erreurs avec contexte
- **Cycle de vie**: Démarrage et arrêt de l'application

### Format de log des requêtes
```
INFO - Request: METHOD URL
DEBUG - Request body: {body[:500]}...
INFO - Response: STATUS_CODE - Time: X.XXXs - Path: /path
```

## Points d'extension

### Améliorations possibles
1. **Monitoring avancé**: 
   - Métriques Prometheus
   - Traces distribués
   - Health checks détaillés des dépendances

2. **Sécurité**:
   - Authentification JWT
   - Rate limiting par utilisateur
   - Validation d'entrée renforcée

3. **Performance**:
   - Cache middleware (Redis)
   - Compression des réponses
   - Connection pooling

4. **Observabilité**:
   - Structured logging (JSON)
   - Correlation IDs
   - Alerting sur erreurs

### Configuration avancée
- **Environnements multiples**: Dev/Staging/Prod
- **Secrets management**: Variables sensibles
- **Feature flags**: Activation/désactivation de fonctionnalités
- **Circuit breakers**: Protection contre les pannes en cascade

## Structure des dépendances

### Hiérarchie des modules
```
app.py (main)
├── api/routes/analytics.py (routes analytics)
├── core/config.py (configuration)
├── core/exceptions.py (exceptions personnalisées)
└── services core (WalletAnalyzer, TransactionProcessor, etc.)
```

### Ordre d'initialisation
1. Configuration logging
2. Création instance FastAPI
3. Ajout middlewares (CORS, Request logging)
4. Configuration exception handlers
5. Définition endpoints système
6. Inclusion des routers
7. Démarrage serveur Uvicorn