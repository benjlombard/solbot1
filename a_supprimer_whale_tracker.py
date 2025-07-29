#!/usr/bin/env python3
"""
🐋 Whale Tracker - Phase 1: Identification et Tracking Basique
Détecte et suit les gros portefeuilles (whales) pour les tokens surveillés
"""

import sqlite3
import asyncio
import aiohttp
import logging
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict

logger = logging.getLogger('whale_tracker')

@dataclass
class WhaleWallet:
    """Représente un portefeuille whale"""
    address: str
    label: str = None  # CEX, known whale, etc.
    total_value_usd: float = 0.0
    is_known_entity: bool = False
    first_detected: datetime = None
    last_activity: datetime = None

@dataclass
class WhalePosition:
    """Position d'un whale sur un token spécifique"""
    wallet_address: str
    token_address: str
    balance: float
    balance_usd: float
    percentage_of_supply: float
    last_updated: datetime
    is_accumulating: bool = None

@dataclass
class WhaleTransaction:
    """Transaction significative d'un whale"""
    wallet_address: str
    token_address: str
    transaction_type: str  # 'buy', 'sell', 'transfer'
    amount: float
    amount_usd: float
    timestamp: datetime
    signature: str
    price_impact: float = None

class WhaleTracker:
    """Tracker principal pour l'identification et le suivi des whales"""
    
    def __init__(self, database_path: str = "tokens.db"):
        self.database_path = database_path
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Configuration seuils
        self.WHALE_THRESHOLDS = {
            'min_token_value_usd': 10000,     # $10K minimum par token
            'min_total_portfolio_usd': 50000,  # $50K portfolio total
            'min_supply_percentage': 1.0,      # 1% du supply minimum
            'significant_trade_usd': 5000,     # Trade significatif > $5K
        }
        
        # Wallets connus (CEX, market makers, etc.)
        self.KNOWN_WALLETS = {
            # Exchanges principaux
            "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1": "Binance Hot Wallet",
            "GThUX1Atko4tqhN2NaiTazWSeFWMuiUiswQttNs2r9F9": "Binance Cold Storage",
            "36dn9cKuFW7rCUfCTPZ9MYPBnhDPdWaE6uHjzfyLJr7Y": "FTX Hot Wallet",
            "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM": "Coinbase",
            "ASTyfSima4LLAdDgoFGkgqoKowG1LZFDr9fAQrg6eWAr": "OKX Hot Wallet",
        }
        
        self.setup_database()
        
    def setup_database(self):
        """Créer les tables nécessaires pour le whale tracking"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            # Table des wallets identifiés comme whales
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS whale_wallets (
                    address TEXT PRIMARY KEY,
                    label TEXT,
                    total_value_usd REAL DEFAULT 0,
                    is_known_entity BOOLEAN DEFAULT 0,
                    first_detected TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_activity TIMESTAMP,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Table des positions des whales par token
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS whale_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wallet_address TEXT,
                    token_address TEXT,
                    balance REAL,
                    balance_usd REAL,
                    percentage_of_supply REAL,
                    is_accumulating BOOLEAN,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (wallet_address) REFERENCES whale_wallets (address),
                    FOREIGN KEY (token_address) REFERENCES tokens (address),
                    UNIQUE(wallet_address, token_address)
                )
            ''')
            
            # Table des transactions significatives des whales
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS whale_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wallet_address TEXT,
                    token_address TEXT,
                    transaction_type TEXT,
                    amount REAL,
                    amount_usd REAL,
                    price_impact REAL,
                    signature TEXT UNIQUE,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (wallet_address) REFERENCES whale_wallets (address),
                    FOREIGN KEY (token_address) REFERENCES tokens (address)
                )
            ''')
            
            # Index pour optimiser les requêtes
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_whale_positions_token ON whale_positions(token_address)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_whale_positions_wallet ON whale_positions(wallet_address)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_whale_transactions_token ON whale_transactions(token_address)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_whale_transactions_timestamp ON whale_transactions(timestamp)')
            
            conn.commit()
            logger.info("✅ Whale tracking database initialized")
            
        except sqlite3.Error as e:
            logger.error(f"Database setup error: {e}")
        finally:
            conn.close()
    
    async def start_session(self):
        """Démarrer la session HTTP"""
        if not self.session:
            connector = aiohttp.TCPConnector(limit=50, limit_per_host=20)
            timeout = aiohttp.ClientTimeout(total=15)
            self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
    
    async def close_session(self):
        """Fermer la session HTTP"""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def get_token_holders(self, token_address: str, limit: int = 100) -> List[Dict]:
        """Récupérer la liste des holders d'un token via Solscan"""
        url = f"https://public-api.solscan.io/token/holders?tokenAddress={token_address}&limit={limit}"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('holders', [])
                else:
                    logger.warning(f"Solscan API error {response.status} for {token_address}")
                    return []
        except Exception as e:
            logger.error(f"Error fetching holders for {token_address}: {e}")
            return []
    
    async def get_token_supply_info(self, token_address: str) -> Dict:
        """Récupérer les informations sur le supply du token"""
        url = f"https://public-api.solscan.io/token/meta?tokenAddress={token_address}"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        'total_supply': float(data.get('supply', 0)),
                        'decimals': int(data.get('decimals', 9)),
                        'holder_count': int(data.get('holder', 0))
                    }
        except Exception as e:
            logger.error(f"Error fetching supply info for {token_address}: {e}")
        
        return {'total_supply': 0, 'decimals': 9, 'holder_count': 0}
    
    async def get_token_price_usd(self, token_address: str) -> float:
        """Récupérer le prix USD du token depuis la base ou DexScreener"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            # Essayer d'abord depuis la base de données
            cursor.execute('''
                SELECT COALESCE(dexscreener_price_usd, price_usdc) as price
                FROM tokens 
                WHERE address = ? AND (dexscreener_price_usd > 0 OR price_usdc > 0)
            ''', (token_address,))
            
            result = cursor.fetchone()
            if result and result[0]:
                return float(result[0])
            
            # Fallback: DexScreener API
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    pairs = data.get('pairs', [])
                    if pairs:
                        return float(pairs[0].get('priceUsd', 0))
            
            return 0.0
            
        except Exception as e:
            logger.error(f"Error getting price for {token_address}: {e}")
            return 0.0
        finally:
            conn.close()
    
    async def identify_whales_for_token(self, token_address: str) -> List[WhaleWallet]:
        """Identifier les whales pour un token spécifique"""
        logger.info(f"🔍 Identifying whales for token {token_address}")
        
        # Récupérer les informations du token
        supply_info = await self.get_token_supply_info(token_address)
        token_price = await self.get_token_price_usd(token_address)
        
        if supply_info['total_supply'] == 0 or token_price == 0:
            logger.warning(f"Cannot identify whales for {token_address}: missing supply or price data")
            return []
        
        # Récupérer les top holders
        holders = await self.get_token_holders(token_address, limit=50)
        whales = []
        
        for holder in holders:
            try:
                wallet_address = holder.get('address', '')
                balance = float(holder.get('amount', 0))
                
                if not wallet_address or balance == 0:
                    continue
                
                # Calculer les métriques
                balance_adjusted = balance / (10 ** supply_info['decimals'])
                balance_usd = balance_adjusted * token_price
                percentage_of_supply = (balance_adjusted / supply_info['total_supply']) * 100
                
                # Vérifier les critères de whale
                is_whale = (
                    balance_usd >= self.WHALE_THRESHOLDS['min_token_value_usd'] or
                    percentage_of_supply >= self.WHALE_THRESHOLDS['min_supply_percentage']
                )
                
                if is_whale:
                    # Vérifier si c'est un wallet connu
                    label = self.KNOWN_WALLETS.get(wallet_address)
                    is_known = wallet_address in self.KNOWN_WALLETS
                    
                    whale = WhaleWallet(
                        address=wallet_address,
                        label=label,
                        total_value_usd=balance_usd,  # On ne connaît que cette position pour l'instant
                        is_known_entity=is_known,
                        first_detected=datetime.now(),
                        last_activity=datetime.now()
                    )
                    
                    whales.append(whale)
                    
                    logger.info(f"🐋 Whale detected: {wallet_address[:8]}... "
                              f"(${balance_usd:,.0f}, {percentage_of_supply:.2f}% supply)")
                
            except Exception as e:
                logger.error(f"Error processing holder {holder}: {e}")
                continue
        
        return whales
    
    async def update_whale_positions(self, token_address: str, whales: List[WhaleWallet]):
        """Mettre à jour les positions des whales en base de données"""
        if not whales:
            return
        
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            supply_info = await self.get_token_supply_info(token_address)
            token_price = await self.get_token_price_usd(token_address)
            
            for whale in whales:
                # Insérer ou mettre à jour le whale dans whale_wallets
                cursor.execute('''
                    INSERT OR REPLACE INTO whale_wallets 
                    (address, label, total_value_usd, is_known_entity, first_detected, last_activity)
                    VALUES (?, ?, ?, ?, 
                           COALESCE((SELECT first_detected FROM whale_wallets WHERE address = ?), ?),
                           ?)
                ''', (
                    whale.address, whale.label, whale.total_value_usd, whale.is_known_entity,
                    whale.address, whale.first_detected, whale.last_activity
                ))
                
                # Calculer la position actuelle
                holders = await self.get_token_holders(token_address, limit=100)
                holder_data = next((h for h in holders if h.get('address') == whale.address), None)
                
                if holder_data:
                    balance = float(holder_data.get('amount', 0))
                    balance_adjusted = balance / (10 ** supply_info['decimals'])
                    balance_usd = balance_adjusted * token_price
                    percentage_of_supply = (balance_adjusted / supply_info['total_supply']) * 100 if supply_info['total_supply'] > 0 else 0
                    
                    # Insérer ou mettre à jour la position
                    cursor.execute('''
                        INSERT OR REPLACE INTO whale_positions 
                        (wallet_address, token_address, balance, balance_usd, percentage_of_supply, last_updated)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (
                        whale.address, token_address, balance_adjusted, balance_usd, 
                        percentage_of_supply, datetime.now()
                    ))
            
            conn.commit()
            logger.info(f"💾 Updated {len(whales)} whale positions for token {token_address}")
            
        except Exception as e:
            logger.error(f"Error updating whale positions: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    async def scan_all_tokens_for_whales(self, limit: int = 20):
        """Scanner tous les tokens actifs pour identifier les whales"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            # Récupérer les tokens les plus actifs/récents
            cursor.execute('''
                SELECT address, symbol 
                FROM tokens 
                WHERE (dexscreener_volume_24h > 50000 OR volume_24h > 50000)
                AND (dexscreener_price_usd > 0 OR price_usdc > 0)
                AND symbol IS NOT NULL 
                AND symbol != 'UNKNOWN'
                ORDER BY COALESCE(dexscreener_volume_24h, volume_24h, 0) DESC
                LIMIT ?
            ''', (limit,))
            
            tokens = cursor.fetchall()
            
        except Exception as e:
            logger.error(f"Error getting tokens for whale scan: {e}")
            return
        finally:
            conn.close()
        
        if not tokens:
            logger.info("No tokens found for whale scanning")
            return
        
        logger.info(f"🐋 Starting whale scan for {len(tokens)} tokens")
        
        await self.start_session()
        
        try:
            for i, (token_address, symbol) in enumerate(tokens, 1):
                logger.info(f"[{i}/{len(tokens)}] Scanning {symbol} ({token_address})")
                
                try:
                    whales = await self.identify_whales_for_token(token_address)
                    
                    if whales:
                        await self.update_whale_positions(token_address, whales)
                        logger.info(f"✅ Found {len(whales)} whales for {symbol}")
                    else:
                        logger.info(f"ℹ️ No whales found for {symbol}")
                    
                    # Délai pour éviter le rate limiting
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    logger.error(f"Error scanning {symbol}: {e}")
                    continue
                    
        finally:
            await self.close_session()
        
        logger.info("🎯 Whale scanning completed")
    
    def get_whale_summary(self) -> Dict:
        """Récupérer un résumé de l'activité des whales"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            # Statistiques générales
            cursor.execute("SELECT COUNT(*) FROM whale_wallets WHERE status = 'active'")
            total_whales = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM whale_wallets WHERE is_known_entity = 1")
            known_entities = cursor.fetchone()[0]
            
            cursor.execute("SELECT SUM(total_value_usd) FROM whale_wallets WHERE status = 'active'")
            total_whale_value = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT COUNT(DISTINCT token_address) FROM whale_positions")
            tokens_with_whales = cursor.fetchone()[0]
            
            cursor.execute('''
                SELECT COUNT(*) FROM whale_positions 
                WHERE last_updated > datetime('now', '-24 hours')
            ''')
            recent_positions = cursor.fetchone()[0]
            
            # Top 5 whales par valeur
            cursor.execute('''
                SELECT address, label, total_value_usd, is_known_entity
                FROM whale_wallets 
                WHERE status = 'active'
                ORDER BY total_value_usd DESC 
                LIMIT 5
            ''')
            top_whales = [
                {
                    'address': row[0],
                    'label': row[1] or f"Whale {row[0][:8]}...",
                    'value_usd': row[2],
                    'is_known': bool(row[3])
                }
                for row in cursor.fetchall()
            ]
            
            return {
                'total_whales': total_whales,
                'known_entities': known_entities,
                'total_whale_value_usd': total_whale_value,
                'tokens_with_whales': tokens_with_whales,
                'recent_positions_24h': recent_positions,
                'top_whales': top_whales
            }
            
        except Exception as e:
            logger.error(f"Error getting whale summary: {e}")
            return {}
        finally:
            conn.close()
    
    def get_token_whale_analysis(self, token_address: str) -> Dict:
        """Analyser l'activité des whales pour un token spécifique"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            # Positions actuelles des whales sur ce token
            cursor.execute('''
                SELECT wp.wallet_address, ww.label, wp.balance_usd, wp.percentage_of_supply,
                       wp.last_updated, ww.is_known_entity
                FROM whale_positions wp
                JOIN whale_wallets ww ON wp.wallet_address = ww.address
                WHERE wp.token_address = ?
                AND ww.status = 'active'
                ORDER BY wp.balance_usd DESC
            ''', (token_address,))
            
            positions = [
                {
                    'wallet_address': row[0],
                    'label': row[1] or f"Whale {row[0][:8]}...",
                    'balance_usd': row[2],
                    'percentage_of_supply': row[3],
                    'last_updated': row[4],
                    'is_known_entity': bool(row[5])
                }
                for row in cursor.fetchall()
            ]
            
            # Métriques d'agrégation
            total_whale_value = sum(p['balance_usd'] for p in positions)
            total_whale_percentage = sum(p['percentage_of_supply'] for p in positions)
            whale_count = len(positions)
            
            # Concentration score (basé sur la distribution)
            if positions:
                top_3_percentage = sum(p['percentage_of_supply'] for p in positions[:3])
                concentration_score = min(top_3_percentage / 30 * 100, 100)  # Max 100 si top 3 = 30%+
            else:
                concentration_score = 0
            
            return {
                'whale_count': whale_count,
                'total_whale_value_usd': total_whale_value,
                'total_whale_percentage': total_whale_percentage,
                'concentration_score': concentration_score,
                'positions': positions
            }
            
        except Exception as e:
            logger.error(f"Error analyzing whale activity for {token_address}: {e}")
            return {}
        finally:
            conn.close()

# Fonctions utilitaires pour intégration
async def run_whale_scan():
    """Fonction pour lancer un scan des whales"""
    tracker = WhaleTracker()
    await tracker.scan_all_tokens_for_whales(limit=30)

async def get_whale_data_for_api():
    """Fonction pour récupérer les données whales pour l'API"""
    tracker = WhaleTracker()
    return tracker.get_whale_summary()

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    async def main():
        tracker = WhaleTracker()
        
        # Test avec un scan limité
        await tracker.scan_all_tokens_for_whales(limit=5)
        
        # Afficher le résumé
        summary = tracker.get_whale_summary()
        print("\n🐋 WHALE TRACKING SUMMARY:")
        print(f"Total Whales: {summary.get('total_whales', 0)}")
        print(f"Known Entities: {summary.get('known_entities', 0)}")
        print(f"Total Value: ${summary.get('total_whale_value_usd', 0):,.0f}")
        print(f"Tokens with Whales: {summary.get('tokens_with_whales', 0)}")
        
        if summary.get('top_whales'):
            print("\n🏆 Top Whales:")
            for whale in summary['top_whales']:
                label = whale['label'] if whale['is_known'] else f"Unknown {whale['address'][:8]}..."
                print(f"  {label}: ${whale['value_usd']:,.0f}")
    
    asyncio.run(main())