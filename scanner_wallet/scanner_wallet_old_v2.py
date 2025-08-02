#!/usr/bin/env python3
"""
Moniteur de Wallet Solana avec support QuickNode API
Surveille les transactions d'un wallet Solana et les sauvegarde dans SQLite
"""

import sqlite3
import requests
import json
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
import threading

# Importer la configuration
try:
    from config import DefaultConfig as Config
    print("✅ Configuration chargée depuis config.py")
except ImportError:
    print("⚠️ config.py non trouvé, utilisation des valeurs par défaut")
    # Configuration de fallback si config.py n'existe pas
    class Config:
        WALLET_ADDRESS = "2RH6rUTPBJ9rUDPpuV9b8z1YL56k1tYU6Uk5ZoaEFFSK"
        QUICKNODE_ENDPOINT = "https://methodical-cosmological-card.solana-mainnet.quiknode.pro/d843e0882bc67b641b842dbd96f704e5ec04bf14/"
        UPDATE_INTERVAL = 45
        DB_NAME = "solana_wallet.db"
        DEFAULT_TRANSACTION_LIMIT = 35
        MAX_RETRIES = 3
        RETRY_DELAY = 2
        PAUSE_BETWEEN_TX_DETAILS = 0.1
        MAX_CONSECUTIVE_ERRORS = 3
        FLASK_HOST = '127.0.0.1'
        FLASK_PORT = 5000
        FLASK_DEBUG = True
        
        @classmethod
        def get_rpc_endpoints(cls):
            return [
                cls.QUICKNODE_ENDPOINT if cls.QUICKNODE_ENDPOINT else "https://api.mainnet-beta.solana.com",
                "https://rpc.ankr.com/solana",
                "https://api.mainnet-beta.solana.com",
                "https://solana.public-rpc.com"
            ]
        
        @classmethod
        def get_rpc_headers(cls):
            return {
                'Content-Type': 'application/json',
                'User-Agent': 'SolanaWalletMonitor/1.0-QuickNode',
                'Accept': 'application/json',
            }


WALLET_ADDRESS = Config.WALLET_ADDRESS
WALLET_ADDRESSES = Config.WALLET_ADDRESSES
RPC_ENDPOINTS = Config.get_rpc_endpoints()
CURRENT_RPC_INDEX = 0
DB_NAME = Config.DB_NAME
UPDATE_INTERVAL = Config.UPDATE_INTERVAL
MAX_RETRIES = Config.MAX_RETRIES
RETRY_DELAY = Config.RETRY_DELAY

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('wallet_monitor.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class SolanaWalletMonitor:
    def __init__(self, wallet_addresses: List[str], db_name: str):  
        self.wallet_addresses = wallet_addresses  # Liste de wallets
        self.wallet_address = wallet_addresses[0] if wallet_addresses else None
        self.db_name = db_name
        self.token_cache = {}
        self.init_database()
    
    def get_balance_changes_for_wallet_old(self, wallet_address: str, limit: int = 20) -> List[Dict]:
        """
        Récupère les balance changes (comme Solscan Balance Changes)
        en scannant les comptes de tokens associés au wallet
        """
        try:
            logger.info(f"🔍 Scanning balance changes pour {wallet_address[:8]}...")
            
            # 1. Récupérer tous les comptes de tokens actuels
            current_token_accounts = self.get_solana_rpc_data(
                "getTokenAccountsByOwner",
                [
                    wallet_address,
                    {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                    {"encoding": "jsonParsed"}
                ]
            )
            
            if not current_token_accounts or "result" not in current_token_accounts:
                logger.warning(f"Aucun compte de token trouvé pour {wallet_address[:8]}...")
                return []
            
            balance_changes = []
            token_accounts = current_token_accounts["result"]["value"]
            
            logger.info(f"📊 Trouvé {len(token_accounts)} comptes de tokens pour {wallet_address[:8]}...")
            i = 0
            # 2. Pour chaque compte de token, récupérer l'historique
            for account in token_accounts:
                i+=1
                print(f"i = {i}")
                try:
                    account_pubkey = account["pubkey"]
                    token_info = account["account"]["data"]["parsed"]["info"]
                    token_mint = token_info["mint"]
                    
                    # Récupérer les signatures pour ce compte de token (balance changes)
                    signatures_result = self.get_solana_rpc_data(
                        "getSignaturesForAddress",
                        [account_pubkey, {"limit": min(limit, 15)}]  # Limité pour éviter le spam
                    )
                    
                    if signatures_result and "result" in signatures_result:
                        signatures = signatures_result["result"]
                        logger.debug(f"🔍 {len(signatures)} signatures trouvées pour le token {token_mint[:8]}...")
                        
                        for sig_info in signatures:
                            signature = sig_info["signature"]
                            
                            # Vérifier si cette signature existe déjà dans notre DB
                            if self.signature_exists_in_db(signature):
                                logger.debug(f"⏭️ Signature {signature[:10]}... déjà en DB, skip")
                                continue
                            
                            # Récupérer les détails de la transaction
                            tx_detail = self.get_solana_rpc_data(
                                "getTransaction",
                                [signature, {"encoding": "json", "maxSupportedTransactionVersion": 0}]
                            )
                            
                            if tx_detail and tx_detail.get("result"):
                                # Analyser ce balance change
                                balance_change = self.analyze_balance_change_transaction(
                                    tx_detail, wallet_address, token_mint, account_pubkey
                                )
                                
                                if balance_change:
                                    balance_changes.append(balance_change)
                                    logger.info(f"✅ Balance change détecté: {balance_change['token_symbol']} "
                                            f"({balance_change['amount_change']:+,.4f})")
                    
                    # Pause entre les comptes pour éviter le rate limiting
                    time.sleep(0.2)
                    
                except Exception as e:
                    logger.warning(f"Erreur lors de l'analyse du compte token {account.get('pubkey', 'UNKNOWN')}: {e}")
                    continue
            
            logger.info(f"🎯 Balance changes trouvés: {len(balance_changes)} pour {wallet_address[:8]}...")
            return balance_changes
            
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des balance changes: {e}")
            return []

    def get_balance_changes_for_wallet(self, wallet_address: str, limit: int = 30, time_window_hours: int = 1) -> List[Dict]:
        """
        Récupère les 30 balance changes les plus récents pour un wallet donné en scannant ses comptes de tokens.
        :param wallet_address: Adresse du wallet Solana
        :param limit: Nombre maximum de balance changes à retourner
        :param time_window_hours: Fenêtre temporelle en heures pour filtrer les transactions récentes
        """
        try:
            logger.info(f"🔍 Récupération des {limit} balance changes les plus récents pour {wallet_address[:8]}...")

            # 1. Récupérer tous les comptes de tokens associés au wallet
            current_token_accounts = self.get_solana_rpc_data(
                "getTokenAccountsByOwner",
                [
                    wallet_address,
                    {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                    {"encoding": "jsonParsed"}
                ]
            )

            if not current_token_accounts or "result" not in current_token_accounts:
                logger.warning(f"Aucun compte de token trouvé pour {wallet_address[:8]}...")
                return []

            token_accounts = current_token_accounts["result"]["value"]
            logger.info(f"📊 Trouvé {len(token_accounts)} comptes de tokens pour {wallet_address[:8]}...")

            # Calculer le timestamp minimum (actuel - time_window_hours)
            current_time = int(time.time())
            min_timestamp = current_time - (time_window_hours * 3600)

            # 2. Collecter les signatures récentes pour chaque compte de token
            all_signatures = []
            for account in token_accounts:
                account_pubkey = account["pubkey"]
                signatures_result = self.get_solana_rpc_data(
                    "getSignaturesForAddress",
                    [account_pubkey, {"limit": 15, "commitment": "finalized"}]
                )

                if signatures_result and "result" in signatures_result:
                    signatures = [
                        sig for sig in signatures_result["result"]
                        if sig["blockTime"] and sig["blockTime"] >= min_timestamp
                    ]
                    all_signatures.extend(signatures)
                    logger.debug(f"🔍 {len(signatures)} signatures récentes trouvées pour le compte {account_pubkey[:8]}...")

                time.sleep(0.1)  # Pause pour éviter le rate limiting

            if not all_signatures:
                logger.warning(f"Aucune signature récente trouvée pour les comptes de tokens de {wallet_address[:8]}...")
                return []

            # 3. Trier les signatures par blockTime (du plus récent au plus ancien) et dédupliquer
            all_signatures = sorted(
                list({sig["signature"]: sig for sig in all_signatures}.values()),
                key=lambda x: x["blockTime"] or 0,
                reverse=True
            )[:limit * 2]  # Prendre un peu plus pour compenser les signatures sans balance change

            logger.info(f"📊 Total {len(all_signatures)} signatures uniques à analyser pour {wallet_address[:8]}...")

            # 4. Analyser les transactions pour extraire les balance changes
            balance_changes = []
            processed_signatures = 0

            for sig_info in all_signatures:
                if len(balance_changes) >= limit:
                    break

                signature = sig_info["signature"]
                logger.debug(f"Analyse de la signature {signature[:10]}... (blockTime: {sig_info['blockTime']})")

                # Vérifier si la signature existe déjà dans la DB
                if self.signature_exists_in_db(signature):
                    logger.debug(f"⏭️ Signature {signature[:10]}... déjà en DB, skip")
                    continue

                # Récupérer les détails de la transaction
                tx_detail = self.get_solana_rpc_data(
                    "getTransaction",
                    [signature, {"encoding": "json", "maxSupportedTransactionVersion": 0}]
                )

                if not tx_detail or not tx_detail.get("result"):
                    logger.debug(f"⚠️ Transaction {signature[:10]}... non trouvée ou invalide")
                    continue

                # Analyser les balance changes pour cette transaction
                balance_change = self.analyze_balance_change_transaction(
                    tx_detail, wallet_address
                )

                if balance_change:
                    balance_changes.extend(balance_change)
                    for change in balance_change:
                        logger.info(
                            f"✅ Balance change détecté: {change['token_symbol']} "
                            f"({change['amount_change']:+,.4f})"
                        )

                processed_signatures += 1
                time.sleep(0.2)  # Pause pour éviter le rate limiting

            logger.info(f"🎯 Total balance changes trouvés : {len(balance_changes)} pour {wallet_address[:8]}...")
            return sorted(balance_changes, key=lambda x: x["block_time"] or 0, reverse=True)[:limit]

        except Exception as e:
            logger.error(f"Erreur lors de la récupération des balance changes: {e}")
            return []

    def get_balance_changes_for_wallet_old_v1(self, wallet_address: str, limit: int = 30) -> List[Dict]:
        """
        Récupère les 30 balance changes les plus récents pour un wallet donné.
        """
        try:
            logger.info(f"🔍 Récupération des {limit} balance changes les plus récents pour {wallet_address[:8]}...")

            # 1. Récupérer les signatures récentes pour le wallet
            signatures_result = self.get_solana_rpc_data(
                "getSignaturesForAddress",
                [wallet_address, {"limit": limit, "commitment": "finalized"}]
            )

            if not signatures_result or "result" not in signatures_result:
                logger.warning(f"Aucune transaction trouvée pour {wallet_address[:8]}...")
                return []

            signatures = signatures_result["result"]
            logger.info(f"📊 Trouvé {len(signatures)} transactions pour {wallet_address[:8]}...")

            balance_changes = []
            processed_signatures = 0

            # 2. Parcourir chaque signature (transaction)
            for sig_info in signatures:
                if processed_signatures >= limit:
                    break

                signature = sig_info["signature"]

                # Vérifier si la signature existe déjà dans la DB
                if self.signature_exists_in_db(signature):
                    logger.debug(f"⏭️ Signature {signature[:10]}... déjà en DB, skip")
                    continue

                # 3. Récupérer les détails de la transaction
                tx_detail = self.get_solana_rpc_data(
                    "getTransaction",
                    [signature, {"encoding": "json", "maxSupportedTransactionVersion": 0}]
                )

                if not tx_detail or not tx_detail.get("result"):
                    logger.debug(f"⚠️ Transaction {signature[:10]}... non trouvée ou invalide")
                    continue

                # 4. Analyser les balance changes pour cette transaction
                # (On suppose que analyze_balance_change_transaction peut extraire tous les changements de balance pour les tokens dans cette tx)
                balance_change = self.analyze_balance_change_transaction(
                    tx_detail, wallet_address
                )

                if balance_change:
                    balance_changes.extend(balance_change)
                    for change in balance_change:
                        logger.info(
                            f"✅ Balance change détecté: {change['token_symbol']} "
                            f"({change['amount_change']:+,.4f})"
                        )

                processed_signatures += 1

                # Pause pour éviter le rate limiting
                time.sleep(0.2)

            logger.info(f"🎯 Total balance changes trouvés : {len(balance_changes)} pour {wallet_address[:8]}...")
            return balance_changes[:limit]  # S'assurer de ne retourner que le nombre demandé

        except Exception as e:
            logger.error(f"Erreur lors de la récupération des balance changes: {e}")
            return []

    def signature_exists_in_db(self, signature: str) -> bool:
        """Vérifie si une signature existe déjà dans la DB"""
        try:
            conn = sqlite3.connect(self.db_name)
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM transactions WHERE signature = ? LIMIT 1", (signature,))
            exists = cursor.fetchone() is not None
            conn.close()
            return exists
        except Exception as e:
            logger.error(f"Erreur lors de la vérification de signature: {e}")
            return False

    def analyze_balance_change_transaction(self, tx_detail: Dict, wallet_address: str) -> List[Dict]:
        """
        Analyse une transaction pour extraire tous les balance changes pour les comptes de tokens associés au wallet.
        Retourne une liste de balance changes.
        """
        try:
            tx = tx_detail["result"]
            meta = tx.get("meta", {})
            balance_changes = []
            signature = tx.get("transaction", {}).get("signatures", [None])[0]
            logger.debug(f"📝 Analyse de la transaction {signature[:10]}...")

            # Récupérer les comptes de tokens associés au wallet
            token_accounts_result = self.get_solana_rpc_data(
                "getTokenAccountsByOwner",
                [
                    wallet_address,
                    {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                    {"encoding": "jsonParsed"}
                ]
            )

            if not token_accounts_result or "result" not in token_accounts_result:
                logger.debug(f"❌ Aucun compte de token trouvé pour {wallet_address[:8]}...")
                return []

            token_accounts = {
                account["pubkey"]: account["account"]["data"]["parsed"]["info"]["mint"]
                for account in token_accounts_result["result"]["value"]
            }
            logger.debug(f"🔍 {len(token_accounts)} comptes de tokens associés trouvés pour {wallet_address[:8]}...")

            # Analyser les changements de balance pour tous les tokens
            pre_token_balances = meta.get("preTokenBalances", [])
            post_token_balances = meta.get("postTokenBalances", [])
            logger.debug(f"📊 {len(pre_token_balances)} preTokenBalances, {len(post_token_balances)} postTokenBalances")

            for pre_balance in pre_token_balances:
                pre_owner = pre_balance.get("owner")
                pre_account_index = pre_balance.get("accountIndex")
                token_mint = pre_balance.get("mint")
                token_account = pre_balance.get("programId")  # Adresse du compte de token

                # Vérifier si ce compte de token appartient au wallet
                for token_account_pubkey, mint in token_accounts.items():
                    if token_mint == mint and pre_owner == wallet_address:
                        logger.debug(f"🔎 Compte de token {token_account_pubkey[:8]}... trouvé pour mint {token_mint[:8]}...")

                        # Trouver le post_balance correspondant
                        for post_balance in post_token_balances:
                            if (
                                post_balance.get("mint") == token_mint
                                and post_balance.get("accountIndex") == pre_account_index
                                and post_balance.get("owner") == wallet_address
                            ):
                                pre_amount = float(pre_balance.get("uiTokenAmount", {}).get("uiAmount") or 0)
                                post_amount = float(post_balance.get("uiTokenAmount", {}).get("uiAmount") or 0)
                                amount_change = post_amount - pre_amount

                                if abs(amount_change) > 0.000001:  # Changement significatif
                                    logger.info(f"✅ Changement détecté: {amount_change:+.4f} pour {token_mint[:8]}...")
                                    token_change = {
                                        "amount_change": amount_change,
                                        "pre_balance": pre_amount,
                                        "post_balance": post_amount,
                                        "decimals": post_balance.get("uiTokenAmount", {}).get("decimals", 9),
                                        "token_mint": token_mint,
                                        "token_account": token_account_pubkey,
                                    }

                                    # Calculer le changement SOL pour ce wallet
                                    accounts = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
                                    pre_balances = meta.get("preBalances", [])
                                    post_balances = meta.get("postBalances", [])

                                    sol_change = 0
                                    wallet_index = None
                                    for i, account in enumerate(accounts):
                                        if account == wallet_address:
                                            wallet_index = i
                                            break

                                    if wallet_index is not None and wallet_index < len(pre_balances):
                                        pre_sol = pre_balances[wallet_index] if pre_balances[wallet_index] is not None else 0
                                        post_sol = post_balances[wallet_index] if post_balances[wallet_index] is not None else 0
                                        sol_change = (post_sol - pre_sol) / 1e9

                                    # Récupérer les métadonnées du token
                                    try:
                                        token_metadata = self.get_token_metadata(token_mint)
                                        token_symbol = token_metadata["symbol"]
                                        token_name = token_metadata["name"]
                                        if token_symbol == "UNKNOWN":
                                            token_symbol = f"TOKEN_{token_mint[:6]}"
                                            token_name = f"Unknown Token {token_mint[:6]}"
                                            logger.warning(f"⚠️ Token non identifié: {token_mint[:8]}... -> {token_symbol}")
                                    except Exception as e:
                                        logger.warning(f"Erreur métadonnées token {token_mint}: {e}")
                                        token_symbol = "UNKNOWN"
                                        token_name = "Unknown Token"

                                    # Déterminer le type de transaction
                                    transaction_type = "other"
                                    price_per_token = 0
                                    is_large_token_amount = False
                                    SOL_CHANGE_THRESHOLD = 0.001

                                    if amount_change > 0:  # Tokens reçus
                                        if sol_change < -SOL_CHANGE_THRESHOLD:
                                            transaction_type = "buy"
                                            price_per_token = abs(sol_change) / abs(amount_change) if amount_change != 0 else 0
                                        elif abs(sol_change) <= SOL_CHANGE_THRESHOLD:
                                            fee = meta.get("fee", 0) / 1e9
                                            if fee > 0.001:
                                                transaction_type = "buy"
                                                price_per_token = fee / abs(amount_change) if amount_change != 0 else 0
                                            else:
                                                transaction_type = "transfer"
                                        else:
                                            transaction_type = "transfer"
                                    elif amount_change < 0:  # Tokens envoyés
                                        if sol_change > SOL_CHANGE_THRESHOLD:
                                            transaction_type = "sell"
                                            price_per_token = abs(sol_change) / abs(amount_change) if amount_change != 0 else 0
                                        else:
                                            transaction_type = "transfer"

                                    # Détecter les grosses quantités
                                    abs_amount = abs(amount_change)
                                    decimals = token_change["decimals"]
                                    if (
                                        abs_amount >= 100000
                                        or (abs_amount >= 1000 and decimals <= 6)
                                        or (abs_amount >= 10 and decimals <= 2)
                                    ):
                                        is_large_token_amount = True

                                    # Construire la transaction
                                    balance_change_tx = {
                                        "signature": signature,
                                        "wallet_address": wallet_address,
                                        "slot": tx.get("slot", 0),
                                        "block_time": tx.get("blockTime"),
                                        "amount": sol_change,
                                        "fee": meta.get("fee", 0) / 1e9,
                                        "status": "success" if meta.get("err") is None else "failed",
                                        "accounts": accounts,
                                        "transaction_type": transaction_type,
                                        "token_mint": token_mint,
                                        "token_symbol": token_symbol,
                                        "token_name": token_name,
                                        "token_amount": abs(amount_change),
                                        "amount_change": amount_change,
                                        "price_per_token": price_per_token,
                                        "is_token_transaction": True,
                                        "is_large_token_amount": is_large_token_amount,
                                        "source": "balance_change",
                                    }

                                    balance_changes.append(balance_change_tx)
                                break

            logger.debug(f"📝 Transaction {signature[:10]}... : {len(balance_changes)} balance changes détectés")
            return balance_changes

        except Exception as e:
            logger.error(f"Erreur lors de l'analyse du balance change: {e}")
            return []
        
    def analyze_balance_change_transaction_old(self, tx_detail: Dict, wallet_address: str, 
                                        token_mint: str, token_account: str) -> Optional[Dict]:
        """
        Analyse une transaction balance change pour extraire les infos pertinentes
        """
        try:
            tx = tx_detail["result"]
            meta = tx.get("meta", {})
            
            # Analyser les changements de balance pour ce token spécifique
            pre_token_balances = meta.get("preTokenBalances", [])
            post_token_balances = meta.get("postTokenBalances", [])
            
            # Trouver les changements pour ce compte de token spécifique
            token_change = None
            
            for pre_balance in pre_token_balances:
                if pre_balance.get("mint") == token_mint:
                    # Trouver le post_balance correspondant
                    for post_balance in post_token_balances:
                        if (post_balance.get("mint") == token_mint and 
                            post_balance.get("accountIndex") == pre_balance.get("accountIndex")):
                            
                            pre_amount = float(pre_balance.get("uiTokenAmount", {}).get("uiAmount") or 0)
                            post_amount = float(post_balance.get("uiTokenAmount", {}).get("uiAmount") or 0)
                            amount_change = post_amount - pre_amount
                            
                            if abs(amount_change) > 0.000001:  # Changement significatif
                                token_change = {
                                    'amount_change': amount_change,
                                    'pre_balance': pre_amount,
                                    'post_balance': post_amount,
                                    'decimals': post_balance.get("uiTokenAmount", {}).get("decimals", 9)
                                }
                                break
                    
                    if token_change:
                        break
            
            if not token_change:
                return None
            
            # Calculer le changement SOL pour ce wallet
            accounts = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
            pre_balances = meta.get("preBalances", [])
            post_balances = meta.get("postBalances", [])
            
            sol_change = 0
            wallet_index = None
            for i, account in enumerate(accounts):
                if account == wallet_address:
                    wallet_index = i
                    break
            
            if wallet_index is not None and wallet_index < len(pre_balances):
                pre_sol = pre_balances[wallet_index] if pre_balances[wallet_index] is not None else 0
                post_sol = post_balances[wallet_index] if post_balances[wallet_index] is not None else 0
                sol_change = (post_sol - pre_sol) / 1e9
            
            # Récupérer les métadonnées du token
            try:
                token_metadata = self.get_token_metadata(token_mint)
                token_symbol = token_metadata['symbol']
                token_name = token_metadata['name']
                # FALLBACK pour tokens inconnus
                if token_symbol == 'UNKNOWN':
                    # Essayer d'extraire des infos du mint address
                    token_symbol = f"TOKEN_{token_mint[:6]}"
                    token_name = f"Unknown Token {token_mint[:6]}"
                    logger.warning(f"⚠️ Token non identifié: {token_mint[:8]}... -> {token_symbol}")

            except Exception as e:
                logger.warning(f"Erreur métadonnées token {token_mint}: {e}")
                token_symbol = 'UNKNOWN'
                token_name = 'Unknown Token'
            
            # Déterminer le type de transaction
            amount_change = token_change['amount_change']
            transaction_type = 'other'
            price_per_token = 0
            is_large_token_amount = False
            
            # Logique de détection similaire à ton code existant
            SOL_CHANGE_THRESHOLD = 0.001
            
            if amount_change > 0:  # Tokens reçus
                if sol_change < -SOL_CHANGE_THRESHOLD:
                    transaction_type = 'buy'
                    price_per_token = abs(sol_change) / abs(amount_change) if amount_change != 0 else 0
                elif abs(sol_change) <= SOL_CHANGE_THRESHOLD:
                    fee = meta.get('fee', 0) / 1e9
                    if fee > 0.001:
                        transaction_type = 'buy'
                        price_per_token = fee / abs(amount_change) if amount_change != 0 else 0
                    else:
                        transaction_type = 'transfer'
                else:
                    transaction_type = 'transfer'
            elif amount_change < 0:  # Tokens envoyés
                if sol_change > SOL_CHANGE_THRESHOLD:
                    transaction_type = 'sell'
                    price_per_token = abs(sol_change) / abs(amount_change) if amount_change != 0 else 0
                else:
                    transaction_type = 'transfer'
            
            # Détecter les grosses quantités
            abs_amount = abs(amount_change)
            decimals = token_change['decimals']
            if (abs_amount >= 100000 or 
                abs_amount >= 1000 and decimals <= 6 or 
                abs_amount >= 10 and decimals <= 2):
                is_large_token_amount = True
            
            # Construire la transaction
            balance_change_tx = {
                "signature": tx.get("transaction", {}).get("signatures", [None])[0],
                "wallet_address": wallet_address,
                "slot": tx.get("slot", 0),
                "block_time": tx.get("blockTime"),
                "amount": sol_change,
                "fee": meta.get("fee", 0) / 1e9,
                "status": "success" if meta.get("err") is None else "failed",
                "accounts": accounts,
                "transaction_type": transaction_type,
                "token_mint": token_mint,
                "token_symbol": token_symbol,
                "token_name": token_name,
                "token_amount": abs(amount_change),
                "amount_change": amount_change,  # Gardé pour debug
                "price_per_token": price_per_token,
                "is_token_transaction": True,
                "is_large_token_amount": is_large_token_amount,
                "source": "balance_change"  # Pour identifier la source
            }
            
            return balance_change_tx
            
        except Exception as e:
            logger.error(f"Erreur lors de l'analyse du balance change: {e}")
            return None

    def update_database_schema(self, cursor):
        """
        Met à jour la structure de la base de données avec optimisations pour token summary
        """
        # Liste des colonnes à ajouter si elles n'existent pas
        columns_to_add = [
            ('wallet_address', 'TEXT'),
            ('token_mint', 'TEXT'),
            ('token_symbol', 'TEXT'),
            ('token_name', 'TEXT'),
            ('transaction_type', 'TEXT'),
            ('token_amount', 'REAL'),
            ('price_per_token', 'REAL'),
            ('is_token_transaction', 'BOOLEAN DEFAULT 0'),
            ('is_large_token_amount', 'BOOLEAN DEFAULT 0')
        ]
        
        # Récupérer la structure actuelle de la table
        cursor.execute("PRAGMA table_info(transactions)")
        existing_columns = [row[1] for row in cursor.fetchall()]
        
        # Ajouter les colonnes manquantes
        for column_name, column_type in columns_to_add:
            if column_name not in existing_columns:
                try:
                    cursor.execute(f'ALTER TABLE transactions ADD COLUMN {column_name} {column_type}')
                    logger.info(f"✅ Colonne '{column_name}' ajoutée à la table transactions")
                except sqlite3.OperationalError as e:
                    logger.warning(f"⚠️ Impossible d'ajouter la colonne '{column_name}': {e}")

        # Créer des index pour optimiser les requêtes GROUP BY
        indexes_to_create = [
            ("idx_token_mint", "CREATE INDEX IF NOT EXISTS idx_token_mint ON transactions(token_mint)"),
            ("idx_wallet_token", "CREATE INDEX IF NOT EXISTS idx_wallet_token ON transactions(wallet_address, token_mint)"),
            ("idx_transaction_type", "CREATE INDEX IF NOT EXISTS idx_transaction_type ON transactions(transaction_type)"),
            ("idx_block_time", "CREATE INDEX IF NOT EXISTS idx_block_time ON transactions(block_time)"),
            ("idx_token_transactions", "CREATE INDEX IF NOT EXISTS idx_token_transactions ON transactions(is_token_transaction, token_mint)")
        ]
        
        for index_name, index_sql in indexes_to_create:
            try:
                cursor.execute(index_sql)
                logger.info(f"✅ Index '{index_name}' créé")
            except sqlite3.OperationalError as e:
                logger.debug(f"Index '{index_name}' existe déjà ou erreur: {e}")

        # Créer une table pour le cache des token summaries (optionnel)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS token_summary_cache (
                token_mint TEXT PRIMARY KEY,
                wallet_address TEXT,
                symbol TEXT,
                name TEXT,
                total_buys INTEGER DEFAULT 0,
                total_sells INTEGER DEFAULT 0,
                total_bought_amount REAL DEFAULT 0,
                total_sold_amount REAL DEFAULT 0,
                total_sol_spent REAL DEFAULT 0,
                total_sol_received REAL DEFAULT 0,
                avg_buy_price REAL DEFAULT 0,
                avg_sell_price REAL DEFAULT 0,
                net_position REAL DEFAULT 0,
                estimated_pnl REAL DEFAULT 0,
                first_transaction_time INTEGER,
                last_transaction_time INTEGER,
                unique_wallets TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        logger.info("✅ Table token_summary_cache créée/mise à jour")

    def get_token_metadata(self, mint_address: str) -> Dict:
        """
        Récupère les métadonnées d'un token avec cache et fallbacks multiples
        """
        # Vérifier le cache d'abord
        if mint_address in self.token_cache:
            cached_data = self.token_cache[mint_address]
            # Vérifier si le cache n'est pas expiré (1 heure)
            if (datetime.now() - cached_data['cached_at']).seconds < 3600:
                return cached_data['data']
        
        token_metadata = {
            'mint': mint_address,
            'symbol': 'UNKNOWN',
            'name': 'Unknown Token',
            'decimals': 9,
            'logo_uri': None,
            'coingecko_id': None
        }
        
        try:
            # Méthode 1: Jupiter Token List (le plus fiable)
            try:
                response = requests.get(
                    'https://token.jup.ag/all',
                    timeout=10,
                    headers={'Accept': 'application/json'}
                )
                if response.status_code == 200:
                    tokens = response.json()
                    for token in tokens:
                        if token.get('address') == mint_address:
                            token_metadata.update({
                                'symbol': token.get('symbol', 'UNKNOWN'),
                                'name': token.get('name', 'Unknown Token'),
                                'decimals': token.get('decimals', 9),
                                'logo_uri': token.get('logoURI'),
                            })
                            logger.debug(f"✅ Token trouvé via Jupiter: {token_metadata['symbol']}")
                            break
            except Exception as e:
                logger.warning(f"Erreur Jupiter API pour {mint_address}: {e}")
            
            # Méthode 2: Fallback avec Solana Token Registry
            if token_metadata['symbol'] == 'UNKNOWN':
                try:
                    response = requests.get(
                        'https://raw.githubusercontent.com/solana-labs/token-list/main/src/tokens/solana.tokenlist.json',
                        timeout=10
                    )
                    if response.status_code == 200:
                        token_list = response.json()
                        for token in token_list.get('tokens', []):
                            if token.get('address') == mint_address:
                                token_metadata.update({
                                    'symbol': token.get('symbol', 'UNKNOWN'),
                                    'name': token.get('name', 'Unknown Token'),
                                    'decimals': token.get('decimals', 9),
                                    'logo_uri': token.get('logoURI'),
                                })
                                logger.debug(f"✅ Token trouvé via Solana Registry: {token_metadata['symbol']}")
                                break
                except Exception as e:
                    logger.warning(f"Erreur Solana Registry pour {mint_address}: {e}")
            
            # Méthode 3: RPC Solana pour les métadonnées on-chain
            if token_metadata['symbol'] == 'UNKNOWN':
                try:
                    # Récupérer les métadonnées depuis la blockchain
                    metadata_result = self.get_solana_rpc_data(
                        "getAccountInfo",
                        [mint_address, {"encoding": "jsonParsed"}]
                    )
                    
                    if metadata_result and metadata_result.get('result', {}).get('value'):
                        account_data = metadata_result['result']['value']
                        if account_data.get('data', {}).get('parsed'):
                            parsed_info = account_data['data']['parsed'].get('info', {})
                            token_metadata.update({
                                'decimals': parsed_info.get('decimals', 9),
                            })
                            logger.debug(f"✅ Métadonnées on-chain récupérées pour {mint_address}")
                except Exception as e:
                    logger.warning(f"Erreur métadonnées on-chain pour {mint_address}: {e}")
            
            # Méthode 4: Essayer de récupérer depuis DexScreener (pour les tokens populaires)
            if token_metadata['symbol'] == 'UNKNOWN':
                try:
                    response = requests.get(
                        f'https://api.dexscreener.com/latest/dex/tokens/{mint_address}',
                        timeout=5
                    )
                    if response.status_code == 200:
                        data = response.json()
                        if data.get('pairs') and len(data['pairs']) > 0:
                            token_info = data['pairs'][0].get('baseToken', {})
                            if token_info.get('address') == mint_address:
                                token_metadata.update({
                                    'symbol': token_info.get('symbol', 'UNKNOWN'),
                                    'name': token_info.get('name', 'Unknown Token'),
                                })
                                logger.debug(f"✅ Token trouvé via DexScreener: {token_metadata['symbol']}")
                except Exception as e:
                    logger.warning(f"Erreur DexScreener pour {mint_address}: {e}")
            
            if token_metadata['symbol'] == 'UNKNOWN':
                short_mint = mint_address[:6].upper()
                token_metadata.update({
                    'symbol': f"TOKEN_{short_mint}",
                    'name': f"Token {short_mint}",
                })
                logger.info(f"🏷️ Token créé avec fallback: {token_metadata['symbol']} ({mint_address[:8]}...)")

            # Mettre en cache
            self.token_cache[mint_address] = {
                'data': token_metadata,
                'cached_at': datetime.now()
            }
            
            logger.info(f"🪙 Token analysé: {token_metadata['symbol']} ({mint_address[:8]}...)")
            return token_metadata
            
        except Exception as e:
            logger.error(f"❌ Erreur lors de la récupération des métadonnées pour {mint_address}: {e}")
            
            short_mint = mint_address[:6].upper()
            token_metadata.update({
                'symbol': f"TOKEN_{short_mint}",
                'name': f"Token {short_mint}",
            })

            # Mettre en cache même les échecs pour éviter de refaire la requête
            self.token_cache[mint_address] = {
                'data': token_metadata,
                'cached_at': datetime.now()
            }
            
            return token_metadata

    def analyze_token_transaction(self, tx_detail: Dict, wallet_address: str) -> Dict:
        """
        Analyse AMÉLIORÉE d'une transaction pour identifier les tokens, le type (buy/sell/transfer) et les montants
        Détecte mieux les petits achats de tokens avec de grosses quantités
        """
        analysis = {
            'transaction_type': 'other',
            'token_mint': None,
            'token_symbol': None,
            'token_name': None,
            'token_amount': 0,
            'price_per_token': 0,
            'sol_amount_change': tx_detail.get('amount', 0),
            'is_token_transaction': False,
            'token_metadata': None,
            'is_large_token_amount': False  # NOUVEAU: pour détecter les grosses quantités de tokens
        }
        
        try:
            # Récupérer les informations de la transaction
            if 'result' not in tx_detail or not tx_detail['result']:
                return analysis
                
            tx = tx_detail['result']
            meta = tx.get('meta', {})
            message = tx.get('transaction', {}).get('message', {})
            
            # Analyser les changements de balance des tokens (SPL)
            pre_token_balances = meta.get('preTokenBalances', [])
            post_token_balances = meta.get('postTokenBalances', [])
            
            # Créer des maps pour faciliter la comparaison
            pre_balances_map = {}
            post_balances_map = {}
            
            for balance in pre_token_balances:
                account_index = balance.get('accountIndex')
                mint = balance.get('mint')
                ui_amount = balance.get('uiTokenAmount', {}).get('uiAmount')
                amount = float(ui_amount) if ui_amount is not None else 0.0
                pre_balances_map[f"{account_index}_{mint}"] = {
                    'mint': mint,
                    'amount': amount,
                    'decimals': balance.get('uiTokenAmount', {}).get('decimals', 9),
                    'account_index': account_index
                }
            
            for balance in post_token_balances:
                account_index = balance.get('accountIndex')
                mint = balance.get('mint')
                ui_amount = balance.get('uiTokenAmount', {}).get('uiAmount')
                amount = float(ui_amount) if ui_amount is not None else 0.0
                post_balances_map[f"{account_index}_{mint}"] = {
                    'mint': mint,
                    'amount': amount,
                    'decimals': balance.get('uiTokenAmount', {}).get('decimals', 9),
                    'account_index': account_index
                }
            
            # Trouver l'index du wallet dans les comptes
            accounts = message.get('accountKeys', [])
            wallet_account_indices = []
            
            # AMÉLIORATION: Chercher toutes les occurrences du wallet (pas seulement la première)
            for i, account in enumerate(accounts):
                if account == wallet_address:
                    wallet_account_indices.append(i)
            
            if not wallet_account_indices:
                logger.debug(f"Wallet {wallet_address[:8]}... non trouvé dans les comptes de la transaction")
                return analysis
            
            # Analyser les changements de balance pour tous les comptes liés à ce wallet
            token_changes = []
            
            # Comparer les balances avant/après pour tous les comptes
            all_keys = set(pre_balances_map.keys()) | set(post_balances_map.keys())
            
            for key in all_keys:
                account_index = int(key.split('_')[0])
                mint = key.split('_')[1]
                
                # AMÉLIORATION: Regarder tous les comptes de tokens, pas seulement ceux du wallet principal
                # Car les tokens peuvent être dans des comptes associés (Associated Token Accounts)
                
                pre_balance = pre_balances_map.get(key, {'amount': 0, 'mint': mint, 'decimals': 9})
                post_balance = post_balances_map.get(key, {'amount': 0, 'mint': mint, 'decimals': 9})
                
                pre_amount = pre_balance.get('amount', 0) or 0
                post_amount = post_balance.get('amount', 0) or 0
                amount_change = post_amount - pre_amount
                
                # AMÉLIORATION: Seuil plus bas pour détecter les micro-changements
                if abs(amount_change) > 0.000000001:  # Seuil encore plus bas
                    token_changes.append({
                        'mint': mint,
                        'amount_change': amount_change,
                        'decimals': post_balance.get('decimals', 9),
                        'account_index': account_index,
                        'pre_amount': pre_amount,
                        'post_amount': post_amount
                    })
                    
                    logger.debug(f"🔍 Changement token détecté: {mint[:8]}... "
                            f"Change: {amount_change:,.6f} (de {pre_amount:,.6f} à {post_amount:,.6f})")
            
            # Si on a des changements de tokens, analyser le type de transaction
            if token_changes:
                analysis['is_token_transaction'] = True
                
                # AMÉLIORATION: Prendre le changement avec la plus grosse valeur absolue OU la plus grosse quantité
                main_token_change = None
                
                # Priorité 1: Le plus gros changement en valeur absolue
                max_change = max(token_changes, key=lambda x: abs(x['amount_change']))
                
                # Priorité 2: Si plusieurs changements similaires, prendre celui avec la plus grosse quantité
                significant_changes = [tc for tc in token_changes if abs(tc['amount_change']) > abs(max_change['amount_change']) * 0.1]
                
                if len(significant_changes) > 1:
                    # Prendre celui avec la plus grosse quantité finale
                    main_token_change = max(significant_changes, key=lambda x: x['post_amount'])
                else:
                    main_token_change = max_change
                
                analysis['token_mint'] = main_token_change['mint']
                analysis['token_amount'] = abs(main_token_change['amount_change'])
                
                # NOUVEAU: Détecter les grosses quantités de tokens (même si valeur SOL faible)
                token_amount = analysis['token_amount']
                
                # Critères pour "grosse quantité" de tokens
                if (token_amount >= 100000 or  # Plus de 100k tokens
                    token_amount >= 1000 and main_token_change['decimals'] <= 6 or  # Plus de 1k pour tokens avec peu de décimales
                    token_amount >= 10 and main_token_change['decimals'] <= 2):  # Plus de 10 pour tokens avec très peu de décimales
                    analysis['is_large_token_amount'] = True
                    logger.info(f"🔥 GROSSE QUANTITÉ de tokens détectée: {token_amount:,.2f} tokens")
                
                # Récupérer les métadonnées du token
                try:
                    token_metadata = self.get_token_metadata(main_token_change['mint'])
                    analysis['token_metadata'] = token_metadata
                    analysis['token_symbol'] = token_metadata['symbol']
                    analysis['token_name'] = token_metadata['name']
                except Exception as e:
                    logger.warning(f"Erreur métadonnées token {main_token_change['mint']}: {e}")
                    analysis['token_symbol'] = 'UNKNOWN'
                    analysis['token_name'] = 'Unknown Token'
                
                # AMÉLIORATION: Logique de détection du type de transaction plus précise
                sol_change = analysis['sol_amount_change']
                token_change = main_token_change['amount_change']
                
                # Seuils plus sensibles pour détecter les achats/ventes
                SOL_CHANGE_THRESHOLD = 0.001  # 0.001 SOL minimum
                
                logger.debug(f"🔍 Analyse transaction: SOL change = {sol_change:.6f}, Token change = {token_change:,.6f}")
                
                if token_change > 0:  # Augmentation de tokens
                    if sol_change < -SOL_CHANGE_THRESHOLD:
                        # Tokens augmentent, SOL diminue significativement = ACHAT CLAIR
                        analysis['transaction_type'] = 'buy'
                        analysis['price_per_token'] = abs(sol_change) / analysis['token_amount'] if analysis['token_amount'] > 0 else 0
                        logger.info(f"✅ ACHAT détecté: +{analysis['token_amount']:,.4f} {analysis['token_symbol']} pour {abs(sol_change):.6f} SOL")
                        
                    elif abs(sol_change) <= SOL_CHANGE_THRESHOLD:
                        # Tokens augmentent, SOL ne change pas beaucoup = POSSIBLEMENT UN ACHAT avec frais inclus
                        # Vérifier s'il y a des frais de transaction significatifs
                        fee = meta.get('fee', 0) / 1e9  # Convertir en SOL
                        
                        if fee > 0.001:  # Si frais > 0.001 SOL
                            analysis['transaction_type'] = 'buy'
                            # Estimer le prix basé sur les frais (approximation)
                            analysis['price_per_token'] = fee / analysis['token_amount'] if analysis['token_amount'] > 0 else 0
                            logger.info(f"✅ ACHAT détecté (via frais): +{analysis['token_amount']:,.4f} {analysis['token_symbol']} (frais: {fee:.6f} SOL)")
                        else:
                            # Probablement un transfert entrant ou airdrop
                            analysis['transaction_type'] = 'transfer'
                            logger.info(f"🔄 TRANSFERT/AIRDROP: +{analysis['token_amount']:,.4f} {analysis['token_symbol']}")
                    else:
                        # Tokens et SOL augmentent = transfert entrant étrange ou swap complexe
                        analysis['transaction_type'] = 'transfer'
                        
                elif token_change < 0:  # Diminution de tokens
                    if sol_change > SOL_CHANGE_THRESHOLD:
                        # Tokens diminuent, SOL augmente = VENTE CLAIRE
                        analysis['transaction_type'] = 'sell'
                        analysis['price_per_token'] = abs(sol_change) / analysis['token_amount'] if analysis['token_amount'] > 0 else 0
                        logger.info(f"✅ VENTE détectée: -{analysis['token_amount']:,.4f} {analysis['token_symbol']} pour +{sol_change:.6f} SOL")
                        
                    elif abs(sol_change) <= SOL_CHANGE_THRESHOLD:
                        # Tokens diminuent, SOL ne change pas beaucoup = transfert sortant
                        analysis['transaction_type'] = 'transfer'
                        logger.info(f"🔄 TRANSFERT sortant: -{analysis['token_amount']:,.4f} {analysis['token_symbol']}")
                    else:
                        # Tokens et SOL diminuent = possiblement un swap ou transfert avec frais
                        analysis['transaction_type'] = 'transfer'
                
                # Log final de l'analyse
                logger.info(f"🎯 Transaction {analysis['transaction_type'].upper()}: "
                        f"{analysis['token_amount']:,.4f} {analysis['token_symbol']} "
                        f"(SOL change: {sol_change:+.6f}) "
                        f"{'🔥 GROSSE QUANTITÉ' if analysis['is_large_token_amount'] else ''}")
                        
            else:
                # Pas de changement de tokens détecté, analyser comme transaction SOL
                if abs(analysis['sol_amount_change']) > 0.001:
                    analysis['transaction_type'] = 'sol_transfer'
                    analysis['token_symbol'] = 'SOL'
                    analysis['token_name'] = 'Solana'
                    analysis['token_amount'] = abs(analysis['sol_amount_change'])
                    
                    # Même les transferts SOL peuvent être "gros"
                    if analysis['token_amount'] >= 1.0:  # Plus de 1 SOL
                        analysis['is_large_token_amount'] = True
            
            return analysis

        except Exception as e:
            logger.error(f"❌ Erreur lors de l'analyse de la transaction: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return analysis

    def init_database(self):
        """Initialise la base de données SQLite"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        # Table des transactions
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signature TEXT UNIQUE NOT NULL,
                wallet_address TEXT,
                slot INTEGER,
                block_time INTEGER,
                amount REAL,
                token_mint TEXT,
                token_symbol TEXT,
                token_name TEXT,
                transaction_type TEXT,
                token_amount REAL,
                price_per_token REAL,
                fee REAL,
                status TEXT,
                is_token_transaction BOOLEAN DEFAULT 0,
                is_large_token_amount BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        self.update_database_schema(cursor)

        # Table des tokens
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tokens (
                address TEXT PRIMARY KEY,
                symbol TEXT,
                name TEXT,
                decimals INTEGER,
                price_usd REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Table des statistiques du wallet
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS wallet_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT,
                balance_sol REAL,
                total_transactions INTEGER,
                total_volume REAL,
                pnl REAL,
                largest_transaction REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS token_summary_cache (
            token_mint TEXT PRIMARY KEY,
            wallet_address TEXT,
            symbol TEXT,
            name TEXT,
            total_buys INTEGER DEFAULT 0,
            total_sells INTEGER DEFAULT 0,
            total_bought_amount REAL DEFAULT 0,
            total_sold_amount REAL DEFAULT 0,
            total_sol_spent REAL DEFAULT 0,
            total_sol_received REAL DEFAULT 0,
            avg_buy_price REAL DEFAULT 0,
            avg_sell_price REAL DEFAULT 0,
            net_position REAL DEFAULT 0,
            estimated_pnl REAL DEFAULT 0,
            first_transaction_time INTEGER,
            last_transaction_time INTEGER,
            unique_wallets TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
        
        conn.commit()
        conn.close()
        logger.info("✅ Base de données initialisée")
    
    

    def update_database_schema(self, cursor):
        """
        Met à jour la structure de la base de données avec le nouveau champ
        """
        # Liste des colonnes à ajouter si elles n'existent pas
        columns_to_add = [
            ('wallet_address', 'TEXT'),
            ('token_mint', 'TEXT'),
            ('token_symbol', 'TEXT'),
            ('token_name', 'TEXT'),
            ('transaction_type', 'TEXT'),
            ('token_amount', 'REAL'),
            ('price_per_token', 'REAL'),
            ('is_token_transaction', 'BOOLEAN DEFAULT 0'),
            ('is_large_token_amount', 'BOOLEAN DEFAULT 0')  # NOUVEAU
        ]
        
        # Récupérer la structure actuelle de la table
        cursor.execute("PRAGMA table_info(transactions)")
        existing_columns = [row[1] for row in cursor.fetchall()]
        
        # Ajouter les colonnes manquantes
        for column_name, column_type in columns_to_add:
            if column_name not in existing_columns:
                try:
                    cursor.execute(f'ALTER TABLE transactions ADD COLUMN {column_name} {column_type}')
                    logger.info(f"✅ Colonne '{column_name}' ajoutée à la table transactions")
                except sqlite3.OperationalError as e:
                    logger.warning(f"⚠️ Impossible d'ajouter la colonne '{column_name}': {e}")


    def get_solana_rpc_data(self, method: str, params: List) -> Optional[Dict]:
        """Effectue un appel RPC vers Solana avec gestion des erreurs et fallbacks"""
        global CURRENT_RPC_INDEX
        
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params
        }
        
        for attempt in range(MAX_RETRIES):
            current_endpoint = RPC_ENDPOINTS[CURRENT_RPC_INDEX]
            
            try:
                if attempt == 0:  # Log seulement la première tentative pour éviter le spam
                    logger.debug(f"Appel RPC: {method} sur {current_endpoint}")
                
                # Headers optimisés pour QuickNode
                headers = Config.get_rpc_headers()
                
                response = requests.post(
                    current_endpoint, 
                    json=payload, 
                    timeout=15,
                    headers=headers
                )
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:
                    logger.warning(f"Rate limit atteint sur {current_endpoint}")
                    # Basculer vers le prochain endpoint
                    CURRENT_RPC_INDEX = (CURRENT_RPC_INDEX + 1) % len(RPC_ENDPOINTS)
                    if attempt < MAX_RETRIES - 1:
                        logger.info(f"Basculement vers {RPC_ENDPOINTS[CURRENT_RPC_INDEX]}")
                        time.sleep(RETRY_DELAY * (attempt + 1))  # Délai progressif
                        continue
                else:
                    response.raise_for_status()
                    
            except requests.exceptions.Timeout:
                logger.error(f"Timeout sur {current_endpoint}")
                CURRENT_RPC_INDEX = (CURRENT_RPC_INDEX + 1) % len(RPC_ENDPOINTS)
            except requests.exceptions.ConnectionError:
                logger.error(f"Erreur de connexion sur {current_endpoint}")
                CURRENT_RPC_INDEX = (CURRENT_RPC_INDEX + 1) % len(RPC_ENDPOINTS)
            except requests.RequestException as e:
                logger.error(f"Erreur RPC sur {current_endpoint}: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                
        logger.error("❌ Tous les endpoints RPC ont échoué")
        return None
    
    def get_wallet_balance(self) -> float:
        """Récupère le solde SOL du wallet"""
        result = self.get_solana_rpc_data("getBalance", [self.wallet_address])
        if result and "result" in result:
            return result["result"]["value"] / 1e9  # Conversion de lamports en SOL
        return 0.0
    
    def get_transactions(self, limit: int = None) -> List[Dict]:
        """Récupère les transactions récentes du wallet avec gestion intelligente"""
        if limit is None:
            limit = Config.DEFAULT_TRANSACTION_LIMIT
        
        # Utiliser la limite configurée pour QuickNode
        safe_limit = min(limit, Config.DEFAULT_TRANSACTION_LIMIT)
        
        result = self.get_solana_rpc_data(
            "getSignaturesForAddress",
            [self.wallet_address, {"limit": safe_limit}]
        )
        
        if not result or "result" not in result:
            logger.warning("Aucune signature de transaction récupérée")
            return []
        
        transactions = []
        signatures = result["result"]
        
        # Traiter les transactions avec pause optimisée pour QuickNode
        for i, tx_info in enumerate(signatures):
            if i > 0:
                time.sleep(Config.PAUSE_BETWEEN_TX_DETAILS)  # Pause très courte avec QuickNode
                
            tx_detail = self.get_transaction_details(tx_info["signature"])
            if tx_detail:
                transactions.append(tx_detail)
        
        logger.info(f"✅ Récupéré {len(transactions)} transactions sur {len(signatures)} signatures (QuickNode API)")
        return transactions
    
    def get_transaction_details(self, signature: str) -> Optional[Dict]:
        """Récupère les détails d'une transaction"""
        result = self.get_solana_rpc_data(
            "getTransaction",
            [signature, {"encoding": "json", "maxSupportedTransactionVersion": 0}]
        )
        
        if not result or "result" not in result or not result["result"]:
            return None
        
        tx = result["result"]
        meta = tx.get("meta", {})
        
        # Analyse des changements de balance
        pre_balances = meta.get("preBalances", [])
        post_balances = meta.get("postBalances", [])
        accounts = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
        
        # Calcul du changement de balance pour notre wallet
        wallet_index = None
        for i, account in enumerate(accounts):
            if account == self.wallet_address:
                wallet_index = i
                break
        
        amount = 0
        if wallet_index is not None and wallet_index < len(pre_balances):
            amount = (post_balances[wallet_index] - pre_balances[wallet_index]) / 1e9
        
        token_analysis = self.analyze_token_transaction(result, self.wallet_address)

        transaction_detail = {
            "signature": signature,
            "slot": tx.get("slot", 0),
            "block_time": tx.get("blockTime"),
            "amount": amount,  # ton calcul existant
            "fee": meta.get("fee", 0) / 1e9,
            "status": "success" if meta.get("err") is None else "failed",
            "accounts": accounts,
            # Ajouter les infos tokens
            "transaction_type": token_analysis['transaction_type'],
            "token_mint": token_analysis['token_mint'],
            "token_symbol": token_analysis['token_symbol'],
            "token_name": token_analysis['token_name'],
            "token_amount": token_analysis['token_amount'],
            "price_per_token": token_analysis['price_per_token'],
            "is_token_transaction": token_analysis['is_token_transaction']
        }
    
        return transaction_detail
    
    def save_transaction(self, tx: Dict):
        """Sauvegarde une transaction dans la base de données"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO transactions 
                (signature, wallet_address, slot, block_time, amount, fee, status, 
                token_mint, token_symbol, token_name, transaction_type, 
                token_amount, price_per_token, is_token_transaction)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                tx["signature"],
                self.wallet_address,
                tx["slot"],
                tx["block_time"],
                tx["amount"],
                tx["fee"],
                tx["status"],
                tx.get("token_mint"),
                tx.get("token_symbol"),
                tx.get("token_name"),
                tx.get("transaction_type"),
                tx.get("token_amount"),
                tx.get("price_per_token"),
                tx.get("is_token_transaction", False)
            ))
            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la sauvegarde: {e}")
        finally:
            conn.close()
    
    def save_transaction_for_wallet(self, tx: Dict, wallet_address: str):
        """
        Version améliorée pour sauvegarder avec les nouvelles informations
        """
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO transactions 
                (signature, wallet_address, slot, block_time, amount, fee, status, 
                token_mint, token_symbol, token_name, transaction_type, 
                token_amount, price_per_token, is_token_transaction, is_large_token_amount)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                tx["signature"],
                wallet_address,
                tx["slot"],
                tx["block_time"],
                tx["amount"],
                tx["fee"],
                tx["status"],
                tx.get("token_mint"),
                tx.get("token_symbol"),
                tx.get("token_name"),
                tx.get("transaction_type"),
                tx.get("token_amount"),
                tx.get("price_per_token"),
                tx.get("is_token_transaction", False),
                tx.get("is_large_token_amount", False)
            ))
            conn.commit()
            
            # Log pour debug
            if tx.get("is_token_transaction"):
                source = tx.get("source", "signature")
                logger.info(f"💾 Sauvegarde [{source.upper()}]: {tx.get('transaction_type', 'unknown').upper()} "
                f"{tx.get('token_amount', 0):,.4f} {tx.get('token_symbol', 'UNKNOWN')} "
                f"({'🔥 GROSSE QUANTITÉ' if tx.get('is_large_token_amount') else 'normale'})")
                        
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la sauvegarde: {e}")
        finally:
            conn.close()

    def update_wallet_stats(self):
        """Met à jour les statistiques pour tous les wallets"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        for wallet_address in self.wallet_addresses:
            # Récupération des statistiques pour ce wallet
            balance = self.get_wallet_balance_for_address(wallet_address)
            
            cursor.execute("SELECT COUNT(*) FROM transactions WHERE wallet_address = ?", (wallet_address,))
            total_transactions = cursor.fetchone()[0]
            
            cursor.execute("SELECT SUM(ABS(amount)) FROM transactions WHERE amount != 0 AND wallet_address = ?", (wallet_address,))
            result = cursor.fetchone()
            total_volume = result[0] if result[0] else 0
            
            cursor.execute("SELECT SUM(amount) FROM transactions WHERE wallet_address = ?", (wallet_address,))
            result = cursor.fetchone()
            pnl = result[0] if result[0] else 0
            
            cursor.execute("SELECT MAX(ABS(amount)) FROM transactions WHERE wallet_address = ?", (wallet_address,))
            result = cursor.fetchone()
            largest_transaction = result[0] if result[0] else 0
            
            # Sauvegarde des stats pour ce wallet
            cursor.execute('''
                INSERT INTO wallet_stats 
                (balance_sol, total_transactions, total_volume, pnl, largest_transaction)
                VALUES (?, ?, ?, ?, ?)
            ''', (balance, total_transactions, total_volume, pnl, largest_transaction))
            
            logger.info(f"📊 Stats {wallet_address[:8]}... - Balance: {balance:.4f} SOL, Transactions: {total_transactions}, P&L: {pnl:.4f} SOL")
        
        conn.commit()
        conn.close()
    
    def monitor_loop(self):
        """Boucle principale de monitoring pour TOUS les wallets avec balance changes"""
        logger.info(f"🚀 Démarrage du monitoring pour {len(self.wallet_addresses)} wallets")
        
        consecutive_errors = 0
        max_consecutive_errors = Config.MAX_CONSECUTIVE_ERRORS
        
        while True:
            try:
                logger.info("--- 🔄 Cycle de monitoring HYBRIDE (signatures + balance changes) ---")
                
                total_new_transactions = 0
                
                # Boucler sur TOUS les wallets
                for wallet_address in self.wallet_addresses:
                    logger.info(f"📱 Traitement HYBRIDE du wallet: {wallet_address[:8]}...")
                    
                    # 1. MÉTHODE CLASSIQUE : Récupérer les transactions signées
                    logger.info(f"🔍 Scan des transactions signées pour {wallet_address[:8]}...")
                    signed_transactions = self.get_transactions_for_wallet(wallet_address)
                    new_signed = 0
                    
                    if signed_transactions:
                        for tx in signed_transactions:
                            if not self.signature_exists_in_db(tx["signature"]):
                                self.save_transaction_for_wallet(tx, wallet_address)
                                new_signed += 1
                    
                    # 2. NOUVELLE MÉTHODE : Récupérer les balance changes
                    logger.info(f"🔍 Scan des balance changes pour {wallet_address[:8]}...")
                    balance_changes = self.get_balance_changes_for_wallet(wallet_address)
                    new_balance_changes = 0
                    
                    if balance_changes:
                        for tx in balance_changes:
                            if not self.signature_exists_in_db(tx["signature"]):
                                self.save_transaction_for_wallet(tx, wallet_address)
                                new_balance_changes += 1
                    
                    total_new_signed = new_signed
                    total_new_balance_changes = new_balance_changes
                    total_new_transactions += total_new_signed + total_new_balance_changes
                    
                    logger.info(f"✅ Wallet {wallet_address[:8]}... - "
                            f"Signées: {total_new_signed}, Balance Changes: {total_new_balance_changes}")
                    
                    # Pause entre les wallets
                    time.sleep(2)
                
                # Mettre à jour les statistiques globales
                self.update_wallet_stats()
                
                if total_new_transactions > 0:
                    logger.info(f"🎉 TOTAL HYBRIDE: {total_new_transactions} nouvelles transactions sur tous les wallets")
                else:
                    logger.info("ℹ️ Aucune nouvelle transaction détectée (signatures + balance changes)")
                
                consecutive_errors = 0
                
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"❌ Erreur monitoring hybride (#{consecutive_errors}): {e}")
                
                if consecutive_errors >= max_consecutive_errors:
                    logger.critical(f"🚨 Trop d'erreurs ({consecutive_errors}). Pause longue...")
                    time.sleep(UPDATE_INTERVAL * 2)
                    consecutive_errors = 0
                else:
                    time.sleep(UPDATE_INTERVAL // 3)
            
            sleep_time = UPDATE_INTERVAL
            if consecutive_errors > 0:
                sleep_time *= (1 + consecutive_errors * 0.2)
            
            logger.info(f"⏱️ Prochaine vérification HYBRIDE dans {sleep_time:.0f} secondes")
            time.sleep(sleep_time)

    def get_transactions_for_wallet(self, wallet_address: str, limit: int = None) -> List[Dict]:
        """Récupère les transactions pour UN wallet spécifique"""
        if limit is None:
            limit = Config.DEFAULT_TRANSACTION_LIMIT
        
        safe_limit = min(limit, Config.DEFAULT_TRANSACTION_LIMIT)
        
        result = self.get_solana_rpc_data(
            "getSignaturesForAddress",
            [wallet_address, {"limit": safe_limit}]
        )
        
        if not result or "result" not in result:
            logger.warning(f"Aucune signature pour {wallet_address[:8]}...")
            return []
        
        transactions = []
        signatures = result["result"]
        
        for i, tx_info in enumerate(signatures):
            if i > 0:
                time.sleep(Config.PAUSE_BETWEEN_TX_DETAILS)
                
            tx_detail = self.get_transaction_details_for_wallet(tx_info["signature"], wallet_address)
            if tx_detail:
                transactions.append(tx_detail)
        
        logger.info(f"✅ Récupéré {len(transactions)} transactions pour {wallet_address[:8]}...")
        return transactions

    def get_transaction_details_for_wallet(self, signature: str, wallet_address: str) -> Optional[Dict]:
        """
        Version améliorée qui détecte mieux les achats de tokens
        """
        result = self.get_solana_rpc_data(
            "getTransaction",
            [signature, {"encoding": "json", "maxSupportedTransactionVersion": 0}]
        )
        
        if not result or "result" not in result or not result["result"]:
            return None
        
        tx = result["result"]
        meta = tx.get("meta", {})
        
        # Calcul du changement de balance SOL pour CE wallet
        pre_balances = meta.get("preBalances", [])
        post_balances = meta.get("postBalances", [])
        accounts = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
        
        wallet_index = None
        for i, account in enumerate(accounts):
            if account == wallet_address:
                wallet_index = i
                break
        
        amount = 0
        if wallet_index is not None and wallet_index < len(pre_balances):
            pre_balance = pre_balances[wallet_index] if pre_balances[wallet_index] is not None else 0
            post_balance = post_balances[wallet_index] if post_balances[wallet_index] is not None else 0
            amount = (post_balance - pre_balance) / 1e9
        
        # Analyser les tokens avec la nouvelle logique améliorée
        try:
            token_analysis = self.analyze_token_transaction(result, wallet_address)
        except Exception as e:
            logger.error(f"Erreur lors de l'analyse des tokens pour {signature}: {e}")
            token_analysis = {
                'transaction_type': 'other',
                'token_mint': None,
                'token_symbol': None,
                'token_name': None,
                'token_amount': 0,
                'price_per_token': 0,
                'is_token_transaction': False,
                'is_large_token_amount': False
            }

        transaction_detail = {
            "signature": signature,
            "wallet_address": wallet_address,
            "slot": tx.get("slot", 0),
            "block_time": tx.get("blockTime"),
            "amount": amount,
            "fee": meta.get("fee", 0) / 1e9,
            "status": "success" if meta.get("err") is None else "failed",
            "accounts": accounts,
            "transaction_type": token_analysis['transaction_type'],
            "token_mint": token_analysis['token_mint'],
            "token_symbol": token_analysis['token_symbol'],
            "token_name": token_analysis['token_name'],
            "token_amount": token_analysis['token_amount'],
            "price_per_token": token_analysis['price_per_token'],
            "is_token_transaction": token_analysis['is_token_transaction'],
            "is_large_token_amount": token_analysis['is_large_token_amount']  # NOUVEAU
        }

        return transaction_detail

    def get_wallet_balance_for_address(self, wallet_address: str) -> float:
        """Récupère le solde SOL pour un wallet spécifique"""
        result = self.get_solana_rpc_data("getBalance", [wallet_address])
        if result and "result" in result:
            return result["result"]["value"] / 1e9
        return 0.0

# API Flask pour le dashboard
app = Flask(__name__)
CORS(app)

@app.route('/')
def dashboard():
    return render_template('dashboard.html')


@app.route('/api/debug/missing-transaction/<signature>')
def debug_missing_transaction(signature):
    """Vérifier si une transaction spécifique existe en DB"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Chercher cette transaction précise
    cursor.execute('''
        SELECT signature, wallet_address, token_symbol, token_amount, 
               transaction_type, block_time, is_token_transaction,
               created_at, token_mint
        FROM transactions 
        WHERE signature = ?
    ''', (signature,))
    
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return jsonify({
            "found": True,
            "signature": result[0],
            "wallet_address": result[1],
            "token_symbol": result[2],
            "token_amount": result[3],
            "transaction_type": result[4],
            "block_time": result[5],
            "is_token_transaction": bool(result[6]),
            "created_at": result[7],
            "token_mint": result[8]
        })
    else:
        return jsonify({"found": False, "signature": signature})

@app.route('/api/debug/recent-by-wallet/<wallet_address>')
def debug_recent_by_wallet(wallet_address):
    """Vérifier les transactions récentes pour un wallet spécifique"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Récupérer les 20 dernières transactions pour ce wallet
    cursor.execute('''
        SELECT signature, token_symbol, token_amount, transaction_type, 
               block_time, is_token_transaction, created_at
        FROM transactions 
        WHERE wallet_address = ?
        ORDER BY block_time DESC 
        LIMIT 20
    ''', (wallet_address,))
    
    results = cursor.fetchall()
    conn.close()
    
    transactions = []
    for row in results:
        transactions.append({
            "signature": row[0][:10] + "...",
            "token_symbol": row[1],
            "token_amount": row[2],
            "transaction_type": row[3],
            "block_time": row[4],
            "is_token_transaction": bool(row[5]),
            "created_at": row[6],
            "age_minutes": (time.time() - row[4]) / 60 if row[4] else 0
        })
    
    return jsonify({
        "wallet_address": wallet_address,
        "total_transactions": len(transactions),
        "transactions": transactions
    })

@app.route('/api/debug/balance-changes-status')
def debug_balance_changes_status():
    """Vérifier le statut des balance changes récents"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Statistiques des transactions récentes (dernières 24h)
    yesterday = int(time.time()) - 86400
    
    cursor.execute('''
        SELECT 
            COUNT(*) as total,
            COUNT(CASE WHEN is_token_transaction = 1 THEN 1 END) as token_transactions,
            COUNT(CASE WHEN transaction_type = 'buy' THEN 1 END) as buys,
            COUNT(CASE WHEN transaction_type = 'sell' THEN 1 END) as sells,
            COUNT(CASE WHEN transaction_type = 'transfer' THEN 1 END) as transfers
        FROM transactions 
        WHERE block_time >= ?
    ''', (yesterday,))
    
    stats = cursor.fetchone()
    
    # Dernières transactions token
    cursor.execute('''
        SELECT signature, wallet_address, token_symbol, token_amount, 
               transaction_type, block_time
        FROM transactions 
        WHERE is_token_transaction = 1 AND block_time >= ?
        ORDER BY block_time DESC 
        LIMIT 10
    ''', (yesterday,))
    
    recent_tokens = cursor.fetchall()
    conn.close()
    
    return jsonify({
        "period": "Last 24 hours",
        "stats": {
            "total_transactions": stats[0],
            "token_transactions": stats[1],
            "buys": stats[2],
            "sells": stats[3],
            "transfers": stats[4]
        },
        "recent_token_transactions": [
            {
                "signature": tx[0][:10] + "...",
                "wallet": tx[1][:8] + "...",
                "token": tx[2],
                "amount": tx[3],
                "type": tx[4],
                "age_minutes": (time.time() - tx[5]) / 60 if tx[5] else 0
            }
            for tx in recent_tokens
        ]
    })


@app.route('/api/debug/force-refresh-wallet/<wallet_address>')
def force_refresh_wallet(wallet_address):
    """Force le refresh d'un wallet spécifique"""
    try:
        monitor = SolanaWalletMonitor([wallet_address], DB_NAME)
        
        # 1. Transactions signées
        signed_transactions = monitor.get_transactions_for_wallet(wallet_address, limit=10)
        new_signed = 0
        
        for tx in signed_transactions:
            if not monitor.signature_exists_in_db(tx["signature"]):
                monitor.save_transaction_for_wallet(tx, wallet_address)
                new_signed += 1
        
        # 2. Balance changes
        balance_changes = monitor.get_balance_changes_for_wallet(wallet_address, limit=30, time_window_hours=1)
        new_balance_changes = 0
        
        for tx in balance_changes:
            if not monitor.signature_exists_in_db(tx["signature"]):
                monitor.save_transaction_for_wallet(tx, wallet_address)
                new_balance_changes += 1
        
        return jsonify({
            "wallet_address": wallet_address,
            "refresh_result": {
                "new_signed_transactions": new_signed,
                "new_balance_changes": new_balance_changes,
                "total_new": new_signed + new_balance_changes
            }
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/debug/balance-changes')
def debug_balance_changes():
    """Route de debug pour vérifier les balance changes en DB"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Balance changes récents
    cursor.execute('''
        SELECT signature, wallet_address, token_symbol, token_amount, transaction_type, block_time
        FROM transactions 
        WHERE is_token_transaction = 1 
        ORDER BY block_time DESC 
        LIMIT 50
    ''')
    
    balance_changes = cursor.fetchall()
    conn.close()
    
    result = [
        {
            "signature": bc[0][:10] + "...",
            "wallet": bc[1][:8] + "...",
            "token": bc[2],
            "amount": bc[3],
            "type": bc[4],
            "time": bc[5]
        }
        for bc in balance_changes
    ]
    
    return jsonify({
        "total_balance_changes": len(result),
        "balance_changes": result
    })


@app.route('/api/token-summary')
def get_token_summary():
    """API pour récupérer le résumé des tokens avec statistiques de trading"""

    # Récupération et conversion sécurisée de TOUS les paramètres
    wallet_filter = request.args.get('wallet', 'all')


    # Conversion sécurisée des paramètres
    try:
        period_days = int(request.args.get('period', '30'))
    except (ValueError, TypeError):
        period_days = 30
    
    try:
        min_transactions = int(request.args.get('min_transactions', '2'))
    except (ValueError, TypeError):
        min_transactions = 2
    
    try:
        min_value = float(request.args.get('min_value', '0.1'))
    except (ValueError, TypeError):
        min_value = 0.1
    
    sort_by = request.args.get('sort_by', 'total_value')
    
    print(f"DEBUG - Paramètres reçus: period_days={period_days} ({type(period_days)}), min_value={min_value} ({type(min_value)})")
    
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Calculer le timestamp de début selon la période
        period_start = None
        if period_days > 0:
            period_start = int(time.time()) - (period_days * 24 * 60 * 60)
        
        # Requête SQL de base avec CAST pour forcer les types
        base_query = '''
        SELECT 
            token_mint,
            token_symbol,
            token_name,
            COUNT(CASE WHEN transaction_type = 'buy' THEN 1 END) as total_buys,
            COALESCE(SUM(CASE WHEN transaction_type = 'buy' THEN CAST(token_amount AS REAL) END), 0) as total_bought_amount,
            COALESCE(SUM(CASE WHEN transaction_type = 'buy' THEN ABS(CAST(amount AS REAL)) END), 0) as total_sol_spent,
            COALESCE(AVG(CASE WHEN transaction_type = 'buy' AND CAST(price_per_token AS REAL) > 0 THEN CAST(price_per_token AS REAL) END), 0) as avg_buy_price,
            COUNT(CASE WHEN transaction_type = 'sell' THEN 1 END) as total_sells,
            COALESCE(SUM(CASE WHEN transaction_type = 'sell' THEN CAST(token_amount AS REAL) END), 0) as total_sold_amount,
            COALESCE(SUM(CASE WHEN transaction_type = 'sell' THEN ABS(CAST(amount AS REAL)) END), 0) as total_sol_received,
            COALESCE(AVG(CASE WHEN transaction_type = 'sell' AND CAST(price_per_token AS REAL) > 0 THEN CAST(price_per_token AS REAL) END), 0) as avg_sell_price,
            COUNT(*) as total_transactions,
            COALESCE(SUM(ABS(CAST(amount AS REAL))), 0) as total_value,
            MIN(CAST(block_time AS INTEGER)) as first_transaction_time,
            MAX(CAST(block_time AS INTEGER)) as last_transaction_time,
            COUNT(DISTINCT wallet_address) as unique_wallets,
            GROUP_CONCAT(DISTINCT wallet_address) as wallet_list
        FROM transactions 
        WHERE token_mint IS NOT NULL 
        AND token_mint != ''
        AND token_symbol IS NOT NULL
        AND token_symbol != ''
        '''
        
        params = []
        
        if wallet_filter != 'all':
            base_query += ' AND wallet_address = ?'
            params.append(wallet_filter)
            
        if period_start:
            base_query += ' AND CAST(block_time AS INTEGER) >= ?'
            params.append(period_start)
            
        if min_value > 0:
            base_query += ' AND ABS(CAST(amount AS REAL)) >= ?'
            params.append(min_value)
            
        base_query += '''
        GROUP BY token_mint, token_symbol, token_name
        HAVING COUNT(*) >= ?
        '''
        params.append(min_transactions)
        
        cursor.execute(base_query, params)
        raw_results = cursor.fetchall()
        
        # Traiter les résultats avec gestion d'erreurs
        token_summaries = []
        
        for row in raw_results:
            try:
                # Conversion sécurisée des valeurs
                total_bought = float(row[4]) if row[4] is not None else 0.0
                total_sold = float(row[8]) if row[8] is not None else 0.0
                net_position = total_bought - total_sold
                
                sol_spent = float(row[5]) if row[5] is not None else 0.0
                sol_received = float(row[9]) if row[9] is not None else 0.0
                net_sol = sol_received - sol_spent
                
                estimated_pnl = 0.0
                pnl_percentage = 0.0
                if sol_spent > 0:
                    estimated_pnl = net_sol
                    pnl_percentage = (estimated_pnl / sol_spent) * 100
                    
                status = "neutral"
                if net_position > 0:
                    status = "long"
                elif net_position < 0:
                    status = "short"
                    
                # Vérification sécurisée du timestamp
                last_transaction_time = int(row[14]) if row[14] is not None else 0
                is_recent = (time.time() - last_transaction_time) < 86400 if last_transaction_time > 0 else False
                
                hotness_score = 0
                if is_recent:
                    hotness_score += 50
                total_tx = int(row[11]) if row[11] is not None else 0
                if total_tx > 5:
                    hotness_score += 20
                if abs(pnl_percentage) > 20:
                    hotness_score += 30
                    
                wallet_addresses = (row[16] or '').split(',') if row[16] else []
                
                token_summary = {
                    'token_mint': row[0] or '',
                    'symbol': row[1] or 'UNKNOWN',
                    'name': row[2] or 'Unknown Token',
                    'trading_stats': {
                        'total_buys': int(row[3]) if row[3] is not None else 0,
                        'total_sells': int(row[7]) if row[7] is not None else 0,
                        'total_transactions': total_tx,
                        'total_bought_amount': total_bought,
                        'total_sold_amount': total_sold,
                        'net_position': net_position,
                        'total_sol_spent': sol_spent,
                        'total_sol_received': sol_received,
                        'net_sol': net_sol,
                        'avg_buy_price': float(row[6]) if row[6] is not None else 0.0,
                        'avg_sell_price': float(row[10]) if row[10] is not None else 0.0,
                        'total_value': float(row[12]) if row[12] is not None else 0.0,
                        'unique_wallets': int(row[15]) if row[15] is not None else 0,
                        'wallet_addresses': wallet_addresses[:3],
                        'all_wallets': wallet_addresses
                    },
                    'performance': {
                        'estimated_pnl_sol': round(estimated_pnl, 4),
                        'pnl_percentage': round(pnl_percentage, 2),
                        'status': status,
                        'is_profitable': estimated_pnl > 0
                    },
                    'timing': {
                        'first_transaction': int(row[13]) if row[13] is not None else 0,
                        'last_transaction': last_transaction_time,
                        'is_recent_activity': is_recent,
                        'days_active': max(1, (last_transaction_time - int(row[13])) // 86400) if row[13] and last_transaction_time > 0 else 1
                    },
                    'metadata': {
                        'hotness_score': hotness_score,
                        'is_hot': hotness_score >= 70,
                        'position_size': 'large' if abs(net_position) > 100000 else 'medium' if abs(net_position) > 10000 else 'small'
                    },
                    'links': {
                        'dexscreener': f"https://dexscreener.com/solana/{row[0]}",
                        'jupiter': f"https://jup.ag/swap/SOL-{row[0]}",
                        'pump_fun': f"https://pump.fun/{row[0]}",
                        'solscan': f"https://solscan.io/token/{row[0]}",
                        'birdeye': f"https://birdeye.so/token/{row[0]}?chain=solana"
                    }
                }
                
                token_summaries.append(token_summary)
                
            except (ValueError, TypeError) as e:
                logger.warning(f"Erreur lors du traitement du token {row[0]}: {e}")
                continue
        
        # Trier les résultats
        sort_key_mapping = {
            'total_value': lambda x: x['trading_stats']['total_value'],
            'last_activity': lambda x: x['timing']['last_transaction'],
            'pnl': lambda x: x['performance']['estimated_pnl_sol'],
            'net_position': lambda x: abs(x['trading_stats']['net_position']),
            'hotness': lambda x: x['metadata']['hotness_score'],
            'transactions': lambda x: x['trading_stats']['total_transactions']
        }
        
        if sort_by in sort_key_mapping:
            token_summaries.sort(key=sort_key_mapping[sort_by], reverse=True)
        
        # Statistiques globales
        total_tokens = len(token_summaries)
        total_profitable = sum(1 for t in token_summaries if t['performance']['is_profitable'])
        total_pnl = sum(t['performance']['estimated_pnl_sol'] for t in token_summaries)
        hot_tokens_count = sum(1 for t in token_summaries if t['metadata']['is_hot'])
        
        result = {
            'summary': {
                'total_tokens': total_tokens,
                'profitable_tokens': total_profitable,
                'loss_tokens': total_tokens - total_profitable,
                'profit_ratio': round((total_profitable / total_tokens * 100), 1) if total_tokens > 0 else 0,
                'total_estimated_pnl': round(total_pnl, 4),
                'hot_tokens_count': hot_tokens_count,
                'period_days': period_days,
                'wallet_filter': wallet_filter,
                'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            },
            'tokens': token_summaries
        }
        
        conn.close()
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du token summary: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            'error': str(e),
            'summary': {'total_tokens': 0},
            'tokens': []
        }), 500


@app.route('/api/token-details/<token_mint>')
def get_token_details(token_mint):
    """Détails complets d'un token spécifique"""
    wallet_filter = request.args.get('wallet', 'all')
    
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        query = '''
        SELECT signature, wallet_address, block_time, amount, transaction_type, 
               token_amount, price_per_token, fee, status, token_symbol, token_name
        FROM transactions 
        WHERE token_mint = ? AND is_token_transaction = 1
        '''
        params = [token_mint]
        
        if wallet_filter != 'all':
            query += ' AND wallet_address = ?'
            params.append(wallet_filter)
            
        query += ' ORDER BY block_time DESC'
        
        cursor.execute(query, params)
        transactions = cursor.fetchall()
        
        formatted_transactions = []
        for tx in transactions:
            formatted_transactions.append({
                'signature': tx[0],
                'wallet_address': tx[1],
                'block_time': int(tx[2]),
                'amount_sol': float(tx[3]),
                'transaction_type': tx[4],
                'token_amount': float(tx[5]) if tx[5] else 0,
                'price_per_token': float(tx[6]) if tx[6] else 0,
                'fee': float(tx[7]) if tx[7] else 0,
                'status': tx[8],
                'token_symbol': tx[9],
                'token_name': tx[10],
                'date': datetime.fromtimestamp(tx[2]).strftime('%Y-%m-%d %H:%M:%S') if tx[2] else ''
            })
        
        conn.close()
        
        return jsonify({
            'token_mint': token_mint,
            'transactions': formatted_transactions,
            'total_transactions': len(formatted_transactions)
        })
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des détails du token {token_mint}: {e}")
        return jsonify({'error': str(e), 'transactions': []}), 500


@app.route('/api/stats')
def get_stats():
    """API pour récupérer les statistiques du wallet"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Dernières statistiques
    cursor.execute('''
        SELECT balance_sol, total_transactions, total_volume, pnl, largest_transaction, updated_at
        FROM wallet_stats ORDER BY updated_at DESC LIMIT 1
    ''')
    stats = cursor.fetchone()
    sol_usd, sol_eur = get_sol_price()
    # Transactions récentes
    cursor.execute('''
        SELECT signature, block_time, amount, fee, status
        FROM transactions ORDER BY block_time DESC LIMIT 10
    ''')
    recent_transactions = cursor.fetchall()
    
    # Distribution par type de transaction
    cursor.execute('''
        SELECT 
            CASE WHEN amount > 0 THEN 'Réception' ELSE 'Envoi' END as type,
            COUNT(*) as count,
            SUM(ABS(amount)) as volume
        FROM transactions WHERE amount != 0
        GROUP BY CASE WHEN amount > 0 THEN 'Réception' ELSE 'Envoi' END
    ''')
    transaction_distribution = cursor.fetchall()
    
    conn.close()
    
    result = {
        "wallet_address": WALLET_ADDRESS,
        "stats": {
            "balance_sol": stats[0] if stats else 0,
            "balance_usd": (stats[0] * sol_usd) if stats else 0,
            "balance_eur": (stats[0] * sol_eur) if stats else 0,
            "total_transactions": int(stats[1]) if stats else 0,  # Entier
            "total_volume": stats[2] if stats else 0,
            "total_volume_usd": (stats[2] * sol_usd) if stats else 0,
            "total_volume_eur": (stats[2] * sol_eur) if stats else 0,
            "pnl": stats[3] if stats else 0,
            "pnl_usd": (stats[3] * sol_usd) if stats else 0,
            "pnl_eur": (stats[3] * sol_eur) if stats else 0,
            "largest_transaction": stats[4] if stats else 0,
            "largest_transaction_usd": (stats[4] * sol_usd) if stats else 0,
            "largest_transaction_eur": (stats[4] * sol_eur) if stats else 0,
            "sol_price_usd": sol_usd,
            "sol_price_eur": sol_eur,
            "last_update": datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        },
        "recent_transactions": [
            {
                "signature": tx[0],
                "block_time": tx[1],
                "amount": tx[2],
                "fee": tx[3],
                "status": tx[4]
            }
            for tx in recent_transactions
        ],
        "transaction_distribution": [
            {
                "type": dist[0],
                "count": dist[1],
                "volume": dist[2]
            }
            for dist in transaction_distribution
        ]
    }
    
    return jsonify(result)

@app.route('/api/wallets')
def get_wallets():
    """Retourne la liste des wallets surveillés"""
    return jsonify({
        "wallets": Config.WALLET_ADDRESSES if hasattr(Config, 'WALLET_ADDRESSES') else [Config.WALLET_ADDRESS]
    })

@app.route('/api/stats/<wallet_address>')
def get_wallet_stats(wallet_address):
    """Stats pour un wallet spécifique"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Stats pour un wallet spécifique
    cursor.execute('''
        SELECT 
            COUNT(*) as total_transactions,
            SUM(ABS(amount)) as total_volume,
            SUM(amount) as pnl,
            MAX(ABS(amount)) as largest_transaction
        FROM transactions 
        WHERE wallet_address = ?
    ''', (wallet_address,))
    
    wallet_stats = cursor.fetchone()
    
    # Balance actuelle
    monitor = SolanaWalletMonitor(Config.WALLET_ADDRESSES, DB_NAME)
    balance = monitor.get_wallet_balance_for_address(wallet_address)
    
    sol_usd, sol_eur = get_sol_price()
    
    result = {
        "wallet_address": wallet_address,
        "stats": {
            "balance_sol": balance,
            "balance_usd": balance * sol_usd,
            "balance_eur": balance * sol_eur,
            "total_transactions": int(wallet_stats[0]) if wallet_stats[0] else 0,
            "total_volume": wallet_stats[1] if wallet_stats[1] else 0,
            "pnl": wallet_stats[2] if wallet_stats[2] else 0,
            "largest_transaction": wallet_stats[3] if wallet_stats[3] else 0,
            "sol_price_usd": sol_usd,
            "sol_price_eur": sol_eur,
            "last_update": datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        }
    }
    
    conn.close()
    return jsonify(result)

@app.route('/api/tokens/<wallet_address>')
def get_wallet_tokens(wallet_address):
    """Tokens détenus par un wallet avec leurs informations détaillées"""
    try:
        # Créer une instance du monitor pour accéder aux méthodes RPC
        monitor = SolanaWalletMonitor(Config.WALLET_ADDRESSES, DB_NAME)
        
        # 1. Récupérer les comptes de tokens SPL pour ce wallet
        token_accounts_result = monitor.get_solana_rpc_data(
            "getTokenAccountsByOwner",
            [
                wallet_address,
                {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},  # SPL Token Program
                {"encoding": "jsonParsed"}
            ]
        )
        
        if not token_accounts_result or "result" not in token_accounts_result:
            return jsonify({
                "wallet_address": wallet_address,
                "tokens": [],
                "error": "Impossible de récupérer les comptes de tokens"
            })
        
        token_accounts = token_accounts_result["result"]["value"]
        tokens_info = []
        
        # 2. Traiter chaque compte de token
        for account in token_accounts:
            try:
                account_data = account["account"]["data"]["parsed"]["info"]
                token_amount = float(account_data["tokenAmount"]["uiAmount"] or 0)
                
                # Ignorer les tokens avec un solde de 0
                if token_amount <= 0:
                    continue
                
                mint_address = account_data["mint"]
                decimals = int(account_data["tokenAmount"]["decimals"])
                
                # 3. Récupérer les métadonnées du token
                token_metadata = monitor.get_token_metadata(mint_address)
                
                # 4. Récupérer les statistiques de trading depuis la DB
                conn = sqlite3.connect(DB_NAME)
                cursor = conn.cursor()
                
                # Stats de trading pour ce token et ce wallet
                cursor.execute('''
                    SELECT 
                        COUNT(*) as total_transactions,
                        SUM(CASE WHEN transaction_type = 'buy' THEN token_amount ELSE 0 END) as total_bought,
                        SUM(CASE WHEN transaction_type = 'sell' THEN token_amount ELSE 0 END) as total_sold,
                        AVG(CASE WHEN transaction_type = 'buy' AND price_per_token > 0 THEN price_per_token ELSE NULL END) as avg_buy_price,
                        AVG(CASE WHEN transaction_type = 'sell' AND price_per_token > 0 THEN price_per_token ELSE NULL END) as avg_sell_price,
                        MAX(block_time) as last_transaction_time
                    FROM transactions 
                    WHERE wallet_address = ? AND token_mint = ? AND transaction_type IN ('buy', 'sell')
                ''', (wallet_address, mint_address))
                
                trading_stats = cursor.fetchone()
                conn.close()
                
                # 5. Calculer les métriques
                total_bought = trading_stats[1] or 0
                total_sold = trading_stats[2] or 0
                avg_buy_price = trading_stats[3] or 0
                avg_sell_price = trading_stats[4] or 0
                
                # Estimer la valeur en SOL (approximative)
                estimated_value_sol = 0
                if avg_buy_price > 0:
                    estimated_value_sol = token_amount * avg_buy_price
                
                # P&L approximatif
                pnl_sol = 0
                if avg_buy_price > 0 and total_bought > 0:
                    cost_basis = total_bought * avg_buy_price
                    current_value = token_amount * avg_buy_price  # Simplifié
                    pnl_sol = current_value - cost_basis
                
                # 6. Récupérer le prix actuel depuis DexScreener (optionnel)
                current_price_usd = 0
                try:
                    price_response = requests.get(
                        f'https://api.dexscreener.com/latest/dex/tokens/{mint_address}',
                        timeout=3
                    )
                    if price_response.status_code == 200:
                        price_data = price_response.json()
                        if price_data.get('pairs') and len(price_data['pairs']) > 0:
                            current_price_usd = float(price_data['pairs'][0].get('priceUsd', 0))
                except:
                    pass  # Ignore errors
                
                token_info = {
                    "mint": mint_address,
                    "symbol": token_metadata['symbol'],
                    "name": token_metadata['name'],
                    "decimals": decimals,
                    "logo_uri": token_metadata.get('logo_uri'),
                    "balance": token_amount,
                    "balance_raw": account_data["tokenAmount"]["amount"],
                    "account_address": account["pubkey"],
                    
                    # Trading stats
                    "trading_stats": {
                        "total_transactions": int(trading_stats[0]) if trading_stats[0] else 0,
                        "total_bought": total_bought,
                        "total_sold": total_sold,
                        "net_position": total_bought - total_sold,
                        "avg_buy_price_sol": avg_buy_price,
                        "avg_sell_price_sol": avg_sell_price,
                        "last_transaction_time": trading_stats[5]
                    },
                    
                    # Valuation
                    "valuation": {
                        "estimated_value_sol": estimated_value_sol,
                        "pnl_sol": pnl_sol,
                        "current_price_usd": current_price_usd,
                        "estimated_value_usd": token_amount * current_price_usd if current_price_usd > 0 else 0
                    },
                    
                    # Links
                    "links": {
                        "solscan": f"https://solscan.io/token/{mint_address}",
                        "pump_fun": f"https://pump.fun/{mint_address}",
                        "dexscreener": f"https://dexscreener.com/solana/{mint_address}",
                        "jupiter": f"https://jup.ag/swap/{mint_address}-SOL"
                    }
                }
                
                tokens_info.append(token_info)
                
            except Exception as e:
                logger.error(f"Erreur lors du traitement du token {account.get('account', {}).get('data', {}).get('parsed', {}).get('info', {}).get('mint', 'UNKNOWN')}: {e}")
                continue
        
        # 7. Trier par valeur estimée décroissante
        tokens_info.sort(key=lambda x: x['valuation']['estimated_value_sol'], reverse=True)
        
        # 8. Calculer les totaux
        total_estimated_value_sol = sum(token['valuation']['estimated_value_sol'] for token in tokens_info)
        total_estimated_value_usd = sum(token['valuation']['estimated_value_usd'] for token in tokens_info)
        total_pnl_sol = sum(token['valuation']['pnl_sol'] for token in tokens_info)
        
        result = {
            "wallet_address": wallet_address,
            "summary": {
                "total_tokens": len(tokens_info),
                "total_estimated_value_sol": total_estimated_value_sol,
                "total_estimated_value_usd": total_estimated_value_usd,
                "total_pnl_sol": total_pnl_sol,
                "updated_at": datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            },
            "tokens": tokens_info
        }
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des tokens pour {wallet_address}: {e}")
        return jsonify({
            "wallet_address": wallet_address,
            "error": str(e),
            "tokens": []
        }), 500

@app.route('/api/transactions')
def get_transactions_api():
    """API pour récupérer les transactions avec filtres"""
    limit = request.args.get('limit', Config.DEFAULT_TRANSACTION_LIMIT, type=int)
    min_amount = request.args.get('min_amount', 0, type=float)
    wallet = request.args.get('wallet', 'all')
    transaction_type = request.args.get('type', 'all')
    
    # Respecter les limites configurées
    limit = min(limit, getattr(Config, 'MAX_TRANSACTION_LIMIT', 100))
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Construire la requête avec filtres
    query = '''
        SELECT signature, block_time, amount, fee, status, created_at,
               token_mint, token_symbol, token_name, transaction_type,
               token_amount, price_per_token, is_token_transaction, wallet_address
        FROM transactions 
        WHERE 1=1
    '''
    params = []
    
    if min_amount > 0:
        query += ' AND (ABS(amount) >= ? OR (is_token_transaction = 1 AND token_amount >= ?))'
        params.extend([min_amount, min_amount])

    if wallet != 'all':
        query += ' AND wallet_address = ?'
        params.append(wallet)
    
    if transaction_type != 'all':
        query += ' AND transaction_type = ?'
        params.append(transaction_type)
    
    query += ' ORDER BY block_time DESC LIMIT ?'
    params.append(limit)
    
    cursor.execute(query, params)
    transactions = cursor.fetchall()
    conn.close()
    
    result = [
        {
            "signature": tx[0],
            "block_time": tx[1],
            "amount": tx[2],
            "fee": tx[3],
            "status": tx[4],
            "created_at": tx[5],
            "token_mint": tx[6],
            "token_symbol": tx[7],
            "token_name": tx[8],
            "transaction_type": tx[9],
            "token_amount": tx[10],
            "price_per_token": tx[11],
            "is_token_transaction": bool(tx[12]),
            "wallet_address": tx[13]
        }
        for tx in transactions
    ]
    
    logger.info(f"📊 API transactions: {len(result)} transactions retournées "
                f"(wallet: {wallet}, type: {transaction_type}, min: {min_amount})")

    return jsonify(result)

def get_sol_price():
        """Récupère le prix actuel du SOL en USD et EUR"""
        try:
            response = requests.get('https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd,eur', timeout=5)
            if response.status_code == 200:
                data = response.json()
                return data['solana']['usd'], data['solana']['eur']
        except:
            pass
        return 100, 85  # Prix par défaut si API échoue

def run_monitor():
    """Lance le monitoring en arrière-plan"""
    monitor = SolanaWalletMonitor(Config.WALLET_ADDRESSES, DB_NAME)
    monitor.monitor_loop()

if __name__ == "__main__":
    # Démarrage du monitoring en thread séparé
    monitor_thread = threading.Thread(target=run_monitor, daemon=True)
    monitor_thread.start()
    
    # Démarrage du serveur Flask
    host = getattr(Config, 'FLASK_HOST', '127.0.0.1')
    port = getattr(Config, 'FLASK_PORT', 5000)
    debug = getattr(Config, 'FLASK_DEBUG', True)
    
    logger.info(f"🌐 Serveur web démarré sur http://{host}:{port}")
    app.run(debug=debug, host=host, port=port)