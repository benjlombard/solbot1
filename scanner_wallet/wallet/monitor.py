
"""
Solana Wallet Monitor - Main Orchestrator Module
Coordinates all monitoring activities across wallets, tokens, and transactions
"""

import time
import threading
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
import queue
import signal
import sys

# Core imports with fallbacks
try:
    from core.logger import get_logger, get_default_logger
    from core.database import get_database_manager
    from core.config import get_config
    from core.exceptions import MonitoringError, CriticalSystemError
    
    from wallet.priority_manager import WalletPriorityManager
    from wallet.scanner import WalletScanner
    from wallet.balance_tracker import BalanceTracker, BalanceChange
    
    from models.wallet import WalletPriority, WalletStats
    from models.token import Token, TokenAccount, TokenDiscovery
    from models.transaction import Transaction, TransactionType, TransactionStatus
    
    from utils.helpers import get_current_timestamp, safe_divide
    from utils.validators import quick_validate_address as validate_wallet_address
    
except ImportError as e:
    # Fallback implementations for development
    import logging
    logging.warning(f"A core module import failed in monitor.py: {e}. Using fallback implementations.")
    def get_logger(name=None):
        logger = logging.getLogger(name or 'monitor')
        logger.setLevel(logging.INFO)
        return logger
    
    def get_database_manager(): return None
    def get_config(): 
        class MockConfig:
            class monitoring:
                update_interval = 45
        return MockConfig()
    
    def get_current_timestamp():
        import time
        return int(time.time())

    def safe_divide(a, b):
        return a / b if b != 0 else 0

    def validate_wallet_address(addr):
        return isinstance(addr, str) and len(addr) >= 32

    class BalanceChange:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
            self.is_significant = True  # Default

    class WalletPriorityManager:
        def __init__(self): 
            self.wallets = []
            self.current_index = 0
    
        def select_next_wallet(self): 
            if not self.wallets:
                return None
            # Simple round-robin
            wallet = self.wallets[self.current_index % len(self.wallets)]
            self.current_index += 1
            return wallet
        
        def add_wallet(self, wallet):
            if wallet not in self.wallets:
                self.wallets.append(wallet)
        
        def update_priority(self, wallet, score): 
            pass
    
    class WalletScanner:
        def __init__(self): pass
        def scan_wallet(self, wallet):
            return {
                'new_accounts': [],
                'transactions': [],
                'all_accounts': [],
                'duration': 1.0
            }  
    
    class BalanceTracker:
        def __init__(self): pass
        def track_wallet(self, wallet): return True

# Logger
logger = get_logger(__name__)

@dataclass
class ScanResult:
    """Result of a single wallet scan"""
    wallet_address: str
    cycle_id: str
    scan_duration: float
    new_accounts_found: int = 0
    total_accounts: int = 0
    transactions_detected: int = 0
    success: bool = True
    error_message: Optional[str] = None
    timestamp: int = field(default_factory=get_current_timestamp)

@dataclass
class MonitorStats:
    """Real-time monitoring statistics"""
    total_cycles: int = 0
    total_scans: int = 0
    successful_scans: int = 0
    failed_scans: int = 0
    total_wallets: int = 0
    active_wallets: int = 0
    total_discoveries: int = 0
    total_transactions: int = 0
    avg_cycle_duration: float = 0.0
    last_cycle_time: int = 0
    uptime_seconds: int = 0
    start_time: int = field(default_factory=get_current_timestamp)

class SolanaWalletMonitor:
    """
    Main orchestrator for Solana wallet monitoring
    Coordinates scanning, priority management, balance tracking, and transaction analysis
    """
    
    def __init__(self, wallet_addresses: Optional[List[str]] = None):
        # Core components
        try:
            self.config = get_config()
            logger.info(f"✅ Config loaded: {type(self.config)}")
        except Exception as e:
            logger.error(f"❌ Error loading config: {e}")
            self.config = None
        self.db_manager = get_database_manager()
        self.logger = get_default_logger()
        
        # Subsystems
        self.priority_manager = WalletPriorityManager()
        self.scanner = WalletScanner()
        self.balance_tracker = BalanceTracker()
        
        # Thread-safe operations
        self._lock = threading.Lock()
        self._running = False
        self._shutdown_event = threading.Event()
        self._monitor_thread = None
        self._stats_thread = None
        
        # Data structures
        self.wallets: Set[str] = set()
        self.stats = MonitorStats()
        self.scan_queue: queue.Queue = queue.Queue()
        self.results_queue: queue.Queue = queue.Queue()
        
        # Initialize wallets
        if wallet_addresses:
            self.add_wallets(wallet_addresses)
        
        # Signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        logger.info("🧠 Solana Wallet Monitor initialized")
    
    def add_wallets(self, wallet_addresses: List[str]) -> Dict[str, bool]:
        """Add wallets to monitoring"""
        results = {}
        
        for address in wallet_addresses:
            try:
                if not validate_wallet_address(address):
                    logger.warning(f"❌ Invalid wallet address: {address}")
                    results[address] = False
                    continue
                
                with self._lock:
                    if address not in self.wallets:
                        self.wallets.add(address)
                        self.balance_tracker.track_wallet(address)
                        logger.debug(f"🔧 Adding {address} to priority manager")
                        self.priority_manager.add_wallet(address)
                        logger.info(f"✅ Added wallet: {address}")
                
                results[address] = True
                
            except Exception as e:
                logger.error(f"❌ Error adding wallet {address}: {e}")
                results[address] = False
        
        with self._lock:
            self.stats.total_wallets = len(self.wallets)
            self.stats.active_wallets = len(self.wallets)
        
        return results
    
    def remove_wallets(self, wallet_addresses: List[str]) -> Dict[str, bool]:
        """Remove wallets from monitoring"""
        results = {}
        
        for address in wallet_addresses:
            try:
                with self._lock:
                    if address in self.wallets:
                        self.wallets.discard(address)
                        logger.info(f"✅ Removed wallet: {address}")
                        results[address] = True
                    else:
                        results[address] = False
                
            except Exception as e:
                logger.error(f"❌ Error removing wallet {address}: {e}")
                results[address] = False
        
        with self._lock:
            self.stats.total_wallets = len(self.wallets)
            self.stats.active_wallets = len(self.wallets)
        
        return results
    
    def start_monitoring(self) -> bool:
        """Start the monitoring system"""
        try:
            with self._lock:
                if self._running:
                    logger.warning("⚠️ Monitoring already running")
                    return False
                
                if not self.wallets:
                    logger.warning("⚠️ No wallets to monitor")
                    return False
                
                self._running = True
                self._shutdown_event.clear()
                self.stats.start_time = get_current_timestamp()
            
            # Start monitoring thread
            self._monitor_thread = threading.Thread(
                target=self._monitoring_loop,
                name="WalletMonitor",
                daemon=True
            )
            self._monitor_thread.start()
            
            # Start stats thread
            self._stats_thread = threading.Thread(
                target=self._stats_loop,
                name="StatsUpdater",
                daemon=True
            )
            self._stats_thread.start()
            
            logger.info("🚀 Wallet monitoring started")
            logger.info(f"📊 Monitoring {len(self.wallets)} wallets")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error starting monitoring: {e}")
            self._running = False
            return False
    
    def stop_monitoring(self) -> bool:
        """Stop the monitoring system"""
        try:
            with self._lock:
                if not self._running:
                    logger.warning("⚠️ Monitoring not running")
                    return False
                
                self._running = False
                self._shutdown_event.set()
            
            # Wait for threads to finish
            if self._monitor_thread and self._monitor_thread.is_alive():
                self._monitor_thread.join(timeout=5.0)
            
            if self._stats_thread and self._stats_thread.is_alive():
                self._stats_thread.join(timeout=2.0)
            
            logger.info("🛑 Wallet monitoring stopped")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error stopping monitoring: {e}")
            return False
    
    def _monitoring_loop(self):
        """Main monitoring loop running in background thread"""
        logger.info("🔄 Starting monitoring loop")
        
        while self._running and not self._shutdown_event.is_set():
            try:
                cycle_start = get_current_timestamp()
                cycle_id = f"cycle_{cycle_start}"
                
                logger.info(f"🔄 Starting cycle {cycle_id}")
                debug_scanner_status(self)
                # Select next wallet based on priority
                try:
                    selected_wallet = self.priority_manager.select_next_wallet()
                    logger.info(f"🎯 Selected wallet for scan: {selected_wallet}")
                except Exception as e:
                    logger.error(f"❌ Error selecting wallet: {e}")
                    selected_wallet = None

                if not selected_wallet:
                    logger.warning(f"⚠️ Priority manager returned None. Available wallets: {list(self.wallets)[:5]}")  # Show first 5
                    # Fallback: select first wallet
                    if self.wallets:
                        selected_wallet = list(self.wallets)[0]
                        logger.info(f"🔄 Using fallback wallet: {selected_wallet}")
                
                if selected_wallet and selected_wallet in self.wallets:
                    logger.info(f"✅ Wallet {selected_wallet} is valid, starting scan...")
                    
                    # Perform wallet scan
                    try:
                        scan_result = self._scan_wallet(selected_wallet, cycle_id)
                        
                        if scan_result:
                            logger.info(f"📊 Scan result: Success={scan_result.success}, New accounts={scan_result.new_accounts_found}, Transactions={scan_result.transactions_detected}")
                        else:
                            logger.warning(f"⚠️ Scan result is None for {selected_wallet}")
                    except Exception as e:
                        logger.error(f"❌ Error during wallet scan: {e}")
                        scan_result = None
                    
                    # Update priority and track changes...
                    self._update_cycle_stats(cycle_start, scan_result)
                else:
                    logger.warning(f"⚠️ No valid wallet selected or wallet not in list. Selected: {selected_wallet}, Wallets count: {len(self.wallets)}")
                    scan_result = None
                    # Update stats even for failed cycles
                    self._update_cycle_stats(cycle_start, None)
                
                # Log cycle completion with detailed info
                duration = get_current_timestamp() - cycle_start
                discoveries = scan_result.new_accounts_found if scan_result else 0
                transactions = scan_result.transactions_detected if scan_result else 0
                logger.info(f"✅ Cycle {cycle_id} completed - Duration: {duration:.2f}s, Discoveries: {discoveries}, Transactions: {transactions}")
                # Get sleep interval safely
                try:
                    sleep_interval = self.config.monitoring.update_interval if self.config else 45
                except:
                    sleep_interval = 45
                # Sleep with countdown log
                logger.debug(f"😴 Sleeping for {self.config.monitoring.update_interval} seconds until next cycle...")
                time.sleep(self.config.monitoring.update_interval)
                
            except Exception as e:
                logger.error(f"❌ Monitoring loop error: {e}", exc_info=True)  # exc_info=True pour la stack trace
                self.stats.failed_scans += 1
                time.sleep(5)
    
    def _scan_wallet(self, wallet_address: str, cycle_id: str) -> ScanResult:
        """Scan a single wallet for changes"""
        scan_start = time.time()
        
        try:
            # Perform actual scan
            scan_data = self.scanner.scan_wallet(wallet_address)
            if scan_data is None:
                scan_data = {
                    'new_accounts': [],
                    'transactions': [],
                    'all_accounts': [],
                    'duration': 0.0
                }
            
            # Process results
            new_accounts = scan_data.get('new_accounts', [])
            transactions = scan_data.get('transactions', [])
            
            # Store results
            if self.db_manager:
                self._store_scan_results(wallet_address, cycle_id, scan_data)
            
            scan_duration = time.time() - scan_start
            
            result = ScanResult(
                wallet_address=wallet_address,
                cycle_id=cycle_id,
                scan_duration=scan_duration,
                new_accounts_found=len(new_accounts),
                total_accounts=len(scan_data.get('all_accounts', [])),
                transactions_detected=len(transactions),
                success=True
            )
            
            logger.info(f"✅ Scan completed for {wallet_address}: {len(new_accounts)} new accounts")
            return result
            
        except Exception as e:
            scan_duration = time.time() - scan_start
            
            result = ScanResult(
                wallet_address=wallet_address,
                cycle_id=cycle_id,
                scan_duration=scan_duration,
                success=False,
                error_message=str(e)
            )
            
            logger.error(f"❌ Scan failed for {wallet_address}: {e}")
            return result
    
    def _update_wallet_priority(self, wallet_address: str, scan_result: ScanResult):
        """Update wallet priority based on scan results"""
        try:
            if scan_result.success:
                # Calculate new priority based on activity
                activity_score = scan_result.transactions_detected * 2 + scan_result.new_accounts_found * 5
                new_priority = min(10.0, max(0.1, activity_score / 10.0))
                
                self.priority_manager.update_priority(wallet_address, new_priority)
                
        except Exception as e:
            logger.error(f"❌ Error updating priority for {wallet_address}: {e}")
    
    def _track_balance_changes(self, wallet_address: str, scan_result: ScanResult):
        """Track balance changes for a wallet"""
        try:
            changes = self.balance_tracker.scan_balance_changes(wallet_address)
            
            if changes:
                logger.info(f"💰 {len(changes)} balance changes detected for {wallet_address}")
                
                # Process significant changes
                significant_changes = [c for c in changes if c.is_significant]
                if significant_changes:
                    self._process_significant_changes(significant_changes)
                    
        except Exception as e:
            logger.error(f"❌ Error tracking balance changes for {wallet_address}: {e}")
    
    def _process_significant_changes(self, changes: List[BalanceChange]):
        """Process significant balance changes"""
        for change in changes:
            try:
                # Create transaction record
                transaction = Transaction(
                    signature=f"balance_change_{change.timestamp}",  # Synthetic signature
                    wallet_address=change.wallet_address,
                    slot=0,  # Placeholder
                    amount=float(change.display_change),
                    token_amount=float(change.display_change),
                    token_mint=change.token_mint,
                    token_symbol=change.token_symbol,
                    transaction_type=TransactionType.TRANSFER,
                    status=TransactionStatus.SUCCESS,
                    source="balance_tracker"
                )
                
                # Log significant changes
                if abs(change.display_change) > 1000:  # Large transaction threshold
                    # self.logger.log_large_transaction(
                    #     change.wallet_address,
                    #     "balance_change",
                    #     float(change.display_change),
                    #     change.token_symbol
                    # )
                    logger.warning(f"💰 Large transaction: {float(change.display_change)} {change.token_symbol} for {change.wallet_address}")
                
            except Exception as e:
                logger.error(f"❌ Error processing significant change: {e}")
    
    def _store_scan_results(self, wallet_address: str, cycle_id: str, scan_data: Dict):
        """Store scan results in database"""
        if not self.db_manager:
            return
            
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Store scan history
                cursor.execute("""
                    INSERT INTO scan_history 
                    (wallet_address, cycle_id, scan_type, total_accounts, 
                     new_accounts, scan_duration, completed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    wallet_address, cycle_id, "full_scan",
                    len(scan_data.get('all_accounts', [])),
                    len(scan_data.get('new_accounts', [])),
                    scan_data.get('duration', 0),
                    get_current_timestamp()
                ))
                
                # Store token discoveries
                for account in scan_data.get('new_accounts', []):
                    cursor.execute("""
                        INSERT INTO token_discoveries 
                        (token_mint, wallet_address, discovered_at, initial_balance, decimals)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        account.get('mint'),
                        wallet_address,
                        get_current_timestamp(),
                        account.get('balance', 0),
                        account.get('decimals', 9)
                    ))
                
                conn.commit()
                
        except Exception as e:
            logger.error(f"❌ Error storing scan results: {e}")
    
    def _update_cycle_stats(self, cycle_start: int, scan_result: Optional[ScanResult]):
        """Update monitoring statistics"""
        with self._lock:
            self.stats.total_cycles += 1
            
            if scan_result:
                self.stats.total_scans += 1
                if scan_result.success:
                    self.stats.successful_scans += 1
                    self.stats.total_discoveries += scan_result.new_accounts_found
                    self.stats.total_transactions += scan_result.transactions_detected
                else:
                    self.stats.failed_scans += 1
            
            # Update averages
            if self.stats.total_cycles > 0:
                self.stats.avg_cycle_duration = safe_divide(
                    get_current_timestamp() - self.stats.last_cycle_time,
                    self.stats.total_cycles
                )
            
            self.stats.last_cycle_time = get_current_timestamp()
            self.stats.uptime_seconds = get_current_timestamp() - self.stats.start_time
    
    def _stats_loop(self):
        """Background thread for periodic stats updates"""
        logger.info("📊 Starting stats updater")
        
        while self._running and not self._shutdown_event.is_set():
            try:
                # Update wallet statistics
                self._update_wallet_statistics()
                
                # Log periodic summary
                self._log_periodic_summary()
                
                # Sleep for stats update interval
                time.sleep(60)  # Update every minute
                
            except Exception as e:
                logger.error(f"❌ Stats loop error: {e}")
                time.sleep(30)
    
    def _update_wallet_statistics(self):
        """Update wallet-level statistics"""
        if not self.db_manager:
            return
            
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Update wallet stats
                for wallet in self.wallets:
                    # First, get the transaction count for the wallet
                    cursor.execute(
                        "SELECT COUNT(*) FROM transactions WHERE wallet_address = ?",
                        (wallet,)
                    )
                    tx_count = cursor.fetchone()[0]
                    
                    # Now, insert or replace the stats using the known wallet address
                    cursor.execute("""
                        INSERT OR REPLACE INTO wallet_stats 
                        (wallet_address, total_transactions, updated_at)
                        VALUES (?, ?, ?)
                    """, (wallet, tx_count, get_current_timestamp()))
                
                conn.commit()
                
        except Exception as e:
            logger.error(f"❌ Error updating wallet statistics: {e}")
    
    def _log_periodic_summary(self):
        """Log periodic summary of monitoring activity"""
        with self._lock:
            stats_copy = self.stats
        
        logger.info(f"""
        📊 Monitoring Summary:
        - Uptime: {stats_copy.uptime_seconds/3600:.1f}h
        - Wallets: {stats_copy.total_wallets} total, {stats_copy.active_wallets} active
        - Cycles: {stats_copy.total_cycles} total, {stats_copy.successful_scans} successful
        - Discoveries: {stats_copy.total_discoveries} new accounts
        - Transactions: {stats_copy.total_transactions} detected
        - Success Rate: {safe_divide(stats_copy.successful_scans, stats_copy.total_scans)*100:.1f}%
        """)
    
    def get_system_status(self) -> Dict[str, any]:
        """Get comprehensive system status"""
        with self._lock:
            status = {
                'monitoring_active': self._running,
                'wallets_count': len(self.wallets),
                'statistics': self.stats.__dict__,
                'components': {
                    'priority_manager': 'active',
                    'scanner': 'active',
                    'balance_tracker': 'active'
                }
            }
        
        return status
    
    def get_detailed_stats(self) -> Dict[str, any]:
        """Get detailed monitoring statistics"""
        with self._lock:
            stats = self.stats
            
            return {
                'system_stats': stats.__dict__,
                'wallets': list(self.wallets),
                'performance': {
                    'scans_per_hour': safe_divide(stats.total_scans, stats.uptime_seconds/3600),
                    'discoveries_per_scan': safe_divide(stats.total_discoveries, max(stats.total_scans, 1)),
                    'success_rate': safe_divide(stats.successful_scans, max(stats.total_scans, 1)),
                    'avg_cycle_duration': stats.avg_cycle_duration
                }
            }
    
    def health_check(self) -> Dict[str, any]:
        """Perform comprehensive health check"""
        checks = {
            'monitoring_active': self._running,
            'wallets_configured': len(self.wallets) > 0,
            'components_initialized': all([
                self.priority_manager is not None,
                self.scanner is not None,
                self.balance_tracker is not None
            ]),
            'threads_alive': {
                'monitor': self._monitor_thread and self._monitor_thread.is_alive(),
                'stats': self._stats_thread and self._stats_thread.is_alive()
            },
            'uptime_hours': safe_divide(get_current_timestamp() - self.stats.start_time, 3600)
        }
        
        overall_health = all(checks.values())
        checks['overall_health'] = overall_health
        
        return checks
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        logger.info(f"🛑 Received signal {signum}, shutting down...")
        self.stop_monitoring()
        sys.exit(0)

# Factory functions for easy initialization
def create_monitor(wallet_addresses: Optional[List[str]] = None) -> SolanaWalletMonitor:
    """Create a new monitor instance"""
    return SolanaWalletMonitor(wallet_addresses)

def get_default_monitor() -> SolanaWalletMonitor:
    """Get singleton default monitor instance"""
    global _default_monitor
    if '_default_monitor' not in globals():
        _default_monitor = SolanaWalletMonitor()
    return _default_monitor

# Global instance
_default_monitor = None

# Convenience functions
def start_monitoring(wallets: List[str] = None) -> bool:
    """Start monitoring with default instance"""
    monitor = get_default_monitor()
    if wallets:
        monitor.add_wallets(wallets)
    return monitor.start_monitoring()

def stop_monitoring() -> bool:
    """Stop default monitoring"""
    return get_default_monitor().stop_monitoring()


def debug_scanner_status(self):
    """Debug scanner state"""
    scanner_status = self.scanner.get_scan_status()
    logger.info(f"Scanner status: {scanner_status}")
    
    priority_status = self.priority_manager.get_priority_statistics()
    logger.info(f"Priority status: {priority_status}")
    
    logger.info(f"Active scans: {len(self.scanner._active_scans)}")
    logger.info(f"Cache size: {len(self.scanner._scan_cache)}")

def get_status() -> Dict[str, any]:
    """Get status of default monitor"""
    return get_default_monitor().get_system_status()

if __name__ == "__main__":
    # Development testing
    logger.info("🧪 Testing Solana Wallet Monitor...")
    
    # Create test monitor
    monitor = create_monitor()
    
    # Test with sample wallet
    test_wallets = [
        "4DdrfGHGdMjCqVbNtXsEEGL1SryTeMo8KMGWWtZyZVFh",
        "5GhK...fJd8"
    ]
    
    monitor.add_wallets(test_wallets)
    
    # Start monitoring (in test mode)
    logger.info("📊 Starting test monitoring...")
    monitor.start_monitoring()
    
    # Let it run briefly
    time.sleep(2)
    
    # Get status
    status = monitor.get_system_status()
    logger.info(f"📊 Status: {status}")
    
    # Stop monitoring
    monitor.stop_monitoring()
    
    logger.info("✅ Monitor test completed")


__all__ = ['SolanaWalletMonitor', 'create_monitor', 'get_default_monitor']