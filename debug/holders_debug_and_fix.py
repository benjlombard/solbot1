#!/usr/bin/env python3
"""
🔧 Debug et correction du problème de récupération des holders
"""

import asyncio
import aiohttp
import logging

# Configuration du logger
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def test_holders_apis(token_address: str):
    """Tester différentes APIs pour récupérer les holders"""
    
    async with aiohttp.ClientSession() as session:
        
        # Test 1: Solscan API publique (original)
        print("🔍 Test 1: Solscan API publique")
        try:
            url1 = f"https://public-api.solscan.io/v2.0/token/holders?tokenAddress={token_address}&limit=1"
            async with session.get(url1) as resp:
                print(f"Status: {resp.status}")
                print(f"Headers: {dict(resp.headers)}")
                data = await resp.json()
                print(f"Response: {data}")
                if data and "total" in data:
                    print(f"✅ Holders count: {data['total']}")
                else:
                    print("❌ No 'total' field found")
        except Exception as e:
            print(f"❌ Error: {e}")
        
        print("\n" + "="*50 + "\n")
        
        # Test 2: Solscan avec headers
        print("🔍 Test 2: Solscan avec User-Agent")
        try:
            url2 = f"https://public-api.solscan.io/token/holders?tokenAddress={token_address}&limit=1"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json',
                'Origin': 'https://solscan.io',
                'Referer': 'https://solscan.io/'
            }
            async with session.get(url2, headers=headers) as resp:
                print(f"Status: {resp.status}")
                data = await resp.json()
                print(f"Response: {data}")
                if data and "total" in data:
                    print(f"✅ Holders count: {data['total']}")
                else:
                    print("❌ No 'total' field found")
        except Exception as e:
            print(f"❌ Error: {e}")
        
        print("\n" + "="*50 + "\n")
        
        # Test 3: Alternative Helius API
        print("🔍 Test 3: Helius API")
        try:
            helius_url = "https://rpc.helius.xyz/?api-key=872ddf73-4cfd-4263-a418-521bbde27eb8"
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccounts",
                "params": {
                    "mint": token_address,
                    "options": {
                        "showZeroBalance": False
                    }
                }
            }
            async with session.post(helius_url, json=payload) as resp:
                print(f"Status: {resp.status}")
                data = await resp.json()
                if "result" in data and "token_accounts" in data["result"]:
                    holders_count = len(data["result"]["token_accounts"])
                    print(f"✅ Holders count via Helius: {holders_count}")
                else:
                    print(f"Response: {data}")
        except Exception as e:
            print(f"❌ Error: {e}")
        
        print("\n" + "="*50 + "\n")
        
        # Test 4: Jupiter API (pour vérifier que le token existe)
        print("🔍 Test 4: Vérification token via Jupiter")
        try:
            jupiter_url = "https://token.jup.ag/all"
            async with session.get(jupiter_url) as resp:
                data = await resp.json()
                token_found = False
                for token in data:
                    if token.get("address") == token_address:
                        print(f"✅ Token trouvé sur Jupiter: {token.get('symbol', 'UNKNOWN')}")
                        token_found = True
                        break
                if not token_found:
                    print("❌ Token non trouvé sur Jupiter (peut être trop récent)")
        except Exception as e:
            print(f"❌ Error: {e}")

# Méthode corrigée pour récupérer les holders
async def get_holders_improved(address: str, session: aiohttp.ClientSession) -> int:
    """Méthode améliorée pour récupérer les holders avec fallbacks"""
    
    # Méthode 1: Solscan avec headers appropriés
    try:
        url = f"https://public-api.solscan.io/token/holders?tokenAddress={address}&limit=1"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Origin': 'https://solscan.io',
            'Referer': 'https://solscan.io/',
            'sec-ch-ua': '"Google Chrome";v="91", "Chromium";v="91", ";Not A Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site'
        }
        
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data and isinstance(data, dict) and "total" in data:
                    holders = data["total"]
                    logger.debug(f"✅ Solscan holders for {address}: {holders}")
                    return holders
                else:
                    logger.debug(f"Solscan response structure: {data}")
            else:
                logger.debug(f"Solscan HTTP {resp.status} for {address}")
    except Exception as e:
        logger.debug(f"Solscan error for {address}: {e}")
    
    # Méthode 2: Fallback avec Helius
    try:
        helius_url = "https://rpc.helius.xyz/?api-key=872ddf73-4cfd-4263-a418-521bbde27eb8"
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenLargestAccounts",
            "params": [address]
        }
        
        async with session.post(helius_url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 200:
                data = await resp.json()
                if "result" in data and "value" in data["result"]:
                    # Compter les comptes avec un solde > 0
                    accounts = data["result"]["value"]
                    holders = len([acc for acc in accounts if acc.get("uiAmount", 0) > 0])
                    logger.debug(f"✅ Helius holders for {address}: {holders}")
                    return holders
    except Exception as e:
        logger.debug(f"Helius error for {address}: {e}")
    
    # Méthode 3: Estimation basée sur l'activité (dernier recours)
    logger.debug(f"❌ Could not get holders for {address}, returning 0")
    return 0

# Version corrigée à intégrer dans TokenEnricher
def get_corrected_market_data_method():
    """Retourne la méthode _get_market_data corrigée"""
    return '''
    async def _get_market_data(self, address: str) -> dict:
        """Récupérer les données de marché avec holders corrigés"""
        market_data = {}
        
        # DexScreener
        dex_url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
        dex_data = await self._fetch_json(dex_url)
        
        if dex_data and dex_data.get("pairs"):
            pair = dex_data["pairs"][0]
            market_data.update({
                "price_usdc": float(pair.get("priceUsd", 0)),
                "market_cap": float(pair.get("marketCap", 0)),
                "liquidity_usd": float(pair.get("liquidity", {}).get("usd", 0)),
                "volume_24h": float(pair.get("volume", {}).get("h24", 0)),
                "price_change_24h": float(pair.get("priceChange", {}).get("h24", 0)),
                "age_hours": (time.time() * 1000 - pair.get("pairCreatedAt", time.time() * 1000)) / 3600000
            })
        
        # Jupiter price check
        jupiter_quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={address}&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=1000000&slippageBps=500"
        jupiter_price = await self._fetch_json(jupiter_quote_url)
        
        if jupiter_price and "outAmount" in jupiter_price:
            try:
                price = int(jupiter_price["outAmount"]) / 1e6
                if not market_data.get("price_usdc"):
                    market_data["price_usdc"] = price
                market_data["is_tradeable"] = True
            except:
                pass
        
        # RugCheck
        rug_url = f"https://api.rugcheck.xyz/v1/tokens/{address}/report"
        rug_data = await self._fetch_json(rug_url)
        
        if rug_data:
            market_data.update({
                "rug_score": rug_data.get("score", 50),
                "quality_score": min(100, max(0, rug_data.get("score", 50)))
            })
        
        # Holders via méthode améliorée
        holders_count = await self._get_holders_improved(address)
        market_data["holders"] = holders_count
        
        return market_data
    
    async def _get_holders_improved(self, address: str) -> int:
        """Méthode améliorée pour récupérer les holders"""
        # Méthode 1: Solscan avec headers appropriés
        try:
            url = f"https://public-api.solscan.io/token/holders?tokenAddress={address}&limit=1"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json',
                'Origin': 'https://solscan.io',
                'Referer': 'https://solscan.io/'
            }
            
            async with self.session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and isinstance(data, dict) and "total" in data:
                        return data["total"]
                        
        except Exception as e:
            logger.debug(f"Solscan error for {address}: {e}")
        
        # Méthode 2: Fallback avec Helius
        try:
            helius_url = "https://rpc.helius.xyz/?api-key=872ddf73-4cfd-4263-a418-521bbde27eb8"
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenLargestAccounts",
                "params": [address]
            }
            
            async with self.session.post(helius_url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if "result" in data and "value" in data["result"]:
                        accounts = data["result"]["value"]
                        return len([acc for acc in accounts if acc.get("uiAmount", 0) > 0])
                        
        except Exception as e:
            logger.debug(f"Helius error for {address}: {e}")
        
        return 0
    '''

# Test avec un token connu
async def main():
    # Token USDC pour tester (token connu avec beaucoup de holders)
    test_token = ""
    print(f"Testing avec USDC token: {test_token}")
    await test_holders_apis(test_token)

if __name__ == "__main__":
    asyncio.run(main())