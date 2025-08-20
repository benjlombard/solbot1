import logging
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from polling_manager import polling_manager
from early_adopter_scorer import scorer
from database import db
from config import settings

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('pumpfun_tracker.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestionnaire de cycle de vie de l'application"""
    logger.info("Starting PumpFun Tracker with intelligent polling...")
    
    # Démarrage du polling intelligent
    polling_manager.start_polling()
    
    # Mise à jour initiale des scores
    try:
        await scorer.update_all_early_adopters()
        logger.info("Initial early adopter scoring completed")
    except Exception as e:
        logger.error(f"Error in initial scoring: {e}")
    
    logger.info("PumpFun Tracker started successfully")
    
    yield
    
    # Arrêt propre
    logger.info("Shutting down PumpFun Tracker...")
    await polling_manager.shutdown()
    logger.info("PumpFun Tracker stopped")

# Création de l'application FastAPI
app = FastAPI(
    title="PumpFun Early Adopters Tracker",
    description="Système de tracking des early adopters pump.fun avec polling intelligent",
    version="1.0.1",
    lifespan=lifespan
)

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    """Page d'accueil de l'API"""
    return {
        "message": "PumpFun Early Adopters Tracker API - Polling Version",
        "version": "1.0.1",
        "status": "running",
        "polling_mode": True,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/health")
async def health_check():
    """Vérification de la santé du système"""
    try:
        # Vérifier la base de données
        stats = db.get_dashboard_stats()
        
        # Vérifier le polling manager
        polling_health = await polling_manager.health_check()
        
        health = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "database": {
                "status": "connected" if stats else "error",
                "total_tokens": stats.get('total_tokens_tracked', 0),
                "total_early_adopters": stats.get('total_early_adopters', 0)
            },
            "polling_manager": polling_health,
            "services": {
                "database": "ok",
                "polling": "ok" if polling_health['status'] == 'healthy' else "warning"
            }
        }
        
        # Déterminer le statut global
        if polling_health['status'] == 'warning':
            health['status'] = 'warning'
        elif not stats or polling_health['status'] == 'degraded':
            health['status'] = 'degraded'
        
        return health
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "error",
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }

@app.get("/api/stats")
async def get_stats():
    """Statistiques générales du système"""
    try:
        # Stats base de données
        db_stats = db.get_dashboard_stats()
        
        # Stats polling manager
        polling_stats = polling_manager.get_stats()
        
        return {
            "database": db_stats,
            "polling_manager": polling_stats,
            "last_updated": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving stats")

@app.get("/api/early-adopters")
async def get_early_adopters(
    min_confidence: float = 0.6,
    limit: int = 50
):
    """Récupère la liste des early adopters"""
    try:
        adopters = db.get_early_adopters(min_confidence, limit)
        
        result = []
        for adopter in adopters:
            result.append({
                "wallet_address": adopter.wallet_address,
                "confidence_score": adopter.confidence_score,
                "success_rate": adopter.success_rate,
                "total_picks": adopter.total_picks,
                "successful_picks": adopter.successful_picks,
                "avg_roi": adopter.avg_roi,
                "avg_entry_timing": adopter.avg_entry_timing,
                "last_activity": adopter.last_activity.isoformat()
            })
        
        return {
            "early_adopters": result,
            "count": len(result),
            "filters": {
                "min_confidence": min_confidence,
                "limit": limit
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting early adopters: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving early adopters")

@app.get("/api/recent-tokens")
async def get_recent_tokens(hours_back: int = 24, limit: int = 100):
    """Récupère les tokens récents avec early adopter signals"""
    try:
        tokens = db.get_recent_tokens(hours_back, limit)
        
        return {
            "tokens": tokens,
            "count": len(tokens),
            "filters": {
                "hours_back": hours_back,
                "limit": limit
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting recent tokens: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving recent tokens")

@app.get("/api/copy-trading-opportunities")
async def get_copy_trading_opportunities(min_confidence: float = 0.8):
    """Identifie les opportunités de copy trading"""
    try:
        opportunities = await scorer.identify_copy_trading_opportunities(min_confidence)
        
        return {
            "opportunities": opportunities,
            "count": len(opportunities),
            "filters": {
                "min_confidence": min_confidence
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting copy trading opportunities: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving opportunities")

@app.get("/api/wallet/{wallet_address}")
async def get_wallet_details(wallet_address: str):
    """Détails d'un wallet spécifique"""
    try:
        # Récupérer les achats du wallet
        purchases = db.get_wallet_purchases(wallet_address, days_back=30)
        
        # Récupérer le profil early adopter s'il existe
        adopters = db.get_early_adopters(min_confidence_score=0.0, limit=1000)
        adopter_profile = None
        
        for adopter in adopters:
            if adopter.wallet_address == wallet_address:
                adopter_profile = {
                    "confidence_score": adopter.confidence_score,
                    "success_rate": adopter.success_rate,
                    "total_picks": adopter.total_picks,
                    "successful_picks": adopter.successful_picks,
                    "avg_roi": adopter.avg_roi,
                    "avg_entry_timing": adopter.avg_entry_timing,
                    "last_activity": adopter.last_activity.isoformat()
                }
                break
        
        return {
            "wallet_address": wallet_address,
            "early_adopter_profile": adopter_profile,
            "recent_purchases": purchases,
            "purchase_count": len(purchases)
        }
        
    except Exception as e:
        logger.error(f"Error getting wallet details for {wallet_address}: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving wallet details")

@app.post("/api/update-scores")
async def trigger_score_update():
    """Déclenche manuellement une mise à jour des scores"""
    try:
        # Exécuter en arrière-plan
        task = asyncio.create_task(scorer.update_all_early_adopters())
        
        return {
            "message": "Score update triggered",
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error triggering score update: {e}")
        raise HTTPException(status_code=500, detail="Error triggering score update")

@app.post("/api/force-poll")
async def force_poll():
    """Force un polling immédiat (pour debug/test)"""
    try:
        result = await polling_manager.force_poll_now()
        return result
        
    except Exception as e:
        logger.error(f"Error in force poll: {e}")
        raise HTTPException(status_code=500, detail="Error forcing poll")

@app.get("/api/polling-stats")
async def get_polling_stats():
    """Statistiques détaillées du polling"""
    try:
        stats = polling_manager.get_stats()
        health = await polling_manager.health_check()
        
        return {
            "polling_stats": stats,
            "health_check": health,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting polling stats: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving polling stats")

@app.get("/api/dashboard-data")
async def get_dashboard_data():
    """Données complètes pour le dashboard Streamlit"""
    try:
        # Récupérer toutes les données nécessaires
        db_stats = db.get_dashboard_stats()
        top_performers = scorer.get_top_performers(limit=10)
        recent_tokens = db.get_recent_tokens(hours_back=24, limit=20)
        opportunities = await scorer.identify_copy_trading_opportunities(min_confidence=0.8)
        polling_stats = polling_manager.get_stats()
        
        return {
            "stats": db_stats,
            "top_performers": top_performers,
            "recent_tokens": recent_tokens,
            "copy_trading_opportunities": opportunities,
            "system_health": polling_stats,
            "last_updated": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting dashboard data: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving dashboard data")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Gestionnaire global d'exceptions"""
    logger.error(f"Unhandled exception on {request.url}: {exc}")
    
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "timestamp": datetime.now().isoformat()
        }
    )

if __name__ == "__main__":
    logger.info("Starting PumpFun Tracker server with intelligent polling...")
    
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
        log_level="info"
    )