#!/usr/bin/env python3
"""
Jupiter Token Database Scanner - Version Corrigée
Scanne, enrichit et stocke les tokens dans SQLite pour analyse trading

Usage: python jupiter_db_scanner.py --interval 10 --limit 15 --database tokens.db
"""
import numpy as np
import requests
import sqlite3
import time
import json
import argparse
import random
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
import logging


class TokenDatabaseScanner:
    """Scanner de tokens avec base de données SQLite"""
    
    TOKEN_LIST_URL = "https://token.jup.ag/all"
    QUOTE_API_URL = "https://quote-api.jup.ag/v6"
    DEXSCREENER_API = "https://api.dexscreener.com/latest"
    
    def __init__(self, database_path: str = "tokens.db"):
        self.database_path = database_path
        self.setup_logging()
        self.setup_database()
        self.migrate_database()
        self.setup_session()
        
        self.SOURCE_PRIORITY = [
            'dexscreener', 'birdeye', 'raydium', 'orca', 
            'coingecko', 'geckoterminal', 'solscan'
        ]

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
        
        # Cache pour éviter de rescanner les mêmes tokens trop souvent
        self.recently_scanned = set()
        self.last_full_refresh = 0
    
    def setup_logging(self):
        """Configuration du logging compatible Windows"""
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
            quality_score REAL,
            has_dexscreener_data BOOLEAN DEFAULT 0,
            is_tradeable BOOLEAN DEFAULT 0,
            first_discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            discovery_source TEXT DEFAULT 'jupiter',
            tags TEXT,
            metadata TEXT,
            tx_count_24h INTEGER,
            has_verified_contract BOOLEAN DEFAULT 0,
            has_rug_check BOOLEAN DEFAULT 0,
            rug_score REAL,
            issues TEXT
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
    
    def get_alternative_token_data(self, token_address: str) -> Dict:
        """Services alternatifs si DexScreener échoue"""
        # Liste des sources à essayer dans l'ordre
        sources = [
            ('raydium', self.get_raydium_data),
            ('orca', self.get_orca_data),
            ('coingecko', self.get_coingecko_data),
            ('geckoterminal', self.get_geckoterminal_data),
            ('solscan', self.get_solscan_data),
            ('birdeye', self.get_birdeye_data),
            ('jupiter_stats', self.get_jupiter_stats_data),
            ('helius', self.get_helius_data)
        ]

        combined_data = {'has_alternative_data': False, 'sources_tried': []}

        for source_name, source_func in sources:
            try:
                data = source_func(token_address)
                combined_data['sources_tried'].append(source_name)
                
                if data.get(f'has_{source_name}_data', False):
                    combined_data.update(data)
                    combined_data['has_alternative_data'] = True
                    combined_data['primary_source'] = source_name
                    
                    self.logger.debug(f"Got data from {source_name} for {token_address}")
                    break
                    
            except Exception as e:
                self.logger.debug(f"Error with {source_name} for {token_address}: {e}")
                continue
        
        # Si aucune source principale n'a fonctionné, essayer de combiner les données partielles
        if not combined_data['has_alternative_data']:
            partial_data = {}
            
            for source_name, source_func in sources[:3]:
                try:
                    data = source_func(token_address)
                    for key in ['price_usd', 'market_cap', 'volume_24h', 'holders_count']:
                        if data.get(key):
                            partial_data[key] = data[key]
                            
                except:
                    continue
            
            if partial_data:
                combined_data.update(partial_data)
                combined_data['has_alternative_data'] = True
                combined_data['primary_source'] = 'combined_partial'
        
        return combined_data

    def calculate_quality_score(self, token_data: Dict) -> float:
        """
        Calculer un score de qualité pour un token basé sur plusieurs métriques.
        Score final entre 0 et 100.
        """
        score_components = {
            'liquidity': 0.0,
            'volume': 0.0,
            'age': 0.0,
            'volatility': 0.0,
            'risk': 0.0,
            'activity': 0.0,
            'technical': 0.0
        }
        
        # Poids des composants (somme = 1)
        weights = {
            'liquidity': 0.25,
            'volume': 0.20,
            'age': 0.15,
            'volatility': 0.10,
            'risk': 0.15,
            'activity': 0.10,
            'technical': 0.05
        }
        
        def safe_float(value, default=0):
            """Convertir en float de manière sécurisée"""
            if value is None:
                return default
            try:
                return float(value)
            except (ValueError, TypeError):
                return default

        # 1. Liquidité
        liquidity_usd = safe_float(token_data.get('liquidity_usd'))
        if liquidity_usd:
            score_components['liquidity'] = min(liquidity_usd / 100000, 1.0)
            if liquidity_usd < 5000:
                score_components['liquidity'] *= 0.5
        
        # 2. Volume
        volume_24h = safe_float(token_data.get('volume_24h'))
        market_cap = safe_float(token_data.get('market_cap'), 1) 
        if volume_24h and market_cap:
            volume_ratio = volume_24h / market_cap
            score_components['volume'] = min(volume_ratio / 5, 1.0)
            if volume_ratio > 10:
                score_components['volume'] *= 0.7
        
        # 3. Âge
        age_hours = safe_float(token_data.get('age_hours'))
        if age_hours != float('inf') and age_hours > 0:
            if 1 <= age_hours <= 24:
                score_components['age'] = 1.0
            elif age_hours < 1:
                score_components['age'] = 0.5
            else:
                score_components['age'] = max(0, 1 - (age_hours - 24) / 168)
        
        # 4. Volatilité
        price_change_24h = safe_float(token_data.get('price_change_24h'))
        if price_change_24h != 0:
            price_change_24h = abs(price_change_24h)
            score_components['volatility'] = max(0, 1 - price_change_24h / 50)
        else:
            score_components['volatility'] = 0.5
        
        # 5. Risque
        if token_data.get('has_rug_check', False):
            rug_score = safe_float(token_data.get('rug_score'), 50)
            score_components['risk'] = max(0, (100 - rug_score) / 100)
        else:
            score_components['risk'] = 1.0
            if liquidity_usd < 10000 or (volume_24h > 0 and market_cap > 0 and volume_24h / market_cap > 10):
                score_components['risk'] = 0.5
        
        # 6. Activité
        route_count = safe_float(token_data.get('route_count'))
        score_components['activity'] = min(route_count / 5, 1.0)
        
        # 7. Aspects techniques
        technical_points = sum([
            1 if token_data.get('logo_uri') else 0,
            1 if token_data.get('tags') else 0,
            1 if token_data.get('is_tradeable', False) else 0
        ])
        score_components['technical'] = technical_points / 3
        
        # Calcul du score final
        final_score = sum(score_components[key] * weights[key] for key in score_components) * 100
        final_score = round(final_score, 2)
        
        # Stocker les sous-scores
        for key, value in score_components.items():
            token_data[f'{key}_score'] = round(value, 2)

        self.logger.debug(f"Score for {token_data.get('symbol', 'Unknown')}: {final_score}")
        
        return final_score
    
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
    
    def get_orca_data(self, token_address: str) -> Dict:
        """Récupérer les données depuis Orca"""
        try:
            response = self.session.get(
                f"https://api.orca.so/allPools?include=all",
                timeout=5
            )
            if response.status_code == 200:
                pools = response.json().get('pools', [])
                for pool in pools:
                    if token_address in [pool.get('tokenA', {}).get('mint', ''), 
                                       pool.get('tokenB', {}).get('mint', '')]:
                        return {
                            'has_orca_data': True,
                            'liquidity_usd': pool.get('liquidity'),
                            'volume_24h': pool.get('volume24h'),
                            'fee_24h': pool.get('fee24h')
                        }
            return {'has_orca_data': False}
        except Exception as e:
            self.logger.debug(f"Orca error: {e}")
            return {'has_orca_data': False}

    def get_raydium_data(self, token_address: str) -> Dict:
        """Récupérer les données depuis Raydium"""
        try:
            response = self.session.get(
                f"https://api.raydium.io/v2/main/token/{token_address}",
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                return {
                    'has_raydium_data': True,
                    'price_usd': data.get('price'),
                    'liquidity_usd': data.get('liquidity'),
                    'volume_24h': data.get('volume24h'),
                    'pair_address': data.get('pair_address')
                }
            return {'has_raydium_data': False}
        except Exception as e:
            self.logger.debug(f"Raydium error: {e}")
            return {'has_raydium_data': False}

    def get_coingecko_data(self, token_address: str) -> Dict:
        """Récupérer les données depuis CoinGecko"""
        try:
            response = self.session.get(
                f"https://api.coingecko.com/api/v3/coins/solana/contract/{token_address}",
                timeout=8
            )
            
            if response.status_code == 200:
                data = response.json()
                market_data = data.get('market_data', {})
                
                return {
                    'has_coingecko_data': True,
                    'source': 'coingecko',
                    'price_usd': market_data.get('current_price', {}).get('usd'),
                    'market_cap': market_data.get('market_cap', {}).get('usd'),
                    'volume_24h': market_data.get('total_volume', {}).get('usd'),
                    'price_change_24h': market_data.get('price_change_percentage_24h'),
                    'ath': market_data.get('ath', {}).get('usd'),
                    'ath_date': market_data.get('ath_date', {}).get('usd'),
                    'description': data.get('description', {}).get('en', '')[:200]
                }
            
            return {'has_coingecko_data': False}
            
        except Exception as e:
            self.logger.debug(f"CoinGecko error for {token_address}: {e}")
            return {'has_coingecko_data': False}

    def get_geckoterminal_data(self, token_address: str) -> Dict:
        """Récupérer les données depuis GeckoTerminal"""
        try:
            response = self.session.get(
                f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{token_address}",
                timeout=8
            )
            
            if response.status_code == 200:
                data = response.json()
                token_data = data.get('data', {}).get('attributes', {})
                
                return {
                    'has_geckoterminal_data': True,
                    'source': 'geckoterminal',
                    'price_usd': token_data.get('price_usd'),
                    'fdv_usd': token_data.get('fdv_usd'),
                    'market_cap_usd': token_data.get('market_cap_usd'),
                    'total_supply': token_data.get('total_supply'),
                    'volume_usd_24h': token_data.get('volume_usd', {}).get('h24')
                }
            
            return {'has_geckoterminal_data': False}
            
        except Exception as e:
            self.logger.debug(f"GeckoTerminal error for {token_address}: {e}")
            return {'has_geckoterminal_data': False}

    def get_helius_data(self, token_address: str) -> Dict:
        """Récupérer les données depuis Helius (nécessite une clé API)"""
        try:
            # NOTE: Remplacez  par votre vraie clé
            api_key = ""
            if api_key == "":
                return {'has_helius_data': False}
                
            payload = {
                "jsonrpc": "2.0",
                "id": "my-id",
                "method": "getAsset",
                "params": {
                    "id": token_address
                }
            }
            
            response = self.session.post(
                f"https://rpc.helius.xyz/?api-key={api_key}",
                json=payload,
                timeout=8
            )
            
            if response.status_code == 200:
                data = response.json()
                result = data.get('result', {})
                
                return {
                    'has_helius_data': True,
                    'source': 'helius',
                    'ownership': result.get('ownership', {}),
                    'royalty': result.get('royalty', {}),
                    'creators': result.get('creators', []),
                    'compression': result.get('compression', {}),
                    'grouping': result.get('grouping', [])
                }
            
            return {'has_helius_data': False}
            
        except Exception as e:
            self.logger.debug(f"Helius error for {token_address}: {e}")
            return {'has_helius_data': False}

    def get_solscan_data(self, token_address: str) -> Dict:
        """Récupérer les données depuis Solscan"""
        try:
            response = self.session.get(
                f"https://public-api.solscan.io/token/meta?tokenAddress={token_address}",
                timeout=8
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Holders info
                holders_count = 0
                try:
                    holders_response = self.session.get(
                        f"https://public-api.solscan.io/token/holders?tokenAddress={token_address}&limit=1",
                        timeout=5
                    )
                    
                    if holders_response.status_code == 200:
                        holders_data = holders_response.json()
                        holders_count = holders_data.get('total', 0)
                except:
                    pass
                
                return {
                    'has_solscan_data': True,
                    'source': 'solscan',
                    'supply': data.get('supply'),
                    'decimals': data.get('decimals'),
                    'holders_count': holders_count,
                    'icon': data.get('icon'),
                    'website': data.get('website'),
                    'twitter': data.get('twitter')
                }
            
            return {'has_solscan_data': False}
            
        except Exception as e:
            self.logger.debug(f"Solscan error for {token_address}: {e}")
            return {'has_solscan_data': False}

    def get_dexscreener_data(self, token_address: str) -> Dict:
        """Enrichir avec les données DexScreener"""
        try:
            response = self.session.get(
                f"{self.DEXSCREENER_API}/dex/tokens/{token_address}",
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                pairs = data.get('pairs', [])
                
                if pairs:
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
    
    def get_token_info_from_db(self, token_address: str) -> Optional[Dict]:
        """Récupérer les infos d'un token depuis la base"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT address, symbol, name, age_hours, first_discovered_at, quality_score 
        FROM tokens WHERE address = ?
        ''', (token_address,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                'address': result[0],
                'symbol': result[1], 
                'name': result[2],
                'age_hours': result[3],
                'first_discovered_at': result[4],
                'quality_score': result[5]
            }
        return None
    
    def token_exists_in_db(self, token_address: str) -> bool:
        """Vérifier si un token existe déjà en base"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT 1 FROM tokens WHERE address = ?', (token_address,))
        exists = cursor.fetchone() is not None
        
        conn.close()
        return exists

    def is_wrapped_token(self, token_data: Dict) -> bool:
        """Détecte si c'est un wrapped token"""
        name = token_data.get('name', '').lower()
        symbol = token_data.get('symbol', '').lower()
        return (
            name.startswith(('wrapped ', 'wrapped-')) or 
            symbol.startswith(('w', 'wrapped')) or
            'wrapped' in name or
            'wrapped' in symbol
        )

    def get_token_data_with_priority(self, token_address: str) -> Dict:
        """Récupérer les données avec priorité des sources"""
        self.logger.debug(f"Fetching data for {token_address} with priority")
        
        for source in self.SOURCE_PRIORITY:
            try:
                method = getattr(self, f'get_{source}_data', None)
                if not method:
                    self.logger.warning(f"Method get_{source}_data not found")
                    continue
                    
                data = method(token_address)
                if data and isinstance(data, dict) and data.get(f'has_{source}_data'):
                    return data
            except Exception as e:
                self.logger.debug(f"Error getting data from {source}: {str(e)}")
                continue
    
        return {'has_data': False}

    def get_onchain_data(self, token_address: str) -> Dict:
        """Récupère les données directement de la blockchain (simplifié)"""
        try:
            # Simulation d'un appel blockchain - à implémenter avec solana-py
            return {
                'has_onchain_data': True,
                'exists': True
            }
        except Exception as e:
            return {'has_onchain_data': False}

    def get_underlying_token(self, wrapped_address: str) -> Optional[str]:
        """Trouve le token original pour les wrapped tokens (simplifié)"""
        try:
            # Logique simplifiée - à améliorer selon vos besoins
            return None
        except Exception:
            return None

    def enrich_token_data(self, token_address: str, base_data: Dict) -> Dict:
        """Enrichir un token avec toutes les données en une fois"""
        
        # 1. Initialisation des données
        token_data = base_data.copy()
        
        # 2. Vérification Jupiter
        try:
            jupiter_data = self.check_jupiter_price(token_address)
            if jupiter_data and isinstance(jupiter_data, dict):
                token_data.update(jupiter_data)
                token_data['is_tradeable'] = jupiter_data.get('has_price', False)
        except Exception as e:
            self.logger.error(f"Jupiter price check failed: {e}")
            token_data['is_tradeable'] = False

        # 3. Essayer DexScreener en premier
        try:
            dex_data = self.get_dexscreener_data(token_address)
            if dex_data and dex_data.get('has_dexscreener_data'):
                token_data.update(dex_data)
        except Exception as e:
            self.logger.error(f"DexScreener failed: {e}")
            dex_data = {'has_dexscreener_data': False}

        # 4. Fallback sur d'autres sources si nécessaire
        if not dex_data.get('has_dexscreener_data'):
            try:
                # 4a. Vérifier si c'est un wrapped token
                if self.is_wrapped_token(token_data):
                    underlying = self.get_underlying_token(token_address)
                    if underlying:
                        underlying_data = self.get_dexscreener_data(underlying)
                        if underlying_data.get('has_dexscreener_data'):
                            token_data.update({
                                'is_wrapped': True,
                                'underlying_token': underlying,
                                'wrapped_price': underlying_data.get('price_usd'),
                                'has_alternative_data': True,
                                'primary_source': 'wrapped_token'
                            })

                # 4b. Essayer les autres sources
                if not token_data.get('has_alternative_data'):
                    alt_data = self.get_token_data_with_priority(token_address)
                    if alt_data and isinstance(alt_data, dict) and alt_data.get('has_data') != False:
                        token_data.update(alt_data)

                # 4c. Dernier recours: vérification on-chain
                if not token_data.get('has_alternative_data'):
                    onchain_data = self.get_onchain_data(token_address)
                    if onchain_data:
                        token_data.update(onchain_data)

            except Exception as e:
                self.logger.error(f"Alternative data collection failed: {e}")

        # Si aucune donnée de marché n'est trouvée mais que Jupiter fonctionne,
        # utiliser Jupiter comme source minimale
        if (not token_data.get('has_dexscreener_data') and 
            not token_data.get('has_alternative_data') and 
            token_data.get('is_tradeable')):
            
            token_data['has_jupiter_basic_data'] = True
            token_data['primary_source'] = 'jupiter_basic'
            
            # Essayer d'estimer certaines métriques basiques
            if token_data.get('price_usdc') and token_data.get('route_count', 0) > 0:
                # Token très récent ou très petit, utiliser des estimations
                token_data['estimated_liquidity'] = True
                self.logger.info(f"Using Jupiter-only data for {token_data['symbol']} - very new/small token")

        # 5. Vérification RugCheck
        try:
            rug_data = self.check_rug_pull_risk(token_address)
            if rug_data:
                token_data.update(rug_data)
        except Exception as e:
            self.logger.debug(f"RugCheck failed: {e}")

        # 6. Calcul du score avec gestion des erreurs
        try:
            token_data['quality_score'] = self.calculate_quality_score(token_data)
            
            # Bonus: ajustement pour wrapped tokens
            if token_data.get('is_wrapped'):
                token_data['quality_score'] = min(
                    100, 
                    token_data['quality_score'] * 1.2  # 20% boost pour wrapped tokens
                )
        except Exception as e:
            self.logger.error(f"Quality score calculation failed: {e}")
            token_data['quality_score'] = 0

        # 7. Validation finale des données
        self.validate_token_data(token_data)

        return token_data

    def check_rug_pull_risk(self, token_address: str) -> Dict:
        """Vérifier le risque de rug pull via RugCheck"""
        try:
            response = self.session.get(
                f"https://api.rugcheck.xyz/v1/tokens/{token_address}/report",
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                rug_score = data.get('score', 0)
                rug_score = max(0, min(rug_score, 100))  # Validation 0-100
                return {
                    'has_rug_check': True,
                    'rug_score': rug_score,
                    'issues': data.get('issues', [])[:10]  # Limiter les issues
                }
            return {'has_rug_check': False}
        except Exception as e:
            self.logger.debug(f"RugCheck error for {token_address}: {e}")
            return {'has_rug_check': False}

    def validate_token_data(self, token_data: Dict) -> bool:
        """Valider les données avant sauvegarde"""
        
        # Vérifications essentielles
        if not token_data.get('address') or not token_data.get('symbol'):
            self.logger.error(f"Missing required fields: address or symbol")
            return False
        
        # Fonction helper pour nettoyer les valeurs numériques
        def clean_numeric(value):
            """Nettoyer et valider une valeur numérique"""
            if value is None:
                return None
            try:
                num_val = float(value)
                # Vérifier les valeurs aberrantes
                if abs(num_val) > 1e15:  # Trop grand
                    return None
                return num_val
            except (ValueError, TypeError):
                return None

        # Valider les types numériques
        numeric_fields = ['price_usdc', 'market_cap', 'liquidity_usd', 'volume_24h', 
                        'price_change_24h', 'age_hours', 'quality_score', 'rug_score', 'price_impact']
        
        for field in numeric_fields:
            if field in token_data:
                cleaned_value = clean_numeric(token_data[field])
                if token_data[field] is not None and cleaned_value is None:
                    self.logger.warning(f"Invalid numeric value for {field}: {token_data[field]}")
                token_data[field] = cleaned_value
        
        # Valider les listes JSON
        list_fields = ['dexes', 'tags', 'issues']
        for field in list_fields:
            if field in token_data and token_data[field] is not None:
                if not isinstance(token_data[field], list):
                    try:
                        # Essayer de convertir si c'est une string JSON
                        if isinstance(token_data[field], str):
                            token_data[field] = json.loads(token_data[field])
                        else:
                            token_data[field] = []
                    except:
                        token_data[field] = []
        
        # Valider quality_score dans la plage attendue
        if token_data.get('quality_score') is not None:
            score = token_data['quality_score']
            if not (0 <= score <= 100):
                self.logger.warning(f"Quality score out of range: {score}, clamping to 0-100")
                token_data['quality_score'] = max(0, min(score, 100))
        
        return True

    def save_token_to_db(self, token_data: Dict):
        """Sauvegarder un token en base de données"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        # Préparer les données JSON
        dexes_json = json.dumps(token_data.get('dexes', []))
        tags_json = json.dumps(token_data.get('tags', []))
        issues_json = json.dumps(token_data.get('issues', []))
        metadata_json = json.dumps({
            'jupiter_data': {
                'logoURI': token_data.get('logo_uri'),
                'extensions': token_data.get('extensions', {})
            },
            'dexscreener_data': token_data.get('dexscreener_data', {}),
            'jupiter_price_data': token_data.get('jupiter_price_data', {}),
            'rug_check_data': {
                'has_rug_check': token_data.get('has_rug_check', False),
                'rug_score': token_data.get('rug_score', None),
                'issues': token_data.get('issues', [])
            }
        })

        cursor.execute('''
        INSERT OR REPLACE INTO tokens (
            address, symbol, name, decimals, logo_uri, price_usdc, market_cap,
            liquidity_usd, volume_24h, price_change_24h, age_hours, pair_created_at,
            route_count, dexes, price_impact, quality_score, has_dexscreener_data,
            is_tradeable, last_updated_at, discovery_source, tags, metadata,
            tx_count_24h, has_verified_contract, has_rug_check, rug_score, issues
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?, ?, ?)
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
            metadata_json,
            token_data.get('tx_count_24h', 0),
            token_data.get('has_verified_contract', False),
            token_data.get('has_rug_check', False),
            token_data.get('rug_score', None),
            issues_json
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
    
    def display_existing_token_info(self, token: Dict, db_info: Dict):
        """Afficher les informations d'un token existant"""
        symbol = token['symbol']
        address = token['address']
        
        # Calculer l'âge depuis la découverte
        discovered_at = db_info.get('first_discovered_at', '')
        age_str = "Unknown"
        
        if discovered_at:
            try:
                # Parse la date de découverte
                discovered_time = datetime.fromisoformat(discovered_at.replace('Z', '+00:00'))
                age_delta = datetime.now() - discovered_time.replace(tzinfo=None)
                
                if age_delta.days > 0:
                    age_str = f"{age_delta.days}d {age_delta.seconds//3600}h"
                else:
                    age_str = f"{age_delta.seconds//3600}h {(age_delta.seconds%3600)//60}m"
            except:
                age_str = "Parse error"
        
        # Âge du token (DexScreener)
        token_age = ""
        if db_info.get('age_hours'):
            hours = db_info['age_hours']
            if hours < 24:
                token_age = f" | Token age: {hours:.1f}h"
            else:
                token_age = f" | Token age: {hours/24:.1f}d"
        
        print(f"⏭️ {symbol} - Already in database | Address: {address[:8]}...{address[-6:]} | "
              f"Discovered: {age_str} ago{token_age} | Quality: {db_info.get('quality_score', 0)}")
    
    def get_birdeye_data(self, token_address: str) -> Dict:
        """Récupérer les données depuis Birdeye"""
        try:
            response = self.session.get(
                f"https://public-api.birdeye.so/defi/token_overview?address={token_address}",
                headers={"X-API-KEY": "YOUR_BIRDEYE_KEY"},  # Optionnel
                timeout=8
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success') and data.get('data'):
                    token_data = data['data']
                    return {
                        'has_birdeye_data': True,
                        'source': 'birdeye',
                        'price_usd': token_data.get('price'),
                        'market_cap': token_data.get('mc'),
                        'liquidity_usd': token_data.get('liquidity'),
                        'volume_24h': token_data.get('v24hUSD'),
                        'age_hours': None  # Birdeye ne fournit pas l'âge
                    }
        except Exception as e:
            self.logger.debug(f"Birdeye error for {token_address}: {e}")
        
        return {'has_birdeye_data': False}

    def get_jupiter_stats_data(self, token_address: str) -> Dict:
        """Récupérer les données depuis Jupiter Stats"""  
        try:
            response = self.session.get(
                f"https://stats.jup.ag/coingecko/coins/{token_address}",
                timeout=5
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'has_jupiter_stats_data': True,
                    'source': 'jupiter_stats',
                    'price_usd': data.get('current_price'),
                    'market_cap': data.get('market_cap'),
                    'volume_24h': data.get('total_volume'),
                    'price_change_24h': data.get('price_change_percentage_24h')
                }
        except Exception as e:
            self.logger.debug(f"Jupiter Stats error for {token_address}: {e}")
        
        return {'has_jupiter_stats_data': False}

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
        print(f"Quality Score: {token_data['quality_score']}/100")
        
        # Score breakdown
        print(f"Score Breakdown: "
              f"Liquidity={token_data.get('liquidity_score', 0):.2f}, "
              f"Volume={token_data.get('volume_score', 0):.2f}, "
              f"Age={token_data.get('age_score', 0):.2f}, "
              f"Volatility={token_data.get('volatility_score', 0):.2f}, "
              f"Risk={token_data.get('risk_score', 0):.2f}, "
              f"Activity={token_data.get('activity_score', 0):.2f}, "
              f"Technical={token_data.get('technical_score', 0):.2f}")
        
        # RugCheck info
        if token_data.get('has_rug_check'):
            print(f"RugCheck Risk Score: {token_data.get('rug_score', 0):.2f}/100")
            if token_data.get('issues'):
                print(f"RugCheck Issues: {', '.join(token_data['issues'][:3])}")
        else:
            print("RugCheck Data: Not available")

        # Prix Jupiter
        if token_data.get('price_usdc'):
            print(f"Price (Jupiter): ${token_data['price_usdc']:.8f} USDC")
            print(f"Route Count: {token_data.get('route_count', 0)}")
            if token_data.get('dexes'):
                print(f"Available DEXes: {', '.join(token_data['dexes'][:3])}")
        
        # Données de marché (vérifier toutes les sources)
        market_data_found = False
        
        # 1. Données DexScreener (priorité)
        if token_data.get('has_dexscreener_data'):
            print(f"📊 DEXSCREENER DATA:")
            market_data_found = True
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

        # 2. Sources alternatives
        elif token_data.get('has_alternative_data'):
            source = token_data.get('primary_source', 'unknown').upper()
            print(f"📊 {source} DATA:")
            market_data_found = True
            
            if token_data.get('market_cap'):
                print(f"Market Cap: ${token_data['market_cap']:,.0f}")
            if token_data.get('liquidity_usd'):
                print(f"Liquidity: ${token_data['liquidity_usd']:,.0f}")
            if token_data.get('volume_24h'):
                print(f"Volume 24h: ${token_data['volume_24h']:,.0f}")
            if token_data.get('price_change_24h'):
                print(f"Price Change 24h: {token_data['price_change_24h']:+.2f}%")
            if token_data.get('holders_count'):
                print(f"Holders: {token_data['holders_count']:,}")
            
            # Afficher toutes les sources essayées
            sources_tried = token_data.get('sources_tried', [])
            if len(sources_tried) > 1:
                print(f"Sources tried: {', '.join(sources_tried)}")

        # 3. Données Jupiter seulement (fallback)
        elif token_data.get('has_price') or token_data.get('price_usdc'):
            print(f"📊 JUPITER DATA ONLY:")
            market_data_found = True
            print(f"Token is tradeable on {len(token_data.get('dexes', []))} DEX(es)")
            if token_data.get('price_impact'):
                print(f"Price Impact: {token_data['price_impact']:.2f}%")
            if token_data.get('route_count', 0) > 0:
                print(f"Available Routes: {token_data['route_count']}")
            print("Note: Limited market data - only Jupiter routing available")

        # 4. Aucune donnée trouvée
        if not market_data_found:
            print("📊 Market Data: No data available from any source")
            if token_data.get('is_tradeable'):
                print("⚠️ Token appears tradeable but no market data found - this may indicate a very new token")
        
        # Métadonnées
        if token_data.get('logo_uri'):
            print(f"Logo: Available")
        
        print(f"Tradeable: {'Yes' if token_data.get('is_tradeable') else 'No'}")
        print(f"{'='*60}")
    
    def get_diversified_candidates(self, all_tokens: List[Dict], limit: int) -> List[Dict]:
        """Obtenir des candidats diversifiés en évitant la répétition"""
        # Filtrer les candidats de qualité
        candidates = []
        for token in all_tokens:
            # Ignorer les tokens dans la liste d'exclusion
            if token['symbol'].upper() in self.ignore_tokens:
                continue
            # Vérifier si le token correspond aux hot patterns
            is_hot = any(pattern.upper() in token['symbol'].upper() or pattern.upper() in token['name'].upper()
                        for pattern in self.hot_patterns)
            
            # Calcul préliminaire du score
            preliminary_score = self.calculate_preliminary_quality_score(token)
            if preliminary_score >= 3 or is_hot:
                token['preliminary_quality_score'] = preliminary_score
                candidates.append(token)
        
        self.logger.info(f"Found {len(candidates)} quality candidates")
        
        # Refresh du cache toutes les heures
        current_time = time.time()
        if current_time - self.last_full_refresh > 3600:  # 1 heure
            self.recently_scanned.clear()
            self.last_full_refresh = current_time
            self.logger.info("Cache refreshed - will scan all candidates again")
        
        # Exclure les tokens récemment scannés
        fresh_candidates = [
            token for token in candidates 
            if token['address'] not in self.recently_scanned
        ]
        
        if len(fresh_candidates) < limit:
            # Si pas assez de nouveaux candidats, mélanger tous les candidats
            self.logger.info(f"Only {len(fresh_candidates)} fresh candidates, using all candidates")
            fresh_candidates = candidates
            # Effacer une partie du cache pour permettre le renouvellement
            if len(self.recently_scanned) > 1000:
                to_remove = list(self.recently_scanned)[:500]
                for addr in to_remove:
                    self.recently_scanned.discard(addr)
        
        # Randomiser l'ordre pour diversifier
        random.shuffle(fresh_candidates)
        
        # Trier par score de qualité les meilleurs candidats
        selected = sorted(fresh_candidates[:limit * 3], 
                         key=lambda x: x.get('preliminary_quality_score', 0), reverse=True)
        
        return selected[:limit * 2]  # Plus de candidats pour compenser les doublons

    def calculate_preliminary_quality_score(self, token_data: Dict) -> float:
        """Calcul préliminaire du score de qualité (sans données de marché)"""
        score = 0
        
        # Vérifications basiques
        if token_data.get('symbol') and len(token_data['symbol']) <= 10:
            score += 2
        
        if token_data.get('name') and len(token_data['name']) <= 50:
            score += 1
            
        if token_data.get('logoURI'):
            score += 2
            
        # Hot patterns bonus
        is_hot = any(pattern.upper() in token_data.get('symbol', '').upper() or 
                    pattern.upper() in token_data.get('name', '').upper()
                    for pattern in self.hot_patterns)
        if is_hot:
            score += 5
            
        return score

    def migrate_database(self):
        """Migrer la base de données pour ajouter les nouvelles colonnes"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        # Vérifier quelles colonnes existent déjà
        cursor.execute("PRAGMA table_info(tokens)")
        existing_columns = {row[1]: row[2] for row in cursor.fetchall()}  # nom: type
        
        # Nouvelles colonnes à ajouter
        new_columns = {
            'tx_count_24h': 'INTEGER DEFAULT 0',
            'has_verified_contract': 'BOOLEAN DEFAULT 0',
            'has_rug_check': 'BOOLEAN DEFAULT 0', 
            'rug_score': 'REAL DEFAULT NULL',
            'issues': 'TEXT DEFAULT NULL'
        }
        
        # Ajouter les colonnes manquantes
        for column_name, column_def in new_columns.items():
            if column_name not in existing_columns:
                try:
                    cursor.execute(f'ALTER TABLE tokens ADD COLUMN {column_name} {column_def}')
                    self.logger.info(f"Added column: {column_name}")
                except sqlite3.OperationalError as e:
                    self.logger.warning(f"Could not add column {column_name}: {e}")
        
        # Changer quality_score en REAL si c'est INTEGER
        if 'quality_score' in existing_columns and 'INTEGER' in existing_columns['quality_score']:
            try:
                # Approche simple : juste recréer l'index
                cursor.execute('DROP INDEX IF EXISTS idx_quality')
                cursor.execute('CREATE INDEX idx_quality ON tokens(CAST(quality_score AS REAL))')
                self.logger.info("Updated quality_score index for REAL values")
            except Exception as e:
                self.logger.warning(f"Could not migrate quality_score: {e}")
        
        conn.commit()
        conn.close()
        self.logger.info("Database migration completed")

    def scan_and_process_tokens(self, limit: int = 20) -> Dict:
        """Scanner et traiter les tokens avec diversification améliorée"""
        scan_start = time.time()
        
        self.logger.info(f"Starting token scan (limit: {limit})")
        
        # Récupérer les tokens Jupiter
        all_tokens = self.get_jupiter_tokens()
        if not all_tokens:
            return {'error': 'No tokens retrieved from Jupiter'}
        
        # Obtenir des candidats diversifiés
        candidates = self.get_diversified_candidates(all_tokens, limit)
        
        # Traiter les candidats
        new_tokens_count = 0
        existing_tokens_count = 0
        processed_count = 0
        
        for token in candidates:
            if processed_count >= limit:
                break
                
            token_address = token['address']
            
            # Ajouter au cache des tokens récemment scannés
            self.recently_scanned.add(token_address)
            
            # Vérifier si le token existe déjà
            if self.token_exists_in_db(token_address):
                existing_tokens_count += 1
                
                # Récupérer les infos de la base pour l'affichage
                db_info = self.get_token_info_from_db(token_address)
                if db_info:
                    self.display_existing_token_info(token, db_info)
                else:
                    print(f"⏭️ {token['symbol']} - Already in database (Address: {token_address[:8]}...{token_address[-6:]})")
                continue
            
            processed_count += 1
            self.logger.info(f"Processing new token: {token['symbol']} ({processed_count}/{limit})")
            print(f"🔍 Processing new token: {token['symbol']} ({processed_count}/{limit})")
            
            # Enrichir les données
            token_data = {
                'address': token_address,
                'symbol': token['symbol'],
                'name': token['name'],
                'decimals': token.get('decimals', 9),
                'logo_uri': token.get('logoURI'),
                'tags': token.get('tags', [])
            }
            
            token_data = self.enrich_token_data(token_address, token_data)
            
            # Validation des données
            if not self.validate_token_data(token_data):
                self.logger.warning(f"Invalid token data for {token['symbol']}, skipping...")
                continue

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
            'notes': f'Quality threshold: 3+, Cache size: {len(self.recently_scanned)}, Jupiter+DexScreener enrichment'
        }
        
        self.save_scan_history(scan_stats)
        
        return scan_stats
    
    def run_continuous_scanning(self, interval_minutes: int, limit: int):
        """Scanner en continu avec amélioration de la diversité"""
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
                    print(f"   Cache size: {len(self.recently_scanned)}")
                    
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
            print(f"📊 Final cache size: {len(self.recently_scanned)}")
    
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