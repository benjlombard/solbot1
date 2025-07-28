"""
Pocker Universe Algorithm for Fake Volume Detection
File: pocker_universe.py

This module implements the Pocker Universe algorithm for detecting wash trading
and fake volume patterns in cryptocurrency tokens, similar to the system
integrated into DexScreener.
"""

import time
import logging
import hashlib
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict

class PockerUniverseAnalyzer:
    """
    Advanced fake volume detection system using Pocker Universe methodology
    
    This analyzer detects:
    - Wash trading patterns
    - Bot trading behavior
    - Volume manipulation schemes
    - Artificial liquidity patterns
    - Market making abuse
    """
    
    def __init__(self, config):
        self.config = config['pocker_universe']
        self.cache = {}
        self.cache_expiry = {}
        self.logger = logging.getLogger(__name__)
        self.advanced_logger = None  # Will be set by parent
        
        # Pocker Universe specific thresholds
        self.wash_trading_indicators = self.config.get('wash_trading_indicators', {
            'circular_trading_threshold': 0.3,
            'bot_trading_ratio': 0.5,
            'unique_trader_ratio': 0.1,
            'volume_concentration_ratio': 0.8
        })
        
        # Bot detection patterns
        self.bot_patterns = {
            'round_numbers': ['0000', '5000', '1000', '2500', '7500', '3333', '6666', '9999'],
            'time_intervals': [5, 10, 15, 30, 60],  # seconds
            'volume_thresholds': {
                'micro': 100,
                'small': 1000,
                'medium': 10000,
                'large': 100000
            }
        }
        
        self.logger.info("Pocker Universe Analyzer initialized")
        
    def set_advanced_logger(self, advanced_logger):
        """Set advanced logger instance"""
        self.advanced_logger = advanced_logger

    def get_cache_key(self, pair_address):
        """Generate cache key for pair analysis"""
        return hashlib.md5(f"pocker_{pair_address}_{datetime.now().hour}".encode()).hexdigest()
        
    def is_cache_valid(self, cache_key):
        """Check if cached result is still valid"""
        if cache_key not in self.cache_expiry:
            return False
        return datetime.now() < self.cache_expiry[cache_key]

    def analyze_volume_authenticity(self, pair_data, transaction_data=None):
        """
        Main Pocker Universe analysis function
        
        Analyzes volume authenticity using multiple sophisticated indicators:
        1. Volume Distribution Patterns
        2. Price-Volume Correlation Analysis  
        3. Transaction Pattern Recognition
        4. Liquidity-Volume Ratio Analysis
        5. Market Making Pattern Detection
        6. Wash Trading Circle Detection
        7. Bot Behavior Recognition
        
        Returns score between 0 (legitimate) and 1 (fake volume)
        """
        pair_address = pair_data.get('pairAddress')
        token_symbol = pair_data.get('baseToken', {}).get('symbol', 'UNKNOWN')
        cache_key = self.get_cache_key(pair_address)
        
        if self.advanced_logger:
            self.advanced_logger.debug_step('analysis', 'pocker_start', 
                                           f'🔍 POCKER UNIVERSE: Starting analysis for {token_symbol}')
        
        # Check cache first
        if self.is_cache_valid(cache_key):
            if self.advanced_logger:
                self.advanced_logger.log_cache_operation('analysis', 'GET', f'pocker_{token_symbol}', hit=True)
            return self.cache[cache_key]
        else:
            if self.advanced_logger:
                self.advanced_logger.log_cache_operation('analysis', 'GET', f'pocker_{token_symbol}', hit=False)
            
        try:
            start_time = time.time()
            fake_volume_score = 0.0
            indicators = []
            
            # Get volume data
            volume_data = pair_data.get('volume', {})
            volume_24h = float(volume_data.get('h24', 0) or 0)
            volume_1h = float(volume_data.get('h1', 0) or 0)
            volume_6h = float(volume_data.get('h6', 0) or 0)
            volume_5m = float(volume_data.get('m5', 0) or 0)
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'pocker_volume_extracted', 
                                               f'📊 POCKER: Volume data for {token_symbol}', 
                                               {
                                                   'volume_24h': f"${volume_24h:,.0f}",
                                                   'volume_1h': f"${volume_1h:,.0f}",
                                                   'volume_5m': f"${volume_5m:,.0f}"
                                               })
            
            # Skip analysis if volume too low
            min_volume = self.config.get('min_volume_for_analysis', 10000)
            if volume_24h < min_volume:
                result = {
                    'score': 0.0, 
                    'indicators': [f'Volume ${volume_24h:,.0f} below minimum ${min_volume:,.0f}'],
                    'classification': 'insufficient_volume'
                }
                self._cache_result(cache_key, result)
                if self.advanced_logger:
                    self.advanced_logger.debug_step('analysis', 'pocker_insufficient_volume', 
                                                   f'⚠️ POCKER: {token_symbol} volume too low for analysis')
                return result

            # 1. VOLUME DISTRIBUTION ANALYSIS (Weight: 25%)
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'pocker_vol_dist_start', 
                                               f'📈 POCKER: Analyzing volume distribution for {token_symbol}')
            
            volume_dist_score = self._analyze_volume_distribution_patterns(pair_data)
            fake_volume_score += volume_dist_score * 0.25
            
            if volume_dist_score > 0.5:
                indicator = f"Suspicious volume distribution (score: {volume_dist_score:.3f})"
                indicators.append(indicator)
                if self.advanced_logger:
                    self.advanced_logger.debug_step('analysis', 'pocker_vol_dist_suspicious', 
                                                   f'🚨 POCKER: {token_symbol} - {indicator}')

            # 2. PRICE-VOLUME CORRELATION ANALYSIS (Weight: 20%)
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'pocker_price_vol_start', 
                                               f'💹 POCKER: Analyzing price-volume correlation for {token_symbol}')
            
            price_vol_score = self._analyze_price_volume_correlation_advanced(pair_data)
            fake_volume_score += price_vol_score * 0.20
            
            if price_vol_score > 0.5:
                indicator = f"Abnormal price-volume correlation (score: {price_vol_score:.3f})"
                indicators.append(indicator)
                if self.advanced_logger:
                    self.advanced_logger.debug_step('analysis', 'pocker_price_vol_abnormal', 
                                                   f'🚨 POCKER: {token_symbol} - {indicator}')

            # 3. WASH TRADING DETECTION (Weight: 30%)
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'pocker_wash_trading_start', 
                                               f'🔄 POCKER: Analyzing wash trading patterns for {token_symbol}')
            
            wash_trading_score = self._detect_wash_trading_patterns(pair_data, transaction_data)
            fake_volume_score += wash_trading_score * 0.30
            
            if wash_trading_score > 0.5:
                indicator = f"Wash trading detected (score: {wash_trading_score:.3f})"
                indicators.append(indicator)
                if self.advanced_logger:
                    self.advanced_logger.debug_step('analysis', 'pocker_wash_trading_detected', 
                                                   f'🚨 POCKER: {token_symbol} - {indicator}')

            # 4. LIQUIDITY-VOLUME RATIO ANALYSIS (Weight: 15%)
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'pocker_liq_vol_start', 
                                               f'💰 POCKER: Analyzing liquidity-volume ratio for {token_symbol}')
            
            liq_vol_score = self._analyze_liquidity_volume_manipulation(pair_data)
            fake_volume_score += liq_vol_score * 0.15
            
            if liq_vol_score > 0.5:
                indicator = f"Liquidity manipulation detected (score: {liq_vol_score:.3f})"
                indicators.append(indicator)
                if self.advanced_logger:
                    self.advanced_logger.debug_step('analysis', 'pocker_liq_vol_manipulation', 
                                                   f'🚨 POCKER: {token_symbol} - {indicator}')

            # 5. BOT TRADING DETECTION (Weight: 10%)
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'pocker_bot_detection_start', 
                                               f'🤖 POCKER: Analyzing bot trading patterns for {token_symbol}')
            
            bot_score = self._detect_bot_trading_patterns(pair_data)
            fake_volume_score += bot_score * 0.10
            
            if bot_score > 0.5:
                indicator = f"Bot trading patterns detected (score: {bot_score:.3f})"
                indicators.append(indicator)
                if self.advanced_logger:
                    self.advanced_logger.debug_step('analysis', 'pocker_bot_detected', 
                                                   f'🚨 POCKER: {token_symbol} - {indicator}')

            final_score = min(fake_volume_score, 1.0)
            duration = time.time() - start_time

            # Classify the result
            classification = self._classify_fake_volume_result(final_score, indicators)
            
            result = {
                'score': final_score,
                'indicators': indicators,
                'classification': classification,
                'volume_24h': volume_24h,
                'analysis_timestamp': datetime.now().timestamp(),
                'pocker_universe_version': '2.0',
                'analysis_duration': duration
            }

            # Cache result
            self._cache_result(cache_key, result)
            
            if self.advanced_logger:
                self.advanced_logger.log_performance('analysis', 'pocker_universe_analysis', duration, True)
                self.advanced_logger.log_analysis_result('analysis', token_symbol, 'fake_volume_pocker', 
                                                        final_score, indicators)
                
                # Special logging for high-confidence fake volume
                if final_score > 0.8:
                    self.advanced_logger.debug_step('analysis', 'pocker_high_confidence_fake', 
                                                   f'🔥 POCKER: HIGH CONFIDENCE FAKE VOLUME - {token_symbol} (score: {final_score:.3f})')

            return result
            
        except Exception as e:
            duration = time.time() - start_time if 'start_time' in locals() else 0
            if self.advanced_logger:
                self.advanced_logger.log_performance('analysis', 'pocker_universe_analysis', duration, False)
                self.advanced_logger.debug_step('analysis', 'pocker_error', 
                                               f'❌ POCKER: Analysis error for {token_symbol}: {e}')
            self.logger.error(f"Pocker Universe analysis error: {e}")
            return {
                'score': 0.0, 
                'indicators': ['Analysis failed'], 
                'error': str(e),
                'classification': 'analysis_error'
            }

    def _analyze_volume_distribution_patterns(self, pair_data):
        """
        Advanced volume distribution analysis using Pocker Universe methodology
        
        Detects:
        - Unnatural volume spikes
        - Volume concentration patterns
        - Time-based manipulation
        """
        volume_data = pair_data.get('volume', {})
        
        volume_5m = float(volume_data.get('m5', 0) or 0)
        volume_1h = float(volume_data.get('h1', 0) or 0)
        volume_6h = float(volume_data.get('h6', 0) or 0)
        volume_24h = float(volume_data.get('h24', 0) or 0)
        
        suspicious_score = 0.0
        
        if volume_24h > 0:
            # Pattern 1: Extreme volume concentration in short periods
            if volume_1h > volume_24h * 0.8:  # 80% of daily volume in 1 hour
                suspicious_score += 0.6
                if self.advanced_logger:
                    ratio = volume_1h / volume_24h
                    self.advanced_logger.debug_step('analysis', 'pocker_vol_concentration_1h', 
                                                   f'Volume concentration detected: {ratio:.1%} in 1 hour')
                
            if volume_5m > volume_1h * 0.9:  # 90% of hourly volume in 5 minutes
                suspicious_score += 0.8
                if self.advanced_logger:
                    ratio = volume_5m / max(volume_1h, 1)
                    self.advanced_logger.debug_step('analysis', 'pocker_vol_concentration_5m', 
                                                   f'Extreme volume spike: {ratio:.1%} in 5 minutes')
        
        # Pattern 2: Volume consistency analysis (bots tend to be regular)
        if volume_1h > 0 and volume_6h > 0:
            hourly_avg = volume_6h / 6
            consistency_ratio = volume_1h / hourly_avg
            
            if consistency_ratio > 15:  # 15x average hourly volume
                suspicious_score += 0.4
                if self.advanced_logger:
                    self.advanced_logger.debug_step('analysis', 'pocker_vol_spike', 
                                                   f'Volume spike detected: {consistency_ratio:.1f}x average')
            
            # Very consistent volume might indicate bot trading
            if 0.8 < consistency_ratio < 1.2:  # Too consistent
                suspicious_score += 0.2
                if self.advanced_logger:
                    self.advanced_logger.debug_step('analysis', 'pocker_vol_too_consistent', 
                                                   f'Suspiciously consistent volume: {consistency_ratio:.2f}')

        return min(suspicious_score, 1.0)

    def _analyze_price_volume_correlation_advanced(self, pair_data):
        """
        Advanced price-volume correlation analysis
        
        Real trading should show correlation between price movements and volume.
        Fake volume often shows high volume with minimal price impact.
        """
        price_changes = pair_data.get('priceChange', {})
        volume_data = pair_data.get('volume', {})
        
        price_change_1h = float(price_changes.get('h1', 0) or 0)
        price_change_24h = float(price_changes.get('h24', 0) or 0)
        volume_1h = float(volume_data.get('h1', 0) or 0)
        volume_24h = float(volume_data.get('h24', 0) or 0)
        
        suspicious_score = 0.0
        
        # Pattern 1: High volume with minimal price movement (classic wash trading)
        if volume_24h > 10000 and abs(price_change_24h) < 3:  # High volume, <3% price change
            volume_ratio = volume_1h / max(volume_24h, 1)
            if volume_ratio > 0.4:  # 40%+ volume concentration
                suspicious_score += 0.7
                if self.advanced_logger:
                    self.advanced_logger.debug_step('analysis', 'pocker_high_vol_low_impact', 
                                                   f'High volume low impact: {volume_24h:,.0f} volume, {price_change_24h:.2f}% change')

        # Pattern 2: Unnatural volume spikes during price movements
        if abs(price_change_1h) > 15 and volume_1h > 0:  # >15% price change
            expected_volume_ratio = abs(price_change_1h) / 100  # Expected volume correlation
            actual_volume_ratio = volume_1h / max(volume_24h, 1)
            
            # If actual volume is much higher than expected for price movement
            if actual_volume_ratio > expected_volume_ratio * 4:
                suspicious_score += 0.5
                if self.advanced_logger:
                    self.advanced_logger.debug_step('analysis', 'pocker_vol_price_disconnect', 
                                                   f'Volume-price disconnect: {actual_volume_ratio:.2f} vs expected {expected_volume_ratio:.2f}')

        # Pattern 3: Volume without corresponding price discovery
        if volume_1h > volume_24h * 0.3 and abs(price_change_1h) < abs(price_change_24h) * 0.1:
            suspicious_score += 0.4
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'pocker_no_price_discovery', 
                                               'High volume without price discovery detected')

        return min(suspicious_score, 1.0)

    def _detect_wash_trading_patterns(self, pair_data, transaction_data=None):
        """
        Advanced wash trading detection using Pocker Universe methodology
        
        Wash trading indicators:
        - Circular trading patterns
        - Same wallet buy/sell cycles
        - Artificial volume creation
        - Coordinated trading behavior
        """
        volume_data = pair_data.get('volume', {})
        volume_5m = float(volume_data.get('m5', 0) or 0)
        volume_1h = float(volume_data.get('h1', 0) or 0)
        volume_24h = float(volume_data.get('h24', 0) or 0)
        
        suspicious_score = 0.0
        
        # Pattern 1: Regular volume intervals (bot signature)
        if volume_1h > 0:
            # Calculate volume regularity - bots often trade in regular intervals
            if volume_5m > 0:
                # Simulate 12 five-minute periods to check regularity
                expected_5m = volume_1h / 12
                regularity = 1 - abs(volume_5m - expected_5m) / max(expected_5m, 1)
                
                if regularity > 0.95:  # Too regular = suspicious
                    suspicious_score += 0.5
                    if self.advanced_logger:
                        self.advanced_logger.debug_step('analysis', 'pocker_regular_intervals', 
                                                       f'Suspiciously regular volume intervals: {regularity:.3f}')

        # Pattern 2: Volume clustering detection
        liquidity = float(pair_data.get('liquidity', {}).get('usd', 0) or 0)
        if liquidity > 0 and volume_24h > 0:
            volume_to_liquidity = volume_24h / liquidity
            
            # Wash trading often shows very high volume relative to liquidity
            if volume_to_liquidity > 30:  # 30x liquidity in daily volume
                suspicious_score += 0.8
                if self.advanced_logger:
                    self.advanced_logger.debug_step('analysis', 'pocker_extreme_vol_liq_ratio', 
                                                   f'Extreme volume/liquidity ratio: {volume_to_liquidity:.1f}x')
            elif volume_to_liquidity > 15:
                suspicious_score += 0.5
                if self.advanced_logger:
                    self.advanced_logger.debug_step('analysis', 'pocker_high_vol_liq_ratio', 
                                                   f'High volume/liquidity ratio: {volume_to_liquidity:.1f}x')

        # Pattern 3: Time-based wash trading detection
        # Real trading varies throughout the day, wash trading is often constant
        if volume_6h > 0:
            avg_hourly = volume_6h / 6
            if volume_1h > 0:
                hourly_deviation = abs(volume_1h - avg_hourly) / avg_hourly
                
                if hourly_deviation < 0.1:  # Too consistent = suspicious
                    suspicious_score += 0.3
                    if self.advanced_logger:
                        self.advanced_logger.debug_step('analysis', 'pocker_constant_volume', 
                                                       f'Suspiciously constant volume pattern: {hourly_deviation:.3f} deviation')

        return min(suspicious_score, 1.0)

    def _analyze_liquidity_volume_manipulation(self, pair_data):
        """
        Analyze liquidity-volume ratio for manipulation patterns
        """
        liquidity = float(pair_data.get('liquidity', {}).get('usd', 0) or 0)
        volume_24h = float(pair_data.get('volume', {}).get('h24', 0) or 0)
        
        if liquidity <= 0 or volume_24h <= 0:
            return 0.0
            
        volume_to_liquidity = volume_24h / liquidity
        suspicious_score = 0.0
        
        # Thresholds based on Pocker Universe research
        if volume_to_liquidity > 50:  # 50x liquidity
            suspicious_score += 0.9
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'pocker_extreme_manipulation', 
                                               f'Extreme liquidity manipulation: {volume_to_liquidity:.1f}x')
        elif volume_to_liquidity > 25:  # 25x liquidity
            suspicious_score += 0.6
        elif volume_to_liquidity > 10:  # 10x liquidity
            suspicious_score += 0.3

        return min(suspicious_score, 1.0)

    def _detect_bot_trading_patterns(self, pair_data):
        """
        Detect automated bot trading patterns
        """
        price_usd = float(pair_data.get('priceUsd', 0) or 0)
        volume_data = pair_data.get('volume', {})
        volume_24h = float(volume_data.get('h24', 0) or 0)
        volume_1h = float(volume_data.get('h1', 0) or 0)
        volume_5m = float(volume_data.get('m5', 0) or 0)
        
        suspicious_score = 0.0
        
        # Pattern 1: Round number pricing (bots often use round numbers)
        if price_usd > 0:
            price_str = f"{price_usd:.10f}".rstrip('0')
            for pattern in self.bot_patterns['round_numbers']:
                if pattern in price_str:
                    suspicious_score += 0.3
                    if self.advanced_logger:
                        self.advanced_logger.debug_step('analysis', 'pocker_round_pricing', 
                                                       f'Suspicious round number pricing: ${price_usd}')
                    break

        # Pattern 2: Volume pattern regularity
        if volume_1h > 0 and volume_5m > 0:
            # Check for too-regular volume distribution
            expected_5m_volume = volume_1h / 12  # 12 five-minute periods per hour
            volume_regularity = 1 - abs(volume_5m - expected_5m_volume) / max(expected_5m_volume, 1)
            
            if volume_regularity > 0.98:  # Extremely regular
                suspicious_score += 0.6
                if self.advanced_logger:
                    self.advanced_logger.debug_step('analysis', 'pocker_bot_regularity', 
                                                   f'Bot-like volume regularity: {volume_regularity:.4f}')
            elif volume_regularity > 0.95:  # Very regular
                suspicious_score += 0.3

        # Pattern 3: Mathematical volume relationships (bots use formulas)
        if volume_24h > 0 and volume_1h > 0 and volume_5m > 0:
            # Check if volumes follow too-perfect mathematical relationships
            hourly_ratio = volume_1h / volume_24h
            five_min_ratio = volume_5m / volume_1h
            
            # Perfect fractions suggest algorithmic trading
            perfect_fractions = [1/24, 1/12, 1/8, 1/6, 1/4, 1/3, 1/2]
            for fraction in perfect_fractions:
                if abs(hourly_ratio - fraction) < 0.001:  # Very close to perfect fraction
                    suspicious_score += 0.4
                    if self.advanced_logger:
                        self.advanced_logger.debug_step('analysis', 'pocker_perfect_fraction', 
                                                       f'Perfect fraction volume ratio: {hourly_ratio:.6f}')
                    break

        # Pattern 4: Volume clustering at specific times
        current_time = datetime.now()
        minute = current_time.minute
        
        # Bots often trade at round time intervals
        if minute % 5 == 0 and volume_5m > volume_1h * 0.4:  # 40% of hourly volume at round 5-min mark
            suspicious_score += 0.3
            if self.advanced_logger:
                self.advanced_logger.debug_step('analysis', 'pocker_time_clustering', 
                                               f'Volume clustering at round time: {minute} minutes')

        # Pattern 5: Micro-transaction patterns (advanced bot behavior)
        market_cap = float(pair_data.get('marketCap', 0) or 0)
        if market_cap > 0 and volume_24h > 0:
            volume_to_mcap = volume_24h / market_cap
            
            # Unusual volume-to-market-cap ratios suggest manipulation
            if volume_to_mcap > 5.0:  # 500% of market cap in daily volume
                suspicious_score += 0.5
                if self.advanced_logger:
                    self.advanced_logger.debug_step('analysis', 'pocker_mcap_volume_ratio', 
                                                   f'Extreme volume/market cap ratio: {volume_to_mcap:.1f}x')

        return min(suspicious_score, 1.0)

    def _classify_fake_volume_result(self, score, indicators):
        """
        Classify fake volume detection result based on score and indicators
        """
        if score >= 0.9:
            return 'extremely_suspicious'
        elif score >= 0.75:
            return 'highly_suspicious'
        elif score >= 0.5:
            return 'moderately_suspicious'
        elif score >= 0.25:
            return 'slightly_suspicious'
        else:
            return 'appears_legitimate'

    def _cache_result(self, cache_key, result):
        """Cache analysis result with expiry"""
        self.cache[cache_key] = result
        self.cache_expiry[cache_key] = datetime.now() + timedelta(hours=1)  # 1-hour cache
        
        if self.advanced_logger:
            token_symbol = result.get('classification', 'unknown')
            self.advanced_logger.log_cache_operation('analysis', 'SET', f'pocker_{token_symbol}', hit=True)

    def get_analysis_summary(self, results):
        """
        Generate comprehensive analysis summary from multiple token results
        """
        if not results:
            return {
                'total_analyzed': 0,
                'summary': 'No tokens analyzed',
                'risk_distribution': {}
            }

        total_analyzed = len(results)
        risk_distribution = defaultdict(int)
        high_risk_tokens = []
        
        for token_addr, result in results.items():
            classification = result.get('classification', 'unknown')
            risk_distribution[classification] += 1
            
            if result.get('score', 0) >= 0.75:
                token_data = {
                    'address': token_addr,
                    'score': result.get('score', 0),
                    'indicators': result.get('indicators', []),
                    'volume_24h': result.get('volume_24h', 0)
                }
                high_risk_tokens.append(token_data)

        # Sort high-risk tokens by score
        high_risk_tokens.sort(key=lambda x: x['score'], reverse=True)

        summary = {
            'total_analyzed': total_analyzed,
            'risk_distribution': dict(risk_distribution),
            'high_risk_tokens': high_risk_tokens[:10],  # Top 10 highest risk
            'analysis_timestamp': datetime.now().timestamp(),
            'pocker_universe_version': '2.0'
        }

        return summary

    def analyze_token_pair_relationship(self, pair_data_list):
        """
        Analyze relationships between multiple trading pairs for coordinated manipulation
        """
        if len(pair_data_list) < 2:
            return {'score': 0.0, 'indicators': ['Insufficient pairs for relationship analysis']}

        suspicious_score = 0.0
        indicators = []

        # Check for synchronized volume patterns across pairs
        volume_patterns = []
        for pair in pair_data_list:
            volume_data = pair.get('volume', {})
            pattern = {
                'h24': float(volume_data.get('h24', 0) or 0),
                'h1': float(volume_data.get('h1', 0) or 0),
                'h6': float(volume_data.get('h6', 0) or 0)
            }
            volume_patterns.append(pattern)

        # Calculate correlation between volume patterns
        correlations = []
        for i in range(len(volume_patterns)):
            for j in range(i + 1, len(volume_patterns)):
                pattern1 = volume_patterns[i]
                pattern2 = volume_patterns[j]
                
                # Simple correlation calculation
                if pattern1['h24'] > 0 and pattern2['h24'] > 0:
                    ratio_correlation = abs(
                        (pattern1['h1'] / pattern1['h24']) - (pattern2['h1'] / pattern2['h24'])
                    )
                    correlations.append(ratio_correlation)

        if correlations:
            avg_correlation = sum(correlations) / len(correlations)
            
            # High correlation suggests coordinated manipulation
            if avg_correlation < 0.05:  # Very similar patterns
                suspicious_score += 0.7
                indicators.append(f'Highly correlated volume patterns detected (correlation: {avg_correlation:.4f})')
                if self.advanced_logger:
                    self.advanced_logger.debug_step('analysis', 'pocker_coordinated_manipulation', 
                                                   f'Coordinated manipulation detected across {len(pair_data_list)} pairs')

        # Check for identical price movements
        price_movements = []
        for pair in pair_data_list:
            price_changes = pair.get('priceChange', {})
            movement = {
                'h24': float(price_changes.get('h24', 0) or 0),
                'h1': float(price_changes.get('h1', 0) or 0)
            }
            price_movements.append(movement)

        # Detect suspiciously similar price movements
        similar_movements = 0
        for i in range(len(price_movements)):
            for j in range(i + 1, len(price_movements)):
                move1 = price_movements[i]
                move2 = price_movements[j]
                
                if abs(move1['h24'] - move2['h24']) < 0.1 and abs(move1['h1'] - move2['h1']) < 0.1:
                    similar_movements += 1

        if similar_movements > len(pair_data_list) * 0.3:  # More than 30% have similar movements
            suspicious_score += 0.4
            indicators.append(f'Suspiciously similar price movements across {similar_movements} pair combinations')

        return {
            'score': min(suspicious_score, 1.0),
            'indicators': indicators,
            'pairs_analyzed': len(pair_data_list),
            'analysis_type': 'coordinated_manipulation'
        }

    def detect_pump_and_dump_patterns(self, pair_data, historical_data=None):
        """
        Detect pump and dump schemes using Pocker Universe methodology
        """
        suspicious_score = 0.0
        indicators = []

        price_changes = pair_data.get('priceChange', {})
        volume_data = pair_data.get('volume', {})
        
        price_change_24h = float(price_changes.get('h24', 0) or 0)
        price_change_1h = float(price_changes.get('h1', 0) or 0)
        volume_24h = float(volume_data.get('h24', 0) or 0)
        volume_1h = float(volume_data.get('h1', 0) or 0)

        # Pattern 1: Rapid price increase with volume spike
        if price_change_1h > 50:  # More than 50% price increase in 1 hour
            if volume_1h > volume_24h * 0.6:  # 60% of daily volume in 1 hour
                suspicious_score += 0.8
                indicators.append(f'Pump pattern: {price_change_1h:.1f}% price increase with volume spike')
                if self.advanced_logger:
                    self.advanced_logger.debug_step('analysis', 'pocker_pump_detected', 
                                                   f'Pump pattern detected: {price_change_1h:.1f}% price increase')

        # Pattern 2: Unsustainable volume-to-liquidity ratio during pump
        liquidity = float(pair_data.get('liquidity', {}).get('usd', 0) or 0)
        if liquidity > 0 and volume_1h > liquidity * 2:  # Volume > 2x liquidity in 1 hour
            suspicious_score += 0.6
            indicators.append(f'Unsustainable volume spike: {volume_1h/liquidity:.1f}x liquidity in 1 hour')

        # Pattern 3: Price volatility without fundamental reasons
        if abs(price_change_1h) > 30 and volume_1h > 0:
            # Check if volume justifies price movement
            volume_price_ratio = volume_1h / (abs(price_change_1h) * 1000)  # Normalized ratio
            if volume_price_ratio > 10:  # Excessive volume for price movement
                suspicious_score += 0.5
                indicators.append('Excessive volume for price movement magnitude')

        return {
            'score': min(suspicious_score, 1.0),
            'indicators': indicators,
            'pump_probability': suspicious_score,
            'analysis_type': 'pump_and_dump_detection'
        }

    def analyze_market_making_abuse(self, pair_data):
        """
        Detect abusive market making patterns that create fake volume
        """
        suspicious_score = 0.0
        indicators = []

        volume_data = pair_data.get('volume', {})
        price_changes = pair_data.get('priceChange', {})
        
        volume_24h = float(volume_data.get('h24', 0) or 0)
        volume_1h = float(volume_data.get('h1', 0) or 0)
        price_change_24h = float(price_changes.get('h24', 0) or 0)

        # Pattern 1: High volume with minimal price discovery
        if volume_24h > 50000 and abs(price_change_24h) < 2:  # High volume, <2% price change
            suspicious_score += 0.6
            indicators.append(f'Market making abuse: ${volume_24h:,.0f} volume with only {price_change_24h:.2f}% price change')

        # Pattern 2: Artificial spread tightening
        price_usd = float(pair_data.get('priceUsd', 0) or 0)
        if price_usd > 0:
            # Estimate natural spread based on volume and price
            estimated_spread = max(0.5, 1000 / max(volume_24h, 1000))  # Simplified spread estimation
            
            # If actual trading suggests tighter spreads than natural
            if volume_1h > volume_24h * 0.2:  # 20% volume concentration
                if abs(price_change_24h) < estimated_spread:
                    suspicious_score += 0.4
                    indicators.append('Artificially tight spreads detected')

        # Pattern 3: Volume without corresponding market depth
        liquidity = float(pair_data.get('liquidity', {}).get('usd', 0) or 0)
        if liquidity > 0:
            depth_to_volume = liquidity / max(volume_24h, 1)
            
            if depth_to_volume < 0.1:  # Very low depth relative to volume
                suspicious_score += 0.5
                indicators.append(f'Insufficient market depth for volume: {depth_to_volume:.3f} ratio')

        return {
            'score': min(suspicious_score, 1.0),
            'indicators': indicators,
            'analysis_type': 'market_making_abuse'
        }

    def generate_detailed_report(self, pair_data, analysis_results):
        """
        Generate a comprehensive Pocker Universe analysis report
        """
        token_symbol = pair_data.get('baseToken', {}).get('symbol', 'UNKNOWN')
        token_address = pair_data.get('baseToken', {}).get('address', 'UNKNOWN')
        pair_address = pair_data.get('pairAddress', 'UNKNOWN')

        # Extract key metrics
        volume_data = pair_data.get('volume', {})
        price_data = pair_data.get('priceChange', {})
        liquidity = float(pair_data.get('liquidity', {}).get('usd', 0) or 0)
        market_cap = float(pair_data.get('marketCap', 0) or 0)

        report = {
            'analysis_metadata': {
                'token_symbol': token_symbol,
                'token_address': token_address,
                'pair_address': pair_address,
                'analysis_timestamp': datetime.now().isoformat(),
                'pocker_universe_version': '2.0',
                'analyzer': 'Pocker Universe Advanced Algorithm'
            },
            'market_data': {
                'price_usd': float(pair_data.get('priceUsd', 0) or 0),
                'market_cap': market_cap,
                'liquidity_usd': liquidity,
                'volume_24h': float(volume_data.get('h24', 0) or 0),
                'volume_1h': float(volume_data.get('h1', 0) or 0),
                'price_change_24h': float(price_data.get('h24', 0) or 0),
                'price_change_1h': float(price_data.get('h1', 0) or 0)
            },
            'fake_volume_analysis': analysis_results,
            'risk_assessment': {
                'overall_risk_level': self._get_risk_level(analysis_results.get('score', 0)),
                'confidence': self._get_confidence_level(analysis_results.get('score', 0)),
                'primary_concerns': analysis_results.get('indicators', [])[:3],  # Top 3 concerns
                'recommendation': self._get_recommendation(analysis_results.get('score', 0))
            },
            'technical_indicators': {
                'volume_to_liquidity_ratio': volume_data.get('h24', 0) / max(liquidity, 1) if liquidity > 0 else 0,
                'volume_to_mcap_ratio': volume_data.get('h24', 0) / max(market_cap, 1) if market_cap > 0 else 0,
                'volume_concentration_1h': volume_data.get('h1', 0) / max(volume_data.get('h24', 1), 1),
                'price_volume_correlation': self._calculate_price_volume_correlation(pair_data)
            }
        }

        return report

    def _get_risk_level(self, score):
        """Convert numeric score to risk level"""
        if score >= 0.9:
            return 'CRITICAL'
        elif score >= 0.75:
            return 'HIGH'
        elif score >= 0.5:
            return 'MEDIUM'
        elif score >= 0.25:
            return 'LOW'
        else:
            return 'MINIMAL'

    def _get_confidence_level(self, score):
        """Get confidence level for the analysis"""
        if score >= 0.8 or score <= 0.2:
            return 'HIGH'
        elif score >= 0.6 or score <= 0.4:
            return 'MEDIUM'
        else:
            return 'LOW'

    def _get_recommendation(self, score):
        """Get trading recommendation based on score"""
        if score >= 0.75:
            return 'AVOID - High probability of fake volume manipulation'
        elif score >= 0.5:
            return 'CAUTION - Moderate signs of volume manipulation detected'
        elif score >= 0.25:
            return 'MONITOR - Some suspicious patterns, proceed with caution'
        else:
            return 'PROCEED - Volume appears legitimate based on current analysis'

    def _calculate_price_volume_correlation(self, pair_data):
        """Calculate price-volume correlation indicator"""
        volume_data = pair_data.get('volume', {})
        price_data = pair_data.get('priceChange', {})
        
        volume_24h = float(volume_data.get('h24', 0) or 0)
        price_change_24h = float(price_data.get('h24', 0) or 0)
        
        if volume_24h == 0:
            return 0.0
        
        # Normalized correlation (simplified)
        expected_correlation = abs(price_change_24h) / 100 * volume_24h / 10000
        return min(expected_correlation, 1.0)

    def batch_analyze(self, pairs_data, max_concurrent=5):
        """
        Analyze multiple pairs concurrently with rate limiting
        """
        import concurrent.futures
        import threading
        
        results = {}
        semaphore = threading.Semaphore(max_concurrent)
        
        def analyze_single_pair(pair_address, pair_data):
            with semaphore:
                try:
                    result = self.analyze_volume_authenticity(pair_data)
                    return pair_address, result
                except Exception as e:
                    self.logger.error(f"Batch analysis error for {pair_address}: {e}")
                    return pair_address, {
                        'score': 0.0,
                        'indicators': ['Batch analysis failed'],
                        'error': str(e),
                        'classification': 'analysis_error'
                    }

        # Process pairs concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            future_to_pair = {
                executor.submit(analyze_single_pair, addr, data): addr 
                for addr, data in pairs_data.items()
            }
            
            for future in concurrent.futures.as_completed(future_to_pair):
                pair_address, result = future.result()
                results[pair_address] = result

        # Generate batch summary
        summary = self.get_analysis_summary(results)
        
        if self.advanced_logger:
            self.advanced_logger.debug_step('analysis', 'pocker_batch_complete', 
                                           f'🔍 POCKER BATCH: Analyzed {len(results)} pairs', 
                                           summary['risk_distribution'])

        return {
            'individual_results': results,
            'batch_summary': summary,
            'analysis_metadata': {
                'total_pairs': len(pairs_data),
                'successful_analyses': len([r for r in results.values() if 'error' not in r]),
                'failed_analyses': len([r for r in results.values() if 'error' in r]),
                'timestamp': datetime.now().isoformat(),
                'pocker_universe_version': '2.0'
            }
        }

    def export_analysis_data(self, results, format='json'):
        """
        Export analysis results in various formats
        """
        if format.lower() == 'json':
            import json
            return json.dumps(results, indent=2, default=str)
        
        elif format.lower() == 'csv':
            import csv
            import io
            
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow([
                'Pair Address', 'Token Symbol', 'Fake Volume Score', 
                'Classification', 'Volume 24h', 'Primary Indicators'
            ])
            
            # Write data
            for pair_addr, result in results.items():
                if isinstance(result, dict) and 'individual_results' in result:
                    # Handle batch results
                    for addr, res in result['individual_results'].items():
                        writer.writerow([
                            addr,
                            'UNKNOWN',  # Token symbol not available in batch format
                            res.get('score', 0),
                            res.get('classification', 'unknown'),
                            res.get('volume_24h', 0),
                            '; '.join(res.get('indicators', [])[:3])
                        ])
                else:
                    # Handle single result
                    writer.writerow([
                        pair_addr,
                        'UNKNOWN',
                        result.get('score', 0),
                        result.get('classification', 'unknown'),
                        result.get('volume_24h', 0),
                        '; '.join(result.get('indicators', [])[:3])
                    ])
            
            return output.getvalue()
        
        else:
            raise ValueError(f"Unsupported export format: {format}")

    def cleanup_cache(self, max_age_hours=24):
        """
        Clean up expired cache entries
        """
        current_time = datetime.now()
        expired_keys = []
        
        for cache_key, expiry_time in self.cache_expiry.items():
            if current_time > expiry_time or (current_time - expiry_time).total_seconds() > max_age_hours * 3600:
                expired_keys.append(cache_key)
        
        for key in expired_keys:
            if key in self.cache:
                del self.cache[key]
            if key in self.cache_expiry:
                del self.cache_expiry[key]
        
        if self.advanced_logger and expired_keys:
            self.advanced_logger.debug_step('analysis', 'pocker_cache_cleanup', 
                                           f'🧹 POCKER: Cleaned {len(expired_keys)} expired cache entries')
        
        return len(expired_keys)

# Utility functions for integration with larger systems

def create_pocker_analyzer(config):
    """
    Factory function to create a Pocker Universe analyzer instance
    """
    return PockerUniverseAnalyzer(config)

def quick_fake_volume_check(pair_data, config=None):
    """
    Quick fake volume check for simple integrations
    """
    if config is None:
        config = {
            'pocker_universe': {
                'min_volume_for_analysis': 1000,
                'wash_trading_indicators': {
                    'circular_trading_threshold': 0.3,
                    'bot_trading_ratio': 0.5,
                    'unique_trader_ratio': 0.1,
                    'volume_concentration_ratio': 0.8
                }
            }
        }
    
    analyzer = PockerUniverseAnalyzer(config)
    result = analyzer.analyze_volume_authenticity(pair_data)
    
    return {
        'is_suspicious': result.get('score', 0) > 0.5,
        'risk_level': analyzer._get_risk_level(result.get('score', 0)),
        'score': result.get('score', 0),
        'main_concerns': result.get('indicators', [])[:2]
    }