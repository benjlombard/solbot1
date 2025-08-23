import logging
import asyncio
import httpx
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Set
from collections import defaultdict
import json
import os

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


class PumpFunLatestTokensDiscovery:
    """Service de découverte via l'endpoint /coins/latest"""
    
    def __init__(self, db_manager, system_monitor=None):
        self.db = db_manager
        self.system_monitor = system_monitor
        self.base_url = "https://frontend-api-v3.pump.fun"
        self.last_processed_time = None
        
    async def discover_latest_tokens(self, limit: int = 50) -> Dict[str, Any]:
        """Découvre les nouveaux tokens via l'endpoint /coins/latest"""
        result = {
            'tokens_discovered': 0,
            'new_tokens': [],
            'errors': [],
            'processed_at': datetime.now().isoformat()
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/coins/latest"
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'application/json',
                    'Referer': 'https://pump.fun/'
                }
                
                logger.debug(f"🔍 Fetching latest tokens from: {url}")
                
                async with session.get(url, headers=headers, timeout=30) as response:
                    logger.debug(f"📥 Response status: {response.status}")
                    logger.debug(f"📥 Response headers: {dict(response.headers)}")
                    if response.status == 200:
                        data = await response.json()

                        # --- Fallback Logic ---
                        # Vérifier si la réponse est un signe de blocage de l'API
                        temp_token = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else {})
                        
                        is_blocked = (
                            temp_token.get('name') == 'h1.nu/17w1U' or
                            temp_token.get('description') == 'create solana tokens for dirt cheap!'
                        )

                        if is_blocked:
                            logger.warning("⚠️ Blocked by /coins/latest API. Attempting fallback to /coins?limit=1...")
                            fallback_url = f"{self.base_url}/coins?offset=0&limit=1"
                            async with session.get(fallback_url, headers=headers, timeout=30) as fallback_response:
                                if fallback_response.status == 200:
                                    data = await fallback_response.json()
                                    logger.info("✅ Fallback to /coins?limit=1 successful.")
                                else:
                                    error_msg = f"Fallback API call to /coins?limit=1 failed with status {fallback_response.status}"
                                    logger.error(error_msg)
                                    result['errors'].append(error_msg)
                                    return result # Quitter si le fallback échoue aussi
                        # --- End of Fallback Logic ---
                        
                        logger.debug(f"📊 Received response from discovery endpoint")
                        logger.debug(f"📊 Response type: {type(data)}")
                        
                        # L'endpoint /coins/latest ou le fallback /coins peut retourner une liste ou un objet
                        tokens = []
                        
                        if isinstance(data, dict) and 'mint' in data:
                            # C'est un seul token directement
                            tokens = [data]
                            logger.debug(f"📊 Single token received: {data.get('mint', 'NO_MINT')} - {data.get('name', 'NO_NAME')}")
                        elif isinstance(data, list):
                            # C'est une liste de tokens
                            tokens = data
                            logger.debug(f"📊 Token list received with {len(tokens)} tokens")
                        elif isinstance(data, dict):
                            # Peut-être que les tokens sont dans une propriété
                            tokens = data.get('data', data.get('coins', data.get('tokens', [])))
                            logger.debug(f"📊 Tokens extracted from nested structure: {len(tokens) if isinstance(tokens, list) else 'Not a list'}")
                        
                        if not tokens:
                            logger.debug(f"📊 No tokens found in response")
                            return result
                        
                        logger.debug(f"📊 Processing {len(tokens)} token(s)")
                        
                        # Traiter chaque token
                        for token_data in tokens:
                            try:
                                logger.debug(f"🔍 Processing token: {token_data.get('mint', 'NO_MINT')} - {token_data.get('name', 'NO_NAME')}")
                                
                                # Vérifier si c'est un nouveau token
                                if await self._is_new_token_latest(token_data):
                                    logger.debug(f"✅ Token is new, creating...")
                                    new_token = await self._create_token_from_latest_api(token_data)
                                    if new_token:
                                        result['new_tokens'].append(new_token)
                                        result['tokens_discovered'] += 1
                                        logger.debug(f"✅ Token successfully created: {new_token.address}")
                                        
                                        # Analyser le créateur immédiatement
                                        asyncio.create_task(
                                            self._analyze_creator_async(new_token.creator)
                                        )
                                    else:
                                        logger.warning(f"❌ Failed to create token from data")
                                else:
                                    logger.debug(f"⏭️ Token already exists, skipping")
                                    
                            except Exception as e:
                                logger.error(f"Error processing token from latest: {e}")
                                logger.error(f"Token data: {token_data}")
                                result['errors'].append(f"Token processing error: {str(e)}")
                        
                        # Mettre à jour le timestamp de traitement
                        self.last_processed_time = datetime.now()
                        
                        logger.debug(f"✅ Latest tokens discovery: {result['tokens_discovered']} new tokens found")
                        
                    else:
                        error_msg = f"HTTP {response.status} from latest endpoint"
                        logger.error(error_msg)
                        result['errors'].append(error_msg)
                        
        except Exception as e:
            error_msg = f"Error in latest tokens discovery: {e}"
            logger.error(error_msg)
            result['errors'].append(error_msg)
        
        return result
    
    async def _is_new_token_latest(self, token_data: dict) -> bool:
        """Vérifie si le token est nouveau dans notre base"""
        mint_address = token_data.get('mint')
        logger.debug(f"🔍 Checking if token is new: {mint_address}")

        if not mint_address:
            logger.warning(f"❌ No mint address found in token data: {list(token_data.keys())}")
            return False
        
        # Vérifier si on a déjà ce token
        existing_token = self.db.get_token_by_address(mint_address)
        
        if existing_token:
            logger.debug(f"❌ Token {mint_address[:10]}... already exists in database")
            return False

        logger.debug(f"✅ Token {mint_address[:10]}... is new!")
  
        # Vérification supplémentaire par timestamp si disponible
        created_timestamp = token_data.get('created_timestamp')
        if created_timestamp and self.last_processed_time:
            try:
                token_created_at = datetime.fromtimestamp(created_timestamp / 1000)
                logger.debug(f"🕐 Token created at: {token_created_at}")
                logger.debug(f"🕐 Last processed: {self.last_processed_time}")
                
                # Ne traiter que les tokens créés après notre dernière vérification
                if token_created_at <= self.last_processed_time:
                    logger.debug(f"⏭️ Token {mint_address[:10]}... already processed based on timestamp")
                    return False
            except Exception as e:
                logger.warning(f"⚠️ Error parsing timestamp {created_timestamp}: {e}")
        
        return True
    
    async def _create_token_from_latest_api(self, token_data: dict) -> Optional[PumpToken]:
        """Crée un objet PumpToken depuis les données de l'endpoint latest"""
        try:
            mint_address = token_data.get('mint')
            creator = token_data.get('creator') 
            name = token_data.get('name')
            symbol = token_data.get('symbol')
            description = token_data.get('description', '')
            
            # Convertir timestamp (millisecondes)
            created_timestamp = token_data.get('created_timestamp')
            if created_timestamp:
                created_at = datetime.fromtimestamp(created_timestamp / 1000)
            else:
                created_at = datetime.now()
            
            # Market cap au moment de la découverte
            market_cap = token_data.get('usd_market_cap', 0)
            
            token = PumpToken(
                address=mint_address,
                name=name,
                symbol=symbol,
                description=description,
                creator=creator,
                created_at=created_at,
                market_cap_discovery=market_cap
            )
            
            # Insérer en base
            if self.db.insert_pump_token(token):
                logger.debug(f"🆕 NEW TOKEN via /latest: {mint_address} by {creator[:10]}...")
                
                # Enregistrer l'appel API
                if self.system_monitor:
                    self.system_monitor.record_api_call('pumpfun_latest')
                
                return token
            
        except Exception as e:
            logger.error(f"Error creating token from latest API data: {e}")
        
        return None
    
    async def _analyze_creator_async(self, creator_address: str):
        """Analyse le créateur de manière asynchrone"""
        try:
            await asyncio.sleep(1)  # Petite pause pour éviter la surcharge
            creator_analyzer.analyze_creator(creator_address)
            logger.debug(f"Creator analyzed for latest token: {creator_address[:10]}...")
        except Exception as e:
            logger.error(f"Error analyzing creator {creator_address}: {e}")


class PumpFunTokenDiscovery:
    """Service de découverte via API pump.fun (méthode existante)"""
    
    def __init__(self, db_manager, system_monitor=None):
        self.db = db_manager
        self.system_monitor = system_monitor
        self.base_url = "https://frontend-api-v3.pump.fun"
        
    async def discover_new_tokens(self, limit: int = 50) -> Dict[str, Any]:
        """Découvre les nouveaux tokens via l'API (méthode existante)"""
        result = {
            'tokens_discovered': 0,
            'new_tokens': [],
            'errors': []
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/coins?offset=0&limit={limit}"
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                
                async with session.get(url, headers=headers, timeout=30) as response:
                    if response.status == 200:
                        data = await response.json()
                        tokens = data if isinstance(data, list) else []
                        
                        for token_data in tokens:
                            if await self._is_new_token(token_data):
                                new_token = await self._create_token_from_api(token_data)
                                if new_token:
                                    result['new_tokens'].append(new_token)
                                    result['tokens_discovered'] += 1
                        
                        logger.debug(f"API Discovery: {result['tokens_discovered']} new tokens found")
                        
        except Exception as e:
            logger.error(f"Error in API discovery: {e}")
            result['errors'].append(str(e))
        
        return result
    
    async def _is_new_token(self, token_data: dict) -> bool:
        """Vérifie si le token est nouveau dans notre base"""
        mint_address = token_data.get('mint')
        if not mint_address:
            return False
        
        # Vérifier si on a déjà ce token
        existing_token = self.db.get_token_by_address(mint_address)
        return existing_token is None
    
    async def _create_token_from_api(self, token_data: dict) -> Optional[PumpToken]:
        """Crée un objet PumpToken depuis les données API"""
        try:
            from .models import PumpToken
            
            mint_address = token_data.get('mint')
            creator = token_data.get('creator') 
            name = token_data.get('name')
            symbol = token_data.get('symbol')
            description = token_data.get('description', '')
            
            # Convertir timestamp (millisecondes)
            created_timestamp = token_data.get('created_timestamp')
            if created_timestamp:
                created_at = datetime.fromtimestamp(created_timestamp / 1000)
            else:
                created_at = datetime.now()
            
            market_cap = token_data.get('usd_market_cap', 0)
            
            token = PumpToken(
                address=mint_address,
                name=name,
                symbol=symbol,
                description=description,
                creator=creator,
                created_at=created_at,
                market_cap_discovery=market_cap
            )
            
            # Insérer en base
            if self.db.insert_pump_token(token):
                logger.debug(f"NEW TOKEN via API: {mint_address} by {creator}")
                return token
            
        except Exception as e:
            logger.error(f"Error creating token from API data: {e}")
        
        return None

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

        if self._is_purchase_correct(transaction):
            purchases = self._extract_purchase_info_correct(transaction)
            for purchase in purchases:
                db.insert_early_purchase(purchase)
                result['purchases'].append(purchase)
            if purchases:
                result['processed'] = True
                logger.debug(f"Purchase detected: {len(purchases)} purchases")

        return result

    def _is_token_creation_correct(self, transaction: HeliusTransaction) -> bool:
        """
        Détection correcte des créations de tokens pump.fun
        Basée sur l'analyse des discriminators d'instructions
        """
        for instruction in transaction.instructions:
            if instruction.programId == settings.pumpfun_program_id:
                # Analyser les données de l'instruction
                if len(instruction.data) >= 8:
                    # Les discriminators pump.fun pour "create"
                    # Le discriminator "create" est différent de "buy"/"sell"
                    data_bytes = instruction.data
                    
                    # Log pour debug
                    logger.debug(f"Pump.fun instruction data: {data_bytes[:16] if len(data_bytes) >= 16 else data_bytes}")
                    
                    # Méthode 1: Détecter par longueur de données et pattern
                    # Les créations ont généralement plus de données que les swaps
                    if len(data_bytes) > 50:  # Les créations ont plus de metadata
                        return True
                    
                    # Méthode 2: Analyser les comptes impliqués
                    # Les créations impliquent généralement plus de comptes
                    if len(instruction.accounts) >= 10:  # Création implique plus de comptes
                        return True
                    
        return False

    def _is_purchase_correct(self, transaction: HeliusTransaction) -> bool:
        """
        Détection correcte des achats pump.fun
        """
        has_pumpfun_instruction = any(
            inst.programId == settings.pumpfun_program_id for inst in transaction.instructions
        )
        
        # Un achat a une instruction pump.fun ET des token transfers
        return has_pumpfun_instruction and bool(transaction.tokenTransfers)

    def _extract_token_info_correct(self, transaction: HeliusTransaction) -> PumpToken | None:
        """
        Extraction correcte des informations de token créé
        """
        try:
            # Trouver l'instruction pump.fun de création
            for instruction in transaction.instructions:
                if instruction.programId == settings.pumpfun_program_id:
                    if len(instruction.accounts) >= 4:  # Création nécessite plusieurs comptes
                        
                        # Dans pump.fun, la structure typique pour create est:
                        # accounts[0] = creator (fee payer)
                        # accounts[1] = mint address (nouveau token)
                        # accounts[2] = bonding curve
                        # accounts[3] = associated bonding curve
                        # ... autres comptes
                        
                        creator = transaction.feePayer  # Le vrai créateur
                        token_address = instruction.accounts[1]  # Mint address
                        bonding_curve = instruction.accounts[2] if len(instruction.accounts) > 2 else None
                        associated_bonding_curve = instruction.accounts[3] if len(instruction.accounts) > 3 else None
                        
                        logger.debug(f"🔍 Extracting token creation:")
                        logger.debug(f"   Creator: {creator}")
                        logger.debug(f"   Token: {token_address}")
                        logger.debug(f"   Bonding curve: {bonding_curve}")
                        logger.debug(f"   Associated BC: {associated_bonding_curve}")
                        
                        return PumpToken(
                            address=token_address,
                            name=None,  # À enrichir plus tard
                            symbol=None,  # À enrichir plus tard
                            description=None,  # À enrichir plus tard
                            creator=creator,
                            created_at=transaction.timestamp,
                            market_cap_discovery=None
                        )
            
            logger.warning("Could not extract token info from pump.fun creation transaction")
            return None
            
        except Exception as e:
            logger.error(f"Error extracting token info: {e}")
            return None

    def _extract_purchase_info_correct(self, transaction: HeliusTransaction) -> List[EarlyPurchase]:
        """
        Extraction correcte des informations d'achat
        """
        purchases = []
        
        try:
            for transfer in transaction.tokenTransfers:
                # Ignorer SOL (wrapped SOL)
                if transfer.get('mint') == 'So11111111111111111111111111111111111111112':
                    continue

                buyer = transfer.get('toUserAccount')
                token_address = transfer.get('mint')
                token_amount = float(transfer.get('tokenAmount', 0))
                
                if not buyer or not token_address:
                    continue
                
                # Calculer le montant SOL dépensé
                sol_amount = 0
                for native_transfer in transaction.nativeTransfers:
                    if native_transfer.get('fromUserAccount') == buyer:
                        sol_amount = native_transfer.get('amount', 0) / 1e9  # Convertir lamports en SOL
                        break
                
                # Calculer les minutes après création
                # Pour l'instant, on met 0 - sera calculé plus tard avec la DB
                minutes_after_creation = 0
                
                purchase = EarlyPurchase(
                    signature=transaction.signature,
                    token_address=token_address,
                    buyer_address=buyer,
                    sol_amount=sol_amount,
                    token_amount=token_amount,
                    timestamp=transaction.timestamp,
                    minutes_after_creation=minutes_after_creation,
                    market_cap_at_purchase=None
                )
                
                purchases.append(purchase)
                logger.debug(f"Extracted purchase: {buyer} bought {token_amount} {token_address} for {sol_amount} SOL")
                
        except Exception as e:
            logger.error(f"Error extracting purchase info: {e}")
        
        return purchases

    def analyze_pump_instruction_discriminator(self, instruction_data: str) -> str:
        """
        Analyse le discriminator d'une instruction pump.fun pour déterminer le type
        Les discriminators sont les 8 premiers bytes de l'instruction
        """
        if len(instruction_data) < 16:  # 8 bytes = 16 hex chars
            return "unknown"
        
        # Convertir les 8 premiers bytes en discriminator
        try:
            # Si c'est déjà en bytes
            if isinstance(instruction_data, bytes):
                discriminator = instruction_data[:8]
            else:
                # Si c'est en base64 ou hex, le décoder
                import base64
                decoded = base64.b64decode(instruction_data)
                discriminator = decoded[:8]
            
            discriminator_hex = discriminator.hex()
            
            # Discriminators connus pour pump.fun (à découvrir par reverse engineering)
            known_discriminators = {
                "181ec828051c0777": "create",     # Exemple - à vérifier
                "f223c68952e1f2b6": "buy",        # Exemple - à vérifier
                "51b6dbc3e70f2d2e": "sell",       # Exemple - à vérifier
            }
            
            instruction_type = known_discriminators.get(discriminator_hex, "unknown")
            
            logger.debug(f"Discriminator: {discriminator_hex} -> {instruction_type}")
            
            return instruction_type
            
        except Exception as e:
            logger.error(f"Error analyzing discriminator: {e}")
            return "unknown"

    def log_pump_instruction_details(self, transaction: HeliusTransaction):
        """
        Log détaillé pour découvrir les patterns des instructions pump.fun
        """
        for i, instruction in enumerate(transaction.instructions):
            if instruction.programId == settings.pumpfun_program_id:
                logger.debug(f"🔍 Pump.fun instruction {i}:")
                logger.debug(f"   Program: {instruction.programId}")
                logger.debug(f"   Data length: {len(instruction.data)}")
                logger.debug(f"   Accounts count: {len(instruction.accounts)}")
                
                # Log les premiers bytes (discriminator)
                if len(instruction.data) >= 8:
                    if isinstance(instruction.data, bytes):
                        discriminator = instruction.data[:8].hex()
                    else:
                        try:
                            import base64
                            decoded = base64.b64decode(instruction.data)
                            discriminator = decoded[:8].hex()
                        except:
                            discriminator = str(instruction.data)[:16]
                    
                    logger.debug(f"   Discriminator: {discriminator}")
                
                # Log quelques comptes
                for j, account in enumerate(instruction.accounts[:5]):
                    logger.debug(f"   Account {j}: {account}")
                
                # Analyser le contexte
                has_token_transfers = bool(transaction.tokenTransfers)
                has_native_transfers = bool(transaction.nativeTransfers)
                
                logger.debug(f"   Context: transfers={has_token_transfers}, native={has_native_transfers}")
                
                # Hypothèse sur le type
                if not has_token_transfers and len(instruction.accounts) >= 8:
                    logger.debug(f"   🎯 LIKELY TOKEN CREATION (no transfers, many accounts)")
                elif has_token_transfers:
                    logger.debug(f"   🎯 LIKELY SWAP/TRADE (has transfers)")
                else:
                    logger.debug(f"   🎯 UNKNOWN TYPE")

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
    
        # ===== NOUVEAU: Services de découverte multiples =====
        self.latest_tokens_discovery = PumpFunLatestTokensDiscovery(db, self.system_monitor)
        self.general_token_discovery = PumpFunTokenDiscovery(db, self.system_monitor)
        
        # Timers séparés pour chaque méthode
        self.last_latest_discovery = datetime.now() - timedelta(minutes=10)
        self.last_general_discovery = datetime.now() - timedelta(minutes=30)
        
        # Configuration des intervalles
        self.latest_discovery_interval_seconds = getattr(settings, 'latest_discovery_interval_seconds', 60)  # 1 minute par défaut
        self.general_discovery_interval_seconds = getattr(settings, 'api_discovery_interval_seconds', 300)  # 5 minutes par défaut
        
        # Flag pour activer/désactiver l'ancienne méthode
        self.use_transaction_detection = getattr(settings, 'use_transaction_token_detection', False)

        self.use_api_discovery = getattr(settings, 'use_api_discovery', True)
        self.use_latest_discovery = getattr(settings, 'use_latest_discovery', True)  # NOUVEAU

    def start_polling(self):
        """Démarre le polling intelligent"""
        if not self.polling_task or self.polling_task.done():
            self.is_running = True
            self.polling_task = asyncio.create_task(self._polling_loop())
            logger.debug("🚀 Intelligent polling started with latest tokens discovery")
    
    # async def _polling_loop(self):
    #     """Boucle principale de polling avec découverte multi-méthodes"""
    #     logger.debug("🔥 Starting intelligent polling loop with LATEST tokens discovery")
        
    #     while self.is_running:
    #         try:
    #             # Vérifier et réinitialiser les stats quotidiennes
    #             self._check_daily_reset()
                
    #             # Vérifier les limites de crédits
    #             if self.system_monitor.get_helius_credits_today() >= settings.max_daily_credits * 0.95:
    #                 logger.warning("Credit limit nearly reached, pausing polling")
    #                 await asyncio.sleep(3600)  # Attendre 1h
    #                 continue
                
    #             # Vérifier la santé de l'API avant de continuer
    #             if self.consecutive_failures >= 3:
    #                 logger.warning(f"API health degraded ({self.consecutive_failures} failures), extending polling interval")
    #                 self.current_polling_interval = min(self.current_polling_interval * 1.5, self.max_polling_interval * 2)
                
    #             # ===== NOUVEAU: Découverte prioritaire via /coins/latest =====
    #             if (self.use_latest_discovery and 
    #                 (datetime.now() - self.last_latest_discovery).total_seconds() > self.latest_discovery_interval_seconds):
                    
    #                 await self._run_latest_tokens_discovery()
                
    #             # Découverte générale (moins fréquente)
    #             if (self.use_api_discovery and 
    #                 (datetime.now() - self.last_general_discovery).total_seconds() > self.general_discovery_interval_seconds):
                    
    #                 await self._run_general_api_discovery()
                
    #             # Traitement des transactions selon la configuration
    #             # success = False
    #             # if getattr(settings, 'use_transaction_token_detection', False):
    #             #     # Ancienne méthode (complète avec détection de création)
    #             #     success = await self._poll_recent_transactions_safe()
    #             # else:
    #             #     # Nouvelle méthode (achats seulement)
    #             #     success = await self._poll_transactions_for_purchases_only_safe()
                
    #             # if success:
    #             #     self.consecutive_failures = 0
    #             #     self.last_successful_poll = datetime.now()
    #             #     self.api_health_status = "healthy"
    #             # else:
    #             #     self.consecutive_failures += 1
    #             #     self.api_health_status = "degraded" if self.consecutive_failures < 5 else "critical"
                
    #             # Nettoyer le cache périodiquement
    #             await self._cleanup_cache()

    #             # Exécuter l'enrichissement des métadonnées périodiquement
    #             if settings.enable_metadata_enrichment and (datetime.now() - self.last_enrichment_run).total_seconds() > settings.enrichment_interval_seconds:
    #                 await self._enrich_token_metadata()
                
    #             # Adapter l'intervalle de polling
    #             self._adapt_polling_interval()
                
    #             # Attendre avant le prochain cycle avec backoff si nécessaire
    #             wait_time = self.current_polling_interval
    #             if self.consecutive_failures > 0:
    #                 wait_time = min(wait_time * (1 + self.consecutive_failures * 0.5), 1800)  # Max 30 min
                
    #             logger.debug(f"Waiting {wait_time}s before next poll (failures: {self.consecutive_failures})")
    #             await asyncio.sleep(wait_time)
                
    #         except Exception as e:
    #             logger.error(f"Error in polling loop: {e}")
    #             self.consecutive_failures += 1
    #             await asyncio.sleep(60)  # Attendre 1 minute en cas d'erreur

    # Ajoutez ces logs de debug dans la boucle de polling (_polling_loop) 
# pour identifier où le processus se bloque

    # async def _polling_loop(self):
    #     """Boucle principale de polling avec debug amélioré"""
    #     logger.debug("🔥 Starting intelligent polling loop with LATEST tokens discovery")
        
    #     cycle_count = 0
        
    #     while self.is_running:
    #         try:
    #             cycle_count += 1
    #             logger.debug(f"🔄 Starting polling cycle #{cycle_count}")
                
    #             # Vérifier et réinitialiser les stats quotidiennes
    #             logger.debug(f"📅 Checking daily reset...")
    #             self._check_daily_reset()
                
    #             # Vérifier les limites de crédits
    #             logger.debug(f"💳 Checking credit limits...")
    #             helius_credits = self.system_monitor.get_helius_credits_today() if self.system_monitor else 0
    #             if helius_credits >= settings.max_daily_credits * 0.95:
    #                 logger.warning("Credit limit nearly reached, pausing polling")
    #                 await asyncio.sleep(3600)  # Attendre 1h
    #                 continue
                
    #             # Vérifier la santé de l'API avant de continuer
    #             logger.debug(f"🩺 Checking API health...")
    #             if self.consecutive_failures >= 3:
    #                 logger.warning(f"API health degraded ({self.consecutive_failures} failures), extending polling interval")
    #                 self.current_polling_interval = min(self.current_polling_interval * 1.5, self.max_polling_interval * 2)
                
    #             # ===== DÉCOUVERTE TOKENS =====
    #             logger.debug(f"🔍 Checking discovery schedules...")
                
    #             # NOUVEAU: Découverte prioritaire via /coins/latest
    #             try:
    #                 if (self.use_latest_discovery and 
    #                     (datetime.now() - self.last_latest_discovery).total_seconds() > self.latest_discovery_interval_seconds):
                        
    #                     logger.debug(f"🔥 Running LATEST tokens discovery...")
    #                     await self._run_latest_tokens_discovery()
    #                     logger.debug(f"✅ LATEST discovery completed")
    #                 else:
    #                     logger.debug(f"⏭️ LATEST discovery not due yet")
    #             except Exception as e:
    #                 logger.error(f"❌ Error in LATEST discovery: {e}")
                
    #             # Découverte générale (moins fréquente)
    #             try:
    #                 if (self.use_api_discovery and 
    #                     (datetime.now() - self.last_general_discovery).total_seconds() > self.general_discovery_interval_seconds):
                        
    #                     logger.debug(f"📡 Running general API discovery...")
    #                     await self._run_general_api_discovery()
    #                     logger.debug(f"✅ General discovery completed")
    #                 else:
    #                     logger.debug(f"⏭️ General discovery not due yet")
    #             except Exception as e:
    #                 logger.error(f"❌ Error in general discovery: {e}")
                
    #             # ===== TRAITEMENT TRANSACTIONS (si activé) =====
    #             logger.debug(f"📊 Checking transaction processing...")
    #             success = True  # Par défaut, pas de polling de transactions
                
    #             try:
    #                 # DÉSACTIVÉ : Traitement des transactions
    #                 # if getattr(settings, 'use_transaction_token_detection', False):
    #                 #     success = await self._poll_recent_transactions_safe()
    #                 # else:
    #                 #     success = await self._poll_transactions_for_purchases_only_safe()
                    
    #                 logger.debug(f"📊 Transaction processing skipped (disabled)")
    #             except Exception as e:
    #                 logger.error(f"❌ Error in transaction processing: {e}")
    #                 success = False
                
    #             # ===== MISE À JOUR STATUTS =====
    #             logger.debug(f"📈 Updating statuses...")
                
    #             if success:
    #                 self.consecutive_failures = 0
    #                 self.last_successful_poll = datetime.now()
    #                 self.api_health_status = "healthy"
    #             else:
    #                 self.consecutive_failures += 1
    #                 self.api_health_status = "degraded" if self.consecutive_failures < 5 else "critical"
                
    #             # Nettoyer le cache périodiquement
    #             logger.debug(f"🧹 Cleaning cache...")
    #             try:
    #                 await self._cleanup_cache()
    #             except Exception as e:
    #                 logger.error(f"❌ Error cleaning cache: {e}")

    #             # Exécuter l'enrichissement des métadonnées périodiquement
    #             logger.debug(f"✨ Checking enrichment schedule...")
    #             try:
    #                 if settings.enable_metadata_enrichment and (datetime.now() - self.last_enrichment_run).total_seconds() > settings.enrichment_interval_seconds:
    #                     logger.debug(f"🔄 Starting enrichment task...")
    #                     await self._enrich_token_metadata()
    #                     logger.debug(f"✅ Enrichment completed")
    #                 else:
    #                     logger.debug(f"⏭️ Enrichment not due yet")
    #             except Exception as e:
    #                 logger.error(f"❌ Error in enrichment: {e}")
                
    #             # Adapter l'intervalle de polling
    #             logger.debug(f"⚙️ Adapting polling interval...")
    #             try:
    #                 self._adapt_polling_interval()
    #             except Exception as e:
    #                 logger.error(f"❌ Error adapting interval: {e}")
                
    #             # Attendre avant le prochain cycle
    #             wait_time = self.current_polling_interval
    #             if self.consecutive_failures > 0:
    #                 wait_time = min(wait_time * (1 + self.consecutive_failures * 0.5), 1800)  # Max 30 min
                
    #             logger.debug(f"😴 Cycle #{cycle_count} completed. Waiting {wait_time}s before next cycle...")
    #             logger.debug(f"📊 Cycle stats: failures={self.consecutive_failures}, health={self.api_health_status}")
                
    #             await asyncio.sleep(wait_time)
                
    #         except asyncio.CancelledError:
    #             logger.debug("🛑 Polling loop cancelled")
    #             break
    #         except Exception as e:
    #             logger.error(f"💥 Critical error in polling loop cycle #{cycle_count}: {e}")
    #             import traceback
    #             logger.error(f"📋 Traceback: {traceback.format_exc()}")
    #             self.consecutive_failures += 1
    #             await asyncio.sleep(60)  # Attendre 1 minute en cas d'erreur
        
    #     logger.debug("🏁 Polling loop ended")
    


    async def _polling_loop(self):
        """Boucle principale de polling avec découverte optimisée"""
        logger.info("🚀 DISCOVERY ENGINE STARTED - Latest: 30s | API: 60s")
        
        cycle_count = 0
        
        # Configuration des intervalles optimisés
        LATEST_DISCOVERY_INTERVAL_SECONDS = 30  # Toutes les 30 secondes
        API_DISCOVERY_INTERVAL_SECONDS = 60     # Toutes les 60 secondes
        
        while self.is_running:
            try:
                cycle_count += 1
                
                # Vérifications système (silencieuses)
                self._check_daily_reset()
                helius_credits = self.system_monitor.get_helius_credits_today() if self.system_monitor else 0
                if helius_credits >= settings.max_daily_credits * 0.95:
                    logger.warning("💳 CREDIT LIMIT REACHED - Pausing discovery")
                    await asyncio.sleep(3600)
                    continue
                
                # ===== 1. DÉCOUVERTE LATEST (30 secondes) =====
                if (self.use_latest_discovery and 
                    (datetime.now() - self.last_latest_discovery).total_seconds() > LATEST_DISCOVERY_INTERVAL_SECONDS):
                    
                    logger.info("🔥 LATEST DISCOVERY START")
                    try:
                        await self._run_latest_discovery_with_enrichment()
                    except Exception as e:
                        logger.error(f"❌ LATEST DISCOVERY FAILED: {e}")
                
                # ===== 2. DÉCOUVERTE API GÉNÉRALE (60 secondes) =====
                if (self.use_api_discovery and 
                    (datetime.now() - self.last_general_discovery).total_seconds() > API_DISCOVERY_INTERVAL_SECONDS):
                    
                    logger.info("📡 API DISCOVERY START")
                    try:
                        await self._run_api_discovery_with_enrichment()
                    except Exception as e:
                        logger.error(f"❌ API DISCOVERY FAILED: {e}")
                
                # ===== 3. ENRICHISSEMENT DIFFÉRÉ (silencieux) =====
                if settings.enable_metadata_enrichment and (datetime.now() - self.last_enrichment_run).total_seconds() > settings.enrichment_interval_seconds:
                    try:
                        await self._enrich_token_metadata()
                    except Exception as e:
                        logger.error(f"❌ BACKGROUND ENRICHMENT FAILED: {e}")
                
                # Nettoyage (silencieux)
                try:
                    await self._cleanup_cache()
                except:
                    pass
                
                # Mise à jour des statuts
                self.consecutive_failures = 0
                self.last_successful_poll = datetime.now()
                self.api_health_status = "healthy"
                
                # Attendre avant le prochain cycle
                await asyncio.sleep(10)
                
            except asyncio.CancelledError:
                logger.info("🛑 DISCOVERY ENGINE STOPPED")
                break
            except Exception as e:
                logger.error(f"💥 CRITICAL ERROR: {e}")
                self.consecutive_failures += 1
                await asyncio.sleep(60)
        
        logger.info("🏁 DISCOVERY ENGINE SHUTDOWN")

    async def _run_latest_discovery_with_enrichment(self):
        """Découverte LATEST avec enrichissement immédiat complet"""
        try:
            # 1. Découverte des nouveaux tokens
            discovery_limit = getattr(settings, 'latest_discovery_limit', 20)
            result = await self.latest_tokens_discovery.discover_latest_tokens(limit=discovery_limit)
            
            # 2. Traitement des nouveaux tokens
            if result['new_tokens']:
                logger.info(f"📊 {len(result['new_tokens'])} NEW TOKENS (LATEST) → Starting enrichment")
                
                for token in result['new_tokens']:
                    try:
                        await self._full_immediate_enrichment(token.address, token.creator, "LATEST")
                    except Exception as e:
                        logger.error(f"❌ ENRICHMENT FAILED (LATEST): {token.address[:8]}... → {e}")
                
                # Statistiques
                self._update_daily_stats_latest_discovery(result['tokens_discovered'])
                logger.info(f"✅ LATEST DISCOVERY COMPLETE → {result['tokens_discovered']} tokens processed")
            else:
                logger.info("✅ LATEST DISCOVERY COMPLETE → No new tokens found")
            
            # Erreurs
            if result['errors']:
                logger.warning(f"⚠️ LATEST DISCOVERY ERRORS: {len(result['errors'])}")
            
            # Finalisation
            self.last_latest_discovery = datetime.now()
            if self.system_monitor:
                self.system_monitor.record_api_call('pumpfun_latest')
            
        except Exception as e:
            logger.error(f"❌ LATEST DISCOVERY CRITICAL FAILURE: {e}")
            self.last_latest_discovery = datetime.now()

    async def _run_api_discovery_with_enrichment(self):
        """Découverte API générale avec enrichissement immédiat complet"""
        try:
            # 1. Découverte des nouveaux tokens
            discovery_limit = getattr(settings, 'api_discovery_limit', 50)
            result = await self.general_token_discovery.discover_new_tokens(limit=discovery_limit)
            
            # 2. Traitement des nouveaux tokens
            if result['new_tokens']:
                logger.info(f"📊 {len(result['new_tokens'])} NEW TOKENS (API) → Starting enrichment")
                
                for token in result['new_tokens']:
                    try:
                        await self._full_immediate_enrichment(token.address, token.creator, "API")
                    except Exception as e:
                        logger.error(f"❌ ENRICHMENT FAILED (API): {token.address[:8]}... → {e}")
                
                # Statistiques
                self._update_daily_stats_general_discovery(result['tokens_discovered'])
                logger.info(f"✅ API DISCOVERY COMPLETE → {result['tokens_discovered']} tokens processed")
            else:
                logger.info("✅ API DISCOVERY COMPLETE → No new tokens found")
            
            # Erreurs
            if result['errors']:
                logger.warning(f"⚠️ API DISCOVERY ERRORS: {len(result['errors'])}")
            
            # Finalisation
            self.last_general_discovery = datetime.now()
            if self.system_monitor:
                self.system_monitor.record_api_call('pumpfun_general')
            
        except Exception as e:
            logger.error(f"❌ API DISCOVERY CRITICAL FAILURE: {e}")
            self.last_general_discovery = datetime.now() + timedelta(minutes=5)

    async def _full_immediate_enrichment(self, token_address: str, creator_address: str, source: str = "UNKNOWN"):
        """
        Enrichissement complet avec double appel RugCheck et logique de sélection de rapport.
        """
        logger.info(f"🔄 [{source}] Starting dual enrichment for {token_address[:8]}...")
        logger.info(f"   Full token address: {token_address}")
        
        reports_dir = "rugcheck_reports"
        os.makedirs(reports_dir, exist_ok=True)

        rugcheck_before = None
        rugcheck_after = None
        
        try:
            # --- Étape 1: Collecte des rapports RugCheck ---
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                # Premier appel RugCheck
                logger.info(f"🔎 [{token_address[:8]}] Fetching initial RugCheck report...")
                try:
                    rugcheck_before = await self._enrich_single_token_rugcheck(session, token_address)
                    if rugcheck_before:
                        file_path = os.path.join(reports_dir, f"{token_address}_before.json")
                        with open(file_path, 'w') as f: json.dump(rugcheck_before, f, indent=4)
                        logger.info(f"📝 Saved 'before' report to {file_path}")
                except Exception as e:
                    logger.warning(f"⚠️ [{token_address[:8]}] Initial RugCheck call failed: {e}")

                # Pause
                logger.info(f"⏳ [{token_address[:8]}] Waiting 15 seconds for data to mature...")
                await asyncio.sleep(15)

                # Deuxième appel RugCheck
                logger.info(f"🔎 [{token_address[:8]}] Fetching final RugCheck report...")
                try:
                    rugcheck_after = await self._enrich_single_token_rugcheck(session, token_address)
                    if rugcheck_after:
                        file_path = os.path.join(reports_dir, f"{token_address}_after.json")
                        with open(file_path, 'w') as f: json.dump(rugcheck_after, f, indent=4)
                        logger.info(f"📝 Saved 'after' report to {file_path}")
                except Exception as e:
                     logger.warning(f"⚠️ [{token_address[:8]}] Final RugCheck call failed: {e}")

            # --- Étape 2: Sélection du rapport final basé sur les nouvelles règles ---
            final_rugcheck_report = None
            if rugcheck_before and rugcheck_after:
                self._log_rugcheck_comparison(token_address, rugcheck_before, rugcheck_after)
                score_before = rugcheck_before.get('score_normalised', 101)
                score_after = rugcheck_after.get('score_normalised', 101)
                if score_before <= score_after:
                    final_rugcheck_report = rugcheck_before
                    logger.info(f"⚖️ [{token_address[:8]}] Using 'before' report (Score: {score_before}) as it's lower or equal to 'after' (Score: {score_after}).")
                else:
                    final_rugcheck_report = rugcheck_after
                    logger.info(f"⚖️ [{token_address[:8]}] Using 'after' report (Score: {score_after}) as it's lower than 'before' (Score: {score_before}).")
            elif rugcheck_before:
                final_rugcheck_report = rugcheck_before
                logger.warning(f"⚠️ [{token_address[:8]}] Using 'before' report as 'after' report failed.")
            elif rugcheck_after:
                final_rugcheck_report = rugcheck_after
                logger.warning(f"⚠️ [{token_address[:8]}] Using 'after' report as 'before' report failed.")
            else:
                logger.error(f"❌ [{token_address[:8]}] Both RugCheck calls failed. Storing score as -1.")
                final_rugcheck_report = {"error": "Both RugCheck calls failed", "score_normalised": -1, "totalHolders": 0, "risks": []}
            
            # --- Étape 3: Vérification de la liste noire ---
            BLACKLIST_RISK = "Creator history of rugged tokens"
            def check_for_blacklist(report):
                if not report or not isinstance(report.get('risks'), list): return False
                return any(isinstance(r, dict) and r.get('name') == BLACKLIST_RISK for r in report['risks'])

            if check_for_blacklist(final_rugcheck_report):
                logger.warning(f"🚨 BLACKLISTED: Token {token_address[:8]}... based on final selected report. Halting enrichment.")
                db.update_token_pumpfun_data(token_address, {'is_blacklisted': True})
                db.upsert_rugcheck_report(token_address, final_rugcheck_report)
                return

            # --- Étape 4: Enrichissement et mise à jour (si pas blacklisté) ---
            logger.info(f"✨ [{token_address[:8]}] Proceeding with full enrichment.")
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                token_obj = db.get_token_by_address(token_address)
                pumpfun_data, onchain_data = await asyncio.gather(
                    self._enrich_single_token_pumpfun(session, token_address),
                    self._enrich_single_token_onchain(token_address, token_obj)
                )

            pumpfun_data = pumpfun_data or {}
            onchain_data = onchain_data or {}

            if onchain_data.get('success'):
                pumpfun_data.update({
                    'bonding_curve_progress': onchain_data.get('bonding_curve_progress', 0),
                    'virtual_sol_reserves': onchain_data.get('virtual_sol_reserves', 0),
                    'virtual_token_reserves': onchain_data.get('virtual_token_reserves', 0)
                })

            final_score = final_rugcheck_report.get('score_normalised', -1)
            final_holders_count = final_rugcheck_report.get('totalHolders', 0)
            pumpfun_data['holders_count'] = final_holders_count if final_holders_count is not None else 0
            pumpfun_data['rugcheck_score'] = final_score

            if pumpfun_data:
                db.update_token_pumpfun_data(token_address, pumpfun_data)
                logger.info(f"💾 [{token_address[:8]}] Updated Pump.fun data in DB.")

            db.upsert_rugcheck_report(token_address, final_rugcheck_report)
            logger.info(f"💾 [{token_address[:8]}] Upserted final RugCheck report in DB.")

            db.create_snapshot(token_address)
            logger.info(f"📸 [{token_address[:8]}] Created database snapshot after enrichment.")

            asyncio.create_task(self._analyze_creator_async(creator_address, token_address))
            
            logger.info(f"✅ [{token_address[:8]}] Enriched: Pump {pumpfun_data.get('bonding_curve_progress', 0):.2f}%, Rug {final_score}, Holders {final_holders_count}")

        except Exception as e:
            logger.error(f"💥 CRITICAL Enrichment failed for {token_address[:8]}: {e}", exc_info=True)

    def _log_rugcheck_comparison(self, token_address: str, before: Dict, after: Dict):
        """Logue une comparaison détaillée entre deux rapports RugCheck."""
        try:
            score_before = before.get('score_normalised', 'N/A')
            score_after = after.get('score_normalised', 'N/A')
            
            holders_before = before.get('totalHolders', 'N/A')
            holders_after = after.get('totalHolders', 'N/A')
            
            risks_before_list = before.get('risks', [])
            risks_after_list = after.get('risks', [])
            
            # Extraire les noms des risques pour l'affichage, en s'assurant qu'ils sont des chaînes
            risks_before_names = sorted([str(r.get('name')) for r in risks_before_list if isinstance(r, dict)])
            risks_after_names = sorted([str(r.get('name')) for r in risks_after_list if isinstance(r, dict)])

            # Construire le message de log détaillé pour éviter les problèmes de formatage
            log_msg_parts = [
                f"📊 [{token_address[:8]}] RugCheck 15s Compare:",
                f"Score: {score_before} to {score_after}",
                f"Holders: {holders_before} to {holders_after}",
                f"Risks Before: {risks_before_names or '[]'}",
                f"Risks After: {risks_after_names or '[]'}"
            ]
            
            logger.info(" | ".join(log_msg_parts))
                
        except Exception as e:
            logger.warning(f"⚠️ Could not log RugCheck comparison for {token_address[:8]}: {e}")

    async def _analyze_creator_async(self, creator_address: str, token_address: str = ""):
        """Analyse le créateur de manière asynchrone"""
        try:
            # Analyse dans un thread séparé
            def analyze_creator_sync():
                return creator_analyzer.analyze_creator(creator_address, force_refresh=True)
            
            loop = asyncio.get_event_loop()
            performance = await loop.run_in_executor(None, analyze_creator_sync)
            
            # Mise à jour base
            if performance:
                creator_analyzer.update_creator_in_database(performance)
                
                # Log simple
                if performance.is_blacklisted:
                    logger.warning(f"🚨 Blacklisted creator {creator_address[:8]}: {performance.blacklist_reason}")
                else:
                    logger.info(f"👤 Creator {creator_address[:8]} analyzed: Score {performance.reputation_score:.0f}")
                
        except Exception as e:
            logger.error(f"❌ Creator analysis failed for {creator_address[:8]}: {e}")

    def _check_daily_reset(self):
        """Vérifie et réinitialise les stats quotidiennes"""
        current_date = datetime.now().date()
        
        if current_date != self.last_reset_date:
            self.daily_stats.clear()
            self.credits_used_today = 0
            self.last_reset_date = current_date
            logger.debug("Daily stats reset")

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
            logger.debug(f"Polling interval adapted to {self.current_polling_interval}s (avg activity: {avg_activity:.1f})")

    async def _cleanup_cache(self):
        """Nettoie le cache des signatures traitées"""
        now = datetime.now()
        
        # Nettoyer toutes les heures
        if (now - self.last_signature_cleanup).total_seconds() > 3600:
            # Garder seulement les signatures des 6 dernières heures
            if len(self.processed_signatures) > 5000:
                logger.debug(f"Cleaning signature cache: {len(self.processed_signatures)} -> limiting to recent ones")
                # Pour simplifier, on vide complètement le cache
                # Dans un vrai système, on utiliserait un cache avec TTL
                self.processed_signatures.clear()
            
            self.last_signature_cleanup = now

    def _update_daily_stats(self, transaction_count: int):
        """Met à jour les statistiques quotidiennes"""
        self.daily_stats['transactions_processed'] += transaction_count
        self.daily_stats['polling_cycles'] += 1
        
        # Alerte si proche de la limite
        if self.credits_used_today > settings.max_daily_credits * 0.8:
            logger.warning(f"High credit usage: {self.credits_used_today}/{settings.max_daily_credits}")

    def _is_transaction_worth_processing(self, transaction) -> bool:
        """Détermine si une transaction mérite d'être traitée (optimisation)"""
        # Vérifier s'il y a des transferts significatifs
        if hasattr(transaction, 'tokenTransfers') and transaction.tokenTransfers:
            for transfer in transaction.tokenTransfers:
                amount = float(transfer.get('tokenAmount', 0))
                if amount >= settings.min_sol_amount_filter:
                    return True
        
        # Vérifier s'il y a des transferts natifs significatifs
        if hasattr(transaction, 'nativeTransfers') and transaction.nativeTransfers:
            for transfer in transaction.nativeTransfers:
                amount = transfer.get('amount', 0)
                if amount >= settings.min_sol_amount_filter * 1e9:  # Conversion lamports
                    return True
        
        # Toujours traiter les transactions UNKNOWN (potentielles créations de tokens)
        if hasattr(transaction, 'type') and transaction.type == "UNKNOWN":
            return True
        
        return False

    async def _trigger_scoring_update(self):
        """Déclenche une mise à jour du scoring des early adopters"""
        try:
            await scorer.update_all_early_adopters()
            logger.debug("Early adopter scoring updated")
        except Exception as e:
            logger.error(f"Error updating early adopter scores: {e}")

    async def _get_transaction_details_with_retry(self, signature: str, max_retries: int = 2):
        """Récupère les détails d'une transaction avec retry et logging détaillé"""
        for attempt in range(max_retries):
            try:
                logger.debug(f"📄 Getting transaction details - attempt {attempt + 1}/{max_retries}")
                
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
                
                logger.debug(f"📤 Sending getTransaction request:")
                logger.debug(f"   Signature: {signature}")
                logger.debug(f"   Payload: {json.dumps(payload, indent=2)}")
                
                async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
                    response = await client.post(url, json=payload)
                    
                    logger.debug(f"📥 getTransaction response:")
                    logger.debug(f"   Status: {response.status_code}")
                    
                    response.raise_for_status()
                
                data = response.json()
                logger.debug(f"📋 Transaction details response:")
                logger.debug(f"   Has result: {'result' in data}")
                logger.debug(f"   Has error: {'error' in data}")
                
                if 'error' in data:
                    logger.error(f"   Error: {data['error']}")
                    return None
                
                if not data.get('result'):
                    logger.warning(f"   ⚠️ No result for transaction {signature[:20]}...")
                    return None
                
                result = data['result']
                logger.debug(f"   Transaction exists: {result is not None}")
                
                if result:
                    # Log structure de la transaction
                    logger.debug(f"   Transaction structure:")
                    logger.debug(f"     - signature: {result.get('signature', 'N/A')}")
                    logger.debug(f"     - slot: {result.get('slot', 'N/A')}")
                    logger.debug(f"     - blockTime: {result.get('blockTime', 'N/A')}")
                    logger.debug(f"     - has transaction: {'transaction' in result}")
                    
                    if 'transaction' in result:
                        tx_data = result['transaction']
                        logger.debug(f"     - has message: {'message' in tx_data}")
                        
                        if 'message' in tx_data:
                            message = tx_data['message']
                            logger.debug(f"       - accountKeys count: {len(message.get('accountKeys', []))}")
                            logger.debug(f"       - instructions count: {len(message.get('instructions', []))}")
                            
                            # Log les premiers account keys
                            account_keys = message.get('accountKeys', [])
                            for i, key in enumerate(account_keys[:5]):  # Premier 5
                                logger.debug(f"         Account {i}: {key}")
                            
                            # Log les instructions
                            instructions = message.get('instructions', [])
                            for i, inst in enumerate(instructions):
                                program_id_index = inst.get('programIdIndex')
                                program_id = account_keys[program_id_index] if program_id_index < len(account_keys) else 'Unknown'
                                logger.debug(f"         Instruction {i}: program={program_id} (index={program_id_index})")
                                logger.debug(f"           accounts: {inst.get('accounts', [])}")
                                logger.debug(f"           data length: {len(inst.get('data', ''))}")
                                
                                # Marquer si c'est pump.fun
                                if program_id == self.pumpfun_program_id:
                                    logger.debug(f"           🎯 PUMP.FUN INSTRUCTION DETECTED!")
                
                # Parser la transaction
                parsed_tx = self._parse_helius_transaction(result)
                
                if parsed_tx:
                    logger.debug(f"   ✅ Transaction parsed successfully")
                    logger.debug(f"     - Type: {parsed_tx.type}")
                    logger.debug(f"     - Instructions: {len(parsed_tx.instructions)}")
                    logger.debug(f"     - Token transfers: {len(parsed_tx.tokenTransfers)}")
                    
                    # Compter les instructions pump.fun
                    pumpfun_instructions = sum(1 for inst in parsed_tx.instructions if inst.programId == self.pumpfun_program_id)
                    logger.debug(f"     - Pump.fun instructions: {pumpfun_instructions}")
                    
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

    def _parse_helius_transaction(self, tx_data: Dict[str, Any]):
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
                logger.debug(f"Found {len(address_table_lookups)} address table lookups - expanding account keys")
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
                            logger.debug(f"Using pump.fun program ID from previous detection")
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
                    from .models import HeliusInstruction
                    instruction = HeliusInstruction(
                        accounts=instruction_accounts,
                        data=inst_data.get('data', ''),
                        innerInstructions=[],
                        programId=program_id
                    )
                    instructions.append(instruction)
                    
                    # Log et mémoriser si c'est pump.fun
                    if program_id == self.pumpfun_program_id:
                        logger.debug(f"✅ Pump.fun instruction successfully parsed in instruction {inst_idx}!")
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
            from .models import HeliusTransaction
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
            
            logger.debug(f"✅ Transaction parsed: {len(instructions)} instructions, {len(token_transfers)} transfers")
            logger.debug(f"   Pump.fun instructions in final transaction: {pumpfun_count}")
            
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

    async def _enrich_token_metadata(self):
        """Tâche de fond pour enrichir les métadonnées des tokens."""
        logger.debug("Starting token metadata enrichment task...")
        self.last_enrichment_run = datetime.now()
        
        try:
            # Note: get_tokens_to_enrich returns addresses, but we need the full token object
            # to get the bonding curve addresses. Let's get the full objects.
            token_addresses_to_enrich = db.get_tokens_to_enrich(
                limit=settings.enrichment_batch_size,
                update_interval_minutes=settings.enrichment_update_interval_minutes
            )
            
            if not token_addresses_to_enrich:
                logger.debug("No tokens require metadata enrichment at this time.")
                return

            tokens_to_enrich_obj = [db.get_token_by_address(addr) for addr in token_addresses_to_enrich]
            tokens_to_enrich_obj = [t for t in tokens_to_enrich_obj if t is not None]
            
            tokens_to_enrich = [t.__dict__ for t in tokens_to_enrich_obj]

            if not tokens_to_enrich:
                logger.debug("No valid token objects to enrich.")
                return

            logger.debug(f"Found {len(tokens_to_enrich)} tokens to enrich.")
            
            # Fetch data from HTTP API and on-chain concurrently
            async with aiohttp.ClientSession() as session:
                http_api_tasks = [self.pump_fun_client.get_token_data(session, t['address']) for t in tokens_to_enrich]
                on_chain_tasks = [get_pump_progress_correct(t['address'], t.get('bonding_curve'), t.get('associated_bonding_curve'), self.helius_api_key) for t in tokens_to_enrich]
                rugcheck_tasks = [self.rugcheck_client.get_token_report_async(session, t['address']) for t in tokens_to_enrich]
                
                all_tasks = http_api_tasks + on_chain_tasks + rugcheck_tasks
                results = await asyncio.gather(*all_tasks, return_exceptions=True)

            http_api_results = results[:len(tokens_to_enrich)]
            on_chain_results = results[len(tokens_to_enrich):2*len(tokens_to_enrich)]
            rugcheck_results = results[2*len(tokens_to_enrich):]

            updated_count = 0
            for i, token in enumerate(tokens_to_enrich):
                token_address = token['address']
                pump_data = http_api_results[i] if isinstance(http_api_results[i], dict) else {}
                on_chain_data = on_chain_results[i] if isinstance(on_chain_results[i], dict) else {}
                rugcheck_report = rugcheck_results[i] if isinstance(rugcheck_results[i], dict) else None

                # Combine the data
                if on_chain_data.get('success'):
                    pump_data['bonding_curve_progress'] = on_chain_data.get('bonding_curve_progress')

                # Create a snapshot before updating
                db.create_snapshot(token_address)

                # Update the database if we got any new data
                if pump_data:
                    success = db.update_token_pumpfun_data(token_address, pump_data)
                    if success:
                        updated_count += 1
                
                if rugcheck_report:
                    db.upsert_rugcheck_report(token_address, rugcheck_report)
            
            logger.debug(f"Enrichment task complete. Updated {updated_count}/{len(tokens_to_enrich)} tokens.")

        except Exception as e:
            logger.error(f"An error occurred during the enrichment task: {e}", exc_info=True)

    async def _enrich_single_token_pumpfun(self, session, token_address: str) -> Dict:
        """Enrichissement via Pump.fun API pour un token"""
        try:
            data = await self.pump_fun_client.get_token_data(session, token_address)
            return data if data else {}
        except Exception as e:
            logger.error(f"Error enriching {token_address} with Pump.fun API: {e}")
            return {}

    async def _enrich_single_token_onchain(self, token_address: str, token_obj) -> Dict:
        """Enrichissement on-chain pour un token"""
        try:
            # Récupérer les attributs selon le type d'objet
            if hasattr(token_obj, '__dict__'):
                # C'est un objet PumpToken, utiliser les attributs
                bonding_curve = getattr(token_obj, 'bonding_curve', None)
                associated_bonding_curve = getattr(token_obj, 'associated_bonding_curve', None)
            elif isinstance(token_obj, dict):
                # C'est un dictionnaire, utiliser .get()
                bonding_curve = token_obj.get('bonding_curve')
                associated_bonding_curve = token_obj.get('associated_bonding_curve')
            else:
                # Fallback : essayer les deux méthodes
                bonding_curve = getattr(token_obj, 'bonding_curve', None) if hasattr(token_obj, 'bonding_curve') else None
                associated_bonding_curve = getattr(token_obj, 'associated_bonding_curve', None) if hasattr(token_obj, 'associated_bonding_curve') else None
            
            logger.debug(f"🔗 On-chain enrichment for {token_address[:10]}... - BC: {bonding_curve[:10] if bonding_curve else 'None'}...")
            
            data = await get_pump_progress_correct(
                token_address,
                bonding_curve,
                associated_bonding_curve,
                self.helius_api_key
            )
            return data if data else {}
        except Exception as e:
            logger.error(f"Error enriching {token_address} on-chain: {e}")
            return {}

    async def _enrich_single_token_rugcheck(self, session, token_address: str) -> Dict:
        """Enrichissement via RugCheck pour un token"""
        try:
            data = await self.rugcheck_client.get_token_report_async(session, token_address)
            return data if data else {}
        except Exception as e:
            logger.error(f"Error enriching {token_address} with RugCheck: {e}")
            return {}

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
            logger.debug("Force polling triggered")
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

    async def force_latest_discovery(self) -> Dict[str, Any]:
        """Force la découverte latest immédiate (pour debug/test)"""
        try:
            logger.debug("Force latest discovery triggered")
            await self._run_latest_tokens_discovery()
            return {
                'status': 'success',
                'message': 'Force latest discovery completed',
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error in force latest discovery: {e}")
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
        logger.debug("Polling manager shutdown complete")

    async def _run_latest_tokens_discovery(self):
        """Exécute la découverte via l'endpoint /coins/latest"""
        try:
            logger.debug("🔥 Running LATEST tokens discovery...")
            
            # Récupérer la limite depuis la config
            discovery_limit = getattr(settings, 'latest_discovery_limit', 20)  # Plus petit car plus fréquent
            
            # Exécuter la découverte
            result = await self.latest_tokens_discovery.discover_latest_tokens(limit=discovery_limit)
            
            # Traitement des résultats
            if result['tokens_discovered'] > 0:
                logger.debug(f"🎯 LATEST Discovery: {result['tokens_discovered']} new tokens found!")
                
                # Analyser les créateurs des nouveaux tokens est déjà fait dans la méthode
                # Mettre à jour les statistiques
                self._update_daily_stats_latest_discovery(result['tokens_discovered'])
                
                # Déclencher l'enrichissement immédiat pour les nouveaux tokens
                for token in result['new_tokens']:
                    asyncio.create_task(self._priority_enrich_token(token.address))
                    
            else:
                logger.debug("LATEST Discovery: No new tokens found")
            
            # Traiter les erreurs
            if result['errors']:
                logger.warning(f"LATEST Discovery errors: {result['errors']}")
            
            # Mettre à jour le timestamp
            self.last_latest_discovery = datetime.now()
            
            # Record de l'appel API pour monitoring
            if self.system_monitor:
                self.system_monitor.record_api_call('pumpfun_latest')
            
        except Exception as e:
            logger.error(f"Error in LATEST tokens discovery: {e}")
            # En cas d'erreur, attendre plus longtemps avant le prochain essai
            self.last_latest_discovery = datetime.now()

    async def _run_general_api_discovery(self):
        """Exécute la découverte générale via l'API pump.fun"""
        try:
            logger.debug("📡 Running general API discovery...")
            
            # Récupérer la limite depuis la config
            discovery_limit = getattr(settings, 'api_discovery_limit', 50)
            
            # Exécuter la découverte
            result = await self.general_token_discovery.discover_new_tokens(limit=discovery_limit)
            
            # Traitement des résultats
            if result['tokens_discovered'] > 0:
                logger.debug(f"📊 General Discovery: {result['tokens_discovered']} new tokens found")
                
                # Analyser les créateurs des nouveaux tokens
                for token in result['new_tokens']:
                    try:
                        # Analyse synchrone du créateur
                        creator_analyzer.analyze_creator(token.creator)
                        logger.debug(f"Creator analyzed for general token: {token.address}")
                    except Exception as e:
                        logger.error(f"Error analyzing creator {token.creator}: {e}")
                
                # Mettre à jour les statistiques
                self._update_daily_stats_general_discovery(result['tokens_discovered'])
            else:
                logger.debug("General Discovery: No new tokens found")
            
            # Traiter les erreurs
            if result['errors']:
                logger.warning(f"General Discovery errors: {result['errors']}")
            
            # Mettre à jour le timestamp
            self.last_general_discovery = datetime.now()
            
            # Record de l'appel API pour monitoring
            if self.system_monitor:
                self.system_monitor.record_api_call('pumpfun_general')
            
        except Exception as e:
            logger.error(f"Error in general API discovery: {e}")
            # En cas d'erreur, attendre plus longtemps avant le prochain essai
            self.last_general_discovery = datetime.now() + timedelta(minutes=5)

    async def _priority_enrich_token(self, token_address: str):
        """Enrichissement prioritaire pour les nouveaux tokens découverts"""
        try:
            logger.debug(f"🚀 Priority enriching new token: {token_address[:10]}...")
            
            # Récupérer le token depuis la DB
            token_obj = db.get_token_by_address(token_address)
            if not token_obj:
                logger.warning(f"Token {token_address} not found in DB for priority enrichment")
                return
            
            # Créer snapshot avant enrichissement
            db.create_snapshot(token_address)
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                # Enrichissement parallèle prioritaire
                tasks = [
                    self._enrich_single_token_pumpfun(session, token_address),
                    self._enrich_single_token_onchain(token_address, token_obj),  # Passer l'objet directement
                    self._enrich_single_token_rugcheck(session, token_address)
                ]
                
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Traiter les résultats
                pumpfun_data = results[0] if isinstance(results[0], dict) else {}
                onchain_data = results[1] if isinstance(results[1], dict) else {}
                rugcheck_data = results[2] if isinstance(results[2], dict) else None
                
                # Merger les données on-chain
                if onchain_data.get('success'):
                    pumpfun_data['bonding_curve_progress'] = onchain_data.get('bonding_curve_progress', 0)
                    pumpfun_data['virtual_sol_reserves'] = onchain_data.get('virtual_sol_reserves', 0)
                    pumpfun_data['virtual_token_reserves'] = onchain_data.get('virtual_token_reserves', 0)
                
                # Mettre à jour en base
                if pumpfun_data:
                    success = db.update_token_pumpfun_data(token_address, pumpfun_data)
                    if success:
                        logger.debug(f"✅ Priority enriched: {token_address[:10]}... with progress: {pumpfun_data.get('bonding_curve_progress', 'N/A')}")
                
                # Mettre à jour rugcheck
                if rugcheck_data:
                    db.upsert_rugcheck_report(token_address, rugcheck_data)
            
        except Exception as e:
            logger.error(f"Error in priority enrichment for {token_address}: {e}")

    def _update_daily_stats_latest_discovery(self, tokens_discovered: int):
        """Met à jour les statistiques pour la découverte latest"""
        self.daily_stats['latest_tokens_discovered'] += tokens_discovered
        self.daily_stats['latest_discovery_calls'] += 1
        
        if tokens_discovered > 0:
            logger.debug(f"📈 Daily LATEST discovery stats: {self.daily_stats['latest_tokens_discovered']} tokens via {self.daily_stats['latest_discovery_calls']} calls")

    def _update_daily_stats_general_discovery(self, tokens_discovered: int):
        """Met à jour les statistiques pour la découverte générale"""
        self.daily_stats['general_tokens_discovered'] += tokens_discovered
        self.daily_stats['general_discovery_calls'] += 1
        
        if tokens_discovered > 0:
            logger.debug(f"📊 Daily general discovery stats: {self.daily_stats['general_tokens_discovered']} tokens via {self.daily_stats['general_discovery_calls']} calls")

    async def _poll_transactions_for_purchases_only_safe(self) -> bool:
        """Version sécurisée du polling pour achats uniquement"""
        try:
            await self._poll_transactions_for_purchases_only()
            return True
        except Exception as e:
            logger.error(f"Error in purchases-only polling: {e}")
            return False

    async def _poll_transactions_for_purchases_only(self):
        """Version simplifiée qui ne cherche que les achats, pas les créations"""
        try:
            # Calculer la période à scanner
            lookback_minutes = max(self.current_polling_interval / 60 * 1.2, 3)
            since_time = datetime.now() - timedelta(minutes=lookback_minutes)
            
            logger.debug(f"Polling transactions for purchases only since {since_time.isoformat()}")
            
            # Récupérer les transactions pump.fun récentes
            transactions = await self._get_recent_pumpfun_transactions(since_time)
            
            if not transactions:
                logger.debug("No pump.fun transactions found")
                self.recent_activity_levels.append(0)
                return
            
            # Filtrer les doublons
            new_transactions = []
            for tx in transactions:
                if tx.signature not in self.processed_signatures:
                    new_transactions.append(tx)
                    self.processed_signatures.add(tx.signature)
            
            if not new_transactions:
                logger.debug(f"Found {len(transactions)} transactions but all already processed")
                self.recent_activity_levels.append(0)
                return
            
            logger.debug(f"Processing {len(new_transactions)} new transactions (purchases only)")
            
            self.recent_activity_levels.append(len(new_transactions))
            self.last_activity_time = datetime.now()
            
            # Traiter les transactions pour achats uniquement
            await self._process_transaction_batch_purchases_only(new_transactions)
            
            # Mettre à jour les statistiques
            self._update_daily_stats(len(new_transactions))
            
        except Exception as e:
            logger.error(f"Error polling transactions for purchases: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

    async def _process_transaction_batch_purchases_only(self, transactions: List[HeliusTransaction]):
        """Traite un lot de transactions pour achats uniquement"""
        logger.debug(f"Processing batch of {len(transactions)} transactions (purchases only)")
        
        purchases_detected = 0
        
        for transaction in transactions:
            try:
                # Log détaillé pour debug (optionnel)
                if hasattr(self.data_processor, 'log_pump_instruction_details'):
                    if any(inst.programId == self.pumpfun_program_id for inst in transaction.instructions):
                        self.data_processor.log_pump_instruction_details(transaction)
                
                # Filtrer les micro-transactions
                if not self._is_transaction_worth_processing(transaction):
                    continue
                
                # Traiter SEULEMENT les achats
                if self.data_processor._is_purchase_correct(transaction):
                    purchases = self.data_processor._extract_purchase_info_correct(transaction)
                    for purchase in purchases:
                        if db.insert_early_purchase(purchase):
                            purchases_detected += 1
                            logger.debug(f"Purchase recorded: {purchase.buyer_address} -> {purchase.token_address}")
            
            except Exception as e:
                logger.error(f"Error processing transaction {transaction.signature}: {e}")
        
        # Logs de résumé
        if purchases_detected > 0:
            logger.debug(f"Batch processed: {purchases_detected} purchases detected")
            
            # Déclencher la mise à jour des scores
            asyncio.create_task(self._trigger_scoring_update())
        else:
            logger.debug("No purchases detected in this batch")

    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques du polling avec données discovery"""
        base_stats = {
            'is_running': self.is_running,
            'current_polling_interval': self.current_polling_interval,
            'credits_used_today': self.system_monitor.get_helius_credits_today() if self.system_monitor else 0,
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
        
        # Ajouter les stats de découverte
        base_stats['discovery'] = {
            'latest_discovery': {
                'enabled': getattr(self, 'use_latest_discovery', False),
                'last_run': self.last_latest_discovery.isoformat(),
                'time_since_last_minutes': (datetime.now() - self.last_latest_discovery).total_seconds() / 60,
                'interval_seconds': self.latest_discovery_interval_seconds,
                'tokens_discovered_today': self.daily_stats.get('latest_tokens_discovered', 0),
                'calls_today': self.daily_stats.get('latest_discovery_calls', 0)
            },
            'general_discovery': {
                'enabled': getattr(self, 'use_api_discovery', False),
                'last_run': self.last_general_discovery.isoformat(),
                'time_since_last_minutes': (datetime.now() - self.last_general_discovery).total_seconds() / 60,
                'interval_seconds': self.general_discovery_interval_seconds,
                'tokens_discovered_today': self.daily_stats.get('general_tokens_discovered', 0),
                'calls_today': self.daily_stats.get('general_discovery_calls', 0)
            }
        }
        
        return base_stats

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
            
            logger.debug(f"Polling transactions since {since_time.isoformat()} (lookback: {lookback_minutes:.1f}min)")
            
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
                logger.debug(f"Found {len(transactions)} transactions but all already processed")
                self.recent_activity_levels.append(0)
                return
            
            logger.debug(f"Processing {len(new_transactions)} new transactions")
            
            # Debug: analyser les transactions
            pumpfun_count = 0
            for tx in new_transactions:
                has_pumpfun = any(inst.programId == self.pumpfun_program_id for inst in tx.instructions)
                if has_pumpfun:
                    pumpfun_count += 1
                    logger.debug(f"🎯 Pump.fun transaction: {tx.signature[:20]}... - Type: {tx.type}")
            
            logger.debug(f"📊 Transactions with pump.fun instructions: {pumpfun_count}/{len(new_transactions)}")
            
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
                logger.debug(f"🔍 Attempt {attempt + 1}/{max_retries} to fetch pump.fun transactions")
                
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
                
                logger.debug(f"📤 Sending request to Helius:")
                logger.debug(f"   URL: {url}")
                logger.debug(f"   Payload: {json.dumps(payload, indent=2)}")
                
                # Utiliser un timeout plus court et retry
                async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=10.0)) as client:
                    response = await client.post(url, json=payload)
                    
                    logger.debug(f"📥 Response from Helius:")
                    logger.debug(f"   Status: {response.status_code}")
                    logger.debug(f"   Headers: {dict(response.headers)}")
                    
                    response.raise_for_status()
                
                data = response.json()
                logger.debug(f"📋 Response data:")
                logger.debug(f"   Raw response: {json.dumps(data, indent=2)}")
                
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
                    logger.debug(f"ℹ️ Empty result - no signatures found for pump.fun program")
                    return []
                
                signatures = data['result']
                logger.debug(f"📊 Found {len(signatures)} signatures for pump.fun program")
                
                # Log détails des signatures
                for i, sig_info in enumerate(signatures[:3]):  # Log les 3 premières
                    logger.debug(f"   Signature {i+1}: {json.dumps(sig_info, indent=4)}")
                
                # OPTIMISATION: Traiter seulement les 5 plus récentes
                recent_signatures = signatures[:5]  # RÉDUIT drastiquement
                transactions = []
                
                # OPTIMISATION: Récupérer les détails
                if recent_signatures:
                    recent_sigs = []
                    for sig_info in recent_signatures:
                        signature = sig_info['signature']
                        block_time = sig_info.get('blockTime')
                        
                        logger.debug(f"🔍 Processing signature: {signature}")
                        logger.debug(f"   Block time: {block_time}")
                        
                        if not block_time:
                            logger.warning(f"   ⚠️ No block time for signature {signature[:20]}...")
                            continue
                        
                        # Vérifier si la transaction est dans la fenêtre de temps
                        tx_time = datetime.fromtimestamp(block_time)
                        time_diff = datetime.now() - tx_time
                        
                        logger.debug(f"   Transaction time: {tx_time.isoformat()}")
                        logger.debug(f"   Time diff: {time_diff.total_seconds():.1f} seconds ago")
                        logger.debug(f"   Since time: {since_time.isoformat()}")
                        logger.debug(f"   In window: {tx_time >= since_time}")
                        
                        if tx_time >= since_time:
                            recent_sigs.append(signature)
                            logger.debug(f"   ✅ Added to recent signatures")
                        else:
                            logger.debug(f"   ❌ Too old, skipped")
                    
                    logger.debug(f"📈 Processing {len(recent_sigs)} recent signatures")
                    
                    # Récupérer les détails des transactions récentes (max 3)
                    for signature in recent_sigs[:3]:  # LIMITE à 3 max
                        logger.debug(f"🔍 Fetching transaction details for: {signature[:20]}...")
                        tx_detail = await self._get_transaction_details_with_retry(signature, max_retries=2)
                        if tx_detail:
                            logger.debug(f"   ✅ Transaction details retrieved")
                            transactions.append(tx_detail)
                        else:
                            logger.warning(f"   ❌ Failed to get transaction details")
                
                # Record Helius API calls
                self.system_monitor.record_helius_call('getSignaturesForAddress', 10)
                if transactions:
                    self.system_monitor.record_helius_call('getTransaction', 10 * len(transactions))

                logger.debug(f"✅ Retrieved {len(transactions)} pump.fun transactions")
                
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