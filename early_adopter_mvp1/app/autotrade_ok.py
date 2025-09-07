#!/usr/bin/env python3
"""
Implémentation des vraies transactions Solana avec validations et débug optimisé
Support pour mainnet et devnet
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
from enum import Enum

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
    from solders.instruction import Instruction, AccountMeta
    from solders.pubkey import Pubkey
    from solders.address_lookup_table_account import AddressLookupTableAccount
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

# Énumération pour les réseaux
class Network(Enum):
    MAINNET = "mainnet"
    DEVNET = "devnet"



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


# Configuration des réseaux
NETWORK_CONFIGS = {
    Network.MAINNET: {
        "rpc_url": "https://mainnet.helius-rpc.com/?api-key=09fa25c2-61df-44b7-b435-bbd2dbbae0df",  # Replace with your Helius RPC URL
        "jupiter_api": "https://quote-api.jup.ag/v6",
        "explorer_base": "https://solscan.io",
        "name": "Mainnet Beta"
    },
    # Network.MAINNET: {
    #     "rpc_url": "https://api.mainnet-beta.solana.com",
    #     "jupiter_api": "https://quote-api.jup.ag/v6",
    #     "explorer_base": "https://solscan.io",
    #     "name": "Mainnet Beta"
    # },
    Network.DEVNET: {
        "rpc_url": "https://api.devnet.solana.com",
        "jupiter_api": "https://quote-api.jup.ag/v6",  # Jupiter fonctionne aussi sur devnet
        "explorer_base": "https://solscan.io",
        "name": "Devnet"
    }
}

# Configuration du logging
logging.basicConfig(
    level=logging.DEBUG,
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
    slippage_bps: int = 200  # Réduit à 1% pour limiter les pertes
    priority_fee_lamports: int = 100  # Frais de priorité par défaut
    network: Network = Network.DEVNET  # Par défaut sur devnet pour la sécurité
    confirmation_timeout: int = 60  # 3 minutes
    require_manual_confirmation: bool = True
    confirmation_strategy: str = "smart"  # "smart", "basic", "aggressive"
    accept_finalized_after_timeout: bool = True

    def get_confirmation_timeout(self) -> int:
        """Retourne le timeout selon la stratégie"""
        if self.confirmation_strategy == "basic":
            return 15  # Rapide
        elif self.confirmation_strategy == "aggressive":
            return 60  # Plus long
        else:  # smart
            return 30  # Équilibré

    def __post_init__(self):
        if self.take_profit_levels is None:
            self.take_profit_levels = [100, 300, 500]
        if self.take_profit_portions is None:
            self.take_profit_portions = [0.5, 0.3, 0.2]

    @property
    def solana_rpc_url(self) -> str:
        """Retourne l'URL RPC selon le réseau configuré"""
        return NETWORK_CONFIGS[self.network]["rpc_url"]
    
    @property
    def jupiter_api_url(self) -> str:
        """Retourne l'URL de l'API Jupiter selon le réseau"""
        return NETWORK_CONFIGS[self.network]["jupiter_api"]
    
    @property
    def explorer_base_url(self) -> str:
        """Retourne l'URL de base de l'explorateur selon le réseau"""
        return NETWORK_CONFIGS[self.network]["explorer_base"]
    
    @property
    def network_name(self) -> str:
        """Retourne le nom du réseau"""
        return NETWORK_CONFIGS[self.network]["name"]

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
    network: Network
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

    def get_explorer_url(self) -> str:
        """Retourne l'URL de l'explorateur pour cette transaction"""
        base_url = NETWORK_CONFIGS[self.network]["explorer_base"]
        cluster_param = "?cluster=devnet" if self.network == Network.DEVNET else ""
        return f"{base_url}/tx/{self.entry_tx_signature}{cluster_param}"

class SolanaClient:
    """Client pour interagir avec Solana"""
    
    def __init__(self, rpc_url: str, private_key: str, network: Network = Network.DEVNET):
        self.rpc_url = rpc_url
        self.network = network
        self.client = None
        self._context_count = 0  # Track nested context entries
        self._session_active = False
        self.last_balance = None  # Initialize balance caching
        self.last_balance_time = 0  # Initialize balance caching timestamp
        try:
            if SOLANA_AVAILABLE:
                private_key_bytes = base58.b58decode(private_key)
                self.keypair = Keypair.from_bytes(private_key_bytes)
                self.public_key = self.keypair.pubkey()
                logger.info(f"🔑 Wallet loaded: {str(self.public_key)[:8]}...{str(self.public_key)[-8:]} ({network.value})")
                logger.debug(f"Clé publique complète : {self.public_key}")
            else:
                logger.error("Solana libraries not available")
                self.keypair = None
                self.public_key = None
        except Exception as e:
            logger.error(f"Error loading wallet: {e}")
            self.keypair = None
            self.public_key = None

    async def __aenter__(self):
        logger.debug("Entering SolanaClient context...")
        self._context_count += 1
        if self._context_count == 1:  # Only initialize on first entry
            if not self.client:
                self.client = AsyncClient(self.rpc_url)
                logger.debug(f"Client initialized: {self.client}")
            if not await self.client.is_connected():
                logger.error("Failed to connect to Solana RPC")
                raise Exception("Solana client failed to connect")
            logger.debug("Solana client session started (mainnet)")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        logger.debug("Exiting SolanaClient context...")
        self._context_count -= 1
        if self._context_count == 0:  # Only close when all contexts are exited
            if self.client:
                await self.client.close()
                logger.debug("Client closed")
            self.client = None
            logger.debug("Solana client session closed (mainnet)")

    async def load_address_lookup_table(self, account_key: Pubkey) -> Optional[AddressLookupTableAccount]:
        """Load an Address Lookup Table account from the blockchain"""
        try:
            await self.ensure_client_active()
            
            response = await self.client.get_account_info(account_key)
            if not response.value:
                logger.error(f"Address Lookup Table account not found: {account_key}")
                return None
            
            account_info = response.value
            data = account_info.data
            if len(data) < 56:
                logger.error(f"Invalid ALT data length: {len(data)}")
                return None
            
            # Extract addresses (each address is 32 bytes)
            addresses_data = data[56:]  # Skip the 56-byte header
            num_addresses = len(addresses_data) // 32
            
            addresses = []
            for i in range(num_addresses):
                start_idx = i * 32
                end_idx = start_idx + 32
                address_bytes = addresses_data[start_idx:end_idx]
                address = Pubkey(address_bytes)
                addresses.append(address)
            
            logger.debug(f"Loaded ALT {account_key} with {len(addresses)} addresses")
            
            return AddressLookupTableAccount(
                key=account_key,
                addresses=addresses
            )
            
        except Exception as e:
            logger.error(f"Error loading Address Lookup Table {account_key}: {e}")
            return None

    async def ensure_client_active(self):
        logger.debug("Ensuring Solana client is active...")
        if not self.client or not await self.client.is_connected():
            logger.error("Solana client is not active or not initialized")
            raise Exception("Solana client not active. Use 'async with solana_client' context manager.")
        logger.debug("Solana client is active")
        return self.client

    async def get_balance(self) -> Optional[float]:
        try:
            logger.debug("Checking wallet balance...")
            await self.ensure_client_active()
            if not self.public_key:
                logger.error("No public key set for wallet")
                return None
            if self.last_balance is not None and time.time() - self.last_balance_time < 30:
                logger.debug(f"Using cached balance: {self.last_balance:.6f} SOL")
                return self.last_balance
            logger.debug(f"Fetching balance from RPC for {self.public_key}")
            response = await self.client.get_balance(self.public_key)
            logger.debug(f"Balance response: {response}")
            if response.value:
                balance_lamports = response.value
                balance_sol = balance_lamports / 1e9
                self.last_balance = balance_sol
                self.last_balance_time = time.time()
                logger.debug(f"💰 Wallet balance: {balance_sol:.6f} SOL ({self.network.value})")
                return balance_sol
            logger.error("No balance value in response")
            return None
        except Exception as e:
            logger.error(f"Error getting balance: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return None

    async def request_devnet_airdrop(self, sol_amount: float = 1.0) -> Optional[str]:
        """Demande un airdrop de SOL sur devnet"""
        if self.network != Network.DEVNET:
            logger.error("Airdrop only available on devnet")
            return None
        
        try:
            await self.ensure_client_active()
            if not self.public_key:
                logger.error("No public key available for airdrop")
                return None
            
            lamports = int(sol_amount * 1e9)
            logger.info(f"🪂 Requesting {sol_amount} SOL airdrop on devnet...")
            
            response = await self.client.request_airdrop(self.public_key, lamports)
            if response.value:
                tx_signature = str(response.value)
                logger.info(f"✅ Airdrop requested: {tx_signature}")
                
                # Attendre la confirmation
                if await self.confirm_transaction(tx_signature):
                    logger.info(f"✅ Airdrop confirmed: {sol_amount} SOL added to wallet")
                    return tx_signature
                else:
                    logger.error("❌ Airdrop confirmation failed")
                    return None
            else:
                logger.error("❌ Airdrop request failed")
                return None
                
        except Exception as e:
            logger.error(f"Error requesting airdrop: {e}")
            return None

    async def has_token_account(self, token_mint: str) -> Optional[Pubkey]:
        """Vérifie si un compte token existe pour un mint donné, retourne l'adresse du compte ou None."""
        try:
            await self.ensure_client_active()
            mint_pubkey = Pubkey.from_string(token_mint)
            logger.debug(f"Checking token account for mint: {token_mint} and wallet: {self.public_key}")
            
            # Check cache first
            if token_mint in self.known_atas:
                ata_address = self.known_atas[token_mint]
                logger.info(f"✅ Found cached token account for mint {token_mint[:8]}...")
                logger.info(f"==================== FULL ATA ADDRESS ====================")
                logger.info(f"ATA: {ata_address}")
                logger.info(f"========================================================")
                return Pubkey.from_string(ata_address)

            for attempt in range(2):  # Reduced to 2 retries
                try:
                    response = await self.client.get_token_accounts_by_owner(
                        self.public_key,
                        TokenAccountOpts(program_id=TOKEN_PROGRAM_ID)
                    )
                    logger.debug(f"Token accounts response (attempt {attempt + 1}): {response}")
                    if not response.value:
                        logger.debug(f"No token accounts found for wallet {self.public_key}")
                    else:
                        for account in response.value:
                            try:
                                account_data = ACCOUNT_LAYOUT.parse(account.account.data)
                                logger.debug(f"Found account with mint: {account_data.mint}, pubkey: {account.pubkey}")
                                if str(account_data.mint) == str(mint_pubkey):
                                    ata_address = str(account.pubkey)
                                    logger.info(f"✅ Token account found for mint {token_mint[:8]}...")
                                    logger.info(f"==================== FULL ATA ADDRESS ====================")
                                    logger.info(f"ATA: {ata_address}")
                                    logger.info(f"========================================================")
                                    self.known_atas[token_mint] = ata_address  # Cache the ATA
                                    return account.pubkey
                            except Exception as e:
                                logger.debug(f"Skipping invalid token account: {e}")
                                continue
                    if attempt < 1:
                        logger.debug(f"Retrying token account check (attempt {attempt + 2}/2)")
                        await asyncio.sleep(1)
                except Exception as e:
                    logger.error(f"Error checking token account (attempt {attempt + 1}): {e}")
                    if attempt == 1:
                        raise
                    await asyncio.sleep(1)
            logger.debug(f"No token account found for {token_mint[:8]}... after retries")
            manual_input = input(f"No token account found for mint {token_mint[:8]}... Enter token account address manually (or press Enter to skip): ").strip()
            if not manual_input:
                logger.debug("User skipped manual input")
                return None
            try:
                manual_account_pubkey = Pubkey.from_string(manual_input)
                account_info = await self.client.get_account_info(manual_account_pubkey)
                if account_info.value is None:
                    logger.error(f"Invalid token account address: {manual_input}")
                    return None
                if account_info.value.owner != TOKEN_PROGRAM_ID:
                    logger.error(f"Address {manual_input} is not a valid token account")
                    return None
                account_data = ACCOUNT_LAYOUT.parse(account_info.value.data)
                if str(account_data.mint) != str(mint_pubkey):
                    logger.error(f"Token account mint {account_data.mint} does not match requested mint {token_mint}")
                    return None
                logger.info(f"✅ Manually entered token account for mint {token_mint[:8]}...")
                logger.info(f"==================== FULL ATA ADDRESS ====================")
                logger.info(f"ATA: {manual_input}")
                logger.info(f"========================================================")
                self.known_atas[token_mint] = manual_input  # Cache the manual ATA
                return manual_account_pubkey
            except Exception as e:
                logger.error(f"Invalid token account address: {e}")
                return None
        except Exception as e:
            logger.error(f"Error checking token account: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return None

    async def get_dynamic_priority_fee(self) -> int:
        """Obtenir des frais de priorité dynamiques basés sur les conditions du réseau"""
        try:
            response = await self.client.get_recent_prioritization_fees()
            if response.value:
                avg_fee = sum(fee.prioritization_fee for fee in response.value) // len(response.value)
                # Ajuster les frais selon le réseau
                if self.network == Network.DEVNET:
                    return max(50, min(avg_fee, 500))  # Plus bas sur devnet
                else:
                    return max(100, min(avg_fee, 1000))  # Standard sur mainnet
            return 50 if self.network == Network.DEVNET else 100
        except Exception:
            return 50 if self.network == Network.DEVNET else 100

    async def simulate_transaction(self, transaction: VersionedTransaction) -> bool:
        try:
            logger.debug("Starting transaction simulation...")
            logger.debug("Solana client active (verified by context manager)")
            await self.ensure_client_active()
            logger.debug(f"Simulating transaction: {transaction}")
            simulation_response = await self.client.simulate_transaction(transaction)
            logger.debug(f"Simulation response: {simulation_response}")
            if simulation_response.value.err:
                logger.error(f"Simulation failed with error: {simulation_response.value.err}")
                return False
            logger.debug("Simulation successful")
            return True
        except Exception as e:
            logger.error(f"Error simulating transaction: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return False

    async def send_transaction(self, transaction: VersionedTransaction) -> Optional[str]:
        """Envoie une transaction avec un logging amélioré"""
        try:
            await self.ensure_client_active()
            if not self.keypair:
                logger.error("Keypair Solana non disponible")
                return None
                
            logger.info(f"📡 Envoi de la transaction à Solana {self.network.value}...")
            
            # Loguer des détails sur la transaction
            serialized_tx = base64.b64encode(bytes(transaction)).decode()
            logger.info(f"📊 Transaction Details:")
            logger.info(f"   Size: {len(serialized_tx)} chars (base64)")
            logger.info(f"   Signatures: {len(transaction.signatures)}")
            logger.info(f"   Instructions: {len(transaction.message.instructions)}")
            logger.info(f"   Account keys: {len(transaction.message.account_keys)}")
            logger.info(f"   Blockhash: {transaction.message.recent_blockhash}")
            logger.info(f"   ATL lookups: {len(transaction.message.address_table_lookups)}")
            
            # Vérifier que la transaction est bien signée
            if not transaction.signatures or all(str(sig) == "1111111111111111111111111111111111111111111111111111111111111111" for sig in transaction.signatures):
                logger.error("❌ Transaction not properly signed")
                return None
            
            logger.info(f"   First signature: {str(transaction.signatures[0])[:16]}...")
            
            opts = TxOpts(
                skip_preflight=False,
                preflight_commitment=Confirmed,
                max_retries=3,
            )
            
            logger.debug(f"📤 Sending transaction with options: {opts}")
            
            # Mesurer le temps d'envoi
            send_start = time.time()
            response = await self.client.send_transaction(transaction, opts=opts)
            send_time = time.time() - send_start
            
            logger.info(f"📨 Send completed in {send_time:.1f}s")
            logger.debug(f"📋 RPC Response: {response}")
            
            if response.value:
                tx_signature = str(response.value)
                logger.info(f"✅ Transaction sent successfully: {tx_signature}")
                logger.info(f"🔗 Explorer URL: {NETWORK_CONFIGS[self.network]['explorer_base']}/tx/{tx_signature}{'?cluster=devnet' if self.network == Network.DEVNET else ''}")
                
                # Vérifier que la signature correspond à celle de la transaction
                if str(transaction.signatures[0]) != tx_signature:
                    logger.warning(f"⚠️ Signature mismatch:")
                    logger.warning(f"   Expected: {transaction.signatures[0]}")
                    logger.warning(f"   Received: {tx_signature}")
                
                return tx_signature
            else:
                logger.error("❌ Transaction send failed - no value in response")
                logger.error(f"📋 Full response: {response}")
                
                # Essayer d'extraire plus d'informations de l'erreur
                if hasattr(response, 'error'):
                    logger.error(f"   RPC Error: {response.error}")
                
                return None
                
        except Exception as e:
            logger.error(f"❌ Error sending transaction: {e}")
            logger.error(f"📋 Full traceback: {traceback.format_exc()}")
            
            # Analyser le type d'erreur
            error_str = str(e).lower()
            if "transactionsignatureverificationfailure" in error_str:
                logger.error("💡 Signature verification failure - check keypair or transaction structure")
            elif "blockhash" in error_str:
                logger.error("💡 Blockhash issue - transaction may be too old")
            elif "insufficient" in error_str:
                logger.error("💡 Insufficient balance for transaction")
            elif "network" in error_str or "connection" in error_str:
                logger.error("💡 Network connectivity issue")
            elif "rate" in error_str:
                logger.error("💡 Rate limit exceeded")
            
            return None

    async def confirm_transaction(self, signature: str, timeout: int = 60) -> bool:
        """Version corrigée qui détecte correctement les transactions finalisées"""
        try:
            await self.ensure_client_active()
            logger.info(f"⏳ Waiting for transaction confirmation: {signature[:8]}... ({self.network.value})")
            logger.info(f"🔗 Explorer URL: {NETWORK_CONFIGS[self.network]['explorer_base']}/tx/{signature}{'?cluster=devnet' if self.network == Network.DEVNET else ''}")
            
            start_time = time.time()
            check_count = 0
            
            while time.time() - start_time < timeout:
                check_count += 1
                elapsed = time.time() - start_time
                
                try:
                    logger.debug(f"📊 Confirmation check #{check_count} (elapsed: {elapsed:.1f}s)")
                    
                    response = await self.client.get_signature_statuses([Signature.from_string(signature)])
                    logger.debug(f"📋 Signature status response: {response}")
                    
                    if response.value and len(response.value) > 0:
                        status = response.value[0]
                        
                        if status is None:
                            logger.debug(f"🔄 Transaction not yet found on network (check #{check_count})")
                        else:
                            logger.info(f"📊 Transaction Status Check #{check_count}:")
                            logger.info(f"   Confirmation Status: {status.confirmation_status}")
                            logger.info(f"   Confirmations: {status.confirmations}")
                            logger.info(f"   Slot: {status.slot}")
                            logger.info(f"   Error: {status.err}")
                            
                            # CORRECTION ICI : Inclure "finalized" dans la vérification
                            if status.confirmation_status:
                                logger.info(f"🔍 DEBUG: Checking status '{status.confirmation_status}' (type: {type(status.confirmation_status)})")
                                if str(status.confirmation_status).lower() in ["transactionconfirmationstatus.processed", "transactionconfirmationstatus.confirmed", "transactionconfirmationstatus.finalized"]:
                                    logger.info(f"✅ Transaction confirmed with status '{status.confirmation_status}': {signature[:8]}... ({self.network.value})")
                                    logger.info(f"   Final confirmations: {status.confirmations}")
                                    logger.info(f"   Confirmation time: {elapsed:.1f}s")
                                    return True
                            
                            if status.err:
                                logger.error(f"❌ Transaction failed with error: {status.err}")
                                return False
                    
                    await asyncio.sleep(2)
                    
                except Exception as check_error:
                    logger.error(f"❌ Error during confirmation check #{check_count}: {check_error}")
                    await asyncio.sleep(2)
            
            # Final checks avec accès correct aux attributs
            logger.warning(f"⏰ Transaction confirmation timeout after {timeout}s")
            
            try:
                logger.info("🔍 Final attempt with direct transaction lookup...")
                tx_details = await self.client.get_transaction(
                    Signature.from_string(signature),
                    encoding="json",
                    max_supported_transaction_version=0
                )
                
                if tx_details.value:
                    logger.info("✅ Transaction found in final direct lookup!")
                    
                    # CORRECTION ICI : Accès correct aux métadonnées
                    if hasattr(tx_details.value, 'transaction') and hasattr(tx_details.value.transaction, 'meta'):
                        meta = tx_details.value.transaction.meta
                    elif hasattr(tx_details.value, 'meta'):
                        meta = tx_details.value.meta
                    else:
                        # Structure différente selon la version Solana
                        logger.debug("Transaction structure varies, attempting alternative access...")
                        meta = None
                    
                    if meta is not None:
                        if meta.err is None:
                            logger.info(f"✅ Transaction was actually successful: {signature[:8]}...")
                            return True
                        else:
                            logger.error(f"❌ Transaction failed: {meta.err}")
                            return False
                    else:
                        # Si on ne peut pas accéder aux métadonnées, considérer comme succès si trouvé
                        logger.info(f"✅ Transaction found in ledger (assuming success): {signature[:8]}...")
                        return True
                        
            except Exception as e:
                logger.debug(f"Final direct lookup failed: {e}")
            
            return False
            
        except Exception as e:
            logger.error(f"❌ Error confirming transaction: {e}")
            return False

class JupiterClient:
    """Client pour interagir avec Jupiter API"""
    
    def __init__(self, api_url: str):
        self.base_url = api_url
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

def ask_user_confirmation(operation: str, details: Dict, network: Network) -> bool:
    """Demande confirmation à l'utilisateur avant d'exécuter une transaction"""
    print("\n" + "="*60)
    print(f"🚨 CONFIRMATION REQUIRED: {operation}")
    print("="*60)
    print(f"  Network: {NETWORK_CONFIGS[network]['name']}")
    for key, value in details.items():
        print(f"  {key}: {value}")
    print("="*60)
    if network == Network.MAINNET:
        print("⚠️  This will execute a REAL transaction on Solana MAINNET")
        print("⚠️  This involves REAL MONEY")
    else:
        print("⚠️  This will execute a transaction on Solana DEVNET")
        print("⚠️  This uses test tokens (no real value)")
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
        self.known_atas = {"Dtznpvk7EBXHhTNvz1YjWCTByfPVFsDqMgafKA3ppump": "DX7XJdr7X53FFe1fga4DSJj86E8GHsoAmro4wnAvYTH2"}  # Cache for known ATAs

    async def get_transaction_details(self, signature: str) -> Optional[Dict]:
        """Récupère les détails d'une transaction via le SolanaClient"""
        if self.solana_client:
            async with self.solana_client as solana:
                try:
                    logger.info(f"🔍 Fetching transaction details for: {signature[:8]}...")
                    
                    tx_details = await solana.client.get_transaction(
                        Signature.from_string(signature),
                        encoding="json",
                        max_supported_transaction_version=0
                    )
                    
                    if tx_details.value:
                        logger.info(f"✅ Transaction details retrieved")
                        
                        # Extraire des informations utiles
                        meta = tx_details.value.meta
                        if meta:
                            logger.info(f"📊 Transaction Meta:")
                            logger.info(f"   Error: {meta.err}")
                            
                            if meta.err:
                                logger.error(f"❌ Transaction failed with error: {meta.err}")
                                return {"success": False, "error": meta.err, "meta": meta}
                            else:
                                logger.info(f"✅ Transaction executed successfully")
                                return {"success": True, "meta": meta}
                        else:
                            logger.warning(f"⚠️ Transaction found but no meta information")
                            return {"success": None, "meta": None}
                    else:
                        logger.warning(f"❌ Transaction not found: {signature}")
                        return None
                        
                except Exception as e:
                    logger.error(f"❌ Error fetching transaction details: {e}")
                    return None
        return None

    async def initialize_solana_client(self):
        """Initialise le client Solana"""
        if self.wallet_private_key and SOLANA_AVAILABLE:
            self.solana_client = SolanaClient(
                self.config.solana_rpc_url, 
                self.wallet_private_key,
                self.config.network
            )
            logger.info(f"🔗 Solana client initialized ({self.config.network_name})")
        else:
            logger.warning("⚠️ Solana client not available - running in simulation mode")

    async def ensure_devnet_balance(self, min_balance: float = 1.0) -> bool:
        """S'assure d'avoir assez de SOL sur devnet, demande un airdrop si nécessaire"""
        if self.config.network != Network.DEVNET:
            return True  # Pas d'airdrop sur mainnet
        
        try:
            if not self.solana_client:
                return False
                
            async with self.solana_client as solana:
                balance = await solana.get_balance()
                if balance is None:
                    logger.error("Could not retrieve balance")
                    return False
                
                if balance < min_balance:
                    logger.info(f"Low devnet balance: {balance:.6f} SOL (need {min_balance:.6f})")
                    airdrop_amount = max(2.0, min_balance * 2)  # Demander au moins 2 SOL
                    
                    # Demander confirmation pour l'airdrop
                    while True:
                        response = input(f"Request {airdrop_amount} SOL airdrop on devnet? (yes/no): ").lower().strip()
                        if response in ['yes', 'y']:
                            break
                        elif response in ['no', 'n']:
                            logger.info("Airdrop declined")
                            return False
                        else:
                            print("Please answer 'yes' or 'no'")
                    
                    # Demander l'airdrop
                    airdrop_tx = await solana.request_devnet_airdrop(airdrop_amount)
                    if airdrop_tx:
                        # Vérifier le nouveau solde
                        new_balance = await solana.get_balance()
                        if new_balance and new_balance >= min_balance:
                            logger.info(f"✅ Devnet balance sufficient: {new_balance:.6f} SOL")
                            return True
                    
                    logger.error("Failed to get sufficient devnet balance")
                    return False
                else:
                    logger.info(f"✅ Devnet balance sufficient: {balance:.6f} SOL")
                    return True
                    
        except Exception as e:
            logger.error(f"Error ensuring devnet balance: {e}")
            return False

    async def can_afford_trade(self, sol_amount: float, account_creation_cost: float, solana: SolanaClient) -> tuple[bool, str, dict]:
        try:
            if not solana:
                return False, "Solana client not available", {}
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
            costs["network"] = self.config.network.value
            
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

    def debug_transaction_info(self, transaction: VersionedTransaction, keypair: Keypair):
        logger.info("🔧 DÉBOGAGE DE LA TRANSACTION :")
        logger.info(f"  Nombre de signatures : {len(transaction.signatures)}")
        for i, sig in enumerate(transaction.signatures):
            logger.info(f"  Signature {i+1} : {str(sig)[:8]}...")
        logger.info(f"  Clé publique du portefeuille : {str(keypair.pubkey())[:8]}...")
        logger.info(f"  Clé publique dans account_keys : {str(transaction.message.account_keys[0])[:8]}...")
        logger.info(f"  Portefeuille présent dans account_keys : {str(keypair.pubkey()) in [str(k) for k in transaction.message.account_keys]}")
        logger.info(f"  Blockhash récent : {transaction.message.recent_blockhash}")
        logger.info(f"  Nombre d'instructions : {len(transaction.message.instructions)}")
        for i, instr in enumerate(transaction.message.instructions):
            logger.debug(f"  Instruction {i+1} : program_id_index={instr.program_id_index}, accounts={instr.accounts}, data={instr.data[:16]}...")
        logger.info(f"  Address Table Lookups : {len(transaction.message.address_table_lookups)}")
        for i, atl in enumerate(transaction.message.address_table_lookups):
            logger.debug(f"  ATL {i+1} : account_key={atl.account_key}, writable={atl.writable_indexes}, readonly={atl.readonly_indexes}")

    async def create_token_account_if_needed(self, solana: SolanaClient, token_mint: str) -> Optional[Pubkey]:
        try:
            mint_pubkey = Pubkey.from_string(token_mint)
            logger.info(f"Checking token account for mint: {token_mint[:8]}...")
            
            # Check cache first
            if token_mint in self.known_atas:
                ata_address = self.known_atas[token_mint]
                logger.info(f"✅ Found cached token account for mint {token_mint[:8]}...")
                logger.info(f"==================== FULL ATA ADDRESS ====================")
                logger.info(f"ATA: {ata_address}")
                logger.info(f"========================================================")
                return Pubkey.from_string(ata_address)

            existing_ata = await solana.has_token_account(token_mint)
            if existing_ata:
                ata_address = str(existing_ata)
                logger.info(f"✅ Token account already exists for mint: {token_mint[:8]}...")
                logger.info(f"==================== FULL ATA ADDRESS ====================")
                logger.info(f"ATA: {ata_address}")
                logger.info(f"========================================================")
                self.known_atas[token_mint] = ata_address
                return existing_ata

            logger.info(f"Creating associated token account for mint: {token_mint[:8]}...")
            ata = Pubkey.find_program_address(
                seeds=[
                    bytes(solana.public_key),
                    bytes(TOKEN_PROGRAM_ID),
                    bytes(mint_pubkey)
                ],
                program_id=TOKEN_PROGRAM_ID
            )[0]
            ata_address = str(ata)
            logger.info(f"Derived ATA: {ata_address[:8]}...")
            logger.info(f"==================== FULL ATA ADDRESS ====================")
            logger.info(f"ATA: {ata_address}")
            logger.info(f"========================================================")

            balance = await solana.get_balance()
            logger.info(f"Current balance: {balance:.6f} SOL")
            if balance < 0.00203928:
                logger.error(f"Insufficient balance for ATA creation: need at least 0.00203928 SOL, have {balance:.6f} SOL")
                return None

            instruction = create_associated_token_account(
                payer=solana.public_key,
                owner=solana.public_key,
                mint=mint_pubkey
            )
            
            recent_blockhash = (await solana.client.get_latest_blockhash()).value.blockhash
            message = MessageV0.try_compile(
                payer=solana.public_key,
                instructions=[instruction],
                address_lookup_table_accounts=[],
                recent_blockhash=recent_blockhash
            )
            transaction = VersionedTransaction(message, [solana.keypair])
            
            logger.info("Simulating ATA creation transaction...")
            if await solana.simulate_transaction(transaction):
                logger.info("Simulation successful, sending transaction...")
                tx_signature = await solana.send_transaction(transaction)
                if tx_signature and await solana.confirm_transaction(tx_signature):
                    logger.info(f"✅ Created token account for mint {token_mint[:8]}...")
                    logger.info(f"==================== FULL ATA ADDRESS ====================")
                    logger.info(f"ATA: {ata_address}")
                    logger.info(f"========================================================")
                    self.known_atas[token_mint] = ata_address
                    return ata
                else:
                    logger.error(f"Failed to confirm ATA creation transaction: {tx_signature}")
            else:
                logger.error("Simulation failed for ATA creation")
            return None
        except Exception as e:
            logger.error(f"Error creating token account for mint {token_mint[:8]}...: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return None

    
    async def get_transaction_details(self, signature: str) -> Optional[Dict]:
        """Récupère les détails complets d'une transaction"""
        try:
            logger.info(f"🔍 Fetching transaction details for: {signature[:8]}...")
            
            tx_details = await self.client.get_transaction(
                Signature.from_string(signature),
                encoding="json",
                max_supported_transaction_version=0
            )
            
            if tx_details.value:
                logger.info(f"✅ Transaction details retrieved")
                
                # Extraire des informations utiles
                meta = tx_details.value.meta
                if meta:
                    logger.info(f"📊 Transaction Meta:")
                    logger.info(f"   Error: {meta.err}")
                    logger.info(f"   Fee: {meta.fee} lamports")
                    logger.info(f"   Pre balances: {meta.pre_balances}")
                    logger.info(f"   Post balances: {meta.post_balances}")
                    logger.info(f"   Compute units consumed: {meta.compute_units_consumed}")
                    
                    if meta.log_messages:
                        logger.info(f"📝 Log Messages:")
                        for i, log in enumerate(meta.log_messages[-10:]):  # Derniers 10 logs
                            logger.info(f"   [{i}] {log}")
                    
                    if meta.err:
                        logger.error(f"❌ Transaction failed with error: {meta.err}")
                        return {"success": False, "error": meta.err, "meta": meta}
                    else:
                        logger.info(f"✅ Transaction executed successfully")
                        return {"success": True, "meta": meta}
                else:
                    logger.warning(f"⚠️ Transaction found but no meta information")
                    return {"success": None, "meta": None}
            else:
                logger.warning(f"❌ Transaction not found: {signature}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error fetching transaction details: {e}")
            return None

    async def execute_buy_order(self, token_address: str, token_symbol: str, sol_amount: float) -> Optional[Position]:
        try:
            logger.info(f"🔥 EXECUTING BUY ORDER: {sol_amount:.3f} SOL → {token_symbol} ({token_address[:8]}...) on {self.config.network_name}")
            
            if not self.wallet_private_key or not SOLANA_AVAILABLE:
                logger.error("Running in simulation mode")
                return await self._execute_simulated_buy(token_address, token_symbol, sol_amount)
            
            if not self.solana_client:
                logger.debug("Initialisation du client Solana...")
                await self.initialize_solana_client()
                logger.debug(f"Client Solana initialisé : {self.solana_client}")
            
            async with JupiterClient(self.config.jupiter_api_url) as jupiter, self.solana_client as solana:
                logger.debug(f"Contexte async entré : JupiterClient={jupiter}, SolanaClient={solana}")
                logger.debug("Client Solana actif (vérifié par le gestionnaire de contexte)")
                
                # Vérification du compte de token
                logger.debug(f"Vérification de l'ATA pour le mint : {token_address}")
                ata = await self.create_token_account_if_needed(solana, token_address)
                if not ata:
                    logger.error("Aucun compte de token disponible et échec de la création")
                    return None
                logger.info(f"Utilisation de l'ATA : {str(ata)[:8]}... pour le swap")
                logger.debug(f"Adresse ATA complète : {str(ata)}")

                account_creation_cost = 0.0  # ATA déjà existant

                # Vérification du solde
                logger.debug("Vérification du solde du portefeuille...")
                can_afford, balance_msg, cost_breakdown = await self.can_afford_trade(sol_amount, account_creation_cost, solana)
                
                logger.info(f"💰 Analyse du solde ({self.config.network_name}) :")
                for key, value in cost_breakdown.items():
                    if isinstance(value, (int, float)):
                        logger.info(f"  {key} : {value:.6f} SOL")
                    else:
                        logger.info(f"  {key} : {value}")
                
                if not can_afford:
                    logger.error(f"❌ {balance_msg}")
                    return None
                
                logger.info(f"✅ {balance_msg}")
                
                # Paramètres de la transaction
                sol_lamports = int(sol_amount * 1e9)
                if sol_lamports < 1000:
                    logger.error(f"Montant trop faible : {sol_amount:.9f} SOL")
                    return None
                logger.debug(f"Paramètres de la transaction : sol_lamports={sol_lamports}, slippage_bps={self.config.slippage_bps}")
                
                # Obtenir un devis de Jupiter
                logger.debug("Récupération du devis depuis Jupiter...")
                quote = await jupiter.get_quote(
                    input_mint=self.SOL_MINT,
                    output_mint=token_address,
                    amount=sol_lamports,
                    slippage_bps=self.config.slippage_bps
                )
                
                if not quote:
                    logger.error("Échec de la récupération du devis depuis Jupiter")
                    return None
                logger.debug(f"Devis Jupiter reçu : {quote}")
                logger.info(f"📊 Détails du devis : in_amount={quote.get('inAmount')}, out_amount={quote.get('outAmount')}, price_impact={quote.get('priceImpactPct')}%")
                
                # Calcul des détails de la transaction
                estimated_tokens_raw = int(quote.get('outAmount', 0))
                token_decimals = 6  # À ajuster selon les métadonnées du token
                estimated_tokens = estimated_tokens_raw / (10 ** token_decimals)
                estimated_price = sol_amount / estimated_tokens if estimated_tokens > 0 else 0
                impact_pct = float(quote.get('priceImpactPct', 0))
                
                logger.info(f"📊 Analyse du devis :")
                logger.info(f"  Entrée : {sol_amount:.6f} SOL")
                logger.info(f"  Sortie : {estimated_tokens:.0f} {token_symbol}")
                logger.info(f"  Prix par token : {estimated_price:.8f} SOL")
                logger.info(f"  Impact sur le prix : {impact_pct:.2f}%")
                
                # Confirmation utilisateur si nécessaire
                if self.config.require_manual_confirmation:
                    confirmation_details = {
                        "Opération": "ACHAT",
                        "Token": f"{token_symbol} ({token_address[:8]}...)",
                        "Montant SOL": f"{sol_amount:.6f} SOL",
                        "Tokens attendus": f"{estimated_tokens:.0f} {token_symbol}",
                        "Prix par token": f"{estimated_price:.8f} SOL",
                        "Impact sur le prix": f"{impact_pct:.2f}%",
                        "Solde actuel": f"{cost_breakdown.get('current_balance', 0):.6f} SOL",
                        "Solde restant": f"{cost_breakdown.get('available_after', 0):.6f} SOL"
                    }
                    if not ask_user_confirmation("Achat de token", confirmation_details, self.config.network):
                        logger.info("Transaction annulée par l'utilisateur")
                        return None
                
                # Obtenir les frais de priorité
                logger.debug("Récupération des frais de priorité...")
                priority_fee = await solana.get_dynamic_priority_fee()
                logger.debug(f"Frais de priorité : {priority_fee} lamports")
                
                # Obtenir la transaction de swap depuis Jupiter
                logger.debug("Récupération de la transaction de swap depuis Jupiter...")
                swap_data = await jupiter.get_swap_transaction(
                    quote,
                    str(solana.public_key),
                    priority_fee
                )
                
                if not swap_data:
                    logger.error("Échec de la récupération de la transaction de swap depuis Jupiter")
                    return None
                logger.debug(f"Données de la transaction Jupiter : {swap_data}")
                logger.info(f"📜 Clé 'swapTransaction' présente : {'swapTransaction' in swap_data}")
                
                # APPROCHE SIMPLIFIÉE : Signer directement la transaction Jupiter sans modification
                logger.debug("Parsing et signature directe de la transaction Jupiter...")
                transaction_bytes = base64.b64decode(swap_data.get('swapTransaction'))
                logger.debug(f"Octets de la transaction (taille) : {len(transaction_bytes)}")
                
                # Créer la transaction à partir des bytes de Jupiter
                original_transaction = VersionedTransaction.from_bytes(transaction_bytes)
                logger.debug(f"Transaction Jupiter parsée : {original_transaction}")
                logger.info(f"🔍 Détails de la transaction Jupiter :")
                logger.info(f"  Signatures : {original_transaction.signatures}")
                logger.info(f"  Blockhash original : {original_transaction.message.recent_blockhash}")
                logger.info(f"  Compte principal : {original_transaction.message.account_keys[0]}")
                
                # Vérification du keypair avant signature
                logger.info("✍️ Préparation de la signature de la transaction...")
                logger.debug(f"Keypair utilisé : pubkey={str(solana.keypair.pubkey())[:8]}...")
                if str(solana.keypair.pubkey()) != str(original_transaction.message.account_keys[0]):
                    logger.error(f"Erreur : La clé publique du keypair ({solana.keypair.pubkey()}) ne correspond pas au compte principal ({original_transaction.message.account_keys[0]})")
                    return None

                # IMPORTANT: Signer directement SANS CHANGER LE BLOCKHASH
                # Ceci évite tous les problèmes de reconstruction et d'Address Lookup Tables
                transaction = VersionedTransaction(original_transaction.message, [solana.keypair])
                
                logger.info("✅ Transaction Jupiter signée directement (sans modification)")
                logger.info(f"  Signature : {str(transaction.signatures[0])[:8]}...")
                logger.info(f"  Blockhash utilisé : {transaction.message.recent_blockhash}")
                
                # Débogage de la transaction signée
                logger.info("🔧 DEBUG : Analyse de la transaction signée...")
                self.debug_transaction_info(transaction, solana.keypair)
                
                # Simuler la transaction
                logger.info("🔍 Simulation de la transaction...")
                simulation_result = await solana.simulate_transaction(transaction)
                if not simulation_result:
                    logger.error("❌ Échec de la simulation de la transaction")
                    logger.debug(f"Résultat de la simulation : {simulation_result}")
                    return None
                
                logger.info("✅ Simulation de la transaction réussie")
                logger.debug(f"Résultat de la simulation : {simulation_result}")
                
                # Envoyer la transaction
                logger.info(f"📡 Envoi de la transaction à Solana {self.config.network_name}...")
                tx_signature = await solana.send_transaction(transaction)
                if not tx_signature:
                    logger.error("❌ Échec de l'envoi de la transaction")
                    return None
                logger.debug(f"Signature de la transaction : {tx_signature}")
                
                # Confirmer la transaction
                logger.info(f"⏳ Confirming transaction: {tx_signature[:8]}...")
                confirmation_start = time.time()
                
                confirmed = await solana.confirm_transaction(tx_signature, self.config.confirmation_timeout)
                confirmation_time = time.time() - confirmation_start

                if confirmed:
                    logger.info(f"✅ Transaction confirmée en {confirmation_time:.1f}s")
                    
                    # Créer une position
                    position = Position(
                        token_address=token_address,
                        token_symbol=token_symbol,
                        entry_price=estimated_price,
                        sol_amount=sol_amount,
                        token_amount=estimated_tokens,
                        entry_time=datetime.now(),
                        entry_tx_signature=tx_signature,
                        network=self.config.network
                    )
                    
                    # Mettre à jour l'état du trader
                    self.positions[token_address] = position
                    self.daily_spent += sol_amount
                    self.daily_trades += 1
                    
                    logger.info(f"🎉 ACHAT CONFIRMÉ !")
                    logger.info(f"   Token : {estimated_tokens:.0f} {token_symbol}")
                    logger.info(f"   Coût : {sol_amount:.6f} SOL")
                    logger.info(f"   Prix : {estimated_price:.8f} SOL par token")
                    logger.info(f"   Réseau : {self.config.network_name}")
                    logger.info(f"   TX : {tx_signature}")
                    logger.info(f"   Explorer : {position.get_explorer_url()}")
                    
                    return position
                else:
                    logger.error("❌ Transaction confirmation failed or timed out")
            
                    # Essayer de récupérer plus d'informations
                    logger.info(f"🔍 Attempting to get transaction details...")
                    tx_details = await self.get_transaction_details(tx_signature)
                    
                    if tx_details:
                        if tx_details.get("success") is True:
                            logger.info(f"🎉 Transaction was actually successful! Creating position...")
                            # Créer la position même si la confirmation a échoué
                            # ... créer la position ...
                        elif tx_details.get("success") is False:
                            logger.error(f"💥 Transaction definitively failed: {tx_details.get('error')}")
                            return None
                        else:
                            logger.warning(f"❓ Transaction status unclear")
                    
                    logger.error(f"🔗 Check transaction manually: {self.config.explorer_base_url}/tx/{tx_signature}{'?cluster=devnet' if self.config.network == Network.DEVNET else ''}")
                    return None
                            
        except Exception as e:
            logger.error(f"Erreur dans execute_buy_order : {e}")
            logger.error(f"Trace complète : {traceback.format_exc()}")
            return None

    async def execute_buy_order_old(self, token_address: str, token_symbol: str, sol_amount: float) -> Optional[Position]:
        try:
            logger.info(f"🔥 EXECUTING BUY ORDER: {sol_amount:.3f} SOL → {token_symbol} ({token_address[:8]}...) on {self.config.network_name}")
            
            if not self.wallet_private_key or not SOLANA_AVAILABLE:
                logger.error("Running in simulation mode")
                return await self._execute_simulated_buy(token_address, token_symbol, sol_amount)
            
            if not self.solana_client:
                logger.debug("Initialisation du client Solana...")
                await self.initialize_solana_client()
                logger.debug(f"Client Solana initialisé : {self.solana_client}")
            
            async with JupiterClient(self.config.jupiter_api_url) as jupiter, self.solana_client as solana:
                logger.debug(f"Contexte async entré : JupiterClient={jupiter}, SolanaClient={solana}")
                logger.debug("Client Solana actif (vérifié par le gestionnaire de contexte)")
                
                # Vérification du compte de token
                logger.debug(f"Vérification de l'ATA pour le mint : {token_address}")
                ata = await self.create_token_account_if_needed(solana, token_address)
                if not ata:
                    logger.error("Aucun compte de token disponible et échec de la création")
                    return None
                logger.info(f"Utilisation de l'ATA : {str(ata)[:8]}... pour le swap")
                logger.debug(f"Adresse ATA complète : {str(ata)}")

                account_creation_cost = 0.0  # ATA déjà existant

                # Vérification du solde
                logger.debug("Vérification du solde du portefeuille...")
                can_afford, balance_msg, cost_breakdown = await self.can_afford_trade(sol_amount, account_creation_cost, solana)
                
                logger.info(f"💰 Analyse du solde ({self.config.network_name}) :")
                for key, value in cost_breakdown.items():
                    if isinstance(value, (int, float)):
                        logger.info(f"  {key} : {value:.6f} SOL")
                    else:
                        logger.info(f"  {key} : {value}")
                
                if not can_afford:
                    logger.error(f"❌ {balance_msg}")
                    return None
                
                logger.info(f"✅ {balance_msg}")
                
                # Paramètres de la transaction
                sol_lamports = int(sol_amount * 1e9)
                if sol_lamports < 1000:
                    logger.error(f"Montant trop faible : {sol_amount:.9f} SOL")
                    return None
                logger.debug(f"Paramètres de la transaction : sol_lamports={sol_lamports}, slippage_bps={self.config.slippage_bps}")
                
                # Obtenir un devis de Jupiter
                logger.debug("Récupération du devis depuis Jupiter...")
                quote = await jupiter.get_quote(
                    input_mint=self.SOL_MINT,
                    output_mint=token_address,
                    amount=sol_lamports,
                    slippage_bps=self.config.slippage_bps
                )
                
                if not quote:
                    logger.error("Échec de la récupération du devis depuis Jupiter")
                    return None
                logger.debug(f"Devis Jupiter reçu : {quote}")
                logger.info(f"📊 Détails du devis : in_amount={quote.get('inAmount')}, out_amount={quote.get('outAmount')}, price_impact={quote.get('priceImpactPct')}%")
                
                # Calcul des détails de la transaction
                estimated_tokens_raw = int(quote.get('outAmount', 0))
                token_decimals = 6  # À ajuster selon les métadonnées du token
                estimated_tokens = estimated_tokens_raw / (10 ** token_decimals)
                estimated_price = sol_amount / estimated_tokens if estimated_tokens > 0 else 0
                impact_pct = float(quote.get('priceImpactPct', 0))
                
                logger.info(f"📊 Analyse du devis :")
                logger.info(f"  Entrée : {sol_amount:.6f} SOL")
                logger.info(f"  Sortie : {estimated_tokens:.0f} {token_symbol}")
                logger.info(f"  Prix par token : {estimated_price:.8f} SOL")
                logger.info(f"  Impact sur le prix : {impact_pct:.2f}%")
                
                # Confirmation utilisateur si nécessaire
                if self.config.require_manual_confirmation:
                    confirmation_details = {
                        "Opération": "ACHAT",
                        "Token": f"{token_symbol} ({token_address[:8]}...)",
                        "Montant SOL": f"{sol_amount:.6f} SOL",
                        "Tokens attendus": f"{estimated_tokens:.0f} {token_symbol}",
                        "Prix par token": f"{estimated_price:.8f} SOL",
                        "Impact sur le prix": f"{impact_pct:.2f}%",
                        "Solde actuel": f"{cost_breakdown.get('current_balance', 0):.6f} SOL",
                        "Solde restant": f"{cost_breakdown.get('available_after', 0):.6f} SOL"
                    }
                    if not ask_user_confirmation("Achat de token", confirmation_details, self.config.network):
                        logger.info("Transaction annulée par l'utilisateur")
                        return None
                
                # Obtenir les frais de priorité
                logger.debug("Récupération des frais de priorité...")
                priority_fee = await solana.get_dynamic_priority_fee()
                logger.debug(f"Frais de priorité : {priority_fee} lamports")
                
                # Obtenir la transaction de swap depuis Jupiter
                logger.debug("Récupération de la transaction de swap depuis Jupiter...")
                swap_data = await jupiter.get_swap_transaction(
                    quote,
                    str(solana.public_key),
                    priority_fee
                )
                
                if not swap_data:
                    logger.error("Échec de la récupération de la transaction de swap depuis Jupiter")
                    return None
                logger.debug(f"Données de la transaction Jupiter : {swap_data}")
                logger.info(f"📜 Clé 'swapTransaction' présente : {'swapTransaction' in swap_data}")
                
                # Parse et préparer la transaction
                logger.debug("Parsing des octets de la transaction...")
                transaction_bytes = base64.b64decode(swap_data.get('swapTransaction'))
                logger.debug(f"Octets de la transaction (taille) : {len(transaction_bytes)}")
                transaction = VersionedTransaction.from_bytes(transaction_bytes)
                logger.debug(f"Transaction parsée : {transaction}")
                logger.info(f"🔍 Détails de la transaction avant signature :")
                logger.info(f"  Signatures : {transaction.signatures}")
                logger.info(f"  Blockhash : {transaction.message.recent_blockhash}")
                logger.info(f"  Compte principal : {transaction.message.account_keys[0]}")

                # Débogage de la transaction
                logger.info("🔧 DEBUG : Analyse de la transaction avant signature...")
                self.debug_transaction_info(transaction, solana.keypair)

                # Rafraîchir le blockhash
                logger.debug("Récupération d'un blockhash frais...")
                recent_blockhash = (await solana.client.get_latest_blockhash()).value.blockhash
                logger.debug(f"Nouveau blockhash : {recent_blockhash}")

                # Charger les Address Lookup Tables (ATL)
                address_lookup_tables = []
                for atl in transaction.message.address_table_lookups:
                    logger.debug(f"Chargement de l'ATL : {atl.account_key}")
                    try:
                        lookup_table = await solana.load_address_lookup_table(atl.account_key)
                        if lookup_table:
                            address_lookup_tables.append(lookup_table)
                            logger.debug(f"ATL chargée : {atl.account_key}, {len(lookup_table.addresses)} adresses")
                        else:
                            logger.error(f"Échec du chargement de l'ATL : {atl.account_key}")
                            return None
                    except Exception as e:
                        logger.error(f"Erreur lors du chargement de l'ATL {atl.account_key} : {e}")
                        logger.error(f"Trace complète : {traceback.format_exc()}")
                        return None

                # # Déterminer les indices des comptes signataires et modifiables
                # header = transaction.message.header
                # num_required_signatures = header.num_required_signatures
                # num_readonly_signed_accounts = header.num_readonly_signed_accounts
                # num_readonly_unsigned_accounts = header.num_readonly_unsigned_accounts

                # signer_indices = list(range(num_required_signatures))
                # writable_signer_indices = list(range(num_required_signatures - num_readonly_signed_accounts))
                # total_accounts = len(transaction.message.account_keys)
                # writable_unsigned_indices = list(range(num_required_signatures, total_accounts - num_readonly_unsigned_accounts))

                # # Combiner les account_keys et les adresses de l'ATL
                # all_account_keys = list(transaction.message.account_keys)
                # for atl in transaction.message.address_table_lookups:
                #     for idx in atl.writable_indexes:
                #         all_account_keys.append(address_lookup_tables[0].addresses[idx])
                #     for idx in atl.readonly_indexes:
                #         all_account_keys.append(address_lookup_tables[0].addresses[idx])

                # # Convertir les CompiledInstruction en Instruction
                # instructions = []
                # for compiled_instr in transaction.message.instructions:
                #     program_id = transaction.message.account_keys[compiled_instr.program_id_index]
                #     accounts = []
                #     for account_idx in compiled_instr.accounts:
                #         try:
                #             pubkey = all_account_keys[account_idx]
                #             accounts.append(AccountMeta(
                #                 pubkey=pubkey,
                #                 is_signer=account_idx in signer_indices,
                #                 is_writable=(account_idx in writable_signer_indices or account_idx in writable_unsigned_indices)
                #             ))
                #         except IndexError:
                #             logger.error(f"IndexError : account_idx={account_idx} dépasse la longueur de all_account_keys={len(all_account_keys)}")
                #             return None
                #     instruction = Instruction(
                #         program_id=program_id,
                #         accounts=accounts,
                #         data=compiled_instr.data
                #     )
                #     instructions.append(instruction)
                #     logger.debug(f"Instruction convertie : program_id={program_id}, accounts={len(accounts)}, data={compiled_instr.data[:16]}...")

                # Créer un nouveau MessageV0 avec le blockhash mis à jour
                # new_message = MessageV0.try_compile(
                #     payer=solana.public_key,
                #     instructions=instructions,
                #     address_lookup_table_accounts=address_lookup_tables,
                #     recent_blockhash=recent_blockhash
                # )
                # logger.debug(f"Nouveau MessageV0 créé avec blockhash : {recent_blockhash}")

                 # Vérification du keypair avant signature
                # logger.info("✍️ Préparation de la signature de la transaction...")
                # logger.debug(f"Keypair utilisé : pubkey={str(solana.keypair.pubkey())[:8]}...")
                # if str(solana.keypair.pubkey()) != str(new_message.account_keys[0]):
                #     logger.error(f"Erreur : La clé publique du keypair ({solana.keypair.pubkey()}) ne correspond pas au compte principal ({new_message.account_keys[0]})")
                #     return None

                # # Créer la transaction signée (signing happens in constructor)
                # transaction = VersionedTransaction(new_message, [solana.keypair])
                # logger.info("✅ Transaction signée automatiquement lors de la construction")
                # logger.info(f"  Signature : {str(transaction.signatures[0])[:8]}...")

                try:
                    # Méthode simplifiée : ne pas reconstruire toute la transaction
                    # Juste mettre à jour le blockhash dans la transaction existante
                    
                    # Créer une nouvelle transaction avec le même message mais un nouveau blockhash
                    original_message = transaction.message
                    
                    # Créer un nouveau message avec blockhash mis à jour
                    # Mais garder exactement la même structure d'accounts et d'instructions
                    new_message = MessageV0(
                        header=original_message.header,
                        account_keys=original_message.account_keys,
                        recent_blockhash=recent_blockhash,
                        instructions=original_message.instructions,
                        address_table_lookups=original_message.address_table_lookups
                    )
                    
                    logger.debug(f"Nouveau MessageV0 créé avec blockhash mis à jour : {recent_blockhash}")
                    
                    # Créer la transaction signée avec le nouveau message
                    transaction = VersionedTransaction(new_message, [solana.keypair])
                    logger.info("✅ Transaction reconstruite avec nouveau blockhash et signée")
                    logger.info(f"  Signature : {str(transaction.signatures[0])[:8]}...")
                    
                except Exception as reconstruct_error:
                    logger.error(f"Erreur lors de la reconstruction : {reconstruct_error}")
                    logger.error(f"Trace complète : {traceback.format_exc()}")
                    
                    # Fallback : utiliser la transaction originale sans modification du blockhash
                    logger.warning("⚠️ Utilisation de la transaction originale sans modification du blockhash")
                    transaction = VersionedTransaction(transaction.message, [solana.keypair])
                    logger.info("✅ Transaction originale signée")
                    logger.info(f"  Signature : {str(transaction.signatures[0])[:8]}...")

                

               

                # Débogage de la transaction signée
                logger.info("🔧 DEBUG : Analyse de la transaction signée...")
                self.debug_transaction_info(transaction, solana.keypair)
                
                # Simuler la transaction
                logger.info("🔍 Simulation de la transaction...")
                simulation_result = await solana.simulate_transaction(transaction)
                if not simulation_result:
                    logger.error("❌ Échec de la simulation de la transaction")
                    logger.debug(f"Résultat de la simulation : {simulation_result}")
                    return None
                
                logger.info("✅ Simulation de la transaction réussie")
                logger.debug(f"Résultat de la simulation : {simulation_result}")
                
                # Envoyer la transaction
                logger.info(f"📡 Envoi de la transaction à Solana {self.config.network_name}...")
                tx_signature = await solana.send_transaction(transaction)
                if not tx_signature:
                    logger.error("❌ Échec de l'envoi de la transaction")
                    return None
                logger.debug(f"Signature de la transaction : {tx_signature}")
                
                # Confirmer la transaction
                logger.info(f"⏳ Confirmation de la transaction : {tx_signature[:8]}...")
                confirmation_start = time.time()
                
                if await solana.confirm_transaction(tx_signature, self.config.confirmation_timeout):
                    confirmation_time = time.time() - confirmation_start
                    logger.info(f"✅ Transaction confirmée en {confirmation_time:.1f}s")
                    
                    # Créer une position
                    position = Position(
                        token_address=token_address,
                        token_symbol=token_symbol,
                        entry_price=estimated_price,
                        sol_amount=sol_amount,
                        token_amount=estimated_tokens,
                        entry_time=datetime.now(),
                        entry_tx_signature=tx_signature,
                        network=self.config.network
                    )
                    
                    # Mettre à jour l'état du trader
                    self.positions[token_address] = position
                    self.daily_spent += sol_amount
                    self.daily_trades += 1
                    
                    logger.info(f"🎉 ACHAT CONFIRMÉ !")
                    logger.info(f"   Token : {estimated_tokens:.0f} {token_symbol}")
                    logger.info(f"   Coût : {sol_amount:.6f} SOL")
                    logger.info(f"   Prix : {estimated_price:.8f} SOL par token")
                    logger.info(f"   Réseau : {self.config.network_name}")
                    logger.info(f"   TX : {tx_signature}")
                    logger.info(f"   Explorer : {position.get_explorer_url()}")
                    
                    return position
                else:
                    logger.error("❌ Échec ou timeout de la confirmation de la transaction")
                    explorer_url = f"{self.config.explorer_base_url}/tx/{tx_signature}"
                    if self.config.network == Network.DEVNET:
                        explorer_url += "?cluster=devnet"
                    logger.error(f"   Vérifiez le statut de la transaction : {explorer_url}")
                    return None
                            
        except Exception as e:
            logger.error(f"Erreur dans execute_buy_order : {e}")
            logger.error(f"Trace complète : {traceback.format_exc()}")
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
            entry_tx_signature=f"sim_{int(time.time())}",
            network=self.config.network
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
        logger.info(f"🚀 Starting position monitoring on {self.config.network_name}...")
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
            "network": self.config.network.value,
            "network_name": self.config.network_name,
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
                    "tx_signature": p.entry_tx_signature,
                    "network": p.network.value,
                    "explorer_url": p.get_explorer_url()
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

def create_network_config(network_name: str) -> TradeConfig:
    """Crée une configuration selon le réseau choisi"""
    if network_name.lower() in ['mainnet', 'main']:
        return TradeConfig(
            network=Network.MAINNET,
            max_sol_per_trade=0.0001,  # Montant très faible pour la sécurité
            max_daily_budget=0.01,
            require_manual_confirmation=True  # Confirmation obligatoire sur mainnet
        )
    elif network_name.lower() in ['devnet', 'dev']:
        return TradeConfig(
            network=Network.DEVNET,
            max_sol_per_trade=0.1,     # Montants plus élevés sur devnet
            max_daily_budget=1.0,
            require_manual_confirmation=False  # Peut être désactivé sur devnet
        )
    else:
        raise ValueError(f"Network '{network_name}' not supported. Use 'mainnet' or 'devnet'")

async def test_autotrader(network: str = "devnet"):
    """Fonction de test pour l'autotrader avec vraies transactions"""
    try:
        config = create_network_config(network)
    except ValueError as e:
        print(f"❌ {e}")
        return
    
    print(f"🧪 Testing AutoTrader on {config.network_name}...")
    print("🔍 System Check:")
    print(f"  Network: {config.network_name}")
    print(f"  RPC URL: {config.solana_rpc_url}")
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
                    if config.network == Network.DEVNET:
                        print(f"  💡 Will request airdrop if needed")
            else:
                print("  ❌ Could not retrieve wallet balance")
    
    monitoring_task = asyncio.create_task(trader.start_monitoring())
    
    try:
        test_tokens = [
            {
                # USDC devnet - token plus standard
                "address": "Dtznpvk7EBXHhTNvz1YjWCTByfPVFsDqMgafKA3ppump",
                "symbol": "xxx",
                "name": "xxx Coin Devnet",
                "usd_market_cap": 50000,
                "created_at": datetime.now().isoformat(),
                "description": "xxx token on devnet for testing"
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
                    if config.network == Network.MAINNET:
                        print("\n⚠️  ATTENTION: This will execute a REAL transaction on MAINNET!")
                        print("⚠️  This involves REAL MONEY!")
                    else:
                        print("\n⚠️  ATTENTION: This will execute a transaction on DEVNET")
                        print("⚠️  This uses test tokens (no real value)")
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
                        print(f"   Explorer: {position.get_explorer_url()}")
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
        print(f"\n📈 Final Trading Stats ({stats['network_name']}):")
        print("="*50)
        print(f"Network: {stats['network_name']}")
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
                print(f"    Network: {pos['network']}")
                print(f"    TX: {pos['tx_signature']}")
                if not pos['tx_signature'].startswith('sim_'):
                    print(f"    Explorer: {pos['explorer_url']}")
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

def show_help():
    """Affiche l'aide pour l'utilisation du script"""
    print("AutoTrader - Solana Trading Bot")
    print("=" * 50)
    print("Usage:")
    print("  python autotrader.py [network]")
    print("")
    print("Networks:")
    print("  mainnet  - Trade on Solana mainnet (REAL MONEY)")
    print("  devnet   - Trade on Solana devnet (TEST TOKENS)")
    print("")
    print("Examples:")
    print("  python autotrader.py devnet     # Test on devnet")
    print("  python autotrader.py mainnet    # Trade on mainnet")
    print("")
    print("Environment Variables (.env file):")
    print("  WALLET_PRIVATE_KEY=your_base58_private_key")
    print("")
    print("Safety Features:")
    print("  - Devnet: Automatic airdrop, higher limits")
    print("  - Mainnet: Manual confirmation required, low limits")
    print("  - All networks: Simulation mode if wallet not configured")

if __name__ == "__main__":
    import sys
    
    # Vérifier les arguments
    if len(sys.argv) > 1:
        if sys.argv[1] in ['-h', '--help', 'help']:
            show_help()
            sys.exit(0)
        network = sys.argv[1]
    else:
        # Demander à l'utilisateur de choisir le réseau
        print("AutoTrader - Choose Network")
        print("=" * 30)
        print("1. devnet  - Test with fake SOL (recommended)")
        print("2. mainnet - Real trading with real SOL (⚠️ RISKY)")
        print("3. help    - Show detailed help")
        print("")
        
        while True:
            choice = input("Choose network (1/2/3): ").strip()
            if choice == '1':
                network = 'devnet'
                break
            elif choice == '2':
                network = 'mainnet'
                break
            elif choice == '3':
                show_help()
                sys.exit(0)
            else:
                print("Please choose 1, 2, or 3")
    
    print("AutoTrader REAL Trading Test System")
    print("=" * 60)
    
    if network.lower() == 'mainnet':
        print("⚠️  WARNING: MAINNET MODE - REAL MONEY AT RISK")
        print("⚠️  Only use with small amounts you can afford to lose")
        print("⚠️  Trading crypto is extremely risky")
        print("⚠️  This is experimental software - use at your own risk")
    else:
        print("🧪 DEVNET MODE - Testing with fake SOL")
        print("✅ Safe for testing - no real money at risk")
        print("✅ Automatic airdrops available")
    
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
    
    if SOLANA_AVAILABLE and wallet_key and network.lower() == 'mainnet':
        print(f"\n🚨 FINAL WARNING FOR MAINNET:")
        print(f"   This will use your REAL Solana wallet")
        print(f"   Transactions will be executed on MAINNET")
        print(f"   You may LOSE MONEY")
        print(f"   Maximum trade size: 0.0001 SOL")
        print(f"   Daily budget: 0.01 SOL")
        final_confirm = input(f"\nType 'I UNDERSTAND THE RISKS' to continue: ")
        if final_confirm != 'I UNDERSTAND THE RISKS':
            print("❌ Test cancelled for safety")
            sys.exit(1)
        print("✅ Proceeding with mainnet trading test...")
    elif network.lower() == 'devnet':
        print(f"\n✅ DEVNET MODE:")
        print(f"   Using test network with fake SOL")
        print(f"   No real money at risk")
        print(f"   Higher trade limits for testing")
        print(f"   Automatic airdrop if needed")
    
    asyncio.run(test_autotrader(network))