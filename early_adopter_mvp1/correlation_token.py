import asyncio
import aiohttp
import json
import argparse
import os
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import time
from typing import Dict, List, Set, Tuple
import logging
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

# Configuration depuis .env
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")
if not HELIUS_API_KEY:
    raise ValueError("HELIUS_API_KEY non trouvée dans le fichier .env")

HELIUS_RPC_URL = f"https://rpc.helius.xyz/?api-key={HELIUS_API_KEY}"

# Charger les adresses depuis .env
whale_addresses_str = os.getenv("WHALE_ADDRESSES")
if not whale_addresses_str:
    raise ValueError("WHALE_ADDRESSES non trouvées dans le fichier .env")

# Parser la liste d'adresses de manière plus robuste
try:
    cleaned_str = whale_addresses_str.replace('\n', '').replace('\r', '').strip()
    
    if cleaned_str.startswith('[') and cleaned_str.endswith(']'):
        content = cleaned_str[1:-1]
        addresses = []
        current_addr = ""
        in_quotes = False
        
        for char in content:
            if char in ['"', "'"]:
                in_quotes = not in_quotes
            elif char == ',' and not in_quotes:
                addr = current_addr.strip().strip('"\'').strip()
                if addr:
                    addresses.append(addr)
                current_addr = ""
            else:
                current_addr += char
        
        addr = current_addr.strip().strip('"\'').strip()
        if addr:
            addresses.append(addr)
            
        WHALE_ADDRESSES = addresses
    else:
        WHALE_ADDRESSES = [addr.strip().strip('"\'') for addr in cleaned_str.split(',')]
        WHALE_ADDRESSES = [addr for addr in WHALE_ADDRESSES if addr]
        
except Exception as e:
    raise ValueError(f"Erreur parsing WHALE_ADDRESSES: {e}")

if not WHALE_ADDRESSES:
    raise ValueError("Aucune adresse trouvée dans WHALE_ADDRESSES")

# Compteur global de requêtes API
api_request_counter = 0
DEBUG_MODE = False

# Configuration de surveillance
CHECK_INTERVAL = 60
LOOKBACK_MINUTES = 60
MIN_CORRELATION_THRESHOLD = 2
MIN_TRANSACTION_VALUE = 1

class SolanaCorrelationMonitor:
    def __init__(self):
        self.session = None
        self.token_activity = defaultdict(list)
        self.correlation_scores = defaultdict(int)
        self.last_check_time = datetime.now()
        self.requests_this_cycle = 0
        self.total_requests = 0
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def log_api_request(self, request_type: str = "API"):
        """Logger et compter les requêtes API"""
        global api_request_counter
        api_request_counter += 1
        self.requests_this_cycle += 1
        self.total_requests += 1
        if DEBUG_MODE:
            logger.debug(f"[{api_request_counter}] {request_type}")

    async def get_address_signatures(self, address: str, limit: int = 50) -> List[Dict]:
        """Récupère les signatures d'une adresse"""
        self.log_api_request("getSignatures")
        
        payload = {
            "jsonrpc": "2.0",
            "id": f"sig-{api_request_counter}",
            "method": "getSignaturesForAddress",
            "params": [address, {"limit": limit, "commitment": "confirmed"}]
        }
        
        try:
            async with self.session.post(HELIUS_RPC_URL, json=payload) as response:
                if response.status == 429:
                    logger.warning(f"Rate limit pour {address[:8]}...")
                    await asyncio.sleep(2)
                    return await self.get_address_signatures(address, limit)
                
                data = await response.json()
                result = data.get("result", [])
                
                if DEBUG_MODE:
                    logger.debug(f"[{api_request_counter}] {address[:8]}...: {len(result)} signatures")
                
                return result
                
        except Exception as e:
            logger.error(f"Erreur signatures {address[:8]}...: {e}")
            return []

    async def get_transaction_with_inner(self, signature: str) -> Dict:
        """Récupère une transaction avec les inner instructions"""
        self.log_api_request("getTransaction")
        
        payload = {
            "jsonrpc": "2.0",
            "id": f"tx-{api_request_counter}",
            "method": "getTransaction",
            "params": [
                signature,
                {
                    "encoding": "jsonParsed",
                    "maxSupportedTransactionVersion": 0,
                    "commitment": "confirmed"
                }
            ]
        }
        
        try:
            async with self.session.post(HELIUS_RPC_URL, json=payload) as response:
                if response.status == 429:
                    await asyncio.sleep(1)
                    return await self.get_transaction_with_inner(signature)
                
                data = await response.json()
                result = data.get("result", {})
                
                if DEBUG_MODE:
                    inner_count = len(result.get("meta", {}).get("innerInstructions", []))
                    logger.debug(f"[{api_request_counter}] TX {signature[:8]}...: {inner_count} inner instructions")
                
                return result
                
        except Exception as e:
            logger.error(f"Erreur transaction {signature[:8]}...: {e}")
            return {}

    def parse_comprehensive_transfers(self, tx_data: Dict, address: str, signature: str) -> List[Tuple[str, str, float, float]]:
        """Parse complet avec détection des swaps Pump.fun/Jupiter/Meteora"""
        transfers = []
        
        if not tx_data or tx_data.get("meta", {}).get("err"):
            return transfers
        
        sig_short = signature[:8] + "..."
        
        # METHODE 1: Analyser les changements de balance (le plus fiable)
        pre_balances = tx_data.get("meta", {}).get("preTokenBalances", [])
        post_balances = tx_data.get("meta", {}).get("postTokenBalances", [])
        accounts = tx_data.get("transaction", {}).get("message", {}).get("accountKeys", [])
        
        # Trouver l'index de notre adresse (gestion robuste des formats)
        target_account_index = None
        for i, account in enumerate(accounts):
            try:
                if isinstance(account, str):
                    account_key = account
                elif isinstance(account, dict):
                    account_key = account.get("pubkey", "")
                else:
                    continue
                    
                if account_key == address:
                    target_account_index = i
                    break
            except Exception as e:
                if DEBUG_MODE:
                    logger.debug(f"        Erreur parsing account {i}: {e}")
                continue
        
        if DEBUG_MODE:
            logger.debug(f"    [{api_request_counter}] WALLET {address[:8]}... | TX {sig_short}")
            logger.debug(f"        Balances: {len(pre_balances)} pre + {len(post_balances)} post")
            if target_account_index is not None:
                logger.debug(f"        Adresse trouvée à l'index {target_account_index}")
        
        # NOUVEAU: Créer un mapping des comptes pour détecter les patterns
        account_map = {}
        for i, account in enumerate(accounts):
            try:
                if isinstance(account, str):
                    account_map[i] = account
                elif isinstance(account, dict):
                    account_map[i] = account.get("pubkey", "")
            except:
                continue
        
        # Analyser les changements de balance
        balance_changes = {}
        
        # Pre balances
        for pre_balance in pre_balances:
            account_index = pre_balance.get("accountIndex")
            if account_index == target_account_index:
                mint = pre_balance.get("mint")
                amount = float(pre_balance.get("uiTokenAmount", {}).get("uiAmount", 0))
                balance_changes[mint] = [amount, 0]
        
        # Post balances
        for post_balance in post_balances:
            account_index = post_balance.get("accountIndex")
            if account_index == target_account_index:
                mint = post_balance.get("mint")
                amount = float(post_balance.get("uiTokenAmount", {}).get("uiAmount", 0))
                
                if mint in balance_changes:
                    balance_changes[mint][1] = amount
                else:
                    balance_changes[mint] = [0, amount]
        
        # Calculer les changements
        for mint, (pre_amount, post_amount) in balance_changes.items():
            change = post_amount - pre_amount
            
            if abs(change) > 0.001:
                action = "RECEIVE" if change > 0 else "SEND"
                value_usd = 0
                
                if DEBUG_MODE:
                    logger.debug(f"        Balance change: {action} {abs(change):,.3f} {mint}")
                
                transfers.append((mint, action, abs(change), value_usd))
        
        # METHODE 2: Parser les instructions principales avec détection de patterns
        instructions = tx_data.get("transaction", {}).get("message", {}).get("instructions", [])
        
        if DEBUG_MODE:
            logger.debug(f"        {len(instructions)} instructions principales")
        
        self.parse_instructions_with_patterns(instructions, address, transfers, account_map, "main")
        
        # METHODE 3: Parser les inner instructions
        inner_instructions = tx_data.get("meta", {}).get("innerInstructions", [])
        
        if DEBUG_MODE and inner_instructions:
            total_inner = sum(len(inner.get("instructions", [])) for inner in inner_instructions)
            logger.debug(f"        {len(inner_instructions)} groupes inner ({total_inner} instructions)")
        
        for inner_group in inner_instructions:
            inner_inst_list = inner_group.get("instructions", [])
            self.parse_instructions_with_patterns(inner_inst_list, address, transfers, account_map, "inner")
        
        # METHODE 4: Analyser les transferts SOL natifs
        self.parse_sol_transfers(tx_data, address, target_account_index, transfers)
        
        if DEBUG_MODE:
            if transfers:
                logger.debug(f"        RESULTAT: {len(transfers)} transferts détectés")
                for token_mint, action, amount, value in transfers:
                    token_short = token_mint if token_mint == "SOL" else f"{token_mint[:12]}..."
                    logger.debug(f"          {action} {amount:,.3f} {token_short}")
            else:
                logger.debug(f"        RESULTAT: Aucun transfert détecté")
            logger.debug("")
        
        return transfers

    def parse_instructions_with_patterns(self, instructions: List[Dict], address: str, transfers: List, account_map: Dict, inst_type: str):
        """Parse avec détection des patterns Pump.fun/Jupiter/Meteora"""
        for i, instruction in enumerate(instructions):
            try:
                program_id = instruction.get("programId", "")
                
                # Identifier le type de programme
                program_type = self.identify_program_type(program_id)
                
                if "parsed" in instruction:
                    parsed = instruction["parsed"]
                    inst_type_name = parsed.get("type", "unknown")
                    
                    if DEBUG_MODE:
                        logger.debug(f"        [{inst_type}-{i:2d}] {program_id[:8]}... ({program_type}) : {inst_type_name}")
                    
                    # Transfert SPL Token classique
                    if inst_type_name == "transfer":
                        self.parse_spl_transfer(parsed, address, transfers)
                    
                    # Autres instructions
                    elif inst_type_name in ["mintTo", "burn", "approve", "create"]:
                        if DEBUG_MODE:
                            logger.debug(f"            {inst_type_name}")
                
                else:
                    # Instructions non-parsées - NOUVEAU PARSING
                    if DEBUG_MODE:
                        logger.debug(f"        [{inst_type}-{i:2d}] {program_id[:8]}... ({program_type}) : non-parsée")
                    
                    # Analyser selon le type de programme
                    if program_type in ["PUMP_FUN", "JUPITER", "METEORA", "RAYDIUM"]:
                        self.parse_dex_instruction(instruction, address, transfers, account_map, program_type)
                        
            except Exception as e:
                if DEBUG_MODE:
                    logger.debug(f"        Erreur parsing instruction {i}: {e}")
                continue

    def identify_program_type(self, program_id: str) -> str:
        """Identifie le type de programme pour la détection de patterns"""
        # Programmes DEX connus
        dex_programs = {
            "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P": "PUMP_FUN",
            "JUP6LkbZogxGo2dtjzF8ZGmKj1Q38LkZVuUBZq5Q5tV": "JUPITER", 
            "JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB": "JUPITER",
            "Eo7WjKq67rjJQSZxS6z3YkapzY3eMj6Xy8X5EQVn5UaB": "METEORA",
            "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "RAYDIUM",
            "27haf8L6oxUeXrHrgEgsexjSY5hbVUWEmvv9Nyxg8vQv": "RAYDIUM_AMM"
        }
        
        # Programmes système
        system_programs = {
            "11111111111111111111111111111111": "SYSTEM",
            "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA": "SPL_TOKEN",
            "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL": "ASSOCIATED_TOKEN",
            "ComputeBudget111111111111111111111111111111": "COMPUTE_BUDGET"
        }
        
        if program_id in dex_programs:
            return dex_programs[program_id]
        elif program_id in system_programs:
            return system_programs[program_id]
        else:
            return "UNKNOWN"

    def parse_dex_instruction(self, instruction: Dict, address: str, transfers: List, account_map: Dict, program_type: str):
        """Parse les instructions DEX non-parsées en analysant les comptes"""
        try:
            accounts = instruction.get("accounts", [])
            
            if DEBUG_MODE:
                logger.debug(f"            Analyse {program_type}: {len(accounts)} comptes impliqués")
            
            # Pour les DEX, analyser les comptes pour détecter les patterns
            user_accounts = []
            vault_accounts = []
            mint_accounts = []
            
            for account_index in accounts:
                if isinstance(account_index, int) and account_index in account_map:
                    account_addr = account_map[account_index]
                    
                    # Notre adresse utilisateur
                    if account_addr == address:
                        user_accounts.append(account_addr)
                    # Détecter les vaults/pools (patterns typiques)
                    elif any(keyword in account_addr for keyword in ["vault", "pool", "amm", "market"]):
                        vault_accounts.append(account_addr)
                    # Potentiels token mints (longueur typique)
                    elif len(account_addr) >= 32:
                        mint_accounts.append(account_addr)
            
            if DEBUG_MODE and (user_accounts or vault_accounts):
                logger.debug(f"            Pattern détecté: user={len(user_accounts)}, vaults={len(vault_accounts)}, mints={len(mint_accounts)}")
            
            # Si notre adresse est impliquée avec des vaults, c'est probablement un swap
            if user_accounts and vault_accounts:
                if DEBUG_MODE:
                    logger.debug(f"            SWAP {program_type} détecté - analyse des mints...")
                
                # Analyser les mints potentiels pour ce swap
                for mint_candidate in mint_accounts:
                    # Estimer si c'est un receive ou send basé sur les patterns
                    # (logique simplifiée - dans la réalité il faudrait plus d'analyse)
                    if program_type == "PUMP_FUN":
                        # Pump.fun : généralement achat de memecoins
                        if DEBUG_MODE:
                            logger.debug(f"            >>> PUMP.FUN pattern: potentiel achat {mint_candidate[:12]}...")
                        # Ne pas ajouter automatiquement car on n'a pas les montants
                    elif program_type in ["JUPITER", "METEORA"]:
                        if DEBUG_MODE:
                            logger.debug(f"            >>> {program_type} pattern détecté")
                
        except Exception as e:
            if DEBUG_MODE:
                logger.debug(f"            Erreur analyse DEX: {e}")

    def parse_spl_transfer(self, parsed: Dict, address: str, transfers: List):
        """Parse un transfert SPL Token standard"""
        try:
            info = parsed.get("info", {})
            source = info.get("source", "")
            destination = info.get("destination", "")
            amount_str = info.get("amount", "0")
            mint = info.get("mint", "UNKNOWN")
            
            try:
                amount = float(amount_str)
            except (ValueError, TypeError):
                amount = 0
            
            # Vérifier si notre adresse est impliquée
            action = None
            if address in destination:
                action = "RECEIVE"
            elif address in source:
                action = "SEND"
            
            if action and amount > 0:
                # Éviter les doublons
                duplicate = False
                for existing_mint, existing_action, existing_amount, _ in transfers:
                    if (existing_mint == mint and existing_action == action and 
                        abs(existing_amount - amount) < amount * 0.01):
                        duplicate = True
                        break
                
                if not duplicate:
                    if DEBUG_MODE:
                        logger.debug(f"            >>> SPL {action} {amount:,.0f} {mint[:12]}...")
                    transfers.append((mint, action, amount, 0))
                    
        except Exception as e:
            if DEBUG_MODE:
                logger.debug(f"            Erreur SPL transfer: {e}")

    def parse_sol_transfers(self, tx_data: Dict, address: str, target_account_index: int, transfers: List):
        """Parse les transferts SOL natifs"""
        try:
            pre_sol = 0
            post_sol = 0
            
            # SOL balances
            pre_sol_balances = tx_data.get("meta", {}).get("preBalances", [])
            post_sol_balances = tx_data.get("meta", {}).get("postBalances", [])
            
            if target_account_index is not None:
                if target_account_index < len(pre_sol_balances):
                    pre_sol = pre_sol_balances[target_account_index] / 1e9
                if target_account_index < len(post_sol_balances):
                    post_sol = post_sol_balances[target_account_index] / 1e9
            
            sol_change = post_sol - pre_sol
            if abs(sol_change) > 0.0001:  # Plus de 0.0001 SOL
                action = "RECEIVE" if sol_change > 0 else "SEND"
                value_usd = abs(sol_change) * 200  # ~200$ par SOL
                
                if DEBUG_MODE:
                    logger.debug(f"        SOL change: {action} {abs(sol_change):.6f} SOL (${value_usd:.2f})")
                
                transfers.append(("SOL", action, abs(sol_change), value_usd))
                
        except Exception as e:
            if DEBUG_MODE:
                logger.debug(f"        Erreur SOL parsing: {e}")

    def detect_token_from_accounts(self, instruction: Dict, address: str, account_map: Dict) -> List[str]:
        """Détecte les tokens impliqués en analysant les comptes d'une instruction"""
        potential_mints = []
        
        try:
            accounts = instruction.get("accounts", [])
            
            # Analyser chaque compte
            for account_index in accounts:
                if isinstance(account_index, int) and account_index in account_map:
                    account_addr = account_map[account_index]
                    
                    # Patterns de détection de mints
                    # Les mints ont généralement des caractéristiques spécifiques
                    if (len(account_addr) >= 32 and 
                        account_addr != address and 
                        not any(keyword in account_addr.lower() for keyword in [
                            "system", "token", "compute", "program", "vault", "authority"
                        ])):
                        potential_mints.append(account_addr)
            
            # Filtrer les doublons
            potential_mints = list(set(potential_mints))
            
            if DEBUG_MODE and potential_mints:
                logger.debug(f"            Mints potentiels: {len(potential_mints)}")
                for mint in potential_mints[:3]:  # Afficher les 3 premiers
                    logger.debug(f"              - {mint[:12]}...")
            
            return potential_mints
            
        except Exception as e:
            if DEBUG_MODE:
                logger.debug(f"            Erreur détection mints: {e}")
            return []

    def parse_instructions(self, instructions: List[Dict], address: str, transfers: List, inst_type: str):
        """Parse une liste d'instructions avec gestion d'erreurs robuste"""
        for i, instruction in enumerate(instructions):
            try:
                if "parsed" in instruction:
                    parsed = instruction["parsed"]
                    inst_type_name = parsed.get("type", "unknown")
                    
                    if DEBUG_MODE:
                        prog_id = instruction.get("programId", "")[:8] + "..."
                        logger.debug(f"        [{inst_type}-{i:2d}] {prog_id} : {inst_type_name}")
                    
                    # Transfert SPL Token
                    if inst_type_name == "transfer":
                        info = parsed.get("info", {})
                        source = info.get("source", "")
                        destination = info.get("destination", "")
                        amount_str = info.get("amount", "0")
                        mint = info.get("mint", "UNKNOWN")
                        
                        try:
                            amount = float(amount_str)
                        except (ValueError, TypeError):
                            amount = 0
                        
                        # Vérifier si notre adresse est impliquée
                        action = None
                        if address in destination:
                            action = "RECEIVE"
                        elif address in source:
                            action = "SEND"
                        
                        if action and amount > 0:
                            # Éviter les doublons
                            duplicate = False
                            for existing_mint, existing_action, existing_amount, _ in transfers:
                                if (existing_mint == mint and existing_action == action and 
                                    abs(existing_amount - amount) < amount * 0.01):
                                    duplicate = True
                                    break
                            
                            if not duplicate:
                                if DEBUG_MODE:
                                    logger.debug(f"        >>> {action} {amount:,.0f} {mint}")
                                transfers.append((mint, action, amount, 0))
                    
                    # Autres instructions intéressantes
                    elif inst_type_name in ["mintTo", "burn", "approve", "create"]:
                        if DEBUG_MODE:
                            logger.debug(f"        >>> {inst_type_name}")
                else:
                    # Instructions non-parsées
                    if DEBUG_MODE:
                        prog_id = instruction.get("programId", "")[:8] + "..."
                        logger.debug(f"        [{inst_type}-{i:2d}] {prog_id} : non-parsée")
                        
            except Exception as e:
                if DEBUG_MODE:
                    logger.debug(f"        Erreur parsing instruction {i}: {e}")
                continue

    async def get_multiple_addresses_batch(self, addresses: List[str], limit: int = 50) -> Dict[str, List[Dict]]:
        """Batch processing ultra-optimisé pour économiser les crédits"""
        batch_size = 15  # Augmenté de 10 à 15 pour moins de requêtes
        all_results = {}
        
        for i in range(0, len(addresses), batch_size):
            batch = addresses[i:i + batch_size]
            batch_num = i//batch_size + 1
            total_batches = (len(addresses)-1)//batch_size + 1
            
            logger.info(f"Batch {batch_num}/{total_batches}: {len(batch)} adresses")
            
            # Exécuter toutes les requêtes du batch en parallèle (plus rapide)
            tasks = [self.get_address_signatures(address, limit) for address in batch]
            
            try:
                # Attendre toutes les requêtes simultanément
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for address, result in zip(batch, results):
                    if isinstance(result, Exception):
                        logger.error(f"Erreur batch {address[:8]}...: {result}")
                        all_results[address] = []
                    else:
                        all_results[address] = result
                
                # Délai réduit entre batches
                if i + batch_size < len(addresses):
                    await asyncio.sleep(0.3)  # Réduit de 0.5s à 0.3s
                    
            except Exception as e:
                logger.error(f"Erreur batch complet: {e}")
                # Fallback: traiter une par une
                for address in batch:
                    try:
                        result = await self.get_address_signatures(address, limit)
                        all_results[address] = result
                        await asyncio.sleep(0.1)
                    except Exception as addr_e:
                        logger.error(f"Erreur fallback {address[:8]}...: {addr_e}")
                        all_results[address] = []
                
        logger.info(f"Batch terminé: {len(all_results)} adresses | {self.requests_this_cycle} requêtes API")
        return all_results

    async def get_transactions_batch_optimized(self, signatures_with_addresses: List[Tuple[str, str]]) -> Dict[str, Dict]:
        """Batch ultra-optimisé pour les détails de transactions"""
        results = {}
        batch_size = 8  # Traiter 8 transactions simultanément
        
        total_sigs = len(signatures_with_addresses)
        logger.info(f"Analyse de {total_sigs} transactions en batches de {batch_size}...")
        
        for i in range(0, total_sigs, batch_size):
            batch = signatures_with_addresses[i:i + batch_size]
            batch_num = i//batch_size + 1
            total_batches = (total_sigs-1)//batch_size + 1
            
            if DEBUG_MODE:
                logger.debug(f"Transaction batch {batch_num}/{total_batches}: {len(batch)} transactions")
            
            # Exécuter en parallèle
            tasks = [self.get_transaction_with_inner(sig) for sig, addr in batch]
            
            try:
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for (signature, address), result in zip(batch, batch_results):
                    if isinstance(result, Exception):
                        if DEBUG_MODE:
                            logger.debug(f"Erreur TX {signature[:8]}...: {result}")
                        results[signature] = {}
                    else:
                        results[signature] = result
                
                # Petit délai entre batches de transactions
                if i + batch_size < total_sigs:
                    await asyncio.sleep(0.1)  # Très court délai
                    
            except Exception as e:
                logger.error(f"Erreur batch transactions: {e}")
                # Fallback
                for signature, address in batch:
                    try:
                        result = await self.get_transaction_with_inner(signature)
                        results[signature] = result
                        await asyncio.sleep(0.05)
                    except Exception:
                        results[signature] = {}
        
        return results

    async def check_recent_activity_optimized(self) -> Dict[str, List[Tuple[str, str, float, float]]]:
        """Version ultra-optimisée avec cache intelligent"""
        self.requests_this_cycle = 0
        cycle_start_time = time.time()
        
        logger.info(f"Vérification de {len(WHALE_ADDRESSES)} adresses...")
        
        cutoff_time = datetime.now() - timedelta(minutes=LOOKBACK_MINUTES)
        recent_activity = {}
        
        # Étape 1: Récupérer toutes les signatures (OPTIMISÉ)
        logger.info("Étape 1/3: Signatures batch...")
        all_signatures = await self.get_multiple_addresses_batch(WHALE_ADDRESSES, limit=20)
        signatures_requests = self.requests_this_cycle
        
        # Étape 2: Filtrer et préparer (PAS DE REQUÊTE)
        signatures_to_fetch = []
        
        if DEBUG_MODE:
            logger.debug("SIGNATURES RÉCENTES:")
        
        for address, signatures in all_signatures.items():
            recent_activity[address] = []
            recent_count = 0
            
            for sig_info in signatures:
                tx_time = datetime.fromtimestamp(sig_info.get("blockTime", 0))
                if tx_time < cutoff_time:
                    break
                    
                signature = sig_info["signature"]
                signatures_to_fetch.append((signature, address))
                recent_count += 1
            
            if DEBUG_MODE:
                logger.debug(f"    {address[:8]}...: {recent_count} transactions récentes")
        
        transaction_requests_needed = len(signatures_to_fetch)
        logger.info(f"Étape 2/3: {transaction_requests_needed} transactions à analyser")
        
        # Étape 3: Analyser en batch ultra-optimisé
        if signatures_to_fetch:
            logger.info("Étape 3/3: Analyse batch des transactions...")
            
            if DEBUG_MODE:
                logger.debug("ANALYSE TRANSACTIONS:")
            
            transaction_details = await self.get_transactions_batch_optimized(signatures_to_fetch)
            transaction_requests = self.requests_this_cycle - signatures_requests
            
            # Parser tous les résultats
            for signature, address in signatures_to_fetch:
                tx_details = transaction_details.get(signature, {})
                if tx_details:
                    transfers = self.parse_comprehensive_transfers(tx_details, address, signature)
                    recent_activity[address].extend(transfers)
        
        # Statistiques détaillées
        cycle_time = time.time() - cycle_start_time
        total_requests = self.requests_this_cycle
        
        logger.info(
            f"Cycle terminé en {cycle_time:.2f}s | "
            f"Requêtes: {signatures_requests} signatures + {transaction_requests_needed} transactions = {total_requests} total | "
            f"Cumulé: {self.total_requests}"
        )
        
        if DEBUG_MODE:
            efficiency = len(WHALE_ADDRESSES) / total_requests if total_requests > 0 else 0
            logger.debug(f"Efficacité: {efficiency:.1f} adresses/requête")
        
        return recent_activity

    def analyze_correlations(self, recent_activity: Dict) -> List[Dict]:
        """Analyse les corrélations"""
        token_receivers = defaultdict(list)
        token_senders = defaultdict(list)
        
        if DEBUG_MODE:
            logger.debug("ANALYSE DES CORRÉLATIONS:")
        
        for address, activities in recent_activity.items():
            if DEBUG_MODE and activities:
                logger.debug(f"    {address[:8]}...: {len(activities)} activités")
            
            for token_mint, action, amount, value in activities:
                if action in ["BUY", "RECEIVE"]:
                    token_receivers[token_mint].append({
                        'address': address,
                        'amount': amount,
                        'value': value,
                        'action': action
                    })
                elif action in ["SELL", "SEND"]:
                    token_senders[token_mint].append({
                        'address': address,
                        'amount': amount,
                        'value': value,
                        'action': action
                    })
        
        correlated_tokens = []
        
        # Corrélations de réception
        for token_mint, receivers in token_receivers.items():
            if len(receivers) >= MIN_CORRELATION_THRESHOLD:
                total_amount = sum(r['amount'] for r in receivers)
                total_value = sum(r['value'] for r in receivers)
                
                correlated_tokens.append({
                    'token_mint': token_mint,
                    'receiver_count': len(receivers),
                    'receivers': receivers,
                    'total_amount': total_amount,
                    'total_value': total_value,
                    'correlation_score': len(receivers) / len(WHALE_ADDRESSES),
                    'timestamp': datetime.now(),
                    'action_type': 'COORDINATED_RECEIVE'
                })
        
        # Corrélations d'envoi
        for token_mint, senders in token_senders.items():
            if len(senders) >= MIN_CORRELATION_THRESHOLD:
                total_amount = sum(s['amount'] for s in senders)
                total_value = sum(s['value'] for s in senders)
                
                correlated_tokens.append({
                    'token_mint': token_mint,
                    'sender_count': len(senders),
                    'senders': senders,
                    'total_amount': total_amount,
                    'total_value': total_value,
                    'correlation_score': len(senders) / len(WHALE_ADDRESSES),
                    'timestamp': datetime.now(),
                    'action_type': 'COORDINATED_SEND'
                })
        
        correlated_tokens.sort(key=lambda x: x['correlation_score'], reverse=True)
        return correlated_tokens

    async def monitor_loop(self):
        """Boucle principale optimisée"""
        logger.info(f"Démarrage surveillance {len(WHALE_ADDRESSES)} adresses...")
        logger.info(f"Intervalle: {CHECK_INTERVAL}s | Lookback: {LOOKBACK_MINUTES}min")
        if DEBUG_MODE:
            logger.info("MODE DEBUG ACTIVÉ - Parsing manuel détaillé")
        
        cycle_count = 0
        
        while True:
            try:
                cycle_count += 1
                cycle_start_time = time.time()
                
                logger.info(f"\nCYCLE #{cycle_count}")
                logger.info(f"Requêtes totales: {self.total_requests}")
                
                # Vérifier l'activité
                recent_activity = await self.check_recent_activity_optimized()
                
                # Debug summary
                if DEBUG_MODE:
                    self.debug_display_wallet_activity(recent_activity)
                
                # Analyser les corrélations
                correlations = self.analyze_correlations(recent_activity)
                
                # Résultats
                cycle_time = time.time() - cycle_start_time
                requests_per_minute = (self.requests_this_cycle / cycle_time) * 60 if cycle_time > 0 else 0
                
                logger.info(f"\nRÉSULTATS CYCLE #{cycle_count}")
                logger.info(f"Temps: {cycle_time:.2f}s")
                logger.info(f"Requêtes ce cycle: {self.requests_this_cycle}")
                logger.info(f"Vitesse: {requests_per_minute:.1f} req/min")
                logger.info(f"Total: {self.total_requests} requêtes")
                
                if correlations:
                    logger.info(f"{len(correlations)} corrélations détectées !")
                    
                    for i, correlation in enumerate(correlations[:5], 1):
                        action_count = correlation.get('receiver_count', correlation.get('sender_count', 0))
                        
                        # Affichage de l'adresse complète du token
                        token_address = correlation['token_mint']
                        
                        logger.info(
                            f"  {i}. Token: {token_address}"
                        )
                        logger.info(
                            f"     {correlation['action_type']} | "
                            f"{action_count} adresses | "
                            f"Score: {correlation['correlation_score']:.1%} | "
                            f"{correlation['total_amount']:,.3f} tokens | "
                            f"${correlation['total_value']:.2f}"
                        )
                        
                        # Adresses impliquées
                        addresses = correlation.get('receivers', correlation.get('senders', []))
                        addr_list = [addr['address'][:8] + '...' for addr in addresses[:3]]
                        if len(addresses) > 3:
                            addr_list.append(f"et {len(addresses)-3} autres")
                        logger.info(f"     Adresses: {', '.join(addr_list)}")
                else:
                    logger.info("Aucune corrélation significative détectée")
                
                # Coût
                estimated_cost_usd = self.total_requests * 0.0001  # RPC standard ~0.01¢
                logger.info(f"Coût estimé: ${estimated_cost_usd:.4f}")
                
                # Attente
                sleep_time = max(0, CHECK_INTERVAL - cycle_time)
                logger.info(f"Attente {sleep_time:.0f}s...")
                await asyncio.sleep(sleep_time)
                
            except KeyboardInterrupt:
                logger.info(f"\nArrêt demandé. Total requêtes: {self.total_requests}")
                break
            except Exception as e:
                logger.error(f"Erreur: {e}")
                await asyncio.sleep(30)

    def debug_display_wallet_activity(self, recent_activity: Dict):
        """Affichage debug optimisé"""
        if not DEBUG_MODE:
            return
            
        logger.debug("\nRÉSUMÉ PAR WALLET:")
        
        active_wallets = {addr: activities for addr, activities in recent_activity.items() if activities}
        inactive_count = len(WHALE_ADDRESSES) - len(active_wallets)
        
        if active_wallets:
            logger.debug(f"WALLETS ACTIFS ({len(active_wallets)}):")
            
            for address, activities in active_wallets.items():
                addr_short = address[:8] + "..."
                total_value = sum(activity[3] for activity in activities)
                logger.debug(f"    {addr_short} ({len(activities)} activités, ${total_value:.2f}):")
                
                # Grouper par token
                token_activity = defaultdict(list)
                for token_mint, action, amount, value in activities:
                    token_activity[token_mint].append((action, amount, value))
                
                for token_mint, actions in token_activity.items():
                    receives = [a for a in actions if a[0] in ["BUY", "RECEIVE"]]
                    sends = [a for a in actions if a[0] in ["SELL", "SEND"]]
                    
                    if receives and sends:
                        recv_amt = sum(a[1] for a in receives)
                        send_amt = sum(a[1] for a in sends)
                        recv_val = sum(a[2] for a in receives)
                        send_val = sum(a[2] for a in sends)
                        recv_count = len(receives)
                        send_count = len(sends)
                        logger.debug(f"        {token_mint}:")
                        logger.debug(f"          {recv_count} reçu(s): {recv_amt:,.3f} tokens (${recv_val:.2f})")
                        logger.debug(f"          {send_count} envoyé(s): {send_amt:,.3f} tokens (${send_val:.2f})")
                    elif receives:
                        recv_amt = sum(a[1] for a in receives)
                        recv_val = sum(a[2] for a in receives)
                        recv_count = len(receives)
                        logger.debug(f"        {token_mint}:")
                        logger.debug(f"          {recv_count} reçu(s): {recv_amt:,.3f} tokens (${recv_val:.2f})")
                    elif sends:
                        send_amt = sum(a[1] for a in sends)
                        send_val = sum(a[2] for a in sends)
                        send_count = len(sends)
                        logger.debug(f"        {token_mint}:")
                        logger.debug(f"          {send_count} envoyé(s): {send_amt:,.3f} tokens (${send_val:.2f})")
        
        if inactive_count > 0:
            logger.debug(f"WALLETS INACTIFS: {inactive_count} adresses")
        
        logger.debug("")

def parse_arguments():
    """Parse les arguments de ligne de commande"""
    parser = argparse.ArgumentParser(
        description="Solana Token Correlation Monitor - Parsing manuel optimisé",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples d'utilisation:
  python correlation_token.py                    # Mode normal
  python correlation_token.py --debug            # Mode debug avec détails
  python correlation_token.py --debug --interval 30   # Debug rapide
        """
    )
    
    parser.add_argument('--debug', action='store_true', help='Mode debug détaillé')
    parser.add_argument('--interval', type=int, default=60, help='Intervalle en secondes (défaut: 60)')
    parser.add_argument('--lookback', type=int, default=60, help='Fenêtre d\'analyse en minutes (défaut: 60)')
    parser.add_argument('--min-correlation', type=int, default=2, help='Seuil de corrélation (défaut: 2)')
    
    return parser.parse_args()

async def main():
    """Fonction principale"""
    global DEBUG_MODE, CHECK_INTERVAL, LOOKBACK_MINUTES, MIN_CORRELATION_THRESHOLD
    
    args = parse_arguments()
    
    DEBUG_MODE = args.debug
    CHECK_INTERVAL = args.interval
    LOOKBACK_MINUTES = args.lookback
    MIN_CORRELATION_THRESHOLD = args.min_correlation
    
    if DEBUG_MODE:
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
    else:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', datefmt='%H:%M:%S')
    
    global logger
    logger = logging.getLogger(__name__)
    
    print("CONFIGURATION PARSING MANUEL")
    print(f"  API Key: {HELIUS_API_KEY[:8]}...{HELIUS_API_KEY[-4:]}")
    print(f"  Adresses: {len(WHALE_ADDRESSES)}")
    print(f"  Mode: RPC standard + parsing manuel (économique)")
    print(f"  Intervalle: {CHECK_INTERVAL}s")
    print(f"  Lookback: {LOOKBACK_MINUTES}min")
    print(f"  Seuil: {MIN_CORRELATION_THRESHOLD} adresses")
    print(f"  Debug: {'ACTIVÉ' if DEBUG_MODE else 'DÉSACTIVÉ'}")
    print("")
    
    if DEBUG_MODE:
        print("MODE DEBUG:")
    if DEBUG_MODE:
        print("MODE DEBUG:")
        print("  - Compteur de requêtes API détaillé")
        print("  - Parsing manuel des instructions + inner instructions")
        print("  - Adresses complètes des tokens affichées")
        print("  - Balance changes + transfers détectés")
        print("  - Montants en tokens ET en USD")
        print(f"\nADRESSES SURVEILLÉES ({len(WHALE_ADDRESSES)}):")
        for i, addr in enumerate(WHALE_ADDRESSES, 1):
            print(f"  {i:2d}. {addr}")
        print("")
    
    try:
        async with SolanaCorrelationMonitor() as monitor:
            await monitor.monitor_loop()
    except KeyboardInterrupt:
        print(f"\nProgramme arrêté")
        print(f"Total requêtes utilisées: {api_request_counter}")
        print(f"Coût estimé final: ${api_request_counter * 0.0001:.4f}")
    except Exception as e:
        logger.error(f"Erreur fatale: {e}")
        logger.info(f"Total requêtes avant erreur: {api_request_counter}")

if __name__ == "__main__":
    asyncio.run(main())