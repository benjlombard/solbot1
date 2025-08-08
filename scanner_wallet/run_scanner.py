#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Launcher script for the Solana Wallet Monitor background service.
"""

import time
import sys
import os
import signal

# Add project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def main():
    """
    Initializes and runs the Solana Wallet Monitor.
    """
    # It's crucial to import these after setting the path
    from core.logger import get_logger, setup_logger
    from core.config import get_config
    from core.database import get_database_manager
    from wallet.monitor import SolanaWalletMonitor

    # Setup logger
    setup_logger()
    logger = get_logger(__name__)

    logger.info("🚀 Starting Solana Wallet Monitor Service...")

    # Load configuration and database
    try:
        config = get_config()
        db_manager = get_database_manager()
        logger.info("✅ Configuration and database loaded successfully.")
    except Exception as e:
        logger.error(f"❌ Critical error during initialization: {e}")
        sys.exit(1)

    # Get wallet addresses from config
    wallet_addresses = getattr(getattr(config, 'wallet', {}), 'addresses', [])
    if not wallet_addresses:
        logger.warning("⚠️ No wallet addresses found in the configuration. The monitor will start with an empty set.")
        logger.warning("Please run `python scanner_wallet/init_wallets.py` or add wallets to your config.")
        return

    # Create and start the monitor
    monitor = SolanaWalletMonitor(wallet_addresses=wallet_addresses)
    
    # Graceful shutdown handler
    def shutdown_handler(signum, frame):
        logger.info("🛑 Shutdown signal received. Stopping monitor gracefully...")
        monitor.stop_monitoring()
        logger.info("✅ Monitor stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)
    
    # Start monitoring (this creates the background threads)
    if not monitor.start_monitoring():
        logger.error("❌ Failed to start monitoring")
        sys.exit(1)

    logger.info(f"✅ Solana Wallet Monitor is now running for {len(wallet_addresses)} wallet(s).")
    logger.info("Press Ctrl+C to stop the service.")

    try:
        # Main thread just waits - all work is done in background threads
        while monitor._running:
            time.sleep(10)  # Check every 10 seconds if still running
            
            # Optional: Log a brief status every 5 minutes
            if int(time.time()) % 300 == 0:  # Every 5 minutes
                status = monitor.get_system_status()
                logger.debug(f"🔍 Monitor active: {status['monitoring_active']}")
                
    except KeyboardInterrupt:
        logger.info("🛑 Keyboard interrupt received")
        shutdown_handler(signal.SIGINT, None)
    except Exception as e:
        logger.error(f"❌ Unexpected error in main loop: {e}")
        monitor.stop_monitoring()
        sys.exit(1)

if __name__ == "__main__":
    main()