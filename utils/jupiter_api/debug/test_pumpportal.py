#!/usr/bin/env python3
import requests
import json

def test_pumpportal():
    address = "41vZZpGqBQ2dGxS99cmWZuQuC7X97VbcqiAobp29pump"
    
    print(f"🧪 Testing PumpPortal API for: {address}")
    
    # URLs possibles basées sur la doc PumpPortal
    pumpportal_urls = [
        f"https://pumpportal.fun/api/data/{address}",
        f"https://api.pumpportal.fun/data/{address}",
        f"https://pumpportal.fun/api/bonding-curve/{address}",
        f"https://api.pumpportal.fun/token/{address}",
        f"https://pumpportal.fun/api/token/{address}",
    ]
    
    headers = {
        'Accept': 'application/json',
        'User-Agent': 'Mozilla/5.0 (compatible; TokenScanner/1.0)',
    }
    
    for i, url in enumerate(pumpportal_urls, 1):
        print(f"\n📡 Test {i}: {url}")
        try:
            response = requests.get(url, headers=headers, timeout=10)
            print(f"   Status: {response.status_code}")
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    print(f"   ✅ Success! Keys: {list(data.keys())}")
                    print(f"   📄 Data: {json.dumps(data, indent=2)}")
                    
                    # Chercher les champs de progression
                    if 'progress' in data:
                        print(f"   🎯 Progress found: {data['progress']}")
                    if 'bonding_curve' in data:
                        print(f"   📊 Bonding curve data: {data['bonding_curve']}")
                    if 'real_token_reserves' in data:
                        print(f"   💰 Real token reserves: {data['real_token_reserves']}")
                        
                    return data
                    
                except json.JSONDecodeError:
                    text = response.text[:300]
                    print(f"   📄 Text response: {text}...")
            else:
                print(f"   ❌ Error: {response.text[:200]}")
                
        except Exception as e:
            print(f"   ❌ Exception: {e}")
    
    return None

def test_bitquery():
    """Test de l'API Bitquery avec GraphQL"""
    address = "41vZZpGqBQ2dGxS99cmWZuQuC7X97VbcqiAobp29pump"
    
    print(f"\n🔍 Testing Bitquery GraphQL API")
    
    # Requête GraphQL pour obtenir les données de bonding curve
    query = """
    query GetBondingCurveData($address: String!) {
      solana {
        transfers(
          currency: {is: $address}
          options: {limit: 1, desc: "block.timestamp.time"}
        ) {
          currency {
            address
            symbol
          }
          amount
          block {
            timestamp {
              time
            }
          }
        }
        
        accounts(
          currency: {is: $address}
          options: {limit: 10}
        ) {
          currency {
            address
            symbol
          }
          balance
          account {
            address
          }
        }
      }
    }
    """
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ory_at_hbkaZAsdEyEXAVclDT25nAxheu8tB01Zy904O1qLNXE.FNfybgiQ9b5ZEngYmcOnRPuqDfQ_wITc4En9HYfys4M',  # Utiliser une vraie clé API si nécessaire
    }
    
    payload = {
        'query': query,
        'variables': {'address': address}
    }
    
    try:
        response = requests.post(
            'https://graphql.bitquery.io/',
            headers=headers,
            json=payload,
            timeout=15
        )
        
        print(f"   Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ Success! Data: {json.dumps(data, indent=2)[:500]}...")
            return data
        else:
            print(f"   ❌ Error: {response.text[:200]}")
            
    except Exception as e:
        print(f"   ❌ Exception: {e}")
    
    return None

if __name__ == "__main__":
    print("🚀 Testing Real Pump.fun APIs")
    print("=" * 60)
    
    # Test PumpPortal d'abord
    pumpportal_data = test_pumpportal()
    
    # Test Bitquery
    bitquery_data = test_bitquery()
    
    print("\n" + "=" * 60)
    print("📊 SUMMARY")
    print("=" * 60)
    
    if pumpportal_data:
        print("✅ PumpPortal: Success")
    else:
        print("❌ PumpPortal: Failed")
        
    if bitquery_data:
        print("✅ Bitquery: Success")
    else:
        print("❌ Bitquery: Failed")