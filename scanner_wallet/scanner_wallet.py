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
from datetime import datetime
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
            
            # Mettre en cache
            self.token_cache[mint_address] = {
                'data': token_metadata,
                'cached_at': datetime.now()
            }
            
            logger.info(f"🪙 Token analysé: {token_metadata['symbol']} ({mint_address[:8]}...)")
            return token_metadata
            
        except Exception as e:
            logger.error(f"❌ Erreur lors de la récupération des métadonnées pour {mint_address}: {e}")
            
            # Mettre en cache même les échecs pour éviter de refaire la requête
            self.token_cache[mint_address] = {
                'data': token_metadata,
                'cached_at': datetime.now()
            }
            
            return token_metadata

    def analyze_token_transaction(self, tx_detail: Dict, wallet_address: str) -> Dict:
        """
        Analyse une transaction pour identifier les tokens, le type (buy/sell/transfer) et les montants
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
            'token_metadata': None
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
                    'decimals': balance.get('uiTokenAmount', {}).get('decimals', 9)
                }
            
            for balance in post_token_balances:
                account_index = balance.get('accountIndex')
                mint = balance.get('mint')
                ui_amount = balance.get('uiTokenAmount', {}).get('uiAmount')
                amount = float(ui_amount) if ui_amount is not None else 0.0
                post_balances_map[f"{account_index}_{mint}"] = {
                    'mint': mint,
                    'amount': amount,
                    'decimals': balance.get('uiTokenAmount', {}).get('decimals', 9)
                }
            
            # Trouver l'index du wallet dans les comptes
            accounts = message.get('accountKeys', [])
            wallet_index = None
            for i, account in enumerate(accounts):
                if account == wallet_address:
                    wallet_index = i
                    break
            
            if wallet_index is None:
                return analysis
            
            # Analyser les changements de balance pour ce wallet
            token_changes = []
            
            # Comparer les balances avant/après
            all_keys = set(pre_balances_map.keys()) | set(post_balances_map.keys())
            
            for key in all_keys:
                account_index = int(key.split('_')[0])
                
                # Ne regarder que les comptes liés à notre wallet
                if account_index != wallet_index:
                    continue
                    
                pre_balance = pre_balances_map.get(key, {'amount': 0, 'mint': None, 'decimals': 9})
                post_balance = post_balances_map.get(key, {'amount': 0, 'mint': None, 'decimals': 9})
                
                mint = pre_balance.get('mint') or post_balance.get('mint')
                if not mint:
                    continue
                    
                pre_amount = pre_balance.get('amount', 0) or 0
                post_amount = post_balance.get('amount', 0) or 0
                amount_change = post_amount - pre_amount
                
                if abs(amount_change) > 0.000001:  # Ignorer les changements microscopiques
                    token_changes.append({
                        'mint': mint,
                        'amount_change': amount_change,
                        'decimals': post_balance.get('decimals', 9)
                    })
            
            # Si on a des changements de tokens, analyser le type de transaction
            if token_changes:
                analysis['is_token_transaction'] = True
                
                # Prendre le plus gros changement de token
                main_token_change = max(token_changes, key=lambda x: abs(x['amount_change']))
                
                analysis['token_mint'] = main_token_change['mint']
                analysis['token_amount'] = abs(main_token_change['amount_change'])
                
                # Récupérer les métadonnées du token
                token_metadata = self.get_token_metadata(main_token_change['mint'])
                analysis['token_metadata'] = token_metadata
                analysis['token_symbol'] = token_metadata['symbol']
                analysis['token_name'] = token_metadata['name']
                
                # Déterminer le type de transaction
                sol_change = analysis['sol_amount_change']
                token_change = main_token_change['amount_change']
                
                if token_change > 0 and sol_change < 0:
                    # Tokens augmentent, SOL diminue = ACHAT
                    analysis['transaction_type'] = 'buy'
                    # Calculer le prix approximatif par token
                    if analysis['token_amount'] > 0:
                        analysis['price_per_token'] = abs(sol_change) / analysis['token_amount']
                        
                elif token_change < 0 and sol_change > 0:
                    # Tokens diminuent, SOL augmente = VENTE
                    analysis['transaction_type'] = 'sell'
                    # Calculer le prix approximatif par token
                    if analysis['token_amount'] > 0:
                        analysis['price_per_token'] = abs(sol_change) / analysis['token_amount']
                        
                elif token_change != 0:
                    # Changement de tokens sans changement significatif de SOL = TRANSFER
                    analysis['transaction_type'] = 'transfer'
                
                logger.debug(f"🔍 Transaction {analysis['transaction_type'].upper()}: "
                            f"{analysis['token_amount']:.4f} {analysis['token_symbol']} "
                            f"({abs(sol_change):.4f} SOL)")
            
            else:
                # Pas de changement de tokens détecté, mais on a un changement SOL
                if abs(analysis['sol_amount_change']) > 0.001:
                    analysis['transaction_type'] = 'sol_transfer'
                    analysis['token_symbol'] = 'SOL'
                    analysis['token_name'] = 'Solana'
                    analysis['token_amount'] = abs(analysis['sol_amount_change'])
            
            return analysis
            
        except Exception as e:
            logger.error(f"❌ Erreur lors de l'analyse de la transaction: {e}")
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
                balance_sol REAL,
                total_transactions INTEGER,
                total_volume REAL,
                pnl REAL,
                largest_transaction REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("✅ Base de données initialisée")
    
    

    def update_database_schema(self, cursor):
        """Met à jour la structure de la base de données existante"""
        # Liste des colonnes à ajouter si elles n'existent pas
        columns_to_add = [
            ('wallet_address', 'TEXT'),
            ('token_mint', 'TEXT'),
            ('token_symbol', 'TEXT'),
            ('token_name', 'TEXT'),
            ('transaction_type', 'TEXT'),
            ('token_amount', 'REAL'),
            ('price_per_token', 'REAL'),
            ('is_token_transaction', 'BOOLEAN DEFAULT 0')
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
        """Sauvegarde une transaction dans la base de données pour un wallet spécifique"""
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
                wallet_address,  # Utiliser le wallet_address passé en paramètre
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
        """Boucle principale de monitoring pour TOUS les wallets"""
        logger.info(f"🚀 Démarrage du monitoring pour {len(self.wallet_addresses)} wallets")
        
        consecutive_errors = 0
        max_consecutive_errors = Config.MAX_CONSECUTIVE_ERRORS
        
        while True:
            try:
                logger.info("--- 🔄 Cycle de monitoring multi-wallet ---")
                
                total_new_transactions = 0
                
                # Boucler sur TOUS les wallets
                for wallet_address in self.wallet_addresses:
                    logger.info(f"📱 Traitement du wallet: {wallet_address[:8]}...")
                    
                    # Récupérer les transactions pour ce wallet
                    transactions = self.get_transactions_for_wallet(wallet_address)
                    new_transactions = 0
                    
                    if transactions:
                        for tx in transactions:
                            # Vérifier si la transaction existe déjà
                            conn = sqlite3.connect(self.db_name)
                            cursor = conn.cursor()
                            cursor.execute("SELECT signature FROM transactions WHERE signature = ?", (tx["signature"],))
                            exists = cursor.fetchone()
                            conn.close()
                            
                            if not exists:
                                # Utiliser une méthode modifiée qui prend le wallet en paramètre
                                self.save_transaction_for_wallet(tx, wallet_address)
                                new_transactions += 1
                    
                    total_new_transactions += new_transactions
                    logger.info(f"✅ {new_transactions} nouvelles transactions pour {wallet_address[:8]}...")
                    
                    # Petite pause entre les wallets
                    time.sleep(1)
                
                # Mettre à jour les statistiques globales
                self.update_wallet_stats()
                
                if total_new_transactions > 0:
                    logger.info(f"🎉 TOTAL: {total_new_transactions} nouvelles transactions sur tous les wallets")
                else:
                    logger.info("ℹ️ Aucune nouvelle transaction détectée sur aucun wallet")
                
                consecutive_errors = 0
                
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"❌ Erreur monitoring multi-wallet (#{consecutive_errors}): {e}")
                
                if consecutive_errors >= max_consecutive_errors:
                    logger.critical(f"🚨 Trop d'erreurs ({consecutive_errors}). Pause longue...")
                    time.sleep(UPDATE_INTERVAL * 2)
                    consecutive_errors = 0
                else:
                    time.sleep(UPDATE_INTERVAL // 3)
            
            sleep_time = UPDATE_INTERVAL
            if consecutive_errors > 0:
                sleep_time *= (1 + consecutive_errors * 0.2)
            
            logger.info(f"⏱️ Prochaine vérification dans {sleep_time:.0f} secondes")
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
        """Récupère les détails d'une transaction pour un wallet spécifique"""
        result = self.get_solana_rpc_data(
            "getTransaction",
            [signature, {"encoding": "json", "maxSupportedTransactionVersion": 0}]
        )
        
        if not result or "result" not in result or not result["result"]:
            return None
        
        tx = result["result"]
        meta = tx.get("meta", {})
        
        # Calcul du changement de balance pour CE wallet
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
        
        # Analyser les tokens pour CE wallet
        try:
            token_analysis = self.analyze_token_transaction(result, wallet_address)
        except Exception as e:
            logger.error(f"Erreur lors de l'analyse des tokens pour {signature}: {e}")
            # Valeurs par défaut en cas d'erreur
            token_analysis = {
                'transaction_type': 'other',
                'token_mint': None,
                'token_symbol': None,
                'token_name': None,
                'token_amount': 0,
                'price_per_token': 0,
                'is_token_transaction': False
            }

        transaction_detail = {
            "signature": signature,
            "wallet_address": wallet_address,  # IMPORTANT: associer à ce wallet
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
            "is_token_transaction": token_analysis['is_token_transaction']
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
        WHERE ABS(amount) >= ?
    '''
    params = [min_amount]
    
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