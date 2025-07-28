"""
Solana Client - Implementation complète pour le Trading Bot
File: solana_client.py

Client Solana professionnel avec toutes les fonctionnalités de trading :
- Gestion des wallets et transactions
- Trading de tokens SPL
- Calcul de slippage et prix d'impact
- Gestion des erreurs et retry logic
- Simulation de transactions
- Support des DEX (Raydium, Orca, Jupiter)
"""

import requests
import base58
import os
import time
import json
import base64
import struct
import asyncio
import logging
from decimal import Decimal, ROUND_DOWN
from typing import Optional, Dict, List, Tuple, Union, Any
from dataclasses import dataclass, field
from enum import Enum
import concurrent.futures
from datetime import datetime, timedelta

# Solana dependencies
try:
    from solana.rpc.api import Client
    from solana.rpc.async_api import AsyncClient
    from solana.rpc.commitment import Commitment, Confirmed, Finalized
    from solana.rpc.types import TxOpts

#Nouvelle API depuis solders
try:
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey as PublicKey
    from solders.transaction import Transaction
    from solders.system_program import transfer, TransferParams
    SOLDERS_API = True
except ImportError:
    # Ancienne API
    from solana.keypair import Keypair
    from solana.publickey import PublicKey  
    from solana.transaction import Transaction
    from solana.system_program import transfer, TransferParams
    SOLDERS_API = False
    
    # SPL Token support
    from spl.token.client import Token
    from spl.token.constants import TOKEN_PROGRAM_ID, ASSOCIATED_TOKEN_PROGRAM_ID
    from spl.token.instructions import (
        create_associated_token_account, 
        get_associated_token_address,
        transfer_checked, TransferCheckedParams
    )
    
    # Anchor/Serum support pour les DEX
    try:
        from anchorpy import Provider, Wallet
        ANCHOR_AVAILABLE = True
    except ImportError:
        ANCHOR_AVAILABLE = False
        
    SOLANA_AVAILABLE = True
    
except ImportError:
    SOLANA_AVAILABLE = False
    # Créer des classes mock pour éviter les erreurs d'import
    class PublicKey:
        def __init__(self, key): self.key = key
        def __str__(self): return str(self.key)
    
    class Keypair:
        @staticmethod
        def generate(): return None
        
    class Client:
        def __init__(self, *args, **kwargs): pass

# Jupiter SDK pour les swaps optimaux
try:
    import requests
    JUPITER_AVAILABLE = True
except ImportError:
    JUPITER_AVAILABLE = False


class TransactionStatus(Enum):
    """États des transactions Solana"""
    PENDING = "pending"
    CONFIRMED = "confirmed" 
    FINALIZED = "finalized"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class DEXType(Enum):
    """Types de DEX supportés"""
    JUPITER = "jupiter"        # Aggregateur principal
    RAYDIUM = "raydium"       # AMM populaire
    ORCA = "orca"             # AMM avec concentrated liquidity
    SERUM = "serum"           # Order book DEX
    DIRECT = "direct"         # Transfer direct (pas de swap)


class NetworkType(Enum):
    """Types de réseau Solana"""
    MAINNET = "mainnet-beta"
    DEVNET = "devnet"
    TESTNET = "testnet"
    LOCALNET = "localnet"


@dataclass
class TokenInfo:
    """Information sur un token SPL"""
    address: str
    symbol: str
    name: str
    decimals: int
    mint_authority: Optional[str] = None
    freeze_authority: Optional[str] = None
    supply: Optional[int] = None
    is_initialized: bool = True


@dataclass
class WalletBalance:
    """Balance d'un wallet"""
    sol_balance: float
    token_balances: Dict[str, float]
    total_value_usd: float
    last_updated: datetime = field(default_factory=datetime.now)


@dataclass
class TransactionResult:
    """Résultat d'une transaction"""
    signature: str
    status: TransactionStatus
    slot: Optional[int] = None
    block_time: Optional[int] = None
    fee: Optional[int] = None
    error: Optional[str] = None
    logs: List[str] = field(default_factory=list)
    compute_units_consumed: Optional[int] = None


@dataclass
class SwapQuote:
    """Quote pour un swap de tokens"""
    input_mint: str
    output_mint: str
    input_amount: int
    output_amount: int
    other_amount_threshold: int
    swap_mode: str
    slippage_bps: int
    price_impact_pct: float
    route_plan: List[Dict]
    dex: DEXType
    fee_bps: Optional[int] = None
    estimated_fee_sol: Optional[float] = None


@dataclass
class SwapParams:
    """Paramètres pour un swap"""
    input_token: str
    output_token: str
    amount: float
    slippage: float = 0.01  # 1% par défaut
    max_price_impact: float = 0.05  # 5% par défaut
    priority_fee: int = 10000  # lamports
    compute_unit_limit: int = 300000
    dex_preference: Optional[DEXType] = None


@dataclass
class SolanaConfig:
    """Configuration du client Solana"""
    rpc_url: str
    backup_rpc_urls: List[str]
    private_key: str
    commitment: str = "confirmed"
    transaction_timeout: int = 60
    confirmation_timeout: int = 30
    max_retries: int = 3
    retry_delay: int = 2
    priority_fee_lamports: int = 10000
    compute_unit_limit: int = 300000
    compute_unit_price: int = 1000


class SolanaClientError(Exception):
    """Exception de base pour le client Solana"""
    pass


class InsufficientFundsError(SolanaClientError):
    """Erreur de fonds insuffisants"""
    pass


class SlippageExceededError(SolanaClientError):
    """Erreur de slippage dépassé"""
    pass


class TransactionFailedError(SolanaClientError):
    """Erreur de transaction échouée"""
    pass


class SolanaClient:
    """
    Client Solana professionnel pour trading de tokens
    
    Features:
    - Gestion complète des wallets et balances
    - Trading via Jupiter, Raydium, Orca
    - Simulation et validation de transactions
    - Gestion des erreurs et retry logic
    - Calcul de slippage et prix d'impact
    - Support des transactions prioritaires
    """
    
    # Tokens de référence communs
    COMMON_TOKENS = {
        'SOL': 'So11111111111111111111111111111111111111112',  # Wrapped SOL
        'USDC': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
        'USDT': 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',
        'RAY': '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R',
        'SRM': 'SRMuApVNdxXokk5GT7XD5cUUgXMBCoAz2LHeuAoKWRt',
        'ORCA': 'orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE'
    }
    
    # Jupiter API endpoints
    JUPITER_API_V6 = "https://quote-api.jup.ag/v6"
    
    def __init__(self, config: SolanaConfig, advanced_logger=None):
        """Initialize Solana client"""
        if not SOLANA_AVAILABLE:
            raise ImportError("Solana dependencies not installed. Run: pip install solana anchor-py spl-token")
        
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.advanced_logger = advanced_logger
        
        # Initialize RPC clients
        self._setup_rpc_clients()
        
        # Initialize wallet
        self._setup_wallet()
        
        # Performance tracking
        self.performance_metrics = {
            'total_transactions': 0,
            'successful_transactions': 0,
            'failed_transactions': 0,
            'total_fees_paid': 0,
            'average_confirmation_time': 0.0
        }
        
        # Cache pour les token info
        self._token_info_cache = {}
        self._price_cache = {}
        self._cache_lock = asyncio.Lock()
        
        self.logger.info(f"Solana client initialized for {self.config.rpc_url}")
    
    def _setup_rpc_clients(self):
        """Setup RPC clients with failover"""
        try:
            commitment = Commitment(self.config.commitment)
            
            # Client principal
            self.client = Client(
                self.config.rpc_url,
                commitment=commitment,
                timeout=self.config.transaction_timeout
            )
            
            # Client asynchrone
            self.async_client = AsyncClient(
                self.config.rpc_url,
                commitment=commitment,
                timeout=self.config.transaction_timeout
            )
            
            # Clients de backup
            self.backup_clients = []
            for backup_url in self.config.backup_rpc_urls:
                try:
                    backup_client = Client(backup_url, commitment=commitment)
                    self.backup_clients.append(backup_client)
                except Exception as e:
                    self.logger.warning(f"Failed to setup backup client {backup_url}: {e}")
            
            self.logger.info(f"RPC clients setup: 1 primary + {len(self.backup_clients)} backup")
            
        except Exception as e:
            self.logger.error(f"Failed to setup RPC clients: {e}")
            raise SolanaClientError(f"RPC setup failed: {e}")
    
    def _setup_wallet(self):
        """Setup wallet from private key"""
        try:
            if self.config.private_key:
                # Parse private key (support multiple formats)
                if self.config.private_key.startswith('['):
                    # Array format [1,2,3,...]
                    key_array = json.loads(self.config.private_key)
                    self.keypair = Keypair.from_secret_key(bytes(key_array))
                elif len(self.config.private_key) == 88:
                    # Base58 format
                    import base58
                    secret_key = base58.b58decode(self.config.private_key)
                    self.keypair = Keypair.from_secret_key(secret_key)
                else:
                    # Hex format
                    secret_key = bytes.fromhex(self.config.private_key)
                    self.keypair = Keypair.from_secret_key(secret_key)
                
                self.public_key = self.keypair.public_key
                self.wallet_address = str(self.public_key)
                
                self.logger.info(f"Wallet loaded: {self.wallet_address}")
                
            else:
                # Generate new wallet for testing
                self.keypair = Keypair.generate()
                self.public_key = self.keypair.public_key
                self.wallet_address = str(self.public_key)
                
                self.logger.warning(f"Generated new wallet: {self.wallet_address}")
                
        except Exception as e:
            self.logger.error(f"Failed to setup wallet: {e}")
            raise SolanaClientError(f"Wallet setup failed: {e}")
    
    async def get_balance(self, token_address: Optional[str] = None) -> Union[float, WalletBalance]:
        """
        Get wallet balance for SOL or specific token
        
        Args:
            token_address: Token mint address (None for SOL)
            
        Returns:
            Float for single token, WalletBalance for complete balance
        """
        try:
            if token_address is None:
                # Get SOL balance
                response = await self.async_client.get_balance(self.public_key)
                sol_balance = response.value / 1e9  # Convert lamports to SOL
                return sol_balance
            
            elif token_address == 'ALL':
                # Get complete wallet balance
                return await self._get_complete_balance()
            
            else:
                # Get specific token balance
                return await self._get_token_balance(token_address)
                
        except Exception as e:
            self.logger.error(f"Failed to get balance: {e}")
            return 0.0
    
    async def _get_complete_balance(self) -> WalletBalance:
        """Get complete wallet balance including all tokens"""
        try:
            # Get SOL balance
            sol_response = await self.async_client.get_balance(self.public_key)
            sol_balance = sol_response.value / 1e9
            
            # Get token accounts
            token_accounts = await self.async_client.get_token_accounts_by_owner(
                self.public_key,
                {"programId": TOKEN_PROGRAM_ID}
            )
            
            token_balances = {}
            total_value_usd = 0.0
            
            for account in token_accounts.value:
                try:
                    # Parse token account data
                    account_data = account.account.data
                    if isinstance(account_data, str):
                        # Base64 encoded data
                        decoded_data = base64.b64decode(account_data)
                    else:
                        decoded_data = account_data
                    
                    # Extract mint and amount from token account data
                    # Token account structure: mint(32) + owner(32) + amount(8) + ...
                    if len(decoded_data) >= 72:
                        mint_bytes = decoded_data[0:32]
                        amount_bytes = decoded_data[64:72]
                        
                        mint_address = str(PublicKey(mint_bytes))
                        amount = struct.unpack('<Q', amount_bytes)[0]
                        
                        if amount > 0:
                            # Get token info for decimals
                            token_info = await self.get_token_info(mint_address)
                            if token_info:
                                balance = amount / (10 ** token_info.decimals)
                                token_balances[mint_address] = balance
                
                except Exception as e:
                    self.logger.debug(f"Error parsing token account: {e}")
                    continue
            
            # TODO: Calculate USD values using price feeds
            # For now, just use SOL value estimation
            total_value_usd = sol_balance * 100  # Rough SOL price estimate
            
            return WalletBalance(
                sol_balance=sol_balance,
                token_balances=token_balances,
                total_value_usd=total_value_usd
            )
            
        except Exception as e:
            self.logger.error(f"Failed to get complete balance: {e}")
            return WalletBalance(
                sol_balance=0.0,
                token_balances={},
                total_value_usd=0.0
            )
    
    async def _get_token_balance(self, token_address: str) -> float:
        """Get balance for specific token"""
        try:
            token_mint = PublicKey(token_address)
            
            # Get associated token account
            ata = get_associated_token_address(self.public_key, token_mint)
            
            # Check if account exists
            account_info = await self.async_client.get_account_info(ata)
            if not account_info.value:
                return 0.0
            
            # Get token account info
            token_account = await self.async_client.get_token_account_balance(ata)
            if token_account.value:
                return float(token_account.value.ui_amount or 0.0)
            
            return 0.0
            
        except Exception as e:
            self.logger.debug(f"Failed to get token balance for {token_address}: {e}")
            return 0.0
    
    async def get_token_info(self, token_address: str) -> Optional[TokenInfo]:
        """Get token information from mint account"""
        try:
            # Check cache first
            if token_address in self._token_info_cache:
                return self._token_info_cache[token_address]
            
            token_mint = PublicKey(token_address)
            
            # Get mint account info
            mint_info = await self.async_client.get_account_info(token_mint)
            if not mint_info.value:
                return None
            
            # Parse mint account data
            data = mint_info.value.data
            if isinstance(data, str):
                decoded_data = base64.b64decode(data)
            else:
                decoded_data = data
            
            if len(decoded_data) >= 82:
                # Mint account structure
                mint_authority_option = decoded_data[0:4]
                mint_authority = decoded_data[4:36] if mint_authority_option != b'\x00\x00\x00\x00' else None
                supply = struct.unpack('<Q', decoded_data[36:44])[0]
                decimals = decoded_data[44]
                is_initialized = decoded_data[45] != 0
                freeze_authority_option = decoded_data[46:50]
                freeze_authority = decoded_data[50:82] if freeze_authority_option != b'\x00\x00\x00\x00' else None
                
                token_info = TokenInfo(
                    address=token_address,
                    symbol="UNKNOWN",  # Would need metadata to get symbol
                    name="Unknown Token",
                    decimals=decimals,
                    mint_authority=str(PublicKey(mint_authority)) if mint_authority else None,
                    freeze_authority=str(PublicKey(freeze_authority)) if freeze_authority else None,
                    supply=supply,
                    is_initialized=is_initialized
                )
                
                # Cache result
                self._token_info_cache[token_address] = token_info
                return token_info
            
            return None
            
        except Exception as e:
            self.logger.error(f"Failed to get token info for {token_address}: {e}")
            return None
    
    async def get_swap_quote(self, params: SwapParams) -> Optional[SwapQuote]:
        """Get swap quote from Jupiter aggregator"""
        try:
            if not JUPITER_AVAILABLE:
                raise SolanaClientError("Jupiter not available - requests library required")
            
            # Get token info for decimals
            input_token_info = await self.get_token_info(params.input_token)
            if not input_token_info:
                raise SolanaClientError(f"Could not get info for input token {params.input_token}")
            
            # Convert amount to raw units
            input_amount = int(params.amount * (10 ** input_token_info.decimals))
            slippage_bps = int(params.slippage * 10000)  # Convert to basis points
            
            # Jupiter quote API request
            quote_params = {
                'inputMint': params.input_token,
                'outputMint': params.output_token,
                'amount': input_amount,
                'slippageBps': slippage_bps,
                'onlyDirectRoutes': False,
                'maxAccounts': 20
            }
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'jupiter_quote_request',
                                               f'🔄 JUPITER: Requesting quote for {params.amount} tokens')
            
            response = requests.get(
                f"{self.JUPITER_API_V6}/quote",
                params=quote_params,
                timeout=10
            )
            
            if response.status_code != 200:
                raise SolanaClientError(f"Jupiter quote failed: {response.status_code}")
            
            quote_data = response.json()
            
            # Calculate price impact
            price_impact = float(quote_data.get('priceImpactPct', 0))
            if price_impact > params.max_price_impact:
                raise SlippageExceededError(f"Price impact {price_impact:.2%} exceeds max {params.max_price_impact:.2%}")
            
            # Parse route plan
            route_plan = quote_data.get('routePlan', [])
            
            swap_quote = SwapQuote(
                input_mint=params.input_token,
                output_mint=params.output_token,
                input_amount=input_amount,
                output_amount=int(quote_data['outAmount']),
                other_amount_threshold=int(quote_data['otherAmountThreshold']),
                swap_mode=quote_data.get('swapMode', 'ExactIn'),
                slippage_bps=slippage_bps,
                price_impact_pct=price_impact,
                route_plan=route_plan,
                dex=DEXType.JUPITER
            )
            
            if self.advanced_logger:
                output_amount_ui = swap_quote.output_amount / (10 ** input_token_info.decimals)  # Approximation
                self.advanced_logger.debug_step('trading', 'jupiter_quote_success',
                                               f'✅ JUPITER: Quote received - {output_amount_ui:.6f} output, {price_impact:.3%} impact')
            
            return swap_quote
            
        except Exception as e:
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'jupiter_quote_error',
                                               f'❌ JUPITER: Quote failed - {e}')
            self.logger.error(f"Failed to get swap quote: {e}")
            return None
    
    async def execute_swap(self, quote: SwapQuote, simulate_first: bool = True) -> Optional[TransactionResult]:
        """Execute token swap using Jupiter"""
        try:
            if simulate_first:
                # Simulate transaction first
                simulation_result = await self._simulate_swap(quote)
                if not simulation_result:
                    raise TransactionFailedError("Swap simulation failed")
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'swap_execution_start',
                                               f'🔄 SWAP: Executing swap via Jupiter')
            
            # Get swap transaction from Jupiter
            swap_request = {
                'quoteResponse': {
                    'inputMint': quote.input_mint,
                    'outputMint': quote.output_mint,
                    'inAmount': str(quote.input_amount),
                    'outAmount': str(quote.output_amount),
                    'otherAmountThreshold': str(quote.other_amount_threshold),
                    'swapMode': quote.swap_mode,
                    'slippageBps': quote.slippage_bps,
                    'routePlan': quote.route_plan
                },
                'userPublicKey': str(self.public_key),
                'wrapAndUnwrapSol': True,
                'computeUnitPriceMicroLamports': self.config.compute_unit_price,
                'prioritizationFeeLamports': self.config.priority_fee_lamports
            }
            
            response = requests.post(
                f"{self.JUPITER_API_V6}/swap",
                json=swap_request,
                timeout=30
            )
            
            if response.status_code != 200:
                raise TransactionFailedError(f"Jupiter swap API failed: {response.status_code}")
            
            swap_data = response.json()
            
            # Deserialize and sign transaction
            transaction_bytes = base64.b64decode(swap_data['swapTransaction'])
            transaction = Transaction.deserialize(transaction_bytes)
            
            # Sign transaction
            transaction.sign(self.keypair)
            
            # Send transaction
            result = await self._send_and_confirm_transaction(transaction)
            
            if result.status == TransactionStatus.CONFIRMED:
                if self.advanced_logger:
                    self.advanced_logger.debug_step('trading', 'swap_execution_success',
                                                   f'✅ SWAP: Transaction confirmed - {result.signature}')
                
                # Update performance metrics
                self.performance_metrics['successful_transactions'] += 1
                if result.fee:
                    self.performance_metrics['total_fees_paid'] += result.fee
            else:
                if self.advanced_logger:
                    self.advanced_logger.debug_step('trading', 'swap_execution_failed',
                                                   f'❌ SWAP: Transaction failed - {result.error}')
                
                self.performance_metrics['failed_transactions'] += 1
            
            self.performance_metrics['total_transactions'] += 1
            return result
            
        except Exception as e:
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'swap_execution_error',
                                               f'❌ SWAP: Execution error - {e}')
            self.logger.error(f"Failed to execute swap: {e}")
            self.performance_metrics['failed_transactions'] += 1
            self.performance_metrics['total_transactions'] += 1
            return None
    
    async def _simulate_swap(self, quote: SwapQuote) -> bool:
        """Simulate swap transaction before execution"""
        try:
            # This would require getting the transaction first and simulating it
            # For now, we'll do basic validation
            
            # Check if we have enough input token balance
            input_balance = await self._get_token_balance(quote.input_mint)
            input_token_info = await self.get_token_info(quote.input_mint)
            
            if input_token_info:
                required_amount = quote.input_amount / (10 ** input_token_info.decimals)
                if input_balance < required_amount:
                    raise InsufficientFundsError(f"Insufficient balance: {input_balance} < {required_amount}")
            
            # Check SOL balance for fees
            sol_balance = await self.get_balance()
            if sol_balance < 0.01:  # Need at least 0.01 SOL for fees
                raise InsufficientFundsError("Insufficient SOL for transaction fees")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Swap simulation failed: {e}")
            return False
    
    async def _send_and_confirm_transaction(self, transaction: Transaction) -> TransactionResult:
        """Send transaction and wait for confirmation"""
        try:
            start_time = time.time()
            
            # Send transaction
            tx_opts = TxOpts(
                skip_confirmation=False,
                skip_preflight=False,
                preflight_commitment=Commitment("confirmed"),
                max_retries=self.config.max_retries
            )
            
            response = await self.async_client.send_transaction(
                transaction,
                opts=tx_opts
            )
            
            signature = str(response.value)
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'transaction_sent',
                                               f'📤 TX: Sent transaction {signature[:8]}...')
            
            # Wait for confirmation
            confirmation_start = time.time()
            confirmed = False
            
            for attempt in range(self.config.max_retries):
                try:
                    # Check transaction status
                    status_response = await self.async_client.get_signature_statuses([signature])
                    
                    if status_response.value and status_response.value[0]:
                        status_info = status_response.value[0]
                        
                        if status_info.confirmation_status == "confirmed" or status_info.confirmation_status == "finalized":
                            confirmed = True
                            break
                        elif status_info.err:
                            # Transaction failed
                            error_msg = str(status_info.err)
                            return TransactionResult(
                                signature=signature,
                                status=TransactionStatus.FAILED,
                                error=error_msg
                            )
                    
                    # Check timeout
                    if time.time() - confirmation_start > self.config.confirmation_timeout:
                        return TransactionResult(
                            signature=signature,
                            status=TransactionStatus.TIMEOUT,
                            error="Confirmation timeout"
                        )
                    
                    await asyncio.sleep(1)  # Wait 1 second before next check
                    
                except Exception as e:
                    self.logger.debug(f"Error checking transaction status: {e}")
                    await asyncio.sleep(2)
            
            if confirmed:
                # Get final transaction details
                try:
                    tx_details = await self.async_client.get_transaction(
                        signature,
                        encoding="json",
                        commitment=Commitment("confirmed")
                    )
                    
                    if tx_details.value:
                        confirmation_time = time.time() - start_time
                        
                        # Update average confirmation time
                        current_avg = self.performance_metrics['average_confirmation_time']
                        total_txs = self.performance_metrics['total_transactions']
                        new_avg = ((current_avg * total_txs) + confirmation_time) / (total_txs + 1)
                        self.performance_metrics['average_confirmation_time'] = new_avg
                        
                        return TransactionResult(
                            signature=signature,
                            status=TransactionStatus.CONFIRMED,
                            slot=tx_details.value.slot,
                            block_time=tx_details.value.block_time,
                            fee=tx_details.value.transaction.meta.fee if tx_details.value.transaction.meta else None,
                            logs=tx_details.value.transaction.meta.log_messages if tx_details.value.transaction.meta else [],
                            compute_units_consumed=tx_details.value.transaction.meta.compute_units_consumed if tx_details.value.transaction.meta else None
                        )
                
                except Exception as e:
                    self.logger.debug(f"Error getting transaction details: {e}")
                
                # Return basic confirmed result if details fetch failed
                return TransactionResult(
                    signature=signature,
                    status=TransactionStatus.CONFIRMED
                )
            
            else:
                return TransactionResult(
                    signature=signature,
                    status=TransactionStatus.TIMEOUT,
                    error="Transaction not confirmed within timeout"
                )
                
        except Exception as e:
            self.logger.error(f"Failed to send transaction: {e}")
            return TransactionResult(
                signature="",
                status=TransactionStatus.FAILED,
                error=str(e)
            )
    
    async def transfer_sol(self, to_address: str, amount: float) -> Optional[TransactionResult]:
        """Transfer SOL to another wallet"""
        try:
            to_pubkey = PublicKey(to_address)
            
            # Check balance
            current_balance = await self.get_balance()
            if current_balance < amount + 0.001:  # Reserve for fees
                raise InsufficientFundsError(f"Insufficient SOL: {current_balance} < {amount + 0.001}")
            
            # Convert SOL to lamports
            lamports = int(amount * 1e9)
            
            # Create transfer instruction
            transfer_instruction = transfer(
                TransferParams(
                    from_pubkey=self.public_key,
                    to_pubkey=to_pubkey,
                    lamports=lamports
                )
            )
            
            # Create transaction
            transaction = Transaction()
            transaction.add(transfer_instruction)
            
            # Get recent blockhash
            recent_blockhash = await self.async_client.get_latest_blockhash()
            transaction.recent_blockhash = recent_blockhash.value.blockhash
            
            # Sign and send
            transaction.sign(self.keypair)
            result = await self._send_and_confirm_transaction(transaction)
            
            if self.advanced_logger:
                status = "✅" if result.status == TransactionStatus.CONFIRMED else "❌"
                self.advanced_logger.debug_step('trading', 'sol_transfer_complete',
                                               f'{status} SOL Transfer: {amount} SOL to {to_address[:8]}...')
            
            return result
            
        except Exception as e:
            self.logger.error(f"Failed to transfer SOL: {e}")
            return None
    
    async def transfer_token(self, token_address: str, to_address: str, amount: float) -> Optional[TransactionResult]:
        """Transfer SPL token to another wallet"""
        try:
            token_mint = PublicKey(token_address)
            to_pubkey = PublicKey(to_address)
            
            # Get token info
            token_info = await self.get_token_info(token_address)
            if not token_info:
                raise SolanaClientError(f"Could not get token info for {token_address}")
            
            # Check balance
            current_balance = await self._get_token_balance(token_address)
            if current_balance < amount:
                raise InsufficientFundsError(f"Insufficient token balance: {current_balance} < {amount}")
            
            # Convert to raw amount
            raw_amount = int(amount * (10 ** token_info.decimals))
            
            # Get source token account
            source_ata = get_associated_token_address(self.public_key, token_mint)
            
            # Get or create destination token account
            dest_ata = get_associated_token_address(to_pubkey, token_mint)
            
            # Check if destination account exists
            dest_account_info = await self.async_client.get_account_info(dest_ata)
            
            transaction = Transaction()
            
            # Create destination account if it doesn't exist
            if not dest_account_info.value:
                create_ata_instruction = create_associated_token_account(
                    payer=self.public_key,
                    owner=to_pubkey,
                    mint=token_mint
                )
                transaction.add(create_ata_instruction)
            
            # Create transfer instruction
            transfer_instruction = transfer_checked(
                TransferCheckedParams(
                    program_id=TOKEN_PROGRAM_ID,
                    source=source_ata,
                    mint=token_mint,
                    dest=dest_ata,
                    owner=self.public_key,
                    amount=raw_amount,
                    decimals=token_info.decimals
                )
            )
            transaction.add(transfer_instruction)
            
            # Get recent blockhash
            recent_blockhash = await self.async_client.get_latest_blockhash()
            transaction.recent_blockhash = recent_blockhash.value.blockhash
            
            # Sign and send
            transaction.sign(self.keypair)
            result = await self._send_and_confirm_transaction(transaction)
            
            if self.advanced_logger:
                status = "✅" if result.status == TransactionStatus.CONFIRMED else "❌"
                self.advanced_logger.debug_step('trading', 'token_transfer_complete',
                                               f'{status} Token Transfer: {amount} {token_info.symbol} to {to_address[:8]}...')
            
            return result
            
        except Exception as e:
            self.logger.error(f"Failed to transfer token: {e}")
            return None
    
    async def buy_token(self, token_address: str, sol_amount: float, max_slippage: float = 0.01) -> Optional[TransactionResult]:
        """Buy token with SOL"""
        try:
            # Create swap parameters
            params = SwapParams(
                input_token=self.COMMON_TOKENS['SOL'],  # Wrapped SOL
                output_token=token_address,
                amount=sol_amount,
                slippage=max_slippage,
                dex_preference=DEXType.JUPITER
            )
            
            # Get quote
            quote = await self.get_swap_quote(params)
            if not quote:
                raise SolanaClientError("Could not get swap quote")
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'buy_token_start',
                                               f'💰 BUY: {sol_amount} SOL → {token_address[:8]}... (slippage: {max_slippage:.1%})')
            
            # Execute swap
            result = await self.execute_swap(quote)
            
            if result and result.status == TransactionStatus.CONFIRMED:
                if self.advanced_logger:
                    self.advanced_logger.debug_step('trading', 'buy_token_success',
                                                   f'✅ BUY: Token purchase confirmed - {result.signature[:8]}...')
            
            return result
            
        except Exception as e:
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'buy_token_error',
                                               f'❌ BUY: Purchase failed - {e}')
            self.logger.error(f"Failed to buy token: {e}")
            return None
    
    async def sell_token(self, token_address: str, amount: float, max_slippage: float = 0.01) -> Optional[TransactionResult]:
        """Sell token for SOL"""
        try:
            # Create swap parameters
            params = SwapParams(
                input_token=token_address,
                output_token=self.COMMON_TOKENS['SOL'],  # Wrapped SOL
                amount=amount,
                slippage=max_slippage,
                dex_preference=DEXType.JUPITER
            )
            
            # Get quote
            quote = await self.get_swap_quote(params)
            if not quote:
                raise SolanaClientError("Could not get swap quote")
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'sell_token_start',
                                               f'💸 SELL: {amount} tokens → SOL (slippage: {max_slippage:.1%})')
            
            # Execute swap
            result = await self.execute_swap(quote)
            
            if result and result.status == TransactionStatus.CONFIRMED:
                if self.advanced_logger:
                    self.advanced_logger.debug_step('trading', 'sell_token_success',
                                                   f'✅ SELL: Token sale confirmed - {result.signature[:8]}...')
            
            return result
            
        except Exception as e:
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'sell_token_error',
                                               f'❌ SELL: Sale failed - {e}')
            self.logger.error(f"Failed to sell token: {e}")
            return None
    
    async def get_token_price(self, token_address: str, vs_currency: str = 'SOL') -> Optional[float]:
        """Get current token price"""
        try:
            # Check cache first
            cache_key = f"{token_address}_{vs_currency}"
            if cache_key in self._price_cache:
                cached_price, cached_time = self._price_cache[cache_key]
                if time.time() - cached_time < 30:  # 30 second cache
                    return cached_price
            
            # Use Jupiter quote API to get price
            if vs_currency == 'SOL':
                quote_currency = self.COMMON_TOKENS['SOL']
            elif vs_currency == 'USDC':
                quote_currency = self.COMMON_TOKENS['USDC']
            else:
                quote_currency = vs_currency
            
            # Get token info for decimals
            token_info = await self.get_token_info(token_address)
            if not token_info:
                return None
            
            # Use 1 token as base amount
            base_amount = 10 ** token_info.decimals
            
            # Get quote for 1 token
            quote_params = {
                'inputMint': token_address,
                'outputMint': quote_currency,
                'amount': base_amount,
                'slippageBps': 50  # 0.5% slippage
            }
            
            response = requests.get(
                f"{self.JUPITER_API_V6}/quote",
                params=quote_params,
                timeout=5
            )
            
            if response.status_code == 200:
                quote_data = response.json()
                output_amount = int(quote_data['outAmount'])
                
                # Get quote currency decimals
                if quote_currency == self.COMMON_TOKENS['SOL']:
                    quote_decimals = 9
                elif quote_currency == self.COMMON_TOKENS['USDC']:
                    quote_decimals = 6
                else:
                    quote_info = await self.get_token_info(quote_currency)
                    quote_decimals = quote_info.decimals if quote_info else 9
                
                price = output_amount / (10 ** quote_decimals)
                
                # Cache result
                self._price_cache[cache_key] = (price, time.time())
                
                return price
            
            return None
            
        except Exception as e:
            self.logger.debug(f"Failed to get token price: {e}")
            return None
    
    async def create_associated_token_account(self, token_address: str, owner: Optional[str] = None) -> Optional[TransactionResult]:
        """Create associated token account for a token"""
        try:
            token_mint = PublicKey(token_address)
            owner_pubkey = PublicKey(owner) if owner else self.public_key
            
            # Check if account already exists
            ata = get_associated_token_address(owner_pubkey, token_mint)
            account_info = await self.async_client.get_account_info(ata)
            
            if account_info.value:
                self.logger.info(f"Associated token account already exists: {ata}")
                return TransactionResult(
                    signature="",
                    status=TransactionStatus.CONFIRMED,
                    error="Account already exists"
                )
            
            # Create account
            create_instruction = create_associated_token_account(
                payer=self.public_key,
                owner=owner_pubkey,
                mint=token_mint
            )
            
            transaction = Transaction()
            transaction.add(create_instruction)
            
            # Get recent blockhash
            recent_blockhash = await self.async_client.get_latest_blockhash()
            transaction.recent_blockhash = recent_blockhash.value.blockhash
            
            # Sign and send
            transaction.sign(self.keypair)
            result = await self._send_and_confirm_transaction(transaction)
            
            if self.advanced_logger:
                status = "✅" if result.status == TransactionStatus.CONFIRMED else "❌"
                self.advanced_logger.debug_step('trading', 'create_ata_complete',
                                               f'{status} ATA Created: {token_address[:8]}... for {str(owner_pubkey)[:8]}...')
            
            return result
            
        except Exception as e:
            self.logger.error(f"Failed to create associated token account: {e}")
            return None
    
    def calculate_slippage(self, expected_amount: float, actual_amount: float) -> float:
        """Calculate slippage percentage"""
        if expected_amount == 0:
            return 0.0
        return abs(expected_amount - actual_amount) / expected_amount * 100
    
    def calculate_price_impact(self, input_amount: float, output_amount: float, market_price: float) -> float:
        """Calculate price impact percentage"""
        if market_price == 0:
            return 0.0
        
        effective_price = output_amount / input_amount
        return abs(market_price - effective_price) / market_price * 100
    
    async def estimate_transaction_fee(self, transaction: Transaction) -> Optional[int]:
        """Estimate transaction fee in lamports"""
        try:
            # Simulate transaction to get fee estimate
            simulation = await self.async_client.simulate_transaction(transaction)
            
            if simulation.value and simulation.value.err is None:
                # Base fee calculation (5000 lamports per signature)
                base_fee = 5000 * len(transaction.signatures)
                
                # Add compute unit fee if any
                compute_fee = 0
                if hasattr(simulation.value, 'units_consumed'):
                    compute_fee = simulation.value.units_consumed * self.config.compute_unit_price
                
                total_fee = base_fee + compute_fee + self.config.priority_fee_lamports
                return total_fee
            
            # Fallback estimation
            return 10000  # 0.00001 SOL
            
        except Exception as e:
            self.logger.debug(f"Failed to estimate transaction fee: {e}")
            return 10000  # Default fallback
    
    async def get_transaction_history(self, limit: int = 10) -> List[Dict]:
        """Get transaction history for wallet"""
        try:
            signatures = await self.async_client.get_signatures_for_address(
                self.public_key,
                limit=limit
            )
            
            transactions = []
            for sig_info in signatures.value:
                try:
                    tx_details = await self.async_client.get_transaction(
                        sig_info.signature,
                        encoding="json"
                    )
                    
                    if tx_details.value:
                        transactions.append({
                            'signature': sig_info.signature,
                            'slot': sig_info.slot,
                            'block_time': sig_info.block_time,
                            'status': 'confirmed' if not sig_info.err else 'failed',
                            'fee': tx_details.value.transaction.meta.fee if tx_details.value.transaction.meta else 0,
                            'error': str(sig_info.err) if sig_info.err else None
                        })
                        
                except Exception as e:
                    self.logger.debug(f"Error getting transaction details: {e}")
                    continue
            
            return transactions
            
        except Exception as e:
            self.logger.error(f"Failed to get transaction history: {e}")
            return []
    
    async def monitor_transaction(self, signature: str, timeout: int = 60) -> TransactionStatus:
        """Monitor transaction status until confirmed or timeout"""
        try:
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                try:
                    status_response = await self.async_client.get_signature_statuses([signature])
                    
                    if status_response.value and status_response.value[0]:
                        status_info = status_response.value[0]
                        
                        if status_info.confirmation_status == "finalized":
                            return TransactionStatus.FINALIZED
                        elif status_info.confirmation_status == "confirmed":
                            return TransactionStatus.CONFIRMED
                        elif status_info.err:
                            return TransactionStatus.FAILED
                    
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    self.logger.debug(f"Error monitoring transaction: {e}")
                    await asyncio.sleep(5)
            
            return TransactionStatus.TIMEOUT
            
        except Exception as e:
            self.logger.error(f"Failed to monitor transaction: {e}")
            return TransactionStatus.FAILED
    
    def get_performance_metrics(self) -> Dict:
        """Get client performance metrics"""
        total_txs = self.performance_metrics['total_transactions']
        success_rate = (self.performance_metrics['successful_transactions'] / max(total_txs, 1)) * 100
        
        return {
            'total_transactions': total_txs,
            'successful_transactions': self.performance_metrics['successful_transactions'],
            'failed_transactions': self.performance_metrics['failed_transactions'],
            'success_rate_percent': success_rate,
            'total_fees_paid_lamports': self.performance_metrics['total_fees_paid'],
            'total_fees_paid_sol': self.performance_metrics['total_fees_paid'] / 1e9,
            'average_confirmation_time_seconds': self.performance_metrics['average_confirmation_time'],
            'wallet_address': self.wallet_address
        }
    
    async def health_check(self) -> Dict:
        """Perform health check on client and RPC connection"""
        health_status = {
            'timestamp': datetime.now().isoformat(),
            'wallet_address': self.wallet_address,
            'rpc_connection': False,
            'sol_balance': 0.0,
            'recent_blockhash': None,
            'rpc_latency_ms': 0.0
        }
        
        try:
            # Test RPC connection with latency measurement
            start_time = time.time()
            
            # Get recent blockhash (simple RPC test)
            blockhash_response = await self.async_client.get_latest_blockhash()
            
            end_time = time.time()
            health_status['rpc_latency_ms'] = (end_time - start_time) * 1000
            
            if blockhash_response.value:
                health_status['rpc_connection'] = True
                health_status['recent_blockhash'] = str(blockhash_response.value.blockhash)
            
            # Get SOL balance
            balance = await self.get_balance()
            health_status['sol_balance'] = balance
            
            health_status['status'] = 'healthy' if health_status['rpc_connection'] else 'unhealthy'
            
        except Exception as e:
            health_status['status'] = 'unhealthy'
            health_status['error'] = str(e)
            self.logger.error(f"Health check failed: {e}")
        
        return health_status
    
    async def close(self):
        """Close client connections"""
        try:
            if hasattr(self, 'async_client'):
                await self.async_client.close()
            
            if hasattr(self, 'client'):
                self.client.close()
            
            self.logger.info("Solana client connections closed")
            
        except Exception as e:
            self.logger.error(f"Error closing client: {e}")
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        asyncio.create_task(self.close())
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# Utility functions and helpers

def create_solana_client(config: Dict, advanced_logger=None) -> SolanaClient:
    """Factory function to create Solana client"""
    solana_config = SolanaConfig(
        rpc_url=config['solana']['rpc_url'],
        backup_rpc_urls=config['solana']['backup_rpc_urls'],
        private_key=config['solana']['wallet_private_key'],
        commitment=config['solana'].get('commitment', 'confirmed'),
        transaction_timeout=config['solana'].get('transaction_timeout', 60),
        confirmation_timeout=config['solana'].get('confirmation_timeout', 30),
        max_retries=config['solana'].get('max_retries', 3),
        retry_delay=config['solana'].get('retry_delay', 2),
        priority_fee_lamports=config['solana'].get('priority_fee_lamports', 10000),
        compute_unit_limit=config['solana'].get('compute_unit_limit', 300000),
        compute_unit_price=config['solana'].get('compute_unit_price', 1000)
    )
    
    return SolanaClient(solana_config, advanced_logger)


async def quick_buy(token_address: str, sol_amount: float, config: Dict) -> Optional[str]:
    """Quick buy utility function"""
    try:
        async with create_solana_client(config) as client:
            result = await client.buy_token(token_address, sol_amount)
            return result.signature if result and result.status == TransactionStatus.CONFIRMED else None
    except Exception as e:
        logging.getLogger(__name__).error(f"Quick buy failed: {e}")
        return None


async def quick_sell(token_address: str, amount: float, config: Dict) -> Optional[str]:
    """Quick sell utility function"""
    try:
        async with create_solana_client(config) as client:
            result = await client.sell_token(token_address, amount)
            return result.signature if result and result.status == TransactionStatus.CONFIRMED else None
    except Exception as e:
        logging.getLogger(__name__).error(f"Quick sell failed: {e}")
        return None


async def get_wallet_value(wallet_address: str, config: Dict) -> Dict:
    """Get total wallet value utility"""
    try:
        # Create temporary client for reading (no private key needed)
        temp_config = SolanaConfig(
            rpc_url=config['solana']['rpc_url'],
            backup_rpc_urls=config['solana']['backup_rpc_urls'],
            private_key=""  # Empty for read-only
        )
        
        async with SolanaClient(temp_config) as client:
            # Override public key for read-only operations
            client.public_key = PublicKey(wallet_address)
            
            balance = await client.get_balance('ALL')
            return {
                'wallet_address': wallet_address,
                'sol_balance': balance.sol_balance,
                'token_count': len(balance.token_balances),
                'total_value_usd': balance.total_value_usd,
                'last_updated': balance.last_updated.isoformat()
            }
    except Exception as e:
        logging.getLogger(__name__).error(f"Failed to get wallet value: {e}")
        return {'error': str(e)}


# Example usage and testing

async def test_solana_client():
    """Test Solana client functionality"""
    print("Testing Solana Client...")
    
    # Example configuration
    config = {
        'solana': {
            'rpc_url': 'https://api.mainnet-beta.solana.com',
            'backup_rpc_urls': [
                'https://solana-api.projectserum.com',
                'https://rpc.ankr.com/solana'
            ],
            'wallet_private_key': '',  # Add your private key for testing
            'commitment': 'confirmed',
            'transaction_timeout': 60,
            'confirmation_timeout': 30,
            'max_retries': 3,
            'retry_delay': 2,
            'priority_fee_lamports': 10000,
            'compute_unit_limit': 300000,
            'compute_unit_price': 1000
        }
    }
    
    if not config['solana']['wallet_private_key']:
        print("❌ No private key configured - skipping transaction tests")
        return
    
    try:
        async with create_solana_client(config) as client:
            print(f"✅ Client created for wallet: {client.wallet_address}")
            
            # Health check
            health = await client.health_check()
            print(f"🏥 Health check: {health['status']} (latency: {health['rpc_latency_ms']:.1f}ms)")
            
            # Get balance
            balance = await client.get_balance()
            print(f"💰 SOL balance: {balance:.6f}")
            
            # Get complete balance
            complete_balance = await client.get_balance('ALL')
            print(f"📊 Total tokens: {len(complete_balance.token_balances)}")
            
            # Test token price
            usdc_price = await client.get_token_price(client.COMMON_TOKENS['USDC'], 'SOL')
            if usdc_price:
                print(f"💱 USDC/SOL price: {usdc_price:.6f}")
            
            # Performance metrics
            metrics = client.get_performance_metrics()
            print(f"📈 Performance: {metrics['total_transactions']} transactions, {metrics['success_rate_percent']:.1f}% success")
            
            print("✅ All tests completed successfully!")
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        raise


if __name__ == "__main__":
    if not SOLANA_AVAILABLE:
        print("❌ Solana dependencies not installed")
        print("Run: pip install solana anchor-py spl-token requests")
    else:
        print("✅ Solana dependencies available")
        
        # Run tests
        try:
            asyncio.run(test_solana_client())
        except KeyboardInterrupt:
            print("\n🛑 Tests interrupted by user")
        except Exception as e:
            print(f"❌ Test error: {e}")
            import traceback
            traceback.print_exc()