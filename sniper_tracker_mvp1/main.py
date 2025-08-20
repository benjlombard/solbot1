# main.py
import subprocess
import threading
import time
import logging
import signal
import sys
from setup_db import create_database

# Configuration des logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/app.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

class SniperTrackerApp:
    def __init__(self):
        self.webhook_process = None
        self.dashboard_process = None
        self.running = True
    
    def start_webhook_server(self):
        """Démarre le serveur de webhooks"""
        logger.info("🚀 Démarrage du serveur webhook...")
        self.webhook_process = subprocess.Popen([
            'uvicorn', 'webhook_receiver:app', 
            '--host', '0.0.0.0', 
            '--port', '8000',
            '--reload'
        ])
    
    def start_dashboard(self):
        """Démarre le dashboard Streamlit"""
        logger.info("📊 Démarrage du dashboard...")
        self.dashboard_process = subprocess.Popen([
            'streamlit', 'run', 'dashboard.py',
            '--server.port', '8501',
            '--server.address', '0.0.0.0'
        ])
    
    def stop_all(self):
        """Arrête tous les processus"""
        logger.info("🛑 Arrêt de l'application...")
        
        if self.webhook_process:
            self.webhook_process.terminate()
            self.webhook_process.wait()
        
        if self.dashboard_process:
            self.dashboard_process.terminate()
            self.dashboard_process.wait()
        
        self.running = False
    
    def signal_handler(self, signum, frame):
        """Gestionnaire de signaux pour arrêt propre"""
        logger.info("Signal reçu, arrêt en cours...")
        self.stop_all()
        sys.exit(0)
    
    def run(self):
        """Lance l'application complète"""
        # Création de la base de données
        create_database()
        
        # Configuration des signaux
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        try:
            # Démarrage des services
            self.start_webhook_server()
            time.sleep(2)  # Attente démarrage webhook
            
            self.start_dashboard()
            
            logger.info("✅ Application démarrée avec succès!")
            logger.info("📊 Dashboard: http://localhost:8501")
            logger.info("🔗 Webhook: http://localhost:8000")
            
            # Boucle principale
            while self.running:
                time.sleep(1)
                
                # Vérification santé des processus
                if self.webhook_process.poll() is not None:
                    logger.error("❌ Serveur webhook arrêté!")
                    break
                
                if self.dashboard_process.poll() is not None:
                    logger.error("❌ Dashboard arrêté!")
                    break
        
        except Exception as e:
            logger.error(f"Erreur critique: {str(e)}")
        
        finally:
            self.stop_all()

if __name__ == "__main__":
    app = SniperTrackerApp()
    app.run()