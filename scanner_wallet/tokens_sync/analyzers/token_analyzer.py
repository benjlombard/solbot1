"""
Token Analyzer
Comprehensive analysis of tokens including viability scoring, risk assessment, and dead token detection.
"""
import time
import logging
import math
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from ..models.token_data import TokenData


class TokenHealth(Enum):
    """Token health status enumeration"""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    DEAD = "dead"
    UNKNOWN = "unknown"


class DeathReason(Enum):
    """Reasons why a token might be considered dead"""
    NO_LIQUIDITY = "no_liquidity"
    NO_VOLUME = "no_volume"
    NO_HOLDERS = "no_holders"
    PRICE_COLLAPSED = "price_collapsed"
    RUGGED = "rugged"
    ABANDONED = "abandoned"
    TECHNICAL_FAILURE = "technical_failure"
    SCAM_DETECTED = "scam_detected"


@dataclass
class AnalysisResult:
    """Result of token analysis"""
    token_address: str
    viability_score: float  # 0-100, higher = more viable
    risk_score: float      # 0-100, higher = more risky
    momentum_score: float  # -100 to +100, positive = bullish momentum
    health_status: TokenHealth
    death_reason: Optional[DeathReason] = None
    confidence: float = 0.0  # 0-1, confidence in the analysis
    analysis_timestamp: float = 0.0
    
    def __post_init__(self):
        if self.analysis_timestamp == 0.0:
            self.analysis_timestamp = time.time()


@dataclass
class ScoreComponents:
    """Breakdown of score components for transparency"""
    liquidity_score: float = 0.0
    volume_score: float = 0.0
    holder_score: float = 0.0
    price_stability_score: float = 0.0
    market_cap_score: float = 0.0
    age_score: float = 0.0
    momentum_indicators: Dict[str, float] = None
    risk_factors: Dict[str, float] = None
    
    def __post_init__(self):
        if self.momentum_indicators is None:
            self.momentum_indicators = {}
        if self.risk_factors is None:
            self.risk_factors = {}


class TokenAnalyzer:
    """
    Comprehensive token analysis engine for scoring and dead token detection
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        
        # Analysis thresholds and weights
        self.config = {
            # Viability score weights (must sum to 1.0)
            'viability_weights': {
                'liquidity': 0.25,
                'volume': 0.20,
                'holders': 0.15,
                'market_cap': 0.15,
                'price_stability': 0.15,
                'age': 0.10
            },
            
            # Risk score weights (must sum to 1.0)
            'risk_weights': {
                'security_risk': 0.30,
                'liquidity_risk': 0.25,
                'concentration_risk': 0.20,
                'volatility_risk': 0.15,
                'technical_risk': 0.10
            },
            
            # Dead token thresholds
            'death_thresholds': {
                'min_liquidity_usd': 100,
                'min_volume_24h_usd': 10,
                'min_holders': 5,
                'max_price_drop_percent': 99,
                'min_market_cap_usd': 100,
                'max_days_no_activity': 30,
                'max_rug_risk_score': 95
            },
            
            # Momentum indicators
            'momentum_config': {
                'price_weight': 0.4,
                'volume_weight': 0.3,
                'holder_weight': 0.2,
                'liquidity_weight': 0.1
            },
            
            # Historical analysis periods
            'analysis_periods': {
                'short_term_hours': 24,
                'medium_term_hours': 168,  # 7 days
                'long_term_hours': 720     # 30 days
            }
        }
        
        self.logger.info("📊 Token Analyzer initialized")
    
    def analyze_token(
        self, 
        token_data: TokenData, 
        historical_data: Optional[List[Dict]] = None
    ) -> AnalysisResult:
        """
        Perform comprehensive analysis of a token
        
        Args:
            token_data: Current token data
            historical_data: Optional historical snapshots
            
        Returns:
            AnalysisResult with all scores and assessments
        """
        try:
            # Calculate individual scores
            viability_score = self.calculate_viability_score(token_data, historical_data)
            risk_score = self.calculate_risk_score(token_data, historical_data)
            momentum_score = self.calculate_momentum_score(token_data, historical_data)
            
            # Assess health status
            health_status, death_reason = self._assess_token_health(token_data, historical_data)
            
            # Calculate confidence in analysis
            confidence = self._calculate_analysis_confidence(token_data, historical_data)
            
            result = AnalysisResult(
                token_address=token_data.address,
                viability_score=viability_score,
                risk_score=risk_score,
                momentum_score=momentum_score,
                health_status=health_status,
                death_reason=death_reason,
                confidence=confidence
            )
            
            self.logger.debug(
                f"📊 Analysis completed for {token_data.address[:8]}...: "
                f"V={viability_score:.1f}, R={risk_score:.1f}, M={momentum_score:.1f}, "
                f"Health={health_status.value}"
            )
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error analyzing token {token_data.address}: {e}")
            return AnalysisResult(
                token_address=token_data.address,
                viability_score=0.0,
                risk_score=100.0,
                momentum_score=0.0,
                health_status=TokenHealth.UNKNOWN,
                confidence=0.0
            )
    
    def calculate_viability_score(
        self, 
        token_data: TokenData, 
        historical_data: Optional[List[Dict]] = None
    ) -> float:
        """
        Calculate token viability score (0-100, higher = more viable)
        
        Args:
            token_data: Current token data
            historical_data: Optional historical data
            
        Returns:
            Viability score from 0 to 100
        """
        try:
            scores = ScoreComponents()
            weights = self.config['viability_weights']
            
            # 1. Liquidity Score (0-100)
            scores.liquidity_score = self._calculate_liquidity_score(token_data)
            
            # 2. Volume Score (0-100)
            scores.volume_score = self._calculate_volume_score(token_data, historical_data)
            
            # 3. Holder Score (0-100)
            scores.holder_score = self._calculate_holder_score(token_data, historical_data)
            
            # 4. Market Cap Score (0-100)
            scores.market_cap_score = self._calculate_market_cap_score(token_data)
            
            # 5. Price Stability Score (0-100)
            scores.price_stability_score = self._calculate_price_stability_score(token_data, historical_data)
            
            # 6. Age Score (0-100)
            scores.age_score = self._calculate_age_score(token_data)
            
            # Calculate weighted total
            total_score = (
                scores.liquidity_score * weights['liquidity'] +
                scores.volume_score * weights['volume'] +
                scores.holder_score * weights['holders'] +
                scores.market_cap_score * weights['market_cap'] +
                scores.price_stability_score * weights['price_stability'] +
                scores.age_score * weights['age']
            )
            
            return max(0.0, min(100.0, total_score))
            
        except Exception as e:
            self.logger.error(f"Error calculating viability score: {e}")
            return 0.0
    
    def calculate_risk_score(
        self, 
        token_data: TokenData, 
        historical_data: Optional[List[Dict]] = None
    ) -> float:
        """
        Calculate token risk score (0-100, higher = more risky)
        
        Args:
            token_data: Current token data
            historical_data: Optional historical data
            
        Returns:
            Risk score from 0 to 100
        """
        try:
            scores = ScoreComponents()
            weights = self.config['risk_weights']
            
            # 1. Security Risk (rug pull, authority, etc.)
            security_risk = self._calculate_security_risk(token_data)
            scores.risk_factors['security'] = security_risk
            
            # 2. Liquidity Risk (low liquidity, removable LP)
            liquidity_risk = self._calculate_liquidity_risk(token_data)
            scores.risk_factors['liquidity'] = liquidity_risk
            
            # 3. Concentration Risk (holder concentration, insider trading)
            concentration_risk = self._calculate_concentration_risk(token_data)
            scores.risk_factors['concentration'] = concentration_risk
            
            # 4. Volatility Risk (price instability)
            volatility_risk = self._calculate_volatility_risk(token_data, historical_data)
            scores.risk_factors['volatility'] = volatility_risk
            
            # 5. Technical Risk (mint authority, freeze authority)
            technical_risk = self._calculate_technical_risk(token_data)
            scores.risk_factors['technical'] = technical_risk
            
            # Calculate weighted total
            total_risk = (
                security_risk * weights['security_risk'] +
                liquidity_risk * weights['liquidity_risk'] +
                concentration_risk * weights['concentration_risk'] +
                volatility_risk * weights['volatility_risk'] +
                technical_risk * weights['technical_risk']
            )
            
            return max(0.0, min(100.0, total_risk))
            
        except Exception as e:
            self.logger.error(f"Error calculating risk score: {e}")
            return 100.0  # Assume high risk on error
    
    def calculate_momentum_score(
        self, 
        token_data: TokenData, 
        historical_data: Optional[List[Dict]] = None
    ) -> float:
        """
        Calculate momentum score (-100 to +100, positive = bullish)
        
        Args:
            token_data: Current token data
            historical_data: Optional historical data
            
        Returns:
            Momentum score from -100 to +100
        """
        try:
            scores = ScoreComponents()
            weights = self.config['momentum_config']
            
            # 1. Price Momentum
            price_momentum = self._calculate_price_momentum(token_data, historical_data)
            scores.momentum_indicators['price'] = price_momentum
            
            # 2. Volume Momentum
            volume_momentum = self._calculate_volume_momentum(token_data, historical_data)
            scores.momentum_indicators['volume'] = volume_momentum
            
            # 3. Holder Momentum
            holder_momentum = self._calculate_holder_momentum(token_data, historical_data)
            scores.momentum_indicators['holders'] = holder_momentum
            
            # 4. Liquidity Momentum
            liquidity_momentum = self._calculate_liquidity_momentum(token_data, historical_data)
            scores.momentum_indicators['liquidity'] = liquidity_momentum
            
            # Calculate weighted momentum
            total_momentum = (
                price_momentum * weights['price_weight'] +
                volume_momentum * weights['volume_weight'] +
                holder_momentum * weights['holder_weight'] +
                liquidity_momentum * weights['liquidity_weight']
            )
            
            return max(-100.0, min(100.0, total_momentum))
            
        except Exception as e:
            self.logger.error(f"Error calculating momentum score: {e}")
            return 0.0
    
    def is_token_dead(
        self, 
        token_data: TokenData, 
        historical_data: Optional[List[Dict]] = None
    ) -> Tuple[bool, Optional[DeathReason]]:
        """
        Determine if a token should be considered dead
        
        Args:
            token_data: Current token data
            historical_data: Optional historical data
            
        Returns:
            Tuple of (is_dead, death_reason)
        """
        try:
            thresholds = self.config['death_thresholds']
            
            # Check for rug pull
            if token_data.is_rugged or token_data.rug_risk_score >= thresholds['max_rug_risk_score']:
                return True, DeathReason.RUGGED
            
            # Check liquidity
            if token_data.liquidity_usd < thresholds['min_liquidity_usd']:
                return True, DeathReason.NO_LIQUIDITY
            
            # Check volume
            if token_data.volume_24h < thresholds['min_volume_24h_usd']:
                return True, DeathReason.NO_VOLUME
            
            # Check holders
            if token_data.holder_count < thresholds['min_holders']:
                return True, DeathReason.NO_HOLDERS
            
            # Check market cap
            if token_data.market_cap < thresholds['min_market_cap_usd']:
                return True, DeathReason.PRICE_COLLAPSED
            
            # Check for massive price drop
            if token_data.price_change_24h <= -thresholds['max_price_drop_percent']:
                return True, DeathReason.PRICE_COLLAPSED
            
            # Check for prolonged inactivity (requires historical data)
            if historical_data and len(historical_data) > 0:
                if self._check_prolonged_inactivity(token_data, historical_data):
                    return True, DeathReason.ABANDONED
            
            # Check for technical failures
            if self._check_technical_failure(token_data):
                return True, DeathReason.TECHNICAL_FAILURE
            
            return False, None
            
        except Exception as e:
            self.logger.error(f"Error checking if token is dead: {e}")
            return False, None
    
    def _calculate_liquidity_score(self, token_data: TokenData) -> float:
        """Calculate liquidity score (0-100)"""
        liquidity = token_data.liquidity_usd
        
        if liquidity <= 0:
            return 0.0
        
        # Logarithmic scoring for liquidity
        # $1K = 20, $10K = 40, $100K = 60, $1M = 80, $10M+ = 100
        if liquidity >= 10_000_000:
            return 100.0
        elif liquidity >= 1_000_000:
            return 80.0 + (20.0 * (liquidity - 1_000_000) / 9_000_000)
        elif liquidity >= 100_000:
            return 60.0 + (20.0 * (liquidity - 100_000) / 900_000)
        elif liquidity >= 10_000:
            return 40.0 + (20.0 * (liquidity - 10_000) / 90_000)
        elif liquidity >= 1_000:
            return 20.0 + (20.0 * (liquidity - 1_000) / 9_000)
        else:
            return 20.0 * (liquidity / 1_000)
    
    def _calculate_volume_score(self, token_data: TokenData, historical_data: Optional[List[Dict]]) -> float:
        """Calculate volume score (0-100)"""
        volume_24h = token_data.volume_24h
        
        if volume_24h <= 0:
            return 0.0
        
        # Base score from 24h volume
        if volume_24h >= 1_000_000:
            base_score = 100.0
        elif volume_24h >= 100_000:
            base_score = 80.0 + (20.0 * (volume_24h - 100_000) / 900_000)
        elif volume_24h >= 10_000:
            base_score = 60.0 + (20.0 * (volume_24h - 10_000) / 90_000)
        elif volume_24h >= 1_000:
            base_score = 40.0 + (20.0 * (volume_24h - 1_000) / 9_000)
        elif volume_24h >= 100:
            base_score = 20.0 + (20.0 * (volume_24h - 100) / 900)
        else:
            base_score = 20.0 * (volume_24h / 100)
        
        # Adjust based on volume consistency (if historical data available)
        if historical_data and len(historical_data) >= 3:
            consistency_factor = self._calculate_volume_consistency(historical_data)
            base_score *= consistency_factor
        
        return min(100.0, base_score)
    
    def _calculate_holder_score(self, token_data: TokenData, historical_data: Optional[List[Dict]]) -> float:
        """Calculate holder score (0-100)"""
        holders = token_data.holder_count
        
        if holders <= 0:
            return 0.0
        
        # Base score from holder count
        if holders >= 10_000:
            base_score = 100.0
        elif holders >= 1_000:
            base_score = 80.0 + (20.0 * (holders - 1_000) / 9_000)
        elif holders >= 100:
            base_score = 60.0 + (20.0 * (holders - 100) / 900)
        elif holders >= 50:
            base_score = 40.0 + (20.0 * (holders - 50) / 50)
        elif holders >= 10:
            base_score = 20.0 + (20.0 * (holders - 10) / 40)
        else:
            base_score = 20.0 * (holders / 10)
        
        # Adjust for holder growth trend
        if historical_data and len(historical_data) >= 2:
            growth_factor = self._calculate_holder_growth_factor(historical_data)
            base_score *= growth_factor
        
        return min(100.0, base_score)
    
    def _calculate_market_cap_score(self, token_data: TokenData) -> float:
        """Calculate market cap score (0-100)"""
        market_cap = token_data.market_cap
        
        if market_cap <= 0:
            return 0.0
        
        # Logarithmic scoring for market cap
        if market_cap >= 100_000_000:  # $100M+
            return 100.0
        elif market_cap >= 10_000_000:  # $10M-$100M
            return 80.0 + (20.0 * (market_cap - 10_000_000) / 90_000_000)
        elif market_cap >= 1_000_000:   # $1M-$10M
            return 60.0 + (20.0 * (market_cap - 1_000_000) / 9_000_000)
        elif market_cap >= 100_000:     # $100K-$1M
            return 40.0 + (20.0 * (market_cap - 100_000) / 900_000)
        elif market_cap >= 10_000:      # $10K-$100K
            return 20.0 + (20.0 * (market_cap - 10_000) / 90_000)
        else:                           # <$10K
            return 20.0 * (market_cap / 10_000)
    
    def _calculate_price_stability_score(self, token_data: TokenData, historical_data: Optional[List[Dict]]) -> float:
        """Calculate price stability score (0-100, higher = more stable)"""
        # Base volatility from 24h change
        price_change_24h = abs(token_data.price_change_24h)
        
        if price_change_24h >= 90:
            base_score = 0.0
        elif price_change_24h >= 50:
            base_score = 20.0 * (1 - (price_change_24h - 50) / 40)
        elif price_change_24h >= 20:
            base_score = 60.0 + (20.0 * (1 - (price_change_24h - 20) / 30))
        elif price_change_24h >= 10:
            base_score = 80.0 + (20.0 * (1 - (price_change_24h - 10) / 10))
        else:
            base_score = 100.0
        
        # Adjust based on historical volatility
        if historical_data and len(historical_data) >= 7:
            volatility_factor = self._calculate_historical_volatility_factor(historical_data)
            base_score *= volatility_factor
        
        return max(0.0, min(100.0, base_score))
    
    def _calculate_age_score(self, token_data: TokenData) -> float:
        """Calculate age score (0-100, older = more established)"""
        if not token_data.timestamp_token_created or token_data.timestamp_token_created <= 0:
            return 10.0  # Low score for unknown age
        
        current_time = time.time()
        age_seconds = current_time - token_data.timestamp_token_created
        age_days = age_seconds / 86400
        
        if age_days >= 365:      # 1+ years
            return 100.0
        elif age_days >= 90:     # 3+ months
            return 80.0 + (20.0 * (age_days - 90) / 275)
        elif age_days >= 30:     # 1+ month
            return 60.0 + (20.0 * (age_days - 30) / 60)
        elif age_days >= 7:      # 1+ week
            return 40.0 + (20.0 * (age_days - 7) / 23)
        elif age_days >= 1:      # 1+ day
            return 20.0 + (20.0 * (age_days - 1) / 6)
        else:                    # < 1 day
            return 20.0 * age_days
    
    def _calculate_security_risk(self, token_data: TokenData) -> float:
        """Calculate security risk (0-100, higher = more risky)"""
        risk = 0.0
        
        # Rug risk score (most important)
        if token_data.rug_risk_score > 0:
            risk += token_data.rug_risk_score * 0.6
        else:
            risk += 50.0 * 0.6  # Assume medium risk if unknown
        
        # Additional risk factors
        if token_data.is_rugged:
            risk = 100.0  # Maximum risk if already rugged
        
        if token_data.risk_count > 0:
            risk += min(token_data.risk_count * 5, 20)  # Max 20 points for multiple risks
        
        if token_data.has_low_liquidity:
            risk += 10.0
        
        return min(100.0, risk)
    
    def _calculate_liquidity_risk(self, token_data: TokenData) -> float:
        """Calculate liquidity risk (0-100)"""
        risk = 0.0
        
        # Base risk from liquidity amount
        liquidity = token_data.liquidity_usd
        if liquidity < 1_000:
            risk += 80.0
        elif liquidity < 10_000:
            risk += 60.0
        elif liquidity < 100_000:
            risk += 40.0
        elif liquidity < 1_000_000:
            risk += 20.0
        
        # Additional liquidity risks
        if hasattr(token_data, 'lp_removable_percentage'):
            removable_pct = getattr(token_data, 'lp_removable_percentage', 0)
            risk += min(removable_pct * 0.5, 30)  # Max 30 points for removable LP
        
        if token_data.has_low_liquidity:
            risk += 20.0
        
        return min(100.0, risk)
    
    def _calculate_concentration_risk(self, token_data: TokenData) -> float:
        """Calculate concentration risk (0-100)"""
        risk = 0.0
        
        # Top holder concentration
        if token_data.top_holder_percentage > 50:
            risk += 60.0
        elif token_data.top_holder_percentage > 30:
            risk += 40.0
        elif token_data.top_holder_percentage > 20:
            risk += 25.0
        elif token_data.top_holder_percentage > 10:
            risk += 15.0
        
        # Top 10 holders concentration
        if token_data.top_10_holders_percentage > 80:
            risk += 30.0
        elif token_data.top_10_holders_percentage > 60:
            risk += 20.0
        elif token_data.top_10_holders_percentage > 40:
            risk += 10.0
        
        # Insider trading risks
        if token_data.insider_holders_count > 0:
            risk += min(token_data.insider_holders_count * 5, 20)
        
        if token_data.insider_networks_detected > 0:
            risk += min(token_data.insider_networks_detected * 10, 30)
        
        return min(100.0, risk)
    
    def _calculate_volatility_risk(self, token_data: TokenData, historical_data: Optional[List[Dict]]) -> float:
        """Calculate volatility risk (0-100)"""
        risk = 0.0
        
        # 24h price change risk
        price_change = abs(token_data.price_change_24h)
        if price_change > 90:
            risk += 80.0
        elif price_change > 50:
            risk += 60.0
        elif price_change > 30:
            risk += 40.0
        elif price_change > 15:
            risk += 20.0
        
        # Historical volatility (if available)
        if historical_data and len(historical_data) >= 7:
            volatility = self._calculate_historical_volatility(historical_data)
            risk += min(volatility * 2, 40)  # Max 40 points for historical volatility
        
        return min(100.0, risk)
    
    def _calculate_technical_risk(self, token_data: TokenData) -> float:
        """Calculate technical risk (0-100)"""
        risk = 0.0
        
        # Authority risks
        if not token_data.mint_authority_revoked:
            risk += 40.0
        
        if not token_data.freeze_authority_revoked:
            risk += 30.0
        
        # Pump.fun specific risks
        if token_data.is_pump_fun and token_data.bonding_curve_progress < 100:
            risk += 20.0  # Prebond tokens have completion risk
        
        return min(100.0, risk)
    
    def _calculate_price_momentum(self, token_data: TokenData, historical_data: Optional[List[Dict]]) -> float:
        """Calculate price momentum (-100 to +100)"""
        # Short-term momentum from recent changes
        momentum = 0.0
        
        # 24h change
        momentum += token_data.price_change_24h * 0.4
        
        # 6h change
        momentum += token_data.price_change_6h * 0.3
        
        # 1h change
        momentum += token_data.price_change_1h * 0.3
        
        # Trend analysis from historical data
        if historical_data and len(historical_data) >= 3:
            trend_momentum = self._calculate_price_trend_momentum(historical_data)
            momentum = (momentum * 0.7) + (trend_momentum * 0.3)
        
        return max(-100.0, min(100.0, momentum))
    
    def _calculate_volume_momentum(self, token_data: TokenData, historical_data: Optional[List[Dict]]) -> float:
        """Calculate volume momentum (-100 to +100)"""
        if not historical_data or len(historical_data) < 2:
            return 0.0
        
        try:
            current_volume = token_data.volume_24h
            if current_volume <= 0:
                return -50.0
            
            # Compare with recent historical volumes
            recent_volumes = [float(h.get('volume_24h', 0)) for h in historical_data[:5]]
            avg_volume = sum(v for v in recent_volumes if v > 0) / max(len([v for v in recent_volumes if v > 0]), 1)
            
            if avg_volume > 0:
                volume_change = ((current_volume - avg_volume) / avg_volume) * 100
                return max(-100.0, min(100.0, volume_change))
            
            return 0.0
            
        except Exception:
            return 0.0
    
    def _calculate_holder_momentum(self, token_data: TokenData, historical_data: Optional[List[Dict]]) -> float:
        """Calculate holder momentum (-100 to +100)"""
        if not historical_data or len(historical_data) < 2:
            return 0.0
        
        try:
            current_holders = token_data.holder_count
            if current_holders <= 0:
                return -50.0
            
            # Compare with recent historical holder counts
            recent_holders = [int(h.get('holder_count', 0)) for h in historical_data[:5]]
            avg_holders = sum(h for h in recent_holders if h > 0) / max(len([h for h in recent_holders if h > 0]), 1)
            
            if avg_holders > 0:
                holder_change = ((current_holders - avg_holders) / avg_holders) * 100
                return max(-100.0, min(100.0, holder_change))
            
            return 0.0
            
        except Exception:
            return 0.0
    
    def _calculate_liquidity_momentum(self, token_data: TokenData, historical_data: Optional[List[Dict]]) -> float:
        """Calculate liquidity momentum (-100 to +100)"""
        if not historical_data or len(historical_data) < 2:
            return 0.0
        
        try:
            current_liquidity = token_data.liquidity_usd
            if current_liquidity <= 0:
                return -50.0
            
            # Compare with recent historical liquidity
            recent_liquidity = [float(h.get('liquidity_usd', 0)) for h in historical_data[:3]]
            avg_liquidity = sum(l for l in recent_liquidity if l > 0) / max(len([l for l in recent_liquidity if l > 0]), 1)
            
            if avg_liquidity > 0:
                liquidity_change = ((current_liquidity - avg_liquidity) / avg_liquidity) * 100
                return max(-100.0, min(100.0, liquidity_change))
            
            return 0.0
            
        except Exception:
            return 0.0
    
    def _assess_token_health(self, token_data: TokenData, historical_data: Optional[List[Dict]]) -> Tuple[TokenHealth, Optional[DeathReason]]:
        """Assess overall token health"""
        # Check if dead first
        is_dead, death_reason = self.is_token_dead(token_data, historical_data)
        if is_dead:
            return TokenHealth.DEAD, death_reason
        
        # Calculate health factors
        critical_factors = 0
        warning_factors = 0
        
        # Check critical factors
        if token_data.liquidity_usd < 1000:
            critical_factors += 1
        if token_data.volume_24h < 100:
            critical_factors += 1
        if token_data.rug_risk_score > 80:
            critical_factors += 1
        if token_data.top_holder_percentage > 60:
            critical_factors += 1
        
        # Check warning factors
        if token_data.liquidity_usd < 10000:
            warning_factors += 1
        if token_data.volume_24h < 1000:
            warning_factors += 1
        if token_data.holder_count < 100:
            warning_factors += 1
        if abs(token_data.price_change_24h) > 50:
            warning_factors += 1
        if not token_data.mint_authority_revoked:
            warning_factors += 1
        
        # Determine health status
        if critical_factors >= 2:
            return TokenHealth.CRITICAL, None
        elif critical_factors >= 1 or warning_factors >= 3:
            return TokenHealth.WARNING, None
        elif warning_factors >= 1:
            return TokenHealth.WARNING, None
        else:
            return TokenHealth.HEALTHY, None
    
    def _calculate_analysis_confidence(self, token_data: TokenData, historical_data: Optional[List[Dict]]) -> float:
        """Calculate confidence in the analysis (0-1)"""
        confidence = 0.5  # Base confidence
        
        # Data completeness factors
        if token_data.price_usd > 0:
            confidence += 0.1
        if token_data.liquidity_usd > 0:
            confidence += 0.1
        if token_data.volume_24h > 0:
            confidence += 0.1
        if token_data.holder_count > 0:
            confidence += 0.1
        if token_data.timestamp_token_created > 0:
            confidence += 0.05
        
        # Historical data availability
        if historical_data:
            data_points = len(historical_data)
            if data_points >= 10:
                confidence += 0.1
            elif data_points >= 5:
                confidence += 0.05
        
        # Security data availability
        if token_data.rug_risk_score > 0:
            confidence += 0.05
        
        return min(1.0, confidence)
    
    def _check_prolonged_inactivity(self, token_data: TokenData, historical_data: List[Dict]) -> bool:
        """Check for prolonged inactivity indicating abandonment"""
        if not historical_data or len(historical_data) < 5:
            return False
        
        try:
            max_days = self.config['death_thresholds']['max_days_no_activity']
            recent_data = historical_data[:max_days]  # Last N snapshots
            
            # Check for consistent zero or very low activity
            zero_volume_count = 0
            zero_price_change_count = 0
            
            for snapshot in recent_data:
                volume = float(snapshot.get('volume_24h', 0))
                price_change = abs(float(snapshot.get('price_change_24h', 0)))
                
                if volume < 10:  # Less than $10 volume
                    zero_volume_count += 1
                if price_change < 1:  # Less than 1% price change
                    zero_price_change_count += 1
            
            # If majority of recent snapshots show no activity
            if zero_volume_count >= len(recent_data) * 0.8:
                return True
            if zero_price_change_count >= len(recent_data) * 0.9:
                return True
            
            return False
            
        except Exception:
            return False
    
    def _check_technical_failure(self, token_data: TokenData) -> bool:
        """Check for technical failures"""
        # Check for obvious technical issues
        if token_data.price_usd <= 0 and token_data.market_cap <= 0:
            return True
        
        # Check for impossible values
        if token_data.liquidity_usd < 0 or token_data.volume_24h < 0:
            return True
        
        # Check for metadata issues indicating technical problems
        if not token_data.symbol or token_data.symbol.startswith('UNK_'):
            if token_data.market_cap < 1000:  # Only for very small tokens
                return True
        
        return False
    
    def _calculate_volume_consistency(self, historical_data: List[Dict]) -> float:
        """Calculate volume consistency factor (0.5-1.5)"""
        try:
            volumes = [float(h.get('volume_24h', 0)) for h in historical_data[:7]]
            volumes = [v for v in volumes if v > 0]
            
            if len(volumes) < 3:
                return 1.0
            
            avg_volume = sum(volumes) / len(volumes)
            variance = sum((v - avg_volume) ** 2 for v in volumes) / len(volumes)
            std_dev = math.sqrt(variance)
            
            # Coefficient of variation
            cv = std_dev / avg_volume if avg_volume > 0 else 2.0
            
            # Lower CV = more consistent = higher factor
            if cv < 0.5:
                return 1.2
            elif cv < 1.0:
                return 1.1
            elif cv < 2.0:
                return 1.0
            else:
                return 0.8
                
        except Exception:
            return 1.0
    
    def _calculate_holder_growth_factor(self, historical_data: List[Dict]) -> float:
        """Calculate holder growth factor (0.5-1.5)"""
        try:
            if len(historical_data) < 2:
                return 1.0
            
            oldest = historical_data[-1]
            newest = historical_data[0]
            
            old_holders = int(oldest.get('holder_count', 0))
            new_holders = int(newest.get('holder_count', 0))
            
            if old_holders <= 0:
                return 1.0
            
            growth_rate = (new_holders - old_holders) / old_holders
            
            # Positive growth = bonus, negative = penalty
            if growth_rate > 0.5:
                return 1.3
            elif growth_rate > 0.2:
                return 1.2
            elif growth_rate > 0:
                return 1.1
            elif growth_rate > -0.1:
                return 1.0
            elif growth_rate > -0.3:
                return 0.9
            else:
                return 0.7
                
        except Exception:
            return 1.0
    
    def _calculate_historical_volatility_factor(self, historical_data: List[Dict]) -> float:
        """Calculate historical volatility factor (0.5-1.2)"""
        try:
            price_changes = [abs(float(h.get('price_change_24h', 0))) for h in historical_data[:14]]
            price_changes = [p for p in price_changes if p >= 0]
            
            if len(price_changes) < 3:
                return 1.0
            
            avg_volatility = sum(price_changes) / len(price_changes)
            
            # Lower average volatility = higher stability score
            if avg_volatility < 5:
                return 1.2
            elif avg_volatility < 10:
                return 1.1
            elif avg_volatility < 20:
                return 1.0
            elif avg_volatility < 40:
                return 0.9
            else:
                return 0.7
                
        except Exception:
            return 1.0
    
    def _calculate_historical_volatility(self, historical_data: List[Dict]) -> float:
        """Calculate historical volatility score (0-50)"""
        try:
            price_changes = [abs(float(h.get('price_change_24h', 0))) for h in historical_data[:14]]
            price_changes = [p for p in price_changes if p >= 0]
            
            if len(price_changes) < 3:
                return 20.0  # Default medium volatility
            
            avg_volatility = sum(price_changes) / len(price_changes)
            return min(50.0, avg_volatility)
            
        except Exception:
            return 20.0
    
    def _calculate_price_trend_momentum(self, historical_data: List[Dict]) -> float:
        """Calculate price trend momentum from historical data (-50 to +50)"""
        try:
            if len(historical_data) < 3:
                return 0.0
            
            prices = []
            for h in historical_data[:7]:  # Last 7 data points
                price = float(h.get('price_usd', 0))
                if price > 0:
                    prices.append(price)
            
            if len(prices) < 3:
                return 0.0
            
            # Calculate linear trend
            n = len(prices)
            x_values = list(range(n))
            
            # Simple linear regression slope
            x_mean = sum(x_values) / n
            y_mean = sum(prices) / n
            
            numerator = sum((x_values[i] - x_mean) * (prices[i] - y_mean) for i in range(n))
            denominator = sum((x_values[i] - x_mean) ** 2 for i in range(n))
            
            if denominator == 0:
                return 0.0
            
            slope = numerator / denominator
            
            # Convert slope to momentum score
            # Positive slope = upward trend = positive momentum
            trend_momentum = slope * 100000  # Scale factor
            
            return max(-50.0, min(50.0, trend_momentum))
            
        except Exception:
            return 0.0
    
    def batch_analyze_tokens(
        self, 
        tokens_data: List[TokenData], 
        historical_data_map: Optional[Dict[str, List[Dict]]] = None
    ) -> List[AnalysisResult]:
        """
        Analyze multiple tokens in batch
        
        Args:
            tokens_data: List of token data objects
            historical_data_map: Optional mapping of token_address -> historical_data
            
        Returns:
            List of analysis results
        """
        results = []
        
        for token_data in tokens_data:
            try:
                historical_data = None
                if historical_data_map:
                    historical_data = historical_data_map.get(token_data.address)
                
                result = self.analyze_token(token_data, historical_data)
                results.append(result)
                
            except Exception as e:
                self.logger.error(f"Error analyzing token {token_data.address}: {e}")
                results.append(AnalysisResult(
                    token_address=token_data.address,
                    viability_score=0.0,
                    risk_score=100.0,
                    momentum_score=0.0,
                    health_status=TokenHealth.UNKNOWN,
                    confidence=0.0
                ))
        
        return results
    
    def identify_dead_tokens(
        self, 
        tokens_data: List[TokenData], 
        historical_data_map: Optional[Dict[str, List[Dict]]] = None
    ) -> List[Tuple[str, DeathReason]]:
        """
        Identify dead tokens from a list
        
        Args:
            tokens_data: List of token data objects
            historical_data_map: Optional mapping of token_address -> historical_data
            
        Returns:
            List of tuples (token_address, death_reason)
        """
        dead_tokens = []
        
        for token_data in tokens_data:
            try:
                historical_data = None
                if historical_data_map:
                    historical_data = historical_data_map.get(token_data.address)
                
                is_dead, death_reason = self.is_token_dead(token_data, historical_data)
                if is_dead and death_reason:
                    dead_tokens.append((token_data.address, death_reason))
                    
            except Exception as e:
                self.logger.error(f"Error checking if token {token_data.address} is dead: {e}")
        
        self.logger.info(f"💀 Identified {len(dead_tokens)} dead tokens")
        return dead_tokens
    
    def get_top_tokens_by_score(
        self, 
        analysis_results: List[AnalysisResult], 
        score_type: str = "viability",
        limit: int = 10
    ) -> List[AnalysisResult]:
        """
        Get top tokens by specified score
        
        Args:
            analysis_results: List of analysis results
            score_type: "viability", "risk" (inverted), or "momentum"
            limit: Number of top tokens to return
            
        Returns:
            List of top analysis results
        """
        if score_type == "viability":
            sorted_results = sorted(analysis_results, key=lambda r: r.viability_score, reverse=True)
        elif score_type == "risk":
            sorted_results = sorted(analysis_results, key=lambda r: r.risk_score, reverse=False)  # Lower risk = better
        elif score_type == "momentum":
            sorted_results = sorted(analysis_results, key=lambda r: r.momentum_score, reverse=True)
        else:
            raise ValueError(f"Unknown score_type: {score_type}")
        
        return sorted_results[:limit]
    
    def get_analysis_statistics(self, analysis_results: List[AnalysisResult]) -> Dict[str, Any]:
        """Get statistics from analysis results"""
        if not analysis_results:
            return {}
        
        # Health status distribution
        health_counts = {}
        for status in TokenHealth:
            health_counts[status.value] = len([r for r in analysis_results if r.health_status == status])
        
        # Death reason distribution
        death_reasons = {}
        for reason in DeathReason:
            death_reasons[reason.value] = len([r for r in analysis_results if r.death_reason == reason])
        
        # Score statistics
        viability_scores = [r.viability_score for r in analysis_results]
        risk_scores = [r.risk_score for r in analysis_results]
        momentum_scores = [r.momentum_score for r in analysis_results]
        confidences = [r.confidence for r in analysis_results]
        
        return {
            'total_analyzed': len(analysis_results),
            'health_distribution': health_counts,
            'death_reasons': death_reasons,
            'score_statistics': {
                'viability': {
                    'avg': sum(viability_scores) / len(viability_scores),
                    'min': min(viability_scores),
                    'max': max(viability_scores),
                    'median': sorted(viability_scores)[len(viability_scores) // 2]
                },
                'risk': {
                    'avg': sum(risk_scores) / len(risk_scores),
                    'min': min(risk_scores),
                    'max': max(risk_scores),
                    'median': sorted(risk_scores)[len(risk_scores) // 2]
                },
                'momentum': {
                    'avg': sum(momentum_scores) / len(momentum_scores),
                    'min': min(momentum_scores),
                    'max': max(momentum_scores),
                    'median': sorted(momentum_scores)[len(momentum_scores) // 2]
                },
                'confidence': {
                    'avg': sum(confidences) / len(confidences),
                    'min': min(confidences),
                    'max': max(confidences)
                }
            }
        }
    
    def update_config(self, new_config: Dict[str, Any]):
        """Update analyzer configuration"""
        self.config.update(new_config)
        self.logger.info(f"🔧 Updated analyzer configuration: {list(new_config.keys())}")
    
    def get_config(self) -> Dict[str, Any]:
        """Get current analyzer configuration"""
        return self.config.copy()
    
    def export_analysis_results(self, analysis_results: List[AnalysisResult], filename: Optional[str] = None) -> str:
        """Export analysis results to JSON file"""
        import json
        
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"token_analysis_{timestamp}.json"
        
        export_data = {
            'export_timestamp': datetime.now().isoformat(),
            'total_tokens': len(analysis_results),
            'config': self.config,
            'statistics': self.get_analysis_statistics(analysis_results),
            'results': [
                {
                    'token_address': r.token_address,
                    'viability_score': r.viability_score,
                    'risk_score': r.risk_score,
                    'momentum_score': r.momentum_score,
                    'health_status': r.health_status.value,
                    'death_reason': r.death_reason.value if r.death_reason else None,
                    'confidence': r.confidence,
                    'analysis_timestamp': r.analysis_timestamp
                }
                for r in analysis_results
            ]
        }
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"📄 Analysis results exported to {filename}")
            return filename
            
        except Exception as e:
            self.logger.error(f"❌ Failed to export analysis results: {e}")
            return ""


def create_token_analyzer(logger: Optional[logging.Logger] = None) -> TokenAnalyzer:
    """
    Factory function to create a configured token analyzer
    
    Args:
        logger: Optional logger instance
        
    Returns:
        Configured TokenAnalyzer instance
    """
    return TokenAnalyzer(logger=logger)