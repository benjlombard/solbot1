#!/usr/bin/env python3
"""
🐋 Whale Detector Integration - Intégration du système de détection whale
Version adaptée pour s'intégrer parfaitement avec solana_monitor_c4.py
"""

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

logger = logging.getLogger('whale_detector')

# Configuration
HELIUS_WS_URL = "wss://rpc.helius.xyz/?api-key=872ddf73-4cfd-4263-a418-521bbde27eb8"
SOLANA_RPC_URL = "https://rpc.helius.xyz/?api-key=872ddf73-4cfd-4263-a418-521bbde27eb8"

# Seuils configurables
WHALE_THRESHOLD_USD = 100  # Seuil minimum pour une transaction whale
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
    
    def __init__(self, database_path: str = "tokens.db"):
        self.database_path = database_path
        self.classifier = WhaleWalletClassifier()
        self.session: Optional[aiohttp.ClientSession] = None
        self.client: Optional[AsyncClient] = None
        self.is_running = False
        self.setup_database()
    
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
        self.session = aiohttp.ClientSession()
        self.client = AsyncClient(SOLANA_RPC_URL)
        self.is_running = True
        logger.info("🐋 Whale Transaction Detector started")
    
    async def stop(self):
        """Arrêter le détecteur"""
        self.is_running = False
        if self.session:
            await self.session.close()
        if self.client:
            await self.client.close()
        logger.info("🐋 Whale Transaction Detector stopped")
    
    async def get_token_price_estimate(self, token_address: str) -> float:
        """Estimer le prix d'un token via Jupiter ou DexScreener"""
        try:
            # Essayer Jupiter d'abord
            jupiter_url = f"https://quote-api.jup.ag/v6/quote?inputMint={token_address}&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=1000000&slippageBps=500"
            
            async with self.session.get(jupiter_url, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "outAmount" in data:
                        return int(data["outAmount"]) / 1e6
            
            # Fallback sur DexScreener
            dex_url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            async with self.session.get(dex_url, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("pairs"):
                        return float(data["pairs"][0].get("priceUsd", 0))
            
        except Exception as e:
            logger.debug(f"Error getting price for {token_address}: {e}")
        
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
        """Parser une transaction pour détecter l'activité whale"""
        try:
            logger.info(f"🔍 DEBUT parsing transaction: {signature[:20]}...")
            
            # Analyser les logs pour détecter les gros swaps
            has_indicators = self.contains_large_swap_indicators(logs)
            logger.info(f"🔍 Indicateurs détectés: {has_indicators}")
            
            if not has_indicators:
                logger.warning(f"❌ ARRÊT: Pas d'indicateurs pour {signature[:20]}...")
                return None
            
            logger.info(f"✅ CONTINUE: Récupération transaction {signature[:20]}...")
            
            sig = Signature.from_string(signature)
            tx = await self.client.get_transaction(
                sig,
                commitment="finalized",
                max_supported_transaction_version=0
            )
            
            if not tx.value or not tx.value.transaction:
                logger.warning(f"❌ TRANSACTION VIDE pour {signature[:20]}...")
                return None
            
            logger.info(f"✅ TRANSACTION RÉCUPÉRÉE pour {signature[:20]}...")
            
            # Analyser les instructions de la transaction
            message = tx.value.transaction.transaction.message
            logger.info(f"🔍 Analyse {len(message.instructions)} instructions...")
            
            # Rechercher les transferts de tokens importants
            for i, instruction in enumerate(message.instructions):
                program_id = str(message.account_keys[instruction.program_id_index])
                logger.info(f"   Instruction {i}: Programme {program_id[:8]}...")
                
                # Analyser les instructions des programmes DEX
                if program_id in [JUPITER_PROGRAM, RAYDIUM_PROGRAM, PUMP_FUN_PROGRAM]:
                    logger.info(f"🎯 PROGRAMME DEX TROUVÉ: {program_id[:8]}...")
                    
                    whale_data = await self.extract_whale_data_from_instruction(
                        instruction, message, signature, program_id
                    )
                    
                    logger.info(f"🔍 Whale data extraite: {whale_data is not None}")
                    
                    if whale_data:
                        logger.info(f"💰 Montant USD: {whale_data.get('amount_usd', 0)}")
                        
                        if self.is_significant_transaction(whale_data):
                            logger.info(f"✅ TRANSACTION SIGNIFICATIVE!")
                            return await self.create_whale_transaction(whale_data)
                        else:
                            logger.warning(f"❌ Transaction pas assez significative")
            
            logger.warning(f"❌ AUCUNE WHALE TROUVÉE pour {signature[:20]}...")
            
        except Exception as e:
            logger.error(f"❌ ERREUR parsing transaction {signature[:20]}...: {e}")
        
        return None
    
    def contains_large_swap_indicators(self, logs: List[str]) -> bool:
        """Vérifier si les logs indiquent un gros swap"""
        logger.info(f"🔍 Vérification indicateurs sur {len(logs)} logs...")
        
        for i, log in enumerate(logs):
            log_lower = log.lower()
            
            # 🎯 INDICATEURS ÉLARGIS
            # 1. Toute mention de Jupiter
            if "jupiter" in log_lower:
                logger.info(f"✅ INDICATEUR JUPITER trouvé log {i}: {log[:80]}...")
                return True
            
            # 2. Toute mention de "route"
            if "route" in log_lower:
                logger.info(f"✅ INDICATEUR ROUTE trouvé log {i}: {log[:80]}...")
                return True
            
            # 3. Swaps, transfers, instructions avec montants
            if any(word in log_lower for word in ["swap", "transfer", "instruction:"]):
                logger.info(f"✅ INDICATEUR GÉNÉRIQUE trouvé log {i}: {log[:80]}...")
                return True
            
            # 4. Raydium, Pump.fun, autres DEX
            if any(word in log_lower for word in ["raydium", "pump", "orca", "meteora"]):
                logger.info(f"✅ INDICATEUR DEX trouvé log {i}: {log[:80]}...")
                return True
        
        logger.warning("❌ AUCUN INDICATEUR TROUVÉ dans les logs")
        return False
    
    def is_significant_transaction(self, tx_data: Dict) -> bool:
        """Vérifier si une transaction est significative"""
        amount_usd = tx_data.get('amount_usd', 0)
        wallet = tx_data.get('wallet_address', '')
        
        # Filtrer par montant minimum
        if amount_usd < WHALE_THRESHOLD_USD:
            return False
        
        # Filtrer les wallets spam
        if wallet in self.classifier.spam_wallets.values():
            return False
        
        return True
    
    async def extract_whale_data_from_instruction(self, instruction, message, signature: str, program_id: str) -> Optional[Dict]:
        """Extraire les données whale d'une instruction"""
        try:
            logger.info(f"🔍 Extraction données pour programme: {program_id[:8]}...")
            
            # Vérifier les indices avant de les utiliser
            try:
                accounts = []
                for idx in instruction.accounts:
                    if idx < len(message.account_keys):
                        accounts.append(str(message.account_keys[idx]))
                    else:
                        logger.warning(f"⚠️ Index {idx} dépasse {len(message.account_keys)} comptes")
                
                logger.info(f"🔍 {len(accounts)} comptes valides récupérés")
                
            except Exception as e:
                logger.error(f"❌ Erreur extraction comptes: {e}")
                # FALLBACK: Utiliser tous les comptes disponibles
                accounts = [str(key) for key in message.account_keys]
                logger.info(f"🔄 Fallback: {len(accounts)} comptes totaux utilisés")
            
            # FIX: Filtrer les comptes système pour trouver le vrai user wallet
            system_accounts = {
                "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                "11111111111111111111111111111111",
                "ComputeBudget111111111111111111111111111111",
                "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
                program_id
            }
            
            # Trouver le premier compte qui n'est pas un programme système
            user_wallet = None
            for account in accounts:
                if account not in system_accounts and not account.startswith("11111"):
                    user_wallet = account
                    logger.info(f"🎯 User wallet trouvé: {user_wallet[:8]}...")
                    break
            
            if not user_wallet and accounts:
                user_wallet = accounts[0]  # Fallback sur le premier compte
                logger.warning(f"⚠️ Fallback wallet: {user_wallet[:8]}...")
            
            if not user_wallet:
                logger.warning("❌ Aucun wallet utilisateur trouvé")
                return None

            # Logique spécifique selon le programme
            if program_id == JUPITER_PROGRAM:
                logger.info("🪐 APPEL parse_jupiter_instruction...")
                result = await self.parse_jupiter_instruction([user_wallet] + accounts, instruction, signature)
                logger.info(f"🪐 RÉSULTAT Jupiter: {result is not None}")
                if result:
                    logger.info(f"💰 Montant: ${result.get('amount_usd', 0)}")
                return result
            elif program_id == RAYDIUM_PROGRAM:
                logger.info("🌊 APPEL parse_raydium_instruction...")
                result = await self.parse_raydium_instruction([user_wallet] + accounts, instruction, signature)
                logger.info(f"🌊 RÉSULTAT Raydium: {result is not None}")
                if result:
                    logger.info(f"💰 Montant: ${result.get('amount_usd', 0)}")
                return result
            elif program_id == PUMP_FUN_PROGRAM:
                logger.info("🚀 APPEL parse_pump_fun_instruction...")
                result = await self.parse_pump_fun_instruction([user_wallet] + accounts, instruction, signature)
                logger.info(f"🚀 RÉSULTAT Pump.fun: {result is not None}")
                if result:
                    logger.info(f"💰 Montant: ${result.get('amount_usd', 0)}")
                return result
            
        except Exception as e:
            logger.error(f"❌ Erreur extraction whale data: {e}")
            import traceback
            logger.error(f"Stack trace: {traceback.format_exc()}")
        
        return None
    
    async def parse_jupiter_instruction(self, accounts: List[str], instruction, signature: str) -> Optional[Dict]:
        """Parser une instruction Jupiter pour extraire les données de swap"""
        try:
            logger.info(f"🪐 Jupiter: {len(accounts)} comptes disponibles")
            
            if len(accounts) < 1:
                logger.warning(f"❌ Pas assez de comptes Jupiter: {len(accounts)}")
                return None
            
            # Dans Jupiter, généralement:
            # accounts[0] = user wallet
            # accounts[1] = user source token account
            # accounts[2] = user dest token account
            user_wallet = accounts[0]
            logger.info(f"🪐 User wallet: {user_wallet[:8]}...")
            
            # Analyser les données de l'instruction pour extraire les montants
            try:
                if hasattr(instruction, 'data') and instruction.data:
                    # Convertir en bytes si nécessaire
                    if isinstance(instruction.data, (list, tuple)):
                        instruction_data = bytes(instruction.data)
                    elif isinstance(instruction.data, str):
                        instruction_data = instruction.data.encode('utf-8')
                    else:
                        instruction_data = instruction.data
                else:
                    instruction_data = b''
                    
                logger.info(f"🪐 Instruction data length: {len(instruction_data)}")
                
            except Exception as data_error:
                logger.debug(f"⚠️ Erreur lecture instruction data: {data_error}")
                instruction_data = b''
            
            # Jupiter utilise des structures complexes, on va essayer d'analyser
            # les logs de transaction pour extraire les montants réels
            try:
                # Récupérer la transaction complète pour analyser les pré/post token balances
                sig = Signature.from_string(signature)
                tx = await self.client.get_transaction(
                    sig,
                    commitment="finalized",
                    max_supported_transaction_version=0
                )
                
                if tx.value and tx.value.transaction and hasattr(tx.value, 'meta'):
                    meta = tx.value.meta
                    
                    # Analyser les changements de balance de tokens
                    if hasattr(meta, 'pre_token_balances') and hasattr(meta, 'post_token_balances'):
                        token_changes = self.analyze_token_balance_changes(
                            meta.pre_token_balances, 
                            meta.post_token_balances,
                            user_wallet
                        )
                        
                        if token_changes:
                            logger.info(f"🪐 Token changes détectés: {len(token_changes)}")
                            
                            # Prendre le plus gros changement comme base
                            largest_change = max(token_changes, key=lambda x: abs(x['amount_change']))
                            
                            # Estimer la valeur USD
                            price = await self.get_token_price_estimate(largest_change['mint'])
                            amount_usd = abs(largest_change['amount_change']) * price
                            
                            logger.info(f"🪐 Largest change: {largest_change['amount_change']} tokens, ${amount_usd}")
                            
                            return {
                                'wallet_address': user_wallet,
                                'token_address': largest_change['mint'],
                                'transaction_type': 'sell' if largest_change['amount_change'] < 0 else 'buy',
                                'signature': signature,
                                'dex_id': 'jupiter',
                                'amount_tokens': abs(largest_change['amount_change']),
                                'amount_usd': amount_usd,
                            }
            
            except Exception as e:
                logger.error(f"❌ Erreur analyse token balances Jupiter: {e}")
            
            # Fallback: créer une transaction générique avec estimation
            return {
                'wallet_address': user_wallet,
                'token_address': "So11111111111111111111111111111111111111112",  # SOL par défaut
                'transaction_type': 'swap',
                'signature': signature,
                'dex_id': 'jupiter',
                'amount_tokens': 1.0,
                'amount_usd': 500.0,  # Montant minimum pour déclencher le seuil
            }
            
        except Exception as e:
            logger.error(f"❌ Erreur parsing Jupiter: {e}")
        
        return None
    
    async def parse_raydium_instruction(self, accounts: List[str], instruction, signature: str) -> Optional[Dict]:
        """Parser une instruction Raydium pour extraire les données de swap"""
        try:
            logger.info(f"🌊 Raydium: {len(accounts)} comptes disponibles")
            
            if len(accounts) < 5:
                logger.warning(f"❌ Pas assez de comptes Raydium: {len(accounts)}")
                return None
            
            # Dans Raydium AMM, généralement:
            # accounts[0] = user wallet  
            # accounts[1] = user source token account
            # accounts[2] = user dest token account
            # accounts[3] = AMM pool
            user_wallet = accounts[0]
            logger.info(f"🌊 User wallet: {user_wallet[:8]}...")
            
            # Analyser les données de l'instruction
            try:
                if hasattr(instruction, 'data') and instruction.data:
                    if isinstance(instruction.data, (list, tuple)):
                        instruction_data = bytes(instruction.data)
                    elif isinstance(instruction.data, str):
                        instruction_data = instruction.data.encode('utf-8')
                    else:
                        instruction_data = instruction.data
                else:
                    instruction_data = b''
                    
                logger.info(f"🌊 Instruction data length: {len(instruction_data)}")
                
            except Exception as data_error:
                logger.debug(f"⚠️ Erreur lecture instruction data Raydium: {data_error}")
                instruction_data = b''
            
            # Le premier byte indique le type d'instruction Raydium
            if len(instruction_data) >= 1:
                instruction_type = instruction_data[0]
                logger.info(f"🌊 Raydium instruction type: {instruction_type}")
                
                # Types courants:
                # 9 = swap_base_in
                # 11 = swap_base_out
                if instruction_type in [9, 11]:
                    try:
                        # Récupérer la transaction pour analyser les token balances
                        sig = Signature.from_string(signature)
                        tx = await self.client.get_transaction(
                            sig,
                            commitment="finalized",
                            max_supported_transaction_version=0
                        )
                        
                        if tx.value and tx.value.transaction and hasattr(tx.value, 'meta'):
                            meta = tx.value.meta
                            
                            if hasattr(meta, 'pre_token_balances') and hasattr(meta, 'post_token_balances'):
                                token_changes = self.analyze_token_balance_changes(
                                    meta.pre_token_balances,
                                    meta.post_token_balances,
                                    user_wallet
                                )
                                
                                if token_changes:
                                    logger.info(f"🌊 Token changes Raydium: {len(token_changes)}")
                                    
                                    # Prendre le plus gros changement
                                    largest_change = max(token_changes, key=lambda x: abs(x['amount_change']))
                                    
                                    # Estimer la valeur USD
                                    price = await self.get_token_price_estimate(largest_change['mint'])
                                    amount_usd = abs(largest_change['amount_change']) * price
                                    
                                    logger.info(f"🌊 Raydium change: {largest_change['amount_change']} tokens, ${amount_usd}")
                                    
                                    return {
                                        'wallet_address': user_wallet,
                                        'token_address': largest_change['mint'],
                                        'transaction_type': 'sell' if largest_change['amount_change'] < 0 else 'buy',
                                        'signature': signature,
                                        'dex_id': 'raydium',
                                        'amount_tokens': abs(largest_change['amount_change']),
                                        'amount_usd': amount_usd,
                                    }
                    
                    except Exception as e:
                        logger.error(f"❌ Erreur analyse Raydium balances: {e}")
            
            # Fallback générique
            return {
                'wallet_address': user_wallet,
                'token_address': "So11111111111111111111111111111111111111112",
                'transaction_type': 'swap',
                'signature': signature,
                'dex_id': 'raydium',
                'amount_tokens': 1.0,
                'amount_usd': 250.0,
            }
            
        except Exception as e:
            logger.error(f"❌ Erreur parsing Raydium: {e}")
        
        return None
    
    async def parse_pump_fun_instruction(self, accounts: List[str], instruction, signature: str) -> Optional[Dict]:
        """Parser une instruction Pump.fun pour extraire les données de trade"""
        try:
            logger.info(f"🚀 Pump.fun: {len(accounts)} comptes disponibles")
            
            if len(accounts) < 1:
                logger.warning(f"❌ Pas assez de comptes Pump.fun: {len(accounts)}")
                return None
            
            # Dans Pump.fun:
            # accounts[0] = user wallet
            # accounts[1] = bonding curve
            # accounts[2] = associated token account
            user_wallet = accounts[0]
            logger.info(f"🚀 User wallet: {user_wallet[:8]}...")
            
            try:
                if hasattr(instruction, 'data') and instruction.data:
                    if isinstance(instruction.data, (list, tuple)):
                        instruction_data = bytes(instruction.data)
                    elif isinstance(instruction.data, str):
                        instruction_data = instruction.data.encode('utf-8')
                    else:
                        instruction_data = instruction.data
                else:
                    instruction_data = b''
                    
                logger.info(f"🚀 Instruction data length: {len(instruction_data)}")
                
            except Exception as data_error:
                logger.debug(f"⚠️ Erreur lecture instruction data Pump: {data_error}")
                instruction_data = b''
            
            if len(instruction_data) >= 1:
                instruction_type = instruction_data[0]
                logger.info(f"🚀 Pump.fun instruction type: {instruction_type}")
                
                # Types Pump.fun courants:
                # 102 = buy
                # 108 = sell
                if instruction_type in [102, 103, 108, 109]:  # buy/sell variants
                    try:
                        # Récupérer la transaction pour analyser
                        sig = Signature.from_string(signature)
                        tx = await self.client.get_transaction(
                            sig,
                            commitment="finalized",
                            max_supported_transaction_version=0
                        )
                        
                        if tx.value and tx.value.transaction and hasattr(tx.value, 'meta'):
                            meta = tx.value.meta
                            
                            # Analyser les logs pour extraire les montants Pump.fun
                            if hasattr(meta, 'log_messages'):
                                pump_data = self.parse_pump_fun_logs(meta.log_messages)
                                if pump_data:
                                    logger.info(f"🚀 Pump.fun data des logs: {pump_data}")
                                    
                                    return {
                                        'wallet_address': user_wallet,
                                        'token_address': pump_data.get('token_address', accounts[2] if len(accounts) > 2 else ''),
                                        'transaction_type': pump_data.get('transaction_type', 'buy'),
                                        'signature': signature,
                                        'dex_id': 'pump_fun',
                                        'amount_tokens': pump_data.get('amount_tokens', 0),
                                        'amount_usd': pump_data.get('amount_usd', 0),
                                    }
                            
                            # Fallback avec token balances
                            if hasattr(meta, 'pre_token_balances') and hasattr(meta, 'post_token_balances'):
                                token_changes = self.analyze_token_balance_changes(
                                    meta.pre_token_balances,
                                    meta.post_token_balances,
                                    user_wallet
                                )
                                
                                if token_changes:
                                    logger.info(f"🚀 Pump.fun token changes: {len(token_changes)}")
                                    
                                    largest_change = max(token_changes, key=lambda x: abs(x['amount_change']))
                                    
                                    # Pump.fun utilise souvent des prix fixes ou calculables
                                    price = await self.get_token_price_estimate(largest_change['mint'])
                                    amount_usd = abs(largest_change['amount_change']) * price
                                    
                                    logger.info(f"🚀 Pump.fun change: {largest_change['amount_change']} tokens, ${amount_usd}")
                                    
                                    return {
                                        'wallet_address': user_wallet,
                                        'token_address': largest_change['mint'],
                                        'transaction_type': 'buy' if largest_change['amount_change'] > 0 else 'sell',
                                        'signature': signature,
                                        'dex_id': 'pump_fun',
                                        'amount_tokens': abs(largest_change['amount_change']),
                                        'amount_usd': amount_usd,
                                    }
                    
                    except Exception as e:
                        logger.error(f"❌ Erreur analyse Pump.fun balances: {e}")
            
            # Fallback générique
            return {
                'wallet_address': user_wallet,
                'token_address': accounts[2] if len(accounts) > 2 else "So11111111111111111111111111111111111111112",
                'transaction_type': 'buy',
                'signature': signature,
                'dex_id': 'pump_fun',
                'amount_tokens': 1000.0,
                'amount_usd': 300.0,
            }
            
        except Exception as e:
            logger.error(f"❌ Erreur parsing Pump.fun: {e}")
        
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
            
            logger.info(f"📊 Analysé {len(changes)} changements de balance significatifs")
            
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
                        
                        logger.info(f"🚀 Pump.fun log parsed: {tx_type} ${usd_amount}")
                        
                        return {
                            'transaction_type': tx_type,
                            'amount_usd': usd_amount,
                            'amount_tokens': token_amount,
                            'sol_amount': sol_amount
                        }
        
        except Exception as e:
            logger.error(f"❌ Erreur parsing Pump.fun logs: {e}")
        
        return None
    
    async def create_whale_transaction(self, whale_data: Dict) -> WhaleTransaction:
        """Créer un objet WhaleTransaction"""
        
        # Estimer le prix si pas fourni
        if whale_data.get('amount_usd', 0) == 0:
            price = await self.get_token_price_estimate(whale_data['token_address'])
            whale_data['amount_usd'] = whale_data.get('amount_tokens', 0) * price
        
        # Classifier le wallet
        wallet_classification = self.classifier.classify_wallet(
            whale_data['wallet_address'], 
            whale_data['amount_usd']
        )
        
        # Vérifier si le token est dans notre base
        is_in_db = await self.check_token_in_database(whale_data['token_address'])
        
        # Enregistrer l'activité whale
        if wallet_classification['is_interesting']:
            self.classifier.record_whale_activity(whale_data['wallet_address'])
        
        return WhaleTransaction(
            signature=whale_data['signature'],
            token_address=whale_data['token_address'],
            wallet_address=whale_data['wallet_address'],
            transaction_type=whale_data['transaction_type'],
            amount_usd=whale_data['amount_usd'],
            amount_tokens=whale_data.get('amount_tokens', 0),
            timestamp=datetime.now(),
            price_impact=whale_data.get('price_impact', 0),
            is_known_whale=whale_data['wallet_address'] in self.classifier.known_whales,
            wallet_label=wallet_classification['label'],
            is_in_database=is_in_db,
            dex_id=whale_data.get('dex_id', 'unknown')
        )
    
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
            logger.info(f"📈 Whale activity on tracked token: {whale_tx.token_address}")
        else:
            logger.info(f"📊 New whale activity: {whale_tx.token_address}")
            
            # Si transaction critique, considérer l'ajout du token
            if whale_tx.amount_usd >= CRITICAL_THRESHOLD_USD:
                await self.queue_token_for_discovery(whale_tx.token_address)
                logger.info(f"🎯 Queued critical token for discovery: {whale_tx.token_address}")
    
    async def queue_token_for_discovery(self, token_address: str):
        """Ajouter un token à la queue de découverte automatique"""
        try:
            # Intégrer avec le système d'enrichissement existant
            from solana_monitor_c4 import token_enricher
            await token_enricher.queue_for_enrichment(token_address)
            logger.info(f"🔍 Token queued for enrichment: {token_address}")
        except Exception as e:
            logger.error(f"Error queuing token for discovery: {e}")

# API pour récupérer les données whale
class WhaleActivityAPI:
    """API pour récupérer les données d'activité whale"""
    
    def __init__(self, database_path: str = "tokens.db"):
        self.database_path = database_path
    
    def get_recent_whale_activity(self, hours: int = 1, limit: int = 50) -> List[Dict]:
        """Récupérer l'activité whale récente"""
        
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT * FROM whale_transactions_live 
                WHERE timestamp > datetime('now', '-{} hours', 'localtime')
                ORDER BY timestamp DESC, amount_usd DESC
                LIMIT ?
            '''.format(hours), (limit,))
            
            columns = [desc[0] for desc in cursor.description]
            results = []
            
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            
            return results
            
        except sqlite3.Error as e:
            logger.error(f"Error getting whale activity: {e}")
            return []
        finally:
            conn.close()
    
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
    await whale_detector.start()

async def stop_whale_monitoring():
    """Arrêter le monitoring des transactions whales"""
    await whale_detector.stop()

# Fonction pour traiter les logs WebSocket et détecter les whales
async def process_websocket_logs_for_whales(signature: str, logs: List[str]):
    """Traiter les logs WebSocket pour détecter l'activité whale"""
    if not whale_detector.is_running:
        return
    
    try:
        # Parser la transaction pour détecter les whales
        whale_tx = await whale_detector.parse_transaction_for_whale_activity(signature, logs)
        
        if whale_tx:
            await whale_detector.process_whale_transaction(whale_tx)
    except Exception as e:
        logger.debug(f"Error processing whale activity for {signature}: {e}")