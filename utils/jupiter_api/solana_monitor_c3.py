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

class TokenEnricher:
    """Classe pour enrichir les tokens détectés en temps réel"""
    
    def __init__(self):
        self.session: aiohttp.ClientSession = None
        self.enrichment_queue = asyncio.Queue()
        self.is_running = False
        
    async def start(self):
        """Démarrer l'enrichissement en arrière-plan"""
        if self.is_running:
            return
            
        self.session = aiohttp.ClientSession(
            connector=TCPConnector(limit=30),
            timeout=aiohttp.ClientTimeout(total=15)
        )
        self.is_running = True
        
        # Démarrer la tâche d'enrichissement en arrière-plan
        asyncio.create_task(self._enrichment_worker())
        logger.info("🔍 Token enricher started")
    
    async def stop(self):
        """Arrêter l'enrichissement"""
        self.is_running = False
        if self.session:
            await self.session.close()
            self.session = None
    
    async def queue_for_enrichment(self, address: str):
        """Ajouter un token à la queue d'enrichissement"""
        if self.is_running:
            await self.enrichment_queue.put(address)
            set_enrichment_queue_size(self.enrichment_queue.qsize())
            logger.debug(f"🔄 Queued token for enrichment: {address} (queue size: {self.enrichment_queue.qsize()})")
    
    async def _enrichment_worker(self):
        """Worker qui enrichit les tokens en continu"""
        while self.is_running:
            try:

                # Mettre à jour le nombre de tâches actives
                from performance_monitor import set_active_enrichment_tasks
                set_active_enrichment_tasks(1)
                # Attendre un nouveau token (timeout de 10s)
                address = await asyncio.wait_for(
                    self.enrichment_queue.get(), 
                    timeout=10.0
                )
                
                set_enrichment_queue_size(self.enrichment_queue.qsize())

                logger.info(f"🔍 Starting enrichment for: {address}")

                # Mesurer le temps d'enrichissement
                start_time = time.time()
                success = False

                try:
                    await self._enrich_token(address)
                    success = True
                except Exception as e:
                    logger.error(f"Error enriching token {address}: {e}")
                    success = False
                finally:
                    # Enregistrer les métriques
                    enrichment_time = time.time() - start_time
                    record_token_update(address, enrichment_time, success)
                # Délai entre les enrichissements pour éviter le rate limiting

                await asyncio.sleep(3)
                
            except asyncio.TimeoutError:
                # Pas de nouveau token, continuer
                continue
            except Exception as e:
                logger.error(f"Error in enrichment worker: {e}")
                await asyncio.sleep(5)
            finally:
                # Remettre à 0 les tâches actives
                set_active_enrichment_tasks(0)
    
    async def _fetch_json(self, url: str, timeout: int = 10) -> dict:
        """Fetch JSON avec gestion d'erreur"""
        # Déterminer le type d'API à partir de l'URL
        api_type = "unknown"
        if "jupiter" in url:
            api_type = "jupiter"
        elif "dexscreener" in url:
            api_type = "dexscreener"
        elif "rugcheck" in url:
            api_type = "rugcheck"
        elif "helius" in url:
            api_type = "helius"
        elif "solscan" in url:
            api_type = "solscan"
        
        start_time = time.time()
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    call_time = time.time() - start_time
                    record_api_call(api_type, call_time)
                    return await resp.json()
                else:
                    call_time = time.time() - start_time
                    record_api_call(f"{api_type}_error", call_time)
                    logger.debug(f"HTTP {resp.status} for {url}")
                    return {}
        except Exception as e:
            call_time = time.time() - start_time
            record_api_call(f"{api_type}_error", call_time)
            logger.debug(f"Error fetching {url}: {e}")
            return {}
    
    async def _get_token_metadata(self, address: str) -> dict:
        """Récupérer les métadonnées du token"""
        # Essayer Helius d'abord
        helius_url = f"https://rpc.helius.xyz/?api-key=872ddf73-4cfd-4263-a418-521bbde27eb8"
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getAsset",
            "params": {"id": address}
        }
        
        try:
            async with self.session.post(helius_url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result = data.get("result", {})
                    content = result.get("content", {})
                    metadata = content.get("metadata", {})
                    
                    if metadata:
                        return {
                            "symbol": metadata.get("symbol", "UNKNOWN"),
                            "name": metadata.get("name", "Unknown Token"),
                            "decimals": result.get("token_info", {}).get("decimals", 9),
                            "logo_uri": content.get("files", [{}])[0].get("uri") if content.get("files") else None
                        }
        except Exception as e:
            logger.debug(f"Error getting Helius metadata for {address}: {e}")
        
        # Fallback: vérifier Jupiter
        jupiter_url = "https://token.jup.ag/all"
        jupiter_data = await self._fetch_json(jupiter_url)
        
        if jupiter_data:
            for token in jupiter_data:
                if token.get("address") == address:
                    return {
                        "symbol": token.get("symbol", "UNKNOWN"),
                        "name": token.get("name", "Unknown Token"),
                        "decimals": token.get("decimals", 9),
                        "logo_uri": token.get("logoURI")
                    }
        
        return {
            "symbol": "UNKNOWN",
            "name": "Unknown Token",
            "decimals": 9,
            "logo_uri": None
        }

    async def _get_market_data(self, address: str) -> dict:
        """Récupérer les données de marché"""
        market_data = {}
        
        # DexScreener
        dex_url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
        dex_data = await self._fetch_json(dex_url)
        
        if dex_data and dex_data.get("pairs"):
            pair = dex_data["pairs"][0]
            market_data.update({
                "price_usdc": float(pair.get("priceUsd", 0)),
                "market_cap": float(pair.get("marketCap", 0)),
                "liquidity_usd": float(pair.get("liquidity", {}).get("usd", 0)),
                "volume_24h": float(pair.get("volume", {}).get("h24", 0)),
                "price_change_24h": float(pair.get("priceChange", {}).get("h24", 0)),
                "age_hours": (time.time() * 1000 - pair.get("pairCreatedAt", time.time() * 1000)) / 3600000
            })
        
        # Jupiter price check
        jupiter_quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={address}&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=1000000&slippageBps=500"
        jupiter_price = await self._fetch_json(jupiter_quote_url)
        
        if jupiter_price and "outAmount" in jupiter_price:
            try:
                price = int(jupiter_price["outAmount"]) / 1e6
                if not market_data.get("price_usdc"):
                    market_data["price_usdc"] = price
                market_data["is_tradeable"] = True
            except:
                pass
        
        # RugCheck
        rug_url = f"https://api.rugcheck.xyz/v1/tokens/{address}/report"
        rug_data = await self._fetch_json(rug_url)
        
        if rug_data:
            market_data.update({
                "rug_score": rug_data.get("score", 50),
                "quality_score": min(100, max(0, rug_data.get("score", 50)))
            })
        
        # Holders via Helius
        holders_count = await self._get_holders_via_helius(address)
        market_data["holders"] = holders_count
        
        return market_data

    async def _get_holders_via_helius(self, address: str) -> int:
        """Récupérer le nombre de holders via Helius API"""
        try:
            helius_url = "https://rpc.helius.xyz/?api-key=872ddf73-4cfd-4263-a418-521bbde27eb8"
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenLargestAccounts",
                "params": [address]
            }
            
            async with self.session.post(helius_url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "result" in data and "value" in data["result"]:
                        # Compter les comptes avec un solde > 0
                        accounts = data["result"]["value"]
                        holders = len([acc for acc in accounts if acc.get("uiAmount", 0) > 0])
                        logger.debug(f"✅ Helius holders for {address}: {holders}")
                        return holders
                    else:
                        logger.debug(f"Helius response structure: {data}")
                else:
                    logger.debug(f"Helius HTTP {resp.status} for {address}")
                    
        except Exception as e:
            logger.error(f"Error getting holders via Helius for {address}: {e}")
        
        # Fallback: essayer une méthode alternative avec getProgramAccounts
        try:
            payload_alternative = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getProgramAccounts",
                "params": [
                    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                    {
                        "encoding": "jsonParsed",
                        "filters": [
                            {
                                "dataSize": 165
                            },
                            {
                                "memcmp": {
                                    "offset": 0,
                                    "bytes": address
                                }
                            }
                        ]
                    }
                ]
            }
            
            async with self.session.post(helius_url, json=payload_alternative, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "result" in data:
                        # Compter les comptes token actifs
                        active_accounts = 0
                        for account in data["result"]:
                            try:
                                parsed = account.get("account", {}).get("data", {}).get("parsed", {})
                                info = parsed.get("info", {})
                                if float(info.get("tokenAmount", {}).get("uiAmount", 0)) > 0:
                                    active_accounts += 1
                            except:
                                continue
                        
                        logger.debug(f"✅ Helius alternative method holders for {address}: {active_accounts}")
                        return active_accounts
                        
        except Exception as e:
            logger.debug(f"Helius alternative method failed for {address}: {e}")
        
        logger.warning(f"❌ Could not get holders count for {address}")
        return 0

    def _calculate_invest_score(self, data: dict) -> float:
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
    
    async def _enrich_token(self, address: str):
        """Enrichir un token complet"""
        try:
            logger.info(f"🔍 Enriching token: {address}")
            
            # Récupérer métadonnées et données de marché en parallèle
            metadata_task = self._get_token_metadata(address)
            market_task = self._get_market_data(address)
            
            metadata, market_data = await asyncio.gather(metadata_task, market_task)
            
            # Combiner les données
            enriched_data = {**metadata, **market_data}
            enriched_data["address"] = address
            
            # Calculer le score d'investissement
            enriched_data["invest_score"] = self._calculate_invest_score(enriched_data)
            
            # Déterminer si tradeable
            if "is_tradeable" not in enriched_data:
                enriched_data["is_tradeable"] = bool(
                    enriched_data.get("price_usdc", 0) > 0 or
                    enriched_data.get("volume_24h", 0) > 0
                )
            
            # Sauvegarder en base
            await self._update_token_in_db(enriched_data)
            
            # Log du résultat
            symbol = enriched_data.get("symbol", "UNKNOWN")
            score = enriched_data.get("invest_score", 0)
            price = enriched_data.get("price_usdc", 0)
            
            logger.info(f"✅ Enriched {symbol} | Score: {score} | Price: ${price:.8f}")
            
            # Alert pour les tokens à fort potentiel
            if score >= 80:
                logger.warning(f"🚨 HIGH SCORE TOKEN: {symbol} (Score: {score}) - {address}")
                logger.warning(f"🔗 DexScreener: https://dexscreener.com/solana/{address}")
                logger.warning(f"🔗 Pump.fun: https://pump.fun/coin/{address}")
            
        except Exception as e:
            logger.error(f"Error enriching token {address}: {e}")
    
    async def _update_token_in_db(self, token_data: dict):
        """Mettre à jour le token dans la base de données"""
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        try:
            # Utiliser l'heure locale pour updated_at
            local_timestamp = get_local_timestamp()
            
            cursor.execute('''
                UPDATE tokens SET 
                    symbol = ?, name = ?, decimals = ?, logo_uri = ?,
                    price_usdc = ?, market_cap = ?, liquidity_usd = ?, volume_24h = ?,
                    price_change_24h = ?, age_hours = ?, quality_score = ?, rug_score = ?,
                    holders = ?, is_tradeable = ?, invest_score = ?,
                    updated_at = ?
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
                token_data.get("is_tradeable"),
                token_data.get("invest_score"),
                local_timestamp,  # updated_at avec heure locale
                token_data["address"]
            ))
            
            conn.commit()
            logger.debug(f"💾 Updated token {token_data['address']} in database")
            
        except sqlite3.Error as e:
            logger.error(f"Database error updating token {token_data['address']}: {e}")
        finally:
            conn.close()

    async def _update_token_in_db_old(self, token_data: dict):
        """Mettre à jour le token dans la base de données"""
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE tokens SET 
                    symbol = ?, name = ?, decimals = ?, logo_uri = ?,
                    price_usdc = ?, market_cap = ?, liquidity_usd = ?, volume_24h = ?,
                    price_change_24h = ?, age_hours = ?, quality_score = ?, rug_score = ?,
                    holders = ?, is_tradeable = ?, invest_score = ?,
                    updated_at = CURRENT_TIMESTAMP
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


async def process_new_token(token_address, bonding_curve_status, raydium_pool_address):
    """Store newly detected token in the database and queue for enrichment."""
    if not is_valid_token_address(token_address):
        logger.warning(f"Invalid token address detected: {token_address}")
        return
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    try:
        # Utiliser l'heure locale pour les nouveaux tokens
        local_timestamp = get_local_timestamp()
        
        # Vérifier si le token existe déjà
        cursor.execute('SELECT address, bonding_curve_status FROM tokens WHERE address = ?', (token_address,))
        existing = cursor.fetchone()
        
        if existing:
            # Mettre à jour les informations existantes seulement si c'est pertinent
            existing_status = existing[1]
            should_update = False
            
            # Logic de mise à jour intelligente
            if not existing_status and bonding_curve_status:
                should_update = True
            elif existing_status == "active" and bonding_curve_status in ["completed", "migrated"]:
                should_update = True
            elif existing_status == "completed" and bonding_curve_status == "migrated":
                should_update = True
            elif not raydium_pool_address is None:  # Toujours mettre à jour si on a une nouvelle pool address
                should_update = True
            
            if should_update:
                cursor.execute('''
                    UPDATE tokens SET 
                        bonding_curve_status = COALESCE(?, bonding_curve_status),
                        raydium_pool_address = COALESCE(?, raydium_pool_address),
                        updated_at = ?,
                        launch_timestamp = COALESCE(launch_timestamp, ?)
                    WHERE address = ?
                ''', (
                    bonding_curve_status, 
                    raydium_pool_address,
                    local_timestamp,  # updated_at avec heure locale
                    local_timestamp,  # launch_timestamp avec heure locale
                    token_address
                ))
                logger.debug(f"🔄 Updated existing token: address={token_address}, status={bonding_curve_status}")
                
                # Queue for re-enrichment if status changed significantly
                if bonding_curve_status in ["completed", "migrated"]:
                    await token_enricher.queue_for_enrichment(token_address)
            else:
                logger.debug(f"⏩ No update needed for token: address={token_address}, existing_status={existing_status}, new_status={bonding_curve_status}")
        else:
            # Insérer un nouveau token avec l'heure locale
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
                local_timestamp,  # first_discovered_at avec heure locale
                local_timestamp,  # updated_at avec heure locale
                local_timestamp,  # launch_timestamp avec heure locale
                bonding_curve_status, raydium_pool_address
            ))
            logger.info(f"💾 Saved new token: address={token_address}, status={bonding_curve_status}")
            
            # Queue for enrichment
            await token_enricher.queue_for_enrichment(token_address)
            
            # Log des liens utiles pour vérification manuelle
            logger.info(f"🔗 DEX Screener: https://dexscreener.com/solana/{token_address}")
            if bonding_curve_status in ["active", "completed"]:
                logger.info(f"🔗 Pump.fun: https://pump.fun/coin/{token_address}")
        
        conn.commit()
        
    except sqlite3.Error as e:
        logger.error(f"Database error saving token {token_address}: {str(e)}")
    finally:
        conn.close()


async def process_new_token_old(token_address, bonding_curve_status, raydium_pool_address):
    """Store newly detected token in the database and queue for enrichment."""
    if not is_valid_token_address(token_address):
        logger.warning(f"Invalid token address detected: {token_address}")
        return
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    try:
        # Vérifier si le token existe déjà
        cursor.execute('SELECT address, bonding_curve_status FROM tokens WHERE address = ?', (token_address,))
        existing = cursor.fetchone()
        
        if existing:
            # Mettre à jour les informations existantes seulement si c'est pertinent
            existing_status = existing[1]
            should_update = False
            
            # Logic de mise à jour intelligente
            if not existing_status and bonding_curve_status:
                should_update = True
            elif existing_status == "active" and bonding_curve_status in ["completed", "migrated"]:
                should_update = True
            elif existing_status == "completed" and bonding_curve_status == "migrated":
                should_update = True
            elif not raydium_pool_address is None:  # Toujours mettre à jour si on a une nouvelle pool address
                should_update = True
            
            if should_update:
                cursor.execute('''
                    UPDATE tokens SET 
                        bonding_curve_status = COALESCE(?, bonding_curve_status),
                        raydium_pool_address = COALESCE(?, raydium_pool_address),
                        launch_timestamp = COALESCE(launch_timestamp, ?)
                    WHERE address = ?
                ''', (
                    bonding_curve_status, 
                    raydium_pool_address, 
                    datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                    token_address
                ))
                logger.debug(f"🔄 Updated existing token: address={token_address}, status={bonding_curve_status}")
                
                # Queue for re-enrichment if status changed significantly
                if bonding_curve_status in ["completed", "migrated"]:
                    await token_enricher.queue_for_enrichment(token_address)
            else:
                logger.debug(f"⏩ No update needed for token: address={token_address}, existing_status={existing_status}, new_status={bonding_curve_status}")
        else:
            # Insérer un nouveau token
            cursor.execute('''
                INSERT INTO tokens (
                    address, symbol, name, decimals, logo_uri, price_usdc, market_cap,
                    liquidity_usd, volume_24h, price_change_24h, age_hours, quality_score,
                    rug_score, holders, holder_distribution, is_tradeable, invest_score,
                    early_bonus, social_bonus, holders_bonus, first_discovered_at,
                    launch_timestamp, bonding_curve_status, raydium_pool_address
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?)
            ''', (
                token_address, "UNKNOWN", None, None, None, None, None,
                None, None, None, None, None, None, None, None, None, None, None, None, None,
                datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                bonding_curve_status, raydium_pool_address
            ))
            logger.info(f"💾 Saved new token: address={token_address}, status={bonding_curve_status}")
            
            # Queue for enrichment
            await token_enricher.queue_for_enrichment(token_address)
            
            # Log des liens utiles pour vérification manuelle
            logger.info(f"🔗 DEX Screener: https://dexscreener.com/solana/{token_address}")
            if bonding_curve_status in ["active", "completed"]:
                logger.info(f"🔗 Pump.fun: https://pump.fun/coin/{token_address}")
        
        conn.commit()
        
    except sqlite3.Error as e:
        logger.error(f"Database error saving token {token_address}: {str(e)}")
    finally:
        conn.close()

async def enrich_existing_tokens():
    """Enrichir périodiquement les tokens existants non enrichis"""
    while True:
        try:
            # Attendre 60 secondes entre chaque cycle d'enrichissement
            await asyncio.sleep(60)
            
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            
            # Trouver les tokens non enrichis
            cursor.execute('''
                SELECT address FROM tokens 
                WHERE (symbol IS NULL OR symbol = 'UNKNOWN' OR symbol = '') 
                AND first_discovered_at > datetime('now', '-24 hours', 'localtime')
                ORDER BY first_discovered_at DESC
                LIMIT 5
            ''')
            
            unenriched = [row[0] for row in cursor.fetchall()]
            conn.close()
            
            if unenriched:
                logger.info(f"🔄 Found {len(unenriched)} unenriched tokens from last 24h")
                for address in unenriched:
                    await token_enricher.queue_for_enrichment(address)
                    await asyncio.sleep(2)  # Délai entre chaque ajout à la queue
            
        except Exception as e:
            logger.error(f"Error in enrich_existing_tokens: {e}")
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


# Instance globale de l'enricher
token_enricher = TokenEnricher()

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


async def start_monitoring(log_level='INFO'):
    """Start Pump.fun and Raydium monitoring tasks with enrichment."""
    logger.info(f"🚀 Starting Enhanced Solana monitoring with enrichment (log level: {log_level})")

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
    
    

