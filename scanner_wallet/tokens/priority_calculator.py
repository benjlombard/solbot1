#!/usr/bin/env python3
"""
Calculateur de score et de priorité pour les tokens - VERSION CORRIGÉE
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
        
        # Debug des seuils
        self.logger.info(f"🎯 Seuils configurés:")
        self.logger.info(f"   HOT: {self.config.hot_threshold}")
        self.logger.info(f"   WARM: {self.config.warm_threshold}")
        self.logger.info(f"   COLD: {self.config.cold_threshold}")
    
    def calculate_token_score(self, token_data: Dict) -> float:
        """
        Calcule le score d'un token (0-100)
        
        Args:
            token_data: Données du token depuis la DB
            
        Returns:
            Score entre 0 et 100
        """
        try:
            # Extraction des métriques avec debug
            volume_24h = float(token_data.get('volume_24h', 0) or 0)
            price_change_24h = abs(float(token_data.get('price_change_24h', 0) or 0))
            market_cap = float(token_data.get('market_cap', 0) or 0)
            created_at = token_data.get('created_at')
            
            self.logger.debug(f"📊 Métriques brutes:")
            self.logger.debug(f"   Volume 24h: ${volume_24h:,.2f}")
            self.logger.debug(f"   Price change: {price_change_24h:.2f}%")
            self.logger.debug(f"   Market cap: ${market_cap:,.2f}")
            self.logger.debug(f"   Created: {created_at}")
            
            # Calculer l'âge du token
            age_hours = self._calculate_token_age_hours(created_at)
            
            # Compter les transactions récentes (approximation)
            tx_count = self._estimate_recent_transactions(token_data)
            
            # Normalisation des métriques (0-1) avec debug
            volume_score = min(volume_24h / self.config.volume_24h_max, 1.0)
            price_change_score = min(price_change_24h / self.config.price_change_max, 1.0)
            market_cap_score = min(market_cap / self.config.market_cap_max, 1.0)
            tx_count_score = min(tx_count / 1000, 1.0)  # Max 1000 tx récentes
            
            # Score d'âge (plus récent = meilleur score)
            age_score = self._calculate_age_score(age_hours)
            
            self.logger.debug(f"📈 Scores normalisés:")
            self.logger.debug(f"   Volume: {volume_score:.3f} (poids: {self.config.volume_weight})")
            self.logger.debug(f"   Price change: {price_change_score:.3f} (poids: {self.config.price_change_weight})")
            self.logger.debug(f"   Market cap: {market_cap_score:.3f} (poids: {self.config.market_cap_weight})")
            self.logger.debug(f"   TX count: {tx_count_score:.3f} (poids: {self.config.tx_count_weight})")
            self.logger.debug(f"   Age: {age_score:.3f} (poids: {self.config.age_weight}) - {age_hours:.1f}h")
            
            # Calcul du score final pondéré
            final_score = (
                volume_score * self.config.volume_weight +
                price_change_score * self.config.price_change_weight +
                market_cap_score * self.config.market_cap_weight +
                tx_count_score * self.config.tx_count_weight +
                age_score * self.config.age_weight
            ) * 100  # Convertir en score 0-100
            
            self.logger.debug(f"🎯 Score final calculé: {final_score:.1f}")
            
            return min(final_score, 100.0)
            
        except Exception as e:
            self.logger.error(f"❌ Erreur calcul score: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
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
            self.logger.debug(f"🎯 Détermination priorité pour score: {score:.1f}")
            
            # Vérifications spéciales pour DEAD
            if self._is_dead_token(token_data):
                self.logger.debug("💀 Token classé DEAD (conditions spéciales)")
                return TokenPriority.DEAD
            
            # Vérification pour CRITICAL (nouveaux tokens)
            if self._is_critical_token(token_data):
                self.logger.debug("🔥 Token classé CRITICAL (nouveau/activité intense)")
                return TokenPriority.CRITICAL
            
            # Classification basée sur le score
            if score >= self.config.hot_threshold:
                self.logger.debug(f"🌡️ Token classé HOT (score {score:.1f} >= {self.config.hot_threshold})")
                return TokenPriority.HOT
            elif score >= self.config.warm_threshold:
                self.logger.debug(f"🟡 Token classé WARM (score {score:.1f} >= {self.config.warm_threshold})")
                return TokenPriority.WARM
            elif score >= self.config.cold_threshold:
                self.logger.debug(f"🧊 Token classé COLD (score {score:.1f} >= {self.config.cold_threshold})")
                return TokenPriority.COLD
            else:
                self.logger.debug(f"💀 Token classé DEAD (score {score:.1f} < {self.config.cold_threshold})")
                return TokenPriority.DEAD
                
        except Exception as e:
            self.logger.error(f"❌ Erreur détermination priorité: {e}")
            return TokenPriority.WARM  # Priorité par défaut
    
    def _calculate_token_age_hours(self, created_at: str) -> float:
        """Calcule l'âge du token en heures"""
        if not created_at:
            return 24 * 365  # 1 an par défaut si pas de date
        
        try:
            # Parse de la date (format SQLite)
            if isinstance(created_at, str):
                # Gérer différents formats de date
                created_at = created_at.replace('Z', '').replace('+00:00', '')
                if 'T' in created_at:
                    created_time = datetime.fromisoformat(created_at)
                else:
                    created_time = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S')
            else:
                created_time = created_at
            
            age = datetime.now() - created_time
            hours = age.total_seconds() / 3600
            
            self.logger.debug(f"⏰ Âge calculé: {hours:.1f} heures")
            return hours
            
        except Exception as e:
            self.logger.debug(f"⚠️ Erreur parsing date {created_at}: {e}")
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
                result = int(min(estimated_tx, 10000))  # Cap à 10k
                self.logger.debug(f"💱 TX estimées: {result} (volume: ${volume_24h}, prix: ${price_usd})")
                return result
            
            return 0
            
        except Exception:
            return 0
    
    def _is_dead_token(self, token_data: Dict) -> bool:
        """Vérifie si un token doit être considéré comme mort"""
        try:
            # Token marqué comme mort
            if token_data.get('is_dead') == 1:
                self.logger.debug("💀 Token marqué is_dead=1")
                return True
            
            # Token ruggé
            if token_data.get('is_rugged') == 1:
                self.logger.debug("💀 Token marqué is_rugged=1")
                return True
            
            # Volume quasi nul (plus strict)
            volume_24h = float(token_data.get('volume_24h', 0) or 0)
            if volume_24h < 50:  # Moins de 50$ de volume
                self.logger.debug(f"💀 Volume trop faible: ${volume_24h}")
                return True
            
            # Market cap très faible
            market_cap = float(token_data.get('market_cap', 0) or 0)
            if market_cap < 500:  # Moins de 500$ de market cap
                self.logger.debug(f"💀 Market cap trop faible: ${market_cap}")
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
                self.logger.debug(f"🔥 Token critique: très récent ({age_hours:.1f}h)")
                return True
            
            # Volume explosif récent
            volume_24h = float(token_data.get('volume_24h', 0) or 0)
            if volume_24h > 500000:  # Plus de 500k$ de volume
                self.logger.debug(f"🔥 Token critique: volume explosif (${volume_24h:,.0f})")
                return True
            
            # Changement de prix extrême
            price_change = abs(float(token_data.get('price_change_24h', 0) or 0))
            if price_change > 200:  # Plus de 200% de changement
                self.logger.debug(f"🔥 Token critique: changement prix extrême ({price_change:.1f}%)")
                return True
            
            return False
            
        except Exception:
            return False