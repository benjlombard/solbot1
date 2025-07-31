import requests
import json
from typing import Dict, List, Optional

class DexScreenerAPI:
    BASE_URL = "https://api.dexscreener.com/latest/dex"
    
    def __init__(self):
        self.session = requests.Session()
        # Ajouter des headers pour éviter les blocages
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def get_token_pairs(self, token_address: str) -> Optional[Dict]:
        """
        Récupère les paires d'un token depuis DexScreener
        
        Args:
            token_address (str): L'adresse du token (ex: adresse de contrat)
        
        Returns:
            Dict: Données des paires ou None si erreur
        """
        try:
            url = f"{self.BASE_URL}/tokens/{token_address}"
            response = self.session.get(url)
            response.raise_for_status()
            return response.json()
        
        except requests.exceptions.RequestException as e:
            print(f"Erreur lors de la requête API: {e}")
            return None
    
    def extract_liquidity_info(self, pairs_data: Dict) -> List[Dict]:
        """
        Extrait les informations de liquidité de toutes les paires
        
        Args:
            pairs_data (Dict): Données retournées par l'API
        
        Returns:
            List[Dict]: Liste des informations de liquidité
        """
        liquidity_info = []
        
        if not pairs_data or 'pairs' not in pairs_data:
            print("Aucune paire trouvée dans les données")
            return liquidity_info
        
        print(f"Nombre de paires trouvées: {len(pairs_data['pairs'])}")
        
        for i, pair in enumerate(pairs_data['pairs']):
            if pair is None:
                continue
            
            # Vérifier si les données de liquidité existent
            liquidity_data = pair.get('liquidity', {})
            has_liquidity_data = bool(liquidity_data)
            
            # Pour PumpFun et autres DEX sans données de liquidité directes,
            # on peut estimer à partir du market cap et volume
            liquidity_usd = liquidity_data.get('usd', 0) if has_liquidity_data else 0
            liquidity_base = liquidity_data.get('base', 0) if has_liquidity_data else 0
            liquidity_quote = liquidity_data.get('quote', 0) if has_liquidity_data else 0
            
            # Informations sur les transactions
            txns = pair.get('txns', {})
            volume = pair.get('volume', {})
            
            pair_info = {
                'dex_id': pair.get('dexId', 'N/A'),
                'pair_address': pair.get('pairAddress', 'N/A'),
                'base_token': {
                    'address': pair.get('baseToken', {}).get('address', 'N/A'),
                    'name': pair.get('baseToken', {}).get('name', 'N/A'),
                    'symbol': pair.get('baseToken', {}).get('symbol', 'N/A')
                },
                'quote_token': {
                    'address': pair.get('quoteToken', {}).get('address', 'N/A'),
                    'name': pair.get('quoteToken', {}).get('name', 'N/A'),
                    'symbol': pair.get('quoteToken', {}).get('symbol', 'N/A')
                },
                'has_liquidity_data': has_liquidity_data,
                'liquidity_usd': liquidity_usd,
                'liquidity_base': liquidity_base,
                'liquidity_quote': liquidity_quote,
                'volume_24h': volume.get('h24', 0),
                'volume_6h': volume.get('h6', 0),
                'volume_1h': volume.get('h1', 0),
                'volume_5m': volume.get('m5', 0),
                'price_usd': float(pair.get('priceUsd', 0)),
                'price_native': float(pair.get('priceNative', 0)),
                'chain_id': pair.get('chainId', 'N/A'),
                'market_cap': pair.get('marketCap', 0),
                'fdv': pair.get('fdv', 0),
                'pair_created_at': pair.get('pairCreatedAt', 'N/A'),
                'price_change_24h': pair.get('priceChange', {}).get('h24', 0),
                'price_change_6h': pair.get('priceChange', {}).get('h6', 0),
                'txns_24h_buys': txns.get('h24', {}).get('buys', 0),
                'txns_24h_sells': txns.get('h24', {}).get('sells', 0),
                'txns_6h_buys': txns.get('h6', {}).get('buys', 0),
                'txns_6h_sells': txns.get('h6', {}).get('sells', 0),
            }
            
            liquidity_info.append(pair_info)
        
        return liquidity_info
    
    def get_liquidity_data(self, token_address: str) -> List[Dict]:
        """
        Fonction principale pour récupérer les données de liquidité
        
        Args:
            token_address (str): L'adresse du token
        
        Returns:
            List[Dict]: Informations de liquidité formatées
        """
        print(f"Récupération des données pour le token: {token_address}")
        
        # Récupérer les données des paires
        pairs_data = self.get_token_pairs(token_address)
        
        if not pairs_data:
            print("Aucune donnée récupérée")
            return []
        
        # Extraire les informations de liquidité
        liquidity_info = self.extract_liquidity_info(pairs_data)
        
        return liquidity_info

def main():
    # Exemple d'utilisation
    dex_api = DexScreenerAPI()
    
    # Exemple avec l'adresse du token PEPE sur Ethereum
    # Remplacez par l'adresse du token que vous voulez analyser
    token_address = "0x6982508145454Ce325dDbE47a25d4ec3d2311933"  # PEPE token
    
    liquidity_data = dex_api.get_liquidity_data(token_address)
    
    if liquidity_data:
        print(f"\n=== Données de liquidité trouvées pour {len(liquidity_data)} paire(s) ===\n")
        
        for i, pair in enumerate(liquidity_data, 1):
            print(f"Paire {i}:")
            print(f"  DEX: {pair['dex_id']}")
            print(f"  Paire: {pair['base_token']['symbol']}/{pair['quote_token']['symbol']}")
            print(f"  Nom complet: {pair['base_token']['name']}")
            print(f"  Adresse de la paire: {pair['pair_address']}")
            
            # Affichage conditionnel selon la disponibilité des données de liquidité
            if pair['has_liquidity_data']:
                print(f"  ✅ Liquidité USD: ${pair['liquidity_usd']:,.2f}")
                print(f"  ✅ Liquidité Base: {pair['liquidity_base']:,.6f} {pair['base_token']['symbol']}")
                print(f"  ✅ Liquidité Quote: {pair['liquidity_quote']:,.6f} {pair['quote_token']['symbol']}")
            else:
                print(f"  ❌ Données de liquidité non disponibles (typique pour {pair['dex_id']})")
                print(f"  📊 Market Cap: ${pair['market_cap']:,.2f}")
                print(f"  📊 FDV: ${pair['fdv']:,.2f}")
            
            print(f"  💰 Prix USD: ${pair['price_usd']}")
            print(f"  💰 Prix natif: {pair['price_native']} {pair['quote_token']['symbol']}")
            print(f"  📈 Volume 24h: ${pair['volume_24h']:,.2f}")
            print(f"  📈 Volume 6h: ${pair['volume_6h']:,.2f}")
            print(f"  🔄 Transactions 24h: {pair['txns_24h_buys']} achats, {pair['txns_24h_sells']} ventes")
            print(f"  📊 Variation 24h: {pair['price_change_24h']:.2f}%")
            print(f"  📊 Variation 6h: {pair['price_change_6h']:.2f}%")
            
            # Convertir timestamp si disponible
            if pair['pair_created_at'] != 'N/A':
                try:
                    import datetime
                    created_date = datetime.datetime.fromtimestamp(pair['pair_created_at'] / 1000)
                    print(f"  🕒 Paire créée: {created_date.strftime('%Y-%m-%d %H:%M:%S')}")
                except:
                    print(f"  🕒 Paire créée: {pair['pair_created_at']}")
            
            print(f"  ⛓️ Blockchain: {pair['chain_id']}")
            print("-" * 60)
    else:
        print("Aucune donnée de liquidité trouvée")

def example_with_custom_token():
    """
    Exemple pour utiliser avec un token personnalisé
    """
    dex_api = DexScreenerAPI()
    
    # Remplacez par l'adresse de votre token
    custom_token = input("Entrez l'adresse du token à analyser: ").strip()
    
    if custom_token:
        liquidity_data = dex_api.get_liquidity_data(custom_token)
        
        if liquidity_data:
            # Trier par liquidité USD décroissante
            liquidity_data.sort(key=lambda x: x['liquidity_usd'], reverse=True)
            
            print(f"\n=== Informations du token {liquidity_data[0]['base_token']['symbol']} ===\n")
            
            for i, pair in enumerate(liquidity_data[:5], 1):  # Top 5
                print(f"{i}. {pair['base_token']['symbol']}/{pair['quote_token']['symbol']} sur {pair['dex_id']}")
                
                if pair['has_liquidity_data']:
                    print(f"   💧 Liquidité USD: ${pair['liquidity_usd']:,.2f}")
                    print(f"   💧 Base: {pair['liquidity_base']:,.6f} {pair['base_token']['symbol']}")
                    print(f"   💧 Quote: {pair['liquidity_quote']:,.6f} {pair['quote_token']['symbol']}")
                else:
                    print(f"   📊 Market Cap: ${pair['market_cap']:,.2f}")
                    print(f"   📊 FDV: ${pair['fdv']:,.2f}")
                    print(f"   📈 Volume 24h: ${pair['volume_24h']:,.2f}")
                
                print(f"   💰 Prix: ${pair['price_usd']} ({pair['price_change_24h']:+.2f}% 24h)")
                print(f"   🔄 Transactions 24h: {pair['txns_24h_buys']}↗️ / {pair['txns_24h_sells']}↘️")
                print()

def debug_raw_response():
    """
    Fonction de debug pour voir la réponse brute de l'API
    """
    dex_api = DexScreenerAPI()
    
    token_address = input("Entrez l'adresse du token pour debug: ").strip()
    
    if token_address:
        print(f"\n=== DEBUG: Réponse brute de l'API ===")
        pairs_data = dex_api.get_token_pairs(token_address)
        
        if pairs_data:
            print(json.dumps(pairs_data, indent=2))
        else:
            print("Aucune donnée reçue")

if __name__ == "__main__":
    print("=== DexScreener Liquidity Fetcher ===")
    print("1. Exemple avec PEPE token")
    print("2. Token personnalisé")
    print("3. Debug - Voir réponse brute API")
    
    choice = input("Choisissez une option (1, 2 ou 3): ").strip()
    
    if choice == "1":
        main()
    elif choice == "2":
        example_with_custom_token()
    elif choice == "3":
        debug_raw_response()
    else:
        print("Option invalide, exécution de l'exemple par défaut...")
        main()