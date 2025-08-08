#!/usr/bin/env python3
"""
Démarrage manuel du scanner principal
"""

import sys
import os
from pathlib import Path
import time
import logging

# Ajouter le path du projet
sys.path.insert(0, str(Path(__file__).parent))

def start_scanner_process():
    """Démarrer le processus de scan principal"""
    
    try:
        from core.config import get_config
        from wallet.monitor import SolanaWalletMonitor
        
        print("🚀 Démarrage du scanner principal...")
        
        # Configuration
        config = get_config()
        
        if not config.scanner.enabled:
            print("⚠️ Scanner désactivé dans la configuration")
            print("💡 Activez-le dans config.toml : [scanner] enabled = true")
            return
        
        print(f"✅ Configuration: {config.environment.value}")
        print(f"📊 Intervalle de scan: {config.scanner.scan_interval}s")
        print(f"🎯 Wallets maximum par cycle: {config.scanner.max_wallets_per_cycle}")
        
        # Monitor
        monitor = WalletMonitor()
        
        print("✅ Monitor initialisé")
        print("🔄 Démarrage des scans automatiques...")
        print("   (Ctrl+C pour arrêter)")
        
        # Lancer le monitoring
        try:
            monitor.start()
        except KeyboardInterrupt:
            print("\n🛑 Arrêt demandé par l'utilisateur")
            monitor.stop()
            print("✅ Scanner arrêté proprement")
        
    except ImportError as e:
        print(f"❌ Erreur d'import: {e}")
        print("💡 Vérifiez la structure du projet et les dépendances")
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()

def check_scanner_status():
    """Vérifier l'état du scanner via l'API admin"""
    
    try:
        import requests
        
        # Tester l'API admin
        response = requests.get("http://localhost:5000/api/admin/health", timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            print("✅ API accessible")
            print(f"📊 Statut: {data}")
            
            # Tester le scanner spécifiquement
            scanner_response = requests.get("http://localhost:5000/api/admin/scanner/status", timeout=5)
            
            if scanner_response.status_code == 200:
                scanner_data = scanner_response.json()
                print(f"🔍 Scanner: {scanner_data}")
            else:
                print(f"⚠️ Scanner API: {scanner_response.status_code}")
        else:
            print(f"❌ API non accessible: {response.status_code}")
            
    except requests.exceptions.ConnectionError:
        print("❌ Serveur Flask non démarré")
        print("💡 Lancez d'abord: python api/app.py")
    except Exception as e:
        print(f"❌ Erreur API: {e}")

def force_scan_all_wallets():
    """Forcer un scan de tous les wallets via l'API"""
    
    try:
        import requests
        
        print("🔄 Lancement d'un scan forcé de tous les wallets...")
        
        response = requests.post("http://localhost:5000/api/admin/scanner/scan-all", 
                               timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Scan lancé: {data}")
        else:
            print(f"❌ Erreur scan: {response.status_code}")
            print(response.text)
            
    except Exception as e:
        print(f"❌ Erreur: {e}")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Gestion du scanner")
    parser.add_argument("action", choices=["start", "status", "force-scan"], 
                       help="Action à effectuer")
    
    args = parser.parse_args()
    
    print(f"🛠️ Action: {args.action}")
    print("=" * 40)
    
    if args.action == "start":
        start_scanner_process()
    elif args.action == "status":
        check_scanner_status()
    elif args.action == "force-scan":
        force_scan_all_wallets()