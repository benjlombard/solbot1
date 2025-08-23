import asyncio
import aiohttp
import logging
from typing import Dict, List, Optional, Any

class RugCheckClient:
    """
    Client for RugCheck.xyz API with specialized methods for token security analysis
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None, system_monitor: Optional['SystemMonitor'] = None):
        self.base_url = "https://api.rugcheck.xyz/v1"
        self.logger = logger or logging.getLogger(__name__)
        self.system_monitor = system_monitor
    
    async def get_token_report_async(
        self, 
        session: aiohttp.ClientSession, 
        token_address: str
    ) -> Optional[Dict]:
        """
        Get comprehensive security report asynchronously
        
        Args:
            session: aiohttp session
            token_address: Token address to analyze
            
        Returns:
            Complete security report or None if not available
        """
        if self.system_monitor:
            self.system_monitor.record_api_call('rugcheck')

        headers = {}
        headers['Authorization'] = 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3NTYxMzQ0NzUsImlkIjoiRWdlQTFoWkg2djdDUXZOcmRLTXlSTkVNRlVnWW5iaXJ2YVBSNHJNVXdhS3cifQ.dGe-b-NgnP-aJnHHzW_pH04jDqfg1GfAozi_c4VZDE4'

        url = f"{self.base_url}/tokens/{token_address}/report"
        try:
            async with session.get(url, timeout=45.0) as response:
                if response.status == 200:
                    data = await response.json()
                    self.logger.debug(f"✅ Got RugCheck report for {token_address[:8]}...")
                    return data
                else:
                    self.logger.debug(f"RugCheck report failed for {token_address[:8]}...: status {response.status}")
                    return None
        except Exception as e:
            self.logger.error(f"Error fetching RugCheck report for {token_address[:8]}...: {e}")
            return None
