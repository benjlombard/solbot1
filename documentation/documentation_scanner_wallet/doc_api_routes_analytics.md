# Solana Wallet Analytics API - Documentation Technique

## Vue d'ensemble

**Fichier**: `analytics.py`  
**Type**: Module de routes FastAPI  
**Fonction**: API REST pour l'analyse complète de wallets Solana

### Description
Module fournissant des endpoints REST pour l'analyse de wallets Solana incluant l'analyse des transactions, l'analyse de portefeuille, les métriques de performance, l'évaluation des risques et l'analyse de tokens.

## Architecture et Dépendances

### Imports principaux
- **FastAPI**: Framework web (`APIRouter`, `HTTPException`, `Query`, `Depends`)
- **Pydantic**: Validation de données (`BaseModel`, `Field`, `validator`)
- **Core modules**: Modules métier personnalisés
- **Standard library**: `logging`, `datetime`, `typing`

### Services core utilisés
1. **WalletAnalyzer**: Analyse complète de wallet
2. **TransactionProcessor**: Traitement des transactions
3. **PortfolioTracker**: Suivi de portefeuille
4. **DataCollector**: Collection de données

### Gestion d'erreurs
- **SolanaRPCError**: Erreurs RPC blockchain (HTTP 503)
- **DataProcessingError**: Erreurs traitement données (HTTP 422)
- **ValidationError**: Erreurs validation (HTTP 400)
- **RateLimitError**: Erreurs limite taux
- **Exception générique**: Erreur serveur (HTTP 500)

## Modèles de données (Pydantic)

### Modèles de requête

#### `WalletAnalysisRequest`
```python
- wallet_address: str (requis, 32-44 caractères)
- days: Optional[int] = 30 (1-365)
- include_tokens: Optional[bool] = True
- include_nfts: Optional[bool] = False
```

#### `TransactionAnalysisRequest`
```python
- wallet_address: str (requis)
- start_date: Optional[datetime] = None
- end_date: Optional[datetime] = None
- limit: Optional[int] = 100 (1-1000)
- transaction_type: Optional[str] = None
```

#### `PortfolioAnalysisRequest`
```python
- wallet_address: str (requis)
- include_historical: Optional[bool] = True
- currency: Optional[str] = "USD"
```

#### `TokenAnalysisRequest`
```python
- wallet_address: str (requis)
- token_address: Optional[str] = None
- min_value: Optional[float] = 0 (>=0)
```

### Modèles de réponse

#### `WalletAnalysisResponse`
```python
- wallet_address: str
- analysis_date: datetime
- summary: Dict[str, Any]
- transactions: Dict[str, Any]
- portfolio: Dict[str, Any]
- performance: Dict[str, Any]
- risk_metrics: Dict[str, Any]
```

#### `TransactionAnalysisResponse`
```python
- wallet_address: str
- transaction_count: int
- date_range: Dict[str, datetime]
- transactions: List[Dict[str, Any]]
- summary: Dict[str, Any]
```

#### `PortfolioAnalysisResponse`
```python
- wallet_address: str
- total_value: float
- tokens: List[Dict[str, Any]]
- allocation: Dict[str, float]
- performance: Dict[str, Any]
```

## Endpoints API

### 1. **GET /** - Information API
- **Fonction**: Informations sur les endpoints disponibles
- **Retour**: Métadonnées API et liste des endpoints
- **Statut**: 200 OK

### 2. **POST /wallet/analyze** - Analyse complète wallet
- **Fonction**: Analyse complète d'un wallet Solana
- **Body**: `WalletAnalysisRequest`
- **Retour**: `WalletAnalysisResponse`
- **Services**: `WalletAnalyzer.analyze_wallet()`
- **Features**:
  - Historique des transactions
  - Composition du portefeuille
  - Métriques de performance
  - Évaluation des risques
  - Analyse des tokens/NFTs

### 3. **POST /transactions/analyze** - Analyse transactions
- **Fonction**: Analyse détaillée de l'historique des transactions
- **Body**: `TransactionAnalysisRequest`
- **Retour**: `TransactionAnalysisResponse`
- **Services**: `TransactionProcessor.analyze_transactions()`
- **Features**:
  - Catégorisation des transactions
  - Métriques de volume/fréquence
  - Détection de patterns
  - Calculs profit/perte

### 4. **POST /portfolio/analyze** - Analyse portefeuille
- **Fonction**: Analyse de la composition et performance du portefeuille
- **Body**: `PortfolioAnalysisRequest`
- **Retour**: `PortfolioAnalysisResponse`
- **Services**: `PortfolioTracker.analyze_portfolio()`
- **Features**:
  - Holdings actuels et valeurs
  - Répartition du portefeuille
  - Métriques de performance
  - Analyse de diversification

### 5. **POST /tokens/analyze** - Analyse tokens
- **Fonction**: Analyse détaillée des holdings et transactions de tokens
- **Body**: `TokenAnalysisRequest`
- **Services**: `DataCollector.analyze_tokens()`
- **Features**:
  - Positions et changements
  - Activité de trading
  - Métriques de performance
  - Métadonnées des tokens

### 6. **GET /wallet/{wallet_address}/summary** - Résumé wallet
- **Fonction**: Aperçu rapide de l'activité et holdings
- **Params**: `wallet_address` (path), `days` (query, 1-365)
- **Services**: `WalletAnalyzer.get_wallet_summary()`
- **Features**:
  - Balance actuelle
  - Activité récente
  - Top holdings
  - Métriques clés

### 7. **GET /wallet/{wallet_address}/transactions** - Transactions paginées
- **Fonction**: Liste paginée des transactions du wallet
- **Params**: `limit` (1-500), `before` (signature pour pagination)
- **Services**: `TransactionProcessor.get_transactions()`

### 8. **GET /wallet/{wallet_address}/portfolio** - Portefeuille actuel
- **Fonction**: Holdings et valeurs actuelles du portefeuille
- **Services**: `PortfolioTracker.get_current_portfolio()`

### 9. **GET /wallet/{wallet_address}/performance** - Métriques performance
- **Fonction**: Métriques de performance pour la période spécifiée
- **Params**: `days` (1-365)
- **Services**: `WalletAnalyzer.get_performance_metrics()`

### 10. **GET /health** - Health check
- **Fonction**: Vérification de santé du service et dépendances
- **Retour**: Statut des services (200 OK ou 503 Service Unavailable)

## Fonctions de dépendances

### Injection de dépendances FastAPI
```python
- get_wallet_analyzer() -> WalletAnalyzer
- get_transaction_processor() -> TransactionProcessor
- get_portfolio_tracker() -> PortfolioTracker
- get_data_collector() -> DataCollector
```

## Validation et sécurité

### Validation wallet address
- **Longueur**: 32-44 caractères
- **Validation**: Via validator Pydantic sur `WalletAnalysisRequest.wallet_address`

### Limites de requête
- **Jours d'analyse**: 1-365
- **Limite transactions**: 1-1000 (analyse), 1-500 (listing)
- **Valeur minimum token**: >=0

## Logging et monitoring

### Logger
- **Instance**: `logger = logging.getLogger(__name__)`
- **Événements loggés**:
  - Début d'analyses (INFO)
  - Erreurs par type (ERROR)
  - Health check failures (ERROR)

### Métriques capturées
- Adresses wallet analysées
- Types d'erreurs rencontrées
- Temps de réponse (implicite via FastAPI)

## Structure des réponses

### Format de réponse standard
```json
{
  "wallet_address": "string",
  "timestamp/analysis_date": "datetime",
  "data": "object",
  "metadata": "object"
}
```

### Codes de statut HTTP
- **200**: Succès
- **400**: Erreur de validation
- **422**: Erreur de traitement des données
- **500**: Erreur serveur interne
- **503**: Service blockchain indisponible

## Points d'extension

### Nouvelles fonctionnalités possibles
1. **Authentification**: Ajout de middleware d'auth
2. **Rate limiting**: Implémentation de limites par utilisateur
3. **Caching**: Cache Redis pour les réponses fréquentes
4. **WebSocket**: Endpoints temps réel
5. **Export**: Endpoints d'export PDF/Excel
6. **Alertes**: Système de notifications

### Optimisations techniques
1. **Pagination avancée**: Cursors pour grandes datasets
2. **Async processing**: Jobs en arrière-plan pour analyses lourdes
3. **Batch operations**: Analyse multiple wallets
4. **Historical data**: Stockage et requête de données historiques

## Configuration requise

### Variables d'environnement (via `settings`)
- Configuration RPC Solana
- Paramètres de base de données
- Clés API services externes
- Paramètres de logging

### Dépendances externes
- **Blockchain**: Node RPC Solana
- **Prix**: APIs de données de marché
- **Storage**: Base de données pour cache/historique