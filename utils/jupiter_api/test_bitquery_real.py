#!/usr/bin/env python3
import requests
import json

def test_bitquery_v2():
    """Test avec la syntaxe Bitquery v2 correcte"""
    address = "41vZZpGqBQ2dGxS99cmWZuQuC7X97VbcqiAobp29pump"
    
    print(f"🔍 Testing Bitquery v2 API for: {address}")
    
    # Requête basée sur la vraie documentation Bitquery v2
    query = """
    {
      solana(dataset: combined) {
        balanceUpdates(
          where: {
            balanceUpdate: {
              currency: {
                address: {is: "%s"}
              }
            }
            transaction: {result: {success: true}}
          }
          orderBy: {descending: blockDate}
          limit: {count: 20}
        ) {
          blockDate
          balanceUpdate {
            account {
              address
            }
            amount
            currency {
              address
              symbol
              decimals
            }
            preBalance
            postBalance
          }
          transaction {
            signature
          }
        }
      }
    }
    """ % address
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ory_at_hbkaZAsdEyEXAVclDT25nAxheu8tB01Zy904O1qLNXE.FNfybgiQ9b5ZEngYmcOnRPuqDfQ_wITc4En9HYfys4M',  # Remplacez par votre vraie clé
    }
    
    payload = {
        'query': query
    }
    
    try:
        response = requests.post(
            'https://graphql.bitquery.io/',
            headers=headers,
            json=payload,
            timeout=20
        )
        
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            
            if 'errors' in data:
                print(f"❌ GraphQL Errors: {data['errors']}")
                
                # Essayer une requête plus simple
                return test_simple_query(address)
            else:
                print(f"✅ Success!")
                print(f"📄 Response: {json.dumps(data, indent=2)[:1000]}...")
                
                # Analyser les données
                if 'data' in data and 'solana' in data['data']:
                    balance_updates = data['data']['solana']['balanceUpdates']
                    return analyze_balance_updates(balance_updates, address)
                
        else:
            print(f"❌ HTTP Error: {response.text}")
            
    except Exception as e:
        print(f"❌ Exception: {e}")
    
    return None

def test_simple_query(address):
    """Test avec une requête ultra-simple"""
    print(f"\n🧪 Trying simple query for {address}")
    
    # Requête minimale pour tester la syntaxe
    query = """
    {
      solana {
        instructions(
          where: {
            instruction: {
              program: {
                address: {is: "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"}
              }
            }
          }
          limit: {count: 5}
        ) {
          instruction {
            program {
              address
            }
          }
        }
      }
    }
    """
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ory_at_hbkaZAsdEyEXAVclDT25nAxheu8tB01Zy904O1qLNXE.FNfybgiQ9b5ZEngYmcOnRPuqDfQ_wITc4En9HYfys4M',  # Remplacez par votre vraie clé
    }
    
    payload = {'query': query}
    
    try:
        response = requests.post(
            'https://graphql.bitquery.io/',
            headers=headers,
            json=payload,
            timeout=15
        )
        
        print(f"Simple query status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            if 'errors' in data:
                print(f"❌ Simple query errors: {data['errors']}")
            else:
                print(f"✅ Simple query works!")
                print(f"📄 Data: {json.dumps(data, indent=2)[:500]}...")
                return data
        else:
            print(f"❌ Simple query failed: {response.text[:200]}")
            
    except Exception as e:
        print(f"❌ Simple query exception: {e}")
    
    return None

def test_pump_fun_specific():
    """Test spécifique pour Pump.fun selon leur documentation"""
    address = "41vZZpGqBQ2dGxS99cmWZuQuC7X97VbcqiAobp29pump"
    
    print(f"\n🎯 Testing Pump.fun specific query")
    
    # Requête adaptée de la doc Bitquery pour Pump.fun
    query = """
    query PumpFunBondingCurve($token: String!) {
      solana {
        dexTrades(
          where: {
            trade: {
              currency: {
                address: {is: $token}
              }
            }
            instruction: {
              program: {
                address: {is: "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"}
              }
            }
          }
          orderBy: {descending: block_time}
          limit: {count: 10}
        ) {
          block {
            timestamp {
              time
            }
          }
          trade {
            currency {
              address
              symbol
            }
            amount
            amountInUSD
          }
          instruction {
            accounts {
              address
            }
          }
        }
      }
    }
    """
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ory_at_hbkaZAsdEyEXAVclDT25nAxheu8tB01Zy904O1qLNXE.FNfybgiQ9b5ZEngYmcOnRPuqDfQ_wITc4En9HYfys4M',  # Remplacez par votre vraie clé
    }
    
    payload = {
        'query': query,
        'variables': {'token': address}
    }
    
    try:
        response = requests.post(
            'https://graphql.bitquery.io/',
            headers=headers,
            json=payload,
            timeout=20
        )
        
        print(f"Pump.fun query status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            
            if 'errors' in data:
                print(f"❌ Pump.fun query errors: {data['errors']}")
            else:
                print(f"✅ Pump.fun query success!")
                print(f"📄 Data: {json.dumps(data, indent=2)[:800]}...")
                
                # Analyser les comptes pour trouver la bonding curve
                if 'data' in data and 'solana' in data['data']:
                    trades = data['data']['solana']['dexTrades']
                    
                    print(f"\n📊 Found {len(trades)} trades")
                    
                    # Extraire les adresses de comptes
                    all_accounts = set()
                    for trade in trades:
                        if 'instruction' in trade and 'accounts' in trade['instruction']:
                            for account in trade['instruction']['accounts']:
                                all_accounts.add(account['address'])
                    
                    print(f"📋 Found {len(all_accounts)} unique accounts")
                    for account in list(all_accounts)[:5]:
                        print(f"   Account: {account}")
                
                return data
        else:
            print(f"❌ Pump.fun query failed: {response.text[:200]}")
            
    except Exception as e:
        print(f"❌ Pump.fun query exception: {e}")
    
    return None

def analyze_balance_updates(balance_updates, token_address):
    """Analyser les balance updates pour calculer la progression"""
    print(f"\n📊 Analyzing {len(balance_updates)} balance updates")
    
    max_balance = 0
    bonding_curve_balance = 0
    
    for update in balance_updates:
        if 'balanceUpdate' in update:
            balance_update = update['balanceUpdate']
            post_balance = float(balance_update.get('postBalance', 0) or 0)
            account = balance_update.get('account', {}).get('address', '')
            
            print(f"   Account: {account[:20]}... Balance: {post_balance:,.0f}")
            
            if post_balance > max_balance:
                max_balance = post_balance
                bonding_curve_balance = post_balance
    
    if bonding_curve_balance > 100_000_000:  # Plus de 100M tokens
        # Calculer avec la formule Pump.fun
        total_supply = 1_000_000_000  # 1B tokens
        reserved_tokens = 206_900_000  # 206.9M réservés
        initial_tokens = total_supply - reserved_tokens  # 793.1M
        
        progress = 100 - ((bonding_curve_balance * 100) / initial_tokens)
        progress = max(0, min(progress, 99.9))
        
        print(f"\n🎯 CALCULATED RESULTS:")
        print(f"   Tokens remaining: {bonding_curve_balance:,.0f}")
        print(f"   Initial tokens: {initial_tokens:,.0f}")
        print(f"   Progress: {progress:.1f}%")
        print(f"   DexScreener shows: 4.4%")
        print(f"   Difference: {abs(progress - 4.4):.1f}%")
        
        return {
            'progress': progress,
            'tokens_remaining': bonding_curve_balance,
            'success': True
        }
    else:
        print(f"❌ No bonding curve balance found (max: {max_balance:,.0f})")
        return {'success': False}

if __name__ == "__main__":
    print("🚀 Testing Bitquery v2 API (Corrected)")
    print("=" * 60)
    
    # Test 1: Requête principale
    result1 = test_bitquery_v2()
    
    print("\n" + "=" * 60)
    
    # Test 2: Requête Pump.fun spécifique
    result2 = test_pump_fun_specific()
    
    print("\n" + "=" * 60)
    print("📊 FINAL RESULTS")
    print("=" * 60)
    
    if result1 and result1.get('success'):
        print(f"✅ Method 1 Success: {result1['progress']:.1f}%")
    else:
        print("❌ Method 1 Failed")
    
    if result2:
        print("✅ Method 2 got data (check above for details)")
    else:
        print("❌ Method 2 Failed")