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

# Configuration globale
WALLET_ADDRESS = Config.WALLET_ADDRESS
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
    def __init__(self, wallet_address: str, db_name: str):
        self.wallet_address = wallet_address
        self.db_name = db_name
        self.init_database()
        
    def init_database(self):
        """Initialise la base de données SQLite"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        # Table des transactions
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signature TEXT UNIQUE NOT NULL,
                slot INTEGER,
                block_time INTEGER,
                amount REAL,
                token_address TEXT,
                token_symbol TEXT,
                transaction_type TEXT,
                from_address TEXT,
                to_address TEXT,
                fee REAL,
                status TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
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
        
        return {
            "signature": signature,
            "slot": tx.get("slot", 0),
            "block_time": tx.get("blockTime"),
            "amount": amount,
            "fee": meta.get("fee", 0) / 1e9,
            "status": "success" if meta.get("err") is None else "failed",
            "accounts": accounts
        }
    
    def save_transaction(self, tx: Dict):
        """Sauvegarde une transaction dans la base de données"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO transactions 
                (signature, slot, block_time, amount, fee, status, from_address, to_address)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                tx["signature"],
                tx["slot"],
                tx["block_time"],
                tx["amount"],
                tx["fee"],
                tx["status"],
                tx.get("accounts", [None])[0] if tx.get("accounts") else None,
                self.wallet_address
            ))
            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Erreur lors de la sauvegarde: {e}")
        finally:
            conn.close()
    
    def update_wallet_stats(self):
        """Met à jour les statistiques du wallet"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        # Récupération des statistiques
        balance = self.get_wallet_balance()
        
        cursor.execute("SELECT COUNT(*) FROM transactions")
        total_transactions = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(ABS(amount)) FROM transactions WHERE amount != 0")
        result = cursor.fetchone()
        total_volume = result[0] if result[0] else 0
        
        cursor.execute("SELECT SUM(amount) FROM transactions")
        result = cursor.fetchone()
        pnl = result[0] if result[0] else 0
        
        cursor.execute("SELECT MAX(ABS(amount)) FROM transactions")
        result = cursor.fetchone()
        largest_transaction = result[0] if result[0] else 0
        
        # Sauvegarde des stats
        cursor.execute('''
            INSERT INTO wallet_stats 
            (balance_sol, total_transactions, total_volume, pnl, largest_transaction)
            VALUES (?, ?, ?, ?, ?)
        ''', (balance, total_transactions, total_volume, pnl, largest_transaction))
        
        conn.commit()
        conn.close()
        
        logger.info(f"📊 Stats - Balance: {balance:.4f} SOL, Transactions: {total_transactions}, P&L: {pnl:.4f} SOL")
    
    def monitor_loop(self):
        """Boucle principale de monitoring optimisée pour QuickNode"""
        logger.info(f"🚀 Démarrage du monitoring QuickNode pour le wallet: {self.wallet_address}")
        logger.info(f"⚡ Utilisation de QuickNode premium - Limite: ~300 req/sec")
        
        
        consecutive_errors = 0
        max_consecutive_errors = Config.MAX_CONSECUTIVE_ERRORS
        
        while True:
            try:
                logger.info("--- 🔄 Cycle de monitoring QuickNode ---")
                
                # Récupérer les transactions
                transactions = self.get_transactions()
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
                            self.save_transaction(tx)
                            new_transactions += 1
                
                # Mettre à jour les statistiques
                self.update_wallet_stats()
                
                if new_transactions > 0:
                    logger.info(f"✅ {new_transactions} nouvelles transactions traitées via QuikNode")
                else:
                    logger.info("ℹ️ Aucune nouvelle transaction détectée")
                
                # Réinitialiser le compteur d'erreurs en cas de succès
                consecutive_errors = 0
                
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"❌ Erreur monitoring (#{consecutive_errors}): {e}")
                
                if consecutive_errors >= max_consecutive_errors:
                    logger.critical(f"🚨 Trop d'erreurs ({consecutive_errors}). Pause longue...")
                    time.sleep(UPDATE_INTERVAL * 2)
                    consecutive_errors = 0
                else:
                    time.sleep(UPDATE_INTERVAL // 3)
            
            # Délai optimisé pour QuickNode
            sleep_time = UPDATE_INTERVAL
            if consecutive_errors > 0:
                sleep_time *= (1 + consecutive_errors * 0.2)
            
            logger.info(f"⏱️ Prochaine vérification dans {sleep_time:.0f} secondes")
            time.sleep(sleep_time)

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

@app.route('/api/transactions')
def get_transactions_api():
    """API pour récupérer les transactions avec filtres"""
    limit = request.args.get('limit', Config.DEFAULT_TRANSACTION_LIMIT, type=int)
    min_amount = request.args.get('min_amount', 0, type=float)
    
    # Respecter les limites configurées
    limit = min(limit, getattr(Config, 'MAX_TRANSACTION_LIMIT', 100))
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT signature, block_time, amount, fee, status, created_at
        FROM transactions 
        WHERE ABS(amount) >= ?
        ORDER BY block_time DESC 
        LIMIT ?
    ''', (min_amount, limit))
    
    transactions = cursor.fetchall()
    conn.close()
    
    result = [
        {
            "signature": tx[0],
            "block_time": tx[1],
            "amount": tx[2],
            "fee": tx[3],
            "status": tx[4],
            "created_at": tx[5]
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
    monitor = SolanaWalletMonitor(WALLET_ADDRESS, DB_NAME)
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