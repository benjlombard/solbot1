#!/usr/bin/env python3
"""
💰 Pump.fun Data Enricher - Version Continue
Enrichit les tokens avec les données pump.fun en continu
Basé sur pump_fun_checker.py mais avec enrichissement complet des données
"""

import sqlite3
import aiohttp
import json
import time
import logging
import asyncio
import argparse
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from aiohttp import ClientSession, TCPConnector
import random

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class RateLimiter:
    """Rate limiter pour Pump.fun API - IDENTIQUE AU SCRIPT ORIGINAL"""
    requests_per_minute: int = 120
    requests_made: int = 0
    window_start: float = 0
    consecutive_429s: int = 0
    backoff_multiplier: float = 1.0
    
    def __post_init__(self):
        self.window_start = time.time()
    
    async def acquire(self):
        """Acquérir le droit de faire une requête"""
        current_time = time.time()
        
        # Reset de la fenêtre si 60 secondes écoulées
        if current_time - self.window_start >= 60:
            self.requests_made = 0
            self.window_start = current_time
            if self.consecutive_429s == 0:
                self.backoff_multiplier = max(1.0, self.backoff_multiplier * 0.9)
        
        # Vérifier si on peut faire une requête
        if self.requests_made >= self.requests_per_minute:
            wait_time = 60 - (current_time - self.window_start)
            if wait_time > 0:
                logger.debug(f"⏳ Rate limit: waiting {wait_time:.1f}s")
                await asyncio.sleep(wait_time + 0.1)
                self.requests_made = 0
                self.window_start = time.time()
        
        # Délai adaptatif
        base_delay = 60 / self.requests_per_minute
        adaptive_delay = base_delay * self.backoff_multiplier
        
        await asyncio.sleep(adaptive_delay)
        self.requests_made += 1
    
    async def handle_429(self):
        """Gérer une erreur 429"""
        self.consecutive_429s += 1
        self.backoff_multiplier = min(5.0, self.backoff_multiplier * 1.5)
        
        wait_time = min(120, 10 * self.consecutive_429s + random.uniform(0, 5))
        logger.warning(f"🚨 Rate limit hit #{self.consecutive_429s}, waiting {wait_time:.1f}s")
        await asyncio.sleep(wait_time)
    
    def reset_429(self):
        """Réinitialiser après succès"""
        if self.consecutive_429s > 0:
            logger.info("✅ Rate limit recovered")
            self.consecutive_429s = 0

class ContinuousPumpFunEnricher:
    """Version continue de l'enrichisseur Pump.fun - LOGIQUE IDENTIQUE AU SCRIPT DEXSCREENER"""
    
    def __init__(self, database_path: str = "tokens.db", check_interval_minutes: int = 15, 
                 batch_size: int = 30, min_hours_since_update: int = 1, 
                 strategy: str = "never_updated", verbose: bool = True):
        self.database_path = database_path
        self.check_interval_minutes = check_interval_minutes
        self.batch_size = batch_size
        self.min_hours_since_update = min_hours_since_update
        self.strategy = strategy
        self.verbose = verbose
        self.rate_limiter = RateLimiter(requests_per_minute=100)  # Conservative
        self.is_running = False
        
        # URLs Pump.fun (mises à jour 2025)
        self.pump_fun_urls = [
            "https://frontend-api.pump.fun/coins/{}",      # URL principale
            "https://frontend-api-v2.pump.fun/coins/{}",   # Version 2
            "https://frontend-api-v3.pump.fun/coins/{}",   # Version 3
        ]
        
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
    
    def migrate_database_pump_fun(self):
        """Migrer la base pour ajouter les colonnes Pump.fun"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("PRAGMA table_info(tokens)")
            cols = {col[1] for col in cursor.fetchall()}
            
            # Colonnes Pump.fun à ajouter
            pump_fun_columns = [
                ("exists_on_pump", "BOOLEAN DEFAULT NULL"),
                ("pump_fun_name", "TEXT"),
                ("pump_fun_symbol", "TEXT"),
                ("pump_fun_description", "TEXT"),
                ("pump_fun_image_uri", "TEXT"),
                ("pump_fun_metadata_uri", "TEXT"),
                ("pump_fun_twitter", "TEXT"),
                ("pump_fun_telegram", "TEXT"),
                ("pump_fun_website", "TEXT"),
                ("pump_fun_show_name", "BOOLEAN DEFAULT 0"),
                ("pump_fun_created_timestamp", "INTEGER"),
                ("pump_fun_usd_market_cap", "REAL"),
                ("pump_fun_reply_count", "INTEGER"),
                ("pump_fun_raydium_pool", "TEXT"),
                ("pump_fun_complete", "BOOLEAN DEFAULT 0"),
                ("pump_fun_total_supply", "REAL"),
                ("pump_fun_creator", "TEXT"),
                ("pump_fun_nsfw", "BOOLEAN DEFAULT 0"),
                ("pump_fun_market_cap", "REAL"),  # Market cap en SOL
                ("pump_fun_virtual_sol_reserves", "REAL"),
                ("pump_fun_virtual_token_reserves", "REAL"),
                ("pump_fun_bonding_curve", "TEXT"),
                ("pump_fun_associated_bonding_curve", "TEXT"),
                ("pump_fun_king_of_hill_timestamp", "INTEGER"),
                ("pump_fun_market_id", "TEXT"),
                ("pump_fun_inverted", "BOOLEAN DEFAULT 0"),
                ("pump_fun_is_currently_live", "BOOLEAN DEFAULT 0"),
                ("pump_fun_username", "TEXT"),  # Nom du créateur
                ("pump_fun_profile_image", "TEXT"),  # Image de profil du créateur
                ("pump_fun_last_pump_update", "TIMESTAMP"),
            ]
            
            for col_name, col_type in pump_fun_columns:
                if col_name not in cols:
                    cursor.execute(f"ALTER TABLE tokens ADD COLUMN {col_name} {col_type}")
                    logger.info(f"✅ Added column: {col_name}")
            
            conn.commit()
            
        except sqlite3.Error as e:
            logger.error(f"Error migrating database: {e}")
        finally:
            conn.close()
    
    def get_tokens_to_enrich(self, limit: int, strategy: str = "never_updated", min_hours_since_update: int = 1) -> List[Dict]:
        """
        COPIE EXACTE de la méthode du script DexScreener qui fonctionne mais adaptée pour Pump.fun
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
                    AND (pump_fun_last_pump_update IS NULL 
                         OR pump_fun_last_pump_update = ''
                         OR pump_fun_last_pump_update < datetime('now', '-{} hours', 'localtime'))
                '''.format(min_hours_since_update)
                exclude_recent_params = ()
            
            if strategy == "never_updated":
                query = f'''
                    SELECT address, symbol, updated_at, pump_fun_last_pump_update, exists_on_pump
                    FROM tokens 
                    WHERE (pump_fun_last_pump_update IS NULL 
                           OR pump_fun_last_pump_update = '')
                    AND symbol IS NOT NULL 
                    AND symbol != 'UNKNOWN' 
                    AND symbol != ''
                    AND (status IS NULL OR status IN ('active', 'new', 'no_dex_data'))
                    AND (exists_on_pump = 1 OR exists_on_pump IS NULL)
                    ORDER BY first_discovered_at DESC
                    LIMIT ?
                '''
                params = (limit,)
                
            elif strategy == "existing_pump_tokens":
                query = f'''
                    SELECT address, symbol, updated_at, pump_fun_last_pump_update, exists_on_pump
                    FROM tokens 
                    WHERE exists_on_pump = 1
                    AND symbol IS NOT NULL 
                    AND symbol != 'UNKNOWN' 
                    AND symbol != ''
                    {exclude_recent_condition}
                    ORDER BY COALESCE(pump_fun_last_pump_update, '1970-01-01') ASC
                    LIMIT ?
                '''
                params = (limit,)
                
            elif strategy == "oldest":
                query = f'''
                    SELECT address, symbol, updated_at, pump_fun_last_pump_update, exists_on_pump
                    FROM tokens 
                    WHERE symbol IS NOT NULL 
                    AND symbol != 'UNKNOWN' 
                    AND symbol != ''
                    AND (status IS NULL OR status IN ('active', 'new', 'no_dex_data'))
                    AND (exists_on_pump = 1 OR exists_on_pump IS NULL)
                    {exclude_recent_condition}
                    ORDER BY COALESCE(pump_fun_last_pump_update, '1970-01-01') ASC
                    LIMIT ?
                '''
                params = (limit,)
                
            elif strategy == "recent":
                query = f'''
                    SELECT address, symbol, updated_at, pump_fun_last_pump_update, exists_on_pump
                    FROM tokens 
                    WHERE first_discovered_at > datetime('now', '-24 hours', 'localtime')
                    AND symbol IS NOT NULL 
                    AND symbol != 'UNKNOWN' 
                    AND symbol != ''
                    AND (status IS NULL OR status IN ('active', 'new', 'no_dex_data'))
                    AND (exists_on_pump = 1 OR exists_on_pump IS NULL)
                    {exclude_recent_condition}
                    ORDER BY first_discovered_at DESC
                    LIMIT ?
                '''
                params = (limit,)
                
            elif strategy == "random":
                query = f'''
                    SELECT address, symbol, updated_at, pump_fun_last_pump_update, exists_on_pump
                    FROM tokens 
                    WHERE symbol IS NOT NULL 
                    AND symbol != 'UNKNOWN' 
                    AND symbol != ''
                    AND (status IS NULL OR status IN ('active', 'new', 'no_dex_data'))
                    AND (exists_on_pump = 1 OR exists_on_pump IS NULL)
                    {exclude_recent_condition}
                    ORDER BY RANDOM()
                    LIMIT ?
                '''
                params = (limit,)
                
            elif strategy == "force_all":
                query = '''
                    SELECT address, symbol, updated_at, pump_fun_last_pump_update, exists_on_pump
                    FROM tokens 
                    WHERE symbol IS NOT NULL 
                    AND symbol != 'UNKNOWN' 
                    AND symbol != ''
                    AND (status IS NULL OR status NOT IN ('archived', 'blacklisted'))
                    AND (exists_on_pump = 1 OR exists_on_pump IS NULL)
                    ORDER BY COALESCE(pump_fun_last_pump_update, '1970-01-01') ASC
                    LIMIT ?
                '''
                params = (limit,)
                
            else:
                raise ValueError(f"Stratégie inconnue: {strategy}")
            
            cursor.execute(query, params)
            tokens = [dict(row) for row in cursor.fetchall()]
            
            if self.verbose and tokens:
                logger.info(f"📋 {len(tokens)} tokens sélectionnés avec stratégie '{strategy}'")
                
                # Log de debug pour les tokens exists_on_pump = 1
                pump_tokens = [t for t in tokens if t.get('exists_on_pump') == 1]
                if pump_tokens:
                    logger.info(f"🎯 {len(pump_tokens)} tokens confirmés sur Pump.fun")
            
            return tokens
            
        except sqlite3.Error as e:
            logger.error(f"Erreur base de données: {e}")
            return []
        finally:
            conn.close()
    
    async def fetch_pump_fun_data(self, address: str) -> Optional[Dict]:
        """
        Récupérer les données Pump.fun - VERSION COMPLÈTE
        """
        await self.rate_limiter.acquire()
        
        # Essayer différentes URLs dans l'ordre
        for i, url_template in enumerate(self.pump_fun_urls):
            try:
                url = url_template.format(address)
                logger.debug(f"🔍 Checking URL {i+1}: {url}")
                
                connector = TCPConnector(
                    limit=30,
                    limit_per_host=15,
                    ttl_dns_cache=300,
                    use_dns_cache=True
                )
                
                timeout = aiohttp.ClientTimeout(total=10)
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Accept': 'application/json, text/plain, */*',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Referer': 'https://pump.fun/'
                }
                
                async with ClientSession(connector=connector, timeout=timeout, headers=headers) as session:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            try:
                                data = await resp.json()
                                
                                # Vérifier si on a des données valides
                                if data and isinstance(data, dict):
                                    mint = data.get('mint') or data.get('address') or data.get('tokenAddress')
                                    
                                    if mint and mint.lower() == address.lower():
                                        self.rate_limiter.reset_429()
                                        logger.debug(f"✅ Found pump.fun data: {data.get('symbol')} ({url})")
                                        return data
                                    elif mint:
                                        logger.debug(f"❓ Different mint in response: {mint} != {address}")
                                    else:
                                        # Parfois le token existe mais les champs sont différents
                                        symbol = data.get('symbol') or data.get('name')
                                        name = data.get('name') or data.get('description')
                                        creator = data.get('creator')
                                        
                                        if symbol or name or creator:
                                            logger.debug(f"✅ Token exists with alternate format: {symbol}")
                                            # Ajouter l'adresse manquante
                                            data['mint'] = address
                                            return data
                            
                            except Exception as json_error:
                                logger.debug(f"❌ JSON parse error from {url}: {json_error}")
                                continue
                        
                        elif resp.status == 404:
                            logger.debug(f"❌ 404 from {url}")
                            continue  # Essayer l'URL suivante
                        
                        elif resp.status == 429:
                            await self.rate_limiter.handle_429()
                            return None
                        
                        else:
                            logger.debug(f"❌ HTTP {resp.status} from {url}")
                            continue
                            
            except asyncio.TimeoutError:
                logger.debug(f"⏱️ Timeout for {url}")
                continue
            except Exception as e:
                logger.debug(f"❌ Error with {url}: {e}")
                continue
        
        # Aucune URL n'a fonctionné
        logger.debug(f"❌ No data found on pump.fun for {address}")
        self.stats['no_data_found'] += 1
        return None
    
    def extract_pump_fun_fields(self, pump_data: Dict, address: str) -> Dict:
        """
        Extraire tous les champs Pump.fun selon la structure de données
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
        
        def safe_bool(value, default=False):
            if isinstance(value, bool):
                return value
            elif isinstance(value, str):
                return value.lower() in ('true', '1', 'yes')
            elif isinstance(value, (int, float)):
                return bool(value)
            return default
        
        # Extraire toutes les données selon la structure Pump.fun
        extracted = {
            'exists_on_pump': True,  # Si on a des données, le token existe
            'pump_fun_name': pump_data.get('name'),
            'pump_fun_symbol': pump_data.get('symbol'),
            'pump_fun_description': pump_data.get('description'),
            'pump_fun_image_uri': pump_data.get('image_uri'),
            'pump_fun_metadata_uri': pump_data.get('metadata_uri'),
            'pump_fun_twitter': pump_data.get('twitter'),
            'pump_fun_telegram': pump_data.get('telegram'),
            'pump_fun_website': pump_data.get('website'),
            'pump_fun_show_name': safe_bool(pump_data.get('show_name')),
            'pump_fun_created_timestamp': safe_int(pump_data.get('created_timestamp')),
            'pump_fun_usd_market_cap': safe_float(pump_data.get('usd_market_cap')),
            'pump_fun_reply_count': safe_int(pump_data.get('reply_count')),
            'pump_fun_raydium_pool': pump_data.get('raydium_pool'),
            'pump_fun_complete': safe_bool(pump_data.get('complete')),
            'pump_fun_total_supply': safe_float(pump_data.get('total_supply')),
            'pump_fun_creator': pump_data.get('creator'),
            'pump_fun_nsfw': safe_bool(pump_data.get('nsfw')),
            'pump_fun_market_cap': safe_float(pump_data.get('market_cap')),
            'pump_fun_virtual_sol_reserves': safe_float(pump_data.get('virtual_sol_reserves')),
            'pump_fun_virtual_token_reserves': safe_float(pump_data.get('virtual_token_reserves')),
            'pump_fun_bonding_curve': pump_data.get('bonding_curve'),
            'pump_fun_associated_bonding_curve': pump_data.get('associated_bonding_curve'),
            'pump_fun_king_of_hill_timestamp': safe_int(pump_data.get('king_of_hill_timestamp')),
            'pump_fun_market_id': pump_data.get('market_id'),
            'pump_fun_inverted': safe_bool(pump_data.get('inverted')),
            'pump_fun_is_currently_live': safe_bool(pump_data.get('is_currently_live')),
            'pump_fun_username': pump_data.get('username'),
            'pump_fun_profile_image': pump_data.get('profile_image'),
            'pump_fun_last_pump_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        return extracted
    
    def create_token_snapshot(self, address: str, snapshot_reason: str = 'before_pump_fun_update') -> bool:
        """
        Créer un snapshot du token dans tokens_hist AVANT l'enrichissement Pump.fun
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
                    
                    -- Colonnes DexScreener (si elles existent)
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
                    
                    -- Colonnes DexScreener
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
    
    def update_token_in_database(self, address: str, pump_fun_data: Dict) -> bool:
        """
        Mettre à jour le token avec les données Pump.fun dans la base de données
        """
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            update_query = '''
                UPDATE tokens SET 
                    exists_on_pump = ?,
                    pump_fun_name = ?,
                    pump_fun_symbol = ?,
                    pump_fun_description = ?,
                    pump_fun_image_uri = ?,
                    pump_fun_metadata_uri = ?,
                    pump_fun_twitter = ?,
                    pump_fun_telegram = ?,
                    pump_fun_website = ?,
                    pump_fun_show_name = ?,
                    pump_fun_created_timestamp = ?,
                    pump_fun_usd_market_cap = ?,
                    pump_fun_reply_count = ?,
                    pump_fun_raydium_pool = ?,
                    pump_fun_complete = ?,
                    pump_fun_total_supply = ?,
                    pump_fun_creator = ?,
                    pump_fun_nsfw = ?,
                    pump_fun_market_cap = ?,
                    pump_fun_virtual_sol_reserves = ?,
                    pump_fun_virtual_token_reserves = ?,
                    pump_fun_bonding_curve = ?,
                    pump_fun_associated_bonding_curve = ?,
                    pump_fun_king_of_hill_timestamp = ?,
                    pump_fun_market_id = ?,
                    pump_fun_inverted = ?,
                    pump_fun_is_currently_live = ?,
                    pump_fun_username = ?,
                    pump_fun_profile_image = ?,
                    pump_fun_last_pump_update = ?,
                    updated_at = ?
                WHERE address = ?
            '''
            
            values = (
                pump_fun_data.get('exists_on_pump'),
                pump_fun_data.get('pump_fun_name'),
                pump_fun_data.get('pump_fun_symbol'),
                pump_fun_data.get('pump_fun_description'),
                pump_fun_data.get('pump_fun_image_uri'),
                pump_fun_data.get('pump_fun_metadata_uri'),
                pump_fun_data.get('pump_fun_twitter'),
                pump_fun_data.get('pump_fun_telegram'),
                pump_fun_data.get('pump_fun_website'),
                pump_fun_data.get('pump_fun_show_name'),
                pump_fun_data.get('pump_fun_created_timestamp'),
                pump_fun_data.get('pump_fun_usd_market_cap'),
                pump_fun_data.get('pump_fun_reply_count'),
                pump_fun_data.get('pump_fun_raydium_pool'),
                pump_fun_data.get('pump_fun_complete'),
                pump_fun_data.get('pump_fun_total_supply'),
                pump_fun_data.get('pump_fun_creator'),
                pump_fun_data.get('pump_fun_nsfw'),
                pump_fun_data.get('pump_fun_market_cap'),
                pump_fun_data.get('pump_fun_virtual_sol_reserves'),
                pump_fun_data.get('pump_fun_virtual_token_reserves'),
                pump_fun_data.get('pump_fun_bonding_curve'),
                pump_fun_data.get('pump_fun_associated_bonding_curve'),
                pump_fun_data.get('pump_fun_king_of_hill_timestamp'),
                pump_fun_data.get('pump_fun_market_id'),
                pump_fun_data.get('pump_fun_inverted'),
                pump_fun_data.get('pump_fun_is_currently_live'),
                pump_fun_data.get('pump_fun_username'),
                pump_fun_data.get('pump_fun_profile_image'),
                pump_fun_data.get('pump_fun_last_pump_update'),
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
    
    def enrich_token(self, token: Dict) -> bool:
        """
        ENRICHIR UN TOKEN AVEC LES DONNÉES PUMP.FUN + SNAPSHOT
        """
        address = token['address']
        symbol = token.get('symbol', 'UNKNOWN')
        
        if self.verbose:
            logger.info(f"🔍 Enrichissement Pump.fun: {symbol} ({address[:8]}...)")
        
        # 1. CRÉER UN SNAPSHOT AVANT L'ENRICHISSEMENT
        snapshot_created = self.create_token_snapshot(address, 'before_pump_fun_update')
        if snapshot_created:
            self.stats['snapshots_created'] += 1
        else:
            self.stats['snapshot_errors'] += 1
            logger.debug(f"⚠️ Impossible de créer le snapshot pour {symbol}, on continue quand même")
        
        # 2. ENRICHISSEMENT NORMAL (logique originale inchangée)
        # Récupérer les données Pump.fun
        try:
            pump_data = asyncio.run(self.fetch_pump_fun_data(address))
            
            if not pump_data:  # Aucune donnée Pump.fun
                # Le token n'existe pas ou plus sur Pump.fun
                logger.debug(f"❌ Pas de données Pump.fun pour {symbol}")
                
                # Mettre à jour exists_on_pump = False
                conn = sqlite3.connect(self.database_path)
                cursor = conn.cursor()
                try:
                    cursor.execute('''
                        UPDATE tokens SET 
                            exists_on_pump = 0,
                            pump_fun_last_pump_update = ?,
                            updated_at = ?
                        WHERE address = ?
                    ''', (
                        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        address
                    ))
                    conn.commit()
                    logger.debug(f"💾 Marqué {symbol} comme absent de Pump.fun")
                except sqlite3.Error as e:
                    logger.error(f"Erreur DB pour {address}: {e}")
                finally:
                    conn.close()
                
                return False

            # Extraire les champs selon la structure Pump.fun
            pump_fun_fields = self.extract_pump_fun_fields(pump_data, address)
            
            # Mettre à jour en base
            success = self.update_token_in_database(address, pump_fun_fields)
            
            if success:
                self.stats['successful_updates'] += 1
                
                # Log des informations clés
                name = pump_fun_fields.get('pump_fun_name', 'N/A')
                market_cap = pump_fun_fields.get('pump_fun_usd_market_cap', 0)
                complete = pump_fun_fields.get('pump_fun_complete', False)
                creator = pump_fun_fields.get('pump_fun_creator', 'N/A')
                
                # Sauvegarder pour le rapport final
                self.stats['last_successful_tokens'].append({
                    'symbol': symbol,
                    'address': address,
                    'name': name,
                    'market_cap': market_cap,
                    'complete': complete,
                    'creator': creator[:8] + '...' if creator != 'N/A' else 'N/A'
                })
                
                # Garder seulement les 20 derniers
                self.stats['last_successful_tokens'] = self.stats['last_successful_tokens'][-20:]
                
                if self.verbose:
                    status = "✅ COMPLETE" if complete else "🔄 ACTIVE"
                    logger.info(f"{status} {symbol}: MC=${market_cap:,.0f}, Creator={creator[:8] if creator != 'N/A' else 'N/A'}...")
            
            return success
            
        except Exception as e:
            logger.error(f"Erreur enrichissement {address}: {e}")
            self.stats['api_errors'] += 1
            return False
    
    def run_enrichment_cycle(self) -> Dict:
        """
        Version adaptée de run_enrichment pour un seul cycle
        """
        start_time = time.time()
        
        if self.verbose:
            logger.info(f"🔄 Démarrage cycle d'enrichissement Pump.fun")
            logger.info(f"🎯 Stratégie: {self.strategy}")
            logger.info(f"📊 Tokens à traiter: {self.batch_size}")
        
        # Récupérer les tokens à enrichir
        tokens = self.get_tokens_to_enrich(self.batch_size, self.strategy, self.min_hours_since_update)
        
        if not tokens:
            logger.info("😴 Aucun token à enrichir trouvé avec ces critères")
            return {'success': True, 'tokens_processed': 0, 'message': 'Aucun token trouvé'}
        
        if self.verbose:
            logger.info(f"📋 {len(tokens)} tokens sélectionnés pour enrichissement")
            
            # Statistiques sur les tokens
            pump_confirmed = len([t for t in tokens if t.get('exists_on_pump') == 1])
            never_checked = len([t for t in tokens if t.get('exists_on_pump') is None])
            
            if pump_confirmed > 0:
                logger.info(f"✅ {pump_confirmed} tokens confirmés sur Pump.fun")
            if never_checked > 0:
                logger.info(f"❓ {never_checked} tokens jamais vérifiés")
        
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
                time.sleep(0.5)  # Délai plus important pour Pump.fun
        
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
        logger.info(f"🚀 Démarrage enrichissement Pump.fun continu")
        logger.info(f"📋 Configuration: batch={self.batch_size}, interval={self.check_interval_minutes}min, strategy={self.strategy}")
        
        # Migration de la base de données
        self.migrate_database_pump_fun()
        
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
        logger.info("📊 PUMP.FUN ENRICHER FINAL STATS")
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
                name = token['name']
                market_cap = token['market_cap']
                complete = "✅" if token['complete'] else "🔄"
                creator = token['creator']
                
                logger.info(f"   {i:2}. {symbol:<12} | {name:<20} | MC: ${market_cap:<12,.0f} | "
                           f"{complete} | Creator: {creator}")
        
        logger.info("=" * 60)

def main():
    """Fonction principale"""
    parser = argparse.ArgumentParser(description="Continuous Pump.fun Data Enricher")
    
    parser.add_argument("--database", default="tokens.db", help="Chemin vers la base de données")
    parser.add_argument("--batch-size", type=int, default=30, help="Nombre de tokens par cycle")
    parser.add_argument("--interval", type=int, default=15, help="Intervalle entre cycles (minutes)")
    parser.add_argument("--strategy", choices=['never_updated', 'existing_pump_tokens', 'oldest', 'recent', 'random', 'force_all'], 
                       default='never_updated', help="Stratégie de sélection des tokens")
    parser.add_argument("--min-hours", type=int, default=1, 
                       help="Heures minimum depuis dernière MAJ Pump.fun")
    parser.add_argument("--verbose", action="store_true", help="Mode verbose")
    parser.add_argument("--single-cycle", action="store_true", help="Exécuter un seul cycle et s'arrêter")
    parser.add_argument("--test-token", type=str, help="Tester avec un token spécifique")
    parser.add_argument("--migrate-only", action="store_true", help="Seulement migrer la base de données")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Créer l'enrichisseur
    enricher = ContinuousPumpFunEnricher(
        database_path=args.database,
        check_interval_minutes=args.interval,
        batch_size=args.batch_size,
        min_hours_since_update=args.min_hours,
        strategy=args.strategy,
        verbose=args.verbose
    )
    
    try:
        if args.migrate_only:
            # Mode migration uniquement
            logger.info("🔧 Migration de la base de données...")
            enricher.migrate_database_pump_fun()
            logger.info("✅ Migration terminée")
            
        elif args.test_token:
            # Mode test avec un token spécifique
            test_token = {'address': args.test_token, 'symbol': 'TEST'}
            logger.info(f"🧪 Test avec token: {args.test_token}")
            success = enricher.enrich_token(test_token)
            logger.info(f"🧪 Résultat: {'✅ Succès' if success else '❌ Échec'}")
            
        elif args.single_cycle:
            # Mode single cycle
            enricher.migrate_database_pump_fun()
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