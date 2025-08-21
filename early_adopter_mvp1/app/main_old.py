import logging
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from polling_manager import polling_manager
from early_adopter_scorer import scorer
from database import db
from config import settings

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
    from pump_fun_client import PumpFunClient
    pump_client = PumpFunClient(logger=logger)
    logger.info("Pump.fun client initialized successfully")
except ImportError as e:
    logger.error(f"Failed to import PumpFunClient: {e}")
    pump_client = None


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
    """Récupère les données d'analyse des tokens enrichies"""
    try:
        # Récupérer les tokens récents avec les achats early adopters
        recent_tokens = db.get_recent_tokens(hours_back=48, limit=200)
        
        enriched_tokens = []
        
        for token in recent_tokens:
            try:
                token_address = token['address']
                
                # Calculer l'âge en heures
                created_at = datetime.fromisoformat(token['created_at']) if isinstance(token['created_at'], str) else token['created_at']
                age_hours = (datetime.now() - created_at).total_seconds() / 3600
                
                # Récupérer les achats détaillés pour ce token
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT ep.*, ea.confidence_score, ea.success_rate, ea.total_picks
                        FROM early_purchases ep
                        LEFT JOIN early_adopters ea ON ep.buyer_address = ea.wallet_address
                        WHERE ep.token_address = ?
                        ORDER BY ep.timestamp DESC
                    """, (token_address,))
                    
                    purchases = cursor.fetchall()
                
                # Enrichir les données early adopters avec leurs profils
                ea_buyers_enriched = []
                for purchase in purchases:
                    if purchase['confidence_score']:  # Si c'est un EA qualifié
                        ea_buyers_enriched.append({
                            'address': purchase['buyer_address'],
                            'confidence_score': purchase['confidence_score'],
                            'success_rate': purchase['success_rate'],
                            'total_picks': purchase['total_picks'],
                            'sol_amount': purchase['sol_amount'],
                            'minutes_after_creation': purchase['minutes_after_creation']
                        })
                
                # Calculer les métriques réelles basées sur les données
                total_volume_sol = sum([p['sol_amount'] for p in purchases])
                avg_entry_timing = sum([p['minutes_after_creation'] for p in purchases]) / len(purchases) if purchases else 0
                
                # Calculer la concentration des achats
                buyer_amounts = {}
                for purchase in purchases:
                    buyer = purchase['buyer_address']
                    buyer_amounts[buyer] = buyer_amounts.get(buyer, 0) + purchase['sol_amount']
                
                if buyer_amounts:
                    sorted_amounts = sorted(buyer_amounts.values(), reverse=True)
                    top_5_amount = sum(sorted_amounts[:5])
                    total_amount = sum(sorted_amounts)
                    top_5_percentage = (top_5_amount / total_amount * 100) if total_amount > 0 else 0
                else:
                    top_5_percentage = 0
                
                # Récupérer les données Pump.fun pour ce token (version synchrone)
                pump_token_data = None
                if pump_client:
                    try:
                        pump_token_data = pump_client.get_token_data(token_address)
                    except Exception as e:
                        logger.warning(f"Failed to get Pump.fun data for {token_address}: {e}", exc_info=True)
                
                # Données de base
                token_enriched = {
                    'address': token_address,
                    'symbol': token.get('symbol', 'UNK'),
                    'name': token.get('name', 'Unknown'),
                    'creator': token['creator'],
                    'created_at': token['created_at'],
                    'age_hours': round(age_hours, 2),
                    
                    # Données Early Adopter réelles
                    'early_adopter_buyers': ea_buyers_enriched,
                    'early_purchases_count': token.get('early_purchases_count', 0),
                    
                    # Données calculées à partir des achats réels
                    'volume_24h_sol': total_volume_sol,
                    'unique_buyers': len(set([p['buyer_address'] for p in purchases])),
                    'avg_entry_timing_minutes': round(avg_entry_timing, 1),
                    'top_5_holders_percentage': round(top_5_percentage, 1),
                    
                    # Calculs de tendances (24h vs total)
                    'recent_volume_24h': sum([p['sol_amount'] for p in purchases 
                                            if (datetime.now() - datetime.fromisoformat(p['timestamp'])).total_seconds() < 86400]),
                    
                    # Métriques dérivées des données réelles
                    'ea_avg_confidence': sum([ea['confidence_score'] for ea in ea_buyers_enriched]) / len(ea_buyers_enriched) if ea_buyers_enriched else 0,
                    'ea_recent_activity': len([ea for ea in ea_buyers_enriched if ea['total_picks'] > 0]),
                    'fastest_entry_minutes': min([p['minutes_after_creation'] for p in purchases]) if purchases else None,
                    'largest_purchase_sol': max([p['sol_amount'] for p in purchases]) if purchases else 0,
                }
                
                # Ajouter les données Pump.fun si disponibles
                if pump_token_data:
                    token_enriched.update({
                        # Données financières réelles de Pump.fun
                        'price_usd': pump_token_data.price_usd,
                        'market_cap_usd': pump_token_data.market_cap,
                        'bonding_curve_progress': pump_token_data.bonding_curve_progress,
                        'holders_count': pump_token_data.holder_count,
                        'volume_24h_pump': pump_token_data.volume_24h,
                        'is_pump_fun': pump_token_data.is_pump_fun,
                        'is_verified': pump_token_data.is_verified,
                        'logo_uri': pump_token_data.logo_uri,
                        'symbol': pump_token_data.symbol or token_enriched['symbol'],
                        'name': pump_token_data.name or token_enriched['name'],
                    })
                else:
                    # Valeurs par défaut si pas de données Pump.fun
                    token_enriched.update({
                        'price_usd': None,
                        'market_cap_usd': None,
                        'bonding_curve_progress': None,
                        'holders_count': None,
                        'volume_24h_pump': None,
                        'is_pump_fun': False,
                        'is_verified': False,
                        'logo_uri': None,
                    })
                
                enriched_tokens.append(token_enriched)
                
            except Exception as e:
                logger.error(f"Error enriching token {token.get('address', 'unknown')}: {e}")
                continue
        
        logger.info(f"Enriched {len(enriched_tokens)} tokens")
        return enriched_tokens
        
    except Exception as e:
        logger.error(f"Error in get_tokens_analysis: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error retrieving token analysis data: {str(e)}")

@app.get("/api/token/{token_address}/details")
async def get_token_details(token_address: str):
    """Récupère les détails complets d'un token avec données Pump.fun"""
    try:
        # Récupérer le token de base
        token = db.get_token_by_address(token_address)
        
        if not token:
            raise HTTPException(status_code=404, detail="Token not found")
        
        # Récupérer les données Pump.fun
        pump_token_data = pump_client.get_token_data(token_address)
        bonding_status = pump_client.get_token_bonding_status(token_address)
        
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
            
            # Données d'achat réelles
            'purchases': purchases,
            'purchase_timeline': purchase_timeline,
            'total_purchases': len(purchases),
            'ea_purchases': len([p for p in purchases if p['ea_profile']]),
            'total_volume_sol': sum([p['sol_amount'] for p in purchases]),
            'unique_buyers': len(set([p['buyer_address'] for p in purchases])),
            
            # Métriques temporelles
            'avg_purchase_amount': sum([p['sol_amount'] for p in purchases]) / len(purchases) if purchases else 0,
            'avg_entry_timing': sum([p['minutes_after_creation'] for p in purchases]) / len(purchases) if purchases else 0,
            'fastest_entry': min([p['minutes_after_creation'] for p in purchases]) if purchases else None,
            'latest_entry': max([p['minutes_after_creation'] for p in purchases]) if purchases else None,
            
            # Analyse Early Adopters
            'top_ea_buyers': [p for p in purchases if p['ea_profile'] and p['ea_profile']['confidence_score'] > 0.8],
            'ea_avg_confidence': sum([p['ea_profile']['confidence_score'] for p in purchases if p['ea_profile']]) / len([p for p in purchases if p['ea_profile']]) if any(p['ea_profile'] for p in purchases) else 0,
        }
        
        # Ajouter les données Pump.fun si disponibles
        if pump_token_data:
            detailed_data.update({
                'pump_fun_data': {
                    'price_usd': pump_token_data.price_usd,
                    'market_cap': pump_token_data.market_cap,
                    'bonding_curve_progress': pump_token_data.bonding_curve_progress,
                    'holder_count': pump_token_data.holder_count,
                    'volume_24h': pump_token_data.volume_24h,
                    'is_verified': pump_token_data.is_verified,
                    'logo_uri': pump_token_data.logo_uri,
                    'symbol_pump': pump_token_data.symbol,
                    'name_pump': pump_token_data.name,
                }
            })
        
        # Ajouter les données de bonding curve si disponibles
        if bonding_status:
            detailed_data.update({
                'bonding_curve_data': bonding_status
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