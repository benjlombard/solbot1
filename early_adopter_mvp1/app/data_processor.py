import logging
import json
import base64
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
import struct
import httpx

from models import PumpToken, EarlyPurchase, HeliusTransaction
from database import db
from config import settings

logger = logging.getLogger(__name__)

class PumpFunDataProcessor:
    def __init__(self):
        self.pumpfun_program_id = settings.pumpfun_program_id
        self.processed_signatures = set()
        self.httpx_client = httpx.AsyncClient(timeout=10.0)
    
    async def process_helius_transaction(self, transaction: HeliusTransaction) -> Dict[str, Any]:
        """
        Traite une transaction Helius pour détecter les événements pump.fun
        """
        result = {
            'processed': False,
            'token_created': None,
            'purchases': [],
            'errors': []
        }
        
        try:
            # Éviter les doublons
            if transaction.signature in self.processed_signatures:
                logger.debug(f"Transaction already processed: {transaction.signature}")
                return result
            
            # Vérifier si c'est une transaction pump.fun
            if not self._is_pumpfun_transaction(transaction):
                return result
            
            # Traitement selon le type de transaction
            if transaction.type == "UNKNOWN":
                # Potentielle création de token
                token = await self._process_token_creation(transaction)
                if token:
                    result['token_created'] = token
                    result['processed'] = True
            
            elif transaction.type == "SWAP":
                # Potentiel achat de token
                purchase = await self._process_token_purchase(transaction)
                if purchase:
                    result['purchases'].append(purchase)
                    result['processed'] = True
            
            # Marquer comme traité
            self.processed_signatures.add(transaction.signature)
            
            # Nettoyage périodique du cache
            if len(self.processed_signatures) > 10000:
                self.processed_signatures.clear()
            
        except Exception as e:
            logger.error(f"Error processing transaction {transaction.signature}: {e}")
            result['errors'].append(str(e))
        
        return result
    
    def _is_pumpfun_transaction(self, transaction: HeliusTransaction) -> bool:
        """Vérifie si la transaction concerne pump.fun"""
        for instruction in transaction.instructions:
            if instruction.programId == self.pumpfun_program_id:
                return True
        return False
    
    async def _process_token_creation(self, transaction: HeliusTransaction) -> Optional[PumpToken]:
        """
        Traite une création de token pump.fun
        """
        try:
            # Analyser les instructions pour extraire les données de création
            for instruction in transaction.instructions:
                if instruction.programId == self.pumpfun_program_id:
                    
                    # Tenter de décoder les données d'instruction
                    token_data = await self._decode_token_creation_data(instruction, transaction)
                    
                    if token_data:
                        token = PumpToken(
                            address=token_data['token_address'],
                            name=token_data.get('name'),
                            symbol=token_data.get('symbol'),
                            description=token_data.get('description'),
                            creator=transaction.feePayer,
                            created_at=transaction.timestamp,
                            market_cap_discovery=token_data.get('market_cap')
                        )
                        
                        # Sauvegarder en base
                        if db.insert_pump_token(token):
                            logger.info(f"New pump.fun token created: {token.address} - {token.symbol}")
                            return token
                        
        except Exception as e:
            logger.error(f"Error processing token creation {transaction.signature}: {e}")
        
        return None
    
    async def _process_token_purchase(self, transaction: HeliusTransaction) -> Optional[EarlyPurchase]:
        """
        Traite un achat de token pump.fun
        """
        try:
            # Analyser les transferts de tokens pour détecter les achats
            if not transaction.tokenTransfers:
                return None
            
            # Rechercher les transferts SOL vers pump.fun et tokens vers l'acheteur
            sol_transfer = None
            token_transfer = None
            
            for transfer in transaction.tokenTransfers:
                # Skip si montant trop faible (optimisation budget)
                if float(transfer.get('tokenAmount', 0)) < settings.min_sol_amount_filter:
                    continue
                
                # Identifier les transferts pertinents
                if transfer.get('mint') == 'So11111111111111111111111111111111111111112':  # SOL
                    sol_transfer = transfer
                else:
                    token_transfer = transfer
            
            if not (sol_transfer and token_transfer):
                return None
            
            # Extraire les données d'achat
            buyer_address = token_transfer.get('toUserAccount')
            token_address = token_transfer.get('mint')
            sol_amount = float(sol_transfer.get('tokenAmount', 0)) / 1e9  # Conversion lamports
            token_amount = float(token_transfer.get('tokenAmount', 0))
            
            if not all([buyer_address, token_address, sol_amount > 0]):
                return None
            
            # Vérifier si le token existe et calculer le timing
            token = db.get_token_by_address(token_address)
            if not token:
                # Le token n'est peut-être pas encore détecté, on peut l'ignorer pour l'instant
                return None
            
            # Calculer les minutes après création
            time_diff = transaction.timestamp - token.created_at
            minutes_after = int(time_diff.total_seconds() / 60)
            
            # Filtrer les achats trop tardifs (optimisation)
            if minutes_after > (settings.max_entry_timing_hours * 60):
                return None
            
            # Estimer le market cap au moment de l'achat
            market_cap_at_purchase = await self._estimate_market_cap(token_address, transaction.timestamp)
            
            purchase = EarlyPurchase(
                signature=transaction.signature,
                token_address=token_address,
                buyer_address=buyer_address,
                sol_amount=sol_amount,
                token_amount=token_amount,
                timestamp=transaction.timestamp,
                minutes_after_creation=minutes_after,
                market_cap_at_purchase=market_cap_at_purchase
            )
            
            # Sauvegarder en base
            if db.insert_early_purchase(purchase):
                logger.info(f"Early purchase detected: {buyer_address} -> {token.symbol} ({minutes_after}min after creation)")
                return purchase
                
        except Exception as e:
            logger.error(f"Error processing token purchase {transaction.signature}: {e}")
        
        return None
    
    async def _decode_token_creation_data(self, instruction: Any, transaction: HeliusTransaction) -> Optional[Dict[str, Any]]:
        """
        Décode les données de création de token à partir de l'instruction
        """
        try:
            # Pour une approche simplifiée, on utilise les données disponibles dans accountData
            if hasattr(transaction, 'accountData') and transaction.accountData:
                for account_info in transaction.accountData:
                    # Rechercher des données de token mint
                    if 'tokenInfo' in account_info:
                        token_info = account_info['tokenInfo']
                        return {
                            'token_address': account_info.get('account', ''),
                            'name': token_info.get('name', 'Unknown'),
                            'symbol': token_info.get('symbol', 'UNK'),
                            'description': token_info.get('description', ''),
                            'market_cap': None  # À calculer plus tard
                        }
            
            # Fallback : extraire l'adresse du token depuis les comptes de l'instruction
            if len(instruction.accounts) > 0:
                potential_token_address = instruction.accounts[0]
                return {
                    'token_address': potential_token_address,
                    'name': None,
                    'symbol': None, 
                    'description': None,
                    'market_cap': None
                }
            
        except Exception as e:
            logger.error(f"Error decoding token creation data: {e}")
        
        return None
    
    async def _estimate_market_cap(self, token_address: str, timestamp: datetime) -> Optional[float]:
        """
        Estime le market cap d'un token à un moment donné
        Pour le MVP, on retourne None et on implémenterait ça plus tard
        """
        # TODO: Implémenter l'estimation du market cap
        # Cela nécessiterait des appels API supplémentaires qui consommeraient des crédits
        return None
    
    async def _enrich_token_metadata(self, token_address: str) -> Dict[str, Any]:
        """
        Enrichit les métadonnées d'un token en utilisant l'API Helius
        """
        try:
            url = f"{settings.helius_rpc_url}/?api-key={settings.helius_api_key}"
            
            payload = {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "getAsset", 
                "params": {
                    "id": token_address
                }
            }
            
            response = await self.httpx_client.post(url, json=payload)
            
            if response.status_code == 200:
                data = response.json()
                if 'result' in data:
                    result = data['result']
                    return {
                        'name': result.get('content', {}).get('metadata', {}).get('name'),
                        'symbol': result.get('content', {}).get('metadata', {}).get('symbol'),
                        'description': result.get('content', {}).get('metadata', {}).get('description')
                    }
        except Exception as e:
            logger.error(f"Error enriching token metadata for {token_address}: {e}")
        
        return {}
    
    def get_processing_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques de traitement"""
        return {
            'processed_transactions': len(self.processed_signatures),
            'last_reset': datetime.now().isoformat()
        }
    
    async def cleanup(self):
        """Nettoyage des ressources"""
        await self.httpx_client.aclose()

# Instance globale
processor = PumpFunDataProcessor()