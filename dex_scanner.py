"""
DEX Listings Scanner for Solana
File: dex_scanner.py

Real-time scanner for new token listings on Solana DEXs.
Inspired by https://github.com/0xCaso/dex-listings-scanner-bot but adapted for Solana.

Features:
- Real-time monitoring of new pairs on Raydium, Orca, Meteora
- WebSocket connections for instant notifications
- Duplicate filtering with database tracking
- Integration with existing bot architecture
- Smart filtering based on liquidity, volume, and safety
"""

import asyncio
import websockets
import json
import logging
import time
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
import threading
from collections import defaultdict, deque

# Imports depuis votre bot existant
from database import DatabaseManager, TokenRecord, TokenStatus
from rugcheck import RugCheckAnalyzer

class DEXProtocol(Enum):
    """Supported DEX protocols on Solana"""
    RAYDIUM = "raydium"
    ORCA = "orca"
    METEORA = "meteora"
    PHOENIX = "phoenix"
    OPENBOOK = "openbook"
    JUPITER = "jupiter"

@dataclass
class DEXConfig:
    """Configuration for a specific DEX"""
    name: str
    protocol: DEXProtocol
    program_id: str
    factory_address: Optional[str] = None
    websocket_url: Optional[str] = None
    api_endpoint: Optional[str] = None
    enabled: bool = True

@dataclass
class NewPairEvent:
    """Event data for a newly created trading pair"""
    dex: DEXProtocol
    pair_address: str
    base_token: str
    quote_token: str
    base_symbol: str
    quote_symbol: str
    liquidity_sol: float
    initial_price: Optional[float]
    block_time: int
    signature: str
    raw_data: Dict
    
    # Computed fields
    age_seconds: float = field(default=0)
    is_sol_pair: bool = field(default=False)
    
    def __post_init__(self):
        """Calculate derived fields"""
        self.age_seconds = time.time() - self.block_time
        self.is_sol_pair = (
            self.quote_token == "So11111111111111111111111111111111111111112" or
            self.base_token == "So11111111111111111111111111111111111111112"
        )

class DEXListingsScanner:
    """
    Real-time scanner for new DEX listings on Solana
    
    This scanner monitors multiple DEXs simultaneously and provides
    real-time notifications of new trading pairs with intelligent filtering.
    """
    
    # Solana DEX configurations
    DEX_CONFIGS = {
        DEXProtocol.RAYDIUM: DEXConfig(
            name="Raydium",
            protocol=DEXProtocol.RAYDIUM,
            program_id="675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
            api_endpoint="https://api.raydium.io/v2/main/pairs"
        ),
        DEXProtocol.ORCA: DEXConfig(
            name="Orca",
            protocol=DEXProtocol.ORCA,
            program_id="whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
            api_endpoint="https://api.orca.so/v1/whirlpool/list"
        ),
        DEXProtocol.METEORA: DEXConfig(
            name="Meteora",
            protocol=DEXProtocol.METEORA,
            program_id="Eo7WjKq67rjJQSZxS6z3YkapzY3eMj6Xy8X5EQVn5UaB"
        )
    }
    
    def __init__(self, config: Dict, database_manager: DatabaseManager, 
                 rugcheck_analyzer: RugCheckAnalyzer, logger=None):
        """Initialize the DEX listings scanner"""
        self.config = config
        self.db = database_manager
        self.rugcheck = rugcheck_analyzer
        self.logger = logger or logging.getLogger(__name__)
        
        # Scanner state
        self.is_running = False
        self.websocket_connections = {}
        self.seen_pairs = set()
        self.recent_pairs = deque(maxlen=1000)  # Cache des 1000 dernières paires
        
        # Event callbacks
        self.new_pair_callbacks: List[Callable] = []
        
        # Rate limiting and filtering
        self.min_liquidity_sol = config.get('scanner', {}).get('min_liquidity_sol', 5.0)
        self.max_age_minutes = config.get('scanner', {}).get('max_age_minutes', 60)
        self.enabled_dexs = config.get('scanner', {}).get('enabled_dexs', [
            DEXProtocol.RAYDIUM.value, DEXProtocol.ORCA.value
        ])
        
        # Performance tracking
        self.stats = {
            'total_pairs_found': 0,
            'filtered_pairs': 0,
            'duplicate_pairs': 0,
            'valid_new_pairs': 0,
            'scanner_uptime': 0,
            'last_pair_time': None
        }
        
        self.logger.info("DEX Listings Scanner initialized")
    
    def add_new_pair_callback(self, callback: Callable[[NewPairEvent], None]):
        """Add callback for new pair events"""
        self.new_pair_callbacks.append(callback)
        self.logger.info(f"Added new pair callback: {callback.__name__}")
    
    async def start_scanning(self):
        """Start real-time scanning of all enabled DEXs"""
        self.logger.info("🚀 Starting DEX Listings Scanner...")
        self.is_running = True
        self.stats['scanner_uptime'] = time.time()
        
        # Start scanner tasks for each enabled DEX
        tasks = []
        
        for dex_protocol in self.enabled_dexs:
            try:
                protocol_enum = DEXProtocol(dex_protocol)
                if protocol_enum in self.DEX_CONFIGS:
                    config = self.DEX_CONFIGS[protocol_enum]
                    if config.enabled:
                        task = asyncio.create_task(
                            self._scan_dex(config), 
                            name=f"scan_{config.name.lower()}"
                        )
                        tasks.append(task)
                        self.logger.info(f"✅ Started scanner for {config.name}")
            except ValueError:
                self.logger.warning(f"⚠️ Unknown DEX protocol: {dex_protocol}")
        
        if not tasks:
            self.logger.error("❌ No valid DEX scanners started")
            return
        
        # Start cleanup task
        cleanup_task = asyncio.create_task(self._cleanup_old_pairs(), name="cleanup")
        tasks.append(cleanup_task)
        
        try:
            # Wait for all scanners to complete (or until stopped)
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            self.logger.error(f"❌ Scanner error: {e}")
        finally:
            self.is_running = False
            self.logger.info("🛑 DEX Listings Scanner stopped")
    
    async def _scan_dex(self, dex_config: DEXConfig):
        """Scan a specific DEX for new pairs"""
        self.logger.info(f"🔍 Starting {dex_config.name} scanner...")
        
        while self.is_running:
            try:
                if dex_config.protocol == DEXProtocol.RAYDIUM:
                    await self._scan_raydium()
                elif dex_config.protocol == DEXProtocol.ORCA:
                    await self._scan_orca()
                elif dex_config.protocol == DEXProtocol.METEORA:
                    await self._scan_meteora()
                
                # Wait before next scan cycle
                await asyncio.sleep(30)  # Scan every 30 seconds
                
            except Exception as e:
                self.logger.error(f"❌ Error scanning {dex_config.name}: {e}")
                await asyncio.sleep(60)  # Wait longer on error
    
    async def _scan_raydium(self):
        """Scan Raydium for new pairs"""
        try:
            response = requests.get(
                "https://api.raydium.io/v2/main/pairs",
                timeout=10
            )
            
            if response.status_code != 200:
                self.logger.warning(f"Raydium API error: {response.status_code}")
                return
            
            data = response.json()
            if not isinstance(data, list):
                return
            
            current_time = time.time()
            new_pairs_found = 0
            
            for pair_data in data:
                try:
                    # Extract pair information
                    pair_address = pair_data.get('ammId')
                    if not pair_address:
                        continue
                    
                    # Check if we've seen this pair before
                    pair_key = f"raydium_{pair_address}"
                    if pair_key in self.seen_pairs:
                        continue
                    
                    # Parse pair data
                    base_mint = pair_data.get('baseMint')
                    quote_mint = pair_data.get('quoteMint')
                    base_symbol = pair_data.get('baseSymbol', 'UNKNOWN')
                    quote_symbol = pair_data.get('quoteSymbol', 'UNKNOWN')
                    liquidity = float(pair_data.get('liquidity', 0))
                    price = float(pair_data.get('price', 0)) if pair_data.get('price') else None
                    
                    # Basic filtering
                    if not base_mint or not quote_mint:
                        continue
                    
                    if liquidity < self.min_liquidity_sol * 1e9:  # Convert to lamports
                        continue
                    
                    # Create new pair event
                    new_pair = NewPairEvent(
                        dex=DEXProtocol.RAYDIUM,
                        pair_address=pair_address,
                        base_token=base_mint,
                        quote_token=quote_mint,
                        base_symbol=base_symbol,
                        quote_symbol=quote_symbol,
                        liquidity_sol=liquidity / 1e9,
                        initial_price=price,
                        block_time=int(current_time),
                        signature=f"raydium_{int(current_time)}_{pair_address[:8]}",
                        raw_data=pair_data
                    )
                    
                    # Process new pair
                    if await self._process_new_pair(new_pair):
                        new_pairs_found += 1
                        self.seen_pairs.add(pair_key)
                
                except Exception as e:
                    self.logger.debug(f"Error processing Raydium pair: {e}")
                    continue
            
            if new_pairs_found > 0:
                self.logger.info(f"🔥 Raydium: Found {new_pairs_found} new pairs")
        
        except Exception as e:
            self.logger.error(f"Error scanning Raydium: {e}")
    
    async def _scan_orca(self):
        """Scan Orca for new pairs"""
        try:
            response = requests.get(
                "https://api.orca.so/v1/whirlpool/list",
                timeout=10
            )
            
            if response.status_code != 200:
                self.logger.warning(f"Orca API error: {response.status_code}")
                return
            
            data = response.json()
            pools = data.get('whirlpools', [])
            
            current_time = time.time()
            new_pairs_found = 0
            
            for pool_data in pools:
                try:
                    pool_address = pool_data.get('address')
                    if not pool_address:
                        continue
                    
                    pair_key = f"orca_{pool_address}"
                    if pair_key in self.seen_pairs:
                        continue
                    
                    token_a = pool_data.get('tokenA', {})
                    token_b = pool_data.get('tokenB', {})
                    
                    base_mint = token_a.get('mint')
                    quote_mint = token_b.get('mint')
                    base_symbol = token_a.get('symbol', 'UNKNOWN')
                    quote_symbol = token_b.get('symbol', 'UNKNOWN')
                    
                    # Estimate liquidity from TVL
                    tvl = float(pool_data.get('tvl', 0))
                    liquidity_sol = tvl / 140 if tvl > 0 else 0  # Rough SOL conversion
                    
                    if not base_mint or not quote_mint:
                        continue
                    
                    if liquidity_sol < self.min_liquidity_sol:
                        continue
                    
                    new_pair = NewPairEvent(
                        dex=DEXProtocol.ORCA,
                        pair_address=pool_address,
                        base_token=base_mint,
                        quote_token=quote_mint,
                        base_symbol=base_symbol,
                        quote_symbol=quote_symbol,
                        liquidity_sol=liquidity_sol,
                        initial_price=float(pool_data.get('price', 0)) if pool_data.get('price') else None,
                        block_time=int(current_time),
                        signature=f"orca_{int(current_time)}_{pool_address[:8]}",
                        raw_data=pool_data
                    )
                    
                    if await self._process_new_pair(new_pair):
                        new_pairs_found += 1
                        self.seen_pairs.add(pair_key)
                
                except Exception as e:
                    self.logger.debug(f"Error processing Orca pool: {e}")
                    continue
            
            if new_pairs_found > 0:
                self.logger.info(f"🌊 Orca: Found {new_pairs_found} new pairs")
        
        except Exception as e:
            self.logger.error(f"Error scanning Orca: {e}")
    
    async def _scan_meteora(self):
        """Scan Meteora for new pairs (placeholder - API endpoint needed)"""
        try:
            # Meteora doesn't have a public API yet, so this is a placeholder
            # You could implement WebSocket connection to Solana RPC to listen for
            # Meteora program logs here
            
            # For now, we'll just log that it's not implemented
            self.logger.debug("Meteora scanning not yet implemented (waiting for public API)")
            
        except Exception as e:
            self.logger.error(f"Error scanning Meteora: {e}")
    
    async def _process_new_pair(self, new_pair: NewPairEvent) -> bool:
        """Process a newly found pair"""
        try:
            # Update stats
            self.stats['total_pairs_found'] += 1
            
            # Check if pair already exists in database
            existing_token = None
            try:
                # Check both base and quote tokens
                for token_address in [new_pair.base_token, new_pair.quote_token]:
                    if token_address != "So11111111111111111111111111111111111111112":  # Skip SOL
                        existing_token = self.db.get_token_by_address(token_address)
                        if existing_token:
                            break
                
                if existing_token:
                    self.stats['duplicate_pairs'] += 1
                    self.logger.debug(f"🔄 Duplicate pair detected: {new_pair.base_symbol}/{new_pair.quote_symbol}")
                    return False
            
            except Exception as e:
                self.logger.debug(f"Database check error: {e}")
            
            # Apply filters
            if not self._apply_filters(new_pair):
                self.stats['filtered_pairs'] += 1
                return False
            
            # Add to recent pairs cache
            self.recent_pairs.append(new_pair)
            self.stats['valid_new_pairs'] += 1
            self.stats['last_pair_time'] = datetime.now()
            
            # Log the discovery
            self.logger.info(
                f"🆕 NEW PAIR: {new_pair.base_symbol}/{new_pair.quote_symbol} "
                f"on {new_pair.dex.value.upper()} - "
                f"Liquidity: {new_pair.liquidity_sol:.2f} SOL"
            )
            
            # Notify callbacks
            for callback in self.new_pair_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(new_pair)
                    else:
                        callback(new_pair)
                except Exception as e:
                    self.logger.error(f"Error in callback {callback.__name__}: {e}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error processing new pair: {e}")
            return False
    
    def _apply_filters(self, new_pair: NewPairEvent) -> bool:
        """Apply filtering criteria to new pairs"""
        try:
            # Filter 1: Minimum liquidity
            if new_pair.liquidity_sol < self.min_liquidity_sol:
                self.logger.debug(f"Filtered: Low liquidity {new_pair.liquidity_sol:.2f} SOL")
                return False
            
            # Filter 2: Must be SOL pair (for now)
            if not new_pair.is_sol_pair:
                self.logger.debug(f"Filtered: Not a SOL pair")
                return False
            
            # Filter 3: Skip obvious scam tokens
            scam_keywords = ['scam', 'test', 'fake', 'rugpull', 'honeypot']
            symbol_lower = new_pair.base_symbol.lower()
            if any(keyword in symbol_lower for keyword in scam_keywords):
                self.logger.debug(f"Filtered: Suspicious symbol {new_pair.base_symbol}")
                return False
            
            # Filter 4: Basic symbol validation
            if len(new_pair.base_symbol) > 20 or not new_pair.base_symbol.replace('$', '').isalnum():
                self.logger.debug(f"Filtered: Invalid symbol {new_pair.base_symbol}")
                return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error in filters: {e}")
            return False
    
    async def _cleanup_old_pairs(self):
        """Cleanup old pairs from memory cache"""
        while self.is_running:
            try:
                current_time = time.time()
                max_age_seconds = self.max_age_minutes * 60
                
                # Clean seen pairs older than max age
                pairs_to_remove = set()
                for pair_key in self.seen_pairs:
                    # Extract timestamp from pair key if possible
                    # This is a simplified cleanup - you might want to store timestamps separately
                    pass
                
                # Clean recent pairs cache
                while (self.recent_pairs and 
                       current_time - self.recent_pairs[0].block_time > max_age_seconds):
                    self.recent_pairs.popleft()
                
                await asyncio.sleep(300)  # Cleanup every 5 minutes
                
            except Exception as e:
                self.logger.error(f"Error in cleanup: {e}")
                await asyncio.sleep(300)
    
    def stop_scanning(self):
        """Stop the scanner"""
        self.logger.info("🛑 Stopping DEX Listings Scanner...")
        self.is_running = False
    
    def get_stats(self) -> Dict:
        """Get scanner statistics"""
        uptime = time.time() - self.stats['scanner_uptime'] if self.stats['scanner_uptime'] else 0
        
        return {
            'total_pairs_found': self.stats['total_pairs_found'],
            'filtered_pairs': self.stats['filtered_pairs'],
            'duplicate_pairs': self.stats['duplicate_pairs'],
            'valid_new_pairs': self.stats['valid_new_pairs'],
            'cache_size': len(self.seen_pairs),
            'recent_pairs_count': len(self.recent_pairs),
            'uptime_seconds': uptime,
            'uptime_hours': uptime / 3600,
            'last_pair_time': self.stats['last_pair_time'].isoformat() if self.stats['last_pair_time'] else None,
            'enabled_dexs': self.enabled_dexs,
            'is_running': self.is_running
        }
    
    def get_recent_pairs(self, limit: int = 20) -> List[NewPairEvent]:
        """Get recent pairs found by the scanner"""
        return list(self.recent_pairs)[-limit:]
    
    def clear_cache(self):
        """Clear the scanner cache"""
        self.seen_pairs.clear()
        self.recent_pairs.clear()
        self.logger.info("Scanner cache cleared")

# Integration functions for your existing bot

async def create_dex_scanner_integration(config: Dict, database_manager: DatabaseManager, 
                                       rugcheck_analyzer: RugCheckAnalyzer, 
                                       comprehensive_analyzer_callback: Callable) -> DEXListingsScanner:
    """
    Create and configure the DEX scanner with integration to your existing bot
    
    Args:
        config: Bot configuration
        database_manager: Database manager instance
        rugcheck_analyzer: RugCheck analyzer instance
        comprehensive_analyzer_callback: Function to call for comprehensive analysis
        
    Returns:
        Configured DEXListingsScanner instance
    """
    
    # Create scanner
    scanner = DEXListingsScanner(config, database_manager, rugcheck_analyzer)
    
    # Add callback for new pairs
    async def on_new_pair(new_pair: NewPairEvent):
        """Callback when scanner finds a new pair"""
        try:
            # Determine which token to analyze (non-SOL token)
            token_to_analyze = None
            if new_pair.base_token != "So11111111111111111111111111111111111111112":
                token_to_analyze = new_pair.base_token
            elif new_pair.quote_token != "So11111111111111111111111111111111111111112":
                token_to_analyze = new_pair.quote_token
            
            if token_to_analyze:
                # Log the discovery with more details
                logger = logging.getLogger(__name__)
                logger.info(
                    f"🚨 SCANNER DISCOVERY: {new_pair.base_symbol}/{new_pair.quote_symbol} "
                    f"on {new_pair.dex.value.upper()}\n"
                    f"   📍 Token: {token_to_analyze}\n"
                    f"   💧 Liquidity: {new_pair.liquidity_sol:.2f} SOL\n"
                    f"   💰 Price: ${new_pair.initial_price:.8f}" if new_pair.initial_price else "N/A"
                )
                
                # Call comprehensive analysis
                analysis_result = await comprehensive_analyzer_callback(token_to_analyze)
                
                # Enhanced logging based on analysis
                if analysis_result.get('passed_all_checks', False):
                    trading_rec = analysis_result.get('trading_recommendation', {})
                    if trading_rec.get('action') == 'BUY':
                        logger.info(
                            f"🎯 EXCELLENT DISCOVERY: {new_pair.base_symbol} - "
                            f"{trading_rec.get('action')} (Confidence: {trading_rec.get('confidence', 0):.1%})"
                        )
                
        except Exception as e:
            logger.error(f"Error processing scanned pair: {e}")
    
    scanner.add_new_pair_callback(on_new_pair)
    
    return scanner

# Example usage and configuration

SCANNER_CONFIG_EXAMPLE = {
    'scanner': {
        'enabled': True,
        'min_liquidity_sol': 5.0,          # Minimum 5 SOL liquidity
        'max_age_minutes': 60,              # Consider pairs up to 1 hour old
        'enabled_dexs': ['raydium', 'orca'], # Which DEXs to scan
        'scan_interval_seconds': 30,        # How often to scan
        'filters': {
            'require_sol_pair': True,       # Only SOL pairs
            'min_symbol_length': 2,         # Minimum symbol length
            'max_symbol_length': 15,        # Maximum symbol length
            'exclude_keywords': ['test', 'fake', 'scam']
        }
    }
}

def add_scanner_to_config(existing_config: Dict) -> Dict:
    """Add scanner configuration to existing bot config"""
    if 'scanner' not in existing_config:
        existing_config['scanner'] = SCANNER_CONFIG_EXAMPLE['scanner']
    
    return existing_config

if __name__ == "__main__":
    # Example test run
    async def test_scanner():
        """Test the scanner"""
        import asyncio
        
        # Mock database and rugcheck for testing
        class MockDB:
            def get_token_by_address(self, address):
                return None
        
        class MockRugCheck:
            pass
        
        config = SCANNER_CONFIG_EXAMPLE
        scanner = DEXListingsScanner(config, MockDB(), MockRugCheck())
        
        # Add test callback
        def test_callback(pair):
            print(f"🆕 Found pair: {pair.base_symbol}/{pair.quote_symbol} on {pair.dex.value}")
        
        scanner.add_new_pair_callback(test_callback)
        
        # Run for 5 minutes
        try:
            task = asyncio.create_task(scanner.start_scanning())
            await asyncio.sleep(300)  # 5 minutes
            scanner.stop_scanning()
            await task
        except KeyboardInterrupt:
            scanner.stop_scanning()
        
        # Print stats
        stats = scanner.get_stats()
        print(f"\n📊 Scanner Stats:")
        for key, value in stats.items():
            print(f"   {key}: {value}")
    
    asyncio.run(test_scanner())