# setup_db.py
import sqlite3
from datetime import datetime

def create_database():
    conn = sqlite3.connect('snipers.db')
    cursor = conn.cursor()
    
    # Création des tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tokens (
            address TEXT PRIMARY KEY,
            name TEXT,
            symbol TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pools (
            address TEXT PRIMARY KEY,
            token_address TEXT,
            market_address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (token_address) REFERENCES tokens(address)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS swaps (
            signature TEXT PRIMARY KEY,
            pool_address TEXT,
            buyer_address TEXT,
            sol_amount REAL,
            token_amount REAL,
            timestamp TIMESTAMP,
            seconds_after_pool_creation REAL,
            FOREIGN KEY (pool_address) REFERENCES pools(address)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS snipers (
            wallet_address TEXT PRIMARY KEY,
            snipe_count INTEGER DEFAULT 0,
            avg_reaction_time REAL,
            confidence_score REAL DEFAULT 0.0,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Index pour performance
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_swaps_timing ON swaps(seconds_after_pool_creation)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_swaps_buyer ON swaps(buyer_address)')
    
    conn.commit()
    conn.close()
    print("✅ Base de données créée avec succès")

if __name__ == "__main__":
    create_database()