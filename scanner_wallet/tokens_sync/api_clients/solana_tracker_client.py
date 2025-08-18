"""
Solana Tracker API Client
Specialized client for interacting with SolanaTracker.io API for token data and analytics.
"""
import asyncio
import aiohttp
from typing import Dict, List, Optional, Tuple, Any
from .base_client import BaseApiClient, ApiResponse, RateLimitConfig
from ..models.token_data import TokenData


class SolanaTrackerClient(BaseApiClient):
    """
    Client for SolanaTracker.io API with specialized methods for token analytics
    """
    
    def __init__(self, logger=None, api_tracker=None):
        super().__init__(
            base_url="https://api.solanatracker.io",
            api_name="solanatracker",
            timeout=30.0,
            rate_limit=RateLimitConfig(
                calls_per_minute=60,
                calls_per_hour=3600,
                burst_limit=10
            ),
            logger=logger,
            api_tracker=api_tracker
        )
    
    def get_api_info(self) -> Dict:
        """Get SolanaTracker API information"""
        return {
            "name": "SolanaTracker",
            "base_url": self.base_url,
            "rate_limits": {
                "calls_per_minute": 60,
                "burst_limit": 10
            },
            "endpoints": [
                "tokens/{address}",
                "tokens/{address}/price",
                "tokens/{address}/holders",
                "tokens/{address}/transactions",
                "tokens/trending",
                "tokens/new"
            ],
            "features": [
                "Token metadata",
                "Price data",
                "Holder analytics",
                "Transaction history",
                "Trending tokens",
                "New token discovery"
            ]
        }
    
    def get_token_data(self, token_address: str) -> Optional[TokenData]:
        """
        Get comprehensive token data from SolanaTracker
        
        Args:
            token_address: Token address to lookup
            
        Returns:
            TokenData object or None if not found
        """
        response = self.make_request(f"tokens/{token_address}")
        
        if not response.success:
            self.logger.debug(f"SolanaTracker failed for {token_address[:8]}...: {response.error_message}")
            return None
        
        if not response.data:
            self.logger.debug(f"No SolanaTracker data for {token_address[:8]}...")
            return None
        
        return self._parse_token_response(token_address, response.data)
    
    async def get_token_data_async(
        self, 
        session: aiohttp.ClientSession, 
        token_address: str
    ) -> Optional[TokenData]:
        """
        Get token data asynchronously
        
        Args:
            session: aiohttp session
            token_address: Token address to lookup
            
        Returns:
            TokenData object or None if not found
        """
        response = await self.make_async_request(session, f"tokens/{token_address}")
        
        if not response.success or not response.data:
            self.logger.debug(f"Async SolanaTracker failed for {token_address[:8]}...")
            return None
        
        return self._parse_token_response(token_address, response.data)
    
    def get_token_price(self, token_address: str) -> Optional[Dict]:
        """
        Get current price data for a token
        
        Args:
            token_address: Token address
            
        Returns:
            Price data dictionary or None
        """
        response = self.make_request(f"tokens/{token_address}/price")
        
        if response.success and response.data:
            return response.data
        
        return None
    
    def get_token_holders(self, token_address: str, limit: int = 100) -> Optional[Dict]:
        """
        Get holder distribution data for a token
        
        Args:
            token_address: Token address
            limit: Maximum number of holders to return
            
        Returns:
            Holder data dictionary or None
        """
        params = {'limit': limit}
        response = self.make_request(f"tokens/{token_address}/holders", params=params)
        
        if response.success and response.data:
            return response.data
        
        return None
    
    def get_token_transactions(
        self, 
        token_address: str, 
        limit: int = 50,
        transaction_type: Optional[str] = None
    ) -> Optional[List[Dict]]:
        """
        Get recent transactions for a token
        
        Args:
            token_address: Token address
            limit: Maximum number of transactions
            transaction_type: Filter by type ('buy', 'sell', 'transfer')
            
        Returns:
            List of transaction dictionaries or None
        """
        params = {'limit': limit}
        if transaction_type:
            params['type'] = transaction_type
        
        response = self.make_request(f"tokens/{token_address}/transactions", params=params)
        
        if response.success and response.data:
            return response.data.get('transactions', [])
        
        return None
    
    def get_trending_tokens(self, timeframe: str = '24h', limit: int = 20) -> List[TokenData]:
        """
        Get trending tokens from SolanaTracker
        
        Args:
            timeframe: Time period ('1h', '24h', '7d')
            limit: Maximum number of tokens
            
        Returns:
            List of TokenData objects
        """
        params = {'timeframe': timeframe, 'limit': limit}
        response = self.make_request("tokens/trending", params=params)
        
        if not response.success or not response.data:
            self.logger.warning(f"Failed to get trending tokens: {response.error_message}")
            return []
        
        tokens = []
        
        trending_list = response.data.get('tokens', [])
        if isinstance(trending_list, list):
            for token_info in trending_list:
                try:
                    token_address = token_info.get('address') or token_info.get('mint')
                    if token_address:
                        token_data = self._parse_token_response(token_address, token_info)
                        if token_data:
                            tokens.append(token_data)
                except Exception as e:
                    self.logger.debug(f"Error parsing trending token: {e}")
                    continue
        
        return tokens
    
    def get_new_tokens(self, limit: int = 20, min_liquidity: float = 1000.0) -> List[TokenData]:
        """
        Get newly created tokens from SolanaTracker
        
        Args:
            limit: Maximum number of tokens
            min_liquidity: Minimum liquidity in USD
            
        Returns:
            List of TokenData objects
        """
        params = {'limit': limit, 'min_liquidity': min_liquidity}
        response = self.make_request("tokens/new", params=params)
        
        if not response.success or not response.data:
            self.logger.warning(f"Failed to get new tokens: {response.error_message}")
            return []
        
        tokens = []
        
        new_tokens_list = response.data.get('tokens', [])
        if isinstance(new_tokens_list, list):
            for token_info in new_tokens_list:
                try:
                    token_address = token_info.get('address') or token_info.get('mint')
                    if token_address:
                        token_data = self._parse_token_response(token_address, token_info)
                        if token_data:
                            tokens.append(token_data)
                except Exception as e:
                    self.logger.debug(f"Error parsing new token: {e}")
                    continue
        
        return tokens
    
    def get_token_creation_timestamp(self, token_address: str) -> Optional[int]:
        """
        Get token creation timestamp from SolanaTracker
        
        Args:
            token_address: Token address
            
        Returns:
            Unix timestamp or None
        """
        response = self.make_request(f"tokens/{token_address}")
        
        if response.success and response.data:
            token_info = response.data.get('token', {})
            creation_info = token_info.get('creation', {})
            
            if 'created_time' in creation_info:
                return int(creation_info['created_time'])
            elif 'created_at' in creation_info:
                timestamp = creation_info['created_at']
                # Handle both seconds and milliseconds
                return int(timestamp / 1000) if timestamp > 1e12 else int(timestamp)
        
        return None
    
    def get_tokens_batch(self, token_addresses: List[str]) -> Dict[str, TokenData]:
        """
        Get token data for multiple addresses (sequential processing)
        
        Args:
            token_addresses: List of token addresses
            
        Returns:
            Dictionary mapping token_address -> TokenData
        """
        results = {}
        
        for token_address in token_addresses:
            try:
                token_data = self.get_token_data(token_address)
                if token_data:
                    results[token_address] = token_data
                
                # Rate limiting between calls
                import time
                time.sleep(1.0)  # Conservative rate limiting
                
            except Exception as e:
                self.logger.debug(f"Error getting SolanaTracker data for {token_address[:8]}...: {e}")
                continue
        
        return results
    
    async def get_tokens_batch_async(
        self, 
        session: aiohttp.ClientSession, 
        token_addresses: List[str]
    ) -> Dict[str, TokenData]:
        """
        Get token data for multiple addresses asynchronously
        
        Args:
            session: aiohttp session
            token_addresses: List of token addresses
            
        Returns:
            Dictionary mapping token_address -> TokenData
        """
        # Limit concurrent requests
        semaphore = asyncio.Semaphore(5)  # Conservative concurrency
        
        async def fetch_single_token(token_addr: str) -> Tuple[str, Optional[TokenData]]:
            async with semaphore:
                try:
                    # Small delay to respect rate limits
                    await asyncio.sleep(0.2)
                    token_data = await self.get_token_data_async(session, token_addr)
                    return token_addr, token_data
                except Exception as e:
                    self.logger.debug(f"Async SolanaTracker error for {token_addr[:8]}...: {e}")
                    return token_addr, None
        
        # Execute requests
        tasks = [fetch_single_token(addr) for addr in token_addresses]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        results = {}
        for result in results_list:
            if isinstance(result, Exception):
                self.logger.debug(f"SolanaTracker async task exception: {result}")
                continue
            
            token_addr, token_data = result
            if token_data:
                results[token_addr] = token_data
        
        return results
    
    def _parse_token_response(self, token_address: str, data: Dict) -> Optional[TokenData]:
        """Parse SolanaTracker API response into TokenData object"""
        try:
            if not data or not isinstance(data, dict):
                return None
            
            # Handle nested token data structure
            token_info = data.get('token', data)  # Sometimes data is nested under 'token'
            
            # Basic token information
            symbol = token_info.get('symbol', f"UNK_{token_address[:6]}")
            name = token_info.get('name', f"Unknown Token {token_address[:8]}")
            decimals = int(token_info.get('decimals', 9))
            
            # Price and market data
            price_usd = float(token_info.get('price', 0) or token_info.get('price_usd', 0) or 0)
            market_cap = float(token_info.get('market_cap', 0) or token_info.get('fdv', 0) or 0)
            
            # Supply information
            total_supply = float(token_info.get('total_supply', 0) or 0)
            circulating_supply = float(token_info.get('circulating_supply', total_supply))
            
            # Volume data
            volume_data = token_info.get('volume', {})
            if isinstance(volume_data, dict):
                volume_24h = float(volume_data.get('24h', 0) or volume_data.get('h24', 0) or 0)
                volume_1h = float(volume_data.get('1h', 0) or volume_data.get('h1', 0) or 0)
                volume_6h = float(volume_data.get('6h', 0) or volume_data.get('h6', 0) or 0)
            else:
                volume_24h = float(token_info.get('volume_24h', 0) or 0)
                volume_1h = float(token_info.get('volume_1h', 0) or 0)
                volume_6h = float(token_info.get('volume_6h', 0) or 0)
            
            # Price change data
            price_changes = token_info.get('price_change', {})
            if isinstance(price_changes, dict):
                price_change_24h = float(price_changes.get('24h', 0) or price_changes.get('h24', 0) or 0)
                price_change_1h = float(price_changes.get('1h', 0) or price_changes.get('h1', 0) or 0)
                price_change_6h = float(price_changes.get('6h', 0) or price_changes.get('h6', 0) or 0)
            else:
                price_change_24h = float(token_info.get('price_change_24h', 0) or 0)
                price_change_1h = float(token_info.get('price_change_1h', 0) or 0)
                price_change_6h = float(token_info.get('price_change_6h', 0) or 0)
            
            # Liquidity data
            liquidity_data = token_info.get('liquidity', {})
            if isinstance(liquidity_data, dict):
                liquidity_usd = float(liquidity_data.get('usd', 0) or liquidity_data.get('total', 0) or 0)
                liquidity_sol = float(liquidity_data.get('sol', 0) or liquidity_data.get('base', 0) or 0)
            else:
                liquidity_usd = float(token_info.get('liquidity_usd', 0) or 0)
                liquidity_sol = float(token_info.get('liquidity_sol', 0) or 0)
            
            # Holder information
            holder_count = int(token_info.get('holder_count', 0) or token_info.get('holders', 0) or 0)
            
            # Creation timestamp
            creation_timestamp = 0
            creation_info = token_info.get('creation', {})
            if isinstance(creation_info, dict):
                if 'created_time' in creation_info:
                    creation_timestamp = int(creation_info['created_time'])
                elif 'created_at' in creation_info:
                    timestamp = creation_info['created_at']
                    creation_timestamp = int(timestamp / 1000) if timestamp > 1e12 else int(timestamp)
            elif 'created_at' in token_info:
                timestamp = token_info['created_at']
                creation_timestamp = int(timestamp / 1000) if timestamp > 1e12 else int(timestamp)
            
            # Additional metadata
            logo_uri = token_info.get('logo') or token_info.get('image') or token_info.get('logo_uri')
            is_verified = bool(token_info.get('verified', False) or token_info.get('is_verified', False))
            
            # Social and website data
            social_data = token_info.get('social', {})
            website = social_data.get('website') if isinstance(social_data, dict) else None
            twitter = social_data.get('twitter') if isinstance(social_data, dict) else None
            telegram = social_data.get('telegram') if isinstance(social_data, dict) else None
            
            # Create TokenData object
            token_data = TokenData(
                address=token_address,
                symbol=symbol,
                name=name,
                decimals=decimals,
                price_usd=price_usd,
                timestamp_token_created=creation_timestamp,
                holder_count=holder_count,
                market_cap=market_cap,
                fdv=market_cap,  # SolanaTracker typically provides FDV as market_cap
                volume_1h=volume_1h,
                volume_6h=volume_6h,
                volume_24h=volume_24h,
                price_change_1h=price_change_1h,
                price_change_6h=price_change_6h,
                price_change_24h=price_change_24h,
                liquidity_usd=liquidity_usd,
                liquidity_sol=liquidity_sol,
                logo_uri=logo_uri,
                is_verified=is_verified,
                metadata_source="solanatracker"
            )
            
            # Clean and validate data
            token_data = token_data.clean_symbol_name()
            
            self.logger.debug(
                f"✅ Parsed SolanaTracker data for {token_address[:8]}... "
                f"({symbol}, MC: ${market_cap:,.0f}, Holders: {holder_count})"
            )
            
            return token_data
            
        except Exception as e:
            self.logger.error(f"Error parsing SolanaTracker response for {token_address[:8]}...: {e}")
            return None
    
    def get_token_analytics(self, token_address: str) -> Optional[Dict]:
        """
        Get comprehensive analytics for a token
        
        Args:
            token_address: Token address
            
        Returns:
            Analytics dictionary with multiple data points
        """
        analytics = {}
        
        try:
            # Get basic token data
            token_data = self.get_token_data(token_address)
            if token_data:
                analytics['token'] = token_data.to_dict() if hasattr(token_data, 'to_dict') else token_data.__dict__
            
            # Get price data
            price_data = self.get_token_price(token_address)
            if price_data:
                analytics['price'] = price_data
            
            # Get holder data
            holder_data = self.get_token_holders(token_address, limit=50)
            if holder_data:
                analytics['holders'] = holder_data
            
            # Get recent transactions
            transactions = self.get_token_transactions(token_address, limit=20)
            if transactions:
                analytics['transactions'] = transactions
            
            return analytics if analytics else None
            
        except Exception as e:
            self.logger.error(f"Error getting analytics for {token_address[:8]}...: {e}")
            return None
    
    def search_tokens(self, query: str, limit: int = 10) -> List[TokenData]:
        """
        Search for tokens by name or symbol
        
        Args:
            query: Search query (name or symbol)
            limit: Maximum number of results
            
        Returns:
            List of matching TokenData objects
        """
        params = {'q': query, 'limit': limit}
        response = self.make_request("tokens/search", params=params)
        
        if not response.success or not response.data:
            return []
        
        tokens = []
        search_results = response.data.get('tokens', [])
        
        for token_info in search_results:
            try:
                token_address = token_info.get('address') or token_info.get('mint')
                if token_address:
                    token_data = self._parse_token_response(token_address, token_info)
                    if token_data:
                        tokens.append(token_data)
            except Exception as e:
                self.logger.debug(f"Error parsing search result: {e}")
                continue
        
        return tokens
    
    def get_solanatracker_health_status(self) -> Dict:
        """
        Check SolanaTracker API health status
        
        Returns:
            Dictionary with health information
        """
        try:
            # Test with trending endpoint (usually fast)
            response = self.make_request("tokens/trending", params={'limit': 1}, max_retries=1)
            
            return {
                'healthy': response.success,
                'status_code': response.status_code,
                'response_time': response.duration,
                'error_message': response.error_message,
                'features_available': {
                    'trending': response.success,
                    'basic_token_data': response.success
                }
            }
            
        except Exception as e:
            return {
                'healthy': False,
                'status_code': None,
                'response_time': 0,
                'error_message': str(e),
                'features_available': {
                    'trending': False,
                    'basic_token_data': False
                }
            }