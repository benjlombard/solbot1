import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import statistics

from models import EarlyAdopter
from database import db
from config import settings

logger = logging.getLogger(__name__)

class EarlyAdopterScorer:
    def __init__(self):
        self.min_picks = settings.min_picks_for_early_adopter
        self.min_success_rate = settings.min_success_rate
        self.success_roi_threshold = settings.success_roi_threshold
        self.max_entry_market_cap = settings.max_entry_market_cap
        self.max_entry_timing_hours = settings.max_entry_timing_hours
    
    async def update_all_early_adopters(self) -> Dict[str, Any]:
        """
        Met à jour les scores de tous les early adopters potentiels
        """
        stats = {
            'wallets_analyzed': 0,
            'early_adopters_identified': 0,
            'high_confidence_adopters': 0,
            'errors': []
        }
        
        try:
            # Récupérer tous les wallets ayant fait des achats précoces
            wallet_addresses = self._get_potential_early_adopter_wallets()
            stats['wallets_analyzed'] = len(wallet_addresses)
            
            for wallet_address in wallet_addresses:
                try:
                    early_adopter = await self._analyze_wallet(wallet_address)
                    if early_adopter:
                        # Sauvegarder le profil early adopter
                        if db.upsert_early_adopter(early_adopter):
                            stats['early_adopters_identified'] += 1
                            
                            if early_adopter.confidence_score >= 0.8:
                                stats['high_confidence_adopters'] += 1
                                
                except Exception as e:
                    error_msg = f"Error analyzing wallet {wallet_address}: {e}"
                    logger.error(error_msg)
                    stats['errors'].append(error_msg)
            
            logger.info(f"Early adopter scoring completed: {stats}")
            
        except Exception as e:
            logger.error(f"Error in update_all_early_adopters: {e}")
            stats['errors'].append(str(e))
        
        return stats
    
    def _get_potential_early_adopter_wallets(self) -> List[str]:
        """
        Récupère la liste des wallets ayant fait au moins min_picks achats précoces
        """
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Récupérer les wallets avec au moins min_picks achats précoces
                cursor.execute("""
                    SELECT buyer_address, COUNT(*) as purchase_count
                    FROM early_purchases 
                    WHERE minutes_after_creation <= ?
                    GROUP BY buyer_address
                    HAVING purchase_count >= ?
                    ORDER BY purchase_count DESC
                """, (self.max_entry_timing_hours * 60, self.min_picks))
                
                return [row['buyer_address'] for row in cursor.fetchall()]
                
        except Exception as e:
            logger.error(f"Error getting potential early adopter wallets: {e}")
            return []
    
    async def _analyze_wallet(self, wallet_address: str) -> Optional[EarlyAdopter]:
        """
        Analyse un wallet pour déterminer s'il est un early adopter
        """
        try:
            # Récupérer tous les achats du wallet
            purchases = self._get_wallet_purchases_detailed(wallet_address)
            
            if len(purchases) < self.min_picks:
                return None
            
            # Calculer les métriques
            metrics = self._calculate_wallet_metrics(purchases)
            
            # Calculer le score de confiance
            confidence_score = self._calculate_confidence_score(metrics)
            
            # Vérifier les critères minimum
            if (metrics['success_rate'] >= self.min_success_rate and 
                metrics['avg_entry_timing'] <= self.max_entry_timing_hours):
                
                return EarlyAdopter(
                    wallet_address=wallet_address,
                    total_picks=metrics['total_picks'],
                    successful_picks=metrics['successful_picks'],
                    avg_entry_timing=metrics['avg_entry_timing'],
                    success_rate=metrics['success_rate'],
                    avg_roi=metrics['avg_roi'],
                    confidence_score=confidence_score,
                    last_activity=metrics['last_activity']
                )
            
            return None
            
        except Exception as e:
            logger.error(f"Error analyzing wallet {wallet_address}: {e}")
            return None
    
    def _get_wallet_purchases_detailed(self, wallet_address: str) -> List[Dict[str, Any]]:
        """
        Récupère les achats détaillés d'un wallet avec les résultats
        """
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT 
                        ep.*,
                        pt.name,
                        pt.symbol,
                        pt.created_at as token_created_at,
                        to.roi_24h,
                        to.roi_7d,
                        to.outcome_type,
                        to.peak_market_cap
                    FROM early_purchases ep
                    JOIN pump_tokens pt ON ep.token_address = pt.address
                    LEFT JOIN token_outcomes to ON ep.token_address = to.token_address
                    WHERE ep.buyer_address = ?
                    AND ep.minutes_after_creation <= ?
                    ORDER BY ep.timestamp DESC
                """, (wallet_address, self.max_entry_timing_hours * 60))
                
                purchases = []
                for row in cursor.fetchall():
                    purchase = {
                        'signature': row['signature'],
                        'token_address': row['token_address'],
                        'sol_amount': row['sol_amount'],
                        'token_amount': row['token_amount'],
                        'timestamp': datetime.fromisoformat(row['timestamp']),
                        'minutes_after_creation': row['minutes_after_creation'],
                        'market_cap_at_purchase': row['market_cap_at_purchase'],
                        'token_name': row['name'],
                        'token_symbol': row['symbol'],
                        'roi_24h': row['roi_24h'],
                        'roi_7d': row['roi_7d'],
                        'outcome_type': row['outcome_type'],
                        'peak_market_cap': row['peak_market_cap']
                    }
                    
                    # Calculer le ROI si pas disponible
                    if not purchase['roi_24h']:
                        purchase['roi_24h'] = self._estimate_roi(purchase)
                    
                    purchases.append(purchase)
                
                return purchases
                
        except Exception as e:
            logger.error(f"Error getting wallet purchases for {wallet_address}: {e}")
            return []
    
    def _calculate_wallet_metrics(self, purchases: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Calcule les métriques d'un wallet
        """
        total_picks = len(purchases)
        successful_picks = 0
        total_roi = 0
        entry_timings = []
        
        for purchase in purchases:
            # Compter les succès (ROI >= seuil de succès)
            roi = purchase.get('roi_24h', 0) or purchase.get('roi_7d', 0) or 0
            if roi >= self.success_roi_threshold:
                successful_picks += 1
            
            total_roi += roi
            entry_timings.append(purchase['minutes_after_creation'] / 60.0)  # En heures
        
        success_rate = successful_picks / total_picks if total_picks > 0 else 0
        avg_roi = total_roi / total_picks if total_picks > 0 else 0
        avg_entry_timing = statistics.mean(entry_timings) if entry_timings else 0
        
        last_activity = max(p['timestamp'] for p in purchases) if purchases else datetime.now()
        
        return {
            'total_picks': total_picks,
            'successful_picks': successful_picks,
            'success_rate': success_rate,
            'avg_roi': avg_roi,
            'avg_entry_timing': avg_entry_timing,
            'last_activity': last_activity
        }
    
    def _calculate_confidence_score(self, metrics: Dict[str, Any]) -> float:
        """
        Calcule le score de confiance d'un early adopter (0-1)
        """
        # Facteurs de scoring
        success_rate_score = min(metrics['success_rate'] / 0.8, 1.0)  # Max à 80%
        
        # Score de timing (plus tôt = mieux)
        timing_score = max(0, 1 - (metrics['avg_entry_timing'] / self.max_entry_timing_hours))
        
        # Score de volume (plus d'achats = mieux)
        volume_score = min(metrics['total_picks'] / 20, 1.0)  # Max à 20 picks
        
        # Score de ROI (avec plafond pour éviter les outliers)
        roi_score = min(metrics['avg_roi'] / 10.0, 1.0)  # Max à 10x ROI moyen
        
        # Score de récence (activité récente = bonus)
        days_since_last = (datetime.now() - metrics['last_activity']).days
        recency_score = max(0, 1 - (days_since_last / 30))  # Décroit sur 30 jours
        
        # Calcul du score final pondéré
        confidence_score = (
            success_rate_score * 0.35 +  # Taux de succès (35%)
            timing_score * 0.25 +        # Timing d'entrée (25%)
            volume_score * 0.20 +        # Volume d'activité (20%)
            roi_score * 0.15 +           # ROI moyen (15%)
            recency_score * 0.05         # Récence (5%)
        )
        
        return round(confidence_score, 3)
    
    def _estimate_roi(self, purchase: Dict[str, Any]) -> float:
        """
        Estime le ROI d'un achat si pas disponible
        Pour le MVP, retourne 0 - à implémenter avec des données de prix réelles
        """
        # TODO: Implémenter l'estimation ROI avec des données de prix
        return 0.0
    
    async def identify_copy_trading_opportunities(self, min_confidence: float = 0.8) -> List[Dict[str, Any]]:
        """
        Identifie les opportunités de copy trading basées sur les achats récents d'early adopters
        """
        opportunities = []
        
        try:
            # Récupérer les early adopters de haute confiance
            top_adopters = db.get_early_adopters(min_confidence_score=min_confidence, limit=20)
            
            if not top_adopters:
                return opportunities
            
            # Récupérer leurs achats récents (dernières 24h)
            recent_cutoff = datetime.now() - timedelta(hours=24)
            
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                for adopter in top_adopters:
                    cursor.execute("""
                        SELECT 
                            ep.*,
                            pt.name,
                            pt.symbol,
                            pt.creator
                        FROM early_purchases ep
                        JOIN pump_tokens pt ON ep.token_address = pt.address
                        WHERE ep.buyer_address = ?
                        AND ep.timestamp >= ?
                        ORDER BY ep.timestamp DESC
                        LIMIT 5
                    """, (adopter.wallet_address, recent_cutoff.isoformat()))
                    
                    recent_purchases = cursor.fetchall()
                    
                    for purchase in recent_purchases:
                        opportunity = {
                            'token_address': purchase['token_address'],
                            'token_name': purchase['name'],
                            'token_symbol': purchase['symbol'],
                            'creator': purchase['creator'],
                            'early_adopter': adopter.wallet_address,
                            'adopter_confidence': adopter.confidence_score,
                            'adopter_success_rate': adopter.success_rate,
                            'purchase_timestamp': purchase['timestamp'],
                            'minutes_after_creation': purchase['minutes_after_creation'],
                            'sol_amount': purchase['sol_amount'],
                            'confidence_level': self._classify_confidence(adopter.confidence_score)
                        }
                        opportunities.append(opportunity)
            
            # Trier par confiance et récence
            opportunities.sort(key=lambda x: (x['adopter_confidence'], -x['minutes_after_creation']), reverse=True)
            
        except Exception as e:
            logger.error(f"Error identifying copy trading opportunities: {e}")
        
        return opportunities[:10]  # Top 10 opportunités
    
    def _classify_confidence(self, score: float) -> str:
        """Classifie le niveau de confiance"""
        if score >= 0.9:
            return "TRÈS ÉLEVÉE"
        elif score >= 0.8:
            return "ÉLEVÉE"
        elif score >= 0.7:
            return "MOYENNE"
        else:
            return "FAIBLE"
    
    def get_top_performers(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Récupère les top performers avec leurs statistiques détaillées
        """
        try:
            top_adopters = db.get_early_adopters(min_confidence_score=0.6, limit=limit)
            
            performers = []
            for adopter in top_adopters:
                # Récupérer les picks récents
                recent_picks = db.get_wallet_purchases(adopter.wallet_address, days_back=7)
                
                performer = {
                    'wallet_address': adopter.wallet_address,
                    'confidence_score': adopter.confidence_score,
                    'success_rate': adopter.success_rate,
                    'total_picks': adopter.total_picks,
                    'successful_picks': adopter.successful_picks,
                    'avg_roi': adopter.avg_roi,
                    'avg_entry_timing': adopter.avg_entry_timing,
                    'last_activity': adopter.last_activity.isoformat(),
                    'recent_picks_count': len(recent_picks),
                    'confidence_level': self._classify_confidence(adopter.confidence_score)
                }
                performers.append(performer)
            
            return performers
            
        except Exception as e:
            logger.error(f"Error getting top performers: {e}")
            return []

# Instance globale
scorer = EarlyAdopterScorer()