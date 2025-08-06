
#!/usr/bin/env python3
"""
FastAPI application for Solana wallet analytics.

This module sets up the main FastAPI application with all routes,
middleware, error handling, and configuration.
"""

import logging
import sys
import traceback
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exception_handlers import http_exception_handler

from api.routes import analytics
from core.config import settings
from core.exceptions import (
    SolanaRPCError,
    DataProcessingError,
    ValidationError,
    RateLimitError
)

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('logs/app.log') if settings.LOG_TO_FILE else logging.NullHandler()
    ]
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager for startup and shutdown events.
    """
    # Startup
    logger.info("Starting Solana Wallet Analytics API")
    logger.info(f"Environment: {settings.ENVIRONMENT}")
    logger.info(f"Debug mode: {settings.DEBUG}")
    logger.info(f"Log level: {settings.LOG_LEVEL}")
    
    try:
        # Initialize any required services here
        # For example, database connections, external service clients, etc.
        yield
    finally:
        # Shutdown
        logger.info("Shutting down Solana Wallet Analytics API")


# Create FastAPI application
app = FastAPI(
    title="Solana Wallet Analytics API",
    description="API for analyzing Solana wallet transactions and providing analytics insights",
    version="1.0.0",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    Log all incoming requests and their responses.
    """
    start_time = time.time()
    
    # Log request
    logger.info(f"Request: {request.method} {request.url}")
    if request.method in ["POST", "PUT", "PATCH"]:
        try:
            body = await request.body()
            if body:
                logger.debug(f"Request body: {body.decode()[:500]}...")
        except Exception:
            pass
    
    response = await call_next(request)
    
    # Log response
    process_time = time.time() - start_time
    logger.info(
        f"Response: {response.status_code} - "
        f"Time: {process_time:.3f}s - "
        f"Path: {request.url.path}"
    )
    
    return response


# Custom exception handlers
@app.exception_handler(SolanaRPCError)
async def solana_rpc_exception_handler(request: Request, exc: SolanaRPCError):
    """Handle Solana RPC specific errors."""
    logger.error(f"Solana RPC Error: {exc}")
    return JSONResponse(
        status_code=503,
        content={
            "error": "Solana RPC Service Error",
            "message": str(exc),
            "type": "solana_rpc_error",
            "details": exc.details if hasattr(exc, 'details') else None
        }
    )


@app.exception_handler(DataProcessingError)
async def data_processing_exception_handler(request: Request, exc: DataProcessingError):
    """Handle data processing errors."""
    logger.error(f"Data Processing Error: {exc}")
    return JSONResponse(
        status_code=422,
        content={
            "error": "Data Processing Error",
            "message": str(exc),
            "type": "data_processing_error",
            "details": exc.details if hasattr(exc, 'details') else None
        }
    )


@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    """Handle validation errors."""
    logger.error(f"Validation Error: {exc}")
    return JSONResponse(
        status_code=400,
        content={
            "error": "Validation Error",
            "message": str(exc),
            "type": "validation_error",
            "details": exc.details if hasattr(exc, 'details') else None
        }
    )


@app.exception_handler(RateLimitError)
async def rate_limit_exception_handler(request: Request, exc: RateLimitError):
    """Handle rate limit errors."""
    logger.warning(f"Rate Limit Error: {exc}")
    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate Limit Exceeded",
            "message": str(exc),
            "type": "rate_limit_error",
            "retry_after": exc.retry_after if hasattr(exc, 'retry_after') else None
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle all other unhandled exceptions."""
    logger.error(f"Unhandled exception: {exc}")
    logger.error(traceback.format_exc())
    
    if settings.DEBUG:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "message": str(exc),
                "type": "internal_error",
                "traceback": traceback.format_exc()
            }
        )
    else:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "message": "An unexpected error occurred",
                "type": "internal_error"
            }
        )


# Health check endpoint
@app.get("/health")
async def health_check():
    """
    Health check endpoint to verify the API is running.
    """
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "environment": settings.ENVIRONMENT
    }


@app.get("/")
async def root():
    """
    Root endpoint with API information.
    """
    return {
        "name": "Solana Wallet Analytics API",
        "version": "1.0.0",
        "description": "API for analyzing Solana wallet transactions and providing analytics insights",
        "docs_url": "/docs" if settings.DEBUG else None,
        "health_check": "/health"
    }


# Include routers
app.include_router(
    analytics.router,
    prefix="/api/v1/analytics",
    tags=["analytics"]
)


# Add additional imports at the top
import time
from datetime import datetime


if __name__ == "__main__":
    import uvicorn
    
    # Run the application
    uvicorn.run(
        "api.app:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower(),
        access_log=True
    )