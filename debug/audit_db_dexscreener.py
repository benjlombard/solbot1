#!/usr/bin/env python3
"""
🔍 Programme de Contrôle DB vs DexScreener
Compare les données de la table tokens avec DexScreener pour détecter les écarts
"""

import sqlite3
import requests
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import logging

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DBDexScreenerAuditor:
    """Classe pour auditer les données entre la DB et DexScreener"""
    
    def __init__(self, database_path: str = "../tokens.db"):
        self.database_path = database_path
        self.tolerance_percent = 5.0  # Tolérance de 5% pour les différences numériques
        
        # Mapping des champs DexScreener DB vers API DexScreener
        self.field_mapping = {
            # Champs de base (pour référence)
            'price_usdc': 'priceUsd',
            'market_cap': 'marketCap', 
            'liquidity_usd': 'liquidity.usd',
            'volume_24h': 'volume.h24',
            'price_change_24h': 'priceChange.h24',
            
            # Champs DexScreener spécifiques
            'dexscreener_liquidity_base': 'liquidity.base',
            'dexscreener_liquidity_quote': 'liquidity.quote',
            'dexscreener_volume_1h': 'volume.h1',
            'dexscreener_volume_6h': 'volume.h6',
            'dexscreener_price_change_1h': 'priceChange.h1',
            'dexscreener_price_change_6h': 'priceChange.h6',
            'dexscreener_txns_1h': 'txns.h1.total',
            'dexscreener_txns_6h': 'txns.h6.total', 
            'dexscreener_txns_24h': 'txns.h24.total',
            'dexscreener_buys_1h': 'txns.h1.buys',
            'dexscreener_sells_1h': 'txns.h1.sells',
            'dexscreener_buys_24h': 'txns.h24.buys',
            'dexscreener_sells_24h': 'txns.h24.sells'
        }
        
    def get_recent_tokens(self, limit: int = 10) -> List[Dict]:
        """Récupérer les tokens les plus récemment mis à jour avec toutes les colonnes DexScreener"""
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT address, symbol, updated_at, first_discovered_at,
                       dexscreener_pair_created_at, dexscreener_price_usd, 
                       dexscreener_market_cap, dexscreener_liquidity_base, 
                       dexscreener_liquidity_quote, dexscreener_volume_1h, 
                       dexscreener_volume_6h, dexscreener_volume_24h,
                       dexscreener_price_change_1h, dexscreener_price_change_6h,
                       dexscreener_price_change_h24, dexscreener_txns_1h, 
                       dexscreener_txns_6h, dexscreener_txns_24h,
                       dexscreener_buys_1h, dexscreener_sells_1h, 
                       dexscreener_buys_24h, dexscreener_sells_24h,
                       dexscreener_dexscreener_url, dexscreener_last_dexscreener_update
                FROM tokens 
                WHERE updated_at IS NOT NULL 
                AND symbol IS NOT NULL 
                AND symbol != 'UNKNOWN' 
                AND symbol != ''
                ORDER BY updated_at DESC 
                LIMIT ?
            ''', (limit,))
            
            tokens = []
            for row in cursor.fetchall():
                tokens.append(dict(row))
            
            return tokens
            
        except sqlite3.Error as e:
            logger.error(f"Erreur base de données: {e}")
            return []
        finally:
            conn.close()
    
    def fetch_dexscreener_data(self, address: str) -> Optional[Dict]:
        """Récupérer les données DexScreener pour un token"""
        url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
        
        try:
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('pairs') and len(data['pairs']) > 0:
                    return data['pairs'][0]  # Prendre la première paire
                else:
                    logger.warning(f"Aucune paire trouvée pour {address}")
                    return None
            else:
                logger.warning(f"API DexScreener error {response.status_code} pour {address}")
                return None
                
        except Exception as e:
            logger.error(f"Erreur récupération DexScreener pour {address}: {e}")
            return None
    
    def get_nested_value(self, data: Dict, path: str) -> Optional[float]:
        """Récupérer une valeur imbriquée (ex: liquidity.usd, txns.h1.buys)"""
        try:
            keys = path.split('.')
            value = data
            for key in keys:
                if isinstance(value, dict) and key in value:
                    value = value[key]
                else:
                    return None
            
            # Gestion spéciale pour les totaux de transactions
            if path.endswith('.total'):
                # Calculer le total buys + sells si disponible
                parent_path = '.'.join(keys[:-1])
                parent_value = data
                for key in keys[:-1]:
                    if isinstance(parent_value, dict) and key in parent_value:
                        parent_value = parent_value[key]
                    else:
                        return None
                
                if isinstance(parent_value, dict):
                    buys = parent_value.get('buys', 0) or 0
                    sells = parent_value.get('sells', 0) or 0
                    return float(buys + sells) if (buys or sells) else None
            
            return float(value) if value is not None else None
        except (ValueError, TypeError):
            return None
    
    def calculate_percentage_diff(self, db_value: Optional[float], dex_value: Optional[float]) -> Optional[float]:
        """Calculer la différence en pourcentage entre deux valeurs"""
        if db_value is None or dex_value is None:
            return None
        
        if dex_value == 0:
            if db_value == 0:
                return 0.0
            else:
                return 100.0  # Différence maximale si DB a une valeur mais pas DexScreener
        
        return abs((db_value - dex_value) / dex_value) * 100
    
    def is_significant_difference(self, db_value: Optional[float], dex_value: Optional[float]) -> bool:
        """Vérifier si la différence est significative"""
        diff = self.calculate_percentage_diff(db_value, dex_value)
        return diff is not None and diff > self.tolerance_percent
    
    def format_value_comparison(self, db_value: Optional[float], dex_value: Optional[float], field_name: str) -> str:
        """Formater la comparaison de valeurs pour l'affichage"""
        if db_value is None and dex_value is None:
            return f"{field_name}: Aucune donnée des deux côtés"
        elif db_value is None:
            return f"{field_name}: DB=NULL, DexScreener={dex_value:,.2f}"
        elif dex_value is None:
            return f"{field_name}: DB={db_value:,.2f}, DexScreener=NULL"
        else:
            diff = self.calculate_percentage_diff(db_value, dex_value)
            return f"{field_name}: DB={db_value:,.2f}, DexScreener={dex_value:,.2f} (écart: {diff:.1f}%)"
    
    def audit_token(self, token_data: Dict) -> Dict:
        """Auditer un token spécifique"""
        address = token_data['address']
        symbol = token_data['symbol']
        
        logger.info(f"🔍 Audit de {symbol} ({address[:8]}...)")
        
        # Récupérer les données DexScreener
        dex_data = self.fetch_dexscreener_data(address)
        
        if not dex_data:
            return {
                'address': address,
                'symbol': symbol,
                'status': 'ERROR',
                'message': 'Impossible de récupérer les données DexScreener',
                'discrepancies': [],
                'has_issues': True
            }
        
        # Comparer chaque champ
        discrepancies = []
        has_issues = False
        
        for db_field, dex_path in self.field_mapping.items():
            db_value = token_data.get(db_field)
            dex_value = self.get_nested_value(dex_data, dex_path)
            
            if self.is_significant_difference(db_value, dex_value):
                has_issues = True
                comparison = self.format_value_comparison(db_value, dex_value, db_field)
                discrepancies.append(comparison)
        
        # Vérifications spéciales pour les colonnes DexScreener uniquement
        
        # 1. Vérification de la date de création de la paire
        if 'pairCreatedAt' in dex_data and token_data.get('dexscreener_pair_created_at'):
            try:
                dex_timestamp = dex_data['pairCreatedAt']
                # Convertir en format datetime pour comparaison
                from datetime import datetime
                dex_datetime = datetime.fromtimestamp(dex_timestamp / 1000)
                db_datetime_str = token_data['dexscreener_pair_created_at']
                
                if db_datetime_str:
                    try:
                        # Gérer différents formats de datetime
                        if 'T' in db_datetime_str:
                            db_datetime = datetime.fromisoformat(db_datetime_str.replace('Z', '+00:00'))
                        else:
                            db_datetime = datetime.strptime(db_datetime_str, '%Y-%m-%d %H:%M:%S')
                        
                        # Tolérance de 1 minute
                        time_diff = abs((dex_datetime - db_datetime).total_seconds())
                        if time_diff > 60:
                            has_issues = True
                            discrepancies.append(f"dexscreener_pair_created_at: DB={db_datetime_str}, DexScreener={dex_datetime.isoformat()}")
                    except ValueError as ve:
                        has_issues = True
                        discrepancies.append(f"dexscreener_pair_created_at: Format invalide DB={db_datetime_str}")
            except Exception as e:
                logger.debug(f"Erreur comparaison date pour {address}: {e}")
        
        # 2. Vérification de l'URL DexScreener
        if 'url' in dex_data:
            dex_url = dex_data['url']
            db_url = token_data.get('dexscreener_dexscreener_url')
            if db_url and db_url != dex_url:
                has_issues = True
                discrepancies.append(f"dexscreener_url: DB={db_url}, DexScreener={dex_url}")
        
        # 3. Vérification cohérence transactions (buys + sells = total)
        for period in ['1h', '6h', '24h']:
            # Adapter les noms de champs selon votre structure
            if period == '24h':
                db_total_field = 'dexscreener_txns_24h'
                db_buys_field = 'dexscreener_buys_24h'
                db_sells_field = 'dexscreener_sells_24h'
            else:
                db_total_field = f'dexscreener_txns_{period}'
                db_buys_field = f'dexscreener_buys_{period}'
                db_sells_field = f'dexscreener_sells_{period}'
            
            db_total = token_data.get(db_total_field, 0) or 0
            db_buys = token_data.get(db_buys_field, 0) or 0 
            db_sells = token_data.get(db_sells_field, 0) or 0
            
            if db_total > 0 and (db_buys + db_sells) > 0:
                if abs(db_total - (db_buys + db_sells)) > 1:  # Tolérance de 1 transaction
                    has_issues = True
                    discrepancies.append(f"Incohérence transactions {period}: total={db_total}, buys+sells={db_buys + db_sells}")
        
        # 4. Vérification de la dernière mise à jour DexScreener
        db_last_update = token_data.get('dexscreener_last_dexscreener_update')
        if db_last_update:
            try:
                from datetime import datetime, timedelta
                if 'T' in db_last_update:
                    last_update_dt = datetime.fromisoformat(db_last_update.replace('Z', '+00:00'))
                else:
                    last_update_dt = datetime.strptime(db_last_update, '%Y-%m-%d %H:%M:%S')
                
                # Vérifier si la mise à jour est très ancienne (plus de 24h)
                now = datetime.now()
                if (now - last_update_dt).total_seconds() > 86400:  # 24h
                    has_issues = True
                    discrepancies.append(f"dexscreener_last_update: Données anciennes ({db_last_update})")
            except ValueError:
                has_issues = True
                discrepancies.append(f"dexscreener_last_update: Format invalide ({db_last_update})")
        
        return {
            'address': address,
            'symbol': symbol,
            'status': 'OK' if not has_issues else 'ISSUES',
            'message': 'Données cohérentes' if not has_issues else f'{len(discrepancies)} écart(s) détecté(s)',
            'discrepancies': discrepancies,
            'has_issues': has_issues,
            'dex_data_available': True
        }
    
    def run_audit(self, limit: int = 10, delay_between_calls: float = 1.0) -> Dict:
        """Lancer l'audit complet focalisé sur les colonnes DexScreener uniquement"""
        logger.info(f"🚀 Démarrage de l'audit COLONNES DEXSCREENER pour {limit} tokens")
        logger.info(f"📊 Tolérance configurée: {self.tolerance_percent}%")
        
        # Afficher les champs DexScreener qui vont être vérifiés
        dexscreener_fields = [k for k in self.field_mapping.keys() if k.startswith('dexscreener_')]
        logger.info(f"🔍 Colonnes DexScreener à auditer: {len(dexscreener_fields)}")
        logger.info(f"   Champs: {', '.join(dexscreener_fields)}")
        logger.info("=" * 80)
        
        # Récupérer les tokens récents
        tokens = self.get_recent_tokens(limit)
        
        if not tokens:
            logger.error("❌ Aucun token trouvé dans la base de données")
            return {'success': False, 'message': 'Aucun token trouvé'}
        
        logger.info(f"📋 {len(tokens)} tokens récupérés pour audit")
        
        # Vérifier quels tokens ont des données DexScreener
        tokens_with_dexscreener_data = []
        for token in tokens:
            has_dexscreener_data = any(
                token.get(field) is not None and token.get(field) != 0 
                for field in dexscreener_fields
            )
            if has_dexscreener_data:
                tokens_with_dexscreener_data.append(token)
        
        logger.info(f"📈 Tokens avec données DexScreener en DB: {len(tokens_with_dexscreener_data)}/{len(tokens)}")
        
        # Auditer chaque token
        results = []
        ok_count = 0
        issues_count = 0
        error_count = 0
        no_data_count = 0
        
        for i, token in enumerate(tokens, 1):
            logger.info(f"\n[{i}/{len(tokens)}] " + "="*50)
            
            # Vérifier si le token a des données DexScreener en DB
            has_dexscreener_data = any(
                token.get(field) is not None and token.get(field) != 0 
                for field in dexscreener_fields
            )
            
            if not has_dexscreener_data:
                no_data_count += 1
                logger.info(f"⚪ {token['symbol']}: Aucune donnée DexScreener en DB")
                results.append({
                    'address': token['address'],
                    'symbol': token['symbol'],
                    'status': 'NO_DATA',
                    'message': 'Aucune donnée DexScreener en DB',
                    'discrepancies': [],
                    'has_issues': False
                })
                continue
            
            result = self.audit_token(token)
            results.append(result)
            
            if result['status'] == 'OK':
                ok_count += 1
                logger.info(f"✅ {result['symbol']}: {result['message']}")
            elif result['status'] == 'ISSUES':
                issues_count += 1
                logger.warning(f"⚠️  {result['symbol']}: {result['message']}")
                for discrepancy in result['discrepancies']:
                    logger.warning(f"   📊 {discrepancy}")
            else:  # ERROR
                error_count += 1
                logger.error(f"❌ {result['symbol']}: {result['message']}")
            
            # Délai entre les appels API
            if i < len(tokens):
                time.sleep(delay_between_calls)
        
        # Rapport final
        logger.info("\n" + "="*80)
        logger.info("📋 RAPPORT FINAL DE L'AUDIT DEXSCREENER")
        logger.info("="*80)
        logger.info(f"✅ Tokens OK (cohérents):     {ok_count:>3}")
        logger.info(f"⚠️  Tokens avec écarts:       {issues_count:>3}")
        logger.info(f"❌ Tokens en erreur:          {error_count:>3}")
        logger.info(f"⚪ Tokens sans données DS:    {no_data_count:>3}")
        logger.info(f"📊 Total audité:              {len(tokens):>3}")
        
        auditable_tokens = len(tokens) - no_data_count
        success_rate = (ok_count / auditable_tokens * 100) if auditable_tokens > 0 else 0
        logger.info(f"📈 Taux cohérence (sur tokens avec données): {success_rate:.1f}%")
        
        # Analyse des champs les plus problématiques
        field_issues = {}
        for result in results:
            if result['status'] == 'ISSUES':
                for discrepancy in result['discrepancies']:
                    field_name = discrepancy.split(':')[0]
                    field_issues[field_name] = field_issues.get(field_name, 0) + 1
        
        if field_issues:
            logger.info(f"\n🔍 CHAMPS DEXSCREENER LES PLUS PROBLÉMATIQUES:")
            logger.info("-" * 60)
            for field, count in sorted(field_issues.items(), key=lambda x: x[1], reverse=True):
                logger.info(f"   {field:<35}: {count} token(s)")
        
        # Détail des tokens avec problèmes
        if issues_count > 0:
            logger.info("\n🔍 DÉTAIL DES TOKENS AVEC ÉCARTS DEXSCREENER:")
            logger.info("-" * 80)
            for result in results:
                if result['status'] == 'ISSUES':
                    logger.info(f"\n🏷️  {result['symbol']} ({result['address'][:8]}...)")
                    for discrepancy in result['discrepancies']:
                        logger.info(f"   • {discrepancy}")
        
        return {
            'success': True,
            'total_audited': len(tokens),
            'ok_count': ok_count,
            'issues_count': issues_count,
            'error_count': error_count,
            'no_data_count': no_data_count,
            'auditable_count': auditable_tokens,
            'success_rate': success_rate,
            'field_issues': field_issues,
            'results': results
        }
    
    def export_audit_results(self, results: Dict, filename: str = None) -> str:
        """Exporter les résultats d'audit en JSON"""
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"audit_db_dexscreener_{timestamp}.json"
        
        audit_export = {
            'audit_timestamp': datetime.now().isoformat(),
            'database_path': self.database_path,
            'tolerance_percent': self.tolerance_percent,
            'summary': {
                'total_audited': results.get('total_audited', 0),
                'ok_count': results.get('ok_count', 0),
                'issues_count': results.get('issues_count', 0),
                'error_count': results.get('error_count', 0),
                'success_rate': results.get('success_rate', 0)
            },
            'detailed_results': results.get('results', [])
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(audit_export, f, indent=2, ensure_ascii=False)
        
        logger.info(f"📄 Résultats exportés vers: {filename}")
        return filename

def main():
    """Fonction principale"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Audit DB vs DexScreener")
    parser.add_argument("--database", default="../tokens.db", help="Chemin vers la base de données")
    parser.add_argument("--limit", type=int, default=10, help="Nombre de tokens à auditer")
    parser.add_argument("--tolerance", type=float, default=5.0, help="Tolérance en % pour les écarts")
    parser.add_argument("--delay", type=float, default=1.0, help="Délai entre appels API (secondes)")
    parser.add_argument("--export", action="store_true", help="Exporter les résultats en JSON")
    parser.add_argument("--verbose", action="store_true", help="Mode verbose")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Créer l'auditeur
    auditor = DBDexScreenerAuditor(args.database)
    auditor.tolerance_percent = args.tolerance
    
    try:
        # Lancer l'audit
        results = auditor.run_audit(
            limit=args.limit,
            delay_between_calls=args.delay
        )
        
        if not results['success']:
            logger.error("❌ Audit échoué")
            return 1
        
        # Exporter si demandé
        if args.export:
            auditor.export_audit_results(results)
        
        # Code de retour basé sur les résultats
        if results['issues_count'] > 0:
            logger.warning(f"⚠️  Audit terminé avec {results['issues_count']} écart(s) détecté(s)")
            return 2  # Code pour indiquer des écarts trouvés
        else:
            logger.info("✅ Audit terminé - Toutes les données sont cohérentes")
            return 0
            
    except KeyboardInterrupt:
        logger.info("\n🛑 Audit interrompu par l'utilisateur")
        return 1
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'audit: {e}")
        return 1

if __name__ == "__main__":
    exit(main())