"""
Découverte directe via Solana RPC - 100% Gratuit
Surveille les transactions de création de tokens
"""

import requests
import json
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import base58

class SolanaDirectDiscovery:
    """Découverte directe de nouveaux tokens via Solana RPC"""
    
    # Programme IDs importants pour les tokens
    TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
    ASSOCIATED_TOKEN_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
    METAPLEX_PROGRAM = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"
    
    def __init__(self, rpc_url: str = "https://api.mainnet-beta.solana.com"):
        self.rpc_url = rpc_url
        self.logger = logging.getLogger(__name__)
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json'
        })
    
    def get_recent_token_creations(self, slots_back: int = 1000) -> List[Dict]:
        """
        Récupérer les créations de tokens récentes via RPC
        """
        try:
            # Obtenir le slot actuel
            current_slot = self._get_current_slot()
            if not current_slot:
                return []
            
            start_slot = max(0, current_slot - slots_back)
            
            self.logger.info(f"🔍 Scanning slots {start_slot} to {current_slot}")
            
            new_tokens = []
            
            # Scanner les blocs récents (échantillonnage)
            sample_slots = range(start_slot, current_slot, max(1, slots_back // 100))
            
            for slot in sample_slots:
                try:
                    block_tokens = self._scan_block_for_tokens(slot)
                    new_tokens.extend(block_tokens)
                    
                    # Rate limiting
                    time.sleep(0.1)
                    
                except Exception as e:
                    self.logger.debug(f"Error scanning slot {slot}: {e}")
                    continue
            
            self.logger.info(f"🆕 Found {len(new_tokens)} new tokens via RPC scan")
            return new_tokens
            
        except Exception as e:
            self.logger.error(f"Error in RPC token discovery: {e}")
            return []
    
    def _get_current_slot(self) -> Optional[int]:
        """Obtenir le slot actuel"""
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSlot",
                "params": [{"commitment": "processed"}]
            }
            
            response = self.session.post(self.rpc_url, json=payload, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                return result.get('result')
            
        except Exception as e:
            self.logger.error(f"Error getting current slot: {e}")
        
        return None
    
    def _scan_block_for_tokens(self, slot: int) -> List[Dict]:
        """Scanner un bloc pour les créations de tokens"""
        try:
            # Obtenir le bloc
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBlock",
                "params": [
                    slot,
                    {
                        "encoding": "json",
                        "transactionDetails": "full",
                        "rewards": False
                    }
                ]
            }
            
            response = self.session.post(self.rpc_url, json=payload, timeout=10)
            
            if response.status_code != 200:
                return []
            
            block_data = response.json()
            result = block_data.get('result')
            
            if not result or not result.get('transactions'):
                return []
            
            new_tokens = []
            
            # Analyser chaque transaction
            for tx in result['transactions']:
                try:
                    tx_tokens = self._analyze_transaction_for_tokens(tx, slot)
                    new_tokens.extend(tx_tokens)
                except Exception as e:
                    continue
            
            return new_tokens
            
        except Exception as e:
            self.logger.debug(f"Error scanning block {slot}: {e}")
            return []
    
    def _analyze_transaction_for_tokens(self, transaction: Dict, slot: int) -> List[Dict]:
        """Analyser une transaction pour détecter les créations de tokens"""
        try:
            meta = transaction.get('meta', {})
            if meta.get('err'):  # Skip failed transactions
                return []
            
            message = transaction.get('transaction', {}).get('message', {})
            instructions = message.get('instructions', [])
            account_keys = message.get('accountKeys', [])
            
            new_tokens = []
            
            for instruction in instructions:
                try:
                    program_id_index = instruction.get('programIdIndex')
                    if program_id_index is None or program_id_index >= len(account_keys):
                        continue
                    
                    program_id = account_keys[program_id_index]
                    
                    # Détecter les instructions de création de token
                    if program_id == self.TOKEN_PROGRAM:
                        token_info = self._parse_token_instruction(instruction, account_keys, slot)
                        if token_info:
                            new_tokens.append(token_info)
                
                except Exception as e:
                    continue
            
            return new_tokens
            
        except Exception as e:
            return []
    
    def _parse_token_instruction(self, instruction: Dict, account_keys: List[str], slot: int) -> Optional[Dict]:
        """Parser une instruction de création de token"""
        try:
            # Analyser les données de l'instruction
            data = instruction.get('data', '')
            if not data:
                return None
            
            # Décoder les données (base58 ou base64)
            try:
                if isinstance(data, str):
                    # Essayer de décoder
                    decoded_data = base58.b58decode(data)
                else:
                    return None
            except Exception:
                return None
            
            # Vérifier si c'est une instruction de création de mint
            if len(decoded_data) > 0 and decoded_data[0] == 0:  # InitializeMint instruction
                accounts = instruction.get('accounts', [])
                
                if len(accounts) > 0:
                    mint_address = account_keys[accounts[0]]
                    
                    return {
                        'token_address': mint_address,
                        'symbol': 'UNKNOWN',
                        'name': 'Unknown Token',
                        'decimals': 9,  # Default
                        'slot_created': slot,
                        'age_hours': 0,  # Just created
                        'liquidity_usd': 0,
                        'volume_24h': 0,
                        'price_usd': 0,
                        'source': 'solana_rpc_direct',
                        'chain_id': 'solana',
                        'created_timestamp': int(time.time())
                    }
            
        except Exception as e:
            return None
        
        return None
    
    def get_program_accounts_tokens(self, limit: int = 100) -> List[Dict]:
        """
        Méthode alternative: obtenir les comptes de programme récents
        """
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getProgramAccounts",
                "params": [
                    self.TOKEN_PROGRAM,
                    {
                        "encoding": "base64",
                        "filters": [
                            {
                                "dataSize": 82  # Taille d'un compte mint
                            }
                        ]
                    }
                ]
            }
            
            response = self.session.post(self.rpc_url, json=payload, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                accounts = result.get('result', [])
                
                # Parser les comptes pour extraire les infos des tokens
                tokens = []
                for account in accounts[:limit]:
                    try:
                        pubkey = account.get('pubkey')
                        if pubkey:
                            tokens.append({
                                'token_address': pubkey,
                                'symbol': 'UNKNOWN',
                                'name': 'RPC Discovered Token',
                                'decimals': 9,
                                'age_hours': 0,
                                'liquidity_usd': 0,
                                'volume_24h': 0,
                                'price_usd': 0,
                                'source': 'rpc_program_accounts',
                                'chain_id': 'solana',
                                'created_timestamp': int(time.time())
                            })
                    except Exception:
                        continue
                
                self.logger.info(f"📊 RPC Program Accounts: Found {len(tokens)} token accounts")
                return tokens
            
        except Exception as e:
            self.logger.error(f"Error getting program accounts: {e}")
        
        return []

# Intégration avec votre bot
def add_rpc_discovery_to_bot(bot_instance):
    """Ajouter la découverte RPC directe au bot"""
    
    # Utiliser le RPC du bot
    rpc_url = bot_instance.config['solana']['rpc_url']
    rpc_discovery = SolanaDirectDiscovery(rpc_url)
    
    async def get_newest_tokens_rpc(hours_back: int = 24) -> List[Dict]:
        """Découverte via RPC direct"""
        try:
            # Convertir heures en slots approximatifs (400ms par slot)
            slots_back = int(hours_back * 3600 / 0.4)
            slots_back = min(slots_back, 5000)  # Limiter pour éviter trop d'appels
            
            # Méthode 1: Scanner les blocs récents
            block_tokens = rpc_discovery.get_recent_token_creations(slots_back)
            
            # Méthode 2: Program accounts (plus simple)
            program_tokens = rpc_discovery.get_program_accounts_tokens(50)
            
            # Combiner
            all_tokens = block_tokens + program_tokens
            
            # Dédupliquer
            seen = set()
            unique_tokens = []
            for token in all_tokens:
                addr = token['token_address']
                if addr not in seen:
                    seen.add(addr)
                    unique_tokens.append(token)
            
            bot_instance.logger.info(f"🔗 RPC Discovery: Found {len(unique_tokens)} tokens")
            return unique_tokens
            
        except Exception as e:
            bot_instance.logger.error(f"Error in RPC discovery: {e}")
            return []
    
    bot_instance.get_newest_tokens_rpc = get_newest_tokens_rpc
    return rpc_discovery

# Test
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    
    rpc = SolanaDirectDiscovery()
    
    print("🔗 Testing Solana RPC Direct Discovery...")
    
    # Test program accounts method (plus simple)
    tokens = rpc.get_program_accounts_tokens(10)
    print(f"📊 Found {len(tokens)} token accounts")
    
    for token in tokens[:5]:
        print(f"  - {token['token_address'][:8]}...")