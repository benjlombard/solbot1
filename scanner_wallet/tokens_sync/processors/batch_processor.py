"""
Batch Processor
Handles asynchronous batch processing of tokens using multiple API clients.
"""
import asyncio
import aiohttp
import time
import logging
from typing import List, Dict, Set, Optional, Tuple
from datetime import datetime

from ..models.token_data import TokenData, BatchResult
from ..database.token_repository import TokenRepository, QueueRepository
from ..api_clients.dexscreener_client import DexScreenerClient
from ..api_clients.base_client import ApiResponse


class BatchProcessor:
    """
    Handles batch processing of tokens with async API calls and database operations
    """
    
    def __init__(
        self,
        dex_client: DexScreenerClient,
        token_repo: TokenRepository,
        queue_repo: QueueRepository,
        config,
        logger: Optional[logging.Logger] = None
    ):
        self.dex_client = dex_client
        self.token_repo = token_repo
        self.queue_repo = queue_repo
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        
        # Processing statistics
        self.stats = {
            'total_processed': 0,
            'successful': 0,
            'failed': 0,
            'tokens_found': 0,
            'tokens_missing': 0,
            'processing_time': 0.0
        }
    
    async def process_tokens_batch(self, token_addresses: List[str]) -> int:
        """
        Process a batch of tokens asynchronously
        
        Args:
            token_addresses: List of token addresses to process
            
        Returns:
            Number of successfully processed tokens
        """
        if not token_addresses:
            return 0
        
        start_time = time.time()
        self.logger.info(f"🔄 Starting batch processing for {len(token_addresses)} tokens")
        
        try:
            # 1. Fetch token data from APIs
            tokens_data = await self._fetch_tokens_data_async(token_addresses)
            
            # 2. Process database operations
            successful_count = await self._process_database_operations(token_addresses, tokens_data)
            
            # 3. Update statistics
            processing_time = time.time() - start_time
            self._update_stats(len(token_addresses), successful_count, processing_time)
            
            self.logger.info(
                f"✅ Batch processing completed: {successful_count}/{len(token_addresses)} "
                f"successful in {processing_time:.2f}s"
            )
            
            return successful_count
            
        except Exception as e:
            self.logger.error(f"❌ Error in batch processing: {e}", exc_info=True)
            # Update queue status for failed tokens
            for token_addr in token_addresses:
                self.queue_repo.update_token_status(token_addr, success=False, error_message=str(e))
            return 0
    
    async def _fetch_tokens_data_async(self, token_addresses: List[str]) -> Dict[str, TokenData]:
        """
        Fetch token data from APIs asynchronously
        
        Args:
            token_addresses: List of token addresses
            
        Returns:
            Dictionary mapping token_address -> TokenData
        """
        self.logger.debug(f"📡 Fetching data for {len(token_addresses)} tokens via API")
        
        # Create aiohttp session with timeout
        timeout = aiohttp.ClientTimeout(total=self.config.rpc.timeout)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Use DexScreener batch API
            tokens_data = await self.dex_client.get_tokens_batch_async(
                session=session,
                token_addresses=token_addresses,
                batch_size=self.config.apis.dexscreener_batch_size
            )
            
            # Handle missing tokens with individual fallback
            missing_tokens = set(token_addresses) - set(tokens_data.keys())
            
            if missing_tokens:
                self.logger.warning(f"🔍 {len(missing_tokens)} tokens missing from batch, trying individual fallback")
                
                # Try individual requests for missing tokens
                individual_results = await self._fetch_individual_tokens(session, list(missing_tokens))
                tokens_data.update(individual_results)
        
        found_count = len(tokens_data)
        missing_count = len(token_addresses) - found_count
        
        self.logger.info(f"📊 API Results: {found_count} found, {missing_count} missing")
        
        return tokens_data
    
    async def _fetch_individual_tokens(
    self, 
    session: aiohttp.ClientSession, 
    token_addresses: List[str]
) -> Dict[str, TokenData]:
        """Fetch tokens individually as fallback avec timeout optimisé"""
        results = {}
        
        # CORRECTION: Réduire la concurrence pour éviter les timeouts
        semaphore = asyncio.Semaphore(3)  # Réduit de 5 à 3
        
        async def fetch_single_token(token_addr: str) -> Tuple[str, Optional[TokenData]]:
            async with semaphore:
                try:
                    # CORRECTION: Timeout plus court pour les requêtes individuelles
                    response = await asyncio.wait_for(
                        self.dex_client.make_async_request(session, f"dex/tokens/{token_addr}"),
                        timeout=8.0  # Réduit de 30s à 8s
                    )
                    
                    if response.success and response.data:
                        token_data = self.dex_client._parse_single_token_response(
                            token_addr, response.data
                        )
                        if token_data:
                            self.logger.debug(f"✅ Individual success: {token_addr[:8]}...")
                            return token_addr, token_data
                    
                    self.logger.debug(f"❌ Individual failed: {token_addr[:8]}...")
                    return token_addr, None
                    
                except asyncio.TimeoutError:
                    self.logger.debug(f"⏰ Individual timeout: {token_addr[:8]}...")
                    return token_addr, None
                except Exception as e:
                    self.logger.debug(f"❌ Individual error {token_addr[:8]}...: {e}")
                    return token_addr, None
        
        # CORRECTION: Traitement par plus petits groupes
        chunk_size = 10
        for i in range(0, len(token_addresses), chunk_size):
            chunk = token_addresses[i:i + chunk_size]
            tasks = [fetch_single_token(addr) for addr in chunk]
            
            try:
                chunk_results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=30.0
                )
                
                for result in chunk_results:
                    if isinstance(result, Exception):
                        continue
                    token_addr, token_data = result
                    if token_data:
                        results[token_addr] = token_data
                        
            except asyncio.TimeoutError:
                self.logger.warning(f"Chunk timeout for {len(chunk)} tokens")
                
            # Pause entre chunks pour éviter le rate limiting
            await asyncio.sleep(0.5)
        
        return results
    
    async def _process_database_operations(
        self, 
        token_addresses: List[str], 
        tokens_data: Dict[str, TokenData]
    ) -> int:
        """
        Process database operations for all tokens
        
        Args:
            token_addresses: Original list of token addresses
            tokens_data: Token data from APIs
            
        Returns:
            Number of successful operations
        """
        self.logger.debug(f"💾 Processing database operations for {len(token_addresses)} tokens")
        
        # Create database tasks
        db_tasks = []
        for token_address in token_addresses:
            token_data = tokens_data.get(token_address)
            
            if token_data:
                # Token data found - upsert to database
                task = asyncio.to_thread(self._upsert_token_with_queue_update, token_address, token_data)
            else:
                # No token data found - create stub or mark as no data
                task = asyncio.to_thread(self._handle_missing_token, token_address)
            
            db_tasks.append(task)
        
        # Execute database operations
        db_results = await asyncio.gather(*db_tasks, return_exceptions=True)
        
        # Count successful operations
        successful_count = 0
        for i, result in enumerate(db_results):
            token_addr = token_addresses[i]
            
            if isinstance(result, Exception):
                self.logger.error(f"💾 Database operation failed for {token_addr[:8]}...: {result}")
                self.queue_repo.update_token_status(token_addr, success=False, error_message=str(result))
            elif result:
                successful_count += 1
            else:
                self.logger.warning(f"💾 Database operation returned False for {token_addr[:8]}...")
                self.queue_repo.update_token_status(token_addr, success=False, error_message="Database operation failed")
        
        self.logger.debug(f"💾 Database operations: {successful_count}/{len(token_addresses)} successful")
        
        return successful_count
    
    def _upsert_token_with_queue_update(self, token_address: str, token_data: TokenData) -> bool:
        """
        Upsert token to database and update queue status
        
        Args:
            token_address: Token address
            token_data: Token data to upsert
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Upsert token to database
            success = self.token_repo.upsert_token(token_data)
            
            # Update queue status
            if success:
                self.queue_repo.update_token_status(token_address, success=True)
                self.logger.debug(f"✅ Successfully upserted {token_address[:8]}... ({token_data.symbol})")
            else:
                self.queue_repo.update_token_status(
                    token_address, 
                    success=False, 
                    error_message="Upsert failed"
                )
                self.logger.warning(f"❌ Failed to upsert {token_address[:8]}...")
            
            return success
            
        except Exception as e:
            self.logger.error(f"❌ Error upserting token {token_address[:8]}...: {e}")
            self.queue_repo.update_token_status(token_address, success=False, error_message=str(e))
            return False
    
    def _handle_missing_token(self, token_address: str) -> bool:
        """
        Handle token with no data found
        
        Args:
            token_address: Token address
            
        Returns:
            True if handled successfully, False otherwise
        """
        try:
            # Create stub entry or mark as no data
            success = self.token_repo.create_token_stub(token_address)
            
            # Update queue status
            if success:
                self.queue_repo.update_token_status(token_address, success=True)
                self.logger.debug(f"📝 Created stub for {token_address[:8]}...")
            else:
                self.queue_repo.update_token_status(
                    token_address, 
                    success=False, 
                    error_message="Failed to create stub"
                )
                self.logger.warning(f"❌ Failed to create stub for {token_address[:8]}...")
            
            return success
            
        except Exception as e:
            self.logger.error(f"❌ Error handling missing token {token_address[:8]}...: {e}")
            self.queue_repo.update_token_status(token_address, success=False, error_message=str(e))
            return False
    
    def _update_stats(self, total_tokens: int, successful_tokens: int, processing_time: float):
        """Update processing statistics"""
        self.stats['total_processed'] += total_tokens
        self.stats['successful'] += successful_tokens
        self.stats['failed'] += (total_tokens - successful_tokens)
        self.stats['processing_time'] += processing_time
    
    def get_batch_statistics(self) -> Dict:
        """Get current batch processing statistics"""
        stats = self.stats.copy()
        
        # Calculate derived metrics
        if stats['total_processed'] > 0:
            stats['success_rate'] = (stats['successful'] / stats['total_processed']) * 100
            stats['avg_processing_time'] = stats['processing_time'] / stats['total_processed']
        else:
            stats['success_rate'] = 0.0
            stats['avg_processing_time'] = 0.0
        
        return stats
    
    def reset_statistics(self):
        """Reset processing statistics"""
        self.stats = {
            'total_processed': 0,
            'successful': 0,
            'failed': 0,
            'tokens_found': 0,
            'tokens_missing': 0,
            'processing_time': 0.0
        }
        
        self.logger.debug("📊 Batch processor statistics reset")


class EnhancedBatchProcessor(BatchProcessor):
    """
    Enhanced batch processor with additional capabilities
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.processing_history = []
        self.max_history_size = 100
    
    async def process_tokens_batch_with_retry(
        self, 
        token_addresses: List[str], 
        max_retries: int = 2
    ) -> int:
        """
        Process tokens batch with retry logic for failed tokens
        
        Args:
            token_addresses: List of token addresses
            max_retries: Maximum retry attempts
            
        Returns:
            Number of successfully processed tokens
        """
        remaining_tokens = token_addresses.copy()
        total_successful = 0
        
        for attempt in range(max_retries + 1):
            if not remaining_tokens:
                break
            
            self.logger.info(
                f"🔄 Batch attempt {attempt + 1}/{max_retries + 1} "
                f"for {len(remaining_tokens)} tokens"
            )
            
            # Process current batch
            successful_count = await self.process_tokens_batch(remaining_tokens)
            total_successful += successful_count
            
            # If last attempt or all successful, break
            if attempt == max_retries or successful_count == len(remaining_tokens):
                break
            
            # Identify failed tokens for retry
            # This would require tracking which specific tokens failed
            # For simplicity, we'll retry all on failure
            if successful_count < len(remaining_tokens):
                failed_count = len(remaining_tokens) - successful_count
                self.logger.warning(
                    f"⚠️ {failed_count} tokens failed, will retry in attempt {attempt + 2}"
                )
                
                # Wait before retry
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
        
        return total_successful
    
    def add_to_history(self, batch_info: Dict):
        """Add batch processing info to history"""
        batch_info['timestamp'] = datetime.now()
        self.processing_history.append(batch_info)
        
        # Trim history if too large
        if len(self.processing_history) > self.max_history_size:
            self.processing_history = self.processing_history[-self.max_history_size:]
    
    def get_processing_trends(self) -> Dict:
        """Get processing trends from history"""
        if not self.processing_history:
            return {}
        
        recent_batches = self.processing_history[-10:]  # Last 10 batches
        
        return {
            'total_batches': len(self.processing_history),
            'recent_avg_success_rate': sum(b.get('success_rate', 0) for b in recent_batches) / len(recent_batches),
            'recent_avg_processing_time': sum(b.get('processing_time', 0) for b in recent_batches) / len(recent_batches),
            'last_batch_time': recent_batches[-1]['timestamp'] if recent_batches else None
        }