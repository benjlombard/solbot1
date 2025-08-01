#!/usr/bin/env python3
"""
📱 Social Media Alpha Scanner
Détecte les signaux alpha sur Twitter, Telegram, Discord
"""

import asyncio
import aiohttp
import json
import re
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import tweepy
import telethon
from telethon import TelegramClient

logger = logging.getLogger('social_scanner')

class SocialAlphaScanner:
    """Scanner pour signaux alpha sur les réseaux sociaux"""
    
    def __init__(self):
        self.twitter_api = None
        self.telegram_client = None
        self.discord_client = None
        
        # Influenceurs crypto à surveiller (score d'influence)
        self.crypto_influencers = {
            # Twitter handles avec scores
            'muradmahmudov': {'score': 95, 'specialty': 'memecoins'},
            'therealcryptoj': {'score': 85, 'specialty': 'solana'},
            'lookonchain': {'score': 90, 'specialty': 'onchain_analysis'},
            'solanafm': {'score': 80, 'specialty': 'solana_ecosystem'},
            'solana': {'score': 75, 'specialty': 'official'},
            'jupiterexchange': {'score': 70, 'specialty': 'dex'},
            # Ajouter plus d'influenceurs
        }
        
        # Channels Telegram à surveiller
        self.telegram_channels = [
            '@SolanaAlpha',
            '@SolanaGems', 
            '@PumpFunAlpha',
            '@SolanaMemeCoins',
            '@SolTradingAlpha'
        ]
        
        # Mots-clés et patterns importants
        self.alpha_keywords = [
            'launching now', 'just launched', 'new token', 'fresh mint',
            'pump.fun', 'bonding curve', 'migration', 'raydium pool',
            'liquidity added', 'dev doxxed', 'audit passed', 'rug safe',
            'low cap gem', 'moonshot', 'x100 potential', 'alpha call'
        ]
        
        # Pattern pour détecter les adresses Solana
        self.solana_pattern = re.compile(r'[A-Za-z0-9]{32,44}')
        
        self.detected_tokens = set()
        self.social_scores = {}
    
    async def start_monitoring(self):
        """Démarrer le monitoring de tous les réseaux sociaux"""
        tasks = []
        
        # Twitter monitoring
        if self.twitter_api:
            tasks.append(self.monitor_twitter())
        
        # Telegram monitoring  
        if self.telegram_client:
            tasks.append(self.monitor_telegram())
        
        # Discord monitoring
        if self.discord_client:
            tasks.append(self.monitor_discord())
        
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def monitor_twitter(self):
        """Monitor Twitter pour signaux alpha"""
        logger.info("🐦 Starting Twitter monitoring...")
        
        while True:
            try:
                # Monitor mentions et tweets des influenceurs
                for handle, info in self.crypto_influencers.items():
                    recent_tweets = await self.get_recent_tweets(handle, count=10)
                    
                    for tweet in recent_tweets:
                        await self.analyze_twitter_content(tweet, info)
                
                # Search pour keywords spécifiques
                for keyword in ['pump.fun', 'new solana token', 'just launched']:
                    tweets = await self.search_twitter(keyword, count=20)
                    
                    for tweet in tweets:
                        await self.analyze_twitter_content(tweet, {'score': 50})
                
                await asyncio.sleep(30)  # Check toutes les 30 secondes
                
            except Exception as e:
                logger.error(f"Twitter monitoring error: {e}")
                await asyncio.sleep(60)
    
    async def monitor_telegram(self):
        """Monitor channels Telegram pour alpha"""
        logger.info("📱 Starting Telegram monitoring...")
        
        while True:
            try:
                for channel in self.telegram_channels:
                    # Récupérer messages récents
                    messages = await self.get_telegram_messages(channel, limit=50)
                    
                    for message in messages:
                        await self.analyze_telegram_message(message, channel)
                
                await asyncio.sleep(15)  # Check toutes les 15 secondes
                
            except Exception as e:
                logger.error(f"Telegram monitoring error: {e}")
                await asyncio.sleep(30)
    
    async def analyze_twitter_content(self, tweet: Dict, influencer_info: Dict):
        """Analyser le contenu Twitter pour alpha"""
        
        text = tweet.get('text', '').lower()
        author = tweet.get('author', {}).get('username', '')
        created_at = tweet.get('created_at')
        
        # Calculer le score de base selon l'influenceur
        base_score = influencer_info.get('score', 50)
        
        # Détecter les adresses Solana
        addresses = self.solana_pattern.findall(tweet.get('text', ''))
        
        if addresses and any(keyword in text for keyword in self.alpha_keywords):
            
            for address in addresses:
                if len(address) >= 32 and address not in self.detected_tokens:
                    
                    # Calculer le score social
                    social_score = self.calculate_social_score(
                        content=text,
                        author_score=base_score,
                        engagement=tweet.get('public_metrics', {}),
                        platform='twitter'
                    )
                    
                    # Créer l'alerte
                    alpha_signal = {
                        'address': address,
                        'source': 'twitter',
                        'author': author,
                        'author_score': base_score,
                        'social_score': social_score,
                        'content': tweet.get('text')[:200],
                        'url': f"https://twitter.com/{author}/status/{tweet.get('id')}",
                        'detected_time': datetime.now(),
                        'engagement': tweet.get('public_metrics', {}),
                        'keywords_found': [kw for kw in self.alpha_keywords if kw in text]
                    }
                    
                    await self.process_social_alpha(alpha_signal)
    
    async def analyze_telegram_message(self, message: Dict, channel: str):
        """Analyser message Telegram pour alpha"""
        
        text = message.get('message', '').lower()
        
        # Détecter adresses Solana
        addresses = self.solana_pattern.findall(message.get('message', ''))
        
        if addresses and any(keyword in text for keyword in self.alpha_keywords):
            
            for address in addresses:
                if len(address) >= 32 and address not in self.detected_tokens:
                    
                    # Score selon le channel
                    channel_scores = {
                        '@SolanaAlpha': 85,
                        '@SolanaGems': 75,
                        '@PumpFunAlpha': 80,
                        '@SolanaMemeCoins': 70,
                        '@SolTradingAlpha': 90
                    }
                    
                    base_score = channel_scores.get(channel, 60)
                    
                    social_score = self.calculate_social_score(
                        content=text,
                        author_score=base_score,
                        engagement={'views': message.get('views', 0)},
                        platform='telegram'
                    )
                    
                    alpha_signal = {
                        'address': address,
                        'source': 'telegram',
                        'channel': channel,
                        'social_score': social_score,
                        'content': message.get('message')[:200],
                        'detected_time': datetime.now(),
                        'views': message.get('views', 0),
                        'keywords_found': [kw for kw in self.alpha_keywords if kw in text]
                    }
                    
                    await self.process_social_alpha(alpha_signal)
    
    def calculate_social_score(self, content: str, author_score: int, 
                              engagement: Dict, platform: str) -> int:
        """Calculer le score social d'un signal"""
        
        score = author_score  # Score de base de l'auteur
        
        # Bonus pour mots-clés premium
        premium_keywords = ['dev doxxed', 'audit passed', 'rug safe', 'just launched', 'migration']
        for keyword in premium_keywords:
            if keyword in content:
                score += 10
        
        # Bonus engagement
        if platform == 'twitter':
            likes = engagement.get('like_count', 0)
            retweets = engagement.get('retweet_count', 0)
            replies = engagement.get('reply_count', 0)
            
            # Engagement élevé = signal plus fort
            if likes > 100: score += 15
            elif likes > 50: score += 10
            elif likes > 20: score += 5
            
            if retweets > 50: score += 15
            elif retweets > 20: score += 10
            elif retweets > 5: score += 5
            
            if replies > 20: score += 10
            elif replies > 10: score += 5
        
        elif platform == 'telegram':
            views = engagement.get('views', 0)
            if views > 1000: score += 15
            elif views > 500: score += 10
            elif views > 100: score += 5
        
        # Pénalités
        spam_indicators = ['pump and dump', 'guaranteed profit', '1000x guaranteed']
        for indicator in spam_indicators:
            if indicator in content:
                score -= 20
        
        # Timing bonus (plus récent = mieux)
        # TODO: Ajouter bonus pour timing récent
        
        return min(max(score, 0), 100)
    
    async def process_social_alpha(self, alpha_signal: Dict):
        """Traiter un signal alpha détecté"""
        
        address = alpha_signal['address']
        
        if address in self.detected_tokens:
            return
        
        self.detected_tokens.add(address)
        
        # Enrichir avec données on-chain rapides
        enriched_signal = await self.enrich_social_signal(alpha_signal)
        
        # Calculer score combiné (social + on-chain)
        combined_score = self.calculate_combined_score(enriched_signal)
        enriched_signal['combined_score'] = combined_score
        
        # Alerte si score élevé
        if combined_score >= 70:
            await self.send_social_alert(enriched_signal)
        
        # Sauvegarder
        await self.save_social_signal(enriched_signal)
        
        logger.info(f"📱 SOCIAL ALPHA: {address[:8]}... | Score: {combined_score} | Source: {alpha_signal['source']}")
    
    async def enrich_social_signal(self, signal: Dict) -> Dict:
        """Enrichir le signal avec données on-chain"""
        
        enriched = signal.copy()
        address = signal['address']
        
        try:
            # Quick check si le token existe déjà
            async with aiohttp.ClientSession() as session:
                
                # Check Pump.fun
                async with session.get(f"https://frontend-api.pump.fun/coins/{address}", timeout=3) as resp:
                    if resp.status == 200:
                        pump_data = await resp.json()
                        enriched.update({
                            'exists_on_pump': True,
                            'market_cap': pump_data.get('usd_market_cap', 0),
                            'symbol': pump_data.get('symbol'),
                            'name': pump_data.get('name'),
                            'created_timestamp': pump_data.get('created_timestamp')
                        })
                
                # Quick RugCheck
                async with session.get(f"https://api.rugcheck.xyz/v1/tokens/{address}/report", timeout=3) as resp:
                    if resp.status == 200:
                        rug_data = await resp.json()
                        enriched['rug_score'] = rug_data.get('score', 50)
        
        except Exception as e:
            logger.debug(f"Social enrichment error for {address}: {e}")
        
        return enriched
    
    def calculate_combined_score(self, signal: Dict) -> int:
        """Score combiné social + on-chain"""
        
        social_score = signal.get('social_score', 50)
        
        # Bonus on-chain
        bonus = 0
        
        # Market cap sweet spot
        market_cap = signal.get('market_cap', 0)
        if 1000 <= market_cap <= 50000:
            bonus += 20
        elif 50000 <= market_cap <= 100000:
            bonus += 10
        
        # Rug score
        rug_score = signal.get('rug_score', 50)
        if rug_score <= 20:
            bonus += 15
        elif rug_score <= 40:
            bonus += 10
        
        # Timing (si très récent)
        created_timestamp = signal.get('created_timestamp')
        if created_timestamp:
            time_diff = datetime.now().timestamp() - created_timestamp
            if time_diff < 300:  # < 5 minutes
                bonus += 25
            elif time_diff < 900:  # < 15 minutes
                bonus += 15
        
        return min(social_score + bonus, 100)
    
    async def send_social_alert(self, signal: Dict):
        """Envoyer alerte pour signal social high-score"""
        
        address = signal['address']
        score = signal['combined_score']
        source = signal['source']
        author = signal.get('author', signal.get('channel', 'Unknown'))
        
        alert_message = f"""
🚨 SOCIAL ALPHA DETECTED 🚨
📍 Token: {address}
📊 Score: {score}/100
📱 Source: {source.upper()}
👤 From: {author}
💰 Market Cap: ${signal.get('market_cap', 0):,.0f}
🛡️ Rug Score: {signal.get('rug_score', 'Unknown')}
🔥 Keywords: {', '.join(signal.get('keywords_found', []))}
📝 Content: {signal.get('content', '')[:100]}...
🔗 URL: {signal.get('url', 'N/A')}
        """
        
        logger.warning(alert_message)
        # TODO: Envoyer via Discord/Telegram/email
    
    async def save_social_signal(self, signal: Dict):
        """Sauvegarder le signal en base de données"""
        # TODO: Implémenter sauvegarde en base
        pass
    
    # Méthodes d'API externes (à implémenter)
    async def get_recent_tweets(self, username: str, count: int = 10) -> List[Dict]:
        """Récupérer tweets récents d'un utilisateur"""
        # TODO: Implémenter avec tweepy ou Twitter API v2
        return []
    
    async def search_twitter(self, query: str, count: int = 20) -> List[Dict]:
        """Rechercher des tweets"""
        # TODO: Implémenter recherche Twitter
        return []
    
    async def get_telegram_messages(self, channel: str, limit: int = 50) -> List[Dict]:
        """Récupérer messages Telegram récents"""
        # TODO: Implémenter avec telethon
        return []


# Configuration et setup
async def setup_social_scanner():
    """Setup du scanner social"""
    
    scanner = SocialAlphaScanner()
    
    # TODO: Configurer les APIs
    # scanner.twitter_api = tweepy.Client(bearer_token="YOUR_TWITTER_BEARER_TOKEN")
    # scanner.telegram_client = TelegramClient('session', api_id, api_hash)
    
    return scanner


# Utilisation
async def main():
    scanner = await setup_social_scanner()
    
    # Test avec signal simulé
    test_signal = {
        'address': 'TestTokenAddress123456789012345678901234',
        'source': 'twitter',
        'author': 'muradmahmudov',
        'social_score': 85,
        'content': 'New gem just launched on pump.fun! Dev doxxed, audit passed. Low cap gem with x100 potential.',
        'url': 'https://twitter.com/test/status/123',
        'detected_time': datetime.now(),
        'engagement': {'like_count': 150, 'retweet_count': 45},
        'keywords_found': ['just launched', 'dev doxxed', 'audit passed', 'low cap gem', 'x100 potential']
    }
    
    await scanner.process_social_alpha(test_signal)

if __name__ == "__main__":
    asyncio.run(main())