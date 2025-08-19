"""
RugCheck API Client
Specialized client for interacting with RugCheck.xyz API for token security analysis.
"""
import asyncio
import aiohttp
from typing import Dict, List, Optional, Tuple, Any
from .base_client import BaseApiClient, ApiResponse, RateLimitConfig
from ..models.token_data import TokenData


class RugCheckClient(BaseApiClient):
    """
    Client for RugCheck.xyz API with specialized methods for token security analysis
    """
    
    def __init__(self, logger=None, api_tracker=None):
        # RugCheck has reasonable rate limits
        super().__init__(
            base_url="https://api.rugcheck.xyz/v1",
            api_name="rugcheck",
            timeout=45.0,  # Security analysis can take longer
            rate_limit=RateLimitConfig(
                calls_per_minute=40,
                calls_per_hour=2400,
                burst_limit=8
            ),
            logger=logger,
            api_tracker=api_tracker
        )
    
    def get_api_info(self) -> Dict:
        """Get RugCheck API information"""
        return {
            "name": "RugCheck",
            "base_url": self.base_url,
            "rate_limits": {
                "calls_per_minute": 40,
                "burst_limit": 8
            },
            "endpoints": [
                "tokens/{address}/report",
                "tokens/{address}/holders",
                "tokens/{address}/risks"
            ],
            "features": [
                "Security analysis",
                "Holder distribution",
                "Risk assessment",
                "Authority checks",
                "Liquidity analysis"
            ]
        }
    
    def get_token_report(self, token_address: str) -> Optional[Dict]:
        """
        Get comprehensive security report for a token
        
        Args:
            token_address: Token address to analyze
            
        Returns:
            Complete security report or None if not available
        """
        response = self.make_request(f"tokens/{token_address}/report")
        
        if not response.success:
            self.logger.debug(f"RugCheck report failed for {token_address[:8]}...: {response.error_message}")
            return None
        
        if not response.data:
            self.logger.debug(f"No RugCheck data for {token_address[:8]}...")
            return None
        
        self.logger.debug(f"✅ Got RugCheck report for {token_address[:8]}...")
        return response.data
    
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
        response = await self.make_async_request(session, f"tokens/{token_address}/report")
        
        if not response.success or not response.data:
            self.logger.debug(f"Async RugCheck failed for {token_address[:8]}...")
            return None
        
        return response.data
    
    def get_tokens_batch(self, token_addresses: List[str]) -> Dict[str, Dict]:
        """
        Get security reports for multiple tokens (sequential due to API limitations)
        
        Args:
            token_addresses: List of token addresses
            
        Returns:
            Dictionary mapping token_address -> security_report
        """
        results = {}
        
        for token_address in token_addresses:
            try:
                report = self.get_token_report(token_address)
                if report:
                    results[token_address] = report
                
                # Rate limiting between calls
                import time
                time.sleep(1.5)  # Conservative rate limiting
                
            except Exception as e:
                self.logger.debug(f"Error getting RugCheck data for {token_address[:8]}...: {e}")
                continue
        
        return results
    
    async def get_tokens_batch_async(
        self, 
        session: aiohttp.ClientSession, 
        token_addresses: List[str]
    ) -> Dict[str, Dict]:
        """
        Get security reports for multiple tokens asynchronously
        
        Args:
            session: aiohttp session
            token_addresses: List of token addresses
            
        Returns:
            Dictionary mapping token_address -> security_report
        """
        # Limit concurrent requests for security analysis
        semaphore = asyncio.Semaphore(3)  # Conservative concurrency
        
        async def fetch_single_report(token_addr: str) -> Tuple[str, Optional[Dict]]:
            async with semaphore:
                try:
                    # Add small delay between requests
                    await asyncio.sleep(0.5)
                    report = await self.get_token_report_async(session, token_addr)
                    return token_addr, report
                except Exception as e:
                    self.logger.debug(f"Async RugCheck error for {token_addr[:8]}...: {e}")
                    return token_addr, None
        
        # Execute requests
        tasks = [fetch_single_report(addr) for addr in token_addresses]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        results = {}
        for result in results_list:
            if isinstance(result, Exception):
                self.logger.debug(f"RugCheck async task exception: {result}")
                continue
            
            token_addr, report = result
            if report:
                results[token_addr] = report
        
        return results
    
    def extract_security_data(self, rugcheck_report: Dict) -> Dict:
        """
        Extract and normalize security data from RugCheck response
        
        Args:
            rugcheck_report: Raw RugCheck API response
            
        Returns:
            Normalized security data dictionary
        """
        try:
            if not rugcheck_report or not isinstance(rugcheck_report, dict):
                self.logger.debug("Invalid or empty RugCheck response")
                return self._get_default_security_data()
            
            security_data = {}
            
            # Risk scores
            security_data['rug_risk_score'] = float(rugcheck_report.get('score_normalised', 50) or 50)
            security_data['rug_raw_score'] = float(rugcheck_report.get('score', 0) or 0)
            security_data['is_rugged'] = bool(rugcheck_report.get('rugged', False))
            
            # Token authorities
            token_info = rugcheck_report.get('token', {})
            if isinstance(token_info, dict):
                security_data['mint_authority_revoked'] = token_info.get('mintAuthority') is None
                security_data['freeze_authority_revoked'] = token_info.get('freezeAuthority') is None
            else:
                security_data['mint_authority_revoked'] = False
                security_data['freeze_authority_revoked'] = False
            
            # Holder analysis
            self._extract_holder_data(rugcheck_report, security_data)
            
            # Risk analysis
            self._extract_risk_data(rugcheck_report, security_data)
            
            # Liquidity analysis
            self._extract_liquidity_data(rugcheck_report, security_data)
            
            # Additional metadata
            self._extract_metadata(rugcheck_report, security_data)
            
            self.logger.debug(
                f"Successfully extracted RugCheck data: "
                f"score={security_data.get('rug_risk_score')}, "
                f"holders={security_data.get('holder_count')}, "
                f"risks={security_data.get('risk_count')}"
            )
            
            return security_data
            
        except Exception as e:
            self.logger.error(f"Error extracting RugCheck data: {e}")
            return self._get_default_security_data()
    
    def _extract_holder_data(self, report: Dict, security_data: Dict):
        """Extract holder distribution data"""
        try:
            # Total holders
            security_data['holder_count'] = int(report.get('totalHolders', 0) or 0)
            
            # Top holders analysis
            top_holders = report.get('topHolders', [])
            if isinstance(top_holders, list) and top_holders:
                # Top holder percentage
                first_holder = top_holders[0] if len(top_holders) > 0 else {}
                security_data['top_holder_percentage'] = float(first_holder.get('pct', 0) or 0)
                
                # Top 10 holders percentage
                top_10_pct = 0.0
                for i, holder in enumerate(top_holders[:10]):
                    if isinstance(holder, dict) and 'pct' in holder:
                        try:
                            top_10_pct += float(holder.get('pct', 0) or 0)
                        except (ValueError, TypeError):
                            continue
                security_data['top_10_holders_percentage'] = top_10_pct
                
                # Insider analysis
                insider_count = 0
                for holder in top_holders:
                    if isinstance(holder, dict) and holder.get('insider', False):
                        insider_count += 1
                security_data['insider_holders_count'] = insider_count
                
            else:
                security_data['top_holder_percentage'] = 0.0
                security_data['top_10_holders_percentage'] = 0.0
                security_data['insider_holders_count'] = 0
            
            # Insider networks
            security_data['insider_networks_detected'] = int(report.get('graphInsidersDetected', 0) or 0)
            
        except Exception as e:
            self.logger.debug(f"Error extracting holder data: {e}")
            security_data.update({
                'holder_count': 0,
                'top_holder_percentage': 0.0,
                'top_10_holders_percentage': 0.0,
                'insider_holders_count': 0,
                'insider_networks_detected': 0
            })
    
    def _extract_risk_data(self, report: Dict, security_data: Dict):
        """Extract risk assessment data"""
        try:
            # Risk count and types
            risks = report.get('risks', [])
            if isinstance(risks, list):
                security_data['risk_count'] = len(risks)
                
                # Check for specific risk types
                risk_names = [risk.get('name', '') for risk in risks if isinstance(risk, dict)]
                security_data['has_low_liquidity'] = any('Low Liquidity' in name for name in risk_names)
                security_data['has_mint_risk'] = any('Mint' in name for name in risk_names)
                security_data['has_freeze_risk'] = any('Freeze' in name for name in risk_names)
                security_data['has_concentration_risk'] = any('Concentration' in name for name in risk_names)
                
                # Risk details for analysis
                security_data['risk_details'] = [
                    {
                        'name': risk.get('name', ''),
                        'severity': risk.get('severity', 'unknown'),
                        'description': risk.get('description', '')
                    }
                    for risk in risks if isinstance(risk, dict)
                ]
            else:
                security_data['risk_count'] = 0
                security_data['has_low_liquidity'] = False
                security_data['has_mint_risk'] = False
                security_data['has_freeze_risk'] = False
                security_data['has_concentration_risk'] = False
                security_data['risk_details'] = []
            
        except Exception as e:
            self.logger.debug(f"Error extracting risk data: {e}")
            security_data.update({
                'risk_count': 0,
                'has_low_liquidity': False,
                'has_mint_risk': False,
                'has_freeze_risk': False,
                'has_concentration_risk': False,
                'risk_details': []
            })
    
    def _extract_liquidity_data(self, report: Dict, security_data: Dict):
        """Extract liquidity analysis data"""
        try:
            # Total market liquidity
            liquidity_raw = report.get('totalMarketLiquidity', 0.0)
            security_data['liquidity_usd'] = float(liquidity_raw) if liquidity_raw is not None else 0.0
            
            # LP providers
            security_data['lp_providers_count'] = int(report.get('totalLPProviders', 0) or 0)
            
            # LP analysis
            lp_analysis = report.get('lpAnalysis', {})
            if isinstance(lp_analysis, dict):
                security_data['lp_locked_percentage'] = float(lp_analysis.get('lockedPercentage', 0) or 0)
                security_data['lp_burned_percentage'] = float(lp_analysis.get('burnedPercentage', 0) or 0)
                security_data['lp_removable_percentage'] = float(lp_analysis.get('removablePercentage', 0) or 0)
            else:
                security_data['lp_locked_percentage'] = 0.0
                security_data['lp_burned_percentage'] = 0.0
                security_data['lp_removable_percentage'] = 0.0
            
        except Exception as e:
            self.logger.debug(f"Error extracting liquidity data: {e}")
            security_data.update({
                'liquidity_usd': 0.0,
                'lp_providers_count': 0,
                'lp_locked_percentage': 0.0,
                'lp_burned_percentage': 0.0,
                'lp_removable_percentage': 0.0
            })
    
    def _extract_metadata(self, report: Dict, security_data: Dict):
        """Extract additional metadata"""
        try:
            # Launchpad information
            launchpad = report.get('launchpad', {})
            if isinstance(launchpad, dict):
                security_data['launchpad_name'] = launchpad.get('name')
                security_data['is_pump_fun'] = launchpad.get('platform') == 'pump_fun'
            else:
                security_data['launchpad_name'] = None
                security_data['is_pump_fun'] = False
            
            # Analysis timestamp
            security_data['analysis_timestamp'] = report.get('timestamp')
            
            # Token age
            created_at = report.get('token', {}).get('createdAt')
            if created_at:
                try:
                    import time
                    current_time = time.time()
                    if isinstance(created_at, (int, float)):
                        # Handle both seconds and milliseconds
                        creation_time = created_at / 1000 if created_at > 1e12 else created_at
                        security_data['token_age_hours'] = (current_time - creation_time) / 3600
                    else:
                        security_data['token_age_hours'] = 0
                except:
                    security_data['token_age_hours'] = 0
            else:
                security_data['token_age_hours'] = 0
            
        except Exception as e:
            self.logger.debug(f"Error extracting metadata: {e}")
            security_data.update({
                'launchpad_name': None,
                'is_pump_fun': False,
                'analysis_timestamp': None,
                'token_age_hours': 0
            })
    
    def _get_default_security_data(self) -> Dict:
        """Get default security data for failed analysis"""
        return {
            'rug_risk_score': 50.0,
            'rug_raw_score': 0.0,
            'is_rugged': False,
            'mint_authority_revoked': False,
            'freeze_authority_revoked': False,
            'top_holder_percentage': 0.0,
            'top_10_holders_percentage': 0.0,
            'insider_holders_count': 0,
            'holder_count': 0,
            'insider_networks_detected': 0,
            'lp_providers_count': 0,
            'liquidity_usd': 0.0,
            'launchpad_name': None,
            'is_pump_fun': False,
            'risk_count': 0,
            'has_low_liquidity': False,
            'has_mint_risk': False,
            'has_freeze_risk': False,
            'has_concentration_risk': False,
            'risk_details': [],
            'lp_locked_percentage': 0.0,
            'lp_burned_percentage': 0.0,
            'lp_removable_percentage': 0.0,
            'analysis_timestamp': None,
            'token_age_hours': 0
        }
    
    def get_token_risks_only(self, token_address: str) -> Optional[List[Dict]]:
        """
        Get only the risks for a token (lighter endpoint)
        
        Args:
            token_address: Token address
            
        Returns:
            List of risk objects or None
        """
        response = self.make_request(f"tokens/{token_address}/risks")
        
        if response.success and response.data:
            return response.data.get('risks', [])
        
        return None
    
    def get_token_holders_analysis(self, token_address: str) -> Optional[Dict]:
        """
        Get detailed holder analysis for a token
        
        Args:
            token_address: Token address
            
        Returns:
            Holder analysis data or None
        """
        response = self.make_request(f"tokens/{token_address}/holders")
        
        if response.success and response.data:
            return response.data
        
        return None
    
    def calculate_security_score(self, security_data: Dict) -> float:
        """
        Calculate a comprehensive security score (0-100, higher = safer)
        
        Args:
            security_data: Extracted security data
            
        Returns:
            Security score from 0-100
        """
        try:
            score = 100.0  # Start with perfect score
            
            # Authority penalties (high impact)
            if not security_data.get('mint_authority_revoked', True):
                score -= 30  # Major red flag
            
            if not security_data.get('freeze_authority_revoked', True):
                score -= 20  # Significant risk
            
            # Concentration penalties
            top_holder_pct = security_data.get('top_holder_percentage', 0)
            if top_holder_pct > 50:
                score -= 25
            elif top_holder_pct > 30:
                score -= 15
            elif top_holder_pct > 20:
                score -= 10
            
            top_10_pct = security_data.get('top_10_holders_percentage', 0)
            if top_10_pct > 80:
                score -= 15
            elif top_10_pct > 60:
                score -= 10
            elif top_10_pct > 40:
                score -= 5
            
            # Risk penalties
            risk_count = security_data.get('risk_count', 0)
            score -= min(risk_count * 5, 20)  # Max 20 points for risks
            
            # Liquidity penalties
            if security_data.get('has_low_liquidity', False):
                score -= 10
            
            # Insider network penalties
            insider_networks = security_data.get('insider_networks_detected', 0)
            score -= min(insider_networks * 3, 15)
            
            # LP security bonus
            lp_locked = security_data.get('lp_locked_percentage', 0)
            lp_burned = security_data.get('lp_burned_percentage', 0)
            secure_lp_pct = lp_locked + lp_burned
            
            if secure_lp_pct > 80:
                score += 10
            elif secure_lp_pct > 50:
                score += 5
            
            # Already rugged penalty
            if security_data.get('is_rugged', False):
                score = 0  # Automatic zero
            
            return max(0.0, min(100.0, score))
            
        except Exception as e:
            self.logger.error(f"Error calculating security score: {e}")
            return 50.0  # Neutral score on error
    
    def is_token_safe(self, security_data: Dict, threshold: float = 70.0) -> bool:
        """
        Determine if a token meets safety criteria
        
        Args:
            security_data: Extracted security data
            threshold: Minimum security score required
            
        Returns:
            True if token is considered safe
        """
        security_score = self.calculate_security_score(security_data)
        
        # Additional hard requirements
        hard_requirements = [
            not security_data.get('is_rugged', False),
            security_data.get('mint_authority_revoked', False),
            security_data.get('top_holder_percentage', 100) < 50,
            security_data.get('risk_count', 10) < 5
        ]
        
        return security_score >= threshold and all(hard_requirements)
    
    def get_rugcheck_health_status(self) -> Dict:
        """
        Check RugCheck API health status
        
        Returns:
            Dictionary with health information
        """
        try:
            # Test with a known token (should be fast)
            test_token = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC
            response = self.make_request(f"tokens/{test_token}/risks", max_retries=0)
            
            return {
                'healthy': response.success,
                'status_code': response.status_code,
                'response_time': response.duration,
                'error_message': response.error_message
            }
            
        except Exception as e:
            return {
                'healthy': False,
                'status_code': None,
                'response_time': 0,
                'error_message': str(e)
            }