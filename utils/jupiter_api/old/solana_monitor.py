import asyncio
import json
import logging
import sqlite3
import websockets
from solders.pubkey import Pubkey
from solders.signature import Signature
from solana.rpc.async_api import AsyncClient
from datetime import datetime, timezone
from decouple import config
from websockets.exceptions import ConnectionClosedError, InvalidStatusCode
import random
import time
from httpx import HTTPStatusError
import base64

# Configuration du logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Capturer tous les niveaux de logs
if not logger.handlers:  # Éviter d'ajouter plusieurs handlers
    file_handler = logging.FileHandler("solana_monitor.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(stream_handler)

# Constants
PUMP_FUN_PROGRAM = Pubkey.from_string("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
SPL_TOKEN_PROGRAM = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
RAYDIUM_AMM_PROGRAM = Pubkey.from_string("675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8")
HELIUS_WS_URL = f"wss://rpc.helius.xyz/?api-key={config('HELIUS_API_KEY', default='')}"
#SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com" #limites trop strictes
SOLANA_RPC_URL = f"https://rpc.helius.xyz/?api-key={config('HELIUS_API_KEY', default='872ddf73-4cfd-4263-a418-521bbde27eb8')}"
#SOLANA_RPC_URL = f"https://solana-mainnet.quicknode.com/{config('QUICKNODE_API_KEY', default='')}" #QUICKNODE
DATABASE_PATH = "tokens.db"

async def monitor_pump_fun():
    """Monitor Pump.fun for new token mints and bonding curve completions."""
    async with AsyncClient(SOLANA_RPC_URL) as client:
        async def subscribe_to_program(program_id, subscription_id):
            while True:
                try:
                    logger.debug(f"Attempting WebSocket connection to {HELIUS_WS_URL} for program {program_id}")
                    async with websockets.connect(HELIUS_WS_URL, ping_interval=60, ping_timeout=30) as ws:
                        logger.info(f"Connected to Helius WebSocket for program {program_id}")
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
                        logger.debug(f"Sent subscription request for program {program_id}: %s", json.dumps(subscription, indent=2))
                        
                        last_log_time = time.time()
                        while True:
                            try:
                                message = await ws.recv()
                                logger.debug(f"WebSocket raw message for program {program_id}: %s", message[:500] + ("..." if len(message) > 500 else ""))
                                message_data = json.loads(message)
                                if "result" in message_data:
                                    logger.info(f"Subscription confirmation for program {program_id}: %s", message_data["result"])
                                    continue
                                
                                logs = message_data.get("params", {}).get("result", {}).get("value", {}).get("logs", [])
                                signature = message_data.get("params", {}).get("result", {}).get("value", {}).get("signature")
                                logger.debug(f"Processing logs for program {program_id}, signature: %s, log count: %d", signature, len(logs))
                                
                                for i, log in enumerate(logs):
                                    logger.debug(f"Log [{i}] for program {program_id}: %s", log)  # Loguer chaque log brut
                                    if program_id == PUMP_FUN_PROGRAM:
                                        if any(keyword in log.lower() for keyword in ["bondingcurve", "completed", "create"]):
                                            token_address = await parse_pump_fun_event(signature, client)
                                            if token_address:
                                                status = "completed" if "completed" in log.lower() else "active"
                                                logger.info(f"Pump.fun token event: address=%s, status=%s, signature=%s", token_address, status, signature)
                                                await process_new_token(token_address, status, None)
                                    elif program_id == SPL_TOKEN_PROGRAM:
                                        if any(keyword in log.lower() for keyword in ["tokenmint", "create", "initializeaccount", "initializemint"]):
                                            token_address = await parse_pump_fun_event(signature, client)
                                            if token_address:
                                                logger.info(f"Pump.fun token created: address=%s, signature=%s", token_address, signature)
                                                await process_new_token(token_address, "active", None)
                                
                                # Loguer périodiquement l'état de la connexion
                                if time.time() - last_log_time > 300:  # Toutes les 5 minutes
                                    logger.info(f"Helius WebSocket still active for program {program_id}")
                                    last_log_time = time.time()
                                    
                            except websockets.exceptions.WebSocketException as e:
                                logger.error(f"WebSocket error for program {program_id}: %s", str(e))
                                break
                            except Exception as e:
                                logger.error(f"Message processing error for program {program_id}, signature %s: %s", signature, str(e))
                                continue
                            
                except websockets.exceptions.InvalidStatusCode as e:
                    logger.error(f"WebSocket connection failed for program {program_id} with status %d: %s", e.status_code, str(e))
                    if e.status_code == 401:
                        logger.error("Invalid Helius API key. Stopping monitoring for program %s.", program_id)
                        return
                    backoff = min(60, (2 ** random.uniform(1, 5)))
                    logger.info(f"Retrying connection for program {program_id} in %.2f seconds...", backoff)
                    await asyncio.sleep(backoff)
                except websockets.exceptions.WebSocketException as e:
                    logger.error(f"WebSocket connection error for program {program_id}: %s", str(e))
                    backoff = min(60, (2 ** random.uniform(1, 5)))
                    logger.info(f"Retrying connection for program {program_id} in %.2f seconds...", backoff)
                    await asyncio.sleep(backoff)
                except Exception as e:
                    logger.error(f"Unexpected error in monitoring program {program_id}: %s", str(e))
                    backoff = min(60, (2 ** random.uniform(1, 5)))
                    logger.info(f"Retrying connection for program {program_id} in %.2f seconds...", backoff)
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
                    logger.info("Connected to Helius WebSocket for Raydium monitoring")
                    
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
                    logger.debug("Sent Raydium subscription request: %s", json.dumps(subscription, indent=2))
                    
                    last_log_time = time.time()
                    while True:
                        try:
                            message = await ws.recv()
                            logger.debug("Raydium WebSocket raw message: %s", message[:500] + ("..." if len(message) > 500 else ""))
                            message_data = json.loads(message)
                            if "result" in message_data:
                                logger.info("Raydium subscription confirmation received: %s", message_data["result"])
                                continue
                            
                            logs = message_data.get("params", {}).get("result", {}).get("value", {}).get("logs", [])
                            signature = message_data.get("params", {}).get("result", {}).get("value", {}).get("signature")
                            logger.debug("Processing Raydium logs for signature: %s, log count: %d", signature, len(logs))
                            
                            for i, log in enumerate(logs):
                                logger.debug("Raydium log [%d]: %s", i, log)
                                if "Program 675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8 invoke" in log:
                                    next_log = logs[i + 1] if i + 1 < len(logs) else ""
                                    if any(keyword in next_log.lower() for keyword in ["initialize2", "createpool"]):
                                        logger.debug("Potential pool initialization detected: %s", next_log)
                                        pool_data = await parse_raydium_pool(signature, client)
                                        if pool_data:
                                            logger.info(
                                                "New Raydium pool detected: token_address=%s, pool_address=%s, signature=%s",
                                                pool_data["token_address"], pool_data["pool_address"], signature
                                            )
                                            await process_new_token(pool_data["token_address"], "migrated", pool_data["pool_address"])
                            
                            if time.time() - last_log_time > 300:
                                logger.info("Helius WebSocket still active for Raydium")
                                last_log_time = time.time()
                                    
                        except websockets.exceptions.WebSocketException as e:
                            logger.error("Raydium WebSocket error: %s", str(e))
                            break
                        except Exception as e:
                            logger.error("Raydium message processing error for signature %s: %s", signature, str(e))
                            continue
                            
            except websockets.exceptions.InvalidStatusCode as e:
                logger.error("Raydium WebSocket connection failed with status %d: %s", e.status_code, str(e))
                if e.status_code == 401:
                    logger.error("Invalid Helius API key. Stopping Raydium monitoring.")
                    return
                backoff = min(60, (2 ** random.uniform(1, 5)))
                logger.info("Retrying Raydium connection in %.2f seconds...", backoff)
                await asyncio.sleep(backoff)
            except websockets.exceptions.WebSocketException as e:
                logger.error("Raydium WebSocket connection error: %s", str(e))
                backoff = min(60, (2 ** random.uniform(1, 5)))
                logger.info("Retrying Raydium connection in %.2f seconds...", backoff)
                await asyncio.sleep(backoff)
            except Exception as e:
                logger.error("Unexpected error in Raydium monitoring: %s", str(e))
                backoff = min(60, (2 ** random.uniform(1, 5)))
                logger.info("Retrying Raydium connection in %.2f seconds...", backoff)
                await asyncio.sleep(backoff)

async def parse_pump_fun_event(signature: str, client: AsyncClient) -> str | None:
    """Parse Pump.fun transaction to extract token address."""
    try:
        logger.debug(f"Fetching Pump.fun transaction for signature: %s", signature)
        sig = Signature.from_string(signature)
        tx = await client.get_transaction(
            sig,
            commitment="finalized",
            max_supported_transaction_version=0
        )
        if not tx.value or not tx.value.transaction or not tx.value.transaction.transaction:
            logger.debug(f"No valid transaction data for signature: %s", signature)
            return None

        # Accéder au message de la transaction
        message = tx.value.transaction.transaction.message
        token_address = None
        for i, instruction in enumerate(message.instructions):
            # Récupérer l'adresse du programme
            program_id = str(message.account_keys[instruction.program_id_index])
            accounts = [str(message.account_keys[idx]) for idx in instruction.accounts]
            # Ignorer les programmes non pertinents
            if program_id in ["ComputeBudget111111111111111111111111111111", "11111111111111111111111111111111"]:
                logger.debug("Skipping irrelevant program: %s", program_id)
                continue
            
            # Vérifier si instruction.data est bytes ou str
            instruction_data = instruction.data
            raw_data = instruction_data
            if isinstance(instruction_data, bytes):
                instruction_data = instruction_data.decode('utf-8', errors='ignore')
            elif isinstance(instruction_data, str):
                try:
                    instruction_data = base64.b64decode(instruction_data).decode('utf-8', errors='ignore')
                except (base64.binascii.Error, UnicodeDecodeError):
                    pass
            instruction_data = instruction_data.lower()
            logger.debug(
                "Pump.fun instruction [%d]: program_id=%s, raw_data=%s, decoded_data=%s, accounts=%s, accounts_length=%d",
                i, program_id, raw_data, instruction_data, accounts, len(instruction.accounts)
            )
            
            if program_id == "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA":
                if any(keyword in instruction_data for keyword in ["initializemint", "tokenmint", "transfer", "closeaccount"]):
                    if len(instruction.accounts) >= 1:
                        token_address = str(message.account_keys[instruction.accounts[0]])
                        logger.info("Found token address in Token Program: %s", token_address)
            elif program_id == "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P":
                if any(keyword in instruction_data for keyword in ["create", "createidempotent", "bondingcurve", "global", "initialize", "mint"]):
                    if len(instruction.accounts) >= 2:
                        token_address = str(message.account_keys[instruction.accounts[1]])
                        logger.info("Found potential token address in Pump.fun transaction: %s", token_address)
                    else:
                        logger.debug("Insufficient accounts for Pump.fun instruction: %d", len(instruction.accounts))
            elif program_id == "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL":
                if any(keyword in instruction_data for keyword in ["createidempotent", "create"]):
                    if len(instruction.accounts) >= 4:
                        token_address = str(message.account_keys[instruction.accounts[3]])
                        logger.info("Found token address in Associated Token Program: %s", token_address)
                    else:
                        logger.debug("Insufficient accounts for Associated Token instruction: %d", len(instruction.accounts))
            elif program_id == "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8":
                if any(keyword in instruction_data for keyword in ["ray_log", "initialize", "swap"]):
                    if len(instruction.accounts) >= 2:
                        token_address = str(message.account_keys[instruction.accounts[1]])
                        logger.info("Found potential token address in Raydium Program: %s", token_address)
                    else:
                        logger.debug("Insufficient accounts for Raydium instruction: %d", len(instruction.accounts))

        if not token_address:
            logger.debug("No token address found in transaction: %s", signature)
        return token_address
    except Exception as e:
        logger.error("Error parsing Pump.fun event for signature %s: %s", signature, str(e))
        return None

async def parse_raydium_pool(signature: str, client: AsyncClient) -> dict | None:
    """Parse Raydium transaction to extract token and pool address."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            logger.debug(f"Fetching Raydium transaction for signature: %s (attempt {attempt + 1}/{max_retries})", signature)
            sig = Signature.from_string(signature)
            tx = await client.get_transaction(
                sig,
                commitment="finalized",
                max_supported_transaction_version=0
            )
            if not tx.value:
                logger.debug(f"No transaction data for signature: %s", signature)
                return None
            
            pool_data = {"token_address": None, "pool_address": None}
            for i, instruction in enumerate(tx.value.transaction.message.instructions):
                logger.debug("Raydium instruction [%d]: program_id=%s, data=%s, accounts=%s", 
                            i, instruction.program_id, instruction.data, instruction.accounts)
                if str(instruction.program_id) == str(RAYDIUM_AMM_PROGRAM):
                    instruction_data = str(instruction.data).lower()
                    if any(keyword in instruction_data for keyword in ["initialize2", "initialize", "createpool"]):
                        if len(instruction.accounts) >= 3:
                            pool_data["token_address"] = instruction.accounts[0].to_string()
                            pool_data["pool_address"] = instruction.accounts[1].to_string()
                            logger.info(
                                "Found Raydium pool: token_address=%s, pool_address=%s, signature=%s",
                                pool_data["token_address"], pool_data["pool_address"], signature
                            )
            if not pool_data["token_address"]:
                logger.debug("No token or pool address found in transaction: %s", signature)
            else:
                logger.info("Parsed Raydium pool data: %s", pool_data)
            return pool_data if pool_data["token_address"] else None
        except HTTPStatusError as e:
            if e.response.status_code == 429:
                backoff = min(60, (2 ** (attempt + random.uniform(1, 5))))
                logger.warning(f"Rate limit hit for signature {signature}. Retrying in {backoff:.2f} seconds...")
                await asyncio.sleep(backoff)
                continue
            logger.error("HTTP error parsing Raydium pool for signature %s: %s", signature, str(e))
            return None
        except Exception as e:
            logger.error("Error parsing Raydium pool for signature %s: %s", signature, str(e))
            return None
    logger.error(f"Failed to parse Raydium pool for signature {signature} after {max_retries} attempts")
    return None

async def process_new_token(token_address, bonding_curve_status, raydium_pool_address):
    """Store newly detected token in the database."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO tokens (
                address, symbol, name, decimals, logo_uri, price_usdc, market_cap,
                liquidity_usd, volume_24h, price_change_24h, age_hours, quality_score,
                rug_score, holders, holder_distribution, is_tradeable, invest_score,
                early_bonus, social_bonus, holders_bonus, first_discovered_at,
                launch_timestamp, bonding_curve_status, raydium_pool_address
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ? ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?)
        ''', (
            token_address, "UNKNOWN", None, None, None, None, None,
            None, None, None, None, None, None, None, None, None, None, None, None, None, None,
            datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            bonding_curve_status, raydium_pool_address
        ))
        conn.commit()
        logger.info(
            "Saved token to database: address=%s, bonding_curve_status=%s, raydium_pool_address=%s",
            token_address, bonding_curve_status, raydium_pool_address or "None"
        )
    except sqlite3.Error as e:
        logger.error("Database error saving token %s: %s", token_address, str(e))
    finally:
        conn.close()

async def start_monitoring():
    """Start Pump.fun and Raydium monitoring tasks."""
    logger.debug("Starting monitoring tasks")
    if logger.handlers:
        logger.handlers[0].flush()
    await asyncio.gather(
        monitor_pump_fun(),
        monitor_raydium_pools()
    )