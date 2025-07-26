#!/usr/bin/env python3
import requests
import json

def test_pump_apis():
    address = "41vZZpGqBQ2dGxS99cmWZuQuC7X97VbcqiAobp29pump"
    
    # Différentes APIs possibles pour Pump.fun
    apis_to_test = [
        # APIs alternatives trouvées dans la communauté
        f"https://pump.fun/api/coins/{address}",
        f"https://frontend-api.pump.fun/coins/{address}",
        f"https://api.pump.fun/coin/{address}",
        f"https://pump.fun/coin/{address}/info",
        
        # APIs de proxies/wrappers
        f"https://pumpportal.fun/api/data/{address}",
        f"https://api.pumpapi.net/coin/{address}",
        
        # Via des indexeurs tiers
        f"https://api.solanabeach.io/v1/token/{address}",
        f"https://api.solscan.io/token/{address}",
        
        # API Birdeye (souvent utilisée pour les données DeFi)
        f"https://public-api.birdeye.so/defi/token_overview?address={address}",
    ]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://dexscreener.com/',
    }
    
    for i, url in enumerate(apis_to_test, 1):
        print(f"\n🧪 Test {i}: {url}")
        try:
            response = requests.get(url, headers=headers, timeout=10)
            print(f"   Status: {response.status_code}")
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    print(f"   ✅ JSON Success! Keys: {list(data.keys())}")
                    
                    # Chercher des mots-clés liés à la progression
                    json_str = json.dumps(data).lower()
                    keywords = ['progress', 'curve', 'completion', 'reserves', 'bonding', 'target']
                    found_keywords = [kw for kw in keywords if kw in json_str]
                    if found_keywords:
                        print(f"   📊 Found keywords: {found_keywords}")
                    
                    # Afficher les données si elles semblent pertinentes
                    if any(key in json_str for key in ['market', 'cap', 'progress']):
                        print(f"   📄 Data preview: {json.dumps(data, indent=2)[:500]}...")
                        
                except json.JSONDecodeError:
                    text = response.text[:200]
                    print(f"   📄 Text response: {text}...")
                    if 'progress' in text.lower() or 'curve' in text.lower():
                        print(f"   📊 Found progress/curve keywords in HTML")
            else:
                print(f"   ❌ HTTP {response.status_code}")
                
        except Exception as e:
            print(f"   ❌ Error: {e}")

def test_birdeye_specifically():
    """Test spécifique de l'API Birdeye qui est souvent utilisée"""
    address = "41vZZpGqBQ2dGxS99cmWZuQuC7X97VbcqiAobp29pump"
    
    print(f"\n🐦 Test spécifique Birdeye:")
    
    birdeye_urls = [
        f"https://public-api.birdeye.so/defi/token_overview?address={address}",
        f"https://public-api.birdeye.so/v1/token/{address}",
        f"https://public-api.birdeye.so/defi/price?address={address}",
    ]
    
    headers = {
        'X-API-KEY': 'demo',  # Clé demo publique
        'Accept': 'application/json',
    }
    
    for url in birdeye_urls:
        try:
            response = requests.get(url, headers=headers, timeout=10)
            print(f"   {url}")
            print(f"   Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"   ✅ Success: {json.dumps(data, indent=2)[:300]}...")
            else:
                print(f"   Response: {response.text[:100]}")
        except Exception as e:
            print(f"   Error: {e}")

if __name__ == "__main__":
    test_pump_apis()
    test_birdeye_specifically()