from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum

class TransactionType(str, Enum):
    UNKNOWN = "UNKNOWN"
    SWAP = "SWAP"

class OutcomeType(str, Enum):
    SUCCESS = "success"
    FAIL = "fail"  
    PENDING = "pending"

# Helius Webhook Models
class HeliusInstruction(BaseModel):
    accounts: List[str]
    data: str
    innerInstructions: Optional[List[Dict[str, Any]]] = []
    programId: str

class HeliusTransaction(BaseModel):
    signature: str
    slot: int
    timestamp: datetime
    type: str
    source: str
    fee: int
    feePayer: str
    instructions: List[HeliusInstruction]
    nativeTransfers: Optional[List[Dict[str, Any]]] = []
    tokenTransfers: Optional[List[Dict[str, Any]]] = []
    accountData: Optional[List[Dict[str, Any]]] = []

class HeliusWebhookData(BaseModel):
    transactions: List[HeliusTransaction]

# Database Models
class PumpToken(BaseModel):
    address: str
    name: Optional[str] = None
    symbol: Optional[str] = None
    description: Optional[str] = None
    creator: str
    created_at: datetime
    market_cap_discovery: Optional[float] = None
    # NOTE: A corresponding 'is_blacklisted' column (BOOLEAN, default FALSE) needs to be added to the 'pump_tokens' table in the database.
    is_blacklisted: bool = False

class EarlyPurchase(BaseModel):
    signature: str
    token_address: str
    buyer_address: str
    sol_amount: float
    token_amount: float
    timestamp: datetime
    minutes_after_creation: int
    market_cap_at_purchase: Optional[float] = None

class EarlyAdopter(BaseModel):
    wallet_address: str
    total_picks: int = 0
    successful_picks: int = 0
    avg_entry_timing: float = 0.0
    success_rate: float = 0.0
    avg_roi: float = 0.0
    confidence_score: float = 0.0
    last_activity: datetime

class TokenOutcome(BaseModel):
    token_address: str
    outcome_type: OutcomeType
    roi_24h: Optional[float] = None
    roi_7d: Optional[float] = None
    peak_market_cap: Optional[float] = None
    migration_date: Optional[datetime] = None

# API Response Models
class EarlyAdopterStats(BaseModel):
    wallet_address: str
    total_picks: int
    successful_picks: int
    success_rate: float
    avg_roi: float
    confidence_score: float
    recent_picks: List[str] = []

class TokenAlert(BaseModel):
    token_address: str
    name: Optional[str]
    symbol: Optional[str]
    creator: str
    early_adopter_buyers: List[str]
    confidence_level: str
    created_at: datetime
    market_cap: Optional[float] = None

class DashboardStats(BaseModel):
    total_tokens_tracked: int
    total_early_adopters: int
    top_performers: List[EarlyAdopterStats]
    recent_alerts: List[TokenAlert]
    credits_used_today: int