import logging
import asyncio
import aiohttp
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from .system_monitor import SystemMonitor
from .polling_manager import IntelligentPollingManager
from .early_adopter_scorer import scorer
from .database import db
from .config import settings
from .pump_fun_client import PumpFunClient
# Ajoutez cette ligne avec les autres imports
from .creator_analyzer import creator_analyzer
# Configuration du logging AVANT d'importer pump_fun_client
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('pumpfun_tracker.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# MAINTENANT importer et initialiser le client Pump.fun
try:
    pump_client = PumpFunClient(logger_instance=logger)
    logger.info("Pump.fun client initialized successfully")
except ImportError as e:
    logger.error(f"Failed to import PumpFunClient or initialize it: {e}", exc_info=True)
    pump_client = None

system_monitor = SystemMonitor(db)
polling_manager = IntelligentPollingManager(system_monitor=system_monitor)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestionnaire de cycle de vie de l'application"""
    logger.info("Starting PumpFun Tracker with intelligent polling...")
    
    # Start the system monitor in a background thread
    import threading
    monitor_thread = threading.Thread(target=system_monitor.run, daemon=True)
    monitor_thread.start()

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


@app.post("/api/force-latest-discovery")
async def force_latest_discovery():
    """Force la découverte latest immédiate (pour debug/test)"""
    try:
        result = await polling_manager.force_latest_discovery()
        return result
        
    except Exception as e:
        logger.error(f"Error in force latest discovery: {e}")
        raise HTTPException(status_code=500, detail="Error forcing latest discovery")

@app.get("/api/discovery-stats")
async def get_discovery_stats():
    """Statistiques détaillées de la découverte de tokens"""
    try:
        stats = polling_manager.get_stats()
        
        # Extraire les données de découverte
        discovery_stats = stats.get('discovery', {})
        
        # Ajouter des métriques calculées
        latest_stats = discovery_stats.get('latest_discovery', {})
        general_stats = discovery_stats.get('general_discovery', {})
        
        return {
            "latest_discovery": {
                **latest_stats,
                "avg_tokens_per_call": (
                    latest_stats.get('tokens_discovered_today', 0) / 
                    max(latest_stats.get('calls_today', 1), 1)
                ),
                "next_run_in_seconds": max(0, 
                    latest_stats.get('interval_seconds', 60) - 
                    (latest_stats.get('time_since_last_minutes', 0) * 60)
                )
            },
            "general_discovery": {
                **general_stats,
                "avg_tokens_per_call": (
                    general_stats.get('tokens_discovered_today', 0) / 
                    max(general_stats.get('calls_today', 1), 1)
                ),
                "next_run_in_seconds": max(0, 
                    general_stats.get('interval_seconds', 300) - 
                    (general_stats.get('time_since_last_minutes', 0) * 60)
                )
            },
            "total_tokens_discovered_today": (
                latest_stats.get('tokens_discovered_today', 0) + 
                general_stats.get('tokens_discovered_today', 0)
            ),
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error getting discovery stats: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving discovery stats")

@app.get("/api/latest-tokens")
async def get_latest_tokens_discovered(limit: int = 20):
    """Récupère les tokens les plus récemment découverts"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Récupérer les tokens les plus récents avec leurs données d'enrichissement
            cursor.execute("""
                SELECT 
                    pt.*,
                    rr.score as rugcheck_score,
                    rr.is_rugged as rugcheck_rugged
                FROM pump_tokens pt
                LEFT JOIN rugcheck_reports rr ON pt.address = rr.token_address
                ORDER BY pt.row_created_at DESC
                LIMIT ?
            """, (limit,))
            
            tokens = []
            for row in cursor.fetchall():
                token_data = dict(row)
                
                # Calculer l'âge
                created_at = datetime.fromisoformat(token_data['created_at'])
                age_minutes = (datetime.now() - created_at).total_seconds() / 60
                token_data['age_minutes'] = round(age_minutes, 1)
                
                # Ajouter des métriques
                token_data['discovery_method'] = 'latest_api'  # Indiquer la méthode de découverte
                
                tokens.append(token_data)
            
            return {
                "tokens": tokens,
                "count": len(tokens),
                "timestamp": datetime.now().isoformat()
            }
            
    except Exception as e:
        logger.error(f"Error getting latest tokens: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving latest tokens")

@app.get("/api/discovery-performance")
async def get_discovery_performance():
    """Analyse des performances de découverte"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Statistiques des dernières 24h
            since_24h = (datetime.now() - timedelta(hours=24)).isoformat()
            
            # Tokens découverts par heure
            cursor.execute("""
                SELECT 
                    strftime('%H', row_created_at) as hour,
                    COUNT(*) as tokens_count
                FROM pump_tokens
                WHERE row_created_at >= ?
                GROUP BY strftime('%H', row_created_at)
                ORDER BY hour
            """, (since_24h,))
            
            hourly_distribution = {
                row['hour']: row['tokens_count'] 
                for row in cursor.fetchall()
            }
            
            # Top créateurs découverts
            cursor.execute("""
                SELECT 
                    creator,
                    COUNT(*) as tokens_created,
                    MIN(row_created_at) as first_token,
                    MAX(row_created_at) as latest_token
                FROM pump_tokens
                WHERE row_created_at >= ?
                GROUP BY creator
                HAVING tokens_created > 1
                ORDER BY tokens_created DESC
                LIMIT 10
            """, (since_24h,))
            
            top_creators = []
            for row in cursor.fetchall():
                top_creators.append({
                    'creator': row['creator'],
                    'tokens_created': row['tokens_created'],
                    'first_token': row['first_token'],
                    'latest_token': row['latest_token'],
                    'creator_short': row['creator'][:10] + "..."
                })
            
            # Tokens avec bonding curve progress élevé
            cursor.execute("""
                SELECT 
                    address, symbol, creator, bonding_curve_progress,
                    row_created_at, usd_market_cap
                FROM pump_tokens
                WHERE row_created_at >= ?
                AND bonding_curve_progress > 50
                ORDER BY bonding_curve_progress DESC
                LIMIT 10
            """, (since_24h,))
            
            high_progress_tokens = [dict(row) for row in cursor.fetchall()]
            
            # Statistiques globales
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_discovered,
                    AVG(bonding_curve_progress) as avg_progress,
                    AVG(usd_market_cap) as avg_market_cap,
                    COUNT(CASE WHEN bonding_curve_progress > 10 THEN 1 END) as tokens_with_activity
                FROM pump_tokens
                WHERE row_created_at >= ?
            """, (since_24h,))
            
            global_stats = dict(cursor.fetchone())
            
            return {
                "performance_24h": {
                    "total_discovered": global_stats['total_discovered'],
                    "avg_progress": round(global_stats['avg_progress'] or 0, 2),
                    "avg_market_cap": round(global_stats['avg_market_cap'] or 0, 2),
                    "tokens_with_activity": global_stats['tokens_with_activity'],
                    "activity_rate": round(
                        (global_stats['tokens_with_activity'] / max(global_stats['total_discovered'], 1)) * 100, 1
                    )
                },
                "hourly_distribution": hourly_distribution,
                "top_creators": top_creators,
                "high_progress_tokens": high_progress_tokens,
                "timestamp": datetime.now().isoformat()
            }
            
    except Exception as e:
        logger.error(f"Error getting discovery performance: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving discovery performance")

@app.get("/api/config")
async def get_current_config():
    """Retourne la configuration actuelle du système"""
    try:
        config_info = {
            "discovery": {
                "use_latest_discovery": getattr(settings, 'use_latest_discovery', False),
                "latest_discovery_interval_seconds": getattr(settings, 'latest_discovery_interval_seconds', 60),
                "latest_discovery_limit": getattr(settings, 'latest_discovery_limit', 20),
                "use_api_discovery": getattr(settings, 'use_api_discovery', False),
                "api_discovery_interval_seconds": getattr(settings, 'api_discovery_interval_seconds', 300),
                "api_discovery_limit": getattr(settings, 'api_discovery_limit', 50),
                "use_transaction_detection": getattr(settings, 'use_transaction_token_detection', False),
                "token_discovery_method": getattr(settings, 'token_discovery_method', 'latest')
            },
            "polling": {
                "base_polling_interval_seconds": settings.base_polling_interval_seconds,
                "min_polling_interval_seconds": settings.min_polling_interval_seconds,
                "max_polling_interval_seconds": settings.max_polling_interval_seconds,
                "adaptive_polling_enabled": settings.adaptive_polling_enabled
            },
            "budget": {
                "max_daily_credits": settings.max_daily_credits,
                "min_sol_amount_filter": settings.min_sol_amount_filter,
                "credit_warning_threshold": settings.credit_warning_threshold,
                "credit_pause_threshold": settings.credit_pause_threshold
            },
            "enrichment": {
                "enable_metadata_enrichment": settings.enable_metadata_enrichment,
                "enrichment_interval_seconds": settings.enrichment_interval_seconds,
                "enrichment_batch_size": settings.enrichment_batch_size,
                "enrichment_update_interval_minutes": settings.enrichment_update_interval_minutes
            }
        }
        
        return config_info
        
    except Exception as e:
        logger.error(f"Error getting config: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving configuration")

@app.get("/api/health-detailed")
async def get_detailed_health():
    """Vérification de santé détaillée incluant la découverte"""
    try:
        # Health check de base
        base_health = await health_check()
        
        # Stats de découverte
        discovery_stats = polling_manager.get_stats().get('discovery', {})
        
        # Vérifications spécifiques à la découverte
        discovery_health = {
            "latest_discovery": {
                "enabled": discovery_stats.get('latest_discovery', {}).get('enabled', False),
                "last_run_minutes_ago": discovery_stats.get('latest_discovery', {}).get('time_since_last_minutes', 0),
                "status": "healthy" if discovery_stats.get('latest_discovery', {}).get('time_since_last_minutes', 0) < 5 else "warning"
            },
            "general_discovery": {
                "enabled": discovery_stats.get('general_discovery', {}).get('enabled', False),
                "last_run_minutes_ago": discovery_stats.get('general_discovery', {}).get('time_since_last_minutes', 0),
                "status": "healthy" if discovery_stats.get('general_discovery', {}).get('time_since_last_minutes', 0) < 15 else "warning"
            }
        }
        
        # Déterminer le statut global de découverte
        discovery_status = "healthy"
        if not discovery_stats.get('latest_discovery', {}).get('enabled', False) and not discovery_stats.get('general_discovery', {}).get('enabled', False):
            discovery_status = "warning"
        elif discovery_health['latest_discovery']['status'] == "warning" and discovery_health['general_discovery']['status'] == "warning":
            discovery_status = "degraded"
        
        # Combiner avec le health check de base
        detailed_health = {
            **base_health,
            "discovery": {
                "status": discovery_status,
                **discovery_health
            },
            "components": {
                "database": base_health.get('database', {}).get('status', 'unknown'),
                "polling": base_health.get('polling_manager', {}).get('status', 'unknown'),
                "discovery": discovery_status,
                "enrichment": "healthy" if settings.enable_metadata_enrichment else "disabled"
            }
        }
        
        # Déterminer le statut global
        component_statuses = list(detailed_health['components'].values())
        if 'error' in component_statuses or 'critical' in component_statuses:
            detailed_health['status'] = 'critical'
        elif 'degraded' in component_statuses:
            detailed_health['status'] = 'degraded'
        elif 'warning' in component_statuses:
            detailed_health['status'] = 'warning'
        
        return detailed_health
        
    except Exception as e:
        logger.error(f"Detailed health check failed: {e}")
        return {
            "status": "error",
            "timestamp": datetime.now().isoformat(),
            "error": str(e)
        }

# Ajouter également cette fonction utilitaire pour tester la découverte
@app.post("/api/test-latest-endpoint")
async def test_latest_endpoint():
    """Test direct de l'endpoint /coins/latest de pump.fun"""
    try:
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            url = "https://frontend-api-v3.pump.fun/coins/latest"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json'
            }
            
            async with session.get(url, headers=headers, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    return {
                        "status": "success",
                        "endpoint": url,
                        "response_status": response.status,
                        "tokens_count": len(data) if isinstance(data, list) else 0,
                        "sample_token": data[0] if isinstance(data, list) and len(data) > 0 else None,
                        "timestamp": datetime.now().isoformat()
                    }
                else:
                    return {
                        "status": "error",
                        "endpoint": url,
                        "response_status": response.status,
                        "error": f"HTTP {response.status}",
                        "timestamp": datetime.now().isoformat()
                    }
                    
    except Exception as e:
        logger.error(f"Error testing latest endpoint: {e}")
        return {
            "status": "error",
            "error": str(e),
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

@app.get("/api/creators")
async def get_creators(
    min_reputation: float = 0,
    min_success_rate: float = 0,
    limit: int = 50,
    min_tokens: int = 1
):
    """Récupère la liste des créateurs avec filtres"""
    try:
        creators = creator_analyzer.get_creators_by_filter(
            min_reputation=min_reputation,
            min_success_rate=min_success_rate,
            limit=limit,
            min_tokens=min_tokens
        )
        
        # Convert to dict for JSON response
        result = [c.__dict__ for c in creators]
        
        return {
            "creators": result,
            "count": len(result),
            "filters": {
                "min_reputation": min_reputation,
                "min_success_rate": min_success_rate,
                "limit": limit,
                "min_tokens": min_tokens
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting creators: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving creators")

@app.get("/api/creator/{creator_address}/tokens")
async def get_creator_tokens(creator_address: str):
    """Récupère tous les tokens pour un créateur spécifique."""
    try:
        tokens = creator_analyzer.get_tokens_for_creator(creator_address)
        return {
            "creator_address": creator_address,
            "tokens": tokens,
            "count": len(tokens)
        }
    except Exception as e:
        logger.error(f"Error getting tokens for creator {creator_address}: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving creator tokens")

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

@app.get("/api/recent-purchases-detailed")
async def get_recent_purchases_detailed(hours_back: int = 24, limit: int = 100):
    """Récupère les achats récents avec tous les détails en utilisant les données disponibles"""
    try:
        detailed_purchases = []
        
        # Récupérer tous les early adopters avec leurs profils
        adopters = db.get_early_adopters(min_confidence_score=0.0, limit=1000)
        adopter_profiles = {}
        
        for adopter in adopters:
            adopter_profiles[adopter.wallet_address] = {
                "confidence_score": adopter.confidence_score,
                "success_rate": adopter.success_rate,
                "total_picks": adopter.total_picks,
                "successful_picks": adopter.successful_picks,
                "avg_roi": adopter.avg_roi,
                "avg_entry_timing": adopter.avg_entry_timing,
                "last_activity": adopter.last_activity.isoformat()
            }
        
        # Récupérer les tokens récents
        tokens = db.get_recent_tokens(hours_back, limit)
        
        # Pour chaque token, extraire les informations d'achat
        for token in tokens:
            token_data = {
                "token_address": token['address'],
                "token_name": token.get('name', ''),
                "token_symbol": token.get('symbol', ''),
                "token_creator": token.get('creator', ''),
                "token_created_at": token.get('created_at', ''),
            }
            
            # Simuler des achats basés sur les données disponibles dans le token
            # (En attendant d'avoir accès aux vraies données d'achat)
            
            # Si le token a des early adopter buyers
            if 'early_adopter_buyers' in token and token['early_adopter_buyers']:
                for buyer_address in token['early_adopter_buyers']:
                    purchase = {
                        "signature": f"sim_{token['address'][:8]}_{buyer_address[:8]}",
                        "timestamp": token.get('created_at', ''),
                        "buyer_address": buyer_address,
                        "token_address": token['address'],
                        "sol_amount": 0.1,  # Valeur par défaut
                        "minutes_after_creation": 5,  # Valeur par défaut
                        **token_data,
                        "early_adopter_profile": adopter_profiles.get(buyer_address)
                    }
                    detailed_purchases.append(purchase)
            
            # Sinon, créer au moins une entrée pour le token
            else:
                purchase = {
                    "signature": f"unknown_{token['address'][:8]}",
                    "timestamp": token.get('created_at', ''),
                    "buyer_address": "Unknown",
                    "token_address": token['address'],
                    "sol_amount": 0.0,
                    "minutes_after_creation": 0,
                    **token_data,
                    "early_adopter_profile": None
                }
                detailed_purchases.append(purchase)
        
        # Limiter le nombre de résultats
        detailed_purchases = detailed_purchases[:limit]
        
        return {
            "purchases": detailed_purchases,
            "count": len(detailed_purchases),
            "filters": {
                "hours_back": hours_back,
                "limit": limit
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting recent purchases detailed: {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving recent purchases detailed: {str(e)}")

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


@app.get("/api/updated-tokens-stats")
async def get_updated_tokens_stats():
    """Récupère le nombre de tokens mis à jour récemment."""
    try:
        counts = db.get_updated_tokens_counts()
        return counts
    except Exception as e:
        logger.error(f"Error getting updated tokens stats: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving updated tokens stats")


@app.get("/api/transactions-detailed")
async def get_transactions_detailed(
    hours_back: int = 24, 
    limit: int = 100,
    min_sol_amount: float = 0.0,
    max_minutes_after: int = 1440,  # 24h par défaut
    early_adopters_only: bool = False
):
    """Récupère les transactions détaillées directement depuis la base de données"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Calculer la date de début
            since_date = (datetime.now() - timedelta(hours=hours_back)).isoformat()
            
            # Requête SQL pour récupérer toutes les données nécessaires
            base_query = """
                SELECT 
                    ep.signature,
                    ep.token_address,
                    ep.buyer_address,
                    ep.sol_amount,
                    ep.token_amount,
                    ep.timestamp,
                    ep.minutes_after_creation,
                    ep.market_cap_at_purchase,
                    pt.name as token_name,
                    pt.symbol as token_symbol,
                    pt.creator as token_creator,
                    pt.created_at as token_created_at,
                    ea.confidence_score,
                    ea.success_rate,
                    ea.total_picks,
                    ea.successful_picks,
                    ea.avg_roi,
                    ea.avg_entry_timing
                FROM early_purchases ep
                JOIN pump_tokens pt ON ep.token_address = pt.address
                LEFT JOIN early_adopters ea ON ep.buyer_address = ea.wallet_address
                WHERE ep.timestamp >= ?
                AND ep.sol_amount >= ?
                AND ep.minutes_after_creation <= ?
            """
            
            params = [since_date, min_sol_amount, max_minutes_after]
            
            # Ajouter filtre early adopters si nécessaire
            if early_adopters_only:
                base_query += " AND ea.wallet_address IS NOT NULL"
            
            # Ordonner et limiter
            base_query += " ORDER BY ep.timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(base_query, params)
            rows = cursor.fetchall()
            
            # Convertir en liste de dictionnaires
            transactions = []
            for row in rows:
                transaction = {
                    'signature': row['signature'],
                    'token_address': row['token_address'],
                    'buyer_address': row['buyer_address'],
                    'sol_amount': row['sol_amount'],
                    'token_amount': row['token_amount'],
                    'timestamp': row['timestamp'],
                    'minutes_after_creation': row['minutes_after_creation'],
                    'market_cap_at_purchase': row['market_cap_at_purchase'],
                    'token_name': row['token_name'],
                    'token_symbol': row['token_symbol'],
                    'token_creator': row['token_creator'],
                    'token_created_at': row['token_created_at'],
                    'early_adopter_profile': None
                }
                
                # Ajouter le profil early adopter s'il existe
                if row['confidence_score'] is not None:
                    transaction['early_adopter_profile'] = {
                        'confidence_score': row['confidence_score'],
                        'success_rate': row['success_rate'],
                        'total_picks': row['total_picks'],
                        'successful_picks': row['successful_picks'],
                        'avg_roi': row['avg_roi'],
                        'avg_entry_timing': row['avg_entry_timing']
                    }
                
                transactions.append(transaction)
            
            return {
                "transactions": transactions,
                "count": len(transactions),
                "filters": {
                    "hours_back": hours_back,
                    "limit": limit,
                    "min_sol_amount": min_sol_amount,
                    "max_minutes_after": max_minutes_after,
                    "early_adopters_only": early_adopters_only
                }
            }
            
    except Exception as e:
        logger.error(f"Error getting detailed transactions: {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving detailed transactions: {str(e)}")


@app.get("/api/debug/database-content")
async def debug_database_content():
    """Endpoint de debug pour vérifier le contenu de la base de données"""
    try:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Compter les entrées dans chaque table
            cursor.execute("SELECT COUNT(*) FROM pump_tokens")
            tokens_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM early_purchases")
            purchases_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM early_adopters")
            adopters_count = cursor.fetchone()[0]
            
            # Récupérer quelques exemples
            cursor.execute("SELECT * FROM early_purchases ORDER BY timestamp DESC LIMIT 5")
            sample_purchases = [dict(row) for row in cursor.fetchall()]
            
            cursor.execute("SELECT * FROM pump_tokens ORDER BY created_at DESC LIMIT 5")
            sample_tokens = [dict(row) for row in cursor.fetchall()]
            
            return {
                "counts": {
                    "pump_tokens": tokens_count,
                    "early_purchases": purchases_count,
                    "early_adopters": adopters_count
                },
                "samples": {
                    "recent_purchases": sample_purchases,
                    "recent_tokens": sample_tokens
                }
            }
            
    except Exception as e:
        logger.error(f"Error in debug endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/tokens-analysis")
async def get_tokens_analysis():
    """Récupère les données d'analyse des tokens directement depuis la base de données."""
    try:
        # 1. Récupérer les tokens, maintenant enrichis, depuis la DB
        recent_tokens = db.get_recent_tokens(hours_back=10000, limit=10000)
        
        # 2. La plupart de la logique d'enrichissement est maintenant en DB ou dans le service de fond.
        #    On peut simplifier cette section pour se concentrer sur les calculs qui doivent
        #    rester en temps réel (comme l'âge).
        
        enriched_tokens = []
        for token in recent_tokens:
            try:
                token_address = token['address']
                
                # Calculer l'âge en heures
                created_at = datetime.fromisoformat(token['created_at']) if isinstance(token['created_at'], str) else token['created_at']
                age_hours = (datetime.now() - created_at).total_seconds() / 3600
                
                # La plupart des données sont déjà dans `token`, il suffit de les formater.
                # On garde la récupération des achats car elle est spécifique à cette vue.
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT sol_amount, minutes_after_creation, buyer_address
                        FROM early_purchases
                        WHERE token_address = ?
                    """, (token_address,))
                    purchases = cursor.fetchall()

                total_volume_sol = sum([p['sol_amount'] for p in purchases])
                avg_entry_timing = sum([p['minutes_after_creation'] for p in purchases]) / len(purchases) if purchases else 0
                
                # Préparer le dictionnaire final, en utilisant les données de la DB
                token_data = dict(token)
                token_data['age_hours'] = round(age_hours, 2)
                token_data['volume_24h_sol'] = total_volume_sol # Note: ce n'est pas le volume sur 24h, mais le volume total des "early purchases"
                token_data['avg_entry_timing_minutes'] = round(avg_entry_timing, 1)
                token_data['unique_buyers'] = len(set([p['buyer_address'] for p in purchases]))
                
                creator_address = token.get('creator')
                if creator_address:
                    try:
                        creator_performance = creator_analyzer.analyze_creator(creator_address)
                        
                        # Ajouter les données créateur au token
                        token_data.update({
                            'creator_reputation_score': creator_performance.reputation_score,
                            'creator_risk_score': creator_performance.risk_score,
                            'creator_success_rate': creator_performance.success_rate,
                            'creator_is_blacklisted': creator_performance.is_blacklisted,
                            'creator_blacklist_reason': creator_performance.blacklist_reason,
                            'creator_total_tokens': creator_performance.total_tokens,
                            'creator_consecutive_failures': creator_performance.consecutive_failures,
                            'creator_confidence_level': creator_performance.confidence_level
                        })
                        
                    except Exception as e:
                        logger.error(f"Error analyzing creator {creator_address}: {e}")
                        # Valeurs par défaut en cas d'erreur
                        token_data.update({
                            'creator_reputation_score': 50.0,
                            'creator_risk_score': 50.0,
                            'creator_success_rate': 0.0,
                            'creator_is_blacklisted': False,
                            'creator_blacklist_reason': None,
                            'creator_total_tokens': 0,
                            'creator_consecutive_failures': 0,
                            'creator_confidence_level': 'UNKNOWN'
                        })

                enriched_tokens.append(token_data)

            except Exception as e:
                logger.error(f"Error processing token {token.get('address', 'unknown')} for analysis: {e}", exc_info=True)
                continue
        
        logger.info(f"Processed {len(enriched_tokens)} tokens from database for analysis.")
        return enriched_tokens
        
    except Exception as e:
        logger.error(f"Error in get_tokens_analysis: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error retrieving token analysis data: {str(e)}")

@app.get("/api/token/{token_address}/details")
async def get_token_details(token_address: str):
    """Récupère les détails complets d'un token avec données Pump.fun."""
    try:
        # Récupérer le token de base
        token = db.get_token_by_address(token_address)
        
        if not token:
            raise HTTPException(status_code=404, detail="Token not found")
        
        # Récupérer les données Pump.fun de manière asynchrone
        pump_token_data = None
        if pump_client:
            async with aiohttp.ClientSession() as session:
                pump_token_data = await pump_client.get_token_data(session, token_address)

        # Récupérer tous les achats pour ce token avec profils EA
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    ep.*,
                    ea.confidence_score,
                    ea.success_rate,
                    ea.total_picks,
                    ea.successful_picks,
                    ea.avg_roi
                FROM early_purchases ep
                LEFT JOIN early_adopters ea ON ep.buyer_address = ea.wallet_address
                WHERE ep.token_address = ?
                ORDER BY ep.timestamp ASC
            """, (token_address,))
            
            purchases = []
            for row in cursor.fetchall():
                purchases.append({
                    'signature': row['signature'],
                    'buyer_address': row['buyer_address'],
                    'sol_amount': row['sol_amount'],
                    'token_amount': row['token_amount'],
                    'timestamp': row['timestamp'],
                    'minutes_after_creation': row['minutes_after_creation'],
                    'market_cap_at_purchase': row['market_cap_at_purchase'],
                    'ea_profile': {
                        'confidence_score': row['confidence_score'],
                        'success_rate': row['success_rate'],
                        'total_picks': row['total_picks'],
                        'successful_picks': row['successful_picks'],
                        'avg_roi': row['avg_roi']
                    } if row['confidence_score'] else None
                })
        
        # Calculer des métriques réelles
        age_hours = (datetime.now() - token.created_at).total_seconds() / 3600
        
        # Analyse temporelle des achats
        purchase_timeline = []
        cumulative_volume = 0
        for purchase in purchases:
            cumulative_volume += purchase['sol_amount']
            purchase_timeline.append({
                'timestamp': purchase['timestamp'],
                'cumulative_volume': cumulative_volume,
                'sol_amount': purchase['sol_amount'],
                'is_early_adopter': purchase['ea_profile'] is not None
            })
        
        # Données de base
        detailed_data = {
            'address': token.address,
            'symbol': token.symbol,
            'name': token.name,
            'creator': token.creator,
            'created_at': token.created_at.isoformat(),
            'age_hours': age_hours,
            'market_cap_discovery': token.market_cap_discovery,
            
            'purchases': purchases,
            'purchase_timeline': purchase_timeline,
            'total_purchases': len(purchases),
            'ea_purchases': len([p for p in purchases if p['ea_profile']]),
            'total_volume_sol': sum([p['sol_amount'] for p in purchases]),
            'unique_buyers': len(set([p['buyer_address'] for p in purchases])),
            
            'avg_purchase_amount': sum([p['sol_amount'] for p in purchases]) / len(purchases) if purchases else 0,
            'avg_entry_timing': sum([p['minutes_after_creation'] for p in purchases]) / len(purchases) if purchases else 0,
            'fastest_entry': min([p['minutes_after_creation'] for p in purchases]) if purchases else None,
            'latest_entry': max([p['minutes_after_creation'] for p in purchases]) if purchases else None,
            
            'top_ea_buyers': [p for p in purchases if p['ea_profile'] and p['ea_profile']['confidence_score'] > 0.8],
            'ea_avg_confidence': sum([p['ea_profile']['confidence_score'] for p in purchases if p['ea_profile']]) / len([p for p in purchases if p['ea_profile']]) if any(p['ea_profile'] for p in purchases) else 0,
        }
        
        # Ajouter les données Pump.fun si disponibles (maintenant un dictionnaire)
        if pump_token_data:
            detailed_data.update({
                'pump_fun_data': {
                    'market_cap': pump_token_data.get('usd_market_cap'),
                    'bonding_curve_progress': pump_token_data.get('bonding_curve_progress'),
                    'holder_count': pump_token_data.get('holder_count'),
                    'is_verified': pump_token_data.get('complete'),
                    'logo_uri': pump_token_data.get('image_uri'),
                    'symbol_pump': pump_token_data.get('symbol'),
                    'name_pump': pump_token_data.get('name'),
                },
                'bonding_curve_data': pump_token_data # Renvoyer tout le dict pour la courbe
            })
        
        return detailed_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting token details for {token_address}: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving token details")

# Endpoint pour vérifier la santé de l'API Pump.fun
@app.get("/api/pump-fun/health")
async def get_pump_fun_health():
    """Vérifie la santé de l'API Pump.fun"""
    try:
        health_status = pump_client.get_pump_fun_health_status()
        return health_status
    except Exception as e:
        logger.error(f"Error checking Pump.fun health: {e}")
        return {"overall_healthy": False, "error": str(e)}

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


# Fonctions utilitaires
def _calculate_volume_trend(local_volume: float, pump_volume: float) -> float:
    """Calcule la tendance de volume en comparant les données locales et Pump.fun"""
    if pump_volume and pump_volume > 0:
        return ((local_volume - pump_volume) / pump_volume) * 100
    return 0.0

def _estimate_holder_growth(current_holders: int, age_hours: float) -> float:
    """Estime la croissance des holders basée sur l'âge du token"""
    if age_hours < 24:
        # Pour les tokens de moins de 24h, estimer la croissance basée sur le taux actuel
        holders_per_hour = current_holders / max(age_hours, 1)
        return (holders_per_hour / current_holders) * 100 if current_holders > 0 else 0
    else:
        # Pour les tokens plus anciens, difficile d'estimer sans données historiques
        return None


if __name__ == "__main__":
    logger.info("Starting PumpFun Tracker server with intelligent polling...")
    
    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
        log_level="info"
    )