import sqlite3
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from contextlib import contextmanager
import json

from app.models import PumpToken, EarlyPurchase, EarlyAdopter, TokenOutcome, OutcomeType
from app.config import settings

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
                    market_cap_discovery REAL,
                    -- Cached data from Pump.fun API
                    usd_market_cap REAL,
                    holders_count INTEGER,
                    bonding_curve_progress REAL,
                    logo_uri TEXT,
                    is_verified BOOLEAN,
                    last_updated_pumpfun TIMESTAMP,
                    twitter TEXT,
                    telegram TEXT,
                    website TEXT,
                    total_supply REAL,
                    nsfw BOOLEAN,
                    bonding_curve TEXT,
                    king_of_the_hill_timestamp TIMESTAMP,
                    metadata_uri TEXT,
                    associated_bonding_curve TEXT,
                    raydium_pool TEXT,
                    virtual_sol_reserves REAL,
                    virtual_token_reserves REAL,
                    hidden BOOLEAN,
                    show_name BOOLEAN,
                    last_trade_timestamp TIMESTAMP,
                    market_cap REAL,
                    market_id TEXT,
                    inverted BOOLEAN,
                    real_sol_reserves REAL,
                    real_token_reserves REAL,
                    livestream_ban_expiry TIMESTAMP,
                    last_reply TIMESTAMP,
                    reply_count INTEGER,
                    is_banned BOOLEAN,
                    is_currently_live BOOLEAN,
                    initialized BOOLEAN,
                    video_uri TEXT,
                    updated_at TIMESTAMP,
                    pump_swap_pool TEXT,
                    ath_market_cap REAL,
                    ath_market_cap_timestamp TIMESTAMP,
                    banner_uri TEXT,
                    hide_banner BOOLEAN,
                    livestream_downrank_score REAL,
                    row_created_at TIMESTAMP
                )
            """)

            # Table pump_tokens_history
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pump_tokens_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_timestamp TIMESTAMP,
                    token_address TEXT,
                    name TEXT,
                    symbol TEXT,
                    description TEXT,
                    creator TEXT,
                    created_at TIMESTAMP,
                    market_cap_discovery REAL,
                    usd_market_cap REAL,
                    holders_count INTEGER,
                    bonding_curve_progress REAL,
                    logo_uri TEXT,
                    is_verified BOOLEAN,
                    last_updated_pumpfun TIMESTAMP,
                    twitter TEXT,
                    telegram TEXT,
                    website TEXT,
                    total_supply REAL,
                    nsfw BOOLEAN,
                    bonding_curve TEXT,
                    king_of_the_hill_timestamp TIMESTAMP,
                    metadata_uri TEXT,
                    associated_bonding_curve TEXT,
                    raydium_pool TEXT,
                    virtual_sol_reserves REAL,
                    virtual_token_reserves REAL,
                    hidden BOOLEAN,
                    show_name BOOLEAN,
                    last_trade_timestamp TIMESTAMP,
                    market_cap REAL,
                    market_id TEXT,
                    inverted BOOLEAN,
                    real_sol_reserves REAL,
                    real_token_reserves REAL,
                    livestream_ban_expiry TIMESTAMP,
                    last_reply TIMESTAMP,
                    reply_count INTEGER,
                    is_banned BOOLEAN,
                    is_currently_live BOOLEAN,
                    initialized BOOLEAN,
                    video_uri TEXT,
                    updated_at TIMESTAMP,
                    pump_swap_pool TEXT,
                    ath_market_cap REAL,
                    ath_market_cap_timestamp TIMESTAMP,
                    banner_uri TEXT,
                    hide_banner BOOLEAN,
                    livestream_downrank_score REAL,
                    row_created_at TIMESTAMP,
                    creator_reputation_score REAL DEFAULT NULL,
                    creator_risk_score REAL DEFAULT NULL,
                    creator_is_blacklisted BOOLEAN DEFAULT FALSE,
                    creator_total_previous_tokens INTEGER DEFAULT 0,
                    creator_success_rate REAL DEFAULT NULL,
                    FOREIGN KEY (token_address) REFERENCES pump_tokens(address)
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
            
            # Table rugcheck_reports
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS rugcheck_reports (
                    token_address TEXT PRIMARY KEY,
                    score REAL,
                    is_rugged BOOLEAN,
                    risks TEXT,
                    top_holders TEXT,
                    raw_report TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (token_address) REFERENCES pump_tokens(address)
                )
            """)

            # Création des index pour optimiser les performances
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_created_at ON pump_tokens(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_buyer_address ON early_purchases(buyer_address)",
                "CREATE INDEX IF NOT EXISTS idx_token_timestamp ON early_purchases(token_address, timestamp)",
                "CREATE INDEX IF NOT EXISTS idx_confidence_score ON early_adopters(confidence_score DESC)",
                "CREATE INDEX IF NOT EXISTS idx_signature ON early_purchases(signature)",
                "CREATE INDEX IF NOT EXISTS idx_rugcheck_reports_token_address ON rugcheck_reports(token_address)"
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
                    (address, name, symbol, description, creator, created_at, market_cap_discovery, row_created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    token.address, token.name, token.symbol, token.description,
                    token.creator, token.created_at, token.market_cap_discovery,
                    datetime.now().isoformat()
                ))
                conn.commit()
                logger.debug(f"Inserted token: {token.address}")
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
                logger.debug(f"Inserted early purchase: {purchase.signature}")
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
                logger.debug(f"Updated early adopter: {adopter.wallet_address}")
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

    def create_snapshot(self, token_address: str):
        """Crée un snapshot d'un token dans la table d'historique."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Récupérer les noms de colonnes de la table source
                cursor.execute("PRAGMA table_info(pump_tokens)")
                source_columns = [row['name'] for row in cursor.fetchall() if row['name'] != 'address']
                
                # Récupérer l'état actuel du token
                cursor.execute(f"SELECT {', '.join(source_columns)} FROM pump_tokens WHERE address = ?", (token_address,))
                token_row = cursor.fetchone()
                
                if not token_row:
                    logger.warning(f"Token {token_address} not found for snapshot.")
                    return

                # Préparer les données pour l'insertion
                history_columns = ['snapshot_timestamp', 'token_address'] + source_columns
                history_values = [datetime.now().isoformat(), token_address] + list(token_row)
                
                # Construire la requête d'insertion
                query = f"""
                    INSERT INTO pump_tokens_history ({', '.join(history_columns)})
                    VALUES ({', '.join(['?'] * len(history_columns))})
                """
                
                cursor.execute(query, tuple(history_values))
                conn.commit()
                logger.debug(f"Created snapshot for token: {token_address}")

        except Exception as e:
            logger.error(f"Error creating snapshot for token {token_address}: {e}", exc_info=True)
    
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
        """Récupère les tokens récents avec les données enrichies et les achats early adopters"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                since_date = datetime.now() - timedelta(hours=hours_back)
                
                # La requête inclut maintenant toutes les colonnes de pump_tokens et le score de rugcheck
                cursor.execute("""
                    SELECT 
                        pt.*,
                        rr.score as rugcheck_score,
                        rr.risks as rugcheck_risks,
                        rr.top_holders as rugcheck_top_holders,
                        rr.raw_report as rugcheck_raw_report,
                        COUNT(ep.id) as early_purchases_count,
                        GROUP_CONCAT(DISTINCT ea.wallet_address) as early_adopter_buyers
                    FROM pump_tokens pt
                    LEFT JOIN early_purchases ep ON pt.address = ep.token_address
                    LEFT JOIN early_adopters ea ON ep.buyer_address = ea.wallet_address 
                        AND ea.confidence_score >= 0.6
                    LEFT JOIN rugcheck_reports rr ON pt.address = rr.token_address
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
                    
                    # Convertir la ligne de la base de données en dictionnaire
                    token_data = dict(row)
                    # Ajouter les acheteurs early adopters traités
                    token_data['early_adopter_buyers'] = early_adopters
                    tokens.append(token_data)
                    
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

    def get_tokens_to_enrich(self, limit: int = 50, update_interval_minutes: int = 5) -> List[str]:
        """
        Récupère une liste d'adresses de tokens qui ont besoin d'être enrichies.
        Sélectionne les tokens qui n'ont pas été mis à jour dans l'intervalle de temps spécifié.
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # Tokens qui n'ont jamais été mis à jour ou mis à jour il y a plus de X minutes
                interval_ago = (datetime.now() - timedelta(minutes=update_interval_minutes)).isoformat()
                cursor.execute("""
                    SELECT address FROM pump_tokens
                    WHERE last_updated_pumpfun IS NULL OR last_updated_pumpfun < ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (interval_ago, limit))
                
                rows = cursor.fetchall()
                return [row['address'] for row in rows]
        except Exception as e:
            logger.error(f"Error getting tokens to enrich: {e}")
            return []

    def update_token_pumpfun_data(self, token_address: str, pump_data: Dict[str, Any]) -> bool:
        """Met à jour un token avec les données fraîches et complètes de l'API Pump.fun."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                def ts_to_iso(timestamp_ms):
                    if not timestamp_ms:
                        return None
                    return datetime.fromtimestamp(timestamp_ms / 1000).isoformat()

                cursor.execute("""
                    UPDATE pump_tokens
                    SET 
                        name = ?, symbol = ?, description = ?, logo_uri = ?, is_verified = ?,
                        usd_market_cap = ?, bonding_curve_progress = ?,
                        twitter = ?, telegram = ?, website = ?, total_supply = ?, nsfw = ?,
                        bonding_curve = ?, king_of_the_hill_timestamp = ?, metadata_uri = ?,
                        associated_bonding_curve = ?, raydium_pool = ?, virtual_sol_reserves = ?,
                        virtual_token_reserves = ?, hidden = ?, show_name = ?, last_trade_timestamp = ?,
                        market_cap = ?, market_id = ?, inverted = ?, real_sol_reserves = ?,
                        real_token_reserves = ?, livestream_ban_expiry = ?, last_reply = ?,
                        reply_count = ?, is_banned = ?, is_currently_live = ?, initialized = ?,
                        video_uri = ?, pump_swap_pool = ?, ath_market_cap = ?,
                        ath_market_cap_timestamp = ?, banner_uri = ?, hide_banner = ?,
                        livestream_downrank_score = ?, last_updated_pumpfun = ?, updated_at = ?
                    WHERE address = ?
                """, (
                    pump_data.get('name'), pump_data.get('symbol'), pump_data.get('description'),
                    pump_data.get('image_uri'), pump_data.get('complete', False),
                    pump_data.get('usd_market_cap'),
                    pump_data.get('bonding_curve_progress'), pump_data.get('twitter'),
                    pump_data.get('telegram'), pump_data.get('website'), pump_data.get('total_supply'),
                    pump_data.get('nsfw', False), pump_data.get('bonding_curve'),
                    ts_to_iso(pump_data.get('king_of_the_hill_timestamp')), pump_data.get('metadata_uri'),
                    pump_data.get('associated_bonding_curve'), pump_data.get('raydium_pool'),
                    pump_data.get('virtual_sol_reserves'), pump_data.get('virtual_token_reserves'),
                    pump_data.get('hidden'), pump_data.get('show_name'),
                    ts_to_iso(pump_data.get('last_trade_timestamp')), pump_data.get('market_cap'),
                    pump_data.get('market_id'), pump_data.get('inverted'),
                    pump_data.get('real_sol_reserves'), pump_data.get('real_token_reserves'),
                    ts_to_iso(pump_data.get('livestream_ban_expiry')), ts_to_iso(pump_data.get('last_reply')),
                    pump_data.get('reply_count'), pump_data.get('is_banned'),
                    pump_data.get('is_currently_live'), pump_data.get('initialized'),
                    pump_data.get('video_uri'),
                    pump_data.get('pump_swap_pool'), pump_data.get('ath_market_cap'),
                    ts_to_iso(pump_data.get('ath_market_cap_timestamp')), pump_data.get('banner_uri'),
                    pump_data.get('hide_banner'), pump_data.get('livestream_downrank_score'),
                    datetime.now().isoformat(),
                    datetime.now().isoformat(),
                    token_address
                ))
                conn.commit()
                logger.debug(f"Enriched token data comprehensively for {token_address}")
                return True
        except Exception as e:
            logger.error(f"Error updating token {token_address} with comprehensive pump.fun data: {e}", exc_info=True)
            return False

    def upsert_rugcheck_report(self, token_address: str, report: Dict[str, Any]) -> bool:
        """Insère ou met à jour un rapport de rugcheck."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                score = report.get('score_normalised')
                is_rugged = report.get('rugged')
                risks = json.dumps(report.get('risks', []))
                top_holders = json.dumps(report.get('topHolders', []))
                raw_report = json.dumps(report)
                
                cursor.execute("""
                    INSERT OR REPLACE INTO rugcheck_reports 
                    (token_address, score, is_rugged, risks, top_holders, raw_report, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    token_address, score, is_rugged, risks, top_holders, raw_report,
                    datetime.now().isoformat()
                ))
                conn.commit()
                logger.debug(f"Upserted rugcheck report for {token_address}")
                return True
        except Exception as e:
            logger.error(f"Error upserting rugcheck report for {token_address}: {e}")
            return False

    def get_updated_tokens_counts(self) -> Dict[str, int]:
        """Récupère le nombre de tokens mis à jour récemment."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                intervals = {
                    "5m": "5 minutes",
                    "30m": "30 minutes",
                    "1h": "1 hour",
                    "6h": "6 hours"
                }
                
                counts = {}
                
                for key, interval_str in intervals.items():
                    query = f"SELECT count(*) FROM pump_tokens WHERE datetime(last_updated_pumpfun) >= datetime('now', 'localtime', '-{interval_str}');"
                    cursor.execute(query)
                    count = cursor.fetchone()[0]
                    counts[key] = count
                    
                return counts
        except Exception as e:
            logger.error(f"Error getting updated tokens counts: {e}", exc_info=True)
            return {}

    def get_new_tokens_count(self, since: datetime) -> int:
        """Counts new tokens since a given datetime."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM pump_tokens WHERE row_created_at >= ?", (since.isoformat(),))
                return cursor.fetchone()[0]
        except Exception as e:
            self.logger.error(f"Error counting new tokens: {e}")
            return 0

    def get_new_early_adopters_count(self, since: datetime) -> int:
        """Counts new early adopters since a given datetime."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # Assuming 'last_activity' is updated when an adopter is created or becomes "early"
                cursor.execute("SELECT COUNT(*) FROM early_adopters WHERE last_activity >= ?", (since.isoformat(),))
                return cursor.fetchone()[0]
        except Exception as e:
            self.logger.error(f"Error counting new early adopters: {e}")
            return 0

    def get_pump_tokens_updates_count(self, since: datetime) -> int:
        """Counts updated pump_tokens since a given datetime."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM pump_tokens WHERE last_updated_pumpfun >= ?", (since.isoformat(),))
                return cursor.fetchone()[0]
        except Exception as e:
            self.logger.error(f"Error counting pump_tokens updates: {e}")
            return 0

# Instance globale
db = DatabaseManager()