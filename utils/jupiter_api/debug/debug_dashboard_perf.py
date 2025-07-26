#!/usr/bin/env python3
"""
🔍 Script de debug pour diagnostiquer les écarts entre dashboard et base de données
"""

import sqlite3
import time
from datetime import datetime, timedelta
from collections import defaultdict
import json

def debug_dashboard_metrics(database_path="../tokens.db"):
    """Analyser les écarts entre dashboard et réalité"""
    
    print("🔍 DIAGNOSTIC DES MÉTRIQUES DASHBOARD")
    print("="*60)
    
    conn = sqlite3.connect(database_path)
    cursor = conn.cursor()
    
    # 1. Vérifier l'heure système vs base de données
    cursor.execute("SELECT datetime('now', 'localtime') as db_time")
    db_time = cursor.fetchone()[0]
    system_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    print(f"⏰ Heure système     : {system_time}")
    print(f"⏰ Heure base donnée : {db_time}")
    print()
    
    # 2. Analyser les updates récentes avec différentes fenêtres
    time_windows = [
        ("5 minutes", "'-5 minutes'"),
        ("10 minutes", "'-10 minutes'"),
        ("1 heure", "'-1 hour'"),
        ("24 heures", "'-24 hours'")
    ]
    
    print("📊 ANALYSE DES UPDATES PAR FENÊTRE TEMPORELLE:")
    for window_name, sql_interval in time_windows:
        # Tokens avec updated_at récent
        cursor.execute(f"""
            SELECT COUNT(*) FROM tokens 
            WHERE updated_at > datetime('now', {sql_interval}, 'localtime')
            AND updated_at IS NOT NULL
        """)
        count_updated = cursor.fetchone()[0]
        
        # Tokens avec first_discovered_at récent (nouveaux)
        cursor.execute(f"""
            SELECT COUNT(*) FROM tokens 
            WHERE first_discovered_at > datetime('now', {sql_interval}, 'localtime')
        """)
        count_discovered = cursor.fetchone()[0]
        
        # Tokens enrichis récemment
        cursor.execute(f"""
            SELECT COUNT(*) FROM tokens 
            WHERE updated_at > datetime('now', {sql_interval}, 'localtime')
            AND symbol IS NOT NULL 
            AND symbol != 'UNKNOWN' 
            AND symbol != ''
        """)
        count_enriched = cursor.fetchone()[0]
        
        print(f"   {window_name:<12}: {count_updated:>3} mis à jour | {count_discovered:>3} découverts | {count_enriched:>3} enrichis")
    
    print()
    
    # 3. Détail des 20 dernières updates
    print("📋 DÉTAIL DES 20 DERNIÈRES MISES À JOUR:")
    cursor.execute("""
        SELECT symbol, updated_at, first_discovered_at,
               CASE 
                   WHEN updated_at IS NOT NULL 
                   THEN round((julianday('now', 'localtime') - julianday(updated_at)) * 24 * 60, 1)
                   ELSE NULL 
               END as minutes_ago_updated,
               CASE 
                   WHEN first_discovered_at IS NOT NULL 
                   THEN round((julianday('now', 'localtime') - julianday(first_discovered_at)) * 24 * 60, 1)
                   ELSE NULL 
               END as minutes_ago_discovered
        FROM tokens 
        WHERE updated_at IS NOT NULL
        ORDER BY updated_at DESC 
        LIMIT 20
    """)
    
    results = cursor.fetchall()
    print("   Symbol       | Updated (min ago) | Discovered (min ago) | Updated At")
    print("   " + "-"*75)
    
    recent_5min = 0
    for row in results:
        symbol, updated_at, discovered_at, min_ago_upd, min_ago_disc = row
        symbol = symbol or "UNKNOWN"
        
        if min_ago_upd and min_ago_upd <= 5:
            recent_5min += 1
            indicator = "🔥"
        elif min_ago_upd and min_ago_upd <= 10:
            indicator = "⚡"
        else:
            indicator = "  "
        
        print(f"   {indicator} {symbol:<10} | {min_ago_upd or 'N/A':>13} | {min_ago_disc or 'N/A':>16} | {updated_at}")
    
    print(f"\n✅ Tokens réellement mis à jour dans les 5 dernières minutes: {recent_5min}")
    print()
    
    # 4. Vérifier les doublons potentiels
    print("🔍 VÉRIFICATION DES DOUBLONS:")
    cursor.execute("""
        SELECT symbol, COUNT(*) as count 
        FROM tokens 
        WHERE symbol IS NOT NULL AND symbol != 'UNKNOWN' AND symbol != ''
        GROUP BY symbol 
        HAVING COUNT(*) > 1 
        ORDER BY count DESC 
        LIMIT 10
    """)
    
    duplicates = cursor.fetchall()
    if duplicates:
        print("   Tokens dupliqués détectés:")
        for symbol, count in duplicates:
            print(f"   - {symbol}: {count} occurrences")
    else:
        print("   ✅ Pas de doublons détectés")
    
    print()
    
    # 5. Analyser la cohérence updated_at vs first_discovered_at
    print("🔍 COHÉRENCE DES TIMESTAMPS:")
    cursor.execute("""
        SELECT COUNT(*) FROM tokens 
        WHERE updated_at IS NOT NULL 
        AND first_discovered_at IS NOT NULL
        AND updated_at < first_discovered_at
    """)
    inconsistent = cursor.fetchone()[0]
    
    if inconsistent > 0:
        print(f"   ⚠️  {inconsistent} tokens avec updated_at < first_discovered_at")
    else:
        print("   ✅ Timestamps cohérents")
    
    # 6. Vérifier les NULL values
    cursor.execute("SELECT COUNT(*) FROM tokens WHERE updated_at IS NULL")
    null_updated = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM tokens WHERE first_discovered_at IS NULL")
    null_discovered = cursor.fetchone()[0]
    
    print(f"   Tokens sans updated_at: {null_updated}")
    print(f"   Tokens sans first_discovered_at: {null_discovered}")
    print()
    
    # 7. Simuler le calcul du dashboard
    print("🧮 SIMULATION DU CALCUL DASHBOARD:")
    
    # Si le dashboard utilise une fenêtre glissante de 5 minutes
    now = time.time()
    five_minutes_ago = now - (5 * 60)
    
    print(f"   Timestamp actuel: {now}")
    print(f"   Il y a 5 min: {five_minutes_ago}")
    print(f"   Date actuelle: {datetime.fromtimestamp(now)}")
    print(f"   Date -5min: {datetime.fromtimestamp(five_minutes_ago)}")
    
    # Vérifier si le dashboard pourrait compter autrement
    cursor.execute("""
        SELECT updated_at FROM tokens 
        WHERE updated_at IS NOT NULL
        ORDER BY updated_at DESC 
        LIMIT 200
    """)
    
    all_updates = [row[0] for row in cursor.fetchall()]
    
    # Convertir en timestamps et compter dans différentes fenêtres
    dashboard_counts = {}
    
    for window_minutes in [5, 10, 15, 30]:
        cutoff = datetime.now() - timedelta(minutes=window_minutes)
        cutoff_str = cutoff.strftime('%Y-%m-%d %H:%M:%S')
        
        count = sum(1 for update_str in all_updates if update_str >= cutoff_str)
        dashboard_counts[f"{window_minutes}min"] = count
    
    print(f"\n📊 COMPTAGES SIMULÉS DASHBOARD:")
    for window, count in dashboard_counts.items():
        print(f"   Dernières {window}: {count} tokens")
    
    conn.close()
    
    # 8. Recommandations
    print("\n💡 RECOMMANDATIONS:")
    
    if recent_5min != 150:  # Si écart important
        print("   🔧 Actions suggérées:")
        print("   1. Vérifier la logique de fenêtre temporelle dans performance_monitor.py")
        print("   2. S'assurer que le dashboard utilise la même timezone que la DB")
        print("   3. Vérifier si le compteur inclut les tentatives vs les succès")
        print("   4. Ajouter des logs détaillés dans record_token_update()")
        
        if recent_5min < 150:
            print("   ⚠️  Le dashboard semble surestimer le nombre d'updates")
        else:
            print("   ⚠️  Le dashboard pourrait sous-estimer le nombre d'updates")
    else:
        print("   ✅ Les métriques semblent cohérentes")
    
    print("\n" + "="*60)
    
    return {
        "real_5min_updates": recent_5min,
        "dashboard_claim": 150,  # Valeur vue dans le dashboard
        "discrepancy": abs(recent_5min - 150),
        "simulated_counts": dashboard_counts
    }

def check_performance_monitor_logic():
    """Vérifier la logique du performance monitor"""
    
    print("\n🔍 VÉRIFICATION DE LA LOGIQUE PERFORMANCE MONITOR")
    print("="*60)
    
    try:
        from performance_monitor import performance_monitor
        
        # Vérifier les données en mémoire
        with performance_monitor.lock:
            current_time = time.time()
            window_start = current_time - performance_monitor.window_seconds
            
            recent_updates = [t for t in performance_monitor.update_timestamps if t >= window_start]
            
            print(f"⏰ Fenêtre du monitor: {performance_monitor.window_seconds} secondes")
            print(f"⏰ Timestamp actuel: {current_time}")
            print(f"⏰ Début fenêtre: {window_start}")
            print(f"📊 Updates en mémoire (fenêtre): {len(recent_updates)}")
            print(f"📊 Total updates en mémoire: {len(performance_monitor.update_timestamps)}")
            print(f"📊 Total updates compteur: {performance_monitor.total_updates}")
            
            # Afficher les derniers timestamps
            if performance_monitor.update_timestamps:
                print(f"\n📋 Derniers timestamps d'updates:")
                for i, ts in enumerate(list(performance_monitor.update_timestamps)[-10:]):
                    ago = (current_time - ts) / 60
                    dt = datetime.fromtimestamp(ts)
                    print(f"   {i+1:2}. {dt} (il y a {ago:.1f}min)")
        
        return True
        
    except ImportError:
        print("❌ Module performance_monitor non trouvé")
        return False
    except Exception as e:
        print(f"❌ Erreur lors de la vérification: {e}")
        return False

if __name__ == "__main__":
    # Lancer le diagnostic complet
    result = debug_dashboard_metrics()
    
    # Vérifier la logique du monitor
    check_performance_monitor_logic()
    
    print(f"\n🎯 RÉSUMÉ:")
    print(f"   Dashboard affiche: 150 tokens mis à jour (5min)")
    print(f"   Base de données: {result['real_5min_updates']} tokens mis à jour (5min)")
    print(f"   Écart: {result['discrepancy']} tokens")
    
    if result['discrepancy'] > 10:
        print(f"   ⚠️  Écart significatif détecté!")
        print(f"   🔧 Correction nécessaire dans le code du dashboard")
    else:
        print(f"   ✅ Écart acceptable")