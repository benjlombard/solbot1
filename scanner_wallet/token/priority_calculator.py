#!/usr/bin/env python3
"""
Calculateur de score et de priorité pour les tokens
"""

import time
import math
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta

from core.priority_config import TokenPriority, PriorityConfig
from core.logger import get_logger

class TokenPriorityCalculator:
    """Calculateur de priorité des tokens"""
    
    def __init__(self, config: PriorityConfig):
        self.config = config
        self.logger = get_logger('priority_calculator')
    
    def calculate_token_score(self, token_data: Dict) -> float:
        """
        Calcule le score d'un token (0-100)
        
        Args:
            token_data: Données du token depuis la DB
            
        Returns:
            Score entre 0 et 100
        """
        try:
            # Extraction des métriques
            volume_24h = float(token_data.get('volume_24h', 0) or 0)
            price_change_24h = abs(float(token_data.get('price_change_24h', 0) or 0))
            market_cap = float(token_data.get('market_cap', 0) or 0)
            created_at = token_data.get('created_at')
            
            # Calculer l'âge du token
            age_hours = self._calculate_token_age_hours(created_at)
            
            # Compter les transactions récentes (approximation)
            tx_count = self._estimate_recent_transactions(token_data)
            
            # Normalisation des métriques (0-1)
            volume_score = min(volume_24h / self.config.volume_24h_max, 1.0)
            price_change_score = min(price_change_24h / self.config.price_change_max, 1.0)
            market_cap_score = min(market_cap / self.config.market_cap_max, 1.0)
            tx_count_score = min(tx_count / 1000, 1.0)  # Max 1000 tx récentes
            
            # Score d'âge (plus récent = meilleur score)
            age_score = self._calculate_age_score(age_hours)
            
            # Calcul du score final pondéré
            final_score = (
                volume_score * self.config.volume_weight +
                price_change_score * self.config.price_change_weight +
                market_cap_score * self.config.market_cap_weight +
                tx_count_score * self.config.tx_count_weight +
                age_score * self.config.age_weight
            ) * 100  # Convertir en score 0-100
            
            self.logger.debug(f"Score calculé pour {token_data.get('address', 'unknown')[:8]}...: {final_score:.1f}")
            
            return min(final_score, 100.0)
            
        except Exception as e:
            self.logger.error(f"Erreur calcul score: {e}")
            return 50.0  # Score neutre en cas d'erreur
    
    def determine_priority_level(self, score: float, token_data: Dict) -> TokenPriority:
        """
        Détermine le niveau de priorité basé sur le score
        
        Args:
            score: Score calculé (0-100)
            token_data: Données du token
            
        Returns:
            Niveau de priorité
        """
        try:
            # Vérifications spéciales pour DEAD
            if self._is_dead_token(token_data):
                return TokenPriority.DEAD
            
            # Vérification pour CRITICAL (nouveaux tokens)
            if self._is_critical_token(token_data):
                return TokenPriority.CRITICAL
            
            # Classification basée sur le score
            if score >= self.config.hot_threshold:
                return TokenPriority.HOT
            elif score >= self.config.warm_threshold:
                return TokenPriority.WARM
            elif score >= self.config.cold_threshold:
                return TokenPriority.COLD
            else:
                return TokenPriority.DEAD
                
        except Exception as e:
            self.logger.error(f"Erreur détermination priorité: {e}")
            return TokenPriority.WARM  # Priorité par défaut
    
    def _calculate_token_age_hours(self, created_at: str) -> float:
        """Calcule l'âge du token en heures"""
        if not created_at:
            return 24 * 365  # 1 an par défaut si pas de date
        
        try:
            # Parse de la date (format SQLite)
            if isinstance(created_at, str):
                created_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            else:
                created_time = created_at
            
            age = datetime.now() - created_time.replace(tzinfo=None)
            return age.total_seconds() / 3600
            
        except Exception:
            return 24 * 365  # Fallback
    
    def _calculate_age_score(self, age_hours: float) -> float:
        """
        Calcule le score d'âge (plus récent = meilleur)
        
        Args:
            age_hours: Âge en heures
            
        Returns:
            Score entre 0 et 1
        """
        # Score décroissant exponentiellement avec l'âge
        # Nouveaux tokens (< 1h) = score élevé
        # Anciens tokens (> 7 jours) = score faible
        
        if age_hours <= 1:
            return 1.0
        elif age_hours <= 24:  # < 1 jour
            return 0.8
        elif age_hours <= 168:  # < 1 semaine
            return 0.5
        elif age_hours <= 720:  # < 1 mois
            return 0.2
        else:
            return 0.1
    
    def _estimate_recent_transactions(self, token_data: Dict) -> int:
        """
        Estime le nombre de transactions récentes
        Basé sur le volume et le prix moyen
        """
        try:
            volume_24h = float(token_data.get('volume_24h', 0) or 0)
            price_usd = float(token_data.get('price_usd', 0) or 0)
            
            if price_usd > 0 and volume_24h > 0:
                # Estimation : volume / prix moyen / 2 (buy + sell)
                estimated_tx = (volume_24h / price_usd) / 2
                return int(min(estimated_tx, 10000))  # Cap à 10k
            
            return 0
            
        except Exception:
            return 0
    
    def _is_dead_token(self, token_data: Dict) -> bool:
        """Vérifie si un token doit être considéré comme mort"""
        try:
            # Token marqué comme mort
            if token_data.get('is_dead') == 1:
                return True
            
            # Token ruggé
            if token_data.get('is_rugged') == 1:
                return True
            
            # Volume quasi nul
            volume_24h = float(token_data.get('volume_24h', 0) or 0)
            if volume_24h < 100:  # Moins de 100$ de volume
                return True
            
            # Market cap très faible
            market_cap = float(token_data.get('market_cap', 0) or 0)
            if market_cap < 1000:  # Moins de 1000$ de market cap
                return True
            
            return False
            
        except Exception:
            return False
    
    def _is_critical_token(self, token_data: Dict) -> bool:
        """Vérifie si un token doit être en priorité critique"""
        try:
            # Token très récent
            age_hours = self._calculate_token_age_hours(token_data.get('created_at'))
            if age_hours <= self.config.new_token_age_hours:
                return True
            
            # Volume explosif récent
            volume_24h = float(token_data.get('volume_24h', 0) or 0)
            if volume_24h > 500000:  # Plus de 500k$ de volume
                return True
            
            # Changement de prix extrême
            price_change = abs(float(token_data.get('price_change_24h', 0) or 0))
            if price_change > 200:  # Plus de 200% de changement
                return True
            
            return False
            
        except Exception:
            return False