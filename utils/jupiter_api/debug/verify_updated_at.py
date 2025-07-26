#!/usr/bin/env python3
"""
🔍 Vérification que updated_at fonctionne correctement
"""

import sqlite3
from datetime import datetime, timedelta

def check_updated_at_functionality():
    """Vérifier que updated_at fonctionne"""
    conn = sqlite3.connect("../tokens.db")
    cursor = conn.cursor()
    
    print("=== VÉRIFICATION UPDATED_AT ===\n")
    
    # 1. Vérifier que la colonne existe
    cursor.execute("PRAGMA table_info(tokens)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'updated_at' in columns:
        print("✅ Colonne 'updated_at' existe")
    else:
        print("❌ Colonne 'updated_at' manquante !")
        conn.close()
        return
    
    # 2. Vérifier les données récentes
    cursor.execute('''
        SELECT 
            COUNT(*) as total_tokens,
            COUNT(updated_at) as tokens_with_updated_at,
            MIN(updated_at) as oldest_update,
            MAX(updated_at) as newest_update
        FROM tokens
    ''')
    
    stats = cursor.fetchone()
    print(f"📊 Statistiques:")
    print(f"   Total tokens: {stats[0]}")
    print(f"   Avec updated_at: {stats[1]}")
    print(f"   Plus ancien update: {stats[2]}")
    print(f"   Plus récent update: {stats[3]}")
    
    # 3. Tokens mis à jour dans les 10 dernières minutes
    cursor.execute('''
        SELECT address, symbol, updated_at, first_discovered_at
        FROM tokens 
        WHERE updated_at > datetime('now', '-10 minutes')
        ORDER BY updated_at DESC
        LIMIT 10000
    ''')
    
    recent_updates = cursor.fetchall()
    print(f"\n🔥 Tokens mis à jour dans les 10 dernières minutes: {len(recent_updates)}")
    
    for addr, symbol, updated, discovered in recent_updates:
        print(f"   {symbol or 'UNKNOWN'} ({addr[:8]}...) - Updated: {updated}")
    
    # 4. Comparer updated_at vs first_discovered_at
    cursor.execute('''
        SELECT address, symbol, first_discovered_at, updated_at,
               (julianday(updated_at) - julianday(first_discovered_at)) * 24 * 60 as diff_minutes
        FROM tokens 
        WHERE updated_at != first_discovered_at
        AND first_discovered_at > datetime('now', '-1 hour')
        ORDER BY updated_at DESC
        LIMIT 5
    ''')
    
    enriched_tokens = cursor.fetchall()
    print(f"\n⚡ Tokens enrichis (updated_at > first_discovered_at): {len(enriched_tokens)}")
    
    for addr, symbol, discovered, updated, diff in enriched_tokens:
        print(f"   {symbol or 'UNKNOWN'} - Enrichi en {diff:.1f} minutes")
        print(f"     Découvert: {discovered}")
        print(f"     Mis à jour: {updated}")
    
    # 5. Tokens qui ont besoin d'être re-enrichis (pas d'update récent)
    cursor.execute('''
        SELECT address, symbol, updated_at, invest_score
        FROM tokens 
        WHERE updated_at < datetime('now', '-2 hours')
        AND first_discovered_at > datetime('now', '-24 hours')
        AND (symbol IS NULL OR symbol = 'UNKNOWN')
        ORDER BY updated_at ASC
        LIMIT 5
    ''')
    
    stale_tokens = cursor.fetchall()
    print(f"\n⚠️  Tokens qui ont besoin d'être re-enrichis: {len(stale_tokens)}")
    
    for addr, symbol, updated, score in stale_tokens:
        print(f"   {addr[:8]}... - Dernière MAJ: {updated}")
    
    # 6. Test de fonctionnement en temps réel
    print(f"\n🔄 Test en temps réel...")
    print("Surveillez votre scanner - vous devriez voir des tokens avec:")
    print("- updated_at récent (quelques secondes)")
    print("- updated_at > first_discovered_at (après enrichissement)")
    
    conn.close()

# Requêtes SQL pratiques pour monitoring manuel
sql_queries = {
    "tokens_récents": '''
        SELECT symbol, updated_at, invest_score
        FROM tokens 
        WHERE updated_at > datetime('now', '-5 minutes')
        ORDER BY updated_at DESC;
    ''',
    
    "enrichissement_actif": '''
        SELECT 
            COUNT(*) as enrichis_derniere_heure
        FROM tokens 
        WHERE updated_at > first_discovered_at
        AND updated_at > datetime('now', '-1 hour');
    ''',
    
    "tokens_à_re_enrichir": '''
        SELECT address, symbol, updated_at
        FROM tokens 
        WHERE updated_at < datetime('now', '-2 hours')
        AND (symbol IS NULL OR symbol = 'UNKNOWN')
        LIMIT 10;
    ''',
    
    "activité_enrichissement": '''
        SELECT 
            strftime('%H:%M', updated_at) as heure,
            COUNT(*) as nb_updates
        FROM tokens 
        WHERE updated_at > datetime('now', '-1 hour')
        GROUP BY strftime('%H:%M', updated_at)
        ORDER BY heure DESC;
    '''
}

def watch_updates_live():
    """Surveiller les mises à jour en temps réel"""
    import time
    
    print("🔴 SURVEILLANCE EN TEMPS RÉEL (Ctrl+C pour arrêter)")
    print("Vérification toutes les 30 secondes...\n")
    
    last_count = 0
    
    try:
        while True:
            conn = sqlite3.connect("../tokens.db")
            cursor = conn.cursor()
            
            # Compter les updates récentes
            cursor.execute('''
                SELECT COUNT(*) FROM tokens 
                WHERE updated_at > datetime('now', '-30 seconds')
            ''')
            current_count = cursor.fetchone()[0]
            
            # Récupérer les derniers tokens mis à jour
            cursor.execute('''
                SELECT symbol, invest_score, updated_at
                FROM tokens 
                WHERE updated_at > datetime('now', '-30 seconds')
                ORDER BY updated_at DESC
                LIMIT 3
            ''')
            recent = cursor.fetchall()
            
            timestamp = datetime.now().strftime('%H:%M:%S')
            
            if current_count > 0:
                print(f"[{timestamp}] 🔥 {current_count} tokens mis à jour:")
                for symbol, score, updated in recent:
                    print(f"  - {symbol or 'UNKNOWN'} (Score: {score or 0}) à {updated}")
            else:
                print(f"[{timestamp}] ⏳ Aucune mise à jour récente...")
            
            conn.close()
            time.sleep(30)
            
    except KeyboardInterrupt:
        print("\n✅ Surveillance arrêtée")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "watch":
        watch_updates_live()
    else:
        check_updated_at_functionality()
        
        print("\n" + "="*50)
        print("📋 COMMANDES UTILES:")
        print("\n# Vérification rapide:")
        print("python verify_updated_at.py")
        print("\n# Surveillance temps réel:")
        print("python verify_updated_at.py watch")
        print("\n# Requête SQL manuelle:")
        print("sqlite3 ../tokens.db \"SELECT symbol, updated_at FROM tokens WHERE updated_at > datetime('now', '-5 minutes') ORDER BY updated_at DESC LIMIT 10;\"")
        print("="*50)

# Commandes SQLite directes pour vérification rapide
print("""
🔧 VÉRIFICATIONS RAPIDES AVEC SQLITE3:

# 1. Tokens récemment mis à jour
sqlite3 ../tokens.db "SELECT symbol, updated_at, invest_score FROM tokens WHERE updated_at > datetime('now', '-5 minutes') ORDER BY updated_at DESC LIMIT 10;"

# 2. Différence entre discovery et update  
sqlite3 ../tokens.db "SELECT symbol, first_discovered_at, updated_at FROM tokens WHERE updated_at != first_discovered_at LIMIT 5;"

# 3. Compter les updates par heure
sqlite3 ../tokens.db "SELECT strftime('%H:00', updated_at) as heure, COUNT(*) FROM tokens WHERE updated_at > datetime('now', '-6 hours') GROUP BY heure ORDER BY heure DESC;"

# 4. Tokens avec enrichissement réussi
sqlite3 ../tokens.db "SELECT COUNT(*) FROM tokens WHERE symbol != 'UNKNOWN' AND updated_at > first_discovered_at;"
""")