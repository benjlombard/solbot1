#!/usr/bin/env python3
"""
Détecteur de Patterns Pump & Dump pour tokens Solana/Pump.fun
Basé sur l'analyse du cas CABAL

Patterns détectés:
1. Création coordonnée de comptes multiples
2. Transferts identiques vers Metaplex (3.08$)
3. Structure hiérarchique de financement
4. Fermetures de comptes intermédiaires
5. Achats massifs initiaux
6. Distribution vers comptes multiples

Usage: python pump_detector.py <token_address>
"""

import asyncio
import aiohttp
import json
import sys
import argparse
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Dict, Set, Optional
from collections import defaultdict
import logging
from colorama import Fore, Back, Style, init

# Configuration des couleurs pour les logs
init(autoreset=True)

# Configuration du logging avec couleurs
class ColoredFormatter(logging.Formatter):
    """Formatter avec couleurs pour les logs"""
    
    COLORS = {
        'DEBUG': Fore.CYAN,
        'INFO': Fore.GREEN,
        'WARNING': Fore.YELLOW,
        'ERROR': Fore.RED,
        'CRITICAL': Fore.RED + Back.WHITE + Style.BRIGHT
    }

    def __init__(self):
        super().__init__(
            fmt='%(asctime)s | %(levelname)s | %(message)s',
            datefmt='%H:%M:%S'
        )

    def format(self, record):
        log_color = self.COLORS.get(record.levelname, '')
        record.levelname = f"{log_color}{record.levelname}{Style.RESET_ALL}"
        return super().format(record)

# Configuration du logger
def setup_logger():
    """Configuration sécurisée du logger avec couleurs"""
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    
    # Éviter les doublons de handlers
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(ColoredFormatter())
        logger.addHandler(handler)
    
    return logger

logger = setup_logger()

@dataclass
class Transaction:
    signature: str
    time: datetime
    action: str
    from_address: str
    to_address: str
    amount: float
    value_usd: float
    token: str

@dataclass
class SuspiciousPattern:
    pattern_type: str
    confidence: float
    description: str
    evidence: List[str]
    accounts_involved: Set[str]

class PumpDumpDetector:
    def __init__(self, rpc_endpoint: str = "https://api.mainnet-beta.solana.com"):
        self.rpc_endpoint = rpc_endpoint
        self.session = None
        
        # Constantes identifiées dans l'analyse CABAL
        self.METAPLEX_TRANSFER_AMOUNT = 0.0151156  # SOL (~3.08$)
        self.PUMP_FUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
        
        # Seuils de détection
        self.MIN_COORDINATED_ACCOUNTS = 3
        self.MAX_TIME_WINDOW_HOURS = 2
        self.MIN_CONFIDENCE_SCORE = 0.7

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def get_token_creator(self, token_address: str) -> Optional[str]:
        """Trouve l'adresse du créateur d'un token"""
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [token_address, {"limit": 10}]
            }
            
            async with self.session.post(self.rpc_endpoint, json=payload) as response:
                data = await response.json()
                
            if "result" not in data or not data["result"]:
                return None
                
            # Récupérer la première transaction (création du token)
            first_tx = data["result"][-1]  # La plus ancienne
            tx_details = await self.get_transaction_details(first_tx["signature"])
            
            if tx_details:
                return tx_details.from_address
                
            return None
            
        except Exception as e:
            logger.error(f"Erreur recherche créateur: {e}")
            return None

    async def get_account_transactions(self, account: str, limit: int = 100) -> List[Transaction]:
        """Récupère les transactions d'un compte via RPC Solana"""
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [
                    account,
                    {"limit": limit}
                ]
            }
            
            async with self.session.post(self.rpc_endpoint, json=payload) as response:
                data = await response.json()
                
            if "result" not in data or not data["result"]:
                logger.warning(f"Aucune signature trouvée pour {account[:10]}...")
                return []
                
            logger.debug(f"Trouvé {len(data['result'])} signatures pour {account[:10]}...")
            
            # Récupérer les détails de chaque transaction
            transactions = []
            for sig_info in data["result"][:20]:  # Limite pour éviter trop de requêtes
                transaction = await self.get_transaction_details(sig_info["signature"])
                if transaction:
                    transactions.append(transaction)
                    
            return transactions
            
        except Exception as e:
            logger.error(f"Erreur récupération transactions {account[:10]}...: {e}")
            return []

    async def get_transaction_details(self, signature: str) -> Optional[Transaction]:
        """Récupère les détails d'une transaction spécifique"""
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTransaction",
                "params": [
                    signature,
                    {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}
                ]
            }
            
            async with self.session.post(self.rpc_endpoint, json=payload) as response:
                data = await response.json()
                
            if "result" not in data or not data["result"]:
                return None
                
            # Parser la transaction
            tx_data = data["result"]
            return self.parse_transaction(signature, tx_data)
            
        except Exception as e:
            logger.error(f"Erreur détails transaction {signature}: {e}")
            return None

    def parse_transaction(self, signature: str, tx_data: dict) -> Optional[Transaction]:
        """Parse une transaction Solana en format Transaction"""
        try:
            if not tx_data or "meta" not in tx_data:
                return None
                
            instructions = tx_data.get("transaction", {}).get("message", {}).get("instructions", [])
            accounts = tx_data.get("transaction", {}).get("message", {}).get("accountKeys", [])
            
            # Déterminer le type d'action basé sur les instructions
            action = "UNKNOWN"
            from_addr = ""
            to_addr = ""
            amount = 0.0
            
            for instruction in instructions:
                if isinstance(instruction, dict):
                    program_id = instruction.get("programId", "")
                    
                    # Détection des patterns spécifiques
                    if "Create" in str(instruction):
                        action = "CREATE ACCOUNT"
                    elif "Close" in str(instruction):
                        action = "CLOSE ACCOUNT"
                    elif "Transfer" in str(instruction):
                        action = "TRANSFER"
                    
                    # Extraire les adresses et montants des comptes impliqués
                    if len(accounts) >= 2:
                        from_addr = accounts[0].get('pubkey', '') if isinstance(accounts[0], dict) else str(accounts[0])
                        to_addr = accounts[1].get('pubkey', '') if isinstance(accounts[1], dict) and len(accounts) > 1 else (str(accounts[1]) if len(accounts) > 1 else "")
            
            # Calculer le montant basé sur les changements de balance
            pre_balances = tx_data.get("meta", {}).get("preBalances", [])
            post_balances = tx_data.get("meta", {}).get("postBalances", [])
            
            if pre_balances and post_balances and len(pre_balances) == len(post_balances):
                # Calculer la différence de balance (en lamports)
                balance_changes = [post - pre for pre, post in zip(pre_balances, post_balances)]
                if balance_changes:
                    amount = abs(max(balance_changes, key=abs)) / 1_000_000_000  # Convertir en SOL
            
            return Transaction(
                signature=signature,
                time=datetime.fromtimestamp(tx_data.get("blockTime", 0)),
                action=action,
                from_address=from_addr,
                to_address=to_addr,
                amount=amount,
                value_usd=amount * 200,  # Approximation prix SOL
                token="SOL"
            )
            
        except Exception as e:
            logger.error(f"Erreur parsing transaction {signature}: {e}")
            return None

    def detect_metaplex_pattern(self, transactions: List[Transaction]) -> Optional[SuspiciousPattern]:
        """Détecte les transferts identiques vers Metaplex (Pattern CABAL)"""
        metaplex_transfers = []
        
        for tx in transactions:
            # Recherche des transferts de 3.08$ vers Metaplex
            if (abs(tx.amount - self.METAPLEX_TRANSFER_AMOUNT) < 0.001 and
                ("metaplex" in tx.to_address.lower() or 
                 "metadata" in tx.to_address.lower())):
                metaplex_transfers.append(tx)
        
        if len(metaplex_transfers) >= 3:  # Multiple instances du même token
            return SuspiciousPattern(
                pattern_type="MULTIPLE_TOKEN_INSTANCES",
                confidence=0.9,
                description=f"Création de {len(metaplex_transfers)} instances de token avec transferts identiques vers Metaplex",
                evidence=[f"Transfer {tx.signature}: {tx.amount} SOL vers Metaplex" for tx in metaplex_transfers],
                accounts_involved={tx.from_address for tx in metaplex_transfers}
            )
        return None

    def detect_hierarchical_funding(self, transactions: List[Transaction]) -> Optional[SuspiciousPattern]:
        """Détecte la structure hiérarchique de financement (3m -> DFd -> 2Nn pattern)"""
        # Grouper les transactions par comptes
        account_flows = defaultdict(list)
        
        for tx in transactions:
            account_flows[tx.from_address].append(tx)
            
        # Rechercher les patterns de financement en cascade
        funding_chains = []
        
        for account, txs in account_flows.items():
            # Rechercher les transferts vers d'autres comptes du réseau
            for tx in txs:
                if tx.to_address in account_flows:
                    funding_chains.append((account, tx.to_address, tx.amount))
        
        if len(funding_chains) >= 2:
            return SuspiciousPattern(
                pattern_type="HIERARCHICAL_FUNDING",
                confidence=0.8,
                description="Structure de financement hiérarchique détectée",
                evidence=[f"{chain[0][:10]}... -> {chain[1][:10]}...: {chain[2]} SOL" for chain in funding_chains],
                accounts_involved=set([chain[0] for chain in funding_chains] + [chain[1] for chain in funding_chains])
            )
        return None

    def detect_coordinated_account_creation(self, transactions: List[Transaction]) -> Optional[SuspiciousPattern]:
        """Détecte la création coordonnée de comptes multiples"""
        create_account_txs = [tx for tx in transactions if tx.action == "CREATE ACCOUNT"]
        
        if len(create_account_txs) < self.MIN_COORDINATED_ACCOUNTS:
            return None
            
        # Vérifier si les créations sont dans une fenêtre temporelle courte
        time_window = timedelta(hours=self.MAX_TIME_WINDOW_HOURS)
        recent_creates = []
        
        for tx in create_account_txs:
            if any(abs((tx.time - other.time).total_seconds()) < time_window.total_seconds() 
                   for other in create_account_txs if other != tx):
                recent_creates.append(tx)
        
        if len(recent_creates) >= self.MIN_COORDINATED_ACCOUNTS:
            return SuspiciousPattern(
                pattern_type="COORDINATED_ACCOUNT_CREATION",
                confidence=0.85,
                description=f"Création coordonnée de {len(recent_creates)} comptes en {self.MAX_TIME_WINDOW_HOURS}h",
                evidence=[f"CREATE ACCOUNT: {tx.signature} at {tx.time}" for tx in recent_creates],
                accounts_involved={tx.from_address for tx in recent_creates}
            )
        return None

    def detect_massive_initial_purchase(self, transactions: List[Transaction]) -> Optional[SuspiciousPattern]:
        """Détecte l'achat initial massif (Pattern 58M tokens)"""
        large_purchases = []
        
        for tx in transactions:
            # Rechercher les gros achats de tokens (>1M tokens ou >$500)
            if ((tx.token != "SOL" and tx.amount > 1000000) or 
                (tx.token == "SOL" and tx.value_usd > 500)):
                large_purchases.append(tx)
        
        if large_purchases:
            total_value = sum(tx.value_usd for tx in large_purchases)
            return SuspiciousPattern(
                pattern_type="MASSIVE_INITIAL_PURCHASE",
                confidence=0.9,
                description=f"Achat initial massif détecté: ${total_value:.2f}",
                evidence=[f"Purchase: {tx.amount} {tx.token} (${tx.value_usd})" for tx in large_purchases],
                accounts_involved={tx.from_address for tx in large_purchases}
            )
        return None

    def detect_account_cleanup(self, transactions: List[Transaction]) -> Optional[SuspiciousPattern]:
        """Détecte le nettoyage de comptes intermédiaires"""
        close_account_txs = [tx for tx in transactions if tx.action == "CLOSE ACCOUNT"]
        
        if len(close_account_txs) >= 2:
            # Calculer la récupération totale de rent
            total_recovered = sum(tx.amount for tx in close_account_txs)
            
            return SuspiciousPattern(
                pattern_type="ACCOUNT_CLEANUP",
                confidence=0.7,
                description=f"Nettoyage de {len(close_account_txs)} comptes, récupération: {total_recovered:.3f} SOL",
                evidence=[f"CLOSE: {tx.from_address[:10]}... -> {tx.to_address[:10]}..." for tx in close_account_txs],
                accounts_involved={tx.from_address for tx in close_account_txs}
            )
        return None

    def detect_multiple_distribution(self, transactions: List[Transaction]) -> Optional[SuspiciousPattern]:
        """Détecte la distribution vers comptes multiples (Pattern 6)"""
        distribution_transfers = []
        
        # Rechercher les transferts de même montant vers des adresses différentes
        amount_groups = defaultdict(list)
        for tx in transactions:
            if tx.action == "TRANSFER" and tx.amount > 0:
                # Grouper par montant (arrondi pour gérer les variations mineures)
                rounded_amount = round(tx.amount, 6)
                amount_groups[rounded_amount].append(tx)
        
        # Identifier les distributions suspectes
        for amount, txs in amount_groups.items():
            if len(txs) >= 3:  # Au moins 3 transferts du même montant
                unique_recipients = set(tx.to_address for tx in txs)
                if len(unique_recipients) >= 3:  # Vers des adresses différentes
                    distribution_transfers.extend(txs)
        
        if distribution_transfers:
            return SuspiciousPattern(
                pattern_type="MULTIPLE_DISTRIBUTION",
                confidence=0.8,
                description=f"Distribution coordonnée de {len(distribution_transfers)} transferts vers comptes multiples",
                evidence=[f"Transfer: {tx.amount} {tx.token} to {tx.to_address[:10]}..." for tx in distribution_transfers[:5]],
                accounts_involved={tx.from_address for tx in distribution_transfers} | {tx.to_address for tx in distribution_transfers}
            )
        return None

    def calculate_overall_risk_score(self, patterns: List[SuspiciousPattern]) -> float:
        """Calcule le score de risque global basé sur tous les patterns détectés"""
        if not patterns:
            return 0.0
            
        # Pondération des 6 patterns selon leur importance
        weights = {
            "COORDINATED_ACCOUNT_CREATION": 0.18,   # Pattern 1
            "MULTIPLE_TOKEN_INSTANCES": 0.20,       # Pattern 2 (Metaplex)
            "HIERARCHICAL_FUNDING": 0.20,           # Pattern 3
            "ACCOUNT_CLEANUP": 0.12,                # Pattern 4
            "MASSIVE_INITIAL_PURCHASE": 0.20,       # Pattern 5
            "MULTIPLE_DISTRIBUTION": 0.10           # Pattern 6
        }
        
        weighted_score = 0.0
        total_weight = 0.0
        
        for pattern in patterns:
            weight = weights.get(pattern.pattern_type, 0.1)
            weighted_score += pattern.confidence * weight
            total_weight += weight
            
        return weighted_score / total_weight if total_weight > 0 else 0.0

    def log_pattern_detection(self, pattern_name: str, detected: bool, details: str = "", accounts: Set[str] = None):
        """Log standardisé pour chaque pattern avec couleurs"""
        status_icon = "✅" if detected else "❌"
        status_color = Fore.GREEN if detected else Fore.RED
        
        logger.info(f"{status_icon} Pattern {pattern_name}: {status_color}{'DÉTECTÉ' if detected else 'NON DÉTECTÉ'}{Style.RESET_ALL}")
        if details and detected:
            logger.info(f"   └─ {Fore.CYAN}{details}{Style.RESET_ALL}")
            if accounts and len(accounts) <= 10:  # Limiter l'affichage
                logger.info(f"      Comptes: {Fore.YELLOW}{', '.join([acc[:8]+'...' for acc in sorted(accounts)])}{Style.RESET_ALL}")
            elif accounts and len(accounts) > 10:
                sample_accounts = list(sorted(accounts))[:5]
                logger.info(f"      Comptes (échantillon): {Fore.YELLOW}{', '.join([acc[:8]+'...' for acc in sample_accounts])} et {len(accounts)-5} autres{Style.RESET_ALL}")

    async def analyze_token_launch(self, token_address: str, creator_address: str = None) -> Dict:
        """Analyse complète d'un lancement de token avec logs détaillés"""
        logger.info(f"{'='*60}")
        logger.info(f"🔍 ANALYSE DU TOKEN: {token_address[:20]}...")
        logger.info(f"{'='*60}")
        
        # Utiliser le créateur fourni ou le rechercher
        if creator_address:
            logger.info(f"📝 Créateur fourni: {creator_address[:10]}...")
        else:
            logger.info("🔍 Recherche du créateur du token...")
            creator_address = await self.get_token_creator(token_address)
            
            if not creator_address:
                logger.error("❌ Impossible de trouver le créateur du token")
                return {"error": "Créateur introuvable"}
            
            logger.info(f"✅ Créateur trouvé: {creator_address[:10]}...")
        
        # Récupérer les transactions du créateur
        logger.info("📡 Récupération des transactions du créateur...")
        transactions = await self.get_account_transactions(creator_address)
        
        if not transactions:
            logger.error("❌ Aucune transaction trouvée")
            return {"error": "Aucune transaction trouvée"}
        
        logger.info(f"✅ {len(transactions)} transactions récupérées pour {creator_address[:10]}...")
        logger.info(f"{Fore.CYAN}{'─'*60}{Style.RESET_ALL}")
        
        # Appliquer tous les détecteurs de patterns avec logs
        patterns = []
        
        # Pattern 1: Création coordonnée de comptes
        logger.info("🔄 Analyse Pattern 1: Création coordonnée de comptes...")
        coordination_pattern = self.detect_coordinated_account_creation(transactions)
        if coordination_pattern:
            patterns.append(coordination_pattern)
            self.log_pattern_detection("COORDINATED_ACCOUNTS", True, 
                                     f"{len(coordination_pattern.accounts_involved)} comptes impliqués",
                                     coordination_pattern.accounts_involved)
        else:
            self.log_pattern_detection("COORDINATED_ACCOUNTS", False)
        
        # Pattern 2: Transferts Metaplex multiples
        logger.info("🔄 Analyse Pattern 2: Transferts identiques vers Metaplex...")
        metaplex_pattern = self.detect_metaplex_pattern(transactions)
        if metaplex_pattern:
            patterns.append(metaplex_pattern)
            evidence_count = len(metaplex_pattern.evidence)
            self.log_pattern_detection("METAPLEX_TRANSFERS", True, 
                                     f"{evidence_count} instances de token créées",
                                     metaplex_pattern.accounts_involved)
        else:
            self.log_pattern_detection("METAPLEX_TRANSFERS", False)
        
        # Pattern 3: Financement hiérarchique
        logger.info("🔄 Analyse Pattern 3: Structure hiérarchique de financement...")
        funding_pattern = self.detect_hierarchical_funding(transactions)
        if funding_pattern:
            patterns.append(funding_pattern)
            self.log_pattern_detection("HIERARCHICAL_FUNDING", True, 
                                     "Chaîne de financement détectée",
                                     funding_pattern.accounts_involved)
        else:
            self.log_pattern_detection("HIERARCHICAL_FUNDING", False)
        
        # Pattern 4: Nettoyage de comptes
        logger.info("🔄 Analyse Pattern 4: Fermetures de comptes intermédiaires...")
        cleanup_pattern = self.detect_account_cleanup(transactions)
        if cleanup_pattern:
            patterns.append(cleanup_pattern)
            self.log_pattern_detection("ACCOUNT_CLEANUP", True, 
                                     cleanup_pattern.description,
                                     cleanup_pattern.accounts_involved)
        else:
            self.log_pattern_detection("ACCOUNT_CLEANUP", False)
        
        # Pattern 5: Achat initial massif
        logger.info("🔄 Analyse Pattern 5: Achat initial massif...")
        purchase_pattern = self.detect_massive_initial_purchase(transactions)
        if purchase_pattern:
            patterns.append(purchase_pattern)
            self.log_pattern_detection("MASSIVE_PURCHASE", True, 
                                     purchase_pattern.description,
                                     purchase_pattern.accounts_involved)
        else:
            self.log_pattern_detection("MASSIVE_PURCHASE", False)
        
        # Pattern 6: Distribution vers comptes multiples
        logger.info("🔄 Analyse Pattern 6: Distribution vers comptes multiples...")
        distribution_pattern = self.detect_multiple_distribution(transactions)
        if distribution_pattern:
            patterns.append(distribution_pattern)
            self.log_pattern_detection("MULTIPLE_DISTRIBUTION", True, 
                                     distribution_pattern.description,
                                     distribution_pattern.accounts_involved)
        else:
            self.log_pattern_detection("MULTIPLE_DISTRIBUTION", False)
        
        # Calcul du score de risque global
        risk_score = self.calculate_overall_risk_score(patterns)
        risk_level = self.get_risk_level(risk_score)
        
        # Logs finaux avec résumé coloré
        logger.info(f"{Fore.CYAN}{'─'*60}{Style.RESET_ALL}")
        logger.info(f"📊 {Fore.MAGENTA}RÉSUMÉ DE L'ANALYSE:{Style.RESET_ALL}")
        logger.info(f"   • Patterns détectés: {Fore.YELLOW}{len(patterns)}/6{Style.RESET_ALL}")
        logger.info(f"   • Score de risque: {Fore.YELLOW}{risk_score:.2f}{Style.RESET_ALL}")
        
        # Couleur selon le niveau de risque
        risk_color = self.get_risk_color(risk_score)
        logger.info(f"   • Niveau de risque: {risk_color}{risk_level}{Style.RESET_ALL}")
        
        # Recommandations
        recommendations = self.generate_recommendations(risk_score, patterns)
        if recommendations:
            logger.info(f"💡 {Fore.MAGENTA}RECOMMANDATIONS:{Style.RESET_ALL}")
            for rec in recommendations:
                logger.info(f"   • {rec}")
        
        logger.info(f"{Fore.YELLOW}{'='*60}{Style.RESET_ALL}")
        
        return {
            "token_address": token_address,
            "creator_address": creator_address,
            "analysis_time": datetime.now().isoformat(),
            "transactions_analyzed": len(transactions),
            "patterns_detected": len(patterns),
            "risk_score": risk_score,
            "risk_level": risk_level,
            "patterns": [
                {
                    "type": p.pattern_type,
                    "confidence": p.confidence,
                    "description": p.description,
                    "evidence_count": len(p.evidence),
                    "accounts_involved": len(p.accounts_involved)
                }
                for p in patterns
            ],
            "recommendations": recommendations
        }

    def get_risk_color(self, score: float) -> str:
        """Retourne la couleur selon le score de risque"""
        if score >= 0.8:
            return Fore.RED + Back.WHITE + Style.BRIGHT
        elif score >= 0.6:
            return Fore.RED + Style.BRIGHT
        elif score >= 0.4:
            return Fore.YELLOW + Style.BRIGHT
        elif score >= 0.2:
            return Fore.YELLOW
        else:
            return Fore.GREEN

    def get_risk_level(self, score: float) -> str:
        """Convertit le score numérique en niveau de risque"""
        if score >= 0.8:
            return "TRÈS ÉLEVÉ"
        elif score >= 0.6:
            return "ÉLEVÉ"
        elif score >= 0.4:
            return "MODÉRÉ"
        elif score >= 0.2:
            return "FAIBLE"
        else:
            return "MINIMAL"

    def generate_recommendations(self, risk_score: float, patterns: List[SuspiciousPattern]) -> List[str]:
        """Génère des recommandations basées sur l'analyse"""
        recommendations = []
        
        if risk_score >= 0.8:
            recommendations.append("⚠️  ATTENTION: Fortes suspicions de manipulation coordonnée")
            recommendations.append("❌ Éviter absolument d'investir dans ce token")
            recommendations.append("🚨 Signaler ce token aux plateformes d'échange")
            
        elif risk_score >= 0.6:
            recommendations.append("⚠️  PRUDENCE: Suspicions modérées de manipulation")
            recommendations.append("⏸️  Reporter l'investissement jusqu'à clarification")
            
        elif risk_score >= 0.4:
            recommendations.append("🤔 VIGILANCE: Quelques signaux d'alarme détectés")
            recommendations.append("🔍 Effectuer des recherches approfondies avant investissement")
            
        # Recommandations spécifiques par pattern
        pattern_types = {p.pattern_type for p in patterns}
        
        if "MULTIPLE_TOKEN_INSTANCES" in pattern_types:
            recommendations.append("🔄 Instances multiples détectées - possibles tests ou échecs")
            
        if "HIERARCHICAL_FUNDING" in pattern_types:
            recommendations.append("🏗️  Structure financière complexe - obfuscation potentielle")
            
        if "MASSIVE_INITIAL_PURCHASE" in pattern_types:
            recommendations.append("🐋 Whale détecté - risque de dump massif")
            
        if "COORDINATED_ACCOUNT_CREATION" in pattern_types:
            recommendations.append("🎭 Comptes coordonnés - manipulation organisée suspectée")
            
        if "MULTIPLE_DISTRIBUTION" in pattern_types:
            recommendations.append("📤 Distribution coordonnée - préparation pump & dump")
            
        if risk_score < 0.2:
            recommendations.append("✅ Patterns de manipulation limités détectés")
            recommendations.append("📊 Effectuer une analyse fondamentale classique")
            
        return recommendations

# Fonction CLI principale
async def run_analysis(token_address: str, creator_address: str = None, rpc_endpoint: str = "https://api.mainnet-beta.solana.com"):
    """Lance l'analyse pour une adresse donnée"""
    try:
        async with PumpDumpDetector(rpc_endpoint) as detector:
            await detector.analyze_token_launch(token_address, creator_address)
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'analyse: {e}")
        return 1
    return 0

def main():
    """Point d'entrée principal avec gestion des arguments"""
    parser = argparse.ArgumentParser(
        description="Détecteur de Patterns Pump & Dump pour tokens Solana",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples d'usage:
  python pump_detector.py So11111111111111111111111111111111111111112
  python pump_detector.py --rpc https://api.mainnet-beta.solana.com So11111111111111111111111111111111111111112
  
Patterns détectés:
  1. ✅/❌ Création coordonnée de comptes multiples
  2. ✅/❌ Transferts identiques vers Metaplex (3.08$)
  3. ✅/❌ Structure hiérarchique de financement
  4. ✅/❌ Fermetures de comptes intermédiaires
  5. ✅/❌ Achats massifs initiaux
  6. ✅/❌ Distribution vers comptes multiples
        """
    )
    
    parser.add_argument(
        'token_address',
        help='Adresse du token à analyser (format Solana)'
    )
    
    parser.add_argument(
        '--creator', '-c',
        help='Adresse du créateur du token (optionnel - sera recherchée automatiquement si non fournie)'
    )

    parser.add_argument(
        '--rpc',
        default="https://api.mainnet-beta.solana.com",
        help='Endpoint RPC Solana (défaut: api.mainnet-beta.solana.com)'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Mode verbose (plus de détails)'
    )
    
    args = parser.parse_args()
    
    # Configuration du niveau de log
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    # Validation de l'adresse
    if len(args.token_address) < 32 or len(args.token_address) > 44:
        logger.error(f"Adresse token invalide: {args.token_address}")
        logger.error("   Format attendu: adresse Solana (32-44 caractères)")
        return 1
    
    # Lancement de l'analyse
    logger.info(f"Démarrage du détecteur Pump & Dump")
    logger.info(f"RPC: {args.rpc}")
    
    return asyncio.run(run_analysis(args.token_address, args.creator, args.rpc))

# Exemple d'utilisation programmatique
async def example_usage():
    """Exemple d'utilisation du détecteur"""
    
    # Adresse du token CABAL (exemple)
    cabal_token = "your_token_address_here"
    
    async with PumpDumpDetector() as detector:
        result = await detector.analyze_token_launch(cabal_token)
        return result

if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info(f"\nAnalyse interrompue par l'utilisateur")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Erreur critique: {e}")
        sys.exit(1)