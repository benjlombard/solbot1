#!/usr/bin/env python3
"""
Script de diagnostic pour tester l'API Helius et pump.fun
"""

import asyncio
import httpx
import json
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()

HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")
HELIUS_RPC_URL = "https://mainnet.helius-rpc.com"
PUMPFUN_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

async def test_helius_connection():
    """Test de connexion basique à Helius"""
    print("🔗 Test de connexion Helius...")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            url = f"{HELIUS_RPC_URL}/?api-key={HELIUS_API_KEY}"
            
            payload = {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "getHealth"
            }
            
            response = await client.post(url, json=payload)
            print(f"Status: {response.status_code}")
            print(f"Response: {response.json()}")
            
            return response.status_code == 200
            
        except Exception as e:
            print(f"❌ Erreur: {e}")
            return False

async def test_pump_fun_program():
    """Test de récupération des transactions pump.fun"""
    print("\n🎯 Test du programme pump.fun...")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            url = f"{HELIUS_RPC_URL}/?api-key={HELIUS_API_KEY}"
            
            # Test 1: Vérifier que le programme existe
            payload = {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "getAccountInfo",
                "params": [
                    PUMPFUN_PROGRAM_ID,
                    {"encoding": "base64"}
                ]
            }
            
            response = await client.post(url, json=payload)
            print(f"Programme pump.fun existe: {response.status_code == 200}")
            
            if response.status_code == 200:
                result = response.json().get('result')
                if result and result.get('value'):
                    print("✅ Programme pump.fun trouvé")
                else:
                    print("❌ Programme pump.fun non trouvé")
                    return False
            
            # Test 2: Récupérer les signatures récentes
            payload = {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "getSignaturesForAddress",
                "params": [
                    PUMPFUN_PROGRAM_ID,
                    {
                        "limit": 10,
                        "commitment": "confirmed"
                    }
                ]
            }
            
            response = await client.post(url, json=payload)
            print(f"Signatures status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                signatures = data.get('result', [])
                print(f"📊 Nombre de signatures trouvées: {len(signatures)}")
                
                if signatures:
                    print("🔍 Détails des 3 premières signatures:")
                    for i, sig in enumerate(signatures[:3]):
                        print(f"  {i+1}. {sig['signature'][:20]}... - Block time: {sig.get('blockTime', 'N/A')}")
                        
                        # Récupérer les détails d'une transaction
                        if i == 0:  # Seulement la première pour économiser
                            await test_transaction_details(client, sig['signature'])
                else:
                    print("❌ Aucune signature trouvée")
            
            return len(signatures) > 0 if 'signatures' in locals() else False
            
        except Exception as e:
            print(f"❌ Erreur: {e}")
            return False

async def test_transaction_details(client, signature):
    """Test de récupération des détails d'une transaction"""
    print(f"\n🔍 Test transaction: {signature[:20]}...")
    
    try:
        url = f"{HELIUS_RPC_URL}/?api-key={HELIUS_API_KEY}"
        
        payload = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "getTransaction",
            "params": [
                signature,
                {
                    "encoding": "json",
                    "maxSupportedTransactionVersion": 0,
                    "commitment": "confirmed"
                }
            ]
        }
        
        response = await client.post(url, json=payload)
        
        if response.status_code == 200:
            data = response.json()
            result = data.get('result')
            
            if result:
                print("✅ Transaction récupérée")
                
                # Analyser les instructions
                instructions = result.get('transaction', {}).get('message', {}).get('instructions', [])
                print(f"📋 Nombre d'instructions: {len(instructions)}")
                
                # Chercher les instructions pump.fun
                pumpfun_instructions = 0
                for inst in instructions:
                    program_id_index = inst.get('programIdIndex')
                    if program_id_index is not None:
                        accounts = result.get('transaction', {}).get('message', {}).get('accountKeys', [])
                        if program_id_index < len(accounts):
                            program_id = accounts[program_id_index]
                            if program_id == PUMPFUN_PROGRAM_ID:
                                pumpfun_instructions += 1
                
                print(f"🎯 Instructions pump.fun: {pumpfun_instructions}")
                
                # Analyser les transferts de tokens
                meta = result.get('meta', {})
                pre_token_balances = meta.get('preTokenBalances', [])
                post_token_balances = meta.get('postTokenBalances', [])
                
                print(f"💰 Pré-balances tokens: {len(pre_token_balances)}")
                print(f"💰 Post-balances tokens: {len(post_token_balances)}")
                
                return True
            else:
                print("❌ Transaction non trouvée")
                return False
        else:
            print(f"❌ Erreur HTTP: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return False

async def test_alternative_pump_detection():
    """Test de méthodes alternatives pour détecter pump.fun"""
    print("\n🔄 Test méthodes alternatives...")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Méthode 1: Rechercher par token mint connu
            print("1. Test via tokens pump.fun connus...")
            
            # Quelques adresses de tokens pump.fun connus (exemples)
            known_pump_tokens = [
                "So11111111111111111111111111111111111111112",  # SOL wrapper
                # Ajouter d'autres tokens pump.fun connus ici
            ]
            
            # Méthode 2: Rechercher via Enhanced API de Helius
            print("2. Test Enhanced API...")
            
            url = f"{HELIUS_RPC_URL}/?api-key={HELIUS_API_KEY}"
            
            # Essayer l'Enhanced API pour récupérer les transactions récentes
            payload = {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "getRecentBlockhash",
                "params": []
            }
            
            response = await client.post(url, json=payload)
            print(f"Enhanced API status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print(f"Dernier blockhash: {result.get('result', {}).get('value', {}).get('blockhash', 'N/A')[:20]}...")
            
            return True
            
        except Exception as e:
            print(f"❌ Erreur: {e}")
            return False

async def main():
    """Fonction principale de diagnostic"""
    print("🚀 Diagnostic API Helius & Pump.fun")
    print("=" * 50)
    
    # Vérification configuration
    print(f"🔑 API Key: {HELIUS_API_KEY[:10] if HELIUS_API_KEY else 'NON CONFIGURÉE'}...")
    print(f"🎯 Programme pump.fun: {PUMPFUN_PROGRAM_ID}")
    print(f"🌐 URL Helius: {HELIUS_RPC_URL}")
    
    if not HELIUS_API_KEY:
        print("❌ HELIUS_API_KEY non configurée !")
        return
    
    # Tests
    tests = [
        ("Connexion Helius", test_helius_connection),
        ("Programme pump.fun", test_pump_fun_program),
        ("Méthodes alternatives", test_alternative_pump_detection),
    ]
    
    results = {}
    
    for test_name, test_func in tests:
        print(f"\n{'='*20} {test_name} {'='*20}")
        try:
            result = await test_func()
            results[test_name] = result
            print(f"✅ {test_name}: {'SUCCÈS' if result else 'ÉCHEC'}")
        except Exception as e:
            results[test_name] = False
            print(f"❌ {test_name}: ERREUR - {e}")
    
    # Résumé
    print(f"\n{'='*50}")
    print("📊 RÉSUMÉ DES TESTS:")
    for test_name, result in results.items():
        status = "✅ SUCCÈS" if result else "❌ ÉCHEC"
        print(f"  {test_name}: {status}")
    
    # Recommandations
    print(f"\n💡 RECOMMANDATIONS:")
    
    if not results.get("Connexion Helius", False):
        print("  - Vérifiez votre clé API Helius")
        print("  - Vérifiez votre connexion Internet")
    
    if not results.get("Programme pump.fun", False):
        print("  - L'ID du programme pump.fun pourrait avoir changé")
        print("  - Pump.fun pourrait être moins actif en ce moment")
        print("  - Essayez de vérifier sur pump.fun directement")
    
    if all(not r for r in results.values()):
        print("  - Problème majeur avec l'API ou la configuration")
        print("  - Contactez le support Helius si nécessaire")
    
    print(f"\n🕒 Test terminé: {datetime.now().isoformat()}")

if __name__ == "__main__":
    asyncio.run(main())