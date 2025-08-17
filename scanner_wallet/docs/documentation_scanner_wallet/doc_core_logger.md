# Documentation - Système de Logging Avancé Solana

## Vue d'ensemble
**Fichier**: `core/logger.py`  
**Type**: Système de logging centralisé avancé  
**Objectif**: Logging intelligent avec contexte, rotation, formatage spécialisé et métriques pour le Solana Wallet Monitor

## Architecture générale

### Système multi-couches
- **Niveaux personnalisés** pour domaines métier spécifiques
- **Formatters spécialisés** (couleur, contexte, JSON, icônes)
- **Handlers avancés** (rotation intelligente, métriques, intégrations)
- **Filtres contextuels** (rate limiting, contexte thread-local)
- **Logger principal singleton** avec configuration flexible

### Fallbacks et imports
- Imports avec fallbacks si modules utils indisponibles
- Constantes et icônes par défaut intégrées
- Fonctions de formatage basiques en fallback

## Niveaux de log personnalisés

### Niveaux métier ajoutés
```python
CUSTOM_LOG_LEVELS = {
    'DISCOVERY': 25,     # Entre INFO et WARNING - découvertes de tokens
    'TRANSACTION': 25,   # Entre INFO et WARNING - transactions importantes
    'PERFORMANCE': 35,   # Entre WARNING et ERROR - métriques performance
    'BATCH': 15         # Entre DEBUG et INFO - opérations de batch
}
```

### Ajout automatique au système logging
- Intégration native avec `logging.addLevelName()`
- Utilisables comme niveaux standard dans toute l'application

## Formatters personnalisés

### `ColoredFormatter(logging.Formatter)`
**Objectif**: Formatage avec codes couleur ANSI pour console

**Couleurs par niveau**:
```python
COLORS = {
    'DEBUG': '\033[36m',      # Cyan
    'BATCH': '\033[94m',      # Bleu clair
    'INFO': '\033[97m',       # Blanc
    'DISCOVERY': '\033[92m',  # Vert clair
    'TRANSACTION': '\033[93m', # Jaune
    'WARNING': '\033[93m',    # Jaune
    'ERROR': '\033[91m',      # Rouge
    'CRITICAL': '\033[95m',   # Magenta
    'PERFORMANCE': '\033[35m' # Violet
}
```

**Fonctionnalités**:
- **Auto-détection** support couleur terminal
- **Variables d'environnement** respectées (`TERM=dumb`, `NO_COLOR`)
- **Formatage niveau et logger** avec couleurs distinctes
- **Codes ANSI**: Couleur + gras + reset automatique

### `ContextFormatter(logging.Formatter)`
**Objectif**: Enrichissement automatique avec contexte métier

**Contexte extrait automatiquement**:
- `wallet_address` → `W:4Ddrf...Er9nNh`
- `cycle_id` → `C:123` (extrait numéro)
- `scan_id` → `S:abc123` (6 derniers chars)
- `batch_id` → `B:batch_456`

**Format final**: `[W:4Ddrf C:123 S:abc123] Message de log`

### `JSONFormatter(logging.Formatter)`
**Objectif**: Format JSON structuré pour systèmes de monitoring

**Structure de base**:
```python
{
    'timestamp': float,        # Unix timestamp
    'level': str,             # Niveau de log
    'logger': str,            # Nom du logger
    'message': str,           # Message formaté
    'module': str,            # Module source
    'function': str,          # Fonction source
    'line': int               # Numéro de ligne
}
```

**Enrichissements automatiques**:
- **Contexte métier**: `wallet_address`, `cycle_id`, `scan_id`, `batch_id`
- **Contexte RPC**: `rpc_method`, `token_mint`, `signature`
- **Exceptions**: Stack trace formatée si présente
- **Métriques**: Données numériques si attachées au record

**Sérialisation robuste**: Fallback gracieux si JSON échoue

### `IconFormatter(logging.Formatter)`
**Objectif**: Ajout d'icônes visuelles contextuelles

**Icônes par niveau**:
- DEBUG: 🔍, BATCH: 📦, INFO: ℹ️, DISCOVERY: 🆕
- TRANSACTION: 💰, WARNING: ⚠️, ERROR: ❌, CRITICAL: 🚨

**Icônes contextuelles** (selon contenu message):
- RPC: 🔌, Wallet: 👛, Token: 🪙, Database: 💾
- Cache: 🗄️, Fast: ⚡, Slow: 🐌

**Ajout au record**: `record.icon` disponible pour autres formatters

## Handlers personnalisés

### `SmartRotatingFileHandler(RotatingFileHandler)`
**Objectif**: Rotation intelligente par taille + temps

**Fonctionnalités avancées**:
- **Rotation par taille**: Hérite du comportement standard
- **Nettoyage par âge**: Suppression automatique fichiers anciens
- **Nettoyage périodique**: Toutes les heures (configurable)
- **Gestion d'erreurs**: Pas d'interruption logging si nettoyage échoue

**Paramètres**:
```python
SmartRotatingFileHandler(
    filename=str,
    maxBytes=int,           # Taille max avant rotation
    backupCount=int,        # Nombre de backups à conserver
    max_age_days=int       # Âge max des fichiers (nouveauté)
)
```

### `PerformanceHandler(logging.Handler)`
**Objectif**: Collecte et analyse métriques de performance

**Fonctionnalités**:
- **Filtrage spécialisé**: Ne traite que les logs `PERFORMANCE`
- **Extraction métriques**: Parser automatique des métriques dans les messages
- **Buffer circulaire**: Garde les 100 dernières métriques
- **Callback externe**: Notification temps réel des métriques

**Métriques extraites automatiquement**:
```python
patterns = {
    'rps': r'RPS:\s*(\d+(?:\.\d+)?)',
    'success_rate': r'Succès:\s*(\d+(?:\.\d+)?)%',
    'duration': r'(\d+(?:\.\d+)?)s',
    'count': r'(\d+)\s+items',
    'efficiency': r'efficacité:\s*(\d+(?:\.\d+)?)'
}
```

**API de récupération**: `get_recent_metrics(count=10)`

## Filtres personnalisés

### `ContextFilter(logging.Filter)`
**Objectif**: Injection automatique de contexte thread-local et global

**Contexte automatique**:
- **Thread info**: `thread_name`, `process_id`
- **Thread-local**: Contexte spécifique au thread courant
- **Global**: Contexte fourni par callback externe

**API de gestion contexte**:
- `set_context(**kwargs)`: Définit contexte thread
- `clear_context()`: Efface contexte thread
- Support `context_provider` callable pour contexte global

### `LevelRangeFilter(logging.Filter)`
**Objectif**: Filtrage par plage de niveaux

**Usage**: Permettre seulement INFO à ERROR, exclure DEBUG et CRITICAL
```python
LevelRangeFilter(min_level=logging.INFO, max_level=logging.ERROR)
```

### `RateLimitFilter(logging.Filter)`
**Objectif**: Anti-spam pour messages répétitifs

**Fonctionnalités**:
- **Limite par minute**: Configurable (défaut: 60/min)
- **Clé de groupage**: `niveau:message[100 chars]`
- **Fenêtre glissante**: Messages comptés sur 60 secondes
- **Nettoyage automatique**: Toutes les 5 minutes
- **Mémoire optimisée**: Suppression anciennes entrées

**Algorithme**: Timestamp par occurrence, filtrage par fenêtre temporelle

## Logger principal - SolanaWalletLogger

### Singleton thread-safe
```python
class SolanaWalletLogger:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        # Double-checked locking pattern
```

### Initialisation complète
**Paramètres de configuration**:
```python
SolanaWalletLogger(
    log_level="INFO",                    # Niveau de log
    log_file="wallet_monitor.log",       # Fichier principal
    console_output=True,                 # Sortie console
    json_output=False,                   # Fichier JSON séparé
    max_file_size=10*1024*1024,         # 10MB max
    backup_count=5,                      # 5 backups
    max_age_days=7                       # 7 jours rétention
)
```

### Configuration automatique des handlers

#### Handler fichier
- **Type**: `SmartRotatingFileHandler`
- **Formatter**: `ContextFormatter` avec contexte complet
- **Format**: `timestamp - level - [contexte] logger - [fonction:ligne] - message`

#### Handler console
- **Type**: `StreamHandler` vers stdout
- **Formatter**: `ColoredFormatter` + `IconFormatter`
- **Format**: `icône timestamp - level - message`
- **Couleurs**: Auto-détection support terminal

#### Handler JSON (optionnel)
- **Fichier**: `*_json.log` (suffixe automatique)
- **Formatter**: `JSONFormatter`
- **Usage**: Intégration systèmes monitoring (ELK, etc.)

#### Handler performance
- **Type**: `PerformanceHandler`
- **Usage**: Collecte métriques temps réel
- **Buffer**: 100 entrées circulaires

### Configuration des filtres
- **ContextFilter**: Appliqué à tous les handlers
- **RateLimitFilter**: Appliqué sauf aux métriques (120/min)
- **Thread-safety**: Gestion contexte par thread

### API de logging spécialisée

#### Contexte temporaire
```python
with logger.context(wallet_address="4Ddr...", cycle_id="cycle_123"):
    logger.info("Message avec contexte automatique")
```

#### Logs métier spécialisés
```python
# Cycle de monitoring
log_cycle_start(cycle_id, wallet_address=None)
log_cycle_end(cycle_id, duration, **stats)

# Sélection et découverte
log_wallet_selected(wallet_address, priority_score=None)
log_discovery_result(wallet_address, total_accounts, new_accounts)

# Transactions et priorité
log_balance_change(wallet_address, tx_type, amount, symbol, signature=None)
log_priority_update(wallet_address, old_priority, new_priority)

# RPC et performance
log_batch_result(method, count, duration, success=True)
log_rpc_error(method, error, endpoint=None)
log_performance(rps, success_rate, **metrics)
```

#### Chaque méthode spécialisée:
- **Contexte automatique**: Injection transparente
- **Formatage métier**: Templates prédéfinis
- **Niveau approprié**: Utilise niveaux personnalisés
- **Enrichissement**: Métriques et métadonnées automatiques

### Gestion dynamique
```python
# Modification niveau runtime
set_level("DEBUG")

# Gestion handlers
add_custom_handler(handler)
remove_handler(handler_type)

# Statistiques
get_log_stats()          # Dict complet statistiques
get_recent_performance_metrics(count=10)
```

## Fonctions d'initialisation

### `setup_logger(**kwargs) -> SolanaWalletLogger`
**Factory function principale** avec tous paramètres

### `get_logger(name=None) -> logging.Logger`
**Récupération logger enfant** du singleton principal

### Configurations pré-définies

#### `setup_development_logging()`
- Level: DEBUG, Console: Oui, JSON: Non
- Fichier: 5MB max, 3 backups, 3 jours
- Optimisé pour développement local

#### `setup_production_logging()`
- Level: INFO, Console: Non, JSON: Oui
- Fichier: `/var/log/wallet_monitor/production.log`
- 50MB max, 10 backups, 30 jours
- Optimisé pour systèmes de monitoring

#### `setup_testing_logging()`
- Level: WARNING, Console: Non, JSON: Non
- Fichier: 1MB max, 2 backups, 1 jour
- Minimal pour tests automatisés

### `@log_with_context(**context_kwargs)`
**Décorateur automatique** pour contexte de fonction
```python
@log_with_context(component="rpc_client")
def make_rpc_call():
    # Tous les logs auront automatiquement component="rpc_client"
```

## Utilitaires d'analyse et monitoring

### `LogAnalyzer(log_file)`
**Analyseur de logs** pour patterns et problèmes

#### `analyze_error_patterns(last_hours=24)`
**Analyse erreurs et warnings récents**:
```python
{
    'period_hours': 24,
    'total_errors': int,
    'total_warnings': int,
    'error_types': {error_type: count},
    'warning_types': {warning_type: count},
    'top_errors': [(type, count)],      # Top 5
    'top_warnings': [(type, count)]     # Top 5
}
```

#### `get_performance_trends(last_hours=24)`
**Analyse tendances performance**:
```python
{
    'period_hours': 24,
    'data_points': int,
    'avg_rps': float,
    'avg_success_rate': float,
    'max_rps': float,
    'min_rps': float,
    'latest_metrics': [metrics]         # 5 plus récentes
}
```

**Parser automatique**: Extraction RPS et success rate des logs

### `HealthChecker(logger_instance)`
**Vérificateur santé système logging**

#### `check_health() -> Dict`
**Check complet avec tests fonctionnels**:
- **Logger fonctionnel**: Test écriture message
- **Fichier accessible**: Test permissions écriture
- **Handlers opérationnels**: Test individuel chaque handler
- **Utilisation mémoire**: Estimation approximative

**Statuts**: `healthy`, `degraded`, `critical`

#### `get_recommendations() -> List[str]`
**Recommandations automatiques**:
- Problèmes de santé détectés
- Taille fichier log excessive
- Handlers défaillants
- Optimisations possibles

## Intégrations et extensions

### `SlackLogHandler(logging.Handler)`
**Intégration Slack** pour alertes critiques

**Fonctionnalités**:
- **Niveaux configurables**: Minimum ERROR par défaut
- **Formatage riche**: Couleurs selon niveau, champs structurés
- **Contexte métier**: Wallet, module, fonction automatiquement
- **Non-bloquant**: Timeout 5s, pas d'exception si échec
- **Payload Slack**: Format attachments avec couleurs

### `DatabaseLogHandler(logging.Handler)`
**Stockage logs en base de données**

**Fonctionnalités**:
- **Buffer configurable**: 100 logs par défaut avant flush
- **Thread-safe**: Lock sur buffer
- **Auto-création table**: DDL automatique si table manquante
- **Contexte complet**: Tous champs métier stockés
- **Flush intelligent**: Buffer plein ou fermeture handler

**Schema table**:
```sql
CREATE TABLE logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL,
    level TEXT,
    logger_name TEXT,
    message TEXT,
    module TEXT,
    function_name TEXT,
    line_number INTEGER,
    wallet_address TEXT,
    cycle_id TEXT,
    scan_id TEXT,
    signature TEXT,
    token_mint TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

## Constantes et formats

### `LOG_ICONS`
**Icônes par contexte**:
```python
{
    'success': '✅', 'error': '❌', 'warning': '⚠️', 'info': 'ℹ️',
    'debug': '🔍', 'critical': '🚨', 'scan': '🔍', 'discovery': '🆕',
    'transaction': '💰', 'batch': '📦', 'priority': '🎯', 'wallet': '👛',
    'token': '🪙', 'rpc': '🔌', 'database': '💾', 'cache': '🗄️',
    'fast': '⚡', 'slow': '🐌', 'optimization': '🚀', 'monitoring': '📊'
}
```

### `LOG_FORMATS`
**Templates messages métier**:
```python
{
    'cycle_start': "🧠 CYCLE INTELLIGENT #{cycle} - {timestamp}",
    'cycle_end': "✅ CYCLE #{cycle} TERMINÉ - Durée: {duration}s",
    'wallet_selected': "🎯 WALLET SÉLECTIONNÉ: {wallet_short}",
    'discovery_result': "📊 Découverte: {total} comptes ({new} nouveaux)",
    'balance_change': "💰 Balance change: {type} {amount} {symbol}",
    'priority_update': "{icon} Priorité: {old} → {new} ({change:+.2f})",
    'batch_result': "📦 Batch {method}: {count} items en {duration:.2f}s",
    'rpc_error': "❌ Erreur RPC {method}: {error}",
    'performance': "📊 Performance - RPS: {rps:.1f}, Succès: {success_rate:.1f}%"
}
```

## Gestion des instances globales

### Instance par défaut
```python
_default_logger_instance = None

def init_default_logger(**kwargs):
    # Initialise logger global avec paramètres

def get_default_logger() -> SolanaWalletLogger:
    # Lazy initialization du logger global
```

### Pattern d'utilisation recommandé
```python
# Dans un module
from core.logger import get_logger
logger = get_logger(__name__)

# Utilisation avec contexte automatique
logger.info("Message standard")

# Utilisation spécialisée
from core.logger import get_default_logger
main_logger = get_default_logger()
main_logger.log_discovery_result(wallet, 150, 5)
```

## Mode développement et tests

### `if __name__ == "__main__"`
**Suite de tests complète**:
- Test tous niveaux de log (standard + personnalisés)
- Test contexte temporaire avec wallet/cycle
- Test toutes méthodes spécialisées
- Démonstration formatage et couleurs
- Génération fichier test pour vérification

### Tests inclus
```python
# Niveaux standard
test_logger.debug("🔍 Test DEBUG")
test_logger.info("ℹ️ Test INFO")
test_logger.warning("⚠️ Test WARNING")
test_logger.error("❌ Test ERROR") 
test_logger.critical("🚨 Test CRITICAL")

# Contexte
with logger.context(wallet_address="4Ddr...", cycle_id="cycle_123"):
    test_logger.info("Test avec contexte")

# Méthodes spécialisées
logger.log_cycle_start("cycle_123", "4Ddr...")
logger.log_discovery_result("4Ddr...", 150, 5)
logger.log_balance_change("4Ddr...", "buy", 1000.0, "USDC")
logger.log_priority_update("4Ddr...", 2.5, 3.2)
logger.log_batch_result("getMultipleAccounts", 50, 1.23)
logger.log_performance(rps=15.5, success_rate=98.2, batch_efficiency=0.85)
logger.log_cycle_end("cycle_123", 45.6, discoveries=5, transactions=3)
```

Cette documentation couvre l'intégralité du système de logging avancé avec ses formatters, handlers, filtres, analyseurs, intégrations et APIs spécialisées, permettant une compréhension complète sans accès au code source.