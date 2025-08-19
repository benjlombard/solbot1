"""
Batch Processor - Version Corrigée
PROBLÈME IDENTIFIÉ : Confusion entre tokens de queue et price updates
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
    
    async def process_new_tokens_from_queue(self, token_addresses: List[str]) -> int:
        """
        Process NEW tokens FROM QUEUE - ces tokens DOIVENT être dans la queue
        
        Args:
            token_addresses: List of token addresses from queue
            
        Returns:
            Number of successfully processed tokens
        """
        if not token_addresses:
            return 0
        
        start_time = time.time()
        self.logger.info(f"🔄 Processing {len(token_addresses)} NEW tokens from QUEUE")
        
        try:
            # 1. Fetch token data from APIs
            tokens_data = await self._fetch_tokens_data_optimized(token_addresses)
            
            # 2. Process database operations WITH queue updates
            successful_count = await self._process_database_operations(
                token_addresses, tokens_data, update_queue=True  # IMPORTANT: TRUE pour la queue
            )
            
            # 3. Update statistics
            processing_time = time.time() - start_time
            self._update_stats(len(token_addresses), successful_count, processing_time)
            
            self.logger.info(
                f"✅ NEW tokens processing completed: {successful_count}/{len(token_addresses)} "
                f"successful in {processing_time:.2f}s"
            )
            
            return successful_count
            
        except Exception as e:
            self.logger.error(f"❌ Error processing NEW tokens from queue: {e}", exc_info=True)
            # Update queue status for failed tokens - ils sont censés être dans la queue
            for token_addr in token_addresses:
                try:
                    self.queue_repo.update_token_status(token_addr, success=False, error_message=str(e))
                except Exception as queue_error:
                    self.logger.error(f"❌ Failed to update queue for {token_addr[:8]}...: {queue_error}")
            return 0
    
    async def process_price_updates(self, token_addresses: List[str]) -> int:
        """
        Process PRICE UPDATES for existing tokens - ces tokens ne sont PAS dans la queue
        
        Args:
            token_addresses: List of token addresses needing price updates
            
        Returns:
            Number of successfully processed tokens
        """
        if not token_addresses:
            return 0
        
        start_time = time.time()
        self.logger.info(f"🔄 Processing {len(token_addresses)} PRICE UPDATES (not from queue)")
        
        try:
            # 1. Fetch token data from APIs
            tokens_data = await self._fetch_tokens_data_optimized(token_addresses)
            
            # 2. Process database operations WITHOUT queue updates
            successful_count = await self._process_database_operations(
                token_addresses, tokens_data, update_queue=False  # IMPORTANT: FALSE pour price updates
            )
            
            # 3. Update statistics
            processing_time = time.time() - start_time
            self._update_stats(len(token_addresses), successful_count, processing_time)
            
            self.logger.info(
                f"✅ Price updates completed: {successful_count}/{len(token_addresses)} "
                f"successful in {processing_time:.2f}s"
            )
            
            return successful_count
            
        except Exception as e:
            self.logger.error(f"❌ Error processing price updates: {e}", exc_info=True)
            # Pas de mise à jour de queue - ces tokens ne sont pas dans la queue
            return 0
    
    # DEPRECATED: Méthode ambiguë à ne plus utiliser
    async def process_tokens_batch(self, token_addresses: List[str], update_queue: bool = True) -> int:
        """
        DEPRECATED: Utilisez process_new_tokens_from_queue() ou process_price_updates()
        """
        self.logger.warning("⚠️ process_tokens_batch() is deprecated. Use specific methods instead.")
        
        if update_queue:
            return await self.process_new_tokens_from_queue(token_addresses)
        else:
            return await self.process_price_updates(token_addresses)
    
    async def _fetch_tokens_data_optimized(self, token_addresses: List[str]) -> Dict[str, TokenData]:
        """
        Fetch token data with efficient batch usage
        """
        self.logger.debug(f"📡 Starting API fetch for {len(token_addresses)} tokens")
        
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
                
                self.logger.debug(
                    f"📡 Batch {batch_count} completed in {batch_duration:.2f}s: "
                    f"found {len(batch_data)}/{len(batch)} tokens"
                )
                
                all_tokens_data.update(batch_data)
                
                # Rate limiting between batches
                if i + max_batch_size < len(token_addresses):
                    await asyncio.sleep(0.5)  # 500ms pause between batches

            # Fallback for missing tokens, inside the session block
            found_count = len(all_tokens_data)
            missing_count = len(token_addresses) - found_count
            self.logger.debug(f"📊 Batch API Results: {found_count} found, {missing_count} missing")

            if missing_count > 0:
                missing_addresses = set(token_addresses) - set(all_tokens_data.keys())
                self.logger.info(f"📡 Performing individual fallback for {len(missing_addresses)} missing tokens...")
                
                fallback_tasks = []
                for addr in missing_addresses:
                    fallback_tasks.append(self.dex_client.get_token_data_async(session, addr))
                
                fallback_results = await asyncio.gather(*fallback_tasks, return_exceptions=True)

                fallback_found_count = 0
                for i, result in enumerate(fallback_results):
                    if isinstance(result, TokenData):
                        all_tokens_data[result.address] = result
                        fallback_found_count += 1
                    elif isinstance(result, Exception):
                        # Log the exception if needed
                        pass
                
                self.logger.info(f"📡 Fallback completed: found {fallback_found_count}/{len(missing_addresses)} additional tokens.")

        final_found_count = len(all_tokens_data)
        final_missing_count = len(token_addresses) - final_found_count
        self.logger.debug(f"📊 Final API Results: {final_found_count} found, {final_missing_count} missing")
        
        return all_tokens_data
    
    async def _process_database_operations(
        self, 
        token_addresses: List[str], 
        tokens_data: Dict[str, TokenData],
        update_queue: bool
    ) -> int:
        """
        Process database operations with queue handling logic
        
        Args:
            token_addresses: Original list of token addresses
            tokens_data: Token data from APIs
            update_queue: Whether to update queue status (True for new tokens, False for price updates)
            
        Returns:
            Number of successful operations
        """
        self.logger.debug(f"💾 Processing DB operations for {len(token_addresses)} tokens (queue_update={update_queue})")
        
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

        self.logger.debug(f"💾 Created {len(db_tasks)} database tasks: {tokens_with_data} upserts, {tokens_without_data} missing")

        # Execute database operations
        db_start = time.time()
        db_results = await asyncio.gather(*db_tasks, return_exceptions=True)
        db_duration = time.time() - db_start
        
        self.logger.debug(f"💾 Database operations completed in {db_duration:.2f}s")

        # Count successful operations
        successful_count = 0
        for i, result in enumerate(db_results):
            token_addr = token_addresses[i]
            
            if isinstance(result, Exception):
                self.logger.error(f"💾 Database operation failed for {token_addr[:8]}...: {result}")
                # Update queue only if this is a queue-managed token
                if update_queue:
                    try:
                        self.queue_repo.update_token_status(token_addr, success=False, error_message=str(result))
                    except Exception as e:
                        self.logger.error(f"❌ Queue update failed for {token_addr[:8]}...: {e}")
            elif result:
                successful_count += 1
            else:
                self.logger.warning(f"💾 Database operation returned False for {token_addr[:8]}...")
                # Update queue only if this is a queue-managed token
                if update_queue:
                    try:
                        self.queue_repo.update_token_status(token_addr, success=False, error_message="Database operation failed")
                    except Exception as e:
                        self.logger.error(f"❌ Queue update failed for {token_addr[:8]}...: {e}")
        
        self.logger.debug(f"💾 Database operations: {successful_count}/{len(token_addresses)} successful")
        return successful_count
    
    def _upsert_token_with_conditional_queue_update(
    self, 
    token_address: str, 
    token_data: TokenData, 
    update_queue: bool
) -> bool:
        """
        Upsert token and conditionally update queue status
        Note: Historization is now handled automatically in token_repo.upsert_token()
        """
        try:
            # L'historisation est maintenant gérée automatiquement dans upsert_token:
            # - AVANT mise à jour pour les tokens existants (capture l'état précédent)
            # - APRÈS insertion pour les nouveaux tokens (capture l'état initial)
            success = self.token_repo.upsert_token(token_data)
            
            # Update queue status ONLY if this token came from the queue
            if update_queue:
                if success:
                    try:
                        queue_success = self.queue_repo.update_token_status(token_address, success=True)
                        if not queue_success:
                            self.logger.warning(f"💾 Queue update failed for {token_address[:8]}... after successful upsert")
                    except Exception as e:
                        self.logger.error(f"❌ Queue update error for {token_address[:8]}...: {e}")
                else:
                    try:
                        self.queue_repo.update_token_status(
                            token_address, 
                            success=False, 
                            error_message="Upsert failed"
                        )
                    except Exception as e:
                        self.logger.error(f"❌ Queue update error for {token_address[:8]}...: {e}")
            
            if success:
                operation_type = "queue token" if update_queue else "price update"
                self.logger.debug(f"✅ Successfully processed {token_address[:8]}... ({operation_type}) with auto-historization")
            
            return success
            
        except Exception as e:
            self.logger.error(f"❌ Error upserting token {token_address[:8]}...: {e}")
            if update_queue:
                try:
                    self.queue_repo.update_token_status(token_address, success=False, error_message=str(e))
                except Exception as queue_error:
                    self.logger.error(f"❌ Queue update error for {token_address[:8]}...: {queue_error}")
            return False
    
    def _handle_missing_token_with_conditional_queue_update(
        self, 
        token_address: str, 
        update_queue: bool
    ) -> bool:
        """
        Handle missing token and conditionally update queue status
        """
        try:
            # Check if token exists
            token_exists = self.token_repo.token_exists(token_address)
            
            if token_exists:
                # Token exists, mark as no data
                success = self.token_repo.mark_token_no_data(
                    token_address,
                    max_attempts=self.config.processing.max_failed_attempts,
                    increment_attempts=True
                )
                
                if update_queue:
                    if success:
                        try:
                            queue_success = self.queue_repo.update_token_status(token_address, success=True)
                            self.logger.debug(f"📝 Marked existing token as no data: {token_address[:8]}... (queue managed)")
                        except Exception as e:
                            self.logger.error(f"❌ Queue update error for {token_address[:8]}...: {e}")
                    else:
                        try:
                            self.queue_repo.update_token_status(
                                token_address, 
                                success=False, 
                                error_message="Failed to mark as no data"
                            )
                        except Exception as e:
                            self.logger.error(f"❌ Queue update error for {token_address[:8]}...: {e}")
                else:
                    self.logger.debug(f"📝 Marked existing token as no data: {token_address[:8]}... (price update)")
                
                return success
            else:
                # Token doesn't exist, create stub
                success = self.token_repo.create_token_stub(
                    token_address,
                    max_attempts=self.config.processing.max_failed_attempts
                )
                
                if update_queue:
                    if success:
                        try:
                            queue_success = self.queue_repo.update_token_status(token_address, success=True)
                            self.logger.debug(f"📝 Created stub for {token_address[:8]}... (queue managed)")
                        except Exception as e:
                            self.logger.error(f"❌ Queue update error for {token_address[:8]}...: {e}")
                    else:
                        try:
                            self.queue_repo.update_token_status(
                                token_address, 
                                success=False, 
                                error_message="Failed to create stub"
                            )
                        except Exception as e:
                            self.logger.error(f"❌ Queue update error for {token_address[:8]}...: {e}")
                else:
                    self.logger.debug(f"📝 Created stub for {token_address[:8]}... (price update)")
                
                return success
                
        except Exception as e:
            self.logger.error(f"❌ Exception handling missing token {token_address[:8]}...: {e}")
            if update_queue:
                try:
                    self.queue_repo.update_token_status(token_address, success=False, error_message=str(e))
                except Exception as queue_error:
                    self.logger.error(f"❌ Queue update error for {token_address[:8]}...: {queue_error}")
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