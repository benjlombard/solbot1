
"""
Solana Wallet Monitor - Wallet Priority Manager
Dynamic priority scoring system for intelligent wallet scanning
"""

import time
import threading
import json
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
import heapq
import sqlite3

# Core imports with fallbacks
try:
    from core.logger import get_logger
    from core.database import get_database_manager
    from core.config import get_config
    from core.exceptions import PrioritySystemError
    
    from models.wallet import WalletPriority, WalletStats
    from utils.helpers import get_current_timestamp, clamp, safe_divide
    from utils.validators import quick_validate_address as validate_wallet_address

    
except ImportError as e:
    # Fallback implementations for development
    import logging
    def get_logger(name=None):
        return logging.getLogger(name or 'priority_manager')
    
    def get_database_manager(): return None
    def get_config(): return None
    
    def validate_wallet_address(addr):
        logging.getLogger('priority_manager').warning("Using fallback address validator for %s", addr)
        return len(addr) == 44

# Logger
logger = get_logger(__name__)

@dataclass
class PriorityScore:
    """Enhanced priority score with detailed breakdown"""
    wallet_address: str
    base_score: float = 5.0
    activity_bonus: float = 0.0
    volume_bonus: float = 0.0
    recency_bonus: float = 0.0
    discovery_bonus: float = 0.0
    penalty: float = 0.0
    final_score: float = 5.0
    calculation_time: int = field(default_factory=get_current_timestamp)
    
    @property
    def priority_category(self) -> str:
        """Categorize priority score"""
        if self.final_score >= 8.0:
            return "CRITICAL"
        elif self.final_score >= 6.0:
            return "HIGH"
        elif self.final_score >= 3.0:
            return "MEDIUM"
        elif self.final_score >= 1.0:
            return "LOW"
        else:
            return "VERY_LOW"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            'wallet_address': self.wallet_address,
            'base_score': self.base_score,
            'activity_bonus': self.activity_bonus,
            'volume_bonus': self.volume_bonus,
            'recency_bonus': self.recency_bonus,
            'discovery_bonus': self.discovery_bonus,
            'penalty': self.penalty,
            'final_score': self.final_score,
            'priority_category': self.priority_category,
            'calculation_time': self.calculation_time
        }

class WalletPriorityManager:
    """
    Intelligent priority management system for wallet scanning
    Uses dynamic scoring based on activity, volume, and recency
    """
    
    def __init__(self):
        self.db_manager = get_database_manager()
        self.config = get_config()
        
        # Thread-safe storage
        self._lock = threading.Lock()
        self._wallet_priorities: Dict[str, WalletPriority] = {}
        self._priority_scores: Dict[str, PriorityScore] = {}
        self._selection_queue: List[Tuple[float, str, int]] = []
        self._last_selection_time: Dict[str, int] = {}
        
        # Configuration constants
        self.MAX_PRIORITY = 10.0
        self.MIN_PRIORITY = 0.1
        self.DEFAULT_PRIORITY = 5.0
        
        # Scoring weights
        self.WEIGHTS = {
            'activity': 0.3,
            'volume': 0.25,
            'recency': 0.2,
            'discovery': 0.15,
            'penalty': 0.1
        }
        
        self._initialize_system()
        logger.info("🎯 Wallet priority manager initialized")
    
    def _initialize_system(self):
        """Initialize priority system from database"""
        try:
            if self.db_manager:
                self._load_priorities_from_db()
            else:
                logger.warning("⚠️ No database manager available, using memory storage")
                
        except Exception as e:
            logger.error(f"❌ Error initializing priority system: {e}")
    
    def _load_priorities_from_db(self):
        """Load existing priorities from database"""
        try:
            with self.db_manager.get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM wallet_priorities")
                
                for row in cursor.fetchall():
                    wallet_priority = WalletPriority(
                        wallet_address=row['wallet_address'],
                        priority_score=float(row['priority_score']),
                        last_scan_time=row['last_scan_time'],
                        scan_count_1h=int(row['scan_count_1h']),
                        scan_count_24h=int(row['scan_count_24h']),
                        activity_score=float(row['activity_score']),
                        volume_score_1h=float(row['volume_score_1h']),
                        new_tokens_score_1h=float(row['new_tokens_score_1h']),
                        total_scans=int(row['total_scans']),
                        avg_scan_duration=float(row['avg_scan_duration']),
                        last_activity_detected=row['last_activity_detected'],
                        consecutive_empty_scans=int(row['consecutive_empty_scans']),
                        priority_history=json.loads(row['priority_history']) if row['priority_history'] else [],
                        updated_at=row['updated_at'],
                        created_at=row['created_at']
                    )
                    
                    with self._lock:
                        self._wallet_priorities[row['wallet_address']] = wallet_priority
                
                logger.info(f"✅ Loaded {len(self._wallet_priorities)} wallet priorities")
                
        except Exception as e:
            logger.error(f"❌ Error loading priorities: {e}")
    
    def add_wallet(self, wallet_address: str, initial_priority: float = 5.0) -> bool:
        """Add a new wallet to priority management"""
        try:
            if not validate_wallet_address(wallet_address):
                logger.warning(f"❌ Invalid wallet address: {wallet_address}")
                return False
            
            with self._lock:
                if wallet_address not in self._wallet_priorities:
                    now = get_current_timestamp()
                    
                    wallet_priority = WalletPriority(
                        wallet_address=wallet_address,
                        priority_score=clamp(initial_priority, self.MIN_PRIORITY, self.MAX_PRIORITY),
                        last_scan_time=0,
                        scan_count_1h=0,
                        scan_count_24h=0,
                        activity_score=0.0,
                        volume_score_1h=0.0,
                        new_tokens_score_1h=0.0,
                        total_scans=0,
                        avg_scan_duration=0.0,
                        last_activity_detected=0,
                        consecutive_empty_scans=0,
                        priority_history=[],
                        updated_at=now,
                        created_at=now
                    )
                    
                    self._wallet_priorities[wallet_address] = wallet_priority
                    logger.info(f"✅ Added wallet {wallet_address} with priority {initial_priority}")
                    
                    # Save to database
                    self._save_priority(wallet_priority)
                
            return True
            
        except Exception as e:
            logger.error(f"❌ Error adding wallet {wallet_address}: {e}")
            return False
    
    def remove_wallet(self, wallet_address: str) -> bool:
        """Remove a wallet from priority management"""
        try:
            with self._lock:
                if wallet_address in self._wallet_priorities:
                    del self._wallet_priorities[wallet_address]
                    self._priority_scores.pop(wallet_address, None)
                    logger.info(f"✅ Removed wallet {wallet_address}")
                    return True
            return False
            
        except Exception as e:
            logger.error(f"❌ Error removing wallet {wallet_address}: {e}")
            return False
    
    def calculate_priority_score(self, wallet_address: str) -> PriorityScore:
        """Calculate comprehensive priority score for a wallet"""
        try:
            with self._lock:
                if wallet_address not in self._wallet_priorities:
                    raise PrioritySystemError(f"Wallet not found: {wallet_address}")
                
                priority = self._wallet_priorities[wallet_address]
            
            # Base score calculation
            base_score = self.DEFAULT_PRIORITY
            
            # Activity bonus based on recent activity
            activity_bonus = self._calculate_activity_bonus(priority)
            
            # Volume bonus based on transaction volume
            volume_bonus = self._calculate_volume_bonus(wallet_address)
            
            # Recency bonus for recent activity
            recency_bonus = self._calculate_recency_bonus(priority)
            
            # Discovery bonus for new token discoveries
            discovery_bonus = self._calculate_discovery_bonus(wallet_address)
            
            # Penalty for empty scans or inactivity
            penalty = self._calculate_penalty(priority)
            
            # Calculate final score
            final_score = base_score + activity_bonus + volume_bonus + recency_bonus + discovery_bonus - penalty
            
            # Clamp to valid range
            final_score = clamp(final_score, self.MIN_PRIORITY, self.MAX_PRIORITY)
            
            score = PriorityScore(
                wallet_address=wallet_address,
                base_score=base_score,
                activity_bonus=activity_bonus,
                volume_bonus=volume_bonus,
                recency_bonus=recency_bonus,
                discovery_bonus=discovery_bonus,
                penalty=penalty,
                final_score=final_score
            )
            
            # Cache the score
            with self._lock:
                self._priority_scores[wallet_address] = score
            
            return score
            
        except Exception as e:
            logger.error(f"❌ Error calculating priority for {wallet_address}: {e}")
            return PriorityScore(wallet_address=wallet_address, final_score=self.DEFAULT_PRIORITY)
    
    def _calculate_activity_bonus(self, priority: WalletPriority) -> float:
        """Calculate activity-based bonus"""
        now = get_current_timestamp()
        hours_since_activity = safe_divide(now - priority.last_activity_detected, 3600)
        
        # Bonus for recent activity (decays over 24h)
        if hours_since_activity < 1:
            return 3.0
        elif hours_since_activity < 6:
            return 2.0
        elif hours_since_activity < 24:
            return 1.0
        elif hours_since_activity > 168:  # 1 week
            return -2.0  # Penalty for very old activity
        
        return 0.0
    
    def _calculate_volume_bonus(self, wallet_address: str) -> float:
        """Calculate volume-based bonus"""
        try:
            if not self.db_manager:
                return 0.0
            
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get 24h transaction volume
                cursor.execute("""
                    SELECT SUM(ABS(amount)) FROM transactions
                    WHERE wallet_address = ? AND block_time > ?
                """, (wallet_address, get_current_timestamp() - 86400))
                
                result = cursor.fetchone()
                volume = float(result[0]) if result[0] else 0.0
                
                # Bonus based on volume tiers
                if volume > 100:  # SOL
                    return 2.5
                elif volume > 10:
                    return 1.5
                elif volume > 1:
                    return 0.5
                    
        except Exception as e:
            logger.error(f"❌ Error calculating volume bonus: {e}")
        
        return 0.0
    
    def _calculate_recency_bonus(self, priority: WalletPriority) -> float:
        """Calculate recency bonus"""
        now = get_current_timestamp()
        hours_since_scan = safe_divide(now - priority.last_scan_time, 3600)
        
        # Bonus for long time since last scan
        if hours_since_scan > 6:
            return min(2.0, hours_since_scan / 12.0)
        
        return 0.0
    
    def _calculate_discovery_bonus(self, wallet_address: str) -> float:
        """Calculate discovery bonus"""
        try:
            if not self.db_manager:
                return 0.0
            
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Count recent discoveries
                cursor.execute("""
                    SELECT COUNT(*) FROM token_discoveries
                    WHERE wallet_address = ? AND discovered_at > ?
                """, (wallet_address, get_current_timestamp() - 86400))
                
                result = cursor.fetchone()
                discoveries = int(result[0]) if result[0] else 0
                
                # Bonus based on discoveries
                return min(2.0, discoveries * 0.5)
                
        except Exception as e:
            logger.error(f"❌ Error calculating discovery bonus: {e}")
        
        return 0.0
    
    def _calculate_penalty(self, priority: WalletPriority) -> float:
        """Calculate penalties"""
        penalty = 0.0
        
        # Penalty for consecutive empty scans
        if priority.consecutive_empty_scans > 5:
            penalty += min(3.0, priority.consecutive_empty_scans * 0.3)
        
        # Penalty for no activity in long time
        now = get_current_timestamp()
        days_since_activity = safe_divide(now - priority.last_activity_detected, 86400)
        if days_since_activity > 7:
            penalty += min(2.0, days_since_activity / 7.0)
        
        return penalty
    
    def select_next_wallet(self) -> Optional[str]:
        """Select the next wallet to scan based on priority"""
        try:
            available_wallets = []
            
            with self._lock:
                # Calculate scores for all wallets
                for wallet_address in self._wallet_priorities:
                    score = self.calculate_priority_score(wallet_address)
                    available_wallets.append((score.final_score, wallet_address))
            
            if not available_wallets:
                return None
            
            # Sort by priority score (descending)
            available_wallets.sort(key=lambda x: x[0], reverse=True)
            
            # Select highest priority wallet
            selected_wallet = available_wallets[0][1]
            
            logger.debug(f"🎯 Selected wallet {selected_wallet} with score {available_wallets[0][0]}")
            
            return selected_wallet
            
        except Exception as e:
            logger.error(f"❌ Error selecting next wallet: {e}")
            return None
    
    def update_priority(self, wallet_address: str, new_score: float, reason: str = "manual") -> bool:
        """Update wallet priority score"""
        try:
            if not validate_wallet_address(wallet_address):
                return False
            
            new_score = clamp(new_score, self.MIN_PRIORITY, self.MAX_PRIORITY)
            
            with self._lock:
                if wallet_address not in self._wallet_priorities:
                    return False
                
                priority = self._wallet_priorities[wallet_address]
                old_score = priority.priority_score
                
                # Update score
                priority.priority_score = new_score
                priority.updated_at = get_current_timestamp()
                
                # Add to history
                priority.priority_history.append({
                    'score': new_score,
                    'reason': reason,
                    'timestamp': get_current_timestamp()
                })
                
                # Trim history to last 50 entries
                if len(priority.priority_history) > 50:
                    priority.priority_history = priority.priority_history[-50:]
            
            # Save to database
            self._save_priority(priority)
            
            logger.info(f"🔄 Updated priority for {wallet_address}: {old_score:.2f} → {new_score:.2f} ({reason})")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error updating priority for {wallet_address}: {e}")
            return False
    
    def increment_scan_count(self, wallet_address: str, duration: float, discoveries: int = 0) -> bool:
        """Increment scan count and update metrics"""
        try:
            with self._lock:
                if wallet_address not in self._wallet_priorities:
                    return False
                
                priority = self._wallet_priorities[wallet_address]
                now = get_current_timestamp()
                
                # Update counts
                priority.total_scans += 1
                priority.scan_count_1h += 1
                priority.scan_count_24h += 1
                priority.last_scan_time = now
                
                # Update duration
                if priority.total_scans == 1:
                    priority.avg_scan_duration = duration
                else:
                    priority.avg_scan_duration = (
                        (priority.avg_scan_duration * (priority.total_scans - 1) + duration) /
                        priority.total_scans
                    )
                
                # Update discovery bonus
                if discoveries > 0:
                    priority.new_tokens_score_1h = min(10.0, priority.new_tokens_score_1h + discoveries * 0.2)
                
                # Reset consecutive empty scans if discoveries
                if discoveries > 0:
                    priority.consecutive_empty_scans = 0
                else:
                    priority.consecutive_empty_scans += 1
                
                priority.updated_at = now
            
            # Save to database
            self._save_priority(priority)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error incrementing scan count: {e}")
            return False
    
    def _save_priority(self, priority: WalletPriority) -> bool:
        """Save priority to database"""
        if not self.db_manager:
            return True  # Memory storage
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO wallet_priorities 
                    (wallet_address, priority_score, last_scan_time, scan_count_1h, 
                     scan_count_24h, activity_score, volume_score_1h, new_tokens_score_1h,
                     total_scans, avg_scan_duration, last_activity_detected, 
                     consecutive_empty_scans, priority_history, updated_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    priority.wallet_address,
                    priority.priority_score,
                    priority.last_scan_time,
                    priority.scan_count_1h,
                    priority.scan_count_24h,
                    priority.activity_score,
                    priority.volume_score_1h,
                    priority.new_tokens_score_1h,
                    priority.total_scans,
                    priority.avg_scan_duration,
                    priority.last_activity_detected,
                    priority.consecutive_empty_scans,
                    json.dumps(priority.priority_history),
                    priority.updated_at,
                    priority.created_at
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            logger.error(f"❌ Error saving priority: {e}")
            return False
    
    def get_wallet_priorities(self) -> Dict[str, WalletPriority]:
        """Get all wallet priorities"""
        with self._lock:
            return dict(self._wallet_priorities)
    
    def get_priority_scores(self) -> Dict[str, PriorityScore]:
        """Get current priority scores for all wallets"""
        scores = {}
        with self._lock:
            for wallet_address in self._wallet_priorities:
                scores[wallet_address] = self.calculate_priority_score(wallet_address)
        return scores
    
    def get_priority_ranking(self, limit: Optional[int] = None) -> List[Tuple[float, str]]:
        """Get wallet priority ranking"""
        scores = []
        
        with self._lock:
            for wallet_address in self._wallet_priorities:
                score = self.calculate_priority_score(wallet_address)
                scores.append((score.final_score, wallet_address))
        
        # Sort by priority score (descending)
        scores.sort(key=lambda x: x[0], reverse=True)
        
        if limit:
            scores = scores[:limit]
        
        return scores
    
    def reset_priorities(self, reason: str = "system_reset") -> bool:
        """Reset all wallet priorities to default"""
        try:
            with self._lock:
                for wallet_address, priority in self._wallet_priorities.items():
                    old_score = priority.priority_score
                    priority.priority_score = self.DEFAULT_PRIORITY
                    priority.priority_history.append({
                        'score': self.DEFAULT_PRIORITY,
                        'reason': reason,
                        'timestamp': get_current_timestamp()
                    })
                    
                    self._save_priority(priority)
                    
                    logger.info(f"🔄 Reset priority for {wallet_address}: {old_score:.2f} → {self.DEFAULT_PRIORITY}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error resetting priorities: {e}")
            return False
    
    def reset_wallet_priority(self, wallet_address: str, reason: str = "manual_reset") -> bool:
        """Reset priority for specific wallet"""
        return self.update_priority(wallet_address, self.DEFAULT_PRIORITY, reason)
    
    def get_priority_statistics(self) -> Dict[str, Any]:
        """Get comprehensive priority statistics"""
        try:
            with self._lock:
                priorities = list(self._wallet_priorities.values())
            
            if not priorities:
                return {'error': 'No wallets configured'}
            
            scores = [p.priority_score for p in priorities]
            
            return {
                'total_wallets': len(priorities),
                'priority_distribution': {
                    'critical': sum(1 for s in scores if s >= 8.0),
                    'high': sum(1 for s in scores if 6.0 <= s < 8.0),
                    'medium': sum(1 for s in scores if 3.0 <= s < 6.0),
                    'low': sum(1 for s in scores if 1.0 <= s < 3.0),
                    'very_low': sum(1 for s in scores if s < 1.0)
                },
                'statistics': {
                    'min': min(scores),
                    'max': max(scores),
                    'avg': safe_divide(sum(scores), len(scores)),
                    'median': sorted(scores)[len(scores)//2] if scores else 0
                },
                'last_update': get_current_timestamp()
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting priority statistics: {e}")
            return {'error': str(e)}
    
    def cleanup_old_data(self, days: int = 30) -> int:
        """Clean up old priority data"""
        if not self.db_manager:
            return 0
        
        try:
            cutoff_time = get_current_timestamp() - (days * 86400)
            
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Clean old wallet priorities (if needed)
                cursor.execute("""
                    DELETE FROM wallet_priorities 
                    WHERE last_scan_time < ? AND total_scans = 0
                """, (cutoff_time,))
                
                deleted_count = cursor.rowcount
                conn.commit()
                
                logger.info(f"🧹 Cleaned up {deleted_count} old priority records")
                return deleted_count
                
        except Exception as e:
            logger.error(f"❌ Error cleaning old priority data: {e}")
            return 0

# Singleton instance
_priority_manager = None

def get_priority_manager() -> WalletPriorityManager:
    """Get global priority manager instance"""
    global _priority_manager
    
    if _priority_manager is None:
        _priority_manager = WalletPriorityManager()
    
    return _priority_manager

# Convenience functions
def calculate_priority(wallet_address: str) -> PriorityScore:
    """Calculate priority for a wallet"""
    return get_priority_manager().calculate_priority_score(wallet_address)

def get_next_priority_wallet() -> Optional[str]:
    """Get next wallet to scan based on priority"""
    return get_priority_manager().select_next_wallet()

def update_wallet_priority(wallet_address: str, new_priority: float, reason: str = "manual") -> bool:
    """Update priority for a wallet"""
    return get_priority_manager().update_priority(wallet_address, new_priority, reason)

# Development testing
if __name__ == "__main__":
    logger.info("🧪 Testing Wallet Priority Manager...")
    
    # Create test instance
    manager = get_priority_manager()
    
    # Test wallets
    test_wallets = [
        "4DdrfGHGdMjCqVbNtXsEEGL1SryTeMo8KMGWWtZyZVFh",
        "5GhK...fJd8",
        "6JkL...mN9"
    ]
    
    # Add wallets
    for wallet in test_wallets:
        manager.add_wallet(wallet)
    
    # Calculate priorities
    for wallet in test_wallets:
        score = manager.calculate_priority_score(wallet)
        logger.info(f"📊 Priority for {wallet}: {score.final_score:.2f} ({score.priority_category})")
    
    # Get ranking
    ranking = manager.get_priority_ranking()
    logger.info(f"🏆 Priority ranking: {ranking}")
    
    # Get statistics
    stats = manager.get_priority_statistics()
    logger.info(f"📊 Priority statistics: {stats}")
    
    logger.info("✅ Priority manager test completed")



__all__ = [
    'WalletPriorityManager',
    'PriorityScore',
    'get_priority_manager',
    'calculate_priority',
    'get_next_priority_wallet',
    'update_wallet_priority'
]