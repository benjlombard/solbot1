"""
Token Enricher
Handles token data enrichment from multiple API sources with intelligent routing and fallback.
"""
import asyncio
import aiohttp
import time
import logging
from typing import Dict, List, Optional, Tuple, Set
from datetime import datetime
from dataclasses import dataclass

from ..models.token_data import TokenData, TokenType, TokenTypeResult
from ..api_clients.dexscreener_client import DexScreenerClient
from ..api_clients.pumpfun_client import PumpFunClient
from ..api_clients.rugcheck_client import RugCheckClient
from ..api_clients.solana_tracker_client import SolanaTrackerClient
from ..analyzers.token_type_detector import TokenTypeDetector
from ..analyzers.token_analyzer import TokenAnalyzer


@dataclass
class EnrichmentResult:
    """Result of token enrichment process"""
    token_address: str
    success: bool
    token_data: Optional[TokenData] = None
    error_message: Optional[str] = None
    sources_used: List[str] = None
    enrichment_time: float = 0.0
    
    def __post_init__(self):
        if self.sources_used is None:
            self.sources_used = []


@dataclass
class EnrichmentStrategy:
    """Strategy for enriching a specific type of token"""
    token_type: TokenType
    primary_sources: List[str]
    fallback_sources: List[str]
    require_security_check: bool = True
    max_age_hours: int = 24


class TokenEnricher:
    """
    Comprehensive token data enrichment service with intelligent source routing
    """
    
    def __init__(
        self,
        dex_client: DexScreenerClient,
        pump_client: PumpFunClient,
        rugcheck_client: RugCheckClient,
        solana_tracker_client: Optional[SolanaTrackerClient] = None,
        config=None,
        logger: Optional[logging.Logger] = None
    ):
        self.dex_client = dex_client
        self.pump_client = pump_client
        self.rugcheck_client = rugcheck_client
        self.solana_tracker_client = solana_tracker_client
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        
        # Initialize analyzers
        self.type_detector = TokenTypeDetector(
            dex_client=dex_client,
            pump_client=pump_client,
            logger=logger
        )
        self.token_analyzer = TokenAnalyzer()
        
        # Enrichment strategies
        self.strategies = {
            TokenType.DEX_LISTED: EnrichmentStrategy(
                token_type=TokenType.DEX_LISTED,
                primary_sources=['dexscreener'],
                fallback_sources=['solana_tracker'],
                require_security_check=True
            ),
            TokenType.PUMP_PREBOND: EnrichmentStrategy(
                token_type=TokenType.PUMP_PREBOND,
                primary_sources=['pumpfun'],
                fallback_sources=['dexscreener'],
                require_security_check=True
            ),
            TokenType.PUMP_GRADUATED: EnrichmentStrategy(
                token_type=TokenType.PUMP_GRADUATED,
                primary_sources=['dexscreener', 'pumpfun'],
                fallback_sources=['solana_tracker'],
                require_security_check=True
            ),
            TokenType.UNKNOWN: EnrichmentStrategy(
                token_type=TokenType.UNKNOWN,
                primary_sources=['dexscreener', 'pumpfun'],
                fallback_sources=['solana_tracker'],
                require_security_check=False
            )
        }
        
        # Statistics
        self.stats = {
            'total_enriched': 0,
            'successful_enrichments': 0,
            'failed_enrichments': 0,
            'by_token_type': {},
            'by_source': {},
            'avg_enrichment_time': 0.0,
            'security_checks_performed': 0
        }
        
        self.logger.info("🎯 Token Enricher initialized")
    
    async def enrich_token(self, token_address: str) -> EnrichmentResult:
        """
        Enrich a single token with comprehensive data from multiple sources
        
        Args:
            token_address: Token address to enrich
            
        Returns:
            EnrichmentResult with enriched token data
        """
        start_time = time.time()
        self.logger.debug(f"🔍 Starting enrichment for {token_address[:8]}...")
        
        try:
            # 1. Detect token type
            type_result = await self.type_detector.detect_token_type_async(token_address)
            self.logger.debug(f"🏷️ Token type detected: {type_result.token_type.value} (confidence: {type_result.confidence:.2f})")
            
            # 2. Get enrichment strategy
            strategy = self.strategies.get(type_result.token_type, self.strategies[TokenType.UNKNOWN])
            
            # 3. Enrich using strategy
            token_data = await self._enrich_with_strategy(token_address, strategy, type_result)
            
            if token_data:
                # 4. Security enrichment
                if strategy.require_security_check:
                    token_data = await self._enrich_security_data(token_data)
                
                # 5. Calculate analysis scores
                token_data = self._calculate_analysis_scores(token_data)
                
                # 6. Final data cleaning
                token_data = token_data.clean_symbol_name()
                
                enrichment_time = time.time() - start_time
                
                # Update statistics
                self._update_stats(type_result.token_type, ['multiple'], enrichment_time, True)
                
                self.logger.debug(f"✅ Enrichment completed for {token_address[:8]}... in {enrichment_time:.2f}s")
                
                return EnrichmentResult(
                    token_address=token_address,
                    success=True,
                    token_data=token_data,
                    sources_used=['multiple'],
                    enrichment_time=enrichment_time
                )
            else:
                error_msg = f"No data found from any source for token type {type_result.token_type.value}"
                self.logger.warning(f"❌ {error_msg}")
                
                self._update_stats(type_result.token_type, [], time.time() - start_time, False)
                
                return EnrichmentResult(
                    token_address=token_address,
                    success=False,
                    error_message=error_msg,
                    enrichment_time=time.time() - start_time
                )
                
        except Exception as e:
            error_msg = f"Enrichment error: {e}"
            self.logger.error(f"❌ Error enriching {token_address[:8]}...: {e}")
            
            self._update_stats(TokenType.UNKNOWN, [], time.time() - start_time, False)
            
            return EnrichmentResult(
                token_address=token_address,
                success=False,
                error_message=error_msg,
                enrichment_time=time.time() - start_time
            )
    
    async def enrich_tokens_batch(self, token_addresses: List[str]) -> List[EnrichmentResult]:
        """
        Enrich multiple tokens in batch with optimized API usage
        
        Args:
            token_addresses: List of token addresses to enrich
            
        Returns:
            List of EnrichmentResult objects
        """
        if not token_addresses:
            return []
        
        self.logger.info(f"🔄 Starting batch enrichment for {len(token_addresses)} tokens")
        start_time = time.time()
        
        # Group tokens by type for optimized processing
        token_groups = await self._group_tokens_by_type(token_addresses)
        
        # Process each group with appropriate strategy
        all_results = []
        
        for token_type, addresses in token_groups.items():
            if not addresses:
                continue
                
            self.logger.debug(f"📊 Processing {len(addresses)} {token_type.value} tokens")
            
            strategy = self.strategies.get(token_type, self.strategies[TokenType.UNKNOWN])
            group_results = await self._enrich_group_with_strategy(addresses, strategy)
            all_results.extend(group_results)
        
        # Sort results to match original order
        results_dict = {result.token_address: result for result in all_results}
        ordered_results = [results_dict.get(addr, EnrichmentResult(addr, False, error_message="Not processed")) 
                          for addr in token_addresses]
        
        batch_time = time.time() - start_time
        successful_count = sum(1 for r in ordered_results if r.success)
        
        self.logger.info(f"✅ Batch enrichment completed: {successful_count}/{len(token_addresses)} successful in {batch_time:.2f}s")
        
        return ordered_results
    
    async def _group_tokens_by_type(self, token_addresses: List[str]) -> Dict[TokenType, List[str]]:
        """Group tokens by their detected type for optimized processing"""
        groups = {token_type: [] for token_type in TokenType}
        
        # Detect types for all tokens (could be optimized with batch detection)
        detection_tasks = [self.type_detector.detect_token_type_async(addr) for addr in token_addresses]
        type_results = await asyncio.gather(*detection_tasks, return_exceptions=True)
        
        for i, result in enumerate(type_results):
            token_addr = token_addresses[i]
            
            if isinstance(result, Exception):
                self.logger.debug(f"Type detection failed for {token_addr[:8]}...: {result}")
                groups[TokenType.UNKNOWN].append(token_addr)
            else:
                groups[result.token_type].append(token_addr)
        
        # Log group sizes
        for token_type, addresses in groups.items():
            if addresses:
                self.logger.debug(f"🏷️ {token_type.value}: {len(addresses)} tokens")
        
        return groups
    
    async def _enrich_with_strategy(
        self, 
        token_address: str, 
        strategy: EnrichmentStrategy, 
        type_result: TokenTypeResult
    ) -> Optional[TokenData]:
        """Enrich a single token using the specified strategy"""
        
        # Try primary sources first
        for source in strategy.primary_sources:
            try:
                token_data = await self._enrich_from_source(token_address, source, type_result)
                if token_data:
                    self.logger.debug(f"✅ Primary source {source} successful for {token_address[:8]}...")
                    return token_data
            except Exception as e:
                self.logger.debug(f"❌ Primary source {source} failed for {token_address[:8]}...: {e}")
                continue
        
        # Try fallback sources
        for source in strategy.fallback_sources:
            try:
                token_data = await self._enrich_from_source(token_address, source, type_result)
                if token_data:
                    self.logger.debug(f"✅ Fallback source {source} successful for {token_address[:8]}...")
                    return token_data
            except Exception as e:
                self.logger.debug(f"❌ Fallback source {source} failed for {token_address[:8]}...: {e}")
                continue
        
        return None
    
    async def _enrich_group_with_strategy(
        self, 
        token_addresses: List[str], 
        strategy: EnrichmentStrategy
    ) -> List[EnrichmentResult]:
        """Enrich a group of tokens with the same strategy using batch operations"""
        
        results = []
        
        # Try batch operations first for primary sources
        for source in strategy.primary_sources:
            if source == 'dexscreener' and len(token_addresses) > 1:
                # Use batch API for DexScreener
                batch_results = await self._enrich_batch_from_dexscreener(token_addresses)
                results.extend(batch_results)
                
                # Remove successfully processed tokens
                successful_addrs = {r.token_address for r in batch_results if r.success}
                token_addresses = [addr for addr in token_addresses if addr not in successful_addrs]
                
                if not token_addresses:
                    break
        
        # Process remaining tokens individually
        if token_addresses:
            individual_tasks = [self.enrich_token(addr) for addr in token_addresses]
            individual_results = await asyncio.gather(*individual_tasks, return_exceptions=True)
            
            for result in individual_results:
                if isinstance(result, Exception):
                    self.logger.error(f"Individual enrichment failed: {result}")
                else:
                    results.append(result)
        
        return results
    
    async def _enrich_from_source(
        self, 
        token_address: str, 
        source: str, 
        type_result: TokenTypeResult
    ) -> Optional[TokenData]:
        """Enrich from a specific data source"""
        
        if source == 'dexscreener':
            return await self._enrich_from_dexscreener(token_address)
        elif source == 'pumpfun':
            return await self._enrich_from_pumpfun(token_address)
        elif source == 'solana_tracker' and self.solana_tracker_client:
            return await self._enrich_from_solana_tracker(token_address)
        else:
            self.logger.warning(f"Unknown or unavailable source: {source}")
            return None
    
    async def _enrich_from_dexscreener(self, token_address: str) -> Optional[TokenData]:
        """Enrich from DexScreener"""
        async with aiohttp.ClientSession() as session:
            return await self.dex_client.get_token_data_async(session, token_address)
    
    async def _enrich_from_pumpfun(self, token_address: str) -> Optional[TokenData]:
        """Enrich from Pump.fun"""
        async with aiohttp.ClientSession() as session:
            return await self.pump_client.get_token_data_async(session, token_address)
    
    async def _enrich_from_solana_tracker(self, token_address: str) -> Optional[TokenData]:
        """Enrich from SolanaTracker"""
        if not self.solana_tracker_client:
            return None
        
        async with aiohttp.ClientSession() as session:
            return await self.solana_tracker_client.get_token_data_async(session, token_address)
    
    async def _enrich_batch_from_dexscreener(self, token_addresses: List[str]) -> List[EnrichmentResult]:
        """Enrich multiple tokens from DexScreener using batch API"""
        results = []
        
        try:
            async with aiohttp.ClientSession() as session:
                tokens_data = await self.dex_client.get_tokens_batch_async(session, token_addresses)
            
            for token_addr in token_addresses:
                token_data = tokens_data.get(token_addr)
                
                if token_data:
                    results.append(EnrichmentResult(
                        token_address=token_addr,
                        success=True,
                        token_data=token_data,
                        sources_used=['dexscreener']
                    ))
                else:
                    results.append(EnrichmentResult(
                        token_address=token_addr,
                        success=False,
                        error_message="Not found in DexScreener batch",
                        sources_used=['dexscreener']
                    ))
        
        except Exception as e:
            self.logger.error(f"Batch DexScreener enrichment failed: {e}")
            # Return failed results for all tokens
            for token_addr in token_addresses:
                results.append(EnrichmentResult(
                    token_address=token_addr,
                    success=False,
                    error_message=str(e),
                    sources_used=['dexscreener']
                ))
        
        return results
    
    async def _enrich_security_data(self, token_data: TokenData) -> TokenData:
        """Enrich token with security data from RugCheck"""
        try:
            async with aiohttp.ClientSession() as session:
                security_report = await self.rugcheck_client.get_token_report_async(session, token_data.address)
            
            if security_report:
                security_data = self.rugcheck_client.extract_security_data(security_report)
                
                # Update token data with security information
                token_data.rug_risk_score = security_data.get('rug_risk_score', 50.0)
                token_data.rug_raw_score = security_data.get('rug_raw_score', 0.0)
                token_data.is_rugged = security_data.get('is_rugged', False)
                token_data.mint_authority_revoked = security_data.get('mint_authority_revoked', False)
                token_data.freeze_authority_revoked = security_data.get('freeze_authority_revoked', False)
                token_data.top_holder_percentage = security_data.get('top_holder_percentage', 0.0)
                token_data.top_10_holders_percentage = security_data.get('top_10_holders_percentage', 0.0)
                token_data.insider_holders_count = security_data.get('insider_holders_count', 0)
                token_data.insider_networks_detected = security_data.get('insider_networks_detected', 0)
                token_data.lp_providers_count = security_data.get('lp_providers_count', 0)
                token_data.has_low_liquidity = security_data.get('has_low_liquidity', False)
                token_data.risk_count = security_data.get('risk_count', 0)
                token_data.launchpad_name = security_data.get('launchpad_name')
                token_data.is_pump_fun = security_data.get('is_pump_fun', False)
                
                # Update holder count if RugCheck has better data
                if security_data.get('holder_count', 0) > token_data.holder_count:
                    token_data.holder_count = security_data['holder_count']
                
                self.stats['security_checks_performed'] += 1
                self.logger.debug(f"🔒 Security data enriched for {token_data.address[:8]}...")
            
        except Exception as e:
            self.logger.debug(f"Security enrichment failed for {token_data.address[:8]}...: {e}")
        
        return token_data
    
    def _calculate_analysis_scores(self, token_data: TokenData) -> TokenData:
        """Calculate viability, risk, and momentum scores"""
        try:
            # This would typically use historical data, but for now we'll use current data
            historical_data = []  # Would come from database
            
            viability_score = self.token_analyzer.calculate_viability_score(token_data, historical_data)
            risk_score = self.token_analyzer.calculate_risk_score(token_data, historical_data)
            momentum_score = self.token_analyzer.calculate_momentum_score(token_data, historical_data)
            
            # These would be added to TokenData if they existed
            # For now, we'll calculate but not store them directly
            self.logger.debug(
                f"📊 Analysis scores for {token_data.address[:8]}...: "
                f"V={viability_score:.1f}, R={risk_score:.1f}, M={momentum_score:.1f}"
            )
            
        except Exception as e:
            self.logger.debug(f"Error calculating analysis scores: {e}")
        
        return token_data
    
    def _update_stats(
        self, 
        token_type: TokenType, 
        sources_used: List[str], 
        enrichment_time: float, 
        success: bool
    ):
        """Update enrichment statistics"""
        self.stats['total_enriched'] += 1
        
        if success:
            self.stats['successful_enrichments'] += 1
        else:
            self.stats['failed_enrichments'] += 1
        
        # Update by token type
        type_key = token_type.value
        if type_key not in self.stats['by_token_type']:
            self.stats['by_token_type'][type_key] = {'total': 0, 'successful': 0}
        
        self.stats['by_token_type'][type_key]['total'] += 1
        if success:
            self.stats['by_token_type'][type_key]['successful'] += 1
        
        # Update by source
        for source in sources_used:
            if source not in self.stats['by_source']:
                self.stats['by_source'][source] = {'total': 0, 'successful': 0}
            
            self.stats['by_source'][source]['total'] += 1
            if success:
                self.stats['by_source'][source]['successful'] += 1
        
        # Update average enrichment time
        total_time = self.stats['avg_enrichment_time'] * (self.stats['total_enriched'] - 1)
        self.stats['avg_enrichment_time'] = (total_time + enrichment_time) / self.stats['total_enriched']
    
    def get_enrichment_statistics(self) -> Dict:
        """Get current enrichment statistics"""
        stats = self.stats.copy()
        
        # Calculate success rates
        if stats['total_enriched'] > 0:
            stats['overall_success_rate'] = (stats['successful_enrichments'] / stats['total_enriched']) * 100
        else:
            stats['overall_success_rate'] = 0.0
        
        # Calculate success rates by token type
        for type_key, type_stats in stats['by_token_type'].items():
            if type_stats['total'] > 0:
                type_stats['success_rate'] = (type_stats['successful'] / type_stats['total']) * 100
            else:
                type_stats['success_rate'] = 0.0
        
        # Calculate success rates by source
        for source, source_stats in stats['by_source'].items():
            if source_stats['total'] > 0:
                source_stats['success_rate'] = (source_stats['successful'] / source_stats['total']) * 100
            else:
                source_stats['success_rate'] = 0.0
        
        return stats
    
    def reset_statistics(self):
        """Reset enrichment statistics"""
        self.stats = {
            'total_enriched': 0,
            'successful_enrichments': 0,
            'failed_enrichments': 0,
            'by_token_type': {},
            'by_source': {},
            'avg_enrichment_time': 0.0,
            'security_checks_performed': 0
        }
        
        self.logger.info("📊 Token enricher statistics reset")
    
    def update_strategy(self, token_type: TokenType, strategy: EnrichmentStrategy):
        """Update enrichment strategy for a token type"""
        self.strategies[token_type] = strategy
        self.logger.info(f"🔧 Updated enrichment strategy for {token_type.value}")
    
    def get_health_status(self) -> Dict:
        """Get health status of all API clients"""
        health_status = {
            'overall_healthy': True,
            'clients': {}
        }
        
        # Check DexScreener
        try:
            dex_health = {'healthy': True, 'error': None}
            # Could implement actual health check
        except Exception as e:
            dex_health = {'healthy': False, 'error': str(e)}
            health_status['overall_healthy'] = False
        
        health_status['clients']['dexscreener'] = dex_health
        
        # Check Pump.fun
        try:
            pump_health = self.pump_client.get_pump_fun_health_status()
            if not pump_health.get('overall_healthy', False):
                health_status['overall_healthy'] = False
        except Exception as e:
            pump_health = {'healthy': False, 'error': str(e)}
            health_status['overall_healthy'] = False
        
        health_status['clients']['pumpfun'] = pump_health
        
        # Check RugCheck
        try:
            rugcheck_health = self.rugcheck_client.get_rugcheck_health_status()
            if not rugcheck_health.get('healthy', False):
                health_status['overall_healthy'] = False
        except Exception as e:
            rugcheck_health = {'healthy': False, 'error': str(e)}
            health_status['overall_healthy'] = False
        
        health_status['clients']['rugcheck'] = rugcheck_health
        
        # Check SolanaTracker if available
        if self.solana_tracker_client:
            try:
                st_health = self.solana_tracker_client.get_solanatracker_health_status()
                if not st_health.get('healthy', False):
                    health_status['overall_healthy'] = False
            except Exception as e:
                st_health = {'healthy': False, 'error': str(e)}
                health_status['overall_healthy'] = False
            
            health_status['clients']['solana_tracker'] = st_health
        
        return health_status


def create_token_enricher(
    dex_client: DexScreenerClient,
    pump_client: PumpFunClient,
    rugcheck_client: RugCheckClient,
    solana_tracker_client: Optional[SolanaTrackerClient] = None,
    config=None,
    logger: Optional[logging.Logger] = None
) -> TokenEnricher:
    """
    Factory function to create a configured token enricher
    
    Args:
        dex_client: DexScreener API client
        pump_client: Pump.fun API client
        rugcheck_client: RugCheck API client
        solana_tracker_client: Optional SolanaTracker API client
        config: Configuration object
        logger: Optional logger instance
        
    Returns:
        Configured TokenEnricher instance
    """
    return TokenEnricher(
        dex_client=dex_client,
        pump_client=pump_client,
        rugcheck_client=rugcheck_client,
        solana_tracker_client=solana_tracker_client,
        config=config,
        logger=logger
    )