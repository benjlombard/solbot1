#!/usr/bin/env python3
"""
Script d'initialisation de la base de données pour le trading
À ajouter dans scanner_wallet/core/database.py ou exécuter séparément
"""
import os
import sys
import sqlite3
from pathlib import Path

# Ajouter le répertoire parent au Python path pour les imports
current_dir = Path(__file__).parent
project_root = current_dir.parent
sys.path.insert(0, str(project_root))
def create_trading_tables_direct(db_path):
    """Crée les tables directement avec SQLite"""
    
    try:
        # Créer le répertoire s'il n'existe pas
        db_file = Path(db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            
            print(f"🔧 Connexion à la base de données: {db_path}")
            
            # Table des paramètres de trading utilisateur
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trading_settings (
                    wallet_address TEXT PRIMARY KEY,
                    default_slippage REAL DEFAULT 0.5,
                    max_trade_amount_sol REAL DEFAULT 10.0,
                    max_daily_volume_sol REAL DEFAULT 100.0,
                    auto_approve_under_sol REAL DEFAULT 1.0,
                    preferred_dex TEXT DEFAULT 'jupiter',
                    enable_mev_protection BOOLEAN DEFAULT 1,
                    priority_fee_lamports INTEGER DEFAULT 5000,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            """)
            print("✅ Table trading_settings créée")
            
            # Table des ordres de trade
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_orders (
                    order_id TEXT PRIMARY KEY,
                    wallet_address TEXT NOT NULL,
                    token_mint TEXT NOT NULL,
                    token_symbol TEXT,
                    trade_type TEXT NOT NULL,
                    amount_sol REAL NOT NULL,
                    amount_tokens REAL NOT NULL,
                    slippage REAL NOT NULL,
                    quote_id TEXT,
                    dex TEXT DEFAULT 'jupiter',
                    status TEXT DEFAULT 'pending',
                    
                    -- Données d'exécution
                    transaction_signature TEXT,
                    actual_amount_received REAL,
                    actual_price REAL,
                    gas_used REAL,
                    
                    -- Timestamps
                    created_at INTEGER NOT NULL,
                    submitted_at INTEGER,
                    confirmed_at INTEGER,
                    
                    -- Métadonnées
                    priority_fee INTEGER DEFAULT 5000,
                    notes TEXT
                )
            """)
            print("✅ Table trade_orders créée")
            
            # Table des portfolios de trading
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trading_portfolios (
                    wallet_address TEXT PRIMARY KEY,
                    total_trades INTEGER DEFAULT 0,
                    successful_trades INTEGER DEFAULT 0,
                    failed_trades INTEGER DEFAULT 0,
                    total_volume_sol REAL DEFAULT 0.0,
                    total_fees_paid REAL DEFAULT 0.0,
                    total_pnl_sol REAL DEFAULT 0.0,
                    avg_trade_size_sol REAL DEFAULT 0.0,
                    largest_trade_sol REAL DEFAULT 0.0,
                    best_trade_pnl REAL DEFAULT 0.0,
                    worst_trade_pnl REAL DEFAULT 0.0,
                    favorite_tokens TEXT,
                    preferred_dex TEXT DEFAULT 'jupiter',
                    risk_score REAL DEFAULT 1.0,
                    updated_at INTEGER NOT NULL
                )
            """)
            print("✅ Table trading_portfolios créée")
            
            # Index pour améliorer les performances
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_trade_orders_wallet ON trade_orders(wallet_address)",
                "CREATE INDEX IF NOT EXISTS idx_trade_orders_status ON trade_orders(status)",
                "CREATE INDEX IF NOT EXISTS idx_trade_orders_created ON trade_orders(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_trade_orders_token ON trade_orders(token_mint)",
                "CREATE INDEX IF NOT EXISTS idx_trade_orders_wallet_status ON trade_orders(wallet_address, status)",
                "CREATE INDEX IF NOT EXISTS idx_trade_orders_wallet_created ON trade_orders(wallet_address, created_at DESC)"
            ]
            
            for index_sql in indexes:
                cursor.execute(index_sql)
            
            print("✅ Index créés")
            
            conn.commit()
            print("✅ Tables de trading créées avec succès")
            return True
            
    except Exception as e:
        print(f"❌ Erreur lors de la création des tables: {e}")
        return False


def create_trading_tables_with_manager():
    """Crée les tables en utilisant le database manager si disponible"""
    try:
        # Essayer d'importer le database manager
        from core.database import get_database_manager
        
        db_manager = get_database_manager()
        
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            # Même code que ci-dessus mais avec le manager
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trading_settings (
                    wallet_address TEXT PRIMARY KEY,
                    default_slippage REAL DEFAULT 0.5,
                    max_trade_amount_sol REAL DEFAULT 10.0,
                    max_daily_volume_sol REAL DEFAULT 100.0,
                    auto_approve_under_sol REAL DEFAULT 1.0,
                    preferred_dex TEXT DEFAULT 'jupiter',
                    enable_mev_protection BOOLEAN DEFAULT 1,
                    priority_fee_lamports INTEGER DEFAULT 5000,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trade_orders (
                    order_id TEXT PRIMARY KEY,
                    wallet_address TEXT NOT NULL,
                    token_mint TEXT NOT NULL,
                    token_symbol TEXT,
                    trade_type TEXT NOT NULL,
                    amount_sol REAL NOT NULL,
                    amount_tokens REAL NOT NULL,
                    slippage REAL NOT NULL,
                    quote_id TEXT,
                    dex TEXT DEFAULT 'jupiter',
                    status TEXT DEFAULT 'pending',
                    transaction_signature TEXT,
                    actual_amount_received REAL,
                    actual_price REAL,
                    gas_used REAL,
                    created_at INTEGER NOT NULL,
                    submitted_at INTEGER,
                    confirmed_at INTEGER,
                    priority_fee INTEGER DEFAULT 5000,
                    notes TEXT
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trading_portfolios (
                    wallet_address TEXT PRIMARY KEY,
                    total_trades INTEGER DEFAULT 0,
                    successful_trades INTEGER DEFAULT 0,
                    failed_trades INTEGER DEFAULT 0,
                    total_volume_sol REAL DEFAULT 0.0,
                    total_fees_paid REAL DEFAULT 0.0,
                    total_pnl_sol REAL DEFAULT 0.0,
                    avg_trade_size_sol REAL DEFAULT 0.0,
                    largest_trade_sol REAL DEFAULT 0.0,
                    best_trade_pnl REAL DEFAULT 0.0,
                    worst_trade_pnl REAL DEFAULT 0.0,
                    favorite_tokens TEXT,
                    preferred_dex TEXT DEFAULT 'jupiter',
                    risk_score REAL DEFAULT 1.0,
                    updated_at INTEGER NOT NULL
                )
            """)
            
            # Index
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_trade_orders_wallet ON trade_orders(wallet_address)",
                "CREATE INDEX IF NOT EXISTS idx_trade_orders_status ON trade_orders(status)",
                "CREATE INDEX IF NOT EXISTS idx_trade_orders_created ON trade_orders(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_trade_orders_token ON trade_orders(token_mint)",
                "CREATE INDEX IF NOT EXISTS idx_trade_orders_wallet_status ON trade_orders(wallet_address, status)",
                "CREATE INDEX IF NOT EXISTS idx_trade_orders_wallet_created ON trade_orders(wallet_address, created_at DESC)"
            ]
            
            for index_sql in indexes:
                cursor.execute(index_sql)
            
            conn.commit()
            
        print("✅ Tables de trading créées avec le database manager")
        return True
        
    except ImportError as e:
        print(f"⚠️ Database manager non disponible: {e}")
        return False
    except Exception as e:
        print(f"❌ Erreur avec database manager: {e}")
        return False


def find_database_file():
    """Trouve le fichier de base de données"""
    possible_paths = [
        "solana_wallet.db",
        "scanner_wallet/solana_wallet.db", 
        "../solana_wallet.db",
        "data/solana_wallet.db"
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return path
    
    # Si aucun fichier trouvé, utiliser le chemin par défaut
    return "solana_wallet.db"


def main():
    """Fonction principale d'initialisation"""
    print("🚀 Initialisation des tables de trading...")
    print("=" * 50)
    
    # Méthode 1: Essayer avec le database manager
    print("📋 Tentative 1: Utilisation du database manager")
    if create_trading_tables_with_manager():
        print("🎉 Initialisation réussie avec le database manager!")
        return
    
    # Méthode 2: Création directe avec SQLite
    print("\n📋 Tentative 2: Création directe avec SQLite")
    db_path = find_database_file()
    print(f"🎯 Base de données cible: {db_path}")
    
    if create_trading_tables_direct(db_path):
        print("🎉 Initialisation réussie en mode direct!")
        return
    
    print("❌ Échec de l'initialisation des tables de trading")
    sys.exit(1)


if __name__ == "__main__":
    main()