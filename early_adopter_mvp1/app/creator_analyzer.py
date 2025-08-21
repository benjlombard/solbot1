import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict
from dataclasses import dataclass

from .database import db

logger = logging.getLogger(__name__)

@dataclass
class TokenOutcome:
    """Classe pour représenter le résultat d'un token"""
    address: str
    name: Optional[str]
    symbol: Optional[str]
    created_at: datetime
    outcome: str  # SUCCESS, FAILURE, NEUTRAL, PENDING
    roi_24h: float
    roi_7d: Optional[float]
    peak_market_cap: float
    current_market_cap: float
    survival_time_hours: float
    is_rugged: bool
    final_status: str  # ACTIVE, DEAD, RUGGED, MIGRATED

@dataclass
class CreatorPerformance:
    """Classe pour représenter les performances d'un créateur"""
    creator_address: str
    total_tokens: int
    successful_tokens: int
    failed_tokens: int
    neutral_tokens: int
    pending_tokens: int
    success_rate: float
    failure_rate: float
    avg_roi: float
    median_roi: float
    best_roi: float
    worst_roi: float
    avg_survival_time: float
    reputation_score: float
    risk_score: float
    confidence_level: str
    is_blacklisted: bool
    blacklist_reason: Optional[str]
    consecutive_failures: int
    days_since_last_success: Optional[int]
    avg_time_between_launches: float
    launch_frequency_category: str
    first_token_date: Optional[datetime]
    last_token_date: Optional[datetime]

class CreatorAnalyzer:
    """
    Analyseur de performance des créateurs de tokens
    """
    
    def __init__(self):
        # Seuils configurables
        self.SUCCESS_ROI_THRESHOLD = 5.0  # ROI > 5x = succès
        self.FAILURE_ROI_THRESHOLD = -0.5  # Perte > 50% = échec
        self.SUCCESS_MARKET_CAP_THRESHOLD = 100000  # $100k = succès
        self.FAILURE_MARKET_CAP_THRESHOLD = 1000  # < $1k après 48h = échec
        self.MIN_SURVIVAL_SUCCESS_HOURS = 168  # 1 semaine = succès long terme
        self.MAX_FAILURE_HOURS = 6  # Mort en 6h = échec rapide
        
        # Seuils de blacklisting
        self.BLACKLIST_CONSECUTIVE_FAILURES = 5
        self.BLACKLIST_FAILURE_RATE_THRESHOLD = 0.8
        self.BLACKLIST_MIN_TOKENS_FOR_RATE = 5
        
        # Cache des analyses
        self._cache = {}
        self._cache_expiry = {}
        self._cache_ttl_minutes = 30
    
    def analyze_creator(self, creator_address: str, force_refresh: bool = False) -> CreatorPerformance:
        """
        Analyse complète des performances d'un créateur
        
        Args:
            creator_address: Adresse du créateur à analyser
            force_refresh: Forcer le recalcul même si en cache
            
        Returns:
            CreatorPerformance: Objet contenant toutes les métriques
        """
        # Vérifier le cache
        if not force_refresh and self._is_cached_valid(creator_address):
            logger.debug(f"Using cached analysis for creator {creator_address[:10]}...")
            return self._cache[creator_address]
        
        logger.info(f"🔍 Analyzing creator performance: {creator_address[:10]}...")
        
        # Récupérer les tokens du créateur
        tokens = self._get_creator_tokens(creator_address)
        
        if not tokens:
            logger.warning(f"No tokens found for creator {creator_address[:10]}...")
            return self._create_empty_performance(creator_address)
        
        # Analyser chaque token
        token_outcomes = []
        for token in tokens:
            outcome = self._analyze_token_outcome(token)
            token_outcomes.append(outcome)
        
        # Calculer les métriques globales
        performance = self._calculate_creator_metrics(creator_address, token_outcomes)
        
        # Mettre en cache
        self._cache[creator_address] = performance
        self._cache_expiry[creator_address] = datetime.now() + timedelta(minutes=self._cache_ttl_minutes)
        
        logger.info(f"✅ Creator analysis completed: {creator_address[:10]} - "
                   f"Score: {performance.reputation_score:.1f} - "
                   f"Success Rate: {performance.success_rate*100:.1f}%")
        
        return performance
    
    def _get_creator_tokens(self, creator_address: str) -> List[Dict[str, Any]]:
        """Récupère tous les tokens d'un créateur avec leurs données"""
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT 
                        pt.address,
                        pt.name,
                        pt.symbol,
                        pt.creator,
                        pt.created_at,
                        pt.usd_market_cap,
                        pt.bonding_curve_progress,
                        pt.virtual_sol_reserves,
                        pt.virtual_token_reserves,
                        pt.is_verified,
                        pt.nsfw,
                        pt.hidden,
                        to_ext.roi_24h,
                        to_ext.roi_7d,
                        to_ext.peak_market_cap,
                        to_ext.current_market_cap,
                        to_ext.survival_time_hours,
                        to_ext.is_rugged,
                        to_ext.final_status,
                        to_ext.outcome_type,
                        rr.score as rugcheck_score,
                        rr.is_rugged as rugcheck_rugged
                    FROM pump_tokens pt
                    LEFT JOIN token_outcomes_extended to_ext ON pt.address = to_ext.token_address
                    LEFT JOIN rugcheck_reports rr ON pt.address = rr.token_address
                    WHERE pt.creator = ?
                    ORDER BY pt.created_at ASC
                """, (creator_address,))
                
                return [dict(row) for row in cursor.fetchall()]
                
        except Exception as e:
            logger.error(f"Error fetching tokens for creator {creator_address}: {e}")
            return []
    
    def _analyze_token_outcome(self, token: Dict[str, Any]) -> TokenOutcome:
        """Analyse le résultat d'un token individuel"""
        
        # Calculer l'âge du token
        created_at = datetime.fromisoformat(token['created_at'])
        age_hours = (datetime.now() - created_at).total_seconds() / 3600
        
        # Utiliser les données existantes si disponibles
        if token.get('outcome_type') and token.get('roi_24h') is not None:
            outcome = token['outcome_type']
            roi_24h = token['roi_24h']
            survival_time = token.get('survival_time_hours', age_hours)
            is_rugged = token.get('is_rugged', False) or token.get('rugcheck_rugged', False)
        else:
            # Calculer l'outcome basé sur les données disponibles
            outcome, roi_24h, survival_time, is_rugged = self._calculate_token_outcome(token, age_hours)
        
        return TokenOutcome(
            address=token['address'],
            name=token.get('name'),
            symbol=token.get('symbol'),
            created_at=created_at,
            outcome=outcome,
            roi_24h=roi_24h,
            roi_7d=token.get('roi_7d', 0),
            peak_market_cap=token.get('peak_market_cap', 0) or 0,
            current_market_cap=token.get('current_market_cap', 0) or token.get('usd_market_cap', 0) or 0,
            survival_time_hours=survival_time,
            is_rugged=is_rugged,
            final_status=token.get('final_status', 'ACTIVE' if age_hours < 24 else 'UNKNOWN')
        )
    
    def _calculate_token_outcome(self, token: Dict[str, Any], age_hours: float) -> Tuple[str, float, float, bool]:
        """Calcule l'outcome d'un token basé sur plusieurs critères"""
        
        current_market_cap = token.get('usd_market_cap', 0) or 0
        bonding_progress = token.get('bonding_curve_progress', 0) or 0
        rugcheck_score = token.get('rugcheck_score', 50) or 50
        is_rugged = token.get('rugcheck_rugged', False) or False
        
        # Estimation du ROI basée sur les données disponibles
        roi_24h = 0.0
        if current_market_cap > 1000:  # Si market cap significative
            # Estimation simplifiée du ROI
            initial_market_cap = 30000  # Market cap initial estimé pour pump.fun
            roi_24h = (current_market_cap / initial_market_cap) - 1
        
        # Critères de succès (dans l'ordre de priorité)
        is_success = (
            bonding_progress >= 100.0 or  # Migration vers Raydium = succès garanti
            current_market_cap >= self.SUCCESS_MARKET_CAP_THRESHOLD or  # Gros market cap
            roi_24h >= self.SUCCESS_ROI_THRESHOLD or  # ROI élevé
            (age_hours >= self.MIN_SURVIVAL_SUCCESS_HOURS and current_market_cap >= 10000)  # Survie long terme
        )
        
        # Critères d'échec
        is_failure = (
            is_rugged or  # Token ruggé
            rugcheck_score >= 80 or  # Score rugcheck très mauvais
            roi_24h <= self.FAILURE_ROI_THRESHOLD or  # Grosse perte
            (age_hours >= 48 and current_market_cap <= self.FAILURE_MARKET_CAP_THRESHOLD) or  # Mort après 48h
            (age_hours >= self.MAX_FAILURE_HOURS and current_market_cap <= 100)  # Mort rapide
        )
        
        # Déterminer l'outcome
        if is_failure:
            outcome = 'FAILURE'
        elif is_success:
            outcome = 'SUCCESS'
        elif age_hours < 24:
            outcome = 'PENDING'  # Trop récent pour juger
        else:
            outcome = 'NEUTRAL'  # Ni succès ni échec
        
        survival_time = min(age_hours, 168)  # Cap à 1 semaine
        
        return outcome, roi_24h, survival_time, is_rugged
    
    def _calculate_creator_metrics(self, creator_address: str, outcomes: List[TokenOutcome]) -> CreatorPerformance:
        """Calcule toutes les métriques d'un créateur"""
        
        if not outcomes:
            return self._create_empty_performance(creator_address)
        
        # Compter les résultats par type
        success_count = sum(1 for o in outcomes if o.outcome == 'SUCCESS')
        failure_count = sum(1 for o in outcomes if o.outcome == 'FAILURE')
        neutral_count = sum(1 for o in outcomes if o.outcome == 'NEUTRAL')
        pending_count = sum(1 for o in outcomes if o.outcome == 'PENDING')
        total_count = len(outcomes)
        
        # Calculer les taux
        success_rate = success_count / total_count if total_count > 0 else 0
        failure_rate = failure_count / total_count if total_count > 0 else 0
        
        # Calculer les ROI
        rois = [o.roi_24h for o in outcomes if o.roi_24h is not None]
        avg_roi = sum(rois) / len(rois) if rois else 0
        median_roi = sorted(rois)[len(rois)//2] if rois else 0
        best_roi = max(rois) if rois else 0
        worst_roi = min(rois) if rois else 0
        
        # Temps de survie moyen
        survival_times = [o.survival_time_hours for o in outcomes if o.survival_time_hours > 0]
        avg_survival = sum(survival_times) / len(survival_times) if survival_times else 0
        
        # Analyser les échecs consécutifs
        consecutive_failures = self._calculate_consecutive_failures(outcomes)
        
        # Calculer le temps depuis le dernier succès
        days_since_last_success = self._calculate_days_since_last_success(outcomes)
        
        # Fréquence de lancement
        avg_time_between, frequency_category = self._calculate_launch_frequency(outcomes)
        
        # Calculer les scores
        reputation_score = self._calculate_reputation_score(outcomes, success_rate, avg_roi, avg_survival)
        risk_score = self._calculate_risk_score(outcomes, failure_rate, consecutive_failures, days_since_last_success)
        
        # Niveau de confiance
        confidence_level = self._determine_confidence_level(total_count, success_rate, reputation_score)
        
        # Blacklisting
        is_blacklisted, blacklist_reason = self._determine_blacklist_status(
            outcomes, failure_rate, consecutive_failures, total_count
        )
        
        # Dates
        first_date = min(o.created_at for o in outcomes) if outcomes else None
        last_date = max(o.created_at for o in outcomes) if outcomes else None
        
        return CreatorPerformance(
            creator_address=creator_address,
            total_tokens=total_count,
            successful_tokens=success_count,
            failed_tokens=failure_count,
            neutral_tokens=neutral_count,
            pending_tokens=pending_count,
            success_rate=success_rate,
            failure_rate=failure_rate,
            avg_roi=avg_roi,
            median_roi=median_roi,
            best_roi=best_roi,
            worst_roi=worst_roi,
            avg_survival_time=avg_survival,
            reputation_score=reputation_score,
            risk_score=risk_score,
            confidence_level=confidence_level,
            is_blacklisted=is_blacklisted,
            blacklist_reason=blacklist_reason,
            consecutive_failures=consecutive_failures,
            days_since_last_success=days_since_last_success,
            avg_time_between_launches=avg_time_between,
            launch_frequency_category=frequency_category,
            first_token_date=first_date,
            last_token_date=last_date
        )
    
    def _calculate_reputation_score(self, outcomes: List[TokenOutcome], success_rate: float, 
                                  avg_roi: float, avg_survival: float) -> float:
        """Calcule le score de réputation (0-100)"""
        
        base_score = 50.0
        
        # Bonus pour taux de succès (0-35 points)
        success_bonus = min(success_rate * 35, 35)
        
        # Bonus pour ROI moyen (0-25 points)
        roi_bonus = min(max(avg_roi * 5, 0), 25)
        
        # Bonus pour survie moyenne (0-15 points)
        survival_bonus = min(avg_survival / 24 * 15, 15)  # 15 points max pour 24h+ de survie moyenne
        
        # Bonus pour expérience (0-10 points)
        experience_bonus = min(len(outcomes) * 1, 10)
        
        # Bonus pour consistance (pas d'échecs consécutifs)
        consecutive_failures = self._calculate_consecutive_failures(outcomes)
        consistency_bonus = max(5 - consecutive_failures, -15)  # Peut être négatif
        
        # Pénalité pour tokens ruggés
        rugged_count = sum(1 for o in outcomes if o.is_rugged)
        rug_penalty = rugged_count * -20  # -20 par rug
        
        # Bonus pour récence d'activité
        if outcomes:
            last_token_age = (datetime.now() - max(o.created_at for o in outcomes)).days
            recency_bonus = max(5 - last_token_age/7, -5)  # Bonus si actif récemment
        else:
            recency_bonus = 0
        
        score = (base_score + success_bonus + roi_bonus + survival_bonus + 
                experience_bonus + consistency_bonus + rug_penalty + recency_bonus)
        
        return max(0, min(100, score))
    
    def _calculate_risk_score(self, outcomes: List[TokenOutcome], failure_rate: float, 
                            consecutive_failures: int, days_since_last_success: Optional[int]) -> float:
        """Calcule le score de risque (0-100, plus haut = plus risqué)"""
        
        base_risk = 30.0
        
        # Risque basé sur le taux d'échec
        failure_risk = failure_rate * 40  # 0-40 points
        
        # Risque pour échecs consécutifs
        consecutive_risk = min(consecutive_failures * 8, 30)  # 8 points par échec, max 30
        
        # Risque si pas de succès récent
        if days_since_last_success is not None:
            stale_success_risk = min(days_since_last_success / 30 * 15, 15)  # 15 points max
        else:
            stale_success_risk = 10  # Pas de succès du tout
        
        # Risque pour tokens ruggés
        rugged_count = sum(1 for o in outcomes if o.is_rugged)
        rug_risk = min(rugged_count * 15, 25)  # 15 points par rug, max 25
        
        # Réduction pour expérience positive
        if len(outcomes) >= 5 and failure_rate < 0.3:
            experience_reduction = min(len(outcomes), 15)
        else:
            experience_reduction = 0
        
        # Risque pour fréquence de lancement élevée (pump and dump pattern)
        avg_time_between, _ = self._calculate_launch_frequency(outcomes)
        if avg_time_between < 24:  # Moins de 24h entre tokens
            spam_risk = 15
        elif avg_time_between < 72:  # Moins de 3 jours
            spam_risk = 5
        else:
            spam_risk = 0
        
        risk = (base_risk + failure_risk + consecutive_risk + stale_success_risk + 
               rug_risk + spam_risk - experience_reduction)
        
        return max(0, min(100, risk))
    
    def _calculate_consecutive_failures(self, outcomes: List[TokenOutcome]) -> int:
        """Calcule le nombre d'échecs consécutifs depuis la fin"""
        if not outcomes:
            return 0
        
        # Trier par date de création (plus récent en premier)
        sorted_outcomes = sorted(outcomes, key=lambda x: x.created_at, reverse=True)
        
        consecutive = 0
        for outcome in sorted_outcomes:
            if outcome.outcome == 'FAILURE':
                consecutive += 1
            elif outcome.outcome == 'SUCCESS':
                break  # Arrêter au premier succès
            # Ignorer NEUTRAL et PENDING pour le calcul
        
        return consecutive
    
    def _calculate_days_since_last_success(self, outcomes: List[TokenOutcome]) -> Optional[int]:
        """Calcule le nombre de jours depuis le dernier succès"""
        success_dates = [o.created_at for o in outcomes if o.outcome == 'SUCCESS']
        
        if not success_dates:
            return None
        
        last_success = max(success_dates)
        return (datetime.now() - last_success).days
    
    def _calculate_launch_frequency(self, outcomes: List[TokenOutcome]) -> Tuple[float, str]:
        """Calcule la fréquence de lancement moyenne"""
        if len(outcomes) < 2:
            return 0.0, 'INSUFFICIENT_DATA'
        
        # Trier par date
        sorted_outcomes = sorted(outcomes, key=lambda x: x.created_at)
        
        # Calculer les intervalles entre tokens
        intervals = []
        for i in range(1, len(sorted_outcomes)):
            prev_date = sorted_outcomes[i-1].created_at
            curr_date = sorted_outcomes[i].created_at
            interval_hours = (curr_date - prev_date).total_seconds() / 3600
            intervals.append(interval_hours)
        
        avg_hours = sum(intervals) / len(intervals)
        
        # Catégoriser la fréquence
        if avg_hours < 24:
            category = 'VERY_HIGH'  # Plus d'un token par jour (suspect)
        elif avg_hours < 72:
            category = 'HIGH'  # Un token tous les 1-3 jours
        elif avg_hours < 168:
            category = 'MEDIUM'  # Un token par semaine
        elif avg_hours < 720:
            category = 'LOW'  # Un token par mois
        else:
            category = 'VERY_LOW'  # Moins d'un token par mois
        
        return avg_hours, category
    
    def _determine_confidence_level(self, total_tokens: int, success_rate: float, reputation_score: float) -> str:
        """Détermine le niveau de confiance dans l'analyse"""
        if total_tokens < 3:
            return 'INSUFFICIENT_DATA'
        elif total_tokens >= 10 and reputation_score >= 70 and success_rate >= 0.5:
            return 'HIGH_CONFIDENCE'
        elif total_tokens >= 5 and reputation_score >= 50 and success_rate >= 0.3:
            return 'MEDIUM_CONFIDENCE'
        elif total_tokens >= 3:
            return 'LOW_CONFIDENCE'
        else:
            return 'NO_CONFIDENCE'
    
    def _determine_blacklist_status(self, outcomes: List[TokenOutcome], failure_rate: float, 
                                  consecutive_failures: int, total_tokens: int) -> Tuple[bool, Optional[str]]:
        """Détermine si un créateur doit être blacklisté"""
        
        # Règle 1: Trop d'échecs consécutifs
        if consecutive_failures >= self.BLACKLIST_CONSECUTIVE_FAILURES:
            return True, f"{consecutive_failures} échecs consécutifs"
        
        # Règle 2: Taux d'échec trop élevé avec assez de données
        if total_tokens >= self.BLACKLIST_MIN_TOKENS_FOR_RATE and failure_rate >= self.BLACKLIST_FAILURE_RATE_THRESHOLD:
            return True, f"Taux d'échec {failure_rate*100:.1f}% sur {total_tokens} tokens"
        
        # Règle 3: Tokens ruggés multiples
        rugged_count = sum(1 for o in outcomes if o.is_rugged)
        if rugged_count >= 2:
            return True, f"{rugged_count} tokens ruggés détectés"
        
        # Règle 4: Pattern suspect - beaucoup de tokens rapprochés tous en échec
        if total_tokens >= 5:
            recent_outcomes = sorted(outcomes, key=lambda x: x.created_at, reverse=True)[:5]
            recent_failures = sum(1 for o in recent_outcomes if o.outcome == 'FAILURE')
            if recent_failures >= 4:
                return True, f"{recent_failures}/5 derniers tokens en échec"
        
        # Règle 5: Activité suspecte (trop de tokens en peu de temps)
        avg_time_between, frequency_category = self._calculate_launch_frequency(outcomes)
        if frequency_category == 'VERY_HIGH' and failure_rate >= 0.6:
            return True, f"Lancement suspect: {frequency_category.lower()} frequency + {failure_rate*100:.1f}% failures"
        
        return False, None
    
    def _create_empty_performance(self, creator_address: str) -> CreatorPerformance:
        """Crée un objet CreatorPerformance vide pour les créateurs sans tokens"""
        return CreatorPerformance(
            creator_address=creator_address,
            total_tokens=0,
            successful_tokens=0,
            failed_tokens=0,
            neutral_tokens=0,
            pending_tokens=0,
            success_rate=0.0,
            failure_rate=0.0,
            avg_roi=0.0,
            median_roi=0.0,
            best_roi=0.0,
            worst_roi=0.0,
            avg_survival_time=0.0,
            reputation_score=50.0,  # Score neutre par défaut
            risk_score=50.0,
            confidence_level='INSUFFICIENT_DATA',
            is_blacklisted=False,
            blacklist_reason=None,
            consecutive_failures=0,
            days_since_last_success=None,
            avg_time_between_launches=0.0,
            launch_frequency_category='INSUFFICIENT_DATA',
            first_token_date=None,
            last_token_date=None
        )
    
    def _is_cached_valid(self, creator_address: str) -> bool:
        """Vérifie si le cache est encore valide"""
        if creator_address not in self._cache:
            return False
        
        expiry = self._cache_expiry.get(creator_address)
        if not expiry or datetime.now() > expiry:
            return False
        
        return True
    
    def update_creator_in_database(self, performance: CreatorPerformance) -> bool:
        """Met à jour ou insère les données d'un créateur en base"""
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO creator_performance (
                        creator_address, total_tokens_created, successful_tokens, failed_tokens,
                        neutral_tokens, avg_roi, avg_peak_market_cap, avg_survival_time_hours,
                        success_rate, failure_rate, risk_score, reputation_score, confidence_level,
                        is_blacklisted, blacklist_reason, consecutive_failures, best_token_roi,
                        worst_token_roi, avg_time_between_launches_hours, first_token_date,
                        last_token_date, last_updated
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    performance.creator_address, performance.total_tokens, performance.successful_tokens,
                    performance.failed_tokens, performance.neutral_tokens, performance.avg_roi,
                    0,  # avg_peak_market_cap à calculer
                    performance.avg_survival_time, performance.success_rate, performance.failure_rate,
                    performance.risk_score, performance.reputation_score, performance.confidence_level,
                    performance.is_blacklisted, performance.blacklist_reason, performance.consecutive_failures,
                    performance.best_roi, performance.worst_roi, performance.avg_time_between_launches,
                    performance.first_token_date.isoformat() if performance.first_token_date else None,
                    performance.last_token_date.isoformat() if performance.last_token_date else None,
                    datetime.now().isoformat()
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"Error updating creator {performance.creator_address} in database: {e}")
            return False
    
    def get_top_creators(self, limit: int = 10, min_tokens: int = 3) -> List[CreatorPerformance]:
        """Récupère les meilleurs créateurs"""
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT creator_address
                    FROM creator_performance
                    WHERE total_tokens_created >= ? AND is_blacklisted = FALSE
                    ORDER BY reputation_score DESC, success_rate DESC
                    LIMIT ?
                """, (min_tokens, limit))
                
                creator_addresses = [row['creator_address'] for row in cursor.fetchall()]
                
                return [self.analyze_creator(addr) for addr in creator_addresses]
                
        except Exception as e:
            logger.error(f"Error getting top creators: {e}")
            return []
    
    def get_blacklisted_creators(self) -> List[CreatorPerformance]:
        """Récupère tous les créateurs blacklistés"""
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT creator_address
                    FROM creator_performance
                    WHERE is_blacklisted = TRUE
                    ORDER BY last_updated DESC
                """)
                
                creator_addresses = [row['creator_address'] for row in cursor.fetchall()]
                
                return [self.analyze_creator(addr) for addr in creator_addresses]
                
        except Exception as e:
            logger.error(f"Error getting blacklisted creators: {e}")
            return []
    
    def analyze_token_with_creator_context(self, token_address: str) -> Dict[str, Any]:
        """Analyse un token avec le contexte de son créateur"""
        try:
            # Récupérer les infos du token
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM pump_tokens WHERE address = ?", (token_address,))
                token = cursor.fetchone()
                
                if not token:
                    return {"error": "Token not found"}
                
                token = dict(token)
            
            # Analyser le créateur
            creator_performance = self.analyze_creator(token['creator'])
            
            # Calculer le score du token basé sur le créateur
            token_score = self._calculate_token_score_from_creator(token, creator_performance)
            
            return {
                "token": token,
                "creator_performance": creator_performance,
                "token_score": token_score,
                "recommendation": self._get_token_recommendation(token_score, creator_performance)
            }
            
        except Exception as e:
            logger.error(f"Error analyzing token {token_address} with creator context: {e}")
            return {"error": str(e)}
    
    def _calculate_token_score_from_creator(self, token: Dict[str, Any], creator_performance: CreatorPerformance) -> float:
        """Calcule un score pour un token basé sur les performances de son créateur"""
        
        base_score = 50.0
        
        # Score basé sur la réputation du créateur (0-40 points)
        creator_score_factor = creator_performance.reputation_score / 100
        creator_bonus = creator_score_factor * 40
        
        # Bonus/Malus basé sur le risque (0 à -30 points)
        risk_factor = creator_performance.risk_score / 100
        risk_penalty = risk_factor * -30
        
        # Bonus pour créateurs expérimentés (0-10 points)
        experience_bonus = min(creator_performance.total_tokens * 2, 10)
        
        # Malus pour créateurs blacklistés (-50 points)
        blacklist_penalty = -50 if creator_performance.is_blacklisted else 0
        
        # Bonus pour créateurs avec succès récents (0-15 points)
        if creator_performance.days_since_last_success is not None:
            if creator_performance.days_since_last_success <= 7:
                recent_success_bonus = 15
            elif creator_performance.days_since_last_success <= 30:
                recent_success_bonus = 10
            elif creator_performance.days_since_last_success <= 90:
                recent_success_bonus = 5
            else:
                recent_success_bonus = 0
        else:
            recent_success_bonus = 0
        
        # Malus pour échecs consécutifs (-5 points par échec)
        consecutive_penalty = creator_performance.consecutive_failures * -5
        
        # Bonus pour fréquence de lancement raisonnable
        if creator_performance.launch_frequency_category in ['LOW', 'MEDIUM']:
            frequency_bonus = 5
        elif creator_performance.launch_frequency_category == 'VERY_HIGH':
            frequency_bonus = -10  # Suspect
        else:
            frequency_bonus = 0
        
        total_score = (base_score + creator_bonus + risk_penalty + experience_bonus + 
                      blacklist_penalty + recent_success_bonus + consecutive_penalty + frequency_bonus)
        
        return max(0, min(100, total_score))
    
    def _get_token_recommendation(self, token_score: float, creator_performance: CreatorPerformance) -> Dict[str, Any]:
        """Génère une recommandation d'achat pour un token"""
        
        if creator_performance.is_blacklisted:
            return {
                "decision": "AVOID",
                "confidence": "HIGH",
                "reason": f"Créateur blacklisté: {creator_performance.blacklist_reason}",
                "score": token_score,
                "color": "red"
            }
        
        if token_score >= 80:
            return {
                "decision": "STRONG_BUY",
                "confidence": "HIGH",
                "reason": f"Créateur excellent (score: {creator_performance.reputation_score:.1f}, succès: {creator_performance.success_rate*100:.1f}%)",
                "score": token_score,
                "color": "green"
            }
        elif token_score >= 65:
            return {
                "decision": "BUY",
                "confidence": "MEDIUM",
                "reason": f"Créateur fiable (score: {creator_performance.reputation_score:.1f}, succès: {creator_performance.success_rate*100:.1f}%)",
                "score": token_score,
                "color": "lightgreen"
            }
        elif token_score >= 45:
            return {
                "decision": "WATCH",
                "confidence": "LOW",
                "reason": f"Créateur moyen (score: {creator_performance.reputation_score:.1f}, risque: {creator_performance.risk_score:.1f})",
                "score": token_score,
                "color": "yellow"
            }
        else:
            return {
                "decision": "AVOID",
                "confidence": "MEDIUM",
                "reason": f"Créateur risqué (score: {creator_performance.reputation_score:.1f}, échecs: {creator_performance.consecutive_failures})",
                "score": token_score,
                "color": "orange"
            }
    
    def bulk_update_creators(self, creator_addresses: List[str] = None) -> Dict[str, Any]:
        """Met à jour en masse les performances des créateurs"""
        
        if creator_addresses is None:
            # Récupérer tous les créateurs de la base
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT DISTINCT creator FROM pump_tokens")
                creator_addresses = [row['creator'] for row in cursor.fetchall()]
        
        results = {
            "total_creators": len(creator_addresses),
            "updated": 0,
            "blacklisted": 0,
            "errors": 0,
            "top_creators": [],
            "newly_blacklisted": []
        }
        
        logger.info(f"🔄 Starting bulk update for {len(creator_addresses)} creators...")
        
        for i, creator_address in enumerate(creator_addresses, 1):
            try:
                # Analyser le créateur
                performance = self.analyze_creator(creator_address, force_refresh=True)
                
                # Mettre à jour en base
                if self.update_creator_in_database(performance):
                    results["updated"] += 1
                    
                    if performance.is_blacklisted:
                        results["blacklisted"] += 1
                        results["newly_blacklisted"].append({
                            "address": creator_address,
                            "reason": performance.blacklist_reason,
                            "consecutive_failures": performance.consecutive_failures
                        })
                    
                    # Collecter les top créateurs
                    if performance.reputation_score >= 70 and performance.total_tokens >= 3:
                        results["top_creators"].append({
                            "address": creator_address,
                            "reputation_score": performance.reputation_score,
                            "success_rate": performance.success_rate,
                            "total_tokens": performance.total_tokens
                        })
                
                # Log du progrès
                if i % 10 == 0:
                    logger.info(f"Progress: {i}/{len(creator_addresses)} creators processed")
                    
            except Exception as e:
                logger.error(f"Error updating creator {creator_address}: {e}")
                results["errors"] += 1
        
        # Trier les top créateurs
        results["top_creators"].sort(key=lambda x: x["reputation_score"], reverse=True)
        results["top_creators"] = results["top_creators"][:10]
        
        logger.info(f"✅ Bulk update completed: {results['updated']}/{results['total_creators']} updated, "
                   f"{results['blacklisted']} blacklisted, {results['errors']} errors")
        
        return results
    
    def get_creator_risk_alert(self, creator_address: str) -> Optional[Dict[str, Any]]:
        """Génère une alerte de risque pour un créateur"""
        
        performance = self.analyze_creator(creator_address)
        
        alerts = []
        
        # Alerte échecs consécutifs
        if performance.consecutive_failures >= 3:
            alerts.append({
                "type": "CONSECUTIVE_FAILURES",
                "level": "HIGH" if performance.consecutive_failures >= 5 else "MEDIUM",
                "message": f"{performance.consecutive_failures} échecs consécutifs",
                "recommendation": "Éviter ce créateur"
            })
        
        # Alerte taux d'échec élevé
        if performance.failure_rate >= 0.7 and performance.total_tokens >= 5:
            alerts.append({
                "type": "HIGH_FAILURE_RATE",
                "level": "HIGH",
                "message": f"Taux d'échec de {performance.failure_rate*100:.1f}%",
                "recommendation": "Créateur très risqué"
            })
        
        # Alerte lancement suspect
        if performance.launch_frequency_category == 'VERY_HIGH' and performance.failure_rate >= 0.5:
            alerts.append({
                "type": "SUSPICIOUS_ACTIVITY",
                "level": "HIGH",
                "message": f"Lancement très fréquent + échecs fréquents",
                "recommendation": "Pattern de pump & dump possible"
            })
        
        # Alerte pas de succès récent
        if (performance.days_since_last_success and 
            performance.days_since_last_success >= 90 and 
            performance.total_tokens >= 3):
            alerts.append({
                "type": "NO_RECENT_SUCCESS",
                "level": "MEDIUM",
                "message": f"Pas de succès depuis {performance.days_since_last_success} jours",
                "recommendation": "Créateur en déclin"
            })
        
        if not alerts:
            return None
        
        return {
            "creator_address": creator_address,
            "alerts": alerts,
            "overall_risk_level": "HIGH" if any(a["level"] == "HIGH" for a in alerts) else "MEDIUM",
            "is_blacklisted": performance.is_blacklisted,
            "reputation_score": performance.reputation_score,
            "risk_score": performance.risk_score
        }
    
    def clear_cache(self):
        """Vide le cache des analyses"""
        self._cache.clear()
        self._cache_expiry.clear()
        logger.info("Creator analyzer cache cleared")

# Instance globale
creator_analyzer = CreatorAnalyzer()