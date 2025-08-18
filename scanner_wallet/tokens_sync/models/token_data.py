"""
Token Data Models
Centralized data structures for token information and related entities.
"""
from dataclasses import dataclass, field
from typing import Dict, Optional, List
from enum import Enum


class TokenType(Enum):
    """Enumeration of token types"""
    DEX_LISTED = "dex_listed"
    PUMP_PREBOND = "pump_prebond"
    PUMP_GRADUATED = "pump_graduated"
    UNKNOWN = "unknown"


@dataclass
class TokenData:
    """Comprehensive token data structure"""
    address: str
    symbol: str = None
    name: str = None
    decimals: int = 9
    price_usd: float = 0.0
    logo_uri: str = None
    coingecko_id: str = None
    is_verified: bool = False
    timestamp_token_created: int = 0
    creator_address: str = None
    bonding_curve_progress: float = 0.0
    holder_count: int = 0
    market_cap: float = 0.0
    volume_5m: float = 0.0
    volume_1h: float = 0.0
    volume_6h: float = 0.0
    volume_24h: float = 0.0
    price_change_5m: float = 0.0
    price_change_1h: float = 0.0
    price_change_6h: float = 0.0
    price_change_24h: float = 0.0
    price_volatility_24h: float = 0.0
    liquidity_usd: float = 0.0
    liquidity_sol: float = 0.0
    fdv: float = 0.0
    rug_risk_score: float = 50.0
    metadata_source: str = None
    original_address: str = None
    
    # Security fields
    top_holder_percentage: float = 0.0
    top_10_holders_percentage: float = 0.0
    insider_holders_count: int = 0
    insider_networks_detected: int = 0
    lp_providers_count: int = 0
    has_low_liquidity: bool = False
    rug_raw_score: float = 0.0
    is_rugged: bool = False
    risk_count: int = 0
    mint_authority_revoked: bool = False
    freeze_authority_revoked: bool = False
    launchpad_name: str = None
    is_pump_fun: bool = False
    
    def clean_symbol_name(self) -> 'TokenData':
        """Clean symbol and name to avoid SQL injection and special characters"""
        if self.symbol:
            self.symbol = self.symbol.replace('#', '').replace("'", "").replace('"', '').strip()
            if not self.symbol:
                self.symbol = f"UNK_{self.address[:6]}"
        
        if self.name:
            self.name = self.name.replace('#', '').replace("'", "").replace('"', '').strip()
            if not self.name:
                self.name = f"Unknown Token {self.address[:8]}"
        
        # Limit string lengths
        if self.symbol and len(self.symbol) > 20:
            self.symbol = self.symbol[:20]
        
        if self.name and len(self.name) > 100:
            self.name = self.name[:100]
        
        return self
    
    def calculate_derived_metrics(self) -> 'TokenData':
        """Calculate derived metrics like ratios"""
        # These would be added as properties or calculated fields
        return self


@dataclass
class TokenTypeResult:
    """Result of token type detection"""
    token_type: TokenType
    confidence: float  # 0.0 to 1.0
    source_data: Dict = field(default_factory=dict)
    needs_pump_enrichment: bool = False
    needs_dex_enrichment: bool = False


@dataclass
class HistoricalSnapshot:
    """Structure for historical token data snapshot"""
    token_address: str
    snapshot_timestamp: int
    previous_snapshot_id: Optional[int] = None
    
    # Core metrics
    price_usd: float = 0.0
    market_cap: float = 0.0
    volume_24h: float = 0.0
    holder_count: int = 0
    liquidity_usd: float = 0.0
    
    # Calculated deltas
    price_delta_usd: float = 0.0
    market_cap_delta: float = 0.0
    volume_24h_delta: float = 0.0
    holder_count_delta: int = 0
    
    # Analysis scores
    viability_score: float = 50.0
    risk_score: float = 50.0
    momentum_score: float = 0.0


@dataclass
class QueueItem:
    """Queue processing item"""
    token_address: str
    status: str = "pending"  # pending, processing, completed, failed
    created_at: Optional[str] = None
    processing_started_at: Optional[str] = None
    completed_at: Optional[str] = None
    retry_count: int = 0
    last_error: Optional[str] = None


@dataclass
class BatchResult:
    """Result of batch processing"""
    total_requested: int
    successful: int
    failed: int
    tokens_found: List[str] = field(default_factory=list)
    tokens_missing: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage"""
        if self.total_requested == 0:
            return 0.0
        return (self.successful / self.total_requested) * 100


@dataclass
class CycleStats:
    """Statistics for a sync cycle"""
    cycle_id: int
    cycle_number: int
    start_time: Optional[int] = None
    end_time: Optional[int] = None
    duration: float = 0.0
    
    # Operations counts
    new_tokens: int = 0
    updated_tokens: int = 0
    historized_tokens: int = 0
    creation_timestamps: int = 0
    dead_tokens_marked: int = 0
    pumpfun_updated: int = 0
    
    # API calls
    api_calls: Dict[str, int] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    
    def add_operation(self, operation: str, count: int = 1):
        """Add operation count"""
        if hasattr(self, operation):
            setattr(self, operation, getattr(self, operation) + count)
    
    def add_api_call(self, api_name: str, count: int = 1):
        """Add API call count"""
        if api_name not in self.api_calls:
            self.api_calls[api_name] = 0
        self.api_calls[api_name] += count
    
    def add_error(self, error_msg: str):
        """Add error message"""
        self.errors.append(error_msg)