#!/usr/bin/env python3
"""
Script de migration de la base de données pour le système de priorités dynamiques
Ajoute les tables et colonnes nécessaires pour le monitoring intelligent
"""

import sqlite3
import os
import time
from typing import List

class DatabaseMigrator:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.version_table = "schema_versions"
        
    def get_connection(self):
        """Créer une connexion à la base de données"""
        return sqlite3.connect(self.db_path)
    
    def init_version_tracking(self):
        """Initialise le système de versioning des migrations"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS {self.version_table} (
                    version INTEGER PRIMARY KEY,
                    migration_name TEXT NOT NULL,
                    applied_at INTEGER NOT NULL,
                    description TEXT
                )
            ''')
            conn.commit()
            print("✅ Système de versioning initialisé")
        except Exception as e:
            print(f"❌ Erreur initialisation versioning: {e}")
        finally:
            conn.close()
    
    def is_migration_applied(self, version: int) -> bool:
        """Vérifie si une migration a déjà été appliquée"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(f"SELECT 1 FROM {self.version_table} WHERE version = ?", (version,))
            return cursor.fetchone() is not None
        except:
            return False
        finally:
            conn.close()
    
    def mark_migration_applied(self, version: int, name: str, description: str):
        """Marque une migration comme appliquée"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(f'''
                INSERT INTO {self.version_table} (version, migration_name, applied_at, description)
                VALUES (?, ?, ?, ?)
            ''', (version, name, int(time.time()), description))
            conn.commit()
            print(f"✅ Migration {version} - {name} marquée comme appliquée")
        except Exception as e:
            print(f"❌ Erreur marquage migration: {e}")
        finally:
            conn.close()
    
    def column_exists(self, table_name: str, column_name: str) -> bool:
        """Vérifie si une colonne existe dans une table"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()
            return any(col[1] == column_name for col in columns)
        except:
            return False
        finally:
            conn.close()
    
    def table_exists(self, table_name: str) -> bool:
        """Vérifie si une table existe"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name=?
            ''', (table_name,))
            return cursor.fetchone() is not None
        except:
            return False
        finally:
            conn.close()

    def migration_001_wallet_priorities(self):
        """Migration 001: Créer la table wallet_priorities"""
        if self.is_migration_applied(1):
            print("⏭️ Migration 001 déjà appliquée")
            return True
            
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            print("🔄 Application de la migration 001: Table wallet_priorities")
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS wallet_priorities (
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
            ''')
            
            # Index pour optimiser les requêtes
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_wallet_priorities_score 
                ON wallet_priorities(priority_score DESC, last_scan_time ASC)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_wallet_priorities_activity 
                ON wallet_priorities(last_activity_detected DESC)
            ''')
            
            conn.commit()
            self.mark_migration_applied(1, "wallet_priorities", "Table des priorités par wallet")
            print("✅ Migration 001 appliquée avec succès")
            return True
            
        except Exception as e:
            print(f"❌ Erreur migration 001: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def migration_002_wallet_activity_metrics(self):
        """Migration 002: Créer la table wallet_activity_metrics"""
        if self.is_migration_applied(2):
            print("⏭️ Migration 002 déjà appliquée")
            return True
            
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            print("🔄 Application de la migration 002: Table wallet_activity_metrics")
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS wallet_activity_metrics (
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
            ''')
            
            # Index pour optimiser les requêtes temporelles
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_activity_metrics_wallet_time 
                ON wallet_activity_metrics(wallet_address, timestamp DESC)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_activity_metrics_timestamp 
                ON wallet_activity_metrics(timestamp DESC)
            ''')
            
            conn.commit()
            self.mark_migration_applied(2, "wallet_activity_metrics", "Métriques d'activité par wallet")
            print("✅ Migration 002 appliquée avec succès")
            return True
            
        except Exception as e:
            print(f"❌ Erreur migration 002: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def migration_003_scan_queue(self):
        """Migration 003: Créer la table scan_queue"""
        if self.is_migration_applied(3):
            print("⏭️ Migration 003 déjà appliquée")
            return True
            
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            print("🔄 Application de la migration 003: Table scan_queue")
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS scan_queue (
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
            ''')
            
            # Index pour la queue de priorité
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_scan_queue_priority 
                ON scan_queue(status, priority_score DESC, scheduled_time ASC)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_scan_queue_wallet 
                ON scan_queue(wallet_address, status)
            ''')
            
            conn.commit()
            self.mark_migration_applied(3, "scan_queue", "File d'attente intelligente des scans")
            print("✅ Migration 003 appliquée avec succès")
            return True
            
        except Exception as e:
            print(f"❌ Erreur migration 003: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def migration_004_extend_existing_tables(self):
        """Migration 004: Ajouter des colonnes aux tables existantes"""
        if self.is_migration_applied(4):
            print("⏭️ Migration 004 déjà appliquée")
            return True
            
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            print("🔄 Application de la migration 004: Extension des tables existantes")
            
            # Ajouter colonnes à token_accounts
            columns_to_add_token_accounts = [
                ("activity_score", "REAL DEFAULT 0.0"),
                ("last_activity_time", "INTEGER DEFAULT 0"),
                ("detection_efficiency", "REAL DEFAULT 1.0"),
                ("scan_frequency_minutes", "INTEGER DEFAULT 30")
            ]
            
            for column_name, column_def in columns_to_add_token_accounts:
                if not self.column_exists("token_accounts", column_name):
                    cursor.execute(f"ALTER TABLE token_accounts ADD COLUMN {column_name} {column_def}")
                    print(f"   ➕ Ajouté token_accounts.{column_name}")
            
            # Ajouter colonnes à transactions
            columns_to_add_transactions = [
                ("detection_delay", "REAL DEFAULT 0.0"),
                ("wallet_priority_at_detection", "REAL DEFAULT 1.0"),
                ("scan_cycle_id", "TEXT"),
                ("discovery_method", "TEXT DEFAULT 'signature'")
            ]
            
            for column_name, column_def in columns_to_add_transactions:
                if not self.column_exists("transactions", column_name):
                    cursor.execute(f"ALTER TABLE transactions ADD COLUMN {column_name} {column_def}")
                    print(f"   ➕ Ajouté transactions.{column_name}")
            
            # Ajouter colonnes à scan_history
            columns_to_add_scan_history = [
                ("priority_score_before", "REAL DEFAULT 1.0"),
                ("priority_score_after", "REAL DEFAULT 1.0"),
                ("rpc_requests_count", "INTEGER DEFAULT 0"),
                ("efficiency_score", "REAL DEFAULT 0.0"),
                ("activity_detected", "INTEGER DEFAULT 0")
            ]
            
            for column_name, column_def in columns_to_add_scan_history:
                if not self.column_exists("scan_history", column_name):
                    cursor.execute(f"ALTER TABLE scan_history ADD COLUMN {column_name} {column_def}")
                    print(f"   ➕ Ajouté scan_history.{column_name}")
            
            # Nouveaux index
            new_indexes = [
                ("idx_token_accounts_activity", "CREATE INDEX IF NOT EXISTS idx_token_accounts_activity ON token_accounts(activity_score DESC, last_activity_time DESC)"),
                ("idx_transactions_detection", "CREATE INDEX IF NOT EXISTS idx_transactions_detection ON transactions(detection_delay, wallet_priority_at_detection)"),
                ("idx_scan_history_efficiency", "CREATE INDEX IF NOT EXISTS idx_scan_history_efficiency ON scan_history(efficiency_score DESC, completed_at DESC)")
            ]
            
            for index_name, index_sql in new_indexes:
                cursor.execute(index_sql)
                print(f"   📊 Index créé: {index_name}")
            
            conn.commit()
            self.mark_migration_applied(4, "extend_existing_tables", "Extension des tables existantes")
            print("✅ Migration 004 appliquée avec succès")
            return True
            
        except Exception as e:
            print(f"❌ Erreur migration 004: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def migration_005_initialize_wallet_priorities(self):
        """Migration 005: Initialiser les priorités pour les wallets existants"""
        if self.is_migration_applied(5):
            print("⏭️ Migration 005 déjà appliquée")
            return True
            
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            print("🔄 Application de la migration 005: Initialisation des priorités")
            
            # Récupérer tous les wallets existants depuis les transactions
            cursor.execute('''
                SELECT DISTINCT wallet_address 
                FROM transactions 
                WHERE wallet_address IS NOT NULL
            ''')
            existing_wallets = cursor.fetchall()
            
            # Récupérer aussi depuis token_accounts
            cursor.execute('''
                SELECT DISTINCT wallet_address 
                FROM token_accounts 
                WHERE wallet_address IS NOT NULL
            ''')
            token_wallets = cursor.fetchall()
            
            # Combiner les deux listes
            all_wallets = set()
            all_wallets.update([w[0] for w in existing_wallets])
            all_wallets.update([w[0] for w in token_wallets])
            
            print(f"   📱 Trouvé {len(all_wallets)} wallets uniques à initialiser")
            
            current_time = int(time.time())
            
            for wallet_address in all_wallets:
                # Calculer des statistiques de base pour chaque wallet
                cursor.execute('''
                    SELECT COUNT(*), 
                           COUNT(CASE WHEN block_time >= ? THEN 1 END),
                           COALESCE(SUM(ABS(amount)), 0)
                    FROM transactions 
                    WHERE wallet_address = ?
                ''', (current_time - 3600, wallet_address))  # Dernière heure
                
                total_tx, recent_tx, total_volume = cursor.fetchone()
                
                # Calculer un score initial basé sur l'activité historique
                base_score = 1.0
                if recent_tx > 0:
                    base_score += min(recent_tx * 0.5, 5.0)  # Max +5 pour activité récente
                if total_volume > 10:
                    base_score += min(total_volume * 0.1, 3.0)  # Max +3 pour volume
                
                # Insérer ou mettre à jour les priorités
                cursor.execute('''
                    INSERT OR REPLACE INTO wallet_priorities 
                    (wallet_address, priority_score, scan_count_24h, activity_score, 
                     volume_score_1h, total_scans, updated_at)
                    VALUES (?, ?, ?, ?, ?, 0, ?)
                ''', (wallet_address, base_score, total_tx, float(recent_tx), 
                      float(total_volume), current_time))
                
                print(f"   🎯 {wallet_address[:8]}... initialisé avec score {base_score:.2f}")
            
            conn.commit()
            self.mark_migration_applied(5, "initialize_wallet_priorities", "Initialisation priorités wallets existants")
            print("✅ Migration 005 appliquée avec succès")
            return True
            
        except Exception as e:
            print(f"❌ Erreur migration 005: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def run_all_migrations(self) -> bool:
        """Exécute toutes les migrations dans l'ordre"""
        print("🚀 Démarrage des migrations de base de données")
        print("=" * 60)
        
        # Vérifier que la DB existe
        if not os.path.exists(self.db_path):
            print(f"❌ Base de données non trouvée: {self.db_path}")
            return False
        
        # Initialiser le système de versioning
        self.init_version_tracking()
        
        # Liste des migrations à exécuter
        migrations = [
            ("001", self.migration_001_wallet_priorities),
            ("002", self.migration_002_wallet_activity_metrics),
            ("003", self.migration_003_scan_queue),
            ("004", self.migration_004_extend_existing_tables),
            ("005", self.migration_005_initialize_wallet_priorities)
        ]
        
        success_count = 0
        for migration_id, migration_func in migrations:
            print(f"\n📦 Migration {migration_id}")
            print("-" * 40)
            
            try:
                if migration_func():
                    success_count += 1
                else:
                    print(f"❌ Échec migration {migration_id}")
                    # Continuer avec les autres migrations
            except Exception as e:
                print(f"❌ Erreur critique migration {migration_id}: {e}")
        
        print("\n" + "=" * 60)
        print(f"✅ Migrations terminées: {success_count}/{len(migrations)} réussies")
        
        if success_count == len(migrations):
            print("🎉 Toutes les migrations appliquées avec succès!")
            self.show_database_summary()
            return True
        else:
            print("⚠️ Certaines migrations ont échoué, vérifiez les logs")
            return False

    def show_database_summary(self):
        """Affiche un résumé de la structure de la base après migration"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            print("\n📊 RÉSUMÉ DE LA BASE DE DONNÉES")
            print("=" * 50)
            
            # Tables principales
            tables = ['wallet_priorities', 'wallet_activity_metrics', 'scan_queue', 
                     'transactions', 'token_accounts', 'scan_history']
            
            for table in tables:
                if self.table_exists(table):
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]
                    print(f"📋 {table}: {count:,} enregistrements")
            
            # Migrations appliquées
            print(f"\n🔄 MIGRATIONS APPLIQUÉES:")
            cursor.execute(f'''
                SELECT version, migration_name, datetime(applied_at, 'unixepoch', 'localtime')
                FROM {self.version_table} 
                ORDER BY version
            ''')
            
            for version, name, applied_at in cursor.fetchall():
                print(f"   ✅ {version:03d} - {name} (appliquée le {applied_at})")
            
        except Exception as e:
            print(f"❌ Erreur résumé: {e}")
        finally:
            conn.close()

def main():
    """Point d'entrée principal du script de migration"""
    import sys
    
    # Chemin vers la base de données
    db_path = "../solana_wallet.db"
    
    # Vérifier les arguments
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    
    print(f"🎯 Migration de la base de données: {db_path}")
    
    # Créer et exécuter le migrateur
    migrator = DatabaseMigrator(db_path)
    
    if migrator.run_all_migrations():
        print("\n🎉 Migration terminée avec succès!")
        print("💡 Vous pouvez maintenant implémenter le système de priorités dynamiques")
        return 0
    else:
        print("\n❌ Échec de la migration")
        return 1

if __name__ == "__main__":
    exit(main())