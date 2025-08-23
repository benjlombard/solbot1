import struct
import aiohttp
import asyncio
from typing import Dict, Optional
import logging
from solders.pubkey import Pubkey

logger = logging.getLogger(__name__)

# Constantes Pump.fun correctes
PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

def get_bonding_curve_address(mint_address: str) -> str:
    """Calcule l'adresse PDA correcte de la bonding curve"""
    try:
        mint_pubkey = Pubkey.from_string(mint_address)
        pump_program = Pubkey.from_string(PUMP_PROGRAM_ID)
        
        # Calcul PDA correct avec les seeds officielles
        seeds = [b"bonding-curve", bytes(mint_pubkey)]
        bonding_curve_address, _ = Pubkey.find_program_address(seeds, pump_program)
        
        return str(bonding_curve_address)
    except Exception as e:
        logger.error(f"Error calculating bonding curve PDA: {e}")
        return ""

async def get_pump_progress_correct(
    token_address: str, 
    db_bonding_curve: Optional[str],
    db_associated_bonding_curve: Optional[str],
    helius_api_key: str
) -> Optional[Dict]:
    """
    Solution corrigée utilisant la vraie structure de données Pump.fun
    Basée sur https://gist.github.com/rubpy/6c57e9d12acd4b6ed84e9f205372631d
    """
    logger.debug(f"Getting progress for: {token_address}")
    
    try:
        # 1. Calculer ou utiliser l'adresse de bonding curve
        if db_bonding_curve:
            bonding_curve_address = db_bonding_curve
        else:
            bonding_curve_address = get_bonding_curve_address(token_address)
        
        logger.debug(f"Bonding curve address: {bonding_curve_address}")
        
        # 2. Récupérer les données on-chain
        rpc_url = f"https://mainnet.helius-rpc.com/?api-key={helius_api_key}"
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getAccountInfo",
            "params": [
                bonding_curve_address,
                {
                    "encoding": "base64",
                    "commitment": "confirmed"
                }
            ]
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(rpc_url, json=payload, timeout=15) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if 'result' in data and data['result'] and data['result']['value']:
                        account_info = data['result']['value']
                        account_data = account_info.get('data')
                        
                        if account_data and len(account_data) >= 2:
                            import base64
                            raw_data = base64.b64decode(account_data[0])
                            
                            if len(raw_data) >= 49:  # Besoin d'au moins 49 bytes pour la structure complète
                                try:
                                    # Structure de données Pump.fun selon l'IDL officiel
                                    # Source: https://gist.github.com/rubpy/6c57e9d12acd4b6ed84e9f205372631d
                                    
                                    # Vérifier le discriminator (8 premiers bytes)
                                    discriminator = raw_data[:8]
                                    expected_discriminator = bytes([0x17, 0xb7, 0xf8, 0x37, 0x60, 0xd8, 0xac, 0x60])
                                    
                                    if discriminator != expected_discriminator:
                                        logger.debug(f"Unexpected discriminator for {token_address}: {discriminator.hex()}")
                                    
                                    # Offsets corrects selon la structure Pump.fun
                                    virtual_token_reserves = struct.unpack('<Q', raw_data[0x08:0x10])[0]  # 8-16
                                    virtual_sol_reserves = struct.unpack('<Q', raw_data[0x10:0x18])[0]    # 16-24
                                    real_token_reserves = struct.unpack('<Q', raw_data[0x18:0x20])[0]     # 24-32
                                    real_sol_reserves = struct.unpack('<Q', raw_data[0x20:0x28])[0]       # 32-40
                                    token_total_supply = struct.unpack('<Q', raw_data[0x28:0x30])[0]      # 40-48
                                    complete = struct.unpack('<?', raw_data[0x30:0x31])[0]               # 48-49
                                    
                                    logger.debug(f"Bonding curve data for {token_address}:")
                                    logger.debug(f"  Virtual token reserves: {virtual_token_reserves:,}")
                                    logger.debug(f"  Virtual SOL reserves: {virtual_sol_reserves:,}")
                                    logger.debug(f"  Real token reserves: {real_token_reserves:,}")
                                    logger.debug(f"  Real SOL reserves: {real_sol_reserves:,}")
                                    logger.debug(f"  Complete: {complete}")
                                    
                                    # Calcul du progrès selon la formule officielle Pump.fun
                                    # Source: Documentation et reverse engineering
                                    initial_virtual_tokens = 1_073_000_000  # Total virtual au départ
                                    tokens_to_sell = 793_100_000  # Tokens vendables pour atteindre 100%
                                    
                                    # Méthode 1: Basée sur virtual_token_reserves (recommandée)
                                    tokens_sold_virtual = (initial_virtual_tokens * 10**6 - virtual_token_reserves) / (10**6)
                                    progress_virtual = (tokens_sold_virtual / tokens_to_sell) * 100
                                    progress_virtual = max(0, min(progress_virtual, 100))
                                    
                                    # Méthode 2: Basée sur real_token_reserves (alternative)
                                    real_tokens = real_token_reserves / (10**6)  # Convertir en tokens réels
                                    tokens_sold_real = tokens_to_sell - real_tokens
                                    progress_real = (tokens_sold_real / tokens_to_sell) * 100
                                    progress_real = max(0, min(progress_real, 100))
                                    
                                    # Utiliser la méthode virtual par défaut
                                    final_progress = progress_virtual
                                    
                                    logger.debug(f"Progress calculation for {token_address}:")
                                    logger.debug(f"  Tokens sold (virtual): {tokens_sold_virtual:,.0f}")
                                    logger.debug(f"  Progress (virtual method): {progress_virtual:.2f}%")
                                    logger.debug(f"  Progress (real method): {progress_real:.2f}%")
                                    logger.debug(f"  Final progress: {final_progress:.2f}%")
                                    
                                    # Calculer le prix et market cap
                                    price_sol = 0
                                    market_cap = 0
                                    
                                    if virtual_sol_reserves > 0 and virtual_token_reserves > 0:
                                        # Prix = virtual_sol / virtual_token (en SOL par token)
                                        price_sol = virtual_sol_reserves / virtual_token_reserves
                                        price_usd = price_sol * 180  # Approximation SOL = $180
                                        market_cap = price_usd * 1_000_000_000  # 1B total supply
                                        
                                        logger.debug(f"  Price: {price_sol:.10f} SOL (${price_usd:.10f})")
                                        logger.debug(f"  Market Cap: ${market_cap:,.2f}")
                                    
                                    return {
                                        'bonding_curve_progress': round(final_progress, 2),
                                        'virtual_sol_reserves': virtual_sol_reserves,
                                        'virtual_token_reserves': virtual_token_reserves,
                                        'real_sol_reserves': real_sol_reserves,
                                        'real_token_reserves': real_token_reserves,
                                        'complete': complete,
                                        'price_sol': price_sol,
                                        'market_cap': market_cap,
                                        'tokens_sold_virtual': tokens_sold_virtual,
                                        'progress_virtual': round(progress_virtual, 2),
                                        'progress_real': round(progress_real, 2),
                                        'success': True,
                                        'source': 'onchain_correct'
                                    }
                                    
                                except Exception as e:
                                    logger.error(f"Error decoding bonding curve data for {token_address}: {e}")
                                    logger.error(f"Data preview: {raw_data[:64].hex()}")
                            else:
                                logger.debug(f"Insufficient data length for {token_address}: {len(raw_data)} bytes")
                        else:
                            logger.debug(f"No account data for bonding curve {bonding_curve_address}")
                    else:
                        logger.debug(f"No account found for bonding curve {bonding_curve_address}")
                else:
                    logger.error(f"RPC error {response.status} for {token_address}")
        
    except asyncio.TimeoutError:
        logger.error(f"Timeout fetching bonding curve data for {token_address}")
    except Exception as e:
        logger.error(f"Error in get_pump_progress_correct for {token_address}: {e}")
    
    # Fallback: essayer l'API Pump.fun
    try:
        logger.debug(f"Fallback to Pump.fun API for {token_address}")
        
        async with aiohttp.ClientSession() as session:
            url = f"https://frontend-api-v3.pump.fun/coins/{token_address}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            async with session.get(url, headers=headers, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    progress = data.get('bonding_curve_progress')
                    
                    if progress is not None:
                        logger.debug(f"Got progress from Pump.fun API: {progress}%")
                        return {
                            'bonding_curve_progress': float(progress),
                            'success': True,
                            'source': 'pumpfun_api'
                        }
                elif response.status == 404:
                    logger.debug(f"Token {token_address} not found on Pump.fun")
                    return {
                        'bonding_curve_progress': 0.0,
                        'success': True,
                        'source': 'pumpfun_api_not_found'
                    }
                    
    except Exception as e:
        logger.error(f"Pump.fun API fallback failed for {token_address}: {e}")
    
    # Fallback final: estimation conservative
    logger.debug(f"All methods failed for {token_address}, using conservative estimate")
    return {
        'bonding_curve_progress': 1.0,  # Estimation très conservative
        'success': False,
        'estimated': True,
        'source': 'estimated'
    }

# Version alternative utilisant DexScreener pour validation
async def get_pump_progress_via_dexscreener(token_address: str) -> Optional[Dict]:
    """
    Méthode alternative utilisant DexScreener pour validation
    """
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    pairs = data.get('pairs', [])
                    
                    for pair in pairs:
                        if 'pump' in pair.get('dexId', '').lower():
                            market_cap = pair.get('marketCap', 0)
                            
                            if market_cap > 0:
                                # Estimation basée sur le market cap
                                # Note: Cette méthode est moins précise que l'on-chain
                                target_market_cap = 126000  # Approximation pour 100%
                                progress = (market_cap / target_market_cap) * 100
                                progress = max(0, min(progress, 100))
                                
                                return {
                                    'bonding_curve_progress': round(progress, 2),
                                    'market_cap': market_cap,
                                    'success': True,
                                    'source': 'dexscreener'
                                }
                                
    except Exception as e:
        logger.error(f"DexScreener method failed for {token_address}: {e}")
    
    return None

# Version pour tests
async def test_bonding_curve_calculation(token_address: str, helius_api_key: str):
    """
    Version de test pour comparer les méthodes
    """
    print(f"🧪 Testing bonding curve calculation for {token_address}")
    
    # Méthode 1: On-chain correct
    result1 = await get_pump_progress_correct(token_address, None, None, helius_api_key)
    
    # Méthode 2: DexScreener
    result2 = await get_pump_progress_via_dexscreener(token_address)
    
    print(f"📊 Results:")
    if result1 and result1.get('success'):
        print(f"  On-chain method: {result1['bonding_curve_progress']:.2f}% (source: {result1['source']})")
        if 'progress_virtual' in result1:
            print(f"    Virtual method: {result1['progress_virtual']:.2f}%")
        if 'progress_real' in result1:
            print(f"    Real method: {result1['progress_real']:.2f}%")
        if 'market_cap' in result1:
            print(f"    Market cap: ${result1['market_cap']:,.2f}")
    
    if result2 and result2.get('success'):
        print(f"  DexScreener method: {result2['bonding_curve_progress']:.2f}%")
        print(f"    Market cap: ${result2['market_cap']:,.2f}")
    
    return result1 if result1 and result1.get('success') else result2