import requests
import time

def test_solscan_apis(token_address):
    """
    Teste différentes endpoints Solscan pour voir lesquelles fonctionnent
    """
    
    # URLs à tester
    test_urls = [
        # API v1 publique
        f"https://public-api.solscan.io/token/transfers/{token_address}",
        f"https://public-api.solscan.io/token/meta?tokenAddress={token_address}",
        f"https://public-api.solscan.io/token/holders?tokenAddress={token_address}",
        
        # API v2 (parfois différente)
        f"https://api.solscan.io/token/transfers/{token_address}",
        f"https://api.solscan.io/token/meta?tokenAddress={token_address}",
        
        # Pro API (nécessite clé)
        f"https://pro-api.solscan.io/v1.0/token/transfers?tokenAddress={token_address}",
    ]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json',
    }
    
    for url in test_urls:
        try:
            print(f"\n🔍 Test: {url}")
            
            response = requests.get(url, headers=headers, timeout=10)
            
            print(f"   Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"   ✅ SUCCÈS! Données reçues: {len(str(data))} chars")
                print(f"   📊 Aperçu: {str(data)[:200]}...")
                
                # Si c'est les transfers, montrer le count
                if 'transfers' in url and isinstance(data, dict):
                    if 'data' in data:
                        print(f"   💰 Nombre de transfers: {len(data.get('data', []))}")
                
            elif response.status_code == 404:
                print(f"   ❌ 404 - Token non trouvé ou pas de données")
            elif response.status_code == 429:
                print(f"   ⚠️ 429 - Rate limit atteint")
            else:
                print(f"   ❌ Erreur: {response.status_code}")
                print(f"   📄 Response: {response.text[:200]}...")
                
        except requests.exceptions.Timeout:
            print(f"   ⏰ Timeout")
        except requests.exceptions.RequestException as e:
            print(f"   ❌ Erreur réseau: {e}")
        
        # Pause entre requêtes pour éviter rate limit
        time.sleep(2)

# Test avec votre token
token_address = "53SDajfns8MnVbLnmbBkaAjgGqf3vBScEgm44E6wZqvA"
test_solscan_apis(token_address)