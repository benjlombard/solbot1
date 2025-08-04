#!/usr/bin/env python3
"""
Script de réparation complète de la base de données
Recrée les tables avec la bonne structure et configure le bon wallet
"""

import sqlite3
import os
import time
import shutil
from datetime import datetime

def get_correct_schema():
    """Retourne le schéma correct pour toutes les tables"""
    return {
        'transactions': '''
            CREATE TABLE transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signature TEXT UNIQUE NOT NULL,
                wallet_address TEXT,
                slot INTEGER,
                block_time INTEGER,
                amount REAL,
                token_mint TEXT,
                token_symbol TEXT,
                token_name TEXT,
                transaction_type TEXT,
                token_amount REAL,
                price_per_token REAL,
                fee REAL,
                status TEXT,
                is_token_transaction BOOLEAN DEFAULT 0,
                is_large_token_amount BOOLEAN DEFAULT 0,
                detection_delay REAL DEFAULT 0.0,
                wallet_priority_at_detection REAL DEFAULT 1.0,
                scan_cycle_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''',
        
        'tokens': '''
            CREATE TABLE tokens (
                address TEXT PRIMARY KEY,
                symbol TEXT,
                name TEXT,
                decimals INTEGER,
                price_usd REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''',
        
        'wallet_stats': '''
            CREATE TABLE wallet_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT,
                balance_sol REAL,
                total_transactions INTEGER,
                total_volume REAL,
                pnl REAL,
                largest_transaction REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''',
        
        'token_accounts': '''
            CREATE TABLE token_accounts (
                wallet_address TEXT,
                ata_pubkey TEXT,
                token_mint TEXT,
                balance REAL,
                decimals INTEGER DEFAULT 9,
                first_seen INTEGER,
                last_updated INTEGER,
                last_scanned INTEGER,
                is_active BOOLEAN DEFAULT 1,
                scan_priority INTEGER DEFAULT 1,
                activity_score REAL DEFAULT 0.0,
                last_activity_time INTEGER DEFAULT 0,
                PRIMARY KEY (wallet_address, ata_pubkey)
            )
        ''',
        
        'scan_history': '''
            CREATE TABLE scan_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT,
                scan_type TEXT,
                total_accounts INTEGER,
                new_accounts INTEGER,
                scan_duration REAL,
                completed_at INTEGER,
                priority_score_before REAL DEFAULT 1.0,
                priority_score_after REAL DEFAULT 1.0,
                rpc_requests_count INTEGER DEFAULT 0,
                efficiency_score REAL DEFAULT 0.0,
                activity_detected INTEGER DEFAULT 0,
                notes TEXT
            )
        ''',
        
        'wallet_priorities': '''
            CREATE TABLE wallet_priorities (
                wallet_address TEXT PRIMARY KEY,
                priority_score REAL DEFAULT 1.0,
                last_scan_time INTEGER DEFAULT 0,
                scan_count_1h INTEGER DEFAULT 0,
                scan_count_24h INTEGER DEFAULT 0,
                activity_score REAL DEFAULT 0.0,
                volume_score_1h REAL DEFAULT 0.0,
                new_tokens_score_1h INTEGER DEFAULT 0,
                total_scans INTEGER DEFAULT 0,
                avg_scan_duration REAL DEFAULT 0.0,
                last_activity_detected INTEGER DEFAULT 0,
                consecutive_empty_scans INTEGER DEFAULT 0,
                updated_at INTEGER DEFAULT 0,
                created_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        ''',
        
        'wallet_activity_metrics': '''
            CREATE TABLE wallet_activity_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                period_minutes INTEGER DEFAULT 15,
                new_transactions_count INTEGER DEFAULT 0,
                volume_sol REAL DEFAULT 0.0,
                new_token_accounts INTEGER DEFAULT 0,
                scan_duration REAL DEFAULT 0.0,
                discoveries_count INTEGER DEFAULT 0,
                balance_changes_count INTEGER DEFAULT 0,
                rpc_requests_made INTEGER DEFAULT 0,
                errors_count INTEGER DEFAULT 0,
                efficiency_score REAL DEFAULT 0.0
            )
        ''',
        
        'scan_queue': '''
            CREATE TABLE scan_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL,
                priority_score REAL NOT NULL,
                scheduled_time INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                scan_type TEXT DEFAULT 'balance_change',
                estimated_duration REAL DEFAULT 30.0,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                started_at INTEGER,
                completed_at INTEGER,
                error_message TEXT
            )
        '''
    }

def get_correct_indexes():
    """Retourne les index à créer"""
    return [
        "CREATE INDEX IF NOT EXISTS idx_token_accounts_wallet ON token_accounts(wallet_address)",
        "CREATE INDEX IF NOT EXISTS idx_token_accounts_mint ON token_accounts(token_mint)",
        "CREATE INDEX IF NOT EXISTS idx_token_accounts_priority ON token_accounts(scan_priority DESC, last_scanned ASC)",
        "CREATE INDEX IF NOT EXISTS idx_token_accounts_active ON token_accounts(is_active, last_updated DESC)",
        "CREATE INDEX IF NOT EXISTS idx_transactions_wallet_time ON transactions(wallet_address, block_time DESC)",
        "CREATE INDEX IF NOT EXISTS idx_transactions_token_type ON transactions(is_token_transaction, block_time DESC)",
        "CREATE INDEX IF NOT EXISTS idx_scan_history_wallet ON scan_history(wallet_address, completed_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_wallet_priorities_score ON wallet_priorities(priority_score DESC, last_scan_time ASC)",
        "CREATE INDEX IF NOT EXISTS idx_wallet_priorities_activity ON wallet_priorities(last_activity_detected DESC)",
        "CREATE INDEX IF NOT EXISTS idx_activity_metrics_wallet_time ON wallet_activity_metrics(wallet_address, timestamp DESC)",
        "CREATE INDEX IF NOT EXISTS idx_scan_queue_priority ON scan_queue(status, priority_score DESC, scheduled_time ASC)",
        "CREATE INDEX IF NOT EXISTS idx_token_accounts_activity ON token_accounts(activity_score DESC, last_activity_time DESC)"
    ]

def backup_database(db_name):
    """Crée une sauvegarde de la base de données"""
    if not os.path.exists(db_name):
        print(f"⚠️ Base de données {db_name} non trouvée")
        return None
    
    backup_name = f"{db_name}.backup_{int(time.time())}"
    try:
        shutil.copy2(db_name, backup_name)
        print(f"💾 Sauvegarde créée: {backup_name}")
        return backup_name
    except Exception as e:
        print(f"❌ Erreur sauvegarde: {e}")
        return None

def extract_data(db_name, target_wallet):
    """Extrait les données du wallet cible avant reconstruction"""
    print(f"📊 Extraction des données pour {target_wallet[:8]}...")
    
    data = {
        'transactions': [],
        'token_accounts': [],
        'scan_history': [],
        'wallet_stats': []
    }
    
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        
        # Extraire les transactions
        try:
            cursor.execute("SELECT * FROM transactions WHERE wallet_address = ?", (target_wallet,))
            data['transactions'] = cursor.fetchall()
            print(f"   📝 {len(data['transactions'])} transactions extraites")
        except sqlite3.OperationalError:
            print("   ⚠️ Table transactions non trouvée")
        
        # Extraire les comptes de tokens
        try:
            cursor.execute("SELECT * FROM token_accounts WHERE wallet_address = ?", (target_wallet,))
            data['token_accounts'] = cursor.fetchall()
            print(f"   🪙 {len(data['token_accounts'])} comptes de tokens extraits")
        except sqlite3.OperationalError:
            print("   ⚠️ Table token_accounts non trouvée")
        
        # Extraire l'historique
        try:
            cursor.execute("SELECT * FROM scan_history WHERE wallet_address = ?", (target_wallet,))
            data['scan_history'] = cursor.fetchall()
            print(f"   📚 {len(data['scan_history'])} entrées d'historique extraites")
        except sqlite3.OperationalError:
            print("   ⚠️ Table scan_history non trouvée")
        
        # Extraire les stats
        try:
            cursor.execute("SELECT * FROM wallet_stats WHERE wallet_address = ?", (target_wallet,))
            data['wallet_stats'] = cursor.fetchall()
            print(f"   📊 {len(data['wallet_stats'])} entrées de stats extraites")
        except sqlite3.OperationalError:
            print("   ⚠️ Table wallet_stats non trouvée")
        
        conn.close()
        return data
        
    except Exception as e:
        print(f"❌ Erreur extraction: {e}")
        return data

def recreate_database(db_name, target_wallet):
    """Recrée complètement la base de données avec la bonne structure"""
    print(f"🔨 Reconstruction de la base de données...")
    
    # Supprimer l'ancienne base
    if os.path.exists(db_name):
        os.remove(db_name)
        print(f"   🗑️ Ancienne base supprimée")
    
    # Créer la nouvelle base
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    
    # Créer toutes les tables
    schemas = get_correct_schema()
    for table_name, schema in schemas.items():
        try:
            cursor.execute(schema)
            print(f"   ✅ Table {table_name} créée")
        except Exception as e:
            print(f"   ❌ Erreur création table {table_name}: {e}")
    
    # Créer les index
    indexes = get_correct_indexes()
    for index in indexes:
        try:
            cursor.execute(index)
        except Exception as e:
            print(f"   ⚠️ Erreur index: {e}")
    
    print(f"   📚 {len(indexes)} index créés")
    
    # Initialiser les priorités pour le wallet cible
    current_time = int(time.time())
    cursor.execute('''
        INSERT INTO wallet_priorities 
        (wallet_address, priority_score, last_scan_time, total_scans, updated_at, created_at)
        VALUES (?, 3.0, 0, 0, ?, ?)
    ''', (target_wallet, current_time, current_time))
    
    print(f"   🎯 Priorité initialisée pour {target_wallet[:8]}...")
    
    conn.commit()
    conn.close()
    
    print("✅ Base de données reconstruite avec succès")

def main():
    """Point d'entrée principal"""
    DB_NAME = "solana_wallet.db"
    TARGET_WALLET = "4DdrfiDHpmx55i4SPssxVzS9ZaKLb8qr45NKY9Er9nNh"
    
    print("🔧 RÉPARATION COMPLÈTE DE LA BASE DE DONNÉES")
    print("=" * 60)
    print(f"📍 Base de données: {DB_NAME}")
    print(f"🎯 Wallet cible: {TARGET_WALLET[:8]}...{TARGET_WALLET[-8:]}")
    
    # Demander confirmation
    response = input("\n⚠️ Cette opération va reconstruire complètement la base. Continuer? (o/N): ")
    if response.lower() not in ['o', 'oui', 'y', 'yes']:
        print("❌ Réparation annulée")
        return
    
    # Créer une sauvegarde
    print("\n📦 Création d'une sauvegarde...")
    backup_path = backup_database(DB_NAME)
    
    # Extraire les données existantes (optionnel)
    if os.path.exists(DB_NAME):
        extract_data(DB_NAME, TARGET_WALLET)
    
    # Reconstruire la base
    recreate_database(DB_NAME, TARGET_WALLET)
    
    print("\n🎉 RÉPARATION TERMINÉE")
    print("=" * 60)
    print(f"✅ Base de données reconstruite pour le wallet:")
    print(f"   {TARGET_WALLET}")
    print("💡 Vous pouvez maintenant relancer le moniteur")
    
    if backup_path:
        print(f"💾 Sauvegarde disponible: {backup_path}")

if __name__ == "__main__":
    main()