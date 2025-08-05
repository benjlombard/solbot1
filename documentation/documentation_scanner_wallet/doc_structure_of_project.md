## 📋 Description des Modules

### 🔧 Core (Fondations)
- **config.py** : Configuration centralisée du système
- **database.py** : Gestionnaire SQLite thread-safe
- **logger.py** : Configuration logging avancée
- **exceptions.py** : Exceptions personnalisées

### 🔌 RPC (Communication Blockchain)
- **client.py** : Client RPC avec système de fallback
- **batch_manager.py** : Gestionnaire de batching intelligent
- **rate_limiter.py** : Gestion des limites de taux adaptatifs
- **endpoints.py** : Configuration des endpoints RPC

### 👛 Wallet (Surveillance Portefeuilles)
- **monitor.py** : Moniteur principal (orchestreur)
- **priority_manager.py** : Système de priorités dynamiques
- **scanner.py** : Logique de scan des comptes
- **balance_tracker.py** : Suivi des changements de balance

### 🪙 Token (Gestion Tokens)
- **account_manager.py** : Gestion des comptes de tokens (ATA)
- **metadata_fetcher.py** : Récupération des métadonnées tokens
- **discovery_engine.py** : Moteur de découverte de tokens
- **cache_manager.py** : Cache intelligent des métadonnées

### 💰 Transaction (Analyse Transactions)
- **analyzer.py** : Analyse des transactions
- **classifier.py** : Classification buy/sell/transfer
- **storage.py** : Sauvegarde des transactions
- **validator.py** : Validation des données de transactions

### 🌐 API (Interface Web)
- **routes/** : Routes organisées par fonctionnalité
  - **dashboard.py** : Interface principale
  - **analytics.py** : Analytics avancées
  - **batching.py** : Gestion du batching
  - **admin.py** : Administration système
- **middleware/** : Middleware de l'application
  - **auth.py** : Authentification (développement futur)
  - **cors.py** : Configuration CORS
- **app.py** : Application Flask principale

### 📊 Models (Modèles de Données)
- **wallet.py** : Modèles de données wallet
- **transaction.py** : Modèles de données transaction
- **token.py** : Modèles de données token
- **schemas.py** : Schémas de validation API

### 🛠️ Utils (Utilitaires)
- **helpers.py** : Fonctions utilitaires générales
- **formatters.py** : Formatage des données
- **validators.py** : Validation des données
- **constants.py** : Constantes globales du système