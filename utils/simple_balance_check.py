#!/usr/bin/env python3
"""
Vérification simple de balance Solana
File: utils/simple_balance_check.py

Script simple qui ne dépend que de requests pour vérifier la balance
"""

import requests
import json
import os

def check_balance_simple():
    """Vérification simple de balance sans dépendances complexes"""
    
    print("💰 VÉRIFICATION SIMPLE DE BALANCE")
    print("=" * 50)
    
    # Adresse du wallet à vérifier
    wallet_address = "7fkAZYsjbkMoTySXqvuerXgwXvqDq9ZGPuB2q6cEtVgs"
    
    # Différents endpoints RPC à tester
    rpc_endpoints = [
        "https://api.mainnet-beta.solana.com",
        "https://solana-api.projectserum.com",
        "https://rpc.ankr.com/solana"
    ]
    
    print(f"📍 Wallet à vérifier: {wallet_address}")
    print()
    
    for i, rpc_url in enumerate(rpc_endpoints, 1):
        print(f"🔗 Test RPC {i}: {rpc_url}")
        
        try:
            # Payload pour la requête RPC
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBalance",
                "params": [wallet_address]
            }
            
            # Faire la requête
            response = requests.post(
                rpc_url, 
                json=payload, 
                timeout=10,
                headers={'Content-Type': 'application/json'}
            )
            
            # Vérifier la réponse
            if response.status_code == 200:
                data = response.json()
                
                if 'result' in data and 'value' in data['result']:
                    balance_lamports = data['result']['value']
                    balance_sol = balance_lamports / 1_000_000_000  # 1 SOL = 1e9 lamports
                    
                    print(f"   ✅ Réponse reçue")
                    print(f"   💰 Balance: {balance_sol:.9f} SOL")
                    print(f"   📊 Lamports: {balance_lamports:,}")
                    
                    # Estimation en USD (cours approximatif SOL ≈ $140)
                    usd_estimate = balance_sol * 140
                    print(f"   💵 Valeur estimée: ${usd_estimate:.2f}")
                    
                    if balance_sol > 0:
                        print(f"   🎉 SUCCESS: Le wallet contient {balance_sol:.6f} SOL!")
                        return balance_sol
                    else:
                        print(f"   ⚠️ Le wallet semble vide")
                        
                elif 'error' in data:
                    print(f"   ❌ Erreur RPC: {data['error']}")
                else:
                    print(f"   ❌ Réponse inattendue: {data}")
                    
            else:
                print(f"   ❌ HTTP Error: {response.status_code}")
                print(f"   📝 Response: {response.text[:200]}")
                
        except requests.exceptions.Timeout:
            print(f"   ⏰ Timeout après 10 secondes")
        except requests.exceptions.ConnectionError:
            print(f"   🔌 Erreur de connexion")
        except Exception as e:
            print(f"   ❌ Erreur: {e}")
        
        print()  # Ligne vide
    
    return 0

def check_multiple_wallets():
    """Vérifier plusieurs wallets pour comparaison"""
    
    print("🔍 VÉRIFICATION DE PLUSIEURS WALLETS")
    print("=" * 50)
    
    # Wallets à tester
    wallets = {
        "Votre wallet": "7fkAZYsjbkMoTySXqvuerXgwXvqDq9ZGPuB2q6cEtVgs",
        "Wallet SOL (référence)": "So11111111111111111111111111111111111111112",
        "Wallet USDC (référence)": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    }
    
    rpc_url = "https://api.mainnet-beta.solana.com"
    
    for name, address in wallets.items():
        print(f"📍 {name}: {address}")
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [address]
        }
        
        try:
            response = requests.post(rpc_url, json=payload, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if 'result' in data:
                    balance_lamports = data['result']['value']
                    balance_sol = balance_lamports / 1e9
                    print(f"   💰 {balance_sol:.9f} SOL")
                else:
                    print(f"   ❌ Erreur: {data}")
            else:
                print(f"   ❌ HTTP {response.status_code}")
                
        except Exception as e:
            print(f"   ❌ Erreur: {e}")
        
        print()

def test_rpc_connection():
    """Tester la connexion RPC de base"""
    
    print("🔗 TEST DE CONNEXION RPC")
    print("=" * 30)
    
    rpc_url = "https://api.mainnet-beta.solana.com"
    
    # Test 1: getHealth
    print("1. Test getHealth...")
    try:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "getHealth"}
        response = requests.post(rpc_url, json=payload, timeout=5)
        
        if response.status_code == 200:
            print("   ✅ RPC répond correctement")
        else:
            print(f"   ❌ HTTP {response.status_code}")
    except Exception as e:
        print(f"   ❌ Erreur: {e}")
    
    # Test 2: getVersion
    print("2. Test getVersion...")
    try:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "getVersion"}
        response = requests.post(rpc_url, json=payload, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            if 'result' in data:
                version = data['result']['solana-core']
                print(f"   ✅ Version Solana: {version}")
            else:
                print(f"   ❌ Pas de version: {data}")
        else:
            print(f"   ❌ HTTP {response.status_code}")
    except Exception as e:
        print(f"   ❌ Erreur: {e}")
    
    print()

if __name__ == "__main__":
    print("🚀 TESTS SIMPLES SOLANA")
    print("=" * 60)
    
    # Test 1: Connexion RPC
    test_rpc_connection()
    
    # Test 2: Balance de votre wallet
    balance = check_balance_simple()
    
    # Test 3: Comparaison avec d'autres wallets
    check_multiple_wallets()
    
    # Résumé
    print("📋 RÉSUMÉ:")
    print("=" * 20)
    if balance > 0:
        print(f"✅ Votre wallet contient {balance:.6f} SOL")
        print("👉 Si le bot affiche 0, c'est un problème de configuration des clés")
    else:
        print("❌ Votre wallet semble vide ou inaccessible")
        print("👉 Vérifiez l'adresse du wallet")
    
    print("\n💡 Pour corriger le problème du bot:")
    print("1. Créez un fichier .env à la racine avec SOLANA_PRIVATE_KEY")
    print("2. Assurez-vous que la clé privée correspond à ce wallet")
    print("3. Relancez le bot avec: python main.py --wallet-info")