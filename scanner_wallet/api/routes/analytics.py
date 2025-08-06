
#!/usr/bin/env python3
"""
Analytics routes for Solana wallet analysis.

This module provides REST API endpoints for wallet analytics including:
- Transaction analysis
- Portfolio analytics
- Performance metrics
- Risk assessment
- Token analysis
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator

from core.wallet_analyzer import WalletAnalyzer
from core.transaction_processor import TransactionProcessor
from core.portfolio_tracker import PortfolioTracker
from core.data_collector import DataCollector
from core.config import settings
from core.exceptions import (
    SolanaRPCError,
    DataProcessingError,
    ValidationError,
    RateLimitError
)

logger = logging.getLogger(__name__)

# Create router
router = APIRouter()

# Pydantic models for request/response
class WalletAnalysisRequest(BaseModel):
    """Request model for wallet analysis."""
    wallet_address: str = Field(..., description="Solana wallet address to analyze")
    days: Optional[int] = Field(30, ge=1, le=365, description="Number of days to analyze")
    include_tokens: Optional[bool] = Field(True, description="Include token analysis")
    include_nfts: Optional[bool] = Field(False, description="Include NFT analysis")
    
    @validator('wallet_address')
    def validate_wallet_address(cls, v):
        """Validate Solana wallet address format."""
        if not v or len(v) < 32 or len(v) > 44:
            raise ValueError('Invalid Solana wallet address format')
        return v


class TransactionAnalysisRequest(BaseModel):
    """Request model for transaction analysis."""
    wallet_address: str = Field(..., description="Solana wallet address")
    start_date: Optional[datetime] = Field(None, description="Start date for analysis")
    end_date: Optional[datetime] = Field(None, description="End date for analysis")
    limit: Optional[int] = Field(100, ge=1, le=1000, description="Maximum number of transactions")
    transaction_type: Optional[str] = Field(None, description="Filter by transaction type")


class PortfolioAnalysisRequest(BaseModel):
    """Request model for portfolio analysis."""
    wallet_address: str = Field(..., description="Solana wallet address")
    include_historical: Optional[bool] = Field(True, description="Include historical data")
    currency: Optional[str] = Field("USD", description="Currency for value calculation")


class TokenAnalysisRequest(BaseModel):
    """Request model for token analysis."""
    wallet_address: str = Field(..., description="Solana wallet address")
    token_address: Optional[str] = Field(None, description="Specific token to analyze")
    min_value: Optional[float] = Field(0, ge=0, description="Minimum token value in USD")


# Response models
class WalletAnalysisResponse(BaseModel):
    """Response model for wallet analysis."""
    wallet_address: str
    analysis_date: datetime
    summary: Dict[str, Any]
    transactions: Dict[str, Any]
    portfolio: Dict[str, Any]
    performance: Dict[str, Any]
    risk_metrics: Dict[str, Any]


class TransactionAnalysisResponse(BaseModel):
    """Response model for transaction analysis."""
    wallet_address: str
    transaction_count: int
    date_range: Dict[str, datetime]
    transactions: List[Dict[str, Any]]
    summary: Dict[str, Any]


class PortfolioAnalysisResponse(BaseModel):
    """Response model for portfolio analysis."""
    wallet_address: str
    total_value: float
    tokens: List[Dict[str, Any]]
    allocation: Dict[str, float]
    performance: Dict[str, Any]


# Dependency for services
async def get_wallet_analyzer() -> WalletAnalyzer:
    """Dependency to get WalletAnalyzer instance."""
    return WalletAnalyzer()


async def get_transaction_processor() -> TransactionProcessor:
    """Dependency to get TransactionProcessor instance."""
    return TransactionProcessor()


async def get_portfolio_tracker() -> PortfolioTracker:
    """Dependency to get PortfolioTracker instance."""
    return PortfolioTracker()


async def get_data_collector() -> DataCollector:
    """Dependency to get DataCollector instance."""
    return DataCollector()


# Routes
@router.get("/", summary="Analytics API Information")
async def get_analytics_info():
    """Get information about available analytics endpoints."""
    return {
        "name": "Solana Wallet Analytics",
        "version": "1.0.0",
        "endpoints": {
            "wallet_analysis": "/wallet/analyze",
            "transaction_analysis": "/transactions/analyze",
            "portfolio_analysis": "/portfolio/analyze",
            "token_analysis": "/tokens/analyze",
            "wallet_summary": "/wallet/{wallet_address}/summary"
        }
    }


@router.post("/wallet/analyze", 
             response_model=WalletAnalysisResponse,
             summary="Complete Wallet Analysis")
async def analyze_wallet(
    request: WalletAnalysisRequest,
    analyzer: WalletAnalyzer = Depends(get_wallet_analyzer)
):
    """
    Perform comprehensive analysis of a Solana wallet.
    
    This endpoint provides:
    - Transaction history analysis
    - Portfolio composition
    - Performance metrics
    - Risk assessment
    - Token holdings analysis
    """
    try:
        logger.info(f"Starting wallet analysis for: {request.wallet_address}")
        
        # Perform analysis
        analysis_result = await analyzer.analyze_wallet(
            wallet_address=request.wallet_address,
            days=request.days,
            include_tokens=request.include_tokens,
            include_nfts=request.include_nfts
        )
        
        return WalletAnalysisResponse(
            wallet_address=request.wallet_address,
            analysis_date=datetime.utcnow(),
            **analysis_result
        )
        
    except SolanaRPCError as e:
        logger.error(f"Solana RPC error during wallet analysis: {e}")
        raise HTTPException(status_code=503, detail=f"Blockchain service error: {str(e)}")
    except DataProcessingError as e:
        logger.error(f"Data processing error during wallet analysis: {e}")
        raise HTTPException(status_code=422, detail=f"Data processing failed: {str(e)}")
    except ValidationError as e:
        logger.error(f"Validation error during wallet analysis: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid request: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error during wallet analysis: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/transactions/analyze",
             response_model=TransactionAnalysisResponse,
             summary="Transaction Analysis")
async def analyze_transactions(
    request: TransactionAnalysisRequest,
    processor: TransactionProcessor = Depends(get_transaction_processor)
):
    """
    Analyze transaction history for a wallet.
    
    Provides detailed transaction analysis including:
    - Transaction categorization
    - Volume and frequency metrics
    - Pattern detection
    - Profit/loss calculations
    """
    try:
        logger.info(f"Starting transaction analysis for: {request.wallet_address}")
        
        # Process transactions
        analysis_result = await processor.analyze_transactions(
            wallet_address=request.wallet_address,
            start_date=request.start_date,
            end_date=request.end_date,
            limit=request.limit,
            transaction_type=request.transaction_type
        )
        
        return TransactionAnalysisResponse(**analysis_result)
        
    except Exception as e:
        logger.error(f"Error during transaction analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/portfolio/analyze",
             response_model=PortfolioAnalysisResponse,
             summary="Portfolio Analysis")
async def analyze_portfolio(
    request: PortfolioAnalysisRequest,
    tracker: PortfolioTracker = Depends(get_portfolio_tracker)
):
    """
    Analyze current portfolio composition and performance.
    
    Provides:
    - Current token holdings and values
    - Portfolio allocation breakdown
    - Performance metrics
    - Diversification analysis
    """
    try:
        logger.info(f"Starting portfolio analysis for: {request.wallet_address}")
        
        analysis_result = await tracker.analyze_portfolio(
            wallet_address=request.wallet_address,
            include_historical=request.include_historical,
            currency=request.currency
        )
        
        return PortfolioAnalysisResponse(**analysis_result)
        
    except Exception as e:
        logger.error(f"Error during portfolio analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tokens/analyze",
             summary="Token Analysis")
async def analyze_tokens(
    request: TokenAnalysisRequest,
    collector: DataCollector = Depends(get_data_collector)
):
    """
    Analyze token holdings and transactions.
    
    Provides detailed token-specific analysis including:
    - Holding positions and changes
    - Trading activity
    - Performance metrics
    - Token metadata
    """
    try:
        logger.info(f"Starting token analysis for: {request.wallet_address}")
        
        analysis_result = await collector.analyze_tokens(
            wallet_address=request.wallet_address,
            token_address=request.token_address,
            min_value=request.min_value
        )
        
        return analysis_result
        
    except Exception as e:
        logger.error(f"Error during token analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/wallet/{wallet_address}/summary",
            summary="Wallet Summary")
async def get_wallet_summary(
    wallet_address: str,
    days: int = Query(30, ge=1, le=365, description="Number of days for summary"),
    analyzer: WalletAnalyzer = Depends(get_wallet_analyzer)
):
    """
    Get a quick summary of wallet activity and holdings.
    
    Provides high-level overview including:
    - Current balance
    - Recent activity
    - Top holdings
    - Key metrics
    """
    try:
        logger.info(f"Getting wallet summary for: {wallet_address}")
        
        summary = await analyzer.get_wallet_summary(
            wallet_address=wallet_address,
            days=days
        )
        
        return {
            "wallet_address": wallet_address,
            "summary_date": datetime.utcnow(),
            "period_days": days,
            **summary
        }
        
    except Exception as e:
        logger.error(f"Error getting wallet summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/wallet/{wallet_address}/transactions",
            summary="Get Wallet Transactions")
async def get_wallet_transactions(
    wallet_address: str,
    limit: int = Query(50, ge=1, le=500, description="Number of transactions to return"),
    before: Optional[str] = Query(None, description="Transaction signature to paginate before"),
    processor: TransactionProcessor = Depends(get_transaction_processor)
):
    """
    Get paginated list of wallet transactions.
    """
    try:
        transactions = await processor.get_transactions(
            wallet_address=wallet_address,
            limit=limit,
            before=before
        )
        
        return {
            "wallet_address": wallet_address,
            "transactions": transactions,
            "count": len(transactions)
        }
        
    except Exception as e:
        logger.error(f"Error getting transactions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/wallet/{wallet_address}/portfolio",
            summary="Get Current Portfolio")
async def get_current_portfolio(
    wallet_address: str,
    tracker: PortfolioTracker = Depends(get_portfolio_tracker)
):
    """
    Get current portfolio holdings and values.
    """
    try:
        portfolio = await tracker.get_current_portfolio(wallet_address)
        
        return {
            "wallet_address": wallet_address,
            "timestamp": datetime.utcnow(),
            "portfolio": portfolio
        }
        
    except Exception as e:
        logger.error(f"Error getting portfolio: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/wallet/{wallet_address}/performance",
            summary="Get Performance Metrics")
async def get_performance_metrics(
    wallet_address: str,
    days: int = Query(30, ge=1, le=365),
    analyzer: WalletAnalyzer = Depends(get_wallet_analyzer)
):
    """
    Get performance metrics for the specified period.
    """
    try:
        performance = await analyzer.get_performance_metrics(
            wallet_address=wallet_address,
            days=days
        )
        
        return {
            "wallet_address": wallet_address,
            "period_days": days,
            "metrics": performance
        }
        
    except Exception as e:
        logger.error(f"Error getting performance metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Health check for analytics service
@router.get("/health", summary="Analytics Service Health Check")
async def analytics_health_check():
    """Check health of analytics service and dependencies."""
    try:
        # Test basic functionality
        analyzer = WalletAnalyzer()
        
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow(),
            "services": {
                "wallet_analyzer": "operational",
                "transaction_processor": "operational",
                "portfolio_tracker": "operational",
                "data_collector": "operational"
            }
        }
    except Exception as e:
        logger.error(f"Analytics health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "timestamp": datetime.utcnow(),
                "error": str(e)
            }
        )