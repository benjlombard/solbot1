#!/usr/bin/env python3
"""
Implémentation des vraies transactions Solana avec validations et débug optimisé
"""

import traceback
import asyncio
import logging
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from decimal import Decimal
import aiohttp
import os
from pathlib import Path
import base64
import random

# Imports pour Solana
try:
    from spl.token.instructions import create_associated_token_account
    from solders.message import MessageV0
    from solders.keypair import Keypair
    from solders.message import Message
    from solana.rpc.async_api import AsyncClient
    from solana.rpc.commitment import Confirmed
    from solana.rpc.types import TxOpts, TokenAccountOpts
    from solders.transaction import VersionedTransaction
    from solders.pubkey import Pubkey
    from solders.hash import Hash
    from solders.signature import Signature
    from spl.token.constants import TOKEN_PROGRAM_ID
    from spl.token._layouts import ACCOUNT_LAYOUT
    import base58
    SOLANA_AVAILABLE = True
    print("✅ Solana libraries imported successfully")
except ImportError as e:
    SOLANA_AVAILABLE = False
    print(f"⚠️ Solana libraries not available: {e}")
    print("Install with: pip install solana solders base58")

    # Fallback classes pour éviter les erreurs de définition
    class Keypair:
        @staticmethod
        def from_bytes(data):
            return None
        def pubkey(self):
            return None
        def sign_message(self, msg):
            return None

    class VersionedTransaction:
        @staticmethod
        def from_bytes(data):
            return None
        def sign(self, keypair):
            pass

    class Pubkey:
        def __str__(self):
            return "mock_pubkey"

    class Signature:
        @staticmethod
        def from_string(sig):
            return None

# Charger les variables d'environnement
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✅ Variables d'environnement chargées depuis .env")
except ImportError:
    print("⚠️ python-dotenv non installé, tentative de chargement manuel du .env")
    env_file = Path(".env")
    if env_file.exists():
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()
        print("✅ Variables d'environnement chargées manuellement")

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class TradeConfig:
    """Configuration pour le trading automatique"""
    max_sol_per_trade: float = 0.0001  # Réduit pour les tests
    max_daily_budget: float = 0.01     # Budget quotidien conservateur
    max_simultaneous_positions: int = 2
    min_score_to_buy: float = 60
    min_confidence_level: float = 40
    stop_loss_percentage: float = -40
    take_profit_levels: List[float] = None
    take_profit_portions: List[float] = None
    max_token_age_minutes: int = 10
    price_check_interval_seconds: int = 30
    slippage_bps: int = 100  # Réduit à 2% pour limiter les pertes
    priority_fee_lamports: int = 100  # Frais de priorité par défaut
    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    confirmation_timeout: int = 180  # 2 minutes
    require_manual_confirmation: bool = True

    def __post_init__(self):
        if self.take_profit_levels is None:
            self.take_profit_levels = [100, 300, 500]
        if self.take_profit_portions is None:
            self.take_profit_portions = [0.5, 0.3, 0.2]

@dataclass
class Position:
    """Représente une position de trading"""
    token_address: str
    token_symbol: str
    entry_price: float
    sol_amount: float
    token_amount: float
    entry_time: datetime
    entry_tx_signature: str
    current_price: float = 0.0
    current_value: float = 0.0
    pnl_percentage: float = 0.0
    stop_loss_triggered: bool = False
    take_profits_executed: Dict[int, bool] = None

    def __post_init__(self):
        if self.take_profits_executed is None:
            self.take_profits_executed = {i: False for i in range(3)}

    def update_price(self, new_price: float):
        """Met à jour le prix et calcule le PnL"""
        self.current_price = new_price
        self.current_value = new_price * self.token_amount
        if self.entry_price > 0:
            self.pnl_percentage = ((new_price - self.entry_price) / self.entry_price) * 100

class SolanaClient:
    """Client pour interagir avec Solana"""
    
    def __init__(self, rpc_url: str, private_key: str):
        self.rpc_url = rpc_url
        self.client = None
        self._session_active = False
        try:
            if SOLANA_AVAILABLE:
                private_key_bytes = base58.b58decode(private_key)
                self.keypair = Keypair.from_bytes(private_key_bytes)
                self.public_key = self.keypair.pubkey()
                logger.info(f"🔑 Wallet loaded: {str(self.public_key)[:8]}...{str(self.public_key)[-8:]}")
            else:
                logger.error("Solana libraries not available")
                self.keypair = None
                self.public_key = None
        except Exception as e:
            logger.error(f"Error loading wallet: {e}")
            self.keypair = None
            self.public_key = None

    async def __aenter__(self):
        if SOLANA_AVAILABLE and not self._session_active:
            self.client = AsyncClient(self.rpc_url)
            self._session_active = True
            logger.debug("✅ Solana client session started")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client and self._session_active:
            await self.client.close()
            self._session_active = False
            logger.debug("✅ Solana client session closed")

    async def ensure_client_active(self):
        """Ensure the client is active before making requests"""
        if not self._session_active or not self.client:
            raise RuntimeError("Solana client not active. Use 'async with solana_client' context manager.")

    async def get_balance(self) -> Optional[float]:
        """Obtient le solde SOL du wallet"""
        try:
            await self.ensure_client_active()
            if not self.public_key:
                return None
            response = await self.client.get_balance(self.public_key)
            if response.value:
                balance_lamports = response.value
                balance_sol = balance_lamports / 1e9
                logger.debug(f"💰 Wallet balance: {balance_sol:.6f} SOL")
                return balance_sol
            return None
        except Exception as e:
            logger.error(f"Error getting balance: {e}")
            return None

    async def has_token_account(self, token_mint: str) -> bool:
        """Vérifie si un compte token existe pour un mint donné, avec saisie manuelle si non trouvé"""
        try:
            await self.ensure_client_active()
            mint_pubkey = Pubkey.from_string(token_mint)
            logger.debug(f"Checking token account for mint: {token_mint}")
            response = await self.client.get_token_accounts_by_owner(
                self.public_key,
                TokenAccountOpts(program_id=TOKEN_PROGRAM_ID)
            )
            logger.debug(f"Token accounts response: {response}")
            if not response.value:
                logger.debug(f"No token accounts found for wallet {self.public_key}")
                # Demander à l'utilisateur de saisir manuellement l'adresse du compte de token
                manual_input = input(f"No token account found for mint {token_mint[:8]}... Enter token account address manually (or press Enter to skip): ").strip()
                if not manual_input:
                    logger.debug("User skipped manual input")
                    return False
                # Valider l'adresse saisie
                try:
                    manual_account_pubkey = Pubkey.from_string(manual_input)
                    # Vérifier si le compte existe et appartient au programme de token
                    account_info = await self.client.get_account_info(manual_account_pubkey)
                    if account_info.value is None:
                        logger.error(f"Invalid token account address: {manual_input}")
                        return False
                    # Vérifier que le compte appartient au programme de token
                    if account_info.value.owner != TOKEN_PROGRAM_ID:
                        logger.error(f"Address {manual_input} is not a valid token account")
                        return False
                    # Vérifier que le compte correspond au mint
                    account_data = ACCOUNT_LAYOUT.parse(account_info.value.data)
                    if str(account_data.mint) != str(mint_pubkey):
                        logger.error(f"Token account mint {account_data.mint} does not match requested mint {token_mint}")
                        return False
                    logger.info(f"✅ Manually entered token account {manual_input[:8]}... is valid")
                    return True
                except Exception as e:
                    logger.error(f"Invalid token account address: {e}")
                    return False
            for account in response.value:
                try:
                    account_data = ACCOUNT_LAYOUT.parse(account.account.data)
                    logger.debug(f"Found account with mint: {account_data.mint}")
                    if str(account_data.mint) == str(mint_pubkey):
                        logger.info(f"✅ Token account already exists for {token_mint[:8]}...")
                        return True
                except Exception as e:
                    logger.debug(f"Skipping invalid token account: {e}")
                    continue
            logger.debug(f"No token account found for {token_mint[:8]}...")
            # Demander à l'utilisateur de saisir manuellement si aucun compte n'est trouvé
            manual_input = input(f"No token account found for mint {token_mint[:8]}... Enter token account address manually (or press Enter to skip): ").strip()
            if not manual_input:
                logger.debug("User skipped manual input")
                return False
            try:
                manual_account_pubkey = Pubkey.from_string(manual_input)
                account_info = await self.client.get_account_info(manual_account_pubkey)
                if account_info.value is None:
                    logger.error(f"Invalid token account address: {manual_input}")
                    return False
                if account_info.value.owner != TOKEN_PROGRAM_ID:
                    logger.error(f"Address {manual_input} is not a valid token account")
                    return False
                account_data = ACCOUNT_LAYOUT.parse(account_info.value.data)
                if str(account_data.mint) != str(mint_pubkey):
                    logger.error(f"Token account mint {account_data.mint} does not match requested mint {token_mint}")
                    return False
                logger.info(f"✅ Manually entered token account {manual_input[:8]}... is valid")
                return True
            except Exception as e:
                logger.error(f"Invalid token account address: {e}")
                return False
        except Exception as e:
            logger.error(f"Error checking token account: {e}")
            return False

    async def get_dynamic_priority_fee(self) -> int:
        """Obtenir des frais de priorité dynamiques basés sur les conditions du réseau"""
        try:
            response = await self.client.get_recent_prioritization_fees()
            if response.value:
                avg_fee = sum(fee.prioritization_fee for fee in response.value) // len(response.value)
                return max(100, min(avg_fee, 1000))  # Entre 100 et 1000 lamports
            return 100
        except Exception:
            return 100

    async def simulate_transaction(self, transaction: VersionedTransaction) -> bool:
        """Simule une transaction pour vérifier si elle réussirait"""
        try:
            # Ne pas vérifier ensure_client_active car nous sommes dans un context manager
            # et le client devrait être actif
            if not self.client:
                logger.error("Solana client not initialized")
                return False
                
            logger.debug("Sending transaction simulation request...")
            response = await self.client.simulate_transaction(transaction, commitment=Confirmed)
            
            if response.value.err:
                logger.error(f"Simulation failed: {response.value.err}")
                return False
                
            logger.debug("✅ Transaction simulation successful")
            return True
            
        except Exception as e:
            logger.error(f"Error simulating transaction: {e}")
            return False

    async def send_transaction(self, transaction: VersionedTransaction) -> Optional[str]:
        """Envoie une transaction avec gestion d'erreurs détaillée"""
        try:
            await self.ensure_client_active()
            if not self.keypair:
                logger.error("Solana keypair not available")
                return None

            logger.info("📡 Sending transaction to Solana...")
            opts = TxOpts(skip_preflight=False, preflight_commitment=Confirmed)
            response = await self.client.send_transaction(transaction, opts=opts)

            if response.value:
                tx_signature = str(response.value)
                logger.info(f"✅ Transaction sent: {tx_signature}")
                return tx_signature
            else:
                logger.error("Failed to send transaction - no response value")
                return None

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error sending transaction: {error_msg}")
            if "insufficient lamports" in error_msg.lower():
                logger.error("💸 INSUFFICIENT FUNDS")
                logger.error("💡 Add more SOL to your wallet")
            elif "blockhash not found" in error_msg.lower():
                logger.error("⏰ Transaction expired (blockhash too old)")
            elif "already processed" in error_msg.lower():
                logger.warning("⚠️ Transaction may have already been processed")
            return None

    async def confirm_transaction(self, signature: str, timeout: int = 60) -> bool:
        """Confirme qu'une transaction a été processée"""
        try:
            await self.ensure_client_active()
            logger.info(f"⏳ Waiting for transaction confirmation: {signature[:8]}...")
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                response = await self.client.get_signature_statuses([Signature.from_string(signature)])
                if response.value and response.value[0]:
                    status = response.value[0]
                    if status.confirmation_status:
                        logger.info(f"✅ Transaction confirmed: {signature[:8]}...")
                        return True
                    elif status.err:
                        logger.error(f"❌ Transaction failed: {status.err}")
                        return False
                await asyncio.sleep(2)
                
            logger.warning(f"⏰ Transaction confirmation timeout: {signature[:8]}...")
            return False
        except Exception as e:
            logger.error(f"Error confirming transaction: {e}")
            return False

class JupiterClient:
    """Client pour interagir avec Jupiter API"""
    
    def __init__(self):
        self.base_url = "https://quote-api.jup.ag/v6"
        self.session = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def get_quote(self, input_mint: str, output_mint: str, amount: int, slippage_bps: int = 200) -> Optional[Dict]:
        """Obtient un devis de Jupiter"""
        try:
            url = f"{self.base_url}/quote"
            params = {
                "inputMint": input_mint,
                "outputMint": output_mint,
                "amount": amount,
                "slippageBps": slippage_bps,
                "onlyDirectRoutes": "false",
                "asLegacyTransaction": "false"
            }
            logger.debug(f"🔍 Getting Jupiter quote: {amount} {input_mint[:8]}... → {output_mint[:8]}...")
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    quote = await response.json()
                    logger.debug(f"✅ Quote received: {quote.get('outAmount', 0)} tokens")
                    return quote
                else:
                    logger.error(f"Jupiter quote failed: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Error getting Jupiter quote: {e}")
            return None

    async def get_swap_transaction(self, quote: Dict, user_public_key: str, priority_fee_lamports: int = 100) -> Optional[Dict]:
        """Obtient la transaction de swap depuis Jupiter"""
        try:
            url = f"{self.base_url}/swap"
            payload = {
                "quoteResponse": quote,
                "userPublicKey": user_public_key,
                "wrapAndUnwrapSol": True,
                "computeUnitPriceMicroLamports": priority_fee_lamports,
                "asLegacyTransaction": False
            }
            logger.debug("🔄 Getting swap transaction from Jupiter...")
            async with self.session.post(url, json=payload) as response:
                if response.status == 200:
                    swap_data = await response.json()
                    logger.debug("✅ Swap transaction received")
                    return swap_data
                else:
                    error_text = await response.text()
                    logger.error(f"Jupiter swap transaction failed: {response.status} - {error_text}")
                    if response.status == 429:
                        logger.error("💡 Rate limit reached, try again later")
                    elif response.status == 400:
                        logger.error("💡 Invalid request, check token addresses and parameters")
                    return None
        except Exception as e:
            logger.error(f"Error getting swap transaction: {e}")
            return None

def ask_user_confirmation(operation: str, details: Dict) -> bool:
    """Demande confirmation à l'utilisateur avant d'exécuter une transaction"""
    print("\n" + "="*60)
    print(f"🚨 CONFIRMATION REQUIRED: {operation}")
    print("="*60)
    for key, value in details.items():
        print(f"  {key}: {value}")
    print("="*60)
    print("⚠️  This will execute a REAL transaction on Solana mainnet")
    print("⚠️  Make sure you understand what you're doing")
    print("⚠️  This operation cannot be undone")
    print("="*60)
    while True:
        response = input("Do you want to proceed? (yes/no): ").lower().strip()
        if response in ['yes', 'y']:
            return True
        elif response in ['no', 'n']:
            return False
        else:
            print("Please answer 'yes' or 'no'")

class AutoTrader:
    """Système de trading automatique avec vraies transactions"""
    
    def __init__(self, config: TradeConfig, wallet_private_key: str = None):
        self.config = config
        self.wallet_private_key = wallet_private_key
        self.positions: Dict[str, Position] = {}
        self.daily_spent = 0.0
        self.daily_trades = 0
        self.last_reset_date = datetime.now().date()
        self.SOL_MINT = "So11111111111111111111111111111111111111112"
        self.is_running = False
        self.monitoring_task = None
        self.solana_client = None

    async def initialize_solana_client(self):
        """Initialise le client Solana"""
        if self.wallet_private_key and SOLANA_AVAILABLE:
            self.solana_client = SolanaClient(self.config.solana_rpc_url, self.wallet_private_key)
            logger.info("🔗 Solana client initialized")
        else:
            logger.warning("⚠️ Solana client not available - running in simulation mode")

    async def can_afford_trade(self, sol_amount: float, account_creation_cost: float) -> tuple[bool, str, dict]:
        """Vérifie si le wallet peut se permettre un trade"""
        try:
            if not self.solana_client:
                return False, "Solana client not available", {}
            async with self.solana_client as solana:
                balance = await solana.get_balance()
                if balance is None:
                    return False, "Could not retrieve balance", {}
                priority_fee = await solana.get_dynamic_priority_fee()
                costs = {
                    "swap_amount": sol_amount,
                    "transaction_fees": 0.0005,
                    "account_creation": account_creation_cost,
                    "priority_fees": priority_fee / 1e9,
                    "safety_buffer": 0.0005
                }
                total_needed = sum(costs.values())
                available_after = balance - total_needed
                costs["total_needed"] = total_needed
                costs["current_balance"] = balance
                costs["available_after"] = available_after
                if balance < total_needed:
                    deficit = total_needed - balance
                    return False, f"Insufficient balance: need {deficit:.6f} more SOL", costs
                if available_after < 0.0003:
                    return False, f"Would leave only {available_after:.6f} SOL (too low)", costs
                return True, f"Balance check passed: {available_after:.6f} SOL will remain", costs
        except Exception as e:
            return False, f"Error checking balance: {e}", {}

    def reset_daily_stats_if_needed(self):
        """Remet à zéro les stats quotidiennes si nécessaire"""
        current_date = datetime.now().date()
        if current_date != self.last_reset_date:
            self.daily_spent = 0.0
            self.daily_trades = 0
            self.last_reset_date = current_date
            logger.info("Daily trading stats reset")

    def can_make_trade(self, sol_amount: float) -> bool:
        """Vérifie si on peut faire un trade selon les limites"""
        self.reset_daily_stats_if_needed()
        if self.daily_spent + sol_amount > self.config.max_daily_budget:
            logger.warning(f"Daily budget exceeded: {self.daily_spent + sol_amount:.3f} > {self.config.max_daily_budget}")
            return False
        if len(self.positions) >= self.config.max_simultaneous_positions:
            logger.warning(f"Maximum positions reached: {len(self.positions)}")
            return False
        if sol_amount > self.config.max_sol_per_trade:
            logger.warning(f"Trade amount too large: {sol_amount} > {self.config.max_sol_per_trade}")
            return False
        return True

    def calculate_investment_amount(self, score: float, confidence: float) -> float:
        """Calcule le montant à investir selon le score et la confiance"""
        base_amount = self.config.max_sol_per_trade
        if score >= 80 and confidence >= 70:
            return base_amount
        elif score >= 70 and confidence >= 50:
            return base_amount * 0.75
        elif score >= 60 and confidence >= 40:
            return base_amount * 0.5
        return 0

    async def should_buy_token(self, token_data: Dict, score: float, confidence: float) -> bool:
        """Détermine si on doit acheter un token"""
        try:
            if 'created_at' in token_data:
                created_at = datetime.fromisoformat(token_data['created_at'].replace('Z', '+00:00'))
                age_minutes = (datetime.now() - created_at.replace(tzinfo=None)).total_seconds() / 60
                if age_minutes > self.config.max_token_age_minutes:
                    logger.debug(f"Token too old: {age_minutes:.1f} minutes")
                    return False
            if token_data['address'] in self.positions:
                return False
            if confidence < self.config.min_confidence_level:
                logger.debug(f"Confidence too low: {confidence} < {self.config.min_confidence_level}")
                return False
            if score < self.config.min_score_to_buy:
                logger.debug(f"Score too low: {score} < {self.config.min_score_to_buy}")
                return False
            investment_amount = self.calculate_investment_amount(score, confidence)
            if investment_amount <= 0:
                return False
            if not self.can_make_trade(investment_amount):
                return False
            return True
        except Exception as e:
            logger.error(f"Error in should_buy_token: {e}")
            return False

    

    def debug_transaction_info(self, transaction, keypair=None):
        """Debug helper to understand transaction structure"""
        logger.info("🔍 TRANSACTION DEBUG INFO:")
        logger.info(f"  Transaction type: {type(transaction)}")
        logger.info(f"  Transaction dir: {[attr for attr in dir(transaction) if not attr.startswith('_')]}")
        
        if hasattr(transaction, 'message'):
            message = transaction.message
            logger.info(f"  Message type: {type(message)}")
            logger.info(f"  Message dir: {[attr for attr in dir(message) if not attr.startswith('_')]}")
            
            if hasattr(message, 'header'):
                logger.info(f"  Header: {message.header}")
                
            if hasattr(message, 'account_keys'):
                logger.info(f"  Account keys count: {len(message.account_keys)}")
                logger.info(f"  Account keys: {[str(key)[:8] + '...' for key in message.account_keys[:3]]}")
                
            if hasattr(message, 'recent_blockhash'):
                logger.info(f"  Recent blockhash: {str(message.recent_blockhash)[:8]}...")
                
            if hasattr(message, 'instructions'):
                logger.info(f"  Instructions count: {len(message.instructions)}")
        
        if hasattr(transaction, 'signatures'):
            logger.info(f"  Signatures count: {len(transaction.signatures)}")
            logger.info(f"  Signatures: {[str(sig)[:8] + '...' if sig else 'None' for sig in transaction.signatures[:3]]}")
        
        if keypair:
            logger.info(f"  Wallet pubkey: {str(keypair.pubkey())[:8]}...")
            
            # Check if wallet is in account keys
            if hasattr(transaction, 'message') and hasattr(transaction.message, 'account_keys'):
                wallet_in_accounts = str(keypair.pubkey()) in [str(key) for key in transaction.message.account_keys]
                logger.info(f"  Wallet in account keys: {wallet_in_accounts}")


    async def create_token_account_if_needed(self, solana: SolanaClient, token_mint: str) -> Optional[Pubkey]:
        """Create an associated token account if none exists"""
        try:
            mint_pubkey = Pubkey.from_string(token_mint)
            has_account = await solana.has_token_account(token_mint)
            if has_account:
                logger.info(f"✅ Token account already exists for mint: {token_mint[:8]}...")
                return None  # Account already exists

            logger.info(f"Creating associated token account for mint: {token_mint[:8]}...")
            ata = Pubkey.find_program_address(
                seeds=[
                    bytes(solana.public_key),
                    bytes(TOKEN_PROGRAM_ID),
                    bytes(mint_pubkey)
                ],
                program_id=TOKEN_PROGRAM_ID
            )[0]
            
            # Create instruction for associated token account
            instruction = create_associated_token_account(
                payer=solana.public_key,
                owner=solana.public_key,
                mint=mint_pubkey
            )
            
            # Build transaction
            recent_blockhash = (await solana.client.get_latest_blockhash()).value.blockhash
            message = MessageV0.try_compile(
                payer=solana.public_key,
                instructions=[instruction],
                address_lookup_table_accounts=[],
                recent_blockhash=recent_blockhash
            )
            transaction = VersionedTransaction(message, [solana.keypair])
            
            # Simulate and send transaction
            if await solana.simulate_transaction(transaction):
                tx_signature = await solana.send_transaction(transaction)
                if tx_signature and await solana.confirm_transaction(tx_signature):
                    logger.info(f"✅ Created token account: {str(ata)[:8]}...")
                    return ata
            logger.error("Failed to create token account")
            return None
        except Exception as e:
            logger.error(f"Error creating token account: {e}")
            return None

    async def execute_buy_order(self, token_address: str, token_symbol: str, sol_amount: float) -> Optional[Position]:
        """Exécute un ordre d'achat avec vraies transactions"""
        try:
            logger.info(f"🔥 EXECUTING BUY ORDER: {sol_amount:.3f} SOL → {token_symbol} ({token_address[:8]}...)")
            
            if not self.wallet_private_key or not SOLANA_AVAILABLE:
                logger.error("Running in simulation mode")
                return await self._execute_simulated_buy(token_address, token_symbol, sol_amount)
            
            if not self.solana_client:
                await self.initialize_solana_client()
            
            async with JupiterClient() as jupiter, self.solana_client as solana:
                # Check token account and create if needed
                ata = await self.create_token_account_if_needed(solana, token_address)
                if not ata and not await solana.has_token_account(token_address):
                    logger.error("No token account available and failed to create one")
                    return None

                account_creation_cost = 0.0 if await solana.has_token_account(token_address) else 0.002035

                #check balance
                can_afford, balance_msg, cost_breakdown = await self.can_afford_trade(sol_amount, account_creation_cost)
                
                logger.info(f"💰 Balance Analysis:")
                for key, value in cost_breakdown.items():
                    logger.info(f"  {key}: {value:.6f} SOL")
                
                if not can_afford:
                    logger.error(f"❌ {balance_msg}")
                    return None
                
                logger.info(f"✅ {balance_msg}")
                
                # Prepare trade parameters
                sol_lamports = int(sol_amount * 1e9)
                if sol_lamports < 1000:
                    logger.error(f"Amount too small: {sol_amount:.9f} SOL")
                    return None
                
                # Get quote from Jupiter
                quote = await jupiter.get_quote(
                    input_mint=self.SOL_MINT,
                    output_mint=token_address,
                    amount=sol_lamports,
                    slippage_bps=self.config.slippage_bps
                )
                
                if not quote:
                    logger.error("Failed to get quote from Jupiter")
                    return None
                
                # Calculate trade details
                estimated_tokens_raw = int(quote.get('outAmount', 0))
                estimated_tokens = estimated_tokens_raw / 1e6  # À améliorer avec les décimales réelles
                estimated_price = sol_amount / estimated_tokens if estimated_tokens > 0 else 0
                impact_pct = float(quote.get('priceImpactPct', 0))
                
                logger.info(f"📊 Quote Analysis:")
                logger.info(f"  Input: {sol_amount:.6f} SOL")
                logger.info(f"  Output: {estimated_tokens:.0f} {token_symbol}")
                logger.info(f"  Price per token: {estimated_price:.8f} SOL")
                logger.info(f"  Price impact: {impact_pct:.2f}%")
                
                # User confirmation if required
                if self.config.require_manual_confirmation:
                    confirmation_details = {
                        "Operation": "BUY ORDER",
                        "Token": f"{token_symbol} ({token_address[:8]}...)",
                        "SOL Amount": f"{sol_amount:.6f} SOL",
                        "Expected Tokens": f"{estimated_tokens:.0f} {token_symbol}",
                        "Price per Token": f"{estimated_price:.8f} SOL",
                        "Price Impact": f"{impact_pct:.2f}%",
                        "Current Balance": f"{cost_breakdown.get('current_balance', 0):.6f} SOL",
                        "Remaining Balance": f"{cost_breakdown.get('available_after', 0):.6f} SOL"
                    }
                    if not ask_user_confirmation("Token Purchase", confirmation_details):
                        logger.info("User cancelled transaction")
                        return None
                
                # Get priority fee and swap transaction
                priority_fee = await solana.get_dynamic_priority_fee()
                swap_data = await jupiter.get_swap_transaction(
                    quote,
                    str(solana.public_key),
                    priority_fee
                )
                
                if not swap_data:
                    logger.error("Failed to get swap transaction from Jupiter")
                    return None
                
                # Parse and prepare transaction
                transaction_bytes = base64.b64decode(swap_data.get('swapTransaction'))
                transaction = VersionedTransaction.from_bytes(transaction_bytes)
                
                # DEBUG: Analyze transaction structure
                logger.info("🔧 DEBUG: Analyzing transaction before signing...")
                self.debug_transaction_info(transaction, solana.keypair)
                
                # Sign the transaction
                logger.info("✍️ Signing transaction with wallet keypair...")
                try:
                    # Get the raw message bytes for signing
                    message_bytes = bytes(transaction.message)
                    logger.info(f"  Signing {len(message_bytes)} message bytes...")
                    
                    # Sign the message bytes
                    signature = solana.keypair.sign_message(message_bytes)
                    logger.info(f"  Generated signature: {str(signature)[:8]}...")
                    
                    if not signature:
                        logger.error("Failed to generate signature")
                        return None
                    
                    # Update the transaction with the new signature
                    transaction.signatures = [signature]
                    logger.info("✅ Transaction signed successfully")
                    
                    # Verify the signature
                    if transaction.signatures and transaction.signatures[0] and str(transaction.signatures[0]) != "11111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111":
                        logger.info(f"  Verified signature in transaction: {str(transaction.signatures[0])[:8]}...")
                    else:
                        logger.error("  WARNING: Signature verification failed - transaction may still have placeholder")
                    
                    # DEBUG: Analyze signed transaction
                    logger.info("🔧 DEBUG: Analyzing signed transaction...")
                    self.debug_transaction_info(transaction, solana.keypair)
                    
                except Exception as signing_error:
                    logger.error(f"Transaction signing failed: {signing_error}")
                    logger.error(f"Full signing error: {traceback.format_exc()}")
                    return None
                
                # Simulate transaction BEFORE sending
                logger.info("🔍 Simulating transaction...")
                simulation_success = await solana.simulate_transaction(transaction)
                if not simulation_success:
                    logger.error("❌ Transaction simulation failed")
                    return None
                
                logger.info("✅ Transaction simulation passed")
                
                # Send transaction
                logger.info("📡 Sending transaction to Solana network...")
                tx_signature = await solana.send_transaction(transaction)
                if not tx_signature:
                    logger.error("❌ Failed to send transaction")
                    return None
                
                # Confirm transaction
                logger.info(f"⏳ Confirming transaction: {tx_signature[:8]}...")
                confirmation_start = time.time()
                
                if await solana.confirm_transaction(tx_signature, self.config.confirmation_timeout):
                    confirmation_time = time.time() - confirmation_start
                    logger.info(f"✅ Transaction confirmed in {confirmation_time:.1f}s")
                    
                    # Create position
                    position = Position(
                        token_address=token_address,
                        token_symbol=token_symbol,
                        entry_price=estimated_price,
                        sol_amount=sol_amount,
                        token_amount=estimated_tokens,
                        entry_time=datetime.now(),
                        entry_tx_signature=tx_signature
                    )
                    
                    # Update trader state
                    self.positions[token_address] = position
                    self.daily_spent += sol_amount
                    self.daily_trades += 1
                    
                    logger.info(f"🎉 BUY ORDER CONFIRMED!")
                    logger.info(f"   Token: {estimated_tokens:.0f} {token_symbol}")
                    logger.info(f"   Cost: {sol_amount:.6f} SOL")
                    logger.info(f"   Price: {estimated_price:.8f} SOL per token")
                    logger.info(f"   TX: {tx_signature}")
                    logger.info(f"   Explorer: https://solscan.io/tx/{tx_signature}")
                    
                    return position
                else:
                    logger.error("❌ Transaction confirmation failed or timed out")
                    logger.error(f"   Check transaction status: https://solscan.io/tx/{tx_signature}")
                    return None
                                
        except Exception as e:
            logger.error(f"Error in execute_buy_order: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return None

    async def _execute_simulated_buy(self, token_address: str, token_symbol: str, sol_amount: float) -> Optional[Position]:
        """Exécute un achat simulé"""
        logger.info("🎭 Executing simulated buy order...")
        position = Position(
            token_address=token_address,
            token_symbol=token_symbol,
            entry_price=0.001,
            sol_amount=sol_amount,
            token_amount=sol_amount * 1000,
            entry_time=datetime.now(),
            entry_tx_signature=f"sim_{int(time.time())}"
        )
        self.positions[token_address] = position
        self.daily_spent += sol_amount
        self.daily_trades += 1
        logger.info(f"✅ SIMULATED BUY: {position.token_amount:.0f} {token_symbol} for {sol_amount:.3f} SOL")
        return position

    async def execute_sell_order(self, position: Position, percentage: float, reason: str) -> bool:
        """Exécute un ordre de vente"""
        try:
            tokens_to_sell = position.token_amount * percentage
            estimated_sol = tokens_to_sell * position.current_price
            logger.info(f"🔴 EXECUTING SELL ORDER: {tokens_to_sell:.0f} {position.token_symbol} → {estimated_sol:.3f} SOL ({reason})")
            position.token_amount -= tokens_to_sell
            logger.info(f"✅ SIMULATED SELL: {tokens_to_sell:.0f} tokens for ~{estimated_sol:.3f} SOL")
            if position.token_amount <= 0:
                del self.positions[position.token_address]
                logger.info(f"Position closed for {position.token_symbol}")
            return True
        except Exception as e:
            logger.error(f"Error executing sell order: {e}")
            return False

    async def monitor_position(self, position: Position):
        """Surveille une position et exécute les ordres de sortie"""
        try:
            price_change = random.uniform(-0.1, 0.1)
            new_price = position.entry_price * (1 + price_change)
            position.update_price(new_price)
            logger.debug(f"📊 {position.token_symbol}: {position.pnl_percentage:+.1f}% | Price: {position.current_price:.6f}")
            if not position.stop_loss_triggered and position.pnl_percentage <= self.config.stop_loss_percentage:
                logger.warning(f"🛑 STOP-LOSS TRIGGERED: {position.token_symbol} at {position.pnl_percentage:+.1f}%")
                await self.execute_sell_order(position, 1.0, f"Stop-loss {position.pnl_percentage:+.1f}%")
                position.stop_loss_triggered = True
                return
            for i, profit_level in enumerate(self.config.take_profit_levels):
                if not position.take_profits_executed[i] and position.pnl_percentage >= profit_level:
                    portion = self.config.take_profit_portions[i]
                    logger.info(f"🎯 TAKE-PROFIT {i+1}: {position.token_symbol} at {position.pnl_percentage:+.1f}%")
                    await self.execute_sell_order(position, portion, f"Take-profit {profit_level}%")
                    position.take_profits_executed[i] = True
        except Exception as e:
            logger.error(f"Error monitoring position {position.token_symbol}: {e}")

    async def start_monitoring(self):
        """Démarre la surveillance des positions"""
        self.is_running = True
        logger.info("🚀 Starting position monitoring...")
        while self.is_running:
            try:
                if self.positions:
                    logger.debug(f"Monitoring {len(self.positions)} positions...")
                    for position in list(self.positions.values()):
                        await self.monitor_position(position)
                await asyncio.sleep(self.config.price_check_interval_seconds)
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(10)

    def stop_monitoring(self):
        """Arrête la surveillance"""
        self.is_running = False
        logger.info("🛑 Stopping position monitoring...")

    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques du trader"""
        self.reset_daily_stats_if_needed()
        total_positions_value = sum(p.current_value for p in self.positions.values())
        total_pnl = sum(p.current_value - p.sol_amount for p in self.positions.values())
        return {
            "is_running": self.is_running,
            "daily_spent": self.daily_spent,
            "daily_budget_remaining": self.config.max_daily_budget - self.daily_spent,
            "daily_trades": self.daily_trades,
            "active_positions": len(self.positions),
            "max_positions": self.config.max_simultaneous_positions,
            "total_positions_value": total_positions_value,
            "total_pnl": total_pnl,
            "solana_available": SOLANA_AVAILABLE,
            "wallet_configured": self.wallet_private_key is not None,
            "positions": [
                {
                    "token": p.token_symbol,
                    "address": p.token_address[:8] + "...",
                    "entry_price": p.entry_price,
                    "current_price": p.current_price,
                    "pnl_percentage": p.pnl_percentage,
                    "sol_amount": p.sol_amount,
                    "token_amount": p.token_amount,
                    "entry_time": p.entry_time.isoformat(),
                    "tx_signature": p.entry_tx_signature
                }
                for p in self.positions.values()
            ]
        }

def calculate_opportunity_score(token_data: Dict) -> tuple[float, float]:
    """Calcule le score d'opportunité d'un token"""
    score = 50.0
    confidence = 30.0
    market_cap = token_data.get('usd_market_cap', 0)
    if 20000 <= market_cap <= 80000:
        score += 25
        confidence += 20
    if 'created_at' in token_data:
        try:
            created_at = datetime.fromisoformat(token_data['created_at'].replace('Z', '+00:00'))
            age_minutes = (datetime.now() - created_at.replace(tzinfo=None)).total_seconds() / 60
            if age_minutes <= 5:
                score += 20
                confidence += 15
        except:
            pass
    if token_data.get('name') and len(token_data.get('name', '')) > 3:
        score += 5
        confidence += 5
    if token_data.get('description') and len(token_data.get('description', '')) > 50:
        score += 5
        confidence += 5
    return min(score, 100), min(confidence, 100)

async def test_autotrader():
    """Fonction de test pour l'autotrader avec vraies transactions"""
    print("🧪 Testing AutoTrader with REAL transactions...")
    config = TradeConfig(
        max_sol_per_trade=0.0001,
        max_daily_budget=0.01,
        max_simultaneous_positions=2,
        min_score_to_buy=60,
        min_confidence_level=40,
        require_manual_confirmation=True,
        confirmation_timeout=120
    )
    print("🔍 System Check:")
    print(f"  Solana libraries available: {SOLANA_AVAILABLE}")
    if not SOLANA_AVAILABLE:
        print("  Install with: pip install solana solders base58")
    wallet_private_key = os.getenv('WALLET_PRIVATE_KEY')
    print(f"  Wallet private key found: {wallet_private_key is not None}")
    if wallet_private_key:
        print(f"  Key length: {len(wallet_private_key)} characters")
    trader = AutoTrader(config, wallet_private_key=wallet_private_key)
    print(f"  Trader has wallet key: {trader.wallet_private_key is not None}")
    await trader.initialize_solana_client()
    if trader.solana_client and SOLANA_AVAILABLE:
        async with trader.solana_client as solana:
            balance = await solana.get_balance()
            if balance is not None:
                print(f"  Current wallet balance: {balance:.6f} SOL")
                if balance < config.max_sol_per_trade:
                    print(f"  ⚠️ Warning: Balance too low for trading ({balance:.6f} < {config.max_sol_per_trade})")
            else:
                print("  ❌ Could not retrieve wallet balance")
    monitoring_task = asyncio.create_task(trader.start_monitoring())
    try:
        test_tokens = [
            {
                "address": "8kNK1d2XENBREYY3tYuezvYErmwiAg5mntNgYStppump",
                "symbol": "TEST1",
                "name": "Test Token 1",
                "usd_market_cap": 50000,
                "created_at": datetime.now().isoformat(),
                "description": "This is a test token with good fundamentals for testing purposes"
            }
        ]
        print("\n📊 Testing token evaluation...")
        for i, token in enumerate(test_tokens):
            print(f"\n--- Token {i+1}: {token['symbol']} ---")
            score, confidence = calculate_opportunity_score(token)
            print(f"Score: {score:.1f}/100")
            print(f"Confidence: {confidence:.1f}/100")
            should_buy = await trader.should_buy_token(token, score, confidence)
            print(f"Should buy: {should_buy}")
            if should_buy:
                investment_amount = trader.calculate_investment_amount(score, confidence)
                print(f"Investment amount: {investment_amount:.6f} SOL")
                if SOLANA_AVAILABLE and trader.wallet_private_key:
                    print("\n⚠️  ATTENTION: This will execute a REAL transaction!")
                    print("⚠️  Make sure you have enough SOL and understand the risks!")
                    proceed = input(f"\nDo you want to test buying {token['symbol']} with {investment_amount:.6f} SOL? (yes/no): ").lower().strip()
                    if proceed != 'yes':
                        print("❌ Skipping this token")
                        continue
                print(f"\n🚀 Executing buy order for {token['symbol']}...")
                position = await trader.execute_buy_order(
                    token['address'],
                    token['symbol'],
                    investment_amount
                )
                if position:
                    print(f"✅ Position opened: {position.token_symbol}")
                    print(f"   TX Signature: {position.entry_tx_signature}")
                    if not position.entry_tx_signature.startswith('sim_'):
                        print(f"   Solscan: https://solscan.io/tx/{position.entry_tx_signature}")
                else:
                    print("❌ Failed to open position")
                print("\n⏳ Waiting 10 seconds before next token...")
                await asyncio.sleep(10)
        if trader.positions:
            print(f"\n⏳ Running monitoring for 60 seconds...")
            await asyncio.sleep(60)
        else:
            print("\n📊 No positions opened, running brief monitoring...")
            await asyncio.sleep(10)
        stats = trader.get_stats()
        print(f"\n📈 Final Trading Stats:")
        print("="*50)
        print(f"Daily spent: {stats['daily_spent']:.6f} SOL")
        print(f"Daily budget remaining: {stats['daily_budget_remaining']:.6f} SOL")
        print(f"Daily trades: {stats['daily_trades']}")
        print(f"Active positions: {stats['active_positions']}")
        print(f"Total PnL: {stats['total_pnl']:+.6f} SOL")
        print(f"Solana libraries: {'✅' if stats['solana_available'] else '❌'}")
        print(f"Wallet configured: {'✅' if stats['wallet_configured'] else '❌'}")
        if stats['positions']:
            print(f"\n📊 Active Positions:")
            for pos in stats['positions']:
                print(f"  {pos['token']} ({pos['address']})")
                print(f"    PnL: {pos['pnl_percentage']:+.1f}%")
                print(f"    Amount: {pos['token_amount']:.0f} tokens ({pos['sol_amount']:.6f} SOL)")
                print(f"    TX: {pos['tx_signature']}")
                if not pos['tx_signature'].startswith('sim_'):
                    print(f"    Solscan: https://solscan.io/tx/{pos['tx_signature']}")
                print("")
    except KeyboardInterrupt:
        print("\n⏹️ Test interrupted by user")
    except Exception as e:
        logger.error(f"Error in test: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n🏁 Stopping trader...")
        trader.stop_monitoring()
        monitoring_task.cancel()
        try:
            await monitoring_task
        except asyncio.CancelledError:
            pass
        print("✅ Test completed")

if __name__ == "__main__":
    print("AutoTrader REAL Trading Test System")
    print("=" * 60)
    print("⚠️  WARNING: This system can execute REAL transactions")
    print("⚠️  Only use with small amounts you can afford to lose")
    print("⚠️  Trading crypto is extremely risky")
    print("⚠️  This is experimental software - use at your own risk")
    print("=" * 60)
    print("\n🔒 Security Checks:")
    if not SOLANA_AVAILABLE:
        print("❌ Solana libraries not installed")
        print("   Install with: pip install solana solders base58")
        print("   Running in simulation mode only")
    else:
        print("✅ Solana libraries available")
    wallet_key = os.getenv('WALLET_PRIVATE_KEY')
    if not wallet_key:
        print("❌ No wallet private key configured")
        print("   Add WALLET_PRIVATE_KEY to your .env file")
        print("   Running in simulation mode only")
    else:
        print("✅ Wallet private key configured")
    if SOLANA_AVAILABLE and wallet_key:
        print(f"\n🚨 FINAL WARNING:")
        print(f"   This will use your REAL Solana wallet")
        print(f"   Transactions will be executed on MAINNET")
        print(f"   You may LOSE MONEY")
        print(f"   Maximum trade size: 0.0005 SOL")
        print(f"   Daily budget: 0.01 SOL")
        final_confirm = input(f"\nType 'I UNDERSTAND THE RISKS' to continue: ")
        if final_confirm != 'I UNDERSTAND THE RISKS':
            print("❌ Test cancelled for safety")
            exit(1)
        print("✅ Proceeding with real trading test...")
    asyncio.run(test_autotrader())