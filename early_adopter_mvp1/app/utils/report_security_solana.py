#!/usr/bin/env python3
"""
Solana Token Analysis Script - Enhanced Version
Generates a comprehensive report on a given token by querying the Solana blockchain.
Enhanced to match rugcheck.xyz functionality.
"""

import json
import requests
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
import base58
import time
import sys
import base64
import os
# Path correction to allow running as a script
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from early_adopter_mvp1.app.creator_analyzer import creator_analyzer, CreatorPerformance


# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RequestCounter:
    """Request counter per endpoint"""
    def __init__(self):
        self.counts = {}
    
    def increment(self, endpoint: str):
        self.counts[endpoint] = self.counts.get(endpoint, 0) + 1
    
    def get_summary(self):
        return self.counts

# Global counter instance
request_counter = RequestCounter()

# Enhanced known accounts database
KNOWN_ACCOUNT_TYPES = {
    # Pump.fun related addresses
    "2fSAnP1XTWoSErmdaGurL7qJ8rAwWwweyc7EKtqhXdbJ": {"name": "Pump Fun", "type": "AMM"},
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P": {"name": "Pump Fun", "type": "AMM"},
    "Ce6TQqeHC9p8KetsN6JsjHK7UTZk7nasjjnr7XxXp9F1": {"name": "Pump Fun", "type": "AMM"},
    "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg": {"name": "Pump Fun", "type": "AMM"},
    
    # Raydium addresses
    "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1": {"name": "Raydium", "type": "AMM"},
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK": {"name": "Raydium CLAMM", "type": "AMM"},
    
    # Jupiter
    "JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB": {"name": "Jupiter", "type": "AMM"},
    
    # Orca
    "9W959DqEETiGZocYWCQPaJ6sBmUzgfxXfqGeTEdp3aQP": {"name": "Orca", "type": "AMM"},
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc": {"name": "Orca Whirlpool", "type": "AMM"},
}

KNOWN_LOCKER_PROGRAMS = {
    "strmRqUCoQUgGUan5YhzUZa6KqdzwX5L6FpUxfmKg5m": "Streamflow",
    "UnXptnp5bhWcNdm4TWGWnfEWWXmHd6j6UTtv6yQFY2j": "Team Finance",
}

LAUNCHPAD_INFO = {
    "pump_fun": {
        "name": "Pump.Fun",
        "logo": "https://api.rugcheck.xyz/public/logos/pump_fun.png",
        "url": "https://pump.fun",
        "platform": "pump_fun"
    },
    "raydium": {
        "name": "Raydium",
        "logo": "https://api.rugcheck.xyz/public/logos/raydium.png", 
        "url": "https://raydium.io",
        "platform": "raydium"
    }
}

@dataclass
class TokenHolder:
    """Dataclass for a token holder"""
    address: str
    amount: int
    decimals: int
    pct: float
    uiAmount: float
    uiAmountString: str
    owner: str
    insider: bool = False
    is_contract: bool = False
    account_type: str = 'wallet'

@dataclass
class TokenMetadata:
    """Token metadata"""
    name: str
    symbol: str
    uri: str
    mutable: bool
    updateAuthority: str

@dataclass
class TokenInfo:
    """Basic token information"""
    mintAuthority: Optional[str]
    supply: int
    decimals: int
    isInitialized: bool
    freezeAuthority: Optional[str]

@dataclass
class Risk:
    """Dataclass for an identified risk"""
    name: str
    value: str
    description: str
    score: int
    level: str

def to_relative_time(dt: datetime) -> str:
    """Converts a datetime object to a human-readable relative time string."""
    now = datetime.now()
    delta = now - dt
    
    seconds = delta.total_seconds()
    if seconds < 60:
        return f"{int(seconds)} seconds ago"
    minutes = seconds / 60
    if minutes < 60:
        return f"{int(minutes)} minutes ago"
    hours = minutes / 60
    if hours < 24:
        return f"{int(hours)} hours ago"
    days = hours / 24
    if days < 7:
        return f"{int(days)} days ago"
    weeks = days / 7
    if weeks < 4.345:
        return f"{int(weeks)} weeks ago"
    months = days / 30.437
    if months < 12:
        return f"{int(months)} months ago"
    years = days / 365.25
    return f"{int(years)} years ago"

def is_valid_solana_address(address: str) -> bool:
    """Validates a Solana address"""
    try:
        if len(address) < 32 or len(address) > 44:
            return False
        decoded = base58.b58decode(address)
        return len(decoded) == 32
    except Exception:
        return False


def json_datetime_serializer(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class SolanaTokenAnalyzer:
    """Enhanced Solana token analyzer matching rugcheck functionality"""
    
    def __init__(self, rpc_url: str = "https://api.mainnet-beta.solana.com"):
        self.rpc_url = rpc_url
        self.backup_rpcs = [
            "https://solana-mainnet.g.alchemy.com/v2/demo",
            "https://rpc.ankr.com/solana", 
            "https://api.mainnet-beta.solana.com",
            "https://solana-api.projectserum.com"
        ]
        self.rate_limit_delay = 0.5
        self._pumpfun_cache = {}
        
    def _make_rpc_call(self, method: str, params: List[Any] = None, retry_count: int = 2) -> Dict:
        """Performs an RPC call with optimized retry and fallback"""
        request_counter.increment(f"RPC/{method}")
        time.sleep(self.rate_limit_delay * 0.1)
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or []
        }
        
        urls_to_try = [self.rpc_url] + [url for url in self.backup_rpcs if url != self.rpc_url]
        
        for attempt, url in enumerate(urls_to_try):
            if attempt > 0:
                logger.info(f"Trying with backup RPC: {url}")
                
            for retry in range(retry_count):
                try:
                    timeout = 15 if attempt == 0 else 10
                    response = requests.post(
                        url, json=payload,
                        headers={'Content-Type': 'application/json'},
                        timeout=timeout
                    )
                    
                    if response.status_code == 429:
                        wait_time = min(2 ** retry, 8)
                        logger.warning(f"Rate limit for {method}, waiting {wait_time}s...")
                        time.sleep(wait_time)
                        self.rate_limit_delay = min(self.rate_limit_delay * 1.5, 3)
                        continue
                    elif response.status_code in [410, 403]:
                        logger.warning(f"Endpoint {method} not available ({response.status_code})")
                        break
                    
                    response.raise_for_status()
                    result = response.json()
                    
                    if "error" in result:
                        error_msg = result["error"]
                        if isinstance(error_msg, dict):
                            error_msg = error_msg.get("message", str(error_msg))
                        logger.error(f"RPC Error {method}: {error_msg}")
                        return {"error": error_msg}
                    
                    if attempt > 0:
                        logger.info(f"Success with backup after {attempt + 1} attempts")
                    
                    self.rate_limit_delay = max(self.rate_limit_delay * 0.9, 0.2)
                    return result
                    
                except requests.exceptions.Timeout:
                    logger.warning(f"Timeout {method} (attempt {retry + 1})")
                    break
                except requests.exceptions.RequestException as e:
                    if "403" in str(e) or "Forbidden" in str(e):
                        break
                    if retry < retry_count - 1:
                        time.sleep(1)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON Error {method}: {e}")
                    break
        
        logger.error(f"Definitive failure for {method}")
        return {"error": "All RPC calls failed"}

    def get_token_info(self, mint_address: str) -> Optional[TokenInfo]:
        """Gets basic token information"""
        logger.info(f"Fetching token information: {mint_address}")
        
        result = self._make_rpc_call("getAccountInfo", [
            mint_address,
            {"encoding": "jsonParsed"}
        ])
        
        if "error" in result or "result" not in result or not result["result"]["value"]:
            logger.error(f"Could not fetch token info: {mint_address}")
            return None
        
        try:
            account_data = result["result"]["value"]["data"]["parsed"]["info"]
            return TokenInfo(
                mintAuthority=account_data.get("mintAuthority"),
                supply=int(account_data.get("supply", 0)),
                decimals=int(account_data.get("decimals", 0)),
                isInitialized=account_data.get("isInitialized", False),
                freezeAuthority=account_data.get("freezeAuthority")
            )
        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"Error parsing token info: {e}")
            return None

    def get_token_metadata_onchain(self, mint_address: str) -> Optional[TokenMetadata]:
        """Gets metadata from onchain Metaplex data"""
        try:
            # Metaplex metadata program ID
            metadata_program_id = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"
            
            # Try to find metadata account using getProgramAccounts
            result = self._make_rpc_call("getProgramAccounts", [
                metadata_program_id,
                {
                    "encoding": "base64", 
                    "filters": [
                        {"dataSize": 679},
                        {"memcmp": {"offset": 33, "bytes": mint_address}}
                    ]
                }
            ])
            
            if "result" in result and result["result"]:
                for account in result["result"][:1]:  # Take first match
                    try:
                        data_b64 = account["account"]["data"][0]
                        data_bytes = base64.b64decode(data_b64)
                        
                        metadata = self._parse_metadata_bytes(data_bytes)
                        if metadata:
                            logger.info(f"Found onchain metadata for {mint_address}")
                            return metadata
                            
                    except Exception as e:
                        logger.debug(f"Error parsing metadata account: {e}")
                        continue
                        
        except Exception as e:
            logger.debug(f"Error fetching onchain metadata: {e}")
        
        return None

    def _parse_metadata_bytes(self, data: bytes) -> Optional[TokenMetadata]:
        """Parse Metaplex metadata bytes"""
        try:
            if len(data) < 100:
                return None
                
            # Check metadata account discriminator
            if data[0] != 4:  # MetadataV1 key
                return None
            
            # Extract update authority (bytes 1-33)
            update_authority_bytes = data[1:33]
            update_authority = base58.b58encode(update_authority_bytes).decode()
            
            # Parse name (starts at offset 65)
            offset = 65
            if offset + 4 >= len(data):
                return None
                
            name_len = int.from_bytes(data[offset:offset+4], 'little')
            offset += 4
            
            if offset + name_len >= len(data):
                return None
                
            name = data[offset:offset+name_len].decode('utf-8', errors='ignore').rstrip('\x00')
            offset += name_len
            
            # Parse symbol
            if offset + 4 >= len(data):
                return None
                
            symbol_len = int.from_bytes(data[offset:offset+4], 'little') 
            offset += 4
            
            if offset + symbol_len >= len(data):
                return None
                
            symbol = data[offset:offset+symbol_len].decode('utf-8', errors='ignore').rstrip('\x00')
            offset += symbol_len
            
            # Parse URI
            if offset + 4 >= len(data):
                return None
                
            uri_len = int.from_bytes(data[offset:offset+4], 'little')
            offset += 4
            
            if offset + uri_len >= len(data):
                return None
                
            uri = data[offset:offset+uri_len].decode('utf-8', errors='ignore').rstrip('\x00')
            
            # Determine mutability (if update authority is not burn address)
            burn_address = "11111111111111111111111111111111"
            mutable = update_authority != burn_address
            
            return TokenMetadata(
                name=name.strip(),
                symbol=symbol.strip(), 
                uri=uri.strip(),
                mutable=mutable,
                updateAuthority=update_authority
            )
            
        except Exception as e:
            logger.debug(f"Error parsing metadata bytes: {e}")
            return None

    def get_token_metadata_from_external_sources(self, mint_address: str) -> Optional[TokenMetadata]:
        """Gets metadata from external sources"""
        # Jupiter API
        try:
            url = "https://token.jup.ag/strict"
            request_counter.increment(url)
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                tokens = response.json()
                for token in tokens:
                    if token.get("address") == mint_address:
                        return TokenMetadata(
                            name=token.get("name", "Unknown"),
                            symbol=token.get("symbol", "UNKNOWN"),
                            uri=token.get("logoURI", ""),
                            mutable=True,
                            updateAuthority=mint_address
                        )
        except Exception as e:
            logger.debug(f"Jupiter API Error: {e}")
        
        # Solana Token List
        try:
            url = "https://raw.githubusercontent.com/solana-labs/token-list/main/src/tokens/solana.tokenlist.json"
            request_counter.increment(url)
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                token_list = response.json()
                for token in token_list.get("tokens", []):
                    if token.get("address") == mint_address:
                        return TokenMetadata(
                            name=token.get("name", "Unknown"),
                            symbol=token.get("symbol", "UNKNOWN"),
                            uri=token.get("logoURI", ""),
                            mutable=True,
                            updateAuthority=mint_address
                        )
        except Exception as e:
            logger.debug(f"Token List Error: {e}")
        
        return None

    def identify_account_type(self, address: str) -> Dict[str, str]:
        """Identifies the type of an account"""
        logger.debug(f"Identifying account type for: {address}")
        
        # Check known accounts first
        if address in KNOWN_ACCOUNT_TYPES:
            result = KNOWN_ACCOUNT_TYPES[address]
            logger.debug(f"Found in KNOWN_ACCOUNT_TYPES: {result}")
            return result
        
        # Check known locker programs
        if address in KNOWN_LOCKER_PROGRAMS:
            result = {"name": KNOWN_LOCKER_PROGRAMS[address], "type": "LOCKER"}
            logger.debug(f"Found in KNOWN_LOCKER_PROGRAMS: {result}")
            return result
        
        # Check if it's an executable (program)
        try:
            account_info = self._make_rpc_call("getAccountInfo", [address])
            if (account_info and account_info.get("result", {}).get("value")):
                if account_info["result"]["value"].get("executable", False):
                    result = {"name": "Program", "type": "PROGRAM"}
                    logger.debug(f"Identified as program: {result}")
                    return result
        except Exception as e:
            logger.debug(f"Error checking if account is program: {e}")
        
        result = {"name": "Unknown", "type": "WALLET"}
        logger.debug(f"Defaulting to: {result}")
        return result

    def get_token_holders_via_api(self, mint_address: str, limit: int = 15) -> List[TokenHolder]:
        """Gets holders from external APIs"""
        logger.info("Trying to fetch from external APIs")
        
        # Try pump.fun API first for pump tokens
        pump_data = self._get_pumpfun_data(mint_address)
        if pump_data:
            logger.info("Token found on pump.fun, creating proper holder structure")
            token_info = self.get_token_info(mint_address)
            if token_info:
                # Use the actual pump.fun addresses from the API response
                bonding_curve = pump_data.get('bonding_curve', '2fSAnP1XTWoSErmdaGurL7qJ8rAwWwweyc7EKtqhXdbJ')
                associated_bonding_curve = pump_data.get('associated_bonding_curve', '38StPxmPmG9KRSfQFQrZ4h5Ks19JTJgXMomE8NWCEXtt')
                
                return [
                    TokenHolder(
                        address=associated_bonding_curve,
                        amount=token_info.supply,
                        decimals=token_info.decimals,
                        pct=100.0,
                        uiAmount=token_info.supply / (10 ** token_info.decimals),
                        uiAmountString=str(token_info.supply / (10 ** token_info.decimals)),
                        owner=bonding_curve,  # The bonding curve contract owns the associated token account
                        account_type="amm (Pump Fun)",
                        is_contract=True
                    )
                ]
        
        # Try SolScan API
        try:
            solscan_url = f"https://public-api.solscan.io/token/holders?tokenAddress={mint_address}&offset=0&limit={limit}"
            request_counter.increment(solscan_url)
            
            response = requests.get(solscan_url, timeout=10, headers={
                'User-Agent': 'SolanaTokenAnalyzer/1.0'
            })
            
            if response.status_code == 200:
                data = response.json()
                holders = []
                
                if 'data' in data:
                    token_info = self.get_token_info(mint_address)
                    total_supply = token_info.supply if token_info else 1
                    
                    for item in data['data'][:limit]:
                        amount = int(item.get('amount', 0))
                        pct = (amount / total_supply * 100) if total_supply > 0 else 0
                        decimals = token_info.decimals if token_info else 6
                        ui_amount = amount / (10 ** decimals)
                        
                        owner = item.get('owner', 'Unknown')
                        # Apply account type identification
                        account_info = self.identify_account_type(owner)
                        account_type = 'wallet'
                        is_contract = False
                        
                        if account_info["type"] == "AMM":
                            account_type = f"amm ({account_info['name']})"
                            is_contract = True
                        elif account_info["type"] == "LOCKER":
                            account_type = f"locker ({account_info['name']})"
                            is_contract = True
                        elif account_info["type"] == "PROGRAM":
                            account_type = "unknown_contract"
                            is_contract = True
                        
                        holders.append(TokenHolder(
                            address=item.get('address', 'Unknown'),
                            amount=amount,
                            decimals=decimals,
                            pct=pct,
                            uiAmount=ui_amount,
                            uiAmountString=str(ui_amount),
                            owner=owner,
                            account_type=account_type,
                            is_contract=is_contract
                        ))
                    
                    if holders:
                        logger.info(f"Fetched {len(holders)} holders via SolScan API")
                        return holders
        
        except Exception as e:
            logger.debug(f"External API Error: {e}")
        
        return []

    def get_token_holders(self, mint_address: str, limit: int = 15) -> List[TokenHolder]:
        """Gets holders with enhanced analysis and account type detection"""
        logger.info(f"Fetching holders: {mint_address}")
        
        # Try RPC first
        result = self._make_rpc_call("getTokenLargestAccounts", [mint_address])
        
        if "error" in result or "result" not in result:
            logger.warning("RPC failed, trying external APIs...")
            external_holders = self.get_token_holders_via_api(mint_address, limit)
            if external_holders:
                return external_holders
            
            logger.warning("All methods failed, using fallback holders")
            return self._create_fallback_holders(mint_address)
        
        # Process RPC results
        holders = []
        largest_accounts = result["result"]["value"]
        
        token_info = self.get_token_info(mint_address)
        total_supply = token_info.supply if token_info else 1
        
        accounts_to_process = min(limit, len(largest_accounts))
        
        for i, account in enumerate(largest_accounts[:accounts_to_process]):
            logger.debug(f"Processing holder {i+1}/{accounts_to_process}")
            
            # Get owner of the token account
            owner = "Unknown"
            account_info_result = self._make_rpc_call("getAccountInfo", [account["address"], {"encoding": "jsonParsed"}])
            if (account_info_result and account_info_result.get("result", {}).get("value")):
                try:
                    parsed_data = account_info_result["result"]["value"]["data"]["parsed"]["info"]
                    owner = parsed_data.get("owner", "Unknown")
                except (KeyError, TypeError):
                    owner = "Unknown"

            # Identify account type
            is_contract = False
            account_type = 'wallet'
            
            if owner != "Unknown":
                logger.debug(f"Processing holder {i+1} with owner: {owner}")
                account_info = self.identify_account_type(owner)
                logger.debug(f"Account info result: {account_info}")
                
                if account_info["type"] == "AMM":
                    account_type = f"amm ({account_info['name']})"
                    is_contract = True
                    logger.info(f"Holder {i+1} identified as AMM: {account_info['name']}")
                elif account_info["type"] == "LOCKER":
                    account_type = f"locker ({account_info['name']})"
                    is_contract = True
                    logger.info(f"Holder {i+1} identified as LOCKER: {account_info['name']}")
                elif account_info["type"] == "PROGRAM":
                    account_type = "unknown_contract"
                    is_contract = True
                    logger.info(f"Holder {i+1} identified as PROGRAM")
                else:
                    account_type = 'wallet'
                    logger.info(f"Holder {i+1} identified as WALLET")
                
                logger.debug(f"Final account_type for holder {i+1}: {account_type}")
            else:
                logger.debug(f"Holder {i+1} has unknown owner")

            amount = int(account["amount"])
            decimals = int(account["decimals"])
            pct = (amount / total_supply * 100) if total_supply > 0 else 0
            ui_amount = amount / (10 ** decimals)
            
            holders.append(TokenHolder(
                address=account["address"],
                amount=amount,
                decimals=decimals,
                pct=pct,
                uiAmount=ui_amount,
                uiAmountString=str(ui_amount),
                owner=owner,
                is_contract=is_contract,
                account_type=account_type
            ))
            
            time.sleep(0.05)
        
        logger.info(f"Fetched and analyzed {len(holders)} holders")
        return holders

    def _create_fallback_holders(self, mint_address: str) -> List[TokenHolder]:
        """Creates dummy holders for risk analysis"""
        token_info = self.get_token_info(mint_address)
        if token_info and token_info.supply > 0:
            # For pump.fun tokens, use the actual pump.fun data
            pump_data = self._get_pumpfun_data(mint_address)
            if pump_data:
                logger.info("Creating pump.fun fallback holder with correct addresses")
                bonding_curve = pump_data.get('bonding_curve', '2fSAnP1XTWoSErmdaGurL7qJ8rAwWwweyc7EKtqhXdbJ')
                associated_bonding_curve = pump_data.get('associated_bonding_curve', '38StPxmPmG9KRSfQFQrZ4h5Ks19JTJgXMomE8NWCEXtt')
                
                return [
                    TokenHolder(
                        address=associated_bonding_curve,
                        amount=token_info.supply,
                        decimals=token_info.decimals,
                        pct=100.0,
                        uiAmount=token_info.supply / (10 ** token_info.decimals),
                        uiAmountString=str(token_info.supply / (10 ** token_info.decimals)),
                        owner=bonding_curve,
                        account_type="amm (Pump Fun)",
                        is_contract=True
                    )
                ]
            else:
                # Unknown token type - treat as high risk
                logger.warning("Creating fallback holder for unknown token type")
                return [
                    TokenHolder(
                        address="Unknown_Holder_1",
                        amount=token_info.supply,
                        decimals=token_info.decimals,
                        pct=100.0,
                        uiAmount=token_info.supply / (10 ** token_info.decimals),
                        uiAmountString=str(token_info.supply / (10 ** token_info.decimals)),
                        owner="Unknown",
                        account_type="wallet"
                    )
                ]
        return []

    def detect_launchpad(self, mint_address: str, holders: List[TokenHolder], 
                        pump_data: Optional[Dict]) -> Optional[Dict]:
        """Detects the launch platform"""
        
        # If we have pump.fun data, it's definitely pump.fun
        if pump_data:
            return LAUNCHPAD_INFO["pump_fun"]
        
        # Check holders for known AMM addresses
        for holder in holders[:5]:
            account_info = self.identify_account_type(holder.owner)
            if account_info["name"] == "Pump Fun":
                return LAUNCHPAD_INFO["pump_fun"]
            elif account_info["name"] in ["Raydium", "Raydium CLAMM"]:
                return LAUNCHPAD_INFO["raydium"]
        
        return None

    def find_token_creator_enhanced(self, mint_address: str) -> Tuple[Optional[str], int]:
        """Enhanced version of creator search"""
        logger.info(f"Searching for creator: {mint_address}")
        
        # Strategy 1: pump.fun API first
        creator = self._find_creator_via_pump_api(mint_address)
        if creator:
            return creator, 0

        # Strategy 2: Transaction analysis
        creator = self._find_creator_via_transactions(mint_address)
        if creator:
            return creator, 0
        
        logger.warning("Creator not found with any method")
        return None, 0

    def _find_creator_via_transactions(self, mint_address: str) -> Optional[str]:
        """Searches for the creator by analyzing transactions"""
        try:
            signatures_result = self._make_rpc_call("getSignaturesForAddress", [
                mint_address,
                {"limit": 20}
            ])
            
            if "result" not in signatures_result or not signatures_result["result"]:
                return None
            
            signatures = signatures_result["result"]
            
            # Analyze the last few transactions (oldest first)
            for sig_info in reversed(signatures[-3:]):
                try:
                    signature = sig_info["signature"]
                    tx_result = self._make_rpc_call("getTransaction", [
                        signature,
                        {"encoding": "json", "maxSupportedTransactionVersion": 0}
                    ])
                    
                    if ("result" in tx_result and tx_result["result"] and
                        "transaction" in tx_result["result"]):
                        
                        message = tx_result["result"]["transaction"]["message"]
                        if "accountKeys" in message and message["accountKeys"]:
                            potential_creator = message["accountKeys"][0]
                            
                            if potential_creator != mint_address:
                                logger.info(f"Potential creator found: {potential_creator}")
                                return potential_creator
                
                except Exception as e:
                    logger.debug(f"Error analyzing transaction: {e}")
                    continue
            
            return None
            
        except Exception as e:
            logger.debug(f"Error searching creator via transactions: {e}")
            return None

    def _get_pumpfun_data(self, mint_address: str) -> Optional[Dict[str, Any]]:
        """Calls the pump.fun API"""
        if mint_address in self._pumpfun_cache:
            return self._pumpfun_cache[mint_address]

        try:
            pump_api_url = f"https://frontend-api-v3.pump.fun/coins/{mint_address}"
            request_counter.increment(pump_api_url)
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://pump.fun/'
            }
            
            response = requests.get(pump_api_url, timeout=10, headers=headers)
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    self._pumpfun_cache[mint_address] = data
                    return data
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON response from pump.fun API")
                    self._pumpfun_cache[mint_address] = None
                    return None
            else:
                logger.warning(f"pump.fun API failed, status: {response.status_code}")
                self._pumpfun_cache[mint_address] = None
                return None
                
        except requests.exceptions.RequestException as e:
            logger.warning(f"Error calling pump.fun API: {e}")
            self._pumpfun_cache[mint_address] = None
            return None

    def _find_creator_via_pump_api(self, mint_address: str) -> Optional[str]:
        """Searches for creator via pump.fun API"""
        pump_data = self._get_pumpfun_data(mint_address)
        
        if not pump_data:
            return None
            
        creator_address = pump_data.get("creator")
        if creator_address and is_valid_solana_address(creator_address):
            logger.info(f"Creator found via pump.fun API: {creator_address}")
            return creator_address
        else:
            logger.debug(f"No valid creator in pump.fun API response")
            return None

    def find_token_creator(self, mint_address: str) -> Tuple[Optional[str], int]:
        """Public interface for creator search"""
        return self.find_token_creator_enhanced(mint_address)

    def calculate_rugcheck_style_score(self, token_info: TokenInfo, holders: List[TokenHolder], 
                                     mint_address: str, creator: Optional[str], 
                                     token_metadata: Optional[TokenMetadata]) -> Tuple[int, int]:
        """Calculates risk score in rugcheck style (low score = good, high score = bad)"""
        
        # Start with perfect score (0 = no risk)
        risk_score = 0
        
        # Authority risks (major penalties)
        if token_info.mintAuthority:
            risk_score += 30  # Mint authority active
        
        if token_info.freezeAuthority:
            risk_score += 20  # Freeze authority active
        
        # Holder concentration analysis (excluding AMM/lockers)
        wallet_holders = [h for h in holders if h.account_type == 'wallet' and not h.account_type.startswith(('amm', 'locker'))]
        
        if wallet_holders:
            # Top holder concentration
            top_holder_pct = wallet_holders[0].pct if wallet_holders else 0
            
            if top_holder_pct > 90:
                risk_score += 40
            elif top_holder_pct > 70:
                risk_score += 25  
            elif top_holder_pct > 50:
                risk_score += 15
            elif top_holder_pct > 30:
                risk_score += 8
            
            # Top 10 concentration
            top_10_pct = sum(h.pct for h in wallet_holders[:10])
            if top_10_pct > 90:
                risk_score += 20
            elif top_10_pct > 80:
                risk_score += 15
            elif top_10_pct > 70:
                risk_score += 10
        else:
            # No wallet holders found (all in contracts)
            risk_score += 5
        
        # Low holder count
        total_wallet_holders = len(wallet_holders)
        if total_wallet_holders < 10:
            risk_score += 15
        elif total_wallet_holders < 50:
            risk_score += 8
        elif total_wallet_holders < 100:
            risk_score += 3
        
        # Supply analysis
        if token_info.supply > 10**15:
            risk_score += 10  # Extremely high supply
        elif token_info.supply < 1000:
            risk_score += 5   # Suspiciously low supply
        
        # Metadata risks
        if token_metadata:
            if token_metadata.mutable:
                risk_score += 5  # Mutable metadata
            if not token_metadata.uri or len(token_metadata.uri) < 10:
                risk_score += 3  # No/poor metadata
        else:
            risk_score += 8  # No metadata found
        
        # Creator risks
        if not creator or creator == "Unknown":
            risk_score += 10  # Unknown creator
        
        # Liquidity provider penalty (if no known AMMs detected)
        has_known_amm = any(h.account_type.startswith('amm') for h in holders)
        if not has_known_amm:
            risk_score += 12  # No known AMM liquidity
        
        # Convert to normalized score (0-100, where 0 is perfect)
        normalized_score = min(100, risk_score)
        
        # Raw score for compatibility (higher = worse)
        raw_score = risk_score * 10
        
        return raw_score, normalized_score

    def analyze_risks_enhanced(self, token_info: TokenInfo, holders: List[TokenHolder], 
                             mint_address: str, creator: Optional[str],
                             token_metadata: Optional[TokenMetadata]) -> List[Risk]:
        """Enhanced risk analysis matching rugcheck style"""
        risks = []
        
        if not token_info:
            risks.append(Risk(
                name="Token information unavailable",
                value="",
                description="Unable to retrieve basic token information",
                score=5000,
                level="danger"
            ))
            return risks
        
        # Authority risks
        if token_info.mintAuthority:
            risks.append(Risk(
                name="Mint authority active",
                value=str(token_info.mintAuthority),
                description="Token can still be minted by the mint authority - this allows inflation",
                score=3000,
                level="danger"
            ))
        
        if token_info.freezeAuthority:
            risks.append(Risk(
                name="Freeze authority active", 
                value=str(token_info.freezeAuthority),
                description="Token accounts can be frozen by freeze authority - this allows censorship",
                score=2000,
                level="warn"
            ))
        
        # Holder analysis (excluding AMM/lockers)
        wallet_holders = [h for h in holders if h.account_type == 'wallet' and not h.account_type.startswith(('amm', 'locker'))]
        
        if wallet_holders:
            top_holder_pct = wallet_holders[0].pct
            top_10_pct = sum(h.pct for h in wallet_holders[:10])
            
            if top_holder_pct > 70:
                risks.append(Risk(
                    name="Single holder dominance",
                    value=f"{top_holder_pct:.2f}%",
                    description="One wallet holds a large portion of the token supply",
                    score=int(top_holder_pct * 50),
                    level="danger"
                ))
            elif top_holder_pct > 50:
                risks.append(Risk(
                    name="High holder concentration", 
                    value=f"{top_holder_pct:.2f}%",
                    description="Top holder has significant control over token supply",
                    score=int(top_holder_pct * 30),
                    level="warn"
                ))
            
            if top_10_pct > 85:
                risks.append(Risk(
                    name="Top 10 holders control majority",
                    value=f"{top_10_pct:.2f}%", 
                    description="Top 10 wallets control most of the token supply",
                    score=int(top_10_pct * 20),
                    level="danger"
                ))
            
        # Low liquidity warning
        has_known_amm = any(h.account_type.startswith('amm') for h in holders)
        if not has_known_amm:
            risks.append(Risk(
                name="Low amount of LP Providers",
                value="",
                description="Only a few users are providing liquidity",
                score=500,
                level="warn"
            ))
        
        # Metadata risks
        if not token_metadata:
            risks.append(Risk(
                name="No metadata found",
                value="",
                description="Token metadata could not be retrieved",
                score=800,
                level="warn"
            ))
        elif token_metadata.mutable:
            risks.append(Risk(
                name="Mutable metadata",
                value="Yes",
                description="Token metadata can be changed by update authority",
                score=500,
                level="warn"
            ))
        
        return risks

    def analyze_token_with_options(self, mint_address: str, fast_mode: bool = False, 
                                 find_creator: bool = True, max_holders: int = 15) -> Dict[str, Any]:
        """Complete analysis with rugcheck-style enhancements"""
        logger.info(f"Analyzing token: {mint_address}")
        if fast_mode:
            logger.info("Fast mode enabled")
        
        start_time = time.time()
        
        if not is_valid_solana_address(mint_address):
            raise ValueError(f"Invalid address: {mint_address}")
        
        # Basic information
        token_info = self.get_token_info(mint_address)
        if not token_info:
            raise ValueError(f"Token not found: {mint_address}")
        
        # Enhanced metadata retrieval
        token_metadata = None
        if not fast_mode:
            # Try onchain first, then external
            token_metadata = self.get_token_metadata_onchain(mint_address)
            if not token_metadata:
                token_metadata = self.get_token_metadata_from_external_sources(mint_address)
        
        # Holders with enhanced analysis
        holder_limit = min(max_holders, 5) if fast_mode else max_holders
        holders = self.get_token_holders(mint_address, holder_limit)
        
        # Creator
        creator = None
        creator_balance = 0
        if find_creator:
            creator, creator_balance = self.find_token_creator(mint_address)

        creator_analysis = None
        if creator and creator != "Unknown":
            try:
                logger.info(f"Analyzing creator's past performance: {creator}")
                creator_analysis = creator_analyzer.analyze_creator(creator)
                if creator_analysis and creator_analysis.total_tokens > 0:
                    logger.info(f"Creator analysis found: {creator_analysis.total_tokens} tokens created previously.")
                elif creator_analysis:
                    logger.info(f"Creator has no previously created tokens on record.")

            except Exception as e:
                logger.error(f"Could not analyze creator {creator}: {e}")
                # Ensure creator_analysis is None if analysis fails
                creator_analysis = None
        
        if not creator:
            creator = "Unknown"
        
        # Enhanced risk analysis  
        risks = self.analyze_risks_enhanced(token_info, holders, mint_address, creator, token_metadata)
        
        # Rugcheck-style scoring
        raw_score, normalized_score = self.calculate_rugcheck_style_score(
            token_info, holders, mint_address, creator, token_metadata
        )
        
        # Build known accounts database
        known_accounts = {}
        for holder in holders:
            if holder.owner and holder.owner != "Unknown":
                account_info = self.identify_account_type(holder.owner)
                known_accounts[holder.owner] = account_info
        
        # Add creator to known accounts
        if creator and creator != "Unknown":
            known_accounts[creator] = {"name": "Creator", "type": "CREATOR"}
        
        # Detect launchpad
        pump_data = self._get_pumpfun_data(mint_address)
        launchpad = self.detect_launchpad(mint_address, holders, pump_data)
        
        # Build the report
        report = {
            "mint": mint_address,
            "tokenProgram": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
            "creator": creator,
            "creatorBalance": creator_balance,
            "creator_analysis": asdict(creator_analysis) if creator_analysis else None,
            "token": asdict(token_info),
            "token_extensions": None,
            "tokenMeta": asdict(token_metadata) if token_metadata else {
                "name": "Unknown Token",
                "symbol": "UNKNOWN", 
                "uri": "",
                "mutable": False,
                "updateAuthority": ""
            },
            "topHolders": [asdict(holder) for holder in holders],
            "freezeAuthority": token_info.freezeAuthority,
            "mintAuthority": token_info.mintAuthority,
            "risks": [asdict(risk) for risk in risks],
            "score": raw_score,
            "score_normalised": normalized_score,
            "fileMeta": {
                "description": "",
                "name": token_metadata.name if token_metadata else "Unknown Token",
                "symbol": token_metadata.symbol if token_metadata else "UNKNOWN",
                "image": ""
            },
            "lockerOwners": {},
            "lockers": {},
            "markets": None,
            "totalMarketLiquidity": 0,
            "totalStableLiquidity": 0, 
            "totalLPProviders": 0,
            "totalHolders": len([h for h in holders if h.account_type == 'wallet' and not h.account_type.startswith(('amm', 'locker'))]),
            "price": 0,
            "rugged": normalized_score > 70,  # High risk threshold
            "tokenType": "",
            "transferFee": {
                "pct": 0,
                "maxAmount": 0,
                "authority": "11111111111111111111111111111111"
            },
            "knownAccounts": known_accounts,
            "events": [],
            "verification": None,
            "graphInsidersDetected": 0,
            "insiderNetworks": None,
            "detectedAt": datetime.now().isoformat() + "Z",
            "creatorTokens": None,
            "launchpad": launchpad,
            "analysisMode": "fast" if fast_mode else "standard"
        }
        
        analysis_time = time.time() - start_time
        logger.info(f"Analysis finished in {analysis_time:.2f} seconds")
        
        # Enhance with pump.fun data if available
        if pump_data:
            report["tokenMeta"]["name"] = pump_data.get("name", report["tokenMeta"]["name"])
            report["tokenMeta"]["symbol"] = pump_data.get("symbol", report["tokenMeta"]["symbol"])
            report["tokenMeta"]["uri"] = pump_data.get("image_uri", report["tokenMeta"]["uri"])
            
            report["fileMeta"]["name"] = pump_data.get("name", report["fileMeta"]["name"])
            report["fileMeta"]["symbol"] = pump_data.get("symbol", report["fileMeta"]["symbol"])
            report["fileMeta"]["description"] = pump_data.get("description", report["fileMeta"]["description"])
            report["fileMeta"]["image"] = pump_data.get("image_uri", report["fileMeta"]["image"])

            # Add social links and market data
            report["socials"] = {
                "twitter": pump_data.get("twitter"),
                "telegram": pump_data.get("telegram"),
                "website": pump_data.get("website")
            }
            report["market_cap"] = pump_data.get("usd_market_cap")
            
            # Timestamps
            created_timestamp = pump_data.get("created_timestamp")
            if created_timestamp:
                report["created_at"] = datetime.fromtimestamp(created_timestamp / 1000).isoformat()

            last_trade_timestamp = pump_data.get("last_trade_timestamp") 
            if last_trade_timestamp:
                report["last_trade_at"] = datetime.fromtimestamp(last_trade_timestamp / 1000).isoformat()

            report["ath_market_cap"] = pump_data.get("ath_market_cap")
            ath_timestamp = pump_data.get("ath_market_cap_timestamp")
            if ath_timestamp:
                report["ath_timestamp"] = datetime.fromtimestamp(ath_timestamp / 1000).isoformat()
            
        return report

    def analyze_token(self, mint_address: str) -> Dict[str, Any]:
        """Standard analysis (for compatibility)"""
        return self.analyze_token_with_options(mint_address, fast_mode=False, find_creator=True, max_holders=15)

def main():
    """Main function with enhanced options"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Enhanced Solana Token Analyzer (rugcheck-style)")
    parser.add_argument("token", nargs='?', help="Address of the token to analyze")
    parser.add_argument("--rpc-url", default="https://api.mainnet-beta.solana.com",
                       help="URL of the Solana RPC node")
    parser.add_argument("--output", "-o", help="JSON output file")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Verbose mode")
    parser.add_argument("--test", action="store_true",
                       help="Use a test token")
    parser.add_argument("--fast", action="store_true",
                       help="Fast mode")
    parser.add_argument("--ultra-fast", action="store_true",
                       help="Ultra-fast mode")
    parser.add_argument("--no-creator", action="store_true",
                       help="Do not search for the creator")
    parser.add_argument("--max-holders", type=int, default=15,
                       help="Maximum number of holders (default: 15)")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Test token
    if args.test or not args.token:
        test_token = "So11111111111111111111111111111111111111112"  # Wrapped SOL
        if not args.token:
            logger.info(f"Test token: {test_token}")
            token_address = test_token
        else:
            token_address = args.token
    else:
        token_address = args.token
    
    try:
        if not is_valid_solana_address(token_address):
            logger.error(f"Invalid address: {token_address}")
            return 1
        
        analyzer = SolanaTokenAnalyzer(args.rpc_url)
        
        if args.ultra_fast:
            logger.info("Ultra-fast mode enabled")
            report = analyzer.analyze_token_with_options(
                token_address,
                fast_mode=True,
                find_creator=False,
                max_holders=3
            )
        elif args.fast:
            logger.info("Fast mode enabled")
            report = analyzer.analyze_token_with_options(
                token_address,
                fast_mode=True,
                find_creator=not args.no_creator,
                max_holders=5
            )
        else:
            report = analyzer.analyze_token_with_options(
                token_address,
                fast_mode=False,
                find_creator=not args.no_creator,
                max_holders=args.max_holders
            )
        
        # Request summary
        request_summary = request_counter.get_summary()
        logger.info("=== REQUESTS SUMMARY ===")
        total_requests = 0
        for endpoint, count in sorted(request_summary.items()):
            logger.info(f"{endpoint}: {count} requests")
            total_requests += count
        logger.info(f"Total: {total_requests} requests")
        logger.info("=" * 30)
        
        # Enhanced report summary
        logger.info(f"Token: {report['mint']}")
        logger.info(f"Name: {report['fileMeta']['name']}")
        logger.info(f"Symbol: {report['fileMeta']['symbol']}")
        if report['fileMeta'].get('description'):
            logger.info(f"Description: {report['fileMeta']['description']}")
        
        logger.info(f"Supply: {report['token']['supply']:,}")
        logger.info(f"Wallet Holders: {report['totalHolders']}")
        
        # Risk analysis
        logger.info(f"Risks ({len(report['risks'])}):")
        if report['risks']:
            for risk in report['risks']:
                logger.info(f"  - [{risk['level'].upper()}] {risk['name']}: {risk['value']}")
        
        # Enhanced scoring display
        normalized_score = report['score_normalised']
        if normalized_score <= 20:
            score_status = f"{normalized_score}/100 - EXCELLENT"
        elif normalized_score <= 40:
            score_status = f"{normalized_score}/100 - GOOD"
        elif normalized_score <= 60:
            score_status = f"{normalized_score}/100 - MODERATE"
        elif normalized_score <= 80:
            score_status = f"{normalized_score}/100 - HIGH RISK"
        else:
            score_status = f"{normalized_score}/100 - VERY HIGH RISK"
            
        logger.info(f"Risk Score: {score_status}")
        
        rugged_status = "YES" if report['rugged'] else "NO"
        logger.info(f"High Risk Token: {rugged_status}")

        # Timestamps and market data
        if report.get('created_at'):
            created_dt = datetime.fromisoformat(report['created_at'])
            relative_time = to_relative_time(created_dt)
            logger.info(f"Created: {report['created_at']} ({relative_time})")
        
        if report.get('market_cap') is not None:
            logger.info(f"Market Cap: ${report['market_cap']:,.2f}")
            
        if report.get('ath_market_cap') is not None:
            logger.info(f"ATH Market Cap: ${report['ath_market_cap']:,.2f}")

        # Authority status
        mint_auth_status = "REVOKED" if not report['token']['mintAuthority'] else f"ACTIVE"
        freeze_auth_status = "REVOKED" if not report['token']['freezeAuthority'] else f"ACTIVE"
        
        logger.info(f"Mint Authority: {mint_auth_status}")
        logger.info(f"Freeze Authority: {freeze_auth_status}")
        
        # Transfer fee status
        transfer_fee = report.get('transferFee', {})
        fee_pct = transfer_fee.get('pct', 0)
        fee_authority = transfer_fee.get('authority', '')
        
        if fee_pct > 0:
            fee_status = f"{fee_pct}%"
        else:
            fee_status = "NO FEES"
            
        # Check if transfer fee authority is revoked (burn address)
        burn_address = "11111111111111111111111111111111"
        if fee_authority == burn_address:
            fee_authority_status = "REVOKED"
        elif fee_authority:
            fee_authority_status = f"ACTIVE"
        else:
            fee_authority_status = "NONE"
            
        logger.info(f"Transfer Fees: {fee_status}")
        logger.info(f"Transfer Fee Authority: {fee_authority_status}")
        
        # Metadata status
        if report.get('tokenMeta'):
            mutable_status = "YES" if report['tokenMeta']['mutable'] else "NO"
            logger.info(f"Mutable Metadata: {mutable_status}")
        
        # Launchpad info
        if report.get('launchpad'):
            logger.info(f"Launchpad: {report['launchpad']['name']}")
        
        # Social links
        socials = report.get('socials', {})
        if socials and any(socials.values()):
            logger.info("Social Links:")
            if socials.get('twitter'):
                logger.info(f"  Twitter: {socials['twitter']}")
            if socials.get('telegram'):
                logger.info(f"  Telegram: {socials['telegram']}")
            if socials.get('website'):
                logger.info(f"  Website: {socials['website']}")
        
        if report.get('creator') and report['creator'] != "Unknown":
            logger.info(f"Creator: {report['creator']}")
        else:
            logger.info("Creator: Not identified")

        # Creator analysis summary
        if report.get('creator_analysis'):
            ca = report['creator_analysis']
            logger.info("--- Creator Analysis ---")
            logger.info(f"  Reputation Score: {ca.get('reputation_score', 0.0):.1f}/100 | Risk Score: {ca.get('risk_score', 0.0):.1f}/100")
            
            if ca.get('total_tokens', 0) > 0:
                logger.info(f"  History: {ca['total_tokens']} tokens created since {ca['first_token_date'].strftime('%Y-%m-%d') if ca.get('first_token_date') else 'N/A'}")
                logger.info(f"  Success Rate: {ca.get('success_rate', 0.0)*100:.1f}% ({ca.get('successful_tokens', 0)} successful, {ca.get('failed_tokens', 0)} failed)")
                logger.info(f"  Avg. ROI: {ca.get('avg_roi', 0.0):.2f}x | Avg. Survival: {ca.get('avg_survival_time', 0.0):.1f} hours")
            
            if ca.get('is_blacklisted'):
                logger.warning(f"  BLACKLISTED: YES - Reason: {ca.get('blacklist_reason', 'N/A')}")
            else:
                logger.info(f"  Blacklisted: NO")

            if ca.get('confidence_level') != 'INSUFFICIENT_DATA':
                logger.info(f"  Analysis Confidence: {ca.get('confidence_level', 'N/A')}")
            logger.info("------------------------")
        
        # Save output
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False, default=json_datetime_serializer)
            logger.info(f"Report saved to: {args.output}")
        else:
            print("\n" + "=" * 50)
            print("JSON REPORT:")
            print("=" * 50)
            print(json.dumps(report, indent=2, ensure_ascii=False, default=json_datetime_serializer))
        
        return 0
        
    except KeyboardInterrupt:
        logger.info("User interruption")
        return 1
    except Exception as e:
        logger.error(f"Error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit(main())