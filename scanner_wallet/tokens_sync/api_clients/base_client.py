"""
Base API Client
Provides common functionality for all API clients including retry logic,
rate limiting, session management, and error handling.
"""
import time
import asyncio
import aiohttp
import requests
import logging
from abc import ABC, abstractmethod
from typing import Dict, Optional, Any, List, Union
from dataclasses import dataclass
from urllib.parse import urljoin


@dataclass
class ApiResponse:
    """Standardized API response structure"""
    success: bool
    status_code: Optional[int] = None
    data: Optional[Dict] = None
    error_message: Optional[str] = None
    duration: float = 0.0
    api_name: str = ""


@dataclass
class RateLimitConfig:
    """Rate limiting configuration"""
    calls_per_minute: int = 60
    calls_per_hour: int = 3600
    burst_limit: int = 10
    backoff_factor: float = 1.5


class BaseApiClient(ABC):
    """
    Base class for all API clients with common functionality
    """
    
    def __init__(
        self,
        base_url: str,
        api_name: str,
        timeout: float = 30.0,
        rate_limit: Optional[RateLimitConfig] = None,
        logger: Optional[logging.Logger] = None,
        api_tracker=None
    ):
        self.base_url = base_url.rstrip('/')
        self.api_name = api_name
        self.timeout = timeout
        self.rate_limit = rate_limit or RateLimitConfig()
        self.logger = logger or logging.getLogger(f"{__name__}.{api_name}")
        
        self.api_tracker = api_tracker

        # Rate limiting tracking
        self._call_history: List[float] = []
        self._last_call_time = 0.0
        
        # Session management
        self.session = self._create_session()
        
    def _is_batch_call(self, endpoint: str, params: Optional[Dict]) -> bool:
        """Détermine si c'est un appel batch"""
        # Pour DexScreener : endpoint contient plusieurs adresses séparées par des virgules
        if 'tokens/' in endpoint:
            # Extraire la partie après 'tokens/'
            token_part = endpoint.split('tokens/')[-1]
            # Si contient des virgules, c'est un batch
            return ',' in token_part
        return False

    def _count_addresses_in_call(self, endpoint: str, params: Optional[Dict]) -> int:
        """Compte le nombre d'adresses dans l'appel"""
        if 'tokens/' in endpoint:
            token_part = endpoint.split('tokens/')[-1]
            if ',' in token_part:
                return len(token_part.split(','))
            else:
                return 1
        return 0
        
    def _create_session(self) -> requests.Session:
        """Create and configure requests session"""
        session = requests.Session()
        session.headers.update(self._get_default_headers())
        return session
    
    def _get_default_headers(self) -> Dict[str, str]:
        """Get default headers for API requests"""
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
        }
    
    def _should_rate_limit(self) -> tuple[bool, float]:
        """
        Check if we should rate limit and return wait time
        
        Returns:
            (should_wait, wait_time_seconds)
        """
        current_time = time.time()
        
        # Clean old entries
        cutoff_time = current_time - 60  # Last minute
        self._call_history = [t for t in self._call_history if t > cutoff_time]
        
        # Check rate limits
        calls_last_minute = len(self._call_history)
        
        if calls_last_minute >= self.rate_limit.calls_per_minute:
            # Calculate wait time
            oldest_call = min(self._call_history)
            wait_time = 60 - (current_time - oldest_call) + 1
            return True, wait_time
        
        # Check burst protection
        if (current_time - self._last_call_time) < (60 / self.rate_limit.burst_limit):
            wait_time = (60 / self.rate_limit.burst_limit) - (current_time - self._last_call_time)
            return True, wait_time
        
        return False, 0.0
    
    def _record_api_call(self, duration: float, success: bool = True, status_code: Optional[int] = None):
        """Record API call for rate limiting and monitoring"""
        current_time = time.time()
        self._call_history.append(current_time)
        self._last_call_time = current_time
        
        # Log call for monitoring
        self.logger.debug(
            f"API call {self.api_name}: {duration:.3f}s, "
            f"status={status_code}, success={success}"
        )
    
    def _build_url(self, endpoint: str) -> str:
        """Build full URL from endpoint"""
        return urljoin(self.base_url + '/', endpoint.lstrip('/'))
    
    def _handle_response(self, response: requests.Response, duration: float) -> ApiResponse:
        """Handle and standardize API response"""
        try:
            if response.status_code == 200:
                data = response.json()
                return ApiResponse(
                    success=True,
                    status_code=response.status_code,
                    data=data,
                    duration=duration,
                    api_name=self.api_name
                )
            else:
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_data = response.json()
                    if 'error' in error_data:
                        error_msg += f": {error_data['error']}"
                except:
                    error_msg += f": {response.text[:100]}"
                
                return ApiResponse(
                    success=False,
                    status_code=response.status_code,
                    error_message=error_msg,
                    duration=duration,
                    api_name=self.api_name
                )
                
        except Exception as e:
            return ApiResponse(
                success=False,
                status_code=response.status_code,
                error_message=f"Response parsing error: {e}",
                duration=duration,
                api_name=self.api_name
            )
    
    def make_request(self, endpoint: str, method: str = "GET", params: Optional[Dict] = None, 
                data: Optional[Dict] = None, max_retries: int = 0) -> ApiResponse:
        """
        Make HTTP request with retry logic, rate limiting, and API tracking
        """
        url = self._build_url(endpoint)
        
        # Nom complet de l'endpoint pour le tracking
        endpoint_name = f"{self.api_name}_{endpoint.strip('/').replace('/', '_')}"
        
        for attempt in range(max_retries):
            try:
                # Check rate limiting
                should_wait, wait_time = self._should_rate_limit()
                if should_wait:
                    self.logger.debug(f"Rate limiting: waiting {wait_time:.2f}s")
                    time.sleep(wait_time)
                
                # Make request
                start_time = time.time()
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=data,
                    timeout=self.timeout
                )
                duration = time.time() - start_time
                
                # Record call for internal tracking
                self._record_api_call(duration, response.status_code == 200, response.status_code)
                
                # Handle response
                api_response = self._handle_response(response, duration)
                
                # ========== CORRECTION: API TRACKER INTEGRATION ==========
                # Enregistrer l'appel dans l'API tracker pour le monitoring
                if hasattr(self, 'api_tracker') and self.api_tracker:
                    try:
                        self.api_tracker.record_call(
                            api_name=endpoint_name,
                            duration=duration,
                            success=(response.status_code == 200),
                            http_status=response.status_code,
                            error_msg=api_response.error_message if not api_response.success else None
                        )
                    except Exception as tracker_error:
                        # Ne pas faire échouer la requête si le tracking échoue
                        self.logger.debug(f"API tracker error: {tracker_error}")
                
                if hasattr(self, 'cycle_logger') and self.cycle_logger:
                    try:
                        # Déterminer si c'est un appel batch ou individuel
                        is_batch_call = self._is_batch_call(endpoint, params)
                        addresses_count = self._count_addresses_in_call(endpoint, params)
                        
                        self.cycle_logger.record_api_endpoint_call(
                            client_name=self.api_name,
                            endpoint=endpoint.strip('/').replace('/', '_'),
                            is_batch=is_batch_call,
                            addresses_count=addresses_count
                        )
                    except Exception as cycle_error:
                        # Ne pas faire échouer la requête si le tracking échoue
                        self.logger.debug(f"Cycle logger error: {cycle_error}")

                # Check if we should retry
                if not api_response.success and self._should_retry(api_response, attempt, max_retries):
                    continue
                
                return api_response
                
            except requests.exceptions.Timeout as e:
                error_msg = f"Request timeout after {self.timeout}s on attempt {attempt + 1}"
                self.logger.warning(error_msg)
                
                # Enregistrer le timeout dans l'API tracker
                if hasattr(self, 'api_tracker') and self.api_tracker:
                    try:
                        self.api_tracker.record_call(
                            api_name=endpoint_name,
                            duration=self.timeout,
                            success=False,
                            http_status=None,
                            error_msg=error_msg
                        )
                    except Exception:
                        pass
                
                if attempt == max_retries - 1:
                    return ApiResponse(
                        success=False,
                        error_message=f"Request timeout after {max_retries} attempts",
                        api_name=self.api_name,
                        duration=self.timeout
                    )
                    
            except requests.exceptions.RequestException as e:
                error_msg = f"Request error on attempt {attempt + 1}: {e}"
                self.logger.warning(error_msg)
                
                # Enregistrer l'erreur dans l'API tracker
                if hasattr(self, 'api_tracker') and self.api_tracker:
                    try:
                        duration_estimate = time.time() - start_time if 'start_time' in locals() else 0.0
                        self.api_tracker.record_call(
                            api_name=endpoint_name,
                            duration=duration_estimate,
                            success=False,
                            http_status=None,
                            error_msg=str(e)
                        )
                    except Exception:
                        pass
                
                if attempt == max_retries - 1:
                    return ApiResponse(
                        success=False,
                        error_message=f"Request failed: {e}",
                        api_name=self.api_name
                    )
            
            # Wait before retry
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) * self.rate_limit.backoff_factor
                time.sleep(wait_time)
        
        # Fallback response (should not reach here normally)
        final_error = f"All {max_retries} attempts failed"
        
        # Enregistrer l'échec final dans l'API tracker
        if hasattr(self, 'api_tracker') and self.api_tracker:
            try:
                self.api_tracker.record_call(
                    api_name=endpoint_name,
                    duration=0.0,
                    success=False,
                    http_status=None,
                    error_msg=final_error
                )
            except Exception:
                pass
        
        return ApiResponse(
            success=False,
            error_message=final_error,
            api_name=self.api_name
        )

    
    def _should_retry(self, response: ApiResponse, attempt: int, max_retries: int) -> bool:
        """Determine if request should be retried based on response"""
        if attempt >= max_retries - 1:
            return False
        
        # Retry on server errors
        if response.status_code and response.status_code >= 500:
            return True
        
        # Retry on rate limiting
        if response.status_code == 429:
            return True
        
        # Don't retry on client errors (4xx except 429)
        if response.status_code and 400 <= response.status_code < 500:
            return False
        
        return True
    
    async def make_async_request(
    self,
    session: aiohttp.ClientSession,
    endpoint: str,
    method: str = "GET",
    params: Optional[Dict] = None,
    data: Optional[Dict] = None,
    max_retries: int = 3
) -> ApiResponse:
        """
        Make asynchronous HTTP request with API tracking
        """
        url = self._build_url(endpoint)
        
        # Nom complet de l'endpoint pour le tracking
        endpoint_name = f"{self.api_name}_{endpoint.strip('/').replace('/', '_')}"
        
        for attempt in range(max_retries):
            try:
                start_time = time.time()
                
                async with session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=data,
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:
                    duration = time.time() - start_time
                    
                    # Record call for internal tracking
                    self._record_api_call(duration, response.status == 200, response.status)
                    
                    # Handle response
                    if response.status == 200:
                        data = await response.json()
                        api_response = ApiResponse(
                            success=True,
                            status_code=response.status,
                            data=data,
                            duration=duration,
                            api_name=self.api_name
                        )
                    else:
                        error_msg = f"HTTP {response.status}"
                        try:
                            error_data = await response.json()
                            if 'error' in error_data:
                                error_msg += f": {error_data['error']}"
                        except:
                            text = await response.text()
                            error_msg += f": {text[:100]}"
                        
                        api_response = ApiResponse(
                            success=False,
                            status_code=response.status,
                            error_message=error_msg,
                            duration=duration,
                            api_name=self.api_name
                        )
                    
                    # ========== CORRECTION: API TRACKER INTEGRATION ==========
                    # Enregistrer l'appel dans l'API tracker pour le monitoring
                    if hasattr(self, 'api_tracker') and self.api_tracker:
                        try:
                            self.api_tracker.record_call(
                                api_name=endpoint_name,
                                duration=duration,
                                success=(response.status == 200),
                                http_status=response.status,
                                error_msg=api_response.error_message if not api_response.success else None
                            )
                        except Exception as tracker_error:
                            # Ne pas faire échouer la requête si le tracking échoue
                            self.logger.debug(f"API tracker error: {tracker_error}")
                    
                    # Check if we should retry
                    if self._should_retry(api_response, attempt, max_retries):
                        continue
                    
                    return api_response
                    
            except asyncio.TimeoutError:
                error_msg = f"Async timeout on attempt {attempt + 1}"
                self.logger.warning(error_msg)
                
                # Enregistrer le timeout dans l'API tracker
                if hasattr(self, 'api_tracker') and self.api_tracker:
                    try:
                        self.api_tracker.record_call(
                            api_name=endpoint_name,
                            duration=self.timeout,
                            success=False,
                            http_status=None,
                            error_msg=error_msg
                        )
                    except Exception:
                        pass
                
                if attempt == max_retries - 1:
                    return ApiResponse(
                        success=False,
                        error_message=f"Request timeout after {max_retries} attempts",
                        api_name=self.api_name
                    )
                    
            except Exception as e:
                error_msg = f"Async request error on attempt {attempt + 1}: {e}"
                self.logger.warning(error_msg)
                
                # Enregistrer l'erreur dans l'API tracker
                if hasattr(self, 'api_tracker') and self.api_tracker:
                    try:
                        duration_estimate = time.time() - start_time if 'start_time' in locals() else 0.0
                        self.api_tracker.record_call(
                            api_name=endpoint_name,
                            duration=duration_estimate,
                            success=False,
                            http_status=None,
                            error_msg=str(e)
                        )
                    except Exception:
                        pass
                
                if attempt == max_retries - 1:
                    return ApiResponse(
                        success=False,
                        error_message=f"Request failed: {e}",
                        api_name=self.api_name
                    )
            
            # Wait before retry
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) * self.rate_limit.backoff_factor
                await asyncio.sleep(wait_time)
        
        # Fallback response
        final_error = f"All {max_retries} attempts failed"
    
    def close(self):
        """Close the session and cleanup resources"""
        if hasattr(self, 'session'):
            self.session.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    @abstractmethod
    def get_api_info(self) -> Dict[str, Any]:
        """Get API-specific information and capabilities"""
        pass


class ApiClientManager:
    """
    Manager for multiple API clients with shared session and monitoring
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        self.clients: Dict[str, BaseApiClient] = {}
        self._global_call_stats: Dict[str, int] = {}
    
    def register_client(self, name: str, client: BaseApiClient):
        """Register an API client"""
        self.clients[name] = client
        self.logger.debug(f"Registered API client: {name}")
    
    def get_client(self, name: str) -> Optional[BaseApiClient]:
        """Get registered API client by name"""
        return self.clients.get(name)
    
    def get_all_stats(self) -> Dict[str, Dict]:
        """Get statistics from all registered clients"""
        stats = {}
        for name, client in self.clients.items():
            stats[name] = {
                'calls_last_minute': len(client._call_history),
                'last_call': client._last_call_time,
                'rate_limit': {
                    'calls_per_minute': client.rate_limit.calls_per_minute,
                    'burst_limit': client.rate_limit.burst_limit
                }
            }
        return stats
    
    def close_all(self):
        """Close all registered clients"""
        for client in self.clients.values():
            try:
                client.close()
            except Exception as e:
                self.logger.warning(f"Error closing client: {e}")
        self.clients.clear()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_all()