# Documentation Technique : Solana Wallet Monitor - Constantes Globales

## 📋 Métadonnées du Script

- **Nom du fichier** : `constants.py`
- **Version** : 2.0.0 (Codename: BatchOptimized)
- **Auteur** : Solana Wallet Monitor Team
- **Date de création** : 2024-01-15
- **Langage** : Python 3.8+
- **Type** : Module de constantes globales
- **Licence** : MIT

## 🎯 Objectif et Contexte

### But Principal
Ce module centralise toutes les constantes hardcodées et valeurs par défaut pour le système Solana Wallet Monitor. Il sert de référentiel unique pour éviter la duplication de valeurs magiques dans le code.

### Problème Résolu
- Évite la dispersion des constantes dans multiple fichiers
- Facilite la maintenance et modification des paramètres
- Standardise les formats et seuils utilisés
- Centralise la configuration système

## 🏗️ Architecture et Structure

### Organisation des Sections
Le module est divisé en 12 sections principales :

1. **CONSTANTES SOLANA BLOCKCHAIN** - IDs de programmes, formats, seuils
2. **CONSTANTES RÉSEAU ET RPC** - Endpoints, timeouts, rate limiting
3. **CONSTANTES BATCHING ET PERFORMANCE** - Optimisations, seuils de performance
4. **CONSTANTES DÉTECTION ET CLASSIFICATION** - Types de transactions, priorités
5. **CONSTANTES MÉTADONNÉES ET CACHE** - Providers, configuration cache
6. **CONSTANTES BASE DE DONNÉES** - Configuration SQLite, limites
7. **CONSTANTES LOGGING ET MONITORING** - Icônes, formats, niveaux
8. **CONSTANTES VALIDATION ET SÉCURITÉ** - Patterns regex, limites sécurisées
9. **CONSTANTES API ET DASHBOARD** - CORS, limites API, statuts HTTP
10. **CONSTANTES ALERTES ET NOTIFICATIONS** - Types d'alertes, seuils
11. **CONSTANTES TESTS ET DÉVELOPPEMENT** - Configuration test, données mock
12. **HELPERS ET FONCTIONS UTILITAIRES** - Fonctions d'assistance

### Imports et Dépendances
```python
from typing import Dict, List, Tuple
import re
```

## 📊 Constantes Clés par Catégorie

### Blockchain Solana
- **Programme IDs officiels** : Token Program, Associated Token Program, System Program
- **Formats** : Longueurs d'adresses (44 chars), signatures (88 chars), clés publiques (32 bytes)
- **Valeurs économiques** : 1 SOL = 1 milliard de lamports, balance minimum exempt de loyer
- **Seuils de détection** : Changements SOL significatifs (0.001), balances minimales

### Configuration RPC
- **Endpoints par défaut** : 5 RPC publics en fallback (Solana officiel, Ankr, etc.)
- **Timeouts** : 15s standard, 25s batch, 30s critique
- **Rate limiting** : 5 RPS par défaut, 100 RPS QuickNode gratuit
- **Retry logic** : 3 tentatives max, backoff exponentiel

### Optimisation Performance
- **Tailles de batch optimales** : 100 comptes multiples, 20 signatures, 10 transactions
- **Tailles conservatrices** : Versions réduites pour plans gratuits
- **Seuils performance** : Temps de réponse (1s bon, 5s warning, 15s critique)
- **Intervalles adaptatifs** : 30s haute activité à 300s inactivité

### Classification Transactions
- **Types** : BUY, SELL, TRANSFER, SWAP, STAKE, LIQUIDITY
- **Statuts** : SUCCESS, FAILED, PENDING, TIMEOUT
- **Priorités de scan** : 0 (inactif) à 5 (jamais scanné)
- **Seuils montants** : Différenciés par nombre de décimales du token

## 🔧 Fonctions Utilitaires Intégrées

### Formatage d'Affichage
- `format_wallet_address()` : Tronque les adresses (8 chars début/fin)
- `format_token_mint()` : Formate les mints de tokens (6 chars)
- `format_signature()` : Raccourcit les signatures (16 chars)

### Validation
- `validate_solana_address()` : Regex Base58, 44 caractères
- `validate_solana_signature()` : Regex Base58, 88 caractères
- Patterns prédéfinis pour symboles tokens, cycle IDs

### Génération Fallback
- `get_fallback_token_symbol()` : "TOKEN_ABC123" depuis mint
- `get_fallback_token_name()` : "Token ABC123" depuis mint
- `is_large_token_amount()` : Détermine si montant significatif

### Analyse Performance
- `get_performance_status()` : Évalue métriques (good/warning/critical)
- `get_adaptive_interval()` : Retourne intervalle selon activité
- `get_scan_priority_name()` : Convertit niveau en nom lisible

## 🛡️ Sécurité et Validation

### Patterns de Validation
- **Adresses Solana** : `^[1-9A-HJ-NP-Za-km-z]{44}$`
- **Signatures** : `^[1-9A-HJ-NP-Za-km-z]{88}$`
- **Symboles tokens** : `^[A-Z][A-Z0-9_]{1,10}$`

### Limites de Sécurité
- 1000 wallets max par instance
- 50000 tokens max par wallet
- 10000 transactions max par scan
- 2048 MB RAM maximum

### Filtres de Sécurité
- Blacklists pour mints malicieux
- Program IDs suspects bloqués
- Patterns de détection (honeypot, scam, rug)

## 📈 Configuration Performance

### Cache Intelligent
- **Métadonnées tokens** : TTL 1h, 10K entrées max
- **Stats wallets** : TTL 5min, 1K entrées max
- **Réponses RPC** : TTL 1min, 5K entrées max
- Nettoyage automatique par intervalles

### Base de Données
- **SQLite optimisé** : Mode WAL, cache 64MB, timeout 30s
- **Index critiques** : Transactions par wallet/temps, comptes par wallet
- **Nettoyage automatique** : 30 jours transactions, 7 jours historique

### Providers Métadonnées
- **Jupiter API** : Token list principale, cache 1h
- **Solana Token List** : Liste officielle, cache 2h
- Fallback automatique et retry configurable

## 🚨 Système d'Alertes

### Types d'Alertes
- Nouvelles grosses transactions
- Nouveaux tokens découverts  
- Activité élevée wallet
- Erreurs système et dégradation performance

### Seuils Configurés
- **Transaction importante** : 10 SOL ou 100K tokens
- **Haute activité** : 50 tx/heure
- **Dégradation critique** : 50% de baisse performance

## 🧪 Support Tests et Développement

### Configuration Test
- Réponses RPC mockées avec délai 100ms
- Wallets et tokens de test prédéfinis
- Données d'exemple complètes (transactions, tokens)

### Données Mock
- Transaction exemple avec signature, slot, timing
- Token exemple (USDC) avec métadonnées complètes
- Structure standardisée pour tests reproductibles

## 📊 Monitoring et Logging

### Système d'Icônes
- 30+ emojis pour classification visuelle des logs
- Catégories : états, activités, performance, système, résultats
- Formats standardisés pour cycles, découvertes, changements

### Niveaux Personnalisés
- DISCOVERY (25) : Entre INFO et WARNING
- TRANSACTION (25) : Événements transactionnels  
- PERFORMANCE (35) : Entre WARNING et ERROR
- BATCH (15) : Entre DEBUG et INFO

## 🔄 Export et Utilisation

### Constantes Principales Exportées
Les constantes les plus utilisées sont exposées via `__all__` :
- IDs programmes Solana et valeurs blockchain
- Configuration RPC et retry
- Tailles de batch et seuils performance
- Types transactions et priorités scan
- Fonctions helper principales

### Pattern d'Utilisation
```python
from constants import (
    LAMPORTS_PER_SOL,
    DEFAULT_RPC_ENDPOINTS, 
    OPTIMAL_BATCH_SIZES,
    format_wallet_address,
    validate_solana_address
)
```

## 🎯 Points d'Attention Critiques

### Performance
- Tailles de batch adaptées selon plan RPC (gratuit vs payant)
- Intervalles adaptatifs selon activité détectée
- Cache intelligent pour éviter requêtes redondantes

### Sécurité
- Validation stricte des entrées utilisateur
- Limites pour prévenir abus ressources
- Blacklists tokens/programmes malicieux

### Maintenance
- Centralisation facilite mise à jour globale
- Versioning et métadonnées intégrées
- Configuration test séparée pour développement

Cette documentation permet de comprendre intégralement la logique, structure et utilisation du module sans accès au code source.