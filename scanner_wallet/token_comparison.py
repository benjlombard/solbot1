#!/usr/bin/env python3
"""
Script de comparaison détaillée pour un token spécifique
Compare les valeurs entre:
- Table tokens
- Table tokens_history (dernier snapshot)
- API DexScreener
- API Pump.fun
- API Rugcheck.xyz

Usage:
    python token_comparison.py                    # Token aléatoire
    python token_comparison.py <token_address>    # Token spécifique
"""

import sqlite3
import requests
import sys
import time
import json
from datetime import datetime
from typing import Dict, Optional, Any, List
import logging
from dataclasses import dataclass
import random

# Try to import tabulate, install if not available
try:
    from tabulate import tabulate
except ImportError:
    print("📦 Installation de tabulate...")
    import subprocess
    import sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "tabulate"])
    from tabulate import tabulate

# Configuration
CONFIG = {
    'db_path': 'solana_wallet_monitor.db',
    'api_timeout': 15,
    'retry_attempts': 3,
    'retry_delay': 2.0,
}

@dataclass
class FieldComparison:
    field_name: str
    tokens_value: Any
    history_value: Any
    dex_value: Any
    pump_value: Any
    rug_value: Any
    tokens_status: str = "N/A"
    history_status: str = "N/A"
    dex_status: str = "N/A"
    pump_status: str = "N/A"
    rug_status: str = "N/A"

class TokenDetailedComparison:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'en-US,en;q=0.9',
        })
        
        # Setup logging
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger('TokenComparison')
        
        # Tolerances pour les comparaisons
        self.tolerances = {
            'price_usd': 5.0,           # 5% pour le prix
            'market_cap': 10.0,         # 10% pour market cap
            'volume_24h': 20.0,         # 20% pour volume (très variable)
            'liquidity_usd': 15.0,      # 15% pour liquidité
            'holder_count': 10,         # 10 holders de différence max
            'top_holder_percentage': 2.0,  # 2% de différence max
            'rug_risk_score': 5.0,      # 5 points de différence max
        }
    
    def get_db_connection(self) -> sqlite3.Connection:
        """Get database connection"""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn
    
    def get_random_token(self) -> Optional[str]:
        """Récupérer un token aléatoire actif"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT address FROM tokens 
                    WHERE is_dead = 0 
                    AND (price_usd > 0 OR market_cap > 0)
                    AND last_price_update > strftime('%s', 'now', '-48 hours')
                    ORDER BY RANDOM() 
                    LIMIT 1
                """)
                result = cursor.fetchone()
                return result[0] if result else None
        except Exception as e:
            self.logger.error(f"Erreur récupération token aléatoire: {e}")
            return None
    
    def get_tokens_data(self, token_address: str) -> Optional[Dict]:
        """Récupérer les données de la table tokens"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM tokens WHERE address = ?", (token_address,))
                result = cursor.fetchone()
                return dict(result) if result else None
        except Exception as e:
            self.logger.error(f"Erreur récupération données tokens: {e}")
            return None
    
    def get_history_data(self, token_address: str) -> Optional[Dict]:
        """Récupérer le dernier snapshot de tokens_history"""
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM tokens_history 
                    WHERE token_address = ? 
                    ORDER BY snapshot_timestamp DESC 
                    LIMIT 1
                """, (token_address,))
                result = cursor.fetchone()
                return dict(result) if result else None
        except Exception as e:
            self.logger.error(f"Erreur récupération données history: {e}")
            return None
    
    def api_request_with_retry(self, url: str, source: str) -> Optional[Dict]:
        """Faire une requête API avec retry"""
        for attempt in range(CONFIG['retry_attempts']):
            try:
                response = self.session.get(url, timeout=CONFIG['api_timeout'])
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:
                    self.logger.warning(f"Rate limit {source}, retry {attempt + 1}")
                    time.sleep(CONFIG['retry_delay'] * (attempt + 1))
                    continue
                else:
                    self.logger.debug(f"{source} HTTP {response.status_code}")
                    break
            except Exception as e:
                self.logger.debug(f"Erreur {source} tentative {attempt + 1}: {e}")
                if attempt < CONFIG['retry_attempts'] - 1:
                    time.sleep(CONFIG['retry_delay'])
        return None
    
    def get_dexscreener_data(self, token_address: str) -> Optional[Dict]:
        """Récupérer les données de DexScreener"""
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        data = self.api_request_with_retry(url, "DexScreener")
        
        if data and 'pairs' in data and data['pairs']:
            # Prendre la pair avec le plus de liquidité
            best_pair = max(data['pairs'], key=lambda x: float(x.get('liquidity', {}).get('usd', 0) or 0))
            return {
                'price_usd': float(best_pair.get('priceUsd', 0) or 0),
                'market_cap': float(best_pair.get('fdv', 0) or 0),
                'volume_5m': float(best_pair.get('volume', {}).get('m5', 0) or 0),
                'volume_1h': float(best_pair.get('volume', {}).get('h1', 0) or 0),
                'volume_6h': float(best_pair.get('volume', {}).get('h6', 0) or 0),
                'volume_24h': float(best_pair.get('volume', {}).get('h24', 0) or 0),
                'price_change_5m': float(best_pair.get('priceChange', {}).get('m5', 0) or 0),
                'price_change_1h': float(best_pair.get('priceChange', {}).get('h1', 0) or 0),
                'price_change_6h': float(best_pair.get('priceChange', {}).get('h6', 0) or 0),
                'price_change_24h': float(best_pair.get('priceChange', {}).get('h24', 0) or 0),
                'liquidity_usd': float(best_pair.get('liquidity', {}).get('usd', 0) or 0),
                'liquidity_sol': float(best_pair.get('liquidity', {}).get('base', 0) or 0),
                'fdv': float(best_pair.get('fdv', 0) or 0),
                'symbol': best_pair.get('baseToken', {}).get('symbol'),
                'name': best_pair.get('baseToken', {}).get('name'),
                'source': 'dexscreener'
            }
        return None
    
    def get_pumpfun_data(self, token_address: str) -> Optional[Dict]:
        """Récupérer les données de Pump.fun"""
        urls = [
            f"https://frontend-api.pump.fun/coins/{token_address}",
            f"https://frontend-api-v2.pump.fun/coins/{token_address}",
            f"https://frontend-api-v3.pump.fun/coins/{token_address}",
        ]
        
        for url in urls:
            data = self.api_request_with_retry(url, "Pump.fun")
            if data and isinstance(data, dict):
                # Vérifier que c'est le bon token
                mint = data.get('mint') or data.get('address') or data.get('tokenAddress')
                if mint and mint.lower() == token_address.lower():
                    # Calculer le prix si pas directement disponible
                    price_usd = 0.0
                    if data.get('usd_market_cap') and data.get('total_supply'):
                        price_usd = float(data.get('usd_market_cap', 0)) / float(data.get('total_supply', 1))
                    
                    return {
                        'symbol': data.get('symbol'),
                        'name': data.get('name'),
                        'price_usd': price_usd,
                        'market_cap': float(data.get('usd_market_cap', 0)),
                        'volume_24h': float(data.get('volume_24h', 0)),
                        'bonding_curve_progress': float(data.get('bonding_curve_progress', 0)),
                        'holder_count': int(data.get('holder_count', 0) or data.get('holders', 0)),
                        'creator_address': data.get('creator'),
                        'timestamp_token_created': int(data.get('created_timestamp', 0) / 1000) if data.get('created_timestamp', 0) > 1e12 else int(data.get('created_timestamp', 0)),
                        'is_verified': data.get('complete', False),
                        'logo_uri': data.get('image_uri'),
                        'source': 'pumpfun'
                    }
        return None
    
    def get_rugcheck_data(self, token_address: str) -> Optional[Dict]:
        """Récupérer les données de Rugcheck"""
        url = f"https://api.rugcheck.xyz/v1/tokens/{token_address}/report"
        data = self.api_request_with_retry(url, "Rugcheck")
        
        if data and isinstance(data, dict):
            # Extraire les données des top holders
            top_holders = data.get('topHolders', [])
            top_holder_percentage = 0.0
            top_10_holders_percentage = 0.0
            insider_holders_count = 0
            
            if isinstance(top_holders, list) and top_holders:
                try:
                    # Top holder
                    if len(top_holders) > 0:
                        top_holder_percentage = float(top_holders[0].get('pct', 0))
                    
                    # Top 10 holders
                    for i, holder in enumerate(top_holders[:10]):
                        if isinstance(holder, dict) and 'pct' in holder:
                            top_10_holders_percentage += float(holder.get('pct', 0))
                    
                    # Insider holders
                    for holder in top_holders:
                        if isinstance(holder, dict) and holder.get('insider', False):
                            insider_holders_count += 1
                except:
                    pass
            
            # Safe extraction avec protection contre les None
            token_info = data.get('token') or {}
            launchpad_info = data.get('launchpad') or {}
            
            return {
                'holder_count': data.get('totalHolders', 0),
                'rug_risk_score': data.get('score_normalised', 50),
                'rug_raw_score': data.get('score', 0),
                'is_rugged': data.get('rugged', False),
                'top_holder_percentage': top_holder_percentage,
                'top_10_holders_percentage': top_10_holders_percentage,
                'insider_holders_count': insider_holders_count,
                'insider_networks_detected': data.get('graphInsidersDetected', 0),
                'liquidity_usd': float(data.get('totalMarketLiquidity', 0) or 0),
                'lp_providers_count': data.get('totalLPProviders', 0),
                'risk_count': len(data.get('risks', [])),
                'mint_authority_revoked': token_info.get('mintAuthority') is None if isinstance(token_info, dict) else False,
                'freeze_authority_revoked': token_info.get('freezeAuthority') is None if isinstance(token_info, dict) else False,
                'launchpad_name': launchpad_info.get('name') if isinstance(launchpad_info, dict) else None,
                'is_pump_fun': launchpad_info.get('platform') == 'pump_fun' if isinstance(launchpad_info, dict) else False,
                'source': 'rugcheck'
            }
        return None
    
    def compare_values(self, field_name: str, reference_value: Any, compare_value: Any) -> str:
        """Comparer deux valeurs et retourner le statut"""
        if reference_value is None and compare_value is None:
            return "✅ OK"
        if reference_value is None or compare_value is None:
            return "⚠️  N/A"
        
        # Valeurs numériques
        if isinstance(reference_value, (int, float)) and isinstance(compare_value, (int, float)):
            if reference_value == 0 and compare_value == 0:
                return "✅ OK"
            if reference_value == 0 or compare_value == 0:
                return "⚠️  ZERO"
            
            # Appliquer les tolérances
            if field_name in ['holder_count', 'insider_holders_count', 'risk_count']:
                # Valeurs entières
                diff = abs(reference_value - compare_value)
                tolerance = self.tolerances.get(field_name, 5)
                return "✅ OK" if diff <= tolerance else f"❌ DIFF({diff:.0f})"
            
            elif field_name in self.tolerances:
                # Valeurs avec pourcentage de tolérance
                tolerance = self.tolerances[field_name]
                diff_percent = abs((reference_value - compare_value) / reference_value) * 100
                return "✅ OK" if diff_percent <= tolerance else f"❌ DIFF({diff_percent:.1f}%)"
            
            else:
                # Comparaison directe pour autres valeurs numériques
                return "✅ OK" if reference_value == compare_value else f"❌ DIFF"
        
        # Valeurs booléennes
        elif isinstance(reference_value, bool) and isinstance(compare_value, bool):
            return "✅ OK" if reference_value == compare_value else "❌ DIFF"
        
        # Valeurs string
        elif isinstance(reference_value, str) and isinstance(compare_value, str):
            return "✅ OK" if reference_value.strip().lower() == compare_value.strip().lower() else "❌ DIFF"
        
        # Comparaison générale
        else:
            return "✅ OK" if str(reference_value) == str(compare_value) else "❌ DIFF"
    
    def format_value(self, value: Any, field_name: str) -> str:
        """Formater une valeur pour l'affichage"""
        if value is None:
            return "N/A"
        
        if isinstance(value, bool):
            return "✓" if value else "✗"
        
        if isinstance(value, (int, float)):
            if field_name in ['price_usd'] and value > 0:
                if value >= 1:
                    return f"${value:.6f}"
                else:
                    return f"${value:.8f}"
            elif field_name in ['market_cap', 'fdv', 'liquidity_usd', 'volume_24h']:
                if value >= 1000000:
                    return f"${value/1000000:.2f}M"
                elif value >= 1000:
                    return f"${value/1000:.1f}K"
                else:
                    return f"${value:.2f}"
            elif field_name in ['price_change_5m', 'price_change_1h', 'price_change_6h', 'price_change_24h']:
                return f"{value:+.2f}%"
            elif field_name in ['top_holder_percentage', 'top_10_holders_percentage']:
                return f"{value:.2f}%"
            elif field_name in ['bonding_curve_progress']:
                return f"{value:.3f}"
            elif field_name in ['rug_risk_score']:
                return f"{value:.1f}/100"
            elif isinstance(value, int):
                return f"{value:,}"
            else:
                return f"{value:.4f}"
        
        if isinstance(value, str):
            return value[:50] + "..." if len(value) > 50 else value
        
        return str(value)
    
    def compare_token_data(self, token_address: str) -> None:
        """Comparer toutes les données pour un token donné"""
        self.logger.info(f"🔍 Analyse comparative pour le token: {token_address}")
        print("=" * 80)
        print(f"🪙 TOKEN: {token_address}")
        print("=" * 80)
        
        # Récupérer toutes les données
        print("📥 Récupération des données...")
        tokens_data = self.get_tokens_data(token_address)
        history_data = self.get_history_data(token_address)
        
        if not tokens_data:
            print("❌ Token non trouvé dans la table tokens")
            return
        
        print(f"   ✅ Table tokens: {tokens_data['symbol']} - {tokens_data['name']}")
        print(f"   {'✅' if history_data else '❌'} Table history: {'Dernier snapshot trouvé' if history_data else 'Aucun historique'}")
        
        # APIs (avec délais pour éviter rate limiting)
        print("   🌐 Récupération DexScreener...", end="", flush=True)
        dex_data = None
        try:
            dex_data = self.get_dexscreener_data(token_address)
            print(f" {'✅' if dex_data else '❌'}")
        except Exception as e:
            print(f" ❌ (Erreur: {str(e)[:50]})")
            self.logger.debug(f"Erreur DexScreener: {e}")
        time.sleep(1)
        
        print("   🚀 Récupération Pump.fun...", end="", flush=True)
        pump_data = None
        try:
            pump_data = self.get_pumpfun_data(token_address)
            print(f" {'✅' if pump_data else '❌'}")
        except Exception as e:
            print(f" ❌ (Erreur: {str(e)[:50]})")
            self.logger.debug(f"Erreur Pump.fun: {e}")
        time.sleep(1)
        
        print("   🔒 Récupération Rugcheck...", end="", flush=True)
        rug_data = None
        try:
            rug_data = self.get_rugcheck_data(token_address)
            print(f" {'✅' if rug_data else '❌'}")
        except Exception as e:
            print(f" ❌ (Erreur: {str(e)[:50]})")
            self.logger.debug(f"Erreur Rugcheck: {e}")
        
        print("\n📊 COMPARAISON DÉTAILLÉE")
        print("=" * 80)
        
        # Définir les champs à comparer
        comparison_fields = [
            # Métadonnées de base
            ('symbol', 'Symbole'),
            ('name', 'Nom'),
            ('decimals', 'Décimales'),
            ('logo_uri', 'Logo URI'),
            ('creator_address', 'Créateur'),
            ('timestamp_token_created', 'Timestamp création'),
            ('is_verified', 'Vérifié'),
            
            # Prix et market cap
            ('price_usd', 'Prix USD'),
            ('market_cap', 'Market Cap'),
            ('fdv', 'FDV'),
            
            # Volume
            ('volume_5m', 'Volume 5m'),
            ('volume_1h', 'Volume 1h'),
            ('volume_6h', 'Volume 6h'),
            ('volume_24h', 'Volume 24h'),
            
            # Changements de prix
            ('price_change_5m', 'Variation 5m'),
            ('price_change_1h', 'Variation 1h'),
            ('price_change_6h', 'Variation 6h'),
            ('price_change_24h', 'Variation 24h'),
            
            # Liquidité
            ('liquidity_usd', 'Liquidité USD'),
            ('liquidity_sol', 'Liquidité SOL'),
            
            # Holders et sécurité
            ('holder_count', 'Nombre holders'),
            ('top_holder_percentage', 'Top holder %'),
            ('top_10_holders_percentage', 'Top 10 holders %'),
            ('insider_holders_count', 'Holders insider'),
            ('insider_networks_detected', 'Réseaux insider'),
            
            # Scores et risques
            ('rug_risk_score', 'Score risque'),
            ('rug_raw_score', 'Score brut'),
            ('is_rugged', 'Est ruggé'),
            ('risk_count', 'Nombre risques'),
            
            # Pump.fun spécifique
            ('bonding_curve_progress', 'Bonding curve'),
            ('is_pump_fun', 'Est Pump.fun'),
            
            # Autorités
            ('mint_authority_revoked', 'Mint authority révoqué'),
            ('freeze_authority_revoked', 'Freeze authority révoqué'),
        ]
        
        # Préparer les données pour le tableau
        table_data = []
        
        for field_name, display_name in comparison_fields:
            # Récupérer les valeurs
            tokens_value = tokens_data.get(field_name) if tokens_data else None
            history_value = history_data.get(field_name) if history_data else None
            dex_value = dex_data.get(field_name) if dex_data else None
            pump_value = pump_data.get(field_name) if pump_data else None
            rug_value = rug_data.get(field_name) if rug_data else None
            
            # Formater les valeurs
            tokens_formatted = self.format_value(tokens_value, field_name)
            history_formatted = self.format_value(history_value, field_name)
            dex_formatted = self.format_value(dex_value, field_name)
            pump_formatted = self.format_value(pump_value, field_name)
            rug_formatted = self.format_value(rug_value, field_name)
            
            # Calculer les statuts (en utilisant tokens comme référence)
            history_status = self.compare_values(field_name, tokens_value, history_value) if history_value is not None else "N/A"
            dex_status = self.compare_values(field_name, tokens_value, dex_value) if dex_value is not None else "N/A"
            pump_status = self.compare_values(field_name, tokens_value, pump_value) if pump_value is not None else "N/A"
            rug_status = self.compare_values(field_name, tokens_value, rug_value) if rug_value is not None else "N/A"
            
            # Ajouter à la table si au moins une valeur existe
            if any(v is not None for v in [tokens_value, history_value, dex_value, pump_value, rug_value]):
                table_data.append([
                    display_name,
                    tokens_formatted,
                    f"{history_formatted}\n{history_status}",
                    f"{dex_formatted}\n{dex_status}",
                    f"{pump_formatted}\n{pump_status}",
                    f"{rug_formatted}\n{rug_status}"
                ])
        
        # Afficher le tableau
        headers = ["Champ", "🗃️  Tokens (REF)", "📜 History", "📊 DexScreener", "🚀 Pump.fun", "🔒 Rugcheck"]
        print(tabulate(table_data, headers=headers, tablefmt="grid", maxcolwidths=[20, 20, 15, 15, 15, 15]))
        
        # Résumé des statuts
        print("\n📈 RÉSUMÉ DES STATUTS")
        print("=" * 50)
        
        all_statuses = []
        for row in table_data:
            for col in row[2:]:  # Skip field name and reference value
                status_line = col.split('\n')[-1] if '\n' in col else col
                if status_line.startswith(('✅', '❌', '⚠️')):
                    all_statuses.append(status_line)
        
        ok_count = sum(1 for s in all_statuses if s.startswith('✅'))
        diff_count = sum(1 for s in all_statuses if s.startswith('❌'))
        warning_count = sum(1 for s in all_statuses if s.startswith('⚠️'))
        
        total_comparisons = len(all_statuses)
        if total_comparisons > 0:
            ok_rate = (ok_count / total_comparisons) * 100
            print(f"✅ Valeurs cohérentes: {ok_count}/{total_comparisons} ({ok_rate:.1f}%)")
            print(f"❌ Différences détectées: {diff_count}")
            print(f"⚠️  Valeurs manquantes/nulles: {warning_count}")
            
            if ok_rate >= 80:
                print(f"\n🎉 EXCELLENT: Cohérence élevée ({ok_rate:.1f}%)")
            elif ok_rate >= 60:
                print(f"\n✅ BON: Cohérence acceptable ({ok_rate:.1f}%)")
            elif ok_rate >= 40:
                print(f"\n⚠️  MOYEN: Cohérence partielle ({ok_rate:.1f}%)")
            else:
                print(f"\n🚨 PROBLÈME: Faible cohérence ({ok_rate:.1f}%)")
        
        # Informations sur les sources de données
        print(f"\n🔍 SOURCES DE DONNÉES DISPONIBLES")
        print("=" * 40)
        sources = []
        if tokens_data: sources.append("✅ Base de données (tokens)")
        if history_data: sources.append("✅ Historique (tokens_history)")
        if dex_data: sources.append("✅ DexScreener API")
        if pump_data: sources.append("✅ Pump.fun API")
        if rug_data: sources.append("✅ Rugcheck API")
        
        for source in sources:
            print(f"   {source}")
        
        # Recommandations
        if diff_count > 0:
            print(f"\n💡 RECOMMANDATIONS")
            print("=" * 30)
            print("   • Vérifier les processus de synchronisation")
            print("   • Contrôler les intervalles de mise à jour")
            print("   • Examiner les sources de données incohérentes")
            if not history_data:
                print("   • Lancer l'historisation pour ce token")

def main():
    """Point d'entrée principal"""
    print("🔍 Script de comparaison détaillée de token")
    print("=" * 50)
    
    # Vérifier les arguments
    token_address = None
    if len(sys.argv) > 1:
        token_address = sys.argv[1].strip()
        print(f"Token spécifié: {token_address}")
    else:
        print("Sélection d'un token aléatoire...")
    
    # Initialiser le comparateur
    comparator = TokenDetailedComparison(CONFIG['db_path'])
    
    # Obtenir l'adresse du token
    if not token_address:
        token_address = comparator.get_random_token()
        if not token_address:
            print("❌ Impossible de trouver un token aléatoire")
            return
        print(f"Token sélectionné: {token_address}")
    
    print("=" * 50)
    
    # Faire la comparaison
    try:
        comparator.compare_token_data(token_address)
    except KeyboardInterrupt:
        print("\n⏹️  Comparaison interrompue par l'utilisateur")
    except Exception as e:
        print(f"\n❌ Erreur lors de la comparaison: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()