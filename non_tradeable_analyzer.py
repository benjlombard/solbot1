#!/usr/bin/env python3
"""
🔍 Non-Tradeable Tokens Analyzer
Analyser et vérifier les tokens marqués comme non-tradeable
"""

import sqlite3
import asyncio
import aiohttp
import argparse
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import json
import time

# Configuration du logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('non_tradeable_analyzer')

@dataclass
class TokenAnalysis:
    """Résultats d'analyse d'un token"""
    address: str
    symbol: str
    is_tradeable_db: bool
    
    # Tests de tradeabilité
    jupiter_tradeable: bool
    dexscreener_tradeable: bool
    rugcheck_accessible: bool
    
    # Données actuelles
    jupiter_price: Optional[float]
    dexscreener_price: Optional[float]
    dexscreener_volume: Optional[float]
    dexscreener_liquidity: Optional[float]
    
    # Métadonnées
    first_discovered: str
    last_updated: str
    bonding_curve_status: Optional[str]
    invest_score: Optional[float]
    
    # Conclusion
    should_be_tradeable: bool
    confidence: str  # 'high', 'medium', 'low'
    reason: str

class NonTradeableAnalyzer:
    """Analyseur pour les tokens non-tradeable"""
    
    def __init__(self, database_path: str = "tokens.db"):
        self.database_path = database_path
        self.session: aiohttp.ClientSession = None
        
        # Rate limiting
        self.last_jupiter_call = 0
        self.last_dexscreener_call = 0
        self.last_rugcheck_call = 0
        self.jupiter_delay = 0.5  # 2 req/sec
        self.dexscreener_delay = 1.0  # 1 req/sec
        self.rugcheck_delay = 2.0  # 0.5 req/sec
    
    async def start_session(self):
        """Démarrer la session HTTP"""
        connector = aiohttp.TCPConnector(limit=20, limit_per_host=10)
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=10)
        )
    
    async def close_session(self):
        """Fermer la session HTTP"""
        if self.session:
            await self.session.close()
    
    def get_non_tradeable_tokens(self, limit: int = None, age_hours: int = None) -> List[Dict]:
        """Récupérer les tokens non-tradeable de la DB"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            query = '''
                SELECT address, symbol, name, is_tradeable, first_discovered_at, 
                       updated_at, bonding_curve_status, invest_score, price_usdc,
                       dexscreener_price_usd, dexscreener_volume_24h, 
                       dexscreener_liquidity_quote, rug_score
                FROM tokens 
                WHERE is_tradeable = 0 OR is_tradeable IS NULL
            '''
            
            params = []
            
            if age_hours:
                query += ' AND first_discovered_at > datetime("now", "-{} hours", "localtime")'.format(age_hours)
            
            query += ' ORDER BY first_discovered_at DESC'
            
            if limit:
                query += f' LIMIT {limit}'
            
            cursor.execute(query, params)
            
            tokens = []
            for row in cursor.fetchall():
                tokens.append({
                    'address': row[0],
                    'symbol': row[1] or 'UNKNOWN',
                    'name': row[2] or 'Unknown',
                    'is_tradeable': bool(row[3]) if row[3] is not None else False,
                    'first_discovered_at': row[4],
                    'updated_at': row[5],
                    'bonding_curve_status': row[6],
                    'invest_score': row[7],
                    'price_usdc': row[8],
                    'dexscreener_price_usd': row[9],
                    'dexscreener_volume_24h': row[10],
                    'dexscreener_liquidity_quote': row[11],
                    'rug_score': row[12]
                })
            
            return tokens
            
        except sqlite3.Error as e:
            logger.error(f"Erreur DB: {e}")
            return []
        finally:
            conn.close()
    
    async def rate_limit_wait(self, api_type: str):
        """Attendre pour respecter le rate limiting"""
        now = time.time()
        
        if api_type == "jupiter":
            time_since_last = now - self.last_jupiter_call
            if time_since_last < self.jupiter_delay:
                await asyncio.sleep(self.jupiter_delay - time_since_last)
            self.last_jupiter_call = time.time()
            
        elif api_type == "dexscreener":
            time_since_last = now - self.last_dexscreener_call
            if time_since_last < self.dexscreener_delay:
                await asyncio.sleep(self.dexscreener_delay - time_since_last)
            self.last_dexscreener_call = time.time()
            
        elif api_type == "rugcheck":
            time_since_last = now - self.last_rugcheck_call
            if time_since_last < self.rugcheck_delay:
                await asyncio.sleep(self.rugcheck_delay - time_since_last)
            self.last_rugcheck_call = time.time()
    
    async def test_jupiter_tradeable(self, address: str) -> Tuple[bool, Optional[float]]:
        """Tester si le token est tradeable sur Jupiter"""
        await self.rate_limit_wait("jupiter")
        
        try:
            url = f"https://quote-api.jup.ag/v6/quote?inputMint={address}&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=1000000&slippageBps=500"
            
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and "outAmount" in data and data["outAmount"]:
                        try:
                            price = float(data["outAmount"]) / 1e6
                            return True, price
                        except (ValueError, TypeError):
                            return False, None
                elif resp.status == 400:
                    # Souvent retourné quand le token n'est pas tradeable
                    return False, None
                
        except asyncio.TimeoutError:
            logger.debug(f"Timeout Jupiter pour {address}")
        except Exception as e:
            logger.debug(f"Erreur Jupiter pour {address}: {e}")
        
        return False, None
    
    async def test_dexscreener_tradeable(self, address: str) -> Tuple[bool, Dict]:
        """Tester si le token a des données DexScreener"""
        await self.rate_limit_wait("dexscreener")
        
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
            
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and data.get("pairs") and len(data["pairs"]) > 0:
                        pair = data["pairs"][0]
                        try:
                            return True, {
                                'price': float(pair.get("priceUsd", 0) or 0),
                                'volume_24h': float(pair.get("volume", {}).get("h24", 0) or 0),
                                'liquidity': float(pair.get("liquidity", {}).get("usd", 0) or 0)
                            }
                        except (ValueError, TypeError):
                            return False, {}
                        
        except asyncio.TimeoutError:
            logger.debug(f"Timeout DexScreener pour {address}")
        except Exception as e:
            logger.debug(f"Erreur DexScreener pour {address}: {e}")
        
        return False, {}
    
    async def test_rugcheck_accessible(self, address: str) -> bool:
        """Tester si RugCheck a des données pour ce token"""
        await self.rate_limit_wait("rugcheck")
        
        try:
            url = f"https://api.rugcheck.xyz/v1/tokens/{address}/report"
            
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return bool(data and data.get("score") is not None)
                elif resp.status == 404:
                    return False
                    
        except Exception as e:
            logger.debug(f"Erreur RugCheck pour {address}: {e}")
        
        return False
    
    async def analyze_token(self, token_data: Dict) -> TokenAnalysis:
        """Analyser un token pour déterminer sa tradeabilité réelle"""
        address = token_data['address']
        symbol = token_data['symbol']
        
        logger.info(f"🔍 Analysing: {symbol} ({address[:8]}...)")
        
        # Tests en parallèle
        jupiter_task = self.test_jupiter_tradeable(address)
        dexscreener_task = self.test_dexscreener_tradeable(address)
        rugcheck_task = self.test_rugcheck_accessible(address)
        
        # Attendre tous les résultats
        (jupiter_tradeable, jupiter_price), (dexscreener_tradeable, dex_data), rugcheck_accessible = await asyncio.gather(
            jupiter_task, dexscreener_task, rugcheck_task, return_exceptions=True
        )
        
        # Gérer les exceptions
        if isinstance(jupiter_tradeable, Exception):
            jupiter_tradeable, jupiter_price = False, None
        if isinstance(dexscreener_tradeable, Exception):
            dexscreener_tradeable, dex_data = False, {}
        if isinstance(rugcheck_accessible, Exception):
            rugcheck_accessible = False
        
        # Déterminer si le token devrait être tradeable
        should_be_tradeable = False
        confidence = "low"
        reason = "Unknown"
        
        # Logique de décision
        tradeable_indicators = []
        
        if jupiter_tradeable:
            tradeable_indicators.append("Jupiter")
        if dexscreener_tradeable:
            tradeable_indicators.append("DexScreener")
        if rugcheck_accessible:
            tradeable_indicators.append("RugCheck")
        
        # Données supplémentaires de la DB (gestion des None)
        dex_price = token_data.get('dexscreener_price_usd') or 0
        price_usdc = token_data.get('price_usdc') or 0
        volume_24h = token_data.get('dexscreener_volume_24h') or 0
        
        has_dex_price = dex_price > 0
        has_price_usdc = price_usdc > 0
        has_volume = volume_24h > 0
        
        if has_dex_price:
            tradeable_indicators.append("DB-DexPrice")
        if has_price_usdc:
            tradeable_indicators.append("DB-Price")
        if has_volume:
            tradeable_indicators.append("DB-Volume")
        
        # Décision finale
        if len(tradeable_indicators) >= 2:
            should_be_tradeable = True
            confidence = "high" if len(tradeable_indicators) >= 3 else "medium"
            reason = f"Multiple indicators: {', '.join(tradeable_indicators)}"
            
        elif len(tradeable_indicators) == 1:
            should_be_tradeable = True
            confidence = "medium"
            reason = f"Single indicator: {tradeable_indicators[0]}"
            
        elif token_data.get('bonding_curve_status') in ['completed', 'migrated']:
            should_be_tradeable = True
            confidence = "medium"
            reason = f"Bonding curve {token_data['bonding_curve_status']}"
            
        else:
            should_be_tradeable = False
            reason = "No tradeable indicators found"
        
        return TokenAnalysis(
            address=address,
            symbol=symbol,
            is_tradeable_db=token_data['is_tradeable'],
            
            jupiter_tradeable=jupiter_tradeable,
            dexscreener_tradeable=dexscreener_tradeable,
            rugcheck_accessible=rugcheck_accessible,
            
            jupiter_price=jupiter_price,
            dexscreener_price=dex_data.get('price'),
            dexscreener_volume=dex_data.get('volume_24h'),
            dexscreener_liquidity=dex_data.get('liquidity'),
            
            first_discovered=token_data['first_discovered_at'],
            last_updated=token_data['updated_at'],
            bonding_curve_status=token_data['bonding_curve_status'],
            invest_score=token_data['invest_score'],
            
            should_be_tradeable=should_be_tradeable,
            confidence=confidence,
            reason=reason
        )
    
    async def analyze_batch(self, tokens: List[Dict], batch_size: int = 5) -> List[TokenAnalysis]:
        """Analyser un batch de tokens"""
        results = []
        
        for i in range(0, len(tokens), batch_size):
            batch = tokens[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(tokens) + batch_size - 1) // batch_size
            
            logger.info(f"📦 Processing batch {batch_num}/{total_batches} ({len(batch)} tokens)")
            
            # Analyser le batch en parallèle
            tasks = [self.analyze_token(token) for token in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Filtrer les exceptions
            for result in batch_results:
                if isinstance(result, TokenAnalysis):
                    results.append(result)
                else:
                    logger.error(f"Erreur dans le batch: {result}")
            
            # Délai entre batches pour éviter le rate limiting
            if i + batch_size < len(tokens):
                await asyncio.sleep(2)
        
        return results
    
    def update_tradeable_status(self, analyses: List[TokenAnalysis], dry_run: bool = True) -> int:
        """Mettre à jour le statut tradeable dans la DB"""
        if dry_run:
            logger.info("🧪 DRY RUN - Aucune mise à jour ne sera effectuée")
        
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        updated_count = 0
        
        try:
            for analysis in analyses:
                if analysis.should_be_tradeable and analysis.confidence in ['high', 'medium']:
                    if not dry_run:
                        cursor.execute('''
                            UPDATE tokens 
                            SET is_tradeable = 1,
                                updated_at = ?
                            WHERE address = ?
                        ''', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), analysis.address))
                        
                        if cursor.rowcount > 0:
                            updated_count += 1
                            logger.info(f"✅ Updated {analysis.symbol}: non-tradeable -> tradeable")
                    else:
                        logger.info(f"🔄 Would update {analysis.symbol}: non-tradeable -> tradeable ({analysis.confidence} confidence)")
                        updated_count += 1
            
            if not dry_run:
                conn.commit()
                
        except sqlite3.Error as e:
            logger.error(f"Erreur mise à jour DB: {e}")
        finally:
            conn.close()
        
        return updated_count
    
    def display_analysis_report(self, analyses: List[TokenAnalysis]):
        """Afficher le rapport d'analyse"""
        
        # Statistiques
        total = len(analyses)
        should_be_tradeable = len([a for a in analyses if a.should_be_tradeable])
        high_confidence = len([a for a in analyses if a.confidence == 'high'])
        medium_confidence = len([a for a in analyses if a.confidence == 'medium'])
        
        print("=" * 120)
        print("🔍 NON-TRADEABLE TOKENS ANALYSIS REPORT")
        print("=" * 120)
        print(f"📊 Total analyzed: {total}")
        print(f"✅ Should be tradeable: {should_be_tradeable} ({should_be_tradeable/total*100:.1f}%)")
        print(f"🎯 High confidence: {high_confidence}")
        print(f"⚠️ Medium confidence: {medium_confidence}")
        print()
        
        # Tokens qui devraient être tradeable
        tradeable_candidates = [a for a in analyses if a.should_be_tradeable]
        
        if tradeable_candidates:
            print("🚀 TOKENS THAT SHOULD BE TRADEABLE")
            print("=" * 120)
            print(f"{'Symbol':<12} {'Jupiter':<8} {'DexScreen':<10} {'RugCheck':<9} {'Confidence':<11} {'Reason':<30} {'Address':<10}")
            print("-" * 120)
            
            for analysis in sorted(tradeable_candidates, key=lambda x: (x.confidence == 'high', x.symbol)):
                jupiter_icon = "✅" if analysis.jupiter_tradeable else "❌"
                dex_icon = "✅" if analysis.dexscreener_tradeable else "❌"
                rug_icon = "✅" if analysis.rugcheck_accessible else "❌"
                
                confidence_icon = "🎯" if analysis.confidence == 'high' else "⚠️" if analysis.confidence == 'medium' else "❓"
                
                print(f"{analysis.symbol:<12} {jupiter_icon:<8} {dex_icon:<10} {rug_icon:<9} {confidence_icon} {analysis.confidence:<10} {analysis.reason[:28]:<30} {analysis.address[:8]}...")
        
        # Tokens vraiment non-tradeable
        non_tradeable = [a for a in analyses if not a.should_be_tradeable]
        
        if non_tradeable:
            print(f"\n❌ CONFIRMED NON-TRADEABLE TOKENS ({len(non_tradeable)})")
            print("=" * 120)
            
            for analysis in non_tradeable[:10]:  # Limiter l'affichage
                print(f"   {analysis.symbol:<12} | {analysis.reason} | {analysis.address[:8]}...")
        
        print("\n" + "=" * 120)

async def main():
    """Fonction principale"""
    parser = argparse.ArgumentParser(description="🔍 Non-Tradeable Tokens Analyzer")
    
    parser.add_argument("--database", default="tokens.db", help="Path to database")
    parser.add_argument("--limit", type=int, help="Limit number of tokens to analyze")
    parser.add_argument("--age-hours", type=int, help="Only analyze tokens discovered in last N hours")
    parser.add_argument("--batch-size", type=int, default=5, help="Batch size for analysis")
    parser.add_argument("--update", action="store_true", help="Update tradeable status in DB")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be updated without changing DB")
    parser.add_argument("--export-json", type=str, help="Export analysis to JSON file")
    parser.add_argument("--quick", action="store_true", help="Quick analysis (skip some checks)")
    
    args = parser.parse_args()
    
    analyzer = NonTradeableAnalyzer(args.database)
    
    try:
        await analyzer.start_session()
        
        logger.info("🔍 Starting non-tradeable tokens analysis...")
        
        # Récupérer les tokens non-tradeable
        tokens = analyzer.get_non_tradeable_tokens(args.limit, args.age_hours)
        
        if not tokens:
            logger.info("✅ No non-tradeable tokens found!")
            return
        
        logger.info(f"📋 Found {len(tokens)} non-tradeable tokens to analyze")
        
        # Analyser les tokens
        analyses = await analyzer.analyze_batch(tokens, args.batch_size)
        
        # Afficher le rapport
        analyzer.display_analysis_report(analyses)
        
        # Mettre à jour la DB si demandé
        if args.update or args.dry_run:
            updated_count = analyzer.update_tradeable_status(analyses, dry_run=args.dry_run)
            
            if args.dry_run:
                logger.info(f"🧪 DRY RUN: Would update {updated_count} tokens")
            else:
                logger.info(f"✅ Updated {updated_count} tokens in database")
        
        # Export JSON si demandé
        if args.export_json:
            export_data = [
                {
                    'address': a.address,
                    'symbol': a.symbol,
                    'should_be_tradeable': a.should_be_tradeable,
                    'confidence': a.confidence,
                    'reason': a.reason,
                    'jupiter_tradeable': a.jupiter_tradeable,
                    'dexscreener_tradeable': a.dexscreener_tradeable,
                    'rugcheck_accessible': a.rugcheck_accessible
                }
                for a in analyses
            ]
            
            with open(args.export_json, 'w') as f:
                json.dump(export_data, f, indent=2)
            
            logger.info(f"📁 Analysis exported to: {args.export_json}")
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
    finally:
        await analyzer.close_session()

if __name__ == "__main__":
    asyncio.run(main())