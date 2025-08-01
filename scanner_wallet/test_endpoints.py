#!/usr/bin/env python3
"""
Script de diagnostic pour tester les endpoints RPC Solana
Utilise ce script pour identifier le meilleur endpoint à utiliser
"""

import requests
import time
import json
from typing import List, Dict, Tuple
from config import Config

def test_rpc_endpoint(endpoint: str, timeout: int = 10) -> Tuple[bool, float, str]:
    """
    Teste un endpoint RPC Solana
    Retourne: (succès, temps_réponse, message)
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getHealth",
        "params": []
    }
    
    headers = Config.get_rpc_headers()
    
    try:
        start_time = time.time()
        response = requests.post(endpoint, json=payload, timeout=timeout, headers=headers)
        response_time = time.time() - start_time
        
        if response.status_code == 200:
            result = response.json()
            if "result" in result:
                return True, response_time, "OK"
            else:
                return False, response_time, f"Réponse invalide: {result}"
        else:
            return False, response_time, f"HTTP {response.status_code}: {response.text[:100]}"
            
    except requests.exceptions.Timeout:
        return False, timeout, "Timeout"
    except requests.exceptions.ConnectionError:
        return False, 0, "Erreur de connexion"
    except Exception as e:
        return False, 0, f"Erreur: {str(e)}"

def test_wallet_query(endpoint: str, wallet_address: str) -> Tuple[bool, float, str]:
    """
    Teste une requête spécifique au wallet
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [wallet_address]
    }
    
    headers = Config.get_rpc_headers()
    
    try:
        start_time = time.time()
        response = requests.post(endpoint, json=payload, timeout=15, headers=headers)
        response_time = time.time() - start_time
        
        if response.status_code == 200:
            result = response.json()
            if "result" in result and "value" in result["result"]:
                balance_sol = result["result"]["value"] / 1e9
                return True, response_time, f"Balance: {balance_sol:.4f} SOL"
            else:
                return False, response_time, f"Réponse invalide: {result}"
        elif response.status_code == 429:
            return False, response_time, "Rate limit atteint (429)"
        else:
            return False, response_time, f"HTTP {response.status_code}"
            
    except Exception as e:
        return False, 0, f"Erreur: {str(e)}"

def main():
    print("🧪 Test des endpoints RPC Solana")
    print("=" * 50)
    
    wallet_address = Config.WALLET_ADDRESS
    endpoints = Config.RPC_ENDPOINTS
    
    print(f"Wallet testé: {wallet_address}")
    print(f"Nombre d'endpoints: {len(endpoints)}")
    print()
    
    results = []
    
    for i, endpoint in enumerate(endpoints, 1):
        print(f"🔍 Test {i}/{len(endpoints)}: {endpoint}")
        
        # Test de santé de base
        success_health, time_health, msg_health = test_rpc_endpoint(endpoint)
        print(f"   Santé: {'✅' if success_health else '❌'} ({time_health:.2f}s) - {msg_health}")
        
        if success_health:
            # Test de requête wallet
            success_wallet, time_wallet, msg_wallet = test_wallet_query(endpoint, wallet_address)
            print(f"   Wallet: {'✅' if success_wallet else '❌'} ({time_wallet:.2f}s) - {msg_wallet}")
            
            # Score global
            score = 0
            if success_health and success_wallet:
                score = 100 - (time_health + time_wallet) * 10  # Pénaliser la latence
                score = max(0, score)
            
            results.append({
                'endpoint': endpoint,
                'health_ok': success_health,
                'wallet_ok': success_wallet,
                'avg_time': (time_health + time_wallet) / 2,
                'score': score
            })
        else:
            results.append({
                'endpoint': endpoint,
                'health_ok': False,
                'wallet_ok': False,
                'avg_time': time_health,
                'score': 0
            })
        
        print()
        time.sleep(1)  # Pause entre les tests
    
    # Tri des résultats par score
    results.sort(key=lambda x: x['score'], reverse=True)
    
    print("📊 Résultats classés par performance:")
    print("=" * 50)
    
    for i, result in enumerate(results, 1):
        status = "🟢" if result['health_ok'] and result['wallet_ok'] else "🔴"
        print(f"{i}. {status} {result['endpoint']}")
        print(f"   Score: {result['score']:.1f}/100")
        print(f"   Temps moyen: {result['avg_time']:.2f}s")
        print(f"   Santé: {'OK' if result['health_ok'] else 'KO'} | "
              f"Wallet: {'OK' if result['wallet_ok'] else 'KO'}")
        print()
    
    # Recommandations
    print("💡 Recommandations:")
    print("=" * 50)
    
    working_endpoints = [r for r in results if r['health_ok'] and r['wallet_ok']]
    
    if working_endpoints:
        best = working_endpoints[0]
        print(f"✅ Meilleur endpoint: {best['endpoint']}")
        print(f"   Utilise ce endpoint comme premier choix dans RPC_ENDPOINTS")
        print()
        
        if len(working_endpoints) > 1:
            print("📝 Configuration recommandée pour config.py:")
            print("RPC_ENDPOINTS = [")
            for endpoint_info in working_endpoints[:4]:  # Top 4
                print(f'    "{endpoint_info["endpoint"]}",')
            print("]")
        else:
            print("⚠️  Un seul endpoint fonctionne. Considérez utiliser un service RPC premium.")
    else:
        print("❌ Aucun endpoint ne fonctionne correctement!")
        print("   Vérifiez votre connexion internet ou utilisez un endpoint RPC premium.")
    
    print()
    print("🔧 Pour résoudre les problèmes de rate limiting:")
    print("1. Augmentez UPDATE_INTERVAL dans config.py (recommandé: 90-120s)")
    print("2. Utilisez un endpoint RPC premium (Alchemy, QuickNode, etc.)")
    print("3. Réduisez DEFAULT_TRANSACTION_LIMIT")
    print("4. Ajoutez plus de pauses entre les requêtes")

if __name__ == "__main__":
    main()