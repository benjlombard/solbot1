# Solana Wallet Monitor - Dashboard API Routes

## Vue d'ensemble

Le module `dashboard_routes.py` implémente l'interface API principale du dashboard pour la visualisation des données en temps réel du Solana Wallet Monitor. Il fournit une API REST complète avec système de cache pour l'affichage des statistiques, wallets, tokens et transactions.

## Architecture et Configuration

### Blueprint Flask
- **Nom du blueprint** : `dashboard_bp`
- **Préfixe URL** : `/api/dashboard`
- **Template principal** : `dashboard.html`

### Système de Cache
**Variables globales** :
- `_dashboard_cache` : Dictionnaire de stockage des données
- `_cache_expiry` : Dictionnaire des timestamps d'expiration
- `CACHE_DURATION` : 30 secondes (durée par défaut)

**Fonctions de gestion** :
- `cache_result(key, data, duration)` : Met en cache un résultat
- `get_cached_result(key)` : Récupère données si cache valide
- `clear_expired_cache()` : Nettoie automatiquement le cache expiré

### Gestion Base de Données
- `get_db_connection()` : Récupère connexion via database manager
- Gestion d'erreurs avec logging automatique
- Utilisation de context managers (`with` statements)

## Routes Principales du Dashboard

### 1. `/` - Dashboard Home
**Méthode** : GET  
**Objectif** : Affichage de la page principale du dashboard  
**Retour** : Template HTML `dashboard.html` ou erreur 500 si template manquant

### 2. `/data` - Données principales (VERSION MULTI-WALLETS)
**Méthode** : GET  
**Cache** : 60 secondes  
**Objectif** : Fournit toutes les données essentielles du dashboard

#### Statistiques Générales
- `total_token_accounts` : Comptes de tokens actifs
- `total_unique_tokens` : Tokens uniques découverts (via transactions)
- `balance_changes_1h` : Changements de balance dernière heure
- `large_transactions_24h` : Grosses transactions 24h
- `last_scan_time` : Timestamp du dernier scan
- `total_wallets` : Nombre de wallets monitorés

#### Tokens les Plus Actifs (24h)
**Requête complexe** avec regroupement par `(token_mint, token_symbol, wallet_address)` :
- Comptage transactions par token
- Calcul totaux bought/sold et positions nettes
- Prix moyen et volume SOL total
- Score d'activité : `min(100, (tx_count * 10) + (sol_volume * 5))`
- Formatage des adresses courtes
- Tri par comptage transactions DESC, puis dernière activité DESC
- **Limite** : 20 tokens max, affichage principal = top 8

#### Nouveaux Tokens (GEMS)
**Critères de détection** :
- Découverts il y a moins de 2h (`hours_ago < 2`)
- Au moins 2 transactions (`transaction_count >= 2`)
- Classification confiance : 'high' si ≥5 tx, sinon 'medium'
- **Limite** : 5 gems max

#### Alertes Volume Élevé
**Critères** :
- Volume SOL > 1.0 sur 24h
- Niveau d'alerte : 'critical' si >10 SOL, sinon 'warning'
- **Limite** : 5 alertes max

#### Métriques Wallets
**Calculs de répartition** :
- High priority : `priority_score >= 4.0`
- Medium priority : `2.0 <= priority_score < 4.0`
- Low priority : `priority_score < 2.0`
- Recently scanned : scannés dans les 5 dernières minutes
- Priorité moyenne globale

#### Métriques Performance (24h)
- Nombre total de scans
- Durée moyenne des scans
- Total découvertes de comptes
- Score d'efficacité moyen
- Scans par heure calculés

**Structure retour** :
```json
{
  "success": true,
  "data": {
    "timestamp": unix_timestamp,
    "stats": {...},
    "wallet_metrics": {...},
    "performance_metrics": {...},
    "top_tokens": [...],
    "new_gems": [...],
    "volume_alerts": [...],
    "active_tokens_list": [...]
  }
}
```

### 3. `/wallet-overview` - Vue d'ensemble wallets
**Méthode** : GET  
**Cache** : 45 secondes

#### Données par wallet
**Requête JOIN complexe** calculant :
- Informations de base : priorité, derniers scans, activité
- Comptes tokens : total et prioritaires (`scan_priority >= 3`)
- Transactions 24h : globales et tokens uniquement
- Statuts calculés :
  - `scan_status` : "recent" (≤60s), "normal" (≤300s), "overdue" (>300s)
  - `priority_category` : "high" (≥4.0), "medium" (≥2.0), "low" (<2.0)
  - `activity_level` : "high" (>10 tx/24h), "medium" (>2), "low" (≤2)

#### Résumé global
- Total wallets, high priority count, overdue scans
- Wallets actifs (activity_level != 'low')
- Priorité moyenne calculée

### 4. `/recent-activity` - Activité récente
**Méthode** : GET  
**Paramètres** : `hours` (défaut: 24), `limit` (défaut: 50, max: 200)  
**Cache** : 30 secondes (clé incluant paramètres)

#### Transactions récentes
**Champs extraits** :
- Signature, wallet, token (mint/symbol/name)
- Type transaction, montants token et SOL
- Prix par token, détection delay
- Classification `is_large_token_amount`
- Calcul `hours_ago` et valeur USD si prix disponible

#### Découvertes récentes
**Source** : Table `token_accounts` + JOIN transactions pour symbole
- Token mint, wallet découvreur
- Balance initiale, timestamp découverte
- Symbole généré si absent : `TOKEN_{mint[:6]}`

#### Fusion et tri
- Combinaison transactions + découvertes
- Tri par timestamp DESC (`block_time` ou `discovered_at`)
- Application limite finale

### 5. `/performance-metrics` - Métriques performance
**Méthode** : GET  
**Paramètres** : `hours` (défaut: 24)  
**Cache** : 120 secondes

#### Métriques système globales
- Statistiques scans : total, durée (moy/min/max)
- Total découvertes et comptes scannés
- Efficacité moyenne, scans par heure
- Découvertes par scan calculées

#### Métriques par wallet
**Top 10 wallets** par efficacité :
- Nombre scans, durée moyenne
- Découvertes totales, efficacité moyenne

#### Tendances horaires  
**Regroupement par heure** (format strftime '%H') :
- Scans par heure, durée moyenne
- Découvertes, normalisation par durée totale

#### Métriques RPC (optionnelles)
- Requêtes RPC moyennes par scan
- Total requêtes RPC, efficacité RPC calculée

## Routes de Recherche et Filtrage

### 6. `/search` - Recherche globale
**Méthode** : GET  
**Paramètres** : 
- `q` : Query (min 3 caractères)
- `type` : 'all'|'wallets'|'tokens'|'transactions' (défaut: 'all')
- `limit` : max 100

#### Recherche Wallets
- Pattern LIKE sur `wallet_address`
- Tri par `priority_score DESC`
- Type de match : 'wallet_address'

#### Recherche Tokens
- Recherche sur `token_symbol`, `token_name`, `token_mint`
- Regroupement par mint+wallet avec comptage transactions
- Détermination type match : 'symbol', 'name', ou 'mint'
- Tri par nombre transactions DESC puis activité DESC

#### Recherche Transactions
- Recherche sur `signature` et `token_symbol`
- Tri par `block_time DESC`
- Type match : 'signature' ou 'token'

**Structure résultats** :
```json
{
  "query": "search_term",
  "data_type": "all",
  "total_results": count,
  "results": {
    "wallets": [...],
    "tokens": [...], 
    "transactions": [...]
  }
}
```

## Routes de Détail

### 7. `/wallet/<wallet_address>` - Détail wallet
**Méthode** : GET  
**Cache** : 60 secondes  
**Validation** : Adresse 44 caractères obligatoire

#### Informations de base
**Source** : `wallet_priorities`
- Priority score, scans, activité, durée moyenne
- Classification automatique priority_category

#### Statistiques comptes tokens
- Total, actifs (`balance > 0`), prioritaires (`scan_priority >= 3`)
- Priorité moyenne des comptes

#### Statistiques transactions
- Comptages par type (total, token, large, buy/sell)
- Volume SOL total, ratio buy/sell calculé
- Transactions 24h, dernière transaction

#### Top tokens du wallet
**Requête JOIN complexe** :
- Balance, décimales, priorité scan
- Symbol/name via sous-requêtes FIRST_VALUE
- Comptage transactions par token
- Calcul `display_balance` selon décimales
- Tri par balance DESC puis priorité DESC
- **Limite** : 20 tokens

#### Activité récente
**10 dernières transactions token** :
- Détails transaction avec formatage
- Calcul `hours_ago` pour affichage

### 8. `/token/<token_mint>` - Détail token
**Méthode** : GET  
**Cache** : 90 secondes  
**Validation** : Mint 44 caractères obligatoire

#### Informations de base
**Récupération symbol/name** via FIRST_VALUE sur transactions récentes
**Fallback** : `TOKEN_{mint[:6]}` si données manquantes

#### Statistiques globales
- Nombre holders uniques (DISTINCT wallet_address)
- Total transactions, volumes bought/sold
- Prix moyen (WHERE price_per_token > 0)
- Première découverte, dernière activité
- Calculs net_flow et durées depuis événements

#### Répartition par wallet
**Top 15 wallets** par nombre transactions :
- Totaux bought/sold par wallet
- Position nette calculée (`bought - sold`)
- Balance actuelle via JOIN token_accounts
- Heures depuis dernière transaction

#### Activité récente
**15 dernières transactions** :
- Tous détails transaction par wallet
- Calcul `hours_ago`, formatage standard

## Routes Utilitaires

### 9. `/health` - Health check
**Test connexion DB** avec requête `SELECT 1`
- Statut : 'healthy' si DB OK, sinon 'degraded'
- Taille cache actuelle, timestamp

### 10. `/cache/clear` - Vider cache
**Méthode** : POST  
**Action** : Vide `_dashboard_cache` et `_cache_expiry`
**Retour** : Nombre d'items supprimés

### 11. `/stats` - Statistiques dashboard
**Métriques d'usage** :
- Nombre entrées cache (après nettoyage)
- Placeholders pour hit ratio, connexions actives, temps réponse

## Gestion des Erreurs

### Handlers personnalisés
- **404** : "Dashboard endpoint not found"
- **500** : "Internal server error in dashboard" avec logging

### Stratégie générale
- Try/catch sur toutes les routes principales
- Logging détaillé des erreurs avec traceback
- Retours JSON standardisés via `create_error_response`
- Codes HTTP appropriés (400 pour validation, 404 pour not found, 500 pour erreurs serveur)

## Importation et Dépendances

### Modules Core
- `models.*` : WalletPriority, Token, Transaction, schémas
- `core.database` : Database manager
- `core.config` : Configuration globale
- `utils.*` : Formatters et helpers

### Fallbacks gracieux
```python
try:
    # Imports normaux
except ImportError as e:
    # Fallbacks pour développement
    def create_success_response(msg, data=None): 
        return {'success': True, 'message': msg, 'data': data}
```

## Initialisation et Export

### Fonction d'initialisation
```python
def init_dashboard_routes(app):
    """Enregistre le blueprint sur l'application Flask"""
    app.register_blueprint(dashboard_bp)
```

### Nettoyage automatique
```python
def cleanup_dashboard_cache():
    """Nettoyage périodique du cache expiré"""
    clear_expired_cache()
```

### Exports publics
```python
__all__ = [
    'dashboard_bp',
    'init_dashboard_routes', 
    'cleanup_dashboard_cache'
]
```

## Patterns et Techniques Utilisées

### 1. Caching Strategy
- Cache par endpoint avec durées différenciées (30s à 120s)
- Clés de cache incluant paramètres pour requêtes paramétrées
- Nettoyage automatique des entrées expirées
- Invalidation manuelle via endpoint `/cache/clear`

### 2. Formatage des données
- Adresses courtes : `f"{addr[:6]}...{addr[-6:]}"`
- Timestamps relatifs : calcul `hours_ago`, `days_since`
- Classification automatique : priority_category, scan_status, activity_level
- Arrondis précision : token amounts, prix, scores

### 3. Requêtes SQL optimisées
- Sous-requêtes pour statistiques associées
- JOINs LEFT pour données optionnelles
- Regroupements avec comptages et moyennes
- CASE WHEN pour classifications conditionnelles
- FIRST_VALUE OVER pour récupération dernières valeurs

### 4. Gestion d'erreurs robuste
- Validation paramètres en amont
- Try/catch granulaire par section
- Logging contextuel avec traceback
- Retours JSON cohérents avec codes HTTP appropriés

### 5. API Response Pattern
Toutes les réponses suivent le format :
```json
{
  "success": boolean,
  "message": string,
  "data": object,
  "errors": array (si applicable)
}
```

Cette architecture fournit une API dashboard complète, performante et robuste pour la visualisation temps réel des données du Solana Wallet Monitor, avec une gestion intelligente du cache et des requêtes optimisées pour supporter le monitoring multi-wallets à grande échelle.