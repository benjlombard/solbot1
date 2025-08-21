#!/usr/bin/env python3
"""
Script de démarrage pour le système PumpFun Early Adopters Tracker
Version Polling Intelligent
"""

import os
import sys
import logging
import asyncio
import subprocess
from pathlib import Path

# Charger les variables d'environnement depuis .env
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✅ Variables d'environnement chargées depuis .env")
except ImportError:
    print("⚠️ python-dotenv non installé, tentative de chargement manuel du .env")
    # Fallback manual pour charger .env
    env_file = Path(".env")
    if env_file.exists():
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()
        print("✅ Variables d'environnement chargées manuellement")

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def check_requirements():
    """Vérifie que les dépendances sont installées"""
    required_packages = [
        'fastapi',
        'uvicorn',
        'streamlit',
        'httpx',
        'pydantic',
        'plotly',
        'pandas',
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        logger.error(f"Packages manquants: {missing_packages}")
        logger.info("Installez-les avec: pip install " + " ".join(missing_packages))
        return False
    
    return True

def check_environment():
    """Vérifie la configuration de l'environnement"""
    env_file = Path(".env")
    
    if not env_file.exists():
        logger.warning("Fichier .env non trouvé, création d'un exemple...")
        
        env_content = """# Configuration PumpFun Early Adopters Tracker
HELIUS_API_KEY=your_helius_api_key_here
DATABASE_URL=early_adopter.db

# Polling Configuration
BASE_POLLING_INTERVAL_SECONDS=120
MIN_POLLING_INTERVAL_SECONDS=60
MAX_POLLING_INTERVAL_SECONDS=300

# Budget
MAX_DAILY_CREDITS=2000
MIN_SOL_AMOUNT_FILTER=0.01

# API
API_HOST=0.0.0.0
API_PORT=8000
DEBUG=False

# Logging
LOG_LEVEL=INFO
"""
        
        with open(env_file, 'w') as f:
            f.write(env_content)
        
        logger.info("Fichier .env créé. Veuillez configurer votre HELIUS_API_KEY")
        return False
    
    # Vérifier si la clé API est configurée
    helius_key = os.getenv('HELIUS_API_KEY', '').strip()
    
    # Debug: afficher ce qui est lu
    logger.info(f"HELIUS_API_KEY lu: '{helius_key[:10]}...' (longueur: {len(helius_key)})")
    
    if not helius_key or helius_key == 'your_helius_api_key_here':
        logger.error("HELIUS_API_KEY non configurée ou invalide dans .env")
        logger.info("Veuillez éditer le fichier .env et définir votre clé API Helius")
        return False
    
    logger.info("Configuration environnement OK")
    return True

def initialize_database():
    """Initialise la base de données"""
    try:
        from .database import db
        logger.info("Base de données initialisée avec succès")
        return True
    except Exception as e:
        logger.error(f"Erreur initialisation base de données: {e}")
        return False

def start_api_server():
    """Démarre le serveur API"""
    logger.info("Démarrage du serveur API...")
    
    try:
        # Import de l'application
        from .main import app
        import uvicorn
        
        # Configuration
        host = os.getenv('API_HOST', '0.0.0.0')
        port = int(os.getenv('API_PORT', 8000))
        debug = os.getenv('DEBUG', 'False').lower() == 'true'
        
        logger.info(f"Serveur API démarré sur http://{host}:{port}")
        
        # Démarrage
        # NOTE: The app string must be "app.main:app" for reload to work correctly
        # when running with `python -m app.run` from the parent directory.
        app_string = "app.main:app"
        
        uvicorn.run(
            app_string if debug else app,
            host=host,
            port=port,
            reload=debug,
            log_level="info"
        )
        
    except Exception as e:
        logger.error(f"Erreur démarrage serveur API: {e}")
        return False

def start_streamlit():
    """Démarre l'interface Streamlit"""
    logger.info("Démarrage de l'interface Streamlit...")
    
    try:
        streamlit_port = int(os.getenv('STREAMLIT_PORT', 8501))
        
        cmd = [
            sys.executable, "-m", "streamlit", "run",
            "streamlit/streamlit_app.py",
            "--server.port", str(streamlit_port),
            "--server.address", "0.0.0.0"
        ]
        
        subprocess.run(cmd)
        
    except Exception as e:
        logger.error(f"Erreur démarrage Streamlit: {e}")
        return False

def main():
    """Fonction principale"""
    logger.info("🚀 Démarrage PumpFun Early Adopters Tracker - Version Polling")
    
    # Vérifications préalables
    logger.info("1. Vérification des dépendances...")
    if not check_requirements():
        sys.exit(1)
    
    logger.info("2. Vérification de l'environnement...")
    if not check_environment():
        sys.exit(1)
    
    logger.info("3. Initialisation de la base de données...")
    if not initialize_database():
        sys.exit(1)
    
    # Choix du mode de démarrage
    if len(sys.argv) > 1:
        mode = sys.argv[1].lower()
    else:
        print("\nChoisissez le mode de démarrage:")
        print("1. API seulement")
        print("2. Streamlit seulement") 
        print("3. Les deux (recommandé)")
        
        choice = input("Votre choix (1-3): ").strip()
        
        if choice == "1":
            mode = "api"
        elif choice == "2":
            mode = "streamlit"
        elif choice == "3":
            mode = "both"
        else:
            logger.error("Choix invalide")
            sys.exit(1)
    
    # Démarrage selon le mode
    if mode in ["api", "both"]:
        if mode == "both":
            # Démarrer l'API en arrière-plan pour le mode combiné
            logger.info("Mode combiné sélectionné")
            logger.info("Pour arrêter, utilisez Ctrl+C")
            
            import threading
            api_thread = threading.Thread(target=start_api_server, daemon=True)
            api_thread.start()
            
            # Attendre un peu que l'API démarre
            import time
            time.sleep(3)
            
            # Démarrer Streamlit en premier plan
            start_streamlit()
        else:
            start_api_server()
    
    elif mode == "streamlit":
        start_streamlit()
    
    else:
        logger.error("Mode invalide. Utilisez: api, streamlit, ou both")
        sys.exit(1)

if __name__ == "__main__":
    main()