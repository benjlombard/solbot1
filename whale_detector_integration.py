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
import httpx

logger = logging.getLogger('whale_detector')

# Configuration
HELIUS_WS_URL = "wss://rpc.helius.xyz/?api-key=872ddf73-4cfd-4263-a418-521bbde27eb8"
SOLANA_RPC_URL = "https://rpc.helius.xyz/?api-key=872ddf73-4cfd-4263-a418-521bbde27eb8"

# Seuils configurables
WHALE_THRESHOLD_USD = 100  # Seuil minimum pour une transaction whale
CRITICAL_THRESHOLD_USD = 5000  # Seuil pour les transactions critiques

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
    def __init__(self, max_calls: int = 2, time_window: int = 2):
        self.max_calls = max_calls  # e.g., 5 calls per second
        self.time_window = time_window  # 1 second
        self.calls = []
        self.semaphore = Semaphore(max_calls)
        self.backoff_time = 0
        self.last_429_time = None

    async def acquire(self):
        """Acquire a permit, respecting rate limits and backoff."""
        now = time.time()
        if self.last_429_time and now - self.last_429_time < self.backoff_time:
            await sleep(self.backoff_time - (now - self.last_429_time) + 0.1)  # Small buffer
        self.calls = [call_time for call_time in self.calls if now - call_time < self.time_window]
        if len(self.calls) >= self.max_calls:
            await sleep(self.time_window - (now - self.calls[0]) + 0.1)
            self.calls = self.calls[1:]
        await self.semaphore.acquire()
        self.calls.append(now)

    def release(self):
        """Release the semaphore."""
        self.semaphore.release()

    def handle_429(self):
        """Handle a 429 error with exponential backoff."""
        self.last_429_time = time.time()
        self.backoff_time = min(self.backoff_time * 3 if self.backoff_time else 2, 180)  # Start at 2s, max 3min
        safe_log_debug(f"429 detected, backing off for {self.backoff_time}s")

class WhaleWalletClassifier:
    """Classification des wallets whales"""
    def __init__(self):
        self.known_whales: set = set()
        self.whale_activity: Dict[str, List[datetime]] = {}
        self.wallet_labels: Dict[str, str] = {}
        self.spam_wallets = {
            "binance_hot": "2ojv9BAiHUrvsm9gxDe7fJSzbNZSJcxZvf8dqmWGHG8S",
            "coinbase_hot": "H8sMJSCQxfKiFTCfDR3DUMLPwcRbM61LGFJ8N4dK3WjS",
            "pump_fun_fee": "CebN5WGQ4jvEPvsVU4EoHEpgzq1VV7AbicfhtW4xC9iM",
        }

    def classify_wallet(self, wallet_address: str, transaction_amount: float) -> Dict[str, str]:
        for label, address in self.spam_wallets.items():
            if wallet_address == address:
                return {"type": "exchange", "label": label.replace('_', ' ').title(), "is_interesting": False}
        now = datetime.now()
        if wallet_address in self.whale_activity:
            recent_activity = [tx_time for tx_time in self.whale_activity[wallet_address] if now - tx_time < timedelta(days=7)]
            if len(recent_activity) >= 3:
                self.known_whales.add(wallet_address)
                return {"type": "recurring_whale", "label": f"Whale récurrent ({len(recent_activity)} tx/7j)", "is_interesting": True}
        if transaction_amount >= CRITICAL_THRESHOLD_USD:
            return {"type": "new_whale", "label": f"Nouvelle whale (${transaction_amount:,.0f})", "is_interesting": True}
        elif transaction_amount >= WHALE_THRESHOLD_USD:
            return {"type": "whale", "label": f"Whale (${transaction_amount:,.0f})", "is_interesting": True}
        return {"type": "unknown", "label": "Wallet inconnu", "is_interesting": False}

    def record_whale_activity(self, wallet_address: str):
        if wallet_address not in self.whale_activity:
            self.whale_activity[wallet_address] = []
        self.whale_activity[wallet_address].append(datetime.now())
        cutoff = datetime.now() - timedelta(days=30)
        self.whale_activity[wallet_address] = [tx_time for tx_time in self.whale_activity[wallet_address] if tx_time > cutoff]

class WhaleTransactionDetector:
    def __init__(self, database_path: str = "tokens.db", whale_threshold: int = WHALE_THRESHOLD_USD):
        self.database_path = database_path
        self.whale_threshold = whale_threshold
        self.classifier = WhaleWalletClassifier()
        self.session: Optional[aiohttp.ClientSession] = None
        self.client: Optional[AsyncClient] = None
        self.is_running = False
        self.rate_limiter = RateLimiter(max_calls=2, time_window=2)
        self.circuit_breaker_failures = 0
        self.circuit_breaker_reset_time = None
        self.last_429_time = None
        self.price_cache = TTLCache(maxsize=2000, ttl=600)
        self.signature_queue = deque(maxlen=100)
        self.batch_interval = 3
        self.debug_stats = {
            'total_processed': 0, 'parse_errors': 0, 'signature_errors': 0,
            'client_errors': 0, 'instruction_errors': 0, 'other_errors': 0
        }
        self.performance_stats = {
            'last_successful_call': time.time(),
            'consecutive_429s': 0,
            'adaptive_delay': 1.0
        }
        self.setup_database()
        logger.info(f"🐋 Whale detector initialized with threshold: ${self.whale_threshold:,}")

    def adjust_rate_limiting(self):
        """Ajuste automatiquement les limites selon les performances"""
        now = time.time()
        
        # Si trop de 429s récents, ralentir drastiquement
        if self.performance_stats['consecutive_429s'] > 3:
            self.rate_limiter.max_calls = 1
            self.rate_limiter.time_window = 5
            self.performance_stats['adaptive_delay'] = min(self.performance_stats['adaptive_delay'] * 2, 30)
            safe_log_debug(f"🔥 EMERGENCY SLOWDOWN: 1 call per 5s, delay {self.performance_stats['adaptive_delay']}s")
        
        # Si pas de problème depuis 5 minutes, accélérer légèrement
        elif now - self.performance_stats['last_successful_call'] > 300:
            self.rate_limiter.max_calls = min(self.rate_limiter.max_calls + 1, 3)
            self.performance_stats['adaptive_delay'] = max(self.performance_stats['adaptive_delay'] * 0.8, 0.5)
            safe_log_debug(f"📈 PERFORMANCE RECOVERY: {self.rate_limiter.max_calls} calls per {self.rate_limiter.time_window}s")

    def setup_database(self):
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS whale_transactions_live (
                    signature TEXT PRIMARY KEY, token_address TEXT, wallet_address TEXT, transaction_type TEXT,
                    amount_usd REAL, amount_tokens REAL, timestamp TIMESTAMP, price_impact REAL,
                    is_known_whale BOOLEAN, wallet_label TEXT, is_in_database BOOLEAN, dex_id TEXT DEFAULT 'unknown',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_whale_timestamp ON whale_transactions_live(timestamp DESC)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_whale_token ON whale_transactions_live(token_address, timestamp DESC)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_whale_amount ON whale_transactions_live(amount_usd DESC)')
            conn.commit()
            logger.info("✅ Whale transactions database initialized")
        except sqlite3.Error as e:
            logger.error(f"Database setup error: {e}")
        finally:
            conn.close()

    async def start(self):
        try:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
            self.client = AsyncClient(SOLANA_RPC_URL)
            self.is_running = True
            asyncio.create_task(self.batch_processing_loop())
            logger.info("🐋 Whale Transaction Detector started")
        except Exception as e:
            safe_log_error("Failed to start whale detector", e)

    async def stop(self):
        self.is_running = False
        try:
            if self.session:
                await self.session.close()
            if self.client:
                await self.client.close()
            logger.info("🐋 Whale Transaction Detector stopped")
            logger.info("📊 DEBUG STATS:")
            for key, value in self.debug_stats.items():
                logger.info(f"   {key}: {value}")
        except Exception as e:
            safe_log_error("Error stopping whale detector", e)

    async def get_token_price_estimate(self, token_address: str) -> float:
        """Fetch token price estimate from Jupiter or DexScreener with enhanced caching and rate limiting."""
        try:
            # Cache hit standard
            if token_address in self.price_cache:
                safe_log_debug(f"Price cache hit for {token_address[:8]}...")
                return self.price_cache[token_address]

            # NOUVEAU: Cache négatif pour éviter de re-requêter les tokens sans prix
            negative_cache_key = f"negative_{token_address}"
            if negative_cache_key in self.price_cache:
                safe_log_debug(f"Negative cache hit for {token_address[:8]}...")
                return 0.0

            # SOL hardcodé
            if token_address == "So11111111111111111111111111111111111111112":
                sol_price = 200.0  # Prix SOL approximatif
                self.price_cache[token_address] = sol_price
                safe_log_debug(f"SOL price: ${sol_price}")
                return sol_price

            # NOUVEAU: Vérifier les stats de performance avant de faire des appels externes
            if self.performance_stats['consecutive_429s'] > 5:
                safe_log_debug(f"Skipping external price call due to performance issues")
                return 0.0

            # Tentative Jupiter avec rate limiting renforcé
            jupiter_url = f"https://quote-api.jup.ag/v6/quote?inputMint={token_address}&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=1000000&slippageBps=500"
            
            await self.rate_limiter.acquire()
            try:
                # NOUVEAU: Ajouter le délai adaptatif
                if self.performance_stats['adaptive_delay'] > 1.0:
                    await sleep(self.performance_stats['adaptive_delay'])
                
                async with self.session.get(jupiter_url, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if "outAmount" in data and data["outAmount"]:
                            price = int(data["outAmount"]) / 1e6
                            self.price_cache[token_address] = price
                            safe_log_debug(f"Fetched Jupiter price for {token_address[:8]}: ${price:.6f}")
                            
                            # NOUVEAU: Marquer le succès
                            self.performance_stats['last_successful_call'] = time.time()
                            return price
                    elif resp.status == 429:
                        self.rate_limiter.handle_429()
                        self.performance_stats['consecutive_429s'] += 1
                        safe_log_debug(f"429 on Jupiter API for {token_address[:8]}")
                        # NOUVEAU: Cache négatif temporaire pour éviter les re-tentatives immédiates
                        self.price_cache[negative_cache_key] = True
                        return 0.0
                    else:
                        safe_log_debug(f"Jupiter API error {resp.status} for {token_address[:8]}")
                        
            except asyncio.TimeoutError:
                safe_log_debug(f"Jupiter API timeout for {token_address[:8]}")
            except Exception as e:
                safe_log_debug(f"Jupiter API exception for {token_address[:8]}: {str(e)}")
            finally:
                self.rate_limiter.release()

            # Tentative DexScreener avec les mêmes protections
            dex_url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            
            await self.rate_limiter.acquire()
            try:
                # NOUVEAU: Délai adaptatif aussi pour DexScreener
                if self.performance_stats['adaptive_delay'] > 1.0:
                    await sleep(self.performance_stats['adaptive_delay'])
                    
                async with self.session.get(dex_url, timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("pairs") and len(data["pairs"]) > 0:
                            price_usd = data["pairs"][0].get("priceUsd")
                            if price_usd and float(price_usd) > 0:
                                price = float(price_usd)
                                self.price_cache[token_address] = price
                                safe_log_debug(f"Fetched DexScreener price for {token_address[:8]}: ${price:.6f}")
                                
                                # NOUVEAU: Marquer le succès
                                self.performance_stats['last_successful_call'] = time.time()
                                return price
                    elif resp.status == 429:
                        self.rate_limiter.handle_429()
                        self.performance_stats['consecutive_429s'] += 1
                        safe_log_debug(f"429 on DexScreener API for {token_address[:8]}")
                        # NOUVEAU: Cache négatif
                        self.price_cache[negative_cache_key] = True
                        return 0.0
                    else:
                        safe_log_debug(f"DexScreener API error {resp.status} for {token_address[:8]}")
                        
            except asyncio.TimeoutError:
                safe_log_debug(f"DexScreener API timeout for {token_address[:8]}")
            except Exception as e:
                safe_log_debug(f"DexScreener API exception for {token_address[:8]}: {str(e)}")
            finally:
                self.rate_limiter.release()
            
            # NOUVEAU: Estimation fallback améliorée basée sur les changements SOL
            if hasattr(self, '_current_sol_change') and self._current_sol_change:
                estimated_price = abs(self._current_sol_change) * 200 / 1000000  # Estimation grossière
                if estimated_price > 0:
                    safe_log_debug(f"Estimated price from SOL change: ${estimated_price:.6f}")
                    # Cache l'estimation mais plus courte durée
                    cache_key_estimated = f"estimated_{token_address}"
                    self.price_cache[cache_key_estimated] = estimated_price
                    return estimated_price
            
            # NOUVEAU: Si aucun prix trouvé, mettre en cache négatif avec TTL plus court
            self.price_cache[negative_cache_key] = True
            safe_log_debug(f"No price found for {token_address[:8]}, cached negative result")
            return 0.0
            
        except Exception as e:
            safe_log_error(f"Error getting price for {token_address[:8]}: {str(e)}", e)
            # NOUVEAU: En cas d'erreur, aussi mettre en cache négatif
            negative_cache_key = f"negative_{token_address}"
            self.price_cache[negative_cache_key] = True
            return 0.0

    async def check_token_in_database(self, token_address: str) -> bool:
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT 1 FROM tokens WHERE address = ? LIMIT 1", (token_address,))
            return cursor.fetchone() is not None
        except sqlite3.Error:
            return False
        finally:
            conn.close()

    async def process_websocket_logs_for_whales(self, signature: str, logs: List[str]):
        if not self.is_running:
            safe_log_debug("Whale detector not running")
            return
        self.signature_queue.append((signature, logs))
        safe_log_debug(f"Queued signature {signature[:20]}... ({len(self.signature_queue)} in queue)")
        if len(self.signature_queue) >= 5:
            await self.process_signature_batch()

    async def process_signature_batch(self):
        while self.signature_queue and self.is_running:
            if self.last_429_time and time.time() - self.last_429_time < self.rate_limiter.backoff_time:
                await sleep(self.rate_limiter.backoff_time - (time.time() - self.last_429_time) + 0.1)
            signature, logs = self.signature_queue.popleft()
            safe_log_debug(f"Processing batched signature {signature[:20]}...")
            whale_tx = await self.parse_transaction_for_whale_activity(signature, logs)
            safe_log_debug(f"Rate limit stats: {self.get_rate_limit_stats()}")
            if whale_tx:
                safe_log_debug(f"Whale transaction detected: ${whale_tx.amount_usd}")
                await self.process_whale_transaction(whale_tx)
            await sleep(0.5)  # Small delay between signatures
        await sleep(self.batch_interval)

    async def batch_processing_loop(self):
        last_adjustment = time.time()
    
        while self.is_running:
            await self.process_signature_batch()
            
            # NOUVEAU: Ajustement périodique (toutes les 30 secondes)
            if time.time() - last_adjustment > 30:
                self.adjust_rate_limiting()
                last_adjustment = time.time()

    def get_rate_limit_stats(self) -> Dict:
        return {
            'circuit_breaker_failures': self.circuit_breaker_failures,
            'last_429_ago_seconds': int(time.time() - self.last_429_time) if self.last_429_time else None,
            'circuit_breaker_reset_in': int(self.circuit_breaker_reset_time - time.time()) if self.circuit_breaker_reset_time else None,
            'rate_limit_calls_recent': len(self.rate_limiter.calls),
            'current_backoff_time': self.rate_limiter.backoff_time,
            'queue_size': len(self.signature_queue)
        }

    def contains_large_swap_indicators(self, logs: List[str]) -> bool:
        """Version corrigée - beaucoup plus permissive pour détecter l'activité DEX"""
        try:
            safe_log_debug(f"Checking indicators in {len(logs)} logs...")
            
            if len(logs) < 8:  # Transactions trop petites généralement pas intéressantes
                safe_log_debug("❌ Transaction too small (< 8 logs)")
                return False

            for i, log in enumerate(logs):
                log_lower = log.lower()
                
                # Débogage: afficher quelques logs pour diagnostic
                if i < 3:  # Afficher les 3 premiers logs
                    safe_log_debug(f"Log {i}: {log}")
                
                # CORRECTION 1: Recherche par IDs de programme (plus fiable)
                program_ids = [
                    "jup6lkbz",  # Jupiter complet
                    "6ef8rrec",  # Pump.fun complet  
                    "675kpx9m",  # Raydium complet
                ]
                
                for program_id in program_ids:
                    if program_id in log_lower:
                        safe_log_debug(f"✅ DEX Program ID {program_id.upper()} found in log {i}")
                        return True
                
                # CORRECTION 2: Mots-clés d'action (utiliser OR au lieu de AND)
                action_keywords = [
                    "instruction: buy",
                    "instruction: sell", 
                    "instruction: swap",
                    "program log: instruction:",
                ]
                
                for keyword in action_keywords:
                    if keyword in log_lower:
                        safe_log_debug(f"✅ Trading pattern '{keyword}' found in log {i}")
                        return True
                
                # CORRECTION 3: Détection de programmes par structure
                if "program" in log_lower and "invoke" in log_lower:
                    safe_log_debug(f"✅ Program invoke pattern found in log {i}")
                    return True
            
            safe_log_debug("❌ No strong DEX indicators found")
            return False
            
        except Exception as e:
            safe_log_error(f"Error in contains_large_swap_indicators: {str(e)}", e)
            return False


    def is_significant_transaction(self, tx_data: Dict) -> bool:
        try:
            amount_usd = tx_data.get('amount_usd', 0)
            wallet = tx_data.get('wallet_address', '')
            token = tx_data.get('token_address', '')
            safe_log_debug(f"🔍 ANALYSE TX: ${amount_usd:.2f} | Wallet: {wallet[:8]}... | Token: {token[:8]}...")
            if amount_usd < self.whale_threshold:
                safe_log_debug(f"Montant insuffisant: ${amount_usd} < ${self.whale_threshold}")
                return False
            if wallet in self.classifier.spam_wallets.values():
                safe_log_debug(f"Wallet spam détecté: {wallet[:8]}...")
                return False
            safe_log_debug(f"Transaction significative: ${amount_usd}")
            return True
        except Exception as e:
            safe_log_error(f"Erreur is_significant_transaction: {str(e)}", e)
            return False

    async def extract_whale_data_from_instruction(self, instruction, message, signature: str, program_id: str, tx_data) -> Optional[Dict]:
        """Version corrigée qui passe tx_data aux méthodes"""
        try:
            safe_log_debug(f"Extraction données pour programme: {program_id[:8]}...")
            accounts = []
            for idx in instruction.accounts:
                if idx < len(message.account_keys):
                    accounts.append(str(message.account_keys[idx]))
            if not accounts:
                safe_log_debug("Aucun compte valide trouvé")
                return None
            
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
                    break
            if not user_wallet:
                user_wallet = accounts[0]
                safe_log_debug(f"Fallback wallet: {user_wallet[:8]}...")
            
            # CORRECTION: Passer tx_data au lieu de refaire l'appel RPC
            if program_id == JUPITER_PROGRAM:
                safe_log_debug("🪐 Calling parse_jupiter_instruction...")
                result = await self.parse_jupiter_instruction([user_wallet] + accounts, instruction, signature, tx_data)
            elif program_id == RAYDIUM_PROGRAM:
                safe_log_debug("🌊 Calling parse_raydium_instruction...")
                result = await self.parse_raydium_instruction([user_wallet] + accounts, instruction, signature, tx_data)
            elif program_id == PUMP_FUN_PROGRAM:
                safe_log_debug("🚀 Calling parse_pump_fun_instruction...")
                result = await self.parse_pump_fun_instruction([user_wallet] + accounts, instruction, signature, tx_data)
            else:
                safe_log_debug(f"Programme non géré: {program_id}")
                return None
            return result
        except Exception as e:
            safe_log_error(f"Erreur globale extraction whale data: {str(e)}", e, signature)
            return None

    async def parse_jupiter_instruction(self, accounts: List[str], instruction, signature: str, tx_data) -> Optional[Dict]:
        try:
            safe_log_debug(f"🪐 Parsing Jupiter instruction: {signature[:20]}...")
            if len(accounts) < 2:
                safe_log_debug(f"🪐 Not enough accounts: {len(accounts)}")
                return None
            user_wallet = accounts[0]
            safe_log_debug(f"🪐 User wallet: {user_wallet[:8]}...")
            if not tx_data or not tx_data.transaction:
                safe_log_debug(f"🪐 No transaction data for {signature[:20]}...")
                return None
        
            pre_balances = tx_data.transaction.meta.pre_token_balances
            post_balances = tx_data.transaction.meta.post_token_balances
            balance_changes = self.analyze_token_balance_changes(pre_balances, post_balances, user_wallet, tx_data)

            if not balance_changes:
                safe_log_debug(f"🪐 No significant balance changes for {signature[:20]}...")
                return None

            primary_change = balance_changes[0]
            token_address = primary_change['mint']
            amount_tokens = abs(primary_change['amount_change'])
            price_usd = await self.get_token_price_estimate(token_address)
            amount_usd = amount_tokens * price_usd if price_usd else 0
            transaction_type = 'buy' if primary_change['amount_change'] > 0 else 'sell'
            safe_log_debug(f"🪐 Parsed: {transaction_type} {amount_tokens:.2f} tokens (${amount_usd:.2f})")
            return {
                'wallet_address': user_wallet, 'token_address': token_address, 'transaction_type': transaction_type,
                'signature': signature, 'dex_id': 'jupiter', 'amount_tokens': amount_tokens, 'amount_usd': amount_usd,
            }
        except Exception as e:
            safe_log_error(f"🪐 Error parsing Jupiter instruction: {str(e)}", e, signature)
            return None

    async def parse_raydium_instruction(self, accounts: List[str], instruction, signature: str, tx_data) -> Optional[Dict]:
        try:
            safe_log_debug(f"🌊 Parsing Raydium instruction: {signature[:20]}...")
            if len(accounts) < 5:
                safe_log_debug(f"🌊 Not enough accounts: {len(accounts)}")
                return None
            user_wallet = accounts[0]
            safe_log_debug(f"🌊 User wallet: {user_wallet[:8]}...")
            
            if not tx_data or not tx_data.transaction:
                safe_log_debug(f"🌊 No transaction data for {signature[:20]}...")
                return None
        
            log_messages = tx_data.transaction.meta.log_messages or []
            is_swap = any("swap" in log.lower() for log in log_messages)
            if not is_swap:
                safe_log_debug(f"🌊 No swap event in logs for {signature[:20]}...")
                return None
            pre_balances = tx_data.transaction.meta.pre_token_balances
            post_balances = tx_data.transaction.meta.post_token_balances
            balance_changes = self.analyze_token_balance_changes(pre_balances, post_balances, user_wallet, tx_data)
            if not balance_changes:
                safe_log_debug(f"🌊 No significant balance changes for {signature[:20]}...")
                return None
            primary_change = max(balance_changes, key=lambda x: abs(x['amount_change']), default=None)
            if not primary_change:
                safe_log_debug(f"🌊 No primary balance change identified")
                return None
            token_address = primary_change['mint']
            amount_tokens = abs(primary_change['amount_change'])
            transaction_type = 'buy' if primary_change['amount_change'] > 0 else 'sell'
            price_usd = await self.get_token_price_estimate(token_address)
            if price_usd == 0.0:
                if token_address == "So11111111111111111111111111111111111111112":
                    price_usd = 200.0  # Prix SOL
                else:
                    # Estimation grossière : si beaucoup de tokens, prix faible
                    if amount_tokens > 1000000:
                        price_usd = 0.00001  # Token très bon marché
                    elif amount_tokens > 1000:
                        price_usd = 0.001   # Token bon marché
                    else:
                        price_usd = 1.0     # Token cher
                safe_log_debug(f"🌊 Using estimated price ${price_usd:.6f} for {token_address[:8]}...")


            amount_usd = amount_tokens * price_usd
            safe_log_debug(f"🌊 Parsed: {transaction_type} {amount_tokens:.2f} tokens (${amount_usd:.2f}) of {token_address[:8]}...")
            return {
                'wallet_address': user_wallet, 'token_address': token_address, 'transaction_type': transaction_type,
                'signature': signature, 'dex_id': 'raydium', 'amount_tokens': amount_tokens, 'amount_usd': amount_usd,
            }
        except Exception as e:
            safe_log_error(f"🌊 Error parsing Raydium instruction: {str(e)}", e, signature)
            return None

    async def parse_pump_fun_instruction(self, accounts: List[str], instruction, signature: str, tx_data) -> Optional[Dict]:
        try:
            safe_log_debug(f"🚀 Parsing Pump.fun instruction: {signature[:20]}...")
            if len(accounts) < 2:
                safe_log_debug(f"🚀 Not enough accounts: {len(accounts)}")
                return None
            user_wallet = accounts[0]
            safe_log_debug(f"🚀 User wallet: {user_wallet[:8]}...")
            
            if not tx_data or not tx_data.transaction:
                safe_log_debug(f"🚀 No transaction data for {signature[:20]}...")
                return None
        
            log_messages = tx_data.transaction.meta.log_messages or []
            trade_data = self.parse_pump_fun_logs(log_messages)
            if not trade_data:
                safe_log_debug(f"🚀 No trade data in logs for {signature[:20]}...")
                return None
            pre_balances = tx_data.transaction.meta.pre_token_balances
            post_balances = tx_data.transaction.meta.post_token_balances
            balance_changes = self.analyze_token_balance_changes(pre_balances, post_balances, user_wallet, tx_data)
            if not balance_changes:
                safe_log_debug(f"🚀 No significant balance changes for {signature[:20]}...")
                return None
            primary_change = max(balance_changes, key=lambda x: abs(x['amount_change']), default=None)
            if not primary_change:
                safe_log_debug(f"🚀 No primary balance change identified")
                return None
            token_address = primary_change['mint']
            amount_tokens = abs(primary_change['amount_change'])
            transaction_type = trade_data.get('transaction_type', 'buy' if primary_change['amount_change'] > 0 else 'sell')
            amount_usd = trade_data.get('amount_usd', 0)
            if amount_usd == 0:
                price_usd = await self.get_token_price_estimate(token_address)
                if price_usd == 0.0:
                    safe_log_debug(f"🚀 Failed to get price for token {token_address[:8]}...")
                    return None
                amount_usd = amount_tokens * price_usd
            safe_log_debug(f"🚀 Parsed: {transaction_type} {amount_tokens:.2f} tokens (${amount_usd:.2f}) of {token_address[:8]}...")
            return {
                'wallet_address': user_wallet, 'token_address': token_address, 'transaction_type': transaction_type,
                'signature': signature, 'dex_id': 'pump_fun', 'amount_tokens': amount_tokens, 'amount_usd': amount_usd,
            }
        except Exception as e:
            safe_log_error(f"🚀 Error parsing Pump.fun instruction: {str(e)}", e, signature)
            return None

    async def parse_transaction_for_whale_activity(self, signature: str, logs: List[str]) -> Optional[WhaleTransaction]:
        """Analyse complète d'une transaction pour détecter l'activité whale"""
        self.debug_stats['total_processed'] += 1
        
        # Circuit breaker et rate limiting
        if self.circuit_breaker_failures > 3:
            if self.circuit_breaker_failures >= 3 and self.circuit_breaker_reset_time and time.time() < self.circuit_breaker_reset_time:
                safe_log_debug(f"Circuit breaker active, skipping {signature[:20]}... until {datetime.fromtimestamp(self.circuit_breaker_reset_time).strftime('%H:%M:%S')}")
                return None
            else:
                self.circuit_breaker_failures = 0
                self.circuit_breaker_reset_time = None
        
        if self.last_429_time and time.time() - self.last_429_time < self.rate_limiter.backoff_time:
            safe_log_debug(f"Rate limit backoff active, skipping {signature[:20]}...")
            return None
        
        try:
            safe_log_debug(f"DÉBUT parsing transaction: {signature[:20]}...", signature)
            
            # Validation de base
            if not signature or len(signature) < 20:
                safe_log_error(f"Invalid signature: '{signature}'")
                self.debug_stats['signature_errors'] += 1
                return None
            
            if not logs:
                safe_log_debug(f"No logs for {signature[:20]}...", signature)
                return None
            
            # Vérification des indicateurs d'activité
            safe_log_debug(f"Analyzing {len(logs)} logs...", signature)
            has_indicators = self.contains_large_swap_indicators(logs)
            safe_log_debug(f"Activity indicators detected: {has_indicators}", signature)
            
            if not has_indicators:
                safe_log_debug(f"STOP: No activity indicators for {signature[:20]}...", signature)
                return None
            
            # Création de la signature Solana
            try:
                sig = Signature.from_string(signature)
                safe_log_debug(f"Signature created successfully", signature)
            except Exception as sig_error:
                safe_log_error(f"Error creating signature: {str(sig_error)}", sig_error, signature)
                self.debug_stats['signature_errors'] += 1
                return None
            
            # Vérification du client RPC
            safe_log_debug(f"Fetching transaction via RPC...", signature)
            if not self.client:
                safe_log_error(f"RPC client not initialized", signature=signature)
                self.debug_stats['client_errors'] += 1
                return None
            
            # Récupération de la transaction avec rate limiting
            await self.rate_limiter.acquire()
            try:
                tx = await self.client.get_transaction(sig, commitment="finalized", max_supported_transaction_version=0)
                safe_log_debug(f"Transaction fetched: {tx is not None}", signature)
                
                # Reset du circuit breaker en cas de succès
                if self.circuit_breaker_failures > 0:
                    self.circuit_breaker_failures = 0
                    self.circuit_breaker_reset_time = None
                    safe_log_debug("Circuit breaker reset - connection OK")
                
                self.performance_stats['last_successful_call'] = time.time()
                self.performance_stats['consecutive_429s'] = 0

            except Exception as client_error:
                error_msg = str(client_error).lower()
                if "429" in error_msg or "too many requests" in error_msg:
                    self.last_429_time = time.time()
                    self.circuit_breaker_failures += 1
                    self.rate_limiter.handle_429()
                    if self.circuit_breaker_failures >= 3:  # Au lieu de 5
                        self.circuit_breaker_reset_time = time.time() + 120  # 2 minutes au lieu de 1
                        safe_log_debug(f"Circuit breaker activated, pausing for 120s")
                    
                    self.performance_stats['consecutive_429s'] += 1
                    self.adjust_rate_limiting()
                    safe_log_error(f"Rate limit 429 - backing off for {self.rate_limiter.backoff_time}s", client_error, signature)
                else:
                    safe_log_error(f"Error fetching transaction: {str(client_error)}", client_error, signature)
                    self.circuit_breaker_failures += 1
                    self.debug_stats['client_errors'] += 1
                return None
            finally:
                self.rate_limiter.release()
            
            # Validation de la transaction récupérée
            if not tx.value or not tx.value.transaction:
                safe_log_debug(f"Empty transaction (tx={tx is not None})", signature)
                return None
            
            if not tx.value.transaction.meta:
                safe_log_debug(f"No transaction meta data", signature)
                return None
            
            safe_log_debug(f"Valid transaction fetched", signature)
            
            # Analyse des instructions de la transaction
            try:
                message = tx.value.transaction.transaction.message
                safe_log_debug(f"Analyzing {len(message.instructions)} instructions...", signature)
                
                # Compteurs pour debug
                dex_programs_found = 0
                
                for i, instruction in enumerate(message.instructions):
                    try:
                        # Validation de l'index du programme
                        if instruction.program_id_index >= len(message.account_keys):
                            safe_log_debug(f"Invalid program index: {instruction.program_id_index} >= {len(message.account_keys)}", signature)
                            continue
                        
                        program_id = str(message.account_keys[instruction.program_id_index])
                        safe_log_debug(f"Found program {i}: {program_id[:8]}... ({program_id})", signature)
                        
                        # Vérification si c'est un programme DEX connu
                        if program_id in [JUPITER_PROGRAM, RAYDIUM_PROGRAM, PUMP_FUN_PROGRAM]:
                            dex_programs_found += 1
                            safe_log_debug(f"🎯 DEX PROGRAM DETECTED #{dex_programs_found}: {program_id[:8]}...", signature)
                            
                            # Extraction des données whale
                            whale_data = await self.extract_whale_data_from_instruction(
                                instruction, message, signature, program_id, tx.value
                            )
                            
                            safe_log_debug(f"Whale data extracted: {whale_data is not None}", signature)
                            
                            if whale_data:
                                safe_log_debug(f"💰 Amount found: ${whale_data.get('amount_usd', 0):.2f} | Tokens: {whale_data.get('amount_tokens', 0):.2f}", signature)
                                
                                # Test de significativité
                                if self.is_significant_transaction(whale_data):
                                    safe_log_debug(f"🐋 SIGNIFICANT TRANSACTION DETECTED!", signature)
                                    
                                    # Création de l'objet WhaleTransaction
                                    whale_tx = await self.create_whale_transaction(whale_data)
                                    if whale_tx:
                                        safe_log_debug(f"✅ WhaleTransaction created: ${whale_tx.amount_usd:.2f}", signature)
                                        return whale_tx
                                    else:
                                        safe_log_debug(f"❌ Failed to create WhaleTransaction", signature)
                                else:
                                    safe_log_debug(f"💸 Transaction not significant enough: ${whale_data.get('amount_usd', 0):.2f} < ${self.whale_threshold}", signature)
                            else:
                                safe_log_debug(f"❌ No whale data could be extracted", signature)
                                
                    except Exception as instruction_error:
                        safe_log_error(f"Error processing instruction {i}: {str(instruction_error)}", instruction_error, signature)
                        self.debug_stats['instruction_errors'] += 1
                        continue
                
                # Résumé de l'analyse
                safe_log_debug(f"📊 Analysis complete: {dex_programs_found} DEX programs found in {len(message.instructions)} instructions", signature)
                
                if dex_programs_found == 0:
                    safe_log_debug(f"ℹ️  No DEX programs detected in transaction", signature)
                
                safe_log_debug(f"❌ NO WHALE FOUND for {signature[:20]}...", signature)
                
            except Exception as message_error:
                safe_log_error(f"Error analyzing message: {str(message_error)}", message_error, signature)
                self.debug_stats['instruction_errors'] += 1
                return None
                
        except Exception as e:
            safe_log_error(f"GLOBAL ERROR parsing transaction {signature[:20]}...: {str(e)}", e, signature)
            self.debug_stats['other_errors'] += 1
            return None
        
        return None

    def log_detection_stats(self):
        """Log des statistiques détaillées pour debug"""
        total = self.debug_stats['total_processed']
        if total > 0:
            safe_log_debug(f"📊 STATS: {total} transactions traitées")
            safe_log_debug(f"   - Erreurs parsing: {self.debug_stats['parse_errors']} ({self.debug_stats['parse_errors']/total*100:.1f}%)")
            safe_log_debug(f"   - Erreurs signature: {self.debug_stats['signature_errors']} ({self.debug_stats['signature_errors']/total*100:.1f}%)")
            safe_log_debug(f"   - Erreurs client: {self.debug_stats['client_errors']} ({self.debug_stats['client_errors']/total*100:.1f}%)")
            safe_log_debug(f"   - Erreurs instruction: {self.debug_stats['instruction_errors']} ({self.debug_stats['instruction_errors']/total*100:.1f}%)")
            safe_log_debug(f"   - Queue size: {len(self.signature_queue)}")

    async def create_whale_transaction(self, whale_data: Dict) -> WhaleTransaction:
        try:
            safe_log_debug(f"Création WhaleTransaction: ${whale_data.get('amount_usd', 0)}")
            wallet_classification = self.classifier.classify_wallet(whale_data['wallet_address'], whale_data['amount_usd'])
            self.classifier.record_whale_activity(whale_data['wallet_address'])
            is_in_db = await self.check_token_in_database(whale_data['token_address'])
            return WhaleTransaction(
                signature=whale_data['signature'],
                token_address=whale_data['token_address'],
                wallet_address=whale_data['wallet_address'],
                transaction_type=whale_data['transaction_type'],
                amount_usd=whale_data['amount_usd'],
                amount_tokens=whale_data.get('amount_tokens', 0),
                timestamp=datetime.now(),
                price_impact=whale_data.get('price_impact', 0),
                is_known_whale=wallet_classification['is_interesting'],
                wallet_label=wallet_classification['label'],
                is_in_database=is_in_db,
                dex_id=whale_data.get('dex_id', 'unknown')
            )
        except Exception as e:
            safe_log_error(f"Erreur création whale transaction: {str(e)}", e)
            return None

    def analyze_token_balance_changes(self, pre_balances, post_balances, user_wallet: str, tx_data=None) -> List[Dict]:
        """Version améliorée avec analyse SOL"""
        changes = []
        try:
            # Analyser les balances SOL
            if tx_data and tx_data.transaction and tx_data.transaction.meta:
                meta = tx_data.transaction.meta
                if meta.pre_balances and meta.post_balances:
                    account_keys = tx_data.transaction.transaction.message.account_keys
                    for i, account in enumerate(account_keys):
                        if str(account) == user_wallet:
                            if i < len(meta.pre_balances) and i < len(meta.post_balances):
                                pre_sol_amount = meta.pre_balances[i] / 1e9
                                post_sol_amount = meta.post_balances[i] / 1e9
                                sol_change = post_sol_amount - pre_sol_amount
                                if abs(sol_change) > 0.1:  # Plus de 0.1 SOL
                                    changes.append({
                                        'mint': 'So11111111111111111111111111111111111111112',
                                        'owner': user_wallet,
                                        'pre_amount': pre_sol_amount,
                                        'post_amount': post_sol_amount,
                                        'amount_change': sol_change
                                    })
                                    safe_log_debug(f"SOL change: {sol_change:.3f} SOL")
            
            # Token balances existant...
            pre_dict = {}
            post_dict = {}
            if pre_balances:
                for balance in pre_balances:
                    if hasattr(balance, 'owner') and str(balance.owner) == user_wallet:
                        key = (str(balance.mint), str(balance.owner))
                        pre_dict[key] = float(balance.ui_token_amount.ui_amount or 0)
            
            if post_balances:
                for balance in post_balances:
                    if hasattr(balance, 'owner') and str(balance.owner) == user_wallet:
                        key = (str(balance.mint), str(balance.owner))
                        post_dict[key] = float(balance.ui_token_amount.ui_amount or 0)
            
            all_keys = set(pre_dict.keys()) | set(post_dict.keys())
            for key in all_keys:
                mint, owner = key
                pre_amount = pre_dict.get(key, 0)
                post_amount = post_dict.get(key, 0)
                change = post_amount - pre_amount
                if abs(change) > 0.001:
                    changes.append({
                        'mint': mint, 'owner': owner, 'pre_amount': pre_amount,
                        'post_amount': post_amount, 'amount_change': change
                    })
            
            safe_log_debug(f"📊 Analysé {len(changes)} changements de balance significatifs")
            return changes
        except Exception as e:
            safe_log_error(f"❌ Erreur analyse token balances: {e}", e)
            return changes


    def parse_pump_fun_logs(self, log_messages: List[str]) -> Optional[Dict]:
        """Parse les logs Pump.fun pour extraire les données de trading - Version corrigée"""
        try:
            safe_log_debug(f"🚀 Parsing {len(log_messages)} Pump.fun logs...")
            
            for i, log in enumerate(log_messages):
                log_lower = log.lower()
                
                # Debug: afficher les premiers logs
                if i < 5:
                    safe_log_debug(f"🚀 Log {i}: {log}")
                
                # CORRECTION 1: Recherche plus large des indicateurs d'action
                buy_indicators = [
                    "buy", "purchase", "acquire", "swap in", "trade in",
                    "instruction: buy", "buyinstruction", "buypumpfun"
                ]
                sell_indicators = [
                    "sell", "dispose", "exit", "swap out", "trade out", 
                    "instruction: sell", "sellinstruction", "sellpumpfun"
                ]
                
                # Détection du type de transaction
                transaction_type = None
                if any(indicator in log_lower for indicator in buy_indicators):
                    transaction_type = "buy"
                    safe_log_debug(f"🚀 Buy transaction detected in log {i}")
                elif any(indicator in log_lower for indicator in sell_indicators):
                    transaction_type = "sell"
                    safe_log_debug(f"🚀 Sell transaction detected in log {i}")
                
                # Si on a détecté une action, chercher les montants
                if transaction_type:
                    import re
                    
                    # Patterns de recherche améliorés
                    patterns = {
                        'sol': [
                            r'(\d+\.?\d*)\s*sol',
                            r'sol:\s*(\d+\.?\d*)',
                            r'amount:\s*(\d+\.?\d*)\s*sol',
                            r'(\d+\.?\d*)\s*lamports'  # 1 SOL = 1e9 lamports
                        ],
                        'usd': [
                            r'\$(\d+\.?\d*)',
                            r'usd:\s*(\d+\.?\d*)',
                            r'(\d+\.?\d*)\s*usd',
                            r'value:\s*\$(\d+\.?\d*)'
                        ],
                        'tokens': [
                            r'(\d+\.?\d*)\s*tokens?',
                            r'tokens?:\s*(\d+\.?\d*)',
                            r'amount:\s*(\d+\.?\d*)\s*tokens?',
                            r'quantity:\s*(\d+\.?\d*)'
                        ]
                    }
                    
                    # Extraction des montants
                    sol_amount = 0
                    usd_amount = 0
                    token_amount = 0
                    
                    # Recherche SOL
                    for pattern in patterns['sol']:
                        match = re.search(pattern, log_lower)
                        if match:
                            sol_amount = float(match.group(1))
                            if 'lamports' in pattern:
                                sol_amount = sol_amount / 1e9  # Convertir lamports en SOL
                            safe_log_debug(f"🚀 SOL amount found: {sol_amount}")
                            break
                    
                    # Recherche USD
                    for pattern in patterns['usd']:
                        match = re.search(pattern, log_lower)
                        if match:
                            usd_amount = float(match.group(1))
                            safe_log_debug(f"🚀 USD amount found: {usd_amount}")
                            break
                    
                    # Recherche tokens
                    for pattern in patterns['tokens']:
                        match = re.search(pattern, log_lower)
                        if match:
                            token_amount = float(match.group(1))
                            safe_log_debug(f"🚀 Token amount found: {token_amount}")
                            break
                    
                    # Calcul du montant USD si pas trouvé directement
                    if usd_amount == 0 and sol_amount > 0:
                        usd_amount = sol_amount * 200  # Prix SOL approximatif
                        safe_log_debug(f"🚀 USD calculated from SOL: ${usd_amount}")
                    
                    # Si on a au moins un montant ou le type de transaction
                    if sol_amount > 0 or usd_amount > 0 or token_amount > 0 or transaction_type:
                        result = {
                            'transaction_type': transaction_type,
                            'amount_usd': usd_amount,
                            'amount_tokens': token_amount,
                            'sol_amount': sol_amount
                        }
                        safe_log_debug(f"🚀 Pump.fun parsed successfully: {transaction_type} ${usd_amount:.2f}")
                        return result
            
            # CORRECTION 2: Fallback plus permissif
            # Si on a des logs mais pas de pattern spécifique, chercher des indices génériques
            for log in log_messages:
                log_lower = log.lower()
                
                # Recherche de patterns génériques d'instruction
                if any(keyword in log_lower for keyword in ["instruction:", "program log:", "invoke"]):
                    # C'est probablement une instruction Pump.fun
                    
                    # Tentative d'extraction de nombres
                    import re
                    numbers = re.findall(r'\d+\.?\d*', log)
                    if numbers:
                        # Prendre le plus gros nombre comme montant potentiel
                        amounts = [float(n) for n in numbers if float(n) > 0]
                        if amounts:
                            max_amount = max(amounts)
                            
                            # Heuristique sur la taille du nombre
                            if max_amount > 1000000000:  # Probable lamports
                                sol_amount = max_amount / 1e9
                                usd_amount = sol_amount * 200
                            elif max_amount > 1000:  # Probable tokens
                                token_amount = max_amount
                                usd_amount = 0  # Sera calculé plus tard
                            else:  # Probable SOL ou USD
                                sol_amount = max_amount
                                usd_amount = max_amount * 200
                            
                            result = {
                                'transaction_type': 'buy',  # Défaut à buy
                                'amount_usd': usd_amount,
                                'amount_tokens': token_amount if 'token_amount' in locals() else 0,
                                'sol_amount': sol_amount if 'sol_amount' in locals() else 0
                            }
                            safe_log_debug(f"🚀 Pump.fun fallback parsing: ${usd_amount:.2f}")
                            return result
            
            # CORRECTION 3: Fallback ultime pour Pump.fun
            if log_messages and len(log_messages) > 0:
                # Si on a des logs mais rien trouvé, c'est quand même une transaction Pump.fun
                safe_log_debug(f"🚀 Pump.fun ultimate fallback: assuming minimal transaction")
                return {
                    'transaction_type': 'buy',  # Défaut
                    'amount_usd': 0,  # Sera calculé à partir des balances
                    'amount_tokens': 0,
                    'sol_amount': 0
                }
            
            safe_log_debug(f"🚀 No Pump.fun trade data found in logs")
            return None
            
        except Exception as e:
            safe_log_error(f"❌ Erreur parsing Pump.fun logs: {e}", e)
            return None

    async def save_whale_transaction(self, whale_tx: WhaleTransaction):
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
        await self.save_whale_transaction(whale_tx)
        if whale_tx.is_in_database:
            logger.debug(f"📈 Whale activity on tracked token: {whale_tx.token_address}")
        else:
            logger.info(f"📊 New whale activity: {whale_tx.token_address}")
            if whale_tx.amount_usd >= CRITICAL_THRESHOLD_USD:
                await self.queue_token_for_discovery(whale_tx.token_address)
                logger.debug(f"🎯 Queued critical token for discovery: {whale_tx.token_address}")

    async def queue_token_for_discovery(self, token_address: str):
        try:
            # Placeholder: Replace with actual integration if solana_monitor_c4 exists
            logger.debug(f"🔍 Token queued for enrichment: {token_address}")
        except Exception as e:
            logger.error(f"Error queuing token for discovery: {e}")

class WhaleActivityAPI:
    def __init__(self, database_path: str = "tokens.db", whale_threshold: int = 10000):
        self.database_path = database_path
        self.whale_threshold = whale_threshold
        self._debug_mode = True  # Active le mode debug
        self._transactions_seen = 0
        self._transactions_with_dex_programs = 0
        self._transactions_with_balances = 0
        self._transactions_with_prices = 0

    def log_debug_stats(self):
        """Affiche les stats de debug"""
        safe_log_debug(f"📊 DEBUG STATS:")
        safe_log_debug(f"   Transactions vues: {self._transactions_seen}")
        safe_log_debug(f"   Avec programmes DEX: {self._transactions_with_dex_programs}")
        safe_log_debug(f"   Avec changements balance: {self._transactions_with_balances}")
        safe_log_debug(f"   Avec prix trouvés: {self._transactions_with_prices}")
        #safe_log_debug(f"   Queue size: {len(self.signature_queue)}")


    def get_token_info_for_whale(self, token_address: str) -> Dict:
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
                return {'symbol': result[0] or 'UNKNOWN', 'name': result[1] or 'Unknown Token', 'status': result[2] or 'unknown'}
            return {'symbol': 'NEW', 'name': 'New Token', 'status': 'new'}
        except sqlite3.Error:
            return {'symbol': 'ERROR', 'name': 'Error Token', 'status': 'error'}
        finally:
            conn.close()

    def get_recent_whale_activity(self, hours: int = 1, limit: int = 50) -> List[Dict]:
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
        try:
            if isinstance(timestamp_str, str):
                dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            else:
                dt = timestamp_str
            return dt.strftime('%d/%m %H:%M:%S')
        except:
            return 'Invalid date'

    def format_whale_amount(self, amount_usd: float) -> str:
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
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        try:
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

whale_detector = WhaleTransactionDetector()
whale_api = WhaleActivityAPI()

async def process_websocket_logs_for_whales(signature: str, logs: List[str]):
    """Process WebSocket logs for whale activity using the global detector instance."""
    if not whale_detector.is_running:
        return
    
    # NOUVEAU: Filtrage précoce pour éviter d'encombrer la queue
    if not whale_detector.contains_large_swap_indicators(logs):
        safe_log_debug(f"Skipping {signature[:20]}... - no DEX indicators")
        return
        
    whale_detector.signature_queue.append((signature, logs))
    safe_log_debug(f"Queued signature {signature[:20]}... ({len(whale_detector.signature_queue)} in queue)")
    
    # Traiter par lots plus gros pour réduire la fréquence
    if len(whale_detector.signature_queue) >= 3:  # Au lieu de 5
        await whale_detector.process_signature_batch()

async def start_whale_monitoring():
    """Démarrer le monitoring des transactions whales"""
    logger.info("🐋 Starting Whale Transaction Monitoring System")
    await whale_detector.start()

async def stop_whale_monitoring():
    """Arrêter le monitoring des transactions whales"""
    await whale_detector.stop()

async def main():
    await whale_detector.start()
    try:
        while True:
            await asyncio.sleep(3600)  # Keep running
    except KeyboardInterrupt:
        await whale_detector.stop()

if __name__ == "__main__":
    asyncio.run(main())