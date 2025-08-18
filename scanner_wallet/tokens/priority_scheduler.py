#!/usr/bin/env python3
"""
Ordonnanceur pour les cycles de mise à jour par priorité
"""

import asyncio
import time
import threading
from typing import Dict, List, Optional
from datetime import datetime

from core.priority_config import TokenPriority, PriorityConfig
from core.logger import get_logger
from tokens.priority_manager import TokenPriorityManager

class PriorityScheduler:
    """Ordonnanceur des cycles de mise à jour par priorité"""
    
    def __init__(self, priority_config: PriorityConfig, priority_manager: TokenPriorityManager):
        self.config = priority_config
        self.manager = priority_manager
        self.logger = get_logger('priority_scheduler')
        
        self.running = False
        self.cycles_stats = {
            'critical': {'count': 0, 'last_run': None, 'tokens_processed': 0},
            'hot': {'count': 0, 'last_run': None, 'tokens_processed': 0},
            'warm': {'count': 0, 'last_run': None, 'tokens_processed': 0},
            'cold': {'count': 0, 'last_run': None, 'tokens_processed': 0}
        }
        
        # Callback pour le traitement des tokens (sera fourni par le service principal)
        self.token_processor_callback = None
        
        # Threads pour chaque cycle
        self.cycle_threads = {}
    
    def set_token_processor(self, callback):
        """Définit la fonction de traitement des tokens"""
        self.token_processor_callback = callback
    
    def start(self):
        """Démarre tous les cycles de mise à jour"""
        if self.running:
            self.logger.warning("⚠️ Scheduler déjà en cours d'exécution")
            return
        
        if not self.token_processor_callback:
            self.logger.error("❌ Aucun processeur de tokens défini")
            return
        
        self.running = True
        self.logger.info("🚀 Démarrage du scheduler de priorité")
        
        # Démarrer les threads pour chaque cycle
        self.cycle_threads = {
            'critical': threading.Thread(target=self._run_critical_cycle, daemon=True),
            'hot': threading.Thread(target=self._run_hot_cycle, daemon=True),
            'warm': threading.Thread(target=self._run_warm_cycle, daemon=True),
            'cold': threading.Thread(target=self._run_cold_cycle, daemon=True),
            'recalculation': threading.Thread(target=self._run_recalculation_cycle, daemon=True)
        }
        
        for name, thread in self.cycle_threads.items():
            thread.start()
            self.logger.info(f"✅ Cycle {name} démarré")
    
    def stop(self):
        """Arrête tous les cycles"""
        self.logger.info("🛑 Arrêt du scheduler")
        self.running = False
        
        # Attendre l'arrêt des threads (timeout de 5s)
        for name, thread in self.cycle_threads.items():
            if thread.is_alive():
                thread.join(timeout=5.0)
                if thread.is_alive():
                    self.logger.warning(f"⚠️ Thread {name} n'a pas pu être arrêté proprement")
    
    def _run_critical_cycle(self):
        """Cycle pour les tokens CRITICAL - 30 secondes"""
        self.logger.info("🔥 Cycle CRITICAL démarré")
        
        while self.running:
            try:
                start_time = time.time()
                
                # Récupérer les tokens critiques
                critical_tokens = self.manager.get_tokens_by_priority(
                    TokenPriority.CRITICAL, 
                    self.config.max_tokens_per_batch
                )
                
                if critical_tokens:
                    self.logger.debug(f"🔥 Traitement de {len(critical_tokens)} tokens CRITICAL")
                    
                    # Traiter les tokens
                    processed = self._process_tokens_batch(critical_tokens, "CRITICAL")
                    
                    # Mettre à jour les stats
                    self.cycles_stats['critical']['count'] += 1
                    self.cycles_stats['critical']['last_run'] = datetime.now()
                    self.cycles_stats['critical']['tokens_processed'] += processed
                
                # Calculer le temps d'attente
                processing_time = time.time() - start_time
                sleep_time = max(0, self.config.critical_interval - processing_time)
                
                if self.running:
                    time.sleep(sleep_time)
                    
            except Exception as e:
                self.logger.error(f"❌ Erreur dans le cycle CRITICAL: {e}")
                time.sleep(self.config.critical_interval)
    
    def _run_hot_cycle(self):
        """Cycle pour les tokens HOT - 30 secondes"""
        self.logger.info("🌡️ Cycle HOT démarré")
        
        while self.running:
            try:
                start_time = time.time()
                
                hot_tokens = self.manager.get_tokens_by_priority(
                    TokenPriority.HOT, 
                    self.config.max_tokens_per_batch
                )
                
                if hot_tokens:
                    self.logger.debug(f"🌡️ Traitement de {len(hot_tokens)} tokens HOT")
                    processed = self._process_tokens_batch(hot_tokens, "HOT")
                    
                    self.cycles_stats['hot']['count'] += 1
                    self.cycles_stats['hot']['last_run'] = datetime.now()
                    self.cycles_stats['hot']['tokens_processed'] += processed
                
                processing_time = time.time() - start_time
                sleep_time = max(0, self.config.hot_interval - processing_time)
                
                if self.running:
                    time.sleep(sleep_time)
                    
            except Exception as e:
                self.logger.error(f"❌ Erreur dans le cycle HOT: {e}")
                time.sleep(self.config.hot_interval)
    
    def _run_warm_cycle(self):
        """Cycle pour les tokens WARM - 5 minutes"""
        self.logger.info("🟡 Cycle WARM démarré")
        
        while self.running:
            try:
                start_time = time.time()
                
                warm_tokens = self.manager.get_tokens_by_priority(
                    TokenPriority.WARM, 
                    self.config.max_tokens_per_batch
                )
                
                if warm_tokens:
                    self.logger.debug(f"🟡 Traitement de {len(warm_tokens)} tokens WARM")
                    processed = self._process_tokens_batch(warm_tokens, "WARM")
                    
                    self.cycles_stats['warm']['count'] += 1
                    self.cycles_stats['warm']['last_run'] = datetime.now()
                    self.cycles_stats['warm']['tokens_processed'] += processed
                
                processing_time = time.time() - start_time
                sleep_time = max(0, self.config.warm_interval - processing_time)
                
                if self.running:
                    time.sleep(sleep_time)
                    
            except Exception as e:
                self.logger.error(f"❌ Erreur dans le cycle WARM: {e}")
                time.sleep(self.config.warm_interval)
    
    def _run_cold_cycle(self):
        """Cycle pour les tokens COLD - 1 heure"""
        self.logger.info("🧊 Cycle COLD démarré")
        
        while self.running:
            try:
                start_time = time.time()
                
                cold_tokens = self.manager.get_tokens_by_priority(
                    TokenPriority.COLD, 
                    self.config.max_tokens_per_batch * 2  # Plus de tokens COLD
                )
                
                if cold_tokens:
                    self.logger.debug(f"🧊 Traitement de {len(cold_tokens)} tokens COLD")
                    processed = self._process_tokens_batch(cold_tokens, "COLD")
                    
                    self.cycles_stats['cold']['count'] += 1
                    self.cycles_stats['cold']['last_run'] = datetime.now()
                    self.cycles_stats['cold']['tokens_processed'] += processed
                
                processing_time = time.time() - start_time
                sleep_time = max(0, self.config.cold_interval - processing_time)
                
                if self.running:
                    time.sleep(sleep_time)
                    
            except Exception as e:
                self.logger.error(f"❌ Erreur dans le cycle COLD: {e}")
                time.sleep(self.config.cold_interval)
    
    def _run_recalculation_cycle(self):
        """Cycle de recalcul complet des priorités"""
        self.logger.info("🔄 Cycle de recalcul démarré")
        
        while self.running:
            try:
                self.logger.info("🔄 Début du recalcul complet des priorités")
                stats = self.manager.recalculate_all_priorities()
                
                self.logger.info(f"✅ Recalcul terminé: {stats['priority_changes']} changements")
                
                # Sauvegarder les métriques
                self.manager.save_metrics()
                
                # Attendre le prochain recalcul
                if self.running:
                    time.sleep(self.config.recalculation_interval)
                    
            except Exception as e:
                self.logger.error(f"❌ Erreur dans le cycle de recalcul: {e}")
                time.sleep(300)  # Attendre 5 minutes en cas d'erreur
    
    def _process_tokens_batch(self, token_addresses: List[str], priority_name: str) -> int:
        """
        Traite un batch de tokens via le callback
        
        Args:
            token_addresses: Liste des adresses
            priority_name: Nom de la priorité pour les logs
            
        Returns:
            Nombre de tokens traités avec succès
        """
        if not self.token_processor_callback:
            self.logger.error("❌ Aucun processeur de tokens configuré")
            return 0
        
        try:
            # Appeler le processeur de tokens (sera fourni par le sync_service)
            processed_count = self.token_processor_callback(token_addresses)
            
            # Marquer les tokens pour recalcul après traitement
            self.manager.mark_tokens_for_recalculation(token_addresses)
            
            return processed_count
            
        except Exception as e:
            self.logger.error(f"❌ Erreur traitement batch {priority_name}: {e}")
            return 0
    
    def get_status(self) -> Dict:
        """Retourne le statut du scheduler"""
        return {
            'running': self.running,
            'cycles_stats': self.cycles_stats,
            'priority_distribution': self.manager.get_priority_distribution(),
            'manager_stats': self.manager.get_stats()
        }
    
    def force_recalculation(self):
        """Force un recalcul immédiat des priorités"""
        self.logger.info("🔄 Recalcul forcé des priorités")
        try:
            stats = self.manager.recalculate_all_priorities()
            self.logger.info(f"✅ Recalcul forcé terminé: {stats['priority_changes']} changements")
            return stats
        except Exception as e:
            self.logger.error(f"❌ Erreur recalcul forcé: {e}")
            return None