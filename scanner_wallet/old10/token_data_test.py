#!/usr/bin/env python3
"""
Script de test pour vérifier la cohérence des données tokens
- Teste la cohérence entre tokens et tokens_history
- Vérifie que les données correspondent aux APIs
- Rapport détaillé des incohérences
"""

import sqlite3
import requests
import time
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import logging
from dataclasses import dataclass

# Configuration
CONFIG = {
    'db_path': 'solana_wallet_monitor.db',
    'api_timeout': 10,
    'test_sample_size': 10,  # Nombre de tokens à tester contre les APIs
    'tolerance_percent': 5.0,  # Tolérance pour les différences de prix (%)
    'max_age_hours': 24,  # Age max acceptable pour les données (heures)
}

@dataclass
class TestResult:
    test_name: str
    passed: bool
    details: str
    token_address: Optional[str] = None

class TokenDataTester:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('token_test.log', encoding='utf-8')
            ]
        )
        self.logger = logging.getLogger('TokenTester')
        
        self.results: List[TestResult] = []
    
    def get_db_connection(self) -> sqlite3.Connection:
        """Get database connection"""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn
    
    def add_result(self, test_name: str, passed: bool, details: str, token_address: str = None):
        """Add test result"""
        self.results.append(TestResult(test_name, passed, details, token_address))
        status = "✅ PASS" if passed else "❌ FAIL"
        token_info = f" [{token_address[:8]}...]" if token_address else ""
        self.logger.info(f"{status} {test_name}{token_info}: {details}")
    
    def test_tokens_history_consistency(self) -> None:
        """Test 1: Vérifier la cohérence entre tokens et le dernier snapshot de tokens_history"""
        self.logger.info("=== Test 1: Cohérence tokens <-> tokens_history ===")
        
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Récupérer les tokens avec leur dernier snapshot
                query = """
                WITH latest_snapshots AS (
                    SELECT 
                        token_address,
                        price_usd, market_cap, holder_count, volume_24h,
                        top_holder_percentage, rug_risk_score,
                        ROW_NUMBER() OVER (PARTITION BY token_address ORDER BY snapshot_timestamp DESC) as rn
                    FROM tokens_history
                    WHERE snapshot_timestamp > strftime('%s', 'now', '-7 days')
                )
                SELECT 
                    t.address, t.symbol, t.price_usd as current_price, t.market_cap as current_mc,
                    t.holder_count as current_holders, t.volume_24h as current_volume,
                    t.top_holder_percentage as current_top_holder, t.rug_risk_score as current_rug_score,
                    ls.price_usd as snapshot_price, ls.market_cap as snapshot_mc,
                    ls.holder_count as snapshot_holders, ls.volume_24h as snapshot_volume,
                    ls.top_holder_percentage as snapshot_top_holder, ls.rug_risk_score as snapshot_rug_score,
                    t.last_historized_at
                FROM tokens t
                LEFT JOIN latest_snapshots ls ON t.address = ls.token_address AND ls.rn = 1
                WHERE t.is_dead = 0 
                AND t.last_historized_at IS NOT NULL
                AND (t.price_usd > 0 OR t.market_cap > 0)
                LIMIT 50
                """
                
                cursor.execute(query)
                tokens = cursor.fetchall()
                
                if not tokens:
                    self.add_result("tokens_history_consistency", False, "Aucun token avec historique trouvé")
                    return
                
                inconsistent_count = 0
                total_tested = 0
                
                for token in tokens:
                    total_tested += 1
                    token_address = token['address']
                    inconsistencies = []
                    
                    # Vérifier chaque champ critique
                    fields_to_check = [
                        ('price_usd', 'current_price', 'snapshot_price'),
                        ('market_cap', 'current_mc', 'snapshot_mc'),
                        ('holder_count', 'current_holders', 'snapshot_holders'),
                        ('volume_24h', 'current_volume', 'snapshot_volume'),
                        ('top_holder_percentage', 'current_top_holder', 'snapshot_top_holder'),
                        ('rug_risk_score', 'current_rug_score', 'snapshot_rug_score')
                    ]
                    
                    for field_name, current_key, snapshot_key in fields_to_check:
                        current_val = token[current_key] or 0
                        snapshot_val = token[snapshot_key] or 0
                        
                        # Skip si pas de snapshot
                        if token[snapshot_key] is None:
                            continue
                        
                        # Calculer la différence
                        if field_name in ['price_usd', 'market_cap', 'volume_24h'] and current_val > 0:
                            diff_percent = abs((current_val - snapshot_val) / current_val) * 100
                            if diff_percent > CONFIG['tolerance_percent']:
                                inconsistencies.append(f"{field_name}: {current_val} vs {snapshot_val} ({diff_percent:.1f}% diff)")
                        elif field_name in ['holder_count', 'rug_risk_score'] and current_val != snapshot_val:
                            inconsistencies.append(f"{field_name}: {current_val} vs {snapshot_val}")
                    
                    if inconsistencies:
                        inconsistent_count += 1
                        details = f"Incohérences: {'; '.join(inconsistencies[:3])}"
                        self.add_result("token_history_consistency", False, details, token_address)
                    else:
                        self.add_result("token_history_consistency", True, "Données cohérentes", token_address)
                
                # Résumé global
                consistency_rate = ((total_tested - inconsistent_count) / total_tested) * 100 if total_tested > 0 else 0
                summary = f"Cohérence globale: {consistency_rate:.1f}% ({total_tested - inconsistent_count}/{total_tested})"
                self.add_result("tokens_history_summary", consistency_rate >= 90, summary)
                
        except Exception as e:
            self.add_result("tokens_history_consistency", False, f"Erreur: {e}")
    
    def get_dexscreener_data(self, token_address: str) -> Optional[Dict]:
        """Récupérer les données de DexScreener pour comparaison"""
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            response = self.session.get(url, timeout=CONFIG['api_timeout'])
            
            if response.status_code == 200:
                data = response.json()
                if 'pairs' in data and data['pairs']:
                    # Prendre la pair avec le plus de liquidité
                    best_pair = max(data['pairs'], key=lambda x: float(x.get('liquidity', {}).get('usd', 0) or 0))
                    return {
                        'price_usd': float(best_pair.get('priceUsd', 0) or 0),
                        'market_cap': float(best_pair.get('fdv', 0) or 0),
                        'volume_24h': float(best_pair.get('volume', {}).get('h24', 0) or 0),
                        'liquidity_usd': float(best_pair.get('liquidity', {}).get('usd', 0) or 0),
                        'price_change_24h': float(best_pair.get('priceChange', {}).get('h24', 0) or 0),
                        'source': 'dexscreener'
                    }
        except Exception as e:
            self.logger.debug(f"Erreur DexScreener pour {token_address[:8]}...: {e}")
        return None
    
    def get_rugcheck_data(self, token_address: str) -> Optional[Dict]:
        """Récupérer les données de Rugcheck pour comparaison"""
        try:
            url = f"https://api.rugcheck.xyz/v1/tokens/{token_address}/report"
            response = self.session.get(url, timeout=CONFIG['api_timeout'])
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'holder_count': data.get('totalHolders', 0),
                    'rug_risk_score': data.get('score_normalised', 50),
                    'top_holder_percentage': data.get('topHolders', [{}])[0].get('pct', 0) if data.get('topHolders') else 0,
                    'liquidity_usd': float(data.get('totalMarketLiquidity', 0) or 0),
                    'source': 'rugcheck'
                }
        except Exception as e:
            self.logger.debug(f"Erreur Rugcheck pour {token_address[:8]}...: {e}")
        return None
    
    def get_pumpfun_data(self, token_address: str) -> Optional[Dict]:
        """Récupérer les données de Pump.fun pour comparaison"""
        try:
            urls = [
                f"https://frontend-api.pump.fun/coins/{token_address}",
                f"https://frontend-api-v2.pump.fun/coins/{token_address}",
            ]
            
            for url in urls:
                try:
                    response = self.session.get(url, timeout=CONFIG['api_timeout'])
                    if response.status_code == 200:
                        data = response.json()
                        if data and isinstance(data, dict):
                            return {
                                'market_cap': float(data.get('usd_market_cap', 0) or 0),
                                'holder_count': int(data.get('holder_count', 0) or 0),
                                'volume_24h': float(data.get('volume_24h', 0) or 0),
                                'bonding_curve_progress': float(data.get('bonding_curve_progress', 0) or 0),
                                'source': 'pumpfun'
                            }
                except:
                    continue
        except Exception as e:
            self.logger.debug(f"Erreur Pump.fun pour {token_address[:8]}...: {e}")
        return None
    
    def test_api_data_accuracy(self) -> None:
        """Test 2: Vérifier que les données DB correspondent aux APIs"""
        self.logger.info("=== Test 2: Précision des données vs APIs ===")
        
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Sélectionner un échantillon de tokens récents
                query = """
                SELECT address, symbol, price_usd, market_cap, volume_24h, holder_count,
                       top_holder_percentage, rug_risk_score, bonding_curve_progress,
                       liquidity_usd, last_price_update, metadata_source
                FROM tokens 
                WHERE is_dead = 0 
                AND last_price_update > strftime('%s', 'now', '-6 hours')
                AND (price_usd > 0 OR market_cap > 0)
                ORDER BY last_price_update DESC 
                LIMIT ?
                """
                
                cursor.execute(query, (CONFIG['test_sample_size'],))
                tokens = cursor.fetchall()
                
                if not tokens:
                    self.add_result("api_accuracy", False, "Aucun token récent trouvé pour test API")
                    return
                
                accurate_count = 0
                total_tested = 0
                
                for token in tokens:
                    total_tested += 1
                    token_address = token['address']
                    db_data = dict(token)
                    
                    # Tester selon la source de métadonnées
                    api_data = None
                    source_tested = None
                    
                    # Test DexScreener (prioritaire)
                    if 'dexscreener' in (token['metadata_source'] or ''):
                        api_data = self.get_dexscreener_data(token_address)
                        source_tested = 'dexscreener'
                        time.sleep(0.5)  # Rate limiting
                    
                    # Test Pump.fun si pas de données DexScreener
                    if not api_data and ('pumpfun' in (token['metadata_source'] or '') or token['bonding_curve_progress'] > 0):
                        api_data = self.get_pumpfun_data(token_address)
                        source_tested = 'pumpfun'
                        time.sleep(1.0)  # Rate limiting plus strict
                    
                    # Test Rugcheck pour holder data
                    rugcheck_data = self.get_rugcheck_data(token_address)
                    time.sleep(1.0)  # Rate limiting
                    
                    # Comparer les données
                    inaccuracies = []
                    
                    if api_data:
                        # Comparer prix et market cap
                        if source_tested == 'dexscreener':
                            for field in ['price_usd', 'market_cap', 'volume_24h']:
                                db_val = db_data.get(field, 0) or 0
                                api_val = api_data.get(field, 0) or 0
                                
                                if db_val > 0 and api_val > 0:
                                    diff_percent = abs((db_val - api_val) / api_val) * 100
                                    if diff_percent > CONFIG['tolerance_percent'] * 2:  # Tolérance plus large pour APIs
                                        inaccuracies.append(f"{field}: DB={db_val:.6f} vs API={api_val:.6f} ({diff_percent:.1f}%)")
                        
                        elif source_tested == 'pumpfun':
                            # Test spécifique Pump.fun
                            for field in ['market_cap', 'holder_count']:
                                db_val = db_data.get(field, 0) or 0
                                api_val = api_data.get(field, 0) or 0
                                
                                if api_val > 0 and abs(db_val - api_val) > max(api_val * 0.1, 10):
                                    inaccuracies.append(f"{field}: DB={db_val} vs API={api_val}")
                    
                    # Comparer données Rugcheck
                    if rugcheck_data:
                        for field in ['holder_count', 'top_holder_percentage']:
                            db_val = db_data.get(field, 0) or 0
                            api_val = rugcheck_data.get(field, 0) or 0
                            
                            if field == 'holder_count' and api_val > 0:
                                if abs(db_val - api_val) > max(api_val * 0.2, 5):  # 20% tolérance pour holders
                                    inaccuracies.append(f"rugcheck_{field}: DB={db_val} vs API={api_val}")
                            elif field == 'top_holder_percentage' and api_val > 0:
                                if abs(db_val - api_val) > 5:  # 5% tolérance pour percentage
                                    inaccuracies.append(f"rugcheck_{field}: DB={db_val:.1f}% vs API={api_val:.1f}%")
                    
                    # Résultat du test pour ce token
                    if inaccuracies:
                        details = f"Incohérences {source_tested}: {'; '.join(inaccuracies[:2])}"
                        self.add_result("api_accuracy_token", False, details, token_address)
                    else:
                        accurate_count += 1
                        details = f"Données précises ({source_tested})"
                        self.add_result("api_accuracy_token", True, details, token_address)
                
                # Résumé global
                accuracy_rate = (accurate_count / total_tested) * 100 if total_tested > 0 else 0
                summary = f"Précision globale: {accuracy_rate:.1f}% ({accurate_count}/{total_tested})"
                self.add_result("api_accuracy_summary", accuracy_rate >= 70, summary)
                
        except Exception as e:
            self.add_result("api_accuracy", False, f"Erreur: {e}")
    
    def test_data_freshness(self) -> None:
        """Test 3: Vérifier la fraîcheur des données"""
        self.logger.info("=== Test 3: Fraîcheur des données ===")
        
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Tokens avec données anciennes
                cutoff_timestamp = int(time.time()) - (CONFIG['max_age_hours'] * 3600)
                
                query = """
                SELECT 
                    COUNT(*) as total_tokens,
                    COUNT(CASE WHEN last_price_update > ? THEN 1 END) as fresh_tokens,
                    COUNT(CASE WHEN last_price_update IS NULL THEN 1 END) as never_updated,
                    COUNT(CASE WHEN is_dead = 1 THEN 1 END) as dead_tokens
                FROM tokens 
                WHERE (price_usd > 0 OR market_cap > 0)
                """
                
                cursor.execute(query, (cutoff_timestamp,))
                stats = cursor.fetchone()
                
                total = stats['total_tokens']
                fresh = stats['fresh_tokens']
                never_updated = stats['never_updated']
                dead = stats['dead_tokens']
                
                if total > 0:
                    freshness_rate = (fresh / total) * 100
                    summary = f"Fraîcheur: {freshness_rate:.1f}% ({fresh}/{total}), Jamais mis à jour: {never_updated}, Morts: {dead}"
                    self.add_result("data_freshness", freshness_rate >= 60, summary)
                else:
                    self.add_result("data_freshness", False, "Aucun token avec données trouvé")
                
        except Exception as e:
            self.add_result("data_freshness", False, f"Erreur: {e}")
    
    def test_database_integrity(self) -> None:
        """Test 4: Vérifier l'intégrité de la base de données"""
        self.logger.info("=== Test 4: Intégrité de la base de données ===")
        
        try:
            with self.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Test 1: Tokens sans adresse
                cursor.execute("SELECT COUNT(*) FROM tokens WHERE address IS NULL OR address = ''")
                tokens_no_address = cursor.fetchone()[0]
                self.add_result("db_integrity_address", tokens_no_address == 0, f"Tokens sans adresse: {tokens_no_address}")
                
                # Test 2: Snapshots orphelins
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens_history th 
                    LEFT JOIN tokens t ON th.token_address = t.address 
                    WHERE t.address IS NULL
                """)
                orphan_snapshots = cursor.fetchone()[0]
                self.add_result("db_integrity_orphans", orphan_snapshots < 10, f"Snapshots orphelins: {orphan_snapshots}")
                
                # Test 3: Données cohérentes
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens 
                    WHERE price_usd < 0 OR market_cap < 0 OR volume_24h < 0 OR holder_count < 0
                """)
                negative_values = cursor.fetchone()[0]
                self.add_result("db_integrity_negative", negative_values == 0, f"Valeurs négatives: {negative_values}")
                
                # Test 4: Tokens avec market cap mais sans prix
                cursor.execute("""
                    SELECT COUNT(*) FROM tokens 
                    WHERE market_cap > 0 AND (price_usd IS NULL OR price_usd = 0)
                """)
                mc_no_price = cursor.fetchone()[0]
                self.add_result("db_integrity_price", mc_no_price < 5, f"Market cap sans prix: {mc_no_price}")
                
        except Exception as e:
            self.add_result("db_integrity", False, f"Erreur: {e}")
    
    def run_all_tests(self) -> None:
        """Exécuter tous les tests"""
        self.logger.info("🧪 Démarrage des tests de cohérence des données tokens")
        self.logger.info("=" * 60)
        
        start_time = time.time()
        
        # Exécuter tous les tests
        self.test_database_integrity()
        self.test_data_freshness()
        self.test_tokens_history_consistency()
        self.test_api_data_accuracy()
        
        # Générer le rapport final
        self.generate_report(time.time() - start_time)
    
    def generate_report(self, runtime: float) -> None:
        """Générer le rapport final"""
        self.logger.info("=" * 60)
        self.logger.info("📊 RAPPORT FINAL DES TESTS")
        self.logger.info("=" * 60)
        
        total_tests = len(self.results)
        passed_tests = sum(1 for r in self.results if r.passed)
        failed_tests = total_tests - passed_tests
        
        self.logger.info(f"⏱️  Durée d'exécution: {runtime:.1f} secondes")
        self.logger.info(f"📈 Tests réussis: {passed_tests}/{total_tests} ({(passed_tests/total_tests)*100:.1f}%)")
        self.logger.info(f"❌ Tests échoués: {failed_tests}")
        
        if failed_tests > 0:
            self.logger.info("\n🔍 DÉTAILS DES ÉCHECS:")
            for result in self.results:
                if not result.passed:
                    token_info = f" [{result.token_address[:8]}...]" if result.token_address else ""
                    self.logger.info(f"   ❌ {result.test_name}{token_info}: {result.details}")
        
        # Recommandations
        self.logger.info("\n💡 RECOMMANDATIONS:")
        
        if any(r.test_name.startswith('api_accuracy') and not r.passed for r in self.results):
            self.logger.info("   • Vérifier la synchronisation avec les APIs externes")
            self.logger.info("   • Ajuster les intervalles de mise à jour")
        
        if any(r.test_name.startswith('token_history') and not r.passed for r in self.results):
            self.logger.info("   • Vérifier le processus d'historisation")
            self.logger.info("   • Corriger les incohérences tokens <-> tokens_history")
        
        if any(r.test_name == 'data_freshness' and not r.passed for r in self.results):
            self.logger.info("   • Augmenter la fréquence de mise à jour")
            self.logger.info("   • Vérifier que le service de sync fonctionne")
        
        overall_health = (passed_tests / total_tests) * 100
        if overall_health >= 90:
            self.logger.info(f"\n🎉 EXCELLENT: Santé globale du système: {overall_health:.1f}%")
        elif overall_health >= 70:
            self.logger.info(f"\n✅ BON: Santé globale du système: {overall_health:.1f}%")
        elif overall_health >= 50:
            self.logger.info(f"\n⚠️  MOYEN: Santé globale du système: {overall_health:.1f}%")
        else:
            self.logger.info(f"\n🚨 CRITIQUE: Santé globale du système: {overall_health:.1f}%")

def main():
    """Point d'entrée principal"""
    print("🧪 Script de test de cohérence des données tokens")
    print("=" * 50)
    print(f"Base de données: {CONFIG['db_path']}")
    print(f"Taille échantillon API: {CONFIG['test_sample_size']}")
    print(f"Tolérance: {CONFIG['tolerance_percent']}%")
    print("=" * 50)
    
    tester = TokenDataTester(CONFIG['db_path'])
    tester.run_all_tests()
    
    print("\n📝 Logs détaillés sauvegardés dans 'token_test.log'")

if __name__ == "__main__":
    main()