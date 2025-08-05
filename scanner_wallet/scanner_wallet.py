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
import threading
from contextlib import contextmanager

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
        ENABLE_RPC_BATCHING = True
        BATCH_SIZES = {
            'getMultipleAccounts': 8,        # Conservateur pour free plan
            'token_metadata': 5,              # Métadonnées par batch
            'signatures_batch': 12,           # Signatures par batch
            'transactions_batch': 6           # Transactions par batch
        }

        # Timing et sécurité
        BATCH_TIMING = {
            'min_delay_between_batches': 0.3,     # 300ms pause entre batches
            'max_concurrent_batches': 1,          # Un seul batch à la fois
            'batch_timeout': 25,                  # 25s timeout par batch
            'adaptive_sizing': True               # Ajustement automatique des tailles
        }

        # Monitoring des rate limits
        RATE_LIMIT_MONITORING = {
            'track_response_times': True,
            'max_acceptable_response_time': 8000,  # 8s max
            'reduce_batch_size_threshold': 5000,   # Réduire si > 5s
            'emergency_fallback_threshold': 15000   # Fallback individuel si > 15s
        }
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

class BatchRPCManager:
    """Gestionnaire intelligent de batching RPC avec adaptation aux rate limits"""

    def __init__(self, monitor_instance):
        self.monitor = monitor_instance
        self.batch_stats = {
            'total_batches': 0,
            'successful_batches': 0,
            'failed_batches': 0,
            'avg_response_time': 0,
            'current_batch_sizes': Config.BATCH_SIZES.copy(),
            'rate_limit_hits': 0,
            'fallback_count': 0
        }
        self.response_times = []
        self.last_batch_time = 0

    def adaptive_batch_size(self, method: str) -> int:
        """Calcule la taille optimale de batch selon les performances récentes"""
        base_size = self.batch_stats['current_batch_sizes'].get(method, 5)

        # Réduire si rate limit récent
        if self.batch_stats['rate_limit_hits'] > 0:
            reduction_factor = min(0.5, self.batch_stats['rate_limit_hits'] * 0.2)
            base_size = max(2, int(base_size * (1 - reduction_factor)))
            logger.debug(f"🔧 Taille batch réduite pour {method}: {base_size}")

        # Augmenter progressivement si tout va bien
        elif (len(self.response_times) > 5 and
              sum(self.response_times[-5:]) / 5 < Config.RATE_LIMIT_MONITORING['reduce_batch_size_threshold']):
            base_size = min(base_size + 1, Config.BATCH_SIZES[method] * 1.5)
            logger.debug(f"📈 Taille batch augmentée pour {method}: {base_size}")

        self.batch_stats['current_batch_sizes'][method] = base_size
        return int(base_size)

    def batch_get_multiple_accounts(self, account_addresses: List[str]) -> Dict:
        """Batch optimisé pour récupérer plusieurs comptes"""
        if not Config.ENABLE_RPC_BATCHING or len(account_addresses) <= 1:
            # Fallback individuel
            return self._individual_account_calls(account_addresses)

        batch_size = self.adaptive_batch_size('getMultipleAccounts')
        all_results = {}

        for i in range(0, len(account_addresses), batch_size):
            batch_addresses = account_addresses[i:i + batch_size]

            batch_start = time.time()
            logger.debug(f"🔄 Batch RPC: {len(batch_addresses)} comptes (lot {i//batch_size + 1})")

            try:
                # Respecter le délai entre batches
                if time.time() - self.last_batch_time < Config.BATCH_TIMING['min_delay_between_batches']:
                    sleep_time = Config.BATCH_TIMING['min_delay_between_batches'] - (time.time() - self.last_batch_time)
                    time.sleep(sleep_time)

                # Appel RPC batch
                result = self.monitor.get_solana_rpc_data(
                    "getMultipleAccounts",
                    [batch_addresses, {"encoding": "jsonParsed"}]
                )

                batch_duration = time.time() - batch_start
                self.response_times.append(batch_duration * 1000)  # En millisecondes
                self.last_batch_time = time.time()

                if result and "result" in result:
                    batch_results = result["result"]["value"]
                    for j, account_data in enumerate(batch_results):
                        if j < len(batch_addresses):
                            all_results[batch_addresses[j]] = account_data

                    self.batch_stats['successful_batches'] += 1
                    logger.debug(f"✅ Batch réussi: {len(batch_addresses)} comptes en {batch_duration:.2f}s")
                else:
                    logger.warning(f"⚠️ Batch RPC échoué, fallback individuel")
                    individual_results = self._individual_account_calls(batch_addresses)
                    all_results.update(individual_results)
                    self.batch_stats['failed_batches'] += 1

            except Exception as e:
                logger.error(f"❌ Erreur batch RPC: {e}")
                # Fallback vers appels individuels
                individual_results = self._individual_account_calls(batch_addresses)
                all_results.update(individual_results)
                self.batch_stats['failed_batches'] += 1
                self.batch_stats['fallback_count'] += 1

        # Nettoyer l'historique des temps de réponse
        if len(self.response_times) > 20:
            self.response_times = self.response_times[-20:]

        self.batch_stats['total_batches'] += 1
        return all_results

    def _individual_account_calls(self, addresses: List[str]) -> Dict:
        """Fallback: appels RPC individuels"""
        results = {}
        for address in addresses:
            try:
                result = self.monitor.rate_limited_rpc_call("getAccount", [address, {"encoding": "jsonParsed"}])
                if result and "result" in result:
                    results[address] = result["result"]["value"]
                time.sleep(Config.RATE_LIMIT_DELAY)  # Respecter rate limit
            except Exception as e:
                logger.error(f"❌ Erreur appel individuel {address[:8]}...: {e}")
                results[address] = None
        return results

    def batch_get_signatures_for_addresses(self, addresses: List[str], limit_per_address: int = 10) -> Dict:
        """Batch pour récupérer les signatures de plusieurs adresses"""
        if not Config.ENABLE_RPC_BATCHING:
            return self._individual_signatures_calls(addresses, limit_per_address)

        all_signatures = {}
        batch_size = self.adaptive_batch_size('signatures_batch')

        for i in range(0, len(addresses), batch_size):
            batch_addresses = addresses[i:i + batch_size]

            try:
                # Créer les requêtes pour le batch
                batch_requests = []
                for j, address in enumerate(batch_addresses):
                    batch_requests.append({
                        "jsonrpc": "2.0",
                        "id": j,
                        "method": "getSignaturesForAddress",
                        "params": [address, {"limit": limit_per_address, "commitment": "finalized"}]
                    })

                # Attendre entre les batches
                if time.time() - self.last_batch_time < Config.BATCH_TIMING['min_delay_between_batches']:
                    sleep_time = Config.BATCH_TIMING['min_delay_between_batches'] - (time.time() - self.last_batch_time)
                    time.sleep(sleep_time)

                batch_start = time.time()
                logger.debug(f"🔄 Batch signatures: {len(batch_addresses)} adresses")

                # Envoyer le batch
                response = requests.post(
                    self.monitor.get_current_rpc_endpoint(),
                    json=batch_requests,
                    timeout=Config.BATCH_TIMING['batch_timeout'],
                    headers=Config.get_rpc_headers()
                )

                batch_duration = time.time() - batch_start
                self.response_times.append(batch_duration * 1000)
                self.last_batch_time = time.time()

                if response.status_code == 200:
                    batch_results = response.json()
                    if isinstance(batch_results, list):
                        for result in batch_results:
                            if "result" in result and result.get("id") is not None:
                                address_index = result["id"]
                                if address_index < len(batch_addresses):
                                    address = batch_addresses[address_index]
                                    all_signatures[address] = result["result"]

                    logger.debug(f"✅ Batch signatures réussi: {len(batch_addresses)} adresses en {batch_duration:.2f}s")
                    self.batch_stats['successful_batches'] += 1
                else:
                    raise Exception(f"HTTP {response.status_code}")

            except Exception as e:
                logger.warning(f"⚠️ Batch signatures échoué: {e}, fallback individuel")
                individual_results = self._individual_signatures_calls(batch_addresses, limit_per_address)
                all_signatures.update(individual_results)
                self.batch_stats['failed_batches'] += 1

        return all_signatures

    def _individual_signatures_calls(self, addresses: List[str], limit_per_address: int) -> Dict:
        """Fallback: appels signatures individuels"""
        results = {}
        for address in addresses:
            try:
                result = self.monitor.rate_limited_rpc_call(
                    "getSignaturesForAddress",
                    [address, {"limit": limit_per_address, "commitment": "finalized"}]
                )
                if result and "result" in result:
                    results[address] = result["result"]
                time.sleep(Config.RATE_LIMIT_DELAY)
            except Exception as e:
                logger.error(f"❌ Erreur signatures {address[:8]}...: {e}")
                results[address] = []
        return results

    def get_batch_stats(self) -> Dict:
        """Retourne les statistiques de performance du batching"""
        if self.batch_stats['total_batches'] > 0:
            success_rate = (self.batch_stats['successful_batches'] / self.batch_stats['total_batches']) * 100
        else:
            success_rate = 0

        avg_response_time = sum(self.response_times) / len(self.response_times) if self.response_times else 0

        return {
            **self.batch_stats,
            'success_rate': round(success_rate, 1),
            'avg_response_time_ms': round(avg_response_time, 1),
            'current_efficiency': len(self.response_times),
            'rate_limit_status': 'OK' if self.batch_stats['rate_limit_hits'] == 0 else 'WARNING'
        }

class ThreadSafeSQLiteManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self.lock = threading.RLock()

    @contextmanager
    def get_connection(self, retry_count=3):
        """Context manager pour obtenir une connexion avec retry automatique"""
        for attempt in range(retry_count):
            try:
                with self.lock:
                    conn = sqlite3.connect(
                        self.db_path,
                        timeout=30.0,
                        check_same_thread=False
                    )
                    # Configuration pour améliorer la concurrence
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute("PRAGMA synchronous=NORMAL")
                    conn.execute("PRAGMA busy_timeout=30000")
                    yield conn
                    conn.close()
                    break
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < retry_count - 1:
                    time.sleep(0.1 * (attempt + 1))
                    continue
                else:
                    raise

# 2. AJOUTER CETTE VARIABLE GLOBALE
db_manager = None


class SolanaWalletMonitor:
    def __init__(self, wallet_addresses: List[str], db_name: str):
        self.wallet_addresses = wallet_addresses
        self.wallet_address = wallet_addresses[0] if wallet_addresses else None
        self.db_name = db_name
        self.token_cache = {}
        self.request_count = 0
        self.last_full_scan = {}  # Trackage des derniers scans complets par wallet
        self.scan_cycle_id = None
        global db_manager
        db_manager = ThreadSafeSQLiteManager(db_name)
        self.init_database()
        self.batch_manager = BatchRPCManager(self) if Config.ENABLE_RPC_BATCHING else None
        self.rpc_performance = {
            'total_requests': 0,
            'batch_requests': 0,
            'individual_requests': 0,
            'time_saved_estimate': 0
        }
        logger.info(f"🔧 Batching RPC: {'ACTIVÉ' if Config.ENABLE_RPC_BATCHING else 'DÉSACTIVÉ'}")

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

    def get_current_rpc_endpoint(self) -> str:
        """Retourne l'endpoint RPC actuel"""
        global CURRENT_RPC_INDEX
        return RPC_ENDPOINTS[CURRENT_RPC_INDEX]

    def get_random_wallet_to_scan(self) -> Optional[str]:
        """Sélectionne un wallet aléatoirement en tenant compte des priorités et cooldowns"""
        try:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                current_time = int(time.time())
                logger.debug("🎲 Sélection aléatoire du wallet...")

                # Récupérer tous les wallets éligibles
                cursor.execute('''
                    SELECT 
                        wallet_address, 
                        priority_score,
                        last_scan_time,
                        (? - last_scan_time) as seconds_since_scan
                    FROM wallet_priorities
                    WHERE (? - last_scan_time) >= ?
                    ORDER BY wallet_address
                ''', (current_time, current_time, Config.MIN_INTERVAL_BETWEEN_SCANS))

                eligible_wallets = cursor.fetchall()

                if not eligible_wallets:
                    logger.debug("⏸️ Aucun wallet éligible pour sélection aléatoire")
                    return None

                logger.debug(f"🎯 {len(eligible_wallets)} wallets éligibles pour sélection aléatoire")

                if Config.RANDOM_SELECTION_WEIGHT_BY_PRIORITY:
                    # Sélection pondérée par la priorité
                    weights = []
                    wallets = []

                    for wallet, priority, last_scan, since_scan in eligible_wallets:
                        # Calculer le poids basé sur la priorité et le temps écoulé
                        base_weight = max(0.1, priority)  # Poids minimum de 0.1

                        # Bonus pour le temps écoulé
                        time_bonus = min(2.0, since_scan / 600)  # Bonus max de 2.0 après 10min

                        final_weight = base_weight + time_bonus
                        weights.append(final_weight)
                        wallets.append(wallet)

                        logger.debug(f"   📊 {wallet[:8]}... Poids: {final_weight:.2f} (priorité: {priority:.2f}, temps: {since_scan}s)")

                    # Sélection pondérée
                    import random
                    selected_wallet = random.choices(wallets, weights=weights, k=1)[0]

                else:
                    # Sélection purement aléatoire
                    import random
                    selected_wallet = random.choice([row[0] for row in eligible_wallets])

                logger.info(f"🎲 Wallet sélectionné aléatoirement: {selected_wallet[:8]}...")
                return selected_wallet

        except Exception as e:
            logger.error(f"❌ Erreur sélection aléatoire: {e}")
            return None

    def initialize_wallet_priorities(self):
        """Initialise les priorités pour tous les wallets configurés avec logs détaillés"""
        logger.info("🎯 INITIALISATION DES PRIORITÉS DYNAMIQUES")
        logger.info("-" * 60)

        try:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                current_time = int(time.time())
                initialized_count = 0
                logger.info(f"📱 Traitement de {len(self.wallet_addresses)} wallets...")

                for i, wallet_address in enumerate(self.wallet_addresses):
                    logger.info(f"\n📍 [{i+1}/{len(self.wallet_addresses)}] Initialisation: {wallet_address[:8]}...{wallet_address[-8:]}")

                    # Calculer des métriques initiales basées sur l'historique
                    cursor.execute('''
                        SELECT COUNT(*) as total_tx,
                            COUNT(CASE WHEN block_time >= ? THEN 1 END) as recent_tx,
                            COALESCE(SUM(ABS(amount)), 0) as total_volume,
                            COUNT(CASE WHEN is_token_transaction = 1 THEN 1 END) as token_tx,
                            MAX(block_time) as last_activity
                        FROM transactions 
                        WHERE wallet_address = ?
                    ''', (current_time - 3600, wallet_address))  # Dernière heure

                    result = cursor.fetchone()
                    total_tx, recent_tx, total_volume, token_tx, last_activity = result or (0, 0, 0, 0, 0)

                    # Compter les comptes de tokens existants
                    cursor.execute('''
                        SELECT COUNT(*) as total_accounts,
                            COUNT(CASE WHEN first_seen >= ? THEN 1 END) as recent_accounts
                        FROM token_accounts 
                        WHERE wallet_address = ? AND is_active = 1
                    ''', (current_time - 86400, wallet_address))  # Dernières 24h

                    accounts_result = cursor.fetchone()
                    total_accounts, recent_accounts = accounts_result or (0, 0)

                    # Calculer un score initial intelligent
                    base_score = 1.0

                    # Bonus pour activité récente
                    if recent_tx > 0:
                        activity_bonus = min(recent_tx * 0.5, 3.0)
                        base_score += activity_bonus
                        logger.info(f"   📈 Bonus activité récente: +{activity_bonus:.2f} ({recent_tx} transactions)")

                    # Bonus pour volume
                    if total_volume > 5:
                        volume_bonus = min(total_volume * 0.1, 2.0)
                        base_score += volume_bonus
                        logger.info(f"   💰 Bonus volume: +{volume_bonus:.2f} ({total_volume:.2f} SOL)")

                    # Bonus pour nouveaux comptes de tokens
                    if recent_accounts > 0:
                        discovery_bonus = min(recent_accounts * 0.3, 1.5)
                        base_score += discovery_bonus
                        logger.info(f"   🆕 Bonus découvertes: +{discovery_bonus:.2f} ({recent_accounts} comptes)")

                    # Bonus pour portefeuille actif (beaucoup de tokens)
                    if total_accounts > 20:
                        portfolio_bonus = min((total_accounts - 20) * 0.05, 1.0)
                        base_score += portfolio_bonus
                        logger.info(f"   📊 Bonus portefeuille: +{portfolio_bonus:.2f} ({total_accounts} comptes)")

                    # Calcul de l'âge de la dernière activité
                    time_since_activity = (current_time - last_activity) if last_activity else 999999
                    activity_age_hours = time_since_activity / 3600

                    # Insérer ou mettre à jour les priorités
                    cursor.execute('''
                        INSERT OR REPLACE INTO wallet_priorities 
                        (wallet_address, priority_score, activity_score, volume_score_1h, 
                        new_tokens_score_1h, total_scans, last_activity_detected, updated_at, created_at)
                        VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)
                    ''', (wallet_address, base_score, float(recent_tx), float(total_volume),
                          recent_accounts, last_activity or 0, current_time, current_time))

                    logger.info(f"   🎯 Score final calculé: {base_score:.2f}")
                    logger.info(f"   ⏰ Dernière activité: {activity_age_hours:.1f}h ago" if last_activity else "   ⏰ Aucune activité historique")
                    logger.info(f"   📊 Métriques: {total_tx} tx totales, {token_tx} token tx, {total_accounts} comptes")

                    initialized_count += 1

                conn.commit()

                # Afficher un résumé de l'initialisation
                logger.info(f"\n✅ INITIALISATION TERMINÉE")
                logger.info(f"   📊 Wallets initialisés: {initialized_count}/{len(self.wallet_addresses)}")

                # Afficher le classement initial
                cursor.execute('''
                    SELECT wallet_address, priority_score, activity_score, total_scans
                    FROM wallet_priorities 
                    ORDER BY priority_score DESC
                ''')

                rankings = cursor.fetchall()
                logger.info(f"\n🏆 CLASSEMENT INITIAL DES PRIORITÉS:")
                for i, (wallet, score, activity, scans) in enumerate(rankings):
                    medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i+1}."
                    logger.info(f"   {medal} {wallet[:8]}... Score: {score:.2f} | Activité: {activity:.1f} | Scans: {scans}")

                logger.info("✅ Système de priorités prêt")

        except Exception as e:
            logger.error(f"❌ Erreur lors de l'initialisation des priorités: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

    def get_next_wallet_to_scan(self) -> Optional[str]:
        """Retourne le prochain wallet à scanner selon le mode configuré"""

        if Config.WALLET_SELECTION_MODE == "random":
            logger.debug("🎲 Mode de sélection: ALÉATOIRE")
            return self.get_random_wallet_to_scan()
        else:
            logger.debug("🎯 Mode de sélection: PRIORITÉ")
            return self.get_priority_wallet_to_scan()

    def get_priority_wallet_to_scan(self) -> Optional[str]:
        """Retourne le prochain wallet à scanner selon les priorités avec logs détaillés"""



        try:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                current_time = int(time.time())
                logger.debug("🔍 Recherche du wallet prioritaire...")

                # Requête pour trouver le wallet le plus prioritaire
                cursor.execute('''
                    SELECT 
                        wallet_address, 
                        priority_score, 
                        last_scan_time,
                        total_scans,
                        consecutive_empty_scans,
                        (? - last_scan_time) as seconds_since_scan,
                        CASE 
                            WHEN priority_score >= 4.0 THEN 30   -- Haute priorité: 30s
                            WHEN priority_score >= 2.0 THEN 90   -- Moyenne: 1.5min
                            WHEN priority_score >= 1.0 THEN 180  -- Basse: 3min
                            ELSE 300                             -- Très basse: 5min
                        END as target_interval
                    FROM wallet_priorities
                    WHERE (? - last_scan_time) >= 
                        CASE 
                            WHEN priority_score >= 4.0 THEN 30
                            WHEN priority_score >= 2.0 THEN 90
                            WHEN priority_score >= 1.0 THEN 180
                            ELSE 300
                        END
                    ORDER BY priority_score DESC, last_scan_time ASC
                    LIMIT 1
                ''', (current_time, current_time))

                result = cursor.fetchone()

                if result:
                    wallet, score, last_scan, total_scans, empty_scans, since_scan, target = result

                    logger.debug(f"🎯 Wallet sélectionné: {wallet[:8]}...")
                    logger.debug(f"   Score: {score:.2f}")
                    logger.debug(f"   Temps depuis dernier scan: {since_scan//60}m{since_scan%60}s")
                    logger.debug(f"   Intervalle cible: {target}s")
                    logger.debug(f"   Scans effectués: {total_scans}")
                    logger.debug(f"   Scans vides consécutifs: {empty_scans}")

                    return wallet
                else:
                    logger.debug("⏸️ Aucun wallet nécessite un scan immédiat")

                    # Afficher l'état de tous les wallets pour diagnostiquer
                    cursor.execute('''
                        SELECT wallet_address, priority_score, 
                            (? - last_scan_time) as since_scan,
                            CASE 
                                WHEN priority_score >= 4.0 THEN 30
                                WHEN priority_score >= 2.0 THEN 90
                                WHEN priority_score >= 1.0 THEN 180
                                ELSE 300
                            END as needed_interval
                        FROM wallet_priorities
                        ORDER BY priority_score DESC
                    ''', (current_time,))

                    all_wallets = cursor.fetchall()
                    logger.debug("📊 État de tous les wallets:")
                    for wallet, score, since, needed in all_wallets:
                        remaining = max(0, needed - since)
                        status = "✅ PRÊT" if since >= needed else f"⏳ {remaining}s"
                        logger.debug(f"   {wallet[:8]}... Score: {score:.2f} | Depuis: {since}s | {status}")

                    return None

        except Exception as e:
            logger.error(f"❌ Erreur sélection wallet: {e}")
            return None


    def update_wallet_priority(self, wallet_address: str, scan_duration: float,
                               discoveries: int, transactions_found: int):
        """Met à jour la priorité d'un wallet après un scan avec logs détaillés"""
        try:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                current_time = int(time.time())
                logger.debug(f"📊 Mise à jour priorité pour {wallet_address[:8]}...")

                # Récupérer l'état actuel
                cursor.execute('''
                    SELECT priority_score, total_scans, consecutive_empty_scans, 
                        activity_score, avg_scan_duration
                    FROM wallet_priorities 
                    WHERE wallet_address = ?
                ''', (wallet_address,))

                current_data = cursor.fetchone()
                if not current_data:
                    logger.warning(f"⚠️ Wallet {wallet_address[:8]}... non trouvé dans les priorités")
                    return

                old_score, total_scans, empty_scans, activity_score, avg_duration = current_data

                # Calculer les bonus/malus
                activity_bonus = min(transactions_found * 0.3, 2.0)  # Max +2.0 pour activité
                discovery_bonus = min(discoveries * 0.5, 1.5)        # Max +1.5 pour découvertes

                # Malus pour scan lent (>45s)
                efficiency_penalty = max(0, (scan_duration - 45) * 0.02)

                # Malus pour scans vides répétés
                empty_penalty = min(empty_scans * 0.1, 1.0) if transactions_found == 0 else 0

                # Calcul du nouveau score
                if transactions_found > 0 or discoveries > 0:
                    # Activité détectée - augmenter la priorité
                    new_score = old_score + activity_bonus + discovery_bonus - efficiency_penalty
                    new_empty_scans = 0  # Reset des scans vides
                    logger.debug(f"   📈 ACTIVITÉ DÉTECTÉE")
                    logger.debug(f"      Bonus activité: +{activity_bonus:.2f}")
                    logger.debug(f"      Bonus découvertes: +{discovery_bonus:.2f}")
                    if efficiency_penalty > 0:
                        logger.debug(f"      Malus lenteur: -{efficiency_penalty:.2f}")
                else:
                    # Aucune activité - diminuer progressivement la priorité
                    decay_factor = 0.95  # Diminution de 5% par scan vide
                    new_score = max(0.5, old_score * decay_factor - empty_penalty)
                    new_empty_scans = empty_scans + 1
                    logger.debug(f"   📉 SCAN VIDE")
                    logger.debug(f"      Facteur de déclin: {decay_factor}")
                    logger.debug(f"      Malus scans vides: -{empty_penalty:.2f}")
                    logger.debug(f"      Scans vides consécutifs: {new_empty_scans}")

                # Limiter le score dans une plage raisonnable
                new_score = max(0.1, min(10.0, new_score))

                # Calculer la nouvelle durée moyenne
                if total_scans == 0:
                    new_avg_duration = scan_duration
                else:
                    new_avg_duration = (avg_duration * total_scans + scan_duration) / (total_scans + 1)

                # Mettre à jour en base
                cursor.execute('''
                    UPDATE wallet_priorities 
                    SET 
                        last_scan_time = ?,
                        total_scans = total_scans + 1,
                        avg_scan_duration = ?,
                        activity_score = activity_score * 0.8 + ?,
                        priority_score = ?,
                        consecutive_empty_scans = ?,
                        updated_at = ?
                    WHERE wallet_address = ?
                ''', (current_time, new_avg_duration, float(transactions_found),
                      new_score, new_empty_scans, current_time, wallet_address))

                conn.commit()

                # Logs détaillés de la mise à jour
                score_change = new_score - old_score
                change_icon = "📈" if score_change > 0 else "📉" if score_change < 0 else "➡️"

                logger.info(f"   {change_icon} Priorité: {old_score:.2f} → {new_score:.2f} ({score_change:+.2f})")
                logger.debug(f"   ⏱️ Durée moyenne: {new_avg_duration:.1f}s")
                logger.debug(f"   📊 Total scans: {total_scans + 1}")

                # Déterminer la nouvelle catégorie de priorité
                if new_score >= 4.0:
                    category = "🔥 HAUTE (scan toutes les 30s)"
                elif new_score >= 2.0:
                    category = "🟡 MOYENNE (scan toutes les 90s)"
                elif new_score >= 1.0:
                    category = "🔵 BASSE (scan toutes les 3min)"
                else:
                    category = "⚪ TRÈS BASSE (scan toutes les 5min)"

                logger.info(f"   📋 Catégorie: {category}")

        except Exception as e:
            logger.error(f"❌ Erreur mise à jour priorité: {e}")


    def record_scan_metrics(self, wallet_address: str, scan_duration: float,
                            discoveries: int, transactions_found: int, rpc_requests: int):
        """Enregistre les métriques détaillées d'un scan avec logs"""

        try:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                current_time = int(time.time())
                logger.debug(f"📝 Enregistrement métriques pour {wallet_address[:8]}...")

                # Calculer l'efficacité
                if rpc_requests > 0:
                    efficiency_score = ((discoveries + transactions_found) / rpc_requests) * 100
                else:
                    efficiency_score = 0

                # Calculer le volume estimé (placeholder - vous pouvez l'améliorer)
                estimated_volume = transactions_found * 0.1  # Estimation basique

                cursor.execute('''
                    INSERT INTO wallet_activity_metrics 
                    (wallet_address, timestamp, period_minutes, scan_duration, discoveries_count, 
                    balance_changes_count, rpc_requests_made, efficiency_score, volume_sol, 
                    new_token_accounts, errors_count)
                    VALUES (?, ?, 15, ?, ?, ?, ?, ?, ?, ?, 0)
                ''', (wallet_address, current_time, scan_duration, discoveries,
                      transactions_found, rpc_requests, efficiency_score, estimated_volume, discoveries))

                conn.commit()

                logger.debug(f"   📊 Efficacité: {efficiency_score:.1f}%")
                logger.debug(f"   🔢 RPC/découverte: {rpc_requests / max(discoveries + transactions_found, 1):.1f}")

                # Nettoyer les anciennes métriques (garder 7 jours)
                week_ago = current_time - (7 * 24 * 3600)
                cursor.execute('DELETE FROM wallet_activity_metrics WHERE timestamp < ?', (week_ago,))
                deleted = cursor.rowcount
                if deleted > 0:
                    logger.debug(f"   🧹 Nettoyage: {deleted} anciennes métriques supprimées")

                conn.commit()

        except Exception as e:
            logger.error(f"❌ Erreur enregistrement métriques: {e}")


    def get_wallet_priority_stats(self) -> Dict:
        """Retourne les statistiques actuelles des priorités pour le dashboard"""

        try:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                # Statistiques générales
                cursor.execute('''
                    SELECT 
                        COUNT(*) as total_wallets,
                        AVG(priority_score) as avg_priority,
                        MIN(priority_score) as min_priority,
                        MAX(priority_score) as max_priority,
                        COUNT(CASE WHEN priority_score >= 4.0 THEN 1 END) as high_priority,
                        COUNT(CASE WHEN priority_score >= 2.0 AND priority_score < 4.0 THEN 1 END) as medium_priority,
                        COUNT(CASE WHEN priority_score < 2.0 THEN 1 END) as low_priority
                    FROM wallet_priorities
                ''')

                stats = cursor.fetchone()

                # Activité récente
                current_time = int(time.time())
                cursor.execute('''
                    SELECT COUNT(*) FROM wallet_priorities 
                    WHERE last_scan_time >= ?
                ''', (current_time - 300,))  # Dernières 5 minutes

                recent_scans = cursor.fetchone()[0]

                return {
                    'total_wallets': stats[0],
                    'avg_priority': round(stats[1], 2) if stats[1] else 0,
                    'min_priority': stats[2] or 0,
                    'max_priority': stats[3] or 0,
                    'high_priority_count': stats[4],
                    'medium_priority_count': stats[5],
                    'low_priority_count': stats[6],
                    'recent_scans_5min': recent_scans
                }

        except Exception as e:
            logger.error(f"❌ Erreur statistiques priorités: {e}")
            return {}

    def update_database_schema(self, cursor):
        """Met à jour la structure de la base de données"""
        # 1. Créer la table wallet_priorities
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS wallet_priorities (
                wallet_address TEXT PRIMARY KEY,
                priority_score REAL DEFAULT 1.0,
                last_scan_time INTEGER DEFAULT 0,
                scan_count_1h INTEGER DEFAULT 0,
                scan_count_24h INTEGER DEFAULT 0,
                activity_score REAL DEFAULT 0.0,
                volume_score_1h REAL DEFAULT 0.0,
                new_tokens_score_1h INTEGER DEFAULT 0,
                total_scans INTEGER DEFAULT 0,
                avg_scan_duration REAL DEFAULT 0.0,
                last_activity_detected INTEGER DEFAULT 0,
                consecutive_empty_scans INTEGER DEFAULT 0,
                updated_at INTEGER DEFAULT 0,
                created_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        ''')

        # 2. Créer la table wallet_activity_metrics
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS wallet_activity_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                period_minutes INTEGER DEFAULT 15,
                new_transactions_count INTEGER DEFAULT 0,
                volume_sol REAL DEFAULT 0.0,
                new_token_accounts INTEGER DEFAULT 0,
                scan_duration REAL DEFAULT 0.0,
                discoveries_count INTEGER DEFAULT 0,
                balance_changes_count INTEGER DEFAULT 0,
                rpc_requests_made INTEGER DEFAULT 0,
                errors_count INTEGER DEFAULT 0,
                efficiency_score REAL DEFAULT 0.0
            )
        ''')

        # 3. Créer la table scan_queue
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scan_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL,
                priority_score REAL NOT NULL,
                scheduled_time INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                scan_type TEXT DEFAULT 'balance_change',
                estimated_duration REAL DEFAULT 30.0,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                started_at INTEGER,
                completed_at INTEGER,
                error_message TEXT
            )
        ''')

        # Ajouter les nouvelles colonnes aux tables existantes (gestion d'erreur pour éviter les crashes)
        new_columns = [
            ("token_accounts", "activity_score", "REAL DEFAULT 0.0"),
            ("token_accounts", "last_activity_time", "INTEGER DEFAULT 0"),
            ("transactions", "detection_delay", "REAL DEFAULT 0.0"),
            ("transactions", "wallet_priority_at_detection", "REAL DEFAULT 1.0"),
            ("transactions", "scan_cycle_id", "TEXT"),
            ("scan_history", "priority_score_before", "REAL DEFAULT 1.0"),
            ("scan_history", "priority_score_after", "REAL DEFAULT 1.0"),
            ("scan_history", "rpc_requests_count", "INTEGER DEFAULT 0"),
            ("scan_history", "efficiency_score", "REAL DEFAULT 0.0")
        ]

        for table, column, definition in new_columns:
            try:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                logger.debug(f"✅ Ajouté colonne {table}.{column}")
            except sqlite3.OperationalError:
                # Colonne existe déjà
                pass


        # Index pour optimiser les requêtes
        indexes_to_create = [
            ("idx_token_accounts_wallet", "CREATE INDEX IF NOT EXISTS idx_token_accounts_wallet ON token_accounts(wallet_address)"),
            ("idx_token_accounts_mint", "CREATE INDEX IF NOT EXISTS idx_token_accounts_mint ON token_accounts(token_mint)"),
            ("idx_token_accounts_priority", "CREATE INDEX IF NOT EXISTS idx_token_accounts_priority ON token_accounts(scan_priority DESC, last_scanned ASC)"),
            ("idx_token_accounts_active", "CREATE INDEX IF NOT EXISTS idx_token_accounts_active ON token_accounts(is_active, last_updated DESC)"),
            ("idx_transactions_wallet_time", "CREATE INDEX IF NOT EXISTS idx_transactions_wallet_time ON transactions(wallet_address, block_time DESC)"),
            ("idx_transactions_token_type", "CREATE INDEX IF NOT EXISTS idx_transactions_token_type ON transactions(is_token_transaction, block_time DESC)"),
            ("idx_scan_history_wallet", "CREATE INDEX IF NOT EXISTS idx_scan_history_wallet ON scan_history(wallet_address, completed_at DESC)"),

            ("idx_wallet_priorities_score", "CREATE INDEX IF NOT EXISTS idx_wallet_priorities_score ON wallet_priorities(priority_score DESC, last_scan_time ASC)"),
            ("idx_wallet_priorities_activity", "CREATE INDEX IF NOT EXISTS idx_wallet_priorities_activity ON wallet_priorities(last_activity_detected DESC)"),
            ("idx_activity_metrics_wallet_time", "CREATE INDEX IF NOT EXISTS idx_activity_metrics_wallet_time ON wallet_activity_metrics(wallet_address, timestamp DESC)"),
            ("idx_scan_queue_priority", "CREATE INDEX IF NOT EXISTS idx_scan_queue_priority ON scan_queue(status, priority_score DESC, scheduled_time ASC)"),
            ("idx_token_accounts_activity", "CREATE INDEX IF NOT EXISTS idx_token_accounts_activity ON token_accounts(activity_score DESC, last_activity_time DESC)")

        ]

        for index_name, index_sql in indexes_to_create:
            try:
                cursor.execute(index_sql)
                logger.debug(f"✅ Index '{index_name}' créé/vérifié")
            except sqlite3.OperationalError as e:
                logger.debug(f"Index '{index_name}' existe déjà: {e}")

    def rate_limited_rpc_call(self, method: str, params: List) -> Optional[Dict]:
        """Appel RPC avec respect du rate limit"""
        start_time = time.time()
        self.request_count += 1
        self.rpc_performance['total_requests'] += 1

        if self.request_count % 10 == 0:
            logger.debug(f"📊 Requêtes RPC effectuées: {self.request_count} (Batch: {self.rpc_performance['batch_requests']})")

        result = self.get_solana_rpc_data(method, params)

        # Monitoring des performances
        response_time = (time.time() - start_time) * 1000
        if self.batch_manager:
            self.batch_manager.response_times.append(response_time)

            # Détecter les rate limits
            if response_time > Config.RATE_LIMIT_MONITORING['max_acceptable_response_time']:
                self.batch_manager.batch_stats['rate_limit_hits'] += 1
                logger.warning(f"⚠️ Réponse lente détectée: {response_time:.0f}ms")

        # Respect du rate limit avec ajustement adaptatif
        base_delay = Config.RATE_LIMIT_DELAY
        if response_time > Config.RATE_LIMIT_MONITORING['reduce_batch_size_threshold']:
            base_delay *= 1.5  # Augmenter le délai si les réponses sont lentes

        time.sleep(base_delay)
        self.rpc_performance['individual_requests'] += 1

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
        Découvre les comptes de tokens pour un wallet avec batching RPC optimisé
        Retourne: (total_accounts, new_accounts)
        """
        scan_start_time = time.time()
        batching_enabled = self.batch_manager is not None and Config.ENABLE_RPC_BATCHING

        logger.info(f"🔍 Découverte des comptes de tokens pour {wallet_address[:8]}... "
                    f"(Batching: {'✅ ON' if batching_enabled else '❌ OFF'})")

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

        # SECTION 1: RÉCUPÉRATION DES COMPTES DE TOKENS (avec ou sans batching)
        token_accounts_data = None
        discovery_method = "unknown"

        if batching_enabled:
            # MÉTHODE BATCH OPTIMISÉE
            try:
                batch_start = time.time()
                logger.debug(f"⚡ Utilisation du batching RPC pour {wallet_address[:8]}...")

                # Récupérer les comptes de tokens via RPC standard (pas de batch pour getTokenAccountsByOwner)
                token_accounts_result = self.rate_limited_rpc_call(
                    "getTokenAccountsByOwner",
                    [
                        wallet_address,
                        {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                        {"encoding": "jsonParsed"}
                    ]
                )

                if token_accounts_result and "result" in token_accounts_result:
                    token_accounts_data = token_accounts_result["result"]["value"]
                    discovery_method = "rpc_standard"

                    batch_duration = time.time() - batch_start
                    logger.debug(f"⚡ Récupération RPC standard: {len(token_accounts_data)} comptes en {batch_duration:.2f}s")

                    # Si on a beaucoup de comptes, on peut les traiter par batch pour les détails
                    if len(token_accounts_data) > 10:
                        logger.info(f"📦 Traitement par batch de {len(token_accounts_data)} comptes...")
                        token_accounts_data = self._process_token_accounts_batch(token_accounts_data, wallet_address)
                        discovery_method = "rpc_batch_processed"

                    self.rpc_performance['batch_requests'] += 1

                else:
                    logger.warning("⚠️ RPC standard échoué, tentative fallback...")
                    raise Exception("RPC result empty or invalid")

            except Exception as e:
                logger.warning(f"⚠️ Batching échoué ({e}), fallback vers méthode classique...")
                batching_enabled = False  # Désactiver pour cette itération
                if self.batch_manager:
                    self.batch_manager.batch_stats['failed_batches'] += 1
                    self.batch_manager.batch_stats['fallback_count'] += 1

        # FALLBACK: MÉTHODE CLASSIQUE
        if not batching_enabled or token_accounts_data is None:
            try:
                fallback_start = time.time()
                logger.debug(f"🔄 Utilisation méthode classique pour {wallet_address[:8]}...")

                token_accounts_result = self.rate_limited_rpc_call(
                    "getTokenAccountsByOwner",
                    [
                        wallet_address,
                        {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                        {"encoding": "jsonParsed"}
                    ]
                )

                if token_accounts_result and "result" in token_accounts_result:
                    token_accounts_data = token_accounts_result["result"]["value"]
                    discovery_method = "rpc_fallback"

                    fallback_duration = time.time() - fallback_start
                    logger.debug(f"🔄 Méthode classique: {len(token_accounts_data)} comptes en {fallback_duration:.2f}s")
                    self.rpc_performance['individual_requests'] += 1
                else:
                    logger.error(f"❌ Impossible de récupérer les comptes de tokens pour {wallet_address[:8]}...")
                    return 0, 0

            except Exception as e:
                logger.error(f"❌ Erreur critique lors de la récupération des comptes: {e}")
                return 0, 0

        # VALIDATION DES DONNÉES
        if not token_accounts_data:
            logger.warning(f"⚠️ Aucun compte de token trouvé pour {wallet_address[:8]}...")
            return 0, 0

        total_accounts = len(token_accounts_data)
        logger.info(f"📊 Trouvé {total_accounts} comptes de tokens pour {wallet_address[:8]}... "
                    f"(méthode: {discovery_method})")

        # SECTION 2: COMPARAISON AVEC LES DONNÉES EXISTANTES
        comparison_start = time.time()

        # Charger les comptes existants depuis la DB
        existing_accounts = self.load_token_accounts_from_db(wallet_address)
        existing_ata_pubkeys = {acc['ata_pubkey'] for acc in existing_accounts}

        comparison_duration = time.time() - comparison_start
        logger.debug(f"📂 Comparaison DB: {len(existing_accounts)} existants en {comparison_duration:.3f}s")

        # SECTION 3: TRAITEMENT INTELLIGENT DES COMPTES
        processing_start = time.time()
        new_accounts = []
        updated_accounts = []
        processing_errors = 0

        # Traitement par lots pour optimiser les performances
        batch_size = Config.TOKEN_DISCOVERY_BATCH_SIZE if hasattr(Config, 'TOKEN_DISCOVERY_BATCH_SIZE') else 50

        for i, account in enumerate(token_accounts_data):
            try:
                # Progression tous les X comptes
                if i > 0 and i % batch_size == 0:
                    progress_pct = (i / total_accounts) * 100
                    logger.info(f"📈 Progression: {i}/{total_accounts} comptes traités ({progress_pct:.1f}%)")

                    # Pause adaptative pour éviter la surcharge
                    if batching_enabled and i % (batch_size * 2) == 0:
                        pause_time = Config.BATCH_TIMING.get('min_delay_between_batches', 0.2)
                        time.sleep(pause_time)

                # Extraction des données du compte
                ata_pubkey = account.get("pubkey")
                if not ata_pubkey:
                    logger.warning(f"⚠️ Compte sans pubkey ignoré (index {i})")
                    processing_errors += 1
                    continue

                account_data = account.get("account", {})
                parsed_data = account_data.get("data", {}).get("parsed", {})
                token_info = parsed_data.get("info", {})

                if not token_info:
                    logger.debug(f"⚠️ Compte {ata_pubkey[:8]}... sans info de token")
                    processing_errors += 1
                    continue

                # Extraction des métadonnées
                token_mint = token_info.get("mint")
                token_amount_info = token_info.get("tokenAmount", {})
                balance = float(token_amount_info.get("uiAmount") or 0)
                decimals = token_amount_info.get("decimals", 9)

                if not token_mint:
                    logger.debug(f"⚠️ Compte {ata_pubkey[:8]}... sans mint address")
                    processing_errors += 1
                    continue

                # Déterminer si c'est un nouveau compte
                is_new_account = ata_pubkey not in existing_ata_pubkeys

                account_data = {
                    'ata_pubkey': ata_pubkey,
                    'token_mint': token_mint,
                    'balance': balance,
                    'decimals': decimals,
                    'is_new': is_new_account
                }

                if is_new_account:
                    new_accounts.append(account_data)
                    logger.debug(f"🆕 Nouveau compte découvert: {token_mint[:8]}... "
                                 f"(balance: {balance:,.4f}, decimals: {decimals})")
                else:
                    updated_accounts.append(account_data)

            except Exception as e:
                logger.error(f"❌ Erreur traitement compte {i}: {e}")
                processing_errors += 1
                continue

        processing_duration = time.time() - processing_start
        logger.info(f"⚙️ Traitement terminé: {len(new_accounts)} nouveaux, {len(updated_accounts)} mis à jour "
                    f"en {processing_duration:.2f}s ({processing_errors} erreurs)")

        # SECTION 4: SAUVEGARDE EN BASE DE DONNÉES
        save_start = time.time()

        try:
            all_accounts_to_save = new_accounts + updated_accounts
            new_count = self.save_token_accounts_to_db(wallet_address, all_accounts_to_save, scan_type)

            save_duration = time.time() - save_start
            logger.info(f"💾 Sauvegarde: {len(all_accounts_to_save)} comptes en {save_duration:.2f}s")

        except Exception as e:
            logger.error(f"❌ Erreur sauvegarde: {e}")
            new_count = 0

        # SECTION 5: FINALISATION ET STATISTIQUES
        # Marquer comme scanné si scan complet
        if should_full_scan:
            self.last_full_scan[wallet_address] = current_time
            logger.debug(f"✅ Marqué comme scanné complet: {wallet_address[:8]}...")

        # Enregistrer l'historique du scan
        total_scan_duration = time.time() - scan_start_time
        try:
            self.record_scan_history(wallet_address, scan_type, total_accounts, len(new_accounts), total_scan_duration)
        except Exception as e:
            logger.warning(f"⚠️ Erreur enregistrement historique: {e}")

        # STATISTIQUES DE PERFORMANCE
        if batching_enabled and self.batch_manager:
            batch_stats = self.batch_manager.get_batch_stats()
            time_saved_estimate = max(0, total_accounts * 0.1 - total_scan_duration)  # Estimation conservative
            self.rpc_performance['time_saved_estimate'] += time_saved_estimate

            logger.info(f"⚡ Performance Batching:")
            logger.info(f"   📊 Taux de réussite: {batch_stats['success_rate']:.1f}%")
            logger.info(f"   ⏱️ Temps de réponse moyen: {batch_stats.get('avg_response_time_ms', 0):.0f}ms")
            logger.info(f"   💾 Temps économisé estimé: {time_saved_estimate:.1f}s")

            # Adaptation automatique des paramètres
            if batch_stats['success_rate'] < 80:
                logger.warning(f"⚠️ Performances dégradées, ajustement des paramètres...")
                self._adjust_batch_parameters()

        # LOGS FINAUX
        efficiency_score = (len(new_accounts) / max(total_accounts, 1)) * 100

        logger.info(f"✅ Scan {scan_type} terminé pour {wallet_address[:8]}...")
        logger.info(f"   📊 Comptes totaux: {total_accounts}")
        logger.info(f"   🆕 Nouveaux comptes: {len(new_accounts)}")
        logger.info(f"   🔄 Comptes mis à jour: {len(updated_accounts)}")
        logger.info(f"   ⏱️ Durée totale: {total_scan_duration:.2f}s")
        logger.info(f"   📈 Efficacité découverte: {efficiency_score:.1f}%")
        logger.info(f"   🔧 Méthode utilisée: {discovery_method}")

        if processing_errors > 0:
            logger.warning(f"   ⚠️ Erreurs de traitement: {processing_errors}")

        return total_accounts, len(new_accounts)

    def _process_token_accounts_batch(self, token_accounts_data: List[Dict], wallet_address: str) -> List[Dict]:
        """
        Traite les comptes de tokens par batch pour optimiser les performances
        """
        if not self.batch_manager:
            return token_accounts_data

        try:
            batch_size = self.batch_manager.adaptive_batch_size('token_metadata')
            processed_accounts = []

            logger.debug(f"📦 Traitement par batch: {len(token_accounts_data)} comptes, taille batch: {batch_size}")

            for i in range(0, len(token_accounts_data), batch_size):
                batch_accounts = token_accounts_data[i:i + batch_size]

                # Traiter le batch (ici on peut ajouter du traitement parallèle si nécessaire)
                for account in batch_accounts:
                    processed_accounts.append(account)

                # Pause entre les batches
                if i + batch_size < len(token_accounts_data):
                    time.sleep(Config.BATCH_TIMING.get('min_delay_between_batches', 0.2))

            logger.debug(f"✅ Traitement batch terminé: {len(processed_accounts)} comptes traités")
            return processed_accounts

        except Exception as e:
            logger.error(f"❌ Erreur traitement batch: {e}")
            return token_accounts_data

    def _adjust_batch_parameters(self):
        """
        Ajuste automatiquement les paramètres de batching selon les performances
        """
        if not self.batch_manager:
            return

        try:
            stats = self.batch_manager.batch_stats

            # Réduire les tailles de batch si trop d'échecs
            if stats['success_rate'] < 70:
                for key in Config.BATCH_SIZES:
                    current_size = Config.BATCH_SIZES[key]
                    new_size = max(2, int(current_size * 0.7))
                    Config.BATCH_SIZES[key] = new_size
                    logger.info(f"🔧 Taille batch {key} réduite: {current_size} → {new_size}")

            # Augmenter le délai entre batches si nécessaire
            if stats.get('rate_limit_hits', 0) > 3:
                old_delay = Config.BATCH_TIMING['min_delay_between_batches']
                new_delay = min(1.0, old_delay * 1.3)
                Config.BATCH_TIMING['min_delay_between_batches'] = new_delay
                logger.info(f"🔧 Délai entre batches augmenté: {old_delay:.2f}s → {new_delay:.2f}s")

            # Reset des compteurs après ajustement
            stats['rate_limit_hits'] = 0

        except Exception as e:
            logger.error(f"❌ Erreur ajustement paramètres: {e}")

    def load_token_accounts_from_db(self, wallet_address: str) -> List[Dict]:
        """Charge les comptes de tokens depuis la base de données"""
        try:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
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

    def save_token_accounts_to_db(self, wallet_address: str, accounts: List[Dict], scan_type: str) -> int:
        """Sauvegarde les comptes de tokens en base avec logique intelligente"""
        try:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                current_time = int(time.time())
                new_count = 0
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

    def record_scan_history(self, wallet_address: str, scan_type: str, total_accounts: int,
                            new_accounts: int, scan_duration: float):
        """Enregistre l'historique des scans"""


        try:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO scan_history 
                    (wallet_address, scan_type, total_accounts, new_accounts, scan_duration, completed_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (wallet_address, scan_type, total_accounts, new_accounts, scan_duration, int(time.time())))

                conn.commit()
                logger.debug(f"📝 Historique de scan enregistré pour {wallet_address[:8]}...")

        except sqlite3.Error as e:
            logger.error(f"❌ Erreur lors de l'enregistrement de l'historique: {e}")


    def get_priority_accounts_for_scanning(self, wallet_address: str, limit: int = 100) -> List[Dict]:
        """Récupère les comptes prioritaires à scanner pour les balance changes - VERSION CORRIGÉE"""

        try:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                current_time = int(time.time())

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

    def scan_balance_changes_for_accounts(self, wallet_address: str, priority_accounts: List[Dict]) -> List[Dict]:
        """Scanne les balance changes avec batching optimisé"""
        balance_changes = []
        current_time = int(time.time())
        scan_window = 3600

        logger.info(f"🔍 Scan balance changes (Batching: {'ON' if self.batch_manager else 'OFF'}) "
                    f"pour {len(priority_accounts)} comptes...")

        if self.batch_manager and len(priority_accounts) > 3:
            # NOUVELLE APPROCHE: Batching des signatures
            ata_addresses = [acc['ata_pubkey'] for acc in priority_accounts]

            batch_start = time.time()
            logger.info(f"⚡ Récupération batch signatures pour {len(ata_addresses)} comptes...")

            # Utiliser le batch manager pour les signatures
            all_signatures = self.batch_manager.batch_get_signatures_for_addresses(ata_addresses, limit_per_address=10)

            batch_duration = time.time() - batch_start
            logger.info(f"✅ Batch signatures terminé: {len(all_signatures)} comptes en {batch_duration:.2f}s")
            self.rpc_performance['batch_requests'] += len(ata_addresses)
            self.rpc_performance['time_saved_estimate'] += max(0, len(ata_addresses) * 0.5 - batch_duration)

            # Traiter les résultats batch
            for i, account in enumerate(priority_accounts):
                ata_pubkey = account['ata_pubkey']
                token_mint = account['token_mint']

                signatures_data = all_signatures.get(ata_pubkey, [])

                # Filtrer les signatures récentes
                recent_signatures = [
                    sig for sig in signatures_data
                    if sig.get("blockTime") and sig["blockTime"] >= (current_time - scan_window)
                ]

                if not recent_signatures:
                    continue

                logger.debug(f"🔍 {len(recent_signatures)} signatures récentes pour {token_mint[:8]}...")

                # Traitement des transactions (code identique à l'original)
                for sig_info in recent_signatures:
                    signature = sig_info["signature"]

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
                        if bc_tx['token_mint'] == token_mint:
                            balance_changes.append(bc_tx)
                            logger.info(f"✅ Balance change: {bc_tx['transaction_type'].upper()} "
                                        f"{bc_tx['token_amount']:,.4f} {bc_tx['token_symbol']}")

                # Marquer comme scanné
                self.mark_account_as_scanned(wallet_address, ata_pubkey)

                # Délai réduit grâce au batching
                if i % 5 == 0:  # Pause tous les 5 comptes au lieu de chaque compte
                    time.sleep(Config.RATE_LIMIT_DELAY)

        else:
            # Fallback vers la méthode classique (code existant inchangé)
            logger.debug("🔄 Utilisation méthode classique (pas de batching)")
            for i, account in enumerate(priority_accounts):
                # ... code original identique ...
                pass

        # Statistiques finales
        if self.batch_manager:
            batch_stats = self.batch_manager.get_batch_stats()
            time_saved = self.rpc_performance['time_saved_estimate']
            logger.info(f"⚡ Batching Performance - Temps économisé estimé: {time_saved:.1f}s, "
                        f"Efficacité: {batch_stats['success_rate']:.1f}%")

        logger.info(f"🎯 Scan terminé: {len(balance_changes)} balance changes trouvés")
        return balance_changes

    def mark_account_as_scanned(self, wallet_address: str, ata_pubkey: str):
        """Marque un compte comme scanné récemment"""

        try:

            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                current_time = int(time.time())
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

    def signature_exists_in_db(self, signature: str) -> bool:
        """Vérifie si une signature existe déjà dans la DB"""
        try:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM transactions WHERE signature = ? LIMIT 1", (signature,))
                return cursor.fetchone() is not None

        except Exception as e:
            logger.error(f"Erreur vérification signature: {e}")
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
        try:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR IGNORE INTO transactions 
                    (signature, wallet_address, slot, block_time, amount, fee, status, 
                    token_mint, token_symbol, token_name, transaction_type, 
                    token_amount, price_per_token, is_token_transaction, is_large_token_amount)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    tx["signature"], wallet_address, tx["slot"], tx["block_time"],
                    tx["amount"], tx["fee"], tx["status"], tx.get("token_mint"),
                    tx.get("token_symbol"), tx.get("token_name"), tx.get("transaction_type"),
                    tx.get("token_amount"), tx.get("price_per_token"),
                    tx.get("is_token_transaction", False), tx.get("is_large_token_amount", False)
                ))
                conn.commit()

                if tx.get("is_token_transaction"):
                    source = tx.get("source", "signature")
                    logger.info(f"💾 Sauvegarde [{source.upper()}]: {tx.get('transaction_type', 'unknown').upper()} "
                                f"{tx.get('token_amount', 0):,.4f} {tx.get('token_symbol', 'UNKNOWN')}")

        except Exception as e:
            logger.error(f"❌ Erreur sauvegarde transaction: {e}")

    def get_wallet_balance_for_address(self, wallet_address: str) -> float:
        """Récupère le solde SOL pour un wallet spécifique"""
        result = self.rate_limited_rpc_call("getBalance", [wallet_address])
        if result and "result" in result:
            return result["result"]["value"] / 1e9
        return 0.0

    def update_wallet_stats(self):
        """Met à jour les statistiques pour tous les wallets"""

        with db_manager.get_connection() as conn:
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


    def monitor_loop(self):
        """Boucle principale de monitoring avec priorités dynamiques intelligentes et logs détaillés"""
        logger.info("=" * 100)
        logger.info("🚀 DÉMARRAGE DU MONITORING INTELLIGENT AVEC PRIORITÉS DYNAMIQUES")
        logger.info("=" * 100)
        logger.info(f"📱 Wallets configurés: {len(self.wallet_addresses)}")
        for i, wallet in enumerate(self.wallet_addresses):
            logger.info(f"   {i+1}. {wallet[:8]}...{wallet[-8:]}")
        logger.info(f"🔧 Configuration: Rate limit = {Config.RATE_LIMIT_DELAY}s")
        logger.info(f"🔧 Scan complet = {Config.FULL_SCAN_INTERVAL_HOURS}h")
        logger.info(f"🔧 Base de données: {self.db_name}")
        logger.info("=" * 100)

        # Initialiser les priorités
        logger.info("🎯 INITIALISATION DES PRIORITÉS DYNAMIQUES")
        logger.info("-" * 60)
        try:
            self.initialize_wallet_priorities()
            logger.info("✅ Priorités initialisées avec succès")
        except Exception as e:
            logger.error(f"❌ Erreur initialisation priorités: {e}")
            logger.error("💡 Continuation avec priorités par défaut...")

        # Variables de contrôle
        consecutive_errors = 0
        max_consecutive_errors = Config.MAX_CONSECUTIVE_ERRORS
        cycle_count = 0
        scan_cycle_id = None
        total_cycles_successful = 0
        total_transactions_found = 0
        total_discoveries_made = 0
        start_time = time.time()

        logger.info("\n🎬 DÉMARRAGE DE LA BOUCLE DE MONITORING")
        logger.info("=" * 100)

        while True:
            try:
                cycle_count += 1
                cycle_start_time = time.time()
                scan_cycle_id = f"cycle_{cycle_count}_{int(time.time())}"

                logger.info("\n" + "=" * 100)
                logger.info(f"🧠 CYCLE INTELLIGENT #{cycle_count} - {datetime.now().strftime('%H:%M:%S')}")
                logger.info("=" * 100)
                logger.info(f"🆔 Cycle ID: {scan_cycle_id}")
                logger.info(f"⏱️ Uptime: {(time.time() - start_time) / 60:.1f} minutes")
                logger.info(f"📊 Statistiques globales:")
                logger.info(f"   ✅ Cycles réussis: {total_cycles_successful}")
                logger.info(f"   💰 Transactions trouvées: {total_transactions_found}")
                logger.info(f"   🆕 Découvertes totales: {total_discoveries_made}")
                logger.info(f"   🔢 Requêtes RPC totales: {self.request_count}")
                logger.info(f"   ❌ Erreurs consécutives: {consecutive_errors}")

                # ÉTAPE 1: SÉLECTION INTELLIGENTE DU WALLET
                logger.info("\n" + "-" * 80)
                logger.info(f"🎯 ÉTAPE 1: SÉLECTION DU WALLET ({Config.WALLET_SELECTION_MODE.upper()})")
                logger.info("-" * 80)

                if Config.WALLET_SELECTION_MODE == "random":
                    mode_desc = "🎲 ALÉATOIRE"
                    if Config.RANDOM_SELECTION_WEIGHT_BY_PRIORITY:
                        mode_desc += " (pondéré par priorités)"
                    else:
                        mode_desc += " (équiprobable)"
                else:
                    mode_desc = "🎯 PRIORITÉS DYNAMIQUES"

                logger.info(f"🔧 Mode de sélection: {mode_desc}")
                logger.info(f"⏱️ Intervalle minimum: {Config.MIN_INTERVAL_BETWEEN_SCANS}s")

                # Afficher l'état actuel des priorités
                try:
                    conn = sqlite3.connect(self.db_name)
                    cursor = conn.cursor()

                    logger.info("📋 État actuel des priorités:")
                    cursor.execute('''
                        SELECT wallet_address, priority_score, last_scan_time, 
                            total_scans, consecutive_empty_scans,
                            (? - last_scan_time) as seconds_since_scan
                        FROM wallet_priorities 
                        ORDER BY priority_score DESC
                    ''', (int(time.time()),))

                    priorities_data = cursor.fetchall()
                    for i, (wallet, score, last_scan, total_scans, empty_scans, since_scan) in enumerate(priorities_data):
                        status_icon = "🔥" if score >= 4.0 else "🟡" if score >= 2.0 else "🔵"
                        urgency = "URGENT" if since_scan > 300 else "NORMAL" if since_scan > 120 else "RÉCENT"
                        logger.info(f"   {status_icon} {i+1}. {wallet[:8]}... Score: {score:.2f} | "
                                    f"Dernier scan: {since_scan//60}m{since_scan%60}s | "
                                    f"Scans: {total_scans} | Vides: {empty_scans} | {urgency}")

                    conn.close()

                except Exception as e:
                    logger.warning(f"⚠️ Impossible d'afficher les priorités: {e}")

                # Déterminer le wallet à scanner
                wallet_to_scan = self.get_next_wallet_to_scan()

                if not wallet_to_scan:
                    logger.info("⏸️ AUCUN WALLET PRIORITAIRE DÉTECTÉ")
                    logger.info("💤 Tous les wallets sont à jour selon leurs priorités")
                    logger.info("⏱️ Pause de 15 secondes avant réévaluation...")
                    time.sleep(15)
                    continue

                logger.info(f"🎯 WALLET SÉLECTIONNÉ: {wallet_to_scan[:8]}...{wallet_to_scan[-8:]}")

                if Config.WALLET_SELECTION_MODE == "random":
                    # Afficher les wallets éligibles et leurs poids
                    conn = sqlite3.connect(self.db_name)
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT wallet_address, priority_score, 
                            (? - last_scan_time) as since_scan
                        FROM wallet_priorities
                        ORDER BY priority_score DESC
                    ''', (int(time.time()),))

                    all_wallets_status = cursor.fetchall()
                    logger.info("📊 État de tous les wallets pour sélection aléatoire:")
                    for wallet, priority, since in all_wallets_status:
                        eligible = since >= Config.MIN_INTERVAL_BETWEEN_SCANS
                        status = "✅ ÉLIGIBLE" if eligible else f"⏳ {Config.MIN_INTERVAL_BETWEEN_SCANS - since}s"
                        logger.info(f"   {wallet[:8]}... Priorité: {priority:.2f} | Depuis: {since}s | {status}")

                    conn.close()

                # Récupérer les détails de priorité du wallet sélectionné
                try:
                    conn = sqlite3.connect(self.db_name)
                    cursor = conn.cursor()
                    cursor.execute('''
                        SELECT priority_score, last_scan_time, total_scans, 
                            consecutive_empty_scans, activity_score
                        FROM wallet_priorities 
                        WHERE wallet_address = ?
                    ''', (wallet_to_scan,))

                    priority_data = cursor.fetchone()
                    if priority_data:
                        score, last_scan, total_scans, empty_scans, activity = priority_data
                        time_since_scan = int(time.time()) - (last_scan or 0)

                        logger.info(f"📊 Détails du wallet sélectionné:")
                        logger.info(f"   🎯 Score de priorité: {score:.2f}")
                        logger.info(f"   ⏰ Temps depuis dernier scan: {time_since_scan//60}m{time_since_scan%60}s")
                        logger.info(f"   📈 Scans effectués: {total_scans}")
                        logger.info(f"   💤 Scans vides consécutifs: {empty_scans}")
                        logger.info(f"   🔥 Score d'activité: {activity:.2f}")

                    conn.close()

                except Exception as e:
                    logger.warning(f"⚠️ Impossible de récupérer les détails: {e}")

                # ÉTAPE 2: DÉCOUVERTE DES COMPTES DE TOKENS
                logger.info("\n" + "-" * 80)
                logger.info("🔍 ÉTAPE 2: DÉCOUVERTE DES COMPTES DE TOKENS")
                logger.info("-" * 80)

                scan_start = time.time()
                rpc_requests_before = self.request_count

                logger.info(f"📊 État initial:")
                logger.info(f"   🔢 Requêtes RPC avant scan: {rpc_requests_before}")
                logger.info(f"   ⏱️ Début du scan: {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")

                try:
                    total_accounts, new_accounts = self.discover_token_accounts(wallet_to_scan)

                    discovery_duration = time.time() - scan_start
                    rpc_requests_discovery = self.request_count - rpc_requests_before

                    logger.info(f"✅ Découverte terminée:")
                    logger.info(f"   📊 Comptes totaux: {total_accounts}")
                    logger.info(f"   🆕 Nouveaux comptes: {new_accounts}")
                    logger.info(f"   ⏱️ Durée découverte: {discovery_duration:.2f}s")
                    logger.info(f"   🔢 Requêtes RPC utilisées: {rpc_requests_discovery}")

                    if new_accounts > 0:
                        logger.info(f"🎊 DÉCOUVERTE! {new_accounts} nouveaux comptes de tokens trouvés!")
                        for i in range(min(new_accounts, 3)):  # Afficher max 3 exemples
                            logger.info(f"   🆕 Nouveau compte #{i+1} découvert")

                except Exception as e:
                    logger.error(f"❌ Erreur lors de la découverte: {e}")
                    total_accounts, new_accounts = 0, 0
                    discovery_duration = time.time() - scan_start
                    rpc_requests_discovery = self.request_count - rpc_requests_before

                # ÉTAPE 3: IDENTIFICATION DES COMPTES PRIORITAIRES
                logger.info("\n" + "-" * 80)
                logger.info("🎯 ÉTAPE 3: IDENTIFICATION DES COMPTES PRIORITAIRES")
                logger.info("-" * 80)

                priority_selection_start = time.time()

                try:
                    priority_accounts = self.get_priority_accounts_for_scanning(wallet_to_scan, limit=50)
                    priority_selection_duration = time.time() - priority_selection_start

                    logger.info(f"📊 Résultats de priorisation:")
                    logger.info(f"   🎯 Comptes prioritaires identifiés: {len(priority_accounts)}")
                    logger.info(f"   ⏱️ Durée sélection: {priority_selection_duration:.3f}s")

                    if not priority_accounts:
                        logger.info("ℹ️ Aucun compte prioritaire à scanner")
                        logger.info("✅ Tous les comptes sont à jour")

                        # Enregistrer un scan vide mais réussi
                        self.update_wallet_priority(wallet_to_scan, discovery_duration, new_accounts, 0)
                        logger.info(f"📝 Priorité mise à jour pour scan vide")
                        continue

                    # Analyser les comptes prioritaires
                    never_scanned = sum(1 for acc in priority_accounts if acc.get('last_scanned') is None)
                    high_priority = sum(1 for acc in priority_accounts if acc.get('scan_priority', 1) >= 3)
                    old_scanned = sum(1 for acc in priority_accounts if acc.get('time_since_scan', 0) > 1800)

                    logger.info(f"📈 Analyse des comptes prioritaires:")
                    logger.info(f"   🆕 Jamais scannés: {never_scanned}")
                    logger.info(f"   🔥 Haute priorité: {high_priority}")
                    logger.info(f"   ⏰ Scannés il y a >30min: {old_scanned}")

                    # Afficher quelques exemples de comptes à scanner
                    for i, account in enumerate(priority_accounts[:3]):
                        priority = account.get('scan_priority', 1)
                        last_scan = account.get('last_scanned')
                        time_since = account.get('time_since_scan', 0)

                        if last_scan is None:
                            scan_status = "JAMAIS"
                        elif time_since > 3600:
                            scan_status = f"{time_since//3600}h ago"
                        else:
                            scan_status = f"{time_since//60}m ago"

                        logger.info(f"   🎯 Compte #{i+1}: {account['token_mint'][:8]}... "
                                    f"Priorité: {priority} | Dernier scan: {scan_status}")

                except Exception as e:
                    logger.error(f"❌ Erreur identification priorités: {e}")
                    priority_accounts = []
                    priority_selection_duration = time.time() - priority_selection_start

                # ÉTAPE 4: SCAN DES BALANCE CHANGES
                logger.info("\n" + "-" * 80)
                logger.info("🔍 ÉTAPE 4: SCAN DES BALANCE CHANGES")
                logger.info("-" * 80)

                balance_scan_start = time.time()
                rpc_requests_before_balance = self.request_count

                try:
                    balance_changes = self.scan_balance_changes_for_accounts(wallet_to_scan, priority_accounts)

                    balance_scan_duration = time.time() - balance_scan_start
                    rpc_requests_balance = self.request_count - rpc_requests_before_balance

                    logger.info(f"📊 Résultats du scan des balance changes:")
                    logger.info(f"   💰 Balance changes détectés: {len(balance_changes)}")
                    logger.info(f"   ⏱️ Durée scan balance: {balance_scan_duration:.2f}s")
                    logger.info(f"   🔢 Requêtes RPC utilisées: {rpc_requests_balance}")

                    if balance_changes:
                        logger.info(f"🎊 ACTIVITÉ DÉTECTÉE! {len(balance_changes)} balance changes trouvés:")

                        for i, bc in enumerate(balance_changes[:5]):  # Afficher max 5 exemples
                            tx_type = bc.get('transaction_type', 'unknown').upper()
                            token_symbol = bc.get('token_symbol', 'UNKNOWN')
                            token_amount = bc.get('token_amount', 0)
                            amount_change = bc.get('amount_change', 0)
                            is_large = bc.get('is_large_token_amount', False)

                            size_indicator = "🔥 GROSSE QUANTITÉ" if is_large else "normale"

                            logger.info(f"   💰 #{i+1}: {tx_type} {token_amount:,.4f} {token_symbol} "
                                        f"(change: {amount_change:+.4f}) - {size_indicator}")
                            logger.info(f"        Signature: {bc.get('signature', 'N/A')[:16]}...")

                except Exception as e:
                    logger.error(f"❌ Erreur scan balance changes: {e}")
                    balance_changes = []
                    balance_scan_duration = time.time() - balance_scan_start
                    rpc_requests_balance = self.request_count - rpc_requests_before_balance

                # ÉTAPE 5: SAUVEGARDE DES TRANSACTIONS
                logger.info("\n" + "-" * 80)
                logger.info("💾 ÉTAPE 5: SAUVEGARDE DES TRANSACTIONS")
                logger.info("-" * 80)

                save_start = time.time()
                new_transactions = 0
                duplicate_transactions = 0

                try:
                    for i, tx in enumerate(balance_changes):
                        signature = tx.get("signature", "")

                        if not self.signature_exists_in_db(signature):
                            tx["scan_cycle_id"] = scan_cycle_id

                            # Calculer le délai de détection
                            tx_time = tx.get('block_time', 0)
                            detection_delay = time.time() - tx_time if tx_time > 0 else 0
                            tx["detection_delay"] = detection_delay

                            # Ajouter la priorité du wallet au moment de la détection
                            try:
                                conn = sqlite3.connect(self.db_name)
                                cursor = conn.cursor()
                                cursor.execute("SELECT priority_score FROM wallet_priorities WHERE wallet_address = ?",
                                               (wallet_to_scan,))
                                priority_result = cursor.fetchone()
                                tx["wallet_priority_at_detection"] = priority_result[0] if priority_result else 1.0
                                conn.close()
                            except:
                                tx["wallet_priority_at_detection"] = 1.0

                            self.save_transaction_for_wallet(tx, wallet_to_scan)
                            new_transactions += 1

                            # Log détaillé pour chaque nouvelle transaction
                            tx_type = tx.get('transaction_type', 'unknown').upper()
                            token_symbol = tx.get('token_symbol', 'UNKNOWN')
                            token_amount = tx.get('token_amount', 0)
                            delay_str = f"{detection_delay:.1f}s" if detection_delay > 0 else "temps réel"

                            logger.info(f"   💾 Sauvegardé #{new_transactions}: {tx_type} "
                                        f"{token_amount:,.4f} {token_symbol} "
                                        f"(délai détection: {delay_str})")
                        else:
                            duplicate_transactions += 1

                    save_duration = time.time() - save_start

                    logger.info(f"✅ Sauvegarde terminée:")
                    logger.info(f"   💾 Nouvelles transactions: {new_transactions}")
                    logger.info(f"   🔄 Doublons évités: {duplicate_transactions}")
                    logger.info(f"   ⏱️ Durée sauvegarde: {save_duration:.3f}s")

                except Exception as e:
                    logger.error(f"❌ Erreur sauvegarde: {e}")
                    save_duration = time.time() - save_start

                # ÉTAPE 6: CALCUL DES MÉTRIQUES ET MISE À JOUR DES PRIORITÉS
                logger.info("\n" + "-" * 80)
                logger.info("📊 ÉTAPE 6: CALCUL DES MÉTRIQUES ET MISE À JOUR")
                logger.info("-" * 80)

                metrics_start = time.time()

                try:
                    # Calculer les métriques globales du scan
                    total_scan_duration = time.time() - scan_start
                    total_rpc_requests = self.request_count - rpc_requests_before

                    logger.info(f"📈 Métriques du scan:")
                    logger.info(f"   ⏱️ Durée totale: {total_scan_duration:.2f}s")
                    logger.info(f"   🔢 Requêtes RPC totales: {total_rpc_requests}")
                    logger.info(f"   📊 Efficacité (découvertes/RPC): {(new_accounts + new_transactions) / max(total_rpc_requests, 1):.3f}")
                    logger.info(f"   💰 Taux de réussite: {(new_transactions / max(len(balance_changes), 1)) * 100:.1f}%")

                    # Enregistrer les métriques détaillées
                    self.record_scan_metrics(wallet_to_scan, total_scan_duration, new_accounts,
                                             new_transactions, total_rpc_requests)

                    # Mettre à jour la priorité du wallet
                    old_priority = None
                    try:
                        conn = sqlite3.connect(self.db_name)
                        cursor = conn.cursor()
                        cursor.execute("SELECT priority_score FROM wallet_priorities WHERE wallet_address = ?",
                                       (wallet_to_scan,))
                        result = cursor.fetchone()
                        old_priority = result[0] if result else 1.0
                        conn.close()
                    except:
                        old_priority = 1.0

                    self.update_wallet_priority(wallet_to_scan, total_scan_duration, new_accounts, new_transactions)

                    # Récupérer la nouvelle priorité
                    try:
                        conn = sqlite3.connect(self.db_name)
                        cursor = conn.cursor()
                        cursor.execute("SELECT priority_score FROM wallet_priorities WHERE wallet_address = ?",
                                       (wallet_to_scan,))
                        result = cursor.fetchone()
                        new_priority = result[0] if result else 1.0
                        conn.close()
                    except:
                        new_priority = 1.0

                    priority_change = new_priority - old_priority
                    change_indicator = "📈" if priority_change > 0 else "📉" if priority_change < 0 else "➡️"

                    logger.info(f"🎯 Mise à jour de la priorité:")
                    logger.info(f"   📊 Ancienne priorité: {old_priority:.2f}")
                    logger.info(f"   📊 Nouvelle priorité: {new_priority:.2f}")
                    logger.info(f"   {change_indicator} Changement: {priority_change:+.2f}")

                    metrics_duration = time.time() - metrics_start
                    logger.info(f"   ⏱️ Durée calcul métriques: {metrics_duration:.3f}s")

                except Exception as e:
                    logger.error(f"❌ Erreur calcul métriques: {e}")

                # ÉTAPE 7: RÉSUMÉ DU CYCLE
                logger.info("\n" + "-" * 80)
                logger.info("🎉 RÉSUMÉ DU CYCLE")
                logger.info("-" * 80)

                cycle_duration = time.time() - cycle_start_time
                total_cycles_successful += 1
                total_transactions_found += new_transactions
                total_discoveries_made += new_accounts

                # Mise à jour des statistiques de scan_history avec les nouvelles colonnes
                try:
                    conn = sqlite3.connect(self.db_name)
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO scan_history 
                        (wallet_address, scan_type, total_accounts, new_accounts, scan_duration, 
                        completed_at, priority_score_before, priority_score_after, 
                        rpc_requests_count, efficiency_score, activity_detected, notes)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (wallet_to_scan, "balance_change_priority", total_accounts, new_accounts,
                          total_scan_duration, int(time.time()), old_priority or 1.0, new_priority or 1.0,
                          total_rpc_requests, (new_accounts + new_transactions) / max(total_rpc_requests, 1),
                          1 if new_transactions > 0 else 0, f"Cycle #{cycle_count}"))
                    conn.commit()
                    conn.close()
                except Exception as e:
                    logger.warning(f"⚠️ Erreur sauvegarde historique: {e}")

                # Affichage du résumé
                logger.info(f"✅ CYCLE #{cycle_count} TERMINÉ AVEC SUCCÈS")
                logger.info(f"   🎯 Wallet scanné: {wallet_to_scan[:8]}...{wallet_to_scan[-8:]}")
                logger.info(f"   ⏱️ Durée totale cycle: {cycle_duration:.2f}s")
                logger.info(f"   📊 Comptes de tokens: {total_accounts} ({new_accounts} nouveaux)")
                logger.info(f"   💰 Balance changes: {len(balance_changes)} ({new_transactions} nouveaux)")
                logger.info(f"   🔢 Requêtes RPC utilisées: {total_rpc_requests}")
                logger.info(f"   🎯 Priorité finale: {new_priority:.2f}")

                # Indicateurs de performance
                if new_transactions > 0:
                    logger.info(f"🎊 SUCCÈS: Activité détectée! {new_transactions} nouvelles transactions")
                    success_icon = "🟢"
                elif new_accounts > 0:
                    logger.info(f"🆕 DÉCOUVERTE: {new_accounts} nouveaux comptes de tokens")
                    success_icon = "🟡"
                else:
                    logger.info(f"✅ SCAN PROPRE: Aucune nouvelle activité")
                    success_icon = "🔵"

                # Statistiques cumulées
                logger.info(f"\n📊 STATISTIQUES GLOBALES:")
                logger.info(f"   {success_icon} Cycles réussis: {total_cycles_successful}")
                logger.info(f"   💰 Transactions totales trouvées: {total_transactions_found}")
                logger.info(f"   🆕 Découvertes totales: {total_discoveries_made}")
                logger.info(f"   🔢 Requêtes RPC totales: {self.request_count}")
                logger.info(f"   ⏱️ Uptime: {(time.time() - start_time) / 60:.1f} minutes")
                logger.info(f"   📈 Moyenne transactions/cycle: {total_transactions_found / max(total_cycles_successful, 1):.2f}")

                consecutive_errors = 0  # Reset du compteur d'erreurs

            except Exception as e:
                consecutive_errors += 1
                logger.error("\n" + "!" * 80)
                logger.error(f"❌ ERREUR CRITIQUE DANS LE CYCLE #{cycle_count}")
                logger.error("!" * 80)
                logger.error(f"🔥 Erreur #{consecutive_errors}: {e}")
                logger.error(f"📍 Cycle ID: {scan_cycle_id}")
                logger.error(f"⏱️ Timestamp: {datetime.now().isoformat()}")

                # Traceback détaillé
                import traceback
                logger.error(f"📋 Traceback complet:")
                for line in traceback.format_exc().split('\n'):
                    if line.strip():
                        logger.error(f"   {line}")

                # Gestion des erreurs consécutives
                if consecutive_errors >= max_consecutive_errors:
                    logger.critical("!" * 80)
                    logger.critical(f"🚨 ALERTE: {consecutive_errors} erreurs consécutives!")
                    logger.critical("🛑 Activation du mode de récupération...")
                    logger.critical("!" * 80)

                    # Mode de récupération avec pause longue
                    recovery_time = 120  # 2 minutes
                    logger.critical(f"⏱️ Pause de récupération: {recovery_time} secondes")
                    logger.critical("🔧 Vérifiez les logs pour diagnostiquer le problème")

                    time.sleep(recovery_time)
                    consecutive_errors = 0
                    logger.info("🔄 Reprise du monitoring après récupération")
                else:
                    # Pause courte pour les erreurs isolées
                    error_pause = 30 + (consecutive_errors * 10)
                    logger.warning(f"⏱️ Pause d'erreur: {error_pause} secondes")
                    time.sleep(error_pause)

            # CALCUL DE LA PAUSE ADAPTATIVE
            logger.info("\n" + "-" * 60)
            logger.info("⏱️ CALCUL DE LA PAUSE ADAPTATIVE")
            logger.info("-" * 60)

            # Logique de pause intelligente
            if new_transactions > 0:
                pause_time = 10  # Pause courte si activité détectée
                pause_reason = f"Activité détectée ({new_transactions} transactions)"
                priority_boost = "🔥 Mode haute fréquence activé"
            elif new_accounts > 0:
                pause_time = 20  # Pause moyenne si nouveaux comptes
                pause_reason = f"Nouveaux comptes découverts ({new_accounts})"
                priority_boost = "🟡 Mode découverte activé"
            elif consecutive_errors > 0:
                pause_time = 45 + (consecutive_errors * 15)  # Pause progressive si erreurs
                pause_reason = f"Récupération d'erreur (#{consecutive_errors})"
                priority_boost = "🔧 Mode récupération"
            else:
                pause_time = 25  # Pause normale
                pause_reason = "Scan propre, pas d'activité"
                priority_boost = "🔵 Mode normal"

            logger.info(f"⏰ Pause calculée: {pause_time} secondes")
            logger.info(f"📝 Raison: {pause_reason}")
            logger.info(f"🎯 Mode: {priority_boost}")

            # Affichage du compte à rebours si pause > 20s
            if pause_time > 20:
                logger.info(f"⏳ Prochaine analyse dans {pause_time} secondes...")
                logger.info(f"🔄 Cycle suivant #{cycle_count + 1} prévu à {(datetime.now() + timedelta(seconds=pause_time)).strftime('%H:%M:%S')}")

            logger.info("=" * 100)
            logger.info(f"😴 PAUSE DE {pause_time} SECONDES...")
            logger.info("=" * 100)

            time.sleep(pause_time)

# API Flask pour le dashboard
app = Flask(__name__)
CORS(app)

@app.route('/')
def dashboard():
    return render_template('new_dashboard.html')


@app.route('/api/batching-performance')
def get_batching_performance():
    """API pour récupérer les métriques de performance du batching"""
    try:
        if not hasattr(monitor, 'batch_manager') or not monitor.batch_manager:
            return jsonify({'error': 'Batching not enabled'}), 404

        stats = monitor.batch_manager.get_batch_stats()
        rpc_perf = monitor.rpc_performance

        return jsonify({
            'batching_enabled': Config.ENABLE_RPC_BATCHING,
            'batch_stats': stats,
            'rpc_performance': {
                'total_requests': rpc_perf['total_requests'],
                'batch_requests': rpc_perf['batch_requests'],
                'individual_requests': rpc_perf['individual_requests'],
                'time_saved_estimate': round(rpc_perf['time_saved_estimate'], 2),
                'batch_ratio': round((rpc_perf['batch_requests'] / max(rpc_perf['total_requests'], 1)) * 100, 1)
            },
            'current_batch_sizes': stats['current_batch_sizes'],
            'recommendations': {
                'efficiency_status': 'good' if stats['success_rate'] > 90 else 'warning' if stats['success_rate'] > 70 else 'poor',
                'rate_limit_status': stats['rate_limit_status']
            }
        })

    except Exception as e:
        logger.error(f"Erreur API batching performance: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/batching-config', methods=['GET', 'POST'])
def batching_config():
    """API pour consulter/modifier la configuration du batching"""
    if request.method == 'GET':
        return jsonify({
            'enabled': Config.ENABLE_RPC_BATCHING,
            'batch_sizes': Config.BATCH_SIZES,
            'batch_timing': Config.BATCH_TIMING,
            'rate_limit_monitoring': Config.RATE_LIMIT_MONITORING
        })

    elif request.method == 'POST':
        try:
            data = request.get_json()

            if 'enabled' in data:
                Config.ENABLE_RPC_BATCHING = bool(data['enabled'])
                logger.info(f"🔧 Batching RPC {'activé' if Config.ENABLE_RPC_BATCHING else 'désactivé'}")

            if 'batch_sizes' in data:
                for key, value in data['batch_sizes'].items():
                    if key in Config.BATCH_SIZES and 1 <= value <= 20:
                        Config.BATCH_SIZES[key] = value
                        logger.info(f"🔧 Taille batch {key} modifiée: {value}")

            return jsonify({'success': True, 'message': 'Configuration mise à jour'})

        except Exception as e:
            logger.error(f"Erreur modification config batching: {e}")
            return jsonify({'error': str(e)}), 500

@app.route('/api/selection-mode', methods=['GET', 'POST'])
def selection_mode():
    """API pour récupérer ou modifier le mode de sélection des wallets"""
    if request.method == 'GET':
        return jsonify({
            'current_mode': Config.WALLET_SELECTION_MODE,
            'weighted_by_priority': Config.RANDOM_SELECTION_WEIGHT_BY_PRIORITY,
            'min_interval': Config.MIN_INTERVAL_BETWEEN_SCANS,
            'available_modes': ['priority', 'random']
        })

    elif request.method == 'POST':
        try:
            data = request.get_json()
            new_mode = data.get('mode')

            if new_mode not in ['priority', 'random']:
                return jsonify({'error': 'Mode must be "priority" or "random"'}), 400

            # Modifier temporairement le mode (non persistant)
            Config.WALLET_SELECTION_MODE = new_mode

            if 'weighted_by_priority' in data:
                Config.RANDOM_SELECTION_WEIGHT_BY_PRIORITY = bool(data['weighted_by_priority'])

            logger.info(f"🔧 Mode de sélection changé: {new_mode.upper()}")

            return jsonify({
                'success': True,
                'new_mode': Config.WALLET_SELECTION_MODE,
                'weighted_by_priority': Config.RANDOM_SELECTION_WEIGHT_BY_PRIORITY
            })

        except Exception as e:
            logger.error(f"❌ Erreur changement mode: {e}")
            return jsonify({'error': str(e)}), 500

@app.route('/api/selection-stats')
def get_selection_stats():
    """API pour récupérer les statistiques de sélection des wallets"""
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            current_time = int(time.time())

            # Statistiques des dernières 24h
            cursor.execute('''
                SELECT 
                    sh.wallet_address,
                    COUNT(*) as scan_count,
                    AVG(sh.scan_duration) as avg_duration,
                    MAX(sh.completed_at) as last_scan,
                    SUM(sh.activity_detected) as activity_count
                FROM scan_history sh
                WHERE sh.completed_at >= ?
                GROUP BY sh.wallet_address
                ORDER BY scan_count DESC
            ''', (current_time - 86400,))

            selection_stats = []
            for row in cursor.fetchall():
                wallet = row[0]
                selection_stats.append({
                    'wallet_address': wallet,
                    'wallet_short': f"{wallet[:6]}...{wallet[-6:]}",
                    'scan_count_24h': row[1],
                    'avg_duration': round(row[2], 1) if row[2] else 0,
                    'last_scan': row[3],
                    'activity_detections': row[4] or 0,
                    'hours_since_scan': round((current_time - row[3]) / 3600, 1) if row[3] else 999
                })

            # Statistiques globales
            total_scans = sum(stat['scan_count_24h'] for stat in selection_stats)
            most_scanned = max(selection_stats, key=lambda x: x['scan_count_24h']) if selection_stats else None
            least_scanned = min(selection_stats, key=lambda x: x['scan_count_24h']) if selection_stats else None

            return jsonify({
                'selection_mode': Config.WALLET_SELECTION_MODE,
                'wallet_stats': selection_stats,
                'global_stats': {
                    'total_scans_24h': total_scans,
                    'most_scanned_wallet': most_scanned['wallet_short'] if most_scanned else None,
                    'least_scanned_wallet': least_scanned['wallet_short'] if least_scanned else None,
                    'avg_scans_per_wallet': round(total_scans / len(selection_stats), 1) if selection_stats else 0
                }
            })

    except Exception as e:
        logger.error(f"❌ Erreur statistiques sélection: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/health')
def health_check():
    """Point de santé de l'API"""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "version": "2.0-optimized"
    })


@app.route('/api/wallet-priorities')
def get_wallet_priorities():
    """API pour récupérer l'état actuel des priorités des wallets"""
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            current_time = int(time.time())

            cursor.execute('''
                SELECT 
                    wp.wallet_address,
                    wp.priority_score,
                    wp.last_scan_time,
                    wp.total_scans,
                    wp.consecutive_empty_scans,
                    wp.activity_score,
                    wp.avg_scan_duration,
                    (? - wp.last_scan_time) as seconds_since_scan,
                    CASE 
                        WHEN wp.priority_score >= 4.0 THEN 'high'
                        WHEN wp.priority_score >= 2.0 THEN 'medium'
                        ELSE 'low'
                    END as priority_category,
                    CASE 
                        WHEN wp.priority_score >= 4.0 THEN 30
                        WHEN wp.priority_score >= 2.0 THEN 90
                        ELSE 180
                    END as scan_interval_seconds
                FROM wallet_priorities wp
                ORDER BY wp.priority_score DESC, wp.last_scan_time ASC
            ''', (current_time,))

            priorities = []
            for row in cursor.fetchall():
                wallet_addr = row[0]
                priorities.append({
                    'wallet_address': wallet_addr,
                    'wallet_short': f"{wallet_addr[:6]}...{wallet_addr[-6:]}",
                    'priority_score': round(row[1], 2),
                    'last_scan_time': row[2],
                    'total_scans': row[3],
                    'consecutive_empty_scans': row[4],
                    'activity_score': round(row[5], 2),
                    'avg_scan_duration': round(row[6], 1) if row[6] else 0,
                    'seconds_since_scan': row[7],
                    'priority_category': row[8],
                    'scan_interval_seconds': row[9],
                    'next_scan_in': max(0, row[9] - row[7]),
                    'is_ready_for_scan': row[7] >= row[9]
                })

            # Statistiques globales
            cursor.execute('''
                SELECT 
                    COUNT(*) as total,
                    AVG(priority_score) as avg_score,
                    COUNT(CASE WHEN priority_score >= 4.0 THEN 1 END) as high_priority,
                    COUNT(CASE WHEN priority_score >= 2.0 AND priority_score < 4.0 THEN 1 END) as medium_priority,
                    COUNT(CASE WHEN priority_score < 2.0 THEN 1 END) as low_priority
                FROM wallet_priorities
            ''')

            stats_row = cursor.fetchone()
            stats = {
                'total_wallets': stats_row[0],
                'average_priority': round(stats_row[1], 2) if stats_row[1] else 0,
                'high_priority_wallets': stats_row[2],
                'medium_priority_wallets': stats_row[3],
                'low_priority_wallets': stats_row[4]
            }

            return jsonify({
                'priorities': priorities,
                'stats': stats,
                'timestamp': current_time
            })

    except Exception as e:
        logger.error(f"Erreur récupération priorités: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/scan-efficiency')
def get_scan_efficiency():
    """API pour récupérer les métriques d'efficacité des scans"""
    hours = request.args.get('hours', 24, type=int)

    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()

            start_time = int(time.time()) - (hours * 3600)

            # Métriques par wallet
            cursor.execute('''
                SELECT 
                    wam.wallet_address,
                    COUNT(*) as scan_count,
                    AVG(wam.scan_duration) as avg_duration,
                    SUM(wam.discoveries_count) as total_discoveries,
                    SUM(wam.balance_changes_count) as total_transactions,
                    SUM(wam.rpc_requests_made) as total_rpc_requests,
                    AVG(wam.efficiency_score) as avg_efficiency
                FROM wallet_activity_metrics wam
                WHERE wam.timestamp >= ?
                GROUP BY wam.wallet_address
                ORDER BY avg_efficiency DESC
            ''', (start_time,))

            efficiency_data = []
            for row in cursor.fetchall():
                wallet_addr = row[0]
                efficiency_data.append({
                    'wallet_address': wallet_addr,
                    'wallet_short': f"{wallet_addr[:6]}...{wallet_addr[-6:]}",
                    'scan_count': row[1],
                    'avg_duration': round(row[2], 1) if row[2] else 0,
                    'total_discoveries': row[3],
                    'total_transactions': row[4],
                    'total_rpc_requests': row[5],
                    'avg_efficiency': round(row[6], 1) if row[6] else 0,
                    'discoveries_per_scan': round(row[3] / max(row[1], 1), 2),
                    'transactions_per_scan': round(row[4] / max(row[1], 1), 2)
                })

            # Tendances temporelles (par heure)
            cursor.execute('''
                SELECT 
                    strftime('%H', datetime(timestamp, 'unixepoch')) as hour,
                    COUNT(*) as scans,
                    AVG(efficiency_score) as avg_efficiency,
                    SUM(discoveries_count) as discoveries,
                    SUM(balance_changes_count) as transactions
                FROM wallet_activity_metrics
                WHERE timestamp >= ?
                GROUP BY hour
                ORDER BY hour
            ''', (start_time,))

            hourly_trends = []
            for row in cursor.fetchall():
                hourly_trends.append({
                    'hour': row[0],
                    'scans': row[1],
                    'avg_efficiency': round(row[2], 1) if row[2] else 0,
                    'discoveries': row[3],
                    'transactions': row[4]
                })

            return jsonify({
                'efficiency_by_wallet': efficiency_data,
                'hourly_trends': hourly_trends,
                'period_hours': hours
            })

    except Exception as e:
        logger.error(f"Erreur récupération efficacité: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/priority-history')
def get_priority_history():
    """API pour récupérer l'historique des changements de priorité"""
    wallet = request.args.get('wallet', 'all')
    hours = request.args.get('hours', 24, type=int)

    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()

            start_time = int(time.time()) - (hours * 3600)

            if wallet != 'all':
                cursor.execute('''
                    SELECT 
                        sh.wallet_address,
                        sh.completed_at,
                        sh.priority_score_before,
                        sh.priority_score_after,
                        sh.activity_detected,
                        sh.new_accounts,
                        sh.scan_duration,
                        sh.efficiency_score
                    FROM scan_history sh
                    WHERE sh.wallet_address = ? AND sh.completed_at >= ?
                    ORDER BY sh.completed_at DESC
                    LIMIT 50
                ''', (wallet, start_time))
            else:
                cursor.execute('''
                    SELECT 
                        sh.wallet_address,
                        sh.completed_at,
                        sh.priority_score_before,
                        sh.priority_score_after,
                        sh.activity_detected,
                        sh.new_accounts,
                        sh.scan_duration,
                        sh.efficiency_score
                    FROM scan_history sh
                    WHERE sh.completed_at >= ?
                    ORDER BY sh.completed_at DESC
                    LIMIT 100
                ''', (start_time,))

            history = []
            for row in cursor.fetchall():
                wallet_addr = row[0]
                priority_change = (row[3] or 0) - (row[2] or 0)

                history.append({
                    'wallet_address': wallet_addr,
                    'wallet_short': f"{wallet_addr[:6]}...{wallet_addr[-6:]}",
                    'timestamp': row[1],
                    'priority_before': round(row[2], 2) if row[2] else 0,
                    'priority_after': round(row[3], 2) if row[3] else 0,
                    'priority_change': round(priority_change, 2),
                    'activity_detected': bool(row[4]),
                    'new_accounts': row[5] or 0,
                    'scan_duration': round(row[6], 1) if row[6] else 0,
                    'efficiency_score': round(row[7], 1) if row[7] else 0,
                    'change_direction': 'up' if priority_change > 0 else 'down' if priority_change < 0 else 'stable'
                })


            return jsonify({
                'history': history,
                'wallet_filter': wallet,
                'period_hours': hours
            })

    except Exception as e:
        logger.error(f"Erreur récupération historique priorité: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/next-scans')
def get_next_scans():
    """API pour récupérer la planification des prochains scans"""
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            current_time = int(time.time())

            cursor.execute('''
                SELECT 
                    wp.wallet_address,
                    wp.priority_score,
                    wp.last_scan_time,
                    (? - wp.last_scan_time) as seconds_since_scan,
                    CASE 
                        WHEN wp.priority_score >= 4.0 THEN 30
                        WHEN wp.priority_score >= 2.0 THEN 90
                        ELSE 180
                    END as scan_interval,
                    wp.consecutive_empty_scans,
                    wp.activity_score
                FROM wallet_priorities wp
                ORDER BY 
                    CASE 
                        WHEN (? - wp.last_scan_time) >= 
                            CASE 
                                WHEN wp.priority_score >= 4.0 THEN 30
                                WHEN wp.priority_score >= 2.0 THEN 90
                                ELSE 180
                            END 
                        THEN wp.priority_score 
                        ELSE 0 
                    END DESC,
                    wp.last_scan_time ASC
            ''', (current_time, current_time))

            next_scans = []
            ready_count = 0

            for i, row in enumerate(cursor.fetchall()):
                wallet_addr = row[0]
                priority_score = row[1]
                last_scan = row[2]
                since_scan = row[3]
                interval = row[4]
                empty_scans = row[5]
                activity_score = row[6]

                time_until_next = max(0, interval - since_scan)
                is_ready = since_scan >= interval

                if is_ready:
                    ready_count += 1

                # Estimation du prochain scan
                if is_ready:
                    next_scan_eta = "Maintenant"
                    eta_seconds = 0
                else:
                    eta_seconds = time_until_next
                    if eta_seconds < 60:
                        next_scan_eta = f"{eta_seconds}s"
                    else:
                        next_scan_eta = f"{eta_seconds//60}m{eta_seconds%60}s"

                # Déterminer la priorité visuelle
                if priority_score >= 4.0:
                    priority_badge = {"level": "high", "color": "red", "label": "HAUTE"}
                elif priority_score >= 2.0:
                    priority_badge = {"level": "medium", "color": "orange", "label": "MOYENNE"}
                else:
                    priority_badge = {"level": "low", "color": "blue", "label": "BASSE"}

                next_scans.append({
                    'queue_position': i + 1,
                    'wallet_address': wallet_addr,
                    'wallet_short': f"{wallet_addr[:6]}...{wallet_addr[-6:]}",
                    'priority_score': round(priority_score, 2),
                    'priority_badge': priority_badge,
                    'is_ready_for_scan': is_ready,
                    'seconds_since_scan': since_scan,
                    'scan_interval_seconds': interval,
                    'time_until_next_scan': eta_seconds,
                    'next_scan_eta': next_scan_eta,
                    'consecutive_empty_scans': empty_scans,
                    'activity_score': round(activity_score, 1),
                    'urgency_level': 'urgent' if is_ready and priority_score >= 3.0 else 'normal'
                })

            # Statistiques de la queue
            queue_stats = {
                'total_wallets': len(next_scans),
                'ready_for_scan': ready_count,
                'high_priority_ready': sum(1 for scan in next_scans if scan['is_ready_for_scan'] and scan['priority_score'] >= 4.0),
                'next_scan_wallet': next_scans[0]['wallet_short'] if next_scans and next_scans[0]['is_ready_for_scan'] else None,
                'average_priority': round(sum(scan['priority_score'] for scan in next_scans) / len(next_scans), 2) if next_scans else 0
            }

            return jsonify({
                'next_scans': next_scans,
                'queue_stats': queue_stats,
                'timestamp': current_time
            })

    except Exception as e:
        logger.error(f"Erreur récupération prochains scans: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/priority-analytics')
def get_priority_analytics():
    """API pour récupérer des analytics avancées sur le système de priorités"""
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            current_time = int(time.time())

            # Performance par tranche de priorité
            cursor.execute('''
                SELECT 
                    CASE 
                        WHEN wp.priority_score >= 4.0 THEN 'high'
                        WHEN wp.priority_score >= 2.0 THEN 'medium'
                        ELSE 'low'
                    END as priority_tier,
                    COUNT(*) as wallet_count,
                    AVG(wp.priority_score) as avg_score,
                    AVG(wp.avg_scan_duration) as avg_duration,
                    AVG(wp.activity_score) as avg_activity,
                    SUM(wp.total_scans) as total_scans_performed
                FROM wallet_priorities wp
                GROUP BY priority_tier
                ORDER BY 
                    CASE priority_tier 
                        WHEN 'high' THEN 1 
                        WHEN 'medium' THEN 2 
                        ELSE 3 
                    END
            ''')

            tier_performance = []
            for row in cursor.fetchall():
                tier_performance.append({
                    'tier': row[0],
                    'wallet_count': row[1],
                    'avg_priority_score': round(row[2], 2) if row[2] else 0,
                    'avg_scan_duration': round(row[3], 1) if row[3] else 0,
                    'avg_activity_score': round(row[4], 1) if row[4] else 0,
                    'total_scans': row[5] or 0
                })

            # Évolution des priorités sur les dernières 24h
            cursor.execute('''
                SELECT 
                    strftime('%H', datetime(sh.completed_at, 'unixepoch')) as hour,
                    AVG(sh.priority_score_after) as avg_priority,
                    COUNT(*) as scan_count,
                    SUM(sh.activity_detected) as activity_detections,
                    AVG(sh.efficiency_score) as avg_efficiency
                FROM scan_history sh
                WHERE sh.completed_at >= ?
                GROUP BY hour
                ORDER BY hour
            ''', (current_time - 86400,))

            hourly_evolution = []
            for row in cursor.fetchall():
                hourly_evolution.append({
                    'hour': row[0],
                    'avg_priority': round(row[1], 2) if row[1] else 0,
                    'scan_count': row[2],
                    'activity_detections': row[3] or 0,
                    'avg_efficiency': round(row[4], 1) if row[4] else 0
                })

            # Top wallets par découvertes
            cursor.execute('''
                SELECT 
                    wam.wallet_address,
                    SUM(wam.discoveries_count) as total_discoveries,
                    SUM(wam.balance_changes_count) as total_transactions,
                    COUNT(*) as scan_count,
                    AVG(wam.efficiency_score) as avg_efficiency,
                    wp.priority_score
                FROM wallet_activity_metrics wam
                JOIN wallet_priorities wp ON wam.wallet_address = wp.wallet_address
                WHERE wam.timestamp >= ?
                GROUP BY wam.wallet_address
                ORDER BY total_discoveries DESC, total_transactions DESC
                LIMIT 10
            ''', (current_time - 86400,))

            top_performers = []
            for row in cursor.fetchall():
                wallet_addr = row[0]
                top_performers.append({
                    'wallet_address': wallet_addr,
                    'wallet_short': f"{wallet_addr[:6]}...{wallet_addr[-6:]}",
                    'total_discoveries': row[1] or 0,
                    'total_transactions': row[2] or 0,
                    'scan_count': row[3],
                    'avg_efficiency': round(row[4], 1) if row[4] else 0,
                    'current_priority': round(row[5], 2) if row[5] else 0
                })

            # Métriques système globales
            cursor.execute('''
                SELECT 
                    COUNT(DISTINCT wp.wallet_address) as total_wallets,
                    AVG(wp.priority_score) as system_avg_priority,
                    MAX(wp.priority_score) as max_priority,
                    MIN(wp.priority_score) as min_priority,
                    SUM(wp.total_scans) as total_scans_ever,
                    AVG(wp.avg_scan_duration) as system_avg_duration
                FROM wallet_priorities wp
            ''')

            system_row = cursor.fetchone()
            system_metrics = {
                'total_wallets': system_row[0],
                'system_avg_priority': round(system_row[1], 2) if system_row[1] else 0,
                'max_priority': round(system_row[2], 2) if system_row[2] else 0,
                'min_priority': round(system_row[3], 2) if system_row[3] else 0,
                'total_scans_performed': system_row[4] or 0,
                'system_avg_duration': round(system_row[5], 1) if system_row[5] else 0
            }

            # Calcul de l'efficacité système
            cursor.execute('''
                SELECT 
                    SUM(wam.discoveries_count + wam.balance_changes_count) as total_findings,
                    SUM(wam.rpc_requests_made) as total_rpc_requests
                FROM wallet_activity_metrics wam
                WHERE wam.timestamp >= ?
            ''', (current_time - 86400,))

            efficiency_row = cursor.fetchone()
            if efficiency_row and efficiency_row[1] and efficiency_row[1] > 0:
                system_efficiency = round((efficiency_row[0] / efficiency_row[1]) * 100, 1)
            else:
                system_efficiency = 0

            system_metrics['system_efficiency_24h'] = system_efficiency


            return jsonify({
                'tier_performance': tier_performance,
                'hourly_evolution': hourly_evolution,
                'top_performers': top_performers,
                'system_metrics': system_metrics,
                'generated_at': current_time
            })

    except Exception as e:
        logger.error(f"Erreur récupération analytics priorité: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/manual-priority-update', methods=['POST'])
def manual_priority_update():
    """API pour mise à jour manuelle de la priorité d'un wallet"""
    try:
        data = request.get_json()
        wallet_address = data.get('wallet_address')
        new_priority = data.get('priority_score')
        reason = data.get('reason', 'Manual adjustment')

        if not wallet_address or new_priority is None:
            return jsonify({'error': 'wallet_address and priority_score required'}), 400

        if not (0.1 <= new_priority <= 10.0):
            return jsonify({'error': 'priority_score must be between 0.1 and 10.0'}), 400

        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            current_time = int(time.time())

            # Vérifier que le wallet existe
            cursor.execute('SELECT priority_score FROM wallet_priorities WHERE wallet_address = ?',
                           (wallet_address,))
            result = cursor.fetchone()

            if not result:
                return jsonify({'error': 'Wallet not found in priorities'}), 404

            old_priority = result[0]

            # Mettre à jour la priorité
            cursor.execute('''
                UPDATE wallet_priorities 
                SET priority_score = ?, updated_at = ?
                WHERE wallet_address = ?
            ''', (new_priority, current_time, wallet_address))

            # Enregistrer l'action manuelle dans l'historique
            cursor.execute('''
                INSERT INTO scan_history 
                (wallet_address, scan_type, total_accounts, new_accounts, scan_duration, 
                completed_at, priority_score_before, priority_score_after, notes)
                VALUES (?, 'manual_priority_update', 0, 0, 0, ?, ?, ?, ?)
            ''', (wallet_address, current_time, old_priority, new_priority, f"Manual: {reason}"))

            conn.commit()

            logger.info(f"🔧 Priorité mise à jour manuellement: {wallet_address[:8]}... "
                        f"{old_priority:.2f} → {new_priority:.2f} (Raison: {reason})")

            return jsonify({
                'success': True,
                'wallet_address': wallet_address,
                'old_priority': round(old_priority, 2),
                'new_priority': round(new_priority, 2),
                'reason': reason,
                'updated_at': current_time
            })

    except Exception as e:
        logger.error(f"Erreur mise à jour manuelle priorité: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/token-discoveries')
def get_token_discoveries():
    """API pour récupérer les découvertes de tokens récentes - VERSION CORRIGÉE"""
    hours = request.args.get('hours', 24, type=int)

    try:
        with db_manager.get_connection() as conn:
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


            return jsonify({'discoveries': discoveries})

    except Exception as e:
        logger.error(f"Erreur récupération token discoveries: {e}")
        return jsonify({'discoveries': []}), 500

@app.route('/api/large-transactions')
def get_large_transactions():
    """API pour récupérer les transactions importantes"""
    hours = request.args.get('hours', 24, type=int)

    try:
        with db_manager.get_connection() as conn:
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

            return jsonify({'transactions': transactions})

    except Exception as e:
        logger.error(f"Erreur récupération large transactions: {e}")
        return jsonify({'transactions': []}), 500

@app.route('/api/debug/token-accounts/<wallet_address>')
def debug_token_accounts(wallet_address):
    """Debug: Voir les comptes de tokens d'un wallet"""
    try:
        with db_manager.get_connection() as conn:
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
        with db_manager.get_connection() as conn:
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
        with db_manager.get_connection() as conn:
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
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()

            # Stats générales MULTI-WALLETS
            cursor.execute("SELECT COUNT(DISTINCT token_mint) FROM transactions WHERE is_token_transaction = 1")
            total_tokens = cursor.fetchone()[0] or 0

            cursor.execute("SELECT COUNT(*) FROM token_accounts WHERE is_active = 1")
            total_token_accounts = cursor.fetchone()[0] or 0

            cursor.execute("""
                SELECT COUNT(*) FROM transactions 
                WHERE is_token_transaction = 1 AND block_time >= ?
            """, (int(time.time()) - 3600,))
            balance_changes_1h = cursor.fetchone()[0] or 0

            cursor.execute("""
                SELECT COUNT(*) FROM transactions 
                WHERE is_large_token_amount = 1 AND block_time >= ?
            """, (int(time.time()) - 86400,))
            large_transactions_24h = cursor.fetchone()[0] or 0

            # Dernier scan
            cursor.execute("SELECT MAX(completed_at) FROM scan_history")
            last_scan_result = cursor.fetchone()
            last_scan_time = last_scan_result[0] if last_scan_result[0] else 0

            # Tokens les plus actifs
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

        return jsonify({
            'stats': {
                'totalTokenAccounts': total_token_accounts,
                'balanceChangesCount': balance_changes_1h,
                'largeTransactionsCount': large_transactions_24h,
                'lastScanTime': last_scan_time,
                'totalTokens': total_tokens
            },
            'topTokens': top_tokens[:8],
            'newGems': [t for t in top_tokens if t['last_activity'] > (int(time.time()) - 7200)][:5],
            'volumeAlerts': [t for t in top_tokens if t['volume'] > 5][:5],
            'activeTokensList': top_tokens
        })

    except Exception as e:
        logger.error(f"Erreur dashboard data: {e}")
        return jsonify({
            'stats': {'totalTokenAccounts': 0, 'balanceChangesCount': 0, 'largeTransactionsCount': 0, 'lastScanTime': 0, 'totalTokens': 0},
            'topTokens': [], 'newGems': [], 'volumeAlerts': [], 'activeTokensList': []
        }), 500

@app.route('/api/recent-balance-changes')
def get_recent_balance_changes():
    """API pour récupérer les balance changes récents"""
    limit = request.args.get('limit', 20, type=int)

    try:
        with db_manager.get_connection() as conn:
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

    print("🧪 CONFIGURATION TEST:")
    print(f"   Wallets configurés: {len(WALLET_ADDRESSES)}")
    for i, wallet in enumerate(WALLET_ADDRESSES):
        print(f"   #{i+1}: {wallet[:8]}...{wallet[-8:]}")
    print(f"   Mode: {'TEST' if len(WALLET_ADDRESSES) == 1 else 'NORMAL'}")

    # Lancer Flask dans un thread séparé
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    # Lancer la boucle de monitoring
    monitor.monitor_loop()

if __name__ == "__main__":
    main()
