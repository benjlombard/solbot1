#!/usr/bin/env python3
"""
Moniteur de Wallet Solana avec approche optimisée des balance changes
Surveille intelligemment les nouveaux comptes de tokens et leurs changements
"""

import sqlite3
import requests
import json
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
import threading
import asyncio

# Importer la configuration
try:
    from config import DefaultConfig as Config
    print("✅ Configuration chargée depuis config.py")
except ImportError:
    print("⚠️ config.py non trouvé, utilisation des valeurs par défaut")
    class Config:
        WALLET_ADDRESS = "2RH6rUTPBJ9rUDPpuV9b8z1YL56k1tYU6Uk5ZoaEFFSK"
        WALLET_ADDRESSES = ["2RH6rUTPBJ9rUDPpuV9b8z1YL56k1tYU6Uk5ZoaEFFSK"]
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
        FULL_SCAN_INTERVAL_HOURS = 6  # Scan complet toutes les 6h
        RATE_LIMIT_DELAY = 0.2  # Délai entre requêtes RPC
        TOKEN_DISCOVERY_BATCH_SIZE = 50  # Traiter par lots

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
                'User-Agent': 'SolanaWalletMonitor/2.0-Optimized',
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

# Configuration du logging avec plus de détails
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.FileHandler('wallet_monitor.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class SolanaWalletMonitor:
    def __init__(self, wallet_addresses: List[str], db_name: str):
        self.wallet_addresses = wallet_addresses
        self.wallet_address = wallet_addresses[0] if wallet_addresses else None
        self.db_name = db_name
        self.token_cache = {}
        self.request_count = 0
        self.last_full_scan = {}  # Trackage des derniers scans complets par wallet
        self.init_database()

    def init_database(self):
        """Initialise la base de données SQLite avec schéma optimisé"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        # Table des transactions (inchangée)
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

        # Table des tokens (inchangée)
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

        # Table des statistiques du wallet (inchangée)
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

        # Table pour stocker les comptes de tokens (ATA) - AMÉLIORÉE
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS token_accounts (
                wallet_address TEXT,
                ata_pubkey TEXT,
                token_mint TEXT,
                balance REAL,
                decimals INTEGER DEFAULT 9,
                first_seen INTEGER,
                last_updated INTEGER,
                last_scanned INTEGER,
                is_active BOOLEAN DEFAULT 1,
                scan_priority INTEGER DEFAULT 1,
                PRIMARY KEY (wallet_address, ata_pubkey)
            )
        ''')

        # Table pour tracker les scans complets
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scan_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT,
                scan_type TEXT,
                total_accounts INTEGER,
                new_accounts INTEGER,
                scan_duration REAL,
                completed_at INTEGER,
                notes TEXT
            )
        ''')

        self.update_database_schema(cursor)
        conn.commit()
        conn.close()
        logger.info("✅ Base de données initialisée avec schéma optimisé")

    def update_database_schema(self, cursor):
        """Met à jour la structure de la base de données"""
        # Index pour optimiser les requêtes
        indexes_to_create = [
            ("idx_token_accounts_wallet", "CREATE INDEX IF NOT EXISTS idx_token_accounts_wallet ON token_accounts(wallet_address)"),
            ("idx_token_accounts_mint", "CREATE INDEX IF NOT EXISTS idx_token_accounts_mint ON token_accounts(token_mint)"),
            ("idx_token_accounts_priority", "CREATE INDEX IF NOT EXISTS idx_token_accounts_priority ON token_accounts(scan_priority DESC, last_scanned ASC)"),
            ("idx_token_accounts_active", "CREATE INDEX IF NOT EXISTS idx_token_accounts_active ON token_accounts(is_active, last_updated DESC)"),
            ("idx_transactions_wallet_time", "CREATE INDEX IF NOT EXISTS idx_transactions_wallet_time ON transactions(wallet_address, block_time DESC)"),
            ("idx_transactions_token_type", "CREATE INDEX IF NOT EXISTS idx_transactions_token_type ON transactions(is_token_transaction, block_time DESC)"),
            ("idx_scan_history_wallet", "CREATE INDEX IF NOT EXISTS idx_scan_history_wallet ON scan_history(wallet_address, completed_at DESC)")
        ]

        for index_name, index_sql in indexes_to_create:
            try:
                cursor.execute(index_sql)
                logger.debug(f"✅ Index '{index_name}' créé/vérifié")
            except sqlite3.OperationalError as e:
                logger.debug(f"Index '{index_name}' existe déjà: {e}")

    def rate_limited_rpc_call(self, method: str, params: List) -> Optional[Dict]:
        """Appel RPC avec respect du rate limit"""
        self.request_count += 1
        
        if self.request_count % 10 == 0:
            logger.debug(f"📊 Requêtes RPC effectuées: {self.request_count}")
        
        result = self.get_solana_rpc_data(method, params)
        
        # Respect du rate limit
        time.sleep(Config.RATE_LIMIT_DELAY)
        
        return result

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
                    retry_after = int(response.headers.get('Retry-After', 5))
                    logger.warning(f"⚠️ Rate limit sur {current_endpoint[:50]}... Attente {retry_after}s")
                    time.sleep(retry_after)
                    CURRENT_RPC_INDEX = (CURRENT_RPC_INDEX + 1) % len(RPC_ENDPOINTS)
                    continue
                else:
                    response.raise_for_status()

            except requests.exceptions.Timeout:
                logger.error(f"⏰ Timeout sur {current_endpoint[:50]}...")
                CURRENT_RPC_INDEX = (CURRENT_RPC_INDEX + 1) % len(RPC_ENDPOINTS)
            except requests.exceptions.ConnectionError:
                logger.error(f"🔌 Erreur de connexion sur {current_endpoint[:50]}...")
                CURRENT_RPC_INDEX = (CURRENT_RPC_INDEX + 1) % len(RPC_ENDPOINTS)
            except requests.RequestException as e:
                logger.error(f"❌ Erreur RPC: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))

        logger.error("❌ Tous les endpoints RPC ont échoué")
        return None

    def discover_token_accounts(self, wallet_address: str, force_full_scan: bool = False) -> Tuple[int, int]:
        """
        Découvre les comptes de tokens pour un wallet
        Retourne: (total_accounts, new_accounts)
        """
        scan_start_time = time.time()
        logger.info(f"🔍 Découverte des comptes de tokens pour {wallet_address[:8]}...")
        
        # Vérifier si un scan complet est nécessaire
        last_full_scan = self.last_full_scan.get(wallet_address, 0)
        current_time = int(time.time())
        time_since_last_scan = current_time - last_full_scan
        
        should_full_scan = (
            force_full_scan or 
            time_since_last_scan > (Config.FULL_SCAN_INTERVAL_HOURS * 3600) or
            last_full_scan == 0
        )
        
        if should_full_scan:
            logger.info(f"🔄 SCAN COMPLET pour {wallet_address[:8]}... (dernier scan: {time_since_last_scan//3600}h ago)")
            scan_type = "full"
        else:
            logger.info(f"📝 Scan incrémental pour {wallet_address[:8]}... (dernier scan: {time_since_last_scan//60}min ago)")
            scan_type = "incremental"

        # Récupérer les comptes de tokens actuels via RPC
        token_accounts_result = self.rate_limited_rpc_call(
            "getTokenAccountsByOwner",
            [
                wallet_address,
                {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                {"encoding": "jsonParsed"}
            ]
        )

        if not token_accounts_result or "result" not in token_accounts_result:
            logger.warning(f"❌ Impossible de récupérer les comptes de tokens pour {wallet_address[:8]}...")
            return 0, 0

        current_accounts = token_accounts_result["result"]["value"]
        total_accounts = len(current_accounts)
        logger.info(f"📊 Trouvé {total_accounts} comptes de tokens pour {wallet_address[:8]}...")

        # Charger les comptes existants depuis la DB
        existing_accounts = self.load_token_accounts_from_db(wallet_address)
        existing_ata_pubkeys = {acc['ata_pubkey'] for acc in existing_accounts}
        
        # Identifier les nouveaux comptes
        new_accounts = []
        updated_accounts = []
        
        for i, account in enumerate(current_accounts):
            if i > 0 and i % 50 == 0:
                logger.info(f"📈 Progression: {i}/{total_accounts} comptes traités...")
                
            ata_pubkey = account["pubkey"]
            token_info = account["account"]["data"]["parsed"]["info"]
            token_mint = token_info["mint"]
            balance = float(token_info["tokenAmount"]["uiAmount"] or 0)
            decimals = token_info["tokenAmount"]["decimals"]
            
            if ata_pubkey not in existing_ata_pubkeys:
                new_accounts.append({
                    'ata_pubkey': ata_pubkey,
                    'token_mint': token_mint,
                    'balance': balance,
                    'decimals': decimals,
                    'is_new': True
                })
                logger.debug(f"🆕 Nouveau compte découvert: {token_mint[:8]}... (balance: {balance:,.2f})")
            else:
                # Mettre à jour le compte existant
                updated_accounts.append({
                    'ata_pubkey': ata_pubkey,
                    'token_mint': token_mint,
                    'balance': balance,
                    'decimals': decimals,
                    'is_new': False
                })

        # Sauvegarder en base
        new_count = self.save_token_accounts_to_db(wallet_address, new_accounts + updated_accounts, scan_type)
        
        # Marquer comme scanné
        if should_full_scan:
            self.last_full_scan[wallet_address] = current_time

        # Enregistrer l'historique du scan
        scan_duration = time.time() - scan_start_time
        self.record_scan_history(wallet_address, scan_type, total_accounts, len(new_accounts), scan_duration)
        
        logger.info(f"✅ Scan {scan_type} terminé pour {wallet_address[:8]}... - "
                   f"{total_accounts} total, {len(new_accounts)} nouveaux, {len(updated_accounts)} mis à jour "
                   f"(durée: {scan_duration:.1f}s)")
        
        return total_accounts, len(new_accounts)

    def load_token_accounts_from_db(self, wallet_address: str) -> List[Dict]:
        """Charge les comptes de tokens depuis la base de données"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT ata_pubkey, token_mint, balance, decimals, first_seen, 
                       last_updated, last_scanned, is_active, scan_priority
                FROM token_accounts 
                WHERE wallet_address = ? AND is_active = 1
                ORDER BY scan_priority DESC, last_scanned ASC
            ''', (wallet_address,))
            
            rows = cursor.fetchall()
            accounts = []
            
            for row in rows:
                accounts.append({
                    'ata_pubkey': row[0],
                    'token_mint': row[1],
                    'balance': row[2],
                    'decimals': row[3],
                    'first_seen': row[4],
                    'last_updated': row[5],
                    'last_scanned': row[6],
                    'is_active': bool(row[7]),
                    'scan_priority': row[8]
                })
            
            logger.debug(f"📂 Chargé {len(accounts)} comptes depuis la DB pour {wallet_address[:8]}...")
            return accounts
            
        except sqlite3.Error as e:
            logger.error(f"❌ Erreur lors du chargement des comptes: {e}")
            return []
        finally:
            conn.close()

    def save_token_accounts_to_db(self, wallet_address: str, accounts: List[Dict], scan_type: str) -> int:
        """Sauvegarde les comptes de tokens en base avec logique intelligente"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        current_time = int(time.time())
        new_count = 0
        
        try:
            for account in accounts:
                is_new = account.get('is_new', False)
                
                # Priorité plus élevée pour les nouveaux comptes
                scan_priority = 3 if is_new else 1
                
                cursor.execute('''
                    INSERT OR REPLACE INTO token_accounts
                    (wallet_address, ata_pubkey, token_mint, balance, decimals,
                     first_seen, last_updated, last_scanned, is_active, scan_priority)
                    VALUES (?, ?, ?, ?, ?, 
                            COALESCE((SELECT first_seen FROM token_accounts 
                                    WHERE wallet_address = ? AND ata_pubkey = ?), ?),
                            ?, ?, 1, ?)
                ''', (
                    wallet_address, account['ata_pubkey'], account['token_mint'],
                    account['balance'], account['decimals'],
                    wallet_address, account['ata_pubkey'], current_time,  # Pour COALESCE
                    current_time, current_time, scan_priority
                ))
                
                if is_new:
                    new_count += 1
            
            conn.commit()
            logger.info(f"💾 Sauvegardé {len(accounts)} comptes ({new_count} nouveaux) pour {wallet_address[:8]}...")
            return new_count
            
        except sqlite3.Error as e:
            logger.error(f"❌ Erreur lors de la sauvegarde des comptes: {e}")
            return 0
        finally:
            conn.close()

    def record_scan_history(self, wallet_address: str, scan_type: str, total_accounts: int, 
                          new_accounts: int, scan_duration: float):
        """Enregistre l'historique des scans"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO scan_history 
                (wallet_address, scan_type, total_accounts, new_accounts, scan_duration, completed_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (wallet_address, scan_type, total_accounts, new_accounts, scan_duration, int(time.time())))
            
            conn.commit()
            logger.debug(f"📝 Historique de scan enregistré pour {wallet_address[:8]}...")
            
        except sqlite3.Error as e:
            logger.error(f"❌ Erreur lors de l'enregistrement de l'historique: {e}")
        finally:
            conn.close()

    def get_priority_accounts_for_scanning(self, wallet_address: str, limit: int = 100) -> List[Dict]:
        """Récupère les comptes prioritaires à scanner pour les balance changes - VERSION CORRIGÉE"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        current_time = int(time.time())
        
        try:
            # LOGIQUE CORRIGÉE: Plus agressive pour identifier les comptes à scanner
            cursor.execute('''
                SELECT ata_pubkey, token_mint, balance, decimals, scan_priority, last_scanned
                FROM token_accounts 
                WHERE wallet_address = ? AND is_active = 1
                ORDER BY 
                    CASE 
                        WHEN last_scanned IS NULL THEN 0  -- Jamais scannés = priorité max
                        WHEN scan_priority >= 3 THEN 1   -- Nouveaux comptes = haute priorité
                        WHEN ? - last_scanned > 1800 THEN 2  -- Plus de 30min = priorité moyenne
                        ELSE 3  -- Récents = basse priorité
                    END ASC,
                    scan_priority DESC,
                    last_scanned ASC
                LIMIT ?
            ''', (wallet_address, current_time, limit))
            
            rows = cursor.fetchall()
            accounts = []
            
            for row in rows:
                last_scanned = row[5]
                time_since_scan = (current_time - last_scanned) if last_scanned else 999999
                
                # CRITÈRES PLUS PERMISSIFS pour capturer plus de comptes
                needs_scan = (
                    last_scanned is None or  # Jamais scanné
                    time_since_scan > 900 or  # Plus de 15 minutes (au lieu de 30)
                    row[4] >= 3  # Priorité élevée (nouveaux comptes)
                )
                
                accounts.append({
                    'ata_pubkey': row[0],
                    'token_mint': row[1],
                    'balance': row[2],
                    'decimals': row[3],
                    'scan_priority': row[4],
                    'last_scanned': last_scanned,
                    'needs_scan': needs_scan,
                    'time_since_scan': time_since_scan
                })
            
            priority_accounts = [acc for acc in accounts if acc['needs_scan']]
            
            # LOGS AMÉLIORÉS pour diagnostiquer
            logger.info(f"🎯 {len(priority_accounts)} comptes prioritaires identifiés pour {wallet_address[:8]}... "
                    f"(sur {len(accounts)} comptes actifs)")
            
            if len(priority_accounts) == 0 and len(accounts) > 0:
                # Diagnostiquer pourquoi aucun compte n'est prioritaire
                never_scanned = sum(1 for acc in accounts if acc['last_scanned'] is None)
                recent_scanned = sum(1 for acc in accounts if acc['time_since_scan'] < 900)
                old_scanned = sum(1 for acc in accounts if acc['time_since_scan'] >= 900)
                
                logger.info(f"🔍 Diagnostic priorités pour {wallet_address[:8]}...:")
                logger.info(f"   - Jamais scannés: {never_scanned}")
                logger.info(f"   - Scannés récemment (<15min): {recent_scanned}")
                logger.info(f"   - Scannés anciennement (>15min): {old_scanned}")
                
                # FORCER au moins quelques comptes si aucun n'est prioritaire
                if len(accounts) > 0:
                    forced_accounts = accounts[:min(5, len(accounts))]
                    for acc in forced_accounts:
                        acc['needs_scan'] = True
                    priority_accounts = forced_accounts
                    logger.info(f"🔧 FORÇAGE: {len(priority_accounts)} comptes forcés pour scan")
            
            return priority_accounts[:limit]
            
        except sqlite3.Error as e:
            logger.error(f"❌ Erreur lors de la récupération des comptes prioritaires: {e}")
            return []
        finally:
            conn.close()

    def scan_balance_changes_for_accounts(self, wallet_address: str, priority_accounts: List[Dict]) -> List[Dict]:
        """Scanne les balance changes pour les comptes prioritaires"""
        balance_changes = []
        current_time = int(time.time())
        scan_window = 3600  # 1 heure
        
        logger.info(f"🔍 Scan des balance changes pour {len(priority_accounts)} comptes prioritaires...")
        
        for i, account in enumerate(priority_accounts):
            if i > 0 and i % 10 == 0:
                logger.info(f"📈 Progression balance changes: {i}/{len(priority_accounts)} comptes scannés...")
            
            ata_pubkey = account['ata_pubkey']
            token_mint = account['token_mint']
            
            # Récupérer les signatures récentes pour ce compte de token
            signatures_result = self.rate_limited_rpc_call(
                "getSignaturesForAddress",
                [ata_pubkey, {"limit": 10, "commitment": "finalized"}]
            )
            
            if not signatures_result or "result" not in signatures_result:
                continue
                
            recent_signatures = [
                sig for sig in signatures_result["result"]
                if sig.get("blockTime") and sig["blockTime"] >= (current_time - scan_window)
            ]
            
            if not recent_signatures:
                continue
                
            logger.debug(f"🔍 {len(recent_signatures)} signatures récentes pour {token_mint[:8]}...")
            
            # Analyser chaque transaction récente
            for sig_info in recent_signatures:
                signature = sig_info["signature"]
                
                # Vérifier si déjà en DB
                if self.signature_exists_in_db(signature):
                    continue
                    
                # Récupérer les détails de la transaction
                tx_detail = self.rate_limited_rpc_call(
                    "getTransaction",
                    [signature, {"encoding": "json", "maxSupportedTransactionVersion": 0}]
                )
                
                if not tx_detail or not tx_detail.get("result"):
                    continue
                
                # Analyser le balance change
                balance_change_txs = self.analyze_balance_change_transaction(tx_detail, wallet_address)
                
                for bc_tx in balance_change_txs:
                    if bc_tx['token_mint'] == token_mint:  # Vérifier que c'est le bon token
                        balance_changes.append(bc_tx)
                        logger.info(f"✅ Balance change: {bc_tx['transaction_type'].upper()} "
                                   f"{bc_tx['token_amount']:,.4f} {bc_tx['token_symbol']} "
                                   f"({bc_tx['amount_change']:+.4f})")
            
            # Marquer le compte comme scanné
            self.mark_account_as_scanned(wallet_address, ata_pubkey)
            
            # Respecter le rate limit
            time.sleep(Config.RATE_LIMIT_DELAY)
        
        logger.info(f"🎯 Scan terminé: {len(balance_changes)} balance changes trouvés")
        return balance_changes

    def mark_account_as_scanned(self, wallet_address: str, ata_pubkey: str):
        """Marque un compte comme scanné récemment"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        current_time = int(time.time())
        
        try:
            cursor.execute('''
                UPDATE token_accounts 
                SET last_scanned = ?, scan_priority = CASE 
                    WHEN scan_priority > 1 THEN scan_priority - 1 
                    ELSE 1 
                END
                WHERE wallet_address = ? AND ata_pubkey = ?
            ''', (current_time, wallet_address, ata_pubkey))
            
            conn.commit()
            
        except sqlite3.Error as e:
            logger.error(f"❌ Erreur lors de la mise à jour du scan: {e}")
        finally:
            conn.close()

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

    # [Le reste des méthodes reste identique - get_token_metadata, analyze_balance_change_transaction, etc.]
    
    def get_token_metadata(self, mint_address: str) -> Dict:
        """Récupère les métadonnées d'un token avec cache et fallbacks multiples"""
        if mint_address in self.token_cache:
            cached_data = self.token_cache[mint_address]
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
            # Méthode 1: Jupiter Token List
            try:
                response = requests.get('https://token.jup.ag/all', timeout=10, headers={'Accept': 'application/json'})
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

            # Fallback si UNKNOWN
            if token_metadata['symbol'] == 'UNKNOWN':
                short_mint = mint_address[:6].upper()
                token_metadata.update({
                    'symbol': f"TOKEN_{short_mint}",
                    'name': f"Token {short_mint}",
                })

            self.token_cache[mint_address] = {
                'data': token_metadata,
                'cached_at': datetime.now()
            }

            return token_metadata

        except Exception as e:
            logger.error(f"❌ Erreur lors de la récupération des métadonnées pour {mint_address}: {e}")
            short_mint = mint_address[:6].upper()
            token_metadata.update({
                'symbol': f"TOKEN_{short_mint}",
                'name': f"Token {short_mint}",
            })
            self.token_cache[mint_address] = {
                'data': token_metadata,
                'cached_at': datetime.now()
            }
            return token_metadata
    
    def analyze_balance_change_transaction(self, tx_detail: Dict, wallet_address: str) -> List[Dict]:
        """Analyse une transaction pour extraire tous les balance changes"""
        try:
            tx = tx_detail["result"]
            meta = tx.get("meta", {})
            balance_changes = []
            signature = tx.get("transaction", {}).get("signatures", [None])[0]
            
            pre_token_balances = meta.get("preTokenBalances", [])
            post_token_balances = meta.get("postTokenBalances", [])
            
            logger.debug(f"📝 Analyse transaction {signature[:10]}... - "
                        f"{len(pre_token_balances)} pre, {len(post_token_balances)} post balances")

            # Créer un mapping des changements de balance
            balance_changes_map = {}
            
            # Traiter les pre-balances
            for pre_balance in pre_token_balances:
                account_index = pre_balance.get("accountIndex")
                token_mint = pre_balance.get("mint")
                owner = pre_balance.get("owner")
                
                if owner == wallet_address:
                    key = f"{account_index}_{token_mint}"
                    pre_amount = float(pre_balance.get("uiTokenAmount", {}).get("uiAmount") or 0)
                    decimals = pre_balance.get("uiTokenAmount", {}).get("decimals", 9)
                    
                    balance_changes_map[key] = {
                        'token_mint': token_mint,
                        'pre_amount': pre_amount,
                        'post_amount': 0,
                        'decimals': decimals,
                        'account_index': account_index
                    }

            # Traiter les post-balances
            for post_balance in post_token_balances:
                account_index = post_balance.get("accountIndex")
                token_mint = post_balance.get("mint")
                owner = post_balance.get("owner")
                
                if owner == wallet_address:
                    key = f"{account_index}_{token_mint}"
                    post_amount = float(post_balance.get("uiTokenAmount", {}).get("uiAmount") or 0)
                    decimals = post_balance.get("uiTokenAmount", {}).get("decimals", 9)
                    
                    if key in balance_changes_map:
                        balance_changes_map[key]['post_amount'] = post_amount
                    else:
                        # Nouveau token (pre_amount = 0)
                        balance_changes_map[key] = {
                            'token_mint': token_mint,
                            'pre_amount': 0,
                            'post_amount': post_amount,
                            'decimals': decimals,
                            'account_index': account_index
                        }

            # Analyser les changements significatifs
            for key, change_data in balance_changes_map.items():
                pre_amount = change_data['pre_amount']
                post_amount = change_data['post_amount']
                amount_change = post_amount - pre_amount
                
                if abs(amount_change) > 0.000001:  # Changement significatif
                    token_mint = change_data['token_mint']
                    
                    # Récupérer les métadonnées du token
                    try:
                        token_metadata = self.get_token_metadata(token_mint)
                        token_symbol = token_metadata["symbol"]
                        token_name = token_metadata["name"]
                    except Exception as e:
                        logger.warning(f"Erreur métadonnées token {token_mint}: {e}")
                        token_symbol = f"TOKEN_{token_mint[:6]}"
                        token_name = f"Unknown Token {token_mint[:6]}"

                    # Calculer le changement SOL
                    accounts = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
                    pre_balances = meta.get("preBalances", [])
                    post_balances = meta.get("postBalances", [])
                    
                    sol_change = 0
                    for i, account in enumerate(accounts):
                        if account == wallet_address and i < len(pre_balances) and i < len(post_balances):
                            pre_sol = pre_balances[i] if pre_balances[i] is not None else 0
                            post_sol = post_balances[i] if post_balances[i] is not None else 0
                            sol_change = (post_sol - pre_sol) / 1e9
                            break

                    # Déterminer le type de transaction et prix
                    transaction_type = "other"
                    price_per_token = 0
                    SOL_CHANGE_THRESHOLD = 0.001

                    if amount_change > 0:  # Achat/Réception
                        if sol_change < -SOL_CHANGE_THRESHOLD:
                            transaction_type = "buy"
                            price_per_token = abs(sol_change) / abs(amount_change)
                        else:
                            transaction_type = "transfer"
                    elif amount_change < 0:  # Vente/Envoi
                        if sol_change > SOL_CHANGE_THRESHOLD:
                            transaction_type = "sell"
                            price_per_token = abs(sol_change) / abs(amount_change)
                        else:
                            transaction_type = "transfer"

                    # Déterminer si c'est une grosse quantité
                    abs_amount = abs(amount_change)
                    decimals = change_data["decimals"]
                    is_large_token_amount = (
                        abs_amount >= 100000 or
                        (abs_amount >= 1000 and decimals <= 6) or
                        (abs_amount >= 10 and decimals <= 2)
                    )

                    balance_change_tx = {
                        "signature": signature,
                        "wallet_address": wallet_address,
                        "slot": tx.get("slot", 0),
                        "block_time": tx.get("blockTime"),
                        "amount": sol_change,
                        "fee": meta.get("fee", 0) / 1e9,
                        "status": "success" if meta.get("err") is None else "failed",
                        "transaction_type": transaction_type,
                        "token_mint": token_mint,
                        "token_symbol": token_symbol,
                        "token_name": token_name,
                        "token_amount": abs(amount_change),
                        "amount_change": amount_change,
                        "price_per_token": price_per_token,
                        "is_token_transaction": True,
                        "is_large_token_amount": is_large_token_amount,
                        "source": "balance_change"
                    }

                    balance_changes.append(balance_change_tx)
                    logger.debug(f"✅ Balance change détecté: {transaction_type.upper()} "
                               f"{abs(amount_change):,.4f} {token_symbol}")

            return balance_changes

        except Exception as e:
            logger.error(f"❌ Erreur analyse balance change: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return []

    def save_transaction_for_wallet(self, tx: Dict, wallet_address: str):
        """Sauvegarde une transaction pour un wallet spécifique"""
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

            if tx.get("is_token_transaction"):
                source = tx.get("source", "signature")
                logger.info(f"💾 Sauvegarde [{source.upper()}]: {tx.get('transaction_type', 'unknown').upper()} "
                           f"{tx.get('token_amount', 0):,.4f} {tx.get('token_symbol', 'UNKNOWN')} "
                           f"({'🔥 GROSSE QUANTITÉ' if tx.get('is_large_token_amount') else 'normale'})")
        except sqlite3.Error as e:
            logger.error(f"❌ Erreur lors de la sauvegarde: {e}")
        finally:
            conn.close()

    def get_wallet_balance_for_address(self, wallet_address: str) -> float:
        """Récupère le solde SOL pour un wallet spécifique"""
        result = self.rate_limited_rpc_call("getBalance", [wallet_address])
        if result and "result" in result:
            return result["result"]["value"] / 1e9
        return 0.0

    def update_wallet_stats(self):
        """Met à jour les statistiques pour tous les wallets"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()

        for wallet_address in self.wallet_addresses:
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

            cursor.execute('''
                INSERT INTO wallet_stats 
                (wallet_address, balance_sol, total_transactions, total_volume, pnl, largest_transaction)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (wallet_address, balance, total_transactions, total_volume, pnl, largest_transaction))

            logger.info(f"📊 Stats {wallet_address[:8]}... - Balance: {balance:.4f} SOL, "
                       f"Transactions: {total_transactions}, P&L: {pnl:.4f} SOL")

        conn.commit()
        conn.close()

    def monitor_loop(self):
        """Boucle principale de monitoring optimisée avec approche intelligente"""
        logger.info(f"🚀 Démarrage du monitoring OPTIMISÉ pour {len(self.wallet_addresses)} wallets")
        logger.info(f"🔧 Configuration: Rate limit = {Config.RATE_LIMIT_DELAY}s, "
                   f"Scan complet = {Config.FULL_SCAN_INTERVAL_HOURS}h")

        consecutive_errors = 0
        max_consecutive_errors = Config.MAX_CONSECUTIVE_ERRORS
        cycle_count = 0

        while True:
            try:
                cycle_count += 1
                logger.info(f"=" * 80)
                logger.info(f"🔄 CYCLE #{cycle_count} - Monitoring OPTIMISÉ")
                logger.info(f"=" * 80)

                total_new_transactions = 0
                total_accounts_discovered = 0
                total_new_accounts = 0

                for wallet_index, wallet_address in enumerate(self.wallet_addresses):
                    logger.info(f"📱 [{wallet_index + 1}/{len(self.wallet_addresses)}] "
                               f"Traitement du wallet: {wallet_address[:8]}...")

                    # ÉTAPE 1: Découverte/mise à jour des comptes de tokens
                    logger.info(f"🔍 ÉTAPE 1: Découverte des comptes de tokens...")
                    total_accounts, new_accounts = self.discover_token_accounts(wallet_address)
                    total_accounts_discovered += total_accounts
                    total_new_accounts += new_accounts

                    if new_accounts > 0:
                        logger.info(f"🆕 {new_accounts} nouveaux comptes découverts pour {wallet_address[:8]}...")

                    # ÉTAPE 2: Récupération des comptes prioritaires à scanner
                    logger.info(f"🎯 ÉTAPE 2: Identification des comptes prioritaires...")
                    priority_accounts = self.get_priority_accounts_for_scanning(wallet_address, limit=50)

                    if not priority_accounts:
                        logger.info(f"✅ Aucun compte prioritaire à scanner pour {wallet_address[:8]}...")
                        continue

                    # ÉTAPE 3: Scan des balance changes sur les comptes prioritaires
                    logger.info(f"🔍 ÉTAPE 3: Scan des balance changes...")
                    balance_changes = self.scan_balance_changes_for_accounts(wallet_address, priority_accounts)

                    # ÉTAPE 4: Sauvegarde des nouvelles transactions
                    new_balance_changes = 0
                    for tx in balance_changes:
                        if not self.signature_exists_in_db(tx["signature"]):
                            self.save_transaction_for_wallet(tx, wallet_address)
                            new_balance_changes += 1

                    total_new_transactions += new_balance_changes

                    logger.info(f"✅ Wallet {wallet_address[:8]}... terminé - "
                               f"Comptes: {total_accounts} ({new_accounts} nouveaux), "
                               f"Balance changes: {new_balance_changes}")

                    # Pause entre wallets pour respecter le rate limit
                    if wallet_index < len(self.wallet_addresses) - 1:
                        time.sleep(2)

                # ÉTAPE 5: Mise à jour des statistiques
                logger.info(f"📊 ÉTAPE 5: Mise à jour des statistiques...")
                self.update_wallet_stats()

                # Résumé du cycle
                logger.info(f"=" * 80)
                logger.info(f"🎉 CYCLE #{cycle_count} TERMINÉ:")
                logger.info(f"   📊 Total comptes découverts: {total_accounts_discovered}")
                logger.info(f"   🆕 Nouveaux comptes: {total_new_accounts}")
                logger.info(f"   💰 Nouvelles transactions: {total_new_transactions}")
                logger.info(f"   🔢 Requêtes RPC effectuées: {self.request_count}")
                logger.info(f"=" * 80)
                
                if total_new_transactions > 0:
                    logger.info(f"🎊 SUCCÈS: {total_new_transactions} nouvelles transactions détectées!")
                else:
                    logger.info(f"ℹ️ Aucune nouvelle transaction détectée ce cycle")

                consecutive_errors = 0

            except Exception as e:
                consecutive_errors += 1
                logger.error(f"❌ Erreur monitoring cycle #{cycle_count} (#{consecutive_errors}): {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")

                if consecutive_errors >= max_consecutive_errors:
                    logger.critical(f"🚨 Trop d'erreurs consécutives ({consecutive_errors}). Pause longue...")
                    time.sleep(UPDATE_INTERVAL * 2)
                    consecutive_errors = 0
                else:
                    time.sleep(UPDATE_INTERVAL // 3)

            # Calcul du temps d'attente adaptatif
            sleep_time = UPDATE_INTERVAL
            if consecutive_errors > 0:
                sleep_time *= (1 + consecutive_errors * 0.3)

            logger.info(f"⏱️ Prochaine vérification dans {sleep_time:.0f} secondes...")
            logger.info(f"🔄 Auto-refresh actif - Cycle #{cycle_count + 1} à {(datetime.now() + timedelta(seconds=sleep_time)).strftime('%H:%M:%S')}")
            
            time.sleep(sleep_time)

# API Flask pour le dashboard
app = Flask(__name__)
CORS(app)

@app.route('/')
def dashboard():
    return render_template('new_dashboard.html')

@app.route('/api/health')
def health_check():
    """Point de santé de l'API"""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "version": "2.0-optimized"
    })


# Ajouter ces routes dans ton scanner_wallet.py, dans la section API Flask

@app.route('/api/token-discoveries')
def get_token_discoveries():
    """API pour récupérer les découvertes de tokens récentes - VERSION CORRIGÉE"""
    hours = request.args.get('hours', 24, type=int)
    
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Calculer le timestamp de début
        current_time = int(time.time())
        start_time = current_time - (hours * 3600)
        
        # CORRECTION: Utiliser les colonnes qui existent vraiment
        cursor.execute('''
            SELECT ta.token_mint, ta.first_seen, ta.balance, ta.wallet_address,
                   COUNT(t.signature) as transaction_count
            FROM token_accounts ta
            LEFT JOIN transactions t ON ta.token_mint = t.token_mint 
                AND t.wallet_address = ta.wallet_address
            WHERE ta.first_seen >= ?
            GROUP BY ta.token_mint, ta.first_seen, ta.balance, ta.wallet_address
            ORDER BY ta.first_seen DESC
            LIMIT 20
        ''', (start_time,))
        
        discoveries = []
        for row in cursor.fetchall():
            # Récupérer le symbol depuis les transactions si disponible
            cursor.execute('''
                SELECT token_symbol FROM transactions 
                WHERE token_mint = ? AND token_symbol IS NOT NULL 
                LIMIT 1
            ''', (row[0],))
            symbol_result = cursor.fetchone()
            symbol = symbol_result[0] if symbol_result else f"TOKEN_{row[0][:6]}"
            
            discoveries.append({
                'token_mint': row[0],
                'symbol': symbol,
                'discovered_at': row[1],
                'balance': row[2],
                'wallet_address': row[3],
                'wallet_short': f"{row[3][:4]}...{row[3][-4:]}" if row[3] else 'Unknown',
                'transaction_count': row[4],
                'age_hours': (current_time - row[1]) / 3600 if row[1] else 0
            })
        
        conn.close()
        return jsonify({'discoveries': discoveries})
        
    except Exception as e:
        logger.error(f"Erreur récupération token discoveries: {e}")
        return jsonify({'discoveries': []}), 500

@app.route('/api/large-transactions')
def get_large_transactions():
    """API pour récupérer les transactions importantes"""
    hours = request.args.get('hours', 24, type=int)
    
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Calculer le timestamp de début
        current_time = int(time.time())
        start_time = current_time - (hours * 3600)
        
        cursor.execute('''
            SELECT signature, wallet_address, token_mint, token_symbol, token_name,
                   transaction_type, token_amount, amount, block_time, is_large_token_amount
            FROM transactions 
            WHERE is_large_token_amount = 1 
            AND block_time >= ?
            ORDER BY block_time DESC 
            LIMIT 20
        ''', (start_time,))
        
        transactions = []
        for row in cursor.fetchall():
            transactions.append({
                'signature': row[0],
                'wallet_address': row[1],
                'token_mint': row[2],
                'token_symbol': row[3],
                'token_name': row[4],
                'transaction_type': row[5],
                'token_amount': row[6],
                'amount': row[7],
                'block_time': row[8],
                'is_large_token_amount': bool(row[9])
            })
        
        conn.close()
        return jsonify({'transactions': transactions})
        
    except Exception as e:
        logger.error(f"Erreur récupération large transactions: {e}")
        return jsonify({'transactions': []}), 500

@app.route('/api/debug/token-accounts/<wallet_address>')
def debug_token_accounts(wallet_address):
    """Debug: Voir les comptes de tokens d'un wallet"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT ata_pubkey, token_mint, balance, decimals, 
                   first_seen, last_updated, last_scanned, 
                   is_active, scan_priority
            FROM token_accounts 
            WHERE wallet_address = ?
            ORDER BY scan_priority DESC, last_scanned ASC
            LIMIT 20
        ''', (wallet_address,))
        
        accounts = []
        current_time = int(time.time())
        
        for row in cursor.fetchall():
            accounts.append({
                'ata_pubkey': row[0][:8] + "..." + row[0][-8:],
                'token_mint': row[1][:8] + "..." + row[1][-8:],
                'balance': row[2],
                'decimals': row[3],
                'first_seen': row[4],
                'last_updated': row[5],
                'last_scanned': row[6],
                'is_active': bool(row[7]),
                'scan_priority': row[8],
                'minutes_since_scan': round((current_time - row[6]) / 60, 1) if row[6] else "Never"
            })
        
        conn.close()
        return jsonify({
            'wallet_address': wallet_address,
            'total_accounts': len(accounts),
            'accounts': accounts
        })
        
    except Exception as e:
        logger.error(f"Erreur debug token accounts: {e}")
        return jsonify({'error': str(e)}), 500
        
@app.route('/api/scan-progress')
def get_scan_progress():
    """API pour récupérer la progression des scans - VERSION CORRIGÉE"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Récupérer l'historique récent des scans
        cursor.execute('''
            SELECT wallet_address, scan_type, total_accounts, new_accounts, 
                   scan_duration, completed_at
            FROM scan_history 
            ORDER BY completed_at DESC 
            LIMIT 10
        ''')
        
        progress = []
        for row in cursor.fetchall():
            progress.append({
                'wallet_address': row[0],
                'wallet_short': f"{row[0][:4]}...{row[0][-4:]}" if row[0] else 'Unknown',
                'scan_type': row[1],
                'total_accounts': row[2],
                'new_accounts': row[3],
                'scan_duration': round(row[4], 2) if row[4] else 0,
                'completed_at': row[5],
                'age_minutes': round((int(time.time()) - row[5]) / 60, 1) if row[5] else 0
            })
        
        # Calculer le statut global
        if progress:
            recent_scan = progress[0]
            if recent_scan['age_minutes'] < 5:
                status = "Active"
            elif recent_scan['age_minutes'] < 60:
                status = "Recent"
            else:
                status = "Idle"
        else:
            status = "Unknown"
        
        # Ajouter des statistiques globales
        cursor.execute('''
            SELECT 
                COUNT(DISTINCT wallet_address) as total_wallets,
                SUM(total_accounts) as total_accounts,
                SUM(new_accounts) as total_new_accounts,
                AVG(scan_duration) as avg_duration
            FROM scan_history 
            WHERE completed_at >= ?
        ''', (int(time.time()) - 86400,))  # Dernières 24h
        
        stats_row = cursor.fetchone()
        global_stats = {
            'total_wallets_scanned': stats_row[0] or 0,
            'total_accounts_processed': stats_row[1] or 0,
            'total_new_accounts_found': stats_row[2] or 0,
            'average_scan_duration': round(stats_row[3], 2) if stats_row[3] else 0
        }
        
        conn.close()
        return jsonify({
            'progress': progress,
            'status': status,
            'global_stats': global_stats
        })
        
    except Exception as e:
        logger.error(f"Erreur récupération scan progress: {e}")
        return jsonify({
            'progress': [],
            'status': 'Error',
            'global_stats': {}
        }), 500

@app.route('/api/wallet-summary')
def get_wallet_summary():
    """API pour récupérer un résumé détaillé par wallet"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        wallets_summary = []
        
        for wallet_address in WALLET_ADDRESSES:
            # Stats des comptes de tokens
            cursor.execute('''
                SELECT COUNT(*) as total_accounts,
                       COUNT(CASE WHEN scan_priority >= 3 THEN 1 END) as new_accounts
                FROM token_accounts 
                WHERE wallet_address = ? AND is_active = 1
            ''', (wallet_address,))
            accounts_stats = cursor.fetchone()
            
            # Stats des transactions
            cursor.execute('''
                SELECT COUNT(*) as total_transactions,
                       COUNT(CASE WHEN is_token_transaction = 1 THEN 1 END) as token_transactions,
                       COUNT(CASE WHEN is_large_token_amount = 1 THEN 1 END) as large_transactions
                FROM transactions 
                WHERE wallet_address = ?
            ''', (wallet_address,))
            tx_stats = cursor.fetchone()
            
            # Balance SOL
            cursor.execute('''
                SELECT balance_sol FROM wallet_stats 
                WHERE wallet_address = ? 
                ORDER BY updated_at DESC LIMIT 1
            ''', (wallet_address,))
            balance_result = cursor.fetchone()
            balance = balance_result[0] if balance_result else 0.0
            
            wallets_summary.append({
                'wallet_address': wallet_address,
                'short_address': f"{wallet_address[:8]}...{wallet_address[-8:]}",
                'balance_sol': balance,
                'total_accounts': accounts_stats[0] if accounts_stats else 0,
                'new_accounts': accounts_stats[1] if accounts_stats else 0,
                'total_transactions': tx_stats[0] if tx_stats else 0,
                'token_transactions': tx_stats[1] if tx_stats else 0,
                'large_transactions': tx_stats[2] if tx_stats else 0
            })
        
        conn.close()
        return jsonify({
            'wallets': wallets_summary,
            'total_wallets': len(wallets_summary)
        })
        
    except Exception as e:
        logger.error(f"Erreur récupération wallet summary: {e}")
        return jsonify({'wallets': [], 'total_wallets': 0}), 500


@app.route('/api/dashboard-data')
def get_dashboard_data():
    """Données principales pour le dashboard - VERSION AMÉLIORÉE"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Stats générales MULTI-WALLETS
        cursor.execute("SELECT COUNT(DISTINCT token_mint) FROM transactions WHERE is_token_transaction = 1")
        total_tokens = cursor.fetchone()[0] or 0
        
        cursor.execute("SELECT COUNT(*) FROM token_accounts WHERE is_active = 1")
        total_token_accounts = cursor.fetchone()[0] or 0
        
        cursor.execute("""
            SELECT COUNT(*) FROM transactions 
            WHERE is_token_transaction = 1 AND block_time >= ?
        """, (int(time.time()) - 3600,))  # Dernière heure
        balance_changes_1h = cursor.fetchone()[0] or 0
        
        cursor.execute("""
            SELECT COUNT(*) FROM transactions 
            WHERE is_large_token_amount = 1 AND block_time >= ?
        """, (int(time.time()) - 86400,))  # Dernières 24h
        large_transactions_24h = cursor.fetchone()[0] or 0
        
        # Dernier scan
        cursor.execute("""
            SELECT MAX(completed_at) FROM scan_history
        """)
        last_scan_result = cursor.fetchone()
        last_scan_time = last_scan_result[0] if last_scan_result[0] else 0
        
        # Tokens les plus actifs par wallet (AMÉLIORATION)
        cursor.execute("""
            SELECT t.token_symbol, t.token_mint, t.wallet_address, 
                   COUNT(*) as tx_count,
                   SUM(CASE WHEN transaction_type = 'buy' THEN token_amount ELSE 0 END) as total_bought,
                   AVG(price_per_token) as avg_price,
                   MAX(block_time) as last_activity
            FROM transactions t
            WHERE is_token_transaction = 1 AND block_time >= ?
            GROUP BY token_mint, token_symbol, wallet_address
            HAVING tx_count >= 1
            ORDER BY tx_count DESC, last_activity DESC
            LIMIT 20
        """, (int(time.time()) - 86400,))
        
        top_tokens_data = cursor.fetchall()
        top_tokens = []
        for row in top_tokens_data:
            top_tokens.append({
                'symbol': row[0] or 'UNKNOWN',
                'address': row[1],
                'wallet_address': row[2],
                'wallet_short': f"{row[2][:4]}...{row[2][-4:]}" if row[2] else 'Unknown',
                'price': row[5] or 0,
                'volume': row[3] or 0,
                'total_bought': row[4] or 0,
                'last_activity': row[6] or 0,
                'score': min(100, (row[3] * 10) + (row[4] * 0.01))
            })
        
        conn.close()
        
        return jsonify({
            'stats': {
                'totalTokenAccounts': total_token_accounts,
                'balanceChangesCount': balance_changes_1h,
                'largeTransactionsCount': large_transactions_24h,
                'lastScanTime': last_scan_time,
                'totalTokens': total_tokens
            },
            'topTokens': top_tokens[:8],
            'newGems': [t for t in top_tokens if t['last_activity'] > (int(time.time()) - 7200)][:5],  # 2h
            'volumeAlerts': [t for t in top_tokens if t['volume'] > 5][:5],
            'activeTokensList': top_tokens
        })
        
    except Exception as e:
        logger.error(f"Erreur dashboard data: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({
            'stats': {
                'totalTokenAccounts': 0,
                'balanceChangesCount': 0, 
                'largeTransactionsCount': 0,
                'lastScanTime': 0,
                'totalTokens': 0
            },
            'topTokens': [],
            'newGems': [],
            'volumeAlerts': [],
            'activeTokensList': []
        }), 500

@app.route('/api/recent-balance-changes')
def get_recent_balance_changes():
    """API pour récupérer les balance changes récents"""
    limit = request.args.get('limit', 20, type=int)
    
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT signature, wallet_address, token_mint, token_symbol, token_name,
                   transaction_type, token_amount, amount, block_time, is_large_token_amount
            FROM transactions 
            WHERE is_token_transaction = 1 
            ORDER BY block_time DESC 
            LIMIT ?
        ''', (limit,))
        
        balance_changes = []
        for row in cursor.fetchall():
            balance_changes.append({
                'signature': row[0],
                'wallet_address': row[1],
                'token_mint': row[2],
                'token_symbol': row[3],
                'token_name': row[4],
                'transaction_type': row[5],
                'token_amount': row[6],
                'amount': row[7],
                'block_time': row[8],
                'is_large_token_amount': bool(row[9])
            })
        
        conn.close()
        return jsonify({'balance_changes': balance_changes})
        
    except Exception as e:
        logger.error(f"Erreur récupération balance changes: {e}")
        return jsonify({'balance_changes': []}), 500

def run_flask():
    """Lance le serveur Flask"""
    logger.info(f"🚀 Lancement du serveur Flask sur http://{Config.FLASK_HOST}:{Config.FLASK_PORT}")
    app.run(host=Config.FLASK_HOST, port=Config.FLASK_PORT, debug=Config.FLASK_DEBUG)

def main():
    """Point d'entrée principal"""
    monitor = SolanaWalletMonitor(WALLET_ADDRESSES, DB_NAME)
    
    # Lancer Flask dans un thread séparé
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Lancer la boucle de monitoring
    monitor.monitor_loop()

if __name__ == "__main__":
    main()