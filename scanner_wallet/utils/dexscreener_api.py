import aiohttp
import asyncio
from typing import Dict, Optional, Any

from core.logger import get_logger

logger = get_logger(__name__)

BASE_URL = "https://api.dexscreener.com/latest/dex/tokens"

async def get_dexscreener_data_for_mints(token_addresses: list[str]) -> Dict[str, Dict[str, Any]]:
    """
    Fetches DexScreener data for a list of token mints asynchronously.

    Args:
        token_addresses: A list of token mint addresses.

    Returns:
        A dictionary where keys are mint addresses and values are the
        extracted DexScreener data for the best pair.
    """
    if not token_addresses:
        return {}

    # The original URL was incorrect for fetching by token mints.
    # It was /dex/pairs/solana/{mints}, which expects pair addresses.
    # The correct endpoint is /dex/tokens/{mints}.
    url = f"https://api.dexscreener.com/latest/dex/tokens/{','.join(token_addresses)}"
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    if data and data.get('pairs'):
                        # The response for /tokens endpoint also contains a 'pairs' key.
                        # The logic to find the best pair remains the same.
                        return _find_best_pairs_for_tokens(data['pairs'])
                    else:
                        logger.debug("No pairs found in DexScreener response for tokens: %s", token_addresses)
                        return {}
                else:
                    logger.warning(f"DexScreener API error: {response.status} for tokens {token_addresses}")
                    return {}
        except asyncio.TimeoutError:
            logger.warning(f"DexScreener API timeout for tokens {token_addresses}")
            return {}
        except Exception as e:
            logger.error(f"Error fetching DexScreener data: {e}", exc_info=True)
            return {}

def _find_best_pairs_for_tokens(pairs: list[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Processes a list of pairs to find the best one (highest liquidity) for each base token.
    """
    best_pairs_by_mint = {}
    for pair in pairs:
        base_token_address = pair.get('baseToken', {}).get('address')
        if not base_token_address:
            continue

        liquidity_usd = float(pair.get('liquidity', {}).get('usd', 0))

        # If we haven't seen this mint yet, or this pair has more liquidity
        if base_token_address not in best_pairs_by_mint or liquidity_usd > best_pairs_by_mint[base_token_address].get('liquidity', {}).get('usd', 0):
            best_pairs_by_mint[base_token_address] = pair

    # Now extract the fields from the best pair for each mint
    results = {}
    for mint, pair_data in best_pairs_by_mint.items():
        results[mint] = _extract_dexscreener_fields(pair_data)
        
    return results

def _extract_dexscreener_fields(pair_data: Dict) -> Dict:
    """
    Extracts relevant fields from a DexScreener pair data object.
    """
    def safe_float(value, default=0.0):
        try:
            return float(value) if value is not None else default
        except (ValueError, TypeError):
            return default

    price_usd = safe_float(pair_data.get('priceUsd'))
    liquidity = safe_float(pair_data.get('liquidity', {}).get('usd'))
    volume_24h = safe_float(pair_data.get('volume', {}).get('h24'))
    
    return {
        'price_usd': price_usd,
        'liquidity_usd': liquidity,
        'volume_24h': volume_24h
    }

async def get_price_and_liquidity(token_address: str) -> Optional[Dict[str, float]]:
    """
    A simple wrapper to get price and liquidity for a single token.
    Note: It's more efficient to use get_dexscreener_data_for_mints for multiple tokens.
    """
    data = await get_dexscreener_data_for_mints([token_address])
    return data.get(token_address)

if __name__ == '__main__':
    # Example usage
    async def test():
        # A list of recently discovered tokens
        test_mints = [
            "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", # WIF
            "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm", # WEN
            "61Cj6SPELhKW2dXqPXjAV1dyv2JFcSStdCuksYmbaicx"  # User's token
        ]
        
        print(f"Fetching data for {len(test_mints)} tokens...")
        results = await get_dexscreener_data_for_mints(test_mints)
        
        for mint, data in results.items():
            print(f"\n--- {mint} ---")
            if data:
                print(f"  Price: ${data.get('price_usd', 'N/A')}")
                print(f"  Liquidity: ${data.get('liquidity_usd', 'N/A'):,.2f}")
                print(f"  Volume (24h): ${data.get('volume_24h', 'N/A'):,.2f}")
            else:
                print("  No data found.")

    asyncio.run(test())
