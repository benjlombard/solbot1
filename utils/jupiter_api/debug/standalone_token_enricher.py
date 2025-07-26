#!/usr/bin/env python3
"""
🔧 Standalone Token Enricher
Script pour enrichir manuellement les tokens détectés dans la base de données
Usage: python standalone_token_enricher.py [--limit 10] [--force-all]
"""

import asyncio
import aiohttp
import sqlite3
import logging
import argparse
from datetime import datetime
from token_enricher import TokenEnricher

# Configuration du logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class StandaloneEnricher:
    def __init__(self, database_path: str = "../tokens.db"):
        self.database_path = database_path
        self.enricher = TokenEnricher(database_path)
    
    async def get_tokens_to_enrich(self, limit: int = None, force_all: bool = False) -> list:
        """Récupérer les tokens à enrichir"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            if force_all:
                # Enrichir tous les tokens
                query = '''
                    SELECT address, symbol, name, first_discovered_at 
                    FROM tokens 
                    ORDER BY first_discovered_at DESC
                '''
                params = ()
            else:
                # Enrichir seulement les tokens non enrichis
                query = '''
                    SELECT address, symbol, name, first_discovered_at 
                    FROM tokens 
                    WHERE symbol IS NULL OR symbol = 'UNKNOWN' OR symbol = ''
                    ORDER BY first_discovered_at DESC
                '''
                params = ()
            
            if limit:
                query += ' LIMIT ?'
                params = params + (limit,)
            
            cursor.execute(query, params)
            return cursor.fetchall()
            
        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return []
        finally:
            conn.close()
    
    async def show_database_stats(self):
        """Afficher les statistiques de la base"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            # Stats générales
            cursor.execute("SELECT COUNT(*) FROM tokens")
            total_tokens = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tokens WHERE symbol IS NULL OR symbol = 'UNKNOWN' OR symbol = ''")
            unenriched = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tokens WHERE is_tradeable = 1")
            tradeable = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tokens WHERE invest_score >= 80")
            high_score = cursor.fetchone()[0]
            
            # Tokens récents (dernières 24h)
            cursor.execute("SELECT COUNT(*) FROM tokens WHERE first_discovered_at > datetime('now', '-24 hours')")
            recent = cursor.fetchone()[0]
            
            logger.info("📊 Database Statistics:")
            logger.info(f"   Total tokens: {total_tokens}")
            logger.info(f"   Unenriched: {unenriched}")
            logger.info(f"   Tradeable: {tradeable}")
            logger.info(f"   High score (≥80): {high_score}")
            logger.info(f"   Recent (24h): {recent}")
            
            # Top 5 par score
            cursor.execute('''
                SELECT address, symbol, invest_score, price_usdc, volume_24h 
                FROM tokens 
                WHERE invest_score IS NOT NULL 
                ORDER BY invest_score DESC 
                LIMIT 5
            ''')
            
            top_tokens = cursor.fetchall()
            if top_tokens:
                logger.info("\n🏆 Top 5 tokens by score:")
                for i, (addr, symbol, score, price, volume) in enumerate(top_tokens, 1):
                    logger.info(f"   {i}. {symbol or 'UNKNOWN'} | Score: {score:.2f} | Price: ${price or 0:.8f} | Vol: ${volume or 0:.0f}")
            
        except sqlite3.Error as e:
            logger.error(f"Database error getting stats: {e}")
        finally:
            conn.close()
    
    async def enrich_tokens(self, limit: int = None, force_all: bool = False):
        """Enrichir les tokens"""
        logger.info("🔍 Starting token enrichment process...")
        
        # Afficher les stats avant
        await self.show_database_stats()
        
        # Récupérer les tokens à enrichir
        tokens_to_enrich = await self.get_tokens_to_enrich(limit, force_all)
        
        if not tokens_to_enrich:
            logger.info("✅ No tokens to enrich found!")
            return
        
        logger.info(f"🔄 Found {len(tokens_to_enrich)} tokens to enrich")
        
        # Démarrer l'enrichissement
        enriched_count = 0
        failed_count = 0
        
        for i, (address, current_symbol, current_name, discovered_at) in enumerate(tokens_to_enrich, 1):
            try:
                logger.info(f"\n[{i}/{len(tokens_to_enrich)}] Enriching: {address}")
                logger.info(f"   Current: {current_symbol or 'UNKNOWN'} | {current_name or 'Unknown'}")
                logger.info(f"   Discovered: {discovered_at}")
                
                # Enrichir le token
                await self.enricher.enrich_unenriched_tokens(limit=1)  # Enrichir un token
                enriched_count += 1
                
                # Délai entre les enrichissements
                if i < len(tokens_to_enrich):
                    logger.info("   ⏳ Waiting 3 seconds before next token...")
                    await asyncio.sleep(3)
                
            except Exception as e:
                logger.error(f"   ❌ Error enriching {address}: {e}")
                failed_count += 1
                continue
        
        # Stats finales
        logger.info(f"\n🎯 Enrichment completed!")
        logger.info(f"   ✅ Enriched: {enriched_count}")
        logger.info(f"   ❌ Failed: {failed_count}")
        
        # Afficher les stats après
        logger.info("\n📊 Updated database statistics:")
        await self.show_database_stats()

async def main():
    parser = argparse.ArgumentParser(description="Standalone Token Enricher")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of tokens to enrich")
    parser.add_argument("--force-all", action="store_true", help="Force enrich all tokens (not just unenriched)")
    parser.add_argument("--stats-only", action="store_true", help="Show database stats only")
    parser.add_argument("--database", default="tokens.db", help="Database path")
    
    args = parser.parse_args()
    
    enricher = StandaloneEnricher(args.database)
    
    if args.stats_only:
        await enricher.show_database_stats()
    else:
        await enricher.enrich_tokens(args.limit, args.force_all)

if __name__ == "__main__":
    asyncio.run(main())