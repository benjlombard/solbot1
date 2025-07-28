#!/usr/bin/env python3
"""
🔍 DexScreener Debug & Analysis Tool
Analyse détaillée du comportement de l'enrichisseur DexScreener
"""

import sqlite3
import json
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import logging
from collections import defaultdict, Counter

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class DexScreenerAnalyzer:
    """Analyseur pour débugger et vérifier le comportement de l'enrichisseur DexScreener"""
    
    def __init__(self, database_path: str = "../tokens.db"):
        self.database_path = database_path
        
    def get_db_connection(self):
        """Créer une connexion à la base de données"""
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def analyze_token_status_distribution(self) -> Dict:
        """Analyser la distribution des statuts des tokens"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Distribution globale des statuts
            cursor.execute('''
                SELECT 
                    COALESCE(status, 'NULL') as status,
                    COUNT(*) as count,
                    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM tokens), 2) as percentage
                FROM tokens 
                GROUP BY status 
                ORDER BY count DESC
            ''')
            
            status_distribution = [dict(row) for row in cursor.fetchall()]
            
            # Évolution des statuts dans les dernières 24h (via snapshots)
            cursor.execute('''
                SELECT 
                    COALESCE(status, 'NULL') as status,
                    COUNT(*) as count
                FROM tokens_hist 
                WHERE snapshot_timestamp > datetime('now', '-24 hours', 'localtime')
                GROUP BY status 
                ORDER BY count DESC
            ''')
            
            recent_status_changes = [dict(row) for row in cursor.fetchall()]
            
            return {
                'current_distribution': status_distribution,
                'recent_changes_24h': recent_status_changes
            }
            
        except sqlite3.Error as e:
            logger.error(f"Erreur analyse statuts: {e}")
            return {}
        finally:
            conn.close()
    
    def analyze_dexscreener_update_frequency(self) -> Dict:
        """Analyser la fréquence des mises à jour DexScreener"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Tokens jamais mis à jour vs mis à jour
            cursor.execute('''
                SELECT 
                    CASE 
                        WHEN dexscreener_last_dexscreener_update IS NULL OR dexscreener_last_dexscreener_update = '' 
                        THEN 'Never Updated'
                        ELSE 'Has Updates'
                    END as update_status,
                    COUNT(*) as count
                FROM tokens 
                GROUP BY update_status
            ''')
            
            update_status = [dict(row) for row in cursor.fetchall()]
            
            # Distribution par ancienneté des dernières mises à jour
            cursor.execute('''
                SELECT 
                    CASE 
                        WHEN dexscreener_last_dexscreener_update IS NULL OR dexscreener_last_dexscreener_update = '' 
                        THEN 'Never'
                        WHEN dexscreener_last_dexscreener_update > datetime('now', '-1 hour', 'localtime') 
                        THEN 'Last Hour'
                        WHEN dexscreener_last_dexscreener_update > datetime('now', '-6 hours', 'localtime') 
                        THEN 'Last 6 Hours'
                        WHEN dexscreener_last_dexscreener_update > datetime('now', '-24 hours', 'localtime') 
                        THEN 'Last 24 Hours'
                        WHEN dexscreener_last_dexscreener_update > datetime('now', '-7 days', 'localtime') 
                        THEN 'Last Week'
                        ELSE 'Older than Week'
                    END as recency,
                    COUNT(*) as count
                FROM tokens 
                GROUP BY recency
                ORDER BY 
                    CASE recency
                        WHEN 'Never' THEN 6
                        WHEN 'Last Hour' THEN 1
                        WHEN 'Last 6 Hours' THEN 2
                        WHEN 'Last 24 Hours' THEN 3
                        WHEN 'Last Week' THEN 4
                        WHEN 'Older than Week' THEN 5
                    END
            ''')
            
            update_recency = [dict(row) for row in cursor.fetchall()]
            
            # Fréquence des mises à jour par token (comptage via snapshots)
            cursor.execute('''
                SELECT 
                    update_count,
                    COUNT(*) as tokens_count
                FROM (
                    SELECT 
                        address,
                        COUNT(*) as update_count
                    FROM tokens_hist 
                    WHERE snapshot_reason = 'before_dexscreener_update'
                    GROUP BY address
                ) 
                GROUP BY update_count
                ORDER BY update_count
            ''')
            
            update_frequency = [dict(row) for row in cursor.fetchall()]
            
            return {
                'update_status': update_status,
                'update_recency': update_recency,
                'update_frequency': update_frequency
            }
            
        except sqlite3.Error as e:
            logger.error(f"Erreur analyse fréquence: {e}")
            return {}
        finally:
            conn.close()
    
    def analyze_recent_enrichment_activity(self, hours: int = 24) -> Dict:
        """Analyser l'activité d'enrichissement récente"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Snapshots créés récemment
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_snapshots,
                    COUNT(DISTINCT address) as unique_tokens,
                    MIN(snapshot_timestamp) as first_snapshot,
                    MAX(snapshot_timestamp) as last_snapshot
                FROM tokens_hist 
                WHERE snapshot_timestamp > datetime('now', '-{} hours', 'localtime')
                AND snapshot_reason = 'before_dexscreener_update'
            '''.format(hours))
            
            snapshot_activity = dict(cursor.fetchone())
            
            # Tokens mis à jour avec succès récemment
            cursor.execute('''
                SELECT 
                    COUNT(*) as successful_updates,
                    COUNT(DISTINCT address) as unique_updated_tokens
                FROM tokens 
                WHERE dexscreener_last_dexscreener_update > datetime('now', '-{} hours', 'localtime')
            '''.format(hours))
            
            successful_updates = dict(cursor.fetchone())
            
            # Changements de statut récents
            cursor.execute('''
                SELECT 
                    status,
                    COUNT(*) as count
                FROM tokens_hist 
                WHERE snapshot_timestamp > datetime('now', '-{} hours', 'localtime')
                GROUP BY status
                ORDER BY count DESC
            '''.format(hours))
            
            status_changes = [dict(row) for row in cursor.fetchall()]
            
            # Top des tokens mis à jour récemment avec leurs métriques
            cursor.execute('''
                SELECT 
                    t.symbol,
                    t.address,
                    t.dexscreener_last_dexscreener_update,
                    t.dexscreener_price_usd,
                    t.dexscreener_volume_24h,
                    t.dexscreener_liquidity_quote,
                    t.status
                FROM tokens t
                WHERE t.dexscreener_last_dexscreener_update > datetime('now', '-{} hours', 'localtime')
                ORDER BY t.dexscreener_last_dexscreener_update DESC
                LIMIT 20
            '''.format(hours))
            
            recent_updates = [dict(row) for row in cursor.fetchall()]
            
            return {
                'snapshot_activity': snapshot_activity,
                'successful_updates': successful_updates,
                'status_changes': status_changes,
                'recent_token_updates': recent_updates
            }
            
        except sqlite3.Error as e:
            logger.error(f"Erreur analyse activité récente: {e}")
            return {}
        finally:
            conn.close()
    
    def analyze_failure_patterns(self) -> Dict:
        """Analyser les patterns d'échecs d'enrichissement"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Tokens avec statut d'échec
            cursor.execute('''
                SELECT 
                    status,
                    COUNT(*) as count,
                    AVG(CAST((julianday('now', 'localtime') - julianday(first_discovered_at)) AS INTEGER)) as avg_age_days
                FROM tokens 
                WHERE status IN ('inactive', 'archived', 'no_dex_data')
                GROUP BY status
                ORDER BY count DESC
            ''')
            
            failure_status = [dict(row) for row in cursor.fetchall()]
            
            # Tokens les plus anciens sans données DexScreener
            cursor.execute('''
                SELECT 
                    symbol,
                    address,
                    first_discovered_at,
                    CAST((julianday('now', 'localtime') - julianday(first_discovered_at)) AS INTEGER) as age_days,
                    status
                FROM tokens 
                WHERE (dexscreener_last_dexscreener_update IS NULL OR dexscreener_last_dexscreener_update = '')
                AND symbol IS NOT NULL 
                AND symbol != 'UNKNOWN'
                ORDER BY first_discovered_at ASC
                LIMIT 20
            ''')
            
            oldest_without_data = [dict(row) for row in cursor.fetchall()]
            
            # Échecs consécutifs par token (via snapshots)
            cursor.execute('''
                SELECT 
                    consecutive_failures,
                    COUNT(*) as token_count
                FROM (
                    SELECT 
                        address,
                        COUNT(*) as consecutive_failures
                    FROM tokens_hist 
                    WHERE snapshot_timestamp > datetime('now', '-7 days', 'localtime')
                    AND (dexscreener_last_dexscreener_update IS NULL OR dexscreener_last_dexscreener_update = '')
                    GROUP BY address
                )
                GROUP BY consecutive_failures
                ORDER BY consecutive_failures
            ''')
            
            consecutive_failures = [dict(row) for row in cursor.fetchall()]
            
            return {
                'failure_status_distribution': failure_status,
                'oldest_without_data': oldest_without_data,
                'consecutive_failures_distribution': consecutive_failures
            }
            
        except sqlite3.Error as e:
            logger.error(f"Erreur analyse échecs: {e}")
            return {}
        finally:
            conn.close()
    
    def analyze_data_quality(self) -> Dict:
        """Analyser la qualité des données DexScreener"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Complétude des données DexScreener
            cursor.execute('''
                SELECT 
                    'price_usd' as field,
                    COUNT(CASE WHEN dexscreener_price_usd > 0 THEN 1 END) as non_zero_count,
                    COUNT(CASE WHEN dexscreener_price_usd IS NOT NULL THEN 1 END) as non_null_count,
                    COUNT(*) as total_count
                FROM tokens 
                WHERE dexscreener_last_dexscreener_update IS NOT NULL 
                AND dexscreener_last_dexscreener_update != ''
                
                UNION ALL
                
                SELECT 
                    'volume_24h' as field,
                    COUNT(CASE WHEN dexscreener_volume_24h > 0 THEN 1 END) as non_zero_count,
                    COUNT(CASE WHEN dexscreener_volume_24h IS NOT NULL THEN 1 END) as non_null_count,
                    COUNT(*) as total_count
                FROM tokens 
                WHERE dexscreener_last_dexscreener_update IS NOT NULL 
                AND dexscreener_last_dexscreener_update != ''
                
                UNION ALL
                
                SELECT 
                    'liquidity_quote' as field,
                    COUNT(CASE WHEN dexscreener_liquidity_quote > 0 THEN 1 END) as non_zero_count,
                    COUNT(CASE WHEN dexscreener_liquidity_quote IS NOT NULL THEN 1 END) as non_null_count,
                    COUNT(*) as total_count
                FROM tokens 
                WHERE dexscreener_last_dexscreener_update IS NOT NULL 
                AND dexscreener_last_dexscreener_update != ''
            ''')
            
            data_completeness = [dict(row) for row in cursor.fetchall()]
            
            # Distribution des valeurs
            cursor.execute('''
                SELECT 
                    'Price Ranges' as metric,
                    CASE 
                        WHEN dexscreener_price_usd = 0 THEN 'Zero'
                        WHEN dexscreener_price_usd < 0.000001 THEN '< $0.000001'
                        WHEN dexscreener_price_usd < 0.001 THEN '< $0.001'
                        WHEN dexscreener_price_usd < 1 THEN '< $1'
                        ELSE '>= $1'
                    END as range_category,
                    COUNT(*) as count
                FROM tokens 
                WHERE dexscreener_last_dexscreener_update IS NOT NULL 
                AND dexscreener_last_dexscreener_update != ''
                GROUP BY range_category
                
                UNION ALL
                
                SELECT 
                    'Volume Ranges' as metric,
                    CASE 
                        WHEN dexscreener_volume_24h = 0 THEN 'Zero'
                        WHEN dexscreener_volume_24h < 100 THEN '< $100'
                        WHEN dexscreener_volume_24h < 1000 THEN '< $1K'
                        WHEN dexscreener_volume_24h < 10000 THEN '< $10K'
                        ELSE '>= $10K'
                    END as range_category,
                    COUNT(*) as count
                FROM tokens 
                WHERE dexscreener_last_dexscreener_update IS NOT NULL 
                AND dexscreener_last_dexscreener_update != ''
                GROUP BY range_category
            ''')
            
            value_distributions = [dict(row) for row in cursor.fetchall()]
            
            return {
                'data_completeness': data_completeness,
                'value_distributions': value_distributions
            }
            
        except sqlite3.Error as e:
            logger.error(f"Erreur analyse qualité: {e}")
            return {}
        finally:
            conn.close()
    
    def check_snapshot_consistency(self) -> Dict:
        """Vérifier la cohérence des snapshots"""
        conn = self.get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Snapshots par jour
            cursor.execute('''
                SELECT 
                    DATE(snapshot_timestamp) as snapshot_date,
                    COUNT(*) as snapshot_count,
                    COUNT(DISTINCT address) as unique_tokens
                FROM tokens_hist 
                WHERE snapshot_timestamp > datetime('now', '-7 days', 'localtime')
                GROUP BY DATE(snapshot_timestamp)
                ORDER BY snapshot_date DESC
            ''')
            
            daily_snapshots = [dict(row) for row in cursor.fetchall()]
            
            # Tokens avec snapshots multiples récents
            cursor.execute('''
                SELECT 
                    address,
                    symbol,
                    COUNT(*) as snapshot_count,
                    MIN(snapshot_timestamp) as first_snapshot,
                    MAX(snapshot_timestamp) as last_snapshot
                FROM tokens_hist th
                JOIN tokens t ON th.address = t.address
                WHERE th.snapshot_timestamp > datetime('now', '-24 hours', 'localtime')
                GROUP BY th.address, symbol
                HAVING COUNT(*) > 1
                ORDER BY snapshot_count DESC
                LIMIT 10
            ''')
            
            multiple_snapshots = [dict(row) for row in cursor.fetchall()]
            
            # Orphan snapshots (snapshots sans token correspondant)
            cursor.execute('''
                SELECT COUNT(*) as orphan_count
                FROM tokens_hist th
                LEFT JOIN tokens t ON th.address = t.address
                WHERE t.address IS NULL
            ''')
            
            orphan_snapshots = dict(cursor.fetchone())
            
            return {
                'daily_snapshots': daily_snapshots,
                'tokens_with_multiple_snapshots': multiple_snapshots,
                'orphan_snapshots': orphan_snapshots
            }
            
        except sqlite3.Error as e:
            logger.error(f"Erreur vérification snapshots: {e}")
            return {}
        finally:
            conn.close()
    
    def generate_comprehensive_report(self, hours: int = 24) -> Dict:
        """Générer un rapport complet"""
        logger.info("🔍 Génération du rapport complet d'analyse DexScreener...")
        
        report = {
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'analysis_period_hours': hours,
            'status_analysis': self.analyze_token_status_distribution(),
            'update_frequency_analysis': self.analyze_dexscreener_update_frequency(),
            'recent_activity': self.analyze_recent_enrichment_activity(hours),
            'failure_patterns': self.analyze_failure_patterns(),
            'data_quality': self.analyze_data_quality(),
            'snapshot_consistency': self.check_snapshot_consistency()
        }
        
        return report
    
    def print_formatted_report(self, report: Dict):
        """Afficher le rapport de manière formatée"""
        print("=" * 80)
        print("🔍 DEXSCREENER ENRICHER - RAPPORT D'ANALYSE DÉTAILLÉ")
        print("=" * 80)
        print(f"📅 Généré le: {report['generated_at']}")
        print(f"⏱️  Période d'analyse: {report['analysis_period_hours']} heures")
        print()
        
        # 1. Distribution des statuts
        print("📊 1. DISTRIBUTION DES STATUTS")
        print("-" * 40)
        if report['status_analysis'].get('current_distribution'):
            for status in report['status_analysis']['current_distribution']:
                print(f"   {status['status']:<15}: {status['count']:>6} tokens ({status['percentage']:>5}%)")
        print()
        
        # 2. Fréquence des mises à jour
        print("🔄 2. FRÉQUENCE DES MISES À JOUR DEXSCREENER")
        print("-" * 50)
        if report['update_frequency_analysis'].get('update_status'):
            for status in report['update_frequency_analysis']['update_status']:
                print(f"   {status['update_status']:<15}: {status['count']:>6} tokens")
        
        print("\n   📈 Ancienneté des dernières mises à jour:")
        if report['update_frequency_analysis'].get('update_recency'):
            for recency in report['update_frequency_analysis']['update_recency']:
                print(f"   {recency['recency']:<20}: {recency['count']:>6} tokens")
        print()
        
        # 3. Activité récente
        print("⚡ 3. ACTIVITÉ RÉCENTE")
        print("-" * 30)
        recent = report['recent_activity']
        if recent.get('snapshot_activity'):
            snap = recent['snapshot_activity']
            print(f"   📸 Snapshots créés: {snap.get('total_snapshots', 0)}")
            print(f"   🎯 Tokens uniques: {snap.get('unique_tokens', 0)}")
            
        if recent.get('successful_updates'):
            updates = recent['successful_updates']
            print(f"   ✅ Mises à jour réussies: {updates.get('successful_updates', 0)}")
            print(f"   🎯 Tokens mis à jour: {updates.get('unique_updated_tokens', 0)}")
        
        if recent.get('recent_token_updates'):
            print(f"\n   🏆 TOP 10 TOKENS MIS À JOUR RÉCEMMENT:")
            for i, token in enumerate(recent['recent_token_updates'][:10], 1):
                symbol = token.get('symbol', 'UNKNOWN')
                price = token.get('dexscreener_price_usd', 0) or 0
                volume = token.get('dexscreener_volume_24h', 0) or 0
                status = token.get('status', 'N/A')
                print(f"   {i:2}. {symbol:<12} | ${price:<12.8f} | Vol: ${volume:<12,.0f} | Status: {status}")
        print()
        
        # 4. Patterns d'échecs
        print("❌ 4. ANALYSE DES ÉCHECS")
        print("-" * 30)
        if report['failure_patterns'].get('failure_status_distribution'):
            for failure in report['failure_patterns']['failure_status_distribution']:
                avg_age = failure.get('avg_age_days', 0) or 0
                print(f"   {failure['status']:<15}: {failure['count']:>6} tokens (âge moyen: {avg_age:.1f}j)")
        
        if report['failure_patterns'].get('consecutive_failures_distribution'):
            print(f"\n   🔄 Distribution des échecs consécutifs:")
            for cf in report['failure_patterns']['consecutive_failures_distribution']:
                print(f"   {cf['consecutive_failures']} échecs: {cf['token_count']} tokens")
        print()
        
        # 5. Qualité des données
        print("📋 5. QUALITÉ DES DONNÉES")
        print("-" * 30)
        if report['data_quality'].get('data_completeness'):
            print("   Complétude des champs (tokens avec données DexScreener):")
            for field in report['data_quality']['data_completeness']:
                field_name = field['field']
                non_zero = field.get('non_zero_count', 0)
                total = field.get('total_count', 1)
                pct = (non_zero / total * 100) if total > 0 else 0
                print(f"   {field_name:<20}: {non_zero:>5}/{total:<5} ({pct:>5.1f}% avec valeurs > 0)")
        print()
        
        # 6. Snapshots
        print("📸 6. COHÉRENCE DES SNAPSHOTS")
        print("-" * 35)
        if report['snapshot_consistency'].get('daily_snapshots'):
            print("   Snapshots par jour (7 derniers jours):")
            for day in report['snapshot_consistency']['daily_snapshots']:
                date = day['snapshot_date']
                count = day['snapshot_count']
                unique = day['unique_tokens']
                print(f"   {date}: {count:>4} snapshots ({unique:>3} tokens uniques)")
        
        orphans = report['snapshot_consistency'].get('orphan_snapshots', {}).get('orphan_count', 0)
        if orphans > 0:
            print(f"\n   ⚠️ Snapshots orphelins: {orphans}")
        print()
        
        print("=" * 80)
        print("✅ RAPPORT TERMINÉ")
        print("=" * 80)

def main():
    """Fonction principale"""
    parser = argparse.ArgumentParser(description="DexScreener Debug & Analysis Tool")
    
    parser.add_argument("--database", default="../tokens.db", help="Chemin vers la base de données")
    parser.add_argument("--hours", type=int, default=24, help="Période d'analyse en heures")
    parser.add_argument("--output", type=str, help="Fichier de sortie JSON (optionnel)")
    parser.add_argument("--format", choices=['console', 'json', 'both'], default='console', 
                       help="Format de sortie")
    
    args = parser.parse_args()
    
    # Créer l'analyseur
    analyzer = DexScreenerAnalyzer(args.database)
    
    try:
        # Générer le rapport
        report = analyzer.generate_comprehensive_report(args.hours)
        
        # Affichage selon le format choisi
        if args.format in ['console', 'both']:
            analyzer.print_formatted_report(report)
        
        if args.format in ['json', 'both'] or args.output:
            output_file = args.output or f"dexscreener_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False, default=str)
            print(f"📄 Rapport JSON sauvegardé: {output_file}")
        
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'analyse: {e}")
        return 1

if __name__ == "__main__":
    exit(main())