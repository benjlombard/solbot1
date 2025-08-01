# config.py - Configuration avancée pour le moniteur Solana

import os
from typing import List

# Récupérer les wallets directement au niveau du module
def get_wallet_addresses() -> List[str]:
    wallets_str = os.getenv('WALLET_ADDRESSES')
    wallets = [wallet.strip() for wallet in wallets_str.split(',') if wallet.strip()]
    return wallets

# Variables globales
WALLET_ADDRESSES = get_wallet_addresses()
WALLET_ADDRESS = WALLET_ADDRESSES[0] if WALLET_ADDRESSES else '2RH6rUTPBJ9rUDPpuV9b8z1YL56k1tYU6Uk5ZoaEFFSK'

class Config:
    """Configuration principale du moniteur Solana"""
    
    # Utiliser les variables globales
    WALLET_ADDRESSES = WALLET_ADDRESSES
    WALLET_ADDRESS = WALLET_ADDRESS
    
    QUICKNODE_ENDPOINT = os.getenv('QUICKNODE_ENDPOINT', '')
    QUICKNODE_API_KEY = os.getenv('QUICKNODE_API_KEY', '')

    # Le reste de ta config reste pareil...
    @classmethod
    def get_rpc_endpoints(cls) -> List[str]:
        endpoints = []
        if cls.QUICKNODE_ENDPOINT:
            endpoints.append(cls.QUICKNODE_ENDPOINT)
        endpoints.extend([
            "https://api.mainnet-beta.solana.com",
            "https://rpc.ankr.com/solana",
            "https://solana.public-rpc.com",
        ])
        return endpoints
    
    # Tout le reste de ta config...
    UPDATE_INTERVAL = int(os.getenv('UPDATE_INTERVAL', 90))
    MAX_RETRIES = int(os.getenv('MAX_RETRIES', 3))
    RETRY_DELAY = int(os.getenv('RETRY_DELAY', 2))
    DB_NAME = os.getenv('DB_NAME', 'solana_wallet.db')
    DEFAULT_TRANSACTION_LIMIT = 35
    MAX_TRANSACTION_LIMIT = 100
    LARGE_TRANSACTION_THRESHOLD = float(os.getenv('ALERT_THRESHOLD', 1.0))
    FLASK_HOST = os.getenv('FLASK_HOST', '127.0.0.1')
    FLASK_PORT = int(os.getenv('FLASK_PORT', 5000))
    FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    RPC_TIMEOUT = 20
    CONNECTION_TIMEOUT = 10
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE = os.getenv('LOG_FILE', 'wallet_monitor.log')
    REQUESTS_PER_MINUTE = 100
    PAUSE_BETWEEN_TX_DETAILS = 0.3
    MAX_CONSECUTIVE_ERRORS = 2
    ERROR_BACKOFF_MULTIPLIER = 1.2
    
    @classmethod
    def get_rpc_headers(cls) -> dict:
        return {
            'Content-Type': 'application/json',
            'User-Agent': 'SolanaWalletMonitor/1.0-QuickNode',
            'Accept': 'application/json',
        }
    
    @classmethod
    def validate_config(cls):
        errors = []
        if not cls.WALLET_ADDRESS or len(cls.WALLET_ADDRESS) < 40:
            errors.append("WALLET_ADDRESS invalide")
        if cls.UPDATE_INTERVAL < 30:
            errors.append("UPDATE_INTERVAL trop faible (minimum 30s recommandé)")
        try:
            endpoints = cls.get_rpc_endpoints()
            if not endpoints:
                errors.append("Aucun endpoint RPC configuré")
        except Exception as e:
            errors.append(f"Erreur dans get_rpc_endpoints: {e}")
        if errors:
            raise ValueError(f"Erreurs de configuration: {', '.join(errors)}")
        return True

# Le reste pareil...
class DevelopmentConfig(Config):
    FLASK_DEBUG = True
    UPDATE_INTERVAL = 30
    LOG_LEVEL = 'DEBUG'

class ProductionConfig(Config):
    FLASK_DEBUG = False
    FLASK_HOST = '0.0.0.0'
    UPDATE_INTERVAL = 30
    LOG_LEVEL = 'INFO'
    DEFAULT_TRANSACTION_LIMIT = 25
    MAX_TRANSACTION_LIMIT = 200

def get_config():
    env = os.getenv('ENVIRONMENT', 'development').lower()
    if env == 'production':
        return ProductionConfig
    else:
        return DevelopmentConfig

DefaultConfig = get_config()





















































































































