#!/usr/bin/env python3
"""
Jupiter Token Database Scanner
Scanne, enrichit et stocke les tokens dans SQLite pour analyse trading

Usage: python jupiter_db_scanner.py --interval 10 --limit 15 --database tokens.db
"""

import requests
import sqlite3
import time
import json
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
import logging

class TokenDatabaseScanner:
    """Scanner de tokens avec base de données SQLite"""
    
    TOKEN_LIST_URL = "https://token.jup.ag/all"
    QUOTE_API_URL = "https://quote-api.jup.ag/v6/quote"
    DEXSCREENER_API = "https://api.dexscreener.com/latest"
    
    def __init__(self, database_path: str = "tokens.db"):
        self.database_path = database_path
        self.setup_logging()
        self.setup_database()
        self.setup_session()
        
        # Configuration
        self.ignore_tokens = {
            'SOL', 'USDC', 'USDT', 'BTC', 'ETH', 'BONK', 'WIF', 
            'JUP', 'ORCA', 'RAY', 'SRM', 'STEP', 'COPE', 'MSOL'
        }
        
        self.hot_patterns = [
            'TRUMP', 'BIDEN', 'ELON', 'AI', 'PEPE', 'DOGE', 'SHIB', 
            'MEME', 'MOON', 'GEM', 'PUMP', 'ROCKET', 'DIAMOND', 'CHAD',
            '2024', '2025', 'NEW', 'FRESH', 'LAUNCH'
        ]
    
    def setup_logging(self):
        """Configuration du logging compatible Windows"""
        # Configuration pour éviter les erreurs d'encodage Unicode sur Windows
        import sys
        
        # Handler pour fichier avec UTF-8
        file_handler = logging.FileHandler('token_scanner.log', encoding='utf-8')
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        
        # Handler pour console compatible Windows
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        
        # Configurer le logger
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        # Éviter la duplication de logs
        self.logger.propagate = False
    
    def setup_database(self):
        """Créer la base de données SQLite"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        # Table principale des tokens
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS tokens (
            address TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            name TEXT,
            decimals INTEGER,
            logo_uri TEXT,
            price_usdc REAL,
            market_cap REAL,
            liquidity_usd REAL,
            volume_24h REAL,
            price_change_24h REAL,
            age_hours REAL,
            pair_created_at INTEGER,
            route_count INTEGER,
            dexes TEXT,
            price_impact REAL,
            quality_score INTEGER,
            has_dexscreener_data BOOLEAN DEFAULT 0,
            is_tradeable BOOLEAN DEFAULT 0,
            first_discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            discovery_source TEXT DEFAULT 'jupiter',
            tags TEXT,
            metadata TEXT
        )
        ''')
        
        # Index pour les requêtes rapides
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_symbol ON tokens(symbol)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_discovered_at ON tokens(first_discovered_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_age ON tokens(age_hours)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tradeable ON tokens(is_tradeable)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_quality ON tokens(quality_score)')
        
        # Table des scans
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS scan_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            tokens_scanned INTEGER,
            new_tokens_found INTEGER,
            existing_tokens_skipped INTEGER,
            scan_duration_seconds REAL,
            notes TEXT
        )
        ''')
        
        conn.commit()
        conn.close()
        self.logger.info("Database initialized: " + self.database_path)
    
    def setup_session(self):
        """Configuration de la session HTTP"""
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'TokenScanner/1.0',
            'Accept': 'application/json'
        })
    
    def get_jupiter_tokens(self) -> List[Dict]:
        """Récupérer tous les tokens Jupiter"""
        try:
            self.logger.info("Fetching tokens from Jupiter API...")
            response = self.session.get(self.TOKEN_LIST_URL, timeout=30)
            
            if response.status_code == 200:
                tokens = response.json()
                self.logger.info(f"Retrieved {len(tokens)} tokens from Jupiter")
                return tokens
            else:
                self.logger.error(f"Jupiter API error: {response.status_code}")
                return []
        except Exception as e:
            self.logger.error(f"Error fetching Jupiter tokens: {e}")
            return []
    
    def calculate_quality_score(self, token: Dict) -> int:
        """Calculer le score de qualité d'un token"""
        symbol = token.get('symbol', '').upper()
        name = token.get('name', '').upper()
        
        if symbol in self.ignore_tokens:
            return 0
        
        if len(symbol) < 2 or len(symbol) > 20:
            return 0
        
        # Patterns suspects
        suspicious = ['TEST', 'FAKE', 'SCAM', 'NULL', 'UNDEFINED', 'UNKNOWN']
        if any(pattern in symbol or pattern in name for pattern in suspicious):
            return 0
        
        score = 0
        
        # Patterns populaires
        for pattern in self.hot_patterns:
            if pattern in symbol or pattern in name:
                if pattern in ['TRUMP', 'ELON', 'AI', 'PEPE']:
                    score += 5  # Patterns très hot
                else:
                    score += 3
                break
        
        # Métadonnées
        if token.get('logoURI'):
            score += 2
        if token.get('decimals', 9) in [6, 8, 9]:
            score += 1
        if token.get('tags'):
            score += 1
        
        # Format du symbole
        if len(symbol) <= 6:
            score += 1
        if symbol.startswith('$'):
            score += 2
        if symbol.endswith(('INU', 'DOGE')):
            score += 2
        
        # Longueur du nom
        if 5 < len(name) < 50:
            score += 1
        
        return score
    
    def check_jupiter_price(self, token_address: str) -> Dict:
        """Vérifier le prix d'un token via Jupiter"""
        try:
            params = {
                'inputMint': token_address,
                'outputMint': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
                'amount': 1000000,  # 1 token (6 decimales)
                'slippageBps': 500
            }
            
            response = self.session.get(f"{self.QUOTE_API_URL}/quote", params=params, timeout=5)
            
            if response.status_code == 200:
                quote = response.json()
                return {
                    'has_price': True,
                    'price_usdc': int(quote.get('outAmount', 0)) / 1e6,
                    'route_count': len(quote.get('routePlan', [])),
                    'dexes': [step.get('swapInfo', {}).get('label', 'Unknown') 
                             for step in quote.get('routePlan', [])],
                    'price_impact': quote.get('priceImpactPct', 0)
                }
            
            return {'has_price': False}
            
        except Exception as e:
            return {'has_price': False, 'error': str(e)}
    
    def get_dexscreener_data(self, token_address: str) -> Dict:
        """Enrichir avec les données DexScreener"""
        try:
            # Rechercher le token sur DexScreener
            response = self.session.get(
                f"{self.DEXSCREENER_API}/dex/tokens/{token_address}",
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                pairs = data.get('pairs', [])
                
                if pairs:
                    # Prendre la première paire (plus liquide)
                    pair = pairs[0]
                    
                    # Calculer l'âge si disponible
                    age_hours = None
                    created_at = pair.get('pairCreatedAt')
                    if created_at:
                        age_hours = (time.time() * 1000 - created_at) / (1000 * 3600)
                    
                    return {
                        'has_dexscreener_data': True,
                        'price_usd': float(pair.get('priceUsd', 0)) if pair.get('priceUsd') else None,
                        'market_cap': pair.get('marketCap'),
                        'liquidity_usd': pair.get('liquidity', {}).get('usd'),
                        'volume_24h': pair.get('volume', {}).get('h24'),
                        'price_change_24h': pair.get('priceChange', {}).get('h24'),
                        'age_hours': age_hours,
                        'pair_created_at': created_at,
                        'dex_id': pair.get('dexId'),
                        'pair_address': pair.get('pairAddress')
                    }
            
            return {'has_dexscreener_data': False}
            
        except Exception as e:
            self.logger.debug(f"DexScreener error for {token_address}: {e}")
            return {'has_dexscreener_data': False}
    
    def token_exists_in_db(self, token_address: str) -> bool:
        """Vérifier si un token existe déjà en base"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT 1 FROM tokens WHERE address = ?', (token_address,))
        exists = cursor.fetchone() is not None
        
        conn.close()
        return exists
    
    def save_token_to_db(self, token_data: Dict):
        """Sauvegarder un token en base de données"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        # Préparer les données
        dexes_json = json.dumps(token_data.get('dexes', []))
        tags_json = json.dumps(token_data.get('tags', []))
        metadata_json = json.dumps({
            'jupiter_data': {
                'logoURI': token_data.get('logo_uri'),
                'extensions': token_data.get('extensions', {})
            },
            'dexscreener_data': token_data.get('dexscreener_data', {}),
            'jupiter_price_data': token_data.get('jupiter_price_data', {})
        })
        
        cursor.execute('''
        INSERT OR REPLACE INTO tokens (
            address, symbol, name, decimals, logo_uri, price_usdc, market_cap,
            liquidity_usd, volume_24h, price_change_24h, age_hours, pair_created_at,
            route_count, dexes, price_impact, quality_score, has_dexscreener_data,
            is_tradeable, last_updated_at, discovery_source, tags, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?)
        ''', (
            token_data['address'],
            token_data['symbol'],
            token_data['name'],
            token_data['decimals'],
            token_data.get('logo_uri'),
            token_data.get('price_usdc'),
            token_data.get('market_cap'),
            token_data.get('liquidity_usd'),
            token_data.get('volume_24h'),
            token_data.get('price_change_24h'),
            token_data.get('age_hours'),
            token_data.get('pair_created_at'),
            token_data.get('route_count'),
            dexes_json,
            token_data.get('price_impact'),
            token_data['quality_score'],
            token_data.get('has_dexscreener_data', False),
            token_data.get('is_tradeable', False),
            'jupiter',
            tags_json,
            metadata_json
        ))
        
        conn.commit()
        conn.close()
    
    def save_scan_history(self, scan_stats: Dict):
        """Sauvegarder l'historique des scans"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO scan_history (tokens_scanned, new_tokens_found, existing_tokens_skipped, scan_duration_seconds, notes)
        VALUES (?, ?, ?, ?, ?)
        ''', (
            scan_stats['tokens_scanned'],
            scan_stats['new_tokens_found'],
            scan_stats['existing_tokens_skipped'],
            scan_stats['scan_duration'],
            scan_stats.get('notes', '')
        ))
        
        conn.commit()
        conn.close()
    
    def display_token_info(self, token_data: Dict):
        """Afficher les informations détaillées d'un token"""
        symbol = token_data['symbol']
        name = token_data['name']
        address = token_data['address']
        
        print(f"\n🆕 NEW TOKEN DISCOVERED:")
        print(f"{'='*60}")
        print(f"Symbol: {symbol}")
        print(f"Name: {name}")
        print(f"Address: {address}")
        print(f"Decimals: {token_data['decimals']}")
        print(f"Quality Score: {token_data['quality_score']}/10")
        
        # Prix Jupiter
        if token_data.get('price_usdc'):
            print(f"Price (Jupiter): ${token_data['price_usdc']:.8f} USDC")
            print(f"Route Count: {token_data.get('route_count', 0)}")
            if token_data.get('dexes'):
                print(f"Available DEXes: {', '.join(token_data['dexes'][:3])}")
        
        # Données DexScreener
        if token_data.get('has_dexscreener_data'):
            print(f"📊 DEXSCREENER DATA:")
            if token_data.get('age_hours'):
                print(f"Age: {token_data['age_hours']:.1f} hours")
            if token_data.get('market_cap'):
                print(f"Market Cap: ${token_data['market_cap']:,.0f}")
            if token_data.get('liquidity_usd'):
                print(f"Liquidity: ${token_data['liquidity_usd']:,.0f}")
            if token_data.get('volume_24h'):
                print(f"Volume 24h: ${token_data['volume_24h']:,.0f}")
            if token_data.get('price_change_24h'):
                print(f"Price Change 24h: {token_data['price_change_24h']:+.2f}%")
        else:
            print("📊 DexScreener: No data available")
        
        # Métadonnées
        if token_data.get('logo_uri'):
            print(f"Logo: Available")
        
        print(f"Tradeable: {'Yes' if token_data.get('is_tradeable') else 'No'}")
        print(f"{'='*60}")
    
    def scan_and_process_tokens(self, limit: int = 20) -> Dict:
        """Scanner et traiter les tokens"""
        scan_start = time.time()
        
        self.logger.info(f"Starting token scan (limit: {limit})")
        
        # Récupérer les tokens Jupiter
        all_tokens = self.get_jupiter_tokens()
        if not all_tokens:
            return {'error': 'No tokens retrieved from Jupiter'}
        
        # Filtrer les candidats de qualité
        candidates = []
        for token in all_tokens:
            quality_score = self.calculate_quality_score(token)
            if quality_score >= 3:  # Seuil de qualité
                token['quality_score'] = quality_score
                candidates.append(token)
        
        # Trier par score de qualité
        candidates.sort(key=lambda x: x['quality_score'], reverse=True)
        candidates = candidates[:limit * 3]  # Prendre plus de candidats pour compenser les doublons
        
        self.logger.info(f"Found {len(candidates)} quality candidates")
        
        # Traiter les candidats
        new_tokens_count = 0
        existing_tokens_count = 0
        processed_count = 0
        
        for token in candidates[:limit]:
            if processed_count >= limit:
                break
                
            token_address = token['address']
            
            # Vérifier si le token existe déjà
            if self.token_exists_in_db(token_address):
                existing_tokens_count += 1
                print(f"⏭️ {token['symbol']} - Already in database")
                continue
            
            processed_count += 1
            # Éviter les emojis dans les logs pour compatibilité Windows
            self.logger.info(f"Processing new token: {token['symbol']} ({processed_count}/{limit})")
            print(f"🔍 Processing new token: {token['symbol']} ({processed_count}/{limit})")
            
            # Enrichir les données
            token_data = {
                'address': token_address,
                'symbol': token['symbol'],
                'name': token['name'],
                'decimals': token.get('decimals', 9),
                'logo_uri': token.get('logoURI'),
                'quality_score': token['quality_score'],
                'tags': token.get('tags', [])
            }
            
            # Vérifier le prix Jupiter
            jupiter_price = self.check_jupiter_price(token_address)
            if jupiter_price.get('has_price'):
                token_data.update({
                    'price_usdc': jupiter_price['price_usdc'],
                    'route_count': jupiter_price['route_count'],
                    'dexes': jupiter_price['dexes'],
                    'price_impact': jupiter_price['price_impact'],
                    'is_tradeable': True
                })
            
            # Enrichir avec DexScreener
            dex_data = self.get_dexscreener_data(token_address)
            token_data.update(dex_data)
            
            # Sauvegarder en base
            self.save_token_to_db(token_data)
            
            # Afficher les informations
            self.display_token_info(token_data)
            
            new_tokens_count += 1
            
            # Rate limiting
            time.sleep(0.5)
        
        scan_duration = time.time() - scan_start
        
        # Statistiques du scan
        scan_stats = {
            'tokens_scanned': processed_count + existing_tokens_count,
            'new_tokens_found': new_tokens_count,
            'existing_tokens_skipped': existing_tokens_count,
            'scan_duration': scan_duration,
            'notes': f'Quality threshold: 3+, Jupiter+DexScreener enrichment'
        }
        
        self.save_scan_history(scan_stats)
        
        return scan_stats
    
    def run_continuous_scanning(self, interval_minutes: int, limit: int):
        """Scanner en continu"""
        print("🚀 TOKEN DATABASE SCANNER")
        print("=" * 60)
        print(f"Database: {self.database_path}")
        print(f"Scan Interval: {interval_minutes} minutes")
        print(f"Tokens per scan: {limit}")
        print("=" * 60)
        print("Press Ctrl+C to stop\n")
        
        scan_count = 0
        
        try:
            while True:
                scan_count += 1
                print(f"\n🔄 SCAN #{scan_count} - {datetime.now().strftime('%H:%M:%S')}")
                print("-" * 60)
                
                # Effectuer le scan
                stats = self.scan_and_process_tokens(limit)
                
                if 'error' in stats:
                    self.logger.error(f"Scan failed: {stats['error']}")
                else:
                    print(f"\n📊 SCAN COMPLETE:")
                    print(f"   Duration: {stats['scan_duration']:.1f}s")
                    print(f"   New tokens: {stats['new_tokens_found']}")
                    print(f"   Already known: {stats['existing_tokens_skipped']}")
                    print(f"   Total processed: {stats['tokens_scanned']}")
                    
                    # Log sans emojis
                    self.logger.info(f"Scan #{scan_count} complete: {stats['new_tokens_found']} new tokens found")
                
                # Prochaine exécution
                next_scan = datetime.now() + timedelta(minutes=interval_minutes)
                print(f"⏰ Next scan at: {next_scan.strftime('%H:%M:%S')}")
                print("=" * 60)
                
                # Attendre
                time.sleep(interval_minutes * 60)
                
        except KeyboardInterrupt:
            print(f"\n🛑 Scanner stopped by user")
            print(f"📊 Total scans completed: {scan_count}")
    
    def get_database_stats(self):
        """Statistiques de la base de données"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        stats = {}
        
        # Nombre total de tokens
        cursor.execute('SELECT COUNT(*) FROM tokens')
        stats['total_tokens'] = cursor.fetchone()[0]
        
        # Tokens tradeables
        cursor.execute('SELECT COUNT(*) FROM tokens WHERE is_tradeable = 1')
        stats['tradeable_tokens'] = cursor.fetchone()[0]
        
        # Tokens avec données DexScreener
        cursor.execute('SELECT COUNT(*) FROM tokens WHERE has_dexscreener_data = 1')
        stats['tokens_with_dexscreener'] = cursor.fetchone()[0]
        
        # Token le plus récent
        cursor.execute('SELECT symbol, age_hours FROM tokens WHERE age_hours IS NOT NULL ORDER BY age_hours ASC LIMIT 1')
        newest = cursor.fetchone()
        if newest:
            stats['newest_token'] = f"{newest[0]} ({newest[1]:.1f}h)"
        
        # Nombre de scans
        cursor.execute('SELECT COUNT(*) FROM scan_history')
        stats['total_scans'] = cursor.fetchone()[0]
        
        conn.close()
        return stats

def main():
    parser = argparse.ArgumentParser(description='Jupiter Token Database Scanner')
    parser.add_argument('--interval', '-i', type=int, default=10, help='Scan interval in minutes')
    parser.add_argument('--limit', '-l', type=int, default=15, help='Tokens per scan')
    parser.add_argument('--database', '-d', default='tokens.db', help='SQLite database path')
    parser.add_argument('--stats', action='store_true', help='Show database statistics')
    parser.add_argument('--single-scan', action='store_true', help='Run single scan and exit')
    
    args = parser.parse_args()
    
    # Créer le scanner
    scanner = TokenDatabaseScanner(args.database)
    
    if args.stats:
        # Afficher les statistiques
        stats = scanner.get_database_stats()
        print("📊 DATABASE STATISTICS")
        print("=" * 40)
        for key, value in stats.items():
            print(f"{key.replace('_', ' ').title()}: {value}")
        return
    
    if args.single_scan:
        # Scan unique
        print("🔍 Running single scan...")
        stats = scanner.scan_and_process_tokens(args.limit)
        print("✅ Single scan completed")
        return
    
    # Scanner en continu
    scanner.run_continuous_scanning(args.interval, args.limit)

if __name__ == "__main__":
    main()