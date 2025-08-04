#!/usr/bin/env python3
"""
Script de nettoyage de la base de données pour le moniteur Solana
Réinitialise les priorités et configure le bon wallet
"""

import sqlite3
import os
import time
from datetime import datetime

def cleanup_database():
    """Nettoie et réinitialise la base de données"""
    
    # Configuration
    DB_NAME = "solana_wallet.db"
    TARGET_WALLET = "4DdrfiDHpmx55i4SPssxVzS9ZaKLb8qr45NKY9Er9nNh"
    
    print("🧹 NETTOYAGE DE LA BASE DE DONNÉES")
    print("=" * 50)
    print(f"📍 Base de données: {DB_NAME}")
    print(f"🎯 Wallet cible: {TARGET_WALLET[:8]}...{TARGET_WALLET[-8:]}")
    
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # 1. Nettoyer les données de wallets non désirés
        print("\n1️⃣ Suppression des données de wallets non désirés...")
        
        # Supprimer les transactions
        cursor.execute("DELETE FROM transactions WHERE wallet_address != ?", (TARGET_WALLET,))
        deleted_tx = cursor.rowcount
        print(f"   📊 Transactions supprimées: {deleted_tx}")
        
        # Supprimer les comptes de tokens
        cursor.execute("DELETE FROM token_accounts WHERE wallet_address != ?", (TARGET_WALLET,))
        deleted_accounts = cursor.rowcount
        print(f"   📊 Comptes de tokens supprimés: {deleted_accounts}")
        
        # Supprimer les stats de wallets
        cursor.execute("DELETE FROM wallet_stats WHERE wallet_address != ?", (TARGET_WALLET,))
        deleted_stats = cursor.rowcount
        print(f"   📊 Stats de wallets supprimées: {deleted_stats}")
        
        # Supprimer l'historique de scans
        cursor.execute("DELETE FROM scan_history WHERE wallet_address != ?", (TARGET_WALLET,))
        deleted_history = cursor.rowcount
        print(f"   📊 Historiques supprimés: {deleted_history}")
        
        # 2. Réinitialiser les priorités
        print("\n2️⃣ Réinitialisation des priorités...")
        
        # Supprimer toutes les priorités existantes
        cursor.execute("DELETE FROM wallet_priorities")
        print(f"   🗑️ Anciennes priorités supprimées")
        
        # Vérifier la structure de la table wallet_priorities
        cursor.execute("PRAGMA table_info(wallet_priorities)")
        columns = [row[1] for row in cursor.fetchall()]
        print(f"   📋 Colonnes disponibles: {', '.join(columns)}")
        
        # Créer une nouvelle priorité pour le wallet cible avec colonnes disponibles
        current_time = int(time.time())
        
        # Construire la requête en fonction des colonnes disponibles
        base_columns = ['wallet_address', 'priority_score', 'last_scan_time', 'total_scans']
        base_values = [TARGET_WALLET, 3.0, 0, 0]
        
        optional_columns = {
            'scan_count_1h': 0,
            'scan_count_24h': 0,
            'activity_score': 0.0,
            'volume_score_1h': 0.0,
            'new_tokens_score_1h': 0,
            'avg_scan_duration': 0.0,
            'last_activity_detected': 0,
            'consecutive_empty_scans': 0,
            'updated_at': current_time,
            'created_at': current_time
        }
        
        # Ajouter les colonnes optionnelles qui existent
        for col, val in optional_columns.items():
            if col in columns:
                base_columns.append(col)
                base_values.append(val)
        
        # Construire et exécuter la requête
        placeholders = ', '.join(['?' for _ in base_columns])
        columns_str = ', '.join(base_columns)
        
        insert_query = f'''
            INSERT INTO wallet_priorities ({columns_str})
            VALUES ({placeholders})
        '''
        
        cursor.execute(insert_query, base_values)
        
        print(f"   ✅ Priorité créée pour {TARGET_WALLET[:8]}... (score: 3.0)")
        
        # 3. Nettoyer les métriques
        print("\n3️⃣ Nettoyage des métriques...")
        
        # Supprimer les métriques d'activité
        cursor.execute("DELETE FROM wallet_activity_metrics WHERE wallet_address != ?", (TARGET_WALLET,))
        deleted_metrics = cursor.rowcount
        print(f"   📊 Métriques supprimées: {deleted_metrics}")
        
        # 4. Vérifier l'état final
        print("\n4️⃣ Vérification de l'état final...")
        
        # Compter les enregistrements restants
        tables_to_check = [
            ("transactions", "wallet_address"),
            ("token_accounts", "wallet_address"),
            ("wallet_stats", "wallet_address"),
            ("scan_history", "wallet_address"),
            ("wallet_priorities", "wallet_address"),
            ("wallet_activity_metrics", "wallet_address")
        ]
        
        for table, wallet_col in tables_to_check:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE {wallet_col} = ?", (TARGET_WALLET,))
                count = cursor.fetchone()[0]
                print(f"   📊 {table}: {count} enregistrement(s) pour le wallet cible")
                
                # Vérifier s'il reste d'autres wallets
                cursor.execute(f"SELECT COUNT(DISTINCT {wallet_col}) FROM {table}")
                distinct_wallets = cursor.fetchone()[0]
                if distinct_wallets > 1:
                    print(f"   ⚠️ {table}: {distinct_wallets} wallets distincts encore présents")
                
            except sqlite3.OperationalError:
                print(f"   ⚠️ Table {table} non trouvée")
        
        # 5. Optimiser la base de données
        print("\n5️⃣ Optimisation de la base de données...")
        cursor.execute("VACUUM")
        print("   ✅ VACUUM exécuté")
        
        cursor.execute("ANALYZE")
        print("   ✅ ANALYZE exécuté")
        
        conn.commit()
        conn.close()
        
        print("\n✅ NETTOYAGE TERMINÉ")
        print("=" * 50)
        print(f"🎯 La base est maintenant configurée pour le wallet:")
        print(f"   {TARGET_WALLET}")
        print("💡 Vous pouvez maintenant relancer le moniteur")
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur lors du nettoyage: {e}")
        return False

def backup_database():
    """Crée une sauvegarde de la base avant nettoyage"""
    DB_NAME = "solana_wallet.db"
    
    if not os.path.exists(DB_NAME):
        print(f"⚠️ Base de données {DB_NAME} non trouvée")
        return False
    
    backup_name = f"{DB_NAME}.backup_{int(time.time())}"
    
    try:
        import shutil
        shutil.copy2(DB_NAME, backup_name)
        print(f"💾 Sauvegarde créée: {backup_name}")
        return True
    except Exception as e:
        print(f"❌ Erreur sauvegarde: {e}")
        return False

def main():
    """Point d'entrée principal"""
    print("🧹 UTILITAIRE DE NETTOYAGE - MONITEUR SOLANA")
    print("=" * 60)
    
    # Demander confirmation
    response = input("⚠️ Voulez-vous nettoyer la base de données? (o/N): ")
    if response.lower() not in ['o', 'oui', 'y', 'yes']:
        print("❌ Nettoyage annulé")
        return
    
    # Créer une sauvegarde
    print("\n📦 Création d'une sauvegarde...")
    backup_ok = backup_database()
    
    if not backup_ok:
        response = input("⚠️ Impossible de créer une sauvegarde. Continuer? (o/N): ")
        if response.lower() not in ['o', 'oui', 'y', 'yes']:
            print("❌ Nettoyage annulé")
            return
    
    # Effectuer le nettoyage
    success = cleanup_database()
    
    if success:
        print("\n🎉 Nettoyage réussi!")
        print("💡 Vous pouvez maintenant relancer le moniteur avec:")
        print("   python start_monitor.py")
    else:
        print("\n❌ Nettoyage échoué")
        if backup_ok:
            print("💡 Vous pouvez restaurer la sauvegarde si nécessaire")

if __name__ == "__main__":
    main()