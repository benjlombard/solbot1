#!/usr/bin/env python3
"""
Correction finale du décalage de 2h détecté
"""

import sqlite3
import os
from datetime import datetime

def fix_timezone_offset():
    """
    Corriger le décalage de 2h pour tous les tokens
    """
    
    database_path = "../tokens.db"
    
    if not os.path.exists(database_path):
        print(f"❌ Base de données {database_path} introuvable!")
        return False
    
    print("🔧 CORRECTION DU DÉCALAGE TIMEZONE")
    print("=" * 50)
    
    try:
        conn = sqlite3.connect(database_path)
        cursor = conn.cursor()
        
        # Sauvegarder l'état avant correction
        cursor.execute("SELECT COUNT(*) FROM tokens WHERE first_discovered_at IS NOT NULL")
        tokens_with_date = cursor.fetchone()[0]
        
        cursor.execute("SELECT MAX(first_discovered_at) FROM tokens")
        latest_before = cursor.fetchone()[0]
        
        print(f"📊 Tokens à corriger: {tokens_with_date}")
        print(f"🕐 Dernière date avant correction: {latest_before}")
        print(f"🕐 Heure PC actuelle: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Demander confirmation
        response = input("\n❓ Voulez-vous corriger TOUS les tokens (+2h) ? (oui/non): ").strip().lower()
        
        if response not in ['oui', 'o', 'yes', 'y']:
            print("⏹️  Correction annulée.")
            return False
        
        print("\n🔄 Correction en cours...")
        
        # 1. Corriger first_discovered_at
        cursor.execute('''
            UPDATE tokens 
            SET first_discovered_at = datetime(first_discovered_at, '+2 hours')
            WHERE first_discovered_at IS NOT NULL
        ''')
        
        affected_first = cursor.rowcount
        print(f"✅ {affected_first} corrections sur first_discovered_at")
        
        # 2. Corriger updated_at
        cursor.execute('''
            UPDATE tokens 
            SET updated_at = datetime(updated_at, '+2 hours')
            WHERE updated_at IS NOT NULL
        ''')
        
        affected_updated = cursor.rowcount
        print(f"✅ {affected_updated} corrections sur updated_at")
        
        # 3. Corriger launch_timestamp s'il existe
        try:
            cursor.execute('''
                UPDATE tokens 
                SET launch_timestamp = datetime(launch_timestamp, '+2 hours')
                WHERE launch_timestamp IS NOT NULL
            ''')
            affected_launch = cursor.rowcount
            print(f"✅ {affected_launch} corrections sur launch_timestamp")
        except:
            print("ℹ️  Pas de colonne launch_timestamp")
        
        # Commit des changements
        conn.commit()
        
        # Vérification après correction
        cursor.execute("SELECT MAX(first_discovered_at) FROM tokens")
        latest_after = cursor.fetchone()[0]
        
        print(f"\n📅 Vérification post-correction:")
        print(f"   Avant: {latest_before}")
        print(f"   Après: {latest_after}")
        
        # Calculer le décalage actuel
        if latest_after:
            try:
                token_time = datetime.fromisoformat(latest_after)
                now = datetime.now()
                diff = now - token_time
                hours_diff = diff.total_seconds() / 3600
                
                print(f"   Décalage actuel: {hours_diff:.1f}h")
                
                if abs(hours_diff) < 0.5:
                    print("🎉 CORRECTION RÉUSSIE! Les timestamps sont maintenant corrects.")
                elif abs(hours_diff) < 2:
                    print("✅ Correction OK, décalage normal.")
                else:
                    print("⚠️  Il reste encore un décalage important.")
                    
            except Exception as e:
                print(f"❌ Erreur lors de la vérification: {e}")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Erreur lors de la correction: {e}")
        return False

def show_recent_tokens_after_fix():
    """
    Afficher les tokens récents après la correction
    """
    
    print("\n📅 TOKENS RÉCENTS APRÈS CORRECTION:")
    print("-" * 40)
    
    try:
        conn = sqlite3.connect("../tokens.db")
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT symbol, first_discovered_at 
            FROM tokens 
            WHERE first_discovered_at IS NOT NULL 
            ORDER BY first_discovered_at DESC 
            LIMIT 5
        ''')
        
        recent = cursor.fetchall()
        
        now = datetime.now()
        print(f"🕐 Heure PC: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        for i, (symbol, date_str) in enumerate(recent, 1):
            symbol_short = (symbol or "UNKNOWN")[:10]
            print(f"{i}. {symbol_short:<12} -> {date_str}")
            
            try:
                token_time = datetime.fromisoformat(date_str)
                diff = now - token_time
                minutes_diff = diff.total_seconds() / 60
                
                if minutes_diff < 60:
                    status = f"✅ Il y a {minutes_diff:.0f} min"
                else:
                    hours_diff = minutes_diff / 60
                    status = f"ℹ️  Il y a {hours_diff:.1f}h"
                
                print(f"   {status}")
                
            except Exception as e:
                print(f"   ❌ Erreur: {e}")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Erreur: {e}")

def generate_scanner_fixes():
    """
    Générer les corrections pour éviter le problème à l'avenir
    """
    
    print(f"\n📝 CORRECTIONS POUR VOS SCANNERS:")
    print("=" * 50)
    
    print(f"\n🔧 1. Dans jup_db_scan_k2_g3_c1.py, fonction save_token_to_db():")
    print("   Remplacez les lignes de timestamp par:")
    print("   ```")
    print("   local_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')")
    print("   ```")
    
    print(f"\n🔧 2. Dans solana_monitor_c3.py, fonction process_new_token():")
    print("   Remplacez les lignes de timestamp par:")
    print("   ```")
    print("   local_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')")
    print("   ```")
    
    print(f"\n🔧 3. Dans token_enricher.py, fonction _update_token_in_db():")
    print("   Ajoutez avant la requête UPDATE:")
    print("   ```")
    print("   # Utiliser l'heure locale pour updated_at")
    print("   cursor.execute('''")
    print("       UPDATE tokens SET ")
    print("           ...,")
    print("           updated_at = ?")
    print("       WHERE address = ?")
    print("   ''', (..., datetime.now().strftime('%Y-%m-%d %H:%M:%S'), address))")
    print("   ```")

if __name__ == "__main__":
    print("🚀 CORRECTION FINALE DU TIMEZONE")
    print("Cette opération va ajouter 2h à TOUS vos tokens.")
    print()
    
    # Étape 1: Corriger les données existantes
    success = fix_timezone_offset()
    
    if success:
        # Étape 2: Vérifier le résultat
        show_recent_tokens_after_fix()
        
        # Étape 3: Donner les instructions pour les scanners
        generate_scanner_fixes()
        
        print(f"\n🎉 CORRECTION TERMINÉE!")
        print("✅ Prochaines étapes:")
        print("1. Modifiez vos scanners avec le code ci-dessus")
        print("2. Redémarrez vos services")
        print("3. Les nouveaux tokens auront la bonne heure")
        
    else:
        print("❌ Correction échouée ou annulée.")