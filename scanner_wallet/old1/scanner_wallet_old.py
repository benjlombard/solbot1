#!/usr/bin/env python3
"""
Moniteur de Wallet Solana
Surveille les transactions d'un wallet Solana et les sauvegarde dans SQLite
"""

import sqlite3
import requests
import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional
from flask import Flask, jsonify, render_template
from flask_cors import CORS
import threading
import schedule

# Configuration
WALLET_ADDRESS = "2RH6rUTPBJ9rUDPpuV9b8z1YL56k1tYU6Uk5ZoaEFFSK"
RPC_ENDPOINT = "https://api.mainnet-beta.solana.com"
DB_NAME = "scan_wallet.db"
UPDATE_INTERVAL = 30  # secondes

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('wallet_monitor.log'),
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
            CREATE TABLE IF NOT EXISTS scan_wallet_transactions (
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
            CREATE TABLE IF NOT EXISTS scan_wallet_tokens (
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
            CREATE TABLE IF NOT EXISTS scan_wallet_stats (
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
        logger.info("Base de données initialisée")
    
    def get_solana_rpc_data(self, method: str, params: List) -> Optional[Dict]:
        """Effectue un appel RPC vers Solana"""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params
        }
        
        try:
            response = requests.post(RPC_ENDPOINT, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Erreur RPC: {e}")
            return None
    
    def get_wallet_balance(self) -> float:
        """Récupère le solde SOL du wallet"""
        result = self.get_solana_rpc_data("getBalance", [self.wallet_address])
        if result and "result" in result:
            return result["result"]["value"] / 1e9  # Conversion de lamports en SOL
        return 0.0
    
    def get_transactions(self, limit: int = 50) -> List[Dict]:
        """Récupère les transactions récentes du wallet"""
        result = self.get_solana_rpc_data(
            "getSignaturesForAddress",
            [self.wallet_address, {"limit": limit}]
        )
        
        if not result or "result" not in result:
            return []
        
        transactions = []
        for tx_info in result["result"]:
            tx_detail = self.get_transaction_details(tx_info["signature"])
            if tx_detail:
                transactions.append(tx_detail)
        
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
        
        logger.info(f"Stats mises à jour - Balance: {balance:.4f} SOL, Transactions: {total_transactions}")
    
    def monitor_loop(self):
        """Boucle principale de monitoring"""
        logger.info(f"Démarrage du monitoring pour le wallet: {self.wallet_address}")
        
        while True:
            try:
                transactions = self.get_transactions()
                new_transactions = 0
                
                for tx in transactions:
                    self.save_transaction(tx)
                    new_transactions += 1
                
                self.update_wallet_stats()
                
                if new_transactions > 0:
                    logger.info(f"{new_transactions} nouvelles transactions traitées")
                
            except Exception as e:
                logger.error(f"Erreur dans la boucle de monitoring: {e}")
            
            time.sleep(UPDATE_INTERVAL)

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
            "total_transactions": stats[1] if stats else 0,
            "total_volume": stats[2] if stats else 0,
            "pnl": stats[3] if stats else 0,
            "largest_transaction": stats[4] if stats else 0,
            "last_update": stats[5] if stats else None
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
    limit = request.args.get('limit', 50, type=int)
    min_amount = request.args.get('min_amount', 0, type=float)
    
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

def run_monitor():
    """Lance le monitoring en arrière-plan"""
    monitor = SolanaWalletMonitor(WALLET_ADDRESS, DB_NAME)
    monitor.monitor_loop()

if __name__ == "__main__":
    # Démarrage du monitoring en thread séparé
    monitor_thread = threading.Thread(target=run_monitor, daemon=True)
    monitor_thread.start()
    
    # Démarrage du serveur Flask
    logger.info("Démarrage du serveur web sur http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)