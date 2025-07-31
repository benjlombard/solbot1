#!/usr/bin/env python3
"""
🔧 Symbol Fixer - Réparateur automatique de symboles
Corrige les tokens avec symbol = ERROR ou UNKNOWN en récupérant les vraies données
NOUVEAU: Système de tracking des tentatives pour éviter les re-tentatives inutiles
"""

import asyncio
import aiohttp
import sqlite3
import time
import logging
import argparse
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from aiohttp import ClientSession, TCPConnector
import random
import struct

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('symbol_fixer')

@dataclass
class FixedTokenData:
    """Données corrigées d'un token"""
    address: str
    old_symbol: str
    new_symbol: str
    name: str
    decimals: int
    logo_uri: Optional[str]
    source: str  # Source des données (helius, jupiter, dexscreener)
    confidence: str  # high, medium, low

class RateLimiter:
    """Rate limiter intelligent pour chaque API"""
    
    def __init__(self, api_name: str, requests_per_minute: int = 60):
        self.api_name = api_name
        self.requests_per_minute = requests_per_minute
        self.requests_made = 0
        self.window_start = time.time()
        self.consecutive_429s = 0
        self.backoff_multiplier = 1.0
        
    async def acquire(self):
        """Acquérir le droit de faire une requête"""
        current_time = time.time()
        
        # Reset de la fenêtre si 60 secondes écoulées
        if current_time - self.window_start >= 60:
            self.requests_made = 0
            self.window_start = current_time
            # Réduire le backoff si pas d'erreur récente
            if self.consecutive_429s == 0:
                self.backoff_multiplier = max(1.0, self.backoff_multiplier * 0.9)
        
        # Vérifier si on peut faire une requête
        if self.requests_made >= self.requests_per_minute:
            wait_time = 60 - (current_time - self.window_start)
            if wait_time > 0:
                logger.debug(f"⏳ {self.api_name} rate limit: waiting {wait_time:.1f}s")
                await asyncio.sleep(wait_time + 0.1)
                self.requests_made = 0
                self.window_start = time.time()
        
        # Délai adaptatif basé sur les erreurs précédentes
        if self.api_name == 'Helius':
            base_delay = max(1.0, 60 / self.requests_per_minute)  # Minimum 1 seconde
        else:
            base_delay = 60 / self.requests_per_minute
        adaptive_delay = base_delay * self.backoff_multiplier
        
        await asyncio.sleep(adaptive_delay)
        self.requests_made += 1
    
    async def handle_429(self):
        """Gérer une erreur 429"""
        self.consecutive_429s += 1
        if self.consecutive_429s <= 3:
            wait_time = 30 * (2 ** (self.consecutive_429s - 1))  # 30s, 60s, 120s
        else:
            wait_time = 300  # 5 minutes après 3 échecs
        
        wait_time += random.uniform(0, wait_time * 0.1)
        logger.warning(f"🚨 {self.api_name} rate limit hit #{self.consecutive_429s}, waiting {wait_time:.1f}s")
        await asyncio.sleep(wait_time)
    
    def reset_429(self):
        """Réinitialiser après succès"""
        if self.consecutive_429s > 0:
            logger.info(f"✅ {self.api_name} recovered from rate limiting")
            self.consecutive_429s = 0

class SymbolFixer:
    """Classe principale pour corriger les symboles"""
    
    def __init__(self, database_path: str = "tokens.db"):
        self.database_path = database_path
        self.session: Optional[ClientSession] = None
        self.is_running = False
        
        # Rate limiters pour chaque API
        self.rate_limiters = {
            'jupiter': RateLimiter('Jupiter', 100),     # 120 req/min
            'dexscreener': RateLimiter('DexScreener', 40), # 50 req/min conservative
            'rugcheck': RateLimiter('RugCheck', 25),    # 30 req/min conservative
            'solscan': RateLimiter('Solscan', 50),      # 60 req/min
            #'helius': RateLimiter('Helius', 50),        # 100 req/min
        }
        
        # Configuration Helius
        self.helius_api_key = ""
        self.helius_rpc_url = f"https://rpc.helius.xyz/?api-key={self.helius_api_key}"
        
        # Statistiques
        self.stats = {
            'total_processed': 0,
            'successful_fixes': 0,
            'api_errors': 0,
            'no_data_found': 0,
            'skipped_max_attempts': 0,
            'cycles_completed': 0,
            'start_time': time.time(),
            'fixes_by_source': {},
            'last_successful_tokens': []  # Les 10 derniers tokens corrigés
        }
        
        # Initialiser le schéma DB
        self.init_database_schema()
    
    def init_database_schema(self):
        """Initialiser/mettre à jour le schéma de la base de données"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            # Vérifier si les colonnes existent déjà
            cursor.execute("PRAGMA table_info(tokens)")
            columns = [row[1] for row in cursor.fetchall()]
            
            # Ajouter les nouvelles colonnes si elles n'existent pas
            if 'symbol_fix_attempts' not in columns:
                logger.info("🔧 Adding symbol_fix_attempts column...")
                cursor.execute('ALTER TABLE tokens ADD COLUMN symbol_fix_attempts INTEGER DEFAULT 0')
                
            if 'last_symbol_fix_attempt' not in columns:
                logger.info("🔧 Adding last_symbol_fix_attempt column...")
                cursor.execute('ALTER TABLE tokens ADD COLUMN last_symbol_fix_attempt DATETIME')
            
            if 'skip_symbol_fix' not in columns:
                logger.info("🔧 Adding skip_symbol_fix column...")
                cursor.execute('ALTER TABLE tokens ADD COLUMN skip_symbol_fix BOOLEAN DEFAULT FALSE')
            
            conn.commit()
            logger.info("✅ Database schema updated")
            
        except sqlite3.Error as e:
            logger.error(f"❌ Database schema error: {e}")
        finally:
            conn.close()
    
    async def start_session(self):
        """Démarrer la session HTTP"""
        connector = TCPConnector(
            limit=50,
            limit_per_host=20,
            ttl_dns_cache=300,
            use_dns_cache=True
        )
        
        self.session = ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=15),
            headers={
                'User-Agent': 'Solana-Symbol-Fixer/1.0',
                'Accept': 'application/json'
            }
        )
        
        logger.info("🚀 HTTP session started")
    
    async def close_session(self):
        """Fermer la session HTTP"""
        if self.session:
            await self.session.close()
        logger.info("🛑 HTTP session closed")
    
    def get_tokens_to_fix(self, batch_size: int, age_hours: Optional[int] = None, 
                         max_attempts: int = 3, retry_delay_hours: int = 1) -> List[Dict]:
        """Récupérer les tokens à corriger avec système de tracking des tentatives"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            # Requête avec système de tentatives
            query = '''
                SELECT address, symbol, name, decimals, logo_uri, 
                       first_discovered_at, updated_at, invest_score,
                       symbol_fix_attempts, last_symbol_fix_attempt
                FROM tokens 
                WHERE (symbol = 'ERROR' OR symbol = 'UNKNOWN' OR symbol IS NULL OR symbol = '')
                AND (skip_symbol_fix IS NULL OR skip_symbol_fix = FALSE)
                AND (symbol_fix_attempts IS NULL OR symbol_fix_attempts < ?)
                AND (last_symbol_fix_attempt IS NULL OR 
                     last_symbol_fix_attempt < datetime("now", "-{} hours", "localtime"))
            '''.format(retry_delay_hours)
            
            params = [max_attempts]
            
            if age_hours:
                query += ' AND first_discovered_at > datetime("now", "-{} hours", "localtime")'.format(age_hours)
            
            # Prioriser les tokens récents et ceux avec un score, et ceux avec moins de tentatives
            query += '''
                ORDER BY 
                    COALESCE(symbol_fix_attempts, 0) ASC,
                    CASE WHEN invest_score > 50 THEN 1 ELSE 2 END,
                    first_discovered_at DESC
                LIMIT ?
            '''
            params.append(batch_size)
            
            cursor.execute(query, params)
            
            tokens = []
            for row in cursor.fetchall():
                tokens.append({
                    'address': row[0],
                    'symbol': row[1] or 'UNKNOWN',
                    'name': row[2],
                    'decimals': row[3],
                    'logo_uri': row[4],
                    'first_discovered_at': row[5],
                    'updated_at': row[6],
                    'invest_score': row[7],
                    'symbol_fix_attempts': row[8] or 0,
                    'last_symbol_fix_attempt': row[9]
                })
            
            # Log des statistiques sur les tokens ignorés
            cursor.execute('''
                SELECT COUNT(*) FROM tokens 
                WHERE (symbol = 'ERROR' OR symbol = 'UNKNOWN' OR symbol IS NULL OR symbol = '')
                AND symbol_fix_attempts >= ?
            ''', (max_attempts,))
            skipped_count = cursor.fetchone()[0]
            
            if skipped_count > 0:
                logger.info(f"📊 {skipped_count} tokens skipped (max attempts reached)")
            
            return tokens
            
        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return []
        finally:
            conn.close()
    
    def update_token_attempt(self, address: str, success: bool):
        """Mettre à jour les compteurs de tentatives après une tentative"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            if success:
                # Succès: reset les tentatives
                cursor.execute('''
                    UPDATE tokens SET 
                        symbol_fix_attempts = 0,
                        last_symbol_fix_attempt = ?,
                        skip_symbol_fix = FALSE
                    WHERE address = ?
                ''', (current_time, address))
                logger.debug(f"✅ Reset attempts for successful fix: {address}")
            else:
                # Échec: incrémenter les tentatives
                cursor.execute('''
                    UPDATE tokens SET 
                        symbol_fix_attempts = COALESCE(symbol_fix_attempts, 0) + 1,
                        last_symbol_fix_attempt = ?
                    WHERE address = ?
                ''', (current_time, address))
                
                # Vérifier si on doit marquer comme skip
                cursor.execute('SELECT symbol_fix_attempts FROM tokens WHERE address = ?', (address,))
                attempts = cursor.fetchone()
                if attempts and attempts[0] >= 1:
                    cursor.execute('UPDATE tokens SET skip_symbol_fix = TRUE WHERE address = ?', (address,))
                    logger.warning(f"🚫 Token {address} marked as skip after {attempts[0]} failed attempts")
            
            conn.commit()
            
        except sqlite3.Error as e:
            logger.error(f"Database error updating attempts for {address}: {e}")
        finally:
            conn.close()
    
    async def fetch_helius_metadata(self, address: str) -> Optional[Dict]:
        """Récupérer les métadonnées via Helius (méthode principale)"""
        await self.rate_limiters['helius'].acquire()
        
        try:
            # Méthode 1: getAsset (plus complète)
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAsset",
                "params": {"id": address}
            }
            
            async with self.session.post(self.helius_rpc_url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result = data.get("result", {})
                    
                    if result:
                        content = result.get("content", {})
                        metadata = content.get("metadata", {})
                        
                        if metadata and metadata.get("symbol"):
                            self.rate_limiters['helius'].reset_429()
                            return {
                                'symbol': metadata.get("symbol", "").strip(),
                                'name': metadata.get("name", "").strip(),
                                'decimals': result.get("token_info", {}).get("decimals", 9),
                                'logo_uri': content.get("files", [{}])[0].get("uri") if content.get("files") else None,
                                'source': 'helius_asset',
                                'confidence': 'high'
                            }
                
                elif resp.status == 429:
                    await self.rate_limiters['helius'].handle_429()
                    return None
        
        except Exception as e:
            logger.debug(f"Helius getAsset error for {address}: {e}")
        
        # Méthode 2: getAccountInfo en fallback
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [
                    address,
                    {"encoding": "base64"}
                ]
            }
            
            async with self.session.post(self.helius_rpc_url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result = data.get("result", {})
                    
                    if result and result.get("value"):
                        # Essayer de parser les données du mint account
                        account_data = result["value"].get("data", [])
                        if account_data and len(account_data) > 0:
                            try:
                                decoded_data = account_data[0]  # Base64 data
                                # Parsing basique - les vrais métadonnées sont souvent ailleurs
                                return {
                                    'symbol': f"TOKEN_{address[:8]}",  # Symbole générique
                                    'name': f"Token {address[:8]}",
                                    'decimals': 9,  # Défaut commun
                                    'logo_uri': None,
                                    'source': 'helius_account',
                                    'confidence': 'low'
                                }
                            except Exception:
                                pass
                
                elif resp.status == 429:
                    await self.rate_limiters['helius'].handle_429()
                    
        except Exception as e:
            logger.debug(f"Helius getAccountInfo error for {address}: {e}")
        
        return None
    
    async def fetch_jupiter_metadata(self, address: str) -> Optional[Dict]:
        """Récupérer via Jupiter token list"""
        await self.rate_limiters['jupiter'].acquire()
        
        try:
            url = "https://token.jup.ag/all"
            
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    tokens = await resp.json()
                    
                    # Chercher notre token
                    for token in tokens:
                        if token.get("address") == address:
                            self.rate_limiters['jupiter'].reset_429()
                            return {
                                'symbol': token.get("symbol", "").strip(),
                                'name': token.get("name", "").strip(),
                                'decimals': token.get("decimals", 9),
                                'logo_uri': token.get("logoURI"),
                                'source': 'jupiter',
                                'confidence': 'high'
                            }
                
                elif resp.status == 429:
                    await self.rate_limiters['jupiter'].handle_429()
                    
        except Exception as e:
            logger.debug(f"Jupiter error for {address}: {e}")
        
        return None
    
    async def fetch_dexscreener_metadata(self, address: str) -> Optional[Dict]:
        """Récupérer via DexScreener avec UN SEUL acquire pour toutes les méthodes"""
        await self.rate_limiters['dexscreener'].acquire()  # UN SEUL acquire !
        
        # Méthode 1: API tokens
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
            
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.debug(f"DexScreener tokens API response for {address}: {json.dumps(data, indent=2)}")
                    
                    if data and data.get("pairs") and len(data["pairs"]) > 0:
                        # Traitement normal des pairs
                        pairs = data["pairs"]
                        best_pair = max(pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0))
                        
                        base_token = best_pair.get("baseToken", {})
                        quote_token = best_pair.get("quoteToken", {})
                        
                        target_token = None
                        if base_token.get("address") == address:
                            target_token = base_token
                        elif quote_token.get("address") == address:
                            target_token = quote_token
                        else:
                            target_token = base_token
                        
                        if target_token and target_token.get("symbol"):
                            symbol = target_token.get("symbol", "").strip()
                            name = target_token.get("name", "").strip()
                            
                            if symbol and symbol not in ['UNKNOWN', 'ERROR', '']:
                                self.rate_limiters['dexscreener'].reset_429()
                                logger.debug(f"DexScreener found via tokens API: {symbol} ({name}) for {address}")
                                
                                return {
                                    'symbol': symbol,
                                    'name': name or symbol,
                                    'decimals': int(target_token.get("decimals", 9)),
                                    'logo_uri': None,
                                    'source': 'dexscreener_tokens',
                                    'confidence': 'medium',
                                    'pair_address': best_pair.get("pairAddress"),
                                    'dex_id': best_pair.get("dexId"),
                                    'liquidity_usd': float(best_pair.get("liquidity", {}).get("usd", 0) or 0)
                                }
                    
                    logger.debug(f"DexScreener tokens API: No pairs or pairs=null for {address}")
                
                elif resp.status == 429:
                    await self.rate_limiters['dexscreener'].handle_429()
                    return None
                elif resp.status == 404:
                    logger.debug(f"DexScreener tokens API: Token {address} not found (404)")
                else:
                    logger.debug(f"DexScreener tokens API: HTTP {resp.status} for {address}")
                    
        except Exception as e:
            logger.debug(f"DexScreener tokens API error for {address}: {e}")
        
        # Méthode 2: API search (SANS acquire supplémentaire !)
        try:
            search_url = f"https://api.dexscreener.com/latest/dex/search/?q={address}"
            
            async with self.session.get(search_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.debug(f"DexScreener search API response for {address}: {json.dumps(data, indent=2)}")
                    
                    if data and data.get("pairs") and len(data["pairs"]) > 0:
                        # Chercher une paire qui contient notre token
                        for pair in data["pairs"]:
                            base_token = pair.get("baseToken", {})
                            quote_token = pair.get("quoteToken", {})
                            pair_address = pair.get("pairAddress", "")
                            
                            target_token = None
                            
                            if base_token.get("address") == address:
                                target_token = base_token
                                logger.debug(f"Found as baseToken in pair {pair_address}")
                            elif quote_token.get("address") == address:
                                target_token = quote_token
                                logger.debug(f"Found as quoteToken in pair {pair_address}")
                            elif pair_address.lower() == address.lower():
                                target_token = base_token
                                logger.debug(f"Address matches pairAddress, using baseToken: {base_token.get('symbol')}")
                            
                            if target_token and target_token.get("symbol"):
                                symbol = target_token.get("symbol", "").strip()
                                name = target_token.get("name", "").strip()
                                
                                if symbol and symbol not in ['UNKNOWN', 'ERROR', '']:
                                    self.rate_limiters['dexscreener'].reset_429()
                                    logger.debug(f"DexScreener found via search API: {symbol} ({name}) for {address}")
                                    
                                    return {
                                        'symbol': symbol,
                                        'name': name or symbol,
                                        'decimals': int(target_token.get("decimals", 9)),
                                        'logo_uri': None,
                                        'source': 'dexscreener_search',
                                        'confidence': 'high',
                                        'pair_address': pair.get("pairAddress"),
                                        'dex_id': pair.get("dexId"),
                                        'liquidity_usd': float(pair.get("liquidity", {}).get("usd", 0) or 0),
                                        'token_address': target_token.get("address")
                                    }
                    
                    logger.debug(f"DexScreener search API: No matching pairs found for {address}")
                
                elif resp.status == 429:
                    await self.rate_limiters['dexscreener'].handle_429()
                elif resp.status == 404:
                    logger.debug(f"DexScreener search API: Not found (404) for {address}")
                else:
                    logger.debug(f"DexScreener search API: HTTP {resp.status} for {address}")
                    
        except Exception as e:
            logger.debug(f"DexScreener search API error for {address}: {e}")
        
        # Méthode 3: API Solana (SANS acquire supplémentaire !)
        try:
            solana_url = f"https://api.dexscreener.com/latest/dex/solana/{address}"
            
            async with self.session.get(solana_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.debug(f"DexScreener Solana API response for {address}: {json.dumps(data, indent=2)}")
                    
                    if data and data.get("pairs") and len(data["pairs"]) > 0:
                        pairs = data["pairs"]
                        best_pair = max(pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0))
                        
                        base_token = best_pair.get("baseToken", {})
                        quote_token = best_pair.get("quoteToken", {})
                        
                        target_token = None
                        if base_token.get("address") == address:
                            target_token = base_token
                        elif quote_token.get("address") == address:
                            target_token = quote_token
                        else:
                            target_token = base_token
                        
                        if target_token and target_token.get("symbol"):
                            symbol = target_token.get("symbol", "").strip()
                            name = target_token.get("name", "").strip()
                            
                            if symbol and symbol not in ['UNKNOWN', 'ERROR', '']:
                                self.rate_limiters['dexscreener'].reset_429()
                                logger.debug(f"DexScreener found via Solana API: {symbol} ({name}) for {address}")
                                
                                return {
                                    'symbol': symbol,
                                    'name': name or symbol,
                                    'decimals': int(target_token.get("decimals", 9)),
                                    'logo_uri': None,
                                    'source': 'dexscreener_solana',
                                    'confidence': 'medium',
                                    'pair_address': best_pair.get("pairAddress"),
                                    'dex_id': best_pair.get("dexId"),
                                    'liquidity_usd': float(best_pair.get("liquidity", {}).get("usd", 0) or 0)
                                }
                
                elif resp.status == 429:
                    await self.rate_limiters['dexscreener'].handle_429()
                elif resp.status == 404:
                    logger.debug(f"DexScreener Solana API: Not found (404) for {address}")
                else:
                    logger.debug(f"DexScreener Solana API: HTTP {resp.status} for {address}")
                    
        except Exception as e:
            logger.debug(f"DexScreener Solana API error for {address}: {e}")
        
        return None
    
    async def fetch_solscan_metadata(self, address: str) -> Optional[Dict]:
        """Récupérer via Solscan"""
        await self.rate_limiters['solscan'].acquire()
        
        try:
            url = f"https://public-api.solscan.io/token/meta?tokenAddress={address}"
            
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    if data and data.get("symbol"):
                        self.rate_limiters['solscan'].reset_429()
                        return {
                            'symbol': data.get("symbol", "").strip(),
                            'name': data.get("name", "").strip(),
                            'decimals': data.get("decimals", 9),
                            'logo_uri': data.get("icon"),
                            'source': 'solscan',
                            'confidence': 'medium'
                        }
                
                elif resp.status == 429:
                    await self.rate_limiters['solscan'].handle_429()
                    
        except Exception as e:
            logger.debug(f"Solscan error for {address}: {e}")
        
        return None
    
    async def get_token_metadata(self, address: str) -> Optional[FixedTokenData]:
        """Récupérer les métadonnées d'un token depuis plusieurs sources avec priorisation intelligente"""
        
        logger.debug(f"🔍 Starting metadata search for {address}")
        
        # NOUVEAU: Prioriser DexScreener car il a souvent les vrais symboles
        # Essayer les sources dans un ordre optimisé
        sources = [
            ('dexscreener', self.fetch_dexscreener_metadata),  # Maintenant en premier !
            ('jupiter', self.fetch_jupiter_metadata),
            ('solscan', self.fetch_solscan_metadata),
            ('helius', self.fetch_helius_metadata),           # Helius en dernier (symboles génériques)
        ]
        
        found_data = []  # Collecter toutes les données trouvées pour debug
        best_result = None
        best_score = 0
        
        for source_name, fetch_func in sources:
            try:
                logger.debug(f"🔍 Trying {source_name} for {address}")
                metadata = await fetch_func(address)
                
                if metadata:
                    found_data.append((source_name, metadata))
                    logger.debug(f"✅ {source_name} returned: {metadata}")
                    
                    symbol = metadata.get('symbol', '').strip()
                    confidence = metadata.get('confidence', 'medium')
                    
                    # Calculer un score de qualité pour chaque résultat
                    quality_score = 0
                    
                    # Critères de qualité du symbole
                    if symbol and symbol not in ['ERROR', 'UNKNOWN', ''] and len(symbol) >= 1 and len(symbol) <= 20:
                        quality_score += 10  # Symbole valide
                        
                        # Bonus pour symboles qui ne sont pas génériques
                        if not symbol.startswith('TOKEN_'):
                            quality_score += 20
                        
                        # Bonus par source (DexScreener prioritaire)
                        if source_name.startswith('dexscreener'):
                            quality_score += 30  # DexScreener très prioritaire
                        elif source_name == 'jupiter':
                            quality_score += 25  # Jupiter aussi fiable
                        elif source_name == 'solscan':
                            quality_score += 15  # Solscan moyen
                        elif source_name.startswith('helius'):
                            quality_score += 5   # Helius en dernier (souvent générique)
                        
                        # Bonus par confidence
                        if confidence == 'high':
                            quality_score += 15
                        elif confidence == 'medium':
                            quality_score += 10
                        # low = +0
                        
                        # Bonus si on a aussi un nom différent du symbole
                        name = metadata.get('name', '').strip()
                        if name and name != symbol and not name.startswith('Token '):
                            quality_score += 10
                        
                        logger.debug(f"📊 {source_name} quality score: {quality_score} (symbol: {symbol})")
                        
                        # Garder le meilleur résultat
                        if quality_score > best_score:
                            best_score = quality_score
                            best_result = FixedTokenData(
                                address=address,
                                old_symbol='ERROR',  # Sera mis à jour par l'appelant
                                new_symbol=symbol,
                                name=name or symbol,
                                decimals=metadata.get('decimals', 9),
                                logo_uri=metadata.get('logo_uri'),
                                source=source_name,
                                confidence=confidence
                            )
                            logger.debug(f"🏆 New best result: {symbol} from {source_name} (score: {quality_score})")
                
                else:
                    logger.debug(f"❌ {source_name} returned no data for {address}")
                
            except Exception as e:
                logger.debug(f"❌ Error with {source_name} for {address}: {e}")
                continue
        
        # Debug final
        if found_data:
            logger.info(f"🎯 Found {len(found_data)} sources with data:")
            for source, data in found_data:
                symbol = data.get('symbol', 'N/A')
                confidence = data.get('confidence', 'N/A')
                logger.info(f"   {source}: {symbol} ({confidence})")
        
        if best_result:
            logger.info(f"✅ Selected BEST result: {best_result.new_symbol} from {best_result.source} (score: {best_score})")
            return best_result
        else:
            logger.debug(f"❌ No valid symbol found from any source for {address}")
            return None
    
    def update_token_in_db(self, fixed_data: FixedTokenData) -> bool:
        """Mettre à jour le token dans la DB"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            # Récupérer l'ancien symbole
            cursor.execute('SELECT symbol FROM tokens WHERE address = ?', (fixed_data.address,))
            old_row = cursor.fetchone()
            if old_row:
                fixed_data.old_symbol = old_row[0] or 'UNKNOWN'
            
            # Mettre à jour
            cursor.execute('''
                UPDATE tokens SET 
                    symbol = ?,
                    name = COALESCE(?, name),
                    decimals = COALESCE(?, decimals),
                    logo_uri = COALESCE(?, logo_uri),
                    updated_at = ?
                WHERE address = ?
            ''', (
                fixed_data.new_symbol,
                fixed_data.name if fixed_data.name else None,
                fixed_data.decimals,
                fixed_data.logo_uri,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                fixed_data.address
            ))
            
            if cursor.rowcount > 0:
                conn.commit()
                return True
            else:
                logger.warning(f"Token {fixed_data.address} not found in DB")
                return False
                
        except sqlite3.Error as e:
            logger.error(f"Database error updating {fixed_data.address}: {e}")
            return False
        finally:
            conn.close()
    
    async def process_batch(self, tokens: List[Dict]) -> Dict:
        """Traiter un batch de tokens avec système de tracking des tentatives"""
        batch_stats = {
            'processed': 0,
            'fixed': 0,
            'errors': 0,
            'no_data': 0,
            'retry_tokens': 0
        }
        
        logger.info(f"🔧 Processing batch of {len(tokens)} tokens")
        
        for i, token in enumerate(tokens, 1):
            logger.info(f"📊 Rate limiter status:")
            for name, limiter in self.rate_limiters.items():
                logger.info(f"   {name}: {limiter.requests_made}/{limiter.requests_per_minute} "
                        f"(backoff: {limiter.backoff_multiplier:.2f}x, 429s: {limiter.consecutive_429s})")

            address = token['address']
            old_symbol = token['symbol']
            attempts = token.get('symbol_fix_attempts', 0)
            
            try:
                logger.info(f"[{i}/{len(tokens)}] 🔍 Fixing: {old_symbol} ({address[:8]}...) [attempt #{attempts + 1}]")
                
                if attempts > 0:
                    batch_stats['retry_tokens'] += 1
                    logger.info(f"🔄 Retry token - previous attempts: {attempts}")
                
                # Récupérer les nouvelles métadonnées
                fixed_data = await self.get_token_metadata(address)
                
                if fixed_data:
                    # Mettre à jour en DB
                    if self.update_token_in_db(fixed_data):
                        batch_stats['fixed'] += 1
                        self.stats['successful_fixes'] += 1
                        
                        # Marquer comme succès dans le système de tentatives
                        self.update_token_attempt(address, success=True)
                        
                        # Statistiques par source
                        source = fixed_data.source
                        self.stats['fixes_by_source'][source] = self.stats['fixes_by_source'].get(source, 0) + 1
                        
                        # Garder les derniers tokens corrigés
                        self.stats['last_successful_tokens'].append({
                            'address': address,
                            'old_symbol': old_symbol,
                            'new_symbol': fixed_data.new_symbol,
                            'name': fixed_data.name,
                            'source': fixed_data.source,
                            'confidence': fixed_data.confidence,
                            'attempts': attempts + 1,
                            'timestamp': datetime.now().strftime('%H:%M:%S')
                        })
                        
                        # Garder seulement les 10 derniers
                        self.stats['last_successful_tokens'] = self.stats['last_successful_tokens'][-10:]
                        
                        logger.info(f"✅ Fixed: {old_symbol} → {fixed_data.new_symbol} ({fixed_data.source}, {fixed_data.confidence}) after {attempts + 1} attempts")
                    else:
                        batch_stats['errors'] += 1
                        self.stats['api_errors'] += 1
                        # Marquer comme échec
                        self.update_token_attempt(address, success=False)
                else:
                    batch_stats['no_data'] += 1
                    self.stats['no_data_found'] += 1
                    # Marquer comme échec
                    self.update_token_attempt(address, success=False)
                    logger.debug(f"❌ No metadata found for {address}")
                
                batch_stats['processed'] += 1
                self.stats['total_processed'] += 1
                
                # Petit délai entre tokens pour éviter de surcharger
                if i < len(tokens):
                    await asyncio.sleep(2.0)
                
            except Exception as e:
                logger.error(f"Error processing {address}: {e}")
                batch_stats['errors'] += 1
                self.stats['api_errors'] += 1
                # Marquer comme échec en cas d'exception
                self.update_token_attempt(address, success=False)
                continue
        
        return batch_stats
    
    def reset_failed_tokens(self, reset_skipped: bool = False):
        """Réinitialiser les compteurs de tentatives pour relancer des tokens"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            if reset_skipped:
                # Réinitialiser aussi les tokens marqués comme skip
                cursor.execute('''
                    UPDATE tokens SET 
                        symbol_fix_attempts = 0,
                        last_symbol_fix_attempt = NULL,
                        skip_symbol_fix = FALSE
                    WHERE (symbol = 'ERROR' OR symbol = 'UNKNOWN' OR symbol IS NULL OR symbol = '')
                ''')
                message = "🔄 Reset ALL failed tokens (including skipped)"
            else:
                # Réinitialiser seulement les tokens non-skip
                cursor.execute('''
                    UPDATE tokens SET 
                        symbol_fix_attempts = 0,
                        last_symbol_fix_attempt = NULL
                    WHERE (symbol = 'ERROR' OR symbol = 'UNKNOWN' OR symbol IS NULL OR symbol = '')
                    AND (skip_symbol_fix IS NULL OR skip_symbol_fix = FALSE)
                ''')
                message = "🔄 Reset failed tokens (excluding permanently skipped)"
            
            affected = cursor.rowcount
            conn.commit()
            logger.info(f"{message}: {affected} tokens reset")
            
        except sqlite3.Error as e:
            logger.error(f"Database error resetting tokens: {e}")
        finally:
            conn.close()
    
    def get_fix_stats(self) -> Dict:
        """Obtenir des statistiques sur l'état des tokens à corriger"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            stats = {}
            
            # Total tokens à corriger
            cursor.execute('''
                SELECT COUNT(*) FROM tokens 
                WHERE (symbol = 'ERROR' OR symbol = 'UNKNOWN' OR symbol IS NULL OR symbol = '')
            ''')
            stats['total_to_fix'] = cursor.fetchone()[0]
            
            # Tokens jamais tentés
            cursor.execute('''
                SELECT COUNT(*) FROM tokens 
                WHERE (symbol = 'ERROR' OR symbol = 'UNKNOWN' OR symbol IS NULL OR symbol = '')
                AND (symbol_fix_attempts IS NULL OR symbol_fix_attempts = 0)
            ''')
            stats['never_tried'] = cursor.fetchone()[0]
            
            # Tokens avec tentatives en cours
            cursor.execute('''
                SELECT COUNT(*) FROM tokens 
                WHERE (symbol = 'ERROR' OR symbol = 'UNKNOWN' OR symbol IS NULL OR symbol = '')
                AND symbol_fix_attempts > 0 AND symbol_fix_attempts < 3
                AND (skip_symbol_fix IS NULL OR skip_symbol_fix = FALSE)
            ''')
            stats['in_progress'] = cursor.fetchone()[0]
            
            # Tokens définitivement skip
            cursor.execute('''
                SELECT COUNT(*) FROM tokens 
                WHERE (symbol = 'ERROR' OR symbol = 'UNKNOWN' OR symbol IS NULL OR symbol = '')
                AND (symbol_fix_attempts >= 3 OR skip_symbol_fix = TRUE)
            ''')
            stats['permanently_skipped'] = cursor.fetchone()[0]
            
            # Répartition par nombre de tentatives
            cursor.execute('''
                SELECT COALESCE(symbol_fix_attempts, 0) as attempts, COUNT(*) 
                FROM tokens 
                WHERE (symbol = 'ERROR' OR symbol = 'UNKNOWN' OR symbol IS NULL OR symbol = '')
                GROUP BY COALESCE(symbol_fix_attempts, 0)
                ORDER BY attempts
            ''')
            stats['by_attempts'] = dict(cursor.fetchall())
            
            return stats
            
        except sqlite3.Error as e:
            logger.error(f"Database error getting stats: {e}")
            return {}
        finally:
            conn.close()
    
    def log_cycle_stats(self, batch_stats: Dict, cycle_num: int):
        """Logger les statistiques du cycle avec informations sur les tentatives"""
        runtime = time.time() - self.stats['start_time']
        
        logger.info("=" * 80)
        logger.info(f"📊 CYCLE #{cycle_num} COMPLETED")
        logger.info("=" * 80)
        logger.info(f"🔧 This cycle: {batch_stats['fixed']}/{batch_stats['processed']} fixed")
        if batch_stats['retry_tokens'] > 0:
            logger.info(f"🔄 Retry tokens in this cycle: {batch_stats['retry_tokens']}")
        logger.info(f"📈 Total runtime: {runtime/60:.1f} minutes")
        logger.info(f"📊 Overall stats:")
        logger.info(f"   ✅ Total fixed: {self.stats['successful_fixes']}")
        logger.info(f"   📦 Total processed: {self.stats['total_processed']}")
        logger.info(f"   🔄 Cycles completed: {self.stats['cycles_completed']}")
        logger.info(f"   ❌ API errors: {self.stats['api_errors']}")
        logger.info(f"   ⚪ No data found: {self.stats['no_data_found']}")
        logger.info(f"   🚫 Skipped (max attempts): {self.stats['skipped_max_attempts']}")
        
        # Statistiques détaillées sur l'état des tokens
        fix_stats = self.get_fix_stats()
        if fix_stats:
            logger.info(f"📋 Token fix status:")
            logger.info(f"   🎯 Total to fix: {fix_stats.get('total_to_fix', 0)}")
            logger.info(f"   🆕 Never tried: {fix_stats.get('never_tried', 0)}")
            logger.info(f"   🔄 In progress: {fix_stats.get('in_progress', 0)}")
            logger.info(f"   🚫 Permanently skipped: {fix_stats.get('permanently_skipped', 0)}")
            
            if fix_stats.get('by_attempts'):
                logger.info(f"   📊 By attempts: {fix_stats['by_attempts']}")
        
        # Statistiques par source
        if self.stats['fixes_by_source']:
            logger.info(f"📡 Fixes by source:")
            for source, count in sorted(self.stats['fixes_by_source'].items(), key=lambda x: x[1], reverse=True):
                logger.info(f"   {source}: {count}")
        
        # Derniers tokens corrigés
        if self.stats['last_successful_tokens']:
            logger.info(f"🎯 Last successful fixes:")
            for token in self.stats['last_successful_tokens'][-5:]:  # 5 derniers
                attempts_info = f" (attempt #{token['attempts']})" if token.get('attempts', 1) > 1 else ""
                logger.info(f"   {token['timestamp']} | {token['old_symbol']} → {token['new_symbol']} | {token['source']}{attempts_info}")
        
        logger.info("=" * 80)
    
    async def run_continuous(self, batch_size: int = 20, cycle_interval_minutes: float = 15, 
                           age_hours: Optional[int] = None, max_cycles: Optional[int] = None,
                           max_attempts: int = 3, retry_delay_hours: int = 1):
        """Lancer le processus en continu avec système de tentatives"""
        self.is_running = True
        logger.info("🚀 Starting continuous symbol fixing with attempt tracking")
        logger.info(f"📋 Config: batch_size={batch_size}, cycle_interval={cycle_interval_minutes}min")
        logger.info(f"🔄 Retry config: max_attempts={max_attempts}, retry_delay={retry_delay_hours}h")
        
        await self.start_session()
        
        try:
            cycle_num = 0
            
            while self.is_running:
                cycle_num += 1
                logger.info(f"\n🔄 Starting cycle #{cycle_num}")
                
                # Récupérer les tokens à corriger avec système de tentatives
                tokens_to_fix = self.get_tokens_to_fix(batch_size, age_hours, max_attempts, retry_delay_hours)
                
                if not tokens_to_fix:
                    logger.info("✅ No tokens to fix found!")
                    
                    # Afficher un résumé de l'état
                    fix_stats = self.get_fix_stats()
                    if fix_stats.get('total_to_fix', 0) > 0:
                        logger.info(f"📊 Remaining tokens: {fix_stats['total_to_fix']} total, "
                                  f"{fix_stats.get('permanently_skipped', 0)} permanently skipped, "
                                  f"{fix_stats.get('in_progress', 0)} waiting for retry")
                    
                    if max_cycles and cycle_num >= max_cycles:
                        break
                    
                    logger.info(f"⏰ Waiting {cycle_interval_minutes} minutes before next cycle...")
                    await asyncio.sleep(cycle_interval_minutes * 60)
                    continue
                
                logger.info(f"📋 Found {len(tokens_to_fix)} tokens to fix")
                
                # Traiter le batch
                batch_stats = await self.process_batch(tokens_to_fix)
                
                # Statistiques du cycle
                self.stats['cycles_completed'] += 1
                self.stats['skipped_max_attempts'] = self.get_fix_stats().get('permanently_skipped', 0)
                self.log_cycle_stats(batch_stats, cycle_num)
                
                # Arrêter si nombre max de cycles atteint
                if max_cycles and cycle_num >= max_cycles:
                    logger.info(f"🏁 Maximum cycles ({max_cycles}) reached")
                    break
                
                # Attendre avant le prochain cycle
                logger.info(f"⏰ Waiting {cycle_interval_minutes} minutes before next cycle...")
                
                # Attente interruptible
                for _ in range(int(cycle_interval_minutes * 60)):
                    if not self.is_running:
                        break
                    await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"❌ Error in continuous mode: {e}")
        finally:
            await self.close_session()
            self.log_final_stats()
    
    def log_final_stats(self):
        """Afficher les statistiques finales avec informations sur les tentatives"""
        runtime = time.time() - self.stats['start_time']
        
        logger.info("=" * 100)
        logger.info("🏁 SYMBOL FIXER FINAL STATS")
        logger.info("=" * 100)
        logger.info(f"⏱️  Total runtime: {runtime/3600:.2f} hours")
        logger.info(f"🔄 Cycles completed: {self.stats['cycles_completed']}")
        logger.info(f"📦 Tokens processed: {self.stats['total_processed']}")
        logger.info(f"✅ Symbols fixed: {self.stats['successful_fixes']}")
        logger.info(f"🚫 Permanently skipped: {self.stats.get('skipped_max_attempts', 0)}")
        
        if self.stats['total_processed'] > 0:
            success_rate = (self.stats['successful_fixes'] / self.stats['total_processed']) * 100
            logger.info(f"📈 Success rate: {success_rate:.1f}%")
            
            if runtime > 0:
                throughput = self.stats['total_processed'] / (runtime / 60)
                logger.info(f"⚡ Throughput: {throughput:.2f} tokens/minute")
        
        # Statistiques finales sur l'état des tokens
        fix_stats = self.get_fix_stats()
        if fix_stats:
            logger.info(f"📊 Final token status:")
            logger.info(f"   🎯 Still to fix: {fix_stats.get('total_to_fix', 0)}")
            logger.info(f"   🚫 Permanently skipped: {fix_stats.get('permanently_skipped', 0)}")
            logger.info(f"   🔄 Awaiting retry: {fix_stats.get('in_progress', 0)}")
        
        if self.stats['fixes_by_source']:
            logger.info(f"📡 Sources used:")
            total_fixes = sum(self.stats['fixes_by_source'].values())
            for source, count in sorted(self.stats['fixes_by_source'].items(), key=lambda x: x[1], reverse=True):
                percentage = (count / total_fixes) * 100
                logger.info(f"   {source}: {count} ({percentage:.1f}%)")
        
        logger.info("=" * 100)
    
    async def test_specific_token(self, address: str):
        """Test spécifique pour diagnostiquer un token"""
        logger.info(f"🧪 DIAGNOSTIC MODE for {address}")
        logger.info("=" * 80)
        
        await self.start_session()
        
        try:
            # Afficher l'état actuel du token
            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT symbol, symbol_fix_attempts, last_symbol_fix_attempt, skip_symbol_fix
                FROM tokens WHERE address = ?
            ''', (address,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                symbol, attempts, last_attempt, skip = row
                logger.info(f"📊 Current status:")
                logger.info(f"   Symbol: {symbol}")
                logger.info(f"   Attempts: {attempts or 0}")
                logger.info(f"   Last attempt: {last_attempt or 'Never'}")
                logger.info(f"   Skip flag: {skip or False}")
            
            # Test chaque source individuellement
            sources = [
                ('Helius', self.fetch_helius_metadata),
                ('Jupiter', self.fetch_jupiter_metadata),
                ('DexScreener', self.fetch_dexscreener_metadata),
                ('Solscan', self.fetch_solscan_metadata)
            ]
            
            for source_name, fetch_func in sources:
                logger.info(f"\n🔍 Testing {source_name}...")
                try:
                    result = await fetch_func(address)
                    if result:
                        logger.info(f"✅ {source_name} SUCCESS:")
                        for key, value in result.items():
                            logger.info(f"   {key}: {value}")
                    else:
                        logger.info(f"❌ {source_name} returned None")
                except Exception as e:
                    logger.error(f"❌ {source_name} ERROR: {e}")
            
            # Test la fonction principale
            logger.info(f"\n🎯 Testing main get_token_metadata function...")
            result = await self.get_token_metadata(address)
            
            if result:
                logger.info(f"✅ FINAL RESULT:")
                logger.info(f"   Symbol: {result.new_symbol}")
                logger.info(f"   Name: {result.name}")
                logger.info(f"   Source: {result.source}")
                logger.info(f"   Confidence: {result.confidence}")
            else:
                logger.info(f"❌ FINAL RESULT: None")
        
        finally:
            await self.close_session()
        
        logger.info("=" * 80)

    def stop(self):
        """Arrêter le processus"""
        self.is_running = False
        logger.info("🛑 Stop requested")

def main():
    """Fonction principale"""
    parser = argparse.ArgumentParser(description="🔧 Symbol Fixer - Automatic token symbol repair with attempt tracking")
    
    parser.add_argument("--database", default="tokens.db", help="Database path")
    parser.add_argument("--batch-size", type=int, default=20, help="Tokens per batch (default: 20)")
    parser.add_argument("--cycle-interval", type=float, default=15, help="Minutes between cycles (default: 15)")
    parser.add_argument("--age-hours", type=int, help="Only fix tokens discovered in last N hours")
    parser.add_argument("--max-cycles", type=int, help="Maximum number of cycles to run")
    parser.add_argument("--max-attempts", type=int, default=3, help="Maximum attempts per token (default: 3)")
    parser.add_argument("--retry-delay", type=int, default=1, help="Hours to wait before retry (default: 1)")
    parser.add_argument("--single-cycle", action="store_true", help="Run only one cycle")
    parser.add_argument("--reset-failed", action="store_true", help="Reset failed token attempts before starting")
    parser.add_argument("--reset-all", action="store_true", help="Reset ALL token attempts (including skipped)")
    parser.add_argument("--show-stats", action="store_true", help="Show current fix statistics and exit")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be fixed without updating DB")
    parser.add_argument("--test-token", type=str, help="Test a specific token address for debugging")
    parser.add_argument("--log-level", choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], 
                       default='INFO', help="Logging level")
    
    args = parser.parse_args()
    
    # Configuration du logging
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    
    # Créer le fixer
    fixer = SymbolFixer(args.database)
    
    try:
        if args.show_stats:
            # Afficher les statistiques et quitter
            stats = fixer.get_fix_stats()
            logger.info("📊 CURRENT FIX STATISTICS")
            logger.info("=" * 50)
            logger.info(f"🎯 Total tokens to fix: {stats.get('total_to_fix', 0)}")
            logger.info(f"🆕 Never tried: {stats.get('never_tried', 0)}")
            logger.info(f"🔄 In progress: {stats.get('in_progress', 0)}")
            logger.info(f"🚫 Permanently skipped: {stats.get('permanently_skipped', 0)}")
            if stats.get('by_attempts'):
                logger.info(f"📊 By attempts: {stats['by_attempts']}")
            return
        
        if args.reset_all:
            fixer.reset_failed_tokens(reset_skipped=True)
            return
        elif args.reset_failed:
            fixer.reset_failed_tokens(reset_skipped=False)
            return
        
        if args.test_token:
            # Mode test spécifique
            asyncio.run(fixer.test_specific_token(args.test_token))
        elif args.single_cycle:
            # Mode single cycle
            async def single_run():
                await fixer.start_session()
                tokens = fixer.get_tokens_to_fix(args.batch_size, args.age_hours, 
                                                args.max_attempts, args.retry_delay)
                if tokens:
                    batch_stats = await fixer.process_batch(tokens)
                    fixer.log_cycle_stats(batch_stats, 1)
                else:
                    logger.info("✅ No tokens to fix found")
                    # Afficher les stats même si aucun token
                    stats = fixer.get_fix_stats()
                    if stats.get('total_to_fix', 0) > 0:
                        logger.info(f"📊 {stats['total_to_fix']} tokens still need fixing")
                await fixer.close_session()
            
            asyncio.run(single_run())
        else:
            # Mode continu
            asyncio.run(fixer.run_continuous(
                batch_size=args.batch_size,
                cycle_interval_minutes=args.cycle_interval,
                age_hours=args.age_hours,
                max_cycles=args.max_cycles,
                max_attempts=args.max_attempts,
                retry_delay_hours=args.retry_delay
            ))
            
    except KeyboardInterrupt:
        logger.info("\n🛑 Interrupted by user")
        fixer.stop()
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")

if __name__ == "__main__":
    main()