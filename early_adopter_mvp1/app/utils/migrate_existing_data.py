import sys
import os
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Tuple

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CreatorDataMigrator:
    def __init__(self):
        self.creator_stats = defaultdict(lambda: {
            'tokens': [],
            'total_tokens': 0,
            'successful_tokens': 0,
            'failed_tokens': 0,
            'neutral_tokens': 0,
            'total_roi': 0.0,
            'rois': [],
            'market_caps': [],
            'survival_times': [],
            'first_token_date': None,
            'last_token_date': None,
            'consecutive_failures': 0,
            'last_outcome': None
        })
    
    def scan_existing_tokens(self):
        """Scanner tous les tokens existants en base"""
        logger.info("🔍 Scanning existing tokens...")
        
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Récupérer tous les tokens avec leurs données
            cursor.execute("""
                SELECT 
                    pt.address,
                    pt.name,
                    pt.symbol,
                    pt.creator,
                    pt.created_at,
                    pt.market_cap_discovery,
                    pt.usd_market_cap,
                    pt.bonding_curve_progress,
                    to1.roi_24h,
                    to1.roi_7d,
                    to1.peak_market_cap,
                    to1.outcome_type
                FROM pump_tokens pt
                LEFT JOIN token_outcomes to1 ON pt.address = to1.token_address
                ORDER BY pt.creator, pt.created_at
            """)
            
            tokens = cursor.fetchall()
            logger.info(f"📊 Found {len(tokens)} tokens to1 analyze")
            
            return [dict(token) for token in tokens]
    
    def calculate_token_outcome(self, token: Dict) -> Tuple[str, float, float]:
        """Calculer le résultat d'un token (SUCCESS/FAILURE/NEUTRAL)"""
        
        # Si on a déjà un outcome type, l'utiliser
        if token.get('outcome_type'):
            outcome = token['outcome_type']
            roi = token.get('roi_24h', 0) or 0
            return outcome, roi, token.get('peak_market_cap', 0) or 0
        
        # Sinon, calculer basé sur les données disponibles
        roi_24h = token.get('roi_24h', 0) or 0
        market_cap = token.get('usd_market_cap', 0) or 0
        bonding_progress = token.get('bonding_curve_progress', 0) or 0
        
        # Calculer l'âge du token
        created_at = datetime.fromisoformat(token['created_at'])
        age_hours = (datetime.now() - created_at).total_seconds() / 3600
        
        # Critères de succès/échec
        is_success = (
            roi_24h >= 5.0 or  # ROI > 5x
            market_cap >= 100000 or  # Market cap > $100k
            bonding_progress >= 80.0 or  # Proche de migration
            (age_hours >= 168 and market_cap >= 10000)  # Survie 1 semaine + $10k
        )
        
        is_failure = (
            roi_24h <= -0.5 or  # Perte > 50%
            (age_hours >= 48 and market_cap <= 1000) or  # 2 jours + mort
            (age_hours >= 6 and market_cap <= 100)  # 6h + vraiment mort
        )
        
        if is_success:
            outcome = 'SUCCESS'
        elif is_failure:
            outcome = 'FAILURE'
        else:
            outcome = 'NEUTRAL'
        
        survival_hours = min(age_hours, 168)  # Cap à 1 semaine
        
        return outcome, roi_24h, survival_hours
    
    def analyze_creator_patterns(self, creator_address: str, tokens: List[Dict]):
        """Analyser les patterns d'un créateur"""
        stats = self.creator_stats[creator_address]
        
        # Trier par date de création
        tokens.sort(key=lambda x: x['created_at'])
        
        consecutive_failures = 0
        last_outcome = None
        
        for token in tokens:
            outcome, roi, survival_time = self.calculate_token_outcome(token)
            
            stats['tokens'].append({
                'address': token['address'],
                'name': token.get('name'),
                'symbol': token.get('symbol'),
                'created_at': token['created_at'],
                'outcome': outcome,
                'roi': roi,
                'survival_time': survival_time
            })
            
            # Compter les résultats
            if outcome == 'SUCCESS':
                stats['successful_tokens'] += 1
                consecutive_failures = 0
            elif outcome == 'FAILURE':
                stats['failed_tokens'] += 1
                consecutive_failures += 1
            else:
                stats['neutral_tokens'] += 1
            
            # Accumuler les données
            stats['rois'].append(roi)
            stats['survival_times'].append(survival_time)
            
            if token.get('usd_market_cap'):
                stats['market_caps'].append(token['usd_market_cap'])
            
            last_outcome = outcome
        
        stats['total_tokens'] = len(tokens)
        stats['consecutive_failures'] = consecutive_failures
        stats['last_outcome'] = last_outcome
        stats['first_token_date'] = tokens[0]['created_at'] if tokens else None
        stats['last_token_date'] = tokens[-1]['created_at'] if tokens else None
    
    def calculate_creator_scores(self, creator_address: str) -> Dict:
        """Calculer tous les scores d'un créateur"""
        stats = self.creator_stats[creator_address]
        
        if stats['total_tokens'] == 0:
            return self._default_scores()
        
        # Taux de succès/échec
        success_rate = stats['successful_tokens'] / stats['total_tokens']
        failure_rate = stats['failed_tokens'] / stats['total_tokens']
        
        # ROI moyen
        avg_roi = sum(stats['rois']) / len(stats['rois']) if stats['rois'] else 0
        best_roi = max(stats['rois']) if stats['rois'] else 0
        worst_roi = min(stats['rois']) if stats['rois'] else 0
        
        # Market cap moyen
        avg_market_cap = sum(stats['market_caps']) / len(stats['market_caps']) if stats['market_caps'] else 0
        
        # Temps de survie moyen
        avg_survival = sum(stats['survival_times']) / len(stats['survival_times']) if stats['survival_times'] else 0
        
        # Calcul du score de réputation (0-100)
        reputation_score = self._calculate_reputation_score(stats, success_rate, avg_roi)
        
        # Calcul du score de risque (0-100, plus haut = plus risqué)
        risk_score = self._calculate_risk_score(stats, failure_rate, stats['consecutive_failures'])
        
        # Niveau de confiance
        confidence_level = self._determine_confidence_level(stats['total_tokens'], success_rate, reputation_score)
        
        # Blacklist automatique
        is_blacklisted, blacklist_reason = self._should_blacklist(stats, failure_rate, stats['consecutive_failures'])
        
        # Temps entre lancements
        avg_time_between = self._calculate_avg_time_between_launches(stats['tokens'])
        
        return {
            'creator_address': creator_address,
            'total_tokens_created': stats['total_tokens'],
            'successful_tokens': stats['successful_tokens'],
            'failed_tokens': stats['failed_tokens'],
            'neutral_tokens': stats['neutral_tokens'],
            'avg_roi': round(avg_roi, 4),
            'avg_peak_market_cap': round(avg_market_cap, 2),
            'avg_survival_time_hours': round(avg_survival, 2),
            'success_rate': round(success_rate, 4),
            'failure_rate': round(failure_rate, 4),
            'risk_score': round(risk_score, 2),
            'reputation_score': round(reputation_score, 2),
            'confidence_level': confidence_level,
            'is_blacklisted': is_blacklisted,
            'blacklist_reason': blacklist_reason,
            'consecutive_failures': stats['consecutive_failures'],
            'best_token_roi': round(best_roi, 4),
            'worst_token_roi': round(worst_roi, 4),
            'avg_time_between_launches_hours': round(avg_time_between, 2),
            'first_token_date': stats['first_token_date'],
            'last_token_date': stats['last_token_date']
        }
    
    def _calculate_reputation_score(self, stats: Dict, success_rate: float, avg_roi: float) -> float:
        """Calculer le score de réputation (0-100)"""
        base_score = 50.0
        
        # Bonus pour taux de succès
        success_bonus = success_rate * 40  # Max 40 points
        
        # Bonus pour ROI moyen
        roi_bonus = min(avg_roi * 2, 20) if avg_roi > 0 else 0  # Max 20 points
        
        # Bonus pour volume de tokens (expérience)
        volume_bonus = min(stats['total_tokens'] * 2, 10)  # Max 10 points
        
        # Pénalités
        failure_penalty = stats['failed_tokens'] * -5  # -5 par échec
        consecutive_penalty = stats['consecutive_failures'] * -10  # -10 par échec consécutif
        
        score = base_score + success_bonus + roi_bonus + volume_bonus + failure_penalty + consecutive_penalty
        
        return max(0, min(100, score))
    
    def _calculate_risk_score(self, stats: Dict, failure_rate: float, consecutive_failures: int) -> float:
        """Calculer le score de risque (0-100, plus haut = plus risqué)"""
        base_risk = 30.0
        
        # Augmentation pour taux d'échec
        failure_risk = failure_rate * 50  # Max 50 points
        
        # Augmentation pour échecs consécutifs
        consecutive_risk = consecutive_failures * 15  # 15 par échec consécutif
        
        # Diminution pour expérience (plus de tokens = moins risqué si bon track record)
        if stats['total_tokens'] >= 5 and failure_rate < 0.3:
            experience_reduction = min(stats['total_tokens'], 15)
        else:
            experience_reduction = 0
        
        # Augmentation si dernier token était un échec
        recent_failure_risk = 20 if stats['last_outcome'] == 'FAILURE' else 0
        
        risk = base_risk + failure_risk + consecutive_risk + recent_failure_risk - experience_reduction
        
        return max(0, min(100, risk))
    
    def _determine_confidence_level(self, total_tokens: int, success_rate: float, reputation_score: float) -> str:
        """Déterminer le niveau de confiance"""
        if total_tokens < 3:
            return 'INSUFFICIENT_DATA'
        elif reputation_score >= 80 and success_rate >= 0.6:
            return 'HIGH_CONFIDENCE'
        elif reputation_score >= 60 and success_rate >= 0.4:
            return 'MEDIUM_CONFIDENCE'
        elif reputation_score >= 40:
            return 'LOW_CONFIDENCE'
        else:
            return 'NO_CONFIDENCE'
    
    def _should_blacklist(self, stats: Dict, failure_rate: float, consecutive_failures: int) -> Tuple[bool, str]:
        """Déterminer si le créateur doit être blacklisté"""
        
        # Règles de blacklist
        if consecutive_failures >= 5:
            return True, f"5+ échecs consécutifs ({consecutive_failures})"
        
        if stats['total_tokens'] >= 5 and failure_rate >= 0.8:
            return True, f"Taux d'échec trop élevé: {failure_rate*100:.1f}%"
        
        if stats['total_tokens'] >= 10 and failure_rate >= 0.7:
            return True, f"Pattern d'échecs répétés: {failure_rate*100:.1f}%"
        
        # Vérifier les tokens récents (3 derniers)
        recent_tokens = stats['tokens'][-3:] if len(stats['tokens']) >= 3 else []
        recent_failures = sum(1 for t in recent_tokens if t['outcome'] == 'FAILURE')
        
        if len(recent_tokens) == 3 and recent_failures == 3:
            return True, "3 derniers tokens tous en échec"
        
        return False, None
    
    def _calculate_avg_time_between_launches(self, tokens: List[Dict]) -> float:
        """Calculer le temps moyen entre les lancements"""
        if len(tokens) < 2:
            return 0.0
        
        time_diffs = []
        for i in range(1, len(tokens)):
            prev_date = datetime.fromisoformat(tokens[i-1]['created_at'])
            curr_date = datetime.fromisoformat(tokens[i]['created_at'])
            diff_hours = (curr_date - prev_date).total_seconds() / 3600
            time_diffs.append(diff_hours)
        
        return sum(time_diffs) / len(time_diffs)
    
    def _default_scores(self) -> Dict:
        """Scores par défaut pour créateurs sans tokens"""
        return {
            'total_tokens_created': 0,
            'successful_tokens': 0,
            'failed_tokens': 0,
            'neutral_tokens': 0,
            'avg_roi': 0.0,
            'avg_peak_market_cap': 0.0,
            'avg_survival_time_hours': 0.0,
            'success_rate': 0.0,
            'failure_rate': 0.0,
            'risk_score': 50.0,
            'reputation_score': 50.0,
            'confidence_level': 'UNKNOWN',
            'is_blacklisted': False,
            'blacklist_reason': None,
            'consecutive_failures': 0,
            'best_token_roi': 0.0,
            'worst_token_roi': 0.0,
            'avg_time_between_launches_hours': 0.0,
            'first_token_date': None,
            'last_token_date': None
        }
    
    def populate_creator_performance_table(self, creator_scores: List[Dict]):
        """Peupler la table creator_performance"""
        logger.info(f"💾 Populating creator_performance table with {len(creator_scores)} creators...")
        
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            for scores in creator_scores:
                cursor.execute("""
                    INSERT OR REPLACE INTO creator_performance (
                        creator_address, total_tokens_created, successful_tokens, failed_tokens,
                        neutral_tokens, avg_roi, avg_peak_market_cap, avg_survival_time_hours,
                        success_rate, failure_rate, risk_score, reputation_score, confidence_level,
                        is_blacklisted, blacklist_reason, consecutive_failures, best_token_roi,
                        worst_token_roi, avg_time_between_launches_hours, first_token_date,
                        last_token_date, created_at, last_updated
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    scores['creator_address'], scores['total_tokens_created'], 
                    scores['successful_tokens'], scores['failed_tokens'], scores['neutral_tokens'],
                    scores['avg_roi'], scores['avg_peak_market_cap'], scores['avg_survival_time_hours'],
                    scores['success_rate'], scores['failure_rate'], scores['risk_score'], 
                    scores['reputation_score'], scores['confidence_level'], scores['is_blacklisted'],
                    scores['blacklist_reason'], scores['consecutive_failures'], scores['best_token_roi'],
                    scores['worst_token_roi'], scores['avg_time_between_launches_hours'],
                    scores['first_token_date'], scores['last_token_date'],
                    datetime.now().isoformat(), datetime.now().isoformat()
                ))
            
            conn.commit()
            logger.info("✅ Creator performance table populated successfully!")
    
    def populate_creator_token_history(self):
        """Peupler la table creator_token_history"""
        logger.info("💾 Populating creator_token_history table...")
        
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            for creator_address, stats in self.creator_stats.items():
                for token in stats['tokens']:
                    cursor.execute("""
                        INSERT OR REPLACE INTO creator_token_history (
                            creator_address, token_address, token_name, token_symbol,
                            launch_date, outcome_type, roi_24h, peak_market_cap,
                            survival_time_hours, is_success, contributed_to_blacklist
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        creator_address, token['address'], token['name'], token['symbol'],
                        token['created_at'], token['outcome'], token['roi'], 0,  # peak_market_cap à calculer
                        token['survival_time'], token['outcome'] == 'SUCCESS',
                        token['outcome'] == 'FAILURE'
                    ))
            
            conn.commit()
            logger.info("✅ Creator token history populated successfully!")
    
    def update_pump_tokens_with_creator_data(self):
        """Mettre à jour pump_tokens avec les données créateur"""
        logger.info("🔄 Updating pump_tokens with creator data...")
        
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Mettre à jour chaque token avec les infos de son créateur
            cursor.execute("""
                UPDATE pump_tokens 
                SET 
                    creator_reputation_score = cp.reputation_score,
                    creator_risk_score = cp.risk_score,
                    creator_is_blacklisted = cp.is_blacklisted,
                    creator_total_previous_tokens = cp.total_tokens_created,
                    creator_success_rate = cp.success_rate
                FROM creator_performance cp
                WHERE pump_tokens.creator = cp.creator_address
            """)
            
            conn.commit()
            logger.info("✅ pump_tokens updated with creator data!")

def run_migration():
    """Exécuter la migration complète des données"""
    logger.info("🚀 Starting creator performance data migration...")
    
    migrator = CreatorDataMigrator()
    
    # 1. Scanner tous les tokens
    tokens = migrator.scan_existing_tokens()
    
    # 2. Grouper par créateur
    creator_tokens = defaultdict(list)
    for token in tokens:
        creator_tokens[token['creator']].append(token)
    
    logger.info(f"📊 Found {len(creator_tokens)} unique creators")
    
    # 3. Analyser chaque créateur
    creator_scores = []
    blacklisted_count = 0
    
    for creator_address, creator_token_list in creator_tokens.items():
        logger.info(f"🔍 Analyzing creator {creator_address[:10]}... ({len(creator_token_list)} tokens)")
        
        migrator.analyze_creator_patterns(creator_address, creator_token_list)
        scores = migrator.calculate_creator_scores(creator_address)
        creator_scores.append(scores)
        
        if scores['is_blacklisted']:
            blacklisted_count += 1
            logger.warning(f"🚨 Creator {creator_address[:10]}... BLACKLISTED: {scores['blacklist_reason']}")
    
    # 4. Peupler les tables
    migrator.populate_creator_performance_table(creator_scores)
    migrator.populate_creator_token_history()
    migrator.update_pump_tokens_with_creator_data()
    
    # 5. Statistiques finales
    logger.info("📈 Migration Statistics:")
    logger.info(f"   • Total creators analyzed: {len(creator_scores)}")
    logger.info(f"   • Blacklisted creators: {blacklisted_count}")
    logger.info(f"   • Total tokens processed: {len(tokens)}")
    
    # Top/Bottom créateurs
    sorted_creators = sorted(creator_scores, key=lambda x: x['reputation_score'], reverse=True)
    
    logger.info("🏆 Top 5 Creators by Reputation:")
    for i, creator in enumerate(sorted_creators[:5], 1):
        logger.info(f"   {i}. {creator['creator_address'][:10]}... - Score: {creator['reputation_score']:.1f} - Success Rate: {creator['success_rate']*100:.1f}%")
    
    logger.info("💀 Bottom 5 Creators by Reputation:")
    for i, creator in enumerate(sorted_creators[-5:], 1):
        logger.info(f"   {i}. {creator['creator_address'][:10]}... - Score: {creator['reputation_score']:.1f} - Success Rate: {creator['success_rate']*100:.1f}%")
    
    logger.info("✅ Creator performance data migration completed successfully!")

if __name__ == "__main__":
    run_migration()