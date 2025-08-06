#!/usr/bin/env python3
"""
Script de vérification de santé du moniteur Solana
Exécute automatiquement les requêtes de diagnostic
"""

import sqlite3
import time
from datetime import datetime
from typing import List, Dict, Any

class HealthChecker:
    def __init__(self, db_name: str = "solana_wallet.db"):
        self.db_name = db_name
    
    def execute_query(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Exécute une requête et retourne les résultats"""
        try:
            conn = sqlite3.connect(self.db_name)
            conn.row_factory = sqlite3.Row  # Pour avoir des dictionnaires
            cursor = conn.cursor()
            cursor.execute(query, params)
            results = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return results
        except Exception as e:
            print(f"❌ Erreur requête: {e}")
            return []
    
    def check_wallet_configuration(self):
        """Vérifie la configuration des wallets"""
        print("🔧 CONFIGURATION DES WALLETS")
        print("-" * 50)
        
        query = """
        SELECT 
            wallet_address,
            priority_score,
            total_scans,
            last_scan_time,
            datetime(last_scan_time, 'unixepoch', '+2 hours') as last_scan_human,
            consecutive_empty_scans,
            activity_score
        FROM wallet_priorities 
        ORDER BY priority_score DESC
        """
        
        results = self.execute_query(query)
        if results:
            for wallet in results:
                addr = wallet['wallet_address']
                print(f"📱 {addr[:8]}...{addr[-8:]}")
                print(f"   🎯 Priorité: {wallet['priority_score']:.2f}")
                print(f"   📊 Scans effectués: {wallet['total_scans']}")
                print(f"   ⏰ Dernier scan: {wallet['last_scan_human'] or 'Jamais'}")
                print(f"   💤 Scans vides: {wallet['consecutive_empty_scans']}")
                print()
        else:
            print("❌ Aucun wallet configuré")
    
    def check_recent_scans(self):
        """Vérifie les scans récents"""
        print("🔍 SCANS RÉCENTS (24H)")
        print("-" * 50)
        
        query = """
        SELECT 
            wallet_address,
            scan_type,
            total_accounts,
            new_accounts,
            scan_duration,
            efficiency_score,
            activity_detected,
            datetime(completed_at, 'unixepoch', '+2 hours') as scan_time
        FROM scan_history 
        WHERE completed_at >= strftime('%s', 'now', '-24 hours')
        ORDER BY completed_at DESC
        LIMIT 10
        """
        
        results = self.execute_query(query)
        if results:
            for scan in results:
                addr = scan['wallet_address']
                print(f"📊 {addr[:8]}... - {scan['scan_time']}")
                print(f"   🔍 Type: {scan['scan_type']}")
                print(f"   📈 Comptes: {scan['total_accounts']} ({scan['new_accounts']} nouveaux)")
                print(f"   ⏱️ Durée: {scan['scan_duration']:.1f}s")
                print(f"   📊 Efficacité: {scan['efficiency_score']:.1f}%")
                print(f"   🎯 Activité: {'✅' if scan['activity_detected'] else '❌'}")
                print()
        else:
            print("❌ Aucun scan récent")
    
    def check_token_accounts(self):
        """Vérifie les comptes de tokens"""
        print("🪙 COMPTES DE TOKENS")
        print("-" * 50)
        
        # Résumé par wallet
        query = """
        SELECT 
            wallet_address,
            COUNT(*) as total_accounts,
            COUNT(CASE WHEN scan_priority >= 3 THEN 1 END) as high_priority_accounts,
            COUNT(CASE WHEN last_scanned IS NULL THEN 1 END) as never_scanned,
            COUNT(CASE WHEN last_scanned >= strftime('%s', 'now', '-1 hour') THEN 1 END) as scanned_recently
        FROM token_accounts 
        WHERE is_active = 1
        GROUP BY wallet_address
        """
        
        results = self.execute_query(query)
        for wallet in results:
            addr = wallet['wallet_address']
            print(f"📱 {addr[:8]}...{addr[-8:]}")
            print(f"   📊 Total comptes: {wallet['total_accounts']}")
            print(f"   🔥 Haute priorité: {wallet['high_priority_accounts']}")
            print(f"   🆕 Jamais scannés: {wallet['never_scanned']}")
            print(f"   ⏰ Scannés récemment: {wallet['scanned_recently']}")
        
        # Nouvelles découvertes
        print("\n🆕 NOUVEAUX COMPTES (24H)")
        print("-" * 30)
        
        query = """
        SELECT 
            wallet_address,
            token_mint,
            balance,
            datetime(first_seen, 'unixepoch', '+2 hours') as discovered_at
        FROM token_accounts 
        WHERE first_seen >= strftime('%s', 'now', '-24 hours')
        AND is_active = 1
        ORDER BY first_seen DESC
        LIMIT 5
        """
        
        new_accounts = self.execute_query(query)
        if new_accounts:
            for account in new_accounts:
                addr = account['wallet_address']
                mint = account['token_mint']
                print(f"🆕 {addr[:8]}... - {mint[:8]}...")
                print(f"   💰 Balance: {account['balance']}")
                print(f"   ⏰ Découvert: {account['discovered_at']}")
        else:
            print("❌ Aucune nouvelle découverte")
    
    def check_balance_changes(self):
        """Vérifie les balance changes récents"""
        print("\n💰 BALANCE CHANGES RÉCENTS (24H)")
        print("-" * 50)
        
        query = """
        SELECT 
            wallet_address,
            transaction_type,
            token_symbol,
            token_amount,
            amount as sol_change,
            is_large_token_amount,
            datetime(block_time, 'unixepoch', '+2 hours') as transaction_time,
            detection_delay
        FROM transactions 
        WHERE is_token_transaction = 1 
        AND block_time >= strftime('%s', 'now', '-24 hours')
        ORDER BY block_time DESC
        LIMIT 10
        """
        
        results = self.execute_query(query)
        if results:
            for tx in results:
                addr = tx['wallet_address']
                tx_type = tx['transaction_type'].upper()
                symbol = tx['token_symbol'] or 'UNKNOWN'
                amount = tx['token_amount']
                sol_change = tx['sol_change']
                is_large = "🔥" if tx['is_large_token_amount'] else ""
                
                print(f"💰 {addr[:8]}... - {tx['transaction_time']}")
                print(f"   📈 {tx_type}: {amount:,.4f} {symbol} {is_large}")
                print(f"   💎 SOL: {sol_change:+.4f}")
                print(f"   ⏱️ Délai détection: {tx['detection_delay']:.1f}s")
                print()
        else:
            print("❌ Aucun balance change récent")
    
    def check_system_health(self):
        """Vérifie la santé générale du système"""
        print("\n🏥 SANTÉ DU SYSTÈME")
        print("-" * 50)
        
        # Métriques globales
        metrics_queries = {
            "Wallets configurés": "SELECT COUNT(*) FROM wallet_priorities",
            "Comptes de tokens actifs": "SELECT COUNT(*) FROM token_accounts WHERE is_active = 1",
            "Transactions token (total)": "SELECT COUNT(*) FROM transactions WHERE is_token_transaction = 1",
            "Balance changes (24h)": """
                SELECT COUNT(*) FROM transactions 
                WHERE is_token_transaction = 1 
                AND block_time >= strftime('%s', 'now', '-24 hours')
            """,
            "Nouveaux comptes (24h)": """
                SELECT COUNT(*) FROM token_accounts 
                WHERE first_seen >= strftime('%s', 'now', '-24 hours')
            """,
            "Scans effectués (24h)": """
                SELECT COUNT(*) FROM scan_history 
                WHERE completed_at >= strftime('%s', 'now', '-24 hours')
            """
        }
        
        for metric, query in metrics_queries.items():
            result = self.execute_query(query)
            value = result[0][list(result[0].keys())[0]] if result else 0
            print(f"📊 {metric}: {value:,}")
        
        # État des wallets
        print(f"\n📱 ÉTAT DES WALLETS")
        print("-" * 30)
        
        query = """
        SELECT 
            wallet_address,
            priority_score,
            (strftime('%s', 'now') - last_scan_time) as seconds_since_last_scan,
            CASE 
                WHEN (strftime('%s', 'now') - last_scan_time) < 120 THEN 'Actif'
                WHEN (strftime('%s', 'now') - last_scan_time) < 600 THEN 'Ralenti'
                ELSE 'Inactif'
            END as status
        FROM wallet_priorities
        """
        
        wallet_status = self.execute_query(query)
        for wallet in wallet_status:
            addr = wallet['wallet_address']
            status = wallet['status']
            priority = wallet['priority_score']
            last_scan = wallet['seconds_since_last_scan']
            
            status_icon = "🟢" if status == "Actif" else "🟡" if status == "Ralenti" else "🔴"
            
            print(f"{status_icon} {addr[:8]}... - {status}")
            print(f"   🎯 Priorité: {priority:.2f}")
            print(f"   ⏰ Dernier scan: {last_scan//60}m{last_scan%60}s ago")
    
    def check_performance(self):
        """Vérifie les performances"""
        print("\n⚡ PERFORMANCES")
        print("-" * 50)
        
        # Efficacité moyenne
        query = """
        SELECT 
            AVG(efficiency_score) as avg_efficiency,
            AVG(scan_duration) as avg_duration,
            SUM(discoveries_count) as total_discoveries,
            SUM(balance_changes_count) as total_balance_changes
        FROM wallet_activity_metrics 
        WHERE timestamp >= strftime('%s', 'now', '-24 hours')
        """
        
        perf = self.execute_query(query)
        if perf and perf[0]['avg_efficiency'] is not None:
            p = perf[0]
            print(f"📊 Efficacité moyenne: {p['avg_efficiency']:.1f}%")
            print(f"⏱️ Durée moyenne scan: {p['avg_duration']:.1f}s")
            print(f"🆕 Total découvertes: {p['total_discoveries'] or 0}")
            print(f"💰 Total balance changes: {p['total_balance_changes'] or 0}")
        else:
            print("❌ Pas de données de performance")
    
    def run_full_check(self):
        """Lance toutes les vérifications"""
        print("🏥 VÉRIFICATION COMPLÈTE DU MONITEUR SOLANA")
        print("=" * 70)
        
        # Afficher l'heure locale
        from datetime import datetime, timezone, timedelta
        utc_plus_2 = timezone(timedelta(hours=2))
        local_time = datetime.now(utc_plus_2)
        print(f"📅 {local_time.strftime('%Y-%m-%d %H:%M:%S')} (UTC+2)")
        print()
        
        try:
            self.check_wallet_configuration()
            self.check_recent_scans()
            self.check_token_accounts()
            self.check_balance_changes()
            self.check_system_health()
            self.check_performance()
            
            print("\n✅ VÉRIFICATION TERMINÉE")
            print("=" * 70)
            
        except Exception as e:
            print(f"❌ Erreur lors de la vérification: {e}")

def main():
    """Point d'entrée principal"""
    checker = HealthChecker()
    checker.run_full_check()

if __name__ == "__main__":
    main()