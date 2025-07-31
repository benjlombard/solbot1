#!/usr/bin/env python3
"""
🎯 Pump.fun Existence Checker
Vérifie si les tokens avec status='no_dex_data' existent sur Pump.fun
"""

import asyncio
import aiohttp
import sqlite3
import time
import logging
import argparse
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from aiohttp import ClientSession, TCPConnector
import random

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('pump_fun_checker')

@dataclass
class PumpFunResult:
    """Résultat de vérification Pump.fun"""
    address: str
    exists_on_pump: bool
    symbol: Optional[str] = None
    name: Optional[str] = None
    error: Optional[str] = None

class RateLimiter:
    """Rate limiter pour l'API Pump.fun"""
    
    def __init__(self, requests_per_minute: int = 120):
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

class PumpFunChecker:
    """Vérificateur d'existence sur Pump.fun"""
    
    def __init__(self, database_path: str = "tokens.db"):
        self.database_path = database_path
        self.session: Optional[ClientSession] = None
        self.rate_limiter = RateLimiter(requests_per_minute=100)  # Conservative
        self.is_running = False
        
        # URLs Pump.fun correctes (mises à jour 2025)
        self.pump_fun_urls = [
            "https://frontend-api.pump.fun/coins/{}",      # URL principale
            "https://frontend-api-v2.pump.fun/coins/{}",   # Version 2
            "https://frontend-api-v3.pump.fun/coins/{}",   # Version 3
        ]
        
        # Statistiques
        self.stats = {
            'total_processed': 0,
            'exists_on_pump': 0,
            'not_on_pump': 0,
            'api_errors': 0,
            'database_updates': 0,
            'cycles_completed': 0,
            'start_time': time.time(),
            'last_successful_tokens': []
        }
    
    def migrate_database(self):
        """Ajouter la colonne exists_on_pump si elle n'existe pas"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            # Vérifier si la colonne existe
            cursor.execute("PRAGMA table_info(tokens)")
            columns = [col[1] for col in cursor.fetchall()]
            
            if 'exists_on_pump' not in columns:
                cursor.execute("ALTER TABLE tokens ADD COLUMN exists_on_pump BOOLEAN DEFAULT NULL")
                logger.info("✅ Added column: exists_on_pump")
                conn.commit()
            else:
                logger.info("✅ Column exists_on_pump already exists")
                
        except sqlite3.Error as e:
            logger.error(f"Database migration error: {e}")
        finally:
            conn.close()
    
    def get_tokens_to_check(self, batch_size: int, status_filter: str = 'no_dex_data', 
                          recheck_failures: bool = False, recheck_after_hours: int = 24) -> List[Dict]:
        """Récupérer les tokens à vérifier avec gestion intelligente des re-tests"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            if recheck_failures:
                # Mode re-check : retester les échecs après X heures
                query = '''
                    SELECT address, symbol, name, status, first_discovered_at, exists_on_pump, updated_at
                    FROM tokens 
                    WHERE (status = ? OR status IS NULL)
                    AND (
                        exists_on_pump IS NULL 
                        OR (exists_on_pump = 0 AND updated_at < datetime('now', '-{} hours', 'localtime'))
                    )
                    AND address IS NOT NULL
                '''.format(recheck_after_hours)
            else:
                # Mode normal : ne tester que les tokens jamais testés
                query = '''
                    SELECT address, symbol, name, status, first_discovered_at, exists_on_pump, updated_at
                    FROM tokens 
                    WHERE (status = ? OR status IS NULL)
                    AND exists_on_pump IS NULL
                    AND address IS NOT NULL
                '''
            
            params = [status_filter]
            
            # Prioriser les tokens récents
            query += '''
                ORDER BY 
                    CASE WHEN first_discovered_at > datetime('now', '-24 hours', 'localtime') THEN 1 ELSE 2 END,
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
                    'status': row[3],
                    'first_discovered_at': row[4],
                    'exists_on_pump': row[5],
                    'updated_at': row[6]
                })
            
            return tokens
            
        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            return []
        finally:
            conn.close()
    
    async def start_session(self):
        """Démarrer la session HTTP"""
        connector = TCPConnector(
            limit=30,
            limit_per_host=15,
            ttl_dns_cache=300,
            use_dns_cache=True
        )
        
        self.session = ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=10),
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://pump.fun/'
            }
        )
        
        logger.info("🚀 HTTP session started")
    
    async def close_session(self):
        """Fermer la session HTTP"""
        if self.session:
            await self.session.close()
        logger.info("🛑 HTTP session closed")
    
    async def check_pump_fun_existence(self, address: str) -> PumpFunResult:
        """Vérifier si un token existe sur Pump.fun"""
        await self.rate_limiter.acquire()
        
        # Essayer différentes URLs dans l'ordre
        for i, url_template in enumerate(self.pump_fun_urls):
            try:
                url = url_template.format(address)
                logger.debug(f"🔍 Checking URL {i+1}: {url}")
                
                async with self.session.get(url) as resp:
                    if resp.status == 200:
                        try:
                            data = await resp.json()
                            
                            # Vérifier si on a des données valides
                            if data and isinstance(data, dict):
                                # Pump.fun utilise différents formats selon l'endpoint
                                mint = data.get('mint') or data.get('address') or data.get('tokenAddress')
                                symbol = data.get('symbol') or data.get('name')
                                name = data.get('name') or data.get('description')
                                creator = data.get('creator')
                                market_cap = data.get('market_cap') or data.get('marketCap') or data.get('usd_market_cap')
                                
                                # Pump.fun peut aussi retourner directement les données sans wrapper
                                if not mint and 'mint' not in data:
                                    # Parfois les données sont dans un format différent
                                    if 'id' in data:
                                        mint = data.get('id')
                                    elif 'contract' in data:
                                        mint = data.get('contract')
                                
                                if mint and mint.lower() == address.lower():
                                    self.rate_limiter.reset_429()
                                    logger.debug(f"✅ Found on pump.fun: {symbol} ({url})")
                                    
                                    return PumpFunResult(
                                        address=address,
                                        exists_on_pump=True,
                                        symbol=symbol,
                                        name=name
                                    )
                                elif mint:
                                    logger.debug(f"❓ Different mint in response: {mint} != {address}")
                                else:
                                    # Parfois le token existe mais les champs sont différents
                                    # Si on a une réponse 200 avec des données, c'est probablement bon
                                    if symbol or name or creator:
                                        logger.debug(f"✅ Token exists with alternate format: {symbol}")
                                        return PumpFunResult(
                                            address=address,
                                            exists_on_pump=True,
                                            symbol=symbol,
                                            name=name
                                        )
                            
                            # Si pas de mint match, essayer l'URL suivante
                            logger.debug(f"❓ No mint match in response from {url}")
                            logger.debug(f"Response preview: {str(data)[:200]}...")
                            
                        except Exception as json_error:
                            logger.debug(f"❌ JSON parse error from {url}: {json_error}")
                            # Log plus de détails sur l'erreur
                            try:
                                text = await resp.text()
                                logger.debug(f"Raw response preview: {text[:300]}...")
                            except:
                                pass
                            continue
                    
                    elif resp.status == 404:
                        logger.debug(f"❌ 404 from {url}")
                        continue  # Essayer l'URL suivante
                    
                    elif resp.status == 429:
                        await self.rate_limiter.handle_429()
                        return PumpFunResult(
                            address=address,
                            exists_on_pump=False,
                            error="Rate limited"
                        )
                    
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
        return PumpFunResult(
            address=address,
            exists_on_pump=False,
            error="Not found on any pump.fun URL"
        )
    
    def update_token_pump_status(self, result: PumpFunResult) -> bool:
        """Mettre à jour le statut pump.fun dans la DB"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE tokens SET 
                    exists_on_pump = ?,
                    updated_at = ?
                WHERE address = ?
            ''', (
                result.exists_on_pump,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                result.address
            ))
            
            if cursor.rowcount > 0:
                conn.commit()
                return True
            else:
                logger.warning(f"Token {result.address} not found in DB")
                return False
                
        except sqlite3.Error as e:
            logger.error(f"Database error updating {result.address}: {e}")
            return False
        finally:
            conn.close()
    
    async def process_batch(self, tokens: List[Dict]) -> Dict:
        """Traiter un batch de tokens"""
        batch_stats = {
            'processed': 0,
            'found_on_pump': 0,
            'not_on_pump': 0,
            'errors': 0,
            'database_updates': 0
        }
        
        logger.info(f"🔧 Processing batch of {len(tokens)} tokens")
        
        for i, token in enumerate(tokens, 1):
            address = token['address']
            symbol = token['symbol']
            
            try:
                logger.info(f"[{i}/{len(tokens)}] 🔍 Checking: {symbol} ({address[:8]}...)")
                
                # Vérifier sur Pump.fun
                result = await self.check_pump_fun_existence(address)
                
                # Mettre à jour en DB
                if self.update_token_pump_status(result):
                    batch_stats['database_updates'] += 1
                    self.stats['database_updates'] += 1
                
                # Statistiques
                if result.exists_on_pump:
                    batch_stats['found_on_pump'] += 1
                    self.stats['exists_on_pump'] += 1
                    
                    # Garder les derniers tokens trouvés
                    self.stats['last_successful_tokens'].append({
                        'address': address,
                        'symbol': result.symbol or symbol,
                        'name': result.name,
                        'timestamp': datetime.now().strftime('%H:%M:%S')
                    })
                    
                    # Garder seulement les 10 derniers
                    self.stats['last_successful_tokens'] = self.stats['last_successful_tokens'][-10:]
                    
                    logger.info(f"✅ Found on Pump.fun: {result.symbol or symbol}")
                else:
                    batch_stats['not_on_pump'] += 1
                    self.stats['not_on_pump'] += 1
                    logger.debug(f"❌ Not on Pump.fun: {symbol}")
                
                batch_stats['processed'] += 1
                self.stats['total_processed'] += 1
                
                # Petit délai entre tokens
                if i < len(tokens):
                    await asyncio.sleep(0.3)
                
            except Exception as e:
                logger.error(f"Error processing {address}: {e}")
                batch_stats['errors'] += 1
                self.stats['api_errors'] += 1
                continue
        
        return batch_stats
    
    def log_cycle_stats(self, batch_stats: Dict, cycle_num: int):
        """Logger les statistiques du cycle"""
        runtime = time.time() - self.stats['start_time']
        
        logger.info("=" * 80)
        logger.info(f"📊 CYCLE #{cycle_num} COMPLETED")
        logger.info("=" * 80)
        logger.info(f"🔧 This cycle: {batch_stats['found_on_pump']}/{batch_stats['processed']} found on Pump.fun")
        logger.info(f"📈 Total runtime: {runtime/60:.1f} minutes")
        logger.info(f"📊 Overall stats:")
        logger.info(f"   ✅ Found on Pump.fun: {self.stats['exists_on_pump']}")
        logger.info(f"   ❌ Not on Pump.fun: {self.stats['not_on_pump']}")
        logger.info(f"   📦 Total processed: {self.stats['total_processed']}")
        logger.info(f"   💾 Database updates: {self.stats['database_updates']}")
        logger.info(f"   🔄 Cycles completed: {self.stats['cycles_completed']}")
        logger.info(f"   ❌ API errors: {self.stats['api_errors']}")
        
        # Derniers tokens trouvés
        if self.stats['last_successful_tokens']:
            logger.info(f"🎯 Last tokens found on Pump.fun:")
            for token in self.stats['last_successful_tokens'][-5:]:
                logger.info(f"   {token['timestamp']} | {token['symbol']} | {token['address'][:8]}...")
        
        logger.info("=" * 80)
    
    async def run_continuous(self, batch_size: int = 25, cycle_interval_minutes: float = 10, 
                           status_filter: str = 'no_dex_data', max_cycles: Optional[int] = None,
                           recheck_failures: bool = False, recheck_after_hours: int = 24):
        """Lancer le processus en continu avec gestion intelligente des re-tests"""
        self.is_running = True
        logger.info("🚀 Starting continuous Pump.fun checking")
        logger.info(f"📋 Config: batch_size={batch_size}, cycle_interval={cycle_interval_minutes}min, status={status_filter}")
        
        if recheck_failures:
            logger.info(f"🔄 Re-check mode: Will retry failures after {recheck_after_hours} hours")
        else:
            logger.info("🚫 One-time mode: Will not retry failures (recommended)")
        
        # Migration de la DB
        self.migrate_database()
        
        await self.start_session()
        
        try:
            cycle_num = 0
            
            while self.is_running:
                cycle_num += 1
                logger.info(f"\n🔄 Starting cycle #{cycle_num}")
                
                # Récupérer les tokens à vérifier
                tokens_to_check = self.get_tokens_to_check(
                    batch_size, 
                    status_filter, 
                    recheck_failures, 
                    recheck_after_hours
                )
                
                if not tokens_to_check:
                    logger.info("✅ No tokens to check found!")
                    
                    if not recheck_failures:
                        logger.info("💡 All tokens have been checked once. Use --recheck-failures to retry failed checks.")
                    
                    if max_cycles and cycle_num >= max_cycles:
                        break
                    
                    logger.info(f"⏰ Waiting {cycle_interval_minutes} minutes before next cycle...")
                    await asyncio.sleep(cycle_interval_minutes * 60)
                    continue
                
                logger.info(f"📋 Found {len(tokens_to_check)} tokens to check")
                
                # Log du type de tokens dans ce batch
                never_checked = len([t for t in tokens_to_check if t['exists_on_pump'] is None])
                retries = len([t for t in tokens_to_check if t['exists_on_pump'] == 0])
                
                if never_checked > 0:
                    logger.info(f"🆕 {never_checked} tokens never checked")
                if retries > 0:
                    logger.info(f"🔄 {retries} tokens being retried")
                
                # Traiter le batch
                batch_stats = await self.process_batch(tokens_to_check)
                
                # Statistiques du cycle
                self.stats['cycles_completed'] += 1
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
        """Afficher les statistiques finales"""
        runtime = time.time() - self.stats['start_time']
        
        logger.info("=" * 100)
        logger.info("🏁 PUMP.FUN CHECKER FINAL STATS")
        logger.info("=" * 100)
        logger.info(f"⏱️  Total runtime: {runtime/3600:.2f} hours")
        logger.info(f"🔄 Cycles completed: {self.stats['cycles_completed']}")
        logger.info(f"📦 Tokens processed: {self.stats['total_processed']}")
        logger.info(f"✅ Found on Pump.fun: {self.stats['exists_on_pump']}")
        logger.info(f"❌ Not on Pump.fun: {self.stats['not_on_pump']}")
        logger.info(f"💾 Database updates: {self.stats['database_updates']}")
        
        if self.stats['total_processed'] > 0:
            success_rate = (self.stats['exists_on_pump'] / self.stats['total_processed']) * 100
            logger.info(f"📈 Pump.fun presence rate: {success_rate:.1f}%")
            
            if runtime > 0:
                throughput = self.stats['total_processed'] / (runtime / 60)
                logger.info(f"⚡ Throughput: {throughput:.2f} tokens/minute")
        
        logger.info("=" * 100)
    
    async def test_specific_token(self, address: str):
        """Test spécifique pour une adresse de token donnée"""
        logger.info(f"🧪 TESTING SPECIFIC TOKEN: {address}")
        logger.info("=" * 80)
        
        await self.start_session()
        
        try:
            # Vérifier si le token existe dans la DB
            conn = sqlite3.connect(self.database_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT address, symbol, name, status, exists_on_pump, first_discovered_at
                FROM tokens 
                WHERE address = ?
            ''', (address,))
            
            db_result = cursor.fetchone()
            conn.close()
            
            if db_result:
                logger.info(f"📋 Token found in database:")
                logger.info(f"   Address: {db_result[0]}")
                logger.info(f"   Symbol: {db_result[1] or 'N/A'}")
                logger.info(f"   Name: {db_result[2] or 'N/A'}")
                logger.info(f"   Status: {db_result[3] or 'N/A'}")
                logger.info(f"   Exists on Pump: {db_result[4] if db_result[4] is not None else 'Not checked'}")
                logger.info(f"   Discovered: {db_result[5] or 'N/A'}")
            else:
                logger.info(f"❌ Token NOT found in database")
            
            logger.info(f"\n🔍 Testing Pump.fun existence...")
            
            # Tester chaque URL individuellement
            for i, url_template in enumerate(self.pump_fun_urls, 1):
                url = url_template.format(address)
                logger.info(f"\n🌐 Test {i}/{len(self.pump_fun_urls)}: {url}")
                
                try:
                    await self.rate_limiter.acquire()
                    
                    async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        logger.info(f"   Status: {resp.status}")
                        
                        if resp.status == 200:
                            try:
                                data = await resp.json()
                                logger.info(f"   Response type: {type(data)}")
                                
                                if isinstance(data, dict):
                                    # Afficher les champs principaux
                                    mint = data.get('mint') or data.get('address') or data.get('tokenAddress')
                                    symbol = data.get('symbol') or data.get('name')
                                    name = data.get('name') or data.get('description')
                                    creator = data.get('creator')
                                    market_cap = data.get('market_cap') or data.get('marketCap')
                                    
                                    logger.info(f"   📊 Response data:")
                                    logger.info(f"      Mint: {mint}")
                                    logger.info(f"      Symbol: {symbol}")
                                    logger.info(f"      Name: {name}")
                                    logger.info(f"      Creator: {creator}")
                                    logger.info(f"      Market Cap: {market_cap}")
                                    
                                    # Vérifier si c'est le bon token
                                    if mint and mint.lower() == address.lower():
                                        logger.info(f"   ✅ MATCH! Token found on Pump.fun")
                                        
                                        # Test de mise à jour de la DB
                                        result = PumpFunResult(
                                            address=address,
                                            exists_on_pump=True,
                                            symbol=symbol,
                                            name=name
                                        )
                                        
                                        if self.update_token_pump_status(result):
                                            logger.info(f"   💾 Database updated successfully")
                                        else:
                                            logger.info(f"   ❌ Database update failed")
                                        
                                        logger.info(f"\n🎯 FINAL RESULT: TOKEN EXISTS ON PUMP.FUN")
                                        logger.info(f"   Symbol: {symbol}")
                                        logger.info(f"   Name: {name}")
                                        logger.info(f"   URL: https://pump.fun/coin/{address}")
                                        return
                                    else:
                                        logger.info(f"   ❌ Mint address doesn't match ({mint} != {address})")
                                else:
                                    logger.info(f"   ❌ Unexpected response format: {str(data)[:200]}...")
                                    
                            except Exception as json_error:
                                logger.info(f"   ❌ JSON parse error: {json_error}")
                                text = await resp.text()
                                logger.info(f"   Raw response: {text[:300]}...")
                        
                        elif resp.status == 404:
                            logger.info(f"   ❌ Not found (404)")
                        elif resp.status == 429:
                            logger.info(f"   🚨 Rate limited (429)")
                            await self.rate_limiter.handle_429()
                        else:
                            logger.info(f"   ❌ HTTP error {resp.status}")
                            text = await resp.text()
                            logger.info(f"   Response: {text[:200]}...")
                            
                except asyncio.TimeoutError:
                    logger.info(f"   ⏱️ Timeout after 15 seconds")
                except Exception as e:
                    logger.info(f"   ❌ Request error: {e}")
            
            # Si aucune URL n'a trouvé le token
            logger.info(f"\n❌ FINAL RESULT: TOKEN NOT FOUND ON PUMP.FUN")
            
            # Mettre à jour la DB avec not found
            result = PumpFunResult(
                address=address,
                exists_on_pump=False,
                error="Not found on any Pump.fun URL"
            )
            
            if self.update_token_pump_status(result):
                logger.info(f"💾 Database updated: exists_on_pump = FALSE")
            
        finally:
            await self.close_session()
        
        logger.info("=" * 80)

    def stop(self):
        """Arrêter le processus"""
        self.is_running = False
        logger.info("🛑 Stop requested")

def main():
    """Fonction principale"""
    parser = argparse.ArgumentParser(description="🎯 Pump.fun Existence Checker")
    
    parser.add_argument("--database", default="tokens.db", help="Database path")
    parser.add_argument("--batch-size", type=int, default=25, help="Tokens per batch (default: 25)")
    parser.add_argument("--cycle-interval", type=float, default=10, help="Minutes between cycles (default: 10)")
    parser.add_argument("--status-filter", default="no_dex_data", help="Status filter (default: no_dex_data)")
    parser.add_argument("--max-cycles", type=int, help="Maximum number of cycles to run")
    parser.add_argument("--single-cycle", action="store_true", help="Run only one cycle")
    parser.add_argument("--test-token", type=str, help="Test a specific token address")
    parser.add_argument("--recheck-failures", action="store_true", 
                       help="Re-check tokens that previously failed (after --recheck-after-hours)")
    parser.add_argument("--recheck-after-hours", type=int, default=24,
                       help="Hours to wait before rechecking failed tokens (default: 24)")
    parser.add_argument("--log-level", choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], 
                       default='INFO', help="Logging level")
    
    args = parser.parse_args()
    
    # Configuration du logging
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    
    # Créer le checker
    checker = PumpFunChecker(args.database)
    
    try:
        if args.test_token:
            # Mode test spécifique
            asyncio.run(checker.test_specific_token(args.test_token))
        elif args.single_cycle:
            # Mode single cycle
            async def single_run():
                checker.migrate_database()
                await checker.start_session()
                
                tokens = checker.get_tokens_to_check(
                    args.batch_size, 
                    args.status_filter, 
                    args.recheck_failures, 
                    args.recheck_after_hours
                )
                if tokens:
                    batch_stats = await checker.process_batch(tokens)
                    checker.log_cycle_stats(batch_stats, 1)
                else:
                    logger.info("✅ No tokens to check found")
                
                await checker.close_session()
            
            asyncio.run(single_run())
        else:
            # Mode continu
            asyncio.run(checker.run_continuous(
                batch_size=args.batch_size,
                cycle_interval_minutes=args.cycle_interval,
                status_filter=args.status_filter,
                max_cycles=args.max_cycles,
                recheck_failures=args.recheck_failures,
                recheck_after_hours=args.recheck_after_hours
            ))
            
    except KeyboardInterrupt:
        logger.info("\n🛑 Interrupted by user")
        checker.stop()
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")

if __name__ == "__main__":
    main()