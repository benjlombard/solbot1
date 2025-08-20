import sqlite3
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from contextlib import contextmanager
import json

from models import PumpToken, EarlyPurchase, EarlyAdopter, TokenOutcome, OutcomeType
from config import settings

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_path: str = settings.database_url):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialise la base de données avec les tables et index nécessaires"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Table pump_tokens
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pump_tokens (
                    address TEXT PRIMARY KEY,
                    name TEXT,
                    symbol TEXT,
                    description TEXT,
                    creator TEXT,
                    created_at TIMESTAMP,
                    market_cap_discovery REAL
                )
            """)
            
            # Table early_purchases
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS early_purchases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signature TEXT UNIQUE,
                    token_address TEXT,
                    buyer_address TEXT,
                    sol_amount REAL,
                    token_amount REAL,
                    timestamp TIMESTAMP,
                    minutes_after_creation INTEGER,
                    market_cap_at_purchase REAL,
                    FOREIGN KEY (token_address) REFERENCES pump_tokens(address)
                )
            """)
            
            # Table early_adopters
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS early_adopters (
                    wallet_address TEXT PRIMARY KEY,
                    total_picks INTEGER DEFAULT 0,
                    successful_picks INTEGER DEFAULT 0,
                    avg_entry_timing REAL DEFAULT 0.0,
                    success_rate REAL DEFAULT 0.0,
                    avg_roi REAL DEFAULT 0.0,
                    confidence_score REAL DEFAULT 0.0,
                    last_activity TIMESTAMP
                )
            """)
            
            # Table token_outcomes
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS token_outcomes (
                    token_address TEXT PRIMARY KEY,
                    outcome_type TEXT,
                    roi_24h REAL,
                    roi_7d REAL,
                    peak_market_cap REAL,
                    migration_date TIMESTAMP,
                    FOREIGN KEY (token_address) REFERENCES pump_tokens(address)
                )
            """)
            
            # Création des index pour optimiser les performances
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_created_at ON pump_tokens(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_buyer_address ON early_purchases(buyer_address)",
                "CREATE INDEX IF NOT EXISTS idx_token_timestamp ON early_purchases(token_address, timestamp)",
                "CREATE INDEX IF NOT EXISTS idx_confidence_score ON early_adopters(confidence_score DESC)",
                "CREATE INDEX IF NOT EXISTS idx_signature ON early_purchases(signature)"
            ]
            
            for index in indexes:
                cursor.execute(index)
            
            conn.commit()
            logger.info("Database initialized successfully")
    
    @contextmanager
    def get_connection(self):
        """Context manager pour les connexions à la base de données"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def insert_pump_token(self, token: PumpToken) -> bool:
        """Insère un nouveau token pump.fun"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO pump_tokens 
                    (address, name, symbol, description, creator, created_at, market_cap_discovery)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    token.address, token.name, token.symbol, token.description,
                    token.creator, token.created_at, token.market_cap_discovery
                ))
                conn.commit()
                logger.info(f"Inserted token: {token.address}")
                return True
        except Exception as e:
            logger.error(f"Error inserting token {token.address}: {e}")
            return False
    
    def insert_early_purchase(self, purchase: EarlyPurchase) -> bool:
        """Insère un achat précoce"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR IGNORE INTO early_purchases 
                    (signature, token_address, buyer_address, sol_amount, token_amount,
                     timestamp, minutes_after_creation, market_cap_at_purchase)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    purchase.signature, purchase.token_address, purchase.buyer_address,
                    purchase.sol_amount, purchase.token_amount, purchase.timestamp,
                    purchase.minutes_after_creation, purchase.market_cap_at_purchase
                ))
                conn.commit()
                logger.info(f"Inserted early purchase: {purchase.signature}")
                return True
        except Exception as e:
            logger.error(f"Error inserting purchase {purchase.signature}: {e}")
            return False
    
    def upsert_early_adopter(self, adopter: EarlyAdopter) -> bool:
        """Insère ou met à jour un early adopter"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO early_adopters 
                    (wallet_address, total_picks, successful_picks, avg_entry_timing,
                     success_rate, avg_roi, confidence_score, last_activity)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    adopter.wallet_address, adopter.total_picks, adopter.successful_picks,
                    adopter.avg_entry_timing, adopter.success_rate, adopter.avg_roi,
                    adopter.confidence_score, adopter.last_activity
                ))
                conn.commit()
                logger.info(f"Updated early adopter: {adopter.wallet_address}")
                return True
        except Exception as e:
            logger.error(f"Error updating early adopter {adopter.wallet_address}: {e}")
            return False
    
    def get_token_by_address(self, address: str) -> Optional[PumpToken]:
        """Récupère un token par son adresse"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM pump_tokens WHERE address = ?", (address,))
                row = cursor.fetchone()
                if row:
                    return PumpToken(
                        address=row['address'],
                        name=row['name'],
                        symbol=row['symbol'], 
                        description=row['description'],
                        creator=row['creator'],
                        created_at=datetime.fromisoformat(row['created_at']),
                        market_cap_discovery=row['market_cap_discovery']
                    )
                return None
        except Exception as e:
            logger.error(f"Error getting token {address}: {e}")
            return None
    
    def get_early_adopters(self, min_confidence_score: float = 0.6, limit: int = 50) -> List[EarlyAdopter]:
        """Récupère les early adopters classés par score de confiance"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM early_adopters 
                    WHERE confidence_score >= ?
                    ORDER BY confidence_score DESC
                    LIMIT ?
                """, (min_confidence_score, limit))
                
                adopters = []
                for row in cursor.fetchall():
                    adopters.append(EarlyAdopter(
                        wallet_address=row['wallet_address'],
                        total_picks=row['total_picks'],
                        successful_picks=row['successful_picks'],
                        avg_entry_timing=row['avg_entry_timing'],
                        success_rate=row['success_rate'],
                        avg_roi=row['avg_roi'],
                        confidence_score=row['confidence_score'],
                        last_activity=datetime.fromisoformat(row['last_activity'])
                    ))
                return adopters
        except Exception as e:
            logger.error(f"Error getting early adopters: {e}")
            return []
    
    def get_wallet_purchases(self, wallet_address: str, days_back: int = 30) -> List[Dict[str, Any]]:
        """Récupère les achats d'un wallet sur une période"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                since_date = datetime.now() - timedelta(days=days_back)
                
                cursor.execute("""
                    SELECT ep.*, pt.name, pt.symbol 
                    FROM early_purchases ep
                    JOIN pump_tokens pt ON ep.token_address = pt.address
                    WHERE ep.buyer_address = ? AND ep.timestamp >= ?
                    ORDER BY ep.timestamp DESC
                """, (wallet_address, since_date.isoformat()))
                
                purchases = []
                for row in cursor.fetchall():
                    purchases.append({
                        'signature': row['signature'],
                        'token_address': row['token_address'],
                        'token_name': row['name'],
                        'token_symbol': row['symbol'],
                        'sol_amount': row['sol_amount'],
                        'timestamp': row['timestamp'],
                        'minutes_after_creation': row['minutes_after_creation']
                    })
                return purchases
        except Exception as e:
            logger.error(f"Error getting wallet purchases {wallet_address}: {e}")
            return []
    
    def get_recent_tokens(self, hours_back: int = 24, limit: int = 100) -> List[Dict[str, Any]]:
        """Récupère les tokens récents avec les achats early adopters"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                since_date = datetime.now() - timedelta(hours=hours_back)
                
                cursor.execute("""
                    SELECT 
                        pt.*,
                        COUNT(ep.id) as early_purchases_count,
                        GROUP_CONCAT(DISTINCT ea.wallet_address) as early_adopter_buyers
                    FROM pump_tokens pt
                    LEFT JOIN early_purchases ep ON pt.address = ep.token_address
                    LEFT JOIN early_adopters ea ON ep.buyer_address = ea.wallet_address 
                        AND ea.confidence_score >= 0.6
                    WHERE pt.created_at >= ?
                    GROUP BY pt.address
                    ORDER BY pt.created_at DESC
                    LIMIT ?
                """, (since_date.isoformat(), limit))
                
                tokens = []
                for row in cursor.fetchall():
                    early_adopters = []
                    if row['early_adopter_buyers']:
                        early_adopters = row['early_adopter_buyers'].split(',')
                    
                    tokens.append({
                        'address': row['address'],
                        'name': row['name'],
                        'symbol': row['symbol'],
                        'creator': row['creator'],
                        'created_at': row['created_at'],
                        'market_cap_discovery': row['market_cap_discovery'],
                        'early_purchases_count': row['early_purchases_count'],
                        'early_adopter_buyers': early_adopters
                    })
                return tokens
        except Exception as e:
            logger.error(f"Error getting recent tokens: {e}")
            return []
    
    def get_dashboard_stats(self) -> Dict[str, Any]:
        """Récupère les statistiques pour le dashboard"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Total tokens tracked
                cursor.execute("SELECT COUNT(*) FROM pump_tokens")
                total_tokens = cursor.fetchone()[0]
                
                # Total early adopters
                cursor.execute("SELECT COUNT(*) FROM early_adopters WHERE confidence_score >= 0.6")
                total_early_adopters = cursor.fetchone()[0]
                
                # Recent activity (24h)
                since_24h = (datetime.now() - timedelta(hours=24)).isoformat()
                cursor.execute("SELECT COUNT(*) FROM early_purchases WHERE timestamp >= ?", (since_24h,))
                recent_purchases = cursor.fetchone()[0]
                
                return {
                    'total_tokens_tracked': total_tokens,
                    'total_early_adopters': total_early_adopters, 
                    'recent_purchases_24h': recent_purchases,
                    'last_updated': datetime.now().isoformat()
                }
        except Exception as e:
            logger.error(f"Error getting dashboard stats: {e}")
            return {}

# Instance globale
db = DatabaseManager()