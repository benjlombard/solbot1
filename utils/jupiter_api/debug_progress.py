#!/usr/bin/env python3
import asyncio
import aiohttp
import json
import sys

async def test_all_sources():
    address = "41vZZpGqBQ2dGxS99cmWZuQuC7X97VbcqiAobp29pump"
    
    print(f"🔍 Testing token: {address}")
    print("=" * 60)
    
    # Test 1: API Pump.fun (différentes URLs possibles)
    pump_urls = [
        f"https://frontend-api.pump.fun/coins/{address}",
        f"https://api.pump.fun/coins/{address}",
        f"https://pump.fun/api/coins/{address}",
    ]
    
    for i, url in enumerate(pump_urls, 1):
        print(f"\n🧪 Test {i}: {url}")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as resp:
                    print(f"   Status: {resp.status}")
                    if resp.status == 200:
                        try:
                            data = await resp.json()
                            print(f"   ✅ Success! Data keys: {list(data.keys())}")
                            print(f"   Raw data: {json.dumps(data, indent=2)[:500]}...")
                            return data
                        except Exception as e:
                            print(f"   ❌ JSON parse error: {e}")
                    else:
                        text = await resp.text()
                        print(f"   Response: {text[:200]}...")
        except Exception as e:
            print(f"   ❌ Request error: {e}")
    
    # Test 2: DexScreener
    print(f"\n🧪 Test DexScreener API:")
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
            async with session.get(url, timeout=10) as resp:
                print(f"   Status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    print(f"   ✅ Success! Found {len(data.get('pairs', []))} pairs")
                    if data.get('pairs'):
                        pair = data['pairs'][0]
                        print(f"   Market Cap: ${pair.get('marketCap', 'N/A')}")
                        print(f"   Liquidity: ${pair.get('liquidity', {}).get('usd', 'N/A')}")
                        print(f"   DEX: {pair.get('dexId', 'N/A')}")
                        return data
                else:
                    text = await resp.text()
                    print(f"   Response: {text[:200]}...")
    except Exception as e:
        print(f"   ❌ Request error: {e}")
    
    # Test 3: Alternative - scraper web Pump.fun
    print(f"\n🧪 Test direct web scrape:")
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://pump.fun/coin/{address}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            async with session.get(url, headers=headers, timeout=10) as resp:
                print(f"   Status: {resp.status}")
                if resp.status == 200:
                    text = await resp.text()
                    print(f"   ✅ Got HTML ({len(text)} chars)")
                    # Chercher des patterns dans le HTML
                    if 'progress' in text.lower():
                        print("   📊 Found 'progress' in HTML")
                    if 'market cap' in text.lower():
                        print("   💰 Found 'market cap' in HTML")
                else:
                    print(f"   ❌ Failed: {resp.status}")
    except Exception as e:
        print(f"   ❌ Request error: {e}")
    
    return None

if __name__ == "__main__":
    try:
        result = asyncio.run(test_all_sources())
        if not result:
            print("\n❌ Aucune source n'a fonctionné")
        else:
            print(f"\n✅ Données récupérées avec succès")
    except Exception as e:
        print(f"❌ Erreur fatale: {e}")
        sys.exit(1)