#!/usr/bin/env python3
"""
Script pour backfill les bonding_curve_progress manquants avec calculs corrects
"""

import sys
import os
import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import db
from app.config import settings
from app.sutils3 import get_pump_progress

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BondingCurveBackfillerCorrect:
    def __init__(self):
        self.helius_api_key = settings.helius_api_key
        self.success_count = 0
        self.error_count = 0
        self.api_success_count = 0
        self.onchain_success_count = 0
        self.estimated_count = 0
        
    async def backfill_missing_progress(self, limit: int = 100, force_update: bool = False):
        """
        Remplit les bonding_curve_progress manquants avec les calculs corrects
        """
        logger.info("Starting bonding curve progress backfill with correct calculations...")
        
        # Récupérer les tokens sans bonding_curve_progress
        tokens_to_update = self._get_tokens_without_progress(limit, force_update)
        
        if not tokens_to_update:
            logger.info("No tokens found without bonding curve progress")
            return
        
        logger.info(f"Found {len(tokens_to_update)} tokens to update")
        
        # Traiter par batches plus petits pour éviter les timeouts
        batch_size = 3  # Réduit pour les calculs on-chain
        for i in range(0, len(tokens_to_update), batch_size):
            batch = tokens_to_update[i:i + batch_size]
            logger.info(f"Processing batch {i//batch_size + 1}/{(len(tokens_to_update) + batch_size - 1)//batch_size}")
            
            await self._process_batch_correct(batch)
            
            # Pause plus longue entre les batches pour éviter rate limiting
            await asyncio.sleep(3)
        
        logger.info(f"Backfill complete:")
        logger.info(f"  Total success: {self.success_count}")
        logger.info(f"  On-chain method: {self.onchain_success_count}")
        logger.info(f"  API method: {self.api_success_count}")
        logger.info(f"  Estimated: {self.estimated_count}")
        logger.info(f"  Errors: {self.error_count}")
    
    def _get_tokens_without_progress(self, limit: int, force_update: bool = False) -> list:
        """
        Récupère les tokens sans bonding_curve_progress ou à forcer
        """
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                if force_update:
                    # Forcer la mise à jour de tous les tokens récents
                    cursor.execute("""
                        SELECT address, name, symbol, row_created_at, bonding_curve, associated_bonding_curve
                        FROM pump_tokens 
                        WHERE datetime(row_created_at) >= datetime('now','localtime','-7 days')
                        AND (is_blacklisted = 0 OR is_blacklisted IS NULL)
                        ORDER BY row_created_at DESC
                        LIMIT ?
                    """, (limit,))
                else:
                    # Seulement les tokens sans progress
                    cursor.execute("""
                        SELECT address, name, symbol, row_created_at, bonding_curve, associated_bonding_curve
                        FROM pump_tokens 
                        WHERE (bonding_curve_progress IS NULL OR bonding_curve_progress = 0)
                        AND datetime(row_created_at) >= datetime('now','localtime','-7 days')
                        AND (is_blacklisted = 0 OR is_blacklisted IS NULL)
                        ORDER BY row_created_at DESC
                        LIMIT ?
                    """, (limit,))
                
                return [dict(row) for row in cursor.fetchall()]
                
        except Exception as e:
            logger.error(f"Error getting tokens without progress: {e}")
            return []
    
    async def _process_batch_correct(self, batch: list):
        """
        Traite un batch de tokens avec les méthodes correctes
        """
        tasks = []
        
        for token in batch:
            task = self._update_single_token_correct(token)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            token_address = batch[i]['address']
            
            if isinstance(result, Exception):
                logger.error(f"Error processing {token_address}: {result}")
                self.error_count += 1
            elif result:
                self.success_count += 1
            else:
                self.error_count += 1
    
    async def _update_single_token_correct(self, token: dict) -> bool:
        """
        Met à jour un token individuel en utilisant sutils3.
        """
        token_address = token['address']
        token_symbol = token.get('symbol', 'UNK')
        
        try:
            logger.info(f"Processing {token_symbol} ({token_address[:10]}...)")
            
            result = await get_pump_progress(
                token_address,
                helius_api_key=self.helius_api_key
            )
            
            if result and result.get('success'):
                # sutils3 retourne TOUJOURS en fraction (0.0-1.0)
                progress_fraction = result['bonding_curve_progress']
                source = result.get('source', 'unknown')
                
                # NORMALISATION : Stocker TOUJOURS en fraction (0.0-1.0)
                update_payload = result.copy()
                update_payload['bonding_curve_progress'] = progress_fraction  # Garder en fraction
                
                success = self._update_token_progress_enhanced(token_address, update_payload)
                
                if success:
                    logger.info(f"✅ Updated {token_symbol}: {progress_fraction*100:.2f}% (stored as {progress_fraction:.6f} fraction)")
                    
                    if 'pumpfun_api' in source:
                        self.api_success_count += 1
                    elif 'helius' in source:
                        self.onchain_success_count += 1
                    else:
                        self.estimated_count += 1
                    
                    return True
                else:
                    logger.error(f"❌ Failed to update database for {token_symbol}")
                    return False
            
            # Fallback estimation
            logger.warning(f"sutils3 failed for {token_symbol}, using estimation.")
            
            estimated_progress_percent = self._estimate_progress_by_age_enhanced(token)
            # Convertir l'estimation en fraction pour cohérence
            estimated_progress_fraction = estimated_progress_percent / 100.0
            
            success = self._update_token_progress_simple(token_address, estimated_progress_fraction, 'local_estimation')
            
            if success:
                logger.info(f"⚠️ Updated {token_symbol}: {estimated_progress_percent:.2f}% (stored as {estimated_progress_fraction:.6f} fraction)")
                self.estimated_count += 1
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Critical error for {token_address}: {e}")
            return False
    
    def _estimate_progress_by_age_enhanced(self, token: dict) -> float:
        """
        Estime le progrès basé sur l'âge du token avec heuristiques améliorées
        """
        try:
            created_at = datetime.fromisoformat(token['row_created_at'])
            age_hours = (datetime.now() - created_at).total_seconds() / 3600
            
            # Heuristiques basées sur l'observation des patterns Pump.fun
            if age_hours < 0.5:
                # Très récent: croissance rapide possible
                return min(15.0, age_hours * 20)
            elif age_hours < 2:
                # Première phase: croissance modérée
                return min(25.0, 15 + (age_hours - 0.5) * 5)
            elif age_hours < 12:
                # Phase établie: croissance lente
                return min(35.0, 25 + (age_hours - 2) * 1)
            elif age_hours < 72:  # 3 jours
                # Phase mature: très lente
                return min(45.0, 35 + (age_hours - 12) * 0.2)
            else:
                # Vieux tokens: plateau
                return min(50.0, 40.0)
            
        except Exception as e:
            logger.error(f"Error estimating progress: {e}")
            return 2.0  # Valeur par défaut très conservative
    
    def _update_token_progress_enhanced(self, token_address: str, result: dict) -> bool:
        """
        Met à jour le token avec toutes les données de bonding curve
        """
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Préparer les données à mettre à jour
                update_data = {
                    'bonding_curve_progress': result['bonding_curve_progress'],
                    'last_updated_pumpfun': datetime.now().isoformat()
                }
                
                # Ajouter les données supplémentaires si disponibles
                if 'virtual_sol_reserves' in result:
                    update_data['virtual_sol_reserves'] = result['virtual_sol_reserves']
                if 'virtual_token_reserves' in result:
                    update_data['virtual_token_reserves'] = result['virtual_token_reserves']
                if 'market_cap' in result and result['market_cap']:
                    update_data['usd_market_cap'] = result['market_cap']
                
                # Construire la requête dynamiquement
                set_clause = ', '.join([f"{key} = ?" for key in update_data.keys()])
                values = list(update_data.values()) + [token_address]
                
                cursor.execute(f"""
                    UPDATE pump_tokens 
                    SET {set_clause}
                    WHERE address = ?
                """, values)
                
                if cursor.rowcount > 0:
                    conn.commit()
                    return True
                else:
                    logger.warning(f"No rows updated for {token_address}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error updating database for {token_address}: {e}")
            return False
    
    def _update_token_progress_simple(self, token_address: str, progress_fraction: float, source: str) -> bool:
        """
        Met à jour seulement le progrès de bonding curve EN FRACTION (0.0-1.0)
        """
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Stockage normalisé : TOUJOURS en fraction
                cursor.execute("""
                    UPDATE pump_tokens 
                    SET bonding_curve_progress = ?, 
                        last_updated_pumpfun = ?
                    WHERE address = ?
                """, (progress_fraction, datetime.now().isoformat(), token_address))
                
                if cursor.rowcount > 0:
                    conn.commit()
                    return True
                else:
                    logger.warning(f"No rows updated for {token_address}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error updating database for {token_address}: {e}")
            return False
    
    def get_backfill_stats_detailed(self) -> dict:
        """
        Retourne les statistiques détaillées après backfill
        """
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Stats globales
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_tokens,
                        COUNT(bonding_curve_progress) as tokens_with_progress,
                        AVG(bonding_curve_progress) as avg_progress,
                        MIN(bonding_curve_progress) as min_progress,
                        MAX(bonding_curve_progress) as max_progress,
                        COUNT(CASE WHEN bonding_curve_progress > 0 THEN 1 END) as positive_progress,
                        COUNT(CASE WHEN bonding_curve_progress >= 50 THEN 1 END) as high_progress
                    FROM pump_tokens
                    WHERE datetime(row_created_at) >= datetime('now','localtime','-7 days')
                    AND (is_blacklisted = 0 OR is_blacklisted IS NULL)
                """)
                
                stats = dict(cursor.fetchone())
                
                # Distribution détaillée
                cursor.execute("""
                    SELECT 
                        CASE 
                            WHEN bonding_curve_progress IS NULL THEN 'NULL'
                            WHEN bonding_curve_progress = 0 THEN '0%'
                            WHEN bonding_curve_progress < 1 THEN '0-1%'
                            WHEN bonding_curve_progress < 5 THEN '1-5%'
                            WHEN bonding_curve_progress < 10 THEN '5-10%'
                            WHEN bonding_curve_progress < 25 THEN '10-25%'
                            WHEN bonding_curve_progress < 50 THEN '25-50%'
                            WHEN bonding_curve_progress < 75 THEN '50-75%'
                            WHEN bonding_curve_progress < 90 THEN '75-90%'
                            WHEN bonding_curve_progress < 100 THEN '90-99%'
                            ELSE '100%'
                        END as range_group,
                        COUNT(*) as count
                    FROM pump_tokens
                    WHERE datetime(row_created_at) >= datetime('now', 'localtime','-7 days')
                    AND (is_blacklisted = 0 OR is_blacklisted IS NULL)
                    GROUP BY range_group
                    ORDER BY count DESC
                """)
                
                distribution = {row['range_group']: row['count'] for row in cursor.fetchall()}
                
                # Stats par période
                cursor.execute("""
                    SELECT 
                        CASE 
                            WHEN datetime(row_created_at) >= datetime('now','localtime', '-1 hour') THEN 'Last hour'
                            WHEN datetime(row_created_at) >= datetime('now','localtime', '-6 hours') THEN 'Last 6 hours'
                            WHEN datetime(row_created_at) >= datetime('now','localtime','-24 hours') THEN 'Last 24 hours'
                            ELSE 'Older (within 7d)'
                        END as period,
                        COUNT(*) as total,
                        COUNT(bonding_curve_progress) as with_progress,
                        AVG(bonding_curve_progress) as avg_progress
                    FROM pump_tokens
                    WHERE created_at >= datetime('now', '-7 days')
                    AND (is_blacklisted = 0 OR is_blacklisted IS NULL)
                    GROUP BY period
                    ORDER BY total DESC
                """)
                
                by_period = {}
                for row in cursor.fetchall():
                    by_period[row['period']] = {
                        'total': row['total'],
                        'with_progress': row['with_progress'],
                        'avg_progress': row['avg_progress']
                    }
                
                return {
                    'global_stats': stats,
                    'distribution': distribution,
                    'by_period': by_period,
                    'backfill_results': {
                        'total_success': self.success_count,
                        'onchain_success': self.onchain_success_count,
                        'api_success': self.api_success_count,
                        'estimated': self.estimated_count,
                        'errors': self.error_count
                    }
                }
                
        except Exception as e:
            logger.error(f"Error getting backfill stats: {e}")
            return {}
    
    async def validate_random_sample(self, sample_size: int = 5):
        """
        Valide les résultats sur un échantillon aléatoire
        """
        logger.info(f"🧪 Validating results on random sample of {sample_size} tokens...")
        
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT address, symbol, bonding_curve_progress
                    FROM pump_tokens 
                    WHERE bonding_curve_progress IS NOT NULL 
                    AND bonding_curve_progress > 0
                    AND datetime(row_created_at) >= datetime('now','localtime', '-24 hours')
                    AND (is_blacklisted = 0 OR is_blacklisted IS NULL)
                    ORDER BY RANDOM()
                    LIMIT ?
                """, (sample_size,))
                
                sample_tokens = cursor.fetchall()
                
                if not sample_tokens:
                    logger.warning("No tokens found for validation")
                    return
                
                logger.info("Validating sample tokens:")
                
                for token in sample_tokens:
                    token_address = token['address']
                    db_progress = token['bonding_curve_progress']
                    symbol = token['symbol'] or 'UNK'
                    
                    logger.info(f"\n🔍 Validating {symbol} ({token_address[:10]}...):")
                    logger.info(f"  DB progress: {db_progress}%")
                    
                    # Re-calculer avec la méthode correcte
                    fresh_result = await get_pump_progress_correct(
                        token_address, None, None, self.helius_api_key
                    )
                    
                    if fresh_result and fresh_result.get('success'):
                        fresh_progress = fresh_result['bonding_curve_progress']
                        source = fresh_result.get('source', 'unknown')
                        diff = abs(fresh_progress - db_progress)
                        
                        logger.info(f"  Fresh calculation: {fresh_progress}% (source: {source})")
                        logger.info(f"  Difference: {diff:.2f}%")
                        
                        if diff < 1.0:
                            logger.info(f"  ✅ Validation passed (diff < 1%)")
                        elif diff < 5.0:
                            logger.warning(f"  ⚠️ Minor difference (diff < 5%)")
                        else:
                            logger.error(f"  ❌ Large difference (diff >= 5%)")
                    else:
                        logger.error(f"  ❌ Fresh calculation failed")
                    
                    # Pause entre les validations
                    await asyncio.sleep(2)
                
        except Exception as e:
            logger.error(f"Error during validation: {e}")

async def main():
    """
    Point d'entrée principal
    """
    logger.info("🚀 Starting bonding curve progress backfill with CORRECT calculations")
    
    backfiller = BondingCurveBackfillerCorrect()
    
    try:
        # Arguments de la ligne de commande
        import argparse
        parser = argparse.ArgumentParser(description="Backfill bonding curve progress")
        parser.add_argument("--limit", type=int, default=100, help="Number of tokens to process")
        parser.add_argument("--force", action="store_true", help="Force update all recent tokens")
        parser.add_argument("--validate", action="store_true", help="Validate results on sample")
        parser.add_argument("--test", type=str, help="Test calculation on specific token address")
        
        args = parser.parse_args()
        
        if args.test:
            # Mode test sur un token spécifique
            logger.info(f"🧪 Testing calculation for {args.test}")
            
            # sutils3 a sa propre fonction de test
            from app.sutils3 import test_optimized_version
            result = await test_optimized_version(args.test, backfiller.helius_api_key)
            
            # La fonction de test affiche déjà des logs détaillés.
            # On peut ajouter un résumé ici si on veut.
            if result and result.get('success'):
                progress_percent = result['bonding_curve_progress'] * 100
                logger.info(f"✅ Test complete. Final progress: {progress_percent:.2f}% via {result.get('source')}")
            else:
                logger.error("❌ Test failed or returned no data.")
            
            return
        
        # Exécuter le backfill
        await backfiller.backfill_missing_progress(
            limit=args.limit, 
            force_update=args.force
        )
        
        # Validation optionnelle
        if args.validate:
            await backfiller.validate_random_sample()
        
        # Afficher les statistiques
        stats = backfiller.get_backfill_stats_detailed()
        if stats:
            logger.info("\n📊 Detailed Backfill Statistics:")
            logger.info("=" * 50)
            
            global_stats = stats['global_stats']

            
            if global_stats['avg_progress'] is not None:
                global_stats['avg_progress'] = float(global_stats['avg_progress'])
            if global_stats['min_progress'] is not None:
                global_stats['min_progress'] = float(global_stats['min_progress'])
            if global_stats['max_progress'] is not None:
                global_stats['max_progress'] = float(global_stats['max_progress'])

            # Et pour by_period aussi
            for period_stats in stats['by_period'].values():
                if period_stats['avg_progress'] is not None:
                    period_stats['avg_progress'] = float(period_stats['avg_progress'])

            logger.info(f"Global stats (7d):")
            logger.info(f"  Total tokens: {global_stats['total_tokens']}")
            logger.info(f"  With progress: {global_stats['tokens_with_progress']}")
            completion_pct = (global_stats['tokens_with_progress'] / global_stats['total_tokens'] * 100) if global_stats['total_tokens'] > 0 else 0
            logger.info(f"  Completion rate: {completion_pct:.1f}%")
            if global_stats['avg_progress'] is not None:
                logger.info(f"  Average progress: {global_stats['avg_progress']:.2f}%")
            else:
                logger.info("  Average progress: N/A")

            if global_stats['min_progress'] is not None and global_stats['max_progress'] is not None:
                logger.info(f"  Min/Max progress: {global_stats['min_progress']:.1f}% / {global_stats['max_progress']:.1f}%")
            else:
                logger.info("  Min/Max progress: N/A")
            
            logger.info(f"\nBackfill results:")
            results = stats['backfill_results']
            logger.info(f"  Total success: {results['total_success']}")
            logger.info(f"  On-chain method: {results['onchain_success']}")
            logger.info(f"  API method: {results['api_success']}")
            logger.info(f"  Estimated: {results['estimated']}")
            logger.info(f"  Errors: {results['errors']}")
            
            logger.info(f"\nProgress distribution:")
            for range_name, count in stats['distribution'].items():
                logger.info(f"  {range_name}: {count} tokens")
            
            logger.info(f"\nBy time period:")
            for period, period_stats in stats['by_period'].items():
                total = period_stats['total']
                with_progress = period_stats['with_progress']
                avg = period_stats['avg_progress']
                pct = (with_progress / total * 100) if total > 0 else 0
                if avg is not None:
                    logger.info(f"  {period}: {with_progress}/{total} ({pct:.1f}%) - Avg: {avg:.2f}%")
                else:
                    logger.info(f"  {period}: {with_progress}/{total} ({pct:.1f}%) - Avg: N/A")
        
        logger.info("\n✅ Backfill completed successfully!")
        logger.info("💡 To validate results, run with --validate flag")
        logger.info("🧪 To test specific token, run with --test TOKEN_ADDRESS")
        
    except KeyboardInterrupt:
        logger.info("\n👋 Backfill interrupted by user")
    except Exception as e:
        logger.error(f"❌ Backfill failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())