#!/usr/bin/env python3
"""
📈 DexScreener Data Enricher - Version Continue
Basé exactement sur le script original qui fonctionne, mais tourne en continu
"""

import sqlite3
import requests
import json
import time
import logging
import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
import argparse
from dataclasses import dataclass

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class RateLimiter:
    """Rate limiter pour DexScreener API - IDENTIQUE AU SCRIPT ORIGINAL"""
    requests_per_minute: int = 300  # Limite DexScreener
    requests_made: int = 0
    window_start: float = 0
    
    def __post_init__(self):
        self.window_start = time.time()
    
    def can_make_request(self) -> bool:
        """Vérifier si on peut faire une requête"""
        current_time = time.time()
        
        # Reset window si 60 secondes écoulées
        if current_time - self.window_start >= 60:
            self.requests_made = 0
            self.window_start = current_time
        
        return self.requests_made < self.requests_per_minute
    
    def wait_if_needed(self):
        """Attendre si nécessaire pour respecter le rate limit"""
        if not self.can_make_request():
            wait_time = 60 - (time.time() - self.window_start)
            if wait_time > 0:
                logger.info(f"⏳ Rate limit atteint, attente de {wait_time:.1f}s...")
                time.sleep(wait_time + 0.1)  # Petit buffer
                self.requests_made = 0
                self.window_start = time.time()
    
    def record_request(self):
        """Enregistrer qu'une requête a été faite"""
        self.requests_made += 1

class ContinuousDexScreenerEnricher:
    """Version continue de l'enrichisseur DexScreener - LOGIQUE IDENTIQUE AU SCRIPT ORIGINAL"""
    
    def __init__(self, database_path: str = "tokens.db", check_interval_minutes: int = 15, 
                 batch_size: int = 50, min_hours_since_update: int = 1, 
                 strategy: str = "oldest", verbose: bool = True):
        self.database_path = database_path
        self.check_interval_minutes = check_interval_minutes
        self.batch_size = batch_size
        self.min_hours_since_update = min_hours_since_update
        self.strategy = strategy
        self.verbose = verbose
        self.rate_limiter = RateLimiter()
        self.base_url = "https://api.dexscreener.com/latest/dex/tokens"
        self.is_running = False
        
        # Statistiques avec historique
        self.stats = {
            'total_processed': 0,
            'successful_updates': 0,
            'api_errors': 0,
            'no_data_found': 0,
            'database_errors': 0,
            'cycles_completed': 0,
            'last_successful_tokens': [],
            'snapshots_created': 0,
            'snapshot_errors': 0
        }
    
    def get_tokens_to_enrich(self, limit: int, strategy: str = "oldest", min_hours_since_update: int = 1) -> List[Dict]:
        """
        COPIE EXACTE de la méthode du script original qui fonctionne
        """
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            # Condition commune pour exclure les tokens récemment mis à jour
            if strategy == "force_all":
                exclude_recent_condition = ""
                exclude_recent_params = ()
            else:
                exclude_recent_condition = '''
                    AND (dexscreener_last_dexscreener_update IS NULL 
                         OR dexscreener_last_dexscreener_update = ''
                         OR dexscreener_last_dexscreener_update < datetime('now', '-{} hours', 'localtime'))
                '''.format(min_hours_since_update)
                exclude_recent_params = ()
            
            if strategy == "never_updated":
                query = f'''
                    SELECT address, symbol, updated_at, dexscreener_last_dexscreener_update
                    FROM tokens 
                    WHERE (dexscreener_last_dexscreener_update IS NULL 
                           OR dexscreener_last_dexscreener_update = '')
                    AND symbol IS NOT NULL 
                    AND symbol != 'UNKNOWN' 
                    AND symbol != ''
                    AND (status IS NULL OR status IN ('active', 'new'))
                    ORDER BY first_discovered_at DESC
                    LIMIT ?
                '''
                params = (limit,)
                
            elif strategy == "oldest":
                query = f'''
                    SELECT address, symbol, updated_at, dexscreener_last_dexscreener_update
                    FROM tokens 
                    WHERE symbol IS NOT NULL 
                    AND symbol != 'UNKNOWN' 
                    AND symbol != ''
                    AND (status IS NULL OR status IN ('active', 'new'))
                    {exclude_recent_condition}
                    ORDER BY COALESCE(dexscreener_last_dexscreener_update, '1970-01-01') ASC
                    LIMIT ?
                '''
                params = (limit,)
                
            elif strategy == "recent":
                query = f'''
                    SELECT address, symbol, updated_at, dexscreener_last_dexscreener_update
                    FROM tokens 
                    WHERE first_discovered_at > datetime('now', '-24 hours', 'localtime')
                    AND symbol IS NOT NULL 
                    AND symbol != 'UNKNOWN' 
                    AND symbol != ''
                    AND (status IS NULL OR status IN ('active', 'new'))
                    {exclude_recent_condition}
                    ORDER BY first_discovered_at DESC
                    LIMIT ?
                '''
                params = (limit,)
                
            elif strategy == "random":
                query = f'''
                    SELECT address, symbol, updated_at, dexscreener_last_dexscreener_update
                    FROM tokens 
                    WHERE symbol IS NOT NULL 
                    AND symbol != 'UNKNOWN' 
                    AND symbol != ''
                    AND (status IS NULL OR status IN ('active', 'new'))
                    {exclude_recent_condition}
                    ORDER BY RANDOM()
                    LIMIT ?
                '''
                params = (limit,)
                
            elif strategy == "force_all":
                query = '''
                    SELECT address, symbol, updated_at, dexscreener_last_dexscreener_update
                    FROM tokens 
                    WHERE symbol IS NOT NULL 
                    AND symbol != 'UNKNOWN' 
                    AND symbol != ''
                    AND (status IS NULL OR status NOT IN ('archived', 'blacklisted'))
                    ORDER BY COALESCE(dexscreener_last_dexscreener_update, '1970-01-01') ASC
                    LIMIT ?
                '''
                params = (limit,)
                
            else:
                raise ValueError(f"Stratégie inconnue: {strategy}")
            
            cursor.execute(query, params)
            tokens = [dict(row) for row in cursor.fetchall()]
            
            if self.verbose and tokens:
                logger.info(f"📋 {len(tokens)} tokens sélectionnés avec stratégie '{strategy}'")
            
            return tokens
            
        except sqlite3.Error as e:
            logger.error(f"Erreur base de données: {e}")
            return []
        finally:
            conn.close()
    
    def fetch_dexscreener_data(self, address: str) -> Optional[Dict]:
        """
        COPIE EXACTE de la méthode du script original qui fonctionne
        """
        self.rate_limiter.wait_if_needed()
        
        url = f"{self.base_url}/{address}"
        
        try:
            response = requests.get(url, timeout=10)
            self.rate_limiter.record_request()
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('pairs') and len(data['pairs']) > 0:
                    # Prendre la paire avec le plus de liquidité
                    best_pair = max(
                        data['pairs'], 
                        key=lambda p: float(p.get('liquidity', {}).get('usd', 0) or 0)
                    )
                    return best_pair
                else:
                    logger.debug(f"Aucune paire trouvée pour {address}")
                    self.stats['no_data_found'] += 1
                    return None
                    
            elif response.status_code == 429:
                logger.warning(f"Rate limit hit pour {address}")
                time.sleep(2)
                return None
            else:
                logger.warning(f"API DexScreener error {response.status_code} pour {address}")
                self.stats['api_errors'] += 1
                return None
                
        except Exception as e:
            logger.error(f"Erreur récupération DexScreener pour {address}: {e}")
            self.stats['api_errors'] += 1
            return None
    
    def extract_dexscreener_fields(self, pair_data: Dict) -> Dict:
        """
        COPIE EXACTE de la méthode du script original qui fonctionne
        """
        def safe_float(value, default=0.0):
            try:
                return float(value) if value is not None else default
            except (ValueError, TypeError):
                return default
        
        def safe_int(value, default=0):
            try:
                return int(value) if value is not None else default
            except (ValueError, TypeError):
                return default
        
        # Extraire toutes les données selon votre structure
        extracted = {
            'dexscreener_pair_created_at': None,
            'dexscreener_price_usd': safe_float(pair_data.get('priceUsd')),
            'dexscreener_market_cap': safe_float(pair_data.get('marketCap')),
            'dexscreener_liquidity_base': safe_float(pair_data.get('liquidity', {}).get('base')),
            'dexscreener_liquidity_quote': safe_float(pair_data.get('liquidity', {}).get('usd')),
            'dexscreener_volume_1h': safe_float(pair_data.get('volume', {}).get('h1')),
            'dexscreener_volume_6h': safe_float(pair_data.get('volume', {}).get('h6')),
            'dexscreener_volume_24h': safe_float(pair_data.get('volume', {}).get('h24')),
            'dexscreener_price_change_1h': safe_float(pair_data.get('priceChange', {}).get('h1')),
            'dexscreener_price_change_6h': safe_float(pair_data.get('priceChange', {}).get('h6')),
            'dexscreener_price_change_h24': safe_float(pair_data.get('priceChange', {}).get('h24')),
            'dexscreener_txns_1h': 0,
            'dexscreener_txns_6h': 0,
            'dexscreener_txns_24h': 0,
            'dexscreener_buys_1h': 0,
            'dexscreener_sells_1h': 0,
            'dexscreener_buys_24h': 0,
            'dexscreener_sells_24h': 0,
            'dexscreener_dexscreener_url': pair_data.get('url', ''),
            'dexscreener_last_dexscreener_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Traitement spécial pour la date de création
        if 'pairCreatedAt' in pair_data and pair_data['pairCreatedAt']:
            try:
                timestamp_ms = pair_data['pairCreatedAt']
                created_datetime = datetime.fromtimestamp(timestamp_ms / 1000)
                extracted['dexscreener_pair_created_at'] = created_datetime.strftime('%Y-%m-%d %H:%M:%S')
            except (ValueError, TypeError) as e:
                logger.debug(f"Erreur conversion date: {e}")
        
        # Traitement des transactions
        txns = pair_data.get('txns', {})
        
        for period in ['h1', 'h6', 'h24']:
            period_data = txns.get(period, {})
            
            buys = safe_int(period_data.get('buys'))
            sells = safe_int(period_data.get('sells'))
            total = buys + sells
            
            if period == 'h1':
                extracted['dexscreener_txns_1h'] = total
                extracted['dexscreener_buys_1h'] = buys
                extracted['dexscreener_sells_1h'] = sells
            elif period == 'h6':
                extracted['dexscreener_txns_6h'] = total
            elif period == 'h24':
                extracted['dexscreener_txns_24h'] = total
                extracted['dexscreener_buys_24h'] = buys
                extracted['dexscreener_sells_24h'] = sells
        
        return extracted
    
    def create_token_snapshot(self, address: str, snapshot_reason: str = 'before_dexscreener_update') -> bool:
        """
        Créer un snapshot du token dans tokens_hist AVANT l'enrichissement
        """
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            # Créer le snapshot en copiant l'état actuel du token
            snapshot_query = '''
                INSERT INTO tokens_hist (
                    address, snapshot_timestamp, symbol, name, decimals, logo_uri,
                    price_usdc, market_cap, liquidity_usd, volume_24h, price_change_24h,
                    age_hours, quality_score, rug_score, holders, holder_distribution,
                    is_tradeable, invest_score, early_bonus, social_bonus, holders_bonus,
                    first_discovered_at, launch_timestamp, bonding_curve_status,
                    raydium_pool_address, updated_at, bonding_curve_progress,
                    dexscreener_pair_created_at, dexscreener_price_usd, dexscreener_market_cap,
                    dexscreener_liquidity_base, dexscreener_liquidity_quote,
                    dexscreener_volume_1h, dexscreener_volume_6h, dexscreener_volume_24h,
                    dexscreener_price_change_1h, dexscreener_price_change_6h, dexscreener_price_change_h24,
                    dexscreener_txns_1h, dexscreener_txns_6h, dexscreener_txns_24h,
                    dexscreener_buys_1h, dexscreener_sells_1h, dexscreener_buys_24h, dexscreener_sells_24h,
                    dexscreener_dexscreener_url, dexscreener_last_dexscreener_update,
                    status, snapshot_reason
                )
                SELECT 
                    address, datetime('now', 'localtime') as snapshot_timestamp,
                    symbol, name, decimals, logo_uri,
                    price_usdc, market_cap, liquidity_usd, volume_24h, price_change_24h,
                    age_hours, quality_score, rug_score, holders, holder_distribution,
                    is_tradeable, invest_score, early_bonus, social_bonus, holders_bonus,
                    first_discovered_at, launch_timestamp, bonding_curve_status,
                    raydium_pool_address, updated_at, bonding_curve_progress,
                    dexscreener_pair_created_at, dexscreener_price_usd, dexscreener_market_cap,
                    dexscreener_liquidity_base, dexscreener_liquidity_quote,
                    dexscreener_volume_1h, dexscreener_volume_6h, dexscreener_volume_24h,
                    dexscreener_price_change_1h, dexscreener_price_change_6h, dexscreener_price_change_h24,
                    dexscreener_txns_1h, dexscreener_txns_6h, dexscreener_txns_24h,
                    dexscreener_buys_1h, dexscreener_sells_1h, dexscreener_buys_24h, dexscreener_sells_24h,
                    dexscreener_dexscreener_url, dexscreener_last_dexscreener_update,
                    COALESCE(status, 'active') as status, ? as snapshot_reason
                FROM tokens 
                WHERE address = ?
            '''
            
            cursor.execute(snapshot_query, (snapshot_reason, address))
            
            if cursor.rowcount > 0:
                conn.commit()
                logger.debug(f"📸 Snapshot créé pour {address} (raison: {snapshot_reason})")
                return True
            else:
                logger.warning(f"⚠️ Token {address} non trouvé pour créer le snapshot")
                return False
                
        except sqlite3.Error as e:
            logger.error(f"Erreur création snapshot pour {address}: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    
    def update_token_in_database(self, address: str, dexscreener_data: Dict) -> bool:
        """
        COPIE EXACTE de la méthode du script original qui fonctionne
        """
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            update_query = '''
                UPDATE tokens SET 
                    dexscreener_pair_created_at = ?,
                    dexscreener_price_usd = ?,
                    dexscreener_market_cap = ?,
                    dexscreener_liquidity_base = ?,
                    dexscreener_liquidity_quote = ?,
                    dexscreener_volume_1h = ?,
                    dexscreener_volume_6h = ?,
                    dexscreener_volume_24h = ?,
                    dexscreener_price_change_1h = ?,
                    dexscreener_price_change_6h = ?,
                    dexscreener_price_change_h24 = ?,
                    dexscreener_txns_1h = ?,
                    dexscreener_txns_6h = ?,
                    dexscreener_txns_24h = ?,
                    dexscreener_buys_1h = ?,
                    dexscreener_sells_1h = ?,
                    dexscreener_buys_24h = ?,
                    dexscreener_sells_24h = ?,
                    dexscreener_dexscreener_url = ?,
                    dexscreener_last_dexscreener_update = ?,
                    updated_at = ?
                WHERE address = ?
            '''
            
            values = (
                dexscreener_data.get('dexscreener_pair_created_at'),
                dexscreener_data.get('dexscreener_price_usd'),
                dexscreener_data.get('dexscreener_market_cap'),
                dexscreener_data.get('dexscreener_liquidity_base'),
                dexscreener_data.get('dexscreener_liquidity_quote'),
                dexscreener_data.get('dexscreener_volume_1h'),
                dexscreener_data.get('dexscreener_volume_6h'),
                dexscreener_data.get('dexscreener_volume_24h'),
                dexscreener_data.get('dexscreener_price_change_1h'),
                dexscreener_data.get('dexscreener_price_change_6h'),
                dexscreener_data.get('dexscreener_price_change_h24'),
                dexscreener_data.get('dexscreener_txns_1h'),
                dexscreener_data.get('dexscreener_txns_6h'),
                dexscreener_data.get('dexscreener_txns_24h'),
                dexscreener_data.get('dexscreener_buys_1h'),
                dexscreener_data.get('dexscreener_sells_1h'),
                dexscreener_data.get('dexscreener_buys_24h'),
                dexscreener_data.get('dexscreener_sells_24h'),
                dexscreener_data.get('dexscreener_dexscreener_url'),
                dexscreener_data.get('dexscreener_last_dexscreener_update'),
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                address
            )
            
            cursor.execute(update_query, values)
            
            if cursor.rowcount > 0:
                conn.commit()
                logger.debug(f"✅ Token {address} mis à jour avec succès")
                return True
            else:
                logger.warning(f"⚠️ Token {address} non trouvé dans la base")
                return False
                
        except sqlite3.Error as e:
            logger.error(f"Erreur base de données pour {address}: {e}")
            self.stats['database_errors'] += 1
            conn.rollback()
            return False
        finally:
            conn.close()
        """
        COPIE EXACTE de la méthode du script original qui fonctionne
        """
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            update_query = '''
                UPDATE tokens SET 
                    dexscreener_pair_created_at = ?,
                    dexscreener_price_usd = ?,
                    dexscreener_market_cap = ?,
                    dexscreener_liquidity_base = ?,
                    dexscreener_liquidity_quote = ?,
                    dexscreener_volume_1h = ?,
                    dexscreener_volume_6h = ?,
                    dexscreener_volume_24h = ?,
                    dexscreener_price_change_1h = ?,
                    dexscreener_price_change_6h = ?,
                    dexscreener_price_change_h24 = ?,
                    dexscreener_txns_1h = ?,
                    dexscreener_txns_6h = ?,
                    dexscreener_txns_24h = ?,
                    dexscreener_buys_1h = ?,
                    dexscreener_sells_1h = ?,
                    dexscreener_buys_24h = ?,
                    dexscreener_sells_24h = ?,
                    dexscreener_dexscreener_url = ?,
                    dexscreener_last_dexscreener_update = ?,
                    updated_at = ?
                WHERE address = ?
            '''
            
            values = (
                dexscreener_data.get('dexscreener_pair_created_at'),
                dexscreener_data.get('dexscreener_price_usd'),
                dexscreener_data.get('dexscreener_market_cap'),
                dexscreener_data.get('dexscreener_liquidity_base'),
                dexscreener_data.get('dexscreener_liquidity_quote'),
                dexscreener_data.get('dexscreener_volume_1h'),
                dexscreener_data.get('dexscreener_volume_6h'),
                dexscreener_data.get('dexscreener_volume_24h'),
                dexscreener_data.get('dexscreener_price_change_1h'),
                dexscreener_data.get('dexscreener_price_change_6h'),
                dexscreener_data.get('dexscreener_price_change_h24'),
                dexscreener_data.get('dexscreener_txns_1h'),
                dexscreener_data.get('dexscreener_txns_6h'),
                dexscreener_data.get('dexscreener_txns_24h'),
                dexscreener_data.get('dexscreener_buys_1h'),
                dexscreener_data.get('dexscreener_sells_1h'),
                dexscreener_data.get('dexscreener_buys_24h'),
                dexscreener_data.get('dexscreener_sells_24h'),
                dexscreener_data.get('dexscreener_dexscreener_url'),
                dexscreener_data.get('dexscreener_last_dexscreener_update'),
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                address
            )
            
            cursor.execute(update_query, values)
            
            if cursor.rowcount > 0:
                conn.commit()
                logger.debug(f"✅ Token {address} mis à jour avec succès")
                return True
            else:
                logger.warning(f"⚠️ Token {address} non trouvé dans la base")
                return False
                
        except sqlite3.Error as e:
            logger.error(f"Erreur base de données pour {address}: {e}")
            self.stats['database_errors'] += 1
            conn.rollback()
            return False
        finally:
            conn.close()
    
    def count_consecutive_dexscreener_failures(self, address: str) -> int:
        """
        Compter les échecs consécutifs de récupération DexScreener dans l'historique
        """
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            # Compter les snapshots récents sans données DexScreener
            query = '''
                SELECT COUNT(*) as failures
                FROM tokens_hist 
                WHERE address = ? 
                AND snapshot_timestamp > datetime('now', '-7 days', 'localtime')
                AND (dexscreener_last_dexscreener_update IS NULL 
                     OR dexscreener_last_dexscreener_update = '')
                ORDER BY snapshot_timestamp DESC
            '''
            
            cursor.execute(query, (address,))
            result = cursor.fetchone()
            
            return result[0] if result else 0
            
        except sqlite3.Error as e:
            logger.error(f"Erreur comptage échecs pour {address}: {e}")
            return 0
        finally:
            conn.close()
    
    def get_token_age_days(self, address: str) -> int:
        """
        Obtenir l'âge du token en jours depuis sa première découverte
        """
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            query = '''
                SELECT 
                    CAST((julianday('now', 'localtime') - julianday(first_discovered_at)) AS INTEGER) as age_days
                FROM tokens 
                WHERE address = ?
            '''
            
            cursor.execute(query, (address,))
            result = cursor.fetchone()
            
            return result[0] if result else 0
            
        except sqlite3.Error as e:
            logger.error(f"Erreur calcul âge pour {address}: {e}")
            return 0
        finally:
            conn.close()

    def update_token_status(self, address: str, status: str) -> bool:
        """
        Mettre à jour le statut d'un token
        """
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            update_query = '''
                UPDATE tokens SET 
                    status = ?,
                    updated_at = datetime('now', 'localtime')
                WHERE address = ?
            '''
            
            cursor.execute(update_query, (status, address))
            
            if cursor.rowcount > 0:
                conn.commit()
                logger.debug(f"📝 Status du token {address} mis à jour: {status}")
                return True
            else:
                logger.warning(f"⚠️ Token {address} non trouvé pour mise à jour status")
                return False
                
        except sqlite3.Error as e:
            logger.error(f"Erreur mise à jour status pour {address}: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
             
    def enrich_token(self, token: Dict) -> bool:
        """
        COPIE EXACTE de la méthode du script original qui fonctionne + SNAPSHOT
        """
        address = token['address']
        symbol = token.get('symbol', 'UNKNOWN')
        
        if self.verbose:
            logger.info(f"🔍 Enrichissement DexScreener: {symbol} ({address[:8]}...)")
        
        # 1. CRÉER UN SNAPSHOT AVANT L'ENRICHISSEMENT
        snapshot_created = self.create_token_snapshot(address, 'before_dexscreener_update')
        if snapshot_created:
            self.stats['snapshots_created'] += 1
        else:
            self.stats['snapshot_errors'] += 1
            logger.debug(f"⚠️ Impossible de créer le snapshot pour {symbol}, on continue quand même")
        
        # 2. ENRICHISSEMENT NORMAL (logique originale inchangée)
        # Récupérer les données DexScreener
        pair_data = self.fetch_dexscreener_data(address)
        
        if not pair_data:  # Aucune donnée DexScreener
            # Compter les échecs précédents dans l'historique
            consecutive_failures = self.count_consecutive_dexscreener_failures(address)
            token_age_days = self.get_token_age_days(address)
            
            if consecutive_failures >= 3:
                self.update_token_status(address, 'inactive')
                logger.debug(f"🔴 Token {symbol} marqué comme inactif ({consecutive_failures} échecs)")
            elif token_age_days > 7 and consecutive_failures >= 1:
                self.update_token_status(address, 'archived')
                logger.debug(f"📦 Token {symbol} archivé (âge: {token_age_days}j, échecs: {consecutive_failures})")
            else:
                self.update_token_status(address, 'no_dex_data')
                logger.debug(f"⚪ Token {symbol} sans données DEX (âge: {token_age_days}j, échecs: {consecutive_failures})")
        
            return False

        # Extraire les champs selon votre structure
        dexscreener_fields = self.extract_dexscreener_fields(pair_data)
        
        # Mettre à jour en base
        success = self.update_token_in_database(address, dexscreener_fields)
        
        if success:
            self.stats['successful_updates'] += 1
            # Remettre le statut à 'active' si enrichissement réussi
            self.update_token_status(address, 'active')
            # Log des informations clés
            price = dexscreener_fields.get('dexscreener_price_usd', 0)
            volume_24h = dexscreener_fields.get('dexscreener_volume_24h', 0)
            liquidity = dexscreener_fields.get('dexscreener_liquidity_quote', 0)
            
            # Sauvegarder pour le rapport final
            self.stats['last_successful_tokens'].append({
                'symbol': symbol,
                'address': address,
                'price': price,
                'volume_24h': volume_24h,
                'liquidity': liquidity,
                'dex_id': pair_data.get('dexId', 'unknown')
            })
            
            # Garder seulement les 20 derniers
            self.stats['last_successful_tokens'] = self.stats['last_successful_tokens'][-20:]
            
            if self.verbose:
                logger.info(f"✅ {symbol}: Prix=${price:.8f}, Vol24h=${volume_24h:,.0f}, Liq=${liquidity:,.0f}")
        
        return success
    
    def run_enrichment_cycle(self) -> Dict:
        """
        Version adaptée de run_enrichment pour un seul cycle
        """
        start_time = time.time()
        
        if self.verbose:
            logger.info(f"🔄 Démarrage cycle d'enrichissement DexScreener")
            logger.info(f"🎯 Stratégie: {self.strategy}")
            logger.info(f"📊 Tokens à traiter: {self.batch_size}")
        
        # Récupérer les tokens à enrichir
        tokens = self.get_tokens_to_enrich(self.batch_size, self.strategy, self.min_hours_since_update)
        
        if not tokens:
            logger.info("😴 Aucun token à enrichir trouvé avec ces critères")
            return {'success': True, 'tokens_processed': 0, 'message': 'Aucun token trouvé'}
        
        if self.verbose:
            logger.info(f"📋 {len(tokens)} tokens sélectionnés pour enrichissement")
        
        # Enrichir chaque token
        cycle_successful = 0
        cycle_processed = 0
        
        for i, token in enumerate(tokens, 1):
            if self.verbose:
                logger.debug(f"[{i}/{len(tokens)}] Processing {token.get('symbol', 'UNKNOWN')}")
            
            success = self.enrich_token(token)
            cycle_processed += 1
            self.stats['total_processed'] += 1
            
            if success:
                cycle_successful += 1
            
            # Petit délai entre les requêtes (comme dans l'original)
            if i < len(tokens):
                time.sleep(0.2)
        
        # Rapport du cycle
        elapsed_time = time.time() - start_time
        self.stats['cycles_completed'] += 1
        
        if self.verbose:
            success_rate = (cycle_successful / cycle_processed * 100) if cycle_processed > 0 else 0
            logger.info(f"✅ Cycle terminé: {cycle_successful}/{cycle_processed} succès ({success_rate:.1f}%) en {elapsed_time:.1f}s")
        
        return {
            'success': True,
            'tokens_processed': cycle_processed,
            'tokens_updated': cycle_successful,
            'elapsed_time': elapsed_time
        }
    
    async def run_continuous(self):
        """Boucle principale continue"""
        self.is_running = True
        logger.info(f"🚀 Démarrage enrichissement DexScreener continu")
        logger.info(f"📋 Configuration: batch={self.batch_size}, interval={self.check_interval_minutes}min, strategy={self.strategy}")
        
        try:
            while self.is_running:
                # Exécuter un cycle d'enrichissement
                result = self.run_enrichment_cycle()
                
                if result['tokens_processed'] > 0:
                    logger.info(f"📊 Stats globales: Cycles={self.stats['cycles_completed']} | "
                               f"Total traités={self.stats['total_processed']} | "
                               f"Succès={self.stats['successful_updates']} | "
                               f"Snapshots={self.stats['snapshots_created']} | "
                               f"Erreurs API={self.stats['api_errors']} | "
                               f"Sans données={self.stats['no_data_found']}")
                
                # Attendre avant le prochain cycle
                if self.is_running:  # Vérifier qu'on n'a pas été arrêté
                    logger.info(f"⏰ Prochain cycle dans {self.check_interval_minutes} minutes")
                    
                    # Attente interruptible
                    for _ in range(self.check_interval_minutes * 60):
                        if not self.is_running:
                            break
                        await asyncio.sleep(1)
        
        except Exception as e:
            logger.error(f"Erreur dans la boucle continue: {e}")
        finally:
            self.log_final_stats()
    
    def stop(self):
        """Arrêter l'enrichissement"""
        self.is_running = False
    
    def log_final_stats(self):
        """Afficher les statistiques finales"""
        success_rate = (self.stats['successful_updates'] / max(1, self.stats['total_processed'])) * 100
        
        logger.info("=" * 60)
        logger.info("📊 DEXSCREENER ENRICHER FINAL STATS")
        logger.info("=" * 60)
        logger.info(f"✅ Total processed:     {self.stats['total_processed']}")
        logger.info(f"💾 Successful updates:  {self.stats['successful_updates']}")
        logger.info(f"📸 Snapshots created:   {self.stats['snapshots_created']}")
        logger.info(f"❌ API errors:          {self.stats['api_errors']}")
        logger.info(f"⚪ No data found:       {self.stats['no_data_found']}")
        logger.info(f"🔄 Cycles completed:    {self.stats['cycles_completed']}")
        logger.info(f"📈 Success rate:        {success_rate:.1f}%")
        
        # Stats sur l'historique
        if self.stats['snapshots_created'] > 0:
            snapshot_rate = (self.stats['snapshots_created'] / max(1, self.stats['total_processed'])) * 100
            logger.info(f"📸 Snapshot rate:       {snapshot_rate:.1f}%")
        
        if self.stats['snapshot_errors'] > 0:
            logger.info(f"⚠️ Snapshot errors:     {self.stats['snapshot_errors']}")
        
        # Afficher les derniers tokens mis à jour
        if self.stats['last_successful_tokens']:
            logger.info(f"\n🎯 DERNIERS TOKENS MIS À JOUR:")
            for i, token in enumerate(self.stats['last_successful_tokens'][-10:], 1):
                symbol = token['symbol']
                price = token['price']
                volume = token['volume_24h']
                liquidity = token['liquidity']
                dex_id = token['dex_id']
                
                logger.info(f"   {i:2}. {symbol:<12} | ${price:<12.8f} | Vol: ${volume:<12,.0f} | "
                           f"Liq: ${liquidity:<12,.0f} | DEX: {dex_id}")
        
        logger.info("=" * 60)

def main():
    """Fonction principale"""
    parser = argparse.ArgumentParser(description="Continuous DexScreener Data Enricher")
    
    parser.add_argument("--database", default="tokens.db", help="Chemin vers la base de données")
    parser.add_argument("--batch-size", type=int, default=50, help="Nombre de tokens par cycle")
    parser.add_argument("--interval", type=int, default=15, help="Intervalle entre cycles (minutes)")
    parser.add_argument("--strategy", choices=['oldest', 'never_updated', 'recent', 'random', 'force_all'], 
                       default='oldest', help="Stratégie de sélection des tokens")
    parser.add_argument("--min-hours", type=int, default=1, 
                       help="Heures minimum depuis dernière MAJ DexScreener")
    parser.add_argument("--verbose", action="store_true", help="Mode verbose")
    parser.add_argument("--single-cycle", action="store_true", help="Exécuter un seul cycle et s'arrêter")
    parser.add_argument("--test-token", type=str, help="Tester avec un token spécifique")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Créer l'enrichisseur
    enricher = ContinuousDexScreenerEnricher(
        database_path=args.database,
        check_interval_minutes=args.interval,
        batch_size=args.batch_size,
        min_hours_since_update=args.min_hours,
        strategy=args.strategy,
        verbose=args.verbose
    )
    
    try:
        if args.test_token:
            # Mode test avec un token spécifique
            test_token = {'address': args.test_token, 'symbol': 'TEST'}
            logger.info(f"🧪 Test avec token: {args.test_token}")
            success = enricher.enrich_token(test_token)
            logger.info(f"🧪 Résultat: {'✅ Succès' if success else '❌ Échec'}")
            
        elif args.single_cycle:
            # Mode single cycle
            result = enricher.run_enrichment_cycle()
            logger.info(f"🎯 Cycle terminé: {result}")
            
        else:
            # Mode continu
            asyncio.run(enricher.run_continuous())
            
    except KeyboardInterrupt:
        logger.info("\n🛑 Enrichissement interrompu par l'utilisateur")
        enricher.stop()
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'enrichissement: {e}")
        return 1

if __name__ == "__main__":
    exit(main())