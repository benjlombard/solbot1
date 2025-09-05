import logging
import hmac
import hashlib
from datetime import datetime
from typing import Dict, Any, List
import asyncio
from collections import defaultdict

from fastapi import HTTPException
from models import HeliusWebhookData, HeliusTransaction
from data_processor import processor
from early_adopter_scorer import scorer
from config import settings

logger = logging.getLogger(__name__)

class WebhookHandler:
    def __init__(self):
        self.webhook_secret = settings.helius_webhook_secret
        self.processing_queue = asyncio.Queue(maxsize=1000)
        self.credits_used_today = 0
        self.daily_stats = defaultdict(int)
        self.last_reset_date = datetime.now().date()
        
        # Démarrer le worker de traitement en arrière-plan
        self.processing_task = None
    
    def start_background_processing(self):
        """Démarre le traitement en arrière-plan"""
        if not self.processing_task or self.processing_task.done():
            self.processing_task = asyncio.create_task(self._process_queue_worker())
            logger.info("Background processing started")
    
    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """
        Vérifie la signature du webhook Helius pour s'assurer de l'authenticité
        """
        if not self.webhook_secret:
            logger.warning("No webhook secret configured, skipping verification")
            return True
        
        # Pour les tests sans webhook réel, retourner True
        if self.webhook_secret == "test_mode":
            logger.info("Test mode activated, skipping signature verification")
            return True
            
        try:
            expected_signature = hmac.new(
                self.webhook_secret.encode(),
                payload,
                hashlib.sha256
            ).hexdigest()
            
            # Helius envoie la signature avec le préfixe 'sha256='
            if signature.startswith('sha256='):
                signature = signature[7:]
            
            return hmac.compare_digest(expected_signature, signature)
            
        except Exception as e:
            logger.error(f"Error verifying webhook signature: {e}")
            return False
    
    async def handle_webhook(self, payload: bytes, signature: str = None) -> Dict[str, Any]:
        """
        Point d'entrée principal pour traiter les webhooks Helius
        """
        response = {
            'status': 'success',
            'processed_transactions': 0,
            'tokens_created': 0,
            'purchases_detected': 0,
            'errors': []
        }
        
        try:
            # Vérifier la signature si fournie
            if signature and not self.verify_webhook_signature(payload, signature):
                raise HTTPException(status_code=401, detail="Invalid webhook signature")
            
            # Parser les données webhook
            webhook_data = HeliusWebhookData.parse_raw(payload)
            
            # Mettre à jour les statistiques quotidiennes
            self._update_daily_stats(len(webhook_data.transactions))
            
            # Optimisation budget : filtrer les transactions non pertinentes
            filtered_transactions = self._filter_transactions(webhook_data.transactions)
            
            logger.info(f"Received {len(webhook_data.transactions)} transactions, "
                       f"filtered to {len(filtered_transactions)} relevant ones")
            
            # Ajouter à la queue de traitement
            for transaction in filtered_transactions:
                try:
                    await self.processing_queue.put(transaction)
                except asyncio.QueueFull:
                    logger.warning("Processing queue full, dropping transaction")
                    response['errors'].append("Queue full - transaction dropped")
            
            response['processed_transactions'] = len(filtered_transactions)
            
        except Exception as e:
            error_msg = f"Error handling webhook: {e}"
            logger.error(error_msg)
            response['status'] = 'error'
            response['errors'].append(error_msg)
            raise HTTPException(status_code=500, detail=error_msg)
        
        return response
    
    def _filter_transactions(self, transactions: List[HeliusTransaction]) -> List[HeliusTransaction]:
        """
        Filtre les transactions pour optimiser l'utilisation des crédits
        """
        filtered = []
        
        for transaction in transactions:
            # Vérifier si c'est une transaction pump.fun
            is_pumpfun = any(
                inst.programId == settings.pumpfun_program_id 
                for inst in transaction.instructions
            )
            
            if not is_pumpfun:
                continue
            
            # Filtrer les micro-transactions pour économiser les crédits
            if transaction.type == "SWAP":
                has_significant_transfer = False
                
                if transaction.tokenTransfers:
                    for transfer in transaction.tokenTransfers:
                        amount = float(transfer.get('tokenAmount', 0))
                        if amount >= settings.min_sol_amount_filter:
                            has_significant_transfer = True
                            break
                
                if not has_significant_transfer:
                    continue
            
            # Éviter les doublons récents (debouncing)
            if self._is_recent_duplicate(transaction):
                continue
            
            filtered.append(transaction)
        
        return filtered
    
    def _is_recent_duplicate(self, transaction: HeliusTransaction) -> bool:
        """
        Vérifie si cette transaction est un doublon récent
        """
        # Implémentation simple basée sur la signature
        # Dans un vrai système, on utiliserait un cache Redis
        return False  # Pour le MVP, on désactive cette fonctionnalité
    
    async def _process_queue_worker(self):
        """
        Worker qui traite les transactions en arrière-plan
        """
        logger.info("Starting queue processing worker")
        
        while True:
            try:
                # Traiter par lots pour optimiser les performances
                batch = []
                
                # Collecter un lot de transactions
                for _ in range(settings.batch_size):
                    try:
                        transaction = await asyncio.wait_for(
                            self.processing_queue.get(), 
                            timeout=5.0
                        )
                        batch.append(transaction)
                    except asyncio.TimeoutError:
                        break
                
                if batch:
                    await self._process_transaction_batch(batch)
                
                # Petite pause pour éviter de surcharger
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error in queue worker: {e}")
                await asyncio.sleep(1.0)
    
    async def _process_transaction_batch(self, transactions: List[HeliusTransaction]):
        """
        Traite un lot de transactions
        """
        logger.info(f"Processing batch of {len(transactions)} transactions")
        
        tokens_created = 0
        purchases_detected = 0
        
        for transaction in transactions:
            try:
                # Traiter la transaction
                result = await processor.process_helius_transaction(transaction)
                
                if result['processed']:
                    if result['token_created']:
                        tokens_created += 1
                    
                    purchases_detected += len(result['purchases'])
                
            except Exception as e:
                logger.error(f"Error processing transaction {transaction.signature}: {e}")
        
        # Mettre à jour les statistiques
        if tokens_created > 0 or purchases_detected > 0:
            logger.info(f"Batch processed: {tokens_created} tokens created, "
                       f"{purchases_detected} purchases detected")
        
        # Trigger scoring update périodiquement
        if purchases_detected > 0:
            asyncio.create_task(self._trigger_scoring_update())
    
    async def _trigger_scoring_update(self):
        """
        Déclenche une mise à jour du scoring des early adopters
        """
        try:
            # Exécuter le scoring en arrière-plan sans bloquer
            await scorer.update_all_early_adopters()
            logger.info("Early adopter scoring updated")
        except Exception as e:
            logger.error(f"Error updating early adopter scores: {e}")
    
    def _update_daily_stats(self, transaction_count: int):
        """
        Met à jour les statistiques quotidiennes
        """
        current_date = datetime.now().date()
        
        # Reset quotidien
        if current_date != self.last_reset_date:
            self.daily_stats.clear()
            self.credits_used_today = 0
            self.last_reset_date = current_date
            logger.info("Daily stats reset")
        
        # Estimation approximative des crédits utilisés
        # Chaque transaction Enhanced coûte ~1 crédit
        estimated_credits = transaction_count
        self.credits_used_today += estimated_credits
        
        self.daily_stats['transactions_received'] += transaction_count
        self.daily_stats['credits_estimated'] += estimated_credits
        
        # Alerte si proche de la limite
        if self.credits_used_today > settings.max_daily_credits * 0.8:
            logger.warning(f"High credit usage: {self.credits_used_today}/{settings.max_daily_credits}")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Retourne les statistiques du gestionnaire de webhooks
        """
        return {
            'daily_stats': dict(self.daily_stats),
            'credits_used_today': self.credits_used_today,
            'max_daily_credits': settings.max_daily_credits,
            'queue_size': self.processing_queue.qsize(),
            'processing_active': self.processing_task and not self.processing_task.done(),
            'last_reset_date': self.last_reset_date.isoformat()
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Vérifie la santé du système de webhooks
        """
        health = {
            'status': 'healthy',
            'issues': []
        }
        
        # Vérifier la queue
        queue_size = self.processing_queue.qsize()
        if queue_size > 500:
            health['issues'].append(f"Queue size high: {queue_size}")
        
        # Vérifier le worker
        if not self.processing_task or self.processing_task.done():
            health['issues'].append("Background processing not running")
            health['status'] = 'degraded'
        
        # Vérifier l'utilisation des crédits
        credit_usage_pct = (self.credits_used_today / settings.max_daily_credits) * 100
        if credit_usage_pct > 90:
            health['issues'].append(f"Credit usage critical: {credit_usage_pct:.1f}%")
            health['status'] = 'warning'
        
        health['queue_size'] = queue_size
        health['credit_usage_percent'] = credit_usage_pct
        
        return health
    
    async def shutdown(self):
        """
        Arrêt propre du gestionnaire
        """
        if self.processing_task and not self.processing_task.done():
            self.processing_task.cancel()
            try:
                await self.processing_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Webhook handler shutdown complete")

# Instance globale
webhook_handler = WebhookHandler()