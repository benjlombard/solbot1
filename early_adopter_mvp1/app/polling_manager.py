import logging
import asyncio
import httpx
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Set
from collections import defaultdict
import json

from .models import HeliusTransaction, HeliusInstruction, PumpToken, EarlyPurchase
from .early_adopter_scorer import scorer
from .config import settings
from .database import db
from .pump_fun_client import PumpFunClient
from .rugcheck_client import RugCheckClient
from .sutils2 import get_pump_progress_correct
from .creator_analyzer import creator_analyzer
import aiohttp

logger = logging.getLogger(__name__)


class DataProcessor:
    async def process_helius_transaction(self, transaction: HeliusTransaction) -> Dict[str, Any]:
        result = {
            'processed': False,
            'token_created': None,
            'purchases': []
        }

        is_pump_fun_tx = any(
            inst.programId == settings.pumpfun_program_id for inst in transaction.instructions
        )

        if not is_pump_fun_tx:
            return result

        if self._is_token_creation(transaction):
            token_info = self._extract_token_info(transaction)
            if token_info:
                db.insert_pump_token(token_info)
                result['token_created'] = token_info
                result['processed'] = True
                await creator_analyzer.analyze_creator(token_info.creator)
        elif self._is_purchase(transaction):
            purchases = self._extract_purchase_info(transaction)
            for purchase in purchases:
                db.insert_early_purchase(purchase)
                result['purchases'].append(purchase)
            if purchases:
                result['processed'] = True
        
        return result

    def _is_token_creation(self, transaction: HeliusTransaction) -> bool:
        return not transaction.tokenTransfers

    def _extract_token_info(self, transaction: HeliusTransaction) -> PumpToken | None:
        try:
            token_address = transaction.instructions[0].accounts[0]
            creator = transaction.feePayer
            
            return PumpToken(
                address=token_address,
                name=None,
                symbol=None,
                description=None,
                creator=creator,
                created_at=transaction.timestamp,
                market_cap_discovery=0
            )
        except Exception as e:
            logger.error(f"Error extracting token info: {e}")
            return None

    def _is_purchase(self, transaction: HeliusTransaction) -> bool:
        return bool(transaction.tokenTransfers)

    def _extract_purchase_info(self, transaction: HeliusTransaction) -> List[EarlyPurchase]:
        purchases = []
        for transfer in transaction.tokenTransfers:
            try:
                if transfer.get('mint') == 'So11111111111111111111111111111111111111112':
                    continue

                buyer = transfer.get('toUserAccount')
                if not buyer:
                    continue
                
                sol_amount = 0
                if transaction.nativeTransfers:
                    for native_transfer in transaction.nativeTransfers:
                        # This logic is a guess, might need refinement
                        if native_transfer.get('toUserAccount') == settings.pumpfun_program_id:
                             sol_amount = native_transfer.get('amount', 0) / 1e9
                             break

                purchases.append(EarlyPurchase(
                    signature=transaction.signature,
                    token_address=transfer.get('mint'),
                    buyer_address=buyer,
                    sol_amount=sol_amount,
                    token_amount=float(transfer.get('tokenAmount', 0)),
                    timestamp=transaction.timestamp,
                    minutes_after_creation=0
                ))
            except Exception as e:
                logger.error(f"Error extracting purchase info from transfer: {e}")
        return purchases


class IntelligentPollingManager:
    def __init__(self, system_monitor: 'SystemMonitor'):
        self.system_monitor = system_monitor
        self.helius_api_key = settings.helius_api_key
        self.helius_rpc_url = "https://mainnet.helius-rpc.com"
        self.pumpfun_program_id = settings.pumpfun_program_id
        
        self.httpx_client = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0))
        self.pump_fun_client = PumpFunClient(logger_instance=logger, system_monitor=self.system_monitor)
        self.rugcheck_client = RugCheckClient(logger=logger, system_monitor=self.system_monitor)
        self.data_processor = DataProcessor()
        self.polling_task = None
        self.is_running = False
        
        # Timer for enrichment task
        self.last_enrichment_run = datetime.now() - timedelta(minutes=10) # Run on first loop
        
        # Cache pour éviter les doublons
        self.processed_signatures: Set[str] = set()
        self.last_signature_cleanup = datetime.now()
        
        # Statistiques
        self.daily_stats = defaultdict(int)
        self.last_reset_date = datetime.now().date()
        self.credits_used_today = 0
        
        # Paramètres de polling adaptatif
        self.base_polling_interval = settings.base_polling_interval_seconds
        self.min_polling_interval = settings.min_polling_interval_seconds
        self.max_polling_interval = settings.max_polling_interval_seconds
        self.current_polling_interval = self.base_polling_interval
        
        # Historique pour polling adaptatif
        self.recent_activity_levels = []
        self.last_activity_time = datetime.now()
        
        # Surveillance de la santé de l'API
        self.consecutive_failures = 0
        self.last_successful_poll = datetime.now()
        self.api_health_status = "unknown"
        
        # Détection pump.fun pour workaround v0 transactions
        self._last_detected_pumpfun = False
    
    def start_polling(self):
        """Démarre le polling intelligent"""
        if not self.polling_task or self.polling_task.done():
            self.is_running = True
            self.polling_task = asyncio.create_task(self._polling_loop())
            logger.info("Intelligent polling started")
    
    async def _polling_loop(self):
        """Boucle principale de polling avec gestion d'erreurs robuste"""
        logger.info("Starting intelligent polling loop")
        
        while self.is_running:
            try:
                # Vérifier et réinitialiser les stats quotidiennes
                self._check_daily_reset()
                
                # Vérifier les limites de crédits
                if self.system_monitor.get_helius_credits_today() >= settings.max_daily_credits * 0.95:
                    logger.warning("Credit limit nearly reached, pausing polling")
                    await asyncio.sleep(3600)  # Attendre 1h
                    continue
                
                # Vérifier la santé de l'API avant de continuer
                if self.consecutive_failures >= 3:
                    logger.warning(f"API health degraded ({self.consecutive_failures} failures), extending polling interval")
                    self.current_polling_interval = min(self.current_polling_interval * 1.5, self.max_polling_interval * 2)
                
                # Exécuter un cycle de polling
                success = await self._poll_recent_transactions_safe()
                
                if success:
                    self.consecutive_failures = 0
                    self.last_successful_poll = datetime.now()
                    self.api_health_status = "healthy"
                else:
                    self.consecutive_failures += 1
                    self.api_health_status = "degraded" if self.consecutive_failures < 5 else "critical"
                
                # Nettoyer le cache périodiquement
                await self._cleanup_cache()

                # Exécuter l'enrichissement des métadonnées périodiquement
                if settings.enable_metadata_enrichment and (datetime.now() - self.last_enrichment_run).total_seconds() > settings.enrichment_interval_seconds:
                    await self._enrich_token_metadata()
                
                # Adapter l'intervalle de polling
                self._adapt_polling_interval()
                
                # Attendre avant le prochain cycle avec backoff si nécessaire
                wait_time = self.current_polling_interval
                if self.consecutive_failures > 0:
                    wait_time = min(wait_time * (1 + self.consecutive_failures * 0.5), 1800)  # Max 30 min
                
                logger.debug(f"Waiting {wait_time}s before next poll (failures: {self.consecutive_failures})")
                await asyncio.sleep(wait_time)
                
            except Exception as e:
                logger.error(f"Error in polling loop: {e}")
                self.consecutive_failures += 1
                await asyncio.sleep(60)  # Attendre 1 minute en cas d'erreur
    
    async def _poll_recent_transactions_safe(self) -> bool:
        """Version sécurisée du polling avec gestion d'erreurs"""
        try:
            await self._poll_recent_transactions()
            return True
        except Exception as e:
            logger.error(f"Error in polling cycle: {e}")
            return False
    
    async def _poll_recent_transactions(self):
        """Récupère et traite les transactions récentes avec debug amélioré"""
        try:
            # Calculer la période à scanner (dernières X minutes)
            lookback_minutes = max(self.current_polling_interval / 60 * 1.2, 3)  # 20% de marge
            since_time = datetime.now() - timedelta(minutes=lookback_minutes)
            
            logger.info(f"Polling transactions since {since_time.isoformat()} (lookback: {lookback_minutes:.1f}min)")
            
            # Récupérer les transactions pump.fun récentes
            transactions = await self._get_recent_pumpfun_transactions(since_time)
            
            if not transactions:
                logger.debug("No new pump.fun transactions found")
                self.recent_activity_levels.append(0)
                return
            
            # Filtrer les doublons avec debug
            new_transactions = []
            for tx in transactions:
                if tx.signature not in self.processed_signatures:
                    new_transactions.append(tx)
                    self.processed_signatures.add(tx.signature)
                else:
                    logger.debug(f"Duplicate transaction filtered: {tx.signature[:20]}...")
            
            if not new_transactions:
                logger.info(f"Found {len(transactions)} transactions but all already processed")
                self.recent_activity_levels.append(0)
                return
            
            logger.info(f"Processing {len(new_transactions)} new transactions")
            
            # Debug: analyser les transactions
            pumpfun_count = 0
            for tx in new_transactions:
                has_pumpfun = any(inst.programId == self.pumpfun_program_id for inst in tx.instructions)
                if has_pumpfun:
                    pumpfun_count += 1
                    logger.info(f"🎯 Pump.fun transaction: {tx.signature[:20]}... - Type: {tx.type}")
            
            logger.info(f"📊 Transactions with pump.fun instructions: {pumpfun_count}/{len(new_transactions)}")
            
            self.recent_activity_levels.append(len(new_transactions))
            self.last_activity_time = datetime.now()
            
            # Traiter les transactions par lots
            await self._process_transaction_batch(new_transactions)
            
            # Mettre à jour les statistiques
            self._update_daily_stats(len(new_transactions))
            
        except Exception as e:
            logger.error(f"Error polling recent transactions: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
    
    async def _get_recent_pumpfun_transactions(self, since_time: datetime) -> List[HeliusTransaction]:
        """
        Récupère les transactions pump.fun récentes avec retry et logging détaillé
        """
        max_retries = 3
        retry_delay = 5  # secondes
        
        for attempt in range(max_retries):
            try:
                logger.info(f"🔍 Attempt {attempt + 1}/{max_retries} to fetch pump.fun transactions")
                
                # OPTIMISATION: Un seul appel par polling cycle
                url = f"{self.helius_rpc_url}/?api-key={self.helius_api_key}"
                
                payload = {
                    "jsonrpc": "2.0",
                    "id": "1",
                    "method": "getSignaturesForAddress",
                    "params": [
                        self.pumpfun_program_id,
                        {
                            "limit": 20,  # RÉDUIT de 100 à 20 pour économiser
                            "commitment": "confirmed"
                        }
                    ]
                }
                
                logger.info(f"📤 Sending request to Helius:")
                logger.info(f"   URL: {url}")
                logger.info(f"   Payload: {json.dumps(payload, indent=2)}")
                
                # Utiliser un timeout plus court et retry
                async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=10.0)) as client:
                    response = await client.post(url, json=payload)
                    
                    logger.info(f"📥 Response from Helius:")
                    logger.info(f"   Status: {response.status_code}")
                    logger.info(f"   Headers: {dict(response.headers)}")
                    
                    response.raise_for_status()
                
                data = response.json()
                logger.info(f"📋 Response data:")
                logger.info(f"   Raw response: {json.dumps(data, indent=2)}")
                
                if 'error' in data:
                    logger.error(f"❌ Helius API error: {data['error']}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        continue
                    return []
                
                if 'result' not in data:
                    logger.warning(f"⚠️ No 'result' field in response")
                    return []
                
                if not data['result']:
                    logger.info(f"ℹ️ Empty result - no signatures found for pump.fun program")
                    return []
                
                signatures = data['result']
                logger.info(f"📊 Found {len(signatures)} signatures for pump.fun program")
                
                # Log détails des signatures
                for i, sig_info in enumerate(signatures[:3]):  # Log les 3 premières
                    logger.info(f"   Signature {i+1}: {json.dumps(sig_info, indent=4)}")
                
                # OPTIMISATION: Traiter seulement les 5 plus récentes
                recent_signatures = signatures[:5]  # RÉDUIT drastiquement
                transactions = []
                
                # OPTIMISATION: Récupérer les détails
                if recent_signatures:
                    recent_sigs = []
                    for sig_info in recent_signatures:
                        signature = sig_info['signature']
                        block_time = sig_info.get('blockTime')
                        
                        logger.info(f"🔍 Processing signature: {signature}")
                        logger.info(f"   Block time: {block_time}")
                        
                        if not block_time:
                            logger.warning(f"   ⚠️ No block time for signature {signature[:20]}...")
                            continue
                        
                        # Vérifier si la transaction est dans la fenêtre de temps
                        tx_time = datetime.fromtimestamp(block_time)
                        time_diff = datetime.now() - tx_time
                        
                        logger.info(f"   Transaction time: {tx_time.isoformat()}")
                        logger.info(f"   Time diff: {time_diff.total_seconds():.1f} seconds ago")
                        logger.info(f"   Since time: {since_time.isoformat()}")
                        logger.info(f"   In window: {tx_time >= since_time}")
                        
                        if tx_time >= since_time:
                            recent_sigs.append(signature)
                            logger.info(f"   ✅ Added to recent signatures")
                        else:
                            logger.info(f"   ❌ Too old, skipped")
                    
                    logger.info(f"📈 Processing {len(recent_sigs)} recent signatures")
                    
                    # Récupérer les détails des transactions récentes (max 3)
                    for signature in recent_sigs[:3]:  # LIMITE à 3 max
                        logger.info(f"🔍 Fetching transaction details for: {signature[:20]}...")
                        tx_detail = await self._get_transaction_details_with_retry(signature, max_retries=2)
                        if tx_detail:
                            logger.info(f"   ✅ Transaction details retrieved")
                            transactions.append(tx_detail)
                        else:
                            logger.warning(f"   ❌ Failed to get transaction details")
                
                # Record Helius API calls
                self.system_monitor.record_helius_call('getSignaturesForAddress', 10)
                if transactions:
                    self.system_monitor.record_helius_call('getTransaction', 10 * len(transactions))

                logger.info(f"✅ Retrieved {len(transactions)} pump.fun transactions")
                
                return transactions
                
            except httpx.TimeoutException as e:
                logger.warning(f"⏱️ Timeout on attempt {attempt + 1}/{max_retries}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                else:
                    logger.error("❌ All retry attempts failed due to timeout")
                    return []
                    
            except httpx.ConnectError as e:
                logger.warning(f"🔌 Connection error on attempt {attempt + 1}/{max_retries}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                else:
                    logger.error("❌ All retry attempts failed due to connection error")
                    return []
                    
            except httpx.HTTPError as e:
                logger.error(f"🌐 HTTP error fetching transactions: {e}")
                logger.error(f"   Response content: {getattr(e.response, 'text', 'No response content') if hasattr(e, 'response') else 'No response'}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                else:
                    return []
                    
            except Exception as e:
                logger.error(f"💥 Unexpected error fetching transactions: {e}")
                logger.error(f"   Exception type: {type(e).__name__}")
                import traceback
                logger.error(f"   Traceback: {traceback.format_exc()}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                else:
                    return []
        
        return []
    
    async def _get_transaction_details_with_retry(self, signature: str, max_retries: int = 2) -> Optional[HeliusTransaction]:
        """Récupère les détails d'une transaction avec retry et logging détaillé"""
        for attempt in range(max_retries):
            try:
                logger.info(f"📄 Getting transaction details - attempt {attempt + 1}/{max_retries}")
                
                url = f"{self.helius_rpc_url}/?api-key={self.helius_api_key}"
                
                payload = {
                    "jsonrpc": "2.0",
                    "id": "1",
                    "method": "getTransaction",
                    "params": [
                        signature,
                        {
                            "encoding": "json",
                            "maxSupportedTransactionVersion": 0,
                            "commitment": "confirmed"
                        }
                    ]
                }
                
                logger.info(f"📤 Sending getTransaction request:")
                logger.info(f"   Signature: {signature}")
                logger.info(f"   Payload: {json.dumps(payload, indent=2)}")
                
                async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
                    response = await client.post(url, json=payload)
                    
                    logger.info(f"📥 getTransaction response:")
                    logger.info(f"   Status: {response.status_code}")
                    
                    response.raise_for_status()
                
                data = response.json()
                logger.info(f"📋 Transaction details response:")
                logger.info(f"   Has result: {'result' in data}")
                logger.info(f"   Has error: {'error' in data}")
                
                if 'error' in data:
                    logger.error(f"   Error: {data['error']}")
                    return None
                
                if not data.get('result'):
                    logger.warning(f"   ⚠️ No result for transaction {signature[:20]}...")
                    return None
                
                result = data['result']
                logger.info(f"   Transaction exists: {result is not None}")
                
                if result:
                    # Log structure de la transaction
                    logger.info(f"   Transaction structure:")
                    logger.info(f"     - signature: {result.get('signature', 'N/A')}")
                    logger.info(f"     - slot: {result.get('slot', 'N/A')}")
                    logger.info(f"     - blockTime: {result.get('blockTime', 'N/A')}")
                    logger.info(f"     - has transaction: {'transaction' in result}")
                    
                    if 'transaction' in result:
                        tx_data = result['transaction']
                        logger.info(f"     - has message: {'message' in tx_data}")
                        
                        if 'message' in tx_data:
                            message = tx_data['message']
                            logger.info(f"       - accountKeys count: {len(message.get('accountKeys', []))}")
                            logger.info(f"       - instructions count: {len(message.get('instructions', []))}")
                            
                            # Log les premiers account keys
                            account_keys = message.get('accountKeys', [])
                            for i, key in enumerate(account_keys[:5]):  # Premier 5
                                logger.info(f"         Account {i}: {key}")
                            
                            # Log les instructions
                            instructions = message.get('instructions', [])
                            for i, inst in enumerate(instructions):
                                program_id_index = inst.get('programIdIndex')
                                program_id = account_keys[program_id_index] if program_id_index < len(account_keys) else 'Unknown'
                                logger.info(f"         Instruction {i}: program={program_id} (index={program_id_index})")
                                logger.info(f"           accounts: {inst.get('accounts', [])}")
                                logger.info(f"           data length: {len(inst.get('data', ''))}")
                                
                                # Marquer si c'est pump.fun
                                if program_id == self.pumpfun_program_id:
                                    logger.info(f"           🎯 PUMP.FUN INSTRUCTION DETECTED!")
                
                # Parser la transaction
                parsed_tx = self._parse_helius_transaction(result)
                
                if parsed_tx:
                    logger.info(f"   ✅ Transaction parsed successfully")
                    logger.info(f"     - Type: {parsed_tx.type}")
                    logger.info(f"     - Instructions: {len(parsed_tx.instructions)}")
                    logger.info(f"     - Token transfers: {len(parsed_tx.tokenTransfers)}")
                    
                    # Compter les instructions pump.fun
                    pumpfun_instructions = sum(1 for inst in parsed_tx.instructions if inst.programId == self.pumpfun_program_id)
                    logger.info(f"     - Pump.fun instructions: {pumpfun_instructions}")
                    
                    return parsed_tx
                else:
                    logger.warning(f"   ❌ Failed to parse transaction")
                    return None
                
            except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError) as e:
                logger.warning(f"🔌 Error getting transaction {signature[:20]}... attempt {attempt + 1}/{max_retries}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
                    continue
                else:
                    logger.error(f"❌ Failed to get transaction {signature[:20]}... after {max_retries} attempts")
                    return None
                    
            except Exception as e:
                logger.error(f"💥 Unexpected error getting transaction {signature[:20]}...: {e}")
                import traceback
                logger.error(f"   Traceback: {traceback.format_exc()}")
                return None
        
        return None
    
    async def _get_transaction_details(self, signature: str) -> Optional[HeliusTransaction]:
        """Récupère les détails d'une transaction"""
        try:
            url = f"{self.helius_rpc_url}/?api-key={self.helius_api_key}"
            
            payload = {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "getTransaction",
                "params": [
                    signature,
                    {
                        "encoding": "json",
                        "maxSupportedTransactionVersion": 0,
                        "commitment": "confirmed"
                    }
                ]
            }
            
            response = await self.httpx_client.post(url, json=payload)
            response.raise_for_status()
            
            data = response.json()
            
            if 'error' in data or not data.get('result'):
                return None
            
            # Parser la transaction
            return self._parse_helius_transaction(data['result'])
            
        except Exception as e:
            logger.error(f"Error getting transaction details for {signature}: {e}")
            return None
    
    def _parse_helius_transaction(self, tx_data: Dict[str, Any]) -> Optional[HeliusTransaction]:
        """Parse une transaction depuis les données Helius - CORRECTION INDEX COMPTES"""
        try:
            # Vérifier les champs requis
            if not all(key in tx_data for key in ['slot']):
                logger.error(f"Missing required fields in transaction data")
                return None
            
            # Récupérer le timestamp avec gestion des timestamps futurs
            block_time = tx_data.get('blockTime')
            timestamp = datetime.now()  # Toujours utiliser le timestamp actuel
            
            # Récupérer la signature
            signature = tx_data.get('signature', '')
            if not signature:
                tx_inner = tx_data.get('transaction', {})
                signatures = tx_inner.get('signatures', [])
                if signatures:
                    signature = signatures[0]
                else:
                    signature = f"unknown_{tx_data.get('slot', 'nosig')}"
            
            # Parser les instructions avec la bonne structure
            instructions = []
            transaction_data = tx_data.get('transaction', {})
            message = transaction_data.get('message', {})
            
            # Récupérer les comptes et instructions
            account_keys = message.get('accountKeys', [])
            raw_instructions = message.get('instructions', [])
            
            logger.debug(f"Parsing transaction: {len(account_keys)} accounts, {len(raw_instructions)} instructions")
            
            # CORRECTION: Gérer l'expansion des comptes avec addressTableLookups
            expanded_account_keys = account_keys.copy()
            
            # Vérifier s'il y a des address table lookups (v0 transactions)
            address_table_lookups = message.get('addressTableLookups', [])
            if address_table_lookups:
                logger.info(f"Found {len(address_table_lookups)} address table lookups - expanding account keys")
                # Pour l'instant, on va juste noter qu'il y en a
                # Dans un vrai système, il faudrait résoudre ces lookups
            
            for inst_idx, inst_data in enumerate(raw_instructions):
                try:
                    # Récupérer l'index du programme
                    program_id_index = inst_data.get('programIdIndex')
                    if program_id_index is None:
                        logger.warning(f"Instruction {inst_idx}: no programIdIndex")
                        continue
                    
                    # CORRECTION: Vérifier l'index ET essayer de récupérer depuis stackHeight si nécessaire
                    program_id = None
                    if program_id_index < len(account_keys):
                        program_id = account_keys[program_id_index]
                    else:
                        # L'index dépasse les comptes de base, probablement une v0 transaction
                        # Pour l'instant, on va ignorer ces instructions
                        logger.warning(f"Instruction {inst_idx}: programIdIndex {program_id_index} >= {len(account_keys)} (v0 transaction?)")
                        
                        # WORKAROUND: Si on a vu du pump.fun dans les logs précédents, on va créer une instruction factice
                        if hasattr(self, '_last_detected_pumpfun') and self._last_detected_pumpfun:
                            program_id = self.pumpfun_program_id
                            logger.info(f"Using pump.fun program ID from previous detection")
                        else:
                            continue
                    
                    # Récupérer les comptes de l'instruction (avec validation)
                    account_indexes = inst_data.get('accounts', [])
                    instruction_accounts = []
                    for idx in account_indexes:
                        if idx < len(account_keys):
                            instruction_accounts.append(account_keys[idx])
                        # Ignorer silencieusement les index invalides pour les v0 transactions
                    
                    # Créer l'instruction
                    instruction = HeliusInstruction(
                        accounts=instruction_accounts,
                        data=inst_data.get('data', ''),
                        innerInstructions=[],
                        programId=program_id
                    )
                    instructions.append(instruction)
                    
                    # Log et mémoriser si c'est pump.fun
                    if program_id == self.pumpfun_program_id:
                        logger.info(f"✅ Pump.fun instruction successfully parsed in instruction {inst_idx}!")
                        self._last_detected_pumpfun = True
                    
                except Exception as e:
                    logger.error(f"Error parsing instruction {inst_idx}: {e}")
                    continue
            
            # Parser les transferts de tokens depuis meta
            token_transfers = []
            meta = tx_data.get('meta', {})
            
            if meta:
                # Analyser les changements de balances pour détecter les transferts
                pre_token_balances = meta.get('preTokenBalances', [])
                post_token_balances = meta.get('postTokenBalances', [])
                
                # Créer des transferts simplifiés basés sur les changements de balance
                for post_balance in post_token_balances:
                    mint = post_balance.get('mint')
                    owner = post_balance.get('owner')
                    ui_amount = post_balance.get('uiTokenAmount', {})
                    amount = ui_amount.get('amount', '0')
                    
                    if mint and owner and amount != '0':
                        token_transfers.append({
                            'mint': mint,
                            'toUserAccount': owner,
                            'tokenAmount': amount,
                            'fromUserAccount': None
                        })
            
            # Déterminer le fee payer
            fee_payer = transaction_data.get('feePayer', '')
            if not fee_payer and account_keys:
                fee_payer = account_keys[0]
            
            # Créer l'objet transaction
            transaction = HeliusTransaction(
                signature=signature,
                slot=tx_data.get('slot', 0),
                timestamp=timestamp,
                type=self._determine_transaction_type(instructions, token_transfers),
                source='helius',
                fee=meta.get('fee', 0),
                feePayer=fee_payer,
                instructions=instructions,
                nativeTransfers=[],
                tokenTransfers=token_transfers,
                accountData=[]
            )
            
            # Compter les instructions pump.fun pour vérification
            pumpfun_count = sum(1 for inst in instructions if inst.programId == self.pumpfun_program_id)
            
            logger.info(f"✅ Transaction parsed: {len(instructions)} instructions, {len(token_transfers)} transfers")
            logger.info(f"   Pump.fun instructions in final transaction: {pumpfun_count}")
            
            return transaction
            
        except Exception as e:
            logger.error(f"💥 Error parsing transaction: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None
    
    def _determine_transaction_type(self, instructions: List, token_transfers: List) -> str:
        """Détermine le type de transaction"""
        # Si il y a des instructions pump.fun et des transferts de tokens, c'est probablement un SWAP
        has_pumpfun = any(inst.programId == self.pumpfun_program_id for inst in instructions)
        has_transfers = len(token_transfers) > 0
        
        if has_pumpfun:
            if has_transfers:
                return "SWAP"
            else:
                return "UNKNOWN"  # Possible création de token
        
        return "UNKNOWN"
    
    async def _process_transaction_batch(self, transactions: List[HeliusTransaction]):
        """Traite un lot de transactions"""
        logger.info(f"Processing batch of {len(transactions)} transactions")
        
        tokens_created = 0
        purchases_detected = 0
        
        for transaction in transactions:
            try:
                # Filtrer les micro-transactions pour économiser le traitement
                if not self._is_transaction_worth_processing(transaction):
                    continue
                
                # Traiter la transaction
                result = await self.data_processor.process_helius_transaction(transaction)
                
                if result['processed']:
                    if result['token_created']:
                        tokens_created += 1
                        logger.info(f"New token created: {result['token_created'].address}")
                    
                    purchases_detected += len(result['purchases'])
                    
                    if result['purchases']:
                        logger.info(f"Early purchases detected: {len(result['purchases'])}")
                
            except Exception as e:
                logger.error(f"Error processing transaction {transaction.signature}: {e}")
        
        # Logs de résumé
        if tokens_created > 0 or purchases_detected > 0:
            logger.info(f"Batch processed: {tokens_created} tokens created, {purchases_detected} purchases detected")
        
        # Déclencher la mise à jour des scores si nécessaire
        if purchases_detected > 0:
            asyncio.create_task(self._trigger_scoring_update())
    
    def _is_transaction_worth_processing(self, transaction: HeliusTransaction) -> bool:
        """Détermine si une transaction mérite d'être traitée (optimisation)"""
        # Vérifier s'il y a des transferts significatifs
        if transaction.tokenTransfers:
            for transfer in transaction.tokenTransfers:
                amount = float(transfer.get('tokenAmount', 0))
                if amount >= settings.min_sol_amount_filter:
                    return True
        
        # Vérifier s'il y a des transferts natifs significatifs
        if transaction.nativeTransfers:
            for transfer in transaction.nativeTransfers:
                amount = transfer.get('amount', 0)
                if amount >= settings.min_sol_amount_filter * 1e9:  # Conversion lamports
                    return True
        
        # Toujours traiter les transactions UNKNOWN (potentielles créations de tokens)
        if transaction.type == "UNKNOWN":
            return True
        
        return False
    
    async def _trigger_scoring_update(self):
        """Déclenche une mise à jour du scoring des early adopters"""
        try:
            await scorer.update_all_early_adopters()
            logger.info("Early adopter scoring updated")
        except Exception as e:
            logger.error(f"Error updating early adopter scores: {e}")
    
    def _adapt_polling_interval(self):
        """Adapte l'intervalle de polling selon l'activité"""
        # Garder seulement les 10 dernières mesures
        if len(self.recent_activity_levels) > 10:
            self.recent_activity_levels = self.recent_activity_levels[-10:]
        
        if not self.recent_activity_levels:
            return
        
        # Calculer l'activité moyenne récente
        avg_activity = sum(self.recent_activity_levels) / len(self.recent_activity_levels)
        
        # Adapter l'intervalle selon l'activité
        if avg_activity > 50:  # Haute activité
            self.current_polling_interval = self.min_polling_interval
        elif avg_activity > 20:  # Activité moyenne
            self.current_polling_interval = self.base_polling_interval
        elif avg_activity > 5:   # Faible activité
            self.current_polling_interval = min(self.base_polling_interval * 1.5, self.max_polling_interval)
        else:  # Très faible activité
            self.current_polling_interval = self.max_polling_interval
        
        # Log les changements significatifs
        if abs(self.current_polling_interval - self.base_polling_interval) > 30:
            logger.info(f"Polling interval adapted to {self.current_polling_interval}s (avg activity: {avg_activity:.1f})")
    
    async def _cleanup_cache(self):
        """Nettoie le cache des signatures traitées"""
        now = datetime.now()
        
        # Nettoyer toutes les heures
        if (now - self.last_signature_cleanup).total_seconds() > 3600:
            # Garder seulement les signatures des 6 dernières heures
            if len(self.processed_signatures) > 5000:
                logger.info(f"Cleaning signature cache: {len(self.processed_signatures)} -> limiting to recent ones")
                # Pour simplifier, on vide complètement le cache
                # Dans un vrai système, on utiliserait un cache avec TTL
                self.processed_signatures.clear()
            
            self.last_signature_cleanup = now
    
    def _check_daily_reset(self):
        """Vérifie et réinitialise les stats quotidiennes"""
        current_date = datetime.now().date()
        
        if current_date != self.last_reset_date:
            self.daily_stats.clear()
            self.credits_used_today = 0
            self.last_reset_date = current_date
            logger.info("Daily stats reset")
    
    def _update_daily_stats(self, transaction_count: int):
        """Met à jour les statistiques quotidiennes"""
        self.daily_stats['transactions_processed'] += transaction_count
        self.daily_stats['polling_cycles'] += 1
        
        # Alerte si proche de la limite
        if self.credits_used_today > settings.max_daily_credits * 0.8:
            logger.warning(f"High credit usage: {self.credits_used_today}/{settings.max_daily_credits}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques du polling avec santé API"""
        return {
            'is_running': self.is_running,
            'current_polling_interval': self.current_polling_interval,
            'credits_used_today': self.credits_used_today,
            'max_daily_credits': settings.max_daily_credits,
            'daily_stats': dict(self.daily_stats),
            'cache_size': len(self.processed_signatures),
            'recent_activity_avg': sum(self.recent_activity_levels[-5:]) / min(len(self.recent_activity_levels), 5) if self.recent_activity_levels else 0,
            'last_activity_time': self.last_activity_time.isoformat(),
            'last_reset_date': self.last_reset_date.isoformat(),
            'api_health': {
                'status': self.api_health_status,
                'consecutive_failures': self.consecutive_failures,
                'last_successful_poll': self.last_successful_poll.isoformat(),
                'time_since_success_minutes': (datetime.now() - self.last_successful_poll).total_seconds() / 60
            }
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Vérifie la santé du système de polling"""
        health = {
            'status': 'healthy',
            'issues': []
        }
        
        # Vérifier si le polling tourne
        if not self.is_running or not self.polling_task or self.polling_task.done():
            health['issues'].append("Polling not running")
            health['status'] = 'degraded'
        
        # Vérifier l'utilisation des crédits
        credit_usage_pct = (self.credits_used_today / settings.max_daily_credits) * 100
        if credit_usage_pct > 90:
            health['issues'].append(f"Credit usage critical: {credit_usage_pct:.1f}%")
            health['status'] = 'warning'
        
        # Vérifier la dernière activité
        time_since_activity = (datetime.now() - self.last_activity_time).total_seconds()
        if time_since_activity > 1800:  # Plus de 30 minutes
            health['issues'].append(f"No activity for {time_since_activity/60:.1f} minutes")
            if health['status'] == 'healthy':
                health['status'] = 'warning'
        
        health['credit_usage_percent'] = credit_usage_pct
        health['time_since_last_activity_minutes'] = time_since_activity / 60
        health['polling_interval'] = self.current_polling_interval
        
        return health
    
    async def force_poll_now(self) -> Dict[str, Any]:
        """Force un polling immédiat (pour debug/test)"""
        try:
            logger.info("Force polling triggered")
            await self._poll_recent_transactions()
            return {
                'status': 'success',
                'message': 'Force polling completed',
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error in force polling: {e}")
            return {
                'status': 'error',
                'message': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    async def shutdown(self):
        """Arrêt propre du polling"""
        self.is_running = False
        
        if self.polling_task and not self.polling_task.done():
            self.polling_task.cancel()
            try:
                await self.polling_task
            except asyncio.CancelledError:
                pass
        
        await self.httpx_client.aclose()
        logger.info("Polling manager shutdown complete")

    async def _enrich_token_metadata(self):
        """
        Version corrigée de l'enrichissement des métadonnées
        """
        logger.info("Starting token metadata enrichment task...")
        self.last_enrichment_run = datetime.now()
        
        try:
            # Récupérer les tokens à enrichir
            token_addresses_to_enrich = db.get_tokens_to_enrich(
                limit=settings.enrichment_batch_size,
                update_interval_minutes=settings.enrichment_update_interval_minutes
            )
            
            if not token_addresses_to_enrich:
                logger.info("No tokens require metadata enrichment at this time.")
                return

            logger.info(f"Found {len(token_addresses_to_enrich)} tokens to enrich.")
            
            # Traiter par lots plus petits pour éviter les timeouts
            batch_size = 5
            updated_count = 0
            
            for i in range(0, len(token_addresses_to_enrich), batch_size):
                batch = token_addresses_to_enrich[i:i + batch_size]
                logger.info(f"Processing batch {i//batch_size + 1}: {len(batch)} tokens")
                
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                    # Tâches parallèles pour ce batch
                    tasks = []
                    
                    for token_address in batch:
                        # Récupérer les données du token depuis la DB
                        token_obj = db.get_token_by_address(token_address)
                        if not token_obj:
                            continue
                        
                        # Ajouter les tâches
                        tasks.extend([
                            self._enrich_single_token_pumpfun(session, token_address),
                            self._enrich_single_token_onchain(token_address, token_obj),
                            self._enrich_single_token_rugcheck(session, token_address)
                        ])
                    
                    # Exécuter toutes les tâches
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # Traiter les résultats par groups de 3 (pumpfun, onchain, rugcheck)
                    for j, token_address in enumerate(batch):
                        try:
                            base_idx = j * 3
                            
                            pumpfun_data = results[base_idx] if base_idx < len(results) else {}
                            onchain_data = results[base_idx + 1] if base_idx + 1 < len(results) else {}
                            rugcheck_data = results[base_idx + 2] if base_idx + 2 < len(results) else None
                            
                            # Assurer la cohérence des données
                            if not isinstance(pumpfun_data, dict):
                                pumpfun_data = {}
                            if not isinstance(onchain_data, dict):
                                onchain_data = {}
                            
                            # Merger les données on-chain dans pumpfun_data
                            if onchain_data.get('success'):
                                pumpfun_data['bonding_curve_progress'] = onchain_data.get('bonding_curve_progress', 0)
                                pumpfun_data['virtual_sol_reserves'] = onchain_data.get('virtual_sol_reserves', 0)
                                pumpfun_data['virtual_token_reserves'] = onchain_data.get('virtual_token_reserves', 0)
                            
                            # Créer snapshot avant mise à jour
                            db.create_snapshot(token_address)
                            
                            # Mettre à jour les données si on a quelque chose
                            update_success = False
                            
                            if pumpfun_data:
                                # S'assurer qu'on a au moins le progrès de bonding curve
                                if 'bonding_curve_progress' not in pumpfun_data or pumpfun_data['bonding_curve_progress'] is None:
                                    # Essayer de récupérer depuis l'API pump.fun directement
                                    try:
                                        async with session.get(
                                            f"https://frontend-api-v3.pump.fun/coins/{token_address}",
                                            timeout=10
                                        ) as resp:
                                            if resp.status == 200:
                                                api_data = await resp.json()
                                                if 'bonding_curve_progress' in api_data:
                                                    pumpfun_data['bonding_curve_progress'] = api_data['bonding_curve_progress']
                                                    logger.info(f"Got bonding progress from API: {api_data['bonding_curve_progress']}")
                                    except Exception as e:
                                        logger.warning(f"Failed to get progress from API for {token_address}: {e}")
                                
                                update_success = db.update_token_pumpfun_data(token_address, pumpfun_data)
                                if update_success:
                                    updated_count += 1
                                    logger.info(f"Updated {token_address} with progress: {pumpfun_data.get('bonding_curve_progress', 'N/A')}")
                            
                            # Mettre à jour rugcheck séparément
                            if rugcheck_data and isinstance(rugcheck_data, dict):
                                db.upsert_rugcheck_report(token_address, rugcheck_data)
                            
                        except Exception as e:
                            logger.error(f"Error processing results for {token_address}: {e}")
                    
                    # Pause entre les batches
                    await asyncio.sleep(2)
            
            logger.info(f"Enrichment task complete. Updated {updated_count}/{len(token_addresses_to_enrich)} tokens.")
            
            # Log des statistiques
            self._log_enrichment_stats()
            
        except Exception as e:
            logger.error(f"An error occurred during the enrichment task: {e}", exc_info=True)

    async def _enrich_single_token_pumpfun(self, session: aiohttp.ClientSession, token_address: str) -> Dict:
        """
        Enrichit un token avec les données Pump.fun
        """
        try:
            return await self.pump_fun_client.get_token_data(session, token_address) or {}
        except Exception as e:
            logger.error(f"Error getting pump.fun data for {token_address}: {e}")
            return {}

    async def _enrich_single_token_onchain(self, token_address: str, token_obj) -> Dict:
        """
        Enrichit un token avec les données on-chain
        """
        try:
            from .sutils2 import get_pump_progress_correct
            
            return await get_pump_progress_correct(
                token_address,
                getattr(token_obj, 'bonding_curve', None),
                getattr(token_obj, 'associated_bonding_curve', None),
                self.helius_api_key
            ) or {}
        except Exception as e:
            logger.error(f"Error getting on-chain data for {token_address}: {e}")
            return {}

    async def _enrich_single_token_rugcheck(self, session: aiohttp.ClientSession, token_address: str) -> Optional[Dict]:
        """
        Enrichit un token avec les données Rugcheck
        """
        try:
            return await self.rugcheck_client.get_token_report_async(session, token_address)
        except Exception as e:
            logger.error(f"Error getting rugcheck data for {token_address}: {e}")
            return None

    def _log_enrichment_stats(self):
        """
        Log des statistiques d'enrichissement
        """
        try:
            # Récupérer les statistiques depuis la base de données
            updated_counts = db.get_updated_tokens_counts()
            
            logger.info("📈 Enrichment Statistics:")
            logger.info(f"   • Tokens updated in last 5m: {updated_counts.get('5m', 0)}")
            logger.info(f"   • Tokens updated in last 30m: {updated_counts.get('30m', 0)}")
            logger.info(f"   • Tokens updated in last 1h: {updated_counts.get('1h', 0)}")
            logger.info(f"   • Tokens updated in last 6h: {updated_counts.get('6h', 0)}")
            
            # Calculer le taux d'enrichissement
            total_tokens_to_enrich = len(db.get_tokens_to_enrich(
                limit=1000,
                update_interval_minutes=settings.enrichment_update_interval_minutes
            ))
            
            logger.info(f"   • Tokens still needing enrichment: {total_tokens_to_enrich}")
            
            # Estimation du progrès
            if total_tokens_to_enrich == 0:
                logger.info("   • ✅ All tokens are up-to-date!")
            else:
                estimated_time = (total_tokens_to_enrich / settings.enrichment_batch_size) * (settings.enrichment_interval_seconds / 60)
                logger.info(f"   • Estimated time to complete: {estimated_time:.1f} minutes")
            
        except Exception as e:
            logger.error(f"Error logging enrichment stats: {e}")



# This will be instantiated in main.py
polling_manager = None