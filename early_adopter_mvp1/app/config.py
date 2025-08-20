import os
from typing import Optional
from pydantic import BaseSettings

class Settings(BaseSettings):
    # Helius Configuration
    helius_api_key: str = os.getenv("HELIUS_API_KEY", "")
    helius_webhook_secret: str = os.getenv("HELIUS_WEBHOOK_SECRET", "")
    helius_rpc_url: str = "https://5ca9e3e5aa71.ngrok-free.app/helius/webhook"
    
    # Pump.fun Configuration
    pumpfun_program_id: str = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
    
    # Database Configuration
    database_url: str = os.getenv("DATABASE_URL", "early_adopter.db")
    
    # Early Adopter Scoring Parameters
    min_picks_for_early_adopter: int = 5
    max_entry_timing_hours: int = 6
    min_success_rate: float = 0.6
    success_roi_threshold: float = 5.0
    max_entry_market_cap: float = 10000.0
    
    # Budget Optimization
    min_sol_amount_filter: float = 0.01
    debounce_window_seconds: int = 30
    batch_size: int = 20
    max_daily_credits: int = 2500
    
    # API Configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8010
    debug: bool = False
    
    # Streamlit Configuration
    streamlit_port: int = 8501
    
    class Config:
        env_file = ".env"

settings = Settings()