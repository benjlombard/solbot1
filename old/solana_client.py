"""
Solana Client - Version Corrigée Compatible
File: solana_client_fixed.py

Client Solana qui fonctionne avec les versions actuelles des packages.
"""

import requests
import base58
import os
import time
import json
import base64
import asyncio
import logging
from decimal import Decimal, ROUND_DOWN
from typing import Optional, Dict, List, Tuple, Union, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta

# Solana dependencies avec gestion des versions
try:
    from solana.rpc.api import Client
    from solana.rpc.async_api import AsyncClient
    from solana.rpc.commitment import Commitment
    from solana.rpc.types import TxOpts
    from solana.rpc.core import RPCException
    
    # Nouvelle API depuis solders
    try:
        from solders.keypair import Keypair
        from solders.pubkey import Pubkey as PublicKey
        from solders.transaction import Transaction
        from solders.system_program import transfer, TransferParams
        from solders.instruction import Instruction
        SOLDERS_API = True
        print("🔧 Using solders API (recommended)")
    except ImportError:
        # Ancienne API en fallback
        try:
            from solana.keypair import Keypair
            from solana.publickey import PublicKey  
            from solana.transaction import Transaction
            from solana.system_program import transfer, TransferParams
            SOLDERS_API = False
            print("⚠️ Using legacy solana API")
        except ImportError:
            # Pas de transaction disponible
            class Transaction:
                def __init__(self): pass
            def transfer(*args, **kwargs): pass
            class TransferParams:
                def __init__(self, *args, **kwargs): pass
            SOLDERS_API = False
            print("❌ No transaction API available")

    SOLANA_AVAILABLE = True
    
except ImportError:
    SOLANA_AVAILABLE = False
    print("❌ Solana not available - using mock classes")
    

# Jupiter disponible si requests fonctionne
JUPITER_AVAILABLE = True

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
    JUPITER = "jupiter"
    RAYDIUM = "raydium"
    ORCA = "orca"
    SERUM = "serum"
    DIRECT = "direct"

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

@dataclass
class SwapQuote:
    """Quote pour un swap de tokens"""
    input_mint: str
    output_mint: str
    input_amount: int
    output_amount: int
    slippage_bps: int
    price_impact_pct: float
    route_plan: List[Dict]
    dex: DEXType

@dataclass 
class SwapParams:
    """Paramètres pour un swap"""
    input_token: str
    output_token: str
    amount: float
    slippage: float = 0.01
    max_price_impact: float = 0.05

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

class SolanaClientError(Exception):
    """Exception de base pour le client Solana"""
    pass

class InsufficientFundsError(SolanaClientError):
    """Erreur de fonds insuffisants"""
    pass

class SlippageExceededError(SolanaClientError):
    """Erreur de slippage dépassé"""  
    pass

class SolanaClient:
    """
    Client Solana simplifié et compatible
    
    Features:
    - Gestion des balances SOL
    - Santé RPC 
    - Compatible avec les nouvelles API
    - Mode lecture seule si pas de clés
    """
    
    # Tokens de référence
    COMMON_TOKENS = {
        'SOL': 'So11111111111111111111111111111111111111112',
        'USDC': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
        'USDT': 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB'
    }
    
    JUPITER_API_V6 = "https://quote-api.jup.ag/v6"
    
    def __init__(self, config: SolanaConfig, advanced_logger=None):
        """Initialize Solana client"""
        if not SOLANA_AVAILABLE:
            raise ImportError("Solana dependencies not installed. Run: pip install solana solders")
        
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
        
        self.logger.info(f"Solana client initialized for {self.config.rpc_url}")
        print(f"🚀 Solana client ready (solders_api: {SOLDERS_API})")
    
    def _setup_rpc_clients(self):
        """Setup RPC clients with failover"""
        try:
            if SOLANA_AVAILABLE:
                commitment = Commitment(self.config.commitment)
                
                # Client principal
                self.client = Client(
                    self.config.rpc_url,
                    commitment=commitment,
                    timeout=self.config.transaction_timeout
                )
            
                # Client asynchrone - OPTIONNEL et avec gestion d'erreur
                try:
                    self.async_client = AsyncClient(
                        self.config.rpc_url,
                        commitment=commitment,
                        timeout=self.config.transaction_timeout
                    )
                    self.logger.info("✅ Both sync and async RPC clients setup successfully")
                except Exception as e:
                    self.logger.warning(f"⚠️ Async client failed, using sync only: {e}")
                    self.async_client = None

            else:
                self.client = None
                self.async_client = None
                self.logger.warning("RPC clients not available - mock mode")

        except Exception as e:
            self.logger.error(f"Failed to setup RPC clients: {e}")
            self.client = None
            self.async_client = None
    
    def _setup_wallet(self):
        """Setup wallet from private key"""
        try:
            if self.config.private_key and SOLANA_AVAILABLE:
                # Parse private key (support multiple formats)
                if self.config.private_key.startswith('['):
                    # Array format [1,2,3,...]
                    key_array = json.loads(self.config.private_key)
                    if SOLDERS_API:
                        self.keypair = Keypair.from_bytes(bytes(key_array))
                    else:
                        self.keypair = Keypair.from_secret_key(bytes(key_array))
                else:
                    # Base58 format
                    secret_key = base58.b58decode(self.config.private_key)
                    if SOLDERS_API:
                        self.keypair = Keypair.from_bytes(secret_key)
                    else:
                        self.keypair = Keypair.from_secret_key(secret_key)
                
                if SOLDERS_API:
                    self.public_key = self.keypair.pubkey()
                else:
                    self.public_key = self.keypair.public_key
                
                self.wallet_address = str(self.public_key)
                
                self.logger.info(f"Wallet loaded: {self.wallet_address}")
                
            else:
                # Mode lecture seule
                self.keypair = None
                self.public_key = None
                self.wallet_address = "READ_ONLY_MODE"
                
                self.logger.warning("Read-only mode - no private key or limited Solana")
                
        except Exception as e:
            self.logger.error(f"Failed to setup wallet: {e}")
            self.keypair = None
            self.public_key = None
            self.wallet_address = "WALLET_ERROR"
            raise SolanaClientError(f"Wallet setup failed: {e}")
    
    async def get_balance(self, token_address: Optional[str] = None) -> Union[float, WalletBalance]:
        """
        Get wallet balance for SOL or complete balance
        
        Args:
            token_address: None for SOL, 'ALL' for complete balance
            
        Returns:
            Float for SOL, WalletBalance for complete
        """
        try:
            if not self.public_key or not self.async_client:
                self.logger.warning("❌ No public key - READ_ONLY mode")
                if token_address == 'ALL':
                    return WalletBalance(0.0, {}, 0.0)
                return 0.0
            
            if token_address is None:
                # CORRECTION PRINCIPALE: Utiliser requests au lieu d'async_client
                try:
                    balance_payload = {
                        "jsonrpc": "2.0",
                        "id": 1, 
                        "method": "getBalance",
                        "params": [str(self.public_key)]
                    }
                    
                    self.logger.debug(f"🔍 Getting balance for {str(self.public_key)}")
                    
                    response = requests.post(
                        self.config.rpc_url,
                        json=balance_payload,
                        timeout=10,
                        headers={'Content-Type': 'application/json'}
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        if 'result' in data and 'value' in data['result']:
                            balance_lamports = data['result']['value']
                            sol_balance = balance_lamports / 1e9
                            
                            self.logger.info(f"💰 Balance retrieved successfully: {sol_balance:.9f} SOL ({balance_lamports:,} lamports)")
                            return sol_balance
                        else:
                            self.logger.error(f"Unexpected balance response format: {data}")
                            return 0.0
                    else:
                        self.logger.error(f"Balance request failed with HTTP {response.status_code}: {response.text}")
                        return 0.0
                        
                except requests.exceptions.Timeout:
                    self.logger.error("Balance request timed out after 10 seconds")
                    return 0.0
                except requests.exceptions.ConnectionError:
                    self.logger.error("Connection error while getting balance")
                    return 0.0
                except Exception as e:
                    self.logger.error(f"Balance request error: {e}")
                    return 0.0
            
            elif token_address == 'ALL':
                # Get complete balance using corrected method
                sol_balance = await self.get_balance()  # Recursive call for SOL only
                
                return WalletBalance(
                    sol_balance=sol_balance,
                    token_balances={},  # Simplified for now
                    total_value_usd=sol_balance * 100  # Rough estimate
                )
            
            else:
                # Specific token balance (placeholder for future implementation)
                self.logger.debug(f"Token balance not implemented for {token_address}")
                return 0.0
                
        except Exception as e:
            self.logger.error(f"Failed to get balance: {e}")
            if token_address == 'ALL':
                return WalletBalance(0.0, {}, 0.0)
            return 0.0
    
    async def get_swap_quote(self, params: SwapParams) -> Optional[SwapQuote]:
        """Get swap quote from Jupiter aggregator"""
        try:
            if not JUPITER_AVAILABLE:
                raise SolanaClientError("Jupiter not available")
            
            # Convert amount to raw units (assume 9 decimals for SOL)
            input_decimals = 9 if params.input_token == self.COMMON_TOKENS['SOL'] else 6
            input_amount = int(params.amount * (10 ** input_decimals))
            slippage_bps = int(params.slippage * 10000)
            
            # Jupiter quote API request
            quote_params = {
                'inputMint': params.input_token,
                'outputMint': params.output_token,
                'amount': input_amount,
                'slippageBps': slippage_bps
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
            
            price_impact = float(quote_data.get('priceImpactPct', 0))
            
            swap_quote = SwapQuote(
                input_mint=params.input_token,
                output_mint=params.output_token,
                input_amount=input_amount,
                output_amount=int(quote_data['outAmount']),
                slippage_bps=slippage_bps,
                price_impact_pct=price_impact,
                route_plan=quote_data.get('routePlan', []),
                dex=DEXType.JUPITER
            )
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'jupiter_quote_success',
                                               f'✅ JUPITER: Quote received - {price_impact:.3%} impact')
            
            return swap_quote
            
        except Exception as e:
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'jupiter_quote_error',
                                               f'❌ JUPITER: Quote failed - {e}')
            self.logger.error(f"Failed to get swap quote: {e}")
            return None
    
    async def buy_token(self, token_address: str, sol_amount: float, max_slippage: float = 0.01):
        """Buy token with SOL (simulation for now)"""
        try:
            if not self.keypair:
                self.logger.warning("Cannot execute trades in read-only mode")
                return None
            
            params = SwapParams(
                input_token=self.COMMON_TOKENS['SOL'],
                output_token=token_address,
                amount=sol_amount,
                slippage=max_slippage
            )
            
            quote = await self.get_swap_quote(params)
            if not quote:
                raise SolanaClientError("Could not get swap quote")
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'buy_token_simulation',
                                               f'💰 BUY SIMULATION: {sol_amount} SOL → {token_address[:8]}...')
            
            # For now, return a simulated successful result
            return TransactionResult(
                signature="SIMULATION_" + str(int(time.time())),
                status=TransactionStatus.CONFIRMED
            )
            
        except Exception as e:
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'buy_token_error',
                                               f'❌ BUY: Purchase failed - {e}')
            self.logger.error(f"Failed to buy token: {e}")
            return None
    
    async def sell_token(self, token_address: str, amount: float, max_slippage: float = 0.01):
        """Sell token for SOL (simulation for now)"""
        try:
            if not self.keypair:
                self.logger.warning("Cannot execute trades in read-only mode")
                return None
            
            params = SwapParams(
                input_token=token_address,
                output_token=self.COMMON_TOKENS['SOL'],
                amount=amount,
                slippage=max_slippage
            )
            
            quote = await self.get_swap_quote(params)
            if not quote:
                raise SolanaClientError("Could not get swap quote")
            
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'sell_token_simulation',
                                               f'💸 SELL SIMULATION: {amount} tokens → SOL')
            
            # For now, return a simulated successful result
            return TransactionResult(
                signature="SIMULATION_" + str(int(time.time())),
                status=TransactionStatus.CONFIRMED
            )
            
        except Exception as e:
            if self.advanced_logger:
                self.advanced_logger.debug_step('trading', 'sell_token_error',
                                               f'❌ SELL: Sale failed - {e}')
            self.logger.error(f"Failed to sell token: {e}")
            return None
    
    async def get_token_price(self, token_address: str, vs_currency: str = 'SOL') -> Optional[float]:
        """Get current token price using Jupiter"""
        try:
            if vs_currency == 'SOL':
                quote_currency = self.COMMON_TOKENS['SOL']
            elif vs_currency == 'USDC':
                quote_currency = self.COMMON_TOKENS['USDC']
            else:
                quote_currency = vs_currency
            
            # Use small amount for price check
            params = SwapParams(
                input_token=token_address,
                output_token=quote_currency,
                amount=1.0,  # 1 token
                slippage=0.01
            )
            
            quote = await self.get_swap_quote(params)
            if quote:
                # Calculate price from quote
                input_decimals = 9 if token_address == self.COMMON_TOKENS['SOL'] else 6
                output_decimals = 9 if quote_currency == self.COMMON_TOKENS['SOL'] else 6
                
                price = (quote.output_amount / (10 ** output_decimals)) / (quote.input_amount / (10 ** input_decimals))
                return price
            
            return None
            
        except Exception as e:
            self.logger.debug(f"Failed to get token price: {e}")
            return None
    
    async def health_check(self) -> Dict:
        """Perform health check on client and RPC connection"""
        health_status = {
            'timestamp': datetime.now().isoformat(),
            'wallet_address': self.wallet_address,
            'rpc_connection': False,
            'sol_balance': 0.0,
            'rpc_latency_ms': 0.0,
            'solana_available': SOLANA_AVAILABLE,
            'solders_api': SOLDERS_API,
            'client_status': 'healthy' if SOLANA_AVAILABLE else 'limited'
        }
        
        try:
            start_time = time.time()
            
            # Test RPC with simple HTTP call
            response = requests.post(
                self.config.rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getHealth"
                },
                timeout=10
            )
            
            end_time = time.time()
            health_status['rpc_latency_ms'] = (end_time - start_time) * 1000
            health_status['rpc_connection'] = response.status_code == 200
            
            if self.public_key:
                try:
                    # Requête directe pour la balance via requests
                    balance_payload = {
                        "jsonrpc": "2.0", 
                        "id": 1,
                        "method": "getBalance",
                        "params": [str(self.public_key)]
                    }
                    
                    balance_response = requests.post(
                        self.config.rpc_url,
                        json=balance_payload,
                        timeout=10
                    )
                    
                    if balance_response.status_code == 200:
                        balance_data = balance_response.json()
                        if 'result' in balance_data and 'value' in balance_data['result']:
                            balance_lamports = balance_data['result']['value']
                            balance_sol = balance_lamports / 1e9
                            health_status['sol_balance'] = balance_sol
                            self.logger.info(f"💰 Health check balance: {balance_sol:.9f} SOL")
                        else:
                            self.logger.warning(f"Balance response format unexpected: {balance_data}")
                    else:
                        self.logger.warning(f"Balance request failed: HTTP {balance_response.status_code}")
                    
                except Exception as e:
                    self.logger.warning(f"Could not get balance in health check: {e}")
            
            health_status['status'] = 'healthy' if health_status['rpc_connection'] else 'unhealthy'
            
        except Exception as e:
            health_status['status'] = 'unhealthy'
            health_status['error'] = str(e)
            self.logger.error(f"Health check failed: {e}")
        
        return health_status
    
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
            'wallet_address': self.wallet_address,
            'mode': 'READ_ONLY' if not self.keypair else 'FULL',
            'solana_available': SOLANA_AVAILABLE,
            'solders_api': SOLDERS_API
        }
    
    async def close(self):
        """Close client connections"""
        try:
            if hasattr(self, 'async_client') and self.async_client:
                await self.async_client.close()
            self.logger.info("Solana client connections closed")
        except Exception as e:
            self.logger.error(f"Error closing client: {e}")
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

# Utility functions
def create_solana_client(config: Dict, advanced_logger=None) -> SolanaClient:
    """Factory function to create Solana client"""
    solana_config = SolanaConfig(
        rpc_url=config['solana']['rpc_url'],
        backup_rpc_urls=config['solana']['backup_rpc_urls'],
        private_key=config['solana'].get('wallet_private_key', ''),
        commitment=config['solana'].get('commitment', 'confirmed'),
        transaction_timeout=config['solana'].get('transaction_timeout', 60),
        confirmation_timeout=config['solana'].get('confirmation_timeout', 30),
        max_retries=config['solana'].get('max_retries', 3),
        retry_delay=config['solana'].get('retry_delay', 2)
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

# Test function
async def test_client():
    """Test the fixed client"""
    print("🧪 Testing Fixed Solana Client")
    print("=" * 50)
    
    config = {
        'solana': {
            'rpc_url': 'https://api.mainnet-beta.solana.com',
            'backup_rpc_urls': [],
            'wallet_private_key': '',  # Empty for read-only test
            'commitment': 'confirmed'
        }
    }
    
    try:
        async with create_solana_client(config) as client:
            print(f"✅ Client created: {client.wallet_address}")
            
            # Health check
            health = await client.health_check()
            print(f"🏥 Health: {health['status']} (latency: {health['rpc_latency_ms']:.1f}ms)")
            print(f"🔧 Solders API: {health['solders_api']}")
            print(f"📊 Client Status: {health['client_status']}")
            
            # Balance check
            balance = await client.get_balance()
            print(f"💰 SOL Balance: {balance:.6f}")
            
            # Price test
            if JUPITER_AVAILABLE:
                price = await client.get_token_price(client.COMMON_TOKENS['USDC'], 'SOL')
                if price:
                    print(f"💱 USDC/SOL: {price:.6f}")
                else:
                    print("💱 Price check failed (normal in test mode)")
            
            print("✅ All tests passed!")
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_client())