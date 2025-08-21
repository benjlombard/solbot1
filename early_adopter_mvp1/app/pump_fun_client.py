import aiohttp
import asyncio
import logging
from typing import Dict, Optional

# Setting up a default logger in case one isn't provided
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PumpFunClient:
    """
    An asynchronous, self-contained client for interacting with the Pump.fun API.
    This client uses the `aiohttp` library.
    """
    
    def __init__(self, logger_instance: Optional[logging.Logger] = None):
        """
        Initializes the PumpFunClient.
        Args:
            logger_instance: An optional logger instance. If not provided, a default logger is used.
        """
        self.base_url = "https://frontend-api-v3.pump.fun"
        self.logger = logger_instance if logger_instance else logger

    async def get_token_data(self, session: aiohttp.ClientSession, token_address: str) -> Optional[Dict]:
        """
        Asynchronously fetches token data from the Pump.fun API for a given token address.

        Args:
            session: An `aiohttp.ClientSession` object for making the request.
            token_address: The mint address of the token.

        Returns:
            A dictionary containing the token's data from the API, or None if the request fails.
        """
        url = f"{self.base_url}/coins/{token_address}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json'
        }
        
        try:
            async with session.get(url, headers=headers, timeout=20) as response:
                # Raise an HTTPError for bad responses (4xx or 5xx)
                response.raise_for_status()
                data = await response.json()
                self.logger.debug(f"Successfully fetched data for {token_address}")
                return data

        except asyncio.TimeoutError:
            self.logger.warning(f"Timeout error fetching {token_address}")
        except aiohttp.ClientResponseError as http_err:
            self.logger.warning(f"HTTP error fetching {token_address}: {http_err.status} {http_err.message}")
        except aiohttp.ClientError as client_err:
            self.logger.error(f"Client error for {token_address}: {client_err}")
        except Exception as e:
            self.logger.error(f"An unexpected error occurred while fetching data for {token_address}: {e}", exc_info=True)
            
        return None