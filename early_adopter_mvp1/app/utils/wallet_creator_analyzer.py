import requests
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import os

class HeliusWalletAnalyzer:
    def __init__(self, api_key: str = None):
        self.api_key ='09fa25c2-61df-44b7-b435-bbd2dbbae0df'
        if not self.api_key:
            raise ValueError("HELIUS_API_KEY est requis. Obtenez-le sur https://helius.xyz")
        
        self.rpc_url = f"https://mainnet.helius-rpc.com/?api-key={self.api_key}"
        self.enhanced_url = f"https://api.helius.xyz/v0"
        
        # Compteurs de requêtes et crédits (AVANT get_sol_price)
        self.request_stats = {
            "coingecko_price": {"requests": 0, "credits": 0},
            "helius_transactions": {"requests": 0, "credits": 0},
            "helius_transfers": {"requests": 0, "credits": 0},
            "helius_rpc_transaction": {"requests": 0, "credits": 0}
        }
        
        # Coût approximatif en crédits par endpoint (basé sur la documentation Helius)
        self.credit_costs = {
            "coingecko_price": 0,  # API externe gratuite
            "helius_transactions": 10,  # Enhanced API - transactions parsées
            "helius_transfers": 5,   # Enhanced API - transferts
            "helius_rpc_transaction": 1  # RPC standard
        }
        
        # Initialiser le prix SOL après les compteurs
        self.sol_price_usd = self.get_sol_price()
    
    def _log_request(self, endpoint: str, response_size: int = 0):
        """Enregistre une requête et calcule les crédits utilisés"""
        self.request_stats[endpoint]["requests"] += 1
        
        # Calcul des crédits basé sur le type d'endpoint (ajusté selon observations réelles)
        if endpoint == "helius_transactions":
            # COÛT RÉEL OBSERVÉ : ~100 crédits pour l'endpoint Enhanced transactions
            # Cela semble être un coût fixe élevé indépendamment du nombre de transactions
            credits = 100  # Coût réel observé
            print(f"[DEBUG] Helius Enhanced transactions: {response_size} transactions -> {credits} crédits (coût réel observé)")
        elif endpoint == "helius_rpc_transaction":
            credits = 1  # Coût fixe par transaction RPC (confirmé)
        elif endpoint == "helius_transfers":
            credits = 5  # Coût standard Enhanced API
        else:
            credits = self.credit_costs.get(endpoint, 1)
        
        self.request_stats[endpoint]["credits"] += credits
    
    def get_request_summary(self) -> Dict:
        """Retourne un résumé des requêtes et crédits utilisés"""
        total_requests = sum(stats["requests"] for stats in self.request_stats.values())
        total_credits = sum(stats["credits"] for stats in self.request_stats.values())
        
        return {
            "total_requests": total_requests,
            "total_credits": total_credits,
            "breakdown": {
                "CoinGecko (prix SOL)": {
                    "requests": self.request_stats["coingecko_price"]["requests"],
                    "credits": self.request_stats["coingecko_price"]["credits"]
                },
                "Helius Enhanced (transactions)": {
                    "requests": self.request_stats["helius_transactions"]["requests"], 
                    "credits": self.request_stats["helius_transactions"]["credits"]
                },
                "Helius Enhanced (transferts)": {
                    "requests": self.request_stats["helius_transfers"]["requests"],
                    "credits": self.request_stats["helius_transfers"]["credits"]
                },
                "Helius RPC (détails transaction)": {
                    "requests": self.request_stats["helius_rpc_transaction"]["requests"],
                    "credits": self.request_stats["helius_rpc_transaction"]["credits"]
                }
            }
        }
    
    def get_sol_price(self) -> float:
        """Récupère le prix actuel de SOL en USD"""
        try:
            response = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd")
            self._log_request("coingecko_price")
            
            if response.status_code == 200:
                data = response.json()
                return data.get("solana", {}).get("usd", 200)  # Prix par défaut si API échoue
        except:
            self._log_request("coingecko_price")  # Compter même en cas d'erreur
        return 200  # Prix approximatif par défaut
    
    def get_parsed_transactions(self, wallet_address: str, limit: int = 1000) -> List[Dict]:
        """Récupère les transactions parsées via l'API Helius Enhanced"""
        url = f"{self.enhanced_url}/addresses/{wallet_address}/transactions"
        
        params = {
            "api-key": self.api_key
            # Note: limit n'est pas supporté par cet endpoint
        }
        
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            transactions = response.json()
            self._log_request("helius_transactions", len(transactions))
            # Limiter manuellement si nécessaire
            return transactions[:limit] if len(transactions) > limit else transactions
        else:
            self._log_request("helius_transactions", 0)
            print(f"Erreur API Helius: {response.status_code} - {response.text}")
            return []
    
    def get_token_transfers(self, wallet_address: str, limit: int = 1000) -> List[Dict]:
        """Récupère les transferts de tokens via Helius"""
        url = f"{self.enhanced_url}/addresses/{wallet_address}/transfers"
        
        params = {
            "api-key": self.api_key,
            "limit": limit,
            "type": "TRANSFER"
        }
        
        response = requests.get(url, params=params)
        
        if response.status_code == 200:
            transfers = response.json()
            self._log_request("helius_transfers", len(transfers))
            return transfers
        else:
            self._log_request("helius_transfers", 0)
            return []
    
    def analyze_wallet_creation(self, transactions: List[Dict]) -> Optional[datetime]:
        """Trouve la date de création du wallet"""
        if not transactions:
            return None
        
        # Helius retourne déjà les transactions triées par date (plus récente en premier)
        oldest_tx = transactions[-1]
        timestamp = oldest_tx.get("timestamp")
        
        if timestamp:
            return datetime.fromtimestamp(timestamp)
        return None
    
    def analyze_funding(self, wallet_address: str, transactions: List[Dict]) -> List[Dict]:
        """Analyse les financements reçus par le wallet"""
        funding_transactions = []
        
        for tx in transactions:
            # Analyse des transferts SOL natifs
            native_transfers = tx.get("nativeTransfers", [])
            
            for transfer in native_transfers:
                # Si le wallet est le destinataire
                if transfer.get("toUserAccount") == wallet_address:
                    amount_sol = transfer.get("amount", 0) / 1e9
                    
                    # Filtre les montants significatifs (> 0.001 SOL)
                    if amount_sol > 0.001:
                        from_address = transfer.get("fromUserAccount", "Unknown")
                        
                        # Identifie si c'est depuis un exchange connu
                        funding_source = self.identify_funding_source(from_address)
                        
                        # Vérifier si c'est la première transaction du wallet
                        is_first_transaction = (tx == transactions[-1])  # Dernière transaction = première chronologiquement
                        
                        funding_transactions.append({
                            "signature": tx.get("signature"),
                            "timestamp": datetime.fromtimestamp(tx.get("timestamp", 0)),
                            "amount_sol": amount_sol,
                            "amount_usd": amount_sol * self.sol_price_usd,
                            "from_address": from_address,
                            "funding_source": funding_source,
                            "description": tx.get("description", ""),
                            "is_first_transaction": is_first_transaction
                        })
        
        return funding_transactions
    
    def identify_funding_source(self, address: str) -> str:
        """Identifie la source de financement (exchange, etc.)"""
        known_sources = {
            # Exchanges principaux
            "Binance": ["5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9"],
            "Coinbase": ["GVXRSBjFk6e6J3NbVPXohDJetcTjaeeuykUpbQF8UoMU"],
            "Kraken": ["DvBhKjDHZ8H3Ae7qbEMPKSW5FV4jYdkhkZQjKZZHGuPL"],
            "OKX": ["5VCwKtCXgCJ6kit5FybXjvriW3xELsFDhYrPSqtJNmcD"],
            "KuCoin": ["DdBuEvT7PNNm2gtpnDJGdSzm9Z29dWk9LPXWqZp2fZJA"]
        }
        
        for exchange_name, addresses in known_sources.items():
            if address in addresses:
                return exchange_name
        
        # Si ce n'est pas un exchange connu
        return "Wallet privé"
    
    def get_transaction_details_rpc(self, signature: str) -> Dict:
        """Récupère les détails d'une transaction via RPC pour plus d'informations"""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [
                signature,
                {
                    "encoding": "json",
                    "maxSupportedTransactionVersion": 0
                }
            ]
        }
        
        response = requests.post(self.rpc_url, json=payload)
        self._log_request("helius_rpc_transaction")
        
        return response.json()
    
    def check_token_creation_enhanced(self, wallet_address: str, token_address: str, transactions: List[Dict], token_symbol: str = None) -> Dict:
        """Vérification améliorée de création de token avec RPC fallback"""
        token_creation_evidence = {
            "token_account_created": False,
            "bonding_curve_created": False,
            "vault_created": False,
            "pump_fun_detected": False,
            "token_symbol": None,
            "token_address": token_address,
            "creation_transactions": [],
            "create_account_count": 0,
            "create_account_details": [],
            "token_creation_signature": None  # Nouveau: signature spécifique de création vers le token
        }
        
        for tx in transactions:
            signature = tx.get("signature")
            timestamp = datetime.fromtimestamp(tx.get("timestamp", 0))
            description = tx.get("description", "").lower()
            
            # 1. Analyse des account changes (nouvelles créations)
            account_data = tx.get("accountData", [])
            for account in account_data:
                if (account.get("account") == token_address and 
                    account.get("nativeBalanceChange") == 0):  # Nouveau compte créé
                    token_creation_evidence["create_account_count"] += 1
                    token_creation_evidence["token_account_created"] = True
                    token_creation_evidence["token_creation_signature"] = signature
                    
                    detail = {
                        "method": "accountData",
                        "from": "Unknown",
                        "to": account.get("account", "Unknown")[:20] + "...",
                        "signature": signature[:20] + "..."
                    }
                    token_creation_evidence["create_account_details"].append(detail)
            
            # 2. Analyse RPC pour plus de détails
            if not description or description == "-":
                rpc_tx = self.get_transaction_details_rpc(signature)
                
                if "result" in rpc_tx and rpc_tx["result"]:
                    logs = rpc_tx["result"].get("meta", {}).get("logMessages", [])
                    account_keys = rpc_tx["result"].get("transaction", {}).get("message", {}).get("accountKeys", [])
                    instructions = rpc_tx["result"].get("transaction", {}).get("message", {}).get("instructions", [])
                    
                    # Analyse des instructions pour détecter CREATE_ACCOUNT
                    for instruction in instructions:
                        program_id_index = instruction.get("programIdIndex")
                        if program_id_index is not None and program_id_index < len(account_keys):
                            program_id = account_keys[program_id_index]
                            
                            # System Program = CREATE_ACCOUNT
                            if program_id == "11111111111111111111111111111112":
                                accounts = instruction.get("accounts", [])
                                if len(accounts) >= 2:
                                    from_account = account_keys[accounts[0]] if accounts[0] < len(account_keys) else "Unknown"
                                    to_account = account_keys[accounts[1]] if accounts[1] < len(account_keys) else "Unknown"
                                    
                                    if from_account == wallet_address:
                                        token_creation_evidence["create_account_count"] += 1
                                        token_creation_evidence["token_account_created"] = True
                                        
                                        # Si c'est vers l'adresse du token, enregistrer la signature
                                        if to_account == token_address:
                                            token_creation_evidence["token_creation_signature"] = signature
                                        
                                    detail = {
                                        "method": "SystemProgram",
                                        "from": from_account[:20] + "...",
                                        "to": to_account[:20] + "...",
                                        "signature": signature[:20] + "...",
                                        "is_token_address": (to_account == token_address)
                                    }
                                    token_creation_evidence["create_account_details"].append(detail)
                            
                            # Token Program = CREATE_ACCOUNT pour tokens
                            elif program_id in ["TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", 
                                               "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"]:
                                accounts = instruction.get("accounts", [])
                                if len(accounts) >= 1:
                                    to_account = account_keys[accounts[0]] if accounts[0] < len(account_keys) else "Unknown"
                                    
                                    token_creation_evidence["create_account_count"] += 1
                                    token_creation_evidence["token_account_created"] = True
                                    
                                    # Si c'est vers l'adresse du token, enregistrer la signature
                                    if to_account == token_address:
                                        token_creation_evidence["token_creation_signature"] = signature
                                    
                                    detail = {
                                        "method": "TokenProgram",
                                        "from": wallet_address[:20] + "...",
                                        "to": to_account[:20] + "...",
                                        "signature": signature[:20] + "...",
                                        "is_token_address": (to_account == token_address)
                                    }
                                    token_creation_evidence["create_account_details"].append(detail)
                    
                    # Recherche de l'adresse du token dans les comptes
                    if token_address and token_address in account_keys:
                        token_creation_evidence["token_account_created"] = True
                        token_creation_evidence["token_creation_signature"] = signature
                    
                    # Recherche Pump.fun dans les comptes
                    pump_accounts = [acc for acc in account_keys if "pump" in acc.lower()]
                    if pump_accounts:
                        token_creation_evidence["pump_fun_detected"] = True
            
            # 3. Analyse standard de la description Helius
            elif description and description != "-":
                if "create_account" in description or "createaccount" in description:
                    token_creation_evidence["create_account_count"] += 1
                    token_creation_evidence["token_account_created"] = True
                    
                    detail = {
                        "method": "HeliusDescription",
                        "from": "Unknown",
                        "to": "Unknown",
                        "signature": signature[:20] + "...",
                        "description": description
                    }
                    token_creation_evidence["create_account_details"].append(detail)
                
                if "pump.fun" in description or "pumpfun" in description:
                    token_creation_evidence["pump_fun_detected"] = True
            
            # 4. Analyse des transferts de tokens
            token_transfers = tx.get("tokenTransfers", [])
            for transfer in token_transfers:
                mint = transfer.get("mint", "")
                if token_address and mint == token_address:
                    token_creation_evidence["token_account_created"] = True
                    if not token_creation_evidence["token_creation_signature"]:
                        token_creation_evidence["token_creation_signature"] = signature
            
            # 5. Analyse des changements natifs (création de comptes SOL)
            native_transfers = tx.get("nativeTransfers", [])
            for transfer in native_transfers:
                from_acc = transfer.get("fromUserAccount", "")
                to_acc = transfer.get("toUserAccount", "")
                amount = transfer.get("amount", 0)
                
                # Petit montant depuis le wallet créateur = potentiel CREATE_ACCOUNT
                if (from_acc == wallet_address and amount < 10000000 and amount > 1000000):  # Entre 0.001 et 0.01 SOL
                    token_creation_evidence["create_account_count"] += 1
                    token_creation_evidence["token_account_created"] = True
                    
                    # Si c'est vers l'adresse du token, enregistrer la signature
                    if to_acc == token_address:
                        token_creation_evidence["token_creation_signature"] = signature
                    
                    detail = {
                        "method": "NativeTransfer",
                        "from": from_acc[:20] + "...",
                        "to": to_acc[:20] + "...",
                        "amount": f"{amount/1e9:.6f} SOL",
                        "signature": signature[:20] + "...",
                        "is_token_address": (to_acc == token_address)
                    }
                    token_creation_evidence["create_account_details"].append(detail)
            
            # Enregistrement de la transaction si pertinente
            if (token_creation_evidence["create_account_count"] > 0 or 
                token_creation_evidence["pump_fun_detected"]):
                
                token_creation_evidence["creation_transactions"].append({
                    "signature": signature,
                    "timestamp": timestamp,
                    "description": description if description != "-" else "Analysé via RPC",
                    "type": "creation_activity"
                })
        
        # Heuristique finale
        if (token_creation_evidence["create_account_count"] >= 1 and 
            token_creation_evidence["pump_fun_detected"]):
            
            token_creation_evidence["bonding_curve_created"] = True
            token_creation_evidence["vault_created"] = True
        
        elif token_creation_evidence["create_account_count"] >= 3:
            token_creation_evidence["bonding_curve_created"] = True
            token_creation_evidence["vault_created"] = True
        
        return token_creation_evidence
    
    def find_profit_transfers(self, wallet_address: str, transactions: List[Dict], target_addresses: List[str] = None) -> List[Dict]:
        """Trouve les transferts de profits vers des collecteurs centraux"""
        profit_transfers = []
        
        # Adresses suspectes connues (collecteurs centraux)
        suspicious_addresses = target_addresses or [
            "AVeA6F18KEZ27wknfKmJ",  # Exemple du collecteur identifié
        ]
        
        for tx in transactions:
            native_transfers = tx.get("nativeTransfers", [])
            
            for transfer in native_transfers:
                # Si le wallet envoie vers une adresse suspecte
                if (transfer.get("fromUserAccount") == wallet_address and 
                    transfer.get("toUserAccount") in suspicious_addresses):
                    
                    amount_sol = transfer.get("amount", 0) / 1e9
                    
                    profit_transfers.append({
                        "signature": tx.get("signature"),
                        "timestamp": datetime.fromtimestamp(tx.get("timestamp", 0)),
                        "amount_sol": amount_sol,
                        "to_address": transfer.get("toUserAccount"),
                        "description": tx.get("description", "")
                    })
        
        return profit_transfers
    
    def analyze_creator_wallet(self, wallet_address: str, token_address: str, token_symbol: str = None, target_addresses: List[str] = None) -> Dict:
        """Analyse complète d'un wallet créateur avec Helius"""
        
        # Récupération des transactions via Helius
        transactions = self.get_parsed_transactions(wallet_address)
        
        if not transactions:
            return {"error": "Aucune transaction trouvée pour ce wallet"}
        
        # Analyse de la création du wallet
        creation_date = self.analyze_wallet_creation(transactions)
        
        # Analyse du financement
        funding_info = self.analyze_funding(wallet_address, transactions)
        
        # Vérification de création de token
        token_creation = self.check_token_creation_enhanced(wallet_address, token_address, transactions, token_symbol)
        
        # Recherche de transferts vers collecteurs
        profit_transfers = self.find_profit_transfers(wallet_address, transactions, target_addresses)
        
        # Compilation des résultats avec stats des requêtes
        result = {
            "wallet_address": wallet_address,
            "creation_date": creation_date.isoformat() if creation_date else "Non déterminée",
            "total_transactions": len(transactions),
            "funding_info": {
                "total_fundings": len(funding_info),
                "total_amount_sol": sum([f["amount_sol"] for f in funding_info]),
                "funding_details": funding_info
            },
            "token_creation": token_creation,
            "profit_transfers": {
                "total_transfers": len(profit_transfers),
                "total_amount_sol": sum([t["amount_sol"] for t in profit_transfers]),
                "transfer_details": profit_transfers
            },
            "risk_assessment": self.assess_risk(funding_info, token_creation, profit_transfers),
            "is_likely_creator": (
                token_creation["pump_fun_detected"] and 
                token_creation["token_account_created"]
            ),
            "is_likely_scammer": (
                len(profit_transfers) > 0 and
                token_creation["pump_fun_detected"] and
                sum([t["amount_sol"] for t in profit_transfers]) > 10  # Plus de 10 SOL transférés
            ),
            "api_usage": self.get_request_summary()  # Nouveau: statistiques des requêtes
        }
        
        return result
    
    def assess_risk(self, funding_info: List[Dict], token_creation: Dict, profit_transfers: List[Dict]) -> str:
        """Évalue le niveau de risque du wallet"""
        risk_factors = []
        
        # Facteurs de risque
        if token_creation["pump_fun_detected"]:
            risk_factors.append("Utilise Pump.fun")
        
        if len(profit_transfers) > 0:
            risk_factors.append("Transfère vers collecteur central")
        
        total_profit_transferred = sum([t["amount_sol"] for t in profit_transfers])
        if total_profit_transferred > 50:
            risk_factors.append("Gros montants transférés")
        
        exchange_funding = any("Exchange" in f.get("funding_source", "") for f in funding_info)
        if not exchange_funding and len(funding_info) > 0:
            risk_factors.append("Financement depuis wallet privé")
        
        # Évaluation du risque
        if len(risk_factors) >= 3:
            return f"TRÈS ÉLEVÉ - {', '.join(risk_factors)}"
        elif len(risk_factors) >= 2:
            return f"ÉLEVÉ - {', '.join(risk_factors)}"
        elif len(risk_factors) >= 1:
            return f"MODÉRÉ - {', '.join(risk_factors)}"
        else:
            return "FAIBLE"

# Fonction d'utilisation simple
def analyze_wallet_helius(wallet_address: str, token_address: str, token_symbol: str = None, api_key: str = None, target_addresses: List[str] = None) -> Dict:
    """
    Analyse un wallet créateur avec Helius
    
    Args:
        wallet_address: L'adresse du wallet à analyser
        token_address: L'adresse du token créé
        token_symbol: Le symbole du token (optionnel)
        api_key: Clé API Helius (ou via variable d'environnement HELIUS_API_KEY)
        target_addresses: Liste d'adresses collectrices à surveiller
    
    Returns:
        Dictionnaire avec toutes les informations d'analyse
    """
    analyzer = HeliusWalletAnalyzer(api_key)
    return analyzer.analyze_creator_wallet(wallet_address, token_address, token_symbol, target_addresses)

# Exemple d'utilisation
if __name__ == "__main__":
    # Vous devez obtenir une clé API gratuite sur https://helius.xyz
    # Soit la passer directement, soit la définir comme variable d'environnement
    
    # Exemple avec le wallet BUILD
    wallet_build = "dpHgHMoSk4i4mJrW36Bx22hS88mHCvq1SR33J5CC4Dh"
    token_address_build = "5vk4QrN69RP2Hb3JTwY4jmHRRcWj1jv213U9Dngopump"
    collecteur_central = ["AVeA6F18KEZ27wknfKmJ"]
    
    print("=== ANALYSE DU WALLET BUILD AVEC HELIUS ===")

    # Créer l'analyseur pour accéder au prix SOL
    analyzer = HeliusWalletAnalyzer()

    result = analyze_wallet_helius(
        wallet_build, 
        token_address_build,
        "BUILD",
        target_addresses=collecteur_central
    )

    # Vérification d'erreur avant d'afficher les résultats
    if "error" in result:
        print(f"ERREUR: {result['error']}")
        exit(1)

    # NOUVEAU RÉSUMÉ CONCIS - Les 3 points clés
    print(f"\n" + "="*80)
    print("🔍 RÉSUMÉ D'ANALYSE - POINTS CLÉS")
    print("="*80)

    # 1. Transaction create account vers l'adresse du token
    token_creation_sig = result['token_creation'].get('token_creation_signature')
    if token_creation_sig:
        print(f"✅ Transaction CREATE_ACCOUNT du wallet analysé vers l'adresse du token trouvée :")
        print(f"   Signature: {token_creation_sig}")
    else:
        print(f"❌ Aucune transaction CREATE_ACCOUNT directe vers l'adresse du token trouvée")
        if result['token_creation']['create_account_count'] > 0:
            print(f"   Mais {result['token_creation']['create_account_count']} CREATE_ACCOUNT détectés au total")

    # 2. Date de création du portefeuille (moins de 24h)
    creation_date = result.get('creation_date')
    if creation_date != "Non déterminée":
        creation_datetime = datetime.fromisoformat(creation_date.replace('Z', '+00:00'))
        now = datetime.now(creation_datetime.tzinfo) if creation_datetime.tzinfo else datetime.now()
        time_diff = now - creation_datetime
        
        if time_diff.total_seconds() < 86400:  # 24 heures en secondes
            print(f"⚠️  Portefeuille créé il y a moins de 24h :")
            print(f"   Date de création: {creation_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"   Âge: {time_diff.total_seconds()/3600:.1f} heures")
        else:
            print(f"✅ Portefeuille créé il y a plus de 24h :")
            print(f"   Date de création: {creation_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"   Âge: {time_diff.days} jours")
    else:
        print(f"❓ Date de création du portefeuille : Non déterminée")

    # 3. Première transaction de financement
    if result['funding_info']['funding_details']:
        first_funding = None
        for funding in result['funding_info']['funding_details']:
            if funding['is_first_transaction']:
                first_funding = funding
                break
        
        if first_funding:
            print(f"💰 Première transaction correspondant au financement :")
            print(f"   Depuis: {first_funding['funding_source']}")
            print(f"   Adresse: {first_funding['from_address']}")
            print(f"   Montant: {first_funding['amount_sol']:.6f} SOL (${first_funding['amount_usd']:.2f})")
            print(f"   Signature: {first_funding['signature']}")
        else:
            # Prendre le financement le plus ancien
            oldest_funding = min(result['funding_info']['funding_details'], 
                               key=lambda x: x['timestamp'])
            print(f"💰 Premier financement détecté (pas forcément la première transaction) :")
            print(f"   Depuis: {oldest_funding['funding_source']}")
            print(f"   Adresse: {oldest_funding['from_address']}")
            print(f"   Montant: {oldest_funding['amount_sol']:.6f} SOL (${oldest_funding['amount_usd']:.2f})")
            print(f"   Signature: {oldest_funding['signature']}")
    else:
        print(f"❌ Aucun financement significatif détecté")

    # Affichage des statistiques d'utilisation de l'API
    print(f"\n" + "="*60)
    print("STATISTIQUES D'UTILISATION DE L'API HELIUS")
    print("="*60)

    api_stats = result['api_usage']

    print(f"TOTAL: {api_stats['total_requests']} requêtes - {api_stats['total_credits']} crédits utilisés")
    print("\nDétail par endpoint:")

    for endpoint_name, stats in api_stats['breakdown'].items():
        if stats['requests'] > 0:
            print(f"• {endpoint_name}:")
            print(f"  - Requêtes: {stats['requests']}")
            print(f"  - Crédits: {stats['credits']}")
            
            # Calcul du coût estimé (basé sur les tarifs Helius)
            if "CoinGecko" in endpoint_name:
                cost_usd = 0  # API gratuite
            elif "Enhanced" in endpoint_name:
                cost_usd = stats['credits'] * 0.0001  # ~0.01¢ par crédit Enhanced
            elif "RPC" in endpoint_name:
                cost_usd = stats['credits'] * 0.00005  # ~0.005¢ par crédit RPC
            else:
                cost_usd = stats['credits'] * 0.0001
            
            print(f"  - Coût estimé: ${cost_usd:.4f}")
        else:
            print(f"• {endpoint_name}: Non utilisé")

    # Estimation du coût total
    total_cost_usd = (
        api_stats['breakdown']['Helius Enhanced (transactions)']['credits'] * 0.0001 +
        api_stats['breakdown']['Helius Enhanced (transferts)']['credits'] * 0.0001 +
        api_stats['breakdown']['Helius RPC (détails transaction)']['credits'] * 0.00005
    )

    print(f"\nCoût total estimé: ${total_cost_usd:.4f}")

    # Conseils d'optimisation
    print(f"\n" + "-"*40)
    print("CONSEILS D'OPTIMISATION:")

    rpc_requests = api_stats['breakdown']['Helius RPC (détails transaction)']['requests']
    enhanced_requests = api_stats['breakdown']['Helius Enhanced (transactions)']['requests']

    if enhanced_requests > 0:
        print("• ⚠️  COÛT ÉLEVÉ: L'endpoint Enhanced transactions coûte ~100 crédits par requête!")
        print("• 💡 OPTIMISATION: Limitez les analyses de wallets pour économiser les crédits")

    if rpc_requests > 5:
        print(f"• ⚠️  {rpc_requests} requêtes RPC détectées. Chaque RPC = 1 crédit")
        print("• 💡 Essayez d'analyser moins de transactions sans description")

    if api_stats['total_credits'] > 100:
        print("• ⚠️  Usage intensif détecté (>100 crédits par analyse)")
        print("• 💡 Considérez implémenter un cache pour éviter les requêtes répétées")

    if enhanced_requests == 1 and rpc_requests < 5:
        print("• ✅ Usage optimal: 1 Enhanced + peu de RPC")

    remaining_credits = 100000 - api_stats['total_credits']
    analyses_remaining = remaining_credits // 102  # Basé sur votre observation réelle

    print(f"• 📊 Plan gratuit Helius: 100,000 crédits/mois")
    print(f"• 📈 Avec ce coût (~102 crédits/analyse), vous pouvez faire ~{analyses_remaining:,} analyses ce mois")