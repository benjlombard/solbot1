#!/usr/bin/env python3
"""
🔥 Ultra-Early Token Detection System - Version Robuste
Détecte les nouveaux tokens avec APIs alternatives
"""

import asyncio
import aiohttp
import json
import time
from datetime import datetime
import logging
import sqlite3
import os
from typing import Dict, List, Optional

# Configuration logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('ultra_detector')

class UltraEarlyDetector:
    """Système de détection ultra-précoce avec APIs alternatives"""
    
    def __init__(self):
        self.detected_tokens = set()
        self.alert_callbacks = []
        self.session = None
        
        # Tokens connus à ignorer
        self.ignore_tokens = {
            'So11111111111111111111111111111111111111112',  # SOL
            'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
            'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',  # USDT
            '4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R',  # RAY
            'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263',  # BONK
        }
        
        # Headers pour éviter les blocages
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        }
        
        # Initialiser la base de données
        self.init_database()
        
        # Sources de détection avec statut
        self.sources = {
            'dexscreener_new': True,      # API Dexscreener - très fiable
            'birdeye_new': True,          # API Birdeye - excellente
            'pump_fun_backup': True,       # Backup Pump.fun
            'raydium_pools': True,        # Pools Raydium
            'jupiter_listings': True,     # Jupiter listings
            'geckoterminal': True,        # GeckoTerminal API
        }
        
        self.api_status = {source: True for source in self.sources}
    
    def init_database(self):
        """Initialiser la base de données SQLite"""
        self.db_path = "detected_tokens.db"
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tokens (
                address TEXT PRIMARY KEY,
                symbol TEXT,
                name TEXT,
                source TEXT,
                detection_time REAL,
                early_score INTEGER,
                market_cap REAL,
                price_usd REAL,
                volume_24h REAL,
                liquidity_usd REAL,
                age_minutes REAL,
                twitter TEXT,
                telegram TEXT,
                website TEXT,
                dex TEXT,
                pair_address TEXT,
                created_timestamp REAL
            )
        ''')
        
        conn.commit()
        conn.close()
    
    async def save_to_database(self, token_data):
        """Sauvegarder en base de données"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO tokens 
                (address, symbol, name, source, detection_time, early_score, 
                 market_cap, price_usd, volume_24h, liquidity_usd, age_minutes,
                 twitter, telegram, website, dex, pair_address, created_timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                token_data.get('address'),
                token_data.get('symbol'),
                token_data.get('name'),
                token_data.get('source'),
                token_data.get('detection_time'),
                token_data.get('early_score'),
                token_data.get('market_cap'),
                token_data.get('price_usd'),
                token_data.get('volume_24h'),
                token_data.get('liquidity_usd'),
                token_data.get('age_minutes'),
                token_data.get('twitter'),
                token_data.get('telegram'),
                token_data.get('website'),
                token_data.get('dex'),
                token_data.get('pair_address'),
                token_data.get('created_timestamp')
            ))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Database save error: {e}")
    
    async def create_session(self):
        """Créer une session HTTP persistante"""
        connector = aiohttp.TCPConnector(limit=50, limit_per_host=10)
        timeout = aiohttp.ClientTimeout(total=15, connect=10)
        self.session = aiohttp.ClientSession(
            headers=self.headers,
            connector=connector,
            timeout=timeout
        )
    
    async def close_session(self):
        """Fermer la session HTTP"""
        if self.session:
            await self.session.close()
    
    async def start_monitoring(self):
        """Démarrer tous les monitors en parallèle"""
        await self.create_session()
        
        tasks = []
        
        if self.sources['dexscreener_new']:
            tasks.append(self.monitor_dexscreener_new())
        
        if self.sources['birdeye_new']:
            tasks.append(self.monitor_birdeye_new())
            
        if self.sources['geckoterminal']:
            tasks.append(self.monitor_geckoterminal())
            
        if self.sources['pump_fun_backup']:
            tasks.append(self.monitor_pump_fun_backup())
        
        if self.sources['raydium_pools']:
            tasks.append(self.monitor_raydium_pools())
            
        if self.sources['jupiter_listings']:
            tasks.append(self.monitor_jupiter_listings())
        
        logger.info("🚀 Starting Ultra-Early Token Detection System...")
        logger.info(f"📊 Active sources: {len([s for s in self.sources.values() if s])}")
        
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await self.close_session()
    
    async def monitor_dexscreener_new(self):
        """Monitor Dexscreener pour nouveaux tokens - Très fiable"""
        logger.info("🔍 Starting Dexscreener monitor...")
        
        while True:
            try:
                # API Dexscreener pour nouveaux tokens Solana
                url = "https://api.dexscreener.com/latest/dex/tokens/new/solana"
                
                async with self.session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        for pair in data.get('pairs', []):
                            base_token = pair.get('baseToken', {})
                            address = base_token.get('address')
                            
                            if address and address not in self.detected_tokens and address not in self.ignore_tokens:
                                
                                # Calculer l'âge du token
                                pair_created = pair.get('pairCreatedAt')
                                age_minutes = None
                                if pair_created:
                                    created_time = datetime.fromisoformat(pair_created.replace('Z', '+00:00'))
                                    age_minutes = (datetime.now(created_time.tzinfo) - created_time).total_seconds() / 60
                                
                                # Filtrer les tokens très récents (< 2 heures)
                                if age_minutes is None or age_minutes < 120:
                                    await self.process_new_token({
                                        'address': address,
                                        'symbol': base_token.get('symbol', 'UNKNOWN'),
                                        'name': base_token.get('name', ''),
                                        'source': 'dexscreener_new',
                                        'price_usd': float(pair.get('priceUsd', 0)),
                                        'volume_24h': float(pair.get('volume', {}).get('h24', 0)),
                                        'liquidity_usd': float(pair.get('liquidity', {}).get('usd', 0)),
                                        'market_cap': float(pair.get('fdv', 0)),
                                        'dex': pair.get('dexId'),
                                        'pair_address': pair.get('pairAddress'),
                                        'age_minutes': age_minutes,
                                        'detection_time': time.time(),
                                        'priority': 'HIGH'
                                    })
                        
                        self.api_status['dexscreener_new'] = True
                    else:
                        logger.warning(f"Dexscreener API returned status {resp.status}")
                        if resp.status >= 500:
                            self.api_status['dexscreener_new'] = False
                
                await asyncio.sleep(30)  # Check toutes les 30 secondes
                
            except Exception as e:
                logger.error(f"Dexscreener monitor error: {e}")
                self.api_status['dexscreener_new'] = False
                await asyncio.sleep(60)
    
    async def monitor_birdeye_new(self):
        """Monitor Birdeye pour nouveaux tokens"""
        logger.info("🐦 Starting Birdeye monitor...")
        
        while True:
            try:
                # API Birdeye pour tokens récents
                url = "https://public-api.birdeye.so/defi/token_creation/recent?chain=solana&limit=50"
                
                async with self.session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        for token in data.get('data', {}).get('items', []):
                            address = token.get('address')
                            
                            if address and address not in self.detected_tokens and address not in self.ignore_tokens:
                                
                                # Calculer l'âge
                                created_time = token.get('createdTime')
                                age_minutes = None
                                if created_time:
                                    age_minutes = (time.time() - created_time) / 60
                                
                                # Filtrer tokens récents (< 3 heures)
                                if age_minutes is None or age_minutes < 180:
                                    await self.process_new_token({
                                        'address': address,
                                        'symbol': token.get('symbol', 'UNKNOWN'),
                                        'name': token.get('name', ''),
                                        'source': 'birdeye_new',
                                        'market_cap': token.get('mc'),
                                        'liquidity_usd': token.get('liquidity'),
                                        'age_minutes': age_minutes,
                                        'created_timestamp': created_time,
                                        'detection_time': time.time(),
                                        'priority': 'HIGH'
                                    })
                        
                        self.api_status['birdeye_new'] = True
                    else:
                        logger.warning(f"Birdeye API returned status {resp.status}")
                        if resp.status >= 500:
                            self.api_status['birdeye_new'] = False
                
                await asyncio.sleep(45)  # Check toutes les 45 secondes
                
            except Exception as e:
                logger.error(f"Birdeye monitor error: {e}")
                self.api_status['birdeye_new'] = False
                await asyncio.sleep(90)
    
    async def monitor_geckoterminal(self):
        """Monitor GeckoTerminal pour nouveaux pools"""
        logger.info("🦎 Starting GeckoTerminal monitor...")
        
        while True:
            try:
                # API GeckoTerminal pour nouveaux pools Solana
                url = "https://api.geckoterminal.com/api/v2/networks/solana/new_pools?page=1"
                
                async with self.session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        for pool in data.get('data', []):
                            attributes = pool.get('attributes', {})
                            base_token = attributes.get('base_token', {})
                            address = base_token.get('address')
                            
                            if address and address not in self.detected_tokens and address not in self.ignore_tokens:
                                
                                # Calculer l'âge du pool
                                pool_created = attributes.get('pool_created_at')
                                age_minutes = None
                                if pool_created:
                                    created_time = datetime.fromisoformat(pool_created)
                                    age_minutes = (datetime.now(created_time.tzinfo) - created_time).total_seconds() / 60
                                
                                # Filtrer pools récents (< 1 heure)
                                if age_minutes is None or age_minutes < 60:
                                    await self.process_new_token({
                                        'address': address,
                                        'symbol': base_token.get('symbol', 'UNKNOWN'),
                                        'name': base_token.get('name', ''),
                                        'source': 'geckoterminal',
                                        'price_usd': float(attributes.get('base_token_price_usd', 0)),
                                        'volume_24h': float(attributes.get('volume_usd', {}).get('h24', 0)),
                                        'market_cap': float(attributes.get('market_cap_usd', 0)),
                                        'liquidity_usd': float(attributes.get('reserve_in_usd', 0)),
                                        'age_minutes': age_minutes,
                                        'dex': attributes.get('dex_id'),
                                        'pair_address': pool.get('id'),
                                        'detection_time': time.time(),
                                        'priority': 'MEDIUM'
                                    })
                        
                        self.api_status['geckoterminal'] = True
                    else:
                        logger.warning(f"GeckoTerminal API returned status {resp.status}")
                        if resp.status >= 500:
                            self.api_status['geckoterminal'] = False
                
                await asyncio.sleep(60)  # Check toutes les minutes
                
            except Exception as e:
                logger.error(f"GeckoTerminal monitor error: {e}")
                self.api_status['geckoterminal'] = False
                await asyncio.sleep(120)
    
    async def monitor_pump_fun_backup(self):
        """Monitor Pump.fun avec API alternative"""
        logger.info("💊 Starting Pump.fun backup monitor...")
        
        while True:
            try:
                # Essayer plusieurs endpoints
                endpoints = [
                    "https://pump-fun-api.vercel.app/api/coins/recently-created",
                    "https://pumpfun-api.dexlab.space/recently-created",
                ]
                
                for endpoint in endpoints:
                    try:
                        async with self.session.get(endpoint) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                
                                coins = data if isinstance(data, list) else data.get('coins', [])
                                
                                for coin in coins[:20]:  # Limiter à 20 pour éviter le spam
                                    mint = coin.get('mint') or coin.get('address')
                                    if mint and mint not in self.detected_tokens and mint not in self.ignore_tokens:
                                        
                                        created_timestamp = coin.get('created_timestamp')
                                        age_minutes = None
                                        if created_timestamp:
                                            age_minutes = (time.time() - created_timestamp) / 60
                                        
                                        # Filtrer tokens très récents (< 30 minutes)
                                        if age_minutes is None or age_minutes < 30:
                                            await self.process_new_token({
                                                'address': mint,
                                                'symbol': coin.get('symbol', 'UNKNOWN'),
                                                'name': coin.get('name', ''),
                                                'source': 'pump_fun_backup',
                                                'market_cap': coin.get('usd_market_cap', 0),
                                                'created_timestamp': created_timestamp,
                                                'twitter': coin.get('twitter'),
                                                'telegram': coin.get('telegram'),
                                                'website': coin.get('website'),
                                                'age_minutes': age_minutes,
                                                'detection_time': time.time(),
                                                'priority': 'ULTRA_HIGH'
                                            })
                                
                                self.api_status['pump_fun_backup'] = True
                                break  # Succès, sortir de la boucle
                                
                    except Exception:
                        continue  # Essayer l'endpoint suivant
                
                await asyncio.sleep(20)  # Check toutes les 20 secondes
                
            except Exception as e:
                logger.error(f"Pump.fun backup monitor error: {e}")
                self.api_status['pump_fun_backup'] = False
                await asyncio.sleep(60)
    
    async def monitor_raydium_pools(self):
        """Monitor pools Raydium simplifiés"""
        logger.info("🏊 Starting Raydium pools monitor...")
        
        while True:
            try:
                # API plus simple et fiable
                url = "https://api.raydium.io/v2/main/info"
                
                async with self.session.get(url) as resp:
                    if resp.status == 200:
                        # Pour l'instant, on log juste que l'API fonctionne
                        # L'implémentation complète nécessite plus d'analyse de l'API
                        self.api_status['raydium_pools'] = True
                    else:
                        self.api_status['raydium_pools'] = False
                
                await asyncio.sleep(120)  # Check toutes les 2 minutes
                
            except Exception as e:
                logger.error(f"Raydium monitor error: {e}")
                self.api_status['raydium_pools'] = False
                await asyncio.sleep(180)
    
    async def monitor_jupiter_listings(self):
        """Monitor Jupiter listings avec logique améliorée"""
        logger.info("🪐 Starting Jupiter listings monitor...")
        
        known_tokens = set()
        
        while True:
            try:
                async with self.session.get("https://token.jup.ag/all") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        current_tokens = {token['address'] for token in data if token.get('address')}
                        new_tokens = current_tokens - known_tokens - self.ignore_tokens
                        
                        # Éviter le spam au premier run
                        if new_tokens and known_tokens:
                            logger.info(f"🆕 Found {len(new_tokens)} new Jupiter listings")
                            
                            for token in data:
                                address = token.get('address')
                                if address in new_tokens and address not in self.detected_tokens:
                                    await self.process_new_token({
                                        'address': address,
                                        'symbol': token.get('symbol'),
                                        'name': token.get('name'),
                                        'source': 'jupiter_listing',
                                        'detection_time': time.time(),
                                        'priority': 'LOW'  # Jupiter listings sont moins prioritaires
                                    })
                        
                        known_tokens = current_tokens
                        self.api_status['jupiter_listings'] = True
                    else:
                        self.api_status['jupiter_listings'] = False
                
                await asyncio.sleep(120)  # Check toutes les 2 minutes
                
            except Exception as e:
                logger.error(f"Jupiter monitor error: {e}")
                self.api_status['jupiter_listings'] = False
                await asyncio.sleep(180)
    
    async def process_new_token(self, token_data):
        """Traiter un nouveau token détecté"""
        address = token_data['address']
        
        if address in self.detected_tokens or address in self.ignore_tokens:
            return
        
        self.detected_tokens.add(address)
        
        # Calculer le score
        score = self.calculate_early_score(token_data)
        token_data['early_score'] = score
        
        # Alerte si score élevé
        if score >= 60:  # Seuil abaissé pour plus d'alertes
            await self.send_alerts(token_data)
        
        # Sauvegarder en base
        await self.save_to_database(token_data)
        
        # Log avec plus d'infos
        age_str = f"{token_data.get('age_minutes', 0):.1f}min" if token_data.get('age_minutes') else "Unknown"
        logger.info(f"🔥 NEW TOKEN: {token_data.get('symbol', 'UNKNOWN')} | Score: {score} | Age: {age_str} | Source: {token_data['source']}")
    
    def calculate_early_score(self, token_data):
        """Score amélioré pour early detection"""
        score = 0
        
        # Âge du token (plus jeune = mieux)
        age_minutes = token_data.get('age_minutes')
        if age_minutes is not None:
            if age_minutes < 5:      # < 5 minutes
                score += 60
            elif age_minutes < 15:   # < 15 minutes
                score += 45
            elif age_minutes < 60:   # < 1 heure
                score += 30
            elif age_minutes < 180:  # < 3 heures
                score += 15
        
        # Source priority
        source_scores = {
            'pump_fun_backup': 25,
            'dexscreener_new': 20,
            'birdeye_new': 20,
            'geckoterminal': 15,
            'jupiter_listing': 5,
            'raydium_pools': 15
        }
        score += source_scores.get(token_data.get('source'), 5)
        
        # Liquidité (sweet spot pour early tokens)
        liquidity = token_data.get('liquidity_usd', 0)
        if 5000 <= liquidity <= 100000:
            score += 15
        elif 1000 <= liquidity < 5000:
            score += 10
        
        # Volume 24h
        volume = token_data.get('volume_24h', 0)
        if volume > 10000:
            score += 10
        elif volume > 1000:
            score += 5
        
        # Market cap (éviter les trop gros)
        market_cap = token_data.get('market_cap', 0)
        if 10000 <= market_cap <= 500000:
            score += 15
        elif 500000 <= market_cap <= 2000000:
            score += 5
        
        # Social présence
        if token_data.get('twitter'):
            score += 10
        if token_data.get('telegram'):
            score += 8
        if token_data.get('website'):
            score += 5
        
        return min(score, 100)
    
    async def send_alerts(self, token_data):
        """Envoyer alertes pour tokens high-score"""
        for callback in self.alert_callbacks:
            try:
                await callback(token_data)
            except Exception as e:
                logger.error(f"Alert callback error: {e}")
    
    def add_alert_callback(self, callback):
        """Ajouter un callback d'alerte"""
        self.alert_callbacks.append(callback)
    
    def get_status(self):
        """Obtenir le statut des APIs"""
        return self.api_status

# Exemple d'utilisation
async def main():
    detector = UltraEarlyDetector()
    
    # Callback d'alerte détaillé
    async def alert_callback(token):
        print(f"\n🚨 HIGH POTENTIAL TOKEN DETECTED!")
        print(f"   Symbol: {token.get('symbol', 'UNKNOWN')}")
        print(f"   Address: {token['address']}")
        print(f"   Score: {token['early_score']}/100")
        print(f"   Source: {token['source']}")
        print(f"   Age: {token.get('age_minutes', 0):.1f} minutes")
        
        if token.get('price_usd'):
            print(f"   Price: ${token['price_usd']:.8f}")
        if token.get('market_cap'):
            print(f"   Market Cap: ${token['market_cap']:,.0f}")
        if token.get('liquidity_usd'):
            print(f"   Liquidity: ${token['liquidity_usd']:,.0f}")
        if token.get('volume_24h'):
            print(f"   Volume 24h: ${token['volume_24h']:,.0f}")
        if token.get('dex'):
            print(f"   DEX: {token['dex']}")
        
        # Links sociaux
        socials = []
        if token.get('twitter'):
            socials.append(f"Twitter: {token['twitter']}")
        if token.get('telegram'):
            socials.append(f"Telegram: {token['telegram']}")
        if token.get('website'):
            socials.append(f"Website: {token['website']}")
        
        if socials:
            print(f"   Socials: {' | '.join(socials)}")
        
        print("=" * 80)
    
    detector.add_alert_callback(alert_callback)
    
    # Status callback périodique
    async def status_monitor():
        while True:
            await asyncio.sleep(300)  # Toutes les 5 minutes
            status = detector.get_status()
            active_sources = sum(status.values())
            total_sources = len(status)
            logger.info(f"📊 API Status: {active_sources}/{total_sources} active | Detected: {len(detector.detected_tokens)} tokens")
    
    try:
        # Démarrer le monitoring et le status en parallèle
        await asyncio.gather(
            detector.start_monitoring(),
            status_monitor()
        )
    except KeyboardInterrupt:
        logger.info("🛑 Detection stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")

if __name__ == "__main__":
    asyncio.run(main())