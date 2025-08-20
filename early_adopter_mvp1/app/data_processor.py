import logging
import json
import base64
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
import struct
import httpx
from collections import defaultdict

from models import PumpToken, EarlyPurchase, HeliusTransaction
from database import db
from config import settings

logger = logging.getLogger(__name__)

class OptimizedPumpFunDataProcessor:
    def __init__(self):
        self.pumpfun_program_id = settings.pumpfun_program_id
        self.processed_signatures = set()
        self.httpx_client = httpx.AsyncClient(timeout=settings.httpx_timeout_seconds)
        
        # Cache pour les métadonnées des tokens
        self.token_metadata_cache = {}
        self.cache_cleanup_counter = 0
        
        # Statistiques de performance
        self.processing_stats = defaultdict(int)
        self.last_stats_reset = datetime.now()
    
    async def process_helius_transaction(self, transaction: HeliusTransaction) -> Dict[str, Any]:
        """
        Traite une transaction Helius de manière optimisée pour le polling
        """
        result = {
            'processed': False,
            'token_created': None,
            'purchases': [],
            'errors': [],
            'processing_time_ms': 0
        }
        
        start_time = datetime.now()
        
        try:
            logger.info(f"🔄 Processing transaction: {transaction.signature[:20]}...")
            logger.info(f"   Type: {transaction.type}")
            logger.info(f"   Instructions: {len(transaction.instructions)}")
            logger.info(f"   Token transfers: {len(transaction.tokenTransfers)}")
            
            # Compter et log les instructions pump.fun
            pumpfun_instructions = []
            for i, instruction in enumerate(transaction.instructions):
                logger.info(f"   Instruction {i}: {instruction.programId}")
                if instruction.programId == self.pumpfun_program_id:
                    pumpfun_instructions.append(i)
                    logger.info(f"     🎯 PUMP.FUN INSTRUCTION #{i}")
            
            logger.info(f"   Pump.fun instructions found: {len(pumpfun_instructions)}")
            
            # Éviter les doublons avec cache optimisé
            if transaction.signature in self.processed_signatures:
                logger.debug(f"Transaction already processed: {transaction.signature}")
                return result
            
            # Vérification rapide si c'est une transaction pump.fun
            if not self._is_pumpfun_transaction_fast(transaction):
                logger.info(f"   ❌ No pump.fun instructions detected in final check")
                return result
            
            # Pré-filtrage pour optimiser les crédits
            if not self._should_process_transaction(transaction):
                logger.debug(f"Transaction filtered out: {transaction.signature}")
                return result
            
            # Traitement selon le type de transaction avec optimisations
            processed_something = False
            
            if transaction.type == "UNKNOWN":
                logger.info(f"   🔍 Processing as potential token creation...")
                # Potentielle création de token
                token = await self._process_token_creation_optimized(transaction)
                if token:
                    result['token_created'] = token
                    processed_something = True
                    self.processing_stats['tokens_created'] += 1
                    logger.info(f"   ✅ Token created: {token.address}")
                else:
                    logger.info(f"   ❌ No token creation detected")
            
            elif transaction.type == "SWAP":
                logger.info(f"   🔍 Processing as potential token purchase...")
                # Potentiel achat de token
                purchase = await self._process_token_purchase_optimized(transaction)
                if purchase:
                    result['purchases'].append(purchase)
                    processed_something = True
                    self.processing_stats['purchases_detected'] += 1
                    logger.info(f"   ✅ Purchase detected: {purchase.buyer_address[:20]}... -> {purchase.token_address[:20]}...")
                else:
                    logger.info(f"   ❌ No token purchase detected")
            
            # Marquer comme traité seulement si traitement réussi
            if processed_something:
                self.processed_signatures.add(transaction.signature)
                result['processed'] = True
                logger.info(f"   ✅ Transaction processing completed successfully")
            else:
                logger.info(f"   ⚠️ Transaction processed but no pump.fun activity detected")
            
            # Nettoyage périodique optimisé du cache
            self._periodic_cache_cleanup()
            
        except Exception as e:
            logger.error(f"Error processing transaction {transaction.signature}: {e}")
            result['errors'].append(str(e))
            self.processing_stats['errors'] += 1
        
        # Calcul du temps de traitement
        processing_time = (datetime.now() - start_time).total_seconds() * 1000
        result['processing_time_ms'] = round(processing_time, 2)
        
        self.processing_stats['total_processed'] += 1
        
        return result
    
    def _is_pumpfun_transaction_fast(self, transaction: HeliusTransaction) -> bool:
        """Vérification rapide si la transaction concerne pump.fun - CORRIGÉE"""
        # Vérification optimisée - compter toutes les instructions
        pumpfun_count = 0
        for instruction in transaction.instructions:
            if instruction.programId == self.pumpfun_program_id:
                pumpfun_count += 1
                logger.info(f"   ✅ Found pump.fun instruction with programId: {instruction.programId}")
        
        logger.info(f"   Final pump.fun check: {pumpfun_count} instructions found")
        return pumpfun_count > 0
    
    def _should_process_transaction(self, transaction: HeliusTransaction) -> bool:
        """
        Détermine si une transaction mérite d'être traitée (optimisation crédits)
        """
        # Filtrer les micro-transactions
        if transaction.type == "SWAP":
            total_value = 0
            
            if transaction.tokenTransfers:
                for transfer in transaction.tokenTransfers:
                    try:
                        amount = float(transfer.get('tokenAmount', 0))
                        # Convertir en SOL si c'est en lamports
                        if transfer.get('mint') == 'So11111111111111111111111111111111111111112':
                            amount = amount / 1e9
                        total_value += amount
                    except (ValueError, TypeError):
                        continue
            
            # Ignorer les transactions trop petites
            if total_value < settings.min_transaction_value_sol:
                return False
        
        # Toujours traiter les créations potentielles
        if transaction.type == "UNKNOWN":
            return True
        
        # Vérifier s'il y a des comptes intéressants
        interesting_accounts = set()
        for instruction in transaction.instructions:
            if instruction.programId == self.pumpfun_program_id:
                interesting_accounts.update(instruction.accounts[:5])  # Limiter à 5 comptes
        
        return len(interesting_accounts) > 2  # Au moins 3 comptes impliqués
    
    async def _process_token_creation_optimized(self, transaction: HeliusTransaction) -> Optional[PumpToken]:
        """
        Traite une création de token de manière optimisée avec logs détaillés
        """
        try:
            logger.info(f"     🔍 Analyzing transaction for token creation...")
            
            # Recherche rapide des données de token dans les instructions
            for i, instruction in enumerate(transaction.instructions):
                logger.info(f"     Instruction {i}: {instruction.programId}")
                
                if instruction.programId == self.pumpfun_program_id:
                    logger.info(f"     ✅ Found pump.fun instruction at index {i}")
                    
                    # Extraction rapide de l'adresse du token
                    token_address = self._extract_token_address_fast(instruction, transaction)
                    
                    logger.info(f"     Extracted token address: {token_address}")
                    
                    if not token_address:
                        logger.info(f"     ❌ No token address found")
                        continue
                    
                    # Vérifier si ce token existe déjà
                    existing_token = db.get_token_by_address(token_address)
                    if existing_token:
                        logger.info(f"     ⚠️ Token already exists: {token_address}")
                        continue
                    
                    # Créer un token avec métadonnées minimales
                    token = PumpToken(
                        address=token_address,
                        name=None,  # À enrichir plus tard si nécessaire
                        symbol=None,
                        description=None,
                        creator=transaction.feePayer,
                        created_at=transaction.timestamp,
                        market_cap_discovery=None
                    )
                    
                    logger.info(f"     💾 Saving new token to database...")
                    
                    # Sauvegarder immédiatement
                    if db.insert_pump_token(token):
                        logger.info(f"     ✅ New pump.fun token created: {token.address}")
                        
                        # Enrichir les métadonnées en arrière-plan (optionnel)
                        # asyncio.create_task(self._enrich_token_metadata_async(token_address))
                        
                        return token
                    else:
                        logger.info(f"     ❌ Failed to save token to database")
                        
        except Exception as e:
            logger.error(f"     💥 Error processing token creation {transaction.signature}: {e}")
        
        return None
    
    def _extract_token_address_fast(self, instruction: Any, transaction: HeliusTransaction) -> Optional[str]:
        """
        Extraction rapide de l'adresse du token depuis les données de transaction
        """
        try:
            # Méthode 1: Depuis les comptes de l'instruction
            if len(instruction.accounts) > 0:
                # Le token mint est généralement dans les premiers comptes
                for account in instruction.accounts[:3]:
                    if len(account) >= 32:  # Adresse Solana valide
                        return account
            
            # Méthode 2: Depuis les données de compte si disponibles
            if hasattr(transaction, 'accountData') and transaction.accountData:
                for account_info in transaction.accountData:
                    account_addr = account_info.get('account', '')
                    if len(account_addr) >= 32:
                        return account_addr
            
            return None
            
        except Exception as e:
            logger.error(f"Error extracting token address: {e}")
            return None
    
    async def _process_token_purchase_optimized(self, transaction: HeliusTransaction) -> Optional[EarlyPurchase]:
        """
        Traite un achat de token pump.fun - VERSION CORRIGÉE pour pump.fun
        """
        try:
            logger.info(f"     🔍 Analyzing token transfers for purchase detection...")
            logger.info(f"     Token transfers count: {len(transaction.tokenTransfers)}")
            
            if not transaction.tokenTransfers:
                logger.info(f"     ❌ No token transfers found")
                return None
            
            # Log tous les transferts
            for i, transfer in enumerate(transaction.tokenTransfers):
                logger.info(f"     Transfer {i}: {transfer}")
            
            # CORRECTION: Pour pump.fun, si on a une instruction pump.fun ET un transfert de token,
            # alors c'est probablement un achat pump.fun, peu importe le nom du token
            
            pump_token_transfer = None
            
            for i, transfer in enumerate(transaction.tokenTransfers):
                amount = float(transfer.get('tokenAmount', 0))
                mint = transfer.get('mint', '')
                to_account = transfer.get('toUserAccount', '')
                
                logger.info(f"     Analyzing transfer {i}:")
                logger.info(f"       Mint: {mint}")
                logger.info(f"       Amount: {amount}")
                logger.info(f"       To: {to_account}")
                
                # Si on a une instruction pump.fun, alors tout transfert de token peut être un achat pump.fun
                if amount > 0 and to_account and len(mint) >= 32:
                    # Vérifier que ce n'est pas SOL
                    if mint != 'So11111111111111111111111111111111111111112':
                        logger.info(f"       ✅ Token transfer detected (likely pump.fun)")
                        pump_token_transfer = transfer
                        break
                else:
                    logger.info(f"       ❌ Invalid transfer data")
            
            if not pump_token_transfer:
                logger.info(f"     ❌ No valid token transfer found")
                return None
            
            # Extraction des données de l'achat pump.fun
            buyer_address = pump_token_transfer.get('toUserAccount')
            token_address = pump_token_transfer.get('mint')
            token_amount = float(pump_token_transfer.get('tokenAmount', 0))
            
            # Pour pump.fun, estimer le montant SOL depuis la fee ou utiliser une valeur par défaut
            estimated_sol_amount = transaction.fee / 1e9 if transaction.fee > 0 else 0.01  # Estimation minimale
            
            logger.info(f"     Extracted pump.fun purchase data:")
            logger.info(f"       Buyer: {buyer_address}")
            logger.info(f"       Token address: {token_address}")
            logger.info(f"       Token amount: {token_amount}")
            logger.info(f"       Estimated SOL: {estimated_sol_amount}")
            
            if not all([buyer_address, token_address, token_amount > 0]):
                logger.info(f"     ❌ Missing or invalid data")
                return None
            
            # Vérifier si le token existe, sinon le créer
            logger.info(f"     🔍 Checking if token exists in database...")
            token = db.get_token_by_address(token_address)
            if not token:
                logger.info(f"     ❌ Token not found, creating new token: {token_address}")
                # Créer le token automatiquement
                from models import PumpToken
                new_token = PumpToken(
                    address=token_address,
                    name=None,
                    symbol=None,
                    description=None,
                    creator=transaction.feePayer,
                    created_at=transaction.timestamp,
                    market_cap_discovery=None
                )
                
                if db.insert_pump_token(new_token):
                    logger.info(f"     ✅ New token created: {token_address}")
                    token = new_token
                else:
                    logger.info(f"     ❌ Failed to create token")
                    return None
            else:
                logger.info(f"     ✅ Token found: {token.address}")
            
            # Calcul du timing
            time_diff = transaction.timestamp - token.created_at
            minutes_after = int(time_diff.total_seconds() / 60)
            
            logger.info(f"     Timing analysis:")
            logger.info(f"       Transaction time: {transaction.timestamp}")
            logger.info(f"       Token created: {token.created_at}")
            logger.info(f"       Minutes after creation: {minutes_after}")
            
            # Pour le debug, on accepte même les achats tardifs pour l'instant
            if minutes_after < 0:
                # Le token a été créé après cette transaction, ce qui est normal
                # On va ajuster le timing
                minutes_after = 0
                logger.info(f"       ⚠️ Adjusted timing to 0 (token created after transaction)")
            
            # Création de l'achat
            purchase = EarlyPurchase(
                signature=transaction.signature,
                token_address=token_address,
                buyer_address=buyer_address,
                sol_amount=estimated_sol_amount,
                token_amount=token_amount,
                timestamp=transaction.timestamp,
                minutes_after_creation=minutes_after,
                market_cap_at_purchase=None
            )
            
            logger.info(f"     💾 Saving purchase to database...")
            
            # Sauvegarde
            if db.insert_early_purchase(purchase):
                logger.info(f"     ✅ Early purchase saved: {buyer_address[:20]}... -> {token.symbol or token_address[:20]}... ({minutes_after}min)")
                return purchase
            else:
                logger.info(f"     ❌ Failed to save purchase")
                return None
                
        except Exception as e:
            logger.error(f"     💥 Error processing token purchase {transaction.signature}: {e}")
            import traceback
            logger.error(f"     Traceback: {traceback.format_exc()}")
        
        return None
    
    async def _enrich_token_metadata_async(self, token_address: str):
        """
        Enrichit les métadonnées d'un token en arrière-plan
        """
        try:
            # Vérifier le cache
            if token_address in self.token_metadata_cache:
                return
            
            # Marquer comme en cours de traitement
            self.token_metadata_cache[token_address] = {"status": "processing"}
            
            # Récupérer les métadonnées (optionnel, coûte des crédits)
            metadata = await self._fetch_token_metadata(token_address)
            
            if metadata:
                # Mettre à jour en base
                token = db.get_token_by_address(token_address)
                if token:
                    token.name = metadata.get('name') or token.name
                    token.symbol = metadata.get('symbol') or token.symbol
                    token.description = metadata.get('description') or token.description
                    db.insert_pump_token(token)  # Upsert
                
                # Mettre en cache
                self.token_metadata_cache[token_address] = metadata
                
        except Exception as e:
            logger.error(f"Error enriching metadata for {token_address}: {e}")
            # Marquer comme erreur dans le cache
            self.token_metadata_cache[token_address] = {"status": "error"}
    
    async def _fetch_token_metadata(self, token_address: str) -> Optional[Dict[str, Any]]:
        """
        Récupère les métadonnées d'un token (utilise des crédits)
        """
        try:
            # Cette fonction est optionnelle et peut être désactivée pour économiser les crédits
            if not settings.enable_metadata_enrichment:
                return None
            
            url = f"{settings.helius_rpc_url}/?api-key={settings.helius_api_key}"
            
            payload = {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "getAsset",
                "params": {"id": token_address}
            }
            
            response = await self.httpx_client.post(url, json=payload)
            
            if response.status_code == 200:
                data = response.json()
                if 'result' in data:
                    result = data['result']
                    content = result.get('content', {})
                    metadata = content.get('metadata', {})
                    
                    return {
                        'name': metadata.get('name'),
                        'symbol': metadata.get('symbol'),
                        'description': metadata.get('description')
                    }
        except Exception as e:
            logger.error(f"Error fetching metadata for {token_address}: {e}")
        
        return None
    
    def _periodic_cache_cleanup(self):
        """Nettoyage périodique optimisé des caches"""
        self.cache_cleanup_counter += 1
        
        # Nettoyer toutes les 100 transactions
        if self.cache_cleanup_counter >= 100:
            self.cache_cleanup_counter = 0
            
            # Nettoyer le cache des signatures
            if len(self.processed_signatures) > 5000:
                # Garder les 3000 plus récents (approximation)
                signatures_list = list(self.processed_signatures)
                self.processed_signatures = set(signatures_list[-3000:])
                logger.info(f"Cleaned signature cache: {len(signatures_list)} -> {len(self.processed_signatures)}")
            
            # Nettoyer le cache des métadonnées
            if len(self.token_metadata_cache) > 1000:
                # Garder les 500 plus récents
                items = list(self.token_metadata_cache.items())
                self.token_metadata_cache = dict(items[-500:])
                logger.info(f"Cleaned metadata cache: {len(items)} -> {len(self.token_metadata_cache)}")
    
    def get_processing_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques de traitement"""
        now = datetime.now()
        uptime_seconds = (now - self.last_stats_reset).total_seconds()
        
        stats = dict(self.processing_stats)
        stats.update({
            'cache_sizes': {
                'processed_signatures': len(self.processed_signatures),
                'token_metadata': len(self.token_metadata_cache)
            },
            'uptime_seconds': uptime_seconds,
            'transactions_per_minute': (stats.get('total_processed', 0) / max(uptime_seconds / 60, 1)),
            'success_rate': (stats.get('total_processed', 0) - stats.get('errors', 0)) / max(stats.get('total_processed', 1), 1),
            'last_reset': self.last_stats_reset.isoformat()
        })
        
        return stats
    
    def reset_stats(self):
        """Remet à zéro les statistiques"""
        self.processing_stats.clear()
        self.last_stats_reset = datetime.now()
        logger.info("Processing stats reset")
    
    async def cleanup(self):
        """Nettoyage des ressources"""
        await self.httpx_client.aclose()
        logger.info("Data processor cleanup completed")

# Instance globale
processor = OptimizedPumpFunDataProcessor()