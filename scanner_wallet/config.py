# config.py - Configuration optimisée pour le moniteur Solana v2.0

import os
from typing import List

# Récupérer les wallets directement au niveau du module
def get_wallet_addresses() -> List[str]:
    """Récupère la liste des wallets à surveiller"""

    # Mode test
    if os.getenv('TEST_MODE', 'false').lower() == 'true':
        test_wallet = os.getenv('TEST_WALLET')
        if test_wallet:
            print(f"🧪 MODE TEST activé - Wallet: {test_wallet[:8]}...{test_wallet[-8:]}")
            return [test_wallet]

    # CORRECTION: Utiliser le wallet spécifique par défaut
    default_wallet = 'AVAZvHLR2PcWpDf8BXY4rVxNHYRBytycHkcB5z5QNXYm'
    wallets_str = os.getenv('WALLET_ADDRESSES', default_wallet)
    print(wallets_str)
    if not wallets_str:
        return [default_wallet]

    # AJOUT MANQUANT: Traitement de la chaîne pour la convertir en liste
    try:
        # Séparer par virgules et nettoyer chaque wallet
        wallets = [wallet.strip() for wallet in wallets_str.split(',') if wallet.strip()]

        # Filtrer les wallets valides (longueur minimale)
        valid_wallets = []
        for wallet in wallets:
            if len(wallet) >= 32:  # Longueur minimale d'une adresse Solana
                valid_wallets.append(wallet)
            else:
                print(f"⚠️ Wallet invalide ignoré: {wallet}")

        if valid_wallets:
            print(f"✅ {len(valid_wallets)} wallet(s) chargé(s) depuis WALLET_ADDRESSES")
            for i, wallet in enumerate(valid_wallets):
                print(f"   {i+1}. {wallet[:8]}...{wallet[-8:]}")
            return valid_wallets
        else:
            print("⚠️ Aucun wallet valide trouvé, utilisation du wallet par défaut")
            return [default_wallet]

    except Exception as e:
        print(f"❌ Erreur traitement WALLET_ADDRESSES: {e}")
        print("⚠️ Utilisation du wallet par défaut")
        return [default_wallet]

# Variables globales
WALLET_ADDRESSES = get_wallet_addresses()
WALLET_ADDRESS = WALLET_ADDRESSES[0] if WALLET_ADDRESSES else '4DdrfiDHpmx55i4SPssxVzS9ZaKLb8qr45NKY9Er9nNh'


class Config:
    """Configuration principale du moniteur Solana optimisé v2.0"""

    # Wallets à surveiller
    WALLET_ADDRESSES = WALLET_ADDRESSES
    WALLET_ADDRESS = WALLET_ADDRESS

    # Configuration RPC
    QUICKNODE_ENDPOINT = os.getenv('QUICKNODE_ENDPOINT', '')
    QUICKNODE_API_KEY = os.getenv('QUICKNODE_API_KEY', '')

    # Configuration de base
    UPDATE_INTERVAL = int(os.getenv('UPDATE_INTERVAL', 45))
    MAX_RETRIES = int(os.getenv('MAX_RETRIES', 3))
    RETRY_DELAY = int(os.getenv('RETRY_DELAY', 2))
    DB_NAME = os.getenv('DB_NAME', 'solana_wallet.db')
    DEFAULT_TRANSACTION_LIMIT = 35
    MAX_TRANSACTION_LIMIT = 100

    # Configuration Flask
    FLASK_HOST = os.getenv('FLASK_HOST', '127.0.0.1')
    FLASK_PORT = int(os.getenv('FLASK_PORT', 5000))
    FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'

    # Configuration de monitoring optimisé (NOUVEAUX ATTRIBUTS)
    FULL_SCAN_INTERVAL_HOURS = int(os.getenv('FULL_SCAN_INTERVAL_HOURS', 6))
    RATE_LIMIT_DELAY = float(os.getenv('RATE_LIMIT_DELAY', 0.2))
    TOKEN_DISCOVERY_BATCH_SIZE = int(os.getenv('TOKEN_DISCOVERY_BATCH_SIZE', 50))

    # Configuration des seuils
    LARGE_TRANSACTION_THRESHOLD = float(os.getenv('ALERT_THRESHOLD', 1.0))
    MAX_CONSECUTIVE_ERRORS = int(os.getenv('MAX_CONSECUTIVE_ERRORS', 3))

    # Configuration logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE = os.getenv('LOG_FILE', 'wallet_monitor.log')

    # Configuration réseau
    RPC_TIMEOUT = 20
    CONNECTION_TIMEOUT = 10
    REQUESTS_PER_MINUTE = 100
    PAUSE_BETWEEN_TX_DETAILS = 0.1
    ERROR_BACKOFF_MULTIPLIER = 1.2

    # NOUVELLES CONFIGURATIONS BATCHING
    ENABLE_RPC_BATCHING = True
    BATCH_SIZES = {
        'getMultipleAccounts': 8,        # Conservateur pour free plan
        'token_metadata': 5,              # Métadonnées par batch
        'signatures_batch': 12,           # Signatures par batch
        'transactions_batch': 6           # Transactions par batch
    }

    # Timing et sécurité
    BATCH_TIMING = {
        'min_delay_between_batches': 0.3,     # 300ms pause entre batches
        'max_concurrent_batches': 1,          # Un seul batch à la fois
        'batch_timeout': 25,                  # 25s timeout par batch
        'adaptive_sizing': True               # Ajustement automatique des tailles
    }

    # Monitoring des rate limits
    RATE_LIMIT_MONITORING = {
        'track_response_times': True,
        'max_acceptable_response_time': 8000,  # 8s max
        'reduce_batch_size_threshold': 5000,   # Réduire si > 5s
        'emergency_fallback_threshold': 15000   # Fallback individuel si > 15s
    }

    @classmethod
    def get_rpc_endpoints(cls) -> List[str]:
        """Retourne la liste des endpoints RPC avec QuickNode en premier"""
        endpoints = []
        if cls.QUICKNODE_ENDPOINT:
            endpoints.append(cls.QUICKNODE_ENDPOINT)
        endpoints.extend([
            "https://api.mainnet-beta.solana.com",
            "https://rpc.ankr.com/solana",
            "https://solana.public-rpc.com",
        ])
        return endpoints

    @classmethod
    def get_rpc_headers(cls) -> dict:
        """Headers pour les requêtes RPC"""
        return {
            'Content-Type': 'application/json',
            'User-Agent': 'SolanaWalletMonitor/2.0-Optimized',
            'Accept': 'application/json',
        }

    @classmethod
    def validate_config(cls):
        """Valide la configuration"""
        errors = []
        warnings = []

        # Vérification des wallets
        if not cls.WALLET_ADDRESSES:
            errors.append("WALLET_ADDRESSES vide")
        else:
            for i, wallet in enumerate(cls.WALLET_ADDRESSES):
                if not wallet or len(wallet) < 40:
                    errors.append(f"Wallet #{i+1} invalide: {wallet}")

        # Vérification des paramètres de performance
        if cls.UPDATE_INTERVAL < 30:
            warnings.append("UPDATE_INTERVAL très faible - risque de rate limiting")

        if cls.RATE_LIMIT_DELAY < 0.1:
            warnings.append("RATE_LIMIT_DELAY très faible - risque de rate limiting")

        if cls.TOKEN_DISCOVERY_BATCH_SIZE > 100:
            warnings.append("TOKEN_DISCOVERY_BATCH_SIZE élevé - peut ralentir les scans")

        # Vérifier les endpoints RPC
        try:
            endpoints = cls.get_rpc_endpoints()
            if not endpoints:
                errors.append("Aucun endpoint RPC configuré")
        except Exception as e:
            errors.append(f"Erreur dans get_rpc_endpoints: {e}")

        if errors:
            raise ValueError(f"Erreurs critiques: {'; '.join(errors)}")

        return warnings  # Retourner les avertissements pour affichage

class DevelopmentConfig(Config):
    """Configuration pour le développement"""
    FLASK_DEBUG = True
    UPDATE_INTERVAL = 45
    LOG_LEVEL = 'DEBUG'
    RATE_LIMIT_DELAY = 0.3  # Plus lent en dev pour éviter les problèmes
    FULL_SCAN_INTERVAL_HOURS = 2  # Scans plus fréquents en dev
    WALLET_SELECTION_MODE = "random"  # "priority" ou "random"
    RANDOM_SELECTION_WEIGHT_BY_PRIORITY = False  # Si True, les wallets avec plus haute priorité ont plus de chances d'être sélectionnés
    MIN_INTERVAL_BETWEEN_SCANS = 30  # Intervalle minimum entre scans du même wallet (en secondes)
    RANDOM_SELECTION_COOLDOWN = 300  # Cooldown pour les wallets récemment scannés en mode aléatoire (5min)

class ProductionConfig(Config):
    """Configuration pour la production"""
    FLASK_DEBUG = False
    FLASK_HOST = '0.0.0.0'
    UPDATE_INTERVAL = 60
    LOG_LEVEL = 'INFO'
    DEFAULT_TRANSACTION_LIMIT = 25
    MAX_TRANSACTION_LIMIT = 200
    RATE_LIMIT_DELAY = 0.2
    FULL_SCAN_INTERVAL_HOURS = 6

def get_config():
    """Retourne la configuration selon l'environnement"""
    env = os.getenv('ENVIRONMENT', 'development').lower()
    if env == 'production':
        return ProductionConfig
    else:
        return DevelopmentConfig

# Configuration par défaut
DefaultConfig = get_config()

# Validation automatique au chargement du module
try:
    warnings = DefaultConfig.validate_config()
    print(f"✅ Configuration chargée - Wallet principal: {DefaultConfig.WALLET_ADDRESS[:8]}...{DefaultConfig.WALLET_ADDRESS[-8:]}")
    if warnings:
        print("⚠️ Avertissements de configuration:")
        for warning in warnings:
            print(f"   - {warning}")
except Exception as e:
    print(f"❌ Erreur de configuration: {e}")
    print("💡 Vérifiez vos variables d'environnement et votre fichier .env")
