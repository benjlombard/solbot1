import struct
import aiohttp
import asyncio
from typing import Dict, Optional
import logging
from solders.pubkey import Pubkey

logger = logging.getLogger(__name__)

# Constantes Pump.fun
PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

def get_bonding_curve_address(mint_address: str) -> str:
    """Calcule l'adresse PDA de la bonding curve"""
    try:
        mint_pubkey = Pubkey.from_string(mint_address)
        pump_program = Pubkey.from_string(PUMP_PROGRAM_ID)
        
        seeds = [b"bonding-curve", bytes(mint_pubkey)]
        bonding_curve_address, _ = Pubkey.find_program_address(seeds, pump_program)
        
        return str(bonding_curve_address)
    except Exception as e:
        logger.error(f"Error calculating bonding curve PDA: {e}")
        return ""

def calculate_progress_from_reserves(virtual_token_reserves: int, real_token_reserves: int) -> Dict:
    """Calcule le progrès à partir des réserves"""
    try:
        # Constantes Pump.fun
        initial_virtual_tokens = 1_073_000_000 * 10**6  # 1.073B tokens virtuels au départ
        tokens_to_sell = 793_100_000 * 10**6  # Tokens vendables pour 100%
        
        # Méthode 1: Basée sur virtual_token_reserves (recommandée)
        tokens_sold_virtual = initial_virtual_tokens - virtual_token_reserves
        progress_virtual = (tokens_sold_virtual / tokens_to_sell) * 100
        progress_virtual = max(0, min(progress_virtual, 100))
        
        # Méthode 2: Basée sur real_token_reserves (alternative)
        real_tokens = real_token_reserves / 10**6
        tokens_sold_real = (793_100_000 - real_tokens)
        progress_real = (tokens_sold_real / 793_100_000) * 100
        progress_real = max(0, min(progress_real, 100))
        
        return {
            'progress_virtual': round(progress_virtual, 2),
            'progress_real': round(progress_real, 2),
            'tokens_sold_virtual': tokens_sold_virtual / 10**6,
            'final_progress': progress_virtual  # Utiliser virtual par défaut
        }
    except Exception as e:
        logger.error(f"Error calculating progress: {e}")
        return {'final_progress': 0, 'progress_virtual': 0, 'progress_real': 0}

async def get_pump_progress_api_first(
    token_address: str, 
    db_bonding_curve: Optional[str] = None,
    db_associated_bonding_curve: Optional[str] = None,
    helius_api_key: Optional[str] = None
) -> Optional[Dict]:
    """
    Version optimisée : API Pump.fun en priorité, puis Helius en fallback
    """
    logger.info(f"🎯 Getting progress for token: {token_address}")
    
    # 🥇 PRIORITÉ 1: API Pump.fun (rapide et complet)
    try:
        logger.debug(f"📡 Trying Pump.fun API for {token_address}")
        
        async with aiohttp.ClientSession() as session:
            url = f"https://frontend-api-v3.pump.fun/coins/{token_address}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json'
            }
            
            async with session.get(url, headers=headers, timeout=8) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Extraire les données essentielles
                    virtual_sol_reserves = data.get('virtual_sol_reserves', 0)
                    virtual_token_reserves = data.get('virtual_token_reserves', 0)
                    real_sol_reserves = data.get('real_sol_reserves', 0)
                    real_token_reserves = data.get('real_token_reserves', 0)
                    complete = data.get('complete', False)
                    market_cap_usd = data.get('usd_market_cap', 0)
                    
                    # Calculer le progrès avec nos formules
                    progress_calc = calculate_progress_from_reserves(virtual_token_reserves, real_token_reserves)
                    
                    # Calculer le prix si possible
                    price_sol = 0
                    if virtual_sol_reserves > 0 and virtual_token_reserves > 0:
                        price_sol = virtual_sol_reserves / virtual_token_reserves
                    
                    result = {
                        'bonding_curve_progress': progress_calc['final_progress'] / 100,
                        'virtual_sol_reserves': virtual_sol_reserves,
                        'virtual_token_reserves': virtual_token_reserves,
                        'real_sol_reserves': real_sol_reserves,
                        'real_token_reserves': real_token_reserves,
                        'complete': complete,
                        'price_sol': price_sol,
                        'market_cap_usd': market_cap_usd,
                        'tokens_sold_virtual': progress_calc.get('tokens_sold_virtual', 0),
                        'progress_virtual': progress_calc['progress_virtual'],
                        'progress_real': progress_calc['progress_real'],
                        'success': True,
                        'source': 'pumpfun_api',
                        'response_time': 'fast'
                    }
                    
                    logger.info(f"✅ [{token_address[:8]}] API success: {progress_calc['final_progress']:.2f}% progress")
                    logger.debug(f"   💰 Market cap: ${market_cap_usd:,.2f}")
                    logger.debug(f"   🔄 Complete: {complete}")
                    
                    return result
                
                elif response.status == 404:
                    logger.info(f"🚫 Token {token_address} not found on Pump.fun (404)")
                    return {
                        'bonding_curve_progress': 0.0,
                        'success': True,
                        'complete': False,
                        'source': 'pumpfun_api_not_found',
                        'message': 'Token not found on Pump.fun'
                    }
                
                else:
                    logger.warning(f"⚠️ Pump.fun API returned status {response.status} for {token_address}")
                    
    except asyncio.TimeoutError:
        logger.warning(f"⏱️ Pump.fun API timeout for {token_address}")
    except Exception as e:
        logger.warning(f"❌ Pump.fun API failed for {token_address}: {e}")
    
    # 🥈 FALLBACK 1: Helius RPC (si API key disponible)
    if helius_api_key:
        logger.debug(f"🔗 Fallback to Helius RPC for {token_address}")
        
        try:
            # Calculer l'adresse de bonding curve
            bonding_curve_address = db_bonding_curve or get_bonding_curve_address(token_address)
            
            if not bonding_curve_address:
                logger.error(f"❌ Cannot calculate bonding curve address for {token_address}")
                return None
            
            # Appel RPC Helius
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
                async with session.post(rpc_url, json=payload, timeout=12) as response:
                    if response.status == 200:
                        rpc_data = await response.json()
                        
                        if 'result' in rpc_data and rpc_data['result'] and rpc_data['result']['value']:
                            account_info = rpc_data['result']['value']
                            account_data = account_info.get('data')
                            
                            if account_data and len(account_data) >= 2:
                                import base64
                                raw_data = base64.b64decode(account_data[0])
                                
                                if len(raw_data) >= 49:
                                    try:
                                        # Parser la structure on-chain
                                        virtual_token_reserves = struct.unpack('<Q', raw_data[0x08:0x10])[0]
                                        virtual_sol_reserves = struct.unpack('<Q', raw_data[0x10:0x18])[0]
                                        real_token_reserves = struct.unpack('<Q', raw_data[0x18:0x20])[0]
                                        real_sol_reserves = struct.unpack('<Q', raw_data[0x20:0x28])[0]
                                        complete = struct.unpack('<?', raw_data[0x30:0x31])[0]
                                        
                                        # Calculer le progrès
                                        progress_calc = calculate_progress_from_reserves(virtual_token_reserves, real_token_reserves)
                                        
                                        # Calculer prix et market cap
                                        price_sol = 0
                                        market_cap = 0
                                        if virtual_sol_reserves > 0 and virtual_token_reserves > 0:
                                            price_sol = virtual_sol_reserves / virtual_token_reserves
                                            price_usd = price_sol * 180  # Approximation SOL = $180
                                            market_cap = price_usd * 1_000_000_000  # 1B supply
                                        
                                        result = {
                                            'bonding_curve_progress': progress_calc['final_progress'] / 100,
                                            'virtual_sol_reserves': virtual_sol_reserves,
                                            'virtual_token_reserves': virtual_token_reserves,
                                            'real_sol_reserves': real_sol_reserves,
                                            'real_token_reserves': real_token_reserves,
                                            'complete': complete,
                                            'price_sol': price_sol,
                                            'market_cap': market_cap,
                                            'tokens_sold_virtual': progress_calc.get('tokens_sold_virtual', 0),
                                            'progress_virtual': progress_calc['progress_virtual'],
                                            'progress_real': progress_calc['progress_real'],
                                            'success': True,
                                            'source': 'helius_onchain',
                                            'response_time': 'slow'
                                        }
                                        
                                        logger.info(f"✅ [{token_address[:8]}] Helius fallback success: {progress_calc['final_progress']:.2f}%")
                                        return result
                                        
                                    except Exception as e:
                                        logger.error(f"❌ Error parsing on-chain data for {token_address}: {e}")
                        
                        else:
                            logger.debug(f"🚫 No on-chain account found for {bonding_curve_address}")
                    
                    else:
                        logger.error(f"❌ Helius RPC error {response.status} for {token_address}")
        
        except asyncio.TimeoutError:
            logger.warning(f"⏱️ Helius RPC timeout for {token_address}")
        except Exception as e:
            logger.warning(f"❌ Helius RPC failed for {token_address}: {e}")
    
    else:
        logger.debug(f"⏭️ Skipping Helius fallback (no API key) for {token_address}")
    
    # 🥉 FALLBACK 2: DexScreener (estimation basique)
    logger.debug(f"📊 Final fallback to DexScreener for {token_address}")
    
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            
            async with session.get(url, timeout=8) as response:
                if response.status == 200:
                    data = await response.json()
                    pairs = data.get('pairs', [])
                    
                    for pair in pairs:
                        if 'pump' in pair.get('dexId', '').lower():
                            market_cap = pair.get('marketCap', 0)
                            
                            if market_cap > 0:
                                # Estimation grossière basée sur market cap
                                target_market_cap = 126000  # ~$126k pour 100%
                                progress = min((market_cap / target_market_cap) * 100, 100)
                                
                                result = {
                                    'bonding_curve_progress': progress / 100,
                                    'market_cap': market_cap,
                                    'success': True,
                                    'source': 'dexscreener_estimate',
                                    'estimated': True
                                }
                                
                                logger.info(f"📊 [{token_address[:8]}] DexScreener estimate: {progress:.2f}%")
                                return result
                                
    except Exception as e:
        logger.warning(f"❌ DexScreener fallback failed for {token_address}: {e}")
    
    # 💀 Échec total : estimation conservative
    logger.warning(f"💀 All methods failed for {token_address}, returning conservative estimate")
    return {
        'bonding_curve_progress': 0.0,
        'success': False,
        'estimated': True,
        'source': 'failed_all_methods',
        'message': 'All data sources failed'
    }

# Version simplifiée pour usage courant
async def get_pump_progress(token_address: str, helius_api_key: Optional[str] = None) -> Optional[Dict]:
    """Version simplifiée avec gestion d'erreurs propre"""
    result = await get_pump_progress_api_first(token_address, helius_api_key=helius_api_key)
    
    if result and result.get('success'):
        progress_percent = result['bonding_curve_progress'] * 100
        source = result.get('source', 'unknown')
        
        logger.info(f"🎯 {token_address[:8]}: {progress_percent:.2f}% (via {source})")
        
        return result
    
    logger.error(f"❌ Failed to get progress for {token_address}")
    return None

# Fonction de test
async def test_optimized_version(token_address: str, helius_api_key: Optional[str] = None):
    """Test de la version optimisée"""
    print(f"\n🧪 Testing optimized version for {token_address}")
    print("=" * 60)
    
    import time
    start_time = time.time()
    
    result = await get_pump_progress_api_first(token_address, helius_api_key=helius_api_key)
    
    end_time = time.time()
    duration = end_time - start_time
    
    print(f"⏱️  Duration: {duration:.2f}s")
    
    if result and result.get('success'):
        progress = result['bonding_curve_progress'] * 100
        source = result.get('source', 'unknown')
        
        print(f"✅ Success via {source}")
        print(f"📊 Progress: {progress:.2f}%")
        
        if 'market_cap_usd' in result:
            print(f"💰 Market Cap: ${result['market_cap_usd']:,.2f}")
        
        if 'complete' in result:
            print(f"🏁 Complete: {result['complete']}")
            
        if result.get('response_time'):
            print(f"🚀 Speed: {result['response_time']}")
            
    else:
        print("❌ Failed to retrieve data")
        
    return result

# Exemple d'usage
if __name__ == "__main__":
    async def main():
        # Test avec un token d'exemple
        test_token = "7igth4c6og8kQtdEYT7fxDGmbod7HVrofQJur5Fqpump"  # Ton exemple
        helius_key = "your-helius-api-key"  # Optionnel
        
        await test_optimized_version(test_token, helius_key)
    
    asyncio.run(main())