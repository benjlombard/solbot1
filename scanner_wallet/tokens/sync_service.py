#!/usr/bin/env python3
"""
Token Data Synchronization Backend with Historical Tracking
Continuously monitors new tokens from the processing queue and enriches them with external API data.
"""
import sqlite3
import requests
import time
import logging
import json
import math
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Set, Tuple
import threading
from dataclasses import dataclass
import sys
import os
import signal
import functools
from collections import deque, defaultdict
import asyncio
import aiohttp
from pathlib import Path

project_root = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(project_root))

# Import du système de configuration et logging du projet
from core.config import get_config
from core.logger import get_logger, SolanaWalletLogger

# Variables globales
config = None
logger = None

def setup_sync_service_logger(config):
    """Configure un logger spécialisé pour le service de synchronisation"""
    global logger
    
    # Configuration spécialisée pour ce script
    sync_log_file = os.getenv('SYNC_SERVICE_LOG_FILE', 'sync_service.log')
    sync_log_level = os.getenv('SYNC_SERVICE_LOG_LEVEL', config.logging.level.value)
    sync_log_max_size = int(os.getenv('SYNC_SERVICE_LOG_MAX_SIZE_MB', '50'))
    sync_log_backup_count = int(os.getenv('SYNC_SERVICE_LOG_BACKUP_COUNT', '10'))
    
    # Créer le logger spécialisé avec fichier dédié
    sync_logger = SolanaWalletLogger(
        log_level=sync_log_level,
        log_file=str(Path(config.logging.base_dir) / sync_log_file),
        console_output=config.logging.console_output,
        json_output=config.logging.json_output,
        max_file_size=sync_log_max_size * 1024 * 1024,
        backup_count=sync_log_backup_count,
        max_age_days=config.logging.max_age_days,
        force_reconfigure=True
    )
    
    logger = sync_logger.get_logger('token_sync')
    
    logger.info("🚀 Token Sync Service démarré")
    logger.info(f"📊 Base de données: {config.database.get_full_path()}")
    logger.info(f"📝 Log fichier: {Path(config.logging.base_dir) / sync_log_file}")
    logger.info(f"📋 Niveau de log: {sync_log_level}")
    
    return logger

@dataclass
class ApiCallStats:
    """Statistics for a specific API endpoint"""
    total_calls: int = 0
    total_duration: float = 0.0
    calls_5m: deque = None
    calls_30m: deque = None
    calls_1h: deque = None
    
    def __post_init__(self):
        if self.calls_5m is None:
            self.calls_5m = deque()
        if self.calls_30m is None:
            self.calls_30m = deque()
        if self.calls_1h is None:
            self.calls_1h = deque()


@dataclass
class TokenTypeResult:
    token_type: str  # "dex_listed", "pump_prebond", "pump_graduated", "unknown"
    confidence: float  # 0.0 à 1.0
    source_data: Dict = None
    needs_pump_enrichment: bool = False
    needs_dex_enrichment: bool = False

    def __post_init__(self):
        if self.source_data is None:
            self.source_data = {}
    

class CycleLogger:
    """Logger spécialisé pour les cycles de synchronisation"""
    
    def __init__(self, logger):
        self.logger = logger
        self.cycle_count = 0
        self.cumulative_stats = {
            'total_cycles': 0,
            'total_duration': 0.0,
            'total_new_tokens': 0,
            'total_updated_tokens': 0,
            'total_historized_tokens': 0,
            'total_api_calls': {},
            'start_time': None
        }
        self.current_cycle = None
    
    def start_cycle(self, cycle_id: int):
        """Démarre un nouveau cycle"""
        self.cycle_count += 1
        self.current_cycle = {
            'id': cycle_id,
            'number': self.cycle_count,
            'start_time': datetime.now(),
            'end_time': None,
            'duration': 0.0,
            'new_tokens': 0,
            'updated_tokens': 0,
            'historized_tokens': 0,
            'creation_timestamps': 0,
            'dead_tokens_marked': 0,
            'pumpfun_updated': 0,
            'api_calls': {},
            'errors': []
        }
        
        if self.cumulative_stats['start_time'] is None:
            self.cumulative_stats['start_time'] = self.current_cycle['start_time']
        
        # Log de début de cycle (concis)
        self.logger.info(f"🔄 CYCLE {self.cycle_count} STARTED - ID: {cycle_id}")
    
    def end_cycle(self):
        """Termine le cycle courant et affiche les statistiques"""
        if not self.current_cycle:
            return
        
        self.current_cycle['end_time'] = datetime.now()
        self.current_cycle['duration'] = (
            self.current_cycle['end_time'] - self.current_cycle['start_time']
        ).total_seconds()
        
        # Mise à jour des stats cumulées
        self._update_cumulative_stats()
        
        # Affichage des logs
        self._log_cycle_summary()
        self._log_cumulative_summary()
        
        self.current_cycle = None
    
    def record_operation(self, operation: str, count: int):
        """Enregistre une opération du cycle"""
        if not self.current_cycle:
            return
        
        if operation == 'new_tokens':
            self.current_cycle['new_tokens'] += count
        elif operation == 'updated_tokens':
            self.current_cycle['updated_tokens'] += count
        elif operation == 'historized_tokens':
            self.current_cycle['historized_tokens'] += count
        elif operation == 'creation_timestamps':
            self.current_cycle['creation_timestamps'] += count
        elif operation == 'dead_tokens_marked':
            self.current_cycle['dead_tokens_marked'] += count
        elif operation == 'pumpfun_updated':
            self.current_cycle['pumpfun_updated'] += count
    
    def record_api_call(self, api_name: str, count: int = 1):
        """Enregistre des appels API"""
        if not self.current_cycle:
            return
        
        if api_name not in self.current_cycle['api_calls']:
            self.current_cycle['api_calls'][api_name] = 0
        self.current_cycle['api_calls'][api_name] += count
    
    def record_error(self, error_msg: str):
        """Enregistre une erreur"""
        if not self.current_cycle:
            return
        self.current_cycle['errors'].append(error_msg)
    
    def _update_cumulative_stats(self):
        """Met à jour les statistiques cumulées"""
        cycle = self.current_cycle
        cumul = self.cumulative_stats
        
        cumul['total_cycles'] += 1
        cumul['total_duration'] += cycle['duration']
        cumul['total_new_tokens'] += cycle['new_tokens']
        cumul['total_updated_tokens'] += cycle['updated_tokens']
        cumul['total_historized_tokens'] += cycle['historized_tokens']
        
        # Mise à jour des appels API cumulés
        for api_name, count in cycle['api_calls'].items():
            if api_name not in cumul['total_api_calls']:
                cumul['total_api_calls'][api_name] = 0
            cumul['total_api_calls'][api_name] += count
    
    def _log_cycle_summary(self):
        """Affiche le résumé du cycle"""
        cycle = self.current_cycle
        
        self.logger.info("=" * 80)
        self.logger.info(f"📊 CYCLE {cycle['number']} SUMMARY - ID: {cycle['id']}")
        self.logger.info(f"⏰ Start: {cycle['start_time'].strftime('%H:%M:%S')}")
        self.logger.info(f"⏰ End: {cycle['end_time'].strftime('%H:%M:%S')}")
        self.logger.info(f"⏱️ Duration: {cycle['duration']:.1f}s")
        self.logger.info("-" * 40)
        
        # Opérations
        self.logger.info("🔢 OPERATIONS:")
        self.logger.info(f"  ➕ New tokens inserted: {cycle['new_tokens']}")
        self.logger.info(f"  🔄 Tokens updated: {cycle['updated_tokens']}")
        self.logger.info(f"  📈 Tokens historized: {cycle['historized_tokens']}")
        
        if cycle['creation_timestamps'] > 0:
            self.logger.info(f"  ⏰ Creation timestamps: {cycle['creation_timestamps']}")
        if cycle['dead_tokens_marked'] > 0:
            self.logger.info(f"  💀 Dead tokens marked: {cycle['dead_tokens_marked']}")
        if cycle['pumpfun_updated'] > 0:
            self.logger.info(f"  🚀 Pump.fun updated: {cycle['pumpfun_updated']}")
        
        # API Calls
        if cycle['api_calls']:
            self.logger.info("🌐 API CALLS:")
            total_api_calls = sum(cycle['api_calls'].values())
            self.logger.info(f"  📡 Total: {total_api_calls} calls")
            
            # Grouper par type d'API
            dex_calls = sum(v for k, v in cycle['api_calls'].items() if 'dexscreener' in k.lower())
            pump_calls = sum(v for k, v in cycle['api_calls'].items() if 'pumpfun' in k.lower())
            rug_calls = cycle['api_calls'].get('rugcheck', 0)
            solana_calls = sum(v for k, v in cycle['api_calls'].items() if 'solanatracker' in k.lower())
            other_calls = total_api_calls - dex_calls - pump_calls - rug_calls - solana_calls
            
            if dex_calls > 0:
                self.logger.info(f"  🔸 DexScreener: {dex_calls} calls")
            if pump_calls > 0:
                self.logger.info(f"  🚀 Pump.fun: {pump_calls} calls")
            if rug_calls > 0:
                self.logger.info(f"  🔒 Rugcheck: {rug_calls} calls")
            if solana_calls > 0:
                self.logger.info(f"  ⚡ SolanaTracker: {solana_calls} calls")
            if other_calls > 0:
                self.logger.info(f"  🔹 Other: {other_calls} calls")
        
        # Erreurs
        if cycle['errors']:
            self.logger.warning(f"⚠️ ERRORS: {len(cycle['errors'])} errors occurred")
            for error in cycle['errors'][:3]:  # Max 3 erreurs affichées
                self.logger.warning(f"  ❌ {error}")
            if len(cycle['errors']) > 3:
                self.logger.warning(f"  ... and {len(cycle['errors']) - 3} more errors")
    
    def _log_cumulative_summary(self):
        """Affiche le résumé cumulé"""
        cumul = self.cumulative_stats
        
        if cumul['total_cycles'] == 0:
            return
        
        avg_duration = cumul['total_duration'] / cumul['total_cycles']
        runtime = (datetime.now() - cumul['start_time']).total_seconds()
        
        self.logger.info("-" * 40)
        self.logger.info("📈 CUMULATIVE TOTALS:")
        self.logger.info(f"  🔄 Total cycles: {cumul['total_cycles']}")
        self.logger.info(f"  ⏱️ Average cycle time: {avg_duration:.1f}s")
        self.logger.info(f"  🕐 Total runtime: {runtime/3600:.1f}h")
        self.logger.info(f"  ➕ Total new tokens: {cumul['total_new_tokens']}")
        self.logger.info(f"  🔄 Total updated tokens: {cumul['total_updated_tokens']}")
        self.logger.info(f"  📈 Total historized: {cumul['total_historized_tokens']}")
        
        if cumul['total_api_calls']:
            total_api = sum(cumul['total_api_calls'].values())
            avg_api_per_cycle = total_api / cumul['total_cycles']
            self.logger.info(f"  📡 Total API calls: {total_api} (avg {avg_api_per_cycle:.1f}/cycle)")
            
            # Top 3 APIs les plus utilisées
            top_apis = sorted(cumul['total_api_calls'].items(), key=lambda x: x[1], reverse=True)[:3]
            for api_name, count in top_apis:
                self.logger.debug(f"    🔸 {api_name}: {count} calls")
        
        self.logger.info("=" * 80)
    
    def get_cycle_stats_for_db(self) -> Dict:
        """Retourne les stats du cycle pour la base de données"""
        if not self.current_cycle:
            return {}
        
        return {
            'cycle_id': self.current_cycle['id'],
            'cycle_number': self.current_cycle['number'],
            'start_time': self.current_cycle['start_time'],
            'end_time': self.current_cycle['end_time'],
            'duration': self.current_cycle['duration'],
            'new_tokens': self.current_cycle['new_tokens'],
            'updated_tokens': self.current_cycle['updated_tokens'],
            'historized_tokens': self.current_cycle['historized_tokens'],
            'total_api_calls': sum(self.current_cycle['api_calls'].values()),
            'api_calls_detail': json.dumps(self.current_cycle['api_calls']),
            'errors_count': len(self.current_cycle['errors'])
        }


class ApiStatsTracker:
    """Track detailed API statistics per endpoint"""
    
    def __init__(self, db_service=None):
        self.stats = defaultdict(lambda: ApiCallStats())
        self.lock = threading.Lock()
        self.db_service = db_service  # Référence au service pour accès DB
        self.current_cycle_id = None
    
    def set_current_cycle(self, cycle_id: int):
        """Set the current sync cycle ID for tracking"""
        self.current_cycle_id = cycle_id

    def record_call(self, api_name: str, duration: float, success: bool = True, 
                   http_status: int = None, error_msg: str = None):
        """Record an API call with duration and store in database"""
        current_time = time.time()
        duration_ms = int(duration * 1000)  # Convert to milliseconds
        
        with self.lock:
            # Update in-memory stats (existing logic)
            api_stats = self.stats[api_name]
            api_stats.total_calls += 1
            api_stats.total_duration += duration
            
            call_record = (current_time, duration)
            api_stats.calls_5m.append(call_record)
            api_stats.calls_30m.append(call_record)
            api_stats.calls_1h.append(call_record)
            
            self._clean_old_records(api_stats, current_time)
        
        # Store in database (non-blocking)
        if self.db_service:
            try:
                self._store_api_call_to_db(
                    api_name, int(current_time), duration_ms, 
                    success, http_status, error_msg
                )
            except Exception as e:
                # Don't fail the API call if DB storage fails
                print(f"Warning: Failed to store API metric to DB: {e}")
    
    
    
    def _store_api_call_to_db(self, api_name: str, timestamp: int, duration_ms: int,
                         success: bool, http_status: int, error_msg: str):
        """Store API call metrics to database - DEBUG VERSION"""
        try:
            #print(f"🔍 DEBUG DB: Storing {api_name} - cycle: {self.current_cycle_id}, duration: {duration_ms}ms")
            
            with self.db_service.get_db_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO api_metrics (
                        api_name, call_timestamp, duration_ms, success,
                        http_status_code, error_message, sync_cycle_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (api_name, timestamp, duration_ms, success, 
                    http_status, error_msg, self.current_cycle_id))
                
                conn.commit()
                
                # DEBUG: Verify insertion
                cursor.execute("SELECT last_insert_rowid()")
                row_id = cursor.fetchone()[0]
                ##print(f"🔍 DEBUG DB: Inserted API metric with ID {row_id}")
                
                return True
                
        except Exception as e:
            #print(f"❌ DEBUG DB: Failed to store API metric: {e}")
            # Log but don't raise - DB storage is not critical for API functionality
            if hasattr(self.db_service, 'logger'):
                self.db_service.logger.debug(f"Failed to store API metric: {e}")
            return False

    def _clean_old_records(self, api_stats: ApiCallStats, current_time: float):
        """Remove old records from time windows"""
        # 5 minutes
        while api_stats.calls_5m and current_time - api_stats.calls_5m[0][0] > 300:
            api_stats.calls_5m.popleft()
        
        # 30 minutes
        while api_stats.calls_30m and current_time - api_stats.calls_30m[0][0] > 1800:
            api_stats.calls_30m.popleft()
        
        # 1 hour
        while api_stats.calls_1h and current_time - api_stats.calls_1h[0][0] > 3600:
            api_stats.calls_1h.popleft()
    
    def get_stats(self, api_name: str = None) -> Dict:
        """Get statistics for specific API or all APIs"""
        current_time = time.time()
        
        with self.lock:
            if api_name:
                if api_name not in self.stats:
                    return {}
                return self._format_api_stats(api_name, self.stats[api_name], current_time)
            else:
                # Return all APIs
                result = {}
                for name, stats in self.stats.items():
                    result[name] = self._format_api_stats(name, stats, current_time)
                return result
    
    def _format_api_stats(self, name: str, stats: ApiCallStats, current_time: float) -> Dict:
        """Format stats for a single API"""
        # Clean old records first
        self._clean_old_records(stats, current_time)
        
        # Calculate averages
        avg_duration = stats.total_duration / stats.total_calls if stats.total_calls > 0 else 0
        
        # Count calls in time windows
        calls_5m = len(stats.calls_5m)
        calls_30m = len(stats.calls_30m)
        calls_1h = len(stats.calls_1h)
        
        # Calculate average durations for time windows
        avg_5m = sum(d for _, d in stats.calls_5m) / calls_5m if calls_5m > 0 else 0
        avg_30m = sum(d for _, d in stats.calls_30m) / calls_30m if calls_30m > 0 else 0
        avg_1h = sum(d for _, d in stats.calls_1h) / calls_1h if calls_1h > 0 else 0
        
        return {
            'total_calls': stats.total_calls,
            'total_duration_seconds': round(stats.total_duration, 2),
            'avg_duration_seconds': round(avg_duration, 3),
            'calls_5m': calls_5m,
            'calls_30m': calls_30m,
            'calls_1h': calls_1h,
            'avg_duration_5m': round(avg_5m, 3),
            'avg_duration_30m': round(avg_30m, 3),
            'avg_duration_1h': round(avg_1h, 3),
            'rate_per_minute_5m': round(calls_5m / 5, 2),
            'rate_per_minute_30m': round(calls_30m / 30, 2),
            'rate_per_minute_1h': round(calls_1h / 60, 2)
        }


@dataclass
class TokenData:
    """Data structure for token information"""
    address: str
    symbol: str = None
    name: str = None
    decimals: int = 9
    price_usd: float = 0.0
    logo_uri: str = None
    coingecko_id: str = None
    is_verified: bool = False
    timestamp_token_created: int = 0
    creator_address: str = None  
    bonding_curve_progress: float = 0.0    
    holder_count: int = 0  
    market_cap: float = 0.0
    volume_5m: float = 0.0
    volume_1h: float = 0.0
    volume_6h: float = 0.0
    volume_24h: float = 0.0
    price_change_5m: float = 0.0
    price_change_1h: float = 0.0
    price_change_6h: float = 0.0
    price_change_24h: float = 0.0
    price_volatility_24h: float = 0.0
    liquidity_usd: float = 0.0
    liquidity_sol: float = 0.0
    fdv: float = 0.0
    rug_risk_score: float = 50.0
    metadata_source: str = None
    original_address: str = None  # For tracking pair -> token conversion

@dataclass
class HistoricalSnapshot:
    """Structure for historical token data snapshot"""
    token_address: str
    snapshot_timestamp: int
    previous_snapshot_id: Optional[int] = None
    # Metrics
    price_usd: float = 0.0
    market_cap: float = 0.0
    volume_24h: float = 0.0
    holder_count: int = 0
    liquidity_usd: float = 0.0
    # Calculated deltas
    price_delta_usd: float = 0.0
    market_cap_delta: float = 0.0
    volume_24h_delta: float = 0.0
    holder_count_delta: int = 0
    # Scores
    viability_score: float = 50.0
    risk_score: float = 50.0
    momentum_score: float = 0.0

def db_retry(max_retries=3, delay=0.2):
    """Decorator to automatically retry database operations"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(self, *args, **kwargs)
                except sqlite3.OperationalError as e:
                    if "database is locked" in str(e) and attempt < max_retries - 1:
                        wait_time = delay * (2 ** attempt)
                        self.logger.warning(f"Database locked in {func.__name__}, retry {attempt + 1}/{max_retries} in {wait_time:.2f}s")
                        time.sleep(wait_time)
                        continue
                    else:
                        self.logger.error(f"Database error in {func.__name__} after {max_retries} attempts: {e}")
                        raise
                except Exception as e:
                    self.logger.error(f"Unexpected error in {func.__name__}: {e}")
                    raise
            return None
        return wrapper
    return decorator


class TokenAnalyzer:
    """Advanced token analysis and scoring system"""
    
    def __init__(self):
        self.logger = logging.getLogger('TokenAnalyzer')
    
    def calculate_viability_score(self, current_data: TokenData, historical_data: List[Dict] = None) -> float:
        """Calculate token viability score (0-100)"""
        score = 0.0
        
        try:
            # 1. Market Cap Stability (25 points)
            if current_data.market_cap > 1000000:  # >1M
                score += 25
            elif current_data.market_cap > 100000:  # >100K
                score += 20
            elif current_data.market_cap > 10000:   # >10K
                score += 15
            elif current_data.market_cap > 1000:    # >1K
                score += 10
            
            # 2. Liquidity Health (25 points)
            if current_data.market_cap > 0:
                liquidity_ratio = current_data.liquidity_usd / current_data.market_cap
                if liquidity_ratio > 0.15:
                    score += 25
                elif liquidity_ratio > 0.10:
                    score += 20
                elif liquidity_ratio > 0.05:
                    score += 15
                elif liquidity_ratio > 0.02:
                    score += 10
            
            # 3. Volume Activity (20 points)
            if current_data.market_cap > 0:
                volume_ratio = current_data.volume_24h / current_data.market_cap
                if volume_ratio > 0.5:
                    score += 20
                elif volume_ratio > 0.2:
                    score += 15
                elif volume_ratio > 0.1:
                    score += 10
                elif volume_ratio > 0.05:
                    score += 5
            
            # 4. Holder Count (15 points)
            if current_data.holder_count > 1000:
                score += 15
            elif current_data.holder_count > 500:
                score += 12
            elif current_data.holder_count > 100:
                score += 10
            elif current_data.holder_count > 50:
                score += 8
            elif current_data.holder_count > 10:
                score += 5
            
            # 5. Price Stability (15 points)
            if abs(current_data.price_change_24h) < 10:  # <10% change
                score += 15
            elif abs(current_data.price_change_24h) < 25:  # <25% change
                score += 10
            elif abs(current_data.price_change_24h) < 50:  # <50% change
                score += 5
            
            # Bonus/Penalty adjustments
            if current_data.is_verified:
                score += 5
            
            if historical_data and len(historical_data) >= 2:
                # Penalize if consistently declining
                recent_prices = [h.get('price_usd', 0) for h in historical_data[-3:]]
                if len(recent_prices) >= 2 and all(recent_prices[i] <= recent_prices[i-1] for i in range(1, len(recent_prices))):
                    score -= 10
        
        except Exception as e:
            self.logger.error(f"Error calculating viability score: {e}")
            return 50.0
        
        return max(0.0, min(100.0, score))
    
    def calculate_risk_score(self, current_data: TokenData, historical_data: List[Dict] = None) -> float:
        """Calculate token risk score (0-100, higher = more risky)"""
        risk = 0.0
        
        try:
            # 1. Liquidity Risk (30 points)
            if current_data.market_cap > 0:
                liquidity_ratio = current_data.liquidity_usd / current_data.market_cap
                if liquidity_ratio < 0.02:
                    risk += 30
                elif liquidity_ratio < 0.05:
                    risk += 20
                elif liquidity_ratio < 0.10:
                    risk += 10
            
            # 2. Volume Risk (25 points)
            if current_data.volume_24h < 1000:  # Very low volume
                risk += 25
            elif current_data.volume_24h < 10000:
                risk += 15
            elif current_data.volume_24h < 50000:
                risk += 10
            
            # 3. Price Volatility Risk (25 points)
            if abs(current_data.price_change_24h) > 80:
                risk += 25
            elif abs(current_data.price_change_24h) > 50:
                risk += 15
            elif abs(current_data.price_change_24h) > 30:
                risk += 10
            
            # 4. Market Cap Risk (20 points)
            if current_data.market_cap < 1000:
                risk += 20
            elif current_data.market_cap < 10000:
                risk += 15
            elif current_data.market_cap < 100000:
                risk += 10
            
            # Historical trend analysis
            if historical_data and len(historical_data) >= 3:
                # Check for consistent decline
                recent_volumes = [h.get('volume_24h', 0) for h in historical_data[-3:]]
                if len(recent_volumes) >= 2:
                    volume_declining = all(recent_volumes[i] <= recent_volumes[i-1] * 0.8 for i in range(1, len(recent_volumes)))
                    if volume_declining:
                        risk += 10
        
        except Exception as e:
            self.logger.error(f"Error calculating risk score: {e}")
            return 50.0
        
        return max(0.0, min(100.0, risk))
    
    def calculate_momentum_score(self, current_data: TokenData, historical_data: List[Dict] = None) -> float:
        """Calculate momentum score (-100 to +100)"""
        momentum = 0.0
        
        try:
            # 1. Price momentum (40%)
            price_momentum = current_data.price_change_24h
            momentum += price_momentum * 0.4
            
            # 2. Volume momentum (30%)
            if historical_data and len(historical_data) >= 2:
                current_volume = current_data.volume_24h
                previous_volume = historical_data[-1].get('volume_24h', 0)
                if previous_volume > 0:
                    volume_change = ((current_volume - previous_volume) / previous_volume) * 100
                    momentum += volume_change * 0.3
            
            # 3. Holder momentum (20%)
            if historical_data and len(historical_data) >= 2:
                current_holders = current_data.holder_count
                previous_holders = historical_data[-1].get('holder_count', 0)
                if previous_holders > 0:
                    holder_change = ((current_holders - previous_holders) / previous_holders) * 100
                    momentum += holder_change * 0.2
            
            # 4. Liquidity momentum (10%)
            if historical_data and len(historical_data) >= 2:
                current_liquidity = current_data.liquidity_usd
                previous_liquidity = historical_data[-1].get('liquidity_usd', 0)
                if previous_liquidity > 0:
                    liquidity_change = ((current_liquidity - previous_liquidity) / previous_liquidity) * 100
                    momentum += liquidity_change * 0.1
        
        except Exception as e:
            self.logger.error(f"Error calculating momentum score: {e}")
            return 0.0
        
        return max(-100.0, min(100.0, momentum))

    def calculate_predictive_scam_score(self, rugcheck_data: Dict) -> float:
        """
        Calcule un score de scam prédictif basé sur les données de RugCheck.
        Le score va de 0 (très sûr) à 100 (très risqué).
        """
        if not rugcheck_data:
            return 50.0  # Score neutre si pas de données

        score = 0.0
        max_score = 100.0
        
        # 1. Autorité du Mint (40 points) - Le plus gros red flag
        if not rugcheck_data.get('mint_authority_revoked', True):
            score += 40
            self.logger.debug(f"[ScamScore] -40pts: Mint authority non révoquée.")

        # 2. Autorité du Freeze (20 points)
        if not rugcheck_data.get('freeze_authority_revoked', True):
            score += 20
            self.logger.debug(f"[ScamScore] -20pts: Freeze authority non révoquée.")

        # 3. Concentration des détenteurs (Top 10) (25 points)
        top_10_pct = rugcheck_data.get('top_10_holders_percentage', 0.0)
        if top_10_pct > 80:
            score += 25
        elif top_10_pct > 60:
            score += 20
        elif top_10_pct > 40:
            score += 15
        elif top_10_pct > 25:
            score += 10
        if top_10_pct > 25:
            self.logger.debug(f"[ScamScore] -{score}pts: Concentration Top 10 holders: {top_10_pct:.1f}%")

        # 4. Risques détectés par RugCheck (15 points)
        risk_count = rugcheck_data.get('risk_count', 0)
        if risk_count >= 5:
            score += 15
        elif risk_count >= 3:
            score += 10
        elif risk_count >= 1:
            score += 5
        if risk_count > 0:
             self.logger.debug(f"[ScamScore] -{score}pts: {risk_count} risques détectés par RugCheck.")

        # 5. Token déjà marqué comme rugged (score maximum direct)
        if rugcheck_data.get('is_rugged', False):
            self.logger.debug(f"[ScamScore] Max score: Token marqué comme rugged.")
            return max_score
            
        # Normalisation du score pour qu'il soit entre 0 et 100
        final_score = min(score, max_score)
        return final_score
    
    def detect_dead_token(self, current_data: TokenData, historical_data: List[Dict] = None) -> Tuple[bool, str]:
        """Detect if a token should be marked as dead"""
        reasons = []
        
        try:
            # 1. Price crash (>90% drop in 24h)
            if current_data.price_change_24h < -90:
                reasons.append("price_crash_90pct")
            
            # 2. Volume death (volume < $100 for 24h)
            if current_data.volume_24h < 100:
                reasons.append("volume_death")
            
            # 3. Liquidity drain (liquidity < 1% of market cap)
            if current_data.market_cap > 0:
                liquidity_ratio = current_data.liquidity_usd / current_data.market_cap
                if liquidity_ratio < 0.01:
                    reasons.append("liquidity_drain")
            
            # 4. Market cap too low
            if current_data.market_cap < 500:  # Less than $500
                reasons.append("market_cap_too_low")
            
            # 5. Historical decline pattern
            if historical_data and len(historical_data) >= 5:
                # Check if consistently declining for 5 snapshots
                recent_prices = [h.get('price_usd', 0) for h in historical_data[-5:]]
                if len(recent_prices) == 5:
                    declining_trend = all(recent_prices[i] <= recent_prices[i-1] * 0.9 for i in range(1, 5))
                    if declining_trend:
                        reasons.append("consistent_decline")
            
            # 6. Zero holders (if data available)
            if current_data.holder_count == 0:
                reasons.append("zero_holders")
            
            # Decision logic
            critical_reasons = ["price_crash_90pct", "liquidity_drain", "market_cap_too_low"]
            has_critical = any(reason in critical_reasons for reason in reasons)
            
            # Mark as dead if:
            # - Has critical reason, OR
            # - Has 3+ reasons, OR
            # - Has volume death + another reason
            is_dead = (has_critical or 
                      len(reasons) >= 3 or 
                      ("volume_death" in reasons and len(reasons) >= 2))
            
            death_reason = ", ".join(reasons) if is_dead else None
            
            return is_dead, death_reason
        
        except Exception as e:
            self.logger.error(f"Error detecting dead token: {e}")
            return False, None

class TokenSyncService:
    """Main service for token synchronization with historical tracking"""
    
    def __init__(self):

        try:
            self.config = get_config()
            self.logger = setup_sync_service_logger(self.config)

            self.db_path = self.config.database.get_full_path()

            self.logger.info("✅ Configuration et logging initialisés")
            self.logger.info(f"📊 Base de données: {self.db_path}")
        except Exception as e:
                print(f"❌ Erreur lors du chargement de la configuration: {e}")
                raise

        self.running = False
        self.analyzer = TokenAnalyzer()
        self.cycle_logger = CycleLogger(self.logger)

        try:
            self.api_tracker = ApiStatsTracker(db_service=self)  # ← Modification
            self.logger.debug("✅ API tracker initialized successfully")
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize API tracker: {e}")
            raise
        
        self.current_sync_cycle_id = None
        # Request session for connection pooling
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://pump.fun/'
        })
        
        # Statistics
        self.stats = {
            'processed_tokens': 0,
            'successful_updates': 0,
            'failed_updates': 0,
            'api_calls': 0,
            'tokens_historized': 0,
            'tokens_marked_dead': 0,
            'start_time': None
        }

        
    
        self.logger.debug(f"🔧 API tracker verification: {type(self.api_tracker)}")

    def log_debug_response(self, tokens_requested: List[str], api_response: dict, batch_info: str = ""):
        """Logger la réponse API quand des tokens vont échouer"""
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"debug_api_response_{timestamp}.json"
        
        debug_data = {
            "timestamp": datetime.now().isoformat(),
            "batch_info": batch_info,
            "tokens_requested": tokens_requested,
            "tokens_requested_count": len(tokens_requested),
            "api_response": api_response,
            "pairs_in_response": len(api_response.get('pairs', [])) if isinstance(api_response, dict) else 0
        }
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(debug_data, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"🔍 DEBUG: API response saved to {filename}")
            
        except Exception as e:
            self.logger.error(f"❌ Error saving debug file: {e}")

    def test_api_tracking(self):
        """Test method to verify API tracking is working"""
        self.logger.debug("🧪 Testing API tracking...")
        
        # Record a test call
        self._record_api_call('test_api', api_duration)
        # Get stats
        stats = self.api_tracker.get_stats()
        self.logger.debug(f"Test stats: {stats}")
        
        if 'test_api' in stats:
            self.logger.debug("✅ API tracking is working correctly")
        else:
            self.logger.error("❌ API tracking is not working")
        
        return 'test_api' in stats

    def detect_token_type(self, token_address: str) -> TokenTypeResult:
        """Version améliorée avec fallback intelligent"""
        
        self.logger.debug(f"🔍 [DETECT] === DÉBUT DÉTECTION {token_address[:8]}... ===")
        
        # 1. TEST DEXSCREENER avec timeout plus court
        try:
            self.logger.debug(f"🔍 [DETECT] 1/2 Test DexScreener...")
            
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            start_time = time.time()
            response = self.session.get(url, timeout=self.config.rpc.timeout)
            api_duration = time.time() - start_time
            self._record_api_call('dexscreener_type_detection', api_duration)
            
            if response.status_code == 200:
                data = response.json()
                if data and data.get('pairs'):
                    best_pair = max(data['pairs'], key=lambda p: float(p.get('volume', {}).get('h24', 0) or 0))
                    market_cap = float(best_pair.get('fdv', 0) or 0)
                    
                    self.logger.debug(f"✅ [DETECT] DexScreener: MC=${market_cap:,.0f}")
                    
                    if market_cap > 1000:  # ✅ Seuil plus bas pour capturer plus de tokens
                        return TokenTypeResult(
                            token_type="dex_listed",
                            confidence=0.9,
                            source_data={'market_cap': market_cap, 'pair_data': best_pair},
                            needs_dex_enrichment=True,
                            needs_pump_enrichment=False
                        )
                        
            self.logger.debug(f"❌ [DETECT] DexScreener: pas de données significatives")
            
        except Exception as e:
            self.logger.debug(f"❌ [DETECT] DexScreener échoué: {str(e)[:50]}...")
        
        # 2. TEST PUMP.FUN avec v3 en priorité
        try:
            self.logger.debug(f"🔍 [DETECT] 2/2 Test Pump.fun (v3 priority)...")
            
            pump_data = self.get_pumpfun_data(token_address)
            if pump_data:
                bonding_progress = pump_data.bonding_curve_progress
                market_cap = pump_data.market_cap
                
                self.logger.debug(f"✅ [DETECT] Pump.fun: Bonding={bonding_progress}%, MC=${market_cap:,.0f}")
                
                if bonding_progress < 100:
                    return TokenTypeResult(
                        token_type="pump_prebond", 
                        confidence=0.95,
                        source_data=pump_data.__dict__,
                        needs_pump_enrichment=True,
                        needs_dex_enrichment=False
                    )
                else:
                    return TokenTypeResult(
                        token_type="pump_graduated",
                        confidence=0.85, 
                        source_data=pump_data.__dict__,
                        needs_pump_enrichment=True,
                        needs_dex_enrichment=True
                    )
                    
            self.logger.debug(f"❌ [DETECT] Pump.fun: token non trouvé (530 errors)")
            
        except Exception as e:
            self.logger.debug(f"❌ [DETECT] Pump.fun échoué: {str(e)[:50]}...")
        
        # 3. FALLBACK INTELLIGENT
        self.logger.warning(f"❓ [DETECT] === TOKEN UNKNOWN {token_address[:8]}... (APIs indisponibles) ===")
        
        # ✅ Confidence plus basse si APIs en erreur
        return TokenTypeResult(
            token_type="unknown",
            confidence=0.1,  # Très faible car APIs indisponibles
            needs_pump_enrichment=False,  # ✅ Éviter les appels inutiles si 530
            needs_dex_enrichment=True     # DexScreener plus stable
        )

    def enrich_token_by_type(self, token_address: str, token_type_result: TokenTypeResult) -> TokenData:
        """
        Enrichit un token selon son type détecté
        """
        
        if token_type_result.token_type == "dex_listed":
            return self.enrich_dex_listed_token(token_address)
            
        elif token_type_result.token_type == "pump_prebond":
            return self.enrich_pump_prebond_token(token_address, token_type_result.source_data)
            
        elif token_type_result.token_type == "pump_graduated":
            return self.enrich_pump_graduated_token(token_address, token_type_result.source_data)
            
        else:  # unknown
            return self.enrich_unknown_token(token_address)

    def enrich_dex_listed_token(self, token_address: str) -> Optional[TokenData]:
        """Stratégie pour tokens établis sur DEX - CORRIGÉE"""
        self.logger.debug(f"📊 [DEX] Enrichissement DEX pour {token_address[:8]}...")

        try:
            # ✅ CORRECTION: Ne pas utiliser process_tokens_in_batches_async ici
            # Cette méthode fait déjà l'upsert, on ne peut pas retourner TokenData
            
            # Utiliser l'API DexScreener directement
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            start_time = time.time()
            response = self.session.get(url, timeout=self.config.rpc.timeout)
            api_duration = time.time() - start_time
            self._record_api_call('dexscreener_individual', api_duration)
            
            if response.status_code == 200:
                data = response.json()
                if data and data.get('pairs'):
                    # Prendre la meilleure paire
                    best_pair = max(data['pairs'], key=lambda p: float(p.get('volume', {}).get('h24', 0) or 0))
                    
                    # Créer TokenData
                    token_data = TokenData(
                        address=token_address,
                        symbol=best_pair.get('baseToken', {}).get('symbol'),
                        name=best_pair.get('baseToken', {}).get('name'),
                        price_usd=float(best_pair.get('priceUsd', 0) or 0),
                        market_cap=float(best_pair.get('fdv', 0) or 0),
                        volume_24h=float(best_pair.get('volume', {}).get('h24', 0) or 0),
                        liquidity_usd=float(best_pair.get('liquidity', {}).get('usd', 0) or 0),
                        fdv=float(best_pair.get('fdv', 0) or 0),
                        metadata_source="dexscreener_individual"
                    )
                    
                    self.logger.debug(f"✅ [DEX] TokenData créé via DexScreener")
                    return token_data
                else:
                    self.logger.warning(f"❌ [DEX] Aucune paire trouvée")
                    return None
            else:
                self.logger.warning(f"❌ [DEX] HTTP {response.status_code}")
                return None
                
        except Exception as e:
            self.logger.error(f"❌ [DEX] Erreur: {e}")
            return None

    def enrich_pump_prebond_token(self, token_address: str, pump_data: Dict) -> Optional[TokenData]:
        """Stratégie pour tokens Pump.fun en bonding - CORRIGÉE"""
        self.logger.debug(f"🚀 [PUMP-PRE] Enrichissement prebond pour {token_address[:8]}...")
        
        try:
            # ✅ CORRECTION: Vérifier que pump_data contient des données
            if not pump_data or not isinstance(pump_data, dict):
                self.logger.warning(f"❌ [PUMP-PRE] Données Pump.fun invalides")
                return None
            
            # Créer TokenData depuis les données Pump.fun
            token_data = TokenData(
                address=token_address,
                symbol=pump_data.get('symbol', f"UNK_{token_address[:6]}"),
                name=pump_data.get('name', f"Unknown Token {token_address[:8]}"),
                decimals=pump_data.get('decimals', 6),
                price_usd=float(pump_data.get('price_usd', 0) or 0),
                market_cap=float(pump_data.get('market_cap', 0) or 0),
                volume_24h=float(pump_data.get('volume_24h', 0) or 0),
                bonding_curve_progress=float(pump_data.get('bonding_curve_progress', 0) or 0),
                holder_count=int(pump_data.get('holder_count', 0) or data.get('holders', 0)),  
                creator_address=pump_data.get('creator_address'),
                timestamp_token_created=int(pump_data.get('timestamp_token_created', 0) or 0),
                metadata_source="pump_prebond"
            )
            
            self.logger.debug(f"✅ [PUMP-PRE] TokenData créé - Bonding: {token_data.bonding_curve_progress}%")
            return token_data
            
        except Exception as e:
            self.logger.error(f"❌ [PUMP-PRE] Erreur création TokenData: {e}")
            return None

    def enrich_pump_graduated_token(self, token_address: str, pump_data: Dict) -> TokenData:
        """Stratégie pour tokens Pump.fun gradués"""
        # Essayer DexScreener en priorité, fallback sur Pump.fun
        try:
            dex_data = self.get_comprehensive_dexscreener_data(token_address)
            if dex_data.market_cap > pump_data.get('market_cap', 0):
                # DexScreener a des données plus récentes
                return dex_data
        except:
            pass
        
        # Fallback sur données Pump.fun + enrichissement
        return self.enrich_pump_prebond_token(token_address, pump_data)
    
    def _record_api_call(self, api_name: str, duration: float, success: bool = True, http_status: int = None):
        """Helper method to record API calls in both trackers"""
        self.api_tracker.record_call(api_name, duration, success, http_status)
        self.cycle_logger.record_api_call(api_name, 1)
        self.stats['api_calls'] += 1

    def get_db_connection(self, retries: int = 5, delay: float = 0.1) -> sqlite3.Connection:
        """Get database connection with enhanced error handling and retry logic"""
        for attempt in range(retries):
            try:
                conn = sqlite3.connect(
                    self.db_path,
                    timeout=self.config.database.timeout,
                    check_same_thread=False
                )
                conn.row_factory = sqlite3.Row
                
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL") 
                conn.execute("PRAGMA cache_size=-65536")
                conn.execute("PRAGMA temp_store=memory")
                conn.execute(f"PRAGMA busy_timeout={int(self.config.database.timeout * 1000)}")
                conn.execute("PRAGMA wal_autocheckpoint=1000")
                
                conn.execute("SELECT 1").fetchone()
                
                return conn
                
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < retries - 1:
                    wait_time = delay * (2 ** attempt)
                    self.logger.warning(f"Database locked, retry {attempt + 1}/{retries} in {wait_time:.2f}s")
                    time.sleep(wait_time)
                    continue
                else:
                    self.logger.error(f"Database connection error after {retries} attempts: {e}")
                    raise
            except Exception as e:
                self.logger.error(f"Unexpected database connection error: {e}")
                raise
    
    def check_database_health(self) -> bool:
        """Check database health and fix common issues"""
        try:
            conn = self.get_db_connection()
            try:
                cursor = conn.cursor()
                
                cursor.execute("SELECT 1").fetchone()
                
                cursor.execute("PRAGMA journal_mode")
                journal_mode = cursor.fetchone()[0]
                if journal_mode != 'wal':
                    self.logger.warning(f"Database not in WAL mode: {journal_mode}")
                    cursor.execute("PRAGMA journal_mode=WAL")
                    
                cursor.execute("PRAGMA integrity_check")
                integrity = cursor.fetchone()[0]
                if integrity != 'ok':
                    self.logger.error(f"Database integrity issue: {integrity}")
                    return False
                    
                cursor.execute("PRAGMA optimize")
                
                self.logger.debug("✅ Database health check passed")
                return True
                
            finally:
                conn.close()
                
        except Exception as e:
            self.logger.error(f"❌ Database health check failed: {e}")
            return False

    def historize_token_data(self, token_address: str, current_data: TokenData = None) -> bool:
        """
        Historize current token data before updating
        """
        max_retries = 5
        retry_delay = 0.2
        for attempt in range(max_retries):
            conn = None
            try:
                conn = self.get_db_connection()
                with conn:
                    cursor = conn.cursor()
                    cursor.execute("BEGIN IMMEDIATE")
                    cursor.execute("""
                        SELECT id FROM tokens_history 
                        WHERE token_address = ? 
                        ORDER BY snapshot_timestamp DESC 
                        LIMIT 1
                    """, (token_address,))
                    last_snapshot = cursor.fetchone()
                    previous_snapshot_id = last_snapshot[0] if last_snapshot else None
                
                    cursor.execute("""
                        SELECT * FROM tokens_history 
                        WHERE token_address = ? 
                        ORDER BY snapshot_timestamp DESC 
                        LIMIT 10
                    """, (token_address,))
                    historical_data = [dict(row) for row in cursor.fetchall()]
                
                    current_timestamp = int(time.time())
                
                    if current_data is None:
                        cursor.execute("""
                            SELECT * FROM tokens WHERE address = ?
                        """, (token_address,))
                        token_row = cursor.fetchone()
                        if not token_row:
                            self.logger.warning(f"No current data found for token {token_address}")
                            conn.close()
                            return False


                        def safe_get(row, column, default=0.0):
                            """Safely get value from sqlite3.Row with None handling"""
                            try:
                                value = row[column] if column in row.keys() else default
                                return value if value is not None else default
                            except (KeyError, TypeError):
                                return default

                        snapshot_data = {
                            'price_usd': safe_get(token_row, 'price_usd', 0.0),
                            'market_cap': safe_get(token_row, 'market_cap', 0.0),
                            'fdv': safe_get(token_row, 'fdv', 0.0),
                            'liquidity_usd': safe_get(token_row, 'liquidity_usd', 0.0),
                            'liquidity_sol': safe_get(token_row, 'liquidity_sol', 0.0),
                            'liquidity_mc_ratio': safe_get(token_row, 'liquidity_mc_ratio', 0.0),
                            'volume_mc_ratio': safe_get(token_row, 'volume_mc_ratio', 0.0),
                            'price_volatility_1h': safe_get(token_row, 'price_volatility_1h', 0.0),
                            'volume_5m': safe_get(token_row, 'volume_5m', 0.0),
                            'volume_1h': safe_get(token_row, 'volume_1h', 0.0),
                            'volume_6h': safe_get(token_row, 'volume_6h', 0.0),
                            'volume_24h': safe_get(token_row, 'volume_24h', 0.0),
                            'price_change_5m': safe_get(token_row, 'price_change_5m', 0.0),
                            'price_change_1h': safe_get(token_row, 'price_change_1h', 0.0),
                            'price_change_6h': safe_get(token_row, 'price_change_6h', 0.0),
                            'price_change_24h': safe_get(token_row, 'price_change_24h', 0.0),
                            'holder_count': safe_get(token_row, 'holder_count', 0),
                            'bonding_curve_progress': safe_get(token_row, 'bonding_curve_progress', 0.0),
                            'top_holder_percentage': safe_get(token_row, 'top_holder_percentage', 0.0),
                            'top_10_holders_percentage': safe_get(token_row, 'top_10_holders_percentage', 0.0),
                            'insider_holders_count': safe_get(token_row, 'insider_holders_count', 0),
                            'insider_networks_detected': safe_get(token_row, 'insider_networks_detected', 0),
                            'lp_providers_count': safe_get(token_row, 'lp_providers_count', 0),
                            'has_low_liquidity': safe_get(token_row, 'has_low_liquidity', False),
                            'rug_risk_score': safe_get(token_row, 'rug_risk_score', 50),
                            'rug_raw_score': safe_get(token_row, 'rug_raw_score', 0),
                            'is_rugged': safe_get(token_row, 'is_rugged', False),
                            'risk_count': safe_get(token_row, 'risk_count', 0),
                            'symbol': safe_get(token_row, 'symbol', ''),
                            'name': safe_get(token_row, 'name', ''),
                            'decimals': safe_get(token_row, 'decimals', 9),
                            'creator_address': safe_get(token_row, 'creator_address', None),
                            'logo_uri': safe_get(token_row, 'logo_uri', None),
                            'is_verified': safe_get(token_row, 'is_verified', False),
                            'metadata_source': safe_get(token_row, 'metadata_source', None)
                        }

                        if snapshot_data['market_cap'] > 0:
                            snapshot_data['liquidity_mc_ratio'] = snapshot_data['liquidity_usd'] / snapshot_data['market_cap']
                            snapshot_data['volume_mc_ratio'] = snapshot_data['volume_24h'] / snapshot_data['market_cap']
                        else:
                            snapshot_data['liquidity_mc_ratio'] = 0.0
                            snapshot_data['volume_mc_ratio'] = 0.0

                        score_data = TokenData(
                            address=token_address,
                            symbol=snapshot_data['symbol'],
                            price_usd=snapshot_data['price_usd'],
                            market_cap=snapshot_data['market_cap'],
                            fdv=snapshot_data['fdv'],
                            volume_5m=snapshot_data['volume_5m'],
                            volume_1h=snapshot_data['volume_1h'],
                            volume_6h=snapshot_data['volume_6h'],
                            volume_24h=snapshot_data['volume_24h'],
                            price_change_5m=snapshot_data['price_change_5m'],
                            price_change_1h=snapshot_data['price_change_1h'],
                            price_change_6h=snapshot_data['price_change_6h'],
                            price_change_24h=snapshot_data['price_change_24h'],
                            holder_count=snapshot_data['holder_count'],
                            liquidity_usd=snapshot_data['liquidity_usd'],
                            liquidity_sol=snapshot_data['liquidity_sol'],
                            bonding_curve_progress=snapshot_data['bonding_curve_progress']
                        )
                        self.logger.debug(f"📊 Historizing from DB for {token_address[:8]}... - TH: {snapshot_data['top_holder_percentage']:.2f}%, T10H: {snapshot_data['top_10_holders_percentage']:.2f}%")

                    else:
                        snapshot_data = {
                            'price_usd': current_data.price_usd,
                            'market_cap': current_data.market_cap,
                            'fdv': current_data.fdv,
                            'liquidity_usd': current_data.liquidity_usd,
                            'liquidity_sol': current_data.liquidity_sol,
                            'liquidity_mc_ratio': (current_data.liquidity_usd / current_data.market_cap) if current_data.market_cap > 0 else 0.0,
                            'volume_mc_ratio': (current_data.volume_24h / current_data.market_cap) if current_data.market_cap > 0 else 0.0,
                            'price_volatility_1h': getattr(current_data, 'price_volatility_1h', 0.0),
                            'volume_5m': current_data.volume_5m,
                            'volume_1h': current_data.volume_1h,
                            'volume_6h': current_data.volume_6h,
                            'volume_24h': current_data.volume_24h,
                            'price_change_5m': current_data.price_change_5m,
                            'price_change_1h': current_data.price_change_1h,
                            'price_change_6h': current_data.price_change_6h,
                            'price_change_24h': current_data.price_change_24h,
                            'holder_count': current_data.holder_count,
                            'bonding_curve_progress': current_data.bonding_curve_progress,
                            'top_holder_percentage': getattr(current_data, 'top_holder_percentage', 0.0),
                            'top_10_holders_percentage': getattr(current_data, 'top_10_holders_percentage', 0.0),
                            'insider_holders_count': getattr(current_data, 'insider_holders_count', 0),
                            'insider_networks_detected': getattr(current_data, 'insider_networks_detected', 0),
                            'lp_providers_count': getattr(current_data, 'lp_providers_count', 0),
                            'has_low_liquidity': getattr(current_data, 'has_low_liquidity', False),
                            'rug_risk_score': getattr(current_data, 'rug_risk_score', 50),
                            'rug_raw_score': getattr(current_data, 'rug_raw_score', 0),
                            'is_rugged': getattr(current_data, 'is_rugged', False),
                            'risk_count': getattr(current_data, 'risk_count', 0),
                            'symbol': current_data.symbol,
                            'name': current_data.name,
                            'decimals': current_data.decimals,
                            'creator_address': getattr(current_data, 'creator_address', None),
                            'logo_uri': getattr(current_data, 'logo_uri', None),
                            'is_verified': getattr(current_data, 'is_verified', False),
                            'metadata_source': getattr(current_data, 'metadata_source', None)
                        }
                        score_data = current_data
                    
                    deltas = {
                        'price_delta_usd': 0.0, 
                        'market_cap_delta': 0.0, 
                        'volume_24h_delta': 0.0, 
                        'holder_count_delta': 0,
                        'rug_risk_score_delta': 0.0,
                        'top_holder_percentage_delta': 0.0,
                        'insider_holders_delta': 0
                    }
                    
                    if historical_data:
                        last_snapshot_data = historical_data[0]
                        deltas['price_delta_usd'] = snapshot_data['price_usd'] - (last_snapshot_data.get('price_usd', 0) or 0)
                        deltas['market_cap_delta'] = snapshot_data['market_cap'] - (last_snapshot_data.get('market_cap', 0) or 0)
                        deltas['volume_24h_delta'] = snapshot_data['volume_24h'] - (last_snapshot_data.get('volume_24h', 0) or 0)
                        deltas['holder_count_delta'] = snapshot_data['holder_count'] - (last_snapshot_data.get('holder_count', 0) or 0)
                        deltas['rug_risk_score_delta'] = snapshot_data['rug_risk_score'] - (last_snapshot_data.get('rug_risk_score', 50) or 50)
                        deltas['top_holder_percentage_delta'] = snapshot_data['top_holder_percentage'] - (last_snapshot_data.get('top_holder_percentage', 0) or 0)
                        deltas['insider_holders_delta'] = snapshot_data['insider_holders_count'] - (last_snapshot_data.get('insider_holders_count', 0) or 0)
                    
                    viability_score = self.analyzer.calculate_viability_score(score_data, historical_data)
                    risk_score = self.analyzer.calculate_risk_score(score_data, historical_data)
                    momentum_score = self.analyzer.calculate_momentum_score(score_data, historical_data)
                    
                    # INSERT aligné au schéma tokens_history
                    cursor.execute("""
                        INSERT INTO tokens_history (
                            token_address,
                            price_usd, market_cap, fdv, liquidity_usd, liquidity_sol, liquidity_mc_ratio, volume_mc_ratio,
                            price_volatility_1h,
                            volume_5m, volume_1h, volume_6h, volume_24h,
                            price_change_5m, price_change_1h, price_change_6h, price_change_24h,
                            holder_count, bonding_curve_progress,
                            top_holder_percentage, top_10_holders_percentage, insider_holders_count, insider_networks_detected,
                            lp_providers_count, has_low_liquidity,
                            viability_score, risk_score, momentum_score,
                            rug_risk_score, rug_raw_score, is_rugged, risk_count,
                            creator_address, symbol, name, decimals, logo_uri, is_verified, metadata_source,
                            snapshot_timestamp, previous_snapshot_id,
                            price_delta_usd, market_cap_delta, volume_24h_delta, holder_count_delta,
                            rug_risk_score_delta, top_holder_percentage_delta, insider_holders_delta,created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, DATETIME('now'))
                    """, (
                        token_address,
                        snapshot_data['price_usd'], snapshot_data['market_cap'], snapshot_data['fdv'],
                        snapshot_data['liquidity_usd'], snapshot_data['liquidity_sol'],
                        snapshot_data.get('liquidity_mc_ratio', 0.0), snapshot_data.get('volume_mc_ratio', 0.0),
                        snapshot_data.get('price_volatility_1h', 0.0),
                        snapshot_data['volume_5m'], snapshot_data['volume_1h'], snapshot_data['volume_6h'], snapshot_data['volume_24h'],
                        snapshot_data['price_change_5m'], snapshot_data['price_change_1h'], snapshot_data['price_change_6h'], snapshot_data['price_change_24h'],
                        snapshot_data['holder_count'], snapshot_data['bonding_curve_progress'],
                        snapshot_data['top_holder_percentage'], snapshot_data['top_10_holders_percentage'],
                        snapshot_data['insider_holders_count'], snapshot_data['insider_networks_detected'],
                        snapshot_data['lp_providers_count'], snapshot_data['has_low_liquidity'],
                        viability_score, risk_score, momentum_score,
                        snapshot_data['rug_risk_score'], snapshot_data['rug_raw_score'],
                        snapshot_data['is_rugged'], snapshot_data['risk_count'],
                        snapshot_data.get('creator_address'), snapshot_data['symbol'], snapshot_data['name'],
                        snapshot_data['decimals'], snapshot_data.get('logo_uri'),
                        snapshot_data.get('is_verified', False), snapshot_data.get('metadata_source'),
                        current_timestamp, previous_snapshot_id,
                        deltas['price_delta_usd'], deltas['market_cap_delta'], deltas['volume_24h_delta'], deltas['holder_count_delta'],
                        deltas.get('rug_risk_score_delta', 0.0),
                        deltas.get('top_holder_percentage_delta', 0.0),
                        deltas.get('insider_holders_delta', 0)
                    ))
                    
                    cursor.execute("""
                        UPDATE tokens 
                        SET last_historized_at = ?, history_snapshots_count = COALESCE(history_snapshots_count, 0) + 1
                        WHERE address = ?
                    """, (current_timestamp, token_address))
                    

                self.stats['tokens_historized'] += 1
                
                data_source = "new_data" if current_data else "db_data"
                self.logger.debug(f"✅ Historized token {token_address[:8]}... ({data_source}): V={viability_score:.1f}, R={risk_score:.1f}, M={momentum_score:.1f}, TH={snapshot_data['top_holder_percentage']:.1f}%")
                return True
                
            except sqlite3.OperationalError as e:
                if conn:
                    try:
                        conn.close()
                    except:
                        pass
                        
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    wait_time = base_delay * (2 ** attempt)  # Backoff exponentiel
                    self.logger.warning(f"Database locked during historization, retry {attempt + 1}/{max_retries} in {wait_time:.2f}s")
                    time.sleep(wait_time)
                    continue
                else:
                    self.logger.error(f"❌ Error historizing token {token_address} after {max_retries} attempts: {e}")
                    return False
                    
            except Exception as e:
                if conn:
                    try:
                        conn.close()
                    except:
                        pass
                self.logger.error(f"❌ Unexpected error historizing token {token_address}: {e}")
                return False

        return False

    
    def check_and_mark_dead_tokens(self) -> int:
        """Check for dead tokens and mark them"""
        marked_count = 0
        
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Get tokens that are not marked as dead and have recent data
                cursor.execute("""
                    SELECT address, symbol, price_usd, market_cap, volume_24h, 
                           holder_count, liquidity_usd, price_change_24h, 
                           viability_score, risk_score
                    FROM tokens 
                    WHERE is_dead = 0 
                    AND updated_at > datetime('now', '-7 days')
                """)
                
                tokens_to_check = cursor.fetchall()
                
                for token_row in tokens_to_check:
                    token_address = token_row['address']
                    
                    # Create TokenData object for analysis
                    token_data = TokenData(
                        address=token_address,
                        symbol=token_row['symbol'],
                        price_usd=token_row['price_usd'] or 0.0,
                        market_cap=token_row['market_cap'] or 0.0,
                        volume_24h=token_row['volume_24h'] or 0.0,
                        holder_count=token_row['holder_count'] or 0,
                        liquidity_usd=getattr(token_row, 'liquidity_usd', 0.0) or 0.0,
                        price_change_24h=token_row['price_change_24h'] or 0.0
                    )
                    
                    # Get historical data
                    cursor.execute("""
                        SELECT * FROM tokens_history 
                        WHERE token_address = ? 
                        ORDER BY snapshot_timestamp DESC 
                        LIMIT 10
                    """, (token_address,))
                    historical_data = [dict(row) for row in cursor.fetchall()]
                    
                    # Check if token should be marked as dead
                    is_dead, death_reason = self.analyzer.detect_dead_token(token_data, historical_data)
                    
                    if is_dead:
                        # Mark token as dead
                        cursor.execute("""
                            UPDATE tokens 
                            SET is_dead = 1, 
                                death_reason = ?, 
                                death_timestamp = ?
                            WHERE address = ?
                        """, (death_reason, int(time.time()), token_address))
                        
                        marked_count += 1
                        self.stats['tokens_marked_dead'] += 1
                        
                        self.logger.debug(f"💀 Marked token {token_address} ({token_data.symbol}) as dead: {death_reason}")
                
                conn.commit()
                
        except Exception as e:
            self.logger.error(f"❌ Error checking dead tokens: {e}")
        
        return marked_count
    
    def get_pumpfun_data(self, token_address: str) -> Optional[TokenData]:
        """Get token data from Pump.fun API (unchanged from original)"""
        # URLs Pump.fun (comme dans le script qui fonctionne)
        pump_fun_urls = [
            f"https://frontend-api-v3.pump.fun/coins/{token_address}",
            f"https://frontend-api.pump.fun/coins/{token_address}",
            f"https://frontend-api-v2.pump.fun/coins/{token_address}",
        ]
        
        for i, url in enumerate(pump_fun_urls):
            try:
                start_time = time.time()
                response = self.session.get(url, timeout=self.config.rpc.timeout)
                api_duration = time.time() - start_time
                self._record_api_call(f'pumpfun_v{i+1}', api_duration)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Vérifier que les données sont valides
                    if not data or not isinstance(data, dict):
                        continue
                    
                    # Vérification flexible du mint
                    mint = data.get('mint') or data.get('address') or data.get('tokenAddress')
                    if not mint:
                        # Parfois les données sont dans un format différent
                        if 'id' in data:
                            mint = data.get('id')
                        elif 'contract' in data:
                            mint = data.get('contract')
                    
                    # Si mint correspond ou si on a des données valides sans mint
                    if (mint and mint.lower() == token_address.lower()) or (not mint and (data.get('symbol') or data.get('creator'))):
                        
                        # Parser les données Pump.fun
                        token_data = TokenData(
                            address=token_address,
                            symbol=data.get('symbol'),
                            name=data.get('name'),
                            decimals=data.get('decimals', 6),
                            price_usd=float(data.get('usd_market_cap', 0)) / float(data.get('total_supply', 1)) if data.get('total_supply') else 0.0,
                            timestamp_token_created=int(data['created_timestamp'] / 1000) if data.get('created_timestamp') and data['created_timestamp'] > 1e12 else int(data.get('created_timestamp', 0)),
                            creator_address=data.get('creator'), 
                            bonding_curve_progress=float(data.get('bonding_curve_progress', 0)), 
                            holder_count=int(data.get('holder_count', 0) or data.get('holders', 0)),  
                            market_cap=float(data.get('usd_market_cap', 0)),
                            volume_24h=float(data.get('volume_24h', 0)),
                            logo_uri=data.get('image_uri'),
                            is_verified=data.get('complete', False),
                            metadata_source="pumpfun"
                        )
                        
                        # Calculer le prix si pas directement disponible
                        if token_data.price_usd == 0.0 and data.get('virtual_sol_reserves') and data.get('virtual_token_reserves'):
                            sol_reserves = float(data.get('virtual_sol_reserves', 0))
                            token_reserves = float(data.get('virtual_token_reserves', 1))
                            if token_reserves > 0:
                                price_sol = sol_reserves / token_reserves
                                token_data.price_usd = price_sol * 150  # Approximation SOL/USD
                        
                        # Timestamp de création
                        if 'created_timestamp' in data:
                            token_data.timestamp_token_created = int(data['created_timestamp'] / 1000) if data['created_timestamp'] > 1e12 else int(data['created_timestamp'])
                        
                        self.logger.debug(f"✅ Found Pump.fun data for {token_address[:8]}... (MC: ${token_data.market_cap:,.0f}) via URL {i+1}")
                        return token_data
                    else:
                        self.logger.debug(f"Mint mismatch in URL {i+1}: {mint} != {token_address}")
                        
                elif response.status_code == 404:
                    self.logger.debug(f"404 from Pump.fun URL {i+1}")
                    continue
                elif response.status_code == 530:
                    self.logger.warning(f"530 Server error from Pump.fun URL {i+1}, trying next...")
                    continue
                elif response.status_code == 429:
                    self.logger.warning(f"Rate limited by Pump.fun, waiting...")
                    time.sleep(5)  # Attendre plus longtemps
                    continue
                else:
                    self.logger.debug(f"HTTP {response.status_code} from Pump.fun URL {i+1}")
                    continue
                    
            except Exception as e:
                self.logger.debug(f"Error with Pump.fun URL {i+1}: {e}")
                continue
        
        # Aucune URL n'a fonctionné
        self.logger.debug(f"Token not found on any Pump.fun URL: {token_address[:8]}...")
        return None

    def get_rugcheck_data(self, token_address: str) -> Optional[dict]:
        """Get comprehensive analysis from rugcheck.xyz"""
        try:
            url = f"https://api.rugcheck.xyz/v1/tokens/{token_address}/report"
            start_time = time.time()
            response = self.session.get(url, timeout=self.config.rpc.timeout)
            api_duration = time.time() - start_time
            self._record_api_call('rugcheck', api_duration)
            
            if response.status_code == 200:
                data = response.json()
                self.logger.debug(f"✅ Got rugcheck data for {token_address[:8]}...")
                return data
            
            return None
        except Exception as e:
            self.logger.debug(f"Rugcheck error for {token_address[:8]}...: {e}")
            return None

    def extract_rugcheck_data(self, rugcheck_response: dict) -> dict:
        """Extract useful data from rugcheck response"""
        try:
            # Add proper None check and type validation
            if not rugcheck_response or not isinstance(rugcheck_response, dict):
                self.logger.debug("Invalid or empty rugcheck response")
                return {}
            
            # Additional check for empty dict or missing critical data
            if not rugcheck_response:
                self.logger.debug("Empty rugcheck response dict")
                return {}
                
            security_data = {}
            
            # Scores de sécurité (with safe defaults)
            security_data['rug_risk_score'] = rugcheck_response.get('score_normalised', 50)
            security_data['rug_raw_score'] = rugcheck_response.get('score', 0)
            security_data['is_rugged'] = rugcheck_response.get('rugged', False)
            
            # Autorités (safe access with defaults)
            token_info = rugcheck_response.get('token', {})
            if isinstance(token_info, dict):
                security_data['mint_authority_revoked'] = token_info.get('mintAuthority') is None
                security_data['freeze_authority_revoked'] = token_info.get('freezeAuthority') is None
            else:
                security_data['mint_authority_revoked'] = False
                security_data['freeze_authority_revoked'] = False
            
            # Holders analysis (safe access)
            top_holders = rugcheck_response.get('topHolders', [])
            if isinstance(top_holders, list) and top_holders:
                try:
                    # Get top holder percentage safely
                    first_holder = top_holders[0] if len(top_holders) > 0 else {}
                    security_data['top_holder_percentage'] = float(first_holder.get('pct', 0))
                    
                    # Calculate top 10 holders percentage safely
                    top_10_pct = 0.0
                    for i, holder in enumerate(top_holders[:10]):
                        if isinstance(holder, dict) and 'pct' in holder:
                            try:
                                top_10_pct += float(holder.get('pct', 0))
                            except (ValueError, TypeError):
                                continue
                    security_data['top_10_holders_percentage'] = top_10_pct
                    
                    # Count insider holders safely
                    insider_count = 0
                    for holder in top_holders:
                        if isinstance(holder, dict) and holder.get('insider', False):
                            insider_count += 1
                    security_data['insider_holders_count'] = insider_count
                    
                except Exception as e:
                    self.logger.debug(f"Error processing top holders data: {e}")
                    security_data['top_holder_percentage'] = 0.0
                    security_data['top_10_holders_percentage'] = 0.0
                    security_data['insider_holders_count'] = 0
            else:
                security_data['top_holder_percentage'] = 0.0
                security_data['top_10_holders_percentage'] = 0.0
                security_data['insider_holders_count'] = 0
            
            # Autres données (safe access with type checking)
            security_data['holder_count'] = rugcheck_response.get('totalHolders', 0)
            if not isinstance(security_data['holder_count'], (int, float)):
                security_data['holder_count'] = 0
            else:
                security_data['holder_count'] = int(security_data['holder_count'])
                
            security_data['insider_networks_detected'] = rugcheck_response.get('graphInsidersDetected', 0)
            if not isinstance(security_data['insider_networks_detected'], (int, float)):
                security_data['insider_networks_detected'] = 0
            else:
                security_data['insider_networks_detected'] = int(security_data['insider_networks_detected'])
                
            security_data['lp_providers_count'] = rugcheck_response.get('totalLPProviders', 0)
            if not isinstance(security_data['lp_providers_count'], (int, float)):
                security_data['lp_providers_count'] = 0
            else:
                security_data['lp_providers_count'] = int(security_data['lp_providers_count'])
                
            # Liquidity with safe conversion
            liquidity_raw = rugcheck_response.get('totalMarketLiquidity', 0.0)
            try:
                security_data['liquidity_usd'] = float(liquidity_raw) if liquidity_raw is not None else 0.0
            except (ValueError, TypeError):
                security_data['liquidity_usd'] = 0.0
            
            # Launchpad info (safe access)
            launchpad = rugcheck_response.get('launchpad', {})
            if isinstance(launchpad, dict):
                security_data['launchpad_name'] = launchpad.get('name')
                security_data['is_pump_fun'] = launchpad.get('platform') == 'pump_fun'
            else:
                security_data['launchpad_name'] = None
                security_data['is_pump_fun'] = False
            
            # Risques (safe access)
            risks = rugcheck_response.get('risks', [])
            if isinstance(risks, list):
                security_data['risk_count'] = len(risks)
                security_data['has_low_liquidity'] = any(
                    isinstance(risk, dict) and risk.get('name') == 'Low Liquidity' 
                    for risk in risks
                )
            else:
                security_data['risk_count'] = 0
                security_data['has_low_liquidity'] = False
            
            self.logger.debug(f"Successfully extracted rugcheck data: score={security_data.get('rug_risk_score')}, holders={security_data.get('holder_count')}")
            return security_data
            
        except Exception as e:
            self.logger.error(f"Error extracting rugcheck data: {e}")
            return {
                'rug_risk_score': 50,
                'rug_raw_score': 0,
                'is_rugged': False,
                'mint_authority_revoked': False,
                'freeze_authority_revoked': False,
                'top_holder_percentage': 0.0,
                'top_10_holders_percentage': 0.0,
                'insider_holders_count': 0,
                'holder_count': 0,
                'insider_networks_detected': 0,
                'lp_providers_count': 0,
                'liquidity_usd': 0.0,
                'launchpad_name': None,
                'is_pump_fun': False,
                'risk_count': 0,
                'has_low_liquidity': False
            }

    def clean_token_data(self, token_data: TokenData) -> TokenData:
        """Clean token data to avoid SQL injection and special characters"""
        # Nettoyer le symbole
        if token_data.symbol:
            token_data.symbol = token_data.symbol.replace('#', '').replace("'", "").replace('"', '').strip()
            if not token_data.symbol:
                token_data.symbol = f"UNK_{token_data.address[:6]}"
        
        # Nettoyer le nom
        if token_data.name:
            token_data.name = token_data.name.replace('#', '').replace("'", "").replace('"', '').strip()
            if not token_data.name:
                token_data.name = f"Unknown Token {token_data.address[:8]}"
        
        # Limiter la longueur des chaînes
        if token_data.symbol and len(token_data.symbol) > 20:
            token_data.symbol = token_data.symbol[:20]
        
        if token_data.name and len(token_data.name) > 100:
            token_data.name = token_data.name[:100]
        
        return token_data

    def identify_address_type(self, address: str) -> str:
        """Identify if address is a token or pair"""
        try:
            # Test pairs endpoint first
            url_pair = f"https://api.dexscreener.com/latest/dex/pairs/solana/{address}"
            start_time = time.time()
            response = self.session.get(url_pair, timeout=self.config.rpc.timeout)
            api_duration = time.time() - start_time
            self._record_api_call('dexscreener_pairs_check', api_duration)
            
            if response.status_code == 200:
                data = response.json()
                if 'pair' in data and data['pair']:
                    return 'pair'
            
            # Test tokens endpoint
            url_token = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
            start_time = time.time()
            response = self.session.get(url_token, timeout=self.config.rpc.timeout)
            api_duration = time.time() - start_time
            self._record_api_call('dexscreener_tokens_check', api_duration)
            
            if response.status_code == 200:
                data = response.json()
                if 'pairs' in data and data['pairs']:
                    return 'token'
            
            return 'unknown'
            
        except Exception as e:
            self.logger.warning(f"Error identifying address type for {address}: {e}")
            return 'unknown'
    
    def extract_token_from_pair(self, pair_address: str) -> Optional[str]:
        """Extract token address from pair address"""
        try:
            url = f"https://api.dexscreener.com/latest/dex/pairs/solana/{pair_address}"
            start_time = time.time()
            response = self.session.get(url, timeout=self.config.rpc.timeout)
            api_duration = time.time() - start_time
            self._record_api_call('dexscreener_extract_token', api_duration)
            
            if response.status_code == 200:
                data = response.json()
                
                if 'pair' in data and data['pair']:
                    pair = data['pair']
                    base_token = pair.get('baseToken', {}).get('address')
                    quote_token = pair.get('quoteToken', {}).get('address')
                    
                    # Prefer base token if quote is known stable/SOL
                    if quote_token in self.config.monitoring.get('known_quote_tokens', {}):
                        return base_token
                    else:
                        return base_token
                        
        except Exception as e:
            self.logger.warning(f"Error extracting token from pair {pair_address}: {e}")
            
        return None
        
    def get_token_creation_from_dexscreener(self, token_address: str) -> Optional[int]:
        """
        Get token creation timestamp from DexScreener
        
        Args:
            token_address: Token address
            
        Returns:
            Unix timestamp of creation or None if not found
        """
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            start_time = time.time()
            response = self.session.get(url, timeout=self.config.rpc.timeout)
            api_duration = time.time() - start_time
            self._record_api_call('dexscreener_creation_timestamp', api_duration)

            if response.status_code == 200:
                data = response.json()
                
                if 'pairs' in data and data['pairs']:
                    # Take the oldest pair (first creation)
                    oldest_pair = min(data['pairs'], key=lambda p: p.get('pairCreatedAt', float('inf')))
                    
                    if 'pairCreatedAt' in oldest_pair:
                        # pairCreatedAt is usually in milliseconds
                        creation_time = oldest_pair['pairCreatedAt']
                        if creation_time > 1e12:  # If in milliseconds
                            creation_time = creation_time // 1000
                        return int(creation_time)
                
                self.logger.debug(f"No creation data found for {token_address[:8]}...")
                return None
                
        except Exception as e:
            self.logger.warning(f"Error getting creation timestamp from DexScreener for {token_address[:8]}...: {e}")
            return None
    
    def get_token_creation_from_solanatracker(self, token_address: str) -> Optional[int]:
        """
        Get token creation timestamp from Solana Tracker
        
        Args:
            token_address: Token address
            
        Returns:
            Unix timestamp of creation or None if not found
        """
        try:
            url = f"https://api.solanatracker.io/tokens/{token_address}"
            start_time = time.time()
            response = self.session.get(url, timeout=self.config.rpc.timeout)
            api_duration = time.time() - start_time
            self._record_api_call('solanatracker_creation_timestamp', api_duration)

            if response.status_code == 200:
                data = response.json()
                
                if 'token' in data and 'creation' in data['token']:
                    creation_info = data['token']['creation']
                    if 'created_time' in creation_info:
                        return int(creation_info['created_time'])
                
                self.logger.debug(f"No creation data found on SolanaTracker for {token_address[:8]}...")
                return None
                
        except Exception as e:
            self.logger.warning(f"Error getting creation timestamp from SolanaTracker for {token_address[:8]}...: {e}")
            return None
    
    def get_token_creation_timestamp(self, token_address: str) -> Optional[int]:
        """
        Get token creation timestamp trying multiple sources
        
        Args:
            token_address: Token address
            
        Returns:
            Unix timestamp of creation or None if not found
        """
        self.logger.debug(f"🔍 Searching creation timestamp for {token_address[:8]}...")
        
        # Try DexScreener first (more reliable)
        timestamp = self.get_token_creation_from_dexscreener(token_address)
        if timestamp:
            self.logger.debug(f"✅ Found creation timestamp on DexScreener: {datetime.fromtimestamp(timestamp)}")
            return timestamp
        
        # Pause to avoid rate limiting
        time.sleep(0.5)
        
        # Try Solana Tracker
        timestamp = self.get_token_creation_from_solanatracker(token_address)
        if timestamp:
            self.logger.debug(f"✅ Found creation timestamp on SolanaTracker: {datetime.fromtimestamp(timestamp)}")
            return timestamp
        
        self.logger.debug(f"❌ Creation timestamp not found for {token_address[:8]}...")
        return None
    
    
    
    def print_api_database_stats(self):
        """Print API statistics from database"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Stats du cycle actuel
                if self.current_sync_cycle_id:
                    cursor.execute("""
                        SELECT api_name, COUNT(*) as calls, 
                            AVG(duration_ms) as avg_duration,
                            SUM(CASE WHEN success THEN 1 ELSE 0 END) as success_count,
                            SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as error_count
                        FROM api_metrics 
                        WHERE sync_cycle_id = ?
                        GROUP BY api_name
                        ORDER BY calls DESC
                    """, (self.current_sync_cycle_id,))
                    
                    current_cycle_stats = cursor.fetchall()
                    
                    if current_cycle_stats:
                        self.logger.debug("=== 📊 API DATABASE STATS (Current Cycle) ===")
                        for row in current_cycle_stats:
                            self.logger.debug(f"🔗 {row['api_name'].upper()}: {row['calls']} calls, "
                                        f"avg {row['avg_duration']:.0f}ms, "
                                        f"✅{row['success_count']} ❌{row['error_count']}")
                
                # Stats des dernières 24h
                yesterday = int(time.time()) - 86400
                cursor.execute("""
                    SELECT api_name, COUNT(*) as total_calls,
                        AVG(duration_ms) as avg_duration,
                        MIN(duration_ms) as min_duration,
                        MAX(duration_ms) as max_duration,
                        SUM(CASE WHEN success THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as success_rate
                    FROM api_metrics 
                    WHERE call_timestamp > ?
                    GROUP BY api_name
                    HAVING total_calls > 10
                    ORDER BY total_calls DESC
                """, (yesterday,))
                
                stats_24h = cursor.fetchall()
                
                if stats_24h:
                    self.logger.debug("=== 📈 API PERFORMANCE (Last 24h) ===")
                    for row in stats_24h:
                        self.logger.debug(f"📊 {row['api_name']}: {row['total_calls']} calls, "
                                    f"avg {row['avg_duration']:.0f}ms "
                                    f"({row['min_duration']}-{row['max_duration']}ms), "
                                    f"success {row['success_rate']:.1f}%")
        
        except Exception as e:
            self.logger.debug(f"Error getting API database stats: {e}")

    def get_api_performance_report(self, days: int = 7) -> Dict:
        """Get detailed API performance report from database"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                since_timestamp = int(time.time()) - (days * 86400)
                
                cursor.execute("""
                    SELECT 
                        api_name,
                        COUNT(*) as total_calls,
                        AVG(duration_ms) as avg_duration_ms,
                        MIN(duration_ms) as min_duration_ms,
                        MAX(duration_ms) as max_duration_ms,
                        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_ms) as median_duration_ms,
                        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms) as p95_duration_ms,
                        SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful_calls,
                        SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as failed_calls,
                        COUNT(DISTINCT DATE(call_timestamp, 'unixepoch')) as days_active
                    FROM api_metrics 
                    WHERE call_timestamp > ?
                    GROUP BY api_name
                    ORDER BY total_calls DESC
                """, (since_timestamp,))
                
                return {
                    'period_days': days,
                    'apis': [dict(row) for row in cursor.fetchall()]
                }
                
        except Exception as e:
            self.logger.error(f"Error generating API performance report: {e}")
            return {}

    def start_sync_cycle(self) -> int:
        """Start a new sync cycle and return cycle ID - DEBUG FIXED VERSION"""
        cycle_id = int(time.time() * 1000)  # Timestamp en millisecondes comme ID
        
        # DEBUG: Log the exact values
        #print(f"🔍 DEBUG CYCLE: Generated cycle_id = {cycle_id} (type: {type(cycle_id)})")
        
        self.current_sync_cycle_id = cycle_id
        self.api_tracker.set_current_cycle(cycle_id)

        self.cycle_logger.start_cycle(cycle_id)
        
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # DEBUG: Log the exact query and parameters
                start_time = int(time.time())
                #print(f"🔍 DEBUG CYCLE: Inserting with sync_cycle_id={cycle_id}, cycle_start_time={start_time}")
                
                cursor.execute("""
                    INSERT INTO api_cycle_stats (sync_cycle_id, cycle_start_time)
                    VALUES (?, ?)
                """, (cycle_id, start_time))
                
                # DEBUG: Verify the insertion immediately
                cursor.execute("SELECT last_insert_rowid()")
                row_id = cursor.fetchone()[0]
                #print(f"🔍 DEBUG CYCLE: Inserted row ID: {row_id}")
                
                # DEBUG: Verify what was actually inserted
                cursor.execute("SELECT sync_cycle_id, cycle_start_time FROM api_cycle_stats WHERE id = ?", (row_id,))
                inserted_record = cursor.fetchone()
                #print(f"🔍 DEBUG CYCLE: Inserted record: sync_cycle_id={inserted_record[0]}, cycle_start_time={inserted_record[1]}")
                
                conn.commit()
                
                self.logger.debug(f"🚀 Started sync cycle {cycle_id}")
                
                # Vérifier que l'insertion a fonctionné avec le bon ID
                cursor.execute("SELECT sync_cycle_id FROM api_cycle_stats WHERE sync_cycle_id = ?", (cycle_id,))
                verification = cursor.fetchone()
                if verification:
                    self.logger.debug(f"✅ Cycle {cycle_id} successfully created in database")
                    #print(f"🔍 DEBUG CYCLE: Verification successful - found cycle {verification[0]}")
                else:
                    self.logger.error(f"❌ Failed to create cycle {cycle_id} in database")
                    #print(f"🔍 DEBUG CYCLE: Verification FAILED - cycle {cycle_id} not found")
                    
                    # DEBUG: Show what's actually in the table
                    cursor.execute("SELECT id, sync_cycle_id, cycle_start_time FROM api_cycle_stats ORDER BY id DESC LIMIT 3")
                    recent_cycles = cursor.fetchall()
                    #print(f"🔍 DEBUG CYCLE: Recent cycles in DB: {[dict(zip(['id', 'sync_cycle_id', 'cycle_start_time'], row)) for row in recent_cycles]}")
                    
        except Exception as e:
            self.logger.error(f"❌ Failed to record cycle start: {e}")
            #print(f"🔍 DEBUG CYCLE: Exception during insertion: {e}")
            import traceback
            #print(f"🔍 DEBUG CYCLE: Full traceback: {traceback.format_exc()}")
        
        return cycle_id

    def end_sync_cycle(self, tokens_processed: int):
        """End current sync cycle and update stats - DEBUG FIXED VERSION"""
        if not self.current_sync_cycle_id:
            self.logger.warning("No current sync cycle ID to end")
            return
        
        self.logger.debug(f"🔍 DEBUG: Starting end_sync_cycle for cycle {self.current_sync_cycle_id}")
        self.logger.debug(f"🔍 DEBUG: Tokens processed parameter: {tokens_processed}")
        
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 1. Vérifier d'abord l'état actuel de la table api_cycle_stats
                cursor.execute("""
                    SELECT id, sync_cycle_id, cycle_start_time 
                    FROM api_cycle_stats 
                    ORDER BY id DESC LIMIT 3
                """)
                recent_cycles = cursor.fetchall()
                self.logger.debug(f"🔍 DEBUG: Recent cycles: {[dict(zip(['id', 'sync_cycle_id', 'cycle_start_time'], row)) for row in recent_cycles]}")
                
                # 2. Chercher notre cycle - d'abord par sync_cycle_id exact
                cursor.execute("""
                    SELECT id, sync_cycle_id FROM api_cycle_stats WHERE sync_cycle_id = ?
                """, (self.current_sync_cycle_id,))
                exact_match = cursor.fetchone()
                
                if exact_match:
                    self.logger.debug(f"🔍 DEBUG: Found exact match for cycle {self.current_sync_cycle_id}: id={exact_match[0]}")
                    target_cycle_db_id = exact_match[0]
                    update_condition = "id = ?"
                    update_param = target_cycle_db_id
                else:
                    # 3. Si pas de match exact, chercher le plus récent avec sync_cycle_id NULL
                    self.logger.warning(f"🔍 DEBUG: No exact match found for cycle {self.current_sync_cycle_id}")
                    cursor.execute("""
                        SELECT id, sync_cycle_id, cycle_start_time 
                        FROM api_cycle_stats 
                        WHERE sync_cycle_id IS NULL OR sync_cycle_id = ''
                        ORDER BY id DESC LIMIT 1
                    """)
                    null_cycle = cursor.fetchone()
                    
                    if null_cycle:
                        self.logger.debug(f"🔍 DEBUG: Found NULL cycle to update: id={null_cycle[0]}, start_time={null_cycle[2]}")
                        target_cycle_db_id = null_cycle[0]
                        update_condition = "id = ?"
                        update_param = target_cycle_db_id
                        
                        # Mettre à jour le sync_cycle_id d'abord
                        cursor.execute("""
                            UPDATE api_cycle_stats SET sync_cycle_id = ? WHERE id = ?
                        """, (self.current_sync_cycle_id, target_cycle_db_id))
                        self.logger.debug(f"🔍 DEBUG: Updated sync_cycle_id for record {target_cycle_db_id}")
                    else:
                        self.logger.error(f"🔍 DEBUG: No suitable cycle record found to update!")
                        return
                
                # 4. Maintenant, obtenir les statistiques API
                cursor.execute("""
                    SELECT COUNT(*) as count FROM api_metrics WHERE sync_cycle_id = ?
                """, (self.current_sync_cycle_id,))
                count_result = cursor.fetchone()
                record_count = count_result['count'] if count_result else 0
                self.logger.debug(f"🔍 DEBUG: Found {record_count} api_metrics records for cycle {self.current_sync_cycle_id}")
                
                if record_count == 0:
                    self.logger.warning(f"🔍 DEBUG: No API metrics found for cycle {self.current_sync_cycle_id}")
                    # Essayer avec une recherche temporelle approximative
                    cycle_timestamp = self.current_sync_cycle_id // 1000  # Convertir en secondes
                    cursor.execute("""
                        SELECT COUNT(*) FROM api_metrics 
                        WHERE call_timestamp BETWEEN ? AND ?
                    """, (cycle_timestamp - 300, cycle_timestamp + 3600))  # ±5min avant, +1h après
                    approx_count = cursor.fetchone()[0]
                    self.logger.debug(f"🔍 DEBUG: Found {approx_count} API metrics in time range")
                
                # 5. Calculer les statistiques
                cursor.execute("""
                    SELECT 
                        COALESCE(COUNT(*), 0) as total_calls,
                        COALESCE(SUM(duration_ms), 0) as total_duration,
                        COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END), 0) as successful_calls,
                        COALESCE(SUM(CASE WHEN NOT success THEN 1 ELSE 0 END), 0) as failed_calls,
                        COALESCE(COUNT(DISTINCT api_name), 0) as unique_apis
                    FROM api_metrics 
                    WHERE sync_cycle_id = ?
                """, (self.current_sync_cycle_id,))
                
                stats = cursor.fetchone()
                self.logger.debug(f"🔍 DEBUG: Calculated stats: {dict(stats) if stats else 'None'}")
                
                if stats:
                    total_calls = stats['total_calls'] or 0
                    total_duration = stats['total_duration'] or 0
                    successful_calls = stats['successful_calls'] or 0
                    failed_calls = stats['failed_calls'] or 0
                    unique_apis = stats['unique_apis'] or 0
                    
                    self.logger.debug(f"🔍 DEBUG: Final values - calls:{total_calls}, duration:{total_duration}, success:{successful_calls}")
                    
                    # 6. Mettre à jour les statistiques du cycle
                    cursor.execute(f"""
                        UPDATE api_cycle_stats SET
                            cycle_end_time = ?,
                            total_api_calls = ?,
                            total_duration_ms = ?,
                            successful_calls = ?,
                            failed_calls = ?,
                            unique_apis_used = ?,
                            tokens_processed = ?
                        WHERE {update_condition}
                    """, (
                        int(time.time()),
                        total_calls,
                        total_duration,
                        successful_calls,
                        failed_calls,
                        unique_apis,
                        tokens_processed,
                        update_param
                    ))
                    
                    update_count = cursor.rowcount
                    self.logger.debug(f"🔍 DEBUG: UPDATE affected {update_count} rows")
                    
                    conn.commit()
                    
                    # 7. Vérifier le résultat
                    cursor.execute("""
                        SELECT * FROM api_cycle_stats WHERE id = ?
                    """, (target_cycle_db_id,))
                    final_record = cursor.fetchone()
                    self.logger.debug(f"🔍 DEBUG: Final record: {dict(final_record) if final_record else 'NOT FOUND'}")
                    
                    if update_count > 0:
                        self.logger.debug(f"✅ Successfully updated cycle stats for {self.current_sync_cycle_id}")
                    else:
                        self.logger.error(f"❌ Failed to update cycle stats")
                else:
                    self.logger.warning(f"⚠️ No stats calculated")
                    
        except Exception as e:
            self.logger.error(f"❌ Failed to end cycle stats: {e}")
            import traceback
            self.logger.error(f"❌ Full traceback: {traceback.format_exc()}")
        
        self.cycle_logger.end_cycle()
        # Reset current cycle
        self.current_sync_cycle_id = None

    def get_pending_tokens_from_queue(self, batch_size: int) -> List[str]:
        """
        Gets a batch of pending tokens from the queue and marks them as processing.
        This is an atomic operation to prevent race conditions with multiple workers.
        """
        tokens_to_process = []
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                # Use a transaction to ensure atomicity
                with conn:
                    # Step 1: Select pending tokens
                    cursor.execute("""
                        SELECT token_address FROM token_processing_queue
                        WHERE status = 'pending'
                        ORDER BY created_at
                        LIMIT ?
                    """, (batch_size,))
                    
                    tokens_to_process = [row[0] for row in cursor.fetchall()]

                    if not tokens_to_process:
                        return []

                    # Step 2: Mark them as 'processing'
                    placeholders = ','.join('?' for _ in tokens_to_process)
                    update_query = f"""
                        UPDATE token_processing_queue
                        SET status = 'processing', processing_started_at = CURRENT_TIMESTAMP
                        WHERE token_address IN ({placeholders})
                    """
                    cursor.execute(update_query, tokens_to_process)
            
            self.logger.info(f"Locked {len(tokens_to_process)} tokens from queue for processing.")
            return tokens_to_process

        except Exception as e:
            self.logger.error(f"Error getting tokens from queue: {e}")
            return []

    @db_retry(max_retries=3, delay=0.3)
    def get_new_tokens_from_transactions(self) -> Set[str]:
        """Get new token addresses from transactions table (excluding flagged tokens)"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Get all token_mint addresses from transactions that aren't in tokens table
                # AND exclude tokens that are flagged as no_data unless retry period has passed
                query = """
                SELECT DISTINCT t.token_mint
                FROM transactions t
                LEFT JOIN tokens tk ON t.token_mint = tk.address
                WHERE t.token_mint IS NOT NULL 
                AND t.token_mint != ''
                AND tk.address IS NULL
                AND t.token_mint NOT IN (
                    SELECT address FROM tokens 
                    WHERE no_data_available = 1 
                    AND (no_data_last_check > datetime('now', '-' || ? || ' days') OR failed_attempts >= ?)
                )
                ORDER BY t.created_at DESC
                """
                
                cursor.execute(query, (self.config.monitoring.retry_failed_after_days, self.config.monitoring.max_failed_attempts))
                results = cursor.fetchall()
                
                token_addresses = {row[0] for row in results}
                self.logger.debug(f"Found {len(token_addresses)} new tokens to process (excluding flagged tokens)")
                
                return token_addresses
                
        except Exception as e:
            self.logger.error(f"Error getting new tokens: {e}")
            return set()
    
    @db_retry(max_retries=3, delay=0.3)
    def get_tokens_needing_price_update(self) -> List[str]:
        """Get tokens that need price updates (excluding flagged tokens)"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Get tokens that haven't been updated recently and aren't flagged
                cutoff_time = int(time.time()) - self.config.monitoring.price_update_interval_seconds
                self.logger.debug(f"DEBUG: Using cutoff time {datetime.fromtimestamp(cutoff_time)} for general price updates.")

                query = """
                SELECT address 
                FROM tokens 
                WHERE (last_price_update < ? OR last_price_update IS NULL)
                AND (no_data_available = 0 OR no_data_available IS NULL)
                AND (failed_attempts < ? OR failed_attempts IS NULL)
                AND is_dead = 0
                AND (is_rugged = 0 OR is_rugged IS NULL)
                ORDER BY last_price_update ASC NULLS FIRST
                LIMIT ?
                """
                
                cursor.execute(query, (cutoff_time, self.config.monitoring.max_failed_attempts, self.config.batching.batch_sizes['dexscreener']))
                results = cursor.fetchall()
                
                self.logger.debug(f"Found {len(results)} general tokens needing price updates.")
                return [row[0] for row in results]
                
        except Exception as e:
            self.logger.error(f"Error getting tokens for price update: {e}")
            return []
    
    def get_tokens_needing_historization(self) -> List[str]:
        """Get tokens that need historization"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                cutoff_time = int(time.time()) - self.config.monitoring.historization_interval_seconds
                
                query = """
                SELECT address 
                FROM tokens 
                WHERE is_dead = 0
                AND (is_rugged = 0 OR is_rugged IS NULL)
                AND (last_historized_at < ? OR last_historized_at IS NULL)
                AND (price_usd > 0 OR market_cap > 0)
                ORDER BY last_historized_at ASC NULLS FIRST
                LIMIT ?
                """
                
                cursor.execute(query, (cutoff_time, self.config.batching.batch_sizes['dexscreener']))
                results = cursor.fetchall()
                
                return [row[0] for row in results]
                
        except Exception as e:
            self.logger.error(f"Error getting tokens for historization: {e}")
            return []
    
    @db_retry(max_retries=3, delay=0.3)
    def mark_token_no_data(self, token_address: str, increment_attempts: bool = True) -> bool:
        """Mark a token as having no data available"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                if increment_attempts:
                    # Incrémenter le compteur de tentatives échouées
                    cursor.execute("""
                        UPDATE tokens 
                        SET failed_attempts = COALESCE(failed_attempts, 0) + 1,
                            no_data_last_check = CURRENT_TIMESTAMP,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE address = ?
                    """, (token_address,))
                    
                    # Vérifier si on doit marquer comme no_data_available
                    cursor.execute("SELECT failed_attempts FROM tokens WHERE address = ?", (token_address,))
                    result = cursor.fetchone()
                    
                    if result and result[0] >= self.config.monitoring.max_failed_attempts:
                        cursor.execute("""
                            UPDATE tokens 
                            SET no_data_available = 1
                            WHERE address = ?
                        """, (token_address,))
                        self.logger.warning(f"🚫 Token {token_address[:8]}... marked as no_data_available after {result[0]} failed attempts")
                else:
                    # Marquer directement comme no_data
                    cursor.execute("""
                        UPDATE tokens 
                        SET no_data_available = 1,
                            no_data_last_check = CURRENT_TIMESTAMP,
                            failed_attempts = COALESCE(failed_attempts, 0) + 1,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE address = ?
                    """, (token_address,))
                    self.logger.warning(f"🚫 Token {token_address[:8]}... marked as no_data_available")
                
                conn.commit()
                return cursor.rowcount > 0
                
        except Exception as e:
            self.logger.error(f"Error marking token as no data {token_address}: {e}")
            return False

    def create_token_stub(self, token_address: str) -> bool:
        """Create a minimal token entry when no data is found"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Vérifier si le token existe déjà
                cursor.execute("SELECT address FROM tokens WHERE address = ?", (token_address,))
                if cursor.fetchone():
                    # Token existe déjà, juste marquer comme no_data
                    return self.mark_token_no_data(token_address)
                
                # Créer un stub avec données minimales
                current_timestamp = int(time.time())
                
                query = """
                INSERT INTO tokens (
                    address, symbol, name, decimals, price_usd, 
                    no_data_last_check, failed_attempts, no_data_available,
                    last_price_update, metadata_source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """
                
                cursor.execute(query, (
                    token_address,
                    f"UNK_{token_address[:6]}",  # Symbol générique
                    f"Unknown Token {token_address[:8]}",  # Nom générique
                    9,  # Decimals par défaut
                    0.0,  # Prix inconnu
                    None,  # no_data_last_check (pas encore de check)
                    1,  # failed_attempts (première tentative échouée)
                    0,  # no_data_available (pas encore marqué comme no_data)
                    current_timestamp,
                    "stub",  # Source
                ))
                
                conn.commit()
                self.logger.debug(f"📝 Created stub entry for {token_address[:8]}...")
                return True
                
        except Exception as e:
            self.logger.error(f"Error creating token stub {token_address}: {e}")
            return False

    def debug_historization_status(self):
        """Méthode pour debugger l'état de l'historisation"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Dernières historisations
                cursor.execute("""
                    SELECT token_address, snapshot_timestamp, price_usd, market_cap
                    FROM tokens_history 
                    ORDER BY snapshot_timestamp DESC 
                    LIMIT 10
                """)
                
                recent_hist = cursor.fetchall()
                
                self.logger.info("=== 📊 DERNIÈRES HISTORISATIONS ===")
                for row in recent_hist:
                    hist_time = datetime.fromtimestamp(row['snapshot_timestamp'])
                    self.logger.info(f"Token: {row['token_address'][:8]}..., Time: {hist_time}, Prix: ${row['price_usd']}, MC: ${row['market_cap']}")
                
                # Tokens candidats à l'historisation
                cursor.execute("""
                    SELECT address, symbol, price_usd, market_cap, last_historized_at,
                        (strftime('%s', 'now') - COALESCE(last_historized_at, 0)) as seconds_since_hist
                    FROM tokens 
                    WHERE (price_usd > 0 OR market_cap > 0)
                    AND is_dead = 0
                    ORDER BY seconds_since_hist DESC
                    LIMIT 10
                """)
                
                candidates = cursor.fetchall()
                
                self.logger.info("=== 🎯 CANDIDATS HISTORISATION ===")
                for row in candidates:
                    self.logger.info(f"Token: {row['address'][:8]}... ({row['symbol']}), Prix: ${row['price_usd']}, Dernière hist: {row['seconds_since_hist']}s ago")
                
                # Stats générales
                cursor.execute("SELECT COUNT(*) as total FROM tokens_history WHERE snapshot_timestamp > ?", (int(time.time()) - 3600,))
                hist_last_hour = cursor.fetchone()['total']
                
                cursor.execute("SELECT COUNT(*) as total FROM tokens WHERE last_historized_at > ?", (int(time.time()) - 3600,))
                tokens_hist_last_hour = cursor.fetchone()['total']
                
                self.logger.info(f"=== 📈 STATS HISTORISATION ===")
                self.logger.info(f"Historisations dernière heure: {hist_last_hour}")
                self.logger.info(f"Tokens historisés dernière heure: {tokens_hist_last_hour}")
                
        except Exception as e:
            self.logger.error(f"Erreur debug historization: {e}")

    def upsert_token(self, token_data: TokenData) -> bool:
        """Insert or update token in database with historization - enhanced version with retry logic"""
        max_retries = 3
        base_delay = 0.2
        
        for attempt in range(max_retries):
            try:
                # Clean data before insertion
                original_symbol = token_data.symbol
                original_name = token_data.name
                token_data = self.clean_token_data(token_data)
                rugcheck_data = {}
                current_timestamp = int(time.time())

                if original_symbol != token_data.symbol:
                    self.logger.debug(f"Symbol cleaned for {token_data.address[:8]}... - '{original_symbol}' -> '{token_data.symbol}'")
                if original_name != token_data.name:
                    self.logger.debug(f"Name cleaned for {token_data.address[:8]}... - '{original_name}' -> '{token_data.name}'")
                
                # 1. Check if token exists avec retry
                token_exists = False
                conn = self.get_db_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT address FROM tokens WHERE address = ?", (token_data.address,))
                    token_exists = cursor.fetchone() is not None
                finally:
                    conn.close()
                
                # 2. Si token existe, historiser AVANT la mise à jour
                if token_exists:
                    conn = self.get_db_connection()
                    try:
                        cursor = conn.cursor()
                        cursor.execute("SELECT price_usd, market_cap FROM tokens WHERE address = ?", (token_data.address,))
                        existing_row = cursor.fetchone()
                        
                        # Historiser seulement si le token a déjà des données réelles
                        if existing_row and (existing_row['price_usd'] > 0 or existing_row['market_cap'] > 0):
                            # Appeler historize_token_data qui a maintenant sa propre logique de retry
                            historization_success = self.historize_token_data(token_data.address, token_data)
                            if historization_success:
                                # ✅ AJOUT: Logger l'historisation automatique
                                self.cycle_logger.record_operation('historized_tokens', 1)
                        else:
                            self.logger.debug(f"Skipping historization for {token_data.address[:8]}... - no significant data yet")
                    finally:
                        conn.close()
                
                # 3. Faire l'update/insert avec nouvelle connexion
                conn = self.get_db_connection()
                try:
                    cursor = conn.cursor()
                    
                    # Vérifier les données rugcheck récentes
                    if token_exists:
                        cursor.execute("""
                            SELECT last_rugcheck_update, rug_risk_score 
                            FROM tokens 
                            WHERE address = ? AND last_rugcheck_update > ?
                        """, (token_data.address, current_timestamp - 86400))
                        recent_rugcheck = cursor.fetchone()
                    else:
                        recent_rugcheck = None

                    if not recent_rugcheck:
                        # Récupérer nouvelles données rugcheck (sans connexion DB)
                        rugcheck_response = self.get_rugcheck_data(token_data.address)
                        if rugcheck_response:
                            rugcheck_data = self.extract_rugcheck_data(rugcheck_response)
                            # Enrichir token_data avec holder_count de rugcheck si meilleur
                            if rugcheck_data.get('holder_count', 0) > token_data.holder_count:
                                old_count = token_data.holder_count
                                token_data.holder_count = rugcheck_data['holder_count']
                                self.logger.debug(f"📊 Updated holder_count for {token_data.address[:8]}... from {old_count} to {token_data.holder_count}")

                                # Ajouter les attributs manquants à token_data pour l'historisation
                                token_data.top_holder_percentage = rugcheck_data.get('top_holder_percentage', 0.0)
                                token_data.top_10_holders_percentage = rugcheck_data.get('top_10_holders_percentage', 0.0)
                                token_data.insider_holders_count = rugcheck_data.get('insider_holders_count', 0)
                                token_data.insider_networks_detected = rugcheck_data.get('insider_networks_detected', 0)
                                token_data.lp_providers_count = rugcheck_data.get('lp_providers_count', 0)
                                token_data.has_low_liquidity = rugcheck_data.get('has_low_liquidity', False)
                                token_data.rug_risk_score = rugcheck_data.get('rug_risk_score', 50)
                                token_data.rug_raw_score = rugcheck_data.get('rug_raw_score', 0)
                                token_data.is_rugged = rugcheck_data.get('is_rugged', False)
                                token_data.risk_count = rugcheck_data.get('risk_count', 0)
                                token_data.mint_authority_revoked = rugcheck_data.get('mint_authority_revoked', False)
                                token_data.freeze_authority_revoked = rugcheck_data.get('freeze_authority_revoked', False)
                                token_data.launchpad_name = rugcheck_data.get('launchpad_name')
                                token_data.is_pump_fun = rugcheck_data.get('is_pump_fun', False)
                                
                                self.logger.debug(f"🔒 Enriched token_data with rugcheck: TH={token_data.top_holder_percentage:.2f}%, T10H={token_data.top_10_holders_percentage:.2f}%")
                                
                                self.logger.debug(f"🔒 Got rugcheck data for {token_data.address[:8]}... (score: {rugcheck_data.get('rug_risk_score', 50)})")

                    # Calculate advanced metrics
                    liquidity_mc_ratio = 0.0
                    volume_mc_ratio = 0.0
                    if token_data.market_cap > 0:
                        liquidity_mc_ratio = token_data.liquidity_usd / token_data.market_cap
                        volume_mc_ratio = token_data.volume_24h / token_data.market_cap
                    
                    # Calculate scores
                    viability_score = self.analyzer.calculate_viability_score(token_data, [])
                    risk_score = self.analyzer.calculate_risk_score(token_data, [])
                    momentum_score = self.analyzer.calculate_momentum_score(token_data, [])
                    predictive_scam_score = self.analyzer.calculate_predictive_scam_score(rugcheck_data)
                    
                    # Utiliser une transaction pour l'upsert
                    with conn:  # Context manager pour auto-commit/rollback
                        if token_exists:
                            # Update existing token
                            query = """
                            UPDATE tokens SET
                                symbol = COALESCE(?, symbol),
                                name = COALESCE(?, name),
                                decimals = COALESCE(?, decimals),
                                price_usd = ?,
                                logo_uri = COALESCE(?, logo_uri),
                                coingecko_id = COALESCE(?, coingecko_id),
                                is_verified = COALESCE(?, is_verified),
                                timestamp_token_created = CASE 
                                    WHEN ? > 0 AND (timestamp_token_created IS NULL OR timestamp_token_created = 0) 
                                    THEN ? 
                                    ELSE timestamp_token_created 
                                END,
                                creator_address = COALESCE(?, creator_address),
                                bonding_curve_progress = MAX(COALESCE(bonding_curve_progress, 0), COALESCE(?, 0)),
                                holder_count = MAX(COALESCE(holder_count, 0), COALESCE(?, 0)),
                                market_cap = ?,
                                fdv = ?,
                                liquidity_usd = ?,
                                liquidity_sol = ?,
                                liquidity_mc_ratio = ?,
                                volume_mc_ratio = ?,
                                price_volatility_24h = ?,
                                volume_5m = ?,
                                volume_1h = ?,
                                volume_6h = ?,
                                volume_24h = ?,
                                price_change_5m = ?,
                                price_change_1h = ?,
                                price_change_6h = ?,
                                price_change_24h = ?,
                                viability_score = ?,
                                risk_score = ?,
                                momentum_score = ?,
                                predictive_scam_score = ?,
                                rug_risk_score = COALESCE(?, rug_risk_score),
                                rug_raw_score = COALESCE(?, rug_raw_score),
                                is_rugged = COALESCE(?, is_rugged),
                                mint_authority_revoked = COALESCE(?, mint_authority_revoked),
                                freeze_authority_revoked = COALESCE(?, freeze_authority_revoked),
                                top_holder_percentage = COALESCE(?, top_holder_percentage),
                                top_10_holders_percentage = COALESCE(?, top_10_holders_percentage),
                                insider_holders_count = COALESCE(?, insider_holders_count),
                                insider_networks_detected = COALESCE(?, insider_networks_detected),
                                launchpad_name = COALESCE(?, launchpad_name),
                                is_pump_fun = COALESCE(?, is_pump_fun),
                                lp_providers_count = COALESCE(?, lp_providers_count),
                                has_low_liquidity = COALESCE(?, has_low_liquidity),
                                risk_count = COALESCE(?, risk_count),
                                last_rugcheck_update = CASE WHEN ? IS NOT NULL THEN ? ELSE last_rugcheck_update END,
                                last_price_update = ?,
                                metadata_source = COALESCE(?, metadata_source),
                                updated_at = CURRENT_TIMESTAMP,
                                failed_attempts = 0,
                                no_data_available = 0
                            WHERE address = ?
                            """
                            
                            cursor.execute(query, (
                                token_data.symbol,
                                token_data.name,
                                token_data.decimals,
                                token_data.price_usd,
                                token_data.logo_uri,
                                token_data.coingecko_id,
                                token_data.is_verified,
                                token_data.timestamp_token_created,
                                token_data.timestamp_token_created,
                                token_data.creator_address,  
                                token_data.bonding_curve_progress,  
                                token_data.holder_count,  
                                token_data.market_cap,
                                token_data.fdv,
                                token_data.liquidity_usd,
                                token_data.liquidity_sol,
                                liquidity_mc_ratio,
                                volume_mc_ratio,
                                getattr(token_data, 'price_volatility_24h', 0.0),
                                token_data.volume_5m,
                                token_data.volume_1h,
                                token_data.volume_6h,
                                token_data.volume_24h,
                                token_data.price_change_5m,
                                token_data.price_change_1h,
                                token_data.price_change_6h,
                                token_data.price_change_24h,
                                viability_score,
                                risk_score,
                                momentum_score,
                                predictive_scam_score,
                                rugcheck_data.get('rug_risk_score'),
                                rugcheck_data.get('rug_raw_score'),
                                rugcheck_data.get('is_rugged'),
                                rugcheck_data.get('mint_authority_revoked'),
                                rugcheck_data.get('freeze_authority_revoked'),
                                rugcheck_data.get('top_holder_percentage'),
                                rugcheck_data.get('top_10_holders_percentage'),
                                rugcheck_data.get('insider_holders_count'),
                                rugcheck_data.get('insider_networks_detected'),
                                rugcheck_data.get('launchpad_name'),
                                rugcheck_data.get('is_pump_fun'),
                                rugcheck_data.get('lp_providers_count'),
                                rugcheck_data.get('has_low_liquidity'),
                                rugcheck_data.get('risk_count'),
                                current_timestamp if rugcheck_data else None,
                                current_timestamp if rugcheck_data else None,
                                current_timestamp,
                                token_data.metadata_source,
                                token_data.address
                            ))
                        else:
                            # Insert new token
                            query = """
                            INSERT INTO tokens (
                                address, symbol, name, decimals, price_usd, logo_uri,
                                coingecko_id, is_verified, timestamp_token_created, creator_address,
                                bonding_curve_progress, holder_count, market_cap, fdv,
                                liquidity_usd, liquidity_sol, liquidity_mc_ratio, volume_mc_ratio,
                                price_volatility_24h,
                                volume_5m, volume_1h, volume_6h, volume_24h, 
                                price_change_5m, price_change_1h, price_change_6h, price_change_24h,
                                viability_score, risk_score, momentum_score, predictive_scam_score,
                                rug_risk_score, rug_raw_score, is_rugged,
                                mint_authority_revoked, freeze_authority_revoked,
                                top_holder_percentage, top_10_holders_percentage,
                                insider_holders_count, insider_networks_detected,
                                launchpad_name, is_pump_fun, lp_providers_count,
                                has_low_liquidity, risk_count, last_rugcheck_update,
                                last_price_update, metadata_source, last_historized_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """

                            cursor.execute(query, (
                                token_data.address,
                                token_data.symbol,
                                token_data.name,
                                token_data.decimals,
                                token_data.price_usd,
                                token_data.logo_uri,
                                token_data.coingecko_id,
                                token_data.is_verified,
                                token_data.timestamp_token_created,
                                token_data.creator_address, 
                                token_data.bonding_curve_progress,  
                                token_data.holder_count,  
                                token_data.market_cap,
                                token_data.fdv,
                                token_data.liquidity_usd,
                                token_data.liquidity_sol,
                                liquidity_mc_ratio,
                                volume_mc_ratio,
                                getattr(token_data, 'price_volatility_24h', 0.0),
                                token_data.volume_5m,
                                token_data.volume_1h,
                                token_data.volume_6h,
                                token_data.volume_24h,
                                token_data.price_change_5m,
                                token_data.price_change_1h,
                                token_data.price_change_6h,
                                token_data.price_change_24h,
                                viability_score,
                                risk_score,
                                momentum_score,
                                predictive_scam_score,
                                # Données rugcheck
                                rugcheck_data.get('rug_risk_score', 50),
                                rugcheck_data.get('rug_raw_score', 0),
                                rugcheck_data.get('is_rugged', False),
                                rugcheck_data.get('mint_authority_revoked', False),
                                rugcheck_data.get('freeze_authority_revoked', False),
                                rugcheck_data.get('top_holder_percentage', 0.0),
                                rugcheck_data.get('top_10_holders_percentage', 0.0),
                                rugcheck_data.get('insider_holders_count', 0),
                                rugcheck_data.get('insider_networks_detected', 0),
                                rugcheck_data.get('launchpad_name'),
                                rugcheck_data.get('is_pump_fun', False),
                                rugcheck_data.get('lp_providers_count', 0),
                                rugcheck_data.get('has_low_liquidity', False),
                                rugcheck_data.get('risk_count', 0),
                                current_timestamp if rugcheck_data else None,
                                current_timestamp,
                                token_data.metadata_source,
                                current_timestamp
                            ))
                finally:
                    conn.close()
                    
                # 4. Historiser le nouveau token après insertion (si nouveau)
                if not token_exists and (token_data.price_usd > 0 or token_data.market_cap > 0):
                    self.historize_token_data(token_data.address, token_data)
                    self.cycle_logger.record_operation('historized_tokens', 1)
                elif not token_exists:
                    self.logger.debug(f"Skipping initial historization for {token_data.address[:8]}... - no significant data")
                
                return True
                    
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    wait_time = base_delay * (2 ** attempt)
                    self.logger.warning(f"Database locked during upsert, retry {attempt + 1}/{max_retries} in {wait_time:.2f}s")
                    time.sleep(wait_time)
                    continue
                else:
                    self.logger.error(f"Error upserting token {token_data.address} after {max_retries} attempts: {e}")
                    return False
                    
            except Exception as e:
                self.logger.error(f"Unexpected error upserting token {token_data.address}: {e}")
                return False

        return False


    def get_dashboard_priority_tokens(self) -> List[str]:
        """Get tokens that appear in the dashboard overview (high priority for updates)"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Requête identique à get_tokens_overview du dashboard
                query = """
                WITH token_stats AS (
                    SELECT 
                        t.token_mint,
                        COUNT(*) as total_transactions,
                        COUNT(CASE WHEN t.transaction_type = 'TransactionType.BUY' THEN 1 END) as total_buys,
                        COUNT(CASE WHEN t.transaction_type = 'TransactionType.SELL' THEN 1 END) as total_sells,
                        COUNT(DISTINCT CASE WHEN t.transaction_type = 'TransactionType.BUY' THEN t.wallet_address END) as unique_buyers,
                        COUNT(DISTINCT CASE WHEN t.transaction_type = 'TransactionType.SELL' THEN t.wallet_address END) as unique_sellers,
                        SUM(CASE WHEN t.transaction_type = 'TransactionType.BUY' THEN t.amount ELSE 0 END) as buy_volume,
                        SUM(CASE WHEN t.transaction_type = 'TransactionType.SELL' THEN t.amount ELSE 0 END) as sell_volume,
                        AVG(CASE WHEN t.transaction_type = 'TransactionType.BUY' THEN t.wallet_priority_at_detection END) as avg_buyer_priority,
                        MIN(t.block_time) as first_tx_timestamp,
                        MAX(t.block_time) as last_tx_timestamp,
                        MIN(CASE WHEN t.transaction_type = 'TransactionType.BUY' THEN t.created_at END) as first_discovery,
                        COUNT(CASE 
                            WHEN t.transaction_type = 'TransactionType.BUY' 
                            AND t.block_time >= (strftime('%s', 'now') - 86400) 
                            THEN 1 
                        END) as recent_buys_24h,
                        AVG(t.detection_delay) as avg_detection_delay
                    FROM transactions t
                    WHERE t.token_mint IS NOT NULL AND t.token_mint != ''
                    GROUP BY t.token_mint
                    HAVING total_buys >= 0
                ),
                enriched_stats AS (
                    SELECT 
                        ts.*,
                        tk.symbol,
                        tk.name,
                        tk.price_usd,
                        tk.market_cap,
                        tk.last_price_update,
                        tk.metadata_source,
                        tk.timestamp_token_created,
                        CASE 
                            WHEN ts.sell_volume > 0 THEN ROUND(ts.buy_volume / ts.sell_volume, 2)
                            ELSE 999.99
                        END as volume_ratio,
                        ROUND(ts.avg_buyer_priority, 3) as avg_buyer_priority_rounded,
                        ROUND(
                            CASE 
                                WHEN ts.total_buys > 0 THEN (ts.recent_buys_24h * 100.0 / ts.total_buys)
                                ELSE 0 
                            END, 1
                        ) as recent_activity_pct,
                        ROUND((strftime('%s', 'now') - COALESCE(tk.timestamp_token_created, ts.first_tx_timestamp)) / 3600.0, 1) as token_age_hours,
                        ROUND((ts.first_discovery - COALESCE(tk.timestamp_token_created, ts.first_tx_timestamp)) / 3600.0, 1) as discovery_delay_hours,
                        ROUND((ts.last_tx_timestamp - ts.first_tx_timestamp) / 3600.0, 1) as active_lifetime_hours,
                        ROUND(ts.avg_detection_delay, 0) as avg_detection_delay_sec
                    FROM token_stats ts
                    LEFT JOIN tokens tk ON ts.token_mint = tk.address
                )
                SELECT 
                    token_mint
                FROM enriched_stats
                ORDER BY 
                    (CASE WHEN volume_ratio > 10 THEN 10 ELSE volume_ratio END * 20) +
                    (unique_buyers * 2) +
                    (recent_activity_pct) +
                    (avg_buyer_priority_rounded * 50) +
                    (CASE WHEN discovery_delay_hours <= 2 THEN 30 WHEN discovery_delay_hours <= 6 THEN 20 ELSE 0 END)
                    DESC
                LIMIT ?
                """
                
                cursor.execute(query, (self.config.batching.batch_sizes['dexscreener'] * 2,))  # Plus de tokens prioritaires
                results = cursor.fetchall()
                
                token_addresses = [row[0] for row in results if row[0]]
                self.logger.debug(f"Found {len(token_addresses)} dashboard priority tokens")
                
                return token_addresses
                
        except Exception as e:
            self.logger.error(f"Error getting dashboard priority tokens: {e}")
            return []

    def get_dashboard_tokens_needing_update(self) -> List[str]:
        """Get dashboard tokens that need data updates (prioritized)"""
        try:
            dashboard_tokens = self.get_dashboard_priority_tokens()
            
            if not dashboard_tokens:
                return []
            self.logger.debug(f"DEBUG: Found {len(dashboard_tokens)} dashboard priority tokens to check for updates.")

            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Construire la requête avec placeholders
                placeholders = ','.join(['?' for _ in dashboard_tokens])
                cutoff_time = int(time.time()) - (self.config.monitoring.price_update_interval_seconds // 2)
                self.logger.debug(f"DEBUG: Using cutoff time {datetime.fromtimestamp(cutoff_time)} for dashboard token updates.")

                query = f"""
                SELECT t.address 
                FROM tokens t
                WHERE t.address IN ({placeholders})
                AND t.is_dead = 0
                AND (t.is_rugged = 0 OR t.is_rugged IS NULL)
                AND (t.no_data_available = 0 OR t.no_data_available IS NULL)
                AND (t.failed_attempts < ? OR t.failed_attempts IS NULL)
                AND (
                    t.last_price_update < ? 
                    OR t.last_price_update IS NULL
                    OR t.price_usd IS NULL 
                    OR t.price_usd = 0
                    OR t.market_cap IS NULL 
                    OR t.market_cap = 0
                    OR t.symbol IS NULL
                    OR t.name IS NULL
                )
                ORDER BY 
                    CASE WHEN t.last_price_update IS NULL THEN 0 ELSE t.last_price_update END ASC
                """
                
                params = dashboard_tokens + [self.config.monitoring.max_failed_attempts, cutoff_time]
                cursor.execute(query, params)
                results = cursor.fetchall()
                
                priority_tokens = [row[0] for row in results]
                self.logger.debug(f"Found {len(priority_tokens)} dashboard tokens needing updates (from a pool of {len(dashboard_tokens)}).")

                
                return priority_tokens
                
        except Exception as e:
            self.logger.error(f"Error getting dashboard tokens needing update: {e}")
            return []

    def get_tokens_missing_creation_timestamp(self) -> List[str]:
        """Get tokens that need creation timestamp updates"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                query = """
                SELECT address 
                FROM tokens 
                WHERE (timestamp_token_created IS NULL OR timestamp_token_created = 0)
                AND is_dead = 0
                ORDER BY created_at DESC
                LIMIT ?
                """
                
                cursor.execute(query, (self.config.batching.batch_sizes['dexscreener'],))
                results = cursor.fetchall()
                
                return [row[0] for row in results]
                
        except Exception as e:
            self.logger.error(f"Error getting tokens missing creation timestamp: {e}")
            return []
    
    def update_token_creation_timestamp(self, token_address: str) -> bool:
        """Update only the creation timestamp for a specific token"""
        try:
            # Get creation timestamp
            creation_timestamp = self.get_token_creation_timestamp(token_address)
            
            if creation_timestamp:
                with self.get_db_connection() as conn:
                    cursor = conn.cursor()
                    
                    cursor.execute("""
                        UPDATE tokens 
                        SET timestamp_token_created = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE address = ?
                    """, (creation_timestamp, token_address))
                    
                    conn.commit()
                    
                    if cursor.rowcount > 0:
                        self.logger.debug(f"✅ Updated creation timestamp for {token_address[:8]}...")
                        return True
                    else:
                        self.logger.warning(f"⚠️ Token not found in database: {token_address[:8]}...")
                        return False
            else:
                self.logger.warning(f"❌ Could not find creation timestamp for {token_address[:8]}...")
                return False
                
        except Exception as e:
            self.logger.error(f"Error updating creation timestamp for {token_address}: {e}")
            return False
    
    def update_missing_creation_timestamps(self) -> int:
        """Update creation timestamps for tokens that are missing them"""
        self.logger.debug("Starting creation timestamp updates for existing tokens...")
        
        tokens_to_update = self.get_tokens_missing_creation_timestamp()
        
        if not tokens_to_update:
            self.logger.debug("No tokens need creation timestamp updates")
            return 0
        
        successful_updates = 0
        
        for token_address in tokens_to_update:
            try:
                if self.update_token_creation_timestamp(token_address):
                    successful_updates += 1
                
                # Rate limiting between creation timestamp requests
                time.sleep(self.config.monitoring.rate_limit_delay)
                
            except Exception as e:
                self.logger.error(f"Error updating creation timestamp for {token_address}: {e}")
                continue
        
        self.logger.debug(f"Creation timestamp update completed: {successful_updates}/{len(tokens_to_update)} successful")
        
        return successful_updates

    def get_tokens_needing_pumpfun_update(self) -> List[str]:
        """Get tokens with missing market data (likely Pump.fun tokens)"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                query = """
                SELECT address 
                FROM tokens 
                WHERE (market_cap IS NULL OR market_cap = 0 OR market_cap < 1000)
                AND (metadata_source IS NULL OR metadata_source NOT LIKE '%pumpfun%')
                AND (created_at >= datetime('now', '-7 days'))
                AND is_dead = 0
                AND (is_rugged = 0 OR is_rugged IS NULL)
                ORDER BY created_at DESC
                LIMIT ?
                """
                
                cursor.execute(query, (self.config.batching.batch_sizes['pumpfun'],))
                results = cursor.fetchall()
                
                return [row[0] for row in results]
                
        except Exception as e:
            self.logger.error(f"Error getting tokens needing Pump.fun update: {e}")
            return []

    def update_pumpfun_tokens(self) -> int:
        """Update Pump.fun tokens with missing data"""
        self.logger.debug("Starting Pump.fun data updates for tokens with missing market data...")
        
        tokens_to_update = self.get_tokens_needing_pumpfun_update()
        
        if not tokens_to_update:
            self.logger.debug("No tokens need Pump.fun updates")
            return 0
        
        successful_updates = 0
        
        for token_address in tokens_to_update:
            try:
                self.logger.debug(f"Fetching Pump.fun data for: {token_address[:8]}...")
                
                # Get data from Pump.fun
                pumpfun_data = self.get_pumpfun_data(token_address)
                
                if pumpfun_data:
                    # Update only the missing fields in database
                    if self.update_token_with_pumpfun_data(token_address, pumpfun_data):
                        successful_updates += 1
                        self.logger.debug(f"✅ Updated Pump.fun data for: {token_address[:8]}...")
                    else:
                        self.logger.warning(f"❌ Failed to save Pump.fun data for: {token_address[:8]}...")
                else:
                    self.logger.debug(f"No Pump.fun data found for: {token_address[:8]}...")
                
                # Rate limiting spécifique pour Pump.fun
                time.sleep(self.config.monitoring.pumpfun_rate_limit_seconds)
                
            except Exception as e:
                self.logger.error(f"Error updating Pump.fun data for {token_address}: {e}")
                
                # Gestion spécifique des erreurs 530
                if "530" in str(e):
                    self.logger.warning("530 Server error detected, waiting longer...")
                    time.sleep(5)
                
                continue
        
        self.logger.debug(f"Pump.fun update completed: {successful_updates}/{len(tokens_to_update)} successful")
        
        return successful_updates

    def update_token_with_pumpfun_data(self, token_address: str, pumpfun_data: TokenData) -> bool:
        """Update existing token with Pump.fun data (only missing fields)"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Update seulement les champs manquants
                query = """
                UPDATE tokens SET
                    symbol = COALESCE(symbol, ?),
                    name = COALESCE(name, ?),
                    price_usd = CASE WHEN price_usd = 0 OR price_usd IS NULL THEN ? ELSE price_usd END,
                    market_cap = CASE WHEN market_cap = 0 OR market_cap IS NULL THEN ? ELSE market_cap END,
                    volume_24h = CASE WHEN volume_24h = 0 OR volume_24h IS NULL THEN ? ELSE volume_24h END,
                    logo_uri = COALESCE(logo_uri, ?),
                    timestamp_token_created = CASE WHEN (timestamp_token_created = 0 OR timestamp_token_created IS NULL) AND ? > 0 THEN ? ELSE timestamp_token_created END,
                    creator_address = COALESCE(creator_address, ?), 
                    bonding_curve_progress = CASE WHEN bonding_curve_progress = 0 OR bonding_curve_progress IS NULL THEN ? ELSE bonding_curve_progress END, 
                    holder_count = CASE WHEN holder_count = 0 OR holder_count IS NULL THEN ? ELSE holder_count END,  
                    metadata_source = CASE 
                        WHEN metadata_source IS NULL THEN ?
                        WHEN metadata_source NOT LIKE '%pumpfun%' THEN metadata_source || '+pumpfun'
                        ELSE metadata_source
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE address = ?
                """
                
                cursor.execute(query, (
                    pumpfun_data.symbol,
                    pumpfun_data.name,
                    pumpfun_data.price_usd,
                    pumpfun_data.market_cap,
                    pumpfun_data.volume_24h,
                    pumpfun_data.logo_uri,
                    pumpfun_data.timestamp_token_created,
                    pumpfun_data.timestamp_token_created,
                    pumpfun_data.creator_address,  
                    pumpfun_data.bonding_curve_progress,  
                    pumpfun_data.holder_count,  
                    pumpfun_data.metadata_source,
                    token_address
                ))
                
                conn.commit()
                
                return cursor.rowcount > 0
                
        except Exception as e:
            self.logger.error(f"Error updating token with Pump.fun data {token_address}: {e}")
            return False

    def run_historization_cycle(self) -> int:
        """Run historization for tokens that need it"""
        self.logger.debug("Starting historization cycle...")
        
        tokens_to_historize = self.get_tokens_needing_historization()
        
        if not tokens_to_historize:
            self.logger.debug("No tokens need historization")
            return 0
        
        historized_count = 0
        
        for token_address in tokens_to_historize:
            try:
                if self.historize_token_data(token_address):
                    historized_count += 1
                
            except Exception as e:
                self.logger.error(f"Error historizing token {token_address}: {e}")
                continue
        
        self.logger.debug(f"Historization cycle completed: {historized_count}/{len(tokens_to_historize)} successful")
        self.cycle_logger.record_operation('historized_tokens', historized_count)

        return historized_count

    def run_dead_token_check(self) -> int:
        """Run dead token detection cycle"""
        self.logger.debug("Starting dead token check cycle...")
        
        marked_count = self.check_and_mark_dead_tokens()
        
        self.logger.debug(f"Dead token check completed: {marked_count} tokens marked as dead")
        
        return marked_count

    async def fetch_dexscreener_batch_data(self, session: aiohttp.ClientSession, token_addresses: List[str]) -> Dict[str, Dict]:
        """
        Fetches token data from DexScreener using the multi-token endpoint.
        AMÉLIORÉ: Meilleure correspondance et gestion des tokens manqués
        """
        if not token_addresses:
            return {}

        all_pairs_data = {}
        batch_size = 30  # Limite DexScreener
        
        for i in range(0, len(token_addresses), batch_size):
            batch = token_addresses[i:i + batch_size]
            addresses_str = ','.join(batch)
            url = f"https://api.dexscreener.com/latest/dex/tokens/{addresses_str}"
            
            self.logger.info(f"🔍 [BATCH] Requesting {len(batch)} tokens: {[addr[:8] for addr in batch]}")

            try:
                start_time = time.time()
                async with session.get(url, timeout=self.config.rpc.timeout) as response:
                    api_duration = time.time() - start_time
                    self._record_api_call('dexscreener_tokens_batch_async', api_duration)

                    if response.status == 200:
                        data = await response.json()
                        #self.log_debug_response(batch, data, f"batch_{i//30 + 1}")
                        
                        if data and data.get('pairs'):
                            self.logger.info(f"🔍 [BATCH] API returned {len(data['pairs'])} pairs")
                            
                            # ✅ AMÉLIORATION 1: Créer un index de tous les tokens possibles
                            batch_set = set(batch)
                            
                            # ✅ AMÉLIORATION 2: Analyser TOUTES les pairs retournées
                            found_tokens = set()
                            token_pairs_map = {}  # token -> list of pairs
                            
                            for pair in data['pairs']:
                                # Vérifier baseToken
                                base_token_addr = pair.get('baseToken', {}).get('address')
                                if base_token_addr and base_token_addr in batch_set:
                                    if base_token_addr not in token_pairs_map:
                                        token_pairs_map[base_token_addr] = []
                                    token_pairs_map[base_token_addr].append(pair)
                                    found_tokens.add(base_token_addr)
                                
                                # Vérifier quoteToken (cas rare mais possible)
                                quote_token_addr = pair.get('quoteToken', {}).get('address')
                                if quote_token_addr and quote_token_addr in batch_set:
                                    if quote_token_addr not in token_pairs_map:
                                        token_pairs_map[quote_token_addr] = []
                                    token_pairs_map[quote_token_addr].append(pair)
                                    found_tokens.add(quote_token_addr)
                            
                            # ✅ AMÉLIORATION 3: Sélectionner la meilleure pair pour chaque token trouvé
                            for token_addr, pairs in token_pairs_map.items():
                                # Prendre la pair avec le plus gros volume 24h
                                best_pair = max(pairs, key=lambda p: float(p.get('volume', {}).get('h24', 0) or 0))
                                all_pairs_data[token_addr] = best_pair
                                
                                volume_24h = float(best_pair.get('volume', {}).get('h24', 0) or 0)
                                self.logger.debug(f"✅ [BATCH] Found {token_addr[:8]}... with {len(pairs)} pairs, selected best (vol24h: ${volume_24h:,.0f})")

                            # ✅ AMÉLIORATION 4: Debug détaillé pour tokens manqués
                            missing_tokens = batch_set - found_tokens
                            
                            if missing_tokens:
                                missing_short = [addr[:8] for addr in missing_tokens]
                                self.logger.warning(f"❌ [BATCH] Missing from API response: {missing_short}")
                                
                                # ✅ AMÉLIORATION 5: Analyse approfondie des tokens manqués
                                self._analyze_missing_tokens(missing_tokens, data.get('pairs', []))
                            
                            self.logger.info(f"📊 [BATCH] Found: {len(found_tokens)}/{len(batch)} tokens")

                        else:
                            self.logger.debug(f"No pairs found in batch response for tokens: {[t[:8] for t in batch]}")
                    else:
                        self.logger.warning(f"DexScreener batch API returned status {response.status} for tokens: {[t[:8] for t in batch]}")

            except Exception as e:
                self.logger.error(f"Error fetching DexScreener batch data for {[t[:8] for t in batch]}: {e}")
                
            # Pause entre batches
            await asyncio.sleep(1)

        return all_pairs_data

    def _analyze_missing_tokens(self, missing_tokens: Set[str], all_pairs: List[Dict]):
        """
        Analyse pourquoi certains tokens sont manqués
        """
        self.logger.info(f"🔍 [ANALYSIS] Analyzing {len(missing_tokens)} missing tokens...")
        
        for missing_addr in list(missing_tokens)[:3]:  # Limiter à 3 pour éviter spam
            self.logger.info(f"🔍 [ANALYSIS] Analyzing missing token: {missing_addr[:8]}...")
            
            # 1. Chercher si le token apparaît quelque part dans la réponse
            found_somewhere = False
            for pair in all_pairs:
                pair_str = str(pair).lower()
                if missing_addr.lower() in pair_str:
                    found_somewhere = True
                    base_addr = pair.get('baseToken', {}).get('address', '')
                    quote_addr = pair.get('quoteToken', {}).get('address', '')
                    
                    self.logger.info(f"🔍 [ANALYSIS] {missing_addr[:8]}... found in pair data:")
                    self.logger.info(f"   Base: {base_addr[:8] if base_addr else 'N/A'}...")
                    self.logger.info(f"   Quote: {quote_addr[:8] if quote_addr else 'N/A'}...")
                    self.logger.info(f"   Exact match base: {base_addr == missing_addr}")
                    self.logger.info(f"   Exact match quote: {quote_addr == missing_addr}")
                    break
            
            if not found_somewhere:
                self.logger.info(f"🔍 [ANALYSIS] {missing_addr[:8]}... completely absent from API response")
                
                # 2. Vérifier la validité de l'adresse
                if len(missing_addr) != 44:
                    self.logger.info(f"   ⚠️ Invalid address length: {len(missing_addr)} (should be 44)")
                
                # 3. Vérifier les caractères
                invalid_chars = [c for c in missing_addr if not c.isalnum()]
                if invalid_chars:
                    self.logger.info(f"   ⚠️ Invalid characters found: {invalid_chars}")

    def get_batch_statistics(self) -> Dict:
        """
        Retourne des statistiques sur l'efficacité du batch processing
        """
        try:
            # Cette méthode peut être appelée pour monitorer les performances
            stats = {
                'total_batch_requests': getattr(self, '_batch_requests', 0),
                'total_tokens_requested': getattr(self, '_tokens_requested', 0),
                'total_tokens_found': getattr(self, '_tokens_found', 0),
                'success_rate': 0.0
            }
            
            if stats['total_tokens_requested'] > 0:
                stats['success_rate'] = (stats['total_tokens_found'] / stats['total_tokens_requested']) * 100
            
            return stats
        except Exception as e:
            self.logger.error(f"Error calculating batch statistics: {e}")
            return {}

    # ✅ AMÉLIORATION 6: Méthode pour diagnostiquer les problèmes de batch
    def diagnose_batch_issues(self, token_addresses: List[str]) -> Dict[str, str]:
        """
        Diagnostique les problèmes potentiels avec une liste de tokens
        """
        issues = {}
        
        for addr in token_addresses:
            problems = []
            
            # Vérifier la longueur
            if len(addr) != 44:
                problems.append(f"invalid_length_{len(addr)}")
            
            # Vérifier les caractères
            if not addr.replace('1', '').replace('2', '').replace('3', '').replace('4', '').replace('5', '').replace('6', '').replace('7', '').replace('8', '').replace('9', '').replace('0', '').isalpha():
                invalid_chars = [c for c in addr if not c.isalnum()]
                if invalid_chars:
                    problems.append(f"invalid_chars_{invalid_chars}")
            
            # Vérifier si c'est une adresse connue problématique
            if addr.startswith('So1111'):  # SOL wrapper
                problems.append("quote_token")
            
            if problems:
                issues[addr] = ",".join(problems)
        
        return issues

    def _parse_dexscreener_batch_response(self, pairs_data: Dict[str, Dict]) -> Dict[str, TokenData]:
        """
        Parses the batch response from DexScreener into TokenData objects.
        AMÉLIORÉ: Gère aussi les données individuelles
        """
        self.logger.info(f"🔍 [PARSE] Starting parse of {len(pairs_data)} pairs")

        token_data_map = {}
        for token_address, pair_data in pairs_data.items():
            try:
                self.logger.info(f"🔍 [PARSE] Processing {token_address[:8]}...")

                if not (pair_data and pair_data.get('baseToken')):
                    self.logger.debug(f"❌ [PARSE] Invalid pair data for {token_address[:8]}...")
                    continue
                
                # Détecter si c'est notre token dans baseToken ou quoteToken
                base_token_addr = pair_data.get('baseToken', {}).get('address')
                quote_token_addr = pair_data.get('quoteToken', {}).get('address')
                
                # Déterminer quel token nous intéresse
                if base_token_addr == token_address:
                    target_token = pair_data.get('baseToken', {})
                elif quote_token_addr == token_address:
                    target_token = pair_data.get('quoteToken', {})
                    # Inverser les données si notre token est en quote
                    # (cas rare mais possible)
                    self.logger.debug(f"⚠️ [PARSE] Token {token_address[:8]}... found as quoteToken")
                else:
                    # Cas normal: notre token est le baseToken
                    target_token = pair_data.get('baseToken', {})
                
                creation_timestamp = 0
                if 'pairCreatedAt' in pair_data:
                    creation_time = pair_data['pairCreatedAt']
                    if creation_time and creation_time > 1e12:
                        creation_timestamp = int(creation_time // 1000)
                    elif creation_time:
                        creation_timestamp = int(creation_time)

                token_data = TokenData(
                    address=token_address,
                    symbol=target_token.get('symbol'),
                    name=target_token.get('name'),
                    price_usd=float(pair_data.get('priceUsd', 0) or 0),
                    timestamp_token_created=creation_timestamp,
                    market_cap=float(pair_data.get('fdv', 0) or 0),
                    volume_5m=float(pair_data.get('volume', {}).get('m5', 0) or 0),
                    volume_1h=float(pair_data.get('volume', {}).get('h1', 0) or 0),
                    volume_6h=float(pair_data.get('volume', {}).get('h6', 0) or 0),
                    volume_24h=float(pair_data.get('volume', {}).get('h24', 0) or 0),
                    price_change_5m=float(pair_data.get('priceChange', {}).get('m5', 0) or 0),
                    price_change_1h=float(pair_data.get('priceChange', {}).get('h1', 0) or 0),
                    price_change_6h=float(pair_data.get('priceChange', {}).get('h6', 0) or 0),
                    price_change_24h=float(pair_data.get('priceChange', {}).get('h24', 0) or 0),
                    liquidity_usd=float(pair_data.get('liquidity', {}).get('usd', 0) or 0),
                    liquidity_sol=float(pair_data.get('liquidity', {}).get('base', 0) or 0),
                    fdv=float(pair_data.get('fdv', 0) or 0),
                    metadata_source="dexscreener_batch_enhanced",
                    original_address=token_address
                )
                token_data_map[token_address] = token_data
                self.logger.info(f"✅ [PARSE] Successfully parsed {token_address[:8]}...")

            except Exception as e:
                self.logger.error(f"Error parsing pair data for token {token_address}: {e}")
        
        self.logger.info(f"📊 [PARSE] Final result: {len(token_data_map)} tokens parsed successfully")

        return token_data_map

    def update_queue_status(self, token_address: str, success: bool, error_message: Optional[str] = None):
        """Updates the status of a token in the processing queue."""
        status = 'completed' if success else 'failed'
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                if success:
                    cursor.execute("""
                        UPDATE token_processing_queue
                        SET status = ?, completed_at = CURRENT_TIMESTAMP, last_error = NULL
                        WHERE token_address = ?
                    """, (status, token_address))
                else:
                    cursor.execute("""
                        UPDATE token_processing_queue
                        SET status = ?, completed_at = CURRENT_TIMESTAMP, last_error = ?, retry_count = retry_count + 1
                        WHERE token_address = ?
                    """, (status, error_message, token_address))
                conn.commit()
            self.logger.debug(f"Queue status for {token_address} updated to {status}.")
        except Exception as e:
            self.logger.error(f"Failed to update queue status for {token_address}: {e}")


    async def process_tokens_in_batches_async(self, tokens: List[str]) -> int:
        """
        Processes a list of tokens asynchronously using the batch API endpoint.
        AMÉLIORÉ: Fallback individuel pour tokens manqués dans le batch
        """
        if not tokens:
            return 0
        
        start_time = time.time()
        successful_upserts = 0
        
        # 1. Tentative de traitement en batch
        async with aiohttp.ClientSession() as session:
            all_pairs_data = await self.fetch_dexscreener_batch_data(session, tokens)
        
        # 2. Parse les données batch obtenues
        token_data_map = self._parse_dexscreener_batch_response(all_pairs_data)
        
        # 3. Identifier les tokens manqués
        found_tokens = set(token_data_map.keys())
        missing_tokens = set(tokens) - found_tokens
        
        # ✅ NOUVEAU: Fallback individuel pour tokens manqués
        if missing_tokens:
            self.logger.warning(f"🔍 [FALLBACK] Traitement individuel de {len(missing_tokens)} tokens manqués: {[t[:8] for t in missing_tokens]}")
            
            async with aiohttp.ClientSession() as session:
                # Traiter les tokens manqués individuellement
                for token_addr in missing_tokens:
                    try:
                        individual_token_data = await self.fetch_individual_token_data(session, token_addr)
                        if individual_token_data:
                            token_data_map[token_addr] = individual_token_data
                            self.logger.debug(f"✅ [FALLBACK] Token récupéré individuellement: {token_addr[:8]}...")
                        else:
                            self.logger.debug(f"❌ [FALLBACK] Token introuvable même individuellement: {token_addr[:8]}...")
                        
                        # Pause entre requêtes individuelles
                        await asyncio.sleep(0.5)
                        
                    except Exception as e:
                        self.logger.error(f"❌ [FALLBACK] Erreur traitement individuel {token_addr[:8]}...: {e}")
        
        # 4. Créer les tâches de base de données pour TOUS les tokens
        db_tasks = []
        for token_address in tokens:
            token_data = token_data_map.get(token_address)
            
            if token_data:
                db_tasks.append(asyncio.to_thread(self.upsert_token, token_data))
            else:
                # Créer un stub si aucune donnée trouvée
                db_tasks.append(asyncio.to_thread(self.create_token_stub, token_address))
        
        # 5. Exécuter les opérations de base de données
        db_results = await asyncio.gather(*db_tasks, return_exceptions=True)

        # 6. Compter les résultats et mettre à jour la file d'attente
        failed_count = 0
        for i, result in enumerate(db_results):
            token_addr = tokens[i]
            
            if isinstance(result, Exception):
                self.logger.error(f"DB operation failed for token {token_addr}: {result}")
                failed_count += 1
                self.update_queue_status(token_addr, success=False, error_message=str(result))
            elif result:
                successful_upserts += 1
                self.update_queue_status(token_addr, success=True)
            else:
                failed_count += 1
                error_msg = "Upsert returned False"
                self.update_queue_status(token_addr, success=False, error_message=error_msg)

        # 7. Statistiques
        self.stats['successful_updates'] += successful_upserts
        self.stats['failed_updates'] += failed_count
        self.stats['processed_tokens'] += len(tokens)

        total_duration = time.time() - start_time
        batch_success = len(found_tokens)
        fallback_success = len([t for t in missing_tokens if t in token_data_map])
        
        self.logger.debug(f"🏁 Batch processing completed: {successful_upserts}/{len(tokens)} successful in {total_duration:.2f}s")
        self.logger.debug(f"📊 Details: batch={batch_success}, fallback={fallback_success}, stubs={len(tokens)-successful_upserts}")
        
        return successful_upserts

    async def fetch_individual_token_data(self, session: aiohttp.ClientSession, token_address: str) -> Optional[TokenData]:
        """
        Récupère les données d'un token individuellement via l'API DexScreener
        CORRIGÉ: Retourne un objet TokenData au lieu d'un Dict
        """
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            
            start_time = time.time()
            async with session.get(url, timeout=self.config.rpc.timeout) as response:
                api_duration = time.time() - start_time
                self._record_api_call('dexscreener_individual_fallback', api_duration)
                
                if response.status == 200:
                    data = await response.json()
                    
                    if data and data.get('pairs'):
                        # Prendre la meilleure paire (même logique que le batch)
                        best_pair = max(data['pairs'], key=lambda p: float(p.get('volume', {}).get('h24', 0) or 0))
                        
                        # ✅ CORRECTION: Convertir en TokenData
                        token_data = self._convert_pair_to_token_data(token_address, best_pair)
                        
                        self.logger.debug(f"🔍 [INDIVIDUAL] Token trouvé: {token_address[:8]}... (vol24h: ${float(best_pair.get('volume', {}).get('h24', 0) or 0):,.0f})")
                        return token_data
                    else:
                        self.logger.debug(f"🔍 [INDIVIDUAL] Aucune paire pour: {token_address[:8]}...")
                        return None
                else:
                    self.logger.debug(f"🔍 [INDIVIDUAL] HTTP {response.status} pour: {token_address[:8]}...")
                    return None
                    
        except Exception as e:
            self.logger.error(f"🔍 [INDIVIDUAL] Erreur pour {token_address[:8]}...: {e}")
            return None

    def _convert_pair_to_token_data(self, token_address: str, pair_data: Dict) -> TokenData:
        """
        Convertit les données d'une paire DexScreener en objet TokenData
        """
        try:
            # Déterminer quel token nous intéresse
            base_token_addr = pair_data.get('baseToken', {}).get('address')
            quote_token_addr = pair_data.get('quoteToken', {}).get('address')
            
            if base_token_addr == token_address:
                target_token = pair_data.get('baseToken', {})
            elif quote_token_addr == token_address:
                target_token = pair_data.get('quoteToken', {})
                self.logger.debug(f"⚠️ [CONVERT] Token {token_address[:8]}... found as quoteToken")
            else:
                # Cas par défaut: prendre baseToken
                target_token = pair_data.get('baseToken', {})
            
            # Gérer le timestamp de création
            creation_timestamp = 0
            if 'pairCreatedAt' in pair_data:
                creation_time = pair_data['pairCreatedAt']
                if creation_time and creation_time > 1e12:
                    creation_timestamp = int(creation_time // 1000)
                elif creation_time:
                    creation_timestamp = int(creation_time)

            # Créer l'objet TokenData
            token_data = TokenData(
                address=token_address,
                symbol=target_token.get('symbol'),
                name=target_token.get('name'),
                price_usd=float(pair_data.get('priceUsd', 0) or 0),
                timestamp_token_created=creation_timestamp,
                market_cap=float(pair_data.get('fdv', 0) or 0),
                volume_5m=float(pair_data.get('volume', {}).get('m5', 0) or 0),
                volume_1h=float(pair_data.get('volume', {}).get('h1', 0) or 0),
                volume_6h=float(pair_data.get('volume', {}).get('h6', 0) or 0),
                volume_24h=float(pair_data.get('volume', {}).get('h24', 0) or 0),
                price_change_5m=float(pair_data.get('priceChange', {}).get('m5', 0) or 0),
                price_change_1h=float(pair_data.get('priceChange', {}).get('h1', 0) or 0),
                price_change_6h=float(pair_data.get('priceChange', {}).get('h6', 0) or 0),
                price_change_24h=float(pair_data.get('priceChange', {}).get('h24', 0) or 0),
                liquidity_usd=float(pair_data.get('liquidity', {}).get('usd', 0) or 0),
                liquidity_sol=float(pair_data.get('liquidity', {}).get('base', 0) or 0),
                fdv=float(pair_data.get('fdv', 0) or 0),
                metadata_source="dexscreener_individual_fallback",
                original_address=token_address
            )
            
            return token_data
            
        except Exception as e:
            self.logger.error(f"❌ [CONVERT] Erreur conversion pair->TokenData pour {token_address[:8]}...: {e}")
            # Retourner un TokenData minimal en cas d'erreur
            return TokenData(
                address=token_address,
                symbol=f"UNK_{token_address[:6]}",
                name=f"Unknown Token {token_address[:8]}",
                metadata_source="dexscreener_fallback_error"
            )

    def sync_new_tokens(self) -> int:
        """Optimized version with async batch processing from a queue."""
        self.logger.debug("🚀 Starting token synchronization from queue...")
        
        all_new_tokens = self.get_pending_tokens_from_queue(self.config.batching.batch_sizes['dexscreener'])
        
        if not all_new_tokens:
            self.logger.debug("No new tokens in queue to process")
            return 0
        
        # We can process them all in one async run, priority doesn't matter for fetching
        # as much when it's all concurrent.
        self.logger.debug(f"📊 Processing {len(all_new_tokens)} new tokens asynchronously")
        
        result = asyncio.run(self.process_tokens_in_batches_async(all_new_tokens))

        self.cycle_logger.record_operation('new_tokens', result)
        
        return result

    def update_existing_prices(self) -> int:
        """Version simplifiée : mise à jour des tokens selon intervalle et limite configurés"""
        
        self.logger.debug("🔄 Starting simple price updates...")
        
        # Récupérer les tokens à mettre à jour
        tokens_to_update = self.get_tokens_needing_price_update_simple()
        
        if not tokens_to_update:
            self.logger.debug("No tokens need price updates.")
            return 0
        
        self.logger.info(f"📊 Updating {len(tokens_to_update)} tokens (limit: {self.config.monitoring.price_update_limit})")
        
        # Traitement en lot via la méthode batch existante
        try:
            result = asyncio.run(self.process_tokens_in_batches_async(tokens_to_update))
            self.logger.info(f"✅ Price update completed: {result}/{len(tokens_to_update)} successful")
            
            self.cycle_logger.record_operation('updated_tokens', result)
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Error in price update: {e}")
            return 0

    def get_tokens_needing_price_update_simple(self) -> List[str]:
        """Récupère les tokens nécessitant une mise à jour selon la config simple"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Calculer le timestamp de cutoff
                cutoff_timestamp = int(time.time()) - self.config.monitoring.price_update_interval_seconds
                
                query = """
                SELECT address 
                FROM tokens 
                WHERE (last_price_update < ? OR last_price_update IS NULL)
                AND is_dead = 0
                AND (no_data_available = 0 OR no_data_available IS NULL)
                AND (failed_attempts < ? OR failed_attempts IS NULL)
                ORDER BY 
                    CASE WHEN last_price_update IS NULL THEN 0 ELSE last_price_update END ASC,
                    market_cap DESC NULLS LAST
                LIMIT ?
                """
                
                cursor.execute(query, (
                    cutoff_timestamp, 
                    self.config.monitoring.max_failed_attempts, 
                    self.config.monitoring.price_update_limit
                ))
                
                results = cursor.fetchall()
                token_addresses = [row[0] for row in results]
                
                if token_addresses:
                    self.logger.debug(f"Found {len(token_addresses)} tokens needing update (cutoff: {datetime.fromtimestamp(cutoff_timestamp).strftime('%H:%M:%S')})")
                
                return token_addresses
                
        except Exception as e:
            self.logger.error(f"Error getting tokens for simple price update: {e}")
            return []

    #not used anymore for the moment
    def update_existing_prices_old(self) -> int:
        """Optimized version to update existing token prices asynchronously."""
        self.logger.debug("🔄 Starting ASYNC price updates...")
        
        # 1. Get dashboard tokens needing updates first
        dashboard_tokens = self.get_dashboard_tokens_needing_update()
        
        # 2. Get other tokens needing updates
        other_tokens = self.get_tokens_needing_price_update()
        
        # Combine and deduplicate, keeping dashboard tokens at the front for priority
        tokens_to_update = list(dict.fromkeys(dashboard_tokens + other_tokens))
        
        if not tokens_to_update:
            self.logger.debug("No tokens need price updates.")
            return 0
        
        self.logger.debug(f"Found {len(tokens_to_update)} total tokens for price update (Dashboard: {len(dashboard_tokens)})")
        
        # Process all tokens in one async batch
        result = asyncio.run(self.process_tokens_in_batches_async(tokens_to_update))

        self.cycle_logger.record_operation('updated_tokens', result)
        
        return result
        
    def get_flagged_tokens_stats(self) -> Dict:
        """Get statistics about flagged tokens"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Tokens marqués comme no_data
                cursor.execute("SELECT COUNT(*) FROM tokens WHERE no_data_available = 1")
                no_data_count = cursor.fetchone()[0]
                
                # Tokens avec des tentatives échouées mais pas encore flaggés
                cursor.execute("SELECT COUNT(*) FROM tokens WHERE failed_attempts > 0 AND no_data_available = 0")
                partial_failures = cursor.fetchone()[0]
                
                # Tokens éligibles pour retry
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens 
                    WHERE no_data_available = 1 
                    AND no_data_last_check < datetime('now', '-' || ? || ' days')
                """, (self.config.monitoring.retry_failed_after_days,))
                retry_eligible = cursor.fetchone()[0]
                
                # Tokens morts
                cursor.execute("SELECT COUNT(*) FROM tokens WHERE is_dead = 1")
                dead_count = cursor.fetchone()[0]
                
                return {
                    'no_data_flagged': no_data_count,
                    'partial_failures': partial_failures,
                    'retry_eligible': retry_eligible,
                    'dead_tokens': dead_count
                }
                
        except Exception as e:
            self.logger.error(f"Error getting flagged tokens stats: {e}")
            return {}

    def print_statistics(self):
        """Print current statistics"""
        if self.stats['start_time']:
            runtime = time.time() - self.stats['start_time']
            runtime_str = str(timedelta(seconds=int(runtime)))
        else:
            runtime_str = "N/A"
        
        # Stats de flagging
        flagged_stats = self.get_flagged_tokens_stats()
        
        
        self.logger.debug("=== TOKEN SYNC STATISTICS ===")
        self.logger.debug(f"Runtime: {runtime_str}")
        self.logger.debug(f"Processed tokens: {self.stats['processed_tokens']}")
        self.logger.debug(f"Successful updates: {self.stats['successful_updates']}")
        self.logger.debug(f"Failed updates: {self.stats['failed_updates']}")
        self.logger.debug(f"API calls made: {self.stats['api_calls']}")
        self.logger.debug(f"Tokens historized: {self.stats['tokens_historized']}")
        self.logger.debug(f"Tokens marked dead: {self.stats['tokens_marked_dead']}")
        
        # Stats de flagging
        if flagged_stats:
            self.logger.debug("=== FLAGGED TOKENS STATS ===")
            self.logger.debug(f"Tokens marked as no-data: {flagged_stats.get('no_data_flagged', 0)}")
            self.logger.debug(f"Tokens with partial failures: {flagged_stats.get('partial_failures', 0)}")
            self.logger.debug(f"Tokens eligible for retry: {flagged_stats.get('retry_eligible', 0)}")
            self.logger.debug(f"Dead tokens: {flagged_stats.get('dead_tokens', 0)}")

        if self.stats['processed_tokens'] > 0:
            success_rate = (self.stats['successful_updates'] / self.stats['processed_tokens']) * 100
            self.logger.debug(f"Success rate: {success_rate:.1f}%")

        self.print_api_statistics()
    

    def print_api_statistics(self):
        """Print detailed API statistics"""
        try:
            api_stats = self.api_tracker.get_stats()
            
            if not api_stats:
                self.logger.debug("=== 📡 API STATISTICS ===")
                self.logger.debug("No API statistics available")
                return
            
            self.logger.debug("=== 📡 API STATISTICS ===")
            
            # Sort by total calls for better readability
            sorted_apis = sorted(api_stats.items(), key=lambda x: x[1].get('total_calls', 0), reverse=True)
            
            for api_name, stats in sorted_apis:
                if stats.get('total_calls', 0) > 0:  # Only show APIs that have been called
                    self.logger.debug(f"🔗 {api_name.upper()}")
                    self.logger.debug(f"   Total: {stats.get('total_calls', 0)} calls | {stats.get('total_duration_seconds', 0)}s | avg {stats.get('avg_duration_seconds', 0)}s")
                    self.logger.debug(f"   Recent: 5m={stats.get('calls_5m', 0)} | 30m={stats.get('calls_30m', 0)} | 1h={stats.get('calls_1h', 0)}")
                    self.logger.debug(f"   Rate/min: 5m={stats.get('rate_per_minute_5m', 0)} | 30m={stats.get('rate_per_minute_30m', 0)} | 1h={stats.get('rate_per_minute_1h', 0)}")
                    
                    # Alert if rate is too high
                    if stats.get('rate_per_minute_5m', 0) > 10:  # Plus de 10 appels/min sur 5min
                        self.logger.warning(f"   ⚠️ HIGH RATE: {stats.get('rate_per_minute_5m', 0)} calls/min")
            
            # Summary
            total_calls = sum(stats.get('total_calls', 0) for stats in api_stats.values())
            total_duration = sum(stats.get('total_duration_seconds', 0) for stats in api_stats.values())
            total_5m = sum(stats.get('calls_5m', 0) for stats in api_stats.values())
            
            self.logger.debug(f"📊 SUMMARY: {total_calls} total calls | {total_duration:.1f}s total | {total_5m} calls last 5min")
            
        except Exception as e:
            self.logger.error(f"Error printing API statistics: {e}")
            # Debug info
            self.logger.debug(f"API tracker exists: {hasattr(self, 'api_tracker')}")
            if hasattr(self, 'api_tracker'):
                self.logger.debug(f"API tracker type: {type(self.api_tracker)}")
                self.logger.debug(f"API tracker stats keys: {list(self.api_tracker.stats.keys()) if hasattr(self.api_tracker, 'stats') else 'No stats'}")

    
    def log_api_rate_usage(self):
        """Log l'utilisation du rate limit en temps réel"""
        try:
            api_stats = self.api_tracker.get_stats()
            
            # Stats pour DexScreener batch
            if 'dexscreener_tokens_batch_async' in api_stats:
                calls_1m = api_stats['dexscreener_tokens_batch_async']['calls_1h'] / 60
                calls_5m = api_stats['dexscreener_tokens_batch_async']['calls_5m']
                rate_1m = api_stats['dexscreener_tokens_batch_async']['rate_per_minute_1h']
                
                usage_pct = (rate_1m / 60) * 100
                
                self.logger.debug(f"🎯 DexScreener rate usage: {rate_1m:.1f}/60 req/min ({usage_pct:.1f}%) | Last 5min: {calls_5m} calls")
                
                # Alert si on approche de la limite
                if usage_pct > 85:
                    self.logger.warning(f"⚠️ HIGH API USAGE: {usage_pct:.1f}% of rate limit!")
                elif usage_pct > 70:
                    self.logger.debug(f"📊 Moderate API usage: {usage_pct:.1f}%")
            
            # Stats globales toutes APIs
            total_calls_5m = sum(stats.get('calls_5m', 0) for stats in api_stats.values())
            total_rate_1h = sum(stats.get('rate_per_minute_1h', 0) for stats in api_stats.values())
            
            self.logger.debug(f"📈 Total API activity: {total_rate_1h:.1f} calls/min | Last 5min: {total_calls_5m} calls")
            
        except Exception as e:
            self.logger.debug(f"Error logging API rate usage: {e}")

    def record_call(self, api_name: str, duration: float, success: bool = True, 
                http_status: int = None, error_msg: str = None):
        """Record an API call with duration and store in database - DEBUG VERSION"""
        current_time = time.time()
        duration_ms = int(duration * 1000)  # Convert to milliseconds
        
        # DEBUG: Log every call
        #print(f"🔍 DEBUG API: Recording {api_name} call - duration: {duration:.3f}s, success: {success}, cycle: {self.current_cycle_id}")
        
        with self.lock:
            # Update in-memory stats (existing logic)
            api_stats = self.stats[api_name]
            api_stats.total_calls += 1
            api_stats.total_duration += duration
            
            call_record = (current_time, duration)
            api_stats.calls_5m.append(call_record)
            api_stats.calls_30m.append(call_record)
            api_stats.calls_1h.append(call_record)
            
            self._clean_old_records(api_stats, current_time)
        
        # Store in database (non-blocking)
        if self.db_service:
            try:
                result = self._store_api_call_to_db(
                    api_name, int(current_time), duration_ms, 
                    success, http_status, error_msg
                )
                #print(f"🔍 DEBUG API: DB storage result for {api_name}: {result}")
            except Exception as e:
                # Don't fail the API call if DB storage fails
                #print(f"❌ DEBUG API: Failed to store API metric to DB: {e}")
                if hasattr(self.db_service, 'logger'):
                    self.db_service.cycle_logger.record_api_call(api_name, 1)

    def get_api_summary(self) -> str:
        """Get a quick API summary for live monitoring"""
        api_stats = self.api_tracker.get_stats()
        
        if not api_stats:
            return "No API data"
        
        total_5m = sum(stats['calls_5m'] for stats in api_stats.values())
        total_30m = sum(stats['calls_30m'] for stats in api_stats.values())
        
        # Top 3 APIs by recent activity
        top_apis = sorted(api_stats.items(), key=lambda x: x[1]['calls_5m'], reverse=True)[:3]
        top_summary = " | ".join([f"{name}:{stats['calls_5m']}" for name, stats in top_apis if stats['calls_5m'] > 0])
        
        return f"APIs 5m: {total_5m} total ({top_summary}) | 30m: {total_30m}"

    def run_sync_cycle(self):
        """Run one complete synchronization cycle - CORRIGÉ"""
        self.logger.debug("Starting synchronization cycle...")
        self.logger.debug(f"🔍 API tracker status: {hasattr(self, 'api_tracker')}")
        cycle_id = self.start_sync_cycle()
        total_tokens_processed = 0
        
        # ✅ CORRECTION: Initialiser TOUTES les variables dès le début
        new_tokens_updated = 0
        prices_updated = 0
        creation_timestamps_updated = 0
        historized_count = 0
        dead_tokens_marked = 0
        pumpfun_updated = 0
        
        try:
            self.log_api_rate_usage()
            
            # 1. Sync new tokens from transactions
            new_tokens_updated = self.sync_new_tokens()
            self.logger.debug("=== STATS API APRÈS NOUVEAUX TOKENS ===")
            self.print_api_statistics()
            self.log_api_rate_usage()

            

            # 2. Update existing token prices
            prices_updated = self.update_existing_prices()
            self.logger.debug("=== STATS API APRÈS PRIX ===")
            self.print_api_statistics()
            self.print_api_database_stats()
            self.log_api_rate_usage()

            total_tokens_processed = new_tokens_updated + prices_updated
            self.logger.debug(f"Sync cycle completed: {new_tokens_updated} new, {prices_updated} price updates...")
            
            self.debug_historization_status()

            # # 3. Run historization cycle (every few cycles)
            # if not hasattr(self, 'cycle_count'):
            #     self.cycle_count = 0
            
            # self.cycle_count += 1
            
            # # Every 3 cycles - run historization
            # if self.cycle_count % 3 == 0:
            #     historized_count = self.run_historization_cycle()
            #     self.logger.debug("=== STATS API APRÈS HISTORISATION ===")
            #     self.print_api_statistics()
            #     self.log_api_rate_usage()

            # # Every 5 cycles - update missing creation timestamps
            # if self.cycle_count % 5 == 0:
            #     creation_timestamps_updated = self.update_missing_creation_timestamps()
            #     self.logger.debug("=== STATS API APRÈS TIMESTAMPS ===")
            #     self.print_api_statistics()
            #     self.log_api_rate_usage()

            # # Every 6 cycles - check for dead tokens (DÉSACTIVÉ)
            # # if self.cycle_count % 6 == 0:
            # #     dead_tokens_marked = self.run_dead_token_check()
            # #     self.logger.debug("=== STATS API APRÈS DEAD TOKENS ===")
            # #     self.print_api_statistics()

            # # Every 10 cycles - update Pump.fun tokens
            # if self.cycle_count % 10 == 0:
            #     pumpfun_updated = self.update_pumpfun_tokens()
            #     self.logger.debug(f"Pump.fun tokens updated: {pumpfun_updated}")
            #     self.logger.debug("=== STATS API APRÈS PUMPFUN ===")
            #     self.print_api_statistics()
            #     self.log_api_rate_usage()

            # 4. Print statistics
            self.print_statistics()
            
            # Summary final du rate usage
            self.logger.debug("=== 🎯 FINAL API RATE SUMMARY ===")
            self.log_api_rate_usage()

            self.logger.debug(f"Sync cycle completed: {new_tokens_updated} new, {prices_updated} price updates, {creation_timestamps_updated} creation timestamps, {historized_count} historized, {dead_tokens_marked} marked dead")
            
        except Exception as e:
            self.logger.error(f"Error in sync cycle: {e}")
            # ✅ CORRECTION: Log l'erreur complète pour debugging
            import traceback
            self.logger.error(f"Full traceback: {traceback.format_exc()}")
        finally:
            # ✅ CORRECTION - Terminer le cycle dans le finally
            self.end_sync_cycle(total_tokens_processed)

    def start(self):
        """Start the continuous synchronization service"""
        self.logger.debug("Starting Token Sync Service...")

        if not self.check_database_health():
            self.logger.error("❌ Database health check failed. Stopping service.")
            return
        
        self.running = True
        self.stats['start_time'] = time.time()

        try:
            while self.running:
                # Vérifier la santé de la DB périodiquement
                if not hasattr(self, 'last_health_check'):
                    self.last_health_check = time.time()
                
                # Check database health every 30 minutes
                if time.time() - self.last_health_check > 1800:
                    if not self.check_database_health():
                        self.logger.warning("⚠️ Database health check failed during operation")
                    self.last_health_check = time.time()

                self.run_sync_cycle()
                
                if self.running:  # Check if still running before sleeping
                    self.logger.debug(f"Waiting {self.config.monitoring.enrichment_interval_seconds} seconds until next cycle...")
                    self.log_api_rate_usage() 
                    time.sleep(self.config.monitoring.enrichment_interval_seconds)
                    
        except KeyboardInterrupt:
            self.logger.debug("Received interrupt signal")
        except Exception as e:
            self.logger.error(f"Unexpected error in main loop: {e}")
        finally:
            self.stop()
    
    def stop(self):
        """Stop the synchronization service"""
        self.logger.debug("Stopping Token Sync Service...")
        self.running = False
        self.session.close()
        self.print_statistics()
        self.logger.debug("Token Sync Service stopped")

def signal_handler(signum, frame):
    """Handle termination signals"""
    global service
    if service:
        service.stop()
    sys.exit(0)

def main():
    """Main entry point"""
    global service
    
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Initialize service
    service = TokenSyncService()
    
    # Start service
    service.start()

if __name__ == "__main__":
    service = None
    main()