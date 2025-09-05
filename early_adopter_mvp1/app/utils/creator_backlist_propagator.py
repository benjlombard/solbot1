#!/usr/bin/env python3
"""
Script pour propager le blacklistage à tous les tokens d'un créateur
Si un créateur a au moins un token blacklisté, blackliste tous ses tokens
"""

import sys
import os
import logging
from datetime import datetime
from typing import Set, Dict, List

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CreatorBlacklistPropagator:
    def __init__(self):
        self.blacklisted_creators: Set[str] = set()
        self.creator_tokens: Dict[str, List[str]] = {}
        self.tokens_blacklisted = 0
        self.creators_affected = 0
        
    def analyze_creators(self) -> Dict:
        """
        Analyse tous les créateurs et leurs tokens pour identifier ceux à blacklister
        """
        logger.info("🔍 Analyzing creators and their tokens...")
        
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Récupérer tous les tokens avec créateur et statut blacklist
                cursor.execute("""
                    SELECT creator, address, is_blacklisted, name, symbol
                    FROM pump_tokens
                    WHERE creator IS NOT NULL
                    ORDER BY creator
                """)
                
                tokens = cursor.fetchall()
                
                if not tokens:
                    logger.warning("No tokens found in database")
                    return {}
                
                logger.info(f"Found {len(tokens)} tokens to analyze")
                
                # Grouper par créateur
                creator_data = {}
                
                for token in tokens:
                    creator = token['creator']
                    address = token['address']
                    is_blacklisted = bool(token['is_blacklisted'])
                    name = token['name'] or 'Unknown'
                    symbol = token['symbol'] or 'UNK'
                    
                    if creator not in creator_data:
                        creator_data[creator] = {
                            'tokens': [],
                            'blacklisted_tokens': [],
                            'has_blacklisted': False
                        }
                    
                    token_info = {
                        'address': address,
                        'name': name,
                        'symbol': symbol,
                        'is_blacklisted': is_blacklisted
                    }
                    
                    creator_data[creator]['tokens'].append(token_info)
                    
                    if is_blacklisted:
                        creator_data[creator]['blacklisted_tokens'].append(token_info)
                        creator_data[creator]['has_blacklisted'] = True
                        self.blacklisted_creators.add(creator)
                
                # Identifier les créateurs à traiter
                creators_to_blacklist = {}
                
                for creator, data in creator_data.items():
                    if data['has_blacklisted']:
                        non_blacklisted = [t for t in data['tokens'] if not t['is_blacklisted']]
                        
                        if non_blacklisted:
                            creators_to_blacklist[creator] = {
                                'total_tokens': len(data['tokens']),
                                'already_blacklisted': len(data['blacklisted_tokens']),
                                'to_blacklist': len(non_blacklisted),
                                'tokens_to_blacklist': non_blacklisted,
                                'reason_token': data['blacklisted_tokens'][0]  # Premier token blacklisté comme raison
                            }
                
                logger.info(f"📊 Analysis Results:")
                logger.info(f"   Total creators: {len(creator_data)}")
                logger.info(f"   Creators with blacklisted tokens: {len(self.blacklisted_creators)}")
                logger.info(f"   Creators needing propagation: {len(creators_to_blacklist)}")
                
                return creators_to_blacklist
                
        except Exception as e:
            logger.error(f"Error analyzing creators: {e}")
            return {}
    
    def preview_changes(self, creators_to_blacklist: Dict) -> None:
        """
        Affiche un aperçu des changements qui seront effectués
        """
        if not creators_to_blacklist:
            logger.info("✅ No changes needed - all tokens properly blacklisted")
            return
        
        logger.info("\n📋 PREVIEW OF CHANGES:")
        logger.info("=" * 80)
        
        total_tokens_to_blacklist = 0
        
        for i, (creator, data) in enumerate(creators_to_blacklist.items(), 1):
            reason_token = data['reason_token']
            tokens_to_blacklist = data['tokens_to_blacklist']
            
            logger.info(f"\n{i}. Creator: {creator[:20]}...")
            logger.info(f"   Reason: Token '{reason_token['symbol']}' ({reason_token['address'][:10]}...) is blacklisted")
            logger.info(f"   Total tokens: {data['total_tokens']}")
            logger.info(f"   Already blacklisted: {data['already_blacklisted']}")
            logger.info(f"   Will blacklist: {data['to_blacklist']}")
            
            if len(tokens_to_blacklist) <= 5:
                # Afficher tous si <= 5 tokens
                for token in tokens_to_blacklist:
                    logger.info(f"     → {token['symbol']} ({token['address'][:10]}...)")
            else:
                # Afficher les 3 premiers + compteur
                for token in tokens_to_blacklist[:3]:
                    logger.info(f"     → {token['symbol']} ({token['address'][:10]}...)")
                logger.info(f"     → ... and {len(tokens_to_blacklist) - 3} more tokens")
            
            total_tokens_to_blacklist += data['to_blacklist']
        
        logger.info(f"\n📊 SUMMARY:")
        logger.info(f"   Creators affected: {len(creators_to_blacklist)}")
        logger.info(f"   Total tokens to blacklist: {total_tokens_to_blacklist}")
    
    def debug_blacklist_status(self, sample_addresses: list = None) -> None:
        """
        Debug: Affiche le statut actuel des blacklists
        """
        logger.info("🔍 DEBUG: Current blacklist status")
        
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                if sample_addresses:
                    # Vérifier des adresses spécifiques
                    placeholders = ','.join(['?' for _ in sample_addresses])
                    cursor.execute(f"""
                        SELECT address, symbol, creator, is_blacklisted, updated_at
                        FROM pump_tokens 
                        WHERE address IN ({placeholders})
                        ORDER BY creator, address
                    """, sample_addresses)
                else:
                    # Échantillon général
                    cursor.execute("""
                        SELECT address, symbol, creator, is_blacklisted, updated_at
                        FROM pump_tokens 
                        WHERE creator IN (
                            SELECT creator FROM pump_tokens 
                            WHERE is_blacklisted = 1 
                            GROUP BY creator 
                            LIMIT 3
                        )
                        ORDER BY creator, is_blacklisted DESC, address
                        LIMIT 20
                    """)
                
                results = cursor.fetchall()
                
                logger.info("Sample blacklist status:")
                current_creator = None
                for row in results:
                    address = row[0]
                    symbol = row[1] or 'UNK'
                    creator = row[2]
                    is_blacklisted = row[3]
                    updated_at = row[4]
                    
                    if creator != current_creator:
                        logger.info(f"\n👤 Creator: {creator[:20]}...")
                        current_creator = creator
                    
                    status_emoji = "🚫" if is_blacklisted == 1 else "✅"
                    logger.info(f"   {status_emoji} {symbol} ({address[:10]}...) = {is_blacklisted} (updated: {updated_at})")
                
                # Stats globales
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total,
                        COUNT(CASE WHEN is_blacklisted = 1 THEN 1 END) as blacklisted,
                        COUNT(CASE WHEN is_blacklisted = 0 OR is_blacklisted IS NULL THEN 1 END) as not_blacklisted
                    FROM pump_tokens
                """)
                
                stats = cursor.fetchone()
                logger.info(f"\n📊 Global stats:")
                logger.info(f"   Total tokens: {stats[0]}")
                logger.info(f"   Blacklisted (=1): {stats[1]}")
                logger.info(f"   Not blacklisted (=0/NULL): {stats[2]}")
                
        except Exception as e:
            logger.error(f"Error in debug: {e}")

    def execute_blacklist_propagation(self, creators_to_blacklist: Dict, dry_run: bool = True) -> bool:
        """
        Exécute la propagation du blacklistage avec UPDATE SQL direct
        """
        if not creators_to_blacklist:
            logger.info("✅ No changes to execute")
            return True
        
        if dry_run:
            logger.info("\n🧪 DRY RUN MODE - No actual changes will be made")
        else:
            logger.info("\n🚀 EXECUTING BLACKLIST PROPAGATION")
        
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                for creator, data in creators_to_blacklist.items():
                    tokens_to_blacklist = data['tokens_to_blacklist']
                    
                    logger.info(f"\nProcessing creator {creator[:20]}... ({len(tokens_to_blacklist)} tokens)")
                    
                    if not dry_run:
                        # Méthode 1: UPDATE direct avec SQL
                        token_addresses = [token['address'] for token in tokens_to_blacklist]
                        placeholders = ','.join(['?' for _ in token_addresses])
                        
                        sql = f"""
                            UPDATE pump_tokens 
                            SET is_blacklisted = 1, 
                                updated_at = ?
                            WHERE address IN ({placeholders})
                        """
                        
                        params = [datetime.now().isoformat()] + token_addresses
                        
                        logger.info(f"   Executing SQL: {sql}")
                        logger.info(f"   Parameters: {len(token_addresses)} addresses")
                        
                        cursor.execute(sql, params)
                        
                        # Vérifier combien de lignes ont été mises à jour
                        updated_rows = cursor.rowcount
                        logger.info(f"   ✅ Updated {updated_rows} rows in database")
                        
                        if updated_rows != len(tokens_to_blacklist):
                            logger.warning(f"   ⚠️ Expected {len(tokens_to_blacklist)} updates, got {updated_rows}")
                        
                        # Validation immédiate
                        validation_sql = f"""
                            SELECT address, is_blacklisted 
                            FROM pump_tokens 
                            WHERE address IN ({placeholders})
                        """
                        
                        cursor.execute(validation_sql, token_addresses)
                        validation_results = cursor.fetchall()
                        
                        for result in validation_results:
                            address = result[0]
                            is_blacklisted = result[1]
                            token_symbol = next((t['symbol'] for t in tokens_to_blacklist if t['address'] == address), 'UNK')
                            
                            if is_blacklisted == 1:
                                logger.info(f"     ✅ Verified {token_symbol} ({address[:10]}...) = blacklisted")
                            else:
                                logger.error(f"     ❌ FAILED {token_symbol} ({address[:10]}...) = {is_blacklisted}")
                        
                        self.tokens_blacklisted += len(tokens_to_blacklist)
                        
                    else:
                        # Mode dry run - juste afficher ce qui serait fait
                        for token in tokens_to_blacklist:
                            logger.info(f"   🧪 Would blacklist {token['symbol']} ({token['address'][:10]}...)")
                            self.tokens_blacklisted += 1
                    
                    self.creators_affected += 1
                
                if not dry_run:
                    # Commit toutes les changes
                    conn.commit()
                    logger.info(f"\n✅ All changes committed to database!")
                    
                    # Validation globale finale
                    cursor.execute("""
                        SELECT COUNT(*) FROM pump_tokens WHERE is_blacklisted = 1
                    """)
                    total_blacklisted = cursor.fetchone()[0]
                    logger.info(f"📊 Total blacklisted tokens in database: {total_blacklisted}")
                    
                else:
                    logger.info(f"\n🧪 Dry run completed - no changes made")
                
                logger.info(f"📊 Final Results:")
                logger.info(f"   Creators processed: {self.creators_affected}")
                logger.info(f"   Tokens blacklisted: {self.tokens_blacklisted}")
                
                return True
                
        except Exception as e:
            logger.error(f"Error executing blacklist propagation: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_blacklist_statistics(self) -> Dict:
        """
        Retourne les statistiques après propagation
        """
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Stats globales
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_tokens,
                        COUNT(CASE WHEN is_blacklisted = 1 THEN 1 END) as blacklisted_tokens,
                        COUNT(DISTINCT creator) as total_creators
                    FROM pump_tokens
                    WHERE creator IS NOT NULL
                """)
                
                global_stats = dict(cursor.fetchone())
                
                # Stats par créateur
                cursor.execute("""
                    SELECT 
                        COUNT(CASE WHEN is_blacklisted = 1 THEN 1 END) as blacklisted_creators_count
                    FROM (
                        SELECT creator, MAX(is_blacklisted) as has_blacklisted
                        FROM pump_tokens
                        WHERE creator IS NOT NULL
                        GROUP BY creator
                    ) creator_summary
                    WHERE has_blacklisted = 1
                """)
                
                blacklisted_creators_count = cursor.fetchone()[0]
                
                # Distribution des tokens par créateur blacklisté
                cursor.execute("""
                    SELECT 
                        creator,
                        COUNT(*) as total_tokens,
                        COUNT(CASE WHEN is_blacklisted = 1 THEN 1 END) as blacklisted_tokens
                    FROM pump_tokens
                    WHERE creator IN (
                        SELECT creator
                        FROM pump_tokens
                        WHERE is_blacklisted = 1 AND creator IS NOT NULL
                        GROUP BY creator
                    )
                    GROUP BY creator
                    ORDER BY total_tokens DESC
                    LIMIT 10
                """)
                
                top_blacklisted_creators = [dict(row) for row in cursor.fetchall()]
                
                return {
                    'global_stats': global_stats,
                    'blacklisted_creators_count': blacklisted_creators_count,
                    'top_blacklisted_creators': top_blacklisted_creators,
                    'propagation_results': {
                        'creators_affected': self.creators_affected,
                        'tokens_blacklisted': self.tokens_blacklisted
                    }
                }
                
        except Exception as e:
            logger.error(f"Error getting blacklist statistics: {e}")
            return {}
    
    def validate_propagation(self) -> bool:
        """
        Valide que la propagation a été correctement effectuée
        """
        logger.info("🧪 Validating blacklist propagation...")
        
        try:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                
                # Vérifier s'il reste des créateurs avec des tokens partiellement blacklistés
                cursor.execute("""
                    SELECT 
                        creator,
                        COUNT(*) as total_tokens,
                        COUNT(CASE WHEN is_blacklisted = 1 THEN 1 END) as blacklisted_tokens
                    FROM pump_tokens
                    WHERE creator IS NOT NULL
                    GROUP BY creator
                    HAVING COUNT(CASE WHEN is_blacklisted = 1 THEN 1 END) > 0
                       AND COUNT(CASE WHEN is_blacklisted = 1 THEN 1 END) < COUNT(*)
                """)
                
                inconsistent_creators = cursor.fetchall()
                
                if inconsistent_creators:
                    logger.warning(f"⚠️ Found {len(inconsistent_creators)} creators with partial blacklisting:")
                    for creator in inconsistent_creators:
                        logger.warning(f"   {creator['creator'][:20]}...: {creator['blacklisted_tokens']}/{creator['total_tokens']} blacklisted")
                    return False
                else:
                    logger.info("✅ Validation passed - all creators have consistent blacklist status")
                    return True
                    
        except Exception as e:
            logger.error(f"Error validating propagation: {e}")
            return False

def main():
    """
    Point d'entrée principal
    """
    logger.info("🚀 Creator Blacklist Propagator")
    logger.info("=" * 50)
    
    propagator = CreatorBlacklistPropagator()
    
    try:
        # Arguments de ligne de commande
        import argparse
        parser = argparse.ArgumentParser(description="Propagate blacklist status to all tokens of blacklisted creators")
        parser.add_argument("--execute", action="store_true", help="Execute changes (default: dry run)")
        parser.add_argument("--stats-only", action="store_true", help="Only show statistics")
        parser.add_argument("--validate", action="store_true", help="Validate current propagation state")
        parser.add_argument("--debug", action="store_true", help="Show debug info about current blacklist status")

        args = parser.parse_args()
        
        if args.debug:
            # Mode debug
            propagator.debug_blacklist_status()
            return

        if args.validate:
            # Mode validation seulement
            propagator.validate_propagation()
            return
        
        if args.stats_only:
            # Mode statistiques seulement
            stats = propagator.get_blacklist_statistics()
            if stats:
                logger.info("\n📊 Current Blacklist Statistics:")
                logger.info("=" * 40)
                global_stats = stats['global_stats']
                logger.info(f"Total tokens: {global_stats['total_tokens']}")
                logger.info(f"Blacklisted tokens: {global_stats['blacklisted_tokens']}")
                logger.info(f"Total creators: {global_stats['total_creators']}")
                logger.info(f"Creators with blacklisted tokens: {stats['blacklisted_creators_count']}")
                
                pct_blacklisted = (global_stats['blacklisted_tokens'] / global_stats['total_tokens']) * 100
                logger.info(f"Blacklist rate: {pct_blacklisted:.2f}%")
            return
        
        # 1. Analyser les créateurs
        creators_to_blacklist = propagator.analyze_creators()
        
        if not creators_to_blacklist:
            logger.info("✅ All creators already have consistent blacklist status!")
            return
        
        # 2. Aperçu des changements
        propagator.preview_changes(creators_to_blacklist)
        
        # 3. Confirmation utilisateur si mode exécution
        if args.execute:
            print(f"\n⚠️  WARNING: This will blacklist {sum(data['to_blacklist'] for data in creators_to_blacklist.values())} tokens!")
            confirm = input("Are you sure you want to proceed? (yes/no): ").strip().lower()
            
            if confirm not in ['yes', 'y']:
                logger.info("👋 Operation cancelled by user")
                return
        
        # 4. Exécuter (ou dry run)
        success = propagator.execute_blacklist_propagation(
            creators_to_blacklist, 
            dry_run=not args.execute
        )
        
        if success:
            # 5. Afficher les statistiques finales
            stats = propagator.get_blacklist_statistics()
            if stats:
                logger.info("\n📊 Final Statistics:")
                logger.info("=" * 30)
                global_stats = stats['global_stats']
                logger.info(f"Total tokens: {global_stats['total_tokens']}")
                logger.info(f"Blacklisted tokens: {global_stats['blacklisted_tokens']}")
                
                pct_blacklisted = (global_stats['blacklisted_tokens'] / global_stats['total_tokens']) * 100
                logger.info(f"Blacklist rate: {pct_blacklisted:.2f}%")
            
            # 6. Validation finale si exécution réelle
            if args.execute:
                propagator.validate_propagation()
        
        if not args.execute:
            logger.info("\n💡 To execute changes, run with --execute flag")
            logger.info("💡 To see current stats only, run with --stats-only flag")
            logger.info("💡 To validate current state, run with --validate flag")
        
    except KeyboardInterrupt:
        logger.info("\n👋 Operation interrupted by user")
    except Exception as e:
        logger.error(f"❌ Script failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()