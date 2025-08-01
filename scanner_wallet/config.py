# config.py - Configuration avancée pour le moniteur Solana

import os
from typing import List

class Config:
    """Configuration principale du moniteur Solana"""
    
    # Wallet à surveiller
    WALLET_ADDRESS = os.getenv('WALLET_ADDRESS', '2RH6rUTPBJ9rUDPpuV9b8z1YL56k1tYU6Uk5ZoaEFFSK')
    
    # Clé API Ankr (remplacez par votre vraie clé en production)
    #ANKR_API_KEY = os.getenv('ANKR_API_KEY', '899e608564ea0a06d7eba5d751919e7769ab4c52956913f7bb8c5e655ff2d737')
    
    QUICKNODE_ENDPOINT = os.getenv('QUICKNODE_ENDPOINT', '')
    QUICKNODE_API_KEY = os.getenv('QUICKNODE_API_KEY', '')

    # Endpoints RPC Solana (ordonnés par préférence)
    @classmethod
    def get_rpc_endpoints(cls) -> List[str]:
        endpoints = []
        # QuickNode premium (priorité 1)
        if cls.QUICKNODE_ENDPOINT:
            endpoints.append(cls.QUICKNODE_ENDPOINT)
        # Fallbacks
        endpoints.extend([
            "https://api.mainnet-beta.solana.com",
            "https://rpc.ankr.com/solana",
            "https://solana.public-rpc.com",
        ])
        
        return endpoints
    
    # Configuration du monitoring (optimisé pour Ankr)
    UPDATE_INTERVAL = int(os.getenv('UPDATE_INTERVAL', 90))     # 45 secondes (plus rapide avec Ankr)
    MAX_RETRIES = int(os.getenv('MAX_RETRIES', 3))              # Nombre de tentatives
    RETRY_DELAY = int(os.getenv('RETRY_DELAY', 2))              # Délai réduit entre tentatives
    
    # Configuration de la base de données
    DB_NAME = os.getenv('DB_NAME', 'solana_wallet.db')
    
    # Configuration des transactions (optimisé pour Ankr)
    DEFAULT_TRANSACTION_LIMIT = 35                              # Plus élevé avec Ankr premium
    MAX_TRANSACTION_LIMIT = 100                                 # Maximum autorisé avec Ankr
    
    # Configuration des alertes
    LARGE_TRANSACTION_THRESHOLD = float(os.getenv('ALERT_THRESHOLD', 1.0))  # SOL
    
    # Configuration Flask
    FLASK_HOST = os.getenv('FLASK_HOST', '127.0.0.1')          # localhost uniquement par défaut
    FLASK_PORT = int(os.getenv('FLASK_PORT', 5000))
    FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    
    # Configuration des timeouts
    RPC_TIMEOUT = 20                                            # Timeout RPC en secondes
    CONNECTION_TIMEOUT = 10                                     # Timeout de connexion
    
    # Configuration du logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE = os.getenv('LOG_FILE', 'wallet_monitor.log')
    
    # Rate limiting optimisé pour Ankr
    REQUESTS_PER_MINUTE = 100                                   # 150/min avec Ankr (bien sous la limite de 1800)
    PAUSE_BETWEEN_TX_DETAILS = 0.3                             # Pause réduite entre requêtes
    
    # Configuration de performance
    MAX_CONSECUTIVE_ERRORS = 2                                 # Moins d'erreurs attendues avec Ankr
    ERROR_BACKOFF_MULTIPLIER = 1.2                             # Backoff plus doux
    
    @classmethod
    def get_rpc_headers(cls) -> dict:
        """Headers à utiliser pour les requêtes RPC"""
        headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'SolanaWalletMonitor/1.0-QuickNode',
        'Accept': 'application/json',
    }
        return headers
    
    @classmethod
    def validate_config(cls):
        """Valide la configuration"""
        errors = []
        
        if not cls.WALLET_ADDRESS or len(cls.WALLET_ADDRESS) < 40:
            errors.append("WALLET_ADDRESS invalide")
        
        if cls.UPDATE_INTERVAL < 30:
            errors.append("UPDATE_INTERVAL trop faible (minimum 30s recommandé)")
        
        # Vérifier les endpoints RPC
        try:
            endpoints = cls.get_rpc_endpoints()
            if not endpoints:
                errors.append("Aucun endpoint RPC configuré")
        except Exception as e:
            errors.append(f"Erreur dans get_rpc_endpoints: {e}")
        
        if errors:
            raise ValueError(f"Erreurs de configuration: {', '.join(errors)}")
        
        return True

# Configuration pour développement
class DevelopmentConfig(Config):
    FLASK_DEBUG = True
    UPDATE_INTERVAL = 30  # Plus lent en dev
    LOG_LEVEL = 'DEBUG'

# Configuration pour production avec Ankr
class ProductionConfig(Config):
    FLASK_DEBUG = False
    FLASK_HOST = '0.0.0.0'  # Accessible depuis l'extérieur
    UPDATE_INTERVAL = 30    # Très rapide avec Ankr premium
    LOG_LEVEL = 'INFO'
    DEFAULT_TRANSACTION_LIMIT = 25
    MAX_TRANSACTION_LIMIT = 200

# Sélection automatique de l'environnement
def get_config():
    env = os.getenv('ENVIRONMENT', 'development').lower()
    
    if env == 'production':
        return ProductionConfig
    else:
        return DevelopmentConfig

# Configuration par défaut
DefaultConfig = get_config()