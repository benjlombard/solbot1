#!/usr/bin/env python3
"""
Test de diagnostic du wallet Solana
File: utils/test_wallet.py

Script pour diagnostiquer les problèmes de balance et de configuration wallet
"""

import os
import sys
import asyncio
import requests
import json

# Ajouter le répertoire parent au path pour les imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Imports depuis le répertoire parent
from config import get_config
from solana_client import create_solana_client

async def diagnose_wallet():
    """Diagnostic complet du wallet"""
    print("🔍 DIAGNOSTIC DU WALLET")
    print("=" * 50)
    
    # Vérifier le répertoire de travail
    current_dir = os.getcwd()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(script_dir)
    
    print(f"📁 Répertoire courant: {current_dir}")
    print(f"📁 Script dans: {script_dir}")
    print(f"📁 Répertoire parent: {parent_dir}")
    
    # Vérifier la présence du fichier .env
    env_files = ['.env', '../.env', '../../.env']
    env_found = False
    
    for env_file in env_files:
        env_path = os.path.join(current_dir, env_file)
        if os.path.exists(env_path):
            print(f"✅ Fichier .env trouvé: {env_path}")
            env_found = True
            break
        else:
            print(f"❌ .env non trouvé: {env_path}")
    
    if not env_found:
        print("\n🚨 AUCUN FICHIER .env TROUVÉ!")
        print("Créez un fichier .env à la racine du projet avec:")
        return
    
    # Charger les variables d'environnement
    try:
        from dotenv import load_dotenv
        load_dotenv()
        print("✅ Variables d'environnement chargées avec python-dotenv")
    except ImportError:
        print("⚠️ python-dotenv non installé, utilisation des variables système")
    
    # Vérifications de base
    private_key = os.getenv('SOLANA_PRIVATE_KEY', '')
    public_key = os.getenv('SOLANA_PUBLIC_KEY', '')
    
    print(f"\n🔐 CONFIGURATION:")
    print(f"🔑 Private key présente: {'✅' if private_key else '❌'}")
    print(f"📍 Public key configurée: {public_key or 'Non configurée'}")
    
    if private_key:
        # Ne montrer que les premiers et derniers caractères pour la sécurité
        if len(private_key) > 10:
            masked_key = private_key[:5] + "..." + private_key[-5:]
            print(f"🔐 Clé privée (masquée): {masked_key}")
        print(f"📏 Longueur clé privée: {len(private_key)} caractères")
    
    if not private_key:
        print("\n❌ ERREUR: SOLANA_PRIVATE_KEY manquante dans .env")
        return
    
    # Vérification du format de la clé
    print(f"\n🔍 ANALYSE DE LA CLÉ:")
    if private_key.startswith('[') and private_key.endswith(']'):
        print("📋 Format détecté: Array JSON")
        try:
            key_array = json.loads(private_key)
            print(f"✅ Array valide avec {len(key_array)} éléments")
        except:
            print("❌ Array JSON invalide")
    else:
        print("📋 Format détecté: Base58 ou autre")
    
    # Test du client Solana
    print(f"\n🚀 TEST DU CLIENT SOLANA:")
    try:
        # Charger la configuration
        config = get_config()
        print("✅ Configuration chargée")
        
        # Créer le client
        client = create_solana_client(config)
        print(f"✅ Client créé")
        print(f"📍 Adresse wallet: {client.wallet_address}")
        
        # Vérifier si on est en mode READ_ONLY
        if client.wallet_address == "READ_ONLY_MODE":
            print("❌ Client en mode READ_ONLY - problème de clé privée")
            return
        
        # Health check
        print(f"\n🏥 HEALTH CHECK:")
        health = await client.health_check()
        print(f"📊 Statut: {health['status']}")
        print(f"🔌 Connexion RPC: {'✅' if health['rpc_connection'] else '❌'}")
        print(f"⚡ Latence: {health['rpc_latency_ms']:.1f}ms")
        print(f"🔧 Solana disponible: {'✅' if health['solana_available'] else '❌'}")
        print(f"🔧 Solders API: {'✅' if health['solders_api'] else '❌'}")
        
        # Test de balance
        print(f"\n💰 TEST DE BALANCE:")
        if client.public_key:
            try:
                balance = await client.get_balance()
                print(f"💰 Balance SOL: {balance:.9f}")
                
                # Test balance complète
                full_balance = await client.get_balance('ALL')
                print(f"📊 Balance complète:")
                print(f"   SOL: {full_balance.sol_balance:.9f}")
                print(f"   USD estimé: ${full_balance.total_value_usd:.2f}")
                print(f"   Tokens: {len(full_balance.token_balances)}")
                
                if balance > 0:
                    print("✅ Balance récupérée avec succès!")
                else:
                    print("⚠️ Balance est à 0 - vérifiez l'adresse du wallet")
                    
            except Exception as e:
                print(f"❌ Erreur lors de la récupération de balance: {e}")
        else:
            print("❌ Pas de clé publique - mode READ_ONLY")
        
        await client.close()
        
    except Exception as e:
        print(f"❌ Erreur client: {e}")
        import traceback
        traceback.print_exc()

def check_balance_direct():
    """Vérification directe de la balance via RPC"""
    print(f"\n🔗 VÉRIFICATION DIRECTE VIA RPC:")
    
    wallet_address = "7fkAZYsjbkMoTySXqvuerXgwXvqDq9ZGPuB2q6cEtVgs"
    rpc_url = "https://api.mainnet-beta.solana.com"
    
    print(f"📍 Wallet: {wallet_address}")
    print(f"🔗 RPC: {rpc_url}")
    
    # Requête RPC directe
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [wallet_address]
    }
    
    try:
        response = requests.post(rpc_url, json=payload, timeout=10)
        data = response.json()
        
        if 'result' in data:
            balance_lamports = data['result']['value']
            balance_sol = balance_lamports / 1e9
            print(f"💰 Balance directe: {balance_sol:.9f} SOL")
            print(f"📊 Lamports: {balance_lamports:,}")
            
            # Estimation USD (SOL ≈ $140 au cours actuel)
            usd_value = balance_sol * 140
            print(f"💵 Valeur estimée: ${usd_value:.2f}")
            
            if balance_sol > 0:
                print("✅ Le wallet contient bien des SOL!")
            else:
                print("❌ Le wallet est vide selon RPC")
            
            return balance_sol
        else:
            print(f"❌ Erreur RPC: {data}")
            return None
            
    except Exception as e:
        print(f"❌ Erreur requête: {e}")
        return None

def check_environment_setup():
    """Vérifier la configuration de l'environnement"""
    print(f"\n🔧 VÉRIFICATION ENVIRONNEMENT:")
    
    # Python version
    print(f"🐍 Python: {sys.version.split()[0]}")
    
    # Modules importés
    modules_to_check = [
        'solana', 'solders', 'requests', 'base58', 'asyncio'
    ]
    
    for module in modules_to_check:
        try:
            __import__(module)
            print(f"✅ {module}: Disponible")
        except ImportError:
            print(f"❌ {module}: Non disponible")
    
    # Variables d'environnement importantes
    important_vars = [
        'SOLANA_PRIVATE_KEY', 'SOLANA_PUBLIC_KEY', 'ENVIRONMENT'
    ]
    
    for var in important_vars:
        value = os.getenv(var, '')
        if value:
            if 'KEY' in var and len(value) > 10:
                # Masquer les clés
                masked = value[:5] + "..." + value[-5:]
                print(f"🔐 {var}: {masked}")
            else:
                print(f"✅ {var}: {value}")
        else:
            print(f"❌ {var}: Non définie")

async def full_diagnosis():
    """Diagnostic complet"""
    print("🚀 DIAGNOSTIC COMPLET DU WALLET SOLANA")
    print("=" * 60)
    
    # 1. Vérification environnement
    check_environment_setup()
    
    # 2. Vérification balance directe
    direct_balance = check_balance_direct()
    
    # 3. Diagnostic du client
    await diagnose_wallet()
    
    # 4. Résumé
    print(f"\n📋 RÉSUMÉ:")
    print("=" * 30)
    
    if direct_balance and direct_balance > 0:
        print("✅ Le wallet contient des SOL selon RPC")
        print("👉 Si le client affiche 0, c'est un problème de configuration")
    else:
        print("❌ Le wallet semble vide selon RPC")
        print("👉 Vérifiez l'adresse du wallet")
    
    print(f"\n💡 PROCHAINES ÉTAPES:")
    print("1. Assurez-vous que le fichier .env est à la racine du projet")
    print("2. Vérifiez que priv cle correspond bien au wallet")
    print("3. Testez avec: python main.py --wallet-info")

if __name__ == "__main__":
    # Permettre l'exécution depuis n'importe quel répertoire
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    print(f"🔧 Changement vers le répertoire: {os.getcwd()}")
    
    asyncio.run(full_diagnosis())