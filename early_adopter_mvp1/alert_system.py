import asyncio
import logging
from typing import Dict, List, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

class AlertType(Enum):
    HIGH_OPPORTUNITY = "high_opportunity"
    EARLY_ADOPTER_SIGNAL = "early_adopter_signal"
    VOLUME_SPIKE = "volume_spike"
    LIQUIDITY_THRESHOLD = "liquidity_threshold"
    BONDING_CURVE_PROGRESS = "bonding_curve_progress"
    PRICE_MOVEMENT = "price_movement"
    HOLDER_CONCENTRATION = "holder_concentration"

@dataclass
class Alert:
    token_address: str
    alert_type: AlertType
    severity: str  # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    message: str
    data: Dict[str, Any]
    timestamp: datetime
    expires_at: datetime

class AdvancedAlertSystem:
    def __init__(self):
        self.active_alerts: List[Alert] = []
        self.alert_history: List[Alert] = []
        self.user_preferences = {
            'min_opportunity_score': 70,
            'min_ea_count': 2,
            'max_risk_score': 40,
            'volume_spike_threshold': 300,  # % increase
            'price_movement_threshold': 50,  # % change
            'bonding_curve_threshold': 80,  # % completion
        }
    
    async def analyze_token_for_alerts(self, token_data: Dict[str, Any]) -> List[Alert]:
        """Analyse un token et génère des alertes si nécessaire"""
        alerts = []
        
        # Alerte opportunité élevée
        if self._check_high_opportunity(token_data):
            alerts.append(self._create_opportunity_alert(token_data))
        
        # Alerte signal early adopter
        if self._check_early_adopter_signal(token_data):
            alerts.append(self._create_ea_signal_alert(token_data))
        
        # Alerte spike de volume
        if self._check_volume_spike(token_data):
            alerts.append(self._create_volume_spike_alert(token_data))
        
        # Alerte bonding curve
        if self._check_bonding_curve_progress(token_data):
            alerts.append(self._create_bonding_curve_alert(token_data))
        
        # Alerte mouvement de prix
        if self._check_price_movement(token_data):
            alerts.append(self._create_price_movement_alert(token_data))
        
        return alerts
    
    def _check_high_opportunity(self, token_data: Dict[str, Any]) -> bool:
        """Vérifie si le token présente une opportunité élevée"""
        opportunity_score = self._calculate_opportunity_score(token_data)
        risk_score = self._calculate_risk_score(token_data)
        ea_count = len(token_data.get('early_adopter_buyers', []))
        
        return (
            opportunity_score >= self.user_preferences['min_opportunity_score'] and
            risk_score <= self.user_preferences['max_risk_score'] and
            ea_count >= self.user_preferences['min_ea_count'] and
            token_data.get('age_hours', 24) <= 6  # Très récent
        )
    
    def _check_early_adopter_signal(self, token_data: Dict[str, Any]) -> bool:
        """Vérifie les signaux d'early adopters"""
        ea_buyers = token_data.get('early_adopter_buyers', [])
        high_confidence_ea = [
            ea for ea in ea_buyers 
            if ea.get('confidence_score', 0) >= 0.8
        ]
        
        return len(high_confidence_ea) >= 2
    
    def _check_volume_spike(self, token_data: Dict[str, Any]) -> bool:
        """Détecte les spikes de volume"""
        current_volume = token_data.get('volume_1h', 0)
        avg_volume = token_data.get('volume_24h', 0) / 24  # Volume horaire moyen
        
        if avg_volume > 0:
            volume_increase = ((current_volume - avg_volume) / avg_volume) * 100
            return volume_increase >= self.user_preferences['volume_spike_threshold']
        
        return False
    
    def _check_bonding_curve_progress(self, token_data: Dict[str, Any]) -> bool:
        """Vérifie la progression de la bonding curve"""
        progress = token_data.get('bonding_curve_progress', 0)
        return progress >= self.user_preferences['bonding_curve_threshold']
    
    def _check_price_movement(self, token_data: Dict[str, Any]) -> bool:
        """Détecte les mouvements de prix importants"""
        price_change_1h = token_data.get('price_change_1h_percent', 0)
        return abs(price_change_1h) >= self.user_preferences['price_movement_threshold']
    
    def _create_opportunity_alert(self, token_data: Dict[str, Any]) -> Alert:
        """Crée une alerte d'opportunité"""
        ea_count = len(token_data.get('early_adopter_buyers', []))
        opportunity_score = self._calculate_opportunity_score(token_data)
        
        return Alert(
            token_address=token_data['address'],
            alert_type=AlertType.HIGH_OPPORTUNITY,
            severity="HIGH",
            message=f"🎯 OPPORTUNITÉ DÉTECTÉE: {token_data.get('symbol', 'UNK')} - Score: {opportunity_score}/100, {ea_count} EA",
            data={
                'symbol': token_data.get('symbol'),
                'opportunity_score': opportunity_score,
                'ea_count': ea_count,
                'age_hours': token_data.get('age_hours'),
                'pump_fun_link': f"https://pump.fun/{token_data['address']}"
            },
            timestamp=datetime.now(),
            expires_at=datetime.now() + timedelta(hours=2)
        )
    
    def _create_ea_signal_alert(self, token_data: Dict[str, Any]) -> Alert:
        """Crée une alerte de signal early adopter"""
        ea_buyers = token_data.get('early_adopter_buyers', [])
        high_confidence = [ea for ea in ea_buyers if ea.get('confidence_score', 0) >= 0.8]
        
        return Alert(
            token_address=token_data['address'],
            alert_type=AlertType.EARLY_ADOPTER_SIGNAL,
            severity="MEDIUM",
            message=f"🏆 SIGNAL EA FORT: {token_data.get('symbol', 'UNK')} - {len(high_confidence)} EA haute confiance",
            data={
                'symbol': token_data.get('symbol'),
                'high_confidence_ea_count': len(high_confidence),
                'top_ea_scores': [ea.get('confidence_score') for ea in high_confidence[:3]],
                'pump_fun_link': f"https://pump.fun/{token_data['address']}"
            },
            timestamp=datetime.now(),
            expires_at=datetime.now() + timedelta(hours=1)
        )
    
    def _create_volume_spike_alert(self, token_data: Dict[str, Any]) -> Alert:
        """Crée une alerte de spike de volume"""
        current_volume = token_data.get('volume_1h', 0)
        volume_increase = token_data.get('volume_increase_percent', 0)
        
        return Alert(
            token_address=token_data['address'],
            alert_type=AlertType.VOLUME_SPIKE,
            severity="MEDIUM",
            message=f"📈 SPIKE VOLUME: {token_data.get('symbol', 'UNK')} - +{volume_increase:.0f}% en 1h",
            data={
                'symbol': token_data.get('symbol'),
                'volume_1h': current_volume,
                'volume_increase_percent': volume_increase,
                'pump_fun_link': f"https://pump.fun/{token_data['address']}"
            },
            timestamp=datetime.now(),
            expires_at=datetime.now() + timedelta(minutes=30)
        )
    
    def _create_bonding_curve_alert(self, token_data: Dict[str, Any]) -> Alert:
        """Crée une alerte de progression bonding curve"""
        progress = token_data.get('bonding_curve_progress', 0)
        
        return Alert(
            token_address=token_data['address'],
            alert_type=AlertType.BONDING_CURVE_PROGRESS,
            severity="HIGH",
            message=f"🚀 BONDING CURVE: {token_data.get('symbol', 'UNK')} - {progress:.1f}% complété",
            data={
                'symbol': token_data.get('symbol'),
                'bonding_curve_progress': progress,
                'estimated_graduation_time': self._estimate_graduation_time(token_data),
                'pump_fun_link': f"https://pump.fun/{token_data['address']}"
            },
            timestamp=datetime.now(),
            expires_at=datetime.now() + timedelta(hours=6)
        )
    
    def _create_price_movement_alert(self, token_data: Dict[str, Any]) -> Alert:
        """Crée une alerte de mouvement de prix"""
        price_change = token_data.get('price_change_1h_percent', 0)
        severity = "HIGH" if abs(price_change) >= 100 else "MEDIUM"
        
        direction = "📈" if price_change > 0 else "📉"
        
        return Alert(
            token_address=token_data['address'],
            alert_type=AlertType.PRICE_MOVEMENT,
            severity=severity,
            message=f"{direction} MOUVEMENT PRIX: {token_data.get('symbol', 'UNK')} - {price_change:+.1f}% en 1h",
            data={
                'symbol': token_data.get('symbol'),
                'price_change_1h_percent': price_change,
                'current_price': token_data.get('price_usd'),
                'pump_fun_link': f"https://pump.fun/{token_data['address']}"
            },
            timestamp=datetime.now(),
            expires_at=datetime.now() + timedelta(minutes=15)
        )
    
    def _calculate_opportunity_score(self, token_data: Dict[str, Any]) -> int:
        """Calcule le score d'opportunité"""
        # Logique de calcul simplifiée (à adapter selon vos besoins)
        score = 0
        
        # Signal EA (40 points max)
        ea_count = len(token_data.get('early_adopter_buyers', []))
        score += min(40, ea_count * 10)
        
        # Timing (20 points max)
        age_hours = token_data.get('age_hours', 24)
        if age_hours < 1:
            score += 20
        elif age_hours < 6:
            score += 15
        elif age_hours < 24:
            score += 10
        
        # Volume (20 points max)
        volume_24h = token_data.get('volume_24h_sol', 0)
        if volume_24h > 50:
            score += 20
        elif volume_24h > 10:
            score += 15
        elif volume_24h > 1:
            score += 10
        
        # Liquidité (20 points max)
        liquidity = token_data.get('liquidity_sol', 0)
        if liquidity > 20:
            score += 20
        elif liquidity > 10:
            score += 15
        elif liquidity > 5:
            score += 10
        
        return min(100, score)
    
    def _calculate_risk_score(self, token_data: Dict[str, Any]) -> int:
        """Calcule le score de risque"""
        risk = 0
        
        # Faible liquidité
        if token_data.get('liquidity_sol', 0) < 5:
            risk += 30
        
        # Concentration des holders
        top_5_percent = token_data.get('top_5_holders_percentage', 0)
        if top_5_percent > 70:
            risk += 25
        elif top_5_percent > 50:
            risk += 15
        
        # Pas d'early adopters
        if len(token_data.get('early_adopter_buyers', [])) == 0:
            risk += 20
        
        # Token très récent
        if token_data.get('age_hours', 24) < 0.5:
            risk += 15
        
        # Faible volume
        if token_data.get('volume_24h_sol', 0) < 1:
            risk += 20
        
        return min(100, risk)
    
    def _estimate_graduation_time(self, token_data: Dict[str, Any]) -> str:
        """Estime le temps avant graduation de la bonding curve"""
        progress = token_data.get('bonding_curve_progress', 0)
        volume_rate = token_data.get('volume_1h', 0)
        
        if volume_rate > 0 and progress < 100:
            remaining = 100 - progress
            # Estimation simplifiée basée sur le volume actuel
            hours_remaining = remaining / (volume_rate * 0.1)  # Facteur arbitraire
            
            if hours_remaining < 1:
                return f"{int(hours_remaining * 60)} minutes"
            elif hours_remaining < 24:
                return f"{hours_remaining:.1f} heures"
            else:
                return f"{hours_remaining/24:.1f} jours"
        
        return "Impossible à estimer"
    
    async def process_alerts(self) -> None:
        """Traite et nettoie les alertes"""
        now = datetime.now()
        
        # Supprimer les alertes expirées
        self.active_alerts = [
            alert for alert in self.active_alerts 
            if alert.expires_at > now
        ]
        
        # Déplacer les anciennes alertes vers l'historique
        expired_alerts = [
            alert for alert in self.active_alerts 
            if alert.expires_at <= now
        ]
        
        self.alert_history.extend(expired_alerts)
        
        # Garder seulement les 1000 dernières alertes dans l'historique
        if len(self.alert_history) > 1000:
            self.alert_history = self.alert_history[-1000:]
    
    def get_active_alerts(self, severity_filter: str = None) -> List[Alert]:
        """Récupère les alertes actives"""
        if severity_filter:
            return [
                alert for alert in self.active_alerts 
                if alert.severity == severity_filter
            ]
        return self.active_alerts.copy()
    
    def get_alerts_for_token(self, token_address: str) -> List[Alert]:
        """Récupère les alertes pour un token spécifique"""
        return [
            alert for alert in self.active_alerts 
            if alert.token_address == token_address
        ]
    
    def update_preferences(self, new_preferences: Dict[str, Any]) -> None:
        """Met à jour les préférences utilisateur"""
        self.user_preferences.update(new_preferences)
        logger.info(f"Alert preferences updated: {new_preferences}")
    
    def add_custom_alert(self, alert: Alert) -> None:
        """Ajoute une alerte personnalisée"""
        self.active_alerts.append(alert)
        logger.info(f"Custom alert added for {alert.token_address}: {alert.message}")

# Instance globale
alert_system = AdvancedAlertSystem()