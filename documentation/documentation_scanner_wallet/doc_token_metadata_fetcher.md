# Solana Token Metadata Fetcher - Documentation Technique

## Vue d'ensemble

Le **Solana Token Metadata Fetcher** est un système avancé de récupération de métadonnées de tokens avec mise en cache, fournisseurs multiples avec fallback et validation. Il fournit une architecture robuste pour obtenir des informations complètes sur les tokens Solana depuis diverses sources d'API.

## Architecture générale

### Imports et dépendances

**Imports système :**
- `time`, `json`, `requests`, `threading` - Fonctionnalités système et HTTP
- `typing` - Annotations de type (Dict, List, Optional, Tuple, Any, Union)
- `dataclasses.dataclass` - Décorateur pour structures de données
- `datetime.{datetime, timedelta}` - Gestion des dates
- `logging` - Système de logs

**Imports métier avec fallbacks :**
- `core.logger.get_logger` → fallback: `logging.getLogger()`
- `core.config.get_config` → fallback: objet Config simulé
- `models.token.Token` → fallback: classe Token simple
- `token.cache_manager.{get_token_metadata_cache, get_price_cache}` → pas de fallback
- `utils.helpers.{get_current_timestamp, safe_divide}` → fallbacks simples
- `utils.validators.validate_token_mint` → fallback basique

**Configuration fallback :**
```python
Config().metadata = {
    'providers': ['jupiter', 'coingecko', 'solscan'],
    'timeout': 10,
    'retries': 3
}
```

**Token fallback :**
```python
class Token:
    def __init__(self, address, symbol=None, name=None, decimals=9, **kwargs):
        self.address = address
        self.symbol = symbol or "UNKNOWN"
        self.name = name or "Unknown Token"  
        self.decimals = decimals
```

## Structures de données

### MetadataFetchResult

```python
@dataclass
class MetadataFetchResult:
    success: bool                    # Succès de l'opération
    token: Optional[Token] = None    # Objet Token récupéré
    source: str = "unknown"          # Source des données
    fetch_time: float = 0.0          # Temps de récupération en secondes
    error: Optional[str] = None      # Message d'erreur si échec
    metadata: Dict[str, Any] = None  # Métadonnées brutes du provider
```

## Classe principale : TokenMetadataFetcher

### Initialisation

**Attributs d'instance :**
- `self.config` - Configuration via `get_config()`
- `self.metadata_cache` - Cache métadonnées via `get_token_metadata_cache()`
- `self.price_cache` - Cache prix via `get_price_cache()`
- `self.providers` - Configuration des fournisseurs d'API
- `self.request_counts = defaultdict(int)` - Compteurs rate limiting
- `self.last_reset = get_current_timestamp()` - Dernière réinitialisation compteurs
- `self.fetch_lock = threading.RLock()` - Verrou thread-safety

### Configuration des fournisseurs

**Structure self.providers :**
```python
{
    'jupiter': {
        'base_url': 'https://token.jup.ag',
        'endpoints': {
            'metadata': '/all',
            'price': '/price/v2'
        },
        'rate_limit': 100  # requêtes par minute
    },
    'coingecko': {
        'base_url': 'https://api.coingecko.com/api/v3',
        'endpoints': {
            'metadata': '/coins/markets',
            'price': '/simple/price'
        },
        'rate_limit': 50
    },
    'solscan': {
        'base_url': 'https://public-api.solscan.io',
        'endpoints': {
            'metadata': '/token/meta',
            'price': '/market/token'
        },
        'rate_limit': 30
    },
    'fallback': {
        'base_url': 'https://raw.githubusercontent.com/solana-labs/token-list/main/src/tokens',
        'endpoints': {
            'metadata': '/solana.tokenlist.json'
        },
        'rate_limit': 1000
    }
}
```

**Log d'initialisation :** "✅ Token Metadata Fetcher initialized"

### Méthodes principales

#### 1. `fetch_metadata(token_mint: str, force_refresh: bool = False) -> MetadataFetchResult`

**Fonction :** Récupère métadonnées de token avec cache et fallbacks

**Processus complet :**

1. **Validation :**
   - Validation adresse mint via `validate_token_mint()`
   - Si invalide → retour `MetadataFetchResult` avec erreur
   - Mesure temps de début

2. **Vérification cache :**
   - Si `force_refresh = False`
   - Appel `self.metadata_cache.get_token_metadata(token_mint)`
   - Si trouvé → log "📦 Using cached metadata" et retour immédiat avec source "cache"

3. **Tentatives providers :**
   - Itération sur providers via `_get_provider_order()`
   - Pour chaque provider :
     - Appel `_fetch_from_provider(token_mint, provider)`
     - Si succès → cache résultat via `metadata_cache.cache_token_metadata()`
     - Log "✅ Fetched metadata from {provider}"
     - Retour `MetadataFetchResult` avec source provider

4. **Génération fallback :**
   - Si tous providers échouent
   - Appel `_generate_fallback_metadata(token_mint)`
   - Cache résultat fallback
   - Retour avec source "fallback"

**Gestion d'erreurs :** Try/catch sur chaque provider avec warning "⚠️ {provider} failed"

#### 2. `_get_provider_order() -> List[str]`

**Fonction :** Retourne ordre des providers basé sur configuration et fiabilité

**Ordre par défaut :** `['jupiter', 'coingecko', 'solscan', 'fallback']`

#### 3. `_fetch_from_provider(token_mint: str, provider: str) -> MetadataFetchResult`

**Fonction :** Router vers méthodes spécifiques par provider

**Mapping :**
- `'jupiter'` → `_fetch_from_jupiter()`
- `'coingecko'` → `_fetch_from_coingecko()`
- `'solscan'` → `_fetch_from_solscan()`
- `'fallback'` → `_fetch_from_fallback()`
- Autre → erreur "Unknown provider"

### Implémentations par provider

#### 4. `_fetch_from_jupiter(token_mint: str) -> MetadataFetchResult`

**Fonction :** Récupération depuis Jupiter API

**Requête :**
- **URL :** `https://token.jup.ag/all`
- **Méthode :** GET
- **Timeout :** 10 secondes

**Processus :**
1. Requête endpoint `/all` (liste complète tokens)
2. Parcours réponse JSON pour trouver `token_data.mint == token_mint`
3. Si trouvé → création objet `Token` avec :
   ```python
   Token(
       address=token_mint,
       symbol=token_data.get('symbol', 'UNKNOWN'),
       name=token_data.get('name', 'Unknown'),
       decimals=token_data.get('decimals', 9),
       logo_uri=token_data.get('logoURI'),
       metadata_source='jupiter'
   )
   ```
4. Retour `MetadataFetchResult` avec `token_data` complet en metadata

**Erreurs :** "Token not found in Jupiter" si mint non trouvé, "Jupiter API error" pour exceptions

#### 5. `_fetch_from_coingecko(token_mint: str) -> MetadataFetchResult`

**Fonction :** Récupération depuis CoinGecko API

**Processus :**
1. **Mapping mint → CoinGecko ID :**
   - Appel `_get_coingecko_id(token_mint)`
   - Si pas de mapping → retour erreur "No CoinGecko mapping"

2. **Requête API :**
   - **URL :** `https://api.coingecko.com/api/v3/coins/{coingecko_id}`
   - **Timeout :** 10 secondes

3. **Création Token avec données étendues :**
   ```python
   Token(
       address=token_mint,
       symbol=data.get('symbol', '').upper(),
       name=data.get('name', 'Unknown'),
       decimals=9,  # Défaut Solana
       logo_uri=data.get('image', {}).get('small'),
       coingecko_id=coingecko_id,
       market_cap=data.get('market_data', {}).get('market_cap', {}).get('usd'),
       volume_24h=data.get('market_data', {}).get('total_volume', {}).get('usd'),
       price_change_24h=data.get('market_data', {}).get('price_change_percentage_24h'),
       metadata_source='coingecko'
   )
   ```

#### 6. `_fetch_from_solscan(token_mint: str) -> MetadataFetchResult`

**Fonction :** Récupération depuis Solscan API

**Requête :**
- **URL :** `https://public-api.solscan.io/token/meta`
- **Paramètres :** `{'tokenAddress': token_mint}`
- **Timeout :** 10 secondes

**Création Token :**
```python
Token(
    address=token_mint,
    symbol=data.get('symbol', 'UNKNOWN'),
    name=data.get('name', 'Unknown'),
    decimals=data.get('decimals', 9),
    logo_uri=data.get('icon'),
    metadata_source='solscan'
)
```

#### 7. `_fetch_from_fallback(token_mint: str) -> MetadataFetchResult`

**Fonction :** Récupération depuis Solana Labs token list

**Requête :**
- **URL :** `https://raw.githubusercontent.com/solana-labs/token-list/main/src/tokens/solana.tokenlist.json`
- **Timeout :** 15 secondes

**Processus :**
1. Téléchargement token list officielle
2. Parcours `token_list.get('tokens', [])` 
3. Recherche `token_data.get('address') == token_mint`
4. Si trouvé → création Token avec source 'token_list'

#### 8. `_generate_fallback_metadata(token_mint: str) -> Token`

**Fonction :** Génère métadonnées fallback si tous providers échouent

**Génération automatique :**
```python
symbol = f"TOKEN_{token_mint[:6]}"    # Ex: "TOKEN_So1111"
name = f"Token {token_mint[:8]}"      # Ex: "Token So111111"

Token(
    address=token_mint,
    symbol=symbol,
    name=name,
    decimals=9,
    metadata_source='generated'
)
```

#### 9. `_get_coingecko_id(token_mint: str) -> Optional[str]`

**Fonction :** Mapping des mints Solana vers IDs CoinGecko

**Mapping défini :**
```python
{
    "So11111111111111111111111111111111111111112": "solana",          # SOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "usd-coin",     # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "tether",       # USDT
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": "bonk",         # BONK
    "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmM2yM": "pepe"          # PEPE
}
```

### Fonctionnalités avancées

#### 10. `fetch_bulk_metadata(token_mints: List[str], batch_size: int = 50) -> List[MetadataFetchResult]`

**Fonction :** Récupération en lot avec rate limiting

**Processus :**
1. Division liste en batches de `batch_size` (défaut 50)
2. Pour chaque batch :
   - Appel `fetch_metadata()` pour chaque mint
   - Collecte résultats
   - Sleep 0.1s entre batches (rate limiting)
3. Retour liste complète `MetadataFetchResult`

#### 11. `update_price_data(token_mint: str, price_usd: float, source: str = "unknown") -> bool`

**Fonction :** Met à jour données de prix dans caches

**Processus :**
1. Récupération token actuel via `metadata_cache.get_token_metadata()`
2. Si trouvé :
   - Appel `token.update_price(price_usd, source)`
   - Re-cache token mis à jour
   - Cache prix séparément dans `price_cache` :
     ```python
     price_cache.set(
         f"price:{token_mint}",
         {
             'price': price_usd, 
             'source': source, 
             'timestamp': get_current_timestamp()
         },
         ttl=300  # 5 minutes
     )
     ```

#### 12. `enrich_token_data(token: Token) -> Token`

**Fonction :** Enrichit token avec données additionnelles

**Processus d'enrichissement :**
1. **Données marché :** Si `token.coingecko_id` existe
   - Appel `_fetch_market_data(token.coingecko_id)`
   - Mise à jour `market_cap`, `volume_24h`, `price_change_24h`

2. **Données sociales :** 
   - Appel `_fetch_social_data(token.address)`
   - Si données trouvées → `metadata_source = 'enriched'`

#### 13. `_fetch_market_data(coingecko_id: str) -> Optional[Dict[str, Any]]`

**Fonction :** Récupère données marché depuis CoinGecko

**Requête :**
- **URL :** `https://api.coingecko.com/api/v3/coins/{coingecko_id}`
- **Timeout :** 10 secondes

**Extraction données :**
```python
{
    'market_cap': market_data.get('market_cap', {}).get('usd'),
    'volume_24h': market_data.get('total_volume', {}).get('usd'), 
    'price_change_24h': market_data.get('price_change_percentage_24h')
}
```

#### 14. `_fetch_social_data(token_mint: str) -> Optional[Dict[str, Any]]`

**Fonction :** Récupère données réseaux sociaux

**Implémentation actuelle :** Placeholder retournant `None`

### Validation et qualité

#### 15. `validate_token_metadata(token: Token) -> Dict[str, Any]`

**Fonction :** Valide métadonnées de token

**Validations effectuées :**

**Issues (bloquantes) :**
- **Symbole :** Vide ou > 10 caractères
- **Nom :** Vide ou > 100 caractères  
- **Decimales :** Pas dans range 0-18

**Warnings (non-bloquants) :**
- **Logo URI :** Ne commence pas par http:// ou https://
- **Prix USD :** < 0 ou > 1,000,000 (suspect)

**Structure retour :**
```python
{
    'valid': bool,           # True si aucune issue
    'issues': List[str],     # Problèmes bloquants
    'warnings': List[str]    # Avertissements
}
```

### Monitoring et statistiques

#### 16. `get_metadata_stats() -> Dict[str, Any]`

**Fonction :** Statistiques du système de métadonnées

**Structure retour :**
```python
{
    'cache_stats': dict,         # Stats du cache métadonnées
    'price_cache_stats': dict,   # Stats du cache prix
    'providers': List[str],      # Liste des providers disponibles
    'fallback_enabled': bool     # Fallback activé
}
```

#### 17. `cleanup_metadata_cache() -> int`

**Fonction :** Nettoyage cache expiré

**Action :** Appel `self.metadata_cache.cleanup_expired()`
**Retour :** Nombre d'entrées nettoyées

## Instances et fonctions globales

### Instance globale
```python
metadata_fetcher = TokenMetadataFetcher()
```

### Fonctions de convenance

#### `fetch_token_metadata(token_mint: str, force_refresh: bool = False) -> MetadataFetchResult`
**Wrapper :** `metadata_fetcher.fetch_metadata(token_mint, force_refresh)`

#### `fetch_bulk_metadata(token_mints: List[str]) -> List[MetadataFetchResult]`
**Wrapper :** `metadata_fetcher.fetch_bulk_metadata(token_mints)`

#### `update_token_price(token_mint: str, price_usd: float) -> bool`
**Wrapper :** `metadata_fetcher.update_price_data(token_mint, price_usd)`

## Modèle Token étendu (inféré)

```python
class Token:
    def __init__(self, address: str, **kwargs):
        # Attributs de base
        self.address: str = address
        self.symbol: str = kwargs.get('symbol', 'UNKNOWN')
        self.name: str = kwargs.get('name', 'Unknown Token')
        self.decimals: int = kwargs.get('decimals', 9)
        
        # Métadonnées visuelles
        self.logo_uri: Optional[str] = kwargs.get('logo_uri')
        
        # Identifiants externes
        self.coingecko_id: Optional[str] = kwargs.get('coingecko_id')
        
        # Données de marché
        self.market_cap: Optional[float] = kwargs.get('market_cap')
        self.volume_24h: Optional[float] = kwargs.get('volume_24h')
        self.price_change_24h: Optional[float] = kwargs.get('price_change_24h')
        self.price_usd: Optional[float] = kwargs.get('price_usd')
        
        # Métadonnées système
        self.metadata_source: str = kwargs.get('metadata_source', 'unknown')
        self.last_updated: int = get_current_timestamp()
    
    def update_price(self, price_usd: float, source: str) -> None:
        """Met à jour le prix et la source"""
        self.price_usd = price_usd
        self.metadata_source = f"{self.metadata_source}+{source}"
        self.last_updated = get_current_timestamp()
    
    def to_dict(self) -> Dict[str, Any]:
        """Conversion en dictionnaire pour cache/serialization"""
        return {
            'address': self.address,
            'symbol': self.symbol,
            'name': self.name,
            'decimals': self.decimals,
            'logo_uri': self.logo_uri,
            'coingecko_id': self.coingecko_id,
            'market_cap': self.market_cap,
            'volume_24h': self.volume_24h,
            'price_change_24h': self.price_change_24h,
            'price_usd': self.price_usd,
            'metadata_source': self.metadata_source,
            'last_updated': self.last_updated
        }
```

## Patterns et logiques métier

### Stratégie multi-providers
- **Cascade de fallbacks :** Jupiter → CoinGecko → Solscan → Token List → Generated
- **Spécialisation providers :** Jupiter (complet), CoinGecko (marché), Solscan (basique)
- **Fallback intelligent :** Génération automatique si tous échouent

### Gestion de cache
- **Cache métadonnées :** TTL long (4h) car données stables
- **Cache prix :** TTL court (5min) car données volatiles
- **Force refresh :** Bypass cache si besoin données fraîches

### Rate limiting
- **Limites par provider :** Jupiter 100/min, CoinGecko 50/min, Solscan 30/min
- **Compteurs locaux :** `request_counts` par provider
- **Batch processing :** Sleep entre batches pour respecter limites

### Thread safety
- **Verrou réentrant :** Protection opérations fetch concurrentes
- **Caches thread-safe :** Via TokenCacheManager
- **État partagé :** Compteurs rate limiting protégés

### Qualité des données
- **Validation stricte :** Issues bloquantes vs warnings
- **Enrichissement automatique :** Données marché si CoinGecko ID
- **Source tracking :** Traçabilité origine données

### Robustesse
- **Timeouts configurables :** 10-15s selon provider
- **Gestion erreurs :** Continue sur erreur provider individuel
- **Fallback garanti :** Génération automatique si tout échoue

## Gestion d'erreurs et logging

### Préfixes de logs
- ✅ : Succès/initialisation
- 📦 : Utilisation cache
- 📊 : Résultats/statistiques
- 📈 : Données marché/prix
- ⚠️ : Avertissements providers
- ❌ : Erreurs système

### Stratégies d'erreur
- **Per-provider :** Warning et continue vers suivant
- **Global :** Fallback généré si tous échouent
- **Validation :** Issues/warnings séparées
- **Rate limiting :** Respect silencieux des limites

## Exemple de test (section __main__)

**Token de test :** "So11111111111111111111111111111111111111112" (SOL)

**Tests effectués :**
1. **Fetch simple :** `fetch_token_metadata(test_mint)`
2. **Statistiques :** `metadata_fetcher.get_metadata_stats()`

**Outputs attendus :**
- "📊 Metadata fetch result: True from jupiter"
- "📈 Metadata stats: {...}"

## Points d'extension

1. **Providers additionnels :** Moralis, Alchemy, QuickNode APIs
2. **Cache Redis :** Cache distribué pour scaling
3. **Rate limiting avancé :** Token bucket, exponential backoff
4. **Données sociales :** Twitter, Discord, Telegram integration
5. **Validation avancée :** ML pour détection scams, rugs
6. **Monitoring temps réel :** Webhooks changements métadonnées
7. **Batch optimization :** Providers supportant requêtes multiples
8. **Geo-distributed :** CDN pour assets images tokens