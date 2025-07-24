#!/usr/bin/env python3
"""
Jupiter New Tokens Monitor - Surveillance continue des nouveaux tokens
Usage: python jupiter_monitor.py --interval 5 --limit 10 --max-age 24

Arguments:
    --interval X    : Scanner toutes les X minutes (défaut: 5)
    --limit M       : Afficher M tokens max par scan (défaut: 10)
    --max-age Y     : Tokens de moins de Y heures (défaut: 24)
"""

import requests
import time
import json
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Set

class JupiterNewTokensMonitor:
    """Moniteur de nouveaux tokens via Jupiter API"""
    
    TOKEN_LIST_URL = "https://token.jup.ag/all"
    QUOTE_API_URL = "https://quote-api.jup.ag/v6/quote"
    
    def __init__(self, max_age_hours: int = 24, quiet_mode: bool = False):
        self.max_age_hours = max_age_hours
        self.quiet_mode = quiet_mode  # Mode silencieux
        self.seen_tokens: Set[str] = set()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'JupiterMonitor/1.0',
            'Accept': 'application/json'
        })
        
        # Patterns pour identifier les nouveaux tokens POPULAIRES
        self.hot_patterns = [
            'TRUMP', 'BIDEN', 'ELON', 'AI', 'PEPE', 'DOGE', 'SHIB', 
            'MEME', 'MOON', 'GEM', 'PUMP', 'ROCKET', 'DIAMOND', 'CHAD'
        ]
        
        # Patterns généraux
        self.new_token_patterns = [
            '2024', '2025', 'NEW', 'FRESH', 'LAUNCH', 'BETA', 'V2', 'V3',
            'AI', 'MEME', 'INU', 'DOGE', 'PEPE', 'SHIB', 'BONK',
            'MOON', 'GEM', 'PUMP', 'ROCKET', 'FIRE', 'DIAMOND'
        ]
        
        # Tokens à ignorer (trop établis)
        self.ignore_tokens = {
            'SOL', 'USDC', 'USDT', 'BTC', 'ETH', 'BONK', 'WIF', 
            'JUP', 'ORCA', 'RAY', 'SRM', 'STEP', 'COPE', 'MSOL',
            'USDY', 'USDH', 'UXD', 'PAI', 'ATLAS', 'POLIS'
        }
    
    def get_all_tokens(self) -> List[Dict]:
        """Récupérer tous les tokens de Jupiter"""
        try:
            print(f"📡 Fetching token list from Jupiter...")
            
            response = self.session.get(self.TOKEN_LIST_URL, timeout=30)
            
            if response.status_code == 200:
                tokens = response.json()
                print(f"✅ Retrieved {len(tokens)} tokens from Jupiter")
                return tokens
            else:
                print(f"❌ Error fetching tokens: HTTP {response.status_code}")
                return []
                
        except Exception as e:
            print(f"❌ Exception fetching tokens: {e}")
            return []
    
    def is_potentially_new_token(self, token: Dict) -> bool:
        """Vérifier si un token semble nouveau"""
        try:
            symbol = token.get('symbol', '').upper()
            name = token.get('name', '').upper()
            
            # Ignorer les tokens établis
            if symbol in self.ignore_tokens:
                return False
            
            # Vérifier la longueur du symbole
            if len(symbol) < 2 or len(symbol) > 20:
                return False
            
            # Chercher des patterns de nouveauté
            has_new_pattern = any(
                pattern in symbol or pattern in name 
                for pattern in self.new_token_patterns
            )
            
            # Critères supplémentaires
            looks_new = (
                has_new_pattern or
                len(symbol) <= 6 or  # Symboles courts souvent nouveaux
                symbol.endswith('INU') or
                symbol.startswith('$') or
                '2024' in symbol or '2025' in symbol
            )
            
            return looks_new
            
        except Exception:
            return False
    
    def check_token_activity(self, token_address: str, symbol: str) -> Dict:
        """Vérifier l'activité d'un token (prix, liquidité)"""
        try:
            # Essayer d'obtenir un quote vers USDC
            params = {
                'inputMint': token_address,
                'outputMint': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
                'amount': 1000000,  # 1 token (assume 6 decimales)
                'slippageBps': 500  # 5% slippage
            }
            
            response = self.session.get(
                f"{self.QUOTE_API_URL}/quote",
                params=params,
                timeout=5
            )
            
            if response.status_code == 200:
                quote = response.json()
                output_amount = int(quote.get('outAmount', 0))
                price_usdc = output_amount / 1e6
                
                route_plan = quote.get('routePlan', [])
                dexes = [step.get('swapInfo', {}).get('label', 'Unknown') 
                        for step in route_plan]
                
                return {
                    'has_price': True,
                    'price_usdc': price_usdc,
                    'route_count': len(route_plan),
                    'dexes': dexes[:3],  # Top 3 DEXes
                    'price_impact': quote.get('priceImpactPct', 0)
                }
            else:
                return {'has_price': False, 'error': f"HTTP {response.status_code}"}
                
        except Exception as e:
            return {'has_price': False, 'error': str(e)}
    
    def discover_new_tokens(self, limit: int = 10) -> List[Dict]:
        """Découvrir de nouveaux tokens avec filtrage optimisé"""
        print(f"🔍 Scanning for new tokens (limit: {limit})...")
        
        # Récupérer tous les tokens
        all_tokens = self.get_all_tokens()
        if not all_tokens:
            return []
        
        # OPTIMISATION 1: Pré-filtrer pour réduire les appels API
        print("📋 Pre-filtering tokens...")
        candidates = []
        
        for token in all_tokens:
            token_address = token.get('address')
            symbol = token.get('symbol', 'UNKNOWN')
            
            if not token_address or token_address in self.seen_tokens:
                continue
            
            # Filtres plus stricts AVANT de vérifier le prix
            if self.is_high_quality_candidate(token):
                candidates.append(token)
        
        print(f"📊 Found {len(candidates)} high-quality candidates")
        
        # OPTIMISATION 2: Randomiser l'ordre pour éviter de toujours scanner les mêmes
        import random
        random.shuffle(candidates)
        
        new_discoveries = []
        checked_count = 0
        no_price_count = 0
        
        for token in candidates[:100]:  # Limiter à 100 candidats max
            try:
                token_address = token.get('address')
                symbol = token.get('symbol', 'UNKNOWN')
                
                checked_count += 1
                
                # Affichage plus intelligent
                if checked_count % 10 == 0 or len(new_discoveries) > 0:
                    print(f"   🔍 Progress: {checked_count}/{min(100, len(candidates))} | Found: {len(new_discoveries)} | No price: {no_price_count}")
                
                # Vérifier l'activité
                activity = self.check_token_activity(token_address, symbol)
                
                if activity.get('has_price'):
                    discovery = {
                        'address': token_address,
                        'symbol': symbol,
                        'name': token.get('name', 'Unknown'),
                        'decimals': token.get('decimals', 9),
                        'price_usdc': activity.get('price_usdc', 0),
                        'route_count': activity.get('route_count', 0),
                        'dexes': activity.get('dexes', []),
                        'price_impact': activity.get('price_impact', 0),
                        'discovered_at': datetime.now(),
                        'logo': token.get('logoURI')
                    }
                    
                    new_discoveries.append(discovery)
                    self.seen_tokens.add(token_address)
                    
                    print(f"   🎯 FOUND: {symbol} = ${activity.get('price_usdc', 0):.8f} USDC")
                    
                    if len(new_discoveries) >= limit:
                        break
                else:
                    no_price_count += 1
                    # Ne pas afficher chaque token sans prix
                    if checked_count <= 10:  # Afficher seulement les 10 premiers
                        print(f"   ❌ {symbol}: No liquidity")
                
                # Rate limiting plus agressif pour économiser du temps
                time.sleep(0.1)
                
                # Arrêter si trop de tokens sans prix consécutifs
                if no_price_count > 50 and len(new_discoveries) == 0:
                    print("   ⚠️ Too many tokens without liquidity, stopping early")
                    break
                
            except Exception as e:
                print(f"   ❌ Error checking {symbol}: {e}")
                continue
        
        print(f"✅ Discovery complete: {len(new_discoveries)} new tokens found ({checked_count} checked)")
        return new_discoveries
    
    def is_high_quality_candidate(self, token: Dict) -> bool:
        """Filtrage plus strict pour identifier les candidats de qualité"""
        try:
            symbol = token.get('symbol', '').upper()
            name = token.get('name', '').upper()
            
            # Ignorer les tokens établis
            if symbol in self.ignore_tokens:
                return False
            
            # Vérifier la longueur du symbole (plus strict)
            if len(symbol) < 2 or len(symbol) > 15:
                return False
            
            # Ignorer les tokens avec des symboles suspects
            suspicious_patterns = ['TEST', 'FAKE', 'SCAM', 'NULL', 'UNDEFINED', 'UNKNOWN', 'TEMP', 'DEBUG']
            if any(pattern in symbol or pattern in name for pattern in suspicious_patterns):
                return False
            
            # Privilégier les tokens avec des patterns intéressants
            interesting_patterns = [
                '2024', '2025', 'NEW', 'FRESH', 'AI', 'MEME', 'PEPE', 'DOGE', 
                'INU', 'SHIB', 'MOON', 'GEM', 'PUMP', 'ROCKET', 'DIAMOND',
                'TRUMP', 'BIDEN', 'ELON', 'CHAD', 'BASED', 'WOJAK', 'APU'
            ]
            
            has_interesting_pattern = any(
                pattern in symbol or pattern in name 
                for pattern in interesting_patterns
            )
            
            # Patterns HOT (bonus supplémentaire)
            hot_patterns = ['TRUMP', 'ELON', 'AI', 'PEPE', 'DOGE', 'MEME']
            has_hot_pattern = any(
                pattern in symbol or pattern in name 
                for pattern in hot_patterns
            )
            
            # Autres critères de qualité
            has_logo = bool(token.get('logoURI'))
            reasonable_decimals = token.get('decimals', 9) in [6, 8, 9]
            has_tags = bool(token.get('tags', []))
            
            # Score de qualité
            quality_score = 0
            
            # Points pour patterns
            if has_hot_pattern:
                quality_score += 5  # Bonus pour patterns très populaires
            elif has_interesting_pattern:
                quality_score += 3
            
            # Points pour métadonnées
            if has_logo:
                quality_score += 2  # Logo = plus sérieux
            if reasonable_decimals:
                quality_score += 1
            if has_tags:
                quality_score += 1
            
            # Points pour format du symbole
            if len(symbol) <= 6:  # Symboles courts plus populaires
                quality_score += 1
            if symbol.startswith('$'):  # Format meme populaire
                quality_score += 2
            if symbol.endswith('INU') or symbol.endswith('DOGE'):  # Format chien populaire
                quality_score += 2
            
            # Points pour longueur du nom
            if len(name) > 5 and len(name) < 50:  # Nom raisonnable
                quality_score += 1
            
            # Malus pour certains patterns
            boring_patterns = ['COIN', 'TOKEN', 'FINANCE', 'DEFI', 'YIELD']
            if any(pattern in symbol or pattern in name for pattern in boring_patterns):
                quality_score -= 1
            
            # Retourner True si score >= 3 (plus strict)
            return quality_score >= 3
            
        except Exception:
            return False
    
    def format_discovery_report(self, discoveries: List[Dict]) -> str:
        """Formater le rapport de découverte"""
        if not discoveries:
            return "📭 No new tokens discovered in this scan"
        
        report = f"🆕 NEW TOKENS DISCOVERED ({len(discoveries)})\n"
        report += "=" * 60 + "\n"
        
        for i, token in enumerate(discoveries, 1):
            symbol = token['symbol']
            price = token['price_usdc']
            dexes = ', '.join(token['dexes'][:2]) if token['dexes'] else 'Unknown'
            impact = token['price_impact']
            
            report += f"{i:2d}. {symbol:10s} | ${price:>12.8f} | {dexes:15s}\n"
            report += f"    Address: {token['address'][:8]}...{token['address'][-8:]}\n"
            report += f"    Name: {token['name'][:30]}\n"
            
            if impact > 0:
                report += f"    Price Impact: {impact:.2f}%\n"
            
            report += "\n"
        
        return report
    
    def run_continuous_monitoring(self, interval_minutes: int, limit: int):
        """Lancer la surveillance continue"""
        print("🚀 JUPITER NEW TOKENS MONITOR")
        print("=" * 60)
        print(f"⏰ Scan Interval: {interval_minutes} minutes")
        print(f"📊 Tokens per scan: {limit}")
        print(f"🕐 Max token age: {self.max_age_hours} hours")
        print(f"🔍 Patterns: {', '.join(self.new_token_patterns[:5])}...")
        print("=" * 60)
        print("Press Ctrl+C to stop\n")
        
        scan_count = 0
        total_discoveries = 0
        
        try:
            while True:
                scan_count += 1
                start_time = datetime.now()
                
                print(f"🔄 SCAN #{scan_count} - {start_time.strftime('%H:%M:%S')}")
                print("-" * 40)
                
                # Découvrir de nouveaux tokens
                discoveries = self.discover_new_tokens(limit)
                total_discoveries += len(discoveries)
                
                # Afficher le rapport
                report = self.format_discovery_report(discoveries)
                print(report)
                
                # Statistiques
                duration = (datetime.now() - start_time).total_seconds()
                print(f"📊 Scan completed in {duration:.1f}s")
                print(f"📈 Total discoveries: {total_discoveries}")
                print(f"💾 Known tokens: {len(self.seen_tokens)}")
                
                # Attendre le prochain scan
                next_scan = start_time + timedelta(minutes=interval_minutes)
                print(f"⏰ Next scan at: {next_scan.strftime('%H:%M:%S')}")
                print("\n" + "="*60 + "\n")
                
                # Sleep jusqu'au prochain scan
                sleep_time = interval_minutes * 60
                time.sleep(sleep_time)
                
        except KeyboardInterrupt:
            print(f"\n🛑 Monitoring stopped by user")
            print(f"📊 Final stats:")
            print(f"   Total scans: {scan_count}")
            print(f"   Total discoveries: {total_discoveries}")
            print(f"   Known tokens: {len(self.seen_tokens)}")

def main():
    """Fonction principale avec arguments CLI"""
    parser = argparse.ArgumentParser(
        description='Jupiter New Tokens Monitor - Surveillance continue des nouveaux tokens',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Scan toutes les 5 minutes, 10 tokens max, âge < 24h
    python jupiter_monitor.py --interval 5 --limit 10 --max-age 24
    
    # Scan rapide toutes les 2 minutes
    python jupiter_monitor.py --interval 2 --limit 5
    
    # Scan approfondi toutes les 15 minutes
    python jupiter_monitor.py --interval 15 --limit 20 --max-age 12
        """
    )
    
    parser.add_argument('--interval', '-i', type=int, default=5,
                       help='Intervalle entre scans en minutes (défaut: 5)')
    parser.add_argument('--limit', '-l', type=int, default=10,
                       help='Nombre max de tokens par scan (défaut: 10)')
    parser.add_argument('--max-age', '-a', type=int, default=24,
                       help='Âge max des tokens en heures (défaut: 24)')
    
    parser.add_argument('--quiet', '-q', action='store_true',
                       help='Mode silencieux (moins de logs)')
    parser.add_argument('--fast', '-f', action='store_true',
                       help='Mode rapide (filtrage plus agressif)')
    
    args = parser.parse_args()
    
    # Validation des arguments
    if args.interval < 1:
        print("❌ Error: interval must be >= 1 minute")
        return 1
    
    if args.limit < 1 or args.limit > 50:
        print("❌ Error: limit must be between 1 and 50")
        return 1
    
    if args.max_age < 1:
        print("❌ Error: max-age must be >= 1 hour")
        return 1
    
    # Créer et lancer le moniteur
    monitor = JupiterNewTokensMonitor(max_age_hours=args.max_age, quiet_mode=args.quiet)
    
    # Mode rapide : filtrage plus agressif
    if args.fast:
        monitor.ignore_tokens.update(['USDY', 'USDH', 'UXD', 'PAI', 'ATLAS', 'POLIS', 'MATIC', 'AVAX'])
        print("⚡ Fast mode enabled - aggressive filtering")
    
    monitor.run_continuous_monitoring(args.interval, args.limit)
    
    return 0

if __name__ == "__main__":
    exit(main())
