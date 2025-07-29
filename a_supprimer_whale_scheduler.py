#!/usr/bin/env python3
"""
Whale Scheduler - Tâche automatique pour scanner les whales
VERSION WINDOWS COMPATIBLE (sans emojis dans les logs)
"""

import asyncio
import logging
import schedule
import time
import threading
from datetime import datetime
from whale_tracker import WhaleTracker, run_whale_scan

logger = logging.getLogger('whale_scheduler')

class WhaleScheduler:
    """Scheduler pour automatiser les scans de whales"""
    
    def __init__(self):
        self.is_running = False
        self.scheduler_thread = None
        self.tracker = WhaleTracker()
        
    def run_scheduled_scan(self):
        """Exécuter un scan programmé"""
        try:
            logger.info("Starting scheduled whale scan...")
            start_time = time.time()
            
            # Lancer le scan asynchrone
            asyncio.run(run_whale_scan())
            
            elapsed = time.time() - start_time
            logger.info(f"Scheduled whale scan completed in {elapsed:.1f}s")
            
            # Afficher les statistiques après le scan
            summary = self.tracker.get_whale_summary()
            logger.info(f"Scan results: {summary.get('total_whales', 0)} whales, "
                       f"${summary.get('total_whale_value_usd', 0):,.0f} total value")
            
        except Exception as e:
            logger.error(f"Error in scheduled whale scan: {e}")
    
    def start_scheduler(self):
        """Démarrer le scheduler en arrière-plan"""
        if self.is_running:
            logger.warning("Scheduler already running")
            return
            
        logger.info("Starting whale scheduler...")
        
        # Configuration des tâches programmées
        schedule.clear()  # Nettoyer les tâches existantes
        
        # Scanner toutes les 2 heures
        schedule.every(2).hours.do(self.run_scheduled_scan)
        
        # Scanner au démarrage (avec délai de 30 secondes)
        schedule.every().minute.do(self._initial_scan).tag('initial')
        
        self.is_running = True
        
        # Démarrer le thread du scheduler
        self.scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self.scheduler_thread.start()
        
        logger.info("Whale scheduler started (scanning every 2 hours)")
    
    def _initial_scan(self):
        """Scan initial au démarrage (une seule fois)"""
        logger.info("Running initial whale scan...")
        self.run_scheduled_scan()
        
        # Supprimer cette tâche après exécution
        schedule.clear('initial')
        return schedule.CancelJob
    
    def _scheduler_loop(self):
        """Boucle principale du scheduler"""
        while self.is_running:
            try:
                schedule.run_pending()
                time.sleep(60)  # Vérifier toutes les minutes
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
                time.sleep(60)
    
    def stop_scheduler(self):
        """Arrêter le scheduler"""
        if not self.is_running:
            return
            
        logger.info("Stopping whale scheduler...")
        self.is_running = False
        schedule.clear()
        
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=5)
        
        logger.info("Whale scheduler stopped")
    
    def get_next_scan_time(self):
        """Obtenir l'heure du prochain scan"""
        jobs = schedule.get_jobs()
        if jobs:
            next_run = min(job.next_run for job in jobs if job.next_run)
            return next_run
        return None
    
    def force_scan(self):
        """Forcer un scan immédiat"""
        logger.info("Forcing immediate whale scan...")
        threading.Thread(target=self.run_scheduled_scan, daemon=True).start()

# Instance globale du scheduler
whale_scheduler = WhaleScheduler()

def start_whale_monitoring():
    """Fonction pour démarrer le monitoring automatique des whales"""
    whale_scheduler.start_scheduler()

def stop_whale_monitoring():
    """Fonction pour arrêter le monitoring automatique des whales"""
    whale_scheduler.stop_scheduler()

def force_whale_scan():
    """Fonction pour forcer un scan immédiat"""
    whale_scheduler.force_scan()

if __name__ == "__main__":
    # Configuration du logging compatible Windows
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('whale_scheduler.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    
    try:
        # Démarrer le scheduler
        start_whale_monitoring()
        
        # Garder le script en vie
        while True:
            time.sleep(30)
            
            # Afficher le statut toutes les 30 secondes
            next_scan = whale_scheduler.get_next_scan_time()
            if next_scan:
                logger.info(f"Next whale scan: {next_scan.strftime('%H:%M:%S')}")
            
    except KeyboardInterrupt:
        logger.info("Stopping whale scheduler...")
        stop_whale_monitoring()
    except Exception as e:
        logger.error(f"Fatal error in whale scheduler: {e}")
        stop_whale_monitoring()