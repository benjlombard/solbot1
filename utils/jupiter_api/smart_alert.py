#!/usr/bin/env python3
"""
🔔 Smart Alert System - Système d'alertes intelligentes pour tokens
"""

import asyncio
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List
import logging

class SmartAlerts:
    def __init__(self, database_path: str = "tokens.db"):
        self.database_path = database_path
        self.alert_thresholds = {
            "volume_spike": 5.0,  # Multiplication par 5
            "price_spike": 2.0,   # +200%
            "holder_growth": 0.5, # +50% holders
            "liquidity_jump": 3.0, # Liquidity x3
            "new_gem_score": 85,   # Score minimum pour "gem"
        }
    
    async def check_volume_spikes(self) -> List[Dict]:
        """Détecter les pics de volume inhabituels"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        alerts = []
        try:
            # Comparer volume actuel vs moyenne des 24h précédentes
            cursor.execute('''
                SELECT t.address, t.symbol, t.volume_24h, 
                       AVG(th.volume_24h) as avg_volume,
                       (t.volume_24h / AVG(th.volume_24h)) as volume_ratio
                FROM tokens t
                JOIN token_history th ON t.address = th.address
                WHERE th.timestamp > ? 
                AND t.volume_24h > 0 
                AND AVG(th.volume_24h) > 0
                GROUP BY t.address
                HAVING volume_ratio > ?
                ORDER BY volume_ratio DESC
                LIMIT 10
            ''', (
                int((datetime.now() - timedelta(hours=24)).timestamp()),
                self.alert_thresholds["volume_spike"]
            ))
            
            for row in cursor.fetchall():
                alerts.append({
                    "type": "VOLUME_SPIKE",
                    "address": row[0],
                    "symbol": row[1],
                    "current_volume": row[2],
                    "avg_volume": row[3],
                    "ratio": row[4],
                    "message": f"🔥 {row[1]} VOLUME SPIKE: {row[4]:.1f}x normal volume!"
                })
        
        finally:
            conn.close()
        
        return alerts
    
    async def check_new_gems(self) -> List[Dict]:
        """Identifier les nouveaux tokens à fort potentiel"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        alerts = []
        try:
            cursor.execute('''
                SELECT address, symbol, invest_score, price_usdc, 
                       age_hours, bonding_curve_status, holders
                FROM tokens 
                WHERE invest_score >= ? 
                AND first_discovered_at > datetime('now', '-6 hours')
                AND is_tradeable = 1
                ORDER BY invest_score DESC
                LIMIT 5
            ''', (self.alert_thresholds["new_gem_score"],))
            
            for row in cursor.fetchall():
                alerts.append({
                    "type": "NEW_GEM",
                    "address": row[0],
                    "symbol": row[1],
                    "score": row[2],
                    "price": row[3],
                    "age": row[4],
                    "status": row[5],
                    "holders": row[6],
                    "message": f"💎 NEW GEM: {row[1]} (Score: {row[2]}) - Age: {row[4]:.1f}h"
                })
        
        finally:
            conn.close()
        
        return alerts
    
    async def check_graduation_alerts(self) -> List[Dict]:
        """Alertes pour tokens qui graduent de pump.fun"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        alerts = []
        try:
            cursor.execute('''
                SELECT address, symbol, invest_score, volume_24h, holders
                FROM tokens 
                WHERE bonding_curve_status IN ('completed', 'migrated')
                AND first_discovered_at > datetime('now', '-2 hours')
                ORDER BY invest_score DESC
                LIMIT 5
            ''')
            
            for row in cursor.fetchall():
                alerts.append({
                    "type": "GRADUATION",
                    "address": row[0],
                    "symbol": row[1],
                    "score": row[2],
                    "volume": row[3],
                    "holders": row[4],
                    "message": f"🚀 GRADUATION: {row[1]} migrated to Raydium! Score: {row[2]}"
                })
        
        finally:
            conn.close()
        
        return alerts

class TrendAnalyzer:
    """Analyser les tendances de marché"""
    
    def __init__(self, database_path: str = "tokens.db"):
        self.database_path = database_path
    
    async def get_market_sentiment(self) -> Dict:
        """Calculer le sentiment général du marché"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_tokens,
                    AVG(invest_score) as avg_score,
                    COUNT(CASE WHEN price_change_24h > 0 THEN 1 END) as pumping_count,
                    COUNT(CASE WHEN volume_24h > 50000 THEN 1 END) as high_volume_count,
                    COUNT(CASE WHEN bonding_curve_status = 'completed' THEN 1 END) as graduated_count
                FROM tokens 
                WHERE first_discovered_at > datetime('now', '-24 hours')
                AND is_tradeable = 1
            ''')
            
            row = cursor.fetchone()
            if row:
                total = row[0]
                sentiment = "BULLISH" if row[1] > 60 else "BEARISH" if row[1] < 40 else "NEUTRAL"
                
                return {
                    "sentiment": sentiment,
                    "total_tokens": total,
                    "avg_score": row[1],
                    "pumping_ratio": (row[2] / total * 100) if total > 0 else 0,
                    "high_volume_ratio": (row[3] / total * 100) if total > 0 else 0,
                    "graduation_count": row[4]
                }
        
        finally:
            conn.close()
        
        return {"sentiment": "UNKNOWN"}
    
    async def get_trending_patterns(self) -> List[Dict]:
        """Identifier les patterns tendance"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        patterns = []
        try:
            # Pattern 1: Tokens avec croissance constante
            cursor.execute('''
                SELECT t.address, t.symbol, t.invest_score,
                       COUNT(th.timestamp) as data_points,
                       (MAX(th.price_usdc) - MIN(th.price_usdc)) / MIN(th.price_usdc) * 100 as price_growth
                FROM tokens t
                JOIN token_history th ON t.address = th.address
                WHERE th.timestamp > ?
                GROUP BY t.address
                HAVING data_points >= 5 AND price_growth > 50
                ORDER BY price_growth DESC
                LIMIT 5
            ''', (int((datetime.now() - timedelta(hours=12)).timestamp()),))
            
            for row in cursor.fetchall():
                patterns.append({
                    "type": "STEADY_GROWTH",
                    "symbol": row[1],
                    "address": row[0],
                    "score": row[2],
                    "growth": row[4],
                    "description": f"{row[1]}: +{row[4]:.1f}% steady growth"
                })
        
        finally:
            conn.close()
        
        return patterns

# Exemple d'intégration dans le scanner principal
async def enhanced_monitoring_with_alerts():
    """Monitoring avec système d'alertes"""
    alerts = SmartAlerts()
    analyzer = TrendAnalyzer()
    
    while True:
        try:
            # Vérifier les alertes
            volume_alerts = await alerts.check_volume_spikes()
            gem_alerts = await alerts.check_new_gems()
            grad_alerts = await alerts.check_graduation_alerts()
            
            all_alerts = volume_alerts + gem_alerts + grad_alerts
            
            # Afficher les alertes
            for alert in all_alerts:
                logging.warning(alert["message"])
                logging.info(f"🔗 DexScreener: https://dexscreener.com/solana/{alert['address']}")
            
            # Analyse de sentiment
            sentiment = await analyzer.get_market_sentiment()
            patterns = await analyzer.get_trending_patterns()
            
            logging.info(f"📊 Market Sentiment: {sentiment['sentiment']} | Avg Score: {sentiment.get('avg_score', 0):.1f}")
            
            for pattern in patterns:
                logging.info(f"📈 Pattern: {pattern['description']}")
            
            # Attendre 5 minutes avant la prochaine vérification
            await asyncio.sleep(300)
            
        except Exception as e:
            logging.error(f"Error in alert monitoring: {e}")
            await asyncio.sleep(60)