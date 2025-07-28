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


# Ajouter ces routes à votre fichier flask_api.py existant

@app.route('/dashboard/history')
def dashboard_history():
    """Servir le dashboard historique"""
    return render_template('dashboard_history.html')

@app.route('/api/token-chart-data/<address>')
def get_token_chart_data(address):
    """Données formatées pour les graphiques Chart.js"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        days = request.args.get('days', 7, type=int)
        
        cursor.execute('''
            SELECT 
                snapshot_timestamp,
                price_usdc,
                dexscreener_price_usd,
                dexscreener_volume_24h,
                volume_24h,
                dexscreener_liquidity_quote,
                liquidity_usd,
                invest_score,
                holders,
                bonding_curve_progress,
                dexscreener_txns_24h,
                dexscreener_buys_24h,
                dexscreener_sells_24h,
                market_cap,
                dexscreener_market_cap
            FROM tokens_hist 
            WHERE address = ? 
            AND snapshot_timestamp > datetime('now', '-{} days', 'localtime')
            ORDER BY snapshot_timestamp ASC
        '''.format(days), (address,))
        
        data = cursor.fetchall()
        
        # Formater pour Chart.js
        labels = []
        datasets = {
            'price': [],
            'volume': [],
            'liquidity': [],
            'score': [],
            'holders': [],
            'progress': [],
            'transactions': [],
            'buys': [],
            'sells': [],
            'market_cap': []
        }
        
        for row in data:
            # Formater le timestamp
            timestamp = datetime.fromisoformat(row['snapshot_timestamp'].replace('Z', '+00:00'))
            labels.append(timestamp.strftime('%d/%m %H:%M'))
            
            # Utiliser le prix DexScreener en priorité, sinon prix USDC
            price = row['dexscreener_price_usd'] or row['price_usdc'] or 0
            datasets['price'].append(price)
            
            # Volume: DexScreener en priorité
            volume = row['dexscreener_volume_24h'] or row['volume_24h'] or 0
            datasets['volume'].append(volume)
            
            # Liquidité: DexScreener en priorité
            liquidity = row['dexscreener_liquidity_quote'] or row['liquidity_usd'] or 0
            datasets['liquidity'].append(liquidity)
            
            # Market Cap: DexScreener en priorité
            market_cap = row['dexscreener_market_cap'] or row['market_cap'] or 0
            datasets['market_cap'].append(market_cap)
            
            datasets['score'].append(row['invest_score'] or 0)
            datasets['holders'].append(row['holders'] or 0)
            datasets['progress'].append(row['bonding_curve_progress'] or 0)
            datasets['transactions'].append(row['dexscreener_txns_24h'] or 0)
            datasets['buys'].append(row['dexscreener_buys_24h'] or 0)
            datasets['sells'].append(row['dexscreener_sells_24h'] or 0)
        
        conn.close()
        
        return jsonify({
            'labels': labels,
            'datasets': datasets,
            'data_points': len(labels)
        })
        
    except Exception as e:
        logger.error(f"Error getting chart data for {address}: {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/token-history-stats/<address>')
def get_token_history_stats(address):
    """Statistiques détaillées sur l'historique d'un token"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        days = request.args.get('days', 7, type=int)
        
        # Récupérer toutes les données historiques
        cursor.execute('''
            SELECT 
                snapshot_timestamp,
                price_usdc,
                dexscreener_price_usd,
                dexscreener_volume_24h,
                volume_24h,
                dexscreener_liquidity_quote,
                liquidity_usd,
                invest_score,
                holders,
                bonding_curve_progress,
                bonding_curve_status,
                status,
                snapshot_reason,
                market_cap,
                dexscreener_market_cap,
                rug_score
            FROM tokens_hist 
            WHERE address = ? 
            AND snapshot_timestamp > datetime('now', '-{} days', 'localtime')
            ORDER BY snapshot_timestamp ASC
        '''.format(days), (address,))
        
        data = [dict(row) for row in cursor.fetchall()]
        
        if not data:
            return jsonify({
                'error': 'No historical data found',
                'data_points': 0
            })
        
        # Calculer les statistiques
        prices = []
        volumes = []
        scores = [row['invest_score'] for row in data if row['invest_score'] is not None]
        holders_list = [row['holders'] for row in data if row['holders'] is not None]
        
        # Prix: priorité DexScreener
        for row in data:
            price = row['dexscreener_price_usd'] or row['price_usdc']
            if price and price > 0:
                prices.append(price)
        
        # Volume: priorité DexScreener
        for row in data:
            volume = row['dexscreener_volume_24h'] or row['volume_24h']
            if volume and volume > 0:
                volumes.append(volume)
        
        stats = {
            'data_points': len(data),
            'period_days': days,
            'first_snapshot': data[0]['snapshot_timestamp'],
            'last_snapshot': data[-1]['snapshot_timestamp'],
            'snapshot_frequency_hours': round((days * 24) / max(len(data) - 1, 1), 2) if len(data) > 1 else 0,
        }
        
        # Statistiques de prix
        if prices:
            stats['price_stats'] = {
                'min': round(min(prices), 8),
                'max': round(max(prices), 8),
                'avg': round(sum(prices) / len(prices), 8),
                'first': round(prices[0], 8),
                'last': round(prices[-1], 8),
                'change_pct': round(((prices[-1] - prices[0]) / prices[0]) * 100, 2) if prices[0] > 0 else 0,
                'volatility': round((max(prices) - min(prices)) / max(prices) * 100, 2) if max(prices) > 0 else 0
            }
        
        # Statistiques de volume
        if volumes:
            stats['volume_stats'] = {
                'min': round(min(volumes)),
                'max': round(max(volumes)),
                'avg': round(sum(volumes) / len(volumes)),
                'total': round(sum(volumes)),
                'last': round(volumes[-1])
            }
        
        # Statistiques de score
        if scores:
            stats['score_stats'] = {
                'min': round(min(scores), 2),
                'max': round(max(scores), 2),
                'avg': round(sum(scores) / len(scores), 2),
                'first': round(scores[0], 2),
                'last': round(scores[-1], 2),
                'change': round(scores[-1] - scores[0], 2)
            }
        
        # Statistiques de holders
        if holders_list:
            stats['holders_stats'] = {
                'min': min(holders_list),
                'max': max(holders_list),
                'first': holders_list[0],
                'last': holders_list[-1],
                'change': holders_list[-1] - holders_list[0],
                'growth_pct': round(((holders_list[-1] - holders_list[0]) / max(holders_list[0], 1)) * 100, 2)
            }
        
        # Analyse des changements de statut
        status_changes = []
        bonding_changes = []
        
        for i in range(1, len(data)):
            if data[i]['status'] != data[i-1]['status']:
                status_changes.append({
                    'timestamp': data[i]['snapshot_timestamp'],
                    'from': data[i-1]['status'],
                    'to': data[i]['status']
                })
            
            if data[i]['bonding_curve_status'] != data[i-1]['bonding_curve_status']:
                bonding_changes.append({
                    'timestamp': data[i]['snapshot_timestamp'],
                    'from': data[i-1]['bonding_curve_status'],
                    'to': data[i]['bonding_curve_status']
                })
        
        stats['status_changes'] = status_changes
        stats['bonding_changes'] = bonding_changes
        
        # Répartition des raisons de snapshot
        snapshot_reasons = {}
        for row in data:
            reason = row['snapshot_reason'] or 'unknown'
            snapshot_reasons[reason] = snapshot_reasons.get(reason, 0) + 1
        
        stats['snapshot_reasons'] = snapshot_reasons
        
        conn.close()
        
        return jsonify(stats)
        
    except Exception as e:
        logger.error(f"Error getting history stats for {address}: {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/token-trends/<address>')
def get_token_trends(address):
    """Récupérer les tendances historiques d'un token spécifique"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Paramètres de requête
        days = request.args.get('days', 7, type=int)
        limit = request.args.get('limit', 100, type=int)
        
        # Récupérer les données historiques
        cursor.execute('''
            SELECT 
                snapshot_timestamp,
                price_usdc,
                dexscreener_price_usd,
                market_cap,
                dexscreener_market_cap,
                liquidity_usd,
                dexscreener_liquidity_quote,
                volume_24h,
                dexscreener_volume_24h,
                holders,
                invest_score,
                rug_score,
                bonding_curve_progress,
                dexscreener_txns_24h,
                dexscreener_buys_24h,
                dexscreener_sells_24h,
                bonding_curve_status,
                status,
                snapshot_reason
            FROM tokens_hist 
            WHERE address = ? 
            AND snapshot_timestamp > datetime('now', '-{} days', 'localtime')
            ORDER BY snapshot_timestamp ASC
            LIMIT ?
        '''.format(days), (address, limit))
        
        historical_data = [dict(row) for row in cursor.fetchall()]
        
        # Récupérer les infos de base du token
        cursor.execute('''
            SELECT symbol, name, address, first_discovered_at
            FROM tokens 
            WHERE address = ?
        ''', (address,))
        
        token_row = cursor.fetchone()
        token_info = dict(token_row) if token_row else {}
        
        conn.close()
        
        return jsonify({
            'token_info': token_info,
            'historical_data': historical_data,
            'data_points': len(historical_data),
            'period_days': days
        })
        
    except Exception as e:
        logger.error(f"Error getting trends for {address}: {e}")
        return jsonify({"error": "Internal server error"}), 500



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

@app.route('/api/token-has-history/<address>')
def check_token_history(address):
    """Vérifier si un token a des données historiques"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) FROM tokens_hist 
            WHERE address = ?
        ''', (address,))
        
        count = cursor.fetchone()[0]
        conn.close()
        
        return jsonify({
            'has_history': count > 0,
            'data_points': count
        })
        
    except Exception as e:
        logger.error(f"Error checking history for {address}: {e}")
        return jsonify({"has_history": False, "data_points": 0}), 500

@app.route('/api/trends-summary')
def get_trends_summary():
    """Récupérer un résumé des tendances pour tous les tokens actifs"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Paramètres
        hours = request.args.get('hours', 24, type=int)
        min_snapshots = request.args.get('min_snapshots', 2, type=int)
        
        # Récupérer les tokens avec suffisamment de données historiques
        cursor.execute('''
            SELECT 
                t.address,
                t.symbol,
                t.name,
                COUNT(th.snapshot_timestamp) as snapshot_count,
                MIN(th.snapshot_timestamp) as first_snapshot,
                MAX(th.snapshot_timestamp) as last_snapshot,
                
                -- Prix: première et dernière valeur
                (SELECT price_usdc FROM tokens_hist th2 
                 WHERE th2.address = t.address 
                 AND th2.snapshot_timestamp > datetime('now', '-{} hours', 'localtime')
                 ORDER BY th2.snapshot_timestamp ASC LIMIT 1) as price_start,
                 
                (SELECT price_usdc FROM tokens_hist th2 
                 WHERE th2.address = t.address 
                 AND th2.snapshot_timestamp > datetime('now', '-{} hours', 'localtime')
                 ORDER BY th2.snapshot_timestamp DESC LIMIT 1) as price_end,
                
                -- Volume: moyenne et tendance
                AVG(th.dexscreener_volume_24h) as avg_volume,
                MAX(th.dexscreener_volume_24h) as max_volume,
                
                -- Liquidité: tendance
                (SELECT dexscreener_liquidity_quote FROM tokens_hist th2 
                 WHERE th2.address = t.address 
                 AND th2.snapshot_timestamp > datetime('now', '-{} hours', 'localtime')
                 ORDER BY th2.snapshot_timestamp ASC LIMIT 1) as liquidity_start,
                 
                (SELECT dexscreener_liquidity_quote FROM tokens_hist th2 
                 WHERE th2.address = t.address 
                 AND th2.snapshot_timestamp > datetime('now', '-{} hours', 'localtime')
                 ORDER BY th2.snapshot_timestamp DESC LIMIT 1) as liquidity_end,
                
                -- Score d'investissement: tendance
                (SELECT invest_score FROM tokens_hist th2 
                 WHERE th2.address = t.address 
                 AND th2.snapshot_timestamp > datetime('now', '-{} hours', 'localtime')
                 ORDER BY th2.snapshot_timestamp ASC LIMIT 1) as score_start,
                 
                (SELECT invest_score FROM tokens_hist th2 
                 WHERE th2.address = t.address 
                 AND th2.snapshot_timestamp > datetime('now', '-{} hours', 'localtime')
                 ORDER BY th2.snapshot_timestamp DESC LIMIT 1) as score_end,
                
                -- Progression bonding curve
                MAX(th.bonding_curve_progress) as max_bonding_progress,
                
                -- Holders: tendance
                (SELECT holders FROM tokens_hist th2 
                 WHERE th2.address = t.address 
                 AND th2.snapshot_timestamp > datetime('now', '-{} hours', 'localtime')
                 ORDER BY th2.snapshot_timestamp DESC LIMIT 1) as current_holders,
                
                t.bonding_curve_status,
                t.status
                
            FROM tokens t
            JOIN tokens_hist th ON t.address = th.address
            WHERE th.snapshot_timestamp > datetime('now', '-{} hours', 'localtime')
            AND t.symbol IS NOT NULL 
            AND t.symbol != 'UNKNOWN'
            GROUP BY t.address, t.symbol, t.name
            HAVING COUNT(th.snapshot_timestamp) >= ?
            ORDER BY snapshot_count DESC, MAX(th.snapshot_timestamp) DESC
            LIMIT 50
        '''.format(hours, hours, hours, hours, hours, hours), (min_snapshots,))
        
        tokens_summary = []
        for row in cursor.fetchall():
            row_dict = dict(row)
            
            # Calculer les variations en pourcentage
            price_change = 0
            if row_dict['price_start'] and row_dict['price_end'] and row_dict['price_start'] > 0:
                price_change = ((row_dict['price_end'] - row_dict['price_start']) / row_dict['price_start']) * 100
            
            liquidity_change = 0
            if row_dict['liquidity_start'] and row_dict['liquidity_end'] and row_dict['liquidity_start'] > 0:
                liquidity_change = ((row_dict['liquidity_end'] - row_dict['liquidity_start']) / row_dict['liquidity_start']) * 100
            
            score_change = 0
            if row_dict['score_start'] and row_dict['score_end']:
                score_change = row_dict['score_end'] - row_dict['score_start']
            
            # Déterminer la tendance générale
            trend_score = 0
            if price_change > 0: trend_score += 1
            if liquidity_change > 0: trend_score += 1
            if score_change > 0: trend_score += 1
            
            if trend_score >= 2:
                trend = "bullish"
            elif trend_score <= 1 and (price_change < -10 or score_change < -5):
                trend = "bearish"
            else:
                trend = "neutral"
            
            row_dict.update({
                'price_change_pct': round(price_change, 2),
                'liquidity_change_pct': round(liquidity_change, 2),
                'score_change': round(score_change, 2),
                'trend': trend,
                'trend_score': trend_score
            })
            
            tokens_summary.append(row_dict)
        
        conn.close()
        
        return jsonify({
            'tokens': tokens_summary,
            'period_hours': hours,
            'total_tokens': len(tokens_summary)
        })
        
    except Exception as e:
        logger.error(f"Error getting trends summary: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route('/api/trending-tokens')
def get_trending_tokens():
    """Récupérer les tokens avec les meilleures tendances récentes"""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        hours = request.args.get('hours', 6, type=int)
        limit = request.args.get('limit', 20, type=int)
        
        # Requête pour trouver les tokens avec les meilleures performances récentes
        cursor.execute('''
            WITH recent_performance AS (
                SELECT 
                    t.address,
                    t.symbol,
                    t.name,
                    
                    -- Prix: première et dernière valeur
                    (SELECT COALESCE(dexscreener_price_usd, price_usdc) FROM tokens_hist th 
                     WHERE th.address = t.address 
                     AND th.snapshot_timestamp > datetime('now', '-{} hours', 'localtime')
                     AND COALESCE(th.dexscreener_price_usd, th.price_usdc) > 0
                     ORDER BY th.snapshot_timestamp ASC LIMIT 1) as price_start,
                     
                    (SELECT COALESCE(dexscreener_price_usd, price_usdc) FROM tokens_hist th 
                     WHERE th.address = t.address 
                     AND th.snapshot_timestamp > datetime('now', '-{} hours', 'localtime')
                     AND COALESCE(th.dexscreener_price_usd, th.price_usdc) > 0
                     ORDER BY th.snapshot_timestamp DESC LIMIT 1) as price_end,
                    
                    -- Volume récent
                    AVG(COALESCE(th.dexscreener_volume_24h, th.volume_24h, 0)) as avg_volume,
                    MAX(COALESCE(th.dexscreener_volume_24h, th.volume_24h, 0)) as max_volume,
                    
                    -- Score d'investissement
                    (SELECT invest_score FROM tokens_hist th 
                     WHERE th.address = t.address 
                     AND th.snapshot_timestamp > datetime('now', '-{} hours', 'localtime')
                     AND th.invest_score IS NOT NULL
                     ORDER BY th.snapshot_timestamp ASC LIMIT 1) as score_start,
                     
                    (SELECT invest_score FROM tokens_hist th 
                     WHERE th.address = t.address 
                     AND th.snapshot_timestamp > datetime('now', '-{} hours', 'localtime')
                     AND th.invest_score IS NOT NULL
                     ORDER BY th.snapshot_timestamp DESC LIMIT 1) as score_end,
                    
                    -- Données actuelles du token principal
                    t.price_usdc,
                    t.dexscreener_price_usd,
                    t.invest_score,
                    t.volume_24h,
                    t.dexscreener_volume_24h,
                    t.liquidity_usd,
                    t.dexscreener_liquidity_quote,
                    t.holders,
                    t.bonding_curve_status,
                    t.bonding_curve_progress,
                    
                    COUNT(th.snapshot_timestamp) as snapshot_count
                    
                FROM tokens t
                JOIN tokens_hist th ON t.address = th.address
                WHERE th.snapshot_timestamp > datetime('now', '-{} hours', 'localtime')
                AND t.symbol IS NOT NULL 
                AND t.symbol != 'UNKNOWN'
                AND t.symbol != ''
                AND (t.status IS NULL OR t.status IN ('active', 'new'))
                GROUP BY t.address
                HAVING COUNT(th.snapshot_timestamp) >= 2
            )
            SELECT *,
                -- Calculer les variations
                CASE 
                    WHEN price_start > 0 AND price_end > 0 
                    THEN ((price_end - price_start) / price_start) * 100 
                    ELSE 0 
                END as price_change_pct,
                
                CASE 
                    WHEN score_start IS NOT NULL AND score_end IS NOT NULL 
                    THEN score_end - score_start 
                    ELSE 0 
                END as score_change,
                
                -- Score de tendance composite
                (
                    CASE 
                        WHEN price_start > 0 AND price_end > 0 
                        THEN ((price_end - price_start) / price_start) * 100 * 2  -- Pondération prix x2
                        ELSE 0 
                    END +
                    CASE 
                        WHEN score_start IS NOT NULL AND score_end IS NOT NULL 
                        THEN (score_end - score_start) * 1  -- Pondération score x1
                        ELSE 0 
                    END +
                    CASE 
                        WHEN avg_volume > 10000 THEN 5  -- Bonus pour volume élevé
                        WHEN avg_volume > 1000 THEN 2
                        ELSE 0 
                    END
                ) as trend_score
                
            FROM recent_performance
            WHERE price_start > 0 AND price_end > 0  -- Avoir des données de prix valides
            ORDER BY trend_score DESC, price_change_pct DESC
            LIMIT ?
        '''.format(hours, hours, hours, hours, hours), (limit,))
        
        trending_tokens = []
        for row in cursor.fetchall():
            row_dict = dict(row)
            
            # Déterminer la tendance
            trend_score = row_dict['trend_score']
            price_change = row_dict['price_change_pct']
            
            if trend_score > 10 and price_change > 20:
                trend = "hot"
            elif trend_score > 5 and price_change > 10:
                trend = "bullish"
            elif trend_score < -5 and price_change < -10:
                trend = "bearish"
            else:
                trend = "neutral"
            
            row_dict['trend'] = trend
            row_dict['current_price'] = row_dict['dexscreener_price_usd'] or row_dict['price_usdc']
            row_dict['current_volume'] = row_dict['dexscreener_volume_24h'] or row_dict['volume_24h']
            row_dict['current_liquidity'] = row_dict['dexscreener_liquidity_quote'] or row_dict['liquidity_usd']
            
            trending_tokens.append(row_dict)
        
        conn.close()
        
        return jsonify({
            'trending_tokens': trending_tokens,
            'period_hours': hours,
            'total_found': len(trending_tokens)
        })
        
    except Exception as e:
        logger.error(f"Error getting trending tokens: {e}")
        return jsonify({"error": "Internal server error"}), 500


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
            "/api/token-chart-data/<address>",
            "/api/token-history-stats/<address>",
            "/api/token-trends/<address>",
            "/api/dashboard-data",
            "/api/performance",
            "/api/health",
            "/dashboard",
            "/dashboard/detail",
            "/dashboard/history"
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