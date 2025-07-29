#!/usr/bin/env python3
"""
📊 Monitoring whale en temps réel
Surveille les nouvelles détections whale et affiche les stats
"""

import sqlite3
import asyncio
import time
from datetime import datetime, timedelta
from collections import defaultdict

class WhaleMonitor:
    def __init__(self, database_path="tokens.db"):
        self.database_path = database_path
        self.last_check = datetime.now()
        self.running = True
        
    async def monitor_whale_activity(self):
        """Monitoring continu de l'activité whale"""
        print("🐋 === WHALE ACTIVITY MONITOR === 🐋")
        print("Surveillant les nouvelles détections whale...\n")
        
        while self.running:
            try:
                # Vérifier les nouvelles transactions
                new_whales = self.get_new_whale_transactions()
                
                if new_whales:
                    print(f"\n🚨 {len(new_whales)} nouvelles transactions whale détectées!")
                    for whale in new_whales:
                        self.display_whale_transaction(whale)
                
                # Afficher les stats toutes les 30 secondes
                if int(time.time()) % 30 == 0:
                    self.display_whale_stats()
                
                # Vérifier les alertes importantes
                critical_whales = self.check_critical_activity()
                if critical_whales:
                    print(f"\n🔥 ALERTE: {len(critical_whales)} transactions critiques!")
                    for whale in critical_whales:
                        self.display_critical_whale(whale)
                
                await asyncio.sleep(5)  # Check toutes les 5 secondes
                
            except KeyboardInterrupt:
                self.running = False
                print("\n👋 Arrêt du monitoring...")
                break
            except Exception as e:
                print(f"❌ Erreur monitoring: {e}")
                await asyncio.sleep(10)
    
    def get_new_whale_transactions(self):
        """Récupérer les nouvelles transactions whale"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT * FROM whale_transactions_live 
                WHERE created_at > ?
                ORDER BY timestamp DESC
            ''', (self.last_check,))
            
            columns = [desc[0] for desc in cursor.description]
            results = []
            
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            
            # Mettre à jour le timestamp de dernière vérification
            if results:
                self.last_check = datetime.now()
            
            return results
            
        finally:
            conn.close()
    
    def display_whale_transaction(self, whale):
        """Afficher une transaction whale"""
        amount = whale['amount_usd']
        symbol = whale['token_address'][:8] + "..."
        tx_type = whale['transaction_type'].upper()
        wallet = whale['wallet_address'][:8] + "..."
        
        # Emoji selon le montant
        if amount >= 100000:
            emoji = "⚡"
        elif amount >= 50000:
            emoji = "🔥"
        elif tx_type == "SELL":
            emoji = "🔴"
        else:
            emoji = "🟢"
        
        print(f"{emoji} {tx_type} ${amount:,.0f} | {symbol} | {wallet} | {whale['dex_id']}")
    
    def display_critical_whale(self, whale):
        """Afficher une alerte whale critique"""
        print(f"🚨 CRITIQUE: ${whale['amount_usd']:,.0f} {whale['transaction_type']} sur {whale['token_address'][:8]}...")
        print(f"   Wallet: {whale['wallet_address']}")
        print(f"   DEX: {whale['dex_id']} | Label: {whale['wallet_label']}")
    
    def check_critical_activity(self):
        """Vérifier l'activité critique (≥$50K dans les 5 dernières minutes)"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            five_minutes_ago = datetime.now() - timedelta(minutes=5)
            cursor.execute('''
                SELECT * FROM whale_transactions_live 
                WHERE amount_usd >= 50000 
                AND timestamp > ?
                ORDER BY amount_usd DESC
            ''', (five_minutes_ago,))
            
            columns = [desc[0] for desc in cursor.description]
            results = []
            
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            
            return results
            
        finally:
            conn.close()
    
    def display_whale_stats(self):
        """Afficher les statistiques whale"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        try:
            # Stats dernière heure
            cursor.execute('''
                SELECT 
                    COUNT(*) as count,
                    SUM(amount_usd) as volume,
                    AVG(amount_usd) as avg_amount,
                    COUNT(DISTINCT token_address) as unique_tokens
                FROM whale_transactions_live 
                WHERE timestamp > datetime('now', '-1 hour')
            ''')
            
            stats_1h = cursor.fetchone()
            
            # Stats dernières 24h
            cursor.execute('''
                SELECT 
                    COUNT(*) as count,
                    SUM(amount_usd) as volume
                FROM whale_transactions_live 
                WHERE timestamp > datetime('now', '-24 hours')
            ''')
            
            stats_24h = cursor.fetchone()
            
            print(f"\n📊 STATS WHALE:")
            print(f"   1h: {stats_1h[0]} tx | ${stats_1h[1]:,.0f} vol | {stats_1h[3]} tokens")
            print(f"   24h: {stats_24h[0]} tx | ${stats_24h[1]:,.0f} vol")
            
        finally:
            conn.close()

async def monitor_websocket_logs():
    """Monitorer les logs pour vérifier la détection WebSocket"""
    print("📡 Monitoring des logs WebSocket...")
    
    # Observer le fichier de log en temps réel
    import subprocess
    import sys
    
    try:
        # Sur Unix/Linux/Mac
        process = subprocess.Popen(
            ['tail', '-f', 'solana_monitoring.log'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        
        print("👀 Surveillant les logs (Ctrl+C pour arrêter)...")
        
        for line in iter(process.stdout.readline, ''):
            if 'whale' in line.lower() or 'swap' in line.lower():
                print(f"🔍 {line.strip()}")
            
    except FileNotFoundError:
        print("❌ Impossible de surveiller les logs (commande 'tail' non disponible)")
        print("💡 Vérifiez manuellement le fichier 'solana_monitoring.log'")
    except KeyboardInterrupt:
        if 'process' in locals():
            process.terminate()
        print("\n👋 Arrêt du monitoring des logs")

async def test_live_detection():
    """Test complet de la détection en temps réel"""
    
    print("🧪 === TEST DÉTECTION WHALE EN TEMPS RÉEL ===\n")
    
    # Créer un moniteur
    monitor = WhaleMonitor()
    
    # Lancer le monitoring en arrière-plan
    monitor_task = asyncio.create_task(monitor.monitor_whale_activity())
    
    # Lancer aussi le monitoring des logs WebSocket
    log_task = asyncio.create_task(monitor_websocket_logs())
    
    try:
        # Attendre que l'utilisateur arrête
        await asyncio.gather(monitor_task, log_task)
    except KeyboardInterrupt:
        print("\n✅ Tests terminés par l'utilisateur")
        monitor.running = False

if __name__ == "__main__":
    print("🐋 Whale Detection Test Suite")
    print("=" * 50)
    print("1. Créer des données de test")
    print("2. Monitorer l'activité en temps réel") 
    print("3. Monitorer les logs WebSocket")
    
    choice = input("\nChoisissez (1/2/3): ")
    
    if choice == "1":
        # Import et création des données de test
        import sys
        sys.path.append('.')
        asyncio.run(create_realistic_whale_data())
        
    elif choice == "2":
        asyncio.run(WhaleMonitor().monitor_whale_activity())
        
    elif choice == "3":
        asyncio.run(monitor_websocket_logs())
        
    else:
        print("📋 Usage:")
        print("  python whale_test.py  # pour lancer tous les tests")
        print("  python whale_monitor.py  # pour le monitoring continu")