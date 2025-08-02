#!/usr/bin/env python3
"""
Script de migration de base de données pour le moniteur Solana optimisé
Corrige les incompatibilités de schéma entre l'ancienne et la nouvelle version
"""

import sqlite3
import os
import time
from datetime import datetime

def backup_database(db_name: str) -> str:
    """Crée une sauvegarde de la base de données actuelle"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f"{db_name}.backup_{timestamp}"
    
    try:
        # Copier le fichier de base de données
        import shutil
        shutil.copy2(db_name, backup_name)
        print(f"✅ Sauvegarde créée: {backup_name}")
        return backup_name
    except Exception as e:
        print(f"⚠️ Erreur lors de la sauvegarde: {e}")
        return None

def check_database_schema(db_name: str):
    """Vérifie et affiche le schéma actuel de la base de données"""
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        
        print(f"🔍 Vérification du schéma de {db_name}...")
        
        # Lister toutes les tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        
        print(f"📊 Tables trouvées: {tables}")
        
        # Vérifier le schéma de chaque table importante
        for table in ['transactions', 'wallet_stats', 'token_accounts', 'scan_history']:
            if table in tables:
                cursor.execute(f"PRAGMA table_info({table})")
                columns = cursor.fetchall()
                print(f"\n📋 Table '{table}':")
                for col in columns:
                    print(f"   - {col[1]} ({col[2]})")
            else:
                print(f"\n❌ Table '{table}' non trouvée")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Erreur lors de la vérification: {e}")

def migrate_wallet_stats_table(db_name: str):
    """Migre la table wallet_stats pour ajouter la colonne wallet_address"""
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        
        print("🔧 Migration de la table wallet_stats...")
        
        # Vérifier si la colonne wallet_address existe déjà
        cursor.execute("PRAGMA table_info(wallet_stats)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'wallet_address' not in columns:
            print("   ➕ Ajout de la colonne wallet_address...")
            
            # Créer une nouvelle table avec le bon schéma
            cursor.execute('''
                CREATE TABLE wallet_stats_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    wallet_address TEXT,
                    balance_sol REAL,
                    total_transactions INTEGER,
                    total_volume REAL,
                    pnl REAL,
                    largest_transaction REAL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Copier les données existantes (si il y en a)
            cursor.execute("SELECT COUNT(*) FROM wallet_stats")
            count = cursor.fetchone()[0]
            
            if count > 0:
                print(f"   📋 Migration de {count} enregistrements existants...")
                # Assumer un wallet par défaut pour les anciennes données
                default_wallet = "UNKNOWN_WALLET"
                cursor.execute('''
                    INSERT INTO wallet_stats_new 
                    (wallet_address, balance_sol, total_transactions, total_volume, pnl, largest_transaction, updated_at)
                    SELECT ?, balance_sol, total_transactions, total_volume, pnl, largest_transaction, updated_at
                    FROM wallet_stats
                ''', (default_wallet,))
            
            # Supprimer l'ancienne table et renommer la nouvelle
            cursor.execute("DROP TABLE wallet_stats")
            cursor.execute("ALTER TABLE wallet_stats_new RENAME TO wallet_stats")
            
            print("   ✅ Table wallet_stats migrée avec succès")
        else:
            print("   ✅ Colonne wallet_address déjà présente")
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        print(f"❌ Erreur lors de la migration wallet_stats: {e}")
        raise

def ensure_all_tables_exist(db_name: str):
    """S'assure que toutes les tables nécessaires existent avec le bon schéma"""
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        
        print("🔧 Vérification/création de toutes les tables...")
        
        # Table des transactions (mise à jour si nécessaire)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Table des tokens
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tokens (
                address TEXT PRIMARY KEY,
                symbol TEXT,
                name TEXT,
                decimals INTEGER,
                price_usd REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Table des comptes de tokens (nouvelle)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS token_accounts (
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
                PRIMARY KEY (wallet_address, ata_pubkey)
            )
        ''')
        
        # Table de l'historique des scans (nouvelle)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scan_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT,
                scan_type TEXT,
                total_accounts INTEGER,
                new_accounts INTEGER,
                scan_duration REAL,
                completed_at INTEGER,
                notes TEXT
            )
        ''')
        
        # Créer les index
        indexes = [
            ("idx_token_accounts_wallet", "CREATE INDEX IF NOT EXISTS idx_token_accounts_wallet ON token_accounts(wallet_address)"),
            ("idx_token_accounts_mint", "CREATE INDEX IF NOT EXISTS idx_token_accounts_mint ON token_accounts(token_mint)"),
            ("idx_token_accounts_priority", "CREATE INDEX IF NOT EXISTS idx_token_accounts_priority ON token_accounts(scan_priority DESC, last_scanned ASC)"),
            ("idx_transactions_wallet_time", "CREATE INDEX IF NOT EXISTS idx_transactions_wallet_time ON transactions(wallet_address, block_time DESC)"),
            ("idx_transactions_token_type", "CREATE INDEX IF NOT EXISTS idx_transactions_token_type ON transactions(is_token_transaction, block_time DESC)")
        ]
        
        for index_name, index_sql in indexes:
            try:
                cursor.execute(index_sql)
                print(f"   ✅ Index '{index_name}' créé")
            except sqlite3.OperationalError:
                print(f"   ✅ Index '{index_name}' existe déjà")
        
        conn.commit()
        conn.close()
        print("✅ Toutes les tables et index sont prêts")
        
    except Exception as e:
        print(f"❌ Erreur lors de la création des tables: {e}")
        raise

def add_missing_columns_to_transactions(db_name: str):
    """Ajoute les colonnes manquantes à la table transactions"""
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        
        print("🔧 Vérification des colonnes de la table transactions...")
        
        # Vérifier les colonnes existantes
        cursor.execute("PRAGMA table_info(transactions)")
        existing_columns = [col[1] for col in cursor.fetchall()]
        
        # Colonnes requises
        required_columns = [
            ('wallet_address', 'TEXT'),
            ('token_mint', 'TEXT'),
            ('token_symbol', 'TEXT'),
            ('token_name', 'TEXT'),
            ('transaction_type', 'TEXT'),
            ('token_amount', 'REAL'),
            ('price_per_token', 'REAL'),
            ('is_token_transaction', 'BOOLEAN DEFAULT 0'),
            ('is_large_token_amount', 'BOOLEAN DEFAULT 0')
        ]
        
        for column_name, column_type in required_columns:
            if column_name not in existing_columns:
                try:
                    cursor.execute(f'ALTER TABLE transactions ADD COLUMN {column_name} {column_type}')
                    print(f"   ➕ Colonne '{column_name}' ajoutée")
                except sqlite3.OperationalError as e:
                    print(f"   ⚠️ Impossible d'ajouter '{column_name}': {e}")
        
        conn.commit()
        conn.close()
        print("✅ Table transactions mise à jour")
        
    except Exception as e:
        print(f"❌ Erreur lors de la mise à jour des colonnes: {e}")

def main():
    """Point d'entrée principal de la migration"""
    db_name = "solana_wallet.db"
    
    print("🚀 MIGRATION DE BASE DE DONNÉES - MONITEUR SOLANA OPTIMISÉ")
    print("=" * 70)
    
    # Vérifier si la base existe
    if not os.path.exists(db_name):
        print(f"✅ Aucune base existante trouvée. Création d'une nouvelle base...")
        # Créer directement avec le bon schéma
        ensure_all_tables_exist(db_name)
        print("✅ Migration terminée - nouvelle base de données créée")
        return
    
    print(f"📋 Base de données existante trouvée: {db_name}")
    
    # Créer une sauvegarde
    backup_name = backup_database(db_name)
    
    # Vérifier le schéma actuel
    check_database_schema(db_name)
    
    print("\n🔧 DÉBUT DE LA MIGRATION...")
    
    try:
        # Étape 1: Migrer la table wallet_stats
        migrate_wallet_stats_table(db_name)
        
        # Étape 2: Ajouter les colonnes manquantes à transactions
        add_missing_columns_to_transactions(db_name)
        
        # Étape 3: S'assurer que toutes les nouvelles tables existent
        ensure_all_tables_exist(db_name)
        
        print("\n✅ MIGRATION TERMINÉE AVEC SUCCÈS!")
        print("=" * 70)
        print("🎉 La base de données est maintenant compatible avec le moniteur optimisé")
        
        if backup_name:
            print(f"💾 Sauvegarde disponible: {backup_name}")
        
        print("\n🚀 Vous pouvez maintenant relancer le moniteur!")
        
    except Exception as e:
        print(f"\n❌ ÉCHEC DE LA MIGRATION: {e}")
        print("=" * 70)
        
        if backup_name:
            print(f"💾 Restaurez la sauvegarde si nécessaire: {backup_name}")
        
        return False
    
    return True

if __name__ == "__main__":
    success = main()
    if not success:
        exit(1)