#!/usr/bin/env python3
"""
Service principal du système de priorité des tokens
Fonctionne en parallèle du sync_service existant
"""

import signal
import sys
import time
import asyncio
from pathlib import Path

# Ajouter la racine du projet au path
project_root = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(project_root))

from core.config import get_config
from core.priority_config import PriorityConfig
from core.logger import get_logger, SolanaWalletLogger
from tokens.priority_manager import TokenPriorityManager
from tokens.priority_scheduler import PriorityScheduler
from tokens.sync_service import TokenSyncService  # Import de votre service existant

class PriorityTokenService:
    """Service principal du système de priorité"""
    
    def __init__(self):
        # Configuration
        self.config = get_config()
        self.priority_config = PriorityConfig.from_env()
        
        # Logger spécialisé
        self.setup_logger()
        
        # Composants
        self.priority_manager = TokenPriorityManager(self.priority_config)
        self.scheduler = PriorityScheduler(self.priority_config, self.priority_manager)
        
        # Service de sync pour traiter les tokens
        self.sync_service = TokenSyncService()
        
        # État
        self.running = False
        
        self.logger.info("🎯 Priority Token Service initialisé")
    
    def setup_logger(self):
        """Configure le logger spécialisé"""
        priority_logger = SolanaWalletLogger(
            log_level=self.priority_config.log_level,
            log_file=str(Path(self.config.logging.base_dir) / self.priority_config.log_file),
            console_output=self.config.logging.console_output,
            json_output=self.config.logging.json_output,
            max_file_size=20 * 1024 * 1024,  # 20MB
            backup_count=5,
            max_age_days=self.config.logging.max_age_days,
            force_reconfigure=True
        )
        
        self.logger = priority_logger.get_logger('priority_service')
    
    def token_processor_callback(self, token_addresses: list) -> int:
        """
        Callback pour traiter les tokens via le sync_service existant
        
        Args:
            token_addresses: Liste des adresses à traiter
            
        Returns:
            Nombre de tokens traités avec succès
        """
        try:
            # Utiliser la méthode async existante du sync_service
            result = asyncio.run(
                self.sync_service.process_tokens_in_batches_async(token_addresses)
            )
            
            self.logger.debug(f"✅ Traitement terminé: {result}/{len(token_addresses)} tokens")
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Erreur traitement tokens: {e}")
            return 0
    
    def start(self):
        """Démarre le service de priorité"""
        self.logger.info("🚀 Démarrage du Priority Token Service")
        
        try:
            # Configuration du callback
            self.scheduler.set_token_processor(self.token_processor_callback)
            
            # Recalcul initial des priorités
            self.logger.info("🔄 Recalcul initial des priorités...")
            initial_stats = self.priority_manager.recalculate_all_priorities()
            
            self.logger.info("📊 Répartition initiale:")
            distribution = self.priority_manager.get_priority_distribution()
            for priority, count in distribution.items():
                self.logger.info(f"   {priority}: {count} tokens")
            
            # Démarrer le scheduler
            self.scheduler.start()
            self.running = True
            
            self.logger.info("✅ Service de priorité opérationnel")
            
            # Boucle principale
            self.main_loop()
            
        except Exception as e:
            self.logger.error(f"❌ Erreur critique lors du démarrage: {e}")
            self.stop()
    
    def main_loop(self):
        """Boucle principale du service"""
        status_interval = 300  # Log du statut toutes les 5 minutes
        last_status_log = 0
        
        try:
            while self.running:
                current_time = time.time()
                
                # Log périodique du statut
                if current_time - last_status_log > status_interval:
                    self.log_service_status()
                    last_status_log = current_time
                
                # Vérification de la santé du service
                if not self.scheduler.running:
                    self.logger.error("❌ Scheduler arrêté de manière inattendue")
                    break
                
                time.sleep(30)  # Vérification toutes les 30 secondes
                
        except KeyboardInterrupt:
            self.logger.info("⌨️ Interruption clavier détectée")
        except Exception as e:
            self.logger.error(f"❌ Erreur dans la boucle principale: {e}")
    
    def log_service_status(self):
        """Log le statut du service"""
        try:
            status = self.scheduler.get_status()
            
            self.logger.info("📊 === STATUT DU SERVICE DE PRIORITÉ ===")
            
            # Distribution des priorités
            distribution = status['priority_distribution']
            total_tokens = sum(distribution.values())
            
            self.logger.info(f"📈 Tokens gérés: {total_tokens}")
            for priority, count in distribution.items():
                percentage = (count / total_tokens * 100) if total_tokens > 0 else 0
                self.logger.info(f"   {priority}: {count} ({percentage:.1f}%)")
            
            # Stats des cycles
            cycles_stats = status['cycles_stats']
            self.logger.info("🔄 Cycles:")
            for cycle_name, stats in cycles_stats.items():
                last_run = stats['last_run']
                last_run_str = last_run.strftime('%H:%M:%S') if last_run else 'Jamais'
                self.logger.info(f"   {cycle_name}: {stats['count']} cycles, dernière exécution: {last_run_str}")
            
            # Économies d'API estimées
            api_savings = self.estimate_api_savings(distribution)
            self.logger.info(f"💰 Économies API estimées: {api_savings:.1f}%")
            
        except Exception as e:
            self.logger.error(f"❌ Erreur log statut: {e}")
    
    def estimate_api_savings(self, distribution: dict) -> float:
        """Estime les économies d'appels API"""
        try:
            # Calcul théorique des appels sans priorité
            total_tokens = sum(distribution.values())
            if total_tokens == 0:
                return 0.0
            
            # Avec le système standard: tous les tokens mis à jour toutes les heures
            standard_calls_per_hour = total_tokens
            
            # Avec le système de priorité (approximation)
            hot_calls = distribution.get('HOT', 0) * 120  # 120 appels/heure
            warm_calls = distribution.get('WARM', 0) * 12  # 12 appels/heure
            cold_calls = distribution.get('COLD', 0) * 1   # 1 appel/heure
            critical_calls = distribution.get('CRITICAL', 0) * 120
            
            priority_calls_per_hour = hot_calls + warm_calls + cold_calls + critical_calls
            
            if standard_calls_per_hour > 0:
                savings = ((standard_calls_per_hour - priority_calls_per_hour) / standard_calls_per_hour) * 100
                return max(0, savings)
            
            return 0.0
            
        except Exception:
            return 0.0
    
    def stop(self):
        """Arrête le service"""
        self.logger.info("🛑 Arrêt du Priority Token Service")
        
        self.running = False
        
        # Arrêter le scheduler
        if hasattr(self, 'scheduler'):
            self.scheduler.stop()
        
        # Log final
        try:
            final_stats = self.priority_manager.get_stats()
            self.logger.info("📊 Statistiques finales:")
            self.logger.info(f"   Tokens mis à jour: {final_stats['tokens_updated']}")
            self.logger.info(f"   Changements de priorité: {final_stats['priority_changes']}")
            self.logger.info(f"   Erreurs: {final_stats['calculation_errors']}")
        except Exception:
            pass
        
        self.logger.info("✅ Priority Token Service arrêté")

# Variables globales pour la gestion des signaux
service = None

def signal_handler(signum, frame):
    """Gestionnaire des signaux pour arrêt propre"""
    global service
    if service:
        service.stop()
    sys.exit(0)

def main():
    """Point d'entrée principal"""
    global service
    
    # Configuration des signaux
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Créer et démarrer le service
    service = PriorityTokenService()
    service.start()

if __name__ == "__main__":
    main()