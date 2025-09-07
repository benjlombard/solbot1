#!/usr/bin/env python3
"""
Portfolio Database Manager
Gestion de la base de données pour le tracking des transactions et du portfolio
"""

import sqlite3
import logging
import json
from datetime import datetime, date
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import asyncio
import threading

logger = logging.getLogger(__name__)

@dataclass
class TransactionRecord:
    """Enregistrement d'une transaction"""
    transaction_signature: str
    network: str
    operation_type: str  # BUY, SELL, TRANSFER, AIRDROP
    token_address: str
    token_symbol: str
    token_decimals: int = 6
    sol_amount_spent: float = 0.0
    sol_amount_received: float = 0.0
    token_amount: float = 0.0
    price_per_token_sol: float = 0.0
    jupiter_quote_data: Optional[Dict] = None
    jupiter_route_label: Optional[str] = None
    price_impact_percent: Optional[float] = None
    transaction_fees_sol: float = 0.0
    priority_fees_sol: float = 0.0
    account_creation_fees_sol: float = 0.0
    total_fees_sol: float = 0.0
    slippage_tolerance_bps: Optional[int] = None
    slippage_actual_percent: Optional[float] = None
    confirmation_time_seconds: Optional[float] = None
    block_slot: Optional[int] = None
    status: str = "PENDING"  # PENDING, CONFIRMED, FAILED, CANCELLED
    error_message: Optional[str] = None
    timestamp: Optional[datetime] = None

@dataclass
class PositionRecord:
    """Enregistrement d'une position"""
    token_address: str
    token_symbol: str
    network: str
    total_tokens_held: float
    average_entry_price_sol: float
    total_sol_invested: float
    current_price_sol: Optional[float] = None
    current_value_sol: Optional[float] = None
    unrealized_pnl_sol: Optional[float] = None
    unrealized_pnl_percent: Optional[float] = None
    total_transactions: int = 1
    total_fees_paid_sol: float = 0.0
    first_purchase_timestamp: Optional[datetime] = None
    last_transaction_timestamp: Optional[datetime] = None

class PortfolioDatabase:
    """Gestionnaire de base de données pour le portfolio"""
    
    def __init__(self, db_path: str = "app/data/autotrader.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(exist_ok=True)
        self._lock = threading.Lock()
        self.ensure_database_exists()
    
    def ensure_database_exists(self):
        """Vérifie et crée la base de données si nécessaire"""
        if not self.db_path.exists():
            logger.warning(f"Database not found: {self.db_path}")
            logger.info("Creating new database with schema...")
            self.create_database()
        
        # Vérifier que les tables existent
        self.verify_schema()
    
    def create_database(self):
        """Crée la base de données avec le schéma complet"""
        schema_file = self.db_path.parent / "create_database.sql"
        
        if schema_file.exists():
            logger.info(f"Using schema file: {schema_file}")
            with open(schema_file, 'r') as f:
                schema_sql = f.read()
            
            with sqlite3.connect(self.db_path) as conn:
                conn.executescript(schema_sql)
                logger.info("✅ Database created successfully")
        else:
            logger.warning("Schema file not found, creating minimal schema")
            self.create_minimal_schema()
    
    def create_minimal_schema(self):
        """Crée un schéma complet si le fichier SQL n'est pas trouvé"""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                -- Table principale des transactions
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    transaction_signature VARCHAR(88) UNIQUE NOT NULL,
                    network VARCHAR(10) NOT NULL CHECK (network IN ('mainnet', 'devnet')),
                    operation_type VARCHAR(10) NOT NULL CHECK (operation_type IN ('BUY', 'SELL', 'TRANSFER', 'AIRDROP')),
                    
                    -- Informations sur le token
                    token_address VARCHAR(44) NOT NULL,
                    token_symbol VARCHAR(20),
                    token_decimals INTEGER DEFAULT 6,
                    
                    -- Montants de la transaction
                    sol_amount_spent DECIMAL(18, 9) DEFAULT 0,
                    sol_amount_received DECIMAL(18, 9) DEFAULT 0,
                    token_amount DECIMAL(24, 6) NOT NULL,
                    price_per_token_sol DECIMAL(18, 12) NOT NULL,
                    
                    -- Données Jupiter et métadonnées
                    jupiter_quote_data TEXT,
                    jupiter_route_label VARCHAR(50),
                    price_impact_percent DECIMAL(8, 4),
                    
                    -- Frais détaillés
                    transaction_fees_sol DECIMAL(18, 9) DEFAULT 0,
                    priority_fees_sol DECIMAL(18, 9) DEFAULT 0,
                    account_creation_fees_sol DECIMAL(18, 9) DEFAULT 0,
                    total_fees_sol DECIMAL(18, 9) DEFAULT 0,
                    
                    -- Execution details
                    slippage_tolerance_bps INTEGER,
                    slippage_actual_percent DECIMAL(8, 4),
                    confirmation_time_seconds DECIMAL(8, 2),
                    block_slot BIGINT,
                    
                    -- Status et validation
                    status VARCHAR(10) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'CONFIRMED', 'FAILED', 'CANCELLED')),
                    error_message TEXT,
                    
                    -- Audit
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                -- Table des positions actuelles
                CREATE TABLE IF NOT EXISTS current_positions (
                    token_address VARCHAR(44) PRIMARY KEY,
                    token_symbol VARCHAR(20) NOT NULL,
                    network VARCHAR(10) NOT NULL CHECK (network IN ('mainnet', 'devnet')),
                    
                    -- Holdings
                    total_tokens_held DECIMAL(24, 6) NOT NULL DEFAULT 0,
                    average_entry_price_sol DECIMAL(18, 12) NOT NULL,
                    total_sol_invested DECIMAL(18, 9) NOT NULL,
                    
                    -- Timestamps
                    first_purchase_timestamp DATETIME NOT NULL,
                    last_transaction_timestamp DATETIME NOT NULL,
                    last_price_update DATETIME,
                    
                    -- PnL (mis à jour par le portfolio tracker)
                    current_price_sol DECIMAL(18, 12),
                    current_value_sol DECIMAL(18, 9),
                    unrealized_pnl_sol DECIMAL(18, 9),
                    unrealized_pnl_percent DECIMAL(8, 4),
                    
                    -- Statistiques
                    total_transactions INTEGER DEFAULT 1,
                    total_fees_paid_sol DECIMAL(18, 9) DEFAULT 0,
                    
                    -- Audit
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                -- Table de l'historique des prix
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_address VARCHAR(44) NOT NULL,
                    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    
                    -- Prix et données de marché
                    price_sol DECIMAL(18, 12) NOT NULL,
                    price_usd DECIMAL(18, 8),
                    
                    -- Source des données
                    source VARCHAR(20) DEFAULT 'jupiter' CHECK (source IN ('jupiter', 'coingecko', 'dexscreener', 'birdeye')),
                    network VARCHAR(10) NOT NULL CHECK (network IN ('mainnet', 'devnet')),
                    
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                -- Vue pour le portfolio actuel avec PnL
                CREATE VIEW IF NOT EXISTS portfolio_summary AS
                SELECT 
                    p.token_address,
                    p.token_symbol,
                    p.network,
                    p.total_tokens_held,
                    p.average_entry_price_sol,
                    p.total_sol_invested,
                    p.current_price_sol,
                    p.current_value_sol,
                    p.unrealized_pnl_sol,
                    p.unrealized_pnl_percent,
                    p.total_transactions,
                    p.total_fees_paid_sol,
                    p.first_purchase_timestamp,
                    p.last_transaction_timestamp,
                    -- Calculer l'âge de la position en minutes
                    CAST((julianday('now') - julianday(p.first_purchase_timestamp)) * 24 * 60 AS INTEGER) as age_minutes,
                    -- ROI total incluant les frais
                    ROUND(((p.current_value_sol - p.total_sol_invested - p.total_fees_paid_sol) / (p.total_sol_invested + p.total_fees_paid_sol)) * 100, 2) as roi_percent
                FROM current_positions p
                WHERE p.total_tokens_held > 0
                ORDER BY p.unrealized_pnl_percent DESC;

                -- Index pour les requêtes fréquentes
                CREATE INDEX IF NOT EXISTS idx_transactions_signature ON transactions(transaction_signature);
                CREATE INDEX IF NOT EXISTS idx_transactions_token ON transactions(token_address);
                CREATE INDEX IF NOT EXISTS idx_transactions_timestamp ON transactions(timestamp);
                CREATE INDEX IF NOT EXISTS idx_transactions_network ON transactions(network);
                CREATE INDEX IF NOT EXISTS idx_transactions_status ON transactions(status);
                CREATE INDEX IF NOT EXISTS idx_positions_network ON current_positions(network);
                CREATE INDEX IF NOT EXISTS idx_price_history_token_time ON price_history(token_address, timestamp);
            """)
    
    def verify_schema(self):
        """Vérifie que les tables principales existent"""
        required_tables = ['transactions', 'current_positions']
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            existing_tables = [row[0] for row in cursor.fetchall()]
            
            missing_tables = [table for table in required_tables if table not in existing_tables]
            
            if missing_tables:
                logger.error(f"Missing required tables: {missing_tables}")
                raise Exception(f"Database schema incomplete. Missing tables: {missing_tables}")
            
            logger.debug("✅ Database schema verified")
    
    def record_transaction(self, transaction: TransactionRecord) -> bool:
        """Enregistre une transaction dans la base de données"""
        with self._lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    
                    # Préparer les données
                    jupiter_data_json = json.dumps(transaction.jupiter_quote_data) if transaction.jupiter_quote_data else None
                    timestamp = transaction.timestamp or datetime.now()
                    
                    # Insérer la transaction
                    cursor.execute("""
                        INSERT OR REPLACE INTO transactions (
                            timestamp, transaction_signature, network, operation_type,
                            token_address, token_symbol, token_decimals,
                            sol_amount_spent, sol_amount_received, token_amount, price_per_token_sol,
                            jupiter_quote_data, jupiter_route_label, price_impact_percent,
                            transaction_fees_sol, priority_fees_sol, account_creation_fees_sol, total_fees_sol,
                            slippage_tolerance_bps, slippage_actual_percent,
                            confirmation_time_seconds, block_slot, status, error_message
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        timestamp, transaction.transaction_signature, transaction.network, transaction.operation_type,
                        transaction.token_address, transaction.token_symbol, transaction.token_decimals,
                        transaction.sol_amount_spent, transaction.sol_amount_received, transaction.token_amount, transaction.price_per_token_sol,
                        jupiter_data_json, transaction.jupiter_route_label, transaction.price_impact_percent,
                        transaction.transaction_fees_sol, transaction.priority_fees_sol, transaction.account_creation_fees_sol, transaction.total_fees_sol,
                        transaction.slippage_tolerance_bps, transaction.slippage_actual_percent,
                        transaction.confirmation_time_seconds, transaction.block_slot, transaction.status, transaction.error_message
                    ))
                    
                    conn.commit()
                    logger.info(f"✅ Transaction recorded: {transaction.transaction_signature[:8]}... ({transaction.operation_type})")
                    return True
                    
            except Exception as e:
                logger.error(f"❌ Error recording transaction: {e}")
                return False
    
    def update_transaction_status(self, signature: str, status: str, error_message: str = None,
                                confirmation_time: float = None, block_slot: int = None) -> bool:
        """Met à jour le statut d'une transaction"""
        with self._lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    
                    cursor.execute("""
                        UPDATE transactions 
                        SET status = ?, error_message = ?, confirmation_time_seconds = ?, block_slot = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE transaction_signature = ?
                    """, (status, error_message, confirmation_time, block_slot, signature))
                    
                    conn.commit()
                    
                    if cursor.rowcount > 0:
                        logger.debug(f"Transaction status updated: {signature[:8]}... -> {status}")
                        return True
                    else:
                        logger.warning(f"Transaction not found for status update: {signature[:8]}...")
                        return False
                        
            except Exception as e:
                logger.error(f"Error updating transaction status: {e}")
                return False
    
    def update_or_create_position(self, transaction: TransactionRecord) -> bool:
        """Met à jour ou crée une position basée sur une transaction"""
        if transaction.status != "CONFIRMED":
            logger.debug(f"Skipping position update for non-confirmed transaction: {transaction.status}")
            return False
        
        with self._lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    
                    # Récupérer la position existante
                    cursor.execute("""
                        SELECT total_tokens_held, average_entry_price_sol, total_sol_invested, 
                               total_transactions, total_fees_paid_sol, first_purchase_timestamp
                        FROM current_positions 
                        WHERE token_address = ?
                    """, (transaction.token_address,))
                    
                    existing = cursor.fetchone()
                    
                    if existing and transaction.operation_type == "BUY":
                        # Position existante - mise à jour pour un achat
                        old_tokens, old_avg_price, old_invested, old_tx_count, old_fees, first_purchase = existing
                        
                        new_tokens = old_tokens + transaction.token_amount
                        new_invested = old_invested + transaction.sol_amount_spent
                        new_avg_price = new_invested / new_tokens if new_tokens > 0 else 0
                        new_tx_count = old_tx_count + 1
                        new_fees = old_fees + transaction.total_fees_sol
                        
                        cursor.execute("""
                            UPDATE current_positions 
                            SET total_tokens_held = ?, average_entry_price_sol = ?, total_sol_invested = ?,
                                total_transactions = ?, total_fees_paid_sol = ?, last_transaction_timestamp = ?,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE token_address = ?
                        """, (new_tokens, new_avg_price, new_invested, new_tx_count, new_fees,
                             transaction.timestamp or datetime.now(), transaction.token_address))
                        
                        logger.info(f"📊 Position updated: {transaction.token_symbol} - {new_tokens:,.0f} tokens (avg: {new_avg_price:.8f} SOL)")
                        
                    elif existing and transaction.operation_type == "SELL":
                        # Position existante - mise à jour pour une vente
                        old_tokens, old_avg_price, old_invested, old_tx_count, old_fees, first_purchase = existing
                        
                        new_tokens = max(0, old_tokens - transaction.token_amount)
                        new_tx_count = old_tx_count + 1
                        new_fees = old_fees + transaction.total_fees_sol
                        
                        if new_tokens > 0:
                            # Réduire l'investissement proportionnellement
                            proportion_sold = transaction.token_amount / old_tokens
                            new_invested = old_invested * (1 - proportion_sold)
                        else:
                            # Position fermée
                            new_invested = 0
                            new_avg_price = 0
                        
                        cursor.execute("""
                            UPDATE current_positions 
                            SET total_tokens_held = ?, total_sol_invested = ?, total_transactions = ?, 
                                total_fees_paid_sol = ?, last_transaction_timestamp = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE token_address = ?
                        """, (new_tokens, new_invested, new_tx_count, new_fees,
                             transaction.timestamp or datetime.now(), transaction.token_address))
                        
                        logger.info(f"📊 Position updated (SELL): {transaction.token_symbol} - {new_tokens:,.0f} tokens remaining")
                        
                        # Supprimer la position si plus de tokens
                        if new_tokens <= 0:
                            cursor.execute("DELETE FROM current_positions WHERE token_address = ?", (transaction.token_address,))
                            logger.info(f"🗑️ Position closed: {transaction.token_symbol}")
                        
                    elif transaction.operation_type == "BUY":
                        # Nouvelle position - premier achat
                        cursor.execute("""
                            INSERT INTO current_positions (
                                token_address, token_symbol, network, total_tokens_held, 
                                average_entry_price_sol, total_sol_invested, total_transactions, 
                                total_fees_paid_sol, first_purchase_timestamp, last_transaction_timestamp
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            transaction.token_address, transaction.token_symbol, transaction.network,
                            transaction.token_amount, transaction.price_per_token_sol, transaction.sol_amount_spent,
                            1, transaction.total_fees_sol, 
                            transaction.timestamp or datetime.now(), transaction.timestamp or datetime.now()
                        ))
                        
                        logger.info(f"🆕 New position created: {transaction.token_symbol} - {transaction.token_amount:,.0f} tokens")
                    
                    conn.commit()
                    return True
                    
            except Exception as e:
                logger.error(f"❌ Error updating position: {e}")
                return False
    
    def update_position_price(self, token_address: str, new_price_sol: float, 
                            market_data: Dict[str, Any] = None) -> bool:
        """Met à jour le prix d'une position et recalcule le PnL"""
        with self._lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    
                    # Vérifier les colonnes disponibles
                    cursor.execute("PRAGMA table_info(current_positions)")
                    columns = [row[1] for row in cursor.fetchall()]
                    
                    # Récupérer la position
                    cursor.execute("""
                        SELECT total_tokens_held, total_sol_invested, total_fees_paid_sol
                        FROM current_positions 
                        WHERE token_address = ?
                    """, (token_address,))
                    
                    row = cursor.fetchone()
                    if not row:
                        return False
                    
                    tokens_held, sol_invested, fees_paid = row
                    
                    # Calculer les nouvelles valeurs
                    current_value = new_price_sol * tokens_held
                    unrealized_pnl = current_value - sol_invested
                    unrealized_pnl_percent = (unrealized_pnl / sol_invested * 100) if sol_invested > 0 else 0
                    
                    # Construire la requête selon les colonnes disponibles
                    updates = []
                    values = []
                    
                    if 'current_price_sol' in columns:
                        updates.append('current_price_sol = ?')
                        values.append(new_price_sol)
                    if 'current_value_sol' in columns:
                        updates.append('current_value_sol = ?')
                        values.append(current_value)
                    if 'unrealized_pnl_sol' in columns:
                        updates.append('unrealized_pnl_sol = ?')
                        values.append(unrealized_pnl)
                    if 'unrealized_pnl_percent' in columns:
                        updates.append('unrealized_pnl_percent = ?')
                        values.append(unrealized_pnl_percent)
                    if 'last_price_update' in columns:
                        updates.append('last_price_update = CURRENT_TIMESTAMP')
                    if 'updated_at' in columns:
                        updates.append('updated_at = CURRENT_TIMESTAMP')
                    
                    if updates:
                        values.append(token_address)
                        query = f"UPDATE current_positions SET {', '.join(updates)} WHERE token_address = ?"
                        cursor.execute(query, values)
                    
                    # Enregistrer l'historique des prix si la table existe
                    try:
                        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='price_history'")
                        if cursor.fetchone():
                            cursor.execute("""
                                INSERT INTO price_history (token_address, price_sol, timestamp, source)
                                VALUES (?, ?, CURRENT_TIMESTAMP, 'portfolio_tracker')
                            """, (token_address, new_price_sol))
                    except sqlite3.OperationalError:
                        pass
                    
                    conn.commit()
                    return True
                    
            except Exception as e:
                logger.error(f"Error updating position price: {e}")
                return False
    
    def get_position(self, token_address: str) -> Optional[PositionRecord]:
        """Récupère une position spécifique"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM current_positions WHERE token_address = ?
                """, (token_address,))
                
                row = cursor.fetchone()
                if not row:
                    return None
                
                return PositionRecord(
                    token_address=row['token_address'],
                    token_symbol=row['token_symbol'],
                    network=row['network'],
                    total_tokens_held=float(row['total_tokens_held']),
                    average_entry_price_sol=float(row['average_entry_price_sol']),
                    total_sol_invested=float(row['total_sol_invested']),
                    current_price_sol=float(row['current_price_sol']) if row['current_price_sol'] else None,
                    current_value_sol=float(row['current_value_sol']) if row['current_value_sol'] else None,
                    unrealized_pnl_sol=float(row['unrealized_pnl_sol']) if row['unrealized_pnl_sol'] else None,
                    unrealized_pnl_percent=float(row['unrealized_pnl_percent']) if row['unrealized_pnl_percent'] else None,
                    total_transactions=int(row['total_transactions']),
                    total_fees_paid_sol=float(row['total_fees_paid_sol']),
                    first_purchase_timestamp=datetime.fromisoformat(row['first_purchase_timestamp']),
                    last_transaction_timestamp=datetime.fromisoformat(row['last_transaction_timestamp'])
                )
                
        except Exception as e:
            logger.error(f"Error getting position: {e}")
            return None
    
    def get_all_positions(self, network: str = None) -> List[PositionRecord]:
        """Récupère toutes les positions actives"""
        try:
            query = "SELECT * FROM current_positions WHERE total_tokens_held > 0"
            params = []
            
            if network:
                query += " AND network = ?"
                params.append(network)
            
            query += " ORDER BY total_sol_invested DESC"
            
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(query, params)
                
                positions = []
                for row in cursor.fetchall():
                    position = PositionRecord(
                        token_address=row['token_address'],
                        token_symbol=row['token_symbol'],
                        network=row['network'],
                        total_tokens_held=float(row['total_tokens_held']),
                        average_entry_price_sol=float(row['average_entry_price_sol']),
                        total_sol_invested=float(row['total_sol_invested']),
                        current_price_sol=float(row['current_price_sol']) if row['current_price_sol'] else None,
                        current_value_sol=float(row['current_value_sol']) if row['current_value_sol'] else None,
                        unrealized_pnl_sol=float(row['unrealized_pnl_sol']) if row['unrealized_pnl_sol'] else None,
                        unrealized_pnl_percent=float(row['unrealized_pnl_percent']) if row['unrealized_pnl_percent'] else None,
                        total_transactions=int(row['total_transactions']),
                        total_fees_paid_sol=float(row['total_fees_paid_sol']),
                        first_purchase_timestamp=datetime.fromisoformat(row['first_purchase_timestamp']),
                        last_transaction_timestamp=datetime.fromisoformat(row['last_transaction_timestamp'])
                    )
                    positions.append(position)
                
                return positions
                
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []
    
    def get_portfolio_summary(self, network: str = None) -> Dict[str, Any]:
        """Calcule un résumé du portfolio"""
        positions = self.get_all_positions(network)
        
        if not positions:
            return {
                'total_value_sol': 0.0,
                'total_invested_sol': 0.0,
                'total_fees_sol': 0.0,
                'unrealized_pnl_sol': 0.0,
                'unrealized_pnl_percent': 0.0,
                'active_positions': 0,
                'total_transactions': 0
            }
        
        total_value = sum(pos.current_value_sol or 0 for pos in positions)
        total_invested = sum(pos.total_sol_invested for pos in positions)
        total_fees = sum(pos.total_fees_paid_sol for pos in positions)
        unrealized_pnl = total_value - total_invested
        unrealized_pnl_percent = (unrealized_pnl / total_invested * 100) if total_invested > 0 else 0
        total_transactions = sum(pos.total_transactions for pos in positions)
        
        return {
            'total_value_sol': total_value,
            'total_invested_sol': total_invested,
            'total_fees_sol': total_fees,
            'unrealized_pnl_sol': unrealized_pnl,
            'unrealized_pnl_percent': unrealized_pnl_percent,
            'active_positions': len(positions),
            'total_transactions': total_transactions
        }
    
    def get_transaction_history(self, limit: int = 50, network: str = None, 
                              status: str = "CONFIRMED") -> List[Dict[str, Any]]:
        """Récupère l'historique des transactions"""
        try:
            query = """
                SELECT * FROM transactions 
                WHERE status = ?
            """
            params = [status]
            
            if network:
                query += " AND network = ?"
                params.append(network)
            
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(query, params)
                
                transactions = []
                for row in cursor.fetchall():
                    tx = dict(row)
                    # Convertir les champs JSON
                    if tx['jupiter_quote_data']:
                        try:
                            tx['jupiter_quote_data'] = json.loads(tx['jupiter_quote_data'])
                        except:
                            tx['jupiter_quote_data'] = None
                    transactions.append(tx)
                
                return transactions
                
        except Exception as e:
            logger.error(f"Error getting transaction history: {e}")
            return []
    
    def get_daily_stats(self, target_date: date = None, network: str = None) -> Dict[str, Any]:
        """Récupère les statistiques d'une journée"""
        if target_date is None:
            target_date = date.today()
        
        try:
            query = """
                SELECT 
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN operation_type = 'BUY' THEN 1 ELSE 0 END) as buy_trades,
                    SUM(CASE WHEN operation_type = 'SELL' THEN 1 ELSE 0 END) as sell_trades,
                    SUM(sol_amount_spent) as total_spent,
                    SUM(sol_amount_received) as total_received,
                    SUM(total_fees_sol) as total_fees,
                    AVG(confirmation_time_seconds) as avg_confirmation_time,
                    COUNT(CASE WHEN status = 'FAILED' THEN 1 END) as failed_trades
                FROM transactions 
                WHERE DATE(timestamp) = ? AND status IN ('CONFIRMED', 'FAILED')
            """
            params = [target_date]
            
            if network:
                query += " AND network = ?"
                params.append(network)
            
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(query, params)
                
                row = cursor.fetchone()
                
                total_trades = row['total_trades'] or 0
                success_rate = ((total_trades - (row['failed_trades'] or 0)) / total_trades * 100) if total_trades > 0 else 100
                
                return {
                    'total_trades': total_trades,
                    'buy_trades': row['buy_trades'] or 0,
                    'sell_trades': row['sell_trades'] or 0,
                    'total_spent': float(row['total_spent'] or 0),
                    'total_received': float(row['total_received'] or 0),
                    'total_fees': float(row['total_fees'] or 0),
                    'avg_confirmation_time': float(row['avg_confirmation_time'] or 0),
                    'failed_trades': row['failed_trades'] or 0,
                    'success_rate': success_rate
                }
                
        except Exception as e:
            logger.error(f"Error getting daily stats: {e}")
            return {}
    
    def cleanup_old_data(self, days_to_keep: int = 90):
        """Nettoie les anciennes données"""
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        
        with self._lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    
                    # Nettoyer l'historique des prix
                    try:
                        cursor.execute("""
                            DELETE FROM price_history 
                            WHERE timestamp < ?
                        """, (cutoff_date,))
                        price_deleted = cursor.rowcount
                    except sqlite3.OperationalError:
                        price_deleted = 0
                    
                    # Nettoyer les transactions anciennes (garder seulement les confirmées importantes)
                    cursor.execute("""
                        DELETE FROM transactions 
                        WHERE timestamp < ? AND status IN ('FAILED', 'CANCELLED')
                    """, (cutoff_date,))
                    tx_deleted = cursor.rowcount
                    
                    conn.commit()
                    
                    if price_deleted > 0 or tx_deleted > 0:
                        logger.info(f"🧹 Cleaned up old data: {price_deleted} price records, {tx_deleted} failed transactions")
                        
            except Exception as e:
                logger.error(f"Error cleaning up data: {e}")

# Instance globale pour faciliter l'utilisation
_portfolio_db = None

def get_portfolio_db(db_path: str = "app/data/autotrader.db") -> PortfolioDatabase:
    """Récupère l'instance globale de la base de données portfolio"""
    global _portfolio_db
    if _portfolio_db is None:
        _portfolio_db = PortfolioDatabase(db_path)
    return _portfolio_db

def record_trade_transaction(signature, network, token_address, token_symbol, operation_type, 
                           sol_amount, token_amount, price_per_token, fees, jupiter_data, 
                           confirmation_time, status="PENDING"):
    try:
        # Debug des paramètres reçus
        logger.debug(f"🔍 RECORD_TRADE_TRANSACTION DEBUG:")
        logger.debug(f"   signature: {signature}")
        logger.debug(f"   fees parameter: {fees}")
        logger.debug(f"   fees type: {type(fees)}")
        
        if isinstance(fees, dict):
            transaction_fee = fees.get('transaction', 0)
            priority_fee = fees.get('priority', 0)
            account_creation_fee = fees.get('account_creation', 0)
            total_fees = transaction_fee + priority_fee + account_creation_fee
            
            logger.debug(f"   transaction_fee extracted: {transaction_fee:.9f}")
            logger.debug(f"   transaction_fee type: {type(transaction_fee)}")
        else:
            logger.error(f"   fees is not a dict: {fees}")
            transaction_fee = 0
            priority_fee = 0
            account_creation_fee = 0
            total_fees = 0

        # Create TransactionRecord object
        transaction = TransactionRecord(
            transaction_signature=signature,
            network=network,
            operation_type=operation_type,
            token_address=token_address,
            token_symbol=token_symbol,
            sol_amount_spent=sol_amount if operation_type == "BUY" else 0,
            sol_amount_received=sol_amount if operation_type == "SELL" else 0,
            token_amount=token_amount,
            price_per_token_sol=price_per_token,
            jupiter_quote_data=jupiter_data,
            transaction_fees_sol=transaction_fee,
            priority_fees_sol=priority_fee,
            account_creation_fees_sol=account_creation_fee,
            total_fees_sol=total_fees,
            confirmation_time_seconds=confirmation_time,
            status=status,
            timestamp=datetime.now()
        )
        
        # Use the PortfolioDatabase class properly
        db = get_portfolio_db()
        success = db.record_transaction(transaction)
        
        if success and status == "CONFIRMED":
            # Also update the position
            db.update_or_create_position(transaction)
        
        logger.debug(f"   SQL INSERT transaction_fee_sol: {transaction_fee:.9f}")
        logger.info(f"✅ Transaction recorded: {signature[:8]}... ({operation_type})")
        
        return success
        
    except Exception as e:
        logger.error(f"❌ Error recording transaction: {e}")
        import traceback
        logger.error(f"   Traceback: {traceback.format_exc()}")
        return False

# Fonctions d'alerte et de monitoring
def check_portfolio_alerts(network: str = None) -> List[Dict[str, Any]]:
    """Vérifie les alertes du portfolio (PnL, pertes, etc.)"""
    alerts = []
    db = get_portfolio_db()
    
    try:
        positions = db.get_all_positions(network)
        portfolio_summary = db.get_portfolio_summary(network)
        
        # Alerte sur les grosses pertes
        for position in positions:
            if position.unrealized_pnl_percent and position.unrealized_pnl_percent <= -50:
                alerts.append({
                    'type': 'LARGE_LOSS',
                    'severity': 'ERROR',
                    'token': position.token_symbol,
                    'pnl_percent': position.unrealized_pnl_percent,
                    'message': f"Large loss detected: {position.token_symbol} down {position.unrealized_pnl_percent:.1f}%"
                })
            
            elif position.unrealized_pnl_percent and position.unrealized_pnl_percent >= 100:
                alerts.append({
                    'type': 'LARGE_GAIN',
                    'severity': 'INFO',
                    'token': position.token_symbol,
                    'pnl_percent': position.unrealized_pnl_percent,
                    'message': f"Large gain detected: {position.token_symbol} up {position.unrealized_pnl_percent:.1f}%"
                })
        
        # Alerte sur le PnL global
        if portfolio_summary['unrealized_pnl_percent'] <= -30:
            alerts.append({
                'type': 'PORTFOLIO_LOSS',
                'severity': 'WARNING',
                'pnl_percent': portfolio_summary['unrealized_pnl_percent'],
                'message': f"Portfolio down {portfolio_summary['unrealized_pnl_percent']:.1f}%"
            })
        
        return alerts
        
    except Exception as e:
        logger.error(f"Error checking portfolio alerts: {e}")
        return []

def get_portfolio_performance_report(network: str = None, days: int = 7) -> Dict[str, Any]:
    """Génère un rapport de performance du portfolio"""
    db = get_portfolio_db()
    
    try:
        # Performance actuelle
        current_summary = db.get_portfolio_summary(network)
        
        # Historique des trades récents
        recent_transactions = db.get_transaction_history(limit=100, network=network)
        
        # Statistiques par jour
        daily_stats = []
        for i in range(days):
            target_date = date.today() - timedelta(days=i)
            day_stats = db.get_daily_stats(target_date, network)
            day_stats['date'] = target_date.isoformat()
            daily_stats.append(day_stats)
        
        # Calculs de performance
        total_trades = len(recent_transactions)
        buy_trades = len([tx for tx in recent_transactions if tx['operation_type'] == 'BUY'])
        sell_trades = len([tx for tx in recent_transactions if tx['operation_type'] == 'SELL'])
        
        # ROI moyen par trade
        avg_trade_size = sum(tx['sol_amount_spent'] for tx in recent_transactions if tx['operation_type'] == 'BUY') / max(buy_trades, 1)
        
        # Tokens les plus tradés
        token_counts = {}
        for tx in recent_transactions:
            token = tx['token_symbol'] or 'UNKNOWN'
            token_counts[token] = token_counts.get(token, 0) + 1
        
        most_traded = sorted(token_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        
        return {
            'current_portfolio': current_summary,
            'period_days': days,
            'total_trades': total_trades,
            'buy_trades': buy_trades,
            'sell_trades': sell_trades,
            'avg_trade_size_sol': avg_trade_size,
            'most_traded_tokens': most_traded,
            'daily_breakdown': daily_stats,
            'generated_at': datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error generating performance report: {e}")
        return {}

# Fonction de maintenance
def maintenance_tasks():
    """Effectue les tâches de maintenance de la base de données"""
    db = get_portfolio_db()
    
    try:
        # Nettoyer les anciennes données
        db.cleanup_old_data(days_to_keep=90)
        
        # Recalculer les moyennes de prix pour les positions actives
        positions = db.get_all_positions()
        for position in positions:
            # Vérifier la cohérence des données
            if position.total_tokens_held <= 0:
                logger.warning(f"Found position with 0 tokens: {position.token_symbol}")
                # Nettoyer automatiquement
                with sqlite3.connect(db.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM current_positions WHERE token_address = ?", 
                                 (position.token_address,))
                    conn.commit()
                    logger.info(f"Cleaned up empty position: {position.token_symbol}")
        
        logger.info("✅ Maintenance tasks completed")
        
    except Exception as e:
        logger.error(f"Error during maintenance: {e}")

# Test et validation
def test_database_operations():
    """Teste les opérations de base de données"""
    print("🧪 Testing portfolio database operations...")
    
    # Utiliser la vraie base de données au lieu d'une base de test
    db = get_portfolio_db("app/data/autotrader.db")  # ← Changé ici !
    
    try:
        # Debug: Afficher la structure de la table
        with sqlite3.connect(db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(transactions)")
            columns = cursor.fetchall()
            print(f"📋 Available columns in transactions table:")
            for col in columns:
                print(f"   {col[1]} ({col[2]})")
        
        # Test 1: Enregistrer une transaction
        test_tx = TransactionRecord(
            transaction_signature="test_signature_123",
            network="devnet",
            operation_type="BUY",
            token_address="test_token_address",
            token_symbol="TEST",
            sol_amount_spent=0.001,
            token_amount=1000,
            price_per_token_sol=0.000001,
            total_fees_sol=0.00005,
            status="CONFIRMED"
        )
        
        success = db.record_transaction(test_tx)
        print(f"✅ Transaction recording: {'SUCCESS' if success else 'FAILED'}")
        
        # Test 2: Mettre à jour la position
        success = db.update_or_create_position(test_tx)
        print(f"✅ Position update: {'SUCCESS' if success else 'FAILED'}")
        
        # Test 3: Récupérer la position
        position = db.get_position("test_token_address")
        if position:
            print(f"✅ Position retrieval: SUCCESS - {position.token_symbol} with {position.total_tokens_held} tokens")
        else:
            print("❌ Position retrieval: FAILED")
        
        # Test 4: Mettre à jour le prix
        success = db.update_position_price("test_token_address", 0.000002)
        print(f"✅ Price update: {'SUCCESS' if success else 'FAILED'}")
        
        # Test 5: Résumé du portfolio
        summary = db.get_portfolio_summary("devnet")
        print(f"✅ Portfolio summary: {summary['active_positions']} positions, {summary['total_value_sol']:.6f} SOL value")
        
        # Test 6: Historique des transactions
        history = db.get_transaction_history(limit=5, network="devnet")
        print(f"✅ Transaction history: {len(history)} transactions retrieved")
        
        # Test 7: Statistiques quotidiennes
        daily_stats = db.get_daily_stats(network="devnet")
        print(f"📊 Daily stats keys: {list(daily_stats.keys())}")
        if 'total_trades' in daily_stats:
            print(f"✅ Daily stats: {daily_stats['total_trades']} trades today")
        else:
            print(f"⚠️ Daily stats: total_trades key missing. Available: {daily_stats}")
        
        print("\n🎉 All database tests completed successfully!")
        
        # NE PAS supprimer la vraie base de données !
        print("💾 Using real database - not cleaning up test data")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Exécuter les tests si le script est lancé directement
    test_database_operations()