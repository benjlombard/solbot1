"""
Batch Processor - Version Corrigée
Corrections des problèmes de queue et d'optimisation des appels API
"""
import asyncio
import aiohttp
import time
import logging
from typing import List, Dict, Set, Optional, Tuple
from datetime import datetime

from ..models.token_data import TokenData, BatchResult
from ..database.token_repository import TokenRepository
from ..database.queue_repository import QueueRepository
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
    
    async def process_tokens_batch(self, token_addresses: List[str], update_queue: bool = True) -> int:
        """
        Process a batch of tokens asynchronously
        
        Args:
            token_addresses: List of token addresses to process
            update_queue: Whether to update queue status (True for new tokens, False for price updates)
            
        Returns:
            Number of successfully processed tokens
        """
        if not token_addresses:
            return 0
        
        start_time = time.time()
        batch_type = "new tokens" if update_queue else "price updates"
        self.logger.info(f"🔄 Starting batch processing for {len(token_addresses)} {batch_type}")
        
        try:
            # 1. Fetch token data from APIs - OPTIMISÉ
            tokens_data = await self._fetch_tokens_data_optimized(token_addresses)
            
            # 2. Process database operations - CORRIGÉ
            successful_count = await self._process_database_operations(
                token_addresses, tokens_data, update_queue
            )
            
            # 3. Update statistics
            processing_time = time.time() - start_time
            self._update_stats(len(token_addresses), successful_count, processing_time)
            
            self.logger.info(
                f"✅ Batch processing completed: {successful_count}/{len(token_addresses)} "
                f"successful in {processing_time:.2f}s ({batch_type})"
            )
            
            return successful_count
            
        except Exception as e:
            self.logger.error(f"❌ Error in batch processing: {e}", exc_info=True)
            # Update queue status for failed tokens SEULEMENT si c'est un batch de nouveaux tokens
            if update_queue:
                for token_addr in token_addresses:
                    self.queue_repo.update_token_status(token_addr, success=False, error_message=str(e))
            return 0
    
    async def _fetch_tokens_data_optimized(self, token_addresses: List[str]) -> Dict[str, TokenData]:
        """
        OPTIMISATION : Fetch token data with efficient batch usage
        """
        self.logger.info(f"📡 Starting OPTIMIZED API fetch for {len(token_addresses)} tokens")
        
        all_tokens_data = {}
        max_batch_size = min(30, self.config.apis.dexscreener_batch_size)
        
        # Create aiohttp session
        timeout = aiohttp.ClientTimeout(total=self.config.rpc.timeout)
        
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Process tokens in batches of 30 (DexScreener limit)
            batch_count = 0
            for i in range(0, len(token_addresses), max_batch_size):
                batch = token_addresses[i:i + max_batch_size]
                batch_count += 1
                
                self.logger.debug(f"📡 Processing batch {batch_count}: {len(batch)} tokens")
                
                # Try batch API first
                batch_start = time.time()
                batch_data = await self.dex_client.get_tokens_batch_async(
                    session=session,
                    token_addresses=batch,
                    batch_size=max_batch_size
                )
                batch_duration = time.time() - batch_start
                
                self.logger.info(
                    f"📡 Batch {batch_count} completed in {batch_duration:.2f}s: "
                    f"found {len(batch_data)}/{len(batch)} tokens"
                )
                
                all_tokens_data.update(batch_data)
                
                # Identify missing tokens for individual fallback
                missing_tokens = set(batch) - set(batch_data.keys())
                
                if missing_tokens:
                    self.logger.info(f"🔍 {len(missing_tokens)} tokens missing from batch, trying individual requests")
                    
                    # LIMITATION des appels individuels pour éviter l'explosion
                    max_individual_attempts = min(5, len(missing_tokens))  # Limiter à 5 maximum
                    limited_missing = list(missing_tokens)[:max_individual_attempts]
                    
                    if len(missing_tokens) > max_individual_attempts:
                        self.logger.warning(
                            f"⚠️ Limiting individual requests to {max_individual_attempts}/{len(missing_tokens)} "
                            f"missing tokens to prevent API overload"
                        )
                    
                    # Try individual requests for limited missing tokens
                    individual_start = time.time()
                    individual_results = await self._fetch_individual_tokens_limited(session, limited_missing)
                    individual_duration = time.time() - individual_start
                    
                    self.logger.info(
                        f"🔍 Individual requests completed in {individual_duration:.2f}s: "
                        f"found {len(individual_results)}/{len(limited_missing)} tokens"
                    )
                    
                    all_tokens_data.update(individual_results)
                
                # Rate limiting between batches
                if i + max_batch_size < len(token_addresses):
                    await asyncio.sleep(0.5)  # 500ms pause between batches
        
        found_count = len(all_tokens_data)
        missing_count = len(token_addresses) - found_count
        
        self.logger.info(f"📊 OPTIMIZED API Results: {found_count} found, {missing_count} missing")
        return all_tokens_data
    
    async def _fetch_individual_tokens_limited(
        self, 
        session: aiohttp.ClientSession, 
        token_addresses: List[str]
    ) -> Dict[str, TokenData]:
        """Fetch tokens individually with strict limits to prevent API overload"""
        results = {}
        
        # LIMITATION stricte de concurrence
        semaphore = asyncio.Semaphore(2)  # Maximum 2 requêtes simultanées
        
        async def fetch_single_token_safe(token_addr: str) -> Tuple[str, Optional[TokenData]]:
            async with semaphore:
                try:
                    # Timeout court pour éviter les blocages
                    response = await asyncio.wait_for(
                        self.dex_client.make_async_request(session, f"dex/tokens/{token_addr}"),
                        timeout=8.0
                    )
                    
                    if response.success and response.data:
                        token_data = self.dex_client._parse_single_token_response(
                            token_addr, response.data
                        )
                        if token_data:
                            self.logger.debug(f"✅ Individual success: {token_addr[:8]}...")
                            return token_addr, token_data
                    
                    self.logger.debug(f"❌ Individual no data: {token_addr[:8]}...")
                    return token_addr, None
                    
                except asyncio.TimeoutError:
                    self.logger.debug(f"⏰ Individual timeout: {token_addr[:8]}...")
                    return token_addr, None
                except Exception as e:
                    self.logger.debug(f"❌ Individual error {token_addr[:8]}...: {e}")
                    return token_addr, None
        
        # Process with delay between requests
        for i, token_addr in enumerate(token_addresses):
            try:
                result = await fetch_single_token_safe(token_addr)
                if result[1]:  # Si token_data n'est pas None
                    results[result[0]] = result[1]
                
                # Délai entre les requêtes individuelles
                if i < len(token_addresses) - 1:
                    await asyncio.sleep(1.0)
                    
            except Exception as e:
                self.logger.debug(f"Error in individual fetch for {token_addr}: {e}")
                continue
        
        return results
    
    async def _process_database_operations(
        self, 
        token_addresses: List[str], 
        tokens_data: Dict[str, TokenData],
        update_queue: bool
    ) -> int:
        """
        CORRECTION : Process database operations with queue handling logic
        
        Args:
            token_addresses: Original list of token addresses
            tokens_data: Token data from APIs
            update_queue: Whether to update queue status
            
        Returns:
            Number of successful operations
        """
        self.logger.info(f"💾 Starting database operations for {len(token_addresses)} tokens (queue_update={update_queue})")
        
        # Create database tasks
        db_tasks = []
        tokens_with_data = 0
        tokens_without_data = 0

        for token_address in token_addresses:
            token_data = tokens_data.get(token_address)
            
            if token_data:
                tokens_with_data += 1
                # Token data found - upsert to database
                task = asyncio.to_thread(
                    self._upsert_token_with_conditional_queue_update, 
                    token_address, 
                    token_data, 
                    update_queue
                )
            else:
                tokens_without_data += 1
                # No token data found
                task = asyncio.to_thread(
                    self._handle_missing_token_with_conditional_queue_update, 
                    token_address, 
                    update_queue
                )
            
            db_tasks.append(task)

        self.logger.info(f"💾 Created {len(db_tasks)} database tasks: {tokens_with_data} upserts, {tokens_without_data} missing")

        # Execute database operations
        db_start = time.time()
        db_results = await asyncio.gather(*db_tasks, return_exceptions=True)
        db_duration = time.time() - db_start
        
        self.logger.info(f"💾 Database operations completed in {db_duration:.2f}s")

        # Count successful operations
        successful_count = 0
        for i, result in enumerate(db_results):
            token_addr = token_addresses[i]
            
            if isinstance(result, Exception):
                self.logger.error(f"💾 Database operation failed for {token_addr[:8]}...: {result}")
                # Update queue only if this is a queue-managed token
                if update_queue:
                    self.queue_repo.update_token_status(token_addr, success=False, error_message=str(result))
            elif result:
                successful_count += 1
            else:
                self.logger.warning(f"💾 Database operation returned False for {token_addr[:8]}...")
                # Update queue only if this is a queue-managed token
                if update_queue:
                    self.queue_repo.update_token_status(token_addr, success=False, error_message="Database operation failed")
        
        self.logger.debug(f"💾 Database operations: {successful_count}/{len(token_addresses)} successful")
        return successful_count
    
    def _upsert_token_with_conditional_queue_update(
        self, 
        token_address: str, 
        token_data: TokenData, 
        update_queue: bool
    ) -> bool:
        """
        CORRECTION : Upsert token and conditionally update queue status
        """
        try:
            # Upsert token to database
            success = self.token_repo.upsert_token(token_data)
            
            # Update queue status ONLY if this token came from the queue
            if update_queue and success:
                queue_success = self.queue_repo.update_token_status(token_address, success=True)
                if not queue_success:
                    self.logger.warning(f"💾 Queue update failed for {token_address[:8]}... after successful upsert")
            elif update_queue and not success:
                self.queue_repo.update_token_status(
                    token_address, 
                    success=False, 
                    error_message="Upsert failed"
                )
            
            if success:
                operation_type = "queue token" if update_queue else "price update"
                self.logger.debug(f"✅ Successfully processed {token_address[:8]}... ({operation_type})")
            
            return success
            
        except Exception as e:
            self.logger.error(f"❌ Error upserting token {token_address[:8]}...: {e}")
            if update_queue:
                self.queue_repo.update_token_status(token_address, success=False, error_message=str(e))
            return False
    
    def _handle_missing_token_with_conditional_queue_update(
        self, 
        token_address: str, 
        update_queue: bool
    ) -> bool:
        """
        CORRECTION : Handle missing token and conditionally update queue status
        """
        try:
            # Check if token exists
            token_exists = self.token_repo.token_exists(token_address)
            
            if token_exists:
                # Token exists, mark as no data
                success = self.token_repo.mark_token_no_data(token_address, increment_attempts=True)
                
                if update_queue:
                    if success:
                        queue_success = self.queue_repo.update_token_status(token_address, success=True)
                        self.logger.debug(f"📝 Marked existing token as no data: {token_address[:8]}... (queue managed)")
                    else:
                        self.queue_repo.update_token_status(
                            token_address, 
                            success=False, 
                            error_message="Failed to mark as no data"
                        )
                else:
                    self.logger.debug(f"📝 Marked existing token as no data: {token_address[:8]}... (price update)")
                
                return success
            else:
                # Token doesn't exist, create stub
                success = self.token_repo.create_token_stub(token_address)
                
                if update_queue:
                    if success:
                        queue_success = self.queue_repo.update_token_status(token_address, success=True)
                        self.logger.debug(f"📝 Created stub for {token_address[:8]}... (queue managed)")
                    else:
                        self.queue_repo.update_token_status(
                            token_address, 
                            success=False, 
                            error_message="Failed to create stub"
                        )
                else:
                    self.logger.debug(f"📝 Created stub for {token_address[:8]}... (price update)")
                
                return success
                
        except Exception as e:
            self.logger.error(f"❌ Exception handling missing token {token_address[:8]}...: {e}")
            if update_queue:
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