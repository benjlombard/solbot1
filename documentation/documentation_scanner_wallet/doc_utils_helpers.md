# Documentation Technique : Solana Wallet Monitor - Utilitaires Générales

## 📋 Métadonnées du Script

- **Nom du fichier** : `utils.py`
- **Type** : Module d'utilitaires générales
- **Langage** : Python 3.8+
- **Paradigme** : Fonctions pures sans état
- **Dépendances** : `base58`, `hashlib`, `secrets`, `uuid`, `decimal`
- **Licence** : Compatible avec le projet principal

## 🎯 Objectif et Contexte

### But Principal
Ce module fournit une collection complète de fonctions utilitaires pures et sans état pour faciliter les opérations communes dans le système Solana Wallet Monitor. Il centralise toute la logique métier réutilisable et les opérations de bas niveau.

### Philosophie de Design
- **Fonctions pures** : Pas d'effets de bord, résultats prévisibles
- **Gestion d'erreur défensive** : Tous les cas d'erreur sont gérés gracieusement
- **Performance optimisée** : Algorithmes efficaces avec complexité maîtrisée
- **Réutilisabilité maximale** : Code générique utilisable dans tout le projet

## 🏗️ Structure et Organisation

### 12 Catégories Fonctionnelles

1. **UTILITAIRES TEMPORELS** - Gestion du temps, timestamps, intervalles
2. **UTILITAIRES MATHÉMATIQUES** - Calculs sécurisés, statistiques, arrondis
3. **UTILITAIRES SOLANA** - Blockchain-specific, validation, conversions
4. **GÉNÉRATION D'IDENTIFIANTS** - UUIDs, hashs, identifiants uniques
5. **COLLECTIONS ET STRUCTURES** - Manipulation de données complexes
6. **VALIDATION ET NETTOYAGE** - Sanitisation, validation, filtrage
7. **PERFORMANCE ET MONITORING** - Mesures, métriques, optimisation
8. **RETRY ET RÉSILIENCE** - Gestion d'erreurs, backoff, robustesse
9. **JSON ET SÉRIALISATION** - Parsing sécurisé, sérialisation
10. **CLASSES UTILITAIRES** - Structures de données avancées
11. **FONCTIONS AVANCÉES** - Traitement par batch, fusion de configs
12. **EXPORT ET API** - Interface publique du module

### Imports et Dépendances
```python
import time, hashlib, secrets, re, json, math, uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union, Tuple, Callable
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
import base58
```

## ⏰ Utilitaires Temporels

### Fonctions de Base
- **`get_current_timestamp()`** : Timestamp Unix actuel (secondes)
- **`get_current_timestamp_ms()`** : Timestamp Unix en millisecondes
- **`calculate_time_since(timestamp)`** : Temps écoulé depuis un point
- **`calculate_time_until(timestamp)`** : Temps restant jusqu'à un point futur

### Fonctions Avancées
- **`is_timestamp_recent(timestamp, threshold=3600)`** : Vérification de récence
- **`get_time_bucket(timestamp, bucket_size_minutes=15)`** : Groupement temporel
- **`sleep_with_jitter(base_seconds, jitter_factor=0.1)`** : Sleep avec randomisation

### Caractéristiques Techniques
- Gestion robuste des valeurs nulles/invalides (retourne 999999 pour "très ancien")
- Valeurs par défaut intelligentes (3600s = 1h pour récence)
- Jitter aléatoire pour éviter la synchronisation des processus
- Protection contre les timestamps négatifs ou corrompus

## 🔢 Utilitaires Mathématiques

### Opérations Sécurisées
- **`safe_divide(num, den, default=0)`** : Division avec protection division par zéro
- **`safe_percentage(part, total, default=0.0)`** : Calcul de pourcentage sécurisé
- **`round_to_precision(value, precision=2)`** : Arrondi avec Decimal pour précision
- **`clamp(value, min_val, max_val)`** : Limitation de valeur dans bornes

### Statistiques et Analyse
- **`calculate_moving_average(values, window_size=5)`** : Moyenne mobile glissante
- **`calculate_percentile(values, percentile)`** : Calcul de percentile avec interpolation linéaire

### Spécificités Techniques
- Utilise `Decimal` avec `ROUND_HALF_UP` pour éviter les erreurs de float
- Gestion intelligente des listes vides et valeurs nulles
- Algorithme de percentile avec interpolation pour valeurs intermédiaires
- Protection contre les overflows et underflows

## ⚡ Utilitaires Solana Blockchain

### Parsing et Conversion
- **`parse_solana_amount(raw_amount, decimals=9)`** : Parse montants avec détection auto format
- **`lamports_to_sol(lamports)`** : Conversion lamports → SOL (÷ 1 milliard)
- **`sol_to_lamports(sol)`** : Conversion SOL → lamports (× 1 milliard)

### Validation Blockchain
- **`validate_wallet_address(address)`** : Validation Base58 + longueur + décodage
- **`validate_signature(signature)`** : Validation signature transaction (64 bytes)
- **`is_native_sol_mint(mint_address)`** : Détection wrapped SOL mint
- **`get_token_program_id(mint_address)`** : Program ID selon type token

### Logique Métier Solana
- Détection intelligente format brut vs. format affiché (seuil 10^(decimals-2))
- Validation complète Base58 avec vérification décodage
- Support futur Token-2022 via `get_token_program_id`
- Constante wrapped SOL : "So11111111111111111111111111111111111111112"

## 🆔 Génération d'Identifiants

### Identifiants Métier
- **`generate_cycle_id(prefix="cycle")`** : Format "cycle_random_timestamp"
- **`generate_scan_id(wallet_address)`** : Format "scan_address8chars_timestamp"
- **`generate_short_hash(data, length=8)`** : Hash SHA256 tronqué

### Identifiants Techniques
- **`generate_uuid()`** : UUID4 standard
- **`create_hash_signature(*args, algorithm="sha256")`** : Signature multi-arguments

### Caractéristiques de Sécurité
- Utilise `secrets.randbelow()` pour randomisation cryptographique
- Fallback automatique vers `secrets.token_hex()` en cas d'erreur
- Support multiple algorithmes hash avec fallback SHA256
- Format prévisible pour logging et debugging

## 📊 Collections et Structures de Données

### Navigation et Extraction
- **`safe_get(dict, key, default=None, key_path=None)`** : Accès sécurisé avec support chemins "data.result.value"
- **`flatten_dict(nested_dict, separator='.', prefix='')`** : Aplatissement dictionnaire imbriqué
- **`merge_dictionaries(*dicts, deep=False)`** : Fusion avec option récursive

### Manipulation de Listes
- **`chunk_list(lst, chunk_size)`** : Division en chunks de taille fixe
- **`deduplicate_list(lst, key_func=None)`** : Déduplication avec ordre préservé
- **`rotate_list(lst, positions)`** : Rotation (positif=droite, négatif=gauche)

### Algorithmes Avancés
- Navigation par chemin avec gestion des types (dict detection)
- Déduplication O(n) avec fonction de clé personnalisable
- Fusion profonde récursive avec détection conflits
- Rotation optimisée avec modulo pour grandes listes

## 🧹 Validation et Nettoyage de Données

### Nettoyage de Texte
- **`clean_string(text, max_length=None, allowed_chars=None)`** : Nettoyage complet
  - Suppression caractères de contrôle (\x00-\x1f, \x7f-\x9f)
  - Normalisation espaces multiples
  - Filtrage par regex personnalisée
  - Troncature intelligente (préserve les mots)

### Validation Numérique
- **`validate_numeric_string(text, numeric_type="float")`** : Types supportés
  - "int" : Entiers uniquement
  - "float" : Nombres décimaux
  - "positive" : Nombres ≥ 0
  - "percentage" : Nombres 0-100

### Sécurisation Système
- **`sanitize_filename(filename)`** : Nom fichier multi-OS
  - Caractères interdits : `<>:"/\|?*`
  - Noms réservés Windows (CON, PRN, AUX, etc.)
  - Limitation 200 caractères avec préservation extension
  - Fallback "unknown_file" pour cas extrêmes

## 📈 Performance et Monitoring

### Mesure d'Exécution
- **`@measure_execution_time`** : Décorateur retournant (résultat, durée)
- **`ExecutionTimer`** : Context manager avec méthodes duration/duration_ms
- **`calculate_rate_per_second(count, duration)`** : Calcul taux avec protection division par zéro

### Métriques de Performance
- **`calculate_efficiency_score(successes, total, time_taken, optimal_time=None)`**
  - Score 0-1 basé sur taux de succès
  - Prise en compte temps optimal si fourni
  - Moyenne pondérée success_rate + time_efficiency

### Usage Pattern
```python
with ExecutionTimer("operation") as timer:
    # Code à mesurer
    pass
print(f"Durée: {timer.get_duration_ms()}ms")
```

## 🔄 Retry et Résilience

### Backoff Algorithms
- **`exponential_backoff(attempt, base_delay=1.0, max_delay=60.0, jitter=True)`**
  - Formule : min(base_delay * 2^attempt, max_delay)
  - Jitter ±25% pour éviter synchronisation
  - Protection minimum 0.1s

### Logique de Retry
- **`should_retry(exception, attempt, max_attempts, retryable_exceptions=None)`**
  - Types retryables par défaut : ConnectionError, TimeoutError
  - Support types personnalisés via tuple
  - Limite stricte du nombre de tentatives

### Exécution Robuste
- **`retry_with_backoff(func, *args, max_attempts=3, **kwargs)`**
  - Combine backoff + should_retry
  - Préserve la dernière exception
  - Support arguments positionnels et nommés

## 🗄️ Classes Utilitaires Avancées

### RateLimiter (Fenêtre Glissante)
```python
limiter = RateLimiter(max_requests=100, window_seconds=60)
if limiter.can_proceed():
    limiter.record_request()
    # Faire la requête
else:
    time.sleep(limiter.wait_time())
```

**Fonctionnalités :**
- Nettoyage automatique anciennes requêtes
- Calcul temps d'attente optimal
- Taux actuel en requêtes/seconde
- Thread-safe pour usage concurrent

### CircularBuffer (Buffer Circulaire)
```python
buffer = CircularBuffer(size=100)
buffer.append(value)
recent_items = buffer.get_last(10)
average = buffer.average()
```

**Caractéristiques :**
- Taille fixe avec écrasement ancien
- Ordre chronologique préservé
- Calcul moyenne sur valeurs numériques
- Méthodes get_all(), get_last(), clear()

### SimpleCache (Cache TTL)
```python
cache = SimpleCache(max_size=1000, default_ttl=3600)
cache.set("key", value, ttl=1800)
result = cache.get("key", default="not_found")
```

**Fonctionnalités :**
- Expiration automatique TTL
- Éviction LRU quand plein
- Nettoyage proactif des entrées expirées
- Statistiques d'utilisation

### AdaptiveCounter (Compteur Intelligent)
- Fenêtre glissante configurable
- Calcul taux par seconde adaptatif
- Total lifetime + moyenne fenêtre
- Reset complet possible

### ConfigValidator (Validation Configuration)
```python
validator = ConfigValidator()
validator.add_rule("timeout", lambda x: x > 0, required=True)
errors, warnings = validator.validate(config)
```

**Système de Règles :**
- Validators personnalisés (fonctions bool)
- Distinction erreurs/warnings
- Champs obligatoires vs optionnels
- Messages d'erreur détaillés

## 🚀 Fonctions Avancées de Traitement

### Traitement par Batch
- **`batch_process(items, processor, batch_size=100, delay=0.0, progress_callback=None)`**
  - Divise automatiquement en chunks
  - Délai configurable entre batches
  - Callback de progression (batch_index, total_batches)
  - Continue même si un batch échoue
  - Agrège résultats de tous les batches

### Fusion de Configuration
- **`deep_merge_configs(base_config, override_config)`**
  - Fusion récursive profonde
  - Priorité à override_config
  - Préservation des types (dict vs autres)
  - Gestion des configurations null/invalides

### Utilitaires Divers
- **`parse_duration_string("1h30m45s")`** : Parse durées humaines → secondes
- **`interpolate_value(val1, val2, factor)`** : Interpolation linéaire 0.0-1.0
- **`create_hash_signature(*args, algorithm="sha256")`** : Signature multi-paramètres

## 🔧 API et Interface Publique

### Export Complet (`__all__`)
Le module expose 50+ fonctions organisées par catégorie :

**Temporel :** 7 fonctions (timestamps, buckets, jitter)
**Mathématique :** 6 fonctions (division safe, statistiques)
**Solana :** 7 fonctions (parsing, validation, conversion)  
**Identifiants :** 4 fonctions (cycles, scans, hashs, UUIDs)
**Collections :** 6 fonctions (navigation, fusion, manipulation)
**Validation :** 3 fonctions (nettoyage, validation, sanitisation)
**Performance :** 4 fonctions (timers, rates, efficience)
**Résilience :** 3 fonctions (backoff, retry, should_retry)
**JSON :** 2 fonctions (loads/dumps sécurisés)
**Classes :** 5 classes (RateLimiter, CircularBuffer, SimpleCache, etc.)
**Avancées :** 6 fonctions (batch, merge, signature, parsing, interpolation)

### Patterns d'Utilisation Recommandés

**Pour la Performance :**
```python
with ExecutionTimer("api_call") as timer:
    result = api_call()
rate = calculate_rate_per_second(count, timer.get_duration())
```

**Pour la Résilience :**
```python
result = retry_with_backoff(
    unstable_function,
    max_attempts=5,
    retryable_exceptions=(ConnectionError, TimeoutError)
)
```

**Pour le Traitement de Masse :**
```python
def process_batch(items):
    return [process_item(item) for item in items]

results = batch_process(
    large_list, 
    process_batch, 
    batch_size=50,
    delay_between_batches=0.1
)
```

## 🛡️ Robustesse et Gestion d'Erreur

### Philosophie Défensive
- **Jamais de crash** : Toutes les fonctions gèrent les cas d'erreur
- **Valeurs par défaut intelligentes** : 0, "", [], {} selon le contexte
- **Validation des entrées** : Type checking systématique
- **Logging des erreurs** : Exceptions catchées mais information préservée

### Gestion des Types
- Support Union types (int|float, str|None)
- Conversion automatique quand possible
- Fallback gracieux pour types incompatibles
- Préservation des types de sortie attendus

### Performance et Mémoire
- Algorithmes O(n) ou O(log n) privilégiés
- Pas de leak mémoire dans les structures circulaires
- Cleanup automatique (cache, buffers)
- Limite des structures en mémoire (max_size partout)

## 🎯 Points d'Attention Critiques

### Sécurité
- Utilisation de `secrets` pour randomisation cryptographique
- Validation complète adresses/signatures Solana
- Sanitisation système de fichiers (multi-OS)
- Protection contre injection dans les regex

### Performance
- Cache intelligent avec TTL et LRU
- Rate limiting pour éviter la surcharge
- Batch processing pour opérations masse
- Circular buffers pour historiques limités

### Maintenabilité
- Fonctions pures sans état global
- Interface stable avec typage fort
- Documentation intégrée dans le code
- Tests unitaires facilités par pureté fonctionnelle

Cette documentation permet une compréhension complète du module utilitaires sans accès au code source, incluant tous les détails d'implémentation, cas d'usage, et considérations techniques.