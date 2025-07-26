#!/usr/bin/env python3
"""
🌐 Flask API Backend - API pour alimenter le dashboard avec des données réelles
Se connecte à votre base SQLite tokens.db
"""

from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Dict, List
import json
from flask import make_response

app = Flask(__name__)
CORS(app)  # Permettre les requêtes cross-origin pour le dashboard

# Configuration
DATABASE_PATH = "tokens.db"  # Votre base de données existante
logger = logging.getLogger(__name__)

def format_datetime_local(dt_str):
    """Les timestamps sont maintenant corrigés, pas besoin de conversion"""
    return dt_str

class TokenAPI:
    """API pour récupérer les données des tokens"""
    
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
    
    def get_connection(self):
        """Créer une connexion à la base de données"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Pour accéder aux colonnes par nom
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
            
            # New tokens (24h) - avec timezone locale
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

            # Graduated tokens
            cursor.execute("""
                SELECT COUNT(*) FROM tokens 
                WHERE bonding_curve_status IN ('completed', 'migrated')
            """)
            graduated_tokens = cursor.fetchone()[0]
            
            # Tradeable tokens
            cursor.execute("SELECT COUNT(*) FROM tokens WHERE is_tradeable = 1")
            tradeable_tokens = cursor.fetchone()[0]
            
            return {
                "totalTokens": total_tokens,
                "highScoreTokens": high_score_tokens,
                "newTokens": new_tokens,
                "graduatedTokens": graduated_tokens,
                "tradeableTokens": tradeable_tokens,
                "activeTokens": active_tokens
            }
            
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {
                "totalTokens": 0,
                "highScoreTokens": 0,
                "newTokens": 0,
                "graduatedTokens": 0,
                "tradeableTokens": 0,
                "activeTokens": 0
            }
        finally:
            conn.close()
    
    def get_top_tokens(self, limit: int = 10) -> List[Dict]:
        """Récupérer les meilleurs tokens par score"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT address, symbol, name, invest_score, price_usdc, 
                       volume_24h, holders, age_hours, bonding_curve_status,
                       rug_score, liquidity_usd, first_discovered_at
                FROM tokens 
                WHERE is_tradeable = 1 
                AND invest_score IS NOT NULL
                ORDER BY invest_score DESC 
                LIMIT ?
            """, (limit,))
            
            tokens = []
            for row in cursor.fetchall():
                tokens.append({
                    "address": row["address"],
                    "symbol": row["symbol"] or "UNKNOWN",
                    "name": row["name"],
                    "score": float(row["invest_score"]) if row["invest_score"] else 0,
                    "price": float(row["price_usdc"]) if row["price_usdc"] else 0,
                    "volume": float(row["volume_24h"]) if row["volume_24h"] else 0,
                    "holders": int(row["holders"]) if row["holders"] else 0,
                    "age": float(row["age_hours"]) if row["age_hours"] else 0,
                    "status": row["bonding_curve_status"] or "unknown",
                    "rugScore": float(row["rug_score"]) if row["rug_score"] else 0,
                    "liquidity": float(row["liquidity_usd"]) if row["liquidity_usd"] else 0,
                    "discoveredAt": row["first_discovered_at"]
                })
            
            return tokens
            
        except Exception as e:
            logger.error(f"Error getting top tokens: {e}")
            return []
        finally:
            conn.close()
    
    def get_fresh_gems(self, hours: int = 6, limit: int = 10) -> List[Dict]:
        """Récupérer les nouveaux tokens à fort potentiel"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT address, symbol, name, invest_score, price_usdc, 
                       volume_24h, holders, age_hours, bonding_curve_status,
                       first_discovered_at
                FROM tokens 
                WHERE first_discovered_at > datetime('now', '-{} hours', 'localtime')
                AND invest_score >= 60
                AND is_tradeable = 1
                ORDER BY invest_score DESC, first_discovered_at DESC
                LIMIT ?
            """.format(hours), (limit,))
            
            gems = []
            for row in cursor.fetchall():
                gems.append({
                    "address": row["address"],
                    "symbol": row["symbol"] or "UNKNOWN",
                    "name": row["name"],
                    "score": float(row["invest_score"]) if row["invest_score"] else 0,
                    "price": float(row["price_usdc"]) if row["price_usdc"] else 0,
                    "volume": float(row["volume_24h"]) if row["volume_24h"] else 0,
                    "holders": int(row["holders"]) if row["holders"] else 0,
                    "age": float(row["age_hours"]) if row["age_hours"] else 0,
                    "status": row["bonding_curve_status"] or "unknown",
                    "discoveredAt": row["first_discovered_at"]
                })
            
            return gems
            
        except Exception as e:
            logger.error(f"Error getting fresh gems: {e}")
            return []
        finally:
            conn.close()
    
    def get_volume_alerts(self, limit: int = 10) -> List[Dict]:
        """Détecter les pics de volume"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT t.address, t.symbol, t.volume_24h, t.invest_score,
                       t.price_usdc, t.holders, t.first_discovered_at
                FROM tokens t
                WHERE t.volume_24h > 50000
                AND t.first_discovered_at > datetime('now', '-24 hours', 'localtime')
                AND t.is_tradeable = 1
                ORDER BY t.volume_24h DESC
                LIMIT ?
            """, (limit,))
            
            alerts = []
            for row in cursor.fetchall():
                volume = float(row["volume_24h"]) if row["volume_24h"] else 0
                volume_ratio = min(10, volume / 10000)  # Simulation
                
                alerts.append({
                    "address": row["address"],
                    "symbol": row["symbol"] or "UNKNOWN",
                    "volume": volume,
                    "volumeRatio": round(volume_ratio, 1),
                    "score": float(row["invest_score"]) if row["invest_score"] else 0,
                    "price": float(row["price_usdc"]) if row["price_usdc"] else 0,
                    "holders": int(row["holders"]) if row["holders"] else 0,
                    "discoveredAt": row["first_discovered_at"]
                })
            
            return alerts
            
        except Exception as e:
            logger.error(f"Error getting volume alerts: {e}")
            return []
        finally:
            conn.close()
    
    def get_active_tokens(self, limit: int = 10) -> List[Dict]:
        """Récupérer les tokens actifs (avec volume et liquidité)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT address, symbol, name, invest_score, price_usdc, 
                       volume_24h, holders, liquidity_usd, bonding_curve_status,
                       first_discovered_at
                FROM tokens 
                WHERE volume_24h > 50000
                AND is_tradeable = 1
                AND liquidity_usd > 10000
                ORDER BY volume_24h DESC, invest_score DESC
                LIMIT ?
            """, (limit,))
            
            active = []
            for row in cursor.fetchall():
                active.append({
                    "address": row["address"],
                    "symbol": row["symbol"] or "UNKNOWN",
                    "name": row["name"],
                    "score": float(row["invest_score"]) if row["invest_score"] else 0,
                    "price": float(row["price_usdc"]) if row["price_usdc"] else 0,
                    "volume": float(row["volume_24h"]) if row["volume_24h"] else 0,
                    "holders": int(row["holders"]) if row["holders"] else 0,
                    "liquidity": float(row["liquidity_usd"]) if row["liquidity_usd"] else 0,
                    "status": row["bonding_curve_status"] or "unknown",
                    "discoveredAt": row["first_discovered_at"]
                })
            
            return active
            
        except Exception as e:
            logger.error(f"Error getting active tokens: {e}")
            return []
        finally:
            conn.close()
    
    def get_graduated_tokens(self, limit: int = 10) -> List[Dict]:
        """Récupérer les tokens qui ont gradué récemment"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT address, symbol, name, invest_score, price_usdc, 
                       volume_24h, holders, bonding_curve_status,
                       raydium_pool_address, first_discovered_at
                FROM tokens 
                WHERE bonding_curve_status IN ('completed', 'migrated')
                AND first_discovered_at > datetime('now', '-48 hours', 'localtime')
                ORDER BY invest_score DESC, first_discovered_at DESC
                LIMIT ?
            """, (limit,))
            
            graduated = []
            for row in cursor.fetchall():
                graduated.append({
                    "address": row["address"],
                    "symbol": row["symbol"] or "UNKNOWN",
                    "name": row["name"],
                    "score": float(row["invest_score"]) if row["invest_score"] else 0,
                    "price": float(row["price_usdc"]) if row["price_usdc"] else 0,
                    "volume": float(row["volume_24h"]) if row["volume_24h"] else 0,
                    "holders": int(row["holders"]) if row["holders"] else 0,
                    "status": row["bonding_curve_status"],
                    "raydiumPool": row["raydium_pool_address"],
                    "discoveredAt": row["first_discovered_at"]
                })
            
            return graduated
            
        except Exception as e:
            logger.error(f"Error getting graduated tokens: {e}")
            return []
        finally:
            conn.close()
    
    def get_token_details(self, address: str) -> Dict:
        """Récupérer les détails d'un token spécifique"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM tokens WHERE address = ?
            """, (address,))
            
            row = cursor.fetchone()
            if row:
                return dict(row)
            return {}
            
        except Exception as e:
            logger.error(f"Error getting token details for {address}: {e}")
            return {}
        finally:
            conn.close()

# Instance globale de l'API
token_api = TokenAPI()

# Routes Flask
@app.route('/api/stats')
def get_stats():
    """Endpoint pour les statistiques générales"""
    try:
        stats = token_api.get_stats()
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error in /api/stats: {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/tokens-detail')
def get_tokens_detail():
    """Endpoint pour récupérer tous les tokens avec détails"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT address, symbol, name, price_usdc, invest_score, liquidity_usd,
                   volume_24h, holders, age_hours, rug_score, is_tradeable,
                   updated_at, first_discovered_at,
                   COALESCE(updated_at, first_discovered_at) as last_update
            FROM tokens
            ORDER BY last_update DESC, invest_score DESC
        ''')
        
        rows = []
        for row in cursor.fetchall():
            row_dict = dict(row)
            # Les timestamps sont maintenant corrects, pas besoin de conversion
            rows.append(row_dict)
        
        return jsonify(rows)
        
    except Exception as e:
        logger.error(f"Error in /api/tokens-detail: {e}")
        return jsonify({"error": "Internal server error"}), 500
    finally:
        conn.close()

@app.route('/dashboard/invest-ready')
def invest_ready_page():
    return render_template('invest_ready.html')

@app.route('/api/favorites', methods=['GET'])
def get_favorites():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT t.* FROM tokens t
        JOIN favorites f ON t.address = f.address
        ORDER BY f.added_at DESC
    ''')
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify(rows)

@app.route('/api/favorites/<address>', methods=['POST', 'DELETE'])
def toggle_favorite(address):
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    if request.method == 'POST':
        cursor.execute('INSERT OR IGNORE INTO favorites(address) VALUES(?)', (address,))
    else:
        cursor.execute('DELETE FROM favorites WHERE address = ?', (address,))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route('/api/invest-ready')
def get_invest_ready():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT address, symbol, name, price_usdc, invest_score, liquidity_usd,
               volume_24h, holders, age_hours, rug_score, first_discovered_at
        FROM tokens
        WHERE invest_score >= 75
          AND rug_score < 30
          AND liquidity_usd > 50000
        ORDER BY invest_score DESC
        LIMIT 50
    ''')
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify(rows)

@app.route('/api/export-ready')
def export_ready():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT address, symbol, price_usdc, invest_score, liquidity_usd,
               volume_24h, holders, age_hours, first_discovered_at
        FROM tokens
        WHERE invest_score >= 75
          AND rug_score < 30
          AND liquidity_usd > 50000
        ORDER BY invest_score DESC
    ''')
    rows = cursor.fetchall()
    conn.close()

    # Génération CSV
    import io, csv
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["address","symbol","price_usdc","invest_score","liquidity_usd","volume_24h","holders","age_hours","first_discovered_at"])
    for r in rows:
        writer.writerow(list(r))
    csv_data = output.getvalue()
    output.close()

    response = make_response(csv_data)
    response.headers["Content-Disposition"] = "attachment; filename=invest_ready.csv"
    response.headers["Content-type"] = "text/csv"
    return response

@app.route('/dashboard/detail')
def dashboard_detail():
    return render_template('dashboard_detail.html')

@app.route('/api/top-tokens')
def get_top_tokens():
    """Endpoint pour les meilleurs tokens"""
    try:
        limit = request.args.get('limit', 10, type=int)
        tokens = token_api.get_top_tokens(limit)
        return jsonify(tokens)
    except Exception as e:
        logger.error(f"Error in /api/top-tokens: {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/fresh-gems')
def get_fresh_gems():
    """Endpoint pour les nouveaux gems"""
    try:
        hours = request.args.get('hours', 6, type=int)
        limit = request.args.get('limit', 10, type=int)
        gems = token_api.get_fresh_gems(hours, limit)
        return jsonify(gems)
    except Exception as e:
        logger.error(f"Error in /api/fresh-gems: {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/volume-alerts')
def get_volume_alerts():
    """Endpoint pour les alertes de volume"""
    try:
        limit = request.args.get('limit', 10, type=int)
        alerts = token_api.get_volume_alerts(limit)
        return jsonify(alerts)
    except Exception as e:
        logger.error(f"Error in /api/volume-alerts: {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/graduated')
def get_graduated():
    """Endpoint pour les tokens gradués"""
    try:
        limit = request.args.get('limit', 10, type=int)
        graduated = token_api.get_graduated_tokens(limit)
        return jsonify(graduated)
    except Exception as e:
        logger.error(f"Error in /api/graduated: {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/token/<address>')
def get_token_details(address):
    """Endpoint pour les détails d'un token"""
    try:
        details = token_api.get_token_details(address)
        if details:
            return jsonify(details)
        return jsonify({"error": "Token not found"}), 404
    except Exception as e:
        logger.error(f"Error in /api/token/{address}: {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/dashboard-data')
def get_dashboard_data():
    """Endpoint combiné pour toutes les données du dashboard"""
    try:
        dashboard_data = {
            "stats": token_api.get_stats(),
            "topTokens": token_api.get_top_tokens(5),
            "newGems": token_api.get_fresh_gems(6, 5),
            "volumeAlerts": token_api.get_volume_alerts(5),
            "activeTokens": token_api.get_active_tokens(5),
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

@app.route('/api/health')
def health_check():
    """Health check endpoint"""
    try:
        # Test database connection
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tokens")
        count = cursor.fetchone()[0]
        conn.close()
        
        return jsonify({
            "status": "healthy",
            "database": "connected",
            "token_count": count,
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
        "message": "Solana Token Scanner API",
        "version": "1.0.0",
        "endpoints": [
            "/api/stats",
            "/api/top-tokens",
            "/api/fresh-gems", 
            "/api/volume-alerts",
            "/api/graduated",
            "/api/token/<address>",
            "/api/dashboard-data",
            "/api/health"
        ]
    })

# Configuration du logging
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
        conn.close()
        logger.info(f"Database connected successfully. Found {count} tokens.")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        logger.info("Make sure your token scanner is running and has created the database.")
    
    # Lancer le serveur Flask
    app.run(
        host='0.0.0.0',  # Accessible depuis l'extérieur
        port=5000,       # Port par défaut
        debug=True       # Mode debug pour le développement
    )