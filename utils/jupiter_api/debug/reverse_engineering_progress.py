#!/usr/bin/env python3
import requests
import time
import json

def collect_pump_tokens_data():
    """Collecter des données sur plusieurs tokens Pump.fun pour comprendre la formule"""
    
    print("🔍 Collecting Pump.fun tokens from DexScreener trending...")
    
    # Récupérer les tokens trending Pump.fun
    trending_url = "https://api.dexscreener.com/latest/dex/search/?q=pumpfun"
    
    try:
        response = requests.get(trending_url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            pump_tokens = []
            
            for pair in data.get('pairs', []):
                if pair.get('dexId') == 'pumpfun':
                    pump_tokens.append({
                        'address': pair['baseToken']['address'],
                        'symbol': pair['baseToken']['symbol'],
                        'market_cap': pair.get('marketCap', 0),
                        'pair_address': pair.get('pairAddress')
                    })
            
            print(f"Found {len(pump_tokens)} Pump.fun tokens")
            
            # Analyser chaque token pour voir son pourcentage sur DexScreener
            analyzed_tokens = []
            
            for i, token in enumerate(pump_tokens[:10]):  # Analyser les 10 premiers
                print(f"\n📊 Analyzing {i+1}/10: {token['symbol']} (${token['market_cap']:,.0f})")
                
                # Aller sur la page DexScreener pour récupérer le %
                # (On ne peut pas le récupérer via API, il faut le scraper)
                
                analyzed_tokens.append({
                    'symbol': token['symbol'],
                    'market_cap': token['market_cap'],
                    'address': token['address']
                })
                
                time.sleep(1)  # Éviter le rate limiting
            
            return analyzed_tokens
            
    except Exception as e:
        print(f"Error: {e}")
        return []

def analyze_known_progressions():
    """Analyser avec des progressions connues pour déduire la formule"""
    
    # Données observées manuellement
    known_data = [
        {'market_cap': 5550, 'progress': 4.4, 'token': 'SLOTH'},
        # Ajoutez d'autres observations ici si vous en avez
    ]
    
    print("🧮 Analyzing known progressions...")
    
    for data in known_data:
        mc = data['market_cap']
        prog = data['progress']
        
        print(f"\n📊 {data['token']}: ${mc:,.0f} = {prog}%")
        
        # Calculer différents targets possibles
        linear_target = mc / (prog / 100)
        print(f"   Linear target: ${linear_target:,.0f}")
        
        # Test formules non-linéaires
        import math
        
        # Formule logarithmique
        if mc > 100:
            # log(mc) = a * progress + b
            # Pour trouver a et b, on a besoin de plus de points
            log_mc = math.log(mc)
            a_estimate = log_mc / prog
            print(f"   Log formula estimate: log(mc) / {a_estimate:.3f}")
        
        # Formule racine carrée
        sqrt_mc = math.sqrt(mc)
        sqrt_factor = sqrt_mc / prog
        print(f"   Sqrt formula estimate: sqrt(mc) / {sqrt_factor:.3f}")
        
        # Formule puissance
        for power in [0.5, 0.6, 0.7, 0.8, 0.9]:
            powered_mc = mc ** power
            factor = powered_mc / prog
            print(f"   Power {power}: mc^{power} / {factor:.3f}")

def test_formulas_on_known_token():
    """Tester différentes formules sur le token connu"""
    
    # Données connues
    market_cap = 5550
    expected_progress = 4.4
    
    print(f"🧪 Testing formulas on known xx:")
    print(f"   Market Cap: ${market_cap:,.0f}")
    print(f"   Expected Progress: {expected_progress}%")
    print("-" * 50)
    
    # Test 1: Linear avec différents targets
    targets = [69000, 85000, 100000, 126000, 150000]
    for target in targets:
        calc_progress = (market_cap / target) * 100
        error = abs(calc_progress - expected_progress)
        print(f"   Linear {target//1000}k: {calc_progress:.1f}% (error: {error:.1f})")
    
    # Test 2: Formules non-linéaires
    import math
    
    # Logarithmique
    log_progress = (math.log(market_cap) - 6) * 2.5  # Formule ajustée
    log_error = abs(log_progress - expected_progress)
    print(f"   Logarithmic: {log_progress:.1f}% (error: {log_error:.1f})")
    
    # Racine carrée
    sqrt_progress = (math.sqrt(market_cap) / 17)  # Facteur ajusté
    sqrt_error = abs(sqrt_progress - expected_progress)
    print(f"   Square root: {sqrt_progress:.1f}% (error: {sqrt_error:.1f})")
    
    # Puissance 0.7 (entre linéaire et racine)
    power_progress = (market_cap ** 0.7) / 150
    power_error = abs(power_progress - expected_progress)
    print(f"   Power 0.7: {power_progress:.1f}% (error: {power_error:.1f})")
    
    # Formule par paliers (comme Pump.fun)
    if market_cap <= 10000:
        tier_progress = (market_cap / 2500) * 1  # 1% pour les premiers 2.5k
    elif market_cap <= 30000:
        tier_progress = 4 + ((market_cap - 10000) / 5000) * 1  # Progression lente
    else:
        tier_progress = 8 + ((market_cap - 30000) / 10000) * 2  # Progression normale
    
    tier_error = abs(tier_progress - expected_progress)
    print(f"   Tier-based: {tier_progress:.1f}% (error: {tier_error:.1f})")
    
    print(f"\n🎯 Best formula appears to be: TBD based on more data points")

if __name__ == "__main__":
    print("🔬 Reverse Engineering Pump.fun Progress Formula")
    print("=" * 60)
    
    analyze_known_progressions()
    print("\n" + "=" * 60)
    test_formulas_on_known_token()
    
    collect_pump_tokens_data()