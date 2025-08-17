# Documentation - Formateurs Utilitaires pour le Solana Wallet Monitor

## Vue d'ensemble
**Fichier**: `utils/formatters.py`  
**Type**: Bibliothèque centralisée de formatage  
**Objectif**: Formatage cohérent et intelligent de tous les types de données pour affichage, logs et APIs du Solana Wallet Monitor

## Architecture générale

### Organisation modulaire
- **8 domaines de formatage** spécialisés couvrant tous les besoins
- **Fonctions pures** sans état pour faciliter tests et réutilisation
- **Gestion d'erreurs robuste** avec fallbacks gracieux
- **Formatage adaptatif** selon valeurs et contexte
- **Support multi-format** (texte, couleur, compact, détaillé)

### Imports et dépendances
- **Core**: `re`, `time`, `datetime`, `typing`
- **Calculs précis**: `decimal.Decimal` avec arrondi `ROUND_HALF_UP`
- **Sans dépendances externes** pour portabilité maximale

## DOMAINE 1: Formatage des adresses et identifiants

### `format_wallet_address(address, length=8, show_full=False)`
**Objectif**: Formatage uniforme adresses Solana pour UI
**Logique**:
- Validation entrée: retour "Invalid Address" si invalide
- Mode complet: `show_full=True` retourne adresse complète
- Mode compact: `{début[:length]}...{fin[-length:]}`
- Protection courtes: adresses < (2*length + 3) non tronquées

**Exemples**:
```
"4DdrfGH...Er9nNh" (length=8)
"4Ddrf...9Er9n" (length=5)
```

### `format_token_mint(mint, length=6)`
**Objectif**: Formatage mint addresses pour affichage compact
**Spécificité**: Pas de format double-côté, juste début + "..."
**Validation**: "Unknown" si invalide

### `format_signature(signature, length=16)`
**Objectif**: Formatage signatures transactions (88 chars → format court)
**Validation**: "No Signature" si invalide

### `format_ata_pubkey(ata_pubkey, length=8)`
**Objectif**: Formatage clés ATA (Associated Token Account)
**Implémentation**: Délègue à `format_wallet_address()`

### `format_program_id(program_id, length=12)`
**Objectif**: Formatage Program IDs avec reconnaissance automatique
**Programs connus reconnus**:
- `TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA` → "Token Program"
- `ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL` → "Associated Token Program"
- `11111111111111111111111111111111111111111111` → "System Program"
- `So11111111111111111111111111111111111111112` → "Wrapped SOL"

**Fallback**: Format mint si non reconnu

## DOMAINE 2: Formatage des montants et valeurs financières

### `format_sol_amount(amount, decimals=4, show_symbol=True, compact=False)`
**Objectif**: Formatage uniforme montants SOL
**Fonctionnalités**:
- Conversion automatique vers float avec validation
- Mode compact: utilise `format_compact_number()` si montant ≥ 1000
- Séparateurs milliers: `1,234.5678 SOL`
- Symbole optionnel contrôlé par `show_symbol`

**Exemples**:
```
"1,234.5678 SOL" (normal)
"1.23K SOL" (compact=True, amount≥1000)
"0.0000" (show_symbol=False)
```

### `format_token_amount(amount, symbol="", decimals=4, token_decimals=9, compact=False)`
**Objectif**: Formatage montants tokens avec adaptation intelligente
**Logique adaptative décimales**:
- `amount < 0.001`: Utilise `min(8, token_decimals)` pour précision max
- `amount < 1`: Utilise `min(6, decimals + 2)` pour détail
- `amount ≥ 1`: Utilise `decimals` standard

**Formatage intelligent**: Compact si `amount ≥ 1000` et `compact=True`

### `format_lamports(lamports, decimals=9)`
**Objectif**: Conversion lamports → SOL avec formatage
**Conversion**: `lamports / 1_000_000_000`
**Délégation**: Utilise `format_sol_amount()` pour cohérence

### `format_compact_number(number, decimals=2)`
**Objectif**: Notation compacte avec suffixes (K, M, B, T)
**Logique par seuils**:
- `≥ 1T`: Division par 1,000,000,000,000 + "T"
- `≥ 1B`: Division par 1,000,000,000 + "B"  
- `≥ 1M`: Division par 1,000,000 + "M"
- `≥ 1K`: Division par 1,000 + "K"
- `< 1K`: Pas de suffixe

**Gestion signe**: Préservation du signe négatif

### `format_percentage(value, decimals=2, show_sign=True)`
**Objectif**: Formatage pourcentages avec options affichage
**Affichage signe**: `show_sign=True` ajoute "+" pour valeurs positives
**Format**: `"+12.50%"`, `"-5.25%"`, `"0.00%"`

### `format_price_usd(price, decimals=6)`
**Objectif**: Formatage prix USD avec adaptation précision
**Logique adaptative décimales**:
- `price < $0.01`: Jusqu'à 8 décimales pour cryptos
- `price < $1`: Jusqu'à 4 décimales  
- `price ≥ $1`: 2 décimales standard
**Format**: `"$1,234.56"`, `"$0.000123"`

## DOMAINE 3: Formatage du temps et des durées

### `format_timestamp(timestamp, format_type="datetime", timezone="local")`
**Objectif**: Formatage uniforme timestamps Unix
**Types de format supportés**:
- `"datetime"`: `"2024-01-15 14:30:25"`
- `"date"`: `"2024-01-15"`
- `"time"`: `"14:30:25"`
- `"relative"`: Délègue à `format_time_ago()`
- `"iso"`: Format ISO 8601

**Validation**: "Never" si timestamp null/zéro, "Invalid Time" si erreur

### `format_time_ago(timestamp)`
**Objectif**: Formatage temps relatif intuitive
**Logique par seuils**:
- `< 60s`: `"45s ago"`
- `< 1h`: `"15m ago"`
- `< 24h`: `"3h ago"`
- `< 30j`: `"5d ago"`
- `≥ 30j`: Retour format date via `format_timestamp()`

**Cas spéciaux**: "Never" si null, "In the future" si négatif

### `format_duration(seconds, precision="auto", compact=False)`
**Objectif**: Formatage durées avec modes détaillé/compact
**Conversion unités**:
- Jours: `seconds // 86400`
- Heures: `(seconds % 86400) // 3600`
- Minutes: `(seconds % 3600) // 60`
- Secondes: `seconds % 60`

**Mode compact**: `"1d2h30m45s"`
**Mode détaillé**: `"1 day, 2 hours, 30 minutes, and 45 seconds"`
**Gestion singulier/pluriel**: `"1 hour"` vs `"2 hours"`

### `format_eta(timestamp)`
**Objectif**: Formatage ETA (temps restant jusqu'à timestamp futur)
**Logique similaire** à `format_time_ago()` mais pour futur:
- `"Now"` si timestamp ≤ maintenant
- `"in 30s"`, `"in 5m30s"`, `"in 2h15m"`

## DOMAINE 4: Formatage des états et statuts

### `format_transaction_type(tx_type, colored=False)`
**Objectif**: Formatage types transactions avec couleurs optionnelles
**Mapping complet**:
- `BUY` → `🟢 BUY` (vert ANSI si colored)
- `SELL` → `🔴 SELL` (rouge ANSI si colored)
- `TRANSFER` → `🔵 TRANSFER` (bleu)
- `TRANSFER_IN` → `🟢 RECEIVE` (vert)
- `TRANSFER_OUT` → `🟡 SEND` (jaune)
- `SWAP` → `🟣 SWAP` (violet)
- `STAKE/UNSTAKE` → `🔷/🔶` (cyan)
- `OTHER` → `⚪ OTHER` (blanc)

**Normalisation**: Conversion en majuscules et trim automatique

### `format_transaction_status(status, colored=False)`
**Objectif**: Formatage statuts avec icônes et couleurs
**Statuts supportés**:
- `SUCCESS` → `✅ SUCCESS`
- `FAILED` → `❌ FAILED`  
- `PENDING` → `⏳ PENDING`
- `TIMEOUT` → `⏰ TIMEOUT`
- `CANCELLED` → `🚫 CANCELLED`

### `format_priority_level(priority, format_type="badge")`
**Objectif**: Formatage niveaux priorité avec classification automatique
**Classification par seuils**:
- `priority ≥ 4.0`: `HIGH` 🔥 (rouge)
- `priority ≥ 2.0`: `MEDIUM` 🟡 (jaune)  
- `priority ≥ 1.0`: `LOW` 🔵 (bleu)
- `priority < 1.0`: `VERY_LOW` ⚪ (gris)

**Types de format**:
- `"badge"`: `"🔥 HIGH (4.25)"`
- `"text"`: `"HIGH (4.25)"`
- `"emoji"`: `"🔥"`
- `"color"`: Avec codes couleur ANSI

### `format_scan_status(status, details=None)`
**Objectif**: Formatage statuts scan avec détails contextuels
**Statuts avec icônes**:
- `RUNNING` → `🔄`, `COMPLETED` → `✅`, `FAILED` → `❌`
- `PENDING` → `⏳`, `CANCELLED` → `🚫`, `TIMEOUT` → `⏰`

**Enrichissement contextuel**: Ajout durée, découvertes, comptes scannés depuis `details`

## DOMAINE 5: Formatage des données techniques

### `format_rpc_method(method, params_count=None)`
**Objectif**: Formatage noms méthodes RPC pour lisibilité
**Mapping méthodes courantes**:
- `getTokenAccountsByOwner` → `"Get Token Accounts"`
- `getMultipleAccounts` → `"Get Multiple Accounts"`
- `getSignaturesForAddress` → `"Get Signatures"`
- `getTransaction` → `"Get Transaction"`
- `getBalance` → `"Get Balance"`
- `getAccountInfo` → `"Get Account Info"`

**Enrichissement**: Ajout nombre paramètres si fourni

### `format_batch_info(method, size, duration=None)`
**Objectif**: Formatage informations batches RPC avec métriques
**Format de base**: `"📦 Batch Get Multiple Accounts: 8 items"`
**Avec durée**: `"📦 Batch Get Multiple Accounts: 8 items in 1.2s (6.7 items/s)"`
**Calcul débit**: `size / duration` si durée > 0

### `format_error_summary(error, context=None)`
**Objectif**: Formatage résumés d'erreur pour logs
**Format**: `"❌ ExceptionType: message"` ou `"❌ ExceptionType in context: message"`
**Troncature**: Messages > 100 chars tronqués avec "..."

### `format_memory_usage(bytes_used)`
**Objectif**: Formatage utilisation mémoire avec unités automatiques
**Conversion progressive**: B → KB → MB → GB → TB (seuil 1024)
**Format**: `"125.4 MB"`, `"2 GB"`, `"512 B"`

## DOMAINE 6: Formatage des tableaux et listes

### `format_table_row(data, widths, alignments=None)`
**Objectif**: Formatage lignes tableaux avec alignement colonnes
**Alignements supportés**: `'left'`, `'right'`, `'center'`
**Troncature intelligente**: Si contenu > largeur → troncature avec "..."
**Séparateur**: Colonnes séparées par `" | "`

### `format_key_value_pairs(data, indent=2, max_key_width=20)`
**Objectif**: Formatage dictionnaires en paires clé-valeur alignées
**Calcul largeur**: `min(max(len(keys)), max_key_width)`
**Troncature valeurs**: Valeurs > 60 chars tronquées
**Alignement**: Clés justifiées à gauche sur largeur calculée

## DOMAINE 7: Formatage spécialisé pour les logs

### `format_log_header(title, level=1, width=80, char="=")`
**Objectif**: En-têtes de log avec niveaux hiérarchiques
**Niveau 1** (principal): Titre centré avec caractères de bordure complète
**Niveau 2** (sous-titre): `"========== TITRE =========="`
**Niveau 3** (section): `"===== TITRE"`

### `format_progress_bar(current, total, width=30, show_percentage=True)`
**Objectif**: Barres de progression ASCII
**Calcul progression**: `min(current / total, 1.0)`
**Caractères**: `'='` pour rempli, `'-'` pour vide
**Format**: `"[========------] 45.2%"`

### `format_cycle_summary(cycle_id, stats, width=100)`
**Objectif**: Résumés complets cycles monitoring
**Structure**:
1. En-tête avec ID cycle
2. Statistiques principales (wallet, durée, découvertes, transactions)
3. Métriques performance (RPC requests, efficacité)
4. Statut final avec détails
5. Bordure de fermeture

## DOMAINE 8: Formatage pour l'API et le dashboard

### `format_api_response(data, success=True, message=None, metadata=None)`
**Objectif**: Standardisation réponses API
**Structure standard**:
```json
{
  "success": true,
  "timestamp": 1642687200,
  "data": {...},
  "message": "...",  // optionnel
  "metadata": {...}  // optionnel
}
```

### `format_dashboard_stats(raw_stats)`
**Objectif**: Formatage intelligent statistiques pour dashboard
**Formatage automatique par patterns**:
- Clés contenant "balance" → `format_sol_amount()`
- Clés contenant "amount" → `format_token_amount()`
- Clés contenant "price" → `format_price_usd()`
- Clés contenant "time" → `format_timestamp(..., "relative")`
- Clés contenant "duration" → `format_duration(..., compact=True)`
- Clés contenant "percentage" → `format_percentage()`

### `format_token_list_item(token_data)`
**Objectif**: Formatage complet éléments listes tokens
**Enrichissements automatiques**:
- `mint_short`: Version tronquée du mint
- `balance`: Formatage avec symbole et décimales appropriées
- `price`: Formatage USD si disponible
- `last_activity`: Temps relatif
- `priority`: Badge priorité formaté

## Utilitaires de validation et nettoyage

### `sanitize_for_display(text, max_length=100)`
**Objectif**: Nettoyage sécurisé pour affichage
**Nettoyage**: Suppression caractères contrôle `[\x00-\x1f\x7f-\x9f]`
**Sécurité**: Retour "N/A" si invalide

### `format_safe_json(data, indent=None)`
**Objectif**: Sérialisation JSON sécurisée pour logs
**Sécurité**: `default=str` pour objets non-sérialisables
**Fallback**: Message descriptif si échec sérialisation

## Formatage spécialisé pour différents contextes

### `format_notification_message(event_type, data, format_type="text")`
**Objectif**: Messages notifications avec support multi-format
**Events supportés**:
- `"new_large_transaction"`: Formatage avec type, montant, wallet
- `"new_token_discovered"`: Formatage avec symbole et wallet

**Formats de sortie**:
- `"text"`: Texte plain
- `"html"`: Avec balises `<strong>`, `<em>`
- `"markdown"`: Avec `**`, `*`

### `format_export_filename(prefix, wallet_address=None, date_range=None, extension="csv")`
**Objectif**: Génération noms fichiers export standardisés
**Pattern**: `"{prefix}_{wallet_short}_{date_range}_{timestamp}.{extension}"`
**Nettoyage**: Caractères spéciaux dans date_range remplacés par `_`

## Formatage conditionnel et adaptatif

### `format_adaptive_precision(value, value_type="auto")`
**Objectif**: Précision automatique selon valeur et type
**Types spécialisés**:
- `"currency"`: 2 décimales standard, jusqu'à 8 pour micro-montants
- `"percentage"`: 1-3 décimales selon magnitude
- `"ratio"`: 0-4 décimales selon magnitude
- `"auto"`: Logique générale adaptative

### `format_contextual_amount(amount, context)`
**Objectif**: Formatage montants selon contexte structuré
**Types contextuels**:
- `context.type = 'sol'`: Délègue à `format_sol_amount()`
- `context.type = 'token'`: Délègue à `format_token_amount()`
- `context.type = 'usd'`: Délègue à `format_price_usd()`
- `context.type = 'lamports'`: Conversion et formatage

## Constantes et helpers

### `CONTEXT_ICONS`
**Dictionnaire complet** icônes par contexte:
- Actions: `success` ✅, `error` ❌, `warning` ⚠️, `info` ℹ️
- Domaines: `money` 💰, `wallet` 👛, `token` 🪙, `transaction` 💸
- Système: `performance` 📊, `batch` 📦, `system` ⚙️

### `FORMAT_TEMPLATES`
**Templates réutilisables** avec variables:
- `transaction_summary`: `"{icon} {type} {amount} {symbol} on {wallet_short}"`
- `discovery_summary`: `"🆕 Found {count} new {item_type} on {wallet_short}"`
- `priority_change`: `"{icon} Priority: {old:.2f} → {new:.2f} ({change:+.2f})"`
- `performance_metric`: `"📊 {metric}: {value} ({status})"`

### `apply_format_template(template_name, **kwargs)`
**Moteur de templating**: Application templates avec substitution variables
**Gestion d'erreurs**: Message d'erreur si variable manquante

### `get_context_icon(context)`
**Résolution icônes**: Retour icône appropriée ou 📌 par défaut

## Caractéristiques transversales

### Gestion d'erreurs robuste
- **Validation entrées**: Vérification types et valeurs nulles
- **Fallbacks gracieux**: Messages descriptifs si données invalides
- **Pas d'exceptions**: Retour toujours chaîne même en cas d'erreur

### Performance optimisée
- **Fonctions pures**: Pas d'état, facilite mise en cache
- **Calculs minimal**: Évite conversions multiples
- **Lazy evaluation**: Calculs seulement si nécessaires

### Internationalisation prête
- **Formatage locale-aware**: Support séparateurs milliers
- **Messages en anglais**: Facilement traduisibles
- **Formats standards**: ISO pour dates, conventions internationales

### Extensibilité
- **Architecture modulaire**: Ajout facile nouvelles fonctions
- **Templates configurables**: Nouveaux formats via constantes
- **Context-aware**: Adaptation automatique selon données

Cette documentation complète permet de comprendre parfaitement tous les aspects du système de formatage, ses 70+ fonctions, leurs interactions et cas d'usage, sans nécessiter l'accès au code source.