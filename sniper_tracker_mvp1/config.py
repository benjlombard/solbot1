# config.py
import os
from typing import Dict, Any

class Config:
    HELIUS_API_KEY = "b51a900a-0585-48c1-b8f5-b46f4d76d790"
    HELIUS_WEBHOOK_URL = "https://api.helius.xyz/v0/webhooks"
    
    # Base de données
    DATABASE_PATH = "snipers.db"
    
    # Serveur
    HOST = "0.0.0.0"
    PORT = 8010
    
    # Programmes Solana
    PUMP_FUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
    RAYDIUM_LP_V4 = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"