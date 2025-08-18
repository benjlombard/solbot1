#!/usr/bin/env python3
"""
Configuration pour le système de priorité des tokens
"""

import os
from dataclasses import dataclass
from enum import Enum

class TokenPriority(Enum):
    """Niveaux de priorité des tokens"""
    DEAD = 0      # Arrêt des mises à jour
    COLD = 1      # Mise à jour toutes les heures
    WARM = 2      # Mise à jour toutes les 5 minutes  
    HOT = 3       # Mise à jour toutes les 30 secondes
    CRITICAL = 4  # Mise à jour continue (nouveaux tokens)

@dataclass
class PriorityConfig:
    """Configuration du système de priorité"""
    
    # Intervalles de mise à jour (secondes)
    critical_interval: int
    hot_interval: int
    warm_interval: int
    cold_interval: int
    
    # Seuils de score
    hot_threshold: float
    warm_threshold: float
    cold_threshold: float
    
    # Poids du scoring
    volume_weight: float
    price_change_weight: float
    market_cap_weight: float
    tx_count_weight: float
    age_weight: float
    
    # Paramètres de normalisation
    volume_24h_max: float
    market_cap_max: float
    price_change_max: float
    new_token_age_hours: int
    
    # Configuration système
    recalculation_interval: int
    max_tokens_per_batch: int
    log_file: str
    log_level: str
    
    @classmethod
    def from_env(cls) -> 'PriorityConfig':
        """Charge la configuration depuis les variables d'environnement"""
        return cls(
            critical_interval=int(os.getenv('PRIORITY_CRITICAL_INTERVAL', '30')),
            hot_interval=int(os.getenv('PRIORITY_HOT_INTERVAL', '30')),
            warm_interval=int(os.getenv('PRIORITY_WARM_INTERVAL', '300')),
            cold_interval=int(os.getenv('PRIORITY_COLD_INTERVAL', '3600')),
            
            hot_threshold=float(os.getenv('PRIORITY_HOT_THRESHOLD', '80')),
            warm_threshold=float(os.getenv('PRIORITY_WARM_THRESHOLD', '50')),
            cold_threshold=float(os.getenv('PRIORITY_COLD_THRESHOLD', '20')),
            
            volume_weight=float(os.getenv('SCORING_VOLUME_WEIGHT', '0.30')),
            price_change_weight=float(os.getenv('SCORING_PRICE_CHANGE_WEIGHT', '0.20')),
            market_cap_weight=float(os.getenv('SCORING_MARKET_CAP_WEIGHT', '0.20')),
            tx_count_weight=float(os.getenv('SCORING_TX_COUNT_WEIGHT', '0.15')),
            age_weight=float(os.getenv('SCORING_AGE_WEIGHT', '0.15')),
            
            volume_24h_max=float(os.getenv('VOLUME_24H_MAX', '1000000')),
            market_cap_max=float(os.getenv('MARKET_CAP_MAX', '100000000')),
            price_change_max=float(os.getenv('PRICE_CHANGE_MAX', '500')),
            new_token_age_hours=int(os.getenv('NEW_TOKEN_AGE_HOURS', '1')),
            
            recalculation_interval=int(os.getenv('PRIORITY_RECALCULATION_INTERVAL', '600')),
            max_tokens_per_batch=int(os.getenv('PRIORITY_MAX_TOKENS_PER_BATCH', '50')),
            log_file=os.getenv('PRIORITY_LOG_FILE', 'priority_system.log'),
            log_level=os.getenv('PRIORITY_LOG_LEVEL', 'INFO')
        )