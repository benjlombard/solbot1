#!/usr/bin/env python3
"""
Test manuel d'un scan pour déboguer le système
"""

import sys
import os
from pathlib import Path
import time
import logging

# Ajouter le path du projet
sys.path.insert(0, str(Path(__file__).parent))

def test_single_scan():
    """Test d'un scan manuel sur un wallet"""
    
    try:
        # Imports
        from core.database import get_database_manager
        from core.config import get_config
        from wallet.scanner import WalletScanner
        from rpc.client import RPCClient
        
        print("🔄 Initialisation du test de scan...")
        
        # Configuration
        config = get_config()
        print(f"✅ Configuration chargée: {config.environment.value}")
        
        # Base de données
        db = get_database_manager()
        print("✅ Base de données connectée")
        
        # Insérer un wallet de test pour le scan
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                test_address = "3DKfZz4iHgu42LGu3ttQxqz6u4m5z9ptuar8pBsRqkKC"
                cursor.execute("""
                    INSERT OR IGNORE INTO wallet_priorities (wallet_address, priority_score, total_scans)
                    VALUES (?, ?, ?)
                """, (test_address, 5.0, 0))
                conn.commit()
                print(f"Inséré wallet de test: {test_address[:8]}...")
        except Exception as e:
            print(f"Erreur insertion wallet de test: {e}")
            return False

        # Récupérer un wallet de test
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT wallet_address, priority_score 
                FROM wallet_priorities 
                ORDER BY priority_score DESC 
                LIMIT 1
            """)
            
            wallet_data = cursor.fetchone()
            if not wallet_data:
                print("❌ Aucun wallet trouvé dans wallet_priorities")
                return
            
            test_wallet = wallet_data[0]
            priority = wallet_data[1]
            
        print(f"🎯 Test avec wallet: {test_wallet[:8]}...{test_wallet[-8:]} (priorité: {priority})")
        
        # Client RPC
        rpc_client = RPCClient()
        print("✅ Client RPC initialisé")
        
        # Scanner
        scanner = WalletScanner()
        print("✅ Scanner initialisé")
        
        # Test de scan
        print("🚀 Lancement du scan de test...")
        start_time = time.time()
        
        scan_result = scanner.scan_wallet(test_wallet)
        
        duration = time.time() - start_time
        
        print(f"✅ Scan terminé en {duration:.2f}s")
        print(f"📊 Résultat: {scan_result}")
        
        # Vérifier que les données sont en base
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Vérifier scan_history
            cursor.execute("""
                SELECT COUNT(*) FROM scan_history 
                WHERE wallet_address = ? AND completed_at >= ?
            """, (test_wallet, start_time - 10))
            
            recent_scans = cursor.fetchone()[0]
            print(f"📋 Nouveaux scans en base: {recent_scans}")
            
            # Vérifier mise à jour du wallet
            cursor.execute("""
                SELECT last_scan_time, total_scans 
                FROM wallet_priorities 
                WHERE wallet_address = ?
            """, (test_wallet,))
            
            wallet_status = cursor.fetchone()
            if wallet_status:
                last_scan = wallet_status[0]
                total_scans = wallet_status[1]
                print(f"👛 Wallet mis à jour: dernier_scan={last_scan}, total={total_scans}")
            else:
                print("❌ Wallet non mis à jour")
        
        return True
        
    except ImportError as e:
        print(f"❌ Erreur d'import: {e}")
        print("💡 Vérifiez que tous les modules sont disponibles")
        return False
    except Exception as e:
        print(f"❌ Erreur pendant le test: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_rpc_connection():
    """Test de la connexion RPC Solana"""
    
    try:
        from rpc.client import RPCClient
        
        print("🔗 Test de connexion RPC...")
        
        client = RPCClient()
        
        # Test basique
        health = client.health_check()
        print(f"✅ RPC Health: {health.get('overall_status', 'UNKNOWN')}")
        
        # Test getAccountInfo sur un compte connu
        system_program = "11111111111111111111111111111111"
        account_info = client.call("getAccountInfo", [system_program])
        
        if account_info and account_info.get('result'):
            print("✅ Test getAccountInfo: OK")
        else:
            print("⚠️ Test getAccountInfo: Pas de données")
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur RPC: {e}")
        return False

def test_database_access():
    """Test d'accès à la base de données"""
    
    try:
        from core.database import get_database_manager
        
        print("💾 Test d'accès base de données...")
        
        db = get_database_manager()
        
        with db.get_connection() as conn:
            cursor = conn.cursor()
            
            # Test lecture
            cursor.execute("SELECT COUNT(*) FROM wallet_priorities")
            wallet_count = cursor.fetchone()[0]
            print(f"✅ Lecture: {wallet_count} wallets")
            
            # Test écriture (scan_history)
            test_time = int(time.time())
            cursor.execute("""
                INSERT INTO scan_history 
                (wallet_address, cycle_id, scan_type, completed_at, scan_duration, new_accounts, total_accounts) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, ("TEST_WALLET_ADDRESS", "test_cycle", "test_scan", test_time, 1.0, 0, 0))
            
            conn.commit()
            print("✅ Écriture: Test OK")
            
            # Nettoyer le test
            cursor.execute("DELETE FROM scan_history WHERE wallet_address = 'TEST_WALLET_ADDRESS'")
            conn.commit()
            print("✅ Nettoyage: OK")
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur base de données: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Test manuel du système de scan")
    print("=" * 50)
    
    # Assurer une base de données propre
    try:
        from core.config import get_config
        db_path = get_config().database.get_full_path()
        if os.path.exists(db_path):
            os.remove(db_path)
            print(f"🧹 Ancienne base de données '{db_path}' supprimée.")
    except Exception as e:
        print(f"⚠️ Impossible de supprimer l'ancienne base de données: {e}")

    # Tests en séquence
    tests = [
        ("Base de données", test_database_access),
        ("Connexion RPC", test_rpc_connection),
        ("Scan complet", test_single_scan)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print(f"\n🔍 Test: {test_name}")
        print("-" * 30)
        
        try:
            success = test_func()
            results.append((test_name, success))
            
            if success:
                print(f"✅ {test_name}: SUCCÈS")
            else:
                print(f"❌ {test_name}: ÉCHEC")
                
        except Exception as e:
            print(f"💥 {test_name}: ERREUR - {e}")
            results.append((test_name, False))
    
    # Résumé
    print("\n" + "=" * 50)
    print("📊 Résumé des tests:")
    
    for test_name, success in results:
        status = "✅ OK" if success else "❌ ÉCHEC"
        print(f"  • {test_name}: {status}")
    
    success_count = sum(1 for _, success in results if success)
    print(f"\n🎯 Score: {success_count}/{len(results)} tests réussis")
    
    if success_count == len(results):
        print("🚀 Tous les tests passent - le scanner devrait fonctionner")
    else:
        print("⚠️ Des problèmes ont été détectés - voir les détails ci-dessus")