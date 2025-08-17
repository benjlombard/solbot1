#!/usr/bin/env python3
"""
Script d'initialisation des wallets dans la base de données
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import get_config
from core.database import get_database_manager
import time

def init_wallets():
    """Initialise tous les wallets configurés dans la base de données"""
    print("🚀 Initialisation des wallets dans la base de données...")
    
    # Charger la configuration
    config = get_config()
    db_manager = get_database_manager()
    
    print(f"📊 Configuration trouvée:")
    print(f"   - Base de données: {config.database.get_full_path()}")
    print(f"   - Wallets configurés: {len(config.wallet.addresses)}")
    
    # Initialiser les wallets dans la base de données
    current_time = int(time.time())
    initialized_count = 0
    updated_count = 0
    
    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        
        for i, wallet_addr in enumerate(config.wallet.addresses, 1):
            try:
                # Vérifier si le wallet existe déjà
                cursor.execute("""
                    SELECT wallet_address, priority_score FROM wallet_priorities 
                    WHERE wallet_address = ?
                """, (wallet_addr,))
                
                existing = cursor.fetchone()
                
                if existing:
                    print(f"   {i:2d}. {wallet_addr[:8]}...{wallet_addr[-8:]} (déjà existant)")
                    updated_count += 1
                else:
                    # Insérer nouveau wallet
                    cursor.execute("""
                        INSERT INTO wallet_priorities 
                        (wallet_address, priority_score, last_scan_time, total_scans, 
                         activity_score, consecutive_empty_scans, best_priority_ever, 
                         worst_priority_ever, updated_at, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        wallet_addr,
                        2.0,  # Priority score par défaut
                        0,    # Jamais scanné
                        0,    # Total scans
                        0.0,  # Activity score
                        0,    # Consecutive empty scans
                        2.0,  # Best priority ever
                        2.0,  # Worst priority ever
                        current_time,  # Updated at
                        current_time   # Created at
                    ))
                    
                    print(f"   {i:2d}. {wallet_addr[:8]}...{wallet_addr[-8:]} (nouveau)")
                    initialized_count += 1
                    
            except Exception as e:
                print(f"   ❌ Erreur pour {wallet_addr}: {e}")
        
        conn.commit()
    
    print(f"\n✅ Initialisation terminée:")
    print(f"   - Nouveaux wallets: {initialized_count}")
    print(f"   - Wallets existants: {updated_count}")
    print(f"   - Total: {initialized_count + updated_count}")
    
    # Vérification
    with db_manager.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM wallet_priorities")
        total_in_db = cursor.fetchone()[0]
        print(f"   - Total en base: {total_in_db}")

if __name__ == "__main__":
    init_wallets()