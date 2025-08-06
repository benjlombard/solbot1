#!/usr/bin/env python3
"""
Script de démarrage optimisé pour le moniteur Solana
Avec diagnostics avancés et gestion intelligente des comptes de tokens
"""

import os
import sys
import logging
import threading
import time
import sqlite3
from datetime import datetime
from dotenv import load_dotenv

def setup_environment():
    """Configure l'environnement et les variables"""
    if os.path.exists('.env'):
        load_dotenv('.env')
        print("✅ Fichier .env chargé")
    else:
        print("ℹ️ Aucun fichier .env trouvé, utilisation des variables par défaut")
    
    # Vérifier les dépendances
    try:
        import requests
        import flask
        import flask_cors
        print("✅ Toutes les dépendances sont installées")
    except ImportError as e:
        print(f"❌ Dépendance manquante: {e}")
        print("💡 Exécutez: pip install -r requirements.txt")
        sys.exit(1)

def check_configuration():
    """Vérifie la configuration avec diagnostics avancés"""
    try:
        from config import DefaultConfig as Config
        
        errors = []
        warnings = []
        
        # Vérification des wallets
        if not hasattr(Config, 'WALLET_ADDRESSES') or not Config.WALLET_ADDRESSES:
            errors.append("WALLET_ADDRESSES invalide ou vide")
        else:
            for i, wallet in enumerate(Config.WALLET_ADDRESSES):
                if not wallet or len(wallet) < 40:
                    errors.append(f"Wallet #{i+1} invalide: {wallet}")
        
        # Vérification des paramètres de performance
        if Config.UPDATE_INTERVAL < 30:
            warnings.append("UPDATE_INTERVAL très faible - risque de rate limiting")
        
        if Config.RATE_LIMIT_DELAY < 0.1:
            warnings.append("RATE_LIMIT_DELAY très faible - risque de rate limiting")
            
        if Config.TOKEN_DISCOVERY_BATCH_SIZE > 100:
            warnings.append("TOKEN_DISCOVERY_BATCH_SIZE élevé - peut ralentir les scans")
        
        # Vérifier les endpoints RPC
        try:
            endpoints = Config.get_rpc_endpoints()
            if not endpoints:
                errors.append("Aucun endpoint RPC configuré")
            else:
                print(f"🔗 {len(endpoints)} endpoint(s) RPC configuré(s)")
        except Exception as e:
            errors.append(f"Erreur dans get_rpc_endpoints: {e}")
        
        if errors:
            raise ValueError(f"Erreurs critiques: {'; '.join(errors)}")
        
        if warnings:
            print("⚠️ Avertissements de configuration:")
            for warning in warnings:
                print(f"   - {warning}")
        
        print("✅ Configuration validée")
        
        # Afficher les paramètres principaux
        print(f"\n📍 Configuration actuelle:")
        print(f"   💼 Wallets: {len(Config.WALLET_ADDRESSES)} wallet(s)")
        for i, wallet in enumerate(Config.WALLET_ADDRESSES):
            print(f"      {i+1}. {wallet[:8]}...{wallet[-8:]}")
        print(f"   🔑 QuickNode: {'✅ Configuré' if hasattr(Config, 'QUICKNODE_ENDPOINT') and Config.QUICKNODE_ENDPOINT else '❌ Non configuré'}")
        print(f"   ⏱️ Intervalle: {Config.UPDATE_INTERVAL}s")
        print(f"   🚦 Rate limit: {Config.RATE_LIMIT_DELAY}s entre requêtes")
        print(f"   📊 Scan complet: toutes les {Config.FULL_SCAN_INTERVAL_HOURS}h")
        print(f"   🎯 Limite transactions: {Config.DEFAULT_TRANSACTION_LIMIT}")
        print(f"   📦 Batch size: {Config.TOKEN_DISCOVERY_BATCH_SIZE}")
        
        print(f"   🎯 Mode de sélection: {Config.WALLET_SELECTION_MODE.upper()}")
        if Config.WALLET_SELECTION_MODE == "random":
            weight_desc = "pondéré" if Config.RANDOM_SELECTION_WEIGHT_BY_PRIORITY else "équiprobable"
            print(f"   🎲 Sélection aléatoire {weight_desc}")
            print(f"   ⏱️ Intervalle minimum: {Config.MIN_INTERVAL_BETWEEN_SCANS}s")
        else:
            print(f"   🏆 Sélection par priorités dynamiques")

        return Config
        
    except Exception as e:
        print(f"❌ Erreur de configuration: {e}")
        sys.exit(1)

def test_database_connection(db_name: str):
    """Teste et affiche les informations de la base de données"""
    try:
        print("🗄️ Test de connexion à la base de données...")
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        
        # Vérifier les tables principales
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        
        print(f"✅ Base de données connectée: {db_name}")
        print(f"📊 Tables trouvées: {len(tables)}")
        
        # Statistiques par table
        stats = {}
        for table in ['transactions', 'token_accounts', 'scan_history']:
            if table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                stats[table] = count
                print(f"   - {table}: {count:,} enregistrements")
        
        # Statistiques des wallets en DB
        if 'token_accounts' in tables:
            cursor.execute("SELECT wallet_address, COUNT(*) FROM token_accounts GROUP BY wallet_address")
            wallet_stats = cursor.fetchall()
            if wallet_stats:
                print(f"💼 Comptes de tokens par wallet:")
                for wallet, count in wallet_stats:
                    print(f"   - {wallet[:8]}...{wallet[-8:]}: {count:,} comptes")
        
        # Dernières activités
        if 'transactions' in tables and stats.get('transactions', 0) > 0:
            cursor.execute("""
                SELECT token_symbol, transaction_type, block_time 
                FROM transactions 
                WHERE is_token_transaction = 1 
                ORDER BY block_time DESC 
                LIMIT 3
            """)
            recent_txs = cursor.fetchall()
            if recent_txs:
                print(f"📈 Dernières transactions token:")
                for symbol, tx_type, block_time in recent_txs:
                    if block_time:
                        age = int(time.time()) - block_time
                        age_str = f"{age//3600}h{(age%3600)//60}m" if age < 86400 else f"{age//86400}j"
                        print(f"   - {symbol}: {tx_type} (il y a {age_str})")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Erreur base de données: {e}")
        return False

def test_quicknode_connection():
    """Teste la connexion QuickNode avec diagnostics détaillés"""
    try:
        from config import DefaultConfig as Config
        import requests
        
        endpoints = Config.get_rpc_endpoints()
        print(f"🧪 Test de connexion RPC sur {len(endpoints)} endpoint(s)...")
        
        for i, endpoint in enumerate(endpoints):
            print(f"   🔗 Test endpoint #{i+1}: {endpoint[:50]}...")
            
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getHealth",
                "params": []
            }
            
            try:
                headers = Config.get_rpc_headers()
                start_time = time.time()
                response = requests.post(endpoint, json=payload, headers=headers, timeout=10)
                response_time = (time.time() - start_time) * 1000
                
                if response.status_code == 200:
                    print(f"   ✅ Endpoint #{i+1} OK ({response_time:.0f}ms)")
                    if i == 0:  # Premier endpoint (principal)
                        print(f"   🎯 Endpoint principal fonctionnel")
                        return True
                else:
                    print(f"   ⚠️ Endpoint #{i+1} erreur {response.status_code}")
                    
            except requests.exceptions.Timeout:
                print(f"   ⏰ Endpoint #{i+1} timeout")
            except Exception as e:
                print(f"   ❌ Endpoint #{i+1} erreur: {e}")
        
        print("⚠️ Aucun endpoint principal disponible, utilisation des fallbacks")
        return False
        
    except Exception as e:
        print(f"❌ Erreur test connexion RPC: {e}")
        return False

def test_wallet_data_fetch():
    """Teste la récupération de données pour un wallet"""
    try:
        from config import DefaultConfig as Config
        from scanner_wallet import SolanaWalletMonitor
        
        if not Config.WALLET_ADDRESSES:
            print("❌ Aucun wallet configuré pour le test")
            return False
        
        test_wallet = Config.WALLET_ADDRESSES[0]
        print(f"🧪 Test de récupération de données pour {test_wallet[:8]}...")
        
        monitor = SolanaWalletMonitor([test_wallet], Config.DB_NAME)
        
        # Test 1: Récupération du solde
        print("   📊 Test du solde SOL...")
        balance = monitor.get_wallet_balance_for_address(test_wallet)
        if balance >= 0:
            print(f"   ✅ Solde récupéré: {balance:.4f} SOL")
        else:
            print("   ⚠️ Solde non récupéré")
        
        # Test 2: Découverte des comptes de tokens (limité)
        print("   🔍 Test de découverte des comptes de tokens...")
        total_accounts, new_accounts = monitor.discover_token_accounts(test_wallet, force_full_scan=False)
        
        if total_accounts > 0:
            print(f"   ✅ Découverte réussie: {total_accounts} comptes ({new_accounts} nouveaux)")
            
            # Test 3: Récupération des comptes prioritaires
            print("   🎯 Test des comptes prioritaires...")
            priority_accounts = monitor.get_priority_accounts_for_scanning(test_wallet, limit=5)
            print(f"   ✅ {len(priority_accounts)} comptes prioritaires identifiés")
            
            return True
        else:
            print("   ⚠️ Aucun compte de token trouvé")
            return False
            
    except Exception as e:
        print(f"   ❌ Erreur test wallet: {e}")
        return False

def show_startup_summary(Config):
    """Affiche un résumé du démarrage"""
    print("\n" + "=" * 70)
    print("🚀 RÉSUMÉ DU DÉMARRAGE - MONITEUR SOLANA OPTIMISÉ")
    print("=" * 70)
    print(f"📅 Démarrage: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🔧 Version: 2.0 - Approche Balance Changes Intelligente")
    print(f"💼 Wallets surveillés: {len(Config.WALLET_ADDRESSES)}")
    print(f"⏱️ Cycle de monitoring: {Config.UPDATE_INTERVAL}s")
    print(f"🔄 Scan complet automatique: {Config.FULL_SCAN_INTERVAL_HOURS}h")
    print(f"🚦 Rate limiting: {Config.RATE_LIMIT_DELAY}s entre requêtes")
    print(f"🌐 Interface web: http://{Config.FLASK_HOST}:{Config.FLASK_PORT}")
    print("=" * 70)
    print("🎯 STRATÉGIE OPTIMISÉE:")
    print("   1️⃣ Découverte intelligente des comptes de tokens")
    print("   2️⃣ Priorisation des comptes nouveaux/récents")
    print("   3️⃣ Scan ciblé des balance changes")
    print("   4️⃣ Cache persistant en base de données")
    print("   5️⃣ Respect strict du rate limiting")
    print("=" * 70)
    print("📊 LOGS:")
    print("   📝 Fichier: wallet_monitor.log")
    print("   🖥️ Console: logs en temps réel")
    print("   📈 Progression détaillée des scans")
    print("=" * 70)
    print("⚡ OPTIMISATIONS:")
    print("   ✅ Évite les scans redondants")
    print("   ✅ Gestion intelligente des priorités")
    print("   ✅ Cache des métadonnées tokens")
    print("   ✅ Fallbacks automatiques RPC")
    print("   ✅ Historique détaillé des scans")
    print("=" * 70)
    
def run_monitor():
    """Lance le moniteur de wallets"""
    try:
        from scanner_wallet import SolanaWalletMonitor, WALLET_ADDRESSES, DB_NAME
        
        print("🔍 Initialisation du moniteur optimisé...")
        monitor = SolanaWalletMonitor(WALLET_ADDRESSES, DB_NAME)
        
        print("🚀 Démarrage de la boucle de monitoring intelligente...")
        print("💡 Le premier cycle peut être plus long (découverte initiale)")
        print("⏹️ Ctrl+C pour arrêter proprement")
        
        monitor.monitor_loop()
        
    except KeyboardInterrupt:
        print("\n🛑 Arrêt demandé par l'utilisateur")
        print("✅ Moniteur arrêté proprement")
    except Exception as e:
        print(f"❌ Erreur dans le monitoring: {e}")
        import traceback
        traceback.print_exc()

def run_diagnostics():
    """Lance des diagnostics complets avant le démarrage"""
    print("🔬 DIAGNOSTICS PRÉ-DÉMARRAGE")
    print("=" * 50)
    
    # Test 1: Configuration
    print("1️⃣ Vérification de la configuration...")
    Config = check_configuration()
    print("✅ Configuration OK\n")
    
    # Test 2: Base de données
    print("2️⃣ Test de la base de données...")
    db_ok = test_database_connection(Config.DB_NAME)
    if db_ok:
        print("✅ Base de données OK\n")
    else:
        print("⚠️ Problème base de données\n")
    
    # Test 3: Connectivité RPC
    print("3️⃣ Test des endpoints RPC...")
    rpc_ok = test_quicknode_connection()
    if rpc_ok:
        print("✅ RPC principal OK\n")
    else:
        print("⚠️ RPC principal en problème, fallbacks disponibles\n")
    
    # Test 4: Données wallet (optionnel et rapide)
    response = input("4️⃣ Tester la récupération de données wallet? (o/N): ")
    if response.lower() in ['o', 'oui', 'y', 'yes']:
        print("Test des données wallet...")
        wallet_ok = test_wallet_data_fetch()
        if wallet_ok:
            print("✅ Données wallet OK\n")
        else:
            print("⚠️ Problème données wallet\n")
    
    print("🔬 DIAGNOSTICS TERMINÉS")
    print("=" * 50)
    
    return Config

def main():
    """Point d'entrée principal avec diagnostics"""
    print("🚀 DÉMARRAGE DU MONITEUR SOLANA OPTIMISÉ")
    print("=" * 60)
    
    # Configuration de l'environnement
    setup_environment()
    
    # Diagnostics complets
    Config = run_diagnostics()
    
    # Afficher le résumé
    show_startup_summary(Config)
    
    # Confirmation avant démarrage
    print("\n🎯 Prêt à démarrer le monitoring optimisé!")
    response = input("▶️ Démarrer maintenant? (O/n): ")
    if response.lower() in ['n', 'non', 'no']:
        print("🛑 Démarrage annulé par l'utilisateur")
        sys.exit(0)
    
    print("\n🎬 DÉMARRAGE EN COURS...")
    print("=" * 60)
    
    # Importer et démarrer l'application
    try:
        # Importer l'application Flask depuis scanner_wallet
        from scanner_wallet import app
        
        # Démarrer le monitoring en arrière-plan
        monitor_thread = threading.Thread(target=run_monitor, daemon=True)
        monitor_thread.start()
        print("✅ Thread de monitoring démarré en arrière-plan")
        
        # Attendre un peu que le monitoring démarre
        time.sleep(2)
        
        # Configuration Flask
        host = getattr(Config, 'FLASK_HOST', '127.0.0.1')
        port = getattr(Config, 'FLASK_PORT', 5000)
        debug = getattr(Config, 'FLASK_DEBUG', False)  # Debug désactivé en production
        
        print(f"🌐 Démarrage du serveur web sur http://{host}:{port}")
        print("📊 Dashboard accessible dans votre navigateur")
        print("\n💡 CONSEILS D'UTILISATION:")
        print("   - Le premier scan peut prendre plusieurs minutes")
        print("   - Les logs détaillés sont dans wallet_monitor.log")
        print("   - Le monitoring continue en arrière-plan")
        print("   - Ctrl+C pour arrêter proprement")
        print(f"   - {len(Config.WALLET_ADDRESSES)} wallet(s) surveillé(s) intelligemment")
        print("\n📈 PROGRESSION:")
        print("   - Découverte initiale des comptes de tokens en cours...")
        print("   - Les premières transactions apparaîtront sous peu")
        print("   - L'interface se mettra à jour automatiquement")
        print("\n" + "=" * 60)
        
        # Démarrer le serveur Flask (bloquant)
        app.run(host=host, port=port, debug=debug, use_reloader=False)
        
    except KeyboardInterrupt:
        print("\n🛑 Arrêt demandé par l'utilisateur")
        print("✅ Moniteur arrêté proprement")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Erreur lors du démarrage: {e}")
        import traceback
        traceback.print_exc()
        print("💡 Essayez: python scanner_wallet.py")
        sys.exit(1)

if __name__ == "__main__":
    main()