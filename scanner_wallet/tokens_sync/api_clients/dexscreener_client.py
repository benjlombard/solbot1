"""
DexScreener API Client
Specialized client for interacting with DexScreener API endpoints.
"""
import asyncio
import aiohttp
from typing import Dict, List, Optional, Tuple
from .base_client import BaseApiClient, ApiResponse, RateLimitConfig
from ..models.token_data import TokenData


class DexScreenerClient(BaseApiClient):
    """
    Client for DexScreener API with specialized methods for token data retrieval
    """
    
    def __init__(self, logger=None, api_tracker=None):
        super().__init__(
            base_url="https://api.dexscreener.com/latest",
            api_name="dexscreener",
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
        """Get DexScreener API information"""
        return {
            "name": "DexScreener",
            "base_url": self.base_url,
            "rate_limits": {
                "calls_per_minute": 60,
                "burst_limit": 10
            },
            "endpoints": [
                "tokens/{addresses}",
                "pairs/solana/{address}",
                "search"
            ]
        }
    
    def get_token_data(self, token_address: str) -> Optional[TokenData]:
        """
        Get token data for a single token address
        
        Args:
            token_address: Token address to lookup
            
        Returns:
            TokenData object or None if not found
        """
        response = self.make_request(f"dex/tokens/{token_address}")
        
        if not response.success:
            self.logger.debug(f"Failed to get token data for {token_address[:8]}...: {response.error_message}")
            return None
        
        return self._parse_single_token_response(token_address, response.data)

    async def get_token_data_async(self, session: aiohttp.ClientSession, token_address: str) -> Optional[TokenData]:
        """
        Asynchronously get token data for a single token address.
        
        Args:
            session: The aiohttp client session.
            token_address: Token address to lookup.
            
        Returns:
            TokenData object or None if not found.
        """
        response = await self.make_async_request(session, f"dex/tokens/{token_address}")
        
        if not response.success:
            self.logger.debug(f"Failed to get token data for {token_address[:8]}...: {response.error_message}")
            return None
        
        return self._parse_single_token_response(token_address, response.data)
    
    def get_tokens_batch(self, token_addresses: List[str], batch_size: int = 30) -> Dict[str, TokenData]:
        """
        Get token data for multiple addresses using batch endpoint
        
        Args:
            token_addresses: List of token addresses
            batch_size: Maximum tokens per batch (DexScreener limit is 30)
            
        Returns:
            Dictionary mapping token_address -> TokenData
        """
        all_tokens_data = {}
        
        for i in range(0, len(token_addresses), batch_size):
            batch = token_addresses[i:i + batch_size]
            addresses_str = ','.join(batch)
            
            response = self.make_request(f"dex/tokens/{addresses_str}")
            
            if response.success:
                batch_data = self._parse_batch_response(batch, response.data)
                all_tokens_data.update(batch_data)
            else:
                self.logger.warning(f"Batch request failed for {len(batch)} tokens: {response.error_message}")
                # Fallback to individual requests for this batch
                for token_addr in batch:
                    individual_data = self.get_token_data(token_addr)
                    if individual_data:
                        all_tokens_data[token_addr] = individual_data
        
        return all_tokens_data
    
    async def get_tokens_batch_async(self, session: aiohttp.ClientSession, token_addresses: List[str], batch_size: int = 30) -> Dict[str, TokenData]:
        """
        Asynchronously get token data for multiple addresses.
        This method is simplified to only handle batching. Fallback logic is handled by the calling processor.
        """
        all_tokens_data = {}
        max_batch_size = min(30, batch_size)
        
        tasks = []
        for i in range(0, len(token_addresses), max_batch_size):
            batch = token_addresses[i:i + max_batch_size]
            tasks.append(self._fetch_batch_async(session, batch))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, Exception):
                self.logger.warning(f"A batch request failed with exception: {result}")
                continue
            if result:
                all_tokens_data.update(result)
            
        return all_tokens_data
    
    async def _fetch_batch_async(self, session: aiohttp.ClientSession, batch: List[str]) -> Dict[str, TokenData]:
        """Fetch a single batch asynchronously avec validation"""
        if len(batch) > 30:
            self.logger.warning(f"Batch size {len(batch)} exceeds DexScreener limit of 30")
            return {}
        
        if not batch:
            return {}

        valid_addresses = []
        for addr in batch:
            if addr and len(addr.strip()) >= 32:  # Adresse Solana valide
                valid_addresses.append(addr.strip())
            else:
                self.logger.debug(f"Invalid token address skipped: {addr}")
        
        if not valid_addresses:
            self.logger.warning("No valid addresses in batch")
            return {}
        # CORRECTION: Construire l'URL correctement
        addresses_str = ','.join(valid_addresses)
        
        # Vérifier la longueur de l'URL pour éviter les erreurs 400
        test_url = f"{self.base_url}/dex/tokens/{addresses_str}"
        if len(test_url) > 1800:  # Limite URL
            self.logger.warning(f"URL too long ({len(test_url)} chars), splitting batch")
            mid = len(valid_addresses) // 2
            batch1 = valid_addresses[:mid]
            batch2 = valid_addresses[mid:]
            
            result1 = await self._fetch_batch_async(session, batch1)
            result2 = await self._fetch_batch_async(session, batch2)
            
            result1.update(result2)
            return result1
        
        try:
            response = await self.make_async_request(session, f"dex/tokens/{addresses_str}")
            
            if response.success and response.data:
                return self._parse_batch_response(valid_addresses, response.data)
            else:
                self.logger.debug(f"Batch request failed: {response.error_message}")
                return {}
                
        except Exception as e:
            self.logger.warning(f"Batch request exception: {e}")
            return {}
    
    def get_pair_data(self, pair_address: str) -> Optional[Dict]:
        """
        Get data for a specific trading pair
        
        Args:
            pair_address: Trading pair address
            
        Returns:
            Pair data dictionary or None
        """
        response = self.make_request(f"dex/pairs/solana/{pair_address}")
        
        if response.success and response.data.get('pair'):
            return response.data['pair']
        
        return None
    
    def extract_token_from_pair(self, pair_address: str) -> Optional[str]:
        """
        Extract token address from a trading pair
        
        Args:
            pair_address: Trading pair address
            
        Returns:
            Token address or None
        """
        pair_data = self.get_pair_data(pair_address)
        
        if pair_data:
            base_token = pair_data.get('baseToken', {}).get('address')
            quote_token = pair_data.get('quoteToken', {}).get('address')
            
            # Known quote tokens to avoid
            known_quotes = {
                'So11111111111111111111111111111111111111112',  # SOL
                'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
                # Add more as needed
            }
            
            if quote_token in known_quotes:
                return base_token
            else:
                return base_token  # Default to base token
        
        return None
    
    def get_token_creation_timestamp(self, token_address: str) -> Optional[int]:
        """
        Get token creation timestamp from DexScreener
        
        Args:
            token_address: Token address
            
        Returns:
            Unix timestamp or None
        """
        response = self.make_request(f"dex/tokens/{token_address}")
        
        if response.success and response.data.get('pairs'):
            pairs = response.data['pairs']
            if pairs:
                # Take the oldest pair (first creation)
                oldest_pair = min(pairs, key=lambda p: p.get('pairCreatedAt', float('inf')))
                
                creation_time = oldest_pair.get('pairCreatedAt')
                if creation_time:
                    # Handle milliseconds vs seconds
                    if creation_time > 1e12:
                        return int(creation_time // 1000)
                    else:
                        return int(creation_time)
        
        return None
    
    def _parse_single_token_response(self, token_address: str, data: Dict) -> Optional[TokenData]:
        """Parse API response for a single token"""
        if not data or not data.get('pairs'):
            return None
        
        # Get the best pair (highest volume)
        pairs = data['pairs']
        best_pair = max(pairs, key=lambda p: float(p.get('volume', {}).get('h24', 0) or 0))
        
        return self._convert_pair_to_token_data(token_address, best_pair)
    
    def _parse_batch_response(self, requested_tokens: List[str], data: Dict) -> Dict[str, TokenData]:
        """Parse API response for multiple tokens"""
        result = {}
        
        if not data or not data.get('pairs'):
            return result
        
        # Create a mapping of token addresses to their pairs
        token_pairs = {}
        requested_set = set(requested_tokens)
        
        for pair in data['pairs']:
            base_addr = pair.get('baseToken', {}).get('address')
            quote_addr = pair.get('quoteToken', {}).get('address')
            
            # Check if any of our requested tokens are in this pair
            if base_addr in requested_set:
                if base_addr not in token_pairs:
                    token_pairs[base_addr] = []
                token_pairs[base_addr].append(pair)
            
            if quote_addr in requested_set:
                if quote_addr not in token_pairs:
                    token_pairs[quote_addr] = []
                token_pairs[quote_addr].append(pair)
        
        # Convert pairs to TokenData
        for token_addr, pairs in token_pairs.items():
            # Select best pair (highest volume)
            best_pair = max(pairs, key=lambda p: float(p.get('volume', {}).get('h24', 0) or 0))
            token_data = self._convert_pair_to_token_data(token_addr, best_pair)
            if token_data:
                result[token_addr] = token_data
        
        return result
    
    def _convert_pair_to_token_data(self, token_address: str, pair_data: Dict) -> Optional[TokenData]:
        """Convert DexScreener pair data to TokenData object"""
        try:
            # Determine which token info to use
            base_token_addr = pair_data.get('baseToken', {}).get('address')
            quote_token_addr = pair_data.get('quoteToken', {}).get('address')
            
            if base_token_addr == token_address:
                target_token = pair_data.get('baseToken', {})
            elif quote_token_addr == token_address:
                target_token = pair_data.get('quoteToken', {})
            else:
                # Default to base token
                target_token = pair_data.get('baseToken', {})
            
            # Handle creation timestamp
            creation_timestamp = 0
            if 'pairCreatedAt' in pair_data:
                creation_time = pair_data['pairCreatedAt']
                if creation_time and creation_time > 1e12:
                    creation_timestamp = int(creation_time // 1000)
                elif creation_time:
                    creation_timestamp = int(creation_time)
            
            # Create TokenData object
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
                metadata_source="dexscreener"
            )
            
            # Clean and validate data
            return token_data.clean_symbol_name()
            
        except Exception as e:
            self.logger.error(f"Error converting pair data for {token_address[:8]}...: {e}")
            return None