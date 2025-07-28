#!/usr/bin/env python3
"""
⚡ Batch Token Enricher - Traitement parallèle optimisé
Augmente le débit de 10x en traitant plusieurs tokens simultanément
"""

import asyncio
import aiohttp
import sqlite3
import time
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from aiohttp import ClientSession, TCPConnector
import random

logger = logging.getLogger('batch_enricher')

class BatchTokenEnricher:
    """Enrichisseur de tokens optimisé pour le débit"""
    
    def __init__(self, database_path: str = "tokens.db", batch_size: int = 10, max_concurrent: int = 20):
        self.database_path = database_path
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent
        self.session: Optional[ClientSession] = None
        self.semaphore = asyncio.Semaphore(max_concurrent)
        
        # Rate limiters globaux plus agressifs
        self.api_delays = {
            "jupiter": 0.2,      # 5 calls/sec
            "dexscreener": 0.5,  # 2 calls/sec
            "rugcheck": 0.8,     # 1.25 calls/sec
            "solscan": 0.3,      # 3.3 calls/sec
            "helius": 0.4        # 2.5 calls/sec
        }
        
        # Pools de connexions optimisés
        self.connector = TCPConnector(
            limit=100,           # Plus de connexions simultanées
            limit_per_host=30,   # Plus par host
            ttl_dns_cache=300,   # Cache DNS
            use_dns_cache=True,
            keepalive_timeout=30,
            enable_cleanup_closed=True
        )
    
    async def start(self):
        """Démarrer l'enrichisseur avec session optimisée"""
        self.session = ClientSession(
            connector=self.connector,
            timeout=aiohttp.ClientTimeout(
                total=15,      # Timeout plus court
                connect=5,     # Connexion rapide
                sock_read=10   # Lecture rapide
            ),
            headers={
                'User-Agent': 'SolanaBot/1.0',
                'Accept': 'application/json',
                'Accept-Encoding': 'gzip, deflate'
            }
        )
        logger.info("🚀 Batch enricher started with optimized session")
    
    async def stop(self):
        """Arrêter l'enrichisseur"""
        if self.session:
            await self.session.close()
        await self.connector.close()
    
    async def _rate_limited_fetch(self, url: str, api_type: str) -> Optional[Dict]:
        """Fetch avec rate limiting optimisé"""
        async with self.semaphore:  # Limiter la concurrence globale
            try:
                # Délai adaptatif basé sur l'API
                await asyncio.sleep(self.api_delays.get(api_type, 0.5))
                
                async with self.session.get(url) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 429:
                        # Rate limit hit - back off plus longtemps
                        await asyncio.sleep(2 + random.uniform(0, 1))
                        return None
                    else:
                        logger.debug(f"HTTP {resp.status} for {url}")
                        return None
                        
            except asyncio.TimeoutError:
                logger.debug(f"Timeout for {api_type}: {url}")
                return None
            except Exception as e:
                logger.debug(f"Error fetching {api_type}: {e}")
                return None
    
    async def _enrich_single_token_fast(self, address: str) -> Dict:
        """Enrichissement rapide d'un seul token"""
        start_time = time.time()
        
        # Lancer toutes les requêtes en parallèle - LE PLUS IMPORTANT
        tasks = [
            self._get_jupiter_metadata(address),
            self._get_dexscreener_data(address),
            self._get_jupiter_price(address),
            self._get_rugcheck_score(address),
            self._get_holders_helius(address),  # Version optimisée
        ]
        
        # Attendre toutes les réponses avec timeout global
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), 
                timeout=12.0  # Timeout global agressif
            )
        except asyncio.TimeoutError:
            logger.warning(f"Global timeout for token {address}")
            results = [{}] * len(tasks)
        
        # Combiner les résultats rapidement
        enriched = {"address": address}
        for result in results:
            if isinstance(result, dict):
                enriched.update(result)
            elif isinstance(result, Exception):
                logger.debug(f"Task failed for {address}: {result}")
        
        # Calculer les métriques dérivées
        enriched.update(self._calculate_derived_metrics(enriched))
        
        enrich_time = time.time() - start_time
        logger.debug(f"⚡ Enriched {address} in {enrich_time:.2f}s")
        
        return enriched
    
    async def _get_jupiter_metadata(self, address: str) -> Dict:
        """Métadonnées Jupiter optimisées"""
        # Utiliser une requête unique pour tous les tokens Jupiter
        if not hasattr(self, '_jupiter_tokens_cache'):
            url = "https://token.jup.ag/all"
            data = await self._rate_limited_fetch(url, "jupiter")
            if data:
                # Créer un index pour lookup rapide
                self._jupiter_tokens_cache = {
                    token['address']: token for token in data
                }
            else:
                self._jupiter_tokens_cache = {}
        
        token_info = self._jupiter_tokens_cache.get(address, {})
        if token_info:
            return {
                "symbol": token_info.get("symbol", "UNKNOWN"),
                "name": token_info.get("name", "Unknown"),
                "decimals": token_info.get("decimals", 9),
                "logo_uri": token_info.get("logoURI"),
                "is_on_jupiter": True
            }
        
        return {"symbol": "UNKNOWN", "is_on_jupiter": False}
    
    async def _get_dexscreener_data(self, address: str) -> Dict:
        """DexScreener optimisé"""
        url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
        data = await self._rate_limited_fetch(url, "dexscreener")
        
        if data and data.get("pairs"):
            pair = data["pairs"][0]
            return {
                "price_usdc": float(pair.get("priceUsd", 0)),
                "market_cap": float(pair.get("marketCap", 0)),
                "liquidity_usd": float(pair.get("liquidity", {}).get("usd", 0)),
                "volume_24h": float(pair.get("volume", {}).get("h24", 0)),
                "price_change_24h": float(pair.get("priceChange", {}).get("h24", 0)),
                "age_hours": (time.time() * 1000 - pair.get("pairCreatedAt", time.time() * 1000)) / 3600000,
            }
        return {}
    
    async def _get_jupiter_price(self, address: str) -> Dict:
        """Prix Jupiter optimisé"""
        url = f"https://quote-api.jup.ag/v6/quote?inputMint={address}&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=1000000&slippageBps=500"
        data = await self._rate_limited_fetch(url, "jupiter")
        
        if data and "outAmount" in data:
            try:
                price = int(data["outAmount"]) / 1e6
                return {"price_usdc": price, "is_tradeable": True}
            except:
                pass
        return {"is_tradeable": False}
    
    async def _get_rugcheck_score(self, address: str) -> Dict:
        """RugCheck optimisé - VERSION CORRIGÉE"""
        url = f"https://api.rugcheck.xyz/v1/tokens/{address}/report"
        data = await self._rate_limited_fetch(url, "rugcheck")
        
        if data:
            # CORRECTION: Utiliser score_normalised au lieu de score
            normalized_score = data.get("score_normalised", None)
            raw_score = data.get("score", 50)
            
            # Si score_normalised existe, l'utiliser, sinon fallback sur raw_score
            final_score = normalized_score if normalized_score is not None else raw_score
            
            # S'assurer que le score est dans la plage 0-100
            final_score = max(0, min(100, final_score))
            
            return {
                "rug_score": final_score,
                "has_rugcheck_data": True
            }
        
        return {
            "rug_score": 50,  # Score neutre par défaut
            "has_rugcheck_data": False
        }
    
    async def _get_holders_helius(self, address: str) -> Dict:
        """Holders via Helius - version simplifiée"""
        url = "https://rpc.helius.xyz/?api-key=872ddf73-4cfd-4263-a418-521bbde27eb8"
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenLargestAccounts",
            "params": [address]
        }
        
        try:
            async with self.session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "result" in data and "value" in data["result"]:
                        accounts = data["result"]["value"]
                        holders = len([acc for acc in accounts if acc.get("uiAmount", 0) > 0])
                        return {"holders": holders}
        except:
            pass
        
        return {"holders": 0}
    
    def _calculate_derived_metrics(self, data: Dict) -> Dict:
        """Calculer rapidement les métriques dérivées"""
        from math import log
        
        risk = 100 - data.get("rug_score", 50)
        volume_24h = data.get("volume_24h", 0)
        liquidity_usd = data.get("liquidity_usd", 0)
        holders = data.get("holders", 0)
        
        momentum = log(1 + volume_24h / 50_000) * 30 if volume_24h > 0 else 0
        liquidity_score = log(1 + liquidity_usd / 100_000) * 20 if liquidity_usd > 0 else 0
        holders_score = log(1 + holders / 1_000) * 20 if holders > 0 else 0
        
        age_hours = data.get("age_hours", 999)
        early_bonus = 30 if age_hours < 1 else (20 if age_hours < 6 else (10 if age_hours < 24 else 0))
        
        invest_score = (risk * 0.35 + momentum * 0.25 + liquidity_score * 0.15 + holders_score * 0.15 + early_bonus)
        invest_score = round(min(max(invest_score, 0), 200), 2)
        
        return {
            "invest_score": invest_score,
            "is_tradeable": data.get("is_tradeable", False) or data.get("price_usdc", 0) > 0
        }
    
    async def enrich_batch(self, addresses: List[str]) -> List[Dict]:
        """Enrichir un batch de tokens en parallèle - CŒUR DE L'OPTIMISATION"""
        if not addresses:
            return []
        
        logger.info(f"⚡ Starting batch enrichment of {len(addresses)} tokens")
        start_time = time.time()
        
        # Traitement parallèle de tous les tokens du batch
        tasks = [self._enrich_single_token_fast(addr) for addr in addresses]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filtrer les résultats valides
        enriched_tokens = []
        for result in results:
            if isinstance(result, dict) and result.get("address"):
                enriched_tokens.append(result)
            elif isinstance(result, Exception):
                logger.error(f"Batch enrichment error: {result}")
        
        batch_time = time.time() - start_time
        logger.info(f"✅ Batch completed: {len(enriched_tokens)}/{len(addresses)} tokens in {batch_time:.2f}s")
        logger.info(f"📊 Throughput: {len(enriched_tokens)/batch_time:.2f} tokens/sec")
        
        return enriched_tokens
    
    async def update_batch_in_db(self, enriched_tokens: List[Dict]):
        """Mise à jour batch en base de données"""
        if not enriched_tokens:
            return
        
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            local_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Requête préparée pour optimiser
            update_sql = '''
                UPDATE tokens SET 
                    symbol = ?, name = ?, decimals = ?, logo_uri = ?,
                    price_usdc = ?, market_cap = ?, liquidity_usd = ?, volume_24h = ?,
                    price_change_24h = ?, age_hours = ?, rug_score = ?,
                    holders = ?, is_tradeable = ?, invest_score = ?,
                    updated_at = ?
                WHERE address = ?
            '''
            
            # Préparer toutes les données
            batch_data = []
            for token in enriched_tokens:
                batch_data.append((
                    token.get("symbol", "UNKNOWN"),
                    token.get("name", "Unknown"),
                    token.get("decimals", 9),
                    token.get("logo_uri"),
                    token.get("price_usdc"),
                    token.get("market_cap"),
                    token.get("liquidity_usd"),
                    token.get("volume_24h"),
                    token.get("price_change_24h"),
                    token.get("age_hours"),
                    token.get("rug_score"),
                    token.get("holders"),
                    token.get("is_tradeable"),
                    token.get("invest_score"),
                    local_timestamp,
                    token["address"]
                ))
            
            # Exécution batch
            cursor.executemany(update_sql, batch_data)
            conn.commit()
            
            logger.info(f"💾 Updated {len(enriched_tokens)} tokens in database")
            
        except sqlite3.Error as e:
            logger.error(f"Database batch update error: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    async def get_unenriched_tokens_batch(self, limit: int = 50) -> List[str]:
        """Récupérer un batch de tokens non enrichis"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT address FROM tokens 
                WHERE (symbol IS NULL OR symbol = 'UNKNOWN' OR symbol = '') 
                AND first_discovered_at > datetime('now', '-24 hours', 'localtime')
                ORDER BY first_discovered_at DESC
                LIMIT ?
            ''', (limit,))
            
            return [row[0] for row in cursor.fetchall()]
            
        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return []
        finally:
            conn.close()
    
    async def run_continuous_enrichment(self):
        """Boucle d'enrichissement continu optimisé"""
        await self.start()
        
        try:
            while True:
                # Récupérer un gros batch
                unenriched = await self.get_unenriched_tokens_batch(self.batch_size * 3)
                
                if not unenriched:
                    logger.info("😴 No tokens to enrich, waiting...")
                    await asyncio.sleep(30)
                    continue
                
                # Traiter par petits batches pour équilibrer débit/mémoire
                for i in range(0, len(unenriched), self.batch_size):
                    batch = unenriched[i:i + self.batch_size]
                    
                    enriched = await self.enrich_batch(batch)
                    if enriched:
                        await self.update_batch_in_db(enriched)
                    
                    # Petit délai entre les batches
                    await asyncio.sleep(1)
                
                logger.info(f"🔄 Processed {len(unenriched)} tokens, checking for more...")
                await asyncio.sleep(5)  # Délai avant le prochain cycle
                
        except KeyboardInterrupt:
            logger.info("🛑 Stopping enrichment...")
        finally:
            await self.stop()

# Utilisation optimisée
async def main():
    logging.basicConfig(level=logging.INFO)
    
    enricher = BatchTokenEnricher(
        batch_size=15,      # Traiter 15 tokens en parallèle
        max_concurrent=25   # 25 requêtes simultanées max
    )
    
    await enricher.run_continuous_enrichment()

if __name__ == "__main__":
    asyncio.run(main())