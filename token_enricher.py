#!/usr/bin/env python3
"""
🔍 Token Enricher - Enrichit automatiquement les nouveaux tokens détectés
Récupère les métadonnées, prix, et données de marché pour les tokens en base
"""

import asyncio
import aiohttp
import sqlite3
import time
import json
import logging
import random
from datetime import datetime, timezone
from typing import List, Dict, Optional
from aiohttp import ClientSession, TCPConnector
from async_lru import alru_cache
from math import log

# Configuration du logger
logger = logging.getLogger('token_enricher')

class TokenEnricher:
    """Classe pour enrichir les tokens détectés avec leurs métadonnées"""
    
    TOKEN_LIST_URL = "https://token.jup.ag/all"
    QUOTE_API_URL = "https://quote-api.jup.ag/v6/quote"
    DEXSCREENER_API = "https://api.dexscreener.com/latest"
    SOLSCAN_API = "https://public-api.solscan.io"
    
    def __init__(self, database_path: str = "tokens.db"):
        self.database_path = database_path
        self.session: Optional[ClientSession] = None
        
        # Rate limiters pour chaque API
        self.rate_limiters = {
            "jupiter": self._create_rate_limiter(2, 10),  # 2 calls/sec, max 10
            "dexscreener": self._create_rate_limiter(1, 5),  # 1 call/sec, max 5
            "rugcheck": self._create_rate_limiter(1, 5),
            "solscan": self._create_rate_limiter(2, 10),
            "helius": self._create_rate_limiter(1, 5),
        }

    def _create_rate_limiter(self, calls_per_second: float, max_calls: int):
        """Créer un rate limiter simple"""
        return {
            "calls_per_second": calls_per_second,
            "max_calls": max_calls,
            "tokens": max_calls,
            "last_refill": time.time(),
            "lock": asyncio.Lock()
        }

    async def _acquire_rate_limit(self, api_type: str):
        """Acquérir un token de rate limiting"""
        limiter = self.rate_limiters[api_type]
        async with limiter["lock"]:
            now = time.time()
            elapsed = now - limiter["last_refill"]
            limiter["tokens"] = min(
                limiter["max_calls"], 
                limiter["tokens"] + elapsed * limiter["calls_per_second"]
            )
            limiter["last_refill"] = now

            if limiter["tokens"] < 1:
                wait_time = (1 - limiter["tokens"]) / limiter["calls_per_second"]
                logger.debug(f"Rate limit {api_type}, waiting {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
                limiter["tokens"] = min(
                    limiter["max_calls"], 
                    limiter["tokens"] + wait_time * limiter["calls_per_second"]
                )
                limiter["last_refill"] = time.time()

            limiter["tokens"] -= 1

    async def _fetch_json(self, url: str, api_type: str, timeout: int = 10, max_retries: int = 3) -> Optional[Dict]:
        """Fetch JSON avec rate limiting et retry logic"""
        await self._acquire_rate_limit(api_type)
        
        for attempt in range(max_retries):
            try:
                async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                    if resp.status == 429:
                        backoff = (2 ** attempt) + random.uniform(0, 0.1)
                        logger.warning(f"Rate limit hit for {url}, retrying in {backoff:.2f}s")
                        await asyncio.sleep(backoff)
                        continue
                    if resp.status == 200:
                        return await resp.json()
                    logger.debug(f"HTTP {resp.status} for {url}")
                    return None
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt == max_retries - 1:
                    logger.error(f"Failed to fetch {url} after {max_retries} attempts: {e}")
                    return None
                backoff = (2 ** attempt) + random.uniform(0, 0.1)
                logger.debug(f"Error fetching {url}: {e}, retrying in {backoff:.2f}s")
                await asyncio.sleep(backoff)
        return None

    async def get_token_metadata_helius(self, address: str) -> Dict:
        """Récupérer les métadonnées du token via Helius"""
        url = f"https://rpc.helius.xyz/?api-key=872ddf73-4cfd-4263-a418-521bbde27eb8"
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getAsset",
            "params": {"id": address}
        }
        
        try:
            async with self.session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result = data.get("result", {})
                    content = result.get("content", {})
                    
                    return {
                        "symbol": content.get("metadata", {}).get("symbol", "UNKNOWN"),
                        "name": content.get("metadata", {}).get("name", "Unknown Token"),
                        "logo_uri": content.get("files", [{}])[0].get("uri") if content.get("files") else None,
                        "decimals": result.get("token_info", {}).get("decimals", 9),
                        "has_metadata": True
                    }
        except Exception as e:
            logger.debug(f"Error getting metadata from Helius for {address}: {e}")
        
        return {"has_metadata": False}

    async def get_jupiter_metadata(self, address: str) -> Dict:
        """Vérifier si le token est sur Jupiter et récupérer ses métadonnées"""
        try:
            data = await self._fetch_json(self.TOKEN_LIST_URL, "jupiter")
            if data:
                for token in data:
                    if token.get("address") == address:
                        return {
                            "symbol": token.get("symbol", "UNKNOWN"),
                            "name": token.get("name", "Unknown Token"),
                            "decimals": token.get("decimals", 9),
                            "logo_uri": token.get("logoURI"),
                            "is_on_jupiter": True
                        }
        except Exception as e:
            logger.debug(f"Error checking Jupiter for {address}: {e}")
        
        return {"is_on_jupiter": False}

    async def get_dexscreener_data(self, address: str) -> Dict:
        """Récupérer les données de marché depuis DexScreener"""
        url = f"{self.DEXSCREENER_API}/dex/tokens/{address}"
        data = await self._fetch_json(url, "dexscreener")
        
        if data and data.get("pairs"):
            pair = data["pairs"][0]  # Prendre la première paire
            return {
                "price_usd": float(pair.get("priceUsd", 0)),
                "market_cap": float(pair.get("marketCap", 0)),
                "liquidity_usd": float(pair.get("liquidity", {}).get("usd", 0)),
                "volume_24h": float(pair.get("volume", {}).get("h24", 0)),
                "price_change_24h": float(pair.get("priceChange", {}).get("h24", 0)),
                "age_hours": (time.time() * 1000 - pair.get("pairCreatedAt", time.time() * 1000)) / 3600000,
                "has_dexscreener_data": True
            }
        
        return {"has_dexscreener_data": False}

    async def check_jupiter_price(self, address: str) -> Dict:
        """Vérifier le prix via Jupiter API"""
        url = f"{self.QUOTE_API_URL}?inputMint={address}&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=1000000&slippageBps=500"
        data = await self._fetch_json(url, "jupiter")
        
        if data and "outAmount" in data:
            try:
                price = int(data["outAmount"]) / 1e6
                return {"price_usdc": price, "is_tradeable_jupiter": True}
            except (ValueError, TypeError):
                pass
        
        return {"price_usdc": 0, "is_tradeable_jupiter": False}

    async def get_rugcheck_score(self, address: str) -> Dict:
        """Récupérer le score de sécurité depuis RugCheck - VERSION CORRIGÉE"""
        url = f"https://api.rugcheck.xyz/v1/tokens/{address}/report"
        data = await self._fetch_json(url, "rugcheck")
        
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
                "rug_score_raw": raw_score,
                "rug_score_normalized": normalized_score,
                "quality_score": final_score,  # Pour compatibilité
                "has_rugcheck_data": True
            }
        
        return {
            "rug_score": 50,  # Score neutre par défaut
            "quality_score": 50,
            "has_rugcheck_data": False
        }

    async def get_holders_count(self, address: str) -> int:
        """Récupérer le nombre de holders depuis Solscan"""
        url = f"{self.SOLSCAN_API}/token/holders?tokenAddress={address}&limit=1"
        data = await self._fetch_json(url, "solscan")
        
        return data.get("total", 0) if data else 0

    async def analyze_holder_distribution(self, address: str) -> str:
        """Analyser la distribution des holders"""
        url = f"{self.SOLSCAN_API}/token/holders?tokenAddress={address}&limit=100"
        data = await self._fetch_json(url, "solscan")
        
        if data and "total" in data:
            holders = data["total"]
            if holders > 0:
                top_holders = data.get("holders", [])[:10]
                if top_holders:
                    top_holders_sum = sum(float(holder.get("amount", 0)) for holder in top_holders)
                    total_supply = data.get("totalSupply", 1)
                    if total_supply > 0:
                        concentration = (top_holders_sum / total_supply) * 100
                        return f"Top 10: {concentration:.1f}% | Total: {holders}"
        
        return "Unknown"

    def calculate_invest_score(self, data: Dict) -> float:
        """Calculer le score d'investissement"""
        risk = 100 - data.get("rug_score", 50)
        volume_24h = data.get("volume_24h", 0)
        liquidity_usd = data.get("liquidity_usd", 0)
        holders = data.get("holders", 0)
        
        momentum = log(1 + volume_24h / 50_000) * 30 if volume_24h > 0 else 0
        liquidity = log(1 + liquidity_usd / 100_000) * 20 if liquidity_usd > 0 else 0
        holders_score = log(1 + holders / 1_000) * 20 if holders > 0 else 0
        
        # Bonus pour les tokens très récents
        age_hours = data.get("age_hours", 999)
        early_bonus = 0
        if age_hours < 1:
            early_bonus = 30
        elif age_hours < 6:
            early_bonus = 20
        elif age_hours < 24:
            early_bonus = 10
        
        score = (
            risk * 0.35 +
            momentum * 0.25 +
            liquidity * 0.15 +
            holders_score * 0.15 +
            early_bonus
        )
        
        return round(min(max(score, 0), 200), 2)

    async def enrich_token(self, address: str) -> Dict:
        """Enrichir un token avec toutes ses données"""
        logger.info(f"🔍 Enriching token: {address}")
        
        try:
            # Lancer toutes les requêtes en parallèle pour optimiser
            tasks = [
                self.get_token_metadata_helius(address),
                self.get_jupiter_metadata(address),
                self.get_dexscreener_data(address),
                self.check_jupiter_price(address),
                self.get_rugcheck_score(address),
                self.get_holders_count(address),
                self.analyze_holder_distribution(address)
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Combiner les résultats
            enriched_data = {"address": address}
            
            for result in results:
                if isinstance(result, dict):
                    enriched_data.update(result)
                elif isinstance(result, int):
                    enriched_data["holders"] = result
                elif isinstance(result, str):
                    enriched_data["holder_distribution"] = result
                elif isinstance(result, Exception):
                    logger.error(f"Error in enrichment task: {result}")
            
            # Utiliser les métadonnées Helius en priorité, puis Jupiter
            if not enriched_data.get("has_metadata", False) and enriched_data.get("is_on_jupiter", False):
                # Utiliser les données Jupiter si Helius n'a pas de métadonnées
                pass
            
            # Déterminer si le token est tradeable
            enriched_data["is_tradeable"] = (
                enriched_data.get("is_tradeable_jupiter", False) or 
                enriched_data.get("has_dexscreener_data", False)
            )
            
            # Calculer le score d'investissement
            enriched_data["invest_score"] = self.calculate_invest_score(enriched_data)
            
            # Nettoyer les données avant stockage
            final_data = {
                "address": address,
                "symbol": enriched_data.get("symbol", "UNKNOWN"),
                "name": enriched_data.get("name", "Unknown Token"),
                "decimals": enriched_data.get("decimals", 9),
                "logo_uri": enriched_data.get("logo_uri"),
                "price_usdc": enriched_data.get("price_usdc") or enriched_data.get("price_usd"),
                "market_cap": enriched_data.get("market_cap"),
                "liquidity_usd": enriched_data.get("liquidity_usd"),
                "volume_24h": enriched_data.get("volume_24h"),
                "price_change_24h": enriched_data.get("price_change_24h"),
                "age_hours": enriched_data.get("age_hours"),
                "quality_score": enriched_data.get("quality_score"),
                "rug_score": enriched_data.get("rug_score"),
                "holders": enriched_data.get("holders", 0),
                "holder_distribution": enriched_data.get("holder_distribution"),
                "is_tradeable": enriched_data.get("is_tradeable", False),
                "invest_score": enriched_data.get("invest_score", 0)
            }
            
            logger.info(f"✅ Enriched {final_data['symbol']} - Score: {final_data['invest_score']}")
            return final_data
            
        except Exception as e:
            logger.error(f"Error enriching token {address}: {e}")
            return {
                "address": address,
                "symbol": "ERROR",
                "name": "Error enriching",
                "is_tradeable": False,
                "invest_score": 0
            }

    async def update_token_in_db(self, token_data: Dict):
        """Mettre à jour le token dans la base de données"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE tokens SET 
                    symbol = ?, name = ?, decimals = ?, logo_uri = ?,
                    price_usdc = ?, market_cap = ?, liquidity_usd = ?, volume_24h = ?,
                    price_change_24h = ?, age_hours = ?, quality_score = ?, rug_score = ?,
                    holders = ?, holder_distribution = ?, is_tradeable = ?, invest_score = ?
                WHERE address = ?
            ''', (
                token_data.get("symbol"),
                token_data.get("name"),
                token_data.get("decimals"),
                token_data.get("logo_uri"),
                token_data.get("price_usdc"),
                token_data.get("market_cap"),
                token_data.get("liquidity_usd"),
                token_data.get("volume_24h"),
                token_data.get("price_change_24h"),
                token_data.get("age_hours"),
                token_data.get("quality_score"),
                token_data.get("rug_score"),
                token_data.get("holders"),
                token_data.get("holder_distribution"),
                token_data.get("is_tradeable"),
                token_data.get("invest_score"),
                token_data["address"]
            ))
            
            conn.commit()
            logger.debug(f"💾 Updated token {token_data['address']} in database")
            
        except sqlite3.Error as e:
            logger.error(f"Database error updating token {token_data['address']}: {e}")
        finally:
            conn.close()

    async def get_unenriched_tokens(self, limit: int = 10) -> List[str]:
        """Récupérer les tokens qui n'ont pas encore été enrichis"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT address FROM tokens 
                WHERE symbol IS NULL OR symbol = 'UNKNOWN' OR symbol = ''
                ORDER BY first_discovered_at DESC
                LIMIT ?
            ''', (limit,))
            
            return [row[0] for row in cursor.fetchall()]
            
        except sqlite3.Error as e:
            logger.error(f"Database error getting unenriched tokens: {e}")
            return []
        finally:
            conn.close()

    async def enrich_unenriched_tokens(self, limit: int = 5):
        """Enrichir les tokens non enrichis"""
        if not self.session:
            self.session = aiohttp.ClientSession(
                connector=TCPConnector(limit=50),
                timeout=aiohttp.ClientTimeout(total=30)
            )
        
        try:
            unenriched = await self.get_unenriched_tokens(limit)
            
            if not unenriched:
                logger.info("✅ No unenriched tokens found")
                return
            
            logger.info(f"🔄 Enriching {len(unenriched)} tokens...")
            
            for address in unenriched:
                try:
                    enriched_data = await self.enrich_token(address)
                    await self.update_token_in_db(enriched_data)
                    
                    # Petit délai entre chaque token pour éviter le rate limiting
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    logger.error(f"Error enriching token {address}: {e}")
                    continue
                    
        finally:
            if self.session:
                await self.session.close()
                self.session = None

async def main():
    """Fonction principale"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    enricher = TokenEnricher()
    
    try:
        # Enrichir les tokens non enrichis une fois
        await enricher.enrich_unenriched_tokens(limit=10)
        
        logger.info("🎯 Token enrichment completed!")
        
    except Exception as e:
        logger.error(f"Error in main: {e}")

if __name__ == "__main__":
    asyncio.run(main())