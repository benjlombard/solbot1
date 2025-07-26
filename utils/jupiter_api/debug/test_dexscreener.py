#!/usr/bin/env python3
import requests
import json

def analyze_dexscreener_display():
    address = "41vZZpGqBQ2dGxS99cmWZuQuC7X97VbcqiAobp29pump"
    
    print(f"🔍 Analyzing token: {address}")
    print("DexScreener shows: 4.4%")
    print("="*60)
    
    # Récupérer les données complètes
    url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
    response = requests.get(url, timeout=10)
    
    if response.status_code == 200:
        data = response.json()
        pair = data['pairs'][0]
        
        print("📊 Données complètes DexScreener:")
        print(json.dumps(pair, indent=2))
        
        # Extraire les valeurs importantes
        market_cap = pair.get('marketCap', 0)
        liquidity_usd = pair.get('liquidity', {}).get('usd', 0)
        price_usd = float(pair.get('priceUsd', 0))
        
        print(f"\n💰 Valeurs principales:")
        print(f"   Market Cap: ${market_cap:,.2f}")
        print(f"   Liquidity USD: ${liquidity_usd:,.2f}" if liquidity_usd else "   Liquidity USD: N/A")
        print(f"   Price USD: ${price_usd:.8f}")
        
        print(f"\n🧮 Calculs pour retrouver 4.4%:")
        
        # Test différents targets pour market cap
        targets = [69000, 100000, 150000, 200000, 250000, 300000]
        for target in targets:
            if market_cap > 0:
                progress = (market_cap / target) * 100
                print(f"   Target ${target:,}: {progress:.1f}%")
        
        # Chercher automatiquement le target qui donne 4.4%
        if market_cap > 0:
            calculated_target = market_cap / 0.044
            print(f"\n🎯 Target calculé pour 4.4%: ${calculated_target:,.0f}")
        
        print(f"\n📊 Analyses de tous les champs numériques:")
        
        # Vérifier tous les champs pour voir lesquels pourraient donner 4.4%
        def analyze_field(name, value, path=""):
            if isinstance(value, (int, float)) and value > 0:
                # Calculer quel serait le total si ce champ représentait 4.4%
                implied_total = value / 0.044
                if 1000 <= implied_total <= 10000000:  # Range raisonnable
                    print(f"   {path}{name}: {value:,.2f} -> si 4.4%, total = ${implied_total:,.0f}")
                
                # Calculer quel pourcentage ce champ représenterait avec différents totals
                common_totals = [30000, 50000, 69000, 85000, 100000]
                for total in common_totals:
                    if total > value:
                        percentage = (value / total) * 100
                        if 3.0 <= percentage <= 6.0:  # Proche de 4.4%
                            print(f"   {path}{name}: {value:,.2f} / ${total:,} = {percentage:.1f}% ⭐")
        
        # Analyser tous les champs
        for key, value in pair.items():
            if isinstance(value, dict):
                for subkey, subvalue in value.items():
                    analyze_field(subkey, subvalue, f"{key}.")
            else:
                analyze_field(key, value)
        
        # Test spécifique pour les réserves SOL (si disponibles dans les données)
        print(f"\n🔍 Recherche de données de réserves:")
        full_text = json.dumps(pair, indent=2).lower()
        sol_keywords = ['sol', 'reserve', 'bonding', 'curve', 'progress', 'completion']
        for keyword in sol_keywords:
            if keyword in full_text:
                print(f"   Trouvé '{keyword}' dans les données")
    
    else:
        print(f"❌ Erreur API: {response.status_code}")
        print(response.text[:200])

if __name__ == "__main__":
    analyze_dexscreener_display()