import requests
import unittest
from unittest.mock import patch


class TokenFetcher:
    """
    A class to fetch new token pairs from the DexScreener API.
    
    Attributes:
    - base_url: str
        The base URL for the DexScreener API.
    """
    
    def __init__(self):
        """
        Initializes the TokenFetcher with the base URL for the DexScreener API.
        """
        self.base_url = "https://api.dexscreener.com/latest/dex/tokens"
    
    def fetch_new_tokens(self):
        """
        Fetches new token pairs from the DexScreener API.
        
        Returns:
        - list of dict:
            A list containing dictionaries with token names, symbols, and contract addresses.
            
        Raises:
        - requests.exceptions.RequestException:
            If there is an issue with the API request.
        """
        try:
            response = requests.get(self.base_url)
            response.raise_for_status()  # Raise an error for bad responses
            data = response.json()
            
            tokens = []
            for token in data.get('tokens', []):
                token_info = {
                    'name': token.get('name'),
                    'symbol': token.get('symbol'),
                    'contract_address': token.get('address')
                }
                tokens.append(token_info)
            
            return tokens
            
        except requests.exceptions.RequestException as e:
            raise SystemExit(f"API request failed: {e}")


# Unit tests for TokenFetcher class
class TestTokenFetcher(unittest.TestCase):
    
    def setUp(self):
        """
        Sets up the TokenFetcher instance before each test.
        """
        self.token_fetcher = TokenFetcher()
    
    @patch('requests.get')
    def test_fetch_new_tokens_success(self, mock_get):
        """
        Tests the fetch_new_tokens method for a successful API response.
        """
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'tokens': [
                {'name': 'TokenA', 'symbol': 'TKA', 'address': '0x123'},
                {'name': 'TokenB', 'symbol': 'TKB', 'address': '0x456'}
            ]
        }
        mock_get.return_value.raise_for_status.return_value = None
        
        expected_tokens = [
            {'name': 'TokenA', 'symbol': 'TKA', 'contract_address': '0x123'},
            {'name': 'TokenB', 'symbol': 'TKB', 'contract_address': '0x456'}
        ]
        
        tokens = self.token_fetcher.fetch_new_tokens()
        self.assertEqual(tokens, expected_tokens)
    
    @patch('requests.get')
    def test_fetch_new_tokens_empty_response(self, mock_get):
        """
        Tests the fetch_new_tokens method when the API returns an empty token list.
        """
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            'tokens': []
        }
        mock_get.return_value.raise_for_status.return_value = None
        
        tokens = self.token_fetcher.fetch_new_tokens()
        self.assertEqual(tokens, [])
    
    @patch('requests.get')
    def test_fetch_new_tokens_api_failure(self, mock_get):
        """
        Tests the fetch_new_tokens method when the API request fails.
        """
        mock_get.side_effect = requests.exceptions.RequestException("API error")
        
        with self.assertRaises(SystemExit) as cm:
            self.token_fetcher.fetch_new_tokens()
        
        self.assertEqual(str(cm.exception), "API request failed: API error")


def main():
    """
    Fonction principale pour démontrer l'utilisation du TokenFetcher.
    """
    print("=== DexScreener Token Fetcher ===")
    print("Récupération des nouveaux tokens...\n")
    
    fetcher = TokenFetcher()
    
    try:
        new_tokens = fetcher.fetch_new_tokens()
        
        if new_tokens:
            print(f"Nombre de tokens trouvés: {len(new_tokens)}\n")
            
            for i, token in enumerate(new_tokens, 1):
                print(f"Token {i}:")
                print(f"  Nom: {token['name'] or 'N/A'}")
                print(f"  Symbole: {token['symbol'] or 'N/A'}")
                print(f"  Adresse du contrat: {token['contract_address'] or 'N/A'}")
                print("-" * 50)
        else:
            print("Aucun token trouvé.")
            
    except SystemExit as e:
        print(f"Erreur: {e}")


def run_tests():
    """
    Lance les tests unitaires.
    """
    print("=== Lancement des tests unitaires ===\n")
    unittest.main(argv=[''], exit=False, verbosity=2)


if __name__ == "__main__":
    # Vous pouvez choisir ce que vous voulez exécuter:
    
    # 1. Pour exécuter le programme principal
    main()
    
    # 2. Pour exécuter les tests (décommentez la ligne suivante)
    # run_tests()
    
    # 3. Pour exécuter les deux (décommentez les lignes suivantes)
    # print("\n" + "="*60 + "\n")
    # run_tests()