#!/usr/bin/env python3
"""
🐋 Whale Detector Integration - Intégration du système de détection whale
Version adaptée pour s'intégrer parfaitement avec solana_monitor_c4.py
"""
import random
from asyncio import Semaphore, sleep
import asyncio
import json
import logging
import sqlite3
import time
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass
from solders.pubkey import Pubkey
from solders.signature import Signature
from solana.rpc.async_api import AsyncClient
import traceback
from cachetools import TTLCache
from collections import deque

logger = logging.getLogger('whale_detector')

# Configuration
HELIUS_WS_URL = "wss://rpc.helius.xyz/?api-key=872ddf73-4cfd-4263-a418-521bbde27eb8"
SOLANA_RPC_URL = "https://rpc.helius.xyz/?api-key=872ddf73-4cfd-4263-a418-521bbde27eb8"

# Seuils configurables
WHALE_THRESHOLD_USD = 1000  # Seuil minimum pour une transaction whale
CRITICAL_THRESHOLD_USD = 50000  # Seuil pour les transactions critiques

# Programmes Solana à surveiller
JUPITER_PROGRAM = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
RAYDIUM_PROGRAM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
PUMP_FUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

# Token SPL Program ID
TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"

@dataclass
class WhaleTransaction:
    """Structure pour une transaction whale"""
    signature: str
    token_address: str
    wallet_address: str
    transaction_type: str  # 'buy', 'sell', 'transfer'
    amount_usd: float
    amount_tokens: float
    timestamp: datetime
    price_impact: float
    is_known_whale: bool
    wallet_label: str
    is_in_database: bool
    dex_id: str = "unknown"

# === DEBUG WRAPPER FUNCTIONS ===
def safe_log_debug(msg: str, signature: str = ""):
    """Log debug avec gestion des erreurs"""
    try:
        logger.debug(f"🔍 {msg}")
    except Exception as e:
        print(f"LOG ERROR: {e} - Message: {msg}")

def safe_log_error(msg: str, exception: Exception = None, signature: str = ""):
    """Log error avec gestion des erreurs et stack trace"""
    try:
        if exception:
            logger.error(f"❌ {msg}: {str(exception)}")
            logger.error(f"📍 Stack trace: {traceback.format_exc()}")
        else:
            logger.error(f"❌ {msg}")
    except Exception as e:
        print(f"LOG ERROR: {e} - Message: {msg}")

class RateLimiter:
    """Enhanced rate limiter to prevent 429 errors."""
    def __init__(self, max_calls: int = 5, time_window: int = 1):
        self.max_calls = max_calls  # e.g., 5 calls per second
        self.time_window = time_window  # 1 second
        self.calls = []
        self.semaphore = Semaphore(max_calls)
        self.backoff_time = 0
        self.last_429_time = None

    async def acquire(self):
        """Acquire a permit, respecting rate limits and backoff."""
        now = time.time()

        # Apply backoff if recent 429 error
        if self.last_429_time and now - self.last_429_time < self.backoff_time:
            await sleep(self.backoff_time - (now - self.last_429_time))

        # Clean up old calls
        self.calls = [call_time for call_time in self.calls if now - call_time < self.time_window]
        
        # Wait if at limit
        if len(self.calls) >= self.max_calls:
            await sleep(self.time_window - (now - self.calls[0]))
            self.calls = self.calls[1:]  # Remove oldest call

        await self.semaphore.acquire()
        self.calls.append(now)

    def release(self):
        """Release the semaphore."""
        self.semaphore.release()

    def handle_429(self):
        """Handle a 429 error with exponential backoff."""
        self.last_429_time = time.time()
        self.backoff_time = min(self.backoff_time * 2 if self.backoff_time else 1, 60)  # Exponential backoff, max 60s
        safe_log_debug(f"429 detected, backing off for {self.backoff_time}s")

class WhaleWalletClassifier:
    """Classification des wallets whales"""
    
    def __init__(self):
        self.known_whales: set = set()  # Whales récurrents
        self.whale_activity: Dict[str, List[datetime]] = {}  # Historique d'activité
        self.wallet_labels: Dict[str, str] = {}
        
        # Wallets connus à filtrer
        self.spam_wallets = {
            "binance_hot": "2ojv9BAiHUrvsm9gxDe7fJSzbNZSJcxZvf8dqmWGHG8S",
            "coinbase_hot": "H8sMJSCQxfKiFTCfDR3DUMLPwcRbM61LGFJ8N4dK3WjS",
            "pump_fun_fee": "CebN5WGQ4jvEPvsVU4EoHEpgzq1VV7AbicfhtW4xC9iM",
        }
        
    def classify_wallet(self, wallet_address: str, transaction_amount: float) -> Dict[str, str]:
        """Classifier un wallet selon son activité"""
        
        # Vérifier si c'est un wallet système connu
        for label, address in self.spam_wallets.items():
            if wallet_address == address:
                return {
                    "type": "exchange",
                    "label": label.replace('_', ' ').title(),
                    "is_interesting": False
                }
        
        # Vérifier l'historique de ce wallet
        now = datetime.now()
        
        if wallet_address in self.whale_activity:
            recent_activity = [
                tx_time for tx_time in self.whale_activity[wallet_address]
                if now - tx_time < timedelta(days=7)
            ]
            
            if len(recent_activity) >= 3:
                self.known_whales.add(wallet_address)
                return {
                    "type": "recurring_whale",
                    "label": f"Whale récurrent ({len(recent_activity)} tx/7j)",
                    "is_interesting": True
                }
        
        # Nouveau wallet avec grosse transaction
        if transaction_amount >= CRITICAL_THRESHOLD_USD:
            return {
                "type": "new_whale",
                "label": f"Nouvelle whale (${transaction_amount:,.0f})",
                "is_interesting": True
            }
        elif transaction_amount >= WHALE_THRESHOLD_USD:
            return {
                "type": "whale",
                "label": f"Whale (${transaction_amount:,.0f})",
                "is_interesting": True
            }
        
        return {
            "type": "unknown",
            "label": "Wallet inconnu",
            "is_interesting": False
        }
    
    def record_whale_activity(self, wallet_address: str):
        """Enregistrer l'activité d'un wallet"""
        if wallet_address not in self.whale_activity:
            self.whale_activity[wallet_address] = []
        
        self.whale_activity[wallet_address].append(datetime.now())
        
        # Nettoyer l'historique ancien
        cutoff = datetime.now() - timedelta(days=30)
        self.whale_activity[wallet_address] = [
            tx_time for tx_time in self.whale_activity[wallet_address]
            if tx_time > cutoff
        ]

class WhaleTransactionDetector:
    """Détecteur de transactions whales intégré"""
    
    def __init__(self, database_path: str = "tokens.db", whale_threshold: int = WHALE_THRESHOLD_USD):
        self.database_path = database_path
        self.whale_threshold = whale_threshold  # Seuil configurable
        self.classifier = WhaleWalletClassifier()
        self.session: Optional[aiohttp.ClientSession] = None
        self.client: Optional[AsyncClient] = None
        self.is_running = False
        self.rate_limiter = RateLimiter(max_calls=8, time_window=60)  # 8 appels/minute max
        self.circuit_breaker_failures = 0
        self.circuit_breaker_reset_time = None
        self.last_429_time = None
        self.price_cache = TTLCache(maxsize=1000, ttl=300)  # Cache prices for 5 minutes
        self.signature_queue = deque(maxlen=100)  # Queue for batching signatures
        self.batch_interval = 2  # Process batch every 2 seconds
        self.debug_stats = {
            'total_processed': 0,
            'parse_errors': 0,
            'signature_errors': 0,
            'client_errors': 0,
            'instruction_errors': 0,
            'other_errors': 0
        }
        
        try:
            self.setup_database()
            logger.info(f"🐋 Whale detector initialized with threshold: ${self.whale_threshold:,}")
        except Exception as e:
            safe_log_error(f"Failed to initialize whale detector", e)
            
        logger.info(f"🐋 Whale detector initialized with threshold: ${self.whale_threshold:,}")
    

    # Fonction pour traiter les logs WebSocket et détecter les whales
    async def process_websocket_logs_for_whales(signature: str, logs: List[str]):
        """Traiter les logs WebSocket pour détecter l'activité whale - VERSION DEBUG"""
        if not self.is_running:
                safe_log_debug("Whale detector not running")
                return
        
        self.signature_queue.append((signature, logs))
            safe_log_debug(f"Queued signature {signature[:20]}... ({len(self.signature_queue)} in queue)")

            # Process batch if queue is full or after interval
            if len(self.signature_queue) >= 10:  # Adjust batch size as needed
                await self.process_signature_batch()

    async def process_signature_batch(self):
        """Process a batch of queued signatures."""
        while self.signature_queue:
            signature, logs = self.signature_queue.popleft()
            safe_log_debug(f"Processing batched signature {signature[:20]}...")
            whale_tx = await self.parse_transaction_for_whale_activity(signature, logs)
            safe_log_debug(f"Rate limit stats: {self.get_rate_limit_stats()}")
            if whale_tx:
                safe_log_debug(f"Whale transaction detected: ${whale_tx.amount_usd}")
                await self.process_whale_transaction(whale_tx)
        await sleep(self.batch_interval)  # Wait before next batch

    def setup_database(self):
        """Créer la table pour les transactions whales"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS whale_transactions_live (
                    signature TEXT PRIMARY KEY,
                    token_address TEXT,
                    wallet_address TEXT,
                    transaction_type TEXT,
                    amount_usd REAL,
                    amount_tokens REAL,
                    timestamp TIMESTAMP,
                    price_impact REAL,
                    is_known_whale BOOLEAN,
                    wallet_label TEXT,
                    is_in_database BOOLEAN,
                    dex_id TEXT DEFAULT 'unknown',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Index pour des requêtes rapides
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_whale_timestamp 
                ON whale_transactions_live(timestamp DESC)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_whale_token 
                ON whale_transactions_live(token_address, timestamp DESC)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_whale_amount 
                ON whale_transactions_live(amount_usd DESC)
            ''')
            
            conn.commit()
            logger.info("✅ Whale transactions database initialized")
            
        except sqlite3.Error as e:
            logger.error(f"Database setup error: {e}")
        finally:
            conn.close()
    
    async def start(self):
        """Démarrer le détecteur"""
        try:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
            self.client = AsyncClient(SOLANA_RPC_URL)
            self.is_running = True
            logger.info("🐋 Whale Transaction Detector started")
        except Exception as e:
            safe_log_error("Failed to start whale detector", e)
    
    async def stop(self):
        """Arrêter le détecteur"""
        self.is_running = False
        try:
            if self.session:
                await self.session.close()
            if self.client:
                await self.client.close()
            logger.info("🐋 Whale Transaction Detector stopped")
            
            # Afficher les stats de debug
            logger.info("📊 DEBUG STATS:")
            for key, value in self.debug_stats.items():
                logger.info(f"   {key}: {value}")
                
        except Exception as e:
            safe_log_error("Error stopping whale detector", e)
    
    async def get_token_price_estimate(self, token_address: str) -> float:
        """Estimer le prix d'un token via Jupiter ou DexScreener"""
        try:
            if token_address in self.price_cache:
                safe_log_debug(f"Price cache hit for {token_address[:8]}...")
                return self.price_cache[token_address]

            # Essayer Jupiter d'abord
            jupiter_url = f"https://quote-api.jup.ag/v6/quote?inputMint={token_address}&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=1000000&slippageBps=500"
            
            async with self.session.get(jupiter_url, timeout=5) as resp:
                async with self.session.get(jupiter_url, timeout=5) as resp:
                    if resp.status == 200:
                            data = await resp.json()
                            if "outAmount" in data:
                                price = int(data["outAmount"]) / 1e6
                                self.price_cache[token_address] = price
                                return price
                        elif resp.status == 429:
                            self.rate_limiter.handle_429()
                            return 0.0
            
            # Fallback sur DexScreener
            dex_url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            async with self.session.get(dex_url, timeout=5) as resp:
                async with self.session.get(dex_url, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("pairs"):
                            price = float(data["pairs"][0].get("priceUsd", 0))
                            self.price_cache[token_address] = price
                            return price
                    elif resp.status == 429:
                        self.rate_limiter.handle_429()
                        return 0.0
            
        except Exception as e:
            safe_log_error(f"Error getting price for {token_address[:8]}: {str(e)}", e)
            return 0.0
        
        return 0.0
    
    async def check_token_in_database(self, token_address: str) -> bool:
        """Vérifier si un token est dans notre base"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                "SELECT 1 FROM tokens WHERE address = ? LIMIT 1",
                (token_address,)
            )
            return cursor.fetchone() is not None
        except sqlite3.Error:
            return False
        finally:
            conn.close()
    
    async def parse_transaction_for_whale_activity(self, signature: str, logs: List[str]) -> Optional[WhaleTransaction]:
        """Parse a transaction to detect whale activity."""
        self.debug_stats['total_processed'] += 1

        # Circuit breaker - skip if too many recent failures
        if self.circuit_breaker_failures > 5:
            if self.circuit_breaker_reset_time and time.time() < self.circuit_breaker_reset_time:
                safe_log_debug(f"Circuit breaker active, skipping {signature[:20]}...")
                return None
            else:
                # Reset circuit breaker
                self.circuit_breaker_failures = 0
                self.circuit_breaker_reset_time = None

        # Rate limiting for recent 429 errors
        if self.last_429_time and time.time() - self.last_429_time < self.rate_limiter.backoff_time:
            safe_log_debug(f"Rate limit backoff active, skipping {signature[:20]}...")
            return None

        try:
            safe_log_debug(f"DÉBUT parsing transaction: {signature[:20]}...", signature)

            # Validate signature and logs
            if not signature or len(signature) < 20:
                safe_log_error(f"Invalid signature: '{signature}'")
                self.debug_stats['signature_errors'] += 1
                return None

            if not logs:
                safe_log_debug(f"No logs for {signature[:20]}...", signature)
                return None

            # Check for swap indicators in logs
            safe_log_debug(f"Analyzing {len(logs)} logs...", signature)
            has_indicators = self.contains_large_swap_indicators(logs)
            safe_log_debug(f"Swap indicators detected: {has_indicators}", signature)

            if not has_indicators:
                safe_log_debug(f"STOP: No swap indicators for {signature[:20]}...", signature)
                return None

            # Create signature object
            safe_log_debug(f"Creating signature object...", signature)
            try:
                sig = Signature.from_string(signature)
                safe_log_debug(f"Signature created successfully", signature)
            except Exception as sig_error:
                safe_log_error(f"Error creating signature: {str(sig_error)}", sig_error, signature)
                self.debug_stats['signature_errors'] += 1
                return None

            # Fetch transaction with rate limiting
            safe_log_debug(f"Fetching transaction via RPC...", signature)
            if not self.client:
                safe_log_error(f"RPC client not initialized", signature=signature)
                self.debug_stats['client_errors'] += 1
                return None

            await self.rate_limiter.acquire()
            try:
                tx = await self.client.get_transaction(
                    sig,
                    commitment="finalized",
                    max_supported_transaction_version=0
                )
                safe_log_debug(f"Transaction fetched: {tx is not None}", signature)
                # Reset circuit breaker on success
                if self.circuit_breaker_failures > 0:
                    self.circuit_breaker_failures = 0
                    self.circuit_breaker_reset_time = None
                    safe_log_debug("Circuit breaker reset - connection OK")
            except Exception as client_error:
                error_str = str(client_error)
                if "429" in error_str or "Too Many Requests" in error_str:
                    self.last_429_time = time.time()
                    self.circuit_breaker_failures += 1
                    self.rate_limiter.handle_429()
                    safe_log_error(f"Rate limit 429 - activation backoff", client_error, signature)
                    return None
                else:
                    safe_log_error(f"Error fetching transaction: {error_str}", client_error, signature)
                    self.circuit_breaker_failures += 1
                    self.debug_stats['client_errors'] += 1
                    return None
            finally:
                self.rate_limiter.release()

            if not tx.value or not tx.value.transaction:
                safe_log_debug(f"Empty transaction (tx={tx is not None})", signature)
                return None

            if not tx.value.transaction.meta:
                safe_log_debug(f"No transaction meta data", signature)
                return None

            safe_log_debug(f"Valid transaction fetched", signature)

            # Analyze instructions
            try:
                message = tx.value.transaction.transaction.message
                safe_log_debug(f"Analyzing {len(message.instructions)} instructions...", signature)

                for i, instruction in enumerate(message.instructions):
                    try:
                        if instruction.program_id_index >= len(message.account_keys):
                            safe_log_debug(f"Invalid program index: {instruction.program_id_index} >= {len(message.account_keys)}", signature)
                            continue

                        program_id = str(message.account_keys[instruction.program_id_index])
                        safe_log_debug(f"Instruction {i}: Program {program_id[:8]}...", signature)

                        # Process DEX program instructions
                        if program_id in [JUPITER_PROGRAM, RAYDIUM_PROGRAM, PUMP_FUN_PROGRAM]:
                            safe_log_debug(f"DEX PROGRAM FOUND: {program_id[:8]}...", signature)
                            whale_data = await self.extract_whale_data_from_instruction(instruction, message, signature, program_id)
                            safe_log_debug(f"Whale data extracted: {whale_data is not None}", signature)

                            if whale_data:
                                safe_log_debug(f"USD amount: {whale_data.get('amount_usd', 0)}", signature)
                                if self.is_significant_transaction(whale_data):
                                    safe_log_debug(f"SIGNIFICANT TRANSACTION!", signature)
                                    whale_tx = await self.create_whale_transaction(whale_data)
                                    if whale_tx:
                                        return whale_tx
                                else:
                                    safe_log_debug(f"Transaction not significant enough", signature)

                    except Exception as instruction_error:
                        safe_log_error(f"Error processing instruction {i}: {str(instruction_error)}", instruction_error, signature)
                        self.debug_stats['instruction_errors'] += 1
                        continue

                safe_log_debug(f"NO WHALE FOUND for {signature[:20]}...", signature)

            except Exception as message_error:
                safe_log_error(f"Error analyzing message: {str(message_error)}", message_error, signature)
                self.debug_stats['instruction_errors'] += 1
                return None

        except Exception as e:
            safe_log_error(f"GLOBAL ERROR parsing transaction {signature[:20]}...: {str(e)}", e, signature)
            self.debug_stats['other_errors'] += 1
            return None

        return None

    def get_rate_limit_stats(self) -> Dict:
        """Obtenir les stats du rate limiter"""
        return {
            'circuit_breaker_failures': self.circuit_breaker_failures,
            'last_429_ago_seconds': int(time.time() - self.last_429_time) if self.last_429_time else None,
            'circuit_breaker_reset_in': int(self.circuit_breaker_reset_time - time.time()) if self.circuit_breaker_reset_time else None,
            'rate_limit_calls_recent': len(self.rate_limiter.calls)
        }

    def contains_large_swap_indicators(self, logs: List[str]) -> bool:
        """Check if logs indicate a large swap."""
        try:
            safe_log_debug(f"Checking indicators in {len(logs)} logs...")
            
            for i, log in enumerate(logs):
                log_lower = log.lower()
                
                indicators = [
                    ("jupiter" and "swap", "JUPITER SWAP"),
                    ("raydium" and "swap", "RAYDIUM SWAP"),
                    ("pump" and ("buy" or "sell"), "PUMP.FUN TRADE"),
                    ("transfer" and "token", "TOKEN TRANSFER"),
                ]
                
                for condition, label in indicators:
                    if all(keyword in log_lower for keyword in condition.split()):
                    # Check for amount indicators in logs (e.g., SOL or USD)
                    import re
                    sol_pattern = r'(\d+\.?\d*)\s*sol'
                    usd_pattern = r'\$(\d+\.?\d*)'
                    sol_match = re.search(sol_pattern, log_lower)
                    usd_match = re.search(usd_pattern, log_lower)
                    
                    if sol_match or usd_match:
                        amount = float(sol_match.group(1)) * 200 if sol_match else float(usd_match.group(1)) if usd_match else 0
                        if amount < self.whale_threshold / 200:  # Convert USD threshold to SOL estimate
                            safe_log_debug(f"Skipping small transaction: ${amount*200:.0f}")
                            return False
                    safe_log_debug(f"✅ Indicator {label} found in log {i}: {log[:80]}...")
                    return True
            
            safe_log_debug("❌ No swap indicators found")
            return False
        
        except Exception as e:
            safe_log_error(f"Error in contains_large_swap_indicators: {str(e)}", e)
            return False
    
    def is_significant_transaction(self, tx_data: Dict) -> bool:
        """Vérifier si une transaction est significative - VERSION DEBUG"""
        try:
            amount_usd = tx_data.get('amount_usd', 0)
            wallet = tx_data.get('wallet_address', '')
            
            safe_log_debug(f"Test significatif: ${amount_usd} vs seuil ${self.whale_threshold}")
            
            # Filtrer par montant minimum
            if amount_usd < self.whale_threshold:
                safe_log_debug(f"Montant insuffisant: ${amount_usd} < ${self.whale_threshold}")
                return False
            
            # Filtrer les wallets spam
            if wallet in self.classifier.spam_wallets.values():
                safe_log_debug(f"Wallet spam détecté: {wallet[:8]}...")
                return False
            
            safe_log_debug(f"Transaction significative: ${amount_usd}")
            return True
            
        except Exception as e:
            safe_log_error(f"Erreur is_significant_transaction: {str(e)}", e)
            return False
    
    async def extract_whale_data_from_instruction_debug(self, instruction, message, signature: str, program_id: str) -> Optional[Dict]:
        """Version debug de extract_whale_data_from_instruction"""
        try:
            safe_log_debug(f"Extraction données pour programme: {program_id[:8]}...")
            
            # === ÉTAPE 1: Extraction des comptes ===
            try:
                accounts = []
                safe_log_debug(f"Traitement de {len(instruction.accounts)} indices de comptes...")
                
                for idx in instruction.accounts:
                    if idx < len(message.account_keys):
                        account = str(message.account_keys[idx])
                        accounts.append(account)
                        safe_log_debug(f"Compte {len(accounts)}: {account[:8]}...")
                    else:
                        safe_log_debug(f"Index {idx} dépasse {len(message.account_keys)} comptes")
                
                safe_log_debug(f"{len(accounts)} comptes valides récupérés")
                
                if not accounts:
                    safe_log_debug("Aucun compte valide trouvé")
                    return None
                
            except Exception as account_error:
                safe_log_error(f"Erreur extraction comptes: {str(account_error)}", account_error, signature)
                return None
            
            # === ÉTAPE 2: Identification du wallet utilisateur ===
            try:
                # Filtrer les comptes système
                system_accounts = {
                    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                    "11111111111111111111111111111111",
                    "ComputeBudget111111111111111111111111111111",
                    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
                    program_id
                }
                
                user_wallet = None
                for account in accounts:
                    if account not in system_accounts and not account.startswith("11111"):
                        user_wallet = account
                        safe_log_debug(f"User wallet trouvé: {user_wallet[:8]}...")
                        break
                
                if not user_wallet and accounts:
                    user_wallet = accounts[0]  # Fallback
                    safe_log_debug(f"Fallback wallet: {user_wallet[:8]}...")
                
                if not user_wallet:
                    safe_log_debug("Aucun wallet utilisateur trouvé")
                    return None
                    
            except Exception as wallet_error:
                safe_log_error(f"Erreur identification wallet: {str(wallet_error)}", wallet_error, signature)
                return None
            
            # === ÉTAPE 3: Parsing spécifique au programme ===
            try:
                if program_id == JUPITER_PROGRAM:
                    safe_log_debug("🪐 APPEL parse_jupiter_instruction...")
                    #result = await self.parse_jupiter_instruction_debug([user_wallet] + accounts, instruction, signature)
                    result = await self.parse_jupiter_instruction([user_wallet] + accounts, instruction, signature)
                elif program_id == RAYDIUM_PROGRAM:
                    safe_log_debug("🌊 APPEL parse_raydium_instruction...")
                    #result = await self.parse_raydium_instruction_debug([user_wallet] + accounts, instruction, signature)
                    result = await self.parse_raydium_instruction([user_wallet] + accounts, instruction, signature)
                elif program_id == PUMP_FUN_PROGRAM:
                    safe_log_debug("🚀 APPEL parse_pump_fun_instruction...")
                    #result = await self.parse_pump_fun_instruction_debug([user_wallet] + accounts, instruction, signature)
                    result = await self.parse_pump_fun_instruction([user_wallet] + accounts, instruction, signature)
                else:
                    safe_log_debug(f"Programme non géré: {program_id}")
                    return None
                
                safe_log_debug(f"Résultat parsing: {result is not None}")
                if result:
                    safe_log_debug(f"Montant: ${result.get('amount_usd', 0)}")
                
                return result
                
            except Exception as parse_error:
                safe_log_error(f"Erreur parsing programme {program_id[:8]}: {str(parse_error)}", parse_error, signature)
                return None
                
        except Exception as e:
            safe_log_error(f"Erreur globale extraction whale data: {str(e)}", e, signature)
            return None
    
    async def parse_jupiter_instruction(self, accounts: List[str], instruction, signature: str) -> Optional[Dict]:
        """Parse a Jupiter instruction to extract whale transaction data."""
        try:
            safe_log_debug(f"🪐 Parsing Jupiter instruction: {signature[:20]}...")

            if len(accounts) < 2:
                safe_log_debug(f"🪐 Not enough accounts: {len(accounts)}")
                return None

            user_wallet = accounts[0]
            safe_log_debug(f"🪐 User wallet: {user_wallet[:8]}...")

            # Fetch transaction details to get token balances
            sig = Signature.from_string(signature)
            tx = await self.client.get_transaction(
                sig,
                commitment="finalized",
                max_supported_transaction_version=0
            )

            if not tx.value or not tx.value.transaction:
                safe_log_debug(f"🪐 No transaction data for {signature[:20]}...")
                return None

            # Analyze token balance changes
            pre_balances = tx.value.transaction.meta.pre_token_balances
            post_balances = tx.value.transaction.meta.post_token_balances
            balance_changes = self.analyze_token_balance_changes(pre_balances, post_balances, user_wallet)

            if not balance_changes:
                safe_log_debug(f"🪐 No significant balance changes for {signature[:20]}...")
                return None

            # Assume the first significant change is the primary swap
            primary_change = balance_changes[0]
            token_address = primary_change['mint']
            amount_tokens = abs(primary_change['amount_change'])

            # Estimate USD value using token price
            price_usd = await self.get_token_price_estimate(token_address)
            amount_usd = amount_tokens * price_usd if price_usd else 0

            # Determine transaction type (buy or sell)
            transaction_type = 'buy' if primary_change['amount_change'] > 0 else 'sell'

            safe_log_debug(f"🪐 Parsed: {transaction_type} {amount_tokens:.2f} tokens (${amount_usd:.2f})")

            return {
                'wallet_address': user_wallet,
                'token_address': token_address,
                'transaction_type': transaction_type,
                'signature': signature,
                'dex_id': 'jupiter',
                'amount_tokens': amount_tokens,
                'amount_usd': amount_usd,
            }

        except Exception as e:
            safe_log_error(f"🪐 Error parsing Jupiter instruction: {str(e)}", e, signature)
            return None

    async def parse_jupiter_instruction_debug(self, accounts: List[str], instruction, signature: str) -> Optional[Dict]:
        """Version debug de parse_jupiter_instruction"""
        try:
            safe_log_debug(f"🪐 Jupiter: {len(accounts)} comptes disponibles")
            
            if len(accounts) < 1:
                safe_log_debug(f"Pas assez de comptes Jupiter: {len(accounts)}")
                return None
            
            user_wallet = accounts[0]
            safe_log_debug(f"🪐 User wallet: {user_wallet[:8]}...")
            
            # Pour le debug, créer une transaction factice mais significative
            return {
                'wallet_address': user_wallet,
                'token_address': "So11111111111111111111111111111111111111112",  # SOL
                'transaction_type': 'swap',
                'signature': signature,
                'dex_id': 'jupiter',
                'amount_tokens': 5.0,
                'amount_usd': 1200.0,  # Au-dessus du seuil pour test
            }
            
        except Exception as e:
            safe_log_error(f"Erreur parsing Jupiter debug: {str(e)}", e, signature)
            return None
    
    async def parse_raydium_instruction_debug(self, accounts: List[str], instruction, signature: str) -> Optional[Dict]:
        """Version debug de parse_raydium_instruction"""
        try:
            safe_log_debug(f"🌊 Raydium: {len(accounts)} comptes disponibles")
            
            if len(accounts) < 1:
                safe_log_debug(f"Pas assez de comptes Raydium: {len(accounts)}")
                return None
            
            user_wallet = accounts[0]
            safe_log_debug(f"🌊 User wallet: {user_wallet[:8]}...")
            
            return {
                'wallet_address': user_wallet,
                'token_address': "So11111111111111111111111111111111111111112",
                'transaction_type': 'swap',
                'signature': signature,
                'dex_id': 'raydium',
                'amount_tokens': 3.0,
                'amount_usd': 800.0,
            }
            
        except Exception as e:
            safe_log_error(f"Erreur parsing Raydium debug: {str(e)}", e, signature)
            return None
    
    async def parse_raydium_instruction(self, accounts: List[str], instruction, signature: str) -> Optional[Dict]:
        """Parse a Raydium instruction to extract whale transaction data."""
        try:
            safe_log_debug(f"🌊 Parsing Raydium instruction: {signature[:20]}...")

            if len(accounts) < 5:  # Raydium swaps typically involve multiple accounts (user, pool, token accounts)
                safe_log_debug(f"🌊 Not enough accounts: {len(accounts)}")
                return None

            user_wallet = accounts[0]
            safe_log_debug(f"🌊 User wallet: {user_wallet[:8]}...")

            # Fetch transaction details
            sig = Signature.from_string(signature)
            tx = await self.client.get_transaction(
                sig,
                commitment="finalized",
                max_supported_transaction_version=0
            )

            if not tx.value or not tx.value.transaction:
                safe_log_debug(f"🌊 No transaction data for {signature[:20]}...")
                return None

            # Check logs for Raydium swap confirmation
            log_messages = tx.value.transaction.meta.log_messages or []
            is_swap = any("swap" in log.lower() for log in log_messages)
            if not is_swap:
                safe_log_debug(f"🌊 No swap event in logs for {signature[:20]}...")
                return None

            # Analyze token balance changes
            pre_balances = tx.value.transaction.meta.pre_token_balances
            post_balances = tx.value.transaction.meta.post_token_balances
            balance_changes = self.analyze_token_balance_changes(pre_balances, post_balances, user_wallet)

            if not balance_changes:
                safe_log_debug(f"🌊 No significant balance changes for {signature[:20]}...")
                return None

            # Identify primary token swap (assume largest absolute change)
            primary_change = max(balance_changes, key=lambda x: abs(x['amount_change']), default=None)
            if not primary_change:
                safe_log_debug(f"🌊 No primary balance change identified")
                return None

            token_address = primary_change['mint']
            amount_tokens = abs(primary_change['amount_change'])
            transaction_type = 'buy' if primary_change['amount_change'] > 0 else 'sell'

            # Estimate USD value
            price_usd = await self.get_token_price_estimate(token_address)
            if price_usd == 0.0:
                safe_log_debug(f"🌊 Failed to get price for token {token_address[:8]}...")
                return None
            amount_usd = amount_tokens * price_usd

            safe_log_debug(f"🌊 Parsed: {transaction_type} {amount_tokens:.2f} tokens (${amount_usd:.2f}) of {token_address[:8]}...")

            return {
                'wallet_address': user_wallet,
                'token_address': token_address,
                'transaction_type': transaction_type,
                'signature': signature,
                'dex_id': 'raydium',
                'amount_tokens': amount_tokens,
                'amount_usd': amount_usd,
            }

        except Exception as e:
            safe_log_error(f"🌊 Error parsing Raydium instruction: {str(e)}", e, signature)
            return None
            
    async def parse_pump_fun_instruction(self, accounts: List[str], instruction, signature: str) -> Optional[Dict]:
        """Parse a Pump.fun instruction to extract whale transaction data."""
        try:
            safe_log_debug(f"🚀 Parsing Pump.fun instruction: {signature[:20]}...")

            if len(accounts) < 2:  # Pump.fun trades typically involve user and token accounts
                safe_log_debug(f"🚀 Not enough accounts: {len(accounts)}")
                return None

            user_wallet = accounts[0]
            safe_log_debug(f"🚀 User wallet: {user_wallet[:8]}...")

            # Fetch transaction details
            sig = Signature.from_string(signature)
            tx = await self.client.get_transaction(
                sig,
                commitment="finalized",
                max_supported_transaction_version=0
            )

            if not tx.value or not tx.value.transaction:
                safe_log_debug(f"🚀 No transaction data for {signature[:20]}...")
                return None

            # Parse logs for trade details
            log_messages = tx.value.transaction.meta.log_messages or []
            trade_data = self.parse_pump_fun_logs(log_messages)
            if not trade_data:
                safe_log_debug(f"🚀 No trade data in logs for {signature[:20]}...")
                return None

            # Analyze token balance changes
            pre_balances = tx.value.transaction.meta.pre_token_balances
            post_balances = tx.value.transaction.meta.post_token_balances
            balance_changes = self.analyze_token_balance_changes(pre_balances, post_balances, user_wallet)

            if not balance_changes:
                safe_log_debug(f"🚀 No significant balance changes for {signature[:20]}...")
                return None

            # Identify primary token swap
            primary_change = max(balance_changes, key=lambda x: abs(x['amount_change']), default=None)
            if not primary_change:
                safe_log_debug(f"🚀 No primary balance change identified")
                return None

            token_address = primary_change['mint']
            amount_tokens = abs(primary_change['amount_change'])
            transaction_type = trade_data.get('transaction_type', 'buy' if primary_change['amount_change'] > 0 else 'sell')

            # Use USD amount from logs if available, otherwise estimate
            amount_usd = trade_data.get('amount_usd', 0)
            if amount_usd == 0:
                price_usd = await self.get_token_price_estimate(token_address)
                if price_usd == 0.0:
                    safe_log_debug(f"🚀 Failed to get price for token {token_address[:8]}...")
                    return None
                amount_usd = amount_tokens * price_usd

            safe_log_debug(f"🚀 Parsed: {transaction_type} {amount_tokens:.2f} tokens (${amount_usd:.2f}) of {token_address[:8]}...")

            return {
                'wallet_address': user_wallet,
                'token_address': token_address,
                'transaction_type': transaction_type,
                'signature': signature,
                'dex_id': 'pump_fun',
                'amount_tokens': amount_tokens,
                'amount_usd': amount_usd,
            }

        except Exception as e:
            safe_log_error(f"🚀 Error parsing Pump.fun instruction: {str(e)}", e, signature)
            return None

    async def parse_pump_fun_instruction_debug(self, accounts: List[str], instruction, signature: str) -> Optional[Dict]:
        """Version debug de parse_pump_fun_instruction"""
        try:
            safe_log_debug(f"🚀 Pump.fun: {len(accounts)} comptes disponibles")
            
            if len(accounts) < 1:
                safe_log_debug(f"Pas assez de comptes Pump.fun: {len(accounts)}")
                return None
            
            user_wallet = accounts[0]
            safe_log_debug(f"🚀 User wallet: {user_wallet[:8]}...")
            
            return {
                'wallet_address': user_wallet,
                'token_address': "So11111111111111111111111111111111111111112",
                'transaction_type': 'buy',
                'signature': signature,
                'dex_id': 'pump_fun',
                'amount_tokens': 1000.0,
                'amount_usd': 500.0,
            }
            
        except Exception as e:
            safe_log_error(f"Erreur parsing Pump.fun debug: {str(e)}", e, signature)
            return None
    
    async def create_whale_transaction(self, whale_data: Dict) -> WhaleTransaction:
        """Créer un objet WhaleTransaction - VERSION DEBUG"""
        try:
            safe_log_debug(f"Création WhaleTransaction: ${whale_data.get('amount_usd', 0)}")
            
            # Classification simple pour le debug
            wallet_classification = {
                'label': f"Test Whale (${whale_data.get('amount_usd', 0):,.0f})",
                'is_interesting': True
            }
            
            return WhaleTransaction(
                signature=whale_data['signature'],
                token_address=whale_data['token_address'],
                wallet_address=whale_data['wallet_address'],
                transaction_type=whale_data['transaction_type'],
                amount_usd=whale_data['amount_usd'],
                amount_tokens=whale_data.get('amount_tokens', 0),
                timestamp=datetime.now(),
                price_impact=whale_data.get('price_impact', 0),
                is_known_whale=False,
                wallet_label=wallet_classification['label'],
                is_in_database=False,
                dex_id=whale_data.get('dex_id', 'unknown')
            )
            
        except Exception as e:
            safe_log_error(f"Erreur création whale transaction: {str(e)}", e)
            return None

    

    def analyze_token_balance_changes(self, pre_balances, post_balances, user_wallet: str) -> List[Dict]:
        """Analyser les changements de balance de tokens pour un wallet"""
        changes = []
        
        try:
            # Créer des dictionnaires pour un accès rapide
            pre_dict = {}
            post_dict = {}
            
            # Traiter les balances pré-transaction
            if pre_balances:
                for balance in pre_balances:
                    if hasattr(balance, 'owner') and str(balance.owner) == user_wallet:
                        key = (str(balance.mint), str(balance.owner))
                        pre_dict[key] = float(balance.ui_token_amount.ui_amount or 0)
            
            # Traiter les balances post-transaction
            if post_balances:
                for balance in post_balances:
                    if hasattr(balance, 'owner') and str(balance.owner) == user_wallet:
                        key = (str(balance.mint), str(balance.owner))
                        post_dict[key] = float(balance.ui_token_amount.ui_amount or 0)
            
            # Calculer les changements
            all_keys = set(pre_dict.keys()) | set(post_dict.keys())
            
            for key in all_keys:
                mint, owner = key
                pre_amount = pre_dict.get(key, 0)
                post_amount = post_dict.get(key, 0)
                change = post_amount - pre_amount
                
                if abs(change) > 0.001:  # Seuil minimal pour éviter les micro-changements
                    changes.append({
                        'mint': mint,
                        'owner': owner,
                        'pre_amount': pre_amount,
                        'post_amount': post_amount,
                        'amount_change': change
                    })
            
            logger.debug(f"📊 Analysé {len(changes)} changements de balance significatifs")
            
        except Exception as e:
            logger.error(f"❌ Erreur analyse token balances: {e}")
        
        return changes
    
    def parse_pump_fun_logs(self, log_messages: List[str]) -> Optional[Dict]:
        """Parser les logs Pump.fun pour extraire les données de trade"""
        try:
            for log in log_messages:
                log_lower = log.lower()
                
                # Rechercher les patterns Pump.fun dans les logs
                if "pump" in log_lower and any(keyword in log_lower for keyword in ["buy", "sell", "trade"]):
                    # Essayer d'extraire les montants des logs
                    # Les logs Pump.fun contiennent souvent des informations structurées
                    
                    # Pattern pour extraire les montants (exemple simplifié)
                    import re
                    
                    # Rechercher des montants en SOL ou USD
                    sol_pattern = r'(\d+\.?\d*)\s*sol'
                    usd_pattern = r'\$(\d+\.?\d*)'
                    token_pattern = r'(\d+\.?\d*)\s*token'
                    
                    sol_match = re.search(sol_pattern, log_lower)
                    usd_match = re.search(usd_pattern, log_lower)
                    token_match = re.search(token_pattern, log_lower)
                    
                    if sol_match or usd_match:
                        sol_amount = float(sol_match.group(1)) if sol_match else 0
                        usd_amount = float(usd_match.group(1)) if usd_match else sol_amount * 200  # Estimation SOL price
                        token_amount = float(token_match.group(1)) if token_match else 0
                        
                        # Déterminer le type de transaction
                        tx_type = 'buy' if 'buy' in log_lower else 'sell'
                        
                        logger.debug(f"🚀 Pump.fun log parsed: {tx_type} ${usd_amount}")
                        
                        return {
                            'transaction_type': tx_type,
                            'amount_usd': usd_amount,
                            'amount_tokens': token_amount,
                            'sol_amount': sol_amount
                        }
        
        except Exception as e:
            logger.error(f"❌ Erreur parsing Pump.fun logs: {e}")
        
        return None
    
    
    
    async def save_whale_transaction(self, whale_tx: WhaleTransaction):
        """Sauvegarder une transaction whale dans la base"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO whale_transactions_live (
                    signature, token_address, wallet_address, transaction_type,
                    amount_usd, amount_tokens, timestamp, price_impact,
                    is_known_whale, wallet_label, is_in_database, dex_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                whale_tx.signature, whale_tx.token_address, whale_tx.wallet_address,
                whale_tx.transaction_type, whale_tx.amount_usd, whale_tx.amount_tokens,
                whale_tx.timestamp, whale_tx.price_impact, whale_tx.is_known_whale,
                whale_tx.wallet_label, whale_tx.is_in_database, whale_tx.dex_id
            ))
            
            conn.commit()
            logger.info(f"💾 Saved whale transaction: ${whale_tx.amount_usd:,.0f} {whale_tx.transaction_type}")
            
        except sqlite3.Error as e:
            logger.error(f"Error saving whale transaction: {e}")
        finally:
            conn.close()
    
    async def process_whale_transaction(self, whale_tx: WhaleTransaction):
        """Traiter une transaction whale selon sa nature"""
        
        # Sauvegarder la transaction
        await self.save_whale_transaction(whale_tx)
        
        if whale_tx.is_in_database:
            logger.debug(f"📈 Whale activity on tracked token: {whale_tx.token_address}")
        else:
            logger.info(f"📊 New whale activity: {whale_tx.token_address}")
            
            # Si transaction critique, considérer l'ajout du token
            if whale_tx.amount_usd >= CRITICAL_THRESHOLD_USD:
                await self.queue_token_for_discovery(whale_tx.token_address)
                logger.debug(f"🎯 Queued critical token for discovery: {whale_tx.token_address}")
    
    async def queue_token_for_discovery(self, token_address: str):
        """Ajouter un token à la queue de découverte automatique"""
        try:
            # Intégrer avec le système d'enrichissement existant
            from solana_monitor_c4 import token_enricher
            await token_enricher.queue_for_enrichment(token_address)
            logger.debug(f"🔍 Token queued for enrichment: {token_address}")
        except Exception as e:
            logger.error(f"Error queuing token for discovery: {e}")

whale_detector = WhaleTransactionDetector()

# API pour récupérer les données whale
class WhaleActivityAPI:
    """API pour récupérer les données d'activité whale"""
    
    def __init__(self, database_path: str = "tokens.db", whale_threshold: int = 10000):
        self.database_path = database_path
        self.whale_threshold = whale_threshold  # Seuil configurable
    
    def get_token_info_for_whale(self, token_address: str) -> Dict:
        """Récupérer les infos du token pour l'affichage whale"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT symbol, name, bonding_curve_status 
                FROM tokens 
                WHERE address = ?
            ''', (token_address,))
            
            result = cursor.fetchone()
            if result:
                return {
                    'symbol': result[0] or 'UNKNOWN',
                    'name': result[1] or 'Unknown Token',
                    'status': result[2] or 'unknown'
                }
            else:
                return {
                    'symbol': 'NEW',
                    'name': 'New Token',
                    'status': 'new'
                }
        except sqlite3.Error:
            return {
                'symbol': 'ERROR',
                'name': 'Error Token',
                'status': 'error'
            }
        finally:
            conn.close()

    def get_recent_whale_activity(self, hours: int = 1, limit: int = 50) -> List[Dict]:
        """Récupérer l'activité whale récente"""
        
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT w.*, t.symbol, t.name, t.bonding_curve_status
                FROM whale_transactions_live w
                LEFT JOIN tokens t ON w.token_address = t.address
                WHERE w.timestamp > datetime('now', '-{} hours', 'localtime')
                ORDER BY w.timestamp DESC, w.amount_usd DESC
                LIMIT ?
            '''.format(hours), (limit,))
            
            columns = [desc[0] for desc in cursor.description]
            results = []
            
            for row in cursor.fetchall():
                whale_data = dict(zip(columns, row))
            
                # Enrichir avec infos formatées
                whale_data.update({
                    'token_symbol': whale_data.get('symbol') or 'NEW',
                    'token_name': whale_data.get('name') or 'New Token',
                    'token_status': whale_data.get('bonding_curve_status') or 'new',
                    'timestamp_formatted': self.format_whale_timestamp(whale_data['timestamp']),
                    'amount_formatted': self.format_whale_amount(whale_data['amount_usd']),
                    'dexscreener_url': f"https://dexscreener.com/solana/{whale_data['token_address']}",
                    'pump_fun_url': f"https://pump.fun/coin/{whale_data['token_address']}",
                    'token_short': whale_data['token_address'][:8] + '...' + whale_data['token_address'][-4:],
                    'token_full': whale_data['token_address']
                })

                results.append(whale_data)
            
            return results
            
        except sqlite3.Error as e:
            logger.error(f"Error getting whale activity: {e}")
            return []
        finally:
            conn.close()
    
    def format_whale_timestamp(self, timestamp_str: str) -> str:
        """Formater le timestamp pour l'affichage whale"""
        try:
            if isinstance(timestamp_str, str):
                dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            else:
                dt = timestamp_str
            
            return dt.strftime('%d/%m %H:%M:%S')
        except:
            return 'Invalid date'

    def format_whale_amount(self, amount_usd: float) -> str:
        """Formater le montant whale de manière lisible"""
        if amount_usd >= 1_000_000:
            return f"${amount_usd/1_000_000:.1f}M"
        elif amount_usd >= 100_000:
            return f"${amount_usd/1_000:.0f}K"
        elif amount_usd >= 10_000:
            return f"${amount_usd/1_000:.1f}K"
        elif amount_usd >= 1_000:
            return f"${amount_usd:,.0f}"
        else:
            return f"${amount_usd:.0f}"

    def get_whale_activity_for_token(self, token_address: str, hours: int = 24) -> List[Dict]:
        """Récupérer l'activité whale pour un token spécifique"""
        
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT * FROM whale_transactions_live 
                WHERE token_address = ? 
                AND timestamp > datetime('now', '-{} hours', 'localtime')
                ORDER BY timestamp DESC
            '''.format(hours), (token_address,))
            
            columns = [desc[0] for desc in cursor.description]
            results = []
            
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            
            return results
            
        except sqlite3.Error as e:
            logger.error(f"Error getting token whale activity: {e}")
            return []
        finally:
            conn.close()
    
    def get_whale_activity_summary(self) -> Dict:
        """Récupérer un résumé de l'activité whale"""
        
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            # Activité dernière heure
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_transactions,
                    SUM(amount_usd) as total_volume,
                    AVG(amount_usd) as avg_transaction,
                    COUNT(DISTINCT token_address) as unique_tokens,
                    COUNT(DISTINCT wallet_address) as unique_wallets
                FROM whale_transactions_live 
                WHERE timestamp > datetime('now', '-1 hour', 'localtime')
            ''')
            
            row = cursor.fetchone()
            
            return {
                'total_transactions': row[0] or 0,
                'total_volume_usd': row[1] or 0,
                'avg_transaction_usd': row[2] or 0,
                'unique_tokens': row[3] or 0,
                'unique_wallets': row[4] or 0,
                'period': '1 hour'
            }
            
        except sqlite3.Error as e:
            logger.error(f"Error getting whale summary: {e}")
            return {}
        finally:
            conn.close()

# Instance globale du détecteur whale
whale_detector = WhaleTransactionDetector()
whale_api = WhaleActivityAPI()

async def start_whale_monitoring():
    """Démarrer le monitoring des transactions whales"""
    logger.info("🐋 Starting Whale Transaction Monitoring System")
    asyncio.create_task(self.batch_processing_loop())

async def stop_whale_monitoring():
    """Arrêter le monitoring des transactions whales"""
    await whale_detector.stop()

async def batch_processing_loop(self):
    """Background loop for batch processing."""
    while self.is_running:
        await self.process_signature_batch()

def get_rate_limit_stats(self) -> Dict:
    """Get enhanced rate limiter stats."""
    return {
        'circuit_breaker_failures': self.circuit_breaker_failures,
        'last_429_ago_seconds': int(time.time() - self.last_429_time) if self.last_429_time else None,
        'circuit_breaker_reset_in': int(self.circuit_breaker_reset_time - time.time()) if self.circuit_breaker_reset_time else None,
        'rate_limit_calls_recent': len(self.rate_limiter.calls),
        'current_backoff_time': self.rate_limiter.backoff_time,
        'queue_size': len(self.signature_queue) if hasattr(self, 'signature_queue') else 0
    }