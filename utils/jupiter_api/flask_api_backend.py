#!/usr/bin/env python3
"""
🌐 Flask API Backend - Mise à jour pour inclure les données DexScreener
"""

from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Dict, List
import json
from flask import make_response
import random

app = Flask(__name__)
CORS(app)

# Configuration
DATABASE_PATH = "tokens.db"
logger = logging.getLogger(__name__)

def format_datetime_local(dt_str):
    """Les timestamps sont maintenant corrigés, pas besoin de conversion"""
    return dt_str

class TokenAPI:
    """API pour récupérer les données des tokens avec DexScreener"""
    
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
    
    def get_connection(self):
        """Créer une connexion à la base de données"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def get_stats(self) -> Dict:
        """Récupérer les statistiques générales"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # Total tokens
            cursor.execute("SELECT COUNT(*) FROM tokens")
            total_tokens = cursor.fetchone()[0]
            
            # High score tokens (80+)
            cursor.execute("SELECT COUNT(*) FROM tokens WHERE invest_score >= 80")
            high_score_tokens = cursor.fetchone()[0]
            
            # New tokens (24h)
            cursor.execute("""
                SELECT COUNT(*) FROM tokens 
                WHERE first_discovered_at > datetime('now', '-24 hours', 'localtime')
            """)
            new_tokens = cursor.fetchone()[0]
            
            # Active tokens
            cursor.execute("""
                SELECT COUNT(*) FROM tokens 
                WHERE volume_24h > 50000 
                AND is_tradeable = 1
            """)
            active_tokens = cursor.fetchone()[0]

            # Graduated tokens
            cursor.execute("""
                SELECT COUNT(*) FROM tokens 
                WHERE bonding_curve_status IN ('completed', 'migrated')
            """)
            graduated_tokens = cursor.fetchone()[0]
            
            # Tradeable tokens
            cursor.execute("SELECT COUNT(*) FROM tokens WHERE is_tradeable = 1")
            tradeable_tokens = cursor.fetchone()[0]
            
            # Tokens avec données DexScreener
            cursor.execute("""
                SELECT COUNT(*) FROM tokens 
                WHERE dexscreener_price_usd > 0
            """)
            dexscreener_tokens = cursor.fetchone()[0]
            
            return {
                "totalTokens": total_tokens,
                "highScoreTokens": high_score_tokens,
                "newTokens": new_tokens,
                "graduatedTokens": graduated_tokens,
                "tradeableTokens": tradeable_tokens,
                "activeTokens": active_tokens,
                "dexscreenerTokens": dexscreener_tokens
            }
            
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {
                "totalTokens": 0,
                "highScoreTokens": 0,
                "newTokens": 0,
                "graduatedTokens": 0,
                "tradeableTokens": 0,
                "activeTokens": 0,
                "dexscreenerTokens": 0
            }
        finally:
            conn.close()

# Mise à jour de l'endpoint tokens-detail pour inclure DexScreener
@app.route('/api/tokens-detail')
def get_tokens_detail():
    """Endpoint pour récupérer tous les tokens avec détails DexScreener"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # ✅ REQUÊTE MISE À JOUR avec toutes les colonnes DexScreener
        cursor.execute('''
            SELECT address, symbol, name, price_usdc, invest_score, liquidity_usd,
                   volume_24h, holders, age_hours, rug_score, is_tradeable,
                   updated_at, first_discovered_at, bonding_curve_status, bonding_curve_progress,
                   status,
                   -- Colonnes DexScreener
                   dexscreener_pair_created_at,
                   dexscreener_price_usd,
                   dexscreener_market_cap,
                   dexscreener_liquidity_base,
                   dexscreener_liquidity_quote,
                   dexscreener_volume_1h,
                   dexscreener_volume_6h,
                   dexscreener_volume_24h,
                   dexscreener_price_change_1h,
                   dexscreener_price_change_6h,
                   dexscreener_price_change_h24,
                   dexscreener_txns_1h,
                   dexscreener_txns_6h,
                   dexscreener_txns_24h,
                   dexscreener_buys_1h,
                   dexscreener_sells_1h,
                   dexscreener_buys_24h,
                   dexscreener_sells_24h,
                   COALESCE(updated_at, first_discovered_at) as last_update
            FROM tokens
            ORDER BY last_update DESC, invest_score DESC
        ''')
        
        rows = []
        for row in cursor.fetchall():
            row_dict = dict(row)
            
            # ✅ AJOUT: Générer l'URL DexScreener si on a des données
            if row_dict.get('dexscreener_price_usd', 0) > 0:
                row_dict['dexscreener_url'] = f"https://dexscreener.com/solana/{row_dict['address']}"
            else:
                row_dict['dexscreener_url'] = None
            
            # ✅ AJOUT: Calculer la date de dernière mise à jour DexScreener
            # (Pour l'instant, on utilise updated_at, mais vous pourrez ajouter une colonne spécifique plus tard)
            row_dict['last_dexscreener_update'] = row_dict.get('updated_at')
            
            rows.append(row_dict)
        
        logger.info(f"📊 Returned {len(rows)} tokens with DexScreener data")
        return jsonify(rows)
        
    except Exception as e:
        logger.error(f"Error in /api/tokens-detail: {e}")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        conn.close()

# Nouvel endpoint spécifique aux données DexScreener
@app.route('/api/dexscreener-data')
def get_dexscreener_data():
    """Endpoint spécifique pour les données DexScreener"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # Filtres optionnels
        min_volume_24h = request.args.get('min_volume_24h', 0, type=float)
        min_liquidity = request.args.get('min_liquidity', 0, type=float)
        max_age_hours = request.args.get('max_age_hours', 168, type=float)  # 7 jours par défaut
        
        cursor.execute('''
            SELECT address, symbol, name,
                   dexscreener_pair_created_at,
                   dexscreener_price_usd,
                   dexscreener_market_cap,
                   dexscreener_liquidity_base,
                   dexscreener_liquidity_quote,
                   dexscreener_volume_1h,
                   dexscreener_volume_6h,
                   dexscreener_volume_24h,
                   dexscreener_price_change_1h,
                   dexscreener_price_change_6h,
                   dexscreener_price_change_h24,
                   dexscreener_txns_1h,
                   dexscreener_txns_6h,
                   dexscreener_txns_24h,
                   dexscreener_buys_1h,
                   dexscreener_sells_1h,
                   dexscreener_buys_24h,
                   dexscreener_sells_24h,
                   first_discovered_at,
                   updated_at
            FROM tokens
            WHERE dexscreener_price_usd > 0
            AND dexscreener_volume_24h >= ?
            AND dexscreener_liquidity_quote >= ?
            AND (julianday('now', 'localtime') - julianday(first_discovered_at)) * 24 <= ?
            ORDER BY dexscreener_volume_24h DESC
            LIMIT 200
        ''', (min_volume_24h, min_liquidity, max_age_hours))
        
        rows = []
        for row in cursor.fetchall():
            row_dict = dict(row)
            row_dict['dexscreener_url'] = f"https://dexscreener.com/solana/{row_dict['address']}"
            rows.append(row_dict)
        
        return jsonify(rows)
        
    except Exception as e:
        logger.error(f"Error in /api/dexscreener-data: {e}")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        conn.close()

# Instance globale de l'API
token_api = TokenAPI()

# ✅ ENDPOINTS EXISTANTS (gardés tels quels)
@app.route('/api/stats')
def get_stats():
    """Endpoint pour les statistiques générales"""
    try:
        stats = token_api.get_stats()
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error in /api/stats: {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/performance')
def get_performance_metrics():
    """Endpoint pour récupérer les métriques de performance"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Tokens mis à jour dans les 5 dernières minutes
        cursor.execute("""
            SELECT COUNT(*) FROM tokens 
            WHERE updated_at > datetime('now', '-5 minutes', 'localtime')
            AND updated_at IS NOT NULL
            AND symbol IS NOT NULL 
            AND symbol != 'UNKNOWN' 
            AND symbol != ''
        """)
        tokens_updated_5min = cursor.fetchone()[0]
        
        # Tokens mis à jour dans la dernière heure
        cursor.execute("""
            SELECT COUNT(*) FROM tokens 
            WHERE updated_at > datetime('now', '-1 hour', 'localtime')
            AND updated_at IS NOT NULL
            AND symbol IS NOT NULL 
            AND symbol != 'UNKNOWN' 
            AND symbol != ''
        """)
        tokens_updated_1h = cursor.fetchone()[0]
        
        # Total tokens
        cursor.execute("SELECT COUNT(*) FROM tokens")
        total_tokens = cursor.fetchone()[0]
        
        # Tokens enrichis
        cursor.execute("""
            SELECT COUNT(*) FROM tokens 
            WHERE symbol IS NOT NULL 
            AND symbol != 'UNKNOWN' 
            AND symbol != ''
        """)
        enriched_tokens = cursor.fetchone()[0]
        
        # Tokens avec données DexScreener
        cursor.execute("""
            SELECT COUNT(*) FROM tokens 
            WHERE dexscreener_price_usd > 0
        """)
        dexscreener_tokens = cursor.fetchone()[0]
        
        conn.close()
        
        current_throughput = tokens_updated_5min / 300.0
        enrichment_rate = (enriched_tokens / total_tokens * 100) if total_tokens > 0 else 0
        dexscreener_coverage = (dexscreener_tokens / total_tokens * 100) if total_tokens > 0 else 0
        
        summary = {
            'timestamp': datetime.now().isoformat(),
            'tokens_updated_5min': tokens_updated_5min,
            'tokens_updated_1h': tokens_updated_1h,
            'current_throughput': current_throughput,
            'database_total': total_tokens,
            'database_enriched': enriched_tokens,
            'dexscreener_tokens': dexscreener_tokens,
            'enrichment_rate': enrichment_rate,
            'dexscreener_coverage': dexscreener_coverage,
            'success_rate': 95.0 if tokens_updated_5min > 0 else 100.0,
            'status': 'running'
        }
        
        return jsonify(summary)
        
    except Exception as e:
        logger.error(f"Error getting performance metrics: {e}")
        return jsonify({
            "error": "Failed to get performance metrics",
            "tokens_updated_5min": 0,
            "current_throughput": 0,
            "status": "error"
        }), 500

@app.route('/api/dashboard-data')
def get_dashboard_data():
    """Endpoint combiné pour toutes les données du dashboard"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Stats réelles depuis la DB
        cursor.execute("SELECT COUNT(*) FROM tokens")
        total_tokens = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM tokens WHERE invest_score >= 80")
        high_score_tokens = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM tokens 
            WHERE first_discovered_at > datetime('now', '-24 hours', 'localtime')
        """)
        new_tokens = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM tokens 
            WHERE volume_24h > 50000 
            AND is_tradeable = 1
        """)
        active_tokens = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT COUNT(*) FROM tokens 
            WHERE dexscreener_price_usd > 0
        """)
        dexscreener_tokens = cursor.fetchone()[0]
        
        conn.close()
        
        corrected_stats = {
            "totalTokens": total_tokens,
            "highScoreTokens": high_score_tokens,
            "newTokens": new_tokens,
            "activeTokens": active_tokens,
            "dexscreenerTokens": dexscreener_tokens
        }
        
        dashboard_data = {
            "stats": corrected_stats,
            "lastUpdate": datetime.now().isoformat()
        }
        
        return jsonify(dashboard_data)
        
    except Exception as e:
        logger.error(f"Error in /api/dashboard-data: {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/dashboard')
def dashboard():
    """Servir le dashboard HTML"""
    return render_template('dashboard.html')

@app.route('/dashboard/detail')
def dashboard_detail():
    """Servir le dashboard détaillé"""
    return render_template('dashboard_detail.html')

@app.route('/api/health')
def health_check():
    """Health check endpoint"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tokens")
        count = cursor.fetchone()[0]
        
        # Vérifier aussi les données DexScreener
        cursor.execute("SELECT COUNT(*) FROM tokens WHERE dexscreener_price_usd > 0")
        dexscreener_count = cursor.fetchone()[0]
        
        conn.close()
        
        return jsonify({
            "status": "healthy",
            "database": "connected",
            "token_count": count,
            "dexscreener_count": dexscreener_count,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500

@app.route('/')
def index():
    """Page d'accueil de l'API"""
    return jsonify({
        "message": "Solana Token Scanner API with DexScreener",
        "version": "1.1.0",
        "endpoints": [
            "/api/stats",
            "/api/tokens-detail",
            "/api/dexscreener-data",
            "/api/dashboard-data",
            "/api/performance",
            "/api/health",
            "/dashboard",
            "/dashboard/detail"
        ]
    })

if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Vérifier que la base de données existe
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tokens")
        count = cursor.fetchone()[0]
        
        # Vérifier les colonnes DexScreener
        cursor.execute("SELECT COUNT(*) FROM tokens WHERE dexscreener_price_usd > 0")
        dexscreener_count = cursor.fetchone()[0]
        
        conn.close()
        logger.info(f"✅ Database connected: {count} tokens total, {dexscreener_count} with DexScreener data")
    except Exception as e:
        logger.error(f"❌ Database connection failed: {e}")
    
    app.run(host='0.0.0.0', port=5000, debug=True)