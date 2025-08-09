#!/usr/bin/env python3
"""
API pour récupérer les taux de change USD/EUR
Utilise l'API Frankfurter pour les taux en temps réel
"""

import aiohttp
import asyncio
from typing import Optional

# Assuming a logger is available from the project's core modules.
# If not, a standard logger can be configured here.
try:
    from core.logger import get_logger
    logger = get_logger(__name__)
except (ImportError, ModuleNotFoundError):
    import logging
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO)

# Configuration API
FRANKFURTER_API_URL = "https://api.frankfurter.app/latest?from=USD&to=EUR"
DEFAULT_USD_TO_EUR_RATE = 0.92


async def get_usd_to_eur_rate() -> float:
    """
    Fetches the latest USD to EUR exchange rate from the Frankfurter API.
    
    Returns:
        The current USD to EUR exchange rate, or a default value if the API call fails.
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(FRANKFURTER_API_URL, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    rate = data.get('rates', {}).get('EUR')
                    if rate:
                        logger.info(f"Successfully fetched USD to EUR rate: {rate}")
                        return float(rate)
                
                logger.warning(f"Failed to fetch EUR rate from Frankfurter API, status: {response.status}")
    
    except asyncio.TimeoutError:
        logger.warning("Timeout when fetching EUR exchange rate from Frankfurter API.")
    except Exception as e:
        logger.error(f"Error fetching EUR exchange rate: {e}", exc_info=True)
    
    logger.warning(f"Using default USD to EUR rate: {DEFAULT_USD_TO_EUR_RATE}")
    return DEFAULT_USD_TO_EUR_RATE


def get_usd_to_eur_rate_sync() -> float:
    """
    Version synchrone pour éviter les complications async dans certains contextes
    """
    try:
        import requests
        response = requests.get(FRANKFURTER_API_URL, timeout=5)
        if response.status_code == 200:
            data = response.json()
            rate = data.get('rates', {}).get('EUR')
            if rate:
                logger.info(f"Successfully fetched USD to EUR rate (sync): {rate}")
                return float(rate)
        
        logger.warning(f"Failed to fetch EUR rate (sync), status: {response.status_code}")
    except Exception as e:
        logger.error(f"Error fetching EUR exchange rate (sync): {e}")
    
    logger.warning(f"Using default USD to EUR rate: {DEFAULT_USD_TO_EUR_RATE}")
    return DEFAULT_USD_TO_EUR_RATE


if __name__ == '__main__':
    async def test_rate_fetch():
        print("Fetching current USD to EUR rate...")
        rate = await get_usd_to_eur_rate()
        print(f"The current USD to EUR rate is: {rate}")
        
        # Test version synchrone
        print("\nTesting synchronous version...")
        rate_sync = get_usd_to_eur_rate_sync()
        print(f"Synchronous rate: {rate_sync}")
    
    asyncio.run(test_rate_fetch())