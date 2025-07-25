#!/usr/bin/env python3
"""
🚀 Launch Script - Démarre le scanner et l'API dashboard
"""

import asyncio
import threading
import time
import logging
import os
import webbrowser
from pathlib import Path

# Import de vos modules existants
from jup_db_scan_k2_g3_c1 import InvestScanner, main_loop, configure_logging
from flask_api_backend import app

# Configuration par défaut
DEFAULT_DATABASE_PATH = "tokens.db"
DEFAULT_FLASK_HOST = "127.0.0.1"
DEFAULT_FLASK_PORT = 5000

class DashboardLauncher:
    """Classe pour lancer le scanner et l'API dashboard"""
    
    def __init__(self, flask_host=DEFAULT_FLASK_HOST, flask_port=DEFAULT_FLASK_PORT, database_path=DEFAULT_DATABASE_PATH):
        self.scanner = None
        self.flask_thread = None
        self.scanner_task = None
        self.flask_host = flask_host
        self.flask_port = flask_port
        self.database_path = database_path
        
    def start_flask_server(self):
        """Démarrer le serveur Flask dans un thread séparé"""
        def run_flask():
            app.run(
                host=self.flask_host,
                port=self.flask_port,
                debug=False,  # Pas de debug en mode production
                use_reloader=False  # Éviter les conflits avec threading
            )
        
        self.flask_thread = threading.Thread(target=run_flask, daemon=True)
        self.flask_thread.start()
        logging.info(f"🌐 Flask server started on http://{self.flask_host}:{self.flask_port}")
    
    async def start_scanner(self, args):
        """Démarrer le scanner token"""
        self.scanner = InvestScanner(
            database_path=self.database_path,
            enable_early=args.early,
            enable_social=args.social,
            enable_holders=args.holders_growth
        )
        
        logging.info("🔍 Starting token scanner...")
        await main_loop(self.scanner, args)
    
    def open_dashboard(self):
        """Ouvrir le dashboard dans le navigateur"""
        dashboard_url = f"http://{self.flask_host}:{self.flask_port}/dashboard"
        logging.info(f"🌐 Opening dashboard: {dashboard_url}")
        try:
            webbrowser.open(dashboard_url)
        except Exception as e:
            logging.warning(f"Could not open browser automatically: {e}")
            logging.info(f"Please open {dashboard_url} manually in your browser")
    
    async def run(self, args):
        """Fonction principale pour lancer tout"""
        logging.info("🚀 Starting Solana Token Dashboard...")
        
        # Vérifier que la base de données existe ou peut être créée
        try:
            if not os.path.exists(self.database_path):
                logging.info(f"📁 Creating database: {self.database_path}")
            
            # Créer le scanner pour initialiser la DB
            scanner = InvestScanner(database_path=self.database_path)
            logging.info("✅ Database initialized successfully")
            
        except Exception as e:
            logging.error(f"❌ Failed to initialize database: {e}")
            return
        
        # Démarrer le serveur Flask
        self.start_flask_server()
        
        # Attendre que Flask démarre
        time.sleep(2)
        
        # Ouvrir le dashboard (optionnel)
        if not args.no_browser:
            self.open_dashboard()
        
        # Démarrer le scanner en continu
        try:
            await self.start_scanner(args)
        except KeyboardInterrupt:
            logging.info("\n✅ Dashboard stopped by user")
        except Exception as e:
            logging.error(f"❌ Error running scanner: {e}")

def create_dashboard_html():
    """Créer le fichier HTML du dashboard dans le dossier templates"""
    templates_dir = Path("templates")
    templates_dir.mkdir(exist_ok=True)  # Créer le dossier templates s'il n'existe pas
    
    dashboard_path = templates_dir / "dashboard.html"
    
def main():
    """Point d'entrée principal"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Solana Token Dashboard Launcher")
    
    # Arguments du scanner existant
    parser.add_argument("--limit", type=int, default=10, help="Nombre de tokens à scanner")
    parser.add_argument("--interval", type=float, default=10, help="Intervalle de scan en minutes")
    parser.add_argument("--database", default=DEFAULT_DATABASE_PATH, help="Chemin de la base de données")
    parser.add_argument("--update-interval", type=float, default=5.0, help="Intervalle de mise à jour en minutes")
    parser.add_argument("--early", action="store_true", help="Activer la détection précoce")
    parser.add_argument("--social", action="store_true", help="Activer les signaux sociaux")
    parser.add_argument("--holders-growth", action="store_true", help="Activer le monitoring des holders")
    
    # Arguments spécifiques au dashboard
    parser.add_argument("--no-browser", action="store_true", help="Ne pas ouvrir le navigateur automatiquement")
    parser.add_argument("--flask-port", type=int, default=DEFAULT_FLASK_PORT, help="Port du serveur Flask")
    parser.add_argument("--flask-host", default=DEFAULT_FLASK_HOST, help="Host du serveur Flask")
    
    # Arguments de logging
    parser.add_argument("--log-level", 
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        default='INFO',
                        help="Niveau de logging")
    
    args = parser.parse_args()
    
    # Configuration du logging
    configure_logging(args.log_level)
    
    # Créer le fichier dashboard si nécessaire
    create_dashboard_html()
    
    # Lancer le dashboard avec les paramètres spécifiés
    launcher = DashboardLauncher(
        flask_host=args.flask_host,
        flask_port=args.flask_port,
        database_path=args.database
    )
    
    try:
        asyncio.run(launcher.run(args))
    except KeyboardInterrupt:
        logging.info("\n✅ Dashboard launcher stopped by user")
    except Exception as e:
        logging.error(f"❌ Fatal error: {e}")

if __name__ == "__main__":
    main()