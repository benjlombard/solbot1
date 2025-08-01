#!/usr/bin/env python3
"""
Script de démarrage optimisé pour le moniteur Solana avec Ankr
"""

import os
import sys
import logging
from dotenv import load_dotenv

def setup_environment():
    """Configure l'environnement et les variables"""
    # Charger le fichier .env si présent
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
    """Vérifie la configuration"""
    try:
        from config import DefaultConfig as Config
        
        # Vérification manuelle au lieu d'utiliser validate_config()
        errors = []
        
        if not Config.WALLET_ADDRESS or len(Config.WALLET_ADDRESS) < 40:
            errors.append("WALLET_ADDRESS invalide")
        
        if Config.UPDATE_INTERVAL < 30:
            errors.append("UPDATE_INTERVAL trop faible (minimum 30s recommandé)")
        
        # Vérifier les endpoints RPC
        try:
            endpoints = Config.get_rpc_endpoints()
            if not endpoints:
                errors.append("Aucun endpoint RPC configuré")
        except Exception as e:
            errors.append(f"Erreur dans get_rpc_endpoints: {e}")
        
        if errors:
            raise ValueError(f"Erreurs de configuration: {', '.join(errors)}")
        
        print("✅ Configuration validée")
        
        # Afficher les paramètres principaux
        print(f"📍 Wallet: {Config.WALLET_ADDRESS}")
        print(f"🔑 QuickNode: {'Configuré' if hasattr(Config, 'QUICKNODE_ENDPOINT') and Config.QUICKNODE_ENDPOINT else 'Non configuré'}")
        print(f"⏱️ Intervalle: {Config.UPDATE_INTERVAL}s")
        print(f"🎯 Limite transactions: {Config.DEFAULT_TRANSACTION_LIMIT}")
        
    except Exception as e:
        print(f"❌ Erreur de configuration: {e}")
        sys.exit(1)

def test_quicknode_connection():
    """Teste la connexion Ankr"""
    try:
        from config import DefaultConfig as Config
        import requests
        
        endpoint = Config.get_rpc_endpoints()[0]
        headers = Config.get_rpc_headers()
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getHealth",
            "params": []
        }
        
        print("🧪 Test de connexion QuickNode...")
        response = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        
        if response.status_code == 200:
            print("✅ Connexion QuickNode réussie")
            return True
        else:
            print(f"⚠️ Réponse inattendue de QuickNode: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Erreur de connexion QuickNode: {e}")
        return False

def main():
    """Point d'entrée principal"""
    print("🚀 Démarrage du Moniteur de Wallet Solana avec Ankr")
    print("=" * 55)
    
    # Configuration de l'environnement
    setup_environment()
    
    # Vérification de la configuration
    check_configuration()
    
    # Test de connexion Ankr
    quicknode_ok = test_quicknode_connection()
    
    if not quicknode_ok:
        print("⚠️ Attention: Problème avec QuickNode, utilisation des endpoints de fallback")
        response = input("Continuer quand même? (o/N): ")
        if response.lower() not in ['o', 'oui', 'y', 'yes']:
            sys.exit(1)
    
    print("\n🎯 Démarrage du moniteur...")
    print("=" * 55)
    
    # Importer et démarrer l'application
    try:
        # Importer l'application après la configuration
        from scanner_wallet import app, run_monitor  # Utiliser la version corrigée
        import threading
        
        # Démarrer le monitoring en arrière-plan
        monitor_thread = threading.Thread(target=run_monitor, daemon=True)
        monitor_thread.start()
        print("✅ Thread de monitoring démarré")
        
        # Configuration Flask
        from config import DefaultConfig as Config
        host = getattr(Config, 'FLASK_HOST', '127.0.0.1')
        port = getattr(Config, 'FLASK_PORT', 5000)
        debug = getattr(Config, 'FLASK_DEBUG', True)
        
        print(f"🌐 Serveur web: http://{host}:{port}")
        print("📊 Dashboard accessible dans votre navigateur")
        print("\n💡 Conseils:")
        print("   - Ctrl+C pour arrêter le moniteur")
        print("   - Consultez wallet_monitor.log pour les détails")
        print("   - Le monitoring se fait automatiquement en arrière-plan")
        print("\n" + "=" * 55)
        
        # Démarrer le serveur Flask
        app.run(host=host, port=port, debug=debug)
        
    except KeyboardInterrupt:
        print("\n🛑 Arrêt demandé par l'utilisateur")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Erreur lors du démarrage: {e}")
        print("💡 Essayez: python app.py")
        sys.exit(1)

if __name__ == "__main__":
    main()