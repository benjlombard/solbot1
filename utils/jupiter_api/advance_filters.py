#!/usr/bin/env python3
"""
🔍 Advanced Filters - Filtres avancés pour identifier les meilleurs tokens
"""

import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import re

class TokenFilters:
    """Système de filtres avancés pour tokens"""
    
    def __init__(self, database_path: str = "tokens.db"):
        self.database_path = database_path
    
    async def filter_by_whale_activity(self, min_whale_count: int = 3) -> List[Dict]:
        """Filtrer par activité des whales (gros holders)"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT address, symbol, invest_score, holders, holder_distribution
                FROM tokens 
                WHERE holder_distribution LIKE '%Top 10:%'
                AND holders > ?
                AND is_tradeable = 1
                ORDER BY invest_score DESC
                LIMIT 10
            ''', (min_whale_count * 10,))
            
            results = []
            for row in cursor.fetchall():
                # Parser la concentration des top holders
                dist = row[4] or ""
                concentration_match = re.search(r'Top 10: ([\d.]+)%', dist)
                if concentration_match:
                    concentration = float(concentration_match.group(1))
                    # Filtrer les tokens avec concentration équilibrée (pas trop centralisée)
                    if 20 <= concentration <= 70:  # Sweet spot
                        results.append({
                            "address": row[0],
                            "symbol": row[1],
                            "score": row[2],
                            "holders": row[3],
                            "concentration": concentration,
                            "whale_friendly": True
                        })
            
            return results
        
        finally:
            conn.close()
    
    async def filter_moonshot_candidates(self) -> List[Dict]:
        """Identifier les candidats moonshot (très récents, fort potentiel)"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT address, symbol, invest_score, age_hours, 
                       volume_24h, liquidity_usd, holders, rug_score
                FROM tokens 
                WHERE age_hours <= 12  -- Très récent
                AND invest_score >= 70  -- Score élevé
                AND rug_score >= 60    -- Sécurité minimale
                AND volume_24h > 10000 -- Activité minimale
                AND is_tradeable = 1
                ORDER BY invest_score DESC, age_hours ASC
                LIMIT 5
            ''')
            
            results = []
            for row in cursor.fetchall():
                # Calculer un score moonshot
                age_bonus = max(0, 12 - row[3]) * 5  # Bonus pour nouveauté
                volume_score = min(30, (row[4] / 10000) * 10)  # Score volume
                moonshot_score = row[2] + age_bonus + volume_score
                
                results.append({
                    "address": row[0],
                    "symbol": row[1],
                    "base_score": row[2],
                    "moonshot_score": round(moonshot_score, 2),
                    "age_hours": row[3],
                    "volume": row[4],
                    "liquidity": row[5],
                    "holders": row[6],
                    "safety": row[7]
                })
            
            return results
        
        finally:
            conn.close()
    
    async def filter_by_social_signals(self) -> List[Dict]:
        """Filtrer par signaux sociaux (simulation - à connecter avec Twitter API)"""
        # Simulation basée sur les patterns de noms de tokens
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        viral_patterns = [
            r'(?i).*cat.*',     # Cat coins tendance
            r'(?i).*dog.*',     # Dog coins
            r'(?i).*pepe.*',    # Pepe derivatives
            r'(?i).*moon.*',    # Moon tokens
            r'(?i).*ai.*',      # AI tokens
            r'(?i).*trump.*',   # Political tokens
        ]
        
        try:
            cursor.execute('''
                SELECT address, symbol, name, invest_score, volume_24h, holders
                FROM tokens 
                WHERE first_discovered_at > datetime('now', '-24 hours')
                AND is_tradeable = 1
                ORDER BY invest_score DESC
                LIMIT 50
            ''')
            
            results = []
            for row in cursor.fetchall():
                symbol = row[1] or ""
                name = row[2] or ""
                
                # Vérifier les patterns viraux
                social_score = 0
                matching_patterns = []
                
                for pattern in viral_patterns:
                    if re.match(pattern, symbol) or re.match(pattern, name):
                        social_score += 10
                        pattern_name = pattern.replace(r'(?i).*', '').replace('.*', '').upper()
                        matching_patterns.append(pattern_name)
                
                # Bonus pour holders élevés (indicateur social)
                if row[5] > 1000:
                    social_score += 20
                elif row[5] > 500:
                    social_score += 10
                
                if social_score > 0:
                    results.append({
                        "address": row[0],
                        "symbol": symbol,
                        "name": name,
                        "invest_score": row[3],
                        "social_score": social_score,
                        "patterns": matching_patterns,
                        "holders": row[5],
                        "volume": row[4]
                    })
            
            return sorted(results, key=lambda x: x["social_score"], reverse=True)[:10]
        
        finally:
            conn.close()
    
    async def filter_arbitrage_opportunities(self) -> List[Dict]:
        """Identifier les opportunités d'arbitrage potentielles"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            # Tokens avec écart entre prix Jupiter et DexScreener
            cursor.execute('''
                SELECT t1.address, t1.symbol, t1.price_usdc as jupiter_price,
                       t2.price_usdc as dex_price, t1.liquidity_usd,
                       ABS(t1.price_usdc - t2.price_usdc) / t1.price_usdc * 100 as price_diff
                FROM tokens t1
                JOIN tokens t2 ON t1.address = t2.address
                WHERE t1.price_usdc > 0 AND t2.price_usdc > 0
                AND ABS(t1.price_usdc - t2.price_usdc) / t1.price_usdc > 0.05  -- 5% difference
                AND t1.liquidity_usd > 50000  -- Liquidity suffisante
                ORDER BY price_diff DESC
                LIMIT 5
            ''')
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    "address": row[0],
                    "symbol": row[1],
                    "jupiter_price": row[2],
                    "dex_price": row[3],
                    "liquidity": row[4],
                    "price_difference": row[5],
                    "opportunity": "HIGH" if row[5] > 10 else "MEDIUM"
                })
            
            return results
        
        finally:
            conn.close()
    
    async def filter_by_dev_activity(self) -> List[Dict]:
        """Filtrer par activité supposée des développeurs (patterns)"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            # Indicateurs d'activité dev : metadata complète, logo, etc.
            cursor.execute('''
                SELECT address, symbol, name, logo_uri, invest_score,
                       bonding_curve_status, raydium_pool_address
                FROM tokens 
                WHERE symbol != 'UNKNOWN' 
                AND name IS NOT NULL 
                AND logo_uri IS NOT NULL
                AND first_discovered_at > datetime('now', '-48 hours')
                ORDER BY invest_score DESC
                LIMIT 20
            ''')
            
            results = []
            for row in cursor.fetchall():
                dev_score = 0
                
                # Scoring basé sur la complétude des métadonnées
                if row[1] and row[1] != 'UNKNOWN':
                    dev_score += 20
                if row[2] and len(row[2]) > 5:
                    dev_score += 15
                if row[3]:  # Logo URI
                    dev_score += 25
                if row[5] in ['completed', 'migrated']:
                    dev_score += 20  # Progression du projet
                if row[6]:  # Raydium pool
                    dev_score += 20
                
                results.append({
                    "address": row[0],
                    "symbol": row[1],
                    "name": row[2],
                    "invest_score": row[4],
                    "dev_score": dev_score,
                    "status": row[5],
                    "has_logo": bool(row[3]),
                    "has_raydium": bool(row[6])
                })
            
            return sorted(results, key=lambda x: x["dev_score"], reverse=True)[:10]
        
        finally:
            conn.close()

class CustomQueries:
    """Requêtes personnalisées prêtes à l'emploi"""
    
    def __init__(self, database_path: str = "tokens.db"):
        self.database_path = database_path
    
    async def get_diamond_hands_tokens(self) -> List[Dict]:
        """Tokens avec holders stables (diamond hands)"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            # Simulation - dans la vraie vie, analyser l'historique des holders
            cursor.execute('''
                SELECT address, symbol, holders, volume_24h, age_hours,
                       (holders * 1000 / NULLIF(volume_24h, 0)) as diamond_ratio
                FROM tokens 
                WHERE holders > 100
                AND volume_24h > 0
                AND age_hours > 24  -- Au moins 1 jour
                ORDER BY diamond_ratio DESC
                LIMIT 10
            ''')
            
            return [
                {
                    "address": row[0],
                    "symbol": row[1],
                    "holders": row[2],
                    "volume": row[3],
                    "age": row[4],
                    "diamond_ratio": row[5],
                    "stability": "HIGH" if row[5] > 0.5 else "MEDIUM"
                }
                for row in cursor.fetchall()
            ]
        
        finally:
            conn.close()
    
    async def get_breakout_candidates(self) -> List[Dict]:
        """Candidats pour breakout technique"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT t.address, t.symbol, t.price_usdc, t.volume_24h,
                       t.liquidity_usd, t.market_cap, t.invest_score
                FROM tokens t
                WHERE t.volume_24h BETWEEN 25000 AND 100000  -- Volume modéré
                AND t.liquidity_usd > 100000  -- Liquidité solide
                AND t.market_cap < 5000000   -- Small cap
                AND t.invest_score >= 65     -- Score correct
                AND t.price_change_24h BETWEEN -5 AND 15  -- Consolidation
                ORDER BY t.invest_score DESC
                LIMIT 10
            ''')
            
            return [
                {
                    "address": row[0],
                    "symbol": row[1],
                    "price": row[2],
                    "volume": row[3],
                    "liquidity": row[4],
                    "mcap": row[5],
                    "score": row[6],
                    "breakout_potential": "HIGH"
                }
                for row in cursor.fetchall()
            ]
        
        finally:
            conn.close()

# Exemple d'utilisation dans le scanner principal
async def run_advanced_filters():
    """Exécuter tous les filtres avancés"""
    filters = TokenFilters()
    queries = CustomQueries()
    
    print("🔍 Running Advanced Filters...")
    
    # Whale activity
    whales = await filters.filter_by_whale_activity()
    print(f"\n🐋 Whale-friendly tokens: {len(whales)}")
    for token in whales[:3]:
        print(f"  {token['symbol']}: {token['concentration']:.1f}% concentration")
    
    # Moonshots
    moonshots = await filters.filter_moonshot_candidates()
    print(f"\n🚀 Moonshot candidates: {len(moonshots)}")
    for token in moonshots[:3]:
        print(f"  {token['symbol']}: Score {token['moonshot_score']} ({token['age_hours']:.1f}h old)")
    
    # Social signals
    social = await filters.filter_by_social_signals()
    print(f"\n📱 Social trending: {len(social)}")
    for token in social[:3]:
        print(f"  {token['symbol']}: Social {token['social_score']} {token['patterns']}")
    
    # Diamond hands
    diamonds = await queries.get_diamond_hands_tokens()
    print(f"\n💎 Diamond hands: {len(diamonds)}")
    for token in diamonds[:3]:
        print(f"  {token['symbol']}: Ratio {token['diamond_ratio']:.2f}")
    
    # Breakouts
    breakouts = await queries.get_breakout_candidates()
    print(f"\n📈 Breakout candidates: {len(breakouts)}")
    for token in breakouts[:3]:
        print(f"  {token['symbol']}: ${token['price']:.6f} (Score: {token['score']})")