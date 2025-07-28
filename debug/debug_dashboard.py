#!/usr/bin/env python3
"""
🔍 Debug Dashboard - Diagnostiquer pourquoi le dashboard est vide
"""

import sqlite3
import requests
import json
from datetime import datetime, timedelta

def check_database_content():
    """Vérifier le contenu de la base de données"""
    print("=== VÉRIFICATION BASE DE DONNÉES ===\n")
    
    conn = sqlite3.connect("../tokens.db")
    cursor = conn.cursor()
    
    try:
        # 1. Nombre total de tokens
        cursor.execute("SELECT COUNT(*) FROM tokens")
        total_tokens = cursor.fetchone()[0]
        print(f"📊 Total tokens en base: {total_tokens}")
        
        # 2. Tokens récents (24h)
        cursor.execute("SELECT COUNT(*) FROM tokens WHERE first_discovered_at > datetime('now', '-24 hours')")
        recent_tokens = cursor.fetchone()[0]
        print(f"🆕 Tokens découverts (24h): {recent_tokens}")
        
        # 3. Tokens tradeables
        cursor.execute("SELECT COUNT(*) FROM tokens WHERE is_tradeable = 1")
        tradeable_tokens = cursor.fetchone()[0]
        print(f"💱 Tokens tradeables: {tradeable_tokens}")
        
        # 4. Tokens avec score élevé
        cursor.execute("SELECT COUNT(*) FROM tokens WHERE invest_score >= 80")
        high_score = cursor.fetchone()[0]
        print(f"🔥 Tokens score >= 80: {high_score}")
        
        # 5. Tokens gradués
        cursor.execute("SELECT COUNT(*) FROM tokens WHERE bonding_curve_status IN ('completed', 'migrated')")
        graduated = cursor.fetchone()[0]
        print(f"🚀 Tokens gradués: {graduated}")
        
        # 6. Derniers tokens ajoutés
        cursor.execute('''
            SELECT symbol, invest_score, is_tradeable, bonding_curve_status, first_discovered_at
            FROM tokens 
            ORDER BY first_discovered_at DESC 
            LIMIT 5
        ''')
        
        latest = cursor.fetchall()
        print(f"\n📋 5 derniers tokens:")
        for symbol, score, tradeable, status, discovered in latest:
            print(f"   {symbol or 'UNKNOWN'} | Score: {score or 0} | Tradeable: {tradeable} | Status: {status or 'N/A'} | {discovered}")
        
        # 7. Problèmes potentiels
        cursor.execute("SELECT COUNT(*) FROM tokens WHERE symbol IS NULL OR symbol = 'UNKNOWN'")
        unknown_symbols = cursor.fetchone()[0]
        
        if unknown_symbols > total_tokens * 0.8:
            print(f"\n⚠️  PROBLÈME: {unknown_symbols}/{total_tokens} tokens non enrichis!")
        
    finally:
        conn.close()

def check_flask_api():
    """Tester l'API Flask"""
    print("\n=== VÉRIFICATION API FLASK ===\n")
    
    api_urls = [
        "http://localhost:5000/api/health",
        "http://localhost:5000/api/stats", 
        "http://localhost:5000/api/top-tokens",
        "http://localhost:5000/api/fresh-gems",
        "http://localhost:5000/api/dashboard-data"
    ]
    
    for url in api_urls:
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                endpoint = url.split('/')[-1]
                
                if endpoint == "health":
                    print(f"✅ {endpoint}: {data.get('status', 'N/A')} - {data.get('token_count', 0)} tokens")
                elif endpoint == "stats":
                    print(f"✅ {endpoint}: Total={data.get('totalTokens', 0)}, High={data.get('highScoreTokens', 0)}")
                elif endpoint in ["top-tokens", "fresh-gems"]:
                    print(f"✅ {endpoint}: {len(data) if isinstance(data, list) else 0} tokens retournés")
                elif endpoint == "dashboard-data":
                    stats = data.get('stats', {})
                    top = data.get('topTokens', [])
                    gems = data.get('newGems', [])
                    print(f"✅ {endpoint}: Stats OK, {len(top)} top tokens, {len(gems)} gems")
            else:
                print(f"❌ {url}: HTTP {response.status_code}")
                
        except requests.exceptions.ConnectionError:
            print(f"❌ {url}: Connexion refusée (Flask pas démarré?)")
        except Exception as e:
            print(f"❌ {url}: {e}")

def fix_dashboard_data_issues():
    """Corriger les problèmes courants du dashboard"""
    print("\n=== CORRECTIONS AUTOMATIQUES ===\n")
    
    conn = sqlite3.connect("tokens.db")
    cursor = conn.cursor()
    
    try:
        # 1. Marquer quelques tokens comme tradeables pour test
        cursor.execute('''
            UPDATE tokens 
            SET is_tradeable = 1 
            WHERE price_usdc > 0 
            AND symbol != 'UNKNOWN' 
            AND symbol IS NOT NULL
            AND is_tradeable = 0
        ''')
        
        fixed_tradeable = cursor.rowcount
        if fixed_tradeable > 0:
            print(f"🔧 Marqué {fixed_tradeable} tokens comme tradeables")
        
        # 2. Créer des scores factices pour les tokens sans score
        cursor.execute('''
            UPDATE tokens 
            SET invest_score = 65 + (ABS(RANDOM()) % 35)
            WHERE invest_score IS NULL 
            AND symbol != 'UNKNOWN'
            LIMIT 10
        ''')
        
        fixed_scores = cursor.rowcount
        if fixed_scores > 0:
            print(f"🔧 Ajouté des scores à {fixed_scores} tokens")
        
        # 3. Simuler quelques graduations pour test
        cursor.execute('''
            UPDATE tokens 
            SET bonding_curve_status = 'completed'
            WHERE bonding_curve_status IS NULL 
            AND invest_score > 70
            AND symbol != 'UNKNOWN'
            LIMIT 3
        ''')
        
        fixed_graduation = cursor.rowcount
        if fixed_graduation > 0:
            print(f"🔧 Simulé {fixed_graduation} graduations")
        
        conn.commit()
        
        # 4. Vérification finale
        cursor.execute("SELECT COUNT(*) FROM tokens WHERE is_tradeable = 1 AND invest_score > 0")
        good_tokens = cursor.fetchone()[0]
        print(f"✅ {good_tokens} tokens avec données complètes")
        
    finally:
        conn.close()

def create_test_data():
    """Créer des données de test si la base est vide"""
    print("\n=== CRÉATION DONNÉES DE TEST ===\n")
    
    conn = sqlite3.connect("tokens.db")
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT COUNT(*) FROM tokens WHERE is_tradeable = 1")
        tradeable_count = cursor.fetchone()[0]
        
        if tradeable_count < 5:
            print("🏗️ Création de données de test...")
            
            test_tokens = [
                ("11111111111111111111111111111111", "TESTCOIN", "Test Coin 1", 95.5, 0.000001, 50000, 1200, "completed"),
                ("22222222222222222222222222222222", "GEMTEST", "Gem Test Token", 87.2, 0.0000023, 75000, 800, "migrated"), 
                ("33333333333333333333333333333333", "MOONSHOT", "Moon Shot Token", 92.1, 0.000005, 120000, 2000, "active"),
                ("44444444444444444444444444444444", "DIAMOND", "Diamond Hands", 78.9, 0.0000012, 30000, 600, "completed"),
                ("55555555555555555555555555555555", "ROCKET", "Rocket Token", 83.4, 0.000003, 85000, 1500, "migrated")
            ]
            
            for addr, symbol, name, score, price, volume, holders, status in test_tokens:
                cursor.execute('''
                    INSERT OR REPLACE INTO tokens (
                        address, symbol, name, invest_score, price_usdc, volume_24h, 
                        holders, bonding_curve_status, is_tradeable, first_discovered_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, datetime('now', '-1 hour'), datetime('now'))
                ''', (addr, symbol, name, score, price, volume, holders, status))
            
            conn.commit()
            print(f"✅ {len(test_tokens)} tokens de test créés")
        else:
            print(f"✅ {tradeable_count} tokens tradeables existants")
            
    finally:
        conn.close()

def restart_flask_instructions():
    """Instructions pour redémarrer Flask"""
    print("\n=== INSTRUCTIONS RESTART ===\n")
    print("🔄 Pour redémarrer le dashboard:")
    print("1. Ctrl+C pour arrêter le processus actuel")
    print("2. python launch_dashboard.py --early --social --holders-growth --limit 15 --interval 1 --database tokens.db --no-browser")
    print("\n🌐 Puis ouvrez: http://localhost:5000/dashboard")
    print("\n📊 Test API direct: http://localhost:5000/api/dashboard-data")

if __name__ == "__main__":
    print("🔍 DIAGNOSTIC DASHBOARD VIDE")
    print("=" * 50)
    
    # 1. Vérifier la base
    check_database_content()
    
    # 2. Tester l'API
    check_flask_api()
    
    # 3. Proposer des corrections
    fix_needed = input("\n🔧 Appliquer les corrections automatiques? (y/N): ").lower() 
    if fix_needed == 'y':
        fix_dashboard_data_issues()
        
        # 4. Créer des données de test si nécessaire
        test_data = input("🏗️ Créer des données de test? (y/N): ").lower()
        if test_data == 'y':
            create_test_data()
    
    # 5. Instructions
    restart_flask_instructions()
    
    print("\n" + "=" * 50)
    print("🎯 VÉRIFICATIONS RAPIDES:")
    print("sqlite3 tokens.db \"SELECT COUNT(*) FROM tokens WHERE is_tradeable = 1;\"")
    print("curl http://localhost:5000/api/stats")
    print("=" * 50)

# Version simplifiée pour vérification rapide
def quick_check():
    conn = sqlite3.connect("tokens.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM tokens")
    total = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM tokens WHERE is_tradeable = 1")
    tradeable = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM tokens WHERE invest_score >= 60")
    good_score = cursor.fetchone()[0]
    
    print(f"📊 DB: {total} total, {tradeable} tradeable, {good_score} score≥60")
    
    try:
        response = requests.get("http://localhost:5000/api/stats", timeout=2)
        if response.status_code == 200:
            data = response.json()
            print(f"🌐 API: {data.get('totalTokens', 0)} total, {data.get('tradeableTokens', 0)} tradeable")
        else:
            print(f"❌ API: HTTP {response.status_code}")
    except:
        print("❌ API: Non accessible")
    
    conn.close()

print("\n💡 Pour un check rapide: python debug_dashboard.py && python -c 'import debug_dashboard; debug_dashboard.quick_check()'")