import os
from typing import Optional

# Charger les variables d'environnement depuis .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Fallback si python-dotenv n'est pas installé
    from pathlib import Path
    env_file = Path(".env")
    if env_file.exists():
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()

class Settings:
    def __init__(self):
        # Helius Configuration
        self.helius_api_key: str = os.getenv("HELIUS_API_KEY", "")
        self.helius_rpc_url: str = "https://mainnet.helius-rpc.com"
        
        # Pump.fun Configuration
        self.pumpfun_program_id: str = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
        
        # Database Configuration
        self.database_url: str = os.getenv("DATABASE_URL", "early_adopter.db")
        
        # Early Adopter Scoring Parameters
        self.min_picks_for_early_adopter: int = int(os.getenv("MIN_PICKS_FOR_EARLY_ADOPTER", "5"))
        self.max_entry_timing_hours: int = int(os.getenv("MAX_ENTRY_TIMING_HOURS", "6"))
        self.min_success_rate: float = float(os.getenv("MIN_SUCCESS_RATE", "0.6"))
        self.success_roi_threshold: float = float(os.getenv("SUCCESS_ROI_THRESHOLD", "5.0"))
        self.max_entry_market_cap: float = float(os.getenv("MAX_ENTRY_MARKET_CAP", "10000.0"))
        
        # Polling Configuration - OPTIMISÉ POUR ÉCONOMISER LES CRÉDITS
        self.base_polling_interval_seconds: int = int(os.getenv("BASE_POLLING_INTERVAL_SECONDS", "300"))  # 5 minutes par défaut
        self.min_polling_interval_seconds: int = int(os.getenv("MIN_POLLING_INTERVAL_SECONDS", "180"))   # 3 minutes minimum  
        self.max_polling_interval_seconds: int = int(os.getenv("MAX_POLLING_INTERVAL_SECONDS", "600"))   # 10 minutes maximum
        self.polling_lookback_minutes: int = int(os.getenv("POLLING_LOOKBACK_MINUTES", "60"))            # 1 heure pour debug
        self.adaptive_polling_enabled: bool = os.getenv("ADAPTIVE_POLLING_ENABLED", "True").lower() == "true"
        
        # Budget Optimization
        self.min_sol_amount_filter: float = float(os.getenv("MIN_SOL_AMOUNT_FILTER", "0.01"))
        self.batch_size: int = int(os.getenv("BATCH_SIZE", "20"))
        self.max_daily_credits: int = int(os.getenv("MAX_DAILY_CREDITS", "2000"))
        self.credit_warning_threshold: float = float(os.getenv("CREDIT_WARNING_THRESHOLD", "0.8"))
        self.credit_pause_threshold: float = float(os.getenv("CREDIT_PAUSE_THRESHOLD", "0.95"))
        
        # Transaction Filtering
        self.min_transaction_value_sol: float = float(os.getenv("MIN_TRANSACTION_VALUE_SOL", "0.001"))
        self.max_transactions_per_poll: int = int(os.getenv("MAX_TRANSACTIONS_PER_POLL", "1000"))
        self.signature_cache_ttl_hours: int = int(os.getenv("SIGNATURE_CACHE_TTL_HOURS", "6"))
        
        # API Configuration
        self.api_host: str = os.getenv("API_HOST", "0.0.0.0")
        self.api_port: int = int(os.getenv("API_PORT", "8000"))
        self.debug: bool = os.getenv("DEBUG", "False").lower() == "true"
        
        # Streamlit Configuration
        self.streamlit_port: int = int(os.getenv("STREAMLIT_PORT", "8501"))
        
        # Logging Configuration
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")
        self.log_file: str = os.getenv("LOG_FILE", "pumpfun_tracker.log")
        self.log_max_size_mb: int = int(os.getenv("LOG_MAX_SIZE_MB", "50"))
        self.log_backup_count: int = int(os.getenv("LOG_BACKUP_COUNT", "5"))
        
        # Performance Tuning
        self.httpx_timeout_seconds: int = int(os.getenv("HTTPX_TIMEOUT_SECONDS", "30"))
        self.async_workers: int = int(os.getenv("ASYNC_WORKERS", "4"))
        self.db_connection_pool_size: int = int(os.getenv("DB_CONNECTION_POOL_SIZE", "10"))
        
        # Metadata Enrichment
        self.enable_metadata_enrichment: bool = os.getenv("ENABLE_METADATA_ENRICHMENT", "False").lower() == "true"
        
        # Monitoring & Alerts
        self.health_check_interval_seconds: int = int(os.getenv("HEALTH_CHECK_INTERVAL_SECONDS", "300"))
        self.activity_timeout_minutes: int = int(os.getenv("ACTIVITY_TIMEOUT_MINUTES", "30"))
        self.enable_performance_monitoring: bool = os.getenv("ENABLE_PERFORMANCE_MONITORING", "True").lower() == "true"

settings = Settings()