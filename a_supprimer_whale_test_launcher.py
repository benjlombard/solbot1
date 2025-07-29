#!/usr/bin/env python3
"""
WHALE Test Launcher - Script pour tester le système whale complet
Lance le scanner + whale tracking + dashboard en une fois
VERSION WINDOWS COMPATIBLE (sans emojis dans les logs)
"""

import asyncio
import logging
import threading
import time
import webbrowser
import os
from datetime import datetime

# Imports pour le whale tracking
from whale_tracker import WhaleTracker, run_whale_scan
from whale_scheduler import start_whale_monitoring

def setup_logging():
    """Configuration du logging compatible Windows"""
    # Forcer l'encodage UTF-8 pour éviter les erreurs Unicode
    log_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Handler console avec encodage UTF-8
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(log_formatter)
    
    # Handler fichier avec encodage UTF-8 explicite
    file_handler = logging.FileHandler('whale_test.log', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(log_formatter)
    
    # Configuration du logger racine
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    
    # Réduire les logs externes
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)

def start_flask_with_whales():
    """Démarrer Flask avec le whale tracking intégré"""
    def run_flask():
        try:
            # Importer l'app Flask
            from flask_api_backend import app
            
            # Démarrer le whale monitoring avant Flask
            start_whale_monitoring()
            
            # Configurer Flask pour les tests
            app.config['ENV'] = 'development'
            app.config['DEBUG'] = False
            
            # Démarrer le serveur
            app.run(
                host='127.0.0.1',
                port=5000,
                debug=False,
                use_reloader=False,
                threaded=True
            )
        except Exception as e:
            logging.error(f"Error starting Flask with whales: {e}")
    
    # Lancer Flask dans un thread séparé
    flask_thread = threading.Thread(target=run_flask, daemon=True, name="FlaskWhaleServer")
    flask_thread.start()
    
    # Attendre que Flask démarre
    time.sleep(3)
    logging.info("Flask server with whale tracking started on http://127.0.0.1:5000")
    
    return flask_thread

async def test_whale_system():
    """Tester le système whale complet"""
    logging.info("Starting whale system test...")
    
    # 1. Tester le whale tracker de base
    logging.info("Step 1: Testing basic whale tracker...")
    tracker = WhaleTracker()
    
    # 2. Lancer un scan de test sur quelques tokens
    logging.info("Step 2: Running test whale scan...")
    await tracker.scan_all_tokens_for_whales(limit=5)
    
    # 3. Afficher le résumé
    logging.info("Step 3: Getting whale summary...")
    summary = tracker.get_whale_summary()
    
    print("\n" + "="*60)
    print("WHALE SYSTEM TEST RESULTS")
    print("="*60)
    print(f"Total Whales Found: {summary.get('total_whales', 0)}")
    print(f"Known Entities: {summary.get('known_entities', 0)}")
    print(f"Total Whale Value: ${summary.get('total_whale_value_usd', 0):,.2f}")
    print(f"Tokens with Whales: {summary.get('tokens_with_whales', 0)}")
    
    if summary.get('top_whales'):
        print(f"\nTop {len(summary['top_whales'])} Whales:")
        for i, whale in enumerate(summary['top_whales'], 1):
            whale_type = "Known Entity" if whale['is_known'] else "Unknown Whale"
            print(f"  {i}. {whale_type}: {whale['label']} - ${whale['value_usd']:,.2f}")
    
    print("="*60)
    
    return summary

def open_dashboard():
    """Ouvrir le dashboard dans le navigateur"""
    dashboard_url = "http://127.0.0.1:5000/dashboard/detail"
    try:
        webbrowser.open(dashboard_url)
        logging.info(f"Dashboard opened: {dashboard_url}")
    except Exception as e:
        logging.warning(f"Could not open browser: {e}")
        logging.info(f"Please open manually: {dashboard_url}")

async def main():
    """Fonction principale de test"""
    setup_logging()
    
    print("WHALE TRACKING SYSTEM - FULL TEST")
    print("="*50)
    
    try:
        # 1. Démarrer Flask avec whale tracking
        print("Step 1: Starting Flask server with whale tracking...")
        flask_thread = start_flask_with_whales()
        
        # 2. Tester le système whale
        print("Step 2: Testing whale detection system...")
        summary = await test_whale_system()
        
        # 3. Ouvrir le dashboard
        print("Step 3: Opening dashboard...")
        open_dashboard()
        
        # 4. Instructions pour l'utilisateur
        print("\nWHALE SYSTEM READY!")
        print("Dashboard available at: http://127.0.0.1:5000/dashboard/detail")
        print("Whale data will appear in the DexScreener tab")
        print("Check the Analysis tab for whale metrics")
        print("\nTEST INSTRUCTIONS:")
        print("1. Go to the DexScreener tab")
        print("2. Look for the 'Whales' column")
        print("3. Check the Analysis tab for whale summary")
        print("4. Click 'Scanner Whales' to trigger manual scan")
        
        if summary.get('total_whales', 0) > 0:
            print(f"\nFound {summary['total_whales']} whales worth ${summary.get('total_whale_value_usd', 0):,.2f}")
        else:
            print("\nNo whales found yet - try running a manual scan from the dashboard")
        
        print("\nPress Ctrl+C to stop the test")
        
        # 5. Garder le programme en vie
        while True:
            await asyncio.sleep(10)
            
            # Afficher un status toutes les 60 secondes
            if int(time.time()) % 60 == 0:
                logging.info("Whale system running... Dashboard: http://127.0.0.1:5000/dashboard/detail")
    
    except KeyboardInterrupt:
        logging.info("Test stopped by user")
    except Exception as e:
        logging.error(f"Test failed: {e}")
    finally:
        logging.info("Whale test completed")

if __name__ == "__main__":
    # Forcer l'encodage UTF-8 pour Windows
    if os.name == 'nt':  # Windows
        os.environ['PYTHONIOENCODING'] = 'utf-8'
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nWhale test stopped by user")
    except Exception as e:
        print(f"\nFatal error: {e}")
        logging.error(f"Fatal error in whale test: {e}")