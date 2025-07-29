#!/usr/bin/env python3
"""
🎯 Enhanced Solana Monitor with Whale Detection Integration
Monitors Pump.fun and Raydium for new tokens and whale transactions
"""
# -*- coding: utf-8 -*-
import os
import sys

# Forcer l'encodage UTF-8 sur Windows
if sys.platform == "win32":
    import codecs
    _original_stdout = sys.stdout
    _original_stderr = sys.stderr

# Forcer les variables d'environnement pour UTF-8
os.environ['PYTHONIOENCODING'] = 'utf-8'

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

# Import du système de détection whale
from whale_detector_integration import (
    whale_detector, 
    start_whale_monitoring, 
    stop_whale_monitoring,
    process_websocket_logs_for_whales
)

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

parsing_stats = {
    'pump_fun_attempts': 0,
    'pump_fun_success': 0,
    'raydium_attempts': 0,
    'raydium_success': 0
}

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
        """RugCheck optimisé"""
        url = f"https://api.rugcheck.xyz/v1/tokens/{address}/report"
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data:
                        normalized_score = data.get("score_normalised", None)
                        raw_score = data.get("score", 50)
                        final_score = normalized_score if normalized_score is not None else raw_score
                        final_score = max(0, min(100, final_score))
                        return {"rug_score": final_score}
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

    async def stop(self):
        """Arrêter l'enrichisseur"""
        self.is_running = False
        if self.session:
            await self.session.close()

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
                                
                                # 🐋 NOUVEAU: Traiter pour la détection whale
                                await process_websocket_logs_for_whales(signature, logs)
                                
                                # Traitement normal pour les nouveaux tokens
                                relevant_logs = []
                                for i, log in enumerate(logs):
                                    logger.debug(f"Log [{i}] for program {program_id}: {log}")
                                    
                                    if program_id == PUMP_FUN_PROGRAM:
                                        if any(keyword in log for keyword in [
                                            f"Program {str(PUMP_FUN_PROGRAM)} invoke",
                                            "Program log: Instruction: Buy",
                                            "Program log: Instruction: Create",
                                            "Program log: Instruction: RecordCreatorReferral",
                                            "Program log: Instruction: Initialize",
                                            "Program data:",
                                        ]):
                                            relevant_logs.append((i, log))
                                            
                                        elif any(prog in log for prog in [
                                            "Program PuMPXisBKLdSWqUkxEfae6jzp1p6MtiJoPjam5KMN7r invoke",
                                            "Program TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA invoke",
                                        ]):
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
                                            context_logs = logs[max(0, i-5):min(len(logs), i+5)]
                                            if any(f"Program {str(PUMP_FUN_PROGRAM)}" in ctx_log for ctx_log in context_logs):
                                                relevant_logs.append((i, log))
                                
                                if relevant_logs:
                                    if len(signature) < 80 or any(char in signature for char in [' ', '\n', '\t']):
                                        logger.debug(f"Invalid signature format, skipping: {signature[:20]}...")
                                        continue
                                    
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
                                        logger.debug(f"Error parsing transaction {signature}: {parse_error}")
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
                            
                            # 🐋 NOUVEAU: Traiter pour la détection whale
                            await process_websocket_logs_for_whales(signature, logs)
                            
                            # Traitement normal pour Raydium...
                            has_raydium_program = False
                            raydium_invoke_indices = []
                            
                            for i, log in enumerate(logs):
                                logger.debug(f"Raydium log [{i}]: {log}")
                                if f"Program {str(RAYDIUM_AMM_PROGRAM)} invoke" in log:
                                    has_raydium_program = True
                                    raydium_invoke_indices.append(i)
                                    logger.debug(f"Found Raydium program invocation at log {i}")
                            
                            if not has_raydium_program:
                                logger.debug(f"No Raydium program found in logs for signature {signature}")
                                continue
                            
                            for invoke_idx in raydium_invoke_indices:
                                for check_idx in range(invoke_idx + 1, min(invoke_idx + 5, len(logs))):
                                    if check_idx < len(logs):
                                        log_to_check = logs[check_idx].lower()
                                        if any(keyword in log_to_check for keyword in [
                                            "initialize2", "initialize", "createpool", "ray_log"
                                        ]):
                                            logger.debug(f"Potential Raydium pool initialization detected at log {check_idx}: {logs[check_idx]}")
                                            try:
                                                if len(signature) < 80 or any(char in signature for char in [' ', '\n', '\t']):
                                                    logger.debug(f"Invalid Raydium signature format, skipping: {signature[:20]}...")
                                                    continue
                                                pool_data = await parse_raydium_pool(signature, client)
                                                if pool_data:
                                                    logger.debug(
                                                        f"New Raydium pool detected: token_address={pool_data['token_address']}, "
                                                        f"pool_address={pool_data['pool_address']}, signature={signature}"
                                                    )
                                                    await process_new_token(pool_data["token_address"], "migrated", pool_data["pool_address"])
                                                    break
                                            except Exception as parse_error:
                                                logger.debug(f"Error parsing Raydium pool {signature}: {parse_error}")
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

# Fonctions utilitaires pour parsing
async def parse_pump_fun_event(signature: str, client: AsyncClient) -> str | None:
    """Parse Pump.fun transaction to extract token address with validation."""
    if not signature or len(signature) < 80:  # Signature invalide
        return None

    parsing_stats['pump_fun_attempts'] += 1
    max_retries = 1
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
                    program_id = str(message.account_keys[instruction.program_id_index])
                    accounts = [str(message.account_keys[idx]) for idx in instruction.accounts]
                    
                    if program_id in ["ComputeBudget111111111111111111111111111111", "11111111111111111111111111111111"]:
                        logger.debug(f"Skipping irrelevant program: {program_id}")
                        continue
                    
                    if program_id == "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P":  # Pump.fun program
                        if len(instruction.accounts) >= 2:
                            accounts = [str(message.account_keys[idx]) for idx in instruction.accounts]
                            
                            logger.debug(f"Pump.fun instruction accounts: {[(i, acc) for i, acc in enumerate(accounts)]}")
                            
                            system_accounts = {
                                "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
                                "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                                "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
                                "So11111111111111111111111111111111111111112",
                                "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                                "CebN5WGQ4jvEPvsVU4EoHEpgzq1VV7AbicfhtW4xC9iM",
                                "TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM",
                            }
                            
                            for pos, account in enumerate(accounts):
                                if (not account.startswith("111111111111111111111111111111") and
                                    account not in system_accounts and
                                    len(account) >= 32):
                                    all_candidates.append((f"PumpFun_{i}_{pos}", account))
                                    logger.debug(f"Added Pump.fun candidate at position {pos}: {account}")
                                    
                except Exception as inst_error:
                    logger.debug(f"Error processing instruction {i}: {inst_error}")
                    continue

            if all_candidates:
                logger.debug(f"Found {len(all_candidates)} total candidates: {[addr for _, addr in all_candidates]}")
                
                validated_token = await validate_and_filter_token_candidates(all_candidates, client)
                if validated_token:
                    logger.info(f"🎯 Final validated token address: {validated_token}")
                    parsing_stats['pump_fun_success'] += 1
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
                logger.debug(f"Error parsing Pump.fun event for signature {signature} after {max_retries} attempts: {str(e)}")
                return None
            backoff = min(30, (2 ** (attempt + random.uniform(0.5, 1.5))))
            logger.warning(f"Error parsing signature {signature}, retrying in {backoff:.2f} seconds: {str(e)}")
            await asyncio.sleep(backoff)
    
    return None

async def parse_raydium_pool(signature: str, client: AsyncClient) -> dict | None:
    """Parse Raydium transaction to extract token and pool address."""
    parsing_stats['raydium_attempts'] += 1
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
            
            if pool_data and pool_data["token_address"]:
                parsing_stats['raydium_success'] += 1

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
            logger.debug(f"Failed to parse Raydium pool for signature {signature} after {max_retries} attempts: {str(e)}")
            await asyncio.sleep(backoff)
    
    return None

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
        
        if str(account_info.value.owner) != "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA":
            return False
        
        data_length = len(account_info.value.data)
        if data_length != 82:
            logger.debug(f"Address {address} has {data_length} bytes, expected 82 for token mint")
            return False
        
        logger.debug(f"✅ {address} validated as token mint (owner: SPL Token Program, data: {data_length} bytes)")
        return True
        
    except Exception as e:
        logger.debug(f"Error validating {address} as token mint: {e}")
        return False

async def process_new_token(token_address, initial_status=None, raydium_pool_address=None):
    """Process new token detection with improved status determination"""
    if not is_valid_token_address(token_address):
        logger.warning(f"Invalid token address detected: {token_address}")
        return
    
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        local_timestamp = get_local_timestamp()
        
        cursor.execute('SELECT address, bonding_curve_status FROM tokens WHERE address = ?', (token_address,))
        existing = cursor.fetchone()
        
        if existing:
            existing_status = existing[1]
            if should_update_token_status(existing_status, initial_status):
                cursor.execute('''
                    UPDATE tokens SET 
                        bonding_curve_status = ?,
                        raydium_pool_address = COALESCE(?, raydium_pool_address),
                        updated_at = ?,
                        launch_timestamp = COALESCE(launch_timestamp, ?)
                    WHERE address = ?
                ''', (
                    initial_status, 
                    raydium_pool_address,
                    local_timestamp,
                    local_timestamp,
                    token_address
                ))
                logger.info(f"🔄 Updated token status: {token_address} -> {initial_status}")
                
                if initial_status in ["completed", "migrated", "terminated"]:
                    await token_enricher.queue_for_enrichment(token_address)
        else:
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
                initial_status, raydium_pool_address
            ))
            logger.info(f"💾 New token: {token_address} -> {initial_status}")
            
            await token_enricher.queue_for_enrichment(token_address)
        
        conn.commit()
        
        logger.info(f"🔗 DEX: https://dexscreener.com/solana/{token_address}")
        if initial_status in ["active", "created", "completed"]:
            logger.info(f"🔗 Pump: https://pump.fun/coin/{token_address}")
            
    except Exception as e:
        logger.error(f"Error processing token {token_address}: {e}")
    finally:
        conn.close()

def is_valid_token_address(address: str) -> bool:
    """Validate if an address could be a valid token address."""
    if not address or len(address) < 32 or len(address) > 44:
        return False
    
    system_addresses = {
        "11111111111111111111111111111111",
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
        "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
        "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
        "ComputeBudget111111111111111111111111111111",
    }
    
    if address in system_addresses:
        return False
    
    if address.startswith("111111111111111111111111111111"):
        return False
    
    try:
        valid_chars = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
        if not all(c in valid_chars for c in address):
            return False
    except:
        return False
    
    return True

def should_update_token_status(old_status: str, new_status: str) -> bool:
    """Détermine si le statut doit être mis à jour basé sur la priorité"""
    status_priority = {
        "unknown": 0,
        "created": 1,
        "active": 2,
        "completed": 3,
        "terminated": 3,
        "migrated": 4
    }
    
    old_priority = status_priority.get(old_status, 0)
    new_priority = status_priority.get(new_status, 0)
    
    return new_priority > old_priority

# Instance globale de l'enricher
token_enricher = OptimizedTokenEnricher()

async def enrich_existing_tokens():
    """Version optimisée pour enrichir les tokens existants"""
    while True:
        try:
            await asyncio.sleep(45)
            
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            
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
                    await asyncio.sleep(0.1)
            
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
            
            cursor.execute("SELECT COUNT(*) FROM tokens")
            total = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tokens WHERE symbol != 'UNKNOWN' AND symbol IS NOT NULL")
            enriched = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tokens WHERE invest_score >= 80")
            high_score = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tokens WHERE first_discovered_at > datetime('now', '-1 hour', 'localtime')")
            recent = cursor.fetchone()[0]
            
            # 🐋 NOUVEAU: Stats des whales
            cursor.execute("SELECT COUNT(*) FROM whale_transactions_live WHERE timestamp > datetime('now', '-1 hour', 'localtime')")
            whale_activity = cursor.fetchone()[0]
            
            cursor.execute('''
                SELECT symbol, invest_score, price_usdc, address 
                FROM tokens 
                WHERE invest_score IS NOT NULL AND invest_score > 0
                ORDER BY invest_score DESC 
                LIMIT 3
            ''')
            top_tokens = cursor.fetchall()
            
            conn.close()
            
            pump_total = parsing_stats['pump_fun_attempts']
            pump_success = parsing_stats['pump_fun_success']
            raydium_total = parsing_stats['raydium_attempts']
            raydium_success = parsing_stats['raydium_success']
            
            pump_rate = (pump_success / max(1, pump_total)) * 100
            raydium_rate = (raydium_success / max(1, raydium_total)) * 100
            
            logger.info(f"📊 Parsing success rates - Pump.fun: {pump_rate:.1f}% ({pump_success}/{pump_total}) | Raydium: {raydium_rate:.1f}% ({raydium_success}/{raydium_total})")
            logger.info(f"📊 Stats: Total={total} | Enriched={enriched} | High Score={high_score} | Recent 1h={recent} | 🐋 Whales 1h={whale_activity}")
            
            if top_tokens:
                logger.info("🏆 Top 3 tokens:")
                for i, (symbol, score, price, addr) in enumerate(top_tokens, 1):
                    logger.info(f"   {i}. {symbol} | Score: {score:.1f} | ${price:.8f} | {addr[:8]}...")
            
        except Exception as e:
            logger.error(f"Error in display_token_stats: {e}")
            await asyncio.sleep(300)

def migrate_database_progress():
    """Migration spécifique pour ajouter la colonne bonding_curve_progress"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    try:
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
    """Start enhanced monitoring with whale detection."""
    logger.info(f"🚀 Starting Enhanced Solana monitoring with whale detection (log level: {log_level})")
    
    # Migration de la base de données
    migrate_database_progress()
    
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
            raydium_pool_address TEXT,
            updated_at TIMESTAMP,
            bonding_curve_progress REAL DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("✅ Database initialized successfully")
    
    # Démarrer l'enricher et le système whale
    await token_enricher.start()
    logger.info("✅ Token enricher started successfully")
    
    # 🐋 NOUVEAU: Démarrer la détection whale
    await start_whale_monitoring()
    logger.info("🐋 Whale monitoring started successfully")
    
    try:
        # Lancer toutes les tâches en parallèle
        await asyncio.gather(
            monitor_pump_fun(),
            monitor_raydium_pools(),
            enrich_existing_tokens(),
            display_token_stats(),
            return_exceptions=False
        )
    except Exception as e:
        logger.error(f"Error in monitoring tasks: {str(e)}")
        raise
    finally:
        await token_enricher.stop()
        await stop_whale_monitoring()
        logger.info("🛑 All monitoring stopped")

def setup_logging(log_level='INFO'):
    """Configuration du logging avec support UTF-8 correct"""
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Créer le logger principal
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level))
    
    # Supprimer les handlers existants
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # File handler avec UTF-8 explicite
    file_handler = logging.FileHandler('solana_monitoring.log', encoding='utf-8')
    file_handler.setLevel(getattr(logging, log_level))
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    
    # Console handler avec UTF-8
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, log_level))
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

# Point d'entrée principal si le script est lancé directement
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Enhanced Solana Token Monitor with Whale Detection")
    parser.add_argument("--log-level", 
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        default='INFO',
                        help="Set logging level (default: INFO)")
    
    args = parser.parse_args()
    
    # Configuration du logging
    setup_logging(args.log_level)
    
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