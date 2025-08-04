# config.py
# Configuration pour l'API Token Creator Analyzer

import os

class Config:
    """Configuration de base"""
    
    # Configuration QuickNode
    QUICKNODE_ENDPOINT = os.getenv(
        'QUICKNODE_ENDPOINT', 
        'https://misty-alpha-aura.solana-mainnet.quiknode.pro/2a16287e4ba93a9df419f3fa8da45d135d682202/'
    )
    
    # Configuration Flask
    FLASK_HOST = os.getenv('FLASK_HOST', '0.0.0.0')
    FLASK_PORT = int(os.getenv('FLASK_PORT', 5001))
    FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    
    # Configuration de l'analyseur
    RATE_LIMIT_DELAY = float(os.getenv('RATE_LIMIT_DELAY', '0.5'))
    MAX_REQUESTS_PER_MINUTE = int(os.getenv('MAX_REQUESTS_PER_MINUTE', '120'))
    MAX_RETRIES = int(os.getenv('MAX_RETRIES', '2'))
    RETRY_DELAY = int(os.getenv('RETRY_DELAY', '3'))
    
    # Limites de l'API
    MAX_HOURS_BACK = int(os.getenv('MAX_HOURS_BACK', '168'))  # 7 jours max
    MAX_TRANSACTIONS_LIMIT = int(os.getenv('MAX_TRANSACTIONS_LIMIT', '1000'))
    DEFAULT_HOURS_BACK = int(os.getenv('DEFAULT_HOURS_BACK', '24'))
    
    # Configuration des exports
    EXPORT_DIR = os.getenv('EXPORT_DIR', 'exports')
    LOGS_DIR = os.getenv('LOGS_DIR', 'logs')
    
    # Configuration CORS
    CORS_ORIGINS = os.getenv('CORS_ORIGINS', '*').split(',')
    
    # Configuration des timeouts
    REQUEST_TIMEOUT = int(os.getenv('REQUEST_TIMEOUT', '20'))
    API_TIMEOUT = int(os.getenv('API_TIMEOUT', '300'))  # 5 minutes pour les analyses
    
    @classmethod
    def validate(cls):
        """Valide la configuration"""
        errors = []
        
        if not cls.QUICKNODE_ENDPOINT:
            errors.append("QUICKNODE_ENDPOINT est requis")
        
        if not cls.QUICKNODE_ENDPOINT.startswith('https://'):
            errors.append("QUICKNODE_ENDPOINT doit utiliser HTTPS")
        
        if cls.FLASK_PORT < 1 or cls.FLASK_PORT > 65535:
            errors.append("FLASK_PORT doit être entre 1 et 65535")
        
        if cls.RATE_LIMIT_DELAY < 0:
            errors.append("RATE_LIMIT_DELAY ne peut pas être négatif")
        
        if cls.MAX_REQUESTS_PER_MINUTE < 1:
            errors.append("MAX_REQUESTS_PER_MINUTE doit être au moins 1")
        
        return errors
    
    @classmethod
    def print_config(cls):
        """Affiche la configuration actuelle"""
        print("🔧 Configuration actuelle:")
        print(f"   QuickNode: {cls.QUICKNODE_ENDPOINT[:50]}...")
        print(f"   Flask Host: {cls.FLASK_HOST}")
        print(f"   Flask Port: {cls.FLASK_PORT}")
        print(f"   Debug: {cls.FLASK_DEBUG}")
        print(f"   Rate Limit: {cls.RATE_LIMIT_DELAY}s")
        print(f"   Max Req/min: {cls.MAX_REQUESTS_PER_MINUTE}")
        print(f"   Export Dir: {cls.EXPORT_DIR}")
        print(f"   Logs Dir: {cls.LOGS_DIR}")

class DevelopmentConfig(Config):
    """Configuration pour le développement"""
    FLASK_DEBUG = True
    RATE_LIMIT_DELAY = 0.2  # Plus rapide en dev
    MAX_REQUESTS_PER_MINUTE = 200

class ProductionConfig(Config):
    """Configuration pour la production"""
    FLASK_DEBUG = False
    RATE_LIMIT_DELAY = 0.5
    MAX_REQUESTS_PER_MINUTE = 120

# Sélection de la configuration basée sur l'environnement
config_name = os.getenv('FLASK_ENV', 'production').lower()

if config_name == 'development':
    config = DevelopmentConfig
elif config_name == 'production':
    config = ProductionConfig
else:
    config = Config

# Validation de la configuration
validation_errors = config.validate()
if validation_errors:
    print("❌ Erreurs de configuration:")
    for error in validation_errors:
        print(f"   - {error}")
    exit(1)