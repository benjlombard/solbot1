#!/usr/bin/env python3
"""
Analyseur de Token Solana - Optimisé pour l'ATA du token
Récupère le créateur et les transactions de l'ATA spécifique, exporte au format Solscan
"""
import sqlite3
from datetime import datetime, timedelta
import requests
import csv
import json
import time
import logging
from typing import Dict, List, Optional, Tuple
import os
import sqlite3
from pathlib import Path

# Configuration des logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('token_analyzer.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class TokenCreatorAnalyzer:
    def __init__(self, quicknode_endpoint: str = None):
        """
        Initialise l'analyseur avec la configuration QuickNode
        """
        if not quicknode_endpoint:
            logger.error("❌ ERREUR: Endpoint QuickNode requis!")
            logger.error("💡 Configurez votre endpoint QuickNode:")
            logger.error("   export QUICKNODE_ENDPOINT='https://your-endpoint.solana-mainnet.quiknode.pro/...'")
            logger.error("   ou passez-le en paramètre: TokenCreatorAnalyzer('https://...')")
            raise ValueError("Endpoint QuickNode requis pour éviter les rate limits")
        
        self.quicknode_endpoint = quicknode_endpoint
        self.rpc_endpoints = [quicknode_endpoint]
        self.current_rpc_index = 0
        self.request_count = 0
        self.token_cache = {}
        
        # Configuration rate limiting pour compte gratuit QuickNode
        self.rate_limit_delay = 0.5
        self.max_retries = 2
        self.retry_delay = 3
        self.requests_per_minute = 0
        self.last_minute_start = time.time()
        self.max_requests_per_minute = 120
        
        # ===== NOUVEAU: Initialisation du cache SQLite =====
        self.db_path = "token_creators_cache.db"
        self.transactions_db_path = "transactions_cache.db"
        self._init_database()
        self._init_transactions_database()

        logger.info(f"✅ Analyseur QuickNode initialisé")
        logger.info(f"🚀 Endpoint: {quicknode_endpoint[:50]}...")
        logger.info(f"⚡ Rate limit: {self.rate_limit_delay}s entre requêtes")
        logger.info(f"📊 Limite: {self.max_requests_per_minute} req/minute")
        logger.info(f"💾 Cache SQLite: {self.db_path}")


    def _init_database(self):
        """Initialise la base de données SQLite pour le cache des créateurs"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Créer la table si elle n'existe pas
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS token_creators (
                    token_address TEXT PRIMARY KEY,
                    creator_address TEXT NOT NULL,
                    discovery_method TEXT NOT NULL,
                    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_verified TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    verification_count INTEGER DEFAULT 1
                )
            ''')
            
            # Index pour optimiser les recherches
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_token_address ON token_creators(token_address)
            ''')
            
            conn.commit()
            conn.close()
            
            # Vérifier le nombre d'entrées en cache
            count = self._get_cache_count()
            logger.info(f"💾 Cache initialisé: {count} créateurs en mémoire")
            
        except Exception as e:
            logger.error(f"❌ Erreur initialisation cache SQLite: {e}")
            # Continuer sans cache en cas d'erreur
            self.db_path = None

    def _init_transactions_database(self):
        """Initialise la base de données SQLite pour le cache des transactions"""
        try:
            conn = sqlite3.connect(self.transactions_db_path)
            cursor = conn.cursor()
            
            # Table principale des transactions
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS transactions (
                    signature TEXT PRIMARY KEY,
                    wallet_address TEXT NOT NULL,
                    token_address TEXT,
                    block_time INTEGER,
                    slot INTEGER,
                    fee_lamports INTEGER,
                    sol_change REAL,
                    success BOOLEAN,
                    transaction_type TEXT,
                    raw_data TEXT,  -- JSON complet de la transaction
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    analysis_version TEXT DEFAULT '1.0'
                )
            ''')
            
            # Table des interactions entre wallets
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS wallet_interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signature TEXT,
                    from_wallet TEXT,
                    to_wallet TEXT,
                    amount_lamports INTEGER,
                    token_address TEXT,
                    interaction_type TEXT,  -- 'sol_transfer', 'token_transfer', 'swap', etc.
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (signature) REFERENCES transactions(signature)
                )
            ''')
            
            # Table des programmes utilisés
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS program_interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signature TEXT,
                    wallet_address TEXT,
                    program_id TEXT,
                    program_name TEXT,
                    instruction_type TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (signature) REFERENCES transactions(signature)
                )
            ''')
            
            # Table pour métriques ML
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ml_features (
                    wallet_address TEXT PRIMARY KEY,
                    analysis_date TIMESTAMP,
                    feature_vector TEXT,  -- JSON des features calculées
                    risk_score INTEGER,
                    profit_sol REAL,
                    activity_level TEXT,
                    labels TEXT,  -- JSON pour différents labels (scam, legitimate, etc.)
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Index pour performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_wallet_address ON transactions(wallet_address)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_token_address ON transactions(token_address)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_block_time ON transactions(block_time)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_from_to ON wallet_interactions(from_wallet, to_wallet)')
            
            conn.commit()
            conn.close()
            
            # Statistiques du cache
            stats = self._get_transaction_cache_stats()
            logger.info(f"💾 Cache transactions initialisé: {stats['total_transactions']} transactions")
            logger.info(f"   👥 {stats['unique_wallets']} wallets | 🪙 {stats['unique_tokens']} tokens")
            
        except Exception as e:
            logger.error(f"❌ Erreur initialisation cache transactions: {e}")
            self.transactions_db_path = None

    def _get_transaction_cache_stats(self) -> Dict:
        """Retourne les statistiques du cache des transactions"""
        if not self.transactions_db_path:
            return {"cache_enabled": False}
        
        try:
            conn = sqlite3.connect(self.transactions_db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM transactions")
            total_transactions = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(DISTINCT wallet_address) FROM transactions")
            unique_wallets = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(DISTINCT token_address) FROM transactions WHERE token_address IS NOT NULL")
            unique_tokens = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM transactions WHERE created_at > datetime('now', '-24 hours')")
            recent_transactions = cursor.fetchone()[0]
            
            conn.close()
            
            return {
                "cache_enabled": True,
                "total_transactions": total_transactions,
                "unique_wallets": unique_wallets,
                "unique_tokens": unique_tokens,
                "recent_transactions_24h": recent_transactions,
                "database_path": self.transactions_db_path
            }
            
        except Exception as e:
            return {"cache_enabled": False, "error": str(e)}

    def _get_cached_transactions(self, wallet_address: str, token_address: str = None, 
                           hours_back: int = 24) -> List[Dict]:
        """Récupère les transactions depuis le cache AVEC TOUTES LES DONNÉES"""
        if not self.transactions_db_path:
            return []
        
        try:
            conn = sqlite3.connect(self.transactions_db_path)
            cursor = conn.cursor()
            
            # Calculer la fenêtre temporelle
            cutoff_time = int(time.time()) - (hours_back * 3600)
            
            # Requête avec ou sans filtre token
            if token_address:
                cursor.execute('''
                    SELECT signature, block_time, fee_lamports, sol_change, success, 
                        transaction_type, raw_data, token_address
                    FROM transactions 
                    WHERE wallet_address = ? AND token_address = ? AND block_time >= ?
                    ORDER BY block_time DESC
                ''', (wallet_address, token_address, cutoff_time))
            else:
                cursor.execute('''
                    SELECT signature, block_time, fee_lamports, sol_change, success, 
                        transaction_type, raw_data, token_address
                    FROM transactions 
                    WHERE wallet_address = ? AND block_time >= ?
                    ORDER BY block_time DESC
                ''', (wallet_address, cutoff_time))
            
            rows = cursor.fetchall()
            conn.close()
            
            # Convertir en format attendu AVEC TOUTES LES DONNÉES
            cached_transactions = []
            for row in rows:
                tx = {
                    "signature": row[0],
                    "timestamp": row[1],
                    "fee": row[2] / 1e9 if row[2] else 0,
                    "sol_change": row[3] or 0,
                    "success": bool(row[4]),
                    "type": row[5] or "unknown",
                    "token_address": row[7],
                    "wallet_address": wallet_address  # ← AJOUTER pour les contreparties
                }
                
                # ===== NOUVEAU: Reconstituer TOUTES les données depuis raw_data =====
                if row[6]:  # raw_data
                    try:
                        raw_data = json.loads(row[6])
                        
                        # Ajouter toutes les données nécessaires
                        tx["raw_data"] = raw_data
                        
                        # Extraire account_keys, pre_balances, post_balances
                        if "raw_transaction" in raw_data:
                            raw_tx = raw_data["raw_transaction"]
                            tx["account_keys"] = raw_tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
                            tx["pre_balances"] = raw_tx.get("meta", {}).get("preBalances", [])
                            tx["post_balances"] = raw_tx.get("meta", {}).get("postBalances", [])
                            tx["programs"] = raw_data.get("programs", [])
                        else:
                            # Fallback si structure différente
                            tx["account_keys"] = raw_data.get("account_keys", [])
                            tx["pre_balances"] = raw_data.get("pre_balances", [])
                            tx["post_balances"] = raw_data.get("post_balances", [])
                            tx["programs"] = raw_data.get("programs", [])
                        
                        # Marquer que les données complètes sont disponibles
                        tx["has_complete_data"] = True
                        
                    except Exception as e:
                        logger.debug(f"Erreur parsing raw_data pour {row[0][:8]}...: {e}")
                        tx["has_complete_data"] = False
                else:
                    tx["has_complete_data"] = False
                
                cached_transactions.append(tx)
            
            # Log avec plus de détails
            complete_data_count = sum(1 for tx in cached_transactions if tx.get("has_complete_data", False))
            logger.info(f"💾 {len(cached_transactions)} transactions récupérées du cache")
            logger.info(f"   ✅ {complete_data_count} avec données complètes pour analyse avancée")
            
            return cached_transactions
            
        except Exception as e:
            logger.warning(f"⚠️ Erreur lecture cache transactions: {e}")
            return []

    def _save_transactions_to_cache(self, wallet_address: str, transactions: List[Dict], 
                               token_address: str = None):
        """Version améliorée - Sauvegarde avec détails complets structurés"""
        if not self.transactions_db_path or not transactions:
            return
        
        try:
            conn = sqlite3.connect(self.transactions_db_path)
            cursor = conn.cursor()
            
            saved_count = 0
            for tx in transactions:
                try:
                    signature = tx.get("signature", "")
                    
                    # Assurer que nous avons les données complètes de la transaction
                    if not tx.get("programs") or not tx.get("account_keys"):
                        logger.debug(f"   🔄 Récupération détails complets pour {signature[:8]}...")
                        tx_detail = self.rate_limited_rpc_call(
                            "getTransaction",
                            [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
                        )
                        
                        if tx_detail and tx_detail.get("result"):
                            tx_data = tx_detail["result"]
                            
                            # Extraire et structurer toutes les informations nécessaires
                            tx["raw_transaction"] = tx_data
                            tx["account_keys"] = tx_data.get("transaction", {}).get("message", {}).get("accountKeys", [])
                            tx["pre_balances"] = tx_data.get("meta", {}).get("preBalances", [])
                            tx["post_balances"] = tx_data.get("meta", {}).get("postBalances", [])
                            
                            # Extraire les programmes utilisés
                            programs = set()
                            instructions = tx_data.get("transaction", {}).get("message", {}).get("instructions", [])
                            for instruction in instructions:
                                if "programId" in instruction:
                                    programs.add(instruction["programId"])
                                elif isinstance(instruction.get("programIdIndex"), int):
                                    prog_index = instruction["programIdIndex"]
                                    account_keys = tx["account_keys"]
                                    if prog_index < len(account_keys):
                                        program_id = account_keys[prog_index]
                                        if isinstance(program_id, dict):
                                            program_id = program_id.get("pubkey", "")
                                        if program_id:
                                            programs.add(program_id)
                            
                            tx["programs"] = list(programs)
                    
                    # Préparer les données pour la sauvegarde
                    block_time = tx.get("timestamp", 0)
                    fee_lamports = int((tx.get("fee", 0)) * 1e9)
                    sol_change = tx.get("sol_change", 0)
                    success = tx.get("success", True)
                    tx_type = tx.get("type", "sol_transfer")
                    
                    # Créer une structure complète pour raw_data
                    complete_data = {
                        "signature": signature,
                        "timestamp": block_time,
                        "fee": tx.get("fee", 0),
                        "sol_change": sol_change,
                        "success": success,
                        "type": tx_type,
                        "account_keys": tx.get("account_keys", []),
                        "pre_balances": tx.get("pre_balances", []),
                        "post_balances": tx.get("post_balances", []),
                        "programs": tx.get("programs", []),
                        "raw_transaction": tx.get("raw_transaction", {}),
                        "wallet_address": wallet_address
                    }
                    
                    raw_data = json.dumps(complete_data, ensure_ascii=False)
                    
                    cursor.execute('''
                        INSERT OR REPLACE INTO transactions 
                        (signature, wallet_address, token_address, block_time, fee_lamports, 
                        sol_change, success, transaction_type, raw_data)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (signature, wallet_address, token_address, block_time, fee_lamports,
                        sol_change, success, tx_type, raw_data))
                    
                    if cursor.rowcount > 0:
                        saved_count += 1
                    
                except Exception as e:
                    logger.debug(f"Erreur sauvegarde transaction {signature[:8]}: {e}")
                    continue
            
            conn.commit()
            conn.close()
            
            logger.info(f"💾 {saved_count} transactions complètes sauvegardées avec données structurées")
            
        except Exception as e:
            logger.warning(f"⚠️ Erreur sauvegarde cache: {e}")

    def _save_ml_features(self, wallet_address: str, features: Dict, risk_score: int, 
                        profit_sol: float, labels: Dict = None):
        """Sauvegarde les features ML pour entraînement futur"""
        if not self.transactions_db_path:
            return
        
        try:
            conn = sqlite3.connect(self.transactions_db_path)
            cursor = conn.cursor()
            
            feature_vector = json.dumps(features)
            labels_json = json.dumps(labels or {})
            activity_level = features.get("activity_level", "unknown")
            
            cursor.execute('''
                INSERT OR REPLACE INTO ml_features 
                (wallet_address, analysis_date, feature_vector, risk_score, profit_sol, 
                activity_level, labels)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (wallet_address, datetime.now().isoformat(), feature_vector, 
                risk_score, profit_sol, activity_level, labels_json))
            
            conn.commit()
            conn.close()
            
            logger.info(f"🤖 Features ML sauvegardées pour {wallet_address[:8]}...")
            
        except Exception as e:
            logger.warning(f"⚠️ Erreur sauvegarde ML features: {e}")

    def export_ml_dataset(self, output_file: str = "ml_dataset.json") -> bool:
        """Exporte toutes les données pour entraînement ML"""
        if not self.transactions_db_path:
            return False
        
        try:
            conn = sqlite3.connect(self.transactions_db_path)
            cursor = conn.cursor()
            
            # Récupérer toutes les features ML
            cursor.execute('''
                SELECT wallet_address, analysis_date, feature_vector, risk_score, 
                    profit_sol, activity_level, labels
                FROM ml_features
                ORDER BY analysis_date DESC
            ''')
            
            ml_data = []
            for row in cursor.fetchall():
                try:
                    features = json.loads(row[2])
                    labels = json.loads(row[6]) if row[6] else {}
                    
                    record = {
                        "wallet_address": row[0],
                        "analysis_date": row[1],
                        "features": features,
                        "risk_score": row[3],
                        "profit_sol": row[4],
                        "activity_level": row[5],
                        "labels": labels
                    }
                    ml_data.append(record)
                except:
                    continue
            
            conn.close()
            
            # Sauvegarder en JSON
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "export_date": datetime.now().isoformat(),
                    "total_records": len(ml_data),
                    "data": ml_data
                }, f, indent=2, ensure_ascii=False)
            
            logger.info(f"🤖 Dataset ML exporté: {len(ml_data)} records → {output_file}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Erreur export ML dataset: {e}")
            return False

    def _get_cache_count(self) -> int:
        """Retourne le nombre d'entrées dans le cache"""
        if not self.db_path:
            return 0
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM token_creators")
            count = cursor.fetchone()[0]
            conn.close()
            return count
        except:
            return 0

    def _get_creator_from_cache(self, token_address: str) -> Optional[str]:
        """Récupère le créateur depuis le cache SQLite"""
        if not self.db_path:
            return None
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT creator_address, discovery_method, discovered_at 
                FROM token_creators 
                WHERE token_address = ?
            ''', (token_address,))
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                creator_address, method, discovered_at = result
                logger.info(f"💾 Créateur trouvé en cache: {creator_address}")
                logger.info(f"   📅 Découvert le: {discovered_at}")
                logger.info(f"   🔍 Méthode: {method}")
                
                # Mettre à jour le compteur de vérification
                self._update_verification_count(token_address)
                
                return creator_address
            
            return None
            
        except Exception as e:
            logger.warning(f"⚠️ Erreur lecture cache: {e}")
            return None

    def _save_creator_to_cache(self, token_address: str, creator_address: str, discovery_method: str):
        """Sauvegarde le créateur dans le cache SQLite"""
        if not self.db_path:
            return
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Utiliser INSERT OR REPLACE pour gérer les doublons
            cursor.execute('''
                INSERT OR REPLACE INTO token_creators 
                (token_address, creator_address, discovery_method, discovered_at, last_verified, verification_count)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 
                        COALESCE((SELECT verification_count FROM token_creators WHERE token_address = ?), 0) + 1)
            ''', (token_address, creator_address, discovery_method, token_address))
            
            conn.commit()
            conn.close()
            
            logger.info(f"💾 Créateur sauvegardé en cache")
            logger.info(f"   🪙 Token: {token_address}")
            logger.info(f"   👤 Créateur: {creator_address}")
            logger.info(f"   🔍 Méthode: {discovery_method}")
            
        except Exception as e:
            logger.warning(f"⚠️ Erreur sauvegarde cache: {e}")

    def _update_verification_count(self, token_address: str):
        """Met à jour le compteur de vérifications pour un token"""
        if not self.db_path:
            return
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                UPDATE token_creators 
                SET last_verified = CURRENT_TIMESTAMP, 
                    verification_count = verification_count + 1
                WHERE token_address = ?
            ''', (token_address,))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.debug(f"Erreur mise à jour compteur: {e}")

    def _clear_cache(self, confirm: bool = False):
        """Vide complètement le cache (à utiliser avec précaution)"""
        if not self.db_path or not confirm:
            return
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM token_creators")
            conn.commit()
            conn.close()
            logger.info("🗑️ Cache vidé complètement")
        except Exception as e:
            logger.error(f"❌ Erreur vidage cache: {e}")

    def get_cache_stats(self) -> Dict:
        """Retourne les statistiques du cache"""
        if not self.db_path:
            return {"cache_enabled": False}
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Nombre total d'entrées
            cursor.execute("SELECT COUNT(*) FROM token_creators")
            total_count = cursor.fetchone()[0]
            
            # Méthodes de découverte
            cursor.execute("""
                SELECT discovery_method, COUNT(*) 
                FROM token_creators 
                GROUP BY discovery_method 
                ORDER BY COUNT(*) DESC
            """)
            methods = cursor.fetchall()
            
            # Entrées récentes (dernières 24h)
            cursor.execute("""
                SELECT COUNT(*) FROM token_creators 
                WHERE discovered_at > datetime('now', '-1 day')
            """)
            recent_count = cursor.fetchone()[0]
            
            conn.close()
            
            return {
                "cache_enabled": True,
                "total_entries": total_count,
                "recent_entries_24h": recent_count,
                "discovery_methods": dict(methods),
                "database_path": self.db_path
            }
            
        except Exception as e:
            logger.error(f"❌ Erreur stats cache: {e}")
            return {"cache_enabled": False, "error": str(e)}

    def rate_limited_rpc_call(self, method: str, params: List) -> Optional[Dict]:
        """Appel RPC avec gestion du rate limit strict pour QuickNode gratuit"""
        current_time = time.time()
        if current_time - self.last_minute_start >= 60:
            self.requests_per_minute = 0
            self.last_minute_start = current_time
        
        if self.requests_per_minute >= self.max_requests_per_minute:
            wait_time = 60 - (current_time - self.last_minute_start)
            if wait_time > 0:
                logger.warning(f"⏳ Limite QuickNode atteinte, pause de {wait_time:.1f}s...")
                time.sleep(wait_time)
                self.requests_per_minute = 0
                self.last_minute_start = current_time
        
        self.request_count += 1
        self.requests_per_minute += 1
        
        if self.request_count % 10 == 0:
            logger.info(f"📊 Requêtes QuickNode: {self.request_count} total, {self.requests_per_minute}/min")
        
        result = self._solana_rpc_call(method, params)
        time.sleep(self.rate_limit_delay)
        return result

    def _solana_rpc_call(self, method: str, params: List) -> Optional[Dict]:
        """Effectue un appel RPC uniquement vers QuickNode"""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params
        }

        for attempt in range(self.max_retries):
            try:
                headers = {
                    'Content-Type': 'application/json',
                    'User-Agent': 'TokenCreatorAnalyzer/1.0-QuickNode',
                    'Accept': 'application/json',
                }
                
                response = requests.post(
                    self.quicknode_endpoint,
                    json=payload,
                    timeout=20,
                    headers=headers
                )

                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 10))
                    logger.warning(f"⚠️ Rate limit QuickNode, attente {retry_after}s...")
                    time.sleep(retry_after)
                    continue
                elif response.status_code == 403:
                    logger.error(f"❌ Accès refusé QuickNode - vérifiez votre endpoint")
                    logger.error(f"💡 URL utilisée: {self.quicknode_endpoint[:50]}...")
                    return None
                else:
                    logger.error(f"❌ Erreur HTTP {response.status_code}: {response.text[:100]}")
                    response.raise_for_status()

            except requests.exceptions.Timeout:
                logger.warning(f"⏰ Timeout QuickNode (tentative {attempt + 1}/{self.max_retries})")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
            except requests.exceptions.ConnectionError as e:
                logger.error(f"🔌 Erreur de connexion QuickNode: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
            except requests.RequestException as e:
                logger.error(f"❌ Erreur requête QuickNode: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))

        logger.error("❌ Échec de toutes les tentatives vers QuickNode")
        return None

    def find_token_creator(self, token_address: str, exhaustive_search: bool = True, max_signatures: int = None, force_refresh: bool = False) -> Optional[str]:
        """
        Trouve le créateur d'un token avec logique de priorité :
        0. Cache SQLite (si pas force_refresh)
        1. Recherche dans l'historique des transactions (limitée ou exhaustive)
        2. UpdateAuthority via métadonnées (plus fiable)
        3. Mint Authority actuelle 
        4. Recherche via Solscan API
        
        Args:
            token_address: L'adresse du token à analyser
            exhaustive_search: Si True, recherche dans TOUTES les transactions
            max_signatures: Limite optionnelle pour la recherche exhaustive
            force_refresh: Si True, ignore le cache et force la recherche
        """
        logger.info(f"🔍 Recherche du créateur pour le token: {token_address}")
        # PRIORITÉ 0: Vérifier le cache SQLite d'abord
        if not force_refresh:
            logger.info("💾 PRIORITÉ 0: Vérification du cache SQLite...")
            cached_creator = self._get_creator_from_cache(token_address)
            if cached_creator:
                logger.info(f"✅ Créateur trouvé en cache: {cached_creator}")
                return cached_creator
            logger.info("   ⚪ Aucun créateur en cache, recherche nécessaire...")
        else:
            logger.info("🔄 Mode force_refresh: cache ignoré")
        
        logger.info("📋 Logique de priorité (recherche active):")
        logger.info("   1️⃣ Historique des transactions")  # ← CORRIGÉ
        logger.info("   2️⃣ UpdateAuthority via métadonnées")  # ← CORRIGÉ
        logger.info("   3️⃣ Mint Authority actuelle")  # ← CORRIGÉ
        logger.info("   4️⃣ Recherche via Solscan API")  # ← CORRIGÉ
        
        if exhaustive_search:
            limit_msg = f" (limite: {max_signatures})" if max_signatures else " (TOUTES)"
            logger.info(f"   4️⃣ Historique EXHAUSTIF des transactions{limit_msg}")
        else:
            logger.info("   4️⃣ Historique des 10 premières transactions")
        
        logger.info("-" * 60)
        
        creator = None
        discovery_method = None


        if exhaustive_search:
            logger.info("🔍 PRIORITÉ 4: Recherche EXHAUSTIVE dans l'historique...")
            creator = self._find_creator_via_transaction_history(token_address, max_signatures)
            discovery_method = f"transaction_history_exhaustive_{max_signatures or 'all'}"
        else:
            logger.info("🔍 PRIORITÉ 4: Recherche dans les 10 premières transactions...")
            creator = self._find_creator_via_transaction_history(token_address, 10)
            discovery_method = "transaction_history_limited_10"
        
        if creator:
            search_type = "exhaustive" if exhaustive_search else "limitée"
            logger.info(f"✅ Créateur trouvé via recherche {search_type}: {creator}")
            self._save_creator_to_cache(token_address, creator, discovery_method)
            return creator

        # PRIORITÉ 2: UpdateAuthority via métadonnées
        logger.info("🎯 PRIORITÉ 2: Recherche de l'UpdateAuthority...")
        creator = self._get_update_authority_from_metadata(token_address)
        if creator:
            discovery_method = "metadata_update_authority"
            logger.info(f"✅ Créateur trouvé via UpdateAuthority: {creator}")
            self._save_creator_to_cache(token_address, creator, discovery_method)
            return creator
        
        # PRIORITÉ 3: Mint Authority actuelle
        logger.info("🔄 PRIORITÉ 3: Recherche de la Mint Authority actuelle...")
        creator = self._get_mint_authority_from_account_info(token_address)
        if creator and creator.lower() != "none":
            discovery_method = "current_mint_authority"
            logger.info(f"✅ Créateur trouvé via Mint Authority: {creator}")
            self._save_creator_to_cache(token_address, creator, discovery_method)
            return creator
        
        # PRIORITÉ 4: Solscan API
        logger.info("🔄 PRIORITÉ 4: Recherche via Solscan API...")
        creator = self._find_creator_via_solscan(token_address)
        if creator:
            discovery_method = "solscan_api"
            logger.info(f"✅ Créateur trouvé via Solscan: {creator}")
            self._save_creator_to_cache(token_address, creator, discovery_method)
            return creator

        logger.error("❌ Impossible de trouver le créateur du token")
        return None

    def _get_update_authority_from_metadata(self, token_address: str) -> Optional[str]:
        """
        PRIORITÉ 1: Récupère l'updateAuthority depuis les métadonnées du token
        """
        try:
            logger.info("   🔍 Recherche des métadonnées du token...")
            
            # Program ID du Metaplex Token Metadata
            metadata_program_id = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"
            
            # Utiliser getProgramAccounts pour trouver les métadonnées
            accounts_result = self.rate_limited_rpc_call(
                "getProgramAccounts",
                [
                    metadata_program_id,
                    {
                        "encoding": "base64",
                        "filters": [
                            {
                                "memcmp": {
                                    "offset": 33,  # Position du mint address dans la structure
                                    "bytes": token_address
                                }
                            }
                        ]
                    }
                ]
            )
            
            if not accounts_result or not accounts_result.get("result"):
                logger.info("   ⚠️ Aucun compte de métadonnées trouvé")
                return None
            
            accounts = accounts_result["result"]
            logger.info(f"   📊 Trouvé {len(accounts)} compte(s) de métadonnées")
            
            if not accounts:
                return None
            
            # Analyser le premier compte de métadonnées
            metadata_account = accounts[0]
            account_data = metadata_account["account"]["data"]
            
            if isinstance(account_data, list) and len(account_data) > 0:
                update_authority = self._parse_update_authority_from_metadata(account_data[0])
                if update_authority:
                    logger.info(f"   ✅ UpdateAuthority extrait: {update_authority}")
                    return update_authority
            
            logger.info("   ❌ UpdateAuthority non trouvé dans les métadonnées")
            return None
            
        except Exception as e:
            logger.info(f"   ❌ Erreur lors de la récupération des métadonnées: {e}")
            return None

    def _parse_update_authority_from_metadata(self, account_data_b64: str) -> Optional[str]:
        """
        Parse les données des métadonnées pour extraire l'updateAuthority
        Structure Metaplex: [key:1][updateAuthority:32][mint:32][name_len:4][name][...]
        """
        try:
            import base64
            import base58
            
            # Décoder les données base64
            data = base64.b64decode(account_data_b64)
            logger.info(f"   📄 Taille des données: {len(data)} bytes")
            
            if len(data) < 33:  # Minimum : key (1) + updateAuthority (32)
                logger.info("   ❌ Données trop courtes pour contenir updateAuthority")
                return None
            
            # Structure des métadonnées Metaplex :
            # Byte 0: Key (toujours 4 pour Metadata)
            # Bytes 1-32: UpdateAuthority (32 bytes)
            # Bytes 33-64: Mint (32 bytes)
            
            key = data[0]
            logger.info(f"   🔑 Key: {key} (devrait être 4 pour Metadata)")
            
            if key != 4:
                logger.info(f"   ❌ Key incorrect: {key} (attendu: 4)")
                return None
            
            # Extraire l'updateAuthority (bytes 1-32)
            update_authority_bytes = data[1:33]
            update_authority = base58.b58encode(update_authority_bytes).decode('utf-8')
            
            logger.info(f"   🎯 UpdateAuthority brut: {update_authority}")
            
            # Vérifier que ce n'est pas une adresse nulle
            null_address = "11111111111111111111111111111111"
            if update_authority == null_address:
                logger.info("   ⚠️ UpdateAuthority est null (révoqué)")
                return None
            
            return update_authority
            
        except Exception as e:
            logger.info(f"   ❌ Erreur parsing métadonnées: {e}")
            return None

    def _find_creator_via_transaction_history(self, token_address: str, max_signatures: int = None) -> Optional[str]:
        """
        PRIORITÉ 3: Recherche EXHAUSTIVE dans TOUTES les transactions
        Args:
            token_address: L'adresse du token
            max_signatures: Limite optionnelle (None = toutes les transactions)
        """
        try:
            logger.info("   🔍 Recherche EXHAUSTIVE dans TOUTES les transactions...")
            
            all_signatures = []
            before = None
            batch_size = 100  # Maximum autorisé par Solana RPC
            total_batches = 0
            
            # Récupérer TOUTES les signatures par batch
            while True:
                logger.info(f"   📦 Récupération du batch {total_batches + 1}...")
                
                params = [token_address, {"limit": batch_size}]
                if before:
                    params[1]["before"] = before
                
                signatures_result = self.rate_limited_rpc_call("getSignaturesForAddress", params)
                
                if not signatures_result or "result" not in signatures_result:
                    logger.warning(f"   ⚠️ Échec récupération batch {total_batches + 1}")
                    break
                
                batch_signatures = signatures_result["result"]
                
                if not batch_signatures:
                    logger.info("   ✅ Fin des signatures atteinte")
                    break
                
                all_signatures.extend(batch_signatures)
                total_batches += 1
                before = batch_signatures[-1]["signature"]
                
                logger.info(f"   📊 Batch {total_batches}: {len(batch_signatures)} signatures (+{len(all_signatures)} total)")
                
                # Limitation optionnelle
                if max_signatures and len(all_signatures) >= max_signatures:
                    all_signatures = all_signatures[:max_signatures]
                    logger.info(f"   🛑 Limitation appliquée: {max_signatures} signatures")
                    break
                
                # Éviter les boucles infinites avec une limite raisonnable
                if total_batches >= 50:  # ~50k transactions max
                    logger.warning(f"   ⚠️ Limite de sécurité atteinte: {total_batches} batches")
                    break
            
            logger.info(f"   📊 Total récupéré: {len(all_signatures)} signatures sur {total_batches} batches")
            
            if not all_signatures:
                logger.info("   ❌ Aucune signature trouvée")
                return None
            
            # Analyser du plus ancien au plus récent
            logger.info("   🔍 Analyse des transactions (du plus ancien au plus récent)...")
            
            for i, sig_info in enumerate(reversed(all_signatures)):
                if i % 100 == 0:  # Log de progression tous les 100
                    progress = (i / len(all_signatures)) * 100
                    logger.info(f"   📈 Progression: {i}/{len(all_signatures)} ({progress:.1f}%)")
                
                signature = sig_info["signature"]
                creator = self._analyze_single_transaction(signature, token_address)
                
                if creator:
                    logger.info(f"   ✅ Créateur trouvé dans transaction {i+1}/{len(all_signatures)}: {signature}")
                    logger.info(f"   🎯 Position: {len(all_signatures) - i} transactions depuis la fin")
                    return creator
            
            logger.info(f"   ❌ Créateur non trouvé dans les {len(all_signatures)} transactions analysées")
            return None
            
        except Exception as e:
            logger.info(f"   ❌ Erreur analyse exhaustive: {e}")
            return None

    def _find_creator_via_transaction_history_limited(self, token_address: str) -> Optional[str]:
        """
        Version limitée de la recherche (10 transactions) - fonction originale
        """
        try:
            logger.info("   🔍 Récupération des 10 transactions les plus anciennes...")
            
            signatures_result = self.rate_limited_rpc_call(
                "getSignaturesForAddress",
                [token_address, {"limit": 10}]
            )
            
            if not signatures_result or "result" not in signatures_result:
                logger.info("   ❌ Impossible de récupérer l'historique")
                return None
            
            signatures = signatures_result["result"]
            logger.info(f"   📊 Analyse de {len(signatures)} transactions anciennes...")
            
            for sig_info in reversed(signatures):  # Analyser du plus ancien au plus récent
                signature = sig_info["signature"]
                
                creator = self._analyze_single_transaction(signature, token_address)
                if creator:
                    logger.info(f"   ✅ Créateur trouvé dans transaction: {signature}")
                    return creator
            
            logger.info("   ❌ Créateur non trouvé dans les 10 premières transactions")
            return None
            
        except Exception as e:
            logger.info(f"   ❌ Erreur analyse limitée: {e}")
            return None

    def _analyze_single_transaction(self, signature: str, token_address: str) -> Optional[str]:
        """
        Analyse une transaction pour trouver initializeMint
        """
        try:
            tx_details = self.rate_limited_rpc_call(
                "getTransaction",
                [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
            )
            
            if not tx_details or not tx_details.get("result"):
                return None
            
            tx = tx_details["result"]
            
            # Ignorer les transactions échouées
            if tx.get("meta", {}).get("err"):
                return None
            
            # Chercher initializeMint dans les instructions principales
            instructions = tx.get("transaction", {}).get("message", {}).get("instructions", [])
            
            for instruction in instructions:
                creator = self._check_instruction_for_initialize_mint(instruction, token_address)
                if creator:
                    return creator
            
            # Chercher dans les inner instructions
            meta = tx.get("meta", {})
            inner_instructions = meta.get("innerInstructions", [])
            
            for inner_group in inner_instructions:
                for inner_instruction in inner_group.get("instructions", []):
                    creator = self._check_instruction_for_initialize_mint(inner_instruction, token_address)
                    if creator:
                        return creator
            
            return None
            
        except Exception as e:
            return None

    def _check_instruction_for_initialize_mint(self, instruction: dict, token_address: str) -> Optional[str]:
        """
        Vérifie si une instruction est initializeMint pour notre token
        """
        try:
            if not isinstance(instruction.get("parsed"), dict):
                return None
            
            parsed = instruction["parsed"]
            instruction_type = parsed.get("type")
            
            if instruction_type in ["initializeMint", "initializeMint2"]:
                info = parsed.get("info", {})
                mint = info.get("mint")
                mint_authority = info.get("mintAuthority")
                
                if mint == token_address and mint_authority:
                    logger.info(f"      🎯 InitializeMint trouvé!")
                    logger.info(f"         Mint: {mint}")
                    logger.info(f"         Authority: {mint_authority}")
                    return mint_authority
            
            return None
            
        except Exception as e:
            return None

    def _get_mint_authority_from_account_info(self, token_address: str) -> Optional[str]:
        """
        PRIORITÉ 2: Récupère la mint authority actuelle (méthode existante améliorée)
        """
        try:
            logger.info("   🔍 Récupération des informations du mint...")
            
            account_info = self.rate_limited_rpc_call(
                "getAccountInfo",
                [token_address, {"encoding": "jsonParsed"}]
            )
            
            if not account_info or not account_info.get("result"):
                logger.info("   ❌ Impossible de récupérer les informations du mint")
                return None
            
            result = account_info["result"]
            data = result.get("value", {}).get("data", {})
            
            if isinstance(data, dict) and data.get("parsed"):
                parsed_info = data["parsed"]["info"]
                mint_authority = parsed_info.get("mintAuthority")
                
                logger.info(f"   📋 Informations du mint:")
                logger.info(f"      🔢 Decimals: {parsed_info.get('decimals', 'N/A')}")
                logger.info(f"      🏦 Supply: {parsed_info.get('supply', 'N/A')}")
                logger.info(f"      👤 Mint Authority: {mint_authority or 'None'}")
                logger.info(f"      🔐 Freeze Authority: {parsed_info.get('freezeAuthority', 'None')}")
                
                if mint_authority:
                    logger.info(f"   ✅ Mint authority active: {mint_authority}")
                    return mint_authority
                else:
                    logger.info("   ⚠️ Mint authority = None (token renoncé)")
                    return None
            else:
                logger.info("   ❌ Données du mint non parsées")
                return None
                
        except Exception as e:
            logger.info(f"   ❌ Erreur récupération mint authority: {e}")
            return None

    def get_token_ata(self, creator_address: str, token_address: str) -> Optional[str]:
        """
        Récupère l'ATA du créateur pour un token spécifique
        """
        logger.info(f"🔍 Recherche de l'ATA pour {creator_address[:8]}... et token {token_address[:8]}...")
        
        token_accounts_result = self.rate_limited_rpc_call(
            "getTokenAccountsByOwner",
            [
                creator_address,
                {"mint": token_address},
                {"encoding": "jsonParsed"}
            ]
        )

        if not token_accounts_result or "result" not in token_accounts_result:
            logger.error(f"❌ Impossible de récupérer l'ATA pour {token_address}")
            return None

        accounts = token_accounts_result["result"]["value"]
        if not accounts:
            logger.warning(f"⚠️ Aucun ATA trouvé pour {token_address}")
            return None

        ata_pubkey = accounts[0]["pubkey"]
        logger.info(f"✅ ATA trouvé: {ata_pubkey}")
        return ata_pubkey

    def scan_ata_transactions(self, ata_pubkey: str, token_address: str, hours_back: int = 24, max_transactions: int = None) -> List[Dict]:
        """
        Scanne les transactions de l'ATA spécifique pour le token
        """
        logger.info(f"🔍 Scan des transactions de l'ATA {ata_pubkey[:8]}... pour {token_address[:8]}... (dernières {hours_back}h)")
        
        current_time = int(time.time())
        scan_window = hours_back * 3600
        
        limit = 1000 if max_transactions is None else min(max_transactions + 50, 1000)
        signatures_result = self.rate_limited_rpc_call(
            "getSignaturesForAddress",
            [ata_pubkey, {"limit": limit, "commitment": "finalized"}]
        )

        if not signatures_result or "result" not in signatures_result:
            logger.error("❌ Impossible de récupérer les signatures de l'ATA")
            return []

        recent_signatures = [
            sig for sig in signatures_result["result"]
            if sig.get("blockTime") and sig["blockTime"] >= (current_time - scan_window)
        ]

        logger.info(f"📊 {len(recent_signatures)} signatures dans la période de {hours_back}h")
        
        if max_transactions is not None and len(recent_signatures) > max_transactions:
            logger.info(f"⚠️ Limitation appliquée: {max_transactions} transactions sur {len(recent_signatures)}")
            recent_signatures = recent_signatures[:max_transactions]

        balance_changes = []
        processed_signatures = set()
        transactions_with_changes = 0

        total_signatures = len(recent_signatures)
        for i, sig_info in enumerate(recent_signatures):
            if i % 5 == 0 or i == total_signatures - 1:
                progress = (i + 1) / total_signatures * 100
                logger.info(f"📈 Progression: {i + 1}/{total_signatures} ({progress:.1f}%) - "
                           f"Balance changes trouvés: {len(balance_changes)}")

            signature = sig_info["signature"]
            if signature in processed_signatures:
                continue
            processed_signatures.add(signature)

            tx_detail = self.rate_limited_rpc_call(
                "getTransaction",
                [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
            )

            if not tx_detail or not tx_detail.get("result"):
                logger.debug(f"⚠️ Transaction {signature[:8]}... ignorée (pas de détails)")
                continue

            balance_change_txs = self._analyze_ata_transaction(
                tx_detail, ata_pubkey, token_address, sig_info
            )
            
            if balance_change_txs:
                balance_changes.extend(balance_change_txs)
                transactions_with_changes += 1
                logger.info(f"✅ {len(balance_change_txs)} balance changes dans {signature[:8]}...")
            else:
                logger.debug(f"⚪ Pas de balance change dans {signature[:8]}...")

        logger.info(f"✅ Scan terminé:")
        logger.info(f"   📊 Transactions analysées: {len(processed_signatures)}")
        logger.info(f"   💰 Transactions avec balance changes: {transactions_with_changes}")
        logger.info(f"   🎯 Total balance changes: {len(balance_changes)}")
        return balance_changes

    def _analyze_ata_transaction(self, tx_detail: Dict, ata_pubkey: str, token_address: str, sig_info: Dict) -> List[Dict]:
        """
        Analyse une transaction de l'ATA pour extraire les balance changes
        """
        try:
            tx = tx_detail["result"]
            meta = tx.get("meta", {})
            balance_changes = []
            signature = sig_info["signature"]
            
            pre_token_balances = meta.get("preTokenBalances", [])
            post_token_balances = meta.get("postTokenBalances", [])
            fee = meta.get("fee", 0) / 1e9
            
            for pre_balance in pre_token_balances:
                if pre_balance.get("mint") == token_address and pre_balance.get("accountIndex") < len(tx.get("transaction", {}).get("message", {}).get("accountKeys", [])):
                    owner = pre_balance.get("owner")
                    pre_amount = float(pre_balance.get("uiTokenAmount", {}).get("uiAmount") or 0)
                    decimals = pre_balance.get("uiTokenAmount", {}).get("decimals", 9)
                    for post_balance in post_token_balances:
                        if post_balance.get("mint") == token_address and post_balance.get("accountIndex") == pre_balance.get("accountIndex"):
                            post_amount = float(post_balance.get("uiTokenAmount", {}).get("uiAmount") or 0)
                            amount_change = post_amount - pre_amount
                            if abs(amount_change) > 0.0000001:
                                change_type = "inc" if amount_change > 0 else "dec"
                                balance_change = {
                                    "Txhash": signature,
                                    "BlockTimeUnix": sig_info.get("blockTime", 0),
                                    "BlockTime": datetime.fromtimestamp(sig_info.get("blockTime", 0)).strftime('%Y-%m-%dT%H:%M:%S') if sig_info.get("blockTime") else "",
                                    "Fee(SOL)": fee,
                                    "TokenAccount": owner,
                                    "ChangeType": change_type,
                                    "ChangeAmount": int(abs(amount_change) * (10 ** decimals)),
                                    "PreBalancer": int(pre_amount * (10 ** decimals)),
                                    "PostBalancer": int(post_amount * (10 ** decimals)),
                                    "TokenAddress": token_address,
                                    "TokenDecimals": decimals,
                                    "TokenMultiplier": 1.0
                                }
                                balance_changes.append(balance_change)
                                logger.debug(f"✅ Token change: {change_type.upper()} {abs(amount_change):,.4f}")
                            break
            
            return balance_changes

        except Exception as e:
            logger.error(f"❌ Erreur analyse transaction {signature[:10]}...: {e}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")
            return []

    def export_to_csv(self, data: List[Dict], filename: str):
        """Exporte les données vers un fichier CSV au format Solscan"""
        if not data:
            logger.warning("⚠️ Aucune donnée à exporter")
            return
        
        fieldnames = [
            'Txhash', 'BlockTimeUnix', 'BlockTime', 'Fee(SOL)', 'TokenAccount', 
            'ChangeType', 'ChangeAmount', 'PreBalancer', 'PostBalancer', 
            'TokenAddress', 'TokenDecimals', 'TokenMultiplier'
        ]
        
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)
        
        logger.info(f"✅ Données exportées au format Solscan vers {filename}")
        logger.info(f"📊 Format: {len(data)} lignes avec colonnes Solscan standard")

    def _find_creator_via_solscan(self, token_address: str) -> Optional[str]:
        """
        Utilise l'API Solscan pour trouver la transaction initializeMint
        """
        try:
            logger.info("   🔍 Recherche via Solscan API...")
            solscan_url = f"https://public-api.solscan.io/token/transfers/{token_address}"
            headers = {"Accept": "application/json"}
            
            response = requests.get(solscan_url, headers=headers, timeout=10)
            if response.status_code != 200:
                logger.info(f"   ❌ Erreur Solscan API: {response.status_code}")
                return None
            
            transactions = response.json().get("transactions", [])
            if not transactions:
                logger.info("   ❌ Aucune transaction trouvée via Solscan")
                return None
            
            # Prendre la transaction la plus ancienne (dernière dans la liste)
            oldest_tx = transactions[-1]
            tx_hash = oldest_tx.get("txHash")
            
            # Récupérer les détails de la transaction
            tx_details_url = f"https://public-api.solscan.io/transaction/{tx_hash}"
            response = requests.get(tx_details_url, headers=headers, timeout=10)
            if response.status_code != 200:
                logger.info(f"   ❌ Erreur détails transaction: {response.status_code}")
                return None
            
            tx_details = response.json()
            for instruction in tx_details.get("innerInstructions", []):
                for inner in instruction.get("parsedInstructions", []):
                    if inner.get("type") == "initializeMint" and inner.get("params", {}).get("mint") == token_address:
                        mint_authority = inner.get("params", {}).get("mintAuthority")
                        if mint_authority:
                            logger.info(f"   ✅ Créateur trouvé via Solscan: {mint_authority}")
                            return mint_authority
            
            logger.info("   ❌ Créateur non trouvé via Solscan")
            return None
        
        except Exception as e:
            logger.info(f"   ❌ Erreur Solscan API: {e}")
            return None


    def analyze_wallet_complete(self, wallet_address: str, days_back: int = 30, token_address: str = None) -> Dict:
        """
        Analyse complète d'un wallet avec rapport détaillé
        """
        logger.info("=" * 80)
        logger.info(f"🔬 ANALYSE COMPLÈTE DU WALLET {wallet_address[:8]}...")
        logger.info(f"⏰ Période d'analyse: {days_back} jours")
        logger.info("=" * 80)
        
        analysis_start = time.time()
        
        # 1. Informations de base du wallet
        logger.info("\n🏦 ÉTAPE 1: INFORMATIONS DE BASE")
        logger.info("-" * 50)
        wallet_info = self._get_wallet_basic_info(wallet_address)
        
        # 2. Analyse des tokens détenus
        logger.info("\n🪙 ÉTAPE 2: ANALYSE DES TOKENS")
        logger.info("-" * 50)
        tokens_analysis = self._analyze_wallet_tokens(wallet_address)
        
        # 3. Analyse des transactions SOL
        logger.info("\n💰 ÉTAPE 3: TRANSACTIONS SOL")
        logger.info("-" * 50)
        sol_analysis = self._analyze_sol_transactions(wallet_address, days_back)
        
        # 4. Analyse des transactions de tokens
        logger.info("\n🔄 ÉTAPE 4: TRANSACTIONS DE TOKENS")
        logger.info("-" * 50)
        token_tx_analysis = self._analyze_token_transactions(wallet_address, days_back)
        
        # 5. Analyse des patterns de trading
        logger.info("\n📊 ÉTAPE 5: PATTERNS DE TRADING")
        logger.info("-" * 50)
        trading_patterns = self._analyze_trading_patterns(sol_analysis, token_tx_analysis)
        
        # 6. Génération du rapport
        analysis_duration = time.time() - analysis_start
        report = self._generate_wallet_report(
            wallet_address, wallet_info, tokens_analysis, 
            sol_analysis, token_tx_analysis, trading_patterns, 
            analysis_duration, days_back, token_address
        )
        
        return report

    def _get_wallet_basic_info(self, wallet_address: str) -> Dict:
        """Récupère les informations de base du wallet"""
        logger.info("   🔍 Récupération des informations de base...")
        
        # Balance SOL
        balance_result = self.rate_limited_rpc_call("getBalance", [wallet_address])
        sol_balance = balance_result["result"]["value"] / 1e9 if balance_result else 0
        
        # Informations du compte
        account_info = self.rate_limited_rpc_call("getAccountInfo", [wallet_address])
        is_program = False
        if account_info and account_info.get("result", {}).get("value"):
            account_data = account_info["result"]["value"]
            is_program = account_data.get("executable", False)
        
        logger.info(f"   💰 Balance SOL: {sol_balance:.4f}")
        logger.info(f"   🔧 Type: {'Programme' if is_program else 'Wallet normal'}")
        
        return {
            "address": wallet_address,
            "sol_balance": sol_balance,
            "is_program": is_program,
            "analysis_timestamp": datetime.now().isoformat()
        }

    def _analyze_wallet_tokens(self, wallet_address: str) -> Dict:
        """Analyse tous les tokens détenus par le wallet"""
        logger.info("   🔍 Récupération des tokens détenus...")
        
        # Récupérer tous les token accounts
        token_accounts_result = self.rate_limited_rpc_call(
            "getTokenAccountsByOwner",
            [wallet_address, {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}, {"encoding": "jsonParsed"}]
        )
        
        if not token_accounts_result or "result" not in token_accounts_result:
            logger.warning("   ⚠️ Impossible de récupérer les token accounts")
            return {"tokens": [], "total_tokens": 0, "total_value_estimate": 0}
        
        token_accounts = token_accounts_result["result"]["value"]
        tokens_data = []
        total_tokens = len(token_accounts)
        
        logger.info(f"   📊 {total_tokens} token accounts trouvés")
        
        for i, account in enumerate(token_accounts):
            if i % 10 == 0:
                logger.info(f"   📈 Analyse tokens: {i+1}/{total_tokens}")
            
            parsed_info = account["account"]["data"]["parsed"]["info"]
            token_address = parsed_info["mint"]
            balance = float(parsed_info["tokenAmount"]["uiAmount"] or 0)
            decimals = parsed_info["tokenAmount"]["decimals"]
            
            if balance > 0:  # Seulement les tokens avec balance > 0
                token_info = {
                    "address": token_address,
                    "balance": balance,
                    "decimals": decimals,
                    "raw_balance": int(parsed_info["tokenAmount"]["amount"]),
                    "account": account["pubkey"]
                }
                tokens_data.append(token_info)
        
        # Trier par balance décroissante
        tokens_data.sort(key=lambda x: x["balance"], reverse=True)
        
        logger.info(f"   ✅ {len(tokens_data)} tokens avec balance > 0")
        
        return {
            "tokens": tokens_data,
            "total_tokens": len(tokens_data),
            "total_accounts": total_tokens
        }

    def _analyze_sol_transactions(self, wallet_address: str, days_back: int) -> Dict:
        """Analyse les transactions SOL du wallet"""
        logger.info("   🔍 Analyse des transactions SOL...")
        
        cached_transactions = self._get_cached_transactions(wallet_address, hours_back=days_back*24)
    
        if cached_transactions:
            logger.info(f"   💾 Utilisation du cache: {len(cached_transactions)} transactions")
            
            # Utiliser les données du cache
            sol_transfers = cached_transactions
            fees_total = sum(tx.get("fee", 0) for tx in cached_transactions)
            
            # Simuler program_interactions depuis le cache si nécessaire
            program_interactions = {}
            
            for tx in cached_transactions:
                if "raw_data" in tx and tx["raw_data"]:
                    try:
                        tx_data = json.loads(tx["raw_data"]) if isinstance(tx["raw_data"], str) else tx["raw_data"]
                        programs = tx_data.get("programs", [])
                        for program in programs:
                            program_interactions[program] = program_interactions.get(program, 0) + 1
                    except:
                        pass
            
            most_used_programs = sorted(program_interactions.items(), key=lambda x: x[1], reverse=True)[:10]

            return {
                "total_transactions": len(cached_transactions),
                "analyzed_sample": len(cached_transactions),
                "sol_transfers": sol_transfers,
                "total_fees": fees_total,
                "program_interactions": program_interactions,
                "most_used_programs": [],
                "from_cache": True  # Indicateur
            }

        # Si pas de cache, analyse normale + sauvegarde enrichie
        logger.info("   🔄 Pas de cache, analyse complète...")

        current_time = int(time.time())
        scan_window = days_back * 24 * 3600
        
        # Récupérer les signatures
        all_signatures = []
        before = None
        batch_size = 1000
        max_batches = 10  # Limiter pour éviter trop de requêtes
        
        for batch_num in range(max_batches):
            params = [wallet_address, {"limit": batch_size}]
            if before:
                params[1]["before"] = before
            
            signatures_result = self.rate_limited_rpc_call("getSignaturesForAddress", params)
            if not signatures_result or "result" not in signatures_result:
                break
            
            batch_signatures = signatures_result["result"]
            if not batch_signatures:
                break
            
            # Filtrer par période
            recent_sigs = [
                sig for sig in batch_signatures
                if sig.get("blockTime") and sig["blockTime"] >= (current_time - scan_window)
            ]
            
            all_signatures.extend(recent_sigs)
            before = batch_signatures[-1]["signature"]
            
            logger.info(f"   📦 Batch {batch_num + 1}: {len(recent_sigs)} signatures récentes")
            
            # Si pas de signatures récentes dans ce batch, arrêter
            if len(recent_sigs) == 0:
                break
        
        logger.info(f"   📊 Total: {len(all_signatures)} transactions dans les {days_back} derniers jours")
        
        # Analyser un échantillon des transactions
        sample_size = min(100, len(all_signatures))
        sample_sigs = all_signatures[:sample_size] if sample_size > 0 else []
        
        sol_transfers = []
        fees_total = 0
        program_interactions = {}
        
        for i, sig_info in enumerate(sample_sigs):
            if i % 20 == 0:
                logger.info(f"   📈 Analyse SOL: {i+1}/{sample_size}")
            
            signature = sig_info["signature"]
            tx_detail = self.rate_limited_rpc_call(
                "getTransaction",
                [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
            )
            
            if tx_detail and tx_detail.get("result"):
                tx_analysis = self._analyze_sol_transaction(tx_detail["result"], wallet_address, sig_info)
                if tx_analysis:
                    if tx_analysis["type"] == "sol_transfer":
                        sol_transfers.append(tx_analysis)
                    fees_total += tx_analysis.get("fee", 0)
                    
                    # Compter les interactions avec les programmes
                    for program in tx_analysis.get("programs", []):
                        program_interactions[program] = program_interactions.get(program, 0) + 1
        

        self._save_transactions_to_cache(wallet_address, sol_transfers)

        return {
            "total_transactions": len(all_signatures),
            "analyzed_sample": sample_size,
            "sol_transfers": sol_transfers,
            "total_fees": fees_total,
            "program_interactions": program_interactions,
            "most_used_programs": sorted(program_interactions.items(), key=lambda x: x[1], reverse=True)[:10]
        }

    def _analyze_sol_transaction(self, tx: Dict, wallet_address: str, sig_info: Dict) -> Optional[Dict]:
        """Analyse une transaction SOL spécifique"""
        try:
            meta = tx.get("meta", {})
            if meta.get("err"):
                return None
            
            account_keys = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
            pre_balances = meta.get("preBalances", [])
            post_balances = meta.get("postBalances", [])
            
            # Trouver l'index du wallet
            wallet_index = None
            for i, key in enumerate(account_keys):
                if isinstance(key, str) and key == wallet_address:
                    wallet_index = i
                    break
                elif isinstance(key, dict) and key.get("pubkey") == wallet_address:
                    wallet_index = i
                    break
            
            if wallet_index is None or wallet_index >= len(pre_balances):
                return None
            
            # Calculer le changement de balance SOL
            pre_balance = pre_balances[wallet_index] / 1e9
            post_balance = post_balances[wallet_index] / 1e9
            sol_change = post_balance - pre_balance
            
            # Identifier les programmes utilisés
            instructions = tx.get("transaction", {}).get("message", {}).get("instructions", [])
            programs = set()
            for instruction in instructions:
                if "programId" in instruction:
                    programs.add(instruction["programId"])
                elif isinstance(instruction.get("programIdIndex"), int):
                    prog_index = instruction["programIdIndex"]
                    if prog_index < len(account_keys):
                        programs.add(account_keys[prog_index])
            
            return {
                "signature": sig_info["signature"],
                "timestamp": sig_info.get("blockTime", 0),
                "type": "sol_transfer" if abs(sol_change) > 0.001 else "program_interaction",
                "sol_change": sol_change,
                "fee": meta.get("fee", 0) / 1e9,
                "programs": list(programs),
                "success": meta.get("err") is None
            }
        
        except Exception as e:
            return None

    def _analyze_token_transactions(self, wallet_address: str, days_back: int) -> Dict:
        """Analyse les transactions de tokens (version simplifiée)"""
        logger.info("   🔍 Analyse des transactions de tokens (échantillon)...")
        
        # Cette méthode est simplifiée - on pourrait l'étendre pour analyser chaque token
        return {
            "note": "Analyse détaillée des tokens non implémentée dans cette version",
            "recommendation": "Utiliser analyze_token_creator pour des tokens spécifiques"
        }

    def _analyze_trading_patterns(self, sol_analysis: Dict, token_analysis: Dict) -> Dict:
        """Analyse les patterns de trading du wallet"""
        logger.info("   🔍 Analyse des patterns de trading...")
        
        sol_transfers = sol_analysis.get("sol_transfers", [])
        
        if not sol_transfers:
            return {"pattern": "no_trading", "activity_level": "low"}
        
        # Analyser la fréquence des transactions
        total_transfers = len(sol_transfers)

        # Calculer la fenêtre temporelle réelle
        if sol_transfers:
            timestamps = [tx["timestamp"] for tx in sol_transfers if tx["timestamp"] > 0]
            if timestamps:
                time_window_seconds = max(timestamps) - min(timestamps)
                time_window_hours = time_window_seconds / 3600
                time_window_minutes = time_window_seconds / 60
                
                # Éviter division par zéro
                time_window_seconds = max(time_window_seconds, 1)
                time_window_hours = max(time_window_hours, 0.01)
                time_window_minutes = max(time_window_minutes, 0.1)
            else:
                time_window_seconds = time_window_hours = time_window_minutes = 1
        else:
            time_window_seconds = time_window_hours = time_window_minutes = 1

        # Remplacer avg_transaction_per_day par les nouvelles métriques
        transactions_per_second = total_transfers / time_window_seconds
        transactions_per_minute = total_transfers / time_window_minutes  
        transactions_per_hour = total_transfers / time_window_hours
        
        # Analyser les montants
        amounts = [abs(tx["sol_change"]) for tx in sol_transfers if abs(tx["sol_change"]) > 0.001]
        avg_amount = sum(amounts) / len(amounts) if amounts else 0
        max_amount = max(amounts) if amounts else 0
        
        # Déterminer le niveau d'activité (basé sur transactions par heure)
        if transactions_per_hour > 10:
            activity_level = "very_high"
        elif transactions_per_hour > 5:
            activity_level = "high"
        elif transactions_per_hour > 1:
            activity_level = "medium"
        elif transactions_per_hour > 0.2:
            activity_level = "low"
        else:
            activity_level = "very_low"
        
        return {
            "activity_level": activity_level,
            "time_window_seconds": time_window_seconds,
            "time_window_hours": time_window_hours,
            "time_window_minutes": time_window_minutes,
            "transactions_per_second": transactions_per_second,
            "transactions_per_minute": transactions_per_minute,
            "transactions_per_hour": transactions_per_hour,
            "total_volume_manipulated": sum(amounts),
            "total_transfers": total_transfers,
            "avg_amount": avg_amount,
            "max_amount": max_amount,
            "unique_trading_days": len(set(
                datetime.fromtimestamp(tx["timestamp"]).date() 
                for tx in sol_transfers if tx["timestamp"] > 0
            ))
        }



    def _analyze_transaction_counterparties(self, sol_transfers: List[Dict]) -> Dict:
        """Analyse les contreparties des transactions SOL - VERSION CORRIGÉE"""
        logger.info("   🔍 Analyse des contreparties...")
        
        if not sol_transfers:
            return {"counterparties": {}, "top_counterparties": [], "unique_counterparties": 0}
        
        counterparties = {}
        total_interactions = 0
        
        # Analyser chaque transaction pour extraire les contreparties
        for transfer in sol_transfers:
            signature = transfer["signature"]
            
            # PRIORITÉ 1: Utiliser raw_data si disponible (depuis le cache)
            if "raw_data" in transfer and transfer["raw_data"]:
                try:
                    tx_data = json.loads(transfer["raw_data"]) if isinstance(transfer["raw_data"], str) else transfer["raw_data"]
                    account_keys = tx_data.get("account_keys", [])
                    
                    if not account_keys and "raw_transaction" in tx_data:
                        account_keys = tx_data["raw_transaction"].get("transaction", {}).get("message", {}).get("accountKeys", [])
                    
                    # Extraire les contreparties depuis le cache
                    for key in account_keys:
                        address = key if isinstance(key, str) else key.get("pubkey", "")
                        
                        if (address and 
                            address != transfer.get("wallet_address", "") and
                            not self._is_system_program(address)):
                            
                            counterparties[address] = counterparties.get(address, 0) + 1
                            total_interactions += 1
                    
                    continue  # ← IMPORTANT: Passer à la transaction suivante
                    
                except Exception as e:
                    logger.debug(f"   ⚠️ Erreur parsing cache pour {signature[:8]}...: {e}")
                    # Continuer sans faire de requête RPC
            
            # Si pas de raw_data, on skip la transaction au lieu de faire une requête RPC
            logger.debug(f"   ⚪ Transaction {signature[:8]}... ignorée (pas de raw_data en cache)")
        
        # Trier par fréquence
        top_counterparties = sorted(counterparties.items(), key=lambda x: x[1], reverse=True)[:10]
        
        logger.info(f"   📊 {len(counterparties)} contreparties uniques trouvées")
        logger.info(f"   🔄 {total_interactions} interactions totales")
        logger.info(f"   💾 Analyse 100% depuis le cache (0 requêtes RPC)")
        
        return {
            "counterparties": counterparties,
            "top_counterparties": top_counterparties,
            "unique_counterparties": len(counterparties),
            "total_interactions": total_interactions
        }

    def _detect_linked_wallets(self, sol_transfers: List[Dict], threshold_percentage: float = 20.0) -> Dict:
        """Détecte les wallets potentiellement liés - VERSION CORRIGÉE"""
        logger.info("   🕸️ Détection des wallets liés...")
    
        if not sol_transfers:
            return {"linked_wallets": [], "suspicious_patterns": []}
        
        wallet_interactions = {}
        transaction_count = len(sol_transfers)
        threshold_count = max(1, int(transaction_count * threshold_percentage / 100))
        
        for transfer in sol_transfers:
            signature = transfer["signature"]
            
            # PRIORITÉ 1: Utiliser raw_data si disponible
            if "raw_data" in transfer and transfer["raw_data"]:
                try:
                    tx_data = json.loads(transfer["raw_data"]) if isinstance(transfer["raw_data"], str) else transfer["raw_data"]
                    
                    if "raw_transaction" in tx_data:
                        tx = tx_data["raw_transaction"]
                        account_keys = tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
                        pre_balances = tx.get("meta", {}).get("preBalances", [])
                        post_balances = tx.get("meta", {}).get("postBalances", [])
                    else:
                        account_keys = tx_data.get("account_keys", [])
                        pre_balances = tx_data.get("pre_balances", [])
                        post_balances = tx_data.get("post_balances", [])
                    
                    # Analyser les changements de balance depuis le cache
                    for i, key in enumerate(account_keys):
                        address = key if isinstance(key, str) else key.get("pubkey", "")
                        
                        if (i < len(pre_balances) and i < len(post_balances) and 
                            address and not self._is_system_program(address)):
                            
                            balance_change = abs(post_balances[i] - pre_balances[i]) / 1e9
                            
                            if balance_change > 0.001:
                                if address not in wallet_interactions:
                                    wallet_interactions[address] = {
                                        "count": 0,
                                        "total_volume": 0,
                                        "signatures": []
                                    }
                                
                                wallet_interactions[address]["count"] += 1
                                wallet_interactions[address]["total_volume"] += balance_change
                                wallet_interactions[address]["signatures"].append(signature)
                    
                    continue  # ← IMPORTANT: Passer à la transaction suivante
                    
                except Exception as e:
                    logger.debug(f"   ⚠️ Erreur parsing cache pour {signature[:8]}...: {e}")
            
            # Si pas de raw_data complet, on skip au lieu de faire une requête RPC
            logger.debug(f"   ⚪ Transaction {signature[:8]}... ignorée (données incomplètes)")
        
        # Le reste de la fonction reste identique
        linked_wallets = []
        suspicious_patterns = []
        
        for address, data in wallet_interactions.items():
            interaction_percentage = (data["count"] / transaction_count) * 100
            
            if data["count"] >= threshold_count:
                linked_wallets.append({
                    "address": address,
                    "interaction_count": data["count"],
                    "interaction_percentage": interaction_percentage,
                    "total_volume": data["total_volume"],
                    "risk_level": "HIGH" if interaction_percentage > 50 else "MEDIUM"
                })
            
            if data["total_volume"] > 100:
                suspicious_patterns.append({
                    "type": "HIGH_VOLUME",
                    "address": address,
                    "volume": data["total_volume"],
                    "description": f"Volume élevé: {data['total_volume']:.2f} SOL"
                })
            
            if interaction_percentage > 30:
                suspicious_patterns.append({
                    "type": "HIGH_FREQUENCY", 
                    "address": address,
                    "percentage": interaction_percentage,
                    "description": f"Interactions très fréquentes: {interaction_percentage:.1f}%"
                })
        
        logger.info(f"   🎯 {len(linked_wallets)} wallets potentiellement liés")
        logger.info(f"   ⚠️ {len(suspicious_patterns)} patterns suspects")
        logger.info(f"   💾 Analyse 100% depuis le cache (0 requêtes RPC)")
        
        return {
            "linked_wallets": linked_wallets,
            "suspicious_patterns": suspicious_patterns,
            "threshold_used": threshold_percentage
        }

    def _check_token_liquidity(self, token_address: str) -> Dict:
        """Vérifie la liquidité du token sur les principaux DEX"""
        logger.info("   💧 Vérification de la liquidité...")
        
        liquidity_info = {
            "pools_found": [],
            "total_liquidity_usd": 0,
            "dex_presence": {},
            "risk_assessment": "UNKNOWN"
        }
        
        try:
            # Jupiter API pour les informations de token
            jupiter_url = f"https://price.jup.ag/v4/price?ids={token_address}"
            headers = {"Accept": "application/json"}
            
            response = requests.get(jupiter_url, headers=headers, timeout=10)
            if response.status_code == 200:
                jupiter_data = response.json()
                if "data" in jupiter_data and token_address in jupiter_data["data"]:
                    price_info = jupiter_data["data"][token_address]
                    liquidity_info["jupiter_price"] = price_info.get("price", 0)
                    liquidity_info["dex_presence"]["jupiter"] = True
                    logger.info(f"   💰 Prix Jupiter: ${price_info.get('price', 0)}")
            
            # Raydium API (exemple)
            try:
                raydium_url = "https://api.raydium.io/v2/main/pairs"
                response = requests.get(raydium_url, headers=headers, timeout=10)
                if response.status_code == 200:
                    pairs_data = response.json()
                    for pair in pairs_data:
                        if (pair.get("baseMint") == token_address or 
                            pair.get("quoteMint") == token_address):
                            
                            liquidity_info["pools_found"].append({
                                "dex": "Raydium",
                                "pair_id": pair.get("ammId", ""),
                                "liquidity_usd": pair.get("liquidity", 0),
                                "volume_24h": pair.get("volume24h", 0)
                            })
                            liquidity_info["dex_presence"]["raydium"] = True
                            logger.info(f"   🌊 Pool Raydium trouvé: ${pair.get('liquidity', 0)} liquidité")
            except:
                logger.debug("   ⚠️ Impossible de vérifier Raydium")
            
            # Calcul du risque basé sur la liquidité
            total_pools = len(liquidity_info["pools_found"])
            dex_count = len(liquidity_info["dex_presence"])
            
            if total_pools == 0:
                liquidity_info["risk_assessment"] = "TRÈS ÉLEVÉ - Aucune liquidité trouvée"
            elif total_pools == 1 and dex_count == 1:
                liquidity_info["risk_assessment"] = "ÉLEVÉ - Liquidité limitée à un DEX"
            elif dex_count >= 2:
                liquidity_info["risk_assessment"] = "MODÉRÉ - Présent sur plusieurs DEX"
            else:
                liquidity_info["risk_assessment"] = "ÉLEVÉ - Liquidité faible"
            
            logger.info(f"   📊 {total_pools} pools trouvés sur {dex_count} DEX")
            logger.info(f"   ⚠️ Risque: {liquidity_info['risk_assessment']}")
            
        except Exception as e:
            logger.warning(f"   ❌ Erreur vérification liquidité: {e}")
            liquidity_info["error"] = str(e)
            liquidity_info["risk_assessment"] = "INCONNU - Erreur de vérification"
        
        return liquidity_info


    def _calculate_creator_profit(self, creator_address: str, token_address: str, sol_transfers: List[Dict]) -> Dict:
        """Calcule le profit exact du créateur depuis la création du token"""
        logger.info("   💰 Calcul du profit du créateur...")
        
        profit_analysis = {
            "initial_investment": 0,
            "creation_costs": 0,
            "total_revenue": 0,
            "total_expenses": 0,
            "net_profit": 0,
            "profit_percentage": 0,
            "profitable_transactions": 0,
            "loss_transactions": 0,
            "biggest_gain": 0,
            "biggest_loss": 0,
            "break_even": False,
            "transactions_analyzed": 0
        }
        
        try:
            # Estimation des coûts de création (typique sur Solana)
            estimated_creation_cost = 0.01  # ~0.01 SOL pour créer un token
            profit_analysis["creation_costs"] = estimated_creation_cost
            
            total_gains = 0
            total_losses = 0
            transaction_details = []
            
            for transfer in sol_transfers:
                sol_change = transfer.get("sol_change", 0)
                fee = transfer.get("fee", 0)
                
                # Comptabiliser les changements
                if sol_change > 0:  # Revenus (SOL reçu)
                    total_gains += sol_change
                    profit_analysis["profitable_transactions"] += 1
                    if sol_change > profit_analysis["biggest_gain"]:
                        profit_analysis["biggest_gain"] = sol_change
                elif sol_change < 0:  # Dépenses (SOL envoyé)
                    total_losses += abs(sol_change)
                    profit_analysis["loss_transactions"] += 1
                    if abs(sol_change) > profit_analysis["biggest_loss"]:
                        profit_analysis["biggest_loss"] = abs(sol_change)
                
                # Ajouter les fees à chaque transaction
                profit_analysis["total_expenses"] += fee
                
                transaction_details.append({
                    "timestamp": transfer.get("timestamp", 0),
                    "sol_change": sol_change,
                    "fee": fee,
                    "running_balance": total_gains - total_losses
                })
            
            # Calculs finaux
            profit_analysis["total_revenue"] = total_gains
            profit_analysis["total_expenses"] += total_losses + estimated_creation_cost
            profit_analysis["net_profit"] = total_gains - total_losses - estimated_creation_cost
            profit_analysis["transactions_analyzed"] = len(sol_transfers)
            
            # Pourcentage de profit (si on assume un investissement initial)
            initial_investment = max(total_losses, estimated_creation_cost)
            if initial_investment > 0:
                profit_analysis["profit_percentage"] = (profit_analysis["net_profit"] / initial_investment) * 100
            
            profit_analysis["break_even"] = profit_analysis["net_profit"] >= 0
            profit_analysis["initial_investment"] = initial_investment
            
            # Logs détaillés
            logger.info(f"   💵 Revenus totaux: {total_gains:.4f} SOL")
            logger.info(f"   💸 Dépenses totales: {profit_analysis['total_expenses']:.4f} SOL")
            logger.info(f"   💰 Profit net: {profit_analysis['net_profit']:.4f} SOL")
            logger.info(f"   📈 ROI: {profit_analysis['profit_percentage']:.1f}%")
            logger.info(f"   ✅ Rentable: {'Oui' if profit_analysis['break_even'] else 'Non'}")
            
        except Exception as e:
            logger.warning(f"   ❌ Erreur calcul profit: {e}")
            profit_analysis["error"] = str(e)
        
        return profit_analysis

    def _calculate_risk_score(self, wallet_info: Dict, tokens_analysis: Dict, sol_analysis: Dict, 
                            trading_patterns: Dict, counterparties_analysis: Dict, 
                            linked_wallets_analysis: Dict, liquidity_analysis: Dict, 
                            profit_analysis: Dict) -> Dict:
        """Calcule un score de risque automatisé de 0 à 100"""
        logger.info("   📊 Calcul du score de risque...")
        
        risk_score = 0
        risk_factors = []
        max_score = 100
        
        try:
            # FACTEUR 1: Balance du wallet (25 points max)
            wallet_balance = wallet_info.get("sol_balance", 0)
            if wallet_balance == 0:
                risk_score += 25
                risk_factors.append("Balance complètement vide (+25 pts)")
            elif wallet_balance < 0.01:
                risk_score += 20
                risk_factors.append("Balance très faible (+20 pts)")
            elif wallet_balance < 0.1:
                risk_score += 10
                risk_factors.append("Balance faible (+10 pts)")
            
            # FACTEUR 2: Diversification des tokens (10 points max)
            token_count = tokens_analysis.get("total_tokens", 0)
            if token_count == 0:
                risk_score += 10
                risk_factors.append("Aucun token détenu (+10 pts)")
            elif token_count < 3:
                risk_score += 5
                risk_factors.append("Très peu diversifié (+5 pts)")
            
            # FACTEUR 3: Activité de trading (20 points max)
            activity_level = trading_patterns.get("activity_level", "low")
            transactions_per_hour = trading_patterns.get("transactions_per_hour", 0)
            
            if activity_level == "very_high" and transactions_per_hour > 50:
                risk_score += 20
                risk_factors.append(f"Hyperactivité suspecte: {transactions_per_hour:.0f}/h (+20 pts)")
            elif activity_level == "very_high":
                risk_score += 15
                risk_factors.append("Activité très élevée (+15 pts)")
            elif activity_level == "high":
                risk_score += 10
                risk_factors.append("Activité élevée (+10 pts)")
            
            # FACTEUR 4: Concentration des contreparties (15 points max)
            unique_counterparties = counterparties_analysis.get("unique_counterparties", 0)
            total_interactions = counterparties_analysis.get("total_interactions", 1)
            
            if unique_counterparties > 0:
                concentration_ratio = total_interactions / unique_counterparties
                if concentration_ratio > 5:  # Très concentré
                    risk_score += 15
                    risk_factors.append(f"Contreparties très concentrées: {concentration_ratio:.1f} (+15 pts)")
                elif concentration_ratio > 3:
                    risk_score += 10
                    risk_factors.append("Contreparties concentrées (+10 pts)")
            
            # FACTEUR 5: Wallets liés suspects (10 points max)
            linked_wallets = linked_wallets_analysis.get("linked_wallets", [])
            suspicious_patterns = linked_wallets_analysis.get("suspicious_patterns", [])
            
            high_risk_wallets = [w for w in linked_wallets if w.get("risk_level") == "HIGH"]
            if len(high_risk_wallets) > 0:
                risk_score += 10
                risk_factors.append(f"{len(high_risk_wallets)} wallet(s) à haut risque (+10 pts)")
            elif len(suspicious_patterns) > 2:
                risk_score += 5
                risk_factors.append("Patterns suspects détectés (+5 pts)")
            
            # FACTEUR 6: Liquidité du token (10 points max)
            pools_found = len(liquidity_analysis.get("pools_found", []))
            dex_count = len(liquidity_analysis.get("dex_presence", {}))
            
            if pools_found == 0:
                risk_score += 10
                risk_factors.append("Aucune liquidité trouvée (+10 pts)")
            elif pools_found == 1 and dex_count == 1:
                risk_score += 7
                risk_factors.append("Liquidité très limitée (+7 pts)")
            elif dex_count < 2:
                risk_score += 3
                risk_factors.append("Peu de présence DEX (+3 pts)")
            
            # FACTEUR 7: Profitabilité du créateur (10 points max)
            if profit_analysis.get("net_profit", 0) > 100:  # Gros profit
                risk_score += 10
                risk_factors.append(f"Profit élevé: {profit_analysis['net_profit']:.1f} SOL (+10 pts)")
            elif profit_analysis.get("net_profit", 0) > 50:
                risk_score += 7
                risk_factors.append("Profit significatif (+7 pts)")
            elif profit_analysis.get("net_profit", 0) > 10:
                risk_score += 5
                risk_factors.append("Profit modéré (+5 pts)")
            
            # Limiter le score à 100
            risk_score = min(risk_score, max_score)
            
            # Déterminer le niveau de risque
            if risk_score >= 80:
                risk_level = "CRITIQUE"
                risk_color = "🔴"
                recommendation = "ÉVITER ABSOLUMENT"
            elif risk_score >= 60:
                risk_level = "TRÈS ÉLEVÉ"
                risk_color = "🟠"
                recommendation = "FORTEMENT DÉCONSEILLÉ"
            elif risk_score >= 40:
                risk_level = "ÉLEVÉ"
                risk_color = "🟡"
                recommendation = "PRUDENCE REQUISE"
            elif risk_score >= 20:
                risk_level = "MODÉRÉ"
                risk_color = "🟢"
                recommendation = "ACCEPTABLE AVEC VIGILANCE"
            else:
                risk_level = "FAIBLE"
                risk_color = "✅"
                recommendation = "RELATIVEMENT SÛR"
            
            logger.info(f"   🎯 Score de risque: {risk_score}/100")
            logger.info(f"   {risk_color} Niveau: {risk_level}")
            logger.info(f"   💡 Recommandation: {recommendation}")
            
            return {
                "score": risk_score,
                "max_score": max_score,
                "level": risk_level,
                "color": risk_color,
                "recommendation": recommendation,
                "factors": risk_factors,
                "factor_count": len(risk_factors)
            }
            
        except Exception as e:
            logger.warning(f"   ❌ Erreur calcul score risque: {e}")
            return {
                "score": 50,
                "level": "INCONNU",
                "color": "⚠️",
                "recommendation": "IMPOSSIBLE À ÉVALUER",
                "factors": [f"Erreur: {str(e)}"],
                "error": str(e)
            }



    def _is_system_program(self, address: str) -> bool:
        """Vérifie si une adresse est un programme système"""
        system_programs = {
            "11111111111111111111111111111111",  # System Program
            "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",  # Token Program
            "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",  # Associated Token
            "ComputeBudget111111111111111111111111111111",  # Compute Budget
            "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",  # Raydium AMM
            "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Raydium Authority
        }
        return address in system_programs




    def _generate_wallet_report(self, wallet_address: str, wallet_info: Dict, tokens_analysis: Dict, 
                          sol_analysis: Dict, token_analysis: Dict, trading_patterns: Dict, 
                          analysis_duration: float, days_back: int, token_address: str = None) -> Dict:
        """Génère et affiche le rapport complet du wallet"""
        
        logger.info("\n" + "=" * 80)
        logger.info("📋 RAPPORT COMPLET DU WALLET")
        logger.info("=" * 80)
        
        # En-tête
        logger.info(f"🔍 Wallet analysé: {wallet_address}")
        logger.info(f"📅 Période: {days_back} jours")
        logger.info(f"⏱️  Durée d'analyse: {analysis_duration:.1f}s")
        logger.info(f"🔢 Requêtes RPC: {self.request_count}")
        
        # Informations de base
        logger.info("\n🏦 INFORMATIONS GÉNÉRALES")
        logger.info("-" * 40)
        logger.info(f"💰 Balance SOL: {wallet_info['sol_balance']:.4f} SOL")
        logger.info(f"🔧 Type: {'Programme' if wallet_info['is_program'] else 'Wallet EOA'}")
        
        # Tokens
        logger.info("\n🪙 PORTEFEUILLE DE TOKENS")
        logger.info("-" * 40)
        tokens = tokens_analysis["tokens"]
        logger.info(f"📊 Total tokens: {tokens_analysis['total_tokens']} (avec balance > 0)")
        logger.info(f"📋 Total accounts: {tokens_analysis['total_accounts']}")
        
        if tokens:
            logger.info("\n🏆 TOP 10 TOKENS PAR BALANCE:")
            for i, token in enumerate(tokens[:10]):
                logger.info(f"   {i+1:2d}. {token['address'][:8]}... : {token['balance']:,.4f}")
        
        # Activité SOL
        logger.info("\n💰 ACTIVITÉ SOL")
        logger.info("-" * 40)
        logger.info(f"📊 Total transactions: {sol_analysis['total_transactions']}")
        logger.info(f"🔍 Échantillon analysé: {sol_analysis['analyzed_sample']}")
        logger.info(f"💸 Total fees: {sol_analysis['total_fees']:.6f} SOL")
        logger.info(f"🔄 Transferts SOL: {len(sol_analysis['sol_transfers'])}")
        
        # Programmes les plus utilisés
        if sol_analysis["most_used_programs"]:
            logger.info("\n🔧 PROGRAMMES LES PLUS UTILISÉS:")
            for program, count in sol_analysis["most_used_programs"][:5]:
                program_name = self._get_program_name(program)
                logger.info(f"   • {program_name}: {count} interactions")
        
        # Patterns de trading
        logger.info("\n📊 PATTERNS D'ACTIVITÉ")
        logger.info("-" * 40)
        activity_labels = {
            "very_high": "🔥 TRÈS ÉLEVÉE",
            "high": "📈 ÉLEVÉE", 
            "medium": "📊 MOYENNE",
            "low": "📉 FAIBLE",
            "very_low": "💤 TRÈS FAIBLE"
        }
        activity_level = trading_patterns["activity_level"]
        logger.info(f"⏰ Fenêtre d'activité: {trading_patterns['time_window_hours']:.1f}h ({trading_patterns['time_window_minutes']:.0f}min)")
        logger.info(f"📅 Transactions/fenêtre: {trading_patterns['transactions_per_hour']:.1f}/h")
        logger.info(f"⚡ Fréquence: {trading_patterns['transactions_per_minute']:.1f}/min | {trading_patterns['transactions_per_second']:.2f}/sec")
        logger.info(f"💰 Volume total manipulé: {trading_patterns['total_volume_manipulated']:.4f} SOL")
        
        if trading_patterns["avg_amount"] > 0:
            logger.info(f"💰 Montant moyen: {trading_patterns['avg_amount']:.4f} SOL")
            logger.info(f"🎯 Montant max: {trading_patterns['max_amount']:.4f} SOL")
        

        logger.info("\n🔗 ANALYSE DES CONTREPARTIES")
        logger.info("-" * 40)
        counterparties_analysis = self._analyze_transaction_counterparties(sol_analysis.get("sol_transfers", []))
        
        if counterparties_analysis["top_counterparties"]:
            logger.info(f"📊 {counterparties_analysis['unique_counterparties']} contreparties uniques")
            logger.info("\n🏆 TOP 5 CONTREPARTIES:")
            for i, (address, count) in enumerate(counterparties_analysis["top_counterparties"][:5]):
                percentage = (count / counterparties_analysis["total_interactions"]) * 100
                logger.info(f"   {i+1}. {address[:8]}... : {count} interactions ({percentage:.1f}%)")
        else:
            logger.info("⚪ Aucune contrepartie identifiée")

        # NOUVELLE SECTION 2: WALLETS LIÉS
        logger.info("\n🕸️ WALLETS LIÉS DÉTECTÉS")
        logger.info("-" * 40)
        linked_wallets_analysis = self._detect_linked_wallets(sol_analysis.get("sol_transfers", []))
        
        if linked_wallets_analysis["linked_wallets"]:
            logger.info(f"🎯 {len(linked_wallets_analysis['linked_wallets'])} wallets potentiellement liés")
            for wallet in linked_wallets_analysis["linked_wallets"][:3]:
                logger.info(f"   • {wallet['address'][:8]}... : {wallet['interaction_count']} interactions "
                        f"({wallet['interaction_percentage']:.1f}%) - {wallet['risk_level']}")
        else:
            logger.info("✅ Aucun wallet suspect détecté")
        
        if linked_wallets_analysis["suspicious_patterns"]:
            logger.info(f"\n⚠️ {len(linked_wallets_analysis['suspicious_patterns'])} patterns suspects:")
            for pattern in linked_wallets_analysis["suspicious_patterns"][:3]:
                logger.info(f"   🚨 {pattern['description']}")

        # NOUVELLE SECTION 3: LIQUIDITÉ DU TOKEN (si token_address fourni)
        if token_address:
            logger.info("\n💧 LIQUIDITÉ DU TOKEN")
            logger.info("-" * 40)
            liquidity_analysis = self._check_token_liquidity(token_address)
            
            logger.info(f"🏊 Pools trouvés: {len(liquidity_analysis['pools_found'])}")
            logger.info(f"🏢 DEX présents: {len(liquidity_analysis['dex_presence'])}")
            logger.info(f"⚠️ Évaluation risque: {liquidity_analysis['risk_assessment']}")
            
            if liquidity_analysis["pools_found"]:
                for pool in liquidity_analysis["pools_found"][:2]:
                    logger.info(f"   💰 {pool['dex']}: ${pool['liquidity_usd']:,.0f} liquidité")


        # NOUVELLE SECTION: CALCUL DU PROFIT
        logger.info("\n💰 ANALYSE DU PROFIT CRÉATEUR")
        logger.info("-" * 40)
        profit_analysis = self._calculate_creator_profit(wallet_address, token_address or "", sol_analysis.get("sol_transfers", []))
        
        logger.info(f"💵 Revenus totaux: {profit_analysis['total_revenue']:.4f} SOL")
        logger.info(f"💸 Dépenses totales: {profit_analysis['total_expenses']:.4f} SOL")
        logger.info(f"💰 Profit net: {profit_analysis['net_profit']:.4f} SOL")
        logger.info(f"📈 ROI: {profit_analysis['profit_percentage']:.1f}%")
        logger.info(f"📊 Transactions: {profit_analysis['profitable_transactions']} gains / {profit_analysis['loss_transactions']} pertes")
        logger.info(f"🎯 Plus gros gain: {profit_analysis['biggest_gain']:.4f} SOL")
        logger.info(f"🎯 Plus grosse perte: {profit_analysis['biggest_loss']:.4f} SOL")
        logger.info(f"✅ Rentable: {'Oui' if profit_analysis['break_even'] else 'Non'}")
        liquidity_analysis = 1 #to remove
        # NOUVELLE SECTION: SCORE DE RISQUE
        logger.info("\n📊 ÉVALUATION DU RISQUE")
        logger.info("-" * 40)
        risk_analysis = self._calculate_risk_score(
            wallet_info, tokens_analysis, sol_analysis, trading_patterns,
            counterparties_analysis, linked_wallets_analysis, liquidity_analysis, profit_analysis
        )
        
        # logger.info(f"🎯 SCORE DE RISQUE: {risk_analysis['score']}/{risk_analysis['max_score']}")
        # logger.info(f"{risk_analysis['color']} NIVEAU: {risk_analysis['level']}")
        # logger.info(f"💡 RECOMMANDATION: {risk_analysis['recommendation']}")
        
        # if risk_analysis.get("factors"):
        #     logger.info(f"\n⚠️ FACTEURS DE RISQUE IDENTIFIÉS ({risk_analysis['factor_count']}):")
        #     for factor in risk_analysis["factors"][:5]:  # Top 5 facteurs
        #         logger.info(f"   • {factor}")


        # Conclusion
        logger.info("\n🎯 RÉSUMÉ EXÉCUTIF")
        logger.info("-" * 40)
        self._generate_executive_summary(wallet_info, tokens_analysis, trading_patterns)
        
        logger.info("\n" + "=" * 80)
        
        ml_features = {
            "sol_balance": wallet_info.get("sol_balance", 0),
            "total_tokens": tokens_analysis.get("total_tokens", 0),
            "total_transactions": sol_analysis.get("total_transactions", 0),
            "transactions_per_hour": trading_patterns.get("transactions_per_hour", 0),
            "time_window_hours": trading_patterns.get("time_window_hours", 0),
            "total_volume": trading_patterns.get("total_volume_manipulated", 0),
            "unique_counterparties": counterparties_analysis.get("unique_counterparties", 0),
            "linked_wallets_count": len(linked_wallets_analysis.get("linked_wallets", [])),
            "profit_percentage": profit_analysis.get("profit_percentage", 0),
            "activity_level": trading_patterns.get("activity_level", "unknown")
        }
        
        # Labels pour supervision (à ajuster selon vos besoins)
        labels = {
            "is_suspicious": risk_analysis.get("score", 0) > 70,
            "is_profitable": profit_analysis.get("net_profit", 0) > 10,
            "is_active_trader": trading_patterns.get("activity_level") in ["high", "very_high"],
            "wallet_emptied": wallet_info.get("sol_balance", 0) == 0
        }
        
        # Sauvegarder pour ML
        self._save_ml_features(
            wallet_address, 
            ml_features, 
            risk_analysis.get("score", 0),
            profit_analysis.get("net_profit", 0),
            labels
        )

        # Retourner les données pour usage programmatique
        return {
            "wallet_address": wallet_address,
            "analysis_duration": analysis_duration,
            "basic_info": wallet_info,
            "tokens": tokens_analysis,
            "sol_activity": sol_analysis,
            "trading_patterns": trading_patterns,
            "counterparties": counterparties_analysis,
            "linked_wallets": linked_wallets_analysis,
            "liquidity": liquidity_analysis,
            "profit_analysis": profit_analysis,
            "risk_analysis": risk_analysis,
            "rpc_requests": self.request_count,
            "ml_features": ml_features,
            "labels": labels
        }

    def _get_program_name(self, program_id: str) -> str:
        """Retourne le nom convivial d'un programme"""
        known_programs = {
            "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA": "Token Program",
            "11111111111111111111111111111111": "System Program",
            "ComputeBudget111111111111111111111111111111": "Compute Budget",
            "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL": "Associated Token",
            "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM": "Raydium AMM",
            "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8": "Raydium Authority"
        }
        return known_programs.get(program_id, f"{program_id[:8]}...")

    def _generate_executive_summary(self, wallet_info: Dict, tokens_analysis: Dict, trading_patterns: Dict):
        """Génère un résumé exécutif du wallet"""
        
        # Type de wallet
        if wallet_info["is_program"]:
            logger.info("🔧 WALLET PROGRAMME - Compte de smart contract")
        else:
            logger.info("👤 WALLET EOA - Compte utilisateur standard")
        
        # Niveau de richesse
        sol_balance = wallet_info["sol_balance"]
        if sol_balance > 1000:
            logger.info("💎 WHALE - Balance SOL très élevée")
        elif sol_balance > 100:
            logger.info("🐋 GROS DÉTENTEUR - Balance SOL importante")
        elif sol_balance > 10:
            logger.info("💰 DÉTENTEUR MOYEN - Balance SOL correcte")
        elif sol_balance > 1:
            logger.info("💵 PETIT DÉTENTEUR - Balance SOL faible")
        else:
            logger.info("🪙 MICRO DÉTENTEUR - Balance SOL très faible")
        
        # Diversification
        token_count = tokens_analysis["total_tokens"]
        if token_count > 50:
            logger.info("🌈 TRÈS DIVERSIFIÉ - Portfolio de tokens important")
        elif token_count > 20:
            logger.info("🎨 DIVERSIFIÉ - Bon nombre de tokens")
        elif token_count > 5:
            logger.info("📊 MOYENNEMENT DIVERSIFIÉ - Quelques tokens")
        elif token_count > 0:
            logger.info("🎯 PEU DIVERSIFIÉ - Peu de tokens")
        else:
            logger.info("💤 AUCUN TOKEN - Seulement SOL")
        
        # Activité
        activity = trading_patterns["activity_level"]
        if activity in ["very_high", "high"]:
            logger.info("⚡ TRADER ACTIF - Activité de trading élevée")
        elif activity == "medium":
            logger.info("📈 UTILISATEUR RÉGULIER - Activité modérée")
        else:
            logger.info("💤 HODLER / DORMANT - Peu d'activité récente")


    def analyze_token_creator(self, token_address: str, output_filename: str = None, 
                         hours_back: int = 24, max_transactions: int = None,
                         exhaustive_creator_search: bool = True, 
                         max_creator_search_signatures: int = None,
                         force_refresh_creator: bool = False):
        """
        Analyse les transactions de l'ATA du créateur pour le token spécifié
        
        Args:
            token_address: Adresse du token à analyser
            output_filename: Nom du fichier de sortie (optionnel)
            hours_back: Nombre d'heures à analyser pour les transactions ATA
            max_transactions: Limite pour les transactions ATA
            exhaustive_creator_search: Si True, recherche exhaustive du créateur
            max_creator_search_signatures: Limite pour la recherche du créateur
            force_refresh_creator: Si True, ignore le cache et force la recherche du créateur
        """
        logger.info("=" * 80)
        logger.info(f"🚀 ANALYSE DU TOKEN {token_address[:8]}...")
        logger.info(f"⏰ Période ATA: {hours_back} heures")
        
        if force_refresh_creator:
            logger.info(f"🔄 Mode refresh: Cache créateur ignoré")

        if exhaustive_creator_search:
            search_limit = f" (limite: {max_creator_search_signatures})" if max_creator_search_signatures else " (TOUTES)"
            logger.info(f"🔍 Recherche créateur: EXHAUSTIVE{search_limit}")
        else:
            logger.info(f"🔍 Recherche créateur: STANDARD (priorités + 10 transactions)")
        
        if max_transactions:
            logger.info(f"📊 Limitation ATA: {max_transactions} transactions max")
        else:
            logger.info(f"🚀 Mode ATA: ANALYSE COMPLÈTE")
        logger.info("=" * 80)

        try:
            # ÉTAPE 1: Trouver le créateur
            logger.info("\n🔍 ÉTAPE 1: IDENTIFICATION DU CRÉATEUR")
            logger.info("-" * 50)
            
            creator_address = self.find_token_creator(token_address,exhaustive_search=exhaustive_creator_search,
            max_signatures=max_creator_search_signatures,
            force_refresh=force_refresh_creator)
            if not creator_address:
                logger.error("❌ Impossible de trouver le créateur du token")
                return None

            logger.info(f"✅ Créateur identifié: {creator_address}")

            # ÉTAPE 2: Trouver l'ATA du token
            # logger.info("\n🔍 ÉTAPE 2: RECHERCHE DE L'ATA")
            # logger.info("-" * 50)
            
            # ata_pubkey = self.get_token_ata(creator_address, token_address)
            # if not ata_pubkey:
            #     logger.error("❌ Aucun ATA trouvé pour ce token")
            #     return None

            # logger.info(f"✅ ATA identifié: {ata_pubkey}")

            # ÉTAPE 3: Scanner les transactions de l'ATA
            # logger.info("\n💰 ÉTAPE 3: SCAN DES TRANSACTIONS DE L'ATA")
            # logger.info("-" * 50)
            
            # scan_start = time.time()
            # balance_changes = self.scan_ata_transactions(ata_pubkey, token_address, hours_back, max_transactions)
            # scan_duration = time.time() - scan_start
            
            # logger.info(f"✅ Scan terminé en {scan_duration:.1f}s")
            # logger.info(f"💰 {len(balance_changes)} balance changes trouvés")

            # # ÉTAPE 4: Export CSV
            # logger.info("\n💾 ÉTAPE 4: EXPORT DES DONNÉES")
            # logger.info("-" * 50)
            
            # if not output_filename:
            #     timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            #     limit_suffix = f"_limit{max_transactions}" if max_transactions else "_full"
            #     output_filename = f"balance_changes_{creator_address[:8]}_{token_address[:8]}_{timestamp}{limit_suffix}.csv"

            # if balance_changes:
            #     self.export_to_csv(balance_changes, output_filename)
                
            #     # Statistiques finales
            #     inc_count = sum(1 for bc in balance_changes if bc['ChangeType'] == 'inc')
            #     dec_count = sum(1 for bc in balance_changes if bc['ChangeType'] == 'dec')
                
            #     logger.info(f"📊 Résumé des balance changes:")
            #     logger.info(f"   🟢 Augmentations (inc): {inc_count}")
            #     logger.info(f"   🔴 Réductions (dec): {dec_count}")
            #     logger.info(f"   📁 Fichier: {output_filename}")
            # else:
            #     logger.warning("⚠️ Aucun balance change trouvé dans la période")
            #     logger.info("💡 Cela peut signifier:")
            #     logger.info("   - Le créateur n'a pas interagi avec ce token pendant cette période")
            #     logger.info("   - Les montants étaient inférieurs au seuil de détection")

            # ÉTAPE 5: ANALYSE COMPLÈTE DU WALLET CRÉATEUR
            logger.info("\n🔬 ÉTAPE 3: ANALYSE COMPLÈTE DU WALLET CRÉATEUR")
            logger.info("-" * 50)
            
            wallet_analysis = self.analyze_wallet_complete(creator_address, days_back=1,token_address=token_address)  # 7 jours par défaut
            
            # Ajouter les données du wallet au résultat
            result = {
                "token_address": token_address,
                "creator_address": creator_address,
                # "ata_pubkey": ata_pubkey,
                # "balance_changes_count": len(balance_changes),
                # "output_file": output_filename if balance_changes else None,
                # "scan_duration": scan_duration,
                "rpc_requests": self.request_count,
                "wallet_analysis": wallet_analysis
            }

            # RÉSULTATS FINAUX
            logger.info("\n" + "=" * 80)
            logger.info("🎉 ANALYSE TERMINÉE AVEC SUCCÈS")
            logger.info("=" * 80)
            logger.info(f"🪙 Token analysé: {token_address}")
            logger.info(f"👤 Créateur: {creator_address}")
            # logger.info(f"📊 ATA: {ata_pubkey}")
            # logger.info(f"💰 Balance changes: {len(balance_changes)}")
            logger.info(f"🔢 Requêtes RPC totales: {self.request_count}")
            # logger.info(f"⏱️ Durée totale: {scan_duration:.1f}s")
            logger.info("=" * 80)

            return {
                "token_address": token_address,
                "creator_address": creator_address,
                # "ata_pubkey": ata_pubkey,
                # "balance_changes_count": len(balance_changes),
                # "output_file": output_filename if balance_changes else None,
                # "scan_duration": scan_duration,
                "rpc_requests": self.request_count
            }

        except Exception as e:
            logger.error(f"❌ Erreur lors de l'analyse: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None

def main():
    """Point d'entrée principal"""
    print("🚀 Token Creator ATA Transactions Analyzer")
    print("=" * 60)
    
    # Configuration
    QUICKNODE_ENDPOINT = 'https://misty-alpha-aura.solana-mainnet.quiknode.pro/2a16287e4ba93a9df419f3fa8da45d135d682202/'
    TOKEN_ADDRESS = '53SDajfns8MnVbLnmbBkaAjgGqf3vBScEgm44E6wZqvA'
    
    if not TOKEN_ADDRESS:
        print("❌ Adresse de token requise")
        return
    
    # Initialiser l'analyseur
    analyzer = TokenCreatorAnalyzer(QUICKNODE_ENDPOINT)
    
    # Afficher les stats du cache
    cache_stats = analyzer.get_cache_stats()
    if cache_stats["cache_enabled"]:
        print(f"💾 Cache: {cache_stats['total_entries']} créateurs | {cache_stats['recent_entries_24h']} récents (24h)")
    
    try:
        hours_back = int(input("⏰ Nombre d'heures à analyser (défaut: 24): ") or "24")
        
        # Nouvelle option pour forcer le refresh du créateur
        force_refresh = input("🔄 Forcer la recherche du créateur (ignorer cache) ? (y/N): ").lower().startswith('y')
        
        analyze_wallet = input("🔬 Analyser complètement le wallet du créateur ? (Y/n): ").lower()
        analyze_wallet = analyze_wallet != 'n'  # Par défaut = oui
        
    except ValueError:
        hours_back = 24
        force_refresh = False
        analyze_wallet = True
    
    # Lancer l'analyse avec les nouvelles options
    result = analyzer.analyze_token_creator(
        TOKEN_ADDRESS, 
        hours_back=hours_back,
        force_refresh_creator=force_refresh  # ← NOUVEAU
    )
    
    if result:
        print("\n✅ Analyse terminée avec succès !")
        # if result['output_file']:
        #     print(f"📁 Fichier CSV généré: {result['output_file']}")
        
        # Afficher les stats finales du cache
        final_stats = analyzer.get_cache_stats()
        if final_stats["cache_enabled"]:
            print(f"💾 Cache final: {final_stats['total_entries']} créateurs")
    else:
        print("\n❌ Échec de l'analyse")

if __name__ == "__main__":
    main()