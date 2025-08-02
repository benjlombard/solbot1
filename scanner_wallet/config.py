# config.py - Configuration optimisée pour le moniteur Solana v2.0

import os
from typing import List

# Récupérer les wallets directement au niveau du module
def get_wallet_addresses() -> List[str]:
    wallets_str = os.getenv('WALLET_ADDRESSES', '2RH6rUTPBJ9rUDPpuV9b8z1YL56k1tYU6Uk5ZoaEFFSK')
    if not wallets_str:
        return ['2RH6rUTPBJ9rUDPpuV9b8z1YL56k1tYU6Uk5ZoaEFFSK']
    wallets = [wallet.strip() for wallet in wallets_str.split(',') if wallet.strip()]
    return wallets

# Variables globales
WALLET_ADDRESSES = get_wallet_addresses()
WALLET_ADDRESS = WALLET_ADDRESSES[0] if WALLET_ADDRESSES else '2RH6rUTPBJ9rUDPpuV9b8z1YL56k1tYU6Uk5ZoaEFFSK'

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
    if warnings:
        print("⚠️ Avertissements de configuration:")
        for warning in warnings:
            print(f"   - {warning}")
except Exception as e:
    print(f"❌ Erreur de configuration: {e}")
    print("💡 Vérifiez vos variables d'environnement et votre fichier .env")