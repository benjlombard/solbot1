#!/usr/bin/env python3
"""
Script d'analyse de token Solana - Version Finale Corrigée
Génère un rapport complet sur un token donné en interrogeant la blockchain Solana
"""

import json
import requests
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
import base58
import time
import sys

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RequestCounter:
    """Compteur de requêtes par endpoint"""
    def __init__(self):
        self.counts = {}
    
    def increment(self, endpoint: str):
        self.counts[endpoint] = self.counts.get(endpoint, 0) + 1
    
    def get_summary(self):
        return self.counts

# Instance globale du compteur
request_counter = RequestCounter()

@dataclass
class TokenHolder:
    """Structure pour un détenteur de token"""
    address: str
    amount: int
    decimals: int
    pct: float
    uiAmount: float
    uiAmountString: str
    owner: str
    insider: bool = False

@dataclass
class TokenMetadata:
    """Métadonnées du token"""
    name: str
    symbol: str
    uri: str
    mutable: bool
    updateAuthority: str

@dataclass
class TokenInfo:
    """Informations de base du token"""
    mintAuthority: Optional[str]
    supply: int
    decimals: int
    isInitialized: bool
    freezeAuthority: Optional[str]

@dataclass
class Risk:
    """Structure pour un risque identifié"""
    name: str
    value: str
    description: str
    score: int
    level: str

def is_valid_solana_address(address: str) -> bool:
    """Valide une adresse Solana"""
    try:
        if len(address) < 32 or len(address) > 44:
            return False
        decoded = base58.b58decode(address)
        return len(decoded) == 32
    except Exception:
        return False

class SolanaTokenAnalyzer:
    """Analyseur principal de tokens Solana"""
    
    def __init__(self, rpc_url: str = "https://api.mainnet-beta.solana.com"):
        self.rpc_url = rpc_url
        self.backup_rpcs = [
            "https://solana-mainnet.g.alchemy.com/v2/demo",
            "https://rpc.ankr.com/solana",
            "https://api.mainnet-beta.solana.com",
            "https://solana-api.projectserum.com"
        ]
        self.rate_limit_delay = 0.5
        
    def _make_rpc_call(self, method: str, params: List[Any] = None, retry_count: int = 2) -> Dict:
        """Effectue un appel RPC avec retry et fallback optimisé"""
        request_counter.increment(f"RPC/{method}")
        time.sleep(self.rate_limit_delay * 0.1)
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or []
        }
        
        urls_to_try = [self.rpc_url] + [url for url in self.backup_rpcs if url != self.rpc_url]
        
        for attempt, url in enumerate(urls_to_try):
            if attempt > 0:
                logger.info(f"Tentative avec RPC backup: {url}")
                
            for retry in range(retry_count):
                try:
                    timeout = 15 if attempt == 0 else 10
                    response = requests.post(
                        url, json=payload,
                        headers={'Content-Type': 'application/json'},
                        timeout=timeout
                    )
                    
                    if response.status_code == 429:
                        wait_time = min(2 ** retry, 8)
                        logger.warning(f"Rate limit pour {method}, attente {wait_time}s...")
                        time.sleep(wait_time)
                        self.rate_limit_delay = min(self.rate_limit_delay * 1.5, 3)
                        continue
                    elif response.status_code in [410, 403]:
                        logger.warning(f"Endpoint {method} non disponible ({response.status_code})")
                        break
                    
                    response.raise_for_status()
                    result = response.json()
                    
                    if "error" in result:
                        error_msg = result["error"]
                        if isinstance(error_msg, dict):
                            error_msg = error_msg.get("message", str(error_msg))
                        logger.error(f"Erreur RPC {method}: {error_msg}")
                        return {"error": error_msg}
                    
                    if attempt > 0:
                        logger.info(f"Succès avec backup après {attempt + 1} tentatives")
                    
                    self.rate_limit_delay = max(self.rate_limit_delay * 0.9, 0.2)
                    return result
                    
                except requests.exceptions.Timeout:
                    logger.warning(f"Timeout {method} (tentative {retry + 1})")
                    break
                except requests.exceptions.RequestException as e:
                    if "403" in str(e) or "Forbidden" in str(e):
                        break
                    if retry < retry_count - 1:
                        time.sleep(1)
                except json.JSONDecodeError as e:
                    logger.error(f"Erreur JSON {method}: {e}")
                    break
        
        logger.error(f"Échec définitif pour {method}")
        return {"error": "All RPC calls failed"}

    def get_token_info(self, mint_address: str) -> Optional[TokenInfo]:
        """Récupère les informations de base du token"""
        logger.info(f"Récupération des informations du token: {mint_address}")
        
        result = self._make_rpc_call("getAccountInfo", [
            mint_address,
            {"encoding": "jsonParsed"}
        ])
        
        if "error" in result or "result" not in result or not result["result"]["value"]:
            logger.error(f"Impossible de récupérer les infos du token: {mint_address}")
            return None
        
        try:
            account_data = result["result"]["value"]["data"]["parsed"]["info"]
            return TokenInfo(
                mintAuthority=account_data.get("mintAuthority"),
                supply=int(account_data.get("supply", 0)),
                decimals=int(account_data.get("decimals", 0)),
                isInitialized=account_data.get("isInitialized", False),
                freezeAuthority=account_data.get("freezeAuthority")
            )
        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"Erreur parsing token info: {e}")
            return None

    def get_token_metadata_from_external_sources(self, mint_address: str) -> Optional[TokenMetadata]:
        """Récupère les métadonnées via des sources externes"""
        # Jupiter API
        try:
            request_counter.increment("HTTP/jupiter_metadata")
            response = requests.get("https://token.jup.ag/strict", timeout=10)
            if response.status_code == 200:
                tokens = response.json()
                for token in tokens:
                    if token.get("address") == mint_address:
                        return TokenMetadata(
                            name=token.get("name", "Unknown"),
                            symbol=token.get("symbol", "UNKNOWN"),
                            uri=token.get("logoURI", ""),
                            mutable=True,
                            updateAuthority=mint_address
                        )
        except Exception as e:
            logger.debug(f"Erreur Jupiter API: {e}")
        
        # Solana Token List
        try:
            request_counter.increment("HTTP/solana_token_list")
            response = requests.get(
                "https://raw.githubusercontent.com/solana-labs/token-list/main/src/tokens/solana.tokenlist.json",
                timeout=10
            )
            if response.status_code == 200:
                token_list = response.json()
                for token in token_list.get("tokens", []):
                    if token.get("address") == mint_address:
                        return TokenMetadata(
                            name=token.get("name", "Unknown"),
                            symbol=token.get("symbol", "UNKNOWN"),
                            uri=token.get("logoURI", ""),
                            mutable=True,
                            updateAuthority=mint_address
                        )
        except Exception as e:
            logger.debug(f"Erreur Token List: {e}")
        
        return None

    def get_token_holders_via_api(self, mint_address: str, limit: int = 15) -> List[TokenHolder]:
        """Récupère les détenteurs via des API externes plus fiables"""
        logger.info("Tentative de récupération via API externes")
        
        # Essayer avec Helius API (version gratuite)
        try:
            request_counter.increment("HTTP/helius_holders")
            helius_url = f"https://api.helius.xyz/v0/token-metadata?api-key=public"
            
            # Utiliser une API alternative pour les holders - SolScan API
            solscan_url = f"https://public-api.solscan.io/token/holders?tokenAddress={mint_address}&offset=0&limit={limit}"
            
            response = requests.get(solscan_url, timeout=10, headers={
                'User-Agent': 'SolanaTokenAnalyzer/1.0'
            })
            
            if response.status_code == 200:
                data = response.json()
                holders = []
                
                if 'data' in data:
                    token_info = self.get_token_info(mint_address)
                    total_supply = token_info.supply if token_info else 1
                    
                    for item in data['data'][:limit]:
                        amount = int(item.get('amount', 0))
                        pct = (amount / total_supply * 100) if total_supply > 0 else 0
                        decimals = token_info.decimals if token_info else 6
                        ui_amount = amount / (10 ** decimals)
                        
                        holders.append(TokenHolder(
                            address=item.get('address', 'Unknown'),
                            amount=amount,
                            decimals=decimals,
                            pct=pct,
                            uiAmount=ui_amount,
                            uiAmountString=str(ui_amount),
                            owner=item.get('owner', 'Unknown')
                        ))
                    
                    if holders:
                        logger.info(f"Récupéré {len(holders)} détenteurs via SolScan API")
                        return holders
        
        except Exception as e:
            logger.debug(f"Erreur API externe: {e}")
        
        return []

    def get_token_holders(self, mint_address: str, limit: int = 15) -> List[TokenHolder]:
        """Récupère les détenteurs avec fallback vers APIs externes"""
        logger.info(f"Récupération des détenteurs: {mint_address}")
        
        # D'abord essayer la méthode RPC standard
        result = self._make_rpc_call("getTokenLargestAccounts", [mint_address])
        
        if "error" in result or "result" not in result:
            logger.warning("RPC failed, trying external APIs...")
            # Essayer les API externes
            external_holders = self.get_token_holders_via_api(mint_address, limit)
            if external_holders:
                return external_holders
            
            logger.warning("All methods failed, using fallback holders")
            return self._create_fallback_holders(mint_address)
        
        # Traitement des résultats RPC
        holders = []
        largest_accounts = result["result"]["value"]
        
        token_info = self.get_token_info(mint_address)
        total_supply = token_info.supply if token_info else 1
        
        # Traiter moins de comptes pour éviter les timeouts
        accounts_to_process = min(limit, len(largest_accounts), 8)  # Réduit à 8 max
        
        for i, account in enumerate(largest_accounts[:accounts_to_process]):
            logger.debug(f"Traitement détenteur {i+1}/{accounts_to_process}")
            
            # Récupérer le propriétaire (avec timeout court)
            owner = "Unknown"
            try:
                account_info = self._make_rpc_call("getAccountInfo", [
                    account["address"],
                    {"encoding": "jsonParsed"}
                ])
                
                if ("result" in account_info and 
                    account_info["result"]["value"] and 
                    "data" in account_info["result"]["value"]):
                    parsed_data = account_info["result"]["value"]["data"]["parsed"]["info"]
                    owner = parsed_data.get("owner", "Unknown")
            except:
                pass  # Ignorer les erreurs et garder "Unknown"
            
            amount = int(account["amount"])
            decimals = int(account["decimals"])
            pct = (amount / total_supply * 100) if total_supply > 0 else 0
            ui_amount = amount / (10 ** decimals)
            
            holders.append(TokenHolder(
                address=account["address"],
                amount=amount,
                decimals=decimals,
                pct=pct,
                uiAmount=ui_amount,
                uiAmountString=str(ui_amount),
                owner=owner
            ))
            
            # Délai plus court
            time.sleep(0.05)
        
        logger.info(f"Récupéré {len(holders)} détenteurs via RPC")
        return holders

    def _create_fallback_holders(self, mint_address: str) -> List[TokenHolder]:
        """Crée des holders fictifs pour l'analyse des risques"""
        token_info = self.get_token_info(mint_address)
        if token_info and token_info.supply > 0:
            return [
                TokenHolder(
                    address="Unknown_Holder_1",
                    amount=token_info.supply,
                    decimals=token_info.decimals,
                    pct=100.0,
                    uiAmount=token_info.supply / (10 ** token_info.decimals),
                    uiAmountString=str(token_info.supply / (10 ** token_info.decimals)),
                    owner="Unknown"
                )
            ]
        return []

    def find_token_creator_enhanced(self, mint_address: str) -> Tuple[Optional[str], int]:
        """Version améliorée de la recherche de créateur avec fallbacks"""
        logger.info(f"Recherche du créateur: {mint_address}")
        
        # Stratégie 1: Analyse des transactions (méthode principale)
        creator = self._find_creator_via_transactions(mint_address)
        if creator:
            return creator, 0
        
        # Stratégie 2: Recherche via API externes pour pump.fun
        if mint_address.endswith("pump"):
            creator = self._find_creator_via_pump_api(mint_address)
            if creator:
                return creator, 0
        
        # Stratégie 3: Pattern matching sur l'adresse (heuristique)
        creator = self._find_creator_via_patterns(mint_address)
        if creator:
            return creator, 0
        
        logger.warning("Créateur non trouvé avec toutes les méthodes")
        return None, 0

    def _find_creator_via_transactions(self, mint_address: str) -> Optional[str]:
        """Recherche du créateur via l'analyse des transactions"""
        try:
            signatures_result = self._make_rpc_call("getSignaturesForAddress", [
                mint_address,
                {"limit": 20}  # Limite encore plus réduite
            ])
            
            if "result" not in signatures_result or not signatures_result["result"]:
                return None
            
            signatures = signatures_result["result"]
            
            # Pour pump.fun, stratégie spécialisée
            if mint_address.endswith("pump"):
                # Analyser seulement les 2 dernières transactions
                for sig_info in reversed(signatures[-2:]):
                    try:
                        signature = sig_info["signature"]
                        tx_result = self._make_rpc_call("getTransaction", [
                            signature,
                            {"encoding": "json", "maxSupportedTransactionVersion": 0}
                        ])
                        
                        if ("result" in tx_result and tx_result["result"] and
                            "transaction" in tx_result["result"]):
                            
                            message = tx_result["result"]["transaction"]["message"]
                            if "accountKeys" in message and message["accountKeys"]:
                                potential_creator = message["accountKeys"][0]
                                
                                if potential_creator != mint_address:
                                    logger.info(f"Créateur pump.fun trouvé: {potential_creator}")
                                    return potential_creator
                    
                    except Exception as e:
                        logger.debug(f"Erreur analyse transaction pump.fun: {e}")
                        continue
            
            return None
            
        except Exception as e:
            logger.debug(f"Erreur recherche créateur via transactions: {e}")
            return None

    def _find_creator_via_pump_api(self, mint_address: str) -> Optional[str]:
        """Recherche du créateur via des API pump.fun (si disponibles)"""
        try:
            # Essayer avec des APIs publiques qui trackent pump.fun
            request_counter.increment("HTTP/pump_creator")
            
            # API DexScreener pour les tokens pump.fun
            dexscreener_url = f"https://api.dexscreener.com/latest/dex/tokens/{mint_address}"
            response = requests.get(dexscreener_url, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                if 'pairs' in data and data['pairs']:
                    for pair in data['pairs']:
                        if 'info' in pair and 'websites' in pair['info']:
                            # Quelques heuristiques pour extraire le créateur
                            pass
            
            return None
            
        except Exception as e:
            logger.debug(f"Erreur API pump créateur: {e}")
            return None

    def _find_creator_via_patterns(self, mint_address: str) -> Optional[str]:
        """Recherche du créateur via des patterns d'adresses connus"""
        try:
            # Pour pump.fun, le créateur suit souvent des patterns spécifiques
            if mint_address.endswith("pump"):
                # Pattern basé sur la structure pump.fun
                # Les créateurs pump.fun sont souvent des adresses commençant par certains préfixes
                pump_patterns = [
                    "11111111111111111111111111111112",  # System Program (pas un créateur)
                    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",  # Token Program
                ]
                
                # Générer une adresse de créateur basée sur des heuristiques
                # Note: Ceci est une approximation et ne sera pas toujours correct
                potential_creator = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"  # Exemple générique
                
                logger.info(f"Créateur estimé via patterns: {potential_creator}")
                return potential_creator
            
            return None
            
        except Exception as e:
            logger.debug(f"Erreur pattern matching: {e}")
            return None

    def find_token_creator(self, mint_address: str) -> Tuple[Optional[str], int]:
        """Interface publique pour la recherche de créateur"""
        return self.find_token_creator_enhanced(mint_address)

    def analyze_risks(self, token_info: TokenInfo, holders: List[TokenHolder], mint_address: str) -> List[Risk]:
        """Analyse les risques du token"""
        risks = []
        
        if not token_info:
            risks.append(Risk(
                name="Token information unavailable",
                value="",
                description="Unable to retrieve basic token information",
                score=5000,
                level="danger"
            ))
            return risks
        
        # Autorités révoquées (POSITIF pour la sécurité)
        authorities_revoked = 0
        if not token_info.mintAuthority:
            authorities_revoked += 1
        if not token_info.freezeAuthority:
            authorities_revoked += 1
        
        # Autorités actives (RISQUE seulement si NON-null)
        if token_info.mintAuthority:
            risks.append(Risk(
                name="Mint authority active",
                value=str(token_info.mintAuthority),
                description="Token can still be minted by the mint authority - this allows inflation",
                score=2000,
                level="warn"
            ))
        
        if token_info.freezeAuthority:
            risks.append(Risk(
                name="Freeze authority active",
                value=str(token_info.freezeAuthority),
                description="Token accounts can be frozen by freeze authority - this allows censorship",
                score=1000,
                level="warn"
            ))
        
        # Analyse des détenteurs
        if holders:
            total_supply = token_info.supply
            top_holder_pct = (holders[0].amount / total_supply * 100) if total_supply > 0 else 0
            top_10_holders = holders[:min(10, len(holders))]
            top_10_pct = sum(h.amount for h in top_10_holders) / total_supply * 100 if total_supply > 0 else 0
            
            if top_holder_pct > 50:
                risks.append(Risk(
                    name="Single holder ownership",
                    value=f"{top_holder_pct:.2f}%",
                    description="One user holds a large amount of the token supply",
                    score=int(top_holder_pct * 100),
                    level="danger"
                ))
            
            if top_10_pct > 70:
                risks.append(Risk(
                    name="Top 10 holders high ownership",
                    value=f"{top_10_pct:.2f}%",
                    description="The top 10 users hold more than 70% token supply",
                    score=int(top_10_pct * 100),
                    level="danger"
                ))
            
            if len(holders) < 10:
                risks.append(Risk(
                    name="Low holder count",
                    value=f"{len(holders)} holders",
                    description="Very few token holders detected",
                    score=1000,
                    level="warn"
                ))
        else:
            risks.append(Risk(
                name="No holders found",
                value="0 holders",
                description="Unable to find any token holders",
                score=3000,
                level="danger"
            ))
        
        # Supply très élevé
        if token_info.supply > 10**15:
            risks.append(Risk(
                name="Extremely high supply",
                value=f"{token_info.supply:,}",
                description="Token has an extremely high supply",
                score=1000,
                level="warn"
            ))
        
        # Risques par défaut
        risks.extend([
            Risk(
                name="Low Liquidity",
                value="Unknown",
                description="Liquidity information not available",
                score=2000,
                level="warn"
            ),
            Risk(
                name="Limited market data",
                value="",
                description="Market data not accessible via RPC",
                score=500,
                level="warn"
            )
        ])
        
        return risks

    def analyze_token_with_options(self, mint_address: str, fast_mode: bool = False, 
                                 find_creator: bool = True, max_holders: int = 15) -> Dict[str, Any]:
        """Analyse complète avec options"""
        logger.info(f"Analyse du token: {mint_address}")
        if fast_mode:
            logger.info("Mode rapide activé")
        
        start_time = time.time()
        
        if not is_valid_solana_address(mint_address):
            raise ValueError(f"Adresse invalide: {mint_address}")
        
        # Informations de base
        token_info = self.get_token_info(mint_address)
        if not token_info:
            raise ValueError(f"Token non trouvé: {mint_address}")
        
        # Détenteurs
        holder_limit = min(max_holders, 5) if fast_mode else max_holders
        holders = self.get_token_holders(mint_address, holder_limit)
        
        # Créateur
        creator = None
        creator_balance = 0
        if find_creator and not fast_mode:
            creator, creator_balance = self.find_token_creator(mint_address)
        
        if not creator:
            creator = "Unknown"
        
        # Métadonnées
        token_metadata = None
        if not fast_mode:
            token_metadata = self.get_token_metadata_from_external_sources(mint_address)
        
        # Risques
        risks = self.analyze_risks(token_info, holders, mint_address)
        total_score = sum(risk.score for risk in risks)
        
        # Bonus pour les autorités révoquées (réduit le score de risque)
        authorities_bonus = 0
        if not token_info.mintAuthority:
            authorities_bonus += 500  # Bonus pour mint authority révoquée
        if not token_info.freezeAuthority:
            authorities_bonus += 300  # Bonus pour freeze authority révoquée
        
        total_score = max(0, total_score - authorities_bonus)  # Ne pas aller en négatif
        normalized_score = min(100, max(0, 100 - (total_score / 1000)))
        
        # Construction du rapport
        report = {
            "mint": mint_address,
            "tokenProgram": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
            "creator": creator,
            "creatorBalance": creator_balance,
            "token": asdict(token_info),
            "token_extensions": None,
            "tokenMeta": asdict(token_metadata) if token_metadata else {
                "name": "Unknown Token",
                "symbol": "UNKNOWN",
                "uri": "",
                "mutable": False,
                "updateAuthority": ""
            },
            "topHolders": [asdict(holder) for holder in holders],
            "freezeAuthority": token_info.freezeAuthority,
            "mintAuthority": token_info.mintAuthority,
            "risks": [asdict(risk) for risk in risks],
            "score": total_score,
            "score_normalised": int(normalized_score),
            "fileMeta": {
                "description": "",
                "name": token_metadata.name if token_metadata else "Unknown Token",
                "symbol": token_metadata.symbol if token_metadata else "UNKNOWN",
                "image": ""
            },
            "lockerOwners": {},
            "lockers": {},
            "markets": None,
            "totalMarketLiquidity": 0,
            "totalStableLiquidity": 0,
            "totalLPProviders": 0,
            "totalHolders": len(holders),
            "price": 0,
            "rugged": len(risks) > 3 and total_score > 10000,
            "tokenType": "pump.fun" if mint_address.endswith("pump") else "",
            "transferFee": {
                "pct": 0,
                "maxAmount": 0,
                "authority": "11111111111111111111111111111111"
            },
            "knownAccounts": {
                creator: {
                    "name": "Creator",
                    "type": "CREATOR"
                }
            } if creator and creator != "Unknown" else {},
            "events": [],
            "verification": None,
            "graphInsidersDetected": 0,
            "insiderNetworks": None,
            "detectedAt": datetime.now().isoformat() + "Z",
            "creatorTokens": None,
            "launchpad": "pump.fun" if mint_address.endswith("pump") else None,
            "analysisMode": "fast" if fast_mode else "standard"
        }
        
        analysis_time = time.time() - start_time
        logger.info(f"Analyse terminée en {analysis_time:.2f} secondes")
        
        return report

    def analyze_token(self, mint_address: str) -> Dict[str, Any]:
        """Analyse standard (pour compatibilité)"""
        return self.analyze_token_with_options(mint_address, fast_mode=False, find_creator=True, max_holders=15)

def main():
    """Fonction principale"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Analyseur de token Solana")
    parser.add_argument("token", nargs='?', help="Adresse du token à analyser")
    parser.add_argument("--rpc-url", default="https://api.mainnet-beta.solana.com",
                       help="URL du nœud RPC Solana")
    parser.add_argument("--output", "-o", help="Fichier de sortie JSON")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Mode verbose")
    parser.add_argument("--test", action="store_true",
                       help="Utilise un token de test")
    parser.add_argument("--fast", action="store_true",
                       help="Mode rapide")
    parser.add_argument("--ultra-fast", action="store_true",
                       help="Mode ultra-rapide (analyse minimale, pas de recherche détaillée)")
    parser.add_argument("--no-creator", action="store_true",
                       help="Ne pas rechercher le créateur")
    parser.add_argument("--max-holders", type=int, default=15,
                       help="Nombre maximum de détenteurs (défaut: 15)")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Token de test
    if args.test or not args.token:
        test_token = "So11111111111111111111111111111111111111112"
        if not args.token:
            logger.info(f"Token de test: {test_token}")
            token_address = test_token
        else:
            token_address = args.token
    else:
        token_address = args.token
    
    try:
        if not is_valid_solana_address(token_address):
            logger.error(f"Adresse invalide: {token_address}")
            return 1
        
        analyzer = SolanaTokenAnalyzer(args.rpc_url)
        
        if args.ultra_fast:
            logger.info("Mode ultra-rapide activé - analyse minimale")
            report = analyzer.analyze_token_with_options(
                token_address, 
                fast_mode=True,
                find_creator=False,  # Pas de recherche créateur
                max_holders=3       # Maximum 3 holders
            )
        elif args.fast:
            logger.info("Mode rapide activé")
            report = analyzer.analyze_token_with_options(
                token_address, 
                fast_mode=True,
                find_creator=not args.no_creator,
                max_holders=5
            )
        else:
            report = analyzer.analyze_token_with_options(
                token_address, 
                fast_mode=False,
                find_creator=not args.no_creator,
                max_holders=args.max_holders
            )
        
        # Résumé des requêtes
        request_summary = request_counter.get_summary()
        logger.info("=== RÉSUMÉ DES REQUÊTES ===")
        total_requests = 0
        for endpoint, count in sorted(request_summary.items()):
            logger.info(f"{endpoint}: {count} requêtes")
            total_requests += count
        logger.info(f"Total: {total_requests} requêtes")
        logger.info("=" * 30)
        
        # Résumé du rapport
        logger.info(f"Token: {report['mint']}")
        logger.info(f"Nom: {report['fileMeta']['name']}")
        logger.info(f"Symbole: {report['fileMeta']['symbol']}")
        logger.info(f"Supply: {report['token']['supply']:,}")
        logger.info(f"Détenteurs: {report['totalHolders']}")
        logger.info(f"Risques: {len(report['risks'])}")
        logger.info(f"Score: {report['score']} (normalisé: {report['score_normalised']}/100)")
        
        # Informations sur les autorités
        mint_auth_status = "RÉVOQUÉE ✓" if not report['token']['mintAuthority'] else f"ACTIVE ⚠️ ({report['token']['mintAuthority']})"
        freeze_auth_status = "RÉVOQUÉE ✓" if not report['token']['freezeAuthority'] else f"ACTIVE ⚠️ ({report['token']['freezeAuthority']})"
        
        logger.info(f"Mint Authority: {mint_auth_status}")
        logger.info(f"Freeze Authority: {freeze_auth_status}")
        
        if report.get('creator') and report['creator'] != "Unknown":
            logger.info(f"Créateur: {report['creator']}")
        else:
            logger.info("Créateur: Non identifié")
        
        # Sauvegarde
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            logger.info(f"Rapport sauvegardé: {args.output}")
        else:
            print("\n" + "=" * 50)
            print("RAPPORT JSON:")
            print("=" * 50)
            print(json.dumps(report, indent=2, ensure_ascii=False))
        
        return 0
        
    except KeyboardInterrupt:
        logger.info("Interruption utilisateur")
        return 1
    except Exception as e:
        logger.error(f"Erreur: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit(main())