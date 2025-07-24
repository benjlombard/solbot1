"""
Jupiter Token Discovery - Source gratuite pour nouveaux tokens Solana
"""

import requests
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional

class JupiterTokenDiscovery:
    """Découverte de tokens via Jupiter (gratuit)"""
    
    TOKEN_LIST_URL = "https://token.jup.ag/all"
    QUOTE_API_URL = "https://quote-api.jup.ag/v6"
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'SolanaBot/1.0',
            'Accept': 'application/json'
        })
    
    def get_all_tokens(self) -> List[Dict]:
        """Récupérer tous les tokens de Jupiter (gratuit)"""
        try:
            response = self.session.get(self.TOKEN_LIST_URL, timeout=30)
            
            if response.status_code == 200:
                tokens = response.json()
                self.logger.info(f"📊 Jupiter: Retrieved {len(tokens)} tokens")
                return tokens
            else:
                self.logger.error(f"Jupiter API error: {response.status_code}")
                return []
                
        except Exception as e:
            self.logger.error(f"Error fetching Jupiter tokens: {e}")
            return []
    
    def discover_new_tokens_by_activity(self, hours_back: int = 24) -> List[Dict]:
        """
        Découvrir de nouveaux tokens en analysant l'activité récente
        Méthode: chercher des tokens avec peu de données historiques
        """
        try:
            all_tokens = self.get_all_tokens()
            if not all_tokens:
                return []
            
            # Filtrer pour garder seulement les tokens récents/nouveaux
            potential_new_tokens = []
            
            for token in all_tokens:
                # Critères pour identifier les tokens potentiellement nouveaux
                symbol = token.get('symbol', '')
                name = token.get('name', '')
                
                # Skip les stablecoins et tokens bien connus
                if any(known in symbol.upper() for known in ['USDC', 'USDT', 'SOL', 'BTC', 'ETH']):
                    continue
                
                # Skip les tokens avec des noms suspects
                if len(symbol) < 2 or len(symbol) > 20:
                    continue
                
                # Test de prix pour voir si le token est actif
                token_address = token['address']
                has_recent_activity = self._check_token_activity(token_address)
                
                if has_recent_activity:
                    potential_new_tokens.append({
                        'token_address': token_address,
                        'symbol': symbol,
                        'name': name,
                        'decimals': token.get('decimals', 9),
                        'logo_uri': token.get('logoURI'),
                        'source': 'jupiter_discovery',
                        'discovery_method': 'activity_analysis'
                    })
                
                # Limite pour éviter trop d'appels API
                if len(potential_new_tokens) >= 20:
                    break
            
            self.logger.info(f"🆕 Found {len(potential_new_tokens)} potentially new tokens via Jupiter")
            return potential_new_tokens
            
        except Exception as e:
            self.logger.error(f"Error in Jupiter token discovery: {e}")
            return []
    
    def _check_token_activity(self, token_address: str) -> bool:
        """Vérifier si un token a de l'activité récente via Jupiter"""
        try:
            # Essayer d'obtenir un quote pour ce token
            params = {
                'inputMint': token_address,
                'outputMint': 'So11111111111111111111111111111111111111112',  # SOL
                'amount': 1000000,  # 1 token (en unités de base)
                'slippageBps': 300
            }
            
            response = self.session.get(
                f"{self.QUOTE_API_URL}/quote",
                params=params,
                timeout=5
            )
            
            # Si on peut obtenir un quote, le token est actif
            return response.status_code == 200
            
        except Exception:
            return False
    
    def get_tokens_by_search_patterns(self, patterns: List[str] = None) -> List[Dict]:
        """
        Chercher des tokens par patterns dans les nouveaux ajouts
        """
        if patterns is None:
            patterns = ['2024', '2025', 'NEW', 'FRESH', 'LAUNCH', 'V2', 'INU', 'AI']
        
        try:
            all_tokens = self.get_all_tokens()
            matching_tokens = []
            
            for token in all_tokens:
                symbol = token.get('symbol', '').upper()
                name = token.get('name', '').upper()
                
                # Chercher les patterns dans le nom ou symbole
                if any(pattern in symbol or pattern in name for pattern in patterns):
                    # Vérifier que c'est potentiellement nouveau
                    if self._looks_like_new_token(token):
                        matching_tokens.append({
                            'token_address': token['address'],
                            'symbol': token['symbol'],
                            'name': token['name'],
                            'decimals': token.get('decimals', 9),
                            'logo_uri': token.get('logoURI'),
                            'source': 'jupiter_pattern_search',
                            'matched_pattern': next(p for p in patterns if p in symbol or p in name)
                        })
            
            self.logger.info(f"🔍 Found {len(matching_tokens)} tokens matching patterns")
            return matching_tokens[:50]  # Limiter les résultats
            
        except Exception as e:
            self.logger.error(f"Error in pattern search: {e}")
            return []
    
    def _looks_like_new_token(self, token: Dict) -> bool:
        """Heuristiques pour identifier les tokens potentiellement nouveaux"""
        try:
            symbol = token.get('symbol', '')
            name = token.get('name', '')
            
            # Filtres de base
            if len(symbol) < 2 or len(symbol) > 20:
                return False
            
            # Skip les tokens trop établis
            established_tokens = ['USDC', 'USDT', 'SOL', 'BONK', 'WIF', 'JUP', 'ORCA']
            if symbol.upper() in established_tokens:
                return False
            
            # Indicateurs de nouveauté
            new_indicators = ['2024', '2025', 'NEW', 'FRESH', 'BETA', 'V2', 'V3', 'LAUNCH']
            has_new_indicator = any(indicator in symbol.upper() or indicator in name.upper() 
                                  for indicator in new_indicators)
            
            return has_new_indicator
            
        except Exception:
            return False

# Intégration avec votre bot existant
def add_jupiter_discovery_to_bot(bot_instance):
    """Ajouter la découverte Jupiter au bot"""
    
    jupiter_discovery = JupiterTokenDiscovery()
    
    async def get_newest_tokens_jupiter(hours_back: int = 24) -> List[Dict]:
        """Méthode à ajouter au bot pour Jupiter discovery"""
        try:
            # Méthode 1: Par activité
            activity_tokens = jupiter_discovery.discover_new_tokens_by_activity(hours_back)
            
            # Méthode 2: Par patterns
            pattern_tokens = jupiter_discovery.get_tokens_by_search_patterns()
            
            # Combiner et dédupliquer
            all_tokens = activity_tokens + pattern_tokens
            seen_addresses = set()
            unique_tokens = []
            
            for token in all_tokens:
                address = token['token_address']
                if address not in seen_addresses:
                    seen_addresses.add(address)
                    # Ajouter des champs compatibles avec le format existant
                    token.update({
                        'age_hours': 0,  # Inconnu pour Jupiter
                        'liquidity_usd': 0,
                        'volume_24h': 0,
                        'price_usd': 0,
                        'chain_id': 'solana',
                        'created_timestamp': int(time.time())
                    })
                    unique_tokens.append(token)
            
            bot_instance.logger.info(f"🔶 Jupiter Discovery: Found {len(unique_tokens)} potential new tokens")
            return unique_tokens
            
        except Exception as e:
            bot_instance.logger.error(f"Error in Jupiter discovery: {e}")
            return []
    
    # Ajouter la méthode au bot
    bot_instance.get_newest_tokens_jupiter = get_newest_tokens_jupiter
    return jupiter_discovery

# Test de la découverte Jupiter
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    
    jupiter = JupiterTokenDiscovery()
    
    print("🔶 Testing Jupiter Token Discovery...")
    
    # Test 1: Découverte par activité
    new_tokens = jupiter.discover_new_tokens_by_activity(24)
    print(f"📊 Activity-based discovery: {len(new_tokens)} tokens")
    
    for token in new_tokens[:5]:
        print(f"  - {token['symbol']}: {token['token_address'][:8]}...")
    
    # Test 2: Découverte par patterns
    pattern_tokens = jupiter.get_tokens_by_search_patterns()
    print(f"🔍 Pattern-based discovery: {len(pattern_tokens)} tokens")
    
    for token in pattern_tokens[:5]:
        print(f"  - {token['symbol']}: {token['matched_pattern']}")