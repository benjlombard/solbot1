"""
Pump.fun API Client
Specialized client for interacting with Pump.fun API endpoints.
"""
import asyncio
import aiohttp
from typing import Dict, List, Optional, Tuple
from .base_client import BaseApiClient, ApiResponse, RateLimitConfig
from ..models.token_data import TokenData


class PumpFunClient(BaseApiClient):
    """
    Client for Pump.fun API with specialized methods for token data retrieval
    """
    
    def __init__(self, logger=None, api_tracker=None):
        # Pump.fun has stricter rate limits
        super().__init__(
            base_url="https://frontend-api-v3.pump.fun",
            api_name="pumpfun",
            timeout=30.0,
            rate_limit=RateLimitConfig(
                calls_per_minute=30,  # More conservative
                calls_per_hour=1800,
                burst_limit=5
            ),
            logger=logger,
            api_tracker=api_tracker
        )
        
        # Alternative endpoints for fallback
        self.fallback_endpoints = [
            "https://frontend-api.pump.fun",
            "https://frontend-api-v2.pump.fun"
        ]
    
    def _get_default_headers(self) -> Dict[str, str]:
        """Get Pump.fun specific headers"""
        headers = super()._get_default_headers()
        headers.update({
            'Referer': 'https://pump.fun/',
            'Origin': 'https://pump.fun',
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip, deflate, br'
        })
        return headers
    
    def get_api_info(self) -> Dict:
        """Get Pump.fun API information"""
        return {
            "name": "Pump.fun",
            "base_url": self.base_url,
            "fallback_urls": self.fallback_endpoints,
            "rate_limits": {
                "calls_per_minute": 30,
                "burst_limit": 5
            },
            "endpoints": [
                "coins/{address}",
                "coins/trending",
                "coins/new"
            ]
        }
    
    def get_token_data(self, token_address: str) -> Optional[TokenData]:
        """
        Get token data for a single token address with fallback endpoints
        
        Args:
            token_address: Token address to lookup
            
        Returns:
            TokenData object or None if not found
        """
        # Try main endpoint first
        response = self.make_request(f"coins/{token_address}")
        
        if response.success:
            token_data = self._parse_pump_response(token_address, response.data)
            if token_data:
                return token_data
        
        # Try fallback endpoints
        for fallback_url in self.fallback_endpoints:
            try:
                self.logger.debug(f"Trying fallback endpoint: {fallback_url}")
                
                # Temporarily change base URL
                original_base_url = self.base_url
                self.base_url = fallback_url
                
                try:
                    # Utiliser make_request au lieu de requests direct
                    fallback_response = self.make_request(f"coins/{token_address}")
                    
                    if fallback_response.success:
                        token_data = self._parse_pump_response(token_address, fallback_response.data)
                        if token_data:
                            self.logger.debug(f"✅ Found data via fallback: {fallback_url}")
                            return token_data
                            
                finally:
                    # Restaurer l'URL originale
                    self.base_url = original_base_url
                    
            except Exception as e:
                self.logger.debug(f"Fallback endpoint {fallback_url} failed: {e}")
                continue
        
        self.logger.debug(f"Token not found on any Pump.fun endpoint: {token_address[:8]}...")
        return None
    
    async def get_token_data_async(
        self, 
        session: aiohttp.ClientSession, 
        token_address: str
    ) -> Optional[TokenData]:
        """
        Get token data asynchronously with fallback endpoints
        
        Args:
            session: aiohttp session
            token_address: Token address to lookup
            
        Returns:
            TokenData object or None if not found
        """
        # Try main endpoint first
        response = await self.make_async_request(session, f"coins/{token_address}")
        
        if response.success:
            token_data = self._parse_pump_response(token_address, response.data)
            if token_data:
                return token_data
        
        # Try fallback endpoints
        for fallback_url in self.fallback_endpoints:
            try:
                self.logger.debug(f"Trying async fallback: {fallback_url}")
                
                original_base_url = self.base_url
                self.base_url = fallback_url
                
                try:
                    # Utiliser make_async_request au lieu d'aiohttp direct
                    fallback_response = await self.make_async_request(session, f"coins/{token_address}")
                    
                    if fallback_response.success:
                        token_data = self._parse_pump_response(token_address, fallback_response.data)
                        if token_data:
                            self.logger.debug(f"✅ Found data via async fallback: {fallback_url}")
                            return token_data
                            
                finally:
                    # Restaurer l'URL originale
                    self.base_url = original_base_url
                    
            except Exception as e:
                self.logger.debug(f"Async fallback {fallback_url} failed: {e}")
                continue
        
        return None
    
    def get_tokens_batch(self, token_addresses: List[str]) -> Dict[str, TokenData]:
        """
        Get token data for multiple addresses (Pump.fun doesn't have native batch, so sequential)
        
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
                time.sleep(1.0 / self.rate_limit.burst_limit)  # Respect burst limit
                
            except Exception as e:
                self.logger.debug(f"Error getting Pump.fun data for {token_address[:8]}...: {e}")
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
        # Limit concurrent requests to respect rate limits
        semaphore = asyncio.Semaphore(3)  # Max 3 concurrent
        
        async def fetch_single_token(token_addr: str) -> Tuple[str, Optional[TokenData]]:
            async with semaphore:
                try:
                    token_data = await self.get_token_data_async(session, token_addr)
                    return token_addr, token_data
                except Exception as e:
                    self.logger.debug(f"Async error for {token_addr[:8]}...: {e}")
                    return token_addr, None
        
        # Execute requests
        tasks = [fetch_single_token(addr) for addr in token_addresses]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        results = {}
        for result in results_list:
            if isinstance(result, Exception):
                self.logger.debug(f"Async task exception: {result}")
                continue
            
            token_addr, token_data = result
            if token_data:
                results[token_addr] = token_data
        
        return results
    
    def get_trending_tokens(self, limit: int = 20) -> List[TokenData]:
        """
        Get trending tokens from Pump.fun
        
        Args:
            limit: Maximum number of tokens to return
            
        Returns:
            List of TokenData objects
        """
        response = self.make_request("coins/trending")
        
        if not response.success:
            self.logger.warning(f"Failed to get trending tokens: {response.error_message}")
            return []
        
        tokens = []
        
        if response.data and isinstance(response.data, list):
            for token_info in response.data[:limit]:
                try:
                    token_address = token_info.get('mint') or token_info.get('address')
                    if token_address:
                        token_data = self._parse_pump_response(token_address, token_info)
                        if token_data:
                            tokens.append(token_data)
                except Exception as e:
                    self.logger.debug(f"Error parsing trending token: {e}")
                    continue
        
        return tokens
    
    def get_new_tokens(self, limit: int = 20) -> List[TokenData]:
        """
        Get newly created tokens from Pump.fun
        
        Args:
            limit: Maximum number of tokens to return
            
        Returns:
            List of TokenData objects
        """
        response = self.make_request("coins/new")
        
        if not response.success:
            self.logger.warning(f"Failed to get new tokens: {response.error_message}")
            return []
        
        tokens = []
        
        if response.data and isinstance(response.data, list):
            for token_info in response.data[:limit]:
                try:
                    token_address = token_info.get('mint') or token_info.get('address')
                    if token_address:
                        token_data = self._parse_pump_response(token_address, token_info)
                        if token_data:
                            tokens.append(token_data)
                except Exception as e:
                    self.logger.debug(f"Error parsing new token: {e}")
                    continue
        
        return tokens
    
    def _parse_pump_response(self, token_address: str, data: Dict) -> Optional[TokenData]:
        """Parse Pump.fun API response into TokenData object"""
        try:
            if not data or not isinstance(data, dict):
                return None
            
            # Validate mint address
            mint = data.get('mint') or data.get('address') or data.get('tokenAddress')
            if mint and mint.lower() != token_address.lower():
                # Sometimes the response doesn't match exactly, but we still want the data
                self.logger.debug(f"Mint mismatch but processing anyway: {mint} vs {token_address}")
            
            # Parse basic token info
            symbol = data.get('symbol', f"UNK_{token_address[:6]}")
            name = data.get('name', f"Unknown Token {token_address[:8]}")
            decimals = int(data.get('decimals', 6))
            
            # Parse financial data
            market_cap = float(data.get('usd_market_cap', 0) or 0)
            total_supply = float(data.get('total_supply', 1) or 1)
            
            # Calculate price from market cap and supply
            price_usd = market_cap / total_supply if total_supply > 0 else 0.0
            
            # Alternative price calculation from reserves
            if price_usd == 0.0:
                sol_reserves = float(data.get('virtual_sol_reserves', 0) or 0)
                token_reserves = float(data.get('virtual_token_reserves', 1) or 1)
                if sol_reserves > 0 and token_reserves > 0:
                    # Approximate SOL price (this should ideally come from an oracle)
                    sol_price_usd = 150.0  # Rough estimate, should be more precise
                    price_sol = sol_reserves / token_reserves
                    price_usd = price_sol * sol_price_usd
            
            # Parse timestamps
            creation_timestamp = 0
            if 'created_timestamp' in data:
                timestamp = data['created_timestamp']
                if timestamp:
                    # Handle both milliseconds and seconds timestamps
                    creation_timestamp = int(timestamp / 1000) if timestamp > 1e12 else int(timestamp)
            
            # Parse Pump.fun specific data
            bonding_curve_progress = float(data.get('bonding_curve_progress', 0) or 0)
            holder_count = int(data.get('holder_count', 0) or data.get('holders', 0) or 0)
            volume_24h = float(data.get('volume_24h', 0) or 0)
            
            # Creator and verification
            creator_address = data.get('creator')
            is_verified = bool(data.get('complete', False) or data.get('verified', False))
            logo_uri = data.get('image_uri') or data.get('image')
            
            # Create TokenData object
            token_data = TokenData(
                address=token_address,
                symbol=symbol,
                name=name,
                decimals=decimals,
                price_usd=price_usd,
                timestamp_token_created=creation_timestamp,
                creator_address=creator_address,
                bonding_curve_progress=bonding_curve_progress,
                holder_count=holder_count,
                market_cap=market_cap,
                volume_24h=volume_24h,
                logo_uri=logo_uri,
                is_verified=is_verified,
                metadata_source="pumpfun",
                # Pump.fun specific fields
                is_pump_fun=True,
                launchpad_name="pump_fun"
            )
            
            # Clean and validate data
            token_data = token_data.clean_symbol_name()
            
            self.logger.debug(
                f"✅ Parsed Pump.fun data for {token_address[:8]}... "
                f"({symbol}, MC: ${market_cap:,.0f}, Progress: {bonding_curve_progress:.1f}%)"
            )
            
            return token_data
            
        except Exception as e:
            self.logger.error(f"Error parsing Pump.fun response for {token_address[:8]}...: {e}")
            return None
    
    def get_token_creation_timestamp(self, token_address: str) -> Optional[int]:
        """
        Get token creation timestamp from Pump.fun
        
        Args:
            token_address: Token address
            
        Returns:
            Unix timestamp or None
        """
        token_data = self.get_token_data(token_address)
        return token_data.timestamp_token_created if token_data else None
    
    def is_pump_fun_token(self, token_address: str) -> bool:
        """
        Check if a token exists on Pump.fun
        
        Args:
            token_address: Token address to check
            
        Returns:
            True if token exists on Pump.fun
        """
        token_data = self.get_token_data(token_address)
        return token_data is not None
    
    def get_token_bonding_status(self, token_address: str) -> Optional[Dict]:
        """
        Get detailed bonding curve status for a token
        
        Args:
            token_address: Token address
            
        Returns:
            Dictionary with bonding curve information
        """
        response = self.make_request(f"coins/{token_address}")
        
        if not response.success or not response.data:
            return None
        
        data = response.data
        
        return {
            'bonding_curve_progress': float(data.get('bonding_curve_progress', 0) or 0),
            'virtual_sol_reserves': float(data.get('virtual_sol_reserves', 0) or 0),
            'virtual_token_reserves': float(data.get('virtual_token_reserves', 0) or 0),
            'real_sol_reserves': float(data.get('real_sol_reserves', 0) or 0),
            'real_token_reserves': float(data.get('real_token_reserves', 0) or 0),
            'complete': bool(data.get('complete', False)),
            'graduated': float(data.get('bonding_curve_progress', 0) or 0) >= 100.0,
            'market_cap': float(data.get('usd_market_cap', 0) or 0),
            'holder_count': int(data.get('holder_count', 0) or 0)
        }
    
    def get_pump_fun_health_status(self) -> Dict:
        """
        Check Pump.fun API health status
        
        Returns:
            Dictionary with health information
        """
        health_status = {
            'main_endpoint': False,
            'fallback_endpoints': {},
            'overall_healthy': False,
            'recommended_endpoint': None
        }
        
        # Test main endpoint
        try:
            response = self.make_request("coins/trending", max_retries=0)
            health_status['main_endpoint'] = response.success
            if response.success:
                health_status['recommended_endpoint'] = self.base_url
        except:
            pass
        
        # Test fallback endpoints
        for fallback_url in self.fallback_endpoints:
            try:
                original_base_url = self.base_url
                self.base_url = fallback_url
                
                response = self.make_request("coins/trending", max_retries=1)
                health_status['fallback_endpoints'][fallback_url] = response.success
                
                if response.success and not health_status['recommended_endpoint']:
                    health_status['recommended_endpoint'] = fallback_url
                
                self.base_url = original_base_url
                
            except:
                health_status['fallback_endpoints'][fallback_url] = False
        
        # Overall health
        health_status['overall_healthy'] = (
            health_status['main_endpoint'] or 
            any(health_status['fallback_endpoints'].values())
        )
        
        return health_status