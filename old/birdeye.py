"""
Birdeye API Integration Module
File: birdeye.py

Integration with Birdeye API for new token discovery and market data.
"""

import requests
import time
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

@dataclass
class BirdeyeToken:
    """Token information from Birdeye"""
    address: str
    symbol: str
    name: str
    decimals: int
    logo_uri: Optional[str] = None
    created_at: Optional[int] = None
    age_hours: Optional[float] = None
    price: Optional[float] = None
    price_change_24h: Optional[float] = None
    volume_24h: Optional[float] = None
    market_cap: Optional[float] = None
    liquidity: Optional[float] = None
    holder_count: Optional[int] = None
    fdv: Optional[float] = None
    
    def __post_init__(self):
        """Calculate age from creation timestamp"""
        if self.created_at:
            current_time = int(time.time())
            self.age_hours = (current_time - self.created_at) / 3600

class BirdeyeAnalyzer:
    """
    Birdeye API integration for token discovery and analysis
    
    Features:
    - New token discovery
    - Token metadata and market data
    - Price and volume tracking
    - Age-based filtering
    """
    
    BASE_URL = "https://public-api.birdeye.so"
    
    def __init__(self, config: Dict):
        self.config = config.get('birdeye', {})
        self.api_key = self.config.get('api_key', '')
        self.logger = logging.getLogger(__name__)
        
        # Rate limiting
        self.last_request_time = 0
        self.min_request_interval = self.config.get('rate_limit_delay', 1.0)
        
        # Headers for API requests
        self.headers = {
            'Accept': 'application/json',
            'User-Agent': 'SolanaBot/1.0',
        }
        
        if self.api_key:
            self.headers['X-API-KEY'] = self.api_key
            self.logger.info("✅ Birdeye API key configured")
        else:
            self.logger.warning("⚠️ Birdeye API key not configured - rate limits may apply")
    
    def _rate_limit(self):
        """Apply rate limiting between requests"""
        current_time = time.time()
        elapsed = current_time - self.last_request_time
        
        if elapsed < self.min_request_interval:
            sleep_time = self.min_request_interval - elapsed
            time.sleep(sleep_time)
        
        self.last_request_time = time.time()
    
    def _make_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """Make API request with rate limiting and error handling"""
        self._rate_limit()
        
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        
        try:
            response = requests.get(
                url,
                headers=self.headers,
                params=params or {},
                timeout=self.config.get('api_timeout', 30)
            )
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                self.logger.warning("Rate limited by Birdeye API")
                time.sleep(5)
                return None
            else:
                self.logger.warning(f"Birdeye API error: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.Timeout:
            self.logger.error("Birdeye API request timeout")
            return None
        except Exception as e:
            self.logger.error(f"Birdeye API request failed: {e}")
            return None
    
    def get_new_tokens(self, max_age_hours: int = 24, limit: int = 50, 
                      sort_by: str = 'creation_time') -> List[BirdeyeToken]:
        """
        Get new tokens from Birdeye
        
        Args:
            max_age_hours: Maximum age of tokens in hours
            limit: Maximum number of tokens to return
            sort_by: Sort criteria ('creation_time', 'volume', 'market_cap')
        
        Returns:
            List of BirdeyeToken objects
        """
        try:
            # Calculate timestamp cutoff
            cutoff_timestamp = int(time.time() - (max_age_hours * 3600))
            
            # Birdeye new tokens endpoint
            params = {
                'limit': min(limit, 100),  # API limit
                'sort_by': sort_by,
                'sort_type': 'desc',
                'created_after': cutoff_timestamp
            }
            
            self.logger.info(f"🐦 Getting new tokens from Birdeye (max age: {max_age_hours}h)")
            
            response = self._make_request('/defi/token_creation', params)
            
            if not response or 'data' not in response:
                self.logger.warning("No data returned from Birdeye new tokens API")
                return []
            
            tokens = []
            for token_data in response['data']:
                try:
                    token = self._parse_token_data(token_data)
                    if token and (not token.age_hours or token.age_hours <= max_age_hours):
                        tokens.append(token)
                except Exception as e:
                    self.logger.debug(f"Error parsing token data: {e}")
                    continue
            
            self.logger.info(f"✅ Found {len(tokens)} new tokens from Birdeye")
            return tokens
            
        except Exception as e:
            self.logger.error(f"Error getting new tokens from Birdeye: {e}")
            return []
    
    def get_token_overview(self, token_address: str) -> Optional[BirdeyeToken]:
        """Get detailed token overview from Birdeye"""
        try:
            endpoint = f'/defi/token_overview'
            params = {'address': token_address}
            
            response = self._make_request(endpoint, params)
            
            if response and 'data' in response:
                return self._parse_token_data(response['data'])
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting token overview: {e}")
            return None
    
    def get_trending_tokens(self, timeframe: str = '24h', limit: int = 50) -> List[BirdeyeToken]:
        """
        Get trending tokens from Birdeye
        
        Args:
            timeframe: Time period ('1h', '24h', '7d')
            limit: Maximum number of tokens
        
        Returns:
            List of trending BirdeyeToken objects
        """
        try:
            params = {
                'limit': min(limit, 100),
                'timeframe': timeframe,
                'sort_by': 'volume_change_percent',
                'sort_type': 'desc'
            }
            
            response = self._make_request('/defi/trending', params)
            
            if not response or 'data' not in response:
                return []
            
            tokens = []
            for token_data in response['data']:
                try:
                    token = self._parse_token_data(token_data)
                    if token:
                        tokens.append(token)
                except Exception as e:
                    self.logger.debug(f"Error parsing trending token: {e}")
                    continue
            
            self.logger.info(f"📈 Found {len(tokens)} trending tokens from Birdeye")
            return tokens
            
        except Exception as e:
            self.logger.error(f"Error getting trending tokens: {e}")
            return []
    
    def get_token_security(self, token_address: str) -> Optional[Dict]:
        """Get token security information from Birdeye"""
        try:
            endpoint = f'/defi/token_security'
            params = {'address': token_address}
            
            response = self._make_request(endpoint, params)
            
            if response and 'data' in response:
                return response['data']
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error getting token security info: {e}")
            return None
    
    def _parse_token_data(self, token_data: Dict) -> Optional[BirdeyeToken]:
        """Parse token data from Birdeye API response"""
        try:
            # Extract basic token info
            address = token_data.get('address')
            if not address:
                return None
            
            symbol = token_data.get('symbol', 'UNKNOWN')
            name = token_data.get('name', 'Unknown')
            decimals = token_data.get('decimals', 9)
            logo_uri = token_data.get('logoURI')
            created_at = token_data.get('createdAt') or token_data.get('creation_time')
            
            # Market data
            price = token_data.get('price') or token_data.get('priceUsd')
            price_change_24h = token_data.get('priceChange24h') or token_data.get('price_change_24h_percent')
            volume_24h = token_data.get('volume24h') or token_data.get('volume_24h_usd')
            market_cap = token_data.get('marketCap') or token_data.get('mc')
            liquidity = token_data.get('liquidity') or token_data.get('liquidityUsd')
            holder_count = token_data.get('holderCount') or token_data.get('holder_count')
            fdv = token_data.get('fdv') or token_data.get('fully_diluted_valuation')
            
            # Convert string numbers to float if needed
            def safe_float(value):
                if value is None:
                    return None
                try:
                    return float(value)
                except (ValueError, TypeError):
                    return None
            
            return BirdeyeToken(
                address=address,
                symbol=symbol,
                name=name,
                decimals=decimals,
                logo_uri=logo_uri,
                created_at=created_at,
                price=safe_float(price),
                price_change_24h=safe_float(price_change_24h),
                volume_24h=safe_float(volume_24h),
                market_cap=safe_float(market_cap),
                liquidity=safe_float(liquidity),
                holder_count=int(holder_count) if holder_count else None,
                fdv=safe_float(fdv)
            )
            
        except Exception as e:
            self.logger.debug(f"Error parsing token data: {e}")
            return None
    
    async def get_new_tokens_async(self, max_age_hours: int = 24, limit: int = 50) -> List[BirdeyeToken]:
        """Async version of get_new_tokens"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_new_tokens, max_age_hours, limit)
    
    async def get_trending_tokens_async(self, timeframe: str = '24h', limit: int = 50) -> List[BirdeyeToken]:
        """Async version of get_trending_tokens"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.get_trending_tokens, timeframe, limit)
    
    def get_stats(self) -> Dict:
        """Get Birdeye analyzer statistics"""
        return {
            'api_key_configured': bool(self.api_key),
            'base_url': self.BASE_URL,
            'rate_limit_delay': self.min_request_interval,
            'last_request_time': self.last_request_time
        }

# Factory function
def create_birdeye_analyzer(config: Dict) -> BirdeyeAnalyzer:
    """Factory function to create Birdeye analyzer"""
    return BirdeyeAnalyzer(config)

# Utility functions
async def get_newest_birdeye_tokens(config: Dict, max_age_hours: int = 24, limit: int = 50) -> List[Dict]:
    """Utility function to get newest tokens from Birdeye"""
    analyzer = create_birdeye_analyzer(config)
    tokens = await analyzer.get_new_tokens_async(max_age_hours, limit)
    
    # Convert to dict format compatible with existing code
    return [
        {
            'token_address': token.address,
            'symbol': token.symbol,
            'name': token.name,
            'age_hours': token.age_hours or 0,
            'liquidity_usd': token.liquidity or 0,
            'volume_24h': token.volume_24h or 0,
            'price_usd': token.price or 0,
            'price_change_24h': token.price_change_24h or 0,
            'market_cap': token.market_cap or 0,
            'created_timestamp': token.created_at or int(time.time()),
            'chain_id': 'solana',
            'source': 'birdeye'
        }
        for token in tokens
    ]

if __name__ == "__main__":
    # Test Birdeye integration
    import asyncio
    
    async def test_birdeye():
        config = {
            'birdeye': {
                'api_key': '',  # Add your API key here for testing
                'rate_limit_delay': 1.0,
                'api_timeout': 30
            }
        }
        
        analyzer = create_birdeye_analyzer(config)
        
        print("🐦 Testing Birdeye API integration...")
        
        # Test new tokens
        new_tokens = analyzer.get_new_tokens(max_age_hours=48, limit=10)
        print(f"📊 Found {len(new_tokens)} new tokens")
        
        for i, token in enumerate(new_tokens[:3], 1):
            print(f"  {i}. {token.symbol} - Age: {token.age_hours:.1f}h - Price: ${token.price or 0:.8f}")
        
        # Test trending tokens
        trending = analyzer.get_trending_tokens(timeframe='24h', limit=5)
        print(f"🔥 Found {len(trending)} trending tokens")
        
        for i, token in enumerate(trending[:3], 1):
            change = token.price_change_24h or 0
            print(f"  {i}. {token.symbol} - Change: {change:+.2f}%")
    
    asyncio.run(test_birdeye())
