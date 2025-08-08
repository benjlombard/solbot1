#!/usr/bin/env python3
"""
Script de diagnostic du système de scan Solana Wallet Monitor
"""

import sqlite3
import sys
import os
from pathlib import Path

def check_scan_system():
    """Diagnostic complet du système de scan"""
    
    # 1. Vérifier la base de données
    db_path = Path("solana_wallet_monitor.db")
    if not db_path.exists():
        print("❌ Base de données introuvable:", db_path)
        return
    
    print(f"✅ Base de données trouvée: {db_path}")
    
    # Se connecter à la base
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # 2. Vérifier les tables principales
        print("\n📊 État des tables:")
        
        # wallet_priorities
        cursor.execute("SELECT COUNT(*) FROM wallet_priorities")
        wallet_count = cursor.fetchone()[0]
        print(f"👛 wallet_priorities: {wallet_count} wallets")
        
        # scan_history
        cursor.execute("SELECT COUNT(*) FROM scan_history")
        scan_count = cursor.fetchone()[0]
        print(f"📋 scan_history: {scan_count} scans")
        
        # token_accounts
        cursor.execute("SELECT COUNT(*) FROM token_accounts")
        account_count = cursor.fetchone()[0]
        print(f"🪙 token_accounts: {account_count} comptes")
        
        # transactions
        cursor.execute("SELECT COUNT(*) FROM transactions")
        tx_count = cursor.fetchone()[0]
        print(f"💰 transactions: {tx_count} transactions")
        
        # 3. Analyser wallet_priorities en détail
        print("\n🎯 Top 5 wallets par priorité:")
        cursor.execute("""
            SELECT wallet_address, priority_score, last_scan_time, total_scans,
                   (strftime('%s', 'now') - COALESCE(last_scan_time, 0)) as seconds_since_scan
            FROM wallet_priorities 
            ORDER BY priority_score DESC 
            LIMIT 5
        """)
        
        for row in cursor.fetchall():
            addr = f"{row[0][:8]}...{row[0][-8:]}"
            score = row[1]
            last_scan = row[2] if row[2] else "Jamais"
            total_scans = row[3]
            seconds_ago = row[4] if row[2] else "∞"
            print(f"  • {addr}: score={score}, scans={total_scans}, dernier={seconds_ago}s")
        
        # 4. Vérifier s'il y a des scans récents
        print("\n⏰ Scans récents (dernières 24h):")
        cursor.execute("""
            SELECT COUNT(*), MIN(completed_at), MAX(completed_at)
            FROM scan_history 
            WHERE completed_at >= strftime('%s', 'now', '-24 hours')
        """)
        
        recent_data = cursor.fetchone()
        if recent_data[0] > 0:
            print(f"✅ {recent_data[0]} scans dans les 24 dernières heures")
            print(f"   Premier: {recent_data[1]}")
            print(f"   Dernier: {recent_data[2]}")
        else:
            print("❌ Aucun scan dans les 24 dernières heures")
        
        # 5. Vérifier la configuration des wallets
        print("\n📈 Distribution des priorités:")
        cursor.execute("""
            SELECT 
                CASE 
                    WHEN priority_score >= 4.0 THEN 'HIGH'
                    WHEN priority_score >= 2.0 THEN 'MEDIUM'
                    ELSE 'LOW'
                END as category,
                COUNT(*) as count,
                AVG(priority_score) as avg_score
            FROM wallet_priorities
            GROUP BY category
            ORDER BY avg_score DESC
        """)
        
        for row in cursor.fetchall():
            category, count, avg_score = row
            print(f"  • {category}: {count} wallets (score moyen: {avg_score:.2f})")
        
        # 6. Diagnostic des problèmes potentiels
        print("\n🔍 Diagnostic des problèmes:")
        
        problems = []
        
        if scan_count == 0:
            problems.append("❌ Aucun scan n'a jamais été exécuté")
        
        if wallet_count == 0:
            problems.append("❌ Aucun wallet configuré")
        
        # Vérifier les scans récents
        cursor.execute("""
            SELECT COUNT(*) FROM wallet_priorities 
            WHERE last_scan_time IS NULL OR last_scan_time < strftime('%s', 'now', '-1 hour')
        """)
        outdated = cursor.fetchone()[0]
        
        if outdated == wallet_count:
            problems.append(f"⚠️ Tous les {wallet_count} wallets n'ont pas été scannés récemment")
        elif outdated > wallet_count * 0.5:
            problems.append(f"⚠️ {outdated}/{wallet_count} wallets ont des scans obsolètes")
        
        if not problems:
            problems.append("✅ Aucun problème évident détecté")
        
        for problem in problems:
            print(f"  {problem}")
        
        # 7. Recommandations
        print("\n💡 Recommandations:")
        
        if scan_count == 0:
            print("  1. Vérifier que le processus de scan est démarré")
            print("  2. Vérifier les logs d'erreur du scanner")
            print("  3. Tester manuellement un scan via l'API admin")
        
        if wallet_count > 0 and scan_count == 0:
            print("  4. Les wallets sont configurés mais jamais scannés")
            print("  5. Problème probable dans le démarrage du scanner")
        
        print("  6. Vérifier les endpoints RPC Solana")
        print("  7. Vérifier la configuration dans config.toml")
        
    except Exception as e:
        print(f"❌ Erreur lors du diagnostic: {e}")
    finally:
        conn.close()

def check_processes():
    """Vérifier les processus en cours"""
    print("\n🔄 Processus Python en cours:")
    
    try:
        import psutil
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            if 'python' in proc.info['name'].lower():
                cmdline = ' '.join(proc.info['cmdline']) if proc.info['cmdline'] else ''
                if 'scanner' in cmdline.lower() or 'wallet' in cmdline.lower():
                    print(f"  • PID {proc.info['pid']}: {cmdline}")
    except ImportError:
        print("  (psutil non disponible - impossible de lister les processus)")

def check_config_files():
    """Vérifier les fichiers de configuration"""
    print("\n📁 Fichiers de configuration:")
    
    config_files = [
        "config.toml",
        "config/config.toml", 
        "scanner_wallet/config.toml"
    ]
    
    found_config = False
    for config_path in config_files:
        if Path(config_path).exists():
            print(f"✅ Trouvé: {config_path}")
            found_config = True
            
            # Lire le contenu
            try:
                with open(config_path, 'r') as f:
                    content = f.read()
                    
                if '[scanner]' in content:
                    print("  • Section [scanner] trouvée")
                if '[rpc]' in content:
                    print("  • Section [rpc] trouvée")
                if 'enabled = true' in content:
                    print("  • Scanner activé dans la config")
                elif 'enabled = false' in content:
                    print("  • ⚠️ Scanner désactivé dans la config")
                    
            except Exception as e:
                print(f"  • Erreur lecture: {e}")
        else:
            print(f"❌ Absent: {config_path}")
    
    if not found_config:
        print("⚠️ Aucun fichier de configuration trouvé")

if __name__ == "__main__":
    print("🚀 Diagnostic du système de scan Solana Wallet Monitor")
    print("=" * 60)
    
    check_scan_system()
    check_processes()
    check_config_files()
    
    print("\n" + "=" * 60)
    print("✅ Diagnostic terminé")