#!/usr/bin/env python3
"""
🎯 Enhanced Solana Monitor with Automatic Token Enrichment
Monitors Pump.fun and Raydium for new tokens and enriches them automatically
"""

import asyncio
import json
import logging
import sqlite3
import websockets
from solders.pubkey import Pubkey
from solders.signature import Signature
from solana.rpc.async_api import AsyncClient
from datetime import datetime, timezone, timedelta
from decouple import config
from websockets.exceptions import ConnectionClosedError, InvalidStatusCode
import random
import time
from httpx import HTTPStatusError
import base64
import aiohttp
from aiohttp import ClientSession, TCPConnector
from math import log
from typing import Dict, List, Optional

# Fonctions de fallback pour le monitoring
def set_enrichment_queue_size(size: int): pass
def set_active_enrichment_tasks(count: int): pass  
def record_token_update(address: str, update_time: float, success: bool = True): pass

# Configuration du logger
logger = logging.getLogger('solana_monitoring')

# Constants
PUMP_FUN_PROGRAM = Pubkey.from_string("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
SPL_TOKEN_PROGRAM = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
RAYDIUM_AMM_PROGRAM = Pubkey.from_string("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")
HELIUS_WS_URL = f"wss://rpc.helius.xyz/?api-key={config('HELIUS_API_KEY', default='872ddf73-4cfd-4263-a418-521bbde27eb8')}"
SOLANA_RPC_URL = f"https://rpc.helius.xyz/?api-key={config('HELIUS_API_KEY', default='872ddf73-4cfd-4263-a418-521bbde27eb8')}"
DATABASE_PATH = "tokens.db"

def get_local_timestamp():
    """Obtenir un timestamp dans la timezone locale"""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

class OptimizedTokenEnricher:
    """Version optimisée de l'enrichisseur avec traitement par batch"""
    
    def __init__(self):
        self.session: aiohttp.ClientSession = None
        self.enrichment_queue = asyncio.Queue(maxsize=100)  # Queue plus grande
        self.is_running = False
        self.batch_processor = None
        self.batch_size = 10
        self.processing_batch = []
        self.batch_timeout = 5.0  # Traiter le batch même s'il n'est pas plein après 5s
        
    async def start(self):
        """Démarrer l'enrichissement optimisé"""
        if self.is_running:
            return
            
        self.session = aiohttp.ClientSession(
            connector=TCPConnector(
                limit=60,
                limit_per_host=20,
                ttl_dns_cache=300,
                use_dns_cache=True
            ),
            timeout=aiohttp.ClientTimeout(total=12)
        )
        self.is_running = True
        
        # Démarrer le processeur de batch
        asyncio.create_task(self._batch_processor_worker())
        logger.info("🚀 Optimized token enricher started")
    
    async def queue_for_enrichment(self, address: str):
        """Ajouter un token à la queue d'enrichissement"""
        if self.is_running:
            try:
                await asyncio.wait_for(
                    self.enrichment_queue.put(address), 
                    timeout=1.0
                )
                logger.debug(f"🔄 Queued: {address} (queue: {self.enrichment_queue.qsize()})")
            except asyncio.TimeoutError:
                logger.warning(f"⚠️ Queue full, dropping token: {address}")
    
    async def _batch_processor_worker(self):
        """Worker qui traite les tokens par batch"""
        while self.is_running:
            try:
                batch = []
                batch_start_time = time.time()
                
                # Collecter un batch ou attendre le timeout
                while len(batch) < self.batch_size and (time.time() - batch_start_time) < self.batch_timeout:
                    try:
                        address = await asyncio.wait_for(
                            self.enrichment_queue.get(), 
                            timeout=max(0.1, self.batch_timeout - (time.time() - batch_start_time))
                        )
                        batch.append(address)
                    except asyncio.TimeoutError:
                        break
                
                if batch:
                    set_enrichment_queue_size(self.enrichment_queue.qsize())
                    set_active_enrichment_tasks(len(batch))
                    
                    logger.info(f"⚡ Processing batch of {len(batch)} tokens")
                    
                    # Traiter le batch en parallèle
                    start_time = time.time()
                    enriched_count = 0
                    
                    tasks = [self._enrich_token_fast(addr) for addr in batch]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # Mettre à jour en base par batch
                    valid_results = []
                    for result in results:
                        if isinstance(result, dict) and result.get("address"):
                            valid_results.append(result)
                            enriched_count += 1
                        elif isinstance(result, Exception):
                            logger.debug(f"Enrichment error: {result}")
                    
                    if valid_results:
                        await self._update_batch_in_db(valid_results)
                    
                    # Métriques de performance
                    batch_time = time.time() - start_time
                    for addr in batch:
                        record_token_update(addr, batch_time / len(batch), True)
                    
                    logger.info(f"✅ Batch completed: {enriched_count}/{len(batch)} in {batch_time:.2f}s")
                    logger.info(f"📊 Throughput: {enriched_count/batch_time:.2f} tokens/sec")
                
                set_active_enrichment_tasks(0)
                await asyncio.sleep(0.5)  # Petit délai entre les batches
                
            except Exception as e:
                logger.error(f"Error in batch processor: {e}")
                await asyncio.sleep(5)
    
    async def debug_bonding_curve_progress(address: str):
        """Debug pour comparer les différentes sources de progression"""
        import aiohttp
        
        results = {}
        
        # 1. Test API Pump.fun
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://frontend-api.pump.fun/coins/{address}"
                async with session.get(url, timeout=8) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results['pump_fun'] = {
                            'market_cap': data.get("market_cap", 0),
                            'complete': data.get("complete", False),
                            'virtual_sol_reserves': data.get("virtual_sol_reserves"),
                            'virtual_token_reserves': data.get("virtual_token_reserves"),
                            'real_sol_reserves': data.get("real_sol_reserves"),
                            'real_token_reserves': data.get("real_token_reserves"),
                            'total_supply': data.get("total_supply"),
                            'progress': data.get("progress")  # Peut-être que cette valeur existe
                        }
                    else:
                        results['pump_fun'] = {'error': f'HTTP {resp.status}'}
        except Exception as e:
            results['pump_fun'] = {'error': str(e)}
        
        # 2. Test DexScreener
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
                async with session.get(url, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        pairs = data.get("pairs", [])
                        if pairs:
                            best_pair = pairs[0]
                            results['dexscreener'] = {
                                'market_cap': best_pair.get("marketCap"),
                                'liquidity': best_pair.get("liquidity", {}).get("usd"),
                                'dex_id': best_pair.get("dexId"),
                                'pair_address': best_pair.get("pairAddress")
                            }
                    else:
                        results['dexscreener'] = {'error': f'HTTP {resp.status}'}
        except Exception as e:
            results['dexscreener'] = {'error': str(e)}
        
        # 3. Calcul actuel
        market_cap = results.get('pump_fun', {}).get('market_cap', 0)
        if market_cap:
            current_calc = min((market_cap / 69000) * 100, 99.9)
            results['my_calculation'] = {
                'market_cap_used': market_cap,
                'target_used': 69000,
                'percentage_calculated': round(current_calc, 1)
            }
        
        return results

    async def _enrich_token_fast(self, address: str) -> Dict:
        """Version rapide de l'enrichissement"""
        try:
            # Lancer toutes les requêtes en parallèle
            tasks = [
                self._get_metadata_fast(address),
                self._get_market_data_fast(address),
                self._get_holders_fast(address),
                get_bonding_curve_progress(address)
            ]
            
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=10.0
            )
            
            # Combiner les résultats
            enriched = {"address": address}
            for result in results:
                if isinstance(result, dict):
                    enriched.update(result)
            
            # Calculer le score rapidement
            enriched["invest_score"] = self._calculate_score_fast(enriched)
            enriched["is_tradeable"] = bool(enriched.get("price_usdc", 0) > 0)
            
            # Log du progress pour debug
            progress = enriched.get("progress_percentage", 0)
            if progress > 0:
                logger.debug(f"💎 {enriched.get('symbol', 'UNKNOWN')} progress: {progress}%")

            return enriched
            
        except Exception as e:
            logger.debug(f"Fast enrichment error for {address}: {e}")
            return {
                "address": address,
                "symbol": "ERROR",
                "invest_score": 0,
                "is_tradeable": False,
                "progress_percentage": 0.0
            }
    
    async def _get_metadata_fast(self, address: str) -> Dict:
        """Métadonnées rapides - essayer Helius puis Jupiter"""
        # Helius d'abord (plus rapide pour les métadonnées)
        try:
            helius_url = "https://rpc.helius.xyz/?api-key=872ddf73-4cfd-4263-a418-521bbde27eb8"
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getAsset", "params": {"id": address}}
            
            async with self.session.post(helius_url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result = data.get("result", {})
                    content = result.get("content", {})
                    metadata = content.get("metadata", {})
                    
                    if metadata and metadata.get("symbol"):
                        return {
                            "symbol": metadata.get("symbol", "UNKNOWN"),
                            "name": metadata.get("name", "Unknown Token"),
                            "decimals": result.get("token_info", {}).get("decimals", 9)
                        }
        except:
            pass
        
        return {"symbol": "UNKNOWN", "name": "Unknown Token", "decimals": 9}
    
    async def _get_market_data_fast(self, address: str) -> Dict:
        """Données de marché rapides - DexScreener et Jupiter en parallèle"""
        try:
            dex_task = self._fetch_dexscreener(address)
            price_task = self._fetch_jupiter_price(address)
            rug_task = self._fetch_rugcheck(address)
            
            dex_data, price_data, rug_data = await asyncio.gather(
                dex_task, price_task, rug_task, return_exceptions=True
            )
            
            market_data = {}
            
            if isinstance(dex_data, dict):
                market_data.update(dex_data)
            if isinstance(price_data, dict):
                market_data.update(price_data)
            if isinstance(rug_data, dict):
                market_data.update(rug_data)
            
            return market_data
            
        except Exception as e:
            logger.debug(f"Market data error for {address}: {e}")
            return {}
    
    async def _fetch_dexscreener(self, address: str) -> Dict:
        """DexScreener rapide"""
        url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and data.get("pairs"):
                        pair = data["pairs"][0]
                        return {
                            "price_usdc": float(pair.get("priceUsd", 0)),
                            "liquidity_usd": float(pair.get("liquidity", {}).get("usd", 0)),
                            "volume_24h": float(pair.get("volume", {}).get("h24", 0))
                        }
        except:
            pass
        return {}
    
    async def _fetch_jupiter_price(self, address: str) -> Dict:
        """Prix Jupiter rapide"""
        url = f"https://quote-api.jup.ag/v6/quote?inputMint={address}&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=1000000&slippageBps=500"
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and "outAmount" in data:
                        price = int(data["outAmount"]) / 1e6
                        return {"price_usdc": price}
        except:
            pass
        return {}
    
    async def _fetch_rugcheck(self, address: str) -> Dict:
        """RugCheck rapide"""
        url = f"https://api.rugcheck.xyz/v1/tokens/{address}/report"
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data:
                        return {"rug_score": data.get("score", 50)}
        except:
            pass
        return {"rug_score": 50}
    
    async def _get_holders_fast(self, address: str) -> Dict:
        """Holders rapide via Helius"""
        try:
            url = "https://rpc.helius.xyz/?api-key=872ddf73-4cfd-4263-a418-521bbde27eb8"
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getTokenLargestAccounts", "params": [address]}
            
            async with self.session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "result" in data and "value" in data["result"]:
                        accounts = data["result"]["value"]
                        holders = len([acc for acc in accounts if acc.get("uiAmount", 0) > 0])
                        return {"holders": holders}
        except:
            pass
        return {"holders": 0}
    
    def _calculate_score_fast(self, data: Dict) -> float:
        """Calcul rapide du score"""
        from math import log
        
        risk = 100 - data.get("rug_score", 50)
        volume = data.get("volume_24h", 0)
        liquidity = data.get("liquidity_usd", 0)
        holders = data.get("holders", 0)
        
        momentum = log(1 + volume / 50_000) * 30 if volume > 0 else 0
        liq_score = log(1 + liquidity / 100_000) * 20 if liquidity > 0 else 0
        hold_score = log(1 + holders / 1_000) * 20 if holders > 0 else 0
        
        score = risk * 0.35 + momentum * 0.25 + liq_score * 0.15 + hold_score * 0.15
        return round(min(max(score, 0), 200), 2)
    
    async def _update_batch_in_db(self, enriched_tokens: List[Dict]):
        """Mise à jour batch optimisée en base"""
        if not enriched_tokens:
            return
        
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        try:
            local_timestamp = get_local_timestamp()
            
            # Requête batch optimisée
            update_sql = '''
                UPDATE tokens SET 
                    symbol = ?, name = ?, decimals = ?, price_usdc = ?, 
                    liquidity_usd = ?, volume_24h = ?, rug_score = ?,
                    holders = ?, is_tradeable = ?, invest_score = ?,
                    bonding_curve_progress = ?,
                    updated_at = ?
                WHERE address = ?
            '''
            
            batch_data = []
            for token in enriched_tokens:

                progress = token.get("progress_percentage", 0.0)
                
                batch_data.append((
                    token.get("symbol", "UNKNOWN"),
                    token.get("name", "Unknown"),
                    token.get("decimals", 9),
                    token.get("price_usdc"),
                    token.get("liquidity_usd"),
                    token.get("volume_24h"),
                    token.get("rug_score"),
                    token.get("holders"),
                    token.get("is_tradeable"),
                    token.get("invest_score"),
                    progress,
                    local_timestamp,
                    token["address"]
                ))
            
            cursor.executemany(update_sql, batch_data)
            conn.commit()

            # Log pour debug
            progress_tokens = [t for t in enriched_tokens if t.get("progress_percentage", 0) > 0]
            if progress_tokens:
                logger.info(f"💾 Batch updated {len(enriched_tokens)} tokens ({len(progress_tokens)} with progress)")
            else:
                logger.info(f"💾 Batch updated {len(enriched_tokens)} tokens in DB")
            
           
            
        except sqlite3.Error as e:
            logger.error(f"Batch DB update error: {e}")
        finally:
            conn.close()

async def determine_bonding_curve_status(address: str, client: AsyncClient) -> str:
    """
    Détermine le statut réel de la bonding curve en analysant les données on-chain
    """
    try:
        # 1. Vérifier d'abord DexScreener pour voir si le token est tradé
        dex_status = await check_dexscreener_status(address)
        
        # 2. Vérifier les données Pump.fun
        pump_status = await check_pump_fun_status(address)
        
        # 3. Vérifier les pools Raydium
        raydium_status = await check_raydium_pools(address)
        
        # Priorité 1: Token migré vers Raydium
        if raydium_status.get("has_pool", False):
            return "migrated"
        
        # Priorité 2: Token présent sur DexScreener
        if dex_status.get("has_pairs", False):
            dex_id = dex_status.get("dex_id", "").lower()
            liquidity = dex_status.get("liquidity_usd", 0)
            
            # Si c'est sur Raydium via DexScreener = migrated
            if "raydium" in dex_id:
                return "migrated"
            
            # Si c'est sur Pump.fun via DexScreener
            if "pump" in dex_id or liquidity > 0:
                # Vérifier le statut Pump.fun
                if pump_status.get("bonding_curve_complete", False):
                    return "completed"
                else:
                    return "active"  # ← Correction principale !
            
            # Autres DEX = probablement completed ou migrated
            return "completed"
        
        # Priorité 3: Seulement visible sur Pump.fun
        if pump_status.get("exists", False):
            if pump_status.get("is_active", False):
                return "active"
            elif pump_status.get("bonding_curve_complete", False):
                return "completed"
            else:
                return "created"
        
        return "unknown"
        
    except Exception as e:
        logger.error(f"Error determining bonding curve status for {address}: {e}")
        return "unknown"


async def check_dexscreener_status(address: str) -> dict:
    """Vérifier le statut sur DexScreener"""
    import aiohttp
    
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
            async with session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    
                    if pairs:
                        # Analyser les paires pour déterminer le statut
                        for pair in pairs:
                            dex_id = pair.get("dexId", "").lower()
                            liquidity = pair.get("liquidity", {}).get("usd", 0)
                            
                            return {
                                "has_pairs": True,
                                "dex_id": dex_id,
                                "liquidity_usd": liquidity,
                                "is_raydium": "raydium" in dex_id,
                                "is_pump_fun": "pump" in dex_id or "pump.fun" in dex_id.replace(".", "")
                            }
                    
                    return {"has_pairs": False}
    except Exception as e:
        logger.debug(f"Error checking DexScreener for {address}: {e}")
    
    return {"has_pairs": False}

async def check_pump_fun_status(address: str) -> dict:
    """Vérifier le statut sur Pump.fun via leur API"""
    import aiohttp
    
    try:
        async with aiohttp.ClientSession() as session:
            # API Pump.fun (exemple - ajuster selon leur vraie API)
            url = f"https://frontend-api.pump.fun/coins/{address}"
            async with session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Analyser les données Pump.fun
                    market_cap = data.get("market_cap", 0)
                    complete = data.get("complete", False)
                    raydium_pool = data.get("raydium_pool")
                    
                    return {
                        "exists": True,
                        "is_active": market_cap > 0 and not complete,
                        "bonding_curve_complete": complete,
                        "market_cap": market_cap,
                        "has_raydium_pool": raydium_pool is not None
                    }
                elif resp.status == 404:
                    return {"exists": False}
    except Exception as e:
        logger.debug(f"Error checking Pump.fun for {address}: {e}")
    
    return {"exists": False}





async def check_raydium_pools(address: str) -> dict:
    """Vérifier s'il existe des pools Raydium pour ce token"""
    import aiohttp
    
    try:
        async with aiohttp.ClientSession() as session:
            # API Raydium pour chercher les pools
            url = f"https://api.raydium.io/v2/sdk/liquidity/mainnet"
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Chercher des pools contenant notre token
                    for pool in data.get("official", []) + data.get("unOfficial", []):
                        base_mint = pool.get("baseMint", "")
                        quote_mint = pool.get("quoteMint", "")
                        
                        if base_mint == address or quote_mint == address:
                            return {
                                "has_pool": True,
                                "pool_id": pool.get("id"),
                                "liquidity": pool.get("liquidity", 0),
                                "is_official": pool in data.get("official", [])
                            }
    except Exception as e:
        logger.debug(f"Error checking Raydium pools for {address}: {e}")
    
    return {"has_pool": False}  


def should_update_token_status(old_status: str, new_status: str) -> bool:
    """Détermine si le statut doit être mis à jour basé sur la priorité"""
    
    # Hiérarchie des statuts (plus élevé = plus prioritaire)
    status_priority = {
        "unknown": 0,
        "created": 1,
        "active": 2,
        "completed": 3,
        "terminated": 3,  # Même priorité que completed
        "migrated": 4     # Plus haute priorité
    }
    
    old_priority = status_priority.get(old_status, 0)
    new_priority = status_priority.get(new_status, 0)
    
    # Mettre à jour si le nouveau statut a une priorité plus élevée
    # ou si c'est une transition logique
    return new_priority > old_priority or is_valid_status_transition(old_status, new_status)

def is_valid_status_transition(from_status: str, to_status: str) -> bool:
    """Vérifie si la transition de statut est logique"""
    
    valid_transitions = {
        "created": ["active", "terminated"],
        "active": ["completed", "terminated"],
        "completed": ["migrated", "terminated"],
        "terminated": [],  # Les tokens terminés ne changent plus
        "migrated": [],    # Les tokens migrés ne changent plus
        "unknown": ["created", "active", "completed", "migrated", "terminated"]
    }
    
    allowed = valid_transitions.get(from_status, [])
    return to_status in allowed

# Fonction pour mettre à jour en masse les statuts existants
async def update_existing_token_statuses():
    """Mettre à jour les statuts de tous les tokens existants"""
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    try:
        # Récupérer tous les tokens sans statut ou avec statut "unknown"
        cursor.execute("""
            SELECT address, bonding_curve_status 
            FROM tokens 
            WHERE bonding_curve_status IS NULL 
               OR bonding_curve_status = 'unknown'
               OR bonding_curve_status = ''
            LIMIT 50
        """)
        
        tokens_to_update = cursor.fetchall()
        
        if not tokens_to_update:
            logger.info("✅ No tokens need status updates")
            return
        
        logger.info(f"🔄 Updating status for {len(tokens_to_update)} tokens...")
        
        client = AsyncClient("https://rpc.helius.xyz/?api-key=872ddf73-4cfd-4263-a418-521bbde27eb8")
        
        for address, current_status in tokens_to_update:
            try:
                new_status = await determine_bonding_curve_status(address, client)
                
                if new_status != "unknown" and new_status != current_status:
                    cursor.execute("""
                        UPDATE tokens 
                        SET bonding_curve_status = ?, updated_at = ?
                        WHERE address = ?
                    """, (new_status, get_local_timestamp(), address))
                    
                    logger.info(f"📊 Updated {address}: {current_status} -> {new_status}")
                
                # Petit délai pour éviter le rate limiting
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Error updating status for {address}: {e}")
                continue
        
        await client.close()
        conn.commit()
        
        logger.info(f"✅ Status update completed for {len(tokens_to_update)} tokens")
        
    except Exception as e:
        logger.error(f"Error in bulk status update: {e}")
    finally:
        conn.close()

async def get_bonding_curve_progress(address: str) -> dict:
    """Version corrigée avec les offsets exacts et formule précise"""
    try:
        from solders.pubkey import Pubkey
        from solana.rpc.async_api import AsyncClient
        import struct
        
        # Calculer l'adresse de la bonding curve
        pump_program = Pubkey.from_string("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
        mint_pubkey = Pubkey.from_string(address)
        seeds = [b"bonding-curve", bytes(mint_pubkey)]
        bonding_curve_address, _ = Pubkey.find_program_address(seeds, pump_program)
        
        client = AsyncClient("https://rpc.helius.xyz/?api-key=872ddf73-4cfd-4263-a418-521bbde27eb8")
        
        # Récupérer les données de la bonding curve
        account_info = await client.get_account_info(bonding_curve_address)
        
        if account_info.value and account_info.value.data:
            data = account_info.value.data
            
            # Offsets corrects selon la documentation Pump.fun
            virtual_token_reserves = struct.unpack('<Q', data[0x08:0x10])[0]
            virtual_sol_reserves = struct.unpack('<Q', data[0x10:0x18])[0]
            real_token_reserves = struct.unpack('<Q', data[0x18:0x20])[0]
            real_sol_reserves = struct.unpack('<Q', data[0x20:0x28])[0]
            
            # Formule officielle Pump.fun
            initial_virtual_tokens = 1_073_000_000  # 1.073B tokens virtuels initiaux
            tokens_to_sell = 793_100_000  # 793.1M tokens vendables
            
            # Progress = (tokens vendus virtuels) / tokens vendables * 100
            tokens_sold_virtual = (initial_virtual_tokens * 10**6 - virtual_token_reserves) / (10**6)
            progress = (tokens_sold_virtual / tokens_to_sell) * 100
            progress = max(0, min(progress, 99.9))
            
            await client.close()
            
            logger.debug(f"💎 Progress for {address}: {progress:.1f}%")
            
            return {
                "progress_percentage": round(progress, 1),
                "virtual_token_reserves": virtual_token_reserves / (10**6),
                "real_token_reserves": real_token_reserves / (10**6),
                "tokens_sold": tokens_sold_virtual,
                "source": "bonding_curve_direct",
                "has_progress_data": True
            }
        
        await client.close()
        
    except Exception as e:
        logger.debug(f"Error getting bonding curve progress for {address}: {e}")
    
    return {
        "progress_percentage": 0.0,
        "has_progress_data": False,
        "source": "no_data"
    }

async def get_bonding_curve_progress_old(address: str) -> dict:
    """Récupérer le pourcentage de progression de la bonding curve"""
    try:
        async with aiohttp.ClientSession() as session:
            # Essayer d'abord l'API Pump.fun
            url = f"https://frontend-api.pump.fun/coins/{address}"
            async with session.get(url, timeout=8) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Calcul du pourcentage basé sur market cap
                    market_cap = data.get("market_cap", 0)
                    bonding_curve_complete = data.get("complete", False)
                    
                    # Pump.fun complete généralement à ~69k$ market cap
                    TARGET_MARKET_CAP = 69000  # $69k en USD
                    
                    if bonding_curve_complete:
                        progress = 100.0
                    elif market_cap > 0:
                        progress = min((market_cap / TARGET_MARKET_CAP) * 100, 99.9)
                    else:
                        progress = 0.0
                    
                    logger.debug(f"📊 Progress for {address}: {progress}% (MC: ${market_cap})")
                    
                    return {
                        "progress_percentage": round(progress, 1),
                        "current_market_cap": market_cap,
                        "target_market_cap": TARGET_MARKET_CAP,
                        "complete": bonding_curve_complete,
                        "has_progress_data": True
                    }
                else:
                    logger.debug(f"Pump.fun API returned {resp.status} for {address}")
                
    except Exception as e:
        logger.debug(f"Error getting bonding curve progress from Pump.fun for {address}: {e}")
    
    # Fallback: essayer via DexScreener market cap
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
            async with session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    
                    if pairs:
                        best_pair = max(pairs, key=lambda p: p.get("marketCap", 0) or 0)
                        market_cap = best_pair.get("marketCap", 0) or 0
                        
                        if market_cap > 0:
                            TARGET_MARKET_CAP = 69000
                            progress = min((market_cap / TARGET_MARKET_CAP) * 100, 99.9)
                            
                            logger.debug(f"📊 Progress via DexScreener for {address}: {progress}% (MC: ${market_cap})")
                            
                            return {
                                "progress_percentage": round(progress, 1),
                                "current_market_cap": market_cap,
                                "target_market_cap": TARGET_MARKET_CAP,
                                "complete": progress >= 99.9,
                                "has_progress_data": True,
                                "source": "dexscreener"
                            }
                else:
                    logger.debug(f"DexScreener API returned {resp.status} for {address}")
                    
    except Exception as e:
        logger.debug(f"Error getting market cap from DexScreener for {address}: {e}")
    
    logger.debug(f"📊 No progress data found for {address}")
    return {
        "progress_percentage": 0.0,
        "has_progress_data": False
    }

async def validate_and_filter_token_candidates(candidates: list, client: AsyncClient) -> str | None:
    """Validate multiple token candidates and return the most likely mint."""
    if not candidates:
        return None
    
    logger.debug(f"Validating {len(candidates)} token candidates...")
    
    for pos, address in candidates:
        is_mint = await is_likely_token_mint(address, client)
        if is_mint:
            logger.debug(f"🎯 Confirmed token mint at position {pos}: {address}")
            return address
        else:
            logger.debug(f"❌ Position {pos} ({address}) is not a token mint")
    
    # Si aucun n'est validé comme mint, retourner None
    logger.warning("No valid token mint found in candidates")
    return None

async def is_likely_token_mint(address: str, client: AsyncClient) -> bool:
    """Check if an address is likely to be a token mint."""
    try:
        from solders.pubkey import Pubkey
        
        pubkey = Pubkey.from_string(address)
        account_info = await client.get_account_info(pubkey)
        
        if not account_info.value:
            return False
        
        # Vérifier si c'est détenu par le SPL Token Program
        if str(account_info.value.owner) != "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA":
            return False
        
        # Les token mints ont généralement 82 bytes de données
        data_length = len(account_info.value.data)
        if data_length != 82:
            logger.debug(f"Address {address} has {data_length} bytes, expected 82 for token mint")
            return False
        
        logger.debug(f"✅ {address} validated as token mint (owner: SPL Token Program, data: {data_length} bytes)")
        return True
        
    except Exception as e:
        logger.debug(f"Error validating {address} as token mint: {e}")
        return False

async def parse_raydium_pool(signature: str, client: AsyncClient) -> dict | None:
    """Parse Raydium transaction to extract token and pool address."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            logger.debug(f"Fetching Raydium transaction for signature: {signature} (attempt {attempt + 1}/{max_retries})")
            sig = Signature.from_string(signature)
            tx = await client.get_transaction(
                sig,
                commitment="finalized",
                max_supported_transaction_version=0
            )
            if not tx.value or not tx.value.transaction or not tx.value.transaction.transaction:
                logger.debug(f"No transaction data for signature: {signature}")
                return None
            
            message = tx.value.transaction.transaction.message
            pool_data = {"token_address": None, "pool_address": None}
            
            for i, instruction in enumerate(message.instructions):
                try:
                    program_id = str(message.account_keys[instruction.program_id_index])
                    logger.debug(f"Raydium instruction [{i}]: program_id={program_id}, accounts_count={len(instruction.accounts)}")
                    
                    if program_id == str(RAYDIUM_AMM_PROGRAM):
                        instruction_data = ""
                        try:
                            raw_data = instruction.data
                            if isinstance(raw_data, bytes):
                                try:
                                    decoded_bytes = base64.b64decode(raw_data)
                                    instruction_data = decoded_bytes.decode('utf-8', errors='ignore').lower()
                                except:
                                    instruction_data = raw_data.decode('utf-8', errors='ignore').lower()
                            else:
                                instruction_data = str(raw_data).lower()
                        except:
                            instruction_data = ""
                        
                        if any(keyword in instruction_data for keyword in ["initialize2", "initialize", "createpool"]):
                            if len(instruction.accounts) >= 3:
                                pool_data["pool_address"] = str(message.account_keys[instruction.accounts[0]])
                                pool_data["token_address"] = str(message.account_keys[instruction.accounts[1]])
                                logger.debug(
                                    f"Found Raydium pool: token_address={pool_data['token_address']}, "
                                    f"pool_address={pool_data['pool_address']}, signature={signature}"
                                )
                                break
                except Exception as inst_error:
                    logger.debug(f"Error processing Raydium instruction {i}: {inst_error}")
                    continue
            
            return pool_data if pool_data["token_address"] else None
            
        except HTTPStatusError as e:
            if e.response.status_code == 429:
                backoff = min(60, (2 ** (attempt + random.uniform(1, 5))))
                logger.warning(f"Rate limit hit for signature {signature}. Retrying in {backoff:.2f} seconds...")
                await asyncio.sleep(backoff)
                continue
            logger.error(f"HTTP error parsing Raydium pool for signature {signature}: {str(e)}")
            return None
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"Failed to parse Raydium pool for signature {signature} after {max_retries} attempts: {str(e)}")
                return None
            backoff = min(30, (2 ** (attempt + random.uniform(0.5, 1.5))))
            logger.warning(f"Error parsing Raydium signature {signature}, retrying in {backoff:.2f} seconds: {str(e)}")
            await asyncio.sleep(backoff)
    
    return None

def is_valid_token_address(address: str) -> bool:
    """Validate if an address could be a valid token address."""
    if not address:
        return False
    
    # Vérifier la longueur (les adresses Solana font généralement 32-44 caractères en base58)
    if len(address) < 32 or len(address) > 44:
        return False
    
    # Exclure les adresses système connues
    system_addresses = {
        "11111111111111111111111111111111",  # System Program
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",  # SPL Token Program
        "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",  # Pump.fun Program
        "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Raydium AMM
        "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",  # Associated Token Program
        "ComputeBudget111111111111111111111111111111",  # Compute Budget Program
    }
    
    if address in system_addresses:
        return False
    
    # Vérifier que l'adresse ne commence pas par des 1 répétés (indicateur d'adresse système)
    if address.startswith("111111111111111111111111111111"):
        return False
    
    # Vérifier que l'adresse contient des caractères valides en base58
    try:
        # Les caractères valides en base58 Bitcoin (utilisé par Solana)
        valid_chars = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
        if not all(c in valid_chars for c in address):
            return False
    except:
        return False
    
    return True


async def process_new_token(token_address, initial_status=None, raydium_pool_address=None):
    """Version améliorée de process_new_token avec détection de statut"""
    if not is_valid_token_address(token_address):
        logger.warning(f"Invalid token address detected: {token_address}")
        return
    
    # Créer un client Solana pour les vérifications
    client = AsyncClient("https://rpc.helius.xyz/?api-key=872ddf73-4cfd-4263-a418-521bbde27eb8")
    
    try:
        # Déterminer le vrai statut de la bonding curve
        real_status = await determine_bonding_curve_status(token_address, client)
        
        # Utiliser le statut déterminé ou celui fourni en paramètre
        bonding_curve_status = real_status if real_status != "unknown" else initial_status
        
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        # Utiliser l'heure locale pour les nouveaux tokens
        local_timestamp = get_local_timestamp()
        
        # Vérifier si le token existe déjà
        cursor.execute('SELECT address, bonding_curve_status FROM tokens WHERE address = ?', (token_address,))
        existing = cursor.fetchone()
        
        if existing:
            existing_status = existing[1]
            should_update = should_update_token_status(existing_status, bonding_curve_status)
            
            if should_update:
                cursor.execute('''
                    UPDATE tokens SET 
                        bonding_curve_status = ?,
                        raydium_pool_address = COALESCE(?, raydium_pool_address),
                        updated_at = ?,
                        launch_timestamp = COALESCE(launch_timestamp, ?)
                    WHERE address = ?
                ''', (
                    bonding_curve_status, 
                    raydium_pool_address,
                    local_timestamp,
                    local_timestamp,
                    token_address
                ))
                logger.info(f"🔄 Updated token status: {token_address} -> {bonding_curve_status}")
                
                # Queue for enrichment si changement significatif
                if bonding_curve_status in ["completed", "migrated", "terminated"]:
                    await token_enricher.queue_for_enrichment(token_address)
        else:
            # Insérer nouveau token
            cursor.execute('''
                INSERT INTO tokens (
                    address, symbol, name, decimals, logo_uri, price_usdc, market_cap,
                    liquidity_usd, volume_24h, price_change_24h, age_hours, quality_score,
                    rug_score, holders, holder_distribution, is_tradeable, invest_score,
                    early_bonus, social_bonus, holders_bonus, 
                    first_discovered_at, updated_at,
                    launch_timestamp, bonding_curve_status, raydium_pool_address
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                token_address, "UNKNOWN", None, None, None, None, None,
                None, None, None, None, None, None, None, None, None, None, None, None, None,
                local_timestamp, local_timestamp, local_timestamp,
                bonding_curve_status, raydium_pool_address
            ))
            logger.info(f"💾 New token: {token_address} -> {bonding_curve_status}")
            
            # Queue for enrichment
            await token_enricher.queue_for_enrichment(token_address)
        
        conn.commit()
        
        # Log des liens utiles
        logger.info(f"🔗 DEX: https://dexscreener.com/solana/{token_address}")
        if bonding_curve_status in ["active", "created", "completed"]:
            logger.info(f"🔗 Pump: https://pump.fun/coin/{token_address}")
            
    except Exception as e:
        logger.error(f"Error processing token {token_address}: {e}")
    finally:
        await client.close()
        conn.close()


token_enricher = OptimizedTokenEnricher()

# Ajouter cette fonction pour traiter les tokens existants non enrichis
async def enrich_existing_tokens():
    """Version optimisée pour enrichir les tokens existants"""
    while True:
        try:
            await asyncio.sleep(45)  # Vérifier toutes les 45 secondes
            
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            
            # Récupérer plus de tokens à la fois
            cursor.execute('''
                SELECT address FROM tokens 
                WHERE (symbol IS NULL OR symbol = 'UNKNOWN' OR symbol = '') 
                AND first_discovered_at > datetime('now', '-48 hours', 'localtime')
                ORDER BY first_discovered_at DESC
                LIMIT 25
            ''')
            
            unenriched = [row[0] for row in cursor.fetchall()]
            conn.close()
            
            if unenriched:
                logger.info(f"🔄 Found {len(unenriched)} unenriched tokens, queuing...")
                for address in unenriched:
                    await token_enricher.queue_for_enrichment(address)
                    await asyncio.sleep(0.1)  # Délai minimal entre ajouts
            
        except Exception as e:
            logger.error(f"Error in optimized existing tokens enrichment: {e}")
            await asyncio.sleep(60)
        

async def display_token_stats():
    """Afficher périodiquement les statistiques des tokens"""
    while True:
        try:
            await asyncio.sleep(300)  # Toutes les 5 minutes
            
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            
            # Stats générales
            cursor.execute("SELECT COUNT(*) FROM tokens")
            total = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tokens WHERE symbol != 'UNKNOWN' AND symbol IS NOT NULL")
            enriched = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tokens WHERE invest_score >= 80")
            high_score = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tokens WHERE first_discovered_at > datetime('now', '-1 hour', 'localtime')")
            recent = cursor.fetchone()[0]
            
            # Top 3 tokens par score
            cursor.execute('''
                SELECT symbol, invest_score, price_usdc, address 
                FROM tokens 
                WHERE invest_score IS NOT NULL AND invest_score > 0
                ORDER BY invest_score DESC 
                LIMIT 3
            ''')
            top_tokens = cursor.fetchall()
            
            conn.close()
            
            logger.info(f"📊 Stats: Total={total} | Enriched={enriched} | High Score={high_score} | Recent 1h={recent}")
            
            if top_tokens:
                logger.info("🏆 Top 3 tokens:")
                for i, (symbol, score, price, addr) in enumerate(top_tokens, 1):
                    logger.info(f"   {i}. {symbol} | Score: {score:.1f} | ${price:.8f} | {addr[:8]}...")
            
        except Exception as e:
            logger.error(f"Error in display_token_stats: {e}")
            await asyncio.sleep(300)


async def update_existing_token_statuses_loop():
    """Boucle pour mettre à jour les statuts des tokens existants"""
    while True:
        try:
            await asyncio.sleep(3600)  # Toutes les heures
            await update_existing_token_statuses()
        except Exception as e:
            logger.error(f"Error in status update loop: {e}")
            await asyncio.sleep(1800)  # Attendre 30min en cas d'erreur

async def monitor_pump_fun():
    """Monitor Pump.fun for new token mints and bonding curve completions."""
    async with AsyncClient(SOLANA_RPC_URL) as client:
        async def subscribe_to_program(program_id, subscription_id):
            while True:
                try:
                    logger.debug(f"Attempting WebSocket connection to {HELIUS_WS_URL} for program {program_id}")
                    async with websockets.connect(HELIUS_WS_URL, ping_interval=60, ping_timeout=30) as ws:
                        if program_id == PUMP_FUN_PROGRAM:
                            logger.info(f"🎯 Connected to Pump.fun monitoring")
                        elif program_id == SPL_TOKEN_PROGRAM:
                            logger.info(f"🎯 Connected to SPL Token monitoring")
                        subscription = {
                            "jsonrpc": "2.0",
                            "id": subscription_id,
                            "method": "logsSubscribe",
                            "params": [
                                {"mentions": [str(program_id)]},
                                {"commitment": "finalized"}
                            ]
                        }
                        await ws.send(json.dumps(subscription))
                        logger.debug(f"Sent subscription request for program {program_id}")
                        
                        last_log_time = time.time()
                        while True:
                            try:
                                message = await ws.recv()
                                logger.debug(f"WebSocket raw message for program {program_id}: {message[:500]}...")
                                message_data = json.loads(message)
                                
                                if "result" in message_data:
                                    logger.debug(f"Subscription confirmation for program {program_id}: {message_data['result']}")
                                    continue
                                
                                # Vérifier la structure du message
                                params = message_data.get("params")
                                if not params:
                                    continue
                                    
                                result = params.get("result")
                                if not result:
                                    continue
                                    
                                value = result.get("value")
                                if not value:
                                    continue
                                
                                logs = value.get("logs", [])
                                signature = value.get("signature")
                                
                                if not signature:
                                    logger.debug("No signature in message, skipping")
                                    continue
                                
                                logger.debug(f"Processing logs for program {program_id}, signature: {signature}, log count: {len(logs)}")
                                
                                # Traitement des logs avec gestion d'erreur améliorée
                                relevant_logs = []
                                for i, log in enumerate(logs):
                                    logger.debug(f"Log [{i}] for program {program_id}: {log}")
                                    
                                    if program_id == PUMP_FUN_PROGRAM:
                                        # Améliorer la détection des logs Pump.fun pertinents
                                        if any(keyword in log for keyword in [
                                            f"Program {str(PUMP_FUN_PROGRAM)} invoke",
                                            "Program log: Instruction: Buy",
                                            "Program log: Instruction: Create",
                                            "Program log: Instruction: RecordCreatorReferral",
                                            "Program log: Instruction: Initialize",
                                            "Program data:",  # Les données de programme contiennent souvent des infos importantes
                                        ]):
                                            relevant_logs.append((i, log))
                                            
                                        # Détecter aussi les invocations de sous-programmes
                                        elif any(prog in log for prog in [
                                            "Program PuMPXisBKLdSWqUkxEfae6jzp1p6MtiJoPjam5KMN7r invoke",  # Sous-programme Pump.fun
                                            "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke",
                                        ]):
                                            # Vérifier le contexte pour s'assurer que c'est lié à Pump.fun
                                            context_logs = logs[max(0, i-2):min(len(logs), i+3)]
                                            if any(f"Program {str(PUMP_FUN_PROGRAM)}" in ctx_log for ctx_log in context_logs):
                                                relevant_logs.append((i, log))
                                                
                                    elif program_id == SPL_TOKEN_PROGRAM:
                                        if any(keyword in log for keyword in [
                                            "Program log: Instruction: Transfer",
                                            "Program log: Instruction: InitializeAccount",
                                            "Program log: Instruction: InitializeMint",
                                            "Program log: Instruction: MintTo"
                                        ]):
                                            # Vérifier si c'est dans le contexte d'une transaction Pump.fun
                                            context_logs = logs[max(0, i-5):min(len(logs), i+5)]
                                            if any(f"Program {str(PUMP_FUN_PROGRAM)}" in ctx_log for ctx_log in context_logs):
                                                relevant_logs.append((i, log))
                                
                                if relevant_logs:
                                    logger.debug(f"Found {len(relevant_logs)} relevant logs for {program_id}")
                                    
                                    # Analyser les logs pour déterminer le type d'événement
                                    event_type = "unknown"
                                    for log_idx, log_content in relevant_logs:
                                        if "Buy" in log_content:
                                            event_type = "buy"
                                            break
                                        elif "Create" in log_content:
                                            event_type = "create"
                                            break
                                        elif "RecordCreatorReferral" in log_content:
                                            event_type = "referral"
                                            break
                                        elif "Program data:" in log_content:
                                            event_type = "data"
                                            break
                                    
                                    logger.debug(f"Detected {event_type} event for signature {signature}")
                                    
                                    try:
                                        token_address = await parse_pump_fun_event(signature, client)
                                        if token_address:
                                            # Détermine le statut basé sur les logs et le type d'événement
                                            status = "active"
                                            if event_type == "create":
                                                status = "created"
                                            elif any("completed" in log.lower() for _, log in relevant_logs):
                                                status = "completed"
                                            elif any("migrat" in log.lower() for _, log in relevant_logs):
                                                status = "migrated"
                                            elif event_type == "buy":
                                                status = "active"
                                            
                                            logger.debug(f"Pump.fun token event: address={token_address}, status={status}, event_type={event_type}, signature={signature}")
                                            await process_new_token(token_address, status, None)
                                    except Exception as parse_error:
                                        logger.error(f"Error parsing transaction {signature}: {parse_error}")
                                        continue
                                
                                # Log périodique de l'état de la connexion
                                if time.time() - last_log_time > 300:  # Toutes les 5 minutes
                                    logger.debug(f"Helius WebSocket still active for program {program_id}")
                                    last_log_time = time.time()
                                    
                            except websockets.exceptions.WebSocketException as e:
                                logger.error(f"WebSocket error for program {program_id}: {str(e)}")
                                break
                            except json.JSONDecodeError as e:
                                logger.error(f"JSON decode error for program {program_id}: {str(e)}")
                                continue
                            except Exception as e:
                                logger.error(f"Message processing error for program {program_id}: {str(e)}")
                                continue
                            
                except websockets.exceptions.InvalidStatusCode as e:
                    logger.error(f"WebSocket connection failed for program {program_id} with status {e.status_code}: {str(e)}")
                    if e.status_code == 401:
                        logger.error(f"Invalid Helius API key. Stopping monitoring for program {program_id}.")
                        return
                    backoff = min(60, (2 ** random.uniform(1, 5)))
                    logger.debug(f"Retrying connection for program {program_id} in {backoff:.2f} seconds...")
                    await asyncio.sleep(backoff)
                except Exception as e:
                    logger.error(f"Unexpected error in monitoring program {program_id}: {str(e)}")
                    backoff = min(60, (2 ** random.uniform(1, 5)))
                    logger.debug(f"Retrying connection for program {program_id} in {backoff:.2f} seconds...")
                    await asyncio.sleep(backoff)

        # Lancer les souscriptions pour les deux programmes en parallèle
        await asyncio.gather(
            subscribe_to_program(PUMP_FUN_PROGRAM, 1),
            subscribe_to_program(SPL_TOKEN_PROGRAM, 3)
        )

async def monitor_raydium_pools():
    """Monitor Raydium for new liquidity pools."""
    async with AsyncClient(SOLANA_RPC_URL) as client:
        while True:
            try:
                logger.debug(f"Attempting WebSocket connection to {HELIUS_WS_URL}")
                async with websockets.connect(HELIUS_WS_URL, ping_interval=60, ping_timeout=30) as ws:
                    logger.info("🎯 Connected to Raydium monitoring")
                    
                    subscription = {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "logsSubscribe",
                        "params": [
                            {"mentions": [str(RAYDIUM_AMM_PROGRAM)]},
                            {"commitment": "finalized"}
                        ]
                    }
                    await ws.send(json.dumps(subscription))
                    logger.debug("Sent Raydium subscription request")
                    
                    last_log_time = time.time()
                    while True:
                        try:
                            message = await ws.recv()
                            logger.debug(f"Raydium WebSocket raw message: {message[:500]}...")
                            message_data = json.loads(message)
                            
                            if "result" in message_data:
                                logger.debug(f"Raydium subscription confirmation received: {message_data['result']}")
                                continue
                            
                            # Vérification de structure similaire
                            params = message_data.get("params")
                            if not params:
                                continue
                                
                            result = params.get("result")
                            if not result:
                                continue
                                
                            value = result.get("value")
                            if not value:
                                continue
                            
                            logs = value.get("logs", [])
                            signature = value.get("signature")
                            
                            if not signature:
                                continue
                            
                            logger.debug(f"Processing Raydium logs for signature: {signature}, log count: {len(logs)}")
                            
                            # Vérifier qu'il s'agit bien d'une transaction Raydium
                            has_raydium_program = False
                            raydium_invoke_indices = []
                            
                            for i, log in enumerate(logs):
                                logger.debug(f"Raydium log [{i}]: {log}")
                                # Vérifier spécifiquement le programme Raydium
                                if f"Program {str(RAYDIUM_AMM_PROGRAM)} invoke" in log:
                                    has_raydium_program = True
                                    raydium_invoke_indices.append(i)
                                    logger.debug(f"Found Raydium program invocation at log {i}")
                            
                            if not has_raydium_program:
                                logger.debug(f"No Raydium program found in logs for signature {signature}")
                                continue
                            
                            # Chercher les mots-clés pertinents uniquement après une invocation Raydium
                            for invoke_idx in raydium_invoke_indices:
                                # Vérifier les logs suivants pour des mots-clés d'initialisation
                                for check_idx in range(invoke_idx + 1, min(invoke_idx + 5, len(logs))):
                                    if check_idx < len(logs):
                                        log_to_check = logs[check_idx].lower()
                                        if any(keyword in log_to_check for keyword in [
                                            "initialize2", "initialize", "createpool", "ray_log"
                                        ]):
                                            logger.debug(f"Potential Raydium pool initialization detected at log {check_idx}: {logs[check_idx]}")
                                            try:
                                                pool_data = await parse_raydium_pool(signature, client)
                                                if pool_data:
                                                    logger.debug(
                                                        f"New Raydium pool detected: token_address={pool_data['token_address']}, "
                                                        f"pool_address={pool_data['pool_address']}, signature={signature}"
                                                    )
                                                    await process_new_token(pool_data["token_address"], "migrated", pool_data["pool_address"])
                                                    break  # Une seule détection par transaction
                                            except Exception as parse_error:
                                                logger.error(f"Error parsing Raydium pool {signature}: {parse_error}")
                                                continue
                            
                            if time.time() - last_log_time > 300:
                                logger.debug("Helius WebSocket still active for Raydium")
                                last_log_time = time.time()
                                    
                        except websockets.exceptions.WebSocketException as e:
                            logger.error(f"Raydium WebSocket error: {str(e)}")
                            break
                        except json.JSONDecodeError as e:
                            logger.error(f"Raydium JSON decode error: {str(e)}")
                            continue
                        except Exception as e:
                            logger.error(f"Raydium message processing error: {str(e)}")
                            continue
                            
            except websockets.exceptions.InvalidStatusCode as e:
                logger.error(f"Raydium WebSocket connection failed with status {e.status_code}: {str(e)}")
                if e.status_code == 401:
                    logger.error("Invalid Helius API key. Stopping Raydium monitoring.")
                    return
                backoff = min(60, (2 ** random.uniform(1, 5)))
                logger.debug(f"Retrying Raydium connection in {backoff:.2f} seconds...")
                await asyncio.sleep(backoff)
            except Exception as e:
                logger.error(f"Unexpected error in Raydium monitoring: {str(e)}")
                backoff = min(60, (2 ** random.uniform(1, 5)))
                logger.debug(f"Retrying Raydium connection in {backoff:.2f} seconds...")
                await asyncio.sleep(backoff)

async def parse_pump_fun_event(signature: str, client: AsyncClient) -> str | None:
    """Parse Pump.fun transaction to extract token address with validation."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            logger.debug(f"Fetching Pump.fun transaction for signature: {signature} (attempt {attempt + 1}/{max_retries})")
            sig = Signature.from_string(signature)
            tx = await client.get_transaction(
                sig,
                commitment="finalized",
                max_supported_transaction_version=0
            )
            
            if not tx.value or not tx.value.transaction or not tx.value.transaction.transaction:
                logger.debug(f"No valid transaction data for signature: {signature}")
                return None

            # Accéder au message de la transaction
            message = tx.value.transaction.transaction.message
            all_candidates = []
            
            for i, instruction in enumerate(message.instructions):
                try:
                    # Récupérer l'adresse du programme
                    program_id = str(message.account_keys[instruction.program_id_index])
                    accounts = [str(message.account_keys[idx]) for idx in instruction.accounts]
                    
                    # Ignorer les programmes non pertinents
                    if program_id in ["ComputeBudget111111111111111111111111111111", "11111111111111111111111111111111"]:
                        logger.debug(f"Skipping irrelevant program: {program_id}")
                        continue
                    
                    # Gérer instruction.data de manière plus robuste
                    instruction_data = ""
                    try:
                        raw_data = instruction.data
                        if raw_data:
                            if isinstance(raw_data, bytes):
                                # Essayer d'abord directement en UTF-8
                                try:
                                    instruction_data = raw_data.decode('utf-8', errors='ignore').lower()
                                except:
                                    # Puis essayer en tant que base64
                                    try:
                                        decoded_bytes = base64.b64decode(raw_data)
                                        instruction_data = decoded_bytes.decode('utf-8', errors='ignore').lower()
                                    except:
                                        instruction_data = ""
                            elif isinstance(raw_data, str):
                                try:
                                    # D'abord essayer comme base64
                                    decoded_bytes = base64.b64decode(raw_data)
                                    instruction_data = decoded_bytes.decode('utf-8', errors='ignore').lower()
                                except:
                                    # Sinon utiliser tel quel
                                    instruction_data = raw_data.lower()
                            else:
                                instruction_data = str(raw_data).lower()
                    except Exception as decode_error:
                        logger.debug(f"Could not decode instruction data for instruction {i}: {decode_error}")
                        instruction_data = ""
                    
                    logger.debug(
                        f"Pump.fun instruction [{i}]: program_id={program_id}, "
                        f"decoded_data={instruction_data[:50] if instruction_data else 'empty'}, accounts_length={len(instruction.accounts)}"
                    )
                    
                    # Logique de parsing basée sur le programme et les comptes
                    if program_id == "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA":  # SPL Token Program
                        # Pour les instructions de token, chercher les mint addresses
                        if any(keyword in instruction_data for keyword in ["initializemint", "mint", "transfer"]):
                            if len(instruction.accounts) >= 1:
                                potential_token = str(message.account_keys[instruction.accounts[0]])
                                # Vérifier que ce n'est pas un compte système
                                if not potential_token.startswith("111111111111111111111111111111"):
                                    all_candidates.append((f"SPL_{i}_0", potential_token))
                                    logger.debug(f"Added SPL token candidate: {potential_token}")
                                    
                    elif program_id == "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P":  # Pump.fun program
                        # Pour Pump.fun, analyser la structure typique des comptes
                        if len(instruction.accounts) >= 2:
                            accounts = [str(message.account_keys[idx]) for idx in instruction.accounts]
                            
                            # Log tous les comptes pour debug
                            logger.debug(f"Pump.fun instruction accounts: {[(i, acc) for i, acc in enumerate(accounts)]}")
                            
                            # Exclure les comptes système et de service connus
                            system_accounts = {
                                "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",  # Pump.fun program
                                "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",  # SPL Token
                                "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",  # ATA
                                "So11111111111111111111111111111111111111112",   # Wrapped SOL
                                "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
                                "CebN5WGQ4jvEPvsVU4EoHEpgzq1VV7AbicfhtW4xC9iM",  # Fee account connu
                                "TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM",   # Autre fee account
                            }
                            
                            # Filtrer les comptes valides et les ajouter aux candidats
                            for pos, account in enumerate(accounts):
                                if (not account.startswith("111111111111111111111111111111") and
                                    account not in system_accounts and
                                    len(account) >= 32):
                                    all_candidates.append((f"PumpFun_{i}_{pos}", account))
                                    logger.debug(f"Added Pump.fun candidate at position {pos}: {account}")
                                    
                    elif program_id == "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL":  # Associated Token Program
                        if any(keyword in instruction_data for keyword in ["create"]) and len(instruction.accounts) >= 4:
                            # Dans ATA, le mint est généralement au 4ème compte
                            potential_token = str(message.account_keys[instruction.accounts[3]])
                            if not potential_token.startswith("111111111111111111111111111111"):
                                all_candidates.append((f"ATA_{i}_3", potential_token))
                                logger.debug(f"Added ATA candidate: {potential_token}")
                                
                except Exception as inst_error:
                    logger.debug(f"Error processing instruction {i}: {inst_error}")
                    continue

            # Maintenant valider tous les candidats trouvés
            if all_candidates:
                logger.debug(f"Found {len(all_candidates)} total candidates: {[addr for _, addr in all_candidates]}")
                
                # Valider les candidats avec la blockchain
                validated_token = await validate_and_filter_token_candidates(all_candidates, client)
                if validated_token:
                    logger.info(f"🎯 Final validated token address: {validated_token}")
                    return validated_token
                else:
                    logger.warning(f"No candidates validated as token mints for signature {signature}")
            else:
                logger.debug(f"No token candidates found in transaction: {signature}")
                
            return None
            
        except HTTPStatusError as e:
            if e.response.status_code == 429:
                backoff = min(60, (2 ** (attempt + random.uniform(1, 5))))
                logger.warning(f"Rate limit hit for signature {signature}. Retrying in {backoff:.2f} seconds...")
                await asyncio.sleep(backoff)
                continue
            logger.error(f"HTTP error parsing Pump.fun event for signature {signature}: {str(e)}")
            return None
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"Error parsing Pump.fun event for signature {signature} after {max_retries} attempts: {str(e)}")
                return None
            backoff = min(30, (2 ** (attempt + random.uniform(0.5, 1.5))))
            logger.warning(f"Error parsing signature {signature}, retrying in {backoff:.2f} seconds: {str(e)}")
            await asyncio.sleep(backoff)
    
    return None


def migrate_database_progress():
    """Migration spécifique pour ajouter la colonne bonding_curve_progress"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    try:
        # Vérifier si la colonne existe
        cursor.execute("PRAGMA table_info(tokens)")
        cols = {col[1] for col in cursor.fetchall()}
        
        if 'bonding_curve_progress' not in cols:
            cursor.execute("ALTER TABLE tokens ADD COLUMN bonding_curve_progress REAL DEFAULT 0")
            logger.info("✅ Added bonding_curve_progress column")
        
        conn.commit()
        
    except sqlite3.Error as e:
        logger.error(f"Error migrating database: {e}")
    finally:
        conn.close()

async def start_monitoring(log_level='INFO'):
    """Start Pump.fun and Raydium monitoring tasks with enrichment."""
    logger.info(f"🚀 Starting Enhanced Solana monitoring with enrichment (log level: {log_level})")

    # ✅ AJOUTER CETTE LIGNE
    migrate_database_progress()

    # ✅ TEST de validation
    test_address = "41vZZpGqBQ2dGxS99cmWZuQuC7X97VbcqiAobp29pump"
    test_progress = await get_bonding_curve_progress(test_address)
    logger.info(f"🧪 Test progress for {test_address}: {test_progress}")
    
    # Vérifier que le résultat est cohérent avec DexScreener (4.8%)
    if test_progress.get("progress_percentage", 0) > 0:
        logger.info("✅ Bonding curve calculation working correctly!")
    else:
        logger.warning("⚠️ Bonding curve calculation may need adjustment")

    # Créer la base de données si elle n'existe pas
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tokens (
            address TEXT PRIMARY KEY,
            symbol TEXT,
            name TEXT,
            decimals INTEGER,
            logo_uri TEXT,
            price_usdc REAL,
            market_cap REAL,
            liquidity_usd REAL,
            volume_24h REAL,
            price_change_24h REAL,
            age_hours REAL,
            quality_score REAL,
            rug_score REAL,
            holders INTEGER,
            holder_distribution TEXT,
            is_tradeable BOOLEAN DEFAULT 0,
            invest_score REAL,
            early_bonus INTEGER DEFAULT 0,
            social_bonus INTEGER DEFAULT 0,
            holders_bonus INTEGER DEFAULT 0,
            first_discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            launch_timestamp TIMESTAMP,
            bonding_curve_status TEXT,
            raydium_pool_address TEXT
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("✅ Database initialized successfully")
    
    # Démarrer l'enricher
    await token_enricher.start()
    logger.info("✅ Token enricher started successfully")
    
    try:
        # Lancer toutes les tâches en parallèle
        await asyncio.gather(
            monitor_pump_fun(),
            monitor_raydium_pools(),
            enrich_existing_tokens(),
            display_token_stats(),
            update_existing_token_statuses_loop(),  # ← NOUVELLE TÂCHE
            return_exceptions=False
        )
    except Exception as e:
        logger.error(f"Error in monitoring tasks: {str(e)}")
        raise
    finally:
        await token_enricher.stop()
        logger.info("🛑 Token enricher stopped")

# Point d'entrée principal si le script est lancé directement
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Enhanced Solana Token Monitor with Enrichment")
    parser.add_argument("--log-level", 
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        default='INFO',
                        help="Set logging level (default: INFO)")
    
    args = parser.parse_args()
    
    # Configuration du logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('solana_monitoring.log'),
            logging.StreamHandler()
        ]
    )
    
    # Réduire les logs des bibliothèques externes
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    
    try:
        asyncio.run(start_monitoring(args.log_level))
    except KeyboardInterrupt:
        logger.info("\n✅ Monitor stopped by user.")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
    
    

