#!/usr/bin/env python3
"""
Token Data Synchronization Backend
Continuously monitors new tokens from transactions table and enriches them with DexScreener data
"""

#original script

import sqlite3
import requests
import time
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Set
import threading
from dataclasses import dataclass
import sys
import signal

# Configuration
CONFIG = {
    'db_path': 'solana_wallet_monitor.db',
    'api_rate_limit': 2.0,  # seconds between API calls
    'batch_size': 50,       # tokens to process per batch
    'update_interval': 60,  # seconds between sync cycles
    'price_update_interval': 300,  # 5 minutes for price updates
    'dashboard_update_interval': 150, # 2.5 minutes pour dashboard tokens
    'max_retries': 3,
    'pumpfun_rate_limit': 2.0,  # Rate limit spécifique Pump.fun
    'pumpfun_batch_size': 20,   # Batch plus petit pour Pump.fun
    'request_timeout': 10,
    'retry_failed_after_days': 7,  # Réessayer les tokens flaggés après X jours
    'max_failed_attempts': 1,      # Nombre max de tentatives avant flagging définitif
    'known_quote_tokens': {
        'So11111111111111111111111111111111111111112',  # SOL
        'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
        'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',  # USDT
        '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R',  # RAY
        'mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So'   # mSOL
    }
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
    metadata_source: str = None
    original_address: str = None  # For tracking pair -> token conversion

class TokenSyncService:
    """Main service for token synchronization"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.running = False
        self.logger = self._setup_logger()
        
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
            'start_time': None
        }
    
    def _setup_logger(self) -> logging.Logger:
        """Setup logging configuration"""
        logger = logging.getLogger('TokenSync')
        logger.setLevel(logging.DEBUG)
        
        # Console handler with UTF-8 encoding
        handler = logging.StreamHandler()
        handler.stream = open(handler.stream.fileno(), mode='w', encoding='utf-8', buffering=1)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
        # File handler with UTF-8 encoding
        file_handler = logging.FileHandler('token_sync.log', encoding='utf-8')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        return logger
    
    def get_db_connection(self) -> sqlite3.Connection:
        """Get database connection with error handling"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as e:
            self.logger.error(f"Database connection error: {e}")
            raise
    
    def get_pumpfun_data(self, token_address: str) -> Optional[TokenData]:
        """Get token data from Pump.fun API"""
        # URLs Pump.fun (comme dans le script qui fonctionne)
        pump_fun_urls = [
            f"https://frontend-api.pump.fun/coins/{token_address}",
            f"https://frontend-api-v2.pump.fun/coins/{token_address}",
            f"https://frontend-api-v3.pump.fun/coins/{token_address}",
        ]
        
        for i, url in enumerate(pump_fun_urls):
            try:
                response = self.session.get(url, timeout=CONFIG['request_timeout'])
                self.stats['api_calls'] += 1
                
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
                        
                        self.logger.info(f"✅ Found Pump.fun data for {token_address[:8]}... (MC: ${token_data.market_cap:,.0f}) via URL {i+1}")
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
            response = self.session.get(url_pair, timeout=CONFIG['request_timeout'])
            self.stats['api_calls'] += 1
            
            if response.status_code == 200:
                data = response.json()
                if 'pair' in data and data['pair']:
                    return 'pair'
            
            # Test tokens endpoint
            url_token = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
            response = self.session.get(url_token, timeout=CONFIG['request_timeout'])
            self.stats['api_calls'] += 1
            
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
            response = self.session.get(url, timeout=CONFIG['request_timeout'])
            self.stats['api_calls'] += 1
            
            if response.status_code == 200:
                data = response.json()
                
                if 'pair' in data and data['pair']:
                    pair = data['pair']
                    base_token = pair.get('baseToken', {}).get('address')
                    quote_token = pair.get('quoteToken', {}).get('address')
                    
                    # Prefer base token if quote is known stable/SOL
                    if quote_token in CONFIG['known_quote_tokens']:
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
            response = self.session.get(url, timeout=CONFIG['request_timeout'])
            self.stats['api_calls'] += 1
            
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
            response = self.session.get(url, timeout=CONFIG['request_timeout'])
            self.stats['api_calls'] += 1
            
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
            self.logger.info(f"✅ Found creation timestamp on DexScreener: {datetime.fromtimestamp(timestamp)}")
            return timestamp
        
        # Pause to avoid rate limiting
        time.sleep(0.5)
        
        # Try Solana Tracker
        timestamp = self.get_token_creation_from_solanatracker(token_address)
        if timestamp:
            self.logger.info(f"✅ Found creation timestamp on SolanaTracker: {datetime.fromtimestamp(timestamp)}")
            return timestamp
        
        self.logger.debug(f"❌ Creation timestamp not found for {token_address[:8]}...")
        return None
    
    def get_dexscreener_data(self, address: str) -> Optional[TokenData]:
        """Get token data from DexScreener with smart address handling"""
        try:
            token_address = address
            original_address = address
            token_data = None
            
            # Identify address type
            address_type = self.identify_address_type(address)
            
            # If it's a pair, extract token address
            if address_type == 'pair':
                self.logger.info(f"Pair detected {address[:8]}..., extracting token")
                token_address = self.extract_token_from_pair(address)
                
                if not token_address:
                    self.logger.warning(f"Could not extract token from pair {address}")
                    return None
                
                self.logger.info(f"Token extracted: {token_address[:8]}...")
            
            # Get token data
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            response = self.session.get(url, timeout=CONFIG['request_timeout'])
            self.stats['api_calls'] += 1
            
            if response.status_code == 200:
                data = response.json()
                
                if 'pairs' in data and data['pairs']:
                    # Filter valid pairs and sort by liquidity
                    valid_pairs = [
                        p for p in data['pairs'] 
                        if p.get('fdv') and float(p.get('fdv', 0)) > 0
                    ]
                    
                    if not valid_pairs:
                        token_data = None
                    else: 
                        # Take pair with highest liquidity
                        best_pair = max(
                            valid_pairs,
                            key=lambda x: float(x.get('liquidity', {}).get('usd', 0) or 0)
                        )
                        
                        # Get token creation timestamp
                        creation_timestamp = self.get_token_creation_timestamp(token_address)
                        if not creation_timestamp:
                            # If not found via dedicated methods, try from the pair data
                            if 'pairCreatedAt' in best_pair:
                                creation_time = best_pair['pairCreatedAt']
                                if creation_time and creation_time > 1e12:  # If in milliseconds
                                    creation_timestamp = int(creation_time // 1000)
                                elif creation_time:
                                    creation_timestamp = int(creation_time)
                        
                        # Create TokenData object
                        token_data = TokenData(
                            address=token_address,
                            symbol=best_pair.get('baseToken', {}).get('symbol'),
                            name=best_pair.get('baseToken', {}).get('name'),
                            price_usd=float(best_pair.get('priceUsd', 0) or 0),
                            timestamp_token_created=creation_timestamp or 0,
                            creator_address=data.get('creator'),
                            bonding_curve_progress=float(data.get('bonding_curve_progress', 0)),
                            holder_count=int(data.get('holder_count', 0) or data.get('holders', 0)),
                            market_cap=float(best_pair.get('fdv', 0) or 0),
                            volume_1h=float(best_pair.get('volume', {}).get('h1', 0) or 0),
                            volume_6h=float(best_pair.get('volume', {}).get('h6', 0) or 0),
                            volume_24h=float(best_pair.get('volume', {}).get('h24', 0) or 0),
                            price_change_1h=float(best_pair.get('priceChange', {}).get('h1', 0) or 0),
                            price_change_6h=float(best_pair.get('priceChange', {}).get('h6', 0) or 0),
                            price_change_24h=float(best_pair.get('priceChange', {}).get('h24', 0) or 0),
                            metadata_source=f"dexscreener_{address_type}",
                            original_address=original_address
                        )
                else:  
                    token_data = None
                    
        except Exception as e:
            self.logger.error(f"Error fetching DexScreener data for {address}: {e}")
            token_data = None

        if not token_data:
            token_data = self.get_pumpfun_data(token_address)
            if token_data:
                token_data.metadata_source = "pumpfun"

        return token_data
    
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
                
                cursor.execute(query, (CONFIG['retry_failed_after_days'], CONFIG['max_failed_attempts']))
                results = cursor.fetchall()
                
                token_addresses = {row[0] for row in results}
                self.logger.info(f"Found {len(token_addresses)} new tokens to process (excluding flagged tokens)")
                
                return token_addresses
                
        except Exception as e:
            self.logger.error(f"Error getting new tokens: {e}")
            return set()
    
    def get_tokens_needing_price_update(self) -> List[str]:
        """Get tokens that need price updates (excluding flagged tokens)"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Get tokens that haven't been updated recently and aren't flagged
                cutoff_time = int(time.time()) - CONFIG['price_update_interval']
                
                query = """
                SELECT address 
                FROM tokens 
                WHERE (last_price_update < ? OR last_price_update IS NULL)
                AND (no_data_available = 0 OR no_data_available IS NULL
                    OR (no_data_available = 1 AND no_data_last_check < datetime('now', '-' || ? || ' days')))
                AND (failed_attempts < ? OR failed_attempts IS NULL)
                ORDER BY last_price_update ASC NULLS FIRST
                LIMIT ?
                """
                
                cursor.execute(query, (cutoff_time, CONFIG['retry_failed_after_days'], CONFIG['max_failed_attempts'], CONFIG['batch_size']))
                results = cursor.fetchall()
                
                return [row[0] for row in results]
                
        except Exception as e:
            self.logger.error(f"Error getting tokens for price update: {e}")
            return []
    
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
                    
                    if result and result[0] >= CONFIG['max_failed_attempts']:
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

    # 5. AJOUTER nouvelle méthode pour créer un token stub quand aucune donnée n'est trouvée
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
                self.logger.info(f"📝 Created stub entry for {token_address[:8]}...")
                return True
                
        except Exception as e:
            self.logger.error(f"Error creating token stub {token_address}: {e}")
            return False

    def upsert_token(self, token_data: TokenData) -> bool:
        """Insert or update token in database"""
        try:
            self.logger.debug(f"Raw token data for {token_data.address[:8]}... - Symbol: '{token_data.symbol}', Name: '{token_data.name}'")
            original_symbol = token_data.symbol
            original_name = token_data.name
            # Nettoyer les données avant insertion
            token_data = self.clean_token_data(token_data)
            if original_symbol != token_data.symbol:
                self.logger.info(f"Symbol cleaned for {token_data.address[:8]}... - '{original_symbol}' -> '{token_data.symbol}'")
            if original_name != token_data.name:
                self.logger.info(f"Name cleaned for {token_data.address[:8]}... - '{original_name}' -> '{token_data.name}'")
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                current_timestamp = int(time.time())
                
                # Check if token exists
                cursor.execute("SELECT address FROM tokens WHERE address = ?", (token_data.address,))
                exists = cursor.fetchone() is not None
                self.logger.debug(f"Token {token_data.address[:8]}... exists: {exists}")

                if exists:
                    self.logger.debug(f"Updating token {token_data.address[:8]}... with symbol='{token_data.symbol}', name='{token_data.name}'")

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
                        bonding_curve_progress = ?,  
                        holder_count = ?,  
                        market_cap = ?,
                        volume_5m = ?,
                        volume_1h = ?,
                        volume_6h = ?,
                        volume_24h = ?,
                        price_change_5m = ?,
                        price_change_1h = ?,
                        price_change_6h = ?,
                        price_change_24h = ?,
                        last_price_update = ?,
                        metadata_source = COALESCE(?, metadata_source),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE address = ?
                    """
                    self.logger.debug(f"UPDATE params: symbol='{token_data.symbol}', name='{token_data.name}', creator='{token_data.creator_address}'")

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
                        token_data.volume_5m,
                        token_data.volume_1h,
                        token_data.volume_6h,
                        token_data.volume_24h,
                        token_data.price_change_5m,
                        token_data.price_change_1h,
                        token_data.price_change_6h,
                        token_data.price_change_24h,
                        current_timestamp,
                        token_data.metadata_source,
                        token_data.address
                    ))
                else:
                    # Insert new token
                    self.logger.debug(f"Inserting new token {token_data.address[:8]}... with symbol='{token_data.symbol}', name='{token_data.name}'")
                    query = """
                    INSERT INTO tokens (
                        address, symbol, name, decimals, price_usd, logo_uri,
                        coingecko_id, is_verified, timestamp_token_created, creator_address,
                        bonding_curve_progress, holder_count, market_cap, volume_5m,
                        volume_1h, volume_6h, volume_24h, price_change_5m, price_change_1h, 
                        price_change_6h, price_change_24h, last_price_update, metadata_source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """
                    self.logger.debug(f"INSERT params: symbol='{token_data.symbol}', name='{token_data.name}', creator='{token_data.creator_address}'")
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
                        token_data.volume_5m,
                        token_data.volume_1h,
                        token_data.volume_6h,
                        token_data.volume_24h,
                        token_data.price_change_5m,
                        token_data.price_change_1h,
                        token_data.price_change_6h,
                        token_data.price_change_24h,
                        current_timestamp,
                        token_data.metadata_source
                    ))
                
                conn.commit()
                return True
                
        except Exception as e:
            self.logger.error(f"Error upserting token {token_data.address}: {e}")
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
                    HAVING total_buys > 0
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
                        ROUND((ts.first_discovery - COALESCE(tk.timestamp_token_created, ts.first_tx_timestamp)) / 3600.0, 1) as discovery_delay_hours
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
                
                cursor.execute(query, (CONFIG['batch_size'] * 2,))  # Plus de tokens prioritaires
                results = cursor.fetchall()
                
                token_addresses = [row[0] for row in results if row[0]]
                self.logger.info(f"Found {len(token_addresses)} dashboard priority tokens")
                
                return token_addresses
                
        except Exception as e:
            self.logger.error(f"Error getting dashboard priority tokens: {e}")
            return []

    # 2. AJOUTER cette méthode pour les tokens dashboard qui ont besoin de mise à jour
    def get_dashboard_tokens_needing_update(self) -> List[str]:
        """Get dashboard tokens that need data updates (prioritized)"""
        try:
            dashboard_tokens = self.get_dashboard_priority_tokens()
            
            if not dashboard_tokens:
                return []
            
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Construire la requête avec placeholders
                placeholders = ','.join(['?' for _ in dashboard_tokens])
                cutoff_time = int(time.time()) - (CONFIG['price_update_interval'] // 2)  # Update plus fréquent
                
                query = f"""
                SELECT t.address 
                FROM tokens t
                WHERE t.address IN ({placeholders})
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
                
                params = dashboard_tokens + [cutoff_time]
                cursor.execute(query, params)
                results = cursor.fetchall()
                
                priority_tokens = [row[0] for row in results]
                self.logger.info(f"Found {len(priority_tokens)} dashboard tokens needing updates")
                
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
                WHERE timestamp_token_created IS NULL OR timestamp_token_created = 0
                ORDER BY created_at DESC
                LIMIT ?
                """
                
                cursor.execute(query, (CONFIG['batch_size'],))
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
                        self.logger.info(f"✅ Updated creation timestamp for {token_address[:8]}...")
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
        self.logger.info("Starting creation timestamp updates for existing tokens...")
        
        tokens_to_update = self.get_tokens_missing_creation_timestamp()
        
        if not tokens_to_update:
            self.logger.info("No tokens need creation timestamp updates")
            return 0
        
        successful_updates = 0
        
        for token_address in tokens_to_update:
            try:
                if self.update_token_creation_timestamp(token_address):
                    successful_updates += 1
                
                # Rate limiting between creation timestamp requests
                time.sleep(CONFIG['api_rate_limit'])
                
            except Exception as e:
                self.logger.error(f"Error updating creation timestamp for {token_address}: {e}")
                continue
        
        self.logger.info(f"Creation timestamp update completed: {successful_updates}/{len(tokens_to_update)} successful")
        
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
                ORDER BY created_at DESC
                LIMIT ?
                """
                
                cursor.execute(query, (CONFIG['batch_size'] // 2,))  # Batch plus petit
                results = cursor.fetchall()
                
                return [row[0] for row in results]
                
        except Exception as e:
            self.logger.error(f"Error getting tokens needing Pump.fun update: {e}")
            return []

    def update_pumpfun_tokens(self) -> int:
        """Update Pump.fun tokens with missing data"""
        self.logger.info("Starting Pump.fun data updates for tokens with missing market data...")
        
        tokens_to_update = self.get_tokens_needing_pumpfun_update()
        
        if not tokens_to_update:
            self.logger.info("No tokens need Pump.fun updates")
            return 0
        
        successful_updates = 0
        
        for token_address in tokens_to_update:
            try:
                self.logger.info(f"Fetching Pump.fun data for: {token_address[:8]}...")
                
                # Get data from Pump.fun
                pumpfun_data = self.get_pumpfun_data(token_address)
                
                if pumpfun_data:
                    # Update only the missing fields in database
                    if self.update_token_with_pumpfun_data(token_address, pumpfun_data):
                        successful_updates += 1
                        self.logger.info(f"✅ Updated Pump.fun data for: {token_address[:8]}...")
                    else:
                        self.logger.warning(f"❌ Failed to save Pump.fun data for: {token_address[:8]}...")
                else:
                    self.logger.debug(f"No Pump.fun data found for: {token_address[:8]}...")
                
                # Rate limiting spécifique pour Pump.fun
                time.sleep(CONFIG.get('pumpfun_rate_limit', 1.0))
                
            except Exception as e:
                self.logger.error(f"Error updating Pump.fun data for {token_address}: {e}")
                
                # Gestion spécifique des erreurs 530
                if "530" in str(e):
                    self.logger.warning("530 Server error detected, waiting longer...")
                    time.sleep(5)
                
                continue
        
        self.logger.info(f"Pump.fun update completed: {successful_updates}/{len(tokens_to_update)} successful")
        
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

    def process_token_batch(self, token_addresses: List[str]) -> int:
        """Process a batch of token addresses"""
        successful_updates = 0
        
        for address in token_addresses:
            try:
                self.logger.info(f"Processing token: {address[:8]}...")
                
                # Get data from DexScreener
                token_data = self.get_dexscreener_data(address)
                
                if token_data:
                    # Upsert to database
                    if self.upsert_token(token_data):
                        successful_updates += 1
                        self.logger.info(f"✅ Successfully updated: {address[:8]}...")
                        
                        # Reset failed attempts si le token avait des échecs précédents
                        with self.get_db_connection() as conn:
                            cursor = conn.cursor()
                            cursor.execute("""
                                UPDATE tokens 
                                SET failed_attempts = 0, no_data_available = 0
                                WHERE address = ? AND (failed_attempts > 0 OR no_data_available = 1)
                            """, (address,))
                            conn.commit()
                            
                    else:
                        self.logger.warning(f"❌ Failed to save: {address[:8]}...")
                        self.stats['failed_updates'] += 1
                else:
                    # Aucune donnée trouvée - créer un stub et marquer l'échec
                    self.logger.warning(f"❌ No data found for: {address[:8]}...")
                    self.create_token_stub(address)
                    self.stats['failed_updates'] += 1
                
                self.stats['processed_tokens'] += 1
                
                # Rate limiting
                time.sleep(CONFIG['api_rate_limit'])
                
            except Exception as e:
                self.logger.error(f"Error processing token {address}: {e}")
                # En cas d'erreur, créer aussi un stub
                self.create_token_stub(address)
                self.stats['failed_updates'] += 1
        
        return successful_updates
    
    def sync_new_tokens(self) -> int:
        """Synchronize new tokens from transactions"""
        self.logger.info("Starting new token synchronization...")
        
        all_new_tokens = self.get_new_tokens_from_transactions()
    
        if not all_new_tokens:
            self.logger.info("No new tokens to process")
            return 0
        
        # Identifier quels nouveaux tokens sont dans le dashboard
        dashboard_tokens = set(self.get_dashboard_priority_tokens())
        
        # Séparer en priorité dashboard vs autres
        priority_new_tokens = [t for t in all_new_tokens if t in dashboard_tokens]
        other_new_tokens = [t for t in all_new_tokens if t not in dashboard_tokens]
        
        self.logger.info(f"New tokens breakdown: 🎯 {len(priority_new_tokens)} dashboard priority, 📋 {len(other_new_tokens)} others")
        
        total_updated = 0
        
        # 1. D'abord traiter les tokens dashboard
        if priority_new_tokens:
            self.logger.info(f"🎯 Processing {len(priority_new_tokens)} dashboard priority new tokens")
            priority_updated = self.process_token_batch(priority_new_tokens)
            total_updated += priority_updated
            self.logger.info(f"Dashboard new tokens processed: {priority_updated}/{len(priority_new_tokens)}")
        
        # 2. Ensuite traiter les autres (avec limite)
        remaining_batch_size = max(10, CONFIG['batch_size'] - len(priority_new_tokens))
        other_tokens_batch = other_new_tokens[:remaining_batch_size]
        
        if other_tokens_batch:
            self.logger.info(f"📋 Processing {len(other_tokens_batch)} other new tokens")
            other_updated = self.process_token_batch(other_tokens_batch)
            total_updated += other_updated
            self.logger.info(f"Other new tokens processed: {other_updated}/{len(other_tokens_batch)}")
        
        self.stats['successful_updates'] += total_updated
        self.logger.info(f"New token sync completed: {total_updated}/{len(priority_new_tokens) + len(other_tokens_batch)} successful")
        
        return total_updated

    def get_dashboard_sync_stats(self) -> Dict:
        """Get statistics about dashboard token synchronization"""
        try:
            dashboard_tokens = self.get_dashboard_priority_tokens()
            
            if not dashboard_tokens:
                return {'error': 'No dashboard tokens found'}
            
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                placeholders = ','.join(['?' for _ in dashboard_tokens])
                
                # Tokens avec données complètes
                cursor.execute(f"""
                    SELECT COUNT(*) FROM tokens 
                    WHERE address IN ({placeholders})
                    AND symbol IS NOT NULL 
                    AND name IS NOT NULL
                    AND price_usd > 0
                    AND market_cap > 0
                """, dashboard_tokens)
                complete_data = cursor.fetchone()[0]
                
                # Tokens avec données récentes
                recent_cutoff = int(time.time()) - CONFIG['price_update_interval']
                cursor.execute(f"""
                    SELECT COUNT(*) FROM tokens 
                    WHERE address IN ({placeholders})
                    AND last_price_update > ?
                """, dashboard_tokens + [recent_cutoff])
                recent_updates = cursor.fetchone()[0]
                
                return {
                    'total_dashboard_tokens': len(dashboard_tokens),
                    'complete_data': complete_data,
                    'recent_updates': recent_updates,
                    'completion_rate': (complete_data / len(dashboard_tokens)) * 100 if dashboard_tokens else 0,
                    'freshness_rate': (recent_updates / len(dashboard_tokens)) * 100 if dashboard_tokens else 0
                }
                
        except Exception as e:
            self.logger.error(f"Error getting dashboard sync stats: {e}")
            return {}

    def update_existing_prices(self) -> int:
        """Update prices for existing tokens"""
        self.logger.info("Starting price updates for existing tokens...")
        
        # 1. D'abord, mettre à jour les tokens du dashboard
        dashboard_tokens = self.get_dashboard_tokens_needing_update()
        dashboard_updated = 0
        
        if dashboard_tokens:
            self.logger.info(f"🎯 Prioritizing {len(dashboard_tokens)} dashboard tokens")
            dashboard_updated = self.process_token_batch(dashboard_tokens)
            self.logger.info(f"Dashboard tokens updated: {dashboard_updated}/{len(dashboard_tokens)}")
        
        # 2. Ensuite, mettre à jour les autres tokens (avec batch réduit)
        remaining_batch_size = max(5, CONFIG['batch_size'] - len(dashboard_tokens))
        other_tokens = self.get_tokens_needing_price_update()
        
        # Exclure les tokens du dashboard déjà traités
        other_tokens = [t for t in other_tokens if t not in dashboard_tokens][:remaining_batch_size]
        
        other_updated = 0
        if other_tokens:
            self.logger.info(f"📊 Updating {len(other_tokens)} other tokens")
            other_updated = self.process_token_batch(other_tokens)
            self.logger.info(f"Other tokens updated: {other_updated}/{len(other_tokens)}")
        
        total_updated = dashboard_updated + other_updated
        total_processed = len(dashboard_tokens) + len(other_tokens)
        
        self.logger.info(f"Price update completed: {total_updated}/{total_processed} successful (📊 Dashboard: {dashboard_updated}, 📋 Others: {other_updated})")
        
        return total_updated
    
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
                """, (CONFIG['retry_failed_after_days'],))
                retry_eligible = cursor.fetchone()[0]
                
                return {
                    'no_data_flagged': no_data_count,
                    'partial_failures': partial_failures,
                    'retry_eligible': retry_eligible
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
        dashboard_stats = self.get_dashboard_sync_stats()
        
        self.logger.info("=== TOKEN SYNC STATISTICS ===")
        self.logger.info(f"Runtime: {runtime_str}")
        self.logger.info(f"Processed tokens: {self.stats['processed_tokens']}")
        self.logger.info(f"Successful updates: {self.stats['successful_updates']}")
        self.logger.info(f"Failed updates: {self.stats['failed_updates']}")
        self.logger.info(f"API calls made: {self.stats['api_calls']}")
        
        # Stats dashboard
        if dashboard_stats and 'error' not in dashboard_stats:
            self.logger.info("=== 🎯 DASHBOARD PRIORITY STATS ===")
            self.logger.info(f"Dashboard tokens: {dashboard_stats['total_dashboard_tokens']}")
            self.logger.info(f"Complete data: {dashboard_stats['complete_data']} ({dashboard_stats['completion_rate']:.1f}%)")
            self.logger.info(f"Recent updates: {dashboard_stats['recent_updates']} ({dashboard_stats['freshness_rate']:.1f}%)")
        
        # Stats de flagging
        if flagged_stats:
            self.logger.info("=== FLAGGED TOKENS STATS ===")
            self.logger.info(f"Tokens marked as no-data: {flagged_stats.get('no_data_flagged', 0)}")
            self.logger.info(f"Tokens with partial failures: {flagged_stats.get('partial_failures', 0)}")
            self.logger.info(f"Tokens eligible for retry: {flagged_stats.get('retry_eligible', 0)}")

        if self.stats['processed_tokens'] > 0:
            success_rate = (self.stats['successful_updates'] / self.stats['processed_tokens']) * 100
            self.logger.info(f"Success rate: {success_rate:.1f}%")

    
    def run_sync_cycle(self):
        """Run one complete synchronization cycle"""
        self.logger.info("Starting synchronization cycle...")
        
        try:
            # 1. Sync new tokens from transactions
            new_tokens_updated = self.sync_new_tokens()
            
            # 2. Update existing token prices
            prices_updated = self.update_existing_prices()
            
            # 3. Update missing creation timestamps (periodically)
            # Only run this every 5 cycles to avoid too many API calls
            if not hasattr(self, 'cycle_count'):
                self.cycle_count = 0
            
            self.cycle_count += 1
            creation_timestamps_updated = 0
            
            if self.cycle_count % 5 == 0:  # Every 5 cycles
                creation_timestamps_updated = self.update_missing_creation_timestamps()
            
            if self.cycle_count % 10 == 0:  # Tous les 10 cycles
                pumpfun_updated = self.update_pumpfun_tokens()

            # 4. Print statistics
            self.print_statistics()
            
            self.logger.info(f"Sync cycle completed: {new_tokens_updated} new, {prices_updated} price updates, {creation_timestamps_updated} creation timestamps")
            
        except Exception as e:
            self.logger.error(f"Error in sync cycle: {e}")
    
    def start(self):
        """Start the continuous synchronization service"""
        self.logger.info("Starting Token Sync Service...")
        self.running = True
        self.stats['start_time'] = time.time()
        
        try:
            while self.running:
                self.run_sync_cycle()
                
                if self.running:  # Check if still running before sleeping
                    self.logger.info(f"Waiting {CONFIG['update_interval']} seconds until next cycle...")
                    time.sleep(CONFIG['update_interval'])
                    
        except KeyboardInterrupt:
            self.logger.info("Received interrupt signal")
        except Exception as e:
            self.logger.error(f"Unexpected error in main loop: {e}")
        finally:
            self.stop()
    
    def stop(self):
        """Stop the synchronization service"""
        self.logger.info("Stopping Token Sync Service...")
        self.running = False
        self.session.close()
        self.print_statistics()
        self.logger.info("Token Sync Service stopped")

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
    
    print("Token Data Synchronization Backend")
    print("=" * 40)
    print(f"Database: {CONFIG['db_path']}")
    print(f"Update interval: {CONFIG['update_interval']} seconds")
    print(f"Price update interval: {CONFIG['price_update_interval']} seconds")
    print(f"API rate limit: {CONFIG['api_rate_limit']} seconds")
    print("=" * 40)
    
    # Initialize service
    service = TokenSyncService(CONFIG['db_path'])
    
    # Start service
    service.start()

if __name__ == "__main__":
    service = None
    main()