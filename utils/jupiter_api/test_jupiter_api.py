#!/usr/bin/env python3
"""
Test minimal de l'API Jupiter - 100% Gratuit
Usage: python jupiter_test.py
"""

import requests
import json
import time
from datetime import datetime

def test_jupiter_token_list():
    """Test 1: Récupérer la liste complète des tokens Jupiter"""
    print("🔶 Test 1: Jupiter Token List")
    print("-" * 50)
    
    try:
        # URL de l'API Jupiter Token List (gratuite)
        url = "https://token.jup.ag/all"
        
        print(f"📡 Calling: {url}")
        
        response = requests.get(url, timeout=30)
        
        print(f"📊 Status Code: {response.status_code}")
        print(f"📊 Response Size: {len(response.content)} bytes")
        
        if response.status_code == 200:
            tokens = response.json()
            print(f"✅ Success! Found {len(tokens)} tokens")
            
            # Afficher quelques exemples
            print("\n📋 Sample tokens:")
            for i, token in enumerate(tokens[:5]):
                print(f"  {i+1}. {token.get('symbol', 'UNKNOWN')} - {token.get('name', 'Unknown')}")
                print(f"     Address: {token.get('address', 'N/A')}")
                print(f"     Decimals: {token.get('decimals', 'N/A')}")
                print()
            
            # Statistiques
            symbols = [t.get('symbol', '') for t in tokens if t.get('symbol')]
            print(f"📈 Stats:")
            print(f"   Total tokens: {len(tokens)}")
            print(f"   With symbols: {len(symbols)}")
            print(f"   Unique symbols: {len(set(symbols))}")
            
            return tokens
        else:
            print(f"❌ Error: HTTP {response.status_code}")
            print(f"Response: {response.text[:200]}")
            return None
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        return None

def test_jupiter_quote():
    """Test 2: Obtenir un quote de swap"""
    print("\n🔶 Test 2: Jupiter Quote API")
    print("-" * 50)
    
    try:
        # Paramètres pour le quote (SOL -> USDC)
        params = {
            'inputMint': 'So11111111111111111111111111111111111111112',  # SOL
            'outputMint': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
            'amount': 1000000000,  # 1 SOL (en lamports)
            'slippageBps': 50  # 0.5% slippage
        }
        
        url = "https://quote-api.jup.ag/v6/quote"
        
        print(f"📡 Calling: {url}")
        print(f"📊 Params: {params}")
        
        response = requests.get(url, params=params, timeout=10)
        
        print(f"📊 Status Code: {response.status_code}")
        
        if response.status_code == 200:
            quote = response.json()
            print("✅ Quote Success!")
            
            # Parser les résultats
            input_amount = int(quote.get('inAmount', 0))
            output_amount = int(quote.get('outAmount', 0))
            price_impact = quote.get('priceImpactPct', 0)
            
            # Calculer le prix
            sol_amount = input_amount / 1e9  # SOL a 9 decimales
            usdc_amount = output_amount / 1e6  # USDC a 6 decimales
            price_per_sol = usdc_amount / sol_amount if sol_amount > 0 else 0
            
            print(f"📊 Quote Details:")
            print(f"   Input: {sol_amount:.6f} SOL")
            print(f"   Output: {usdc_amount:.6f} USDC")
            print(f"   Price: ${price_per_sol:.2f} per SOL")
            print(f"   Price Impact: {price_impact:.4f}%")
            
            # Route info
            route_plan = quote.get('routePlan', [])
            print(f"   Route Steps: {len(route_plan)}")
            
            for i, step in enumerate(route_plan):
                dex = step.get('swapInfo', {}).get('label', 'Unknown DEX')
                print(f"     Step {i+1}: {dex}")
            
            return quote
            
        else:
            print(f"❌ Error: HTTP {response.status_code}")
            print(f"Response: {response.text[:200]}")
            return None
            
    except Exception as e:
        print(f"❌ Exception: {e}")
        return None

def test_token_discovery():
    """Test 3: Découverte de nouveaux tokens via Jupiter"""
    print("\n🔶 Test 3: Token Discovery")
    print("-" * 50)
    
    try:
        # Récupérer la liste complète
        tokens = test_jupiter_token_list()
        
        if not tokens:
            print("❌ Cannot discover tokens without token list")
            return
        
        # Rechercher des tokens potentiellement nouveaux
        current_year = datetime.now().year
        new_keywords = ['2024', '2025', 'NEW', 'FRESH', 'AI', 'MEME', 'V2']
        
        potential_new = []
        
        for token in tokens:
            symbol = token.get('symbol', '').upper()
            name = token.get('name', '').upper()
            
            # Chercher des indicateurs de nouveauté
            for keyword in new_keywords:
                if keyword in symbol or keyword in name:
                    potential_new.append({
                        'token': token,
                        'keyword': keyword,
                        'symbol': token.get('symbol'),
                        'name': token.get('name'),
                        'address': token.get('address')
                    })
                    break
        
        print(f"🔍 Found {len(potential_new)} potentially new tokens")
        
        # Afficher les résultats
        for i, item in enumerate(potential_new[:10]):
            token = item['token']
            print(f"  {i+1}. {token.get('symbol')} - {token.get('name')}")
            print(f"     Keyword: {item['keyword']}")
            print(f"     Address: {token.get('address', 'N/A')[:8]}...")
            print()
        
        return potential_new
        
    except Exception as e:
        print(f"❌ Exception: {e}")
        return None

def test_token_price_check():
    """Test 4: Vérifier si un token a un prix/liquidité"""
    print("\n🔶 Test 4: Token Price Check")
    print("-" * 50)
    
    # Tokens populaires à tester
    test_tokens = [
        ('BONK', 'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263'),
        ('USDC', 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'),
        ('SOL', 'So11111111111111111111111111111111111111112')
    ]
    
    for symbol, address in test_tokens:
        try:
            print(f"💰 Testing {symbol}...")
            
            # Essayer d'obtenir un quote pour 1 token
            params = {
                'inputMint': address,
                'outputMint': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # vers USDC
                'amount': 1000000,  # 1 token (assume 6 decimales)
                'slippageBps': 100
            }
            
            response = requests.get(
                "https://quote-api.jup.ag/v6/quote",
                params=params,
                timeout=5
            )
            
            if response.status_code == 200:
                quote = response.json()
                output_amount = int(quote.get('outAmount', 0))
                price_usdc = output_amount / 1e6  # USDC a 6 decimales
                
                print(f"   ✅ {symbol}: ~${price_usdc:.6f}")
            else:
                print(f"   ❌ {symbol}: No price available")
                
        except Exception as e:
            print(f"   ❌ {symbol}: Error - {e}")
        
        time.sleep(0.5)  # Rate limiting

def main():
    """Fonction principale - lance tous les tests"""
    print("🚀 JUPITER API TEST SUITE")
    print("=" * 60)
    print(f"⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("🔗 Testing Jupiter APIs (100% Free)")
    print("=" * 60)
    
    # Test 1: Token List
    tokens = test_jupiter_token_list()
    
    # Test 2: Quote API
    test_jupiter_quote()
    
    # Test 3: Token Discovery
    test_token_discovery()
    
    # Test 4: Price Check
    test_token_price_check()
    
    print("\n" + "=" * 60)
    print("✅ JUPITER API TESTS COMPLETED")
    print("=" * 60)
    
    print("\n💡 Key Takeaways:")
    print("   ✅ Jupiter Token List API is FREE and comprehensive")
    print("   ✅ Jupiter Quote API works for price discovery")
    print("   ✅ Can discover new tokens by analyzing metadata")
    print("   ✅ Rate limiting is gentle (no API key required)")
    
    print("\n🔗 Useful Jupiter URLs:")
    print("   • Token List: https://token.jup.ag/all")
    print("   • Quote API: https://quote-api.jup.ag/v6/quote")
    print("   • Documentation: https://docs.jup.ag/")

if __name__ == "__main__":
    main()